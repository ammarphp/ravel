"""Proposed software controls: no native fitter, model, training or physics job."""

from method_decision_fixture import admit_method
from bound_review import bound_review
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import sfitter_profiles as p, sfitter_inputs as inputs, sfitter_compat as compat
from ravel.physics import sfitter_complete_native as native, sfitter_results as results
from sfitter_complete_fixture import source,card,pin,Array

@pytest.mark.parametrize('profile',['top','higgs'])
@pytest.mark.parametrize('algorithm',['flow','smc','craft'])
def test_complete_sector_card_and_permuted_subset(tmp_path,profile,algorithm):
    root=source(tmp_path);basis=p.basis(root,profile);selection=[basis[-1],basis[0]]
    cp,rp,params,document=card(tmp_path,root,profile,selection,algorithm)
    bound=p.compile_card(root,cp,rp,profile,selection,algorithm)
    assert len(bound['selection']['full'])==(22 if profile=='top' else 20)
    assert bound['selection']['indices']==[len(basis)-1,0]
    assert bound['selection']['fixed_zero']==basis[1:-1]
    assert bound['params']==params and bound['census']['bins']==1
    assert bound['inference']==p.INFERENCE and bound['physics_validated'] is False

@pytest.mark.parametrize('profile',['top','higgs'])
@pytest.mark.parametrize('mutation',['unknown','duplicate','wrong_pair','short','reversed_monomial'])
def test_complete_card_refusals(tmp_path,profile,mutation):
    root=source(tmp_path);basis=p.basis(root,profile)
    _,_,_,document=card(tmp_path,root,profile,basis)
    if mutation=='unknown':document['predictions'][0]['modifiers'][0]['name']='unbound'
    if mutation=='duplicate':
        document['observations']*=2;document['predictions']*=2
    if mutation=='wrong_pair':document['predictions'][0]['ID']='different'
    if mutation=='short':document['observations'][0]['Meas']['data']=[]
    if mutation=='reversed_monomial':document['predictions'][0]['modifiers'] += [{'name':basis[0]+'x'+basis[1],'data':[1.]},{'name':basis[1]+'x'+basis[0],'data':[1.]}]
    with pytest.raises(ValueError):inputs.inspect_profile_datacard(document,root,profile)

@pytest.mark.parametrize('filename',['Top_Full.json','Higgs_Full.json','Higgs_Full_with_CtG.json'])
def test_original_defective_population_is_not_silently_deduplicated(tmp_path,filename):
    root=source(tmp_path);raw=(root/'sfitter/data'/filename).read_bytes();document=json.loads(raw)
    with pytest.raises(ValueError):inputs.inspect_profile_datacard(document,root,'top' if filename.startswith('Top') else 'higgs')
    assert (root/'sfitter/data'/filename).read_bytes()==raw

@pytest.mark.parametrize('profile',['spiral','five_point','toy'])
def test_diagnostic_profiles_are_full_and_not_measurement_admission(tmp_path,profile):
    root=source(tmp_path)
    assert p.selection(root,profile,p.basis(root,profile))['fixed_zero']==[]
    with pytest.raises(ValueError):p.selection(root,profile,p.basis(root,profile)[:1])


def test_smc_constructor_compatibility_is_exact_and_unavailable(tmp_path):
    root=source(tmp_path);original=(root/compat.RELATIVE).read_bytes()
    revised=compat.projected_source(original,hashlib.sha256(original).hexdigest())
    assert revised.replace(compat.AFTER.encode(),compat.BEFORE.encode()).replace(compat.PAIR_AFTER.encode(),compat.PAIR_BEFORE.encode())==original
    for name in results.WEIGHTS:assert (name+'=None').encode() in revised
    with pytest.raises(ValueError):compat.projected_source(original+b'\n',hashlib.sha256(original).hexdigest())
    assert (root/compat.RELATIVE).read_bytes()==original


def test_parsed_transport_is_bound_to_original_buffer(tmp_path,monkeypatch):
    path=tmp_path/'delivery.json';raw=b'{"original": true}';path.write_bytes(raw)
    expected=hashlib.sha256(raw).hexdigest()
    # Separate read_bytes is irrelevant: the parser consumes the checked fd.
    monkeypatch.setattr(Path,'read_bytes',lambda self:b'{"original": false}')
    assert native._read(path,expected)=={'original':True}
    with pytest.raises(ValueError):native._read(path,'0'*64)


