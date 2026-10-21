"""The operator-configured reviewer fallback on a host without the OS worker sandbox.

Unit proofs, all inert and fictional: the operator setting and its validation, its freezing into a run's mode
and the narrowing-only child rule, the step's decision and record, transport selection under the fallback (only
what the sandbox enforces is relaxed; the live qualification never is), the worker's trusted-fact reader, the
sink's label and refusal, and the inventory probe of an unsandboxed worker. No model call, no network, no native
job. See ``docs/reference/transports.md``, "Review seats on a host without the OS worker sandbox".
"""
from __future__ import annotations

import json
import sys

import pytest

from test_p06_support import frozen_store, new_store, operator_home  # noqa: F401  (fixture)
from p07_support import Run, run  # noqa: F401  (fixture)
from ravel.controller.authority import AuthorityRefused, freeze_child, mode, operator

FALLBACK = 'restricted-unsandboxed'
LABEL = 'REVIEW WITHOUT OS SANDBOX (OPERATOR-CONFIGURED FALLBACK)'
REVIEW_SEAT = {'purpose': 'review', 'role': 'fictional-critic'}
REVIEW_STEP = {'kind': 'review', 'id': 's-review'}


def _no_sandbox(monkeypatch):
    from ravel.workflow import sandbox
    monkeypatch.setattr(sandbox, 'available', lambda: None)


def _configured_store(tmp_path, fallback=FALLBACK, run_id='run-0001'):
    """A run frozen under an autonomous operator ledger carrying the given fallback."""
    operator.init(mode='autonomous', review_sandbox_fallback=fallback)
    return frozen_store(tmp_path, run_id=run_id)


# ---- 1. the operator setting ---------------------------------------------------------------------------

def test_operator_setting_defaults_to_none_is_written_by_the_cli_and_validated(operator_home, capsys):
    from ravel.controller.authority import cli
    assert operator.CONSUMER_DEFAULTS['review_sandbox_fallback'] == 'none'
    assert operator.REVIEW_SANDBOX_FALLBACKS == ('none', FALLBACK)
    assert operator.default_config()['review_sandbox_fallback'] == 'none'
    assert operator.operator_config()['review_sandbox_fallback'] == 'none'
    assert cli.main(['init', '--mode', 'autonomous', '--review-sandbox-fallback', FALLBACK]) == 0
    assert json.loads(capsys.readouterr().out)['review_sandbox_fallback'] == FALLBACK
    assert operator.operator_config()['review_sandbox_fallback'] == FALLBACK
    assert cli.main(['set', '--review-sandbox-fallback', 'none']) == 0
    assert json.loads(capsys.readouterr().out)['review_sandbox_fallback'] == 'none'
    assert operator.operator_config()['review_sandbox_fallback'] == 'none'
    with pytest.raises(ValueError, match='review_sandbox_fallback'):
        operator.set_values({'review_sandbox_fallback': 'unconfined-everything'})
    with pytest.raises(ValueError, match='review_sandbox_fallback'):
        operator.validate({**operator.default_config(), 'review_sandbox_fallback': 'yes'})
    assert operator.operator_config()['review_sandbox_fallback'] == 'none'  # the refused values were not written
    with pytest.raises(SystemExit):  # the CLI offers only the declared choices
        cli.main(['set', '--review-sandbox-fallback', 'unconfined-everything'])


def test_a_ledger_config_without_the_key_validates_with_none(operator_home):
    legacy = operator.default_config()
    del legacy['review_sandbox_fallback']
    assert operator.validate(legacy)['review_sandbox_fallback'] == 'none'


def test_revoking_the_grant_resets_the_fallback_to_none(operator_home):
    operator.init(mode='autonomous', review_sandbox_fallback=FALLBACK)
    assert operator.operator_config()['review_sandbox_fallback'] == FALLBACK
    operator.revoke_grant('fictional reason for the revocation')
    config = operator.operator_config()
    assert config['review_sandbox_fallback'] == 'none' and config['mode'] == 'physicist-in-the-loop'


# ---- 2. freezing and children --------------------------------------------------------------------------

