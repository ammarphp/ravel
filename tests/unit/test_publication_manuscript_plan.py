"""Controls that take the publication build through the ordinary plan of the manuscript-build operation.

The publication module's own controls ship in their test files."""
from copy import deepcopy
import json
import os
from pathlib import Path
import pytest

from ravel.physics import manuscript_build as mb
from ravel.workflow import execution as e
from ravel.workflow import manuscript_production as mp
from ravel.workflow import publication_runtime as pr
from ravel.workflow import physics_review, science
from test_publication_prepare_build import prepare
from test_publication_runtime_v2 import LIMITS
from test_publication_unqualified_validation import prepared, runtime_proofs, session


# ---------------------------------------------------------------- moved from test_publication_claim_scope.py
@pytest.mark.parametrize('selection', [{}, {'approval_mode': 'scripted_yes'}])
def test_actual_public_build_plan_uses_canonical_scope_without_authority(tmp_path, monkeypatch, selection):
    value, rundir, calls = prepare(tmp_path, monkeypatch, **selection)
    spec = json.loads(Path(value['specification']['path']).read_bytes())
    expected = selection.get('approval_mode', 'physicist')
    assert spec['review_policy']['policy']['claim_scopes'] == {
        'manuscript_pdf_delivery': {'checks': ['integrity'], 'actions': ['delivery']}}
    assert physics_review.validate_policy(spec['review_policy']['policy']) == []
    mb.validate_scope(spec)
    assert science.verify_plan(rundir)['approval_mode'] == expected
    assert spec['max_seconds'] == 30 and spec['max_attempts'] == 1
    assert spec['review_policy']['policy']['max_redos'] == 0
    assert not (rundir / science.APPROVAL).exists()
    assert not (rundir / 'execution_attempt.json').exists()
    assert value['execution_authorized'] is False
    assert value['scientific_acceptance'] is False
    assert value['ordinary_plan']['expert_review'] is False and calls == []


# ---------------------------------------------------------------- moved from test_publication_prepare_build.py
@pytest.mark.parametrize('selection',[{}, {'approval_mode':'scripted_yes'}])
def test_public_prepare_build_reaches_real_plan_without_implicit_approval(tmp_path,monkeypatch,selection):
    value,rd,calls=prepare(tmp_path,monkeypatch,**selection)
    spec=json.loads(Path(value['specification']['path']).read_text())
    expected=selection.get('approval_mode','physicist')
    assert spec['approval_mode']==expected and value['ordinary_plan']['approval_mode']==expected
    assert spec['max_seconds']==30 and spec['max_attempts']==1 and spec['goal_binding']['assignment_id']=='publication-build'
    assert science.verify_plan(rd)['approval_mode']==expected
    assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()
    assert value['execution_authorized'] is False and value['scientific_acceptance'] is False
    assert value['ordinary_plan']['expert_review'] is False and calls==[]


def test_explicit_engineering_assent_uses_existing_ordinary_machine_receipt(tmp_path,monkeypatch):
    value,rd,calls=prepare(tmp_path,monkeypatch,approval_mode='scripted_yes')
    with pytest.raises(ValueError,match='approval mode'):
        science.approve(rd,'Synthetic engineering control only',scripted=False)
    assert not (rd/science.APPROVAL).exists()
    science.approve(rd,'Synthetic engineering software control only; not human or physics review',scripted=True)
    record=json.loads((rd/science.APPROVAL).read_text())
    assert record['approval_mode']=='scripted_yes' and record['expert_review'] is False
    assert record['generated_by']=='ravel.workflow.science.approve' and record['authority']=='scripted_experiment'
    assert science.verify_plan(rd,approved=True)['approval_mode']=='scripted_yes' and calls==[]


def test_autonomous_assent_requires_existing_actual_user_delegation(tmp_path,monkeypatch):
    value,rd,calls=prepare(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='delegation required'):
        science.approve(rd,'A label is not user authority',_delegated=True)
    assert not (rd/science.APPROVAL).exists() and calls==[]


