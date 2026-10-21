"""The sink's hooks into its peers, on fictional controller runs.

Route delivery checks (the manuscript build and the staged ML stages) withhold acceptance with
every field of their typed problems rendered; the routes' ending records are rendered in a
qualified delivery, and the artifacts a route selects for its ending are delivered only after the
sink verifies them again, labelled and never accepted. Host governance's label reaches every
notice and the report; the receipt carries the authority issuer's own account of itself and never
attests terminal identity; the engagement envelope is checked for each delivery and an envelope
that allows no acceptance withholds the accepted label and is rendered.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from ravel.controller import sink
from ravel.controller.sink import checks
from ravel.controller.sink.deliver import _error_row
from p07_support import ISSUER_RECEIPT, REPORT, VALUE, Run, digest, run  # noqa: F401  (run fixture)

ML_STAGE = 'fictional-ml-stage-train'


def ml_route(monkeypatch, calls=None):
    """A staged ML route package with the published check: every staged step needs an accepted, completed
    stage record bound to the delivered plan (the route's ``ml-stage`` records)."""
    module = types.ModuleType('ravel.controller.routes.ml.staged')

    def delivery_errors_from_store(store, plan):
        if calls is not None:
            calls.append(plan['sha256'])
        latest = {e['record'].get('step_id'): e['record'] for e in store.scan('ml-stage')}
        found = []
        for step in plan.get('steps') or ():
            if step.get('operation') != ML_STAGE:
                continue
            record = latest.get(step['id']) or {}
            if not record.get('accepted') or record.get('status') != 'completed' \
                    or record.get('plan_sha256') != plan['sha256']:
                found.append({'code': 'ml_stage_unreceipted', 'step': step['id'], 'stage': 'train'})
        return found
    module.delivery_errors_from_store = delivery_errors_from_store
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


def ml_run(tmp_path, monkeypatch, *, route='judgment'):
    run = Run(tmp_path, monkeypatch)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])['operation'] = ML_STAGE
    run.add_step('s2', ['outputs/report.md'], kind='synthesize', inputs=['s1:outputs/value.json'],
                 deliverables=[('d-report', 'outputs/report.md')])
    plan = run.pin_plan()
    if route != 'judgment':
        # The plan of another route: re-pin it under that route id.
        plan = dict(plan, route={'id': route, 'version': 1, 'spec_sha256': None})
        plan.pop('sha256')
        plan['sha256'] = digest(plan)
        blob = run.store.put_blob(json.dumps(plan, sort_keys=True).encode())
        run.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'source': 'compile', 'revision': 0,
                                  'route': route})
        run.plan_doc = plan
    run.adopt('s1', 'outputs/value.json', VALUE, kind='result')
    run.adopt('s2', 'outputs/report.md', REPORT, kind='document', producer='worker', inputs=['s1:outputs/value.json'])
    run.authority_record('approve_plan', 'approve')
    run.authority_record('final', 'accept', authorizes=False)
    run.review_round('plan', {'plan-critic': (True, 'accept')})
    run.review_round('final', {'physics-critic': (True, 'accept'), 'skeptical-verifier': (True, 'accept'),
                               'physics-decider': (True, 'accept')})
    run.satisfy_upstream()
    return run


# ---- route delivery checks ---------------------------------------------------------------------------

def test_the_staged_ml_route_check_withholds_acceptance_with_its_typed_reason(tmp_path, monkeypatch):
    run = ml_run(tmp_path, monkeypatch)
    calls = []
    ml_route(monkeypatch, calls)
    receipt = run.deliver()
    assert calls == [run.plan_doc['sha256']]
    assert receipt['label'] == 'diagnostic' and receipt['architecture_complete'] is False
    refusal = next(r for r in receipt['work']['current_refusals'] if r['code'] == 'ml')
    assert refusal['message'] == 'ml_stage_unreceipted: step s1, stage train'
    assert refusal['typed'] == {'code': 'ml_stage_unreceipted', 'step': 's1', 'stage': 'train'}


def test_the_staged_ml_route_check_positive_control_a_receipted_stage(tmp_path, monkeypatch):
    run = ml_run(tmp_path, monkeypatch)
    ml_route(monkeypatch)
    run.store.append('ml-stage', {'step_id': 's1', 'stage': 'train', 'status': 'completed', 'accepted': True,
                                  'plan_sha256': run.plan_doc['sha256']})
    receipt = run.deliver()
    assert receipt['label'] == 'accepted' and receipt['architecture_complete'] is True
    assert not [r for r in receipt['work']['current_refusals'] if r['code'] == 'ml']


