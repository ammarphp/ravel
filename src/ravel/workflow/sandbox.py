"""Filesystem/network confinement for worker children, never their supervisors.

Unavailable or unconfirmed confinement refuses execution. A generated profile is
not evidence of OS enforcement; qualification must execute the denial probes.
"""
from __future__ import annotations
import errno
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from .broker import ordinary

SYSTEM_RUNTIME_ROOTS = ('/usr', '/bin', '/lib', '/lib64', '/System/Library', '/Library/Apple')
LINUX_RUNTIME_ALIASES = ('/bin', '/lib', '/lib64')


class SandboxUnavailable(ValueError):
    pass


class SandboxProbeFailed(ValueError):
    pass


class ReadRootRefused(ValueError):
    pass


def quote(value):
    return json.dumps(value, ensure_ascii=True)


def available():
    if sys.platform == 'darwin' and Path('/usr/bin/sandbox-exec').is_file():
        return 'macos'
    if sys.platform.startswith('linux') and shutil.which('bwrap'):
        return 'linux'
    return None


def protected_roots(rundir):
    """Locations no extra read root may overlap: the run tree, every workspace, custody."""
    from .broker import custody, work_root
    return [ordinary(rundir), work_root(rundir).parent, custody(rundir).parents[1]]


def read_root(path):
    """A declared read root as an ordinary path.

    A trusted system runtime root may itself be a link (``/bin`` to ``usr/bin`` on a
    merged-/usr Linux): that name alone is replaced by its target before the symlink
    check. Every other path that is or traverses a link stays refused.
    """
    if str(path) in SYSTEM_RUNTIME_ROOTS:
        path = os.path.realpath(path)
    return ordinary(path)


def _paths(workspace, read_paths, protected=()):
    """Declared read roots: never root, the workspace or inside it, nor overlapping a protected root."""
    workspace = ordinary(workspace)
    paths = list(dict.fromkeys(read_root(p) for p in read_paths))
    guarded = [ordinary(p) for p in protected]
    for p in paths:
        if str(p) == '/' or p.is_relative_to(workspace) or workspace.is_relative_to(p):
            raise ReadRootRefused('sandbox cannot expose root, the workspace or its ancestors')
        if any(p.is_relative_to(g) or g.is_relative_to(p) for g in guarded):
            raise ReadRootRefused('sandbox read root overlaps the run tree, a workspace or custody')
    return workspace, paths


def cli_home_for(workspace):
    """The per-worker CLI home a transport adapter creates beside the workspace (never inside it)."""
    workspace = ordinary(workspace)
    return workspace.parent / (workspace.name + '.cli-home')


def _home(workspace, home, protected=()):
    """A directory the CLI child may read and write besides its workspace, or None.

    It is either the workspace's own sibling ``<attempt>.cli-home`` or a directory that
    overlaps no protected root, the workspace, the account's home or the filesystem root.
    """
    if home is None:
        return None
    import pwd
    home, workspace = ordinary(home), ordinary(workspace)
    if home == cli_home_for(workspace):
        return home
    account = ordinary(pwd.getpwuid(os.getuid()).pw_dir)
    if (str(home) == '/' or account.is_relative_to(home) or home.is_relative_to(workspace)
            or workspace.is_relative_to(home)
            or any(home.is_relative_to(ordinary(g)) or ordinary(g).is_relative_to(home) for g in protected)):
        raise ReadRootRefused('a CLI home cannot be root, the account home, the workspace or a protected root')
    return home


def user_home_for(workspace):
    """The adapter-owned ``HOME`` of a Claude-family worker on macOS, beside the workspace.

    It holds exactly one entry, ``Library/Keychains``: a symbolic link the adapter makes to
    the invoking account's login keychain directory, because Claude Code finds its stored
    login through ``$HOME/Library/Keychains``. This one link is the documented exception to
    the no-symlink path rule; nothing else from the account home is linked or copied.
    """
    workspace = ordinary(workspace)
    return workspace.parent / (workspace.name + '.home')


