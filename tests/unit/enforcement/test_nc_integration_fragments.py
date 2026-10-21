"""Execute proposed cross-owner guards with inert peers; never install a product patch."""
import ast
import builtins
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import textwrap
from types import SimpleNamespace

import pytest

import nc_cases
from nc_patch import apply
from test_nc_patch_fragments import _added_function

PATCHES = nc_cases.FIXTURES / 'patches'


def _function(source, name, namespace):
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(functions) == 1
    exec(compile(ast.Module(body=functions, type_ignores=[]), name, 'exec'), namespace)
    return namespace[name]


def _added(name, function, namespace):
    exec(compile(_added_function(name, function), name, 'exec'), namespace)
    return namespace[function]


def _owned_import(owned, *, rows=(), error=None):
    observed = []

    class Store:
        def __init__(self, run_id):
            observed.append(('store', run_id))

        def scan(self, kind):
            observed.append(('scan', kind))
            return deepcopy(rows)

    def importing(name, globals=None, locals=None, fromlist=(), level=0):
        assert name == 'ravel.controller.store' and level == 0, (name, fromlist, level)
        if error:
            raise error
        return SimpleNamespace(RunStore=Store, controller_owned=lambda path: 'run-one' if owned else None)

    return dict(vars(builtins), __import__=importing), observed


@pytest.mark.parametrize('override', ['0', '999999999999', 'invalid', '-2'])
def test_governed_export_ceiling_ignores_environment(monkeypatch, tmp_path, override):
    from ravel.controller import authority
    from ravel.controller.sink import legacy as sink_legacy
    from ravel.workflow import procedure_export
    governed, legacy = tmp_path / 'governed', tmp_path / 'legacy'
    monkeypatch.setattr(sink_legacy, 'owner', lambda path: 'owned-export' if Path(path) == governed else None)
    monkeypatch.setattr(authority, 'operator_config', lambda: {'procedure_byte_ceiling': 2048})
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', override)
    assert procedure_export._byte_ceiling(governed) == 2048
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', '37')
    assert procedure_export._byte_ceiling(legacy) == 37


@pytest.mark.parametrize('rows', [[], [{}, {}], [{}], [{'record': {'kind': 'restricted-sources', 'fingerprints': None,
                                                             'documents': []}}]])
def test_protected_policy_absence_or_ambiguity_refuses(rows):
    imports, observed = _owned_import(True, rows=rows)
    namespace = {'__builtins__': imports, 'Path': Path, 'SHA': re.compile('[0-9a-f]{64}')}
    policy = _added('restricted-policy.patch', '_controller_source_policy', namespace)
    with pytest.raises(ValueError):
        policy()
    assert observed == [('store', 'run-one'), ('scan', 'restricted-source-policy')]


def test_protected_policy_reads_only_store_and_preserves_legacy_absence():
    row = {'kind': 'restricted-sources', 'fingerprints': ['toy-private-token'],
           'documents': [{'sha256': 'a' * 64}]}
    imports, observed = _owned_import(True, rows=[{'record': row}])
    namespace = {'__builtins__': imports, 'Path': Path, 'SHA': re.compile('[0-9a-f]{64}')}
    policy = _added('restricted-policy.patch', '_controller_source_policy', namespace)
    assert policy() == row
    assert observed == [('store', 'run-one'), ('scan', 'restricted-source-policy')]
    legacy_imports, observed = _owned_import(False)
    namespace['__builtins__'].update(legacy_imports)
    assert policy() is None and observed == []


@pytest.mark.parametrize('name,absent', [('ravel.controller', True), ('ravel.controller.store', False),
                                      ('inert_dependency', False)])
def test_policy_import_failure_is_not_confused_with_an_unowned_run(name, absent):
    imports, _ = _owned_import(True, error=ModuleNotFoundError('missing', name=name))
    namespace = {'__builtins__': imports, 'Path': Path, 'SHA': re.compile('[0-9a-f]{64}')}
    policy = _added('restricted-policy.patch', '_controller_source_policy', namespace)
    if absent:
        assert policy() is None
    else:
        with pytest.raises(ModuleNotFoundError):
            policy()


