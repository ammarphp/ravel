"""Complete synthetic control cohorts; no ATLAS response/limits are claimed."""
from copy import deepcopy
from fractions import Fraction
import hashlib,io,json,math,subprocess,tarfile
from pathlib import Path
import pytest
from ravel.physics import svj_recipe as op, detector_response as dr, published_model as pm, signal_templates as st
from ravel.workflow import science, task_completion as tc, route_prompt
from svj_fixtures import config, policy, write


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}


def emit(path,doc):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(doc,allow_nan=False) if not isinstance(doc,str) else doc)
    return pin(path)


def ref(path,doc):
    p=emit(path,doc);return {'id':path.stem,'path':p['path'],'sha256':p['sha256'],'reference':'Synthetic complete engineering cohort, not calibrated physics.'}


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    def refuse(*args,**kwargs):raise AssertionError('native/provider/external dispatch is forbidden')
    monkeypatch.setattr(subprocess,'Popen',refuse)
    # The real CLI records OS provenance; avoid its platform-only uname helper.
    import platform
    monkeypatch.setattr(platform._Processor,'get',staticmethod(lambda:'synthetic-platform-control'))
    monkeypatch.setattr(platform,'architecture',lambda *a,**k:('64bit','synthetic-platform-control'))


def parent(base):
    prompt='Study the complete semi-visible-jet mediator/darkpion/darkrho/invisible grid with joint tagger and background scenarios at the original Run2 luminosity; report expected limits and uncertainty.'
    doc=route_prompt.route(prompt);req=tc.initial_requirements(prompt)
    req['assignments']=[{'id':'svj','purpose':'Prepare the full source-bound grid and all conditional quantities','coverage':[{'obligation_id':'original-request','criteria':{'request':prompt}}]}]
    doc['task_requirements']=req
    return {'contract':emit(base/'inputs/task_contract.json',doc),'assignment_id':'svj'}


def hidden(base,rinv=.5):
    c=config(base,'mlm');c['generation']['jet_multiplicities']=[0,1,2]
    proc=Path(c['cards']['process']['path']);proc.write_text(proc.read_text()+'add process p p > t t~ j j\n');c['cards']['process']={k:pin(proc)[k] for k in ('path','sha256')}
    par=Path(c['cards']['parameter']['path']);par.write_text(par.read_text()+'BLOCK HIDDEN\n 1 1500\n');c['cards']['parameter']={k:pin(par)[k] for k in ('path','sha256')}
    c['shower']['merging_scale_gev']=100;c['shower']['max_jets']=2
    settings={'HiddenValley:Ngauge':2,'HiddenValley:nFlav':1,'HiddenValley:FSR':True,'HiddenValley:fragment':True,'HiddenValley:alphaOrder':1,'HiddenValley:Lambda':10,'HiddenValley:pTminFSR':11,'HiddenValley:probVector':.75}
    masses={'4900111':10.,'4900113':20.,'4900211':4.,'4900213':9.}
    decays=[]
    for pdg in (4900211,4900213):decays.extend([[str(pdg)+':mayDecay','off'],[str(pdg)+':isVisible','off']])
    for pdg,other in ((4900111,4900211),(4900113,4900213)):
        decays.extend([[str(pdg)+':mayDecay','on'],[str(pdg)+':oneChannel','1 '+str(1-rinv)+' 100 1 -1'],[str(pdg)+':addChannel','1 '+str(rinv)+' 100 '+str(other)+' -'+str(other)]])
    pythia=Path(c['cards']['pythia']['path']);raw=pythia.read_text().replace('qCut = 30','qCut = 100').replace('nJetMax = 1','nJetMax = 2')
    raw+='\n'.join(k+' = '+('on' if v is True else 'off' if v is False else str(v)) for k,v in settings.items())+'\n'
    raw+='\n'.join(k+':m0 = '+str(v) for k,v in masses.items())+'\n'
    raw+='\n'.join(k+' = '+v for k,v in decays)+'\n';pythia.write_text(raw);c['cards']['pythia']={k:pin(pythia)[k] for k in ('path','sha256')}
    contract={'schema_version':1,'parameter_bindings':[{'axis':'mediator_GeV','block':'HIDDEN','codes':[1]}],'particle_mass_bindings':[{'axis':'dark_pion_GeV','pdg':4900111},{'axis':'dark_rho_GeV','pdg':4900113}],'decay_fraction_bindings':[{'axis':'r_inv','pdg':4900111},{'axis':'r_inv','pdg':4900113}],'visible_pdgs':[1,2,3,4,5],'settings':settings,'particle_masses':masses,'invisible_pdgs':[4900211,4900213],'decays':decays,'source_pins':[emit(base/'synthetic-shower-source.json',{'qualified':False})],'assumptions':['Inert pp->ttbar process is a source/API stand-in only, not an SVJ matrix element or shower.']}
    from model_validation_fixture import record_model_events_validation
    record_model_events_validation(c,base/'validation')
    return emit(base/'generation.json',c),emit(base/'shower-contract.json',contract)


