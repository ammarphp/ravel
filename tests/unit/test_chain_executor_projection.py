"""Fictional operation ownership through the ordinary executor and card readers."""
from copy import deepcopy
import json
from time import perf_counter

import pytest

from ravel.workflow import production_executor as pe, role_registry as rr, sfitter_workflow


OPERATION = 'synthetic-chain-operation'
PRODUCER = 'synthetic-producer'
OTHER = 'synthetic-other-producer'
CONSULT = 'synthetic-consult'


def signature(role=PRODUCER):
    return {
        'implementation': {'kind': 'science-mode', 'mode': OPERATION,
                           'module': 'synthetic.adapter', 'dispatch_group': 'event-inference-chain'},
        'effects': [],
        'registration': {
            'executor': role,
            'descriptor': {'summary': 'Supplied synthetic calculation.',
                           'operations': ['prediction'], 'tools': [], 'inputs': ['synthetic input'],
                           'observables': [], 'outputs': ['synthetic output'], 'context': [],
                           'applicability': {'scope': 'general'}},
            'setup_groups': ['synthetic-runtime'],
            'documentation': [{'path': 'docs/workflow/reference/scientific-studies.md',
                               'section': 'Generated-event quantity handoffs'}],
            'curation': {'use_when': ['Supplied synthetic input is available.'],
                         'do_not_use_when': ['The required input is missing.'],
                         'examples': [{'phrase': 'Evaluate supplied synthetic input.',
                                       'spec': {'mode': OPERATION, 'task': {}}}]},
        },
    }


def write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))


@pytest.fixture
def selected(tmp_path, monkeypatch):
    roles = tmp_path / 'data/roles'
    document = {
        'schema_version': 1, 'kind': 'role-registry', 'required_roles': [], 'aliases': {},
        'quantity_kinds': {'synthetic-quantity': {'source_roles': [PRODUCER]}},
        'roles': {identity: {'card': {'id': identity, 'family': family, 'operations': []}}
                  for identity, family in [(PRODUCER, 'production'), (OTHER, 'production'),
                                           (CONSULT, 'consult')]},
    }
    table = {'schema_version': 1, 'kind': 'production-executors', 'operations': {},
             'host_operations': {},
             'completeness_rule': {'implementation_kinds': ['science-mode'], 'effects': []}}
    signatures = {'schema_version': 1, 'kind': 'operation-signatures',
                  'operations': {OPERATION: signature()}}
    write(roles / 'registry.json', document)
    write(roles / 'executors.json', table)
    write(roles.parent / 'operation_signatures.json', signatures)
    monkeypatch.setattr(pe, 'DATA', roles / 'executors.json')
    monkeypatch.setattr(pe, 'SIGNATURES', roles.parent / 'operation_signatures.json')
    return roles, document, table, signatures


def test_real_readers_project_matching_ownership_without_mutating_source(selected):
    roles, document, table, signatures = selected
    before = {path: path.read_bytes() for path in (roles / 'registry.json', roles / 'executors.json',
                                                  roles.parent / 'operation_signatures.json')}
    effective_table = pe.executors()
    cards = rr.all_cards(roles_root=roles)
    assert effective_table['operations'] == {OPERATION: PRODUCER}
    assert rr.load(PRODUCER, roles_root=roles)['operations'] == [OPERATION]
    assert rr.load(OTHER, roles_root=roles)['operations'] == []
    assert pe.completeness_errors(signatures=signatures['operations'], table=effective_table,
                                  cards=cards) == []
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert document['roles'][PRODUCER]['card']['operations'] == []
    assert table['operations'] == {}
    effective_table['operations'].clear()
    assert pe.executors()['operations'] == {OPERATION: PRODUCER}


@pytest.mark.parametrize('role', ['synthetic-missing-role', CONSULT])
def test_missing_or_nonproduction_assignment_fails_completeness(selected, role):
    roles, _, _, signatures = selected
    signatures['operations'][OPERATION] = signature(role)
    write(roles.parent / 'operation_signatures.json', signatures)
    # Neither the assignment nor a missing role creates a new card identity.
    table = pe.executors()
    if role == CONSULT:
        with pytest.raises(ValueError):
            rr.load(CONSULT, roles_root=roles)
    cards = [rr.load(identity, roles_root=roles) for identity in (PRODUCER, OTHER)]
    assert any('not a registered production role' in e for e in pe.completeness_errors(
        signatures=signatures['operations'], table=table, cards=cards))
    if role != CONSULT:
        with pytest.raises(ValueError, match='unregistered role'):
            rr.load(role, roles_root=roles)


