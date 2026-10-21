"""Inert interface canaries for the governed ML and note graph branches.

The P04 boundary and sole sink are explicitly inert doubles here. These cases establish the
consumer's signature, ordering, custody and qualification behavior; they do not qualify the actual
controller, sandbox, batch transport, reviewer transport or release sink.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import types

import pytest

import p17_support as support
from ravel.controller.routes.ml import staged as ml_route
from ravel.controller.routes.manuscript import note, staged as note_route
from ravel.workflow import graph_substrate as gs, ml_executor, ml_stages
from ravel.workflow.graphs import manuscript, ml_study


def app(module, ctx):
    builder = module.build(ctx) if module is ml_study else module.manuscript(ctx)
    compiled = gs.finish(builder, ctx.graph_id)
    print(ctx.graph_id, compiled.structure_sha256)
    assert gs.lint_graph(compiled) == []
    return compiled


def meta(ctx):
    return {'meta': {'graph_id': ctx.graph_id, 'version': ctx.version, 'instance': ctx.instance,
                     'scope_root': str(ctx.scope_root), 'path': None}}


def fake_step(monkeypatch, run_dir, store, calls, *, crash=False):
    # This interface control supplies only the exact controller-issued withheld-read decision.
    from types import SimpleNamespace
    from ravel.controller.authority import retained
    granted = {}
    def current(store, kind, pins):
        return granted.get(json.dumps(pins, sort_keys=True)) if kind == 'r3_action' else None
    def request(store, kind, subject, bounds):
        assert kind == 'r3_action' and subject['gate'] == 'unblind'
        pins = subject['view']['pins']
        assert pins['operation'] == 'ml-stage-evaluate' and pins['ml_training_sha256']
        assert pins['ml_spec_sha256'] and pins['ml_test_sha256'] and pins['plan_sha256']
        record = {'id': 'exact-withheld-read', 'subject': {'gate': 'unblind', 'pins': pins}}
        granted[json.dumps(pins, sort_keys=True)] = record
        return record
    def verify(store, record_id, *, kind, subject):
        record = current(store, kind, subject)
        assert record is not None and record['id'] == record_id
        return record
    service = SimpleNamespace(current=current, request=request, verify=verify)
    monkeypatch.setattr(ml_route, 'authority_service', lambda: service)
    monkeypatch.setattr(retained, 'capture', lambda *a, **k: None)
    def run(actual_store, step, context):
        assert actual_store is store
        calls.append(step['id'])
        result, work = support.launch(run_dir, step)
        assert crash or result.returncode == 0, result.stderr[-1500:]
        rows = support.adopt(store, run_dir, step['id'], work, [r['path'] for r in step['outputs']])
        outcome = {'step_id': step['id'], 'status': 'completed' if result.returncode == 0 else 'failed',
                   'outputs': rows}
        store.append('step-outcome', outcome)
        return outcome
    module = types.ModuleType('ravel.controller.step')
    module.run = run
    monkeypatch.setitem(sys.modules, module.__name__, module)


class InertSink:
    def __init__(self):
        self.calls = []

    def deliver(self, store, plan):
        self.calls.append('deliver')
        return {'id': store.append('delivery', {'plan_sha256': plan['sha256']}), 'qualified': False}

    def bounded_end(self, store, reason):
        self.calls.append('bounded_end')
        return {'id': store.append('delivery', {'reason': reason}), 'qualified': True}


def ml_binding(tmp_path, document=None, leak=False, raw=None):
    run_dir, store = tmp_path / 'run', support.Store(tmp_path / 'store')
    data = tmp_path / 'table.npz'
    support.table(data, leak=leak)
    plan = support.plan('ml.training', {'python': sys.executable, 'dataset_path': str(data),
                                       'dataset_sha256': support.sha(data)},
                        deliverables=(('table', 'method_performance'),))
    work = tmp_path / 'author'
    (work / 'outputs').mkdir(parents=True)
    (work / ml_route.SPEC_OUTPUT).write_text(raw if raw is not None else json.dumps(document or support.spec()))
    support.adopt(store, run_dir, 't01-spec', work, [ml_route.SPEC_OUTPUT])
    store.append('step-outcome', {'step_id': 't01-spec', 'status': 'completed'})
    return ml_executor.Binding(store, run_dir, plan, {'plan_sha256': plan['sha256'], 'run_id': store.run_id})


def test_P17_training_graph_runs_every_planned_stage_through_step_interface(tmp_path, monkeypatch):
    binding = ml_binding(tmp_path)
    calls = []
    fake_step(monkeypatch, binding.run_dir, binding.store, calls)
    ctx = gs.BuildContext(binding.run_dir, 'ml.study', 2, {'study': 'fixture_study'})
    with ml_executor.bound(binding):
        result = app(ml_study, ctx).invoke(meta(ctx), {'recursion_limit': 120})
    assert 'ml_status' in result, result
    assert result['ml_status'] == 'completed', result.get('ml_reason')
    assert calls == [s['id'] for s in binding.plan['steps'] if ml_route.stage_of(s)]
    receipts = ml_route.records(binding.store, ml_route.STAGE_RECORD)
    assert len(receipts) == 7 and all(r['accepted'] for r in receipts)
    assert ml_route.gate('checkin3->deliver', {'store': binding.store, 'run_dir': binding.run_dir,
                                             'plan': binding.plan}) == []
    sink = InertSink()
    assert sink.deliver(binding.store, binding.plan)['qualified'] is False
    assert sink.calls == ['deliver']
    assert 'NOT GOVERNED' not in json.dumps(result)


def test_P17_leakage_stops_the_training_graph_before_a_training_launch(tmp_path, monkeypatch):
    binding = ml_binding(tmp_path, leak=True)
    calls = []
    fake_step(monkeypatch, binding.run_dir, binding.store, calls)
    ctx = gs.BuildContext(binding.run_dir, 'ml.study', 2, {'study': 'fixture_study'})
    with ml_executor.bound(binding):
        result = app(ml_study, ctx).invoke(meta(ctx), {'recursion_limit': 120})
    assert 'ml_status' in result, result
    assert result['ml_status'] == 'held' and result['ml_reason'].startswith('ml_label_leakage')
    from ravel.workflow import graph_nodes
    assert graph_nodes._outcome(result) == 'held'
    assert calls == ['t02-admit', 't03-features']
    assert 'ending' in result['results']


def test_P17_a_crashing_stage_ends_the_child_graph_failed_not_held(tmp_path, monkeypatch):
    """An exception inside a stage is a typed failure of the graph, never a hold or a refusal."""
    from ravel.workflow import graph_nodes
    binding = ml_binding(tmp_path, raw='{not json')
    calls = []
    fake_step(monkeypatch, binding.run_dir, binding.store, calls, crash=True)
    ctx = gs.BuildContext(binding.run_dir, 'ml.study', 2, {'study': 'fixture_study'})
    with ml_executor.bound(binding):
        result = app(ml_study, ctx).invoke(meta(ctx), {'recursion_limit': 120})
    assert calls == ['t02-admit']
    assert result['ml_status'] == 'failed', result.get('ml_reason')
    assert result['status']['terminal'] == 'failed' and graph_nodes._outcome(result) == 'failed'
    assert result['results']['ending']['unfinished']


def test_P17_missing_extended_study_prerequisite_is_honest():
    assert ml_executor.current() is None
    assert ml_executor.prerequisites(profile='study')[0]['id'] == 'staged_ml_executor'
    ctx = gs.BuildContext(Path('/unused'), 'ml.study', 2, {'study': 'fixture_study'})
    with pytest.raises(Exception, match=ml_executor.PREREQUISITE_HOLD):
        ml_study.executor(ctx)


def test_P17_manuscript_graph_assembles_sources_and_uses_only_the_sink_for_qualified_delivery(tmp_path):
    from ravel.controller.routes import manuscript as contract
    store, run_dir = support.Store(tmp_path / 'store'), tmp_path / 'run'
    plan = support.plan('manuscript', {'python': sys.executable, 'tex': '', 'result_path': '/unused/result.json',
                                      'result_sha256': 'a' * 64}, deliverables=(('document', 'document'),))
    author = tmp_path / 'author'
    (author / 'outputs').mkdir(parents=True)
    result_path = tmp_path / 'result.json'
    result_path.write_text('{"metric":0.75}')
    claims = {'kind': 'manuscript-claim-map', 'schema_version': 1, 'title': 'Fixture note',
              'results': {'result': {'sha256': support.sha(result_path)}},
              'claims': [{'id': 'c1', 'text': 'The measured value is 0.75.', 'result': 'result',
                          'quantity': {'pointer': '/metric', 'value': .75}}]}
    (author / 'outputs/claim_map.json').write_text(json.dumps(claims))
    (author / 'outputs/note.md').write_text('# Fixture note\n\n[[claim:c1]]\n')
    support.adopt(store, run_dir, 'm01-author', author, ['outputs/claim_map.json', 'outputs/note.md'])
    store.append('step-outcome', {'step_id': 'm01-author', 'status': 'completed'})
    inputs = {'claim_map': run_dir / 'steps/m01-author/outputs/claim_map.json',
              'note': run_dir / 'steps/m01-author/outputs/note.md', 'result.result': result_path}
    source = tmp_path / 'source'
    assert note.run_stage('sources', inputs, {}, source)['status'] == 'completed'
    support.adopt(store, run_dir, 'm02-sources', source, [p for p, _ in note.OUTPUTS['sources']])
    store.append('step-outcome', {'step_id': 'm02-sources', 'status': 'completed'})
    ctx = gs.BuildContext(run_dir, 'manuscript.build', 1, {'request_id': 'fixture_note'})
    with note_route.services(note_route.Binding(store, run_dir, plan, 'm02-build', run_dir / 'steps/m02-build/attempts/1/outputs')):
        built = app(manuscript, ctx).invoke(meta(ctx))
    assert built['results']['note_assembly']['status'] == 'completed'
    assert built['procedure']['plan_sha256'] == plan['sha256']
    assert built['procedure']['assembly_sha256'] == support.sha(
        run_dir / 'steps/m02-build/attempts/1/outputs/outputs/assembly.json')
    assert store.scan('manuscript-procedure')
    support.adopt(store, run_dir, 'm02-build', run_dir / 'steps/m02-build/attempts/1/outputs', ['outputs/assembly.json'])
    store.append('step-outcome', {'step_id': 'm02-build', 'status': 'completed'})
    pdf = tmp_path / 'pdf'
    inputs = {'sources': source / 'outputs/sources.tar', 'bundle': source / 'outputs/bundle.json'}
    receipt = note.run_stage('pdf', inputs, {'tex': ''}, pdf)
    assert receipt['status'] == 'qualified'
    support.adopt(store, run_dir, 'm03-pdf', pdf, [p for p, _ in note.OUTPUTS['pdf']])
    context = {'store': store, 'run_dir': run_dir, 'plan': plan}
    step = next(s for s in plan['steps'] if s['id'] == 'm03-pdf')
    assert note_route.step(step, {'status': 'completed'}, context) == ['manuscript_tex_unavailable']
    # Qualified sources cannot become an ordinary accepted PDF delivery.
    assert contract.delivery_errors_from_store(store, plan)
    ending = note_route.ending('manuscript_tex_unavailable', context)
    assert ending['qualified'] and ending['artifacts']
    sink = InertSink()
    assert sink.bounded_end(store, ending['qualification'])['qualified'] is True
    assert sink.calls == ['bounded_end']
    assert 'NOT GOVERNED' not in json.dumps(built)
    from ravel.controller.sink import procedure
    from ravel.workflow import procedure_export
    prepared = procedure.prepare_delivery(store, plan, run_dir)
    destination = run_dir / 'delivery-test'
    destination.mkdir()
    delivered = procedure.write(destination, prepared)
    assert {'procedure/procedure.md', 'procedure/Snakefile'} <= {row['path'] for row in delivered}
    document = procedure_export.verify(destination / 'procedure', deep=True)
    assert any(row['kind'] == 'controller-step' for row in document['nodes'])
    assert any(pin['path'].endswith('outputs/sources.tar') for pin in document['source_pins'])
    assert any(pin['path'].endswith('outputs/claim_map.json') for pin in document['source_pins'])
    assert document['controller']['plan_sha256'] == plan['sha256']
    assert all((destination / row['path']).stat().st_mode & 0o077 == 0 for row in delivered)
    source_path = run_dir / 'steps/m02-sources/outputs/sources.tar'
    source_path.write_bytes(source_path.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='changed|custody'):
        procedure.prepare_delivery(store, plan, run_dir)


def test_P17_graph_structure_handoff_preserves_existing_gate_populations(tmp_path, record_property):
    cases = [(ml_study, 'ml.study', 2, {'study': 'fixture_study'},
              {'unblind_gate', 'spend_gate', 'select_gate', 'final_gate'}),
             (manuscript, 'manuscript.build', 1, {'request_id': 'fixture_note'},
              {'report_integrity', 'final_task', 'integrity_auditor', 'meta_reviewer'})]
    for module, graph_id, version, instance, original_nodes in cases:
        ctx = gs.BuildContext(tmp_path, graph_id, version, instance)
        compiled = app(module, ctx)
        assert original_nodes <= set(compiled.builder.nodes)
        record_property(graph_id + '.structure_sha256', compiled.structure_sha256)


def test_P17_budget_ending_is_not_reported_as_a_completed_child_graph(tmp_path, monkeypatch):
    from ravel.workflow import graph_nodes
    binding = ml_binding(tmp_path, support.spec(epochs=100000, wall=1))
    calls = []
    fake_step(monkeypatch, binding.run_dir, binding.store, calls)
    ctx = gs.BuildContext(binding.run_dir, 'ml.study', 2, {'study': 'fixture_study'})
    with ml_executor.bound(binding):
        result = app(ml_study, ctx).invoke(meta(ctx), {'recursion_limit': 120})
    assert result['ml_status'] == 'qualified', result.get('ml_reason')
    assert result['status']['terminal'] == 'budget_exhausted'
    assert graph_nodes._outcome(result) == 'failed'
    assert 't06-evaluate' not in calls
    assert result['results']['ending']['unfinished']
    sink = InertSink()
    assert sink.bounded_end(binding.store, result['ml_reason'])['qualified']
    assert sink.calls == ['bounded_end']
