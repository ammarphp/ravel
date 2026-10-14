"""CLI worker launch adapter: Claude Code, Codex and Gemini CLI as sandboxed tool-using workers.

``prepare_launch(rundir, spec, workspace)`` returns the trusted launch descriptor that
``agent_worker.launch`` hands to its supervisor, with exactly the keys ``argv``,
``transport``, ``model``, ``pass_env_names``, ``read_paths``, ``allowed_actions`` and
``forbidden_sources``. Everything in it is built here, in code:

- the route comes from ``transport_registry.select`` over the spec's preference list and
  the run's ``inputs/agent_preferences.json``, and must be a ``cli-worker``; a one-shot or
  any other kind is refused, never used as a fallback;
- the argv is the declaration's ``argv_template`` filled with the selected model and
  effort, the code-owned final-record schema and the broker MCP configuration from the
  declaration's ``worker_surface.mcp`` row (``ravel work mcp`` over the card's toolbelt);
- the executable is the absolute path of a current probe whose sha256 still matches;
- the CLI's configuration home is either a fresh per-worker directory beside the workspace
  (``<attempt>.cli-home``, removed after the child) or, for the Claude login route, a
  dedicated login-only ``CLAUDE_CONFIG_DIR`` that is checked to hold no instructions,
  skills, agents, hooks or installed plugins, and settings with display keys only (the
  account-synced ``skills/synced`` and ``plugins/synced`` folders every login creates are
  admitted: the launch flags load neither);
- Claude-family CLIs list ``USER`` and ``LOGNAME`` in ``pass_env_names``; the supervisor sets
  both from the password database (the CLI reads its login with ``security -a $USER``);
- Claude-family CLIs get ``CLAUDE_CODE_TMPDIR`` and ``TMPDIR`` set to the worker's own
  ``scratch/tmp`` (the CLI ignores ``TMPDIR`` for its own temporary directory);
- on macOS, Claude-family CLIs get ``HOME`` set to an adapter-owned ``<attempt>.home`` whose
  only entry is ``Library/Keychains``, a link to the account's login keychain directory (the
  CLI finds its stored login there); the sandbox reads that directory and never writes it;
- the toolbelt the broker enforces is pinned by its manifest digest in the descriptor;
- native tools are off where the CLI allows it: Claude runs with no built-in tools and
  Codex with a read-only sandbox, so a native write is refused; Gemini cannot turn its
  native tools off, and nothing it writes natively is credited (only broker output pins are);
- the prompt is written to worker custody with a complete audit record and reaches the
  CLI on standard input (never in argv).

``observe`` parses the CLI's own JSON output after the child exits, from the copy the
supervisor captured through a pipe into custody (never a file in the worker's workspace):
the final record, session id, observed model, tokens, turns and cost go into the receipt,
and turn and cost limits are enforced there. An unparseable envelope or an exceeded limit
fails the worker.

Refusals raise ``LaunchRefused`` naming each missing item; the dispatcher writes a
``refused`` receipt and starts nothing.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

from .. import broker, sandbox, transport_registry as tr
from ..state_io import atomic_json, read_json

DESCRIPTOR_KEYS = ('argv', 'transport', 'model', 'pass_env_names', 'read_paths', 'allowed_actions', 'forbidden_sources')
# Launcher -> the agent name the one-shot host uses for the same CLI (its parsers and login helpers).
AGENTS = {'claude': 'claude', 'codex': 'codex', 'gemini': 'gemini'}
MCP_SERVER = 'ravel'
# A dedicated Claude login directory holds credentials and state only; any of these is user configuration.
CLAUDE_USER_CONFIGURATION = ('CLAUDE.md', 'CLAUDE.local.md', 'settings.json', 'settings.local.json', 'skills',
                             'agents', 'commands', 'plugins', 'hooks', 'output-styles')
# What every real login creates and is still not configuration: display-only settings keys, a
# plugins folder that lists marketplace catalogs with nothing installed or enabled (an interactive
# login also writes installed_plugins.json with an empty plugins map), and the
# account-synced skills/synced/<org>/<skill>/ and plugins/synced/<org>/ folders. RAVEL's launch
# flags (--restricted --setting-sources project --strict-mcp-config --tools '') load no skill from
# them (docs/reference/transports.md).
CLAUDE_COSMETIC_SETTINGS = ('theme', 'preferredNotifChannel', 'spinnerTipsEnabled', 'terminalProgressBarEnabled')
CLAUDE_SYNCED = 'synced'
CLAUDE_PLUGIN_CATALOG = ('known_marketplaces.json', 'marketplaces', CLAUDE_SYNCED)
# The plugin record an interactive login writes with nothing installed: an empty plugins map.
CLAUDE_PLUGIN_RECORD = 'installed_plugins.json'
# Launchers whose CLI enforces a cost ceiling itself; an API-billed route on any other launcher
# cannot bound its spend and is refused by name.
COST_ENFORCING = ('claude',)
INSTRUCTION_FILES = ('CLAUDE.md', 'CLAUDE.local.md', 'AGENTS.md', 'AGENT.md', 'GEMINI.md')
PROJECT_CONFIG_DIRS = ('.claude', '.codex', '.gemini', '.agents')
# Credential files a declared variable names; each is copied into the CLI home and the variable repointed.
CREDENTIAL_FILES = {'AWS_CONFIG_FILE': '.aws/config', 'AWS_SHARED_CREDENTIALS_FILE': '.aws/credentials',
                    'GOOGLE_APPLICATION_CREDENTIALS': '.config/gcloud/application_default_credentials.json'}
# Configuration directories a declared variable names; each becomes a fresh empty directory.
CONFIG_HOMES = ('CLOUDSDK_CONFIG',)
# CLIs with no flag that excludes the configuration they find (declaration notes).
DECLARED_CONFIGURATION_LOADED = ('gemini',)
PROMPT_HINT = 'Follow the RAVEL worker instructions given on standard input.'

FINAL_JSON_SCHEMAS = {
    'producer.v1': {'type': 'object', 'additionalProperties': False, 'required': ['completed', 'summary'],
                    'properties': {'completed': {'type': 'boolean'}, 'summary': {'type': 'string'}}},
    'reviewer.v1': {'type': 'object', 'additionalProperties': False,
                    'required': ['completed', 'disposition', 'findings'],
                    'properties': {'completed': {'type': 'boolean'},
                                   'disposition': {'type': 'string', 'enum': ['supported', 'not_supported',
                                                                              'request_evidence', 'inconclusive']},
                                   'findings': {'type': 'array', 'items': {
                                       'type': 'object', 'additionalProperties': False, 'required': ['summary'],
                                       'properties': {'summary': {'type': 'string', 'minLength': 1}}}}}},
}


class LaunchRefused(ValueError):
    """The worker cannot launch on its route; ``missing`` names each absent item. Nothing started."""
    not_dispatched = True

    def __init__(self, message, missing):
        super().__init__(message)
        self.missing = list(missing)


def _refuse(item, detail=None):
    raise LaunchRefused(f'cli worker refused: {item}' + (f' ({detail})' if detail else ''), [item])


def unsupported(document):
    """Why this adapter cannot launch the declaration (None when it can)."""
    if document['transport_kind'] != 'cli-worker':
        return 'transport_kind:' + document['transport_kind']
    if document['id'] in tr.UNIMPLEMENTED_ROUTES:
        return 'unimplemented:' + document['id']
    surface = document.get('worker_surface')
    if surface and surface['mcp']['config'] == 'probe_required':
        return 'worker_surface.mcp:probe_required'
    if document['launcher'] not in AGENTS:
        return 'adapter:' + document['launcher']
    if document['billing'] == 'api' and document['launcher'] not in COST_ENFORCING:
        return 'cost_unenforceable:' + document['id']
    if not surface:
        return 'worker_surface'
    return None


# ---------------------------------------------------------------- selection and probe

def _card(spec, card):
    from .. import role_registry
    if card is None:
        card = role_registry.load(spec['role']['id'])
        if role_registry.card_sha256(spec['role']['id']) != spec['role']['card_sha256']:
            _refuse('role_card:changed')
    elif tr.digest(card) != spec['role']['card_sha256']:
        _refuse('role_card:changed')
    return card


def run_preferences(run, spec, card):
    """The selection preferences: the spec's route order with the run's tier models and family bindings."""
    path = run / 'inputs' / 'agent_preferences.json'
    if not path.is_file():
        _refuse('preferences', 'inputs/agent_preferences.json')
    document = read_json(path)
    if type(document) is not dict or document.get('kind') != 'agent-preferences' or document.get('schema_version') != 1:
        _refuse('preferences', 'not an agent-preferences record')
    return {'schema_version': 1, 'kind': 'agent-preferences',
            'families': {card.get('family'): list(spec['transport_preference'])},
            'tier_models': deepcopy(document.get('tier_models') or {}),
            'model_families': deepcopy(document.get('model_families') or {})}


def _select(run, spec, card):
    try:
        return tr.select(card, run_preferences(run, spec, card))
    except tr.TransportRefusal as exc:
        raise LaunchRefused(str(exc), exc.missing) from None


def current_probe(document, run=None):
    """(probe record, executable path, sha256) for a current probe of the executable that would run now."""
    record = tr.read_probe(document['id'])
    if record is None:
        _refuse('probe')
    problem = tr.probe_problem(record, document)
    if problem:
        _refuse(problem)
    if record['unusable']:
        raise LaunchRefused('cli worker refused: probe found unusable items', ['probe:' + u for u in record['unusable']])
    path, sha = tr.resolve_executable(document)
    if path is None or not Path(path).is_absolute():
        _refuse('launcher:' + document['launcher'])
    if sha != record['executable_sha256'] or path != record['executable_path']:
        _refuse('probe:stale-executable')
    try:
        tr.check_executable_location(path, rundir=run)
    except tr.TransportRefusal as exc:
        raise LaunchRefused(str(exc), exc.missing) from None
    return record, path, sha


# ---------------------------------------------------------------- workspace, home and files

def _no_instruction_files(ws):
    """The CLI starts in an empty workspace: no instruction or project configuration file above it."""
    account = broker.ordinary(Path.home())
    for folder in [ws, *ws.parents]:
        for name in INSTRUCTION_FILES:
            if (folder / name).exists():
                _refuse('workspace:instruction-file', str(folder / name))
        if folder != account and not account.is_relative_to(folder):
            for name in PROJECT_CONFIG_DIRS:
                if (folder / name).exists():
                    _refuse('workspace:project-configuration', str(folder / name))


def _write_once(path, data):
    """Trusted adapter files in ``inputs/``: written once, read-only, identical on a reattach."""
    raw = data.encode() if type(data) is str else data
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            _refuse('workspace:adapter-file-changed', path.name)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o400)
    return path


def _login_config_dir():
    """The operator's dedicated Claude login directory, checked to carry no user configuration."""
    value = os.environ.get('CLAUDE_CONFIG_DIR')
    if not value:
        _refuse('CLAUDE_CONFIG_DIR', 'set it to a login-only directory; the account default is your own configuration')
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        _refuse('CLAUDE_CONFIG_DIR', 'must be an absolute, existing, non-symlinked directory')
    path = broker.ordinary(path)
    if path == broker.ordinary(Path.home() / '.claude'):
        _refuse('claude_config_dir:user-configuration', 'the account Claude directory')
    found = [name for name in CLAUDE_USER_CONFIGURATION if (path / name).exists() or (path / name).is_symlink()]
    found = [name for name in found if not (name == 'settings.json' and _cosmetic_settings(path / name))
             and not (name == 'plugins' and _plugin_catalog_only(path / name))
             and not (name == 'skills' and _synced_only(path / name))]
    if found:
        _refuse('claude_config_dir:user-configuration', ', '.join(found))
    return path


