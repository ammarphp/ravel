"""Prospective connected engineering controls; author has not executed them.

No process-identity reader is replaced in an eligible positive. Existing
fresh-replication fixtures produce actual ordinary supplied-arithmetic receipts
with explicitly synthetic review actors; these are not physics acceptance.
Only root may admit this test population and its ordinary software effects.
"""
from copy import deepcopy
from contextlib import contextmanager
import json
import sys
from pathlib import Path

import pytest

from ravel.workflow import execution, science, physics_review
from ravel.workflow import readonly_preparation as rp, fresh_replication as fresh
from ravel.workflow import research_cycle as cycle
from ravel.workflow.state_io import atomic_json, read_json
from ravel.physics import research_comparison as comparison
from test_readonly_preparation import session, owner_at, tiny_module, prepare
from test_fresh_replication import seed, seed_domain, seed_dispatch_domain, prepare as fresh_prepare, fresh_run  # noqa: F401


def test_initial_injected_unchanged_return_reader_keeps_complete_fallback(tmp_path, monkeypatch):
    """The exact N1 seam cannot acquire the new preparation lifetime."""
    calls = []
    observed = tmp_path / 'input'; observed.write_bytes(b'original')
    def injected(pid):
        calls.append(pid)
        observed.write_bytes(b'late change with unchanged start identity')
        return 'same-start'
    monkeypatch.setattr(execution, 'process_identity', injected)
    monkeypatch.setattr(science, '_await_worker_registration',
                        lambda _: pytest.fail('fallback gate performed new preparation registration'))
    assert science.prepare_readonly_worker(tmp_path, verifier=science.verify_worker) is None
    assert calls == [] and observed.read_bytes() == b'original'
    assert not (tmp_path / 'outputs').exists()


def engineering_worker(tmp_path, monkeypatch):
    """Actual worker predicates, with explicitly controlled authority transport.

    The plan verifier/selection/ledger are synthetic engineering seams. Actual
    launch-selection law, canonical process observer, input hooks and all ending
    boundaries remain source implementations, rather than assertions supplied
    to the hook under test.
    """
    root = tmp_path / 'worker'; root.mkdir()
    (root / 'data').write_bytes(b'supplied arithmetic only')
    stage = {'stage': 'science', 'command': ['engineering-worker'], 'cwd': str(root),
             'inputs': ['data'], 'outputs': ['outputs/attempt-1'], 'depends_on': [],
             'log': 'logs/engineering-worker.log'}
    binding = {'inputs': ['data'], 'fingerprint': 'explicit-engineering-transport'}
    proposal = {'base_dir': str(root), 'stage_binding': deepcopy(binding)}
    atomic_json(root / science.PLAN, proposal)
    atomic_json(root / 'execution_attempt.json', {'attempt': 1})
    module = tiny_module([root / 'data'])
    def verifier(rd, approved=False, *, _session=None, _readonly=None, **kw):
        assert approved is True and _session is not None and _readonly is not None
        _readonly.inputs(module, {'value': 1}, root, 'original')
        _readonly.inputs(module, {'value': 2}, root, 'effective')
        return deepcopy(proposal)
    monkeypatch.setattr(science, 'verify_plan', verifier)
    monkeypatch.setattr(science, '_selected', lambda *a, **k: (deepcopy(stage), deepcopy(binding), 30))
    identity = execution.process_identity(science.os.getpid())
    assert identity is not None and execution.process_identity is science._READONLY_PROCESS_READER
    record = {'status': 'running', 'supervisor_pid': science.os.getppid(),
              'child_pid': science.os.getpid(), 'child_identity': identity,
              'fingerprint': binding['fingerprint']}
    monkeypatch.setattr(execution, 'load_execution', lambda _: {'stages': {'science': deepcopy(record)}})
    return root, module


@pytest.mark.parametrize('change,late', [
    ('positive', False), ('dangling', False),
    ('inputs/native_execution_plan.json', False),
    ('inputs/checkin1_approval.json', False), ('inputs/task_contract.json', False),
    ('inputs/task_contract.json', True),
    ('inputs/research-child-contract.json', False), ('inputs/research-child-contract.json', True),
    ('logs/physics_review/registration.json', False), ('logs/physics_review/head.json', True),
    ('logs/physics_review/events/00000001.json', True)])
