"""Prospective original-group moment arithmetic; fabricated independent laws.

No genuine events, cohort access, split independence or physics closure.
"""
from copy import deepcopy
from fractions import Fraction as F
import pytest
from ravel.physics import mc_closure as h,root_stream_core as c


def quantity():
    q={'contract':{'bins':[{'id':'VR'}],'representation':'integrated','normalization':{'kind':'absolute','unit':'events','scale':10.},'weight_names':['nominal']},
        'state':{'sumw':[1.,0.,1.],'second_moment':[[5.,0.,5.],[0.,0.,0.],[5.,0.,5.]],
            'counts':{'records':2,'fills':2,'in_range':2,'flow':0,'empty_records':0},'negative_weight_records':{'nominal':1}}}
    q['state_sha256']=c.digest({'contract':q['contract'],'state':q['state']});return q


def test_signed_group_poissonized_vs_fixed_n_full_exposure_oracle():
    q=quantity();p=h.moments(q,h.LAWS[0]);fixed=h.moments(q,h.LAWS[1])
    assert p['yield']==[F(10)] and p['covariance']==[[F(500)]]
    assert fixed['yield']==[F(10)] and fixed['covariance']==[[F(900)]]
    assert fixed['all_flow_and_counter_retained']==q['state']


def test_shared_cross_block_is_not_independent_covariance():
    pred={'basis':['VR'],'yield':[F(2)],'covariance':[[F(9)]]}
    hold={'basis':['VR'],'yield':[F(3)],'covariance':[[F(4)]]}
    assert h.contrast(pred,hold,[['1']],[['3']])['covariance']==[['7']]
    assert h.contrast(pred,hold,[['1']],[['0']])['covariance']==[['13']]
    reused={'basis':['VR'],'yield':[F(2)],'covariance':[[F(9)]]}
    result=h.contrast(pred,reused,[['1']],[['9']])
    assert result['residual']==['0'] and result['covariance']==[['0']]
    assert result['closure_p_value'] is None and result['coverage_qualified'] is False


def test_full_covariance_linear_transfer_preserves_overlapping_validation():
    p={'basis':['CR','VR'],'yield':[F(2),F(3)],'covariance':[[F(4),F(2)],[F(2),F(9)]]}
    v={'basis':['CR','VR'],'yield':[F(5),F(9)],'covariance':[[F(16),F(3)],[F(3),F(25)]]}
    result=h.contrast(p,v,[['1','0'],['0','2']],[[0,0],[0,0]])
    assert result['residual']==['3','3'] and result['covariance']==[['20','7'],['7','61']]


@pytest.mark.parametrize('mutate',[
    lambda q:q['state']['counts'].__setitem__('records',1),
    lambda q:q['contract'].__setitem__('weight_names',['nominal','var']),
    lambda q:q['contract']['normalization'].__setitem__('kind','normalized'),
    lambda q:q['state']['second_moment'][0].__setitem__(0,0)])
def test_fixed_n_counter_signed_cancellation_and_source_domain_refusals(mutate):
    q=quantity();mutate(q);q['state_sha256']=c.digest({'contract':q['contract'],'state':q['state']})
    with pytest.raises(ValueError):h.moments(q,h.LAWS[1])


def test_full_order_and_moment_commitment_cannot_be_relabelled():
    q=quantity();q['state']['sumw'][0]=3
    with pytest.raises(ValueError,match='moment state'):h.moments(q,h.LAWS[0])
    p={'basis':['VR'],'yield':[F(1)],'covariance':[[F(1)]]}
    with pytest.raises(ValueError,match='ordered'):h.contrast(p,{**p,'basis':['SR']},[['1']],[[0]])


def test_ordinary_closure_mode_preserves_whole_question_and_no_observed_law():
    from ravel.workflow.science import adapter
    assert adapter({'mode':'mc-closure','task':{'request':{}}}) is h


