"""Legacy-run R3 case approvals: only a controller capture or a controller authority record credits a human.

The capture cases use the real capture chain with the explicit inert operator stand-in.
The authority-service cases isolate the controller store and ``service.verify`` behind
declaration fakes, as the native authority bridge tests do; every acceptance condition the
issuer and ``rdj_loop._human`` apply to the verified record stays real.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ravel.workflow import approval_authority, approval_capture, gate_wiring, rdj_custody, rdj_loop
from operator_capture import operator_at_terminal
from rdj_fixtures import PROPOSER, Run

RECORD_ID = 'authority-r3-case'


@pytest.fixture
def case(tmp_path):
    run = Run(tmp_path / 'run')
    action = run.action('replace_reviewed_outputs')
    cls, factors = rdj_loop.compute_class(run.root, 'launch', action)
    assert cls == 'R3' and factors['irreversible']
    case_id = rdj_loop.open_case(run.root, 'launch', action, PROPOSER)
    return run, case_id


def digest(run, case_id):
    return run.case(case_id)['decision_point']['action']['digest']


def human(run, case_id):
    return rdj_loop._human(run.root, run.case(case_id))


def approvals(run, case_id):
    return rdj_custody.approvals(run.root, case_id, digest(run, case_id))


def open_codes(run, case_id):
    with pytest.raises(rdj_loop.OpenItems) as refused:
        rdj_loop.authorize(run.root, case_id)
    return {item['code'] for item in refused.value.items}


def span(run, case_id, text=None):
    text = text or f'I approve {case_id}.'
    pin = run.steering(text)
    start = text.index(case_id)
    return pin, dict(source='user_steering', path=pin['path'], start=start, end=start + len(case_id), text=case_id)


# ---------------------------------------------------------------- the controller capture

def test_a_controller_capture_through_the_response_path_credits_the_human(case, monkeypatch):
    run, case_id = case
    assert 'human_required' in open_codes(run, case_id)
    calls = operator_at_terminal(monkeypatch)
    result = gate_wiring.respond(run.root, f'I approve {case_id}.', approve=[case_id], confirm=True)
    assert [c['purpose'] for c in calls] == ['case_approval']
    assert result['decisions'][0]['human_authority'] is True
    assert result['decisions'][0]['authority'] == approval_authority.CONTROLLER_CAPTURE
    assert human(run, case_id) is True
    assert 'human_required' not in open_codes(run, case_id)
    row, = approvals(run, case_id)
    assert approval_authority.case_approval(row)['authority'] == approval_authority.CONTROLLER_CAPTURE


# ---------------------------------------------------------------- what earns no human credit

def test_caller_text_records_evidence_but_no_approval_or_credit(case):
    run, case_id = case
    result = gate_wiring.respond(run.root, f'I approve {case_id}.', approve=[case_id])
    assert result['decisions'][0]['human_authority'] is False and result['governance'] == 'NOT GOVERNED'
    assert approvals(run, case_id) == []
    assert human(run, case_id) is False and 'human_required' in open_codes(run, case_id)


def test_an_interactive_terminal_without_a_capture_earns_no_credit(case, monkeypatch):
    run, case_id = case
    # A terminal session with no agent marker is labelled, not authenticated.
    tty = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr(approval_authority, 'sys', SimpleNamespace(stdin=tty, stdout=tty))
    for name in approval_authority.AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    result = gate_wiring.respond(run.root, f'I approve {case_id}.', approve=[case_id])
    assert result['provenance']['authority'] == approval_authority.TERMINAL_UNATTESTED
    assert approvals(run, case_id) == [] and human(run, case_id) is False


def test_an_automated_terminal_that_cannot_confirm_records_nothing(case):
    run, case_id = case
    before = rdj_custody.rows(run.root, 'approvals'), rdj_custody.rows(run.root, 'user_text')
    # The test process has no terminal the capture may read (the shared fixture's default).
    with pytest.raises(approval_capture.CaptureRefused):
        gate_wiring.respond(run.root, f'I approve {case_id}.', approve=[case_id], confirm=True)
    assert (rdj_custody.rows(run.root, 'approvals'), rdj_custody.rows(run.root, 'user_text')) == before
    assert human(run, case_id) is False


def test_a_historical_human_approver_record_stays_readable_without_credit(case):
    run, case_id = case
    pin, quoted = span(run, case_id)
    # A record written before captures existed: an approve row naming the case, with a claim.
    historical = {'decision': 'approve', 'case_id': case_id, 'action_digest': digest(run, case_id),
                  **quoted, 'sha256': pin['sha256'], 'human_approver': True}
    rdj_custody.append(run.root, 'approvals', historical)
    row, = approvals(run, case_id)
    assert row['human_approver'] is True
    assert approval_authority.case_approval(row) == {'authority': approval_authority.CALLER_UNATTESTED,
                                                     'governance': 'NOT GOVERNED'}
    assert approval_authority.authority(row) == 'unknown'
    assert human(run, case_id) is False and 'human_required' in open_codes(run, case_id)


@pytest.mark.parametrize('evidence', ['none', 'both'])
def test_the_issuer_without_exactly_one_controller_evidence_refuses_and_records_nothing(case, evidence):
    run, case_id = case
    _, quoted = span(run, case_id)
    extra = {}
    if evidence == 'both':
        extra = {'attestation': {'kind': 'controller-capture'}, 'authority': RECORD_ID}
    before = rdj_custody.rows(run.root, 'approvals')
    with pytest.raises(ValueError, match='controller capture or authority-service record'):
        rdj_custody.record_human_approval(run.root, case_id=case_id, **quoted, **extra)
    assert rdj_custody.rows(run.root, 'approvals') == before
    assert human(run, case_id) is False


# ---------------------------------------------------------------- the authority service

class Store:
    def __init__(self, run_id, problems=()):
        self.run_id, self.problems = run_id, list(problems)

    def check_binding(self, run_dir=None):
        return list(self.problems)

    def verify(self):
        return []


@pytest.fixture
def authority(case, monkeypatch):
    """The run's controller store and its verified authority reader, as declaration fakes."""
    from ravel.controller import store as controller_store
    from ravel.controller.authority import common, service
    run, case_id = case
    state = {'owner': 'controller-run', 'problems': [], 'stale': False, 'calls': []}
    state['record'] = {'id': RECORD_ID, 'kind': 'r3_action', 'decision': 'approve', 'label': common.OPERATOR_COMMAND,
                       'source': 'operator_cli', 'authorizes_effects': True,
                       'subject': {'pins': rdj_custody.case_authority_pins(run.root, case_id, digest(run, case_id))}}
    monkeypatch.setattr(controller_store, 'controller_owned', lambda path: state['owner'])
    monkeypatch.setattr(controller_store, 'RunStore', lambda owner: Store(owner, state['problems']))

    def verify(store, record_id, *, kind, subject=None):
        state['calls'].append((store.run_id, record_id, kind, deepcopy(subject)))
        if state['stale'] or record_id != RECORD_ID:
            raise common.AuthorityRefused('authority was superseded by a later decision')
        return deepcopy(state['record'])
    monkeypatch.setattr(service, 'verify', verify)
    return state


