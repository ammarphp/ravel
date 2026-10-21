"""Locations the confined launcher reads, protects or hides, computed on this host.

Paths are canonical (``os.path.realpath``): the macOS profile language and Linux mounts both
act on resolved paths, so ``/tmp`` is ``/private/tmp`` on macOS.
"""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import re
import shutil
import site
import sys
import sysconfig
import tempfile

# Read-only system runtime roots every launch needs.
MACOS_SYSTEM = ('/usr', '/bin', '/sbin', '/System/Library', '/Library/Apple', '/private/etc',
                '/private/var/db/timezone')
LINUX_SYSTEM = ('/usr', '/etc')
LINUX_MERGED_ALIASES = ('/bin', '/sbin', '/lib', '/lib32', '/lib64', '/libx32')

# Run-relative records that decide authority, custody or delivery. A confined launch never
# writes them, and a declared output may not overlap one.
GOVERNED_RUN_PATHS = (
    'inputs', 'logs/authorization', 'logs/execution', 'logs/science-attempts', 'logs/physics_review',
    'logs/allocations', 'logs/state', 'logs/environment', 'logs/STATUS.txt', 'logs/ladder.json',
    'logs/delegated-approvals.jsonl', 'logs/enforcement-surface.jsonl', 'logs/site-tools.jsonl',
    'run_state.json', 'SESSION.lock', 'current_state.json', 'execution_state.json', 'execution_attempt.json',
    'task_contract.json', 'CHECKIN1.md', 'DEVIATIONS.md', 'RESULT.md', 'head.json', 'history',
    'scan_manifest.json', 'scan.json', 'replane.json', 'submission.json', 'parent-binding.json',
    '.reproduce', '.ravel-delivery.json', 'review', 'framework', 'calls', 'agent-work', 'agent-audit',
    'downstream', 'attempts', 'transport-receipts', 'gate-actions', 'rdj', 'research', 'artifacts', 'delivery',
    # Settings, policy and repository control inside the run tree.
    '.ravel', '.claude', '.codex', '.gemini', '.opencode', '.agents', '.git', 'workflow',
    # Names a controller-side interpreter started in the run tree would import.
    'ravel', 'ravel.py', 'sitecustomize.py', 'usercustomize.py',
)
# Governed record families named by pattern under logs/ (failure receipts, watcher preflights).
GOVERNED_LOG_PATTERNS = (r'[^/]+\.failure\.json', r'[^/]+\.preflight\.json')

# Credential and private stores under an account home.
HOME_CREDENTIAL_ENTRIES = (
    '.ssh', '.gnupg', '.aws', '.azure', '.config', '.docker', '.kube', '.claude', '.claude.json', '.codex',
    '.gemini', '.anthropic', '.ravel', '.netrc', '.git-credentials', '.npmrc', '.pypirc', '.vault-token',
    '.password-store', '.terraform.d', '.oci', '.pki', '.cert', '.subversion', '.local/state',
    '.local/share/keyrings', '.bash_history', '.zsh_history', '.sh_history', '.python_history',
    '.lesshst', '.viminfo', '.psql_history', '.mysql_history', '.Xauthority', '.ICEauthority',
    'Library/Keychains', 'Library/Cookies', 'Library/Application Support', 'Library/Containers',
    'Library/Group Containers', 'Library/Mail', 'Library/Messages', 'Library/Safari', 'Library/Accounts',
    'Library/Preferences', 'Library/Calendars', 'Library/IdentityServices', 'Library/HTTPStorages',
)


def real(path):
    return Path(os.path.realpath(os.fspath(path)))


def within(path, roots):
    return any(path == root or path.is_relative_to(root) for root in roots)


def overlaps(path, roots):
    return any(path == root or path.is_relative_to(root) or root.is_relative_to(path) for root in roots)


def depth_sorted(paths):
    return sorted(dict.fromkeys(paths), key=lambda p: (len(p.parts), str(p)))


def outermost(paths):
    """The given paths without any that lies inside another of them."""
    ordered = depth_sorted(paths)
    return [p for i, p in enumerate(ordered) if not within(p, ordered[:i])]


def system_roots():
    names = MACOS_SYSTEM if sys.platform == 'darwin' else LINUX_SYSTEM
    roots = [real(p) for p in names if os.path.exists(p)]
    if sys.platform.startswith('linux'):
        for alias in LINUX_MERGED_ALIASES:
            path = Path(alias)
            if path.exists() and not path.is_symlink():
                roots.append(path)
    return outermost(roots)


def account_homes(environ=None):
    environ = os.environ if environ is None else environ
    homes = [real(pwd.getpwuid(os.getuid()).pw_dir)]
    value = environ.get('HOME')
    if value and os.path.isabs(value):
        homes.append(real(value))
    return list(dict.fromkeys(homes))


def credential_paths(environ=None):
    return [issuer_root(), *[home / entry for home in account_homes(environ) for entry in HOME_CREDENTIAL_ENTRIES]]


def issuer_root():
    """The authority service's resolved root, independent of environment-selected homes."""
    from ravel.controller.authority.issuer import home
    return real(home())


def custody_roots(environ=None):
    """Custody, state stores and worker workspaces wherever this host keeps them."""
    environ = os.environ if environ is None else environ
    roots = [home / '.local/state' for home in account_homes(environ)]
    for name in ('RAVEL_STATE_DIR', 'RAVEL_WORK_ROOT'):
        value = environ.get(name)
        if value and os.path.isabs(value):
            roots.append(real(value))
    from ravel.workflow import machine_lease
    for value in (machine_lease._LOCATION, machine_lease._TEST_DOMAIN):
        if value:
            roots.append(real(value))
    from . import runs
    configured = runs.operator_settings().get('store_root')
    if isinstance(configured, str) and os.path.isabs(configured):
        roots.append(real(configured))
    return list(dict.fromkeys(roots))


