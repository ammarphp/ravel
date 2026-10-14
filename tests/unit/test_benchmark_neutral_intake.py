"""Generic scientific-action transfer; authored, not executed by the source owner."""
import synthetic_identifiers as syn
from copy import deepcopy
import json

import pytest

from ravel import cli
from ravel.validation.validate_task_contract import validate
from ravel.workflow import agent_graph as graph, agent_host, capability_routing
from ravel.workflow import current_state, intake, route_prompt, task_completion
from test_intake_connected_v2 import prepare_case, execute_inert, source_choice


def assert_census_keeps_request(result, prompt, plain=None):
    """The whole request is the first obligation, verbatim; a context label adds or changes no finer one."""
    obligations = result['task_requirements']['obligations']
    assert obligations[0] == task_completion.initial_requirements(prompt)['obligations'][0]
    if plain is not None:
        finer = lambda rows: [(o['id'], o['kind'], o['criteria']) for o in rows[1:]]
        assert finer(obligations) == finer(plain['task_requirements']['obligations'])


LABELS = ['Opaque Amber Label', 'Opaque Birch Label', 'Unseen Northern Laboratory Suite']
TASKS = [
    ('Calculate 2+2.', 'calculation'),
    (('Reproduce the published limits for ' + syn.analysis(28) + '.'), 'reproduce'),
    ('Investigate the full signal, backgrounds and validation of this new measurement.', 'research'),
    ('Implement a custom collider analysis routine and validate all requested bins.', 'research'),
    ('Please make the supplied situation useful.', 'unsupported'),
]


@pytest.mark.parametrize('label', LABELS)
@pytest.mark.parametrize('question,mode', TASKS)
def test_explicit_provenance_label_does_not_select_the_scientific_action(label, question, mode):
    original = route_prompt.route(question)
    prompt = 'Benchmark label: ' + label + '\n' + question
    result = route_prompt.route(prompt)
    assert result['task_mode'] == original['task_mode'] == mode
    assert result['stat_mode'] == original['stat_mode']
    assert result['detector_mode'] == original['detector_mode']
    assert result['targets'] == original['targets']
    assert result['prompt'] == prompt and validate(result) == []
    assert_census_keeps_request(result, prompt, original)
    assert result['approval_required'] is True
    if 'intake' in result:
        assert result['intake']['objective'] == prompt
        assert result['intake']['evidence'] == [{'start':0,'end':len(prompt),'text':prompt}]
    assert result.get('compute_plan') in ('none', 'smoke', 'scan', 'TBD-judgment')


@pytest.mark.parametrize('label', LABELS)
def test_bare_nonscientific_name_does_not_override_an_explicit_calculation(label):
    prompt = label + ': Calculate 2+2.'
    result = route_prompt.route(prompt)
    assert result['task_mode'] == result['intake']['kind'] == 'calculation'
    assert result['intake']['objective'] == prompt
    assert intake.routing_text(prompt) == prompt  # No arbitrary colon prefix was stripped.


@pytest.mark.parametrize('label', LABELS)
def test_same_label_changed_physics_changes_the_route(label):
    a = route_prompt.route('Suite name: ' + label + '\nCalculate 2+2.')
    b = route_prompt.route('Suite name: ' + label + ('\nReproduce ' + syn.analysis(28) + '.'))
    c = route_prompt.route('Suite name: ' + label + '\nInvestigate a new background strategy.')
    assert (a['task_mode'], b['task_mode'], c['task_mode']) == ('calculation', 'reproduce', 'research')


@pytest.mark.parametrize('label', LABELS)
def test_name_without_scientific_question_stays_unresolved(label):
    prompt = 'Benchmark label: ' + label
    recovery = capability_routing.plan(prompt)
    assert recovery['legacy_draft']['task_mode'] == 'unsupported'
    assert recovery['classification_status'] == 'needs_intent_resolution'
    assert recovery['original_request'] == prompt
    assert recovery['parent_goal_replaced'] is recovery['compute_authorized'] is recovery['physics_validated'] is False
    assert any(row['stage'] == 'resolve' for row in recovery['next_actions'])


@pytest.mark.parametrize('label', ['RS1', 'mapyde', 'slepton', 'Projection Grid', 'ShapeFitSuite'])
def test_opaque_context_does_not_add_lexical_component_candidates(label):
    question = 'Calculate 2+2.'
    plain = capability_routing.plan(question)
    annotated = capability_routing.plan('Source label: ' + label + '\n' + question)
    assert annotated['candidates'] == plain['candidates']
    assert annotated['original_request'] != plain['original_request']


