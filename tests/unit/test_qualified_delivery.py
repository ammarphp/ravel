"""Qualified reporting preserves obligations, refusals and journal custody."""
from pathlib import Path

import pytest

from ravel.workflow import task_completion as completion, physics_review as review, route_prompt
from ravel.workflow.state_io import atomic_json, read_json
from test_physics_review import run, opened, reject
from test_finding_routing import journal_classified, contract


def original_contract(root):
    prompt = 'Calculate a supplied dimensionless sum and describe missing inputs.'
    document = route_prompt.route(prompt)
    document['task_requirements'] = completion.initial_requirements(prompt)
    document['task_requirements']['obligations'].append({
        'id': 'missing-inputs', 'kind': 'deliverable', 'statement': 'Describe missing inputs.',
        'criteria': {'description': 'Every missing source is visible.'},
        'evidence': [{'start': 0, 'end': len(prompt), 'text': prompt}]})
    atomic_json(root / 'inputs/task_contract.json', document)
    return document


def pin(path):
    from ravel.workflow.execution import file_hash
    return {'path': str(path), 'sha256': file_hash(path), 'size': path.stat().st_size}


def stalled(run):
    root, _ = run; original_contract(root); opened(run); reject(root)
    review.escalate(root, reason='The supplied input is missing.', needed='Supply the source or accept the boundary summary.')
    return root


def test_complete_original_census_boundaries_and_deviation_without_new_authority(run):
    root = stalled(run)
    approved = (root / 'inputs/checkin1_approval.json').read_bytes()
    head = (root / review.HEAD).read_bytes()
    (root / 'DEVIATIONS.md').write_text('# Existing record\n\nAn earlier boundary.\n')
    result = completion.qualified_delivery(root)
    assert [r['obligation_id'] for r in result['obligations']] == ['original-request', 'missing-inputs']
    assert all(r['state'] == 'blocked' for r in result['obligations'])
    assert result['unresolved_findings'][0]['id'] == 'F1'
    assert result['parent_task_accepted'] is False and result['execution_authorized'] is False
    assert result['authority_origin_authenticated'] is False
    assert result['label'] == 'machine-produced status summary'
    for row in result['obligations']:
        assert row['boundary']['location'].startswith('$.obligations[')
        assert Path(row['boundary']['artifact']['path']).is_file()
        assert Path(row['deviation']['path']).name == 'DEVIATIONS.md'
    assert (root / 'DEVIATIONS.md').read_text().startswith('# Existing record\n\nAn earlier boundary.\n')
    assert (root / 'inputs/checkin1_approval.json').read_bytes() == approved
    assert (root / review.HEAD).read_bytes() == head
    assert review.gate_errors(root, 'bulk') and review.gate_errors(root, 'delivery')
    first = (root / 'DEVIATIONS.md').read_bytes()
    again = completion.qualified_delivery(root)
    assert again == result and (root / 'DEVIATIONS.md').read_bytes() == first


def test_ordinary_unexhausted_review_cannot_use_qualified_ending(run):
    root, _ = run; original_contract(root); opened(run); reject(root)
    with pytest.raises(ValueError, match='exhausted bounds or an escalated'):
        completion.qualified_delivery(root)
    assert not (root / 'DEVIATIONS.md').exists()


def test_limitation_claims_are_withdrawn_through_existing_disposition_contract(run):
    root, _ = run; original_contract(root); opened(run)
    finding = journal_classified(root, 'limitation', effect='invalidates', bound='claim fails')
    review.submit_review(root, role='physics_critic', actor_id='critic', verdict='send_back',
                         summary='Unsupported claim', findings=[finding])
    review.escalate(root, reason='The claim is unsupported.', needed='Review its withdrawal.')
    result = completion.qualified_delivery(root)
    assert result['claim_dispositions'][0]['disposition'] == 'withdrawn'
    assert 'claim fails' in result['claim_dispositions'][0]['reason']
    assert result['unresolved_findings'][0] == finding


