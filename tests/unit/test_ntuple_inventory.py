"""Source-only ordinary adapter engineering harness; authority is mocked."""
import hashlib
import json
from pathlib import Path
import pytest
from ravel.physics import ntuple_inventory as h, columnar_ntuple_recipe as selection
from test_columnar_ntuple_recipe import recipe


def save(root, name, value):
    p=root/name;p.write_text(json.dumps(value,sort_keys=True));raw=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


ROSTER={'requirements':[{'id':'R%02d'%i} for i in range(1,6)],
        'target_families':['family_a','family_b','family_c'],
        'stages':['inventory','selection','background','validation','statistics','comparison','note']}


def plan_for(roster, prepared=('inventory','selection')):
    return {'schema_version':2,'stages':[{'id':x,'request':None,'missing':['not executed']} for x in roster['stages']],
            'prepared_stages':list(prepared),'target_families':list(roster['target_families']),
            'missing_scientific_inputs':['future signal payloads']}


def request(tmp_path, roster=None, portfolio=None):
    roster=ROSTER if roster is None else roster
    portfolio=plan_for(roster) if portfolio is None else portfolio
    root=tmp_path.resolve()/'inputs';root.mkdir()
    law=save(root,'source.json',{'scope':'fabricated conditional applicability'})
    r=recipe();r['sf_applicability'][0]['source']=law
    branches=[]
    for name in selection.required_branches(r):
        scalar=name in ('year','mcChannelNumber','weight_mc_NOSYS','weight_pileup_NOSYS','weight_beamspot') or name.startswith(('trigPassed_','metBaseline_'))
        dtype='uint32' if name in ('year','mcChannelNumber') else 'bool' if name.startswith('trigPassed_') else 'int8' if '_select_' in name else 'float32'
        branches.append({'name':name,'shape':'scalar' if scalar else 'jagged','dtype':dtype,'unit':'MeV' if name.endswith(('_pt_NOSYS','_met_NOSYS')) else '1'})
    d={'schema_version':1,'original_goal':save(root,'goal.json',{'whole_question':'fabricated engineering original'}),
       'goal_binding':{'contract':law,'assignment_id':'full-analysis'},
       'requirements':save(root,'requirements.json',roster),
       'inventory':save(root,'inventory.json',[{'did':'user.a:user.a.801174.file.root','guid':'6AFFAA85-1644-44AC-A7A7-3019A10A46FC','adler32':'ad:b29246d7','display_size':'3.678 GB','events':12345}]),
       'recipe':save(root,'recipe.json',r),'branches':save(root,'branches.json',branches),
       'resolved_members':None,'sample_definitions':None,'site_runtime':None,
       'review_policy':save(root,'policy.json',{'policy':{'claim_scopes':{'root-stream-delivery':{'actions':['delivery']}}}}),
       'assumptions':['Fabricated engineering source, no physics acceptance'],
       'portfolio':save(root,'portfolio.json',portfolio)}
    return {'request':save(root,'request.json',d)},root


def test_missing_external_inputs_do_not_drop_whole_question(tmp_path,monkeypatch):
    task,base=request(tmp_path)
    before={p:p.read_bytes() for p in base.iterdir()}
    monkeypatch.setattr(h,'_approved',lambda task,out:None) # explicitly no ordinary worker/approval claim
    out=tmp_path.resolve()/'new-output'
    result=h.run(task,base,out)
    assert result['status']=='passed' and result['execution_ready'] is False
    assert result['missing_external_inputs']==['resolved_members','sample_definitions','site_runtime']
    assert result['original_task_complete'] is False and result['fits']==0 and result['root_data_accesses']==0
    assert result['inventory_events_are_analysis_tree_entries'] is False
    assert len(result['remaining_stages'])==5 and result['inventory_files']==1
    assert all(p.read_bytes()==raw for p,raw in before.items())
    assert json.loads((out/'original-inventory.json').read_text())[0]['events']==12345
    assert (out/'kernel.py').is_file() and not (out/'root-science.json').exists()


def test_eight_bit_source_flags_and_fresh_input_custody(tmp_path):
    task,base=request(tmp_path)
    paths=h.inputs(task,base)
    assert base/'branches.json' in paths
    (base/'recipe.json').write_text('{}')
    with pytest.raises(ValueError):h.inputs(task,base)


def test_preparation_output_cannot_contaminate_input_tree(tmp_path,monkeypatch):
    task,base=request(tmp_path);monkeypatch.setattr(h,'_approved',lambda task,out:None)
    with pytest.raises(ValueError):h.run(task,base,base/'new-output')
    assert not (base/'new-output').exists()


def test_full_goal_binding_not_substituted(tmp_path):
    task,base=request(tmp_path)
    with pytest.raises(ValueError):h.goal_inputs({'schema_version':2,'task':task,'goal_binding':{'assignment_id':'different'}},base)


def test_source_context_reaches_existing_research_mode(tmp_path):
    task,base=request(tmp_path);ctx=h.context(task,base)
    assert ctx['next_ordinary_mode']=='ntuple-inventory' and ctx['downstream_mode']=='root-stream'
    assert ctx['original_task_complete'] is False and ctx['execution_authorized'] is False
    assert ctx['portfolio']['target_families']==ROSTER['target_families']


OTHER={'requirements':[{'id':'inventory-complete'},{'id':'blinded-selection'},{'id':'expected-limit'}],
       'target_families':['dark_photon_mumu','alp_photons'],
       'stages':['catalogue','cuts','fit','report']}


def test_supplied_roster_families_and_stages_drive_preparation(tmp_path,monkeypatch):
    task,base=request(tmp_path,OTHER,plan_for(OTHER,prepared=('catalogue',)))
    monkeypatch.setattr(h,'_approved',lambda task,out:None)
    result=h.run(task,base,tmp_path.resolve()/'out')
    assert [s['id'] for s in result['remaining_stages']]==['cuts','fit','report']
    ctx=h.context(task,base)
    assert ctx['portfolio']['target_families']==OTHER['target_families']
    assert [r['id'] for r in ctx['requirements_document']['requirements']]==['inventory-complete','blinded-selection','expected-limit']


def _fault(kind):
    roster=json.loads(json.dumps(OTHER));plan=plan_for(OTHER)
    if kind=='dropped-family':plan['target_families']=plan['target_families'][:1]
    elif kind=='extra-family':plan['target_families'].append('unrequested')
    elif kind=='reordered-stages':plan['stages'].reverse()
    elif kind=='dropped-stage':plan['stages'].pop()
    elif kind=='unknown-prepared':plan['prepared_stages']=['absent']
    elif kind=='no-prepared':plan['prepared_stages']=[]
    elif kind=='duplicate-requirement':roster['requirements'].append({'id':'fit'});roster['requirements'].append({'id':'fit'})
    elif kind=='empty-requirements':roster['requirements']=[]
    elif kind=='empty-families':roster['target_families']=[];plan['target_families']=[]
    elif kind=='missing-stages':del roster['stages']
    elif kind=='legacy-portfolio':plan['schema_version']=1
    return roster,plan


@pytest.mark.parametrize('kind',['dropped-family','extra-family','reordered-stages','dropped-stage','unknown-prepared',
    'no-prepared','duplicate-requirement','empty-requirements','empty-families','missing-stages','legacy-portfolio'])
def test_portfolio_cannot_narrow_supplied_roster(tmp_path,kind):
    roster,plan=_fault(kind)
    task,base=request(tmp_path,roster,plan)
    with pytest.raises(ValueError):h.inputs(task,base)
