"""Proposed inert wire/ordinary Graph controls; no provider or local model runs."""
from copy import deepcopy
import hashlib
import json
import threading
from urllib.parse import urlsplit

import pytest

from ravel.workflow import agent_host as host, agent_graph as graph, provider_transport as wire
from ravel.workflow.state_io import atomic_json

SCHEMA = {'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}
VALUE = {'answer':'source control'}


def capabilities(adapter='chat_completions', **changes):
    c = {'output_mode':'tool_call','token_limit_field':{'anthropic':'max_tokens','gemini':'maxOutputTokens'}.get(adapter,'max_tokens'),
         'reasoning_efforts':[],'max_context_bytes':2000000,'max_output_tokens':120}
    c.update(changes)
    return c


def node(*, action='model', role='proposer', packet=None, model='fixture-model'):
    return {'id':'role','kind':'model','role':role,'depends_on':[],'inputs':[],'packet':packet,'action':action,
            'parameters':{'instructions':'Use the complete supplied evidence.','model':model,'reasoning_effort':'high',
                          'max_output_tokens':120,'output_schema':deepcopy(SCHEMA)},'max_attempts':1}


def request(n):
    return {'request_id':'a'*64,'input_artifacts':[],'packet':n['packet']}


class Control:
    def __init__(self):
        self.calls=[]
    def cancelled(self):
        return False
    def call(self, label, kind, body, function, output_tokens=0):
        self.calls.append((label,kind,deepcopy(body),output_tokens))
        return function()


def document(adapter, value=None):
    value = deepcopy(VALUE if value is None else value)
    if adapter == 'anthropic':
        return {'type':'message','role':'assistant','stop_reason':'tool_use','model':'observed-snapshot','id':'fixture-response',
                'content':[{'type':'thinking','thinking':'PRIVATE-CANARY','signature':'PRIVATE-SIGNATURE'},
                           {'type':'tool_use','name':wire.FUNCTION,'id':'fixture-tool','input':value}],
                'usage':{'input_tokens':10,'output_tokens':7,'cache_creation_input_tokens':3,'cache_read_input_tokens':2}}
    if adapter == 'gemini':
        return {'modelVersion':'observed-snapshot','responseId':'fixture-response',
                'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[
                    {'thought':True,'text':'PRIVATE-CANARY'}, {'functionCall':{'name':wire.FUNCTION,'args':value},'thoughtSignature':'PRIVATE-SIGNATURE'}]}}],
                'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':7,'thoughtsTokenCount':2,'totalTokenCount':19}}
    return {'model':'observed-snapshot','id':'fixture-response','choices':[{'finish_reason':'tool_calls','message':{
        'role':'assistant','content':None,'reasoning_content':'PRIVATE-CANARY','tool_calls':[{
            'id':'fixture-tool','type':'function','function':{'name':wire.FUNCTION,'arguments':json.dumps(value)}}]}}],
        'usage':{'prompt_tokens':10,'completion_tokens':7,'total_tokens':17}}


def install_http(monkeypatch, doc, *, status=200):
    seen=[]
    class Response:
        def __init__(self): self.status=status
        def read(self, bound): return json.dumps(doc).encode()[:bound]
        def close(self): pass
    class Connection:
        def __init__(self, hostname, port, timeout):
            self.sock=None;seen.append({'hostname':hostname,'port':port,'timeout':timeout})
        def connect(self): pass
        def request(self, method, path, body, headers):
            seen[-1].update(method=method,path=path,body=json.loads(body),headers=headers)
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(host.http.client,'HTTPConnection',Connection)
    monkeypatch.setattr(host.http.client,'HTTPSConnection',Connection)
    return seen


