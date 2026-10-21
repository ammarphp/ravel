"""The operator ledger: the operator's configuration, outside every worker's reach.

``ravel operator init|set`` appends the operator's configuration to a hash-chained ledger in the
operator area of the controller home. The controller home is fixed by the password database
(never ``HOME``, ``RAVEL_STATE_DIR`` or ``RAVEL_WORK_ROOT``), private to the user (0700), and
lies outside every sandbox: workers and governed launches can neither read nor write it. A
root-owned operator ledger under ``/etc/ravel/operator-authority`` (``operating_mode``), where
present, is the stronger source and overrides this ledger.

The configuration sets one operating mode for every run and route, the budget envelope, the R3
policy, the wait bound, the notification command, whether unconfined execution is allowed, and
the store root. A run freezes it at intake; later changes affect only later runs.

The configuration and authority records are MACed by the key created at operator init,
held at a password-database-fixed location outside the controller store and all worker mounts.
An unconfined same-uid process can still steal that key; receipts must disclose this boundary.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import pwd
import re
import stat

from . import common

SCHEMA = 'operator-config.v1'
LEDGER = 'operator/ledger.jsonl'
# The root-owned ledger is keyed by this target path (operating_mode._operator_records).
ROOT_TARGET = 'operator/config'
RUNGS = ('none', 'dry', 'smoke', 'pilot', 'full', 'scan')
# Ceilings every operator configuration names (earlier ledgers carry exactly these).
CORE_BUDGET_KEYS = ('wall_seconds', 'model_calls', 'tokens', 'cost_usd', 'core_hours', 'events', 'children',
                    'concurrency', 'review_rounds', 'replans', 'max_redos')
# Optional ceilings in units that fit supplied data and batch work; absent or null means not configured
# (reported as unbounded, never as zero). ``input_bytes``/``input_files`` count supplied data read,
# ``batch_cpu_hours`` and ``batch_jobs`` count batch work, ``stage_wall_seconds`` caps one effect's own
# driver wall time (never a batch job's wall time, which ``batch_cpu_hours`` counts).
# ``recoveries`` bounds the governed recovery plans one run may make (``controller.recovery``); it is always finite.
OPTIONAL_BUDGET_KEYS = ('input_bytes', 'input_files', 'batch_cpu_hours', 'batch_jobs', 'stage_wall_seconds',
                        'recoveries', 'retained_disk_bytes')
BUDGET_KEYS = CORE_BUDGET_KEYS + OPTIONAL_BUDGET_KEYS
NULLABLE_BUDGETS = ('cost_usd', 'input_bytes', 'input_files', 'batch_cpu_hours', 'batch_jobs', 'stage_wall_seconds',
                    'retained_disk_bytes')
FRACTIONAL_BUDGETS = ('cost_usd', 'core_hours', 'batch_cpu_hours')
MACHINE_CHECKINS = ('approve_plan', 'go', 'deviation', 'final', 'assumption')
# The check-ins a new configuration delegates when the operator names none. ``assumption`` (a machine-reasoned
# answer to an unanswered question with no plan-declared default, ``controller.graph`` assumptions) is never
# delegated by default: the operator opts in by naming it.
DEFAULT_MACHINE_CHECKINS = ('approve_plan', 'go', 'deviation', 'final')
# R3 decisions the operator may delegate to machine authority in autonomous mode, by name (closed vocabulary).
# ``final_task``: accept the exact final-task action of CHECK-IN 3 when it classifies R3 (with ``final`` among the
# machine check-ins). Every other R3 decision still escalates and waits.
R3_DELEGATIONS = ('final_task',)
DEFAULT_BUDGETS = {'wall_seconds': 14400, 'model_calls': 500, 'tokens': 5_000_000, 'cost_usd': None,
                   'core_hours': 16, 'events': 100_000, 'children': 16, 'concurrency': 2, 'review_rounds': 3,
                   'replans': 3, 'max_redos': 0, **{key: None for key in OPTIONAL_BUDGET_KEYS}, 'recoveries': 2}
DEFAULT_BOUNDS = {'rungs': list(RUNGS), 'allowed_stages': ['*']}
CONSUMER_DEFAULTS = {'harness': None, 'engagement': {'minimum_tier': None}, 'restricted_sources': None,
                     'compute_policy': {'mode': 'bounded'},
                     'remote_job_ceiling': 0, 'procedure_byte_ceiling': 1048576,
                     'agent_preferences': None, 'site_resource_ceilings': None,
                     # The grant (N1): when it ends, which project trees it covers, the run deadline and its
                     # margin, the project instruction document every agent receives, and the free-space floor.
                     'expires_at': None, 'project_scope': None, 'deadline': None, 'instruction_document': None,
                     'disk_free_floor_bytes': None, 'r3_delegation': [],
                     # Review seats where the OS worker sandbox cannot run them: hold (``none``) or run the
                     # restricted broker-only reviewer without OS confinement, labelled (``restricted-unsandboxed``).
                     'review_sandbox_fallback': 'none'}
REVIEW_SANDBOX_FALLBACKS = ('none', 'restricted-unsandboxed')
UTC_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def budget_integer(key):
    """Whether budget ``key`` is counted in whole units."""
    return key not in FRACTIONAL_BUDGETS


def parse_utc(value):
    """Seconds since the epoch of a ``YYYY-MM-DDTHH:MM:SSZ`` time; ``ValueError`` otherwise."""
    from datetime import datetime, timezone
    if type(value) is not str:
        raise ValueError('a time is YYYY-MM-DDTHH:MM:SSZ (UTC)')
    return datetime.strptime(value, UTC_FORMAT).replace(tzinfo=timezone.utc).timestamp()


def default_budgets(route):
    """Return ``{budgets, budget_source}`` for absent operator budget fields.

    The installed envelope supplies absent ceilings. Unknown or stale projections hold.
    Intake applies explicit ceilings afterwards and freezes this provenance once.
    """
    from ravel.controller.graph import service
    provider = getattr(service('authority'), 'envelope', None)
    if provider is None:
        from ravel.controller.engagement import envelope as provider
    budgets = deepcopy(DEFAULT_BUDGETS)
    try:
        installed = provider.data('envelopes.json')
        if installed.get('status') != 'ready':
            raise common.AuthorityRefused('engagement projection unavailable; rebuild or request budget authority')
        helper = getattr(provider, 'defaults', None)
        if not callable(helper):
            raise common.AuthorityRefused('installed engagement envelopes require a defaults provider')
        derived = helper(route)
        if type(derived) is not dict or set(derived) - set(BUDGET_KEYS):
            raise common.AuthorityRefused('engagement defaults must contain budget ceilings only')
        budgets.update(derived)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise common.AuthorityRefused('engagement budget defaults refused: ' + str(exc)) from exc
    source = {'kind': 'engagement_envelope', 'route': route, 'sha256': installed.get('sha256'),
              'tier': route.get('tier', 'full') if isinstance(route, dict) else 'full',
              'margin_fraction': getattr(provider, 'DEFAULT_MARGIN', .25)}
    for key, value in budgets.items():
        if value is None and key in NULLABLE_BUDGETS:
            continue
        if not _number(value, integer=budget_integer(key)):
            raise common.AuthorityRefused(f'invalid derived budget {key}')
    return {'budgets': budgets, 'budget_source': source}


def controller_home():
    """The controller's private state directory for this user.

    The password database fixes it, so no environment value relocates it. A process inside a
    marked test lock domain (``machine_lease``) uses that domain instead.
    """
    from ravel.workflow import machine_lease
    path, kind = machine_lease._resolve()
    if kind == 'test':
        return Path(path) / 'ravel-controller'
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / '.local/state/ravel-controller'


def private_dir(path):
    """Create ``path`` (and missing parents) as a 0700 directory owned by this user; refuse symlinks."""
    path = Path(path)
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise common.AuthorityRefused(f'controller state path {parent} must not be a symbolic link')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise common.AuthorityRefused(f'controller state directory {path} must be a directory owned by this user')
    if info.st_mode & 0o077:
        os.chmod(path, 0o700)
    return path


def default_config():
    return {'schema_version': 1, 'schema': SCHEMA, 'mode': 'physicist-in-the-loop',
            'budgets': deepcopy(DEFAULT_BUDGETS), 'bounds': deepcopy(DEFAULT_BOUNDS),
            'machine_checkins': list(DEFAULT_MACHINE_CHECKINS), 'r3_policy': 'escalate_and_wait',
            'wait_bound_seconds': 3600, 'notify_command': None, 'allow_unconfined': False,
            'allow_request_delegation': False, 'store_root': str(controller_home() / 'runs'),
            **deepcopy(CONSUMER_DEFAULTS)}


def _number(value, *, integer):
    if integer:
        return type(value) is int and value >= 0
    return type(value) in (int, float) and value == value and value >= 0 and value != float('inf')


def validate_argv(command):
    """A bounded explicit argv list (no shell) or None."""
    if command is None:
        return None
    if (type(command) is not list or not command or len(command) > 32
            or any(type(v) is not str or not v or '\0' in v for v in command)
            or sum(len(v.encode()) for v in command) > 8192):
        raise ValueError('notify_command must be an explicit bounded argv list')
    return list(command)


def validate(config):
    """A complete, closed operator configuration; raises ``ValueError`` otherwise."""
    keys = set(default_config())
    if (type(config) is not dict or set(config) - keys
            or keys - set(config) - set(CONSUMER_DEFAULTS)):
        raise ValueError('operator configuration requires exactly: ' + ', '.join(sorted(keys)))
    config = {**deepcopy(CONSUMER_DEFAULTS), **deepcopy(config)}
    if config['schema_version'] != 1 or config['schema'] != SCHEMA:
        raise ValueError(f'operator configuration schema must be {SCHEMA}')
    if config['mode'] not in common.MODES:
        raise ValueError('operating mode must be one of ' + ', '.join(common.MODES))
    budgets = config['budgets']
    from ravel.controller.engagement.compute import validate as validate_compute_policy
    validate_compute_policy(config['compute_policy'])
    if (type(budgets) is not dict or set(budgets) - set(BUDGET_KEYS)
            or set(CORE_BUDGET_KEYS) - set(budgets)):
        raise ValueError('budgets require exactly: ' + ', '.join(CORE_BUDGET_KEYS)
                         + ' (optional: ' + ', '.join(OPTIONAL_BUDGET_KEYS) + ')')
    budgets = config['budgets'] = {**{key: DEFAULT_BUDGETS[key] for key in OPTIONAL_BUDGET_KEYS}, **budgets}
    for key, value in budgets.items():
        if key in NULLABLE_BUDGETS:
            if value is not None and not _number(value, integer=budget_integer(key)):
                raise ValueError(f'budget {key} is a finite nonnegative number or null (not configured)')
        elif not _number(value, integer=budget_integer(key)):
            raise ValueError(f'budget {key} must be a finite nonnegative number')
    bounds = config['bounds']
    if type(bounds) is not dict or set(bounds) != {'rungs', 'allowed_stages'}:
        raise ValueError('bounds require rungs and allowed_stages')
    for key in ('rungs', 'allowed_stages'):
        rows = bounds[key]
        if (type(rows) is not list or len(rows) > 256 or len(set(rows)) != len(rows)
                or any(type(r) is not str or not re.fullmatch(r'[A-Za-z0-9_*.-]+', r) for r in rows)):
            raise ValueError(f'bounds {key} must be a finite list of distinct names')
    if not set(bounds['rungs']) <= set(RUNGS):
        raise ValueError('unknown compute plan in bounds; plans are ' + ', '.join(RUNGS))
    checkins = config['machine_checkins']
    if type(checkins) is not list or len(set(checkins)) != len(checkins) or not set(checkins) <= set(MACHINE_CHECKINS):
        raise ValueError('machine_checkins is a list drawn from ' + ', '.join(MACHINE_CHECKINS))
    if config['r3_policy'] not in common.R3_POLICIES:
        raise ValueError('r3_policy must be one of ' + ', '.join(common.R3_POLICIES))
    if type(config['wait_bound_seconds']) is not int or not 0 <= config['wait_bound_seconds'] <= 30 * 86400:
        raise ValueError('wait_bound_seconds must be an integer between 0 and 30 days')
    validate_argv(config['notify_command'])
    for key in ('allow_unconfined', 'allow_request_delegation'):
        if type(config[key]) is not bool:
            raise ValueError(f'{key} must be true or false')
    if config['harness'] is not None and type(config['harness']) is not dict:
        raise ValueError('harness must be an object or null')
    engagement = config['engagement']
    if (type(engagement) is not dict or set(engagement) != {'minimum_tier'}
            or engagement['minimum_tier'] not in (None, 'lean', 'standard', 'full')):
        raise ValueError('engagement requires minimum_tier: null, lean, standard or full (raise-only)')
    restricted = config['restricted_sources']
    if restricted is not None and (type(restricted) is not str or not Path(restricted).is_absolute()
                                   or '\0' in restricted):
        raise ValueError('restricted_sources must be an absolute path or null')
    for name in ('remote_job_ceiling', 'procedure_byte_ceiling'):
        if not _number(config[name], integer=True):
            raise ValueError(f'{name} must be a nonnegative integer')
    prefs = config['agent_preferences']
    if prefs is not None:
        allowed = {'schema_version', 'kind', 'transport_preference', 'families', 'tier_models', 'model_families'}
        if (type(prefs) is not dict or set(prefs) - allowed or prefs.get('schema_version') != 1
                or prefs.get('kind') != 'agent-preferences' or type(prefs.get('transport_preference')) is not list
                or any(type(v) is not str or not v.strip() for v in prefs['transport_preference'])
                or len(set(prefs['transport_preference'])) != len(prefs['transport_preference'])
                or any(type(prefs[k]) is not dict for k in ('families', 'tier_models', 'model_families') if k in prefs)):
            raise ValueError('agent_preferences must be an agent-preferences document or null')
    ceilings = config['site_resource_ceilings']
    if ceilings is not None and (type(ceilings) is not dict or any(type(k) is not str or not k
            or not _number(v, integer=False) for k, v in ceilings.items())):
        raise ValueError('site_resource_ceilings must contain finite nonnegative ceilings or be null')
    _validate_grant(config)
    common.canonical(config)
    root = config['store_root']
    if type(root) is not str or not Path(root).is_absolute() or '\0' in root:
        raise ValueError('store_root must be an absolute path')
    from . import issuer
    resolved = Path(root).resolve()
    for protected in (issuer.home().resolve(), ledger_path().parent.resolve()):
        if resolved == protected or resolved in protected.parents or protected in resolved.parents:
            raise ValueError('store_root must be separate from operator and issuer state')
    return deepcopy(config)


def agent_preference_problems(prefs):
    """One remedy sentence per ``tier_models`` model the model catalogue flags; [] without a catalogue.

    The operator CLI refuses on these before writing. ``validate`` does not call this: synthetic
    fixture preferences reach ``init`` directly, and a frozen run record only labels its problems.
    """
    import importlib
    try:
        catalogue = importlib.import_module('ravel.workflow.model_catalogue')
    except ImportError:
        return []
    tiers = (prefs or {}).get('tier_models') if type(prefs) is dict else None
    if type(tiers) is not dict:
        return []
    messages = []
    for tier in sorted(tiers):
        routes = tiers[tier]
        if type(routes) is not dict:
            continue
        for transport in sorted(routes):
            model = routes[transport]
            if catalogue.problem(model) is not None:
                message = catalogue.remedy(model)
                if message not in messages:
                    messages.append(message)
    return messages


def _validate_grant(config):
    """The grant's expiry, project scope, deadline, instruction document and free-space floor."""
    if config['expires_at'] is not None:
        parse_utc(config['expires_at'])
    scope = config['project_scope']
    if scope is not None and (type(scope) is not list or not 1 <= len(scope) <= 64 or len(set(scope)) != len(scope)
                              or any(type(p) is not str or '\0' in p or not Path(p).is_absolute() for p in scope)):
        raise ValueError('project_scope is a list of distinct absolute project paths or null')
    deadline = config['deadline']
    if deadline is not None:
        if type(deadline) is not dict or set(deadline) != {'at', 'margin_seconds'}:
            raise ValueError('deadline is {at: YYYY-MM-DDTHH:MM:SSZ, margin_seconds} or null')
        parse_utc(deadline['at'])
        if type(deadline['margin_seconds']) is not int or not 0 <= deadline['margin_seconds'] <= 30 * 86400:
            raise ValueError('deadline margin_seconds is an integer between 0 and 30 days')
    document = config['instruction_document']
    if document is not None and (type(document) is not str or '\0' in document or not Path(document).is_absolute()):
        raise ValueError('instruction_document is an absolute path or null')
    delegated = config['r3_delegation']
    if (type(delegated) is not list or len(set(delegated)) != len(delegated)
            or not set(delegated) <= set(R3_DELEGATIONS)):
        raise ValueError('r3_delegation is a list drawn from ' + ', '.join(R3_DELEGATIONS))
    if config['review_sandbox_fallback'] not in REVIEW_SANDBOX_FALLBACKS:
        raise ValueError('review_sandbox_fallback is one of ' + ', '.join(REVIEW_SANDBOX_FALLBACKS))
    floor = config['disk_free_floor_bytes']
    if floor is not None and not _number(floor, integer=True):
        raise ValueError('disk_free_floor_bytes is a nonnegative integer or null')


