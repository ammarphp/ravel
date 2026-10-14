"""Finite nullable union must preserve its original allowed null value."""
from ravel.workflow.agentrivet_provider import graph_output_schema
from ravel.workflow.agent_host import _validate

def test_nullable_literal_keeps_null_allowed():
    original={'type':'object','properties':{'kind':{'anyOf':[
        {'type':'string','enum':['HEPDATA','TEXT']},{'type':'null'}]}}}
    adapted=graph_output_schema(original)
    _validate({'kind':'TEXT'},adapted)
    _validate({'kind':None},adapted)