def test_a_stage_record_bound_to_another_plan_receipts_nothing(tmp_path, monkeypatch):
    run = ml_run(tmp_path, monkeypatch)
    ml_route(monkeypatch)
    run.store.append('ml-stage', {'step_id': 's1', 'stage': 'train', 'status': 'completed', 'accepted': True,
                                  'plan_sha256': 'f' * 64})
    assert run.deliver()['label'] == 'diagnostic'


def test_a_plan_of_a_route_whose_check_is_not_installed_is_refused(tmp_path, monkeypatch):
    run = ml_run(tmp_path, monkeypatch, route='ml.training')
    receipt = run.deliver()  # the staged ML package is absent in this fixture
    assert receipt['label'] == 'diagnostic'
    refusal = next(r for r in receipt['work']['current_refusals'] if r['code'] == 'ml')
    assert 'ml.training route check is not installed' in refusal['message']
    # Positive control: the same run on the judgment route does not need that package.
    other = ml_run(tmp_path / 'judgment', monkeypatch)
    assert other.deliver()['label'] == 'accepted'


def test_a_failing_route_check_is_a_refusal_never_a_pass(run, monkeypatch):
    run.complete()
    module = types.ModuleType('ravel.controller.routes.ml.staged')

    def broken(store, plan):
        raise KeyError('fictional missing stage table')
    module.delivery_errors_from_store = broken
    monkeypatch.setitem(sys.modules, module.__name__, module)
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic'
    assert any(r['code'] == 'ml' and 'check failed: KeyError' in r['message']
               for r in receipt['work']['current_refusals'])
    module.delivery_errors_from_store = lambda store, plan: {'code': 'not a list'}
    assert run.deliver()['label'] == 'diagnostic'


def test_route_problem_text_keeps_every_field_including_the_detail():
    problem = {'code': 'manuscript_built_outside_mode', 'step': 's2', 'deliverable': 'd-report', 'kind': 'operate',
               'detail': 'a manuscript is delivered only from a manuscript-build step', 'message': None}
    assert checks._problem_text(problem) == ('manuscript_built_outside_mode: step s2, deliverable d-report, '
                                             'kind operate, a manuscript is delivered only from a '
                                             'manuscript-build step')
    assert checks._problem_text({'code': 'c', 'message': 'm', 'detail': 'd'}) == 'c: m, d'
    assert checks._problem_text('plain text') == 'plain text'


def test_a_gate_error_keeps_its_detail():
    row = _error_row({'code': 'x', 'provider': 'p', 'message': 'refused', 'detail': 'why'})
    assert row == {'code': 'x', 'provider': 'p', 'message': 'refused (why)'}
    error = types.SimpleNamespace(code='y', provider='q', message='held', detail='the reason')
    assert _error_row(error)['message'] == 'held (the reason)'


def test_the_manuscript_route_check_renders_its_detail_through_the_delivery(run, monkeypatch):
    run.complete()
    module = types.ModuleType('ravel.controller.routes.manuscript')
    module.delivery_errors_from_store = lambda store, plan: [
        {'code': 'manuscript_built_outside_mode', 'step': 's2', 'deliverable': 'd-report',
         'detail': 'a manuscript is delivered only from a manuscript-build step'}]
    monkeypatch.setitem(sys.modules, module.__name__, module)
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic'
    refusal = next(r for r in receipt['work']['current_refusals'] if r['code'] == 'manuscript')
    assert refusal['message'].endswith('a manuscript is delivered only from a manuscript-build step')


# ---- route ending records and qualified artifacts ------------------------------------------------------

SOURCES = ('outputs/main.tex', 'outputs/sources.tar')
QUALIFICATION = 'fictional_renderer_unavailable'


