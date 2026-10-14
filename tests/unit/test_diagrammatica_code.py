import copy,hashlib,json,sys,os
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType,SimpleNamespace
import pytest
from ravel.physics import diagrammatica_code as d
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json
UP=Path(os.environ.get('RAVEL_HEPTAPOD_TEST_SOURCE', '/__ravel_optional_heptapod_fixture_missing__'))
@pytest.fixture
def require_backend():
 if any(not (UP/rel).is_file() or hashlib.sha256((UP/rel).read_bytes()).hexdigest()!=sha for rel,sha in d.BACKEND.items()):
  pytest.skip('optional exact GPL HEPTAPOD v2.1.0 source fixture not supplied; no download/install')
@pytest.fixture(autouse=True)
def no_backend_launch(monkeypatch):
 import subprocess,urllib.request
 monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(OSError('no process launch; stdlib identity fallback only')))
 monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('no network')))
def request(tmp_path,family='SFF',basis='scalar',identical=False):
 source=tmp_path/'declared-model.txt';source.write_text('Explicit synthetic single-vertex coefficient and species definition; no model certification.\n')
 def p(label,spin,mass,anti=False):return {'label':label,'spin':spin,'mass':mass,'antiparticle':anti,'self_conjugate':spin!=.5}
 if family=='SSS':
  initial=[p('S',0,13)];final=[p('s1',0,2),p('s1' if identical else 's2',0,2 if identical else 3)];nc=1
 else:
  initial=[p('S' if family=='SFF' else 'V',0 if family=='SFF' else 1,13)];final=[p('f1',.5,2),p('f2bar',.5,3,True)];nc=3
 coupling={'gL':'gL','gR':'gR'} if basis=='chiral' else {'gV':'gV','gA':'gA'} if basis=='vector-axial' else 'g'
 symbols=list(coupling.values()) if isinstance(coupling,dict) else [coupling]
 backend={rel:{'path':str(UP/rel),'sha256':sha} for rel,sha in d.BACKEND.items()}
 doc={'schema_version':1,'operation':'symbolic_decay_code','units':'GeV','release':d.RELEASE,'backend_files':backend,'diagram':{'initial':initial,'final':final,'vertices':[{'type':basis,'coupling':coupling}],'color_factor':nc},'grounding':[{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}],'vertex_coefficient_definition':'Synthetic coefficient g multiplies the explicitly declared vertex tensor; no operator normalization inferred.','coupling_dimensions_GeV':{x:1 if family=='SSS' else 0 for x in symbols},'max_seconds':20}
 path=tmp_path/'request.json';atomic_json(path,doc)
 return doc,path,{'input':str(path)}
def save(path,doc):atomic_json(path,doc)

@pytest.mark.parametrize('family,basis,needle',[('SFF','scalar','SpinorUBar'),('SFF','pseudoscalar','GA[5]'),('SFF','chiral','GA[7]'),('VFF','vector','GAD[mu0]'),('VFF','vector-axial','gV'),('VFF','chiral','GA[7]'),('SSS','scalar','amp = I (g)')])
@pytest.mark.usefixtures('require_backend')
def test_actual_released_api_generates_unexecuted_code(tmp_path,family,basis,needle):
 doc,path,task=request(tmp_path,family,basis);out=tmp_path/'out';r=d.run(task,tmp_path,out)
 raw=(out/'upstream-symbolic.wl').read_text();code=(out/'decay-symbolic.wl').read_text()
 assert r['status']=='passed' and needle in raw and raw in code
 assert 'width = pMag / (8 Pi' in raw and 'Conjugate[' in raw
 assert ('nInit = 3;' if family=='VFF' else 'nInit = 1;') in raw
 assert r['evaluated_width'] is None and r['native_calls']==0 and r['physics_validated'] is False and r['execution_authorized'] is False
 assert r['couplings_assumed_real'] is False and r['numeric_masses_are_open_domain_witness_only']
 assert r['script_sha256']==hashlib.sha256(code.encode()).hexdigest()
 assert r['raw_upstream_sha256']==hashlib.sha256(raw.encode()).hexdigest()
 assert '= 13;' not in raw and '= 2;' not in raw

