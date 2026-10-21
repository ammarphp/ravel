"""Deterministic envelope compiler and complete generic route-seat coverage."""
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest

from ravel.controller.engagement import policy
from ravel.controller.engagement.records import data, digest, EngagementRefused

ROOT=Path(__file__).parents[3]

def load(name,path):
    spec=spec_from_file_location(name,path);module=module_from_spec(spec);spec.loader.exec_module(module);return module

fakes=load('p18_build_fakes',ROOT/'tests/fixtures/engagement/fakes.py')
builder=load('p18_builder',ROOT/'scripts/maintenance/build_engagement_envelopes.py')


def fixture_build():
    plan=fakes.fictional_plan();plan['id']='study'
    return [plan], fakes.cards(), fakes.policy_for(plan)


def test_envelope_build_byte_identical_all_tier_bounds():
    specs,cards,rules=fixture_build()
    args=dict(cards=cards,instructions=fakes.FakeInstructions,policy=rules,calibration=data('calibration.json'),source_pins={'catalogue':digest('catalogue')})
    first=builder.build(specs,**args)
    assert builder.encode(first)==builder.encode(builder.build(specs,**args))
    for tier,entry in first['routes']['study'].items():
        for metric in ('sessions','calls','input_tokens','output_tokens','cost_usd'):
            assert entry['floor'][metric]<=entry['low'][metric]<=entry['high'][metric]
        assert len(first['packets']['study'][tier]) >= entry['floor']['sessions']
    assert first['routes']['study']['lean']['floor']['sessions'] < first['routes']['study']['full']['floor']['sessions']


def test_envelope_build_check_detects_route_catalogue_and_calibration_drift(monkeypatch,tmp_path):
    specs,cards,rules=fixture_build()
    fakes.install_fakes(monkeypatch,cards_override=cards)
    monkeypatch.setattr(builder,'load_policy',lambda:rules)
    monkeypatch.setattr(builder,'role_cards',lambda:cards)
    pins={'catalogue':digest('first')}
    monkeypatch.setattr(builder,'source_inventory',lambda path:deepcopy(pins))
    routes=tmp_path/'routes';routes.mkdir()
    path=routes/'study.json';path.write_text(json.dumps(specs[0]))
    target=tmp_path/'envelopes.json'
    args=['--routes',str(routes),'--out',str(target)]
    assert builder.main(args)==0
    original=target.read_bytes()
    assert builder.main(args+['--check'])==0
    # A route metadata change changes provenance even if its seat count does not.
    doc=json.loads(path.read_text());doc['version']=2;path.write_text(json.dumps(doc))
    assert builder.main(args+['--check'])==1 and target.read_bytes()==original
    path.write_text(json.dumps(specs[0]))
    pins['catalogue']=digest('second')
    assert builder.main(args+['--check'])==1
    pins['catalogue']=digest('first')
    assert builder.main(args+['--check'])==0
    # Calibration participates directly in the generated content digest.
    cal=data('calibration.json');cal['parameters']['low']['S']+=1
    changed=builder.build(specs,cards=cards,instructions=fakes.FakeInstructions,policy=rules,calibration=cal,source_pins=pins)
    old=builder.build(specs,cards=cards,instructions=fakes.FakeInstructions,policy=rules,calibration=data('calibration.json'),source_pins=pins)
    assert changed['sha256']!=old['sha256']


def test_EG03_policy_coverage_unknown_seat_fails_build():
    specs,cards,rules=fixture_build()
    specs[0]['steps'][0]['review'].append('trap-auditor')
    with pytest.raises(EngagementRefused,match='unclassified seat kept'):
        builder.build(specs,cards=cards,instructions=fakes.FakeInstructions,policy=rules,calibration=data('calibration.json'),source_pins={})


