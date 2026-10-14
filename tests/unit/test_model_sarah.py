"""Pure full-body stand-ins; no kernel, SDK, UFO import or scientific execution."""
import copy
import json
import os
from pathlib import Path
import subprocess
import pytest
from ravel.physics import model_sarah as s
from ravel.physics import model_provider_bridge as p
from ravel.physics import model_derivation_bridge as d
from ravel.physics import model_tool_bridge as c


@pytest.fixture(autouse=True)
def deny_processes(monkeypatch):
    def deny(*a,**k): raise AssertionError('No native/provider/process execution permitted')
    monkeypatch.setattr(subprocess,'Popen',deny);monkeypatch.setattr(os,'system',deny)


def pin(path):return {'path':str(path),'sha256':c._hash(path)}


def tree(path,destination):
    c._write(destination,c.source_tree(path));return {'root':str(path),'manifest':pin(destination)}


@pytest.fixture
def config(tmp_path):
    provider=tmp_path/'source'; provider.mkdir()
    for name in ('SARAH.m','SARAH.config','Package/checkModel.m','Package/Outputs/madgraph.m','Models/parameters.m','Models/particles.m'):
        target=provider/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text('SA`Version="4.15.4";\n' if name=='SARAH.m' else '(* explicitly synthetic source stand-in *)\n')
    kernel=tmp_path/'kernel';kernel.write_text('not a kernel');kernel.chmod(0o700)
    meta=tmp_path/'app';meta.write_text('explicit unit runtime stand-in')
    model=tmp_path/'models';(model/'SM').mkdir(parents=True)
    for name in ('SM.m','parameters.m','particles.m'):(model/'SM'/name).write_text('(* source-only model stand-in *)\n')
    base={'schema_version':2,'operation':s.READINESS,'source':'Explicit pure synthetic test, no provider qualification',
        'kernel':pin(kernel),'application_metadata':pin(meta),'provider_tree':tree(provider,tmp_path/'provider.json'),
        'trusted_provider_source':True,'expected_kernel_version':15.0,'expected_provider_version':'4.15.4',
        'existing_installation_license_status':'unverified_no_activation_or_credentials_requested','max_seconds':60,'max_ram_mib':2048}
    derived={k:v for k,v in base.items() if k!='existing_installation_license_status'}
    derived.update(operation=s.DERIVATION,model_tree=tree(model,tmp_path/'model.json'),model_name='SM',eigenstate='EWSB',
        ufo_options={'exclude':[],'include_effective_higgs_vertices':False,'bsm_couplings':[],'must_include':[],'read_lists':False,'replacements':{},'python2':False},
        particle_conventions=[{'pdg':25,'spin':1,'color':1,'charge':0,'mass_parameter':'MH','width_parameter':'WH'}],
        point_policy='no_parameter_point_selected',parameter_card=None,trusted_model_source=True,
        provider_readiness_receipt={'path':'PENDING','sha256':'0'*64},provider_readiness_run={'path':'PENDING','attempt_id':'unit','attempt_record':{'path':'PENDING','sha256':'0'*64}})
    return base,derived


def readiness(cg,root,pid=72):
    return {'provider_kind':'sarah','process_id':pid,'provider_root':str(root),'kernel_version':15.0,'provider_version':'4.15.4',
        'provider_loaded':True,'load_messages':[],'kernel_arithmetic_control':4,'parallel_disabled':True,
        'parallel_kernels_list':True,'parallel_kernel_count':0,'entrypoint_definition_counts':{x:1 for x in s.ENTRYPOINTS},
        'definition_kinds':s.ENTRYPOINTS,'model_calculation_performed':False,'generated_events':0}


def native(cg,root,model,exported,pid=72):
    return {'provider_kind':'sarah','process_id':pid,'kernel_version':15.0,'provider_version':'4.15.4',
        'provider_root':str(root),'model_root':str(model),'export_root':str(exported),'model_name':'SM','requested_eigenstate':'EWSB',
        'state_names':['GaugeES','EWSB'],'provider_loaded':True,'start_completed':True,'load_messages':[],'start_messages':[],
        'input_directories':[str(model)],'output_directory':str(exported.parent/'sarah-output'),
        'check_model_invoked':True,'check_model_return_expression':'Null','check_model_messages':[],
        'model_output_choices':{'six_particle_interactions':False,'effective_operators':False,'read_lists':False,'loop_corrections':False,'rges':False,'vertices':True},
        'check_model_boolean_certificate':False,'export_completed':True,'native_ufo_root':str(exported.parent/'sarah-output/SM/EWSB/UFO'),
        'explicit_ufo_options_json':json.dumps(cg['ufo_options'],sort_keys=True),'effective_exclude':['ASS'],
        'parallel_disabled':True,'parallel_kernels_list':True,'parallel_kernel_count':0,
        'model_calculation_performed':True,'decay_calculation_requested':False,'generated_events':0}


