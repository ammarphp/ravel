"""Run admitted external NDA methods without the upstream agent framework.

Only the deterministic dependency closure is compiled from authenticated bytes.
The two framework declarations are replaced in memory with RAVEL-owned field
and keyword-initialization support. No upstream files are edited or vendored;
no orchestral package or HEPTAPOD package initializer is imported. This is a
transport adaptation, not a new width algorithm or physics qualification.
"""
import ast
import builtins
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType


# Ordered public deterministic dependencies; package initializers are excluded.
MODULES = (
    'tools.nda.topology', 'tools.nda.particle_database',
    'tools.nda.quantum_validation', 'tools.nda.simple_diagram',
    'tools.nda.phase_space', 'tools.nda.matrix_element',
    'tools.nda.summary_formatting', 'tools.logging.findings', 'tools.nda.nda_tool',
)
PACKAGES = ('tools', 'tools.nda', 'tools.logging')
FRAMEWORK_DECLARATIONS = {
    'orchestral.tools.base.tool': ('BaseTool',),
    'orchestral.tools.base.field_utils': ('RuntimeField', 'StateField'),
}
MISSING = object()


class Unavailable(ValueError):
    """The supplied source closure needs a separately implemented adaptation."""


class _NoFramework:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'orchestral' or fullname.startswith('orchestral.'):
            raise Unavailable('NDA framework import is prohibited: ' + fullname)
        return None


class _Field:
    def __init__(self, *, description, default=MISSING):
        self.default = default


class _DeterministicTool:
    """Only the keyword/field/error API used by the selected NDA methods.

    Inputs remain governed by the model-derived request and upstream methods.
    This class supplies no agent, tool dispatch, state persistence or execution.
    """
    def __init__(self, **values):
        fields = {name: field for cls in reversed(type(self).__mro__)
                  for name, field in vars(cls).items() if isinstance(field, _Field)}
        if set(values) - set(fields):
            raise Unavailable('NDA constructor needs unsupported fields')
        for name, field in fields.items():
            if name in values:
                value = values[name]
            elif field.default is not MISSING:
                value = deepcopy(field.default)
            else:
                raise ValueError('NDA required field missing: ' + name)
            setattr(self, name, value)

    @staticmethod
    def format_error(*, error, reason, suggestion=None):
        result = {'status': 'error', 'error': error, 'reason': reason}
        if suggestion is not None:
            result['suggestion'] = suggestion
        return json.dumps(result, allow_nan=False)


def check(assets):
    for p, h in assets.items():
        if (not Path(p).is_file() or Path(p).is_symlink()
                or hashlib.sha256(Path(p).read_bytes()).hexdigest() != h):
            raise ValueError('NDA native input changed')


def _unavailable(item, reason):
    return {'id': item['id'], 'status': 'unavailable', 'reason': str(reason),
            'requires': 'Admit the complete pinned deterministic source closure and a RAVEL adaptation of the named API.'}


