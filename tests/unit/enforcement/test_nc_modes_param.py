"""Science-mode rows: a mode named by vocabulary alone is never admitted as an operation (MODE).

One row per science mode of the package data (``mode_descriptors.json``). A descriptor is a suggestion
vocabulary: it grants nothing. A mode runs only as the operation its registered signature names
(``operation_signatures.json``, implementation kind ``science-mode`` and ``mode`` equal to the row's mode),
only through the production role the executors table registers for it, and, for the modes the ML and
manuscript admission governs, only with a current plan authority and a delivery contract.

The adversary is a plan step that names the mode by its vocabulary (the mode id, the descriptor's text, its
operation, tool and context words) without the mode's operation; the mode's operation under another role; and
the mode's operation with an artifact kind or an effect its signature does not declare. For the governed modes
the adversary also withholds the authority record, the delivery contract, the typed adapter or the registered
executor. Oracles are written here from the package data and the row's specification, never from the admission
or executor check itself; each positive control is the step made to conform and passes the same entry.

Where the descriptor lists no operation (a context-only descriptor), no step can name an operation from it:
every word the descriptor offers that is not a registered operation is refused as an unregistered operation,
and a derive step that only carries the descriptor text records no operation, executor or mode evaluation.
The cases are bound to CONTROLLER and end with the declared ``pending-integration:`` skip while
``ravel.controller`` is not installed.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import hashlib
import sys

import pytest

from nc_cases import CONTROLLER, dimension_case, dimension_rows, require_controller
from nc_controller import checkin_view, controller_run, store_root
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register, returns

FICTIONAL_KIND = 'undeclared-fixture-kind'
FICTIONAL_EFFECT = 'undeclared_fixture_effect'
CEILING = 10  # the cost ceiling every pointer resolves to in the conforming step, in the signature's own unit
WITHIN = 5
PLAN_DIGEST = 'a' * 64
# The modes whose admission is governed (the ML modes and the manuscript mode): the row's specification names them.
GOVERNED_MODES = ('ml-training', 'published-classifier', 'classifier-inputs', 'analysis-response-features',
                  'manuscript-build')
INFERENCE_MODES = ('published-classifier', 'classifier-inputs', 'analysis-response-features')
# The four parts of the governed contract: adapter, executor, authority, delivery.
PART_CODES = {'mode_signature_missing', 'mode_adapter_untyped', 'mode_adapter_missing', 'mode_not_registered',
              'mode_task_mismatch', 'mode_executor_missing', 'mode_executor_mismatch', 'mode_authority_unavailable',
              'mode_authority_missing', 'mode_outputs_undeclared', 'mode_delivery_contract_missing'}


def _name(function, row):
    """The mutation-adequacy identifier of one parameterized row of ``function``."""
    return f'{function.__name__}[{row}]'


def _package_json(*parts):
    from ravel.paths import package_data_path
    return json.loads(package_data_path(*parts).read_text())


def _set(document, pointer, value):
    parts = pointer.lstrip('/').split('/')
    for part in parts[:-1]:
        document = document.setdefault(part, {})
    document[parts[-1]] = value


def _codes(errors):
    return [error['code'] for error in errors]


def _step(step_id, kind='operate', *, role=None, operation=None, outputs=None, parameters=None, depends_on=(),
          graph=None):
    step = {'id': step_id, 'kind': kind, 'role': role, 'inputs': [], 'depends_on': list(depends_on),
            'outputs': outputs if outputs is not None
            else [{'path': f'outputs/{step_id}.out', 'kind': 'result', 'required': True}],
            'waypoint': False, 'rung': None, 'budget': {}, 'protocols': [], 'review': [], 'instruction_sources': [],
            'obligations': [], 'parameters': parameters if parameters is not None else {}}
    if operation is not None:
        step['operation'] = operation
    if graph is not None:
        step['graph'] = graph
    return step


def _conforming(step_id, mode, name, signature, role):
    """The step the signature and the executors table admit for the mode's operation."""
    task = {'mode': mode}
    for field in signature['critical_fields']:
        _set(task, field, 'approved')
    parameters = {'task': task, 'effects': list(signature['effects'])}
    pointer = signature['cost']['ceiling_pointer']
    if pointer:
        _set(task, pointer, CEILING)
        parameters['cost'] = {'unit': signature['cost']['unit'], 'amount': WITHIN}
    outputs = [{'path': f'outputs/{step_id}.out', 'kind': signature['produces'][0]['kind'], 'required': True}]
    return _step(step_id, 'operate', role=role, operation=name, outputs=outputs, parameters=parameters)


