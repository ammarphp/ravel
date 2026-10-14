"""Explicit copied-driver derivation for the source-reviewed MG export API.

Original source remains an input. Three copied files get deterministic, recorded
transformations before any native call. Every phase still checks full membership
and bytes; no parser-table or makefile output is excluded from source custody.
"""
import ast
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re

from ravel.physics import model_tool_bridge as bridge
from ravel.physics.model_event_weights import require
from ravel.workflow.state_io import _unique

PARSER_SOURCES = ('aloha/aloha_parsers.py', 'madgraph/iolibs/ufo_expression_parsers.py')


API = {
    ('madgraph/interface/common_run_interface.py', 'update_make_opts_full'):
        '78ce7c2b02e67f4ed3666d3b75e864455d7d32eec48e83c2b532635a0d81a0ad',
    ('madgraph/iolibs/export_v4.py', 'set_fortran_compiler'):
        '07262caa855fa78cd7c557247e21c9a3762622caa01e4695012bf53fad5c2dbf',
    ('aloha/aloha_parsers.py', '__init__'):
        'b895c123b5bfc0b020d04e0eeb702a1e0ef4c31a37aee35c5596be665a7febc8',
    ('madgraph/iolibs/ufo_expression_parsers.py', '__init__'):
        'cdb90148fa8f0dfe2a0136b2957703ceeedd55320b1f8c4d91b9f9928e5eacb1',
    ('vendor/ply/lex.py', 'lex'):
        'f3cc1f95ed7400d947e9e317a5c2daa71f20c806e8b1b822236f62e253ba11df',
    ('vendor/ply/yacc.py', 'write_table'):
        '24eb2b91a00c16f14a041dec5646f18b2a8259b3070bea96c211b82413bfe7f5',
    ('vendor/ply/yacc.py', 'yacc'):
        '92eeac929c448159b217f5092471547fa2d7574889dd95e7cb87cc2fecbc7715',
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, expected):
    path = bridge._regular(str(path), Path.cwd())
    before = path.stat()
    require(before.st_size <= 2 * 1024**2, 'source preparation document exceeds 2MiB')
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(2 * 1024**2 + 1)
        closed = os.fstat(stream.fileno())
    require(len(raw) <= 2 * 1024**2 and identity(before) == identity(opened) ==
            identity(closed) == identity(path.stat()), 'source changed during derivation')
    require(_sha(raw) == expected, 'source derivation input differs from complete manifest')
    return raw


def _document(path, expected):
    """Parse only the descriptor-checked bytes authenticated by the declared pin."""
    def reject(value):
        raise ValueError('non-finite preparation document number: ' + value)
    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), 'non-finite preparation document number: ' + value)
        return number
    return json.loads(_read(path, expected), object_pairs_hook=_unique,
                      parse_constant=reject, parse_float=finite_float)


def _function(tree, name, relative):
    if relative in PARSER_SOURCES:
        found = [n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'UFOExpressionParser'
                 for n in c.body if isinstance(n, ast.FunctionDef) and n.name == name]
    else:
        found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    require(len(found) == 1, 'ambiguous source preparation API: ' + relative + '/' + name)
    return found[0]


def _function_source(raw, name, relative):
    """Exact decorated source span, independent of interpreter AST dump display.

No AST fields are removed. The admitted legacy functions have no type parameters;
future nonempty type parameters refuse. Decorator lines, body and comments inside
the function span are all literal inputs. Parser transformation equivalence still
compares full trees within the same interpreter.
"""
    source = raw.decode('utf-8')
    function = _function(ast.parse(source), name, relative)
    require(not getattr(function, 'type_params', []), 'unsupported source API type parameters')
    start = min([function.lineno] + [d.lineno for d in function.decorator_list])
    end = function.end_lineno
    lines = source.splitlines(keepends=True)
    require(type(end) is int and 1 <= start <= end <= len(lines), 'source API span is incomplete')
    return ''.join(lines[start-1:end]).encode('utf-8')


def make_opts(raw, compiler):
    """Pure replay of reviewed update_make_opts_full with these two defaults.

The selected explicit Fortran path is already a required native input. Upstream
uses f2py when available and otherwise an empty value that this writer converts
back to the same literal f2py default. No compiler or tool probe is performed.
"""
    require(type(compiler) is str and compiler and not re.search(r'[\s;\'"\\]', compiler),
            'literal explicit Fortran selection required for source derivation')
    pattern = re.compile(r'^(\w+)\s*=\s*(.*)$', re.DOTALL)
    variables = {'DEFAULT_F_COMPILER': compiler, 'DEFAULT_F2PY_COMPILER': 'f2py'}
    need_keys = list(variables)
    content = []
    editing = True
    changed = False
    for original in raw.decode('utf-8').splitlines():
        line = original.strip()
        if editing:
            if line.startswith('#') or not line:
                if line.startswith('#end_of_make_opts_variables'):
                    editing = False
                continue
            match = pattern.search(line)
            if match:
                key, value = match.groups()
                if key not in variables:
                    variables[key] = value
                elif value != variables[key]:
                    changed = True
                else:
                    require(key in need_keys, 'duplicate selected compiler default')
                    need_keys.remove(key)
            else:
                editing = False
                content.append(line)
        else:
            content.append(line)
    if need_keys:
        changed = True
    if not changed:
        return raw
    definitions = '\n'.join('%s=%s' % (k, v) for k, v in variables.items() if v is not None)
    return (definitions + '\n#end_of_make_opts_variables\n' + '\n'.join(content)).encode('utf-8')