def test_conflicting_raw_executor_assignment_is_refused(selected):
    roles, _, table, _ = selected
    table['operations'][OPERATION] = OTHER
    write(roles / 'executors.json', table)
    with pytest.raises(ValueError):
        pe.executors()


@pytest.mark.parametrize('identity', [OTHER, CONSULT])
def test_wrong_raw_card_ownership_is_refused(selected, identity):
    roles, document, _, _ = selected
    document['roles'][identity]['card']['operations'] = [OPERATION]
    write(roles / 'registry.json', document)
    with pytest.raises(ValueError):
        rr.load(identity, roles_root=roles)


def test_override_projection_preserves_override_and_identity_guard(selected):
    roles, document, _, _ = selected
    document['roles'][PRODUCER]['override'] = f'cards/{PRODUCER}.json'
    write(roles / 'registry.json', document)
    override = {'id': PRODUCER, 'family': 'production', 'operations': [],
                'purpose': 'Synthetic override contract.'}
    override_path = roles / f'cards/{PRODUCER}.json'
    write(override_path, override)
    effective = rr.load(PRODUCER, roles_root=roles)
    assert effective['purpose'] == override['purpose']
    assert effective['operations'] == [OPERATION]
    assert json.loads(override_path.read_text()) == override
    override['id'] = OTHER
    write(override_path, override)
    with pytest.raises(ValueError, match='card identity differs'):
        rr.load(PRODUCER, roles_root=roles)


@pytest.mark.parametrize('explicit_root', [False, True])
def test_explicit_fixture_never_uses_host_signatures(selected, tmp_path, monkeypatch, explicit_root):
    roles, document, _, _ = selected
    host_data = tmp_path / 'host-data'
    write(host_data / 'operation_signatures.json', {'operations': {OPERATION: signature()}})
    monkeypatch.setattr(rr, 'package_data_path', lambda *parts: host_data.joinpath(*parts))
    (roles.parent / 'operation_signatures.json').unlink()
    kwargs = {'document': document}
    if explicit_root:
        kwargs['roles_root'] = roles
    assert rr.load(PRODUCER, **kwargs)['operations'] == []
    assert all(card['operations'] == [] for card in rr.all_cards(**kwargs))


def test_implicit_default_cards_and_digest_use_selected_package_data(selected, monkeypatch):
    roles, _, _, signatures = selected
    monkeypatch.setattr(rr, 'package_data_path', lambda *parts: roles.parent.joinpath(*parts))
    assert rr.load(PRODUCER)['operations'] == [OPERATION]
    assert next(card for card in rr.all_cards() if card['id'] == PRODUCER)['operations'] == [OPERATION]
    before = rr.registry_sha256()
    signatures['operations'][OPERATION]['registration']['executor'] = OTHER
    write(roles.parent / 'operation_signatures.json', signatures)
    assert rr.registry_sha256() != before
    assert rr.load(PRODUCER)['operations'] == []
    assert rr.load(OTHER)['operations'] == [OPERATION]


def test_completeness_does_not_repair_explicit_table_or_cards(selected):
    roles, _, table, signatures = selected
    cards = rr.all_cards(roles_root=roles)
    unchanged = deepcopy(table)
    assert pe.completeness_errors(signatures=signatures['operations'], table=table, cards=cards)
    assert table == unchanged
    effective = pe.executors()
    cards = deepcopy(cards)
    next(card for card in cards if card['id'] == PRODUCER)['operations'] = []
    before = deepcopy(cards)
    assert any('card operations differ' in e for e in pe.completeness_errors(
        signatures=signatures['operations'], table=effective, cards=cards))
    assert cards == before


