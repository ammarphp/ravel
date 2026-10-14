"""Specific compiler-mode controls: inert backends, no Make/compiler/native call."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
import test_finite_integrals as original
from ravel.physics import finite_integrals as adapter, finite_integrals_core as core

MODE='clang-template-keyword-without-argument-list/v1'
OPTION='-Wno-missing-template-arg-list-after-template-kw'


def compatibility(c, evidence=None):
    c['runtime']['cxx']={'path':'/synthetic/cxx','sha256':'a'*64}
    c['build_compatibility']={'mode':MODE,'compiler':deepcopy(c['runtime']['cxx']),
        'reason':'Explicit prospective compatibility for diagnosed upstream template syntax.',
        'evidence':evidence or [{'path':'diagnostic.txt','sha256':'b'*64}]}
    return c


def test_omission_preserves_existing_configuration_math_and_default_options():
    c=original.cfg();before=deepcopy(c)
    assert core.config(c)==before and core.compiler_options(c)==[]
    upgraded=compatibility(deepcopy(c))
    assert core.compiler_options(core.config(upgraded))==[OPTION]
    assert core.generator_spec(upgraded)==core.generator_spec(before)
    assert [core.numerical_arguments(upgraded,p) for p in upgraded['points']]==[core.numerical_arguments(before,p) for p in before['points']]


@pytest.mark.parametrize('fault',[
    'null','unknown','arbitrary_flags','missing_field','extra_field','empty_reason',
    'relative_compiler','parent_compiler','noncanonical_compiler','different_compiler',
    'different_hash','uppercase_hash','empty_evidence','excess_evidence','bad_evidence_hash',
    'evidence_extra','evidence_missing','evidence_not_list','compiler_extra','compiler_not_object'])
def test_closed_mode_and_exact_compiler_refuse(fault):
    c=compatibility(original.cfg());m=c['build_compatibility']
    if fault=='null':c['build_compatibility']=None
    elif fault=='unknown':m['mode']='gnu-permissive'
    elif fault=='arbitrary_flags':m['flags']=['-w','-fpermissive']
    elif fault=='missing_field':m.pop('reason')
    elif fault=='extra_field':m['native_success']=True
    elif fault=='empty_reason':m['reason']='  '
    elif fault=='relative_compiler':m['compiler']['path']='synthetic/cxx';c['runtime']['cxx']=deepcopy(m['compiler'])
    elif fault=='parent_compiler':m['compiler']['path']='/synthetic/../cxx';c['runtime']['cxx']=deepcopy(m['compiler'])
    elif fault=='noncanonical_compiler':m['compiler']['path']='/synthetic//cxx';c['runtime']['cxx']=deepcopy(m['compiler'])
    elif fault=='different_compiler':m['compiler']['path']='/another/cxx'
    elif fault=='different_hash':m['compiler']['sha256']='c'*64
    elif fault=='uppercase_hash':m['compiler']['sha256']='A'*64;c['runtime']['cxx']=deepcopy(m['compiler'])
    elif fault=='empty_evidence':m['evidence']=[]
    elif fault=='excess_evidence':m['evidence']*=9
    elif fault=='bad_evidence_hash':m['evidence'][0]['sha256']='not-a-digest'
    elif fault=='evidence_extra':m['evidence'][0]['size']=1
    elif fault=='evidence_missing':m['evidence'][0].pop('path')
    elif fault=='evidence_not_list':m['evidence']={}
    elif fault=='compiler_extra':m['compiler']['flags']=['-w']
    else:m['compiler']=[]
    with pytest.raises(ValueError):core.config(c)


@pytest.mark.parametrize('ending_mutation',[False,True])
def test_actual_adapter_consumes_compatibility_evidence_and_retains_ending_refusal(tmp_path,monkeypatch,ending_mutation):
    task,c=original.fixture(tmp_path,monkeypatch)
    diagnostic=tmp_path/'diagnostic.txt';diagnostic.write_text('Synthetic located upstream compiler error.\n')
    compatibility(c,[{k:v for k,v in original.pin(diagnostic).items() if k!='size'}])
    original.save(Path(task['config']),c)
    assert diagnostic.resolve() in adapter.inputs(task,tmp_path)
    assert diagnostic.resolve() in adapter.context_inputs(task,tmp_path)
    context=adapter.context(task,tmp_path)
    assert context['configuration']['build_compatibility']==c['build_compatibility']
    assert any(p['path']==str(diagnostic) for p in context['dependency_pins'])
    assert context['execution_authorized'] is False
    monkeypatch.setattr(adapter,'approved',lambda *_:{'max_seconds':30})
    from ravel.physics import reinterpret_db
    def inert(command,out,config):
        value=original.fake_execution(command,out,config)
        if ending_mutation:diagnostic.write_text('Changed after supplied return.\n')
        return value
    monkeypatch.setattr(reinterpret_db,'execute_native',inert)
    result=adapter.run(task,tmp_path,tmp_path/'output')
    assert result['status']==('failed' if ending_mutation else 'passed')
    if ending_mutation:assert any('ending input custody' in e for e in result['errors'])


def test_changed_compatibility_evidence_refuses_context_before_output(tmp_path,monkeypatch):
    task,c=original.fixture(tmp_path,monkeypatch)
    diagnostic=tmp_path/'diagnostic.txt';diagnostic.write_text('Original located syntax.\n')
    compatibility(c,[{k:v for k,v in original.pin(diagnostic).items() if k!='size'}])
    original.save(Path(task['config']),c);diagnostic.write_text('Substituted evidence.\n')
    with pytest.raises(ValueError,match='source pin changed'):adapter.context(task,tmp_path)


@pytest.mark.parametrize('mode,fail',[(False,'none'),(True,'none'),(True,'build'),(True,'second_return')])
def test_real_worker_body_uses_only_admitted_make_option_and_preserves_failures(tmp_path,monkeypatch,mode,fail):
    prior_cfg=original.cfg;prior_save=original.save
    if mode:
        monkeypatch.setattr(original,'cfg',lambda *a,**kw:compatibility(prior_cfg(*a,**kw)))
        def save(path,value):
            if 'runtime_assets' in value:value['runtime_assets']['/synthetic/cxx']='a'*64
            return prior_save(path,value)
        monkeypatch.setattr(original,'save',save)
    monkeypatch.setenv('CXXFLAGS','-w -fpermissive -O0')
    original.test_actual_worker_source_against_fake_optional_api(tmp_path,monkeypatch,fail)
    state=json.loads((tmp_path/'native/native-integrals.json').read_text())
    command=next(p['command'] for p in state['phases'] if p['name']=='build')
    old=['/synthetic/make','-j1','-C',str(tmp_path/'native/finite_integral'),'pylink',
        'CXX=/synthetic/cxx','SECDEC_CONTRIB='+str(tmp_path),'PYTHON='+__import__('sys').executable,'FORMTHREADS=1']
    assert command==old+(['CXXFLAGS='+OPTION] if mode else [])
    assert 'CXXFLAGS' in state['cleared_build_environment_keys']
    assert ('build_compatibility' in state)==mode
    if mode:assert state['build_compatibility']['compiler']=={'path':'/synthetic/cxx','sha256':'a'*64}
    if fail=='build':assert state['status']=='failed' and state['calls_started']==state['calls_returned']==0
    elif fail=='second_return':assert state['status']=='failed' and state['calls_returned']==2 and (tmp_path/'native/p1.native-return.json').is_file()
    else:assert state['status']=='returned' and state['calls_returned']==2


@pytest.mark.parametrize('mismatch',['path','hash','missing'])
def test_compiler_census_mismatch_refuses_before_optional_import_or_generation(tmp_path,monkeypatch,mismatch):
    prior_cfg=original.cfg;prior_save=original.save
    monkeypatch.setattr(original,'cfg',lambda *a,**kw:compatibility(prior_cfg(*a,**kw)))
    def save(path,value):
        if 'runtime_assets' in value:
            if mismatch=='path':value['cxx']='/another/cxx';value['runtime_assets']['/another/cxx']='a'*64
            elif mismatch=='hash':value['runtime_assets']['/synthetic/cxx']='c'*64
        return prior_save(path,value)
    monkeypatch.setattr(original,'save',save)
    original.test_actual_worker_source_against_fake_optional_api(tmp_path,monkeypatch,'unbound_import')
    state=json.loads((tmp_path/'native/native-integrals.json').read_text())
    assert state['status']=='failed' and state['calls_started']==state['calls_returned']==0
    assert state['phases']==[] and 'imports_before' not in state
    assert 'compatibility compiler differs from selected process input census' in state['error']
