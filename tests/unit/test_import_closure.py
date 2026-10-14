"""Synthetic distribution boundaries and import resolution."""
import json
from pathlib import Path
import pytest
from ravel.validation.import_closure import check


def tree(tmp_path, source, *, internal=('src/ravel/alpha.py',)):
    for path, content in {'src/ravel/__init__.py':'', 'src/ravel/alpha.py':'VALUE = 1',
                          'src/ravel/beta.py':source, 'tests/test_gamma.py':'from ravel import alpha'}.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    registry = {'schema_version':2, 'distribution':{'files':[], 'extra_files':[],
                'trees':['src','tests','scripts'], 'exclude':[], 'internal':list(internal)}}
    (tmp_path/'distribution.json').write_text(json.dumps(registry))
    return tmp_path


@pytest.mark.parametrize('source', ['import ravel.alpha', 'from . import alpha',
                                  'from ravel import alpha', 'from .alpha import VALUE'])
def test_module_import_reports_file_line(tmp_path, source):
    result = check(tree(tmp_path, source), dynamic=False)
    assert any(r['file']=='src/ravel/beta.py' and r['line']==1 and r['module']=='ravel.alpha'
               for r in result['static'])
    assert any(r['file']=='tests/test_gamma.py' for r in result['static'])


def test_function_import_and_withheld_test_are_allowed(tmp_path):
    root = tree(tmp_path, 'def value():\n    from ravel import alpha\n',
                internal=('src/ravel/alpha.py','tests/test_gamma.py'))
    assert check(root)['ok']


def test_empty_set_passes(tmp_path):
    assert check(tree(tmp_path, 'from ravel import alpha', internal=()))['ok']


def test_dynamic_refuses_eager_indirect_import(tmp_path):
    root = tree(tmp_path, "import importlib\nimportlib.import_module('ravel.alpha')",
                internal=('src/ravel/alpha.py','tests/test_gamma.py'))
    result = check(root)
    assert not result['ok']
    assert result['dynamic'][0]['module']=='ravel.beta'


def test_alternate_registry_controls_selection(tmp_path):
    root=tree(tmp_path,'from ravel import alpha')
    alternate=json.loads((root/'distribution.json').read_text())
    alternate['distribution']['internal']=['src/ravel/beta.py']
    path=root/'alternate.json';path.write_text(json.dumps(alternate))
    assert check(root,registry=path)['ok']


def test_dynamic_imports_only_the_package_namespace(tmp_path):
    root=tree(tmp_path,'def value():\n    from ravel import alpha\n',
              internal=('src/ravel/alpha.py','tests/test_gamma.py'))
    (root/'src/ravel_extra.py').write_text("raise RuntimeError('unrelated package must not be executed')")
    assert check(root)['ok']


def test_shipped_source_warnings_do_not_leak(tmp_path, recwarn):
    root=tree(tmp_path, "PATTERN = '\\\\s'\nPATTERN = '\\s'\n", internal=())
    assert check(root, dynamic=False)['ok']
    assert not [w for w in recwarn if issubclass(w.category, SyntaxWarning)]
