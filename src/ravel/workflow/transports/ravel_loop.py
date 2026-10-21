"""RAVEL loop launch adapter: the RAVEL HTTP loop as a sandboxed tool-using worker.

The implementation of the loop lives in ``ravel.transports.ravel_loop`` (re-exported here); its worker
executable is ``ravel.transports.ravel_loop_worker``. This module is the declared registry path of the
``ravel-loop`` kind (``transport_registry.EXECUTOR_MODULES`` and ``ADAPTER_MODULES``) and gives the
dispatcher the same four calls the CLI worker adapter gives it:

- ``unsupported(document)`` names why this adapter cannot launch a declaration (None when it can);
- ``current_probe(document, run)`` is the code identity a live qualification is written for: RAVEL's own
  interpreter and the sources of the worker, the loop, the chat model and the provider wire formats.
  There is no third-party executable to probe;
- ``prepare_launch(rundir, spec, workspace, ...)`` returns the trusted descriptor with exactly the CLI
  adapter's keys. Selection, admission, provider policy, the toolbelt the governed step admitted, the
  controller packet as the prompt (on standard input, kept in custody with an audit record) and the
  closed final-record schema are the CLI adapter's own functions. The argv starts the worker module
  with RAVEL's interpreter; ``inputs/loop.json`` (written once, read-only) carries the endpoint,
  adapter, model, effort, session id, budgets and the credential's variable name. The variable is
  passed to the child by name only (``pass_env_names``); a missing one refuses with its name;
- ``observe(rundir, descriptor, ws, spec, execution)`` reads the worker's result envelope from the
  supervisor's pipe capture into the receipt: final record, session (it must be the one minted here),
  observed model, usage and limits.

What this adapter refuses, and why (each is a typed ``unsupported`` reason):

- ``endpoint:undeclared`` and ``adapter:endpoint``: the declaration names no endpoint, or one whose
  path selects no provider wire format;
- ``auth:<kind>``: a token command would have to run inside the worker sandbox;
- ``cost_budget`` / ``cost_unenforceable``: an API route needs an explicit finite ceiling and
  catalogue context/output limits and tariffs. Each call reserves a context-full upper bound;
  provider-reported usage is priced at the pinned tariff before another call can start;
- ``sandbox_egress:<port>``: remote endpoints use the provider port; local endpoints use a
  separately declared port grant. Linux requires a working port filter for local endpoints;
- ``effort_control:<adapter>``: the declaration claims effort control the adapter cannot carry.

Pinned project instructions are delivered verbatim before the role packet and rechecked by the
supervisor before launch. Inner LangGraph nodes borrow that supervisor's real steering admission
over a lifetime-bound broker connection; the sandbox never receives machine custody. Each admission
is recorded against its original parent node and attempt. Provider redirects are refused.

"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import urlsplit

from .. import broker, project_instructions, sandbox, transport_registry as tr
from ..state_io import atomic_json
from . import cli_worker
from .cli_worker import DESCRIPTOR_KEYS, LaunchRefused

__all__ = ['RavelLoop', 'build', 'unsupported', 'current_probe', 'prepare_launch', 'observe', 'remove_home',
           'adapter_of', 'LaunchRefused', 'AGENT']

AGENT = 'ravel-loop'
WORKER_MODULE = 'ravel.transports.ravel_loop_worker'
CONFIG = 'inputs/loop.json'
# The endpoint path selects the provider wire format (``provider_tools.ADAPTERS``).
ENDPOINT_ADAPTERS = (('/messages', 'anthropic'), (':generateContent', 'gemini'), ('/responses', 'responses'),
                     ('/chat/completions', 'chat_completions'))
TOKEN_LIMIT_FIELDS = {'chat_completions': 'max_completion_tokens'}
MAX_OUTPUT_TOKENS = 16384
# Code whose identity a live qualification of a loop route is written for.
IDENTITY_MODULES = ('ravel.transports.ravel_loop_worker', 'ravel.transports.ravel_loop',
                    'ravel.workflow.ravel_chat_model', 'ravel.workflow.provider_tools',
                    'ravel.workflow.provider_transport', 'ravel.workflow.transports.ravel_loop',
                    'ravel.workflow.transports.loop_control', 'ravel.workflow.broker', 'ravel.workflow.gate_wiring',
                    'ravel.workflow.transports.provider_usage', 'ravel.workflow.model_catalogue',
                    'ravel.workflow.transports.cli_worker', 'ravel.workflow.agent_worker',
                    'ravel.workflow.toolbelt', 'ravel.workflow.broker_mcp',
                    'ravel.workflow.project_instructions', 'ravel.workflow.sandbox')
LOOP_VERSION = 'ravel-loop 1'


def __getattr__(name):
    # The loop implementation imports the graph substrate; selection and admission need none of it.
    if name in ('RavelLoop', 'build'):
        from ravel.transports import ravel_loop
        return getattr(ravel_loop, name)
    raise AttributeError(name)


def _refuse(item, detail=None):
    raise LaunchRefused(f'ravel loop refused: {item}' + (f' ({detail})' if detail else ''), [item])


def adapter_of(document):
    """The provider wire format the declaration's endpoint path selects, or None."""
    endpoint = document.get('endpoint')
    if type(endpoint) is not str:
        return None
    path = urlsplit(endpoint).path
    return next((adapter for suffix, adapter in ENDPOINT_ADAPTERS if path.endswith(suffix)), None)


