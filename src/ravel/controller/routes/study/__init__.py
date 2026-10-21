"""Route hooks for supplied studies, scoped operations and literal calculations.

Planning and route checks run on the controller side. Scientific effects remain
steps of ``controller.step``; the hooks never launch a worker or record assent.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .contracts import adopted_json, bind_scope, digest, records, relative, requested, scope

DATA = Path(__file__).resolve().parents[3] / 'data'
SPEC_ARTIFACT = 'specify:outputs/specification.json'
SCOPE_ARTIFACT = 'specify:outputs/scope.json'
TRANSITIONS = frozenset(('approve_plan', 'checkin1', 'checkin2', 'checkin3', 'deviation',
                         'escalate', 'execute', 'dispatch', 'deliver'))


def parameters(spec, reading, contract, supplied):
    """Keep the full intake visible to specification authors and subsequent gates."""
    return {'study_request': {'contract': deepcopy(contract), 'reading': deepcopy(reading),
                              'supplied': deepcopy(list(supplied)),
                              'statistics': requested(reading, 'prescribed_statistic', 'statistic')},
            'study_bound': False}


def _tables():
    from ravel.workflow.operation_registration import read_signatures
    signatures = read_signatures(DATA / 'operation_signatures.json')
    executors = json.loads((DATA / 'roles/executors.json').read_text())['operations']
    return signatures, executors


def mode_admission(specification):
    """A vocabulary hit alone grants neither an adapter nor its execution role."""
    from ravel.workflow import science
    mode = specification.get('mode') if type(specification) is dict else None
    if mode not in (*science.MODES, *science.PROVIDER_MODES):
        raise ValueError('no ordinary typed study adapter for the selected mode')
    signatures, executors = _tables()
    signature = signatures.get(mode)
    if signature is None or not executors.get(mode):
        raise ValueError('study needs a registered operation signature and production role')
    # Validate the entire ordinary contract; no descriptor or route parameter
    # replaces the adapter's own validation or its prospective review policy.
    science.validate(specification)
    module = science.adapter(specification)
    if not callable(getattr(module, 'validate', None)):
        raise ValueError('the ordinary adapter has no typed validation contract')
    implementation = signature['implementation']
    if implementation.get('module') and implementation['module'] != module.__name__:
        raise ValueError('adapter implementation differs from the operation signature')
    from ravel.workflow.operation_check_policy import executor
    role = executor(mode, specification.get('task') or {}, executors[mode])
    return {'operation': mode, 'role': role, 'signature': deepcopy(signature)}


def implemented_stages(specification, admission):
    if specification['mode'] == 'generate':
        return ['generate', *(['shower'] if specification['generation'].get('shower') else [])]
    if specification['mode'] == 'likelihood':
        return ['likelihood']
    return list(admission['signature'].get('stages', []))


def compute_selection(coverage):
    """Read the child's explicit allocation from its adopted scope before plan review."""
    if 'compute' not in coverage:
        return None
    selected = coverage['compute']
    if (type(selected) is not dict or set(selected) != {'rung', 'reason'}
            or selected['rung'] not in ('smoke', 'full', 'scan')
            or type(selected['reason']) is not str or not selected['reason'].strip()
            or len(selected['reason']) > 16000):
        raise ValueError('child compute selection requires one smoke, full or scan rung and its reason')
    return deepcopy(selected)