def test_supplied_claim_package_must_withdraw_every_original_and_locate_reason(run):
    root = stalled(run)
    plan, rows, value, evidence = contract()
    rows[0].update(disposition='withdrawn', reason='Evidence remains unavailable.')
    value['paragraphs'][0]['text'] += ' Evidence remains unavailable.'
    package = root / 'inputs/claim-package.json'
    atomic_json(package, {'plan': plan, 'rows': rows, 'value': value, 'evidence': evidence})
    result = completion.qualified_delivery(root, claim_package=pin(package))
    assert result['claim_dispositions'] == rows
    assert result['claim_prose'] == value
    rows[0]['disposition'] = 'retained'
    atomic_json(package, {'plan': plan, 'rows': rows, 'value': value, 'evidence': evidence})
    with pytest.raises(ValueError, match='only withdraw'):
        completion.qualified_delivery(root, claim_package=pin(package))


def test_qualified_delivery_refuses_deleted_journal_and_linked_deviation(run, tmp_path):
    root = stalled(run)
    outside = tmp_path / 'external.md'; outside.write_text('preserved')
    (root / 'DEVIATIONS.md').unlink()
    (root / 'DEVIATIONS.md').symlink_to(outside)
    with pytest.raises(ValueError, match='ordinary qualified'):
        completion.qualified_delivery(root)
    assert outside.read_text() == 'preserved'
    (root / 'DEVIATIONS.md').unlink()
    events = sorted((root / review.DIRECTORY / 'events').glob('*.json'))
    events[-1].unlink()
    with pytest.raises(ValueError, match='intact review custody'):
        completion.qualified_delivery(root)


def test_delegated_bound_exhaustion_automatically_records_ending_and_refuses(run, monkeypatch):
    from ravel.workflow import scientific_autonomy
    root, _ = run; original_contract(root); opened(run); reject(root)
    calls = []
    actual = completion.qualified_delivery
    def report(*args, **kwargs):
        calls.append('report')
        return actual(*args, **kwargs)
    monkeypatch.setattr(completion, 'qualified_delivery', report)
    monkeypatch.setattr(scientific_autonomy, 'authorize', lambda *a: {'value': {'bounds': {
        'allowed_changed_paths': [], 'allowed_stages': [], 'max_redos': 0}}})
    with pytest.raises(ValueError, match='qualified ending recorded without new authority'):
        scientific_autonomy.correction_authority(root, {'changed_paths': ['inputs/settings.cfg'], 'stages': ['detector']})
    assert (root / 'outputs/completion/qualified-delivery.json').is_file()
    assert review.status(root)['state'] == 'escalated'
    assert calls == ['report']
    assert review.gate_errors(root, 'bulk')


@pytest.mark.parametrize('child_state,clipped,expected', [
    ('satisfied', False, 'satisfied'), ('negative', False, 'negative'),
    ('partial', False, 'partial'), ('blocked', False, 'blocked'),
    ('satisfied', True, 'partial'),
])
def test_qualified_states_require_current_reviewed_original_scope(run, tmp_path, monkeypatch,
                                                                 child_state, clipped, expected):
    from copy import deepcopy
    from test_task_completion import review_run
    from test_physics_review import make_attempt, check_packet
    from ravel.workflow import science
    root, _ = run
    document = original_contract(root)
    criteria = deepcopy(document['task_requirements']['obligations'][0]['criteria'])
    if clipped:
        criteria = {'description': 'A proper subset of the requested sum.'}
    document['task_requirements']['assignments'] = [{'id': 'sum-child', 'purpose': 'Review supplied sum inputs.',
        'coverage': [{'obligation_id': 'original-request', 'criteria': criteria}]}]
    atomic_json(root / 'inputs/task_contract.json', document)
    contract_pin = pin(root / 'inputs/task_contract.json')
    child = tmp_path / 'reviewed-child'; (child / 'inputs').mkdir(parents=True)
    atomic_json(child / science.SPEC, {'goal_binding': {'contract': contract_pin, 'assignment_id': 'sum-child'}})
    atomic_json(child / 'inputs/quantity.json', {'value': 3, 'source_inputs': [1, 2]})
    coverage = {'obligation_id': 'original-request', 'state': child_state, 'criteria': criteria,
                'evidence': [pin(child / 'inputs/quantity.json')], 'explanation': 'Exact retained scope.'}
    sources = [contract_pin['path'], str(child / science.SPEC), str(child / 'inputs/quantity.json')]
    if child_state in ('partial', 'blocked'):
        (child / 'DEVIATIONS.md').write_text('The missing source is unavailable.\n')
        atomic_json(child / 'inputs/boundary.json', {'kind': 'task-boundary', 'obligation_id': 'original-request',
            'claim_scope': 'diagnostic', 'reason': 'The missing source is unavailable.',
            'deviation': pin(child / 'DEVIATIONS.md')})
        coverage['boundary'] = pin(child / 'inputs/boundary.json')
        sources += [str(child / 'DEVIATIONS.md'), str(child / 'inputs/boundary.json')]
    review_run(child, sources, monkeypatch)
    request = root / 'inputs/completion-request.json'
    atomic_json(request, {'schema_version': 1, 'contract': contract_pin, 'outcomes': [{
        'assignment_id': 'sum-child', 'rundir': str(child), 'claim_scope': 'diagnostic', 'coverage': [coverage]}],
        'parent_review': None, 'report': None})
    attempt = make_attempt(root); check_packet(root, attempt)
    opened((root, attempt)); reject(root)
    review.escalate(root, reason='Remaining source unavailable.', needed='Review the located boundary.')
    result = completion.qualified_delivery(root, completion_request=pin(request))
    assert [r['state'] for r in result['obligations']] == [expected, 'blocked']
    assert result['parent_task_accepted'] is False and result['execution_authorized'] is False
    (child / 'inputs/quantity.json').write_text('{}')
    with pytest.raises(ValueError):
        completion.qualified_delivery(root, completion_request=pin(request))


