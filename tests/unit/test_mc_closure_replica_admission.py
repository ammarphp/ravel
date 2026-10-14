"""UNRUN consumer regressions with fabricated complete replicas and mocked authority.

Capture/canonical analysis/independence/population parsing and the actual _load
admission are exercised when root runs these controls. No actual ROOT/MC data,
production independence, profile/native execution or closure is supplied here.
"""
from copy import deepcopy
from fractions import Fraction as F
import pytest
from ravel.physics import mc_closure as h,root_stream_core as c


@pytest.fixture
def replicas(tmp_path,monkeypatch):
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
        'requirements':save('requirements.json',{'requirements':[{'id':'replica-closure'},{'id':'note'}]}),
        'strategy':strategy,'independence':independence,'cohorts':decls,'partition_protocol':None}
    task={'request':save('request.json',request)}
    def sync():
        # Re-author all fabricated producer declarations consistently so refusal
        # is at the real consumer guard, not an unrelated stale fixture digest.
        for role in ('prediction','heldout'):
            row=next(v for v in loaded.values() if v[2]['samples'][0]['id']==pairs[0][role])
            sample=row[2]['samples'][0]
            actual=[{k:m[k] for k in ('guid','did','entries')}for m in sample['members']]
            sample['normalization']['original_population']=save(sample['id']+'-population.json',{'members':actual})
            population[role]=[{'sample':sample['id'],'dsid':sample['dsid'],'process':sample['process'],
                'members':actual,'normalization':deepcopy(sample['normalization'])}]
            q=row[4]['delivery']['samples'][0]['quantities']['regions']
            q['contract']['normalization']['scale']=c.scale(sample)
            q['state_sha256']=c.digest({'contract':q['contract'],'state':q['state']})
            # Keep the fabricated actual result consistent with the changed
            # complete producer moments. Otherwise a stale projection would
            # refuse before the physical-normalization guard being tested.
            result_pin=decls[role]['stream_result']
            result_path=Path(result_pin['path'])
            result_path.write_bytes(json.dumps({'status':'passed','delivery':row[5]},sort_keys=True).encode())
            decls[role]['stream_result']={'path':str(result_path),
                'sha256':hashlib.sha256(result_path.read_bytes()).hexdigest(),'size':result_path.stat().st_size}
        new=save('independence.json',{'schema_version':1,'kind':'source_declared_independent_complete_MC_replicas',
            'sampling_law':h.LAWS[0],'cohorts':population,'statement':'Inert, not actual production evidence'})
        for row in loaded.values():row[1]['bundle']['files']['closure_production_independence.json']=new
        request['independence']=new
        task['request']=save('request.json',request)
    def sample(role):return next(v[2]['samples'][0] for v in loaded.values() if v[2]['samples'][0]['id']==pairs[0][role])
    sync()
    return SimpleNamespace(task=task,base=root,sample=sample,sync=sync)

def test_distinct_complete_replicas_reach_ordinary_consumer_and_context(replicas):
    result=h._load(replicas.task,replicas.base)
    assert result[-1][0]['result']['basis']==['SR','CR','VR']
    assert result[-1][0]['result']['residual']==['0','0','0']
    assert h.context(replicas.task,replicas.base)['execution_authorized'] is False
    assert h.execution_seconds(replicas.task,replicas.base)==60
    assert h.inputs(replicas.task,replicas.base)


def test_shared_guid_changed_did_rejected_before_contrast(replicas,monkeypatch):
    p,v=replicas.sample('prediction'),replicas.sample('heldout')
    v['members'][0]['guid']=p['members'][0]['guid']
    assert v['members'][0]['did']!=p['members'][0]['did']
    replicas.sync()
    monkeypatch.setattr(h,'contrast',lambda *a:pytest.fail('known reused cohort reached zero-cross contrast'))
    with pytest.raises(ValueError,match='physical GUID'):h._load(replicas.task,replicas.base)


@pytest.mark.parametrize('alias',[
    'file:///fabricated/p.root',
    'file://localhost/fabricated/p.root',
    'file:////fabricated/p.root',
    'file:///fabricated/./p.root',
    'file:///fabricated/x/../p.root',
    'file:///fabricated/%70.root'])
def test_shared_uri_with_relabelled_guid_did_refuses(replicas,alias):
    replicas.sample('heldout')['members'][0]['uri']=alias
    replicas.sync()
    with pytest.raises(ValueError,match='URI alias'):h._load(replicas.task,replicas.base)


def test_remote_host_case_and_default_port_alias_refuses(replicas):
    replicas.sample('prediction')['members'][0]['uri']='root://example.org//data/p.root'
    replicas.sample('heldout')['members'][0]['uri']='root://EXAMPLE.ORG:1094//data/p.root'
    replicas.sync()
    with pytest.raises(ValueError,match='URI alias'):h._load(replicas.task,replicas.base)


@pytest.mark.parametrize('factor', ['cross_section_pb','filter_efficiency','k_factor','luminosity_fb_inverse'])
def test_each_physical_factor_must_match_before_zero_cross(replicas,monkeypatch,factor):
    replicas.sample('heldout')['normalization'][factor]*=2
    replicas.sync()
    monkeypatch.setattr(h,'contrast',lambda *a:pytest.fail('unmatched physical law reached contrast'))
    with pytest.raises(ValueError,match='sigma/filter/K/luminosity'):h._load(replicas.task,replicas.base)


def test_product_equal_different_physical_factors_is_not_declared_transport(replicas):
    norm=replicas.sample('heldout')['normalization']
    norm['cross_section_pb']*=2;norm['filter_efficiency']/=2
    replicas.sync()
    assert c.scale(replicas.sample('prediction'))==c.scale(replicas.sample('heldout'))
    with pytest.raises(ValueError,match='no implicit transport'):h._load(replicas.task,replicas.base)


def test_equal_convention_allows_different_original_signed_denominators(replicas):
    replicas.sample('prediction')['normalization']['sum_weights']=2.
    replicas.sample('heldout')['normalization']['sum_weights']=-4.
    replicas.sync()
    rows=h._load(replicas.task,replicas.base)[-1]
    assert rows[0]['prediction']['scale']=='1/2'
    assert rows[0]['heldout']['scale']=='-1/4'
    assert rows[0]['original_source_entries']=={'prediction':2,'heldout':2}
    assert rows[0]['result']['cross_covariance']==[['0']*3 for _ in range(3)]


def test_fixed_known_alias_hand_oracle_is_not_independence_certificate():
    # Same physical H=P: true cross V cancels; assumed zero would give2V.
    value={'basis':['VR'],'yield':[F(1)],'covariance':[[F(1)]]}
    assert h.contrast(value,value,[['1']],[['1']])['covariance']==[['0']]
    assert h.contrast(value,value,[['1']],[['0']])['covariance']==[['2']]


def test_mismatched_sigma_hand_oracle_is_different_target_not_closure():
    p={'basis':['VR'],'yield':[F(1)],'covariance':[[F(1)]]}
    v={'basis':['VR'],'yield':[F(2)],'covariance':[[F(4)]]}
    assert h.contrast(p,v,[['1']],[['0']])['residual']==['1']
    assert h.contrast(p,v,[['1']],[['0']])['covariance']==[['5']]
    assert h.contrast(p,p,[['1']],[['0']])['covariance']==[['2']]
