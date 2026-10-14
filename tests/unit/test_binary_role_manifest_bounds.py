"""Inert manifest consumption regressions; no model/native/provider invocation."""
from pathlib import Path
import hashlib
import pytest
from ravel.workflow import agent_host as host, agent_graph as graph
from ravel.workflow.state_io import atomic_json
from test_binary_role_evidence import packet, node, request

def deliver(root, n):
    graph.create(root, {'schema_version':1,'graph_id':'independent-inert',
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':256,
                  'max_wall_seconds':30,'max_reworks':0},'nodes':[n]})
    prepared=graph.prepare_external(root,n['id'])
    response=root.parent/'supplied-response.json'
    atomic_json(response, {'schema_version':1,'request_id':prepared['request_id'],
        'request_sha256':prepared['request_sha256'],'invocation_id':'NO-MODEL-SUPPLIED-CONTROL',
        'actor_id':'inert','observed_model':'inert','fresh_context':True,
        'parent_transcript_supplied':False,'value':{'status':'diagnostic-only'}})
    graph.deliver_external(root,n['id'],response)
    return prepared


@pytest.mark.parametrize('entrypoint',['host','graph'])
def test_oversize_manifest_is_refused_before_any_unbounded_text_open(tmp_path,monkeypatch,entrypoint):
    p=packet(tmp_path/'packet',{'raw':b'original'})
    path=Path(p['path'])/'manifest.json'
    # Actual oversized document; trailing JSON whitespace preserves canonical digest.
    with path.open('ab') as stream:stream.write(b' '*(16*1024**2+1))
    opens=[];original=Path.open
    def observed(path_,*args,**kwargs):
        if path_==path and kwargs.get('encoding')=='utf-8':opens.append({'encoding':'utf-8'})
        return original(path_,*args,**kwargs)
    monkeypatch.setattr(Path,'open',observed)
    with pytest.raises((ValueError,host.HostFailure),match='bounded ordinary'):
        if entrypoint=='host':host.AgentHost().prepare_model_context(node(p),request(node(p)))
        else:graph._artifact_checks(node(p))
    witness={'entrypoint':entrypoint,'manifest_bytes':path.stat().st_size,
        'declared_cap':16*1024**2,'unbounded_text_opens_before_refusal':opens,
        'eventually_refused':True,'native_provider_model_calls':0}
    atomic_json(tmp_path/'witness.json',witness)
    assert opens==[], 'manifest cap is enforced only after an unbounded initial JSON read'


def test_role_receipt_must_not_reread_late_oversize_manifest_unbounded(tmp_path,monkeypatch):
    subject=b'{"scope":"diagnostic-control"}'
    p=packet(tmp_path/'packet',{'judgment_request':subject})
    root=tmp_path/'graph';deliver(root,node(p))
    target=Path(p['path'])/'manifest.json'
    check=graph._artifact_checks
    def late(n):
        check(n)
        with target.open('ab') as stream:stream.write(b' '*(16*1024**2+1))
    monkeypatch.setattr(graph,'_artifact_checks',late)
    opens=[];original=Path.open
    def observed(path,*args,**kwargs):
        if path==target and kwargs.get('encoding')=='utf-8' and target.stat().st_size>16*1024**2:
            opens.append({'encoding':'utf-8','bytes':target.stat().st_size})
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',observed)
    outcome=None; refusal=None
    try:
        outcome=graph.role_receipt(root,'critic',expected_subject_sha256=hashlib.sha256(subject).hexdigest(),require_exact_subject=True)
    except (ValueError,host.HostFailure) as error:
        refusal=str(error)
    atomic_json(tmp_path/'witness.json',{'manifest_bytes':target.stat().st_size,'unbounded_oversize_opens':opens,
        'returned_receipt':outcome,'refusal':refusal,'provider_model_native_calls':0})
    assert opens==[], 'receipt rereads late oversize manifest after bounded initial custody'