@pytest.mark.usefixtures('require_backend')
def test_identical_scalar_symmetry_once(tmp_path):
 _,_,task=request(tmp_path,'SSS','scalar',identical=True);d.run(task,tmp_path,tmp_path/'out');raw=(tmp_path/'out/upstream-symbolic.wl').read_text()
 assert 'symmetryFactor = 2;' in raw and 'colorFactor = 1;' in raw and 'nInit = 1;' in raw
 assert raw.count('/ symmetryFactor;')==1

@pytest.mark.usefixtures('require_backend')
def test_same_species_mass_identification_preserves_raw_script(tmp_path):
 doc,path,task=request(tmp_path);doc['diagram']['final'][1].update(label='f1bar',mass=2);save(path,doc)
 r=d.run(task,tmp_path,tmp_path/'out')
 assert r['same_species_mass_coordinate_identifications']=={'mf1bar':'mf1'}
 raw=(tmp_path/'out/upstream-symbolic.wl').read_text();code=(tmp_path/'out/decay-symbolic.wl').read_text()
 assert 'mf1bar = mf1;' not in raw and code.count('mf1bar = mf1;')==1 and raw in code

@pytest.mark.parametrize('change',[lambda j:j.update(units='MeV'),lambda j:j.update(release='0'*40),lambda j:j['diagram']['vertices'][0].update(type='unknown'),lambda j:j['diagram']['initial'][0].update(mass=5),lambda j:j['diagram'].update(color_factor=2),lambda j:j['diagram']['final'][1].update(label='f2Bar',antiparticle=False),lambda j:j['diagram']['final'][1].update(label='positron',antiparticle=False),lambda j:j['diagram']['vertices'][0].update(coupling='g;Run[cmd]'),lambda j:j['diagram']['initial'][0].update(label='S*)Run[cmd](*'),lambda j:j['diagram']['final'][0].update(spin=True),lambda j:j.update(coupling_dimensions_GeV={'g':1}),lambda j:j['diagram']['vertices'][0].update(coupling='N'),lambda j:j['diagram']['final'][0].update(self_conjugate=True)])
def test_material_domain_and_code_injection_refuse_at_intake(tmp_path,change):
 doc,path,task=request(tmp_path);change(doc);save(path,doc)
 with pytest.raises(ValueError):d.inputs(task,tmp_path)
 assert not(tmp_path/'out').exists()

def test_same_species_inconsistent_mass_refuses(tmp_path):
 doc,path,task=request(tmp_path);doc['diagram']['final'][1]['label']='f1bar';save(path,doc)
 with pytest.raises(ValueError,match='same-species'):d.inputs(task,tmp_path)

@pytest.mark.usefixtures('require_backend')
def test_intake_executes_no_backend_and_enumerates_complete_bound_graph(tmp_path,monkeypatch):
 doc,path,task=request(tmp_path);monkeypatch.setattr(d,'_backend',lambda *a:(_ for _ in ()).throw(AssertionError('intake executed code')))
 files=d.inputs(task,tmp_path)
 assert set(map(str,files))=={str(path),*(x['path'] for x in doc['backend_files'].values()),doc['grounding'][0]['path']}
 assert d.execution_seconds(task,tmp_path)==20

def test_changed_backend_and_rebound_expected_hash_refuses(tmp_path):
 doc,path,task=request(tmp_path);rel=next(iter(doc['backend_files']));p=tmp_path/'altered.py';p.write_text('raise AssertionError("untrusted backend")')
 doc['backend_files'][rel]={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()};save(path,doc)
 with pytest.raises(ValueError,match='only exact'):d.inputs(task,tmp_path)

@pytest.mark.usefixtures('require_backend')
def test_symlink_source_refuses(tmp_path):
 doc,path,task=request(tmp_path);p=tmp_path/'link';p.symlink_to(Path(doc['grounding'][0]['path']));doc['grounding'][0]['path']=str(p);save(path,doc)
 with pytest.raises(ValueError):d.inputs(task,tmp_path)