def test_intended_commitment_refuses_publication_substitution(tmp_path,monkeypatch):
    from ravel.workflow.state_io import atomic_json
    path=tmp_path/'delivery.json'
    def substituted(path,value):atomic_json(path,{'foreign':True})
    monkeypatch.setattr(native,'atomic_json',substituted)
    with pytest.raises(ValueError):native._write_committed(path,{'original':True},{})


def test_durable_return_is_detached_and_exact(tmp_path):
    path=tmp_path/'delivery.json';committed={};value={'rows':[1,2]}
    receipt=native._write_committed(path,value,committed);value['rows'].clear()
    assert native._read(path,receipt['sha256'])=={'rows':[1,2]}
    path.write_text('{"rows":[]}')
    with pytest.raises(ValueError):native._read(path,receipt['sha256'])


def test_saved_phase_requires_actual_ordinary_authority(tmp_path,monkeypatch):
    from ravel.workflow import science
    rd=tmp_path/'run';rd.mkdir()
    monkeypatch.setattr(science,'review_waypoint_paths',lambda rd:[])
    monkeypatch.setattr(science,'execution_spec',lambda rd:{'mode':'sfitter-native-fit'})
    monkeypatch.setattr(science,'packet',lambda rd:{'lifecycle_verdict':'FAIL'})
    with pytest.raises(ValueError,match='successful original ordinary'):native._ordinary_paths(rd)

@pytest.mark.parametrize('algorithm',['smc','craft'])
def test_native_histograms_keep_unweighted_diagnostic_semantics(algorithm):
    names=['a','b'];maps={}
    for name in results.ARRAY_MAPS:
        pair=name in ('marginal_2d','profile_2d')
        shape=[2,2] if pair else [3] if name.endswith('_bins') else [2]
        maps[name]={('a','b'):Array(shape)} if pair else {key:Array(shape) for key in names}
    fake=SimpleNamespace(parameters=names,**maps,**{key:None for key in results.WEIGHTS},marginal_effective_size=1.)
    delivered=results.complete_fit_result(fake,names,algorithm,'higgs')
    assert 'log_weights_discarded_not_posterior' in delivered['marginal_semantics']
    assert all(value is None for value in delivered['weights'].values())
    assert delivered['prior_semantics']=='native_physical_log_prior_zero_no_proper_prior_support_claim'
    assert delivered['physics_validated'] is False
    fake.w_hist_lin=Array([2])
    with pytest.raises(ValueError):results.complete_fit_result(fake,names,algorithm,'higgs')

@pytest.mark.parametrize('profile',['top','higgs'])
def test_actual_initializer_embeds_full_canonical_vector_for_both_score_and_prior(monkeypatch,profile):
    import sys
    from types import ModuleType
    from ravel.physics import sfitter_complete_worker as child
    full=['c'+str(i) for i in range(22 if profile=='top' else 20)]
    select={'full':full,'selected':[full[-1],full[0]],'indices':[len(full)-1,0],'fixed_zero':full[1:-1]}
    seen=[]
    class Dense:
        device='software';dtype='software'
        def __init__(self,rows):self.rows=rows;self.shape=(len(rows),len(rows[0]))
        def index_copy(self,dimension,indices,value):
            assert dimension==-1
            for row,chosen in zip(self.rows,value.rows):
                for index,v in zip(indices,chosen):row[index]=v
            return self
    torch=ModuleType('torch');torch.zeros=lambda shape,**kw:Dense([[0.]*shape[-1] for _ in range(shape[0])]);torch.tensor=lambda values,**kw:list(values)
    monkeypatch.setitem(sys.modules,'torch',torch)
    class Full:
        dims_nuisance=0;parameter_names=full
        def __init__(self,params,device):assert 'parameter_names' not in params
        def log_likelihood(self,x):seen.append(('score',copy.deepcopy(x.rows)));return 'source_score'
        def log_prior(self,x):seen.append(('prior',copy.deepcopy(x.rows)));return 'source_prior'
    class Fitter:
        def __init__(self,params,train,device,path,likelihood):self.likelihood=likelihood
    for name,clsname,cls in [('sfitter.likelihood.full_likelihood','ProfileLikelihood',Full),('sfitter.likelihood.toy','ToyLikelihood',Full),('sfitter.fit.flow_fitter','FlowFitter',Fitter),('sfitter.fit.smc_fitter','SMCFitter',Fitter),('sfitter.fit.craft','CraftFitter',Fitter)]:
        module=ModuleType(name);setattr(module,clsname,cls);monkeypatch.setitem(sys.modules,name,module)
    module=ModuleType('sfitter.likelihood.toys2d');module.SpiralLikelihood=module.FivePointLikelihood=Full;monkeypatch.setitem(sys.modules,module.__name__,module)
    fitter,likelihood,native_full=child.initialize({'parameter_names':select['selected']},{'selection':select,'profile':profile,'algorithm':'flow'},'software',SimpleNamespace(get_file=lambda name:name))
    value=Dense([[2.,-3.],[0.,7.]])
    assert likelihood.log_likelihood(value)=='source_score'
    assert likelihood.log_prior(value)=='source_prior'
    expected=[[-3.]+[0.]*(len(full)-2)+[2.],[7.]+[0.]*(len(full)-1)]
    assert seen==[('score',expected),('prior',expected)]
    assert fitter.likelihood is likelihood and likelihood.dims_total==2


