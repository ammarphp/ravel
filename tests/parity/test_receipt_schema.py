"""P-1, P-5 and P-13 across transport kinds: one worker-receipt schema, truthful attestation, explicit ambiguity.

The receipt writer is ``agent_worker.finish`` for every kind. A kind that cannot be launched here produces its
receipt from the execution record its adapter would pass (the host-subagent kind uses its real adapter); the
label that execution carries comes from the production attestation functions, never from this file.
"""
import json

import pytest

from parity_support import declarations
from ravel.workflow import agent_worker as worker, role_registry, transport_receipt as rcpt, transport_registry as tr
from ravel.workflow.transports import host_subagent

KINDS = ('cli-worker', 'cli-oneshot', 'ravel-loop', 'http-model', 'external-relay', 'host-subagent')
COMMON_TRANSPORT = {'id', 'transport_kind', 'declaration_sha256', 'probe_sha256'}
FIXED_SECTIONS = ('role', 'model', 'isolation', 'usage', 'run_tree', 'broker', 'final_record', 'outcome', 'broker')
FINAL = {'completed': True, 'summary': 'parity stub'}


def spec(node_id, role='analysis-author', transport='stub'):
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node_id, 'attempt': 1,
            'role': {'id': role, 'version': role_registry.load(role)['version'],
                     'card_sha256': role_registry.card_sha256(role)},
            'transport_preference': [transport], 'inputs': [],
            'declared_outputs': [{'path': 'outputs/result.txt', 'kind': 'text', 'required': True}],
            'budgets': {'max_turns': 5, 'max_wall_seconds': 30, 'max_broker_calls': 5, 'max_cost_usd': None},
            'final_record_schema': 'producer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}


def launcher_receipt(document, *, loaded=False, session='session-a', override=()):
    """A synthetic launcher receipt of the closed shape for a CLI declaration (no process ran)."""
    zero = '0' * 64
    return {'schema_version': 1, 'kind': rcpt.KIND, 'writer': {'module': 'stub', 'module_sha256': zero},
            'transport': {'id': document['id'], 'transport_kind': document['transport_kind'],
                          'declaration_sha256': tr.declaration_sha256(document), 'declaration_origin': 'builtin',
                          'qualification_status': 'declared',
                          'attestation_capability': document['capabilities']['attestation']},
            'probe': {'probe_sha256': zero, 'executable_sha256': zero, 'current': True},
            'executable': {'path': '/synthetic', 'sha256': zero, 'cli_version': 'stub'},
            'invocation': {'host_invocation_id': 'i', 'argv_sha256': zero, 'env_names': [], 'home_mode': 'isolated',
                           'dotenv_paths': [], 'cwd': '/synthetic', 'prompt_in_argv': False},
            'process': {'pid': 1, 'pgid': 1, 'started_utc': 'u', 'finished_utc': 'u', 'exit_status': 0,
                        'stdout_sha256': zero, 'stderr_sha256': zero, 'stdout_bytes': 0, 'stderr_bytes': 0},
            'content': {'request_sha256': zero, 'prompt_sha256': zero, 'value_sha256': None},
            'effort': {'requested': None, 'transmitted': None},
            'configuration': {'effective_tools': document['capabilities']['tools'],
                              'isolation_profile': document['capabilities']['isolation'], 'config': {},
                              'override_args': list(override), 'managed_settings_sha256': None,
                              'user_configuration_loaded': loaded, 'basis': 'synthetic'},
            'cli_reported': {'label': 'cli-reported', 'session_id': session, 'observed_model': None,
                             'all_models': [], 'usage': {}, 'config_events': [], 'rollout_sha256': None}}


def label_for(document):
    """The attestation label production would compute for this declaration's own launch."""
    kind = document['transport_kind']
    if kind == 'external-relay':
        return rcpt.relay_attestation({}, declaration=document)[0]
    if kind == 'host-subagent':
        return 'host_attested'
    if kind in tr.CLI_KINDS:
        return rcpt.attestation(launcher_receipt(document), verification=[],
                                tools_required=document['capabilities']['tools'])[0]
    return 'transport_attested'          # http-model and ravel-loop: RAVEL itself observes every call


def execution_for(document):
    return {'exit_status': 0, 'attestation': label_for(document),
            'transport': {'id': document['id'], 'transport_kind': document['transport_kind'],
                          'declaration_sha256': tr.declaration_sha256(document), 'probe_sha256': None},
            'isolation': {'profile': document['capabilities']['isolation'], 'user_configuration_loaded': False,
                          'evidence': {'confirmed': False, 'basis': 'synthetic stub'}},
            'model': {'requested': 'parity-model', 'observed': 'parity-model', 'family': 'parity', 'effort': None},
            'session_id': 'session-' + document['id'], 'cli_version': 'stub 0.0',
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'cost_usd': None, 'reported': True,
                      **({'turns': None} if document['transport_kind'] in tr.CLI_KINDS else {})}}


