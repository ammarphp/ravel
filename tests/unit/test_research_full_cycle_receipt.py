"""Real receipt observation on the same inert full-cycle campaign.

The existing fixture owns transport responses. Every approval, decision,
execution, role-credit and final-checkpoint predicate stays authoritative.
"""
import json
from pathlib import Path

from ravel.workflow import architecture_receipt, research_cycle as cycle, agent_graph
from ravel.workflow import research_protocol as protocol, rdj_loop
from test_physics_review import run  # noqa: F401


def test_campaign_ci2_join_reads_review_custody_from_its_recorded_run_path(run, tmp_path, monkeypatch):
    """Campaign records hold run paths as text; the CI2 predecessor join must still read them."""
    from ravel.workflow import physics_review, research_architecture
    from test_physics_review import opened, accept
    root, _ = run
    opened(run)
    accept(root)
    saved = physics_review.snapshot(root, action='reuse')
    (tmp_path/'ci2-snapshot.json').write_text(json.dumps(saved))
    # Isolate the CI2 join: the campaign evidence predicate is exercised by the full-cycle controls.
    monkeypatch.setattr(cycle, '_current_evidence', lambda state, experiment, **kwargs: None)
    experiment = {'rundir': str(root), 'adjudication': {'snapshot': cycle._pin(tmp_path/'ci2-snapshot.json')}}
    assert research_architecture._ci2({'base_dir': str(tmp_path)}, experiment) == saved


def joined(receipt):
    """Every authority join of a legacy receipt holds: the research join and the credited required roles.

    These two predicates were the whole of ``architecture_complete`` before legacy receipts gained the
    controller-mode predicate (always false outside the controller), so each damage below still has to
    break one of them.
    """
    predicates = receipt['architecture_predicates']
    return predicates['research_join_complete'] is True and predicates['required_roles_credited'] is True


def test_missing_campaign_evidence_never_reports_complete_architecture(tmp_path):
    receipt = architecture_receipt.build_receipt(tmp_path, [])
    assert receipt['architecture_complete'] is False
    assert receipt['accepted'] is False
    assert receipt['host']['whole_host_enforcement'] == 'unknown'
    assert receipt['research']['complete'] is False
    architecture_receipt.verify_saved_receipt(receipt)


def test_same_campaign_receipt_requires_every_current_authority_join(tmp_path, monkeypatch, record_property):
    """Removing or staling a joined authority record makes the current receipt incomplete.

    The complete campaign comes from the full-cycle traversal on one stage engine;
    parity between engines is the main traversal's separate control. A complete
    receipt costs minutes to recompute, so the controls remove one record per join
    and completeness is recomputed once, after every restoration; a failure names
    the incomplete join. Other joins are asserted present by the main control.
    """
    import time
    import warnings
    import test_research_full_cycle as main
    # Keep the complete receipt the traversal already recomputed; nothing is replaced.
    built = []
    checked = main.assert_architecture
    monkeypatch.setattr(main, 'assert_architecture',
                        lambda root, rd: built.append(checked(root, rd)) or built[-1])
    started = time.monotonic()
    root, rd = main.full_cycle(tmp_path, record_property, engines=('graph',))
    receipt = built[-1]
    # Timing reaches the log as a warning even if a long run is interrupted.
    warnings.warn(f'receipt control: complete campaign after {time.monotonic() - started:.0f} s')
    _, state = cycle._load(root)
    final = next(e for e in state['experiments'] if e['id'] == 'confirmation')
    assert Path(final['rundir']) == rd
    population = [{'path': 'outputs/attempt-1/result.json', 'kind': 'number'}]
    builds = []

    def current():
        begun = time.monotonic()
        try:
            return architecture_receipt.build_receipt(rd, population)
        finally:
            builds.append(round(time.monotonic() - begun, 1))
            warnings.warn(f'receipt control: build {len(builds)} took {builds[-1]} s')

    assert joined(receipt) and receipt['research']['campaign'] == str(root)
    # A run the controller does not own is never architecture-complete (NOT GOVERNED); the joins are the evidence.
    assert receipt['architecture_predicates']['controller_mode'] is False
    assert receipt['architecture_complete'] is False
    assert architecture_receipt.NOT_GOVERNED in receipt['notices']
    assert receipt['host']['whole_host_enforcement'] == 'unknown'
    assert receipt['research']['parent_task_accepted'] is False
    assert receipt['roles']['missing'] == []
    assert receipt['roles']['ordinary_final']['status'] == 'observed'
    assert receipt['accepted'] is False
    assert len(receipt['research']['experiments']) == len(state['experiments'])
    assert len(receipt['research']['stages']) == len(state['methodology']['stages'])
    assert receipt['research']['experiments'][0]['dispatch']['status'] == 'observed'
    architecture_receipt.verify_saved_receipt(receipt)
    stage = next(s for s in state['methodology']['stages'] if s['status'] == 'done')
    role_pin = stage['worker_receipts'][stage['roles'][0]]
    authorization = rdj_loop.authorizing_receipt(root, 'research_choice',
                                                protocol.stage_action(stage['id'], stage['artifact']))
    assert authorization is not None
    final_manifest = rd / receipt['research']['final_checkpoint']['manifest']['path']
    # One record per join: campaign intake, stage role receipt, stage decision, idea
    # stream, study execution and the final checkpoint; stale bytes for the first two.
    targets = [('campaign intake', root / 'inputs/task_contract.json', True),
               ('stage role receipt', Path(role_pin['path']), True),
               ('stage decision case', rdj_loop._case_path(root, authorization['case']['case_id']), False),
               ('idea stream Graph', root/'idea-dispatches/a/graph'/agent_graph.SPEC, False),
               ('study execution record', Path(final['observation']['receipt']['path']), False),
               ('final checkpoint manifest', final_manifest, False)]
    for label, target, stale in targets:
        if not target.is_absolute():
            target = root / target
        raw = target.read_bytes()
        target.unlink()
        try:
            missing = current()
            assert not joined(missing), label
            assert (missing['research']['errors'] or missing['roles']['errors']
                    or missing['roles'].get('ordinary_final', {}).get('errors')), label
        finally:
            target.write_bytes(raw)
        if stale:
            target.write_bytes(raw + b'\n')
            try:
                assert not joined(current()), label
            finally:
                target.write_bytes(raw)
    restored = current()
    assert joined(restored), json.dumps({
        'research': restored['research']['errors'], 'roles': restored['roles']['errors'],
        'ordinary_final': restored['roles'].get('ordinary_final', {}).get('errors')},
        sort_keys=True, default=str)[:4000]
    record_property('receipt_control_seconds', json.dumps(
        {'total': round(time.monotonic() - started, 1), 'builds': builds}))
