"""Actual typed files/Graph/Host/portfolio/plan controls; no study worker.

Model results use the existing explicit supplied transport stand-in. Ordinary
specification validation and the final scientific plan are real. Runtime
metadata is inert in the fixture and no process/socket/native/provider starts.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import pytest

from ravel.workflow import research_blueprint as blueprint, research_cycle as cycle
from ravel.workflow import research_followup as follow, agent_host, execution, science
from ravel.workflow.state_io import read_json
from test_research_followup import setup, ideas
from test_research_cycle import contract, experiment, hypotheses, write


@pytest.fixture(autouse=True)
def inert_runtime(monkeypatch):
    monkeypatch.setattr(execution, 'runtime_context', lambda: {
        'explicit_inert_source_control': True,
        'environment_sha256': execution.digest(execution.runtime_environment())})
    def refuse(*a, **k):
        raise AssertionError('no scientific worker, model transport or metadata child admitted')
    monkeypatch.setattr(subprocess, 'Popen', refuse)


def case(base, monkeypatch, *, concrete_baseline=False):
    if concrete_baseline:
        root = base / 'cycle'
        cycle.create(root, contract(base), base_dir=base, evaluation_harness=True)
        rows = [hypotheses()[0]]
        cycle.propose(root, rows, origin={'kind': 'supplied_source', 'pin': write(base / 'concrete-hypothesis.json', rows),
            'description': 'One explicit high-value supplied hypothesis; no speculative generation.'})
        context = blueprint.prepare_context(root, root / 'baseline-context')
        parent = None
    else:
        root, contexts = setup(base)
        binding, _ = ideas(base, root, contexts, monkeypatch)
        context = follow.prepare_design_context(root, 'failed-parent', binding, base / 'designer')
        parent = 'failed-parent'
    e = experiment(base, 'template', grouped=False, parent=parent, premise_ids=['pairing'])
    spec = read_json(e['study']['path']); folder = Path(e['study']['path']).parent
    request = {'schema_version': 1, 'context': context, 'study_template': e['study'],
        'files': [{'id': identity, 'path': 'inputs/' + filename, 'format': form, 'source': cycle._pin(folder / filename)}
                  for identity, filename, form in [('contract', 'contract.json', 'json'), ('records', 'records.jsonl', 'jsonl')]],
        'bindings': [{'document': 'study', 'pointer': '/task/' + identity, 'file': identity} for identity in ('contract', 'records')],
        'variables': [{'id': identity, 'file': 'records', 'pointer': '/' + str(i) + '/group_id',
            'schema': {'type': 'string', 'enum': ['a', 'b', 'shared']},
            'meaning': 'Explicit supplied grouping of record ' + str(i) + '; native event identity remains unqualified.',
            'premise_ids': ['pairing']} for i, identity in enumerate(['first-group', 'second-group'])],
        'experiment_template': {k: deepcopy(e[k]) for k in blueprint.EXPERIMENT_FIELDS}}
    request_pin = write(base / 'blueprint.json', request)
    predictions = {'independent': 'independent', 'grouped': 'shared', 'unknown': None,
                   'new-citation_led': 'shared', 'new-speculative': 'independent'}
    if concrete_baseline: predictions = {'independent': 'independent'}
    choice = {'kind': 'research_blueprint_choice', 'blueprint_sha256': request_pin['sha256'],
        'context_sha256': context['sha256'], 'reason': 'Measure explicit grouping and retained independent supplied controls.',
        'variants': [{'id': 'paired', 'change': 'Use one explicitly shared supplied group.',
            'assignments': {'first-group': 'shared', 'second-group': 'shared'}, 'predictions': deepcopy(predictions)},
            {'id': 'repeat', 'change': 'Retain separate supplied groups.',
            'assignments': {'first-group': 'a', 'second-group': 'b'}, 'predictions': deepcopy(predictions)}]}
    choice_pin = write(base / 'choice.json', choice)
    return root, request_pin, choice_pin, request, choice


def graph_spec(root, request_pin, choice_pin, request):
    pins = [request_pin, choice_pin, *blueprint.inputs(request, base_dir=Path(request_pin['path']).parent)]
    unique = {p['path']: p for p in pins}
    inputs = [{'id': 'basis-' + str(i), **{k: p[k] for k in ('path', 'sha256')}} for i, p in enumerate(unique.values())]
    ids = {p['path']: p['id'] for p in inputs}
    return {'schema_version': 1, 'graph_id': 'materialize-actual', 'budget': {'max_nodes': 1, 'max_calls': 1,
        'max_output_tokens': 0, 'max_wall_seconds': 30, 'max_reworks': 0}, 'nodes': [{'id': 'compile', 'kind': 'tool',
        'role': 'designer', 'depends_on': [], 'inputs': inputs, 'packet': None, 'action': 'research-blueprint',
        'max_attempts': 1, 'parameters': {'request_input': ids[request_pin['path']], 'choice_input': ids[choice_pin['path']],
            'output_dir': str(root / 'materialized')}}]}


def compile_case(base, monkeypatch, *, generated_choice=False):
    root, req, choice, request, selected = case(base, monkeypatch)
    if generated_choice:
        host = agent_host.AgentHost(endpoint='http://127.0.0.1:9/v1/responses')
        def response(data, parameters, message, control):
            text = json.dumps(json.loads(data)['input'])
            assert 'Design a fresh discriminating study' in text
            assert 'new-citation_led' in text and 'new-speculative' in text
            return host._result(selected, parameters, message, response_id='inert-designer',
                observed_model='fixture-only', usage={'input_tokens': 10, 'output_tokens': 10})
        monkeypatch.setattr(host, '_responses', response)
        spec = blueprint.choice_spec(req, base_dir=base, graph_id='actual-designer', model='fixture-only',
            reasoning_effort='low', max_output_tokens=128, max_wall_seconds=30)
        model_graph = base / 'designer-model-graph'
        assert cycle.execute_graph(root, model_graph, spec, host)['complete']
        prepared = blueprint.prepare_choice(root, model_graph, node_id='choose', request_pin=req,
            base_dir=base, output_dir=root / 'actual-designer-choice')
        choice = prepared['choice']
        assert read_json(prepared['provenance']['path'])['origin']['role'] == 'designer'
    graph = base / 'materialize-graph'
    assert cycle.execute_graph(root, graph, graph_spec(root, req, choice, request), agent_host.AgentHost())['complete']
    return root, graph, cycle._graph_result(graph, 'compile')['value']['value'], request


def test_generated_hypotheses_to_actual_typed_files_portfolio_selection_and_real_ordinary_plan(tmp_path, monkeypatch):
    root, graph, result, request = compile_case(tmp_path, monkeypatch, generated_choice=True)
    portfolio = read_json(result['portfolio']['path'])
    paired, repeated = portfolio['experiments']
    first = read_json(paired['study']['path']); second = read_json(repeated['study']['path'])
    original = read_json(request['study_template']['path'])
    for key in original:
        if key not in {'task', 'assumptions'}:
            assert first[key] == second[key] == original[key]
    assert first['assumptions'][:len(original['assumptions'])] == original['assumptions']
    paired_rows = [json.loads(row) for row in Path(first['task']['records']).read_text().splitlines()]
    separate_rows = [json.loads(row) for row in Path(second['task']['records']).read_text().splitlines()]
    assert [r['group_id'] for r in paired_rows] == ['shared', 'shared']
    assert [r['group_id'] for r in separate_rows] == ['a', 'b']
    for old, new in zip(separate_rows, paired_rows):
        assert {k: v for k, v in old.items() if k != 'group_id'} == {k: v for k, v in new.items() if k != 'group_id'}
    assert not result['planning_approval_execution_acceptance_authorized']
    assert len(cycle._load(root)[1]['experiments']) == 1
    admit = blueprint.admission_spec(root, graph, node_id='compile', graph_id='normal-admission', max_wall_seconds=30)
    admission_graph = tmp_path / 'admission-graph'
    assert cycle.execute_graph(root, admission_graph, admit, agent_host.AgentHost())['complete']
    follow.adopt_portfolio(root, admission_graph, node_id='admit', context_pin=result['context'])
    state = cycle._load(root)[1]
    assert len(state['graphs']) == 5 and cycle._usage(state)['calls'] == 5
    assert cycle._usage(state)['output_tokens'] == 384
    assert len(state['experiments']) == 3 and state['experiments'][0]['observation']['execution_status'] == 'failed'
    assert all(e['adjudication'] is None for e in state['experiments'])
    assert cycle.select(root)['selected'] == 'paired'
    # No plan sentinel: actual source/input snapshot, ordinary CI1 and prepared
    # runtime are produced by the existing API with only inert runtime metadata.
    rd = tmp_path / 'ordinary-plan'
    cycle.prepare_experiment(root, 'paired', rd)
    verify = science.verify_plan(rd, approved=False)
    assert verify['schema_version'] == 2
    assert science.PLAN and (rd / science.PLAN).is_file()
    assert not (rd / science.APPROVAL).exists() and not (rd / 'execution_attempt.json').exists()
    assert not list((rd / 'logs').glob('science-attempts/*.json'))
    assert not list((rd / 'outputs').rglob('result.json'))
    assert cycle._load(root)[1]['experiments'][1]['plan'] is not None


@pytest.mark.parametrize('change', ['extra-assignment', 'missing-assignment', 'wrong-type', 'undeclared-value'])
def test_invalid_choices_stop_before_creating_any_input_files(tmp_path, monkeypatch, change):
    root, req, choice_pin, request, choice = case(tmp_path, monkeypatch)
    assignments = choice['variants'][1]['assignments']
    if change == 'extra-assignment': assignments['resource-cap'] = 86400
    elif change == 'missing-assignment': assignments.pop('second-group')
    elif change == 'wrong-type': assignments['second-group'] = 1
    else: assignments['second-group'] = 'not-declared'
    choice_pin = write(Path(choice_pin['path']), choice)
    observed = cycle.execute_graph(root, tmp_path / 'invalid-graph', graph_spec(root, req, choice_pin, request), agent_host.AgentHost())
    assert not observed['complete'] and not (root / 'materialized').exists()
    assert len(cycle._load(root)[1]['experiments']) == 1


@pytest.mark.parametrize('change', ['missing-input', 'overlap', 'reserved-id', 'policy-binding', 'unicode-index'])
def test_unbounded_or_misrepresented_blueprints_refuse_input_admission(tmp_path, monkeypatch, change):
    root, req, choice, request, selected = case(tmp_path, monkeypatch)
    if change == 'missing-input': request['files'].pop()
    elif change == 'overlap': request['variables'][1]['pointer'] = '/0/group_id'
    elif change == 'reserved-id': request['files'][0]['id'] = 'study'
    elif change == 'policy-binding': request['bindings'][0]['pointer'] = '/source'
    else: request['variables'][1]['pointer'] = '/١/group_id'
    with pytest.raises(ValueError): blueprint.inputs(request, base_dir=tmp_path)
    assert not (root / 'materialized').exists()


def test_materialized_file_drift_refuses_normal_admission_without_reconstruction(tmp_path, monkeypatch):
    root, graph, result, request = compile_case(tmp_path, monkeypatch)
    path = next(Path(p['path']) for p in result['output_pins'] if p['path'].endswith('records.jsonl'))
    path.write_text(path.read_text().replace('shared', 'changed'))
    with pytest.raises(ValueError):
        blueprint.admission_spec(root, graph, node_id='compile', graph_id='normal-admission', max_wall_seconds=30)
    assert len(cycle._load(root)[1]['experiments']) == 1


def test_cross_cycle_destination_and_repeat_materialization_refuse(tmp_path, monkeypatch):
    root, req, choice, request, selected = case(tmp_path, monkeypatch)
    presented = [{'path': p['path'], 'sha256': p['sha256']} for p in [req, choice, *blueprint.inputs(request, base_dir=tmp_path)]]
    with pytest.raises(ValueError): blueprint.materialize(req, choice, base_dir=tmp_path, output_dir=tmp_path / 'outside-cycle', presented_pins=presented)
    graph = tmp_path / 'materialize-graph'
    assert cycle.execute_graph(root, graph, graph_spec(root, req, choice, request), agent_host.AgentHost())['complete']
    with pytest.raises(ValueError): blueprint.materialize(req, choice, base_dir=tmp_path, output_dir=root / 'materialized', presented_pins=presented)


def test_source_aba_between_input_admission_and_write_refuses_even_restored_bytes(tmp_path, monkeypatch):
    root, req, choice, request, selected = case(tmp_path, monkeypatch)
    present = [req, choice, *blueprint.inputs(request, base_dir=tmp_path)]
    records = Path(request['files'][1]['source']['path']); raw = records.read_bytes()
    original = blueprint._fresh_snapshots; called = []
    def drift(snapshots, base):
        called.append(1)
        if len(called) == 2:
            records.write_bytes(raw.replace(b'"a"', b'"z"'))
            records.write_bytes(raw)
        return original(snapshots, base)
    monkeypatch.setattr(blueprint, '_fresh_snapshots', drift)
    with pytest.raises(ValueError):
        blueprint.materialize(req, choice, base_dir=tmp_path, output_dir=root / 'materialized', presented_pins=present)
    assert len(called) == 2 and not (root / 'materialized').exists()


def test_concrete_baseline_and_screen_need_no_speculative_or_provider_turn(tmp_path, monkeypatch):
    root, req, choice, request, selected = case(tmp_path, monkeypatch, concrete_baseline=True)
    context = read_json(request['context']['path'])
    assert context['speculative_ideation_required'] is False
    assert context['feedback_pin'] is None and context['role_content'] == []
    assert len(context['hypotheses']) == 1 and context['hypotheses'][0]['stream'] == 'citation_led'
    assert not cycle._load(root)[1]['graphs']
    graph = tmp_path / 'source-materialize-graph'
    assert cycle.execute_graph(root, graph, graph_spec(root, req, choice, request), agent_host.AgentHost())['complete']
    result = cycle._graph_result(graph, 'compile')['value']['value']
    admission_graph = tmp_path / 'baseline-admission-graph'
    admission = blueprint.admission_spec(root, graph, node_id='compile', graph_id='baseline-admit', max_wall_seconds=30)
    assert cycle.execute_graph(root, admission_graph, admission, agent_host.AgentHost())['complete']
    blueprint.adopt_portfolio(root, admission_graph, node_id='admit', context_pin=result['context'])
    state = cycle._load(root)[1]
    assert len(state['experiments']) == 2 and all(e['parent'] is None for e in state['experiments'])
    assert len(state['graphs']) == 2 and cycle._usage(state)['output_tokens'] == 0
    assert not state['revisions'] and all(e['adjudication'] is None for e in state['experiments'])
    assert cycle.select(root)['selected'] == 'paired'
    cycle.prepare_experiment(root, 'paired', tmp_path / 'ordinary-baseline-plan')
    assert not (tmp_path / 'ordinary-baseline-plan' / science.APPROVAL).exists()


def test_concrete_context_reopens_after_actual_premise_change(tmp_path, monkeypatch):
    root, req, choice, request, selected = case(tmp_path, monkeypatch, concrete_baseline=True)
    cycle.revise_premise(root, 'pairing', 'Changed explicit original source grouping', basis=[], reason='source drift control')
    with pytest.raises(ValueError):
        blueprint.inputs(request, base_dir=tmp_path)
    assert not (root / 'materialized').exists()


def test_aggregate_competing_output_cap_refuses_before_first_variant_write(tmp_path, monkeypatch):
    root, req, choice_pin, request, selected = case(tmp_path, monkeypatch, concrete_baseline=True)
    path = Path(request['files'][1]['source']['path'])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['explicit_control_annotation'] = 'x' * 65536
    path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
    request['files'][1]['source'] = cycle._pin(path)
    req = write(Path(req['path']), request)
    selected['blueprint_sha256'] = req['sha256']
    selected['variants'] = [{**deepcopy(selected['variants'][0]), 'id': 'candidate-' + str(i)} for i in range(8)]
    choice_pin = write(Path(choice_pin['path']), selected)
    # Small declared-policy stand-in isolates aggregate amplification without
    # running a large data benchmark or changing the product's actual ceiling.
    monkeypatch.setattr(blueprint, 'MAX_TOTAL_BYTES', 256 * 1024)
    presented = [req, choice_pin, *blueprint.inputs(request, base_dir=tmp_path)]
    with pytest.raises(ValueError, match='whole competing output population'):
        blueprint.materialize(req, choice_pin, base_dir=tmp_path, output_dir=root / 'materialized', presented_pins=presented)
    assert not (root / 'materialized').exists()
