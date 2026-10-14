"""Positive knowledge use through the existing source-construction operation."""
import json
from ravel.physics import native_construction
from ravel.workflow import physics_knowledge
from test_physics_knowledge import fixture,pin
from test_native_construction import setup


def test_retrieved_conflict_supports_real_construction_packet_without_new_runner(tmp_path):
    request,_,_=fixture(tmp_path)
    packet=physics_knowledge.retrieve(request,tmp_path)
    knowledge=tmp_path/'retrieved.json';knowledge.write_text(json.dumps(packet,allow_nan=False)+'\n')
    config_path,config=setup(tmp_path)
    # Knowledge is support, not permission to replace the routine's existing obligations.
    config['support_sources']=[{k:pin(knowledge)[k] for k in ('path','sha256')}|{'description':'Retrieved ordered-beam convention conflict; keep the complete source obligations and independent API/runtime qualification.'}]
    config_path.write_text(json.dumps(config)+'\n')
    out=native_construction.write_source_packet(config_path,tmp_path/'construction-packet.json')
    actual=json.loads((tmp_path/'construction-packet.json').read_text())
    restored=json.loads(actual['support_sources'][0]['text'])
    assert restored['contradictions'][0]['id']=='beam-conflict'
    assert restored['test_obligations'][0]['check']=='ordered-beam-prefactor'
    assert actual['obligations']==config['obligations']
    assert actual['target_routine']=='RAVEL_Unknown' and actual['reference_data_name']=='Unknown'
    assert not out['model_executed'] and not actual['execution_authorized'] and not actual['physics_validated']
