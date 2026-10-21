"""MODE row: supplied comparisons enter the ordinary approved science route."""
import pytest

from ravel.physics import research_comparison as comparison
from ravel.workflow import production_executor, role_registry, science
from ravel.workflow import research_controller as bridge, research_cycle as cycle
from ravel.workflow.state_io import read_json
from p11_fakes import FakeRunStore, FakeStep, installed_step
from method_decision_fixture import admit_method
from test_research_cycle import contract, specification, write
from test_research_stats import comparison_task


def setup(tmp_path):
    root = tmp_path / 'campaign'
    cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    template = specification(tmp_path, 'comparison-source', False)
    source = read_json(template['path'])
    request = comparison_task(tmp_path / 'comparison-source', left=(2., 2.), right=(3., 3.))
    source.update(mode='research-comparison', max_seconds=10, max_attempts=1,
                  source='Explicit supplied deterministic scalar comparison control.',
                  task={'schema_version': 1, 'request': write(tmp_path / 'comparison-source/request.json', request)})
    study = write(tmp_path / 'comparison-source/study.json', source)
    child = tmp_path / 'ordinary-comparison'
    experiment = {'id': 'comparison', 'study': study, 'rundir': str(child),
                  'cost': {'wall_seconds': 10}}
    store = FakeRunStore('comparison', root=tmp_path.parent / (tmp_path.name + '-store'))
    # The loop budget the research step's approval carries; the child is admitted against it.
    from ravel.controller.routes.research import loop_budget
    definition = cycle._load(root)[1]['contract']
    budget = loop_budget.declare({'max_decisions': 3, 'campaign': {'max_experiments': definition['max_experiments'],
                                                                   'budget': definition['budget']}}, [], tier='full')
    return root, child, experiment, store, {'run_dir': str(tmp_path), 'research_loop_budget': budget}, source


def approve(child, study):
    science.plan(child, study['path'])
    admit_method(child)
    assert science.approve(child, 'Run this bounded supplied arithmetic control.', scripted=True) == 0
    return science.verify_plan(child, approved=True)


def test_MODE_research_comparison_approved_typed_child_executes_exact_math_pending_review(tmp_path):
    root, child, experiment, store, context, source = setup(tmp_path)
    assert science.adapter(source) is comparison
    assert production_executor.role_for({'operation': 'research-comparison'}) == 'analysis-author'
    assert role_registry.load('analysis-author')['id'] == 'analysis-author'
    plan = approve(child, experiment['study'])
    peer = FakeStep()
    with installed_step(peer), bridge.bound(store, context):
        assert bridge.run_child(root, experiment) == 0
    assert len(peer.calls) == 1
    dispatched = peer.calls[0]['step']
    assert dispatched['kind'] == 'route' and dispatched['route'] == 'study'
    assert dispatched['parameters']['specification']['task'] == source['task']
    assert dispatched['parameters']['own_checkin1'] is True
    assert science.execution.load_execution(child)['stages']['science']['status'] == 'succeeded'
    output = child / plan['stages'][0]['outputs'][0]
    result = read_json(output / 'research-comparison.json')
    assert result['kind'] == 'source_bound_research_comparison'
    assert result['status'] == 'passed' and result['decision'] == 'better'
    assert result['cell_count'] == 2
    assert [cell['gain_interval'] for cell in result['cells']] == [[1., 1.], [1., 1.]]
    assert [[operand['value'] for operand in cell['operands']] for cell in result['cells']] == [[2., 3.], [2., 3.]]
    assert result['scientific_acceptance'] is False and result['physics_validated'] is False
    packet = science.packet(child)
    assert packet['execution']['status'] == 'awaiting_review'
    assert packet['lifecycle_verdict'] == 'PENDING' and packet['physics_validated'] is False
    assert store.scan('research-step-outcome')[0]['record']['outcome']['status'] == 'completed'
    admitted = [row['record'] for row in store.scan('research-loop-reservation')]
    assert [(row['kind'], row['key']) for row in admitted] == [('child', 'research-child-comparison')]
    assert admitted[0]['projection']['tier'] in ('lean', 'standard', 'full')


@pytest.mark.parametrize('damage', ['unapproved', 'approved_input_changed', 'approved_task_changed'])
def test_MODE_research_comparison_refuses_unauthorized_or_changed_child_before_worker(tmp_path, damage):
    root, child, experiment, store, context, source = setup(tmp_path)
    if damage == 'unapproved':
        science.plan(child, experiment['study']['path'])
        admit_method(child)
    else:
        approve(child, experiment['study'])
        if damage == 'approved_input_changed':
            write(tmp_path / 'comparison-source/left.json', {'values': [20., 20.], 'quality': True, 'intervals': [[19., 21.], [19., 21.]]})
        else:
            changed = read_json(child / science.SPEC)
            changed['task']['schema_version'] = 2
            write(child / science.SPEC, changed)
    peer = FakeStep()
    refusal = FileNotFoundError if damage == 'unapproved' else ValueError
    with installed_step(peer), bridge.bound(store, context), pytest.raises(refusal):
        bridge.run_child(root, experiment)
    assert not (child / 'execution_attempt.json').exists()
    assert science.execution.load_execution(child)['stages'].get('science', {}).get('status') != 'succeeded'
    assert store.scan('research-step-outcome') == []


def test_MODE_research_comparison_vocabulary_without_typed_request_is_refused(tmp_path):
    root, child, experiment, store, context, source = setup(tmp_path)
    source['task'] = {'schema_version': 1}
    experiment['study'] = write(tmp_path / 'comparison-source/study.json', source)
    with pytest.raises(ValueError):
        science.plan(child, experiment['study']['path'])
    peer = FakeStep()
    with installed_step(peer), bridge.bound(store, context), pytest.raises(ValueError):
        bridge.run_child(root, experiment)
    assert not (child / 'execution_attempt.json').exists()
    assert store.scan('research-step-outcome') == []
