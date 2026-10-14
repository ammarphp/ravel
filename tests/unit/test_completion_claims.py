"""Receipt-derived claim, selection and disclosure controls on synthetic quantities."""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import task_completion as tc, state_io, execution
from ravel.validation import validate_checkin
from test_task_completion import write
from test_physics_review import make_attempt


def quantity(root, monkeypatch, value=2):
    import platform
    monkeypatch.setattr(platform, 'platform', lambda: 'synthetic runtime')
    write(root / 'inputs/settings.cfg', {'setting': 1})
    write(root / 'inputs/held-fixed.txt', {'fixed': 1})
    record = make_attempt(root, value=value)
    ledger = execution.load_execution(root)['stages']['detector']
    return write(root / 'inputs/quantity-binding.json', {'quantity': 'value'}), {
        'quantity': __import__('test_task_completion', fromlist=['pin']).pin(root / 'outputs/produced.json'),
        'execution_receipts': [__import__('test_task_completion', fromlist=['pin']).pin(root / ledger['attempt_record'])],
        'validator_receipts': []}


@pytest.mark.parametrize('kind', ['checkin1', 'checkin2', 'deck'])
@pytest.mark.parametrize('domain', ['theory', 'ml'])
def test_successful_receipt_without_validator_cannot_be_certified(tmp_path, monkeypatch, kind, domain):
    _, bindings = quantity(tmp_path, monkeypatch)
    claims = [{'id': 'K1', 'domain': domain, 'fidelity': 'certified', 'n_trials': 1, **bindings}]
    doc = {'schema_version': 1, 'kind': kind, 'sections': {'claims': claims}}
    errors = validate_checkin.validate(doc, str(tmp_path))
    assert any('certified_requires_validated' in error for error in errors)
    from ravel.workflow.completion_claims import validate_delivery
    with pytest.raises(ValueError, match='certified_requires_validated'):
        validate_delivery(tmp_path, {'claims': claims})


def test_status_is_computed_and_current_reference_tolerance_required(tmp_path, monkeypatch):
    from ravel.workflow.evidence_status import derive
    _, bindings = quantity(tmp_path, monkeypatch)
    assert derive(tmp_path, **bindings)['state'] == 'executed'
    check = write(tmp_path / 'inputs/finite-check.json', {'schema_version': 1, 'kind': 'finite-quantity',
                  'id': 'finite', 'subject': bindings['quantity'], 'pointer': '/value'})
    bindings['validator_receipts'] = [check]
    assert derive(tmp_path, **bindings) == {'state': 'checked', 'validator_ids': ['finite']}
    reference = write(tmp_path / 'inputs/reference.json', {'value': 2.1})
    validation = write(tmp_path / 'inputs/reference-check.json', {'schema_version': 1, 'kind': 'reference-comparison',
                       'id': 'comparison', 'subject': bindings['quantity'], 'pointer': '/value',
                       'reference': reference, 'reference_pointer': '/value', 'tolerance': {'absolute': .2, 'relative': 0}})
    bindings['validator_receipts'] = [validation]
    status = derive(tmp_path, **bindings)
    assert status['state'] == 'validated' and status['reference'] == reference
    write(Path(reference['path']), {'value': 100})
    with pytest.raises(ValueError): derive(tmp_path, **bindings)


def test_declared_validated_status_and_wrong_subject_do_not_grant_validation(tmp_path, monkeypatch):
    from ravel.workflow.evidence_status import derive
    _, bindings = quantity(tmp_path, monkeypatch)
    wrong = write(tmp_path / 'outputs/other.json', {'value': 2})
    fake = write(tmp_path / 'inputs/fake-check.json', {'schema_version': 1, 'kind': 'finite-quantity',
                 'id': 'finite', 'subject': wrong, 'pointer': '/value', 'status': 'PASS'})
    with pytest.raises(ValueError): derive(tmp_path, **{**bindings, 'validator_receipts': [fake]})
    with pytest.raises(ValueError): derive(tmp_path, **{**bindings, 'quantity': wrong})