def login_keychains():
    """The invoking account's real keychain directory, from the password database (never ``$HOME``)."""
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / 'Library' / 'Keychains'


def _keychain(workspace, keychain_home):
    """(adapter home, real keychain directory) or None; only the workspace's own ``<attempt>.home``."""
    if keychain_home is None:
        return None
    if ordinary(keychain_home) != user_home_for(workspace):
        raise ReadRootRefused('a keychain home must be the workspace\'s own <attempt>.home')
    return ordinary(keychain_home), ordinary(login_keychains())


# Provider egress for a model CLI: outbound TCP to port 443 only and name resolution, plus the
# system services a CLI uses for TLS trust and its stored login (Keychain). Every other port and
# listening sockets stay denied. Hosts are not filtered: that needs a RAVEL-owned proxy.
PROVIDER_PORT = 443
MACOS_PROVIDER_NETWORK = (
    f'(allow network-outbound (remote tcp "*:{PROVIDER_PORT}"))',
    '(allow network-outbound (remote unix-socket (path "/private/var/run/mDNSResponder")))',
    '(allow system-socket)',
    '(allow mach-lookup (global-name "com.apple.dnssd.service") (global-name "com.apple.trustd")'
    ' (global-name "com.apple.trustd.agent") (global-name "com.apple.SecurityServer")'
    ' (global-name "com.apple.securityd.xpc") (global-name "com.apple.system.opendirectoryd.libinfo")'
    ' (global-name "com.apple.system.notification_center") (global-name "com.apple.cfprefsd.daemon")'
    ' (global-name "com.apple.cfprefsd.agent"))',
    '(allow file-read* (literal "/etc") (literal "/var") (literal "/tmp") (subpath "/private/etc")'
    ' (subpath "/private/var/db/timezone"))',
)
NETWORKS = (None, 'provider')
# Claude-family workers only: the login keychain's directory is readable (never writable) and the
# Security framework's remaining services are reachable. Keychain items stay under macOS ACLs.
# Measured with `security show-keychain-info` in the profile: without group-membership lookup and
# the system Module Directory Service database the framework fails before it opens any keychain.
MACOS_KEYCHAIN_SERVICES = ('com.apple.securityd', 'com.apple.security.agent', 'com.apple.ocspd',
                           'com.apple.system.opendirectoryd.membership')
MACOS_KEYCHAIN_SYSTEM_READS = ('/private/var/db/mds',)
# Claude Code reads its stored login by running this tool (`security find-generic-password -a $USER`).
# The base profile's exec rule covers it; naming it keeps the keychain grant independent of the read
# roots. Measured with `show-keychain-info` and a lookup of an absent item: it needs nothing else.
MACOS_KEYCHAIN_TOOL = '/usr/bin/security'