def ledger_path():
    return controller_home() / LEDGER


def _ledger_rows():
    from ravel.workflow import rdj_custody
    path = ledger_path()
    if path.is_symlink():
        raise common.AuthorityRefused('the operator ledger must not be a symbolic link')
    try:
        rows = rdj_custody._read(path)
    except rdj_custody.CustodyError as exc:
        # An edited, truncated or reordered ledger is no configuration: it refuses, typed.
        raise common.AuthorityRefused(f'the operator ledger does not verify: {exc}') from None
    from . import issuer
    context = ['operator-config', str(path.resolve())]
    for row in rows:
        issuer.authenticate(row['record'], context)
    if rows or (issuer.home() / 'issuer.key').exists() or issuer.journal_path(context).exists():
        anchors = issuer.journal(context)
        if [common.digest(row) for row in rows] != [a['sha256'] for a in anchors]:
            raise common.AuthorityRefused('operator ledger differs from issuer history')
    return rows


def _root_config():
    """The root-owned operator ledger's latest configuration, or None where none is provisioned."""
    from ravel.workflow import operating_mode
    target = controller_home() / ROOT_TARGET
    try:
        rows = operating_mode._operator_records('setting', target)
    except operating_mode.MissingOperatorReceipt:
        return None
    if not rows:
        return None
    row = rows[-1]
    config = validate(row['record']['value'])
    return config, {'seq': row['seq'], 'digest': row['digest'],
                    'sha256': common.digest(row['record']['value']),
                    'budget_fields': sorted(row['record']['value']['budgets'])}


