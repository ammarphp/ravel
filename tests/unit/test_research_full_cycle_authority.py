"""Real intake and decision custody for inert research-loop transports."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

from ravel.workflow import rdj_custody, rdj_loop, review_points
from ravel.workflow import research_cycle as cycle, research_protocol as protocol, science
from test_langgraph_research_orchestration import parent
from test_research_cycle import write, contract
from rdj_fixtures import Run, PROPOSER, add, node, anchor_check_depth


def intake(base):
    """Original open task with the actual deterministic reading and draft plan."""
    from ravel.workflow import request_reading, request_plan
    original, _ = parent(base)
    reading = request_reading.document(original['prompt'])
    reading_pin = write(base/'parent/inputs/reading.json', reading)
    original['reading'] = {k: reading_pin[k] for k in ('path', 'sha256')}
    original['reading']['path'] = 'inputs/reading.json'
    plan = write(base/'parent/inputs/request_plan.json', request_plan.draft(reading, original))
    original.update(agent_layer_epoch=2, request_plan={
        'path': 'inputs/request_plan.json', 'sha256': plan['sha256']})
    pin = write(base/'parent/inputs/task_contract.json', original)
    rdj_custody.record_user_text(base/'parent', 'prompt', 'inputs/task_contract.json')
    rdj_custody.record_input_snapshot(base/'parent', 'run_init')
    return original, pin


class Authority:
    """Use the current intake; never fabricate a contract or execution receipt."""
    put = Run.put
    approve = Run.approve
    steering = Run.steering
    case = Run.case

    def __init__(self, root):
        self.root = Path(root)
        review_points._facts(self.root)
        # This is the same original user prompt already bound by run_init.
        rdj_custody.record_user_text(self.root, 'prompt', 'inputs/task_contract.json')

    def requirement(self):
        prompt = json.loads((self.root/'inputs/task_contract.json').read_text())['prompt']
        return {'kind': 'user_requirement', 'binding': {'source': 'prompt',
            'sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'start': 0,
            'end': len(prompt), 'text': prompt}}


def authorize(root, action, *, level=None):
    """Only HTTP replies are inert; RDJ dispatch, registration and authority are real."""
    from test_research_full_cycle_transport import InertDecisionDispatcher
    authority = Authority(root)
    actors = InertDecisionDispatcher()
    case_id = rdj_loop.open_case(root, 'research_choice', action, PROPOSER,
        declared={'class': level} if level else None)
    required = authority.case(case_id)['risk']['class']
    anchors = [authority.requirement()]
    if required == 'R3':
        stage = science.execution.load_execution(root)['stages']['science']
        result = Path(root)/'outputs/attempt-1/result.json'
        anchors.append({'kind': 'tool_output', 'binding': {
            'receipt_id': 'stage:science:'+stage['attempt_id'],
            'output_path': str(result.relative_to(root)), 'sha256': cycle._pin(result)['sha256']},
            'locator': ''})
        from ravel.workflow import rdj_anchor
        checked = rdj_anchor.verify_full(anchors[-1], root)
        assert checked[0] == 'external', checked
    prior = 'action'
    depth = anchor_check_depth(required)
    for number in range(depth):
        identity = 'basis-'+str(number)
        add(authority, case_id, prior, node(identity,
            'The original request supports the bounded fictional decision.',
            anchors=anchors if number == depth-1 else []))
        rdj_loop.run_roles(root, case_id, actors)
        prior = identity
    if required in {'R2', 'R3'}:
        add(authority, case_id, 'action', node('alternative', 'Retain the current incomplete result.',
            kind='alternative'), kind='why_over_alternative')
        rdj_loop.run_roles(root, case_id, actors)
    if required == 'R3':
        authority.approve(case_id)
    receipt = rdj_loop.authorize(root, case_id)
    assert receipt['outcome'] == 'authorize', receipt
    assert rdj_loop.gate_errors(root, 'research_choice', action) == []
    return cycle._pin(Path(root)/'rdj/receipts'/(receipt['receipt_id']+'.json'))


def campaign(tmp_path):
    _, parent_pin = intake(tmp_path)
    c = contract(tmp_path)
    c.update(research_protocol_required=True, goal_binding={
        'contract': parent_pin, 'assignment_id': 'original-task'})
    c['budget'].update(calls=96, output_tokens=300000, wall_seconds=86400)
    root = tmp_path/'cycle'
    cycle.create(root, c, base_dir=tmp_path)
    satisfy_initial_staffing(root)
    return root


def satisfy_initial_staffing(root, *, campaign_root=None):
    """Actual workers fill initial RP1 plan and K11 explore/exploit seats.

    The only fake is the CLI transport process: it reads its exact copied input
    and emits an inert standard CLI envelope. The dispatcher owns confinement,
    actor assignment, receipts, review subjects and custody registration. No
    transport-attestation upgrade or sandbox fallback is supplied by this helper.
    """
    from ravel.workflow import agent_worker, role_registry, spawn_rows, broker, review_projection
    from ravel.workflow.graphs import review as review_graph
    root = Path(root)
    owner = Path(campaign_root) if campaign_root is not None else root
    facts = review_points._facts(root)
    pending = [point for point in spawn_rows.pending(root) if point['row'] == 'K11']
    plan_items = [item for item in review_graph.derive(root, 'checkin1', 1)['items']
                  if item['point_id'] == 'RP1:plan'] if facts.get('agent_layer_epoch') == 2 else []
    if not pending and not plan_items:
        return []
    specs, packets = [], {}
    review_graph.write_packets(root, plan_items)
    for item in plan_items:
        spec = review_graph.worker_spec(root, item)
        spec['transport_preference'] = ['inert-staffing-cli']
        spec['budgets'].update(max_turns=1, max_wall_seconds=60, max_broker_calls=4)
        specs.append(spec)
        packets[spec['node_id']] = review_projection.packet_for(root, item)
    for point in pending:
        for entry in point['roles']:
            role = entry['role']
            card = role_registry.load(role)
            card_pin = write(root/'inputs/staffing'/(role+'.json'), card)
            for number in range(entry['count']):
                namespace = cycle.science.execution.digest(str(root.resolve()))[:12]
                identity = 'initial-' + namespace + '-' + point['id'].replace(':', '-') + '-' + role + '-' + str(number)
                inputs = [
                    {'pin': {'path': 'inputs/task_contract.json',
                             'sha256': broker.sha(root/'inputs/task_contract.json')},
                     'as': 'inputs/original-contract.json'},
                    {'pin': {'path': str(Path(card_pin['path']).relative_to(root)),
                             'sha256': card_pin['sha256']}, 'as': 'inputs/role-card.json'}]
                contract = science.read_json(root/'inputs/task_contract.json')
                for key in ('reading', 'request_plan'):
                    if key in contract:
                        inputs.append({'pin': contract[key], 'as': 'inputs/'+key+'.json'})
                specs.append({'schema_version': 1, 'kind': 'agent-worker-spec',
                    'node_id': identity, 'attempt': 1,
                    'role': {'id': role, 'version': card['version'],
                             'card_sha256': role_registry.card_sha256(role)},
                    'transport_preference': ['inert-staffing-cli'],
                    'inputs': inputs,
                    'declared_outputs': [],
                    'budgets': {'max_turns': 1, 'max_wall_seconds': 60,
                                'max_broker_calls': 4, 'max_cost_usd': None},
                    'final_record_schema': 'reviewer.v1' if role == 'plan-critic' else 'producer.v1', 'work_order': None,
                    'rdj_challenges': None,
                    'parent': {'review_point_id': point['id'], 'map_id': None, 'rca_ticket': None,
                               'review_subject': review_points.review_subject(facts, point)}})
    with cycle.state_io.file_lock(owner/'operation.lock', blocking=False):
        _, state = cycle._load(owner)
        for spec in specs:
            pin = write(root/'inputs/staffing'/(spec['node_id']+'-spec.json'), spec)
            cycle._charge(state, 'staffing:'+cycle.ce.digest(str(root.resolve()))+':'+spec['node_id'],
                {'calls': 1, 'output_tokens': 1024, 'wall_seconds': 60, 'native_attempts': 0}, pin)
        cycle._commit(owner, state, 'initial_research_staffing_reserved',
                      staffing_run=str(root.resolve()), worker_ids=[spec['node_id'] for spec in specs])
    program = '''import json, uuid, os, socket
from pathlib import Path
final={'completed':True,'summary':'Inert original-task staffing control; no physical claim.','findings':[]}
if Path('inputs/review-packet.json').exists():
 item=json.loads(Path('inputs/review-packet.json').read_text())
 manifest=json.loads(Path('inputs/packet/manifest.json').read_text())
 assert item['role']=='plan-critic' and manifest['role']=='plan-critic'
 assert item['point_id']=='RP1:plan'
 final['disposition']='supported'
 sock=socket.socket(socket.AF_UNIX);sock.connect(os.environ['RAVEL_BROKER_SOCKET'])
 sock.sendall((json.dumps({'call_id':'review-output','action':'write','args':{
  'path':'outputs/review.json','content':json.dumps({'schema_version':2,'findings':[]})}})+'\\n').encode())
 reply=json.loads(sock.makefile('rb').readline());assert reply['status']=='ok',reply
 sock.close()
else:
 contract=json.loads(Path('inputs/original-contract.json').read_text())
 card=json.loads(Path('inputs/role-card.json').read_text())
 assert contract['prompt'] and card['id']
 for name in ('reading', 'request_plan'):
  path=Path('inputs')/(name+'.json')
  if path.exists(): assert isinstance(json.loads(path.read_text()),dict)
print(json.dumps({'type':'result','subtype':'success','is_error':False,
 'result':'','session_id':'inert-staffing-'+uuid.uuid4().hex,'num_turns':1,
 'total_cost_usd':0.0,'usage':{'input_tokens':0,'output_tokens':0},
 'modelUsage':{'claude-inert-control':{'outputTokens':0}},'structured_output':final}))
'''
    receipts = []
    for spec in specs:
        descriptor = {'argv': [sys.executable, '-B', '-c', program], 'pass_env_names': [],
            'transport': {'id': 'inert-staffing-cli', 'transport_kind': 'cli-worker',
                'agent': 'claude', 'cli_version': 'inert-standard-envelope-fixture',
                'declared_attestation': 'transport', 'user_configuration_declared_loaded': False,
                'limits': {'max_turns': 1, 'max_cost_usd': None}},
            'model': {'requested': 'claude-inert-control', 'observed': None,
                      'family': 'claude', 'effort': 'high'}}
        receipt = agent_worker.dispatch(root, spec, packet=packets.get(spec['node_id']), launch_spec=descriptor)
        assert receipt['status'] == 'ok', receipt
        assert receipt['attestation'] == 'transport_attested', receipt
        receipts.append(receipt)
    assert not [point for point in spawn_rows.pending(root) if point['row'] == 'K11']
    assert not [point for point in review_points.pending(root) if point['row'] == 1]
    return receipts


@pytest.mark.parametrize('damage', ['missing', 'forged', 'stale'])
def test_stage_authority_requires_current_registered_decision(tmp_path, damage):
    from test_research_default_protocol import synthetic_artifacts
    root = campaign(tmp_path)
    artifact = write(root/'census.json', synthetic_artifacts(root)['limitation_census'])
    action = protocol.stage_action('limitation_census', artifact)
    if damage == 'forged':
        write(root/'rdj/receipts/forged.json', {'outcome': 'authorize', 'action_digest': artifact['sha256']})
    elif damage == 'stale':
        authorize(root, action)
        doc = protocol._method_json(artifact, root)
        doc['limitations'][0]['consequence'] = 'Changed scope requires a new decision.'
        artifact = write(root/'census.json', doc)
    before = cycle._load(root)[1]
    with pytest.raises(ValueError, match='rdj_'):
        protocol.prepare_stage(root, 'limitation_census', artifact, root/'review', model='gpt-5')
    assert cycle._load(root)[1] == before
    assert not (root/'review').exists()


def test_real_decision_allows_preparation_but_never_approval(tmp_path):
    from test_research_default_protocol import synthetic_artifacts
    root = campaign(tmp_path)
    artifact = write(root/'census.json', synthetic_artifacts(root)['limitation_census'])
    authorize(root, protocol.stage_action('limitation_census', artifact))
    prepared = protocol.prepare_stage(root, 'limitation_census', artifact, root/'review', model='gpt-5')
    assert not prepared['execution_authorized']
    assert not (root/science.APPROVAL).exists()


@pytest.mark.parametrize('damage', ['missing', 'forged', 'stale'])
def test_dispatch_proposal_never_reserves_without_exact_registered_authority(tmp_path, damage):
    from ravel.workflow import research_evaluation as evaluation
    root = campaign(tmp_path)
    case = json.loads((Path(__file__).parents[1]/'fixtures/research_full_cycle/case.json').read_text())
    preregistration = write(root/'negative-control-preregistration.json', {
        'schema_version': 1, 'kind': 'research-preregistration',
        'selection_rule': case['selection_rule'], 'stop_rule': case['stop_rule'],
        'approximations': [], 'withheld_cells': [],
        'expected_effect': {'statement': 'Unexecuted negative exposure control.'},
        'evaluator_not_applicable': {key: 'No scientific execution in this negative control.'
            for key in ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}})
    protocol.preregister(root, preregistration, {}, evaluation_harness=True)
    population = write(root/'population.json', {'ids': ['inert-event']})
    study = write(root/'prospective-study.json', {'fixture': 'Unexecuted negative exposure control.'})
    _, state = cycle._load(root)
    # A disclosed prospective-only negative fixture supplies no stage completion,
    # worker, execution, acceptance, dispatch reservation or decision receipt.
    state['experiments'].append({'id': 'unissued', 'study': study, 'plan': None,
        'input_pins': [population], 'observation': None,
        'evaluation': {'candidate': 'inert', 'family': 'inert', 'round': 1,
            'purpose': 'full', 'cells': ['inert'], 'seeds': ['inert'], 'generation': 'inert',
            'population_pins': [population], 'value_pointer': '/value'}})
    cycle._commit(root, state, 'fixture_unissued_exposure_negative_control')
    before = cycle._load(root)[1]
    action = evaluation.prepare_dispatch_action(root, 'unissued')
    assert action['kind'] == 'screening_choice' and action['digest'] == action['pins'][0]['sha256']
    assert cycle._load(root)[1] == before
    if damage == 'forged':
        write(root/'rdj/receipts/forged-dispatch.json', {'outcome': 'authorize', 'action_digest': action['digest']})
    elif damage == 'stale':
        Path(action['pins'][0]['path']).write_text('{"forged":"replacement proposal"}\n')
    with pytest.raises(ValueError, match='rdj_|prospective dispatch action'):
        evaluation.dispatch(root, before, 'unissued')
    assert cycle._load(root)[1] == before
    assert not any(e['kind'] in {'research_adaptive_read', 'research_confirm_read',
        'ordinary_study_dispatch_boundary'} for e in before['events'])


def test_resume_action_requires_original_parent_decision_and_current_response(tmp_path):
    from ravel.workflow import research_orchestrator as orchestrator
    root = campaign(tmp_path)
    parent = tmp_path/'parent'
    satisfy_initial_staffing(parent, campaign_root=root)
    pin = write(root/'outside-response.json', {'observed': 'bounded outside work completed'})
    response = {'response': {k: pin[k] for k in ('path', 'sha256')}}
    action = orchestrator.delivery_action(root, '1'*64, response)
    check = orchestrator.campaign_gates(root, parent)
    assert any(error.provider == 'rdj' for error in check(root, 'research_choice', action))
    authorize(parent, action)
    assert check(root, 'research_choice', action) == []
    document = json.loads(Path(action['pins'][0]['path']).read_text())
    assert document['execution_authorized'] is False
    assert document['approval_from_resume'] is False
    Path(pin['path']).write_text('{}\n')
    with pytest.raises(ValueError, match='response pin changed'):
        orchestrator.delivery_action(root, '1'*64, response)


@pytest.mark.parametrize('decided', [False, True])
def test_stage_role_delivery_resumes_only_with_its_exact_pinned_decision(tmp_path, decided):
    """With the research loop's production gates, a stage resumes after outside role
    delivery only on a real decision in the original parent run."""
    from ravel.workflow import agent_host, graph_substrate, research_orchestrator as orchestrator
    from ravel.workflow.graphs import hosts, stage as stage_graph
    from test_research_default_protocol import synthetic_artifacts
    from test_research_full_cycle import deliver_stage, stage_settings
    root = campaign(tmp_path)
    parent = tmp_path/'parent'
    satisfy_initial_staffing(parent, campaign_root=root)
    gates = orchestrator.campaign_gates(root, parent)
    artifact = write(root/'census.json', synthetic_artifacts(root)['limitation_census'])
    authorize(root, protocol.stage_action('limitation_census', artifact))
    out = root/'coordinator/stages/limitation_census'
    instance = {'campaign': 'stage-delivery-control', 'request': protocol.ce.digest('limitation_census')}
    with hosts(agent_host.AgentHost()) as key:
        request = stage_graph.request(artifact=artifact, out=out, settings=stage_settings(), host_key=key,
                                      operation_sha256='0'*64)
        seen = graph_substrate.run(root, stage_graph.GRAPH_ID, instance, input={'stage_request': request},
                                   gate_check=gates)
        assert [item['kind'] for item in seen['interrupts']] == ['external_delivery'], seen
        item = seen['interrupts'][0]
        deliver_stage(out/'graph')
        response = {'response': {k: v for k, v in cycle._pin(root/'head.json').items() if k != 'size'}}
        action = orchestrator.stage_delivery_action(root, item['payload']['payload'], response)
        assert Path(action['pins'][0]['path']).parent == parent/'inputs/research-deliveries'
        document = json.loads(Path(action['pins'][0]['path']).read_text())
        assert document['stage'] == 'limitation_census' and document['response']['sha256'] == response['response']['sha256']
        assert document['execution_authorized'] is False and document['approval_from_resume'] is False
        pending = item['payload']['payload']
        for damaged in ({**pending, 'stage': 'ideas'}, {**pending, 'graph_root': str(tmp_path/'foreign/graph')},
                        {**pending, 'injected': True}):
            with pytest.raises(ValueError, match='stage delivery'):
                orchestrator.stage_delivery_action(root, damaged, response)
        if decided:
            authorize(parent, action)
        result = graph_substrate.respond(root, stage_graph.GRAPH_ID, instance, {item['id']: response},
                                         gate_check=gates)
    stage = protocol.methodology_status(root)['record']['stages'][0]
    if decided:
        assert result['terminal'] is None and result['next'] == [], result
        assert stage['status'] == 'done'
    else:
        assert result['terminal']['reason'] == 'stage_delivery_gate_refused', result
        assert stage['status'] == 'running' and not stage.get('worker_receipts')
