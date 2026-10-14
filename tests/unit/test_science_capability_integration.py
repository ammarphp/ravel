"""Adverse integration controls for the shared supervised science boundaries.

Pure dispatch/admission cases do not launch processes or require native tools.
The actual module lifecycle cases below run after the source tree is frozen.
"""
import importlib
import re
from types import SimpleNamespace

import pytest

from ravel import cli
from ravel.physics import domain_adapters
from ravel.workflow import science, review_enforcement
from ravel.workflow.state_io import atomic_json


def test_model_diagnostic_refusal_survives_passed_delivery():
    from ravel.physics.science_worker import diagnostic_presentation
    finding = {'kind': 'source_anomaly', 'message': 'Conflicting DECAY declarations'}
    result = {'status': 'passed', 'status_scope': 'Static diagnosis only',
              'preflight_disposition': 'refused', 'execution_authorized': False,
              'details': {'preflight_disposition': 'refused', 'findings': [finding]},
              'downstream_policy': {'execution_authorized': False, 'physics_validated': False,
                                    'source_findings_do_not_set_workflow_approval': True}}
    fields, text = diagnostic_presentation('model-inputs', result)
    assert fields['preflight_disposition'] == 'refused'
    assert fields['source_findings'] == [finding]
    assert 'does not accept' in text and 'refused' in text
    result['details']['findings'] = []
    with pytest.raises(ValueError, match='retained source findings'):
        diagnostic_presentation('model-inputs', result)


@pytest.mark.parametrize('policy_change', [
    {'execution_authorized': True}, {'physics_validated': True},
    {'source_findings_do_not_set_workflow_approval': False},
])
def test_model_diagnostic_cannot_promote_itself_to_downstream_authority(policy_change):
    from ravel.physics.science_worker import diagnostic_presentation
    policy = {'execution_authorized': False, 'physics_validated': False,
              'source_findings_do_not_set_workflow_approval': True}
    policy.update(policy_change)
    result = {'status_scope': 'Static diagnosis only', 'preflight_disposition': 'static_inventory',
              'execution_authorized': False, 'details': {'preflight_disposition': 'static_inventory', 'findings': []},
              'downstream_policy': policy}
    with pytest.raises(ValueError, match='authority boundaries'):
        diagnostic_presentation('model-inputs', result)


def specification(mode, task):
    return {'schema_version': 2, 'mode': mode, 'source': 'Explicit synthetic engineering control',
            'assumptions': ['No detector fidelity or method benefit is inferred'],
            'max_seconds': 45, 'approval_mode': 'scripted_yes', 'task': task,
            'max_attempts': 1, 'review_policy': review_contract()}


def review_contract():
    return {'schema_version': 1, 'policy': {
        'schema_version': 1,
        'actors': {'proposer': 'producer', 'executor': 'executor', 'physics_critic': 'critic',
                   'skeptical_verifier': 'skeptic', 'physics_decider': 'decider'},
        'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
        'required_checks': [{'id': 'integrity', 'kind': 'integrity'},
                            {'id': 'scientific', 'kind': 'scientific'}],
        'claim_scopes': {'diagnostic': {'checks': ['integrity'], 'actions': ['delivery', 'reuse']}},
    }, 'correction_contract': {'task_fields': [], 'input_slots': []}}


