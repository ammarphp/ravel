"""Actual prepare records compose through both native readers and the real ledger.

Qualification is inert: these tests establish evidence-schema composition, not
operating-system enforcement. No capsule or child is started.
"""
from copy import deepcopy
import json

import pytest

from ravel.controller import ledger
from ravel.controller.confine import launcher
from ravel.controller.confine.resource_mechanisms import ResourceMechanism
from ravel.controller.step import native_checks, native_rows
from ravel.controller.store import RunStore


ABSENCE_ROWS = {'G10', 'G14', 'SW27', 'SW17', 'SW34', 'SW35', 'SW36', 'SW37', 'SW38', 'SW24'}
TARGET_ROWS = ABSENCE_ROWS | {'E06'}


@pytest.fixture
def prepare_record(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('evidence composition must not start or materialize a capsule')
    monkeypatch.setattr(launcher, '_materialize', forbidden)
    monkeypatch.setattr(launcher, 'start', forbidden)
    monkeypatch.setattr(launcher, 'machine_grant', lambda: [0])
    monkeypatch.setattr(launcher, '_issuer_plan', lambda plan: None)
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {
        'backend': launcher.BACKENDS[kind], 'confirmed': True, 'checks': ['inert-schema-qualification']})

    def prepare(backend, extra=None):
        monkeypatch.setattr(launcher.worker_sandbox, 'available', lambda: backend)
        plan = launcher.prepare({
            'argv': ['inert-resource-composition'],
            'env': launcher.envmod.capsule_from({}),
            'backend': launcher.BACKENDS[backend],
            'limits': {'cpus': 1, 'wall_seconds': 30, **(extra or {})},
        })
        # Exercise the producer's actual wire record; no hand-written enforcement fixture.
        return json.loads(json.dumps(plan.record))
    return prepare


def materialised_store(tmp_path):
    store = RunStore('native-resource-composition', root=tmp_path / 'store')
    ledger.materialise(store, 'intake', {'run_id': store.run_id})
    ledger.materialise(store, 'plan', {'plan': {'steps': [{
        'id': 'native.resources', 'kind': 'operate', 'launch': True,
        'obligations': sorted(TARGET_ROWS),
    }]}})
    ledger.materialise(store, 'dispatch', {
        'step': 'native.resources', 'seat': 'native.resources', 'seat_kind': 'launch',
        'step_kind': 'operate', 'attempt': 1,
    })
    assert TARGET_ROWS <= {row['id'] for row in ledger.current(store)}
    return store


def observe(store, plan):
    started = store.append('native-resource-started', {'plan': plan})
    finish = {'exit_status': 0, 'timed_out': False, 'confinement': {'errors': []}}
    finished = store.append('native-resource-finished', {'started': started, **finish})
    launch = {'journal_id': started, 'finished_id': finished, 'backend': plan['backend'],
              'plan': plan, **finish}
    reservation = {'amounts': {'core_hours': 30 / 3600}}
    reservation['record_id'] = store.append('budget-reservation', deepcopy(reservation))
    absence = native_rows.path_absence(launch)
    confinement = native_checks.confinement_rows(launch, reservation, {
        'kind': 'launch', 'equal': True, 'differences': []})
    evaluations = {**absence, **confinement}
    for instance in ledger.current(store):
        row = evaluations.get(instance['id'])
        if row and instance['id'] in TARGET_ROWS:
            ledger.record(store, instance['entry'], row['status'], row['evidence'])
    return absence, confinement


@pytest.mark.parametrize(('backend', 'extra', 'cpu'), [
    ('linux', {'memory_mib': 128}, ResourceMechanism.LINUX_CPU_AFFINITY),
    ('macos', {}, ResourceMechanism.COOPERATIVE_THREAD_ENVIRONMENT),
])
def test_prepare_to_both_readers_to_protected_ledger(tmp_path, prepare_record, backend, extra, cpu):
    plan = prepare_record(backend, extra)
    assert plan['limits_enforced']['cpus'] == cpu.value
    if backend == 'linux':
        assert plan['limits_enforced']['memory_mib'] == ResourceMechanism.LINUX_RLIMIT_AS.value
        assert plan['limit_scopes']['memory_mib'] == 'per-process address-space only (not aggregate RSS)'
    else:
        assert plan['limit_scopes']['cpus'] == 'thread environment (cooperative)'
    store = materialised_store(tmp_path)
    absence, confinement = observe(store, plan)
    assert set(absence) == ABSENCE_ROWS
    assert confinement['E06']['status'] == 'satisfied'
    targets = [row for row in ledger.current(store) if row['id'] in TARGET_ROWS]
    assert {row['id'] for row in targets} == TARGET_ROWS
    assert all(row['status'] == ('satisfied' if row['id'] == 'E06' else 'not_applicable')
               and row['evidence']['record'] for row in targets)
    assert ledger.verify(store)['verified'] is True


@pytest.mark.parametrize('backend', ['linux', 'macos'])
@pytest.mark.parametrize('limit', ['aggregate_memory_mib', 'processes', 'disk_mib'])
def test_unsupported_aggregate_never_prepares_or_closes_rows(tmp_path, prepare_record, backend, limit):
    with pytest.raises(launcher.LaunchHeld) as held:
        prepare_record(backend, {limit: 1})
    assert held.value.reason == 'resource_limit_unsupported'
    plan = prepare_record(backend)
    plan['limits'][limit] = 1
    plan['limits_enforced'][limit] = ResourceMechanism.LINUX_RLIMIT_AS.value
    store = materialised_store(tmp_path)
    absence, confinement = observe(store, plan)
    assert absence == {} and 'E06' not in confinement
    assert all(row['status'] == 'pending' for row in ledger.current(store) if row['id'] in TARGET_ROWS)


@pytest.mark.parametrize('damage', ['missing', 'unknown', 'prose', 'backend', 'none', 'list', 'false', 'extra'])
def test_malformed_resource_evidence_never_reaches_ledger_credit(tmp_path, prepare_record, damage):
    plan = prepare_record('linux', {'memory_mib': 128})
    if damage == 'missing':
        del plan['limits_enforced']['memory_mib']
    if damage == 'unknown':
        plan['limits_enforced']['cpus'] = 'unregistered-resource-mechanism'
    if damage == 'prose':
        plan['limits_enforced']['memory_mib'] = 'per-process address-space only (not aggregate RSS)'
    if damage == 'backend':
        plan['limits_enforced']['cpus'] = ResourceMechanism.COOPERATIVE_THREAD_ENVIRONMENT.value
    if damage == 'none':
        plan['limits_enforced'] = None
    if damage == 'list':
        plan['limits_enforced'] = []
    if damage == 'false':
        plan['limits_enforced']['cpus'] = False
    if damage == 'extra':
        plan['limits_enforced']['extra'] = 'claimed'
    store = materialised_store(tmp_path)
    absence, confinement = observe(store, plan)
    assert absence == {} and 'E06' not in confinement
    assert all(row['status'] == 'pending' for row in ledger.current(store) if row['id'] in TARGET_ROWS)
