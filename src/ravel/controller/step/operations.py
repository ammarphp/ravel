"""Operation admission by signature and executor role, and the approved-plan binding of a step.

An operation step is admitted only through its registered signature
(``data/operation_signatures.json``): every produced output and consumed input has a declared
artifact kind, every effect the step declares is one the signature names, the operation's own
cost ceiling resolves from the approved task and the step's requested cost stays within it,
the critical fields equal the approved values, and a command implementation is the module the
launch runs. Declaring a signature grants no scientific support (TOOL-*). A compute operation
runs only through its registered production role from ``data/roles/executors.json``; no other
role and no host implementation substitutes (EXEC-*, R13).

Every step is bound to the plan its authority covers: the step bytes equal the plan record's
step in the store. A step whose bytes changed after approval (another argument, another tool,
another engine) is a plan change, refused here and routed to a deviation (T03, E01).
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

from .services import StepHold, digest, unwrap

SIGNATURES = Path(__file__).resolve().parents[2] / 'data' / 'operation_signatures.json'
# Signature cost pointers that bound a step budget dimension.
POINTER_DIMENSIONS = {'/max_seconds': 'wall_seconds', '/max_wall_seconds': 'wall_seconds', '/events': 'events',
                      '/max_events': 'events'}


def signatures():
    from ravel.workflow.operation_registration import read_signatures
    return read_signatures(SIGNATURES)


def executors():
    from ravel.workflow import production_executor
    return production_executor.executors()


def pointer(document, path):
    """The value at a JSON pointer, or None when any part is absent."""
    if path in (None, ''):
        return document
    value = document
    for part in path.lstrip('/').split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if type(value) is dict and part in value:
            value = value[part]
        elif type(value) is list and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def resource_ceiling(step, signature=None):
    """The signature-resolved finite resource ceiling; absence supplies no cost evidence."""
    signature = signatures().get(step.get('operation')) if signature is None else signature
    cost = (signature or {}).get('cost') or {}
    path = cost.get('ceiling_pointer')
    dimension = POINTER_DIMENSIONS.get(path)
    value = pointer((step.get('parameters') or {}).get('task') or {}, path) if dimension else None
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        return None
    return {'dimension': dimension, 'ceiling_pointer': path, 'amount': value}


def launch_wall_seconds(step, reserved, signature=None):
    """Narrow an ordinary launch's reservation to its declared signature wall ceiling."""
    ceiling = resource_ceiling(step, signature)
    if ceiling is not None and ceiling['dimension'] == 'wall_seconds' and reserved is not None:
        return min(reserved, ceiling['amount'])
    return reserved


def executor_errors(step, signature=None, table=None):
    """A compute operation's step names its registered production role; nothing else fills it."""
    from ravel.workflow import production_executor
    operation = step.get('operation')
    if operation is None:
        return []
    table = executors() if table is None else table
    from . import host_operations
    host_errors = host_operations.admission_errors(step, table)
    if host_errors:
        return host_errors
    required = table['operations'].get(operation)
    if required is not None:
        from ravel.workflow.operation_check_policy import executor
        required = executor(operation, (step.get('parameters') or {}).get('task') or {}, required)
        # Output contracts refine a workflow's registered default; no worker
        # chooses its own role or bypasses this admission check.
        if step.get('role') != required:
            return [{'code': 'executor_role_mismatch', 'operation': operation, 'required': required,
                     'named': step.get('role')}]
        return []
    signature = signatures().get(operation) if signature is None else signature
    if signature is None:
        return [{'code': 'operation_unregistered', 'operation': operation}]
    if production_executor.requires_production(signature, table):
        return [{'code': 'executor_role_missing', 'operation': operation}]
    return []