def macos_profile(workspace, *, read_paths=(), broker_socket=None, protected=(), home=None, network=None,
                  keychain_home=None):
    ws, paths = _paths(workspace, read_paths, protected)
    home = _home(ws, home, protected)
    keychain = _keychain(ws, keychain_home)
    if network not in NETWORKS:
        raise ValueError(f'unknown sandbox network {network!r}')
    # Local unix IPC only; no IP sockets. Calls/receipt/spec/control are absent.
    lines = ['(version 1)', '(deny default)', '(allow process-exec)', '(allow process-fork)',
             '(allow signal (target self))', '(allow sysctl-read)',
             '(allow file-read* (literal "/dev/null") (literal "/dev/urandom"))',
             # dyld aborts the child without the root directory entry; literal, never a subpath.
             '(allow file-read* (literal "/"))',
             '(allow file-write* (literal "/dev/null"))']
    # The child's cwd entry must be listable; calls/, receipts and control files stay unreadable.
    lines.append('(allow file-read* (literal '+quote(str(ws))+'))')
    for path in [*paths, ws/'inputs', ws/'outputs', ws/'scratch']:
        lines.append('(allow file-read* (subpath '+quote(str(path))+'))')
    for path in (ws/'outputs', ws/'scratch', *([home] if home else [])):
        lines.append('(allow file-write* (subpath '+quote(str(path))+'))')
    if home:
        lines.append('(allow file-read* (subpath '+quote(str(home))+'))')
    # Metadata only along the paths the child may use: each ancestor directory entry
    # (path resolution and getcwd need them) and inside the readable roots. Elsewhere a
    # stat is denied, so unrelated trees cannot be enumerated or probed for existence.
    ancestors = sorted({str(a) for p in [*paths, ws, *([home] if home else [])] for a in p.parents})
    lines.append('(allow file-read-metadata '+' '.join('(literal '+quote(a)+')' for a in ancestors)+')')
    lines.append('(allow file-read-metadata (literal '+quote(str(ws))+')'
                 +''.join(' (subpath '+quote(str(p))+')' for p in [*paths, ws/'inputs', ws/'outputs', ws/'scratch',
                                                                *([home] if home else [])])
                 +' (literal "/dev/null") (literal "/dev/urandom") (literal "/dev"))')
    lines.append('(allow network-outbound (remote unix-socket (path '+quote(str(broker_socket or ws/'.broker.sock'))+')))')
    if network == 'provider':
        lines.extend(MACOS_PROVIDER_NETWORK)
    if keychain:
        own, real = keychain
        # The adapter home is the child's HOME; the real keychain directory is read-only.
        lines.append('(allow file-read* file-write* (subpath '+quote(str(own))+'))')
        lines.append('(allow file-read* (subpath '+quote(str(real))+')'
                     +''.join(' (subpath '+quote(p)+')' for p in MACOS_KEYCHAIN_SYSTEM_READS)+')')
        lines.append('(allow file-read-metadata '+' '.join('(literal '+quote(str(a))+')'
                     for a in sorted({*own.parents, *real.parents}, key=str))+')')
        lines.append('(allow mach-lookup '+' '.join('(global-name '+quote(n)+')' for n in MACOS_KEYCHAIN_SERVICES)+')')
        lines.append('(allow file-read* (literal '+quote(MACOS_KEYCHAIN_TOOL)+'))')
        lines.append('(allow process-exec (literal '+quote(MACOS_KEYCHAIN_TOOL)+'))')
    return '\n'.join(lines)+'\n'


# Namespaces hide files and the host network, but a namespace cannot refuse a system call.
# The Linux profile therefore adds a seccomp filter, installed inside the namespace before
# the worker program starts: binding or listening on any socket is refused, as the macOS
# profile refuses it, and without provider egress no socket other than a local one exists.
LINUX_SYSCALLS = {'x86_64': (0xC000003E, {'socket': 41, 'bind': 49, 'listen': 50}),
                  'aarch64': (0xC00000B7, {'socket': 198, 'bind': 200, 'listen': 201})}