def write_ufo(root):
    root.mkdir()
    for name in d.REQUIRED_UFO:(root/name).write_text('# Synthetic scalar/Dirac fixture; no actual SARAH export\n')
    (root/'parameters.py').write_text("""ZERO=Parameter(name='ZERO',nature='internal',type='real',value='0.0')
MH=Parameter(name='MH',nature='external',type='real',value=125.,lhablock='MASS',lhacode=[25])
WH=Parameter(name='WH',nature='external',type='real',value=.004,lhablock='DECAY',lhacode=[25])
ME=Parameter(name='ME',nature='external',type='real',value=.000511,lhablock='MASS',lhacode=[11])
WE=Parameter(name='WE',nature='external',type='real',value=0.,lhablock='DECAY',lhacode=[11])
""")
    (root/'particles.py').write_text("""H=Particle(pdg_code=25,name='H',antiname='H',spin=1,color=1,mass=Param.MH,width=Param.WH,charge=0)
e=Particle(pdg_code=11,name='e',antiname='ebar',spin=2,color=1,mass=Param.ME,width=Param.WE,charge=-1)
ebar=e.anti()
""")
    (root/'couplings.py').write_text("GC=Coupling(name='GC',value='-complex(0,1)*ye',order={'QED':1})\n")
    (root/'lorentz.py').write_text("FFS=Lorentz(name='FFS',spins=[2,2,1],structure='Identity(2,1)')\n")
    (root/'vertices.py').write_text("V=Vertex(name='V',particles=[P.ebar,P.e,P.H],color=['1'],lorentz=[L.FFS],couplings={(0,0):C.GC})\n")


def test_ready_dispatch_and_script(config,tmp_path):
    cg,_=config; assert p.validate_config(cg)==cg
    doc=tmp_path/'c.json';c._write(doc,cg); assert Path(cg['kernel']['path']) in p.inputs({'config':str(doc)},tmp_path)
    script=s.readiness_script(Path('/p'),Path('/r'))
    assert 'OwnValues[SARAH`CheckModel]' in script and 'DownValues[SARAH`Start]' in script
    assert 'SA`Parallelize=False' in script and 'Start[' not in script and 'CheckModel[]' not in script
    assert p.adjudicate(readiness(cg,Path('/p')),cg,Path('/p'),72)['passed']


@pytest.mark.parametrize('key,value',[('schema_version',True),('trusted_provider_source',False),('expected_provider_version','4.15.3'),('expected_kernel_version',True),('max_seconds',121),('max_ram_mib',8192),('existing_installation_license_status','licensed')])
def test_readiness_refuses(config,key,value):
    cg,_=config;cg[key]=value
    with pytest.raises(ValueError):p.validate_config(cg)


@pytest.mark.parametrize('key,value',[('process_id',True),('provider_kind','feynrules'),('parallel_kernel_count',True),('definition_kinds',{'CheckModel':'down'}),('entrypoint_definition_counts',{'Start':1}),('load_messages',['warning']),('model_calculation_performed',True),('provider_version','2.3.49')])
def test_native_readiness_refuses(config,key,value):
    cg,_=config;n=readiness(cg,Path('/p'));n[key]=value;assert not p.adjudicate(n,cg,Path('/p'),72)['passed']


def test_qualified_receipt(config):
    cg,_=config;n=readiness(cg,Path('/p'));checks=s.readiness_adjudicate(n,cg,Path('/p'),72)
    r={'status':'passed','physics_validated':False,'generated_events':0,'model_calculation_performed':False,
       'checks':checks,'native_provider':n,'native_execution':{'returncode':0,'resource_violation':None,'command':['/kernel']}}
    assert d.qualified_receipt(r,15.0)==r
    with pytest.raises(ValueError):d.qualified_receipt(r,14.3)
    r['checks']['checks']['fake']=True
    with pytest.raises(ValueError):d.qualified_receipt(r)


