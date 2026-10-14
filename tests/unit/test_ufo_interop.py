"""Literal conversion, preservation and diagnostic controls; no UFO import."""
import ast
from pathlib import Path
import stat
import pytest
from ravel.physics import ufo_interop as interop, model_derivation_bridge as bridge
from test_model_derivation_bridge import bound, native, PARAMETERS, exported_model

@pytest.mark.parametrize('literal',["'plain'",'"escaped \\\" quote"',"u'Unicode Ω'",'"same # ; , tokens"'])
def test_literal_raise_constructor_preserves_exception_message(literal):
    source='raise UFOError, '+literal+' # retained comment\n'
    new,edits=interop.convert_text(source)
    expected=ast.literal_eval(literal)
    statement=ast.parse(new).body[0]
    assert isinstance(statement,ast.Raise)
    assert statement.exc.func.id=='UFOError' and ast.literal_eval(statement.exc.args[0])==expected
    assert edits==[{'line':1,'exception':'UFOError','message':expected}]
    assert '# retained comment' in new

def test_no_syntax_change_for_strings_comments_numeric_physics_or_modern_raises():
    source='text="raise UFOError, message"\n# raise UFOError, "ignored"\nvalue = 1 / 2\nraise UFOError("modern")\n'
    new,edits=interop.convert_text(source)
    assert new==source and edits==[]

@pytest.mark.parametrize('source',[
    'raise UFOError, dynamic_message\n','raise DifferentError, "message"\n',
    'raise UFOError, b"bytes"\n','raise UFOError, "message", traceback\n',
    'print "unrequested broad conversion"\n','raise UFOError, ("a", "b")\n',
])
def test_unimplemented_legacy_forms_refuse_without_broad_conversion(source):
    with pytest.raises((SyntaxError,ValueError)):interop.convert_text(source)

def source(tmp_path):
    root=tmp_path/'raw';root.mkdir()
    (root/'object_library.py').write_text('class UFOError(Exception):\n    pass\nraise UFOError, "same message"\n')
    (root/'parameters.py').write_text('MASS=172.0\n')
    (root/'empty.rst').write_bytes(b'');(root/'empty.rst').chmod(0o600)
    (root/'raw.pkl').write_bytes(b'complete non-Python member')
    return root

def test_complete_raw_source_bytes_modes_and_unrelated_parameters_preserved(tmp_path):
    root=source(tmp_path);before={str(p):p.read_bytes() for p in root.iterdir()}
    out=tmp_path/'converted';receipt=interop.convert_tree(root,out,interop.POLICY)
    assert receipt['raw_tree_unchanged'] is True and receipt['model_imported'] is False
    assert set(receipt['changed_files'])=={'object_library.py'}
    assert before=={str(p):p.read_bytes() for p in root.iterdir()}
    assert (out/'parameters.py').read_bytes()==(root/'parameters.py').read_bytes()
    assert (out/'empty.rst').stat().st_size==0 and stat.S_IMODE((out/'empty.rst').stat().st_mode)==0o600
    assert (out/'raw.pkl').read_bytes()==(root/'raw.pkl').read_bytes()

@pytest.mark.parametrize('which',['raw_member','raw_parent','output_existing','output_alias','output_inside_raw','unknown_policy'])
def test_alias_existing_or_implicit_conversion_is_refused(tmp_path,which):
    root=source(tmp_path);out=tmp_path/'converted';policy=interop.POLICY
    if which=='raw_member':
        p=root/'parameters.py';p.rename(root/'original.py');p.symlink_to(root/'original.py')
    if which=='raw_parent':
        root.rename(tmp_path/'original');root.symlink_to(tmp_path/'original',target_is_directory=True)
    if which=='output_existing':out.mkdir()
    if which=='output_alias':out.symlink_to(tmp_path/'future',target_is_directory=True)
    if which=='output_inside_raw':out=root/'converted'
    if which=='unknown_policy':policy='auto-convert-everything'
    with pytest.raises(ValueError):interop.convert_tree(root,out,policy)

def test_config_conversion_is_explicit_and_default_preserves_original_policy():
    from test_model_derivation_bridge import config
    c=config();assert bridge.validate_config(c)==c and 'ufo_python_compatibility' not in c
    assert bridge.validate_config({**c,'ufo_python_compatibility':interop.POLICY})['ufo_python_compatibility']==interop.POLICY
    with pytest.raises(ValueError):bridge.validate_config({**c,'ufo_python_compatibility':'automatic'})