def _binding(context):
    specification, spec_row = adopted_json(context, SPEC_ARTIFACT)
    coverage, scope_row = adopted_json(context, SCOPE_ARTIFACT)
    keys = {'schema_version', 'kind', 'deliverables', 'stages', 'child_rundir'}
    if (type(coverage) is not dict or not keys <= set(coverage)
            or set(coverage) - keys - {'evidence_requirements', 'site', 'compute'} or coverage['schema_version'] != 1
            or coverage['kind'] != 'study-scope'):
        raise ValueError('exact study-scope version1 record required')
    compute_selection(coverage)
    child = relative(coverage['child_rundir'])
    if len(child.parts) < 2 or child.parts[0] != 'children':
        raise ValueError('ordinary studies occupy a declared child under children/')
    route = context['plan']['route']
    route = route['id'] if type(route) is dict else route
    if 'site' in coverage:
        site_binding = coverage['site']
        if (route != 'study.site' or type(site_binding) is not dict
                or set(site_binding) not in ({'jobscript', 'wms_scope'}, {'jobscripts', 'wms_scope'})):
            raise ValueError('site launch bindings belong to their exact site scope')
        from .runtime import inspect_inputs
        if 'jobscript' in site_binding:
            pin = site_binding['jobscript']
            if (type(pin) is not dict or set(pin) != {'path', 'sha256'}
                    or type(pin['sha256']) is not str or len(pin['sha256']) != 64):
                raise ValueError('site scope requires its exact prepared jobscript pin')
            inspect_inputs(context['store'], [pin], run_dir=context['run_dir'])
        else:
            # One capability admits exactly these N prepared jobscripts and no more.
            pins = site_binding['jobscripts']
            if (type(pins) is not list or not pins or any(
                    type(pin) is not dict or set(pin) != {'path', 'sha256'}
                    or type(pin['sha256']) is not str or len(pin['sha256']) != 64 for pin in pins)):
                raise ValueError('site scope requires its exact prepared jobscript pins')
            if (len({json.dumps(pin['path']) for pin in pins}) != len(pins)
                    or len({pin['sha256'] for pin in pins}) != len(pins)):
                raise ValueError('site scope jobscript pins must be distinct')
            inspect_inputs(context['store'], pins, run_dir=context['run_dir'])
        wms_scope = site_binding['wms_scope']
        allowed = {'workflow_dir', 'tasks', 'rules', 'max_jobs', 'profile_sha256', 'resource_maxima'}
        if (type(wms_scope) is not dict or set(wms_scope) - allowed
                or not Path(wms_scope.get('workflow_dir', '')).is_absolute()):
            raise ValueError('site scope requires its original absolute workflow and capability limits')
        if 'jobscripts' in site_binding and (type(wms_scope.get('max_jobs')) is not int
                                             or wms_scope['max_jobs'] != len(site_binding['jobscripts'])):
            raise ValueError('site scope max_jobs must equal its pinned jobscript count')
    if route == 'scoped':
        from ravel.workflow import scoped_spec
        scoped_spec.require_valid(specification)
        if specification['mode'] != context['contract']['task_mode']:
            raise ValueError('scoped operation differs from the original request')
        admission = {'operation': 'scoped-' + specification['mode'],
                     'role': 'shower-detector' if specification['mode'] == 'generate' else 'inference',
                     'signature': {'stages': [], 'produces': [{'kind': 'document'}]}}
    else:
        admission = mode_admission(specification)
        if route == 'calculation':
            if specification['mode'] != 'literal-calculation':
                raise ValueError('physical calculation remains a judgment obligation')
            from ravel.physics.literal_calculation import validate_parent
            validate_parent(specification['task'], Path(context['run_dir']))
        elif specification.get('schema_version') != 2:
            raise ValueError('supplied studies require their prospective version2 review contract')
    declared = set(implemented_stages(specification, admission))
    if set(coverage['stages']) - declared:
        raise ValueError('coverage names stages the typed operation does not implement')
    scope(context['reading'], coverage['deliverables'], coverage['stages'])
    return specification, coverage, admission, spec_row, scope_row


