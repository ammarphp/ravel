"""Exact-content reuse laws; source discovery never imports discovered bodies."""
import ast
from collections import OrderedDict
from copy import deepcopy
import hashlib
import os
from pathlib import Path

import pytest

from ravel.workflow import capability_routing as routing
from ravel.workflow import research_coordinator_decisions as decisions
from ravel.workflow import source_syntax as syntax


@pytest.fixture(autouse=True)
def empty_facts_cache(monkeypatch):
    monkeypatch.setattr(syntax, '_CACHE', OrderedDict())
    monkeypatch.setattr(syntax, '_CACHE_BYTES', 0)


def _put(root, relative, raw):
    path = root / 'src/ravel' / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _source(tmp_path):
    _put(tmp_path, 'workflow/science.py', b'''MODES = ('first', 'second')
def adapter(spec):
    mapping = {'first': 'shared', 'second': 'shared'}
    return mapping[spec['mode']]
''')
    _put(tmp_path, 'physics/native_capabilities.py', b'CAPABILITIES = {}\n')
    adapter = _put(tmp_path, 'physics/shared.py', b'''"""Exact public contract."""
raise RuntimeError('discovery must never execute this body')
def validate(): pass
async def inputs(): pass
def run(): pass
''')
    for relative in ('workflow/intake.py', 'workflow/route_prompt.py', 'workflow/cost_preflight.py',
                     'validation/validate_task_contract.py', 'workflow/resource_census.py',
                     'workflow/routine_fetch.py', 'plotting/figure_target.py',
                     'plotting/figure_manifest.py', 'plotting/science_figures.py', 'analysis_catalog.py'):
        _put(tmp_path, relative, b'# current source\n')
    host = _put(tmp_path, 'workflow/agent_host.py', b"TOOLS = ('allowed-tool',)\n")
    extension = _put(tmp_path, 'workflow/extension.py', b'def prepare(): pass\n')
    return adapter, host, extension


def _coordinator(monkeypatch, tmp_path):
    monkeypatch.setattr(routing, '__file__', str(tmp_path / 'src/ravel/workflow/capability_routing.py'))
    monkeypatch.setattr(decisions, '__file__', str(tmp_path / 'src/ravel/workflow/research_coordinator_decisions.py'))
    monkeypatch.setattr(decisions, 'EXTENSIONS', {'prepare': ('ravel.workflow.extension', 'prepare')})
    monkeypatch.setattr(decisions, 'EXTENSION_TRANSPORT', {'prepare': {'arguments': [], 'returns': 'prepared only'}})
    monkeypatch.setattr(decisions, 'PREPARATION_TOOLS', ('allowed-tool', 'changed-tool'))


def test_original_ast_semantics_utf8_async_docstring_and_nested_scope():
    raw = '''"""  Source café contract.\n\n    Detailed law.\n"""
TEXT = '日本語'
async def inputs(): pass
def run():
    def nested(): pass
    return 'inside'
class C:
    def validate(self): pass
'''.encode('utf-8')
    doc, names, constants = syntax.facts(raw)
    assert doc == 'Source café contract.\n\nDetailed law.'
    assert names == ('inputs', 'run')
    assert constants == ('  Source café contract.\n\n    Detailed law.\n', 'inside', '日本語')
    assert type(doc) is str and type(names) is tuple and type(constants) is tuple


