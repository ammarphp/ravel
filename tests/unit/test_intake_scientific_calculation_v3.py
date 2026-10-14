"""Unexecuted R5 source controls; no CAS/native/model or real approval inference.

The source-adapted fixture discloses its inert upstream converter, compute receipt
and reviewer seams. Public typed conversion and exact child/parent completion,
review custody and ordinary status/validation consumers run without return mocks.
Root owns prospective execution and final CI3/autonomy composition qualification.
"""
from pathlib import Path
import json
import pytest
from ravel import cli
from ravel.workflow import calculation_completion as calculation, intake, task_completion as tc, current_state, science
from ravel.workflow.state_io import read_json
from ravel.validation import validate_run_state as validation
from intake_scientific_completion_fixture import complete_parent, pin, write


PROMPT = 'Compute the partial width from the supplied model and inputs in GeV, retaining the complete source and limitations.'


def parent(base, prompt=PROMPT):
    root = base / 'parent'
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(root)]) == 0
    return root, read_json(root / 'inputs/task_contract.json'), pin(root / 'inputs/task_contract.json')


@pytest.mark.parametrize('prompt,literal', [('Compute 2+2', True), (PROMPT, False),
    ('Calculate the supplied symbolic amplitude with all declared complex components and units.', False),
    ('Compute 2+2 and derive the physical lifetime in seconds.', False)])
def test_handoff_selects_actual_entire_original_operation(tmp_path, prompt, literal):
    root, contract, cp = parent(tmp_path, prompt)
    route = calculation.completion_route(cp, base_dir=root)
    handoff = intake.execution_handoff(cp, base_dir=root)
    assert route['literal'] is literal and route['original_request'] == prompt
    assert handoff['child_schema_version'] == (1 if literal else 2)
    assert handoff['completion_api'] == route['completion_api']
    assert handoff['calculation_collection_api'] == route['collection_api']
    assert not route['execution_authorized'] and not handoff['parent_task_accepted']


def test_actual_symbolic_quantity_child_review_parent_review_and_status_join(tmp_path, monkeypatch):
    root, contract, cp = parent(tmp_path)
    request, outcome, converted, source, result = complete_parent(root, cp, monkeypatch)
    assert converted['status'] == 'delivered' and converted['units'] == 'GeV' and converted['dimension_GeV'] == 1
    assert converted['physics_validated'] is False
    assert tc.require_final(request, base_dir=root)['parent_task_accepted']
    gate = validation.evaluate(str(root), contract, strict=True)
    write(tmp_path / 'actual-validation-gate.json', gate)
    assert gate['verdict'] == 'PASS' and gate['parent_task_accepted'], json.dumps(gate, indent=2)
    assert gate['completion_scope'] == 'original_task_completion' and not gate['physics_validated']
    assert {s['name'] for s in gate['stages'] if s['status'] == 'PASS'} == {'task_contract', 'result_pack', 'verification'}
    packet = current_state.build_packet(root)
    assert packet['lifecycle_verdict'] == 'PASS' and packet['parent_task']['completion'] is True
    assert packet['intake_handoff']['child_schema_version'] == 2
    assert 'whole-parent scientific completion' in packet['approval']['note']


def test_child_source_delivery_is_not_whole_parent_review(tmp_path, monkeypatch):
    root, contract, cp = parent(tmp_path)
    request, *_ = complete_parent(root, cp, monkeypatch, accept_parent=False)
    assert tc.evaluate(request, base_dir=root)['ready_for_parent_review']
    assert calculation.evaluate_parent(root, contract)['verdict'] == 'FAIL'
    assert current_state.build_packet(root)['parent_task']['completion'] is False


@pytest.mark.parametrize('mutation', ['source', 'units', 'child_binding', 'foreign_parent', 'completion', 'bare_result'])
def test_scientific_parent_refuses_changed_source_units_child_or_substitute(tmp_path, monkeypatch, mutation):
    root, contract, cp = parent(tmp_path)
    request, outcome, converted, source, result = complete_parent(root, cp, monkeypatch)
    if mutation == 'source':
        Path(source['path']).write_text('Different unreviewed original source.\n')
    elif mutation == 'units':
        converted['units'] = '1'; write(Path(result['path']), converted)
    elif mutation == 'child_binding':
        path = Path(outcome['rundir']) / science.SPEC
        doc = read_json(path); doc['goal_binding']['assignment_id'] = 'other-child'; write(path, doc)
    elif mutation == 'foreign_parent':
        doc = read_json(request['path']); other = write(root / 'different-parent.json', dict(contract, prompt='Compute a different quantity'))
        doc['contract'] = other; write(Path(request['path']), doc)
    elif mutation == 'completion':
        doc = read_json(request['path']); doc['outcomes'][0]['coverage'][0]['criteria'] = {'request': 'Only one easy part'}
        write(Path(request['path']), doc)
    else:
        Path(request['path']).unlink(); write(root / 'outputs/result.json', {'answer': 4, 'unit': '1', 'accepted': True})
    gate = calculation.evaluate_parent(root, contract)
    assert gate['verdict'] == 'FAIL' and not gate['parent_task_accepted']
    assert current_state.build_packet(root)['lifecycle_verdict'] == 'FAIL'