def put(run, ws, rel, text):
    """Write a worker output through its broker: only a broker output pin credits an output."""
    from ravel.workflow import broker
    tool = broker.Broker(run, ws, node_id=ws.parent.name, attempt=int(ws.name), allowed_actions=['write'],
                         max_calls=100000)
    reply = tool.call({'call_id': 'put-' + ws.parent.name, 'action': 'write', 'args': {'path': rel, 'content': text}})
    assert reply['status'] == 'ok', reply


def receipt_via_finish(root, document, *, execution=None, final=FINAL, tag=''):
    run = root / ('run-' + document['id'] + tag)
    run.mkdir()
    s = spec('parity.' + document['id'].replace('.', '-'))
    ws = worker.materialize(run, s)
    put(run, ws, 'outputs/result.txt', 'stub output')
    return run, s, worker.finish(run, s, final=final, execution=execution or execution_for(document))


def receipt_via_host_adapter(root, document):
    run = root / ('run-' + document['id'])
    run.mkdir()
    s = spec('parity.host', transport=document['id'])
    ws = worker.materialize(run, s)
    packet = host_subagent.brief(run, s, ws, transport_id=document['id'])
    # A receipt is written only for work inside a steering-admitted broker window.
    with host_subagent.serve_broker(run, s, packet):
        (ws / 'outputs/result.txt').write_text('stub output')
    return host_subagent.complete(run, s, packet, final=FINAL)


COMMON_USAGE = {'input_tokens', 'output_tokens', 'cost_usd', 'reported'}


def schema_of(receipt, *, exact_usage=False):
    """The key tree of a worker receipt. The normalised parity set keeps the usage keys every kind must carry;
    ``exact_usage`` keeps every usage key, which is how an adapter-only extra such as ``turns`` shows up."""
    shape = {'top': sorted(receipt), 'transport_common': sorted(COMMON_TRANSPORT & set(receipt['transport']))}
    for section in FIXED_SECTIONS:
        value = receipt[section]
        shape[section] = sorted(value) if isinstance(value, dict) else type(value).__name__
    if not exact_usage:
        assert COMMON_USAGE <= set(receipt['usage']), receipt['usage']
        shape['usage'] = sorted(COMMON_USAGE)
    return shape


def representatives():
    """One declaration per transport kind, plus every declaration for the kinds that vary most."""
    return {kind: declarations(kind)[0] for kind in KINDS}


@pytest.fixture
def env(parity_env, monkeypatch):
    monkeypatch.delenv('RAVEL_SESSION_ID', raising=False)
    return parity_env


def test_every_kind_writes_the_same_receipt_schema(env):
    shapes, labels = {}, {}
    for kind, document in representatives().items():
        if kind == 'host-subagent':
            receipt = receipt_via_host_adapter(env, document)
        else:
            _, _, receipt = receipt_via_finish(env, document)
        assert set(receipt) == worker.RECEIPT_FIELDS
        assert COMMON_TRANSPORT <= set(receipt['transport']), kind
        assert receipt['transport']['transport_kind'] == kind
        shapes[kind], labels[kind] = schema_of(receipt), receipt['attestation']
    reference = shapes['cli-worker']
    assert all(shape == reference for shape in shapes.values()), {k: v for k, v in shapes.items() if v != reference}
    assert set(labels.values()) <= set(rcpt.ATTESTATIONS)


def test_attestation_reflects_the_transport_not_the_stub(env):
    labels = {}
    for kind, document in representatives().items():
        receipt = receipt_via_host_adapter(env, document) if kind == 'host-subagent' else \
            receipt_via_finish(env, document)[2]
        labels[kind] = receipt['attestation']
    assert labels['external-relay'] == 'self_attested'       # a relay is never better than self-attested
    assert labels['host-subagent'] == 'host_attested'        # RAVEL observed no process
    assert labels['ravel-loop'] == labels['http-model'] == 'transport_attested'
    assert labels['cli-oneshot'] in ('host_attested', 'transport_attested')


