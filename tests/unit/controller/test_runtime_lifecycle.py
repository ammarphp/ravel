"""Original execution identity and public work-command outcome contracts."""
from copy import deepcopy
import json
import sys

import pytest

from ravel import cli
from ravel.controller import entry, execution_manifest as manifests, outcomes
from ravel.controller.store import RunStore


@pytest.fixture
def store(tmp_path):
    return entry.start(b'Compute a supplied quantity.', channel='terminal', rundir=tmp_path / 'run',
                       root=tmp_path / 'store')


def identity():
    return {'schema_version': 1, 'source': {'digest': 'tree:' + 'a' * 64, 'package_dir': '/opt/runtime'},
            'dependencies': [{'name': 'dependency', 'version': '1'}],
            'python': {'executable': sys.executable}, 'thread_id': 'a' * 64,
            'graph_id': entry.GRAPH_ID, 'closure': [['controller.run', 1]], 'runtime': {'version': '1'}}


@pytest.mark.parametrize('changed', ['source', 'dependencies', 'thread_id', 'runtime', 'closure'])
def test_resume_environment_change_refused_before_admission_or_graph(store, monkeypatch, changed):
    first = identity()
    monkeypatch.setattr(manifests, 'current', lambda *args: deepcopy(first))
    manifests.ensure(store, entry.GRAPH_ID)
    head = store.head()
    changed_identity = deepcopy(first)
    changed_identity[changed] = 'changed'
    monkeypatch.setattr(manifests, 'current', lambda *args: changed_identity)
    calls = []
    monkeypatch.setattr(entry, 'admit', lambda *args: calls.append('admit'))
    monkeypatch.setattr(entry, 'declare_controller', lambda *args: calls.append('declare'))
    with pytest.raises(manifests.ExecutionRefused) as refused:
        entry.drive(store, resume=True)
    assert calls == [] and store.head() == head
    assert manifests.resume_command(store, first) in str(refused.value)
    assert manifests.original(store) == first


def test_original_manifest_and_all_code_epochs_are_retained(store, monkeypatch):
    first = identity()
    monkeypatch.setattr(manifests, 'current', lambda *args: deepcopy(first))
    manifests.ensure(store, entry.GRAPH_ID)
    manifests.ensure(store, entry.GRAPH_ID, resume=True)
    assert store.count(manifests.KIND) == 1
    admitted = dict(first['source'])
    manifests.check_admission(store, admitted)
    store.append('code-identity', admitted)
    store.append('code-identity', admitted)
    with pytest.raises(manifests.ExecutionRefused):
        manifests.check_admission(store, {**admitted, 'digest': 'tree:' + 'b' * 64})
    assert store.count('code-identity') == 2


def test_old_executed_run_cannot_backdate_an_execution_manifest(store, monkeypatch):
    store.append('code-identity', identity()['source'])
    with pytest.raises(manifests.ExecutionRefused, match='no original execution manifest'):
        manifests.ensure(store, entry.GRAPH_ID, resume=True)
    assert store.count(manifests.KIND) == 0


def test_normal_resume_repairs_only_unacknowledged_tail(store):
    before = store.head()
    with (store.root / 'journal.jsonl').open('ab') as stream:
        stream.write(b'{"kind":"interrupted')
    resumed = entry.open_for_resume(store.run_id, root=store.store_root)
    assert resumed.verify() == []
    assert resumed.count('journal-recovery') == 1
    assert resumed.count('request') == 1
    assert resumed.head()['seq'] == before['seq'] + 1
    assert entry.open_for_resume(store.run_id, root=store.store_root).count('journal-recovery') == 1


@pytest.mark.parametrize('delivery,terminal,expected', [
    ({'label': 'accepted', 'accepted': True, 'delivery_dir': 'delivery'}, {}, 'delivered_accepted'),
    ({'qualified': True, 'delivery_dir': 'delivery'}, {}, 'qualified'),
    ({'qualified': True}, {'status': 'qualified'}, 'held'),
    ({}, {'status': 'budget_exhausted'}, 'held'),
    ({}, {'status': 'refused'}, 'refused'),
    ({}, {'status': 'failed'}, 'failed'),
])
def test_outcome_never_promotes_controller_return_to_delivery(delivery, terminal, expected):
    result = outcomes.outcome(delivery=delivery, terminal=terminal, run_id='run-example')
    assert result['status'] == expected
    assert result['require_complete_exit_code'] == outcomes.EXIT_CODES[expected]


@pytest.mark.parametrize('code,status', [(1, 'failed'), (2, 'refused'), (130, 'failed')])
def test_nonzero_command_returns_have_a_typed_process_cause(code, status):
    result = outcomes.outcome(code=code)
    assert result['status'] == status and result['reason_code'] == f'command_exit_{code}'


def test_every_public_dispatch_supports_outcome_file_without_changing_legacy_output(tmp_path, capsys):
    def command(argv):
        assert argv == ['inert-command', 'run']
        print('the work command completed, with no delivery receipt')
        return 0
    path = tmp_path / 'outcome.json'
    assert outcomes.dispatch(['inert-command', 'run', '--outcome-file', str(path)], command) == 0
    assert capsys.readouterr().out == 'the work command completed, with no delivery receipt\n'
    assert json.loads(path.read_text())['status'] == 'held'
    assert outcomes.dispatch(['inert-command', 'run', '--require-complete'], command) == 11