def _plan_record(store, steps, *, deliverable_step):
    """The approved plan in the store, as the controller pins it at CHECK-IN 1."""
    body = {'kind': 'fictional-plan', 'route': {'id': 'judgment'}, 'steps': deepcopy(steps),
            'deliverables': [{'id': 'd1', 'status': 'mapped', 'step': deliverable_step['id'],
                              'output': deliverable_step['outputs'][0]['path']}]}
    sha = require_controller('step.services').digest(body)  # the controller's canonical plan digest
    blob = store.put_blob(json.dumps(dict(body, sha256=sha), sort_keys=True).encode())
    store.append('plan', {'schema_version': 1, 'plan_sha256': sha, 'blob': blob})
    # As the controller binds a plan: its obligations are materialised and each step's plan-bind rows are
    # recorded from their checks, which the governed step verifies before it dispatches the step.
    # A step whose operation is prose longer than any identifier the ledger can name is never bound by a
    # controller; it has no ledger population and the step's own operation admission refuses it at preflight.
    ledger, binding = require_controller('ledger', 'step.binding')
    bound = dict(body, sha256=sha, steps=[s for s in body['steps'] if not isinstance(s.get('operation'), str)
                                          or len(s['operation']) <= 200])
    ledger.materialise(store, 'intake', {'run_id': store.run_id, 'task_mode': 'calculation', 'route': 'judgment'})
    ledger.materialise(store, 'plan', {'plan': bound})
    binding.record_plan_rows(store, bound, contract_sha256=None, ledger=ledger)
    return sha


def _vocabulary(descriptor):
    """Every word a descriptor offers (not its pattern entries), in the order it lists them."""
    words = [descriptor['summary']]
    for field in ('operations', 'tools', 'inputs', 'observables', 'outputs', 'context'):
        words += [word for word in descriptor.get(field) or () if type(word) is str and not word.startswith('re:')]
    return words


# ---------------------------------------------------------------- MODE: vocabulary grants nothing