def response(base,*,background=False,overlap=False):
    base.mkdir(parents=True,exist_ok=True)
    objects={'schema_version':1,'level':'reconstructed','source':'Synthetic uncalibrated source','energy_unit':'GeV','flags':{'electron':{},'muon':{},'jet':{}},'response_evidence':[],'weight_names':['nominal','twice']}
    cuts={x:{'pt':0.,'eta':5.,'id':0} for x in ('electron','muon','jet')}
    regions=[]
    for name,lo,hi in [('s0',10,20),('s1',20,30),('c0',30,40),('c1',40,50)]:regions.append({'name':name,'cuts':[{'var':'MET','op':'>=','val':lo},{'var':'MET','op':'<','val':hi}]})
    if overlap:regions[1]['cuts']=deepcopy(regions[0]['cuts'])
    selection={'name':'synthetic','objects':cuts,'signal':deepcopy(cuts),'overlap_removal':[],'regions':regions}
    weights=[12.,8.,12.,8.,0.] if background else [4.,1.,2.,1.,0.]
    events=[{'event_id':'e'+str(i),'group_id':'g'+str(i),'weights':{'nominal':w,'twice':2*w},'objects':{'electron':[],'muon':[],'jet':[]},'met':{'pt':met,'phi':0.}} for i,(w,met) in enumerate(zip(weights,[15,25,35,45,0]))]
    e1=deepcopy(events);e1[0]['met']['pt']=0;e1[-1]['met']['pt']=15
    if background:e1[1]['met']['pt']=35
    doc={'schema_version':1,'operation':'fixed_event_migrations','axes':[{'name':'joint_tagger','knots':[0,1]}],'reference_point':{'joint_tagger':0},'weight_name':'nominal','normalization':{'scale':1.,'denominator':'fixed','fixed_denominator':1.,'meaning':'Explicit synthetic absolute marks; no cross section or detector efficiency claim'},'source_pins':[ref(base/'origin.json',{'assumptions':'Supplied same-event hypothetical anchors'})],'object_contract':ref(base/'objects.json',objects),'selection':ref(base/'selection.json',selection),'anchors':[{'point':[0],'events':ref(base/'anchor0.json',events)},{'point':[1],'events':ref(base/'anchor1.json',e1)}]}
    return emit(base/'response.json',doc),doc


