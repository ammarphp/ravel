"""Own non-GPL by-value-module controls; no SDK or upstream checkout needed."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import pytest
from ravel.workflow import agentrivet_pins as pins_module, agentrivet_runtime as runtime
from test_agentrivet_provider import provider
from test_agentrivet_candidate import pin


def fixture(base, monkeypatch, *, probe_compiler=False):
    root = base/'own-modules'; root.mkdir()
    prefix = 'own_agentrivet_interface'
    package = ModuleType(prefix); package.__path__ = [str(root)]
    monkeypatch.setitem(sys.modules, prefix, package)
    core = '''def make_llm(provider, model):
    raise RuntimeError("original provider must not be invoked")
class Agent:
    def __init__(self, llm, system_prompt=None, output_model=None):
        llm.valid()
        self.llm=llm; self.system_prompt=system_prompt; self.output_model=output_model
class ReviewLoop:
    def __init__(self, analyst, coder, code_reviewer, physics_reviewer, max_iterations):
        self.agents=[analyst,coder,code_reviewer,physics_reviewer]
        self.max_iterations=max_iterations
'''
    if probe_compiler:   # stands in for an upstream compiler probe at construction
        core += "        __import__('subprocess').run(['true'], check=False)\n"
    (root/'core.py').write_text(core)
    def load(name):
        path=root/(name+'.py'); spec=importlib.util.spec_from_file_location(prefix+'.'+name,path)
        m=importlib.util.module_from_spec(spec);monkeypatch.setitem(sys.modules,spec.name,m)
        exec(compile(path.read_bytes(),str(path),'exec',dont_inherit=True),m.__dict__)
        return m
    core_module = load('core'); roles={}; pins={'core':pin(root/'core.py')}
    for role,(filename,factory,prompt,model) in runtime.ROLES.items():
        model_code = '' if model is None else f'''class {model}:
    @classmethod
    def model_json_schema(cls): return {{"type":"object","properties":{{}},"additionalProperties":False}}
    @classmethod
    def model_validate(cls,value): return cls()
'''
        (root/filename).write_text(f'''from .core import Agent,make_llm
{prompt} = "Own synthetic {role} instruction"
{model_code}
def {factory}(provider,model):
    return Agent(make_llm(provider,model),{prompt},{model or 'None'})
''')
        roles[role]=load(filename[:-3]);pins[role]=pin(root/filename)
    llm=provider(base,max_calls=10,source_inputs=list(pins.values()))
    # Own modules are admitted as one extra census; real upstream pins stay fixed.
    monkeypatch.setitem(pins_module.ALLOWED,'own-portable-fixture',{'label':'own test fixture',
        'files':{pins_module.ROLE_FILES[key]:pin['sha256'] for key,pin in pins.items()}})
    return core_module,roles,pins,llm


def test_all_four_by_value_modules_share_graph_and_restore(tmp_path,monkeypatch):
    core,roles,pins,llm=fixture(tmp_path,monkeypatch)
    old={r:m.make_llm for r,m in roles.items()}
    loop,receipt=runtime.instantiate(core,roles,llm,source_pins=pins,provider='fixture',model='fixture-control',max_iterations=3)
    assert all(a.llm is llm for a in loop.agents)
    assert all(m.make_llm is old[r] for r,m in roles.items())
    assert receipt['required_call_ceiling']==10 and receipt['provider_calls_made']==0
    assert not llm.root.exists()


def test_global_binding_lock_refuses_overlap(tmp_path,monkeypatch):
    core,roles,pins,llm=fixture(tmp_path,monkeypatch)
    runtime._LOCK.acquire()
    try:
        with pytest.raises(ValueError,match='already active'):
            runtime.instantiate(core,roles,llm,source_pins=pins,provider='fixture',model='fixture-control',max_iterations=1)
    finally: runtime._LOCK.release()
    assert all(m.make_llm is core.make_llm for m in roles.values())


def test_partial_core_patch_does_not_fix_imported_role_factories(tmp_path,monkeypatch):
    core,roles,pins,llm=fixture(tmp_path,monkeypatch)
    original=core.make_llm;core.make_llm=lambda *a:llm
    assert all(m.make_llm is original for m in roles.values())
    with pytest.raises(ValueError,match='core factory'):
        runtime.instantiate(core,roles,llm,source_pins=pins,provider='fixture',model='fixture-control',max_iterations=1)


def test_truthful_file_repin_cannot_certify_different_loaded_factory(tmp_path,monkeypatch):
    core,roles,pins,llm=fixture(tmp_path,monkeypatch)
    path=Path(pins['coder']['path']);path.write_text(path.read_text().replace('return Agent(', 'return NotAgent('))
    pins['coder']=pin(path)
    with pytest.raises(ValueError,match='by-value'):
        runtime.instantiate(core,roles,llm,source_pins=pins,provider='fixture',model='fixture-control',max_iterations=1)


def test_original_factory_names_restored_on_constructor_failure(tmp_path,monkeypatch):
    core,roles,pins,llm=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(llm,'valid',lambda: (_ for _ in ()).throw(RuntimeError('own failure')))
    with pytest.raises(RuntimeError):
        runtime.instantiate(core,roles,llm,source_pins=pins,provider='fixture',model='fixture-control',max_iterations=1)
    assert all(m.make_llm is core.make_llm for m in roles.values()) and not runtime._LOCK.locked()


def test_unlisted_upstream_census_is_refused_after_binding_checks(tmp_path,monkeypatch):
    core,roles,pins,llm=fixture(tmp_path,monkeypatch)
    monkeypatch.delitem(pins_module.ALLOWED,'own-portable-fixture')
    with pytest.raises(ValueError,match='allowed AgentRivet upstream commits'):
        runtime.inspect_binding(core,roles,source_pins=pins)


def test_process_start_during_original_role_construction_raises(tmp_path,monkeypatch):
    core,roles,pins,llm=fixture(tmp_path,monkeypatch,probe_compiler=True)
    with pytest.raises(pins_module.UpstreamExecutionRefused,match='ReviewLoop construction'):
        runtime.instantiate(core,roles,llm,source_pins=pins,provider='fixture',model='fixture-control',max_iterations=1)
    assert all(m.make_llm is core.make_llm for m in roles.values()) and not runtime._LOCK.locked()


def test_process_start_inside_a_role_factory_raises_and_restores(tmp_path,monkeypatch):
    core,roles,pins,llm=fixture(tmp_path,monkeypatch)
    module=roles['coder'];factory=module.CoderAgent
    def spawning(provider,model):
        import os
        os.system('true')
        return factory(provider,model)
    monkeypatch.setattr(module,'CoderAgent',spawning)
    with pytest.raises((pins_module.UpstreamExecutionRefused,ValueError)):
        runtime.instantiate(core,roles,llm,source_pins=pins,provider='fixture',model='fixture-control',max_iterations=1)
    assert all(m.make_llm is core.make_llm for m in roles.values()) and not runtime._LOCK.locked()
