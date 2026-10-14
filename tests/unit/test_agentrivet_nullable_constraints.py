"""Nullable schema adaptation keeps exactly the original constrained union."""
from copy import deepcopy
import pytest
from ravel.workflow.agentrivet_provider import graph_output_schema
from ravel.workflow.agent_host import _validate, HostFailure


def adapted(variant):
    original={'type':'object','properties':{'value':{'anyOf':[
        variant,{'type':'null'}]}}}
    before=deepcopy(original)
    schema=graph_output_schema(original)
    assert original==before
    return schema


@pytest.mark.parametrize('variant,allowed,rejected',[
    ({'type':'string','enum':['HEPDATA','TEXT']},['HEPDATA','TEXT',None],['other',0]),
    ({'type':'string','const':'HEPDATA'},['HEPDATA',None],['TEXT','other']),
    ({'type':'string','enum':['HEPDATA','TEXT'],'const':'HEPDATA'},['HEPDATA',None],['TEXT','other']),
    ({'type':'string','enum':['HEPDATA'],'const':'TEXT'},[None],['TEXT','HEPDATA','other']),
    ({'type':'number','enum':[1,2],'const':1.0},[1,1.0,None],[True,False,2]),
    ({'type':'boolean','enum':[True,False],'const':1},[None],[True,False,1]),
    ({'type':'string','enum':['HEPDATA',None]},['HEPDATA',None],['TEXT']),
    ({'type':'string','const':None},[None],['HEPDATA']),
])
def test_nullable_constraint_union_and_json_equality(variant,allowed,rejected):
    schema=adapted(variant)
    assert 'const' not in schema['properties']['value']
    assert sum(value is None for value in schema['properties']['value']['enum'])==1
    for value in allowed:_validate({'value':value},schema)
    for value in rejected:
        with pytest.raises(HostFailure):_validate({'value':value},schema)


@pytest.mark.parametrize('values',[[],{},'HEPDATA',None])
def test_invalid_nullable_enum_refuses(values):
    with pytest.raises(ValueError,match='literal values'):
        adapted({'type':'string','enum':values})