def published(base,values,background_values=(12.,8.,12.,8.)):
    base.mkdir(parents=True,exist_ok=True);channels=[];observations=[];ops=[]
    for ci,name in enumerate(('SR','CR')):
        bg={'name':'background','data':list(background_values[ci*2:ci*2+2]),'modifiers':[{'name':'shared','type':'normsys','data':{'hi':1.1,'lo':.9}}]}
        channels.append({'name':name,'samples':[bg]});observations.append({'name':name,'data':[16,9]})
        vals=values[ci*2:ci*2+2];sample={'name':'signal','data':vals,'modifiers':[{'name':'mu','type':'normfactor','data':None},{'name':'shared','type':'normsys','data':{'hi':1.2,'lo':.8}},{'name':'shape','type':'histosys','data':{'hi_data':[v+1 for v in vals],'lo_data':[v/2 for v in vals]}},{'name':'mc_'+name,'type':'staterror','data':vals}]}
        ops.append({'op':'add','path':f'/channels/{ci}/samples/0','value':sample})
    background={'version':'1.0.0','channels':channels,'observations':observations,'measurements':[{'name':'M','config':{'poi':'mu','parameters':[]}}]}
    patchset={'version':'1.0.0','metadata':{'analysis_id':'synthetic','description':'Inert likelihood source control','references':{'hepdata':'synthetic'},'labels':['mass'],'digests':{'sha256':pm.canonical_background_digest(background)}},'patches':[{'metadata':{'name':'point','values':[1500]},'patch':ops}]}
    br,pr=json.dumps(background).encode(),json.dumps(patchset).encode();archive=base/'source.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        for name,raw in [('background.json',br),('patchset.json',pr)]:item=tarfile.TarInfo(name);item.size=len(raw);t.addfile(item,io.BytesIO(raw))
    doc={'schema_version':1,'source':{'record_id':'synthetic','version':1,'resource_id':'fixture','record_url':'https://example.invalid/record','archive_url':'https://example.invalid/archive','doi':'synthetic control'},'archive':{k:pin(archive)[k] for k in ('path','sha256')},'members':{role:{'name':role+'.json','sha256':hashlib.sha256(raw).hexdigest()} for role,raw in [('background',br),('patchset',pr)]},'coordinates':{'mass':1500},'measurement':'M','expected_background_digest':pm.canonical_background_digest(background),'grounding':[],'inference':{'backend':'numpy','fit_tolerance':1e-7,'poi_cap':128,'root_rtol':1e-4,'n_curve':3,'poi_domain_policy':'engine_dynamic_nonnegative','retain_profile_witnesses':True,'witness_limits':{'evaluations':100,'minimizations':1000,'bytes':1048576}}}
    source=pm.load_published_model(doc,base);template=st.identity_template(source,'supplied-signal')
    evidence=emit(base/'prediction.json',{'source':'Synthetic all-bin response at fixed weights; explicit auxiliary assumption'})
    for channel in template['channels']:
        for sample in channel['samples']:
            sample['provenance']={'kind':'supplied_prediction','description':'Synthetic complete SR/CR prediction','evidence':[{k:evidence[k] for k in ('path','sha256')}],'normalization_shape':'source_decomposition'}
            sample['mc_stat']={'mode':'supplied','description':'Explicit independent Poissonized bin assumption; not fixed-N sampling','weight_model':'nonnegative','sumw':sample['data'],'sumw2':[v*v for v in sample['data']]}
    return emit(base/'published.json',doc),emit(base/'template.json',template)


def fixture(base,*,generation=False,missing=False):
    base=base.resolve();base.mkdir(parents=True,exist_ok=True)
    gp,sp=hidden(base/'generator') if generation else (None,None)
    rp,rd=response(base/'signal');bp,bd=response(base/'background',background=True)
    # One zero-weight event remains, and all scenarios share original IDs/weights.
    pub0,t0=published(base/'likelihood0',[4.,1.,2.,1.]);pub1,t1=published(base/'likelihood1',[0.,1.,2.,1.],(0.,0.,20.,8.))
    if missing:pub0=pub1=t0=t1=rp=bp=None
    rs=[{'id':'no_tag','coordinate':[0],'assumptions':['Explicit supplied reconstructed anchor, no learned ROC']},{'id':'joint_tag','coordinate':[1],'assumptions':['Coherent same-event joint selection changes; no efficiency inference']}]
    bs=[{'id':'nominal','published_model':pub0,'response':bp,'anchor':[0] if bp else None,'assumptions':['Source background nuisance model conditional']},{'id':'hypothetical','published_model':pub1,'response':bp,'anchor':[1] if bp else None,'assumptions':['Supplied joint background migration conditional; no fitted extrapolation']}]
    # Background source and signal template are separable: each background must
    # preserve its own nuisance source, with each signal anchor's full prediction.
    extra={}
    for ri,vals in enumerate(([4.,1.,2.,1.],[0.,1.,2.,1.])):
        for bi,bvals in enumerate(((12.,8.,12.,8.),(0.,0.,20.,8.))):
            _,t=published(base/f'cell-{ri}-{bi}',vals,bvals)
            if not missing:
                source_pin=(pub0,pub1)[bi];source=pm.load_published_model(json.loads(Path(source_pin['path']).read_text()),Path(source_pin['path']).parent)
                td=json.loads(Path(t['path']).read_text());td['source_workspace_sha256']=source.manifest()['workspace_compact_sha256'];t=emit(Path(t['path']),td)
            extra[ri,bi]=None if missing else t
    pp={'id':'p0','coordinate':{'mediator_GeV':1500.,'dark_pion_GeV':10.,'dark_rho_GeV':20.,'r_inv':.5},'generation':gp,'shower_contract':sp,'analysis':None,'response':rp}
    d={'schema_version':1,'source':'Synthetic complete recipe/API controls only; no ATLAS physics qualification','goal_binding':parent(base),'analysis':{'id':'ANA-0001','energy_tev':13,'lumi_fb':139,'sources':[emit(base/'analysis-source.json',{'qualified':False})],'bins':[{'id':n,'channel':ch,'sample':'signal','index':i,'role':ch} for ch,names in [('SR',['s0','s1']),('CR',['c0','c1'])] for i,n in enumerate(names)],'unresolved_bins':[],'interpretation':'conditional_extension_not_published_reproduction'},'axes':[{'name':n,'values':[pp['coordinate'][n]]} for n in pp['coordinate']],'points':[pp],'response_scenarios':rs,'background_scenarios':bs,'templates':[{'point_id':'p0','response_id':r['id'],'background_id':b['id'],'template':extra[ri,bi],'mc_interpretation':'supplied_Poissonized_groups_and_source_MC_constraints'} for ri,r in enumerate(rs) for bi,b in enumerate(bs)],'generation_policy':emit(base/'generation-policy.json',policy()),'analysis_policy':emit(base/'analysis-policy.json',policy()),'inference_policy':emit(base/'inference-policy.json',policy()),'child_seconds':{'generation':90,'analysis':60,'inference':60},'assumptions':['Supplied hypothetical detector and background scenarios at original Run2 exposure; no validated efficiency, ML training, fit or exclusion.']}
    d.update(study_id='STUDY-0001',delivery={'format':'json','filename':'supplied-results.json'},coordinate_constraints=[{'axis':'r_inv','min':0,'max':1}],generation_conventions={'generation':{'beam_pdg':[2212,2212],'energy_gev':[6500,6500],'order':'LO','scheme':'mlm','jet_multiplicities':[0,1,2]},'shower':{'backend':'PYTHIA8','merging_scale_gev':100,'max_jets':2}})
    return d