def _port(endpoint):
    parsed = urlsplit(endpoint)
    return parsed.port or (443 if parsed.scheme == 'https' else 80)


def unsupported(document):
    """Why this adapter cannot launch the declaration (None when it can)."""
    from ..provider_tools import EFFORT_FIELDS
    if document['transport_kind'] != 'ravel-loop':
        return 'transport_kind:' + document['transport_kind']
    if document['id'] in tr.UNIMPLEMENTED_ROUTES:
        return 'unimplemented:' + document['id']
    if type(document.get('endpoint')) is not str:
        return 'endpoint:undeclared'
    adapter = adapter_of(document)
    if adapter is None:
        return 'adapter:endpoint'
    if document['auth']['kind'] not in ('env', 'none') or (document['auth']['kind'] == 'env'
                                                          and len(document['auth']['env_names']) != 1):
        return 'auth:' + document['auth']['kind']
    port = _port(document['endpoint'])
    if port != sandbox.PROVIDER_PORT and not tr.is_loopback(document['endpoint']):
        return f'sandbox_egress:{port}'
    if port != sandbox.PROVIDER_PORT and sandbox.available() == 'linux' and not sandbox.linux_port_rules():
        return 'sandbox_loopback_port_filter_unavailable'
    if document['capabilities']['effort_control'] and adapter not in EFFORT_FIELDS:
        return 'effort_control:' + adapter
    return None


def current_probe(document, run=None):
    """(identity record, worker path, sha256): the code a loop qualification counts for."""
    import importlib
    sources = {}
    for name in IDENTITY_MODULES:
        path = Path(importlib.import_module(name).__file__)
        sources[name] = tr.file_sha256(path)
    worker = str(Path(importlib.import_module(WORKER_MODULE).__file__).resolve())
    executable = str(Path(sys.executable).absolute())
    interpreter_sha = tr.file_sha256(executable)
    sha = tr.digest({'interpreter': executable, 'interpreter_sha256': interpreter_sha, 'sources': sources})
    record = {'schema_version': 1, 'kind': 'ravel-loop-identity', 'transport_id': document['id'],
              'declaration_sha256': tr.declaration_sha256(document), 'cli_version': LOOP_VERSION,
              'interpreter': executable, 'interpreter_sha256': interpreter_sha, 'sources': sources, 'executable_path': worker, 'executable_sha256': sha,
              'unusable': []}
    return record, worker, sha


def remove_home(ws, descriptor):
    """Loop worker configuration lives in its workspace."""
    return None


# The broker socket path the child reaches, as for a CLI worker (a fixed path inside the Linux namespace).
_socket_path = cli_worker._socket_path


