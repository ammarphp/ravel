"""Controller binding doubles exercise decisions, escalation, gates and receipts."""
from copy import deepcopy
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import ravel.controller.engagement as engagement
from ravel.controller.engagement import facts, policy
from ravel.controller.engagement.records import DECISION, ESCALATION, EngagementRefused, data, digest, rows

_SPEC=spec_from_file_location('p18_record_fakes',Path(__file__).parents[2]/'fixtures/engagement/fakes.py')
fakes=module_from_spec(_SPEC);_SPEC.loader.exec_module(fakes)


def setup(monkeypatch, tmp_path, *, config=None):
    fakes.install_fakes(monkeypatch,operator=config or {})
    plan=fakes.fictional_plan()
    installed=fakes.policy_for(plan)
    monkeypatch.setattr(policy,'load_policy',lambda:deepcopy(installed))
    store=fakes.FakeRunStore(root=tmp_path)
    store.append('plan',{'plan':plan,'plan_sha256':plan['sha256']})
    store.append('route',{'route':'study'})
    store.append('engagement-population',{'plan_sha256':plan['sha256'],'deliverable_ids':[d['id'] for d in plan['deliverables']]})
    method=json.loads((Path(__file__).parents[2]/'fixtures/method_decisions/standard_table.json').read_text())
    for kind,body in [('engagement-method',{'method':method,'scan_points':1}),('engagement-novelty',{'value':'N0'})]:
        store.append(kind,body)
        store.append('engagement-fact-credit',{'credited':True,'role':'plan-critic','subject_sha256':digest(body),'plan_sha256':plan['sha256']})
    store.append('engagement-special',{'plan_sha256':plan['sha256'],'complete':True,'flags':[]})
    expected={'status':'ready','floor':{'sessions':1},
              'low':{'sessions':1,'calls':1,'input_tokens':80,'output_tokens':0,'cost_usd':0},
              'high':{'sessions':100,'calls':10000,'input_tokens':100000,'output_tokens':100000,'cost_usd':100}}
    original_data=engagement.data
    monkeypatch.setattr(engagement,'data',lambda name: {'policy_sha256':installed['sha256'],'calibration_sha256':digest(data('calibration.json')),'routes':{'study':{t:deepcopy(expected) for t in ('lean','standard','full')}}} if name=='envelopes.json' else original_data(name))
    fakes.projection_inputs(monkeypatch, engagement, installed)
    return store,plan,installed


def dispatch(store,plan,decision):
    # Fake P04 dispatches each required policy seat and producers. No preaccepted fixture labels.
    applied=engagement.apply(plan,decision)
    roles=[('producer:'+s['id'], 'producer') for s in applied['steps']]
    roles += [(s['key'],'review') for s in decision['seat_plan']['seats'] if not s['conditional']]
    for index,(name,purpose) in enumerate(roles):
        base={'node_id':name,'step_id':name,'seat':purpose,'attempt':1}
        packet=digest({'node':name})
        store.append('step-dispatch',{**base,'purpose':purpose,'packet_sha256':packet,'packet_tokens':100})
        store.append('step-observation',{**base,'session_id':f'session-{index}','status':'completed',
                                        'usage':{'reported':True,'turns':2,'input_tokens':100,'output_tokens':10,'cost_usd':.01}})
        store.append('instruction-delivery',{**base,'kind':'instruction-delivery-session','session':f'session-{index}',
                                            'packet_sha256':packet,'packet_tokens':100})
    return applied


def test_decision_uses_the_frozen_run_configuration(monkeypatch, tmp_path):
    store, plan, _ = setup(monkeypatch, tmp_path)
    import ravel.controller.authority as authority
    monkeypatch.setattr(authority, 'frozen', lambda store, required=False:
                        {'engagement': {'minimum_tier': 'full'}, 'budgets': {}})

    def live_configuration():
        raise AssertionError('a frozen run must not read live operator configuration')

    monkeypatch.setattr(engagement, '_operator', live_configuration)
    assert engagement.decide(store, {'plan': plan})['tier'] == 'full'