def operator_config():
    """The effective operator configuration with ``source`` and ``entry`` (ledger evidence).

    Sources in order: the root-owned ledger, the operator ledger, then the conservative default
    (physicist-in-the-loop, no machine authority). A present but invalid ledger refuses.
    """
    root = _root_config()
    if root is not None:
        config, entry = root
        return {**config, 'source': 'operator_ledger_root', 'entry': entry}
    rows = _ledger_rows()
    if not rows:
        return {**default_config(), 'source': 'default', 'entry': None}
    row = rows[-1]
    record = row['record']
    config = validate(record.get('config'))
    if record.get('config_sha256') != common.digest(record.get('config')):
        raise common.AuthorityRefused('operator ledger entry does not match its configuration digest')
    return {**config, 'source': 'operator_ledger', 'entry': {'seq': row['seq'], 'digest': row['digest'],
                                                             'sha256': record['config_sha256'],
                                                             'budget_fields': _budget_fields(record)}}


def _budget_fields(record):
    # Legacy values remain explicit ceilings, including values equal to old defaults.
    fields = record.get('budget_fields', list(record['config']['budgets']))
    if type(fields) is not list or any(type(k) is not str for k in fields) or not set(fields) <= set(BUDGET_KEYS):
        raise common.AuthorityRefused('operator budget provenance is malformed')
    return sorted(set(fields))


