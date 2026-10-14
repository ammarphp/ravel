"""Source-bound metadata helper registration. Stdlib only, no ravel imports.

Kernel socket peer PID is discovery at observation time, not connect-time identity.
The owner independently binds live generations/parent/group/source/argv before ACK.
"""
from pathlib import Path
import ctypes
import hashlib
import json
import math
import os
import select
import signal
import socket
import struct
import sys
import tempfile
import time
import uuid

ENV = "RAVEL_REGISTERED_HELPER_OWNER"
KEY_ENV = "RAVEL_REGISTERED_HELPER_KEY"
DEADLINE_ENV = "RAVEL_REGISTERED_HELPER_DEADLINE"
MAX_MESSAGE = 4096
MAX_EVENTS = 256
MAX_EVENT_BYTES = 65536
MAX_CONTRACT_BYTES = 8 * 1024**2  # Existing historical JSON input ceiling, separate from control records.
MAX_TOTAL_BYTES = 1024**2
MAX_REQUESTS = 16
MAX_GROUP_MEMBERS = 8
POLL = .025
ACK_SECONDS = 1.


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(compact(value)).hexdigest()


def ordinary(path):
    literal=os.fspath(path)
    path = Path(path)
    if (literal!=str(path) or ".." in path.parts or not path.is_absolute()
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise ValueError("Absolute canonical ordinary registration path required; no aliases/dotdot")
    return path


def pin(path):
    path = ordinary(path)
    with path.open("rb") as stream:
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError("Registration source/declaration1MiB ceiling")
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def checked(value):
    if set(value) != {"path", "sha256"}:
        raise ValueError("Registration source custody differs")
    with ordinary(value["path"]).open("rb") as stream:raw=stream.read(1024**2+1)
    if len(raw)>1024**2 or hashlib.sha256(raw).hexdigest()!=value["sha256"]:
        raise ValueError("Registration source custody differs")
    return raw


def binary_pin(path):
    """Known interpreter identity only; bounded64MiB/1MiB streaming, no loading."""
    path=ordinary(path);before=path.stat();sha=hashlib.sha256();total=0
    if before.st_size>64*1024**2:raise ValueError("Registration interpreter binary64MiB ceiling")
    with path.open("rb") as stream:
        while raw:=stream.read(1024**2):
            total+=len(raw)
            if total>64*1024**2:raise ValueError("Registration interpreter binary grew beyond ceiling")
            sha.update(raw)
    after=path.stat()
    if total!=before.st_size or (before.st_ino,before.st_mtime_ns,before.st_size)!=(after.st_ino,after.st_mtime_ns,after.st_size):
        raise ValueError("Registration interpreter binary changed during streaming")
    return {"path":str(path),"sha256":sha.hexdigest()}


def read(path):
    path = ordinary(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_EVENT_BYTES+1)
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError("Registration metadata byte ceiling")
    return json.loads(raw)


def read_contract(path):
    """Bounded prospective historical input; control records keep their smaller cap."""
    path = ordinary(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_CONTRACT_BYTES + 1)
    if len(raw) > MAX_CONTRACT_BYTES:
        raise ValueError("Registered contract request 8MiB input ceiling")
    return json.loads(raw)


def publish(path, value):
    path = ordinary(path)
    raw = compact(value)
    if len(raw) > MAX_EVENT_BYTES:
        raise ValueError("Registration event byte ceiling")
    if sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file())+len(raw)>MAX_TOTAL_BYTES:
        raise ValueError("Registration aggregate publication ceiling")
    tmp = path.with_name(path.name + ".partial")
    with tmp.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if path.exists():
        raise FileExistsError("Immutable registration publication already exists")
    tmp.rename(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return pin(path)


class _BSDInfo(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in ("flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid", "svuid", "svgid", "reserved")] + [
        ("comm", ctypes.c_char*16), ("name", ctypes.c_char*32)] + [
        (n, ctypes.c_uint32) for n in ("nfiles", "pgid", "jobc", "tdev", "tpgid")] + [
        ("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64)]


class _UniqueInfo(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8*16), ("uniqueid", ctypes.c_uint64), ("parent_uniqueid", ctypes.c_uint64),
                ("idversion", ctypes.c_int32), ("original_parent_version", ctypes.c_int32),
                ("reserved2", ctypes.c_uint64), ("reserved3", ctypes.c_uint64)]


class _BSDWithUnique(ctypes.Structure):
    _fields_ = [("bsd", _BSDInfo), ("unique", _UniqueInfo)]


class KernelObserver:
    """Darwin libproc with supported private BSD+unique flavor18 and sysctl.

    Exact returned ABI sizes are required; no ps-second or timestamp fallback.
    """
    def __init__(self, *, max_calls=4096):
        if sys.platform != "darwin":
            raise ValueError("This ownership backend is qualified only for Darwin")
        self.lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        if (ctypes.sizeof(_BSDInfo),ctypes.sizeof(_UniqueInfo),ctypes.sizeof(_BSDWithUnique))!=(136,56,192):
            raise ValueError("Required supported private Darwin BSD+unique ABI layout differs")
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.calls, self.max_calls = 0, max_calls
        self.lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_pidinfo.restype = ctypes.c_int
        self.lib.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_listpids.restype = ctypes.c_int
        self.lib.proc_pidpath.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32]
        self.lib.proc_pidpath.restype=ctypes.c_int
        self.libc.sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
        self.libc.sysctl.restype = ctypes.c_int
    def charge(self):
        self.calls += 1
        if self.calls > self.max_calls:
            raise ValueError("Registered ownership kernel observation ceiling")
    def identity(self, pid):
        if type(pid) is not int or pid <= 1: raise ValueError("Live ordinary PID required")
        self.charge(); combined = _BSDWithUnique()
        size = self.lib.proc_pidinfo(pid, 18, 0, ctypes.byref(combined), ctypes.sizeof(combined))
        if size == 0:
            if ctypes.get_errno() in (3,): return None
            raise OSError(ctypes.get_errno(), "Required BSD+unique process identity API unavailable; no timestamp fallback")
        if size != ctypes.sizeof(combined): raise ValueError("Short/unsupported combined unique process identity ABI")
        row,unique=combined.bsd,combined.unique
        if row.pid != pid or row.status == 5: return None
        if unique.uniqueid == 0: raise ValueError("Missing required kernel process unique ID")
        return {"pid": row.pid, "ppid": row.ppid, "pgid": row.pgid, "uid": row.uid,
                "start_sec": row.start_sec, "start_usec": row.start_usec, "session": os.getsid(pid),
                "uniqueid": unique.uniqueid, "parent_uniqueid": unique.parent_uniqueid, "idversion": unique.idversion}
    def argv(self, pid):
        self.charge(); mib=(ctypes.c_int*3)(1,49,pid); buf=ctypes.create_string_buffer(65536); size=ctypes.c_size_t(len(buf))
        if self.libc.sysctl(mib,3,buf,ctypes.byref(size),None,0) != 0:
            raise OSError(ctypes.get_errno(), "Bounded KERN_PROCARGS2 unavailable")
        if size.value>=len(buf) or size.value<5:raise ValueError("Observed argv buffer full/short; refusing incomplete census")
        raw=buf.raw[:size.value]; argc=struct.unpack_from("=i",raw)[0]
        if not 1 <= argc <= 32: raise ValueError("Bounded observed argv required")
        cursor=raw.index(b"\0",4)+1
        while cursor<len(raw) and raw[cursor]==0: cursor+=1
        result=[]
        for _ in range(argc):
            end=raw.index(b"\0",cursor);result.append(os.fsdecode(raw[cursor:end]));cursor=end+1
        return result
    def group(self, pgid):
        self.charge(); buf=(ctypes.c_int*4097)()
        ctypes.set_errno(0)
        n=self.lib.proc_listpids(2,pgid,buf,ctypes.sizeof(buf))
        if n<0 or (n==0 and ctypes.get_errno()):raise OSError(ctypes.get_errno(),"Registered group census failed; not empty")
        if n==0:return []
        if n%ctypes.sizeof(ctypes.c_int):raise ValueError("Partial process-list element census")
        if n >= ctypes.sizeof(buf): raise ValueError("Registered group census overflow")
        rows=[]
        for pid in buf[:n//ctypes.sizeof(ctypes.c_int)]:
            if pid>1:
                row=self.identity(pid)
                if row and row["pgid"]==pgid: rows.append(row)
        if len(rows)>MAX_GROUP_MEMBERS: raise ValueError("Registered group member ceiling")
        return rows
    def image(self,pid):
        # Actual p_textvp vnode path, not the mutable user-stack argv/prefix.
        self.charge();buf=ctypes.create_string_buffer(4096)
        n=self.lib.proc_pidpath(pid,buf,len(buf))
        if n<=0:raise OSError(ctypes.get_errno(),"Required bounded process vnode image unavailable")
        if n>=len(buf):raise ValueError("Process vnode image path buffer full")
        literal=os.fsdecode(buf.raw[:n].rstrip(b"\0"))
        if not Path(literal).is_absolute() or "\0" in literal:raise ValueError("Process vnode image path malformed")
        return str(Path(literal).resolve())


def generation(row):
    return None if row is None else {k:row[k] for k in ("pid","pgid","uid","uniqueid","idversion","session")}


def peer_pid(connection):
    if sys.platform != "darwin": raise ValueError("Darwin peer observation required")
    return struct.unpack("=i",connection.getsockopt(0,2,4))[0]  # XNU SOL_LOCAL/LOCAL_PEERPID


def validate_declaration(value):
    required={"schema_version","registration_source","helpers","ack_seconds","cleanup_seconds","max_helpers","max_kernel_calls","max_total_bytes"}
    if set(value)!=required or type(value["schema_version"]) is not int or value["schema_version"]!=1:
        raise ValueError("Closed source-bound helper declaration required")
    if (value["registration_source"]!=pin(Path(__file__).resolve())
            or type(value["ack_seconds"]) not in (int,float) or value["ack_seconds"]!=ACK_SECONDS
            or type(value["max_helpers"]) is not int or not 1<=value["max_helpers"]<=2
            or type(value["max_kernel_calls"]) is not int or value["max_kernel_calls"]!=4096
            or type(value["max_total_bytes"]) is not int or value["max_total_bytes"]!=MAX_TOTAL_BYTES
            or type(value["cleanup_seconds"]) not in (int,float) or not math.isfinite(value["cleanup_seconds"])
            or not 0<value["cleanup_seconds"]<=3):
        raise ValueError("Exact registered helper resource/source admission required")
    helpers=value["helpers"]
    if not isinstance(helpers,list) or len(helpers)!=value["max_helpers"]: raise ValueError("Exact helper ceiling/allowance required")
    seen=set()
    for r in helpers:
        if set(r)!={"key","interpreter_invocation","interpreter_binary","helper_source","request_root","contract_sha256"} or r["key"] in seen:
            raise ValueError("Closed distinct helper route required")
        if r["key"] not in ("initial","final","preparation"): raise ValueError("Unknown helper route")
        checked(r["helper_source"]);ordinary(r["request_root"])
        if (not Path(r["interpreter_invocation"]).is_absolute() or not Path(r["interpreter_invocation"]).is_file()
                or type(r["contract_sha256"]) is not str or len(r["contract_sha256"])!=64
                or any(c not in "0123456789abcdef" for c in r["contract_sha256"])):
            raise ValueError("Exact helper invocation/contract required")
        binary=r["interpreter_binary"]
        if (set(binary)!={"path","sha256"} or str(Path(r["interpreter_invocation"]).resolve())!=str(ordinary(binary["path"]))
                or type(binary["sha256"]) is not str or len(binary["sha256"])!=64
                or any(c not in "0123456789abcdef" for c in binary["sha256"])):
            raise ValueError("Exact helper resolved interpreter binary required")
        seen.add(r["key"])
    if seen not in ({"preparation"},{"initial","final"}):raise ValueError("Exact preparation or worker lifecycle routes required")
    return value


def declaration(contract,phase_roots,registration_source=None):
    """Pure source metadata hook: no reservations, directories, children or OS queries."""
    if set(phase_roots) not in ({"preparation"},{"initial","final"}):
        raise ValueError("Only preparation or exact initial/final registered lifecycle admitted")
    value={"schema_version":1,"registration_source":registration_source or pin(Path(__file__).resolve()),
        "helpers":[{"key":key,"interpreter_invocation":contract["old_runtime"]["interpreter_invocation"],
                    "interpreter_binary":dict(contract["old_runtime"]["interpreter_binary"]),
                    "helper_source":dict(contract["boundary_source"]),"request_root":str(ordinary(root)),
                    "contract_sha256":digest(contract)} for key,root in sorted(phase_roots.items())],
        "ack_seconds":ACK_SECONDS,"cleanup_seconds":3.,"max_helpers":len(phase_roots),
        "max_kernel_calls":4096,"max_total_bytes":MAX_TOTAL_BYTES}
    return validate_declaration(value)


def resource_bounds(value):
    validate_declaration(value);n=value["max_helpers"]
    return {"peak_processes":5,"helper_launches":n,"anchor_forks":n,"original_OS_query_launches":2*n,
        "total_process_launches_including_owner_worker":2+4*n,"gate_seconds":10.,"ack_seconds":1.,
        "global_owner_cleanup_seconds":value["cleanup_seconds"],"owner_output_bytes":MAX_TOTAL_BYTES,
        "owner_kernel_observer_charges":4096,"ACK_observer_charges_per_role":16,
        "ACK_roles":2*n,"unmetered_kernel_syscall_scope":"Each identity charge also invokes getsid; socket/select/read/fsync calls are separate bounded protocol work, not observer charges",
        "maximum_discovery_connections":MAX_REQUESTS+1,"maximum_processed_requests":MAX_REQUESTS,
        "maximum_discovery_message_bytes":MAX_MESSAGE,"maximum_event_bytes":MAX_EVENT_BYTES,
        "maximum_contract_request_bytes":MAX_CONTRACT_BYTES,
        "maximum_events":MAX_EVENTS,"maximum_group_members":MAX_GROUP_MEMBERS,
        "maximum_interpreter_stream_bytes_per_role":64*1024**2,"stream_chunk_bytes":1024**2,
        "ownership_scope":"Cooperative source-bound local children; live unique IDs and anchor guard, not atomic generation-addressed signaling or hostile-user sandbox"}


class HelperOwner:
    def __init__(self,declaration,directory,*,deadline,observer=None):
        validate_declaration(declaration)
        self.directory=ordinary(directory)
        self.directory.mkdir(parents=True,exist_ok=False)
        if type(deadline) not in (int,float) or not math.isfinite(deadline) or deadline<=time.monotonic():
            raise ValueError("Finite future owner deadline required")
        self._declaration=json.loads(compact(declaration));self.deadline=deadline;self.worker=None;self.rows={};self.connections={};self.pending={}
        self.connection_deadlines={}
        self.events=0;self.requests=0;self.errors=[];self.accepted_connections=0;self.discovery_exhausted=False
        self.observer=observer or KernelObserver(max_calls=declaration["max_kernel_calls"])
        self.socket_dir=Path(tempfile.mkdtemp(prefix="ravel-helper-",dir="/tmp")).resolve();self.socket_dir.chmod(0o700)
        self.namespace_identity=(self.socket_dir.stat().st_ino,self.socket_dir.stat().st_uid)
        self.socket_path=self.socket_dir/"s"
        self.listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            self.listener.bind(str(self.socket_path));self.socket_path.chmod(0o600);self.listener.listen(4);self.listener.setblocking(False)
            self.nonce=uuid.uuid4().hex
            self.descriptor={"schema_version":1,"socket":str(self.socket_path),"nonce":self.nonce,"owner":self.observer.identity(os.getpid()),
                             "declaration":self.declaration,"deadline_monotonic":deadline,"directory":str(self.directory)}
            self.descriptor_pin=publish(self.directory/"descriptor.json",self.descriptor)
            self.event("owner_started",{"descriptor":self.descriptor_pin})
        except BaseException:
            self.listener.close()
            if self.socket_path.exists() and not self.socket_path.is_symlink():self.socket_path.unlink()
            self.socket_dir.rmdir()
            raise
    @property
    def declaration(self):return json.loads(compact(self._declaration))
    def event(self,kind,data):
        self.events+=1
        if self.events>MAX_EVENTS: raise ValueError("Registration event count ceiling")
        value={"event":kind,"observed_monotonic":time.monotonic(),**data}
        if sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file())+len(compact(value))>MAX_TOTAL_BYTES:
            raise ValueError("Registration aggregate output ceiling")
        return publish(self.directory/(f"{self.events:04d}-{kind}.json"),value)
    def contained_event(self,kind,data):
        """Publication failure never erases known authority or skips other cleanup."""
        try:return self.event(kind,data)
        except BaseException as exc:
            self.errors.append({"operation":"publication","type":type(exc).__name__,"error":str(exc)})
            return None
    def attach_worker(self,pid):
        if self.worker is not None: raise ValueError("Worker already bound")
        row=self.observer.identity(pid)
        if (row is None or row["ppid"]!=os.getpid() or row["parent_uniqueid"]!=self.descriptor["owner"]["uniqueid"]
                or row["pgid"]!=pid or row["session"]!=pid):
            raise ValueError("Outer cannot prove its live direct worker generation/session")
        self.worker=row;self.event("worker_bound",{"worker":row})
    def _receive(self,conn,msg):
        self.requests+=1
        if self.requests>MAX_REQUESTS: raise ValueError("Registration discovery request ceiling")
        if set(msg)!={"kind","key","nonce","deadline_monotonic"} or msg["nonce"]!=self.nonce or msg["kind"] not in ("helper","anchor"):
            raise ValueError("Malformed/unknown registered helper discovery")
        checked(self.declaration["registration_source"])
        key=msg["key"];spec=next((r for r in self.declaration["helpers"] if r["key"]==key),None)
        if spec is None or key in self.rows: raise ValueError("Unplanned/repeated helper route")
        if any(r.get("state")!="closed" for r in self.rows.values()): raise ValueError("Overlapping helper groups forbidden")
        worker=self.observer.identity(self.worker["pid"]) if self.worker else None
        if worker is None or self.worker is None or generation(worker)!=generation(self.worker): raise ValueError("Owned worker generation disappeared/changed")
        peer=peer_pid(conn);row=self.observer.identity(peer)
        if row is None or row["uid"]!=worker["uid"]: raise ValueError("Unknown helper peer generation")
        if type(msg["deadline_monotonic"]) not in (int,float) or not math.isfinite(msg["deadline_monotonic"]) or not time.monotonic()<msg["deadline_monotonic"]<=min(self.deadline,time.monotonic()+10.):
            raise ValueError("Declared gate deadline differs")
        argv=self.observer.argv(peer)
        if len(argv)!=4 or argv[:3]!=[spec["interpreter_invocation"],spec["helper_source"]["path"],"--child"]:
            raise ValueError("Observed helper invocation differs from stage declaration")
        image=self.observer.image(peer)
        if image!=spec["interpreter_binary"]["path"]:
            raise ValueError("Observed helper executable vnode image differs from declared interpreter")
        if (generation(self.observer.identity(peer))!=generation(row)
                or binary_pin(spec["interpreter_binary"]["path"])!=spec["interpreter_binary"]):
            raise ValueError("Observed helper generation/interpreter binary custody differs")
        row["image_path"]=image
        request=ordinary(argv[3]);root=ordinary(spec["request_root"])
        if request.parent!=root or request.name!="request.json" or digest(read_contract(request))!=spec["contract_sha256"]:
            raise ValueError("Observed helper request contract/path differs")
        checked(spec["helper_source"])
        pending=self.pending.setdefault(key,{"deadline":time.monotonic()+ACK_SECONDS,"gate_deadline":msg["deadline_monotonic"]})
        if pending["gate_deadline"]!=msg["deadline_monotonic"]:raise ValueError("Helper/anchor gate deadlines differ")
        if msg["kind"] in pending: raise ValueError("Duplicate helper/anchor connection")
        pending[msg["kind"]]=(row,conn)
        if {"helper","anchor"}.issubset(pending):
            helper,hconn=pending["helper"];anchor,aconn=pending["anchor"]
            hnow=self.observer.identity(helper["pid"]);anow=self.observer.identity(anchor["pid"])
            if (generation(hnow)!=generation(helper) or generation(anow)!=generation(anchor)
                    or hnow["ppid"]!=worker["pid"] or hnow["parent_uniqueid"]!=worker["uniqueid"] or hnow["pgid"]!=hnow["pid"] or hnow["session"]!=hnow["pid"]
                    or anow["ppid"]!=hnow["pid"] or anow["parent_uniqueid"]!=hnow["uniqueid"] or anow["pgid"]!=hnow["pgid"] or anow["session"]!=hnow["session"]):
                raise ValueError("Independent helper/anchor worker relation differs")
            hnow["image_path"]=helper["image_path"];anow["image_path"]=anchor["image_path"]
            row={"helper":hnow,"anchor":anow,"state":"anchor_acked","deadline":pending["gate_deadline"],
                 "ack_deadline":pending["deadline"],"connections":(hconn,aconn)}
            proof=self.event("registered",{"key":key,"helper":hnow,"anchor":anow,"worker":worker,"request":pin(request),"declaration_sha256":digest(self.declaration)})
            self.rows[key]=row;del self.pending[key]
            ack={"status":"acknowledged","nonce":self.nonce,"key":key,"proof":proof}
            row["ack"]=ack
            self.event("anchor_ack_will_send",{"key":key,"proof":proof})
            aconn.sendall(compact(ack)+b"\n")
    def service(self):
        # Discovery and per-row work are error-contained independently of cleanup.
        while not self.discovery_exhausted:
            try: conn,_=self.listener.accept()
            except BlockingIOError: break
            self.accepted_connections+=1
            if self.accepted_connections>MAX_REQUESTS:
                conn.close();self.discovery_exhausted=True;self.listener.close()
                error={"type":"ValueError","error":"Registration connection ceiling exhausted"}
                self.errors.append(error);self.contained_event("discovery_refused",error);break
            conn.setblocking(False);self.connections[conn]=bytearray()
            self.connection_deadlines[conn]=min(self.deadline,time.monotonic()+ACK_SECONDS)
            if len(self.connections)>4:
                conn.close();self.connections.pop(conn,None);self.connection_deadlines.pop(conn,None)
        for conn,buf in list(self.connections.items()):
            try:
                if time.monotonic()>=self.connection_deadlines[conn]:raise TimeoutError("Discovery connection deadline")
                data=conn.recv(MAX_MESSAGE+1-len(buf))
                if not data:raise EOFError("Discovery peer ended before registration")
                buf.extend(data)
                if len(buf)>MAX_MESSAGE: raise ValueError("Registration discovery byte ceiling")
                if b"\n" not in buf: continue
                line,rest=bytes(buf).split(b"\n",1)
                if rest: raise ValueError("One registration message per connection required")
                self._receive(conn,json.loads(line));self.connections.pop(conn,None);self.connection_deadlines.pop(conn,None)
            except BlockingIOError: continue
            except BaseException as exc:
                error={"type":type(exc).__name__,"error":str(exc)};self.errors.append(error)
                self.contained_event("discovery_refused",error)
                conn.close();self.connections.pop(conn,None);self.connection_deadlines.pop(conn,None)
        for key,p in list(self.pending.items()):
            if time.monotonic()>=p["deadline"]:
                self.contained_event("registration_expired",{"key":key})
                for kind in ("helper","anchor"):
                    if kind in p:p[kind][1].close()
                del self.pending[key]
        for key,row in list(self.rows.items()):
            if row["state"] in ("closed","recovery_required"):continue
            hconn,aconn=row["connections"]
            try:
                if row["state"]=="anchor_acked":
                    if time.monotonic()>=row["ack_deadline"]:raise TimeoutError("Two-role ACK deadline exhausted")
                    ready,_,_=select.select([aconn],[],[],0)
                    if not ready:continue
                    if aconn.recv(MAX_MESSAGE+1)!=b"READY\n":raise ValueError("Anchor readiness/EOF differs")
                    if (generation(self.observer.identity(row["anchor"]["pid"]))!=generation(row["anchor"])
                            or generation(self.observer.identity(row["helper"]["pid"]))!=generation(row["helper"])
                            or generation(self.observer.identity(self.worker["pid"]))!=generation(self.worker)):
                        raise ValueError("Two-role readiness generation changed")
                    ready_pin=self.event("anchor_ready",{"key":key,"registered_proof":row["ack"]["proof"]})
                    ack={**row["ack"],"anchor_ready":ready_pin}
                    if time.monotonic()>=row["ack_deadline"]:raise TimeoutError("Two-role ACK deadline exhausted after proof serialization")
                    hconn.sendall(compact(ack)+b"\n");row["state"]="registered"
                readable,_,_=select.select([hconn],[],[],0)
                if readable:
                    data=hconn.recv(MAX_MESSAGE+1)
                    if data==b"DONE\n" and row["state"]=="registered":
                        members=self.observer.group(row["helper"]["pgid"])
                        if (not any(generation(m)==generation(row["anchor"]) for m in members)
                                or any(m["pid"] not in (row["helper"]["pid"],row["anchor"]["pid"]) for m in members)):
                            raise ValueError("Helper return lacks live anchor or has surviving work descendants")
                        aconn.sendall(b"RELEASE\n");row["state"]="releasing";hconn.sendall(b"REAP\n")
                    elif data==b"REAPED\n" and row["state"]=="releasing":
                        hconn.sendall(b"EXIT\n");row["state"]="exiting"
                    elif not data and row["state"]=="exiting":pass
                    else:raise ValueError("Helper state/EOF/closure message differs")
                if row["state"]=="exiting" and not self.observer.group(row["helper"]["pgid"]):
                    self.event("group_closed",{"key":key,"requires_recovery":False})
                    self._publish_closed(key,row)
                elif time.monotonic()>=row["deadline"]:
                    self.cleanup(key)
            except BaseException as exc:
                self.errors.append({"type":type(exc).__name__,"error":str(exc)})
                self.cleanup(key)
    def _publish_closed(self,key,row):
        publish(self.directory/(key+"-closed.json"),{"key":key,"nonce":self.nonce,
            "declaration_sha256":digest(self.declaration),"requires_recovery":False})
        row["state"]="closed"
        for conn in row["connections"]:conn.close()
    def cleanup(self,key=None):
        # One global reserve. A query/publication error never skips another known group.
        if not hasattr(self,"cleanup_deadline"):
            self.cleanup_deadline=time.monotonic()+self.declaration["cleanup_seconds"]
        deadline=self.cleanup_deadline
        signal_deadline=deadline-min(.1,self.declaration["cleanup_seconds"]/4)
        results=[]
        targets=[(n,r) for n,r in self.rows.items() if (key is None or n==key) and r["state"]!="closed"]
        for name,row in targets:
            result={"key":name,"signals":[],"errors":[],"requires_recovery":True}
            group=row["helper"]["pgid"]
            for sig in (signal.SIGTERM,signal.SIGKILL):
                if time.monotonic()>=signal_deadline:
                    result["errors"].append({"operation":"signal_deadline","error":"Cleanup reserve exhausted"});break
                try:
                    members=self.observer.group(group)
                    if not members:result["requires_recovery"]=False;break
                    known=[r for r in (row["helper"],row["anchor"]) if any(generation(m)==generation(r) for m in members)]
                    if not known:raise ValueError("No live retained group-generation basis; nothing signaled")
                    if not any(generation(self.observer.identity(r["pid"]))==generation(r) for r in known):
                        raise ValueError("Retained group generation changed before signal")
                    if time.monotonic()>=signal_deadline:raise TimeoutError("Cleanup signal deadline exhausted after observations")
                    os.killpg(group,sig);result["signals"].append(sig.name)
                    until=min(signal_deadline,time.monotonic()+.15)
                    while time.monotonic()<until:
                        if not self.observer.group(group):break
                        time.sleep(min(POLL,max(0,until-time.monotonic())))
                except BaseException as exc:
                    result["errors"].append({"operation":sig.name,"type":type(exc).__name__,"error":str(exc)})
                    # Preserve independent escalation opportunity; unknown identity is rechecked.
            try:
                if time.monotonic()>deadline:raise TimeoutError("Final census reserve exhausted")
                result["remaining"]=self.observer.group(group)
                result["requires_recovery"]=bool(result["remaining"])
            except BaseException as exc:
                result["errors"].append({"operation":"final_census","type":type(exc).__name__,"error":str(exc)})
                result["remaining"]=None;result["requires_recovery"]=True
            if result["requires_recovery"] is False:
                try:self._publish_closed(name,row)
                except BaseException as exc:
                    result["requires_recovery"]=True
                    result["errors"].append({"operation":"closure_publication","type":type(exc).__name__,"error":str(exc)})
            if result["requires_recovery"]:row["state"]="recovery_required"
            self.contained_event("cleanup",result);results.append(result)
            # Even if evidence persistence fails, the postACK anchor EOF self-cleanup applies.
            for conn in row["connections"]:conn.close()
        return results
    def cleanup_worker(self,proc):
        """Helper-enabled main group: no inherited numeric-PGID signal authority.

        A absent/reused leader cannot authorize signaling surviving unknown members.
        The same global reserve covers registered and main groups; legacy is separate.
        """
        if not hasattr(self,"cleanup_deadline"):
            self.cleanup_deadline=time.monotonic()+self.declaration["cleanup_seconds"]
        deadline=self.cleanup_deadline;signal_deadline=deadline-min(.1,self.declaration["cleanup_seconds"]/4)
        result={"process_group":proc.pid,"signals":[],"errors":[],"requires_recovery":True,
                "identity_basis":"fresh exact retained worker unique generation", "remaining_group_members":None}
        if self.worker is None or self.worker["pid"]!=proc.pid:
            result["errors"].append({"operation":"worker_admission","error":"No exact owned worker generation"})
            return result
        for sig in (signal.SIGTERM,signal.SIGKILL):
            try:
                if time.monotonic()>=signal_deadline:raise TimeoutError("Main worker cleanup signal reserve exhausted")
                members=self.observer.group(proc.pid)
                if not members:break
                if generation(self.observer.identity(proc.pid))!=generation(self.worker):
                    raise ValueError("Main worker absent/reused; unknown remaining members not signaled")
                if time.monotonic()>=signal_deadline:raise TimeoutError("Main worker cleanup deadline after identity checks")
                os.killpg(proc.pid,sig);result["signals"].append(sig.name)
                until=min(signal_deadline,time.monotonic()+.15)
                while time.monotonic()<until:
                    if not self.observer.group(proc.pid):break
                    time.sleep(min(POLL,max(0,until-time.monotonic())))
            except BaseException as exc:
                result["errors"].append({"operation":sig.name,"type":type(exc).__name__,"error":str(exc)})
                # Re-observe on the next step; absence/reuse never grants escalation.
        try:
            if time.monotonic()>deadline:raise TimeoutError("Main worker final census reserve exhausted")
            result["remaining_group_members"]=self.observer.group(proc.pid)
            result["requires_recovery"]=bool(result["remaining_group_members"])
            result["leader_returncode"]=proc.poll()
        except BaseException as exc:
            result["errors"].append({"operation":"worker_final_census","type":type(exc).__name__,"error":str(exc)})
            result["requires_recovery"]=True
        self.contained_event("worker_cleanup",result)
        return result
    def close(self):
        if hasattr(self,"close_results"):return self.close_results
        results=self.cleanup()
        for p in self.pending.values():
            for kind in ("helper","anchor"):
                if kind in p:p[kind][1].close()
        for c in self.connections:c.close()
        self.listener.close()
        # Remove only the still-exact private namespace; substituted/symlink paths are never removed.
        try:
            current=self.socket_dir.lstat()
            if self.socket_dir.is_symlink() or (current.st_ino,current.st_uid)!=self.namespace_identity:
                raise ValueError("Owner socket namespace identity changed")
            if self.socket_path.is_symlink():raise ValueError("Owner socket substituted")
            self.socket_path.unlink();self.socket_dir.rmdir()
        except BaseException as exc:
            self.errors.append({"operation":"namespace_cleanup","type":type(exc).__name__,"error":str(exc)})
        self.close_results=results
        return results


_receive_buffers = {}


def _recv_line(conn,deadline):
    data=bytearray(_receive_buffers.pop(conn,b""))
    while b"\n" not in data:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError("Registered helper acknowledgment deadline")
        conn.settimeout(remaining);part=conn.recv(MAX_MESSAGE+1-len(data))
        if not part:raise EOFError("Registered outer owner connection ended")
        data.extend(part)
        if len(data)>MAX_MESSAGE:raise ValueError("Registered helper response ceiling")
    line,rest=bytes(data).split(b"\n",1)
    if rest:_receive_buffers[conn]=rest
    return line


def bootstrap(request,gate_deadline):
    """Called before any old-context/source/OS-query work, with no ravel imports."""
    descriptor_path=os.environ.get(ENV);key=os.environ.get(KEY_ENV)
    if not descriptor_path or not key:raise ValueError("Owner-backed registered helper required; no standalone fallback")
    d=read(descriptor_path);validate_declaration(d["declaration"])
    spec=next((r for r in d["declaration"]["helpers"] if r["key"]==key),None)
    if spec is None:raise ValueError("Unplanned helper bootstrap route")
    request=ordinary(request)
    if (request.parent!=ordinary(spec["request_root"]) or request.name!="request.json"
            or digest(read_contract(request))!=spec["contract_sha256"]):raise ValueError("Bootstrap request differs from declared contract")
    if type(gate_deadline) not in (int,float) or not math.isfinite(gate_deadline):raise ValueError("Finite gate deadline required")
    if os.getpid()!=os.getpgid(0) or os.getsid(0)!=os.getpid():raise ValueError("Isolated helper session required")
    conn=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);conn.settimeout(ACK_SECONDS);conn.connect(d["socket"])
    stamp=time.monotonic();deadline=min(stamp+ACK_SECONDS,gate_deadline,d["deadline_monotonic"])
    conn.sendall(compact({"kind":"helper","key":key,"nonce":d["nonce"],"deadline_monotonic":gate_deadline})+b"\n")
    anchor=os.fork()
    if anchor==0:
        conn.close();aconn=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)  # Preserve live generation guard until release/KILL.
        acknowledged=False
        try:
            aconn.settimeout(max(.001,deadline-time.monotonic()));aconn.connect(d["socket"])
            aconn.sendall(compact({"kind":"anchor","key":key,"nonce":d["nonce"],"deadline_monotonic":gate_deadline})+b"\n")
            ack=json.loads(_recv_line(aconn,deadline))
            if ack["nonce"]!=d["nonce"] or ack["key"]!=key or ack["status"]!="acknowledged":raise ValueError("Anchor ACK identity differs")
            _check_ack(ack,aconn,d,key,request);acknowledged=True
            aconn.sendall(b"READY\n")
            message=_recv_line(aconn,gate_deadline+d["declaration"]["cleanup_seconds"])
            if message!=b"RELEASE":raise ValueError("Unknown anchor release")
            os._exit(0)
        except BaseException:
            if acknowledged:os.killpg(os.getpgrp(),signal.SIGKILL)
            os._exit(130)
    try:
        ack=json.loads(_recv_line(conn,deadline))
        if ack["nonce"]!=d["nonce"] or ack["key"]!=key or ack["status"]!="acknowledged":raise ValueError("Helper ACK identity differs")
        _check_ack(ack,conn,d,key,request)
        return RegisteredHelper(conn,anchor,gate_deadline,d,key,ack["proof"],ack["anchor_ready"])
    except BaseException:
        conn.close()
        try:os.kill(anchor,signal.SIGKILL)
        except ProcessLookupError:pass
        os.waitpid(anchor,0)
        raise


