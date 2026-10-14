"""Synthetic writer transport/ordinary controls; no MA5 import or execution."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest
from ravel.physics import ma5_sfs_materialization as m, routine_build as rb
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json,read_json


def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

def fixture(tmp):
 tmp.mkdir(parents=True);root=tmp/'upstream';root.mkdir()
 for name in m.SOURCE_TREES:(root/name).mkdir(parents=True)
 files={**{r:b'ordinary source fixture\n' for r in (*m.EXTRA_SOURCE,*m.LIBRARIES)},
        'bin/ma5':b'version = "1.11.1"\n','madanalysis/core.py':b'# inert source\n','madanalysis/__init__.py':b''}
 for relative,raw in files.items():
  p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
 rows=[{'relative':r,'sha256':pin(root/r)['sha256'],'size':(root/r).stat().st_size,'mode':(root/r).stat().st_mode&0o777} for r in m.selected_source(root)]
 manifest=tmp/'manifest.json';atomic_json(manifest,{'schema_version':1,'root':str(root),'selection':'ma5-sfs-source-projection/v1','files':rows})
 assets={}
 for key,raw in {'source':'bool Example::Initialize() {}\n','header':'INIT_ANALYSIS(Example, "Example")\n#include "new_tagger.h"\n#include "new_smearer_reco.h"\n','info':'<analysis>Example source fixture</analysis>\n','sfs_card':'set main.fastsim.package = fastjet\ndefine smearer j with PT 0.1 [pt > 1]\ndefine reco_efficiency e 0.9 [pt > 10]\ndefine tagger b as b 0.5 [pt > 1]\n'}.items():
  p=tmp/key;p.write_text(raw);assets[key]=pin(p)
 python=tmp/'python';python.write_text('# inert interpreter fixture\n');python.chmod(0o700)
 config={'schema_version':6,'kind':m.KIND,'analysis':'Example','assets':assets,'source_manifest':pin(manifest),'runtime':{'python':pin(python),'files':[]},
         'architecture':{'isMac':True,'has_root':True,'has_fastjet':True,'root_compiler':'/usr/bin/clang++','toPATH1':[],'toPATH2':[],'toLDPATH1':[],'toLDPATH2':[]},'resources':{'max_seconds':60,'max_ram_mib':512,'max_output_bytes':4*1024**2}}
 cp=tmp/'config.json';atomic_json(cp,config);return {'backend':'routine-build','input':str(cp)},config,cp


def synthetic_writer(command,out,resources):
 """Fabricated outputs only, explicitly isolated from real upstream writers."""
 request=read_json(command[-1]);d=request;job=Path(d['job_root']);a=job/'Build/SampleAnalyzer/User/Analyzer';a.mkdir(parents=True)
 for name in m.REQUIRED:(a/name).write_text('// synthetic '+name+'\n')
 for key,suffix in [('source','.cpp'),('header','.h')]:
  (a/(d['analysis']+suffix)).write_bytes(Path(d['assets'][key]).read_bytes())
 (job/'Input').mkdir();(job/'Input'/(d['analysis']+'.info')).write_bytes(Path(d['assets']['info']).read_bytes())
 (a/'analysisList.h').write_text('manager.Add("'+d['analysis']+'",new '+d['analysis']+');\n')
 (job/'Build/Main').mkdir();(job/'Build/Main/main.cpp').write_text('manager.InitializeAnalyzer("'+d['analysis']+'","analysis.saf",parametersA1);\nmanager.InitializeJetClusterer("antikt",parametersC1);\nnew NewSmearer();\nnew NewTagger();\n')
 for name in ('Makefile','setup.sh','setup.csh'):(job/'Build'/name).write_text('# synthetic '+name+'\n')
 prefix=Path(d['source_root']);source=prefix/'madanalysis/core.py';python=Path(command[0])
 atomic_json(Path(d['observation']),{'kind':'ma5-sfs-writer-observation/v1','pid':42,'python':pin(python),'environment':d['environment'],'request_sha256':pin(Path(command[-1]))['sha256'],'card_program':d['card_program'],'imports':[{'module':'madanalysis.core','path':str(source),'sha256':pin(source)['sha256']}],'analysis':d['analysis'],'source_root':str(prefix),'job_root':str(job),'compiler_calls':0,'event_calls':0,'physics_validated':False})
 observation={'command':command,'returncode':0,'resource_violation':None,'synthetic':True,'new_events_generated':0}
 atomic_json(out/'native-execution.json',observation);(out/'native-stdout.log').write_text('synthetic writer fixture\n');(out/'native-stderr.log').write_text('')
 return observation


@pytest.fixture(autouse=True)
def no_ma5_or_native(monkeypatch):
 class Refuse:
  def find_spec(self,name,*args):
   if name=='madanalysis' or name.startswith('madanalysis.'):raise AssertionError('real MA5 import forbidden in source controls')
 guard=Refuse();sys.meta_path.insert(0,guard)
 import subprocess
 monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('process dispatch forbidden in pure control'))
 # The stdlib lazily probes uname/file for descriptive platform metadata.
 # Supply only that inert field while retaining the complete dispatch ban.
 import platform
 monkeypatch.setattr(platform,'platform',lambda: 'synthetic-platform-metadata')
 yield
 sys.meta_path.remove(guard)


def test_complete_source_inputs_sealing_plan_no_dispatch(tmp_path):
 task,d,cp=fixture(tmp_path/'inputs');plan=rb.build_plan(task,cp.parent,tmp_path/'prospective')
 assert rb.seal_configuration(task,cp.parent)==d
 assert set(rb.inputs(task,cp.parent))=={Path(r['path']) for r in plan['input_pins']}
 assert plan['schema_version']==6 and plan['command'][1:3]==['-I','-B']
 assert rb.execution_seconds(task,cp.parent)==60 and not (tmp_path/'prospective').exists()
 assert len(plan['card_program'])==4 and plan['physics_validated'] is False


def test_real_ordinary_unapproved_plan(tmp_path):
 task,d,cp=fixture(tmp_path/'inputs')
 policy={'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'synthetic-source-author','executor':'synthetic-executor','physics_critic':'synthetic-critic','skeptical_verifier':'synthetic-verifier','physics_decider':'synthetic-decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'}],'claim_scopes':{'engineering':{'checks':['integrity'],'actions':['delivery','reuse']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}
 spec={'schema_version':2,'mode':'analyze','task':task,'source':'Synthetic source-only materialization control','assumptions':['No actual MA5 writer or native scientific execution.'],'max_seconds':60,'max_attempts':1,'review_policy':policy,'approval_mode':'physicist'}
 sp=tmp_path/'science.json';atomic_json(sp,spec);plan=science.plan(tmp_path/'ordinary',sp)
 assert plan['schema_version']==2 and len(plan['stages'])==1 and len(plan['stage_binding']['input_snapshot'])>10
 assert not (tmp_path/'ordinary/outputs').exists()


def test_mocked_writer_complete_custody_and_common_worker_report(tmp_path,monkeypatch):
 from ravel.physics import reinterpret_db,science_worker
 task,d,cp=fixture(tmp_path/'inputs');spec={'schema_version':1,'mode':'analyze','task':task,'source':'Synthetic connected source control','assumptions':['Synthetic writer and inert authority only.'],'max_seconds':60,'approval_mode':'physicist'}
 monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer)
 monkeypatch.setattr(science_worker,'verify_worker',lambda root:{'base_dir':str(cp.parent),'output_directory':'outputs','stage_binding':{'input_snapshot':[]}})
 monkeypatch.setattr(science_worker,'execution_spec',lambda root:spec)
 rd=tmp_path/'ordinary';assert science_worker.main([str(rd)])==0
 out=rd/'outputs';r=read_json(out/'result.json');plan=read_json(out/'build-plan.json')
 assert rb.verify_receipt(r,plan,cp.parent,out)==r
 assert r['compiled'] is False and r['physics_validated'] is False and r['original_task_complete'] is False
 figures=read_json(out/'figures.json');assert figures['tables'] and not figures['figures']
 for f in figures['tables'][0]['files']:assert (out/f).is_file() and f in (out/'RESULT.md').read_text()


def test_relative_interpreter_pin_preserves_actual_canonical_identity(tmp_path,monkeypatch):
 from ravel.physics import reinterpret_db
 task,d,cp=fixture(tmp_path/'inputs');d['runtime']['python']['path']='python';atomic_json(cp,d)
 out=tmp_path/'out';out.mkdir();monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer)
 receipt=rb.run(task,cp.parent,out);plan=read_json(out/'build-plan.json')
 assert plan['command'][0]==str(cp.parent/'python')
 assert rb.verify_receipt(receipt,plan,cp.parent,out)==receipt


@pytest.mark.parametrize('member',m.REQUIRED)
def test_missing_generated_source_refuses_complete_delivery(tmp_path,monkeypatch,member):
 from ravel.physics import reinterpret_db
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir()
 def writer(*a):
  x=synthetic_writer(*a);request=read_json(a[0][-1]);(Path(request['job_root'])/'Build/SampleAnalyzer/User/Analyzer'/member).unlink();return x
 monkeypatch.setattr(reinterpret_db,'execute_native',writer)
 with pytest.raises(ValueError,match='missing generated'):rb.run(task,cp.parent,out)
 assert not (out/'build-receipt.json').exists()


@pytest.mark.parametrize('defect',['header','source','registration','output_name','writer','import','compiler','staged_source'])
def test_wrong_materialized_source_or_observation_refuses(tmp_path,monkeypatch,defect):
 from ravel.physics import reinterpret_db
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir()
 def writer(*a):
  x=synthetic_writer(*a);request=read_json(a[0][-1]);job=Path(request['job_root']);p=Path(request['observation']);obs=read_json(p);an=job/'Build/SampleAnalyzer/User/Analyzer'
  if defect in ('header','source'):(an/(d['analysis']+('.h' if defect=='header' else '.cpp'))).write_text('wrong')
  elif defect=='registration':(an/'analysisList.h').write_text('manager.Add("Other",new Other);\n')
  elif defect=='output_name':p=job/'Build/Main/main.cpp';p.write_text(p.read_text().replace('analysis.saf','user.saf'))
  elif defect=='writer':obs['request_sha256']='0'*64
  elif defect=='import':obs['imports'][0]['path']=str(cp)
  elif defect=='compiler':obs['compiler_calls']=1
  else:(Path(request['source_root'])/'madanalysis/core.py').write_text('mutated')
  if defect in ('writer','import','compiler'):atomic_json(p,obs)
  return x
 monkeypatch.setattr(reinterpret_db,'execute_native',writer)
 with pytest.raises(ValueError):rb.run(task,cp.parent,out)
 assert not (out/'build-receipt.json').exists()


@pytest.mark.parametrize('member',m.REQUIRED)
def test_empty_generated_source_cannot_complete_materialization(tmp_path,monkeypatch,member):
 from ravel.physics import reinterpret_db
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir()
 def writer(*a):
  r=synthetic_writer(*a);request=read_json(a[0][-1]);(Path(request['job_root'])/'Build/SampleAnalyzer/User/Analyzer'/member).write_bytes(b'');return r
 monkeypatch.setattr(reinterpret_db,'execute_native',writer)
 with pytest.raises(ValueError,match='empty generated'):rb.run(task,cp.parent,out)
 assert not (out/'build-receipt.json').exists()


@pytest.mark.parametrize('command',['submit X','install fastjet','import events.hepmc','set main.recast = on','set main.outputfile = out.lhe','set main.fastsim.package = fastjet; install root'])
def test_only_source_sfs_card_operations_admitted(command):
 with pytest.raises(ValueError):m.card_program(('set main.fastsim.package = fastjet\ndefine smearer j with PT 1\ndefine reco_efficiency e 1\ndefine tagger b as b 1\n'+command).encode())


def test_manifest_omitted_extra_source_duplicate_and_byte_drift_refuse(tmp_path):
 task,d,cp=fixture(tmp_path/'inputs');root=Path(read_json(d['source_manifest']['path'])['root']);(root/'madanalysis/added.py').write_text('# undeclared')
 with pytest.raises(ValueError,match='projection'):rb.inputs(task,cp.parent)
 (root/'madanalysis/added.py').unlink();manifest=read_json(d['source_manifest']['path']);manifest['files'].append(manifest['files'][0]);atomic_json(Path(d['source_manifest']['path']),manifest);d['source_manifest']=pin(Path(d['source_manifest']['path']));atomic_json(cp,d)
 with pytest.raises(ValueError,match='unique'):rb.inputs(task,cp.parent)


@pytest.mark.parametrize('defect',['source_copy','helper','request','job','execution'])
def test_retained_receipt_revalidation_binds_whole_output_graph(tmp_path,monkeypatch,defect):
 from ravel.physics import reinterpret_db
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir();monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer)
 r=rb.run(task,cp.parent,out);p=read_json(out/'build-plan.json')
 target={'source_copy':out/'work/source/madanalysis/core.py','helper':out/'writer.py','request':out/'writer-request.json','job':out/'job/Build/SampleAnalyzer/User/Analyzer/sigmas.h','execution':out/'writer-execution/native-stdout.log'}[defect]
 target.write_bytes(target.read_bytes()+b'\n')
 with pytest.raises(ValueError):rb.verify_receipt(r,p,cp.parent,out)


def test_committed_writer_document_cannot_mutate_returned_result(tmp_path,monkeypatch):
 from ravel.physics import reinterpret_db
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir();monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer);real=m.atomic_json
 def writer(path,value):
  real(path,value)
  if path.name=='build-receipt.json':value['physics_validated']=True
 monkeypatch.setattr(m,'atomic_json',writer);r=rb.run(task,cp.parent,out)
 assert r['physics_validated'] is False and r==read_json(out/'build-receipt.json')


@pytest.mark.parametrize('field',['python','environment','event_calls','compiler_calls','imports','pid'])
def test_resealed_observation_cannot_change_materialization_semantics(tmp_path,monkeypatch,field):
 from ravel.physics import reinterpret_db
 task,d,cp=fixture(tmp_path/'inputs');out=tmp_path/'out';out.mkdir();monkeypatch.setattr(reinterpret_db,'execute_native',synthetic_writer)
 receipt=rb.run(task,cp.parent,out);plan=read_json(out/'build-plan.json');p=out/'writer-observation.json';obs=read_json(p)
 changes={'python':{'path':str(cp),'sha256':pin(cp)['sha256']},'environment':{},'event_calls':1,'compiler_calls':False,'imports':[],'pid':-1}
 obs[field]=changes[field];atomic_json(p,obs);receipt['writer_observation']={**pin(p),'size':p.stat().st_size};atomic_json(out/'build-receipt.json',receipt)
 with pytest.raises(ValueError):rb.verify_receipt(receipt,plan,cp.parent,out)


def test_helper_program_uses_upstream_writers_without_native_startup():
 tree=ast.parse(m.HELPER);calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
 assert {'Main','Interpreter','JobWriter','jobber.WriteSelectionHeader','jobber.WriteSelectionSource','jobber.CreateBldDir','jobber.WriteMakefiles','runpy.run_path'}<=calls
 assert not {'main.BuildLibrary','main.CheckConfig','main.CheckConfig2','os.system','subprocess.run','subprocess.Popen','jobber.CompileJob'}&calls
 assert "outputName='analysis.saf'" in m.HELPER and 'runpy.run_path' in m.HELPER


def test_source_control_genuine_card_and_writer_api_are_static_only():
 # This test reads the retained source, never imports MA5 or pretends to have
 # generated its outputs. It is intentionally skipped in distribution copies.
 B=Path(__file__).resolve().parents[3]
 p=B/'source-preparation/materialization-config-v1.json'
 if not p.is_file():pytest.skip('retained local source preparation not present in distribution')
 d=read_json(p);rows=m.card_program(Path(d['assets']['sfs_card']['path']).read_bytes())
 assert len(rows)==60
 plan=rb.build_plan({'backend':'routine-build','input':str(p)},p.parent,B/'uncreated-control-output')
 assert len(plan['source_files'])==843 and sum(r['input']['size'] for r in plan['source_files'])==11063565
 assert all(not n.startswith('madanalysis') for n in sys.modules)
