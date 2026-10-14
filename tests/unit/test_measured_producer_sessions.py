"""Finite source-authored controls. Root alone executes; no physics claim."""
from copy import deepcopy
from pathlib import Path
import shutil

import pytest
from ravel.workflow import fresh_replication as fresh, research_cycle as cycle, science, execution
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.validation_io import ValidationSession
from test_fresh_replication import seed, prepare, fresh_run
from test_science_validation_session import prepared


@pytest.fixture(scope='module')
def connected(seed, tmp_path_factory):
    base = tmp_path_factory.mktemp('producer-session-actual-pair')
    root, _, issued = prepare(seed, base)
    rd = fresh_run(seed, base, root, issued)
    bound = fresh.prepare_comparison(root, issued['request'], base/'comparison')
    request = read_json(bound['study']['path'])['task']['request']
    return root, rd, read_json(request['path']), base/'comparison'


def bare(base, name):
    rd = base/name;rd.mkdir()
    atomic_json(rd/science.PLAN, {'schema_version': 2})
    return rd


def test_real_pair_reuses_producer_sessions_but_preserves_both_reconstructions(connected, monkeypatch):
    root, rd, request, base = connected
    acquisitions = []; semantic = []; traversals = []
    old_session = fresh._ProducerSessions.session_for
    old_verify = science._verify_v2;old_prepared = fresh._prepared
    def session_for(owner, path):
        session = old_session(owner, path)
        acquisitions.append((owner, science.root(path), session))
        return session
    def verify(*args, **kwargs):
        semantic.append(kwargs.get('_session'))
        return old_verify(*args, **kwargs)
    def reconstructed(*args, **kwargs):
        traversals.append(kwargs.get('_producer_scope'))
        return old_prepared(*args, **kwargs)
    monkeypatch.setattr(fresh._ProducerSessions, 'session_for', session_for)
    monkeypatch.setattr(science, '_verify_v2', verify)
    monkeypatch.setattr(fresh, '_prepared', reconstructed)
    first = fresh.check_comparison(request, base)
    first_objects = [v[2] for v in acquisitions]
    first_sessions = {id(v) for v in first_objects}
    assert len(traversals) == 2 and traversals[0] is traversals[1]
    assert len(first_sessions) == 2  # actual original and actual fresh runs
    assert len(acquisitions) > len(first_sessions)
    assert len([v for v in semantic if id(v) in first_sessions]) == len(acquisitions)
    assert all(v[2].closed for v in acquisitions)
    acquisitions.clear();traversals.clear();semantic.clear()
    assert fresh.check_comparison(request, base) == first
    assert first_sessions.isdisjoint({id(v[2]) for v in acquisitions})
    assert len(traversals) == 2 and all(v[2].closed for v in acquisitions)


@pytest.mark.parametrize('member', ['file', 'empty_directory'])
def test_original_output_growth_preserves_existing_custody_contract(connected, monkeypatch, member):
    root, fresh_rd, request, base = connected
    doc = read_json(request['replication_request']['path'])
    original = Path(doc['originals'][0]['experiment']['rundir'])
    unexpected = original/'outputs/attempt-1/unlisted-session-control'
    saved_snapshot = read_json(original/execution.STATE_NAME)['stages']['science']['output_snapshot']
    saved_cells = deepcopy(request['cells'])
    expected_ids = [row['id'] for row in doc['population']]
    operand_paths = {cell[side]['source']['path'] for cell in request['cells'] for side in ('left', 'right')}
    saved_operands = {path:read_json(path) for path in operand_paths}
    old = cycle._current_evidence;changed = []
    def evidence(state, e, **kwargs):
        result = old(state, e, **kwargs)
        if Path(e['rundir']) == fresh_rd and not changed:
            changed.append(True)
            if member == 'file':unexpected.write_text('unlisted original output')
            else:unexpected.mkdir()
        return result
    monkeypatch.setattr(cycle, '_current_evidence', evidence)
    try:
        if member == 'file':
            with pytest.raises(ValueError, match='custody|inventory|snapshot|output|artifact|binding'):
                fresh.check_comparison(request, base)
        else:
            # Saved execution snapshots commit regular-file leaves. Empty
            # children of a nonempty output do not change that old schema.
            # Explicit live require_inventory negatives stay separate/exact.
            pins = fresh.check_comparison(request, base)
            assert changed and unexpected.is_dir() and pins
            assert execution.snapshot(original, ['outputs/attempt-1'], outputs=True) == saved_snapshot
            assert request['cells'] == saved_cells
            assert [row['id'] for row in request['cells']] == expected_ids
            assert {path:read_json(path) for path in operand_paths} == saved_operands
            assert all([row['id'] for row in value['cells']] == expected_ids for value in saved_operands.values())
            assert {str(Path(path).resolve()) for path in operand_paths} <= {str(Path(p['path']).resolve()) for p in pins}
        assert changed
    finally:
        if unexpected.is_dir():unexpected.rmdir()
        elif unexpected.exists():unexpected.unlink()