def _command(ws, socket_path):
    package = str(Path(__file__).resolve().parents[3])
    bootstrap = (f'import sys;sys.path.insert(0,{package!r});'
                 f'from {WORKER_MODULE} import main;raise SystemExit(main())')
    return [sys.executable, '-B', '-c', bootstrap, '--workspace', str(ws), '--config', str(ws / CONFIG),
            '--socket', str(socket_path)]


def prepare_launch(rundir, spec, workspace, *, selection=None, card=None, atlas=None, controller=None):
    """The trusted launch descriptor for one loop worker attempt, or ``LaunchRefused`` naming what is missing.

    ``selection``, ``card`` and ``atlas`` are for trusted code only (qualification); ``controller`` carries a
    controller seat's launch facts, as for the CLI worker adapter.
    """
    from .. import agent_worker, provider_policy, toolbelt
    from ..provider_tools import EFFORT_FIELDS
    run = broker.ordinary(rundir)
    spec = agent_worker._validate(spec)
    ws = broker.ordinary(workspace)
    if ws != agent_worker.workspace(run, spec['node_id'], spec['attempt']):
        _refuse('workspace', 'not this attempt\'s workspace')
    card = cli_worker._card(spec, card)
    packet_text = None
    if controller is not None or spec.get('final_record_schema') == agent_worker.CONTROLLER_SCHEMA:
        packet_text = cli_worker._controller_facts(spec, controller, ws)
        selection = controller['selection']
    selected = deepcopy(selection) if selection is not None else cli_worker._select(run, spec, card)
    document = tr.load(selected['transport_id'])
    if packet_text is not None:
        from ravel.controller.step.seats import admission_problem
        problem = admission_problem(document)
        if problem is not None:
            _refuse('controller:transport', problem)
    try:
        admission = provider_policy.admission(run, document, provider_policy.account_class(document),
                                             input_pins=spec['inputs'])
    except provider_policy.PolicyRefused as exc:
        raise LaunchRefused(str(exc), ['provider_policy']) from None
    if document['transport_kind'] != 'ravel-loop':
        _refuse('transport_kind:' + document['transport_kind'], 'a loop worker never falls back to another route')
    problem = tr.executor_problem(document)
    if problem:
        _refuse(problem)
    probe, executable, executable_sha = current_probe(document, run)
    if selected.get('probe_sha256') is not None and selected['probe_sha256'] != tr.digest(probe):
        _refuse('probe:changed')
    adapter = adapter_of(document)
    model, effort = selected['model'], selected.get('effort')
    if type(model) is not str or not tr.MODEL_ID.match(model):
        _refuse('model:invalid')
    if effort is not None and (not document['capabilities']['effort_control'] or adapter not in EFFORT_FIELDS):
        _refuse('effort')
    from .. import model_catalogue
    cap = spec['budgets']['max_cost_usd']
    bound = None
    if document['billing'] == 'api' and cap is None:
        _refuse('cost_budget', 'an API loop needs a finite max_cost_usd; set a per-step cost budget')
    if cap is not None:
        try:
            bound = model_catalogue.call_bound(model)
        except ValueError as exc:
            _refuse('cost_unenforceable', str(exc))
        if bound['cost_usd'] > cap:
            _refuse('cost_budget', f"one context-full call reserves USD {bound['cost_usd']:.6g}; "
                    'raise the authorised cap or choose another model explicitly')
    try:
        pinned = project_instructions.for_run(run)
    except project_instructions.ProjectInstructionsError as exc:
        raise LaunchRefused(str(exc), exc.missing) from None
    instruction_record, prefix = None, ''
    if pinned is not None:
        _, prefix, instruction_record = project_instructions.deliver(
            pinned, AGENT, probe, declaration=document, ancestor_files=[],
            carrier=ws / 'inputs' / project_instructions.CARRIER_NAME)
    auth = document['auth']
    names = list(auth['env_names']) if auth['kind'] == 'env' else []
    for name in names:
        if not os.environ.get(name):
            _refuse('credential:' + name, 'set it in the dispatcher\'s environment; its value is never recorded')
    blind = spec['role']['id'] in agent_worker.blind_roles()
    card_blind = not blind and (card.get('requires') or {}).get('blind') is True
    try:
        belt = cli_worker.toolbelt_for(card, document, blind, atlas=atlas,
                                       blind_actions=agent_worker.blind_actions(card) if card_blind else None)
    except toolbelt.ToolbeltError as exc:
        raise LaunchRefused(f'ravel loop refused: toolbelt:{exc}', ['toolbelt']) from None
    if packet_text is not None and (controller.get('toolbelt') or {}).get('manifest_sha256') != belt['manifest_sha256']:
        _refuse('controller:toolbelt', 'the worker toolbelt differs from the one the governed step admitted')
    belt_path = cli_worker._write_once(ws / 'inputs' / 'toolbelt.json', json.dumps(belt, indent=1, sort_keys=True))
    schema = controller['schema'] if packet_text is not None else cli_worker.FINAL_JSON_SCHEMAS[spec['final_record_schema']]
    schema_path = cli_worker._write_once(ws / 'inputs' / 'final-schema.json', json.dumps(schema, sort_keys=True))
    socket_path = cli_worker._socket_path(run, ws, spec)
    budgets = spec['budgets']
    session = 'ravel-loop-' + uuid.uuid4().hex
    key = agent_worker._key(spec['node_id'], spec['attempt'])
    custody = broker.custody(run)
    # A reattached preparation of the same attempt keeps the session it minted first (the config is written once).
    config_path = ws / CONFIG
    if config_path.is_file() and not config_path.is_symlink():
        try:
            session = json.loads(config_path.read_text())['session_id']
        except (ValueError, KeyError, TypeError):
            _refuse('workspace:adapter-file-changed', CONFIG)
    config = {'schema_version': 1, 'kind': 'ravel-loop-worker-config', 'transport_id': document['id'],
              'declaration_sha256': tr.declaration_sha256(document), 'endpoint': document['endpoint'],
              'adapter': adapter, 'model': model, 'effort': effort, 'session_id': session,
              'auth': {'kind': auth['kind'], 'env_name': names[0] if names else None,
                       'header_style': auth.get('header_style')},
              'max_output_tokens': min(MAX_OUTPUT_TOKENS, bound['max_output_tokens']) if bound else MAX_OUTPUT_TOKENS,
              'cost_bound': bound,
              'token_limit_field': TOKEN_LIMIT_FIELDS.get(adapter, 'max_completion_tokens'),
              'node_id': spec['node_id'], 'attempt': spec['attempt'],
              'budgets': {'max_turns': budgets['max_turns'], 'max_wall_seconds': budgets['max_wall_seconds'],
                          'max_broker_calls': budgets['max_broker_calls'], 'max_cost_usd': cap,
                          'max_steps': budgets['max_broker_calls']},
              'toolbelt': 'inputs/toolbelt.json', 'toolbelt_manifest_sha256': belt['manifest_sha256'],
              'final_schema': 'inputs/final-schema.json'}
    config_path = cli_worker._write_once(config_path, json.dumps(config, indent=1, sort_keys=True))
    prompt = prefix + (cli_worker.build_controller_prompt(packet_text, spec, ws, belt, structured=True)
              if packet_text is not None
              else cli_worker.build_prompt(card, spec, ws, belt, agent=AGENT, structured=True))
    prompt += ('\nFinish by calling the submit_final tool with the final record; a reply without a tool '
               'call is not a final record.\n')
    prompt_path = custody / (key + '.prompt.txt')
    if not prompt_path.exists() or prompt_path.read_text() != prompt:
        prompt_path.write_text(prompt)
    argv = _command(ws, socket_path)
    command = cli_worker.mcp_command(ws, belt_path, socket_path)
    tools = [t['name'] for t in belt['tools'] if t['executes_through']['action'] is not None]
    pass_env = sorted(n for n in names if n not in agent_worker.RESERVED_ENV)
    read_paths = sandbox.runtime_paths(argv)
    allowed = sorted({t['executes_through']['action'] for t in belt['tools'] if t['executes_through']['action']})
    audit = {'schema_version': 1, 'kind': 'ravel-loop-prompt-audit', 'node_id': spec['node_id'],
             'provider_policy': admission, 'attempt': spec['attempt'], 'role': spec['role'],
             'transport_id': document['id'], 'declaration_sha256': tr.declaration_sha256(document),
             'probe_sha256': tr.digest(probe), 'executable_path': executable, 'executable_sha256': executable_sha,
             'prompt': {'path': str(prompt_path), 'sha256': broker.sha(prompt_path),
                        'bytes': prompt_path.stat().st_size, 'channel': 'stdin'},
             'argv': argv, 'argv_sha256': broker.digest(argv), 'pass_env_names': pass_env,
             'config': {'path': str(config_path), 'sha256': broker.sha(config_path)},
             'final_schema_sha256': broker.sha(schema_path), 'toolbelt_manifest_sha256': belt['manifest_sha256'],
             'tools': tools, 'blind': blind, 'model': model, 'effort': effort, 'session_id': session,
             'created_utc': broker.utc()}
    if instruction_record is not None:
        audit['project_instructions'] = instruction_record
    audit_path = custody / (key + '.prompt-audit.json')
    atomic_json(audit_path, audit)
    transport = {'id': document['id'], 'transport_kind': 'ravel-loop', 'agent': AGENT, 'adapter': adapter,
                 'endpoint': document['endpoint'], 'provider_policy': admission,
                 'declaration_sha256': tr.declaration_sha256(document), 'declaration_origin': tr.origin(document),
                 'declared_attestation': document['capabilities']['attestation'],
                 'probe_sha256': tr.digest(probe), 'cli_version': LOOP_VERSION,
                 'executable_path': executable, 'executable_sha256': executable_sha,
                 'stdin': {'path': str(prompt_path), 'sha256': broker.sha(prompt_path)},
                 'prompt_audit': {'path': str(audit_path), 'sha256': broker.sha(audit_path)},
                 'config': {'path': str(config_path), 'sha256': broker.sha(config_path)},
                 'session_id': session, 'cli_home': None, 'cli_home_owned': False, 'user_home': None,
                 'launch_env': {}, 'verified_env': [], 'network': ('provider' if _port(document['endpoint']) == sandbox.PROVIDER_PORT else
                     {'kind': 'loopback', 'host': urlsplit(document['endpoint']).hostname, 'port': _port(document['endpoint'])}),
                 'structured_output': 'enforced',
                 'mcp_command': list(command),
                 'toolbelt': {'path': str(belt_path), 'manifest_sha256': belt['manifest_sha256']},
                 'user_configuration_declared_loaded': False,
                 'limits': {'max_turns': budgets['max_turns'], 'max_cost_usd': cap}, 'receipt': None}
    if instruction_record is not None:
        transport['project_instructions'] = instruction_record
    if packet_text is not None:
        transport['controller'] = {'schema': deepcopy(schema), 'schema_sha256': tr.digest(schema),
                                   'packet_sha256': controller['packet_sha256'],
                                   'manifest_sha256': controller.get('manifest_sha256'),
                                   'step_id': controller.get('step_id'), 'seat': controller.get('seat')}
    descriptor = {'argv': argv, 'transport': transport,
                  'model': {'requested': model, 'observed': None,
                            'family': selected.get('family') or tr.family_of(document, model), 'effort': effort},
                  'pass_env_names': pass_env, 'read_paths': read_paths, 'allowed_actions': allowed,
                  'forbidden_sources': []}
    assert tuple(descriptor) == DESCRIPTOR_KEYS
    return descriptor


