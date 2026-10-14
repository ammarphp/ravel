"""Real context/Graph/Host/inputs/plan controls; no tool or provider execution."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from ravel.workflow import research_tools as tools, research_cycle as cycle
from ravel.workflow import research_blueprint as blueprint, agent_host, execution, science
from ravel.workflow.state_io import read_json
from test_research_blueprint import case
from test_research_cycle import contract, propose, write
from test_research_failure_cycle import connect


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    monkeypatch.setattr(execution, 'runtime_context', lambda: {'explicit_inert_source_control': True,
        'environment_sha256': execution.digest(execution.runtime_environment())})
    def deny(*args, **kwargs):
        raise AssertionError('no process/provider/worker admitted by these source controls')
    monkeypatch.setattr(subprocess, 'Popen', deny)


def fund_contract(monkeypatch, **ceilings):
    """Declare explicit ceilings in every fresh fixture contract; no existing cycle is extended."""
    import test_research_blueprint as fixtures
    source_contract = fixtures.contract
    def funded(base):
        value = source_contract(base)
        request = read_json(value['context_request']['path'])
        request.update(ceilings)
        value['context_request'] = write(Path(value['context_request']['path']), request)
        return value
    monkeypatch.setattr(fixtures, 'contract', funded)


@pytest.fixture(autouse=True)
def funded_source_bound(monkeypatch):
    # Tool preparation binds the real ordinary adapter and lifecycle sources as API
    # documents. Fund those complete supplied sources plus retained-backend recovery
    # APIs in the fresh fixture. The production corpus ceiling stays enforced.
    fund_contract(monkeypatch, max_source_bytes=1024*1024)


def prepared(base, monkeypatch, *, max_context_bytes=64000, backend_statements=0):
    # A fresh, explicit fixture contract funds the growing real lifecycle
    # definitions. Do not extend an existing cycle or hide any omission.
    # Other test modules import this builder, so it funds the source bound itself.
    fund_contract(monkeypatch, max_context_bytes=max_context_bytes, max_source_bytes=1024*1024)
    root, request, choice, value, selected = case(base, monkeypatch, concrete_baseline=True)
    inherited = cycle._load(root)[1]['contract'].get('goal_binding')
    if inherited is not None:
        specification = read_json(value['study_template']['path'])
        specification['goal_binding'] = deepcopy(inherited)
        value['study_template'] = write(Path(value['study_template']['path']), specification)
        request = write(Path(request['path']), value)
        selected['blueprint_sha256'] = request['sha256']
        choice = write(Path(choice['path']), selected)
    # Extra inert statements size the one supplied definition; they change no return value.
    padding = ''.join(f'    unused_{index:04d} = "explicit synthetic padding"\n' for index in range(backend_statements))
    api = write(base / 'backend-api.py', 'def measure(records):\n' + padding + '    return {"unqualified": records}\n')
    document = {'id': 'supplied-backend', 'pin': {k: api[k] for k in ('path', 'sha256')},
        'language': 'python', 'role': 'api', 'version': 'Explicit synthetic source; never imported', 'dependencies': []}
    queries = [{'id': 'actual-measure', 'symbol': 'measure', 'mode': 'definition',
        'documents': ['supplied-backend'], 'required': True}]
    bundle = tools.prepare(root, request, root / 'tool-context', api_documents=[document], queries=queries)
    return root, bundle, choice, value, selected, api


def test_supplied_backend_underfunded_context_keeps_literal_omission_and_budget(tmp_path, monkeypatch):
    # The supplied definition alone exceeds the declared context budget, so its omission
    # does not depend on how much of the budget the real lifecycle definitions leave.
    root, bundle, _, _, _, api = prepared(tmp_path, monkeypatch, max_context_bytes=16000, backend_statements=400)
    assert Path(api['path']).stat().st_size > 16000
    document = read_json(bundle['path'])
    context = read_json(document['api_context']['path'])
    resolution = next(row for row in context['api_resolution'] if row['id'] == 'actual-measure')
    assert resolution['matched_spans'] == 1 and resolution['included_spans'] == 0
    assert resolution['status'] == 'omitted' and not document['context_complete']
    assert context['request']['max_context_bytes'] == 16000
    assert any(row['document'] == 'supplied-backend' and 'budget' in row['reason']
               for row in context['omissions'])
    assert any(row['id'] == 'supplied-backend' and row['pin'] == {key:api[key] for key in ('path','sha256')}
               for row in context['request']['api_documents'])
    assert cycle._load(root)[1]['graphs'] == []


def compile_and_admit(base, monkeypatch):
    root, bundle, choice, value, selected, api = prepared(base, monkeypatch)
    graph = base / 'materialization-graph'
    spec = tools.materialization_spec(bundle, choice, base_dir=base, output_dir=root / 'compiled',
        graph_id='tool-materialization', max_wall_seconds=10)
    assert cycle.execute_graph(root, graph, spec, agent_host.AgentHost())['complete']
    result = cycle._graph_result(graph, 'compile')['value']['value']
    admission = tools.admission_spec(root, graph, node_id='compile', graph_id='tool-admission', max_wall_seconds=10)
    admission_graph = base / 'admission-graph'
    assert cycle.execute_graph(root, admission_graph, admission, agent_host.AgentHost())['complete']
    blueprint.adopt_portfolio(root, admission_graph, node_id='admit', context_pin=result['context'])
    return root, bundle, result, api


def test_real_context_materialization_admission_selection_and_unapproved_plan(tmp_path, monkeypatch):
    root, bundle, result, api = compile_and_admit(tmp_path, monkeypatch)
    b = read_json(bundle['path']); current = cycle._load(root)[1]
    api_context = read_json(b['api_context']['path'])
    assert any(row['document'] == 'supplied-backend' for row in api_context['context_entries'])
    resolution = next(row for row in api_context['api_resolution'] if row['id'] == 'actual-measure')
    assert resolution['status'] == 'complete-supplied-matches' and resolution['included_spans'] == 1
    assert api_context['request']['max_context_bytes'] == 64000
    assert b['requested_quantities'] == current['context']['requested_quantities']
    assert b['compatibility_groups'] == current['context']['compatibility_groups']
    assert len(current['experiments']) == 2 and all(e['tool_context'] == bundle for e in current['experiments'])
    assert current['resource_ledger'] and cycle._usage(current)['calls'] == 2
    assert cycle.select(root)['selected'] == 'paired'
    rd = tmp_path / 'actual-unapproved-plan'
    tools.plan(root, 'paired', rd)
    assert science.verify_plan(rd, approved=False)['schema_version'] == 2
    assert not (rd / science.APPROVAL).exists()
    assert not (rd / 'execution_attempt.json').exists()
    assert cycle._usage(cycle._load(root)[1])['native_attempts'] == 1
    assert not cycle.status(root)['parent_task_accepted']


def test_missing_api_is_visible_testable_and_not_prior_proof_veto(tmp_path, monkeypatch):
    root, req, choice, value, selected = case(tmp_path, monkeypatch, concrete_baseline=True)
    bundle = tools.prepare(root, req, root / 'unknown-api', queries=[{'id': 'unavailable', 'symbol': 'not_implemented',
        'mode': 'definition', 'documents': ['math'], 'required': True}])
    b = read_json(bundle['path']); ctx = read_json(b['api_context']['path'])
    assert not b['context_complete']
    assert any(row['id'] == 'unavailable' and row['status'] == 'not-found' for row in ctx['api_resolution'])
    graph = tmp_path / 'unknown-api-graph'
    spec = tools.materialization_spec(bundle, choice, base_dir=tmp_path, output_dir=root / 'unknown-compiled',
        graph_id='unknown-context', max_wall_seconds=10)
    assert cycle.execute_graph(root, graph, spec, agent_host.AgentHost())['complete']
    assert cycle._load(root)[1]['experiments'] == []


def test_actual_charged_designer_sees_tool_definitions_and_preserves_typed_choice(tmp_path, monkeypatch):
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    # A separate explicit resource contract, never a budget reset on a live cycle.
    # This fixture needs no extra tokens: a zero-output-token supplied Graph is
    # not a provider call; use a fresh cycle fixture with the declared ceiling.
    spec = tools.choice_spec(bundle, base_dir=tmp_path, graph_id='designer-context', model='inert-fixture',
        reasoning_effort='low', max_output_tokens=128, max_wall_seconds=10)
    state = cycle._load(root)[1]
    assert state['contract']['budget']['output_tokens'] == 0
    with pytest.raises(ValueError):
        cycle.execute_graph(root, tmp_path / 'over-budget', spec, agent_host.AgentHost())
    assert not (tmp_path / 'over-budget').exists()
    assert any(row['path'] == api['path'] for row in spec['nodes'][0]['inputs'])
    assert any(row['path'] == read_json(bundle['path'])['api_context']['path'] for row in spec['nodes'][0]['inputs'])


@pytest.mark.parametrize('with_parent', [False, True])
def test_real_designer_context_then_materializer_without_provider(tmp_path, monkeypatch, with_parent):
    import test_research_blueprint as fixtures
    original_contract = fixtures.contract
    def funded(base):
        result = original_contract(base)
        result['budget']['output_tokens'] = 1024
        if with_parent:
            from ravel.workflow import route_prompt, task_completion
            prompt = "Consider a model (say HVT) with a Z'->WW. Construct a summary plot of ATLAS+CMS searches sensitive to Z'->WW for m(Z') < 500 GeV."
            parent = route_prompt.route(prompt)
            req = task_completion.initial_requirements(prompt)
            req['assignments'] = [{'id': 'context-child', 'purpose': 'Synthetic source context; no physical acceptance.',
                'coverage': [{'obligation_id': 'original-request', 'criteria': deepcopy(req['obligations'][0]['criteria'])}]}]
            parent['task_requirements'] = req
            result['goal_binding'] = {'contract': write(base / 'parent/inputs/task_contract.json', parent),
                'assignment_id': 'context-child'}
        return result
    monkeypatch.setattr(fixtures, 'contract', funded)
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    host = agent_host.AgentHost(endpoint='http://127.0.0.1:9/v1/responses')
    seen = []
    def supplied(data, parameters, request, control):
        seen.append(json.loads(data)['input'])
        assert 'def measure(records)' in json.dumps(seen[-1])
        assert 'conditional-variance' in json.dumps(seen[-1])
        return host._result(selected, parameters, request, response_id='inert-tool-designer',
            observed_model='explicit-supplied-fixture', usage={'input_tokens': 10, 'output_tokens': 10})
    monkeypatch.setattr(host, '_responses', supplied)
    spec = tools.choice_spec(bundle, base_dir=tmp_path, graph_id='real-source-designer', model='inert-fixture',
        reasoning_effort='low', max_output_tokens=128, max_wall_seconds=10)
    graph = tmp_path / 'designer-graph'
    assert cycle.execute_graph(root, graph, spec, host)['complete']
    actual = tools.prepare_choice(root, graph, node_id='choose', bundle_pin=bundle, base_dir=tmp_path,
        output_dir=root / 'observed-choice')
    assert read_json(actual['choice']['path']) == selected and len(seen) == 1
    if with_parent:
        assert read_json(bundle['path'])['goal_binding'] == cycle._load(root)[1]['contract']['goal_binding']
        assert 'ATLAS+CMS' in json.dumps(seen[0])
        assert not cycle.status(root)['parent_task_accepted']
    materialized = tmp_path / 'designer-materialization'
    spec = tools.materialization_spec(bundle, actual['choice'], base_dir=tmp_path, output_dir=root / 'designer-compiled',
        graph_id='designer-compiler', max_wall_seconds=10)
    assert cycle.execute_graph(root, materialized, spec, agent_host.AgentHost())['complete']
    assert cycle._usage(cycle._load(root)[1])['calls'] == 2
    assert cycle._usage(cycle._load(root)[1])['output_tokens'] == 128
    assert not cycle._load(root)[1]['experiments']


@pytest.mark.parametrize('field', ['requested_quantities', 'compatibility_groups', 'goal_binding', 'scope'])
def test_forged_context_cannot_drop_parent_denominator(tmp_path, monkeypatch, field):
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    b = read_json(bundle['path'])
    b[field] = [] if field in {'requested_quantities', 'compatibility_groups'} else 'forged'
    forged = write(tmp_path / 'forged-bundle.json', b)
    with pytest.raises(ValueError): tools.input_pins(forged, tmp_path)


@pytest.mark.parametrize('field', ['source_inputs', 'api_documents', 'queries'])
def test_complete_api_population_cannot_be_trimmed(tmp_path, monkeypatch, field):
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    b = read_json(bundle['path'])
    if field == 'source_inputs': b[field] = b[field][1:]
    else:
        request = read_json(b['api_request']['path']); request[field] = []
        b['api_request'] = write(tmp_path / 'trimmed-api-request.json', request)
    forged = write(tmp_path / 'trimmed-bundle.json', b)
    with pytest.raises(ValueError): tools.check_binding(forged, tmp_path)


def test_adopted_api_drift_blocks_direct_select_and_plan_without_resetting_usage(tmp_path, monkeypatch):
    root, bundle, result, api = compile_and_admit(tmp_path, monkeypatch)
    before = cycle._usage(cycle._load(root)[1])
    Path(api['path']).write_text('def changed(records):\n    return records\n')
    with pytest.raises(ValueError): cycle.select(root)
    with pytest.raises(ValueError): tools.plan(root, 'paired', tmp_path / 'must-not-plan')
    assert cycle._usage(cycle._load(root)[1]) == before
    assert not (tmp_path / 'must-not-plan').exists()


def test_api_aba_during_compilation_refuses_without_reconstructing_success(tmp_path, monkeypatch):
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    real = blueprint.materialize
    def mutate(*args, **kwargs):
        result = real(*args, **kwargs)
        path = Path(api['path']); raw = path.read_bytes()
        path.write_bytes(raw + b'# transient supplied-API mutation\n'); path.write_bytes(raw)
        return result
    monkeypatch.setattr(blueprint, 'materialize', mutate)
    spec = tools.materialization_spec(bundle, choice, base_dir=tmp_path, output_dir=root / 'aba',
        graph_id='aba-refusal', max_wall_seconds=10)
    result = cycle.execute_graph(root, tmp_path / 'aba-graph', spec, agent_host.AgentHost())
    assert not result['complete']
    assert not (root / 'aba/tool-materialization.json').exists()
    assert not cycle._load(root)[1]['experiments']


def test_missing_graph_context_source_refuses_before_materialization(tmp_path, monkeypatch):
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    spec = tools.materialization_spec(bundle, choice, base_dir=tmp_path, output_dir=root / 'no-api',
        graph_id='missing-source', max_wall_seconds=10)
    spec['nodes'][0]['inputs'] = [row for row in spec['nodes'][0]['inputs'] if row['path'] != api['path']]
    assert not cycle.execute_graph(root, tmp_path / 'no-api-graph', spec, agent_host.AgentHost())['complete']
    assert not (root / 'no-api').exists()


def test_real_retained_failure_feedback_recovery_uses_same_journal_and_attempt_debt(tmp_path, monkeypatch):
    root = tmp_path / 'cycle'; cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True); propose(tmp_path, root)
    prior, document, feedback = connect(tmp_path, root)
    usage = cycle._usage(cycle._load(root)[1]); count = len(cycle._load(root)[1]['events'])
    pin = tools.recovery_context(root, 'failed-parent', root / 'repair-tool-context')
    recovered = read_json(pin['path'])
    assert recovered['feedback']['observation']['execution_status'] == 'failed'
    assert recovered['feedback']['failed_parent_acceptance_remains_false']
    assert 'Design a fresh discriminating study' in json.dumps(recovered['role_content'])
    assert recovered['whole_task'] == cycle._load(root)[1]['context']['requested_quantities']
    assert cycle._usage(cycle._load(root)[1]) == usage and len(cycle._load(root)[1]['events']) == count
    with pytest.raises(ValueError): tools.plan(root, 'failed-parent', tmp_path / 'old-retry')


def test_actual_failed_feedback_drives_fresh_tool_input_adoption_and_plan(tmp_path, monkeypatch):
    from test_research_failure_cycle import existing_failure
    root, request_pin, choice_pin, request, choice = case(tmp_path, monkeypatch, concrete_baseline=True)
    prior, document, feedback = existing_failure(tmp_path)
    cycle.import_failed_stage(root, 'failed-parent', document, premise_ids=['pairing'], predictions={'independent': None},
        historical_cost={'calls': 0, 'output_tokens': 0, 'wall_seconds': 30, 'native_attempts': 1})
    cycle.diagnostic_feedback(root, 'failed-parent', feedback, allow_control=True)
    old_hashes = {str(p): execution.file_hash(p) for p in prior.rglob('*') if p.is_file()}
    request['context'] = tools.recovery_context(root, 'failed-parent', root / 'actual-recovery-context')
    request_pin = write(tmp_path / 'recovery-blueprint.json', request)
    choice['blueprint_sha256'] = request_pin['sha256']; choice['context_sha256'] = request['context']['sha256']
    choice_pin = write(tmp_path / 'recovery-choice.json', choice)
    bundle = tools.prepare(root, request_pin, root / 'recovery-api-context')
    spec = tools.materialization_spec(bundle, choice_pin, base_dir=tmp_path, output_dir=root / 'recovery-compiled',
        graph_id='recovery-inputs', max_wall_seconds=10)
    graph = tmp_path / 'recovery-graph'; assert cycle.execute_graph(root, graph, spec, agent_host.AgentHost())['complete']
    result = cycle._graph_result(graph, 'compile')['value']['value']
    admission = tools.admission_spec(root, graph, node_id='compile', graph_id='recovery-admission', max_wall_seconds=10)
    admitted = tmp_path / 'recovery-admission-graph'
    assert cycle.execute_graph(root, admitted, admission, agent_host.AgentHost())['complete']
    blueprint.adopt_portfolio(root, admitted, node_id='admit', context_pin=result['context'])
    assert cycle.select(root)['selected'] == 'paired'
    tools.plan(root, 'paired', tmp_path / 'recovery-unapproved-plan')
    state = cycle._load(root)[1]
    assert state['experiments'][0]['observation']['execution_status'] == 'failed'
    assert state['experiments'][0]['adjudication'] is None
    assert all(row['old_votes_carried'] == [] for row in state['revisions'])
    assert cycle._usage(state)['native_attempts'] == 2
    assert {str(p): execution.file_hash(p) for p in prior.rglob('*') if p.is_file()} == old_hashes
    assert not (tmp_path / 'recovery-unapproved-plan' / science.APPROVAL).exists()


def test_public_cli_is_exact_fixed_delegation(tmp_path, monkeypatch, capsys):
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    args = write(tmp_path / 'cli-arguments.json', {'bundle_pin': bundle, 'choice_pin': choice,
        'base_dir': str(tmp_path), 'output_dir': str(root / 'cli-compiled'), 'graph_id': 'cli-tool', 'max_wall_seconds': 10})
    from ravel import cli
    assert cli.main(['research-tools', 'materialization-spec', '--request', args['path']]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['nodes'][0]['action'] == 'research-tools'
    assert not (root / 'cli-compiled').exists()


def test_fixed_full_workflow_reuses_real_graphs_journal_and_ordinary_cli_handoff(tmp_path, monkeypatch):
    root, req, choice, value, selected = case(tmp_path, monkeypatch, concrete_baseline=True)
    result = tools.plan_workflow(root, req, choice, root / 'fixed-workflow', tmp_path / 'fixed-unapproved-run',
        max_wall_seconds=10)
    assert result['selected'] == 'paired'
    assert science.verify_plan(result['rundir'], approved=False)['schema_version'] == 2
    assert result['next_operations']['approve'][:2] == ['ravel', 'approve']
    assert result['next_operations']['run'][:3] == ['ravel', 'research-cycle', 'run']
    assert cycle._usage(cycle._load(root)[1])['calls'] == 2
    assert not result['parent_task_accepted'] and not result['scientific_acceptance']
    assert not (Path(result['rundir']) / science.APPROVAL).exists()


def test_retired_backend_return_is_refused_not_read_as_context(tmp_path, monkeypatch):
    """The retired backend return reader refuses a supplied return; it never parses it."""
    from ravel.workflow.cosmology_backend import BackendRetired
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    raw = write(tmp_path / 'supplied-backend-return.json', {
        'chat_history': [{'name': 'researcher_response_formatter', 'content': '```markdown\nSuccessful synthetic report\n```'}],
        'final_context': {'displayed_images': [], 'n_attempts': 1, 'max_n_attempts': 1,
            'step_execution_status': 'completed', 'previous_steps_execution_summary': 'synthetic only'}})
    with pytest.raises(BackendRetired, match='dropped from RAVEL'):
        tools.backend_result_context(bundle, raw, base_dir=tmp_path, outputs={}, attempt_id='first-retained-result',
            question='Where is the actual requested variance?', next_experiment={})
    assert not cycle._load(root)[1]['context']['steps']
    assert not cycle._load(root)[1]['resource_ledger']


@pytest.mark.parametrize('operation', ['prepare', 'materialization-spec', 'workflow'])
def test_destination_parent_alias_refuses_before_creation(tmp_path, monkeypatch, operation):
    root, req, choice, value, selected = case(tmp_path, monkeypatch, concrete_baseline=True)
    bad = root / '..' / 'outside-tool-state'
    if operation == 'prepare':
        with pytest.raises(ValueError, match='parent traversal'):
            tools.prepare(root, req, bad)
    else:
        bundle = tools.prepare(root, req, root / 'valid-context')
        if operation == 'materialization-spec':
            with pytest.raises(ValueError, match='parent traversal'):
                tools.materialization_spec(bundle, choice, base_dir=tmp_path, output_dir=bad, graph_id='alias', max_wall_seconds=10)
        else:
            with pytest.raises(ValueError, match='parent traversal'):
                tools.plan_workflow(root, req, choice, bad, tmp_path / 'must-not-plan', max_wall_seconds=10)
    assert not (tmp_path / 'outside-tool-state').exists()
    assert not cycle._load(root)[1]['resource_ledger']


def test_shared_knowledge_full_domain_conflict_and_unknown_obligations_reach_designer_context(tmp_path, monkeypatch):
    from test_research_knowledge import request as knowledge_request, MAPPING
    root, req, choice, value, selected = case(tmp_path, monkeypatch, concrete_baseline=True)
    knowledge_pin = knowledge_request(tmp_path)
    cycle.bind_knowledge(root, knowledge_pin, premise_map=MAPPING, reason='Retain the entire synthetic conflict and domain.')
    value['context'] = blueprint.prepare_context(root, root / 'knowledge-design-context')
    req = write(tmp_path / 'knowledge-blueprint.json', value)
    bundle = tools.prepare(root, req, root / 'knowledge-api-context')
    facts = read_json(bundle['path'])['research_facts']
    assert {row['id'] for row in facts['premises']} == {'pairing', *MAPPING.values()}
    packet = facts['knowledge_contexts'][0]['packet']
    assert packet['contradictions'][0]['id'] == 'conflict'
    assert {row['id'] for row in packet['test_obligations']} == {'compare-flux', 'explore-rival'}
    assert all(row['check'] is None for row in packet['test_obligations'])
    assert all(row['domain'] == ['toy'] for row in packet['nodes'])
    assert next(row for row in packet['nodes'] if row['id'] == 'rival')['source_evidence'] == []
    assert knowledge_pin['path'] in {row['path'] for row in tools.input_pins(bundle, tmp_path)}
    forged = read_json(bundle['path']); forged['research_facts']['knowledge_contexts'] = []
    with pytest.raises(ValueError, match='premise/domain/convention/knowledge'):
        tools.check_binding(write(tmp_path / 'dropped-knowledge.json', forged), tmp_path)


def test_retired_backend_recovery_refuses_and_leaves_the_cycle_unchanged(tmp_path, monkeypatch):
    from ravel.workflow.cosmology_backend import BackendRetired
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    raw = write(tmp_path / 'backend-incomplete.json', {
        'chat_history': [{'name': 'researcher_response_formatter', 'content': '```markdown\nNo measurement returned.\n```'}],
        'final_context': {'displayed_images': [], 'n_attempts': 1, 'max_n_attempts': 1,
            'step_execution_status': 'completed', 'previous_steps_execution_summary': 'Supplied incomplete return'}})
    blueprint_pin = read_json(bundle['path'])['blueprint']
    with pytest.raises(BackendRetired, match='dropped from RAVEL'):
        tools.backend_recovery(root, bundle, raw, blueprint_pin, root / 'retained-result-recovery',
            base_dir=tmp_path, outputs={}, attempt_id='retained-only', question='How can the absent covariance be obtained?',
            next_experiment={})
    assert not (root / 'retained-result-recovery').exists()
    assert cycle._load(root)[1]['context']['steps'] == []


# Retained peer adverse fixture and call path; original V1 failure is immutable.
@pytest.mark.parametrize('fault', ['portfolio-drift', 'portfolio-aba', 'receipt-drift'])
def test_generated_terminal_outputs_remain_exact_at_success(tmp_path, monkeypatch, fault):
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    real_write = tools._write
    touched = []
    def final_callback(path, value):
        pin = real_write(path, value)
        if Path(path).name == 'tool-materialization.json':
            target = Path(path) if fault == 'receipt-drift' else Path(path).parent / 'tool-portfolio.json'
            raw = target.read_bytes()
            target.write_bytes(b'{"late_unbound_output":true}\n')
            if fault == 'portfolio-aba':
                target.write_bytes(raw)
            touched.append(str(target))
        return pin
    monkeypatch.setattr(tools, '_write', final_callback)
    spec = tools.materialization_spec(bundle, choice, base_dir=tmp_path, output_dir=root / 'late-compiled',
        graph_id='independent-late-output', max_wall_seconds=10)
    outcome = cycle.execute_graph(root, tmp_path / 'late-graph', spec, agent_host.AgentHost())
    assert touched, 'the actual generated-output callback must have run'
    assert not outcome['complete'], 'late generated-output drift/ABA must not become a completed tool return'
    assert not cycle._load(root)[1]['experiments']


@pytest.mark.parametrize('fault', ['extra-file', 'extra-empty-directory', 'blueprint-output-aba'])
def test_complete_generated_population_and_original_outputs_remain_current(tmp_path, monkeypatch, fault):
    root, bundle, choice, value, selected, api = prepared(tmp_path, monkeypatch)
    real_write = tools._write
    touched = []
    def final_callback(path, value):
        pin = real_write(path, value)
        if Path(path).name == 'tool-materialization.json':
            directory = Path(path).parent
            if fault == 'extra-file':
                (directory / 'unbound.json').write_bytes(b'{}\n')
            elif fault == 'extra-empty-directory':
                (directory / 'unbound-directory').mkdir()
            else:
                target = directory / 'materialization.json'
                raw = target.read_bytes()
                target.write_bytes(b'{}\n')
                target.write_bytes(raw)
            touched.append(str(directory))
        return pin
    monkeypatch.setattr(tools, '_write', final_callback)
    spec = tools.materialization_spec(bundle, choice, base_dir=tmp_path, output_dir=root / 'late-compiled',
        graph_id='independent-output-membership', max_wall_seconds=10)
    outcome = cycle.execute_graph(root, tmp_path / 'late-graph', spec, agent_host.AgentHost())
    assert touched
    assert not outcome['complete']
    assert not cycle._load(root)[1]['experiments']


def test_stored_experiment_context_inventory_contains_complete_tool_closure(tmp_path, monkeypatch):
    root, bundle, result, api = compile_and_admit(tmp_path, monkeypatch)
    closure = tools.input_pins(bundle, tmp_path)
    required = {pin['path']: pin for pin in closure}
    assert bundle['path'] in required and api['path'] in required
    for experiment in cycle._load(root)[1]['experiments']:
        actual = {pin['path']: pin for pin in experiment['input_pins']}
        assert all(actual[path] == pin for path, pin in required.items())
    # The ordinary solver population remains the adapter's actual inputs;
    # the existing cycle inventory additionally presents its design context.
    experiment = cycle._load(root)[1]['experiments'][0]
    specification = read_json(experiment['study']['path'])
    scientific = set(map(str, science.task_inputs(specification, Path(experiment['study']['path']).parent)))
    assert scientific < set(pin['path'] for pin in experiment['input_pins'])
    assert api['path'] not in scientific
    assert not cycle.status(root)['parent_task_accepted']


def test_tool_context_exposure_and_graph_admission_require_full_design_inputs(tmp_path, monkeypatch):
    root, bundle, result, api = compile_and_admit(tmp_path, monkeypatch)
    raw = read_json(result['portfolio']['path'])['experiments'][0]
    specification = read_json(raw['study']['path'])
    solver_pins = [cycle._pin(path) for path in science.task_inputs(specification, Path(raw['study']['path']).parent)]
    with pytest.raises(ValueError, match='complete canonical execution input exposure census'):
        cycle.bind_input_exposure(raw, {p['path']:'model_context' for p in solver_pins},
            tmp_path/'incomplete-exposure', base_dir=tmp_path, reason='Synthetic incomplete design context')
    full = cycle._tool_input_closure(raw, solver_pins, tmp_path)
    exposed = cycle.bind_input_exposure(raw, {p['path']:'model_context' for p in full},
        tmp_path/'complete-exposure', base_dir=tmp_path, reason='Synthetic fully disclosed design context')
    manifest = read_json(exposed['input_exposure']['path'])
    assert {p['path'] for p in manifest['inputs']} == {p['path'] for p in full}
    with pytest.raises(ValueError, match='all explicitly disclosed study sources'):
        cycle._model_input_admission(raw, full, solver_pins, tmp_path)
    cycle._model_input_admission(exposed, full, [*full, exposed['input_exposure']], tmp_path)