@pytest.mark.parametrize('revoked', [False, True])
def test_reporting_labels_validate_delegation_and_preserve_revocation(run, revoked, monkeypatch):
    from ravel.workflow import scientific_autonomy as autonomy, science
    root, _ = run
    prompt = 'Run autonomously. Calculate a supplied dimensionless sum.'
    document = route_prompt.route(prompt)
    document['task_requirements'] = completion.initial_requirements(prompt)
    atomic_json(root / 'inputs/task_contract.json', document)
    source = root / 'inputs/initial-message.txt'; source.write_text(prompt)
    spec = {'schema_version': 2, 'goal_binding': {
        'contract': pin(root / 'inputs/task_contract.json'), 'assignment_id': 'sum-child'}}
    prepared = autonomy.prepare_declaration(spec, root / 'inputs/delegation.json',
        user_text={k: pin(source)[k] for k in ('path', 'sha256')}, quote=autonomy.delegation_intent(prompt)['text'],
        origin='initial_prompt', delegate_actor='coordinator', actions=['accept_recommendation'],
        bounds={'compute_plans': [], 'allowed_changed_paths': [], 'allowed_stages': [], 'max_redos': 0},
        task_class='research_analysis', base_dir=root)
    delegated_document = root / 'inputs/delegated-task.json'
    atomic_json(delegated_document, prepared['document'])
    # Isolate document selection from a scientific-plan launch; declaration custody stays live.
    monkeypatch.setattr(autonomy, '_run_document', lambda rd: (root, read_json(delegated_document)))
    opened(run); reject(root)
    review.escalate(root, reason='Source missing.', needed='Review the boundary.')
    if revoked:
        message = root / 'inputs/revocation-message.txt'; message.write_text('Stop delegated decisions.')
        autonomy.revoke(root, user_text={k: pin(message)[k] for k in ('path', 'sha256')},
                        quote='Stop delegated decisions.')
    result = completion.qualified_delivery(root)
    assert result['delegation_status'] == ('revoked' if revoked else 'recorded')
    assert result['label'] == ('machine-produced status summary' if revoked else 'machine-produced under delegation')
    assert result['execution_authorized'] is False and result['authority_origin_authenticated'] is False


def test_qualified_ending_cannot_replace_original_approved_obligations(run, monkeypatch):
    from ravel.workflow import workflow_state
    root, _ = run; document = original_contract(root)
    contract = root / 'inputs/task_contract.json'
    monkeypatch.setattr(workflow_state, 'approval_input_paths', lambda rd:
                        [str(root / review.POLICY), str(contract)])
    opened(run); reject(root)
    review.escalate(root, reason='Source missing.', needed='Review all original obligations.')
    previous = (root / 'outputs/completion/qualified-delivery.json').read_bytes()
    document['task_requirements']['obligations'].pop()
    atomic_json(contract, document)
    assert review.status(root)['state'] == 'escalated'
    assert review.status(root)['live_errors']
    with pytest.raises(ValueError):
        completion.qualified_delivery(root)
    assert (root / 'outputs/completion/qualified-delivery.json').read_bytes() == previous


