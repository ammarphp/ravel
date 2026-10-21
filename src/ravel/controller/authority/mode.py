"""One operating mode per run, frozen into the protected store at intake.

``freeze_mode`` reads the operator configuration once and records the run's mode, budget
envelope, R3 policy, wait bound, notification command and confinement policy, together with the
provider policy and data classification in force at intake. Every route and the judgment route
read this one record; nothing later changes it: not the environment (``RAVEL_OPERATING_MODE``),
not project mode files, not a later ``ravel operator set``, not a request to a child. It follows
``operating_mode.initialize`` (the H1 freeze) with the ledger in the store instead of the run
directory: one transaction per run, the original request's digest bound into the record, a
request that asks for the physicist narrows the mode, and a request that asks for autonomy is
honoured only when the operator allows request-stated delegation. Children inherit
narrowing-only bounds.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from . import common
from .operator import BUDGET_KEYS, CONSUMER_DEFAULTS, NULLABLE_BUDGETS, default_budgets, operator_config

STRICTER_POLICY = {'conservative_default': 1, 'escalate_and_wait': 0}


def _prompt(contract):
    if type(contract) is not dict:
        raise ValueError('freeze_mode reads the task contract object')
    prompt = contract.get('prompt', '')
    if type(prompt) is not str:
        raise ValueError('task contract prompt must be text')
    return prompt


# A directly negated request to ask ("do not ask for approval", "no need to ask me for permission").
_NEGATED_ASK = re.compile(r"\b(?:do\s+not|don['’]t|never|no\s+need\s+to|need\s+not)\s+(?:need\s+to\s+)?ask\b"
                          r"[^.!?;\n]*?\b(?:approval|confirmation|permission)\b", re.I)


def request_statement(prompt):
    """An explicit mode statement in the verbatim request, as ``(mode, span or None)``, or None.

    Applies the H1 detector (``operating_mode.request_mode``) to the request with every directly
    negated request to ask ("do not ask for approval") blanked: such a phrase states no approval
    requirement. Everything else narrows exactly as in H1, including a requirement with a negation
    elsewhere in its clause ("don't start until I approve") and an unlocated mention (no span).
    """
    from ravel.workflow import operating_mode
    if not prompt:
        return None
    stated = operating_mode.request_mode(_NEGATED_ASK.sub(lambda m: ' ' * len(m.group()), prompt))
    if stated is None or stated[1] is None:
        return stated
    span = stated[1]
    return stated[0], {**span, 'text': prompt[span['start']:span['end']]}


def frozen(store, *, required=True):
    """The run's one frozen mode record (with ``id``); None only when ``required`` is false."""
    rows = [r for r in common.scan(store, common.MODE, common.MODE_SCHEMA) if r.get('run_id') == common.run_id(store)]
    if len(rows) > 1:
        raise common.AuthorityRefused('the run carries more than one operating mode record; one mode per run')
    if not rows:
        if required:
            raise common.AuthorityRefused('the operating mode was not frozen at intake; no authority can be granted')
        return None
    return rows[0]


def _lock(store):
    from ravel.workflow.state_io import file_lock
    return file_lock(store.path('authority-mode.lock'))


def _provider_policy(run_dir, project, input_pins=()):
    """The provider policy and data classification in force at intake, frozen into the record (SW25)."""
    from ravel.workflow import provider_policy
    if run_dir is not None:
        value = provider_policy.validate_run_start(Path(run_dir), input_pins=input_pins)
        rows = provider_policy.project_policy(Path(run_dir))['project_defaults']
    else:
        rows = provider_policy.project_policy(Path(project or Path.cwd()))['project_defaults']
        value = provider_policy._combine(rows)
        supplied = provider_policy.input_classification(input_pins)
        if supplied is not None:
            value = provider_policy._combine([{'data_classification': v} for v in (value, supplied) if v is not None])
        provider_policy.validate_start(value, input_pins)
    record = provider_policy._record(value)
    return {'record': record, 'project_defaults': rows, 'policy_sha256': provider_policy.digest(record)}


def _input_pins(store, contract):
    rows = store.scan('supplied')
    row = rows[-1] if rows else {}
    body = row.get('record', row)
    return [body.get('inputs', []), contract.get('request_pins', {})]


