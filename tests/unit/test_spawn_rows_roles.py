"""Synthetic controls for the second-method, assumption, model-critic and explore/exploit rows."""
import hashlib
import json

import pytest

from ravel.workflow import role_registry, spawn_rows

NEW_CARDS = ('second-method-deriver', 'assumption-auditor', 'model-critic')


def plan(**changes):
    value = {'agent_layer_epoch': 2, 'nodes': [], 'claims': [], 'inputs': [], 'edges': []}
    value.update(changes)
    return value


def field(name, value):
    return {'pointer': '/review/' + name, 'value': value}


def rows(points, row):
    return [p for p in points if p['row'] == row]


@pytest.mark.parametrize('row,facts,role,count', [
    ('K7S', plan(nodes=[{'id': 'n', 'kind': 'operation', 'operation': 'resonance-width'}],
                 claims=[{'id': 'c', 'primary': False, 'inherits': ['n']}]), 'second-method-deriver', 1),
    ('K8', plan(claims=[{'id': 'c', 'basis_declared': ['supplied_inputs']}]), 'assumption-auditor', 1),
    ('K10', plan(nodes=[{'id': 'm', 'kind': 'authored', 'implementation': 'model-authoring', 'authored': {}}]), 'model-critic', 1),
    ('K10', plan(nodes=[{'id': 'm', 'kind': 'operation', 'operation': 'model-tool-bridge'}]), 'model-critic', 1),
    ('K11', plan(nodes=[{'id': 'r', 'kind': 'envelope'}]), 'research-explorer', 1),
    ('K11', plan(nodes=[{'id': 'r', 'kind': 'envelope'}]), 'research-evolver', 1),
])
def test_each_planted_trigger_spawns(row, facts, role, count):
    point = rows(spawn_rows.derive(facts), row)[0]
    assert next(r for r in point['roles'] if r['role'] == role)['count'] == count


def test_clean_siblings_do_not_spawn():
    assert not spawn_rows.derive(plan())
    assert not spawn_rows.derive(plan(agent_layer_epoch=1, claims=[{'id': 'c', 'basis_declared': ['analytic']}],
                                      nodes=[{'id': 'r', 'kind': 'envelope'}]))
    points = spawn_rows.derive(plan(nodes=[{'id': 'n', 'kind': 'operation', 'operation': 'literal-calculation'}]))
    assert not rows(points, 'K10') and not rows(points, 'K11') and not rows(points, 'K8')


def test_second_method_complements_the_primary_analytic_row():
    primary = plan(nodes=[{'id': 'n', 'kind': 'operation', 'operation': 'formula-grid'}],
                   claims=[{'id': 'c', 'primary': True, 'inherits': ['n']}])
    points = spawn_rows.derive(primary)
    assert rows(points, 'K7') and not rows(points, 'K7S')
    point = rows(spawn_rows.derive(plan(nodes=[{'id': 'n', 'kind': 'operation', 'operation': 'resonance-width'}],
                                        claims=[{'id': 'c', 'primary': False, 'inherits': ['n']}])), 'K7S')[0]
    assert point['forbidden_method_nodes'] == ['n'] and point['comparison_required'] and point['claim_id'] == 'c'


def test_one_assumption_audit_per_run_at_delivery():
    points = rows(spawn_rows.derive(plan(claims=[{'id': 'a', 'basis_declared': ['supplied_inputs']},
                                                 {'id': 'b', 'basis_declared': ['supplied_inputs']}])), 'K8')
    assert len(points) == 1 and points[0]['gate'] == 'delivery' and points[0]['severity_floor'] == 7


def test_declared_split_and_default_halves():
    node = {'id': 'r', 'kind': 'operation', 'implementation': 'research-coordinator',
            'fields': [field('attempt_budget', 6), field('explore_exploit', {'exploit': 2, 'explore': 4})]}
    point = rows(spawn_rows.derive(plan(nodes=[node])), 'K11')[0]
    assert point['budget_split'] == {'attempt_budget': 6, 'exploit': 2, 'explore': 4, 'declared': True}
    assert {r['role']: r['count'] for r in point['roles']} == {'research-evolver': 2, 'research-explorer': 4}
    odd = {'id': 'r', 'kind': 'envelope', 'fields': [field('attempt_budget', 5)]}
    split = rows(spawn_rows.derive(plan(nodes=[odd])), 'K11')[0]['budget_split']
    assert (split['exploit'], split['explore'], split['declared']) == (2, 3, False)
    explore_only = {'id': 'r', 'kind': 'envelope', 'fields': [field('attempt_budget', 2),
                                                              field('explore_exploit', {'exploit': 0, 'explore': 2})]}
    assert [r['role'] for r in rows(spawn_rows.derive(plan(nodes=[explore_only])), 'K11')[0]['roles']] == ['research-explorer']


@pytest.mark.parametrize('budget,split', [(4, {'exploit': 1, 'explore': 2}), (4, {'exploit': -1, 'explore': 5}),
                                          (4, {'exploit': 2.0, 'explore': 2}), (0, None), (True, None),
                                          (4, {'exploit': 2, 'explore': 2, 'other': 0})])
