"""Run-scoped model transport admission, pinned before dispatch.

The trusted launcher owns these records. Like other local approvals, they are
tamper evident to sandboxed workers, not authentication against the operator.
Account classes describe configured routes, not independently verified tenancy.
"""
from copy import deepcopy
from pathlib import Path

from .state_io import atomic_json, file_lock, read_json
from .transport_registry import digest

CONFIG = 'inputs/data_classification.json'
PIN = 'provider-policy/pin.json'
LOCK = 'provider-policy/policy.lock'
PUBLIC = {'level': 'public', 'allowed_providers': None}


class PolicyRefused(ValueError):
    """No model dispatch was admitted."""
    not_dispatched = True


def classification(value):
    """Validate a declaration; an empty allowlist explicitly denies every route."""
    if (type(value) is not dict or set(value) != {'level', 'allowed_providers'}
            or value['level'] not in ('restricted', 'internal', 'public')
            or type(value['allowed_providers']) is not list):
        raise PolicyRefused('data_classification requires level and allowed_providers')
    seen = set()
    for entry in value['allowed_providers']:
        if (type(entry) is not dict or set(entry) != {'transport_id', 'account_class'}
                or any(type(v) is not str or not v.strip() for v in entry.values())):
            raise PolicyRefused('allowed provider requires transport_id and account_class')
        key = (entry['transport_id'], entry['account_class'])
        if key in seen:
            raise PolicyRefused('duplicate allowed provider entry')
        seen.add(key)
    return deepcopy(value)


def restricted_inputs(pins):
    """Recognize the optional boolean restricted field on input pins/wrappers."""
    if isinstance(pins, list):
        return any([restricted_inputs(p) for p in pins])
    if isinstance(pins, dict):
        if 'restricted' in pins and type(pins['restricted']) is not bool:
            raise PolicyRefused('input pin restricted must be boolean')
        return pins.get('restricted', False) or any(
            [restricted_inputs(v) for k, v in pins.items() if k != 'restricted'])
    return False


def validate_start(declaration, input_pins=()):
    value = classification(declaration) if declaration is not None else None
    if restricted_inputs(list(input_pins)) and (value is None or value['level'] != 'restricted'):
        raise PolicyRefused('restricted input pins require an explicit restricted data_classification before run start')
    return value


def _path(run):
    path = Path(run).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise PolicyRefused('provider policy run cannot traverse symbolic links')
    for name in (CONFIG, PIN, LOCK):
        target = path / name
        if target.is_symlink() or target.parent.is_symlink():
            raise PolicyRefused('provider policy records cannot be symbolic links')
    return path


def find_run(run):
    """Nested graph roots inherit the nearest enclosing policy record."""
    if run is None:
        return None
    root = _path(run)
    # A new child declaration cannot shadow an enclosing run's existing pin.
    for parent in (root, *root.parents):
        if (parent / PIN).exists():
            return _path(parent)
    for parent in (root, *root.parents):
        if (parent / CONFIG).exists():
            return _path(parent)
    return root


def inherited_declaration(run):
    """Read and verify an enclosing run's declaration without creating a new run."""
    root = find_run(run)
    if root is None or not ((root / PIN).exists() or (root / CONFIG).exists()):
        return None
    record = start(root)
    return record['data_classification'] if record['declared'] else None


def account_class(declaration):
    """Use an explicit account class, else the existing auth-kind:billing identity.

    Legacy declarations distinguish login from API billing, but do not attest
    an organisation or tenant. Custom declarations can name that finer class.
    """
    return declaration.get('account_class') or (
        declaration['auth']['kind'] + ':' + declaration['billing'])


def _configuration(root):
    return classification(read_json(root / CONFIG)) if (root / CONFIG).exists() else None


def _record(value):
    return {'data_classification': value or deepcopy(PUBLIC), 'declared': value is not None}


def _approval(record, previous, replacement):
    keys = {'kind', 'approved', 'authority', 'approved_by', 'approved_utc', 'reason',
            'previous_sha256', 'replacement_sha256'}
    if (type(record) is not dict or set(record) != keys
            or record['kind'] != 'provider-policy-approval' or record['approved'] is not True
            or record['authority'] != 'human'
            or any(type(record[k]) is not str or not record[k].strip()
                   for k in ('approved_by', 'approved_utc', 'reason'))
            or record['previous_sha256'] != digest(previous)
            or record['replacement_sha256'] != digest(replacement)):
        raise PolicyRefused('provider policy change requires an explicit human approval bound to both policy hashes')