@pytest.mark.parametrize('key,value',[('model_name','../SM'),('model_name','SM];Run["x"]'),('eigenstate','EWSB;Exit[]'),('trusted_model_source',False),('point_policy','defaults'),('max_seconds',True),('max_seconds',901),('expected_provider_version','2.3.49')])
def test_derivation_config_refuses(config,key,value):
    _,cg=config;cg[key]=value
    with pytest.raises(ValueError):d.validate_config(cg)


@pytest.mark.parametrize('key,value',[('exclude',['ASS']),('exclude',[[]]),('exclude',['SSSS','SSSS']),('include_effective_higgs_vertices',1),('bsm_couplings',['gX']),('must_include',['h']),('read_lists',True),('replacements',{'x':'y'}),('python2',True)])
def test_unsupported_options(config,key,value):
    _,cg=config;cg['ufo_options'][key]=value
    with pytest.raises(ValueError):d.validate_config(cg)


def test_script_real_api_semantics(config):
    _,cg=config;t=d.script(cg,Path('/p'),Path('/m'),Path('/o/exported-ufo'),Path('/r'))
    assert 'SARAH`Start["SM"]' in t and 'SARAH`CheckModel,$Failed' in t and 'CheckModel[]' not in t
    assert t.index('SA`Parallelize=False')<t.index('Get[')<t.index('SARAH`Start[')<t.index('SARAH`CheckModel,$Failed')<t.index('SARAH`MakeUFO[')
    assert 'SARAH`ReadLists->False' in t and 'SARAH`python2->False' in t and 'SARAH`IncludeEffectiveHiggsVertices->False' in t
    assert 'SARAH`SixParticleInteractions->False' in t and 'SARAH`IncludeLoopCorrections->False' in t
    assert '"effective_exclude"->{"ASS"}' in t and 'SARAH`SARAH[SARAH`InputDirectories]={"/m"}' in t
    assert 'MakeSPheno[' not in t and 'LaunchKernels' not in t and 'ComputeWidths' not in t


@pytest.mark.parametrize('key,value',[('state_names',['EWSB','GaugeES']),('requested_eigenstate','GaugeES'),('input_directories',['/m','/fallback']),('check_model_return_expression','$Failed'),('check_model_boolean_certificate',True),('check_model_messages',['anomaly']),('effective_exclude',[]),('explicit_ufo_options_json','{}'),('export_completed',False),('native_ufo_root','/other/UFO'),('decay_calculation_requested',True),('model_calculation_performed',False)])
def test_derivation_adjudication(config,key,value):
    _,cg=config;n=native(cg,Path('/p'),Path('/m'),Path('/o/exported-ufo'));n[key]=value
    assert not d.adjudicate(n,cg,Path('/p'),Path('/m'),Path('/o/exported-ufo'),72)['passed']


def test_null_is_raw_diagnostic_not_physics(config,tmp_path):
    _,cg=config;ex=tmp_path/'exported-ufo';n=native(cg,Path('/p'),Path('/m'),ex)
    r=d.adjudicate(n,cg,Path('/p'),Path('/m'),ex,72)
    assert r['passed'] and r['check_model_physical_acceptance'] is None
    assert 'Null' in r['diagnostic_interpretation']


def test_complete_census(config,tmp_path):
    _,cg=config;ex=tmp_path/'ufo';write_ufo(ex);r=s.ufo_census(ex,cg['particle_conventions'])
    assert len(r['particles'])==3 and len(r['all_literal_external_card_parameters'])==4
    assert r['particles']['ebar']['pdg']==-11 and r['particles']['ebar']['charge']==1
    assert not r['coupling_expressions_evaluated'] and not r['physical_model_validated']
    assert '-complex(0,1)*ye' in r['couplings']['GC']['source_expression']


@pytest.mark.parametrize('name,old,new',[('particles.py','spin=1','spin=2'),('particles.py','charge=0','charge=True'),('particles.py','Param.MH','Param.MISSING'),('particles.py','pdg_code=11','pdg_code=25'),('parameters.py','lhacode=[25]','lhacode=[26]'),('vertices.py','C.GC','C.MISSING'),('vertices.py','P.ebar','P.MISSING'),('vertices.py','L.FFS','L.MISSING'),('couplings.py',"GC=Coupling", "GC=NotCoupling")])
def test_census_faults(config,tmp_path,name,old,new):
    _,cg=config;ex=tmp_path/'ufo';write_ufo(ex);p0=ex/name;p0.write_text(p0.read_text().replace(old,new))
    with pytest.raises((ValueError,KeyError)):s.ufo_census(ex,cg['particle_conventions'])


