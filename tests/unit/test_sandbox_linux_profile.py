"""The Linux worker profile: system-call filter, read-only namespace and denial probe.

These controls build and interpret the profile; none of them launches a namespace.
The real launch is exercised by the worker suites wherever the host can confine.
"""
import errno
import json
import struct
import subprocess
import sys

import pytest

from ravel.workflow import sandbox

X86_64, AARCH64, I386 = 0xC000003E, 0xC00000B7, 0x40000003
EPERM = sandbox.SECCOMP_REFUSE
AF_UNIX, AF_INET, AF_INET6, AF_NETLINK = 1, 2, 10, 16


def decide(program, *, architecture, number, first=0):
    """Interpret the classic-BPF rows on one system call, as the kernel does."""
    data = struct.pack('<IIQ6Q', number, architecture, 0, first, 0, 0, 0, 0, 0)
    accumulator, index = 0, 0
    for _ in range(len(program) + 1):
        code, when_true, when_false, value = program[index]
        if code == 0x20:
            accumulator = struct.unpack_from('<I', data, value)[0]
            index += 1
        elif code == 0x15:
            index += 1 + (when_true if accumulator == value else when_false)
        elif code == 0x35:
            index += 1 + (when_true if accumulator >= value else when_false)
        elif code == 0x06:
            return value
        else:
            raise AssertionError(f'unexpected instruction {code:#x}')
    raise AssertionError('the filter did not return')


def workspace(tmp_path):
    ws = tmp_path / 'worker'
    for name in ('inputs', 'outputs', 'scratch'):
        (ws / name).mkdir(parents=True)
    return ws


@pytest.mark.parametrize('machine,architecture,numbers', [
    ('x86_64', X86_64, {'socket': 41, 'bind': 49, 'listen': 50, 'read': 0, 'connect': 42, 'execve': 59}),
    ('aarch64', AARCH64, {'socket': 198, 'bind': 200, 'listen': 201, 'read': 63, 'connect': 203, 'execve': 221}),
])
@pytest.mark.parametrize('network', [None, 'provider'])
def test_filter_refuses_bind_and_listen_and_keeps_ordinary_calls(machine, architecture, numbers, network):
    program = sandbox.linux_filter(network, machine)
    call = lambda name, first=0: decide(program, architecture=architecture, number=numbers[name], first=first)
    assert call('bind') == EPERM and call('listen') == EPERM
    assert decide(program, architecture=architecture, number=sandbox.LINUX_IO_URING_SETUP) == EPERM
    for name in ('read', 'connect', 'execve'):
        assert call(name) == sandbox.SECCOMP_ALLOW
    assert call('socket', AF_UNIX) == sandbox.SECCOMP_ALLOW
    for family in (AF_INET, AF_INET6, AF_NETLINK):
        assert call('socket', family) == (EPERM if network is None else sandbox.SECCOMP_ALLOW)
    assert EPERM & 0xFFFF == errno.EPERM and EPERM >> 16 == 0x5


@pytest.mark.parametrize('machine,architecture,foreign', [('x86_64', X86_64, I386), ('x86_64', X86_64, AARCH64),
                                                         ('aarch64', AARCH64, X86_64)])
def test_filter_ends_a_call_made_through_another_architecture(machine, architecture, foreign):
    program = sandbox.linux_filter(None, machine)
    for number in (0, 41, 49, 50, 102, 198, 200, 201):
        assert decide(program, architecture=foreign, number=number) == sandbox.SECCOMP_KILL_PROCESS


def test_filter_refuses_the_second_system_call_table_of_x86_64():
    program = sandbox.linux_filter('provider', 'x86_64')
    for number in (0, 41, 49, 50):
        assert decide(program, architecture=X86_64, number=sandbox.LINUX_X32_SYSCALL_BIT | number) == EPERM


def test_filter_rows_fit_the_kernel_record_and_jump_forward_only():
    for network in sandbox.NETWORKS:
        for machine in sandbox.LINUX_SYSCALLS:
            program = sandbox.linux_filter(network, machine)
            assert struct.calcsize('HBBI') == 8 and len(program) < 4096
            for index, (code, when_true, when_false, value) in enumerate(program):
                struct.pack('HBBI', code, when_true, when_false, value)
                assert index + 1 + max(when_true, when_false) < len(program) or code == 0x06
            assert [row[0] for row in program[-3:]] == [0x06, 0x06, 0x06]


