"""Resource requests reach their enforcing action; admission never claims a quota."""
from importlib import import_module
from types import SimpleNamespace

import pytest

from ravel.controller.confine import launcher, resource_admission as resources
from ravel.controller.authority import operator


@pytest.mark.parametrize('limit', ['aggregate_memory_mib', 'processes', 'disk_mib'])
@pytest.mark.parametrize('nested', [False, True])
def test_every_unsupported_request_reaches_refusal(limit, nested):
    launch = {'limits': {limit: 1}} if nested else {limit: 1}
    with pytest.raises(launcher.LaunchHeld) as held:
        resources.launch_limits(launch, 60)
    assert held.value.reason == 'resource_limit_unsupported'
    assert limit in held.value.detail


def test_supported_request_keeps_exact_ceiling_and_refuses_widening():
    assert resources.launch_limits({'memory_mib': 64, 'limits': {'cpus': 2, 'wall_seconds': 20}}, 30) == {
        'cpus': 2, 'wall_seconds': 20, 'memory_mib': 64}
    with pytest.raises(ValueError, match='reserved wall'):
        resources.launch_limits({'wall_seconds': 31}, 30)
    with pytest.raises(ValueError, match='conflicting'):
        resources.launch_limits({'memory_mib': 32, 'limits': {'memory_mib': 64}}, 30)
    with pytest.raises(launcher.LaunchHeld, match='retained_disk_bytes'):
        resources.launch_limits({}, 30, retained_disk_bytes=100)


@pytest.mark.parametrize('limit', ['aggregate_memory_mib', 'processes', 'disk_mib'])
def test_real_step_preflight_refuses_before_authority_probe_or_output_creation(tmp_path, monkeypatch, limit):
    graph = import_module('ravel.controller.step.graph')
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported request reached an effect')
    authority = SimpleNamespace(effective_bounds=lambda _: {'budgets': {}})
    monkeypatch.setattr(graph, 'module', lambda _: authority)
    monkeypatch.setattr(graph, '_authorize', forbidden)
    monkeypatch.setattr(graph, '_probe', forbidden)
    step = {'id': 'bounded.launch', 'kind': 'operate', 'operation': 'inert', 'inputs': [], 'outputs': [],
            'parameters': {'launch': {'argv': ['inert'], limit: 1}}}
    with pytest.raises(graph.StepHold) as held:
        graph._launch_preflight({'reservation': {'amounts': {'wall_seconds': 60}}}, object(),
                                {'run_dir': str(tmp_path)}, tmp_path, step, None, [], [], {})
    assert held.value.reason == 'resource_limit_unsupported'
    assert not list(tmp_path.iterdir())


def test_admission_accounts_existing_failed_attempts_and_all_copy_representations(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    old = run / 'steps/previous/attempts/2/failed'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'previous')
    monkeypatch.setattr(resources.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10 << 20))
    result = resources.acquisition_admission(run, 100, input_bytes=10)
    assert result['existing_bytes'] == 8
    assert result['copy_population'] == ['acquisition', 'adoption', 'downstream_input']
    assert result['copy_ceiling_bytes'] == 310
    assert result['projected_retained_bytes'] == 8 + 310 + resources.RECEIPT_MARGIN_BYTES
    assert result['headroom_reserved'] is False
    assert 'no quota' in result['scope']
    with pytest.raises(ValueError, match='retained_disk_budget_exhausted'):
        resources.acquisition_admission(run, 100, input_bytes=10,
            retained_disk_bytes=result['projected_retained_bytes'] - 1)
    assert resources.acquisition_admission(run, 100, input_bytes=10,
        retained_disk_bytes=result['projected_retained_bytes'])['retained_disk_bytes'] == result['projected_retained_bytes']


def test_free_space_floor_and_receipt_margin_are_checked_before_effect(tmp_path, monkeypatch):
    required = 3 * 100 + resources.RECEIPT_MARGIN_BYTES + 50
    monkeypatch.setattr(resources.shutil, 'disk_usage', lambda _: SimpleNamespace(free=required - 1))
    with pytest.raises(ValueError, match='acquisition_storage_exhausted'):
        resources.acquisition_admission(tmp_path, 100, free_floor_bytes=50)
    monkeypatch.setattr(resources.shutil, 'disk_usage', lambda _: SimpleNamespace(free=required))
    result = resources.acquisition_admission(tmp_path, 100, free_floor_bytes=50)
    assert result['filesystems'][0]['required_free_bytes'] == required
    assert not list(tmp_path.iterdir())


def test_operator_retention_ceiling_is_optional_typed_and_default_unbounded():
    config = operator.default_config()
    assert config['budgets']['retained_disk_bytes'] is None
    config['budgets']['retained_disk_bytes'] = 100
    assert operator.validate(config)['budgets']['retained_disk_bytes'] == 100
    for bad in (-1, True, 1.5, '100'):
        config['budgets']['retained_disk_bytes'] = bad
        with pytest.raises(ValueError, match='retained_disk_bytes'):
            operator.validate(config)