def test_nonliteral_calculation_cannot_collect_self_selected_literal_child(tmp_path):
    root, contract, cp = parent(tmp_path)
    with pytest.raises((OSError, ValueError, KeyError)):
        calculation.collect(cp, root / 'unrelated-literal-child', root / 'inputs/calculation_delivery.json', base_dir=root)
    assert calculation.evaluate_parent(root, contract)['verdict'] == 'FAIL'


def test_shared_final_input_observation_rejects_wrong_base_and_late_unit_drift(tmp_path, monkeypatch):
    root, contract, cp = parent(tmp_path)
    request, outcome, converted, source, result = complete_parent(root, cp, monkeypatch)
    observed = tc._Inputs(root)
    try:
        with pytest.raises(ValueError, match='current task input session'):
            tc.require_final(request, base_dir=tmp_path, _inputs=observed)
        assert tc.require_final(request, base_dir=root, _inputs=observed)['parent_task_accepted']
        converted['units'] = '1'; write(Path(result['path']), converted)
        with pytest.raises(ValueError): observed.finish()
    finally:
        observed.close()


@pytest.mark.parametrize('prompt', [
    'Investigate the full width calculation and develop a collider analysis method with independent validation.',
    'Calculate the supplied width and investigate a new search analysis with complete detector and background validation.',
    'Calculate the supplied width and derive a complete quantum-field-theory proof with all intermediate steps.',
])
def test_reviewed_calculation_child_does_not_replace_original_research_ci3(tmp_path, monkeypatch, prompt):
    root, contract, cp = parent(tmp_path, prompt)
    request, *_ = complete_parent(root, cp, monkeypatch)
    # A real converted finite child and accepted whole-parent CI2 do not turn
    # an open research/method request into that child calculation's short path.
    assert tc.evaluate(request, base_dir=root)['parent_task_accepted']
    with pytest.raises(ValueError, match='CHECK-IN 3'):
        tc.require_final(request, base_dir=root)


def test_forged_calculation_labels_do_not_exempt_original_research(tmp_path, monkeypatch):
    from ravel.workflow import route_prompt
    prompt = 'Investigate the complete collider background estimation and develop a new method; calculate its validation results.'
    root = tmp_path / 'parent'; root.mkdir()
    contract = route_prompt.route(prompt)
    # Keep the full original evidence and valid closed schema; only the caller
    # labels are forged. Existing prompt routing remains independent of them.
    contract['task_mode'] = 'calculation'; contract['intake']['kind'] = 'calculation'
    cp = write(root / 'inputs/task_contract.json', contract)
    request, *_ = complete_parent(root, cp, monkeypatch)
    assert tc.evaluate(request, base_dir=root)['parent_task_accepted']
    with pytest.raises(ValueError, match='CHECK-IN 3'):
        tc.require_final(request, base_dir=root)


@pytest.mark.parametrize('change', ['partial_typed_result', 'foreign_source', 'untyped_child'])
def test_calculation_short_path_requires_current_typed_source_result_and_operation(tmp_path, monkeypatch, change):
    root, _, cp = parent(tmp_path)
    request, outcome, converted, source, result = complete_parent(root, cp, monkeypatch)
    accepted = tc.evaluate(request, base_dir=root)
    observed = tc._Inputs(root)
    try:
        if change == 'partial_typed_result':
            converted['points'][0]['status'] = 'failed'; converted['points'][0]['real'] = None
            write(Path(result['path']), converted)
        elif change == 'foreign_source':
            foreign = write(root / 'foreign-source.json', {'source': 'No original review or report binding'})
            spec = read_json(Path(outcome['rundir']) / science.SPEC)
            spec['task']['source'] = foreign; write(Path(outcome['rundir']) / science.SPEC, spec)
        else:
            spec = read_json(Path(outcome['rundir']) / science.SPEC)
            spec['mode'] = 'hvt-summary'; write(Path(outcome['rundir']) / science.SPEC, spec)
        with pytest.raises(ValueError):
            tc.require_final(request, base_dir=root)
        # Independent finite-route classifier also refuses a different mode;
        # a stale accepted result cannot authorize changed current sources.
        if change == 'untyped_child':
            assert not tc._reviewed_finite_calculation(read_json(request['path']), accepted, observed)
    finally:
        observed.close()
