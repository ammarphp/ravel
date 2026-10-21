"""Private creation, supplied classification custody and endpoint admission controls."""
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from ravel.controller import entry, graph
from ravel.controller.authority import mode
from ravel.controller.sink import render
from ravel.controller.store import RunStore, RUN_MARKER
from ravel.workflow import private_files, provider_policy as policy, sandbox, transport_registry as tr
from test_p06_support import autonomous, new_store, operator_home, ownership  # noqa: F401


@pytest.fixture
def permissive():
    previous = os.umask(0)
    try:
        yield
    finally:
        os.umask(previous)


def test_run_and_marker_private_from_creation(tmp_path, permissive, monkeypatch):
    created = []
    original = os.mkdir
    def observe(path, mode=0o777, **kwargs):
        result = original(path, mode, **kwargs)
        created.append((Path(path), stat.S_IMODE(Path(path).stat().st_mode)))
        return result
    monkeypatch.setattr(os, 'mkdir', observe)
    store = RunStore.create(tmp_path / 'runs' / 'new', root=tmp_path / 'store')
    assert all(bits == 0o700 for path, bits in created if path.is_relative_to(tmp_path))
    assert stat.S_IMODE((store.run_dir / RUN_MARKER).stat().st_mode) == 0o600


def test_generated_bytes_private_before_first_write(tmp_path, permissive, monkeypatch):
    opened = []
    original = os.open
    def observe(path, flags, mode=0o777, **kwargs):
        fd = original(path, flags, mode, **kwargs)
        if flags & os.O_CREAT:
            opened.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return fd
    monkeypatch.setattr(os, 'open', observe)
    render._write(tmp_path / 'delivery' / 'artifacts' / 'result.txt', b'inert')
    assert opened and all(bits == 0o600 for bits in opened)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in (
        tmp_path / 'delivery', tmp_path / 'delivery' / 'artifacts'))


@pytest.mark.parametrize('bits', [0o400, 0o600, 0o640, 0o644, 0o666])
def test_supplied_copy_never_widens_source_permissions(tmp_path, permissive, bits):
    source = tmp_path / 'source.txt'
    source.write_bytes(b'inert supplied bytes')
    source.chmod(bits)
    run = tmp_path / 'run'; run.mkdir(mode=0o700)
    row = {'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
           'data_classification': policy.RESTRICTED, 'restricted': True}
    staged = graph.stage_supplied_inputs(run, [row])
    target = run / 'inputs' / source.name
    assert target.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(target.stat().st_mode) == bits & 0o600
    assert stat.S_IMODE(source.stat().st_mode) == bits
    assert staged[0]['data_classification'] == policy.RESTRICTED and staged[0]['restricted']


def test_private_writes_refuse_links_and_copies_refuse_special_files(tmp_path):
    target = tmp_path / 'ordinary'; target.write_bytes(b'original')
    linked = tmp_path / 'link'; linked.symlink_to(target)
    with pytest.raises(ValueError, match='link'):
        private_files.write(linked, b'replacement')
    assert target.read_bytes() == b'original'
    pipe = tmp_path / 'pipe'; os.mkfifo(pipe)
    with pytest.raises(ValueError, match='ordinary'):
        private_files.copy(pipe, tmp_path / 'copy')


def test_supplied_intake_defaults_restricted_and_freezes_exact_policy(tmp_path):
    source = tmp_path / 'sample.txt'; source.write_bytes(b'inert')
    rows = entry._supplied([str(source)], tmp_path)
    assert rows[0]['restricted'] is True
    assert rows[0]['data_classification'] == policy.RESTRICTED
    frozen = mode._provider_policy(tmp_path / 'run', None, rows)
    assert frozen['record']['declared'] is True
    assert frozen['record']['data_classification'] == policy.RESTRICTED
    assert frozen['policy_sha256'] == policy.digest(frozen['record'])


def test_programmatic_supplied_rows_also_default_restricted(tmp_path):
    source = tmp_path / 'sample.txt'; source.write_bytes(b'inert')
    row = {'kind': 'file', 'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    store = entry.start(b'A fictional supplied calculation', channel='terminal',
                        rundir=tmp_path / 'run', root=tmp_path / 'store', supplied=[row])
    pinned = store.latest('supplied')['record']['inputs'][0]
    assert pinned['restricted'] and pinned['data_classification'] == policy.RESTRICTED


def test_explicit_project_default_is_respected_and_cannot_be_widened(tmp_path):
    source = tmp_path / 'sample.txt'; source.write_bytes(b'inert')
    route = tr.load('http-responses')
    value = {'level': 'restricted', 'allowed_providers': [
        {'transport_id': route['id'], 'account_class': policy.account_class(route)}]}
    private_files.write(tmp_path / policy.PROJECT_CONFIG, json.dumps(value).encode())
    rows = entry._supplied([str(source)], tmp_path)
    assert rows[0]['data_classification'] == value
    with pytest.raises(entry.EntryError, match='widen'):
        entry._supplied([str(source)], tmp_path, data_classification={'level': 'public', 'allowed_providers': []})


def test_input_classifications_intersect_provider_clearances(tmp_path, monkeypatch):
    route = tr.load('http-responses')
    entry_allowed = {'transport_id': route['id'], 'account_class': policy.account_class(route)}
    value = {'level': 'restricted', 'allowed_providers': [entry_allowed]}
    run = tmp_path / 'run'
    pins = [{'pin': {'path': 'inert', 'data_classification': value}}]
    assert policy.start(run, input_pins=pins)['data_classification'] == value
    assert policy.admission(run, route, entry_allowed['account_class'], input_pins=pins)['admitted_entry'] == entry_allowed
    with pytest.raises(policy.PolicyRefused, match='refuses transport'):
        other = tr.load('http-anthropic')
        policy.admission(run, other, policy.account_class(other), input_pins=pins)
    with pytest.raises(policy.PolicyRefused, match='widen'):
        policy.validate_start(value, [{'data_classification': policy.RESTRICTED}])