def bind(plan, context):
    """Bind adopted scope, allocation and specification before plan review and CHECK-IN 1."""
    specification, coverage, admission, spec_row, scope_row = _binding(context)
    out = bind_scope(plan, context['reading'], coverage['deliverables'], coverage['stages'])
    params = out.setdefault('parameters', {})
    params['study_bound'] = True
    params['study_binding'] = {'specification_sha256': spec_row['sha256'],
                               'scope_sha256': scope_row['sha256'],
                               'child_rundir': coverage['child_rundir'],
                               'mode': specification['mode'],
                               'max_seconds': specification['max_seconds'],
                               'max_attempts': specification.get('max_attempts', 1),
                               'covered': coverage['deliverables'], 'stages': coverage['stages']}
    selected_compute = compute_selection(coverage)
    if selected_compute is not None:
        params['study_binding']['compute'] = selected_compute
    preparation = None
    if any(node['id'] == 'prepare-child' for node in plan['steps']):
        preparation, preparation_row = adopted_json(context, 'prepare-child:outputs/preparation.json')
        if preparation.get('kind') != 'ordinary-study-preparation':
            raise ValueError('adopt the actual ordinary plan preparation receipt before CI1')
        ordinary = preparation.get('ordinary') or {}
        if ordinary.get('child_rundir') != coverage['child_rundir']:
            raise ValueError('prepared ordinary child differs from the requested child scope')
        from ravel.workflow import science, scoped
        module = scoped if ordinary.get('kind') == 'scoped' else science
        child = Path(context['run_dir']) / relative(ordinary['child_rundir'])
        from .contracts import pinned_json
        for filename, field in ((module.PLAN, 'plan_sha256'), (module.SPEC, 'specification_sha256')):
            pinned_json(context['run_dir'], {'path': str(relative(ordinary['child_rundir']) / filename),
                                             'sha256': ordinary[field]})
        params['study_binding']['ordinary'] = deepcopy(ordinary)
        params['study_binding']['preparation_sha256'] = preparation_row['sha256']
    for node in out['steps']:
        if node['id'] == 'operate':
            node.update(operation=admission['operation'], role=admission['role'])
            if selected_compute is not None:
                node['rung'] = selected_compute['rung']
            elif ((node.get('parameters') or {}).get('study_binding') or {}).get('compute') is not None:
                node['rung'] = None
            from ..validator_inputs import declare_role_inputs
            declare_role_inputs(node)
            node.setdefault('budget', {}).update(wall_seconds=specification['max_seconds'], attempts=1)
            if 'generates_events' not in set((admission['signature'].get('effects') or ())):
                # A reservation names every dimension: an operation that generates no events reserves none.
                node['budget'].setdefault('events', 0)
            node.setdefault('parameters', {}).update(task=deepcopy(specification if specification['mode'] in ('generate', 'likelihood')
                                                                   else specification.get('task', {})),
                                                   study_binding=deepcopy(params['study_binding']),
                                                   adapter='ravel.controller.routes.study.runtime',
                                                   evidence_requirements=deepcopy(coverage.get('evidence_requirements', [])))
            if preparation is not None:
                node['parameters']['ordinary'] = deepcopy(preparation['ordinary'])
                # The approved capsule is built by the installed adapter after
                # ordinary authority, not authored as arbitrary argv by a worker.
                node['parameters']['launch'] = {'adapter': 'ravel.controller.routes.study.runtime'}
                node['attempt_limit'] = specification.get('max_attempts', 1)
            if 'site' in coverage:
                node['parameters']['wms_scope'] = deepcopy(coverage['site']['wms_scope'])
                field = 'jobscripts' if 'jobscripts' in coverage['site'] else 'jobscript'
                node['parameters'].setdefault('launch', {})[field] = deepcopy(coverage['site'][field])
            elif preparation is not None and preparation.get('site_launch'):
                # A governed workflow preparation adopted the supplied workflow for a batch site: the
                # request's job count, the adoption's declared rules and the pinned site profile bound
                # one capability, and the submission broker serves the confined run.
                launch = preparation['site_launch']
                if (type(launch) is not dict or set(launch) != {'wms_scope', 'batch', 'site_broker'}
                        or type(launch['batch']) is not int or launch['batch'] < 1):
                    raise ValueError('the prepared site launch needs its wms_scope, batch job count and site_broker')
                node['parameters']['wms_scope'] = deepcopy(launch['wms_scope'])
                node['parameters'].setdefault('launch', {})['batch'] = launch['batch']
                node['parameters']['site_broker'] = deepcopy(launch['site_broker'])
                node['parameters']['site_workflow'] = {'workflow_root': preparation['workflow_root']}
                batch_order(out['steps'])
            from .evidence import requirements
            requirements(node)
            if admission['operation']:
                # The operation's catalogue rows: a provider mode has no vocabulary descriptor and
                # therefore no MODE row; its TOOL and EXEC rows are the ones its receipts discharge.
                from ravel.controller.ledger import load_catalogue
                known = load_catalogue().rows
                obligations = node.setdefault('obligations', [])
                for row in ('MODE-' + admission['operation'], 'TOOL-' + admission['operation'],
                            'EXEC-' + admission['operation']):
                    if row not in obligations and row in known:
                        obligations.append(row)
            # Every scientific instruction reaches the packet even if the
            # operation's applicability is discovered only during preparation.
            for path in _operation_instructions(admission):
                if path not in node['instruction_sources']:
                    node['instruction_sources'].append(path)
            for slot in admission['signature'].get('produces', []):
                # Concrete products are selected by the ordinary prepared plan,
                # not guessed from the name of an operation or signature slot.
                node['parameters'].setdefault('required_artifact_kinds', []).append(slot['kind'])
            products = admission['signature'].get('produces', [])
            if products and node.get('outputs'):
                node['outputs'][0]['kind'] = products[0]['kind']
    out['sha256'] = digest({k: v for k, v in out.items() if k != 'sha256'})
    return out


