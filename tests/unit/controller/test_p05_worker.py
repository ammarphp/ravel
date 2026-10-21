"""Private login state and inert SW40 provider confinement controls. No provider calls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_p05_support import sandboxed  # noqa: F401


def workspace(tmp_path):
    ws = (tmp_path / 'worker').resolve()
    for name in ('inputs', 'outputs', 'scratch'):
        (ws / name).mkdir(parents=True)
    return ws


def test_private_home_validates_owner_provided_file_metadata(tmp_path):
    from ravel.controller.confine.worker import private_home
    from ravel.workflow import sandbox
    ws = workspace(tmp_path)
    home = sandbox.cli_home_for(ws)
    home.mkdir(mode=0o700)
    login = home / '.credentials.json'
    login.write_text('opaque-owner-fixture')
    login.chmod(0o600)
    assert private_home(ws, home) == home
    with pytest.raises(ValueError):
        private_home(ws, tmp_path / 'login')
    login.chmod(0o644)
    with pytest.raises(ValueError):
        private_home(ws, home)
    login.chmod(0o600)
    linked = home / 'linked-login'
    linked.symlink_to(login)
    with pytest.raises(ValueError):
        private_home(ws, home)
    linked.unlink()
    os.link(login, linked)
    with pytest.raises(ValueError):
        private_home(ws, home)
    linked.unlink()
    assert private_home(ws, home) == home


def test_SW40_provider_profile_private_home_and_truthful_fallback(tmp_path, monkeypatch):
    from ravel.workflow import sandbox
    ws = workspace(tmp_path)
    login = tmp_path / 'login'
    login.mkdir()
    home = sandbox.cli_home_for(ws)
    home.mkdir(mode=0o700)
    profile = sandbox.macos_profile(ws, home=home, network='provider')
    assert '(allow file-write* (subpath ' + sandbox.quote(home) + '))' in profile
    assert str(login) not in profile
    assert 'remote tcp "*:443"' in profile
    monkeypatch.setattr(sandbox, 'linux_port_rules', lambda: False)
    assert sandbox.egress('provider', backend='linux') == 'unrestricted'
    monkeypatch.setattr(sandbox, 'linux_port_rules', lambda: True)
    assert sandbox.egress('provider', backend='linux') == 'tcp-443'
    command = sandbox.linux_command(ws, [sys.executable, '-c', 'pass'],
                                   read_paths=sandbox.runtime_paths([sys.executable]), home=home, network='provider')
    assert '--share-net' in command and str(login) not in command


def test_SW40_actual_inert_worker_private_home_and_nonprovider_network(tmp_path, sandboxed):
    from ravel.workflow import sandbox
    ws = workspace(tmp_path)
    login = tmp_path / 'login'
    login.mkdir()
    home = sandbox.cli_home_for(ws)
    home.mkdir(mode=0o700)
    program = r'''
import json, pathlib, socket, sys
pathlib.Path(sys.argv[1], 'canary').write_text('private')
checks = {'private_home_write': True}
for kind, args in [('udp', (socket.AF_INET, socket.SOCK_DGRAM))]:
 try:
  s=socket.socket(*args);s.close();checks[kind + '_denied']=False
 except PermissionError: checks[kind + '_denied']=True
try:
 s=socket.socket();s.settimeout(0.2)
 try: s.connect(('127.0.0.1', 9));checks['other_port_denied']=False
 finally: s.close()
except PermissionError: checks['other_port_denied']=True
except OSError: checks['other_port_denied']=False
print(json.dumps(checks))
'''
    argv = [sys.executable, '-I', '-S', '-B', '-c', program, str(home)]
    result = subprocess.run(sandbox.command(ws, argv, home=home, network='provider',
                             read_paths=sandbox.runtime_paths(argv)), cwd=ws,
                            env={'PATH': '/usr/bin:/bin', 'HOME': str(home)},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    checks = json.loads(result.stdout)
    assert checks['private_home_write'] is True
    if sandboxed == 'linux':
        # Legacy direct DNS capability remains; no datagram is sent by this test.
        assert checks['udp_denied'] is False
    if sandbox.egress('provider') == 'tcp-443':
        assert checks['other_port_denied'] is True
    else:
        assert sandbox.egress('provider') == 'unrestricted'
    assert (home / 'canary').read_text() == 'private'
    assert not (login / 'canary').exists()


@pytest.mark.parametrize('machine', ['x86_64', 'aarch64'])
def test_provider_seccomp_preserves_dns_and_labels_tcp_only_scope(machine):
    from ravel.workflow import sandbox
    arch, calls = sandbox.LINUX_SYSCALLS[machine]
    program = sandbox.linux_filter('provider', machine=machine)

    def evaluate(family, kind, protocol=0):
        words = {0: calls['socket'], 4: arch, 16: family, 24: kind, 32: protocol}
        pc, accumulator = 0, 0
        for _ in range(100):
            code, yes, no, value = program[pc]
            if code == 0x20:
                accumulator = words[value]
            elif code == 0x54:
                accumulator &= value
            elif code == 0x15:
                pc += yes if accumulator == value else no
            elif code == 0x35:
                pc += yes if accumulator >= value else no
            elif code == 0x06:
                return value
            else:
                raise AssertionError(code)
            pc += 1
        raise AssertionError('BPF failed to terminate')

    # Provider workers preserve socket creation for legacy DNS. Landlock restricts TCP
    # ports, never UDP or endpoint identity; evidence must not imply either restriction.
    for family in (1, 2, 10, 16):
        for kind in (1, 2, 3):
            assert evaluate(family, kind) == sandbox.SECCOMP_ALLOW


@pytest.mark.parametrize('egress', ['tcp-443', 'unrestricted'])
def test_worker_provider_evidence_labels_tcp_scope_and_unfiltered_dns(tmp_path, monkeypatch, egress):
    import importlib
    from types import SimpleNamespace
    module = importlib.import_module('ravel.controller.confine.probe')
    from ravel.workflow import sandbox
    ws = workspace(tmp_path)
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    monkeypatch.setattr(sandbox, 'command', lambda *args, **kwargs: ['/inert/not-executed'])
    monkeypatch.setattr(sandbox, 'egress', lambda *args: egress)
    seen = {'tools': [], 'mcp_observed': True, 'mcp_error': None,
            'writable': [], 'env_names': [], 'network': 'none'}
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=json.dumps(seen), stderr=''))
    evidence = module._worker({'workspace': str(ws), 'network': 'provider'})
    assert evidence['endpoint_restricted'] is False
    assert evidence['non_tcp_internet'] == 'unfiltered'
    assert evidence['name_resolution'] == 'direct DNS permitted; UDP unfiltered'
    if egress == 'tcp-443':
        assert evidence['egress_label'] == 'worker egress: any TCP 443 host'
        assert evidence['tcp_restriction'] == 'port-only'
    else:
        assert 'unrestricted' in evidence['egress_label']
        assert 'UDP unfiltered' in evidence['egress_label']


def test_worker_probe_excludes_only_names_its_own_interpreter_adds(tmp_path, monkeypatch):
    """A name only the measuring interpreter adds to an empty environment is not exposure; a name the
    boundary adds is still observed and refuses against the admitted set, and without the measurement
    nothing is excluded."""
    import importlib
    from types import SimpleNamespace
    module = importlib.import_module('ravel.controller.confine.probe')
    from ravel.workflow import sandbox
    ws = workspace(tmp_path)
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    monkeypatch.setattr(sandbox, 'command', lambda *args, **kwargs: ['/inert/not-executed'])
    given = {'PATH': '/usr/bin:/bin', 'HOME': str(ws / 'scratch'), 'LC_CTYPE': 'C.UTF-8'}
    seen = {'tools': [], 'mcp_observed': True, 'mcp_error': None, 'writable': [], 'network': 'none',
            'env_names': sorted([*given, 'FIXTURE_INTERPRETER_NAME', 'FIXTURE_BOUNDARY_NAME']),
            'interpreter_env_names': ['FIXTURE_INTERPRETER_NAME', 'LC_CTYPE']}
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs:
                        SimpleNamespace(returncode=0, stdout=json.dumps(seen), stderr=''))
    observed = module._worker({'workspace': str(ws), 'env': given})
    assert observed['env_names'] == sorted([*given, 'FIXTURE_BOUNDARY_NAME'])
    assert observed['interpreter_env_names'] == ['FIXTURE_INTERPRETER_NAME']
    admitted = {'tools': [], 'writable': [], 'env_names': sorted(given), 'network': 'none'}
    found = module.probe('worker', {'workspace': str(ws), 'env': given, 'admitted': admitted})
    assert {'field': 'env_names', 'unadmitted': ['FIXTURE_BOUNDARY_NAME']} in found['differences']
    assert found['equal'] is False
    del seen['interpreter_env_names']
    observed = module._worker({'workspace': str(ws), 'env': given})
    assert observed['env_names'] == sorted([*given, 'FIXTURE_INTERPRETER_NAME', 'FIXTURE_BOUNDARY_NAME'])
    assert observed['interpreter_env_names'] == []
