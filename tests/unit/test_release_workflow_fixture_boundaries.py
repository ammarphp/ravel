"""Strict guard and source input boundaries remain unchanged by fixture repairs."""
from copy import deepcopy
import hashlib,json,sys
from pathlib import Path
import pytest
from ravel.paths import module_command
from ravel.workflow import execution,prepared_runtime as pr,science
from ravel.physics import analysis_response_features as ar
from instrumentation_fixture import assets,contracts,sha

def interpreter_binding(spelling):
 binary=str(Path(sys.executable).resolve(strict=True))
 return {'command':[spelling], 'input_snapshot':{binary:{'kind':'file','files':[{'name':'.','sha256':execution.file_hash(binary)}]}}}

@pytest.mark.parametrize('other',['resolved_binary','sibling_venv'])
def test_same_binary_different_python_spelling_is_refused(tmp_path,monkeypatch,other):
 original=sys.executable;binary=Path(original).resolve(strict=True)
 logical=tmp_path/'venv-a/bin/python';logical.parent.mkdir(parents=True);logical.symlink_to(binary)
 sibling=tmp_path/'venv-b/bin/python';sibling.parent.mkdir(parents=True);sibling.symlink_to(binary)
 monkeypatch.setattr(sys,'executable',str(logical))
 planned=str(binary) if other=='resolved_binary' else str(sibling)
 assert Path(planned).resolve()==logical.resolve()
 before=dict(__import__('os').environ)
 with pytest.raises(ValueError,match='exact planned Python interpreter spelling'):
  pr._interpreter(interpreter_binding(planned))
 assert dict(__import__('os').environ)==before
 assert module_command('ravel.physics.science_worker')[0]==str(logical)

def test_live_logical_python_capture_and_wrong_binary_snapshot():
 b=interpreter_binding(sys.executable)
 actual=pr._interpreter(b)
 assert actual['spelling']==sys.executable and actual['resolved']==str(Path(sys.executable).resolve())
 b['input_snapshot'][actual['resolved']]['files'][0]['sha256']='0'*64
 with pytest.raises(ValueError,match='missing or changed'):pr._interpreter(b)

@pytest.mark.parametrize('version',[None,True,0,3])
def test_missing_or_invalid_plan_version_still_refuses_without_authority(tmp_path,version):
 inputs=tmp_path/'inputs';inputs.mkdir();proposal={'base_dir':str(tmp_path)}
 if version is not None:proposal['schema_version']=version
 (tmp_path/science.PLAN).write_text(json.dumps(proposal))
 with pytest.raises(ValueError,match='invalid science plan version'):science.review_enabled(tmp_path)
 assert not (tmp_path/science.APPROVAL).exists() and not (tmp_path/'execution_attempt.json').exists()

@pytest.mark.parametrize('change',['missing','altered'])
def test_exact_restored_model_is_required_before_any_source_preparation(tmp_path,monkeypatch,change):
 base=assets(tmp_path/'supplied')
 c=next(iter(contracts(base).values()));model=Path(c['model']['path'])
 if change=='missing':model.unlink()
 else:model.write_bytes(model.read_bytes()+b'changed exact original model')
 out=tmp_path/'prepared';task={'schema_version':1,'operation':'prepare-source','input':str(base/'prepare-input.json'),'input_sha256':sha(base/'prepare-input.json')}
 with pytest.raises(ValueError):ar.inputs(task,base)
 assert not out.exists()


def test_all_supplied_model_assets_match_explicit_census(tmp_path):
 base=assets(tmp_path/'supplied')
 for contract in contracts(base).values():
  for field in ('source','model'):
   pin=contract[field];assert sha(Path(pin['path']))==pin['sha256']


from test_failed_context_scale import unreviewed_case
@pytest.mark.parametrize('ordering',['reverse','last'])
def test_failed_context_summary_is_semantic_not_first_artifact(unreviewed_case,tmp_path,monkeypatch,ordering):
    from ravel.workflow import agent_host as host
    from test_failed_context_scale import test_large_census_is_retained_with_bounded_unknown_failure_view as original
    implementation=host.AgentHost._packet
    def reorder(self,node,*a,**kw):
        packet=implementation(self,node,*a,**kw)
        if ordering=='reverse':packet['artifacts'].reverse()
        else:packet['artifacts'].sort(key=lambda entry:entry['id']=='premise')
        assert any(a['id']=='premise' for a in packet['artifacts'])
        if ordering=='last':assert packet['artifacts'][0]['id']!='premise'
        return packet
    monkeypatch.setattr(host.AgentHost,'_packet',reorder)
    original(unreviewed_case,tmp_path,monkeypatch)


@pytest.mark.parametrize('headline',['source','approval_mode','review_policy','status','verdict'])
def test_recipe_projection_preserves_supplied_assumptions_but_not_producer_decisions(headline):
    from ravel.workflow import review_context
    assumptions=['No detector or independent physics validation is inferred']
    specification={'schema_version':2,'mode':'domain','task':{'domain':'llp'},
                   'assumptions':assumptions,headline:'ACCEPT: producer-only headline',
                   'max_seconds':45,'max_attempts':3}
    original={'specification':specification,'input_snapshot':{'retained-input':{'sha256':'a'*64}}}
    projected,_=review_context._project_science_artifact(original,'outputs/attempt-1/recipe.json')
    assert projected['specification']=={key:specification[key] for key in ('schema_version','mode','task','assumptions')}
    assert projected['specification']['assumptions']==assumptions
    assert projected['input_snapshot']==original['input_snapshot']
    assert 'ACCEPT' not in json.dumps(projected)
    assert specification[headline]=='ACCEPT: producer-only headline'


@pytest.mark.parametrize('outer_seconds',[0,-1])
def test_public_event_refuses_nonpositive_outer_ceiling(tmp_path,monkeypatch,outer_seconds):
    from test_simpleanalysis_events import public_input_fixture
    task,base,_,job,*_=public_input_fixture(tmp_path,monkeypatch)
    original=deepcopy(job)
    assert job['resources']['max_seconds']==120
    with pytest.raises(ValueError,match='adapter execution budget exceeds the scientific-study hard ceiling'):
        science.task_inputs({'mode':'analyze','task':task,'max_seconds':outer_seconds},base)
    assert job==original and not (base/'unexecuted-event-output').exists()