def admission_errors(step, *, inputs_custody=(), approved=None, signature=None, context=None):
    """Why the signature does not admit this step (empty when it does)."""
    operation = step.get('operation')
    signature = signatures().get(operation) if signature is None else signature
    if signature is None:
        return [{'code': 'operation_unregistered', 'operation': operation}]
    errors = []
    if (context is not None and (step.get('parameters') or {}).get('adapter')
            == 'ravel.controller.routes.study.runtime'
            and ((step.get('parameters') or {}).get('ordinary') or {}).get('kind') == 'science'):
        from ravel.controller.routes import study
        try:
            inputs_custody = study.operation_inputs(step, context, inputs_custody)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return [{'code': 'operation_input_binding_invalid', 'message': str(exc)[:1500]}]
    produced = {slot['kind'] for slot in signature['produces']}
    consumed = {slot['kind'] for slot in signature['consumes']}
    for row in step['outputs']:
        if row['kind'] not in produced:
            errors.append({'code': 'operation_artifact_undeclared', 'direction': 'output', 'path': row['path'],
                           'kind': row['kind'], 'declared': sorted(produced)})
    for record in inputs_custody:
        kind = record.get('kind')
        if isinstance(kind, str) and kind.startswith('validation:'):
            continue  # a validator's input (a trap sweep, a check report) is not an operation artifact
        if kind is not None and consumed and kind not in consumed:
            errors.append({'code': 'operation_artifact_undeclared', 'direction': 'input',
                           'artifact': record.get('artifact'), 'kind': kind, 'declared': sorted(consumed)})
    parameters = step.get('parameters') or {}
    extra = sorted(set(parameters.get('effects') or ()) - set(signature['effects']))
    if extra:
        errors.append({'code': 'operation_effect_undeclared', 'effects': extra, 'declared': signature['effects']})
    task = parameters.get('task') or {}
    cost = signature['cost']
    if cost.get('ceiling_pointer'):
        ceiling = pointer(task, cost['ceiling_pointer'])
        if type(ceiling) not in (int, float) or ceiling < 0:
            errors.append({'code': 'operation_ceiling_unresolved', 'pointer': cost['ceiling_pointer']})
        else:
            requested = parameters.get('cost')
            if requested is not None:
                if (type(requested) is not dict or requested.get('unit') != cost['unit']
                        or type(requested.get('amount')) not in (int, float)):
                    errors.append({'code': 'operation_cost_invalid', 'unit': cost['unit']})
                elif requested['amount'] > ceiling:
                    errors.append({'code': 'operation_cost_above_ceiling', 'requested': requested['amount'],
                                   'ceiling': ceiling, 'unit': cost['unit']})
            dimension = POINTER_DIMENSIONS.get(cost['ceiling_pointer'])
            share = (step.get('budget') or {}).get(dimension) if dimension else None
            if share is not None and ceiling > share:
                errors.append({'code': 'operation_ceiling_above_budget', 'dimension': dimension,
                               'ceiling': ceiling, 'budget': share})
    if approved is not None:
        for field in signature['critical_fields']:
            if pointer(task, field) != pointer((approved.get('parameters') or {}).get('task') or {}, field):
                errors.append({'code': 'operation_critical_field_changed', 'field': field})
    implementation = signature['implementation']
    argv = (parameters.get('launch') or {}).get('argv')
    if implementation['kind'] == 'command' and argv is not None and implementation.get('module'):
        module = implementation['module']
        if module not in argv or argv.index(module) == 0 or argv[argv.index(module) - 1] != '-m':
            errors.append({'code': 'operation_implementation_mismatch', 'module': module})
    return errors