def test_cli_classification_uses_existing_schema(tmp_path):
    path = tmp_path / 'policy.json'; path.write_text(json.dumps(policy.RESTRICTED))
    args = entry._drive_parser('inert').parse_args(['--input', 'sample.txt', '--input-classification', str(path)])
    assert entry._input_policy(args) == policy.RESTRICTED
    path.write_text('{"level":"public","allowed_providers":null}')
    with pytest.raises(entry.EntryError, match='classification'):
        entry._input_policy(args)


def test_real_mode_freezes_supplied_pin_and_child_cannot_remove_clearance(operator_home, ownership, tmp_path):
    autonomous()
    store = new_store(tmp_path)
    store.append('supplied', {'inputs': [{'path': 'inert-source', 'data_classification': policy.RESTRICTED,
                                        'restricted': True}]})
    contract = {'prompt': 'Compute an inert fictional quantity from supplied data.'}
    frozen = mode.freeze_mode(store, contract, project=tmp_path)
    assert frozen['provider_policy']['record']['data_classification'] == policy.RESTRICTED
    assert frozen['provider_policy']['record']['declared'] is True
    child = new_store(tmp_path, 'child')
    inherited = mode.freeze_child(child, store, contract)
    assert inherited['provider_policy'] == frozen['provider_policy']


def test_unclassified_child_input_cannot_inherit_public_clearance(operator_home, ownership, tmp_path):
    autonomous()
    parent = new_store(tmp_path)
    contract = {'prompt': 'Compute an inert fictional quantity.'}
    mode.freeze_mode(parent, contract, project=tmp_path)
    child = new_store(tmp_path, 'child')
    child.append('supplied', {'inputs': [{'data_classification': policy.RESTRICTED}]})
    with pytest.raises(policy.PolicyRefused, match='input classification'):
        mode.freeze_child(child, parent, contract)
    assert child.scan('mode') == []


@pytest.mark.parametrize('backend,ports,expected', [('macos', True, 'tcp-443'),
                                                  ('linux', True, 'tcp-443'),
                                                  ('linux', False, 'unrestricted')])
def test_provider_port_scope_never_masquerades_as_endpoint_scope(monkeypatch, backend, ports, expected):
    monkeypatch.setattr(sandbox, 'available', lambda: backend)
    monkeypatch.setattr(sandbox, 'linux_port_rules', lambda: ports)
    details = sandbox.egress_details('provider')
    assert details['class'] == expected
    assert details['destination_scope'] == 'any' and details['endpoint_confinement'] is False
    assert details['udp'] == ('unfiltered' if backend == 'linux' else 'none')
    for level in ('internal', 'restricted'):
        with pytest.raises(sandbox.EndpointConfinementRefused, match='qualified endpoint-confined gateway'):
            sandbox.require_provider_egress({'data_classification': {'level': level}})
    assert sandbox.require_provider_egress({'data_classification': {'level': 'public'}}) == details


def test_uncleared_worker_refuses_before_probe_credentials_or_process(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker, broker
    from ravel.workflow.transports import cli_worker
    run, ws = tmp_path / 'run', tmp_path / 'workspace'
    route = tr.load('claude-cli-worker')
    value = {'level': 'restricted', 'allowed_providers': [
        {'transport_id': route['id'], 'account_class': policy.account_class(route)}]}
    policy.start(run, data_classification=value)
    monkeypatch.setattr(agent_worker, '_validate', lambda spec: spec)
    monkeypatch.setattr(agent_worker, 'workspace', lambda *a: ws)
    monkeypatch.setattr(cli_worker, '_card', lambda *a: {})
    monkeypatch.setattr(cli_worker, 'current_probe', lambda *a: pytest.fail('probe or credential path reached'))
    monkeypatch.setattr(cli_worker, '_cli_home', lambda *a: pytest.fail('credentials copied'))
    with pytest.raises(cli_worker.LaunchRefused, match='provider_endpoint_confinement_unavailable') as held:
        cli_worker.prepare_launch(run, {'node_id': 'inert', 'attempt': 1, 'inputs': []}, ws,
                                  selection={'transport_id': route['id']})
    assert 'provider_endpoint_confinement' in held.value.missing


def test_delivery_receipt_retains_exact_egress_and_resource_scope():
    from ravel.controller.sink import receipts
    details = {'class': 'tcp-443', 'destination_scope': 'any', 'endpoint_confinement': False,
               'udp': 'unfiltered', 'qualified_provider_endpoints': []}
    resource_scope = {'aggregate_memory_mib': 'unsupported', 'disk_mib': 'unsupported'}
    ev = {'authority': {}, 'wms': [], 'launches': [
        {'id': 'inert', 'step_id': 'step', 'attempt': 1, 'backend': 'bwrap', 'kind': 'confined',
         'label': None, 'exit_status': 0, 'errors': [], 'resource_enforcement': resource_scope,
         'limits_enforced': {'memory_mib': 'per-process address-space only (not aggregate RSS)'}}],
          'observations': [{'step_id': 'step', 'attempt': 1, 'transport': 'inert', 'provider_egress': details}]}
    found = receipts.confinement(ev)
    assert found['provider_egress'][0]['egress'] == details
    assert found['launches'][0]['resource_enforcement'] == resource_scope


def test_current_source_instruction_and_directory_surface():
    root = Path(__file__).resolve().parents[3]
    done = subprocess.run([sys.executable, 'scripts/run.py', 'ravel.validation.check_agent_surface'],
                          cwd=root, capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
