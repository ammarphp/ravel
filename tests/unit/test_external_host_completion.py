"""Engineering receipt controls; no actual model inference/physics execution."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest
from ravel.workflow import agent_graph as original, agent_host, review_context, langgraph_runtime
from ravel.workflow.state_io import atomic_json, read_json
from test_agent_graph import node, spec, external_node, external_response, role_packet

candidate=original


def source_pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


BOUND_SOURCES={'agent_graph':None,'agent_host':agent_host,'review_context':review_context,
               'langgraph_runtime':langgraph_runtime}


def old_host(tmp_path, module=original):
    """Separate source copies for every source the production identity binds."""
    identity=module._external_identity();files={}
    bound=sorted(key[:-len('_sha256')] for key in identity if key.endswith('_sha256'))
    assert bound==sorted(BOUND_SOURCES)
    for name in bound:
        path=Path((BOUND_SOURCES[name] or module).__file__)
        target=tmp_path/(name+'-original.py');target.write_bytes(path.read_bytes());files[name]=source_pin(target)
    host={'identity':identity,'sources':files}
    assert module._validate_prepared_external_host(deepcopy(host))==identity
    return host


def proposer(role='proposer'):
    value=external_node(None,role=role)
    return value



def legacy_module(tmp_path):
    """Source-copy control exports the old request without host-source metadata.

    It is a deliberate engineering fixture, never an actual legacy invocation.
    The saved original-source bytes and request/receipt correlation are real.
    """
    text=Path(original.__file__).read_text()
    text=text.replace('                        "prepared_host": prepared_host,\n','')
    path=tmp_path/'legacy-graph-source.py';path.write_text(text+'\n# Engineering legacy source epoch.\n')
    loader=importlib.util.spec_from_file_location('ravel.workflow._legacy_host_control',path)
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
    return module


def legacy_case(tmp_path,role='proposer'):
    legacy=legacy_module(tmp_path)
    root=tmp_path/'graph';legacy.create(root,spec([proposer(role)],calls=1,tokens=256))
    prepared=legacy.prepare_external(root,'verify')
    assert 'prepared_host' not in read_json(prepared['request_file'])
    host=old_host(tmp_path,legacy)
    response=external_response(prepared,tmp_path/'response.json',actor_id='fixture-proposer',fresh_context=False)
    return root,prepared,host,response


def saved_result(root):
    state=candidate.status(root);ref=state['nodes']['verify']['result']
    return candidate._result(root,ref)


@pytest.mark.parametrize('role',['proposer','improver'])
def test_legacy_pending_completion_preserves_old_binding_and_honest_context(tmp_path,role):
    root,prepared,host,response=legacy_case(tmp_path,role)
    raw=Path(prepared['request_file']).read_bytes();usage=original.status(root)['usage']
    state=candidate.deliver_external(root,'verify',response,prepared_host=host)
    assert state['complete'] and state['usage']==usage
    assert Path(prepared['request_file']).read_bytes()==raw
    saved=saved_result(root)
    assert saved['host_sha256']==original.digest(host['identity'])
    assert saved['request']==read_json(prepared['request_file'])['request']
    assert saved['result']['isolation']['fresh_context'] is False
    assert saved['result']['isolation']['fresh_request'] is False
    assert saved['result']['isolation']['parent_transcript_supplied'] is False
    transport=saved['result']['transport']
    assert transport['prepared_host_identity']==host['identity']
    assert transport['delivery_host_identity']==candidate._external_identity()
    assert transport['pending_host_completion'] is True
    assert not saved['result']['execution_authorized'] and not saved['result']['physics_validated']


@pytest.mark.parametrize('fresh,parent',[(True,False),(False,False),(True,True),(False,True)])
def test_future_preparation_pins_actual_host_and_preserves_declared_proposer_flags(tmp_path,fresh,parent):
    root=tmp_path/'new';candidate.create(root,spec([proposer()],calls=1,tokens=256))
    prepared=candidate.prepare_external(root,'verify');document=read_json(prepared['request_file'])
    identity=candidate._validate_prepared_external_host(document['prepared_host'])
    assert identity==candidate._external_identity()
    assert all(Path(pin['path']).is_relative_to(root/'host_sources') for pin in document['prepared_host']['sources'].values())
    response=external_response(prepared,tmp_path/'reply.json',fresh_context=fresh,parent_transcript_supplied=parent)
    candidate.deliver_external(root,'verify',response)
    saved=saved_result(root)
    assert saved['result']['isolation']['fresh_context'] is fresh
    assert saved['result']['isolation']['parent_transcript_supplied'] is parent
    assert saved['result']['transport']['pending_host_completion'] is False


@pytest.mark.parametrize('role',['critic','verifier'])
@pytest.mark.parametrize('fresh,parent',[(False,False),(True,True),(False,True)])
def test_independent_review_roles_remain_strict(tmp_path,role,fresh,parent):
    packet,_=role_packet(tmp_path/'role',role,{'actual':'public control'})
    root=tmp_path/'graph';candidate.create(root,spec([external_node(packet,role=role)],calls=1,tokens=256))
    prepared=candidate.prepare_external(root,'verify')
    response=external_response(prepared,tmp_path/'response.json',fresh_context=fresh,parent_transcript_supplied=parent)
    with pytest.raises(candidate.GraphError,match='fresh context'):
        candidate.deliver_external(root,'verify',response)
    assert candidate.status(root)['nodes']['verify']['status']=='awaiting_external'


@pytest.mark.parametrize('field,value',[('fresh_context','false'),('fresh_context',0),('parent_transcript_supplied',0),('parent_transcript_supplied',None)])
def test_context_attestations_require_bools(tmp_path,field,value):
    root,prepared,host,response=legacy_case(tmp_path)
    changed=read_json(response);changed[field]=value;atomic_json(response,changed)
    with pytest.raises(candidate.GraphError,match='boolean'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)


def test_source_epoch_change_needs_explicit_legacy_host(tmp_path):
    root,prepared,host,response=legacy_case(tmp_path)
    with pytest.raises(candidate.GraphError,match='different request'):
        candidate.deliver_external(root,'verify',response)
    assert candidate.status(root)['nodes']['verify']['status']=='awaiting_external'


@pytest.mark.parametrize('name',['agent_graph','agent_host','review_context','langgraph_runtime'])
def test_prepared_host_source_substitution_is_rejected(tmp_path,name):
    root,prepared,host,response=legacy_case(tmp_path)
    Path(host['sources'][name]['path']).write_text('substituted source bytes')
    with pytest.raises(candidate.GraphError,match='source changed'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)


@pytest.mark.parametrize('mutation',['identity_extra','source_extra','bool_version','different_adapter','bad_hash','wrong_pin_hash'])
def test_prepared_identity_is_closed_and_source_bound(tmp_path,mutation):
    root,prepared,host,response=legacy_case(tmp_path)
    if mutation=='identity_extra':host['identity']['extra']='x'
    if mutation=='source_extra':host['sources']['extra']=host['sources']['agent_graph']
    if mutation=='bool_version':host['identity']['schema_version']=True
    if mutation=='different_adapter':host['identity']['adapter']='fake'
    if mutation=='bad_hash':host['identity']['agent_graph_sha256']='z'*64
    if mutation=='wrong_pin_hash':host['sources']['agent_graph']['sha256']='0'*64
    with pytest.raises(candidate.GraphError):candidate.deliver_external(root,'verify',response,prepared_host=host)


@pytest.mark.parametrize('field',['request_id','request_sha256'])
def test_response_request_transplant_is_rejected(tmp_path,field):
    root,prepared,host,response=legacy_case(tmp_path)
    changed=read_json(response);changed[field]='0'*64;atomic_json(response,changed)
    with pytest.raises(candidate.GraphError,match='different request'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)


@pytest.mark.parametrize('field,value',[('kind','tool'),('attempt_id','wrong'),('node_id','wrong'),('output_tokens_reserved',1),('status','started')])
def test_wrong_reserved_invocation_rejected(tmp_path,field,value):
    root,prepared,host,response=legacy_case(tmp_path)
    state=read_json(root/original.STATE);call=next(iter(state['calls'].values()));call[field]=value
    atomic_json(root/original.STATE,state)
    with pytest.raises(candidate.GraphError,match='reserved call'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)


def test_persisted_reservation_substitution_rejected(tmp_path):
    root,prepared,host,response=legacy_case(tmp_path)
    callpath=next((root/'calls').glob('*.json'));record=read_json(callpath);record['elapsed_seconds']=999;atomic_json(callpath,record)
    with pytest.raises(candidate.GraphError,match='call receipt changed'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)


def test_stale_generation_and_repeat_delivery_rejected(tmp_path):
    root,prepared,host,response=legacy_case(tmp_path)
    before=read_json(root/original.STATE);changed=deepcopy(before);changed['nodes']['verify']['generation']+=1;atomic_json(root/original.STATE,changed)
    with pytest.raises(candidate.GraphError,match='different request'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)
    atomic_json(root/original.STATE,before);candidate.deliver_external(root,'verify',response,prepared_host=host)
    with pytest.raises(candidate.GraphError,match='not awaiting'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)


def test_unrelated_declared_old_host_cannot_rebind_original_request(tmp_path):
    root,prepared,host,response=legacy_case(tmp_path)
    fake=tmp_path/'fake.py';fake.write_text('fake host')
    host['sources']['agent_graph']=source_pin(fake);host['identity']['agent_graph_sha256']=source_pin(fake)['sha256']
    with pytest.raises(candidate.GraphError,match='different request'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)


def test_future_explicit_host_cannot_override_prepared_identity(tmp_path):
    root=tmp_path/'graph';candidate.create(root,spec([proposer()],calls=1,tokens=256));prepared=candidate.prepare_external(root,'verify')
    with pytest.raises(candidate.GraphError,match='differs from prepared'):
        candidate.deliver_external(root,'verify',external_response(prepared,tmp_path/'response.json'),prepared_host=old_host(tmp_path))


def test_original_completed_review_receipt_remains_read_only_rebindable(tmp_path):
    packet,sha=role_packet(tmp_path/'review','verifier',{'actual':'public control'})
    root=tmp_path/'graph';original.create(root,spec([external_node(packet)],calls=1,tokens=256))
    prepared=original.prepare_external(root,'verify');original.deliver_external(root,'verify',external_response(prepared,tmp_path/'reply.json'))
    files={str(p):p.read_bytes() for p in root.rglob('*.json')}
    receipt=candidate.model_receipt(root,'verify',expected_subject_sha256=sha,expected_packet_sha256=packet['manifest_sha256'])
    assert receipt['public_value']=={'status':'request_evidence'} and receipt['context_transport_separated']
    assert {str(p):p.read_bytes() for p in root.rglob('*.json')}==files


def test_host_source_symlink_is_not_ordinary_custody(tmp_path):
    root,prepared,host,response=legacy_case(tmp_path)
    link=tmp_path/'host-source-alias.py';link.symlink_to(host['sources']['agent_graph']['path'])
    host['sources']['agent_graph']['path']=str(link)
    with pytest.raises(candidate.GraphError,match='symlink'):
        candidate.deliver_external(root,'verify',response,prepared_host=host)


def test_host_source_drift_refuses_preparation_before_call_reservation(tmp_path,monkeypatch):
    root=tmp_path/'new';candidate.create(root,spec([proposer()],calls=1,tokens=256))
    identity=candidate._external_identity();identity['agent_host_sha256']='0'*64
    monkeypatch.setattr(candidate,'_external_identity',lambda:identity)
    with pytest.raises(candidate.GraphError,match='source changed'):
        candidate.prepare_external(root,'verify')
    assert candidate.status(root)['usage']=={'calls':0,'reserved_output_tokens':0}
    assert candidate.status(root)['nodes']['verify']['status']=='pending'