def operation_inputs(step, context, inputs_custody):
    """Separate verified preparation controls from the operation's scientific artifacts.

    The approved step binds all three control documents and the ordinary plan.
    That plan's own verifier checks the adapter schema and complete source closure.
    Original custody records continue to identify the step's full input subject.
    """
    from . import runtime
    from .contracts import pinned_json
    parameters = step.get('parameters') or {}
    bound = parameters.get('study_binding') or {}
    plan = context['plan']
    if (parameters.get('adapter') != runtime.ADAPTER
            or bound != (plan.get('parameters') or {}).get('study_binding')
            or not any(node == step for node in plan['steps'])):
        raise ValueError('scientific input roles require the exact approved ordinary step')
    specification, spec_row = adopted_json(context, SPEC_ARTIFACT)
    coverage, scope_row = adopted_json(context, SCOPE_ARTIFACT)
    selected_compute = compute_selection(coverage)
    if (bound.get('compute') != selected_compute
            or (selected_compute is not None and step.get('rung') != selected_compute['rung'])):
        raise ValueError('the compute selection must equal the adopted child scope and approved step')
    admission = mode_admission(specification)
    if (step.get('operation') != admission['operation'] or step.get('role') != admission['role']
            or parameters.get('task') != (specification if specification['mode'] in ('generate', 'likelihood')
                                          else specification.get('task', {}))):
        raise ValueError('the operation and complete task must equal the adopted scientific specification')
    preparation, prep_row = adopted_json(context, 'prepare-child:outputs/preparation.json')
    if (preparation.get('kind') != 'ordinary-study-preparation'
            or preparation.get('ordinary') != parameters.get('ordinary')
            or preparation.get('ordinary') != bound.get('ordinary')
            or coverage['child_rundir'] != bound.get('child_rundir')):
        raise ValueError('the preparation and scope must bind this ordinary child')
    controls = ((SPEC_ARTIFACT, spec_row, 'specification_sha256'),
                (SCOPE_ARTIFACT, scope_row, 'scope_sha256'),
                ('prepare-child:outputs/preparation.json', prep_row, 'preparation_sha256'))
    for artifact, adopted, pin in controls:
        matches = [row for row in inputs_custody if row.get('artifact') == artifact]
        if (len(matches) != 1 or adopted['sha256'] != bound.get(pin)
                or adopted.get('kind') != 'document'
                or any(matches[0].get(key) != adopted.get(key)
                       for key in ('artifact', 'destination', 'sha256', 'status', 'kind'))):
            raise ValueError('each preparation control requires its exact accepted document custody')
    ordinary, child, module, proposal = runtime._ordinary(step, context, approved=False)
    original = pinned_json(context['run_dir'], {
        'path': str(relative(ordinary['child_rundir']) / module.SPEC),
        'sha256': ordinary['specification_sha256']})
    if original != specification:
        adapter = module.adapter(specification)
        verifier = getattr(adapter, 'verify_prepared_specification', None)
        if not callable(verifier):
            raise ValueError('the ordinary child specification must equal the adopted source contract')
        verifier(specification, original, base=Path(context['run_dir']), preparation=preparation)
    control_ids = {artifact for artifact, _, _ in controls}
    scientific = [row for row in inputs_custody if row.get('artifact') not in control_ids]
    consumed = {slot['kind'] for slot in admission['signature']['consumes']}
    with runtime.capsule_runtime():
        sources = {str(path) for path in module.task_inputs(original, proposal['base_dir'])}
    for row in scientific:
        if row.get('kind') not in consumed:
            continue  # The operation signature checks the artifact kind below.
        path = Path(context['run_dir']) / relative(row['destination'])
        if (str(path) not in sources or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != row.get('sha256')):
            raise ValueError('a scientific artifact must match this ordinary source closure by path and digest')
    return scientific