def _check_ack(ack,conn,d,key,request):
    # Socket PID is fresh discovery only; combined live kernel generation is required.
    observer=KernelObserver(max_calls=16)
    owner=observer.identity(peer_pid(conn))
    if generation(owner)!=generation(d["owner"]):raise ValueError("ACK owner generation differs")
    proof=json.loads(checked(ack["proof"]))
    if (proof["event"]!="registered" or proof["key"]!=key or proof["request"]!=pin(request)
            or proof["declaration_sha256"]!=digest(d["declaration"])):raise ValueError("ACK durable proof differs")
    role="helper" if proof["helper"]["pid"]==os.getpid() else "anchor"
    if generation(observer.identity(os.getpid()))!=generation(proof[role]):raise ValueError("ACK own generation differs")
    if role=="helper":
        ready=json.loads(checked(ack["anchor_ready"]))
        if ready["event"]!="anchor_ready" or ready["key"]!=key or ready["registered_proof"]!=ack["proof"]:
            raise ValueError("ACK two-role readiness proof differs")


class RegisteredHelper:
    def __init__(self,conn,anchor,deadline,descriptor,key,proof,ready_proof):self.conn,self.anchor,self.deadline,self.descriptor,self.key,self.proof,self.ready_proof=conn,anchor,deadline,descriptor,key,proof,ready_proof
    def finish(self):
        self.conn.sendall(b"DONE\n")
        if _recv_line(self.conn,self.deadline)!=b"REAP":raise ValueError("Owner did not request anchor reap")
        os.waitpid(self.anchor,0)
        self.conn.sendall(b"REAPED\n")
        if _recv_line(self.conn,self.deadline)!=b"EXIT":raise ValueError("Owner did not authorize isolated exit")
        self.conn.close()


def wait_closed(key,deadline):
    d=read(os.environ[ENV]);path=ordinary(d["directory"])/(key+"-closed.json")
    while time.monotonic()<deadline:
        if path.is_file():
            row=read(path)
            if row["key"]!=key or row["nonce"]!=d["nonce"] or row["requires_recovery"] is not False:raise ValueError("Registered group closure differs")
            return pin(path)
        time.sleep(POLL)
    raise TimeoutError("Registered helper group closure deadline")