def test_a_frozen_mode_carries_the_operators_fallback(operator_home, tmp_path):
    store = _configured_store(tmp_path)
    assert mode.frozen(store)['review_sandbox_fallback'] == FALLBACK


def test_a_child_may_keep_or_drop_the_fallback_but_never_take_it(operator_home, tmp_path):
    parent_store = _configured_store(tmp_path, run_id='parent')
    parent = mode.frozen(parent_store)
    assert mode.narrow(parent)['review_sandbox_fallback'] == FALLBACK  # inherited
    assert mode.narrow(parent, {'review_sandbox_fallback': FALLBACK})['review_sandbox_fallback'] == FALLBACK
    assert mode.narrow(parent, {'review_sandbox_fallback': 'none'})['review_sandbox_fallback'] == 'none'
    dropped = freeze_child(new_store(tmp_path, 'child'), parent_store, {'prompt': 'A fictional child.'},
                           {'review_sandbox_fallback': 'none'})
    assert dropped['review_sandbox_fallback'] == 'none'
    strict = {**parent, 'review_sandbox_fallback': 'none'}
    with pytest.raises(AuthorityRefused, match='review sandbox fallback'):
        mode.narrow(strict, {'review_sandbox_fallback': FALLBACK})
    assert mode.narrow(strict)['review_sandbox_fallback'] == 'none'
    with pytest.raises(AuthorityRefused):  # a child of a dropping child cannot take it back either
        freeze_child(new_store(tmp_path, 'grandchild'), new_store(tmp_path, 'child'), {'prompt': 'x'},
                     {'review_sandbox_fallback': FALLBACK})


# ---- 3. the step's decision ----------------------------------------------------------------------------

def test_review_fallback_is_none_inside_the_sandbox(operator_home, tmp_path, monkeypatch):
    from ravel.controller.step import graph
    from ravel.workflow import sandbox
    store = _configured_store(tmp_path)
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    assert graph._review_fallback(store, REVIEW_SEAT, REVIEW_STEP) is None


def test_review_fallback_is_none_for_a_seat_that_does_not_review(operator_home, tmp_path, monkeypatch):
    from ravel.controller.step import graph
    store = _configured_store(tmp_path)
    _no_sandbox(monkeypatch)
    assert graph._review_fallback(store, {'purpose': 'produce', 'role': 'fictional-author'},
                                  {'kind': 'operate'}) is None
    assert graph._review_fallback(store, None, {'kind': 'operate'}) is None


def test_review_fallback_is_none_when_the_frozen_mode_says_none(operator_home, tmp_path, monkeypatch):
    from ravel.controller.step import graph
    store = _configured_store(tmp_path, fallback='none')
    _no_sandbox(monkeypatch)
    assert graph._review_fallback(store, REVIEW_SEAT, REVIEW_STEP) is None


def test_review_fallback_is_none_without_a_frozen_mode(operator_home, tmp_path, monkeypatch):
    from ravel.controller.step import graph
    operator.init(mode='autonomous', review_sandbox_fallback=FALLBACK)
    _no_sandbox(monkeypatch)
    assert graph._review_fallback(new_store(tmp_path), REVIEW_SEAT, REVIEW_STEP) is None  # never frozen at intake


def test_review_fallback_names_the_restricted_unsandboxed_reviewer_when_configured(operator_home, tmp_path,
                                                                                     monkeypatch):
    from ravel.controller.step import graph
    store = _configured_store(tmp_path)
    _no_sandbox(monkeypatch)
    for seat, acting in ((REVIEW_SEAT, {'kind': 'operate'}), (None, REVIEW_STEP)):  # purpose or step kind
        found = graph._review_fallback(store, seat, acting)
        assert found['kind'] == FALLBACK and found['label'] == LABEL == graph.REVIEW_FALLBACK_LABEL
        assert found['mode_record'] == mode.frozen(store)['id']
        assert found['isolation'] == 'cli-policy' and found['tools'] == 'broker-readonly'
        assert 'OS-enforced blindness' in found['not_enforced']
        assert 'never human review' in found['review_credit']


