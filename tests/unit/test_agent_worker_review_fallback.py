"""The restricted unsandboxed reviewer fallback of the worker layer, using inert Python children only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import sys
from types import SimpleNamespace

import pytest

from test_agent_worker import result, setup, spec

FALLBACK={'kind':'restricted-unsandboxed','record':'review-sandbox-fallback-000001'}
FACTS={'toolbelt':{'tools':['read_file']},'review_sandbox_fallback':FALLBACK}
STUB={'id':'inert-stub','transport_kind':'stub'}


def child_code(marker=None):
    """An inert child: it records that it ran, then prints a final envelope."""
    return ("import json,pathlib\n"
            f"pathlib.Path({str(marker) if marker else 'scratch/ran'!r}).write_text('child ran')\n"
            f"print(json.dumps({{'final':{result()!r}}}))\n")


def launch_spec(code):
    return {'argv':[sys.executable,'-B','-c',code],'transport':dict(STUB)}


def no_sandbox(monkeypatch):
    from ravel.workflow import sandbox
    monkeypatch.setattr(sandbox,'available',lambda:None)
    return sandbox


def prepare_attempt(worker,run,s,descriptor,monkeypatch,*,available,controller=None):
    """Run ``launch`` up to the supervisor spawn, which is replaced; nothing but the attempt record is made."""
    from ravel.workflow import sandbox
    spawned=[]
    real=worker.subprocess.Popen
    def spawn(argv,**kwargs):
        if '-m' in argv and 'ravel.workflow.agent_worker' in argv:
            spawned.append(list(argv));return SimpleNamespace(pid=100)
        return real(argv,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(sandbox,'available',lambda:available)
        patch.setattr(worker.subprocess,'Popen',spawn)
        patch.setattr(worker,'_controller_inventory',lambda *a,**k:{'observed':{'equal':True,'tools':['read_file']}})
        reply=worker.launch(run,s,launch_spec=descriptor,wait=False,
                            **({'controller':controller} if controller is not None else {}))
    assert reply['status']=='running' and len(spawned)==1
    return worker._record(run,s['node_id'],s['attempt'])


def supervise_in_process(worker,run,s,monkeypatch):
    """Supervise the prepared attempt here, with the OS sandbox absent and its entry points guarded."""
    sandbox=no_sandbox(monkeypatch)
    def forbidden(*args,**kwargs):raise AssertionError('the OS sandbox was used on a host without one')
    monkeypatch.setattr(sandbox,'probe',forbidden)
    monkeypatch.setattr(sandbox,'command',forbidden)
    old=signal.getsignal(signal.SIGTERM)
    try:worker.supervise(run,s['node_id'],s['attempt'])
    finally:signal.signal(signal.SIGTERM,old)
    return worker.load_receipt(run,s['node_id'],s['attempt'])


def test_sandbox_fallback_accepts_only_the_declared_kind_with_a_record():
    from ravel.workflow import agent_worker as worker
    for controller in (None,{},{'review_sandbox_fallback':None},{'review_sandbox_fallback':{'kind':FALLBACK['kind']}},
                       {'review_sandbox_fallback':{'record':'r'}},
                       {'review_sandbox_fallback':{'kind':'another-kind','record':'r'}},
                       {'review_sandbox_fallback':{'kind':FALLBACK['kind'],'record':7}},
                       {'review_sandbox_fallback':[FALLBACK]},[FALLBACK]):
        assert worker._sandbox_fallback(controller) is None
    controller={'review_sandbox_fallback':{**FALLBACK,'not_enforced':['writable']}}
    kept=deepcopy(controller)
    found=worker._sandbox_fallback(controller)
    assert found==controller['review_sandbox_fallback']
    found['not_enforced'].append('network');found['kind']='changed'
    assert controller==kept


def test_without_the_fallback_a_host_lacking_the_sandbox_refuses_before_any_child(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);no_sandbox(monkeypatch)
    marker=tmp_path/'marker'
    r=worker.dispatch(run,spec(),launch_spec=launch_spec(child_code(marker)))
    assert r['status']=='refused' and r['failure']['code']=='sandbox_unavailable'
    assert not marker.exists() and worker.processes(run)==[]
    assert 'sandbox_fallback' not in worker._record(run,'worker',1)


def _inventory(worker,run,tmp_path,monkeypatch,controller):
    from ravel.controller import confine
    no_sandbox(monkeypatch)
    targets=[]
    def probe(role,target):
        targets.append((role,target));return {'equal':True,'tools':['read_file']}
    monkeypatch.setattr(confine,'probe',probe,raising=False)
    s=spec();ws=worker.materialize(run,s)
    descriptor=launch_spec('pass')
    environment={'PATH':'/usr/bin:/bin','HOME':str(ws/'scratch')}
    reply=worker._controller_inventory(run,ws,descriptor,controller,environment=environment)
    assert reply=={'observed':{'equal':True,'tools':['read_file']}} and len(targets)==1 and targets[0][0]=='worker'
    return targets[0][1]


def test_controller_inventory_under_the_fallback_is_unconfined_and_marks_the_probe(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    target=_inventory(worker,run,tmp_path,monkeypatch,deepcopy(FACTS))
    assert target['unsandboxed'] is True
    admitted=target['admitted']
    assert admitted['writable']=='unconfined' and admitted['network']=='unconfined'
    assert admitted['tools']==['read_file']
    assert admitted['env_names']==['HOME','PATH']


def test_controller_inventory_without_the_fallback_keeps_the_confined_sets(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    facts={'toolbelt':FACTS['toolbelt']}
    target=_inventory(worker,run,tmp_path,monkeypatch,facts)
    assert 'unsandboxed' not in target
    assert type(target['admitted']['writable']) is list and target['admitted']['writable']
    assert target['admitted']['network']!='unconfined' and target['admitted']['tools']==['read_file']


def test_fallback_record_is_stored_in_the_attempt_beside_the_launch(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);s=spec()
    record=prepare_attempt(worker,run,s,launch_spec(child_code()),monkeypatch,available=None,controller=deepcopy(FACTS))
    assert record['sandbox_fallback']==FALLBACK and record['launch']['status']=='started'
    assert record['launch']['descriptor_sha256']


def test_supervise_under_the_fallback_runs_the_child_without_the_os_sandbox(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);s=spec()
    prepare_attempt(worker,run,s,launch_spec(child_code()),monkeypatch,available=None,controller=deepcopy(FACTS))
    receipt=supervise_in_process(worker,run,s,monkeypatch)
    ws=worker.workspace(run,'worker',1)
    assert (ws/'scratch/ran').read_text()=='child ran'
    isolation=receipt['isolation']
    assert isolation['profile']=='cli-policy'
    assert isolation['evidence']['confirmed'] is False and isolation['evidence']['os_sandbox'] is None
    assert isolation['evidence']['fallback']=='restricted-unsandboxed'
    assert isolation['evidence']['record']==FALLBACK['record']
    assert isolation['sandbox_fallback']['kind']=='restricted-unsandboxed'
    assert isolation['sandbox_fallback']['record']==FALLBACK['record']
    assert 'refusal' not in json.dumps(receipt.get('failure') or {})
    assert all(p['verified_gone'] for p in worker.processes(run))


def test_supervise_without_a_recorded_fallback_refuses_and_starts_no_child(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);s=spec()
    record=prepare_attempt(worker,run,s,launch_spec(child_code()),monkeypatch,available='inert-test-seam')
    assert 'sandbox_fallback' not in record
    receipt=supervise_in_process(worker,run,s,monkeypatch)
    ws=worker.workspace(run,'worker',1)
    assert receipt['status']=='refused' and receipt['failure']['code']=='sandbox_unavailable'
    assert not (ws/'scratch/ran').exists()
    assert all(p['child_pgid'] is None and p['verified_gone'] for p in worker.processes(run))