@pytest.mark.parametrize('selected', ['full', 'standard', 'lean'])
def test_applied_plan_materialises_in_the_real_ledger(monkeypatch, tmp_path, selected):
    from ravel.controller import ledger
    from ravel.controller.ledger import state as ledger_state
    from ravel.controller.store import RunStore

    store, plan, installed = setup(monkeypatch, tmp_path, config={'engagement': {'minimum_tier': selected}})
    import ravel.controller.instructions as instructions
    calls = []
    build = instructions.manifest

    def manifest(step, card):
        calls.append(deepcopy(card))
        return build(step, card)

    monkeypatch.setattr(instructions, 'manifest', manifest)
    full = policy.seat_plan(plan, 'full', installed, cards=fakes.cards(), instructions=instructions)
    decision = engagement.decide(store, {'plan': plan})
    applied = engagement.apply(plan, decision)
    real = RunStore('fictional-run', root=tmp_path / 'store')
    try:
        ledger.materialise(real, 'intake', {'run_id': real.run_id, 'route': 'study'})
        assert ledger.materialise(real, 'plan', applied)
        normal = ledger_state.load(real, full=True).plan
        for step, actual in zip(applied['steps'], normal['steps']):
            assert {'seat': step['role'], 'role': step['role'], 'kind': 'producer'} in actual['seats']
            expected = [s for s in decision['seat_plan']['seats']
                        if s['step_id'] == step['id'] and s['category'] == 'step']
            assert step['engagement_seats'] == expected
            assert all(set(s) == {'seat', 'role', 'kind'} for s in step['seats'])
        assert ledger.verify(real)['verified']
    finally:
        ledger_state.forget(real)
    canonical = fakes.cards()
    for card in calls:
        assert json.dumps(card, sort_keys=True).encode() == json.dumps(canonical[card['id']], sort_keys=True).encode()
    active = {s['key']: s for s in decision['seat_plan']['seats'] if not s.get('conditional')}
    for source in full['seats']:
        target = active[decision['seat_plan']['bindings'][source['key']]]
        assert all(item in target['items'] for item in source['items'] if item['kind'] == 'duty')
        for field in ('forbidden_inputs', 'required_inputs', 'distinct_actor_from'):
            assert set(source['constraints'][field]) <= set(target['constraints'][field])
        for field in ('fresh_session', 'blind'):
            assert not source['constraints'][field] or target['constraints'][field]
    if selected != 'full':
        assert any(s['folded_roles'] for s in active.values())
    assert applied['sha256'] == plan['sha256']
    body = deepcopy(applied)
    pin = body['engagement'].pop('applied_sha256')
    assert pin == digest(body) and pin != plan['sha256']
    assert engagement.check_applied(applied, decision) == []
    assert engagement.apply(applied, decision) == applied
    changed = deepcopy(applied)
    changed['steps'][0]['role'] = 'other-role'
    assert engagement.check_applied(changed, decision)
    for field in ('applied_sha256', 'policy_sha256', 'seat_plan_sha256'):
        changed = deepcopy(applied)
        changed['engagement'][field] = '0' * 64
        assert engagement.check_applied(changed, decision)
    changed = deepcopy(applied)
    changed['engagement']['seat_plan']['seats'][0]['items'] = []
    assert engagement.check_applied(changed, decision)
    changed = deepcopy(applied)
    changed['steps'][0]['correction_rounds'] += 1
    assert engagement.check_applied(changed, decision)


