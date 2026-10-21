"""Staged route delivery preserves environmental defects and qualified source custody."""
from copy import deepcopy
import importlib
import json
import sys

import pytest

from ravel.controller import sink
from test_p06_support import operator_home  # noqa: F401
from test_p07_receipts import authenticated_run, current_authority, observed_ack
from p07_support import Run, VALUE
import p17_support as support

ML = importlib.import_module('ravel.controller.routes.ml.staged')
MANUSCRIPT = importlib.import_module('ravel.controller.routes.manuscript')
STAGED = importlib.import_module('ravel.controller.routes.manuscript.staged')


def routes(monkeypatch):
    for module in (ML, MANUSCRIPT, STAGED):
        monkeypatch.setitem(sys.modules, module.__name__, module)


def training_run(tmp_path, monkeypatch, *, runtime=False):
    run = authenticated_run(tmp_path, monkeypatch)
    routes(monkeypatch)
    run.steps[0]['operation'] = 'ml-stage-train'
    run.steps[0]['parameters']['ml_stage'] = 'train'
    run.pin_plan()
    if runtime:
        value = {**deepcopy(VALUE), 'runtime': {'python': '3.10'}, 'exported_runtime': {'python': '3.12'},
                 'findings': [{'id': 'input-gap', 'kind': 'defect', 'status': 'unresolved'}]}
        run.adopt('s1', 'outputs/value.json', value, kind='result')
    run.review_round('plan', {'plan-critic': (True, 'accept')})
    run.review_round('final', {'physics-critic': (True, 'accept'), 'skeptical-verifier': (True, 'accept'),
                               'physics-decider': (True, 'accept')})
    current_authority(run)
    observed_ack(run)
    return run


@pytest.mark.parametrize('status', ['held', 'refused', 'qualified'])
def test_staged_outputs_retain_missing_prerequisite_and_environment_violation(tmp_path, monkeypatch,
                                                                           operator_home, status):
    run = training_run(tmp_path, monkeypatch, runtime=True)
    held = {'step_id': 's1', 'stage': 'train', 'status': status, 'accepted': False,
            'plan_sha256': run.plan_doc['sha256'], 'reason': 'input prerequisite is unresolved',
            'codes': ['input_prerequisite_missing'], 'problems': [
                {'code': 'input_prerequisite_missing', 'message': 'input prerequisite is unresolved'}]}
    run.store.append('ml-stage', held)
    receipt = run.deliver()
    assert receipt['accepted'] is False and receipt['architecture_complete'] is False
    errors = receipt['work']['current_refusals']
    typed = next(e for e in errors if e['code'] == 'ml')['typed']
    assert typed == {'code': 'ml_stage_unreceipted', 'step': 's1', 'stage': 'train'}
    assert any(e['row'] == 'E27' and e['message'] == 'unsupported historical runtime substitution: python'
               for e in errors)
    assert {i['status'] for i in run.ledger.instances.values() if i['id'] == 'E27'} == {'violated'}
    assert any('input-gap' in e['message'] for e in errors)
    assert run.store.scan('ml-stage')[-1]['record'] == held
    assert any(v['id'] == 'E27' and v['reason'] == 'unsupported historical runtime substitution: python'
               for v in receipt['ledger']['violations'])
    synthesis = ML.ending('input prerequisite is unresolved', {
        'store': run.store, 'run_dir': run.dir, 'plan': run.plan_doc})
    assert synthesis['stages'][0]['status'] == status
    assert synthesis['stages'][0]['problems'] == held['problems']
    bounded = sink.bounded_end(run.store, 'input prerequisite is unresolved')
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert bounded['qualified'] and not bounded['accepted']
    assert any(e['row'] == 'E27' for e in bounded['work']['current_refusals'])
    assert 'input-gap' in json.dumps(ending['unresolved_findings'])
    defect = next(item for item in ending['unresolved_findings'] if item['id'] == 'input-gap')
    assert defect['artifact'] == 's1:outputs/value.json'
    assert defect['item'] == {'id': 'input-gap', 'kind': 'defect', 'status': 'unresolved'}
    assert any(s['kind'] == 'ml-stage-ending' and s['result']['stages'][0]['status'] == status
               for s in ending['syntheses'])
    assert next(s for s in ending['syntheses'] if s['kind'] == 'ml-stage-ending')['result']['stages'][0][
        'problems'] == held['problems']