@dimension_case('MODE', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('MODE'), ids=str)
def test_mode_named_by_vocabulary_without_its_adapter_executor_authority_or_delivery_is_not_admitted(nc, row):
    operations, graph, services, modes_module, ml = require_controller(
        'step.operations', 'step.graph', 'step.services', 'routes.ml.modes', 'routes.ml')
    from ravel.workflow import role_registry
    mode = row.removeprefix('MODE-')

    # Oracle, from the package data: the descriptor, the one science-mode signature of this mode, its executor.
    descriptor = _package_json('mode_descriptors.json')['modes'][mode]
    table = _package_json('operation_signatures.json')['operations']
    owners = sorted(n for n, s in table.items()
                    if s['implementation']['kind'] == 'science-mode' and s['implementation']['mode'] == mode)
    assert len(owners) == 1, f'{mode} has {len(owners)} science-mode signatures: {owners}'
    name = owners[0]
    signature = table[name]
    required = _package_json('roles', 'executors.json')['operations'][name]
    roles = sorted(card['id'] for card in role_registry.all_cards())
    assert required in roles, f'{name} names a production role the registry does not hold'
    module = signature['implementation']['module']
    assert importlib.util.find_spec(module) is not None, f'{mode} names an adapter module that is not installed'
    wrong = next(role for role in roles if role != required)

    # ---- the steps of one governed plan: the conforming one and each attack
    summary = descriptor['summary']
    vocabulary = [word for word in _vocabulary(descriptor) if word not in table]
    assert vocabulary, f'{mode}: the descriptor offers no word outside the registered operations'
    good = _conforming('s01', mode, name, signature, required)
    prose = _step('s02', 'derive', role=wrong, parameters={'mode': mode, 'descriptor': summary, 'task': {'mode': mode}})
    spoken = _step('s03', 'operate', role=required, operation=vocabulary[0], parameters={'task': {'mode': mode}})
    named = _step('s04', 'operate', role=required, operation=f'{mode}-by-descriptor',
                  parameters={'task': {'mode': mode}})
    other_role = _conforming('s05', mode, name, signature, wrong)
    undeclared_kind = deepcopy(_conforming('s06', mode, name, signature, required))
    undeclared_kind['outputs'].append({'path': 'outputs/extra.out', 'kind': FICTIONAL_KIND, 'required': True})
    undeclared_effect = _conforming('s07', mode, name, signature, required)
    undeclared_effect['parameters']['effects'] = [*signature['effects'], FICTIONAL_EFFECT]
    steps = [good, prose, spoken, named, other_role, undeclared_kind, undeclared_effect]

    # ---- direct entries
    # Positive control: the conforming step is admitted, and its registered executor runs it.
    assert operations.admission_errors(good, approved=deepcopy(good)) == [], (mode, name)
    assert operations.executor_errors(good) == [], (mode, name)
    # (a) Vocabulary only: no word of the descriptor, and no name derived from the mode id, is a registered
    # operation, so nothing admits it and no executor is found. The descriptor alone grants nothing.
    for word in [*vocabulary, f'{mode}-by-descriptor']:
        step = _step('s90', 'operate', role=required, operation=word)
        assert _codes(operations.admission_errors(step)) == ['operation_unregistered'], (mode, word)
        assert _codes(operations.executor_errors(step)) == ['operation_unregistered'], (mode, word)
    # (b) The mode's operation under any other registered role, or no role, is refused with the role it needs.
    for named_role in [*(role for role in roles if role != required), None]:
        errors = operations.executor_errors(_step('s91', 'operate', role=named_role, operation=name))
        assert [(e['code'], e['operation'], e['required'], e['named']) for e in errors] == [
            ('executor_role_mismatch', name, required, named_role)], (mode, named_role, errors)
    # (c) An output kind or an effect the signature does not declare is refused; the declared ones are not.
    errors = operations.admission_errors(undeclared_kind, approved=deepcopy(undeclared_kind))
    assert _codes(errors) == ['operation_artifact_undeclared'], (mode, errors)
    assert (errors[0]['direction'], errors[0]['kind']) == ('output', FICTIONAL_KIND), errors
    errors = operations.admission_errors(undeclared_effect, approved=deepcopy(undeclared_effect))
    assert _codes(errors) == ['operation_effect_undeclared'] and errors[0]['effects'] == [FICTIONAL_EFFECT], errors
    if signature['consumes']:
        foreign = [{'artifact': 's00:outputs/x.out', 'kind': FICTIONAL_KIND}]
        errors = operations.admission_errors(good, inputs_custody=foreign, approved=deepcopy(good))
        assert _codes(errors) == ['operation_artifact_undeclared'], (mode, errors)
        assert (errors[0]['direction'], errors[0]['kind']) == ('input', FICTIONAL_KIND), errors
        consumed = [{'artifact': 's00:outputs/x.out', 'kind': signature['consumes'][0]['kind']}]
        assert operations.admission_errors(good, inputs_custody=consumed, approved=deepcopy(good)) == []

    # ---- the mode contract entries, generic over modes: typed adapter and registered executor
    assert modes_module.adapter_errors(good, mode, table=table) == [], mode
    assert modes_module.executor_errors(good, mode) == [], mode
    errors = modes_module.adapter_errors(good, mode, table={k: v for k, v in table.items() if k != mode})
    assert _codes(errors) == ['mode_signature_missing'], (mode, errors)
    untyped = deepcopy(table)
    untyped[mode]['implementation'] = {'kind': 'command', 'module': module}
    assert _codes(modes_module.adapter_errors(good, mode, table=untyped)) == ['mode_adapter_untyped'], mode
    absent = deepcopy(table)
    absent[mode]['implementation']['module'] = 'ravel.physics.fixture_module_that_is_not_installed'
    assert _codes(modes_module.adapter_errors(good, mode, table=absent)) == ['mode_adapter_missing'], mode
    assert _codes(modes_module.adapter_errors(good, mode, table=table, modes=())) == ['mode_not_registered'], mode
    foreign_task = deepcopy(good)
    foreign_task['parameters']['task']['mode'] = 'another-fixture-mode'
    assert _codes(modes_module.adapter_errors(foreign_task, mode, table=table)) == ['mode_task_mismatch'], mode
    executor_errors = modes_module.executor_errors(other_role, mode)
    assert [(e['code'], e['required'], e['named']) for e in executor_errors] == [
        ('mode_executor_mismatch', required, wrong)], (mode, executor_errors)
    unmapped = {'operations': {k: v for k, v in _package_json('roles', 'executors.json')['operations'].items()
                               if k != mode}}
    assert _codes(modes_module.executor_errors(good, mode, table=unmapped)) == ['mode_executor_missing'], mode

    # ---- the governed step, over the run store: preflight evaluates MODE only for an admitted operation
    runtime_good = good
    precursors = []
    if mode == 'manuscript-build':
        author = _step('p00', 'author', role=required,
                       outputs=[{'path': 'outputs/claims.json', 'kind': 'manuscript:claim-map', 'required': True}])
        build = _step('p01', 'subgraph', role=required, graph={'id': 'manuscript.build'}, depends_on=['p00'])
        good['depends_on'] = ['p01']
        precursors = [author, build]
    elif mode == 'ml-training':
        # The atomic signature is structurally valid but runtime training is staged.
        # The extended study provider is unavailable; admit its dry first stage instead.
        from ravel.workflow import ml_stages
        source = _step('p00', 'author', role='ml-planner',
                       outputs=[{'path': 'outputs/ml_study_spec.json', 'kind': 'document', 'required': True}])
        runtime_good = _step('p01', role=required, operation='ml-stage-admit', depends_on=['p00'],
                            outputs=[{'path': path, 'kind': kind, 'required': True}
                                     for path, kind in ml_stages.OUTPUTS['admit']],
                            parameters={'task': {'mode': mode}, 'ml_stage': 'admit',
                                        'launch': {'argv': [sys.executable, '-I', '-m',
                                                            'ravel.workflow.ml_stages', 'admit',
                                                            '--input', 'spec=steps/p00/outputs/ml_study_spec.json']}})
        runtime_good['inputs'] = [{'artifact': 'p00:outputs/ml_study_spec.json', 'kind': 'document'}]
        precursors = [source]
        steps.append(runtime_good)
    store, run_dir = controller_run(nc, mode='autonomous')
    sha = _plan_record(store, [*precursors, *steps], deliverable_step=runtime_good)
    authority_service = require_controller('authority')
    approval = authority_service.request(store, 'approve_plan',
        {'view': checkin_view(store, 'approve_plan', plan_sha256=sha)}, {'rung': 'full'})
    assert approval.get('decision') == 'approve', approval
    for precursor in precursors:
        store.append('step-outcome', {'step_id': precursor['id'], 'attempt': 1, 'status': 'completed'})
    if mode == 'ml-training':
        # Reuse a validated fictional specification; custody attests these exact bytes.
        spec_path = Path(__file__).parents[1] / 'controller' / 'p17_support.py'
        fixture_spec = importlib.util.spec_from_file_location('_mode_stage_fixture', spec_path)
        fixture_module = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture_module)
        raw = json.dumps(ml_stages.validate_spec(fixture_module.spec()), sort_keys=True).encode()
        destination = 'steps/p00/outputs/ml_study_spec.json'
        target = run_dir / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        store.append('custody', {'artifact': 'p00:outputs/ml_study_spec.json', 'step_id': 'p00',
                                'path': 'outputs/ml_study_spec.json', 'kind': 'document',
                                'destination': destination, 'status': 'accepted',
                                'sha256': hashlib.sha256(raw).hexdigest()})
    context = {'run_id': store.run_id, 'store_root': str(store_root(nc)), 'run_dir': str(run_dir), 'attempt': 1,
               'plan_sha256': sha}

    def preflight(step):
        return graph.preflight({'context': context, 'step': step, 'acting': step, 'branch': 'parent', 'results': {}})

    def refused(step, *reasons):
        try:
            returned = preflight(step)
        except services.StepHold as exc:
            assert exc.reason in reasons, (mode, step['id'], exc.reason, reasons)
            return
        raise AssertionError(f'{mode}: step {step["id"]} was admitted by preflight: {str(returned)[:300]}')

    if mode == 'ml-training':
        refused(good, 'ml_training_atomic_refused')
    admitted = preflight(runtime_good)['evaluations']
    runtime_name = runtime_good['operation']
    if mode != 'ml-training':
        assert admitted[f'MODE-{mode}']['status'] == 'satisfied', admitted
    assert admitted[f'TOOL-{runtime_name}']['status'] == 'satisfied'
    assert admitted[f'EXEC-{runtime_name}']['evidence']['role'] == required, admitted
    prose_evaluations = preflight(prose)['evaluations']
    assert not [key for key in prose_evaluations if key.startswith(('MODE-', 'TOOL-', 'EXEC-'))] and \
        'R13' not in prose_evaluations, ('a step that only carries the mode text is evaluated as an operation',
                                         sorted(prose_evaluations))
    refused(spoken, 'operation_unregistered')
    refused(named, 'operation_unregistered')
    refused(other_role, 'executor_role_mismatch')
    refused(undeclared_kind, 'operation_artifact_undeclared')
    refused(undeclared_effect, 'operation_effect_undeclared')

    # ---- (d) the governed modes: authority record and delivery contract (CHECK-IN 1 covers the plan digest)
    step_not_governed = prose
    assert ml.governed(step_not_governed) is None, 'a step that only carries the mode text is a governed mode'
    if mode not in GOVERNED_MODES:
        # Only the signature and the executor admit the other modes; the mode admission leaves them alone.
        assert ml.governed(good) is None, mode
        assert ml.admit(good, plan={'sha256': PLAN_DIGEST, 'steps': [good]}) == [], mode
        return

    def authority(kind, pins):
        assert pins['plan_sha256'] == PLAN_DIGEST, pins
        return {'kind': kind, 'pins': pins}

    def admit_plan(step, plan_steps, *, route='ml.training', deliverable=True, **kwargs):
        plan = {'sha256': PLAN_DIGEST, 'route': {'id': route}, 'steps': plan_steps,
                'deliverables': [{'id': 'd1', 'status': 'mapped', 'step': step['id']}] if deliverable else []}
        return ml.admit(step, plan=plan, **kwargs)

    if mode == 'ml-training':
        # Training runs as the ml.study subgraph with the mode's role, its adapter, and its own authority.
        governed_step = _step('g01', 'subgraph', role=required, graph={'id': 'ml.study'},
                              parameters={'task': {'mode': mode}})
        context_steps = [governed_step]
        extra = {'prerequisites': []}
    elif mode == 'manuscript-build':
        author = _step('g00', 'author', role=required, outputs=[{'path': 'outputs/g00.map', 'kind': 'manuscript:claim-map',
                                                                'required': True}])
        build = _step('g01', 'subgraph', role=required, graph={'id': 'manuscript.build'}, depends_on=['g00'])
        governed_step = _conforming('g02', mode, name, signature, required)
        governed_step['depends_on'] = ['g01']
        context_steps = [author, build, governed_step]
        extra = {}
    else:
        governed_step = _conforming('g01', mode, name, signature, required)
        context_steps = [governed_step]
        extra = {}

    assert ml.governed(governed_step) == mode, mode
    # Positive control: all four parts present -> admitted, through the same entry as the attacks.
    assert admit_plan(governed_step, context_steps, authority=authority, **extra) == [], mode

    def only_part(errors):
        return [code for code in _codes(errors) if code in PART_CODES or code.startswith('ml_training_authority')]

    # No authority service, no record for the plan digest, and an authority that fails never admit.
    assert 'mode_authority_unavailable' in _codes(admit_plan(governed_step, context_steps, **extra)), mode
    errors = admit_plan(governed_step, context_steps, authority=lambda kind, pins: None, **extra)
    assert 'mode_authority_missing' in _codes(errors), (mode, errors)

    def failing(kind, pins):
        raise RuntimeError('the authority service is down')

    errors = admit_plan(governed_step, context_steps, authority=failing, **extra)
    assert 'mode_authority_unavailable' in _codes(errors), (mode, errors)
    if mode == 'ml-training':  # training also needs its own consequential-action authority beyond CHECK-IN 1
        only_plan = lambda kind, pins: authority(kind, pins) if kind == 'approve_plan' else None  # noqa: E731
        errors = admit_plan(governed_step, context_steps, authority=only_plan, **extra)
        assert only_part(errors) == ['ml_training_authority_missing'], (mode, errors)
    # No mapped deliverable produced by the step, or no required output declared: no delivery contract.
    errors = admit_plan(governed_step, context_steps, authority=authority, deliverable=False, **extra)
    assert only_part(errors) == ['mode_delivery_contract_missing'], (mode, errors)
    bare = deepcopy(governed_step)
    bare['outputs'] = [dict(output, required=False) for output in bare['outputs']]
    errors = admit_plan(bare, [bare if s['id'] == bare['id'] else s for s in context_steps], authority=authority,
                        **extra)
    assert only_part(errors) == ['mode_outputs_undeclared'], (mode, errors)
    # Another registered role runs the mode: refused with the registered one named.
    substitute = deepcopy(governed_step)
    substitute['role'] = wrong
    errors = admit_plan(substitute, [substitute if s['id'] == substitute['id'] else s for s in context_steps],
                        authority=authority, **extra)
    assert [(e['code'], e['required'], e['named']) for e in errors if e['code'] in PART_CODES] == [
        ('mode_executor_mismatch', required, wrong)], (mode, errors)
    # The typed adapter: no signature, an untyped one, an unregistered mode.
    errors = admit_plan(governed_step, context_steps, authority=authority,
                        signature_table={k: v for k, v in table.items() if k != mode}, **extra)
    assert only_part(errors) == ['mode_signature_missing'], (mode, errors)
    errors = admit_plan(governed_step, context_steps, authority=authority, modes=(), **extra)
    assert only_part(errors) == ['mode_not_registered'], (mode, errors)
    # A step that is not part of the plan is not admitted on the plan's authority.
    errors = ml.admit(governed_step, plan={'sha256': PLAN_DIGEST, 'steps': []}, authority=authority, **extra)
    assert _codes(errors) == ['mode_step_not_in_plan'], (mode, errors)