def _cosmetic_settings(path):
    """True for a regular settings file whose keys are all display-only."""
    if path.is_symlink() or not path.is_file():
        return False
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError):
        return False
    return type(value) is dict and set(value) <= set(CLAUDE_COSMETIC_SETTINGS)


def _plugin_catalog_only(path):
    """True for a plugins folder holding only marketplace catalogs, account-synced content and,
    at its top level, a plugin record with nothing installed."""
    if path.is_symlink() or not path.is_dir():
        return False
    if any(p.name not in (*CLAUDE_PLUGIN_CATALOG, CLAUDE_PLUGIN_RECORD) for p in path.iterdir()):
        return False
    for found in path.rglob('*'):
        if found.is_symlink() or (found.name == CLAUDE_PLUGIN_RECORD and found.parent != path):
            return False
    record = path / CLAUDE_PLUGIN_RECORD
    if record.exists() and not _no_installed_plugins(record):
        return False
    known = path / 'known_marketplaces.json'
    return (not known.exists() or known.is_file()) and all(
        not (path / name).exists() or (path / name).is_dir() for name in ('marketplaces', CLAUDE_SYNCED))


def _no_installed_plugins(path):
    """True for a regular plugin record whose ``plugins`` map is empty (beside it, only ``version``)."""
    if path.is_symlink() or not path.is_file():
        return False
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError):
        return False
    return type(value) is dict and value.get('plugins') == {} and set(value) <= {'version', 'plugins'}


