"""Inert scope, quantity and route controls; no scientific engine is launched."""
from copy import deepcopy
import importlib
import hashlib
import json
from pathlib import Path
from types import ModuleType

import pytest

from ravel.controller.routes import study
from ravel.controller.routes.study import contracts


class Store:
    """Local binding-interface fake while the shared controller store is absent."""
    def __init__(self, run_id='fictional', *, root=None):
        self.run_id = run_id
        self.root = Path(root or '.')
        self.rows = []

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
        record_id = str(len(self.rows) + 1)
        self.rows.append({'id': record_id, 'kind': kind, 'record': deepcopy(record)})
        return record_id

    def read(self, kind, record_id):
        return next(deepcopy(row) for row in self.rows if row['kind'] == kind and row['id'] == record_id)

    def scan(self, kind):
        return [deepcopy(row) for row in self.rows if row['kind'] == kind]

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def checkpointer(self):
        raise NotImplementedError('no graph execution in this inert fake')


def reading(stages=()):
    return {'deliverables': [{'id': 'quantity'}, {'id': 'new_sample'}],
            'constraints': [{'type': 'requested_stage', 'value': {'stage': stage}} for stage in stages]}


def plan():
    return {'route': {'id': 'study'}, 'parameters': {}, 'steps': [],
            'deliverables': [{'id': 'quantity', 'status': 'mapped'}, {'id': 'new_sample', 'status': 'mapped'}],
            'open_obligations': [{'id': 'prior', 'reason': 'original hold'}]}


def test_R02_supplied_component_keeps_uncovered_parent():
    whole = contracts.scope(reading(), ['quantity', 'new_sample'], [])
    assert whole == []
    bounded = contracts.bind_scope(plan(), reading(), ['quantity'], [])
    assert {row['id'] for row in bounded['open_obligations']} == {'prior', 'new_sample'}
    assert bounded['deliverables'][1]['status'] == 'open'
    assert bounded['sha256'] == contracts.digest({k: v for k, v in bounded.items() if k != 'sha256'})


def test_R04_each_chain_component_survives():
    source = {'deliverables': [{'id': 'diagram'}, {'id': 'amplitude'}, {'id': 'interference'}]}
    assert [r['id'] for r in contracts.scope(source, ['diagram', 'amplitude'], [])] == ['interference']
    assert contracts.scope(source, ['diagram', 'amplitude', 'interference'], []) == []


def test_R08_units_and_requested_statistic_are_required():
    expected = {'units': 'pb', 'statistic': 'declared quadratic form'}
    assert contracts.quantity_errors(expected, deepcopy(expected)) == []
    assert contracts.quantity_errors(expected, {'statistic': expected['statistic']}) == [
        'units changed or missing at the handoff']
    assert contracts.quantity_errors(expected, {'units': 'pb', 'statistic': 'different'}) == [
        'statistic changed or missing at the handoff']


def test_R09_scoped_generation_cannot_drop_detector_stage():
    source = reading(['generate', 'detector'])
    assert contracts.scope(source, ['quantity', 'new_sample'], ['generate'])[0]['id'] == 'stage:detector'
    assert contracts.scope(source, ['quantity', 'new_sample'], ['generate', 'detector']) == []


def test_P05_covariance_and_signed_basis_are_preserved():
    expected = {'basis': ['component_a', 'component_b'], 'covariance': [[1, -0.2], [-0.2, 2]],
                'sign_convention': 'signed interference', 'population': ['a', 'b']}
    assert contracts.quantity_errors(expected, deepcopy(expected)) == []
    actual = deepcopy(expected)
    actual.pop('covariance')
    actual['sign_convention'] = 'absolute interference'
    assert len(contracts.quantity_errors(expected, actual)) == 2


@pytest.mark.parametrize('row,field,value,changed', [
    ('E07', 'pdf_member', 4, 5), ('E08', 'invisible_states', [11, 12], [11]),
    ('E10', 'beam_energy', [7000, 7000], [6500, 6500]),
    ('E10', 'seed', 17, 18), ('E17', 'bin_ids', ['left', 'right'], ['right', 'left']),
    ('E18', 'perturbative_order', 'declared order', 'other order'),
    ('E18', 'process_basis', ['positive', 'negative'], ['positive'])], ids=lambda value: str(value))
