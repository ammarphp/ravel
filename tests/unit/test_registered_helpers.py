"""Portable ownership controls; Darwin live controls are explicitly marked."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import pytest


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


from ravel.workflow import helper_registration as registration
SOURCE=Path(registration.__file__).resolve()
CHILD=Path(__file__).with_name("registered_helper_control_child.py").resolve()
BINARY=registration.binary_pin(Path(sys.executable).resolve())


def identity(pid,ppid=None,pgid=None,uniqueid=None):
    return {"pid":pid,"ppid":ppid or os.getpid(),"pgid":pgid or pid,"uid":os.getuid(),
        "session":pgid or pid,"uniqueid":uniqueid or pid*10,"parent_uniqueid":(ppid or os.getpid())*10,
        "idversion":1,"start_sec":1,"start_usec":1}


class Observer:
    def __init__(self):self.calls=0;self.rows={os.getpid():identity(os.getpid())};self.groups={};self.arg={};self.fail_group=set()
    def identity(self,pid):self.calls+=1;return self.rows.get(pid)
    def argv(self,pid):self.calls+=1;return self.arg[pid]
    def image(self,pid):self.calls+=1;return str(Path(sys.executable).resolve())
    def group(self,gid):
        self.calls+=1
        if gid in self.fail_group:raise TimeoutError("Supplied late-query timeout")
        return self.groups.get(gid,[])


class Connection:
    def __init__(self,pid):self.pid=pid;self.sent=[];self.closed=False
    def sendall(self,value):self.sent.append(value)
    def close(self):self.closed=True
    def recv(self,n):return b"READY\n"


def fixture(tmp_path):
    request=tmp_path/"gate/request.json";request.parent.mkdir()
    request.write_bytes(registration.compact({"literal":"metadata"}))
    contract={"boundary_source":registration.pin(CHILD),"old_runtime":{"interpreter_invocation":sys.executable,"interpreter_binary":BINARY},"literal":"metadata"}
    declaration=registration.declaration(contract,{"preparation":request.parent})
    declaration["helpers"][0]["contract_sha256"]=registration.digest(json.loads(request.read_text()))
    obs=Observer();owner=registration.HelperOwner(declaration,tmp_path/"registry",deadline=time.monotonic()+8.,observer=obs)
    obs.rows[101]=identity(101);owner.attach_worker(101)
    obs.rows[102]=identity(102,101);obs.rows[103]=identity(103,102,102)
    obs.arg[102]=obs.arg[103]=[sys.executable,str(CHILD),"--child",str(request)]
    return owner,obs,request


def register(owner,monkeypatch):
    monkeypatch.setattr(registration,"peer_pid",lambda c:c.pid)
    deadline=time.monotonic()+5.
    a,b=Connection(102),Connection(103)
    for kind,c in (("helper",a),("anchor",b)):
        owner._receive(c,{"kind":kind,"key":"preparation","nonce":owner.nonce,"deadline_monotonic":deadline})
    assert not a.sent and len(b.sent)==1
    with monkeypatch.context() as patch:
        patch.setattr(registration.select,"select",lambda rows,*args:([b],[],[]) if rows==[b] else ([],[],[]))
        owner.service()
    return a,b


def test_independent_roles_durable_proof_before_ack(tmp_path,monkeypatch):
    owner,obs,_=fixture(tmp_path)
    try:
        a,b=register(owner,monkeypatch)
        assert len(a.sent)==len(b.sent)==1
        ack=json.loads(a.sent[0]);assert json.loads(registration.checked(ack["proof"]))["event"]=="registered"
        assert owner.rows["preparation"]["helper"]["uniqueid"]!=owner.rows["preparation"]["anchor"]["uniqueid"]
    finally:owner.close()


@pytest.mark.parametrize("field,value",[("ppid",999),("parent_uniqueid",999),("pgid",999),("session",999),("uid",999)])
def test_wrong_live_relation_never_ack(tmp_path,monkeypatch,field,value):
    owner,obs,_=fixture(tmp_path);obs.rows[103][field]=value
    try:
        with pytest.raises(ValueError):register(owner,monkeypatch)
        assert not owner.rows
    finally:owner.close()


def test_fsync_failure_never_ack(tmp_path,monkeypatch):
    owner,_,_=fixture(tmp_path)
    try:
        monkeypatch.setattr(owner,"event",lambda *a:(_ for _ in ()).throw(OSError("supplied fsync")))
        with pytest.raises(OSError):register(owner,monkeypatch)
        assert not owner.rows
    finally:owner.close()


def test_no_active_poll_has_no_kernel_cost(tmp_path):
    owner,obs,_=fixture(tmp_path)
    try:
        before=obs.calls
        for _ in range(10):owner.service()
        assert obs.calls==before
    finally:owner.close()


def test_contract_drift_no_ack(tmp_path,monkeypatch):
    owner,_,request=fixture(tmp_path)
    try:
        request.write_text('{"literal":"changed"}')
        with pytest.raises(ValueError,match="contract/path"):register(owner,monkeypatch)
        assert not owner.rows
    finally:owner.close()


def test_equal_content_dotdot_route_refused_before_hash(tmp_path,monkeypatch):
    owner,obs,request=fixture(tmp_path)
    outside=tmp_path/"outside";outside.mkdir();(outside/"request.json").write_bytes(request.read_bytes())
    alias=str(request.parent/"../outside/request.json")
    obs.arg[102]=[sys.executable,str(CHILD),"--child",alias]
    try:
        monkeypatch.setattr(registration,"peer_pid",lambda c:c.pid)
        with pytest.raises(ValueError,match="canonical.*dotdot"):
            owner._receive(Connection(102),{"kind":"helper","key":"preparation","nonce":owner.nonce,"deadline_monotonic":time.monotonic()+5.})
        assert not owner.rows
    finally:owner.close()


def test_reused_generation_not_signaled(tmp_path,monkeypatch):
    owner,obs,_=fixture(tmp_path);register(owner,monkeypatch)
    obs.groups[102]=[identity(102,101,102,999),identity(103,102,102,998)]
    signaled=[];monkeypatch.setattr(registration.os,"killpg",lambda *a:signaled.append(a))
    try:
        result=owner.cleanup()[0]
        assert result["requires_recovery"] and not signaled and result["remaining"]
        before=obs.calls
        for _ in range(10):owner.service()
        assert obs.calls==before and owner.rows["preparation"]["state"]=="recovery_required"
    finally:owner.close()
    assert obs.calls>before  # Final independently requested cleanup/census retained.


@pytest.mark.parametrize("leader",[None,"reused"])
def test_main_worker_absent_or_reused_never_signaled(tmp_path,monkeypatch,leader):
    owner,obs,_=fixture(tmp_path);register(owner,monkeypatch)
    obs.groups[102]=[obs.rows[102],obs.rows[103]]
    obs.groups[101]=[identity(104,101,101)]
    obs.rows[101]=None if leader is None else identity(101,uniqueid=99999)
    if leader is not None:obs.groups[101].append(obs.rows[101])
    signals=[]
    def kill(gid,sig):signals.append((gid,sig));obs.groups[gid]=[]
    monkeypatch.setattr(registration.os,"killpg",kill)
    class Proc:
        pid=101
        def poll(self):return 17
    try:
        known=owner.close()
        assert known[0]["signals"]==["SIGTERM"] and not known[0]["requires_recovery"]
        result=owner.cleanup_worker(Proc())
        assert result["requires_recovery"] and result["signals"]==[]
        assert all(gid!=101 for gid,sig in signals)
        assert result["remaining_group_members"]
    finally:owner.close()


def test_main_worker_no_escalation_after_generation_loss(tmp_path,monkeypatch):
    owner,obs,_=fixture(tmp_path);obs.groups[101]=[obs.rows[101],identity(104,101,101)]
    def kill(gid,sig):obs.rows[101]=None;obs.groups[101]=[identity(104,1,101)]
    monkeypatch.setattr(registration.os,"killpg",kill)
    class Proc:
        pid=101
        def poll(self):return 0
    try:
        result=owner.cleanup_worker(Proc())
        assert result["signals"]==["SIGTERM"] and result["requires_recovery"]
        assert any("absent/reused" in e["error"] for e in result["errors"])
    finally:owner.close()


def test_shared_cleanup_deadline_does_not_reset_for_worker(tmp_path,monkeypatch):
    owner,obs,_=fixture(tmp_path);owner.close()
    obs.groups[101]=[obs.rows[101]];signals=[]
    monkeypatch.setattr(registration.os,"killpg",lambda *a:signals.append(a))
    class Proc:
        pid=101
        def poll(self):return None
    with monkeypatch.context() as patch:
        patch.setattr(registration.time,"monotonic",lambda:owner.cleanup_deadline+.1)
        result=owner.cleanup_worker(Proc())
        assert result["requires_recovery"] and not signals and result["remaining_group_members"] is None


def test_query_and_publication_failure_continue_known_cleanup(tmp_path,monkeypatch):
    owner,obs,_=fixture(tmp_path);register(owner,monkeypatch)
    # Inject two retained groups to test error isolation (production refuses overlap).
    owner.rows["other"]={"helper":identity(202),"anchor":identity(203,202,202),"state":"registered","deadline":time.monotonic()+5,"connections":(Connection(202),Connection(203))}
    obs.rows[202]=identity(202);obs.rows[203]=identity(203,202,202)
    obs.groups[202]=[obs.rows[202],obs.rows[203]];obs.fail_group.add(102)
    def kill(gid,sig):obs.groups[gid]=[]
    monkeypatch.setattr(registration.os,"killpg",kill)
    monkeypatch.setattr(owner,"event",lambda *a:(_ for _ in ()).throw(OSError("supplied publication")))
    try:
        result=owner.cleanup();assert result[0]["requires_recovery"] and result[0]["remaining"] is None
        assert result[1]["signals"]==["SIGTERM"] and result[1]["requires_recovery"] is False
    finally:owner.close()


def test_unregistered_bootstrap_has_no_fallback(tmp_path,monkeypatch):
    monkeypatch.delenv(registration.ENV,raising=False)
    with pytest.raises(ValueError,match="no standalone"):registration.bootstrap(tmp_path/"request.json",time.monotonic()+2)


def test_source_drift_and_nonmutable_stage_declaration(tmp_path,monkeypatch):
    owner,obs,request=fixture(tmp_path)
    try:
        public=owner.declaration;public["helpers"][0]["contract_sha256"]="0"*64
        assert owner.declaration["helpers"][0]["contract_sha256"]!=public["helpers"][0]["contract_sha256"]
        with pytest.raises(ValueError,match="source custody"):
            registration.checked({"path":str(CHILD),"sha256":"0"*64})
        assert not owner.rows
    finally:owner.close()


def test_spoofed_argv_wrong_actual_image_no_ack(tmp_path,monkeypatch):
    owner,obs,_=fixture(tmp_path)
    try:
        monkeypatch.setattr(obs,"image",lambda pid:"/unapproved/other-python")
        with pytest.raises(ValueError,match="vnode image"):
            register(owner,monkeypatch)
        assert not owner.rows
    finally:owner.close()


def test_malformed_discovery_preserves_known_cleanup(tmp_path,monkeypatch):
    owner,obs,_=fixture(tmp_path);register(owner,monkeypatch)
    obs.groups[102]=[obs.rows[102],obs.rows[103]]
    monkeypatch.setattr(registration.select,"select",lambda *a:([],[],[]))
    monkeypatch.setattr(registration.os,"killpg",lambda gid,sig:obs.groups.__setitem__(gid,[]))
    c=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);c.connect(str(owner.socket_path));c.sendall(b"x"*(registration.MAX_MESSAGE+1))
    try:
        owner.service();assert any("byte ceiling" in e["error"] for e in owner.errors)
        result=owner.close();assert result[0]["signals"]==["SIGTERM"] and not result[0]["requires_recovery"]
    finally:c.close();owner.close()


def test_late_query_timeout_has_global_reserve_and_other_group(tmp_path,monkeypatch):
    owner,obs,_=fixture(tmp_path);register(owner,monkeypatch)
    owner.rows["other"]={"helper":identity(202),"anchor":identity(203,202,202),"state":"registered","deadline":time.monotonic()+5,"connections":(Connection(202),Connection(203))}
    obs.rows[202]=identity(202);obs.rows[203]=identity(203,202,202);obs.groups[202]=[obs.rows[202],obs.rows[203]]
    clock=[time.monotonic()]
    original=obs.group
    def group(gid):
        if gid==102:clock[0]+=.45;raise TimeoutError("Supplied bounded late query timeout")
        return original(gid)
    with monkeypatch.context() as patch:
        patch.setattr(registration.time,"monotonic",lambda:clock[0]);patch.setattr(obs,"group",group)
        patch.setattr(registration.os,"killpg",lambda gid,sig:obs.groups.__setitem__(gid,[]))
        result=owner.cleanup()
        assert result[0]["remaining"] is None and result[0]["requires_recovery"]
        assert result[1]["signals"]==["SIGTERM"] and not result[1]["requires_recovery"]
    owner.close()


def test_full_or_failed_kernel_census_never_empty():
    import ctypes
    class Library:
        def proc_listpids(self,*a):ctypes.set_errno(5);return 0
    observer=registration.KernelObserver.__new__(registration.KernelObserver);observer.calls=0;observer.max_calls=4096;observer.lib=Library()
    with pytest.raises(OSError,match="not empty"):observer.group(100)
    observer.lib.proc_listpids=lambda *a:16388
    with pytest.raises(ValueError,match="overflow"):observer.group(100)


def test_coalesced_ack_release_framing():
    class C:
        def __init__(self):self.n=0
        def settimeout(self,t):pass
        def recv(self,n):self.n+=1;return b"ACK\nRELEASE\n"
    c=C();deadline=time.monotonic()+1.
    assert registration._recv_line(c,deadline)==b"ACK" and registration._recv_line(c,deadline)==b"RELEASE" and c.n==1


@pytest.mark.parametrize("name,value",[("ack_seconds",True),("max_helpers",True),("max_total_bytes",True),("schema_version",True)])
def test_strict_closed_resource_selector(tmp_path,name,value):
    owner,_,_=fixture(tmp_path)
    try:
        d=owner.declaration;d[name]=value
        with pytest.raises(ValueError):registration.validate_declaration(d)
    finally:owner.close()


def test_publication_ceiling_before_write(tmp_path):
    (tmp_path/"already.bin").write_bytes(b"x"*(registration.MAX_TOTAL_BYTES-3))
    with pytest.raises(ValueError,match="aggregate"):registration.publish(tmp_path/"attempt.json",{"large":"small"})
    assert not (tmp_path/"attempt.json").exists() and not (tmp_path/"attempt.json.partial").exists()


def test_pure_declaration_and_explicit_resource_budget(tmp_path):
    contract={"boundary_source":registration.pin(CHILD),"old_runtime":{"interpreter_invocation":sys.executable,"interpreter_binary":BINARY}}
    future=tmp_path/"not-created"
    d=registration.declaration(contract,{"initial":future/"initial","final":future/"final"})
    assert not future.exists()
    assert d["helpers"][0]["interpreter_binary"]==BINARY
    bounds=registration.resource_bounds(d)
    assert bounds["peak_processes"]==5 and bounds["helper_launches"]==bounds["anchor_forks"]==2
    assert bounds["total_process_launches_including_owner_worker"]==10 and bounds["owner_output_bytes"]==1048576


def test_absent_legacy_field_and_bootstrap_order(monkeypatch):
    import ast
    execution,_=overlay(monkeypatch)
    assert execution.helper_declaration_fields({"legacy":True})=={}
    tree=ast.parse(SOURCE.with_name("historical_qualification.py").read_text())
    main=tree.body[-1]
    calls=[(n.lineno,ast.unparse(n.func)) for n in ast.walk(main) if isinstance(n,ast.Call)]
    assert min(i for i,f in calls if f=="registration.bootstrap")<min(i for i,f in calls if f=="_historical_child")


def test_historical_registered_resource_census():
    historical=load(SOURCE.with_name("historical_qualification.py"),"private_registered_historical_resource_control")
    bounds=historical.resource_bounds()
    assert bounds["maximum_processes_in_gate_tree"]==3
    assert bounds["peak_processes_including_calling_worker"]==4
    assert bounds["peak_processes_including_outer_supervisor"]==5
    assert bounds["maximum_process_launches_per_gate"]==4 and bounds["maximum_process_launches_per_worker"]==8
    assert bounds["worker_launches_including_worker_and_supervisor"]==10 and bounds["owner_registry_output_bytes"]==1048576
    assert bounds["owner_global_cleanup_seconds"]==3 and bounds["owner_kernel_observer_charges"]==4096
    assert bounds["ACK_roles_per_gate"]==2 and bounds["ACK_observer_charges_per_role"]==16
    assert bounds["maximum_captured_input_bytes"]==64*1024**2


@pytest.mark.skipif(sys.platform!="darwin",reason="Requires admitted Darwin live unique identity ABI")
@pytest.mark.parametrize("action",["normal","leader_loss","worker_loss_after_ack","preack_worker_loss","anchor_loss"])
def test_live_owned_lifecycle(tmp_path,action):
    request=tmp_path/"gate/request.json";request.parent.mkdir()
    body={"registration_source":registration.pin(SOURCE),"marker":str(tmp_path/"after-ack.json"),"action":action,
        "descendant":str(tmp_path/"descendant.pid"),"helper_started":str(tmp_path/"helper.pid")}
    request.write_bytes(registration.compact(body))
    declaration={"schema_version":1,"registration_source":registration.pin(SOURCE),"helpers":[{"key":"preparation",
        "interpreter_invocation":sys.executable,"interpreter_binary":BINARY,"helper_source":registration.pin(CHILD),"request_root":str(request.parent),
        "contract_sha256":registration.digest(body)}],"ack_seconds":1.,"cleanup_seconds":3.,"max_helpers":1,"max_kernel_calls":4096,"max_total_bytes":1048576}
    owner=registration.HelperOwner(declaration,tmp_path/"registry",deadline=time.monotonic()+7.)
    env=os.environ.copy();env[registration.ENV]=owner.descriptor_pin["path"]
    worker=subprocess.Popen([sys.executable,str(CHILD),"worker",str(request)],env=env,start_new_session=True,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    owner.attach_worker(worker.pid);result=[]
    try:
        until=time.monotonic()+7.
        while worker.poll() is None and time.monotonic()<until:
            owner.service();time.sleep(.005)
        if worker.poll() is None:raise AssertionError("Owned fixture exceeded declared7s")
        result=owner.close();worker.wait(timeout=1.)
        started=Path(body["helper_started"])
        if started.exists():
            gid=int(started.read_text());until=time.monotonic()+(4.5 if action=="anchor_loss" else 1.5)
            while owner.observer.group(gid) and time.monotonic()<until:time.sleep(.01)
            assert owner.observer.group(gid)==[]
        if action=="normal":
            assert worker.returncode==0 and (tmp_path/"registry/preparation-closed.json").is_file()
        if action=="preack_worker_loss":assert not Path(body["marker"]).exists()
        if action=="leader_loss":assert Path(body["descendant"]).is_file()
        if action=="anchor_loss":
            assert result and any(r["requires_recovery"] and not r["signals"] for r in result)
        else:assert not any(r["requires_recovery"] for r in result)
        assert owner.observer.calls<=4096
        print(json.dumps({"control":action,"worker":owner.worker,"registered":{
            k:{"helper":r["helper"],"anchor":r["anchor"],"state":r["state"]} for k,r in owner.rows.items()},
            "cleanup":result,"kernel_calls":owner.observer.calls,"errors":owner.errors},sort_keys=True))
    finally:
        if worker.poll() is None:worker.kill();worker.wait(timeout=1.)
        owner.close()


@pytest.mark.skipif(sys.platform!="darwin",reason="Requires admitted Darwin live unique identity ABI")
def test_owner_death_anchor_selfcleans_occupied_group(tmp_path):
    request=tmp_path/"gate/request.json";request.parent.mkdir()
    body={"registration_source":registration.pin(SOURCE),"marker":str(tmp_path/"after-ack.json"),"action":"owner_loss",
        "descendant":str(tmp_path/"descendant.pid"),"helper_started":str(tmp_path/"helper.pid"),"worker_pid":str(tmp_path/"worker.pid")}
    request.write_bytes(registration.compact(body))
    owner=subprocess.Popen([sys.executable,str(CHILD),"owner",str(request)],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    owner.wait(timeout=5.);assert owner.returncode==31
    marker=json.loads(Path(body["marker"]).read_text());worker=int(Path(body["worker_pid"]).read_text())
    obs=registration.KernelObserver(max_calls=4096);until=time.monotonic()+2.
    while (obs.group(marker["helper"]) or obs.identity(worker)) and time.monotonic()<until:time.sleep(.01)
    assert obs.group(marker["helper"])==[] and obs.identity(worker) is None
    descriptor=registration.read(tmp_path/"registry/descriptor.json")
    print(json.dumps({"control":"owner_loss","owner_pid":owner.pid,"helper_pid":marker["helper"],"anchor_pid":marker["anchor"],"worker_pid":worker,"final_group":[],"kernel_calls":obs.calls}))
    # Own fixture socket namespace survives abrupt owner exit as recovery evidence, then is removed.
    socket_path=Path(descriptor["socket"])
    assert not socket_path.is_symlink() and socket_path.parent.stat().st_uid==os.getuid()
    socket_path.unlink();socket_path.parent.rmdir()


@pytest.mark.skipif(sys.platform!="darwin",reason="Requires admitted Darwin live unique identity ABI")
def test_two_preack_peers_reap_after_worker_death(tmp_path):
    request=tmp_path/"gate/request.json";request.parent.mkdir()
    body={"registration_source":registration.pin(SOURCE),"marker":str(tmp_path/"after-ack.json"),"action":"normal",
        "descendant":str(tmp_path/"descendant.pid"),"helper_started":str(tmp_path/"helper.pid")}
    request.write_bytes(registration.compact(body))
    d={"schema_version":1,"registration_source":registration.pin(SOURCE),"helpers":[{"key":"preparation",
        "interpreter_invocation":sys.executable,"interpreter_binary":BINARY,"helper_source":registration.pin(CHILD),"request_root":str(request.parent),
        "contract_sha256":registration.digest(body)}],"ack_seconds":1.,"cleanup_seconds":3.,"max_helpers":1,"max_kernel_calls":4096,"max_total_bytes":1048576}
    owner=registration.HelperOwner(d,tmp_path/"registry",deadline=time.monotonic()+7.)
    env=os.environ.copy();env[registration.ENV]=owner.descriptor_pin["path"]
    worker=subprocess.Popen([sys.executable,str(CHILD),"worker",str(request)],env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    owner.attach_worker(worker.pid);peers=[]
    try:
        until=time.monotonic()+1.
        while len(peers)<2 and time.monotonic()<until:
            try:c,_=owner.listener.accept();peers.append(c)
            except BlockingIOError:time.sleep(.005)
        assert len(peers)==2
        observed=[owner.observer.identity(registration.peer_pid(c)) for c in peers]
        assert observed[0]["pid"]!=observed[1]["pid"]
        assert registration.generation(owner.observer.identity(worker.pid))==registration.generation(owner.worker)
        worker.kill();worker.wait(timeout=1.)
        for c in peers:c.close()
        owner.close();gid=int(Path(body["helper_started"]).read_text());until=time.monotonic()+1.5
        while owner.observer.group(gid) and time.monotonic()<until:time.sleep(.01)
        assert not owner.observer.group(gid) and not Path(body["marker"]).exists() and not owner.rows
        print(json.dumps({"control":"two_preack_worker_loss","observed_peers":observed,"final_group":[],"kernel_calls":owner.observer.calls}))
    finally:
        for c in peers:c.close()
        if worker.poll() is None:worker.kill();worker.wait(timeout=1.)
        owner.close()


def overlay(monkeypatch):
    from ravel.workflow import execution,stage_supervisor
    return execution,stage_supervisor


@pytest.mark.skipif(sys.platform!="darwin",reason="Requires admitted Darwin live unique identity ABI")
@pytest.mark.parametrize("action,expected",[("normal",0),("worker_loss_after_ack",23),("timeout",124),("worker_timeout",124),("worker_timeout_ignore_term",124)])
def test_copied_supervisor_all_exit_paths(tmp_path,monkeypatch,action,expected):
    execution,supervisor=overlay(monkeypatch)
    request=tmp_path/"gate/request.json";request.parent.mkdir()
    body={"registration_source":registration.pin(SOURCE),"marker":str(tmp_path/"after-ack.json"),"action":action,
        "descendant":str(tmp_path/"descendant.pid"),"helper_started":str(tmp_path/"helper.pid")}
    request.write_bytes(registration.compact(body))
    d={"schema_version":1,"registration_source":registration.pin(SOURCE),"helpers":[{"key":"preparation",
        "interpreter_invocation":sys.executable,"interpreter_binary":BINARY,"helper_source":registration.pin(CHILD),"request_root":str(request.parent),
        "contract_sha256":registration.digest(body)}],"ack_seconds":1.,"cleanup_seconds":3.,"max_helpers":1,"max_kernel_calls":4096,"max_total_bytes":1048576}
    run=tmp_path/"run";run.mkdir()
    code=supervisor.supervise("ownership_control",run,0,"logs/control.log",[sys.executable,str(CHILD),"worker",str(request)],
        inputs=[str(request)],outputs=[],kill_secs=2.,grace=.5,poll=.01,helper_declaration=d, _engineering_only=True)
    assert code==expected
    state=execution.load_execution(run)["stages"]["ownership_control"]
    assert state["helper_declaration"]==d and state["registered_helper_kernel_calls"]<=4096
    assert all(r["requires_recovery"] is False for r in state["registered_helper_cleanup"])
    if action in ("worker_timeout","worker_timeout_ignore_term"):
        assert state["cleanup"]["requires_recovery"] is False
        assert state["cleanup"]["signals"]==(["SIGTERM"] if action=="worker_timeout" else ["SIGTERM","SIGKILL"])
    marker=json.loads(Path(body["marker"]).read_text())
    assert registration.KernelObserver().group(marker["helper"])==[]
    print(json.dumps({"control":"supervisor_"+action,"code":code,"registered_helper_kernel_calls":state["registered_helper_kernel_calls"],"cleanup":state["registered_helper_cleanup"]}))


# Engineering dispatch runs outside any inherited agent session.
pytestmark = pytest.mark.usefixtures("engineering_session")