def selection(root, *, empty=False):
    trials = [] if empty else [{'id': 'T1', 'candidate': 'I1', 'select': 5.0, 'confirm': 1.0, 'seed': 1, 'confirm_seed': 2},
                             {'id': 'T2', 'candidate': 'I2', 'select': 2.0, 'confirm': 2.0, 'seed': 3, 'confirm_seed': 4}]
    value = {'n_trials': len(trials), 'trials': trials, 'selected_candidate': None if empty else 'I1',
             'selected_result_on_confirm': None if empty else 1.0,
             'best_of_n_select': None if empty else 5.0, 'rule': 'maximum-select', 'objective': 'maximize'}
    return write(root / 'research/selection.json', value)


def test_claim_missing_N_fails_and_selected_confirm_is_primary(tmp_path):
    from ravel.workflow.completion_claims import selection_record
    sp = selection(tmp_path)
    assert selection_record(sp, base_dir=tmp_path)['selected_result_on_confirm'] == 1.0
    value = state_io.read_json(sp['path']); del value['n_trials']
    sp = write(Path(sp['path']), value)
    with pytest.raises(ValueError, match='trials_unreported'): selection_record(sp, base_dir=tmp_path)


def test_optimistic_maximum_and_oracle_gap_are_separate(tmp_path):
    from ravel.workflow.completion_claims import selection_record
    record = selection_record(selection(tmp_path), base_dir=tmp_path)
    assert record['best_of_n_select'] == {'value': 5.0, 'label': 'optimistic'}
    assert record['oracle_gap'] == 1.0
    assert record['n_trials'] == 2


def test_minimization_oracle_gap_reports_nonnegative_selection_loss(tmp_path):
    from ravel.workflow.completion_claims import selection_record
    pin = selection(tmp_path); value = state_io.read_json(pin['path'])
    value.update(objective='minimize', selected_candidate='I2', selected_result_on_confirm=2.0, best_of_n_select=2.0)
    record = selection_record(write(Path(pin['path']), value), base_dir=tmp_path)
    assert record['oracle_gap'] == 1.0
    assert record['best_of_n_select'] == {'value': 2.0, 'label': 'optimistic'}


def protocol(root, *, null=False):
    sp = selection(root, empty=null)
    candidates = [] if null else [{'id': 'I1'}, {'id': 'I2'}, {'id': 'I3'}]
    screen = {'verdicts': [] if null else [{'idea': 'I1', 'verdict': 'promote'}, {'idea': 'I2', 'verdict': 'promote'}, {'idea': 'I3', 'verdict': 'discard'}]}
    write(root / 'research/protocol.json', {'schema_version': 1, 'kind': 'research-protocol', 'regime': 'open_exploratory',
          'stages': [{'id': 'ideas', 'ideas': candidates}, {'id': 'screen', **screen}, {'id': 'validate', 'selection': sp}]})
    return sp


def test_null_funnel_delivers_with_explicit_zero_trials(tmp_path):
    from ravel.workflow.completion_claims import validate_delivery
    from ravel.workflow.completion_disclosure import build
    protocol(tmp_path, null=True)
    block = build(tmp_path)
    delivered = validate_delivery(tmp_path, {'claims': [], 'disclosure': block})
    assert delivered['disclosure']['candidate_funnel']['selected'] == 0
    assert delivered['disclosure']['candidate_funnel']['generated'] == 0


def test_null_selection_retains_completed_trials_without_a_selected_claim(tmp_path):
    from ravel.workflow.completion_claims import selection_record
    pin = selection(tmp_path)
    value = state_io.read_json(pin['path'])
    value.update(selected_candidate=None, selected_result_on_confirm=None)
    record = selection_record(write(Path(pin['path']), value), base_dir=tmp_path)
    assert record['n_trials'] == 2 and record['selected_result_on_confirm'] is None
    assert record['best_of_n_select'] == {'value': 5.0, 'label': 'optimistic'}


def test_quantity_cannot_validate_against_itself(tmp_path, monkeypatch):
    from ravel.workflow.evidence_status import derive
    _, bindings = quantity(tmp_path, monkeypatch)
    check = write(tmp_path / 'inputs/check.json', {'schema_version': 1, 'kind': 'reference-comparison',
        'id': 'self', 'subject': bindings['quantity'], 'pointer': '/value',
        'reference': bindings['quantity'], 'reference_pointer': '/value',
        'tolerance': {'absolute': 0, 'relative': 0}})
    with pytest.raises(ValueError, match='independent reference'):
        derive(tmp_path, **{**bindings, 'validator_receipts': [check]})


