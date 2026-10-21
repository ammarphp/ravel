"""Synthetic journal joins exercise logic; they do not qualify a transport."""
from copy import deepcopy

import pytest

from ravel.controller import testing
from ravel.controller.authority import common
from ravel.controller.confine import host_rows as host
from ravel.controller.store import RunStore, JOURNAL
from ravel.workflow import transport_registry as tr
from test_p06_support import autonomous, operator_home  # noqa: F401


@pytest.fixture
def store(tmp_path, operator_home):
    autonomous()
    return RunStore.create(tmp_path / 'run', root=tmp_path / 'store')


def populate(store, *, omit=None, change=None):
    """Supply fictional records without replacing any production guard/validator."""
    inventory = {'kind': 'worker', 'backend': 'linux', 'equal': True, 'differences': [],
                 'mcp_observed': True, 'mcp_error': None, 'issuer_read_denied': True,
                 'issuer_replace_denied': True, 'tools': ['read'], 'declared_tools': ['read'],
                 'read_roots': ['/fictional/runtime'], 'writable': ['/fictional/output'],
                 'env_names': ['PATH'], 'network': 'none'}
    qualification = {key: 'fictional' for key in tr.QUALIFICATION_RECORD_KEYS}
    qualification.update(schema_version=1, kind=tr.QUALIFICATION_KIND,
        transport_id='fictional-worker', status='live_qualified', executable_sha256='a' * 64,
        declaration_sha256='b' * 64, probe_sha256='c' * 64,
        receipt={'path': '/fictional/receipt.json', 'sha256': 'd' * 64, 'digest': 'e' * 64},
        observed={'session_id': 'fictional-session', 'surface': {'ravel': ['read'], 'unexpected': []}},
        steps=[{'step': name, 'passed': True} for name in sorted(tr.QUALIFICATION_STEPS)])
    selection = {'transport_id': 'fictional-worker', 'probe_sha256': 'c' * 64,
                 'declaration_sha256': 'b' * 64}
    records = [
        ('code-identity', {'governed': True, 'kind': 'installed', 'label': None,
                           'writable_by_controller_user': False, 'symlinks': [], 'selectors': {}, 'problems': []}),
        ('restricted-source-policy', {'fictional': 'source pin'}),
        ('host-observation', {'source': 'controller', 'host_findings': ['fictional_finding'],
            'tripwire': {'declared': store.run_id, 'controller_process': True, 'mode': 'block'}}),
        (tr.QUALIFICATION_KIND, qualification),
        ('step-dispatch', {'step_id': 's1', 'node_id': 'n1', 'attempt': 1,
                           'selection': selection, 'admitted_tools': ['read']}),
        ('tool-inventory', deepcopy(inventory)),
        ('worker-session', {'run_id': store.run_id, 'step': 's1', 'attempt': 1,
                            'session_id': 'fictional-session', 'receipt_sha256': 'f' * 64,
                            'step_spec': {'id': 's1', 'parameters': {}}}),
        ('step-observation', {'step_id': 's1', 'node_id': 'n1', 'attempt': 1, 'status': 'ok',
                              'session_id': 'fictional-session', 'receipt_sha256': 'f' * 64,
                              'transport': 'fictional-worker', 'tool_inventory': inventory})]
    for kind, body in records:
        if kind == omit:
            continue
        if change:
            change(kind, body)
        store.append(kind, body)


def test_real_SW30_refusal_and_authenticated_check(store):
    populate(store)
    with testing.seams(False, controller=True):
        reader, _, _ = host.standing._snapshot(store)
        assert reader.check_binding() == []
        assert host._sources(reader) is not None
        assert common.scan(reader, host.KIND, host.SCHEMA) == []
        result = host.evidence(store)
        assert set(result) == set(host.ROWS) | {'SW30'}
        assert all(row['status'] == 'satisfied' for row in result.values())
        assert result['SW10']['evidence']['label'] == host.LABEL
        assert result['SW10']['evidence']['host_findings'] == ['fictional_finding']
        check = common.scan(store, host.KIND, host.SCHEMA)[0]
        assert all(row['evidence']['record'] == check['id'] for row in result.values())
        assert check['exception'] == 'SeamRefused'
        assert check['seams_enabled'] is False and check['owned'] is True
        assert check['sources']['source_digests']
        assert result['SW30']['evidence']['record'] == check['id']
        assert host.evidence(store) == result
        assert len(store.scan(host.KIND)) == 1


