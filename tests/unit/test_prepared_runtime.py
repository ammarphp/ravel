"""Source/mock controls only: no worker, study assent, native or model process."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from ravel import cli
from ravel.workflow import execution, prepared_runtime as pr, science, scoped
from ravel.workflow.state_io import atomic_json, read_json


def binding(tmp_path):
    payload = tmp_path / 'input.txt'; payload.write_text('source-bound synthetic input')
    return execution.plan_stage(tmp_path, 'science', [sys.executable, '-c', 'pass'],
                                [str(payload)], ['outputs'], [], tmp_path)


@pytest.fixture
def prepared(tmp_path):
    b = binding(tmp_path)
    proposal = {'stage_binding': b, 'prepared_runtime': pr.capture(b)}
    atomic_json(tmp_path / 'inputs/science-plan.json', proposal)
    return tmp_path, proposal


def test_retains_exact_selected_values_removals_and_binding(prepared):
    rd, p = prepared
    c = pr.for_plan(rd)
    assert c['environment'] == execution.runtime_environment()
    assert set(c['environment']) == set(execution.RUNTIME_ENVIRONMENT_KEYS)
    assert c['interpreter']['spelling'] == sys.executable
    assert c['runtime'] == p['stage_binding']['runtime']
    assert c['source_snapshot_sha256'] == execution.digest(p['stage_binding']['input_snapshot'])


def test_restore_only_selected_values_after_success_and_failure(prepared, monkeypatch):
    rd, p = prepared
    saved = p['prepared_runtime']['environment']
    monkeypatch.setenv('PATH', '/parent/different')
    monkeypatch.setenv('CONDA_PREFIX', 'wrong-parent-prefix')
    monkeypatch.setenv('UNSELECTED_SENTINEL', 'parent')
    before = execution.runtime_environment()
    for fail in (False, True):
        try:
            with pr.replay(rd):
                assert execution.runtime_environment() == saved
                assert os.environ['UNSELECTED_SENTINEL'] == 'parent'
                os.environ['UNSELECTED_SENTINEL'] = 'kept-call-change'
                if fail:
                    raise RuntimeError('mock operation failure')
        except RuntimeError:
            pass
        assert execution.runtime_environment() == before
        assert os.environ['UNSELECTED_SENTINEL'] == 'kept-call-change'
        os.environ['UNSELECTED_SENTINEL'] = 'parent'


def test_legacy_capsule_never_changes_plan_or_invents_values(prepared, monkeypatch, tmp_path):
    rd, p = prepared
    original = deepcopy(p);del p['prepared_runtime']
    atomic_json(rd / 'inputs/science-plan.json', p)
    prior = (rd / 'inputs/science-plan.json').read_bytes()
    monkeypatch.setenv('PATH', '/wrong')
    with pytest.raises(ValueError, match='no retained values'):
        with pr.replay(rd): pass
    with pytest.raises(ValueError, match='planned runtime environment hash'):
        pr.for_plan(rd)
    c = pr.for_plan(rd, environment=original['prepared_runtime']['environment'])
    path = tmp_path / 'explicit.json';atomic_json(path, c)
    with pr.replay(rd, capsule_path=path):
        assert execution.runtime_environment() == c['environment']
    assert (rd / 'inputs/science-plan.json').read_bytes() == prior
    assert not (rd / 'inputs/science-approval.json').exists()


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'numeric', 'bool', 'nul', 'wrong_hash',
                                     'fingerprint', 'source', 'interpreter', 'runtime', 'schema_bool'])
def test_capsule_adverse_binding_refuses_before_environment_mutation(prepared, mutation):
    rd, p = prepared;c = deepcopy(p['prepared_runtime'])
    if mutation == 'missing': del c['environment']['PATH']
    if mutation == 'extra': c['environment']['OTHER'] = 'injected'
    if mutation == 'numeric': c['environment']['OMP_NUM_THREADS'] = 1
    if mutation == 'bool': c['environment']['MKL_NUM_THREADS'] = True
    if mutation == 'nul': c['environment']['PATH'] = 'bad\x00path'
    if mutation == 'wrong_hash': c['environment']['PATH'] = 'different'
    if mutation == 'fingerprint': c['stage_fingerprint'] = '0' * 64
    if mutation == 'source': c['source_snapshot_sha256'] = '0' * 64
    if mutation == 'interpreter': c['interpreter']['spelling'] += '-other'
    if mutation == 'runtime': c['runtime']['packages_sha256'] = '0' * 64
    if mutation == 'schema_bool': c['schema_version'] = True
    atomic_json(rd / 'inputs/science-plan.json', {**p, 'prepared_runtime': c})
    prior = dict(os.environ)
    with pytest.raises(ValueError):
        with pr.replay(rd): pass
    assert dict(os.environ) == prior


def test_new_plan_rejects_external_substitution_even_if_environment_equal(prepared, tmp_path):
    rd, p = prepared;c=deepcopy(p['prepared_runtime']);c['kind']='other'
    path=tmp_path/'other.json';atomic_json(path,c)
    with pytest.raises(ValueError, match='cannot replace'):
        with pr.replay(rd,capsule_path=path):pass


def test_alias_interpreter_and_changed_binary_are_not_silently_repaired(prepared, monkeypatch):
    rd,p=prepared
    monkeypatch.setattr(sys,'executable',sys.executable+'-alias')
    with pytest.raises(ValueError,match='exact planned Python interpreter spelling'):
        pr.for_plan(rd)


def test_source_runtime_guards_are_preserved_after_environment_restoration(prepared, monkeypatch):
    rd,p=prepared
    changed=deepcopy(p['stage_binding']);changed['input_snapshot'][str(rd/'input.txt')]['files'][0]['sha256']='f'*64
    with pytest.raises(ValueError,match='fingerprint'):
        pr.validate(p['prepared_runtime'],changed)
    monkeypatch.setenv('PATH','/other-parent')
    with pr.replay(rd):
        current=execution.runtime_context()
        assert current == p['stage_binding']['runtime']


def test_replay_main_thread_and_nesting_are_explicit(prepared):
    rd,_=prepared;errors=[]
    def child():
        try:
            with pr.replay(rd):pass
        except ValueError as exc: errors.append(str(exc))
    t=threading.Thread(target=child);t.start();t.join()
    assert len(errors)==1 and 'main-thread' in errors[0]
    with pr.replay(rd):
        with pytest.raises(ValueError,match='non-nested'):
            with pr.replay(rd):pass


@pytest.mark.parametrize('backend', ['science', 'scoped'])
@pytest.mark.parametrize('operation', ['approve', 'run'])
def test_actual_cli_dispatch_restores_environment_and_forwards_only_caller_assent(prepared, monkeypatch, backend, operation):
    rd,p=prepared
    if backend == 'scoped':
        (rd/'inputs/science-plan.json').rename(rd/'inputs/scoped-plan.json')
    owner = science if backend == 'science' else scoped
    calls=[]
    def mock(*args,**kwargs):
        assert execution.runtime_environment() == p['prepared_runtime']['environment']
        calls.append((args,kwargs));return 17
    monkeypatch.setattr(owner,operation,mock)
    monkeypatch.setenv('PATH','/parent/changed')
    before=execution.runtime_environment()
    argv=[operation,'--rundir',str(rd),'--replay-runtime']
    if operation=='approve':argv+=['--quote','Exact caller-provided mock quote','--scripted']
    else:argv+=['--resume']
    assert cli.main(argv)==17
    assert len(calls)==1 and execution.runtime_environment()==before
    if operation=='approve':
        assert calls[0]==((rd,'Exact caller-provided mock quote'),{'scripted':True})
    else:assert calls[0]==((rd,),{'resume':True})
    assert not (rd/'execution_attempt.json').exists()


def test_capsule_cli_is_read_only_and_output_never_overwrites(prepared, tmp_path):
    rd,p=prepared;out=tmp_path/'capsule.json'
    before=(rd/'inputs/science-plan.json').read_bytes()
    assert cli.main(['runtime-capsule','--rundir',str(rd),'--out',str(out)])==0
    assert read_json(out)==p['prepared_runtime']
    assert cli.main(['runtime-capsule','--rundir',str(rd),'--out',str(out)])==2
    assert (rd/'inputs/science-plan.json').read_bytes()==before


def test_external_capsule_requires_opt_in_before_any_dispatch(prepared,monkeypatch):
    rd,_=prepared;calls=[]
    monkeypatch.setattr(science,'run',lambda *a,**k:calls.append(1))
    assert cli.main(['run','--rundir',str(rd),'--runtime-capsule','anything'])==2
    assert calls==[]


@pytest.mark.parametrize('payload', ['{"a":1,"a":2}', '{"a":NaN}'])
def test_capsule_reader_rejects_duplicate_or_nonfinite_json(tmp_path,payload):
    p=tmp_path/'bad.json';p.write_text(payload)
    with pytest.raises(ValueError):pr.read_capsule(p)


def test_bounded_file_and_leaf_ancestor_symlink_refusals(tmp_path):
    p=tmp_path/'oversized.json';p.write_bytes(b' '*(pr.MAX_CAPSULE_BYTES+1))
    with pytest.raises(ValueError,match='bounded'):pr.read_capsule(p)
    target=tmp_path/'small.json';target.write_text('{}')
    leaf=tmp_path/'alias.json';leaf.symlink_to(target)
    with pytest.raises(ValueError,match='symlinks'):pr.read_capsule(leaf)
    ancestor=tmp_path/'alias';ancestor.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError,match='symlinks'):pr.read_capsule(ancestor/'small.json')


def test_real_science_plan_retains_capsule_and_fresh_verify_guard(tmp_path,monkeypatch):
    from test_physics_review import policy
    source=tmp_path/'input.txt';source.write_text('fabricated source fixture')
    impl=SimpleNamespace(validate=lambda task:None,inputs=lambda task,base:[source])
    monkeypatch.setattr(science,'adapter',lambda spec:impl)
    pol=policy();pol.update(allowed_stages=['science'],allowed_changed_paths=[],max_redos=0)
    spec={'schema_version':2,'mode':'likelihood-parity','source':'Synthetic source/mock runtime control',
          'assumptions':['No worker, approval, native or physics calculation'], 'max_seconds':30,
          'max_attempts':1,'approval_mode':'scripted_yes','task':{'input':str(source)},
          'review_policy':{'schema_version':1,'policy':pol,
            'correction_contract':{'task_fields':[],'input_slots':[]}}}
    sp=tmp_path/'spec.json';atomic_json(sp,spec);rd=tmp_path/'real-planning-only'
    p=science.plan(rd,sp)
    assert pr.for_plan(rd)==p['prepared_runtime']
    monkeypatch.setenv('PATH','/different-parent')
    with pytest.raises(ValueError,match='stale study'):science.verify_plan(rd)
    with pr.replay(rd):assert science.verify_plan(rd)==p
    source.write_text('changed source fixture')
    with pr.replay(rd):
        with pytest.raises(ValueError,match='stale study'):science.verify_plan(rd)
    assert not (rd/'inputs/science-approval.json').exists()
    assert not (rd/'execution_attempt.json').exists()


def test_historical_metadata_only_check_never_borrows_current_interpreter(prepared,monkeypatch):
    rd,p=prepared
    monkeypatch.setattr(sys,'executable','/historical-interpreter-no-longer-current')
    assert pr.validate(p['prepared_runtime'],p['stage_binding'],live_interpreter=False)==p['prepared_runtime']
    with pytest.raises(ValueError):pr.validate(p['prepared_runtime'],p['stage_binding'])


def test_legacy_plan_plain_verification_remains_valid_without_added_field(tmp_path,monkeypatch):
    from test_physics_review import policy
    payload=tmp_path/'source';payload.write_text('explicit fabricated source')
    monkeypatch.setattr(science,'adapter',lambda spec:SimpleNamespace(validate=lambda task:None,inputs=lambda task,base:[payload]))
    pol=policy();pol.update(allowed_stages=['science'],allowed_changed_paths=[],max_redos=0)
    spec={'schema_version':2,'mode':'likelihood-parity','source':'Synthetic legacy-schema inspectability',
          'assumptions':['No worker or approval'], 'max_seconds':30,'max_attempts':1,
          'approval_mode':'scripted_yes','task':{'input':str(payload)},
          'review_policy':{'schema_version':1,'policy':pol,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    sp=tmp_path/'spec.json';atomic_json(sp,spec);rd=tmp_path/'legacy-shaped-plan'
    proposal=science.plan(rd,sp);del proposal['prepared_runtime']
    atomic_json(rd/science.PLAN,proposal)
    atomic_json(rd/'inputs/checkin1.json',science.make_checkin(spec,execution.file_hash(rd/science.PLAN),proposal['stages'][0]))
    assert science.verify_plan(rd)==proposal


def test_null_and_empty_string_remain_different_planned_values(tmp_path, monkeypatch):
    monkeypatch.delenv('CONDA_PREFIX',raising=False)
    b=binding(tmp_path);c=pr.capture(b)
    assert c['environment']['CONDA_PREFIX'] is None
    changed=deepcopy(c['environment']);changed['CONDA_PREFIX']=''
    with pytest.raises(ValueError,match='planned runtime environment hash'):
        pr.capture(b,environment=changed)


def test_optimized_replay_refuses_before_environment_or_callback(prepared,monkeypatch):
    rd,_=prepared;before=dict(os.environ)
    monkeypatch.setattr(sys,'flags',SimpleNamespace(optimize=1))
    with pytest.raises(ValueError,match='ordinary main-thread'):
        with pr.replay(rd):pass
    assert dict(os.environ)==before


def test_reader_rechecks_ending_parent_alias_even_same_file_inode(tmp_path,monkeypatch):
    from contextlib import contextmanager
    parent=tmp_path/'ordinary';parent.mkdir();p=parent/'capsule.json';p.write_text('{}')
    original=Path.open
    @contextmanager
    def changed(path,*a,**k):
        with original(path,*a,**k) as f:
            yield f
        if path==p:
            retained=tmp_path/'retained';parent.rename(retained)
            parent.symlink_to(retained,target_is_directory=True)
    monkeypatch.setattr(Path,'open',changed)
    with pytest.raises(ValueError,match='symlinks'):pr.read_capsule(p)


def test_reader_rejects_same_content_leaf_replacement(tmp_path,monkeypatch):
    from contextlib import contextmanager
    p=tmp_path/'capsule.json';p.write_text('{}');original=Path.open
    @contextmanager
    def changed(path,*a,**k):
        with original(path,*a,**k) as f:yield f
        if path==p:
            replacement=tmp_path/'new.json'
            with original(replacement,'w') as f:f.write('{}')
            replacement.replace(p)
    monkeypatch.setattr(Path,'open',changed)
    with pytest.raises(ValueError,match='changed while reading'):pr.read_capsule(p)


def test_excessive_json_nesting_is_a_bounded_cli_error(tmp_path):
    depth=33
    p=tmp_path/'nested.json';p.write_text('['*depth+'0'+']'*depth)
    with pytest.raises(ValueError,match='nesting'):pr.read_capsule(p)


def test_nesting_census_preserves_quoted_brackets_and_escaped_quotes(tmp_path):
    p=tmp_path/'quoted.json';value={'literal': '['*40 + '\\"' + ']'*40}
    p.write_text(json.dumps(value))
    assert pr.read_capsule(p)==value