def _current(root):
    state = read_json(root / PIN)
    if type(state) is not dict or set(state) != {'initial', 'changes'} or type(state['changes']) is not list:
        raise PolicyRefused('invalid provider policy pin')
    current = state['initial']
    for change in state['changes']:
        _approval(change['approval'], current, change['replacement'])
        current = change['replacement']
    if (type(current) is not dict or set(current) != {'data_classification', 'declared'}
            or type(current['declared']) is not bool):
        raise PolicyRefused('invalid provider policy record')
    if current['declared']:
        classification(current['data_classification'])
    elif current['data_classification'] != PUBLIC:
        raise PolicyRefused('invalid implicit public provider policy')
    return state, current


def start(run, *, data_classification=None, input_pins=()):
    """Pin at run start. Existing runs are checked, never silently re-pinned.

    A caller may supply the declaration here or provision CONFIG before start.
    Legacy runs are pinned on their first guarded call. Child roots inherit an
    enclosing policy; a child cannot replace it by supplying a declaration.
    """
    root = find_run(run)
    if root is None:
        validate_start(data_classification, input_pins)
        if data_classification is not None:
            raise PolicyRefused('a declared data classification requires a run directory')
        return _record(None)
    with file_lock(root / LOCK):
        configured = _configuration(root)
        value = classification(data_classification) if data_classification is not None else configured
        validate_start(value, input_pins)
        target = _record(value)
        if (root / PIN).exists():
            _, current = _current(root)
            if current != target:
                level = current['data_classification']['level']
                raise PolicyRefused(f'{level} provider policy changed without an explicit approval record')
        else:
            if data_classification is not None:
                atomic_json(root / CONFIG, value)
            atomic_json(root / PIN, {'initial': target, 'changes': []})
        return target


def approve_change(run, data_classification, approval_record):
    """Apply an operator approval; records retain the initial pin and whole chain."""
    root = find_run(run)
    replacement = _record(classification(data_classification))
    with file_lock(root / LOCK):
        state, previous = _current(root)
        _approval(approval_record, previous, replacement)
        state['changes'].append({'replacement': replacement, 'approval': deepcopy(approval_record)})
        atomic_json(root / PIN, state)
        atomic_json(root / CONFIG, replacement['data_classification'])
    return replacement


def admission(run, transport_declaration, actual_account_class, *, input_pins=()):
    """Return the receipt/prompt-log fields for an admitted call, or refuse."""
    record = start(run, input_pins=input_pins)
    value = record['data_classification']
    identity = (transport_declaration or {}).get('id', 'undeclared')
    entry = {'transport_id': identity, 'account_class': actual_account_class}
    if record['declared'] and (transport_declaration is None
            or actual_account_class != account_class(transport_declaration)
            or entry not in value['allowed_providers']):
        raise PolicyRefused(f'{value["level"]} data classification refuses transport {identity} '
                            f'(account class {actual_account_class})')
    return {**record, 'admitted_entry': entry if record['declared'] else None,
            'policy_sha256': digest(record)}


def check(run, transport_declaration, account_class):
    """Public admission interface: admitting entry or PolicyRefused."""
    return admission(run, transport_declaration, account_class)['admitted_entry']


def validate_admission(value):
    """Validate the optional receipt field, retaining legacy receipt shapes."""
    if type(value) is not dict or set(value) != {'data_classification', 'declared', 'admitted_entry', 'policy_sha256'}:
        raise PolicyRefused('invalid provider admission receipt')
    record = {key: value[key] for key in ('data_classification', 'declared')}
    if type(record['declared']) is not bool or digest(record) != value['policy_sha256']:
        raise PolicyRefused('invalid provider admission policy digest')
    if record['declared']:
        classification(record['data_classification'])
        if value['admitted_entry'] not in record['data_classification']['allowed_providers']:
            raise PolicyRefused('receipt provider was not admitted')
    elif record['data_classification'] != PUBLIC or value['admitted_entry'] is not None:
        raise PolicyRefused('invalid implicit public provider admission')
    return value


def prompt_log_fields(receipt):
    """Common row projection for launcher, worker and provider model receipts."""
    value = (receipt.get('configuration', {}).get('provider_policy')
             or receipt.get('transport', {}).get('provider_policy'))
    if value is None:
        return {}  # Historical receipts make no classification claim.
    return deepcopy(validate_admission(value))
