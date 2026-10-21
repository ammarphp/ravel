"""Current authority and observed instruction custody at the delivery boundary."""
import contextlib
from copy import deepcopy
import importlib
import io
import json
import re
import sys

import pytest

from ravel.controller import graph as controller
from ravel.controller import instructions
from ravel.controller.authority import issuer, operator
from ravel.controller.sink import evidence, receipts
from test_p06_support import autonomous, operator_home, view  # noqa: F401
from p07_support import Run

AUTHORITY = importlib.import_module('ravel.controller.authority')
ENGAGEMENT = importlib.import_module('ravel.controller.engagement')


def observed_ack(run, *, attempt=1):
    """Use the real instruction producer and verifier, with a controller-held completion."""
    step = next(s for s in run.steps if s['id'] == 's2')
    manifest = instructions.manifest(step, None)
    packet = instructions.packet(manifest, None, step, [])
    binding = dict(run_id=run.store.run_id, step=step['id'], attempt=attempt,
                   manifest_sha256=manifest['sha256'], packet_sha256=packet['sha256'])
    session = run.store.append('worker-session', {
        **binding, 'session_id': 'session-s2-1', 'seat': None, 'packet': packet,
        'card': None, 'step_spec': step, 'inputs': []})
    run.store.append('step-attempt', {**binding, 'session': session})
    instructions.record_delivery(run.store, manifest, packet, session=session)
    final = {'instruction_ack': {'manifest_sha256': manifest['sha256']}, 'checklist': [
        {'unit': u['id'], 'status': 'not_applicable', 'note': 'No scientific operation in this custody control.'}
        for u in manifest['units']]}
    completion = run.store.append('worker-completion', {
        **binding, 'session': session, 'final_record': final, 'artifacts': []})
    with instructions.observed_completion(run.store, session=session, completion_id=completion):
        assert instructions.check_ack(manifest, final, []) == []
    return session, completion


def current_authority(run):
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, 'ravel.controller.engagement', ENGAGEMENT)
        return _current_authority(run)


def _current_authority(run):
    plan = run.plan_doc['sha256']
    approval = AUTHORITY.request(run.store, 'approve_plan', {
        'view': view(run.store, 'approve_plan', plan_sha256=plan)}, {})
    # The final task is R3: CHECK-IN 3 waits for renewed attested operator authority, answered from the operator's
    # own channel with the code the authority issued for this request.
    notices = io.StringIO()
    with contextlib.redirect_stderr(notices):
        final = AUTHORITY.request(run.store, 'final', {
            'view': view(run.store, 'final', plan_sha256=plan, approve_plan=approval['id'])}, {})
    if 'pending' in final:
        code = re.findall(r'--code (\S+)', notices.getvalue())[-1]
        final = AUTHORITY.answer(run.store, final['pending']['request'], code, 'accept')
    assert AUTHORITY.verify(run.store, approval['id'], kind='approve_plan', subject={'plan_sha256': plan})
    assert AUTHORITY.disposition(run.store, final['id'], kind='final', subject={'plan_sha256': plan})
    return approval, final


def authenticated_run(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch).complete()
    monkeypatch.setitem(sys.modules, 'ravel.controller.authority', AUTHORITY)
    monkeypatch.setitem(sys.modules, 'ravel.controller.authority.issuer', issuer)
    run.store.entries[:] = [e for e in run.store.entries
                           if e['kind'] not in ('mode', 'authority', 'worker-session', 'step-attempt',
                                                'worker-completion')
                           and not (e['kind'] == 'instruction-delivery'
                                    and e['record'].get('kind') == 'instruction-delivery')]
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, 'ravel.controller.engagement', ENGAGEMENT)
        autonomous()
        AUTHORITY.freeze_mode(run.store, {'prompt': 'Compute a fictional observable.'})
    return run


def test_receipt_counts_only_the_current_authenticated_authority(tmp_path, monkeypatch, operator_home):
    run = authenticated_run(tmp_path, monkeypatch)
    with controller.services(authority=AUTHORITY):
        current_authority(run)
        old = deepcopy(run.plan_doc)
        run.steps[0]['parameters']['revision'] = 'updated'
        run.pin_plan()
        run.review_round('plan', {'plan-critic': (True, 'accept')})
        run.review_round('final', {'physics-critic': (True, 'accept'), 'skeptical-verifier': (True, 'accept'),
                                   'physics-decider': (True, 'accept')})
        assert old['sha256'] != run.plan_doc['sha256'] and len(run.store.scan('plan')) == 2
        stale = run.deliver()
        assert stale['architecture_predicates']['authority_recorded'] is False
        assert stale['architecture_predicates']['instructions_acknowledged'] is False
        assert stale['architecture_complete'] is False and stale['accepted'] is False
        current_authority(run)
        forged = run.deliver()
        assert forged['architecture_predicates']['authority_recorded'] is True
        assert forged['architecture_predicates']['instructions_acknowledged'] is False
        assert forged['architecture_complete'] is False
        observed_ack(run)
        complete = run.deliver()
        assert complete['accepted'] is True, complete['work']['current_refusals']
        assert complete['architecture_complete'] is True


@pytest.mark.parametrize('fault', ['wrong_attempt', 'missing_completion', 'wrong_packet', 'missing_ack',
                                 'missing_observation'])
def test_observed_instruction_binding_cannot_be_replaced_by_projection(tmp_path, monkeypatch, operator_home, fault):
    run = authenticated_run(tmp_path, monkeypatch)
    with controller.services(authority=AUTHORITY):
        current_authority(run)
        observed_ack(run)
        ev = evidence.gather(run.store, run.plan_doc)
        assert receipts.instructions(ev)['acknowledgement'] == 'complete'
        for entry in run.store.entries:
            if entry['kind'] == 'worker-completion':
                if fault == 'wrong_attempt':
                    entry['record']['attempt'] = 2
                elif fault == 'wrong_packet':
                    entry['record']['packet_sha256'] = '0' * 64
                elif fault == 'missing_ack':
                    entry['record']['final_record']['instruction_ack'] = {}
        if fault == 'missing_completion':
            run.store.entries[:] = [e for e in run.store.entries if e['kind'] != 'worker-completion']
        if fault == 'missing_observation':
            run.store.entries[:] = [e for e in run.store.entries if e['kind'] != 'step-observation']
        receipt = run.deliver()
        assert receipt['architecture_predicates']['instructions_acknowledged'] is False
        assert receipt['accepted'] is False


def test_unknown_usage_prevents_architecture_completion(tmp_path, monkeypatch, operator_home):
    run = authenticated_run(tmp_path, monkeypatch)
    with controller.services(authority=AUTHORITY):
        current_authority(run)
        observed_ack(run)
        for entry in run.store.entries:
            if entry['kind'] == 'budget-settlement':
                entry['record']['measured']['tokens'] = None
        receipt = run.deliver()
        assert 'tokens' in receipt['costs']['unknown']
        assert receipt['architecture_complete'] is False


def test_ending_uses_only_public_ledger_views(tmp_path, monkeypatch):
    from ravel.controller.sink.deliver import ledger_listing
    from p07_support import ledger_module
    import sys
    run = Run(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, 'ravel.controller.ledger', ledger_module(run.ledger, listing=False))
    rows, error = ledger_listing(run.store)
    assert error is None
    assert {r['key'] for r in rows} == set(run.ledger.pending(run.store))
    assert all(r['status'] == 'pending' for r in rows)
    from ravel.controller import sink
    sink.bounded_end(run.store, 'unanswered escalation')
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert ending['ledger_counts'] == run.ledger.summary(run.store)['by_status']
