"""Real existing journal/projection APIs over synthetic retained scientific records."""
import copy,json,os,hashlib
from pathlib import Path
import pytest
from ravel.workflow import review_context as c, physics_review as r, execution as e
from ravel.workflow.state_io import atomic_json, read_json
from test_physics_review import run,opened,finding,accept,make_attempt,check_packet

@pytest.fixture(autouse=True)
def inert_runtime_for_pure_reader_controls(monkeypatch):
    # Source-only metadata controls: no process command is dispatched.
    monkeypatch.setattr(e, 'runtime_context', lambda: {
        'platform': 'synthetic', 'python': 'unit-fixture',
        'environment_sha256': e.digest(e.runtime_environment()),
        'packages_sha256': 'synthetic'})

@pytest.fixture
def context_case(run,tmp_path):
    root,_=run;opened(run);packet=tmp_path/'context';manifest=c.create(root,'critic',packet)
    return root,packet,manifest

def read(case,ids=None,**kwargs):
    root,packet,m=case
    return c.read_artifacts(packet,ids if ids is not None else [x['id'] for x in m['artifacts']],expected_manifest_sha256=m['sha256'],rundir=root,expected_role='critic',**kwargs)

def after_copy(monkeypatch,packet,callback):
    old=c._BatchReadSession.read_bytes;seen=[]
    def wrapped(session,path,**kw):
        raw=old(session,path,**kw)
        if Path(path).is_relative_to(packet/'artifacts') and not seen:
            seen.append(session);callback(session)
        return raw
    monkeypatch.setattr(c._BatchReadSession,'read_bytes',wrapped)
    return seen

@pytest.mark.parametrize('role',c.ROLES)
def test_all_existing_role_content_exactly_matches_original_reader(run,tmp_path,role):
    root,_=run;opened(run);packet=tmp_path/'role';m=c.create(root,role,packet)
    result=c.read_artifacts(packet,[x['id'] for x in m['artifacts']],expected_manifest_sha256=m['sha256'],rundir=root,expected_role=role)
    assert [x['content'] for x in result['artifacts']]==[c.read_artifact(packet,x['id'],expected_manifest_sha256=m['sha256']) for x in m['artifacts']]
    assert result['receipt']['requested_content_reads']==len(m['artifacts'])
    assert result['receipt']['manifest_parses']==1
    assert all(x['content_read'] and hashlib.sha256(x['content']).hexdigest()==x['sha256'] for x in result['artifacts'])
    assert all(result['receipt'][k] is False for k in ['acceptance','delivery','reuse','role_vote'])
    assert result['receipt']['sha256']==e.digest({k:v for k,v in result['receipt'].items() if k!='sha256'})


def test_subset_requested_order_and_no_cross_call_cache(context_case,monkeypatch):
    root,packet,m=context_case;ids=[x['id'] for x in m['artifacts']][::-1][:2];seen=[];old=c._BatchReadSession.close
    def close(session):seen.append(session);return old(session)
    monkeypatch.setattr(c._BatchReadSession,'close',close)
    a=read(context_case,ids);b=read(context_case,ids)
    assert a['receipt']['requested_ids']==b['receipt']['requested_ids']==ids
    assert len({id(x) for x in seen})==2 and all(x.closed and not x.hashes for x in seen)
    (packet/m['artifacts'][-1]['path']).write_bytes(b'corrupt')
    with pytest.raises(ValueError):read(context_case,[m['artifacts'][-1]['id']])


@pytest.mark.parametrize('ids',[[],['missing'],['a0000','a0000'],['a١٢٣٤'],True,'a0000'])
def test_invalid_requested_population(context_case,ids):
    with pytest.raises(ValueError):read(context_case,ids)

@pytest.mark.parametrize('key,value',[('max_manifest_bytes',True),('max_total_bytes',0),('max_source_bytes',2**40),('max_artifacts',0),('context_max_file_bytes',False)])
def test_invalid_bounds(context_case,key,value):
    with pytest.raises(ValueError):read(context_case,**{key:value})