def _synced_only(path):
    """True for a skills folder holding only the account-synced ``synced/`` folder, with no links."""
    if path.is_symlink() or not path.is_dir() or [p.name for p in path.iterdir()] != [CLAUDE_SYNCED]:
        return False
    return (path / CLAUDE_SYNCED).is_dir() and not any(found.is_symlink() for found in path.rglob('*'))


def _copy_credentials(document, home, environment):
    """Copy each declared credential file into the home; repoint its variable. Bytes are copied, never read."""
    launch_env = {}
    names = set(document['pass_env']) | set(document['auth']['env_names'])
    real = Path(environment.get('HOME') or Path.home())
    for name in sorted(names & set(CREDENTIAL_FILES)):
        source = Path(environment[name]) if environment.get(name) else real / CREDENTIAL_FILES[name]
        if source.is_symlink():
            _refuse('credential:' + name, 'a symbolic link is refused')
        if not source.is_file():
            continue
        target = home / 'credentials' / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source, target, follow_symlinks=False)
            target.chmod(0o600)
        launch_env[name] = str(target)
    for name in sorted(names & set(CONFIG_HOMES)):
        target = home / 'config' / name
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        launch_env[name] = str(target)
    return launch_env


def _cli_home(agent, document, ws):
    """(home, owned, launch environment, verified names, MCP config dir) for this CLI."""
    from .. import cli_agent_host as host
    environment = dict(os.environ)
    if agent == 'claude' and document['auth']['kind'] == 'login':
        return _login_config_dir(), False, {}, ['CLAUDE_CONFIG_DIR'], ws / 'inputs' / 'mcp'
    home = sandbox.cli_home_for(ws)
    fresh = not home.exists()
    if fresh:
        home.mkdir(mode=0o700)
    launch_env = _copy_credentials(document, home, environment)
    if agent == 'claude':
        (home / 'claude').mkdir(exist_ok=True, mode=0o700)
        launch_env['CLAUDE_CONFIG_DIR'] = str(home / 'claude')
        config_dir = ws / 'inputs' / 'mcp'
    elif agent == 'codex':
        if fresh:
            host.fresh_codex_home(home / 'codex', environment)
        launch_env['CODEX_HOME'] = str(home / 'codex')
        config_dir = home / 'codex'
    else:
        if fresh:
            host.fresh_google_home(agent, home / 'home', environment)
        launch_env['HOME'] = str(home / 'home')
        config_dir = home / 'home'
    return home, True, launch_env, sorted(launch_env), config_dir


def _keychain_home(ws):
    """The worker's own HOME holding exactly one entry: ``Library/Keychains`` linked to the login keychains.

    The one link RAVEL creates on purpose (see ``sandbox.user_home_for``); it is made fresh,
    and an existing home with anything else in it is refused.
    """
    home = sandbox.user_home_for(ws)
    target = sandbox.login_keychains()
    link = home / 'Library' / 'Keychains'
    if home.exists() or home.is_symlink():
        if (home.is_symlink() or [p.name for p in home.iterdir()] != ['Library']
                or [p.name for p in (home / 'Library').iterdir()] != ['Keychains']
                or not link.is_symlink() or Path(os.readlink(link)) != target):
            _refuse('keychain_home', 'the worker home holds something other than the keychain link')
        return home
    (home / 'Library').mkdir(parents=True, mode=0o700)
    home.chmod(0o700)
    link.symlink_to(target, target_is_directory=True)
    return home


def remove_home(ws, descriptor):
    """Remove the per-worker CLI home and keychain home after the child is gone.

    ``rmtree`` removes the keychain link itself, never what it points to.
    """
    transport = descriptor.get('transport') or {}
    home = transport.get('cli_home')
    if transport.get('cli_home_owned') and home and broker.ordinary(home) == sandbox.cli_home_for(ws):
        shutil.rmtree(home, ignore_errors=True)
    user_home = transport.get('user_home')
    if user_home and Path(user_home) == sandbox.user_home_for(ws):
        shutil.rmtree(user_home, ignore_errors=True)


