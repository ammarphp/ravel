"""Synthetic completion controls: no native tools or model services."""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import task_completion as tc, route_prompt, science, scoped_spec
from ravel.workflow.state_io import read_json
from test_task_completion import write, request, review_run


def parent(tmp_path):
    prompt = 'Summarize the supplied quantities over the complete requested domain.'
    c = route_prompt.route(prompt)
    req = tc.initial_requirements(prompt)
    req['assignments'] = [{'id': 'A1', 'purpose': 'Cover the requested quantities.',
                          'coverage': [{'obligation_id': 'original-request', 'criteria': {'request': prompt}}]}]
    c['task_requirements'] = req
    return c, write(tmp_path / 'parent/inputs/task_contract.json', c)


def outcome(tmp_path, cp, name, kind='science', state='partial'):
    rd = tmp_path / name
    spec_path = {'science': science.SPEC, 'scoped': 'inputs/scoped.json',
                 'route-a': 'inputs/task_contract.json', 'research': 'inputs/task_contract.json',
                 'calculation': 'inputs/task_contract.json'}[kind]
    write(rd / spec_path, {'goal_binding': {'contract': cp, 'assignment_id': 'A1'}})
    criteria = read_json(cp['path'])['task_requirements']['assignments'][0]['coverage'][0]['criteria']
    return {'assignment_id': 'A1', 'rundir': str(rd), 'claim_scope': 'diagnostic',
            'coverage': [{'obligation_id': 'original-request', 'criteria': criteria,
                          'state': state, 'evidence': [], 'explanation': 'Retained scoped contribution.'}]}


def test_multiple_outcomes_do_not_erase_unresolved_coverage(tmp_path):
    _, cp = parent(tmp_path)
    result = tc.evaluate(request(tmp_path, cp, [outcome(tmp_path, cp, 'a'), outcome(tmp_path, cp, 'b')]), base_dir=tmp_path)
    assert result['unmet_obligation_ids'] == ['original-request']
    assert len(result['obligation_census'][0]['contributions']) == 2


@pytest.mark.parametrize('kind', ['scoped', 'route-a', 'research', 'calculation'])
def test_non_science_child_binding_is_checked(tmp_path, kind):
    _, cp = parent(tmp_path)
    out = outcome(tmp_path, cp, 'child', kind)
    assert tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)['unmet_obligation_ids']
    path = Path(out['rundir']) / ('inputs/scoped.json' if kind == 'scoped' else 'inputs/task_contract.json')
    write(path, {'goal_binding': {'contract': cp, 'assignment_id': 'other'}})
    with pytest.raises(ValueError, match='parent assignment'):
        tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)


def test_registration_is_idempotent_and_composition_rechecks_review(tmp_path, monkeypatch):
    _, cp = parent(tmp_path)
    out = outcome(tmp_path, cp, 'child', state='satisfied')
    rd = Path(out['rundir'])
    ev = write(rd / 'inputs/evidence.json', {'quantity': 2})
    out['coverage'][0]['evidence'] = [ev]
    review_run(rd, [cp['path'], str(rd / science.SPEC), ev['path']], monkeypatch)
    write(rd / 'outputs/completion_outcome.json', out)
    binding = {'contract': cp, 'assignment_id': 'A1'}
    tc.register_child(rd, binding, run_kind='science')
    tc.register_child(rd, binding, run_kind='science')
    root = Path(cp['path']).parent.parent
    result = tc.compose(root)
    assert result['uncovered'] == []
    assert result['outcomes'][0]['status'] == 'accepted'
    assert result['coverage'] == {'original-request': ['O1']}
    assert len((root / 'inputs/children.jsonl').read_text().splitlines()) == 1
    monkeypatch.setattr(__import__('ravel.workflow.physics_review', fromlist=['gate_errors']), 'gate_errors', lambda *a, **k: ['hold'])
    assert tc.compose(root, write=False)['uncovered'] == ['original-request']


def test_composition_imports_existing_collection_and_research_denominators(tmp_path, monkeypatch):
    from ravel.workflow import resonance_study, research_cycle
    _, cp = parent(tmp_path); root = Path(cp['path']).parent.parent
    out = outcome(tmp_path, cp, 'child')
    recipe = write(root / 'inputs/recipe.json', {'parent_contract': cp})
    head = write(tmp_path / 'campaign/head.json', {'revision': 1})
    calls = []
    def collect(request, runs, output):
        calls.append(output)
        return {'stages': [{'rundir': out['rundir'], 'state': 'unreviewed_or_held'}]}
    monkeypatch.setattr(resonance_study, 'collect', collect)
    monkeypatch.setattr(research_cycle, 'status', lambda root: {'experiments': [{'id': 'E1'}]})
    monkeypatch.setattr(research_cycle, '_load', lambda root: (root, {'experiments': [{'rundir': out['rundir']}]}))
    write(root / 'inputs/completion_sources.json', {'schema_version': 1,
        'resonance': {'request': recipe, 'runs': {'S1': out['rundir']}}, 'research_cycles': [head]})
    result = tc.compose(root, write=False)
    assert calls and all(value is None for value in calls)
    assert len(result['outcomes']) == 1 and result['outcomes'][0]['status'] == 'pending'
    assert result['uncovered'] == ['original-request']


def test_existing_collector_has_a_read_only_completion_projection(tmp_path):
    from test_resonance_study import fixture
    from ravel.workflow import resonance_study
    path, _ = fixture(tmp_path / 'inputs', two_searches=True)
    before = sorted(tmp_path.rglob('*'))
    view = resonance_study.collect(path, {}, None)
    assert len(view['stages']) == 4 and all(row['state'] == 'not_executed' for row in view['stages'])
    assert not view['parent_task_accepted'] and sorted(tmp_path.rglob('*')) == before


