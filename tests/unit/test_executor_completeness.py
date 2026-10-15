"""Compute signatures and production cards must exhaust the executor table."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import production_executor as executor, role_registry

SIGNATURES = Path(executor.DATA).parent.parent / 'operation_signatures.json'
COMPUTE_KINDS = {'science-mode', 'lifecycle-stage', 'scoped-adapter'}
COMPUTE_EFFECTS = {'executes_native', 'generates_events', 'simulates_detector', 'runs_authored_code'}


def assert_complete(signatures, table, cards):
    """Independent census: operation identities come only from the supplied data."""
    required = {name for name, row in signatures.items()
                if row['implementation']['kind'] in COMPUTE_KINDS
                or COMPUTE_EFFECTS.intersection(row.get('effects', []))}
    assert required <= table['operations'].keys(), sorted(required - table['operations'].keys())
    hosts = table.get('host_operations', {})
    assert not required.intersection(hosts), 'compute cannot be classified as host records'
    assert not table['operations'].keys() & hosts.keys(), 'executor and host classifications overlap'
    assert signatures.keys() <= table['operations'].keys() | hosts.keys()
    for operation, reason in hosts.items():
        assert operation in signatures and isinstance(reason, str) and reason.strip() and '\n' not in reason
    production = {c['id']: c for c in cards if c['family'] == 'production'}
    for operation, role in table['operations'].items():
        assert role in production, (operation, role)
    for role, card in production.items():
        assert set(card['operations']) == {op for op, r in table['operations'].items() if r == role}, role


def test_current_signatures_have_complete_production_dispatch():
    signatures = json.loads(SIGNATURES.read_text())['operations']
    table, cards = executor.executors(), role_registry.all_cards()
    assert set(table['completeness_rule']['implementation_kinds']) == COMPUTE_KINDS
    assert set(table['completeness_rule']['effects']) == COMPUTE_EFFECTS
    assert_complete(signatures, table, cards)
    assert executor.completeness_errors(signatures=signatures, table=table, cards=cards) == []


def test_new_compute_signature_fails_until_mapped_in_temporary_data(tmp_path):
    signatures = json.loads(SIGNATURES.read_text())
    signatures['operations']['fictional-calculus'] = {
        'implementation': {'kind': 'science-mode', 'module': 'fictional.calculus'},
        'stages': [], 'effects': [], 'tools': []}
    path = tmp_path / 'signatures.json'
    path.write_text(json.dumps(signatures))
    operations = json.loads(path.read_text())['operations']
    table, cards = deepcopy(executor.executors()), role_registry.all_cards()
    with pytest.raises(AssertionError):
        assert_complete(operations, table, cards)
    assert any('fictional-calculus' in e for e in executor.completeness_errors(
        signatures=operations, table=table, cards=cards))
    table['operations']['fictional-calculus'] = 'calculation'
    next(c for c in cards if c['id'] == 'calculation')['operations'].append('fictional-calculus')
    assert_complete(operations, table, cards)
    assert executor.completeness_errors(signatures=operations, table=table, cards=cards) == []


@pytest.mark.parametrize('kind', sorted(COMPUTE_KINDS))
def test_compute_kind_cannot_hide_in_host_operations(kind):
    signatures = {'fictional-record': {'implementation': {'kind': kind}, 'effects': []}}
    table = {'operations': {}, 'host_operations': {'fictional-record': 'Writes a record.'}}
    assert any('fictional-record' in e for e in executor.completeness_errors(
        signatures=signatures, table=table, cards=[]))


@pytest.mark.parametrize('effect', sorted(COMPUTE_EFFECTS))
def test_compute_effect_requires_production_even_for_command_kind(effect):
    signatures = {'fictional-command': {'implementation': {'kind': 'command'}, 'effects': [effect]}}
    assert executor.completeness_errors(signatures=signatures,
                                       table={'operations': {}, 'host_operations': {}}, cards=[])


def test_nonproduction_role_and_card_drift_are_refused():
    table = {'operations': {'fictional-statistic': 'fictional-reader'}, 'host_operations': {}}
    cards = [{'id': 'fictional-reader', 'family': 'consult', 'operations': []},
             {'id': 'fictional-producer', 'family': 'production', 'operations': ['fictional-orphan']}]
    errors = executor.completeness_errors(signatures={}, table=table, cards=cards)
    assert any('fictional-reader' in e for e in errors)
    assert any('fictional-producer' in e for e in errors)


@pytest.mark.parametrize('reason', ['', ' ', None, 'First line.\nSecond line.'])
def test_host_record_requires_one_line_reason(reason):
    signatures = {'fictional-record': {'implementation': {'kind': 'command'}, 'effects': []}}
    errors = executor.completeness_errors(signatures=signatures,
        table={'operations': {}, 'host_operations': {'fictional-record': reason}}, cards=[])
    assert any('fictional-record' in e for e in errors)


def test_every_plan_template_node_is_routed_or_declared_outside_production():
    """The planner's own templates: each node seals to a role, is a host record or names no operation."""
    templates = sorted((Path(executor.DATA).parent.parent / 'plan_templates').glob('*.json'))
    assert templates
    table = executor.executors()
    for path in templates:
        nodes = [{'id': f'F-{i}', 'kind': node['kind'], 'operation': node['operation'], 'rung': node.get('rung')}
                 for i, node in enumerate(json.loads(path.read_text())['nodes'])]
        assert executor.plan_role_errors({'plan': {'nodes': nodes}}) == [], path.name
        for node in nodes:
            assert (node['operation'] is None or node['operation'] in table['operations']
                    or node['operation'] in table['host_operations']), (path.name, node)