def test_borrowed_plan_rechecks_dynamic_adapter_admission(prepared):
    rd, payload, inventory, implementation = prepared
    with pytest.raises(ValueError, match='runtime bytes differ'):
        with fresh._ProducerSessions() as owner:
            session = owner.session_for(rd)
            science.verify_plan(rd, approved=True, _session=session, _recheck=True)
            inventory['files'][0]['sha256'] = '0'*64
            science.verify_plan(rd, approved=True, _session=owner.session_for(rd), _recheck=True)
    assert session.closed


def test_default_plan_memo_is_unchanged_and_recheck_is_full(prepared, monkeypatch):
    rd, _, _, _ = prepared;calls = [];old = science._verify_v2
    def verify(*args, **kwargs):
        calls.append(kwargs['approved']);return old(*args, **kwargs)
    monkeypatch.setattr(science, '_verify_v2', verify)
    with science._validation_scope(rd) as session:
        p = science.verify_plan(rd, approved=False, _session=session)
        assert science.verify_plan(rd, approved=False, _session=session) is p
        assert calls == [False]
        science.verify_plan(rd, approved=True, _session=session, _recheck=True)
        science.verify_plan(rd, approved=True, _session=session, _recheck=True)
        assert calls == [False, True, True]


@pytest.mark.parametrize('mutation', ['replace_same_bytes', 'disappear', 'appear'])
def test_reused_ledger_identity_content_and_absence_are_fresh(tmp_path, mutation):
    rd = bare(tmp_path, 'run');ledger = rd/execution.STATE_NAME
    if mutation != 'appear':atomic_json(ledger, {'schema_version':1,'revision':0,'stages':{}})
    with pytest.raises(ValueError, match='identity changed|appeared or disappeared'):
        with fresh._ProducerSessions() as owner:
            session = owner.session_for(rd)
            if mutation == 'replace_same_bytes':
                replacement = rd/'replacement.json';replacement.write_bytes(ledger.read_bytes());replacement.replace(ledger)
            elif mutation == 'disappear':ledger.unlink()
            else:atomic_json(ledger, {'schema_version':1,'revision':0,'stages':{}})
            owner.session_for(rd)
    assert session.closed


def test_separate_canonical_runs_and_cross_run_refusal(prepared, tmp_path):
    rd, _, _, _ = prepared;other = bare(tmp_path, 'other')
    with fresh._ProducerSessions() as owner:
        a = owner.session_for(rd);b = owner.session_for(other)
        assert a is owner.session_for(rd) and a is not b
        with pytest.raises(ValueError, match='cross-run'):
            science.verify_plan(rd, _session=b, _recheck=True)
    assert a.closed and b.closed
    with pytest.raises(ValueError, match='closed'):owner.session_for(rd)
    with pytest.raises(ValueError, match='cannot be reused'):
        with owner:pass


def test_changed_callable_refuses_existing_proof(prepared, monkeypatch):
    rd, _, _, _ = prepared;original = science.verify_plan
    def replacement(rundir, approved=False, *, _session=None, _recheck=False):
        return original(rundir, approved, _session=_session, _recheck=_recheck)
    with pytest.raises(ValueError, match='verifier changed'):
        with fresh._ProducerSessions() as owner:
            session = owner.session_for(rd)
            monkeypatch.setattr(science, 'verify_plan', replacement)
            owner.session_for(rd)
    assert session.closed


def test_unsupported_injected_callable_and_legacy_routing_stay_unshared(prepared, monkeypatch):
    rd, _, _, _ = prepared;calls = [];original = science.verify_plan
    def legacy(rundir, approved=False):
        calls.append((rundir, approved));return original(rundir, approved)
    monkeypatch.setattr(science, 'verify_plan', legacy)
    with fresh._ProducerSessions() as owner:
        assert owner.session_for(rd) is None and not owner.entries
    # The existing current-evidence forwarded call receives no new keywords.
    assert legacy(rd, approved=True)['schema_version'] == 2 and calls == [(rd, True)]


def test_legacy_schema_keeps_original_plan_validation(tmp_path):
    rd = bare(tmp_path, 'legacy')
    atomic_json(rd/science.PLAN, {'schema_version':1})
    atomic_json(rd/science.SPEC, {'schema_version':1})
    with fresh._ProducerSessions() as owner:
        assert owner.session_for(rd) is None and not owner.entries