def test_global_contract_is_wired_through_the_public_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, '_dispatch_main', lambda argv: 0)
    path = tmp_path / 'outcome.json'
    assert cli.main(['arbitrary-registered-command', '--require-complete', '--outcome-file', str(path)]) == 11
    assert json.loads(path.read_text())['status'] == 'held'


def test_exceptions_are_machine_readable_and_traceback_is_private(tmp_path, capsys):
    def broken(argv):
        raise RuntimeError('inert command failed')
    path = tmp_path / 'outcome.json'
    assert outcomes.dispatch(['inert-command', '--outcome-file', str(path)], broken) == 1
    result = json.loads(path.read_text())
    from pathlib import Path
    evidence = Path(result['evidence'])
    assert result['status'] == 'failed' and evidence.stat().st_mode & 0o077 == 0
    assert 'Traceback' in evidence.read_text()
    assert 'Traceback' not in capsys.readouterr().out


@pytest.mark.parametrize('status,expected', list(outcomes.EXIT_CODES.items()))
def test_public_completion_exit_codes_are_exact(status, expected, tmp_path):
    def command(argv):
        print(json.dumps({'outcome': {'status': status, 'schema_version': 1}}))
        return 0
    path = tmp_path / 'outcome.json'
    assert outcomes.dispatch(['drive', '--resume', 'run-example', '--require-complete',
                              '--outcome-file', str(path)], command) == expected
    assert json.loads(path.read_text())['status'] == status


def test_noncontroller_output_cannot_claim_accepted_delivery(tmp_path):
    def command(argv):
        print(json.dumps({'outcome': {'status': 'delivered_accepted'}}))
        return 0
    path = tmp_path / 'outcome.json'
    assert outcomes.dispatch(['inert-command', '--require-complete', '--outcome-file', str(path)], command) == 11
    assert json.loads(path.read_text())['status'] == 'held'


def test_changed_detached_delivery_cannot_report_accepted_outcome(store, monkeypatch):
    store.append('receipt', {'accepted': True, 'label': 'accepted', 'receipt_blob': 'blob',
                             'delivery_dir': 'delivery'})
    from importlib import import_module
    deliver = import_module('ravel.controller.sink.deliver')
    monkeypatch.setattr(deliver, 'receipt', lambda *args: {
        'accepted': False, 'qualified': False, 'label': 'accepted', 'delivery': {'directory': 'delivery'},
        'verification': {'delivery_intact': False}})
    assert entry.summary(store, {'terminal': {'status': 'completed'}})['outcome']['status'] == 'held'


def test_graph_completion_with_null_terminal_can_deliver_but_pending_work_cannot(store, monkeypatch):
    from importlib import import_module
    deliver = import_module('ravel.controller.sink.deliver')
    store.append('receipt', {'accepted': True, 'label': 'accepted', 'delivery_dir': 'delivery',
                             'receipt_blob': 'blob'})
    monkeypatch.setattr(deliver, 'receipt', lambda *args: {
        'accepted': True, 'label': 'accepted', 'delivery': {'directory': 'delivery'},
        'verification': {'delivery_intact': True}})
    assert entry.summary(store, {'terminal': None, 'next': [], 'interrupts': []})['outcome']['status'] == 'delivered_accepted'
    assert entry.summary(store, {'terminal': None, 'next': ['approval']})['outcome']['status'] == 'held'


def test_receipt_row_without_an_authenticated_locator_cannot_claim_delivery(store):
    store.append('receipt', {'accepted': True, 'label': 'accepted', 'delivery_dir': 'delivery'})
    assert entry.summary(store, {'terminal': None, 'next': [], 'interrupts': []})['outcome']['status'] == 'held'


def test_later_admission_never_relabels_the_intake_identity(store, monkeypatch):
    from types import SimpleNamespace
    from ravel.controller.sink import common, evidence
    old = {'digest': 'tree:' + 'a' * 64, 'governed': True, 'label': None, 'problems': []}
    store.append('code-identity', old)
    store.append('code-identity', dict(old, digest='tree:' + 'b' * 64))
    monkeypatch.setattr(common, 'module', lambda *args: SimpleNamespace(code_identity=lambda: old))
    assert evidence._identity(store, [])['pinned'] == old


def test_later_governed_admission_cannot_prove_an_ungoverned_intake(store):
    from ravel.controller.confine import ledger_evidence, policy
    from importlib import import_module
    module = import_module('ravel.controller.confine.ledger_evidence')
    row = {'governed': True, 'label': None, 'problems': [], 'kind': 'installed',
           'writable_by_controller_user': False, 'symlinks': [], 'selectors': {}}
    store.append('code-identity', dict(row, governed=False))
    store.append('code-identity', row)
    store.append(policy.SOURCE_KIND, {'path': '/outside/policy', 'sha256': 'a' * 64})
    assert module.ledger_evidence(store) == {}


def test_current_source_instruction_and_directory_surface_is_valid():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    done = subprocess.run([sys.executable, '-m', 'ravel.validation.check_agent_surface'],
                          cwd=root, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