def note_run(tmp_path, monkeypatch):
    """A note whose rendering stage ended without its document: source artifacts adopted, the PDF deliverable open."""
    run = Run(tmp_path, monkeypatch)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('s2', list(SOURCES), kind='operate', inputs=['s1:outputs/value.json'])
    run.add_step('s3', ['outputs/note.pdf'], kind='operate', inputs=['s2:outputs/sources.tar'],
                 deliverables=[('d-report', 'outputs/note.pdf')])
    run.pin_plan()
    run.adopt('s1', 'outputs/value.json', VALUE, kind='result')
    run.adopt('s2', 'outputs/main.tex', '\\documentclass{article}\n\\begin{document}\n'
              '\\section{Fictional note}\nThe value is 41.7.\n\\end{document}\n', kind='document',
              inputs=['s1:outputs/value.json'])
    run.adopt('s2', 'outputs/sources.tar', b'fictional source archive bytes', kind='archive',
              inputs=['s1:outputs/value.json'])
    run.store.append('step-outcome', {'schema_version': 1, 'step_id': 's3', 'attempt': 1, 'status': 'failed',
                                      'reason': QUALIFICATION})
    run.authority_record('approve_plan', 'approve')
    run.satisfy_upstream()
    return run


def note_route(monkeypatch, selected):
    module = types.ModuleType('ravel.controller.routes.manuscript.staged')
    calls = []

    def qualified_artifacts(store, plan, run_dir):
        calls.append((plan['sha256'], str(run_dir)))
        latest = {e['record']['artifact']: e['record'] for e in store.scan('custody')}
        return [latest[a] for a in selected]
    module.qualified_artifacts = qualified_artifacts
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return calls


def end_note(run, artifacts=tuple(f's2:{p}' for p in SOURCES)):
    record = run.store.append('manuscript-ending', {'reason': QUALIFICATION, 'artifacts': list(artifacts),
                                                    'qualified': True, 'qualification': QUALIFICATION})
    return record, sink.bounded_end(run.store, f'the rendering stage ended: {QUALIFICATION}')


def test_a_route_selected_qualified_artifact_is_delivered_labelled_and_never_accepted(tmp_path, monkeypatch):
    run = note_run(tmp_path, monkeypatch)
    calls = note_route(monkeypatch, [f's2:{p}' for p in SOURCES])
    record, receipt = end_note(run)
    assert calls == [(run.plan_doc['sha256'], str(run.dir))]
    assert receipt['label'] == 'qualified' and receipt['accepted'] is False and receipt['architecture_complete'] is False
    label = f'QUALIFIED ARTIFACT: {QUALIFICATION}'
    assert label in receipt['labels'] and sink.QUALIFIED in receipt['labels']
    files = {f['artifact']: f for f in receipt['delivery']['artifacts']}
    assert set(files) == {'s1:outputs/value.json', 's2:outputs/main.tex', 's2:outputs/sources.tar'}
    assert files['s2:outputs/main.tex']['qualified'] is True and files['s2:outputs/main.tex']['route'] == 'manuscript'
    assert 'qualified' not in files['s1:outputs/value.json']
    tex = run.delivered('artifacts/s2/outputs/main.tex').read_text()
    assert tex.startswith('% RAVEL SINK NOTICE') and label in tex.split('END RAVEL SINK NOTICE')[0]
    assert run.delivered('artifacts/s2/outputs/sources.tar').read_bytes() == b'fictional source archive bytes'
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert {a['artifact']: a['status'] for a in ending['qualified_artifacts']} == {
        's2:outputs/main.tex': 'accepted', 's2:outputs/sources.tar': 'accepted'}
    assert all(a['ending_record'] == record and a['qualification'] == QUALIFICATION
               for a in ending['qualified_artifacts'])
    assert ending['scientific_claims_adopted'] == [] and ending['parent_task_accepted'] is False
    assert {o['id']: o['state'] for o in ending['obligations']}['d-report'] == 'blocked'
    report = run.delivered('DELIVERY.md').read_text()
    assert 'Qualified artifacts' in report and 'artifacts/s2/outputs/main.tex' in report
    inventory = json.loads(run.delivered('INVENTORY.json').read_text())['classification']
    assert not {e['artifact'] for e in inventory['extras']} & {'s2:outputs/main.tex', 's2:outputs/sources.tar'}
    # The saved receipt re-checks the qualified copies too.
    assert sink.receipt(run.store)['verification']['delivery_intact'] is True
    run.delivered('artifacts/s2/outputs/sources.tar').write_bytes(b'changed')
    assert sink.receipt(run.store)['verification']['delivery_intact'] is False