@pytest.mark.parametrize('key,value',[('max_manifest_bytes',1),('max_artifact_bytes',1),('max_total_bytes',1),('max_source_bytes',1),('max_session_io_bytes',1),('max_artifacts',1)])
def test_actual_file_population_and_byte_bounds(context_case,key,value):
    with pytest.raises(ValueError):read(context_case,**{key:value})


def test_full_source_role_basis_cannot_be_relabelled_even_with_self_hash(context_case):
    root,packet,m=context_case
    entry=next(x for x in m['artifacts'] if x['source_path']=='outputs/produced.json')
    forged=b'{"value": 999}\n';(packet/entry['path']).write_bytes(forged);entry['sha256']=hashlib.sha256(forged).hexdigest()
    m['sha256']=e.digest({k:v for k,v in m.items() if k!='sha256'});atomic_json(packet/'manifest.json',m)
    # Existing one-ID reader proves only the copy's external-manifest commitment.
    assert c.read_artifact(packet,entry['id'],expected_manifest_sha256=m['sha256'])==forged
    with pytest.raises(ValueError,match='role/source/journal'):read(context_case,[entry['id']])


def test_context_after_new_journal_basis_requires_fresh_synthesis_packet(run,tmp_path):
    root,_=run;opened(run);packet=tmp_path/'synth';m=c.create(root,'synthesizer',packet)
    r.submit_review(root,role='physics_critic',actor_id='critic',verdict='accept',summary='actual synthetic role',claim_scope='diagnostic')
    with pytest.raises(ValueError,match='role/source/journal'):
        c.read_artifacts(packet,[m['artifacts'][0]['id']],expected_manifest_sha256=m['sha256'],rundir=root,expected_role='synthesizer')


def test_legitimate_prior_review_append_keeps_unchanged_critic_projection(context_case):
    root,packet,m=context_case
    before=len(r._read(root)[1])
    r.submit_review(root,role='physics_critic',actor_id='critic',verdict='accept',
                    summary='Synthetic retained review event',claim_scope='diagnostic')
    result=read(context_case)
    assert result['receipt']['journal_checkpoint']['sequence']==before+1
    assert result['receipt']['source_event_sha256']==m['source_event_sha256']
    assert [x['content'] for x in result['artifacts']]==[
        c.read_artifact(packet,x['id'],expected_manifest_sha256=m['sha256']) for x in m['artifacts']]


def test_failure_after_first_genuine_payload_has_no_partial_success_return(context_case,monkeypatch):
    _,packet,m=context_case
    seen=after_copy(monkeypatch,packet,lambda session:(_ for _ in ()).throw(
        ValueError('synthetic operation failed after first genuine content read')))
    with pytest.raises(ValueError,match='after first genuine'):read(context_case)
    assert len(seen)==1 and seen[0].closed and not seen[0].hashes and not seen[0].proofs
    payload_reads=[x for x in seen[0].content_reads if Path(x[0]).parent==packet/'artifacts']
    assert len(payload_reads)==1 and payload_reads[0][2]==m['artifacts'][0]['sha256']


def test_inherited_json_snapshot_reads_authenticated_bytes_and_charges_session_io(context_case):
    root,_,_=context_case
    path=root/'outputs/additional.json';raw=b'{"observed": 7}\n';path.write_bytes(raw)
    session=c._BatchReadSession(root,1_000_000)
    before=session.io_bytes
    document=session.snapshot(['outputs/additional.json'],outputs=True)
    assert session.io_bytes-before==2*len(raw)  # one hash and one actual JSON read
    assert document[str(path)]['files'][0]['sha256']==hashlib.sha256(raw).hexdigest()
    assert [x for x in session.content_reads if x[0]==str(path)]==[
        (str(path),len(raw),hashlib.sha256(raw).hexdigest())]
    assert session.finish()==[] and session.closed


