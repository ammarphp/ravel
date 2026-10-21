"""Synthetic controls for data-defined staffing; no worker or native execution."""
from copy import deepcopy
import importlib

import pytest


def module():
    return importlib.import_module('ravel.workflow.spawn_rows')


def plan(**changes):
    value = {'agent_layer_epoch': 2, 'nodes': [], 'claims': [], 'inputs': [], 'edges': []}
    value.update(changes)
    return value


@pytest.mark.parametrize('row,facts,role,count', [
    ('K1', plan(nodes=[{'id': 'n', 'kind': 'operation', 'operation': 'literal-calculation', 'tool': 'symbolic', 'rung': 'smoke', 'authored': {'draft': 'draft.json'}}]), 'consult-symbolic', 1),
    ('K4', plan(nodes=[{'id': 'n', 'kind': 'authored', 'authored': {}, 'authors': 'analysis', 'evaluator': {'kind': 'deterministic'}}]), 'analysis-author', 3),
    ('K5', plan(claims=[{'id': 'c', 'basis_declared': ['generated_prediction']}]), 're-deriver', 2),
    ('K6', plan(panels=[{'id': 'p', 'attempts': [{'id': 'a'}, {'id': 'b'}]}]), 'comparative-reviewer', 1),
    ('K7', plan(nodes=[{'id': 'n', 'kind': 'operation', 'operation': 'resonance-width'}], claims=[{'id': 'c', 'primary': True, 'inherits': ['n']}]), 're-deriver', 1),
])
def test_each_planted_trigger_spawns(row, facts, role, count):
    points = module().derive(facts)
    point = next(p for p in points if p['row'] == row)
    assert next(r for r in point['roles'] if r['role'] == role)['count'] == count
    if row == 'K5':
        assert any(r['role'] == 'normalization-auditor' for r in point['roles'])
        assert point['blind_to_producer_numbers']
    if row == 'K4':
        assert point['min_model_families'] == 1
    if row == 'K7':
        assert point['forbidden_method_nodes'] == ['n']


def test_clean_and_legacy_siblings_do_not_spawn():
    assert module().derive(plan()) == []
    assert module().derive(plan(agent_layer_epoch=1, panels=[{'id': 'p', 'attempts': ['a', 'b']}])) == []
    for node in [dict(id='n', kind='operation', operation='literal-calculation', tool='symbolic', rung='smoke'),
                 dict(id='n', kind='authored', authored={})]:
        assert not module().derive(plan(nodes=[node]))


def test_candidate_deadline_and_permutation():
    facts = plan(deadline=True, nodes=[{'id': 'n', 'kind': 'authored', 'authored': {}, 'evaluator': {'kind': 'deterministic'}}])
    points = module().derive(facts)
    assert next(p for p in points if p['row'] == 'K4')['roles'][0]['count'] == 2
    assert any(p['row'] == 'K6' for p in points)
    facts['nodes'].append({'id': 'z', 'kind': 'operation', 'operation': 'literal-calculation'})
    reverse = deepcopy(facts); reverse['nodes'].reverse()
    assert module().derive(facts) == module().derive(reverse)


@pytest.mark.parametrize('primary,operation,expected', [(False, 'resonance-width', False), (True, 'formula-grid', True), (True, 'literal-calculation', True)])
def test_analytic_primary_scope(primary, operation, expected):
    points = module().derive(plan(nodes=[{'id': 'n', 'kind': 'operation', 'operation': operation}],
                                 claims=[{'id': 'c', 'primary': primary, 'inherits': ['n']}]))
    assert any(p['row'] == 'K7' for p in points) == expected


def test_analytic_comparison_rejects_disagreement_and_missing_units():
    compare = module().compare_analytic
    original = {'value': 4., 'unit': 'arb'}
    assert compare(original, {'value': 4., 'unit': 'arb'}, relative_tolerance=0.01)['passed']
    assert not compare(original, {'value': 8., 'unit': 'arb'}, relative_tolerance=0.01)['passed']
    with pytest.raises(ValueError):
        compare(original, {'value': 4.}, relative_tolerance=0.01)


def test_registered_provider_holds_candidate_launch(tmp_path):
    import hashlib
    import json
    from ravel.workflow import decision_gate
    (tmp_path / 'inputs').mkdir()
    facts = plan(nodes=[{'id': 'n', 'kind': 'authored', 'authored': {}, 'evaluator': {'kind': 'deterministic'}}])
    path = tmp_path / 'inputs/plan.json'; path.write_text(json.dumps(facts))
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2, 'request_plan':
        {'path': 'inputs/plan.json', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}))
    assert any(e.code == 'spawn_review_pending' for e in decision_gate.check(tmp_path, 'launch', {'node_id': 'n'}))


def test_data_catalogue_has_closed_row_identities():
    value = module().catalogue()
    assert {row['row'] for row in value['rows']} == {'K1', 'K4', 'K5', 'K6', 'K7', 'K7S', 'K8', 'K10', 'K11', 'KH1', 'KH2', 'KH3'}
    assert len({row['row'] for row in value['rows']}) == len(value['rows'])