def current_plan(store, context):
    """The pinned scientific plan, or its separately authenticated current applied view.

    Neither identity permits ignoring fields: scientific bytes are rehashed in full and the
    complete applied document must equal the engagement service's deterministic projection.
    """
    wanted = (context or {}).get('plan_sha256')
    if type(wanted) is not str or not wanted:
        raise StepHold('plan_unbound', 'the step context names the plan digest its authority covers')
    rows = [unwrap(row) for row in store.scan('plan')]
    found = [row for row in rows if row.get('plan_sha256') == wanted and row.get('blob')]
    if not found:
        raise StepHold('plan_unbound', 'no plan record with the pinned digest is in the run store')
    record = found[-1]
    try:
        plan = json.loads(store.get_blob(record['blob']).decode('utf-8'))
    except (KeyError, ValueError, OSError) as exc:
        raise StepHold('plan_unreadable', str(exc)[:500]) from None
    if type(plan) is not dict or plan.get('sha256') != wanted:
        raise StepHold('plan_changed', 'the stored plan differs from the digest the run state pins')
    if 'engagement' not in plan and digest({k: v for k, v in plan.items() if k != 'sha256'}) != wanted:
        raise StepHold('plan_digest_mismatch', 'the complete scientific plan bytes differ from the approved digest')
    protected = plan if 'engagement' in plan else None
    if record.get('applied_blob'):
        try:
            protected = json.loads(store.get_blob(record['applied_blob']).decode('utf-8'))
        except (KeyError, ValueError, OSError) as exc:
            raise StepHold('engagement_view_invalid', str(exc)[:500]) from None
    supplied = (context or {}).get('plan')
    supplied = supplied if type(supplied) is dict and 'steps' in supplied else None
    if supplied is not None:
        if supplied.get('sha256') != wanted:
            raise StepHold('plan_digest_mismatch', 'the supplied view names another scientific plan')
        if 'engagement' not in supplied and digest({k: v for k, v in supplied.items() if k != 'sha256'}) != wanted:
            raise StepHold('plan_digest_mismatch', 'the supplied scientific plan bytes changed')
    from ravel.controller import engagement
    from ravel.controller.judgment.graph import PLANNING_SOURCE
    applied = supplied if supplied is not None and 'engagement' in supplied else protected
    if applied is None:
        # A planning plan binds only the judgment route's own planning seats (a frame, a decomposition, the RDJ case
        # on an exact approval or final-task action); the engagement decision covers the scientific plan.
        planning = record.get('source') == PLANNING_SOURCE and bool(
            ((plan.get('parameters') or {}).get('judgment') or {}).get('planning_phase'))
        if not planning and (store.scan(engagement.DECISION) or (context or {}).get('applied_sha256') is not None):
            raise StepHold('engagement_view_invalid', 'the current engagement decision requires its pinned applied view')
        return plan
    try:
        decision = engagement.effective_decision(store)
        scientific = decision['scientific_plan']
        if (scientific.get('sha256') != wanted
                or digest({k: v for k, v in scientific.items() if k != 'sha256'}) != wanted
                or ('engagement' not in plan and plan != scientific)):
            raise StepHold('plan_digest_mismatch', 'the engagement decision does not cover the approved scientific bytes')
        for view in (plan if 'engagement' in plan else None, protected, applied):
            if view is None:
                continue
            if type(view) is not dict or view.get('sha256') != wanted or engagement.check_applied(view, decision):
                raise StepHold('engagement_view_invalid', 'the complete applied view differs from the current decision')
        pin = (protected or applied).get('engagement') or {}
        if record.get('applied_blob') and record.get('applied_sha256') != pin.get('applied_sha256'):
            raise StepHold('engagement_view_invalid', 'the protected applied-view digest differs from its plan record')
        expected = (context or {}).get('applied_sha256')
        if expected is not None and expected != (applied.get('engagement') or {}).get('applied_sha256'):
            raise StepHold('engagement_view_invalid', 'the context applied-view digest is stale')
    except StepHold:
        raise
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise StepHold('engagement_view_invalid', str(exc)[:500]) from None
    return deepcopy(applied)


RESEARCH_DERIVED_KINDS = ('author', 'operate', 'route')