@pytest.mark.usefixtures('require_backend')
def test_package_namespaces_restored_on_success_and_failure(tmp_path,monkeypatch):
 _,_,task=request(tmp_path);old=ModuleType('tools');monkeypatch.setitem(sys.modules,'tools',old)
 d.run(task,tmp_path,tmp_path/'out');assert sys.modules['tools'] is old
 assert 'tools.eda.feyncalc_codegen' not in sys.modules
 original=d._backend
 @contextmanager
 def refusing(sources):
  with original(sources) as (parser,generator):
   generator.SymbolicFeynCalcCodeGenerator.generate=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('synthetic generator failure'))
   yield parser,generator
 monkeypatch.setattr(d,'_backend',refusing)
 r=d.run(task,tmp_path,tmp_path/'bad');assert r['status']=='failed' and r['error']['message']=='synthetic generator failure'
 assert sys.modules['tools'] is old and (tmp_path/'bad/diagram-code-report.json').is_file()

@pytest.mark.usefixtures('require_backend')
def test_ending_input_drift_retains_raw_code_and_refuses_next_observation(tmp_path,monkeypatch):
 doc,path,task=request(tmp_path);original=d._backend;source=Path(doc['grounding'][0]['path'])
 @contextmanager
 def changing(sources):
  with original(sources) as modules:
   yield modules
   source.write_text('changed premise')
 monkeypatch.setattr(d,'_backend',changing)
 r=d.run(task,tmp_path,tmp_path/'out')
 assert r['status']=='failed' and r['ending_input_errors']==[str(source)] and r['raw_upstream_script']
 assert (tmp_path/'out/upstream-symbolic.wl').is_file()
 with pytest.raises(ValueError,match='pin differs'):d.inputs(task,tmp_path)

def policy():
 return {'schema_version':1,'actors':{'proposer':'synthetic-proposer','executor':'synthetic-executor','physics_critic':'synthetic-critic','skeptical_verifier':'synthetic-skeptic','physics_decider':'synthetic-decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'custody','kind':'integrity'}],'claim_scopes':{'code_delivery':{'checks':['custody'],'actions':['delivery']}}}
def specification(task):
 return {'schema_version':2,'mode':'diagrammatica-code','source':'Explicit synthetic released-backend source API control','assumptions':['No numerical amplitude or width, native runtime or model certification.'],'max_seconds':45,'approval_mode':'scripted_yes','max_attempts':1,'task':task,'review_policy':{'schema_version':1,'policy':policy(),'correction_contract':{'task_fields':[],'input_slots':[]}}}

@pytest.mark.usefixtures('require_backend')
def test_ordinary_schema2_plan_and_fresh_drift_guard(tmp_path):
 doc,path,task=request(tmp_path);sp=tmp_path/'science.json';save(sp,specification(task));rd=tmp_path/'study'
 p=science.plan(rd,sp)
 assert p['schema_version']==2 and (rd/'inputs/checkin1.json').is_file() and not(rd/'inputs/science-approval.json').exists()
 assert set(science.task_inputs(specification(task),tmp_path))==set(d.inputs(task,tmp_path))
 science.verify_plan(rd,approved=False)
 Path(doc['grounding'][0]['path']).write_text('changed')
 with pytest.raises(ValueError):science.verify_plan(rd,approved=False)
 assert not(rd/'execution_attempt.json').exists()

@pytest.mark.usefixtures('require_backend')
def test_current_mode_requires_schema2_and_unapproved_worker_refuses(tmp_path):
 _,_,task=request(tmp_path);spec=specification(task);legacy={k:v for k,v in spec.items() if k not in ('review_policy','max_attempts')};legacy['schema_version']=1
 with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'legacy',_specfile(tmp_path/'legacy.json',legacy))
 from ravel.physics.science_worker import main
 sp=_specfile(tmp_path/'spec.json',spec);rd=tmp_path/'study';science.plan(rd,sp)
 with pytest.raises(ValueError):main([str(rd),'--attempt','1'])
 assert not(rd/'outputs/attempt-1/diagrammatica-code').exists()

def _specfile(path,spec):save(path,spec);return path
