"""Request-size/identity controls and one ordinary tiny-child registration."""
from pathlib import Path
import json,os,sys,time
import pytest
import test_registered_helpers as b
r=b.registration

def test_real_contract_size_is_independent_of_control_record_limit(tmp_path):
    p=tmp_path/'request.json';p.write_bytes(b'{"pad":"'+b'x'*(79539-10)+b'"}');assert p.stat().st_size==79539
    with pytest.raises(ValueError,match='metadata byte ceiling'):r.read(p)
    assert r.read_contract(p)==json.loads(p.read_bytes())
    assert r.MAX_EVENT_BYTES==65536 and r.MAX_MESSAGE==4096 and r.MAX_TOTAL_BYTES==1048576

@pytest.mark.parametrize('size',[8*1024**2-1,8*1024**2,8*1024**2+1])
def test_contract_exact_byte_boundary(tmp_path,size):
    p=tmp_path/'request.json';raw=b'{"pad":"'+b'x'*(size-10)+b'"}';assert len(raw)==size;p.write_bytes(raw)
    if size<=8*1024**2:assert len(r.read_contract(p)['pad'])==size-10
    else:
        with pytest.raises(ValueError,match='8MiB'):r.read_contract(p)

def test_malformed_json_refuses(tmp_path):
    p=tmp_path/'request.json';p.write_bytes(b'{"unfinished":')
    with pytest.raises(json.JSONDecodeError):r.read_contract(p)

@pytest.mark.parametrize('kind',['ending','ancestor','dangling_ancestor'])
def test_symlink_routes_refuse(tmp_path,kind):
    real=tmp_path/'actual';real.mkdir();(real/'request.json').write_text('{}')
    if kind=='ending':
        path=tmp_path/'request.json';path.symlink_to(real/'request.json')
    else:
        link=tmp_path/'link';link.symlink_to(real if kind=='ancestor' else tmp_path/'absent',target_is_directory=True);path=link/'request.json'
    with pytest.raises(ValueError,match='ordinary registration path'):r.read_contract(path)

def large_owner(tmp_path):
    owner,observer,request=b.fixture(tmp_path)
    body={'padding':'x'*79525};request.write_bytes(r.compact(body));assert request.stat().st_size>65536
    owner._declaration['helpers'][0]['contract_sha256']=r.digest(body)
    return owner,observer,request

def test_owner_large_request_passes_exact_digest_and_preserves_drift_refusal(tmp_path,monkeypatch):
    owner,observer,request=large_owner(tmp_path)
    try:
        a,c=b.register(owner,monkeypatch);assert len(a.sent)==len(c.sent)==1
        assert owner.rows['preparation']['state']=='registered'
    finally:owner.close()

def test_owner_changed_large_request_never_ack(tmp_path,monkeypatch):
    owner,observer,request=large_owner(tmp_path)
    request.write_bytes(r.compact({'padding':'y'*79525}))
    try:
        with pytest.raises(ValueError,match='request contract/path'):b.register(owner,monkeypatch)
        assert not owner.rows
    finally:owner.close()

@pytest.mark.parametrize('changed',[False,True])
def test_bootstrap_large_request_checks_identity_before_any_socket(tmp_path,monkeypatch,changed):
    owner,observer,request=large_owner(tmp_path)
    # Reflect only the prospective declaration in a supplied descriptor.
    descriptor={**owner.descriptor,'declaration':owner.declaration};p=tmp_path/'descriptor.json';p.write_bytes(r.compact(descriptor))
    monkeypatch.setenv(r.ENV,str(p));monkeypatch.setenv(r.KEY_ENV,'preparation')
    monkeypatch.setattr(r.os,'getpgid',lambda pid:os.getpid());monkeypatch.setattr(r.os,'getsid',lambda pid:os.getpid())
    calls=[]
    class ReachedSocket(Exception):pass
    def stop(*args,**kwargs):calls.append(True);raise ReachedSocket('Past exact contract validation')
    monkeypatch.setattr(r.socket,'socket',stop)
    if changed:request.write_bytes(r.compact({'padding':'z'*79525}))
    try:
        if changed:
            with pytest.raises(ValueError,match='Bootstrap request differs'):r.bootstrap(request,time.monotonic()+3.)
            assert not calls
        else:
            with pytest.raises(ReachedSocket):r.bootstrap(request,time.monotonic()+3.)
            assert calls==[True]
    finally:owner.close()