_CASE = test_mode_named_by_vocabulary_without_its_adapter_executor_authority_or_delivery_is_not_admitted
_ML_ADMIT = ('ravel.controller.routes.ml.modes:admit', 'ravel.controller.routes.ml:admit')

register(
    Mutation('M07', 'ravel.controller.step.operations:admission_errors', returns(lambda: []),
             (_name(_CASE, 'MODE-amplitude-crosscheck'), _name(_CASE, 'MODE-model-events')),
             binding=MUTATION_CONTROLLER,
             why='a step naming a mode is admitted whatever its signature declares'),
    Mutation('M06', 'ravel.controller.step.operations:executor_errors', returns(lambda: []),
             (_name(_CASE, 'MODE-amplitude-crosscheck'), _name(_CASE, 'MODE-model-events')),
             binding=MUTATION_CONTROLLER, why='any role, or none, runs a science-mode operation'),
    Mutation('M07', _ML_ADMIT, returns(lambda: []),
             (_name(_CASE, 'MODE-published-classifier'), _name(_CASE, 'MODE-ml-training')),
             binding=MUTATION_CONTROLLER, why='a governed mode is admitted without its four-part contract'),
    Mutation('M07', 'ravel.controller.routes.ml.modes:adapter_errors', returns(lambda: []),
             (_name(_CASE, 'MODE-classifier-inputs'), _name(_CASE, 'MODE-asimov-sensitivity')),
             binding=MUTATION_CONTROLLER, why='a mode is admitted without a typed, installed adapter'),
    Mutation('M06', 'ravel.controller.routes.ml.modes:executor_errors', returns(lambda: []),
             (_name(_CASE, 'MODE-analysis-response-features'), _name(_CASE, 'MODE-asimov-sensitivity')),
             binding=MUTATION_CONTROLLER, why='any role runs a governed mode'),
    Mutation('M04', 'ravel.controller.routes.ml.modes:authority_errors', returns(lambda: []),
             (_name(_CASE, 'MODE-published-classifier'), _name(_CASE, 'MODE-manuscript-build')),
             binding=MUTATION_CONTROLLER, why='a governed mode needs no current authority record'),
    Mutation('M10', 'ravel.controller.routes.ml.modes:delivery_errors', returns(lambda: []),
             (_name(_CASE, 'MODE-published-classifier'), _name(_CASE, 'MODE-manuscript-build')),
             binding=MUTATION_CONTROLLER, why='a governed mode needs no delivery contract'),
)