def task(base,d):return {'input':emit(base/'recipe.json',d)['path']}


def spec(t,d):return op._spec('svj-recipe',t,d,policy(),60)


def test_actual_whole_scenario_response_template_and_conditional_expected_specs(tmp_path):
    d=fixture(tmp_path);r=op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert r['prepared_cells']==4 and r['blocked_cells']==0 and len(r['cells'])==4
    assert not r['physics_validated'] and not r['execution_authorized'] and not r['original_task_complete']
    a=json.loads((tmp_path/'out/response-p0/complete-response.json').read_text())
    assert a['events']==5 and len(a['group_ids'])==5 and len(a['joint_weight_anchor_covariance'])==20
    assert a['weights']['nominal']['conditional_group_covariance'][2][7]==4
    assert a['anchor_records'][0][-1]['weights']['nominal']==0
    assert len(list((tmp_path/'out').glob('background-*')))==1
    vals=[]
    for row in r['cells']:
        s=json.loads(Path(row['expected_specification']['path']).read_text());science.validate(s)
        assert s['mode']=='signal-template' and s['task']['operation']=='inference' and s['goal_binding']==d['goal_binding']
        ws=json.loads(Path(row['template_construction']['paths']['workspace.json']['path']).read_text());vals.append(ws)
    assert vals[0]['channels']!=vals[2]['channels'] and vals[0]['channels']!=vals[1]['channels']
    assert [x['files'] for x in op.write_report(r,tmp_path/'out')]
    assert all(Path(p['path']).is_file() for p in r['output_inventory'])


def test_real_generation_prepare_whole_parent_then_unapproved_ordinary_plan(tmp_path):
    d=fixture(tmp_path,generation=True);t=task(tmp_path,d);r=op.run(t,tmp_path,tmp_path/'out')
    g=r['points'][0]['generation'];assert g['new_events_generated']==0 and not g['execution_authorized']
    s=json.loads(Path(g['specification']['path']).read_text());assert s['mode']=='model-events' and s['goal_binding']==d['goal_binding']
    science.plan(tmp_path/'generation-unapproved',g['specification']['path'])
    assert not (tmp_path/'generation-unapproved/inputs/science-approval.json').exists()
    outer=emit(tmp_path/'science.json',spec(t,d));from ravel.cli import main
    assert main(['plan','--rundir',str(tmp_path/'recipe-unapproved'),'--spec',outer['path']])==0
    assert science.verify_plan(tmp_path/'recipe-unapproved',approved=False)['schema_version']==2
    science.plan(tmp_path/'inference-unapproved',r['cells'][0]['expected_specification']['path'])
    assert not (tmp_path/'inference-unapproved/inputs/science-approval.json').exists()


