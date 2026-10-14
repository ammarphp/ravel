"""Actual small SFitter producer packet through checked shared admission, no engines."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from ravel.workflow import sfitter_conductor as conductor, review_context, agent_graph as graph
from ravel.workflow import research_cycle as cycle, scientific_context_followup as followup, agent_host
from ravel.workflow.state_io import atomic_json
from test_sfitter_conductor import fixture, proposal, SuppliedHost


def test_actual_small_sfitter_producer_target_and_common_authorization(tmp_path,monkeypatch):
    request,docs,request_pin=fixture(tmp_path)
    context_pin=conductor.prepare(request_pin,tmp_path,tmp_path/'context')
    context=json.loads(Path(context_pin['path']).read_bytes())
    assert 'target' in context and 'target_sha256' not in context
    packet=conductor.prepare_lead_packet(context_pin,tmp_path,tmp_path/'packet')
    manifest=review_context.verify_packet(packet['path'],expected_manifest_sha256=packet['manifest_sha256'])
    core_row=next(r for r in manifest['artifacts'] if r['id']=='public_case')
    core=json.loads((Path(packet['path'])/core_row['path']).read_bytes())
    assert core['context']['target']==request['target'] and 'target_sha256' not in core['context']
    selection={'input_id':manifest['inputs'][0]['id'],'offset':0,'max_bytes':65536}
    value=proposal(request,context['phase'],'request_context');value['documentation_markdown']='';value['context_pages']=[selection]
    assert value['target_sha256']==graph.digest(core['context']['target'])
    spec=conductor.lead_graph(context_pin,tmp_path,graph_id='actual_small_target',model=request['model'],max_wall_seconds=120,packet_pin=packet,max_context_reworks=1)
    root=tmp_path/'graph';graph.create(root,spec)
    assert graph.execute(root,SuppliedHost(value),workers=1)['complete']
    old,checkpoint=graph._load(root);ref=deepcopy(checkpoint['nodes']['sfitter_lead']['result']);pin=cycle._pin(root/ref['path'])
    revised=conductor.followup_context(root,context_pin,tmp_path,tmp_path/'followup')
    new,after=graph._load(root)
    assert new['budget']==old['budget'] and after['usage']==checkpoint['usage'] and after['started_epoch']==checkpoint['started_epoch']
    assert after['reworks']==1 and after['graph_revision']==1
    authorization=followup.authorize_revision(root,old,new,checkpoint,pin)
    assert authorization['kind']=='sfitter_conductor_proposal' and authorization['selected_pages']==1
    assert revised['execution_authorized'] is False and revised['physics_validated'] is False
    # Exercise the source-derived target comparison separately from the schema's
    # equivalent const guard. Only the schema validator is inertly bypassed here;
    # all real packet_capture, Host observation and prior-call guards remain live.
    saved=json.loads((root/ref['path']).read_bytes());saved['result']['value']['target_sha256']='a'*64
    atomic_json(root/ref['path'],saved)
    wrong=deepcopy(checkpoint);wrong['nodes']['sfitter_lead']['result']['sha256']=graph.digest(saved)
    wrong['nodes']['sfitter_lead']['result']['result_sha256']=graph.digest(saved['result'])
    wrong_pin=cycle._pin(root/ref['path'])
    monkeypatch.setattr(agent_host,'validate_public_result',lambda value,schema:value)
    with pytest.raises(ValueError,match='original phase/target'):
        followup.authorize_revision(root,old,new,wrong,wrong_pin)
