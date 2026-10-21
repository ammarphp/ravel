"""Compile a scoped ordinary operation while retaining its original parent goal.

The parent contract and plan remain supplied, unresolved obligations. The child
proposes the actual approved-operation recipe, not the parent's figure, note or
research campaign. Its scientific review policy still owns result claims.
"""
from copy import deepcopy
from pathlib import Path
import shutil

from . import science, state_io, request_plan
from ravel.validation import validate_request_plan as vp


def _pointer(document, pointer):
    value = document
    for token in pointer.lstrip('/').split('/'):
        value = value[int(token)] if isinstance(value, list) else value[token.replace('~1', '/').replace('~0', '~')]
    return value


def compile_plan(state, experiment, rundir, original, parent_plan, reading, *, materialize=False):
    from . import research_cycle as cycle, derived_label
    rd = Path(rundir)
    def local_pin(source, identity, expected=None):
        source = cycle._ordinary(source).resolve(strict=True)
        pin = cycle._pin(source)
        if expected is not None and pin['sha256'] != expected:
            raise ValueError('scoped child original source pin changed: ' + identity)
        relative = Path('inputs/research-plan-sources') / (identity + '-' + source.name)
        target = cycle._ordinary(rd / relative)
        if materialize and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open('rb') as stream, target.open('xb') as destination:
                shutil.copyfileobj(stream, destination, 1024 * 1024)
        if (not target.is_file() or cycle._pin(target)['sha256'] != pin['sha256']
                or cycle._pin(source) != pin):
            raise ValueError('scoped child source copy is missing or changed: ' + identity)
        return {'path': relative.as_posix(), 'sha256': pin['sha256']}
    spec = deepcopy(state_io.read_json(rd / science.SPEC))
    proposal = state_io.read_json(rd / science.PLAN)
    if proposal['schema_version'] == 2:
        spec['task'] = deepcopy(proposal['execution_task'])
    science.validate(spec)
    registry = vp.registry()
    modes = [name for name, row in registry.items() if row and
             row['implementation'].get('kind') == 'science-mode' and
             row['implementation'].get('mode') == spec['mode']]
    operation = spec['mode'] if spec['mode'] in modes else modes[0] if len(modes) == 1 else None
    if operation is None:
        raise ValueError('scoped child has no unambiguous registered science operation: ' + spec['mode'])
    signature = registry[operation]
    binding = state['contract']['goal_binding']
    parent_path = Path(binding['contract']['path'])
    if not parent_path.is_absolute(): parent_path = Path(state['base_dir']) / parent_path
    parent_pin = local_pin(parent_path, 'I1', binding['contract']['sha256'])
    parent_root = parent_path.parent.parent if parent_path.parent.name == 'inputs' else parent_path.parent
    plan_pin = original['request_plan']
    parent_plan_pin = local_pin(parent_root / plan_pin['path'], 'I2', plan_pin['sha256'])
    inputs = [
        {'id': 'I1', 'provides': {'kind': 'ravel:unresolved-parent-obligations', 'require': {}},
         'source': 'owner_action', 'locator': 'Original parent obligations remain open outside this scoped operation.',
         'evidence': [], 'pin': parent_pin, 'status': 'supplied'},
        {'id': 'I2', 'provides': {'kind': 'ravel:parent-request-plan', 'require': {}},
         'source': 'owner_action', 'locator': 'Exact original parent request plan; no parent operation is re-admitted here.',
         'evidence': [], 'pin': parent_plan_pin, 'status': 'supplied'}]
    edges = []
    # Relative task inputs retain the source specification's base directory.
    # The v2 execution task already substitutes copied mutable inputs with their
    # absolute child paths; its other inputs still use this original base.
    input_base = Path(proposal['base_dir'])
    allowed = {path.resolve() for path in science.task_inputs(spec, input_base)}
    for port in signature['consumes']:
        pointer = port.get('task_pointer') or '/task/' + port['slot']
        # The released quantities adapter names its signed records `records`;
        # its operation signature names that event-sample port `events`.
        if spec['mode'] == 'quantities' and pointer == '/task/events' and 'events' not in spec['task']:
            pointer = '/task/records'
        try:
            values = _pointer(spec, pointer)
        except (KeyError, TypeError, IndexError):
            if port.get('optional') or port.get('cardinality', '').startswith('0..'):
                continue
            raise ValueError('scoped child cannot bind registered input ' + operation + ':' + port['slot']) from None
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, dict): value = value.get('path')
            if not isinstance(value, str):
                raise ValueError('scoped child input is not an attributable file: ' + pointer)
            path = Path(value)
            if not path.is_absolute(): path = input_base / path
            if path.resolve() not in allowed:
                raise ValueError('scoped child input is outside actual science dependency closure: ' + pointer)
            identity = 'I' + str(len(inputs) + 1)
            pin = local_pin(path, identity)
            inputs.append({'id': identity, 'provides': {'kind': port['kind'], 'require': deepcopy(port.get('require', {}))},
                'source': 'requester', 'locator': str(path), 'evidence': [],
                'pin': pin, 'status': 'supplied'})
            edges.append({'id': 'E' + str(len(edges) + 1), 'from': {'ref': identity, 'slot': 'artifact'},
                'to': {'ref': 'N1', 'slot': port['slot']}, 'kind': port['kind'], 'require': {},
                'resolution': 'compatible', 'converter': None, 'acceptance': 'execution_ledger'})
    fields = []
    for item in signature.get('critical_fields', []):
        pointer = item['pointer'] if isinstance(item, dict) else item
        try: value = _pointer(spec, pointer)
        except (KeyError, TypeError, IndexError):
            raise ValueError('scoped child has an unresolved registered critical field: ' + pointer) from None
        fields.append({'pointer': pointer, 'value': value, 'authority': 'supplied', 'evidence': None})
    def pin(path):
        value = cycle._pin(path)
        return {'path': Path(path).relative_to(rd).as_posix(), 'sha256': value['sha256']}
    node = {'id': 'N1', 'kind': 'operation', 'operation': operation,
        'implementation': 'science-mode', 'status': 'available', 'held_by': None,
        'covers': ['original-request'], 'fields': fields,
        'rung': 'full' if set(signature['effects']) & set(vp.COMPUTE_EFFECTS) else 'dry',
        'budget': {**deepcopy(request_plan.EMPTY_BUDGET), 'basis': 'ceiling', 'max_seconds': spec['max_seconds']},
        'placement': {'backend_plan': pin(rd / science.PLAN)}, 'fan_out': None,
        'spec_template': pin(rd / science.SPEC),
        'review': {'claim_scope': experiment['acceptance_scope'], 'actions': ['delivery', 'reuse']},
        'authored': None, 'request': None}
    obligations = original['task_requirements']['obligations']
    plan = {'schema_version': 1, 'kind': 'request-plan', 'prompt_sha256': parent_plan['prompt_sha256'],
        'reading': deepcopy(original['reading']), 'signatures': {'path': parent_plan['signatures']['path'],
            'entries': {operation: vp.entry_sha256(signature)}},
        'status': 'draft', 'authors': [deepcopy(request_plan.AUTHOR)],
        'inputs': inputs, 'nodes': [node], 'edges': edges, 'claims': [], 'waypoints': [],
        'boundaries': deepcopy(parent_plan['boundaries']),
        'coverage': [{'obligation_id': row['id'], 'by': ['N1', 'I1', 'I2'] if row['id'] == 'original-request'
                      else ['I1', 'I2']} for row in obligations],
        'aggregate_budget': {k: None for k in parent_plan['aggregate_budget']},
        'label': deepcopy(parent_plan['label'])}
    plan['label'] = derived_label.plan_label(reading, plan)
    request_plan._waypoints(plan, registry)
    errors = vp.check(reading, plan, reg=registry, obligations=obligations)
    if errors:
        raise ValueError('scoped science plan cannot preserve the parent contract: ' + '; '.join(row['reason'] for row in errors))
    return plan