@pytest.mark.parametrize('mutation', ['input', 'empty_directory', 'absent_directory', 'mutable_object', 'runtime', 'ancestor_symlink', 'mode'])
def test_late_existing_session_census_is_preserved(prepared, monkeypatch, mutation):
    rd, payload, _, _ = prepared;renamed = None
    try:
        with pytest.raises(ValueError, match='changed|inventory|symlink|runtime|path'):
            with fresh._ProducerSessions() as owner:
                session = owner.session_for(rd)
                science.verify_plan(rd, approved=True, _session=session, _recheck=True)
                if mutation == 'input':payload.write_bytes(b'X'+payload.read_bytes()[1:])
                elif mutation == 'empty_directory':
                    directory = rd/'observed';directory.mkdir();session.require_inventory(directory);(directory/'empty').mkdir()
                elif mutation == 'absent_directory':
                    session.require_inventory(rd/'absent');(rd/'absent').mkdir()
                elif mutation == 'mutable_object':
                    value = {'kind':['one']};session.track(value);value['kind'].append('two')
                elif mutation == 'runtime':
                    session.runtime_context = lambda: {'changed_runtime':True}
                elif mutation == 'ancestor_symlink':
                    renamed = payload.parent.with_name(payload.parent.name+'-moved')
                    payload.parent.rename(renamed);payload.parent.symlink_to(renamed, target_is_directory=True)
                else:payload.chmod(0o600 if payload.stat().st_mode & 0o777 != 0o600 else 0o644)
        assert session.closed
    finally:
        if renamed is not None:
            parent = payload.parent;parent.unlink();renamed.rename(parent)


@pytest.mark.parametrize('failure', ['body', 'second_acquisition', 'first_finish', 'first_close'])
def test_all_acquired_sessions_close_and_primary_failure_survives(tmp_path, monkeypatch, failure):
    a = bare(tmp_path, 'a');b = bare(tmp_path, 'b');sessions = []
    factory = execution._validation_session
    def opened(rd, *tracked):
        if failure == 'second_acquisition' and sessions:raise ValueError('explicit second acquisition failure')
        session = factory(rd, *tracked);sessions.append(session)
        if len(sessions) == 1 and failure == 'first_finish':
            def fail_finish():raise ValueError('explicit first finish failure')
            monkeypatch.setattr(session, 'finish', fail_finish)
        if len(sessions) == 1 and failure == 'first_close':
            old_close = session.close
            def fail_close():old_close();raise ValueError('explicit first close failure')
            monkeypatch.setattr(session, 'close', fail_close)
        return session
    monkeypatch.setattr(execution, '_validation_session', opened)
    expected = 'explicit second acquisition failure' if failure == 'second_acquisition' else 'explicit first finish failure' if failure == 'first_finish' else 'explicit body failure'
    with pytest.raises(ValueError, match=expected) as error:
        with fresh._ProducerSessions() as owner:
            owner.session_for(a);owner.session_for(b)
            if failure in {'body','first_close'}:raise ValueError('explicit body failure')
    assert sessions and all(s.closed for s in sessions)
    if failure == 'first_close':assert any('explicit first close failure' in v for v in error.value.__notes__)


def test_failed_and_unknown_actual_cells_keep_complete_population(seed, tmp_path):
    root, _, issued = prepare(seed, tmp_path, semantics='unknown', quality='unknown')
    fresh_run(seed, tmp_path, root, issued, accepted=False, failed=True)
    bound = fresh.prepare_comparison(root, issued['request'], tmp_path/'comparison')
    request = read_json(read_json(bound['study']['path'])['task']['request']['path'])
    pins = fresh.check_comparison(request, tmp_path/'comparison')
    assert pins and [v['id'] for v in request['cells']] == ['one']
    operand = read_json(request['cells'][0]['left']['source']['path'])['cells'][0]
    assert operand['original_execution_status'] == 'failed' and operand['quality'] is False
    assert operand['value'] is None and operand['reason']


@pytest.mark.parametrize('artifact', [science.SPEC, science.PLAN, 'inputs/checkin1.json', science.APPROVAL])
def test_each_borrowed_call_rechecks_current_semantic_files(prepared, artifact):
    rd, _, _, _ = prepared
    with pytest.raises(ValueError, match='identity changed|changed during|stale|differs'):
        with fresh._ProducerSessions() as owner:
            session = owner.session_for(rd)
            science.verify_plan(rd, approved=True, _session=session, _recheck=True)
            path = rd/artifact
            raw = read_json(path);raw['session-control-mutation'] = True;atomic_json(path, raw)
            science.verify_plan(rd, approved=True, _session=owner.session_for(rd), _recheck=True)
    assert session.closed


def test_empty_owner_and_borrowed_scope_cannot_outlive_one_call():
    owner = fresh._ProducerSessions()
    with owner:
        with fresh._producer_validation(owner) as borrowed:assert borrowed is owner
    with pytest.raises(ValueError, match='cannot be reused'):
        with owner:pass
    with pytest.raises(ValueError, match='active same-call'):
        with fresh._producer_validation(owner):pass