def test_rational_charge(config,tmp_path):
    _,cg=config;ex=tmp_path/'ufo';write_ufo(ex);f=ex/'particles.py';f.write_text(f.read_text().replace('charge=-1','charge=-1/3'))
    assert s.ufo_census(ex,cg['particle_conventions'])['particles']['e']['charge']==float(-1/3)
    f.write_text(f.read_text().replace('charge=-1/3','charge=evil()'))
    with pytest.raises(ValueError):s.ufo_census(ex,cg['particle_conventions'])


def test_readiness_full_worker_body(config,tmp_path,monkeypatch):
    cg,_=config;doc=tmp_path/'config.json';c._write(doc,cg);task={'config':str(doc)};root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(p,'_approved',lambda t,o:(root,{'max_seconds':60}))
    from ravel.physics import reinterpret_db
    def fake(command,o,control):
        c._write(o/'native-process.json',{'pid':72});c._write(o/'native-provider.json',readiness(cg,root/'work/model-provider-bridge/attempt-1/sarah'))
        return {'returncode':0,'resource_violation':None,'command':command}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake);os.environ['WOLFRAMINIT']='unit-init'
    r=p.run(task,tmp_path,out)
    assert r['status']=='passed' and not r['physics_validated'] and os.environ['WOLFRAMINIT']=='unit-init'
    assert 'SARAH' in (out/'qualification.wl').read_text() and 'FeynRules`' not in (out/'qualification.wl').read_text()


@pytest.mark.parametrize('point_selected',[False,True])
def test_derivation_full_worker_body(config,tmp_path,monkeypatch,point_selected):
    _,cg=config
    if point_selected:
        fixture=tmp_path/'fixture';write_ufo(fixture);point=tmp_path/'point.dat';point.write_text(d.literal_external_card((fixture/'parameters.py').read_text())[0])
        cg.update(point_policy='supplied_complete_card',parameter_card=pin(point))
    prior=tmp_path/'prior.json';prior.write_text('{"scope":"explicit unit prior, no actual readiness authority"}');cg['provider_readiness_receipt']=pin(prior)
    monkeypatch.setattr(d,'_qualification',lambda control,base:(c.source_tree(Path(control['provider_tree']['root'])),[]))
    doc=tmp_path/'config.json';c._write(doc,cg);task={'config':str(doc)};root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(d,'_approved',lambda t,o:(root,{'max_seconds':60}))
    from ravel.physics import reinterpret_db
    def fake(command,o,control):
        work=root/'work/model-derivation-bridge/attempt-1'
        c._write(o/'native-process.json',{'pid':72});c._write(o/'native-derivation.json',native(cg,work/'sarah',work/'model_source',o/'exported-ufo'))
        write_ufo(o/'exported-ufo');return {'returncode':0,'resource_violation':None,'command':command}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    r=d.run(task,tmp_path,out)
    retained=c._read(out/'model-derivation-bridge.json')
    assert retained==r
    assert retained['exported_source']['point_policy']==cg['point_policy']
    assert retained['exported_source']['provided_parameter_card_input']==cg['parameter_card']
    assert r['status']=='passed' and r['handoff_eligible'] is point_selected and not r['physics_validated']
    assert r['check_model_physical_acceptance'] is None and len(r['particle_convention_census']['particles'])==3
    assert r['effective_ufo_options']['effective_exclude']==['ASS']
    assert (out/'model-tool-handoff-candidate.json').exists() is point_selected
    if point_selected:
        c._pin(r['exported_source']['parameter_card'],out)
        assert Path(r['exported_source']['parameter_card']['path']).read_bytes()==point.read_bytes()
        candidate=c._read(out/'model-tool-handoff-candidate.json')
        assert not candidate['execution_authority_granted']
        assert all(candidate.get(k)==v for k,v in retained['exported_source'].items())
        assert candidate['derivation_result']['sha256']==c._hash(out/'model-derivation-bridge.json')
        from ravel.workflow import science,execution,physics_review
        monkeypatch.setattr(science,'verify_approval_envelope',lambda root:[])
        monkeypatch.setattr(execution,'stage_errors',lambda root,stage:[])
        monkeypatch.setattr(physics_review,'status',lambda root:{'state':'accepted','claim_scope':'model_source_derivation','cycle_id':'unit-synthetic','attestation':{'scope':'explicit synthetic authority stand-in'}})
        monkeypatch.setattr(physics_review,'gate_errors',lambda root,scope:[])
        record=root/'attempt.json';c._write(record,{'scope':'explicit unit attempt, no executed provider'})
        monkeypatch.setattr(execution,'load_execution',lambda root:{'stages':{'science':{'outputs':[str(out)],'attempt_id':'unit','attempt_record':str(record)}}})
        qualified=d.qualified_handoff(root,tmp_path/'qualified.json')
        assert qualified['provided_parameter_card_input']==pin(point)
        assert qualified['point_policy']=='supplied_complete_card'
        assert not qualified['execution_authority_granted']
    else: assert r['exported_source']['parameter_card'] is None
    assert (out/'exported-source-card.dat').read_text().count('DECAY')==2
    assert not r['exported_source']['native_export_default_card']['selected_as_physical_point']


