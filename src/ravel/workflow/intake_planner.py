"""Bounded original-goal planning through the existing charged Host/Graph.

A real designer chooses a complete supplied-science specification or an exact
source-development continuation. The deterministic second node validates that
choice against the same inputs, writes fresh artifacts and prepares an ordinary
plan. It never approves, executes, edits adapter code or accepts the parent goal.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from . import agent_graph, capability_routing, intake, science
from .task_completion import _Inputs

MAX_PRESENTED_BYTES = 1_500_000
RESOURCE_BOUNDS = {'max_child_seconds': (1, 86400), 'max_calls': (2, 2),
                   'max_output_tokens': (16, 32000), 'max_wall_seconds': (1, 3600)}


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('exact intake planner fields required: ' + ', '.join(sorted(keys)))


def _json(raw):
    from .state_io import _unique
    def reject(value): raise ValueError('nonfinite planning JSON: ' + value)
    def finite(value):
        result = float(value)
        if not math.isfinite(result): raise ValueError('nonfinite planning number')
        return result
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject, parse_float=finite)


def _bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def _write(path, value, observed):
    raw = _bytes(value)
    path = Path(path).absolute()
    if '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('ordinary fresh preparation destination required')
    path.parent.mkdir(parents=True, exist_ok=True)
    pin = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    with path.open('xb') as stream: stream.write(raw)
    observed.file(pin)  # Compare to intended bytes, never the first arbitrary reread.
    return pin


def _resources(value):
    _keys(value, RESOURCE_BOUNDS)
    for key, (lo, hi) in RESOURCE_BOUNDS.items():
        if type(value[key]) is not int or not lo <= value[key] <= hi:
            raise ValueError('finite caller-declared planner resource outside bound: ' + key)
    return value


def _catalogue(inputs, source_root):
    catalogue = capability_routing.catalogue(source_root)
    selected_science = next(p for p in catalogue['source_pins'] if p['path'].endswith('/workflow/science.py'))
    if Path(selected_science['path']).resolve() != Path(science.__file__).resolve():
        raise ValueError('planner source authority must be the actually imported ordinary science implementation')
    for pin in catalogue['source_pins']:
        path = Path(pin['path'])
        inputs.file({**pin, 'size': path.stat().st_size})
    # Compare the same complete JSON representation written into the request.
    # Native registry tuples become JSON lists; every mode and source pin stays.
    return _json(_bytes(catalogue))


def prepare(parent_contract, output_dir, *, base_dir, candidate_modes, evidence, resources, source_root=None):
    """Supply grounded inputs and finite ceilings; no complete study template needed."""
    observed = _Inputs(base_dir)
    try:
        handoff = intake.execution_handoff(parent_contract, base_dir=base_dir)
        observed.file(parent_contract)
        _resources(resources)
        catalogue = _catalogue(observed, source_root)
        rows = {row['mode']: row for row in catalogue['operations']}
        if (type(candidate_modes) is not list or not 1 <= len(candidate_modes) <= 16
                or len(set(candidate_modes)) != len(candidate_modes) or any(m not in rows for m in candidate_modes)):
            raise ValueError('distinct actual candidate modes required; unresolved goals remain in the parent')
        if type(evidence) is not list or len(evidence) > 32:
            raise ValueError('at most32 explicitly supplied planning inputs required')
        selected = [deepcopy(rows[m]) for m in candidate_modes]
        presented = [deepcopy(parent_contract)]
        # Actual candidate API source contents are normal model inputs, not inferred
        # from the names in the complete catalogue. Unselected source stays custody only.
        for row in selected:
            if row.get('status') != 'source_present_not_admitted' or not row.get('source'):
                raise ValueError('candidate mode has no source-backed public dispatcher')
            pin = row['source']; presented.append({**pin, 'size': Path(pin['path']).stat().st_size})
        science_pin = next(p for p in catalogue['source_pins'] if p['path'].endswith('/workflow/science.py'))
        presented.append({**science_pin, 'size': Path(science_pin['path']).stat().st_size})
        for pin in evidence:
            observed.file(pin); presented.append(deepcopy(pin))
        presented = list({p['path']: p for p in presented}.values())
        if sum(p['size'] for p in presented) > MAX_PRESENTED_BYTES:
            raise ValueError('selected planner content exceeds1.5MB; select grounded smaller API/input context without dropping the parent objective')
        out = Path(output_dir).absolute()
        if out.exists(): raise ValueError('fresh planner preparation directory required')
        request = {'schema_version': 1, 'kind': 'intake-planning-request', 'parent_contract': deepcopy(parent_contract),
            'handoff': handoff, 'source_root': str(Path(source_root).absolute()) if source_root is not None else None,
            'catalogue': catalogue, 'candidate_modes': candidate_modes,
            'presented_inputs': presented, 'evidence': deepcopy(evidence), 'resources': deepcopy(resources),
            'limits': {'max_presented_bytes': MAX_PRESENTED_BYTES, 'max_science_inputs': 64},
            'parent_task_accepted': False, 'execution_authorized': False, 'physics_validated': False}
        pin = _write(out / 'request.json', request, observed)
        if pin['size'] + sum(p['size'] for p in presented) > MAX_PRESENTED_BYTES:
            raise ValueError('request plus actual API/input content exceeds1.5MB')
        observed.finish()
        return deepcopy(pin)
    finally: observed.close()


def _request(pin, observed):
    request = observed.document(pin)
    _keys(request, {'schema_version', 'kind', 'parent_contract', 'handoff', 'source_root', 'catalogue',
        'candidate_modes', 'presented_inputs', 'evidence', 'resources', 'limits',
        'parent_task_accepted', 'execution_authorized', 'physics_validated'})
    if request['schema_version'] != 1 or type(request['schema_version']) is not int or request['kind'] != 'intake-planning-request':
        raise ValueError('exact intake planning request required')
    if any(request[key] is not False for key in ('parent_task_accepted', 'execution_authorized', 'physics_validated')):
        raise ValueError('planning cannot carry acceptance or execution authority')
    if request['handoff'] != intake.execution_handoff(request['parent_contract'], base_dir=observed.base):
        raise ValueError('complete original parent handoff changed')
    if request['catalogue'] != _catalogue(observed, request['source_root']):
        raise ValueError('current complete source catalogue differs from planning source')
    _resources(request['resources'])
    if request['limits'] != {'max_presented_bytes': MAX_PRESENTED_BYTES, 'max_science_inputs': 64}:
        raise ValueError('declared planner input limits changed')
    rows = {row['mode']: row for row in request['catalogue']['operations']}
    modes = request['candidate_modes']
    if type(modes) is not list or not 1 <= len(modes) <= 16 or len(set(modes)) != len(modes) or any(m not in rows for m in modes):
        raise ValueError('actual distinct candidate mode population required')
    expected = [request['parent_contract']]
    for mode in modes:
        row = rows[mode]
        if row.get('status') != 'source_present_not_admitted': raise ValueError('candidate source absent')
        expected.append({**row['source'], 'size': Path(row['source']['path']).stat().st_size})
    sp = next(p for p in request['catalogue']['source_pins'] if p['path'].endswith('/workflow/science.py'))
    expected.append({**sp, 'size': Path(sp['path']).stat().st_size})
    if type(request['evidence']) is not list or len(request['evidence']) > 32: raise ValueError('bounded evidence required')
    expected.extend(request['evidence']); expected = list({p['path']: p for p in expected}.values())
    if request['presented_inputs'] != expected:
        raise ValueError('complete selected API/input presentation population differs')
    for item in expected: observed.file(item)
    if pin['size'] + sum(p['size'] for p in expected) > MAX_PRESENTED_BYTES:
        raise ValueError('complete planner presentation exceeds1.5MB')
    return request


def input_pins(request_pin, *, base_dir):
    observed = _Inputs(base_dir)
    try:
        request = _request(request_pin, observed)
        observed.finish()
        return deepcopy([request_pin, *request['presented_inputs']])
    finally: observed.close()


def graph_spec(request_pin, graph_root, output_dir, *, base_dir, graph_id, model, reasoning_effort, adapter='responses'):
    """Actual model choice followed by one authenticated Host preparation tool."""
    observed = _Inputs(base_dir)
    try:
        request = _request(request_pin, observed)
        if adapter not in ('model', 'responses', 'command', 'external', 'anthropic', 'gemini', 'chat_completions'):
            raise ValueError('existing configured model transport required')
        if any(type(v) is not str or not v.strip() for v in (model, reasoning_effort)):
            raise ValueError('explicit actual model/effort required')
        pins = [request_pin, *request['presented_inputs']]
        normal = [{'id': 'intake-request' if i == 0 else 'source-' + str(i), 'path': p['path'], 'sha256': p['sha256']}
                  for i, p in enumerate(pins)]
        schema = {'type': 'object', 'properties': {
            'kind': {'type': 'string', 'const': 'intake-plan-choice'},
            'request_sha256': {'type': 'string', 'const': request_pin['sha256']},
            'disposition': {'type': 'string', 'enum': ['scientific_study', 'source_development']},
            'reason': {'type': 'string', 'minLength': 1, 'maxLength': 16000},
            'plan_json': {'type': 'string', 'minLength': 2, 'maxLength': 200000}},
            'required': ['kind', 'request_sha256', 'disposition', 'reason', 'plan_json'], 'additionalProperties': False}
        r = request['resources']
        spec = {'schema_version': 1, 'graph_id': graph_id, 'goal_binding': request['handoff']['goal_binding'],
            'budget': {'max_nodes': 2, 'max_calls': r['max_calls'], 'max_output_tokens': r['max_output_tokens'],
                       'max_wall_seconds': r['max_wall_seconds'], 'max_reworks': 0},
            'nodes': [{'id': 'choose', 'kind': 'model', 'role': 'designer', 'depends_on': [],
                'inputs': normal, 'packet': None, 'action': adapter, 'max_attempts': 1,
                'parameters': {'model': model, 'reasoning_effort': reasoning_effort, 'max_output_tokens': r['max_output_tokens'],
                    'output_schema': schema, 'instructions': 'Preserve the complete original request and every unresolved scientific deliverable. Read the actual selected API source and supplied evidence. Return a complete ordinary science specification JSON using a selected mode and only supplied input files, or a concrete source-development request JSON with fields summary, missing_operations, owned_paths, input_contract, output_contract, acceptance_tests, source_evidence. A supplied study is a component; proposal, code construction and negative results cannot alone establish whole-parent acceptance. Do not invent data, calibration, physical units, outputs, approvals or adapter implementations. Preserve declared budgets. Literal dimensionless arithmetic may use schema1 and exact parent_contract in its task; other studies require schema2 goal_binding/review_policy. No guessed executable or arbitrary code execution.'}},
                {'id': 'prepare', 'kind': 'tool', 'role': 'executor', 'depends_on': ['choose'],
                 'inputs': normal, 'packet': None, 'action': 'intake-plan', 'max_attempts': 1,
                 'parameters': {'request_input': 'intake-request', 'graph_root': str(Path(graph_root).absolute()),
                                'output_dir': str(Path(output_dir).absolute())}}]}
        agent_graph.validate(spec); observed.finish()
        return deepcopy(spec)
    finally: observed.close()


def _origin(graph_root, request_pin, output_dir, observed):
    from .research_cycle import _graph_result
    root = Path(graph_root).absolute()
    observed.capture(root / agent_graph.SPEC)
    spec, _ = agent_graph._load(root)
    choose = next((n for n in spec['nodes'] if n['id'] == 'choose'), None)
    if choose is None: raise ValueError('actual planner chooser required')
    expected = graph_spec(request_pin, root, output_dir, base_dir=observed.base, graph_id=spec['graph_id'],
        model=choose['parameters']['model'], reasoning_effort=choose['parameters']['reasoning_effort'], adapter=choose['action'])
    if spec != expected: raise ValueError('actual Graph differs from exact bounded original-goal planner')
    origin = _graph_result(root, 'choose')
    observed.file(origin['receipt'])
    if origin['node_kind'] != 'model' or origin['role'] != 'designer' or origin['value'].get('kind') != 'model_result':
        raise ValueError('actual completed and charged designer model choice required')
    return origin


def materialize(request_pin, graph_root, output_dir, *, base_dir, presented_pins):
    """Consume the actual model receipt; compile and plan, never execute or approve."""
    observed = _Inputs(base_dir)
    try:
        request = _request(request_pin, observed)
        presented = {(str(Path(p['path']).absolute()), p['sha256']) for p in presented_pins}
        if any((p['path'], p['sha256']) not in presented for p in [request_pin, *request['presented_inputs']]):
            raise ValueError('complete actual planning request/API/evidence must be ordinary Graph inputs')
        origin = _origin(graph_root, request_pin, output_dir, observed)
        choice = origin['value']['value']
        _keys(choice, {'kind', 'request_sha256', 'disposition', 'reason', 'plan_json'})
        if choice['kind'] != 'intake-plan-choice' or choice['request_sha256'] != request_pin['sha256']:
            raise ValueError('designer choice belongs to another original request')
        if type(choice['reason']) is not str or not choice['reason'].strip() or len(choice['reason']) > 16000:
            raise ValueError('bounded reason required')
        if type(choice['plan_json']) is not str or len(choice['plan_json'].encode()) > 200000:
            raise ValueError('bounded complete plan JSON required')
        plan = _json(choice['plan_json'])
        out = Path(output_dir).absolute()
        parent = Path(request['parent_contract']['path']).parent.parent
        if out.exists() or not out.is_relative_to(parent) or out == parent:
            raise ValueError('fresh planner output within original parent intake required')
        record = {'schema_version': 1, 'kind': 'intake-planning-delivery', 'request': deepcopy(request_pin),
            'parent_contract': deepcopy(request['parent_contract']), 'goal_binding': deepcopy(request['handoff']['goal_binding']),
            'original_request': request['handoff']['original_request'], 'original_obligations': request['handoff']['obligations'],
            'origin': origin, 'disposition': choice['disposition'], 'reason': choice['reason'],
            'parent_task_accepted': False, 'execution_authorized': False, 'physics_validated': False}
        if choice['disposition'] == 'scientific_study':
            science.validate(plan)
            if (plan['mode'] not in request['candidate_modes'] or
                    plan['max_seconds'] * plan.get('max_attempts', 1) > request['resources']['max_child_seconds']):
                raise ValueError('selected actual adapter or child resource exceeds caller declaration')
            if plan['mode'] == 'literal-calculation':
                if (request['handoff']['task_kind'] != 'calculation' or plan['schema_version'] != 1
                        or plan['task']['parent_contract'] != request['parent_contract']):
                    raise ValueError('exact whole calculation requires bound ordinary literal task')
            elif plan.get('goal_binding') != request['handoff']['goal_binding'] or plan['schema_version'] != 2:
                raise ValueError('ordinary scientific component must preserve exact original goal and review policy')
            supplied = {p['path']: p for p in request['presented_inputs']}
            dependencies = science.task_inputs(plan, observed.base)
            if len(dependencies) > request['limits']['max_science_inputs']:
                raise ValueError('science input count exceeds explicit planning bound')
            for path in dependencies:
                name = str(path)
                if name not in supplied: raise ValueError('science dependency was not supplied and presented')
                observed.file(supplied[name])
            spec_pin = _write(out / 'science.json', plan, observed)
            prepared = science.plan(out / 'study', spec_pin['path'])
            # Bind the plan's intended returned value, not an arbitrary first reread.
            intended_plan = (json.dumps(prepared, indent=2, allow_nan=False) + '\n').encode()
            plan_path = out / 'study' / science.PLAN
            plan_pin = {'path': str(plan_path), 'sha256': hashlib.sha256(intended_plan).hexdigest(), 'size': len(intended_plan)}
            observed.file(plan_pin)
            copied_spec = _json(_bytes(plan))
            intended_spec = (json.dumps(copied_spec, indent=2, allow_nan=False) + '\n').encode()
            spec_path = out / 'study' / science.SPEC
            observed.file({'path': str(spec_path), 'sha256': hashlib.sha256(intended_spec).hexdigest(), 'size': len(intended_spec)})
            intended_checkin = (json.dumps(science.make_checkin(copied_spec, plan_pin['sha256'], prepared['stages'][0] if copied_spec['schema_version'] == 2 else None, base=out), indent=2, allow_nan=False) + '\n').encode()
            checkin_path = out / 'study' / 'inputs/checkin1.json'
            observed.file({'path': str(checkin_path), 'sha256': hashlib.sha256(intended_checkin).hexdigest(), 'size': len(intended_checkin)})
            if {str(p) for p in science.task_inputs(plan, out)} != {str(p) for p in dependencies}:
                raise ValueError('science input resolution changed across materialization')
            child_view = science.packet(out / 'study')
            if child_view['execution']['status'] != 'planned' or (out / 'study' / science.APPROVAL).exists():
                raise ValueError('planner must deliver only a fresh unapproved ordinary study')
            record.update(science_specification=spec_pin, child_root=str(out / 'study'),
                next_action='Review exact CHECK-IN1, approve the bounded plan and execute through ordinary science',
                remaining_parent_obligations=deepcopy(request['handoff']['obligations']))
        elif choice['disposition'] == 'source_development':
            _keys(plan, {'summary', 'missing_operations', 'owned_paths', 'input_contract', 'output_contract', 'acceptance_tests', 'source_evidence'})
            for key in ('summary', 'input_contract', 'output_contract'):
                if type(plan[key]) is not str or not plan[key].strip() or len(plan[key]) > 16000: raise ValueError('concrete source-development contract required')
            for key in ('missing_operations', 'owned_paths', 'acceptance_tests'):
                if type(plan[key]) is not list or not 1 <= len(plan[key]) <= 32 or any(type(v) is not str or not v.strip() or len(v) > 4000 for v in plan[key]):
                    raise ValueError('complete bounded source work/acceptance population required')
                if len(set(plan[key])) != len(plan[key]): raise ValueError('distinct source work rows required')
            for path in plan['owned_paths']:
                p = Path(path)
                if p.is_absolute() or '..' in p.parts or '\\' in path or not path.startswith(('src/ravel/', 'tests/', 'docs/')):
                    raise ValueError('explicit confined prospective source targets required')
            if type(plan['source_evidence']) is not list or not plan['source_evidence']:
                raise ValueError('actual source evidence required for missing-operation continuation')
            supplied = {p['path']: p for p in request['presented_inputs']}
            for pin in plan['source_evidence']:
                if supplied.get(pin.get('path')) != pin: raise ValueError('source development cites unpresented bytes')
                observed.file(pin)
            work = {**plan, 'kind': 'original-goal-source-development-request',
                'parent_contract': deepcopy(request['parent_contract']), 'original_request': request['handoff']['original_request'],
                'original_obligations': request['handoff']['obligations'], 'origin': origin,
                'required_before_adoption': ['isolated candidate source', 'meaningful original-goal positive/refusal controls', 'independent source review', 'ordinary integration and fresh plan'],
                'parent_task_accepted': False, 'execution_authorized': False, 'physics_validated': False}
            work_pin = _write(out / 'source-development.json', work, observed)
            record.update(source_development=work_pin,
                next_action='Implement this source-bound work package in isolated development, independently review and integrate it, then return to this original parent',
                remaining_parent_obligations=deepcopy(request['handoff']['obligations']))
        else: raise ValueError('unknown planner disposition')
        pin = _write(out / 'delivery.json', record, observed)
        # Recheck original Graph choice and every consumed source/output at return.
        if _origin(graph_root, request_pin, output_dir, observed) != origin: raise ValueError('actual designer origin changed during preparation')
        if choice['disposition'] == 'scientific_study':
            science.verify_plan(out / 'study')
            if (out / 'study' / science.APPROVAL).exists():
                raise ValueError('child was approved while the planner was still preparing it')
        observed.finish()
        return {'delivery': deepcopy(pin), 'value': deepcopy(record), 'execution_authorized': False, 'parent_task_accepted': False}
    finally: observed.close()


def controller_child(store, request_pin, graph_root, output_dir, *, base_dir, presented_pins):
    """Consume an ordinary charged planning delivery without granting child authority.

    Physical children and source continuations retain every original parent duty
    for judgment. Only an authenticated complete literal parent may take the
    literal operation path; its prepared child still needs ordinary approval.
    """
    output = Path(output_dir).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('controller planning requires a fresh unprepared output directory')
    observed = _Inputs(base_dir)
    try:
        request = observed.document(request_pin)
        parent_pin = request['parent_contract']
        observed.file(parent_pin)
        handoff = request['handoff']
        original = {'parent_contract': deepcopy(parent_pin),
                    'goal_binding': deepcopy(handoff['goal_binding']),
                    'original_request': handoff['original_request'],
                    'original_obligations': deepcopy(handoff['obligations'])}
        supplied = materialize(request_pin, graph_root, output, base_dir=base_dir,
                               presented_pins=presented_pins)
        if (type(supplied) is not dict or supplied.get('execution_authorized') is not False
                or supplied.get('parent_task_accepted') is not False):
            raise ValueError('the actual planning delivery grants no execution or parent acceptance')
        delivery = observed.document(supplied['delivery'])
        if delivery != supplied.get('value') or delivery.get('kind') != 'intake-planning-delivery':
            raise ValueError('actual delivery bytes differ from materialized planning result')
        if (delivery.get('request') != request_pin or
                any(delivery.get(key) != value for key, value in original.items()) or
                delivery.get('remaining_parent_obligations') != original['original_obligations']):
            raise ValueError('planning delivery changed the original parent obligations or goal')
        if any(delivery.get(key) is not False for key in
               ('execution_authorized', 'parent_task_accepted', 'physics_validated')):
            raise ValueError('a planner cannot authorize or accept its ordinary child')
        continuation = 'judgment'
        child_root = None
        literal_parent = None
        if delivery.get('disposition') == 'scientific_study':
            child = Path(delivery['child_root'])
            if (not child.is_absolute() or not child.is_relative_to(output) or child == output
                    or any(p.is_symlink() for p in (child, *child.parents))):
                raise ValueError('fresh planned child must stay within the actual planner output')
            spec = observed.document(delivery['science_specification'])
            copied = observed.document(observed.capture(child / science.SPEC))
            if copied != spec:
                raise ValueError('ordinary child specification changed from delivered bytes')
            science.verify_plan(child)
            view = science.packet(child)
            if view['execution']['status'] != 'planned' or (child / science.APPROVAL).exists():
                raise ValueError('only a fresh planned unapproved ordinary child may continue')
            if spec.get('mode') == 'literal-calculation':
                from ravel.physics.literal_calculation import validate_parent
                if (handoff.get('task_kind') != 'calculation' or spec.get('schema_version') != 1
                        or spec.get('task', {}).get('parent_contract') != parent_pin):
                    raise ValueError('literal exemption requires the exact original calculation parent')
                literal_parent = validate_parent(spec['task'], Path(base_dir))
                continuation = 'controller.step'
            elif spec.get('schema_version') != 2 or spec.get('goal_binding') != original['goal_binding']:
                raise ValueError('physical child must preserve the original scientific goal and review policy')
            # Observe plan bytes after the ordinary verifier, then recheck at return.
            observed.capture(child / science.PLAN)
            child_root = str(child)
        elif delivery.get('disposition') != 'source_development':
            raise ValueError('unknown ordinary planning continuation')
        body = {'kind': 'controller-intake-child', 'delivery': deepcopy(supplied['delivery']),
                **original, 'child_root': child_root, 'continuation': continuation,
                'remaining_parent_obligations': deepcopy(original['original_obligations']),
                'literal_parent': literal_parent, 'execution_authorized': False,
                'parent_task_accepted': False, 'physics_validated': False}
        # JSON-only controller evidence; the store remains outside worker outputs.
        body = _json(_bytes(body))
        observed.finish()
        body['record_id'] = store.append('controller-intake-child', deepcopy(body))
        return body
    finally:
        observed.close()


def record_checkin1_response(delivery_pin, *, user_text, quote, delegate_actor, actions,
                            bounds, task_class, blinding_policy=None, base_dir):
    """Forward the supplied actual CI1 response to the existing authority producer.

    The completed planner/child remain unchanged. This records a declaration
    transition; the separate ordinary delegated approval still decides the plan.
    """
    from . import scientific_autonomy
    from .research_cycle import _graph_result
    observed = _Inputs(base_dir)
    try:
        delivery = observed.document(delivery_pin)
        if (delivery.get('kind') != 'intake-planning-delivery'
                or delivery.get('disposition') != 'scientific_study'
                or any(delivery.get(k) is not False for k in ('parent_task_accepted', 'execution_authorized', 'physics_validated'))):
            raise ValueError('actual unapproved planner scientific delivery required')
        request = _request(delivery['request'], observed)
        output = Path(delivery_pin['path']).parent
        origin = _origin(delivery['origin']['root'], delivery['request'], output, observed)
        if origin != delivery['origin']:
            raise ValueError('planner origin changed before CI1 response')
        prepared = _graph_result(origin['root'], 'prepare')
        observed.file(prepared['receipt'])
        expected = {'delivery': delivery_pin, 'value': delivery,
                    'execution_authorized': False, 'parent_task_accepted': False}
        if (prepared['node_kind'] != 'tool' or prepared['role'] != 'executor'
                or prepared['value'].get('kind') != 'ravel_tool_result'
                or prepared['value'].get('action') != 'intake-plan'
                or _bytes(prepared['value'].get('value')) != _bytes(expected)):
            raise ValueError('CI1 response must consume the actual completed preparation receipt')
        plan = _json(origin['value']['value']['plan_json'])
        spec_pin = delivery['science_specification']
        if observed.file(spec_pin)[0] != _bytes(plan):
            raise ValueError('prepared child differs from actual planner choice')
        child = science.root(delivery['child_root'])
        if child != output / 'study': raise ValueError('original planner child identity required')
        observed.capture(child / science.SPEC); observed.capture(child / science.PLAN)
        observed.capture(child / 'inputs/checkin1.json')
        science.verify_plan(child)
        if (child / science.APPROVAL).exists(): raise ValueError('the original child is already approved; preserve its decision')
        observed.file(user_text)
        if blinding_policy is not None: observed.file(blinding_policy)
        observed.capture(Path(scientific_autonomy.__file__).absolute())
        observed.finish()
        result = scientific_autonomy.record_checkin1_delegation(child,
            user_text={k:user_text[k] for k in ('path', 'sha256')}, quote=quote,
            delegate_actor=delegate_actor, actions=deepcopy(actions), bounds=deepcopy(bounds),
            task_class=task_class, blinding_policy=({k:blinding_policy[k] for k in ('path','sha256')}
                                                  if blinding_policy is not None else None))
        # Check the producer's detached semantic result against exact serialized
        # intended declaration/message/transition bytes, not arbitrary first hashes.
        declaration = result['delegation']; value = declaration['value']
        raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        declaration_pin = {'path': declaration['declaration_path'],
                           'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        observed.file(declaration_pin)
        response_raw = observed.file(user_text)[0]
        observed.file({'path': declaration['user_text_path'], 'sha256': hashlib.sha256(response_raw).hexdigest(), 'size':len(response_raw)})
        transition = {'schema_version':1, 'kind':'checkin1_delegation_transition',
            'objective_sha256':scientific_autonomy.objective(plan),
            'declaration':{k:declaration_pin[k] for k in ('path','sha256')}, 'source_binding':value['source_binding']}
        transition_raw=(json.dumps(transition,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
        transition_pin={'path':str(child / scientific_autonomy.TRANSITION),
            'sha256':hashlib.sha256(transition_raw).hexdigest(),'size':len(transition_raw)}
        observed.file(transition_pin)
        science.verify_plan(child)
        if (child / science.APPROVAL).exists():raise ValueError('no approval may be manufactured by the response producer')
        observed.finish()
        return {'child_root':str(child), 'transition':transition_pin, 'delegation':deepcopy(result),
                'decision_api':'ravel.workflow.science.approve_delegated',
                'execution_authorized':False, 'parent_task_accepted':False}
    finally: observed.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--parent', required=True); prepare_parser.add_argument('--out', required=True)
    prepare_parser.add_argument('--modes', nargs='+', required=True); prepare_parser.add_argument('--evidence', required=True)
    prepare_parser.add_argument('--resources', required=True); prepare_parser.add_argument('--source-root')
    graph = sub.add_parser('graph-spec')
    graph.add_argument('--request', required=True); graph.add_argument('--graph-root', required=True); graph.add_argument('--out', required=True)
    graph.add_argument('--graph-id', required=True); graph.add_argument('--model', required=True); graph.add_argument('--effort', required=True)
    graph.add_argument('--adapter', default='responses')
    response = sub.add_parser('checkin1-response')
    response.add_argument('--delivery', required=True); response.add_argument('--request', required=True)
    args = parser.parse_args(argv)
    observed = _Inputs(Path.cwd())
    try:
        if args.operation == 'prepare':
            parent = observed.capture(Path(args.parent).absolute())
            ep, rp = observed.capture(Path(args.evidence).absolute()), observed.capture(Path(args.resources).absolute())
            value = prepare(parent, args.out, base_dir=Path.cwd(), candidate_modes=args.modes,
                evidence=observed.document(ep), resources=observed.document(rp), source_root=args.source_root)
        elif args.operation == 'graph-spec':
            request = observed.capture(Path(args.request).absolute())
            value = graph_spec(request, args.graph_root, args.out, base_dir=Path.cwd(), graph_id=args.graph_id,
                model=args.model, reasoning_effort=args.effort, adapter=args.adapter)
        else:
            delivery = observed.capture(Path(args.delivery).absolute())
            response_pin = observed.capture(Path(args.request).absolute())
            response = observed.document(response_pin)
            _keys(response, {'user_text','quote','delegate_actor','actions','bounds','task_class','blinding_policy'})
            value = record_checkin1_response(delivery, base_dir=Path.cwd(), **response)
        observed.finish(); print(json.dumps(value, indent=2, allow_nan=False)); return 0
    finally: observed.close()


if __name__ == '__main__':
    raise SystemExit(main())
