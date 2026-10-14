"""Portable native response source compiler controls; no native tools run."""
from copy import deepcopy
import hashlib,json,os
from pathlib import Path
import pytest
from ravel.physics import rivet_response_component as response
from ravel.physics import rivet_event_components as event
from ravel import analysis_sources
from ravel.physics import routine_build


def sha(raw):return hashlib.sha256(raw).hexdigest()

def load(p):return json.loads(p.read_bytes())

def fn(id,typ,name):return{'id':id,'type':typ,'value':{'kind':'builtin','name':name}}

def basic(kind='particles'):
 fs=[fn('eff','particle_eff','PARTICLE_EFF_ONE'),fn('smear','particle_smear','PARTICLE_SMEAR_IDENTITY')]
 node={'kind':'particles','id':'detected','projection_name':'Detected','input':'truth','steps':['smear','eff'],'cuts':[],'pids':None,'outputs':[{'id':'accepted','access':'particles_by_pt','cuts':[]}]}
 return{'schema_version':1,'kind':'native-rivet-response-components','native_api':'4.1.4','functions':fs,'nodes':[node]}

def compile(r,**kw):return response.compile_component(r,particle_inputs={'truth':'truth'},jet_inputs={'truthjets':'truthjets'},met_inputs={'truthmet':'truthmet'},**kw)

def met(params=True,smear=True):
 r=basic();r['functions']=([fn('params','met_params','MET_SMEARPARAMS_IDENTITY')]if params else[])+([fn('smear','met_smear','MET_SMEAR_IDENTITY')]if smear else[])
 r['nodes']=[{'kind':'met','id':'detmet','projection_name':'DetMET','input':'truthmet','params':'params'if params else None,'smear':'smear'if smear else None,'outputs':[]}];return r

def test_order_and_reco_cut_phase_native_types():
 r=basic();r['nodes'][0]['cuts']=[{'field':'pt','relation':'gt','value':20,'unit':'GeV'}]
 c=compile(r)
 assert 'truth, (Cuts::pT > 20.0*GeV), ParticleEffSmearFn(ParticleSmearFn(PARTICLE_SMEAR_IDENTITY)), ParticleEffSmearFn(ParticleEffFn(PARTICLE_EFF_ONE))'in c['init']
 assert '.particlesByPt(Cuts::OPEN)'in c['analyze']
 assert c['response_semantics'][0]['cuts']=='after_all_transforms_on_reco_particle'
 assert not c['native_executed']and not c['physics_validated']

@pytest.mark.parametrize('origin,native',[('all','ANY'),('prompt','NODECAY'),('decay','DECAY')])
@pytest.mark.parametrize('decay,native_decay',[('all','ANY'),('leptonic','LEPTONIC'),('hadronic','HADRONIC')])
def test_tau_native_input_and_origin(origin,native,decay,native_decay):
 r=basic();r['functions']=[];r['nodes']=[{'kind':'tau','id':'taus','projection_name':'Taus','origin':origin,'decay':decay,'cuts':[],'pids':None,'outputs':[{'id':'tauout','access':'taus','cuts':[]}]}]
 c=compile(r);assert f'TauFinder taus(TauDecay::{native_decay}, LeptonOrigin::{native}, Cuts::OPEN)'in c['init'];assert '.taus()'in c['analyze']


@pytest.mark.parametrize('params,smear',[(True,False),(False,True),(True,True)])
def test_met_native_overloads_and_units(params,smear):
 r=met(params,smear);r['nodes'][0]['outputs']=[{'id':'missing','quantity':'missing_pt','unit':'GeV'},{'id':'energy','quantity':'scalar_visible_et','unit':'GeV'}]
 c=compile(r);assert 'truthmet'in c['init'];assert ('METSmearParamsFn('in c['init'])==params;assert ('METSmearFn('in c['init'])==smear
 assert '.missingPt()/GeV'in c['analyze']and '.scalarSumEt()/GeV'in c['analyze']


@pytest.mark.parametrize('quantity',['pt_resolution','et_resolution','pt_significance','et_significance'])
def test_met_resolution_parameter_requirement(quantity):
 r=met(False,True);r['nodes'][0]['outputs']=[{'id':'value','quantity':quantity,'unit':'1'if'significance'in quantity else'GeV'}]
 with pytest.raises(ValueError,match='parameter'):compile(r)
 r=met(True,False);r['nodes'][0]['outputs']=[{'id':'value','quantity':quantity,'unit':'1'if'significance'in quantity else'GeV'}];compile(r)


def test_met_chaining_is_not_native_missing_momentum():
 r=met();later=deepcopy(r['nodes'][0]);later.update(id='later',projection_name='Later',input='detmet');r['nodes'].append(later)
 with pytest.raises(ValueError,match='prior compatible'):compile(r)

