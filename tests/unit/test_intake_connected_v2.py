"""Engineering controls for actual intake/Graph/worker/parent connections.

Authored without execution. Planner model transport is an explicit inert fixture;
ordinary child planning and all source/input guards are real. The separately
marked calculation lifecycle test launches only the finite stdlib arithmetic
worker through ordinary approved science, and needs root's software admission.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from ravel import cli
from ravel.physics import literal_calculation as arithmetic
from ravel.validation import validate_run_state as validation
from ravel.workflow import agent_graph as graph, agent_host, calculation_completion as completion
from ravel.workflow import intake, intake_planner as planner, route_prompt, science, execution
from ravel.workflow.state_io import read_json


def store(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, allow_nan=False) + '\n').encode()
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def parent(base, prompt):
    base.mkdir(parents=True, exist_ok=True)
    contract = route_prompt.route(prompt)
    return contract, store(base / 'inputs/task_contract.json', contract)


def literal_spec(pin, expression='2+2'):
    return {'schema_version': 1, 'mode': 'literal-calculation', 'source': 'Original supplied literal arithmetic request',
        'assumptions': ['All operands are exact dimensionless decimal literals; no physical inference'],
        'max_seconds': 20, 'approval_mode': 'scripted_yes',
        'task': {'parent_contract': pin, 'expression': expression, 'unit': '1'}}


@pytest.mark.parametrize('expression,numerator,denominator', [
    ('2+2', '4', '1'), ('0.1+0.2', '3', '10'), ('-3/2', '-3', '2'), ('(2+3)**2', '25', '1'),
])
def test_exact_literal_decimal_and_signed_result(expression, numerator, denominator):
    value = arithmetic.exact_value(expression)
    assert value == {'numerator': numerator, 'denominator': denominator, 'unit': '1',
                     'representation': 'exact_rational', 'rounding': 'none'}


@pytest.mark.parametrize('expression', ['1/0', 'True+1', 'abs(-2)', '__import__("os")', '2**100', '1e9999', 'x+1'])
def test_literal_language_has_no_unreviewed_python_or_unbounded_operation(expression):
    with pytest.raises(ValueError): arithmetic.exact_value(expression)


def test_entire_numerical_objective_units_and_original_bytes_are_required(tmp_path):
    _, pin = parent(tmp_path, 'Compute 2+2')
    task = literal_spec(pin)['task']
    result = arithmetic.run(task, tmp_path, None)
    assert result['original_request'] == 'Compute 2+2' and result['quantity']['numerator'] == '4'
    assert arithmetic.validate_result(result, task, tmp_path) == result
    for changed in [dict(task, expression='2+3'), dict(task, unit='GeV')]:
        with pytest.raises(ValueError): arithmetic.run(changed, tmp_path, None)
    Path(pin['path']).write_bytes(Path(pin['path']).read_bytes() + b' ')
    with pytest.raises(ValueError): arithmetic.run(task, tmp_path, None)


def test_literal_operation_cannot_reduce_broad_original_request(tmp_path):
    _, pin = parent(tmp_path, 'Compute 2+2 and explain the full detector response and uncertainty.')
    with pytest.raises(ValueError): arithmetic.run(literal_spec(pin)['task'], tmp_path, None)


@pytest.mark.parametrize('prompt', ['Run autonomously. Calculate 2+2.', 'Calculate 2+2 and run autonomously.'])
def test_explicit_autonomy_clause_retains_whole_calculation_prompt_without_approval(tmp_path, prompt):
    _, pin = parent(tmp_path, prompt)
    task = literal_spec(pin)['task']
    validated = arithmetic.validate_parent(task, tmp_path)
    assert validated['original_request'] == prompt and validated['quantity']['numerator'] == '4'
    assert validated['execution_authorized'] is False
    for invalid in ['Do not run autonomously. Calculate 2+2.', 'If approved, run autonomously. Calculate 2+2.', 'Example: run autonomously. Calculate 2+2.', 'Compute 2+2; run autonomously and infer a physical discovery.']:
        with pytest.raises(ValueError): arithmetic.expression_from_prompt(invalid)


def test_original_calculation_cannot_complete_with_bare_result_json(tmp_path):
    contract, _ = parent(tmp_path, 'Compute 2+2')
    store(tmp_path / 'outputs/result.json', {'schema_version': 1, 'value': 4, 'unit': '1'})
    gate = validation.evaluate(str(tmp_path), contract)
    assert gate['verdict'] == 'FAIL' and not gate['parent_task_accepted']
    assert next(s for s in gate['stages'] if s['name'] == 'basis_manifest')['status'] == 'N/A'
    assert not (tmp_path / 'inputs/basis_manifest.json').exists()


def prepare_case(tmp_path, monkeypatch, prompt='Investigate an original background method and its full validation.'):
    contract, pin = parent(tmp_path / 'parent', prompt)
    # Read-only source/runtime metadata fixture; no socket/process/model/native.
    monkeypatch.setattr(execution, 'runtime_context', lambda: {'explicit_inert_source_control': True,
        'environment_sha256': execution.digest(execution.runtime_environment())})
    def refuse(*args, **kwargs): raise AssertionError('no process, native or provider dispatch allowed in planner controls')
    monkeypatch.setattr(subprocess, 'Popen', refuse)
    request = planner.prepare(pin, tmp_path / 'parent/planning', base_dir=tmp_path,
        candidate_modes=['literal-calculation', 'symbolic-evaluation'], evidence=[],
        resources={'max_child_seconds': 20, 'max_calls': 2, 'max_output_tokens': 4096, 'max_wall_seconds': 45})
    gr, output = tmp_path / 'parent/graph', tmp_path / 'parent/prepared'
    spec = planner.graph_spec(request, gr, output, base_dir=tmp_path, graph_id='intake-control',
        model='explicit-inert-fixture', reasoning_effort='high', adapter='responses')
    return contract, pin, request, gr, output, spec


def source_choice(request):
    document = read_json(request['path']); source = document['presented_inputs'][1]
    work = {'summary': 'Implement the missing original background validation operation',
        'missing_operations': ['source-defined background fit and independent validation'],
        'owned_paths': ['src/ravel/physics/new_background.py', 'tests/unit/test_new_background.py'],
        'input_contract': 'Pinned complete SR/CR model, blinded data and calibrated test-statistic law',
        'output_contract': 'Complete original background and validation results, including failures and null outcomes',
        'acceptance_tests': ['complete population retained', 'missing calibration remains unresolved', 'late source drift refuses'],
        'source_evidence': [source]}
    return {'kind': 'intake-plan-choice', 'request_sha256': request['sha256'], 'disposition': 'source_development',
            'reason': 'Current APIs do not implement this exact proposed method; retain the full parent and prepare reviewed source work',
            'plan_json': json.dumps(work)}


def execute_inert(gr, spec, choice, monkeypatch):
    host = agent_host.AgentHost()
    monkeypatch.setattr(host, '_responses', lambda data, parameters, request, control:
        host._result(deepcopy(choice), parameters, request, observed_model='explicit-inert-fixture',
                     usage={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}))
    graph.create(gr, spec)
    return graph.execute(gr, host)


def test_actual_graph_host_compiles_original_goal_source_development(tmp_path, monkeypatch):
    contract, pin, request, gr, output, spec = prepare_case(tmp_path, monkeypatch)
    result = execute_inert(gr, spec, source_choice(request), monkeypatch)
    assert result['complete'] and result['usage']['calls'] == 2
    delivered = read_json(output / 'delivery.json')
    work = read_json(delivered['source_development']['path'])
    assert work['original_request'] == contract['prompt']
    assert work['original_obligations'] == contract['task_requirements']['obligations']
    assert work['parent_task_accepted'] is work['execution_authorized'] is False
    assert delivered['origin']['node_kind'] == 'model'
    assert not (output / 'study').exists()


def test_actual_graph_host_prepares_unapproved_literal_science_child(tmp_path, monkeypatch):
    _, pin, request, gr, output, spec = prepare_case(tmp_path, monkeypatch, 'Compute 2+2')
    choice = {'kind': 'intake-plan-choice', 'request_sha256': request['sha256'], 'disposition': 'scientific_study',
              'reason': 'Exact complete dimensionless request', 'plan_json': json.dumps(literal_spec(pin))}
    result = execute_inert(gr, spec, choice, monkeypatch)
    assert result['complete'] and result['usage']['calls'] == 2
    assert science.packet(output / 'study')['execution']['status'] == 'planned'
    assert science.verify_plan(output / 'study')['mode'] == 'literal-calculation'
    assert not (output / 'study' / science.APPROVAL).exists()
    assert not (output / 'study' / 'execution_attempt.json').exists()
    assert read_json(output / 'delivery.json')['remaining_parent_obligations']


def test_actual_planner_forwards_ci1_response_without_reinitialization_or_approval(tmp_path, monkeypatch):
    _, pin, request, gr, output, spec = prepare_case(tmp_path, monkeypatch, 'Compute 2+2')
    choice = {'kind':'intake-plan-choice','request_sha256':request['sha256'],
        'disposition':'scientific_study','reason':'complete original arithmetic',
        'plan_json':json.dumps(literal_spec(pin))}
    assert execute_inert(gr, spec, choice, monkeypatch)['complete']
    child = output / 'study'
    unchanged = {name:(child/name).read_bytes() for name in [science.SPEC,science.PLAN,'inputs/checkin1.json']}
    message = tmp_path / 'actual-response.txt'; raw = b'Run autonomously.'; message.write_bytes(raw)
    user = {'path':str(message),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
    delivery = output / 'delivery.json'; raw_delivery = delivery.read_bytes()
    result = planner.record_checkin1_response({'path':str(delivery),'sha256':hashlib.sha256(raw_delivery).hexdigest(),'size':len(raw_delivery)},
        user_text=user,quote='Run autonomously.',delegate_actor='explicit-engineering-coordinator',actions=['approve_plan'],
        bounds={'compute_plans':['none'],'allowed_changed_paths':[],'allowed_stages':['science'],'max_redos':0},
        task_class='deterministic_calculation',base_dir=tmp_path)
    assert result['execution_authorized'] is False and result['parent_task_accepted'] is False
    assert result['delegation']['delegation']['authority_label'] == 'machine_under_user_delegation'
    assert (child/'inputs/checkin1-response.txt').read_bytes() == raw
    assert all((child/name).read_bytes() == data for name,data in unchanged.items())
    assert not (child/science.APPROVAL).exists() and not (child/'execution_attempt.json').exists()
    assert graph.status(gr)['usage']['calls'] == 2



@pytest.mark.parametrize('mutation', ['foreign-request', 'unknown-mode', 'overbudget', 'missing-source'])
def test_actual_planner_refuses_choice_outside_grounded_inputs(tmp_path, monkeypatch, mutation):
    _, pin, request, gr, output, spec = prepare_case(tmp_path, monkeypatch, 'Compute 2+2')
    study = literal_spec(pin)
    choice = {'kind': 'intake-plan-choice', 'request_sha256': request['sha256'], 'disposition': 'scientific_study',
              'reason': 'Finite control', 'plan_json': json.dumps(study)}
    if mutation == 'foreign-request': choice['request_sha256'] = '0' * 64
    if mutation == 'unknown-mode': study['mode'] = 'invented-executor'
    if mutation == 'overbudget': study['max_seconds'] = 21
    if mutation == 'missing-source': study['task']['parent_contract'] = {**pin, 'path': str(tmp_path / 'foreign.json')}
    if mutation != 'foreign-request': choice['plan_json'] = json.dumps(study)
    result = execute_inert(gr, spec, choice, monkeypatch)
    assert not result['complete']
    assert not (output / 'delivery.json').exists()


@pytest.mark.parametrize('target', ['source-development.json', 'delivery.json'])
def test_generated_planner_commitment_cannot_be_rebaselined_after_emission(tmp_path, monkeypatch, target):
    _, _, request, gr, output, spec = prepare_case(tmp_path, monkeypatch)
    original = planner._write
    def late(path, value, observed):
        pin = original(path, value, observed)
        if Path(path).name == target: Path(path).write_bytes(Path(path).read_bytes() + b' ')
        return pin
    monkeypatch.setattr(planner, '_write', late)
    result = execute_inert(gr, spec, source_choice(request), monkeypatch)
    assert not result['complete'] and (output / target).exists()


def test_method_study_survey_progress_cannot_be_final_original_task(tmp_path):
    contract, pin = parent(tmp_path, 'Develop a collider classifier method with baselines and independent validation.')
    assert contract['task_mode'] == 'survey' and contract['intake']['kind'] == 'method_study'
    store(tmp_path / 'outputs/survey.json', {'schema_version': 1, 'proposal': 'candidate classifier'})
    assert validation.result_pack_paths(str(tmp_path), 'survey', intake_kind='method_study') == {}
    facts = {'result_pack_paths': {}, 'task_contract_path': pin['path']}
    status, _, checks = validation.check_result_pack(str(tmp_path), contract, facts, 'R', False)
    assert status == 'FAIL' and 'original method-study parent' in checks[0]['msg']
    request = {'schema_version': 1, 'contract': pin, 'outcomes': [], 'parent_review': None, 'report': None}
    store(tmp_path / 'inputs/task_completion.json', request)
    facts['result_pack_paths'] = {'inputs/task_completion.json': 'inputs/task_completion.json'}
    status, _, checks = validation.check_result_pack(str(tmp_path), contract, facts, 'R', False)
    assert status == 'FAIL' and 'original parent task remains open' in checks[0]['msg']


@pytest.mark.parametrize('prompt', [
    'Investigate the excess and compute significance of the excess, retaining null results and stating all calibration limitations.',
    'Estimate the observed significance and retain the full background and calibration uncertainties.',
])
def test_neutral_unknown_inference_preserves_research_objective(prompt):
    contract = route_prompt.route(prompt)
    assert not intake.requests_discovery(prompt)
    assert contract['task_mode'] == 'research' and contract['prompt'] == prompt
    assert contract['task_requirements']['obligations'][0]['statement'] == prompt
    assert contract['compute_plan'] == 'none' and contract['approval_required'] is True


@pytest.mark.parametrize('prompt', ['Claim a discovery at 5 sigma.', 'Give a 5 sigma result from the excess.'])
def test_predetermined_claim_cannot_be_authorized_by_intake(prompt):
    assert intake.requests_discovery(prompt)
    assert route_prompt.route(prompt)['task_mode'] == 'unsupported'


def test_actual_software_calculation_lifecycle_completes_parent_without_curves(tmp_path):
    """Root-only software admission: real stdlib child, no scientific/native engine."""
    contract, pin = parent(tmp_path / 'parent', 'Compute 2+2')
    sp = store(tmp_path / 'science.json', literal_spec(pin))
    rd = tmp_path / 'child'
    science.plan(rd, sp['path'])
    assert validation.evaluate(str(tmp_path / 'parent'), contract)['verdict'] == 'FAIL'
    science.approve(rd, 'Root-authorized synthetic engineering calculation control', scripted=True)
    assert science.run(rd) == 0
    completion.collect(pin, rd, tmp_path / 'parent/inputs/calculation_delivery.json', base_dir=tmp_path)
    gate = validation.evaluate(str(tmp_path / 'parent'), contract)
    assert gate['verdict'] == 'PASS' and gate['parent_task_accepted'] is True
    assert not (tmp_path / 'parent/inputs/basis_manifest.json').exists()
    assert not (rd / 'inputs/physics_review_policy.json').exists()
    Path(rd / 'outputs/result.json').write_bytes(Path(rd / 'outputs/result.json').read_bytes() + b' ')
    assert validation.evaluate(str(tmp_path / 'parent'), contract)['verdict'] == 'FAIL'