def _envelope(raw):
    try:
        document = json.loads(raw)
    except ValueError:
        return None
    if type(document) is not dict or document.get('type') != 'ravel-loop-result' or document.get('schema_version') != 1:
        return None
    return document


def observe(rundir, descriptor, ws, spec, execution):
    """The worker's result envelope as the receipt's final record, session, usage, model and limits."""
    from .. import agent_worker
    from . import provider_usage
    run, ws = broker.ordinary(rundir), broker.ordinary(ws)
    transport = deepcopy(descriptor['transport'])
    stdout = agent_worker.capture_path(run, spec['node_id'], spec['attempt'], 'stdout')
    raw = stdout.read_text(errors='replace') if stdout.is_file() and stdout.stat().st_size <= broker.MAX_MESSAGE else ''
    envelope = _envelope(raw)
    error = None if envelope is not None else 'parse'
    usage = {'input_tokens': None, 'output_tokens': None, 'cost_usd': None, 'reported': False, 'turns': None}
    final, session, observed = None, None, None
    if envelope is not None:
        if envelope.get('status') != 'completed':
            error = 'status:' + str(envelope.get('status'))
        final = envelope.get('final') if type(envelope.get('final')) is dict else None
        session = envelope.get('session_id') if type(envelope.get('session_id')) is str else None
        models = sorted({t.get('model') for t in envelope.get('turns') or () if type(t) is dict
                         and type(t.get('model')) is str})
        # One served model across the session, as the provider reported it; several stay unresolved.
        turns_ = envelope.get('turns') or []
        complete_models = all(type(t) is dict and type(t.get('model')) is str and t['model'] for t in turns_)
        observed = models[0] if len(models) == 1 and complete_models else None
        record = provider_usage.decode(raw, AGENT)
        turns = envelope.get('num_turns') if type(envelope.get('num_turns')) is int else None
        if record['status'] == 'reported':
            split = record['usage']
            priced = None
            if observed is not None:
                from .. import model_catalogue
                priced = model_catalogue.price(split, observed)['cost_usd']
            usage.update(cost_usd=priced, input_tokens=split['input_tokens'] + split['cache_creation_input_tokens']
                         + split['cache_read_input_tokens'], output_tokens=split['output_tokens'], reported=True)
        usage['turns'] = turns
    limits = transport['limits']
    checks = {'turns': {'observed': usage['turns'], 'max': limits['max_turns'],
                        'within': usage['turns'] is not None and usage['turns'] <= limits['max_turns']},
              'cost': {'observed': usage['cost_usd'], 'max': limits['max_cost_usd'],
                       'within': limits['max_cost_usd'] is None or usage['cost_usd'] is not None
                       and usage['cost_usd'] <= limits['max_cost_usd']}}
    isolation = deepcopy(execution.get('isolation') or {'profile': 'unestablished', 'user_configuration_loaded': True,
                                                          'evidence': {}})
    isolation['user_configuration_loaded'] = bool(isolation.get('user_configuration_loaded'))
    reasons = []
    if error:
        reasons.append('envelope:' + error)
    if execution.get('exit_status') != 0:
        reasons.append('exit')
    if session is None or session != transport.get('session_id'):
        reasons.append('session_id')
    elif cli_worker._session_reused(run, transport['id'], session):
        reasons.append('session_reused')
    if isolation['user_configuration_loaded']:
        reasons.append('user_configuration_loaded')
    if not (isolation.get('evidence') or {}).get('confirmed'):
        reasons.append('isolation_unconfirmed')
    if transport['declared_attestation'] != 'transport':
        reasons.append('declared_attestation')
    transport['observation'] = {'envelope_error': error, 'limits': checks, 'config_events': [],
                                'provider_usage': provider_usage.capture(run, spec['node_id'], spec['attempt'], AGENT),
                                'stdout_sha256': broker.sha(stdout) if stdout.is_file() else None,
                                'attestation_reasons': reasons}
    result = {'final': final, 'session_id': session, 'usage': usage, 'cli_version': transport['cli_version'],
              'model': {**descriptor['model'], 'observed': observed}, 'isolation': isolation,
              'attestation': 'transport_attested' if not reasons else 'host_attested', 'transport': transport}
    if not all(c['within'] for c in checks.values()):
        result['budget_exhausted'] = True
    return result