def freeze_mode(store, contract, *, run_dir=None, project=None):
    """Freeze the run's operating mode at intake; a second call returns the same record.

    ``contract`` is the pinned task contract (its ``prompt`` is the verbatim request). The
    optional ``run_dir`` lets the provider policy of the run's project be frozen with it.
    """
    prompt = _prompt(contract)
    prompt_sha256 = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    with _lock(store):
        existing = frozen(store, required=False)
        if existing is not None:
            if existing['prompt_sha256'] != prompt_sha256:
                raise common.AuthorityRefused('the operating mode belongs to a different original request')
            return existing
        config = operator_config()
        from . import autonomy
        # An expired, revoked or out-of-scope grant never freezes machine authority (N1).
        autonomy.intake_refusal(config, run_dir)
        derived = default_budgets(contract.get('route') or contract.get('route_id'))
        explicit = (config['entry'] or {}).get('budget_fields', [])
        budgets = {**derived['budgets'], **{k: config['budgets'][k] for k in explicit}}
        budget_source = {**derived['budget_source'], 'explicit_fields': sorted(explicit),
                         'derived_fields': sorted(set(BUDGET_KEYS) - set(explicit))}
        mode, statement, delegation = config['mode'], None, None
        if mode == 'autonomous':
            delegation = 'operator_configured'
        stated = request_statement(prompt)
        if stated is not None and stated[0] == 'physicist-in-the-loop':
            # A request can always narrow: asking for approval makes the run physicist-in-the-loop.
            mode, statement, delegation = 'physicist-in-the-loop', stated[1], None
        elif stated is not None and stated[0] == 'autonomous' and mode == 'physicist-in-the-loop':
            if config['allow_request_delegation']:
                mode, statement, delegation = 'autonomous', stated[1], 'request_stated'
        body = {'schema': common.MODE_SCHEMA, 'schema_version': 1, 'uid': common.uid(),
                'run_id': common.run_id(store), 'mode': mode, 'delegation': delegation,
                'operator_source': config['source'], 'operator_entry': deepcopy(config['entry']),
                'budgets': budgets, 'budget_source': budget_source, 'bounds': deepcopy(config['bounds']),
                **{k: deepcopy(config[k]) for k in CONSUMER_DEFAULTS},
                'machine_checkins': list(config['machine_checkins']), 'r3_policy': config['r3_policy'],
                'wait_bound_seconds': config['wait_bound_seconds'],
                'notify_command': deepcopy(config['notify_command']),
                'allow_unconfined': config['allow_unconfined'], 'request_statement': deepcopy(statement),
                'request_mode': stated[0] if stated is not None else None,
                'prompt_sha256': prompt_sha256, 'contract_sha256': common.digest(contract),
                'request_pins': deepcopy(contract.get('request_pins', {})),
                'provider_policy': _provider_policy(run_dir, project, _input_pins(store, contract)), 'parent': None,
                'instruction_pin': autonomy.instruction_pin(config, run_dir),
                'human_identity_authenticated': False, 'time_ns': common.now_ns()}
        return common.append(store, common.MODE, body)


def _within(child, parent, key):
    """Whether budget ``key`` at ``child`` stays within ``parent``; malformed values refuse."""
    if child is not None and (type(child) not in (int, float) or child != child or child == float('inf') or child < 0):
        raise ValueError(f'budget {key} must be a finite nonnegative number')
    if key in NULLABLE_BUDGETS:
        return parent is None or (child is not None and child <= parent)
    if child is None:
        raise ValueError(f'budget {key} must be a finite nonnegative number')
    # A record frozen before an optional ceiling existed has none for it: any finite child value narrows it.
    return parent is None or child <= parent


def _names_within(child, parent):
    return '*' in parent or ('*' not in child and set(child) <= set(parent))


