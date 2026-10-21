"""The sink's hooks against the installed peers (skipped until they are installed).

The fakes in ``p07_support`` keep the peers' published rules; this file runs the same hooks
through the real packages: the staged ML and manuscript route checks and the manuscript route's
qualified-artifact selection, host governance's label over the run's ownership and the host's real
findings, the authority issuer's own account, and the engagement policy's envelope check and
receipt section. Each peer is the installed module; the rest of the run is the fictional fixture.
"""
from __future__ import annotations

from io import BytesIO
import json
import sys

import pytest
from pypdf import PdfWriter

ml_staged = pytest.importorskip('ravel.controller.routes.ml.staged')
manuscript = pytest.importorskip('ravel.controller.routes.manuscript')
note_staged = pytest.importorskip('ravel.controller.routes.manuscript.staged')
engagement = pytest.importorskip('ravel.controller.engagement')
issuer = pytest.importorskip('ravel.controller.authority.issuer')
from ravel.workflow import host_governance  # noqa: E402
if not hasattr(host_governance, 'governance_label') or not hasattr(ml_staged, 'delivery_errors_from_store'):
    pytest.skip('host governance and the staged routes are not the integrated packages', allow_module_level=True)

from ravel.controller import sink  # noqa: E402
from p07_support import REPORT, VALUE, Run, run  # noqa: E402,F401  (run fixture)

REAL_LABEL = host_governance.governance_label


def install(monkeypatch, *modules):
    for module in modules:
        monkeypatch.setitem(sys.modules, module.__name__, module)


def isolated_host(tmp_path, monkeypatch, run_):
    """Real host governance over an empty project, user settings and host ledger under the test's own paths."""
    project = tmp_path / 'project'
    (project / '.claude').mkdir(parents=True)
    (tmp_path / 'user-settings').mkdir()
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(project))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'user-settings'))
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(host_governance, 'governance_label', REAL_LABEL)
    return project


def test_the_real_staged_ml_check_refuses_an_unreceipted_training_stage(run, monkeypatch):
    install(monkeypatch, ml_staged)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])['operation'] = \
        'ml-stage-train'
    run.add_step('s2', ['outputs/report.md'], kind='synthesize', inputs=['s1:outputs/value.json'],
                 deliverables=[('d-report', 'outputs/report.md')])
    run.pin_plan()
    run.adopt('s1', 'outputs/value.json', VALUE, kind='result')
    run.adopt('s2', 'outputs/report.md', REPORT, kind='document', producer='worker', inputs=['s1:outputs/value.json'])
    run.authority_record('approve_plan', 'approve')
    run.authority_record('final', 'accept', authorizes=False)
    run.review_round('plan', {'plan-critic': (True, 'accept')})
    run.review_round('final', {'physics-critic': (True, 'accept'), 'skeptical-verifier': (True, 'accept'),
                               'physics-decider': (True, 'accept')})
    run.satisfy_upstream()
    receipt = run.deliver()
    refusal = next(r for r in receipt['work']['current_refusals'] if r['code'] == 'ml')
    assert refusal['typed'] == {'code': 'ml_stage_unreceipted', 'step': 's1', 'stage': 'train'}
    assert refusal['message'] == 'ml_stage_unreceipted: step s1, stage train' and receipt['label'] == 'diagnostic'
    # Positive control: the stage's accepted, completed record bound to this plan receipts it.
    run.store.append('ml-stage', {'step_id': 's1', 'stage': 'train', 'status': 'completed', 'accepted': True,
                                  'plan_sha256': run.plan_doc['sha256']})
    again = run.deliver()
    assert not [r for r in again['work']['current_refusals'] if r['code'] == 'ml']
    assert again['label'] == 'accepted'


def test_the_real_manuscript_check_refuses_a_document_built_outside_the_manuscript_mode(run, monkeypatch):
    install(monkeypatch, ml_staged, manuscript)
    run.complete()
    # The same run with a PDF document deliverable a synthesis step wrote.
    plan = run.plan_doc
    step = next(s for s in run.steps if s['id'] == 's2')
    step['outputs'] = [{'path': 'outputs/report.pdf', 'kind': 'document', 'required': True}]
    run.deliverables[:] = [d for d in run.deliverables if d['id'] != 'd-report'] + [
        {'id': 'd-report', 'status': 'mapped', 'step': 's2', 'output': 'outputs/report.pdf', 'claim_kind': None,
         'artifact_kind': 'document'}]
    plan = run.pin_plan()
    pdf = PdfWriter()
    pdf.add_blank_page(width=300, height=200)
    document = BytesIO()
    pdf.write(document)
    run.adopt('s2', 'outputs/report.pdf', document.getvalue(), kind='document', producer='worker',
              inputs=['s1:outputs/value.json'], attempt=2)
    receipt = run.deliver()
    refusal = next(r for r in receipt['work']['current_refusals'] if r['code'] == 'manuscript')
    assert refusal['typed']['code'] == 'manuscript_built_outside_mode' and refusal['typed']['step'] == 's2'
    assert refusal['message'].endswith('a manuscript is delivered only from a manuscript-build step')
    assert receipt['label'] == 'diagnostic' and receipt['plan']['sha256'] == plan['sha256']


