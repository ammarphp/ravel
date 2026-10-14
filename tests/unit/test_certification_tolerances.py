"""Synthetic approval-bound tolerance controls; no native execution."""
import copy
import json
import sys
from pathlib import Path

import pytest

from ravel.validation import certify_acceptance as producer
from ravel.validation import validate_checkin as vc
from ravel.validation import validate_run_state as vrs
from ravel.workflow import state_io, workflow_state as ws


DEFAULTS = dict(driving_tol=.15, contributing_tol=.25, mu95_bound=.10,
                tail_events=5, driving_factor=1.5, interp_max_span=200.0)
FIXTURES = Path(__file__).parents[1] / 'fixtures/certification-tolerances'


def document():
    return {'schema_version': 1, 'kind': 'checkin1', 'sections': {
        'i': 'Synthetic selection study', 'i-b': 'Supplied synthetic rows',
        'ii': 'Declared comparison', 'iii': {'waypoint': 'One bounded comparison'},
        'iv': 'No native work', 'v': [{'id': 'F1', 'text': 'Synthetic values only'}],
        'vi': ['answer', 'ask', 'propose']}}


def approved(root, overrides=None, *, section=True):
    state_io.atomic_json(root / 'inputs/task_contract.json', vrs._base_contract(
        task_mode='reproduce', compute_plan='none', targets={'analysis': ['synthetic-selection']}))
    checkin = document()
    if section:
        checkin['sections']['certification_tolerances'] = {**DEFAULTS, **(overrides or {})}
    state_io.atomic_json(root / 'inputs/checkin1.json', checkin)
    state_io.atomic_json(root / 'inputs/cost_preflight.json', {
        'schema_version': 1, 'generated_by': 'cost_preflight.py',
        'mode': 'none', 'walltime_h': [0, 0]})
    assert ws.main(['approve', '--rundir', str(root), '--plan', 'none',
                    '--quote', 'Approve the synthetic comparison']) == 0
    assert ws.verify_approval(str(root)) == []


def report(root, monkeypatch, extra=(), *, rundir=None):
    yields = root / 'outputs/yields.json'
    state_io.atomic_json(yields, {'SR_A': {'acceptance': .1, 'events': 100}})
    monkeypatch.setattr(producer, 'published_acceff',
                        lambda *_a, **_kw: (.1, 'grid node (100,10)', False))
    args = ['certify_acceptance', '--acceptance', str(yields), '--tables-dir', str(root),
            '--grid', 'synthetic-model', '--m-parent', '100', '--dm', '10', '--srs', 'SR_A',
            '--region-map', 'SR_A=region-A', '--out', str(root / 'outputs/report.md')]
    if rundir is not None:
        args += ['--rundir', str(rundir)]
    monkeypatch.setattr(sys, 'argv', [*args, *extra])
    producer.main()
    return json.loads((root / 'outputs/report.json').read_text())


def deviation(root, name='driving_tol', before=.15, after=.3):
    (root / 'DEVIATIONS.md').write_text(
        '| parameter | from | to | why | touches |\n'
        '| --- | --- | --- | --- | --- |\n'
        f'| {name} | {before} | {after} | Synthetic diagnostic change | outputs/report.json |\n')


def test_missing_tolerances_are_refused_at_checkin(tmp_path):
    state_io.atomic_json(tmp_path / 'inputs/certification_tolerances.json', {})
    assert any('certification_tolerances' in e for e in vc.validate(document(), tmp_path))


def test_tolerances_appear_in_checkin_bytes(tmp_path):
    state_io.atomic_json(tmp_path / 'inputs/certification_tolerances.json', {'driving_tol': .2})
    raw = vc.checkin_bytes(document(), tmp_path)
    rendered = json.loads(raw)
    assert rendered['sections']['certification_tolerances'] == {**DEFAULTS, 'driving_tol': .2}
    assert vc.validate(rendered, tmp_path) == []
    rendered['sections']['certification_tolerances']['driving_tol'] = .5
    assert any('certification_tolerances' in e for e in vc.validate(rendered, tmp_path))


@pytest.mark.parametrize('name,value', [
    ('driving_tol', .3), ('contributing_tol', .5), ('mu95_bound', .2),
    ('tail_events', 9), ('driving_factor', 2), ('interp_max_span', 300)])
def test_changed_tolerance_without_deviation_is_refused(tmp_path, monkeypatch, name, value):
    approved(tmp_path)
    with pytest.raises(SystemExit, match=name):
        report(tmp_path, monkeypatch, [f'--{name.replace("_", "-")}', str(value)])
    assert not (tmp_path / 'outputs/report.json').exists()


