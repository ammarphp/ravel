"""Verified exact-locator backup recovery and read-only evidence sharing."""
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from test_p06_support import operator_home  # noqa: F401
from ravel.controller import entry, run_bundle
from ravel.controller.authority import issuer, operator, common, stop
from ravel.controller.store import RunStore


@pytest.fixture
def saved(operator_home, tmp_path):
    operator.init(mode='physicist-in-the-loop')
    store = entry.start(b'Compute the supplied quantity.', channel='terminal', rundir=tmp_path / 'run')
    (store.run_dir / 'result.txt').write_text('retained evidence')
    database = store.graph_scope() / 'framework' / 'graphs.sqlite'
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute('create table checkpoint (id text primary key, data text)')
        connection.execute("insert into checkpoint values ('thread', 'checkpoint data')")
    bundle = tmp_path / 'backup'
    run_bundle.export_run(store, bundle)
    return store, bundle


def test_export_verifies_full_state_and_restores_successor_binding(saved):
    store, bundle = saved
    original = store.scan('run')[0]
    before = run_bundle.verify_bundle(bundle)
    assert before['head'] == store.head()
    assert run_bundle.verify_bundle(bundle) == before  # verification does not mutate the bundle
    store.close()
    shutil.rmtree(store.run_dir)
    shutil.rmtree(store.root)
    restored = run_bundle.restore_run(bundle)
    resumed = entry.open_for_resume(store.run_id)
    assert resumed.check_binding() == [] and resumed.verify() == []
    assert resumed.scan('run')[0] == original
    assert resumed.latest('run-restoration')['record']['predecessor_head'] == before['head']
    assert (resumed.run_dir / 'result.txt').read_text() == 'retained evidence'
    with sqlite3.connect(resumed.root / 'graph/framework/graphs.sqlite') as connection:
        assert connection.execute('select * from checkpoint').fetchall() == [('thread', 'checkpoint data')]
    assert stop.stop_state(resumed) != 'running'
    assert not (resumed.root / 'RESTORE-PENDING').exists()
    assert 'operator resume' in restored['next_action']


@pytest.mark.parametrize('member', ['run/result.txt', 'store/journal.jsonl', 'store/graph/framework/graphs.sqlite'])
def test_changed_exported_bytes_are_refused_before_restore(saved, member):
    store, bundle = saved
    with (bundle / member).open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(run_bundle.BundleRefused, match='digest mismatch'):
        run_bundle.restore_run(bundle)
    assert store.verify() == []


def test_unlisted_bundle_member_is_refused(saved):
    _, bundle = saved
    (bundle / 'extra').write_text('extra')
    with pytest.raises(run_bundle.BundleRefused, match='membership'):
        run_bundle.verify_bundle(bundle)


def test_export_refuses_symlink_ancestor_before_copying_into_protected_state(saved, tmp_path):
    store, _ = saved
    alias = tmp_path / 'store-alias'
    alias.symlink_to(store.root, target_is_directory=True)
    with pytest.raises(run_bundle.BundleRefused, match='destination traverses a symbolic link') as refusal:
        run_bundle.export_run(store, alias / 'backup')
    assert 'real path outside the run, store and issuer' in refusal.value.remedy
    assert not (store.root / 'backup').exists()
    assert store.verify() == []


def test_export_normalizes_parent_components_before_overlap_check(saved):
    store, _ = saved
    intermediate = store.root.parent / 'intermediate'
    intermediate.mkdir()
    destination = intermediate / '..' / store.root.name / 'backup'
    with pytest.raises(run_bundle.BundleRefused, match='overlaps protected input state'):
        run_bundle.export_run(store, destination)
    assert not (store.root / 'backup').exists()
    assert store.verify() == []