@pytest.mark.parametrize('adapter',['anthropic','gemini','chat_completions'])
def test_actual_host_dispatch_schema_identity_usage_and_private_discard(monkeypatch,adapter):
    seen=install_http(monkeypatch,document(adapter))
    endpoint = wire.DEFAULTS.get(adapter,'https://compatible.example/v1/chat/completions')
    h=host.AgentHost(adapter=adapter,endpoint=endpoint,api_key='SYNTHETIC-KEY',capabilities=capabilities(adapter))
    c=Control();n=node();result=h.execute(n,request(n),c)
    assert len(c.calls)==1 and c.calls[0][0]==adapter and c.calls[0][3]==120
    assert result['value']==VALUE and result['transport']['adapter']==adapter
    assert result['transport']['requested_model']=='fixture-model' and result['transport']['observed_model']=='observed-snapshot'
    assert result['transport']['execution_mode']=='provider_http'
    assert result['transport']['reasoning_effort_transmitted'] is False
    assert result['public_output_only'] and not result['physics_validated'] and not result['execution_authorized']
    assert 'PRIVATE-' not in json.dumps(result) and 'SYNTHETIC-KEY' not in json.dumps(result)
    assert result['isolation']['model_tools_supplied'] is False and result['isolation']['structured_return_function_supplied']
    assert result['usage']==({'input_tokens':15,'output_tokens':7,'total_tokens':22} if adapter=='anthropic' else
                             {'input_tokens':10,'output_tokens':9,'total_tokens':19} if adapter=='gemini' else
                             {'input_tokens':10,'output_tokens':7,'total_tokens':17})
    body=seen[0]['body']
    assert 'PRIVATE-' not in json.dumps(body) and 'dependencies' not in json.dumps(body)
    if adapter=='anthropic':
        assert body['tools'][0]['input_schema']==SCHEMA and body['tool_choice']['name']==wire.FUNCTION
        assert seen[0]['headers']['x-api-key']=='SYNTHETIC-KEY' and seen[0]['headers']['anthropic-version']=='2023-06-01'
    elif adapter=='gemini':
        assert seen[0]['path']=='/v1beta/models/fixture-model:generateContent'
        assert body['tools'][0]['functionDeclarations'][0]['parametersJsonSchema']==SCHEMA
        assert seen[0]['headers']['x-goog-api-key']=='SYNTHETIC-KEY'
    else:
        assert body['tools'][0]['function']['parameters']==SCHEMA and body['max_tokens']==120
        assert seen[0]['headers']['Authorization']=='Bearer SYNTHETIC-KEY'


@pytest.mark.parametrize('adapter',['anthropic','gemini','chat_completions'])
@pytest.mark.parametrize('value',[{'answer':3},{'answer':'ok','extra':1},{'answer':'ok','scratchpad':'PRIVATE'},{}])
def test_all_new_transports_retain_complete_local_output_validation(monkeypatch,adapter,value):
    install_http(monkeypatch,document(adapter,value));n=node()
    h=host.AgentHost(adapter=adapter,endpoint=wire.DEFAULTS.get(adapter,'https://compatible.example/v1/chat/completions'),
                     api_key='SYNTHETIC',capabilities=capabilities(adapter))
    with pytest.raises(host.HostFailure): h.execute(n,request(n),Control())


@pytest.mark.parametrize('adapter',['anthropic','gemini','chat_completions'])
def test_conditional_schema_wrapper_is_reversible_and_preserves_branches(monkeypatch,adapter):
    schema=deepcopy(SCHEMA);schema['anyOf']=[{'type':'object','properties':{'answer':{'type':'string','const':'source control'}},
                                         'required':['answer'],'additionalProperties':False}]
    seen=install_http(monkeypatch,document(adapter,{'public_record':VALUE}));n=node();n['parameters']['output_schema']=schema
    h=host.AgentHost(adapter=adapter,endpoint=wire.DEFAULTS.get(adapter,'https://compatible.example/v1/chat/completions'),api_key='SYNTHETIC',capabilities=capabilities(adapter))
    assert h.execute(n,request(n),Control())['value']==VALUE
    assert 'public_record' in json.dumps(seen[0]['body']) and 'anyOf' in json.dumps(seen[0]['body'])