@pytest.mark.parametrize('delivery_kind', ['delivery', 'manuscript'])
def test_delivery_and_manuscript_cannot_omit_or_edit_computed_funnel(tmp_path, delivery_kind):
    from ravel.workflow.completion_claims import validate_delivery
    from ravel.workflow.completion_disclosure import build
    protocol(tmp_path)
    with pytest.raises(ValueError, match='funnel_disclosure_missing'):
        validate_delivery(tmp_path, {'kind': delivery_kind, 'claims': []})
    block = build(tmp_path); block['candidate_funnel']['generated'] = 1
    with pytest.raises(ValueError, match='disclosure_differs'):
        validate_delivery(tmp_path, {'kind': delivery_kind, 'claims': [], 'disclosure': block})


def test_disclosure_computes_dataset_deltas_human_help_and_regime(tmp_path):
    from ravel.workflow.completion_disclosure import build
    protocol(tmp_path)
    before = write(tmp_path / 'research/data-before.json', {'rows': 100, 'origin': 'supplied'})
    after = write(tmp_path / 'research/data-after.json', {'rows': 20, 'origin': 'subsampled'})
    write(tmp_path / 'research/dataset_manifest_deltas.json', {'deltas': [{'before': before, 'after': after,
          'operation': 'subsampling', 'reason': 'Bounded screening population'}]})
    write(tmp_path / 'research/human_interventions.json', {'interventions': [{'kind': 'human_manual',
          'action': 'filtering', 'reason': 'Discarded malformed supplied rows'}]})
    result = build(tmp_path)
    assert result['candidate_funnel'] == {'generated': 3, 'screened': 3, 'discarded': 1, 'selected': 1,
           'selected_candidate': 'I1', 'rule': 'maximum-select', 'n_trials': 2}
    assert result['dataset_manifest_deltas'][0]['changed_fields'] == ['origin', 'rows']
    assert result['human_interventions'][0]['kind'] == 'human_manual'
    assert result['regime'] == 'open_exploratory'


def test_delivered_claim_requires_N_and_never_promotes_selection_fluke(tmp_path, monkeypatch):
    from ravel.workflow.completion_claims import claim_record
    _, bindings = quantity(tmp_path, monkeypatch, value=1)
    claim = {'id': 'K1', 'fidelity': 'executed', 'selection': selection(tmp_path), **bindings}
    with pytest.raises(ValueError, match='trials_unreported'): claim_record(tmp_path, claim)
    claim.update(n_trials=2, result=5.0)
    with pytest.raises(ValueError, match='selected_confirmation_required'): claim_record(tmp_path, claim)
    claim['result'] = 1.0
    assert claim_record(tmp_path, claim)['selected_result_on_confirm'] == 1.0


def test_closed_scored_requires_fresh_confirmation_seed(tmp_path):
    from ravel.workflow.completion_claims import selection_record
    pin = selection(tmp_path); value = state_io.read_json(pin['path'])
    value['trials'][0]['confirm_seed'] = value['trials'][0]['seed']
    pin = write(Path(pin['path']), value)
    with pytest.raises(ValueError, match='fresh confirmation'):
        selection_record(pin, base_dir=tmp_path, regime='closed_scored')


def test_failed_reference_cannot_be_promoted_by_supplied_PASS(tmp_path, monkeypatch):
    from ravel.workflow.evidence_status import derive
    _, bindings = quantity(tmp_path, monkeypatch)
    ref = write(tmp_path / 'inputs/reference.json', {'value': 20})
    validation = write(tmp_path / 'inputs/check.json', {'schema_version': 1, 'kind': 'reference-comparison',
        'id': 'comparison', 'subject': bindings['quantity'], 'pointer': '/value', 'reference': ref,
        'reference_pointer': '/value', 'tolerance': {'absolute': .1, 'relative': 0}, 'status': 'PASS'})
    with pytest.raises(ValueError, match='fails declared tolerance'):
        derive(tmp_path, **{**bindings, 'validator_receipts': [validation]})