def test_actual_worker_boundary_closes_missing_authority_observations(tmp_path, monkeypatch, change, late):
    root, module = engineering_worker(tmp_path, monkeypatch)
    if change == 'dangling':
        path = root / 'inputs/task_contract.json'; path.parent.mkdir(exist_ok=True)
        path.symlink_to(root / 'absent-target')
        assert path.is_symlink() and not path.exists()
    def mutation():
        if change not in ('positive', 'dangling'):
            path = root / change; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"unadmitted":true}\n')
    with owner_at(root, monkeypatch) as owner:
        admitted = science._verify_worker_observed(root, owner.session, _readonly=owner)
        assert admitted['attempt'] == 1 and owner.descriptor is module.READONLY_WORKER_V1
        assert set(owner.session.exists_states) == {root / p for p in
            ('inputs/native_execution_plan.json', 'inputs/checkin1_approval.json',
             'inputs/task_contract.json', 'inputs/research-child-contract.json',
             physics_review.REGISTRATION, physics_review.HEAD)}
        if late:
            # Comes after the actual current-launch semantic callback. Only the
            # complete terminal observation can catch the newly created state.
            owner.add_ending_check(mutation)
        result = owner.calculate({'value': 2}, root)
        if not late:
            mutation()
        owner.materialize(admitted, {'schema_version': 2, 'task': {'value': 2}}, result)
        if change in ('positive', 'dangling'):
            bundle = owner.finish()
            assert isinstance(bundle, rp.PreparedDelivery) and bundle.result['values'] == [3, 7]
        else:
            with pytest.raises(ValueError, match='existence changed|inventory appeared|inventory changed'):
                owner.finish()
    assert owner.closed and owner.session.closed and not (root / 'outputs').exists()


@pytest.mark.parametrize('change', ['positive', 'registration', 'head', 'event'])
def test_actual_registered_review_population_is_not_an_unobserved_label(seed, tmp_path, monkeypatch, change):
    """The original real review graph is read, not replaced by active=True."""
    original = Path(seed['experiment']['rundir']) if seed['experiment'].get('rundir') else seed['base'] / 'paired-run'
    # The fixture's run identity remains original. Restore only this deliberately
    # mutated temporary test member in finally; no actual retained run is used.
    target = original / {'registration': physics_review.REGISTRATION, 'head': physics_review.HEAD,
        'event': physics_review.DIRECTORY + '/events/00000001.json'}.get(change, physics_review.HEAD)
    before = target.read_bytes()
    owner_root = tmp_path / 'owner'; owner_root.mkdir()
    with rp.WorkerReadOnlyObservation(owner_root) as owner:
        # Actual producer factory/Session with the real ledger/runtime law.
        resource = owner.resource(fresh._ProducerSessions)
        review_session = resource.session_for(original)
        science._readonly_worker_boundary(original, review_session)
        assert physics_review.active(original, _session=review_session) is True
        assert (str(original / physics_review.DIRECTORY / 'events'), False) in review_session.queries
        prepare(owner, tiny_module(), owner.rundir)
        if change != 'positive':
            owner.add_ending_check(lambda: target.write_bytes(before + b' \n'))
        try:
            if change == 'positive':
                assert owner.finish().result['values'] == [3, 7]
            else:
                with pytest.raises(ValueError, match='identity changed|file changed'):
                    owner.finish()
        finally:
            if target.read_bytes() != before:
                target.write_bytes(before)
    assert owner.closed and review_session.closed