@pytest.mark.parametrize('adapter',['anthropic','gemini','chat_completions'])
@pytest.mark.parametrize('mutation',['missing_model','missing_id','missing_usage','negative_usage','truncated','unknown_tool','multiple_calls'])
def test_provider_census_and_completion_refusals(monkeypatch,adapter,mutation):
    d=document(adapter)
    if mutation=='missing_model': d.pop('modelVersion' if adapter=='gemini' else 'model')
    elif mutation=='missing_id': d.pop('responseId' if adapter=='gemini' else 'id')
    elif mutation=='missing_usage': d.pop('usageMetadata' if adapter=='gemini' else 'usage')
    elif mutation=='negative_usage':
        d['usageMetadata' if adapter=='gemini' else 'usage']['promptTokenCount' if adapter=='gemini' else 'input_tokens' if adapter=='anthropic' else 'prompt_tokens']=-1
    elif mutation=='truncated':
        if adapter=='anthropic': d['stop_reason']='max_tokens'
        elif adapter=='gemini': d['candidates'][0]['finishReason']='MAX_TOKENS'
        else: d['choices'][0]['finish_reason']='length'
    else:
        calls=d['content'] if adapter=='anthropic' else d['candidates'][0]['content']['parts'] if adapter=='gemini' else d['choices'][0]['message']['tool_calls']
        if mutation=='multiple_calls': calls.append(deepcopy(calls[-1]))
        elif adapter=='anthropic': calls[-1]['name']='unreviewed_action'
        elif adapter=='gemini': calls[-1]['functionCall']['name']='unreviewed_action'
        else: calls[-1]['function']['name']='unreviewed_action'
    seen=install_http(monkeypatch,d);n=node();c=Control()
    h=host.AgentHost(adapter=adapter,endpoint=wire.DEFAULTS.get(adapter,'https://compatible.example/v1/chat/completions'),api_key='SYNTHETIC',capabilities=capabilities(adapter))
    with pytest.raises(host.HostFailure): h.execute(n,request(n),c)
    assert len(c.calls)==1 and len(seen)==1


def test_chat_json_schema_and_explicit_reasoning_capability(monkeypatch):
    d=document('chat_completions');d['choices']=[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(VALUE)}}]
    seen=install_http(monkeypatch,d);n=node()
    h=host.AgentHost(adapter='chat_completions',endpoint='https://compatible.example/v1/chat/completions',api_key='SYNTHETIC',
                     capabilities=capabilities(output_mode='json_schema',token_limit_field='max_completion_tokens',reasoning_efforts=['high']))
    r=h.execute(n,request(n),Control());assert r['value']==VALUE
    assert seen[0]['body']['response_format']['json_schema']['schema']==SCHEMA
    assert seen[0]['body']['reasoning_effort']=='high' and seen[0]['body']['max_completion_tokens']==120
    assert r['transport']['reasoning_effort_transmitted'] and not r['isolation']['structured_return_function_supplied']


@pytest.mark.parametrize('change',[{'output_mode':'plain_text'},{'token_limit_field':'invented'},
                                 {'max_context_bytes':True},{'reasoning_efforts':['high','high']}])
def test_incompatible_capability_config_refuses_before_connection(monkeypatch,change):
    seen=install_http(monkeypatch,document('chat_completions'))
    with pytest.raises(host.HostFailure):
        host.AgentHost(adapter='chat_completions',endpoint='https://compatible.example/v1/chat/completions',capabilities=capabilities(**change))
    assert seen==[]


@pytest.mark.parametrize('change',[{'max_context_bytes':16},{'max_output_tokens':100},{'reasoning_efforts':['low']}])
def test_full_context_and_effort_limits_refuse_before_dispatch(monkeypatch,change):
    seen=install_http(monkeypatch,document('chat_completions'));c=Control();n=node()
    h=host.AgentHost(adapter='chat_completions',endpoint='https://compatible.example/v1/chat/completions',api_key='SYNTHETIC',capabilities=capabilities(**change))
    with pytest.raises(host.HostFailure): h.execute(n,request(n),c)
    assert c.calls==[] and seen==[]


@pytest.mark.parametrize('endpoint',['https://api.openai.com/v1/responses','https://cloud.example/v1/chat/completions',
                                   'http://127.0.0.1.cloud.example/v1/chat/completions','http://192.168.1.2/v1/chat/completions'])
def test_local_only_never_accepts_cloud_or_lookalike_destinations(endpoint):
    with pytest.raises(host.HostFailure):
        host.AgentHost(adapter='chat_completions',endpoint=endpoint,privacy='local_only',local_models=['fixture-model'],capabilities=capabilities())


def test_local_only_command_nested_runtime_and_cloud_model_refusals():
    with pytest.raises(host.HostFailure): host.AgentHost(adapter='command',command=['trusted-model'],privacy='local_only',local_models=['fixture-model'])
    with pytest.raises(host.HostFailure): host.AgentHost(adapter='chat_completions',endpoint='http://127.0.0.1:8000/v1/chat/completions',privacy='local_only',local_models=['fixture-model'],capabilities=capabilities(),cosmology_runtime_binding=object())
    with pytest.raises(host.HostFailure): host.AgentHost(adapter='chat_completions',endpoint='http://127.0.0.1:8000/v1/chat/completions',privacy='local_only',local_models=['model:cloud'],capabilities=capabilities())


