"""Fabricated detector laws; source/software assertions, not detector calibration."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import pytest
from ravel.physics import columnar_ntuple_recipe as h, ntuple_inventory as intake
from ravel.physics import columnar_selection as s, columnar_response as response
from ravel.physics import mc_expected_construction, root_stream_core as c


# Fabricated format roles. The code holds no format table: every known role below is
# supplied data, exactly as a real run supplies its own descriptor.
ROLES={'schema_version':1,'kind':'columnar-branch-roles','name':'fabricated-flat-ntuple',
    'source':'fabricated engineering control; no real format','branches':[
        {'name':'weight_pileup_NOSYS','role':'scale_weight','shape':'scalar','unit':'1'},
        {'name':'weight_beamspot','role':'scale_weight','shape':'scalar','unit':'1'},
        {'name':'fabricatedPileupMu','role':'event_pileup','shape':'scalar','unit':'1'},
        {'name':'jet_fabricatedTagEff_NOSYS','role':'object_scale_weight','shape':'jagged','unit':'1'},
        {'name':'jet_fabricatedVertexEff_NOSYS','role':'object_scale_weight','shape':'jagged','unit':'1'}],
    'families':[
        {'pattern':'[A-Za-z]+_pt_NOSYS','role':'object_pt','shape':'jagged','unit':'MeV'},
        {'pattern':'[A-Za-z]+_eta','role':'object_eta','shape':'jagged','unit':'1'},
        {'pattern':'[A-Za-z]+_phi','role':'object_phi','shape':'jagged','unit':'rad'},
        {'pattern':'[A-Za-z]+_e_NOSYS','role':'object_energy','shape':'jagged','unit':'MeV'},
        {'pattern':'[A-Za-z]+_select_passesOR[A-Za-z_]*','role':'baseline_or','shape':'jagged','unit':'1'},
        {'pattern':'[A-Za-z]+_select_[A-Za-z0-9_]+','role':'object_selection','shape':'jagged','unit':'1'},
        {'pattern':'[A-Za-z]+_[A-Za-z0-9]*SF_NOSYS','role':'object_scale_weight','shape':'jagged','unit':'1'},
        {'pattern':'[A-Za-z]+_fabricatedAux[A-Za-z]*','role':'object_auxiliary','shape':'jagged','unit':None},
        {'pattern':'trigPassed_[A-Za-z0-9_]+','role':'trigger_decision','shape':'scalar','unit':'1'},
        {'pattern':'met(Baseline|Signal)_(met|sumet)_NOSYS','role':'stored_met','shape':'scalar','unit':'MeV'},
        {'pattern':'met(Baseline|Signal)_phi_NOSYS','role':'stored_met','shape':'scalar','unit':'rad'}]}


def save(root, name, value):
    path=root/name;raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();path.write_bytes(raw)
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def source(tmp_path, *, payload=True, method='joint_pattern_probabilities'):
    root=tmp_path/'source';root.mkdir()
    proof=save(root,'applicability.json',{'fabricated':'not detector qualified'})
    objects=[]
    for name,prefix in [('electrons','el'),('jets','jet')]:
        objects.append({'name':name,'prefix':prefix,'selection':'source_defined','pt_min_GeV':20,
                        'abs_eta_max':2.5,'scale_factors':[],'tagger':None,
                        'working_points':{y:{'id':'source-'+y,'isolation':None,
                            'gates':[{'branch':prefix+'_wp_'+y,'kind':'bit','low':None,'high':None}]}
                            for y in ('2018','2023')}})
    recipe={'schema_version':2,'objects':objects,
        'overlap_removal':{'semantics':'ordered_directed_simultaneous_deltaR','max_pair_checks_per_event':1000,'rules':[
            {'id':'remove_jet_near_electron','target':'jets','against':'electrons',
             'radius':{'kind':'constant','constant':.2,'offset':None,'scale_GeV':None,'cap':None},'gates':[]},
            {'id':'remove_electron_near_remaining_jet','target':'electrons','against':'jets',
             'radius':{'kind':'constant','constant':.4,'offset':None,'scale_GeV':None,'cap':None},'gates':[]}]},
        'met':{'kind':'unused','components':[],'objects':[]},
        'trigger_by_year':{'2018':['trigPassed_a','trigPassed_b'],'2023':['trigPassed_b','trigPassed_c']},
        'scalar_scale_factors':['weight_pileup_NOSYS'],
        'sf_applicability':[{'subject':'source joint selected-object and conditional event trigger ratio','source':proof,
            'treatment':'declared_conditional_not_calibration_qualification','limitations':['fabricated source']}],
        'regions':[{'id':'SR','role':'signal','counts':{'electrons':[1,None]},'ht':None,'met_GeV':[0,None]},
                   {'id':'CR','role':'control','counts':{'electrons':[0,0]},'ht':None,'met_GeV':[0,None]},
                   {'id':'VR','role':'validation','counts':{'jets':[0,None]},'ht':None,'met_GeV':[0,None]}],
        'uncertainty_policy':'nominal_only_missing_variations_explicit',
        'selection_source':proof,'branch_roles':deepcopy(ROLES),
        'fitted_categories':{'bins':['SR','CR'],'source':proof,
            'semantics':'source_declared_disjoint_independent_poisson',
            'independent_unit':'source_entry_declared_independent_physical_event_group'},
        'response':{'request':proof,'payload':None,'coordinates':[
            {'id':'nel','kind':'count','branch':None,'object':'electrons','rank':None,'unit':'1','missing':None}]}}
    recipe['selection_source']=save(root,'selection-source.json',{'schema_version':1,
        'kind':'source_declared_changed_columnar_selection','law':s.selection_law(recipe),
        'statement':'Fabricated full ordered source law, disjoint recoil association if declared.'})
    request={'schema_version':1,'selection_sha256':s.signature(recipe),'conditioning':response.CONDITION,
        'representation':'joint_patterns' if method.startswith('joint_pattern') else 'joint_or',
        'sample_dsids':[801174],'coordinates':recipe['response']['coordinates'],
        'years':{y:{'chains':bs,'cells':[{'id':'all','bounds':[[0,None]]}]} for y,bs in recipe['trigger_by_year'].items()},
        'source':proof,'acquisition':{'producer':'source_joint_table','configuration_source':proof,
            'required_measurements':['complete joint data/MC event OR conditional on selected objects and one joint object ratio'],
            'limitations':['not calibrated; full original denominator and failed outcomes required']}}
    recipe['response']['request']=save(root,'response-request.json',request)
    if payload:
        data=['1/4','1/4','0','1/2'];mc=['1/2','1/4','0','1/4']
        if method=='joint_pattern_counts':data=[1,1,0,2];mc=[2,1,0,1]
        if method=='joint_or_probabilities':data='3/4';mc='1/2'
        if method=='joint_or_counts':data={'passed':3,'total':4};mc={'passed':2,'total':4}
        table={'schema_version':1,'request_sha256':recipe['response']['request']['sha256'],'method':method,
               'source':proof,'inputs':[proof],'cells':[{'year':y,'id':'all','data':data,'mc':mc,'selected_object_ratio':'4/5'}for y in request['years']]}
        recipe['response']['payload']=save(root,'response-table.json',table)
    return root,recipe


def event(year=2018):
    return {'year':year,'mcChannelNumber':801174,'weight_mc_NOSYS':-3.,'weight_pileup_NOSYS':2.,
        'trigPassed_a':True,'trigPassed_b':False,'trigPassed_c':True,
        'el_pt_NOSYS':[21000.,50000.,9000.],'el_eta':[.2,1.,.1],'el_phi':[.1,2.,0.],
        'el_wp_2018':[1,1,1],'el_wp_2023':[0,1,1],
        'jet_pt_NOSYS':[30000.,45000.],'jet_eta':[.21,2.],'jet_phi':[.11,-2.],
        'jet_wp_2018':[1,1],'jet_wp_2023':[1,1]}


def compiled(root, recipe):
    cap=c.Capture();checked,table,tracker=s.rebase_recipe(recipe,root,cap);cap.finish()
    return checked,table,tracker


@pytest.mark.parametrize('method',response.METHODS)
def test_correlated_joint_or_and_count_lowering(tmp_path,method):
    root,r=source(tmp_path,method=method);checked,table,_=compiled(root,r)
    view=s.event_view(event(),checked,table)
    assert view['object_factor']==pytest.approx(float(Fraction(4,5)*Fraction(3,4)/Fraction(1,2)))
    assert view['objects']['jets']['indices']==[1]
    assert view['objects']['electrons']['indices']==[1,0]
    assert view['object_factor']!=pytest.approx(.8) # marginal independent-product shortcut is wrong here
    assert table['physics_validated'] is False


def test_year_specific_wp_and_complete_unweighted_source_entries(tmp_path):
    root,r=source(tmp_path);r,t,_=compiled(root,r)
    assert s.event_view(event(2023),r,t)['objects']['electrons']['indices']==[1]
    rejected=event();rejected['trigPassed_a']=False
    rows=s.records([event(),rejected],[11,12],{'dsid':801174},r,t)
    assert rows[0]['fills']=={'regions':[[.5],[2.5]]} and rows[1]=={'source_entry':12,'fills':{'regions':[]}}
    assert s.event_view(rejected,r,t)['response_applied'] is False
    assert rejected['weight_mc_NOSYS']==-3. # correction never edits raw generator weights


def test_thresholds_strict_eta_and_unsorted_aligned_reordering(tmp_path):
    root,r=source(tmp_path);r,t,_=compiled(root,r);e=event()
    e['el_pt_NOSYS']=[20000.,50000.,19999.];e['el_eta']=[2.49,2.5,0.]
    assert s.event_view(e,r,t)['objects']['electrons']['pt_GeV']==[20.]
    e=event();v=s.event_view(e,r,t)
    for prefix,order in [('el',[2,0,1]),('jet',[1,0])]:
        for name in list(e):
            if name.startswith(prefix+'_'):e[name]=[e[name][i]for i in order]
    w=s.event_view(e,r,t)
    assert [o['pt_GeV']for o in v['objects'].values()]==[o['pt_GeV']for o in w['objects'].values()]
    assert v['object_factor']==w['object_factor']


def test_pair_rule_order_simultaneous_and_wrapped_phi(tmp_path):
    root,r=source(tmp_path);r,t,_=compiled(root,r);e=event()
    e['el_phi'][0]=math.pi-.01;e['jet_phi'][0]=-math.pi+.01
    assert s.event_view(e,r,t)['objects']['jets']['indices']==[1]
    reversed_recipe=deepcopy(r);reversed_recipe['overlap_removal']['rules'].reverse()
    # Pure law comparison deliberately does not claim calibration for changed order.
    assert s.selection_view(e,reversed_recipe,t['request']['coordinates'])['objects']['electrons']['indices']==[1]
    same=deepcopy(r);same['overlap_removal']['rules']=[{'id':'same','target':'electrons','against':'electrons',
        'radius':{'kind':'constant','constant':.2,'offset':None,'scale_GeV':None,'cap':None},'gates':[]}]
    e=event();e['el_eta'][1]=e['el_eta'][0]+.01;e['el_phi'][1]=e['el_phi'][0]+.01
    assert s.selection_view(e,same,t['request']['coordinates'])['objects']['electrons']['indices']==[]


def test_recipe_requires_recalibration_for_changed_order(tmp_path):
    root,r=source(tmp_path);r['overlap_removal']['rules'].reverse()
    with pytest.raises(ValueError,match='exact source'):compiled(root,r)


@pytest.mark.parametrize('mutation',[
    lambda r:r['objects'][0]['scale_factors'].append('el_recoSF_NOSYS'),
    lambda r:r['objects'][0]['working_points'].pop('2023'),
    lambda r:r['objects'][0]['working_points']['2018']['gates'][0].__setitem__('branch','mu_wp'),
    lambda r:r['regions'][0].__setitem__('met_GeV',[10,None]),
    lambda r:r.__setitem__('met',{'kind':'Baseline','components':[],'objects':[]}),
    lambda r:r['fitted_categories'].__setitem__('bins',['SR']),
])
def test_changed_schema_refuses_nominal_substitutions(tmp_path,mutation):
    _,r=source(tmp_path);mutation(r)
    with pytest.raises(ValueError):h.validate_recipe(r)


@pytest.mark.parametrize('mutation',[
    lambda e:e.__setitem__('year',2024),lambda e:e.__setitem__('mcChannelNumber',999999),
    lambda e:e['el_eta'].pop(),lambda e:e['jet_wp_2018'].__setitem__(0,2),
])
def test_actual_event_domain_and_alignment_refusals(tmp_path,mutation):
    root,r=source(tmp_path);r,t,_=compiled(root,r);e=event();mutation(e)
    with pytest.raises(ValueError):s.event_view(e,r,t)


def test_full_original_response_population_and_zero_support(tmp_path):
    root,r=source(tmp_path);request=json.loads(Path(r['response']['request']['path']).read_text());payload=json.loads(Path(r['response']['payload']['path']).read_text())
    partial=deepcopy(payload);partial['cells'].pop()
    with pytest.raises(ValueError):response.prepare(request,r['response']['request'],partial,s.signature(r),r['trigger_by_year'])
    payload['cells'][0]['mc']=['1','0','0','0']
    table=response.prepare(request,r['response']['request'],payload,s.signature(r),r['trigger_by_year'])
    assert table['cells'][0]['event_factor'] is None and table['cells'][0]['mc_atoms']==['1','0','0','0']
    with pytest.raises(ValueError,match='zero MC'):s.event_view(event(),r,table)


def test_invalid_probability_normalization_and_denominator_refuse(tmp_path):
    root,r=source(tmp_path);request=json.loads(Path(r['response']['request']['path']).read_text());p=json.loads(Path(r['response']['payload']['path']).read_text())
    p['cells'][0]['data']=['1/4','1/4','1/4','1/2']
    with pytest.raises(ValueError,match='sum to one'):response.prepare(request,r['response']['request'],p,s.signature(r),r['trigger_by_year'])
    for value in ('1e999999999','-1','NaN'):
        with pytest.raises(ValueError):response.rational(value)



def refresh_selection(root, recipe):
    """Rebind fabricated law fixtures without changing the response oracle."""
    request=json.loads(Path(recipe['response']['request']['path']).read_text())
    payload=None if recipe['response']['payload'] is None else json.loads(Path(recipe['response']['payload']['path']).read_text())
    recipe['selection_source']=save(root,'selection-source.json',{'schema_version':1,
        'kind':'source_declared_changed_columnar_selection','law':s.selection_law(recipe),
        'statement':'Fabricated source/software law; no detector qualification.'})
    request['selection_sha256']=s.signature(recipe)
    recipe['response']['request']=save(root,'response-request.json',request)
    if payload is not None:
        payload['request_sha256']=recipe['response']['request']['sha256']
        recipe['response']['payload']=save(root,'response-table.json',payload)
    return recipe


def with_recoil(root, recipe, *, complete=False, missing=False):
    recipe=deepcopy(recipe)
    if complete:
        components=[{'id':'producer','x':'changed_px','y':'changed_py','unit':'MeV','sign':1,'groups':['complete']}]
        objects=[];population=['entire-source']
        groups=[{'id':'complete','role':'complete_changed_vector','object':None,'members':['entire-source']}]
        roster=[{'object':o['name'],'treatment':'complete_vector','groups':['complete'],
                 'statement':'Fabricated producer covers this exact changed selection.'}for o in recipe['objects']]
    else:
        components=[{'id':'soft','x':'soft_px','y':'soft_py','unit':'MeV','sign':1,'groups':['soft']}]
        objects=[{'object':'electrons','sign':1,'groups':['electrons']}]
        population=['soft-detector','el-detector']
        groups=[{'id':'soft','role':'soft','object':None,'members':['soft-detector']},
                {'id':'electrons','role':'selected_objects','object':'electrons','members':['el-detector']}]
        roster=[{'object':'electrons','treatment':'selected_term','groups':['electrons'],'statement':'Fabricated selected hard term.'},
                {'object':'jets','treatment':'excluded','groups':[],'statement':'Explicit fabricated source exclusion, not inferred by software.'}]
    recipe['met']={'kind':'source_recoil','components':components,'objects':objects,
        'association':{'convention':'signed_cartesian_sum_for_missing_transverse_momentum',
            'selection_objects':[o['name']for o in recipe['objects']],'object_associations':roster,
            'population':population,'groups':groups},'association_source':None}
    if not missing: refresh_recoil(root,recipe)
    return refresh_selection(root,recipe)


def refresh_recoil(root, recipe):
    recipe['met']['association_source']=save(root,'recoil-source.json',{'schema_version':1,
        'kind':'source_declared_complete_disjoint_changed_recoil',
        'selection':s._identity({k:recipe[k]for k in ('objects','overlap_removal')}),
        'law':s.recoil_law(recipe['met']),'statement':'Fabricated complete association record; not actual detector data.'})
    return recipe

def test_source_recoil_requires_actual_components(tmp_path):
    root,r=source(tmp_path);r=with_recoil(root,r)
    r['selection_source']=save(root,'selection-source.json',{'schema_version':1,'kind':'source_declared_changed_columnar_selection','law':s.selection_law(r),'statement':'fabricated disjoint complete recoil'})
    request=json.loads(Path(r['response']['request']['path']).read_text());request['selection_sha256']=s.signature(r)
    r['response']['request']=save(root,'response-request.json',request)
    p=json.loads(Path(r['response']['payload']['path']).read_text());p['request_sha256']=r['response']['request']['sha256'];r['response']['payload']=save(root,'response-table.json',p)
    r,t,_=compiled(root,r);e=event()
    with pytest.raises(KeyError):s.event_view(e,r,t)
    e['soft_px']=1000.;e['soft_py']=-2000.
    expected=math.hypot(1+sum(pt/1000*math.cos(ph) for pt,ph in zip(e['el_pt_NOSYS'][:2],e['el_phi'][:2])),
                        -2+sum(pt/1000*math.sin(ph) for pt,ph in zip(e['el_pt_NOSYS'][:2],e['el_phi'][:2])))
    assert s.event_view(e,r,t)['met_GeV']==pytest.approx(expected)


def ordinary_task(tmp_path, recipe, source_root):
    # Original ordinary preparation fixture owns every whole-question document;
    # this is explicit inert authority, not a scientific admission receipt.
    from test_ntuple_inventory import request as nominal_request
    task,base=nominal_request(tmp_path);d=json.loads(Path(task['request']['path']).read_text())
    d['recipe']=save(base,'recipe.json',recipe);branches=[]
    req=json.loads(Path(recipe['response']['request']['path']).read_text())
    for name in h.required_branches(recipe):
        shape,unit=s.branch_description(recipe,req,name)
        dtype='uint32' if name in ('year','mcChannelNumber') else 'bool' if name.startswith('trigPassed_') else 'int8' if '_wp_' in name else 'float32'
        branches.append({'name':name,'shape':shape,'unit':unit,'dtype':dtype})
    d['branches']=save(base,'branches.json',branches);task={'request':save(base,'request.json',d)}
    return task,base,branches


def test_missing_calibration_has_ordinary_preparation_and_whole_acquisition(tmp_path,monkeypatch):
    root,r=source(tmp_path,payload=False);task,base,_=ordinary_task(tmp_path,r,root)
    monkeypatch.setattr(intake,'_approved',lambda task,out:None)
    result=intake.run(task,base,tmp_path/'output')
    assert result['execution_ready'] is False and result['kernel'] is None
    assert result['missing_external_inputs']==['resolved_members','sample_definitions','site_runtime','complete_joint_selected_object_and_conditional_trigger_response']
    preparation=json.loads(Path(result['joint_response_preparation']['path']).read_text())
    assert preparation['request']['years'].keys()==r['trigger_by_year'].keys()
    assert preparation['request']['acquisition']['required_measurements'] and preparation['next_action']
    assert len(result['remaining_stages'])==5 and result['original_task_complete'] is False


def test_actual_preparation_copied_inputs_expected_kernel_and_drift(tmp_path,monkeypatch):
    root,r=source(tmp_path);task,base,branches=ordinary_task(tmp_path,r,root)
    monkeypatch.setattr(intake,'_approved',lambda task,out:None)
    result=intake.run(task,base,tmp_path/'output');out=Path(result['kernel']['path']).parent
    recipe=json.loads(Path(result['kernel_recipe']['path']).read_text())
    manifest=json.loads((out/'selection-dependencies.json').read_text())
    files={'kernel.py':result['kernel'],'selection-dependencies.json':save(out,'selection-dependencies.json',manifest)}
    for row in manifest['files']:
        path=out/row['member'];files[row['member']]={**row['original'],'path':str(path)}
    cfg={'bundle':{'entry':'kernel.py','blind_entry':None,'files':files,'review_source':result['kernel_recipe']}}
    analysis=h.analysis_document(recipe,branches,json.loads(Path(task['request']['path']).read_text())['original_goal'],result['kernel'])
    design={'region_roles':{'SR':'signal_region','CR':'control_region','VR':'validation_region'},'recipe':{'cells':[{'law':{'bins':[{'id':'SR'},{'id':'CR'}]}}]}}
    # Transport proves exact consumed original identities even when originals
    # are not reachable; it does not label copies as fresh original observations.
    for path in root.iterdir():path.unlink()
    assert mc_expected_construction.fitted_kernel(recipe,cfg,design,c.Capture(),out,analysis)['bins']==['SR','CR']
    copied=out/manifest['files'][0]['member'];copied.write_text('{}')
    with pytest.raises(ValueError):s.verify_bundle(recipe,cfg,out,c.Capture())


def test_context_and_public_input_roster_retain_calibration_sources(tmp_path):
    root,r=source(tmp_path);task,base,_=ordinary_task(tmp_path,r,root)
    ctx=intake.context(task,base);paths=set(intake.inputs(task,base))
    assert ctx['changed_selection_response']['ready'] is True and ctx['execution_authorized'] is False
    assert all(Path(r['response'][key]['path'])in paths for key in ('request','payload'))


def test_work_budget_is_a_refusal_not_partial_overlap(tmp_path):
    root,r=source(tmp_path);r,t,_=compiled(root,r)
    r['overlap_removal']['max_pair_checks_per_event']=1
    with pytest.raises(ValueError,match='ceiling exhausted'):
        s.selection_view(event(),r,t['request']['coordinates'])


def test_missing_object_rank_is_explicit_calibrated_coordinate():
    axes=[{'id':'first','kind':'pt','branch':None,'object':'el','rank':0,'unit':'GeV','missing':-1}]
    objects={'el':{'indices':[],'pt_GeV':[],'abs_eta':[]}}
    assert s._coordinates({},objects,0,axes)==[-1.]
    axes[0]['missing']=None
    with pytest.raises(ValueError,match='no invented coordinate'):s._coordinates({},objects,0,axes)


def test_foreign_compiled_selection_cannot_be_applied(tmp_path):
    root,r=source(tmp_path);r,t,_=compiled(root,r);r['objects'][0]['pt_min_GeV']=30
    with pytest.raises(ValueError,match='correspondence'):s.event_view(event(),r,t)


def test_complete_large_direct_joint_or_menu_and_representation_refusal(tmp_path):
    root,r=source(tmp_path,method='joint_or_probabilities')
    menu=['trigPassed_source_'+str(i) for i in range(80)]
    r['trigger_by_year']={year:list(menu) for year in r['trigger_by_year']}
    r['selection_source']=save(root,'selection-source.json',{'schema_version':1,
        'kind':'source_declared_changed_columnar_selection','law':s.selection_law(r),
        'statement':'Fabricated complete eighty-chain event OR, not independent leg factors.'})
    request=json.loads(Path(r['response']['request']['path']).read_text())
    request['selection_sha256']=s.signature(r)
    for domain in request['years'].values():domain['chains']=list(menu)
    r['response']['request']=save(root,'response-request.json',request)
    payload=json.loads(Path(r['response']['payload']['path']).read_text())
    payload['request_sha256']=r['response']['request']['sha256']
    r['response']['payload']=save(root,'response-table.json',payload)
    checked,table,_=compiled(root,r);e=event()
    e.update({branch:False for branch in menu});e[menu[-1]]=True
    assert table['request']['years']['2018']['chains']==menu
    assert s.event_view(e,checked,table)['object_factor']==pytest.approx(1.2)
    wrong=deepcopy(payload);wrong['method']='joint_pattern_probabilities'
    with pytest.raises(ValueError,match='complete joint representation'):
        response.prepare(request,r['response']['request'],wrong,s.signature(r),r['trigger_by_year'])
    request['representation']='joint_patterns'
    with pytest.raises(ValueError,match='complete ordered trigger OR'):
        response.validate_request(request,s.signature(r),r['trigger_by_year'])


def replace_task_recipe(task, base, recipe):
    document=json.loads(Path(task['request']['path']).read_text())
    document['recipe']=save(base,'recipe.json',recipe)
    return {'request':save(base,'request.json',document)}


@pytest.mark.parametrize('branch',[
    'metBaseline_met_NOSYS','metBaseline_phi_NOSYS','metBaseline_sumet_NOSYS',
    'metSignal_met_NOSYS','metSignal_phi_NOSYS','metSignal_sumet_NOSYS'])
def test_ordinary_recoil_refuses_stored_magnitude_angle_and_sumet(tmp_path,branch):
    root,r=source(tmp_path);r=with_recoil(root,r);task,base,_=ordinary_task(tmp_path,r,root)
    r['met']['components'][0]['x']=branch
    refresh_recoil(root,r);refresh_selection(root,r);task=replace_task_recipe(task,base,r)
    with pytest.raises(ValueError,match='stored MET'):intake.inputs(task,base)


@pytest.mark.parametrize('mutation',[
    lambda r:r['met']['objects'].clear(),
    lambda r:r['met']['association']['population'].append('missing-hard-term'),
    lambda r:r['met']['association']['groups'][1]['members'].append('soft-detector'),
    lambda r:r['met']['components'][0]['groups'].append('electrons'),
    lambda r:r['met']['components'][0].__setitem__('sign',True),
    lambda r:r['met']['association']['object_associations'].pop(),
    lambda r:r['met']['association']['object_associations'][1].__setitem__('treatment','selected_term'),
])
def test_ordinary_recoil_refuses_omitted_double_counted_and_untyped_associations(tmp_path,mutation):
    root,r=source(tmp_path);r=with_recoil(root,r);task,base,_=ordinary_task(tmp_path,r,root)
    mutation(r);refresh_recoil(root,r);refresh_selection(root,r);task=replace_task_recipe(task,base,r)
    with pytest.raises(ValueError):intake.context(task,base)


def test_signed_complete_recoil_cancellation_and_post_or_object_population(tmp_path):
    root,r=source(tmp_path);r=with_recoil(root,r)
    met=r['met'];met['components'].append({'id':'hard','x':'hard_px','y':'hard_py','unit':'MeV','sign':-1,'groups':['hard']})
    met['association']['population'].append('other-hard-detector')
    met['association']['groups'].append({'id':'hard','role':'unselected_hard','object':None,'members':['other-hard-detector']})
    met['objects'][0]['sign']=-1;refresh_recoil(root,r);refresh_selection(root,r)
    r,table,_=compiled(root,r);e=event();e.update(soft_px=40000.,soft_py=10000.,hard_px=40000.,hard_py=10000.)
    view=s.event_view(e,r,table)
    assert view['objects']['electrons']['indices']==[1,0]
    expected=math.hypot(math.fsum([-50*math.cos(2),-21*math.cos(.1)]),
                        math.fsum([-50*math.sin(2),-21*math.sin(.1)]))
    assert view['met_GeV']==pytest.approx(expected) and view['object_factor']==pytest.approx(1.2)
    assert e['weight_mc_NOSYS']==-3. and e['weight_pileup_NOSYS']==2.


def test_component_only_met_requires_actual_complete_changed_vector_source(tmp_path):
    root,r=source(tmp_path);r=with_recoil(root,r,complete=True)
    r,table,_=compiled(root,r);e=event();e.update(changed_px=30000.,changed_py=-40000.)
    assert s.event_view(e,r,table)['met_GeV']==50.
    bad=deepcopy(r);bad['met']['objects']=[{'object':'electrons','sign':1,'groups':['complete']}]
    with pytest.raises(ValueError):s.validate_recipe(bad)
    bad=deepcopy(r);bad['met']['association']['object_associations'][0]['treatment']='excluded'
    with pytest.raises(ValueError,match='explicitly cover'):s.validate_recipe(bad)


@pytest.mark.parametrize('missing', ['source','association'])
def test_missing_recoil_evidence_has_concrete_acquisition_and_no_kernel(tmp_path,monkeypatch,missing):
    root,r=source(tmp_path);r=with_recoil(root,r,missing=True)
    if missing=='association':r['met']['association']=None;refresh_selection(root,r)
    task,base,_=ordinary_task(tmp_path,r,root);monkeypatch.setattr(intake,'_approved',lambda task,out:None)
    result=intake.run(task,base,tmp_path/'output')
    assert result['kernel'] is None and result['root_specification'] is None and result['execution_ready'] is False
    assert 'complete_source_bound_changed_selection_recoil_association' in result['missing_external_inputs']
    acquisition=json.loads(Path(result['joint_response_preparation']['path']).read_text())
    assert acquisition['recoil_acquisition']['requested_law']==s.recoil_law(r['met'])
    assert len(acquisition['recoil_acquisition']['required'])==3 and acquisition['recoil_acquisition']['next_action']
    assert acquisition['recoil_association']['ready'] is False and acquisition['physics_validated'] is False
    assert result['inventory_events']==12345 and result['original_task_complete'] is False


def test_actual_recoil_producer_selection_and_association_must_match(tmp_path):
    root,r=source(tmp_path);r=with_recoil(root,r);task,base,_=ordinary_task(tmp_path,r,root)
    evidence=json.loads(Path(r['met']['association_source']['path']).read_text())
    evidence['law']['components'][0]['sign']=-1
    r['met']['association_source']=save(root,'recoil-source.json',evidence)
    refresh_selection(root,r);task=replace_task_recipe(task,base,r)
    with pytest.raises(ValueError,match='actual source recoil'):intake.inputs(task,base)


@pytest.mark.parametrize('location', ['wp','target','against'])
@pytest.mark.parametrize('suffix', ['_select_passesOR_NOSYS','_select_passesORLargeR_NOSYS'])
def test_stored_baseline_or_flags_refused_at_every_changed_predicate(tmp_path,location,suffix):
    root,r=source(tmp_path);task,base,_=ordinary_task(tmp_path,r,root)
    if location=='wp':r['objects'][0]['working_points']['2018']['gates'].append({'branch':'el'+suffix,'kind':'bit','low':None,'high':None})
    else:
        prefix='jet' if location=='target' else 'el'
        r['overlap_removal']['rules'][0]['gates'].append({'side':location,'gate':{'branch':prefix+suffix,'kind':'bit','low':None,'high':None}})
    refresh_selection(root,r);task=replace_task_recipe(task,base,r)
    with pytest.raises(ValueError,match='stored baseline OR'):intake.context(task,base)


def test_legitimate_wp_and_pair_flags_preserved_baseline_or_cannot_affect_selection(tmp_path):
    root,r=source(tmp_path)
    r['objects'][0]['working_points']['2018']['gates'].append({'branch':'el_select_tight_NOSYS','kind':'bit','low':None,'high':None})
    r['overlap_removal']['rules'][0]['gates']=[{'side':'target','gate':{'branch':'jet_select_passesJvt_NOSYS','kind':'bit','low':None,'high':None}}]
    refresh_selection(root,r);r,table,_=compiled(root,r)
    e=event();e['el_select_tight_NOSYS']=[1,1,1];e['jet_select_passesJvt_NOSYS']=[1,1]
    e['el_select_passesOR_NOSYS']=[0,0,0];e['jet_select_passesORLargeR_NOSYS']=[0,0]
    first=s.event_view(e,r,table)
    e['el_select_passesOR_NOSYS']=[1,1,1];e['jet_select_passesORLargeR_NOSYS']=[1,1]
    assert first==s.event_view(e,r,table)
    assert 'el_select_tight_NOSYS' in h.required_branches(r) and 'jet_select_passesJvt_NOSYS' in h.required_branches(r)
    assert not any('passesOR' in b for b in h.required_branches(r))


def test_source_tracker_consumes_one_lexical_path_and_refuses_linked_components(tmp_path):
    request=tmp_path/'calibration/request';inputs=tmp_path/'calibration/inputs';request.mkdir(parents=True);inputs.mkdir()
    proof=save(inputs,'proof.json',{'fabricated':'sibling-directory dependency'})
    tracker=s.SourceTracker(c.Capture())
    # A dependency named from its own document base, stepping to a sibling directory, and
    # the same file by its direct path are one consumed, budgeted and retained row.
    sibling,raw=tracker.read({**proof,'path':'../inputs/proof.json'},request)
    direct,again=tracker.read(proof,tmp_path/'unrelated-base')
    assert sibling==direct==inputs/'proof.json' and raw==again==(inputs/'proof.json').read_bytes()
    assert list(tracker.rows)==[inputs/'proof.json'] and tracker.rows[sibling]==proof
    assert '..' not in tracker.rows[sibling]['path']
    # With a linked component the lexical and the resolved path can differ; neither is chosen.
    (tmp_path/'calibration/linked').symlink_to(request)
    with pytest.raises(ValueError,match='unlinked scientific dependency'):
        tracker.read({**proof,'path':'../linked/../inputs/proof.json'},request)
    (inputs/'alias.json').symlink_to(inputs/'proof.json')
    with pytest.raises(ValueError,match='unlinked scientific dependency'):
        tracker.read({**proof,'path':'../inputs/alias.json'},request)
    with pytest.raises(ValueError,match='differ from admitted pin'):
        tracker.read({**proof,'sha256':'0'*64,'path':'../inputs/proof.json'},request)
    assert list(tracker.rows)==[inputs/'proof.json']


def test_nested_recipe_ordinary_preparation_and_transported_expected_closure_dependencies(tmp_path,monkeypatch):
    root,r=source(tmp_path);r=with_recoil(root,r);task,base,branches=ordinary_task(tmp_path,r,root)
    recipe_dir=base/'recipes';deps=recipe_dir/'deps';reqdir=recipe_dir/'calibration/request';tabdir=recipe_dir/'calibration/tables';calinputs=recipe_dir/'calibration/inputs'
    for d in (deps,reqdir,tabdir,calinputs):d.mkdir(parents=True,exist_ok=True)
    proof=json.loads(Path(r['sf_applicability'][0]['source']['path']).read_text())
    actual_proof=save(deps,'applicability.json',proof)
    for row in r['sf_applicability']:row['source']={**actual_proof,'path':'deps/applicability.json'}
    r['fitted_categories']['source']={**actual_proof,'path':'deps/applicability.json'}
    actual_recoil=save(deps,'recoil-source.json',json.loads(Path(r['met']['association_source']['path']).read_text()))
    r['met']['association_source']={**actual_recoil,'path':'deps/recoil-source.json'}
    actual_selection=save(deps,'selection-source.json',{'schema_version':1,'kind':'source_declared_changed_columnar_selection',
        'law':s.selection_law(r),'statement':'Fabricated nested source: each dependency uses its document base.'})
    r['selection_source']={**actual_selection,'path':'deps/selection-source.json'}
    calproof=save(calinputs,'proof.json',proof)
    request=json.loads(Path(r['response']['request']['path']).read_text());request['selection_sha256']=s.signature(r)
    request['source']={**calproof,'path':'../inputs/proof.json'};request['acquisition']['configuration_source']=request['source']
    actual_request=save(reqdir,'request.json',request)
    payload=json.loads(Path(r['response']['payload']['path']).read_text());payload['request_sha256']=actual_request['sha256']
    payload['source']={**calproof,'path':'../inputs/proof.json'};payload['inputs']=[payload['source']]
    actual_payload=save(tabdir,'table.json',payload)
    r['response']['request']={**actual_request,'path':'calibration/request/request.json'}
    r['response']['payload']={**actual_payload,'path':'calibration/tables/table.json'}
    original=json.loads(Path(task['request']['path']).read_text())
    original['recipe']={**save(recipe_dir,'recipe.json',r),'path':'recipes/recipe.json'}
    task={'request':save(base,'request.json',original)}
    # Wrong-base decoys must not be consumed, even with identical basenames.
    (base/'deps').mkdir();save(base/'deps','selection-source.json',{'wrong':'request directory'})
    monkeypatch.setattr(intake,'_approved',lambda task,out:None)
    result=intake.run(task,base,tmp_path/'output');out=Path(result['kernel']['path']).parent
    emitted=json.loads(Path(result['kernel_recipe']['path']).read_text())
    assert emitted['selection_source']['path']==str(deps/'selection-source.json')
    assert emitted['met']['association_source']['path']==str(deps/'recoil-source.json')
    manifest=json.loads((out/'selection-dependencies.json').read_text())
    files={'kernel.py':result['kernel'],'selection-dependencies.json':{ 'path':str(out/'selection-dependencies.json'),
        'sha256':hashlib.sha256((out/'selection-dependencies.json').read_bytes()).hexdigest(),'size':(out/'selection-dependencies.json').stat().st_size}}
    for row in manifest['files']:files[row['member']]={**row['original'],'path':str(out/row['member'])}
    cfg={'bundle':{'entry':'kernel.py','blind_entry':None,'files':files,'review_source':result['kernel_recipe']}}
    analysis=h.analysis_document(emitted,branches,original['original_goal'],result['kernel'])
    design={'region_roles':{'SR':'signal_region','CR':'control_region','VR':'validation_region'},'recipe':{'cells':[{'law':{'bins':[{'id':'SR'},{'id':'CR'}]}}]}}
    for d in (root,recipe_dir):
        for p in d.rglob('*'):
            if p.is_file():p.unlink()
    assert mc_expected_construction.fitted_kernel(emitted,cfg,design,c.Capture(),out,analysis)['bins']==['SR','CR']
    # Closure calls this exact shared transport consumer with two additional
    # immutable producer declarations; it must retain the recoil source too.
    cfg['bundle']['files']['closure_frozen_strategy.json']=save(out,'closure_frozen_strategy.json',{'fabricated':'strategy'})
    cfg['bundle']['files']['closure_production_independence.json']=save(out,'closure_production_independence.json',{'fabricated':'independent replicas'})
    checked,_=s.verify_bundle(emitted,cfg,out,c.Capture(),extra_members=('closure_frozen_strategy.json','closure_production_independence.json'))
    assert checked==emitted
    recoil_member=next(row['member']for row in manifest['files']if row['original']['path']==str(deps/'recoil-source.json'))
    (out/recoil_member).write_text('{}')
    with pytest.raises(ValueError):s.verify_bundle(emitted,cfg,out,c.Capture(),extra_members=('closure_frozen_strategy.json','closure_production_independence.json'))


def with_large_r(root, recipe):
    recipe=deepcopy(recipe)
    obj=deepcopy(recipe['objects'][1]);obj['name']='fatjets';obj['prefix']='largeRjet'
    for year,wp in obj['working_points'].items():wp['gates'][0]['branch']='largeRjet_wp_'+year
    # Names and validity convention from the existing nominal tagger control;
    # the event values and response table remain openly fabricated.
    obj['tagger']={'tagged':'largeRjet_TopTagged','valid':'largeRjet_TopValidKinRange',
                   'score':'largeRjet_TopScore','mass':None}
    recipe['objects'].append(obj)
    return refresh_selection(root,recipe)


def typed_tagger_task(tmp_path, recipe, root):
    task,base,branches=ordinary_task(tmp_path,recipe,root)
    for b in branches:
        if b['name'] in ('largeRjet_TopTagged','largeRjet_TopValidKinRange'):b['dtype']='int8'
    document=json.loads(Path(task['request']['path']).read_text())
    document['branches']=save(base,'branches.json',branches)
    return {'request':save(base,'request.json',document)},base,branches


@pytest.mark.parametrize('field,branch',[
    (field,'largeRjet_select_passesOR'+suffix)
    for field in ('tagged','mass','score','valid')
    for suffix in (('_validKinRange_NOSYS','LargeR_validKinRange_NOSYS') if field=='valid' else ('_NOSYS','LargeR_NOSYS'))])
def test_ordinary_tagger_all_fields_refuse_baseline_or_role(tmp_path,field,branch):
    root,r=source(tmp_path);r=with_large_r(root,r)
    checked,table,_=compiled(root,r);task,base,_=typed_tagger_task(tmp_path,r,root)
    r['objects'][-1]['tagger'][field]=branch;refresh_selection(root,r)
    task=replace_task_recipe(task,base,r)
    with pytest.raises(ValueError,match='stored baseline OR'):intake.inputs(task,base)
    with pytest.raises(ValueError,match='stored baseline OR'):h.required_branches(r)
    with pytest.raises(ValueError,match='stored baseline OR'):s.kernel_bytes(r,table)


def test_legitimate_tagger_ordinary_kernel_and_irrelevant_baseline_or(tmp_path,monkeypatch):
    root,r=source(tmp_path);r=with_large_r(root,r);task,base,branches=typed_tagger_task(tmp_path,r,root)
    monkeypatch.setattr(intake,'_approved',lambda task,out:None)
    result=intake.run(task,base,tmp_path/'output')
    assert result['execution_ready'] is False and result['kernel'] is not None
    checked,table,_=compiled(root,r);e=event()
    e.update(largeRjet_pt_NOSYS=[80000.,100000.],largeRjet_eta=[.2,.1],largeRjet_phi=[1.,2.],
             largeRjet_wp_2018=[1,1],largeRjet_wp_2023=[1,1],largeRjet_TopTagged=[1,1],
             largeRjet_TopValidKinRange=[1,0],largeRjet_TopScore=[.8,-666],
             largeRjet_select_passesOR_NOSYS=[0,0],largeRjet_select_passesORLargeR_NOSYS=[0,0])
    first=s.event_view(e,checked,table)
    e['largeRjet_select_passesOR_NOSYS']=[1,1];e['largeRjet_select_passesORLargeR_NOSYS']=[1,1]
    assert first==s.event_view(e,checked,table)
    assert first['objects']['fatjets']['indices']==[0] and first['object_factor']==pytest.approx(1.2)
    assert not any('passesOR' in b['name'] for b in branches)
    assert e['weight_mc_NOSYS']==-3. and e['weight_pileup_NOSYS']==2.


@pytest.mark.parametrize('branch',[
    'year','mcChannelNumber','weight_mc_NOSYS','weight_pileup_NOSYS','weight_beamspot',
    'trigPassed_a','trigPassed_unselected_source',
    *[prefix+suffix for prefix in ('el','mu','ph','tau','jet','largeRjet')
      for suffix in ('_pt_NOSYS','_eta','_phi','_select_passesOR_NOSYS','_select_custom_NOSYS','_recoSF_NOSYS')],
    'el_wp_2018','jet_wp_2023'])
def test_ordinary_recoil_cannot_retype_any_known_incompatible_branch_role(tmp_path,branch):
    root,r=source(tmp_path);r=with_recoil(root,r,complete=True);task,base,_=ordinary_task(tmp_path,r,root)
    r['met']['components'][0]['x']=branch
    refresh_recoil(root,r);refresh_selection(root,r);task=replace_task_recipe(task,base,r)
    # Authenticated declarations and a forged momentum unit cannot make the
    # identifier/weight/trigger/vector role a Cartesian detector momentum.
    d=json.loads(Path(task['request']['path']).read_text());rows=json.loads(Path(d['branches']['path']).read_text())
    rows=[b for b in rows if b['name']!='changed_px']
    rows=[b for b in rows if b['name']!=branch]+[{'name':branch,'shape':'scalar','unit':'MeV',
         'dtype':'uint32' if branch in ('year','mcChannelNumber') else 'float32'}]
    d['branches']=save(base,'branches.json',rows);task={'request':save(base,'request.json',d)}
    with pytest.raises(ValueError,match='known source branch roles'):intake.inputs(task,base)
    with pytest.raises(ValueError,match='known source branch roles'):h.required_branches(r)


@pytest.mark.parametrize('branch,expected',[
    ('year',('scalar','1')),('mcChannelNumber',('scalar','1')),
    ('weight_mc_NOSYS',('scalar','1')),('weight_pileup_NOSYS',('scalar','1')),
    ('weight_beamspot',('scalar','1')),('trigPassed_outside_menu',('scalar','1')),
    ('mu_pt_NOSYS',('jagged','MeV')),('tau_eta',('jagged','1')),('ph_phi',('jagged','rad')),
    ('largeRjet_select_passesORLargeR_NOSYS',('jagged','1')),
    ('el_recoSF_NOSYS',('jagged','1')),
    ('el_wp_2018',('jagged','1'))])
def test_branch_metadata_known_roles_precede_conflicting_declared_recoil(tmp_path,branch,expected):
    root,r=source(tmp_path);r=with_recoil(root,r,complete=True)
    r['met']['components'][0]['x']=branch
    request=json.loads(Path(r['response']['request']['path']).read_text())
    assert s.branch_description(r,request,branch)==expected
    with pytest.raises(ValueError,match='known source branch roles'):s.validate_recipe(r)


@pytest.mark.parametrize('location',['tagger','pair','response'])
def test_recoil_refuses_actual_declared_nonkinematic_consumer_roles(tmp_path,location):
    root,r=source(tmp_path)
    if location=='tagger':r=with_large_r(root,r);branch='largeRjet_TopScore'
    elif location=='pair':
        branch='el_actual_partner_quality'
        r['overlap_removal']['rules'][0]['gates']=[{'side':'against','gate':{'branch':branch,'kind':'range','low':0.,'high':1.}}]
    else:
        branch='source_dimensionless_coordinate'
        r['response']['coordinates'].append({'id':'source_scalar','kind':'scalar','branch':branch,'object':None,'rank':None,'unit':'1','missing':None})
    r=with_recoil(root,r,complete=True);r['met']['components'][0]['x']=branch
    refresh_recoil(root,r);refresh_selection(root,r)
    with pytest.raises(ValueError,match='known source branch roles'):s.validate_recipe(r)


@pytest.mark.parametrize('branch',['mu_pt_NOSYS','ph_phi','tau_select_custom_NOSYS'])
def test_response_scalar_coordinate_cannot_retype_unselected_native_object_roles(tmp_path,branch):
    root,r=source(tmp_path);task,base,_=ordinary_task(tmp_path,r,root)
    axis={'id':'scalar','kind':'scalar','branch':branch,'object':None,'rank':None,'unit':'1','missing':None}
    r['response']['coordinates']=[axis]
    request=json.loads(Path(r['response']['request']['path']).read_text());request['coordinates']=[axis]
    request['years']={y:{'chains':bs,'cells':[{'id':'all','bounds':[[0,None]]}]} for y,bs in r['trigger_by_year'].items()}
    r['response']['request']=save(root,'response-request.json',request);refresh_selection(root,r)
    task=replace_task_recipe(task,base,r)
    with pytest.raises(ValueError,match='dimensionless scalar source role'):intake.inputs(task,base)
    with pytest.raises(ValueError,match='dimensionless scalar source role'):h.required_branches(r)


def test_dimensionless_known_scalar_coordinates_and_new_signed_cartesian_producer_remain_usable(tmp_path,monkeypatch):
    root,r=source(tmp_path);r=with_recoil(root,r,complete=True)
    axes=[{'id':name,'kind':'scalar','branch':name,'object':None,'rank':None,'unit':'1','missing':None}
          for name in ('year','mcChannelNumber','weight_mc_NOSYS','weight_beamspot','source_scalar')]
    r['response']['coordinates']=axes
    request=json.loads(Path(r['response']['request']['path']).read_text());request['coordinates']=axes
    request['years']={y:{'chains':bs,'cells':[{'id':'all','bounds':[[-1000000,None] for _ in axes]}]} for y,bs in r['trigger_by_year'].items()}
    r['response']['request']=save(root,'response-request.json',request);refresh_selection(root,r)
    task,base,branches=ordinary_task(tmp_path,r,root)
    monkeypatch.setattr(intake,'_approved',lambda task,out:None)
    result=intake.run(task,base,tmp_path/'output')
    assert result['kernel'] is not None and result['execution_ready'] is False
    checked,table,_=compiled(root,r);e=event();e.update(changed_px=-30000.,changed_py=40000.,weight_beamspot=1.1,source_scalar=-2.)
    view=s.event_view(e,checked,table)
    assert view['met_GeV']==50. and view['object_factor']==pytest.approx(1.2)
    assert view['response_coordinates']==[2018.,801174.,-3.,1.1,-2.]
    by_name={b['name']:b for b in branches}
    assert all(by_name[a['branch']]['shape']=='scalar' and by_name[a['branch']]['unit']=='1' for a in axes)
    assert all(by_name[b]['shape']=='scalar' and by_name[b]['unit']=='MeV' for b in ('changed_px','changed_py'))
    assert table['physics_validated'] is False and e['weight_mc_NOSYS']==-3.


# Invented branches, one per supplied role and unit form, resolved only through ROLES.
SUPPLIED_ROLE_ORACLES = (('fabricatedPileupMu','scalar','1'),('weight_beamspot','scalar','1'),
 ('mu_pt_NOSYS','jagged','MeV'),('ph_eta','jagged','1'),('tau_phi','jagged','rad'),('jet_e_NOSYS','jagged','MeV'),
 ('el_select_passesOR_NOSYS','jagged','1'),('jet_select_passesORLargeR_NOSYS','jagged','1'),
 ('mu_select_custom_NOSYS','jagged','1'),('tau_customSF_NOSYS','jagged','1'),
 ('jet_fabricatedTagEff_NOSYS','jagged','1'),('el_fabricatedAuxSpread','jagged',None),
 ('trigPassed_outside_menu','scalar','1'),('metBaseline_met_NOSYS','scalar','MeV'),
 ('metSignal_sumet_NOSYS','scalar','MeV'),('metBaseline_phi_NOSYS','scalar','rad'))


def test_changed_recipe_has_no_built_in_format_roles(tmp_path):
    root,r=source(tmp_path)
    for name in ('DOCUMENTED_NATIVE_BRANCHES','DOCUMENTED_NATIVE_FAMILIES','_native_branch_role'):
        assert not hasattr(s,name)
    assert not hasattr(h,'PREFIXES') and not hasattr(h,'YEARS')
    del r['branch_roles']
    with pytest.raises(ValueError,match='no branch roles are built in'):s.validate_recipe(r)
    # A role the descriptor does not supply is unknown, so it cannot be refused by name.
    (tmp_path/'other').mkdir();root,r=source(tmp_path/'other');r=with_recoil(root,r,complete=True)
    request=json.loads(Path(r['response']['request']['path']).read_text())
    assert s.branch_description(r,request,'fabricatedPileupMu')==('scalar','1')
    r['branch_roles']['branches']=[b for b in r['branch_roles']['branches'] if b['name']!='fabricatedPileupMu']
    assert s._source_branch_role(r,'fabricatedPileupMu') is None


@pytest.mark.parametrize('branch,shape,unit',SUPPLIED_ROLE_ORACLES)
def test_supplied_role_vocabulary_recoil_metadata_and_kernel_refusals(tmp_path,branch,shape,unit):
    root,r=source(tmp_path);r=with_recoil(root,r,complete=True)
    task,base,_=ordinary_task(tmp_path,r,root);_,table,_=compiled(root,r)
    r['met']['components'][0]['x']=branch;refresh_recoil(root,r);refresh_selection(root,r)
    task=replace_task_recipe(task,base,r)
    d=json.loads(Path(task['request']['path']).read_text());branches=json.loads(Path(d['branches']['path']).read_text())
    branches=[b for b in branches if b['name'] not in ('changed_px',branch)]
    branches.append({'name':branch,'shape':'scalar','unit':'MeV',
                     'dtype':'uint32' if branch in ('year','mcChannelNumber') else 'float32'})
    d['branches']=save(base,'branches.json',branches);task={'request':save(base,'request.json',d)}
    request=json.loads(Path(r['response']['request']['path']).read_text())
    assert s.branch_description(r,request,branch)==(shape,unit)
    # Complete source mirrors/forged branch metadata cannot make a known field
    # a new Cartesian producer. Stored MET has its earlier dedicated refusal.
    with pytest.raises(ValueError,match='known source branch roles|stored MET'):intake.inputs(task,base)
    with pytest.raises(ValueError,match='known source branch roles|stored MET'):s.kernel_bytes(r,table)


@pytest.mark.parametrize('branch,shape,unit',[
    row for row in SUPPLIED_ROLE_ORACLES
    if row[1]=='jagged' or row[2]!='1' or row[0].startswith(('metBaseline_','metSignal_'))])
def test_supplied_object_and_met_vocabulary_refuses_scalar_response_retyping(tmp_path,branch,shape,unit):
    root,r=source(tmp_path);task,base,_=ordinary_task(tmp_path,r,root);_,table,_=compiled(root,r)
    axis={'id':'native','kind':'scalar','branch':branch,'object':None,'rank':None,'unit':'1','missing':None}
    r['response']['coordinates']=[axis]
    request=json.loads(Path(r['response']['request']['path']).read_text());request['coordinates']=[axis]
    r['response']['request']=save(root,'response-request.json',request);refresh_selection(root,r)
    task=replace_task_recipe(task,base,r)
    assert s.branch_description(r,request,branch)==(shape,unit)
    with pytest.raises(ValueError,match='dimensionless scalar source role'):intake.inputs(task,base)
    with pytest.raises(ValueError,match='dimensionless scalar source role'):s.kernel_bytes(r,table)


@pytest.mark.parametrize('branch',[
    'el_fabricatedAuxSpread','ph_fabricatedAuxSpread','mu_fabricatedAuxOffset'])
def test_unfixed_native_auxiliary_unit_requires_explicit_bound_schema_and_preserves_canonical_analysis(tmp_path,monkeypatch,branch):
    root,r=source(tmp_path);prefix=branch.split('_')[0]
    if prefix!='el':
        obj=deepcopy(r['objects'][0]);obj['name']=prefix+'objects';obj['prefix']=prefix
        for year,wp in obj['working_points'].items():wp['gates'][0]['branch']=prefix+'_wp_'+year
        r['objects'].append(obj)
    obj=next(o for o in r['objects'] if o['prefix']==prefix)
    obj['working_points']['2018']['gates'].append({'branch':branch,'kind':'range','low':0.,'high':1.})
    refresh_selection(root,r);task,base,branches=ordinary_task(tmp_path,r,root)
    assert next(b for b in branches if b['name']==branch)['unit'] is None
    with pytest.raises(ValueError,match='explicit source-bound unit'):intake.inputs(task,base)
    d=json.loads(Path(task['request']['path']).read_text())
    for value in ('','unknown','unqualified'):
        next(b for b in branches if b['name']==branch)['unit']=value
        d['branches']=save(base,'branches.json',branches);task={'request':save(base,'request.json',d)}
        with pytest.raises(ValueError,match='explicit source-bound unit'):intake.inputs(task,base)
    # Openly fabricated source unit. No absolute detector-unit claim is made;
    # the actual bound declaration survives ordinary canonical compilation.
    declared='fabricated-source-native-unit'
    next(b for b in branches if b['name']==branch)['unit']=declared
    d['branches']=save(base,'branches.json',branches);task={'request':save(base,'request.json',d)}
    assert base/'branches.json' in set(intake.inputs(task,base))
    monkeypatch.setattr(intake,'_approved',lambda task,out:None)
    result=intake.run(task,base,tmp_path/'output')
    emitted=json.loads(Path(result['kernel_recipe']['path']).read_text())
    analysis=h.analysis_document(emitted,branches,d['original_goal'],result['kernel'])
    assert next(b for b in analysis['branch_contract'] if b['name']==branch)['unit']==declared
    assert result['kernel'] is not None and result['execution_ready'] is False
    assert result['original_task_complete'] is False and result['root_data_accesses']==0


def test_supplied_energy_and_nonstandard_jet_sf_are_available_as_typed_object_predicates(tmp_path,monkeypatch):
    root,r=source(tmp_path)
    r['objects'][1]['working_points']['2018']['gates'].extend([
        {'branch':'jet_e_NOSYS','kind':'range','low':0.,'high':1000000.},
        {'branch':'jet_fabricatedTagEff_NOSYS','kind':'range','low':0.,'high':2.},
        {'branch':'jet_fabricatedVertexEff_NOSYS','kind':'range','low':0.,'high':2.}])
    refresh_selection(root,r);task,base,branches=ordinary_task(tmp_path,r,root)
    metadata={b['name']:(b['shape'],b['unit']) for b in branches}
    assert metadata['jet_e_NOSYS']==('jagged','MeV')
    assert metadata['jet_fabricatedTagEff_NOSYS']==('jagged','1')
    assert metadata['jet_fabricatedVertexEff_NOSYS']==('jagged','1')
    monkeypatch.setattr(intake,'_approved',lambda task,out:None)
    result=intake.run(task,base,tmp_path/'output');checked,table,_=compiled(root,r)
    e=event();e.update(jet_e_NOSYS=[60000.,80000.],jet_fabricatedTagEff_NOSYS=[1.,1.],
                       jet_fabricatedVertexEff_NOSYS=[1.,1.])
    view=s.event_view(e,checked,table)
    assert view['objects']['jets']['indices']==[1] and view['object_factor']==pytest.approx(1.2)
    assert e['weight_mc_NOSYS']==-3. and e['weight_pileup_NOSYS']==2.
    assert result['kernel'] is not None and table['physics_validated'] is False