@pytest.mark.parametrize('change', ['positive', 'applicability', 'source', 'extra-original-output', 'cross-participant'])
def test_actual_replication_request_uses_one_shared_owner_and_complete_reconstruction(seed, tmp_path, monkeypatch, change):
    """Real issued producer, originals/fresh outcome law and both _prepared passes.

    Root may execute the inherited ordinary supplied-quantity fixture. This
    test wraps calls solely to record/trigger adversaries; every producer and
    comparison implementation delegates unchanged. It never supplies _recheck.
    """
    root, check, prepared = fresh_prepare(seed, tmp_path)
    fresh_root = fresh_run(seed, tmp_path, root, prepared)
    bound = fresh.prepare_comparison(root, prepared['request'], tmp_path / 'comparison')
    task = read_json(bound['study']['path'])['task']
    request = read_json(task['request']['path'])
    assert request['replication_request'] == prepared['request']
    original_root = seed['base'] / 'paired-run'
    old_extra = original_root / 'outputs/attempt-1/unlisted-member.json'
    calls = []; reconstructions = []; phases = []
    actual_verify = science.verify_plan
    actual_prepared = fresh._prepared
    actual_scope = science._validation_scope
    producer_caller = cycle._current_evidence.__code__
    public_caller = science.verify_approval_envelope.__code__
    call_records = []; owned_scopes = []; call_stack = []

    @contextmanager
    def observed_scope(rd):
        # Delegate the actual source-owned full scope, never a fake Session or
        # a producer proof. The unchanged context closes even on refusal.
        assert call_stack and call_stack[-1]['kind'] == 'independent-public'
        call = call_stack[-1]
        row = {'call_id': call['id'], 'rundir': str(Path(rd)), 'session': None,
               'fresh_plan_proof': False, 'returned': False, 'closed': False}
        owned_scopes.append(row)
        try:
            with actual_scope(rd) as current:
                row['session'] = current
                row['fresh_plan_proof'] = not any(
                    ('science-v2-plan', approved) in current.proofs for approved in (False, True))
                assert current.rundir == Path(rd) and not current.closed
                assert row['fresh_plan_proof']
                yield current
            # Returning from the original context means its full finish ran;
            # its finally has closed the same real run-bound Session.
            row['returned'] = True
        finally:
            row['closed'] = row['session'] is not None and row['session'].closed

    def observed_verify(rd, approved=False, *, _session=None, _recheck=False, **kw):
        caller = sys._getframe(1).f_code
        kind = ('borrowed-producer' if caller is producer_caller else
                'independent-public' if caller is public_caller else 'unexpected')
        calls.append((Path(rd), _session, approved, _recheck))
        row = {'id': len(calls), 'rundir': str(Path(rd)), 'kind': kind,
               'caller_source': caller.co_filename, 'caller_line': caller.co_firstlineno,
               'caller_name': caller.co_name, 'approved': approved, 'recheck': _recheck,
               'session': _session, 'live_on_entry': _session is not None and not _session.closed,
               'live_on_return': False, 'returned': False, 'exception': None,
               'reconstructions': len(reconstructions)}
        call_records.append(row); call_stack.append(row)
        try:
            # Every observed call has exact provenance. Unknown callers fail
            # explicitly instead of being removed from the recorder population.
            assert kind != 'unexpected', row
            assert approved is True, row
            if kind == 'borrowed-producer':
                current_resource = owner.resources[fresh._ProducerSessions]
                assert _session is current_resource.session_for(rd), row
                assert _recheck is True and _session.rundir == Path(rd) and not _session.closed, row
            else:
                assert _session is None and _recheck is False, row
            answer = actual_verify(rd, approved=approved, _session=_session, _recheck=_recheck, **kw)
            row['returned'] = True
            row['live_on_return'] = _session is not None and not _session.closed
            return answer
        except BaseException as exc:
            row['exception'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            assert call_stack[-1] is row
            call_stack.pop()

    def assert_call_census(resource):
        assert len(calls) == len(call_records) and not call_stack
        borrowed = []; public = []
        for raw, row in zip(calls, call_records):
            rd, current, approved, recheck = raw
            assert approved is True and row['approved'] is approved and row['recheck'] is recheck, row
            if row['kind'] == 'borrowed-producer':
                assert current is resource.session_for(rd), row
                assert recheck is True and current.rundir == rd and not current.closed, row
                assert row['live_on_entry'] and (row['live_on_return'] or not row['returned']), row
                borrowed.append(row)
            elif row['kind'] == 'independent-public':
                assert current is None and recheck is False, row
                matches = [scope for scope in owned_scopes if scope['call_id'] == row['id']]
                assert len(matches) == 1, row
                scope = matches[0]
                assert scope['session'].rundir == rd and scope['fresh_plan_proof'] and scope['closed'], row
                assert scope['returned'] is row['returned'], row
                public.append(row)
            else:
                pytest.fail('unassigned verifier provenance: ' + repr(row))
        # Complete disjoint populations, not any() or a filtered weak witness.
        assert len(borrowed) + len(public) == len(calls)
        assert {Path(row['rundir']) for row in borrowed} == {original_root, fresh_root}
        assert public and fresh_root in {Path(row['rundir']) for row in public}
        assert {Path(row['rundir']) for row in public} <= {original_root, fresh_root}
        assert len(owned_scopes) == len(public)
        independent = [scope['session'] for scope in owned_scopes]
        assert len({id(current) for current in independent}) == len(independent)
        assert all(current is not owner.session and all(current is not entry['session']
                   for entry in resource.entries.values()) for current in independent)
        assert all(current.closed for current in independent)

    def retain_diagnostics():
        # Keep complete provenance/counts even when a source mutation or oracle
        # raises. This is a software diagnostic outside the scientific outputs.
        rows = [{**{key: value for key, value in row.items() if key != 'session'},
                 'session_id': None if row['session'] is None else id(row['session']),
                 'session_closed_at_diagnostic': None if row['session'] is None else row['session'].closed}
                for row in call_records]
        scopes = [{**{key: value for key, value in row.items() if key != 'session'},
                   'session_id': None if row['session'] is None else id(row['session'])}
                  for row in owned_scopes]
        counts = {kind: sum(row['kind'] == kind for row in rows)
                  for kind in ('borrowed-producer', 'independent-public', 'unexpected')}
        diagnostic = {'change': change, 'phases': phases, 'reconstructions': len(reconstructions),
                      'total_calls': len(rows), 'call_counts': counts, 'calls': rows, 'owned_scopes': scopes,
                      'scientific_acceptance': False}
        (tmp_path / 'verify-call-provenance.json').write_text(json.dumps(diagnostic, indent=2) + '\n')

    monkeypatch.setattr(science, '_validation_scope', observed_scope)
    monkeypatch.setattr(science, 'verify_plan', observed_verify)
    def observed_prepared(rd, request_pin, *, _producer_scope=None):
        reconstructions.append(_producer_scope)
        if len(reconstructions) == 7:
            if change == 'applicability':
                state = cycle._load(root)[1]
                state['experiments'][0]['applicability_reopened'] = {'premise_id': 'pairing',
                    'reason': 'Explicit synthetic late applicability adversary; no refreshed original.'}
                cycle._commit(root, state, 'synthetic_late_applicability_adversary')
                assert cycle._applicability(cycle._load(root)[1], cycle._load(root)[1]['experiments'][0])['measurement'] is False
            elif change == 'source':
                source = Path(request['cells'][0]['left']['source']['path'])
                source.write_bytes(source.read_bytes() + b' \n')
            elif change == 'extra-original-output':
                assert not old_extra.exists()
                old_extra.write_text('{"unlisted":true}\n')
        result = actual_prepared(rd, request_pin, _producer_scope=_producer_scope)
        assert result[1] == read_json(prepared['request']['path'])
        assert _producer_scope is not None and _producer_scope.active
        return result
    monkeypatch.setattr(fresh, '_prepared', observed_prepared)
    try:
        owner_root = tmp_path / 'worker'; owner_root.mkdir()
        with rp.WorkerReadOnlyObservation(owner_root) as owner:
            owner.inputs(comparison, task, tmp_path / 'comparison', 'original')
            phases.append(len(reconstructions))
            owner.inputs(comparison, task, tmp_path / 'comparison', 'effective')
            phases.append(len(reconstructions))
            resource = owner.resources[fresh._ProducerSessions]
            assert set(resource.entries) == {original_root, fresh_root}
            assert all(entry['session'] is not owner.session for entry in resource.entries.values())
            if change in ('applicability', 'source', 'extra-original-output'):
                with pytest.raises(ValueError, match='method/evidence/premise changed|authenticated|custody|inventory|changed|differs'):
                    owner.calculate(task, tmp_path / 'comparison')
                assert len(reconstructions) >= 7
                assert_call_census(resource)
            else:
                result = owner.calculate(task, tmp_path / 'comparison')
                phases.append(len(reconstructions))
                assert phases == [2, 4, 8]
                assert all(scope is resource for scope in reconstructions)
                assert {rd for rd, _, _, _ in calls} == {original_root, fresh_root}
                assert_call_census(resource)
                assert result['decision'] == 'equivalent' and result['complete_original_cell_denominator'] == ['one']
                if change == 'cross-participant':
                    target = fresh_root / 'outputs/attempt-1/result.json'
                    def late():
                        assert all(not entry['session'].closed for entry in resource.entries.values())
                        target.write_bytes(target.read_bytes() + b' \n')
                    owner.add_ending_check(late)
                owner.materialize({'attempt': 1, 'base_dir': str(tmp_path / 'comparison'),
                    'output_directory': 'outputs/attempt-1'}, {'schema_version': 2,
                    'mode': 'research-comparison', 'task': task}, result)
                if change == 'cross-participant':
                    with pytest.raises(ValueError, match='identity changed|file changed'):
                        owner.finish()
                else:
                    bundle = owner.finish()
                    assert bundle.result == result and bundle.result['physics_validated'] is False
        assert owner.closed and resource.closed and not (owner.rundir / 'outputs').exists()
        assert len(calls) == len(call_records) and not call_stack
        assert all(row['kind'] in ('borrowed-producer', 'independent-public') for row in call_records)
        assert all(current.closed for _, current, _, _ in calls if current is not None)
        assert all(scope['closed'] for scope in owned_scopes)
    finally:
        retain_diagnostics()
        if old_extra.exists():
            old_extra.unlink()