def _refuse_agent(action):
    from ravel.workflow.approval_authority import AGENT_MARKERS
    present = [name for name in AGENT_MARKERS if name in os.environ]
    if present:
        raise common.AuthorityRefused(f'{action} is an operator action; an agent session ({present[0]}) is refused')


def _write(action, config, *, budget_fields=None, extra=None):
    from ravel.workflow import rdj_custody
    _refuse_agent(f'ravel operator {action}')
    config = validate(config)
    path = ledger_path()
    private_dir(path.parent)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    from . import issuer
    record = issuer.seal({'schema_version': 1, 'kind': 'operator-config', 'action': action,
                         'config': config, 'config_sha256': common.digest(config),
                         'budget_fields': sorted(config['budgets'] if budget_fields is None else budget_fields),
                         'operator_uid': os.getuid(), **(extra or {})}, ['operator-config', str(path.resolve())])
    from ravel.workflow.state_io import file_lock
    context = ['operator-config', str(path.resolve())]
    with file_lock(issuer.journal_path(context).with_suffix('.lock')):
        rows = _ledger_rows()
        row = rdj_custody._append(path, record)
        issuer.anchor(context, [{'sha256': common.digest(r)} for r in [*rows, row]])
    os.chmod(path, 0o600)
    return {**config, 'source': 'operator_ledger',
            'entry': {'seq': row['seq'], 'digest': row['digest'], 'sha256': common.digest(config),
                      'budget_fields': _budget_fields(record)}}


