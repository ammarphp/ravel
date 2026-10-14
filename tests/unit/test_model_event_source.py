"""Portable controls for explicit copied MG source derivation; no native calls."""
import ast
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from ravel.physics import model_event_source as s
from ravel.physics import model_events as m


def test_make_opts_binds_only_explicit_defaults_and_is_idempotent():
    raw=(b'DEFAULT_F2PY_COMPILER=f2py\nDEFAULT_F_COMPILER=gfortran\n'
         b'OTHER=preserved\n#end_of_make_opts_variables\n\n  FFLAGS+= -O2\n')
    expected=(b'DEFAULT_F_COMPILER=/admitted/gfortran\nDEFAULT_F2PY_COMPILER=f2py\n'
              b'OTHER=preserved\n#end_of_make_opts_variables\n\nFFLAGS+= -O2')
    assert s.make_opts(raw,'/admitted/gfortran')==expected
    assert s.make_opts(expected,'/admitted/gfortran')==expected


@pytest.mark.parametrize('compiler',[None,'','/tool/path\nFFLAGS=changed','/tool;operation'])
def test_make_opts_requires_literal_explicit_tool(compiler):
    with pytest.raises(ValueError,match='literal explicit'):
        s.make_opts(b'DEFAULT_F_COMPILER=gfortran\n',compiler)


def parser_source():
    return b'''class UFOExpressionParser:
    def __init__(self):
        self.tabmodule = "unchanged-source-table.py"
        yacc.yacc(module=self, debug=0, debugfile="unchanged-debug", tabmodule=self.tabmodule)
    def parse(self, value):
        return value
'''


def test_supported_parser_switch_preserves_every_other_source_byte_and_result():
    raw=parser_source();derived=s.no_parser_table_cache(raw)
    assert derived.replace(b', write_tables=False)',b')')==raw
    recorded=[]
    def construct(**kwargs):recorded.append(kwargs)
    classes=[]
    for source in (raw,derived):
        env={'yacc':SimpleNamespace(yacc=construct)}
        exec(compile(ast.parse(source),'pure-constructor-control','exec'),env)
        classes.append(env['UFOExpressionParser']())
    assert classes[0].parse('same expression')==classes[1].parse('same expression')
    assert 'write_tables' not in recorded[0] and recorded[1].pop('write_tables') is False
    recorded[0].pop('module');recorded[1].pop('module')
    assert recorded[0]==recorded[1]


def test_unknown_table_call_shape_refuses():
    with pytest.raises(ValueError,match='ambiguous'):
        s.no_parser_table_cache(parser_source()+b'# tabmodule=self.tabmodule)\n')


def test_complete_derived_census_still_refuses_new_parser_source(tmp_path,monkeypatch):
    roots={}
    for name in ('madgraph','model'):
        original=tmp_path/(name+'-original');original.mkdir();(original/'source.py').write_text('original\n')
        manifest=tmp_path/(name+'.json');manifest.write_text(json.dumps(s.bridge.source_tree(original)))
        copy=tmp_path/(name+'-copy');copy.mkdir();(copy/'source.py').write_text('original\n')
        roots[name]={'spec':{'root':str(original),'manifest':{'path':str(manifest),'sha256':s.bridge._hash(manifest)}},'copy':copy}
    expected=s.bridge.source_tree(roots['madgraph']['copy'])
    request={'config':{'runtime':{'madgraph_tree':roots['madgraph']['spec']},'model_tree':roots['model']['spec']},
             'madgraph':str(roots['madgraph']['copy']),'model':str(roots['model']['copy']),
             'source_preparation':{'path':'inert-control-record','sha256':'a'*64}}
    monkeypatch.setattr(s,'expected',lambda *_:(expected,{'transformations':[]}))
    output=tmp_path/'outputs';output.mkdir()
    m._copied_source_custody(request,output,'pure-complete')
    (roots['madgraph']['copy']/'py.py').write_text('unadmitted generated executable parser source\n')
    with pytest.raises(ValueError,match='source/driver changed'):
        m._copied_source_custody(request,output,'pure-extra')
    report=json.loads((output/'copied-source-pure-extra.json').read_bytes())
    assert report['mismatches']==['madgraph']
    assert 'py.py' in report['components'][0]['observed']['files']


def test_source_derivation_refuses_unknown_upstream_before_copy(tmp_path):
    original=tmp_path/'original';original.mkdir();(original/'arbitrary.txt').write_text('unknown release\n')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(s.bridge.source_tree(original)))
    config={'runtime':{'madgraph_tree':{'root':str(original),'manifest':{'path':str(manifest),'sha256':s.bridge._hash(manifest)}},
                       'options':{'fortran_compiler':'/admitted/gfortran'}}}
    with pytest.raises(ValueError,match='missing reviewed source preparation API'):
        s.derive(config,tmp_path)
    assert s.bridge.source_tree(original)==json.loads(manifest.read_bytes())


def decorated_source():
    return b'class Bound:\n    @staticmethod\n    def admitted(x):\n        # exact source comment\n        return x\n'