def test_complete_current_staged_chain_is_accepted(tmp_path, monkeypatch, operator_home):
    run = training_run(tmp_path, monkeypatch)
    assert ML.delivery_errors_from_store(run.store, run.plan_doc) == [
        {'code': 'ml_stage_unreceipted', 'step': 's1', 'stage': 'train'}]
    run.store.append('ml-stage', {'step_id': 's1', 'stage': 'train', 'status': 'completed', 'accepted': True,
                                  'plan_sha256': run.plan_doc['sha256']})
    assert ML.delivery_errors_from_store(run.store, run.plan_doc) == []
    receipt = run.deliver()
    assert receipt['label'] == 'accepted' and receipt['architecture_complete'] is True


def test_real_source_only_ending_preserves_labels_and_refuses_document_acceptance(tmp_path, monkeypatch):
    from ravel.controller.routes.manuscript import note
    run = Run(tmp_path, monkeypatch)
    routes(monkeypatch)
    plan = support.plan('manuscript', {'python': sys.executable, 'tex': '', 'result_path': '/unused/result.json',
                                      'result_sha256': 'a' * 64}, deliverables=(('document', 'document'),))
    store, run_dir = run.store, run.dir
    store.append('plan', {'plan_sha256': plan['sha256'], 'source': 'compile', 'revision': 0, 'route': 'manuscript',
                          'blob': store.put_blob(json.dumps(plan, sort_keys=True).encode())})
    run.plan_doc = plan
    def completed(step_id):
        store.append('step-outcome', {'step_id': step_id, 'attempt': 1, 'status': 'completed'})
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
    assembly = STAGED.assemble(STAGED.Binding(store, run_dir, plan, 'm02-build', attempt))
    assert assembly['status'] == 'completed'
    support.adopt(store, run_dir, 'm02-build', attempt, ['outputs/assembly.json'])
    completed('m02-build')
    rendered = tmp_path / 'pdf'
    assert note.run_stage('pdf', {'sources': source / 'outputs/sources.tar', 'bundle': source / 'outputs/bundle.json'},
                          {'tex': ''}, rendered)['status'] == 'qualified'
    support.adopt(store, run_dir, 'm03-pdf', rendered, [p for p, _ in note.OUTPUTS['pdf']])
    context = {'store': store, 'run_dir': run_dir, 'plan': plan}
    step = next(s for s in plan['steps'] if s['id'] == 'm03-pdf')
    assert STAGED.step(step, {'status': 'completed'}, context) == ['manuscript_tex_unavailable']
    ending = STAGED.ending('manuscript_tex_unavailable', context)
    assert ending['qualified'] and ending['artifacts']
    receipt = sink.bounded_end(store, 'manuscript_tex_unavailable')
    assert receipt['label'] == 'qualified' and not receipt['accepted'] and not receipt['architecture_complete']
    chosen = {f['artifact']: f for f in receipt['delivery']['artifacts'] if f.get('qualified')}
    assert set(chosen) == set(ending['artifacts'])
    assert {f['qualification'] for f in chosen.values()} == {'manuscript_tex_unavailable'}
    assert 'QUALIFIED ARTIFACT: manuscript_tex_unavailable' in receipt['labels']
    tex = run.delivered(chosen['m02-sources:outputs/sources/main.tex']['path']).read_text()
    assert 'QUALIFIED ARTIFACT: manuscript_tex_unavailable' in tex.split('END RAVEL SINK NOTICE')[0]
    saved = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert {a['status'] for a in saved['qualified_artifacts']} == {'accepted'}
    assert any(s['kind'] == 'manuscript-ending' and s['result']['qualified'] for s in saved['syntheses'])
    delivered = sink.deliver(store, plan)
    assert not delivered['accepted']
    assert any(e['code'] == 'manuscript' for e in delivered['work']['current_refusals'])
