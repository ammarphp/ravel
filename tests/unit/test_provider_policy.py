"""Synthetic transport-policy boundaries; no network or native scientific jobs."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import agent_graph as graph, cli_agent_host as cli
from ravel.workflow import provider_policy as policy, provider_transport, transport_registry as tr
from ravel.workflow import transport_receipt
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.transports import cli_worker


def declaration(*ids, level='restricted'):
    return {'level': level, 'allowed_providers': [
        {'transport_id': name, 'account_class': policy.account_class(tr.load(name))} for name in ids]}


def run_at(path, *ids, level='restricted'):
    policy.start(path, data_classification=declaration(*ids, level=level))
    return path


@pytest.mark.parametrize('level', ['restricted', 'internal', 'public'])
def test_exact_transport_and_account(level, tmp_path):
    run = run_at(tmp_path / 'run', 'http-anthropic', level=level)
    route = tr.load('http-anthropic')
    assert policy.check(run, route, 'env:api') == declaration('http-anthropic')['allowed_providers'][0]
    for selected, account in [(tr.load('http-responses'), 'env:api'), (route, 'login:subscription')]:
        with pytest.raises(policy.PolicyRefused, match=f'{level}.*transport {selected["id"]}'):
            policy.check(run, selected, account)


def test_implicit_public_and_explicit_deny_all(tmp_path):
    route = tr.load('http-responses')
    assert policy.check(tmp_path / 'legacy', route, 'env:api') is None
    assert policy.admission(None, None, 'unknown')['data_classification'] == policy.PUBLIC
    run = run_at(tmp_path / 'closed')
    with pytest.raises(policy.PolicyRefused, match='restricted.*http-responses'):
        policy.check(run, route, 'env:api')


@pytest.mark.parametrize('mutation', ['replace', 'delete', 'add_to_public'])
def test_mutation_without_approval_refused(tmp_path, mutation):
    run = tmp_path / 'run'
    if mutation == 'add_to_public':
        policy.start(run)
    else:
        run_at(run, 'http-anthropic')
    if mutation == 'delete':
        (run / policy.CONFIG).unlink()
    else:
        atomic_json(run / policy.CONFIG, declaration('http-responses'))
    with pytest.raises(policy.PolicyRefused, match='changed without an explicit approval'):
        policy.check(run, tr.load('http-responses'), 'env:api')


def approval(previous, replacement):
    return {'kind': 'provider-policy-approval', 'approved': True, 'authority': 'human',
            'approved_by': 'operator', 'approved_utc': '2026-01-01T00:00:00Z', 'reason': 'changed data access',
            'previous_sha256': tr.digest(previous), 'replacement_sha256': tr.digest(replacement)}


def test_explicit_approval_binds_both_policies_and_retains_initial(tmp_path):
    run = run_at(tmp_path / 'run', 'http-anthropic')
    previous = policy.start(run)
    value = declaration('http-responses')
    replacement = {'data_classification': value, 'declared': True}
    record = approval(previous, replacement)
    for key, bad in [('approved', False), ('authority', 'model'), ('previous_sha256', 'a' * 64),
                     ('replacement_sha256', 'b' * 64), ('approved_by', ''), ('reason', '')]:
        with pytest.raises(policy.PolicyRefused, match='explicit human approval'):
            policy.approve_change(run, value, {**record, key: bad})
    policy.approve_change(run, value, record)
    assert policy.check(run, tr.load('http-responses'), 'env:api') == value['allowed_providers'][0]
    state = read_json(run / policy.PIN)
    assert state['initial'] == previous and state['changes'][0]['approval'] == record
    with pytest.raises(policy.PolicyRefused):
        policy.approve_change(run, value, record)  # stale approval


@pytest.mark.parametrize('pins', [[{'path': 'synthetic.txt', 'restricted': True}],
                                 [{'pin': {'restricted': True}, 'as': 'inputs/synthetic.txt'}]])
def test_restricted_pins_require_restricted_declaration(tmp_path, pins):
    for value in (None, declaration('http-anthropic', level='public')):
        with pytest.raises(policy.PolicyRefused, match='restricted input pins'):
            policy.start(tmp_path / 'run', data_classification=value, input_pins=pins)
    assert not (tmp_path / 'run' / policy.PIN).exists()
    policy.start(tmp_path / 'run', data_classification=declaration('http-anthropic'), input_pins=pins)


@pytest.mark.parametrize('value', [False, {}, {'level': 'secret', 'allowed_providers': []},
                                 {'level': 'restricted', 'allowed_providers': ['http-anthropic']},
                                 {'level': 'public', 'allowed_providers': None}])
def test_malformed_declarations_refused(value):
    with pytest.raises(policy.PolicyRefused):
        policy.classification(value)


def test_duplicate_entries_and_malformed_pin_flag():
    value = declaration('http-anthropic', 'http-anthropic')
    with pytest.raises(policy.PolicyRefused, match='duplicate'):
        policy.classification(value)
    with pytest.raises(policy.PolicyRefused, match='boolean'):
        policy.validate_start(None, [{'restricted': 'true'}])


def test_explicit_account_class_in_custom_declaration(tmp_path):
    route = deepcopy(tr.load('http-anthropic'))
    route['account_class'] = 'organisation-api'
    tr.validate(route)
    value = {'level': 'restricted', 'allowed_providers': [
        {'transport_id': route['id'], 'account_class': 'organisation-api'}]}
    run = tmp_path / 'run'
    policy.start(run, data_classification=value)
    assert policy.check(run, route, 'organisation-api') == value['allowed_providers'][0]
    with pytest.raises(policy.PolicyRefused):
        policy.check(run, route, 'env:api')
    route['account_class'] = ''
    with pytest.raises(ValueError, match='account_class'):
        tr.validate(route)


@pytest.fixture
def synthetic_cli(monkeypatch):
    facts = {'pid': 1, 'pgid': 1, 'started_utc': 'synthetic', 'finished_utc': 'synthetic',
             'exit_status': 0, 'stdout_sha256': 'a' * 64, 'stderr_sha256': 'b' * 64,
             'stdout_bytes': 1, 'stderr_bytes': 0}
    launches = []
    monkeypatch.setattr(cli, 'choose', lambda agent, source: agent)
    monkeypatch.setattr(tr, 'resolve_executable', lambda *a: ('/synthetic/cli', 'a' * 64))
    monkeypatch.setattr(tr, 'read_probe', lambda *a: {'executable_sha256': 'a' * 64})
    monkeypatch.setattr(tr, 'effective_capabilities', lambda *a, **kw: (
        {'tools': 'none', 'attestation': 'host', 'isolation': 'none'}, []))
    monkeypatch.setattr(cli, '_cli_version', lambda *a: 'synthetic')
    monkeypatch.setattr(cli, '_managed_settings', lambda: None)
    monkeypatch.setattr(cli, 'fresh_codex_home', lambda *a: 'fresh')
    def fake_run(*args, **kwargs):
        launches.append(args)
        return json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False,
                           'result': '{"answer":"ok"}', 'session_id': 'synthetic-session',
                           'usage': {'input_tokens': 2, 'output_tokens': 2}}), facts
    monkeypatch.setattr(cli, '_run', fake_run)
    return launches


PARAMETERS = {'model': 'fixture-model', 'reasoning_effort': 'high', 'max_output_tokens': 100,
              'instructions': 'Read supplied evidence.', 'output_schema': None}


def test_oneshot_refused_before_process_or_credentials(tmp_path, synthetic_cli, monkeypatch):
    run = run_at(tmp_path / 'run', 'http-anthropic')
    monkeypatch.setattr(cli, 'fresh_codex_home', lambda *a: pytest.fail('credentials touched'))
    with pytest.raises(cli.AgentCLIError, match='restricted.*codex-cli-oneshot'):
        cli.invoke('codex', PARAMETERS, {'provider_policy_run': str(run)})
    assert synthetic_cli == []


def test_oneshot_allowed_receipt_and_legacy_shape(tmp_path, synthetic_cli):
    run = run_at(tmp_path / 'run', 'claude-cli-oneshot')
    answer = cli.invoke('claude', PARAMETERS, {}, rundir=run)
    assert len(synthetic_cli) == 1
    receipt = answer['receipt']
    row = receipt['configuration']['provider_policy']
    assert row['data_classification']['level'] == 'restricted'
    assert row['admitted_entry'] == declaration('claude-cli-oneshot')['allowed_providers'][0]
    transport_receipt.shape(receipt)
    assert policy.prompt_log_fields(receipt) == row
    row['admitted_entry']['transport_id'] = 'http-responses'
    with pytest.raises(transport_receipt.ReceiptError):
        transport_receipt.shape(receipt)
    del receipt['configuration']['provider_policy']
    transport_receipt.shape(receipt)


def test_worker_refused_before_probe_or_credentials(tmp_path, monkeypatch):
    run = run_at(tmp_path / 'run', 'http-anthropic')
    from ravel.workflow import agent_worker as worker
    monkeypatch.setattr(worker, '_validate', lambda spec: spec)
    monkeypatch.setattr(worker, 'workspace', lambda *a: tmp_path / 'workspace')
    monkeypatch.setattr(cli_worker, '_card', lambda *a: {})
    monkeypatch.setattr(cli_worker, 'current_probe', lambda *a: pytest.fail('probe reached'))
    with pytest.raises(cli_worker.LaunchRefused, match='restricted.*claude-cli-worker'):
        cli_worker.prepare_launch(run, {'node_id': 'worker', 'attempt': 1, 'inputs': []},
                                  tmp_path / 'workspace', selection={'transport_id': 'claude-cli-worker'})


@pytest.mark.parametrize('adapter,identity', [('anthropic', 'http-anthropic'), ('responses', 'http-responses')])
def test_http_refuses_before_auth_or_network(tmp_path, monkeypatch, adapter, identity):
    from ravel.workflow import agent_host as host
    from test_provider_transport import capabilities, node, request, Control
    run = run_at(tmp_path / 'run', 'claude-cli-worker')
    kw = {'capabilities': capabilities('anthropic')} if adapter == 'anthropic' else {}
    h = host.AgentHost(adapter=adapter, transport=identity, api_key='synthetic', **kw)
    monkeypatch.setattr(h, '_responses', lambda *a, **k: pytest.fail('network reached'))
    monkeypatch.setattr(provider_transport, 'run_token_command', lambda *a, **k: pytest.fail('auth reached'))
    control = Control(); control.root = run
    n = node()
    with pytest.raises(host.HostFailure, match=f'restricted.*{identity}'):
        h.execute(n, request(n), control)
    assert control.calls == []


def test_http_allowed_receipt_and_account_mismatch(tmp_path, monkeypatch):
    from ravel.workflow import agent_host as host
    from test_provider_transport import capabilities, node, request, Control, install_http, document
    run = run_at(tmp_path / 'run', 'http-anthropic')
    seen = install_http(monkeypatch, document('anthropic'))
    h = host.AgentHost(adapter='anthropic', transport='http-anthropic', api_key='synthetic',
                       capabilities=capabilities('anthropic'))
    class ReceiptingControl(Control):
        persisted = None
        def call(self, label, kind, body, function, output_tokens=0):
            result = super().call(label, kind, body, function, output_tokens)
            self.persisted = deepcopy(result)
            return result
    control = ReceiptingControl(); control.root = run
    n = node()
    result = h.execute(n, request(n), control)
    row = result['transport']['provider_policy']
    assert len(seen) == 1 and row['admitted_entry'] == declaration('http-anthropic')['allowed_providers'][0]
    policy.validate_admission(row)
    assert policy.prompt_log_fields(result) == row
    assert control.persisted['transport']['provider_policy'] == row
    h.auth = {'kind': 'command', 'command': ['/synthetic/token'], 'header_style': 'x-api-key'}
    with pytest.raises(host.HostFailure, match='account class command:api'):
        h.execute(n, request(n), control)
    assert len(seen) == 1


def test_http_provider_body_does_not_carry_the_local_run_path(tmp_path, monkeypatch):
    from ravel.workflow import agent_host as host
    from test_provider_transport import capabilities, node, request, Control, install_http, document
    run = run_at(tmp_path / 'run', 'http-anthropic')
    seen = install_http(monkeypatch, document('anthropic'))
    h = host.AgentHost(adapter='anthropic', transport='http-anthropic', api_key='synthetic',
                       capabilities=capabilities('anthropic'))
    control = Control(); control.root = run
    n = node()
    h.execute(n, request(n), control)
    assert len(seen) == 1 and str(run) not in json.dumps(seen[0]['body'])
    assert 'provider_policy_run' not in json.dumps(seen[0]['body'])


def test_oneshot_prompt_and_request_digest_do_not_carry_the_run_path(tmp_path, synthetic_cli):
    run = run_at(tmp_path / 'run', 'claude-cli-oneshot')
    context = {'role': 'synthetic'}
    answer = cli.invoke('claude', PARAMETERS, {**context, 'provider_policy_run': str(run)})
    assert len(synthetic_cli) == 1 and str(run) not in json.dumps(synthetic_cli[0], default=str)
    assert answer['receipt']['content']['request_sha256'] == tr.digest({'parameters': PARAMETERS, 'context': context})


def test_unlabelled_http_cannot_bypass_policy(tmp_path):
    from ravel.workflow import agent_host as host
    from test_provider_transport import node, request, Control
    run = run_at(tmp_path / 'run', 'http-anthropic')
    h = host.AgentHost(api_key='synthetic')
    c = Control(); c.root = run
    n = node()
    with pytest.raises(host.HostFailure, match='transport undeclared'):
        h.execute(n, request(n), c)
    assert not c.calls


def graph_spec(pins, classification=None):
    value = {'schema_version': 1, 'graph_id': 'synthetic',
             'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 200,
                        'max_wall_seconds': 60, 'max_reworks': 0},
             'nodes': [{'id': 'model', 'kind': 'model', 'role': 'proposer', 'depends_on': [],
                        'inputs': pins, 'packet': None, 'action': 'model',
                        'parameters': PARAMETERS, 'max_attempts': 1}]}
    if classification is not None:
        value['data_classification'] = classification
    return value


def test_graph_start_refuses_restricted_input_without_declaration(tmp_path, monkeypatch):
    from ravel.workflow import gate_wiring
    # Steering custody has its own tests; keep this startup policy control inert.
    monkeypatch.setattr(gate_wiring, 'initialize_steering', lambda *a, **k: None)
    pin = {'id': 'input', 'path': str(tmp_path / 'synthetic.txt'), 'sha256': 'a' * 64, 'restricted': True}
    root = tmp_path / 'graph'
    with pytest.raises(policy.PolicyRefused, match='restricted input pins'):
        graph.create(root, graph_spec([pin]))
    assert not root.exists()
    graph.create(root, graph_spec([pin], declaration('http-anthropic')))
    assert read_json(root / policy.PIN)['initial']['data_classification']['level'] == 'restricted'


def test_child_graph_inherits_and_cannot_override(tmp_path, monkeypatch):
    from ravel.workflow import gate_wiring
    monkeypatch.setattr(gate_wiring, 'initialize_steering', lambda *a, **k: None)
    run = run_at(tmp_path / 'run', 'http-anthropic')
    child = run / 'graphs' / 'child'
    graph.create(child, graph_spec([]))
    assert policy.find_run(child) == run
    with pytest.raises(policy.PolicyRefused, match='cannot override'):
        graph.create(run / 'other', graph_spec([], declaration('http-responses')))
    with pytest.raises(policy.PolicyRefused, match='restricted.*http-responses'):
        policy.check(child, tr.load('http-responses'), 'env:api')


def test_symlink_policy_record_refused(tmp_path):
    run = run_at(tmp_path / 'run', 'http-anthropic')
    target = tmp_path / 'replacement.json'
    target.write_text(json.dumps(declaration('http-responses')))
    (run / policy.CONFIG).unlink()
    (run / policy.CONFIG).symlink_to(target)
    with pytest.raises(policy.PolicyRefused, match='symbolic links'):
        policy.check(run, tr.load('http-responses'), 'env:api')


def test_child_configuration_cannot_shadow_pinned_run(tmp_path):
    run = run_at(tmp_path / 'run', 'http-anthropic')
    child = run / 'graphs' / 'child'
    atomic_json(child / policy.CONFIG, declaration('http-responses'))
    assert policy.find_run(child) == run
    with pytest.raises(policy.PolicyRefused, match='restricted.*http-responses'):
        policy.check(child, tr.load('http-responses'), 'env:api')


def test_worker_allowed_admission_survives_descriptor_and_observation(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker as worker, broker, sandbox
    run = run_at(tmp_path / 'run', 'claude-cli-worker')
    ws = tmp_path / 'workspace'
    for name in ('inputs', 'outputs', 'scratch'):
        (ws / name).mkdir(parents=True)
    custody = tmp_path / 'custody'; custody.mkdir()
    home = tmp_path / 'home'; home.mkdir()
    monkeypatch.setattr(worker, '_validate', lambda spec: spec)
    monkeypatch.setattr(worker, 'workspace', lambda *a: ws)
    monkeypatch.setattr(worker, 'blind_roles', lambda: [])
    monkeypatch.setattr(cli_worker, '_card', lambda *a: {})
    monkeypatch.setattr(tr, 'executor_problem', lambda *a: None)
    monkeypatch.setattr(cli_worker, 'current_probe', lambda *a: (
        {'cli_version': 'synthetic'}, '/synthetic/cli', 'a' * 64))
    monkeypatch.setattr(cli_worker, '_no_instruction_files', lambda *a: None)
    monkeypatch.setattr(cli_worker, 'toolbelt_for', lambda *a, **k: {'tools': [], 'manifest_sha256': 'b' * 64})
    monkeypatch.setattr(cli_worker, '_cli_home', lambda *a: (home, False, {}, [], ws / 'inputs' / 'mcp'))
    monkeypatch.setattr(cli_worker, '_socket_path', lambda *a: '/synthetic/broker.sock')
    monkeypatch.setattr(cli_worker, 'build_prompt', lambda *a, **k: 'Synthetic evidence')
    monkeypatch.setattr(sandbox, 'available', lambda: None)
    monkeypatch.setattr(sandbox, 'runtime_paths', lambda *a: [])
    monkeypatch.setattr(broker, 'custody', lambda *a: custody)
    s = {'node_id': 'worker', 'attempt': 1, 'inputs': [], 'role': {'id': 'synthetic'},
         'budgets': {'max_turns': 3, 'max_cost_usd': None}, 'final_record_schema': 'producer.v1'}
    descriptor = cli_worker.prepare_launch(run, s, ws,
        selection={'transport_id': 'claude-cli-worker', 'model': 'fixture-model', 'effort': 'high'})
    row = descriptor['transport']['provider_policy']
    assert row['admitted_entry'] == declaration('claude-cli-worker')['allowed_providers'][0]
    audit = read_json(descriptor['transport']['prompt_audit']['path'])
    assert audit['provider_policy'] == row
    capture = tmp_path / 'stdout'
    capture.write_text(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False,
                                 'result': '', 'session_id': 'synthetic-session',
                                 'structured_output': {'completed': True, 'summary': 'done'}}))
    monkeypatch.setattr(worker, 'capture_path', lambda *a: capture)
    monkeypatch.setattr(cli_worker, '_session_reused', lambda *a: False)
    observed = cli_worker.observe(run, descriptor, ws, s, {'exit_status': 0})
    assert policy.prompt_log_fields(observed) == row


def test_graph_revision_cannot_redeclare_or_add_unclassified_restricted_pins(tmp_path, monkeypatch):
    from ravel.workflow import gate_wiring
    monkeypatch.setattr(gate_wiring, 'initialize_steering', lambda *a, **k: None)
    root = tmp_path / 'graph'
    original = graph_spec([], declaration('http-anthropic'))
    graph.create(root, original)
    replacement = deepcopy(original)
    replacement['data_classification'] = declaration('http-responses')
    with pytest.raises(policy.PolicyRefused, match='explicit approval record'):
        graph.revise(root, replacement, reason='synthetic change')
    public = tmp_path / 'public'
    graph.create(public, graph_spec([]))
    replacement = graph_spec([{'id': 'data', 'path': str(tmp_path / 'data.txt'),
                              'sha256': 'a' * 64, 'restricted': True}])
    with pytest.raises(policy.PolicyRefused, match='restricted input pins'):
        graph.revise(public, replacement, reason='synthetic change')
