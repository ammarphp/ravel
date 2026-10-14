"""Source-native deterministic assembly and specialist custody, no SDK calls."""
import copy
import json
from pathlib import Path

import pytest
from ravel.workflow import sfitter_workflow as w, sfitter_conductor as c
from ravel.workflow import sfitter_source_context as t, agent_graph as g, agent_host as ah
from test_sfitter_assembly import complete_request
from test_sfitter_adapter import save
from test_sfitter_conductor import fixture, SuppliedHost


def assembly_case(tmp):
    request,docs,_=complete_request(tmp)
    baseline=w.assemble_datacard(request,tmp)
    extra=tmp/'declared-auxiliary';extra.mkdir()
    for i in range(140):request['sources'].append(save(extra/(str(i)+'.json'),{'finite_synthetic_source_row':i,'science_qualified':False}))
    rp=save(tmp/'request.json',request)
    cp=c.prepare(rp,tmp,tmp/'context')
    packet=c.prepare_lead_packet(cp,tmp,tmp/'assembly-packet',purpose='assembly')
    return request,rp,cp,packet,baseline


def test_complete_large_assembly_real_public_graph_tool_keeps_all_physical_values(tmp_path):
    request,rp,cp,packet,baseline=assembly_case(tmp_path)
    spec=w.assembly_graph(request,tmp_path,rp,source_packet=packet)
    assert len(spec['nodes'][0]['inputs'])==1 and spec['nodes'][0]['action']=='sfitter-assemble'
    root=tmp_path/'graph';g.create(root,spec)
    result=g.execute(root,ah.AgentHost(api_key='not-used'),workers=1)
    assert result['complete'] and result['usage']=={'calls':1,'reserved_output_tokens':0}
    saved=g._result(root,result['nodes']['assemble_native_card']['result'])['result']
    bundle=saved['value']
    assert bundle['datacard']==baseline['datacard'] and bundle['run_card']==baseline['run_card']
    assert bundle['semantic_manifest']==baseline['semantic_manifest'] and bundle['census']==baseline['census']
    assert all(pin in bundle['inputs'] for pin in request['sources'])
    assert not bundle['execution_authorized'] and bundle['native_parser_roundtrip']=='not_executed'
    # The packet adds no exemption from explicitly configured Host roots.
    from types import SimpleNamespace
    control=SimpleNamespace(cancelled=lambda:False,call=lambda a,k,r,fn:fn())
    node=spec['nodes'][0]
    with pytest.raises(ah.HostFailure):
        ah.AgentHost(api_key='not-used',bound_roots=[str(tmp_path)]).execute(node,
            {'request_id':'bounded_assembly','packet':packet,'input_artifacts':node['inputs']},control)


@pytest.mark.parametrize('change',['missing_source','changed_source','substituted_copy'])
def test_assembly_complete_original_and_copy_population_cannot_be_omitted_or_changed(tmp_path,change):
    request,rp,cp,packet,_=assembly_case(tmp_path)
    spec=w.assembly_graph(request,tmp_path,rp,source_packet=packet)
    pin=request['sources'][-1]
    if change=='missing_source':Path(pin['path']).unlink()
    elif change=='changed_source':Path(pin['path']).write_bytes(b'{}\n')
    else:
        manifest=json.loads((Path(packet['path'])/'manifest.json').read_bytes())
        entry=next(e for e in manifest['artifacts'] if e.get('source_path')==pin['path'])
        (Path(packet['path'])/entry['path']).write_bytes(b'{}\n')
    with pytest.raises((ValueError,g.GraphError,ah.HostFailure,OSError)):g._artifact_checks(spec['nodes'][0])


def test_specialist_packet_uses_ordinary_advisory_roles_then_fresh_lead_context(tmp_path):
    request,docs,rp=fixture(tmp_path)
    for i in range(140):request['sources'].append(save(tmp_path/('extra-'+str(i)+'.json'),{'synthetic_source_row':i}))
    rp=save(Path(rp['path']),request);cp=c.prepare(rp,tmp_path,tmp_path/'initial-context')
    packet=c.prepare_lead_packet(cp,tmp_path,tmp_path/'specialist-packet',purpose='specialist')
    spec=c.consultant_graph(request,tmp_path,rp,max_reworks=0,source_packet=packet)
    assert all(len(n['inputs'])==1 and n['role']=='designer' for n in spec['nodes'])
    root=tmp_path/'consultants';g.create(root,spec)
    host=SuppliedHost({'claims':['Explicit inert advisory response; no scientific acceptance.']})
    assert g.execute(root,host,workers=1)['complete']
    after=c.prepare(rp,tmp_path,tmp_path/'next-lead',consultations=root)
    context=json.loads(Path(after['path']).read_bytes())
    assert len(context['consultations'])==3 and all(r['review_authority'] is False for r in context['consultations'])
    assert g.status(root)['usage']['calls']==3 and not context['physics_validated']