def test_folded_step_keeps_real_instruction_card_pin():
    from ravel.controller.instructions import delivery, reviewer_items
    from ravel.workflow.role_registry import load

    card, folded = load('skeptical-verifier'), load('object-selection-mapper')
    step = {'id': 'final-review', 'kind': 'review', 'role': card['id']}
    source = {'id': 'source-review', 'kind': 'review', 'role': folded['id']}
    manifests = [delivery.manifest(step, card), delivery.manifest(source, folded)]
    items = reviewer_items(manifests[0], card) + reviewer_items(manifests[1], folded)
    seat = {'step': step, 'card': card, 'folded_cards': [folded], 'manifests': manifests,
            'items': items, 'constraints': policy._constraints(card)}
    packed_step = policy._packet_step(seat, policy.load_policy()['packet_scope']['lean'])
    manifest = delivery.manifest(packed_step, card)
    packet = delivery.packet(manifest, card, packed_step, [])
    expected = deepcopy(manifests[0]['units'])
    seen = {u['id'] for u in expected}
    for unit in manifests[1]['units']:
        if unit['id'] not in seen:
            expected.append({**unit, 'via': 'folded'})
            seen.add(unit['id'])
    assert manifest['units'] == expected
    assert manifest['role'] == manifests[0]['role'] == card['id']
    assert manifest['catalogue_sha256'] == manifests[0]['catalogue_sha256']
    assert json.dumps(card, indent=1, sort_keys=True, ensure_ascii=False) in packet['text']
    rendered = json.loads(packet['text'].split('== Step specification (step.v1) ==\n', 1)[1].split('\n\n== ', 1)[0])
    assert rendered['id'] == packed_step['id'] and rendered['role'] == card['id']
    assert [i['id'] for i in rendered['engagement']['items']] == [i['id'] for i in items]
    assert [m['sha256'] for m in rendered['engagement']['folded_manifests']] == [manifests[1]['sha256']]
    assert packed_step['engagement']['items'] == items
    assert packed_step['engagement']['folded_cards'] == [folded]
    assert packed_step['engagement']['folded_manifests'] == manifests[1:]
    assert delivery.check_packet(packet, manifest, card, packed_step, []) == []
    with pytest.raises(delivery.PacketRefused, match='not in the installed catalogue'):
        delivery.manifest(packed_step, {**card, 'folded_cards': [folded]})


def test_EG01_EG02_records_sources_determinism_and_chain(monkeypatch,tmp_path):
    store,plan,installed=setup(monkeypatch,tmp_path)
    first=engagement.decide(store,{'plan':plan,'tier':'full'})
    second=engagement.decide(store,{'plan':plan,'tier':'lean'})
    assert first==second and first['tier']=='lean'
    assert len(store.scan(DECISION))==1
    assert all(r['source'] and r['checker'].startswith('code') for r in first['reasons'])
    Draft202012Validator(data('schemas/engagement-decision.v1.json')).validate({k:v for k,v in first.items() if k!='record_id'})
    previous=None
    for entry in store.entries:
        assert entry['prev']==previous
        assert entry['digest']==digest({k:v for k,v in entry.items() if k!='digest'})
        previous=entry['digest']
    # A newer uncredited assertion cannot reuse credit over old bytes.
    store.append('engagement-novelty',{'value':'N0','extra':'changed'})
    assert engagement.decide(store,{'plan':plan})['tier']=='full'


