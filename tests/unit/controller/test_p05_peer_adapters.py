"""Execute exact peer patch fragments in memory, or the peers' applied code once they integrated them.

No peer source edits or provider invocations.
"""
import ast
import hashlib
import inspect
import os
import importlib
import json
from pathlib import Path
import re
import sys
import types
from types import SimpleNamespace

import pytest

from test_p05_custody_hooks import _apply_execution_fragment
from test_p05_policy import MemoryStore

REPOSITORY = Path(__file__).resolve().parents[3]
PEERS = {
    'ravel.workflow.transports.cli_worker': 'src/ravel/workflow/transports/cli_worker.py',
    'ravel.workflow.procedure_export': 'src/ravel/workflow/procedure_export.py',
    'ravel.validation.check_generality': 'src/ravel/validation/check_generality.py',
    'ravel.workflow.submission_export': 'src/ravel/workflow/submission_export.py',
    'ravel.workflow.wms_launch': 'src/ravel/workflow/wms_launch.py',
}
# Peers whose owners applied the change in their own code (with their own seams): the worker's private
# configuration home, and the sink's operator export ceiling and pinned vendored-source scan. Their tests below run that code;
# the remaining fragments still apply in memory, exactly.
INTEGRATED = ('ravel.workflow.transports.cli_worker', 'ravel.workflow.procedure_export',
              'ravel.workflow.submission_export', 'ravel.validation.check_generality')


def _apply_peer(source, patch, path):
    """Reuse the custody test's strict hunk parser, adapting only the three file headers."""
    sections = re.split(r'(?=^diff --git )', patch, flags=re.MULTILINE)
    prefix = f'diff --git a/{path} b/{path}\n'
    selected = [section for section in sections if section.startswith(prefix)]
    if len(selected) != 1:
        raise ValueError(f'exactly one peer diff required: {path}')
    lines = selected[0].splitlines(keepends=True)
    if lines[:3] != [prefix, f'--- a/{path}\n', f'+++ b/{path}\n']:
        raise ValueError('unexpected peer file headers')
    execution_path = 'src/ravel/workflow/execution.py'
    lines[:3] = [f'diff --git a/{execution_path} b/{execution_path}\n',
                 f'--- a/{execution_path}\n', f'+++ b/{execution_path}\n']
    return _apply_execution_fragment(source, ''.join(lines))


@pytest.fixture
def peers(monkeypatch):
    patch = (REPOSITORY / 'tests/fixtures/peer_contracts/adapter-custody.patch').read_text()
    result = {}
    before = {}
    for name, path in PEERS.items():
        original = importlib.import_module(name)
        source = Path(original.__file__).read_text()
        before[path] = hashlib.sha256(source.encode()).hexdigest()
        if name in INTEGRATED:
            result[name] = original
            continue
        modified, count = _apply_peer(source, patch, path)
        assert count > 0
        module = types.ModuleType(name)
        module.__file__, module.__package__ = original.__file__, original.__package__
        parent = importlib.import_module(original.__package__)
        monkeypatch.setitem(sys.modules, name, module)
        monkeypatch.setattr(parent, name.rsplit('.', 1)[1], module)
        exec(compile(modified, original.__file__, 'exec'), module.__dict__)
        result[name] = module
    yield result
    for path, digest in before.items():
        assert hashlib.sha256((REPOSITORY / path).read_bytes()).hexdigest() == digest


@pytest.fixture
def owned_policy(tmp_path, monkeypatch):
    from ravel.controller.confine import policy
    store = MemoryStore(tmp_path / 'store')
    run = tmp_path / 'run'
    run.mkdir()
    source = tmp_path / 'restricted-sources.json'
    source.write_text(json.dumps({'schema_version': 1, 'kind': 'restricted-sources',
                                  'fingerprints': ['Velvet Otter'], 'documents': []}))

    def owner(path):
        return ('owned', run) if Path(path).absolute().is_relative_to(run) else None

    monkeypatch.setattr(policy.runs, 'owner_of', owner)
    monkeypatch.setattr(policy.runs, 'store', lambda run_id: store)
    return SimpleNamespace(store=store, run=run, source=source, policy=policy)


def test_exact_peer_diffs_are_applied_without_editing_peers(peers):
    assert set(peers) == set(PEERS)
    assert peers['ravel.workflow.procedure_export']._byte_ceiling.__defaults__ == (None,)
    assert 'target' in peers['ravel.validation.check_generality']._external_entries.__code__.co_varnames