@pytest.mark.parametrize('row', ['unrelated', 'wrong_from', 'wrong_to', 'prose_only', 'empty_reason'])
def test_nonmatching_deviation_does_not_authorize_change(tmp_path, monkeypatch, row):
    approved(tmp_path)
    if row == 'unrelated':
        deviation(tmp_path, 'mu95_bound', .1, .3)
    elif row == 'wrong_from':
        deviation(tmp_path, before=.2)
    elif row == 'wrong_to':
        deviation(tmp_path, after=.4)
    elif row == 'prose_only':
        (tmp_path / 'DEVIATIONS.md').write_text('Maybe change driving_tol from 0.15 to 0.3 someday.')
    else:
        deviation(tmp_path)
        path = tmp_path / 'DEVIATIONS.md'
        path.write_text(path.read_text().replace('Synthetic diagnostic change', ''))
    with pytest.raises(SystemExit, match='driving_tol'):
        report(tmp_path, monkeypatch, ['--driving-tol', '.3'])


def test_named_deviation_is_bound_in_report(tmp_path, monkeypatch):
    approved(tmp_path)
    deviation(tmp_path, after=.1)
    result = report(tmp_path, monkeypatch, ['--driving-tol', '.1'])
    policy = result['certification_tolerances']
    assert policy['approved'] == DEFAULTS
    assert policy['effective']['driving_tol'] == result['driving_tol'] == .1
    assert policy['deviations'][0]['parameter'] == 'driving_tol'
    from ravel.validation.certification_tolerances import verify_report
    assert verify_report(tmp_path, result) == []
    (tmp_path / 'DEVIATIONS.md').write_text('Removed the recorded change.')
    assert verify_report(tmp_path, result)


TIGHTER = [('driving_tol', .1), ('contributing_tol', .2), ('mu95_bound', .05),
           ('tail_events', 3), ('driving_factor', 2), ('interp_max_span', 100)]
LOOSER = [('driving_tol', .3), ('contributing_tol', .5), ('mu95_bound', .2),
          ('tail_events', 9), ('driving_factor', 1.2), ('interp_max_span', 300)]


@pytest.mark.parametrize('name,value', TIGHTER)
def test_each_exact_deviation_is_recorded(tmp_path, monkeypatch, name, value):
    approved(tmp_path)
    deviation(tmp_path, name, DEFAULTS[name], value)
    result = report(tmp_path, monkeypatch, [f'--{name.replace("_", "-")}', str(value)])
    assert result['certification_tolerances']['effective'][name] == value
    assert result['certification_tolerances']['deviations'][0]['parameter'] == name


def test_composer_context_expands_all_defaults():
    raw = vc.checkin_bytes(document(), context={'certification_tolerances': {}})
    assert json.loads(raw)['sections']['certification_tolerances'] == DEFAULTS


def test_missing_approval_is_refused(tmp_path, monkeypatch):
    approved(tmp_path)
    (tmp_path / 'inputs/checkin1_approval.json').unlink()
    with pytest.raises(SystemExit, match='approval'):
        report(tmp_path, monkeypatch)


def test_approval_change_during_comparison_is_refused(tmp_path, monkeypatch):
    approved(tmp_path)
    original = producer.read_my_acceptance
    def changed(path):
        approval = tmp_path / 'inputs/checkin1_approval.json'
        approval.write_text(approval.read_text() + ' ')
        return original(path)
    monkeypatch.setattr(producer, 'read_my_acceptance', changed)
    with pytest.raises(SystemExit, match='binding changed'):
        report(tmp_path, monkeypatch)
    assert not (tmp_path / 'outputs/report.json').exists()


def test_one_named_deviation_does_not_cover_two_changes(tmp_path, monkeypatch):
    approved(tmp_path)
    deviation(tmp_path)
    with pytest.raises(SystemExit, match='mu95_bound'):
        report(tmp_path, monkeypatch, ['--driving-tol', '.3', '--mu95-bound', '.2'])


def test_approved_overrides_are_read_when_flags_omitted(tmp_path, monkeypatch):
    approved(tmp_path, {'driving_tol': .2, 'tail_events': 7})
    result = report(tmp_path, monkeypatch)
    assert result['driving_tol'] == .2
    assert result['certification_tolerances']['effective']['tail_events'] == 7