LINUX_IO_URING_SETUP = 425          # the same number on both; it can carry socket requests past a filter
LINUX_X32_SYSCALL_BIT = 0x40000000  # the second system-call table of an x86_64 kernel
SECCOMP_ALLOW, SECCOMP_KILL_PROCESS = 0x7FFF0000, 0x80000000
SECCOMP_REFUSE = 0x00050000 | errno.EPERM
# Landlock (kernel 6.7 and later, access-control version 4) can restrict TCP by port. With it
# the provider profile admits outbound TCP to the provider port only, as on macOS; without
# it the namespace shares the host network unfiltered and the evidence says "unrestricted".
LANDLOCK_PORT_RULES_VERSION = 4
LANDLOCK_CREATE_RULESET, LANDLOCK_ADD_RULE, LANDLOCK_RESTRICT_SELF = 444, 445, 446
LINUX_FILTER_SHIM = (
    'import ctypes,json,os,struct,sys\n'
    'rows=json.loads(sys.argv[1]);port=sys.argv[2];argv=sys.argv[3:]\n'
    'libc=ctypes.CDLL(None,use_errno=True);word=ctypes.c_ulong;call=libc.syscall;call.restype=ctypes.c_long\n'
    'def refused(what):raise OSError(ctypes.get_errno(),"the worker "+what+" was refused")\n'
    # PR_SET_NO_NEW_PRIVS; both restrictions below need it.
    'if libc.prctl(38,word(1),word(0),word(0),word(0)):refused("privilege lock")\n'
    'if port:\n'
    # A rule set handling TCP bind and connect, with one rule: connect to the provider port.
    ' attr=ctypes.create_string_buffer(struct.pack("QQ",0,3),16)\n'
    ' ruleset=call(word(444),attr,ctypes.c_size_t(16),ctypes.c_uint(0))\n'
    ' rule=ctypes.create_string_buffer(struct.pack("QQ",2,int(port)),16)\n'
    ' if ruleset<0 or call(word(445),ctypes.c_int(ruleset),ctypes.c_int(2),rule,ctypes.c_uint(0)) '
    'or call(word(446),ctypes.c_int(ruleset),ctypes.c_uint(0)):refused("port rule")\n'
    ' os.close(ruleset)\n'
    'blob=b"".join(struct.pack("HBBI",*row) for row in rows)\n'
    'buffer=ctypes.create_string_buffer(blob,len(blob))\n'
    'class Program(ctypes.Structure):_fields_=[("len",ctypes.c_ushort),("filter",ctypes.c_void_p)]\n'
    'program=Program(len(rows),ctypes.addressof(buffer))\n'
    # PR_SET_SECCOMP with SECCOMP_MODE_FILTER.
    'if libc.prctl(22,word(2),ctypes.byref(program),word(0),word(0)):refused("system-call filter")\n'
    'os.execv(argv[0],argv)\n')
_PORT_RULES = {}


def linux_port_rules():
    """True when this host's kernel can restrict TCP by port (asked once, never assumed)."""
    if 'value' not in _PORT_RULES:
        value = False
        if sys.platform.startswith('linux'):
            try:
                import ctypes
                call = ctypes.CDLL(None, use_errno=True).syscall
                call.restype = ctypes.c_long
                # No rule set is made: the version query takes a null attribute and flag 1.
                value = call(ctypes.c_ulong(LANDLOCK_CREATE_RULESET), None, ctypes.c_size_t(0),
                             ctypes.c_uint(1)) >= LANDLOCK_PORT_RULES_VERSION
            except (OSError, AttributeError, ImportError):
                value = False
        _PORT_RULES['value'] = value
    return _PORT_RULES['value']