def test_EG03_every_current_route_declared_and_reviewed_by_seat_has_policy():
    rules=policy.load_policy();cards=policy.role_cards()
    snapshots=json.loads((ROOT/'tests/fixtures/engagement/route-seats.json').read_text())
    installed,_=builder.route_specs(ROOT/'src/ravel/data/controller/routes')
    for plan in snapshots+installed:
        route=(plan.get('route') or {}).get('id',plan.get('id'))
        entries=rules['seat_plans'][route]
        for seat in policy.declared_seats(plan,cards):
            assert seat['key'] in entries, (route,seat['key'])
            assert set(entries[seat['key']])=={'lean','standard','full'}
            assert all(v=='keep' or v.startswith(('fold:','dedup:')) for v in entries[seat['key']].values())


@pytest.mark.parametrize('selected',['lean','standard','full'])
def test_EG03_EG04_JR09_every_route_floors_and_duty_equality(monkeypatch,selected):
    snapshots=json.loads((ROOT/'tests/fixtures/engagement/route-seats.json').read_text())
    real=policy.role_cards()
    # Fake packets use actual role identities/reviewers with fictional duty text.
    cards={name:{'id':card['id'],'purpose':'Trace the fictional evidence.','protocol':['Check the source.'],
                 'must_check':['check:fixture'],'must_read':['fixture:source'],
                 'reviewed_by':card.get('reviewed_by',[]),'independence':{},'knowledge':{},'sees':{}}
           for name,card in real.items()}
    fakes.install_fakes(monkeypatch,cards_override=cards)
    for plan in snapshots:
        full=policy.seat_plan(plan,'full',cards=cards,instructions=fakes.FakeInstructions)
        result=policy.seat_plan(plan,selected,cards=cards,instructions=fakes.FakeInstructions)
        assert not result['errors'],(plan['id'],result['errors'])
        if plan['id'] in ('inspect','legacy'):
            assert result['seats']==[];continue
        assert 'checkin1' in result['authority_nodes']
        assert 'checkin:checkin1:plan-critic' in result['bindings']
        assert result['attacks_required']==3
        assert set(result['claim_coverage'])=={'claim-1'}
        def items(seats):return {i['id'] for s in seats if not s['conditional'] for i in s['items']}
        assert items(result['seats'])==items(full['seats'])


def test_envelope_build_missing_peers_are_unavailable_not_zero_success():
    result=builder.build([],cards={},instructions=None,policy=policy.load_policy(),calibration=data('calibration.json'),source_pins={})
    assert result['status']=='unavailable' and result['routes']=={} and result['reason']


def test_EG03_dynamic_judgment_uses_explicit_review_role_classes(monkeypatch):
    fakes.install_fakes(monkeypatch)
    plan=fakes.fictional_plan(route='judgment')
    result=policy.seat_plan(plan,'standard',cards=fakes.cards(),instructions=fakes.FakeInstructions)
    assert result['errors']==[]
    assert result['attacks_required']==3 and result['claim_coverage']


def test_envelope_build_conditional_consults_keep_packet_accounting_without_floor_inflation():
    specs,cards,rules=fixture_build()
    args=dict(cards=cards,instructions=fakes.FakeInstructions,policy=rules,
              calibration=data('calibration.json'),source_pins={})
    baseline=builder.build(specs,**args)
    cards['generator']['knowledge']['consult']=[
        {'when':'failure','role':'trap-auditor'},
        {'when':'failure','role':'trap-auditor'},
        {'when':'before_first_smoke','role':'figure-critic'},
    ]
    result=builder.build(specs,**args)
    for tier in ('lean','standard','full'):
        sessions=[s for s in result['packets']['study'][tier] if s['category']=='consult']
        assert len(sessions)==2 and all(s['conditional'] and s['packet_tokens']>0 for s in sessions)
        before,after=baseline['routes']['study'][tier],result['routes']['study'][tier]
        mandatory=builder.project([s for s in result['packets']['study'][tier] if s['category']!='consult'],args['calibration'])
        assert after['floor']==mandatory['floor'] and after['low']==mandatory['low']
        assert after['floor']['sessions']==before['floor']['sessions']
        assert after['central']['sessions']==before['central']['sessions']+2
        assert after['high']['input_tokens']>before['high']['input_tokens']
    cards['generator']['knowledge']['consult'][0]['when']='unregistered'
    with pytest.raises(EngagementRefused,match='unclassified consult trigger'):
        builder.build(specs,**args)