def _tree(raw, filename):
    """Remove only the released declarations, without importing their package."""
    tree = ast.parse(raw, filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in FRAMEWORK_DECLARATIONS:
            if (node.level or tuple(n.name for n in node.names) != FRAMEWORK_DECLARATIONS[node.module]
                    or any(n.asname for n in node.names) or node not in tree.body):
                raise Unavailable('NDA framework declaration differs: ' + node.module)
            tree.body[tree.body.index(node)] = ast.copy_location(ast.Pass(), node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or '']
            if any(n == 'orchestral' or n.startswith('orchestral.') for n in names):
                raise Unavailable('NDA requires unsupported framework API')
    return ast.fix_missing_locations(tree)


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'orchestral' or name.startswith('orchestral.'):
        raise Unavailable('NDA framework import is prohibited')
    if (name == 'tools' or name.startswith('tools.')) and name not in (*PACKAGES, *MODULES):
        raise Unavailable('NDA import outside deterministic module closure: ' + name)
    return builtins.__import__(name, globals, locals, fromlist, level)


@contextmanager
def backend(request):
    if any(n == 'orchestral' or n.startswith('orchestral.') for n in sys.modules):
        raise Unavailable('NDA requires an isolated interpreter without the framework loaded')
    root = Path(request['source_root']).resolve()
    sources = {}
    # Authenticate and parse the entire closure before executing any dependency.
    for name in MODULES:
        path = root/(name.replace('.', '/') + '.py')
        if path.is_symlink() or not path.is_file() or str(path) not in request['assets']:
            raise Unavailable('NDA deterministic source missing or unadmitted: ' + name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != request['assets'][str(path)]:
            raise ValueError('NDA captured source changed')
        sources[name] = (path, _tree(raw, str(path)))
    old = {n: m for n, m in sys.modules.items() if n == 'tools' or n.startswith('tools.')}
    old_path = sys.path[:]
    guard = _NoFramework()
    try:
        sys.meta_path.insert(0, guard)
        for name in old:
            del sys.modules[name]
        sys.path[:0] = request['sites']
        for name in PACKAGES:
            module = ModuleType(name); module.__path__ = []
            sys.modules[name] = module
        for name, (path, tree) in sources.items():
            module = ModuleType(name); module.__file__ = str(path)
            module.__package__ = name.rpartition('.')[0]
            module.__dict__.update(BaseTool=_DeterministicTool, RuntimeField=_Field, StateField=_Field)
            module.__dict__['__builtins__'] = dict(vars(builtins), __import__=_import)
            sys.modules[name] = module
            exec(compile(tree, str(path), 'exec'), module.__dict__)
        yield sys.modules[MODULES[-1]]
        for name, module in list(sys.modules.items()):
            if name == 'orchestral' or name.startswith('orchestral.'):
                raise Unavailable('NDA framework module loaded')
            if name == 'tools' or name.startswith('tools.'):
                path = getattr(module, '__file__', None)
                if name not in (*PACKAGES, *MODULES) or (path is not None and str(Path(path).resolve()) not in request['assets']):
                    raise ValueError('NDA import outside admitted physical source/runtime: ' + name)
    finally:
        sys.meta_path.remove(guard)
        for name in list(sys.modules):
            if name == 'tools' or name.startswith('tools.'):
                del sys.modules[name]
        sys.modules.update(old)
        sys.path[:] = old_path


def main():
    p = Path(sys.argv[1]); raw = p.read_bytes(); r = json.loads(raw); check(r['assets'])
    if (hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != r['driver_sha256']
            or str(Path(sys.executable).resolve()) not in r['assets']):
        raise ValueError('NDA selected driver/interpreter differs')
    rows = []
    try:
        with backend(r) as mod:
            for item in r['diagrams']:
                directory = Path(r['output'])/item['id']; directory.mkdir()
                try:
                    value = mod.EstimateDecayWidthNDATool(diagram=item['diagram'], include_summary=False,
                                                        base_directory=str(directory))._run()
                    parsed = json.loads(value)
                    rows.append({'id': item['id'], 'status': 'delivered' if parsed.get('status') == 'ok' else 'failed',
                                 'raw': value, 'result': parsed,
                                 'approximation': 'released HEPTAPOD per-diagram NDA; no coherent interference'})
                except (Unavailable, ImportError) as e:
                    rows.append(_unavailable(item, e))
                except Exception as e:
                    rows.append({'id': item['id'], 'status': 'failed', 'error': type(e).__name__ + ': ' + str(e)})
    except (Unavailable, ImportError) as e:
        rows = [_unavailable(item, e) for item in r['diagrams']]
    check(r['assets'])
    if p.read_bytes() != raw:
        raise ValueError('NDA request changed')
    (Path(r['output'])/'nda-result.json').write_text(json.dumps({'schema_version': 1, 'rows': rows}, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