@pytest.mark.parametrize('mode', ['contur-import', 'normalized-measurement', 'ratio-measurement'])
def test_real_adapter_runs_inside_worker_attempt_without_overwriting(tmp_path, monkeypatch, mode):
    # Exercise the actual adapter filesystem contract. Only authorization and
    # rendering are substituted; neither scientific adapter's run is mocked.
    from ravel.physics import science_worker
    from ravel.plotting import science_figures
    from ravel.workflow.state_io import read_json
    if mode == 'contur-import':
        from test_contur_import import contract
        contract(tmp_path)
        task = {'schema_version': 1, 'input': 'input.json'}
        artifact = 'cached-contur-results.json'
    elif mode == 'ratio-measurement':
        from test_ratio_measurement import document, task as ratio_task
        atomic_json(tmp_path / 'input.json', document())
        task = ratio_task()
        artifact = 'ratio-diagnostic.json'
    else:
        from test_normalized_measurement import document, task as contrast_task
        atomic_json(tmp_path / 'input.json', document())
        task = contrast_task()
        artifact = 'normalized-contrast.json'
    rd = tmp_path / 'run'
    rd.mkdir()
    spec = specification(mode, task)
    proposal = {'base_dir': str(tmp_path), 'attempt': 1,
                'output_directory': 'outputs/attempt-1',
                'stage_binding': {'input_snapshot': {}}}
    monkeypatch.setattr(science_worker, 'verify_worker', lambda _: proposal)
    monkeypatch.setattr(science_worker, 'execution_spec', lambda _: spec)
    monkeypatch.setattr(science_figures, 'render', lambda *_: {'figures': [], 'tables': []})
    assert science_worker.main([str(rd), '--attempt', '1']) == 0
    out = rd / 'outputs/attempt-1'
    result = read_json(out / 'result.json')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert (out / mode / artifact).is_file()
    assert read_json(out / 'verification.json')['passed'] is True
    assert read_json(out / 'checkin2.json')['sections']['waypoint']['status'] == 'passed'
    snapshot = {str(p.relative_to(out)): p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):
        science_worker.main([str(rd), '--attempt', '1'])
    assert snapshot == {str(p.relative_to(out)): p.read_bytes() for p in out.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode,task,name', [
    ('contrast', {'input': 'contrast.json'}, 'event_contrasts'),
    ('analyze', {'backend': 'analysis-ir', 'program': 'program.json',
                 'contract': 'objects.json', 'events': 'events.json'}, 'analysis_ir'),
    ('analyze', {'backend': 'routine-build', 'input': 'build.json'}, 'routine_build'),
    ('analyze', {'backend': 'routine-candidate', 'input': 'construction.json',
                 'candidate': 'initial', 'parent_feedback': None}, 'routine_candidate'),
    ('statistical-model', {'input': 'model.json', 'profile_points': [0, 1],
                          'comparison_points': [{'mu': 0}, {'mu': 1}]}, 'statistical_model'),
    ('published-model', {'input': 'published.json'}, 'published_model'),
    ('model-portfolio', {'input': 'portfolio.json'}, 'reinterpret_db'),
    ('signal-template', {'input': 'templates.json'}, 'signal_templates'),
    ('stau-events', {'input': 'events.json'}, 'stau_adapter'),
    ('native-likelihood', {'input': 'native.json'}, 'native_likelihood'),
    ('eft-functions', {'input': 'response.json'}, 'eft_functions'),
    ('contur-import', {'schema_version': 1, 'input': 'source.json'}, 'contur_import'),
    ('ratio-measurement', {'schema_version': 1, 'input': 'ratio.json', 'signal_strength': 1}, 'ratio_measurement'),
    ('derived-quantities', {'schema_version': 1, 'input': 'derived.json', 'contract_sha256': 'a' * 64}, 'derived_quantities'),
    ('finite-mc', {'input': 'finite-mc.json'}, 'finite_mc_model'),
    ('joint-fit', {'input': 'joint-fit.json'}, 'joint_fit'),
    ('joint-qualification', {'input': 'joint-qualification.json'}, 'joint_qualification'),
    ('model-tool-bridge', {'config': 'model-tool.json'}, 'model_tool_bridge'),
    ('model-provider-bridge', {'config': 'provider.json'}, 'model_provider_bridge'),
    ('model-derivation-bridge', {'config': 'derivation.json'}, 'model_derivation_bridge'),
    ('continuous-fit', {'input': 'model.json'}, 'continuous_fit'),
    ('model-inputs', {'slha_file': 'model.slha', 'source_sha256': 'a' * 64,
                      'completeness_file': 'completeness.json'}, 'model_input_study'),
    ('normalized-measurement', {'schema_version': 1, 'input': 'model.json', 'signal_strength': 1,
                                'signal_strength_max': 5}, 'normalized_measurement'),
])
def test_new_science_dispatch_only_validates_and_inventories(tmp_path, monkeypatch, mode, task, name):
    calls = []
    data = tmp_path / 'input.json'
    data.write_text('{}\n')
    fake = SimpleNamespace(validate=lambda value: calls.append(('validate', value)),
                           inputs=lambda value, base: [data],
                           run=lambda *_: pytest.fail('planning must not execute an adapter'))
    original = importlib.import_module
    monkeypatch.setattr(importlib, 'import_module',
                        lambda module: fake if module == 'ravel.physics.' + name else original(module))
    spec = specification(mode, task)
    science.validate(spec)
    assert science.task_inputs(spec, tmp_path) == [data]
    assert calls == [('validate', task)]