def test_the_fallback_follows_the_frozen_value_not_a_later_operator_change(operator_home, tmp_path, monkeypatch):
    from ravel.controller.step import graph
    first = _configured_store(tmp_path, run_id='run-0001')
    operator.set_values({'review_sandbox_fallback': 'none'})
    second = frozen_store(tmp_path, run_id='run-0002')
    _no_sandbox(monkeypatch)
    assert graph._review_fallback(first, REVIEW_SEAT, REVIEW_STEP)['kind'] == FALLBACK
    assert graph._review_fallback(second, REVIEW_SEAT, REVIEW_STEP) is None


# ---- 4. the hold, or the recorded fallback -------------------------------------------------------------

def test_a_selected_fallback_is_returned_with_one_store_record(operator_home, tmp_path, monkeypatch):
    from ravel.controller.step import graph
    store = _configured_store(tmp_path)
    _no_sandbox(monkeypatch)
    relaxed = {'kind': FALLBACK, 'isolation': 'cli-policy', 'blind_capable': False,
               'relaxed_requirements': ['isolation', 'blind']}
    selection = {'transport_id': 'fictional-transport', 'sandbox_fallback': relaxed}
    found = graph._review_sandbox(store, REVIEW_SEAT, REVIEW_STEP, selection=selection)
    assert found['kind'] == FALLBACK and found['label'] == LABEL and found['record']
    rows = store.scan(graph.REVIEW_FALLBACK)
    assert graph.REVIEW_FALLBACK == 'review-sandbox-fallback' and len(rows) == 1
    assert store.read(graph.REVIEW_FALLBACK, found['record']) == rows[0]
    assert rows[0]['step_id'] == 's-review' and rows[0]['transport'] == 'fictional-transport'
    assert rows[0]['seat'] == 'fictional-critic' and rows[0]['relaxed'] == relaxed
    assert rows[0]['kind'] == FALLBACK and rows[0]['label'] == LABEL


def test_a_fallback_without_a_fallback_selection_holds_and_records_nothing(operator_home, tmp_path, monkeypatch):
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    store = _configured_store(tmp_path)
    _no_sandbox(monkeypatch)
    for selection in (None, {'transport_id': 'fictional-transport'}, {'transport_id': 't', 'sandbox_fallback': None}):
        with pytest.raises(StepHold) as held:
            graph._review_sandbox(store, REVIEW_SEAT, REVIEW_STEP, selection=selection)
        assert held.value.reason == 'review_fallback_unselected'
        assert held.value.evidence['fallback']['kind'] == FALLBACK
    assert store.scan(graph.REVIEW_FALLBACK) == []


def test_without_a_configured_fallback_a_review_seat_holds_labelled_and_names_the_setting(operator_home, tmp_path,
                                                                                         monkeypatch):
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    store = _configured_store(tmp_path, fallback='none')
    _no_sandbox(monkeypatch)
    selection = {'transport_id': 'fictional-transport', 'sandbox_fallback': {'kind': FALLBACK}}
    with pytest.raises(StepHold) as held:
        graph._review_sandbox(store, REVIEW_SEAT, REVIEW_STEP, selection=selection)
    assert held.value.reason == 'worker_sandbox_unavailable'
    assert held.value.would_make_possible.startswith('INDEPENDENT REVIEW INCOMPLETE: ')
    assert '--review-sandbox-fallback restricted-unsandboxed' in held.value.would_make_possible
    assert held.value.evidence['label'] == 'INDEPENDENT REVIEW INCOMPLETE'
    assert held.value.evidence['unsandboxed_reviewers'] == 'operator fallback not configured'
    assert held.value.evidence['driver_self_review'] == 'never'
    assert store.scan(graph.REVIEW_FALLBACK) == []


def test_a_non_review_seat_still_holds_without_the_sandbox_even_under_the_fallback(operator_home, tmp_path,
                                                                                   monkeypatch):
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    store = _configured_store(tmp_path)
    _no_sandbox(monkeypatch)
    selection = {'transport_id': 'fictional-transport', 'sandbox_fallback': {'kind': FALLBACK}}
    with pytest.raises(StepHold) as held:
        graph._review_sandbox(store, {'purpose': 'produce', 'role': 'fictional-author'}, {'kind': 'operate'},
                              selection=selection)
    assert held.value.reason == 'worker_sandbox_unavailable'
    assert held.value.evidence['label'] is None and held.value.evidence['review_seat'] is False
    assert 'INDEPENDENT REVIEW INCOMPLETE' not in held.value.would_make_possible
    assert store.scan(graph.REVIEW_FALLBACK) == []