def test_changed_checkin_cannot_redefine_approved_tolerances(tmp_path, monkeypatch):
    approved(tmp_path)
    path = tmp_path / 'inputs/checkin1.json'
    doc = state_io.read_json(path)
    doc['sections']['certification_tolerances']['driving_tol'] = .3
    state_io.atomic_json(path, doc)
    deviation(tmp_path)
    with pytest.raises(SystemExit, match='approval'):
        report(tmp_path, monkeypatch, ['--driving-tol', '.3'])


def test_governed_certificate_requires_an_approved_section(tmp_path, monkeypatch):
    approved(tmp_path, section=False)
    with pytest.raises(SystemExit, match='certification_tolerances'):
        report(tmp_path, monkeypatch)


def test_explicit_run_cannot_bypass_discovered_run(tmp_path, monkeypatch):
    root = tmp_path / 'run'
    approved(root)
    with pytest.raises(SystemExit, match='rundir'):
        report(root, monkeypatch, rundir=tmp_path)


@pytest.mark.parametrize('name,bad', [('driving_tol', True), ('tail_events', 2.5),
    ('mu95_bound', 0), ('contributing_tol', float('nan')), ('driving_factor', .5),
    ('interp_max_span', '200'), ('extra', .1)])
def test_invalid_proposed_controls_are_refused(tmp_path, name, bad):
    path = tmp_path / 'inputs/certification_tolerances.json'
    path.parent.mkdir()
    path.write_text(json.dumps({name: bad}))
    assert any('certification' in e for e in vc.validate(document(), tmp_path))


def test_diagnostic_report_is_the_legacy_report_plus_its_marker(tmp_path, monkeypatch):
    result = report(tmp_path, monkeypatch, ['--diagnostic'])
    assert result.pop('certification_tolerances') == {'schema_version': 1, 'governance': 'diagnostic',
                                                      'effective': DEFAULTS}
    assert result == json.loads((FIXTURES / 'legacy.json').read_text())
    md = (tmp_path / 'outputs/report.md').read_text().splitlines()
    assert md[-1].startswith('Diagnostic only:')
    assert '\n'.join(md[:-1]) + '\n' == (FIXTURES / 'legacy.md').read_text()


def test_out_of_run_certification_without_diagnostic_is_refused(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match='diagnostic'):
        report(tmp_path, monkeypatch, ['--driving-tol', '.9'])
    assert not (tmp_path / 'outputs/report.json').exists()


def test_diagnostic_report_never_passes_the_consumer(tmp_path, monkeypatch):
    result = report(tmp_path, monkeypatch, ['--diagnostic', '--driving-tol', '.9'])
    from ravel.validation.certification_tolerances import verify_report
    assert any('diagnostic' in e for e in verify_report(tmp_path, result))


def test_governed_run_cannot_write_a_diagnostic_report(tmp_path, monkeypatch):
    approved(tmp_path)
    with pytest.raises(SystemExit, match='diagnostic'):
        report(tmp_path, monkeypatch, ['--diagnostic'])


@pytest.mark.parametrize('name,value', LOOSER)
def test_deviation_row_never_loosens_an_approved_tolerance(tmp_path, monkeypatch, name, value):
    approved(tmp_path)
    deviation(tmp_path, name, DEFAULTS[name], value)
    with pytest.raises(SystemExit, match='renewed CHECK-IN 1 approval'):
        report(tmp_path, monkeypatch, [f'--{name.replace("_", "-")}', str(value)])
    assert not (tmp_path / 'outputs/report.json').exists()


def test_looser_tolerance_is_honoured_after_renewed_approval(tmp_path, monkeypatch):
    approved(tmp_path, {'driving_tol': .3})
    result = report(tmp_path, monkeypatch)
    assert result['certification_tolerances']['approved']['driving_tol'] == result['driving_tol'] == .3
    assert result['certification_tolerances']['deviations'] == []


def test_certification_required_plan_contract_renders_default_section():
    contract = {'stat_mode': 'best-sr-counting', 'request_plan': {'path': 'inputs/plan.json', 'sha256': '0' * 64}}
    rendered = json.loads(vc.checkin_bytes(document(), context={'contract': contract}))
    assert rendered['sections']['certification_tolerances'] == DEFAULTS
    assert any('certification_tolerances' in e
               for e in vc.registered_section_errors(document(), context={'contract': contract}))
    legacy = {'stat_mode': 'best-sr-counting'}
    assert 'certification_tolerances' not in json.loads(
        vc.checkin_bytes(document(), context={'contract': legacy}))['sections']