# ---------------------------------------------------------------- moved from test_publication_unqualified_validation.py
def test_actual_verify_v2_keeps_four_live_authors_and_complete_equal_plan(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch)
    expected=mb.inputs(f['task'],f['base']);seconds=mb.execution_seconds(f['task'],f['base'])
    calls=[];verify=mp.verify_author
    def current(*a,**k):calls.append((a,k));return verify(*a,**k)
    monkeypatch.setattr(mp,'verify_author',current)
    s=session(f)
    result=science._verify_v2(f['rd'],_session=s)
    assert len(calls)==4 and result==json.loads((f['rd']/science.PLAN).read_text())
    # The ordinary source base is the specification directory, distinct from
    # the runtime snapshot base originally supplied to prepare_build.
    proofs=runtime_proofs(s)
    assert len(proofs)==1 and {r['kind'] for r in proofs[0].operations.values()}=={'asset-tree','unqualified-closure'}
    first=proofs[0];ordinary_base=result['base_dir']
    assert ordinary_base==f['result']['ordinary_plan']['base_dir']
    assert first.context['literal_base']==ordinary_base
    assert mb._validation_inputs(f['task'],ordinary_base,s)==expected
    assert mb._validation_execution_seconds(f['task'],ordinary_base,s)==seconds==30
    assert runtime_proofs(s)==[first]
    assert len(calls)==6 # Two further original loads, not authority memo hits.
    assert s.finish()==[] and s.closed and not s.proofs
    assert len(calls)==6 # Ending replay is runtime/tree only, never a fake author.
    assert not (f['rd']/science.APPROVAL).exists() and not (f['rd']/'execution_attempt.json').exists()


@pytest.mark.parametrize('change',['byte-restored-mtime','mode','inode','add','delete','empty-directory','alias','special-file','manifest'])
def test_complete_runtime_changes_refuse_on_reuse_or_final_census(tmp_path,monkeypatch,change):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    mb._validation_inputs(f['task'],f['base'],s)
    q=Path(f['runtime']['snapshot_root'])/'selected/assets/synthetic.tfm'
    if change=='byte-restored-mtime':
        old=q.stat();raw=q.read_bytes();q.write_bytes(b'Z'+raw[1:]);os.utime(q,ns=(old.st_atime_ns,old.st_mtime_ns))
    elif change=='mode':q.chmod(0o600)
    elif change=='inode':
        other=q.with_name('replacement');other.write_bytes(q.read_bytes());other.replace(q)
    elif change=='add':(q.parent/'new.sty').write_bytes(b'new')
    elif change=='delete':q.unlink()
    elif change=='empty-directory':(q.parent/'empty-new').mkdir()
    elif change=='alias':q.unlink();q.symlink_to(q.parent/'article.cls')
    elif change=='special-file':os.mkfifo(q.parent/'new-fifo')
    else:
        path=Path(f['runtime']['asset_trees'][0]['manifest']['path']);path.write_bytes(path.read_bytes()+b' ')
    try:
        with pytest.raises((ValueError,OSError)):
            mb._validation_execution_seconds(f['task'],f['base'],s)
    finally:s.close()
    assert s.closed and not s.proofs


@pytest.mark.parametrize('change',['response','request','graph-spec','campaign'])
def test_runtime_proof_never_replaces_actual_live_authority(tmp_path,monkeypatch,change):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    mb._validation_inputs(f['task'],f['base'],s)
    if change=='response':f['response'].write_bytes(f['response'].read_bytes()+b' ')
    elif change=='request':
        p=Path(f['binding']['request']['path']);p.write_bytes(p.read_bytes()+b' ')
    elif change=='graph-spec':
        from ravel.workflow import agent_graph
        p=Path(f['binding']['graph'])/agent_graph.SPEC;p.write_bytes(p.read_bytes()+b' ')
        # Real verifier compares decoded spec as well as retained external request.
        d=json.loads(p.read_text());d['budget']['max_calls']+=1;p.write_text(json.dumps(d))
    else:f['state']['graphs']=[]
    try:
        with pytest.raises((ValueError,OSError)):
            mb._validation_execution_seconds(f['task'],f['base'],s)
    finally:s.close()