def test_export_ceiling_cannot_use_legacy_environment_after_a_controller_dependency_failure(monkeypatch, tmp_path):
    from ravel.controller.sink import legacy as sink_legacy
    from ravel.workflow import procedure_export

    def broken_owner(path):
        raise ModuleNotFoundError('broken controller', name='ravel.controller.store')

    monkeypatch.setattr(sink_legacy, 'owner', broken_owner)
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', '37')
    with pytest.raises(ModuleNotFoundError) as failure:
        procedure_export._byte_ceiling(tmp_path)
    assert failure.value.name == 'ravel.controller.store'


def test_protected_policy_ignores_every_environment_source_channel(monkeypatch):
    # The installed scanner carries its own pinned-policy binding, so the property is checked on it directly.
    from ravel.controller.confine import policy as confine_policy
    source = (nc_cases.ROOT / 'src/ravel/validation/check_generality.py').read_text()
    monkeypatch.setattr(confine_policy, 'restricted_source_document', lambda scope: {
        'kind': 'restricted-sources', 'fingerprints': ['toy-private-token'], 'documents': [{'sha256': 'A' * 64}]})

    class ForbiddenPath:
        @staticmethod
        def cwd():
            return 'controller-owned-cwd'

        def __init__(self, *args, **kwargs):
            raise AssertionError('governed check opened an environment-controlled file')

    namespace = {'Path': ForbiddenPath, 'json': json,
                 '_compact': lambda term: re.sub('[^a-z0-9]', '', term.lower()),
                 'entry_for': lambda term, category: (term, category), 'SHA': re.compile('[0-9a-f]{64}')}
    external = _function(source, '_external_entries', namespace)
    entries, documents = external({'RAVEL_RESTRICTED_SOURCES': 'untrusted.json',
                                   'RAVEL_EVAL_TERMS_FILE': 'another.txt', 'RAVEL_EVAL_TERMS': 'agent-chosen'})
    assert entries == [('toy-private-token', 'external')]
    assert documents == ['a' * 64]


def test_retained_recipe_requires_current_bytes_before_generation(tmp_path):
    def relative(value):
        path = Path(value)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('ordinary relative path required')
        return path

    check = _added('generation-recipe.patch', 'external_recipe_errors', {'Path': Path, 'relative': relative})
    path = tmp_path / 'recipe.json'; path.write_bytes(b'fictional retained external source\n')
    pin = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    step = {'parameters': {'effects': ['generates_events']}}
    context = {'run_dir': str(tmp_path), 'plan': {'parameters': {'external_recipe': pin}}}
    assert check(step, context) == []
    path.write_bytes(b'changed')
    assert [row['code'] for row in check(step, context)] == ['external_recipe_missing']
    assert check({'parameters': {}}, context) == []


def test_watcher_target_must_be_durable_and_nonlinked(tmp_path):
    check = _added('watcher-durable.patch', 'durable_target_errors', {})
    durable = tmp_path / 'inputs' / 'watch.sh'; durable.parent.mkdir(); durable.write_text('inert\n')
    scratch = tmp_path / 'scratch' / 'watch.sh'; scratch.parent.mkdir(); scratch.write_text('inert\n')
    assert check(tmp_path, durable) == []
    assert check(tmp_path, scratch) == ['watcher_target_not_durable']
    linked = tmp_path / 'alias.sh'; linked.symlink_to(durable)
    assert check(tmp_path, linked) == ['watcher_target_not_durable']


def test_runtime_fragment_preserves_unknown_and_refuses_substitution():
    fragment = (PATCHES / 'sink-runtime.patch').read_text().splitlines()
    start = next(i for i, line in enumerate(fragment) if line.startswith('+            historical ='))
    body = []
    for line in fragment[start:]:
        if not line.startswith('+'):
            break
        body.append(line[1:])
    source = 'def runtime_check(findings, item):\n' + textwrap.indent(textwrap.dedent('\n'.join(body)), '    ') + '\n'
    record = []
    findings = SimpleNamespace(violated=lambda *args, **kwargs: record.append((args, kwargs)))
    check = _function(source, 'runtime_check', {})
    check(findings, {'runtime': {'toy_runtime': None}, 'exported_runtime': {'toy_runtime': None}})
    assert record == []
    check(findings, {'runtime': {'toy_runtime': None}, 'exported_runtime': {'toy_runtime': 'exporter-version'}})
    assert record[0][0][0] == 'E27' and record[0][1]['refuse'] == 'diagnostic'
    assert 'toy_runtime' in record[0][0][2]