def linux_filter(network=None, machine=None):
    """The classic-BPF rows ``(code, jt, jf, k)`` of the Linux worker filter.

    Refused with EPERM: ``bind``, ``listen``, ``io_uring_setup``, every call of the x32
    table and, when the profile has no provider egress, ``socket`` for any family other
    than the local one. A call made through another architecture's table ends the process.
    """
    machine = machine or platform.machine()
    machine = {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(machine, machine)
    if machine not in LINUX_SYSCALLS:
        raise SandboxUnavailable('sandbox_unavailable')
    if network not in NETWORKS:
        raise ValueError(f'unknown sandbox network {network!r}')
    architecture, numbers = LINUX_SYSCALLS[machine]
    load, equal, at_least, result = 0x20, 0x15, 0x35, 0x06
    rows = [(load, 'arch'), (equal, architecture, None, 'kill'), (load, 'nr'),
            (at_least, LINUX_X32_SYSCALL_BIT, 'refuse', None), (equal, numbers['bind'], 'refuse', None),
            (equal, numbers['listen'], 'refuse', None), (equal, LINUX_IO_URING_SETUP, 'refuse', None)]
    if network is None:
        rows += [(equal, numbers['socket'], None, 'allow'), (load, 'family'), (equal, 1, 'allow', 'refuse')]  # AF_UNIX
    labels = {'allow': len(rows), 'refuse': len(rows) + 1, 'kill': len(rows) + 2}
    offsets = {'nr': 0, 'arch': 4, 'family': 16}
    program = []
    for index, row in enumerate(rows):
        if row[0] == load:
            program.append((load, 0, 0, offsets[row[1]]))
        else:
            jump = lambda label: 0 if label is None else labels[label] - index - 1
            program.append((row[0], jump(row[2]), jump(row[3]), row[1]))
    return program + [(result, 0, 0, SECCOMP_ALLOW), (result, 0, 0, SECCOMP_REFUSE), (result, 0, 0, SECCOMP_KILL_PROCESS)]


def linux_command(workspace, argv, *, read_paths=(), broker_socket=None, protected=(), home=None, network=None,
                  keychain_home=None):
    if keychain_home is not None:
        raise ValueError('a keychain home is a macOS profile property')
    ws, paths = _paths(workspace, read_paths, protected)
    home = _home(ws, home, protected)
    if network not in NETWORKS:
        raise ValueError(f'unknown sandbox network {network!r}')
    command = [shutil.which('bwrap') or 'bwrap', '--die-with-parent', '--new-session', '--unshare-all',
               *(['--share-net'] if network == 'provider' else ['--unshare-net']),
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    if network == 'provider':
        for p in ('/etc/resolv.conf', '/etc/hosts', '/etc/ssl', '/etc/ca-certificates', '/etc/pki'):
            if Path(p).exists():
                command.extend(['--ro-bind', p, p])
    for p in paths:
        command.extend(['--ro-bind', str(p), str(p)])
    # Merged-/usr systems need these loader and executable names inside the
    # namespace. Read grants use canonical roots; only known system aliases
    # whose targets are already mounted are recreated.
    for name in LINUX_RUNTIME_ALIASES:
        alias = Path(name)
        if alias.is_symlink() and alias.exists():
            target = alias.resolve(strict=True)
            if any(target.is_relative_to(root) for root in paths):
                command.extend(['--symlink', str(target), str(alias)])
    command.extend(['--dir', str(ws)])
    for p in (ws/'inputs',):
        command.extend(['--ro-bind', str(p), str(p)])
    if broker_socket is not None:
        command.extend(['--ro-bind', str(broker_socket), '/tmp/ravel-broker.sock'])
    for p in (ws/'outputs', ws/'scratch', *([home] if home else [])):
        command.extend(['--bind', str(p), str(p)])
    # The namespace hides whatever is not bound. The protected roots and the workspace's
    # other folders are present as directories nobody may search, so reaching for the run
    # tree, custody or the call records is refused by permission, as under the macOS profile.
    bound = [*paths, ws/'inputs', ws/'outputs', ws/'scratch', *([home] if home else []), Path('/proc'), Path('/dev')]
    hidden = [ordinary(p) for p in protected]
    hidden += sorted(p for p in ws.iterdir() if p.is_dir() and not p.is_symlink()) if ws.is_dir() else []
    for p in dict.fromkeys(hidden):
        if any(m.is_relative_to(p) for m in (*bound, ws, Path('/tmp'))) or any(p.is_relative_to(m) for m in bound):
            continue  # an ancestor of something the child needs, or inside a bound tree
        command.extend(['--perms', '000', '--dir', str(p)])
    # Everything not bound above lives on the namespace's own two memory filesystems. They
    # become read-only last, so a write outside outputs, scratch and the CLI home is refused
    # instead of landing in memory that vanishes with the child.
    command.extend(['--remount-ro', '/tmp', '--remount-ro', '/'])
    # The filter is installed by this interpreter inside the namespace; a read root that
    # omits the interpreter leaves nothing to run, and the launch fails closed.
    shim = [sys.executable, '-I', '-S', '-B', '-c', LINUX_FILTER_SHIM,
            json.dumps(linux_filter(network), separators=(',', ':')),
            str(PROVIDER_PORT) if network == 'provider' and linux_port_rules() else '']
    return command+['--chdir',str(ws), '--', *shim, *argv]


def runtime_paths(argv):
    """Read only the interpreter/tool runtime; never the user's home or run."""
    paths = list(dict.fromkeys(str(Path(p).resolve(strict=True))
                              for p in SYSTEM_RUNTIME_ROOTS if Path(p).exists()))
    # A venv needs its prefix and its underlying interpreter prefix.
    for p in (Path(sys.prefix).resolve(strict=True), Path(sys.base_prefix).resolve(strict=True)):
        if p != Path('/') and not any(p.is_relative_to(Path(q)) for q in paths):
            paths.append(str(p))
    executable = Path(argv[0]).resolve()
    if not any(executable.is_relative_to(Path(p)) for p in paths):
        paths.append(str(executable.parent))
    # The RAVEL package the broker's MCP face runs from (site-packages, or a source checkout's src).
    package = Path(__file__).resolve().parents[2]
    if not any(package.is_relative_to(Path(p)) for p in paths):
        paths.append(str(package))
    return paths


def _configuration_name(name):
    return (name in {'HOME', 'ZDOTDIR'} or name.startswith('XDG_') or 'CONFIG' in name
            or name.endswith('_PROFILE') or name.endswith('RC'))


def user_configuration_exposed(read_paths, pass_env_names=()):
    """Computed, not asserted: True when a read root is the account's home or an ancestor
    of it, lies inside a hidden configuration directory of the home (``~/.config``,
    ``~/.claude``, ``~/.local/state`` ...; installed data under ``~/.local/share``,
    ``~/.local/lib``, ``~/.local/bin`` and ``~/.cache`` is not configuration), or a
    passed variable names configuration (``HOME``, ``XDG_*``, ``*CONFIG*``)."""
    import pwd
    home = ordinary(pwd.getpwuid(os.getuid()).pw_dir)
    for root in (read_root(p) for p in read_paths):
        if home.is_relative_to(root):
            return True
        parts = root.relative_to(home).parts if root.is_relative_to(home) else ()
        if parts and parts[0].startswith('.') and parts[0] != '.cache' and not (
                parts[0] == '.local' and len(parts) > 1 and parts[1] in {'share', 'lib', 'bin'}):
            return True
    return any(_configuration_name(n) for n in pass_env_names)


def command(workspace, argv, *, read_paths=(), backend=None, broker_socket=None, protected=(), home=None, network=None,
            keychain_home=None):
    backend = backend or available()
    if not backend:
        raise SandboxUnavailable('sandbox_unavailable')
    if not argv or not Path(argv[0]).is_absolute():
        raise ValueError('absolute worker executable required')
    if backend == 'macos':
        return ['/usr/bin/sandbox-exec','-p',macos_profile(workspace,read_paths=read_paths,broker_socket=broker_socket,
                                                           protected=protected,home=home,network=network,
                                                           keychain_home=keychain_home),*argv]
    if backend == 'linux':
        return linux_command(workspace,argv,read_paths=read_paths,broker_socket=broker_socket,protected=protected,
                             home=home,network=network,keychain_home=keychain_home)
    raise SandboxUnavailable('sandbox_unavailable')


def egress(network, backend=None):
    """What the profile permits outward, as recorded in the probe evidence."""
    if network is None:
        return 'none'
    if (backend or available()) == 'linux' and not linux_port_rules():
        return 'unrestricted'  # a shared network namespace alone cannot filter ports
    return f'tcp-{PROVIDER_PORT}'


def probe(workspace, *, forbidden, executable=sys.executable, read_paths=(), protected=(), home=None, network=None,
          keychain_home=None):
    """Run inert read/write/network denial probes in the actual profile.

    ``home``, ``network`` and ``keychain_home`` must be the child's own, so the evidence describes the profile
    the child runs under. ``forbidden`` is one file or a list of files (custody, run tree,
    peer workspace); every read must be denied. A listening socket is always denied; an
    outbound connection to a port other than 443 (on the loopback address, so nothing
    leaves the machine) must be denied wherever the profile restricts egress. No positive
    claim survives an unavailable launcher, unexpected failure, unreadable allowed input,
    or an allowed forbidden operation.
    """
    ws = ordinary(workspace)
    targets = [str(ordinary(p)) for p in (forbidden if isinstance(forbidden, (list, tuple)) else [forbidden])]
    marker = ws/'inputs/.sandbox-probe';marker.write_text('allowed')
    program = '''import errno,json,pathlib,socket,sys
allowed=pathlib.Path(sys.argv[1]).read_text()=="allowed"
absent=ABSENT
checks={"read_denied":[]}
for path in json.loads(sys.argv[2]):
 try:
  pathlib.Path(path).read_bytes();checks["read_denied"].append(False)
 except PermissionError: checks["read_denied"].append(True)
 except absent: checks["read_denied"].append(True)
try:
 pathlib.Path(sys.argv[3]).write_text("probe");checks["write_denied"]=False
except PermissionError: checks["write_denied"]=True
except OSError as error:
 if error.errno!=errno.EROFS: raise
 checks["write_denied"]=True
try:
 s=socket.socket()
 try:
  s.bind(("127.0.0.1",0));checks["listen_denied"]=False
 finally:s.close()
except PermissionError: checks["listen_denied"]=True
try:
 s=socket.socket();s.settimeout(2)
 try:
  s.connect(("127.0.0.1",9));checks["other_port_denied"]=False
 finally:s.close()
except PermissionError: checks["other_port_denied"]=True
except OSError: checks["other_port_denied"]=False
checks["allowed_input_read"]=allowed
print(json.dumps(checks))
'''
    # A mount namespace hides a forbidden file: there it is absent, not refused by permission.
    program=program.replace('ABSENT','(FileNotFoundError,NotADirectoryError)' if available()=='linux' else '()')
    argv=[executable,'-B','-c',program,str(marker),json.dumps(targets),str(ws/'forbidden-write')]
    outward=egress(network)
    try:
        done=subprocess.run(command(ws,argv,read_paths=read_paths,protected=protected,home=home,network=network,
                                    keychain_home=keychain_home),cwd=ws,
                            env={'PATH':'/usr/bin:/bin','HOME':str(ws/'scratch')},
                            capture_output=True,text=True,timeout=10)
        if done.returncode!=0:
            # Only the launcher's own refusal means unavailable; a denied child is a profile failure.
            if ('sandbox_apply' in done.stderr or 'sandbox_init' in done.stderr or
                    (available() == 'linux' and done.stderr.startswith('bwrap: ') and
                     any(message in done.stderr for message in (
                         'No permissions to create new namespace',
                         'Creating new namespace failed: Operation not permitted',
                         'setting up uid map: Permission denied')))):
                raise SandboxUnavailable('sandbox launcher unavailable: ' + done.stderr.strip()[-1000:])
            failure=SandboxProbeFailed('sandbox probe launcher or profile failed')
            failure.returncode,failure.stderr=done.returncode,done.stderr[-2000:]
            raise failure
        checks=json.loads(done.stdout)
        reads=checks.get('read_denied') if type(checks) is dict else None
        required=('write_denied','listen_denied','allowed_input_read')+(('other_port_denied',) if outward!='unrestricted' else ())
        if (set(checks)!={'read_denied','write_denied','listen_denied','other_port_denied','allowed_input_read'}
                or type(reads) is not list or len(reads)!=len(targets) or not all(v is True for v in reads)
                or not all(checks[k] is True for k in required)):
            failure=SandboxProbeFailed('sandbox probe did not confirm the required denials')
            failure.checks=checks
            raise failure
        computed={**checks,'read_denied':True,'egress':outward,'network_denied':outward=='none'}
        return {'backend':available(),'confirmed':True,'computed_checks':computed,'denied_reads':len(targets),
                'network':outward,'cli_home':home is not None,
                'login_keychain':keychain_home is not None}
    except (OSError,subprocess.SubprocessError) as exc:
        raise SandboxUnavailable('sandbox_probe_unconfirmed') from exc
    finally:
        marker.unlink(missing_ok=True)
