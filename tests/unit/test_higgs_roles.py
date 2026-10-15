"""Synthetic card, dispatch and source-bound convention refusal controls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import role_registry, spawn_rows

ROOT = Path(__file__).resolve().parents[2]
ROLES = ('consult-higgs', 'higgs-coupling-analyst', 'extended-scalar-modeler',
         'higgs-combination-reviewer', 'higgs-theory-uncertainty-auditor')


def test_unresolved_check_alias_rejected_even_if_atlas_lists_it():
    card = role_registry.load('re-deriver')
    card['must_check'] = ['check:higgs.unresolved']
    known = role_registry._known_ids() | set(card['must_check'])
    assert any('unresolved' in e for e in role_registry.validate_card(card, known_ids=known))


def test_reviewer_cannot_read_headline_even_when_forbidden():
    card = role_registry.load('re-deriver')
    card['knowledge']['must_read'].append('producer_headline:synthetic')
    known = role_registry._known_ids() | {'producer_headline:synthetic'}
    assert any('headline' in e for e in role_registry.validate_card(card, known_ids=known))


def test_surface_gate_rejects_unresolved_card(tmp_path, monkeypatch):
    from ravel.validation import check_agent_surface
    roles_root = tmp_path / 'src/ravel/data/roles'
    roles_root.mkdir(parents=True)
    document = role_registry.registry_document()
    card = document['roles']['re-deriver']['card']
    card['must_check'] = ['check:higgs.unresolved']
    document['roles']['re-deriver'].pop('override', None)
    monkeypatch.setattr(role_registry, 'registry_document', lambda **kwargs: deepcopy(document))
    (roles_root / 'registry.json').write_text(json.dumps(document))
    atlas = tmp_path / 'src/ravel/data/knowledge/atlas.json'
    atlas.parent.mkdir(parents=True)
    entries = [{'id': i} for i in role_registry._known_ids() | {'check:higgs.unresolved'}]
    atlas.write_text(json.dumps({'entries': entries}))
    assert any('unresolved' in e for e in check_agent_surface.check_roles(tmp_path))


@pytest.mark.parametrize('role', ROLES)
def test_cards_are_registered_and_checks_resolve(role):
    from ravel.validation import higgs_checks
    card = role_registry.load(role)
    assert not role_registry.validate_card(card)
    assert all(callable(higgs_checks.resolve(i)) for i in card['must_check'])
    assert card['model']['effort'] == 'high'
    if card['family'] == 'specialist-review':
        assert card['independence']['fresh_session']
        assert 'producer_headline' in card['sees']['forbidden_inputs']
        assert 'higgs-coupling-analyst' in card['independence']['distinct_actor_from']


def plan(tags, experiments=None):
    fields = [{'pointer': '/review/domain_tags', 'value': tags}]
    if experiments is not None:
        fields.append({'pointer': '/review/experiments', 'value': experiments})
    return {'agent_layer_epoch': 2, 'nodes': [{'id': 'N-0001', 'kind': 'operation',
        'operation': 'literal-calculation', 'fields': fields}], 'claims': [], 'edges': [], 'inputs': []}


@pytest.mark.parametrize('tags,experiments,expected', [
    (['higgs', 'combination'], ['EXP-A', 'EXP-B'],
     {'higgs-combination-reviewer', 'higgs-theory-uncertainty-auditor'}),
    (['extended-scalar'], None, {'extended-scalar-modeler', 'consult-higgs'}),
    (['combination'], ['EXP-A', 'EXP-B'], {'higgs-theory-uncertainty-auditor'}),
    (['higgs', 'reference-table'], None, set()),
])
def test_spawn_semantic_requests(tags, experiments, expected):
    roles = {r['role'] for p in spawn_rows.derive(plan(tags, experiments)) for r in p['roles']}
    assert roles & set(ROLES) == expected


def test_spawn_ignores_titles_and_preserves_legacy():
    facts = plan(['reference-table'])
    facts['nodes'][0]['title'] = 'higgs combination extended-scalar'
    assert not spawn_rows.derive(facts)
    facts = plan(['higgs', 'combination'], ['EXP-A', 'EXP-B'])
    facts['agent_layer_epoch'] = 1
    assert not spawn_rows.derive(facts)


def test_higgs_conventions_have_located_evidence():
    from ravel.workflow import physics_knowledge, premises
    packet = physics_knowledge.retrieve(premises.shard_request('higgs', roots='all'), premises.DATA)
    assert 0 < len(packet['nodes']) <= 512
    assert all(n['source_evidence'] for n in packet['nodes'] if n['kind'] != 'hypothesis')
    assert {'conv:higgs', 'conv:higgs-scalar-basis', 'conv:higgs-theory-uncertainty'} <= {n['id'] for n in packet['nodes']}


def test_consult_and_role_knowledge_bindings():
    from ravel.workflow import consults, knowledge_bundles
    assert consults.for_tool('higgs')['role'] == 'consult-higgs'
    card = role_registry.load('consult-higgs')
    _, _, _, bindings = knowledge_bundles._stores({})
    assert 'conv:higgs' in bindings['roles'][card['id']]['include']


def test_cards_do_not_claim_unavailable_handbooks():
    ids = role_registry._known_ids()
    for role in ROLES:
        assert set(role_registry.load(role)['knowledge']['must_read']) <= ids


def test_missing_operation_checks_fail_closed():
    from ravel.validation import higgs_checks
    for identity in higgs_checks.DELEGATES:
        result = higgs_checks.run_check({}, check_id=identity)
        assert result['status'] == 'inconclusive' and result['outcome'] != 'passed'


def test_changed_registration_is_rejected_by_cold_bundle(tmp_path):
    import shutil
    from ravel.workflow import knowledge_bundles
    data = tmp_path / 'src/ravel/data'
    for relative in ('knowledge/premises.json', 'knowledge/role_bindings.json',
                     'higgs/registration/premises.json', 'higgs/registration/knowledge.json'):
        target = data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'src/ravel/data' / relative, target)
    path = data / 'higgs/registration/premises.json'
    value = json.loads(path.read_text())
    value['append']['premises'][0]['statement'] = 'Changed synthetic source.'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='registration source changed'):
        knowledge_bundles._stores({'premises_path': data / 'knowledge/premises.json',
                                  'role_bindings_path': data / 'knowledge/role_bindings.json'})


def test_invalid_registration_envelope_and_collision_refused(tmp_path):
    from ravel.workflow.higgs_registration import compose
    directory = tmp_path / 'data/higgs/registration'
    directory.mkdir(parents=True)
    path = directory / 'knowledge.json'
    base = {'kind': 'role-knowledge-bindings', 'schema_version': 1, 'roles': {'synthetic': {}}}
    fragment = {'schema_version': 1, 'kind': 'registry-registration',
                'target': base['kind'], 'append': {'roles': {'synthetic': {}}}}
    path.write_text(json.dumps(fragment))
    with pytest.raises(ValueError, match='collision'):
        compose(base, tmp_path / 'data/knowledge/role_bindings.json')
    fragment['schema_version'] = True
    path.write_text(json.dumps(fragment))
    with pytest.raises(ValueError, match='versioned'):
        compose(base, tmp_path / 'data/knowledge/role_bindings.json')


def test_declared_checks_execute_through_broker(tmp_path, monkeypatch):
    from ravel.workflow import review_projection_checks
    from test_worker_broker import make
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    card = role_registry.load('higgs-theory-uncertainty-auditor')
    review_projection_checks.register(target, card)
    fixture = ROOT / 'tests/knowledge/fixtures/higgs-traps.json'
    document = json.loads(fixture.read_text())['TH2']['planted']
    (target.workspace / 'inputs/declarations.json').write_text(json.dumps(document))
    identity = card['must_check'][0]
    reply = target.call({'call_id': 'C-0001', 'action': 'check run',
        'args': {'check_id': identity, 'paths': ['inputs/declarations.json']}})
    assert reply['status'] == 'failed', reply
    receipt = target.verify_ledger()[-1]
    assert receipt['validator_id'] == identity
    assert receipt['output_pins']


def test_delegation_uses_only_owner_interface_and_preserves_failure(monkeypatch):
    from types import SimpleNamespace
    from ravel.validation import higgs_checks
    identity = 'check:higgs.measurement_bundle'
    called = []
    def checker(doc):
        called.append(doc)
        return {'status': 'failed', 'findings': [{'code': 'supplied-error', 'materiality': 'A'}]}
    monkeypatch.setattr(higgs_checks, 'import_module', lambda name:
        SimpleNamespace(check_measurement_bundle=checker))
    result = higgs_checks.run_check({'population': ['ANA-0001']}, check_id=identity)
    assert result['status'] == 'failed' and result['findings'][0]['code'] == 'supplied-error'
    assert called == [{'population': ['ANA-0001']}]


@pytest.mark.parametrize('identity,module,function,owner', [
    ('check:higgs.measurement_bundle', 'higgs_measurements', 'check_measurement_bundle', 'H-02'),
    ('check:higgs.parameterization_closure', 'higgs_parameterization', 'check_parameterization_closure', 'H-05'),
    ('check:higgs.scalar_basis', 'extended_scalar', 'check_scalar_basis', 'H-09'),
    ('check:higgs.theory_constraints', 'extended_scalar', 'check_theory_constraints', 'H-09'),
    ('check:higgs.cross_engine', 'higgs_likelihood', 'check_cross_engine', 'H-05'),
])
def test_operation_owner_interface(identity, module, function, owner):
    from importlib import import_module
    # H-05 is merged, so its interfaces are required.
    if owner != 'H-05' and not (ROOT / 'src/ravel/physics' / (module + '.py')).is_file():
        pytest.xfail('awaits ' + owner)
    assert callable(getattr(import_module('ravel.physics.' + module), function))


def test_delegation_cannot_pass_material_findings(monkeypatch):
    from types import SimpleNamespace
    from ravel.validation import higgs_checks
    monkeypatch.setattr(higgs_checks, 'import_module', lambda name:
        SimpleNamespace(check_measurement_bundle=lambda doc:
            {'status': 'passed', 'findings': [{'code': 'supplied-error', 'materiality': 'A'}]}))
    assert higgs_checks.run_check({}, check_id='check:higgs.measurement_bundle')['status'] != 'passed'


def test_operation_registration_fragments_beside_the_scalar_fragments_are_not_composed(tmp_path):
    # The registration folder also holds operation-row fragments with another schema; only the
    # scalar registry fragments are composed and pinned.
    from ravel.workflow import higgs_registration
    folder = tmp_path / 'higgs/registration'
    folder.mkdir(parents=True)
    for name in higgs_registration.FILES.values():
        (folder / name).write_text('{}\n')
    (folder / 'fictional-operation.json').write_text(json.dumps({'fictional-operation': {'summary': 'synthetic'}}))
    assert [p.name for p in higgs_registration.fragment_paths(tmp_path)] == sorted(higgs_registration.FILES.values())
