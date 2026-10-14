"""Authored inert source/API regressions; no UFO, Rust, engine or CAS execution."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import feyn_graph as fg, feyn_graph_worker as worker
from test_model_bound_diagrams import cfg


@pytest.mark.parametrize('literal',["'V_1'",'"VCT_1"',"r'V_1'",'r"VCT_1"'])
def test_plain_vertex_literal_preserves_exact_native_quoted_name(literal):
    source='V=Vertex(name='+literal+')\n'
    node=ast.parse(source).body[0].value.keywords[0].value
    assert fg.source_vertex_name(source,node)==node.value
    assert source=='V=Vertex(name='+literal+')\n'


@pytest.mark.parametrize('literal',[
    "'V_\\x31'",'"VCT_\\u0031"',"r'V_\\x31'",'R"V_1"',
    "u'V_1'","'V_' '1'",'"""V_1"""',"'V_\\\n1'",
])
def test_incompatible_native_string_spellings_refuse_without_rewrite(literal):
    source='V=Vertex(name='+literal+')\n'
    node=ast.parse(source).body[0].value.keywords[0].value
    with pytest.raises(ValueError,match='native quoted interior'):
        fg.source_vertex_name(source,node)
    assert source=='V=Vertex(name='+literal+')\n'


def test_equal_python_names_do_not_certify_equal_native_source_names():
    ordinary="V=Vertex(name='V_1')\n";escaped="V=Vertex(name='V_\\x31')\n"
    a=ast.parse(ordinary).body[0].value.keywords[0].value
    b=ast.parse(escaped).body[0].value.keywords[0].value
    assert a.value==b.value=='V_1'
    assert fg.source_vertex_name(ordinary,a)=='V_1'
    with pytest.raises(ValueError,match='native quoted interior'):fg.source_vertex_name(escaped,b)


def membership():
    model={'kind':'ufo','source_vertex_names':['V_1','VCT_1']}
    vertices=[{'name':'V_1','coupling_orders':{'QED':1}},
              {'name':'VCT_1_0','coupling_orders':{'QED':1,'CT':1}},
              {'name':'VCT_1_1','coupling_orders':{'QED':2,'CT':1}}]
    splittings=[{'name':'V_1','splitting':None},
                {'name':'VCT_1','splitting':{'VCT_1_0':[(0,0)],'VCT_1_1':[(0,1)]}}]
    return model,vertices,splittings


@pytest.mark.parametrize('transport',['native_tuples','json_lists'])
def test_native_source_membership_distinguishes_unsplit_and_split(transport):
    model,vertices,splittings=membership()
    if transport=='json_lists':
        import json
        splittings=json.loads(json.dumps(splittings))
    assert worker.check_source_membership(model,vertices,splittings) is splittings
    assert splittings[0]['splitting'] is None
    assert [row['name'] for row in vertices]==['V_1','VCT_1_0','VCT_1_1']


@pytest.mark.parametrize('case',[
    'absent_unsplit','absent_split_member','extra_native','duplicate_native',
    'missing_counterterm','reordered_source','empty_split','boolean_index',
    'boolean_order','ambiguous_membership',
])
def test_whole_native_source_membership_refuses_incomplete_correspondence(case):
    model,vertices,splittings=membership()
    if case=='absent_unsplit':vertices.pop(0)
    if case=='absent_split_member':vertices.pop()
    if case=='extra_native':vertices.append({'name':'unclaimed','coupling_orders':{}})
    if case=='duplicate_native':vertices.append(deepcopy(vertices[0]))
    if case=='missing_counterterm':splittings.pop()
    if case=='reordered_source':splittings.reverse()
    if case=='empty_split':splittings[1]['splitting']={}
    if case=='boolean_index':splittings[1]['splitting']['VCT_1_0']=[[True,0]]
    if case=='boolean_order':vertices[0]['coupling_orders']['QED']=True
    if case=='ambiguous_membership':splittings[1]['splitting']['V_1']=[(0,0)]
    with pytest.raises(ValueError):worker.check_source_membership(model,vertices,splittings)


def test_none_for_absent_name_stops_before_diagram_generation_and_retains_census(tmp_path):
    c=cfg();calls=[];writes=[]
    model=SimpleNamespace(particles=lambda:[],vertices=lambda:[],splitting=lambda name:None)
    engine=SimpleNamespace(DiagramGenerator=lambda *args:calls.append('generate'),
                           DiagramSelector=lambda:object(),set_threads=lambda n:calls.append('threads'))
    with pytest.raises(ValueError,match='actual native membership'):
        worker.enumerate_processes(c,engine,model,tmp_path,lambda value:writes.append(deepcopy(value)))
    assert calls==[] and writes[0]['complete'] is False
    assert writes[0]['model_vertices']==[]
    assert writes[0]['source_vertex_splittings']==[{'name':'V_1','splitting':None}]


def test_parent_delivery_rechecks_real_native_membership(tmp_path):
    c=cfg();writes=[]
    model=SimpleNamespace(particles=lambda:[],
        vertices=lambda:[SimpleNamespace(name=lambda:'V_1',coupling_orders=lambda:{})],
        splitting=lambda name:None)
    class Generator:
        def __init__(self,*args):assert args[3] is model
        def set_momentum_labels(self,value):assert value==c['processes'][0]['momentum_labels']
        def generate(self):return []
    engine=SimpleNamespace(DiagramGenerator=Generator,DiagramSelector=lambda:object(),set_threads=lambda n:None)
    result=worker.enumerate_processes(c,engine,model,tmp_path,lambda value:writes.append(deepcopy(value)))
    assert fg.check_delivery(c,result,tmp_path) is result and result['complete'] is True
    result['model_vertices']=[]
    with pytest.raises(ValueError,match='actual native membership'):fg.check_delivery(c,result,tmp_path)