@pytest.mark.parametrize('boundary', ['prepare', 'start'])
def test_operator_storage_requirement_is_checked_by_the_actual_launcher(monkeypatch, boundary):
    monkeypatch.setattr(launcher.runs, 'operator_settings',
                        lambda: {'budgets': {'retained_disk_bytes': 1024}})
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported operator resource requirement reached an effect')
    monkeypatch.setattr(launcher, 'qualify', forbidden)
    monkeypatch.setattr(launcher, '_issuer_plan', forbidden)
    monkeypatch.setattr(launcher, '_journal', forbidden)
    monkeypatch.setattr(launcher, '_materialize', forbidden)
    with pytest.raises(launcher.LaunchHeld) as held:
        if boundary == 'prepare':
            launcher.prepare({'argv': ['inert'], 'limits': {}})
        else:
            launcher.start(launcher.Plan(launcher.UNCONFINED, {}, ['inert']), popen=forbidden)
    assert held.value.reason == 'resource_limit_unsupported'
    assert 'retained_disk_bytes' in held.value.detail


def test_source_reader_rechecks_capacity_at_the_enforcing_action(tmp_path, monkeypatch):
    from ravel.controller.routes.analysis import execution
    from ravel.controller.step import host_operations
    monkeypatch.setattr(host_operations, 'admit', lambda *_, **__: 'host-decision')
    calls = []
    def refuse(store, step, run_dir, **kwargs):
        calls.append(kwargs)
        raise ValueError('acquisition_storage_exhausted')
    monkeypatch.setattr(resources, 'admit_acquisition', refuse)
    step = {'id': 'acquire.data'}
    output = tmp_path / 'steps/acquire.data/attempts/1/outputs'
    prepared = {'output_root': str(output), 'capsule': {'input_digests': {'declared-input': 'digest'}}}
    with pytest.raises(ValueError, match='acquisition_storage_exhausted'):
        execution.launch_acquisition(SimpleNamespace(path=lambda *p: tmp_path.joinpath(*p)),
                                     step, {'run_dir': str(tmp_path)}, prepared,
                                     inventory=lambda _: pytest.fail('no acquired output may exist'))
    assert calls[0]['phase'] == 'start'
    assert calls[0]['input_paths'] == {'declared-input': 'digest'}
    assert not output.exists()


def test_concurrent_copy_batches_cannot_both_spend_remaining_storage(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from ravel.controller.step import custody, services
    from test_p04_support import FakeStore
    run = tmp_path / 'run'; run.mkdir()
    source = run / 'source'; source.write_bytes(b'x' * 200)
    store = FakeStore(tmp_path / 'store', run_dir=run)
    store.append('mode', {'synthetic': True})
    ceiling = 200 + 300 + resources.RECEIPT_MARGIN_BYTES
    authority = SimpleNamespace(frozen=lambda *_, **__: {},
        effective_bounds=lambda _: {'budgets': {'retained_disk_bytes': ceiling}})
    monkeypatch.setattr(services, 'module', lambda _: authority)
    def copy(index):
        try:
            custody._copy(store, run_dir=run, step={'id': 'copy-' + str(index)}, attempt=1,
                rows=[('outputs/file', source, custody._sha(source), 'artifact')], card=None,
                producer={}, quantities={}, inputs_custody=[])
            return 'copied'
        except services.StepHold as exc:
            return exc.reason
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(copy, (1, 2)))
    assert sorted(results) == ['copied', 'copy_storage_refused']
    assert len(store.scan('custody')) == 1
    assert resources.retained_bytes(run) == 400


def test_default_resource_scope_reaches_the_human_delivery_label():
    from ravel.controller.sink import receipts, render
    scope = launcher._resource_enforcement()
    ev = {'authority': {}, 'wms': [], 'observations': [], 'launches': [
        {'id': 'finished', 'step_id': 'generic', 'attempt': 1, 'backend': 'bwrap', 'kind': 'confined',
         'label': None, 'exit_status': 0, 'errors': [], 'resource_enforcement': scope}]}
    confinement = receipts.confinement(ev)
    receipt = {'run_id': 'resource-display', 'label': 'qualified', 'architecture_complete': False,
               'architecture_predicates': {}, 'labels': [], 'confinement': confinement}
    classification = {'declared': [], 'open': [], 'extras': [], 'excluded': [], 'excluded_count': 0}
    text = render.markdown(receipt, classification, SimpleNamespace())
    assert launcher.RESOURCE_LABEL in text
    assert 'Aggregate memory, process count, retained disk and receipt headroom are unprotected' in text
    assert confinement['launches'][0]['resource_enforcement'] == scope