def test_actual_source_tool_reproduction_hint_remains_available():
    # 8f71cf3: a source-bound adapter is offered only when the request names what it is bound to;
    # a request that does not is offered the general operation alone.
    request = 'Check likelihood parity of the supplied source and its retained conditional profile candidates.'
    result = capability_routing.plan(request)
    modes = {row['mode'] for row in result['candidates']}
    assert 'likelihood-parity' in modes and 'likelihood-candidate-check' not in modes
    named = capability_routing.plan(request + ' Use likelihood-candidate-check.')
    assert {'likelihood-parity', 'likelihood-candidate-check'} <= {row['mode'] for row in named['candidates']}
    for plan in (result, named):
        assert all(row['selection'] == 'declared_metadata_match_requires_host_review' for row in plan['candidates'])
        assert plan['compute_authorized'] is False


@pytest.mark.parametrize('prefix,question,mode', [
    ('Expected significance: ', 'calculate the significance for the supplied physical model.', 'survey'),
    ('Scan masses: ', 'cover all points from 200 to 500 GeV.', 'scan'),
    ('Constraint: retain the 30 second ceiling. ', 'Calculate the lifetime from a supplied width.', 'calculation'),
    ('Mass [GeV]: 300. ', ('Reproduce the published limits for ' + syn.analysis(28) + '.'), 'reproduce'),
])
def test_meaningful_physics_prefix_is_not_discarded(prefix, question, mode):
    prompt = prefix + question
    assert intake.routing_text(prompt) == prompt
    result = route_prompt.route(prompt)
    assert result['task_mode'] == mode and result['prompt'] == prompt
    assert_census_keeps_request(result, prompt)


@pytest.mark.parametrize('value', [
    'Calculate 2+3', 'Only after approval', 'mass 300 GeV', 'Expected significance',
    'A; reproduce every bin', 'Do not calculate', 'alpha=0.3', 'source "quote"',
])
def test_scientific_or_ambiguous_identifier_content_requires_host_interpretation(value):
    prompt = 'Task label: ' + value + '\nCalculate 2+2.'
    assert intake.routing_text(prompt) == prompt and intake.routing_context_unresolved(prompt)
    result = route_prompt.route(prompt)
    assert result['task_mode'] == 'unsupported' and result['compute_plan'] == 'none'
    assert result['prompt'] == prompt
    assert any('grounded --interpretation' in item for item in result['blocking'])


def test_grounded_interpretation_resolves_ambiguous_context_without_rewriting_it():
    prompt = 'Task label: Expected significance\nCalculate the stated expected significance from the supplied model.'
    semantic = {'schema_version':1,'prompt_sha256':intake.prompt_hash(prompt),'kind':'research',
        'objective':prompt,'requested_outputs':['The complete original expected-significance question'],
        'evidence':[{'start':0,'end':len(prompt),'text':prompt}],
        'unresolved':['Exact source model, calibration and finite resource inputs']}
    result = route_prompt.route(prompt, semantic)
    assert result['task_mode'] == 'research' and result['intake']['source'] == 'host-agent'
    assert result['prompt'] == result['intake']['objective'] == prompt
    assert result['approval_required'] is True and result['compute_plan'] == 'none'
    changed = deepcopy(semantic); changed['prompt_sha256'] = '0' * 64
    with pytest.raises(ValueError): route_prompt.route(prompt, changed)


@pytest.mark.parametrize('question', [
    'Run the original task and deliver its full simulation, selections, bins, code and report.',
    'Execute a new custom analysis workflow and provide all requested outputs.',
])
def test_whole_workflow_is_research_without_comparator_name(question):
    # "execute analysis workflow" is a full action, not a compact calculation.
    result = route_prompt.route(question)
    if 'full simulation' in question:
        # ad35854: a demand for full detector simulation is held and never silently downgraded to
        # the fast response; the same whole-workflow request without that demand is research.
        assert result['task_mode'] == 'unsupported' and result['compute_plan'] == 'none'
        assert any('Full simulation of the detector' in row for row in result['blocking'])
        assert route_prompt.route(question.replace(' full simulation,', ''))['task_mode'] == 'research'
    else:
        assert result['task_mode'] == 'research'


