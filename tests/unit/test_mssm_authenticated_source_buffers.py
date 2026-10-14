import json
from pathlib import Path
import pytest
from test_mssm_observable_map import fixture,emit
from ravel.physics import mssm_observable_map as m, generated_spectrum
from ravel.workflow import task_completion as tc, science, execution

def test_api_contract_copy_is_its_authenticated_original_buffer(tmp_path,monkeypatch):
 task,_=fixture(tmp_path,grid=False);original=m.slha.raw_file
 declared=json.loads(m.API.read_bytes());alternate=json.loads(m.API.read_bytes())
 alternate['equations']['lifetime']='THIS IS NOT THE DECLARED SOURCE EQUATION'
 def replaced(path,expected=None):
  raw=original(path,expected)
  if Path(path)==m.API and expected is None:return json.dumps(alternate).encode()
  return raw
 monkeypatch.setattr(m.slha,'raw_file',replaced)
 result=m.compile_map(task,tmp_path)
 assert result['source_equations']==declared,'copied API contract does not equal authenticated source bytes'

def test_accepted_result_uses_its_captured_original_buffer(tmp_path,monkeypatch):
 task,d=fixture(tmp_path/'inputs',grid=False);p=d['points'][0]
 rd=tmp_path/'run';out=rd/'outputs/attempt-1';out.mkdir(parents=True)
 p['spectrum']=emit(out/'CMSSM.slha',Path(p['spectrum']['path']).read_bytes())
 p['origin']={'kind':'accepted_cmssm_spectrum','run':str(rd)}
 good={'status':'passed','generated_slha':{'path':p['spectrum']['path'],'sha256':p['spectrum']['sha256']},'solver_input_sha256':p['input_card']['sha256']}
 actual={**good,'status':'failed'};result=out/'generated-spectrum.json';emit(result,actual)
 def accepted(run,scope,session):
  assert run==str(rd) and scope==m.slha.SCOPE
  return rd,{'explicit_inert_review_standin':True}
 monkeypatch.setattr(tc,'_accepted_review',accepted)
 monkeypatch.setattr(science,'execution_spec',lambda root:{'mode':'generated-spectrum','task':{'config':'inert'}})
 monkeypatch.setattr(generated_spectrum,'_load',lambda task,root:(tmp_path/'inert-config.json',{'schema_version':1}))
 monkeypatch.setattr(execution,'load_execution',lambda root:{'stages':{'science':{'outputs':[str(out)]}}})
 original=m.slha.raw_file
 def replaced(path,expected=None):
  raw=original(path,expected)
  if Path(path)==result and expected is None:return json.dumps(good).encode()
  return raw
 monkeypatch.setattr(m.slha,'raw_file',replaced)
 with pytest.raises(ValueError,match='exact accepted return|changed|SHA'):m._origin(p,tmp_path/'inputs')