def test_an_operator_command_record_approves_the_case_and_credits_the_human(case, authority):
    run, case_id = case
    _, quoted = span(run, case_id)
    rdj_custody.record_human_approval(run.root, case_id=case_id, authority=RECORD_ID, **quoted)
    row, = approvals(run, case_id)
    assert row['authority'] == {'store_run_id': 'controller-run', 'record_id': RECORD_ID, 'kind': 'r3_action',
                                'label': 'operator_command'}
    assert approval_authority.case_approval(row)['authority'] == approval_authority.OPERATOR_COMMAND
    # The reader is asked for exactly this run, case and action.
    assert authority['calls'][0] == ('controller-run', RECORD_ID, 'r3_action',
                                     rdj_custody.case_authority_pins(run.root, case_id, digest(run, case_id)))
    assert human(run, case_id) is True
    assert 'human_required' not in open_codes(run, case_id)
    # Credit is re-verified live: a superseded record no longer credits the recorded row.
    authority['stale'] = True
    assert human(run, case_id) is False and 'human_required' in open_codes(run, case_id)


@pytest.mark.parametrize('fault', ['machine', 'delegated', 'unattested_terminal', 'decision', 'effects',
                                   'kind', 'pins', 'stale', 'no_store', 'unbound_store', 'unknown_id'])
def test_any_other_authority_record_is_refused_and_records_nothing(case, authority, fault):
    from ravel.controller.authority import common
    run, case_id = case
    record = authority['record']
    record_id = RECORD_ID
    if fault == 'machine':
        record['label'] = common.MACHINE
    elif fault == 'delegated':
        record['label'] = common.DELEGATED
    elif fault == 'unattested_terminal':
        record['label'] = common.LEGACY_TERMINAL
    elif fault == 'decision':
        record['decision'] = 'reject'
    elif fault == 'effects':
        record['authorizes_effects'] = False
    elif fault == 'kind':
        record['kind'] = 'approve_plan'
    elif fault == 'pins':
        record['subject']['pins']['rdj_action_digest'] = '0' * 64
    elif fault == 'stale':
        authority['stale'] = True
    elif fault == 'no_store':
        authority['owner'] = None
    elif fault == 'unbound_store':
        authority['problems'].append('the run directory is not the store binding')
    else:
        record_id = 'another-record'
    _, quoted = span(run, case_id)
    before = rdj_custody.rows(run.root, 'approvals')
    with pytest.raises(ValueError):
        rdj_custody.record_human_approval(run.root, case_id=case_id, authority=record_id, **quoted)
    assert rdj_custody.rows(run.root, 'approvals') == before
    assert human(run, case_id) is False


def test_a_recorded_authority_reference_whose_record_changed_earns_no_credit(case, authority):
    from ravel.controller.authority import common
    run, case_id = case
    _, quoted = span(run, case_id)
    rdj_custody.record_human_approval(run.root, case_id=case_id, authority=RECORD_ID, **quoted)
    assert human(run, case_id) is True
    authority['record']['label'] = common.MACHINE
    assert human(run, case_id) is False