def test_explicit_expected_role_and_cycle(context_case,tmp_path):
    root,packet,m=context_case
    with pytest.raises(ValueError):c.read_artifacts(packet,[m['artifacts'][0]['id']],expected_manifest_sha256=m['sha256'],rundir=root,expected_role='verifier')
    accept(root);fresh=make_attempt(root,value=2);check_packet(root,fresh)
    r.open_cycle(root,effective_settings=['inputs/settings.cfg'],stage_receipts=[fresh['attempt_record']],check_results='inputs/checks.json',checkpoint=True)
    with pytest.raises(ValueError,match='role/source/journal'):read(context_case)


@pytest.mark.parametrize('change',['manifest_inode','packet_ABA','source_ABA','blob','journal_append','head_inode','ledger_inode','policy_ABA','runtime','request_order'])
def test_changes_during_batch_refuse_before_return(context_case,monkeypatch,change):
    root,packet,m=context_case;ids=[x['id'] for x in m['artifacts']]
    def aba(path):
        raw=path.read_bytes();s=path.stat();path.write_bytes(b'x'*len(raw));path.write_bytes(raw);os.utime(path,ns=(s.st_atime_ns,s.st_mtime_ns))
    def mutate(session):
        if change=='manifest_inode':
            p=packet/'manifest.json';q=packet/'replacement';q.write_bytes(p.read_bytes());q.replace(p)
        elif change=='packet_ABA':aba(packet/m['artifacts'][0]['path'])
        elif change=='source_ABA':aba(root/m['artifacts'][0]['source_path'])
        elif change=='blob':
            cycle=read_json(root/r.HEAD);events=sorted((root/r.DIRECTORY/'events').glob('*.json'));doc=read_json(events[-1]);blob=root/next(x['snapshot'] for x in doc['snapshots'] if x['snapshot']);aba(blob)
        elif change=='journal_append':(root/r.DIRECTORY/'events'/'99999999.json').write_text('{}')
        elif change in ['head_inode','ledger_inode']:
            p=root/(r.HEAD if change=='head_inode' else e.STATE_NAME);q=root/'replacement';q.write_bytes(p.read_bytes());q.replace(p)
        elif change=='policy_ABA':aba(root/r.POLICY)
        elif change=='runtime':monkeypatch.setenv('CONDA_PREFIX','supplied-runtime-drift')
        else:ids.reverse()
    seen=after_copy(monkeypatch,packet,mutate)
    with pytest.raises(ValueError):read(context_case,ids)
    assert seen and all(s.closed and not s.hashes for s in seen)


@pytest.mark.parametrize('target',['packet','manifest','artifact','ancestry'])
def test_symlink_refusal(context_case,tmp_path,target):
    root,packet,m=context_case
    if target=='packet':
        link=tmp_path/'link';link.symlink_to(packet,target_is_directory=True);packet=link
    elif target=='ancestry':
        p=packet/'artifacts';new=packet/'retained';p.rename(new);p.symlink_to(new,target_is_directory=True)
    else:
        p=packet/('manifest.json' if target=='manifest' else m['artifacts'][0]['path']);new=packet/'copy';new.write_bytes(p.read_bytes());p.unlink();p.symlink_to(new)
    with pytest.raises(ValueError):read((root,packet,m))


@pytest.mark.parametrize('raised',[False,True])
def test_final_error_or_exception_closes_and_never_returns_receipt(context_case,monkeypatch,raised):
    seen=[]
    def fail(session):
        seen.append(session)
        if raised:raise OSError('supplied interruption')
        return ['supplied final refusal']
    monkeypatch.setattr(c._BatchReadSession,'finish',fail)
    with pytest.raises((ValueError,OSError)):read(context_case)
    assert seen[0].closed and not seen[0].hashes


def test_pre_correction_source_and_new_current_source_stay_distinct(run,tmp_path):
    root,_=run;opened(run)
    r.submit_review(root,role='physics_critic',actor_id='critic',verdict='send_back',summary='correction request',findings=[finding()])
    (root/'inputs/settings.cfg').write_text('efficiency=0.85\n')
    r.authorize_correction(root,actor_id='physicist',changed_paths=['inputs/settings.cfg'],stages=['detector'],recheck_checks=['agreement'])
    packet=tmp_path/'verifier';m=c.create(root,'verifier',packet)
    result=c.read_artifacts(packet,[x['id'] for x in m['artifacts']],expected_manifest_sha256=m['sha256'],rundir=root,expected_role='verifier')
    old=next(x for x in result['artifacts'] if x['source_path']=='inputs/settings.cfg' and x['source_phase']=='current_cycle')
    new=next(x for x in result['artifacts'] if x['source_path']=='inputs/settings.cfg' and x['source_phase']=='admitted_correction')
    assert old['content']==b'efficiency=0.8\n' and new['content']==b'efficiency=0.85\n'
    assert old['current_source']['sha256']==new['current_source']['sha256']!=old['source_sha256']


