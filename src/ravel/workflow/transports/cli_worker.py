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
- each worker uses its private CLI configuration home beside the workspace. External owner setup
  supplies its login files. Authentication admission checks file metadata and the CLI's status;
- Claude-family CLIs receive account names from the password database and temporary paths within
  the worker scratch directory;
- the toolbelt the broker enforces is pinned by its manifest digest in the descriptor;
- native tools are off where the CLI allows it: Claude runs with no built-in tools and
  Codex with a read-only sandbox and generated native-tool exclusions; Gemini workers get
  generated core-tool exclusions and an empty context-file list. Qualification must confirm
  the resulting surface; native outputs are never credited (only broker output pins are);
- the prompt is written to worker custody with a complete audit record and reaches the
  CLI on standard input (never in argv);
- a run that pins a project instruction document (``project_instructions``) gets its text
  verbatim ahead of the RAVEL prompt, and the descriptor records its sha256, byte count and
  mechanism; an instruction file above the workspace is accepted only when it is that pinned
  document or a file whose whole content imports it.

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
import stat
import sys
import time
import uuid

from .. import broker, project_instructions, sandbox, transport_registry as tr
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
PROMPT_HINT = 'Follow the RAVEL worker instructions given on standard input.'
# The controller's instruction packet, copied into a seat's workspace by the dispatcher.
CONTROLLER_PACKET = 'packet.md'

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
        from ..review_independence import controller_store
        store = controller_store(run)
        options = {} if store is None else {
            'controller': True, 'qualifications': tr.store_qualifications(store)}
        return tr.select(card, run_preferences(run, spec, card), **options)
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

def _no_instruction_files(ws, pinned=None):
    """The CLI starts in an empty workspace: no instruction or project configuration file above it.

    With a pinned project document, an instruction file above the workspace is accepted when it is
    that document with the pinned sha256, or a file whose whole content is one import of it. The
    accepted files are returned for the receipt. Every other instruction file and every project
    configuration directory is refused.
    """
    account = broker.ordinary(Path.home())
    accepted = []
    for folder in [ws, *ws.parents]:
        for name in INSTRUCTION_FILES:
            found = folder / name
            # A link to nothing supplies no text. It is refused only under a pin, where every
            # instruction file above the workspace must be the declared document or an import of it.
            if found.exists() or (pinned is not None and found.is_symlink()):
                if folder == ws or project_instructions.classify(found, pinned) is None:
                    _refuse('workspace:instruction-file', str(found))
                accepted.append(project_instructions.ancestor_row(found, pinned))
        if folder != account and not account.is_relative_to(folder):
            for name in PROJECT_CONFIG_DIRS:
                if (folder / name).exists():
                    _refuse('workspace:project-configuration', str(folder / name))
    return accepted


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
        from . import cli_login
        _refuse('CLAUDE_CONFIG_DIR', cli_login.remedy('LOGIN_DIRECTORY'))
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


def _configuration_paths(document, home, environment):
    """Point declared file variables at owner-provided files inside the CLI home."""
    from . import cli_login
    launch_env = {}
    names = set(document['pass_env']) | set(document['auth']['env_names'])
    for name in sorted(names & set(CREDENTIAL_FILES)):
        target = home / 'credentials' / name
        cli_login.require_file(target, environment.get(name) or target.parent)
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
        _login_config_dir()
        home = sandbox.cli_home_for(ws)
        config = home / 'claude'
        config.mkdir(parents=True, exist_ok=True, mode=0o700)
        home.chmod(0o700)
        return home, False, {'CLAUDE_CONFIG_DIR': str(config)}, ['CLAUDE_CONFIG_DIR'], ws / 'inputs' / 'mcp'
    home = sandbox.cli_home_for(ws)
    fresh = not home.exists()
    if fresh:
        home.mkdir(mode=0o700)
    launch_env = _configuration_paths(document, home, environment)
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


def remove_home(ws, descriptor):
    """Clean generated CLI configuration while preserving owner-provided login files."""
    transport = descriptor.get('transport') or {}
    home = transport.get('cli_home')
    if transport.get('cli_home_owned') and home and broker.ordinary(home) == sandbox.cli_home_for(ws):
        # External setup owns login files and their containing homes.
        if (Path(home) / 'credentials').exists():
            return
        for name in ('.credentials.json', 'credentials.json', '.claude.json', 'auth.json',
                     'oauth_creds.json', 'google_accounts.json', 'application_default_credentials.json'):
            if any(Path(home).rglob(name)):
                return
        shutil.rmtree(home, ignore_errors=True)


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