def test_missing_inputs_keep_every_grid_and_all_scenario_cells(tmp_path):
    d=fixture(tmp_path,missing=True);d['axes'][0]['values']=[1500.,2000.];second=deepcopy(d['points'][0]);second['id']='p1';second['coordinate']['mediator_GeV']=2000.;d['points'].append(second)
    cells=deepcopy(d['templates']);d['templates']+= [{**c,'point_id':'p1'} for c in cells]
    r=op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert len(r['points'])==2 and len(r['cells'])==8 and r['blocked_cells']==8 and r['prepared_cells']==0
    assert all(len(c['obligations'])==3 for c in r['cells'])
    assert not list((tmp_path/'out').rglob('expected-science.json'))


def test_real_worker_and_common_report_use_fresh_child_with_authority_mocked(tmp_path,monkeypatch):
    from ravel.physics import science_worker
    d=fixture(tmp_path,missing=True);t=task(tmp_path,d);s=spec(t,d);rd=tmp_path/'worker';rd.mkdir()
    monkeypatch.setattr(science_worker,'verify_worker',lambda rd:{'base_dir':str(tmp_path),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':[]}})
    monkeypatch.setattr(science_worker,'execution_spec',lambda rd:s)
    assert science_worker.main([str(rd)])==0
    result=json.loads((rd/'outputs/attempt-1/result.json').read_text())
    assert result['generated_events']==result['fits']==0 and not result['original_task_complete']
    assert (rd/'outputs/attempt-1/svj-recipe/svj-recipe.json').is_file()
    assert (rd/'outputs/attempt-1/svj-recipe-report/cells.json').is_file()
    assert not list(rd.rglob('*.png'))


@pytest.mark.parametrize('bad',['drop_point','drop_cell','rinv','bool','lumi','cr_missing','duplicate_bin','response_dropped','background_independent','background_noanchor','template_bad','parent_missing','source_drift'])
def test_material_grid_response_source_adversaries(tmp_path,bad):
    d=fixture(tmp_path)
    if bad=='drop_point':d['points']=[]
    elif bad=='drop_cell':d['templates'].pop()
    elif bad=='rinv':d['axes'][-1]['values']=[2.];d['points'][0]['coordinate']['r_inv']=2.
    elif bad=='bool':d['axes'][0]['values']=[True]
    elif bad=='lumi':d['analysis']['lumi_fb']=0
    elif bad=='cr_missing':d['analysis']['bins'].pop()
    elif bad=='duplicate_bin':d['analysis']['bins'].append(deepcopy(d['analysis']['bins'][0]))
    elif bad=='response_dropped':d['response_scenarios'].pop();d['templates']=d['templates'][:2]
    elif bad=='background_independent':bp,_=response(tmp_path/'another-background');d['background_scenarios'][1]['response']=bp
    elif bad=='background_noanchor':d['background_scenarios'][1]['anchor']=None
    elif bad=='template_bad':p=Path(d['templates'][0]['template']['path']);doc=json.loads(p.read_text());doc['channels'][0]['samples'][0]['data'][0]=99;d['templates'][0]['template']=emit(p,doc)
    elif bad=='parent_missing':d['goal_binding']=None
    elif bad=='source_drift':Path(d['analysis']['sources'][0]['path']).write_text('{"changed":true}')
    with pytest.raises((ValueError,KeyError,IndexError)):op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/svj-recipe.json').exists()


@pytest.mark.parametrize('bad',['rinv','mass','threshold','invisible','qcut','runtime','parameter','br'])
def test_operational_shower_grid_constraints(tmp_path,bad):
    d=fixture(tmp_path,generation=True);p=d['points'][0];cp=Path(p['generation']['path']);c=json.loads(cp.read_text());sp=Path(p['shower_contract']['path']);s=json.loads(sp.read_text())
    if bad=='rinv':d['axes'][-1]['values']=[.8];p['coordinate']['r_inv']=.8
    elif bad=='mass':d['axes'][1]['values']=[11.];p['coordinate']['dark_pion_GeV']=11.
    elif bad=='threshold':d['axes'][1]['values']=[8.];p['coordinate']['dark_pion_GeV']=8.;s['particle_masses']['4900111']=8.;card=Path(c['cards']['pythia']['path']);card.write_text(card.read_text().replace('4900111:m0 = 10.0','4900111:m0 = 8.0'));c['cards']['pythia']={k:pin(card)[k] for k in ('path','sha256')}
    elif bad=='invisible':s['invisible_pdgs']=[4900111]
    elif bad=='qcut':c['shower']['merging_scale_gev']=30
    elif bad=='runtime':c['runtime']['options']['mg5amc_py8_interface_path']=None
    elif bad=='parameter':s['parameter_bindings'][0]['codes']=[999]
    elif bad=='br':s['decays'][-1][1]='1 0.4 100 4900213 -4900213'
    p['generation']=emit(cp,c);p['shower_contract']=emit(sp,s)
    with pytest.raises((ValueError,KeyError)):op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/svj-recipe.json').exists()


@pytest.mark.parametrize('kind',['sum_weights','overlap','unqualified'])
def test_correlated_and_shared_denominator_response_remains_whole_but_not_independent_bins(tmp_path,kind):
    d=fixture(tmp_path);p=Path(d['points'][0]['response']['path']);doc=json.loads(p.read_text())
    if kind=='sum_weights':doc['normalization']['denominator']='sum_original_weights';doc['normalization']['fixed_denominator']=None
    elif kind=='overlap':
        sel=Path(doc['selection']['path']);s=json.loads(sel.read_text());s['regions'][1]['cuts']=deepcopy(s['regions'][0]['cuts']);doc['selection']=ref(sel,s)
    else:
        for c in d['templates']:c['mc_interpretation']='unqualified'
    d['points'][0]['response']=emit(p,doc)
    if kind=='overlap':
        # Overlapping response requires complete different signal values; missing
        # templates remain honest while the complete joint result is delivered.
        for c in d['templates']:c['template']=None
    r=op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert r['blocked_cells']==4 and not list((tmp_path/'out').rglob('expected-science.json'))
    a=json.loads((tmp_path/'out/response-p0/complete-response.json').read_text());assert len(a['joint_weight_anchor_covariance'])==20
    if kind=='overlap':assert a['weights']['nominal']['conditional_group_covariance'][0][1]==16


def test_original_parent_mismatch_and_v1_refuse_before_run(tmp_path):
    d=fixture(tmp_path);t=task(tmp_path,d);s=spec(t,d);s['goal_binding']=parent(tmp_path/'different')
    p=emit(tmp_path/'wrong-parent.json',s)
    with pytest.raises(ValueError,match='outer ordinary original goal'):science.plan(tmp_path/'bad-run',p['path'])
    assert not (tmp_path/'bad-run').exists()
    s=spec(t,d);s['schema_version']=1;s.pop('goal_binding');s.pop('review_policy');s.pop('max_attempts');p=emit(tmp_path/'v1.json',s)
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'bad-v1',p['path'])
    assert not (tmp_path/'bad-v1').exists()


def test_declared_unknown_control_population_cannot_become_expected_limit_inputs(tmp_path):
    d=fixture(tmp_path);d['analysis']['unresolved_bins']=[{'id':'lepton-control-basis','role':'CR','reason':'No source-qualified ordering/observations/auxiliaries recovered'}]
    result=op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert result['blocked_cells']==4 and all('Unresolved full fitted' in c['obligations'][0] for c in result['cells'])
    assert not list((tmp_path/'out').rglob('expected-science.json'))


def test_signed_correlated_subevents_and_zero_records_remain_full(tmp_path):
    d=fixture(tmp_path);p=Path(d['points'][0]['response']['path']);doc=json.loads(p.read_text())
    for anchor in doc['anchors']:
        f=Path(anchor['events']['path']);rows=json.loads(f.read_text());rows[1]['group_id']='g0';rows[1]['weights']={'nominal':-1.,'twice':-2.};anchor['events']=ref(f,rows)
    d['points'][0]['response']=emit(p,doc)
    for c in d['templates']:c['template']=None
    result=op.run(task(tmp_path,d),tmp_path,tmp_path/'out');bundle=json.loads((tmp_path/'out/response-p0/complete-response.json').read_text())
    assert result['blocked_cells']==4 and bundle['events']==5 and len(bundle['group_ids'])==4
    assert bundle['weights']['nominal']['conditional_group_covariance'][0][1]==-4
    assert bundle['anchor_records'][0][1]['weights']=={'nominal':-1.,'twice':-2.}


def test_existing_marked_provider_receives_complete_unobserved_support(tmp_path):
    from ravel.physics import marked_response as mr, marked_response_provider as mp, mc_auxiliary as mc
    d=fixture(tmp_path);p=Path(d['points'][0]['response']['path']);doc=json.loads(p.read_text());cats=[]
    weights=[4.,1.,2.,1.,0.]
    for i,w in enumerate(weights):
        a0=[0.]*5;a0[i]=1.;a1=deepcopy(a0)
        if i==0:a1=[0.,0.,0.,0.,1.]
        if i==4:a1=[1.,0.,0.,0.,0.]
        cats.append({'id':'cat'+str(i),'group_ids':['g'+str(i)],'weight':w,'denominator_mark':1.,'initial':1/6,'allocation_at_anchors':[a0,a1]})
    cats.append({'id':'unseen','group_ids':[],'weight':3.,'denominator_mark':1.,'initial':1/6,'allocation_at_anchors':[[1.,0.,0.,0.,0.],[1.,0.,0.,0.,0.]]})
    support={'schema_version':1,'sampling_law':'iid_fixed_mark_categories','support_complete':True,'independence':'iid_groups_within_one_fixed_N_stream','source':'Explicit synthetic full joint support, not inferred from observed categories','calibration':'Unqualified hypothetical response','categories':cats,'fitted_destinations':['s0','s1','c0','c1']}
    doc['category_support']=ref(tmp_path/'support.json',support);d['points'][0]['response']=emit(p,doc)
    # The fixed-N category-law and Poissonized projection are distinct; use the
    # marked consumer and leave the independent-bin templates unqualified.
    for c in d['templates']:c['mc_interpretation']='unqualified'
    result=op.run(task(tmp_path,d),tmp_path,tmp_path/'out');out=tmp_path/'out/response-p0'
    law=mr.prepare(json.loads((out/'marked-response.json').read_text()));model=mc.MCAuxiliaryBlock({'input':str(out/'mc-model.json')}).document();ledger=json.loads((out/'joint-mark-ledger.json').read_text())
    assert mp.verify_group_marks(law,model,ledger)['observed_group_count']==5
    assert model['classes'][-1]['observed']==0 and model['classes'][-1]['initial']>0
    assert len(mr.evaluate(law,{c['id']:c['initial'] for c in model['classes']},{'joint_tagger':.5})['values'])==5
    assert result['blocked_cells']==4 and not result['points'][0]['response']['marked_MC']['scientific_sampling_and_calibration_qualified']


@pytest.mark.parametrize('target',['source','generated'])
def test_ending_source_or_generated_swap_retains_failure_without_receipt(tmp_path,monkeypatch,target):
    d=fixture(tmp_path);original=op.atomic_json;changed=[]
    def swap(path,doc):
        value=original(path,doc)
        if path.name=='expected-science.json' and not changed:
            f=Path(d['analysis']['sources'][0]['path']) if target=='source' else tmp_path/'out/response-p0/complete-response.json'
            f.write_text('{"changed":true}');changed.append(str(f))
        return value
    monkeypatch.setattr(op,'atomic_json',swap)
    with pytest.raises(ValueError):op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert changed and not (tmp_path/'out/svj-recipe.json').exists()


@pytest.mark.parametrize('target',['source','generated'])
def test_ending_commitment_swap_moves_false_success_receipt_to_failed_evidence(tmp_path,monkeypatch,target):
    d=fixture(tmp_path);original=op.atomic_json
    def swap(path,doc):
        value=original(path,doc)
        if path.name=='svj-recipe.json':
            f=Path(d['analysis']['sources'][0]['path']) if target=='source' else tmp_path/'out/response-p0/complete-response.json'
            f.write_text('{"changed":true}')
        return value
    monkeypatch.setattr(op,'atomic_json',swap)
    with pytest.raises(ValueError):op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/svj-recipe.json').exists() and (tmp_path/'out/failed-svj-recipe.json').is_file()


def test_child_template_rebinds_relative_evidence_and_common_report_refuses_changed_member(tmp_path):
    d=fixture(tmp_path);p=Path(d['templates'][0]['template']['path']);doc=json.loads(p.read_text())
    for c in doc['channels']:
        for s in c['samples']:s['provenance']['evidence'][0]['path']='prediction.json'
    d['templates'][0]['template']=emit(p,doc)
    result=op.run(task(tmp_path,d),tmp_path,tmp_path/'out');cell=result['cells'][0]
    from ravel.physics import signal_templates as st
    paths=st.inputs({'input':cell['template_construction']['bridge']['path']},tmp_path)
    assert p.parent/'prediction.json' in paths
    Path(result['points'][0]['response']['complete']['path']).write_text('{"changed":true}')
    with pytest.raises(ValueError):op.write_report(result,tmp_path/'out')
    assert not (tmp_path/'out/svj-recipe-report').exists()


def test_existing_typed_analysis_child_is_self_contained_and_ordinary_plannable(tmp_path):
    d=fixture(tmp_path);response_doc=json.loads(Path(d['points'][0]['response']['path']).read_text())
    program={'schema_version':1,'name':'synthetic-svj-source-control','nodes':[{'id':'met','op':'met'},{'id':'pt','op':'field','args':['met'],'field':'pt'},{'id':'threshold','op':'const','value':10,'unit':'GeV'},{'id':'cut','op':'compare','args':['pt','threshold'],'comparison':'ge'}],'regions':[{'name':'SR','cuts':['cut']}]}
    pp=emit(tmp_path/'program.json',program)
    task_doc={'backend':'analysis-ir','program':pp['path'],'contract':response_doc['object_contract']['path'],'events':response_doc['anchors'][0]['events']['path']}
    d['points'][0]['analysis']=emit(tmp_path/'analysis.json',task_doc)
    result=op.run(task(tmp_path,d),tmp_path,tmp_path/'out');child=result['points'][0]['analysis']
    assert not child['actual_analysis_completed'] and not child['execution_authorized']
    science.plan(tmp_path/'analysis-unapproved',child['specification']['path'])
    assert science.verify_plan(tmp_path/'analysis-unapproved',approved=False)['schema_version']==2
    assert not (tmp_path/'analysis-unapproved/inputs/science-approval.json').exists()


def test_completion_receipt_counts_toward_successful_delivery_cap(tmp_path,monkeypatch):
    d=fixture(tmp_path,missing=True)
    monkeypatch.setattr(op,'MAX_DELIVERY_BYTES',1)
    with pytest.raises(ValueError,match='completion receipt'):
        op.run(task(tmp_path,d),tmp_path,tmp_path/'out')
    assert not (tmp_path/'out/svj-recipe.json').exists()
    assert (tmp_path/'out/failed-svj-recipe.json').is_file()


@pytest.mark.parametrize('mutation',['disabled','reset'])
def test_decay_table_effective_order_and_enabled_meson_required(tmp_path,mutation):
    d=fixture(tmp_path,generation=True)
    point=d['points'][0];cfg=json.loads(Path(point['generation']['path']).read_text())
    card=Path(cfg['cards']['pythia']['path']);raw=card.read_text()
    contract=json.loads(Path(point['shower_contract']['path']).read_text())
    if mutation=='disabled':
        raw=raw.replace('4900111:mayDecay = on','4900111:mayDecay = off')
        contract['decays']=[(k,'off' if k=='4900111:mayDecay' else v) for k,v in contract['decays']]
        message='explicitly decay'
    else:
        raw=raw.replace('4900111:oneChannel = 1 0.5 100 1 -1','4900111:addChannel = 1 0.5 100 1 -1').replace('4900111:addChannel = 1 0.5 100 4900211 -4900211','4900111:oneChannel = 1 0.5 100 4900211 -4900211')
        contract['decays']=[('4900111:addChannel' if k=='4900111:oneChannel' else '4900111:oneChannel' if k=='4900111:addChannel' else k,v) for k,v in contract['decays']]
        message='initialize'
    card.write_text(raw);cfg['cards']['pythia']={k:pin(card)[k] for k in ('path','sha256')}
    point['generation']=emit(Path(point['generation']['path']),cfg)
    point['shower_contract']=emit(Path(point['shower_contract']['path']),contract)
    with pytest.raises(ValueError,match=message):op.inputs(task(tmp_path,d),tmp_path)
