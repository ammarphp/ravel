"""Synthetic supplied-host completions; no actual model/native/publisher execution.

Graph reservations and receipt/current-file guards are real software consumers.
Only upstream toy scientific context/campaign semantics use disclosed old fixtures.
"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import agent_graph as graph, agent_host as host
from ravel.workflow import manuscript_production as mp
from ravel.workflow.state_io import atomic_json, read_json
from test_agent_graph import external_node, external_response, role_packet, spec
from test_manuscript_production import setup, pin, put


def pending(root, *, public_bytes=2000, file_bytes=4096):
    packet, subject = role_packet(root/'packet', 'verifier', {'synthetic': True})
    item = external_node(packet)
    item['parameters']['completion_limits'] = {'public_value_bytes': public_bytes, 'response_file_bytes': file_bytes}
    rd = root/'graph';graph.create(rd,spec([item],calls=1,tokens=256))
    return rd,graph.prepare_external(rd,'verify'),subject


def reported(root, prepared, *, invocation='fixture-live-host-invocation', model='test-external-model', counts=None):
    usage = counts or {'input_tokens':100,'output_tokens':200,'total_tokens':300}
    evidence = {'schema_version':1,'kind':'host_meter','request_id':prepared['request_id'],
        'request_sha256':prepared['request_sha256'],'invocation_id':invocation,'observed_model':model,
        'complete_invocation':True,'usage':usage}
    asset = put(root,'usage.json',evidence)
    return {'state':'host_reported','tokens':usage,'source':{'kind':'host_meter','invocation_id':invocation,'artifact':asset}}


def receipt(rd,subject):
    return graph.model_receipt(rd,'verify',expected_subject_sha256=subject,require_exact_subject=True)


def test_external_reported_usage_is_host_attributed_and_never_refunds(tmp_path):
    rd,p,subject=pending(tmp_path);report=reported(tmp_path,p)
    path=external_response(p,tmp_path/'response.json',schema_version=2,usage_report=report)
    graph.deliver_external(rd,'verify',path);r=receipt(rd,subject)
    assert r['transport']['usage_observation']=='external_host_reported'
    assert r['transport']['usage_report']['tokens']==report['tokens']
    assert r['transport']['inference_token_ceiling_enforced'] is False
    assert not r['actor_identity_authenticated'] and r['execution_observation']=='host_attested_external'
    assert graph.status(rd)['usage']=={'calls':1,'reserved_output_tokens':256}
    assert r['external_completion_evidence']['reserved_output_tokens']==256
    with pytest.raises(graph.GraphError,match='not awaiting'):graph.deliver_external(rd,'verify',path)
    assert graph.status(rd)['usage']=={'calls':1,'reserved_output_tokens':256}


@pytest.mark.parametrize('version',[1,2])
def test_unknown_response_stays_null_and_current_original_bytes_are_required(tmp_path,version):
    rd,p,subject=pending(tmp_path)
    extras={} if version==1 else {'schema_version':2,'usage_report':{'state':'unknown','tokens':host._usage(None),'source':None}}
    path=external_response(p,tmp_path/'response.json',**extras)
    graph.deliver_external(rd,'verify',path);r=receipt(rd,subject)
    assert r['transport']['usage_report']['tokens']==host._usage(None)
    assert r['transport']['usage_observation']=='unknown'
    assert graph.status(rd)['usage']=={'calls':1,'reserved_output_tokens':256}
    original=path.read_bytes();path.write_bytes(original+b' ')
    with pytest.raises(graph.GraphError,match='retained pin'):receipt(rd,subject)
    path.write_bytes(original);assert receipt(rd,subject)==r


@pytest.mark.parametrize('change',['boolean','negative','partial','total','wrong-invocation','wrong-request','wrong-model','partial-meter','hash','extra-private','unknown-counts','unknown-source','over-output'])
def test_usage_adversaries_keep_the_original_ambiguous_charge(tmp_path,change):
    rd,p,subject=pending(tmp_path);valid=reported(tmp_path,p);bad=deepcopy(valid)
    if change=='boolean':bad['tokens']['input_tokens']=True
    if change=='negative':bad['tokens']['input_tokens']=-1
    if change=='partial':bad['tokens']['input_tokens']=None
    if change=='total':bad['tokens']['total_tokens']=301
    if change=='wrong-invocation':bad['source']['invocation_id']='other'
    if change=='hash':bad['source']['artifact']['sha256']='0'*64
    if change=='unknown-counts':bad['state']='unknown';bad['source']=None
    if change=='unknown-source':bad['state']='unknown';bad['tokens']=host._usage(None)
    if change=='over-output':
        bad['tokens']={'input_tokens':100,'output_tokens':257,'total_tokens':357}
        evidence=read_json(valid['source']['artifact']['path']);evidence['usage']=bad['tokens']
        bad['source']['artifact']=put(tmp_path,'over-usage.json',evidence)
    if change in ('wrong-request','wrong-model','partial-meter','extra-private'):
        evidence=read_json(valid['source']['artifact']['path'])
        if change=='wrong-request':evidence['request_id']='other'
        if change=='wrong-model':evidence['observed_model']='other'
        if change=='partial-meter':evidence['complete_invocation']=False
        if change=='extra-private':evidence['private_reasoning']='not public'
        bad['source']['artifact']=put(tmp_path,'bad-usage.json',evidence)
    response=external_response(p,tmp_path/'bad-response.json',schema_version=2,usage_report=bad)
    messages={'boolean':'provider token usage','negative':'provider token usage','partial':'complete counts',
        'total':'inconsistent provider token usage','wrong-invocation':'different invocation',
        'wrong-request':'complete source invocation','wrong-model':'complete source invocation',
        'partial-meter':'complete source invocation','hash':'retained pin','extra-private':'usage evidence',
        'unknown-counts':'must remain null','unknown-source':'must remain null','over-output':'output token usage'}
    with pytest.raises(graph.GraphError,match=messages[change]):graph.deliver_external(rd,'verify',response)
    state=graph.status(rd)
    assert state['nodes']['verify']['status']=='awaiting_external'
    assert state['usage']=={'calls':1,'reserved_output_tokens':256}
    assert next(iter(state['calls'].values()))['status']=='ambiguous'
    # Positive baseline proves the intended usage guard can complete this same call.
    graph.deliver_external(rd,'verify',external_response(p,tmp_path/'good-response.json',schema_version=2,usage_report=valid))
    assert receipt(rd,subject)['transport']['usage_observation']=='external_host_reported'
    assert graph.status(rd)['usage']==state['usage']


def test_whole_value_byte_limit_accepts_exact_boundary_and_refuses_plus_one(tmp_path):
    value={'status':'request_evidence'};cost=len(host._json_bytes(value))
    rd,p,subject=pending(tmp_path,public_bytes=cost)
    # Schema permits this status; the altered string fails only the aggregate byte guard below.
    doc=read_json(p['request_file']);params={**doc['parameters'],'output_schema':None}
    assert host.validate_completion_value(value,params)==value
    with pytest.raises(host.HostFailure,match='byte bound'):
        host.validate_completion_value({'status':'request_evidence '},params)
    graph.deliver_external(rd,'verify',external_response(p,tmp_path/'response.json'))
    assert receipt(rd,subject)['public_value']==value


def test_oversize_envelope_is_refused_before_parser_and_does_not_refund(tmp_path,monkeypatch):
    rd,p,_=pending(tmp_path,file_bytes=4096);path=tmp_path/'large.json';path.write_bytes(b'{'*4097)
    parser=host._loads;seen=[]
    def observed(raw):seen.append(True);return parser(raw)
    monkeypatch.setattr(host,'_loads',observed)
    with pytest.raises(graph.GraphError,match='file byte bound'):graph.deliver_external(rd,'verify',path)
    assert not seen and graph.status(rd)['usage']=={'calls':1,'reserved_output_tokens':256}


def test_usage_evidence_is_reconsumed_at_current_receipt_ending(tmp_path):
    rd,p,subject=pending(tmp_path);report=reported(tmp_path,p)
    graph.deliver_external(rd,'verify',external_response(p,tmp_path/'response.json',schema_version=2,usage_report=report))
    original=Path(report['source']['artifact']['path']).read_bytes()
    Path(report['source']['artifact']['path']).write_bytes(original+b' ')
    with pytest.raises(graph.GraphError,match='retained pin'):receipt(rd,subject)
    Path(report['source']['artifact']['path']).write_bytes(original)
    assert receipt(rd,subject)['transport']['usage_report']['tokens']==report['tokens']


def author(root,monkeypatch,*,policy='reserved_unknown',telemetry=False,bound=2000000):
    request,state,value=setup(root/'source',monkeypatch)
    request['runtime'].update(usage_policy=policy,max_output_bytes=bound)
    binding=mp.prepare_writer(request,root/'writer',base_dir=root/'source',campaign=root/'campaign')
    p=graph.prepare_external(binding['graph'],'author')
    response={'schema_version':1,'request_id':p['request_id'],'request_sha256':p['request_sha256'],
        'invocation_id':'synthetic-writer-invocation','actor_id':'toy-writer','observed_model':'synthetic-build',
        'fresh_context':True,'parent_transcript_supplied':False,'value':value}
    if telemetry:
        response.update(schema_version=2,usage_report=reported(root,p,invocation=response['invocation_id'],model=response['observed_model']))
    path=root/'author-response.json';atomic_json(path,response)
    graph.deliver_external(binding['graph'],'author',path)
    # Disclosed inherited synthetic campaign hook; this is not a real model/campaign qualification.
    state['sha256']='1'*64;state['graphs']=[{'root':binding['graph'],'complete':True}]
    return request,state,binding,value,path


def test_reserved_unknown_authorship_preserves_whole_census_and_provenance(tmp_path,monkeypatch):
    r,state,b,value,path=author(tmp_path,monkeypatch)
    got=mp.collect(b,tmp_path/'note');mp.verify_author(got['package'],base_dir=tmp_path/'note')
    provenance=read_json(got['package']['model_provenance']['path']);account=provenance['writer_accounting']
    assert account['usage']==host._usage(None) and account['usage_policy']=='reserved_unknown'
    assert account['reserved_output_tokens']==r['runtime']['max_output_tokens'] and not account['reservation_refunded']
    assert not account['input_token_ceiling_verified'] and not account['output_token_ceiling_verified']
    assert len(provenance['call_receipts'])==1
    assert graph.status(b['graph'])['usage']=={'calls':1,'reserved_output_tokens':4096}
    assert not got['package']['scientific_acceptance'] and len(got['integrity_preparation']['units'])>=7
    original=path.read_bytes();path.write_bytes(original+b' ')
    with pytest.raises(graph.GraphError):mp.verify_author(got['package'],base_dir=tmp_path/'note')


@pytest.mark.parametrize('policy',['strict_reported','reserved_unknown'])
def test_genuine_supplied_host_telemetry_passes_both_declared_writer_policies(tmp_path,monkeypatch,policy):
    r,state,b,_,_=author(tmp_path,monkeypatch,policy=policy,telemetry=True)
    got=mp.collect(b,tmp_path/'note');mp.verify_author(got['package'],base_dir=tmp_path/'note')
    account=read_json(got['package']['model_provenance']['path'])['writer_accounting']
    assert account['usage']['total_tokens']==300 and account['usage_observation']=='external_host_reported'
    assert account['reserved_output_tokens']==4096 and account['inference_token_ceiling_enforced'] is False


def test_strict_writer_refuses_unknown_without_returning_budget(tmp_path,monkeypatch):
    _,_,b,_,_=author(tmp_path,monkeypatch,policy='strict_reported')
    with pytest.raises(ValueError,match='actual token telemetry'):mp.collect(b,tmp_path/'held-note')
    assert not (tmp_path/'held-note').exists()
    assert graph.status(b['graph'])['usage']=={'calls':1,'reserved_output_tokens':4096}


@pytest.mark.parametrize('change',['missing-bytes','bad-policy','boolean-bytes','model-action','over-cap'])
def test_unknown_accounting_policy_is_prospective_and_finite(tmp_path,monkeypatch,change):
    r,_,_=setup(tmp_path,monkeypatch);r['runtime'].update(usage_policy='reserved_unknown',max_output_bytes=1000)
    if change=='missing-bytes':r['runtime'].pop('max_output_bytes')
    if change=='bad-policy':r['runtime']['usage_policy']='estimate_tokens'
    if change=='boolean-bytes':r['runtime']['max_output_bytes']=True
    if change=='model-action':r['runtime']['action']='model'
    if change=='over-cap':r['runtime']['max_output_bytes']=16000000
    with pytest.raises(ValueError):mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert not (tmp_path/'writer').exists()


@pytest.mark.parametrize('change',['stale-quantities','uncharged-campaign','wrong-author','wrong-model','byte-bound'])
def test_reserved_unknown_does_not_weaken_original_author_joins(tmp_path,monkeypatch,change):
    r,state,b,value,path=author(tmp_path,monkeypatch)
    if change=='stale-quantities':state['context']={'different':True}
    if change=='uncharged-campaign':state['graphs']=[]
    if change in ('wrong-author','wrong-model','byte-bound'):
        original=read_json(b['request']['path'])
        if change=='wrong-author':original['author_id']='foreign'
        if change=='wrong-model':original['runtime']['model_build']='foreign'
        if change=='byte-bound':original['runtime']['max_output_bytes']=1
        # Caller cannot re-pin a new request while borrowing old presentation/spec/completion.
        b['request']=put(Path(b['request']['path']).parent,'changed-request.json',original)
    with pytest.raises((ValueError,graph.GraphError)):mp.collect(b,tmp_path/'held-note')
    assert not (tmp_path/'held-note').exists()
    assert graph.status(b['graph'])['usage']=={'calls':1,'reserved_output_tokens':4096}