def test_P04_private_home_preserves_owner_file_lifecycle(peers, tmp_path, monkeypatch):
    module = peers['ravel.workflow.transports.cli_worker']
    login = tmp_path / 'real-login'
    login.mkdir(mode=0o700)
    source = login / '.credentials.json'
    source.write_text('opaque-owner-source')
    source.chmod(0o600)
    ws = tmp_path / 'worker'
    ws.mkdir()
    monkeypatch.setattr(module, '_login_config_dir', lambda: login)
    document = {'auth': {'kind': 'login'}}
    home, owned, env, verified, mcp = module._cli_home('claude', document, ws)
    private = Path(env['CLAUDE_CONFIG_DIR'])
    assert owned is False and private.is_relative_to(home) and not private.is_relative_to(login)
    assert verified == ['CLAUDE_CONFIG_DIR'] and mcp == ws / 'inputs' / 'mcp'
    assert home.stat().st_mode & 0o777 == 0o700 and private.stat().st_mode & 0o777 == 0o700
    assert list(private.iterdir()) == []
    owner_file = private / '.credentials.json'
    owner_file.write_text('opaque-owner-worker')
    owner_file.chmod(0o600)
    module._cli_home('claude', document, ws)
    module.remove_home(ws, {'transport': {'cli_home': str(home), 'cli_home_owned': owned}})
    assert source.read_text() == 'opaque-owner-source'
    assert owner_file.read_text() == 'opaque-owner-worker'


def test_P07_controller_ceiling_ignores_environment_and_preserves_legacy(peers, owned_policy, monkeypatch, tmp_path):
    # The sink's own ceiling: the operator's configuration for a controller-owned run, the environment otherwise.
    from ravel.controller import authority
    from ravel.controller.sink import legacy as sink_legacy
    module = peers['ravel.workflow.procedure_export']
    run = owned_policy.run
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', '9000000')
    monkeypatch.setattr(sink_legacy, 'owner', lambda path: 'owned' if Path(path).absolute().is_relative_to(run) else None)
    monkeypatch.setattr(authority, 'operator_config', lambda: {'procedure_byte_ceiling': 7})
    assert module._byte_ceiling(run) == 7
    assert module._byte_ceiling(tmp_path / 'legacy') == 9000000
    monkeypatch.setattr(authority, 'operator_config', lambda: {})
    assert module._byte_ceiling(run) == module.DEFAULT_BYTE_CEILING


def test_generality_actual_tree_and_paths_use_pin_and_ignore_environment(peers, owned_policy, tmp_path, monkeypatch):
    module = peers['ravel.validation.check_generality']
    fixture = owned_policy
    fixture.policy.freeze_sources(fixture.store, fixture.source, run_dir=fixture.run)
    target = fixture.run / 'note.md'
    target.write_text('Velvet Otter\nAmbient Zebra\n')
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(tmp_path / 'missing-environment-file.json'))
    monkeypatch.setenv('RAVEL_EVAL_TERMS', 'Ambient Zebra')
    empty = tmp_path / 'maintained.json'
    empty.write_text(json.dumps(module.denylist_document([])))
    deny = module.load_denylist(empty, target=target)
    assert deny.match('Velvet Otter') == 'external'
    assert deny.match('Ambient Zebra') is None
    hits = module.scan_tree(fixture.run, module.Denylist([]))
    assert any(hit.rule == 'denylist:external' for hit in hits)
    hits, scanned = module.scan_paths([target], module.Denylist([]), root=fixture.run)
    assert 'note.md' in scanned and any(hit.rule == 'denylist:external' for hit in hits)


@pytest.mark.parametrize('state', ['absent', 'changed', 'unreadable'])
def test_generality_missing_or_changed_pin_refuses_api_and_returns_validation_failure(
        peers, owned_policy, tmp_path, monkeypatch, state):
    module = peers['ravel.validation.check_generality']
    fixture = owned_policy
    if state in ('changed', 'unreadable'):
        fixture.policy.freeze_sources(fixture.store, fixture.source, run_dir=fixture.run)
    if state == 'changed':
        fixture.source.write_text(json.dumps({'kind': 'restricted-sources', 'fingerprints': ['Changed Restriction']}))
    elif state == 'unreadable':
        fixture.source.unlink()
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(fixture.source))
    (fixture.run / 'note.md').write_text('ordinary inert text')
    with pytest.raises(fixture.policy.SourcePolicyRefused):
        module.scan_tree(fixture.run, module.Denylist([]))
    with pytest.raises(fixture.policy.SourcePolicyRefused):
        module.scan_paths([fixture.run / 'note.md'], module.Denylist([]), root=fixture.run)
    monkeypatch.setattr(module, '_git', lambda *args: pytest.fail('policy refusal must precede git scanning'))
    with pytest.raises(fixture.policy.SourcePolicyRefused):
        module.scan_repository(fixture.run, module.Denylist([]))
    assert module.main(['--tree', str(fixture.run), '--root', str(fixture.run)]) == 2