def test_local_model_allowlist_and_control_observation_remain_distinct(monkeypatch):
    seen=install_http(monkeypatch,document('chat_completions'))
    h=host.AgentHost(adapter='chat_completions',endpoint='http://localhost:8000/v1/chat/completions',privacy='local_only',local_models=['fixture-model'],capabilities=capabilities())
    n=node();r=h.execute(n,request(n),Control())
    assert seen[0]['hostname']=='127.0.0.1' and r['transport']['execution_mode']=='provider_http_local'
    assert r['transport']['server_egress_confined'] is False and 'Authorization' not in seen[0]['headers']
    bad=node(model='not-allowed');c=Control()
    with pytest.raises(host.HostFailure): h.execute(bad,request(bad),c)
    assert c.calls==[] and len(seen)==1
    h2=host.AgentHost(adapter='chat_completions',endpoint='http://127.0.0.1:8000/v1/chat/completions',capabilities=capabilities())
    assert h2.execute(n,request(n),Control())['transport']['execution_mode']=='responses_http_loopback_control'


def test_configuration_reads_only_explicit_selected_key_and_never_falls_back(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','UNSELECTED-CANARY');monkeypatch.setenv('SELECTED_CLAUDE_KEY','SYNTHETIC-SELECTED')
    with pytest.raises(host.HostFailure): host.AgentHost.from_config({'type':'anthropic','capabilities':capabilities('anthropic')})
    h=host.AgentHost.from_config({'type':'anthropic','api_key_env':'SELECTED_CLAUDE_KEY','capabilities':capabilities('anthropic')})
    assert h._api_key=='SYNTHETIC-SELECTED' and h._api_key_env=='SELECTED_CLAUDE_KEY'
    with pytest.raises(host.HostFailure): host.AgentHost.from_config({'type':'anthropic','api_key':'SYNTHETIC','capabilities':capabilities('anthropic')})
    local=host.AgentHost.from_config({'type':'chat_completions','endpoint':'http://127.0.0.1:8000/v1/chat/completions',
        'privacy':'local_only','local_models':['fixture-model'],'capabilities':capabilities()})
    assert local._api_key is None
    responses=host.AgentHost.from_config({'type':'responses','endpoint':'http://127.0.0.1:8000/v1/responses',
        'privacy':'local_only','local_models':['fixture-model']})
    assert responses._api_key is None and responses._api_key_env is None


@pytest.mark.parametrize('status',[401,429,500])
@pytest.mark.parametrize('adapter',['anthropic','gemini','chat_completions'])
def test_http_failure_is_retained_with_no_alternate_dispatch(monkeypatch,status,adapter):
    seen=install_http(monkeypatch,{'error':'PRIVATE-ERROR-CANARY'},status=status);n=node();c=Control()
    h=host.AgentHost(adapter=adapter,endpoint=wire.DEFAULTS.get(adapter,'https://compatible.example/v1/chat/completions'),
                     api_key='SYNTHETIC',capabilities=capabilities(adapter))
    with pytest.raises(host.HostFailure) as failure: h.execute(n,request(n),c)
    assert len(seen)==len(c.calls)==1 and 'PRIVATE-' not in str(failure.value)
    assert failure.value.retryable == (status==429) and failure.value.ambiguous == (status>=500)


@pytest.mark.parametrize('adapter',['anthropic','gemini','chat_completions'])
def test_observed_usage_over_declared_output_cap_is_refused(monkeypatch,adapter):
    d=document(adapter)
    if adapter=='anthropic': d['usage']['output_tokens']=121
    elif adapter=='gemini': d['usageMetadata'].update(candidatesTokenCount=119,thoughtsTokenCount=2,totalTokenCount=131)
    else: d['usage'].update(completion_tokens=121,total_tokens=131)
    install_http(monkeypatch,d);n=node()
    h=host.AgentHost(adapter=adapter,endpoint=wire.DEFAULTS.get(adapter,'https://compatible.example/v1/chat/completions'),
                     api_key='SYNTHETIC',capabilities=capabilities(adapter))
    with pytest.raises(host.HostFailure,match='usage exceeds'): h.execute(n,request(n),Control())


def test_actual_graph_local_role_receipt_preserves_exact_subject_budget_and_noncertification(tmp_path,monkeypatch):
    packet=tmp_path/'packet';packet.mkdir();(packet/'artifacts').mkdir();raw=b'{"complete":"evidence"}'
    (packet/'artifacts/evidence.json').write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
    source=tmp_path/'original-evidence.json';source.write_bytes(raw)
    manifest={'schema_version':1,'role':'verifier','artifacts':[{'id':'evidence','path':'artifacts/evidence.json','sha256':sha,'source_path':str(source),'source_sha256':sha,'projection':'complete fixture'}],'findings':[],'reviews':[]}
    manifest['sha256']=graph.digest(manifest);atomic_json(packet/'manifest.json',manifest)
    n=node(action='model',role='verifier',packet={'path':str(packet),'manifest_sha256':manifest['sha256']})
    spec={'schema_version':1,'graph_id':'local-review','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':120,'max_wall_seconds':30,'max_reworks':1},'nodes':[n]}
    root=tmp_path/'graph';graph.create(root,spec);install_http(monkeypatch,document('chat_completions'))
    h=host.AgentHost(adapter='chat_completions',endpoint='http://127.0.0.1:8000/v1/chat/completions',privacy='local_only',local_models=['fixture-model'],capabilities=capabilities())
    state=graph.execute(root,h);assert state['complete'] and state['usage']=={'calls':1,'reserved_output_tokens':120}
    r=graph.model_receipt(root,'role',expected_subject_sha256=sha,expected_packet_sha256=manifest['sha256'],require_exact_subject=True)
    assert r['execution_observation']=='local_transport_observed' and r['exact_subject_presented']
    assert r['context_transport_separated'] and r['public_value']==VALUE
    assert not r['scientific_independence_proven'] and not r['physics_validated'] and not r['execution_authorized']
    with pytest.raises(graph.GraphError): graph.model_receipt(root,'role',expected_subject_sha256='f'*64,require_exact_subject=True)
    changed=host.AgentHost(adapter='chat_completions',endpoint='http://127.0.0.1:8001/v1/chat/completions',privacy='local_only',local_models=['fixture-model'],capabilities=capabilities())
    with pytest.raises(graph.GraphError): graph.execute(root,changed)