def test_inconsistent_split_is_refused(budget, split):
    fields = [field('attempt_budget', budget)] + ([field('explore_exploit', split)] if split is not None else [])
    with pytest.raises(ValueError, match='explore/exploit'):
        spawn_rows.derive(plan(nodes=[{'id': 'r', 'kind': 'envelope', 'fields': fields}]))


def test_derivation_is_permutation_invariant():
    nodes = [{'id': 'm', 'kind': 'operation', 'operation': 'model-sources'}, {'id': 'r', 'kind': 'envelope'},
             {'id': 'w', 'kind': 'operation', 'operation': 'resonance-width'}]
    claims = [{'id': 'b', 'inherits': ['w']}, {'id': 'a', 'basis_declared': ['supplied_inputs']}]
    assert spawn_rows.derive(plan(nodes=nodes, claims=claims)) == \
        spawn_rows.derive(plan(nodes=nodes[::-1], claims=claims[::-1]))


def test_catalogue_rows_are_appended_with_registered_roles():
    catalogue = spawn_rows.catalogue()
    assert [r['row'] for r in catalogue['rows']][:5] == ['K1', 'K4', 'K5', 'K6', 'K7']
    added = {r['row']: r for r in catalogue['rows'][5:]}
    assert set(added) == {'K7S', 'K8', 'K10', 'K11', 'KH1', 'KH2', 'KH3'}
    document = role_registry.registry_document()
    for row in added.values():
        for role in [r['role'] for r in row['roles']] + [row[k] for k in ('exploit_role', 'explore_role') if k in row]:
            assert role in document['roles']


def _rundir(tmp_path, facts):
    (tmp_path / 'inputs').mkdir()
    path = tmp_path / 'inputs/plan.json'; path.write_text(json.dumps(facts))
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2, 'request_plan':
        {'path': 'inputs/plan.json', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}))
    return tmp_path


@pytest.mark.parametrize('gate,action,facts,point', [
    ('delivery', {}, plan(claims=[{'id': 'c', 'basis_declared': ['supplied_inputs']}]), 'K8:run'),
    ('checkin2_accept', {'node_id': 'm'}, plan(nodes=[{'id': 'm', 'kind': 'operation', 'operation': 'model-sources'}]), 'K10:m'),
    ('research_choice', {'node_id': 'r'}, plan(nodes=[{'id': 'r', 'kind': 'envelope'}]), 'K11:r'),
])
def test_registered_provider_holds_each_gate(tmp_path, gate, action, facts, point):
    errors = spawn_rows.gate_errors(_rundir(tmp_path, facts), gate, action)
    assert any(e.code == 'spawn_review_pending' and point in e.message for e in errors)
    from ravel.workflow import decision_gate
    assert any(p['id'] == 'spawn_rows' for p in decision_gate.providers(gate))


@pytest.mark.parametrize('identity', NEW_CARDS)
def test_cards_validate_and_are_blind_specialists(identity):
    card = role_registry.load(identity)
    assert not role_registry.validate_card(card)
    assert card['family'] == 'specialist-review' and card['independence']['kind'] == 'specialist'
    assert card['requires']['tools'] == 'broker-readonly'
    assert {'lessons', 'producer_headline', 'other_verdicts'} <= set(card['sees']['forbidden_inputs'])
    assert role_registry.registry_document()['roles'][identity]['override'] == f'cards/{identity}.json'


def test_second_method_card_forbids_the_first_method():
    card = role_registry.load('second-method-deriver')
    assert 'first_method' in card['sees']['forbidden_inputs'] and card['requires']['blind']
    assert any('forbidden_method_nodes' in text for text in card['protocol'])


@pytest.mark.parametrize('identity', NEW_CARDS)
def test_cards_render_with_zero_drift(identity):
    from ravel.paths import repository_root
    root = repository_root()
    assert not role_registry.validate_registry()
    for surface in role_registry.SURFACES:
        rendered = role_registry.render(surface)
        relative = role_registry.profile_paths(surface)[identity]
        assert (root / relative).read_bytes() == rendered[relative].encode()
    assert not role_registry.check_rendered(root, exclude=('AGENTS.md', 'CLAUDE.md'))


def test_uncontrolled_severe_assumption_must_appear_in_result():
    from ravel.validation import assumption_audit
    audit = {'schema_version': 1, 'kind': 'assumption-audit', 'items': [
        {'id': 'A1', 'statement': 'synthetic shape transfer', 'severity': 8, 'controlled': False},
        {'id': 'A2', 'statement': 'synthetic width neglected', 'severity': 9, 'controlled': True},
        {'id': 'A3', 'statement': 'synthetic rounding', 'severity': 6, 'controlled': False}]}
    assert assumption_audit.check(audit, {'assumptions_reported': []}) == ['uncontrolled assumption A1 (severity 8) is absent from the result']
    assert assumption_audit.check(audit, {'assumptions_reported': ['A1']}) == []
    with pytest.raises(ValueError):
        assumption_audit.check({**audit, 'items': [{'id': 'A1', 'statement': 's', 'severity': 11, 'controlled': False}]}, {})
    with pytest.raises(ValueError):
        assumption_audit.check({**audit, 'items': [{'id': 'A1', 'statement': 's', 'severity': True, 'controlled': False}]}, {})