def test_a_selected_artifact_whose_bytes_changed_is_listed_not_delivered(tmp_path, monkeypatch):
    run = note_run(tmp_path, monkeypatch)
    note_route(monkeypatch, [f's2:{p}' for p in SOURCES])
    (run.dir / 'steps/s2/outputs/sources.tar').write_bytes(b'bytes replaced after adoption')
    _, receipt = end_note(run)
    files = {f['artifact'] for f in receipt['delivery']['artifacts']}
    assert 's2:outputs/sources.tar' not in files and 's2:outputs/main.tex' in files
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    refused = next(a for a in ending['qualified_artifacts'] if a['artifact'] == 's2:outputs/sources.tar')
    assert refused['status'] == 'changed' and 'custody digest' in refused['reasons'][0]
    assert receipt['delivery']['qualified_artifacts_refused'] == 1


def test_an_ending_record_the_route_no_longer_selects_delivers_nothing(tmp_path, monkeypatch):
    run = note_run(tmp_path, monkeypatch)
    note_route(monkeypatch, ['s2:outputs/main.tex'])  # the route selects less than its ending recorded
    _, receipt = end_note(run)
    assert {f['artifact'] for f in receipt['delivery']['artifacts']} == {'s1:outputs/value.json'}
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert {a['status'] for a in ending['qualified_artifacts']} == {'unverified'}
    assert all('now selects' in a['reasons'][0] for a in ending['qualified_artifacts'])
    assert not any(label.startswith('QUALIFIED ARTIFACT') for label in receipt['labels'])


def test_without_the_route_selection_no_qualified_artifact_is_delivered(tmp_path, monkeypatch):
    run = note_run(tmp_path, monkeypatch)  # the staged manuscript package is absent in this fixture
    _, receipt = end_note(run)
    assert {f['artifact'] for f in receipt['delivery']['artifacts']} == {'s1:outputs/value.json'}
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert ending['qualified_artifacts'] and all('not installed' in a['reasons'][0] for a in ending['qualified_artifacts'])


def test_an_unqualified_ending_record_selects_nothing(tmp_path, monkeypatch):
    run = note_run(tmp_path, monkeypatch)
    calls = note_route(monkeypatch, [f's2:{p}' for p in SOURCES])
    run.store.append('manuscript-ending', {'reason': 'incomplete', 'artifacts': [], 'qualified': False,
                                           'qualification': 'incomplete'})
    receipt = sink.bounded_end(run.store, 'budget exhausted')
    assert calls == [] and receipt['delivery']['qualified_artifacts'] == 0


def test_a_qualified_artifact_is_never_part_of_an_ordinary_delivery(tmp_path, monkeypatch):
    run = note_run(tmp_path, monkeypatch)
    note_route(monkeypatch, [f's2:{p}' for p in SOURCES])
    run.store.append('manuscript-ending', {'reason': QUALIFICATION, 'artifacts': [f's2:{p}' for p in SOURCES],
                                           'qualified': True, 'qualification': QUALIFICATION})
    receipt = run.deliver()
    assert receipt['label'] != 'accepted'
    assert {f['artifact'] for f in receipt['delivery']['artifacts']} == {'s1:outputs/value.json'}


def test_every_route_ending_kind_is_rendered_once(tmp_path, monkeypatch):
    from test_p07_sink import partial_run
    run = partial_run(tmp_path, monkeypatch)
    ml = {'schema_version': 1, 'kind': 'ml-qualified-ending', 'reason': 'budget', 'stages': [],
          'completed': ['s1'], 'unfinished': ['s2'], 'exposure': 'nothing_claimed', 'accepted_label': False}
    ids = {'ml': run.store.append('ml-stage-ending', ml),
           'manuscript': run.store.append('manuscript-ending', {'reason': 'budget', 'artifacts': [],
                                                                'qualified': False, 'qualification': 'incomplete'}),
           'research': run.store.append('research-ending', {'reason': 'budget', 'synthesis': {'open': 2}}),
           'study': run.store.append('study-ending', {'reason': 'budget', 'open_obligations': []})}
    run.store.append('ending-synthesis', {'source': 'ml.training', 'result': ml})  # the same content again
    sink.bounded_end(run.store, 'budget exhausted: fictional tokens')
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    shown = {(s['kind'], s['source']): s for s in ending['syntheses']}
    assert set(shown) == {('ml-stage-ending', 'ml.training'), ('manuscript-ending', 'manuscript'),
                          ('research-ending', 'research'), ('study-ending', 'study')}
    assert shown[('ml-stage-ending', 'ml.training')]['record'] == ids['ml']
    assert shown[('ml-stage-ending', 'ml.training')]['result'] == ml
    report = run.delivered('DELIVERY.md').read_text()
    assert 'Unfinished work recorded by ml.training (ml-stage-ending)' in report
    assert 'Unfinished work recorded by research (research-ending)' in report