def init(*, mode, budgets=None, bounds=None, machine_checkins=None, r3_policy='escalate_and_wait',
         wait_bound_seconds=3600, notify_command=None, allow_unconfined=False, allow_request_delegation=False,
         store_root=None, harness=None, engagement=None, restricted_sources=None, remote_job_ceiling=0,
         procedure_byte_ceiling=1048576, agent_preferences=None, site_resource_ceilings=None, expires_at=None,
         project_scope=None, deadline=None, instruction_document=None, disk_free_floor_bytes=None,
         r3_delegation=None, review_sandbox_fallback='none', compute_policy=None):
    """Write the first operator configuration; a second ``init`` is refused (use ``set``)."""
    if _ledger_rows():
        raise common.AuthorityRefused('the operator ledger is already initialized; change it with `ravel operator set`')
    config = default_config()
    config.update(mode=mode, r3_policy=r3_policy, wait_bound_seconds=wait_bound_seconds,
                  notify_command=notify_command, allow_unconfined=allow_unconfined,
                  allow_request_delegation=allow_request_delegation, harness=harness,
                  engagement=deepcopy(engagement if engagement is not None else CONSUMER_DEFAULTS['engagement']),
                  compute_policy=deepcopy(compute_policy if compute_policy is not None else
                                          CONSUMER_DEFAULTS['compute_policy']),
                  restricted_sources=restricted_sources, remote_job_ceiling=remote_job_ceiling,
                  procedure_byte_ceiling=procedure_byte_ceiling, agent_preferences=deepcopy(agent_preferences),
                  site_resource_ceilings=deepcopy(site_resource_ceilings), expires_at=expires_at,
                  project_scope=deepcopy(project_scope), deadline=deepcopy(deadline),
                  instruction_document=instruction_document, disk_free_floor_bytes=disk_free_floor_bytes,
                  r3_delegation=list(r3_delegation or []), review_sandbox_fallback=review_sandbox_fallback)
    if budgets:
        config['budgets'].update(budgets)
    if bounds:
        config['bounds'].update(bounds)
    if machine_checkins is not None:
        config['machine_checkins'] = list(machine_checkins)
    if store_root is not None:
        config['store_root'] = str(Path(store_root).expanduser())
    from . import issuer
    validate(config)
    issuer.initialize()
    return _write('init', config, budget_fields=list(budgets or {}))