def test_execution_evidence_rows(row, field, value, changed):
    expected = {field: value}
    assert contracts.execution_errors(expected, deepcopy(expected)) == []
    assert contracts.execution_errors(expected, {field: changed})
    assert contracts.execution_errors(expected, {})


def test_E13_single_weight_and_nonreentrant_merge():
    expected = {'single_weight': True, 'reentrant': False}
    assert contracts.execution_errors(expected, {'weight_names': ['nominal'], 'reentrant': False}) == []
    assert contracts.execution_errors(expected, {'weight_names': ['nominal', 'variation'], 'merged': True})


def test_scope_rejects_invented_duplicate_and_excluded_work():
    for covered in (['quantity', 'quantity'], ['invented']):
        with pytest.raises(ValueError):
            contracts.scope(reading(), covered, [])
    source = reading()
    source['constraints'] = [{'type': 'negated_stage', 'value': {'stage': 'detector'}}]
    with pytest.raises(ValueError, match='excluded'):
        contracts.scope(source, ['quantity'], ['detector'])


def test_pinned_json_rejects_changed_linked_and_nonfinite_bytes(tmp_path):
    root = tmp_path.resolve()
    path = root / 'record.json'
    raw = b'{"value":1}'
    path.write_bytes(raw)
    pin = {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest()}
    assert contracts.pinned_json(root, pin) == {'value': 1}
    path.write_bytes(b'{"value":2}')
    with pytest.raises(ValueError, match='digest'):
        contracts.pinned_json(root, pin)
    link = root / 'linked.json'
    link.symlink_to(path)
    with pytest.raises(OSError):
        contracts.pinned_json(root, {**pin, 'path': link.name})
    for raw in (b'{"value":NaN}', b'{"value":1e999}', b'{"value":1,"value":2}'):
        path.write_bytes(raw)
        with pytest.raises(ValueError):
            contracts.pinned_json(root, {'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest()})


def test_gate_fails_closed_without_adopted_binding(tmp_path):
    context = {'store': Store(root=tmp_path), 'run_dir': str(tmp_path), 'plan': plan(), 'reading': reading()}
    assert study.gate('approve_plan', context)[0]['code'] == 'study_not_bound'
    assert study.admit({'id': 'operate', 'parameters': {}}, context)
    assert study.admit({'id': 'specify', 'parameters': {'phase': 'prepare'}}, context) == []
    for transition in ('checkin1->execute', 'checkin2->execute[operate]', 'checkin3->deliver',
                       'deviation->execute[changed]'):
        assert study.gate(transition, context)[0]['code'] == 'study_not_bound'


DATA = Path(study.__file__).resolve().parents[3] / 'data'
MODES = sorted(json.loads((DATA / 'mode_descriptors.json').read_text())['modes'])


@pytest.mark.parametrize('mode', MODES, ids=lambda value: 'MODE-' + value)
def test_mode_vocabulary_is_not_typed_admission(mode):
    with pytest.raises((ValueError, TypeError, KeyError)):
        study.mode_admission({'mode': mode})


def test_mode_positive_requires_actual_typed_adapter_and_executor(monkeypatch):
    from ravel.workflow import science
    module = ModuleType('ravel.physics.fictional_study')
    def validate(task):
        if task != {'finite': True}:
            raise ValueError('complete fictional typed input required')
    module.validate = validate
    monkeypatch.setattr(science, 'MODES', (*science.MODES, 'fictional-study'))
    monkeypatch.setattr(science, 'adapter', lambda spec: module)
    signatures = {'fictional-study': {'implementation': {'kind': 'science-mode',
        'mode': 'fictional-study', 'module': module.__name__}}}
    executors = {'fictional-study': 'calculation'}
    monkeypatch.setattr(study, '_tables', lambda: (signatures, executors))
    spec = {'schema_version': 1, 'mode': 'fictional-study', 'source': 'fictional supplied source',
        'assumptions': ['Finite supplied control.'], 'max_seconds': 10, 'approval_mode': 'physicist',
        'task': {'finite': True}}
    assert study.mode_admission(spec)['role'] == 'calculation'
    with pytest.raises(ValueError, match='typed input'):
        study.mode_admission({**spec, 'task': {}})
    executors.clear()
    with pytest.raises(ValueError, match='production role'):
        study.mode_admission(spec)


@pytest.mark.parametrize('route', ['study', 'study_site', 'scoped', 'calculation', 'chain'])
def test_route_specs_have_ordered_prepare_execution_review_and_sink_contracts(route):
    spec = json.loads((DATA / 'controller/routes' / (route + '.json')).read_text())
    assert spec['adapter'] == 'study'
    known = set()
    for step in spec['steps']:
        assert set(step['depends_on']) <= known
        known.add(step['id'])
        assert step['instruction_sources']
        if step['parameters']['phase'] == 'prepare':
            assert step['rung'] in (None, 'none', 'dry')
    assert {row['id'] for row in spec['checkins']} == {'checkin1', 'checkin2', 'checkin3'}
    operation = next(row for row in spec['steps'] if row['id'] == 'operate')
    assert operation['review'] and operation['waypoint'] is False
    review = next(row for row in spec['steps'] if row['id'] == 'operation-review')
    assert review['kind'] == 'subgraph' and review['graph']['id'] == 'review.points'
    assert review['waypoint'] is True and 'operate' in review['depends_on']
    preparation = next(row for row in spec['steps'] if row['id'] == 'prepare-child')
    assert preparation['kind'] == 'operate' and preparation['operation'] == 'ordinary-study-prepare'
    assert preparation['rung'] == 'dry' and preparation['budget']['wall_seconds'] == 120
    assert preparation['parameters']['adapter'] == 'ravel.controller.routes.study.runtime'
    assert preparation['parameters']['action'] == 'prepare'
    assert operation['parameters']['requires_ordinary_child_authority']
    if route == 'chain':
        assert spec['deliverables'] == []  # stretch support returns to judgment with all components open
    if route == 'calculation':
        assert next(row for row in spec['steps'] if row['id'] == 'design')['graph']['id'] == 'intake.plan'


@pytest.mark.parametrize('name', ['cosmology-solvers', 'eft-conventions', 'sfitter'],
                         ids=lambda value: 'STEP-' + value)
def test_specialist_instructions_are_in_every_study_manifest_source(name):
    spec = json.loads((DATA / 'controller/routes/study.json').read_text())
    for step in spec['steps']:
        if step['id'] in ('specify', 'operate'):
            assert 'docs/workflow/steps/' + name + '.md' in step['instruction_sources']


@pytest.mark.parametrize('mode', ['generate', 'likelihood', 'calculation'],
                         ids=lambda value: 'ROUTE-' + value)
def test_route_dimensions_refuse_incomplete_child_before_ci1(mode, tmp_path):
    source = plan()
    source['route']['id'] = 'calculation' if mode == 'calculation' else 'scoped'
    context = {'store': Store(root=tmp_path), 'run_dir': str(tmp_path), 'plan': source, 'reading': reading()}
    assert study.gate('checkin1', context)


def test_request_parameters_preserve_original_units_statistics_and_facts():
    source = reading()
    source['constraints'].append({'type': 'prescribed_statistic', 'value': {'statistic': 'declared formula'}})
    contract = {'task_mode': 'calculation', 'prompt': 'Compute the supplied quantity in cm.'}
    bound = study.parameters({}, source, contract, [{'kind': 'table', 'path': 'inputs/table.json'}])
    assert bound['study_request']['reading'] == source
    assert bound['study_request']['contract'] == contract
    assert bound['study_request']['statistics'] == ['declared formula']


def _adopt(store, root, artifact, value):
    relative = 'steps/' + artifact.replace(':', '/')
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    store.append('custody', {'artifact': artifact, 'destination': relative,
                             'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'accepted'})


def test_binding_preserves_uncovered_scope_and_detects_changed_custody(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    store = Store(root=root / 'store')
    context = {'store': store, 'run_dir': str(root), 'plan': plan(), 'reading': reading(),
               'contract': {'task_mode': 'calculation'}}
    specification = {'schema_version': 2, 'mode': 'fictional-study', 'max_seconds': 10,
                     'max_attempts': 2, 'task': {'inputs': 'supplied'}}
    coverage = {'schema_version': 1, 'kind': 'study-scope', 'deliverables': ['quantity'],
                'stages': [], 'child_rundir': 'children/supplied'}
    _adopt(store, root, study.SPEC_ARTIFACT, specification)
    _adopt(store, root, study.SCOPE_ARTIFACT, coverage)
    monkeypatch.setattr(study, 'mode_admission', lambda spec: {
        'operation': 'fictional-study', 'role': 'calculation', 'signature': {'stages': [], 'produces': []}})
    context['plan']['steps'] = [{'id': 'operate', 'budget': {}, 'parameters': {}, 'instruction_sources': [],
                               'outputs': [{'path': 'outputs/result.json', 'kind': 'document', 'required': True}]}]
    rebound = study.bind(context['plan'], context)
    context['plan'] = rebound
    assert rebound['parameters']['study_binding']['max_attempts'] == 2
    assert rebound['steps'][0]['budget']['wall_seconds'] == 10
    assert any(r['obligation'] == 'new_sample' for r in study.gate('approve_plan', context))
    assert study.admit(rebound['steps'][0], context)
    # A newly adopted replacement changes the frozen plan binding; adoption
    # itself never grants renewed authority for the altered child.
    _adopt(store, root, study.SPEC_ARTIFACT, {**specification, 'max_seconds': 11})
    assert any(r['code'] == 'study_binding_changed' for r in study.gate('approve_plan', context))


class _CompilerBindingFake:
    """Static P01 interface fixture only; never installed as a production fallback.

    These five fixed templates have no parameter expansion. The fake checks
    closed step kinds, basic typed fields, DAG references and preservation of
    route duties. It grants no execution, review credit or compiler validation
    beyond these explicit source-shape checks.
    """
    @staticmethod
    def compile(route_spec, reading, contract):
        steps = deepcopy(route_spec['steps'])
        known = {}
        for step in steps:
            assert step['kind'] in ('acquire', 'operate', 'author', 'derive', 'compare', 'review',
                                    'synthesize', 'ask', 'decide', 'subgraph', 'route')
            assert isinstance(step['id'], str) and step['id'] not in known
            assert isinstance(step['depends_on'], list) and set(step['depends_on']) <= known.keys()
            assert type(step['waypoint']) is bool
            for field in ('inputs', 'outputs', 'review', 'instruction_sources', 'obligations'):
                assert isinstance(step[field], list)
            assert isinstance(step['budget'], dict) and isinstance(step['parameters'], dict)
            assert step['instruction_sources']
            for item in step['inputs']:
                producer, _, output = item['artifact'].partition(':')
                assert producer in known
                assert output in {row['path'] for row in known[producer]['outputs']}
                # The shared compiler requires a direct dependency on every producer read.
                assert producer in step['depends_on'], (step['id'], producer)
            known[step['id']] = step
        result = {'schema_version': 1, 'kind': 'controller-plan', 'revision': 0,
            'route': {'id': route_spec['id'], 'version': route_spec['version'],
                      'spec_sha256': contracts.digest(route_spec)},
            'parameters': study.parameters(route_spec, reading, contract, []), 'steps': steps,
            'deliverables': [{'id': row['id'], 'status': 'open'} for row in reading['deliverables']],
            'waypoints': [row['id'] for row in steps if row['waypoint']],
            'checkins': deepcopy(route_spec['checkins']), 'obligations': deepcopy(route_spec['obligations']),
            'open_obligations': [{'id': row['id'], 'reason': 'static fixture does not map scientific scope'}
                                 for row in reading['deliverables']],
            'instruction_sources': deepcopy(route_spec['instruction_sources']),
            'reading_sha256': contracts.digest(reading), 'contract_sha256': contracts.digest(contract)}
        result['sha256'] = contracts.digest(result)
        return result

    @staticmethod
    def conformance_errors(plan, spec):
        errors = []
        if plan['route']['id'] != spec['id'] or plan['route']['spec_sha256'] != contracts.digest(spec):
            errors.append('route identity changed')
        have = {row['id']: row for row in plan['checkins']}
        for required in spec['checkins']:
            if required['id'] not in have or any(
                    not set(required[field]) <= set(have[required['id']][field]) for field in ('sections', 'seats')):
                errors.append('route checkin changed')
        if not {row['id'] for row in spec['steps']} <= {row['id'] for row in plan['steps']}:
            errors.append('route step missing')
        if not set(spec['obligations']) <= set(plan['obligations']):
            errors.append('route duty missing')
        return errors


@pytest.mark.parametrize('route', ['study', 'study_site', 'scoped', 'calculation', 'chain'])
def test_shared_compiler_conformance_when_integrated(route):
    try:
        compiler = importlib.import_module('ravel.controller.routes.compiler')
    except ModuleNotFoundError as exc:
        if exc.name != 'ravel.controller.routes.compiler':
            raise
        compiler = _CompilerBindingFake
    spec = json.loads((DATA / 'controller/routes' / (route + '.json')).read_text())
    compiled = compiler.compile(spec, reading(), {'task_mode': 'calculation'})
    assert compiler.conformance_errors(compiled, spec) == []
    for field in ('steps', 'checkins', 'obligations'):
        changed = deepcopy(compiled)
        changed[field] = []
        assert compiler.conformance_errors(changed, spec)


def test_completed_process_with_only_scoped_approval_cannot_close_evidence(tmp_path, monkeypatch):
    from ravel.workflow import scoped
    monkeypatch.setattr(study, 'gate', lambda *args: [])
    monkeypatch.setattr(scoped, 'verify_plan', lambda *args, **kwargs: {})
    monkeypatch.setattr(scoped, 'evaluate', lambda *args: {'verdict': 'FAIL'})
    context = {'store': Store(root=tmp_path / 'store'), 'run_dir': str(tmp_path), 'contract': {}, 'plan': {'parameters': {'study_binding': {
        'mode': 'generate', 'child_rundir': 'children/generated'}}}}
    assert study.step({'id': 'operate'}, {'status': 'completed'}, context)
    monkeypatch.setattr(scoped, 'evaluate', lambda *args: {'verdict': 'PASS'})
    assert study.step({'id': 'operate'}, {'status': 'completed'}, context) == []


def _scoped_likelihood():
    return {'schema_version': 1, 'mode': 'likelihood', 'source': 'fictional supplied counting model',
            'assumptions': ['Finite fictional counting control.'], 'max_seconds': 10,
            'approval_mode': 'physicist', 'likelihood': {
                'counting': {'observed': 3, 'background': 2.5, 'background_uncertainty': 0.5, 'signal': 1.0},
                'poi_cap': 10, 'normalization': {'kind': 'signal_strength'}}}


def _scoped_context(root, stages, covered_stages):
    store = Store(root=root / 'store')
    context = {'store': store, 'run_dir': str(root), 'reading': reading(stages),
               'contract': {'task_mode': 'likelihood'},
               'plan': {'route': {'id': 'scoped'}, 'parameters': {}, 'open_obligations': [],
                        'deliverables': [{'id': 'quantity', 'status': 'mapped'},
                                         {'id': 'new_sample', 'status': 'mapped'}],
                        'steps': [{'id': 'operate', 'budget': {}, 'parameters': {}, 'instruction_sources': [],
                                   'outputs': [{'path': 'outputs/result.json', 'kind': 'document', 'required': True}]}]}}
    _adopt(store, root, study.SPEC_ARTIFACT, _scoped_likelihood())
    _adopt(store, root, study.SCOPE_ARTIFACT, {
        'schema_version': 1, 'kind': 'study-scope', 'deliverables': ['quantity', 'new_sample'],
        'stages': covered_stages, 'child_rundir': 'children/likelihood'})
    return context


def test_R09_bound_scoped_plan_dropping_a_requested_stage_is_held_at_checkin1(tmp_path):
    # Positive control: the whole request is covered, so CI1 and its execute edge open.
    root = tmp_path.resolve() / 'covered'
    context = _scoped_context(root, ['likelihood'], ['likelihood'])
    context['plan'] = study.bind(context['plan'], context)
    assert context['plan']['open_obligations'] == []
    assert study.gate('checkin1', context) == []
    assert study.gate('checkin1->execute', context) == []
    # The same child against a request that also asks for generation keeps that stage open.
    root = tmp_path.resolve() / 'dropped'
    context = _scoped_context(root, ['generate', 'likelihood'], ['likelihood'])
    context['plan'] = study.bind(context['plan'], context)
    assert [row['id'] for row in context['plan']['open_obligations']] == ['stage:generate']
    held = study.gate('checkin1', context)
    assert held and {row.get('obligation') for row in held} == {'stage:generate'}
    # Claiming a stage the typed operation does not implement is refused at binding.
    root = tmp_path.resolve() / 'claimed'
    context = _scoped_context(root, ['generate', 'likelihood'], ['generate', 'likelihood'])
    with pytest.raises(ValueError, match='does not implement'):
        study.bind(context['plan'], context)


def _prepared_context(root, monkeypatch):
    from ravel.workflow import science
    root.mkdir(parents=True, exist_ok=True)
    store = Store(root=root / 'protected-store')
    spec = {'schema_version': 2, 'mode': 'fictional-study', 'max_seconds': 10,
            'max_attempts': 2, 'task': {'finite': True}}
    source = json.loads((DATA / 'controller/routes/study.json').read_text())
    # This is the fully ordered route template, without claiming shared compiler execution.
    prepared_plan = {'route': {'id': 'study'}, 'parameters': {}, 'steps': deepcopy(source['steps']),
                     'deliverables': deepcopy(reading()['deliverables']), 'open_obligations': []}
    context = {'store': store, 'run_dir': str(root), 'plan': prepared_plan, 'reading': reading(),
               'contract': {'task_mode': 'supplied_events'}}
    _adopt(store, root, study.SPEC_ARTIFACT, spec)
    _adopt(store, root, study.SCOPE_ARTIFACT, {'schema_version': 1, 'kind': 'study-scope',
        'deliverables': ['quantity', 'new_sample'], 'stages': [], 'child_rundir': 'children/study'})
    child = root / 'children/study'
    def pin_file(name, value):
        path = child / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    ordinary = {'kind': 'science', 'child_rundir': 'children/study',
                'plan_sha256': pin_file(science.PLAN, {'mode': spec['mode'], 'max_seconds': 10}),
                'specification_sha256': pin_file(science.SPEC, spec)}
    preparation = {'kind': 'ordinary-study-preparation', 'ordinary': ordinary}
    _adopt(store, root, 'prepare-child:outputs/preparation.json', preparation)
    monkeypatch.setattr(study, 'mode_admission', lambda spec: {'operation': 'fictional-study',
        'role': 'calculation', 'signature': {'stages': [], 'produces': [{'kind': 'document'}]}})
    return context, spec, child


def test_full_bind_consumes_adopted_preparation_and_real_child_pins(tmp_path, monkeypatch):
    context, spec, child = _prepared_context(tmp_path / 'positive', monkeypatch)
    context['plan'] = study.bind(context['plan'], context)
    assert study.gate('checkin1', context) == []
    operate = next(row for row in context['plan']['steps'] if row['id'] == 'operate')
    assert operate['operation'] == 'fictional-study' and operate['role'] == 'calculation'
    assert operate['parameters']['ordinary']['plan_sha256']
    assert operate['parameters']['adapter'] == 'ravel.controller.routes.study.runtime'
    assert operate['attempt_limit'] == 2
    assert study.admit(operate, context) == []
    assert not context['store'].scan('authority')  # Source binding grants no authority.
    _adopt(context['store'], Path(context['run_dir']), study.SPEC_ARTIFACT,
           {**spec, 'max_seconds': 11})
    errors = study.gate('checkin1->execute', context)
    assert errors and any(row['code'] == 'study_binding_changed' for row in errors)
    assert not context['store'].scan('authority')


def test_site_bind_consumes_adopted_exact_launch_scope_without_granting_authority(tmp_path, monkeypatch):
    context, _, _ = _prepared_context(tmp_path / 'site', monkeypatch)
    context['plan']['route'] = {'id': 'study.site'}
    root = Path(context['run_dir'])
    script = root / 'prepared-script'
    script.write_bytes(b'inert scheduler payload\n')
    pin = {'path': script.name, 'sha256': hashlib.sha256(script.read_bytes()).hexdigest()}
    scope = {'schema_version': 1, 'kind': 'study-scope', 'deliverables': ['quantity', 'new_sample'],
             'stages': [], 'child_rundir': 'children/study', 'site': {'jobscript': pin,
             'wms_scope': {'workflow_dir': str(root), 'max_jobs': 1}}}
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, scope)
    context['plan'] = study.bind(context['plan'], context)
    operate = next(row for row in context['plan']['steps'] if row['id'] == 'operate')
    assert operate['parameters']['launch']['jobscript'] == pin
    assert operate['parameters']['wms_scope'] == scope['site']['wms_scope']
    assert study.gate('checkin1', context) == []
    assert not context['store'].scan('authority')
    script.write_bytes(b'changed prepared bytes\n')
    assert any(row['code'] == 'study_binding_invalid' for row in study.gate('checkin1', context))
    # A jobscript is always content-pinned: a digest-free pin naming a directory is refused.
    (root / 'prepared-directory').mkdir()
    unpinned = deepcopy(scope)
    unpinned['site']['jobscript'] = {'path': 'prepared-directory', 'sha256': None}
    _adopt(context['store'], root, study.SCOPE_ARTIFACT, unpinned)
    assert any(row['code'] == 'study_binding_invalid' and 'jobscript pin' in row['message']
               for row in study.gate('checkin1', context))


def test_full_bind_refuses_missing_preparation_before_authority(tmp_path, monkeypatch):
    context, spec, child = _prepared_context(tmp_path / 'missing', monkeypatch)
    context['store'].rows = [row for row in context['store'].rows
        if row['record'].get('artifact') != 'prepare-child:outputs/preparation.json']
    with pytest.raises(ValueError, match='has not adopted'):
        study.bind(context['plan'], context)
    assert not context['store'].scan('authority')


def test_full_bind_refuses_changed_real_child_plan_pin(tmp_path, monkeypatch):
    from ravel.workflow import science
    context, spec, child = _prepared_context(tmp_path / 'changed', monkeypatch)
    (child / science.PLAN).write_text('{}')
    with pytest.raises(ValueError, match='adopted digest'):
        study.bind(context['plan'], context)
    assert not context['store'].scan('authority')


def test_R02_actual_bind_retains_supplied_plus_new_generation_hole(tmp_path, monkeypatch):
    context, spec, child = _prepared_context(tmp_path / 'mixed', monkeypatch)
    context['reading'] = reading(['generate'])
    _adopt(context['store'], Path(context['run_dir']), study.SCOPE_ARTIFACT, {
        'schema_version': 1, 'kind': 'study-scope', 'deliverables': ['quantity'],
        'stages': [], 'child_rundir': 'children/study'})
    context['plan'] = study.bind(context['plan'], context)
    holes = {row['id'] for row in context['plan']['open_obligations']}
    assert holes == {'new_sample', 'stage:generate'}
    refused = study.gate('checkin1->execute', context)
    assert {row['obligation'] for row in refused} == holes
    assert not context['store'].scan('authority')


def test_R08_physical_calculation_requires_judgment_without_literal_exemption(tmp_path, monkeypatch):
    context, spec, child = _prepared_context(tmp_path / 'physical', monkeypatch)
    context['plan']['route'] = {'id': 'calculation'}
    from ravel.physics import literal_calculation
    calls = []
    monkeypatch.setattr(literal_calculation, 'validate_parent', lambda *args: calls.append(args))
    with pytest.raises(ValueError, match='judgment obligation'):
        study.bind(context['plan'], context)
    assert calls == []
    assert context['plan']['parameters'].get('study_bound') is not True
    assert study.gate('checkin1', context)[0]['code'] == 'study_not_bound'
    assert not context['store'].scan('authority')