@pytest.mark.parametrize('route', ['escalation', 'exhausted_review', 'exhausted_failure'])
def test_terminal_mutation_automatically_records_qualified_ending_without_execution(run, route):
    from test_physics_review import correct
    root, _ = run; original_contract(root)
    policy = read_json(root / review.POLICY)
    policy['max_redos'] = 1 if route == 'exhausted_failure' else 0
    atomic_json(root / review.POLICY, policy)
    opened(run)
    before = read_json(root / 'execution_state.json')
    events_before = review.status(root)['events']
    if route == 'escalation':
        event = review.escalate(root, reason='Source unavailable.', needed='Review the boundary.')
    elif route == 'exhausted_review':
        event = reject(root)
    else:
        reject(root)
        correction = correct(root)
        event = review.fail_correction(root, correction_id=correction['correction_id'], reason='Source unavailable.')
    result = read_json(root / 'outputs/completion/qualified-delivery.json')
    assert event['qualified_ending']['status'] == 'recorded'
    assert review.status(root)['events'] - events_before == (3 if route == 'exhausted_failure' else 1)
    assert [r['obligation_id'] for r in result['obligations']] == ['original-request', 'missing-inputs']
    assert all(r['state'] == 'blocked' for r in result['obligations'])
    assert result['parent_task_accepted'] is False and result['execution_authorized'] is False
    assert read_json(root / 'execution_state.json') == before
    assert review.gate_errors(root, 'bulk') and review.gate_errors(root, 'delivery')
    # Status remains observational and creates no second reporting step.
    files = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    review.status(root); review.status(root)
    assert {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()} == files


def test_automatic_ending_reports_failure_and_retries_without_new_escalation(run, monkeypatch):
    from ravel.workflow import state_io
    root, _ = run; original_contract(root); opened(run)
    real = completion.qualified_delivery
    monkeypatch.setattr(completion, 'qualified_delivery', lambda *a, **kw: (_ for _ in ()).throw(ValueError('repair needed')))
    event = review.escalate(root, reason='Source unavailable.', needed='Review the boundary.')
    assert event['qualified_ending']['status'] == 'unavailable'
    assert 'repair needed' in event['qualified_ending']['reason']
    assert review.status(root)['state'] == 'escalated'
    head = (root / review.HEAD).read_bytes()
    monkeypatch.setattr(completion, 'qualified_delivery', real)
    # The reporting callback must run after the review writer releases its lock.
    original = state_io.file_lock
    from contextlib import contextmanager
    @contextmanager
    def check_lock(*args, **kwargs):
        with original(root / review.DIRECTORY / 'write.lock', blocking=False):
            pass
        with original(*args, **kwargs):
            yield
    monkeypatch.setattr(state_io, 'file_lock', check_lock)
    again = review.escalate(root, reason=event['reason'], needed=event['needed'])
    assert again['qualified_ending']['status'] == 'recorded'
    assert again['sha256'] == event['sha256'] and (root / review.HEAD).read_bytes() == head
    first = (root / 'DEVIATIONS.md').read_bytes()
    assert review.escalate(root, reason=event['reason'], needed=event['needed']) == again
    assert (root / 'DEVIATIONS.md').read_bytes() == first


def test_qualified_ending_recaptures_sources_after_waiting_for_publication_lock(run, monkeypatch):
    from contextlib import contextmanager
    from ravel.workflow import state_io
    root = stalled(run)
    # Remove the prior result so the stale-publication refusal is visible.
    result = root / 'outputs/completion/qualified-delivery.json'
    if result.exists():
        result.unlink()
    original = state_io.file_lock
    @contextmanager
    def changing_lock(path, **kwargs):
        with original(path, **kwargs):
            if Path(path).name == 'qualified.lock':
                (root / 'inputs/task_contract.json').write_text('{}')
            yield
    monkeypatch.setattr(state_io, 'file_lock', changing_lock)
    with pytest.raises((ValueError, KeyError)):
        completion.qualified_delivery(root)
    assert not result.exists()


