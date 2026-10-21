"""Preparation custody and scientific source closure meet at operation admission."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.controller.routes import study
from ravel.controller.routes.study import runtime
from ravel.controller.step import operations
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json
from test_p10_contracts import Store, _adopt, reading
from test_science_review_envelope import specification
from test_wms_adopt import workflow  # noqa: F401


@pytest.fixture
def prepared(tmp_path):
    return prepare(tmp_path, specification(tmp_path))


def prepare(tmp_path, supplied, *, root=None, preparer=None):
    root = root or tmp_path / 'parent'
    root.mkdir(exist_ok=True)
    source = tmp_path / 'specification.json'
    atomic_json(source, supplied)
    child = root / 'children' / 'ordinary'
    with runtime.capsule_runtime():
        extra = preparer(child) if preparer else {}
        if preparer is None:
            science.plan(child, source)
    store = Store(root=root / 'store')
    template = json.loads((study.DATA / 'controller/routes/study.json').read_text())
    plan = {'route': {'id': 'study'}, 'parameters': {}, 'steps': deepcopy(template['steps']),
            'deliverables': deepcopy(reading()['deliverables']), 'open_obligations': []}
    context = {'store': store, 'run_dir': str(root), 'plan': plan, 'reading': reading(),
               'contract': {'task_mode': 'supplied_events'}}
    _adopt(store, root, study.SPEC_ARTIFACT, supplied)
    _adopt(store, root, study.SCOPE_ARTIFACT, {'schema_version': 1, 'kind': 'study-scope',
        'deliverables': ['quantity', 'new_sample'], 'stages': [], 'child_rundir': 'children/ordinary'})
    ordinary = {'kind': 'science', 'child_rundir': 'children/ordinary',
                'plan_sha256': hashlib.sha256((child / science.PLAN).read_bytes()).hexdigest(),
                'specification_sha256': hashlib.sha256((child / science.SPEC).read_bytes()).hexdigest()}
    _adopt(store, root, 'prepare-child:outputs/preparation.json',
           {'kind': 'ordinary-study-preparation', 'ordinary': ordinary, **extra})
    for row in store.rows:
        row['record']['kind'] = 'document'
    context['plan'] = study.bind(plan, context)
    step = next(row for row in context['plan']['steps'] if row['id'] == 'operate')
    custody = [deepcopy(row['record']) for row in store.rows]
    return context, step, custody, child, tmp_path / 'events.json'


def admit(prepared, *, step=None, custody=None):
    context, approved, records, *_ = prepared
    return operations.admission_errors(step or approved, approved=approved,
                                      inputs_custody=records if custody is None else custody, context=context)


def test_source_bound_preparation_documents_reach_common_admission(prepared):
    context, step, records, child, source = prepared
    with runtime.capsule_runtime():
        assert source.is_file() and science.verify_plan(child, approved=False)
    assert admit(prepared) == []
    assert not (child / science.APPROVAL).exists()
    assert not context['store'].scan('authority')
    assert all(row['kind'] == 'document' for row in records)
    native = {key: context[key] for key in ('store', 'run_dir', 'plan')}
    assert operations.admission_errors(step, approved=step, inputs_custody=records, context=native) == []


@pytest.mark.parametrize('change', ['operand', 'plan', 'specification', 'preparation', 'task', 'control-kind'])
def test_changed_source_or_control_binding_refuses(prepared, change):
    context, step, records, child, source = prepared
    changed = deepcopy(step)
    if change == 'operand':
        source.write_text('{"weight": 2}')
    elif change in ('plan', 'specification'):
        target = child / (science.PLAN if change == 'plan' else science.SPEC)
        target.write_text('{}')
    elif change == 'preparation':
        value = deepcopy(records[-1])
        value['sha256'] = '0' * 64
        context['store'].append('custody', value)
    elif change == 'task':
        changed['parameters']['task']['config']['target_ctau']['value'] = 7
    else:
        records[0]['kind'] = 'model'
    errors = admit(prepared, step=changed)
    assert any(error['code'] == 'operation_input_binding_invalid' for error in errors), errors


def test_foreign_document_remains_an_operation_input(prepared):
    records = prepared[2] + [{'artifact': 'other:outputs/value.json', 'kind': 'document'}]
    errors = admit(prepared, custody=records)
    assert errors == [{'code': 'operation_artifact_undeclared', 'direction': 'input',
                       'artifact': 'other:outputs/value.json', 'kind': 'document',
                       'declared': ['model', 'parameter_point']}]


def test_matching_kind_from_another_source_refuses(prepared):
    context, _, records, _, source = prepared
    copy = Path(context['run_dir']) / 'inputs/foreign.json'
    copy.parent.mkdir(exist_ok=True)
    copy.write_bytes(source.read_bytes())
    foreign = {'artifact': 'other:outputs/source.json', 'destination': 'inputs/foreign.json',
               'sha256': hashlib.sha256(copy.read_bytes()).hexdigest(), 'kind': 'model', 'status': 'accepted'}
    errors = admit(prepared, custody=[*records, foreign])
    assert any(error['code'] == 'operation_input_binding_invalid' for error in errors), errors


def test_unbound_caller_retains_the_complete_kind_gate(prepared):
    _, step, records, *_ = prepared
    errors = operations.admission_errors(step, inputs_custody=records, approved=step)
    assert len(errors) == 3 and all(error['code'] == 'operation_artifact_undeclared' for error in errors)


def test_preparation_operation_keeps_its_document_inputs(prepared):
    context, _, records, *_ = prepared
    step = next(row for row in context['plan']['steps'] if row['id'] == 'prepare-child')
    assert operations.admission_errors(step, approved=step, inputs_custody=records[:2], context=context) == []


@pytest.fixture
def model_study(tmp_path, monkeypatch):
    from test_model_authoring import fake_feynrules, zprime
    from test_science_capability_integration import specification as study_specification
    monkeypatch.setenv('FEYNRULES_ROOT', str(fake_feynrules(tmp_path)))
    model = tmp_path / 'parent/steps/model-source/outputs/model.json'
    model.parent.mkdir(parents=True)
    atomic_json(model, zprime())
    request = tmp_path / 'request.json'
    atomic_json(request, {'schema_version': 1, 'spec': {
        'path': str(model), 'sha256': hashlib.sha256(model.read_bytes()).hexdigest()}})
    supplied = study_specification('model-authoring', {'request': request.name})
    return prepare(tmp_path, supplied), model, request, supplied


def test_request_envelope_and_scientific_specification_share_source_custody(model_study):
    prepared, model, request, supplied = model_study
    from ravel.physics import model_authoring
    signature = operations.signatures()['model-authoring']
    assert model_authoring.validate(supplied['task']) == supplied['task']
    assert operations.pointer(supplied, signature['consumes'][0]['task_pointer']) == request.name
    assert admit(prepared) == []
    assert model in science.task_inputs(supplied, request.parent)
    with pytest.raises(ValueError):
        model_authoring.validate({**supplied['task'], 'spec': model.name})


def test_request_location_is_a_critical_approved_field(model_study):
    prepared, _, _, _ = model_study
    step = prepared[1]
    changed = deepcopy(step)
    changed['parameters']['task']['request'] = 'another-request.json'
    errors = operations.admission_errors(changed, approved=step)
    assert any(error['code'] == 'operation_critical_field_changed' for error in errors), errors


def test_scientific_custody_matches_the_actual_adopted_operand(model_study):
    prepared, model, _, _ = model_study
    context, step, records, *_ = prepared
    artifact = 'model-source:outputs/model.json'
    row = {'artifact': artifact, 'destination': str(model.relative_to(Path(context['run_dir']))),
           'sha256': hashlib.sha256(model.read_bytes()).hexdigest(), 'kind': 'expression', 'status': 'accepted'}
    step['inputs'].append({'artifact': artifact, 'kind': 'expression', 'sha256': row['sha256']})
    step['depends_on'].append('model-source')
    assert admit(prepared, custody=[*records, row]) == []
    assert any(error['code'] == 'operation_input_binding_invalid' for error in admit(
        prepared, custody=[*records, {**row, 'sha256': '0' * 64}]))


@pytest.mark.parametrize('changed', ['model', 'request'])
def test_model_operand_and_request_mutations_refuse(model_study, changed):
    prepared, model, request, _ = model_study
    (model if changed == 'model' else request).write_text('{}')
    assert any(error['code'] == 'operation_input_binding_invalid' for error in admit(prepared))


@pytest.fixture
def adopted_workflow(tmp_path, workflow):
    from test_wms_adopt import study as workflow_study
    from ravel.workflow import wms_adopt
    document = workflow_study()
    supplied = {'schema_version': 2, 'mode': wms_adopt.MODE, 'max_attempts': 1,
                **document, 'task': {'schema_version': 1, 'operation': 'run',
                    'snakefile': 'wf/Snakefile', 'targets': ['final.txt'], 'cores': 1}}
    def preparer(child):
        return wms_adopt.prepare_governed(supplied['task'], document, base=workflow['base'],
            child=child, workflow_root=workflow['base'] / 'children/workflow', snakemake=workflow['snakemake'])
    return prepare(tmp_path, supplied, root=workflow['base'], preparer=preparer)


def test_adopted_workflow_source_maps_to_its_prepared_ordinary_contract(adopted_workflow):
    assert admit(adopted_workflow) == []
    assert not (adopted_workflow[3] / science.APPROVAL).exists()


@pytest.mark.parametrize('damage', ['targets', 'cores', 'snakefile', 'adoption', 'source'])
def test_changed_workflow_preparation_or_source_refuses(adopted_workflow, damage):
    from ravel.workflow import wms_adopt
    context, step, records, child, _ = adopted_workflow
    source = json.loads((child / science.SPEC).read_text())
    prepared = json.loads((Path(context['run_dir']) / records[-1]['destination']).read_text())
    original, _ = study.adopted_json(context, study.SPEC_ARTIFACT)
    verifier = wms_adopt.verify_prepared_specification
    if damage == 'snakefile':
        (Path(context['run_dir']) / 'another').write_bytes(
            (Path(context['run_dir']) / original['task']['snakefile']).read_bytes())
    if damage in ('targets', 'cores', 'snakefile'):
        original['task'][damage] = {'targets': ['other.txt'], 'cores': 2, 'snakefile': 'another'}[damage]
    elif damage == 'adoption':
        prepared['adoption']['sha256'] = '0' * 64
    else:
        (Path(context['run_dir']) / original['task']['snakefile']).write_text('changed')
    with pytest.raises(ValueError):
        verifier(original, source, base=Path(context['run_dir']), preparation=prepared)