def shared_temporary(environ=None):
    """Temporary areas other processes write into; a confined launch gets its own instead."""
    environ = os.environ if environ is None else environ
    names = ['/private/tmp', '/private/var/tmp'] if sys.platform == 'darwin' else ['/tmp', '/var/tmp', '/run', '/dev/shm']
    areas = [real(p) for p in names if os.path.exists(p)]
    for value in (environ.get('TMPDIR'), tempfile.gettempdir()):
        if value and os.path.isabs(value):
            areas.append(real(value))
    if sys.platform == 'darwin':
        try:
            areas.append(real(os.confstr('CS_DARWIN_USER_TEMP_DIR')))
        except (ValueError, OSError, TypeError):
            pass
    return outermost(areas)


def package_root():
    """The directory holding the installed ``ravel`` package (site-packages or a checkout's src)."""
    from ravel import paths
    return real(Path(paths.__file__).parent.parent)


def interpreter_roots():
    """The interpreter's prefixes, its executable's directory and every package directory it imports from.

    A dependency directory another environment supplies to this interpreter (a path file, an
    inherited site) is interpreter code too: a confined child of this interpreter must import
    the same packages, so each ``site-packages`` entry of the current path counts as a root.
    """
    roots = [real(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix) if p]
    roots.append(real(sys.executable).parent)
    roots.append(real(os.path.dirname(os.path.abspath(sys.executable))))
    for entry in sys.path:
        if entry and Path(entry).name in ('site-packages', 'dist-packages') and os.path.isdir(entry):
            parents = real(entry).parents
            # <prefix>/lib/pythonX.Y/site-packages: the environment's prefix as a whole (its interpreter
            # link, console entries and venv configuration belong to the same installation).
            roots.append(parents[2] if len(parents) > 2 and parents[1].name == 'lib' else real(entry))
    return [r for r in dict.fromkeys(roots) if str(r) != '/']


def installation_roots():
    """RAVEL's installed code, its interpreter prefixes, the user site and the toolchain prefix."""
    roots = [package_root(), *interpreter_roots()]
    for value in (site.getuserbase(), site.getusersitepackages(), sysconfig.get_path('scripts')):
        if value:
            roots.append(real(value))
    toolchain = toolchain_root()
    if toolchain is not None:
        roots.append(toolchain)
    return [r for r in dict.fromkeys(roots) if str(r) != '/']


def toolchain_root():
    """The native toolchain prefix the controller resolves (pointer file or search order), when it exists."""
    try:
        from ravel import paths
        prefix = paths.native_build_root()
    except (OSError, ValueError, RuntimeError):
        return None
    return real(prefix) if prefix.is_dir() else None


def _prefix(directory):
    """``<prefix>`` for a ``<prefix>/bin``-style directory, unless that prefix is a home or above one."""
    if directory.name not in ('bin', 'sbin', 'libexec', 'lib', 'lib64'):
        return directory
    prefix = directory.parent
    if str(prefix) == '/' or any(home.is_relative_to(prefix) for home in account_homes()):
        return directory
    return prefix


def executable_roots(argv0, path_value):
    """The executable itself; an argv or PATH entry never grants access to its siblings."""
    located = argv0 if os.path.isabs(argv0) else shutil.which(argv0, path=path_value or os.defpath)
    if not located or not os.path.exists(located):
        return []
    return list(dict.fromkeys((Path(os.path.abspath(located)), real(located))))


def path_roots(env):
    """Prefixes of the committed search paths: each ``bin`` entry gives its prefix."""
    roots = []
    for name in ('PATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'PYTHONPATH'):
        for part in (env.get(name) or '').split(os.pathsep):
            if part and os.path.isabs(part) and os.path.isdir(part):
                roots.append(_prefix(real(part)))
    if env.get('CONDA_PREFIX') and os.path.isabs(env['CONDA_PREFIX']) and os.path.isdir(env['CONDA_PREFIX']):
        roots.append(real(env['CONDA_PREFIX']))
    return roots


# Agent and model command-line programs: a confined launch may not start one.
AGENT_PROGRAMS = ('claude', 'codex', 'gemini', 'opencode', 'aider', 'cursor-agent', 'goose', 'amp', 'copilot',
                  'antigravity', 'qwen', 'crush')


def agent_programs(env):
    """Every agent program the committed ``PATH`` would find (each name, every directory, real paths)."""
    found = []
    for part in (env.get('PATH') or '').split(os.pathsep):
        if not part or not os.path.isabs(part):
            continue
        for name in AGENT_PROGRAMS:
            candidate = Path(part) / name
            if candidate.is_file():
                found += [Path(os.path.abspath(candidate)), real(candidate)]
    return list(dict.fromkeys(found))


def governed_paths(root):
    root = real(root)
    return [root / rel for rel in GOVERNED_RUN_PATHS]


def governed_output(root, path):
    """True when ``path`` is, contains or lies inside a governed record of the run at ``root``."""
    root = real(root)
    if path.is_relative_to(root / 'logs') and path.parent == root / 'logs' and any(
            re.fullmatch(pattern, path.name) for pattern in GOVERNED_LOG_PATTERNS):
        return True
    return overlaps(path, governed_paths(root))
