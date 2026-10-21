"""Inert governance scaffolding with real manuscript assembly, registered graph and sink delivery.

This composition checks procedure delivery and byte custody under the fixture's governance contract.
"""
from copy import deepcopy
import importlib
import json
import sys

import pytest

import p17_support as support
from p07_support import run  # noqa: F401

# Preserve the installed modules before the sink fixture marks route services absent.
_REAL_ROUTES = {name: importlib.import_module(name) for name in (
    'ravel.controller.routes.manuscript', 'ravel.controller.routes.manuscript.staged',
    'ravel.controller.routes.manuscript.note', 'ravel.controller.routes.ml.staged',
)}


def test_bounded_sink_delivers_verified_manuscript_procedure_and_detects_changes(run, tmp_path, monkeypatch):
    for name, module in _REAL_ROUTES.items():
        monkeypatch.setitem(sys.modules, name, module)
    from ravel.controller import sink
    from ravel.controller.routes.manuscript import note, staged
    from ravel.workflow import graph_substrate as gs, procedure_export

    result_path = tmp_path / 'result.json'
    result_path.write_text('{"metric":0.75}')
    compiled_plan = support.plan('manuscript', {
        'python': sys.executable, 'tex': '', 'result_path': str(result_path),
        'result_sha256': support.sha(result_path)}, deliverables=(('document', 'document'),))
    run.steps = deepcopy(compiled_plan['steps'])
    run.deliverables = deepcopy(compiled_plan['deliverables'])
    plan = run.pin_plan()
    retained = 'retained-input:outputs/result.json'
    run.adopt('retained-input', 'outputs/result.json', result_path.read_bytes(), kind='result')
    claims = {'kind': 'manuscript-claim-map', 'schema_version': 1, 'title': 'Fixture note',
              'results': {'result': {'sha256': support.sha(result_path)}},
              'claims': [{'id': 'c1', 'text': 'The measured value is 0.75.', 'result': 'result',
                          'quantity': {'pointer': '/metric', 'value': .75}}]}
    author_artifacts = ['m01-author:outputs/claim_map.json', 'm01-author:outputs/note.md',
                        'm01-author:outputs/trap_sweep.json']
    run.adopt('m01-author', 'outputs/claim_map.json', claims, kind='manuscript:claim-map', inputs=[retained])
    run.adopt('m01-author', 'outputs/note.md', '# Fixture note\n\n[[claim:c1]]\n', kind='document')
    run.adopt('m01-author', 'outputs/trap_sweep.json', {'none_hit': True, 'traps_hit': []},
              kind='validation:trap-sweep')
    inputs = {'claim_map': run.dir / 'steps/m01-author/outputs/claim_map.json',
              'note': run.dir / 'steps/m01-author/outputs/note.md', 'result.result': result_path}
    source = tmp_path / 'source'
    assert note.run_stage('sources', inputs, {}, source)['status'] == 'completed'
    source_artifacts = []
    for relative, kind in note.OUTPUTS['sources']:
        run.adopt('m02-sources', relative, (source / relative).read_bytes(), kind=kind, inputs=author_artifacts)
        source_artifacts.append('m02-sources:' + relative)

    attempt = run.dir / 'steps/m02-build/attempts/1/outputs'
    ctx = gs._context(run.dir, 'manuscript.build', {'request_id': 'synthetic_note'})
    with staged.services(staged.Binding(run.store, run.dir, plan, 'm02-build', attempt)):
        graph = gs.build('manuscript.build', ctx)
        assert gs.lint_graph(graph) == []
        built = graph.invoke({'meta': {'graph_id': ctx.graph_id, 'version': ctx.version,
                                      'instance': ctx.instance, 'scope_root': str(run.dir), 'path': None}})
    assert built['results']['note_assembly']['status'] == 'completed'
    assert built['procedure']['plan_sha256'] == plan['sha256']
    run.adopt('m02-build', 'outputs/assembly.json', (attempt / 'outputs/assembly.json').read_bytes(),
              kind='document', inputs=source_artifacts)

    final = sink.bounded_end(run.store, 'recorded stopping point')
    assert final['qualified'] is True and final['accepted'] is False
    assert final.get('delivered') is not False, final
    assert not any(row.get('code') == 'manuscript_procedure_invalid'
                   for row in final['work']['current_refusals'])
    delivery = run.dir / 'delivery'
    expected = {'procedure/procedure.json', 'procedure/procedure.md', 'procedure/Snakefile'}
    artifacts = {row['path']: row for row in final['delivery']['artifacts']}
    assert expected <= set(artifacts)
    document = procedure_export.verify(delivery / 'procedure', deep=True)
    assert document['controller']['plan_sha256'] == plan['sha256']
    assert any(row['kind'] == 'controller-step' for row in document['nodes'])
    assert any(pin['path'].endswith('outputs/sources.tar') for pin in document['source_pins'])
    assert any(pin['path'].endswith('outputs/claim_map.json') for pin in document['source_pins'])
    assert any(pin['path'].endswith('steps/retained-input/outputs/result.json')
               for pin in document['source_pins'])
    inventory_path = delivery / 'INVENTORY.json'
    assert support.sha(inventory_path) == final['delivery']['inventory_sha256']
    inventory = json.loads(inventory_path.read_text())
    assert inventory['artifacts'] == final['delivery']['artifacts']
    assert {row['path'] for row in inventory['artifacts']} == set(artifacts)
    for relative, row in artifacts.items():
        path = delivery / relative
        assert path.stat().st_size == row['size']
        assert support.sha(path) == row['sha256']
        assert path.stat().st_mode & 0o077 == 0
    assert sink.receipt(run.store)['verification']['delivery_intact'] is True

    retained_path = run.dir / 'steps/retained-input/outputs/result.json'
    retained_bytes = retained_path.read_bytes()
    retained_path.write_bytes(b'{"metric":0.25}')
    with pytest.raises(ValueError, match='source changed'):
        procedure_export.verify(delivery / 'procedure', deep=True)
    retained_path.write_bytes(retained_bytes)

    changed = delivery / 'procedure/procedure.md'
    changed.write_text(changed.read_text() + '\nChanged after delivery.\n')
    observed = sink.receipt(run.store)
    assert observed['accepted'] is False
    assert observed['verification']['delivery_intact'] is False
    assert any('procedure/procedure.md changed' in message for message in observed['verification']['problems'])
    assert support.sha(changed) != artifacts['procedure/procedure.md']['sha256']