def test_export_claims_its_destination_exclusively(saved, tmp_path, monkeypatch):
    store, _ = saved
    destination = tmp_path / 'competing-backup'
    original = run_bundle.os.mkdir

    def mkdir(path, *args, **kwargs):
        if Path(path) == destination:
            original(path, 0o700)
            (destination / 'keep.txt').write_text('another creator owns this directory')
            raise FileExistsError(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(run_bundle.os, 'mkdir', mkdir)
    with pytest.raises(run_bundle.BundleRefused, match='destination exists'):
        run_bundle.export_run(store, destination)
    assert (destination / 'keep.txt').read_text() == 'another creator owns this directory'
    assert not (destination / 'BUNDLE.json').exists()


def test_copied_tree_syncs_directory_entries_before_publication(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    (source / 'nested').mkdir(parents=True)
    (source / 'nested' / 'evidence.txt').write_text('retained evidence')
    synced = []
    monkeypatch.setattr(run_bundle, '_fsync_directory', lambda path: synced.append(path))
    run_bundle._copy_tree(source, target)
    assert (target / 'nested' / 'evidence.txt').read_text() == 'retained evidence'
    assert {target / 'nested', target, target.parent} <= set(synced)


@pytest.mark.parametrize('member', ['run/result.txt', 'store/journal.jsonl'])
def test_copy_time_bundle_change_is_refused_before_successor_binding(saved, monkeypatch, member):
    store, bundle = saved
    run_dir = store.run_dir
    store.close()
    shutil.rmtree(run_dir)
    shutil.rmtree(store.root)
    original = run_bundle._copy_tree

    def copy(source, target, **kwargs):
        if source == bundle / member.split('/')[0]:
            with (bundle / member).open('ab') as stream:
                stream.write(b'changed after bundle verification')
        original(source, target, **kwargs)

    monkeypatch.setattr(run_bundle, '_copy_tree', copy)
    with pytest.raises(run_bundle.BundleRefused, match='restored member differs from the signed inventory'):
        run_bundle.restore_run(bundle)
    assert (store.root / 'RESTORE-FAILED').is_file()
    assert 'restoration_identity' not in json.loads((run_dir / 'controller-run.json').read_bytes())
    assert b'run-restoration' not in (store.root / 'journal.jsonl').read_bytes()
    with pytest.raises(entry.EntryError, match='cannot be resumed'):
        entry.open_for_resume(store.run_id)


def test_share_is_read_only_and_cannot_restore(saved, tmp_path):
    store, _ = saved
    head = store.head()
    bundle = tmp_path / 'share'
    run_bundle.export_run(store, bundle, share_only=True)
    assert store.head() == head
    with pytest.raises(run_bundle.BundleRefused, match='read-only share'):
        run_bundle.restore_run(bundle)


def test_hard_stop_after_rebinding_cannot_resume_before_fencing(saved, monkeypatch):
    import multiprocessing
    import os
    from ravel.workflow import effect_ledger
    store, bundle = saved
    run_dir = store.run_dir
    store.close()
    shutil.rmtree(run_dir)
    shutil.rmtree(store.root)

    def interrupted_restore():
        monkeypatch.setattr(effect_ledger, 'bump_epoch', lambda *args: os._exit(42))
        run_bundle.restore_run(bundle)

    process = multiprocessing.get_context('fork').Process(target=interrupted_restore)
    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail('restore did not reach the bounded interruption point')
    assert process.exitcode == 42
    assert json.loads((run_dir / 'controller-run.json').read_bytes())['restoration_identity']
    assert (store.root / 'RESTORE-PENDING').is_file()
    assert not (store.root / 'RESTORE-FAILED').exists()  # os._exit bypassed exception cleanup
    with pytest.raises(entry.EntryError, match='restoration is incomplete'):
        entry.open_for_resume(store.run_id)


def test_export_and_restore_refuse_agent_sessions(saved, monkeypatch, tmp_path):
    store, bundle = saved
    monkeypatch.setenv('CLAUDECODE', '1')
    with pytest.raises(common.AuthorityRefused, match='operator action'):
        run_bundle.export_run(store, tmp_path / 'denied')
    with pytest.raises(common.AuthorityRefused, match='operator action'):
        run_bundle.restore_run(bundle)
    assert not (tmp_path / 'denied').exists()


def test_conflicting_external_history_refuses_stale_restore(saved):
    store, bundle = saved
    stop.record_control(store, 'resume', label=common.OPERATOR_COMMAND, source='operator_cli',
                        evidence={'command': 'resume'}, reason='continue')
    store.close()
    shutil.rmtree(store.run_dir)
    shutil.rmtree(store.root)
    with pytest.raises(run_bundle.BundleRefused, match='conflicting external authority'):
        run_bundle.restore_run(bundle)
    assert not store.root.exists()


def test_ordinary_copy_still_cannot_resume(saved, tmp_path):
    store, _ = saved
    copy = tmp_path / 'copy'
    shutil.copytree(store.run_dir, copy)
    assert store.check_binding(copy)
    with pytest.raises(entry.EntryError, match='cannot be resumed'):
        entry.open_for_resume(store.run_id, rundir=copy)


def test_stale_worker_login_state_cannot_enter_a_share(saved, tmp_path):
    store, _ = saved
    login = store.graph_scope() / 'attempt.cli-home'
    login.mkdir()
    (login / 'auth.json').write_text('private fixture state')
    destination = tmp_path / 'share'
    with pytest.raises(run_bundle.BundleRefused, match='supervised cleanup'):
        run_bundle.export_run(store, destination, share_only=True)
    assert not destination.exists()


def test_public_operator_export_and_restore_commands_are_registered(saved, tmp_path, capsys):
    from ravel import cli
    import shlex
    store, _ = saved
    bundle = tmp_path / 'backup with spaces'
    assert cli.main(['operator', 'export-run', '--run', store.run_id, '--out', str(bundle)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert shlex.split(result['next_action']) == ['ravel', 'operator', 'restore-run', '--bundle', str(bundle)]
    store.close()
    shutil.rmtree(store.run_dir)
    shutil.rmtree(store.root)
    assert cli.main(['operator', 'restore-run', '--bundle', str(bundle)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['run_id'] == store.run_id
    assert entry.open_for_resume(store.run_id).check_binding() == []


def test_restore_revokes_old_live_capabilities_and_process_handles(operator_home, tmp_path):
    from ravel.controller.confine import capability
    operator.init(mode='physicist-in-the-loop')
    store = entry.start(b'Compute a quantity.', channel='terminal', rundir=tmp_path / 'run')
    workflow = store.run_dir / 'workflow'
    workflow.mkdir()
    script = workflow / 'job.sh'
    script.write_text('# properties = {"rule":"task_step"}\nexit 0\n')
    token = capability.mint_capability(store, 'launch-original', {'workflow_dir': str(workflow)})
    registry = store.graph_scope() / 'agent-work/processes.json'
    registry.parent.mkdir(parents=True)
    registry.write_text('{"processes": []}')
    bundle = tmp_path / 'backup'
    run_bundle.export_run(store, bundle)
    store.close()
    shutil.rmtree(store.run_dir)
    shutil.rmtree(store.root)
    run_bundle.restore_run(bundle)
    resumed = entry.open_for_resume(store.run_id)
    with pytest.raises(capability.CapabilityRefused, match='revoked'):
        capability.verify_capability(token, script, store=resumed)
    assert not (resumed.root / 'graph/agent-work/processes.json').exists()
    assert (resumed.root / 'graph/agent-work/processes.json.restored-evidence').exists()


def test_real_checkpoint_thread_continues_without_repeating_a_completed_step(operator_home, tmp_path, monkeypatch):
    import time
    import fakes
    from ravel.controller import graph
    from ravel.workflow import agent_tripwire
    from test_p01_entry import _paused_run
    fakes.isolate(tmp_path, monkeypatch)
    from ravel.controller import store as store_module
    monkeypatch.setattr(store_module, '_operator_config', lambda: {})
    monkeypatch.setattr(agent_tripwire, '_DECLARED', [])
    monkeypatch.setattr(graph, 'review_delivery_assumptions', lambda *args: {})
    fakes.no_checkpoint_seat(monkeypatch)
    issuer.initialize()

    class SignedFixtureAuthority(fakes.FakeAuthority):
        def _append(self, store, body):
            body = {'schema': common.SCHEMA, 'uid': f'authority-{next(self._uids):06d}',
                    'run_id': store.run_id, 'time_ns': time.time_ns(), 'review_credit': False,
                    'human_identity_authenticated': False, **body}
            signed = common.append(store, 'authority', body)
            return {**signed, 'id': body['uid'], 'store_id': signed['id']}

    authority = SignedFixtureAuthority({'go': ['pending', 'go']})
    with fakes.stand_in_graphs(), fakes.installed(authority=authority):
        store = _paused_run(tmp_path)
        state = fakes.final_state(store)
        thread = store.latest('execution-manifest')['record']['thread_id']
        assert state['steps']['w']['attempts'] == 1
        bundle = tmp_path / 'backup'
        run_bundle.export_run(store, bundle)
        store.close()
        shutil.rmtree(store.run_dir)
        shutil.rmtree(store.root)
        run_bundle.restore_run(bundle)
        restored = entry.open_for_resume(store.run_id)
        stop.record_control(restored, 'resume', label=common.OPERATOR_COMMAND, source='operator_cli',
                            evidence={'command': 'resume'}, reason='restored')
        entry.drive(restored, resume=True, gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)
        after = fakes.final_state(restored)
        assert restored.latest('execution-manifest')['record']['thread_id'] == thread
        assert after['steps']['w']['attempts'] == 1
        assert [step for step, _ in fakes.DISPATCHED].count('w') == 1
        assert [step for step, _ in fakes.DISPATCHED].count('f') == 1