def test_local_only_graph_refuses_external_role_before_any_model_call(tmp_path,monkeypatch):
    n=node(action='external');root=tmp_path/'graph'
    graph.create(root,{'schema_version':1,'graph_id':'external-refusal','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':120,'max_wall_seconds':30,'max_reworks':1},'nodes':[n]})
    seen=install_http(monkeypatch,document('chat_completions'))
    h=host.AgentHost(adapter='chat_completions',endpoint='http://127.0.0.1:8000/v1/chat/completions',privacy='local_only',local_models=['fixture-model'],capabilities=capabilities())
    with pytest.raises(graph.GraphError): graph.execute(root,h)
    assert seen==[] and graph.status(root)['usage']['calls']==0


@pytest.mark.parametrize('usage_change',[{'toolUsePromptTokenCount':False},{'cachedContentTokenCount':11}])
def test_gemini_auxiliary_usage_cannot_falsify_complete_token_census(monkeypatch,usage_change):
    d=document('gemini');d['usageMetadata'].update(usage_change)
    install_http(monkeypatch,d);n=node()
    h=host.AgentHost(adapter='gemini',api_key='SYNTHETIC',capabilities=capabilities('gemini'))
    with pytest.raises(host.HostFailure):h.execute(n,request(n),Control())


def test_compatible_endpoint_is_not_inferred_from_responses_default():
    with pytest.raises(host.HostFailure,match='explicit chat endpoint'):
        host.AgentHost(adapter='chat_completions',capabilities=capabilities())


# ------------------------------------------------------------ declared HTTP auth variants

TOKEN_PROGRAM = '''import pathlib, sys
counter = pathlib.Path(sys.argv[1])
n = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(n))
print('SYNTHETIC-TOKEN-%d' % n)
'''