def _operation_instructions(admission):
    instructions = []
    from ravel.controller.instructions import catalogue
    operation = admission.get('operation')
    projected = catalogue.installed().manifests.get('operations', {}).get(operation)
    # A registered operation's admission carries the installed signature (its implementation names the
    # adapter); the projection is checked against that exact signature before its instructions are
    # delivered. A scoped placeholder signature declares no implementation and takes the route's own sources.
    if projected is not None and admission['signature'].get('implementation'):
        if digest(admission['signature']) != projected['signature_sha256']:
            raise ValueError('operation instruction signature differs from its installed source projection')
        instructions.append('operation:' + operation)
    registration = admission['signature'].get('registration') or {}
    for row in registration.get('documentation', []):
        path = row.get('path') if type(row) is dict else row
        if path and path not in instructions:
            instructions.append(path)
    return instructions


def gate(transition, context):
    if transition.split('->', 1)[0] not in TRANSITIONS:
        return []
    plan = context['plan']
    errors = []
    bound = (plan.get('parameters') or {}).get('study_binding')
    if not bound:
        return [{'code': 'study_not_bound', 'message': 'adopt the complete typed specification before CI1'}]
    try:
        _, coverage, _, spec_row, scope_row = _binding(context)
        if (spec_row['sha256'] != bound['specification_sha256']
                or scope_row['sha256'] != bound['scope_sha256']):
            errors.append({'code': 'study_binding_changed', 'message': 'renew plan authority after changed input bytes'})
        errors += [{'code': 'study_scope_open', 'message': row['reason'], 'obligation': row['id']}
                   for row in scope(context['reading'], bound['covered'], bound['stages'])]
    except (ValueError, KeyError, OSError, TypeError) as exc:
        errors.append({'code': 'study_binding_invalid', 'message': str(exc)})
    for row in plan.get('open_obligations', []):
        errors.append({'code': 'study_scope_open', 'obligation': row['id'], 'message': row.get('reason', row['id'])})
    if transition.split('->', 1)[0] in ('checkin3', 'deliver'):
        errors.extend(final_evidence(context))
    return errors


def external_recipe_errors(step, context):
    """Generation needs retained source recipe bytes bound into the approved plan."""
    import hashlib
    params = step.get('parameters') or {}
    effects = set(params.get('effects') or ())
    if step.get('operation'):
        signatures, _ = _tables()
        effects.update((signatures.get(step['operation']) or {}).get('effects') or ())
    if 'generates_events' not in effects:
        return []
    pin = (context.get('plan') or {}).get('parameters', {}).get('external_recipe') or context.get('external_recipe')
    try:
        if type(pin) is not dict or type(pin.get('sha256')) is not str:
            raise ValueError('source recipe pin missing')
        path = Path(context['run_dir']) / relative(pin['path'])
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError('source recipe symlink')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']:
            raise ValueError('source recipe bytes missing or changed')
    except (OSError, ValueError, KeyError, TypeError):
        return [{'code': 'external_recipe_missing', 'message': 'retain a digest-pinned source recipe before generation'}]
    return []


def admit(step, context):
    if (step.get('parameters') or {}).get('phase') == 'prepare':
        return []
    errors = gate('dispatch', context)
    errors.extend(external_recipe_errors(step, context))
    if step['id'] == 'operate':
        # This worker cannot change the launch/authority boundary owned by the
        # shared step and confinement packages. An empty argv is never support.
        launch = (step.get('parameters') or {}).get('launch')
        if not launch and not (step.get('parameters') or {}).get('ordinary'):
            errors.append({'code': 'study_launcher_unbound',
                           'message': 'the shared confined launcher must bind the approved ordinary child'})
        from .evidence import check
        errors.extend(check(context['store'], step, context, phase='dispatch'))
    if step['id'] in ('synthesize', 'deliver'):
        errors.extend(final_evidence(context))
    return errors