def narrow(parent, requested=None):
    """Child authority from the parent's frozen record; any widening is refused.

    ``requested`` may lower budgets, shrink bounds and machine check-ins, make the mode
    physicist-in-the-loop, choose the stricter R3 policy, or shorten nothing else.
    """
    requested = deepcopy(requested or {})
    allowed = {'mode', 'budgets', 'bounds', 'machine_checkins', 'r3_policy', 'allow_unconfined', 'r3_delegation',
               'review_sandbox_fallback'}
    extra = set(requested) - allowed
    if extra:
        raise common.AuthorityRefused('a child cannot set ' + ', '.join(sorted(extra)))
    child = {k: deepcopy(parent[k]) for k in ('mode', 'delegation', 'budgets', 'bounds', 'machine_checkins',
                                             'r3_policy', 'wait_bound_seconds', 'notify_command', 'allow_unconfined')}
    child.update({k: deepcopy(parent.get(k, value)) for k, value in CONSUMER_DEFAULTS.items()})
    child['budget_source'] = deepcopy(parent.get('budget_source', {'kind': 'inherited'}))
    if 'mode' in requested:
        if requested['mode'] not in common.MODES:
            raise ValueError('unknown operating mode')
        if requested['mode'] == 'autonomous' and parent['mode'] != 'autonomous':
            raise common.AuthorityRefused('a child cannot become autonomous under a physicist-in-the-loop parent')
        child['mode'] = requested['mode']
        if child['mode'] == 'physicist-in-the-loop':
            child['delegation'] = None
    for key, value in (requested.get('budgets') or {}).items():
        if key not in BUDGET_KEYS:
            raise ValueError(f'unknown budget {key!r}')
        if not _within(value, parent['budgets'].get(key), key):
            raise common.AuthorityRefused(f'a child cannot widen budget {key} beyond its parent')
        child['budgets'][key] = value
    for key, value in (requested.get('bounds') or {}).items():
        if key not in ('rungs', 'allowed_stages') or type(value) is not list:
            raise ValueError(f'unknown or malformed bound {key!r}')
        if not _names_within(value, parent['bounds'][key]):
            raise common.AuthorityRefused(f'a child cannot widen bound {key} beyond its parent')
        child['bounds'][key] = list(value)
    if 'machine_checkins' in requested:
        if not set(requested['machine_checkins']) <= set(parent['machine_checkins']):
            raise common.AuthorityRefused('a child cannot add machine check-ins beyond its parent')
        child['machine_checkins'] = list(requested['machine_checkins'])
    if 'r3_policy' in requested:
        if requested['r3_policy'] not in STRICTER_POLICY:
            raise ValueError('unknown R3 policy')
        if STRICTER_POLICY[requested['r3_policy']] > STRICTER_POLICY[parent['r3_policy']]:
            raise common.AuthorityRefused('a child cannot take a less strict R3 policy than its parent')
        child['r3_policy'] = requested['r3_policy']
    if 'r3_delegation' in requested:
        wanted = requested['r3_delegation']
        if type(wanted) is not list or not set(wanted) <= set(parent.get('r3_delegation') or []):
            raise common.AuthorityRefused('a child cannot delegate R3 decisions beyond its parent')
        child['r3_delegation'] = list(wanted)
    if 'allow_unconfined' in requested:
        if requested['allow_unconfined'] and not parent['allow_unconfined']:
            raise common.AuthorityRefused('a child cannot allow unconfined execution its parent does not')
        child['allow_unconfined'] = bool(requested['allow_unconfined'])
    if 'review_sandbox_fallback' in requested:
        wanted = requested['review_sandbox_fallback']
        if wanted not in ('none', parent.get('review_sandbox_fallback', 'none')):
            raise common.AuthorityRefused('a child cannot take a review sandbox fallback its parent does not allow')
        child['review_sandbox_fallback'] = wanted
    return child


