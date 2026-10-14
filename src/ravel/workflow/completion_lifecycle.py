"""Epoch-qualified whole-parent completion and journal verification seams."""
from pathlib import Path
from . import state_io


def required(contract):
    return contract.get('task_requirements', {}).get('completion_epoch') == 1


def mark_new_contract(contract):
    """New routed contracts enter epoch1; retained contract bytes are untouched."""
    if 'task_requirements' in contract:
        contract['task_requirements']['completion_epoch'] = 1
    return contract


def evaluate_parent(rundir, contract, stage_limit=None):
    from .task_completion import _Inputs, _contract, require_final
    rd = Path(rundir); observed = _Inputs(rd); checks = []; accepted = False; valid = False
    try:
        parent = observed.capture(rd / 'inputs/task_contract.json')
        current, _, _, _ = _contract(parent, observed)
        if current != contract: raise ValueError('exact original parent contract required')
        valid = True
        if stage_limit != 'task_contract':
            completion = observed.capture(rd / 'inputs/task_completion.json')
            if observed.document(completion)['contract'] != parent:
                raise ValueError('completion must bind exact original parent')
            result = require_final(completion, base_dir=rd, _inputs=observed)
            accepted = result['parent_task_accepted']
            # Research retains its resource and premise floor even when its
            # deliverables arrive entirely through children.
            if contract.get('task_mode') == 'research':
                from ravel.validation import validate_run_state as lifecycle
                facts = lifecycle.discover_facts(str(rd), contract)
                for name, fn in [('resource_census', lifecycle.check_resource_census), ('trap_sweep', lifecycle.check_trap_sweep)]:
                    status, _, rows = fn(str(rd), contract, facts, 'R', False)
                    if status != 'PASS': raise ValueError(name + ': ' + str(rows))
            checks.append({'name': 'whole-task', 'level': 'PASS', 'msg': 'Exact accepted child and parent obligation coverage'})
        if stage_limit == 'task_contract': observed.finish()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        accepted = False
        checks.append({'name': 'whole-task', 'level': 'FAIL', 'msg': str(exc)})
    finally: observed.close()
    passed = valid if stage_limit == 'task_contract' else accepted
    stages = [{'name': 'task_contract', 'required': 'R', 'status': 'PASS' if valid else 'FAIL',
               'artifact': 'inputs/task_contract.json', 'checks': checks if not valid else []}]
    if stage_limit != 'task_contract':
        stages.append({'name': 'result_pack', 'required': 'R', 'status': 'PASS' if accepted else 'FAIL',
                       'artifact': 'inputs/task_completion.json', 'checks': checks})
    return {'rundir': str(rd), 'task_mode': contract['task_mode'], 'compute_plan': contract['compute_plan'],
            'stat_mode': contract['stat_mode'], 'legacy': False, 'stages': stages, 'invariants': [],
            'completion_scope': 'original_task_completion', 'parent_task_accepted': accepted,
            'physics_validated': False, 'verdict': 'PASS' if passed else 'FAIL', 'exit': 0 if passed else 1}


def ensure_policy(root):
    """The packaged template is a prospective policy, never a review receipt."""
    path = Path(root) / 'inputs/physics_review_policy.json'
    if not path.exists():
        template = Path(__file__).parents[1] / 'data/templates/physics_review_policy.json'
        policy = state_io.read_json(template)
        policy['claim_scopes']['original_task_completion'] = {'checks': ['integrity', 'agreement'], 'actions': ['delivery', 'reuse']}
        state_io.atomic_json(path, policy)


def tier_b(root):
    from . import physics_review
    view = physics_review.status(root)
    if view.get('state') != 'accepted' or view.get('live_errors') or view.get('unresolved_findings'):
        raise ValueError('current accepted Tier-B review journal required')
    return {'verdict': 'PASS', 'findings': [], 'cycle_id': view['cycle_id']}


def seal_cost(root, record):
    """Cost provenance binds both its declared inputs and its computed payload."""
    from . import provenance, execution
    value = {k: v for k, v in record.items() if k not in ('input_fingerprint', 'payload_sha256', 'generated_by')}
    value.update(provenance.provenance_pair('cost_preflight.py', [str(Path(root) / 'inputs/task_contract.json')]))
    value['payload_sha256'] = execution.digest(value)
    return value


def verify_cost(root, record):
    from . import provenance, execution, workflow_state
    path = str(Path(root) / 'inputs/task_contract.json')
    ok, reason = provenance.verify_pair(record, 'cost_preflight.py', [path])
    if not ok: return ok, reason
    if record.get('payload_sha256') != execution.digest({k: v for k, v in record.items() if k != 'payload_sha256'}):
        return False, 'cost payload changed'
    if (Path(root) / 'inputs/checkin1_approval.json').exists():
        errors = workflow_state.verify_approval(str(root))
        if errors: return False, 'approved cost binding: ' + '; '.join(errors)
    return True, 'cost inputs and payload current; provenance is not forecast calibration'


def summary_invariant(rundir, contract, facts, legacy, strict):
    """Recompute the summary, never trust a supplied PASS label."""
    from ravel.validation import summary_audit
    if contract.get('task_mode') not in ('summary_plot', 'survey'):
        return 'N/A', 'no published-overlay summary deliverable'
    if not facts.get('result_pack_paths'):
        return 'N/A', 'summary not delivered yet'
    if legacy: return 'waived-legacy', 'summary predates completion gate'
    root = Path(rundir)
    try:
        survey = state_io.read_json(root / 'outputs/survey.json')
        path = facts.get('basis_manifest_path') or 'inputs/basis_manifest.json'
        manifest = state_io.read_json(root / path)
        result = summary_audit.audit(survey, manifest)
        return result['verdict'], 'published-overlay summary audit recomputed: ' + str(result['rules'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return 'FAIL', str(exc)