def test_XF06_same_family_candidates_require_custody_and_distinct_sessions(tmp_path):
    import hashlib
    import json
    from ravel.workflow import rdj_custody, review_points
    facts = plan(nodes=[{'id': 'n', 'kind': 'authored', 'authored': {}, 'evaluator': {'kind': 'deterministic'}}])
    (tmp_path / 'inputs').mkdir()
    path = tmp_path / 'inputs/plan.json'; path.write_text(json.dumps(facts))
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2, 'request_plan':
        {'path': 'inputs/plan.json', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}))
    point = next(p for p in module().derive(facts) if p['row'] == 'K4')
    for index in range(3):
        work = tmp_path / 'agent-work' / str(index) / '1'; work.mkdir(parents=True)
        final = work / 'final.json'; final.write_text('{"findings": []}')
        rec = {'schema_version': 2, 'kind': 'agent-worker-receipt', 'node_id': str(index), 'attempt': 1,
               'review_point_id': point['id'], 'role': {'id': 'spec-author'}, 'status': 'ok',
               'session_id': str(index), 'actor_id': str(index), 'model': {'family': 'alpha'},
               'run_tree': {'modified': False}, 'final_record': {'valid': True, 'path': 'final.json',
               'sha256': hashlib.sha256(final.read_bytes()).hexdigest()},
               'execution_mode': 'transport_attested_cli',
               'review_subject': review_points.review_subject(facts, point)}
        # The dispatcher assigns each worker session its actor at spawn and registers it with the receipt.
        rec['actor_id'] = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', 'ws-' + str(index),
                                                 f'{index}/1', family='alpha')['actor_id']
        path = work / 'receipt.json'; path.write_text(json.dumps(rec))
    pending = next(p for p in module().pending(tmp_path) if p['id'] == point['id'])
    assert pending['family_label'] == 'model family unknown' and not pending['family_diversity_pending']
    for path in (tmp_path / 'agent-work').glob('*/*/receipt.json'):
        index = path.parent.parent.name
        rdj_custody.register_worker_receipt(tmp_path, path.relative_to(tmp_path).as_posix(), verified_label='transport_attested',
                                            actor=rdj_custody.actor_record('synthetic-cli', 'synthetic-model',
                                                                         'ws-' + index, f'{index}/1', family='alpha'))
    assert not any(p['id'] == point['id'] for p in module().pending(tmp_path))
    filled = next(p for p in module().report(tmp_path) if p['id'] == point['id'])
    assert not filled['pending'] and filled['family_label'] == 'single model family'
    # Reusing a transport session cannot replace the third independent candidate.
    path = tmp_path / 'agent-work' / '2' / '1' / 'receipt.json'
    rec = json.loads(path.read_text())
    rec['session_id'] = '1'
    path.write_text(json.dumps(rec))
    rdj_custody.register_worker_receipt(tmp_path, path.relative_to(tmp_path).as_posix(),
                                      verified_label='transport_attested',
                                      actor=rdj_custody.actor_record('synthetic-cli', 'synthetic-model', 'ws-2',
                                                                   '2/1', family='alpha'))
    assert any(p['id'] == point['id'] for p in module().pending(tmp_path))


def test_compare_pinned_width_and_grid_outputs(tmp_path):
    import hashlib
    import json
    pins = []
    for name in ['width.json', 'grid.json']:
        path = tmp_path / name; path.write_text(json.dumps({'total_width_gev': 6.}))
        pins.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    assert module().compare_outputs(tmp_path, *pins, pointer='/total_width_gev', unit='GeV', relative_tolerance=0.01)['passed']
    (tmp_path / 'grid.json').write_text('{"total_width_gev": 12}')
    with pytest.raises(ValueError):
        module().compare_outputs(tmp_path, *pins, pointer='/total_width_gev', unit='GeV', relative_tolerance=0.01)


def test_schema_shaped_metadata_drives_draft_evaluator_and_primary_claim():
    from ravel.validation import intake_records
    from ravel.validation.validate_task_contract import _schema_errors
    fields = [{'pointer': '/review/deadline', 'value': True, 'authority': 'supplied', 'evidence': None}]
    assert not _schema_errors(fields, intake_records.NODE['properties']['fields'], 'fields')
    facts = plan(nodes=[{'id': 'N1', 'kind': 'authored', 'operation': 'model-events', 'rung': 'smoke',
        'fields': fields, 'implementation': 'authored-analysis', 'spec_template': {'path': 'draft.json', 'sha256': 'a'*64},
        'authored': {'signature': {'evaluator': {'kind': 'deterministic'}}}},
        {'id': 'N2', 'kind': 'operation', 'operation': 'resonance-width'}],
        claims=[{'id': 'C1', 'kind': 'calculation', 'inherits': ['N2']}])
    points = module().derive(facts)
    assert {'K1', 'K4', 'K6', 'K7'} <= {p['row'] for p in points}
    assert next(p for p in points if p['row'] == 'K4')['roles'][0]['count'] == 2


def test_width_and_formula_grid_use_their_own_quantity_pointers(tmp_path):
    import hashlib
    import json
    documents = [('first.json', {'schema_version': 1, 'kind': 'resonance-width', 'total_width_gev': 6.}),
                 ('second.json', {'schema_version': 1, 'kind': 'inference', 'results': [
                     {'quantity': 'grid-values', 'role': 'primary', 'unit': 'GeV', 'values': [6.]}]})]
    pins = []
    for name, value in documents:
        path = tmp_path / name; path.write_text(json.dumps(value))
        pins.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    result = module().compare_outputs(tmp_path, *pins, pointer='/total_width_gev',
        second_pointer='/results/0/values/0', unit='GeV', relative_tolerance=0.01)
    assert result['passed']
    assert result['second_pointer'] == '/results/0/values/0'


def test_tool_aliases_collapse_to_one_registered_consult_role():
    from ravel.workflow import role_registry
    facts = plan(nodes=[{'id': 'n', 'kind': 'operation', 'operation': 'model-tool-bridge', 'rung': 'smoke',
                         'authored': {'draft': 'draft.json'}}])
    points = [p for p in module().derive(facts) if p['row'] == 'K1']
    roles = [r['role'] for p in points for r in p['roles']]
    assert roles and len(roles) == len(set(roles))
    document = role_registry.registry_document()
    assert all(role in document['roles'] for role in roles)