# ---- 5. transport selection ----------------------------------------------------------------------------

def _probe_and_qualification(document):
    from ravel.workflow import transport_registry as tr
    probe = {'schema_version': 1, 'kind': 'transport-probe', 'transport_id': document['id'],
             'declaration_sha256': tr.declaration_sha256(document), 'cli_version': 'synthetic 0.0.0',
             'help_sha256': 'b' * 64, 'flags': {flag: 'confirmed' for flag in tr.template_flags(document)},
             'capabilities_confirmed': {key: bool(document['capabilities'][key]) and key != 'blind_capable'
                                        for key in tr.BOOLEAN_CAPABILITIES},
             'unusable': [], 'probed_utc': '2026-01-01T00:00:00Z', 'executable_path': '/synthetic/cli',
             'executable_sha256': 'f' * 64, 'exit_status': 0}
    record = {'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': document['id'],
              'status': 'live_qualified', 'record_path': 'r', 'executable_path': '/synthetic/cli',
              'executable_sha256': 'f' * 64, 'declaration_sha256': tr.declaration_sha256(document),
              'probe_sha256': tr.digest(probe), 'receipt': {}, 'observed': {},
              'steps': [{'step': name, 'passed': True} for name in sorted(tr.QUALIFICATION_STEPS)],
              'rundir': 'run', 'qualified_utc': '2026-01-01T00:00:00Z'}
    return probe, record


def _selection_world(tmp_path, monkeypatch):
    from ravel.workflow import transport_registry as tr
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    _no_sandbox(monkeypatch)
    document = tr.load('claude-cli-worker', installed_only=True)
    probe, record = _probe_and_qualification(document)
    card = {'id': 'fictional-blind-reviewer', 'family': 'fictional-review-family',
            'independence': {'kind': 'voting'}, 'model': {'tier': 'judgment'},
            'requires': {'blind': True, 'isolation_min': 'ravel-sandbox'}}
    preferences = {'schema_version': 1, 'kind': 'agent-preferences',
                   'families': {card['family']: [document['id']]},
                   'tier_models': {'judgment': {document['id']: 'claude-fictional-1'}}}
    return tr, document, probe, record, card, preferences


def test_without_the_fallback_a_sandboxed_worker_is_unavailable_on_a_host_without_the_sandbox(tmp_path, monkeypatch):
    tr, document, probe, record, _, _ = _selection_world(tmp_path, monkeypatch)
    assert tr.executor_problem(document) == 'sandbox_unavailable'
    assert tr.executor_problem(document, sandbox_fallback=True) is None
    assert tr.effective_capabilities(document, probe, registered=frozenset()) == (None, ['sandbox_unavailable'])


def test_the_fallback_makes_a_qualified_worker_cli_policy_and_never_blind(tmp_path, monkeypatch):
    tr, document, probe, record, _, _ = _selection_world(tmp_path, monkeypatch)
    assert document['capabilities']['isolation'] == 'ravel-sandbox' and document['capabilities']['blind_capable']
    for registered in (frozenset(), {tr.digest(record): record}):  # qualified or not, the sandbox is absent
        capabilities, reasons = tr.effective_capabilities(document, probe, registered=registered,
                                                          sandbox_fallback=True)
        assert reasons == [] and capabilities['isolation'] == 'cli-policy'
        assert capabilities['blind_capable'] is False
    assert 'isolation' in tr.SANDBOX_ENFORCED and 'blind' in tr.SANDBOX_ENFORCED


def test_the_fallback_applies_only_to_controller_selection(tmp_path, monkeypatch):
    tr, document, probe, record, card, preferences = _selection_world(tmp_path, monkeypatch)
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card, preferences, probes={document['id']: probe}, executables={document['id']: 'f' * 64},
                  controller=False, sandbox_fallback=True)
    assert refused.value.missing == ['controller']