@pytest.mark.parametrize('missing', ['code-identity', 'restricted-source-policy', 'host-observation',
    'transport-qualification', 'tool-inventory', 'worker-session', 'step-dispatch', 'step-observation'])
def test_missing_source_never_gains_evidence(store, missing):
    populate(store, omit=missing)
    with testing.seams(False, controller=True):
        assert host.evidence(store) == {}
    assert store.scan(host.KIND) == []


@pytest.mark.parametrize('enabled,controller', [(True, True), (True, False), (False, False)])
def test_current_process_must_refuse_seams(store, enabled, controller):
    populate(store)
    with testing.seams(enabled, controller=controller):
        assert host.evidence(store) == {}
    assert store.scan(host.KIND) == []


@pytest.mark.parametrize('fault', ['host_mode', 'host_run', 'host_source', 'qualification_steps',
    'qualification_boolean', 'probe_mismatch', 'inventory_boolean', 'inventory_mismatch', 'admission'])
def test_malformed_and_unmatched_records_fail_closed(store, fault):
    def change(kind, body):
        if kind == 'host-observation':
            if fault == 'host_mode': body['tripwire']['mode'] = 'report'
            if fault == 'host_run': body['tripwire']['declared'] = 'another-run'
            if fault == 'host_source': body['source'] = 'worker'
        if kind == 'transport-qualification':
            if fault == 'qualification_steps': body['steps'] = [{'step': 'receipt_ok', 'passed': True}]
            if fault == 'qualification_boolean': body['observed'] = {}
        if kind == 'step-dispatch' and fault == 'probe_mismatch':
            body['selection']['probe_sha256'] = 'f' * 64
        if kind == 'step-observation':
            if fault == 'inventory_boolean': body['tool_inventory'] = {'kind': 'worker', 'equal': True}
            if fault == 'inventory_mismatch': body['tool_inventory']['env_names'] = ['UNADMITTED']
        if kind == 'code-identity' and fault == 'admission': body['governed'] = False
    populate(store, change=change)
    with testing.seams(False, controller=True):
        assert host.evidence(store) == {}
    assert store.scan(host.KIND) == []


def test_fresh_read_catches_same_length_edit_before_cached_offset(store):
    populate(store)
    store.head()
    path = store.root / JOURNAL
    raw = path.read_bytes()
    assert b'fictional_finding' in raw
    path.write_bytes(raw.replace(b'fictional_finding', b'fabricate_finding'))
    with testing.seams(False, controller=True):
        assert host.evidence(store) == {}


@pytest.mark.parametrize('wrong_parent', [False, True])
def test_derived_seat_joins_through_its_retained_acting_step(store, wrong_parent):
    def change(kind, body):
        if kind == 'step-dispatch':
            body.update(seat='review:critic:1', purpose='review')
        if kind == 'step-observation':
            body.update(step_id='derived-review', seat='review:critic:1')
        if kind == 'worker-session':
            body.update(step='derived-review', seat='review:critic:1', step_spec={
                'id': 'derived-review', 'parameters': {
                    'seat_of': 'wrong-parent' if wrong_parent else 's1', 'purpose': 'review'}})
    populate(store, change=change)
    with testing.seams(False, controller=True):
        rows = host.evidence(store)
    assert bool(rows) is (not wrong_parent)


def test_unissued_SW30_check_is_never_repaired_into_credit(store):
    populate(store)
    store.append(host.KIND, {'schema': host.SCHEMA, 'uid': 'forged', 'run_id': store.run_id,
                            'exception': 'SeamRefused', 'seams_enabled': False})
    with testing.seams(False, controller=True):
        assert host.evidence(store) == {}
    assert len(store.scan(host.KIND)) == 1


@pytest.mark.parametrize('wrong_parent', [False, True])
def test_actual_child_dispatch_checks_explicit_parent_against_retained_seat(store, wrong_parent):
    def change(kind, body):
        if kind == 'step-dispatch':
            body.update(step_id='derived-review',
                        parent_step='wrong-parent' if wrong_parent else 's1',
                        seat='review:critic:1', purpose='review')
        if kind == 'step-observation':
            body.update(step_id='derived-review', seat='review:critic:1')
        if kind == 'worker-session':
            body.update(step='derived-review', seat='review:critic:1', step_spec={
                'id': 'derived-review', 'parameters': {'seat_of': 's1', 'purpose': 'review'}})

    populate(store, change=change)
    with testing.seams(False, controller=True):
        rows = host.evidence(store)
    assert bool(rows) is (not wrong_parent)
    if wrong_parent:
        assert store.scan(host.KIND) == []
