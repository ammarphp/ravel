"""Inert resource admission controls; no large allocation or child is executed."""
import pytest

from ravel.controller.confine import launcher
from ravel.controller.confine.resource_mechanisms import ResourceMechanism, resource_scopes


@pytest.mark.parametrize('key', ['aggregate_memory_mib', 'processes', 'disk_mib'])
@pytest.mark.parametrize('backend', ['bwrap', 'sandbox-exec', 'auto'])
def test_aggregate_requests_hold_before_preparation_effects(monkeypatch, key, backend):
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported limits must hold before probing, copying or launching')
    monkeypatch.setattr(launcher, 'qualify', forbidden)
    monkeypatch.setattr(launcher, '_materialize', forbidden)
    monkeypatch.setattr(launcher.envmod, 'scrub', forbidden)
    # Models a descendant allocation or disk write including scratch/retained attempts.
    # The inert argv must never run, regardless of available or failed sampling.
    monkeypatch.setattr(launcher, 'survivors', forbidden)
    with pytest.raises(launcher.LaunchHeld) as caught:
        launcher.popen({'argv': ['inert-descendant-or-scratch-writer'],
                        'limits': {key: 1}, 'backend': backend})
    assert caught.value.reason == 'resource_limit_unsupported'
    assert key in caught.value.detail
    assert 'failed attempts' in caught.value.detail
    assert 'pre-materialization input copies' in caught.value.detail
    assert 'receipt headroom on every filesystem' in caught.value.detail


@pytest.mark.parametrize('kind', [launcher.CONFINED, launcher.UNCONFINED])
@pytest.mark.parametrize('key', ['aggregate_memory_mib', 'disk_mib', 'processes'])
def test_mutated_plan_holds_before_journal_materialization_or_child(monkeypatch, kind, key):
    def forbidden(*args, **kwargs):
        pytest.fail('no launch effect permitted')
    plan = launcher.Plan(kind, {}, ['inert'], backend='linux', limits={key: 1})
    monkeypatch.setattr(launcher, '_journal', forbidden)
    monkeypatch.setattr(launcher, '_materialize', forbidden)
    with pytest.raises(launcher.LaunchHeld, match='resource_limit_unsupported'):
        launcher.start(plan, popen=forbidden)


def test_legacy_memory_metadata_never_claims_aggregate_guarantee():
    assert launcher._enforced('linux', {'memory_mib': 1}) == {
        'memory_mib': ResourceMechanism.LINUX_RLIMIT_AS.value}
    assert resource_scopes(launcher._enforced('linux', {'memory_mib': 1})) == {
        'memory_mib': 'per-process address-space only (not aggregate RSS)'}
    assert launcher._enforced('macos', {'memory_mib': 1}) == {'memory_mib': False}
    assert launcher._enforced(None, {'memory_mib': 1}) == {'memory_mib': False}
    for backend in ('linux', 'macos', None):
        limits = {name: 1 for name in launcher.AGGREGATE_LIMIT_KEYS}
        assert all(value is False for value in launcher._enforced(backend, limits).values())
    metadata = launcher._resource_enforcement()
    assert metadata['aggregate_sampling'] is False
    assert metadata['filesystem_receipt_headroom'] == 'not reserved'
    assert all(metadata[key] == 'unsupported' for key in launcher.AGGREGATE_LIMIT_KEYS)
    assert metadata['status'] == 'partial'
    assert metadata['label'] == launcher.RESOURCE_LABEL
    assert metadata['reason'] == 'generic_backend_has_no_aggregate_boundary_or_headroom_reservation'


@pytest.mark.parametrize('bad', [0, -1, True, 1.5, '10'])
def test_disk_limit_is_recognized_and_validated(bad):
    with pytest.raises(launcher.ConfinementRefused, match='disk_mib must be a positive integer'):
        launcher._limits({'disk_mib': bad})


def test_unconfined_launch_child_umask_is_private(monkeypatch):
    monkeypatch.setattr(launcher, '_issuer_plan', lambda plan: None)
    monkeypatch.setattr(launcher, '_journal', lambda *args: None)
    calls = []
    class Child:
        pass
    def inert(*args, **kwargs):
        calls.append(kwargs)
        return Child()
    plan = launcher.Plan(launcher.UNCONFINED, {}, ['inert'])
    launcher.start(plan, popen=inert)
    assert calls[0]['umask'] == 0o077
    assert plan.record['resource_enforcement']['label'] == launcher.RESOURCE_LABEL
    with pytest.raises(launcher.ConfinementRefused, match='umask must be 0077'):
        launcher.start(plan, popen=inert, umask=0o002)
    assert len(calls) == 1