def test_a_qualified_worker_is_selected_under_the_fallback_naming_what_was_relaxed(tmp_path, monkeypatch):
    tr, document, probe, record, card, preferences = _selection_world(tmp_path, monkeypatch)
    seen = {'probes': {document['id']: probe}, 'executables': {document['id']: 'f' * 64},
            'controller': True, 'qualifications': {tr.digest(record): record}}
    with pytest.raises(tr.TransportRefusal) as plain:  # no fallback: the host cannot run the worker at all
        tr.select(card, preferences, **seen)
    assert 'sandbox_unavailable' in plain.value.missing
    chosen = tr.select(card, preferences, sandbox_fallback=True, **seen)
    assert chosen['transport_id'] == document['id'] and chosen['model'] == 'claude-fictional-1'
    relaxed = chosen['sandbox_fallback']
    assert relaxed['kind'] == FALLBACK and relaxed['isolation'] == 'cli-policy'
    assert relaxed['blind_capable'] is False
    assert {'isolation', 'blind'} <= set(relaxed['relaxed_requirements'])
    assert set(relaxed['relaxed_requirements']) <= set(tr.SANDBOX_ENFORCED)


def test_the_fallback_never_relaxes_the_live_qualification(tmp_path, monkeypatch):
    tr, document, probe, record, card, preferences = _selection_world(tmp_path, monkeypatch)
    for qualifications in ({}, {tr.digest(record): {**record, 'steps': []}}):  # absent, or not a passed record
        with pytest.raises(tr.TransportRefusal) as refused:
            tr.select(card, preferences, probes={document['id']: probe}, executables={document['id']: 'f' * 64},
                      controller=True, qualifications=qualifications, sandbox_fallback=True)
        assert 'qualification' in refused.value.missing
        assert not set(refused.value.missing) & set(tr.SANDBOX_ENFORCED)  # what the sandbox enforces is relaxed


def test_the_fallback_never_relaxes_a_requirement_the_sandbox_does_not_enforce(tmp_path, monkeypatch):
    tr, document, probe, record, card, preferences = _selection_world(tmp_path, monkeypatch)
    structured = {**card, 'requires': {**card['requires'], 'attestation_min': 'transport', 'tools': 'broker-full'}}
    seen = {'probes': {document['id']: probe}, 'executables': {document['id']: 'f' * 64},
            'controller': True, 'qualifications': {tr.digest(record): record}, 'sandbox_fallback': True}
    assert tr.select(structured, preferences, **seen)['transport_id'] == document['id']  # met requirements pass
    refused_card = {**card, 'model': {'tier': 'judgment', 'effort': 'high'}}
    broken = {**probe, 'capabilities_confirmed': {**probe['capabilities_confirmed'], 'effort_control': False}}
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(refused_card, preferences, **{**seen, 'probes': {document['id']: broken}})
    assert 'effort' in refused.value.missing


# ---- 6. the worker's trusted fact ----------------------------------------------------------------------

def test_the_worker_reads_only_a_recorded_restricted_unsandboxed_fallback_from_controller_facts():
    from ravel.workflow import agent_worker
    reader = agent_worker._sandbox_fallback
    valid = {'kind': FALLBACK, 'record': 'review-sandbox-fallback-000000', 'label': LABEL,
             'not_enforced': ['filesystem confinement']}
    assert reader(None) is None and reader({}) is None and reader([valid]) is None
    assert reader({'review_sandbox_fallback': None}) is None
    assert reader({'review_sandbox_fallback': {'kind': FALLBACK}}) is None  # never recorded in the store
    assert reader({'review_sandbox_fallback': {'kind': FALLBACK, 'record': None}}) is None
    assert reader({'review_sandbox_fallback': {**valid, 'kind': 'unconfined'}}) is None  # another kind
    assert reader({'review_sandbox_fallback': 'restricted-unsandboxed'}) is None
    controller = {'review_sandbox_fallback': valid}
    found = reader(controller)
    assert found == valid and found is not valid
    found['not_enforced'].append('mutated')
    assert valid['not_enforced'] == ['filesystem confinement']  # a copy, not the controller's own object