# ---- host governance -------------------------------------------------------------------------------------

def test_a_run_the_controller_does_not_own_carries_not_governed_in_every_notice(run, monkeypatch):
    run.complete()
    monkeypatch.setattr(sys.modules['ravel.controller.store'], 'controller_owned', lambda path: None)
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic' and receipt['architecture_predicates']['controller_mode'] is False
    assert sink.NOT_GOVERNED in receipt['labels']
    assert receipt['host']['governance']['label'] == 'NOT GOVERNED'
    assert receipt['host']['governance']['reasons'][0] == 'unrestricted_host'
    notice = run.delivered('artifacts/s2/outputs/report.md').read_text().split('END RAVEL SINK NOTICE')[0]
    assert 'Host governance: NOT GOVERNED (unrestricted_host)' in notice
    report = run.delivered('DELIVERY.md').read_text()
    assert 'NOT GOVERNED: unrestricted_host' in report


def test_host_findings_on_a_controller_run_are_rendered_and_do_not_decide_the_label(run):
    run.complete()
    run.host_findings.append({'code': 'hooks_disabled', 'detail': 'a settings file disables every hook'})
    run.host_events.append({'kind': 'hook_failure', 'hook': 'fictional-hook'})
    receipt = run.deliver()
    assert receipt['label'] == 'accepted' and receipt['architecture_complete'] is True
    assert sink.HOST_FINDINGS in receipt['labels']
    assert receipt['host']['governance']['reasons'] == ['hook_failure', 'hooks_disabled']
    notice = run.delivered('artifacts/s2/outputs/report.md').read_text().split('END RAVEL SINK NOTICE')[0]
    assert 'Host governance: controller-owned run; HOST INTEGRITY FINDINGS: hook_failure; hooks_disabled' in notice
    assert 'HOST INTEGRITY FINDINGS: hook_failure; hooks_disabled' in run.delivered('DELIVERY.md').read_text()


def test_a_run_directory_another_controller_run_owns_is_not_governed(run, monkeypatch):
    run.complete()
    monkeypatch.setattr(sys.modules['ravel.controller.store'], 'controller_owned', lambda path: 'run-fictional-other')
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic' and sink.NOT_GOVERNED in receipt['labels']
    assert receipt['architecture_predicates']['controller_mode'] is False
    assert receipt['host']['governance']['this_run'] is False
    notice = run.delivered('artifacts/s2/outputs/report.md').read_text().split('END RAVEL SINK NOTICE')[0]
    assert "Host governance: NOT GOVERNED (the run directory belongs to 'run-fictional-other', not to this run)" in notice


def test_unknown_host_governance_is_never_a_pass(run, monkeypatch):
    run.complete()
    from ravel.workflow import host_governance

    def broken(rundir, project=None, environ=None):
        raise OSError('fictional unreadable host ledger')
    monkeypatch.setattr(host_governance, 'governance_label', broken)
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic' and 'HOST GOVERNANCE UNKNOWN' in receipt['labels']
    assert receipt['host']['governance']['available'] is False
    assert 'HOST GOVERNANCE UNKNOWN' in run.delivered('artifacts/s2/outputs/report.md').read_text()


# ---- the authority issuer and terminal identity ----------------------------------------------------------

def test_the_receipt_carries_the_issuer_account_and_never_attests_terminal_identity(run, monkeypatch):
    run.complete()
    receipt = run.deliver()
    security = receipt['authority_security']
    assert {key: security[key] for key in ISSUER_RECEIPT} == ISSUER_RECEIPT  # the issuer's own account, unchanged
    assert security['issuer_available'] is True and security['issuer_error'] is None
    assert receipt['terminal_identity_attested'] is False and security['terminal_identity_attested'] is False
    assert receipt['authority_security']['confinement_probe'] == {'launches': 1, 'confirmed': 1, 'unconfirmed': [],
                                                                   'backends': ['linux']}
    assert receipt['confinement']['launches'][0]['qualification']['confirmed'] is True
    report = run.delivered('DELIVERY.md').read_text()
    assert ISSUER_RECEIPT['same_user_risk'] in report and 'Terminal identity attested: no.' in report
    # An issuer that claimed attestation changes nothing the sink says.
    claimed = dict(ISSUER_RECEIPT, terminal_identity_attested=True)
    monkeypatch.setattr(sys.modules['ravel.controller.authority.issuer'], 'receipt', lambda: dict(claimed))
    again = run.deliver()
    assert again['terminal_identity_attested'] is False and again['authority_security']['terminal_identity_attested'] is False
    assert again['authority_security']['same_user_risk'] == claimed['same_user_risk']