@pytest.mark.parametrize('write_site', ['deviation', 'boundary'])
@pytest.mark.parametrize('source', ['contract', 'journal'])
def test_publication_rechecks_sources_after_intermediate_writes(run, monkeypatch, write_site, source):
    from ravel.workflow import state_io
    root = stalled(run)
    targets = [root / 'DEVIATIONS.md', root / 'outputs/completion/qualified-boundary.json',
               root / 'outputs/completion/qualified-delivery.json']
    prior = {p: p.read_bytes() for p in targets}
    def change_source():
        if source == 'contract':
            (root / 'inputs/task_contract.json').write_text('{}')
        else:
            head = read_json(root / review.HEAD); head['sequence'] += 1
            atomic_json(root / review.HEAD, head)
    if write_site == 'deviation':
        original = completion._write_qualified_deviation
        def write(path, text):
            original(path, text)
            change_source()
        monkeypatch.setattr(completion, '_write_qualified_deviation', write)
    else:
        original = state_io.atomic_json
        def write(path, value):
            original(path, value)
            if Path(path).name == 'qualified-boundary.json':
                change_source()
        monkeypatch.setattr(state_io, 'atomic_json', write)
    response = review.escalate(root, reason='A changed reporting boundary.', needed='Review retained inputs.')
    assert response['qualified_ending']['status'] == 'unavailable'
    assert all(p.read_bytes() == before for p, before in prior.items())
    assert review.gate_errors(root, 'bulk') and review.gate_errors(root, 'delivery')


@pytest.mark.parametrize('after_replace', [False, True])
def test_failed_final_publication_preserves_previous_report_and_referenced_bytes(run, monkeypatch, after_replace):
    from ravel.workflow import state_io
    root = stalled(run)
    delivery = root / 'outputs/completion/qualified-delivery.json'
    targets = [root / 'DEVIATIONS.md', root / 'outputs/completion/qualified-boundary.json', delivery]
    prior = {p: p.read_bytes() for p in targets}
    original = state_io.atomic_json
    def fail(path, value):
        if Path(path) == delivery:
            if after_replace:
                original(path, value)
            raise OSError('injected final publication failure')
        original(path, value)
    monkeypatch.setattr(state_io, 'atomic_json', fail)
    response = review.escalate(root, reason='A changed reporting boundary.', needed='Review retained inputs.')
    assert response['qualified_ending']['status'] == 'unavailable'
    assert 'injected final publication failure' in response['qualified_ending']['reason']
    assert all(p.read_bytes() == before for p, before in prior.items())
    previous = read_json(delivery)
    assert pin(Path(previous['deviation']['path'])) == previous['deviation']
    assert pin(Path(previous['obligations'][0]['boundary']['artifact']['path'])) == previous['obligations'][0]['boundary']['artifact']
    assert review.status(root)['state'] == 'escalated'
    assert review.gate_errors(root, 'bulk') and review.gate_errors(root, 'delivery')


def test_failed_publication_preserves_a_concurrent_edit(run, monkeypatch):
    from ravel.workflow import state_io
    root = stalled(run)
    delivery = root / 'outputs/completion/qualified-delivery.json'
    deviation = root / 'DEVIATIONS.md'
    original = state_io.atomic_json
    def fail(path, value):
        if Path(path) == delivery:
            deviation.write_text('A separate retained edit.\n')
            raise OSError('injected final publication failure')
        original(path, value)
    monkeypatch.setattr(state_io, 'atomic_json', fail)
    response = review.escalate(root, reason='A changed reporting boundary.', needed='Review retained inputs.')
    assert response['qualified_ending']['status'] == 'unavailable'
    assert deviation.read_text() == 'A separate retained edit.\n'


def test_failed_first_publication_removes_only_its_new_artifacts(run, monkeypatch):
    from ravel.workflow import state_io
    root, _ = run; original_contract(root); opened(run)
    delivery = root / 'outputs/completion/qualified-delivery.json'
    original = state_io.atomic_json
    def fail(path, value):
        if Path(path) == delivery:
            raise OSError('injected final publication failure')
        original(path, value)
    monkeypatch.setattr(state_io, 'atomic_json', fail)
    response = review.escalate(root, reason='Source unavailable.', needed='Review retained inputs.')
    assert response['qualified_ending']['status'] == 'unavailable'
    assert not delivery.exists() and not (root / 'DEVIATIONS.md').exists()
    assert not (root / 'outputs/completion/qualified-boundary.json').exists()
    assert review.status(root)['state'] == 'escalated'