def _subscription_selectors(agent, document, launch_env):
    if document['billing'] != 'subscription' or document['auth']['kind'] != 'login' or agent not in ('codex', 'gemini'):
        return
    item = 'subscription_auth:' + agent
    remedy = ('Use a Codex subscription login or a budgeted HTTP API route.' if agent == 'codex' else
              'Use a Gemini OAuth subscription login or a budgeted HTTP loop.')
    selectors = (('OPENAI_API_KEY', 'AZURE_OPENAI_API_KEY') if agent == 'codex' else
                 ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS', 'GEMINI_USE_VERTEXAI'))
    declared = set(document['pass_env']) | set(document['auth']['env_names'])
    if any(launch_env.get(name) or (name in declared and os.environ.get(name)) for name in selectors):
        _refuse(item, remedy)


def _subscription_login_settings(agent, document, config_dir, launch_env):
    """Validate subscription authentication through CLI status and nonsecret settings."""
    if document['billing'] != 'subscription' or document['auth']['kind'] != 'login':
        return None
    if agent not in ('codex', 'gemini'):
        return None
    _subscription_selectors(agent, document, launch_env)
    item = 'subscription_auth:' + agent
    remedy = ('Use a Codex subscription login or a budgeted HTTP API route.' if agent == 'codex' else
              'Use a Gemini OAuth subscription login or a budgeted HTTP loop.')
    valid, settings = True, None
    try:
        if agent == 'codex':
            from . import cli_login
            try:
                cli_login.preflight(launch_env['RAVEL_CLI_EXECUTABLE'], config_dir, agent='codex',
                                    environment=os.environ)
            except cli_login.LoginRefused:
                valid = False
        else:
            settings = _gemini_settings(config_dir)
            security = settings.get('security') or {}
            auth = security.get('auth') or {}
            mode = auth.get('selectedType')
            if mode is None:
                mode = settings.get('selectedAuthType')
            valid = mode is None or mode == 'oauth-personal'
            if valid:
                settings['security'] = {**security, 'auth': {**auth, 'selectedType': 'oauth-personal'}}

    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        valid = False
    # The refusal is outside the exception handler: no credential-bearing parse
    # error or source bytes enter its message or exception context.
    if not valid:
        _refuse(item, remedy)
    return settings if agent == 'gemini' else None


# ---------------------------------------------------------------- toolbelt and prompt

def toolbelt_for(card, document, blind, *, atlas=None, blind_actions=None):
    """The card's toolbelt at the route's tool policy (reviewers run full-tool). A graph-blind role
    keeps workspace tools only; a card-blind role keeps the tools of ``blind_actions``, the
    workspace actions and the actions its own card names (``agent_worker.blind_actions``)."""
    from .. import toolbelt
    effective = deepcopy(card)
    route = document['capabilities']['tools']
    # requires.tools is a minimum. Only an explicit zero-call contract removes
    # executable tools; ordinary reviewers still write their declared outputs.
    no_calls = (effective['requires'].get('tools') == 'none'
                and effective['stop'].get('max_broker_calls') == 0)
    if (not no_calls
            and tr.TOOLS.index(effective['requires'].get('tools', 'none')) < tr.TOOLS.index(route)):
        effective['requires']['tools'] = route
    executable = toolbelt.EXECUTABLE_ACTIONS
    if effective['family'] == 'production' and not blind:
        from .. import role_registry
        effective['must_check'] = role_registry.resolve_self_checks(
            [*effective['must_check'], *role_registry.self_checks(effective['id'])])
        executable += (toolbelt.CHECK_ACTION,)
    belt = toolbelt.build(effective, atlas=atlas, executable=executable)
    limit = ('read', 'write') if blind else blind_actions
    if limit is not None:
        kept = [t for t in belt['tools'] if t['executes_through']['action'] in (None, *limit)]
        belt['omitted'] += [{'name': t['name'], 'atlas_id': t['atlas_id'], 'reason': 'blind_role',
                             'reachable_through': None} for t in belt['tools'] if t not in kept]
        belt['tools'] = kept
        belt['manifest_sha256'] = toolbelt.manifest_sha256(belt)
    return belt


def build_prompt(card, spec, ws, belt, *, agent, structured):
    """The complete worker prompt: role, protocol, workspace, tools, outputs, budgets and final record."""
    inputs =sorted(p.relative_to(ws).as_posix() for p in (ws / 'inputs').rglob('*')
                    if p.is_file() and not p.is_symlink() and p.parent.name != 'mcp'
                    and p.name not in ('toolbelt.json', 'final-schema.json', project_instructions.CARRIER_NAME))
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

def _controller_facts(spec, controller, ws):
    """The controller seat's launch facts, checked: its packet copy, closed schema and selection."""
    from .. import agent_worker
    if spec['final_record_schema'] != agent_worker.CONTROLLER_SCHEMA:
        _refuse('controller:schema', 'a controller seat spec names the controller final-record schema')
    if (type(controller) is not dict or type(controller.get('schema')) is not dict
            or type(controller.get('selection')) is not dict or type(controller.get('packet_sha256')) is not str):
        _refuse('controller:facts', 'a controller seat carries its packet, closed schema and selection')
    if tr.digest(controller['schema']) != controller.get('schema_sha256'):
        _refuse('controller:schema-changed')
    packet = ws / 'inputs' / CONTROLLER_PACKET
    if packet.is_symlink() or not packet.is_file() or broker.sha(packet) != controller['packet_sha256']:
        _refuse('controller:packet', 'the instruction packet copy differs from the one the controller built')
    return packet.read_text(encoding='utf-8')


def build_controller_prompt(packet_text, spec, ws, belt, *, structured):
    """The controller seat's prompt: the instruction packet verbatim, then this route's worker surface."""
    inputs = sorted(p.relative_to(ws).as_posix() for p in (ws / 'inputs').rglob('*')
                    if p.is_file() and not p.is_symlink() and p.parent.name != 'mcp'
                    and p.name not in ('toolbelt.json', 'final-schema.json', CONTROLLER_PACKET,
                                       project_instructions.CARRIER_NAME))
    tools = [t for t in belt['tools'] if t['executes_through']['action'] is not None]
    lines = [packet_text.rstrip('\n'), '', '== Worker surface ==',
             'Your workspace has inputs/ (read-only), outputs/ and scratch/. Paths are relative to it.',
             f'Use only the `{MCP_SERVER}` MCP tools; every call is receipted by the RAVEL broker:']
    lines += [f"- {t['name']}: {t['description']}" for t in tools] or ['- (no tools: answer from the packet)']
    lines += ['', 'Inputs:'] + ([f'- {p}' for p in inputs] or ['- (none)'])
    lines += ['', 'Declared outputs (write each with ws_write):']
    lines += [f"- {o['path']} ({o['kind']}, {'required' if o['required'] else 'optional'})"
              for o in spec['declared_outputs']] or ['- (none)']
    budget = spec['budgets']
    lines += ['', f"Budgets: at most {budget['max_turns']} turns and {budget['max_broker_calls']} tool calls.", '',
              'Finish with one final record that matches the output contract of the packet: every field, the '
              'instruction acknowledgement, one checklist row per duty unit and the escalation list.']
    if not structured:
        lines.append('Your final message must be that JSON object and nothing else.')
    return '\n'.join(lines) + '\n'


def prepare_launch(rundir, spec, workspace, *, selection=None, card=None, atlas=None, controller=None):
    """Build one trusted descriptor with owner-file admission and generated configuration."""
    homes = []
    try:
        return _prepare_launch(rundir, spec, workspace, selection=selection, card=card, atlas=atlas,
                               controller=controller, homes=homes)
    except BaseException:
        for transport in homes:
            remove_home(workspace, {'transport': transport})
        raise


def _prepare_launch(rundir, spec, workspace, *, selection, card, atlas, controller, homes):
    """The trusted launch descriptor for one worker attempt, or ``LaunchRefused`` naming what is missing.

    ``selection``, ``card`` and ``atlas`` are for trusted code only (``qualify``); graph input
    never supplies them. ``controller`` carries a controller seat's launch facts (the governed
    step built them): the selection made from the operator's frozen preferences, the instruction
    packet the prompt is and the closed output schema the final record must match. A controller
    seat runs only on a transport its admission rules allow.
    """
    from .. import agent_worker, broker_mcp, cli_agent_host as host
    run = broker.ordinary(rundir)
    spec = agent_worker._validate(spec)
    ws = broker.ordinary(workspace)
    if ws != agent_worker.workspace(run, spec['node_id'], spec['attempt']):
        _refuse('workspace', 'not this attempt\'s workspace')
    card = _card(spec, card)
    packet_text = None
    if controller is not None or spec.get('final_record_schema') == agent_worker.CONTROLLER_SCHEMA:
        packet_text = _controller_facts(spec, controller, ws)
        selection = controller['selection']
    selected = deepcopy(selection) if selection is not None else _select(run, spec, card)
    document = tr.load(selected['transport_id'])
    if packet_text is not None:
        from ravel.controller.step.seats import admission_problem
        problem = admission_problem(document)
        if problem is not None:
            _refuse('controller:transport', problem)
    from .. import provider_policy
    try:
        admission = provider_policy.admission(run, document, provider_policy.account_class(document),
                                             input_pins=spec['inputs'])
    except provider_policy.PolicyRefused as exc:
        raise LaunchRefused(str(exc), ['provider_policy']) from None
    try:
        egress = sandbox.require_provider_egress(admission)
    except sandbox.EndpointConfinementRefused as exc:
        raise LaunchRefused(str(exc), ['provider_endpoint_confinement']) from None
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
    if usd is not None and agent not in COST_ENFORCING:
        _refuse('cost_unenforceable', f'{agent} reports no cost; use a null cost budget on a subscription route')
    try:
        # A document that no longer matches its pin refuses here, with the re-pin command, before
        # any ancestor file is judged against it.
        pinned = project_instructions.for_run(run)
        if pinned is not None:
            project_instructions.text_of(pinned)
    except project_instructions.ProjectInstructionsError as exc:
        raise LaunchRefused(str(exc), exc.missing) from None
    ancestors = _no_instruction_files(ws, pinned)
    blind = spec['role']['id'] in agent_worker.blind_roles()
    card_blind = not blind and (card.get('requires') or {}).get('blind') is True
    from .. import toolbelt
    try:
        belt = toolbelt_for(card, document, blind, atlas=atlas,
                            blind_actions=agent_worker.blind_actions(card) if card_blind else None)
    except toolbelt.ToolbeltError as exc:
        raise LaunchRefused(f'cli worker refused: toolbelt:{exc}', ['toolbelt']) from None
    if packet_text is not None and (controller.get('toolbelt') or {}).get('manifest_sha256') != belt['manifest_sha256']:
        _refuse('controller:toolbelt', 'the worker toolbelt differs from the one the governed step admitted')
    _subscription_selectors(agent, document, {})
    home, owned, launch_env, verified, config_dir = _cli_home(agent, document, ws)
    cleanup = {'cli_home': str(home), 'cli_home_owned': owned}
    homes.append(cleanup)
    login_preflight = None
    if agent == 'claude' and document['auth']['kind'] == 'login':
        from . import cli_login
        try:
            login_preflight = cli_login.preflight(executable, _login_config_dir(),
                                                  config=launch_env['CLAUDE_CONFIG_DIR'])
        except cli_login.LoginRefused as exc:
            raise LaunchRefused(str(exc), [exc.code]) from None
    subscription_settings = _subscription_login_settings(agent, document, config_dir,
                                                          {**launch_env, 'RAVEL_CLI_EXECUTABLE': executable})
    belt_path = _write_once(ws / 'inputs' / 'toolbelt.json', json.dumps(belt, indent=1, sort_keys=True))
    schema = controller['schema'] if packet_text is not None else FINAL_JSON_SCHEMAS[spec['final_record_schema']]
    schema_path = _write_once(ws / 'inputs' / 'final-schema.json', json.dumps(schema, sort_keys=True))
    command = mcp_command(ws, belt_path, _socket_path(run, ws, spec))
    surface = document['worker_surface']
    if config_dir.is_relative_to(ws / 'inputs') and (config_dir / 'mcp.json').exists():
        mcp = {'config': surface['mcp']['config'], 'path': str(config_dir / 'mcp.json'), 'env': {}, 'fallback': None,
               'argv': [a.replace('{mcp_config}', str(config_dir / 'mcp.json')) for a in surface['mcp']['argv']]}
    else:
        selected_auth = (subscription_settings if subscription_settings is not None else
                         _gemini_settings(config_dir) if agent == 'gemini' else {})
        mcp = broker_mcp.client_config(document, config_dir=config_dir, command=command)
        if agent == 'gemini' and selected_auth.get('security'):
            settings = Path(mcp['path'])
            settings.write_text(json.dumps({**json.loads(settings.read_text()), 'security': selected_auth['security']},
                                           indent=1))
        if Path(mcp['path']).is_relative_to(ws / 'inputs'):
            Path(mcp['path']).chmod(0o400)
    if agent == 'codex':
        config = Path(mcp['path'])
        text = config.read_text()
        prefix = ('web_search = "disabled"\n[features]\nshell_tool = false\n'
                  'apply_patch_freeform = false\ncollab = false\napps = false\n'
                  '[tools]\nview_image = false\n')
        if not text.startswith(prefix):
            config.write_text(prefix + text)
    elif agent == 'gemini':
        config = Path(mcp['path'])
        settings = json.loads(config.read_text())
        settings['tools'] = {'core': [], 'exclude': [
            'run_shell_command', 'read_file', 'read_many_files', 'write_file', 'replace',
            'list_directory', 'glob', 'search_file_content', 'web_fetch', 'google_web_search',
            'save_memory', 'write_todos', 'activate_skill', 'ask_user', 'enter_plan_mode', 'exit_plan_mode']}
        settings['context'] = {'fileName': []}
        settings['model'] = {'maxSessionTurns': spec['budgets']['max_turns']}
        config.write_text(json.dumps(settings, indent=1))
    if agent in ('codex', 'gemini'):
        config.chmod(0o400)
    if mcp['env'] and any(launch_env.get(k) != v for k, v in mcp['env'].items()):
        _refuse('worker_surface.mcp:home-mismatch')
    if agent == 'claude':
        # Claude Code ignores TMPDIR for its own temporary directory (/tmp/claude-<uid>), which the
        # sandbox denies; both point at the worker's private scratch.
        tmp = ws / 'scratch' / 'tmp'
        tmp.mkdir(mode=0o700, exist_ok=True)
        launch_env.update(CLAUDE_CODE_TMPDIR=str(tmp), TMPDIR=str(tmp))
    user_home = None
    tools = [t['name'] for t in belt['tools'] if t['executes_through']['action'] is not None]
    structured = surface['structured_output'] == 'enforced'
    try:
        # The pinned project document, verbatim, ahead of the RAVEL prompt (or behind the route's confirmed flag).
        instruction_values, prefix, instruction_record = project_instructions.deliver(
            pinned, agent, probe, declaration=document, ancestor_files=ancestors,
            carrier=ws / 'inputs' / project_instructions.CARRIER_NAME)
    except project_instructions.ProjectInstructionsError as exc:
        raise LaunchRefused(str(exc), exc.missing) from None
    prompt = prefix + (build_controller_prompt(packet_text, spec, ws, belt, structured=structured)
                       if packet_text is not None else build_prompt(card, spec, ws, belt, agent=agent, structured=structured))
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
              'prompt_hint': PROMPT_HINT, **instruction_values}
    try:
        argv = tr.render_argv(document, values, executable=executable) + list(mcp['argv'])
    except KeyError as exc:
        _refuse('argv:' + str(exc).strip("'\""))
    if agent == 'claude' and '--tools' in argv:
        # No built-in tools; the allowlist names only the broker MCP tools.
        argv[argv.index('--tools') + 1] = ''
    from .. import execution_guard
    if (shell := execution_guard.worker_shell_refusal(belt, argv, agent, run)) is not None:
        _refuse('shell', shell)  # a strict workflow policy: workflow-manager tools only, no general shell
    names = set(document['pass_env']) | set(document['auth']['env_names'])
    pass_env = sorted({n for n in names if n not in agent_worker.RESERVED_ENV}
                      | (set(agent_worker.ACCOUNT_ENV) if agent == 'claude' else set()))
    read_paths = sandbox.runtime_paths(argv)
    allowed = sorted({t['executes_through']['action'] for t in belt['tools'] if t['executes_through']['action']})
    declared_loaded = False  # generated homes carry only authentication and the broker configuration
    audit = {'schema_version': 1, 'kind': 'cli-worker-prompt-audit', 'node_id': spec['node_id'],
             'provider_policy': admission,
             'attempt': spec['attempt'], 'role': spec['role'], 'transport_id': document['id'],
             'declaration_sha256': tr.declaration_sha256(document), 'probe_sha256': tr.digest(probe),
             'executable_path': executable, 'executable_sha256': executable_sha,
             'prompt': {'path': str(prompt_path), 'sha256': broker.sha(prompt_path), 'bytes': prompt_path.stat().st_size,
                        'channel': 'stdin'},
             # The one context channel the builder controls: the controller packet, else the work order, on stdin.
             'context_channels': ['stdin_packet' if packet_text is not None else 'stdin_work_order'],
             'argv': argv, 'argv_sha256': broker.digest(argv), 'pass_env_names': pass_env,
             'launch_env_names': sorted(launch_env), 'verified_env': verified,
             'final_schema_sha256': broker.sha(schema_path), 'toolbelt_manifest_sha256': belt['manifest_sha256'],
             'mcp': {'config': mcp['config'], 'path': mcp['path'],
                     'sha256': broker.sha(Path(mcp['path'])) if mcp['path'] else None,
                     'servers': [MCP_SERVER]},
             'tools': tools, 'blind': blind, 'model': model, 'effort': effort, 'created_utc': broker.utc()}
    if instruction_record is not None:
        audit['project_instructions'] = instruction_record
    audit_path = custody / (key + '.prompt-audit.json')
    atomic_json(audit_path, audit)
    transport = {'id': document['id'], 'transport_kind': 'cli-worker', 'agent': agent,
                 'provider_policy': admission,
                 'declaration_sha256': tr.declaration_sha256(document), 'declaration_origin': tr.origin(document),
                 'declared_attestation': document['capabilities']['attestation'],
                 'probe_sha256': tr.digest(probe), 'cli_version': probe['cli_version'],
                 'executable_path': executable, 'executable_sha256': executable_sha,
                 'stdin': {'path': str(prompt_path), 'sha256': broker.sha(prompt_path)},
                 'prompt_audit': {'path': str(audit_path), 'sha256': broker.sha(audit_path)},
                 'cli_home': str(home), 'cli_home_owned': owned, 'user_home': str(user_home) if user_home else None,
                 'launch_env': launch_env, 'verified_env': verified,
                 'network': 'provider', 'egress': egress, 'structured_output': surface['structured_output'],
                 'mcp_command': list(command),
                 'toolbelt': {'path': str(belt_path), 'manifest_sha256': belt['manifest_sha256']},
                 'user_configuration_declared_loaded': declared_loaded,
                 'limits': {'max_turns': spec['budgets']['max_turns'], 'max_cost_usd': usd},
                 'receipt': None,
                 'config': {'path': mcp['path'], 'sha256': broker.sha(Path(mcp['path']))} if mcp['path'] else None,
                 'configuration_sha256': broker.sha(Path(mcp['path'])) if mcp['path'] else None}
    if login_preflight is not None:
        transport['login_preflight'] = login_preflight
        transport['login_source'] = str(_login_config_dir())
    if instruction_record is not None:
        transport['project_instructions'] = instruction_record
    if packet_text is not None:
        transport['controller'] = {'schema': deepcopy(schema), 'schema_sha256': tr.digest(schema),
                                   'packet_sha256': controller['packet_sha256'],
                                   'manifest_sha256': controller.get('manifest_sha256'),
                                   'step_id': controller.get('step_id'), 'seat': controller.get('seat'),
                                   # The research controller's role packet and node facts, for the packet read
                                   # boundary the supervisor proves (none for any other controller step).
                                   'research_packet': deepcopy(controller.get('research_packet')
                                                               or (controller.get('research_node') or {}).get('packet')),
                                   'research_inputs': deepcopy((controller.get('research_node') or {}).get('inputs')),
                                   'research_packet_subject_sha256': controller.get('research_packet_subject_sha256'),
                                   'research_role': (controller.get('research_node') or {}).get('role')}
    descriptor = {'argv': argv, 'transport': transport,
                  'model': {'requested': model, 'observed': None, 'family': selected.get('family')
                            or tr.family_of(document, model), 'effort': effort},
                  'pass_env_names': pass_env, 'read_paths': read_paths, 'allowed_actions': allowed,
                  'forbidden_sources': []}
    assert tuple(descriptor) == DESCRIPTOR_KEYS
    return descriptor