@pytest.mark.parametrize('law',[h.LAWS[2],h.LAWS[3]])
def test_group_law_uses_complete_group_count_not_entry_count(law):
    q=quantity();result=h.moments(q,law)
    assert result['full_units']==2 and result['independent_unit']=='physical_group'
    assert result['covariance']==[[F(500 if law==h.LAWS[2] else 900)]]


def test_incomplete_partition_never_becomes_heldout_validation():
    cfg={'schema_version':2,'partitioning':{'operation':'partition'}}
    with pytest.raises(ValueError,match='MERGE'):
        h.full_transport(cfg,{}, {},{},'.',None,{},h.LAWS[0])
    ds={'samples':[{'id':'b','members':[{'entries':10}]}]}
    full={'delivery':{'sampling_law':'poissonized_independent_physical_events_with_event_common_weights'}}
    assert h.full_transport({'schema_version':1},ds,{},full,'.',None,None,h.LAWS[0])=={'b':10}
    with pytest.raises(ValueError,match='groups require'):
        h.full_transport({'schema_version':1},ds,{},full,'.',None,None,h.LAWS[2])


def test_ordinary_complete_replica_caller_binds_strategy_full_exposure_and_sf(tmp_path,monkeypatch):
    """Real consumer/Capture reads, explicitly mocked ROOT and role authority."""
    from pathlib import Path
    from types import SimpleNamespace
    from ravel.workflow import science
    from test_mc_expected_construction import selection_recipe
    import hashlib,json
    root=tmp_path.resolve()/'inputs';root.mkdir()
    def save(name,value,raw=False):
        p=root/name;p.write_bytes(value if raw else json.dumps(value,sort_keys=True).encode())
        return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size}
    r=selection_recipe();source=save('source.json',{'scientific_independence':'fabricated engineering premise'})
    r['fitted_categories']['source']=source;r['sf_applicability'][0]['source']=source
    goal=save('goal.json',{'whole_question':'fabricated analysis, no actual physics'})
    kernel=save('kernel.py',h.h.kernel_bytes(r),raw=True)
    branches=[{'name':n,'shape':'scalar','dtype':'float32','unit':'1'} for n in h.h.required_branches(r)]
    analysis=h.h.analysis_document(r,branches,goal,kernel)
    pairs=[{'prediction':'p','heldout':'v'}]
    strategy=save('strategy.json',{'schema_version':1,'selection_recipe':r,'branch_contract':branches,
        'prediction_operator':[['1','0','0'],['0','1','0'],['0','0','1']], 'sampling_law':h.LAWS[0],
        'normalization_treatment':'conditional_on_original_full_generator_denominator','sample_pairs':pairs,'statement':'Frozen fabricated source'})
    loaded={};population={};decls={}
    for role,sid in (('prediction','p'),('heldout','v')):
        members=[{'id':sid,'guid':'guid-'+sid,'did':'did-'+sid,'uri':'file:///fabricated/'+sid+'.root','entries':2}]
        orig=save(sid+'-population.json',{'members':[{k:m[k] for k in ('guid','did','entries')}for m in members]})
        norm={'original_population':orig,'sum_weights':1.,'luminosity_fb_inverse':1.,
            'cross_section_pb':.001,'filter_efficiency':1.,'k_factor':1.}
        ds={'samples':[{'id':sid,'dsid':100,'process':'background','kind':'background_mc','members':members,'normalization':norm}]}
        q={'contract':{'bins':[{'id':region['id']}for region in r['regions']], 'representation':'integrated',
            'normalization':{'kind':'absolute','unit':'events','scale':1.},'weight_names':['nominal']},
            'state':{'sumw':[1.,2.,3.,0.,1.],'second_moment':[[float(i==j)*10 for j in range(5)]for i in range(5)],
                'counts':{'records':2},'negative_weight_records':{'nominal':0}}}
        q['state_sha256']=c.digest({'contract':q['contract'],'state':q['state']})
        native={'delivery':{'sampling_law':'poissonized_independent_physical_events_with_event_common_weights',
            'samples':[{'id':sid,'quantities':{'regions':q}}]}}
        cfg={'schema_version':1,'bundle':{'files':{'kernel.py':kernel,'closure_frozen_strategy.json':strategy}}}
        cp=save(sid+'-config.json',cfg);task={'config':cp};tp=save(sid+'-task.json',task)
        public={'kind':'fabricated root public projection','samples':native['delivery']['samples']}
        rp=save(sid+'-root-stream-result.json',{'status':'passed','delivery':public})
        directory=root/sid;directory.mkdir();canonical=directory/'root-stream-result.json';canonical.write_bytes(Path(rp['path']).read_bytes())
        rp={**rp,'path':str(canonical)}
        decls[role]={'stream_task':tp,'stream_result':rp,'stream_closure':save(sid+'-closure.json',{'fabricated':True})}
        loaded[cp['path']]=(Path(cp['path']),cfg,ds,deepcopy(analysis),native,public)
        population[role]=[{'sample':sid,'dsid':100,'process':'background','members':[{k:m[k]for k in ('guid','did','entries')}for m in members], 'normalization':norm}]
    independence=save('independence.json',{'schema_version':1,'kind':'source_declared_independent_complete_MC_replicas',
        'sampling_law':h.LAWS[0],'cohorts':population,'statement':'Inert, not actual production evidence'})
    for row in loaded.values():row[1]['bundle']['files']['closure_production_independence.json']=independence
    # _load/native/private/approval are explicit fakes. Consumer parsing, source
    # canonical comparison, full-exposure and arithmetic are real code here.
    monkeypatch.setattr(h.stream,'_load',lambda task,base,cap:loaded[task['config']['path']][:4])
    def guard(result,base):
        row=next(v for v in loaded.values() if v[5]==result['delivery'] and Path(v[0]).stem.startswith(Path(base).name))
        return SimpleNamespace(native_outputs={},native=row[4],original={'config':row[1],'dataset':row[2],'analysis':row[3]},finish=lambda *_:None)
    monkeypatch.setattr(h.stream,'guard',guard)
    monkeypatch.setattr(h.stream,'ordinary_stream_delivery',lambda *a:{'rundir':str(root/'fake-role')})
    monkeypatch.setattr(h.stream,'private_delivery',lambda guard:(guard.native,guard.original))
    monkeypatch.setattr(h.stream,'public_delivery',lambda native,ds,a:next(v[5]for v in loaded.values()if v[4]is native))
    monkeypatch.setattr(science,'review_waypoint_paths',lambda *_:[])
    request={'schema_version':2,'original_goal':goal,'goal_binding':{'assignment_id':'whole'},
        'requirements':save('requirements.json',{'requirements':[{'id':'closure-validated'},{'id':'heldout-agreement'}]}),
        'strategy':strategy,'independence':independence,'cohorts':decls,'partition_protocol':None}
    task={'request':save('request.json',request)}
    result=h._load(task,root);assert len(result[-1])==1 and result[-1][0]['result']['basis']==['SR','CR','VR']
    for bad in ({'requirements':[]},{'requirements':[{'id':'a'},{'id':'a'}]},{'requirements':[{'id':'a'}],'extra':1}):
        unsupported={**request,'requirements':save('bad-requirements.json',bad)}
        with pytest.raises(ValueError,match='roster|requirement'):h._load({'request':save('bad-request.json',unsupported)},root)
    configured=next(iter(loaded.values()))
    original=deepcopy(configured[3]);configured[3]['weight_contract'].pop('derived_factor')
    with pytest.raises(ValueError,match='SF'):h._load(task,root)
    configured[3].clear();configured[3].update(original)
    configured[3]['quantities'][0]['contract']['bins'][0]['id']='CR'
    with pytest.raises(ValueError,match='mapping'):h._load(task,root)


def test_full_parent_normalization_hand_oracle_is_not_a_fold_execution_claim():
    # RS1 oracle9: full parent generator sum100; inclusion1/4 vs3/4 and
    # selected10 vs30. Both scale to40. This is arithmetic only; no original
    # group split/access chronology, fold producer or covariance is fabricated.
    assert F(10)/F(1,4)==F(30)/F(3,4)==40
    assert F(100)/F(100)==1