def test_saved_capsule_refuses_changed_adapter_before_any_opaque_load(tmp_path):
    path=tmp_path/'capsule.json'
    value={name:None for name in ('schema_version','kind','rundir','run_name','profile','algorithm','selection','source_manifest','runtime','datacard','original_run_card','files','adapter_sources','scientific_inputs','physics_validated')}
    value['adapter_sources']={};value['scientific_inputs']={k:None for k in ('datacard','run_card','semantic_manifest','production_handoff','card_derivation')};path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='adapter/compatibility'):native.saved_state(pin(path),tmp_path,{}, {})


@pytest.mark.parametrize('name',['Top_Full.json'])
def test_explicit_derived_complete_card_lineage_preserves_original_population(tmp_path,name):
    from ravel.physics import sfitter_card_derivation as derivation
    root=source(tmp_path);original=(root/'sfitter/data'/name).read_bytes()
    import sfitter_card_repair_fixture as repairs
    with pytest.raises(derivation.records.SourceRecordError) as missing:derivation.derive(root,repairs.CARDS+'/'+name)
    assert missing.value.reason=='missing_repair_manifest'
    binding,manifest=repairs.top_manifest(tmp_path,root)
    derived,lineage=derivation.derive(root,repairs.CARDS+'/'+name,binding)
    assert lineage['repair_manifest']==binding and len(lineage['changes'])==len(manifest['transforms'])
    profile='top' if name.startswith('Top') else 'higgs'
    review,placement=repairs.derived_review(tmp_path,root,derived)
    with pytest.raises(derivation.records.SourceRecordError):inputs.inspect_profile_datacard(derived,root,profile)
    census=inputs.inspect_profile_datacard(derived,root,profile,source_review=review)
    assert census['source_card_quirks']==[placement]
    expected=52 if profile=='top' else 287 if name=='Higgs_Full.json' else 288
    assert census['observations']==expected
    assert sorted(i for row in lineage['rows'] for i in row['original_indices'])==list(range(lineage['original_observations']))
    assert len({row['native_ID'] for row in lineage['rows']})==expected
    assert (root/'sfitter/data'/name).read_bytes()==original
    assert lineage['physics_validated'] is False
    if profile=='top':
        assert census['bins']==110 and derived['observations'][1]['Meas']['data']==[.32]
        assert derived['predictions'][1]['data']==[.311]
        for index in (3,18):assert any(m['name']=='D6qq18xD6qt8' and m['data']==[.010242565258] for m in derived['predictions'][index]['modifiers'])
    else:assert lineage['rows'][0]['original_indices']==[0,276]