def _socket_path(run, ws, spec):
    if sandbox.available() == 'linux':
        return '/tmp/ravel-broker.sock'
    probe = broker.Broker(run, ws, node_id=spec['node_id'], attempt=spec['attempt'], allowed_actions=[], max_calls=0)
    return str(probe.socket_path)


def mcp_command(ws, toolbelt_path, socket_path):
    """The broker MCP face as the CLI starts it inside the sandbox; imports RAVEL from the package root."""
    package = str(Path(__file__).resolve().parents[3])
    bootstrap = (f'import sys;sys.path.insert(0,{package!r});'
                 'from ravel.workflow.work_cli import main;raise SystemExit(main())')
    return [sys.executable, '-B', '-c', bootstrap, 'mcp', '--workspace', str(ws), '--toolbelt', str(toolbelt_path),
            '--socket', str(socket_path)]


def _gemini_settings(config_dir):
    """The fresh home's settings (the login's selected auth type), kept beside the generated MCP entry."""
    settings = config_dir / '.gemini' / 'settings.json'
    return json.loads(settings.read_text()) if settings.is_file() else {}


# ---------------------------------------------------------------- toolbelt and prompt

def toolbelt_for(card, document, blind, *, atlas=None):
    """The card's toolbelt at the route's tool policy (reviewers run full-tool); blind roles keep workspace tools only."""
    from .. import toolbelt
    effective = deepcopy(card)
    route = document['capabilities']['tools']
    if tr.TOOLS.index(effective['requires'].get('tools', 'none')) < tr.TOOLS.index(route):
        effective['requires']['tools'] = route
    executable = toolbelt.EXECUTABLE_ACTIONS
    if effective['family'] == 'production' and not blind:
        from .. import role_registry
        effective['must_check'] = role_registry.resolve_self_checks(
            [*effective['must_check'], *role_registry.self_checks(effective['id'])])
        executable += (toolbelt.CHECK_ACTION,)
    belt = toolbelt.build(effective, atlas=atlas, executable=executable)
    if blind:
        kept = [t for t in belt['tools'] if t['executes_through']['action'] in (None, 'read', 'write')]
        belt['omitted'] += [{'name': t['name'], 'atlas_id': t['atlas_id'], 'reason': 'blind_role',
                             'reachable_through': None} for t in belt['tools'] if t not in kept]
        belt['tools'] = kept
        belt['manifest_sha256'] = toolbelt.manifest_sha256(belt)
    return belt


def build_prompt(card, spec, ws, belt, *, agent, structured):
    """The complete worker prompt: role, protocol, workspace, tools, outputs, budgets and final record."""
    inputs =sorted(p.relative_to(ws).as_posix() for p in (ws / 'inputs').rglob('*')
                    if p.is_file() and not p.is_symlink() and p.parent.name != 'mcp'
                    and p.name not in ('toolbelt.json', 'final-schema.json'))
    tools = [t for t in belt['tools'] if t['executes_through']['action'] is not None]
    protocol = card.get('protocol') or []
    lines = [f"You are the RAVEL role `{card['id']}` (version {spec['role']['version']}).",
             f"Purpose: {card.get('purpose', '').strip()}", '', 'Protocol:']
    lines += [f'- {step}' for step in protocol] or ['- Follow the work order.']
    lines += ['', 'Your workspace has inputs/ (read-only), outputs/ and scratch/. Paths are relative to it.',
              f'Use only the `{MCP_SERVER}` MCP tools; every call is receipted by the RAVEL broker:']
    lines += [f"- {t['name']}: {t['description']}" for t in tools] or ['- (no tools: answer from the prompt)']
    lines += ['', 'Inputs:'] + ([f'- {p}' for p in inputs] or ['- (none)'])
    if (ws / 'inputs' / 'work-order.json').is_file():
        lines += ['', 'Work order (inputs/work-order.json):', (ws / 'inputs' / 'work-order.json').read_text().strip()]
    lines += ['', 'Declared outputs (write each with ws_write):']
    lines += [f"- {o['path']} ({o['kind']}, {'required' if o['required'] else 'optional'})"
              for o in spec['declared_outputs']] or ['- (none)']
    budget = spec['budgets']
    lines += ['', f"Budgets: at most {budget['max_turns']} turns and {budget['max_broker_calls']} tool calls.", '',
              'Finish with one final record that matches this JSON schema. Set completed to true only when every '
              'required output is written:', json.dumps(FINAL_JSON_SCHEMAS[spec['final_record_schema']], sort_keys=True)]
    if not structured:
        lines.append('Your final message must be that JSON object and nothing else.')
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- the descriptor