def final_evidence(context):
    """Intermediate candidate custody cannot substitute for final operation review."""
    bound = (context['plan'].get('parameters') or {}).get('study_binding') or {}
    if not bound:
        return [{'code': 'study_not_bound', 'message': 'ordinary study binding is missing'}]
    child = Path(context['run_dir']) / relative(bound['child_rundir'])
    from ravel.workflow import science, scoped
    from .runtime import capsule_runtime
    try:
        with capsule_runtime():
            packet = (scoped.evaluate(child, context['contract']) if bound['mode'] in ('generate', 'likelihood')
                      else science.packet(child))
        if packet.get('lifecycle_verdict', packet.get('verdict')) != 'PASS':
            return [{'code': 'study_review_pending', 'message': 'current operation review and result evidence are not complete'}]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return [{'code': 'study_evidence_invalid', 'message': str(exc)}]
    route = context['plan'].get('route')
    if (route.get('id') if isinstance(route, dict) else route) == 'study.site':
        from . import remote
        return remote.check(context)
    return []


def batch_order(steps):
    """The step order of a batch submission: the operation returns once every job is submitted.

    The operation review (CHECK-IN 2) then sees the submitted operation while its jobs run, and the
    reconciliation step, gated by that review's go-ahead, waits for the jobs and adopts their outputs.
    A single driver job keeps the route's own order (reconciliation before the review).
    """
    nodes = {node['id']: node for node in steps}
    if not {'operate', 'operation-review', 'reconcile'} <= set(nodes):
        raise ValueError('a batch site plan needs its operate, operation-review and reconcile steps')
    nodes['operation-review']['depends_on'] = [d for d in nodes['operation-review']['depends_on'] if d != 'reconcile']
    nodes['reconcile']['depends_on'] = list(dict.fromkeys([*nodes['reconcile']['depends_on'], 'operation-review']))
    nodes['reconcile']['rung'] = 'full'
    return steps


def checkin(kind, context):
    params = context['plan'].get('parameters') or {}
    view = {'route': context['plan']['route'], 'review_items': [
        {'id': 'whole_scope', 'text': 'Compare all original deliverables, stages, units and statistics with the child.'},
        {'id': 'ordinary_contract', 'text': 'Retain prospective review, corrections and every original execution ceiling.'}],
        'study_binding': deepcopy(params.get('study_binding')),
        'open_obligations': deepcopy(context['plan'].get('open_obligations', []))}
    store = context.get('store')
    if kind in ('approve_plan', 'checkin1') and store is not None and params.get('study_bound'):
        # The check-in's own rows, from the route's evidence: the plan review's credit and the bound
        # study (the route declares no check-in variant).
        from ..analysis import discharge
        evidence = {'validator': 'route.study.bind+plan_review', 'sha256': context['plan'].get('sha256'),
                    'mechanism': 'route.study'}
        if not any(c.get('variants') for c in context['plan'].get('checkins') or ()):
            discharge.record(store, 'authority.ci1', 'not_applicable',
                             {**evidence, 'reason': 'not_applicable:route_declares_no_checkin_variant'}, rows={'C04'})
        credit = discharge.credit(context, 'checkin1')
        if credit:
            discharge.record(store, 'authority.ci1', 'satisfied', {**evidence, 'credit': credit}, rows={'A06', 'C03'})
            # The bound specification states its assumptions; a flagged result-sensitive one (reason and
            # alternatives) would be a numbered flag of the study binding. None flagged: the row is not
            # applicable, with the count of stated assumptions as its evidence.
            flagged = [row for row in (params.get('study_binding') or {}).get('flags') or ()]
            if not flagged:
                discharge.record(store, 'authority.ci1', 'not_applicable',
                                 {**evidence, 'credit': credit, 'reason': 'not_applicable:no_result_sensitive_assumption_flagged'},
                                 rows={'C14'})
    return view


def packet_context(step, context):
    """Expose only the JSON-safe ordinary context through the adapter interface."""
    from .runtime import packet_context as packet
    return packet(context)


def _batch_plan(context):
    """Whether the plan's operation is a batch submission (the bound ``launch.batch`` form)."""
    operate = next((node for node in (context.get('plan') or {}).get('steps') or () if node.get('id') == 'operate'), {})
    return 'batch' in ((operate.get('parameters') or {}).get('launch') or {})