@pytest.mark.parametrize('question', [
    'Do not calculate 2+2.',
    'Claim discovery of a new particle at 5 sigma.',
])
def test_metadata_cannot_override_negation_or_claim_boundary(question):
    prompt = 'Benchmark label: Example Collider Benchmark\n' + question
    result = route_prompt.route(prompt)
    assert result['task_mode'] == 'unsupported' and result['compute_plan'] == 'none'
    assert result['task_requirements']['obligations'] == task_completion.initial_requirements(prompt)['obligations']


@pytest.mark.parametrize('label', LABELS)
def test_public_initiate_preserves_complete_task_and_current_handoff_without_approval(tmp_path, monkeypatch, label):
    monkeypatch.setattr(cli.subprocess, 'call', lambda *a, **k: pytest.fail('intake launched compute'))
    prompt = 'Benchmark label: ' + label + '\nCalculate the lifetime from the supplied width in GeV.'
    root = tmp_path / 'ordinary-parent'
    assert cli.main(['initiate','--prompt',prompt,'--out',str(root)]) == 0
    contract = json.loads((root/'inputs/task_contract.json').read_text())
    handoff = json.loads((root/'inputs/intake_handoff.json').read_text())
    packet = current_state.build_packet(root)
    assert (root/'request.txt').read_text() == contract['prompt'] == handoff['original_request'] == prompt
    assert packet['intake_handoff'] == handoff
    assert handoff['obligations'] == contract['task_requirements']['obligations']
    assert handoff['child_schema_version'] == 2
    assert handoff['parent_task_accepted'] is handoff['compute_authorized'] is False
    assert not (root/'inputs/checkin1_approval.json').exists()
    assert not (root/'execution_attempt.json').exists()


def test_unknown_public_intake_retains_source_and_recovery(tmp_path):
    prompt = 'Suite name: Unseen Northern Laboratory Suite\nPlease make the supplied situation useful.'
    root = tmp_path / 'held-parent'
    assert cli.main(['initiate','--prompt',prompt,'--out',str(root)]) == 1
    assert (root/'request.txt').read_text() == prompt
    recovery = json.loads((root/'inputs/capability_recovery.json').read_text())
    assert recovery['original_request'] == prompt and recovery['compute_authorized'] is False
    assert (root/'current_state.json').is_file()


def test_real_host_context_contains_full_label_question_sources_and_obligations(tmp_path, monkeypatch):
    prompt = 'Benchmark label: Unseen Northern Laboratory Suite\nCalculate the lifetime from the supplied width.'
    contract, pin, request, root, output, spec = prepare_case(tmp_path, monkeypatch, prompt)
    host = agent_host.AgentHost()
    graph.create(root, spec)
    document, state = graph._load(root)
    node = document['nodes'][0]
    prepared = host.prepare_model_context(node, graph._request(document,state,node,graph._host_identity(host)))
    context = json.dumps(prepared['context'],ensure_ascii=False)
    assert 'Unseen Northern Laboratory Suite' in context and 'Calculate the lifetime' in context
    assert 'original-task' in context and pin['sha256'] in context
    assert graph.status(root)['usage']['calls'] == 0
    assert not output.exists()
    assert contract['prompt'] == prompt


def test_real_host_inert_source_development_keeps_unseen_original_task_open(tmp_path, monkeypatch):
    prompt = 'Benchmark label: Unseen Northern Laboratory Suite\nImplement a custom collider analysis routine and validate every requested bin.'
    contract, pin, request, root, output, spec = prepare_case(tmp_path,monkeypatch,prompt)
    result = execute_inert(root,spec,source_choice(request),monkeypatch)
    assert result['complete'] and result['usage']['calls'] == 2
    delivery = json.loads((output/'delivery.json').read_text())
    work = json.loads(open(delivery['source_development']['path']).read())
    assert work['original_request'] == prompt
    assert work['original_obligations'] == contract['task_requirements']['obligations']
    assert work['parent_task_accepted'] is work['execution_authorized'] is False
    assert not (output/'study').exists()


def test_context_is_not_a_literal_calculation_or_delegation_exemption(tmp_path):
    from ravel.physics.literal_calculation import expression_from_prompt
    prompt = 'Context label: Ordinary Suite\nCalculate 2+2 and retain the uncertainty qualification.'
    result = route_prompt.route(prompt)
    assert result['task_mode'] == 'calculation' and result['prompt'] == prompt
    with pytest.raises(ValueError): expression_from_prompt(prompt)
    assert result['approval_required'] is True