def test_EG02_population_and_plan_pins_cannot_be_replaced(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    store.append('engagement-population',{'plan_sha256':plan['sha256'],'deliverable_ids':['claim-1']})
    assert engagement.decide(store,{'plan':plan})['tier']=='full'
    store.append('plan',{'plan':{**plan,'deliverables':[]},'plan_sha256':plan['sha256']})
    with pytest.raises(EngagementRefused,match='digest'):
        engagement.decide(store,{'plan':plan})


def test_EG02_binding_plan_blob_is_verified(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    raw=json.dumps(plan).encode();pin=sha256(raw).hexdigest()
    store.path('blobs').mkdir();store.path('blobs',pin).write_bytes(raw)
    store.append('plan',{'blob':pin,'plan_sha256':plan['sha256']})
    assert engagement.decide(store,{})['tier']=='lean'
    store.path('blobs',pin).write_bytes(b'{}')
    with pytest.raises(EngagementRefused,match='blob digest'):
        engagement.decide(store,{})


def test_EG03_fake_typed_checkin_and_seat_gate(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    decision=engagement.decide(store,{'plan':plan})
    checkin={'engagement':decision,'pins':{'engagement_sha256':decision['sha256']}}
    assert checkin['engagement']['facts'] and checkin['pins']['engagement_sha256']
    applied=engagement.apply(plan,decision)
    assert applied['sha256']==plan['sha256'] and applied!=plan
    assert engagement.check_applied(applied,decision)==[]
    assert engagement.apply(applied,decision)==applied
    applied['checkins'][0]['seats']=[]
    assert engagement.check_applied(applied,decision)
    changed=deepcopy(decision);changed['seat_plan']['seats'].pop()
    with pytest.raises(EngagementRefused,match='digest'):
        engagement.apply(plan,changed)


@pytest.mark.parametrize('trigger,event,new,rereview',[
    ('E1',{'validation_failed':True,'retry_exhausted':True},'standard',True),
    ('E2',{'review':{'verdict':'revise'}},'standard',True),
    ('E2',{'review':{'verdict':'unresolved'}},'standard',True),
    ('E2',{'review':{'credited':False}},'standard',True),
    ('E2',{'review':{'items':[{'status':'failed'}]}},'standard',True),
    ('E3',{'outside_tolerance':True},'standard',True),
    ('E3',{'decomposition_opened':True},'standard',True),
    ('E3',{'anchor_mismatch':True},'standard',True),
    ('E4',{'escalation':'checkin_flag'},'standard',True),
    ('E4',{'escalation':'decision_block'},'standard',True),
    ('E4',{'escalation':'new_experiment_required'},'standard',True),
    ('E4',{'escalation':'stop'},'standard',True),
    ('E4',{'deviation':True},'standard',True),
    ('E4',{'replan':True},'standard',True),
    ('E4',{'status':'held'},'standard',True),
    ('E4',{'ledger_class_violation':'L'},'standard',True),
    ('E4',{'envelope_status':'below_floor','completed':True},'standard',True),
    ('E5',{'new_consequence':'R2'},'standard',True),
    ('E6',{'new_consequence':'R3'},'full',True),
    ('E7',{'mechanical_retry_passed':True},'lean',False),
    ('E8',{'cost_usd':3,'expected_cost_usd':1},'lean',False),
])
def test_EG05_every_escalation_is_recorded(monkeypatch,tmp_path,trigger,event,new,rereview):
    store,plan,_=setup(monkeypatch,tmp_path)
    engagement.decide(store,{'plan':plan})
    event={**event,'evidence':'outcome:1','step_id':'s1','subject_sha256':digest('subject')}
    record=engagement.observe(store,event)
    assert record['triggers']==[trigger] and record['new_tier']==new
    assert record['rereview'] is rereview
    assert record['plan_deviation'] is False and record['seat_addition_class']=='R1'
    assert engagement.observe(store,event)==record  # graph replay is idempotent
    assert len(store.scan(ESCALATION))==1
    assert record['requires_rdj'] is (trigger=='E5')
    assert record['requires_authority'] is (trigger=='E6')
    Draft202012Validator(data('schemas/engagement-escalation.v1.json')).validate({k:v for k,v in record.items() if k!='record_id'})


def test_EG05_V06_second_mechanical_retry_is_step_scoped_and_corrections_bounded(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    engagement.decide(store,{'plan':plan})
    for index in range(2):
        result=engagement.observe(store,{'mechanical_retry_passed':True,'step_id':'s1','evidence':f'retry:{index}'})
    assert result['new_tier']=='standard' and result['scope']=='step' and result['rereview']
    assert engagement.tier(store)=='lean'
    first=engagement.observe(store,{'review':{'verdict':'revise'},'step_id':'s2','evidence':'finding:1'})
    second=engagement.observe(store,{'review':{'verdict':'revise'},'step_id':'s2','evidence':'finding:2'})
    assert first['new_tier']=='standard' and not first['correction_exhausted']
    assert second['new_tier']=='full' and second['correction_exhausted']
    assert second['correction_bound']==1
    assert first['record_id']!=second['record_id']
    assert [r['correction_count'] for r in rows(store,ESCALATION) if 'E2' in r['triggers']]==[1,2]


def test_EG06_EG12_only_authority_raises(monkeypatch,tmp_path):
    monkeypatch.setenv('RAVEL_ENGAGEMENT_TIER','lean')
    (tmp_path/'engagement.json').write_text('{"tier":"lean"}')
    store,plan,_=setup(monkeypatch,tmp_path)
    store.append('worker-output',{'tier':'full'})
    assert engagement.decide(store,{'plan':plan,'engagement':{'tier':'full'}})['tier']=='lean'
    store.append('authority',{'uid':'human-raise','kind':'approve_plan','authorizes_effects':True,'label':'human','subject':{'pins':{'plan_sha256':plan['sha256']}}})
    store.append('engagement-raise',{'plan_sha256':plan['sha256'],'channel':'terminal','authority_record_id':'human-raise','tier':'full'})
    assert engagement.decide(store,{'plan':plan})['tier']=='full'
    store.append('engagement-raise',{'plan_sha256':plan['sha256'],'channel':'terminal','authority_record_id':'human-raise','tier':'lean'})
    # A later lower "raise" has no effect and does not abort the CHECK-IN 1 decision.
    assert engagement.decide(store,{'plan':plan})['tier']=='full'


def test_EG06_operator_cannot_lower_unknown_facts(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path,config={'engagement':{'minimum_tier':'standard'}})
    store.append('engagement-novelty',{'value':'N0','not_credited':True})
    # A standing operator minimum below the computed tier is refused as a lowering, never as a run abort.
    decision=engagement.decide(store,{'plan':plan})
    assert decision['computed_tier']=='full' and decision['tier']=='full'
    assert decision['operator_minimum']=='standard'


def test_EG06_invalid_operator_minimum_is_refused(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path,config={'engagement':{'minimum_tier':'minimal'}})
    with pytest.raises(EngagementRefused,match='tier'):
        engagement.decide(store,{'plan':plan})


def test_EG08_EG11_fake_sink_refuses_missing_seat_and_renders_receipt(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    decision=engagement.decide(store,{'plan':plan})
    dispatch(store,plan,decision)
    check=engagement.check_envelope(store,'deliver')
    assert check['status']=='ok'
    section=engagement.receipt_section(store)
    assert section['accepted_allowed'] and section['envelope_checks']
    assert section['seat_plan_sha256']==decision['seat_plan_sha256']
    store.append('step-dispatch',{'node_id':'missing','step_id':'missing','seat':'review','attempt':1})
    engagement.check_envelope(store,'wave')
    check=engagement.check_envelope(store,'deliver')
    section=engagement.receipt_section(store)
    assert check['status']=='below_floor' and not section['accepted_allowed']
    assert not section['architecture_complete_allowed']
    assert 'ENGAGEMENT BELOW FLOOR' in section['labels']
    Draft202012Validator(data('schemas/envelope-check.v1.json')).validate({k:v for k,v in check.items() if k!='record_id'})


def test_EG11_receipt_cannot_reuse_check_after_new_dispatch(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    decision=engagement.decide(store,{'plan':plan});dispatch(store,plan,decision)
    engagement.check_envelope(store,'deliver')
    assert engagement.receipt_section(store)['accepted_allowed']
    store.append('step-dispatch',{'node_id':'later','step_id':'later','seat':'review','attempt':1})
    assert not engagement.receipt_section(store)['accepted_allowed']


def test_EG05_EG11_step_raise_invalidates_delivery_and_reports_effective_seats(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    decision=engagement.decide(store,{'plan':plan});dispatch(store,plan,decision)
    engagement.check_envelope(store,'deliver')
    assert engagement.receipt_section(store)['accepted_allowed']
    for index in range(2):
        engagement.observe(store,{'mechanical_retry_passed':True,'step_id':'s1','evidence':f'retry:{index}'})
    assert engagement.tier(store)=='lean'
    section=engagement.receipt_section(store)
    assert not section['accepted_allowed']
    assert section['seat_plan_sha256']==engagement.effective_decision(store)['seat_plan_sha256']
    assert section['seat_plan_sha256']!=decision['seat_plan_sha256']


def test_EG06_resume_cannot_reinterpret_frozen_policy(monkeypatch,tmp_path):
    store,plan,installed=setup(monkeypatch,tmp_path)
    decision=engagement.decide(store,{'plan':plan})
    changed=deepcopy(installed);changed['packet_scope']['lean']['inline_context_tokens']=1
    changed['sha256']=digest({k:v for k,v in changed.items() if k!='sha256'})
    monkeypatch.setattr(policy,'load_policy',lambda:changed)
    with pytest.raises(EngagementRefused,match='policy changed'):
        engagement.apply(plan,decision)
    with pytest.raises(EngagementRefused,match='policy changed'):
        engagement.effective_decision(store)


def test_EG04_JR09_folded_verdicts_and_tested_attacks_required(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    decision=engagement.decide(store,{'plan':plan})
    seat=next(s for s in decision['seat_plan']['seats'] if s.get('attacks_required'))
    record={'item_verdicts':[{'item':i['id'],'verdict':'pass','evidence':'outputs/result#/value'} for i in seat['items']],
            'attacks':[{'id':f'a{i}','attack':'Probe the declared bound.','test':'Compare the supplied counterexample.',
                        'evidence':'outputs/check#/result','before_verdict':True} for i in range(3)]}
    assert policy.review_errors(seat,record)==[]
    record['item_verdicts'].pop();record['attacks'][0]['before_verdict']=False
    assert len(policy.review_errors(seat,record))==2


def test_EG03_standard_decider_is_conditioned_on_credited_same_subject_verdicts(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path,config={'engagement':{'minimum_tier':'standard'}})
    decision=engagement.decide(store,{'plan':plan});seats=decision['seat_plan']['seats']
    agreed={'credited':True,'verdict':'accept','subject_sha256':digest('subject')}
    selected=policy.conditional_seats(seats,{'attacker':agreed,'verifier':agreed})
    assert not any(s['conditional'] for s in selected)
    assert any(s['conditional'] for s in policy.conditional_seats(seats,{}))
    mismatch={**agreed,'verdict':'revise'}
    assert any(s['conditional'] for s in policy.conditional_seats(seats,{'attacker':agreed,'verifier':mismatch}))


def test_EG05_effective_decision_applies_monotone_future_seats(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    original=engagement.decide(store,{'plan':plan})
    engagement.observe(store,{'new_consequence':'R2','step_id':'s2','evidence':'class:1'})
    effective=engagement.effective_decision(store)
    assert effective['tier']=='standard'
    assert original['tier']=='lean' and rows(store,DECISION)[0]['tier']=='lean'
    applied=engagement.apply(plan,effective)
    assert engagement.gate_errors(store,'checkin1->execute',plan=applied)==[]
    assert applied['sha256']==plan['sha256']
    assert engagement.gate_errors(store,'deliver[accepted]')


def test_EG02_fact_credit_names_exact_reviewed_bytes(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    items=facts.pin_inputs(store,plan,{'deliverables':plan['deliverables']},{},
                          method=json.loads((Path(__file__).parents[2]/'fixtures/method_decisions/standard_table.json').read_text()),
                          novelty='N0',parent='none')
    review={'plan_sha256':plan['sha256'],'seats':{'plan-critic':{'credited':True,'verdict':'accept'}},
            'engagement_fact_sha256s':[i['subject_sha256'] for i in items]}
    uid=store.append('review',review)
    assert len(facts.credit_reviewed_facts(store,plan,uid))==2
    assert engagement.decide(store,{'plan':plan})['tier']=='lean'
    store.append('engagement-novelty',{'value':'N0','plan_sha256':plan['sha256'],'changed':True})
    assert facts.credit_reviewed_facts(store,plan,uid)  # only unchanged method can be credited
    assert engagement.decide(store,{'plan':plan})['tier']=='full'


def test_a_failed_current_method_collection_invalidates_prior_credit(monkeypatch, tmp_path):
    store, plan, _ = setup(monkeypatch, tmp_path)
    assert engagement.decide(store, {'plan': plan})['tier'] == 'lean'
    facts.pin_inputs(store, plan, {'deliverables': plan['deliverables']}, {},
                     method=None, novelty='N0', parent='none')
    current, _ = facts.collect(store, {'plan': plan}, policy.load_policy())
    assert current['compute']['value'] is None
    assert engagement.decide(store, {'plan': plan})['computed_tier'] == 'full'


def test_EG10_stale_calibration_projection_cannot_buy_approval(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    get_data=engagement.data
    def stale(name):
        value=deepcopy(get_data(name))
        if name=='envelopes.json':value['calibration_sha256']='0'*64
        return value
    monkeypatch.setattr(engagement,'data',stale)
    result=engagement.decide(store,{'plan':plan})
    assert result['projected_envelope'] is None
    assert result['budget_authority']['class']=='R3'
    assert result['tier']=='lean'  # a missing cost model does not reduce or inflate review


def test_EG13_apply_keeps_preapproval_packet_and_round_scope(monkeypatch,tmp_path):
    store,plan,_=setup(monkeypatch,tmp_path)
    plan['steps'][0]['parameters']={'phase':'prepare'}
    plan['steps'][0]['correction_rounds']=3
    plan['sha256']=digest({k:v for k,v in plan.items() if k!='sha256'})
    store.append('plan',{'plan':plan,'plan_sha256':plan['sha256']})
    # Facts are now stale and force full; isolate the pure apply contract with a fresh lean decision.
    original=engagement.decide(store,{'plan':plan})
    original['tier']='lean';original['packet_scope']=policy.load_policy()['packet_scope']['lean'];original['correction_bound']=1
    original['sha256']=digest({k:v for k,v in original.items() if k not in ('sha256','record_id')})
    applied=engagement.apply(plan,original)
    assert applied['steps'][0]['engagement']['inline_context_tokens']==120000
    assert applied['steps'][0]['correction_rounds']==3
    assert applied['steps'][1]['engagement']['inline_context_tokens']==0


def test_template_seats_bind_through_the_compilers_template_id(monkeypatch):
    # A route step expanded per point keeps its template's id, so the seat rule declared for the template applies to
    # every expansion instead of each one being kept unclassified.
    from ravel.controller import routes
    instructions = fakes.install_fakes(monkeypatch)
    point = {'id': 'point', 'kind': 'operate', 'role': 'generator', 'review': ['physics-critic'], 'foreach': 'points',
             'inputs': [], 'outputs': [{'path': 'outputs/point-{item}.json', 'kind': 'artifact', 'required': True}],
             'depends_on': [], 'waypoint': False, 'rung': 'smoke', 'budget': {}, 'protocols': [],
             'instruction_sources': [], 'obligations': []}
    spec = {'schema_version': 1, 'kind': 'route-spec', 'id': 'fixture-points', 'version': 1,
            'title': 'fixture route with a per-point template',
            'match': {'row': 6, 'when': {'field': 'task_mode', 'eq': 'fictional-points'}},
            'admits_scientific_deliverables': True,
            'parameters': [{'name': 'points', 'from': 'contract:fictional_points', 'default': [{'id': 'a'}, {'id': 'b'}]}],
            'steps': [point], 'checkins': [{'id': 'checkin1', 'sections': ['plan'], 'seats': ['plan-critic']}],
            'obligations': ['ROUTE-fixture-points'], 'deliverables': []}
    plan = routes.compile(spec, {}, {})
    assert [(s['id'], s.get('template_id')) for s in plan['steps']] == [('point.a', 'point'), ('point.b', 'point')]
    installed = deepcopy(policy.load_policy())
    installed['seat_plans']['fixture-points'] = {
        'step:point:physics-critic': {'lean': 'tiered', 'standard': 'tiered', 'full': 'keep'},
        'step:point:object-selection-mapper': {'lean': 'tiered', 'standard': 'tiered', 'full': 'keep'},
        'checkin:checkin1:plan-critic': {'lean': 'keep', 'standard': 'keep', 'full': 'keep'}}
    installed['sha256'] = digest({k: v for k, v in installed.items() if k != 'sha256'})
    found = policy.seat_plan(plan, 'standard', installed, cards=fakes.cards(), instructions=instructions)
    assert not [e for e in found['errors'] if 'point.' in e], found['errors']