def test_jet_steps_tags_and_truth_fallback():
 r=basic();r['functions']=[fn('smear','jet_smear','JET_SMEAR_IDENTITY'),fn('eff','jet_eff','JET_EFF_ONE')];r['nodes']=[{'kind':'jets','id':'reco','projection_name':'Reco','input':'truthjets','b_tag':None,'c_tag':None,'steps':['eff','smear'],'outputs':[{'id':'before','access':'truth_jets','cuts':[]},{'id':'after','access':'jets_by_pt','cuts':[]}]}]
 c=compile(r);assert 'truthjets, JetEffFn{}, JetEffFn{}, JetEffSmearFn(JetEffFn(JET_EFF_ONE)), JetEffSmearFn(JetSmearFn(JET_SMEAR_IDENTITY))'in c['init'];assert '.truthJets()'in c['analyze'];assert 'beff_not_ceff'in c['response_semantics'][0]['native_c_tag_warning']

@pytest.mark.parametrize('mutation',[lambda r:r.update(native_api='4.1.3'),lambda r:r['nodes'][0].update(input='future'),lambda r:r['functions'][0]['value'].update(name='JET_EFF_ONE'),lambda r:r['nodes'][0].update(id='SmearedMET'),lambda r:r['nodes'][0].update(projection_name='bad/name'),lambda r:r['nodes'][0].update(steps=['missing']),lambda r:r['functions'].append(fn('unused','particle_eff','PARTICLE_EFF_ONE')),lambda r:r['nodes'].append(deepcopy(r['nodes'][0])),lambda r:r['nodes'][0]['outputs'][0].update(access='truth_particles',cuts=[{'field':'pt','relation':'gt','value':1,'unit':'GeV'}])])
def test_closed_typed_and_consumed_census(mutation):
 r=basic();mutation(r)
 with pytest.raises(ValueError):compile(r)


def test_exact_source_span_and_full_proof():
 raw=b'// complete source\n[](const Particle& p) -> double { return 1.; }\n';start=raw.index(b'[]');end=len(raw)-1
 r=basic();r['functions'][0]['value']={'kind':'source_expression','binding':{'path':'proof.cc','sha256':sha(raw),'size':len(raw),'start':start,'end':end,'expression_sha256':sha(raw[start:end])}}
 c=compile(r,source_units={'proof.cc':raw});assert raw[start:end].decode()in c['init'];assert c['source_dependencies']==[{'path':'proof.cc','sha256':sha(raw),'size':len(raw)}]
 with pytest.raises(ValueError):compile(r,source_units={'proof.cc':raw.replace(b'1.',b'0.')})
 r['functions'][0]['value']['binding']['end']-=1
 with pytest.raises(ValueError):compile(r,source_units={'proof.cc':raw})

def synthetic():
 template=b'#include "Rivet/Analysis.hh"\n// RAVEL_EVENT_HEADERS\nvoid init(){\n// RAVEL_EVENT_INIT\n}\nvoid analyze(){\n// RAVEL_EVENT_ANALYZE\n}\n'
 files={'Example.cc':b'original complete source\n','assets/model.bin':b'complete binary model'}
 capsule={'schema_version':1,'kind':'analysis-source-capsule','framework':'rivet','routine':'Example','source':{'repository':'supplied','revision':None,'description':'Inert complete source control'},'root':'original-root','files':[{'path':k,'sha256':sha(v),'role':'compile'if k=='Example.cc'else'model'}for k,v in files.items()],'layout':{'include_dirs':[],'asset_dirs':['assets']},'dependencies':[{'name':'model','kind':'asset','status':'resolved','files':['assets/model.bin'],'reason':'synthetic immutable asset'}],'dependency_review':{'complete':True,'description':'synthetic original only, no scientific vote'},'submodules':[]}
 recipe={'schema_version':1,'kind':'native-rivet-event-components','particles':{'schema_version':1,'kind':'native-rivet-particle-components','nodes':[{'kind':'stable','id':'truth','projection_name':'Truth','output':None,'cuts':[],'pids':None}]},'dileptons':[],'jets':[],'missing_momentum':[],'response':basic()}
 return capsule,template,recipe,files

def material(tmp_path,**kw):
 c,t,r,f=synthetic();values=dict(compile_unit='Example.cc',template=t,expected_sha256=sha(t),recipe=r,files=f,root=tmp_path/'new');values.update(kw);return response.materialize(c,**values)

def test_fresh_materialization_full_asset_and_no_old_review(tmp_path):
 result=material(tmp_path);c=analysis_sources.load_capsule(result['capsule']);assert not c['dependency_review']['complete'];assert not result['scientific_accepted'];assert (Path(c['root'])/'assets/model.bin').read_bytes()==b'complete binary model'
 with pytest.raises(ValueError,match='fresh'):material(tmp_path)