def prepare_launch(rundir, spec, workspace, *, selection=None, card=None, atlas=None):
    """The trusted launch descriptor for one worker attempt, or ``LaunchRefused`` naming what is missing.

    ``selection``, ``card`` and ``atlas`` are for trusted code only (``qualify``); graph input
    never supplies them.
    """
    from .. import agent_worker, broker_mcp, cli_agent_host as host
    run = broker.ordinary(rundir)
    spec = agent_worker._validate(spec)
    ws = broker.ordinary(workspace)
    if ws != agent_worker.workspace(run, spec['node_id'], spec['attempt']):
        _refuse('workspace', 'not this attempt\'s workspace')
    card = _card(spec, card)
    selected = deepcopy(selection) if selection is not None else _select(run, spec, card)
    document = tr.load(selected['transport_id'])
    if document['transport_kind'] != 'cli-worker':
        _refuse('transport_kind:' + document['transport_kind'], 'a CLI worker never falls back to another route')
    problem = tr.executor_problem(document)
    if problem:
        _refuse(problem)
    probe, executable, executable_sha = current_probe(document, run)
    if selected.get('probe_sha256') is not None and selected['probe_sha256'] != tr.digest(probe):
        _refuse('probe:changed')
    agent = AGENTS[document['launcher']]
    model, effort = selected['model'], selected.get('effort')
    if type(model) is not str or not tr.MODEL_ID.match(model):
        _refuse('model:invalid')
    if effort is not None and (not document['capabilities']['effort_control'] or effort not in host.EFFORTS[agent]):
        _refuse('effort')
    usd = spec['budgets']['max_cost_usd']
    if document['billing'] == 'api' and usd is None:
        _refuse('cost_budget', 'an API-billed worker needs max_cost_usd')
    if usd is not None and agent != 'claude':
        _refuse('cost_unenforceable', f'{agent} reports no cost; use a null cost budget on a subscription route')
    _no_instruction_files(ws)
    blind = spec['role']['id'] in agent_worker.blind_roles()
    from .. import toolbelt
    try:
        belt = toolbelt_for(card, document, blind, atlas=atlas)
    except toolbelt.ToolbeltError as exc:
        raise LaunchRefused(f'cli worker refused: toolbelt:{exc}', ['toolbelt']) from None
    home, owned, launch_env, verified, config_dir = _cli_home(agent, document, ws)
    belt_path = _write_once(ws / 'inputs' / 'toolbelt.json', json.dumps(belt, indent=1, sort_keys=True))
    schema = FINAL_JSON_SCHEMAS[spec['final_record_schema']]
    schema_path = _write_once(ws / 'inputs' / 'final-schema.json', json.dumps(schema, sort_keys=True))
    command = mcp_command(ws, belt_path, _socket_path(run, ws, spec))
    surface = document['worker_surface']
    if config_dir.is_relative_to(ws / 'inputs') and (config_dir / 'mcp.json').exists():
        mcp = {'config': surface['mcp']['config'], 'path': str(config_dir / 'mcp.json'), 'env': {}, 'fallback': None,
               'argv': [a.replace('{mcp_config}', str(config_dir / 'mcp.json')) for a in surface['mcp']['argv']]}
    else:
        selected_auth = _gemini_settings(config_dir) if agent == 'gemini' else {}
        mcp = broker_mcp.client_config(document, config_dir=config_dir, command=command)
        if agent == 'gemini' and selected_auth.get('security'):
            settings = Path(mcp['path'])
            settings.write_text(json.dumps({**json.loads(settings.read_text()), 'security': selected_auth['security']},
                                           indent=1))
        if Path(mcp['path']).is_relative_to(ws / 'inputs'):
            Path(mcp['path']).chmod(0o400)
    if mcp['env'] and any(launch_env.get(k) != v for k, v in mcp['env'].items()):
        _refuse('worker_surface.mcp:home-mismatch')
    if agent == 'claude':
        # Claude Code ignores TMPDIR for its own temporary directory (/tmp/claude-<uid>), which the
        # sandbox denies; both point at the worker's private scratch.
        tmp = ws / 'scratch' / 'tmp'
        tmp.mkdir(mode=0o700, exist_ok=True)
        launch_env.update(CLAUDE_CODE_TMPDIR=str(tmp), TMPDIR=str(tmp))
    # Claude Code reads its stored login from the login keychain under $HOME/Library/Keychains.
    user_home = _keychain_home(ws) if agent == 'claude' and sandbox.available() == 'macos' else None
    if user_home:
        launch_env['HOME'] = str(user_home)
    tools = [t['name'] for t in belt['tools'] if t['executes_through']['action'] is not None]
    structured = surface['structured_output'] == 'enforced'
    prompt = build_prompt(card, spec, ws, belt, agent=agent, structured=structured)
    key = agent_worker._key(spec['node_id'], spec['attempt'])
    custody = broker.custody(run)
    prompt_path = custody / (key + '.prompt.txt')
    if not prompt_path.exists() or prompt_path.read_text() != prompt:
        prompt_path.write_text(prompt)
    values = {'model': model, 'effort': effort, 'schema': json.dumps(schema, sort_keys=True),
              'schema_file': str(schema_path), 'tools': ','.join(f'mcp__{MCP_SERVER}__{n}' for n in tools),
              'usd': (f'{usd:.4f}' if usd is not None else None), 'workspace': str(ws),
              # A whole-token config value, dropped with its flag when the card sets no effort.
              'effort_config': (f'model_reasoning_effort="{effort}"' if effort is not None else None),
              'prompt_hint': PROMPT_HINT}
    try:
        argv = tr.render_argv(document, values, executable=executable) + list(mcp['argv'])
    except KeyError as exc:
        _refuse('argv:' + str(exc).strip("'\""))
    if agent == 'claude' and '--tools' in argv:
        # No built-in tools; the allowlist names only the broker MCP tools.
        argv[argv.index('--tools') + 1] = ''
    names = set(document['pass_env']) | set(document['auth']['env_names'])
    pass_env = sorted({n for n in names if n not in agent_worker.RESERVED_ENV}
                      | (set(agent_worker.ACCOUNT_ENV) if agent == 'claude' else set()))
    read_paths = sandbox.runtime_paths(argv)
    allowed = sorted({t['executes_through']['action'] for t in belt['tools'] if t['executes_through']['action']})
    declared_loaded = agent in DECLARED_CONFIGURATION_LOADED
    audit = {'schema_version': 1, 'kind': 'cli-worker-prompt-audit', 'node_id': spec['node_id'],
             'attempt': spec['attempt'], 'role': spec['role'], 'transport_id': document['id'],
             'declaration_sha256': tr.declaration_sha256(document), 'probe_sha256': tr.digest(probe),
             'executable_path': executable, 'executable_sha256': executable_sha,
             'prompt': {'path': str(prompt_path), 'sha256': broker.sha(prompt_path), 'bytes': prompt_path.stat().st_size,
                        'channel': 'stdin'},
             'argv': argv, 'argv_sha256': broker.digest(argv), 'pass_env_names': pass_env,
             'launch_env_names': sorted(launch_env), 'verified_env': verified,
             'final_schema_sha256': broker.sha(schema_path), 'toolbelt_manifest_sha256': belt['manifest_sha256'],
             'mcp': {'config': mcp['config'], 'path': mcp['path'],
                     'sha256': broker.sha(Path(mcp['path'])) if mcp['path'] else None,
                     'servers': [MCP_SERVER]},
             'tools': tools, 'blind': blind, 'model': model, 'effort': effort, 'created_utc': broker.utc()}
    audit_path = custody / (key + '.prompt-audit.json')
    atomic_json(audit_path, audit)
    transport = {'id': document['id'], 'transport_kind': 'cli-worker', 'agent': agent,
                 'declaration_sha256': tr.declaration_sha256(document), 'declaration_origin': tr.origin(document),
                 'declared_attestation': document['capabilities']['attestation'],
                 'probe_sha256': tr.digest(probe), 'cli_version': probe['cli_version'],
                 'executable_path': executable, 'executable_sha256': executable_sha,
                 'stdin': {'path': str(prompt_path), 'sha256': broker.sha(prompt_path)},
                 'prompt_audit': {'path': str(audit_path), 'sha256': broker.sha(audit_path)},
                 'cli_home': str(home), 'cli_home_owned': owned, 'user_home': str(user_home) if user_home else None,
                 'launch_env': launch_env, 'verified_env': verified,
                 'network': 'provider', 'structured_output': surface['structured_output'],
                 'toolbelt': {'path': str(belt_path), 'manifest_sha256': belt['manifest_sha256']},
                 'user_configuration_declared_loaded': declared_loaded,
                 'limits': {'max_turns': spec['budgets']['max_turns'], 'max_cost_usd': usd},
                 'receipt': None}
    descriptor = {'argv': argv, 'transport': transport,
                  'model': {'requested': model, 'observed': None, 'family': selected.get('family')
                            or tr.family_of(document, model), 'effort': effort},
                  'pass_env_names': pass_env, 'read_paths': read_paths, 'allowed_actions': allowed,
                  'forbidden_sources': []}
    assert tuple(descriptor) == DESCRIPTOR_KEYS
    return descriptor