def test_failed_publication_preserves_a_concurrent_symbolic_link(run, tmp_path, monkeypatch):
    from ravel.workflow import state_io
    root = stalled(run)
    outside = tmp_path / 'separate-record.txt'; outside.write_text('A separate retained edit.\n')
    delivery = root / 'outputs/completion/qualified-delivery.json'
    deviation = root / 'DEVIATIONS.md'
    original = state_io.atomic_json
    def fail(path, value):
        if Path(path) == delivery:
            deviation.unlink(); deviation.symlink_to(outside)
            raise OSError('injected final publication failure')
        original(path, value)
    monkeypatch.setattr(state_io, 'atomic_json', fail)
    response = review.escalate(root, reason='A changed reporting boundary.', needed='Review retained inputs.')
    assert response['qualified_ending']['status'] == 'unavailable'
    assert deviation.is_symlink() and outside.read_text() == 'A separate retained edit.\n'


def test_rollback_failure_preserves_original_publication_error_context(run, monkeypatch):
    from ravel.workflow import state_io
    root = stalled(run)
    delivery = root / 'outputs/completion/qualified-delivery.json'
    deviation = root / 'DEVIATIONS.md'; prior = deviation.read_bytes()
    original = state_io.atomic_json
    def fail(path, value):
        if Path(path) == delivery:
            raise OSError('injected final publication failure')
        original(path, value)
    original_bytes = completion._write_qualified_bytes
    def fail_restore(path, raw):
        if Path(path) == deviation and raw == prior:
            raise OSError('injected restore failure')
        original_bytes(path, raw)
    monkeypatch.setattr(state_io, 'atomic_json', fail)
    monkeypatch.setattr(completion, '_write_qualified_bytes', fail_restore)
    response = review.escalate(root, reason='A changed reporting boundary.', needed='Review retained inputs.')
    assert response['qualified_ending']['status'] == 'unavailable'
    reason = response['qualified_ending']['reason']
    assert 'injected final publication failure' in reason and 'injected restore failure' in reason


@pytest.mark.parametrize('ending', ['successor', 'failed_correction'])
def test_no_progress_bound_automatically_reports_with_redo_budget_remaining(run, monkeypatch, ending):
    from test_physics_review import make_attempt, check_packet
    root, _ = run; original_contract(root)
    policy = read_json(root / review.POLICY); policy['max_redos'] = 3
    atomic_json(root / review.POLICY, policy)
    opened(run); reject(root)
    calls = []
    actual = completion.qualified_delivery
    def report(*args, **kwargs):
        calls.append('report')
        return actual(*args, **kwargs)
    monkeypatch.setattr(completion, 'qualified_delivery', report)
    for index in range(2):
        (root / 'inputs/settings.cfg').write_text(f'value={index + 2}\n')
        correction = review.authorize_correction(root, actor_id='physicist', changed_paths=['inputs/settings.cfg'],
            stages=['detector'], recheck_checks=['agreement'])
        if ending == 'failed_correction':
            event = review.fail_correction(root, correction_id=correction['correction_id'], reason='No result produced.')
        else:
            attempt = make_attempt(root, value=1); check_packet(root, attempt)
            opened((root, attempt), correction_id=correction['correction_id'])
            event = reject(root, name=f'F{index + 2}')
        if index == 0:
            assert calls == [] and 'qualified_ending' not in event
    state = review.status(root)
    assert state['redos_used'] == 2 and state['redos_remaining'] == 1
    assert state['limitation_candidates'][0]['consecutive_no_progress'] == 2
    assert state['waiting_for_human'] is None  # the existing decider route remains available
    assert calls == ['report']
    assert event['qualified_ending']['status'] == 'recorded'
    result = read_json(root / 'outputs/completion/qualified-delivery.json')
    assert len(result['obligations']) == 2 and all(r['state'] == 'blocked' for r in result['obligations'])
    assert len(result['limitation_candidates'][0]['history']) == 2
    assert result['execution_authorized'] is False and result['parent_task_accepted'] is False
    assert state['events'] == (6 if ending == 'failed_correction' else 8)
    assert review.gate_errors(root, 'bulk') and review.gate_errors(root, 'delivery')