SCIENTIFIC_PARENTS = [
    ('Reproduce the published fiducial cross-section analysis and validate all bins.', 'reproduce'),
    (('Reinterpret the published ' + syn.analysis(28) + ' limits for the supplied model.'), 'reinterpret'),
    ('Scan masses from 200 to 500 GeV and validate every point.', 'scan'),
    ('Survey which analyses constrain the supplied physics scenario.', 'survey'),
    # Exact original prompt bodies remain legitimate transfer acceptance inputs.
    *[(prompt,mode) for prompt,mode,_ in route_prompt.REFERENCE_PROMPTS[:3]],
    ('Construct a model-agnostic anomaly search and validate the supplied topology.', 'anomaly_search'),
]


def open_settings():
    return dict(campaign={'id':'complete-original-scientific-task',
        'budget':{'calls':12,'output_tokens':50000,'wall_seconds':600,'native_attempts':2},
        'max_experiments':2,'exploration_every':2,'required_experiments':[],'premises':[]},
        runtime={'model':'inert-source-control','reasoning_effort':'high','adapter':'model',
                 'max_output_tokens':4096,'max_wall_seconds':30}, evidence=[],
        candidate_modes=['quantities'], review={'arguments':{},'allow_control':True},max_decisions=4)


@pytest.mark.parametrize('question,mode', SCIENTIFIC_PARENTS)
@pytest.mark.parametrize('label', [None, *LABELS])
def test_ordinary_scientific_parent_initiate_status_and_open_preparation_preserve_original_mode(tmp_path, question, mode, label):
    from ravel.workflow import research_orchestrator as orchestration, research_coordinator_decisions as decisions
    prompt = question if label is None else 'Benchmark label: ' + label + '\n' + question
    root = tmp_path/'parent'
    assert cli.main(['initiate','--prompt',prompt,'--out',str(root)]) == 0
    path = root/'inputs/task_contract.json';contract = json.loads(path.read_text())
    assert contract['task_mode'] == mode
    handoff = json.loads((root/'inputs/intake_handoff.json').read_text())
    assert current_state.build_packet(root)['intake_handoff'] == handoff
    assert handoff['task_kind'] == handoff['task_mode'] == mode
    assert handoff['original_request'] == prompt and handoff['obligations'] == contract['task_requirements']['obligations']
    expected = [{'obligation_id':r['id'],'criteria':r['criteria']} for r in handoff['obligations']]
    assert contract['task_requirements']['assignments'][0]['coverage'] == expected
    assert handoff['parent_contract']['path'] == str(path)
    settings=tmp_path/'settings.json';settings.write_text(json.dumps(open_settings())+'\n')
    assert cli.main(['research-orchestrate','prepare','--parent-contract',str(path),
                     '--settings',str(settings),'--out',str(tmp_path/'prepared')])==0
    request_pin=orchestration._pin(tmp_path/'prepared/request.json')
    value = decisions.request(request_pin)
    assert value['handoff'] == handoff and value['campaign'] == open_settings()['campaign']
    assert value['handoff']['goal_binding']['assignment_id'] == 'original-task'
    assert json.loads(path.read_text()) == contract  # No relabelling or changed figure/statistical gates.
    assert handoff['compute_authorized'] is handoff['parent_task_accepted'] is handoff['physics_validated'] is False
    assert not (root/'inputs/checkin1_approval.json').exists()
    assert not (root/'execution_attempt.json').exists()
    first = capability_routing.plan(prompt)['next_actions'][0]
    research = mode == 'anomaly_search'
    assert first['stage'] == 'prepare-parent' and handoff['route'] == ('research' if research else 'checkin')
    assert ('research-orchestrate' in first['tool']) is research
    assert ('resource_census' in first['tool']) is not research