@pytest.mark.skipif(sys.platform!='darwin',reason='Actual local Darwin identity ABI required')
def test_ordinary_supervisor_large_metadata_fixture_registers_and_cleans(tmp_path,monkeypatch):
    execution,supervisor=b.overlay(monkeypatch)
    request=tmp_path/'gate/request.json';request.parent.mkdir()
    body={'registration_source':r.pin(b.SOURCE),'marker':str(tmp_path/'after-ack.json'),'action':'normal',
          'descendant':str(tmp_path/'descendant.pid'),'helper_started':str(tmp_path/'helper.pid'),'padding':''}
    target=79539;body['padding']='x'*(target-len(r.compact(body)));request.write_bytes(r.compact(body));assert request.stat().st_size==target
    declaration={'schema_version':1,'registration_source':r.pin(b.SOURCE),'helpers':[{'key':'preparation',
        'interpreter_invocation':sys.executable,'interpreter_binary':b.BINARY,'helper_source':r.pin(b.CHILD),
        'request_root':str(request.parent),'contract_sha256':r.digest(body)}],
        'ack_seconds':1.,'cleanup_seconds':3.,'max_helpers':1,'max_kernel_calls':4096,'max_total_bytes':1048576}
    run=tmp_path/'run';run.mkdir()
    code=supervisor.supervise('large_metadata_control',run,0,'logs/control.log',[sys.executable,str(b.CHILD),'worker',str(request)],
        inputs=[str(request)],outputs=[],kill_secs=5.,grace=.5,poll=.01,helper_declaration=declaration, _engineering_only=True)
    state=execution.load_execution(run)['stages']['large_metadata_control']
    assert code==0 and state['helper_declaration']==declaration
    assert all(not x['requires_recovery'] for x in state['registered_helper_cleanup'])
    marker=json.loads(Path(body['marker']).read_bytes())
    assert r.KernelObserver().group(marker['helper'])==[]
    print(json.dumps({'kind':'actual ordinary supervisor large-request fixture','request_bytes':target,'code':code,
        'worker_pid':state['child_pid'],'helper_pid':marker['helper'],'anchor_pid':marker['anchor'],
        'cleanup':state['registered_helper_cleanup'],'kernel_calls':state['registered_helper_kernel_calls'],'scientific_calls':0},sort_keys=True))


def test_oversized_descriptor_is_still_refused_before_contract_or_socket(tmp_path,monkeypatch):
    descriptor=tmp_path/'descriptor.json';descriptor.write_bytes(b'{"pad":"'+b'x'*65536+b'"}')
    monkeypatch.setenv(r.ENV,str(descriptor));monkeypatch.setenv(r.KEY_ENV,'preparation')
    monkeypatch.setattr(r,'read_contract',lambda *args:pytest.fail('Contract reached before descriptor refusal'))
    monkeypatch.setattr(r.socket,'socket',lambda *args,**kwargs:pytest.fail('Socket reached before descriptor refusal'))
    with pytest.raises(ValueError,match='metadata byte ceiling'):r.bootstrap(tmp_path/'request.json',time.monotonic()+2.)


def test_resource_contract_cap_does_not_expand_control_or_registry(tmp_path):
    owner,observer,request=b.fixture(tmp_path)
    try:
        bounds=r.resource_bounds(owner.declaration)
        assert bounds['maximum_contract_request_bytes']==8*1024**2
        assert bounds['maximum_event_bytes']==65536
        assert bounds['maximum_discovery_message_bytes']==4096
        assert bounds['owner_output_bytes']==1048576
    finally:owner.close()


# Engineering dispatch runs outside any inherited agent session.
pytestmark = pytest.mark.usefixtures("engineering_session")