def test_the_real_note_route_selection_overrules_a_stale_ending_record(run, monkeypatch):
    install(monkeypatch, ml_staged, manuscript, note_staged)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('s2', ['outputs/main.tex'], inputs=['s1:outputs/value.json'],
                 deliverables=[('d-report', 'outputs/main.tex')])
    run.pin_plan()
    run.adopt('s1', 'outputs/value.json', VALUE, kind='result')
    run.adopt('s2', 'outputs/main.tex', '\\documentclass{article}\n\\begin{document}\n'
              '\\section{Fictional}\n\\end{document}\n', kind='document', inputs=['s1:outputs/value.json'],
              outcome='failed')
    run.adopt('s1', 'outputs/extra.json', {'fictional': True})  # an adopted artifact no deliverable names
    run.store.append('manuscript-ending', {'reason': 'fictional', 'artifacts': ['s1:outputs/extra.json'],
                                           'qualified': True, 'qualification': 'manuscript_tex_unavailable'})
    receipt = sink.bounded_end(run.store, 'the rendering stage ended')
    # The note route records no qualified rendering stage, so it selects nothing: the stale record delivers nothing.
    assert 's1:outputs/extra.json' not in {f['artifact'] for f in receipt['delivery']['artifacts']}
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert [a['status'] for a in ending['qualified_artifacts']] == ['unverified']
    assert 'now selects []' in ending['qualified_artifacts'][0]['reasons'][0]


def test_real_host_governance_labels_a_run_the_controller_does_not_own(run, monkeypatch, tmp_path):
    isolated_host(tmp_path, monkeypatch, run)
    run.complete()
    owned = run.deliver()
    assert owned['host']['governance']['label'] is None and owned['host']['governance']['controller_run'] == run.store.run_id
    assert owned['host']['governance']['reasons'] == [] and owned['label'] == 'accepted'
    monkeypatch.setattr(sys.modules['ravel.controller.store'], 'controller_owned', lambda path: None)
    receipt = run.deliver()
    assert receipt['host']['governance']['label'] == 'NOT GOVERNED' and receipt['label'] == 'diagnostic'
    assert receipt['host']['governance']['reasons'][0] == 'unrestricted_host'
    notice = run.delivered('artifacts/s2/outputs/report.md').read_text().split('END RAVEL SINK NOTICE')[0]
    assert 'Host governance: NOT GOVERNED (unrestricted_host' in notice


def test_real_host_findings_on_a_controller_run_reach_every_notice(run, monkeypatch, tmp_path):
    project = isolated_host(tmp_path, monkeypatch, run)
    (project / '.claude' / 'settings.json').write_text(json.dumps({'disableAllHooks': True}))
    run.complete()
    receipt = run.deliver()
    assert 'hooks_disabled' in receipt['host']['governance']['reasons'] and receipt['label'] == 'accepted'
    assert sink.HOST_FINDINGS in receipt['labels']
    notice = run.delivered('artifacts/s2/outputs/report.md').read_text().split('END RAVEL SINK NOTICE')[0]
    assert 'HOST INTEGRITY FINDINGS' in notice and 'hooks_disabled' in notice


def test_the_real_issuer_account_is_carried_and_terminal_identity_is_not_attested(run, monkeypatch):
    install(monkeypatch, issuer)
    run.complete()
    receipt = run.deliver()
    own = json.loads(json.dumps(issuer.receipt()))
    assert {key: receipt['authority_security'][key] for key in own} == dict(own, terminal_identity_attested=False)
    assert receipt['terminal_identity_attested'] is False
    assert issuer.receipt()['same_user_risk'] in run.delivered('DELIVERY.md').read_text()


def test_the_real_engagement_policy_records_its_check_and_allows_nothing_without_a_decision(run, monkeypatch):
    install(monkeypatch, engagement)
    run.complete()
    run.store.entries[:] = [e for e in run.store.entries if e['kind'] != 'engagement-decision']
    receipt = run.deliver()
    assert not [r for r in receipt['work']['current_refusals'] if r['code'] == 'engagement_check'], \
        receipt['work']['current_refusals']
    checks = [e['record'] for e in run.store.scan('envelope-check')]
    assert [c['stage'] for c in checks] == ['deliver'] and checks[-1]['accepted_allowed'] is False
    assert receipt['engagement']['available'] is True and receipt['engagement']['accepted_allowed'] is False
    assert receipt['engagement']['envelope_status'] == checks[-1]['status']
    assert 'USAGE UNKNOWN' in receipt['labels'] and receipt['label'] == 'diagnostic'
    assert receipt['architecture_predicates']['engagement_complete'] is False