@pytest.mark.parametrize('question,mode', [
    ('Generate a parton-level generation-only sample.', 'generate'),
    ('Evaluate the supplied likelihood-only workspace.', 'likelihood'),
    ('Calculate 2+2.', 'calculation'),
])
def test_scoped_operations_and_literal_calculation_do_not_acquire_whole_research_coordinator(tmp_path, question, mode):
    from hashlib import sha256
    from ravel.workflow import research_orchestrator as orchestration
    root = tmp_path/'parent'
    assert cli.main(['initiate','--prompt',question,'--out',str(root)]) == 0
    path=root/'inputs/task_contract.json';raw=path.read_bytes();contract=json.loads(raw)
    assert contract['task_mode'] == mode
    pin={'path':str(path),'sha256':sha256(raw).hexdigest(),'size':len(raw)}
    with pytest.raises(ValueError):
        orchestration.prepare_open(pin,tmp_path/'prepared',base_dir=root,**open_settings())
    if mode=='calculation':
        handoff=json.loads((root/'inputs/intake_handoff.json').read_text())
        assert handoff['child_schema_version']==1 and 'intake_planner' in handoff['planning_apis'][0]
    else:
        assert not (root/'inputs/intake_handoff.json').exists()
        assert contract['compute_plan']=='none'
    assert not (tmp_path/'prepared').exists()


def test_changed_or_incomplete_original_parent_cannot_prepare_open_coordinator(tmp_path):
    from hashlib import sha256
    from ravel.workflow import research_orchestrator as orchestration
    root=tmp_path/'parent';question=SCIENTIFIC_PARENTS[0][0]
    assert cli.main(['initiate','--prompt',question,'--out',str(root)])==0
    path=root/'inputs/task_contract.json';raw=path.read_bytes()
    pin={'path':str(path),'sha256':sha256(raw).hexdigest(),'size':len(raw)}
    path.write_bytes(raw+b' ')
    with pytest.raises(ValueError):orchestration.prepare_open(pin,tmp_path/'changed',base_dir=root,**open_settings())
    contract=json.loads(raw);contract['task_requirements']['assignments'][0]['coverage']=[]
    altered=(json.dumps(contract)+'\n').encode();path.write_bytes(altered)
    pin={'path':str(path),'sha256':sha256(altered).hexdigest(),'size':len(altered)}
    with pytest.raises(ValueError):orchestration.prepare_open(pin,tmp_path/'incomplete',base_dir=root,**open_settings())
    assert not (tmp_path/'changed').exists() and not (tmp_path/'incomplete').exists()


@pytest.mark.parametrize('label', ['slepton', 'HVT', (syn.analysis(28)), (syn.arxiv(678))])
def test_explicit_source_identifier_cannot_select_model_analysis_or_statistical_engine(label):
    question='Scan masses from 200 to 500 GeV and retain the full original model question.'
    plain=route_prompt.route(question)
    prompt='Source label: '+label+'\n'+question
    annotated=route_prompt.route(prompt)
    for field in ('targets','stat_mode','detector_mode','compute_plan','required_user_inputs'):
        assert annotated[field]==plain[field]
    assert annotated['prompt']==prompt
    assert_census_keeps_request(annotated, prompt, plain)


def test_grounded_missing_routine_parent_reaches_coordinator_without_relabelled_research(tmp_path):
    from ravel.workflow import research_orchestrator as orchestration, research_coordinator_decisions as decisions
    prompt='Implement the supplied analysis whose reconstruction code is missing, with full validation.'
    interpretation={'schema_version':1,'prompt_sha256':intake.prompt_hash(prompt),'kind':'no_routine',
        'objective':prompt,'requested_outputs':['The complete original implementation and validation'],
        'evidence':[{'start':0,'end':len(prompt),'text':prompt}],
        'unresolved':['Original cuts/objects/input data/runtime and independent validation evidence']}
    semantic=tmp_path/'interpretation.json';semantic.write_text(json.dumps(interpretation)+'\n')
    root=tmp_path/'parent'
    assert cli.main(['initiate','--prompt',prompt,'--interpretation',str(semantic),'--out',str(root)])==0
    path=root/'inputs/task_contract.json';contract=json.loads(path.read_text())
    handoff=current_state.build_packet(root)['intake_handoff']
    assert contract['task_mode']==handoff['task_kind']==handoff['task_mode']=='no_routine'
    settings=tmp_path/'settings.json';settings.write_text(json.dumps(open_settings())+'\n')
    assert cli.main(['research-orchestrate','prepare','--parent-contract',str(path),
        '--settings',str(settings),'--out',str(tmp_path/'prepared')])==0
    value=decisions.request(orchestration._pin(tmp_path/'prepared/request.json'))
    assert value['handoff']==handoff and value['handoff']['original_request']==prompt
    assert handoff['parent_task_accepted'] is handoff['compute_authorized'] is False