def test_instruction_selector_fragment_changes_only_the_retired_anchor():
    patch = (PATCHES / 'instruction-selector.patch').read_text().splitlines()
    removed = [line[1:] for line in patch if line.startswith('-') and not line.startswith('---')]
    added = [line[1:] for line in patch if line.startswith('+') and not line.startswith('+++')]
    assert len(removed) == len(added) == 1
    assert '#using-these-under-the-model-tier-policy' in removed[0]
    assert added[0] == removed[0].replace('#using-these-under-the-model-tier-policy', '#judgment-sites-under-the-controller')


def test_route_pin_fragment_matches_installed_guard_and_controls():
    document = json.loads((PATCHES / 'manifest.json').read_text())
    row = next(row for row in document['patches'] if row['patch'] == 'route-pin.patch')
    installed = (nc_cases.ROOT / row['target']).read_text()
    assert hashlib.sha256(installed.encode()).hexdigest() == row['result_sha256'], (
        'route fragment must describe the installed source, including its current guard')
    fragment = (PATCHES / row['patch']).read_text()
    reverse = []
    for line in fragment.splitlines(keepends=True):
        if line.startswith('--- a/') or line.startswith('+++ b/'):
            reverse.append(line)
        elif line.startswith('@@ '):
            match = re.match(r'@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@(.*)', line)
            assert match, line
            reverse.append(f'@@ -{match[3]}{match[4] or ""} +{match[1]}{match[2] or ""} @@{match[5]}\n')
        elif line.startswith('+'):
            reverse.append('-' + line[1:])
        elif line.startswith('-'):
            reverse.append('+' + line[1:])
        else:
            reverse.append(line)
    preimage = apply(installed, ''.join(reverse))
    assert hashlib.sha256(preimage.encode()).hexdigest() == row['source_sha256']
    assert apply(preimage, fragment) == installed

    class Store:
        def __init__(self):
            self.rows = []

        def read(self, kind, record_id):
            if record_id != 'retained-route':
                raise KeyError(record_id)
            return {'record': {'route': 'calculation'}}

        def append(self, kind, body):
            self.rows.append((kind, body))

    def admitted(source, route):
        store = Store()
        guard = _function(source, '_admitted', {'adapter': lambda *args: None})
        result = guard({'route': route}, store, {'steps': [{'id': 'effect'}]}, ['effect'], {})
        return result, store.rows

    # The exact removed guard must expose the bypass, with the same inert adapter.
    assert admitted(preimage, {})[0] == (['effect'], {}, {})
    for route in ({}, {'id': 'calculation', 'record_id': 'absent'},
                  {'id': 'another-route', 'record_id': 'retained-route'}):
        (ready, held, holds), records = admitted(installed, route)
        assert ready == [] and held['effect']['status'] == 'held'
        assert holds['effect']['reason'] == 'route_not_pinned'
        assert records[-1][1]['code'] == 'route_not_pinned'
    assert admitted(installed, {'id': 'calculation', 'record_id': 'retained-route'})[0] == (['effect'], {}, {})


def test_fragment_manifest_hashes_and_proving_tests_are_complete():
    document = json.loads((PATCHES / 'manifest.json').read_text())
    assert document['applied_to_product'] is False
    assert {row['patch'] for row in document['patches']} == {path.name for path in PATCHES.glob('*.patch')}
    for row in document['patches']:
        raw = (PATCHES / row['patch']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['patch_sha256']
        assert re.fullmatch('[0-9a-f]{64}', row['source_sha256'])
        assert re.fullmatch('[0-9a-f]{64}', row['result_sha256'])
        for target in row['proving_tests']:
            path, name = target.split('::')
            assert (nc_cases.ROOT / path).is_file(), target
            names = {node.name for node in ast.parse((nc_cases.ROOT / path).read_text()).body
                     if isinstance(node, ast.FunctionDef)}
            assert name in names, target