# ---------------------------------------------------------------- after the child

def _error_tail(path):
    path = Path(path)
    if not path.is_file():
        return ''
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 8192))
        return '\n'.join(stream.read(8192).decode('utf-8', errors='replace').splitlines()[-20:])


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
        if len(parsed.get('all_models') or []) > 1:
            observed = None  # mixed-model totals cannot be attributed to a requested single-model seat
        codex_home = (transport.get('launch_env') or {}).get('CODEX_HOME')
        if agent == 'codex' and observed is None and codex_home:
            observed, rollout_sha = host._codex_rollout(session, {'CODEX_HOME': codex_home})
            if rollout_sha is not None:
                transport['model_rollout_sha256'] = rollout_sha
        tokens = parsed.get('usage') or {}
        cost = (parsed.get('meter') or {}).get('total_cost_usd')
        usage.update(input_tokens=tokens.get('input_tokens'), output_tokens=tokens.get('output_tokens'),
                     cost_usd=cost if type(cost) in (int, float) else None, turns=_turns(agent, parsed, raw),
                     reported=bool(tokens))
        config_events = parsed.get('config_events') or []
        if agent == 'gemini' and (transport.get('configuration_sha256') is not None):
            # _google's declaration-only label describes unmanaged CLI calls. A worker has an isolated,
            # generated home; actual config-load events are retained and still refuse attestation.
            config_events = [event for event in config_events if event.get('type') != 'declared']
        from . import provider_usage
        counter = provider_usage.decode(raw, agent)
        if counter.get('status') == 'reported':
            split = counter['usage']
            usage.update(input_tokens=sum(split[k] for k in ('input_tokens', 'cache_creation_input_tokens',
                         'cache_read_input_tokens')), output_tokens=split['output_tokens'],
                         turns=counter['requests'], reported=True)
            if usage['cost_usd'] is None and observed is not None:
                from .. import model_catalogue
                usage['cost_usd'] = model_catalogue.price(split, observed)['cost_usd']
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
    if transport.get('project_instructions') is not None:
        # Whether the CLI itself reported loading an instruction file: True or False from its own
        # configuration report, None when this output format carries no such report.
        reported = None
        if parsed is not None and str(parsed.get('config_basis', '')).startswith('stream-json init event'):
            reported = any('memory_paths' in (event.get('names') or []) for event in config_events)
        transport['project_instructions'] = project_instructions.with_cli_report(
            transport['project_instructions'], reported)
    from . import provider_usage
    transport['observation'] = {'envelope_error': error, 'limits': checks, 'config_events': config_events,
                                'provider_usage': provider_usage.capture(run, spec['node_id'], spec['attempt'], agent),
                                'stdout_sha256': broker.sha(stdout) if stdout.is_file() else None,
                                'attestation_reasons': reasons}
    if execution.get('exit_status') not in (None, 0):
        from . import cli_login
        stderr = agent_worker.capture_path(run, spec['node_id'], spec['attempt'], 'stderr')
        transport['observation']['failure_diagnostic'] = {
            'exit_status': execution.get('exit_status'), 'stderr_tail': cli_login.safe_error(_error_tail(stderr)),
            'stdout_tail': cli_login.safe_error(_error_tail(stdout)),
            'remedy': (cli_login.remedy(transport['login_source'],
                                       config=(transport.get('launch_env') or {}).get('CLAUDE_CONFIG_DIR'))
                       if transport.get('login_source')
                       else 'Inspect the retained worker error, restore the CLI login, and retry the attempt.')}
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


