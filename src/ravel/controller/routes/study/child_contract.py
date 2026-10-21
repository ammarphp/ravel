"""Exact controller custody for an ordinary child's derived intake at approval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .contracts import pinned_json, records, relative

CONTRACT = 'inputs/task_contract.json'
COMPUTE = 'inputs/controller-compute-approval.json'
RECORD = 'study-child-contract'


class ComputeRungUnavailable(ValueError):
    """No unambiguous approved compute rung belongs to this ordinary child."""
    code = 'ordinary_compute_rung_unavailable'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def prepare(store, child, ordinary, decision, context):
    """Retain the parent intake bytes and derive only child identity/authority removal.

    The verified controller decision supplies approval, never inherited delegation.
    All request content and the pinned reading and request plan remain unchanged.
    """
    parent, child = Path(context['run_dir']).absolute(), Path(child).absolute()
    if child != parent / relative(ordinary['child_rundir']):
        raise ValueError('child contract must belong to its approved ordinary directory')
    from ravel.workflow import science, private_files, rdj_custody
    for name, key in ((science.PLAN, 'plan_sha256'), (science.SPEC, 'specification_sha256')):
        pinned_json(child, {'path': name, 'sha256': ordinary[key]})
    existing = [row for row in store.scan(RECORD)
                if row['record'].get('child_rundir') == ordinary['child_rundir']]
    if existing:
        record = existing[-1]['record']
        if (record['decision'] != decision['id'] or record['plan_sha256'] != context['plan_sha256']):
            raise ValueError('child contract belongs to another controller approval')
        paths(child, store=store)
        return existing[-1]['id']
    if (child / CONTRACT).exists() or (child / CONTRACT).is_symlink():
        raise ValueError('child contract already exists without its controller approval record')
    intake = records(store, 'intake')
    if not intake:
        raise ValueError('child contract requires the controller-pinned parent intake')
    original = store.get_blob(intake[-1]['contract_blob'])
    pinned_json(parent, {'path': CONTRACT, 'sha256': _sha(original)})
    contract = json.loads(original)
    if contract != context.get('contract'):
        raise ValueError('child contract parent differs from the approved controller context')
    derived = deepcopy(contract)
    for key in ('run_id', 'autonomy', 'delegated', 'delegation'):
        derived.pop(key, None)
    files = {CONTRACT: (json.dumps(derived, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()}
    from ravel.validation.validate_task_contract import read_pinned
    for key in ('request_plan', 'reading'):
        if key not in derived:
            continue
        name = relative(derived[key]['path']).as_posix()
        if name in files or name in {science.PLAN, science.SPEC, science.APPROVAL, COMPUTE}:
            raise ValueError('child contract input paths collide')
        files[name] = read_pinned(parent, derived[key], key)
    if context.get('compute_approval') is not None:
        files[COMPUTE] = (json.dumps(context['compute_approval'], indent=2, sort_keys=True,
                                    allow_nan=False) + '\n').encode()
    for name in files:
        target = child / name
        if target.exists() or target.is_symlink():
            raise ValueError('child contract destination already exists: ' + name)
    blobs = {name: store.put_blob(raw) for name, raw in files.items()}
    for name, raw in files.items():
        private_files.write(child / name, raw, exclusive=True)
    identifier = store.append(RECORD, {
        'step_id': context['step_id'], 'child_rundir': ordinary['child_rundir'],
        'parent_rundir': str(parent), 'decision': decision['id'],
        'plan_sha256': context['plan_sha256'], 'child_plan_sha256': ordinary['plan_sha256'],
        'child_specification_sha256': ordinary['specification_sha256'],
        'parent_contract_blob': intake[-1]['contract_blob'], 'files': blobs})
    rdj_custody.record_input_snapshot(child, 'run_init')
    return identifier


def paths(child, *, store=None, sources=None, approval=None, approval_inputs=None):
    """Authenticate live or retained child inputs against the protected approval binding.

    Controller-side callers use the protected store. A capsule without that store
    must reproduce the child's existing science approval fingerprint over the complete
    input roster. This verifies local byte continuity and grants no controller authority.
    """
    child = Path(child).absolute()
    if store is None:
        from ravel.workflow.review_independence import controller_store
        store = controller_store(child)
    if store is None:
        return _approved_paths(child, sources=sources, approval=approval, approval_inputs=approval_inputs)
    run_dir = getattr(store, 'run_dir', None)
    if run_dir is None or child == Path(run_dir).absolute():
        return None
    parent = Path(run_dir).absolute()
    if not child.is_relative_to(parent / 'children'):
        return None
    rows = [r for r in records(store, RECORD) if parent / relative(r['child_rundir']) == child]
    if not rows:
        return None
    record = rows[-1]
    if record['parent_rundir'] != str(parent):
        raise ValueError('child contract controller directory changed')
    binding = getattr(store, 'check_binding', None)
    if callable(binding) and binding():
        raise ValueError('child contract controller binding changed')
    from ravel.workflow import science
    pins = {science.PLAN: record['child_plan_sha256'], science.SPEC: record['child_specification_sha256'],
            **record['files']}
    for name, sha in pins.items():
        if sources is None:
            pinned_json(child, {'path': name, 'sha256': sha})
        elif str(child / relative(name)) not in sources or _sha(sources[str(child / name)]) != sha:
            raise ValueError('retained child contract input differs from controller approval: ' + name)
        if name in record['files']:
            store.get_blob(sha)
    names = [CONTRACT, *sorted(set(record['files']) - {CONTRACT})]
    return [str(child / relative(name)) for name in names]


def _approved_paths(child, *, sources=None, approval=None, approval_inputs=None):
    """Verify the child's own bound approval with only capsule-readable inputs.

    The controller pins this receipt before launching the capsule. Neither a bare
    contract nor an approval written before that contract existed binds its bytes.
    Retained callers must also supply the complete saved approval input roster;
    their outer snapshot validator retains all ordinary receipt and source checks.
    """
    from ravel.workflow import science
    from ravel.workflow.research_cycle import CHILD_CONTRACT_ORIGIN
    if sources is None:
        if not all((child / name).is_file() for name in (CONTRACT, science.PLAN, science.SPEC, science.APPROVAL)):
            return None
        if (child / CHILD_CONTRACT_ORIGIN).exists():
            return None
        def raw(name):
            return science.regular(name, child).read_bytes()
    else:
        if not all(str(child / name) in sources for name in (CONTRACT, science.PLAN, science.SPEC)):
            return None
        if str(child / CHILD_CONTRACT_ORIGIN) in sources:
            return None
        def raw(name):
            return sources[str(child / relative(name))]
    proposal, spec = [json.loads(raw(name)) for name in (science.PLAN, science.SPEC)]
    if proposal.get('research_binding') is not None or spec.get('schema_version') != 2:
        return None
    contract = json.loads(raw(CONTRACT))
    if type(contract) is not dict:
        raise ValueError('child contract must be an object')
    names = [CONTRACT]
    for key in ('request_plan', 'reading'):
        if key not in contract:
            if key == 'request_plan' and contract.get('agent_layer_epoch', 1) == 2:
                raise ValueError('child contract requires its request-plan pin')
            continue
        pin = contract[key]
        name = relative(pin['path']).as_posix()
        if name in names or name in {science.PLAN, science.SPEC, science.APPROVAL, COMPUTE}:
            raise ValueError('child contract input paths collide')
        if _sha(raw(name)) != pin['sha256']:
            raise ValueError('child contract input differs from its pin: ' + name)
        names.append(name)
    if ((sources is None and ((child / COMPUTE).exists() or (child / COMPUTE).is_symlink()))
            or (sources is not None and str(child / COMPUTE) in sources)):
        names.append(COMPUTE)
    paths_ = [str(child / name) for name in [CONTRACT, *sorted(names[1:])]]
    if sources is None:
        # Supply only the independently reconstructed inventory to avoid recursing
        # through this origin lookup; the existing complete approval check still runs.
        science.regular(science.APPROVAL, child)
        try:
            science._verify_v2_approval(child, spec, _child_contract_paths=paths_)
        except ValueError:
            raise ValueError('science plan, prospective policy or immutable envelope changed') from None
    else:
        if type(approval) is not dict or type(approval_inputs) is not list:
            raise ValueError('retained child contract lacks its science approval binding')
        pins = {row['path']: row['sha256'] for row in approval_inputs}
        if (len(pins) != len(approval_inputs) or not set(paths_) <= pins.keys()
                or any(path not in sources or _sha(sources[path]) != sha for path, sha in pins.items())
                or approval.get('plan_sha256') != pins.get(str(child / science.PLAN))
                or approval.get('checkin_sha256') != pins.get(str(child / 'inputs/checkin1.json'))
                or approval.get('input_fingerprint') != _sha(''.join(row['sha256'] for row in approval_inputs).encode())):
            raise ValueError('retained child contract differs from its science approval binding')
    return paths_


def compute_rung(child, *, max_seconds):
    """Read only an effect-authorized rung bound by this child's science approval.

    An approved ceiling is not a rung selection. Campaign children retain their
    separate origin; ordinary children without an explicit binding remain held.
    """
    import math
    from ravel.workflow import execution, science
    from ravel.workflow.research_cycle import CHILD_CONTRACT_ORIGIN
    child = Path(child).absolute()
    if not (child / CONTRACT).exists() or (child / CHILD_CONTRACT_ORIGIN).exists():
        return None
    try:
        roster = paths(child)
        if roster is None or str(child / COMPUTE) not in roster:
            raise ValueError('the approved ordinary child has no explicit compute rung binding')
        science.regular(science.APPROVAL, child)
        science._verify_v2_approval(child, json.loads(science.regular(science.SPEC, child).read_bytes()),
                                   _child_contract_paths=roster)
        binding = json.loads(science.regular(COMPUTE, child).read_bytes())
        keys = {'schema_version', 'required_plan', 'step_id', 'parent_plan_sha256', 'child_plan_sha256',
                'child_specification_sha256', 'max_seconds', 'requires_go', 'authority'}
        if (type(binding) is not dict or set(binding) != keys or type(binding['schema_version']) is not int
                or binding['schema_version'] != 1 or binding['required_plan'] not in ('smoke', 'full', 'scan')
                or type(binding['step_id']) is not str or not binding['step_id']
                or type(binding['parent_plan_sha256']) is not str or len(binding['parent_plan_sha256']) != 64
                or binding['child_plan_sha256'] != execution.file_hash(child / science.PLAN)
                or binding['child_specification_sha256'] != execution.file_hash(child / science.SPEC)
                or type(binding['requires_go']) is not bool or type(binding['authority']) is not dict
                or type(binding['authority'].get('approve_plan')) is not str or not binding['authority']['approve_plan']
                or (binding['requires_go'] and binding['required_plan'] in ('full', 'scan')
                    and (type(binding['authority'].get('go')) is not str or not binding['authority']['go']))):
            raise ValueError('the ordinary compute rung has no complete approval binding')
        ceiling = binding['max_seconds']
        if (type(ceiling) not in (int, float) or not math.isfinite(ceiling) or ceiling <= 0
                or type(max_seconds) not in (int, float) or not math.isfinite(max_seconds)
                or not 0 < max_seconds <= ceiling):
            raise ValueError('ordinary stage exceeds its approved compute rung time ceiling')
        return binding['required_plan']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ComputeRungUnavailable('ordinary compute rung unavailable: ' + str(exc)) from None