def test_derived_card_materialization_is_explicit_and_cannot_overwrite_source(tmp_path):
    from ravel.physics import sfitter_card_derivation as derivation
    import sfitter_card_repair_fixture as repairs
    root=source(tmp_path);original=(root/repairs.TOP).read_bytes()
    with pytest.raises(derivation.records.SourceRecordError) as missing:derivation.materialize(root,repairs.TOP,tmp_path/'unbound')
    assert missing.value.reason=='missing_repair_manifest' and not (tmp_path/'unbound').exists()
    binding,_=repairs.top_manifest(tmp_path,root)
    result=derivation.materialize(root,repairs.TOP,tmp_path/'fresh',binding)
    assert result['repair_manifest']==binding and Path(result['derived_card']['path'])==tmp_path/'fresh/derived-card.json'
    assert native._read(result['derived_card']['path'],result['derived_card']['sha256'])['observations'][1]['Meas']['data']==[.32]
    assert json.loads((tmp_path/'fresh/derivation.json').read_bytes())==result
    with pytest.raises(ValueError):derivation.materialize(root,repairs.TOP,root/'changed',binding)
    with pytest.raises(ValueError):derivation.materialize(root,repairs.TOP,tmp_path/'fresh',binding)
    assert not (root/'changed').exists() and (root/repairs.TOP).read_bytes()==original

@pytest.mark.parametrize('profile',['top','higgs'])
def test_actual_ordinary_schema2_unapproved_plan_captures_complete_original_source(tmp_path,profile):
    from sfitter_complete_fixture import configuration
    from ravel import cli
    from ravel.physics import sfitter_native as legacy
    from ravel.workflow import science
    from ravel.workflow.state_io import atomic_json,read_json
    root=source(tmp_path);task,config=configuration(tmp_path,root,profile)
    spec={'schema_version':2,'mode':'sfitter-native-fit','source':'Synthetic complete native planning control','assumptions':['No numerical job, approval or scientific evidence'], 'max_seconds':30,'approval_mode':'scripted_yes','task':task,'max_attempts':1,
      'review_policy':{'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'producer','executor':'executor','physics_critic':'critic','skeptical_verifier':'skeptic','physics_decider':'decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'scientific','kind':'scientific'}],'claim_scopes':{legacy.SCOPE:{'checks':['integrity'],'actions':['delivery']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}}
    path=tmp_path/'study.json';atomic_json(path,spec);rd=tmp_path/'planned'
    assert cli.main(['plan','--rundir',str(rd),'--spec',str(path)])==0
    assert (rd/science.PLAN).is_file() and not (rd/'inputs/science-approval.json').exists()
    consumed=legacy.inputs(task,tmp_path)
    assert len([p for p in consumed if p.is_relative_to(root)])==235
    assert config['parameters']==[p.basis(root,profile)[-1],p.basis(root,profile)[0]]


@pytest.mark.parametrize('profile',['top','higgs'])
def test_actual_complete_scientific_assembly_reaches_existing_ordinary_adapter(tmp_path,profile):
    from sfitter_complete_fixture import workflow_request
    from ravel.workflow import sfitter_workflow as w, science
    from ravel.workflow.state_io import atomic_json,read_json
    root=source(tmp_path);request,config=workflow_request(tmp_path,root,profile)
    settings={key:config[key] for key in ('source','trusted_upstream_python','runtime','max_seconds','max_ram_mib','max_export_bytes')}
    settings['schema_version']=1;settings_path=tmp_path/'settings.json';atomic_json(settings_path,settings)
    request_path=tmp_path/'workflow.json';atomic_json(request_path,request)
    out=tmp_path/'assembled'
    receipt=w.materialize_datacard(request,tmp_path,out,native_settings=pin(settings_path),request_pin=pin(request_path))
    delivered=read_json(receipt['native_config']['path'])
    assert delivered['schema_version']==2 and delivered['profile']==profile
    assert delivered['parameters']==config['parameters'] and delivered['production_handoff'] is None
    assert receipt['execution_authorized'] is False and receipt['native_calls_observed']==0
    assert science.adapter({'mode':'sfitter-native-fit','task':receipt['native_task']}).__name__=='ravel.physics.sfitter_native'
    assert len([path for path in native.inputs(receipt['native_task'],out) if path.is_relative_to(root)])==235
    assert json.loads(Path(delivered['datacard']['path']).read_text())==w.assemble_datacard(request,tmp_path)['datacard']


