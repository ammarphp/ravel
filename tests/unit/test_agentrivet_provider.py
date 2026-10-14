"""Graph accounting with supplied responses; no actual provider or model use."""
from pathlib import Path
import pytest
from ravel.workflow import agent_graph, agentrivet_provider
from ravel.workflow.state_io import atomic_json, read_json
import test_agentrivet_candidate as supplied

QUEUE=[];OBSERVED=[]
def dispatcher(prepared):
    OBSERVED.append(read_json(prepared['request_file']))
    value=QUEUE.pop(0)
    if isinstance(value,Exception):raise value
    p=Path(prepared['request_file']).parent.parent.parent/('fixture-response-'+str(len(OBSERVED))+'.json')
    atomic_json(p,{'schema_version':1,'request_id':prepared['request_id'],
        'request_sha256':prepared['request_sha256'],'invocation_id':'fixture-'+str(len(OBSERVED)),
        'actor_id':'fixture-control','observed_model':'fixture-control','fresh_context':True,
        'parent_transcript_supplied':False,'value':value})
    return p


def provider(tmp_path, *, max_calls=2, source_inputs=None):
    QUEUE.clear();OBSERVED.clear()
    source=tmp_path/'declared-upstream.py';source.write_text('Explicit supplied upstream source fixture\n')
    return agentrivet_provider.GraphLLM(tmp_path/'graph',model='fixture-control',reasoning_effort='high',
        max_calls=max_calls,max_output_tokens=256,max_wall_seconds=60,dispatcher=dispatcher,
        dispatcher_pin=supplied.pin(Path(__file__)),source_inputs=source_inputs or [supplied.pin(source)])


def test_text_adapter_preserves_exact_messages_and_one_cumulative_graph(tmp_path):
    llm=provider(tmp_path);QUEUE.extend([{'text':'first raw code'},{'text':'second raw code'}])
    one=[{'role':'system','content':'Original upstream instruction'}, {'role':'user','content':'Literal paper and HEPData context'}]
    two=[{'role':'user','content':'Revision with actual prior producer advisories'}]
    assert llm.generate(one)=='first raw code' and llm.generate(two)=='second raw code'
    assert len(OBSERVED)==2
    for original,request in zip((one,two),OBSERVED):
        pin=next(p for p in request['request']['input_artifacts'] if p['id']=='upstream-messages')
        assert read_json(pin['path'])['messages']==original
        assert request['context']['role']=='proposer'
    state=agent_graph.status(llm.root)
    assert state['usage']['calls']==2 and state['usage']['reserved_output_tokens']==512
    assert len(list((llm.root/'attempts').glob('*.json')))==2
    with pytest.raises(ValueError,match='ceiling exhausted'):llm.generate(two)
    assert agent_graph.status(llm.root)['usage']==state['usage']


def test_ambiguous_dispatch_blocks_new_stage_and_reserves_once(tmp_path):
    llm=provider(tmp_path);QUEUE.append(RuntimeError('supplied ambiguous dispatch'))
    with pytest.raises(RuntimeError):llm.generate([{'role':'user','content':'request'}])
    assert agent_graph.status(llm.root)['usage']['calls']==1
    with pytest.raises(ValueError,match='unresolved provider'):llm.generate([{'role':'user','content':'retry'}])
    assert agent_graph.status(llm.root)['usage']['calls']==1


def test_changed_upstream_source_refuses_before_dispatch(tmp_path):
    llm=provider(tmp_path);Path(llm.source_inputs[0]['path']).write_text('changed upstream')
    with pytest.raises(ValueError,match='consumed bytes'):llm.generate([{'role':'user','content':'request'}])
    assert not OBSERVED and not llm.root.exists()


@pytest.mark.parametrize('messages',[[{'role':'system','content':'alone'}],
    [{'role':'user','content':'first'},{'role':'user','content':'second'}],
    [{'role':'user','content':'first'},{'role':'system','content':'second'}]])
def test_message_shape_is_actual_agent_order(tmp_path,messages):
    llm=provider(tmp_path)
    with pytest.raises(ValueError,match='message shape'):llm.generate(messages)
    assert not OBSERVED and not llm.root.exists()


def test_local_nullable_model_schema_requires_literal_fields_without_filling_defaults():
    original={'type':'object','$defs':{'Histogram':{'type':'object',
        'properties':{'edges':{'anyOf':[{'type':'array','items':{'type':'number'}},{'type':'null'}],'default':None}},
        'required':[]}},'properties':{'histograms':{'type':'array','items':{'$ref':'#/$defs/Histogram'}}},'required':['histograms']}
    from copy import deepcopy
    old=deepcopy(original);schema=agentrivet_provider.graph_output_schema(original)
    assert original==old and '$defs' not in schema
    hist=schema['properties']['histograms']['items']
    assert hist['required']==['edges'] and hist['additionalProperties'] is False
    assert hist['properties']['edges']['type']==['array','null']
    from ravel.workflow.agent_host import _validate,HostFailure
    _validate({'histograms':[{'edges':None}]},schema)
    with pytest.raises(HostFailure):_validate({'histograms':[{}]},schema)


@pytest.mark.parametrize('schema',[{'type':'string','anyOf':[{'type':'integer'},{'type':'string'}]},
    {'type':'object','$defs':{'X':{'$ref':'#/$defs/X'}},'properties':{'x':{'$ref':'#/$defs/X'}}},
    {'$ref':'https://example.com/external.json'}])
def test_unsupported_schema_union_recursion_or_external_ref_refuses(schema):
    with pytest.raises(ValueError):agentrivet_provider.graph_output_schema(schema)