@pytest.mark.parametrize('mode,task', [
    ('contrast', {'input': 'contrast.json'}),
    ('analyze', {'backend': 'analysis-ir', 'program': 'program.json',
                 'contract': 'objects.json', 'events': 'events.json'}),
    ('analyze', {'backend': 'routine-build', 'input': 'build.json'}),
    ('analyze', {'backend': 'routine-candidate', 'input': 'construction.json',
                 'candidate': 'initial', 'parent_feedback': None}),
    ('analyze', {'backend': 'rivet-built', 'routine': 'CONTROL'}),
    ('analyze', {'backend': 'simpleanalysis-built', 'routine': 'CONTROL'}),
    ('domain', {'domain': 'model-probe', 'config': {'max_seconds': 45}}),
    ('statistical-model', {'input': 'model.json', 'profile_points': [0, 1],
                          'comparison_points': [{'mu': 0}, {'mu': 1}]}),
    ('published-model', {'input': 'published.json'}),
    ('model-portfolio', {'input': 'portfolio.json'}),
    ('likelihood-parity', {'input': 'parity.json'}),
    ('signal-template', {'input': 'templates.json'}),
    ('stau-events', {'input': 'events.json'}),
    ('native-likelihood', {'input': 'native.json'}),
    ('eft-functions', {'input': 'response.json'}),
    ('contur-import', {'schema_version': 1, 'input': 'source.json'}),
    ('ratio-measurement', {'schema_version': 1, 'input': 'ratio.json', 'signal_strength': 1}),
    ('derived-quantities', {'schema_version': 1, 'input': 'derived.json', 'contract_sha256': 'a' * 64}),
    ('finite-mc', {'input': 'finite-mc.json'}),
    ('joint-fit', {'input': 'joint-fit.json'}),
    ('joint-qualification', {'input': 'joint-qualification.json'}),
    ('model-tool-bridge', {'config': 'model-tool.json'}),
    ('model-provider-bridge', {'config': 'provider.json'}),
    ('model-derivation-bridge', {'config': 'derivation.json'}),
    ('mpi-observer', {'input': 'observer.json'}),
    ('likelihood-profile-probe', {'input': 'profile.json'}),
    ('likelihood-candidate-check', {'input': 'candidates.json'}),
    ('likelihood-step-refinement', {'input': 'refinement.json'}),
    ('continuous-fit', {'input': 'model.json'}),
    ('model-inputs', {'slha_file': 'model.slha', 'source_sha256': 'a' * 64,
                      'completeness_file': 'completeness.json'}),
    ('normalized-measurement', {'schema_version': 1, 'input': 'model.json', 'signal_strength': 1,
                                'signal_strength_max': 5}),
])
def test_each_new_executor_refuses_legacy_plan_before_creating_run(tmp_path, monkeypatch, mode, task):
    monkeypatch.setattr(science, 'adapter', lambda _: SimpleNamespace(validate=lambda _: None))
    spec = specification(mode, task)
    spec['schema_version'] = 1
    spec.pop('max_attempts'); spec.pop('review_policy')
    atomic_json(tmp_path / 'spec.json', spec)
    with pytest.raises(ValueError, match='prospective version 2'):
        science.plan(tmp_path / 'run', tmp_path / 'spec.json')
    assert not (tmp_path / 'run').exists()


def test_every_adapter_input_must_be_regular_before_planning(tmp_path, monkeypatch):
    target = tmp_path / 'input.json'
    target.write_text('{}\n')
    link = tmp_path / 'linked.json'
    link.symlink_to(target)
    fake = SimpleNamespace(inputs=lambda *_: [link])
    monkeypatch.setattr(science, 'adapter', lambda _: fake)
    with pytest.raises(ValueError, match=re.escape(f'input path traverses a symlink: {link}')):
        science.task_inputs(specification('contrast', {'input': 'linked.json'}), tmp_path)


@pytest.mark.parametrize('mode,module_name', [('mpi-observer', 'mpi_observer'),
                                            ('likelihood-profile-probe', 'likelihood_profile_probe'),
                                            ('likelihood-candidate-check', 'likelihood_candidate_check'),
                                            ('likelihood-step-refinement', 'likelihood_step_refinement')])
def test_probe_dispatch_is_validation_adapter_without_execution(tmp_path, monkeypatch, mode, module_name):
    from importlib import import_module
    probe = import_module('ravel.validation.' + module_name)
    data = tmp_path / 'observer.json'; data.write_text('{}')
    calls = []
    monkeypatch.setattr(probe, 'validate', lambda task: calls.append(task))
    monkeypatch.setattr(probe, 'inputs', lambda task, base: [data])
    monkeypatch.setattr(probe, 'execution_seconds', lambda task, base: 1)
    monkeypatch.setattr(probe, 'run', lambda *args: pytest.fail('planning launched a numerical worker'))
    spec = specification(mode, {'input': 'observer.json'})
    science.validate(spec)
    assert science.adapter(spec) is probe
    assert science.task_inputs(spec, tmp_path) == [data]
    assert calls == [spec['task']]