def test_documented_mixed_coefficient_keeps_original_normalization(tmp_path):
    from ravel.physics import sfitter_card_derivation as derivation
    import sfitter_card_repair_fixture as repairs
    root=source(tmp_path);binding,manifest=repairs.top_manifest(tmp_path,root)
    raw=json.loads((root/repairs.TOP).read_bytes())
    card,lineage=derivation.derive(root,repairs.TOP,binding)
    for index in (3,18):
        term=next(m for m in card['predictions'][index]['modifiers'] if m['name']=='D6qq18xD6qt8')
        assert term['data'][0]*2.*3.==pytest.approx(.061455391548,rel=0,abs=1e-15)
        assert term['data'][0]*2.*0.==0.
        change=next(c for c in lineage['changes'] if c['path'].startswith(f'/predictions/{index}/modifiers/') and c['operation']=='replace')
        assert (change['before'],change['after'])==(repairs.MIXED_OLD,repairs.MIXED_NEW)
        assert change['evidence']['line_start']==repairs.NOTE_LINE and change['evidence']==manifest['transforms'][4]['evidence']
        position=int(change['path'].split('/')[4])
        # Only the token changes: the coefficient keeps the supplied source bytes.
        assert raw['predictions'][index]['modifiers'][position]=={'name':repairs.MIXED_OLD,'data':term['data']}
        assert card['predictions'][index]['modifiers'][position] is term
    # No transformation writes a coefficient: every renamed or projected term keeps its original data.
    for index,(before,after) in enumerate(zip(raw['predictions'],card['predictions'])):
        assert before['data']==after['data']
        renamed={repairs.MIXED_OLD:repairs.MIXED_NEW} if index in (3,18) else {}
        kept={renamed.get(m['name'],m['name']):m['data'] for m in before['modifiers']}
        assert {m['name']:m['data'] for m in after['modifiers']}==kept


