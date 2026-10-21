"""The environment of a confined launch: an allowlisted capsule with every forbidden class removed.

A capsule is the set of variables a plan commits for an operation. ``capsule_from`` builds one
from a process environment by allowlist (the committed runtime variables, locale and harmless
interpreter settings). ``scrub`` then removes, whatever the capsule says, every ``RAVEL_*``
override except the launcher's own channel variables, every ``*_UTC`` clock and
``GATE_TIMESTAMP``, proxies, credentials, agent session markers, startup and injection hooks
and the user's agent and desktop sockets. ``launch_environment`` adds the private locations.

The WMS launch capability (``wms_policy.CAPABILITY_ENV``) is a passed channel: a trusted site
launch names it explicitly in its child's capsule so that the child's scheduler submissions are
admitted under that launch. Unlike the supervisor's own channels it is never harvested from an
ambient environment (``capsule_from`` drops it); ``scrub`` keeps it only when a capsule names it.
"""
from __future__ import annotations

import re

# Variables a stage may receive from the committed runtime environment.
ALLOWLIST = (
    'PATH', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'CONDA_PREFIX',
    'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
    'LANG', 'LANGUAGE', 'LC_ALL', 'LC_CTYPE', 'LC_COLLATE', 'LC_MESSAGES', 'LC_MONETARY', 'LC_NUMERIC', 'LC_TIME',
    'TZ', 'USER', 'LOGNAME', 'PYTHONDONTWRITEBYTECODE', 'PYTHONHASHSEED', 'PYTHONUNBUFFERED', 'PYTHONIOENCODING',
    'PYTHONUTF8', 'PYTHONNOUSERSITE', 'PYTHONWARNINGS', 'MPLBACKEND', 'XDG_DATA_HOME',
)
CUSTODY = 'RAVEL_STAGE_CUSTODY'
OUTPUT_DIR = 'RAVEL_OUTPUT_DIR'
# Removed whatever the capsule says.
FORBIDDEN_NAMES = frozenset({
    'GATE_TIMESTAMP', 'LD_PRELOAD', 'LD_AUDIT', 'DYLD_INSERT_LIBRARIES', 'DYLD_FRAMEWORK_PATH', 'PYTHONSTARTUP',
    'PYTHONINSPECT', 'PYTHONBREAKPOINT', 'BASH_ENV', 'ENV', 'PROMPT_COMMAND', 'SHELLOPTS', 'BASHOPTS', 'PERL5OPT',
    'NODE_OPTIONS', 'RUBYOPT', 'SSH_AUTH_SOCK', 'SSH_AGENT_PID', 'GPG_AGENT_INFO', 'DBUS_SESSION_BUS_ADDRESS',
    'KRB5CCNAME', 'XAUTHORITY', 'DISPLAY', 'WAYLAND_DISPLAY', 'CLAUDECODE', 'HOME', 'TMPDIR', 'TMP', 'TEMP',
})
FORBIDDEN_PATTERNS = (
    re.compile(r'_UTC$'),
    re.compile(r'PROXY', re.I),
    re.compile(r'TOKEN|SECRET|PASSW|CREDENTIAL|API_?KEY|PRIVATE_?KEY|AUTH|COOKIE|SESSION', re.I),
    re.compile(r'^(CLAUDE|CODEX|GEMINI|ANTHROPIC|OPENAI|CURSOR|OPENCODE|AIDER|COPILOT|AGENT)', re.I),
    re.compile(r'^(GIT|SVN|HG)_'),
    re.compile(r'^(AWS|AZURE|GOOGLE|GCP|GCLOUD|HF|HUGGINGFACE|WANDB|KUBE|DOCKER|PODMAN|CONTAINER)_?', re.I),
)
# Private locations inside the launch's scratch directory.
SCRATCH = {'HOME': 'home', 'TMPDIR': 'tmp', 'TMP': 'tmp', 'TEMP': 'tmp', 'XDG_CACHE_HOME': 'cache',
           'XDG_CONFIG_HOME': 'config', 'XDG_STATE_HOME': 'state', 'MPLCONFIGDIR': 'matplotlib',
           'TEXMFVAR': 'texmf-var', 'PYTHONPYCACHEPREFIX': 'pycache'}


def channels():
    """The supervisor's own channel variables a confined stage keeps (never clocks or selectors)."""
    from ravel.workflow import execution, helper_registration, machine_lease
    return (helper_registration.ENV, helper_registration.KEY_ENV, helper_registration.DEADLINE_ENV,
            machine_lease.JOB_ENV, execution.BACKEND_JOB_ENV, OUTPUT_DIR, CUSTODY)


LAUNCH_STATE = 'RAVEL_LAUNCH_STATE'


def passed_channels():
    """Variables a trusted launcher names explicitly in a capsule; never harvested from an environment.

    The WMS launch capability (a secret); the submission broker's socket and interpreter variables (a
    brokered child reaches its controller only through that declared channel); and the launch's
    persistent state root: a confined launch has no password entry for its uid and a scratch HOME,
    so its lease, custody and steering records live in the directory the controller declares and
    binds writable for every launch of that child.
    """
    from ravel.workflow import wms_policy
    from ravel.workflow.wms_broker_client import BROKER_ENV, PYTHON_ENV
    return (wms_policy.CAPABILITY_ENV, BROKER_ENV, PYTHON_ENV, LAUNCH_STATE)


def forbidden(name, kept=()):
    """Why ``name`` never enters a confined launch, or None."""
    if name in kept:
        return None
    if name.startswith('RAVEL_'):
        return 'RAVEL override'
    if name in FORBIDDEN_NAMES:
        return 'clock, private location, startup or injection hook, socket or marker'
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(name):
            return 'clock, proxy, credential, agent marker, repository or cloud setting'
    return None


def capsule_from(source):
    """The allowlisted variables of ``source`` plus the supervisor's channel variables."""
    kept = channels()
    return {name: value for name, value in source.items()
            if isinstance(value, str) and (name in ALLOWLIST or name in kept)}


def scrub(capsule):
    """``(environment, removed names)``: the capsule without any forbidden variable."""
    if not isinstance(capsule, dict):
        raise ValueError('a launch environment capsule must be an object of strings')
    kept = (*channels(), *passed_channels())
    env, removed = {}, []
    for name, value in capsule.items():
        if not isinstance(name, str) or not isinstance(value, str) or '\0' in name + value or '=' in name:
            raise ValueError('a launch environment capsule must map names to strings')
        if forbidden(name, kept):
            removed.append(name)
        else:
            env[name] = value
    return env, sorted(removed)


def launch_environment(capsule, scratch=None, extra=None):
    """``(environment, removed)`` for a launch: scrubbed capsule, private locations and ``extra`` channels."""
    env, removed = scrub(capsule)
    if scratch is not None:
        for name, sub in SCRATCH.items():
            env[name] = f'{scratch}/{sub}'
        # The sandbox hides the password database; the launch still knows which user runs it.
        if 'USER' not in env and 'LOGNAME' not in env:
            try:
                import getpass
                user = getpass.getuser()
            except (ImportError, KeyError, OSError):
                user = None
            if user:
                env['USER'] = env['LOGNAME'] = user
    for name, value in (extra or {}).items():
        if forbidden(name, (*channels(), *passed_channels())):
            raise ValueError(f'{name} is not a launcher channel variable')
        env[name] = value
    return env, removed