@pytest.mark.parametrize('which',['missing','changed','extra'])
def test_materialization_original_content_exact(tmp_path,which):
 c,t,r,f=synthetic()
 if which=='missing':f.pop('assets/model.bin')
 elif which=='changed':f['assets/model.bin']=b'substituted'
 else:f['other']=b'undeclared'
 with pytest.raises(ValueError):material(tmp_path,files=f)
 assert not(tmp_path/'new').exists()


@pytest.mark.parametrize('mutation',['change','restore','symlink'])
def test_late_generated_file_custody(tmp_path,monkeypatch,mutation):
 from ravel.workflow import research_cycle as cycle
 original=cycle._bounded_source_snapshot;changed=False
 def observed(path,maximum):
  nonlocal changed
  result=original(path,maximum)
  if path.name=='source-capsule.json'and not changed:
   changed=True;target=path.parent/'source/Example.cc';raw=target.read_bytes()
   if mutation=='symlink':target.unlink();target.symlink_to(path)
   else:
    target.write_bytes(raw+b'changed')
    if mutation=='restore':target.write_bytes(raw)
  return result
 monkeypatch.setattr(cycle,'_bounded_source_snapshot',observed)
 with pytest.raises(ValueError,match='custody'):material(tmp_path)



@pytest.mark.parametrize('relation',['equal','descendant','dot_descendant','ancestor'])
def test_original_root_disjointness_refuses_before_mkdir(tmp_path,monkeypatch,relation):
    cap,template,recipe,files=synthetic()
    original=tmp_path/'original';original.mkdir()
    for relative,raw in files.items():
        path=original/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    cap['root']=str(original)
    before=sorted(str(p.relative_to(original))for p in original.rglob('*'))
    if relation=='equal':destination=original
    elif relation=='descendant':destination=original/'derived'
    elif relation=='dot_descendant':destination=original/'assets'/'..'/'derived'
    else:destination=tmp_path
    observed=[];mkdir=Path.mkdir
    def forbid_write(path,*args,**kwargs):observed.append(str(path));raise AssertionError('overlap guard must precede every mkdir')
    monkeypatch.setattr(Path,'mkdir',forbid_write)
    with pytest.raises(ValueError,match='disjoint'):
        response.materialize(cap,compile_unit='Example.cc',template=template,expected_sha256=sha(template),recipe=recipe,files=files,root=destination)
    assert not observed
    assert sorted(str(p.relative_to(original))for p in original.rglob('*'))==before


@pytest.mark.parametrize('which',['source_alias','destination_alias'])
def test_original_root_alias_overlap_refuses_before_mkdir(tmp_path,monkeypatch,which):
    cap,template,recipe,files=synthetic();original=tmp_path/'original';original.mkdir()
    alias=tmp_path/'alias';alias.symlink_to(original,target_is_directory=True)
    cap['root']=str(alias if which=='source_alias'else original)
    destination=original/'derived'if which=='source_alias'else alias/'derived'
    monkeypatch.setattr(Path,'mkdir',lambda *args,**kwargs:pytest.fail('no write on source/output alias overlap'))
    with pytest.raises(ValueError,match='disjoint'):
        response.materialize(cap,compile_unit='Example.cc',template=template,expected_sha256=sha(template),recipe=recipe,files=files,root=destination)
    assert list(original.iterdir())==[]


def test_relative_source_root_uses_current_invocation_base(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);cap,template,recipe,files=synthetic();cap['root']='original'
    with pytest.raises(ValueError,match='disjoint'):
        response.materialize(cap,compile_unit='Example.cc',template=template,expected_sha256=sha(template),recipe=recipe,files=files,root=Path('original')/'derived')
    assert not(tmp_path/'original').exists()


def test_disjoint_guard_does_not_infer_liveness_or_blanket_alias_acceptance(tmp_path):
    # A missing declared original root remains a byte-supplied source, with no
    # physical-source validation or acceptance gained from source construction.
    output=response._disjoint_destination(tmp_path/'other',str(tmp_path/'missing-original'))
    assert output==tmp_path/'other';assert not output.exists()


def test_existing_directory_alias_identity_guard(tmp_path,monkeypatch):
    source=tmp_path/'original';source.mkdir();alias=tmp_path/'different-spelling';alias.symlink_to(source,target_is_directory=True)
    # Keep alias spelling to model canonical text retaining filesystem case.
    # Identity is genuine stat evidence from the actual symlinked directory.
    resolve=Path.resolve
    def retain_alias(path,*args,**kwargs):
        return path if path==alias/'derived'else resolve(path,*args,**kwargs)
    monkeypatch.setattr(Path,'resolve',retain_alias)
    with pytest.raises(ValueError,match='disjoint'):
        response._disjoint_destination(alias/'derived',str(source))
    assert list(source.iterdir())==[]
