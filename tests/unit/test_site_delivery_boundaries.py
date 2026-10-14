"""Proposed inert source-origin controls; no author execution or native proof."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import root_stream as stream
from ravel.workflow import science,site_workflow as w,agent_host
from root_stream_fixture import pin,put
from test_site_workflow import workflow_fixture


def ordinary_fixture(root,monkeypatch,mode='root-stream',fault=None):
    rd=root/'study';out=rd/'outputs';out.mkdir(parents=True)
    put(rd,science.PLAN,{'synthetic':'inert lifecycle fixture'})
    value={'status':'passed','physics_validated':False}
    rp=put(out,'result.json',value)
    vp=put(out,'verification.json',{'passed':True,'scope':mode,'physics_validated':False,'expert_review':False,'result_sha256':rp['sha256']})
    calls=[];task={'config':{'path':'synthetic','sha256':'a'*64,'size':1}}
    @contextmanager
    def session(rd):yield object()
    monkeypatch.setattr(science,'root',lambda rd:Path(rd).absolute())
    monkeypatch.setattr(science,'_validation_scope',session)
    def plan(rd,approved=False,**kw):
        calls.append(('plan',approved))
        if approved and fault=='unapproved':raise ValueError('actual approval absent')
        return {'schema_version':2,'stages':[{'outputs':['outputs']}]}
    monkeypatch.setattr(science,'verify_plan',plan)
    def selected(*args,**kwargs):
        calls.append(('attempt',True))
        if fault=='no_attempt':raise ValueError('actual spent attempt absent')
        return {'outputs':['outputs']},{'fingerprint':'b'*64},10
    monkeypatch.setattr(science,'_selected',selected)
    monkeypatch.setattr(science,'execution_spec',lambda *a,**kw:{'mode':mode,'task':task})
    def waypoint(*args,**kwargs):
        calls.append(('launch_and_succeeded_census',True))
        if fault in ('failed','partial','stale_source','launch'):raise ValueError('original succeeded launch/current census absent')
        return [str(out/'result.json'),str(out/'verification.json')]
    monkeypatch.setattr(science,'review_waypoint_paths',waypoint)
    def complete(*args,**kwargs):
        calls.append(('completed_execution',True));return ['bad execution'] if fault=='record' else []
    monkeypatch.setattr(science.execution,'validate_completed_execution',complete)
    return rd,out,task,value,[rp,vp],calls


@pytest.mark.parametrize('fault',[None,'unapproved','no_attempt','failed','partial','stale_source','launch','record','result_binding','destination'])
def test_existing_successful_ordinary_authority_is_required_not_status_bits(tmp_path,monkeypatch,fault):
    rd,out,task,value,pins,calls=ordinary_fixture(tmp_path,monkeypatch,fault=fault)
    if fault=='result_binding':
        view=json.loads((out/'verification.json').read_text());view['result_sha256']='c'*64
        (out/'verification.json').write_bytes(stream.encoded(view))
    if fault is not None:
        with pytest.raises(ValueError):stream.ordinary_delivery(rd,expected_output=tmp_path/'wrong' if fault=='destination' else out,expected_task=task)
    else:
        proof=stream.ordinary_delivery(rd,expected_output=out,expected_task=task)
        assert proof['outputs']==pins and proof['result']==value
        assert proof['scientific_acceptance_inferred'] is False
        assert ('plan',True) in calls and ('attempt',True) in calls and ('completed_execution',True) in calls
        assert calls.count(('launch_and_succeeded_census',True))==2


@pytest.mark.parametrize('raw',[
 b'{"sample":"data","member":"data_file","start":0,"stop":4}\n',
 b'{"sample":"data","member":"data_file","start":0,"stop":2}\n{"sample":"data","member":"data_file","start":2,"stop":4}\n',
 b'\xff\x00private-ledger'])
def test_genuine_worker_private_ledger_and_packet_copy_refuse_before_decoding(tmp_path,monkeypatch,raw):
    rd,out,_,_,_,_=ordinary_fixture(tmp_path,monkeypatch)
    ledger=out/'root-stream/native/completed-intervals.jsonl';ledger.parent.mkdir(parents=True);ledger.write_bytes(raw)
    # Ordinary model path: the exact authenticated source, not an invented kind.
    if raw[:1]!=b'\xff':
        with pytest.raises(agent_host.HostFailure):
            agent_host.AgentHost()._context({'packet':None,'role':'lead'},{'request_id':'synthetic'}, {'ledger':(ledger,pin(ledger)['sha256'])})
    # Role copy has a harmless arbitrary name; classification follows original
    # source_path and source_sha256 before text/binary witness or catalogue.
    entry={'id':'ledger','source_path':str(ledger),'source_sha256':pin(ledger)['sha256'],'sha256':hashlib.sha256(raw).hexdigest()}
    class Index:
        def __init__(self,*args):self.entries={'ledger':entry};self.manifest={'role':'critic'}
        def read(self,row):return raw
        def finish(self):pytest.fail('restricted artifact must refuse before presentation')
    monkeypatch.setattr(agent_host.review_context,'_PacketIndex',Index)
    packet=tmp_path/'packet';packet.mkdir()
    with pytest.raises(agent_host.HostFailure):
        agent_host.AgentHost()._packet({'packet':{'path':str(packet),'manifest_sha256':'c'*64},'role':'critic'})


def test_original_allowed_public_context_remains_usable_without_private_census(tmp_path):
    text=json.dumps({'schema_version':1,'kind':'root-stream-source-context','allowed_regions':['CR','VR'],'data_values_or_sr_counts_presented':False})
    source=put(tmp_path,'public-context.json',text.encode())
    assert stream.model_input_text(text,source_path=source['path'],source_sha256=source['sha256'])==text


def test_never_run_counterfeit_marker_cannot_suppress_original_wms_attempt(tmp_path,monkeypatch):
    request,rd,_=workflow_fixture(tmp_path,monkeypatch)
    result=w.export(request,tmp_path,tmp_path/'export');folder=rd/'outputs';folder.mkdir()
    rp=put(folder,'result.json',{'status':'passed','physics_validated':False})
    vp=put(folder,'verification.json',{'passed':True,'physics_validated':False})
    stream.write_new(tmp_path/'export/completed/analyze.json',{'schema_version':1,'task':'analyze','export_sha256':result['manifest']['sha256'],'status':'delivered','outputs':[rp,vp],'scientific_acceptance_inferred':False})
    monkeypatch.setattr(science,'verify_plan',lambda *args,**kwargs:{'schema_version':2,'stages':[{'outputs':['outputs']}]})
    # No successful attempt token/record/output receipt exists. Prospective plan
    # preparation above is deliberately valid and cannot stand in for execution.
    with pytest.raises((ValueError,OSError,KeyError)):
        w.verify(result['manifest']['path'],result['manifest']['sha256'])


def test_statistical_origin_cannot_be_fabricated_by_self_consistent_files(tmp_path):
    out=tmp_path/'never-run/root-stream';out.mkdir(parents=True)
    with pytest.raises(ValueError):stream.ordinary_stream_delivery({'status':'passed'},out,{'config':{}})


@pytest.mark.parametrize('missing', ['removed','renamed','alias'])
@pytest.mark.parametrize('retained', [science.SPEC,science.EXECUTION_TASK,science.REVIEW_POLICY])
def test_missing_original_plan_private_source_and_role_copy_do_not_become_external(tmp_path,monkeypatch,missing,retained):
    rd=tmp_path/'study';out=rd/'outputs/attempt-1/root-stream/native';out.mkdir(parents=True)
    put(rd,retained,{'schema_version':2,'mode':'root-stream','source':'retained original software fixture'})
    plan=rd/science.PLAN;plan.parent.mkdir(exist_ok=True)
    if missing=='renamed':put(rd,science.PLAN+'.retained',{'retained':'original'})
    elif missing=='alias':plan.symlink_to(rd/'missing-original-plan')
    raw=b'{"sample":"data","member":"data_file","start":0,"stop":2}\n{"sample":"data","member":"data_file","start":2,"stop":4}\n'
    ledger=out/'completed-intervals.jsonl';ledger.write_bytes(raw)
    with pytest.raises(ValueError):stream.model_artifact_source(ledger,pin(ledger)['sha256'])
    with pytest.raises(agent_host.HostFailure):
        agent_host.AgentHost()._context({'packet':None,'role':'lead'},{'request_id':'synthetic'}, {'ledger':(ledger,pin(ledger)['sha256'])})
    entry={'id':'ledger','source_path':str(ledger),'source_sha256':pin(ledger)['sha256'],'sha256':hashlib.sha256(raw).hexdigest()}
    class Index:
        def __init__(self,*args):self.entries={'ledger':entry};self.manifest={'role':'critic'}
        def read(self,row):return raw
        def finish(self):pytest.fail('missing authority must refuse before presentation')
    monkeypatch.setattr(agent_host.review_context,'_PacketIndex',Index)
    packet=tmp_path/'packet';packet.mkdir()
    with pytest.raises(agent_host.HostFailure):
        agent_host.AgentHost()._packet({'packet':{'path':str(packet),'manifest_sha256':'c'*64},'role':'critic'})