def freeze_child(store, parent_store, contract, requested=None):
    """Freeze a child run's mode from its parent's record, narrowing only."""
    from . import stop
    state = stop.check(parent_store, 'create child')
    if state['revoked']:
        raise common.AuthorityRefused('cannot delegate from a revoked parent')
    parent = frozen(parent_store)
    effective = effective_bounds(parent_store)
    parent = {**parent, 'budgets': effective['budgets'], 'bounds': effective['bounds']}
    prompt_sha256 = hashlib.sha256(_prompt(contract).encode('utf-8')).hexdigest()
    with _lock(store):
        existing = frozen(store, required=False)
        if existing is not None:
            if existing['prompt_sha256'] != prompt_sha256 or (existing.get('parent') or {}).get('mode_record') != parent['id']:
                raise common.AuthorityRefused('the child mode belongs to a different request or parent')
            return existing
        child = narrow(parent, requested)
        from ravel.workflow import provider_policy
        child_inputs = _input_pins(store, contract)
        parent_policy = parent['provider_policy']['record']
        provider_policy.validate_start(parent_policy['data_classification'] if parent_policy['declared'] else None,
                                       child_inputs)
        body = {'schema': common.MODE_SCHEMA, 'schema_version': 1, 'uid': common.uid(),
                'run_id': common.run_id(store), **child, 'operator_source': parent['operator_source'],
                'operator_entry': deepcopy(parent['operator_entry']), 'request_statement': None,
                'request_mode': None, 'prompt_sha256': prompt_sha256, 'contract_sha256': common.digest(contract),
                'request_pins': deepcopy(contract.get('request_pins', {})),
                'provider_policy': deepcopy(parent['provider_policy']),
                'instruction_pin': deepcopy(parent.get('instruction_pin')),
                'parent': {'run_id': parent['run_id'], 'mode_record': parent['id']},
                'human_identity_authenticated': False, 'time_ns': common.now_ns()}
        return common.append(store, common.MODE, body)


def effective_bounds(store, _seen=()):
    """The frozen envelope narrowed by every approved steering record, in order.

    Steering lowers ceilings and shrinks bounds; a widening steering record counts only with the
    physicist's terminal answer or the operator's own command (``request`` enforces that).
    """
    if common.run_id(store) in _seen or len(_seen) >= 64:
        raise common.AuthorityRefused('cyclic or excessive authority ancestry')
    _seen = (*_seen, common.run_id(store))
    mode = frozen(store)
    current = {'budgets': deepcopy(mode['budgets']), 'bounds': deepcopy(mode['bounds']),
               'mode_record': mode['id'], 'steering_records': []}
    for record in common.scan(store, common.AUTHORITY, common.SCHEMA):
        if (record.get('kind') != 'steering' or record.get('decision') != 'approve'
                or record.get('run_id') != mode['run_id'] or not record.get('authorizes_effects')
                or record.get('mode_record') != mode['id'] or record.get('label') not in common.LABELS):
            continue
        policy = (record.get('bounds') or {}).get('policy') or {}
        for key, value in (policy.get('budgets') or {}).items():
            current['budgets'][key] = value
        for key, value in (policy.get('bounds') or {}).items():
            current['bounds'][key] = list(value)
        current['steering_records'].append(record['id'])
    # Frozen operator ceilings remain outer limits even for an operator steering answer.
    current = intersect(current, mode)
    parent = mode.get('parent')
    if parent is not None:
        ancestor = common.open_store(parent['run_id'])
        if frozen(ancestor)['id'] != parent['mode_record']:
            raise common.AuthorityRefused('ancestor mode dependency changed')
        current = intersect(current, effective_bounds(ancestor, _seen))
    return current


def intersect(current, upper):
    current = deepcopy(current)
    for key, ceiling in upper['budgets'].items():
        value = current['budgets'].get(key)
        if ceiling is not None:
            current['budgets'][key] = ceiling if value is None else min(value, ceiling)
    for key, permitted in upper['bounds'].items():
        present = current['bounds'][key]
        if '*' not in permitted:
            current['bounds'][key] = list(permitted) if '*' in present else [p for p in present if p in permitted]
    return current


def policy_widens(current, policy):
    """The budget and bound keys a steering policy would widen relative to ``current``."""
    widened = []
    for key, value in (policy.get('budgets') or {}).items():
        if key not in BUDGET_KEYS:
            raise ValueError(f'unknown budget {key!r}')
        if not _within(value, current['budgets'].get(key), key):
            widened.append(f'budgets.{key}')
    for key, value in (policy.get('bounds') or {}).items():
        if key not in ('rungs', 'allowed_stages') or type(value) is not list:
            raise ValueError(f'unknown or malformed bound {key!r}')
        if not _names_within(value, current['bounds'][key]):
            widened.append(f'bounds.{key}')
    extra = set(policy) - {'budgets', 'bounds'}
    if extra:
        raise ValueError('a steering policy sets budgets and bounds only; unknown: ' + ', '.join(sorted(extra)))
    return widened