def _research_derived_step(store, step, plan, context):
    """Bind a controller-published research inner step to the exact current approved research parent, or None.

    The research controller publishes each inner step it dispatches (``research-derived-step``) against the
    protected entry of its parent ``research.loop`` subgraph step (``research-subgraph-entry``). The binding holds
    unless the step bytes, the parent plan, the parent step, its request pin and bytes and its campaign contract
    are all exactly the approved ones. This is an approved-parent lineage check, not effect authorization:
    reservation, source custody, executor, operation and authority checks follow as for every step.
    """
    try:
        rows = [unwrap(row) for row in store.scan('research-derived-step')]
    except (KeyError, OSError, ValueError, TypeError, AttributeError) as exc:
        raise StepHold('research_derived_step_unbound', str(exc)[:500]) from None
    candidates = [row for row in rows if type(row) is dict and type(row.get('step')) is dict
                  and row['step'].get('id') == step['id']]
    if not candidates:
        return None
    derived = candidates[-1]
    # The publisher seals both records with the research journal digest (``candidate_experiments.digest``);
    # the exact step and parent bytes are compared as well.
    from ravel.workflow.candidate_experiments import digest as sealed
    try:
        if (derived['step'] != step or derived['step_sha256'] != sealed(step)
                or derived['parent_plan_sha256'] != plan['sha256']):
            raise ValueError('derived step or parent plan changed')
        entry_id = derived['parent_entry_id']
        if type(entry_id) is not str or not entry_id:
            raise ValueError('protected parent entry id required')
        raw = store.read('research-subgraph-entry', entry_id)
        if type(raw) is not dict:
            raise ValueError('protected research parent entry required')
        if raw.get('id', raw.get('record_id', entry_id)) != entry_id:
            raise ValueError('protected parent entry identity changed')
        entry = unwrap(raw)
        parent = entry['parent_step']
        actual = [row for row in plan.get('steps') or () if type(row) is dict and row.get('id') == parent['id']]
        if (entry['parent_plan_sha256'] != plan['sha256'] or len(actual) != 1 or actual[0] != parent
                or entry['parent_step_sha256'] != sealed(parent) or parent.get('kind') != 'subgraph'
                or (parent.get('graph') or {}).get('id') != 'research.loop'):
            raise ValueError('original approved research parent changed')
        parameters = parent.get('parameters') or {}
        from ravel.workflow import research_cycle as cycle, research_coordinator_decisions as decisions
        if 'research_request' in parameters:
            if parameters['research_request'] != entry['request']:
                raise ValueError('original research request binding changed')
            bound_campaign = parameters['campaign']
        else:
            # A bounded sub-question carries no adopted request: its request is the controller-derived pin bound
            # to exactly this approved step and plan, and its campaign is the step's own.
            from ravel.workflow import bounded_research
            if bounded_research.bound_record(store, parent, entry['request'],
                                             {'plan_sha256': plan['sha256']}) is None:
                raise ValueError('original research request binding changed')
            bound_campaign = bounded_research.campaign_root(context['run_dir'], parent)
        campaign = cycle._ordinary(entry['campaign']).resolve(strict=True)
        if cycle._ordinary(bound_campaign).resolve(strict=True) != campaign:
            raise ValueError('original campaign binding changed')
        pin = entry['request']
        if cycle._check_pin(pin, context['run_dir'])[1] != pin:
            raise ValueError('original research request pin changed')
        from ravel.workflow.research_orchestrator import campaign_contract
        if cycle._load(campaign)[1]['contract'] != campaign_contract(decisions.request(pin)):
            raise ValueError('original campaign request contract changed')
        if step.get('kind') not in RESEARCH_DERIVED_KINDS:
            raise ValueError('unsupported derived research step kind')
        if step['kind'] == 'route':
            child = step.get('parameters') or {}
            if (step.get('route') != 'study' or child.get('own_checkin1') is not True
                    or child.get('inherit_budget') is not True or child.get('inherit_authority') is not True):
                raise ValueError('derived child must retain its own approval and inherited bounds')
        return deepcopy(step), plan['sha256'], 'derived_research_step'
    except (KeyError, IndexError, StopIteration, OSError, ValueError, TypeError, AttributeError) as exc:
        raise StepHold('research_derived_step_unbound', str(exc)[:500]) from None