def test_private_import_origin():
    assert Path(interop.__file__).resolve().parent == Path(bridge.__file__).resolve().parent

@pytest.mark.parametrize('policy,unsupported', [('none',False),(interop.POLICY,False),(interop.POLICY,True)])
def test_parse_or_conversion_cannot_erase_failed_kinetic_checks(bound,monkeypatch,policy,unsupported):
    """Actual run/adjudication code with explicit synthetic native return."""
    from ravel.physics import model_tool_bridge as custody, reinterpret_db
    base,c,path,prior,receipt=bound
    if policy!='none':c['ufo_python_compatibility']=policy;custody._write(path,c)
    out=base/'outputs/attempt-1'
    monkeypatch.setattr(bridge,'_approved',lambda *args:(base,{'max_seconds':900}))
    def fake_native(command,output,document):
        work=base/'work/model-derivation-bridge/attempt-1'
        # An otherwise admissible synthetic export: only its object library carries the Python 2 raise.
        exported=exported_model(output/'exported-ufo',**{'object_library.py':'class UFOError(Exception):\n    pass\nraise UFOError, '
            +('dynamic_message' if unsupported else '"same message"')+'\n'})
        raw=native();raw.update(provider_root=str(work/'feynrules'),model_root=str(work/'model_source'),export_root=str(exported),model_files=[str(work/'model_source/SM.fr')],kinetic_result=False,kinetic_result_expression='Null')
        raw['source_loads']['requested_model_files']=raw['model_files'][:]
        custody._write(output/'native-derivation.json',raw);custody._write(output/'native-process.json',{'pid':123})
        return {'returncode':0,'command':command,'scope':'synthetic source-only fixture; no kernel call'}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake_native)
    result=bridge.run({'config':str(path)},base,out)
    checks=custody._read(out/'derivation-checks.json')
    assert checks['passed'] is False and checks['checks']['evaluated_kinetic_normalisation'] is False
    assert result['status']=='failed' and result['handoff_eligible'] is False and result['physics_validated'] is False
    assert not (out/'model-tool-handoff-candidate.json').exists()
    assert 'raise UFOError, ' in (out/'exported-ufo/object_library.py').read_text()
    if policy=='none' or unsupported:
        assert result['export_diagnostics'] and result['exported_source'] is None
    else:
        assert result['export_diagnostics']==[] and result['exported_source']['ufo']==str(out/'exported-ufo-python3')
        assert custody._read(out/'export-static-admission.json')['decision']=='passed'
        assert (out/'exported-ufo-python3/parameters.py').read_text()==PARAMETERS

@pytest.mark.parametrize('definition',['class UFOError(Exception):\n    def __init__(self,*args): pass\n',
    'class UFOError(ValueError):\n    pass\n','UFOError = SomeInstance\n',
    'class UFOError(Exception):\n    pass\ndef f(UFOError):\n    return UFOError\n'])
def test_unobserved_exception_constructor_semantics_refuse(tmp_path,definition):
    root=source(tmp_path);(root/'object_library.py').write_text(definition+'raise UFOError, "message"\n')
    with pytest.raises(ValueError,match='canonical pass-only'):interop.convert_tree(root,tmp_path/'converted',interop.POLICY)


@pytest.mark.parametrize('binding',[
    'def UFOError(message):\n    return RuntimeError(message)\n',
    'async def UFOError(message):\n    return RuntimeError(message)\n',
    'from builtins import RuntimeError as UFOError\n',
    'import builtins as UFOError\n',
    'import UFOError.submodule\n',
    'from another_module import UFOError\n',
    'from another_module import *\n',
    'del UFOError\n',
    'try:\n    pass\nexcept Exception as UFOError:\n    pass\n',
    'match {}:\n    case {"key": UFOError}: pass\n',
    'match []:\n    case [*UFOError]: pass\n',
    'match {}:\n    case {**UFOError}: pass\n',
    'def outer():\n    def UFOError(message):\n        return RuntimeError(message)\n',
    'def outer():\n    from builtins import RuntimeError as UFOError\n',
    'def outer():\n    global UFOError\n',
    'def outer():\n    class UFOError(Exception):\n        pass\n',
])
def test_other_static_exception_bindings_refused_without_model_import(tmp_path,binding):
    root=source(tmp_path)
    (root/'object_library.py').write_text('class UFOError(Exception):\n    pass\n'+binding+'raise UFOError, "same message"\n')
    with pytest.raises(ValueError,match='canonical pass-only'):
        interop.convert_tree(root,tmp_path/'converted',interop.POLICY)
