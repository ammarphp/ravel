"""Byte presentation, original custody and finite same-Graph rework controls."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from ravel.workflow import agent_graph as g, agent_host as ah, review_context as rc
from ravel.workflow import sfitter_conductor as c, sfitter_source_context as t
from test_sfitter_conductor import fixture, proposal, SuppliedHost
from test_sfitter_adapter import save


def setup(tmp, *, selections=None, reworks=1):
    wf,docs,rp=fixture(tmp)
    cp=c.prepare(rp,tmp,tmp/'context')
    packet=c.prepare_lead_packet(cp,tmp,tmp/'packet',selections=selections)
    spec=c.lead_graph(cp,tmp,graph_id='page_lead',model=wf['model'],max_wall_seconds=120,
                      packet_pin=packet,max_context_reworks=reworks)
    root=tmp/'graph';g.create(root,spec)
    return wf,docs,cp,packet,spec,root


def references(docs, manifest):
    refs=list(c.workflow._refs(docs['extraction']))
    mapping={r['pin']['path']:r for r in manifest['inputs']}
    selected=[]
    for pin in refs:
        row=mapping[pin['path']]
        item={'input_id':row['id'],'offset':0,'max_bytes':65536}
        if item not in selected:selected.append(item)
    assert 0<len(selected)<=32
    return selected


def test_request_pages_revises_same_graph_then_final_call_has_exact_full_handoff_sources(tmp_path):
    wf,docs,cp,packet,spec,root=setup(tmp_path)
    manifest=rc.verify_packet(packet['path'],expected_manifest_sha256=packet['manifest_sha256'])
    selections=references(docs,manifest)
    request=proposal(wf,'extraction','request_context');request['documentation_markdown']='';request['context_pages']=selections
    host=SuppliedHost(request);assert g.execute(root,host,workers=1)['complete']
    with pytest.raises(ValueError,match='followup_context'):c.adopt(root,cp,tmp_path,tmp_path/'early')
    before=g.status(root)
    result=c.followup_context(root,cp,tmp_path,tmp_path/'pages')
    after=g.status(root);new,_=g._load(root)
    assert after['instance_id']==before['instance_id'] and after['started_epoch']==before['started_epoch']
    assert after['usage']==before['usage'] and after['reworks']==1 and after['graph_revision']==1
    assert new['budget']==spec['budget'] and new['nodes'][0]['parameters']==spec['nodes'][0]['parameters']
    assert new['nodes'][0]['inputs']==spec['nodes'][0]['inputs']
    value=proposal(wf,'extraction',handoff=docs['extraction']);value['context_pages']=[]
    second=SuppliedHost(value);assert g.execute(root,second,workers=1)['complete']
    adopted=c.adopt(root,cp,tmp_path,tmp_path/'adopted')
    assert adopted['disposition']=='source_draft' and not adopted['review_approved']
    assert g.status(root)['usage']['calls']==2 and g.status(root)['usage']['reserved_output_tokens']==2*wf['model']['max_output_tokens']
    final=json.loads(second.requests[0]['input'][0]['content'])['review_packet']
    assert {'public_case',*[f'selected_page{i}' for i in range(len(selections))]}<=set(final['presentation']['inline_ids'])
    assert second.requests[0]['tools']==[] and not result['content_read_by_model']


@pytest.mark.parametrize('mutation',['original_changed','original_missing','copy_changed','catalogue_rebound','core_rebound'])
def test_original_and_copy_whole_population_is_current_at_direct_host_boundary(tmp_path,mutation):
    wf,docs,cp,packet,spec,root=setup(tmp_path)
    manifest=json.loads((Path(packet['path'])/'manifest.json').read_bytes())
    row=next(r for r in manifest['inputs'] if Path(r['pin']['path']).is_relative_to(tmp_path))
    assert Path(row['pin']['path']).is_relative_to(tmp_path)
    if mutation=='original_changed':Path(row['pin']['path']).write_bytes(b'changed')
    elif mutation=='original_missing':Path(row['pin']['path']).unlink()
    elif mutation=='copy_changed':(Path(packet['path'])/next(e['path'] for e in manifest['artifacts'] if e['id']==row['artifact_id'])).write_bytes(b'changed')
    else:
        if mutation=='catalogue_rebound':manifest['inputs'].pop()
        else:
            leaf=Path(packet['path'])/'artifacts/public_case.txt';value=json.loads(leaf.read_bytes());value['context']['target']['process']='foreign'
            leaf.write_bytes(t._raw(value));next(e for e in manifest['artifacts'] if e['id']=='public_case')['sha256']=hashlib.sha256(leaf.read_bytes()).hexdigest()
        manifest['sha256']=rc.execution.digest({k:v for k,v in manifest.items() if k!='sha256'})
        (Path(packet['path'])/'manifest.json').write_bytes(t._raw(manifest));spec['nodes'][0]['packet']['manifest_sha256']=manifest['sha256']
    with pytest.raises((ValueError,ah.HostFailure,OSError,KeyError)):
        SuppliedHost({})._packet(spec['nodes'][0])


def test_catalogue_and_partial_page_do_not_credit_whole_source(tmp_path):
    wf,docs,rp=fixture(tmp_path);cp=c.prepare(rp,tmp_path,tmp_path/'context')
    packet=c.prepare_lead_packet(cp,tmp_path,tmp_path/'packet')
    manifest=rc.verify_packet(packet['path'],expected_manifest_sha256=packet['manifest_sha256'])
    selections=references(docs,manifest)
    selections[0]['max_bytes']=1
    partial=c.prepare_lead_packet(cp,tmp_path,tmp_path/'partial',selections=selections)
    spec=c.lead_graph(cp,tmp_path,graph_id='partial',model=wf['model'],max_wall_seconds=120,packet_pin=partial)
    root=tmp_path/'graph';g.create(root,spec)
    value=proposal(wf,'extraction',handoff=docs['extraction']);value['context_pages']=[]
    assert g.execute(root,SuppliedHost(value),workers=1)['complete']
    with pytest.raises(ValueError,match='actually supplied'):c.adopt(root,cp,tmp_path,tmp_path/'adopt')


def test_actual_host_deferral_of_selected_page_is_not_successful_presentation(tmp_path):
    wf,docs,rp=fixture(tmp_path);cp=c.prepare(rp,tmp_path,tmp_path/'context')
    first=c.prepare_lead_packet(cp,tmp_path,tmp_path/'initial')
    manifest=rc.verify_packet(first['path'],expected_manifest_sha256=first['manifest_sha256'])
    packet=c.prepare_lead_packet(cp,tmp_path,tmp_path/'selected',selections=references(docs,manifest))
    spec=c.lead_graph(cp,tmp_path,graph_id='deferred',model=wf['model'],max_wall_seconds=120,packet_pin=packet)
    root=tmp_path/'graph';g.create(root,spec)
    value=proposal(wf,'extraction','unresolved');value['context_pages']=[]
    host=SuppliedHost(value)
    raw=(Path(packet['path'])/'artifacts/public_case.txt').read_text()
    host.max_request=4*len(ah._json_bytes({'id':'public_case','content':raw}))+1
    assert g.execute(root,host,workers=1)['complete']
    with pytest.raises(ValueError,match='actually be presented'):c.adopt(root,cp,tmp_path,tmp_path/'adopt')


def test_caps_raw_roles_and_byte_selection_stay_finite(tmp_path):
    wf,docs,cp,packet,spec,root=setup(tmp_path,reworks=0)
    bad=copy.deepcopy(spec);bad['nodes'][0]['inputs']=[{'id':str(i),**cp} for i in range(129)]
    with pytest.raises(g.GraphError):g.validate(bad)
    bad=copy.deepcopy(spec);bad['nodes'][0]['role']='critic';bad['nodes'][0]['inputs']=[]
    with pytest.raises(g.GraphError):g._artifact_checks(bad['nodes'][0])
    for selections in ([{'input_id':'absent','offset':0,'max_bytes':1}],
                       [{'input_id':'input1','offset':0,'max_bytes':65537}],
                       [{'input_id':'input1','offset':0,'max_bytes':1}]*33):
        with pytest.raises(ValueError):c.prepare_lead_packet(cp,tmp_path,tmp_path/'bad',selections=selections)
    with pytest.raises(ValueError,match='inline allowance'):c.prepare_lead_packet(cp,tmp_path,tmp_path/'too-small',max_request_bytes=1)
    value=proposal(wf,'extraction','request_context');value['documentation_markdown']='';value['context_pages']=[{'input_id':'input1','offset':0,'max_bytes':1}]
    assert g.execute(root,SuppliedHost(value),workers=1)['complete']
    with pytest.raises(ValueError,match='rework budget exhausted'):c.followup_context(root,cp,tmp_path,tmp_path/'pages')