def test_the_real_note_route_qualified_sources_through_the_sink(run, monkeypatch, tmp_path):
    """The note route's own source-only ending (no renderer on the host), replayed on a sink fixture run:
    the bounded ending delivers the reviewed, assembled sources labelled, and an ordinary delivery refuses."""
    install(monkeypatch, ml_staged, manuscript, note_staged)  # the fixture marks the route packages absent
    support = pytest.importorskip('p17_support')
    from ravel.controller.routes.manuscript import note
    from ravel.workflow import graph_substrate as gs
    from ravel.workflow.graphs import manuscript as build_graph
    store, run_dir = run.store, run.dir
    plan = support.plan('manuscript', {'python': sys.executable, 'tex': '', 'result_path': '/unused/result.json',
                                       'result_sha256': 'a' * 64}, deliverables=(('document', 'document'),))
    store.append('plan', {'plan_sha256': plan['sha256'], 'source': 'compile', 'revision': 0, 'route': 'manuscript',
                          'blob': store.put_blob(json.dumps(plan, sort_keys=True).encode())})
    run.plan_doc = plan

    def completed(step_id):
        store.append('step-outcome', {'schema_version': 1, 'step_id': step_id, 'attempt': 1, 'status': 'completed'})

    author = tmp_path / 'author'
    (author / 'outputs').mkdir(parents=True)
    result = tmp_path / 'result.json'
    result.write_text('{"metric":0.75}')
    (author / 'outputs/claim_map.json').write_text(json.dumps({
        'kind': 'manuscript-claim-map', 'schema_version': 1, 'title': 'Fictional note',
        'results': {'result': {'sha256': support.sha(result)}},
        'claims': [{'id': 'c1', 'text': 'The measured value is 0.75.', 'result': 'result',
                    'quantity': {'pointer': '/metric', 'value': .75}}]}))
    (author / 'outputs/note.md').write_text('# Fictional note\n\n[[claim:c1]]\n')
    support.adopt(store, run_dir, 'm01-author', author, ['outputs/claim_map.json', 'outputs/note.md'])
    completed('m01-author')
    source = tmp_path / 'source'
    assert note.run_stage('sources', {'claim_map': run_dir / 'steps/m01-author/outputs/claim_map.json',
                                      'note': run_dir / 'steps/m01-author/outputs/note.md', 'result.result': result},
                          {}, source)['status'] == 'completed'
    support.adopt(store, run_dir, 'm02-sources', source, [p for p, _ in note.OUTPUTS['sources']])
    completed('m02-sources')
    attempt = run_dir / 'steps/m02-build/attempts/1/outputs'
    ctx = gs.BuildContext(run_dir, 'manuscript.build', 1, {'request_id': 'fictional_note'})
    with note_staged.services(note_staged.Binding(store, run_dir, plan, 'm02-build', attempt)):
        compiled = gs.finish(build_graph.manuscript(ctx), ctx.graph_id)
        built = compiled.invoke({'meta': {'graph_id': ctx.graph_id, 'version': ctx.version, 'instance': ctx.instance,
                                          'scope_root': str(ctx.scope_root), 'path': None}})
    assert built['results']['note_assembly']['status'] == 'completed'
    support.adopt(store, run_dir, 'm02-build', attempt, ['outputs/assembly.json'])
    completed('m02-build')
    rendered = tmp_path / 'pdf'
    assert note.run_stage('pdf', {'sources': source / 'outputs/sources.tar', 'bundle': source / 'outputs/bundle.json'},
                          {'tex': ''}, rendered)['status'] == 'qualified'
    support.adopt(store, run_dir, 'm03-pdf', rendered, [p for p, _ in note.OUTPUTS['pdf']])
    context = {'store': store, 'run_dir': run_dir, 'plan': plan}
    step = next(s for s in plan['steps'] if s['id'] == 'm03-pdf')
    assert note_staged.step(step, {'status': 'completed'}, context) == ['manuscript_tex_unavailable']
    ending = note_staged.ending('manuscript_tex_unavailable', context)  # the controller's bounded_end calls this first
    assert ending['qualified'] and ending['artifacts']

    receipt = sink.bounded_end(store, 'manuscript_tex_unavailable')
    assert receipt['label'] == 'qualified' and receipt['accepted'] is False and receipt['architecture_complete'] is False
    chosen = {f['artifact']: f for f in receipt['delivery']['artifacts'] if f.get('qualified')}
    assert set(chosen) == set(ending['artifacts']) and all(a.startswith('m02-sources:') for a in chosen)
    assert {f['qualification'] for f in chosen.values()} == {'manuscript_tex_unavailable'}
    assert 'QUALIFIED ARTIFACT: manuscript_tex_unavailable' in receipt['labels']
    tex = run.delivered(chosen['m02-sources:outputs/sources/main.tex']['path']).read_text()
    assert 'QUALIFIED ARTIFACT: manuscript_tex_unavailable' in tex.split('END RAVEL SINK NOTICE')[0]
    saved = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert {a['status'] for a in saved['qualified_artifacts']} == {'accepted'}
    assert any(s['kind'] == 'manuscript-ending' and s['result']['qualified'] for s in saved['syntheses'])

    # Qualified sources never become an ordinary accepted delivery of the document.
    delivered = sink.deliver(store, plan)
    assert delivered['label'] == 'diagnostic' and not any(f.get('qualified') for f in delivered['delivery']['artifacts'])
    assert any(r['code'] == 'manuscript' for r in delivered['work']['current_refusals'])