# ---------------------------------------------------------------- after the child

def _final(agent, parsed):
    from ..cli_agent_host import extract_json
    text = parsed.get('text')
    if type(text) is not str:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        try:
            value = extract_json(text)
        except (ValueError, TypeError, AttributeError):
            return None
    return value if type(value) is dict else None


def _turns(agent, parsed, raw):
    meter = parsed.get('meter') or {}
    if agent == 'claude':
        turns = meter.get('num_turns')
        return turns if type(turns) is int else None
    if agent == 'codex':
        # One ``turn.completed`` event per model turn; a turn completes many items.
        count = 0
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            count += type(event) is dict and event.get('type') == 'turn.completed'
        return count
    calls = ((meter.get('stats') or {}).get('tools') or {}).get('totalCalls')
    return calls + 1 if type(calls) is int else None


def _session_reused(run, transport_id, session_id):
    for row in broker.ledger(run, 'worker-receipts'):
        try:
            receipt = read_json(broker.locate(run, row['record']['pin']['path']))
        except (OSError, ValueError, KeyError):
            continue
        if receipt.get('session_id') == session_id and (receipt.get('transport') or {}).get('id') == transport_id:
            return True
    return False


def observe(rundir, descriptor, ws, spec, execution):
    """Parse the CLI's JSON output into the receipt's final record, session, usage, model and limits."""
    from .. import cli_agent_host as host
    from .. import agent_worker
    run, ws = broker.ordinary(rundir), broker.ordinary(ws)
    transport = deepcopy(descriptor['transport'])
    agent = transport['agent']
    stdout = agent_worker.capture_path(run, spec['node_id'], spec['attempt'], 'stdout')
    raw = stdout.read_text(errors='replace') if stdout.is_file() and stdout.stat().st_size <= broker.MAX_MESSAGE else ''
    parsers = {'claude': host._claude, 'codex': host._codex, 'gemini': lambda out: host._google('gemini', out)}
    parsed, error = None, None
    try:
        parsed = parsers[agent](raw)
    except host.AgentCLIError as exc:
        error = exc.code
    usage = {'input_tokens': None, 'output_tokens': None, 'cost_usd': None, 'reported': False, 'turns': None}
    final, session, observed, config_events = None, None, None, []
    if parsed is not None:
        final = _final(agent, parsed)
        session = parsed.get('session_id') if type(parsed.get('session_id')) is str else None
        observed = parsed.get('observed_model')
        tokens = parsed.get('usage') or {}
        cost = (parsed.get('meter') or {}).get('total_cost_usd')
        usage.update(input_tokens=tokens.get('input_tokens'), output_tokens=tokens.get('output_tokens'),
                     cost_usd=cost if type(cost) in (int, float) else None, turns=_turns(agent, parsed, raw),
                     reported=bool(tokens))
        config_events = parsed.get('config_events') or []
    limits = transport['limits']
    checks = {'turns': {'observed': usage['turns'], 'max': limits['max_turns'],
                        'within': usage['turns'] is not None and usage['turns'] <= limits['max_turns']
                        or usage['turns'] is None and agent != 'claude'},
              'cost': {'observed': usage['cost_usd'], 'max': limits['max_cost_usd'],
                       'within': limits['max_cost_usd'] is None
                       or usage['cost_usd'] is not None and usage['cost_usd'] <= limits['max_cost_usd']}}
    isolation = deepcopy(execution.get('isolation') or {'profile': 'unestablished', 'user_configuration_loaded': True,
                                                          'evidence': {}})
    isolation['user_configuration_loaded'] = bool(isolation.get('user_configuration_loaded')
                                                  or transport['user_configuration_declared_loaded'] or config_events)
    reasons = []
    if error:
        reasons.append('envelope:' + error)
    if execution.get('exit_status') != 0:
        reasons.append('exit')
    if session is None:
        reasons.append('session_id')
    elif _session_reused(run, transport['id'], session):
        reasons.append('session_reused')
    if isolation['user_configuration_loaded']:
        reasons.append('user_configuration_loaded')
    if not (isolation.get('evidence') or {}).get('confirmed'):
        reasons.append('isolation_unconfirmed')
    if transport['declared_attestation'] != 'transport':
        reasons.append('declared_attestation')
    transport['observation'] = {'envelope_error': error, 'limits': checks, 'config_events': config_events,
                                'stdout_sha256': broker.sha(stdout) if stdout.is_file() else None,
                                'attestation_reasons': reasons}
    result = {'final': final, 'session_id': session, 'usage': usage, 'cli_version': transport['cli_version'],
              'model': {**descriptor['model'], 'observed': observed}, 'isolation': isolation,
              'attestation': 'transport_attested' if not reasons else 'host_attested', 'transport': transport}
    if not all(c['within'] for c in checks.values()):
        result['budget_exhausted'] = True
    return result