def referenced_seat(plan, step):
    """The applied view's seat descriptor a derived review seat names by reference (``engagement_seat_ref``: the
    descriptor's key and digest). The seat must carry exactly that descriptor's packet step engagement (its folded
    items, cards, manifests, scope and constraints) and one reviewer item per descriptor item; anything else holds."""
    parameters = step.get('parameters') or {}
    ref = parameters.get('engagement_seat_ref')
    seats = ((plan.get('engagement') or {}).get('seat_plan') or {}).get('seats') or ()
    found = [row for row in seats if type(ref) is dict and type(row) is dict and row.get('key') == ref.get('key')
             and digest(row) == ref.get('sha256')]
    if len(found) != 1:
        raise StepHold('engagement_view_invalid', 'the derived seat names no descriptor of the applied view')
    row = found[0]
    if (step.get('engagement') != (row.get('step') or {}).get('engagement')
            or parameters.get('reviewer_items') != row.get('items')):
        raise StepHold('engagement_view_invalid', 'the derived seat does not carry its descriptor\'s folded duties')
    return deepcopy(row)


def plan_step(store, step, context):
    """``(approved step, plan sha256, binding)``: the plan's record of this step with equal bytes.

    A review seat the controller derives for a check-in is bound by its subject: its parameters
    name the pinned plan digest, and it carries no operation, launch or graph of its own.
    """
    plan = current_plan(store, context)
    if (context or {}).get('research_child_engagement') is not None:
        from ravel.controller.routes.research import child_engagement as children
        child = children.resolve(store, plan, context)
        found = [row for row in child['steps'] if row['id'] == step['id']]
        if len(found) != 1 or found[0] != step:
            raise StepHold('plan_step_changed', 'the acting child step differs from its admitted applied view')
        return deepcopy(found[0]), plan['sha256'], 'research_route_child'
    found = [row for row in plan.get('steps') or () if type(row) is dict and row.get('id') == step['id']]
    if len(found) == 1:
        if digest(found[0]) != digest(step):
            raise StepHold('plan_step_changed', f"step {step['id']} differs from the approved plan; a changed step "
                           'is a deviation that needs renewed authority')
        return deepcopy(found[0]), plan['sha256'], 'plan_step'
    if found:
        raise StepHold('plan_step_ambiguous', f"step {step['id']} appears more than once in the plan")
    research = _research_derived_step(store, step, plan, context)
    if research is not None:
        return research
    subject = (step.get('parameters') or {}).get('subject_plan_sha256')
    if (step['kind'] == 'review' and subject == plan['sha256'] and not step.get('operation')
            and not (step.get('parameters') or {}).get('launch') and not step.get('graph')):
        if plan.get('engagement'):
            parameters = step.get('parameters') or {}
            category = {'plan': 'checkin1', 'waypoint': 'checkin2', 'checkin2': 'checkin2',
                        'final': 'checkin3', 'attacks': 'attack', 'integrity': 'integrity'}.get(parameters.get('purpose'))
            declared = [row for row in plan['engagement']['seat_plan']['seats']
                        if row['role'] == step.get('role') and row['category'] == category and not row.get('conditional')]
            if parameters.get('purpose') == 'rdj':
                # A decision's RDJ case: the applied view declares one for the decide step this seat reviews, and the
                # seat is a card of the RDJ family.
                from ravel.workflow import role_registry
                cases = {row.get('step_id') for row in plan['engagement']['seat_plan'].get('rdj_cases') or ()}
                card = role_registry.card_id(step.get('role'))
                rdj = card is not None and role_registry.load(card).get('family') == 'rdj'
                declared = [step['depends_on'][0]] if rdj and len(step.get('depends_on') or ()) == 1 \
                    and step['depends_on'][0] in cases else []
            descriptor = parameters.get('engagement_seat')
            if parameters.get('engagement_seat_ref') is not None:
                if descriptor is not None:
                    raise StepHold('engagement_view_invalid', 'a derived seat names its descriptor once')
                descriptor = referenced_seat(plan, step)
            if not declared or (descriptor is not None and descriptor not in declared):
                raise StepHold('engagement_view_invalid', 'the derived review seat is not declared by the applied view')
        return deepcopy(step), plan['sha256'], 'derived_review_seat'
    raise StepHold('plan_step_missing', f"step {step['id']} is not in the approved plan")