def test_actual_ordinary_quantity_producer_to_fit_bundle_and_stale_receipt_refusal(tmp_path):
    """Root-only synthetic worker control: actual ordinary APIs, no fit/model/job."""
    from sfitter_complete_fixture import workflow_request
    from site_ordinary_fixture import contract,event,policy
    from ravel.workflow import science,physics_review,sfitter_workflow as w,sfitter_native_handoff as join
    from ravel.workflow.state_io import atomic_json,read_json
    root=source(tmp_path);study=tmp_path/'producer-source';study.mkdir()
    atomic_json(study/'contract.json',contract())
    (study/'records.jsonl').write_text('\n'.join(json.dumps(v) for v in [event('a',[[.5]],2),event('b',[[2]],-1)])+'\n')
    review=policy();review.update(max_redos=0,allowed_stages=['science'],allowed_changed_paths=[])
    spec={'schema_version':2,'mode':'quantities','source':'Explicit synthetic producer-to-fit software control',
        'assumptions':['No physical prediction, native engine, model, provider or scientific validation'],
        'max_seconds':20,'max_attempts':1,'approval_mode':'scripted_yes','task':{'contract':'contract.json','records':'records.jsonl'},
        'review_policy':{'schema_version':1,'policy':review,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    atomic_json(study/'study.json',spec);rd=tmp_path/'producer'
    science.plan(rd,study/'study.json'); admit_method(rd);science.approve(rd,'Root-admitted synthetic software fixture only',scripted=True)
    assert science.run(rd)==0
    plan=science.verify_plan(rd,approved=True);output=rd/plan['stages'][0]['outputs'][0]
    produced=output/'result.json';assert read_json(produced)['quantities']['values']['nominal']==[2,-1]
    # The real producer succeeded; no invented passed native records. Explicit
    # software role judgments use the existing API and claim synthetic scope.
    record=science.execution.load_execution(rd)['stages']['science']
    atomic_json(rd/'inputs/software-checks.json',{'schema_version':1,'checks':[
        {'id':name,'status':'pass','evidence':[{'path':str(produced),'location':'$.quantities.values.nominal'}],
         'attempt_ids':[record['attempt_id']]} for name in ('integrity','agreement')]})
    physics_review.open_cycle(rd,effective_settings=['inputs/science.json'],stage_receipts=[record['attempt_record']],check_results='inputs/software-checks.json')
    # Recorded votes are bound responses of dispatched roles; a declared reviewer name is advice only.
    for role in ['physics_critic','skeptical_verifier','physics_decider']:
        bound_review(rd,role=role,verdict='accept',summary='Synthetic exact arithmetic/custody only; no physical theory qualification',claim_scope='reproduction')
    assert physics_review.gate_errors(rd,'reuse')==[]
    bundle_source=tmp_path/'bundle-source';bundle_source.mkdir();request,config=workflow_request(bundle_source,root,'top')
    evidence=pin(produced);request['sources']=[evidence]
    semantic_path=Path(config['semantic_manifest']['path']);sem=read_json(semantic_path);sem['sources']=[evidence];sem['eft']['evidence']=[evidence];atomic_json(semantic_path,sem)
    for phase,reference in request['handoffs'].items():
        path=Path(reference['path']);doc=read_json(path);doc['sources']=[evidence]
        if phase=='sm_template':
            for row in doc['payload']['rows']:row['evidence']=evidence
        if phase=='parameterization':
            for row in doc['payload']['rows']:
                for key in ('scan_evidence','coupling_sanity_evidence','fit_diagnostics'):row[key]=evidence
        if phase=='conventions':doc['payload']['semantic_manifest']=pin(semantic_path)
        atomic_json(path,doc);request['handoffs'][phase]=pin(path)
    settings={key:config[key] for key in ('source','trusted_upstream_python','runtime','max_seconds','max_ram_mib','max_export_bytes')};settings['schema_version']=1
    settings_path=bundle_source/'settings.json';atomic_json(settings_path,settings)
    roster_path=bundle_source/'producers.json';atomic_json(roster_path,{'schema_version':1,'producers':[{'rundir':str(rd),'artifacts':[evidence]}]})
    request_path=bundle_source/'workflow.json';atomic_json(request_path,request)
    receipt=w.materialize_datacard(request,bundle_source,tmp_path/'composed',native_settings=pin(settings_path),request_pin=pin(request_path),production_roster=pin(roster_path))
    config=read_json(receipt['native_config']['path']);bound=p.compile_card(root,config['datacard']['path'],config['run_card']['path'],'top',config['parameters'],'flow')
    connected=join.verify(config['production_handoff'],tmp_path,config,bound)
    assert connected['produced_inputs']==[evidence] and connected['physics_validated'] is False
    assert produced in connected['paths'] and receipt['execution_authorized'] is False
    attempt=rd/record['attempt_record'];raw=attempt.read_bytes();attempt.unlink()
    with pytest.raises((ValueError,OSError,KeyError)):join.verify(config['production_handoff'],tmp_path,config,bound)
    attempt.write_bytes(raw)


def test_complete_runtime_64k_boundary_is_metadata_only_no_truncated_admission(tmp_path):
    from sfitter_complete_fixture import configuration
    from ravel.physics import sfitter_native as legacy
    root=source(tmp_path);task,config=configuration(tmp_path,root)
    config['runtime']['assets']=[{'path':str(tmp_path/'missing-site'/('module'+str(i))), 'sha256':'0'*64} for i in range(64000)]
    config['runtime']['site_roots']=[str(tmp_path/'missing-site')]
    assert native.validate_config(config)['runtime']['assets']==config['runtime']['assets']
    config_path=Path(task['config']);config_path.write_text(json.dumps(config))
    with pytest.raises((ValueError,OSError)):native.inputs(task,tmp_path)
    config['runtime']['assets'].append({'path':str(tmp_path/'missing-site'/'extra'),'sha256':'0'*64})
    with pytest.raises(ValueError,match='runtime'):native.validate_config(config)
    old={k:config[k] for k in ('operation','purpose','source','upstream_tree','trusted_upstream_python','runtime','datacard','run_card','semantic_manifest','vectors','max_seconds','max_ram_mib','max_export_bytes')};old['schema_version']=1
    old['runtime']['assets']=old['runtime']['assets'][:20001]
    with pytest.raises(ValueError,match='runtime'):legacy.validate_config(old)


def test_complete_runtime_population_refuses_omitted_added_and_aliased_members(tmp_path):
    root=tmp_path/'site';root.mkdir();a=root/'a.py';a.write_text('a=1\n')
    b=root/'b.py';b.write_text('b=2\n')
    config={'runtime':{'site_roots':[str(root)],'assets':[pin(a)]}}
    with pytest.raises(ValueError,match='population'):native.runtime_members(config,tmp_path)
    config['runtime']['assets'].append(pin(b))
    assert native.runtime_members(config,tmp_path)[1]==[a,b]
    c=root/'c.py';c.write_text('c=3\n')
    with pytest.raises(ValueError,match='population'):native.runtime_members(config,tmp_path)
    c.unlink();c.symlink_to(a)
    with pytest.raises(ValueError,match='aliases'):native.runtime_members(config,tmp_path)