def test_registration_race_does_not_publish_a_partial_success(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    q=Path(f['runtime']['snapshot_root'])/'selected/assets/synthetic.tfm'
    original=s.hash_file;changed=[False]
    def read(p):
        if Path(p)==q and not changed[0]:changed[0]=True;q.write_bytes(b'changed at registration')
        return original(p)
    monkeypatch.setattr(s,'hash_file',read)
    try:
        with pytest.raises(ValueError):mb._validation_inputs(f['task'],f['base'],s)
        assert changed[0] and all(not proof.operations for proof in runtime_proofs(s))
    finally:s.close()


def test_late_callback_change_is_caught_by_original_session_closing_census(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    mb._validation_inputs(f['task'],f['base'],s)
    q=Path(f['runtime']['snapshot_root'])/'selected/assets/synthetic.tfm'
    s.retain_final_check(lambda:q.write_bytes(b'late after full runtime replay'))
    errors=s.finish()
    assert errors and any('changed' in value for value in errors) and s.closed and not s.proofs


def test_new_outward_calls_and_approval_do_not_inherit_proofs(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);seen=[];factory=e._validation_session
    def create(*a,**k):s=factory(*a,**k);seen.append(s);return s
    monkeypatch.setattr(e,'_validation_session',create)
    first=science.verify_plan(f['rd']);second=science.verify_plan(f['rd'])
    assert first==second and seen and all(s.closed and not s.proofs for s in seen)
    assert len({id(s) for s in seen})==len(seen)
    science.approve(f['rd'],'Synthetic engineering machine approval only',scripted=True)
    receipt=json.loads((f['rd']/science.APPROVAL).read_text())
    assert receipt['approval_mode']=='scripted_yes' and receipt['expert_review'] is False
    assert all(s.closed and not s.proofs for s in seen)
    assert not (f['rd']/'execution_attempt.json').exists()


def test_unsupported_callable_uses_uncached_original_path(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);s=session(f);old=pr._inventory;calls=[]
    def custom(*a,**k):calls.append((a,k));return old(*a,**k)
    monkeypatch.setattr(pr,'_inventory',custom)
    mb._validation_inputs(f['task'],f['base'],s)
    assert len(calls)==4 and runtime_proofs(s)==[]
    assert s.finish()==[]


def test_distinct_literal_configuration_and_closed_session_do_not_borrow(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    first=mb._validation_inputs(f['task'],f['base'],s)
    original=Path(f['task']['config']);second=original.with_name('second-config.json');second.write_bytes(original.read_bytes())
    second_task={'config':str(second)}
    other=mb._validation_inputs(second_task,f['base'],s)
    assert set(first)-{original}==set(other)-{second} and len(runtime_proofs(s))==2
    assert s.finish()==[]
    with pytest.raises(ValueError,match='closed'):mb._validation_inputs(f['task'],f['base'],s)


@pytest.mark.parametrize('field',['max_files','max_bytes','max_metadata_bytes'])
def test_selected_policy_and_full_union_refusals_are_not_memoized(tmp_path,monkeypatch,field):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    mb._validation_inputs(f['task'],f['base'],s)
    p=Path(f['task']['config']);d=json.loads(p.read_text());d['custody_limits'][field]=1
    other=p.with_name('lower-policy.json');other.write_text(json.dumps(d))
    try:
        with pytest.raises(ValueError):mb._validation_inputs({'config':str(other)},f['base'],s)
    finally:s.close()


def test_qualification_null_still_cannot_satisfy_required_final_runtime(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    mb._validation_inputs(f['task'],f['base'],s)
    with pytest.raises(ValueError,match='qualification'):
        pr.closure_inputs(f['runtime'],f['base'],LIMITS,require_qualified=True)
    assert s.finish()==[]


def test_overlapping_repeated_asset_tree_keeps_one_complete_union(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch)
    p=Path(f['task']['config']);d=json.loads(p.read_text())
    d['runtime']['asset_trees'].append(deepcopy(d['runtime']['asset_trees'][0]))
    other=p.with_name('overlapping-config.json');other.write_text(json.dumps(d))
    task={'config':str(other)};expected=mb.inputs(task,f['base']);s=session(f)
    actual=mb._validation_inputs(task,f['base'],s)
    assert actual==expected and len(actual)==len(set(actual))
    proofs=runtime_proofs(s)
    assert len(proofs)==1 and sum(r['kind']=='asset-tree' for r in proofs[0].operations.values())==1
    assert s.finish()==[]


def test_wrong_run_and_caller_supplied_proof_cannot_reuse_original_success(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    mb._validation_inputs(f['task'],f['base'],s)
    key=next(k for k in s.proofs if type(k) is tuple and k and k[0]=='publication-unqualified-runtime-proof/v1')
    s.proofs[key]={'caller_generated_success':True}
    try:
        with pytest.raises(ValueError,match='caller-supplied'):mb._validation_inputs(f['task'],f['base'],s)
    finally:s.close()
    s=session(f);original=s.rundir;s.rundir=tmp_path/'different-run'
    try:
        # The proof factory is owned by the exact current session/run. Its run
        # cannot be changed after construction and turned into a borrowed token.
        proof=pr._BuildRuntimeProof(s,{},lambda:());s.rundir=original
        with pytest.raises(ValueError,match='cross-run'):proof.live()
    finally:s.close()


def test_config_read_to_registration_change_cannot_become_a_new_baseline(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    q=Path(f['task']['config']);original=s.hash_file;changed=[False]
    def read(path):
        if Path(path)==q and not changed[0]:
            changed[0]=True;doc=json.loads(q.read_text());doc['max_seconds']+=1
            q.write_text(json.dumps(doc))
        return original(path)
    monkeypatch.setattr(s,'hash_file',read)
    try:
        with pytest.raises(ValueError):mb._validation_inputs(f['task'],f['base'],s)
        assert changed[0] and runtime_proofs(s)==[]
    finally:s.close()


def test_distinct_ordinary_and_runtime_bases_have_independent_complete_proofs(tmp_path,monkeypatch):
    f=prepared(tmp_path,monkeypatch);s=session(f)
    result=science._verify_v2(f['rd'],_session=s)
    ordinary_base=result['base_dir'];runtime_base=str(f['base'])
    assert ordinary_base!=runtime_base
    first=runtime_proofs(s)
    assert len(first)==1 and first[0].context['literal_base']==ordinary_base
    expected=mb._validation_inputs(f['task'],ordinary_base,s)
    assert runtime_proofs(s)==first
    assert mb._validation_inputs(f['task'],f['base'],s)==expected
    proofs=runtime_proofs(s)
    assert len(proofs)==2 and first[0] in proofs
    assert {proof.context['literal_base'] for proof in proofs}=={ordinary_base,runtime_base}
    assert {proof.context['resolved_base'] for proof in proofs}=={str(Path(ordinary_base).resolve()),str(Path(runtime_base).resolve())}
    assert all(proof.context['task']==f['task'] for proof in proofs)
    assert all({row['kind'] for row in proof.operations.values()}=={'asset-tree','unqualified-closure'} for proof in proofs)
    assert mb._validation_execution_seconds(f['task'],f['base'],s)==30
    assert runtime_proofs(s)==proofs
    assert s.finish()==[] and s.closed and not s.proofs
    assert not (f['rd']/science.APPROVAL).exists() and not (f['rd']/'execution_attempt.json').exists()
