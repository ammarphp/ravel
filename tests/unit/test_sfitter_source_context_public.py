"""Public preparation and custody-selection claims; supplied software only."""
import json
from pathlib import Path

from ravel.workflow import sfitter_conductor as c, sfitter_application as a
from ravel.workflow import agent_graph as g, sfitter_source_context as t
from test_sfitter_conductor import fixture, proposal, SuppliedHost
from test_sfitter_adapter import pin


def test_public_production_selection_does_not_claim_deferred_content_was_presented(tmp_path):
    request, _, rp = fixture(tmp_path)
    cp = c.prepare(rp, tmp_path, tmp_path/'context')
    packet = c.prepare_lead_packet(cp, tmp_path, tmp_path/'packet')
    manifest = t.review_context.verify_packet(packet['path'], expected_manifest_sha256=packet['manifest_sha256'])
    selected = manifest['inputs'][-1]
    value = proposal(request, 'extraction', 'request_production')
    value['context_pages'] = []
    value['production'] = [{'operation':'madgraph_sm', 'reason':'Prospective input custody selection only.',
                            'artifact_input_ids':[selected['id']]}]
    spec = c.lead_graph(cp, tmp_path, graph_id='production_selection', model=request['model'],
                        max_wall_seconds=120, packet_pin=packet)
    root = tmp_path/'graph'; g.create(root, spec)
    assert g.execute(root, SuppliedHost(value), workers=1)['complete']
    c.adopt(root, cp, tmp_path, tmp_path/'adopted')
    result = a._production(pin(tmp_path/'adopted/adoption-receipt.json'), tmp_path, 0)
    assert result[4] == [selected['pin']]
    assert result[-1].selection_presentation == {
        'kind':'sfitter_production_input_presentation',
        'basis':'mandatory catalogue/core actually presented in the final lead call',
        'whole_input_content_presented_to_lead':False,
        'selection_is_not_scientific_approval':True}
    result[-1].finish()


def test_public_cli_prepares_exact_packet_then_bounded_lead(tmp_path, capsys):
    request, _, rp = fixture(tmp_path)
    cp = c.prepare(rp, tmp_path, tmp_path/'context')
    out = tmp_path/'packet'
    assert c.main(['packet','--input',cp['path'],'--output',str(out)]) == 0
    packet = json.loads(capsys.readouterr().out)
    assert packet['path'] == str(out)
    graph_path = tmp_path/'graph.json'
    assert c.main(['lead-graph','--input',cp['path'],'--output',str(graph_path),
        '--packet',packet['path'],'--manifest-sha256',packet['manifest_sha256'],
        '--model',request['model']['name'],'--reasoning-effort',request['model']['reasoning_effort'],
        '--max-output-tokens',str(request['model']['max_output_tokens']),
        '--max-context-reworks','1']) == 0
    spec = json.loads(graph_path.read_bytes())
    assert spec['nodes'][0]['packet'] == packet
    assert spec['nodes'][0]['inputs'] == [{'id':'input0',**cp}]
    assert spec['budget']['max_calls'] == 2 and spec['budget']['max_reworks'] == 1
    g.validate(spec)