def test_filter_names_one_architecture_under_either_spelling_and_refuses_an_unknown_one():
    assert sandbox.linux_filter(None, 'arm64') == sandbox.linux_filter(None, 'aarch64')
    assert sandbox.linux_filter(None, 'amd64') == sandbox.linux_filter(None, 'x86_64')
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.linux_filter(None, 'synthetic-machine')
    with pytest.raises(ValueError):
        sandbox.linux_filter('everything', 'x86_64')


@pytest.mark.parametrize('port_rules', [True, False])
@pytest.mark.parametrize('network', [None, 'provider'])
def test_command_installs_the_filter_before_the_worker_and_ends_read_only(tmp_path, monkeypatch, network, port_rules):
    monkeypatch.setattr(sandbox.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(sandbox, 'linux_port_rules', lambda: port_rules)
    ws = workspace(tmp_path)
    worker = ['/usr/bin/true', 'argument']
    command = sandbox.linux_command(ws, worker, read_paths=['/usr'], network=network)
    split = command.index('--')
    options, launched = command[:split], command[split + 1:]
    assert launched[-2:] == worker
    assert launched[:5] == [sys.executable, '-I', '-S', '-B', '-c'] and launched[5] == sandbox.LINUX_FILTER_SHIM
    assert json.loads(launched[6]) == [list(row) for row in sandbox.linux_filter(network, 'x86_64')]
    assert launched[7] == ('443' if network == 'provider' and port_rules else '')
    assert len(launched) == 8 + len(worker)
    assert sandbox.egress(network, 'linux') == ('none' if network is None else 'tcp-443' if port_rules else 'unrestricted')
    # Every mount precedes the two read-only remounts; only the working directory follows them.
    assert options[-6:] == ['--remount-ro', '/tmp', '--remount-ro', '/', '--chdir', str(ws)]
    writable = [options[i + 1] for i, option in enumerate(options) if option == '--bind']
    assert writable == [str(ws / 'outputs'), str(ws / 'scratch')]
    assert ('--share-net' in options) == (network == 'provider') and ('--unshare-net' in options) == (network is None)


def test_shim_packs_the_rows_installs_the_filter_and_replaces_itself():
    shim = sandbox.LINUX_FILTER_SHIM
    compile(shim, 'shim', 'exec')
    assert 'prctl(38,' in shim and 'prctl(22,word(2),' in shim       # no-new-privileges, then the filter
    order = [shim.index(text) for text in ('prctl(38,', 'call(word(444),', 'call(word(445),', 'call(word(446),',
                                           'prctl(22,', 'os.execv(argv[0],argv)')]
    assert order == sorted(order)
    # The rule set handles TCP bind and connect (3) and admits connect (2) to the one port.
    assert 'struct.pack("QQ",0,3)' in shim and 'struct.pack("QQ",2,int(port))' in shim
    assert (sandbox.LANDLOCK_CREATE_RULESET, sandbox.LANDLOCK_ADD_RULE, sandbox.LANDLOCK_RESTRICT_SELF) == (444, 445, 446)
    assert 'struct.pack("HBBI",*row)' in shim and shim.rstrip().endswith('os.execv(argv[0],argv)')


def unconfined(monkeypatch, backend):
    """Run the probe program with no confinement at all: it must then confirm nothing."""
    monkeypatch.setattr(sandbox, 'available', lambda: backend)
    monkeypatch.setattr(sandbox, 'command', lambda ws, argv, **kwargs: list(argv))


@pytest.mark.parametrize('backend', ['linux', 'macos'])
def test_probe_program_without_confinement_reports_the_readable_forbidden_file(tmp_path, monkeypatch, backend):
    ws = workspace(tmp_path)
    private = tmp_path / 'private'
    private.write_text('protected')
    unconfined(monkeypatch, backend)
    with pytest.raises(sandbox.SandboxProbeFailed) as refused:
        sandbox.probe(ws, forbidden=private)
    assert refused.value.checks['read_denied'] == [False]
    assert refused.value.checks['write_denied'] is False and refused.value.checks['allowed_input_read'] is True
    (ws / 'forbidden-write').unlink()


def test_an_absent_forbidden_file_counts_as_hidden_only_under_a_namespace(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    absent = tmp_path / 'never-created'
    unconfined(monkeypatch, 'linux')
    with pytest.raises(sandbox.SandboxProbeFailed) as refused:
        sandbox.probe(ws, forbidden=absent)
    # Hidden by absence, yet the unconfined write still refuses the confirmation.
    assert refused.value.checks['read_denied'] == [True] and refused.value.checks['write_denied'] is False
    (ws / 'forbidden-write').unlink()
    unconfined(monkeypatch, 'macos')
    with pytest.raises(sandbox.SandboxProbeFailed) as refused:
        sandbox.probe(ws, forbidden=absent)
    assert refused.value.returncode != 0 and 'FileNotFoundError' in refused.value.stderr
    assert not hasattr(refused.value, 'checks')


def test_probe_counts_a_read_only_filesystem_as_a_refused_write(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    seen = {}

    def run(argv, **kwargs):
        seen['program'], seen['targets'], seen['write'] = argv[3], json.loads(argv[-2]), argv[-1]
        return subprocess.CompletedProcess(argv, 0, json.dumps({
            'read_denied': [True], 'write_denied': True, 'listen_denied': True, 'other_port_denied': True,
            'allowed_input_read': True}), '')
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    monkeypatch.setattr(sandbox, 'command', lambda ws, argv, **kwargs: list(argv))
    monkeypatch.setattr(sandbox.subprocess, 'run', run)
    evidence = sandbox.probe(ws, forbidden=tmp_path / 'private')
    assert evidence['confirmed'] and evidence['backend'] == 'linux'
    assert seen['targets'] == [str(tmp_path / 'private')] and seen['write'] == str(ws / 'forbidden-write')
    assert 'absent=(FileNotFoundError,NotADirectoryError)\n' in seen['program']
    assert 'error.errno!=errno.EROFS: raise' in seen['program']
    # The socket is created inside the guarded block: a refused creation is a refusal, not a crash.
    assert seen['program'].count('try:\n s=socket.socket()') == 2


def test_protected_roots_and_control_folders_are_present_but_unsearchable(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.platform, 'machine', lambda: 'x86_64')
    ws = workspace(tmp_path / 'work' / 'node')
    (ws / 'calls').mkdir()
    (ws / 'note.txt').write_text('a file is simply absent')
    run, custody, tool = tmp_path / 'run', tmp_path / 'custody', tmp_path / 'tool'
    for folder in (run, custody, tool):
        folder.mkdir()
    protected = [run, custody, tmp_path / 'work']       # the last one is an ancestor of the workspace
    command = sandbox.linux_command(ws, ['/usr/bin/true'], read_paths=[tool], protected=protected)
    placeholders = [command[i + 3] for i, option in enumerate(command)
                    if command[i:i + 3] == ['--perms', '000', '--dir']]
    assert placeholders == [str(run), str(custody), str(ws / 'calls')]
    assert command.index('--perms') > command.index(str(ws / 'scratch'))
    assert max(i for i, option in enumerate(command) if option == '--perms') < command.index('--remount-ro')
    assert str(ws / 'note.txt') not in command and command.count(str(tmp_path / 'work')) == 0


def test_port_rules_are_asked_of_the_kernel_once_and_absent_off_linux(monkeypatch):
    monkeypatch.setattr(sandbox, '_PORT_RULES', {})
    monkeypatch.setattr(sandbox.sys, 'platform', 'darwin')
    assert sandbox.linux_port_rules() is False and sandbox._PORT_RULES == {'value': False}
    monkeypatch.setattr(sandbox, '_PORT_RULES', {'value': True})
    assert sandbox.linux_port_rules() is True and sandbox.egress('provider', 'linux') == 'tcp-443'
    monkeypatch.setattr(sandbox, '_PORT_RULES', {'value': False})
    assert sandbox.egress('provider', 'linux') == 'unrestricted' and sandbox.egress('provider', 'macos') == 'tcp-443'
    assert sandbox.egress(None, 'linux') == 'none'