# The worker's own channel for its final answer: the CLI's --json-schema answer, and the RAVEL loop's
# ``submit_final`` tool. Neither can read, write or run anything, so listing one is not a capability beyond
# the RAVEL tools (live evidence: Claude Code 2.1.296 lists StructuredOutput beside mcp__ravel__*).
ANSWER_CHANNEL_TOOLS = frozenset({'StructuredOutput', 'submit_final'})


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


def _qualifier_adapter(document):
    """The launch adapter of the declaration's kind: this module for a CLI worker, the loop adapter for a loop."""
    if document['transport_kind'] == 'cli-worker':
        return sys.modules[__name__]
    if document['transport_kind'] == 'ravel-loop':
        return tr.adapter_module('ravel-loop')
    _refuse('transport_kind:' + document['transport_kind'], 'only a CLI worker or a RAVEL loop route is qualified here')


def _current_executable(adapter, document, run):
    """The sha256 of what would run now: the CLI on PATH, or the loop's code identity."""
    if adapter is sys.modules[__name__]:
        return tr.resolve_executable(document)[1]
    return adapter.current_probe(document, run)[2]


def qualify(transport_id, *, rundir, model, effort=None, max_cost_usd=None, instructions=None,
            controller_rundir=None):
    """Run the conformance task live through ``prepare_launch`` in the sandbox; write the record only if every step passed.

    Returns the qualification record. Raises ``LaunchRefused`` (nothing started) or
    ``QualificationFailed`` (the run happened; the failed steps are named; no record).
    ``instructions`` names a project instruction document: the conformance run pins it, and the
    added step ``project_instructions_recorded`` passes only when the receipt shows its delivery.
    A RAVEL loop route is qualified the same way through its own adapter
    (``ravel.workflow.transports.ravel_loop``); its record is written for the loop's code identity.
    """
    from .. import agent_worker
    from ..review_independence import controller_store
    # The operator may qualify into an existing controller run while keeping the
    # conformance workspace empty and independent of its scientific inputs.
    store = controller_store(controller_rundir if controller_rundir is not None else rundir)
    if controller_rundir is not None and store is None:
        _refuse('controller-rundir:not-owned', str(controller_rundir))
    document = tr.load(transport_id)
    adapter = _qualifier_adapter(document)
    problem = adapter.unsupported(document) or tr.executor_problem(document)
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
    probe, executable, executable_sha = adapter.current_probe(document, run)
    pinned = None
    if instructions is not None:
        try:
            project_instructions.declare(run, instructions)
            pinned = project_instructions.for_run(run)
        except project_instructions.ProjectInstructionsError as exc:
            raise LaunchRefused(str(exc), exc.missing) from None
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
    descriptor = adapter.prepare_launch(run, spec, ws, selection=selection, card=card, atlas=_conformance_atlas())
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
        ('executable_unchanged', _current_executable(adapter, document, run) == executable_sha),
        ('surface_ravel_only', bool(surface['ravel']) and surface['unexpected'] == []),
    ]
    if pinned is not None:
        steps.append(('project_instructions_recorded', project_instructions.receipt_problem(receipt, pinned) is None))
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
    if store is not None:
        tr.record_qualification(store, record)
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
    parser.add_argument('--controller-rundir', type=Path,
                        help='controller-owned run receiving the successful qualification observation')
    parser.add_argument('--model', required=True)
    parser.add_argument('--effort')
    parser.add_argument('--max-cost-usd', type=float)
    parser.add_argument('--project-instructions', type=Path,
                        help='a project instruction document to pin for the conformance run; the receipt must record it')
    # Kept outside the qualification itself: the operator's own terminal retains the passed record for every later
    # controller run, which adopts it at intake while it still matches (``controller.authority.qualifications``).
    parser.add_argument('--for-operator', action='store_true',
                        help='retain the qualification for every later controller run (adopted at intake)')
    args = parser.parse_args(argv)
    try:
        record = qualify(args.transport_id, rundir=args.rundir, model=args.model, effort=args.effort,
                         max_cost_usd=args.max_cost_usd, instructions=args.project_instructions,
                         controller_rundir=args.controller_rundir)
    except LaunchRefused as exc:
        print(json.dumps({'status': 'refused', 'missing': exc.missing, 'detail': str(exc)}, indent=2))
        return 3
    except QualificationFailed as exc:
        print(json.dumps({'status': 'failed', 'failed_steps': exc.failed,
                          'receipt_status': exc.receipt.get('status'), 'failure': exc.receipt.get('failure'),
                          'failure_diagnostic': ((exc.receipt.get('transport') or {}).get('observation') or {}).get(
                              'failure_diagnostic')}, indent=2))
        return 4
    if args.for_operator:
        from ravel.controller.authority import common as authority_common, qualifications
        try:
            record = {**record, 'operator_area': qualifications.record(record)}
        except (authority_common.AuthorityRefused, ValueError, OSError) as exc:
            print(json.dumps({'status': 'refused', 'missing': ['operator_area'], 'detail': str(exc)}, indent=2))
            return 3
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0
