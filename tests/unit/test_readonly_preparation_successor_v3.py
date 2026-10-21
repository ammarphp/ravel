"""Unrun finite N2/C2 controls over real review/index/receipt implementations.

All authorities are explicitly synthetic local engineering fixtures. No native,
model, optimizer or scientific acceptance is inferred from these controls.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.workflow import execution, physics_review as review, review_context
from ravel.workflow import science, workflow_state, readonly_preparation as rp
from ravel.workflow.state_io import atomic_json, read_json
from ravel.physics.ma5_saf import Capture
from test_readonly_preparation import tiny_module, prepare
from bound_review import bound_review
from correction_lookup_fixture import policy, make_attempt, check_packet, finding


def admitted_fixture(tmp_path, monkeypatch, *, downstream=False):
    root = tmp_path / 'run'; (root / 'inputs').mkdir(parents=True)
    declared = policy()
    if downstream:
        declared['allowed_stages'].append('consumer')
    atomic_json(root / review.POLICY, declared)
    atomic_json(root / 'inputs/checkin1_approval.json', {'synthetic': 'local engineering approval boundary'})
    monkeypatch.setattr(workflow_state, 'approval_input_paths', lambda rd: [str(Path(rd) / review.POLICY)])
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **kw: [])
    # Preserve the original complete runtime/environment binding; only the
    # repeated fixture observation is controlled, never the begin_attempt guard.
    runtime = execution.runtime_context()
    monkeypatch.setattr(execution, 'runtime_context', lambda: deepcopy(runtime))
    (root / 'inputs/settings.cfg').write_text('efficiency=0.8\n')
    (root / 'inputs/held-fixed.txt').write_text('fixed recipe\n')
    atomic_json(root / 'inputs/reference.json', {'reference': 1})
    original = make_attempt(root); check_packet(root, original)
    cycle = review.open_cycle(root, effective_settings=['inputs/settings.cfg'],
        stage_receipts=[original['attempt_record']], check_results='inputs/checks.json')
    note = tmp_path / 'external-correction-note.txt'; note.write_text('Located engineering correction rationale.\n')
    packet = tmp_path / 'role-packet'
    manifest = review_context.create(root, 'critic', packet)
    typed = {'kind': 'role_context', 'path': str(packet / 'manifest.json'),
        'sha256': execution.file_hash(packet / 'manifest.json'), 'manifest_sha256': manifest['sha256'],
        'cycle_id': cycle['cycle_id'], 'cycle_sha256': cycle['sha256']}
    supports = [{'path': str(note), 'sha256': execution.file_hash(note)}, typed]
    # The send-back is the bound response of a dispatched critic (a decider is dispatched only after both
    # independent decisions); the decider admits the correction below. The supports ride beside the role's own.
    bound_review(root, role='physics_critic', verdict='send_back',
        summary='Synthetic engineering source-custody correction', findings=[finding()], supporting_artifacts=supports)
    (root / 'inputs/settings.cfg').write_text('efficiency=0.85\n')
    specs = None
    stages = ['detector']
    if downstream:
        stages.append('consumer')
        specs = [{'stage': 'detector', **{k: original[k] for k in ('command', 'cwd', 'inputs', 'outputs', 'log')},
                  'depends_on': []},
                 {'stage': 'consumer', 'command': ['synthetic-consumer'], 'cwd': str(root),
                  'inputs': ['inputs/settings.cfg', 'outputs/produced.json'],
                  'outputs': ['outputs/consumed.json'], 'depends_on': ['detector'], 'log': 'logs/consumer.log'}]
    correction = review.authorize_correction(root, actor_id='physicist', changed_paths=['inputs/settings.cfg'],
        stages=stages, recheck_checks=['agreement'], stage_specs=specs, supporting_artifacts=supports)
    assert review.gate_errors(root, 'correction', 'detector') == []
    return root, correction, note, packet, manifest


def check_current(root, correction, session, stage='detector'):
    """The actual science consumer transports the exact current correction law."""
    admitted = next(row for row in correction['stage_specs'] if row['stage'] == stage)
    selected = {'stage': admitted, 'binding': {'inputs': admitted['inputs']}, 'max_seconds': 30}
    context = {'stage_spec': deepcopy(admitted), 'max_seconds': 30, 'review_action': 'correction'}
    science._check_launch_selection(root, selected, stage, admitted['command'], context, session,
                                   _review_session=session)


@pytest.mark.parametrize('change', ['positive', 'note-before-ending', 'note-after-ending',
    'copy-after-ending', 'extra-after-ending', 'snapshot-after-ending', 'foreign-command'])
def test_actual_correction_gate_retains_full_note_packet_and_snapshot_tail(tmp_path, monkeypatch, change):
    root, correction, note, packet, manifest = admitted_fixture(tmp_path, monkeypatch)
    atomic_json(root / 'execution_attempt.json', {'attempt': 2})
    with rp.WorkerReadOnlyObservation(root) as owner:
        check_current(root, correction, owner.session)
        assert owner.session.proofs[('readonly-correction-gate',)] is True
        assert str(note) in owner.session.files
        assert (str(packet), False) in owner.session.queries
        assert (str(packet / 'artifacts'), False) in owner.session.queries
        checks = tuple(owner.session.final_checks)
        assert checks
        captured = {name: deepcopy(getattr(owner.session, name))
                    for name in ('files', 'hashes', 'queries', 'path_identities')}
        prepare(owner, tiny_module(), root)
        def current():
            # Other complete correction observations may append obligations
            # before freeze. Every original object/order and fact must remain.
            before_checks = tuple(owner.session.final_checks)
            before_facts = {name: deepcopy(getattr(owner.session, name))
                            for name in captured}
            check_current(root, correction, owner.session)
            assert all(actual is expected for actual, expected in
                       zip(owner.session.final_checks, checks))
            assert len(owner.session.final_checks) >= len(checks)
            # This ending semantic replay is frozen: it may enroll no callback.
            assert len(owner.session.final_checks) == len(before_checks)
            assert all(actual is expected for actual, expected in
                       zip(owner.session.final_checks, before_checks))
            for name in captured:
                current_facts = getattr(owner.session, name)
                assert all(key in current_facts and current_facts[key] == value
                           for key, value in captured[name].items())
                assert all(key in current_facts and current_facts[key] == value
                           for key, value in before_facts[name].items())
        owner.add_ending_check(current)
        if change == 'note-before-ending':
            note.write_text('Changed before ending semantic gate.\n')
        elif change not in ('positive', 'foreign-command'):
            def mutate():
                if change == 'note-after-ending': note.write_text('Changed after ending semantic gate.\n')
                elif change == 'copy-after-ending':
                    (packet / manifest['artifacts'][0]['path']).write_bytes(b'late changed packet copy')
                elif change == 'extra-after-ending':
                    (packet / 'artifacts/extra.txt').write_bytes(b'late extra packet member')
                else:
                    (root / correction['snapshots'][0]['path']).write_bytes(b'late changed correction source')
            owner.add_ending_check(mutate)
        if change == 'positive':
            assert owner.finish().result['values'] == [3, 7]
        elif change == 'foreign-command':
            row = correction['stage_specs'][0]
            assert review.correction_execution_errors(root, 'detector', ['foreign'], row['inputs'],
                row['outputs'], row['depends_on'], row['cwd'], row['log'], _session=owner.session)
            assert owner.finish().result['physics_validated'] is False
        else:
            with pytest.raises(ValueError, match='changed|differs|identity'):
                owner.finish()
    assert owner.closed and owner.session.closed
    assert not (root / 'adapter.json').exists()


@pytest.mark.parametrize('change', ['positive', 'source-after-ending', 'source-member-after-ending'])
def test_typed_packet_native_source_capture_is_retained_after_its_finish(tmp_path, monkeypatch, change):
    """Exact generic Capture law behind the actual typed PacketIndex hook.

    This is a controlled source-capture transport fixture, not a released
    SFitter designer packet or a new scientific result.
    """
    root = tmp_path / 'run'; root.mkdir()
    source_root = tmp_path / 'native-source'; source_root.mkdir()
    source = source_root / 'source.saf'; source.write_bytes(b'released capture fixture bytes')
    capture = Capture(); capture.read(source, source_root)
    capture.roots[source_root] = capture.census(source_root)
    packet = tmp_path / 'packet'; (packet / 'artifacts').mkdir(parents=True)
    (packet / 'manifest.json').write_bytes(b'controlled packet metadata')
    index = SimpleNamespace(root=packet, source_capture=capture)
    with rp.WorkerReadOnlyObservation(root) as owner:
        review._readonly_context_sources(root, index, owner.session)
        assert owner.session.hash_file(source) == execution.file_hash(source)
        owner.session.retain_final_check(capture.finish)
        prepare(owner, tiny_module(), root)
        if change != 'positive':
            def mutate():
                if change == 'source-after-ending': source.write_bytes(b'changed original source')
                else: (source_root / 'extra.saf').write_bytes(b'late new original source member')
            owner.add_ending_check(mutate)
        if change == 'positive':
            assert owner.finish().result['physics_validated'] is False
        else:
            with pytest.raises(ValueError, match='changed|identity'):
                owner.finish()
    assert owner.closed and owner.session.closed


@pytest.mark.parametrize('change', ['positive', 'producer-output-after-ending', 'producer-receipt-after-ending'])
def test_actual_regenerated_predecessor_uses_borrowed_live_session_to_joint_tail(tmp_path, monkeypatch, change):
    root, correction, _, _, _ = admitted_fixture(tmp_path, monkeypatch, downstream=True)
    produced = make_attempt(root, value=2)
    atomic_json(root / 'execution_attempt.json', {'attempt': 2})
    assert produced['attempt_id'] != review._view(*review._read(root))['cycle']['receipts'][0]['attempt_id']
    with rp.WorkerReadOnlyObservation(root) as owner:
        check_current(root, correction, owner.session, 'consumer')
        assert not owner.session.closed
        assert str(root / produced['attempt_record']) in owner.session.files
        assert str(root / 'outputs/produced.json') in owner.session.files
        prepare(owner, tiny_module(), root)
        owner.add_ending_check(lambda: check_current(root, correction, owner.session, 'consumer'))
        if change != 'positive':
            target = root / ('outputs/produced.json' if change == 'producer-output-after-ending' else produced['attempt_record'])
            owner.add_ending_check(lambda: target.write_bytes(target.read_bytes() + b' \n'))
        if change == 'positive':
            assert owner.finish().result['values'] == [3, 7]
        else:
            with pytest.raises(ValueError, match='changed|identity'):
                owner.finish()
    assert owner.closed and owner.session.closed
