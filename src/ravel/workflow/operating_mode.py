"""Operator defaults, frozen at intake; no authority from editable run files alone.

Autonomous choices require an externally provisioned, protected operator receipt.
Environment values, session markers and same-user custody do not authenticate an
operator. The consuming CLI cannot issue receipts. A deployment must provision a
separate operator service and confine agents away from trusted runtime/custody.
Without that service an explicit request statement selects no operating-mode
authority; it stays with the retained text-delegation paths, as before this module.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from . import execution, rdj_custody, state_io
from .approval_authority import AGENT_MARKERS

MODES = ('autonomous', 'physicist-in-the-loop')
RUN_RECORD = 'inputs/operating-mode.json'
CONFIG = 'operating-mode.json'
_RUN_STATE = ('run_state.json', 'execution_state.json', 'inputs/checkin1_approval.json', 'inputs/science-approval.json')
DEFAULT_BOUNDS = {
    'compute_plans': ['none', 'dry', 'smoke', 'full', 'scan'],
    'allowed_stages': ['prepare', 'madgraph', 'pythia', 'delphes', 'analysis', 'likelihood', 'science'],
    'max_seconds': 3600, 'max_events': 100000, 'max_redos': 0,
}


def _store():
    from .machine_lease import machine_state_root
    return Path(machine_state_root()) / 'operating-mode'


def _key(path):
    return hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()


def _ledger(path, kind):
    return _store() / kind / (_key(path) + '.jsonl')


def _record(path):
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('operating mode requires a bounded regular record')
    return state_io.read_json(path)


def validate_bounds(value):
    if type(value) is not dict or set(value) != set(DEFAULT_BOUNDS):
        raise ValueError('operating mode requires explicit finite bounds')
    for key in ('compute_plans', 'allowed_stages'):
        rows = value[key]
        if (type(rows) is not list or not rows or len(rows) > 256
                or any(type(x) is not str or not re.fullmatch(r'[A-Za-z0-9_-]+', x) for x in rows)
                or len(set(rows)) != len(rows)):
            raise ValueError('operating mode requires finite distinct plans and stages')
    if not set(value['compute_plans']) <= {'none', 'dry', 'smoke', 'full', 'scan'}:
        raise ValueError('unknown delegated compute plan')
    for key in ('max_seconds', 'max_events', 'max_redos'):
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError('operating mode requires finite nonnegative ceilings')
    return deepcopy(value)


def project_root(start):
    here = Path(start).resolve()
    for path in (here, *here.parents):
        if (path / '.ravel').exists() or (path / '.git').exists() or (path / 'pyproject.toml').exists():
            return path
    return here


def config_path(scope, project=None):
    if scope == 'project':
        return project_root(project or Path.cwd()) / '.ravel' / CONFIG
    if scope == 'user':
        return Path.home() / '.ravel' / CONFIG
    raise ValueError('mode scope must be project or user')


class MissingOperatorReceipt(ValueError):
    """No usable protected operator ledger exists for this selection."""


def _privileged():
    return os.getuid() == 0 or os.geteuid() == 0


def _operator_records(kind, target):
    """Read the externally provisioned operator boundary, never an agent-selected path.

    Only an external privileged operator service can write this root-owned ledger.
    RAVEL's agent/CLI process has no issuance API. Environment, TTY, session markers,
    same-user custody and caller-supplied records are not identity evidence.
    """
    if kind not in {'setting','environment','run'}:
        raise ValueError('unknown operator receipt kind')
    if _privileged():
        # A privileged process could write any ledger: no usable operator boundary exists.
        raise MissingOperatorReceipt('operator authority requires a non-privileged agent identity')
    base = Path('/private/etc' if sys.platform == 'darwin' else '/etc') / 'ravel/operator-authority' / str(os.getuid())
    path = base / kind / (_key(target) + '.jsonl')
    if not path.exists():
        raise MissingOperatorReceipt('trusted operator receipt is required before agent execution')
    for entry in (path, *path.parents):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or os.access(entry, os.W_OK):
            raise ValueError('operator authority must be root-owned and agent-unwritable')
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('invalid operator receipt ledger')
    rows = rdj_custody._read(path)
    for row in rows:
        record = row['record']
        if (set(record) != {'schema_version', 'kind', 'target', 'value'}
                or record['schema_version'] != 1 or record['kind'] != kind
                or record['target'] != str(Path(target).resolve())):
            raise ValueError('operator receipt scope differs')
    return rows


def _has_operator_records(kind, target):
    """Whether a usable operator ledger exists; a present but invalid ledger still refuses."""
    try:
        return bool(_operator_records(kind, target))
    except MissingOperatorReceipt:
        return False


def _operator_proof(kind, target, value):
    rows = _operator_records(kind, target)
    if not rows or rows[-1]['record']['value'] != value:
        raise ValueError('no trusted operator receipt for this exact selection')
    row = rows[-1]
    return {'kind':kind, 'target':str(Path(target).resolve()), 'seq':row['seq'], 'digest':row['digest']}


def _verify_operator_proof(proof, value, *, kind, target):
    if not isinstance(proof, dict) or set(proof) != {'kind','target','seq','digest'}:
        raise ValueError('trusted operator receipt is required')
    if proof['kind'] != kind or proof['target'] != str(Path(target).resolve()):
        raise ValueError('operator receipt kind or target differs')
    rows = _operator_records(kind, target)
    seq = proof['seq']
    if (type(seq) is not int or not 0 <= seq < len(rows)
            or rows[seq]['digest'] != proof['digest'] or rows[seq]['record']['value'] != value):
        raise ValueError('trusted operator receipt differs from the selected authority')


def set_mode(mode, *, scope='project', project=None, bounds=None):
    """Apply an exact pre-issued operator change; this function cannot issue authority."""
    if any(k in os.environ for k in AGENT_MARKERS):
        raise ValueError('only a user/operator can change operating mode; agent session refused')
    if mode not in MODES:
        raise ValueError('unknown operating mode')
    path = config_path(scope, project)
    selection = {'mode':mode, 'source':'project' if scope == 'project' else 'user_default',
                 'bounds':validate_bounds(DEFAULT_BOUNDS if bounds is None else bounds)}
    proof = _operator_proof('setting', path, selection)
    value = {'schema_version':1, **selection, 'operator_receipt':proof,
             'changed_utc':execution.utc_now(), 'actor':'operator'}
    with state_io.file_lock(_ledger(path, 'settings').with_suffix('.lock-setting')):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('operator mode configuration must not be a symlink')
        state_io.atomic_json(path, value)
        rdj_custody._append(_ledger(path, 'settings'), {'path':str(path), 'value':value})
    return value


def _configured(path, source):
    rows = rdj_custody._read(_ledger(path, 'settings'))
    if not path.exists() and not path.is_symlink():
        if rows:
            raise ValueError('operator configuration was deleted without an authenticated removal receipt')
        return None
    value = _record(path)
    if not rows or rows[-1]['record'] != {'path':str(path), 'value':value}:
        raise ValueError('operating mode has no matching operator change receipt')
    if value.get('source') != source or value.get('mode') not in MODES:
        raise ValueError('operating mode configuration source differs')
    selection = {k:value[k] for k in ('mode','source','bounds')}
    validate_bounds(value['bounds'])
    _verify_operator_proof(value.get('operator_receipt'), selection, kind='setting', target=path)
    # A new operator default cannot be hidden by replaying an older configuration.
    _operator_proof('setting', path, selection)
    return value


def request_mode(prompt):
    """Approval prerequisites and negation take precedence over affirmative authority."""
    from .scientific_autonomy import delegation_intent, approval_requirement
    human = approval_requirement(prompt)
    if human:
        return 'physicist-in-the-loop', {'start':human.start(), 'end':human.end(), 'text':human.group()}
    span = delegation_intent(prompt)
    if span:
        return 'autonomous', span
    if re.search(r'\bautonom\w*|\bdelegat\w*|\b(?:approval|confirmation|permission)\b', prompt, re.I):
        return 'physicist-in-the-loop', None
    return None


def resolve(*, prompt='', project=None, environ=None):
    """Resolve a proposed choice; autonomous intake additionally needs a run receipt."""
    env = os.environ if environ is None else environ
    explicit = request_mode(prompt)
    if explicit and explicit[0] == 'physicist-in-the-loop':
        return {'mode':explicit[0], 'source':'explicit_request', 'bounds':deepcopy(DEFAULT_BOUNDS),
                'statement':explicit[1], 'configured':True}
    if 'RAVEL_OPERATING_MODE' in env:
        selected = {'mode':env['RAVEL_OPERATING_MODE'], 'source':'operator_environment',
                    'bounds':validate_bounds(json.loads(env['RAVEL_AUTONOMY_BOUNDS']))
                    if 'RAVEL_AUTONOMY_BOUNDS' in env else deepcopy(DEFAULT_BOUNDS)}
        if selected['mode'] not in MODES:
            raise ValueError('RAVEL_OPERATING_MODE must name an operating mode')
        _operator_proof('environment', project_root(project or Path.cwd()), selected)
        selected['actor'] = 'operator'
    else:
        selected = _configured(config_path('project', project), 'project')
        if selected is None:
            selected = _configured(config_path('user'), 'user_default')
        if selected is None:
            selected = {'mode':'physicist-in-the-loop', 'source':'user_default', 'bounds':deepcopy(DEFAULT_BOUNDS)}
    result = {k:deepcopy(selected[k]) for k in ('mode','source','bounds')}
    result.update(statement=None, configured=selected.get('actor') == 'operator')
    if explicit:
        result.update(mode=explicit[0], source='explicit_request', statement=explicit[1], configured=True)
    return result



def _original(document, root, sources=None):
    if 'prompt' in document:
        return document.get('prompt', ''), None
    binding=document.get('goal_binding')
    pin=binding.get('contract') if isinstance(binding, dict) else document.get('task', {}).get('parent_contract')
    if pin is None:
        return '', None
    from . import scientific_autonomy as autonomy
    exact={k:pin[k] for k in ('path','sha256')}
    path,raw=(autonomy._document(exact,root) if sources is None else autonomy._retained_document(exact,root,sources))
    if pin.get('size')!=len(raw):raise ValueError('original parent contract size changed')
    parent = path.parent.parent if path.parent.name == 'inputs' else path.parent
    return json.loads(raw)['prompt'], parent

def _run_selection(value):
    return {k:deepcopy(value[k]) for k in ('rundir','prompt_sha256','mode','source','bounds','statement','budget_root')}


def _transaction_value(root):
    rows = rdj_custody._read(_ledger(root, 'runs'))
    if not rows:
        return None, False
    if (len(rows) not in (1, 2) or rows[0]['record'].get('phase') != 'pending'
            or len(rows) == 2 and rows[1]['record'] != {'phase':'committed', 'pending':rows[0]['digest']}):
        raise ValueError('invalid operating mode transaction custody')
    return rows[0]['record']['value'], len(rows) == 2


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _publish_exact(path, raw):
    """Atomically publish pending bytes, refusing any existing conflicting bytes."""
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('authority path must not be a symlink')
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            raise ValueError('pending authority bytes conflict with custody')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def _publish(root, value):
    path = root / RUN_RECORD
    if not value['materialized']:
        if path.exists():
            raise ValueError('implicit human mode has an unexpected mode file')
        return
    _publish_exact(path, _json_bytes(value))


def _validate_frozen(root, value, document=None, sources=None):
    if (value.get('schema_version') != 2 or value.get('kind') != 'operating_mode'
            or value.get('rundir') != str(root) or value.get('mode') not in MODES
            or value.get('source') not in {'explicit_request','project','user_default','operator_environment'}):
        raise ValueError('invalid frozen operating mode')
    if (type(value.get('materialized')) is not bool
            or value.get('human_identity_authenticated') is not False
            or value.get('authority_boundary') != 'protected_operator_receipt'):
        raise ValueError('invalid frozen mode metadata')
    validate_bounds(value['bounds'])
    if document is not None and value['prompt_sha256'] != hashlib.sha256(_original(document, root, sources)[0].encode()).hexdigest():
        raise ValueError('operating mode belongs to a different original request')
    if value['mode'] == 'autonomous':
        original = value.get('original_selection') or _run_selection(value)
        _verify_operator_proof(value.get('operator_receipt'), original, kind='run', target=original['rundir'])
        if value.get('materialized') is not True:
            raise ValueError('autonomous mode cannot become an implicit default')
        if (value['budget_root'] != original['rundir'] or value['prompt_sha256'] != original['prompt_sha256']
                or any(value[k] != original[k] for k in ('mode','source','bounds','statement'))):
            raise ValueError('child authority differs from original operator decision')
        if value['rundir'] != original['rundir']:
            doc = document
            if doc is None:
                from . import scientific_autonomy
                _, doc = scientific_autonomy._run_document(root)
            _, parent = _original(doc, root, sources)
            if parent is None or str(parent) != original['rundir']:
                raise ValueError('child lacks its original operator-bound parent')
            binding = doc.get('goal_binding')
            pin = binding.get('contract') if isinstance(binding, dict) else doc.get('task', {}).get('parent_contract')
            if Path(pin['path']).resolve() not in {parent/'inputs/task_contract.json', parent/'task_contract.json'}:
                raise ValueError('child contract does not name the original run contract')


def initialize(root, document, *, project=None, configured_only=False):
    """Recover exact pending bytes; only a committed, independently authorized choice is usable.

    A controller-owned run has one mode record, frozen in its protected store at intake
    (``ravel.controller.authority.freeze_mode``): this legacy freeze writes nothing for it and
    returns None, so intake helpers shared with legacy runs keep working.
    """
    root = Path(root).resolve()
    from ravel.controller.authority import common as controller_authority
    if controller_authority.owned_run(root) is not None:
        return None
    ledger = _ledger(root, 'runs')
    with state_io.file_lock(ledger.with_suffix('.lock-init')):
        value, committed = _transaction_value(root)
        if value is not None:
            if (value.get('prompt_sha256') != hashlib.sha256(_original(document, root)[0].encode()).hexdigest()
                    and not any((root / name).exists() for name in (RUN_RECORD, *_RUN_STATE))):
                # Custody is keyed by path and outlives a deleted run directory.
                raise ValueError('operating mode belongs to a different original request: a previous run used '
                                 'this directory path; choose a new run directory')
            _validate_frozen(root, value, document)
            if committed:
                return frozen(root, document=document)
            _publish(root, value)
            pending = rdj_custody._read(ledger)[0]['digest']
            rdj_custody._append(ledger, {'phase':'committed', 'pending':pending})
            return frozen(root, document=document)
        if (root / RUN_RECORD).exists():
            raise ValueError('mode file has no trusted pending record')
        if any((root / name).exists() for name in _RUN_STATE):
            raise ValueError('operating mode cannot be set during an existing run')
        prompt, parent = _original(document, root)
        inherited = _frozen(parent) if parent is not None else None
        if parent is not None:
            selected = ({k:deepcopy(inherited[k]) for k in ('mode','source','bounds','statement')}
                        if inherited else {'mode':'physicist-in-the-loop','source':'user_default',
                                           'bounds':deepcopy(DEFAULT_BOUNDS),'statement':None})
            configured = bool(inherited and inherited['materialized'])
        else:
            selected = resolve(prompt=prompt, project=project or root)
            if (selected['mode'] == 'autonomous' and selected['source'] == 'explicit_request'
                    and not _has_operator_records('run', root)):
                # No operator run decision exists: the request statement grants no mode
                # authority and stays with the retained text-delegation paths.
                selected = resolve(project=project or root)
            configured = selected.pop('configured')
        value = {'schema_version':2, 'kind':'operating_mode', 'rundir':str(root),
                 'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(), **selected,
                 'budget_root':inherited['budget_root'] if inherited else str(parent or root),
                 'materialized':not configured_only or configured,
                 'recorded_utc':execution.utc_now(), 'authority_boundary':'protected_operator_receipt',
                 'human_identity_authenticated':False}
        if value['mode'] == 'autonomous':
            if inherited:
                value['operator_receipt'] = deepcopy(inherited['operator_receipt'])
                value['original_selection'] = deepcopy(inherited.get('original_selection') or _run_selection(inherited))
            else:
                value['operator_receipt'] = _operator_proof('run', root, _run_selection(value))
        _validate_frozen(root, value, document)
        row = rdj_custody._append(ledger, {'phase':'pending', 'value':value})
        _publish(root, value)
        rdj_custody._append(ledger, {'phase':'committed', 'pending':row['digest']})
    return frozen(root, document=document)


def _frozen(root, *, document=None, sources=None):
    root = Path(root).resolve()
    path = root / RUN_RECORD
    if sources is not None:
        raw = sources.get(str(path))
        if raw is None:
            return None
        value = json.loads(raw)
    else:
        value, committed = _transaction_value(root)
        if value is None:
            if path.exists():
                raise ValueError('frozen operating mode has no intake custody')
            return None
        if not committed:
            raise ValueError('operating mode transaction is pending; resume intake before authority use')
        if value['materialized'] and (_record(path) != value or path.read_bytes() != _json_bytes(value)):
            raise ValueError('frozen operating mode differs from intake custody')
        if not value['materialized'] and path.exists():
            raise ValueError('implicit human mode has an unexpected mode file')
    _validate_frozen(root, value, document, sources)
    return deepcopy(value)


def frozen(root, *, document=None, sources=None):
    value = _frozen(root, document=document, sources=sources)
    return value if value is not None and value['materialized'] else None


def receipt(root, *, sources=None):
    value = frozen(root, sources=sources)
    if value is None or value['mode'] == 'physicist-in-the-loop':
        from . import scientific_autonomy as autonomy
        from . import science
        base = Path(root).resolve()
        science_source = (str(base / science.SPEC) in sources if sources is not None else (base / science.PLAN).exists())
        path = base / science.SPEC if science_source else base / 'inputs/task_contract.json'
        if sources is not None:
            raw = sources.get(str(path))
            document = json.loads(raw) if raw else {}
        else:
            document = state_io.read_json(path) if path.exists() else {}
        d = autonomy.declaration(document, Path(root).resolve(), _sources=sources)
        if d is not None:
            return {'mode': 'autonomous', 'source': 'explicit_request', 'binding': execution.digest(d['value']['source_binding'])}
        if value is None:
            return {'mode': 'physicist-in-the-loop', 'source': 'user_default', 'binding': None}
    return {'mode': value['mode'], 'source': value['source'], 'binding': execution.digest(value)}


def verify_receipt(root, record, *, sources=None):
    expected = receipt(root, sources=sources)
    if record.get('operating_mode') != expected:
        raise ValueError('approval operating mode source or binding differs')


def bind_plan(root):
    """Materialize a finite delegation over the current plan without rewriting it."""
    from . import scientific_autonomy as autonomy
    root = Path(root).resolve()
    value = frozen(root)
    if value is None or value['mode'] != 'autonomous':
        return False
    autonomy.record_mode_delegation(root, value)
    return True


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog='ravel mode')
    subs = parser.add_subparsers(dest='command', required=True)
    setter = subs.add_parser('set')
    setter.add_argument('mode', choices=MODES)
    setter.add_argument('--scope', choices=('project', 'user'), default='project')
    setter.add_argument('--bounds', type=Path, help='JSON finite plans, stages, budget and redo ceilings')
    subs.add_parser('show')
    args = parser.parse_args(argv)
    try:
        result = (set_mode(args.mode, scope=args.scope, bounds=_record(args.bounds) if args.bounds else None)
                  if args.command == 'set' else resolve(project=Path.cwd()))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'operating mode refused: {exc}')
        return 1
    print(json.dumps(result, indent=2))
    return 0


class _ResourceContext(dict):
    """Validated by the common plan-resource join, never reconstructed from JSON."""


def admit_launch(root, command, context):
    """Check and reserve finite supervised launch use under the journal lock.

    Authorizations count even if a process failed to start. Redoing a consumed
    stage requires the operator's redo ceiling; approvals do not reset usage.
    """
    value = frozen(root)
    if value is None or value['mode'] != 'autonomous':
        return
    limits = value['bounds']
    stage = context.get('stage')
    seconds = context.get('max_seconds')
    events = context.get('resource_events', context.get('events'))
    derived = isinstance(context, _ResourceContext)
    orchestration = derived and context.get('resource_reservation') == 'orchestration'
    if not derived and any(k in context for k in ('resource_events','resource_reservation','resource_stages')):
        raise ValueError('resource accounting requires verified plan context')
    if orchestration:
        if (stage != 'scan-dispatch' or seconds != 0 or events != 0
                or not context.get('resource_stages')
                or not set(context['resource_stages']) <= set(limits['allowed_stages'])):
            raise ValueError('orchestration stage scope differs')
    elif stage not in limits['allowed_stages']:
        raise ValueError('stage outside operating mode authority')
    if (type(seconds) not in (int, float) or not (0 <= seconds <= limits['max_seconds'] if orchestration else 0 < seconds <= limits['max_seconds'])
            or type(events) is not int or not 0 <= events <= limits['max_events']):
        raise ValueError('launch lacks finite resources within operating mode ceilings')
    rows = rdj_custody._read(_ledger(value.get('budget_root', root), 'usage'))
    authorized = [row['record'] for row in rows]
    if sum(e['rundir']==str(Path(root).resolve()) and e['stage']==stage for e in authorized) >= 1 + limits['max_redos']:
        raise ValueError('operating mode stage redo ceiling exhausted')
    if (sum(e['max_seconds'] for e in authorized) + seconds > limits['max_seconds']
            or sum(e['events'] for e in authorized) + events > limits['max_events']):
        raise ValueError('operating mode aggregate launch budget exhausted')


from contextlib import contextmanager


@contextmanager
def launch_reservation(root, command, context):
    """Serialize resource reservations across an original request and its children."""
    value=frozen(root)
    if value is None or value['mode']!='autonomous':
        yield
        return
    ledger=_ledger(value.get('budget_root', root), 'usage')
    with state_io.file_lock(ledger.with_suffix('.lock-reservation')):
        admit_launch(root, command, context)
        rdj_custody._append(ledger, {'rundir':str(Path(root).resolve()), 'stage':context['stage'],
            'command':list(command), 'max_seconds':context['max_seconds'], 'events':context.get('resource_events', context['events'])})
        yield