def test_fixed_probe_cannot_exceed_approved_outer_budget(monkeypatch):
    fake = SimpleNamespace(validate=lambda _: None)
    monkeypatch.setattr(science, 'adapter', lambda _: fake)
    spec = specification('domain', {'domain': 'model-probe', 'config': {'max_seconds': 46}})
    with pytest.raises(ValueError, match='hard ceiling'):
        science.validate(spec)


@pytest.mark.parametrize('seconds', [46, 0, -1, True, 1.5])
def test_nested_native_budget_is_admitted_before_approval(tmp_path, monkeypatch, seconds):
    fake = SimpleNamespace(inputs=lambda *_: [], execution_seconds=lambda *_: seconds)
    monkeypatch.setattr(science, 'adapter', lambda _: fake)
    with pytest.raises(ValueError, match='hard ceiling'):
        science.task_inputs(specification('native-likelihood', {'input': 'native.json'}), tmp_path)


def test_nested_native_budget_within_outer_scope_is_admitted(tmp_path, monkeypatch):
    source = tmp_path / 'native.json'
    source.write_text('{}')
    fake = SimpleNamespace(inputs=lambda *_: [source], execution_seconds=lambda *_: 45)
    monkeypatch.setattr(science, 'adapter', lambda _: fake)
    assert science.task_inputs(specification('native-likelihood', {'input': 'native.json'}), tmp_path) == [source]


def test_domain_probe_must_preserve_failure_and_evidence_boundary(tmp_path, monkeypatch):
    fake = SimpleNamespace(validate=lambda _: None, inputs=lambda *_: [],
                           run=lambda *_: {'domain': 'model-probe', 'status': 'passed',
                                           'physics_validated': False,
                                           'details': {'checks_passed': False}})
    monkeypatch.setitem(__import__('sys').modules, 'ravel.physics.model_probe', fake)
    with pytest.raises(ValueError, match='honest bounded postconditions'):
        domain_adapters.run({'domain': 'model-probe', 'config': {}}, tmp_path, tmp_path / 'out')
    assert not (tmp_path / 'out/domain-result.json').exists()


def test_review_refusal_does_not_spend_science_attempt(tmp_path, monkeypatch):
    # The envelope is a separate concern here: this case checks the ordering
    # between review admission and the one-attempt journal write.
    rd = tmp_path / 'run'
    rd.mkdir()
    stage = {'stage': 'science', 'command': ['python', 'worker'], 'inputs': [], 'outputs': ['outputs']}
    monkeypatch.setattr(science, 'review_enabled', lambda _: False)
    monkeypatch.setattr(science, 'verify_plan', lambda *_args, **_kwargs:
                        {'stages': [stage], 'max_seconds': 45})
    def refuse(*_args, **_kwargs):
        raise ValueError('scientific review blocks stage: unresolved finding')
    monkeypatch.setattr(review_enforcement, 'before_stage', refuse)
    with pytest.raises(ValueError, match='unresolved finding'):
        science.run(rd)
    assert not (rd / 'execution_attempt.json').exists()
    assert not (rd / 'execution_state.json').exists()


def test_direct_science_worker_checks_the_actual_attempt_budget(tmp_path, monkeypatch):
    rd = tmp_path / 'run'
    rd.mkdir()
    (rd / 'inputs').mkdir()
    (rd / science.PLAN).write_text('{}\n')
    proposal = {'max_seconds': 45, 'stage_binding': {'fingerprint': 'recipe'}}
    monkeypatch.setattr(science, 'review_enabled', lambda _: False)
    monkeypatch.setattr(science, 'verify_plan', lambda *_args, **_kwargs: proposal)
    monkeypatch.setattr(science.execution, 'load_execution', lambda _: {'stages': {'science': {
        'status': 'running', 'supervisor_pid': __import__('os').getppid(),
        'child_pid': __import__('os').getpid(), 'fingerprint': 'recipe'}}})
    atomic_json(rd / 'execution_attempt.json', {'attempt': 1,
                'plan_sha256': science.execution.file_hash(rd / science.PLAN), 'budget_seconds': 900})
    with pytest.raises(ValueError, match='current approved supervised attempt'):
        science.verify_worker(rd)