def launch_digest(step):
    """The digest of the exact launch the plan approved (argv, environment capsule, reads and writes)."""
    launch = (step.get('parameters') or {}).get('launch') or {}
    return digest({'argv': launch.get('argv'), 'env': launch.get('env') or {}, 'reads': launch.get('reads') or [],
                   'outputs': [row['path'] for row in step['outputs']]})


def route_context(store, context):
    """Current plan and authenticated amendment lineage for route admission."""
    from ravel.controller.graph import service
    authority = service('authority')
    def current(kind, pins):
        if kind == 'approve_plan':
            lookup = getattr(authority, 'plan_authority', None)
            if not callable(lookup):
                raise StepHold('plan_authority_unavailable', 'the authority service checks the current plan chain')
            approval, amendment = lookup(store, pins)
            return amendment or approval
        return authority.current(store, kind, pins=pins)
    return {**context, 'store': store, 'plan': current_plan(store, context), 'authority': current}


def route_errors(step, context):
    """Route checks run after signature admission, including steps without operations."""
    from inspect import signature
    from ravel.controller.routes import inspect, ml
    # Both published forms remain usable while the context-aware route adapter folds in.
    parameters = signature(ml.admit).parameters
    if 'context' in parameters:
        problems = ml.admit(step, context=context)
    else:
        problems = _legacy_route_errors(step, context)
    return list(problems) + inspect.guard(step, context['plan'], route=context.get('route'))


def _legacy_route_errors(step, context):
    """The structural API cannot attest runtime staged prerequisites."""
    from ravel.controller.routes import manuscript, ml
    from ravel.controller.routes.ml import training
    if training.stage_of(step) is not None or manuscript.is_note_stage(step):
        raise StepHold('mode_context_admission_unavailable',
                       'staged execution requires the context-aware route admission service')
    return ml.admit(step, plan=context['plan'], authority=context['authority'])


def observe_route(step, outcome, context):
    """Keep staged ending checks inside the step's outcome custody boundary."""
    from ravel.controller.routes.ml import modes, training
    from ravel.controller.routes import manuscript
    observe = getattr(modes, 'observe', None)
    if callable(observe):
        return observe(step, outcome, context)
    if training.stage_of(step) is not None or manuscript.is_note_stage(step):
        raise StepHold('mode_observer_unavailable', 'the staged route must check its ending before completion')
    return outcome


def summary(signature):
    return json.loads(json.dumps({k: signature[k] for k in ('implementation', 'effects', 'cost', 'critical_fields')}))