def dispatch(step, context, invoke):
    """Wrap the parent's substrate invocation at the approved site-step boundary."""
    route = (context.get('plan') or {}).get('route')
    route = route.get('id') if isinstance(route, dict) else route
    parameters = step.get('parameters') or {}
    if route == 'study.site' and step['id'] == 'reconcile' and _batch_plan(context):
        # The controller waits for the submitted batch jobs and adopts their outputs before the
        # reconciliation worker describes them; worker text is never scheduler evidence.
        from . import site
        site.await_batch(context['store'], step, context)
        return invoke()
    if route != 'study.site' or not parameters.get('wms_scope'):
        if route == 'study.site' and step['id'] == 'operate':
            from .runtime import StudyHold
            raise StudyHold('the site operation needs its approved jobscript, scope and site budget')
        return invoke()
    from . import site
    return site.dispatch(context['store'], step, context, invoke)


def recover(context):
    """Observe original remote attempts before the parent schedules resumed work."""
    route = (context.get('plan') or {}).get('route')
    route = route.get('id') if isinstance(route, dict) else route
    if route != 'study.site':
        return None
    from . import remote, site
    from ravel.controller import authority
    store = context['store']
    errors = remote.capture(context)
    result = site.reconcile(store, drain=authority.stop_state(store) != 'running')
    store.append('study-recovery', {'errors': errors, 'reconciliation': result})
    return {'errors': errors, 'reconciliation': result}


def step(step, outcome, context):
    """Do not turn a process exit or a component result into whole-task closure."""
    from . import evidence
    instruction_problems = []
    if context.get('instruction_manifest_required'):
        instruction_problems = evidence.instruction_errors(context['store'], step, context,
            context.get('final_record') or {}, [row['path'] for row in step.get('outputs', [])])
    if step['id'] == 'inspect':
        if instruction_problems:
            return instruction_problems
        from .runtime import inspect_inputs, supplied_pins
        try:
            inspect_inputs(context['store'], supplied_pins(context), run_dir=context['run_dir'])
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return [{'code': 'study_input_invalid', 'message': str(exc)}]
        return []
    if step['id'] == 'reconcile':
        from . import remote
        return instruction_problems or remote.complete(context)
    if step['id'] == 'operation-review':
        operation = next((node for node in context['plan']['steps'] if node['id'] == 'operate'), step)
        return (instruction_problems + evidence.check(context['store'], operation, context, phase='review')
                + final_evidence(context))
    if step['id'] != 'operate':
        return instruction_problems
    errors = gate('dispatch', context)
    errors.extend(instruction_problems)
    errors.extend(evidence.check(context['store'], step, context, phase='adopt'))
    bound = (context['plan'].get('parameters') or {}).get('study_binding')
    if not bound:
        return errors
    child = Path(context['run_dir']) / relative(bound['child_rundir'])
    from ravel.workflow import science, scoped
    from .runtime import capsule_runtime
    try:
      with capsule_runtime():
        if bound['mode'] in ('generate', 'likelihood'):
            scoped.verify_plan(child, require_approval=True)
            packet = scoped.evaluate(child, context['contract'])
            if packet.get('verdict') != 'PASS':
                errors.append('scoped execution, executed recipe or result verification remains incomplete')
        else:
            science.verify_plan(child, approved=True)
            packet = science.packet(child)
            review_planned = any(node['id'] == 'operation-review' for node in context['plan'].get('steps', []))
            pending = (review_planned and packet.get('execution', {}).get('status') == 'awaiting_review'
                       and packet.get('errors') == [])
            if packet.get('lifecycle_verdict') != 'PASS' and not pending:
                errors.append('ordinary study evidence or prospective review remains incomplete')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return errors


def ending(reason, context):
    """The shared controller invokes the sink after this observational hook."""
    params = context['plan'].get('parameters') or {}
    context['store'].append('study-ending', {'reason': reason, 'binding': params.get('study_binding'),
        'open_obligations': deepcopy(context['plan'].get('open_obligations', [])),
        'steps': deepcopy(context.get('state', {}).get('steps', {})), 'scientific_acceptance_inferred': False})
    route = context['plan'].get('route') or {}
    if (route.get('id') if isinstance(route, dict) else route) == 'study.site':
        from . import remote
        from .site import reconcile
        context['store'].append('study-ending-backend', {'errors': remote.capture(context)})
        context['store'].append('study-ending-remote', reconcile(context['store'], drain=True))


__all__ = ['admit', 'bind', 'checkin', 'ending', 'gate', 'mode_admission', 'parameters', 'step',
           'packet_context', 'dispatch', 'recover', 'external_recipe_errors']