def test_manuscript_requires_rendered_computed_disclosure(tmp_path):
    from ravel.workflow.completion_claims import require_manuscript_disclosure, render
    from ravel.workflow.completion_disclosure import build
    protocol(tmp_path, null=True)
    records = {'claims': [], 'disclosure': build(tmp_path)}
    reviewed = {'report_text': 'A manuscript without the funnel.',
                'quantitative_report': {'task_completion': {'claim_records': records}}}
    with pytest.raises(ValueError, match='funnel_disclosure_missing'):
        require_manuscript_disclosure(tmp_path, reviewed)
    reviewed['report_text'] += render(records)
    require_manuscript_disclosure(tmp_path, reviewed)


@pytest.mark.parametrize('change', ['new', 'stronger', 'narrower_without_deviation', 'omitted'])
def test_delivery_cannot_silently_change_declared_claims(tmp_path, change):
    from ravel.workflow.completion_claims import reconcile
    original = {'id': 'K1', 'kind': 'exclusion', 'level': '95% CLs', 'statistic': 'CLs',
                'comparison': 'supplied-reference', 'basis_declared': ['supplied_inputs', 'counts']}
    contract = {'request_plan': write(tmp_path / 'inputs/plan.json', {'claims': [original]})}
    delivered = deepcopy(original)
    if change == 'new': delivered['id'] = 'K2'
    elif change == 'stronger': delivered['level'] = '99% CLs'
    elif change == 'narrower_without_deviation': delivered['basis_declared'] = ['supplied_inputs']
    records = {'claims': [] if change == 'omitted' else [delivered]}
    observed = tc._Inputs(tmp_path)
    try:
        with pytest.raises(ValueError, match='new_checkin1_required|claim_deviation_required'):
            reconcile(tmp_path, records, contract, observed)
    finally: observed.close()


def test_omitted_claim_has_a_pinned_located_boundary(tmp_path):
    from ravel.workflow.completion_claims import reconcile
    contract = {'request_plan': write(tmp_path / 'inputs/plan.json', {'claims': [{'id': 'K1'}]})}
    deviation = write(tmp_path / 'DEVIATIONS.md', {'reason': 'Supplied input does not cover the interval.'})
    boundary = write(tmp_path / 'inputs/boundary.json', {'kind': 'held-node', 'claim_id': 'K1',
                     'reason': 'No supported quantity in the supplied interval.', 'deviation': deviation})
    observed = tc._Inputs(tmp_path)
    try:
        reconcile(tmp_path, {'claims': [], 'omitted_claims': [{'id': 'K1', 'boundary': boundary}]}, contract, observed)
        observed.finish()
        Path(deviation['path']).write_text('{}')
        with pytest.raises(ValueError):
            reconcile(tmp_path, {'claims': [], 'omitted_claims': [{'id': 'K1', 'boundary': boundary}]}, contract, observed)
    finally: observed.close()


@pytest.mark.parametrize('label', ['Certified.', 'fully certified', 'certified at 5%', 'validated', 'checked'])
@pytest.mark.parametrize('kind', ['checkin1', 'deck'])
def test_free_fidelity_text_cannot_raise_derived_evidence(tmp_path, monkeypatch, label, kind):
    _, bindings = quantity(tmp_path, monkeypatch)
    claims = [{'id': 'K1', 'fidelity': label, 'n_trials': 1, **bindings}]
    doc = {'schema_version': 1, 'kind': kind, 'sections': {'claims': claims}}
    errors = validate_checkin.validate(doc, str(tmp_path))
    assert any('requires_' in error for error in errors)
    from ravel.workflow.completion_claims import claim_record
    with pytest.raises(ValueError, match='requires_'):
        claim_record(tmp_path, claims[0], require_trials=False)


@pytest.mark.parametrize('label', ['not certified on this route', 'uncertified-proxy', 'of record'])
def test_uncertified_fidelity_text_is_retained_but_record_fidelity_is_derived(tmp_path, monkeypatch, label):
    from ravel.workflow.completion_claims import claim_record
    _, bindings = quantity(tmp_path, monkeypatch)
    record = claim_record(tmp_path, {'id': 'K1', 'fidelity': label, **bindings}, require_trials=False)
    assert record['fidelity'] == 'executed' and record['declared_fidelity'] == label
    assert record['certified'] is False