def test_equal_bytes_reuse_without_shared_mutable_ast_or_path_authority(monkeypatch):
    original = syntax.ast.parse
    calls = []
    def parsed(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(syntax.ast, 'parse', parsed)
    raw = b'def run(): pass\n'
    a = syntax.facts(raw, filename='first.py')
    b = syntax.facts(raw, filename='other.py')
    assert a == b == ('', ('run',), ())
    assert calls == [raw.decode('utf-8')]
    with pytest.raises(TypeError):
        a[1][0] = 'changed'
    assert syntax.facts(raw) == b
    assert all(type(key) is bytes for key in syntax._CACHE)


def test_syntax_failures_are_fresh_and_keep_each_current_path(monkeypatch):
    original = syntax.ast.parse
    calls = []
    def parsed(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(syntax.ast, 'parse', parsed)
    for filename in ('original.py', 'changed.py'):
        with pytest.raises(SyntaxError) as caught:
            syntax.facts(b'def broken(:\n', filename=filename)
        assert caught.value.filename == filename
    assert len(calls) == 2 and not syntax._CACHE
    assert syntax.facts(b'def repaired(): pass\n')[1] == ('repaired',)


def test_utf8_failure_is_not_cached_or_replaced_by_locale_decoding():
    for filename in ('bad-one.py', 'bad-two.py'):
        with pytest.raises(UnicodeDecodeError) as caught:
            syntax.facts(b'#\xff\n', filename=filename)
        assert caught.value.__notes__ == ['source path: ' + filename]
    assert not syntax._CACHE


def test_complete_catalogue_reuses_facts_but_reads_all_current_files(tmp_path, monkeypatch):
    adapter, _, _ = _source(tmp_path)
    original = routing._file
    reads = []
    def read(path):
        reads.append(str(path))
        return original(path)
    monkeypatch.setattr(routing, '_file', read)
    first = routing.catalogue(tmp_path)
    first_reads = list(reads)
    second = routing.catalogue(tmp_path)
    assert first == second
    assert reads[len(first_reads):] == first_reads
    assert first_reads.count(str(adapter)) == 2
    assert [r['mode'] for r in first['operations']] == ['first', 'second']
    assert all(r['entrypoints'] == ['inputs', 'run', 'validate'] for r in first['operations'])
    assert all(r['contract'] == 'Exact public contract.' for r in first['operations'])
    assert first['compute_authorized'] is False and first['physics_validated'] is False
    assert all(r['execution_evidence'] == 'not_inferred_from_source' for r in first['operations'])
    first['operations'][0]['entrypoints'].clear()
    first['source_pins'][0]['sha256'] = 'changed-return-value'
    assert routing.catalogue(tmp_path) == second


def test_same_size_mtime_change_deletion_and_new_functions_are_current(tmp_path):
    adapter, _, _ = _source(tmp_path)
    before = routing.catalogue(tmp_path)
    old = adapter.stat()
    raw = adapter.read_bytes().replace(b'def run()', b'def new()')
    adapter.write_bytes(raw)
    os.utime(adapter, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert adapter.stat().st_size == old.st_size and adapter.stat().st_mtime_ns == old.st_mtime_ns
    changed = routing.catalogue(tmp_path)
    assert changed['operations'][0]['entrypoints'] == ['inputs', 'validate']
    assert changed['operations'][0]['source']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert changed['operations'][0]['source'] != before['operations'][0]['source']
    adapter.unlink()
    assert all(r['status'] == 'source_dispatch_unresolved' for r in routing.catalogue(tmp_path)['operations'])
    adapter.write_bytes(b'def run(): pass\n')
    assert routing.catalogue(tmp_path)['operations'][0]['entrypoints'] == ['run']


def test_equal_content_separate_source_paths_keep_distinct_pins_and_alias_refusal(tmp_path):
    adapter, _, _ = _source(tmp_path)
    science = tmp_path / 'src/ravel/workflow/science.py'
    science.write_bytes(science.read_bytes().replace(b"'second': 'shared'", b"'second': 'copied'"))
    copy = _put(tmp_path, 'physics/copied.py', adapter.read_bytes())
    rows = routing.catalogue(tmp_path)['operations']
    assert rows[0]['source']['sha256'] == rows[1]['source']['sha256']
    assert rows[0]['source']['path'] != rows[1]['source']['path']
    copy.unlink(); copy.symlink_to(adapter)
    with pytest.raises(ValueError, match='without symlinks'):
        routing.catalogue(tmp_path)


def test_coordinator_extensions_host_constants_and_pins_remain_fresh(tmp_path, monkeypatch):
    _, host, extension = _source(tmp_path)
    _coordinator(monkeypatch, tmp_path)
    before = decisions.catalogue(['first'])
    assert before['extensions'][0]['status'] == 'connected_public_source'
    assert before['preparation_tools'][0]['action'] == 'allowed-tool'
    for path, old_text, new_text in ((extension, b'prepare', b'changed'),
                                     (host, b'allowed', b'changed')):
        old = path.stat()
        path.write_bytes(path.read_bytes().replace(old_text, new_text))
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        assert path.stat().st_size == old.st_size
    changed = decisions.catalogue(['first'])
    assert changed['extensions'][0]['status'] == 'source_not_yet_composed'
    assert changed['extensions'][0]['source'] is None
    assert changed['preparation_tools'][0]['action'] == 'changed-tool'
    assert changed['preparation_tools'][0]['source'] != before['preparation_tools'][0]['source']
    extension.write_bytes(b'async def prepare(): pass\n')
    restored = decisions.catalogue(['first'])
    assert restored['extensions'][0]['status'] == 'connected_public_source'
    assert restored['extensions'][0]['source']['sha256'] == hashlib.sha256(extension.read_bytes()).hexdigest()
    restored['extensions'][0]['transport']['arguments'].append('mutated')
    assert decisions.catalogue(['first'])['extensions'][0]['transport']['arguments'] == []
    extension.unlink()
    assert decisions.catalogue(['first'])['extensions'][0]['status'] == 'source_not_yet_composed'
    host.unlink()
    with pytest.raises(ValueError, match='regular file'):
        decisions.catalogue(['first'])


def test_cache_entry_byte_budgets_and_oversized_sources_preserve_semantics(monkeypatch):
    monkeypatch.setattr(syntax, 'CACHE_ENTRIES', 2)
    originals = [b'def one(): pass\n', b'def two(): pass\n', b'def tri(): pass\n']
    for raw in originals:
        syntax.facts(raw)
    assert len(syntax._CACHE) == 2 and originals[0] not in syntax._CACHE
    assert syntax._CACHE_BYTES == sum(charge for _, charge in syntax._CACHE.values())
    assert syntax._CACHE_BYTES <= syntax.MAX_CACHE_BYTES
    syntax._CACHE.clear(); monkeypatch.setattr(syntax, '_CACHE_BYTES', 0)
    monkeypatch.setattr(syntax, 'MAX_CACHE_BYTES', 1)
    assert syntax.facts(originals[0])[1] == ('one',) and not syntax._CACHE
    monkeypatch.setattr(syntax, 'MAX_CACHE_BYTES', 16_777_216)
    monkeypatch.setattr(syntax, 'MAX_CACHED_SOURCE_BYTES', 1)
    assert syntax.facts(originals[1])[1] == ('two',) and not syntax._CACHE
    with pytest.raises(TypeError, match='immutable source bytes'):
        syntax.facts(bytearray(originals[0]))


def test_actual_complete_catalogue_equal_to_uncached_original_ast_projection(monkeypatch):
    # No discovered engine is imported/executed; this is the actual installed
    # source catalogue, compared with the original AST facts before caching.
    def original_facts(raw, *, filename='<unknown>'):
        tree = ast.parse(raw.decode('utf-8'))
        return (ast.get_docstring(tree) or '',
                tuple(sorted(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))),
                tuple(sorted({n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and type(n.value) is str})))
    current = deepcopy(routing.catalogue())
    selected = deepcopy(decisions.catalogue(None))
    monkeypatch.setattr(routing, '_syntax_facts', original_facts)
    monkeypatch.setattr(decisions, '_syntax_facts', original_facts)
    assert routing.catalogue() == current
    assert decisions.catalogue(None) == selected


def test_coordinator_extension_mutation_between_facts_and_custody_refuses(tmp_path, monkeypatch):
    _, _, extension = _source(tmp_path)
    _coordinator(monkeypatch, tmp_path)
    baseline = decisions.catalogue(['first'])
    assert baseline['extensions'][0]['status'] == 'connected_public_source'
    original = decisions._syntax_facts
    captured = []
    def facts_then_mutate(raw, *, filename='<unknown>'):
        value = original(raw, filename=filename)
        if filename == str(extension):
            captured.append(value)
            old = extension.stat()
            extension.write_bytes(raw.replace(b'prepare', b'changed'))
            os.utime(extension, ns=(old.st_atime_ns, old.st_mtime_ns))
            assert extension.stat().st_size == old.st_size
        return value
    monkeypatch.setattr(decisions, '_syntax_facts', facts_then_mutate)
    with pytest.raises(ValueError, match='catalogue source changed after syntax facts'):
        decisions.catalogue(['first'])
    assert len(captured) == 1 and 'prepare' in captured[0][1]
    assert hashlib.sha256(extension.read_bytes()).hexdigest() != baseline['extensions'][0]['source']['sha256']


def test_coordinator_host_mutation_between_facts_and_custody_refuses(tmp_path, monkeypatch):
    _, host, _ = _source(tmp_path)
    _coordinator(monkeypatch, tmp_path)
    baseline = decisions.catalogue(['first'])
    assert baseline['preparation_tools'][0]['action'] == 'allowed-tool'
    original = decisions._syntax_facts
    captured = []
    def facts_then_mutate(raw, *, filename='<unknown>'):
        value = original(raw, filename=filename)
        if filename == str(host):
            captured.append(value)
            old = host.stat()
            host.write_bytes(raw.replace(b'allowed', b'changed'))
            os.utime(host, ns=(old.st_atime_ns, old.st_mtime_ns))
            assert host.stat().st_size == old.st_size
        return value
    monkeypatch.setattr(decisions, '_syntax_facts', facts_then_mutate)
    with pytest.raises(ValueError, match='catalogue source changed after syntax facts'):
        decisions.catalogue(['first'])
    assert len(captured) == 1 and 'allowed-tool' in captured[0][2]
    assert hashlib.sha256(host.read_bytes()).hexdigest() != baseline['preparation_tools'][0]['source']['sha256']