def test_a_schema_difference_is_detected():
    base = {k: {} for k in worker.RECEIPT_FIELDS}
    base.update(transport={'id': 'x', 'transport_kind': 'cli-worker'}, role={}, model={}, isolation={},
                usage={k: None for k in COMMON_USAGE}, run_tree={}, broker={}, final_record={}, outcome={})
    drifted = json.loads(json.dumps(base))
    drifted['usage']['extra_field'] = 1
    assert schema_of(base) == schema_of(drifted)                       # the normalised set ignores adapter extras
    assert schema_of(base, exact_usage=True) != schema_of(drifted, exact_usage=True)
    missing = json.loads(json.dumps(base))
    del missing['usage']['reported']
    with pytest.raises(AssertionError):                                 # a missing common key is a schema failure
        schema_of(missing)
    extra_top = {**base, 'unexpected': 1}
    assert schema_of(extra_top) != schema_of(base)


@pytest.mark.xfail(strict=True, reason="defect: cli_worker.observe adds usage.turns, which "
                   "agent_worker.finish's default usage and the host-subagent receipt do not carry")
def test_the_usage_section_has_the_same_keys_on_every_kind(env):
    cli = receipt_via_finish(env, declarations('cli-worker')[0])[2]
    host = receipt_via_host_adapter(env, declarations('host-subagent')[0])
    assert schema_of(cli, exact_usage=True) == schema_of(host, exact_usage=True)


@pytest.mark.parametrize('document', declarations('cli-worker') + declarations('cli-oneshot'), ids=lambda d: d['id'])
def test_configuration_isolation_is_reported_truthfully_on_every_cli_route(document):
    """P-5: loaded user configuration, overriding arguments, or a reused session never keep transport attestation."""
    clean, _ = rcpt.attestation(launcher_receipt(document), verification=[], tools_required=document['capabilities']['tools'])
    expected_clean = 'transport_attested' if document['capabilities']['attestation'] == 'transport' else 'host_attested'
    assert clean == expected_clean
    required = document['capabilities']['tools']
    loaded, reasons = rcpt.attestation(launcher_receipt(document, loaded=True), verification=[], tools_required=required)
    assert loaded == 'host_attested' and any('user configuration' in r for r in reasons)
    override, _ = rcpt.attestation(launcher_receipt(document, override=['--x']), verification=[], tools_required=required)
    assert override == 'host_attested'
    reused, _ = rcpt.attestation(launcher_receipt(document, session='s1'), verification=[], other_session_ids=['s1'],
                                 tools_required=required)
    assert reused == 'host_attested'
    forged, reasons = rcpt.attestation(launcher_receipt(document), verification=['digest differs'])
    assert forged == 'self_attested' and reasons == ['digest differs']
    assert rcpt.shape(launcher_receipt(document))


@pytest.mark.parametrize('kind', KINDS)
def test_an_ambiguous_worker_on_any_kind_closes_only_through_reconcile(env, kind):
    document = declarations(kind)[0]
    execution = {**execution_for(document), 'ambiguous': True, 'exit_status': None}
    run, s, receipt = receipt_via_finish(env, document, execution=execution)
    assert receipt['status'] == 'ambiguous' and receipt['failure']['code'] == 'process_error'
    assert worker.finish(run, s, final=FINAL, execution=execution_for(document))['status'] == 'ambiguous'  # no re-close
    with pytest.raises(ValueError):
        worker.reconcile(run, s['node_id'], 1)                          # explicit evidence and reason required
    pin = {'path': 'inputs/reconcile.txt', 'sha256': __import__('hashlib').sha256(b'evidence').hexdigest()}
    (run / 'inputs').mkdir(exist_ok=True)
    (run / 'inputs/reconcile.txt').write_bytes(b'evidence')
    closed = worker.reconcile(run, s['node_id'], 1, evidence=pin, reason='parity: verified no child remains')
    assert closed['status'] == 'failed' and closed['failure']['detail'] == 'explicitly reconciled failed worker'


# ---------------------------------------------------------------- a real CLI launch, where the host can sandbox one

from test_cli_worker_adapter import cli, ready, real_sandbox_or_skip, spec as cli_spec  # noqa: E402,F401  (fixture reuse)


def test_a_real_sandboxed_cli_launch_writes_the_same_receipt_schema_as_the_stubs(cli):
    """A fake CLI runs under the actual sandbox; its receipt has the schema every other kind produces."""
    real_sandbox_or_skip(cli)
    ready(cli)
    real = worker.dispatch(cli / 'run', cli_spec(cli))
    assert real['status'] == 'ok', real['failure']
    (cli / 'stubs').mkdir()
    stub = receipt_via_finish(cli / 'stubs', declarations('cli-worker')[0])[2]
    assert schema_of(real) == schema_of(stub) and set(real) == worker.RECEIPT_FIELDS
    assert real['transport']['transport_kind'] == 'cli-worker' and real['attestation'] in rcpt.ATTESTATIONS