def test_literal_function_binding_retains_decorator_comment_and_body():
    raw=decorated_source()
    bound=s._function_source(raw,'admitted','reviewed.py')
    assert bound==raw.split(b'class Bound:\n',1)[1]
    for before,after in ((b'@staticmethod',b'@classmethod'),
                         (b'exact source comment',b'changed comment'),
                         (b'return x',b'return -x')):
        assert s._sha(s._function_source(raw.replace(before,after),'admitted','reviewed.py'))!=s._sha(bound)


def test_legacy_ast_empty_version_field_projection_keeps_literal_source(monkeypatch):
    raw=decorated_source();observed=s._function_source(raw,'admitted','reviewed.py')
    tree=ast.parse(raw.decode());node=s._function(tree,'admitted','reviewed.py')
    if 'type_params' in node._fields:
        assert node.type_params==[]
        node._fields=tuple(name for name in node._fields if name!='type_params')
        del node.type_params
    monkeypatch.setattr(s.ast,'parse',lambda *_:tree)
    assert s._function_source(raw,'admitted','reviewed.py')==observed


def test_nonempty_added_type_parameters_refuse_before_source_admission(monkeypatch):
    raw=decorated_source();tree=ast.parse(raw.decode())
    s._function(tree,'admitted','reviewed.py').type_params=[ast.Name(id='Unadmitted')]
    monkeypatch.setattr(s.ast,'parse',lambda *_:tree)
    with pytest.raises(ValueError,match='type parameters'):
        s._function_source(raw,'admitted','reviewed.py')


def test_record_is_consumed_from_authenticated_buffer_without_pathname_reread(tmp_path,monkeypatch):
    tmp_path=tmp_path.resolve();copied=tmp_path/'copied';copied.mkdir()
    out=tmp_path/'output';out.mkdir();path=out/'copied-source-preparation.json'
    witness={'selected_fortran_compiler':'/admitted/compiler','copied_root':str(copied)}
    legitimate=json.dumps(witness).encode()
    forged=json.dumps({**witness,'selected_fortran_compiler':'/forged/compiler'}).encode()
    path.write_bytes(forged)
    request={'config':{},'source_preparation':{'path':str(path),'sha256':s._sha(forged)},'madgraph':str(copied)}
    monkeypatch.setattr(s,'derive',lambda *_:({'files':{}},{'selected_fortran_compiler':'/admitted/compiler'},{}))
    reads=[]
    def unauthenticated_read(target):
        reads.append(str(target))
        path.write_bytes(legitimate)
        try:return json.loads(path.read_bytes())
        finally:path.write_bytes(forged)
    monkeypatch.setattr(s.bridge,'_read',unauthenticated_read)
    with pytest.raises(ValueError,match='independently derived'):
        s.expected(request,out)
    assert reads==[] and path.read_bytes()==forged
    path.write_bytes(legitimate);request['source_preparation']['sha256']=s._sha(legitimate)
    assert s.expected(request,out)[1]==witness


def test_record_actual_buffer_must_match_declared_pin(tmp_path,monkeypatch):
    tmp_path=tmp_path.resolve();copied=tmp_path/'copied';copied.mkdir()
    out=tmp_path/'output';out.mkdir();path=out/'copied-source-preparation.json'
    path.write_text('{}')
    request={'config':{},'source_preparation':{'path':str(path),'sha256':'f'*64},'madgraph':str(copied)}
    monkeypatch.setattr(s,'derive',lambda *_:({}, {}, {}))
    with pytest.raises(ValueError,match='differs from complete manifest'):
        s.expected(request,out)


@pytest.mark.parametrize('raw',[b'{"schema_version":1,"schema_version":1}',b'{"x":Infinity}',b'{"x":1e1000}'])
def test_authenticated_document_preserves_strict_json_number_and_unique_key_policy(tmp_path,raw):
    p=tmp_path.resolve()/'record.json';p.write_bytes(raw)
    with pytest.raises(ValueError,match='duplicate JSON|non-finite'):
        s._document(p,s._sha(raw))


@pytest.mark.parametrize('relative',s.PARSER_SOURCES)
def test_both_parser_sources_preserve_all_bytes_except_cache_keyword(relative):
    raw=parser_source()
    derived=s.no_parser_table_cache(raw,relative)
    assert derived.replace(b', write_tables=False)',b')')==raw


def test_unknown_parser_path_cannot_acquire_transformation_authority():
    with pytest.raises(ValueError,match='unsupported parser'):
        s.no_parser_table_cache(parser_source(),'unreviewed/new_parser.py')


def test_ufo_source_selects_base_constructor_among_subclass_overrides():
    raw=parser_source()+b'class DifferentSubclass(UFOExpressionParser):\n    def __init__(self):\n        self.different=True\n'
    assert s._function_source(raw,'__init__','madgraph/iolibs/ufo_expression_parsers.py').startswith(b'    def __init__')
    derived=s.no_parser_table_cache(raw,'madgraph/iolibs/ufo_expression_parsers.py')
    assert derived.replace(b', write_tables=False)',b')')==raw
