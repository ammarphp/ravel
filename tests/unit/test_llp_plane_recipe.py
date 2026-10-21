"""Full synthetic LLP cohorts; no charged calibration or physics claimed."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess

import pytest
from ravel.physics import llp_plane_recipe as op, marked_response as mr
from ravel.workflow import science, task_completion as tc, route_prompt
from test_svj_recipe import published
from svj_fixtures import policy


def emit(path, doc):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(doc,allow_nan=False)+'\n')
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}


def read(pin): return json.loads(Path(pin['path']).read_text())


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k: (_ for _ in ()).throw(AssertionError('external operations forbidden')))
    import platform
    monkeypatch.setattr(platform._Processor,'get',staticmethod(lambda:'synthetic-control'))
    monkeypatch.setattr(platform,'architecture',lambda *a,**k:('64bit','synthetic-control'))


def fixture(base, *, design='iid_fixed_N_groups', missing_second=True):
    base=base.resolve();base.mkdir(parents=True,exist_ok=True)
    source=emit(base/'source.json',{'definition':'Synthetic exact-point exponential independent group law and joint masks. No calibration.'})
    prompt='Construct the complete charged LLP mass/lifetime/mixed-spectrum plane with source-calibrated response and explicit expected luminosity projections.'
    parent=route_prompt.route(prompt);req=tc.initial_requirements(prompt)
    req['assignments']=[{'id':'llp','purpose':'Full model-plane source and likelihood construction','coverage':[{'obligation_id':'original-request','criteria':{'request':prompt}}]}]
    parent['task_requirements']=req;goal={'contract':emit(base/'parent.json',parent),'assignment_id':'llp'}
    points=[];bins=[{'id':x,'channel':ch,'sample':'signal','index':i,'role':ch} for ch,ns in [('SR',['s0','s1']),('CR',['c0','c1'])] for i,x in enumerate(ns)]
    for j,mass in enumerate((300,600)):
        identity={'schema_version':1,'coordinate':[mass],'energy_tev':13,'spectrum':emit(base/f'spectrum-{mass}.json',{'mass':mass,'source_lifetime_is_not_tree_splitting':True}),
                  'components':[{'id':'associated','process':'supplied charged pair','decay_channels':'fixed source BR channels','llp_species':[{'id':'chargino','mass_GeV':mass,'charge_e':1}]}],'sources':[source]}
        ip=emit(base/f'identity-{mass}.json',identity)
        events=[{'event_id':'e'+str(i),'group_id':'g'+str(i),'weights':{'nominal':1.,'up':2.},'llps':[{'id':'q','species':'chargino','proper_length_mm':10.*i}]} for i in range(4)]
        events.append({'event_id':'zero','group_id':'g3','weights':{'nominal':0.,'up':0.},'llps':[]})
        cohort={'schema_version':1,'point_identity_sha256':ip['sha256'],'component_id':'associated','species':[{'id':'chargino','ctau_mm':10.}],
                'sampling':{'decay_law':'independent_untruncated_exponential','design':design,'weight_unit':'dimensionless','weight_convention':'known_unit_mean_nominal_group_importance_mark','normalization_weight':'nominal','divisor':4.,'complete_exposure':True,'joint_second_moment':'source_asserted_finite','source':source},'events':events,'weight_definitions':[{'id':'nominal','unit':'dimensionless','meaning':'Synthetic nominal unit group mark','source':source},{'id':'up','unit':'dimensionless','meaning':'Synthetic same-group twice nominal diagnostic','source':source}],'sources':[source]}
        cp=emit(base/f'cohort-{mass}.json',cohort)
        states=[{'id':'rejected','regions':[]}]+[{'id':b['id'],'regions':[b['id']]} for b in bins]
        response={'schema_version':1,'point_identity_sha256':ip['sha256'],'component_id':'associated','cohort_sha256':cp['sha256'],'region_ids':[b['id'] for b in bins],
                  'joint_states':states,'events':[{'event_id':e['event_id'],'state_probabilities':{s['id']:float(s['id']==(bins[i]['id'] if i<4 else 'rejected')) for s in states}} for i,e in enumerate(events)],
                  'record_measurable':True,'selection_source':source,'calibration_source':source}
        rp=emit(base/f'response-{mass}.json',response)
        points.append({'id':'p'+str(j),'coordinate':[mass],'identity':ip,'components':[{'id':'associated','rate':{'sigma_pb':.001,'branching_fraction':1.,'source':source},'cohort':None if j and missing_second else cp,'response':None if j and missing_second else rp,'generation':None}],
                       'lifetimes':[{'id':'source','ctau_mm':{'chargino':10.}},{'id':'longer','ctau_mm':{'chargino':15.}}]})
    projections=[{'id':'original','energy_tev':13,'lumi_fb':1.,'background_scaling':'syst','signal_MC':'reuse_exact_cohort','sources':[source]},
                 {'id':'future','energy_tev':13,'lumi_fb':2.,'background_scaling':'stat','signal_MC':'reuse_exact_cohort','sources':[source]}]
    d={'schema_version':1,'source':'Synthetic full LLP API controls; no detector/physics qualification','goal_binding':goal,
       'analysis':{'id':'synthetic-disappearing','energy_tev':13,'lumi_fb':1.,'bins':bins,'unresolved_bins':[],'sources':[source],'transport':'charged_source_required'},
       'axes':[{'id':'mass','unit':'GeV','values':[300,600]}],'points':points,'projection_scenarios':projections,
       'cells':[{'point_id':p['id'],'lifetime_id':t['id'],'projection_id':s['id'],'published_model':None,'template':None,'mc_interpretation':'unqualified'} for p in points for t in p['lifetimes'] for s in projections],
       'mixture_sampling':{'kind':'independent_component_experiments','source':source},'generation_policy':emit(base/'g-policy.json',policy()),'inference_policy':emit(base/'i-policy.json',policy()),
       'child_seconds':{'generation':60,'inference':60},'assumptions':['All source laws and masks are synthetic inert controls; every physical input needs independent review.']}
    return d


def task(base,d): return {'input':emit(base/'request.json',d)['path']}


def run(base,d): return op.run(task(base,d),base,base/'output')


def replace_cohort(base,d,change):
    c=d['points'][0]['components'][0];doc=read(c['cohort']);change(doc);c['cohort']=emit(base/'changed-cohort.json',doc)
    response=read(c['response']);response['cohort_sha256']=c['cohort']['sha256'];c['response']=emit(base/'changed-response.json',response)


def test_complete_requested_plane_population_and_original_exposure(tmp_path):
    d=fixture(tmp_path);r=run(tmp_path,d)
    assert len(r['points'])==2 and len(r['cells'])==8 and r['blocked_cells']==8
    comp=r['points'][0]['components'][0]
    assert comp['original_exposure']['event_count']==5 and comp['original_exposure']['group_count']==4
    assert r['points'][0]['values'][:4]==[.25]*4
    assert r['points'][0]['values'][8:12]==[.5]*4
    assert all('exact-point' in ' '.join(c['obligations']) for c in r['cells'][4:])
    assert r['original_task_complete'] is False and r['generated_events']==r['fits']==0
    assert any('Source-calibrated' in x for x in r['cells'][4]['obligations'])
    assert all(Path(p['path']).is_file() for p in r['output_inventory'])


def test_joint_multiple_particle_ratio_and_empty_product():
    particles=[{'species':'a','proper_length_mm':3},{'species':'b','proper_length_mm':4}]
    r=op.lifetime_ratio(particles,{'a':2.,'b':5.},{'a':3.,'b':7.})
    expected=(2/3)*(5/7)*math.exp(3*(1/2-1/3)+4*(1/5-1/7))
    assert r['ratio']==pytest.approx(expected) and op.lifetime_ratio([],{'a':2.},{'a':3.})['ratio']==1


def test_fixed_n_centered_cross_lifetime_covariance_not_poisson():
    value=mr.empirical_group_mean([[0.,0.],[2.,4.]],3.)
    assert value['values']==[3.,6.] and value['covariance']==[[9.,18.],[18.,36.]]
    assert value['scope'].startswith('estimated_centered') and value['likelihood_inferred'] is False
    assert mr.empirical_group_mean([[4.,8.]],1.)['covariance'] is None


def test_lifetime_no_reweighted_denominator_or_probability_renormalization(tmp_path):
    d=fixture(tmp_path);r=run(tmp_path,d);point=r['points'][0]
    target=[(10/15)*math.exp(i*10*(1/10-1/15))/4 for i in range(4)]
    assert point['values'][4:8]==pytest.approx(target)
    assert math.fsum(target)!=pytest.approx(1.)
    assert point['covariance'][0][4]!=0  # same underlying event at both lifetimes


def test_all_weights_zero_rejection_and_overlapping_joint_masks(tmp_path):
    d=fixture(tmp_path);c=d['points'][0]['components'][0];rp=read(c['response'])
    rp['joint_states'].append({'id':'both','regions':['s0','c0']})
    for e in rp['events']:e['state_probabilities']['both']=0.
    rp['events'][0]['state_probabilities']['s0']=0.;rp['events'][0]['state_probabilities']['both']=1.
    c['response']=emit(tmp_path/'overlap.json',rp);r=run(tmp_path,d)
    assert r['points'][0]['values'][:4]==[.25,.25,.5,.25]
    assert r['points'][0]['components'][0]['weight_names']==['nominal','up']


@pytest.mark.parametrize('mutation', ['missing-event','reordered-event','foreign-model','noncanonical-mask','bad-simplex','missing-region'])
def test_complete_calibrated_source_custody_refusals(tmp_path,mutation):
    d=fixture(tmp_path);c=d['points'][0]['components'][0];rp=read(c['response'])
    if mutation=='missing-event':rp['events'].pop()
    if mutation=='reordered-event':rp['events'].reverse()
    if mutation=='foreign-model':rp['point_identity_sha256']='0'*64
    if mutation=='noncanonical-mask':rp['joint_states'].append({'id':'both','regions':['c0','s0']})
    if mutation=='bad-simplex':rp['events'][0]['state_probabilities']['s0']=.9
    if mutation=='missing-region':rp['region_ids'].pop()
    c['response']=emit(tmp_path/'bad.json',rp)
    with pytest.raises(ValueError):run(tmp_path,d)


def test_new_mass_cohort_cannot_borrow_old_acceptance(tmp_path):
    d=fixture(tmp_path);d['points'][1]['components'][0]['cohort']=d['points'][0]['components'][0]['cohort'];d['points'][1]['components'][0]['response']=d['points'][0]['components'][0]['response']
    with pytest.raises(ValueError,match='mass/spectrum/process'):run(tmp_path,d)


@pytest.mark.parametrize('law',['right_censored','forced_or_truncated'])
def test_unsupported_sampling_branch_preserves_full_cells(tmp_path,law):
    d=fixture(tmp_path);replace_cohort(tmp_path,d,lambda c:c['sampling'].update(decay_law=law))
    r=run(tmp_path,d);assert len(r['cells'])==8 and r['points'][0]['components'][0]['moments'] is None
    assert 'supported joint sampling density' in r['cells'][0]['obligations'][0]


def test_infinite_ratio_second_moment_retains_prediction_and_new_anchor_needs(tmp_path):
    d=fixture(tmp_path);d['points'][0]['lifetimes'][1]['ctau_mm']['chargino']=20.
    r=run(tmp_path,d);c=r['cells'][2]
    assert c['predictions'] and c['additional_source_cohort_requirements'][0]['required_new_source_ctau_mm_strictly_greater_than']=={'chargino':10.}
    assert 'variance' in ' '.join(c['obligations'])


def test_literal_weight_convention_and_full_fixed_n_divisor(tmp_path):
    d=fixture(tmp_path);replace_cohort(tmp_path,d,lambda c:c['sampling'].update(divisor=3))
    with pytest.raises(ValueError,match='all original'):run(tmp_path,d)


def test_unknown_weight_units_is_evidence_needed_not_invented_normalization(tmp_path):
    d=fixture(tmp_path);replace_cohort(tmp_path,d,lambda c:c['sampling'].update(weight_unit='pb'))
    r=run(tmp_path,d);assert r['points'][0]['components'][0]['moments'] is None
    assert 'Weight units' in r['cells'][0]['obligations'][0]


def test_unknown_component_dependence_not_independent_covariance(tmp_path):
    d=fixture(tmp_path);point=d['points'][0];doc=read(point['identity']);doc['components'].append({**deepcopy(doc['components'][0]),'id':'other'})
    point['identity']=emit(tmp_path/'two-components.json',doc)
    for c in point['components']:
        cp=read(c['cohort']);cp['point_identity_sha256']=point['identity']['sha256'];c['cohort']=emit(tmp_path/'join-cohort.json',cp)
        rp=read(c['response']);rp['point_identity_sha256']=point['identity']['sha256'];rp['cohort_sha256']=c['cohort']['sha256'];c['response']=emit(tmp_path/'join-response.json',rp)
    other=deepcopy(point['components'][0]);other.update(id='other',cohort=None,response=None);point['components'].append(other)
    d['mixture_sampling']['kind']='unknown';r=run(tmp_path,d)
    assert 'Shared/correlated' in ' '.join(r['points'][0]['obligations'])


def test_complete_mixed_spectrum_uses_literal_rates_and_independent_experiments(tmp_path):
    d=fixture(tmp_path);point=d['points'][0];ident=read(point['identity']);ident['components'].append({**deepcopy(ident['components'][0]),'id':'other','process':'different source channel'})
    point['identity']=emit(tmp_path/'mixed-point.json',ident)
    first=point['components'][0];second=deepcopy(first);second['id']='other';second['rate']['sigma_pb']=.002;second['rate']['branching_fraction']=.5
    point['components'].append(second)
    for i,c in enumerate(point['components']):
        cp=read(c['cohort']);cp['point_identity_sha256']=point['identity']['sha256'];cp['component_id']=c['id'];c['cohort']=emit(tmp_path/f'mix-cohort-{i}.json',cp)
        rp=read(c['response']);rp['point_identity_sha256']=point['identity']['sha256'];rp['component_id']=c['id'];rp['cohort_sha256']=c['cohort']['sha256'];c['response']=emit(tmp_path/f'mix-response-{i}.json',rp)
    r=run(tmp_path,d);p=r['points'][0];a,b=p['components']
    assert p['values'][:4]==[.5]*4
    assert p['covariance'][0][4]==pytest.approx(a['moments']['covariance'][0][4]+b['moments']['covariance'][0][4])
    assert [c['physical_scale_sigma_BR_L'] for c in p['components']]==[1.,1.]


def test_zero_rate_preserves_full_cohort_with_explicit_surrogate_raw_moments(tmp_path):
    d=fixture(tmp_path);d['points'][0]['components'][0]['rate']['sigma_pb']=0.;r=run(tmp_path,d)
    c=r['points'][0]['components'][0]
    assert all(x==0 for x in c['moments']['values']) and c['original_exposure']['event_count']==5
    assert 'surrogate' in c['raw_moment_scope'] and c['physical_scale_sigma_BR_L']==0


def test_signed_subevents_are_grouped_once_and_all_crossweight_moments_retained(tmp_path):
    d=fixture(tmp_path)
    def add(c):
        c['events'][0]['weights']['nominal']=2.;c['events'][-1]['weights']['nominal']=-1.
        c['events'][-1]['group_id']='g0'
    replace_cohort(tmp_path,d,add);r=run(tmp_path,d);c=r['points'][0]['components'][0]
    assert c['original_exposure']['group_count']==4
    assert len(c['moments']['covariance'])==16 and c['normalized_group_marks']['g0'][0]==.5
    assert c['moments']['scope'].startswith('estimated_centered')


def generation(base,d,point_index=1):
    from svj_fixtures import config, write
    point=d['points'][point_index];component=point['components'][0]
    cfg=config(base/'generator','unmerged_lo')
    cfg['cards']['parameter']=write(base/'generator/param.dat','BLOCK MASS\n 1000024 '+str(point['coordinate'][0])+'\nDECAY 1000024 0\n')
    from model_validation_fixture import record_model_events_validation
    record_model_events_validation(cfg,base/'generator/validation')
    cp=emit(base/'generator/config.json',cfg)
    prep={'schema_version':1,'config':{k:cp[k] for k in ('path','sha256')},'review_policy':{k:d['generation_policy'][k] for k in ('path','sha256')},'supervisor_seconds':90,'goal_binding':d['goal_binding']}
    component['generation']=emit(base/'generation-request.json',prep)
    target={'schema_version':1,'point_identity_sha256':point['identity']['sha256'],'component_id':component['id'],
            'beam_type':[1,1],'beam_pdg':[2212,2212],'energy_gev':[6500,6500],
            'model_manifest':op.gen._generated_pin(cfg['model_tree']['manifest']['path']),
            'process_card':op.gen._generated_pin(cfg['cards']['process']['path']),
            'parameter_card':op.gen._generated_pin(cfg['cards']['parameter']['path']),
            'coordinate_parameters':[{'axis_id':'mass','unit':'GeV','parameter':{'block':'MASS','indices':[1000024]}}],
            'mass_parameters':[{'id':'chargino','parameter':{'block':'MASS','indices':[1000024]}}],
            'decay':cfg['decay'],'sources':d['analysis']['sources']}
    component['generation_target']=emit(base/'generation-target.json',target)
    return cfg,target


def test_existing_generation_blueprint_keeps_original_parent_and_full_inputs(tmp_path):
    d=fixture(tmp_path);generation(tmp_path,d)
    r=run(tmp_path,d);child=r['points'][1]['components'][0]['generation']
    assert child['new_events_generated']==0 and read(child['specification'])['goal_binding']==d['goal_binding']
    assert len(op.inputs(task(tmp_path,d),tmp_path))>len(d['points'])


def test_generated_response_drift_refuses_success_and_keeps_failed_population(tmp_path,monkeypatch):
    d=fixture(tmp_path);original=op._projection_workspace;pub,t=published(tmp_path/'published',[.25]*4)
    d['cells'][0].update(published_model=pub,template=t)
    def drift(*args,**kwargs):
        result=original(*args,**kwargs)
        path=tmp_path/'output/points/p0/associated/lifetime-trace.json';path.write_text('{}');return result
    monkeypatch.setattr(op,'_projection_workspace',drift)
    with pytest.raises(ValueError,match='generated recipe changed'):run(tmp_path,d)
    assert not (tmp_path/'output/llp-plane-recipe.json').exists()


def test_complete_trace_budget_refuses_before_lifetime_transform(tmp_path,monkeypatch):
    d=fixture(tmp_path)
    # Lowering the test-only adapter constant isn't necessary: an added full
    # named-weight basis makes the declared covariance work exceed its cap.
    def wide(c):
        for e in c['events']:
            e['weights'].update({f'w{i}':1. for i in range(65)})
        c['weight_definitions'] += [{'id':f'w{i}','unit':'dimensionless','meaning':'Wide synthetic mark','source':c['sources'][0]} for i in range(65)]
    replace_cohort(tmp_path,d,wide)
    monkeypatch.setattr(op,'lifetime_ratio',lambda *_: (_ for _ in ()).throw(AssertionError('must refuse before transformation')))
    with pytest.raises(ValueError,match='bounded complete'):run(tmp_path,d)


def test_same_cohort_projection_central_f_and_covariance_f_squared(tmp_path):
    r=run(tmp_path,fixture(tmp_path));a,b=r['cells'][:2]
    assert b['predictions']['nominal']==[2*x for x in a['predictions']['nominal']]
    assert b['covariance_scale']==4 and a['covariance_scale']==1


def test_new_energy_is_source_required_not_luminosity_scaling(tmp_path):
    d=fixture(tmp_path);d['projection_scenarios'][1]['energy_tev']=13.6;r=run(tmp_path,d)
    assert 'New beam energy' in ' '.join(r['cells'][1]['obligations'])


def test_projection_preserves_fixed_signal_mc_and_source_nuisances():
    ws={'channels':[{'name':'SR','samples':[{'name':'signal','data':[2.],'modifiers':[{'name':'mu','type':'normfactor','data':None},{'name':'mc','type':'staterror','data':[.4]},{'name':'sys','type':'normsys','data':{'hi':1.2,'lo':.8}},{'name':'shape','type':'histosys','data':{'hi_data':[2.5],'lo_data':[1.5]}}]},{'name':'bg','data':[10.],'modifiers':[{'name':'bgmc','type':'staterror','data':[2.]}]}]}],'observations':[{'name':'SR','data':[10.]}],'measurements':[]}
    projected=op._projection_workspace(ws,{('SR','signal')},4.,'stat');s,b=projected['channels'][0]['samples']
    assert s['data']==[8.] and s['modifiers'][1]['data']==[1.6] and b['modifiers'][0]['data']==[4.]
    assert s['modifiers'][2]['data']==ws['channels'][0]['samples'][0]['modifiers'][2]['data']
    assert s['modifiers'][3]['data']=={'hi_data':[10.],'lo_data':[6.]}
    assert op._projection_workspace(ws,{('SR','signal')},1.,'stat')==ws


def test_full_signal_workspace_inputs_and_ordinary_fixed_n_obligation(tmp_path):
    d=fixture(tmp_path);pub,template=published(tmp_path/'published',[.25]*4)
    for c in d['cells'][:2]:c.update(published_model=pub,template=template)
    r=run(tmp_path,d);assert r['prepared_cells']==2
    for c in r['cells'][:2]:
        assert c['workspace'] and c['inference_specification'] is None and 'covariance is not a likelihood' in ' '.join(c['obligations'])


def test_existing_poisson_all_bin_inference_route_prepared_not_executed(tmp_path):
    d=fixture(tmp_path,design='independent_Poisson_groups');pub,template=published(tmp_path/'published',[.25]*4)
    t=read(template)
    for channel in t['channels']:
        for s in channel['samples']:s['mc_stat']['sumw2']=[.0625]*2
    template=emit(tmp_path/'matching-template.json',t)
    d['cells'][0].update(published_model=pub,template=template,mc_interpretation='supplied_Poissonized_groups_and_source_MC_constraints')
    r=run(tmp_path,d);c=r['cells'][0]
    assert c['state']=='prepared_unapproved' and read(c['inference_specification'])['mode']=='signal-template'
    assert read(c['inference_specification'])['goal_binding']==d['goal_binding']


def test_unknown_joint_second_moment_blocks_statistical_input_admission(tmp_path):
    d=fixture(tmp_path,design='independent_Poisson_groups');pub,t=published(tmp_path/'published',[.25]*4)
    replace_cohort(tmp_path,d,lambda c:c['sampling'].update(joint_second_moment='unknown'))
    d['cells'][0].update(published_model=pub,template=t,mc_interpretation='supplied_Poissonized_groups_and_source_MC_constraints')
    r=run(tmp_path,d);assert r['cells'][0]['inference_specification'] is None and r['cells'][0]['predictions']
    assert 'Joint weight/selection' in ' '.join(r['cells'][0]['obligations'])


def test_ordered_weight_definitions_refuse_label_reuse(tmp_path):
    d=fixture(tmp_path)
    def change(c):c['events'][0]['weights']={'up':2.,'nominal':1.}
    replace_cohort(tmp_path,d,change)
    with pytest.raises(ValueError,match='ordered source-defined weights'):run(tmp_path,d)


def test_nonfinite_or_unrepresentable_lifetime_is_not_zeroed():
    with pytest.raises(ValueError,match='unrepresentable'):
        op.lifetime_ratio([{'species':'a','proper_length_mm':2000.}],{'a':1.},{'a':.5})


def test_unsupported_projected_modifier_is_not_silently_left_unchanged():
    workspace={'channels':[{'name':'SR','samples':[{'name':'signal','data':[1.],'modifiers':[{'type':'invented','data':None}]}]}]}
    with pytest.raises(ValueError,match='unsupported projection'):op._projection_workspace(workspace,{('SR','signal')},2.,'syst')


def test_actual_public_plan_full_inputs_binding_and_report(tmp_path):
    d=fixture(tmp_path);t=task(tmp_path,d)
    spec={'schema_version':2,'mode':'llp-plane-recipe','source':d['source'],'assumptions':d['assumptions'],'max_seconds':60,'approval_mode':'physicist','max_attempts':1,'task':t,'review_policy':policy(),'goal_binding':d['goal_binding']}
    science.validate(spec);files=science.task_inputs(spec,tmp_path)
    assert Path(d['points'][0]['components'][0]['cohort']['path']) in files
    assert Path(read(d['points'][0]['identity'])['spectrum']['path']) in files
    science.plan(tmp_path/'ordinary',emit(tmp_path/'science.json',spec)['path'])
    science.verify_plan(tmp_path/'ordinary',approved=False)
    r=op.run(t,tmp_path,tmp_path/'recipe-out');report=op.write_report(r,tmp_path/'report')
    assert report[0]['complete_cell_count']==8
    from ravel.physics.science_worker import diagnostic_presentation
    assert diagnostic_presentation('llp-plane-recipe',r)[0]['original_task_complete'] is False


def test_whole_grid_omissions_outer_parent_drift_and_ending_source_refuse(tmp_path,monkeypatch):
    d=fixture(tmp_path);d['points'].pop()
    with pytest.raises(ValueError,match='entire ordered'):op.inputs(task(tmp_path,d),tmp_path)
    d=fixture(tmp_path/'fresh');spec={'task':task(tmp_path/'fresh',d),'goal_binding':{**d['goal_binding'],'assignment_id':'foreign'}}
    with pytest.raises(ValueError,match='outer goal'):op.inputs_for_spec(spec,tmp_path)
    original=op._component
    def mutate(*args,**kwargs):
        result=original(*args,**kwargs);Path(d['analysis']['sources'][0]['path']).write_text('{}');return result
    monkeypatch.setattr(op,'_component',mutate)
    with pytest.raises(ValueError,match='artifact'):op.run(spec['task'],tmp_path,tmp_path/'drift-out')
