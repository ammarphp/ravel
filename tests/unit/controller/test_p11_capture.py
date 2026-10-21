"""Controller capture over real RDJ custody and the real response path; explicit inert operator only."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import gate_wiring, rdj_custody, rdj_loop
from p11_fakes import captured_operator
from rdj_fixtures import PROPOSER, Run


@pytest.fixture
def operator(tmp_path):
    with captured_operator(tmp_path) as stand_in:
        yield stand_in


@pytest.fixture
def case(tmp_path, operator):
    run = Run(tmp_path / 'run')
    case_id = rdj_loop.open_case(run.root, 'export', run.action('export_bundle'), PROPOSER)
    return run, case_id


def human(run, case_id):
    return rdj_loop._human(run.root, run.case(case_id))


def approvals(run, case_id):
    return rdj_custody.approvals(run.root, case_id, run.case(case_id)['decision_point']['action']['digest'])


def record(run, case_id, attestation=None):
    text = f'I approve {case_id}.'
    pin = run.steering(text)
    start = text.index(case_id)
    rdj_custody.record_human_approval(run.root, case_id=case_id, source='user_steering',
        path=pin['path'], start=start, end=start + len(case_id), text=case_id, attestation=attestation)
    return pin


def binding(operator, run, case_id):
    capture = operator.approval_capture
    digest = rdj_custody._commit_line(run.root, case_id)['record']['data']['digest']
    # Captures bind the complete text bytes, even though custody quotes only the case span.
    from rdj_fixtures import sha
    return capture.case_binding(run.root, case_id, digest, sha(f'I approve {case_id}.'))


def test_unattested_text_records_no_approval_and_no_human_credit(case):
    run, case_id = case
    with pytest.raises(ValueError, match='controller capture'):
        record(run, case_id)
    assert approvals(run, case_id) == []
    assert human(run, case_id) is False


@pytest.mark.parametrize('fixture_class', ['run', 'copied_authority'])
def test_exact_capture_earns_human_credit_and_uses_real_chain(case, operator, fixture_class):
    run, case_id = case
    target = run
    if fixture_class == 'copied_authority':
        from test_research_full_cycle_authority import Authority
        target = Authority.__new__(Authority)
        target.root = run.root
    target.approve(case_id)
    assert human(run, case_id) is True
    rows = operator.ledger_rows()
    assert len(rows) == 1 and rows[0]['record']['purpose'] == 'case_approval'
    assert not operator.approval_capture._ledger().is_relative_to(run.root.parent)
    expected = binding(operator, run, case_id)
    attestation = operator.approval_capture.find('case_approval', expected)
    assert operator.approval_capture.verify(attestation, purpose='case_approval', binding=expected)
    assert attestation['human_identity_authenticated'] is False


@pytest.mark.parametrize('field', ['rundir', 'case_id', 'action_digest', 'text_sha256', 'purpose'])
def test_capture_of_changed_decision_is_refused_at_record(case, operator, field):
    run, case_id = case
    subject = binding(operator, run, case_id)
    purpose = 'case_approval'
    if field == 'purpose':
        purpose = 'checkin_response'
    elif field == 'rundir':
        subject[field] = str(run.root.parent / 'other-run')
    elif field == 'case_id':
        subject[field] = case_id + '-other'
    else:
        subject[field] = '0' * 64
    attestation = operator.confirm(purpose, subject)
    with pytest.raises(ValueError, match='different decision'):
        record(run, case_id, attestation)
    assert approvals(run, case_id) == []
    assert human(run, case_id) is False


@pytest.mark.parametrize('damage', ['absent', 'corrupt_record', 'corrupt_digest'])
def test_capture_removed_or_corrupted_after_recording_loses_human_credit(case, operator, damage):
    run, case_id = case
    attestation = operator.confirm('case_approval', binding(operator, run, case_id))
    record(run, case_id, attestation)
    assert human(run, case_id) is True
    ledger = operator.approval_capture._ledger()
    if damage == 'absent':
        ledger.unlink()
    else:
        row = json.loads(ledger.read_text())
        if damage == 'corrupt_record':
            row['record']['binding_sha256'] = '0' * 64
        else:
            row['digest'] = '0' * 64
        ledger.write_text(json.dumps(row) + '\n')
    assert approvals(run, case_id)  # the recorded row stays readable
    assert human(run, case_id) is False


def test_capture_absent_from_the_ledger_is_refused_at_record(case, operator):
    run, case_id = case
    attestation = deepcopy(operator.confirm('case_approval', binding(operator, run, case_id)))
    attestation['custody']['seq'] += 1
    with pytest.raises(ValueError, match='absent from the capture ledger'):
        record(run, case_id, attestation)
    assert approvals(run, case_id) == [] and human(run, case_id) is False


def test_caller_written_capture_claim_is_refused_at_record(case):
    run, case_id = case
    with pytest.raises(ValueError, match='no controller capture'):
        record(run, case_id, {'untrusted': 'caller-written capture claim'})
    assert approvals(run, case_id) == [] and human(run, case_id) is False


def test_confirmed_false_records_no_approval(case, operator):
    run, case_id = case
    with pytest.raises(ValueError, match='controller capture'):
        run.approve(case_id, confirmed=False)
    assert approvals(run, case_id) == []
    assert human(run, case_id) is False
    assert operator.ledger_rows() == []


@pytest.mark.parametrize('confirmed', [False, True])
def test_response_propagates_only_explicit_operator_capture(case, operator, monkeypatch, confirmed):
    run, case_id = case
    calls = operator.operator_at_terminal(monkeypatch)
    result = gate_wiring.respond(run.root, f'I approve {case_id}.', approve=[case_id], confirm=confirmed)
    assert human(run, case_id) is confirmed
    assert result['decisions'][0]['human_authority'] is confirmed
    assert result['decisions'][0]['effective'] is confirmed
    assert len(calls) == int(confirmed)
    assert len(approvals(run, case_id)) == int(confirmed)


def test_response_terminal_refusal_records_nothing(case, operator, monkeypatch):
    run, case_id = case
    operator.operator_at_terminal(monkeypatch, confirms=False)
    before = rdj_custody.rows(run.root, 'user_text'), rdj_custody.rows(run.root, 'approvals')
    with pytest.raises(operator.approval_capture.CaptureRefused):
        gate_wiring.respond(run.root, f'I approve {case_id}.', approve=[case_id], confirm=True)
    assert (rdj_custody.rows(run.root, 'user_text'), rdj_custody.rows(run.root, 'approvals')) == before
    assert human(run, case_id) is False


def test_an_automated_terminal_without_a_capture_earns_no_credit(case, monkeypatch):
    """A process with no controlling terminal is refused before anything is recorded."""
    run, case_id = case
    from ravel.workflow import approval_capture

    def no_terminal():
        raise OSError('no controlling terminal')
    monkeypatch.setattr(approval_capture, '_open_terminal', no_terminal)
    before = rdj_custody.rows(run.root, 'approvals')
    with pytest.raises(approval_capture.CaptureRefused, match='no controlling terminal'):
        gate_wiring.respond(run.root, f'I approve {case_id}.', approve=[case_id], confirm=True)
    assert rdj_custody.rows(run.root, 'approvals') == before
    assert human(run, case_id) is False


def test_capture_context_restores_the_copied_authority_method(tmp_path):
    from test_research_full_cycle_authority import Authority
    old_run, old_authority = Run.approve, Authority.approve
    with captured_operator(tmp_path):
        from inspect import signature
        assert Run.approve is Authority.approve
        assert 'confirmed' in signature(Run.approve).parameters
    assert Run.approve is old_run and Authority.approve is old_authority


def test_nested_capture_scope_preserves_outer_approval_after_inner_exit(case, operator, tmp_path):
    run, case_id = case
    capture = operator.approval_capture
    ledger = capture._ledger()
    with captured_operator(tmp_path / 'inner') as nested:
        assert nested is operator and nested.approval_capture is capture
        assert nested.approval_capture._ledger() == ledger
        run.approve(case_id)
        assert human(run, case_id) is True
    assert ledger.is_file() and human(run, case_id) is True
    assert capture.verify(capture.find('case_approval', binding(operator, run, case_id)),
        purpose='case_approval', binding=binding(operator, run, case_id))


def test_respond_cli_confirms_exact_case_capture(case, operator, monkeypatch, capsys):
    run, case_id = case
    calls = operator.operator_at_terminal(monkeypatch)
    assert gate_wiring.main(['respond', '--rundir', str(run.root), '--approve', case_id,
        '--text', f'I approve {case_id}.', '--confirm-terminal']) == 0
    digest = run.case(case_id)['decision_point']['action']['digest']
    assert calls == [{'purpose': 'case_approval', 'binding': binding(operator, run, case_id),
        'summary': f'Approve case {case_id} (action {digest[:12]}) of {run.root.resolve()}'}]
    assert human(run, case_id) is True
    assert json.loads(capsys.readouterr().out)['decisions'][0]['human_authority'] is True


def test_respond_cli_without_confirmation_records_no_approval(case, operator, monkeypatch, capsys):
    run, case_id = case
    calls = operator.operator_at_terminal(monkeypatch)
    assert gate_wiring.main(['respond', '--rundir', str(run.root), '--approve', case_id,
        '--text', f'I approve {case_id}.']) == 0
    assert calls == [] and approvals(run, case_id) == [] and human(run, case_id) is False
    assert json.loads(capsys.readouterr().out)['decisions'][0]['human_authority'] is False


@pytest.fixture
def shared_ledger_fixture():
    """The shared conftest capture-ledger fixture body, compiled from the real tests/conftest.py."""
    import ast
    target = Path(__file__).resolve().parents[2] / 'conftest.py'
    fixture = next(node for node in ast.parse(target.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == '_operator_capture_private_ledger')
    fixture.decorator_list = []  # Call the exact fixture body without starting another pytest session.
    namespace = {}
    exec(compile(ast.Module(body=[fixture], type_ignores=[]), str(target), 'exec'), namespace)
    return namespace[fixture.name]


def test_shared_fixture_allocates_a_private_ledger_on_first_use_and_retains_it(
        case, shared_ledger_fixture, tmp_path_factory, tmp_path):
    run, case_id = case
    from ravel.workflow import approval_capture as capture
    calls = []

    class PrivateFactory:
        def mktemp(self, name):
            calls.append(name)
            return tmp_path_factory.mktemp(name)

    old_ledger = capture._ledger
    with pytest.MonkeyPatch.context() as scope:
        shared_ledger_fixture(PrivateFactory(), scope)
        assert calls == []  # The private capture directory is allocated on first use only.
        with captured_operator(tmp_path) as outer:
            with captured_operator(tmp_path / 'nested'):
                run.approve(case_id)
        assert calls == ['operator-captures']
        ledger = capture._ledger()
        assert not ledger.is_relative_to(run.root.parent)
        assert ledger.is_file() and human(run, case_id) is True
        expected = binding(outer, run, case_id)
        assert capture.verify(capture.find('case_approval', expected), purpose='case_approval', binding=expected)
    assert capture._ledger is old_ledger