# ---- 7. the sink ---------------------------------------------------------------------------------------

def _fallback_row(step_id='s2', seat='fictional-critic'):
    return {'schema_version': 1, 'kind': FALLBACK, 'label': LABEL, 'step_id': step_id, 'seat': seat,
            'transport': 'fictional-transport', 'not_enforced': ['filesystem confinement', 'network confinement'],
            'relaxed': {'kind': FALLBACK, 'relaxed_requirements': ['isolation', 'blind']}}


def test_a_run_with_no_fallback_row_carries_neither_the_label_nor_the_refusal(run):
    run.complete()
    receipt = run.deliver()
    assert LABEL not in receipt['labels']
    assert 'review_unsandboxed' not in {r['code'] for r in receipt['work']['current_refusals']}
    assert receipt['accepted'] is True


def test_a_fallback_row_labels_the_delivery_and_refuses_acceptance(run):
    from ravel.controller.sink import common as sink_common
    run.complete()
    run.store.append('review-sandbox-fallback', _fallback_row())
    receipt = run.deliver()
    assert sink_common.REVIEW_UNSANDBOXED == LABEL
    assert LABEL in receipt['labels']
    refusal = next(r for r in receipt['work']['current_refusals'] if r['code'] == 'review_unsandboxed')
    assert 'step s2' in refusal['message'] and 'filesystem confinement' in refusal['message']
    assert any(d['label'] == LABEL and 'fictional-critic' in d['text'] for d in receipt['label_details'])
    assert receipt['accepted'] is False and receipt['label'] != 'accepted' and receipt['qualified'] is True


# ---- 8. the confine probe ------------------------------------------------------------------------------

INERT_MCP = r"""
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    result = ({'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
               'serverInfo': {'name': 'inert', 'version': '1'}}
              if request['method'] == 'initialize' else
              {'tools': [{'name': name, 'inputSchema': {'type': 'object'}} for name in sys.argv[1:]]})
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
"""


@pytest.fixture
def issuer_world(tmp_path, monkeypatch):
    from ravel.controller.authority import issuer
    from ravel.workflow.approval_authority import AGENT_MARKERS
    root = (tmp_path / 'runtime' / 'authority').resolve()
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(issuer, 'home', lambda: root)
    issuer.initialize()
    return root


def test_an_unsandboxed_worker_probe_records_unconfined_sets_and_issuer_exposure(tmp_path, monkeypatch,
                                                                                 issuer_world):
    from ravel.controller.confine import probe
    _no_sandbox(monkeypatch)
    workspace = (tmp_path / 'worker').resolve()
    for name in ('inputs', 'outputs', 'scratch'):
        (workspace / name).mkdir(parents=True)
    target = {'workspace': str(workspace), 'unsandboxed': True,
              'mcp_command': [sys.executable, '-I', '-S', '-B', '-c', INERT_MCP, 'read', 'write']}
    first = probe('worker', target)
    assert first['unsandboxed'] is True and first['backend'] is None
    assert first['writable'] == 'unconfined' and first['network'] == 'unconfined'
    assert isinstance(first['writable_observed'], list) and first['network_observed'] in ('none', 'host-loopback')
    assert first['egress_label'] == 'worker egress: unconfined (no OS sandbox)'
    assert first['tools'] == ['read', 'write'] and first['mcp_observed'] is True
    assert set(first['issuer_exposure']) == {'issuer_read_denied', 'issuer_replace_denied'}
    assert not [d for d in first['differences'] if str(d.get('field', '')).startswith('issuer')]
    admitted = {'tools': ['read', 'write'], 'writable': 'unconfined', 'env_names': first['env_names'],
                'network': 'unconfined'}
    again = probe('worker', {**target, 'admitted': admitted})
    assert again['equal'] is True and again['differences'] == []
    assert again['writable'] == 'unconfined' and again['unsandboxed'] is True
    assert 'issuer_exposure' in again
    extra = probe('worker', {**target, 'admitted': {**admitted, 'tools': ['read']}})  # served tools still compare
    assert extra['equal'] is False and {'field': 'tools', 'unadmitted': ['write']} in extra['differences']