@pytest.mark.parametrize('command,module', [
    ('hypothesis-board', 'workflow.hypothesis_board'),
    ('experiment-allocator', 'workflow.experiment_allocator'),
    ('evidence-independence', 'workflow.evidence_independence'),
    ('numerical-witness', 'validation.numerical_witness'),
    ('analysis-witness', 'validation.analysis_witness'),
    ('agent-graph', 'workflow.agent_graph'),
])
def test_advisory_cli_preserves_the_modules_actual_argument_parser(monkeypatch, command, module):
    seen = []
    fake = SimpleNamespace(main=lambda argv: seen.append(argv) or 7)
    original = importlib.import_module
    monkeypatch.setattr(importlib, 'import_module',
                        lambda name: fake if name == 'ravel.' + module else original(name))
    assert cli.main([command, '--help']) == 7
    assert seen == [['--help']]


def test_analysis_assessment_dispatch_preserves_bound_specification_and_exclusive_output(tmp_path, monkeypatch):
    seen = []
    fake = SimpleNamespace(main=lambda argv: seen.append(argv) or 2)
    monkeypatch.setitem(__import__('sys').modules, 'ravel.workflow.analysis_admission', fake)
    assert cli.main(['analyses', 'assess', '--specification', str(tmp_path / 'admission.json'),
                     '--out', str(tmp_path / 'report.json')]) == 2
    assert seen == [['--specification', str(tmp_path / 'admission.json'),
                     '--out', str(tmp_path / 'report.json')]]


def test_completion_rejects_unbound_verification_and_live_review(tmp_path, monkeypatch):
    rd = tmp_path / 'run'
    (rd / 'outputs').mkdir(parents=True)
    (rd / 'inputs').mkdir()
    (rd / science.PLAN).write_text('{}\n')
    # The packet computes claim checks over the stage's declared outputs, as a real plan lists them.
    stage = {'stage': 'science', 'outputs': ['outputs']}
    proposal = {'mode': 'contrast', 'max_seconds': 45, 'stages': [stage]}
    monkeypatch.setattr(science, 'verify_plan', lambda *_args, **_kwargs: proposal)
    monkeypatch.setattr(science.execution, 'load_execution', lambda _: {'stages': {'science': {'status': 'succeeded'}}})
    monkeypatch.setattr(science.execution, 'validate_completed_execution', lambda *_: [])
    atomic_json(rd / 'execution_attempt.json', {'attempt': 1,
                'plan_sha256': science.execution.file_hash(rd / science.PLAN), 'budget_seconds': 45})
    atomic_json(rd / 'outputs/result.json', {'status': 'passed', 'physics_validated': False})
    atomic_json(rd / 'outputs/verification.json', {'passed': True, 'scope': 'contrast',
                'physics_validated': False, 'expert_review': False, 'result_sha256': '0' * 64})
    atomic_json(rd / 'outputs/checkin2.json', {'schema_version': 1, 'kind': 'checkin2', 'sections': {
        'waypoint': 'control', 'expectation': 'bounded engineering delivery',
        'ask': {'options': ['GO', 'ADJUST']}}})
    monkeypatch.setattr(review_enforcement, 'delivery_errors', lambda _: ['live review is unresolved'])
    packet = science.packet(rd)
    assert packet['lifecycle_verdict'] == 'FAIL'
    assert any('bind the delivered result' in error for error in packet['errors'])
    assert 'live review is unresolved' in packet['errors']
    assert packet['execution']['status'] == 'failed'  # every check ran; the packet did not stop on a missing field


def test_correction_cli_preserves_explicit_decider_fields_without_launch(tmp_path, monkeypatch):
    request = {'actor_id': 'decider', 'changed_paths': ['inputs/value.json'],
               'recheck_checks': ['scientific'], 'max_seconds': 15}
    atomic_json(tmp_path / 'request.json', request)
    seen = []
    monkeypatch.setattr(science, 'correct', lambda rd, **value: seen.append((rd, value)) or {'status': 'admitted'})
    assert cli.main(['science-correct', '--rundir', str(tmp_path / 'run'),
                     '--request', str(tmp_path / 'request.json')]) == 0
    assert seen == [(tmp_path / 'run', request)]


@pytest.mark.parametrize('bad', [[], {'actor_id': 'decider'},
                                {'actor_id': 'decider', 'changed_paths': [], 'recheck_checks': [], 'execute': True}])
def test_correction_cli_refuses_malformed_or_extra_authority(tmp_path, monkeypatch, bad):
    atomic_json(tmp_path / 'request.json', bad)
    monkeypatch.setattr(science, 'correct', lambda *_args, **_kwargs: pytest.fail('malformed correction must not be admitted'))
    assert cli.main(['science-correct', '--rundir', str(tmp_path / 'run'),
                     '--request', str(tmp_path / 'request.json')]) == 2