def set_values(changes):
    """Apply changes to the current ledger configuration; nested budgets and bounds merge by key."""
    rows = _ledger_rows()
    if not rows:
        raise common.AuthorityRefused('no operator ledger yet; start with `ravel operator init --mode ...`')
    if type(changes) is not dict or not changes:
        raise ValueError('ravel operator set needs at least one change')
    config = validate(rows[-1]['record']['config'])
    for key, value in changes.items():
        if key in ('budgets', 'bounds'):
            if type(value) is not dict:
                raise ValueError(f'{key} changes are a mapping')
            config[key].update(value)
        elif key == 'store_root':
            config[key] = str(Path(value).expanduser()) if type(value) is str else value
        elif key in config and key not in ('schema', 'schema_version'):
            config[key] = value
        else:
            raise ValueError(f'unknown operator setting {key!r}')
    fields = set(_budget_fields(rows[-1]['record'])) | set(changes.get('budgets', {}))
    return _write('set', config, budget_fields=fields)


def revoke_grant(reason):
    """Withdraw the operator grant for every run frozen under an earlier entry, and for later runs.

    The revocation is a ledger entry: runs frozen under an earlier entry find it at their next
    boundary and end qualified (``authority_revoked``); later runs start physicist-in-the-loop with
    no machine check-ins until the operator writes a new grant (``ravel operator set --mode autonomous``).
    """
    rows = _ledger_rows()
    if not rows:
        raise common.AuthorityRefused('no operator ledger yet; there is no grant to revoke')
    if type(reason) is not str or not reason.strip():
        raise ValueError('a revocation states its reason')
    config = validate(rows[-1]['record']['config'])
    config.update(mode='physicist-in-the-loop', machine_checkins=[], allow_request_delegation=False, r3_delegation=[],
                  review_sandbox_fallback='none')
    return _write('revoke', config, budget_fields=_budget_fields(rows[-1]['record']),
                  extra={'revokes': [row['digest'] for row in rows], 'reason': reason.strip()})


def grant_history(entry):
    """``(rows after the frozen ``entry``, None)`` from the authenticated ledger, or ``(None, problem)``.

    ``problem`` is ``authority_invalid`` when the ledger no longer authenticates (edited, copied or
    re-dated without the operator's key) and ``authority_missing`` when the entry is not in it.
    """
    try:
        rows = _ledger_rows()
    except (common.AuthorityRefused, OSError, ValueError, KeyError, TypeError) as exc:
        return None, ('authority_invalid', f'the operator ledger does not authenticate: {exc}'[:500])
    digest = (entry or {}).get('digest')
    for index, row in enumerate(rows):
        if row['digest'] == digest and row['seq'] == (entry or {}).get('seq'):
            return rows[index + 1:], None
    return None, ('authority_missing', 'the operator ledger no longer holds the entry this run was frozen under')


def store_root():
    path = Path(operator_config()['store_root'])
    return path
