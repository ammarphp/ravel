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
PROJECT_CONFIG = '.ravel/data_classification.json'
PROJECT_DECLARED = '.ravel/provider-policy.json'
PROJECT_INPUT = 'inputs/project_provider_policy.json'
PROJECT_MARKER = {'schema_version': 1, 'default': PROJECT_CONFIG}
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


def _read(path):
    try:
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise PolicyRefused('provider policy records cannot be symbolic links')
        return read_json(path)
    except (OSError, ValueError) as exc:
        raise PolicyRefused(f'provider policy unreadable or invalid: {path}: {exc}') from exc


def _present(path):
    # stat errors must not turn an inaccessible declaration into implicit public.
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise PolicyRefused(f'provider policy unreadable: {path}: {exc}') from exc


def _project_row(project, *, register=False):
    config, marker = project / PROJECT_CONFIG, project / PROJECT_DECLARED
    declared = _present(marker)
    if declared and _read(marker) != PROJECT_MARKER:
        raise PolicyRefused(f'invalid project provider policy declaration: {marker}')
    if not declared and not _present(config):
        return None
    value = classification(_read(config))
    if register and not declared:
        atomic_json(marker, PROJECT_MARKER)
    return {'project': str(project), 'data_classification': value, 'sha256': digest(value)}


def _combine(rows):
    if not rows:
        return None
    levels = ('public', 'internal', 'restricted')
    values = [row['data_classification'] for row in rows]
    return {'level': max((v['level'] for v in values), key=levels.index),
            'allowed_providers': [entry for entry in values[0]['allowed_providers']
                                  if all(entry in v['allowed_providers'] for v in values[1:])]}


def project_policy(project, *, register=False):
    """Report all enclosing project defaults; nested settings cannot erase a floor.

    Installation (or first run start) retains a declaration marker, deliberately
    separate from the editable default. Removing the default then fails closed.
    """
    root = _path(project)
    rows = []
    for parent in reversed((root, *root.parents)):
        row = _project_row(parent, register=register)
        if row is not None:
            rows.append(row)
    return {**_record(_combine(rows)), 'project_defaults': rows}


def _narrower(value, floor):
    levels = ('public', 'internal', 'restricted')
    if floor is not None and (value is None
            or levels.index(value['level']) < levels.index(floor['level'])
            or any(entry not in floor['allowed_providers'] for entry in value['allowed_providers'])):
        raise PolicyRefused('run provider policy cannot widen the project default')


def validate_run_start(run, declaration=None, input_pins=()):
    """Resolve project inheritance before creating a graph or validating its pins."""
    project = project_policy(run)
    floor = _combine(project['project_defaults'])
    value = classification(declaration) if declaration is not None else floor
    _narrower(value, floor)
    return validate_start(value, input_pins)


def initialize_project_policy(run):
    """Creation seam: projects without a default retain their existing layout."""
    if project_policy(run)['declared']:
        start(run)


def _project_inputs(root, state):
    rows = project_policy(root, register=True)['project_defaults']
    expected = state.get('project_defaults_sha256') if state else None
    if expected is not None:
        saved = _read(root / PROJECT_INPUT)
        if (type(saved) is not dict or set(saved) != {'schema_version', 'project_defaults'}
                or saved['schema_version'] != 1 or digest(saved) != expected
                or type(saved['project_defaults']) is not list or not saved['project_defaults']):
            raise PolicyRefused('project provider policy input digest changed')
        for row in saved['project_defaults']:
            if (type(row) is not dict or set(row) != {'project', 'data_classification', 'sha256'}
                    or type(row['project']) is not str or not Path(row['project']).is_absolute()
                    or digest(classification(row['data_classification'])) != row['sha256']):
                raise PolicyRefused('invalid project provider policy input')
            # A moved run still checks its originally declared project.
            live = _project_row(_path(row['project']))
            if live is None:
                raise PolicyRefused('declared project provider policy missing')
            rows.extend([row, live])
    return rows


def _path(run):
    path = Path(run).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise PolicyRefused('provider policy run cannot traverse symbolic links')
    for name in (CONFIG, PIN, LOCK, PROJECT_INPUT):
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
        if _present(parent / PIN):
            return _path(parent)
    for parent in (root, *root.parents):
        if _present(parent / CONFIG):
            return _path(parent)
    return root


def inherited_declaration(run, *, include_project=True):
    """Read an enclosing run or project declaration without creating a new run.

    Graph creation distinguishes an enclosing run (which cannot be overridden)
    from a project floor (which the new run may narrow).
    """
    root = find_run(run)
    if root is None or not (_present(root / PIN) or _present(root / CONFIG)):
        return (_combine(project_policy(root or Path.cwd())['project_defaults'])
                if include_project else None)
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
    return classification(_read(root / CONFIG)) if _present(root / CONFIG) else None


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
    state = _read(root / PIN)
    if (type(state) is not dict or not {'initial', 'changes'} <= set(state)
            or set(state) - {'initial', 'changes', 'project_defaults_sha256'}
            or type(state['changes']) is not list
            or ('project_defaults_sha256' in state and
                (type(state['project_defaults_sha256']) is not str or len(state['project_defaults_sha256']) != 64))):
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
        if data_classification is not None:
            raise PolicyRefused('a declared data classification requires a run directory')
        value = _combine(project_policy(Path.cwd(), register=True)['project_defaults'])
        validate_start(value, input_pins)
        return _record(value)
    with file_lock(root / LOCK):
        state, current = _current(root) if _present(root / PIN) else (None, None)
        changed = state is None
        rows = _project_inputs(root, state)
        floor = _combine(rows)
        configured = _configuration(root)
        value = classification(data_classification) if data_classification is not None else configured
        if value is None and state is None:
            value = floor
        _narrower(value, floor)
        validate_start(value, input_pins)
        target = _record(value)
        if state is not None:
            if current != target:
                level = current['data_classification']['level']
                raise PolicyRefused(f'{level} provider policy changed without an explicit approval record')
        if state is None:
            if value is not None:
                atomic_json(root / CONFIG, value)
            state = {'initial': target, 'changes': []}
        if rows and 'project_defaults_sha256' not in state:
            snapshot = {'schema_version': 1, 'project_defaults': rows}
            atomic_json(root / PROJECT_INPUT, snapshot)
            state['project_defaults_sha256'] = digest(snapshot)
            changed = True
        if changed:
            atomic_json(root / PIN, state)
        return target


def approve_change(run, data_classification, approval_record):
    """Apply an operator approval; records retain the initial pin and whole chain."""
    root = find_run(run)
    replacement = _record(classification(data_classification))
    with file_lock(root / LOCK):
        state, previous = _current(root)
        _narrower(replacement['data_classification'], _combine(_project_inputs(root, state)))
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