def test_unregistered_compatibility_rows_remain_unprojected(selected):
    roles, document, table, signatures = selected
    del signatures['operations'][OPERATION]['registration']
    write(roles.parent / 'operation_signatures.json', signatures)
    assert pe.executors() == table
    assert rr.load(PRODUCER, roles_root=roles) == document['roles'][PRODUCER]['card']
    assert any('add a production role' in e for e in pe.completeness_errors(
        signatures=signatures['operations'], table=pe.executors(), cards=rr.all_cards(roles_root=roles)))


def test_validate_registry_keeps_default_projection_and_explicit_fixture_isolation(selected, monkeypatch):
    roles, document, _, _ = selected
    for row in document['roles'].values():
        row['card'].update(reviewed_by=[], knowledge={'consult': []})
    write(roles / 'registry.json', document)
    monkeypatch.setattr(rr, 'package_data_path', lambda *parts: roles.parent.joinpath(*parts))
    monkeypatch.setattr(rr, '_known_ids', lambda root: set())
    monkeypatch.setattr(rr, '_source_roles', lambda root: set())
    observed = {}

    def inspect(card, **kwargs):
        observed[card['id']] = card['operations']
        return []

    monkeypatch.setattr(rr, 'validate_card', inspect)
    # Phase ownership concerns the packaged scientific roles, not this fictional registry.
    monkeypatch.setattr(sfitter_workflow, 'validate_phase_ownership', lambda **kwargs: None)
    assert rr.validate_registry(root=roles.parent.parent) == []
    assert observed[PRODUCER] == [OPERATION]
    observed.clear()
    assert rr.validate_registry(document=document, root=roles.parent.parent) == []
    assert observed[PRODUCER] == []


def test_default_card_inventory_reads_signatures_once_and_records_parse_cost(monkeypatch, record_property):
    from ravel.workflow import operation_registration as registration
    original_read = registration.read_signatures
    calls = []

    def read(path):
        calls.append(path)
        return original_read(path)

    monkeypatch.setattr(registration, 'read_signatures', read)
    started = perf_counter()
    document = rr.registry_document()
    roles = rr.package_data_path('roles')
    prior = [rr.load(identity, document=document, roles_root=roles)
             for identity in sorted(document['roles'])]
    prior_seconds = perf_counter() - started
    prior_parses = len(calls)
    calls.clear()
    started = perf_counter()
    current = rr.all_cards()
    current_seconds = perf_counter() - started
    assert current == prior
    assert prior_parses == len(prior)
    assert len(calls) == 1
    record_property('role_count', len(current))
    record_property('signature_bytes', (roles.parent / 'operation_signatures.json').stat().st_size)
    record_property('prior_signature_parses', prior_parses)
    record_property('current_signature_parses', len(calls))
    record_property('prior_all_cards_seconds', prior_seconds)
    record_property('current_all_cards_seconds', current_seconds)


@pytest.mark.parametrize('inventory', [False, True])
def test_selected_dangling_signature_link_is_refused(selected, inventory):
    roles, _, _, _ = selected
    path = roles.parent / 'operation_signatures.json'
    path.unlink()
    path.symlink_to(roles.parent / 'synthetic-absent-signatures.json')
    with pytest.raises(ValueError):
        if inventory:
            rr.all_cards(roles_root=roles)
        else:
            rr.load(PRODUCER, roles_root=roles)


@pytest.mark.parametrize('present', [False, True])
def test_role_surface_owns_selected_registration_sources_even_when_absent(selected, tmp_path, monkeypatch, present):
    _, document, _, signatures = selected
    project = tmp_path / 'synthetic-source'
    data = project / 'src/ravel/data'
    write(data / 'roles/registry.json', document)
    signature_path = data / 'operation_signatures.json'
    helper_path = project / 'src/ravel/workflow/operation_registration.py'
    if present:
        write(signature_path, signatures)
        helper_path.parent.mkdir(parents=True, exist_ok=True)
        helper_path.write_text('"""Synthetic registration source."""\n')
    monkeypatch.setattr(rr, 'render', lambda *args, **kwargs: {})
    files = rr.owned_paths(project)
    assert files['src/ravel/data/operation_signatures.json'] == signature_path
    assert files['src/ravel/workflow/operation_registration.py'] == helper_path
    assert signature_path.is_file() is present
    assert helper_path.is_file() is present
