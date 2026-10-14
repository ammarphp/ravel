"""Common ordinary-plan and research-choice admission; no execution authority."""
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from . import state_io


@dataclass(frozen=True)
class GateError:
    code: str
    gate: str
    provider: str
    message: str
    fix: str
    pins: tuple = ()


def decision_provider():
    try:
        return import_module('ravel.workflow.decision_gate')
    except ImportError:
        return None


def decision_errors(root, action):
    """Invoke the real aggregator, never mistake an absent provider for assent."""
    provider = decision_provider()
    if provider is None:
        return [GateError('decision_gate_unavailable', 'research_choice', 'research_protocol',
                          'research_choice requires the decision gate', 'Install the ravel.workflow.decision_gate module.')]
    # Keep local checks even if an older registry omits this provider/epoch; the
    # current registry composes the same provider, so repeated errors are dropped.
    from .research_protocol import gate_errors
    errors = []
    for error in [*provider.check(Path(root), 'research_choice', action),
                  *gate_errors(root, 'research_choice', action)]:
        if error not in errors:
            errors.append(error)
    return errors


def run_contract(root):
    root = Path(root)
    for relative in ('inputs/task_contract.json', 'task_contract.json'):
        path = root/relative
        if path.exists():
            return state_io.read_json(path)
    path = root/'inputs/science.json'
    if path.exists():
        spec = state_io.read_json(path)
        # A scoped child keeps its parent's task-completion binding. It must not
        # duplicate the parent's entire research lifecycle before its own result
        # can be reviewed; the original parent's admission is checked there.
        return spec
    return {}


def admission(root, boundary, *, contract=None, bind=False):
    """One predicate for ordinary intake, approval, launch, adoption and delivery.

    Plan/adoption callers bind explicitly. Read-only launch/delivery never repair a
    removed binding. Missing producers block claims, not preparatory computation.
    """
    from . import research_protocol as p
    try:
        contract = run_contract(root) if contract is None else contract
        plan = p._method_json(contract['request_plan'], root) if contract.get('request_plan') else {}
        required = p.required_for([contract, plan]) or contract.get('research_protocol_required', False)
        binding_exists = (Path(root)/'research/binding.json').exists()
        if not required and not binding_exists:
            return []
        if bind and not (Path(root)/'research/binding.json').is_file():
            from . import research_launch
            # An interrupted publication is rolled back first. An existing run
            # binds only with a recorded migration receipt.
            p.recover_binding(root)
            if research_launch.existing_run(root):
                research_launch.migrate(root)
            else:
                p.bind_default(root)
        if not (Path(root)/'research/binding.json').is_file():
            return ['protocol_unbound']
        status = p.methodology_status(root)
        if boundary in {'acceptance', 'delivery', 'reuse', 'final_task', 'export'}:
            errors = [*p.producer_pending(root), *p.methodology_errors(root)]
            # Capped or post-hoc results remain deliverable as ordinary results with
            # their label; they never support a research (search-route) claim.
            if p.route_applicability(root)['route'] == p.SEARCH_ROUTE:
                errors += ['research claim capped: ' + cap for cap in status['claim_cap']]
                if status['record'].get('preregistration_authority') == 'evaluation_harness':
                    errors.append('an evaluation-harness preregistration cannot support a delivered research claim')
            return errors
        if boundary == 'launch':
            if status['record']['preregistration'] is None:
                return ['prospective research preregistration and evaluator pins required']
            from .research_launch import verify
            return verify(root)
        return []
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]