def no_parser_table_cache(raw, relative='aloha/aloha_parsers.py'):
    """Use PLY's supported disk-cache switch; retain all parser/grammar AST."""
    require(relative in PARSER_SOURCES, 'unsupported parser table-cache source')
    source = raw.decode('utf-8')
    needle = 'tabmodule=self.tabmodule)'
    require(source.count(needle) == 1, 'ambiguous parser table-cache call: ' + relative)
    updated = source.replace(needle, 'tabmodule=self.tabmodule, write_tables=False)', 1)
    before, after = ast.parse(source), ast.parse(updated)
    constructor = _function(after, '__init__', relative)
    calls = [n for n in ast.walk(constructor) if isinstance(n, ast.Call) and
             isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and
             n.func.value.id == 'yacc' and n.func.attr == 'yacc']
    require(len(calls) == 1, 'ambiguous parser yacc construction: ' + relative)
    keywords = [k for k in calls[0].keywords if k.arg == 'write_tables']
    require(len(keywords) == 1 and isinstance(keywords[0].value, ast.Constant) and
            keywords[0].value.value is False, 'disk-cache switch did not bind')
    calls[0].keywords.remove(keywords[0])
    require(ast.dump(before, include_attributes=False) == ast.dump(after, include_attributes=False),
            'parser preparation changed grammar or computation')
    return updated.encode('utf-8')


def derive(config, base):
    """Return expected full derived census and pure transform witness."""
    root, manifest, _ = bridge._tree(config['runtime']['madgraph_tree'], base)
    original_pin = config['runtime']['madgraph_tree']['manifest']['sha256']
    original = _document(manifest, original_pin)
    inputs = {}
    witnesses = []
    for (relative, name), expected in API.items():
        require(relative in original['files'], 'missing reviewed source preparation API: ' + relative)
        raw = inputs.setdefault(relative, _read(root/relative, original['files'][relative]))
        observed = _sha(_function_source(raw, name, relative))
        require(observed == expected, 'unsupported source preparation API: ' + relative + '/' + name)
        witnesses.append({'path': str(root/relative), 'source_sha256': original['files'][relative],
                          'function': name, 'function_source_sha256': observed})
    relative = 'Template/LO/Source/make_opts'
    require(relative in original['files'], 'missing complete make_opts source')
    raw = _read(root/relative, original['files'][relative])
    compiler = config['runtime']['options']['fortran_compiler']
    require(compiler is not None, 'explicit admitted Fortran input required')
    rewritten = {
        relative: make_opts(raw, compiler),
        **{path: no_parser_table_cache(inputs[path], path) for path in PARSER_SOURCES},
    }
    expected = deepcopy(original)
    transformations = []
    for relative, content in rewritten.items():
        expected['files'][relative] = _sha(content)
        transformations.append({'relative_path': relative, 'original_sha256': original['files'][relative],
                                'derived_sha256': _sha(content), 'derived_size': len(content)})
    witness = {'schema_version': 1, 'kind': 'deterministic-copied-mg-export-source',
               'original_root': str(root), 'original_manifest': {'path': str(manifest), 'sha256': original_pin},
               'selected_fortran_compiler': compiler, 'api_witnesses': witnesses,
               'transformations': transformations, 'derived_manifest': expected,
               'cache_policy': 'disable both source-bound UFOExpressionParser yacc disk tables; grammar/parser unchanged',
               'scientific_original_modified': False, 'native_qualification': False}
    return expected, witness, rewritten


def prepare(request, output):
    """Transform an exact fresh independent work copy, retain full witness."""
    output = bridge._regular(str(output), Path.cwd(), directory=True)
    path = output/'copied-source-preparation.json'
    require(not path.exists() and not path.is_symlink(), 'preserve existing source derivation record')
    base = Path(request.get('source_base', Path.cwd()))
    expected, witness, replacements = derive(request['config'], base)
    original = _document(witness['original_manifest']['path'], witness['original_manifest']['sha256'])
    copied = bridge._regular(request['madgraph'], Path.cwd(), directory=True)
    origin = Path(witness['original_root'])
    require(copied != origin and not copied.is_relative_to(origin) and not origin.is_relative_to(copied),
            'source preparation requires a separate work copy')
    require(bridge.source_tree(copied) == original, 'fresh copied original differs before derivation')
    # All transformation originals have been authenticated before the first copied write.
    for relative, content in replacements.items():
        target = bridge._regular(str(copied/relative), Path.cwd())
        require(bridge._hash(target) == original['files'][relative], 'copied transformation input changed')
        with target.open('wb') as stream:
            stream.write(content)
        require(bridge._hash(target) == expected['files'][relative], 'copied source derivation write differs')
    require(bridge.source_tree(copied) == expected, 'derived copied source membership/bytes differ')
    require(bridge._tree(request['config']['runtime']['madgraph_tree'], base)[0] == origin,
            'original source changed during copied derivation')
    witness['copied_root'] = str(copied)
    with path.open('x') as stream:
        json.dump(witness, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return {'path': str(path), 'sha256': bridge._hash(path)}


def expected(request, output):
    """Recompute from original inputs, authenticate retained preparation record."""
    expected, witness, _ = derive(request['config'], Path(request.get('source_base', Path.cwd())))
    pin = request['source_preparation']
    require(set(pin) == {'path', 'sha256'}, 'exact source preparation record pin required')
    path = bridge._regular(pin['path'], Path.cwd())
    require(path == bridge._regular(str(Path(output)/'copied-source-preparation.json'), Path.cwd()),
            'source preparation record belongs to another output')
    witness['copied_root'] = str(bridge._regular(request['madgraph'], Path.cwd(), directory=True))
    record = _document(path, pin['sha256'])
    require(record == witness, 'source preparation witness differs from independently derived source')
    return expected, witness