def test_acceptance_gate_verifies_named_reports(tmp_path, monkeypatch):
    from ravel.validation import certificates
    approved(tmp_path)
    governed = report(tmp_path, monkeypatch)
    state_io.atomic_json(tmp_path / 'outputs/governed.json', governed)
    assert certificates.acceptance_report_errors(tmp_path, ['outputs/governed.json'], .15) == []
    errs = certificates.acceptance_report_errors(tmp_path, ['outputs/governed.json'], .2)
    assert any('relative_tolerance' in e and 'driving_tol' in e for e in errs), errs
    ungoverned = {k: v for k, v in governed.items() if k != 'certification_tolerances'}
    state_io.atomic_json(tmp_path / 'outputs/ungoverned.json', ungoverned)
    errs = certificates.acceptance_report_errors(tmp_path, ['outputs/ungoverned.json'], .15)
    assert errs and any('certification_tolerances' in e for e in errs), errs
    state_io.atomic_json(tmp_path / 'outputs/routine.json', {'routine': 'TEST', 'verdict': 'PASS',
                                                              'driving_tol': .15, 'mu95_bound': .2, 'rows': []})
    assert certificates.acceptance_report_errors(tmp_path, ['outputs/routine.json'], .15) == []


def test_live_acceptance_certificate_calls_the_report_gate(tmp_path, monkeypatch):
    from ravel.validation import certificates
    calls = []
    monkeypatch.setattr(certificates, 'acceptance_report_errors',
                        lambda root, subjects, tolerance, require=False:
                        calls.append((list(subjects), tolerance, require)) or ['gate refused'])
    sys.path.insert(0, str(Path(__file__).parent))
    import test_certificates as tc
    contract, _, subject = tc.fixture(tmp_path, kind='acceptance')
    result = tc.check(tmp_path, contract, kind='acceptance', subject=subject)
    # Every subject of the certificate plan is examined, and one per-run report is required.
    assert calls == [([subject], .15, True)] and result['status'] == 'FAIL' and 'gate refused' in result['errors'][0]


def test_live_gate_refuses_a_certificate_without_an_acceptance_report(tmp_path):
    from ravel.validation import certificates
    state_io.atomic_json(tmp_path / 'outputs/statistics.json', {'mu95': 1.0})
    errs = certificates.acceptance_report_errors(tmp_path, ['outputs/statistics.json'], .15, require=True)
    assert errs and any('no per-run acceptance report' in e for e in errs), errs
    assert certificates.acceptance_report_errors(tmp_path, ['outputs/statistics.json'], .15) == []


def test_a_routine_key_does_not_hide_an_unbound_acceptance_report(tmp_path, monkeypatch):
    from ravel.validation import certificates
    approved(tmp_path)
    governed = report(tmp_path, monkeypatch)
    disguised = {k: v for k, v in governed.items() if k != 'certification_tolerances'}
    disguised['routine'] = 'TEST'
    state_io.atomic_json(tmp_path / 'outputs/disguised.json', disguised)
    errs = certificates.acceptance_report_errors(tmp_path, ['outputs/disguised.json'], .15, require=True)
    assert errs and any('certification_tolerances' in e for e in errs), errs


def test_legacy_checkin_bytes_are_unchanged():
    assert vc.checkin_bytes(document()) == (json.dumps(document(), indent=2) + '\n').encode()


def test_report_consumer_rejects_tampered_effective_values(tmp_path, monkeypatch):
    approved(tmp_path)
    result = report(tmp_path, monkeypatch)
    changed = copy.deepcopy(result)
    changed['certification_tolerances']['effective']['driving_tol'] = .4
    from ravel.validation.certification_tolerances import verify_report
    assert verify_report(tmp_path, changed)


def test_certification_on_an_operation_bound_approval(tmp_path, monkeypatch):
    """Certification binds operation inputs; a changed declared input stales the approval certification reads."""
    approved(tmp_path)
    record = json.loads((tmp_path / 'inputs/checkin1_approval.json').read_text())
    assert 'approved_inputs' in record
    result = report(tmp_path, monkeypatch)
    from ravel.validation.certification_tolerances import verify_report
    assert verify_report(tmp_path, result) == []
    contract = json.loads((tmp_path / 'inputs/task_contract.json').read_text())
    contract['assumptions'] = ['a changed declared input after approval']
    state_io.atomic_json(tmp_path / 'inputs/task_contract.json', contract)
    assert verify_report(tmp_path, result)
    with pytest.raises(SystemExit, match='approval'):
        report(tmp_path, monkeypatch)