def test_generality_owned_caller_binds_external_tree_and_paths(peers, owned_policy, tmp_path, monkeypatch, capsys):
    module = peers['ravel.validation.check_generality']
    fixture = owned_policy
    target = tmp_path / 'delivery' / 'note.md'
    target.parent.mkdir()
    target.write_text('Velvet Otter\n')
    monkeypatch.chdir(fixture.run)
    monkeypatch.delenv('RAVEL_RESTRICTED_SOURCES', raising=False)
    assert module.main(['--tree', str(target.parent)]) == 2
    assert 'SourcePolicyRefused' in capsys.readouterr().err
    fixture.policy.freeze_sources(fixture.store, fixture.source, run_dir=fixture.run)
    assert module.main(['--tree', str(target.parent)]) == 1
    assert module.main([str(target)]) == 1
    target.write_text('ordinary public text\n')
    assert module.main(['--tree', str(target.parent)]) == 0


def test_generality_consumes_authenticated_policy_bytes_without_reopening(peers, owned_policy, monkeypatch):
    module = peers['ravel.validation.check_generality']
    fixture = owned_policy
    fixture.policy.freeze_sources(fixture.store, fixture.source, run_dir=fixture.run)
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        assert path != fixture.source, 'the policy must be consumed from its authenticated byte read'
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', read_text)
    entries, _ = module._external_entries({}, target=fixture.run)
    assert module.Denylist(entries).match('Velvet Otter') == 'external'


def test_generality_rebind_removes_ambient_entries_loaded_before_owned_target(
        peers, owned_policy, tmp_path, monkeypatch):
    module = peers['ravel.validation.check_generality']
    fixture = owned_policy
    fixture.policy.freeze_sources(fixture.store, fixture.source, run_dir=fixture.run)
    monkeypatch.delenv('RAVEL_RESTRICTED_SOURCES', raising=False)
    empty = tmp_path / 'maintained.json'
    empty.write_text(json.dumps(module.denylist_document([])))
    deny = module.load_denylist(empty, env={'RAVEL_EVAL_TERMS': 'Ambient Zebra'})
    (fixture.run / 'note.md').write_text('Ambient Zebra')
    assert module.scan_tree(fixture.run, deny) == []


def test_submission_missing_policy_refuses_before_scanner_subprocess(peers, owned_policy, tmp_path, monkeypatch):
    module = peers['ravel.workflow.submission_export']
    fixture = owned_policy
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(fixture.source))
    monkeypatch.setattr(module, '_pinned_deny_list', lambda controller_run: None)   # the run pinned no policy
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs:
                        pytest.fail('missing policy reached scanner subprocess'))
    monkeypatch.setattr(module, '_git', lambda *args, **kwargs:
                        pytest.fail('missing policy reached scanner subprocess'))
    monkeypatch.setattr(module, 'run_path', lambda *args, **kwargs:
                        pytest.fail('missing policy reached scanner loading'))
    with pytest.raises(ValueError, match='no pinned restricted-source policy'):
        module._restricted_source_scan(tmp_path, 'inert-tag', tmp_path / 'vendor', controller_run='owned')


def test_submission_scan_uses_pinned_source_then_refuses_changed_bytes(peers, owned_policy, tmp_path, monkeypatch):
    module = peers['ravel.workflow.submission_export']
    fixture = owned_policy
    pinned = {'path': str(fixture.source), 'sha256': module.file_sha256(fixture.source)}
    monkeypatch.setattr(module, '_pinned_deny_list', lambda controller_run: pinned)   # frozen at intake
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(tmp_path / 'ambient-not-used'))
    calls = []
    monkeypatch.setattr(module, '_git', lambda *args, **kwargs:
                        calls.append(args) or SimpleNamespace(returncode=0, stdout=b'# inert scanner'))

    pinned_bytes = fixture.source.read_bytes()

    def load(path):
        # The scanner loads exactly the bytes validated against the intake pin (a private copy of them).
        assert Path(path).read_bytes() == pinned_bytes
        assert module.file_sha256(Path(path)) == pinned['sha256']
        return {'pinned': True}

    scanner = {'ENV': 'RAVEL_RESTRICTED_SOURCES', 'load_deny_list': load,
               'scan': lambda paths, deny, **kwargs: [] if deny == {'pinned': True} else pytest.fail('wrong deny list')}
    monkeypatch.setattr(module, 'run_path', lambda path: scanner)
    assert module._restricted_source_scan(tmp_path, 'inert-tag', tmp_path / 'vendor', controller_run='owned') == {
        'deny_list': 'pinned', 'findings': 0}
    count = len(calls)
    fixture.source.write_text(json.dumps({'kind': 'restricted-sources', 'fingerprints': ['Changed Restriction']}))
    with pytest.raises(ValueError, match='changed after intake'):
        module._restricted_source_scan(tmp_path, 'inert-tag', tmp_path / 'vendor', controller_run='owned')
    assert len(calls) == count