def test_no_prior_no_derivation(config,tmp_path):
    _,cg=config;doc=tmp_path/'config.json';c._write(doc,cg)
    with pytest.raises(ValueError):d.inputs({'config':str(doc)},tmp_path)


def test_supplied_complete_point_overrides_every_native_default(config,tmp_path):
    _,cg=config; ex=tmp_path/'ufo';write_ufo(ex);text,rows=d.literal_external_card((ex/'parameters.py').read_text())
    original=tmp_path/'point.dat';original.write_text(text.replace('125','130'));cg.update(point_policy='supplied_complete_card',parameter_card=pin(original))
    s.validate_derivation(cg); result=s.select_card(cg,tmp_path,rows,tmp_path/'selected.dat')
    assert (tmp_path/'selected.dat').read_bytes()==original.read_bytes() and set(result)=={'path','sha256'}
    assert '130' in original.read_text()
    original.write_text(text+'BLOCK EXTRA\n1 3\n');cg['parameter_card']=pin(original)
    with pytest.raises(ValueError):s.select_card(cg,tmp_path,rows,tmp_path/'refused.dat')
    assert not (tmp_path/'refused.dat').exists()


@pytest.mark.parametrize('mutation',[lambda t:t.replace('BLOCK MASS','BLOCK OMITTED'),lambda t:t.replace('DECAY 25 0.004','DECAY 25 -1'),lambda t:t+'DECAY 25 1\n'])
def test_supplied_card_missing_negative_duplicate(config,tmp_path,mutation):
    _,cg=config;ex=tmp_path/'ufo';write_ufo(ex);text,rows=d.literal_external_card((ex/'parameters.py').read_text())
    original=tmp_path/'point.dat';original.write_text(mutation(text));cg.update(point_policy='supplied_complete_card',parameter_card=pin(original))
    with pytest.raises(ValueError):s.select_card(cg,tmp_path,rows,tmp_path/'selected.dat')
    assert not (tmp_path/'selected.dat').exists()


def test_whole_ordinary_cli_is_reachable_without_kernel(capsys):
    with pytest.raises(SystemExit) as exit0:p.main(['plan-sarah','--help'])
    assert exit0.value.code==0 and '--sarah' in capsys.readouterr().out
    with pytest.raises(SystemExit) as exit0:d.main(['plan-sarah','--help'])
    text=capsys.readouterr().out
    assert exit0.value.code==0 and '--point-policy' in text and '--particle-conventions' in text


@pytest.mark.parametrize('indices',['{(1,0):C.GC}','{(0,1):C.GC}','{(True,0):C.GC}','{(0,0):C.GC,(0,0):C.GC}'])
def test_vertex_basis_faults(config,tmp_path,indices):
    _,cg=config;ex=tmp_path/'ufo';write_ufo(ex);f=ex/'vertices.py';f.write_text(f.read_text().replace('{(0,0):C.GC}',indices))
    with pytest.raises(ValueError):s.ufo_census(ex,cg['particle_conventions'])