def test_an_absent_issuer_is_reported_absent(run, monkeypatch):
    run.complete()
    monkeypatch.setitem(sys.modules, 'ravel.controller.authority.issuer', None)
    receipt = run.deliver()
    security = receipt['authority_security']
    assert security['issuer_available'] is False and 'not installed' in security['issuer_error']
    assert 'same_user_risk' not in security and 'issuer_authentication' not in security
    assert receipt['terminal_identity_attested'] is False and security['terminal_identity_attested'] is False
    assert 'Authority issuer: not installed' in run.delivered('DELIVERY.md').read_text()


# ---- the engagement envelope -------------------------------------------------------------------------------

def test_a_dispatched_seat_without_its_session_refuses_acceptance_and_renders_the_engagement(run):
    run.complete()
    run.store.append('step-dispatch', {'schema_version': 1, 'step_id': 'final_review', 'seat': 'physics-critic',
                                       'node_id': 'controller:final_review:physics-critic', 'attempt': 1,
                                       'packet_sha256': 'c' * 64, 'packet_tokens': 100})
    receipt = run.deliver()
    assert run.engagement.stages == ['deliver']
    assert receipt['label'] == 'diagnostic' and receipt['architecture_complete'] is False
    assert receipt['architecture_predicates']['engagement_complete'] is False
    assert 'ENGAGEMENT BELOW FLOOR' in receipt['labels']
    assert receipt['engagement']['accepted_allowed'] is False and receipt['engagement']['envelope_status'] == 'below_floor'
    assert any(r['code'] == 'engagement' for r in receipt['work']['current_refusals'])
    assert '## Engagement' in run.delivered('DELIVERY.md').read_text()
    assert 'ENGAGEMENT BELOW FLOOR' in run.delivered('artifacts/s2/outputs/report.md').read_text()


def test_the_engagement_positive_control_and_the_check_of_each_delivery(run):
    run.complete()
    receipt = run.deliver()
    assert receipt['label'] == 'accepted' and receipt['architecture_predicates']['engagement_complete'] is True
    assert receipt['engagement']['tier'] == 'standard' and receipt['engagement']['seat_plan_sha256']
    assert [c['stage'] for c in receipt['engagement']['envelope_checks']] == ['deliver']
    run.deliver()
    assert run.engagement.stages == ['deliver', 'deliver']
    # An observation records no check: it reads the latest one.
    sink.observe_store(run.store)
    assert run.engagement.stages == ['deliver', 'deliver']


def test_a_failing_envelope_check_refuses_even_when_an_earlier_check_allowed_acceptance(run, monkeypatch):
    run.complete()
    assert run.deliver()['label'] == 'accepted'

    def broken(store, stage, broker=None):
        raise ValueError('fictional schema refusal')
    monkeypatch.setattr(sys.modules['ravel.controller.engagement'], 'check_envelope', broken)
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic'
    assert any(r['code'] == 'engagement_check' and 'fictional schema refusal' in r['message']
               for r in receipt['work']['current_refusals'])


def test_an_absent_engagement_policy_is_never_a_pass(run, monkeypatch):
    run.complete()
    monkeypatch.setitem(sys.modules, 'ravel.controller.engagement', None)
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic' and 'ENGAGEMENT UNKNOWN' in receipt['labels']
    assert receipt['engagement']['available'] is False
    assert receipt['architecture_predicates']['engagement_complete'] is False


def test_the_bounded_ending_checks_the_envelope_and_keeps_its_labels(tmp_path, monkeypatch):
    from test_p07_sink import partial_run
    run = partial_run(tmp_path, monkeypatch)
    receipt = sink.bounded_end(run.store, 'budget exhausted: fictional tokens')
    assert run.engagement.stages == ['deliver'] and receipt['label'] == 'qualified'
    assert receipt['engagement']['envelope_checks'][-1]['stage'] == 'deliver'
