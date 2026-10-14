"""Ordinary CLI/Graph/plan controls with explicit inert scientific runtime.

No provider, compiler, fit, event or supplied-arithmetic worker is dispatched.
The core campaign and ordinary approval/review policies are exercised unchanged.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ravel import cli
from ravel.workflow import agent_graph, execution, research_cycle as cycle, science
from ravel.workflow.state_io import read_json
import test_research_cycle as rc


def call(capsys, command, root, **options):
    args = ['research-cycle', command, '--cycle', str(root)]
    for key, value in options.items():
        flag = '--' + key.replace('_', '-')
        if value is True:
            args.append(flag)
        elif value is not False and value is not None:
            args.extend([flag, str(value)])
    code = cli.main(args)
    text = capsys.readouterr().out
    return code, json.loads(text) if text else None


def save(base, name, value):
    return rc.write(base / name, value)['path']


def start(base, capsys):
    root = base / 'cycle'
    contract = rc.contract(base)
    contract['required_experiments'] = ['paired']
    # A CLI-created campaign binds the research protocol (test_cli_create_binds_the_research_protocol);
    # these mechanics controls use the library's synthetic controls.
    cycle.create(root, contract, base_dir=base, evaluation_harness=True)
    rows = deepcopy(rc.hypotheses()[:1])
    rows[0]['premise_ids'] = ['pairing']
    origin = rc.write(base / 'hypotheses.json', rows)
    path = save(base, 'proposal-request.json', {'hypotheses': rows,
        'origin': {'kind': 'supplied_source', 'pin': origin,
                   'description': 'Explicit engineering source hypothesis; no provider/speculative call.'}})
    assert call(capsys, 'propose', root, request=path)[0] == 0
    return root


def context_graph_request(base):
    inputs = [{"id": name, **{k: cycle._pin(base / path)[k] for k in ('path', 'sha256')}}
        for name, path in [('request', 'context-request.json'), ('api', 'math.py')]]
    spec = {'schema_version': 1, 'graph_id': 'cli-context',
        'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 0,
                   'max_wall_seconds': 30, 'max_reworks': 0},
        'nodes': [{'id': 'context', 'kind': 'tool', 'role': 'proposer', 'depends_on': [],
            'inputs': inputs, 'packet': None, 'action': 'scientific-context',
            'parameters': {'request_input': 'request'}, 'max_attempts': 1}]}
    host = rc.write(base / 'host.json', {'type': 'responses', 'api_key_env': 'RAVEL_FIXTURE_NO_CREDENTIAL'})
    return save(base, 'graph-request.json', {'graph_root': 'graph',
        'spec': rc.write(base / 'graph-spec.json', spec), 'host_config': host}), spec


def test_cli_create_binds_the_research_protocol(tmp_path, capsys):
    path = save(tmp_path, 'contract.json', rc.contract(tmp_path))
    assert call(capsys, 'create', tmp_path / 'cycle', request=path)[0] == 0
    assert (tmp_path / 'cycle/research/binding.json').is_file()
    assert cycle._load(tmp_path / 'cycle')[1]['contract']['research_protocol_required'] is True


def test_actual_cli_context_to_concrete_baseline_plan_no_compulsory_speculation(tmp_path, capsys):
    root = start(tmp_path, capsys)
    request, spec = context_graph_request(tmp_path)
    code, graph = call(capsys, 'graph', root, request=request)
    assert code == 0 and graph['complete'] and graph['usage']['calls'] == 1
    assert call(capsys, 'graph', root, request=request)[1]['usage'] == graph['usage']
    experiment = rc.experiment(tmp_path, 'paired', grouped=True, premise_ids=['pairing'])
    experiment['predictions'] = {'independent': 'independent'}
    assert call(capsys, 'design', root, request=save(tmp_path, 'design.json', experiment))[0] == 0
    selected = call(capsys, 'select', root)[1]
    assert selected['selected'] == 'paired' and not selected['execution_authorized']
    rd = tmp_path / 'run'
    assert call(capsys, 'prepare', root, experiment='paired', rundir=rd)[0] == 0
    science.verify_plan(rd, approved=False)
    state = call(capsys, 'status', root)[1]
    assert state['missing_required_experiments'] == ['paired']
    assert not state['connected_task_complete'] and not state['execution_authorized']
    _, history = cycle._load(root)
    assert len(history['hypotheses']) == 1 and history['hypotheses'][0]['stream'] == 'citation_led'
    assert len(history['resource_ledger']) == 2
    assert not (rd / science.APPROVAL).exists() and not (rd / 'execution_attempt.json').exists()
    with pytest.raises(SystemExit) as error:
        call(capsys, 'run', root, experiment='paired')
    assert error.value.code == 2
    assert not list((rd / 'outputs').rglob('result.json'))


def test_cli_premise_reopening_prevents_dispatch_after_real_plan(tmp_path, monkeypatch, capsys):
    root = start(tmp_path, capsys)
    e = rc.experiment(tmp_path, 'paired', grouped=True, premise_ids=['pairing'])
    e['predictions'] = {'independent': 'independent'}
    call(capsys, 'design', root, request=save(tmp_path, 'design.json', e))
    call(capsys, 'prepare', root, experiment='paired', rundir=tmp_path / 'run')
    revision = {'id': 'pairing', 'statement': 'The premise has changed; original comparison is historical.',
        'basis': [], 'reason': 'Engineering selective invalidation control.'}
    call(capsys, 'revise-premise', root, request=save(tmp_path, 'premise.json', revision))
    def forbidden(*args, **kwargs):
        raise AssertionError('reopened study must never reach scientific runner')
    monkeypatch.setattr(science, 'run', forbidden)
    with pytest.raises(SystemExit) as error:
        call(capsys, 'run', root, experiment='paired')
    assert error.value.code == 2
    assert not call(capsys, 'status', root)[1]['experiments'][0]['current_applicability']


def test_cli_rejects_unknown_request_and_oversized_document_before_new_history(tmp_path, capsys):
    root = start(tmp_path, capsys)
    _, before = cycle._load(root)
    bad = save(tmp_path, 'bad.json', {'hypotheses': [], 'origin': {}, 'approval': True})
    with pytest.raises(SystemExit):
        call(capsys, 'propose', root, request=bad)
    huge = tmp_path / 'huge.json'
    huge.write_bytes(b' ' * (2 * 1024 * 1024 + 1))
    with pytest.raises(SystemExit):
        call(capsys, 'propose', root, request=huge)
    assert cycle._load(root)[1]['sha256'] == before['sha256']


def test_cli_authenticated_snapshot_never_parses_unverified_path_read_text(tmp_path, monkeypatch):
    path = tmp_path / 'request.json'
    path.write_bytes(b'{"calls":1}\n')
    def unverified(*args, **kwargs):
        raise AssertionError('unverified read_text must not supply command content')
    monkeypatch.setattr(Path, 'read_text', unverified)
    assert cycle._cli_document(path) == {'calls': 1}


def test_cli_graph_budget_exhaustion_prevents_actual_tool_dispatch(tmp_path, capsys):
    contract = rc.contract(tmp_path)
    contract['budget']['calls'] = 0
    root = tmp_path / 'cycle'
    cycle.create(root, contract, base_dir=tmp_path, evaluation_harness=True)
    request, _ = context_graph_request(tmp_path)
    with pytest.raises(SystemExit):
        call(capsys, 'graph', root, request=request)
    assert not (tmp_path / 'graph').exists()
    assert not cycle._load(root)[1]['resource_ledger']


def test_cli_strict_json_duplicate_key_refuses(tmp_path):
    path = tmp_path / 'request.json'
    path.write_bytes(b'{"calls":1,"calls":2}')
    with pytest.raises(ValueError):
        cycle._cli_document(path)


def test_cli_ordinary_run_exit_is_not_converted_to_scientific_acceptance(tmp_path, monkeypatch, capsys):
    seen = []
    def terminal(root, experiment, *, resume):
        seen.append((str(root), experiment, resume))
        return 3
    monkeypatch.setattr(cycle, 'run_experiment', terminal)
    code, value = call(capsys, 'run', tmp_path / 'cycle', experiment='candidate', resume=True)
    assert code == 3 and value['ordinary_scientific_exit_code'] == 3
    assert value['scientific_acceptance_inferred'] is False and seen[0][2] is True


def test_cli_prepared_graph_requires_existing_source_join_and_forwards_exact_spec(tmp_path, monkeypatch, capsys):
    root = start(tmp_path, capsys)
    request, original = context_graph_request(tmp_path)
    def legacy(root, graph, spec, host):
        raise AssertionError('source without prepared join must not dispatch')
    monkeypatch.setattr(cycle, 'execute_graph', legacy)
    with pytest.raises(SystemExit) as error:
        call(capsys, 'graph', root, request=request, prepared=True)
    assert error.value.code == 2 and not (tmp_path / 'graph').exists()
    seen = []
    def joined(root, graph, spec, host, *, prepared=False):
        seen.append({'root': root, 'graph': graph, 'spec': spec, 'prepared': prepared})
        return {'complete': False, 'usage': {'calls': 0}}
    monkeypatch.setattr(cycle, 'execute_graph', joined)
    code, result = call(capsys, 'graph', root, request=request, prepared=True)
    assert code == 1 and result['complete'] is False
    assert seen[0]['prepared'] is True and seen[0]['spec'] == original
    assert seen[0]['graph'] == tmp_path / 'graph'
    assert not cycle._load(root)[1]['resource_ledger']


def test_cli_actual_precreated_graph_charges_once_through_joined_existing_ledger(tmp_path, capsys):
    root = start(tmp_path, capsys)
    request, spec = context_graph_request(tmp_path)
    graph_root = tmp_path / 'graph'
    agent_graph.create(graph_root, spec)
    code, result = call(capsys, 'graph', root, request=request, prepared=True)
    assert code == 0 and result['complete'] and result['usage']['calls'] == 1
    _, state = cycle._load(root)
    assert len(state['resource_ledger']) == 1 and state['resource_ledger'][0]['id'] == 'graph:' + str(graph_root)
    assert state['graphs'][0]['usage']['calls'] == 1 and state['graphs'][0]['complete']
    assert call(capsys, 'graph', root, request=request, prepared=True)[1]['usage'] == result['usage']
    assert len(cycle._load(root)[1]['resource_ledger']) == 1


def test_cli_blueprint_two_tool_admission_keeps_original_parent_denominator(tmp_path, monkeypatch, capsys):
    import test_research_blueprint as bp
    from ravel.workflow import research_blueprint, task_completion
    from test_task_completion import goal, PROMPT
    _, parent_pin = goal(tmp_path)
    binding = {'contract': parent_pin, 'assignment_id': 'summary-child'}
    original_contract, original_experiment = bp.contract, bp.experiment
    def bound_contract(base):
        c = original_contract(base); c['goal_binding'] = deepcopy(binding); return c
    def bound_experiment(base, *args, **kwargs):
        e = original_experiment(base, *args, **kwargs)
        path = Path(e['study']['path']); spec = read_json(path)
        spec['goal_binding'] = deepcopy(binding); e['study'] = bp.write(path, spec)
        return e
    monkeypatch.setattr(bp, 'contract', bound_contract)
    monkeypatch.setattr(bp, 'experiment', bound_experiment)
    root, request_pin, choice_pin, document, _ = bp.case(tmp_path, monkeypatch, concrete_baseline=True)
    graph_spec = bp.graph_spec(root, request_pin, choice_pin, document)
    host = rc.write(tmp_path / 'host.json', {'type': 'responses', 'api_key_env': 'RAVEL_FIXTURE_NO_CREDENTIAL'})
    graph_request = {'graph_root': str(tmp_path / 'materialization-graph'),
        'spec': rc.write(tmp_path / 'materialization-spec.json', graph_spec), 'host_config': host}
    assert call(capsys, 'graph', root, request=save(tmp_path, 'materialization-request.json', graph_request))[1]['complete']
    materialized = cycle._graph_result(tmp_path / 'materialization-graph', 'compile')['value']['value']
    admission_parameters = save(tmp_path, 'admission-parameters.json', {'graph_id': 'cli-admission', 'max_wall_seconds': 30})
    code, spec = call(capsys, 'blueprint-admission', root, graph=tmp_path / 'materialization-graph',
        node='compile', request=admission_parameters)
    assert code == 0
    admission_request = {'graph_root': str(tmp_path / 'admission-graph'),
        'spec': rc.write(tmp_path / 'admission-spec.json', spec), 'host_config': host}
    assert call(capsys, 'graph', root, request=save(tmp_path, 'admission-request.json', admission_request))[1]['complete']
    call(capsys, 'adopt-portfolio', root, graph=tmp_path / 'admission-graph', node='admit',
        request=save(tmp_path, 'adopt.json', {'context_pin': materialized['context']}))
    rd = tmp_path / 'plan'
    call(capsys, 'prepare', root, experiment='paired', rundir=rd)
    science.verify_plan(rd, approved=False)
    state = call(capsys, 'status', root)[1]
    assert state['parent_task']['original_request'] == PROMPT and not state['parent_task_accepted']
    assert [row['id'] for row in state['parent_task']['effective_obligations']] == ['original-request', 'atlas', 'cms', 'domain']
    assert read_json(rd / science.SPEC)['goal_binding'] == binding
    assert not (rd / science.APPROVAL).exists() and not list((rd / 'outputs').rglob('result.json'))