# ---------------------------------------------------------------- live qualification

CONFORMANCE_ROLE = 'transport-conformance'
CONFORMANCE_INPUT = 'inputs/conformance.json'
CONFORMANCE_OUTPUT = 'outputs/conformance.txt'
SURFACE_OUTPUT = 'outputs/surface.txt'
# A fixed request: the worker lists every skill and tool it can use. Qualification passes only when
# the reply names the RAVEL MCP tools and nothing else (no synced skill, no built-in tool).
SURFACE_REQUEST = (f'Call ws_write with path {SURFACE_OUTPUT} and content listing, one per line, the exact name of '
                   'every skill and every tool available to you in this session, and nothing else. List no '
                   'heading, description or comment.')


def conformance_card():
    """The fixed, generic conformance role: read one input through the broker, write one output, finish."""
    return {'schema_version': 1, 'kind': 'role-card', 'id': CONFORMANCE_ROLE, 'version': '1', 'family': 'qualification',
            'purpose': 'Show that this worker route reaches the RAVEL broker tools and returns a structured final record.',
            'protocol': [f'Call ws_read with path {CONFORMANCE_INPUT}.',
                         f'Call ws_write with path {CONFORMANCE_OUTPUT} and content equal to the nonce field of that '
                         'file, exactly, with nothing else.',
                         SURFACE_REQUEST,
                         'Then finish with completed true and a one-sentence summary.'],
            'requires': {'tools': 'broker-full', 'structured_output': True, 'isolation_min': 'ravel-sandbox',
                         'attestation_min': 'transport', 'blind': False},
            'tools': {'ravel_actions': ['read', 'write'], 'exec_argv_prefixes': [], 'read_paths': ['inputs/'],
                      'validators': []},
            'knowledge': {'may_query': [], 'consult': [], 'derive': [], 'forbidden': [], 'must_read': [],
                          'budget_tokens': 0},
            'must_check': [], 'stop': {'evidence_budget': 0}, 'model': {'tier': 'judgment', 'effort': None,
                                                                         'distinct_family_from': []},
            'output': {'schema': 'producer.v1', 'declared_outputs': [], 'sidecar': False},
            'independence': {'kind': 'advisory'}}


def _conformance_atlas():
    from .. import toolbelt
    atlas = deepcopy(toolbelt.load_atlas())
    atlas['entries'].append({'id': 'role:' + CONFORMANCE_ROLE, 'kind': 'role', 'title': 'transport conformance',
                             'summary': 'fixed live qualification task for a worker route', 'links': {},
                             'status': 'registered'})
    return atlas


def conformance_spec(card):
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': 'qualify.conformance', 'attempt': 1,
            'role': {'id': CONFORMANCE_ROLE, 'version': card['version'], 'card_sha256': tr.digest(card)},
            'transport_preference': [], 'inputs': [{'pin': None, 'as': CONFORMANCE_INPUT}],
            'declared_outputs': [{'path': CONFORMANCE_OUTPUT, 'kind': 'text', 'required': True},
                                 {'path': SURFACE_OUTPUT, 'kind': 'text', 'required': True}],
            'budgets': {'max_turns': 8, 'max_wall_seconds': 600, 'max_broker_calls': 12, 'max_cost_usd': None},
            'final_record_schema': 'producer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}


# The CLI's own channel for a --json-schema answer. It cannot read, write or run anything, so listing it is not a
# capability beyond the RAVEL tools (live evidence: Claude Code 2.1.296 lists it beside mcp__ravel__*).
ANSWER_CHANNEL_TOOLS = frozenset({'StructuredOutput'})


def surface_names(reply, tools):
    """(names listed, names beyond the RAVEL MCP tools) from the worker's skills-and-tools reply."""
    allowed = {*tools, *(f'mcp__{MCP_SERVER}__{name}' for name in tools), *ANSWER_CHANNEL_TOOLS}
    names = [line.strip().lstrip('-*• ').strip().strip('`').strip() for line in reply.splitlines()]
    names = [name for name in names if name]
    return names, [name for name in names if name not in allowed]


def _surface(ws):
    """The surface reply's record: request, digest, names and anything beyond the RAVEL tools."""
    reply = ws / SURFACE_OUTPUT
    if not reply.is_file() or reply.is_symlink():
        return {'request': SURFACE_REQUEST, 'reply_sha256': None, 'names': [], 'unexpected': None, 'ravel': []}
    tools = [t['name'] for t in read_json(ws / 'inputs' / 'toolbelt.json')['tools']]
    names, unexpected = surface_names(reply.read_text(errors='replace'), tools)
    ravel = [name for name in names if name not in ANSWER_CHANNEL_TOOLS and name not in unexpected]
    return {'request': SURFACE_REQUEST, 'reply_sha256': broker.sha(reply), 'names': names, 'unexpected': unexpected,
            'ravel': ravel}