def test_P10_wms_launch_optional_scope_is_forwarded_by_exact_patch(peers):
    module = peers['ravel.workflow.wms_launch']
    parameter = inspect.signature(module.launch).parameters['capability_scope']
    assert parameter.kind == inspect.Parameter.KEYWORD_ONLY and parameter.default is None
    path = PEERS[module.__name__]
    source, _ = _apply_peer((REPOSITORY / path).read_text(),
                            (REPOSITORY / 'tests/fixtures/peer_contracts/adapter-custody.patch').read_text(), path)
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'launch')
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == 'launch_authorization'
             and isinstance(node.func.value, ast.Name) and node.func.value.id == 'wms_policy']
    assert len(calls) == 1
    forwarded = [item.value for item in calls[0].keywords if item.arg == 'capability_scope']
    assert len(forwarded) == 1 and isinstance(forwarded[0], ast.Name)
    assert forwarded[0].id == 'capability_scope'


def test_P10_actual_scope_helper_mints_and_revokes_without_executor(owned_policy, monkeypatch):
    from ravel.workflow import wms_policy
    from ravel.controller.confine import capability
    fixture = owned_policy
    fixture.store.run_id = 'owned'
    workflow = fixture.run / 'workflow'
    workflow.mkdir()
    monkeypatch.delenv(wms_policy.CAPABILITY_ENV, raising=False)
    scope = {'max_jobs': 2, 'resource_maxima': {'threads': 1}}
    with wms_policy.launch_authorization(workflow, 'alpha', 1, {'alpha': 'a' * 64},
                                         capability_scope=scope) as live:
        token = os.environ[wms_policy.CAPABILITY_ENV]
        assert token.startswith('rwc1.owned.wms-alpha-000001.')
        minted = fixture.store.scan(capability.KIND)[0]['record']
        assert minted['scope']['max_jobs'] == 2
        assert minted['scope']['resource_maxima'] == {'threads': 1}
        assert minted['scope']['workflow_dir'] == str(workflow)
        assert minted['scope']['tasks'] == ['alpha']
        assert fixture.store.scan(capability.REVOKED) == []
        assert Path(live).is_file()
    assert wms_policy.CAPABILITY_ENV not in os.environ
    assert not Path(live).exists()
    assert fixture.store.scan(capability.REVOKED)[0]['record']['launch_id'] == 'wms-alpha-000001'


def _assert_dispatch_inventory(monkeypatch):
    from ravel.controller.step import graph
    from copy import deepcopy
    approved = {'tools': ['ws_read'], 'writable': ['/synthetic/outputs'],
                'env_names': ['PATH'], 'network': 'none'}
    state = {'context': {'run_id': 'synthetic-run', 'admitted_inventory': approved},
             'acting': {'id': 'produce'},
             'packet': {'schema': {}, 'schema_sha256': 'a' * 64, 'file_sha256': 'b' * 64,
                        'manifest': {'sha256': 'c' * 64}},
             'preflight': {'selection': {'transport_id': 'restricted-worker'},
                           'toolbelt': {'tools': ['ws_read']}}}
    monkeypatch.setattr(graph.nodes, 'agent', lambda name, **options: options)
    callback = graph._dispatch_node()['controller']
    expected = deepcopy(approved)
    facts = callback(state)
    assert facts['run_id'] == 'synthetic-run'
    assert facts['admitted_inventory'] == expected
    approved['tools'].append('changed-after-dispatch')
    assert facts['admitted_inventory'] == expected


def test_controller_worker_dispatch_forwards_the_complete_approved_inventory(monkeypatch):
    _assert_dispatch_inventory(monkeypatch)


@pytest.mark.parametrize('field', ['run_id', 'admitted_inventory'])
def test_controller_inventory_forwarding_mutants_are_detected(monkeypatch, field):
    from ravel.controller.step import graph
    tree = ast.parse(inspect.getsource(graph._controller_facts))
    result = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Return))
    index = next(i for i, key in enumerate(result.keys) if isinstance(key, ast.Constant) and key.value == field)
    result.keys.pop(index)
    result.values.pop(index)
    scope = dict(graph.__dict__)
    exec(compile(ast.fix_missing_locations(tree), '<inventory-forwarding-mutant>', 'exec'), scope)
    monkeypatch.setattr(graph, '_controller_facts', scope['_controller_facts'])
    with pytest.raises((AssertionError, KeyError)):
        _assert_dispatch_inventory(monkeypatch)
