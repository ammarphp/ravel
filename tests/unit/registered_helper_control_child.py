"""Supplied sleep/marker ownership fixture. No old gates, ravel or scientific work."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def load(path):
    spec=importlib.util.spec_from_file_location("registration_fixture_module",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    kind,request_path=sys.argv[1:3]
    request=json.loads(Path(request_path).read_text())
    module=load(request["registration_source"]["path"])
    if kind=="--child":
        guard=module.bootstrap(request_path,float(os.environ[module.DEADLINE_ENV]))
        marker=Path(request["marker"])
        marker.write_text(json.dumps({"helper":os.getpid(),"anchor":guard.anchor,"proof":guard.proof}))
        action=request["action"]
        if action=="leader_loss":
            descendant=subprocess.Popen([sys.executable,__file__,"descendant",request_path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            Path(request["descendant"]).write_text(str(descendant.pid))
            time.sleep(.05);os._exit(17)
        if action=="anchor_loss":
            os.kill(guard.anchor,signal.SIGKILL);os.waitpid(guard.anchor,0)
            descendant=subprocess.Popen([sys.executable,__file__,"descendant",request_path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            Path(request["descendant"]).write_text(str(descendant.pid));time.sleep(.05);os._exit(29)
        if action in ("worker_loss_after_ack","owner_loss","timeout"):
            time.sleep(7.)
        guard.finish()
    elif kind=="descendant":
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        time.sleep(4.)
    elif kind=="worker":
        descriptor=json.loads(Path(os.environ[module.ENV]).read_text())
        env=os.environ.copy();env[module.KEY_ENV]="preparation";env[module.DEADLINE_ENV]=repr(min(time.monotonic()+5.,descriptor["deadline_monotonic"]))
        child=subprocess.Popen([sys.executable,__file__,"--child",request_path],env=env,
            start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        Path(request["helper_started"]).write_text(str(child.pid))
        if request["action"]=="preack_worker_loss":os._exit(19)
        if request["action"]=="worker_loss_after_ack":
            until=time.monotonic()+2.
            while not Path(request["marker"]).exists() and time.monotonic()<until:time.sleep(.005)
            os._exit(23)
        child.wait(timeout=8.)
        if child.returncode==0:module.wait_closed("preparation",time.monotonic()+1.)
        if request["action"] in ("worker_timeout","worker_timeout_ignore_term"):
            if request["action"]=="worker_timeout_ignore_term":signal.signal(signal.SIGTERM,signal.SIG_IGN)
            time.sleep(7.)
    elif kind=="owner":
        declaration={"schema_version":1,"registration_source":module.pin(request["registration_source"]["path"]),
            "helpers":[{"key":"preparation","interpreter_invocation":sys.executable,"interpreter_binary":module.binary_pin(Path(sys.executable).resolve()),"helper_source":module.pin(__file__),
                "request_root":str(Path(request_path).parent),"contract_sha256":module.digest(request)}],
            "ack_seconds":1.,"cleanup_seconds":3.,"max_helpers":1,"max_kernel_calls":4096,"max_total_bytes":1048576}
        owner=module.HelperOwner(declaration,Path(request_path).parent.parent/"registry",deadline=time.monotonic()+7.)
        env=os.environ.copy();env[module.ENV]=owner.descriptor_pin["path"]
        worker=subprocess.Popen([sys.executable,__file__,"worker",request_path],env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        owner.attach_worker(worker.pid)
        until=time.monotonic()+3.
        while not Path(request["marker"]).exists() and time.monotonic()<until:
            owner.service();time.sleep(.005)
        Path(request["worker_pid"]).write_text(str(worker.pid))
        if not Path(request["marker"]).exists():raise ValueError("Owned ACK fixture did not reach ACK")
        os._exit(31)  # Deliberate outer death: no Python finally/cleanup.
    else:raise ValueError("Unknown supplied control route")


if __name__=="__main__":main()