def qualify(transport_id, *, rundir, model, effort=None, max_cost_usd=None):
    """Run the conformance task live through ``prepare_launch`` in the sandbox; write the record only if every step passed.

    Returns the qualification record. Raises ``LaunchRefused`` (nothing started) or
    ``QualificationFailed`` (the run happened; the failed steps are named; no record).
    """
    from .. import agent_worker
    document = tr.load(transport_id)
    problem = unsupported(document) or tr.executor_problem(document)
    if problem:
        _refuse(problem)
    run = Path(rundir)
    if run.exists() and any(run.iterdir()):
        _refuse('rundir:not-empty', str(run))
    run.mkdir(parents=True, exist_ok=True)
    run = broker.ordinary(run)
    from .. import gate_wiring
    # The qualification run is created here, empty; its worker launch needs the journal record.
    gate_wiring.initialize_steering(run, route='transport-qualification')
    probe, executable, executable_sha = current_probe(document, run)
    nonce = uuid.uuid4().hex
    source = run / CONFORMANCE_INPUT
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps({'nonce': nonce}) + '\n')
    card = conformance_card()
    spec = conformance_spec(card)
    spec['inputs'][0]['pin'] = {'path': CONFORMANCE_INPUT, 'sha256': broker.sha(source)}
    spec['budgets']['max_cost_usd'] = max_cost_usd
    spec['transport_preference'] = [transport_id]
    ws = agent_worker.materialize(run, spec)
    selection = {'transport_id': transport_id, 'model': model, 'effort': effort,
                 'family': tr.family_of(document, model), 'probe_sha256': tr.digest(probe)}
    descriptor = prepare_launch(run, spec, ws, selection=selection, card=card, atlas=_conformance_atlas())
    receipt = agent_worker.launch(run, spec, launch_spec=descriptor)
    calls = [broker.verify_broker_receipt(run, {'path': r['record']['path'], 'sha256': r['record']['sha256']},
                                          verify_outputs=False)
             for r in broker.ledger(run, 'broker')
             if r['record']['node_id'] == spec['node_id'] and r['record']['attempt'] == spec['attempt']]
    output = ws / CONFORMANCE_OUTPUT
    surface = _surface(ws)
    steps = [
        ('receipt_ok', receipt['status'] == 'ok'),
        ('final_record_valid', receipt['final_record']['valid'] is True),
        ('broker_read', any(c['action'] == 'read' and c['status'] == 'ok' for c in calls)),
        ('broker_write', any(c['action'] == 'write' and c['status'] == 'ok' for c in calls)),
        ('output_nonce', output.is_file() and not output.is_symlink() and output.read_text().strip() == nonce),
        ('session_id', type(receipt['session_id']) is str and bool(receipt['session_id'])),
        ('isolation_confirmed', (receipt['isolation'].get('evidence') or {}).get('confirmed') is True),
        ('user_configuration_excluded', receipt['isolation'].get('user_configuration_loaded') is False
         or not document['capabilities']['blind_capable']),
        ('transport_attested', receipt['attestation'] == 'transport_attested'
         or document['capabilities']['attestation'] != 'transport'),
        ('executable_unchanged', tr.resolve_executable(document)[1] == executable_sha),
        ('surface_ravel_only', bool(surface['ravel']) and surface['unexpected'] == []),
    ]
    failed = [name for name, ok in steps if not ok]
    if failed:
        raise QualificationFailed(f'transport {transport_id} did not qualify: ' + ', '.join(failed), failed, receipt)
    receipt_path = ws / 'receipt.json'
    record = {'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': transport_id,
              'status': 'live_qualified', 'record_path': str(tr.qualification_path(transport_id)),
              'executable_path': executable, 'executable_sha256': executable_sha,
              'declaration_sha256': tr.declaration_sha256(document), 'probe_sha256': tr.digest(probe),
              'receipt': {'path': str(receipt_path), 'sha256': broker.sha(receipt_path), 'digest': broker.digest(receipt)},
              'observed': {'model': receipt['model'].get('observed'), 'requested_model': model, 'effort': effort,
                           'session_id': receipt['session_id'], 'turns': receipt['usage'].get('turns'),
                           'cost_usd': receipt['usage'].get('cost_usd'), 'attestation': receipt['attestation'],
                           'surface': surface},
              'steps': [{'step': name, 'passed': ok} for name, ok in steps], 'rundir': str(run),
              'qualified_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    target = tr.qualification_path(transport_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, record)
    return record


class QualificationFailed(ValueError):
    def __init__(self, message, failed, receipt):
        super().__init__(message)
        self.failed, self.receipt = list(failed), receipt


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel transport qualify', description=qualify.__doc__)
    parser.add_argument('transport_id')
    parser.add_argument('--rundir', type=Path, required=True, help='an empty directory for the conformance run')
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort')
    parser.add_argument('--max-cost-usd', type=float)
    args = parser.parse_args(argv)
    try:
        record = qualify(args.transport_id, rundir=args.rundir, model=args.model, effort=args.effort,
                         max_cost_usd=args.max_cost_usd)
    except LaunchRefused as exc:
        print(json.dumps({'status': 'refused', 'missing': exc.missing, 'detail': str(exc)}, indent=2))
        return 3
    except QualificationFailed as exc:
        print(json.dumps({'status': 'failed', 'failed_steps': exc.failed,
                          'receipt_status': exc.receipt.get('status'), 'failure': exc.receipt.get('failure')}, indent=2))
        return 4
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0