def test_native_option_bool_alias_is_not_actual_boolean(config,tmp_path):
    _,cg=config;ex=tmp_path/'ufo';n=native(cg,Path('/p'),Path('/m'),ex);n['model_output_choices']['vertices']=1
    assert not d.adjudicate(n,cg,Path('/p'),Path('/m'),ex,72)['passed']


@pytest.mark.parametrize('filename,old,new',[('particles.py','Param.MH','Other.MH'),('vertices.py','P.H','Other.H'),('vertices.py','L.FFS','Other.FFS'),('vertices.py','C.GC','Other.GC')])
def test_source_reference_namespace_is_not_discarded(config,tmp_path,filename,old,new):
    _,cg=config;ex=tmp_path/'ufo';write_ufo(ex);f=ex/filename;f.write_text(f.read_text().replace(old,new))
    with pytest.raises(ValueError):s.ufo_census(ex,cg['particle_conventions'])


def test_actual_model_triplet_is_required_before_prior_or_kernel(config,tmp_path):
    _,cg=config;model=Path(cg['model_tree']['root']);(model/'SM/particles.m').unlink()
    cg['model_tree']=tree(model,tmp_path/'model-updated.json');doc=tmp_path/'c.json';c._write(doc,cg)
    with pytest.raises(ValueError,match='particles.m'):d.inputs({'config':str(doc)},tmp_path)


def test_wrong_source_version_cannot_gain_readiness(config,tmp_path):
    cg,_=config;provider=Path(cg['provider_tree']['root']);(provider/'SARAH.m').write_text('SA`Version="4.14.0";')
    cg['provider_tree']=tree(provider,tmp_path/'provider-updated.json');doc=tmp_path/'c.json';c._write(doc,cg)
    with pytest.raises(ValueError,match='version'):p.inputs({'config':str(doc)},tmp_path)


def test_original_runtime_mutation_keeps_native_evidence_but_refuses(config,tmp_path,monkeypatch):
    cg,_=config;doc=tmp_path/'c.json';c._write(doc,cg);task={'config':str(doc)};root=tmp_path/'run';root.mkdir();out=root/'outputs/attempt-1'
    monkeypatch.setattr(p,'_approved',lambda t,o:(root,{'max_seconds':60}))
    from ravel.physics import reinterpret_db
    def fake(command,o,control):
        c._write(o/'native-process.json',{'pid':72});c._write(o/'native-provider.json',readiness(cg,root/'work/model-provider-bridge/attempt-1/sarah'))
        Path(cg['application_metadata']['path']).write_text('changed original runtime metadata')
        return {'returncode':0,'resource_violation':None,'command':command}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    with pytest.raises(ValueError,match='pin changed'):p.run(task,tmp_path,out)
    assert (out/'native-provider.json').exists() and not (out/'model-provider-bridge.json').exists()


def test_card_buffer_rejects_mutation_after_population_validation(config,tmp_path,monkeypatch):
    _,cg=config;ex=tmp_path/'ufo';write_ufo(ex);text,rows=d.literal_external_card((ex/'parameters.py').read_text())
    original=tmp_path/'point.dat';original.write_text(text);cg.update(point_policy='supplied_complete_card',parameter_card=pin(original))
    from ravel.validation import model_tool_witness
    parser=model_tool_witness.card_values
    def mutate_after(text):
        result=parser(text);original.write_text(text+'BLOCK EXTRA\n 1 2.0\n');return result
    monkeypatch.setattr(model_tool_witness,'card_values',mutate_after)
    destination=tmp_path/'selected.dat'
    with pytest.raises(ValueError,match='changed during captured-buffer validation'):
        s.select_card(cg,tmp_path,rows,destination)
    assert not destination.exists()


def test_card_buffer_rejects_output_drift(config,tmp_path,monkeypatch):
    _,cg=config;ex=tmp_path/'ufo';write_ufo(ex);text,rows=d.literal_external_card((ex/'parameters.py').read_text())
    original=tmp_path/'point.dat';original.write_text(text);cg.update(point_policy='supplied_complete_card',parameter_card=pin(original))
    destination=tmp_path/'selected.dat';write=Path.write_bytes
    def corrupt(path,raw):
        return write(path,raw+b'BLOCK EXTRA\n 1 2.0\n') if path==destination else write(path,raw)
    monkeypatch.setattr(Path,'write_bytes',corrupt)
    with pytest.raises(ValueError,match='selected output changed'):
        s.select_card(cg,tmp_path,rows,destination)