def test_bearer_from_token_command_runs_once_per_request_and_is_never_recorded(monkeypatch, tmp_path):
    import sys
    program = tmp_path / 'token.py'
    program.write_text(f'#!{sys.executable}\n' + TOKEN_PROGRAM)
    program.chmod(0o700)
    counter = tmp_path / 'count'
    seen = install_http(monkeypatch, document('chat_completions'))
    h = host.AgentHost.from_config({'type': 'chat_completions', 'endpoint': 'https://vertex.example/v1/chat/completions',
        'auth': {'kind': 'command', 'command': [str(program), str(counter)], 'header_style': 'bearer'},
        'capabilities': capabilities()})
    n = node(); first = h.execute(n, request(n), Control()); second = h.execute(n, request(n), Control())
    assert counter.read_text() == '2'
    assert [s['headers']['Authorization'] for s in seen] == ['Bearer SYNTHETIC-TOKEN-1', 'Bearer SYNTHETIC-TOKEN-2']
    identity = h.identity
    assert identity['auth']['kind'] == 'command' and 'command_sha256' in identity['auth']
    assert 'SYNTHETIC-TOKEN' not in json.dumps([first, second, identity])


def test_failed_token_command_names_only_its_status(monkeypatch, tmp_path):
    import sys
    program = tmp_path / 'failed-token.py'
    program.write_text(f'#!{sys.executable}\nimport sys\nprint("PRIVATE-CANARY", file=sys.stderr)\nsys.exit(4)\n')
    program.chmod(0o700)
    seen = install_http(monkeypatch, document('chat_completions'))
    h = host.AgentHost(adapter='chat_completions', endpoint='https://vertex.example/v1/chat/completions',
                       capabilities=capabilities(),
                       auth={'kind': 'command', 'command': [str(program)]})
    n = node(); c = Control()
    with pytest.raises(host.HostFailure) as failure: h.execute(n, request(n), c)
    assert 'status 4' in str(failure.value) and 'PRIVATE' not in str(failure.value) and seen == []


def test_api_key_header_style_for_compatible_endpoints(monkeypatch):
    monkeypatch.setenv('SYNTHETIC_AZURE_KEY', 'SYNTHETIC-AZURE')
    seen = install_http(monkeypatch, document('chat_completions'))
    h = host.AgentHost.from_config({'type': 'chat_completions', 'endpoint': 'https://azure.example/openai/deployments/d/chat/completions',
        'auth': {'kind': 'env', 'env_name': 'SYNTHETIC_AZURE_KEY', 'header_style': 'api-key'}, 'capabilities': capabilities()})
    n = node(); h.execute(n, request(n), Control())
    assert seen[0]['headers']['api-key'] == 'SYNTHETIC-AZURE' and 'Authorization' not in seen[0]['headers']
    assert h.identity['auth'] == {'kind': 'env', 'header_style': 'api-key', 'env_name': 'SYNTHETIC_AZURE_KEY'}


def test_x_api_key_at_a_mantle_style_path(monkeypatch):
    monkeypatch.setenv('SYNTHETIC_BEDROCK_KEY', 'SYNTHETIC-BEDROCK')
    seen = install_http(monkeypatch, document('anthropic'))
    h = host.AgentHost.from_config({'type': 'anthropic', 'endpoint': 'https://bedrock-mantle.region.example/anthropic/v1/messages',
        'auth': {'kind': 'env', 'env_name': 'SYNTHETIC_BEDROCK_KEY', 'header_style': 'x-api-key'},
        'capabilities': capabilities('anthropic')})
    n = node(); h.execute(n, request(n), Control())
    assert seen[0]['path'] == '/anthropic/v1/messages' and seen[0]['headers']['x-api-key'] == 'SYNTHETIC-BEDROCK'
    assert seen[0]['headers']['anthropic-version'] == '2023-06-01'


@pytest.mark.parametrize('auth,match', [
    ({'kind': 'command', 'command': []}, 'argument list'),
    ({'kind': 'env', 'env_name': 'X', 'header_style': 'cookie'}, 'header_style'),
    ({'kind': 'env', 'env_name': 'X', 'command': ['x']}, 'fields'),
    ({'kind': 'basic'}, 'auth.kind'),
])
def test_auth_block_is_closed(auth, match):
    with pytest.raises(host.HostFailure, match=match):
        host.AgentHost(adapter='chat_completions', endpoint='https://c.example/v1/chat/completions',
                       capabilities=capabilities(), auth=auth)


def test_local_only_refuses_a_token_command():
    with pytest.raises(host.HostFailure, match='local_only'):
        host.AgentHost(adapter='chat_completions', endpoint='http://127.0.0.1:8000/v1/chat/completions',
                       privacy='local_only', local_models=['fixture-model'], capabilities=capabilities(),
                       auth={'kind': 'command', 'command': ['token-program']})