@pytest.mark.parametrize('kind',['manifest','policy','payload'])
def test_descriptor_consumption_refuses_actual_read_ABA(context_case,monkeypatch,kind):
    root,packet,m=context_case
    path=packet/'manifest.json' if kind=='manifest' else root/r.POLICY if kind=='policy' else packet/m['artifacts'][0]['path']
    original=path.read_bytes();previous=path.stat();seen=[];old_open=Path.open
    class Stream:
        def __init__(self,inner):self.inner=inner
        def __enter__(self):return self
        def __exit__(self,*args):return self.inner.__exit__(*args)
        def __getattr__(self,name):return getattr(self.inner,name)
        def read(self,size=-1):
            with old_open(path,'wb') as writer:writer.write(b'x'*len(original))
            raw=self.inner.read(size);seen.append(raw)
            with old_open(path,'wb') as writer:writer.write(original)
            os.utime(path,ns=(previous.st_atime_ns,previous.st_mtime_ns))
            return raw
    def opening(current,*args,**kwargs):
        inner=old_open(current,*args,**kwargs)
        return Stream(inner) if current==path and args and args[0]=='rb' and not seen else inner
    monkeypatch.setattr(Path,'open',opening)
    with pytest.raises(ValueError):read(context_case)
    assert seen and seen[0]==b'x'*len(original) and path.read_bytes()==original


def test_added_unindexed_copy_during_subset_refuses(context_case,monkeypatch):
    _,packet,m=context_case
    after_copy(monkeypatch,packet,lambda session:(packet/'artifacts/a9999.txt').write_bytes(b'unindexed'))
    with pytest.raises(ValueError):read(context_case,[m['artifacts'][0]['id']])


def test_unrequested_copy_drift_during_subset_is_freshness_not_content_read(context_case,monkeypatch):
    _,packet,m=context_case;target=packet/m['artifacts'][-1]['path']
    after_copy(monkeypatch,packet,lambda session:target.write_bytes(b'unrequested'))
    with pytest.raises(ValueError):read(context_case,[m['artifacts'][0]['id']])


def test_final_ledger_read_consumes_bounded_actual_bytes_and_refuses_ABA(context_case,monkeypatch):
    root,packet,m=context_case;path=root/e.STATE_NAME;raw=path.read_bytes();seen=[];old_open=Path.open
    class Stream:
        def __init__(self,inner):self.inner=inner
        def __enter__(self):return self
        def __exit__(self,*args):return self.inner.__exit__(*args)
        def __getattr__(self,name):return getattr(self.inner,name)
        def read(self,size=-1):
            assert size==len(raw)+1
            old=path.stat()
            with old_open(path,'wb') as s:s.write(b'x'*len(raw))
            value=self.inner.read(size);seen.append(value)
            with old_open(path,'wb') as s:s.write(raw)
            os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
            return value
    # Arm the actual descriptor adversary after the last requested payload.
    old_read=c._BatchReadSession.read_bytes
    def wrapped(session,current,**kwargs):
        value=old_read(session,current,**kwargs)
        if current==packet/m['artifacts'][-1]['path']:
            def opening(p,*args,**kw):
                s=old_open(p,*args,**kw)
                return Stream(s) if p==path and args and args[0]=='rb' and not seen else s
            monkeypatch.setattr(Path,'open',opening)
        return value
    monkeypatch.setattr(c._BatchReadSession,'read_bytes',wrapped)
    with pytest.raises(ValueError):read(context_case)
    assert seen and path.read_bytes()==raw