def test_choice_census_population_cannot_grow_after_observation(tmp_path):
    inputs = tc._Inputs(tmp_path)
    try:
        inputs.population(tmp_path / 'inputs', '*.json')
        write(tmp_path / 'inputs/late-choice.json', {'choice': 'late'})
        with pytest.raises(ValueError, match='population changed'): inputs.finish()
    finally: inputs.close()


def test_scoped_goal_binding_schema_and_child_checkin_projection(tmp_path):
    _, cp = parent(tmp_path)
    from ravel.workflow.completion_children import checkin_projection
    binding = {'contract': cp, 'assignment_id': 'A1'}
    assert 'goal_binding' in scoped_spec.SCHEMA['properties']
    assert checkin_projection(binding, tmp_path)['parent_obligations'][0]['obligation_id'] == 'original-request'
    spec = {'mode': 'synthetic', 'source': 'Supplied quantities', 'task': {}, 'assumptions': ['Supplied inputs'],
            'max_seconds': 10, 'goal_binding': binding}
    assert science.make_checkin(spec, '0' * 64, base=tmp_path)['sections']['i']['parent_obligations']


def test_general_completion_epoch_preserves_legacy_and_gates_new_parents(tmp_path):
    from ravel.workflow.completion_lifecycle import required
    c, cp = parent(tmp_path)
    assert not required(c)
    c['task_requirements']['completion_epoch'] = 1
    assert required(c)
    assert tc.validate_requirements(c)


def test_trap_pass_without_current_pin_is_refused(tmp_path):
    from ravel.validation.validate_run_state import inv_trap_obligations
    c, _ = parent(tmp_path)
    c['model'] = {'name': 'synthetic', 'assumptions': []}
    # The actual trap trigger is isolated from unrelated contract heuristics.
    from unittest.mock import patch
    facts = {'generation_hits': ['stage'], 'result_pack_paths': {}, 'trap_sweep_path': 'inputs/trap_sweep.json',
             'trap_sweep_doc': {'obligations': [{'trap': 'T1', 'status': 'PASS'}]}}
    with patch('ravel.validation.validate_run_state.traps_hit_ids', return_value=['T1']):
        assert inv_trap_obligations(str(tmp_path), c, facts, False, False)[0] == 'FAIL'
        ev = write(tmp_path / 'inputs/check.json', {'status': 'PASS'})
        facts['trap_sweep_doc']['obligations'][0]['artifact'] = ev
        assert inv_trap_obligations(str(tmp_path), c, facts, False, False)[0] == 'PASS'
        Path(ev['path']).write_text('{}')
        assert inv_trap_obligations(str(tmp_path), c, facts, False, False)[0] == 'FAIL'


def test_aggregate_ceiling_reserves_children_and_refuses_overspend(tmp_path):
    from ravel.workflow.completion_budget import reserve
    root = tmp_path / 'parent'; root.mkdir()
    limits = {'max_seconds': 20, 'max_events': 10, 'max_children': 2}
    reserve(root, 'first', {'max_seconds': 15, 'max_events': 4}, limits)
    with pytest.raises(ValueError, match='aggregate'):
        reserve(root, 'second', {'max_seconds': 6, 'max_events': 4}, limits)
    assert len(read_json(root / 'inputs/delegation_reservations.json')['children']) == 1


def test_accepted_boundary_retains_partial_result_and_requires_deviation(tmp_path, monkeypatch):
    _, cp = parent(tmp_path)
    out = outcome(tmp_path, cp, 'child', state='blocked'); rd = Path(out['rundir'])
    deviation = write(rd / 'DEVIATIONS.md', {'change': 'Supplied population lacks the requested interval.'})
    boundary = write(rd / 'inputs/boundary.json', {'kind': 'held-node', 'obligation_id': 'original-request',
                     'claim_scope': 'diagnostic', 'reason': 'Required supplied input unavailable.', 'deviation': deviation})
    out['coverage'][0].update(held_node=boundary, evidence=[boundary])
    review_run(rd, [cp['path'], str(rd / science.SPEC), boundary['path'], deviation['path']], monkeypatch)
    result = tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)
    assert result['ready_for_parent_review']
    assert result['obligation_census'][0]['contributions'][0]['state'] == 'blocked'
    value = read_json(boundary['path']); value['deviation'] = None; write(Path(boundary['path']), value)
    with pytest.raises(ValueError): tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)


def test_boundary_cannot_substitute_an_unlocated_deviation(tmp_path, monkeypatch):
    _, cp = parent(tmp_path)
    out = outcome(tmp_path, cp, 'child', state='blocked'); rd = Path(out['rundir'])
    deviation = write(rd / 'inputs/other.json', {'change': 'Missing supplied input.'})
    boundary = write(rd / 'inputs/boundary.json', {'kind': 'held-node', 'obligation_id': 'original-request',
        'claim_scope': 'diagnostic', 'reason': 'Required input absent.', 'deviation': deviation})
    out['coverage'][0].update(held_node=boundary, evidence=[boundary])
    review_run(rd, [cp['path'], str(rd / science.SPEC), boundary['path'], deviation['path']], monkeypatch)
    with pytest.raises(ValueError, match='DEVIATIONS.md'):
        tc.evaluate(request(tmp_path, cp, [out]), base_dir=tmp_path)