# Analysis launch admission is kept separate from the shared operation checks above.
# These are closed adapters, not permission to run an arbitrary module or argv.
# The lifecycle declarations retain their registered identity; their concrete native
# executor consumes an already prepared, approved execution plan.
ANALYSIS_LAUNCHES = {
    'lifecycle-routine-recast': {
        'implementation': {'kind': 'lifecycle-stage', 'stage': 'routine-recast',
                           'module': 'ravel.workflow.workflow_state'},
        'role': 'analysis-author', 'stage': 'routine-recast',
        'argv': ('python', '-m', 'ravel.physics.native_pipeline', 'run'),
        'task_fields': ('max_seconds', 'analysis', 'detector_mode', 'executor'),
        'executor_fields': ('execution_plan',), 'input': 'execution_plan', 'flag': '--plan'},
    'analysis-lifecycle': {
        'implementation': {'kind': 'lifecycle-stage', 'stage': 'route-a-run',
                           'module': 'ravel.workflow.workflow_state'},
        'role': 'analysis-author', 'stage': 'route-a-run',
        'argv': ('python', '-m', 'ravel.physics.native_pipeline', 'run'),
        'task_fields': ('max_seconds', 'analysis', 'detector_mode', 'stat_mode', 'executor'),
        'executor_fields': ('execution_plan',), 'input': 'execution_plan', 'flag': '--plan'},
    'lifecycle-scan-aggregation': {
        'implementation': {'kind': 'lifecycle-stage', 'stage': 'scan-aggregation',
                           'module': 'ravel.workflow.scan_orchestrator'},
        'role': 'inference', 'stage': 'scan-aggregation',
        'argv': ('python', '-m', 'ravel.controller.routes.analysis.evidence', 'assemble'),
        'task_fields': ('executor',), 'executor_fields': ('manifest',),
        'input': 'manifest', 'flag': '--manifest'},
    'figure-comparison': {
        'implementation': {'kind': 'science-mode', 'mode': 'figure-comparison',
                           'module': 'ravel.physics.figure_comparison'},
        'role': 'analysis-author', 'stage': 'figure',
        'argv': ('python', '-m', 'ravel.physics.figure_comparison'),
        'task_fields': ('executor',), 'executor_fields': ('action', 'specification'),
        'input': 'specification', 'flag': '--spec',
        'actions': ('digitize', 'plane', 'measurement')},
}

# Explicit literature operations above search. Closed adapters: the step runs as a host operation of the
# coordinator (``host_operations``); the command dispatches the registered literature card through the role
# dispatcher, and its Graph calls are charged by the campaign. Search never reaches them, and no worker
# argument selects a module, argv or dispatched card.
LITERATURE_OPERATIONS = {
    'literature-query-expansion': {
        'implementation': {'kind': 'command', 'module': 'ravel.workflow.research_tools'},
        'dispatches': 'literature-query-expander', 'argv': ('python', '-m', 'ravel.workflow.research_tools',
                                                      'literature-expand'),
        'flag': '--request', 'graph_id_prefix': 'literature-query-expansion-', 'calls': 'one'},
    'literature-evidence-scoring': {
        'implementation': {'kind': 'command', 'module': 'ravel.workflow.research_tools'},
        'dispatches': 'literature-evidence-scorer', 'argv': ('python', '-m', 'ravel.workflow.research_tools',
                                                       'literature-score'),
        'flag': '--request', 'graph_id_prefix': 'literature-evidence-scoring-', 'calls': 'one per batch'},
    'literature-discovery-crawl': {
        'implementation': {'kind': 'command', 'module': 'ravel.workflow.research_tools'},
        'dispatches': 'literature-discovery-selector', 'argv': ('python', '-m', 'ravel.workflow.research_tools',
                                                                'literature-crawl'),
        'flag': '--request', 'graph_id_prefix': '', 'calls': 'one per page and one per selector batch'},
}


def literature_launch_errors(step):
    """Why a literature operation step is outside its closed adapter (empty when it fits)."""
    policy = LITERATURE_OPERATIONS.get(step.get('operation'))
    if policy is None:
        return []
    errors = []
    argv = ((step.get('parameters') or {}).get('launch') or {}).get('argv')
    expected = len(policy['argv']) + 2
    if (type(argv) is not list or len(argv) != expected or tuple(argv[:len(policy['argv'])]) != policy['argv']
            or argv[-2] != policy['flag'] or type(argv[-1]) is not str or not argv[-1]):
        errors.append({'code': 'literature_launch_unadmitted', 'operation': step['operation'],
                       'argv': list(policy['argv']) + [policy['flag'], '<request>']})
    return errors
