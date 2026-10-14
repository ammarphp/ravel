"""Approved, bounded execution for supplied-event and scientific-adapter studies.

The existing stage supervisor owns process cleanup and byte custody. A completed
study is a delivered computation within its declared scope, never paper closure.
"""
from pathlib import Path
import os
from copy import deepcopy
from contextlib import contextmanager
import inspect
import math
import time

from ravel.paths import module_command
from ravel.workflow import execution
from ravel.workflow.state_io import atomic_json, file_lock, read_json

MODES = (
    'task-completion-context',
    'ntuple-inventory',
    'mc-expected-construction',
    'asimov-sensitivity',
    'mc-closure',
    'literal-calculation',
    'root-stream',
    'tree-array-export',
    'cosmic-evolution',
    'chargino-decay-table',
    'published-classifier',
    'mssm-observable-map',
    'nmssm-yukawa-map',
    'width-inputs',
    'mass-width-grid',
    'analysis-response-features',
    'classifier-inputs',
    'llp-plane-recipe',
    'svj-recipe',
    'research-comparison',
    'quantitative-predictive',
    'model-events',
    'analyze',
    'quantities',
    'measurement',
    'domain',
    'contrast',
    'statistical-model',
    'published-model',
    'model-portfolio',
    'likelihood-parity',
    'numerical-reference-check',
    'cosmology-solver',
    'signal-template',
    'stau-events',
    'native-likelihood',
    'full-auxiliary-calibration',
    'background-discrete-profile',
    'eft-functions',
    'normalized-measurement',
    'continuous-fit',
    'native-statistical-construction',
    'model-inputs',
    'contur-import',
    'ratio-measurement',
    'group-normalization',
    'group-composition',
    'source-tables',
    'scientific-delivery',
    'published-summary',
    'native-group-acquisition',
    'retained-shower',
    'derived-quantities',
    'finite-mc',
    'pdf-variations',
    'model-sources',
    'model-tool-bridge',
    'model-provider-bridge',
    'model-derivation-bridge',
    'model-ward',
    'generated-spectrum',
    'mpi-observer',
    'initialized-settings-qualification',
    'initialized-settings-retained',
    'mpi-paired-effect',
    'likelihood-profile-probe',
    'likelihood-candidate-check',
    'likelihood-step-refinement',
    'cr-signal-qualification',
    'joint-fit',
    'joint-qualification',
    'joint-score',
    'hs3-likelihood',
    'workspace-combination-study',
    'diagrammatica-code',
    'symbolic-evaluation',
    'feyn-graph',
    'diagram-analysis',
    'feynarts-amplitude',
    'sfitter-native-fit',
    'sfitter-scan-extraction',
    'sfitter-observed-events',
    'eft-convention-transport',
    'eft-toolchain',
    'finite-integrals',
    'parameter-space-sampling',
    'contur-yoda',
    'contur-companion',
    'ma5-saf',
    'ma5-pad',
    'resonance-width',
    'columnar-analysis',
    'authored-analysis',
    'formula-grid',
    'coupling-morphing',
    'prescribed-statistic',
    'search-statistics',
    'differential-likelihood',
    'cross-section',
    'simplified-spectrum',
    'resonance-lineshape',
    'model-authoring',
    'figure-comparison',
    'amplitude-predictions',
    'weighted-events',
    'reco-ntuple-routine',
    'lhe-transform',
    'generation-reconciliation',
    'event-production',
    'ml-training',
)
AMPLITUDE_MODES = {'amplitude-integration': 'amplitude_integration', 'amplitude-predictions': 'amplitude_predictions',
                   'weighted-events': 'weighted_events', 'amplitude-crosscheck': 'amplitude_crosscheck'}
SPEC = 'inputs/science.json'
PLAN = 'inputs/science-plan.json'
APPROVAL = 'inputs/science-approval.json'
from .method_selection import DECISION_PATH as METHOD_DECISION  # noqa: E402
EXECUTION_TASK = 'inputs/science-execution-task.json'
REVIEW_POLICY = 'inputs/physics_review_policy.json'
# A study whose supplied inputs or native prerequisites are absent is held here.
HELD = 'inputs/science-held.json'


class MissingInput(ValueError):
    """A supplied input path does not exist."""
    def __init__(self, path):
        self.path = str(path)
        super().__init__(f'supplied input not found: {path}')


class LegacyPolicyRefusal(ValueError):
    """A version 1 specification asks for something only a version 2 study may plan."""


class MissingPrerequisite(ValueError):
    """A native engine, package or runtime the adapter needs is not provisioned."""


def applicability(mode):
    """The registered applicability of a dispatchable mode: general, or source-bound with its predicate."""
    from .capability_routing import declared_descriptors
    if mode not in MODES:
        raise ValueError('unknown science mode: ' + str(mode))
    row = declared_descriptors().get(mode)
    return dict(row['descriptor']['applicability']) if row else {'scope': 'general'}


def _applicability_notice(mode):
    bound = applicability(mode)
    if bound['scope'] != 'source-bound':
        return ''
    general = bound['general_operation']
    return ('\nThis adapter is source-bound to ' + bound['bound_to'] + '. It is not a general operation'
            + (f'; the general operation is `{general}`' if general else '') + '.\n')


def adapter(spec):
    if spec['mode'] == 'ml-training':
        from ravel.physics import ml_training
        return ml_training
    if spec['mode']=='ntuple-inventory':
        from ravel.physics import ntuple_inventory
        return ntuple_inventory
    if spec['mode']=='mc-expected-construction':
        from ravel.physics import mc_expected_construction
        return mc_expected_construction
    if spec['mode']=='root-stream':
        from ravel.physics import root_stream
        return root_stream
    if spec['mode']=='tree-array-export':
        from ravel.physics import tree_array_export
        return tree_array_export
    if spec['mode']=='chargino-decay-table':
        from ravel.physics import chargino_decay_table
        return chargino_decay_table
    if spec['mode']=='mssm-observable-map':
        from ravel.physics import mssm_observable_map
        return mssm_observable_map
    if spec['mode']=='nmssm-yukawa-map':
        from ravel.physics import nmssm_yukawa_map
        return nmssm_yukawa_map
    if spec['mode']=='width-inputs':
        from ravel.physics import width_inputs
        return width_inputs
    if spec['mode']=='mass-width-grid':
        from ravel.physics import mass_width_grid
        return mass_width_grid
    if spec['mode'] in ('published-classifier','analysis-response-features','classifier-inputs'):
        from importlib import import_module
        return import_module('ravel.physics.'+spec['mode'].replace('-','_'))
    if spec['mode']=='llp-plane-recipe':
        from ravel.physics import llp_plane_recipe
        return llp_plane_recipe
    if spec['mode']=='svj-recipe':
        from ravel.physics import svj_recipe
        return svj_recipe
    if spec['mode']=='quantitative-predictive':
        from ravel.physics import quantitative_predictive
        return quantitative_predictive
    if spec['mode']=='research-comparison':
        from ravel.physics import research_comparison
        return research_comparison
    if spec['mode'] == 'model-events':
        from ravel.physics import model_events
        return model_events
    if spec['mode']=='joint-score':
        from ravel.physics import joint_score
        return joint_score
    if spec['mode'] in ('formula-grid', 'coupling-morphing', 'prescribed-statistic', 'search-statistics', 'differential-likelihood'):
        from importlib import import_module
        return import_module('ravel.physics.inference.' + spec['mode'].replace('-', '_'))
    """Resolve the admitted scientific implementation without executing it."""
    from importlib import import_module
    mode, task = spec['mode'], spec['task']
    if mode == 'joint-fit' and 'response_family' in task:
        return import_module('ravel.physics.marked_joint_analysis')
    if mode == 'joint-qualification' and 'response_family' in task:
        return import_module('ravel.physics.marked_joint_study')
    if mode == 'numerical-reference-check':
        return import_module('ravel.validation.numerical_reference')
    if mode == 'likelihood-parity':
        return import_module('ravel.validation.likelihood_parity')
    if mode == 'likelihood-profile-probe':
        return import_module('ravel.validation.likelihood_profile_probe')
    if mode == 'likelihood-candidate-check':
        return import_module('ravel.validation.likelihood_candidate_check')
    if mode == 'likelihood-step-refinement':
        return import_module('ravel.validation.likelihood_step_refinement')
    if mode == 'cr-signal-qualification':
        return import_module('ravel.validation.cr_signal_study')
    if mode == 'mpi-observer':
        return import_module('ravel.validation.mpi_observer')
    if mode == 'initialized-settings-qualification':
        return import_module('ravel.validation.initialized_settings_qualification')
    if mode == 'initialized-settings-retained':
        return import_module('ravel.validation.initialized_settings_retained')
    if mode == 'mpi-paired-effect':
        return import_module('ravel.validation.mpi_paired_effect')
    if mode == 'analyze':
        name = {'analysis-ir': 'analysis_ir', 'routine-build': 'routine_build',
                'routine-candidate': 'routine_candidate', 'native-construction':'native_construction',
                'agentrivet-source':'agentrivet_source'}.get(task.get('backend'), 'existing_events')
    else:
        name = {'manuscript-build': 'manuscript_build', 'task-completion-context':'task_completion_context','literal-calculation': 'literal_calculation', 'quantities': 'quantities', 'measurement': 'measurement', 'domain': 'domain_adapters',
                'contrast': 'event_contrasts', 'statistical-model': 'statistical_model', 'published-model': 'published_model',
                'model-portfolio': 'reinterpret_db', 'signal-template': 'signal_templates',
                'stau-events': 'stau_adapter', 'native-likelihood': 'native_likelihood', 'full-auxiliary-calibration': 'full_auxiliary_calibration', 'asimov-sensitivity':'asimov_sensitivity', 'mc-closure':'mc_closure',
                'reco-ntuple-routine': 'reco_ntuple_routine',
                'background-discrete-profile': 'background_discrete_profile',
                'eft-functions': 'eft_functions', 'normalized-measurement': 'normalized_measurement',
                'continuous-fit': 'continuous_fit', 'native-statistical-construction': 'native_statistical_construction', 'model-inputs': 'model_input_study',
                'checkmate-events': 'checkmate_events', 'contur-yoda': 'contur_yoda', 'contur-companion': 'contur_companion', 'contur-import': 'contur_import', 'ratio-measurement': 'ratio_measurement',
                'group-normalization': 'group_normalization', 'group-composition': 'group_composition', 'source-tables': 'source_tables', 'scientific-delivery': 'scientific_delivery', 'published-summary': 'published_summary', 'native-group-acquisition': 'native_group_fills', 'retained-shower': 'retained_shower', 'derived-quantities': 'derived_quantities', 'finite-mc': 'finite_mc_model',
                'pdf-variations': 'pdf_variations', 'model-sources': 'model_sources', 'model-tool-bridge': 'model_tool_bridge', 'model-provider-bridge': 'model_provider_bridge', 'generated-spectrum': 'generated_spectrum',
                'model-derivation-bridge': 'model_derivation_bridge', 'model-ward': 'model_ward', 'joint-fit': 'joint_fit',
                'joint-qualification': 'joint_qualification', 'hs3-likelihood': 'hs3_likelihood', 'workspace-combination-study': 'workspace_combination_study', 'diagrammatica-code': 'diagrammatica_code', 'symbolic-evaluation': 'symbolic_evaluation', 'feyn-graph':'feyn_graph', 'diagram-analysis':'diagram_analysis', 'feynarts-amplitude':'feynarts_amplitude', 'sfitter-native-fit': 'sfitter_native', 'sfitter-scan-extraction': 'sfitter_scan_extraction', 'sfitter-observed-events':'sfitter_observed_events', 'eft-convention-transport': 'eft_conventions', 'eft-toolchain': 'eft_toolchain', 'parameter-space-sampling': 'parameter_space_sampling', 'dataset-query-quantities': 'dataset_query_quantities', 'finite-integrals': 'finite_integrals', 'ma5-saf': 'ma5_saf', 'cosmology-solver': 'cosmology_solver', 'cosmic-evolution': 'cosmic_evolution', 'ma5-pad': 'ma5_pad',
                'resonance-width': 'resonance_width', 'columnar-analysis': 'columnar_analysis', 'authored-analysis': 'authored_analysis',
                'cross-section': 'cross_sections', 'simplified-spectrum': 'simplified_spectrum',
                'resonance-lineshape': 'resonance_lineshape', 'model-authoring': 'model_authoring',
                'figure-comparison': 'figure_comparison',
                'amplitude-integration': 'amplitude_integration', 'amplitude-predictions': 'amplitude_predictions', 'weighted-events': 'weighted_events', 'amplitude-crosscheck': 'amplitude_crosscheck',
                'lhe-transform': 'lhe_transform', 'generation-reconciliation': 'generation_reconciliation',
                'event-production': 'event_production'}[mode]
    return import_module('ravel.physics.' + name)


def regular(value, base, *, _session=None):
    if _session is not None:
        return _session.regular_file(value, base)
    p = Path(value).expanduser()
    p = p if p.is_absolute() else Path(base) / p
    if any(part.is_symlink() for part in (p, *p.parents)):
        raise ValueError(f'input path traverses a symlink: {p}')
    if not p.exists():
        raise MissingInput(p)
    if not p.is_file():
        raise ValueError(f'expected a regular file: {p}')
    return p.resolve()


def validate(spec):
    required = {'schema_version', 'mode', 'source', 'assumptions', 'max_seconds', 'approval_mode', 'task'}
    version = spec.get('schema_version') if isinstance(spec, dict) else None
    if isinstance(spec, dict) and 'resonance_handoff' in spec:
        required.add('resonance_handoff')
        if version != 2 or type(spec['resonance_handoff']) is not str or not spec['resonance_handoff'].strip():
            raise ValueError('resonance handoff requires a version2 bound input pathname')
    if isinstance(spec, dict) and 'backend_handoff' in spec:
        required.add('backend_handoff')
        if version != 2 or type(spec['backend_handoff']) is not str or not spec['backend_handoff'].strip():
            raise ValueError('backend handoff requires a version2 bound input pathname')
    if isinstance(spec, dict) and 'goal_binding' in spec:
        required.add('goal_binding')
        if version != 2: raise ValueError('parent-bound science child requires the ordinary version2 review policy')
        from .task_completion import binding_projection
        binding_projection(spec['goal_binding'], base_dir=Path.cwd())
    if isinstance(spec, dict) and 'generation_efficiency' in spec:
        required.add('generation_efficiency')
        if version != 2 or spec.get('mode') != 'model-events':
            raise ValueError('generation efficiency requires version2 model-events')
        from .generation_efficiency import validate_policy
        validate_policy(spec['generation_efficiency'])
    if isinstance(spec, dict) and 'quantitative_check' in spec:
        required.add('quantitative_check')
        if version != 2 or spec.get('max_attempts') != 1:
            raise ValueError('quantitative check requires one prospectively bound ordinary version2 attempt')
        from .quantitative_predictive_checks import validate_binding
        validate_binding(spec['quantitative_check'])
    if isinstance(spec, dict) and 'execution' in spec:
        # Placement pin (ravel.workflow.placement); one attempt, so its plan is approved once.
        required.add('execution')
        if version != 2 or spec.get('max_attempts') != 1:
            raise ValueError('placement requires one prospectively bound version2 attempt')
        from .placement import validate as validate_placement
        validate_placement(spec['execution'])
    if isinstance(spec, dict) and 'autonomy' in spec:
        required.add('autonomy')
        if version != 2 and not (version==1 and spec.get('mode')=='literal-calculation'):
            raise ValueError('autonomy requires science/v2 or the genuine source-bound literal calculator')
        _keys(spec['autonomy'], {'path', 'sha256'}, 'explicit autonomy declaration pin')
    if version == 2:
        required |= {'review_policy', 'max_attempts'}
        if 'output_policy' in spec:
            required.add('output_policy')
    if not isinstance(spec, dict) or set(spec) != required or type(version) is not int or version not in (1, 2):
        raise ValueError('science specification requires exactly ' + ', '.join(sorted(required)))
    if spec['mode'] not in MODES or spec['approval_mode'] not in ('physicist', 'scripted_yes'):
        raise ValueError('invalid science mode or approval mode')
    if not isinstance(spec['source'], str) or not spec['source'].strip():
        raise ValueError('a scientific source or explicitly synthetic-control description is required')
    if not isinstance(spec['assumptions'], list) or not spec['assumptions'] or any(
            not isinstance(x, str) or not x.strip() for x in spec['assumptions']):
        raise ValueError('at least one explicit assumption is required')
    if type(spec['max_seconds']) is not int or not 1 <= spec['max_seconds'] <= 86400:
        raise ValueError('max_seconds must be an integer from 1 to 86400')
    if not isinstance(spec['task'], dict):
        raise ValueError('task must be an object')
    if version == 2:
        validate_review_contract(spec)
        if 'output_policy' in spec:
            if spec['max_attempts'] != 1 or spec['review_policy']['policy']['max_redos'] != 0:
                raise ValueError('exact output policy requires one prospective attempt and no corrections')
            execution.validate_output_policy(Path.cwd(), ['outputs/attempt-1'], spec['output_policy'], execution.resolve_path)
    task = spec['task']
    if spec['mode'] == 'quantities':
        if set(task) != {'contract', 'records'}:
            raise ValueError('quantities requires contract and records paths')
    else:
        adapter(spec).validate(task)
        if spec['mode'] in ('manuscript-build','task-completion-context','ntuple-inventory', 'mc-expected-construction', 'asimov-sensitivity', 'mc-closure', 'mssm-observable-map','nmssm-yukawa-map','sfitter-native-fit','sfitter-scan-extraction','sfitter-observed-events','eft-convention-transport','model-events','eft-toolchain','finite-integrals','parameter-space-sampling', 'dataset-query-quantities','root-stream','feyn-graph','diagram-analysis','feynarts-amplitude'):adapter(spec).validate_scope(spec)
        if (spec['mode'] == 'domain' and task['domain'] == 'model-probe'
                and task['config']['max_seconds'] > spec['max_seconds']):
            raise ValueError('model probe budget exceeds the scientific-study hard ceiling')


def task_inputs(spec, base, *, _session=None, _readonly=None, _readonly_role=None):
    mode, task = spec['mode'], spec['task']
    goal_inputs = []
    if 'resonance_handoff' in spec:
        from .resonance_study import handoff_inputs
        goal_inputs += [regular(p['path'], base, _session=_session) for p in handoff_inputs(spec, base)]
    if 'backend_handoff' in spec:
        from .backend_portfolio import handoff_inputs
        goal_inputs += [regular(p['path'], base, _session=_session) for p in handoff_inputs(spec, base)]
    if 'goal_binding' in spec:
        from .task_completion import binding_projection
        goal_inputs += [regular(p['path'], base, _session=_session) for p in
                       binding_projection(spec['goal_binding'], base_dir=base)['input_pins']]
    if 'quantitative_check' in spec:
        from . import quantitative_predictive_checks as predictive
        guidance = predictive.guidance(spec['quantitative_check'], base)
        if guidance['requirements']['effective']['wall_seconds'] >= spec['max_seconds']:
            raise ValueError('quantitative checking allocation must fit inside whole stage ceiling')
        goal_inputs += [regular(p, base, _session=_session) for p in predictive.inputs(spec['quantitative_check'], base)]
        goal_inputs.append(regular(predictive.__file__, base, _session=_session))
    if mode == 'quantities':
        from ravel.physics.quantities import validate as check
        files = [regular(task[k], base, _session=_session) for k in ('contract', 'records')]
        check(read_json(files[0]))
        return list(dict.fromkeys([*files, *goal_inputs]))
    # Independently require regular files even for adapters that enumerate runtime
    # artifacts. No validation or input inventory starts external computation.
    implementation = adapter(spec)
    if mode in ('width-inputs','mass-width-grid','ntuple-inventory','mc-expected-construction','mc-closure'): implementation.goal_inputs(spec,base)
    hook = getattr(implementation, '_validation_inputs', None)
    supplied = None if _readonly is None else _readonly.inputs(implementation, task, base, _readonly_role)
    if supplied is None:
        if mode in ('scientific-delivery','svj-recipe','llp-plane-recipe'):
            supplied = implementation.inputs_for_spec(spec, base)
        else:
            supplied = hook(task, base, _session) if hook is not None and _session is not None else implementation.inputs(task, base)
    files = [regular(p, base, _session=_session) for p in supplied]
    if mode == 'model-events':
        from . import generation_efficiency
        files.append(regular(generation_efficiency.__file__, base, _session=_session))
        files += [regular(p, base, _session=_session) for p in generation_efficiency.inputs(spec, base)]
    # Some supplied contracts carry a native runtime ceiling inside their input
    # document. Admit that scope before approval, not only when the outer stage
    # supervisor eventually stops the process.
    budget = getattr(implementation, 'execution_seconds', None)
    if budget is not None:
        budget_hook = getattr(implementation, '_validation_execution_seconds', None)
        seconds = (budget_hook(task, base, _session) if budget_hook is not None and _session is not None
                   else budget(task, base))
        if type(seconds) is not int or not 1 <= seconds <= spec['max_seconds']:
            raise ValueError('adapter execution budget exceeds the scientific-study hard ceiling')
        if 'quantitative_check' in spec and seconds + guidance['requirements']['effective']['wall_seconds'] > spec['max_seconds']:
            raise ValueError('adapter and quantitative checking ceilings must fit the same admitted stage wall')
    return list(dict.fromkeys([*files, *goal_inputs]))


def root(value):
    rd = Path(value).expanduser().absolute()
    if any(p.is_symlink() for p in (rd, *rd.parents)) or not rd.is_dir():
        raise ValueError('run directory must exist and not traverse a symlink')
    for p in ('inputs', 'outputs', 'work', 'logs', 'execution_state.json', 'execution_attempt.json'):
        if (rd / p).is_symlink():
            raise ValueError('run state and artifact roots must not be symlinks')
    return rd.resolve()


def make_checkin(spec, plan_sha256, stage=None, *, base=None, rundir=None, method_decision=None):
    generated = (adapter(spec).event_ceiling(spec['task'], base or Path.cwd()) if spec['mode'] == 'model-events' else 0)
    efficiency = {}
    if spec['mode'] == 'model-events':
        from . import generation_efficiency
        efficiency = {'generation_efficiency': generation_efficiency.guidance(spec, base or Path.cwd())}
    from ravel.validation.validate_checkin import with_registered_sections
    return with_registered_sections({'schema_version': 1, 'kind': 'checkin1', 'sections': {
            'i': {'source': spec['source'], 'scope': spec['mode'],
                  **(__import__('ravel.workflow.completion_children', fromlist=['checkin_projection']).checkin_projection(spec['goal_binding'], base or Path.cwd()) if 'goal_binding' in spec else {})},
            'i-b': {'task': spec['task'], 'plan_sha256': plan_sha256, **execution.output_policy_fields(spec), **execution.helper_declaration_fields(stage or {}),
                    **(__import__('ravel.workflow.role_registry', fromlist=['checkin_fields']).checkin_fields(stage or {}, delegated='autonomy' in spec)),
                    **({'placement': __import__('ravel.workflow.placement', fromlist=['checkin']).checkin(Path(stage['cwd']))} if 'execution' in spec and stage else {})},
            'ii': {'deliverable': 'Audited machine quantities and adapter evidence; figures only for declared plottable quantities.',
                   'reference': 'Only supplied, bound references are comparison evidence.'},
            'iii': {**({'quantitative_check': __import__('ravel.workflow.quantitative_predictive_checks', fromlist=['guidance']).guidance(spec['quantitative_check'], base or Path.cwd())} if 'quantitative_check' in spec else {}), 'waypoint': 'One bounded scientific calculation, followed by CHECK-IN 2; no automatic larger run.',
                    **efficiency,
                    **({'autonomy': spec['autonomy'], 'decision_authority': 'machine_under_user_delegation', 'scientific_review_waived': False} if 'autonomy' in spec else {})},
            'iv': {'max_seconds': spec['max_seconds'], 'workers': 1, 'attempts': spec.get('max_attempts', 1), 'new_generated_events': generated},
            'v': [{'id': f'F{i+1}', 'assumption': a} for i, a in enumerate(spec['assumptions'])],
            'vi': [{'mode': m, 'text': t} for m, t in [('answer', 'Approve the exact recipe and assumptions'),
                   ('ask', 'Clarify the scientific inputs'), ('propose', 'Revise the proposal in a new study')]]}},
                   base, context={'spec': spec, 'stage': stage, 'plan_sha256': plan_sha256, 'rundir': rundir, 'method_decision': method_decision})


def stage_outputs(spec):
    return ['outputs', 'work'] if spec['mode'] == 'analyze' and spec['task']['backend'] == 'rivet' else ['outputs']


def _plan_v1(rundir, specification):
    source = regular(specification, Path.cwd())
    spec = read_json(source)
    validate(spec)
    inputs = sorted(set(str(p) for p in task_inputs(spec, source.parent)))
    rd = Path(rundir).expanduser().absolute()
    if any(p.is_symlink() for p in (rd, *rd.parents)):
        raise ValueError('run directory must not traverse symlinks')
    # A typed specification is the explicit intake for these supplied-data studies.
    # An older routed request is never silently reinterpreted.
    _claim_run_directory(rd)
    rd = root(rd)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        atomic_json(rd / SPEC, spec)
        stage = {'stage': 'science', 'command': module_command('ravel.physics.science_worker', rd),
                 'cwd': str(rd), 'inputs': [SPEC, *inputs], 'outputs': stage_outputs(spec), 'depends_on': []}
        binding = execution.plan_stage(rd, stage['stage'], stage['command'], stage['inputs'], stage['outputs'], [], rd)
        proposal = {'schema_version': 1, 'mode': spec['mode'], 'base_dir': str(source.parent),
                    'stages': [stage], 'stage_binding': binding, 'max_seconds': spec['max_seconds'],
                    'max_attempts': 1, 'approval_mode': spec['approval_mode'], 'expert_review': False}
        from .prepared_runtime import capture
        proposal['prepared_runtime'] = capture(binding)
        atomic_json(rd / PLAN, proposal)
        checkin = make_checkin(spec, execution.file_hash(rd / PLAN), rundir=rd)
        from ravel.validation.validate_checkin import validate as check
        errors = check(checkin)
        if errors:
            raise ValueError('; '.join(errors))
        atomic_json(rd / 'inputs/checkin1.json', checkin)
        (rd / 'CHECKIN1.md').write_text('# Bounded scientific study\n\n' + spec['source'] +
            '\n\nReview `inputs/checkin1.json` and `inputs/science.json`. One worker, one attempt, '
            f'{spec["max_seconds"]} seconds. Approval: {spec["approval_mode"]}. '
            'Scripted assent is not expert review. No collision-event generation or paper-reproduction certification.\n'
            + _applicability_notice(spec['mode']))
        if (rd / 'inputs/method-decision.json').exists():
            from .method_selection import refresh_checkin
            refresh_checkin(rd)
        from . import gate_wiring
        gate_wiring.present_steering_policy(rd)
        (rd / 'DEVIATIONS.md').write_text('# Deviations\n\nNone. A changed specification requires a new plan.\n')
    packet(rd, write=True)
    return proposal


def _literal_delegation_spec(spec,base):
    """The single schema1 exception is an authenticated complete calculator."""
    if spec.get('schema_version')!=1 or spec.get('mode')!='literal-calculation':
        raise ValueError('broader legacy scientific delegation requires prospective science/v2')
    from ravel.physics.literal_calculation import validate_parent
    return validate_parent(spec['task'],base)


def _literal_approval_paths(rd):
    spec=read_json(rd/SPEC);p=read_json(rd/PLAN)
    # Input inventory is shared by all v1 studies; delegation semantics remain
    # checked by both literal machine approval producers and validators.
    from . import scientific_autonomy
    paths=[str(regular(v,rd)) for v in (PLAN,SPEC,'inputs/checkin1.json')]
    paths.extend(str(regular(v,p['base_dir'])) for v in task_inputs(spec,p['base_dir']))
    paths.extend(scientific_autonomy.input_paths(spec,rd))
    from . import work_dispatch
    paths.extend(work_dispatch.approval_input_paths(rd))
    from .method_selection import DECISION_PATH
    if (rd / DECISION_PATH).exists(): paths.append(str(rd / DECISION_PATH))
    return list(dict.fromkeys(paths))


def _verify_literal_machine_approval(rd,proposal,spec,receipt):
    _literal_delegation_spec(spec,proposal['base_dir'])
    _keys(receipt,{'schema_version','generated_by','quote','approval_mode','proposal_approval_mode',
        'expert_review','plan_sha256','checkin_sha256','utc','input_fingerprint',
        'authority','delegation','delegate_actor'},'literal calculator machine approval')
    from . import scientific_autonomy
    scientific_autonomy.verify_decision(spec,receipt,rd)
    scientific_autonomy.plan_authority(rd)
    if (type(receipt['schema_version']) is not int or receipt['schema_version']!=3
            or receipt['generated_by']!='ravel.workflow.science.approve_delegated'
            or receipt['approval_mode']!='delegated_machine'
            or receipt['proposal_approval_mode']!=proposal['approval_mode']
            or receipt['expert_review'] is not False
            or receipt['plan_sha256']!=execution.file_hash(rd/PLAN)
            or receipt['checkin_sha256']!=execution.file_hash(rd/'inputs/checkin1.json')
            or receipt['input_fingerprint']!=_approval_fingerprint(_literal_approval_paths(rd))):
        raise ValueError('literal machine approval changed source, scope, resources or authority')


def _approve_literal_delegated(rd):
    from . import scientific_autonomy
    from .launch_authorization import operational_utc
    from ravel.validation.validate_checkin import validate as check
    with file_lock(rd/'logs/science.lock',blocking=False):
        p=verify_plan(rd);spec=read_json(rd/SPEC)
        _literal_delegation_spec(spec,p['base_dir'])
        d=scientific_autonomy.plan_authority(rd)
        if (rd/APPROVAL).exists():raise ValueError('approval already recorded; preserve original receipt')
        from . import gate_wiring
        refusal=gate_wiring.plan_approval_refusal(rd,'delegated_machine')
        if refusal:raise ValueError(refusal)
        from .completion_budget import reserve_delegated
        reserve_delegated(spec, d, rd)
        errors=check(read_json(rd/'inputs/checkin1.json'))
        if errors:raise ValueError('; '.join(errors))
        receipt={'schema_version':3,'generated_by':'ravel.workflow.science.approve_delegated',
            'quote':d['value']['quote'],'approval_mode':'delegated_machine',
            'proposal_approval_mode':p['approval_mode'],'expert_review':False,
            'plan_sha256':execution.file_hash(rd/PLAN),
            'checkin_sha256':execution.file_hash(rd/'inputs/checkin1.json'),
            'utc':operational_utc(),'input_fingerprint':_approval_fingerprint(_literal_approval_paths(rd)),
            'authority':'delegated_machine',
            'delegation':scientific_autonomy._run_document(rd)[1]['autonomy'],
            'delegate_actor':d['value']['delegate_actor']}
        intended=deepcopy(receipt)
        _register_approval(rd,deepcopy(intended),authority='delegated_machine',reapproval=False,
                           fingerprint=lambda:_approval_fingerprint(_literal_approval_paths(rd)))
        verify_plan(rd,approved=True)
        if scientific_autonomy.plan_authority(rd)!=d or read_json(rd/APPROVAL)!=intended:
            raise ValueError('literal machine decision changed before return')
    packet(rd,write=True)
    return 0


def _verify_plan_v1(rundir, approved=False):
    rd = root(rundir)
    proposal, spec = read_json(rd / PLAN), read_json(rd / SPEC)
    validate(spec)
    from .prepared_runtime import validate_plan
    validate_plan(proposal)
    inputs = [SPEC, *sorted(set(str(p) for p in task_inputs(spec, proposal['base_dir'])))]
    stage = {'stage': 'science', 'command': module_command('ravel.physics.science_worker', rd),
             'cwd': str(rd), 'inputs': inputs, 'outputs': stage_outputs(spec), 'depends_on': []}
    if proposal['stages'] != [stage] or proposal['mode'] != spec['mode']:
        raise ValueError('study plan or scientific input inventory changed')
    if proposal['max_seconds'] != spec['max_seconds'] or proposal['max_attempts'] != 1 or proposal['approval_mode'] != spec['approval_mode']:
        raise ValueError('study budget or approval mode changed')
    binding = execution.plan_stage(rd, stage['stage'], stage['command'], inputs, stage['outputs'], [], rd)
    if binding != proposal['stage_binding']:
        raise ValueError('stale study: runtime, source or scientific input bytes changed')
    from . import work_dispatch
    if work_dispatch.checkin_content(read_json(rd / 'inputs/checkin1.json'), rd) != make_checkin(spec, execution.file_hash(rd / PLAN), rundir=rd):
        raise ValueError('check-in does not describe the current scientific proposal')
    if approved:
        receipt = read_json(rd / APPROVAL)
        if receipt.get('schema_version')==3:
            _verify_literal_machine_approval(rd,proposal,spec,receipt)
        elif (receipt.get('plan_sha256') != execution.file_hash(rd / PLAN)
                or receipt.get('checkin_sha256') != execution.file_hash(rd / 'inputs/checkin1.json')
                or receipt.get('approval_mode') != spec['approval_mode'] or not receipt.get('quote', '').strip()
                or receipt.get('expert_review') is not False
                or ('input_fingerprint' in receipt and receipt['input_fingerprint'] != _approval_fingerprint(approval_input_paths(rd)))):
            raise ValueError('missing or stale study approval')
    return proposal


APPROVAL_ARCHIVE = 'inputs/science-approvals'


def _admit_approval(rd, authority):
    """Decide, before any receipt is written, whether this approval may be recorded.

    A first approval needs the authority every pending steering event permits. A later one is a
    reapproval: it is admitted only while steering holds the study for reapproval, so an
    approved study without such a hold keeps its one receipt. Returns True for a reapproval."""
    from . import gate_wiring
    reapproval = (rd / APPROVAL).exists()
    if reapproval and not gate_wiring.steering_errors(rd):
        raise ValueError('approval already recorded; preserve the original receipt')
    refusal = gate_wiring.plan_approval_refusal(rd, authority)
    if refusal:
        raise ValueError(refusal)
    return reapproval


def _archive_approval(rd, transaction):
    """Keep the receipt a reapproval replaces: its exact bytes stay under ``inputs/science-approvals``
    and the registration records the supersession. Nothing is deleted; the new receipt becomes current."""
    import hashlib
    raw = (rd / APPROVAL).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    archive = rd / APPROVAL_ARCHIVE
    archive.mkdir(parents=True, exist_ok=True)
    kept = sorted(archive.glob('*.json'))
    path = next((p for p in kept if p.read_bytes() == raw), None)
    if path is None:
        path = archive / f'{len(kept) + 1:04d}-{digest[:12]}.json'
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        transaction['created'].append(path)
    transaction['superseded'] = (digest, path.relative_to(rd).as_posix())


def _operator_reapproval(rd, proposal, scripted):
    """An operator's quoted reapproval of an approved scripted study: admitted whatever the
    proposal's scripted mode, while steering holds the study (``_admit_approval``). The receipt keeps
    the proposal's mode, the replaced scripted receipt stays in the archive, and custody records
    the operator's authority."""
    return not scripted and proposal['approval_mode'] == 'scripted_yes' and (rd / APPROVAL).exists()


def _register_approval(rd, receipt, *, authority, reapproval, fingerprint, details=None):
    """Write the approval receipt as one steering transaction (``plan_approval_transaction``).

    The final authority check, the check that CHECK-IN 1 presents the current policy, the bindings
    of the receipt, the archive of a replaced receipt, the receipt and its registration are decided
    together; a refusal leaves the previous current receipt (or none) in place."""
    from . import gate_wiring
    with gate_wiring.plan_approval_transaction(rd, rd / APPROVAL, authority=authority, details=details) as transaction:
        policy = gate_wiring.steering_policy(rd)
        if policy is not None and read_json(rd / 'inputs/checkin1.json').get('sections', {}).get('steering_policy') != policy:
            raise ValueError('CHECK-IN 1 does not present the current custody steering policy')
        if (receipt['plan_sha256'] != execution.file_hash(rd / PLAN)
                or receipt['checkin_sha256'] != execution.file_hash(rd / 'inputs/checkin1.json')
                or receipt['input_fingerprint'] != fingerprint()):
            raise ValueError('the plan, CHECK-IN 1 or approved inputs changed before the approval was recorded')
        if reapproval:
            _archive_approval(rd, transaction)
        atomic_json(rd / APPROVAL, receipt)
    from .research_launch import produce_if_required
    produce_if_required(rd)


def _approve_v1(rundir, quote, *, scripted=False):
    rd = root(rundir)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        p = verify_plan(rd)
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError('actual assent text required')
        operator = _operator_reapproval(rd, p, scripted)
        if not operator and scripted != (p['approval_mode'] == 'scripted_yes'):
            raise ValueError('approval mode must match the proposal; scripted assent is not expert review')
        authority = 'scripted_experiment' if scripted else 'unknown'
        reapproval = _admit_approval(rd, authority)
        from ravel.validation.validate_checkin import validate as check
        errors = check(read_json(rd / 'inputs/checkin1.json'))
        if errors:
            raise ValueError('; '.join(errors))
        from .approval_authority import classify
        _register_approval(rd, {'authority': classify(scripted=scripted, quote=quote),
            'schema_version': 1, 'quote': quote, 'approval_mode': p['approval_mode'],
            'expert_review': False, 'plan_sha256': execution.file_hash(rd / PLAN),
            'checkin_sha256': execution.file_hash(rd / 'inputs/checkin1.json'), 'utc': execution.utc_now(),
            'input_fingerprint': _approval_fingerprint(approval_input_paths(rd))},
            authority=authority, reapproval=reapproval, fingerprint=lambda: _approval_fingerprint(approval_input_paths(rd)),
            details={'proposal_approval_mode': p['approval_mode']} if operator else None)
    packet(rd, write=True)
    return 0


def _verify_worker_v1(rundir):
    rd = root(rundir)
    p = verify_plan(rd, approved=True)
    attempt = read_json(rd / 'execution_attempt.json')
    record = execution.load_execution(rd)['stages'].get('science', {})
    if (attempt.get('attempt') != 1 or attempt.get('plan_sha256') != execution.file_hash(rd / PLAN)
            or attempt.get('budget_seconds') != p['max_seconds']
            or record.get('status') != 'running' or record.get('supervisor_pid') != os.getppid()
            or record.get('child_pid') not in (None, os.getpid())
            or record.get('fingerprint') != p['stage_binding']['fingerprint']):
        raise ValueError('scientific worker requires its current approved supervised attempt')
    return p


def _packet_v1(rundir, *, write=False):
    rd = root(rundir)
    errors, status, mode = [], 'planned', None
    try:
        p = verify_plan(rd)
        mode = p['mode']
        if (rd / APPROVAL).exists():
            verify_plan(rd, approved=True)
            status = 'approved'
        if (rd / 'execution_attempt.json').exists():
            verify_plan(rd, approved=True)
            attempt = read_json(rd / 'execution_attempt.json')
            if (attempt.get('attempt') != 1 or attempt.get('plan_sha256') != execution.file_hash(rd / PLAN)
                    or attempt.get('budget_seconds') != p['max_seconds']):
                raise ValueError('execution-attempt identity or budget differs from the approved plan')
            running = execution.load_execution(rd)['stages'].get('science', {})
            if running.get('status') == 'running':
                status = 'running'
                raise RunningStudy()
            errors += execution.validate_completed_execution(rd, p['stages'])
            status = 'failed' if errors else 'completed'
            if not errors:
                result = read_json(rd / 'outputs/result.json')
                if result.get('status') != 'passed' or result.get('physics_validated') is not False:
                    errors.append('scientific adapter postconditions did not pass')
                verification = read_json(rd / 'outputs/verification.json')
                if (verification.get('passed') is not True or verification.get('scope') != mode
                        or verification.get('physics_validated') is not False
                        or verification.get('expert_review') is not False
                        or verification.get('result_sha256') != execution.file_hash(rd / 'outputs/result.json')):
                    errors.append('scientific verification did not pass or does not bind the delivered result')
                from ravel.validation.claim_checks import science_errors
                errors += science_errors(rd, mode, [rd / value for value in p['stages'][0]['outputs']])
                from ravel.validation.validate_checkin import validate as check
                errors += check(read_json(rd / 'outputs/checkin2.json'))
                from ravel.workflow.review_enforcement import delivery_errors
                errors += delivery_errors(rd)
    except RunningStudy:
        pass
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
        status = 'invalid'
    if errors and status == 'completed':
        status = 'failed'
    result = {'schema_version': 1, 'rundir': str(rd), 'task_mode': mode, 'execution': {'status': status},
              'lifecycle_verdict': 'PASS' if status == 'completed' else 'FAIL' if errors else 'PENDING',
              'errors': errors, 'next_required': {'planned': 'Review and approve CHECK-IN 1',
                  'approved': 'Run one supervised attempt', 'completed': 'Review CHECK-IN 2 before any new study',
                  'running': 'Wait for the owned supervised worker; do not start another attempt',
                  'failed': 'Inspect retained failure; changed/retried work needs a new plan',
                  'invalid': 'Resolve stale or missing artifacts without overwriting evidence'}[status],
              'physics_validated': False, 'scope': 'Bounded scientific adapter delivery, not scientific closure or independent review'}
    if write:
        atomic_json(rd / 'current_state.json', result)
    return result


class RunningStudy(Exception):
    """Internal control flow: an active study is not a failed completed study."""


def _steering_admission(rd):
    """Steering refuses a held, vetoed or paused study before its attempt token is written; the
    supervisor decides again, under the steering lock, at the launch itself."""
    from . import gate_wiring
    allowed, reason = gate_wiring.dispatch_permitted(rd, 'science')
    if not allowed:
        raise ValueError('scientific launch refused by steering: ' + reason)


REFUSED_ATTEMPTS = 'logs/science-attempts/refused'


def _never_launched(record):
    """The supervisor's attempt record of a launch steering refused before any process existed."""
    refusal = record.get('prelaunch_refusal') if type(record) is dict else None
    return (type(refusal) is dict and refusal.get('by') == 'steering' and record.get('status') == 'failed'
            and record.get('child_pid') is None)


def _attempt_spent(rd):
    """The study's attempt is spent by a token or by any supervised attempt that may have launched.

    A token is written before the supervisor's final admission and withdrawn only when that
    admission refused the launch; an attempt steering refused before its process existed is kept
    in the records but spends nothing."""
    if (rd / 'execution_attempt.json').exists():
        return True
    if not (rd / execution.STATE_NAME).exists():
        return False
    stages = execution.load_execution(rd)['stages']
    return bool(stages) and not (set(stages) == {'science'} and _never_launched(stages['science']))


def _release_refused_attempt(rd, attempt):
    """Withdraw the reserved token when the supervisor's final admission refused the launch.

    The token (and its journal entry) move byte for byte under ``logs/science-attempts/refused``;
    the supervisor's attempt record keeps the refusal. Any other outcome keeps the attempt spent."""
    record = execution.load_execution(rd)['stages'].get('science')
    token = rd / 'execution_attempt.json'
    if not _never_launched(record) or not token.is_file() or read_json(token) != attempt:
        return False
    archive = rd / REFUSED_ATTEMPTS
    archive.mkdir(parents=True, exist_ok=True)
    journal = rd / 'logs/science-attempts' / f'{attempt["attempt"]:08d}.json'
    if journal.is_file():
        os.replace(journal, archive / f'{record["attempt_id"]}.journal.json')
    os.replace(token, archive / f'{record["attempt_id"]}.token.json')
    return True


def _run_v1(rundir, *, resume=False):
    rd = root(rundir)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        p = verify_plan(rd, approved=True)
        if _attempt_spent(rd):
            if resume and packet(rd)['lifecycle_verdict'] == 'PASS':
                from ravel.workflow.review_enforcement import before_stage
                s = p['stages'][0]
                before_stage(rd, s['stage'], s['command'], s['inputs'], s['outputs'], [],
                             str(rd), 'logs/science-worker.log', resume=True)
                return 0
            raise ValueError('the one approved attempt is spent; --resume only verifies valid completed work')
        # Refuse an already active scientific review before consuming the only
        # attempt. The supervisor repeats admission at its actual launch boundary.
        _steering_admission(rd)
        from ravel.workflow.review_enforcement import before_stage
        s = p['stages'][0]
        before_stage(rd, s['stage'], s['command'], s['inputs'], s['outputs'], [],
                     str(rd), 'logs/science-worker.log')
        attempt = {'attempt': 1, 'plan_sha256': execution.file_hash(rd / PLAN),
                   'budget_seconds': p['max_seconds'], 'started_utc': execution.utc_now()}
        atomic_json(rd / 'execution_attempt.json', attempt)
        from ravel.workflow.stage_supervisor import supervise
        code = supervise(s['stage'], str(rd), 0, 'logs/science-worker.log', s['command'],
            kill_secs=p['max_seconds'], poll=.2, grace=2, inputs=s['inputs'], outputs=s['outputs'], depends_on=[], cwd=str(rd))
        _release_refused_attempt(rd, attempt)
    state = packet(rd, write=True)
    return code or (0 if state['lifecycle_verdict'] == 'PASS' else 3)


def _keys(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names):
        raise ValueError(label + ' requires exactly ' + ', '.join(sorted(names)))


def _v2_approval_keys(approval, label):
    """Version-two approval fields; ``authority`` is optional for older receipts."""
    names = {'schema_version', 'generated_by', 'quote', 'approval_mode', 'expert_review',
             'plan_sha256', 'checkin_sha256', 'utc', 'input_fingerprint'}
    _keys(approval, names | ({'authority'} if isinstance(approval, dict) and 'authority' in approval else set()), label)
    from .approval_authority import AUTHORITIES
    if 'authority' in approval and approval['authority'] not in AUTHORITIES:
        raise ValueError(label + ' has an invalid authority label')


def _pointer(value, document):
    if not isinstance(value, str) or not value.startswith('/') or '~' in value:
        raise ValueError('mutable fields require unescaped JSON pointers to existing numeric leaves')
    parts = value[1:].split('/')
    current = document
    for part in parts:
        if not part or part.startswith('max_') or part in ('schema_version', 'limits', 'workers', 'attempts',
                                'runtime', 'process', 'topology', 'backend', 'domain', 'operation', 'units', 'unit', 'executable'):
            raise ValueError('fixed semantics and resource fields cannot be mutable')
        if isinstance(current, list) and part.isdecimal():
            index = int(part)
            if index >= len(current):
                raise ValueError('mutable field does not identify an existing leaf: ' + value)
            current = current[index]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise ValueError('mutable field does not identify an existing leaf: ' + value)
    if type(current) not in (int, float) or not math.isfinite(current):
        raise ValueError('mutable fields must be existing finite numeric leaves: ' + value)
    return parts, current


def _set_pointer(document, parts, value):
    target = document
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    target[int(parts[-1]) if isinstance(target, list) else parts[-1]] = value


def _numeric_delta(original, current, fields):
    projected = deepcopy(original)
    for pointer in fields:
        parts, _ = _pointer(pointer, original)
        _, value = _pointer(pointer, current)
        _set_pointer(projected, parts, value)
    if execution.digest(projected) != execution.digest(current):
        raise ValueError('correction changes fixed recipe fields or input structure')


def _field_list(fields, document):
    if not isinstance(fields, list) or any(not isinstance(p, str) for p in fields) or len(fields) != len(set(fields)):
        raise ValueError('mutable fields must be a distinct list')
    for pointer in fields:
        _pointer(pointer, document)


def _slot(document, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/') or '~' in pointer:
        raise ValueError('input slots require unescaped JSON pointers')
    parts = pointer[1:].split('/')
    target = document
    for part in parts:
        if not part or not isinstance(target, dict) or part not in target:
            raise ValueError('input slot must identify an existing task file path')
        target = target[part]
    if not isinstance(target, str) or not target.strip():
        raise ValueError('input slot must identify an existing task file path')
    return parts, target


def validate_review_contract(spec):
    from . import physics_review
    wrapper = spec['review_policy']
    _keys(wrapper, {'schema_version', 'policy', 'correction_contract'}, 'science review policy')
    if type(wrapper['schema_version']) is not int or wrapper['schema_version'] != 1:
        raise ValueError('science review policy schema_version must be integer 1')
    errors = physics_review.validate_policy(wrapper['policy'])
    if errors:
        raise ValueError('; '.join(errors))
    policy, contract = wrapper['policy'], wrapper['correction_contract']
    _keys(contract, {'task_fields', 'input_slots'}, 'correction contract')
    _field_list(contract['task_fields'], spec['task'])
    slots = contract['input_slots']
    if not isinstance(slots, list):
        raise ValueError('input_slots must be a list')
    paths, pointers = [], []
    for slot in slots:
        _keys(slot, {'task_path', 'run_path', 'fields'}, 'mutable input slot')
        _slot(spec['task'], slot['task_path'])
        path = Path(slot['run_path'])
        if (path.as_posix() != slot['run_path'] or len(path.parts) != 3
                or path.parts[:2] != ('inputs', 'science-mutable') or path.suffix != '.json'
                or any(p in ('.', '..') for p in path.parts)):
            raise ValueError('mutable copies require inputs/science-mutable/<name>.json')
        if not isinstance(slot['fields'], list) or not slot['fields']:
            raise ValueError('mutable input copies require explicit numeric fields')
        paths.append(slot['run_path'])
        pointers.append(slot['task_path'])
    if len(set(paths)) != len(paths) or len(set(pointers)) != len(pointers):
        raise ValueError('mutable input slots and copied paths must be distinct')
    expected_paths = set(paths) | ({EXECUTION_TASK} if contract['task_fields'] else set())
    if (set(policy['allowed_changed_paths']) != expected_paths or policy['allowed_stages'] != ['science']
            or type(spec['max_attempts']) is not int or spec['max_attempts'] != 1 + policy['max_redos']):
        raise ValueError('review policy paths, science stage or prospective attempt budget differs from correction contract')
    if policy['max_redos'] and not expected_paths:
        raise ValueError('a redo budget requires an explicit numeric correction envelope')


def _new_capability(spec):
    if spec['mode'] == 'ml-training': return True
    if spec['mode']=='manuscript-build':return True
    if spec['mode'] in AMPLITUDE_MODES:return True
    if spec['mode']=='reco-ntuple-routine':return True
    if spec['mode']=='tree-array-export':return True
    if spec['mode']=='chargino-decay-table':return True
    if spec['mode']=='mssm-observable-map':return True
    if spec['mode']=='nmssm-yukawa-map':return True
    if spec['mode']=='width-inputs':return True
    if spec['mode'] in ('published-classifier','analysis-response-features','classifier-inputs'):return True
    if spec['mode'] in ('svj-recipe','llp-plane-recipe'):return True
    if spec['mode'] in ('research-comparison','quantitative-predictive'):return True
    if spec['mode']=='task-completion-context':return True
    if spec['mode'] == 'model-events': return True
    if spec['mode']=='joint-score':return True
    if spec['mode']=='resonance-width':return True
    if spec['mode'] in ('columnar-analysis', 'authored-analysis'):return True
    if spec['mode'] in ('lhe-transform', 'generation-reconciliation'):return True
    if spec['mode'] == 'event-production': return True
    if spec['mode'] in ('formula-grid', 'coupling-morphing', 'prescribed-statistic', 'search-statistics', 'differential-likelihood'):return True
    if spec['mode'] in ('cross-section', 'simplified-spectrum', 'resonance-lineshape', 'model-authoring'):return True
    if spec['mode'] == 'figure-comparison':return True
    return (spec['mode'] in ('contrast', 'statistical-model', 'published-model', 'model-portfolio', 'likelihood-parity', 'numerical-reference-check', 'cosmology-solver', 'cosmic-evolution',
                            'signal-template', 'stau-events', 'native-likelihood', 'full-auxiliary-calibration', 'background-discrete-profile', 'eft-functions',
                            'normalized-measurement', 'continuous-fit', 'native-statistical-construction', 'model-inputs', 'contur-import',
                            'ratio-measurement', 'group-normalization', 'group-composition', 'source-tables', 'scientific-delivery', 'published-summary', 'native-group-acquisition', 'retained-shower', 'derived-quantities', 'finite-mc', 'pdf-variations', 'model-sources', 'model-tool-bridge', 'generated-spectrum',
                            'model-provider-bridge', 'model-derivation-bridge', 'model-ward', 'mpi-observer', 'initialized-settings-qualification', 'initialized-settings-retained', 'mpi-paired-effect', 'likelihood-profile-probe', 'likelihood-candidate-check', 'likelihood-step-refinement', 'cr-signal-qualification', 'joint-fit', 'joint-qualification', 'joint-score', 'hs3-likelihood', 'workspace-combination-study', 'diagrammatica-code', 'symbolic-evaluation', 'feyn-graph', 'diagram-analysis', 'feynarts-amplitude', 'checkmate-events', 'sfitter-native-fit', 'sfitter-scan-extraction', 'sfitter-observed-events', 'eft-convention-transport', 'eft-toolchain', 'finite-integrals', 'parameter-space-sampling', 'dataset-query-quantities', 'ntuple-inventory', 'mc-expected-construction', 'asimov-sensitivity', 'mc-closure', 'root-stream', 'contur-yoda', 'contur-companion', 'ma5-saf', 'ma5-pad') or spec['mode'] == 'analyze' and spec['task'].get('backend') in ('analysis-ir', 'routine-build', 'rivet-built', 'simpleanalysis-built', 'routine-candidate','native-construction','agentrivet-source')
            or spec['mode'] == 'analyze' and spec['task'].get('backend') == 'rivet' and ('native_weight_cap' in spec['task'] or 'centrality_preload' in spec['task'] or 'nominal_weight' in spec['task'])
            or spec['mode'] == 'domain' and spec['task'].get('domain') in {'model-probe', 'detector-response'})


def review_enabled(rundir):
    rd = root(rundir)
    p = read_json(regular(PLAN, rd))
    if type(p.get('schema_version')) is not int or p['schema_version'] not in (1, 2):
        raise ValueError('invalid science plan version')
    if p['schema_version'] == 1:
        if (rd / REVIEW_POLICY).exists() or read_json(rd / SPEC).get('schema_version') != 1:
            raise ValueError('legacy study cannot acquire a prospective review envelope after planning')
        return False
    return True


def _stage(rd, inputs, number, *, correction_sha256=None, output_policy=None, base_dir=None, _session=None):
    args = [str(rd), '--attempt', str(number)]
    if correction_sha256 is not None:
        args += ['--correction-sha256', correction_sha256]
    stage={'stage': 'science', 'command': module_command('ravel.physics.science_worker', *args),
            'cwd': str(rd), 'inputs': list(inputs), 'outputs': [f'outputs/attempt-{number}'],
            'depends_on': [], 'log': f'logs/science-worker-{number}.log',
            **({'output_policy': deepcopy(output_policy)} if output_policy is not None else {})}
    read=_session.read_document if _session is not None else read_json
    spec=read(rd/SPEC)
    hook=getattr(adapter(spec),'helper_declaration',None) if spec['mode']!='quantities' else None
    if hook is not None:
        task=read(rd/EXECUTION_TASK)['task']
        base_dir=base_dir if base_dir is not None else read(rd/PLAN)['base_dir']
        out=rd/stage['outputs'][0]
        declared=hook(task,base_dir,out,_session=_session)
        if declared is not None:
            execution.helper_declaration_fields({'helper_declaration':declared})
            for row in declared['helpers']:
                if Path(row['request_root'])==out or not Path(row['request_root']).is_relative_to(out):
                    raise ValueError('registered helper root is outside the scientific attempt output')
            stage['helper_declaration']=declared
            for path in execution.helper_input_paths(declared,_session=_session):
                if path not in stage['inputs']:stage['inputs'].append(path)
    if 'execution' in spec:
        _place(rd, spec, stage, number)
    return stage


def _place(rd, spec, stage, number):
    """Make a placed stage's command the backend worker of its pinned plan."""
    from . import placement
    if number != 1 or 'helper_declaration' in stage or getattr(adapter(spec), 'owner_limits', None) is not None:
        raise ValueError('placement supports one attempt without registered helpers or operation owner limits')
    if placement.PLAN not in stage['inputs']:
        raise ValueError('a placed science stage pins its backend plan as an input')
    plan = Path(rd) / placement.PLAN
    if plan.exists():
        placement.verify(rd, 'science', stage['command'], stage['outputs'], spec['execution']['backend_plan'],
                         spec['max_seconds'])
    else:
        placement.pin(rd, 'science', stage['command'], stage['outputs'], spec['execution']['backend_plan'],
                      spec['max_seconds'])
    stage['command'] = placement.worker_command(rd, 'science')


def _placement_inputs(spec):
    from .placement import PLAN as placement_plan
    return [placement_plan] if 'execution' in spec else []


_PLANNING_CALLABLES = (task_inputs, _stage)


def _planning_prospective_owner(rundir):
    # Eligibility is observational only. Unsupported/nonprospective destinations
    # retain the original input-before-path/refusal ordering.
    if not all(actual is owner for actual, owner in zip((task_inputs, _stage), _PLANNING_CALLABLES)):
        return None
    try:
        rd = Path(rundir).expanduser().absolute()
        if rd.exists() or any(p.is_symlink() for p in (rd, *rd.parents)):
            return None
        return rd
    except (OSError, ValueError, TypeError):
        return None


@contextmanager
def _planning_validation_scope(rd, *tracked, prospective=False, _input_inventories=None):
    """One pure planning phase; no observed fact crosses a setup write."""
    if rd is None:
        yield None
        return
    session = execution._validation_session(rd)
    try:
        for value in tracked:
            session.track(value)
        if prospective:
            session.observe_exists(rd)
        yield session
        # Explicit complete terminal tail AFTER every retained callback. The
        # original default finish()/public authority scope remains untouched.
        session.readonly_freeze()
        session.readonly_drain()
        session.readonly_terminal()
        # Canonical task_inputs returns Path values. Preserve their exact type,
        # order and lexical value without sending Path objects to JSON track().
        # Check the actual retained list after every callback and terminal read.
        for current, expected in _input_inventories or ():
            if tuple((type(path), str(path)) for path in current) != expected:
                raise ValueError('planning input inventory changed during validation')
    finally:
        session.close()


def _is_held_dir(rd):
    rd = Path(rd)
    return (rd.is_dir() and not rd.is_symlink() and (rd / HELD).is_file()
            and not (rd / PLAN).exists() and not (rd / SPEC).exists())


def _claim_run_directory(rd):
    """Create a fresh run directory, or take over a held one by archiving its record."""
    if _is_held_dir(rd):
        archive = rd / 'inputs/held'
        archive.mkdir(parents=True, exist_ok=True)
        count = len(list(archive.glob('science-held*.json')))
        suffix = '' if count == 0 else f'-{count}'
        os.replace(rd / HELD, archive / f'science-held{suffix}.json')
        if (rd / 'CHECKIN1.md').is_file():
            os.replace(rd / 'CHECKIN1.md', archive / f'CHECKIN1{suffix}.md')
        return
    if rd.is_dir() and not rd.is_symlink():
        from . import gate_wiring
        entries = list(rd.rglob('*'))
        allowed = ('inputs/steering/', 'inputs/user-steering/')
        administrative = all(not p.is_symlink() and (
            p.relative_to(rd).as_posix() in ('inputs', 'inputs/steering', 'inputs/user-steering')
            or p.relative_to(rd).as_posix().startswith(allowed)) for p in entries)
        if administrative and gate_wiring.steering_policy(rd) is not None:
            return  # Initial policy custody is not an old scientific run.
    rd.mkdir(parents=True, exist_ok=False)
    from . import gate_wiring
    gate_wiring.initialize_steering(rd, route='study-plan')


_PATH_SUFFIX = __import__('re').compile(r'\.[A-Za-z][A-Za-z0-9]{0,9}')


def _named_missing_paths(task, base):
    """Path-like task values that do not exist; output locations are not inputs."""
    found = []
    def walk(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif (isinstance(value, str) and 'output' not in key.lower() and 0 < len(value) < 4096
              and not any(c.isspace() for c in value)
              and ('/' in value or _PATH_SUFFIX.fullmatch(Path(value).suffix or ''))):
            p = Path(value).expanduser()
            p = p if p.is_absolute() else Path(base) / p
            try:
                if not any(part.is_symlink() for part in (p, *p.parents)) and not p.exists():
                    found.append(str(p))
            except OSError:
                pass
    walk(task)
    return found


def _classify(exc):
    if isinstance(exc, MissingInput):
        return {'kind': 'input', 'reason': 'missing', 'path': exc.path}
    if isinstance(exc, MissingPrerequisite):
        return {'kind': 'prerequisite', 'reason': 'missing', 'item': str(exc)}
    if isinstance(exc, ImportError):
        name = getattr(exc, 'name', None) or str(exc)
        return {'kind': 'prerequisite', 'reason': 'missing', 'item': f'Python package {name} is not installed'}
    if isinstance(exc, FileNotFoundError) and exc.filename:
        return {'kind': 'input', 'reason': 'missing', 'path': str(exc.filename)}
    return None


def _unmet_items(spec, base, exc):
    """The unmet inputs and prerequisites behind a planning failure, or None."""
    first = _classify(exc)
    if first is None:
        # A validation session reports a missing file like any other changed path.
        # Re-run the plain inventory to learn whether the input is simply absent.
        try:
            validate(spec)
            task_inputs(spec, base)
        except (ValueError, OSError, ImportError) as again:
            first = _classify(again)
        except Exception:
            return None
    if first is None:
        return None
    items = [first]
    if first['kind'] == 'input':
        seen = {first['path']}
        for path in _named_missing_paths(spec.get('task'), base):
            if path not in seen:
                seen.add(path)
                items.append({'kind': 'input', 'reason': 'missing', 'path': path})
    return items


def _write_held(rundir, source, spec, unmet):
    rd = Path(rundir).expanduser().absolute()
    if any(p.is_symlink() for p in (rd, *rd.parents)):
        raise ValueError('run directory must not traverse symlinks')
    if not _is_held_dir(rd):
        rd.mkdir(parents=True, exist_ok=False)
        from . import gate_wiring
        gate_wiring.initialize_steering(rd, route='study-plan')
    rd = root(rd)
    labels = [u.get('path') or u.get('item') for u in unmet]
    flags = [{'id': f'F{i + 1}', 'item': label, 'kind': u['kind'], 'reason': u['reason'],
              'ask': ('Supply this file at the stated path' if u['kind'] == 'input'
                      else 'Provision this prerequisite, or name an alternative')}
             for i, (u, label) in enumerate(zip(unmet, labels))]
    command = f'ravel plan --rundir {rd} --spec {source}'
    checkin = {'schema_version': 1, 'kind': 'checkin1', 'status': 'held', 'sections': {
        'i': {'request': spec.get('source'), 'scope': spec.get('mode'),
              'summary': f'The {spec.get("mode")} study is ready to plan once the items below are available.'},
        'iv': {'plan': f'After the items are supplied, `{command}` writes the concrete plan for approval.',
               'compute': 'No compute has run.'},
        'v': flags,
        'vi': [{'mode': 'answer', 'text': 'Supply the listed items and re-run the plan command'},
               {'mode': 'ask', 'text': 'Ask about any listed item'},
               {'mode': 'propose', 'text': 'Propose different inputs or a different study'}]}}
    record = {'schema_version': 1, 'kind': 'science-held-plan', 'status': 'held', 'mode': spec.get('mode'),
              'specification': {'path': str(source), 'sha256': execution.file_hash(source)},
              'unmet': unmet, 'checkin1': checkin,
              'next_required': f'Supply each unmet item, then run `{command}`',
              'execution_authorized': False, 'physics_validated': False}
    with file_lock(rd / 'logs/science.lock', blocking=False):
        atomic_json(rd / HELD, record)
        lines = [f'# CHECK-IN 1 (held): {spec.get("mode")} study', '', str(spec.get('source', '')), '',
                 'The plan is held until these items are available:', '']
        lines += [f'{f["id"]}. {f["item"]} ({f["kind"]}, {f["reason"]})' for f in flags]
        lines += ['', f'Supply them, then run `{command}`. The concrete plan and its approval follow.',
                  'You can also ask about an item or propose different inputs. No compute has run.', '']
        (rd / 'CHECKIN1.md').write_text('\n'.join(lines))
    atomic_json(rd / 'current_state.json', held_packet(rd))
    return {'status': 'held', 'mode': spec.get('mode'), 'rundir': str(rd), 'unmet': unmet,
            'checkin': str(rd / 'CHECKIN1.md'), 'held': str(rd / HELD)}


def held_packet(rundir):
    """Status view of a held study: the unmet items are the next requirement."""
    rd = Path(rundir).absolute()
    record = read_json(rd / HELD)
    return {'schema_version': 1, 'rundir': str(rd), 'task_mode': record.get('mode'),
            'execution': {'status': 'held'}, 'lifecycle_verdict': 'HELD', 'errors': [],
            'unmet': record.get('unmet', []),
            'next_required': {'kind': 'checkin', 'what': 'CHECK-IN 1 (held)',
                              'unmet': [u.get('path') or u.get('item') for u in record.get('unmet', [])],
                              'why': record.get('next_required')},
            'instructions': ['CHECKIN1.md'], 'physics_validated': False,
            'scope': 'Held study plan; no plan, approval or compute exists yet'}


def plan(rundir, specification, *, research_binding=None):
    """Write a concrete plan, or a held CHECK-IN 1 when inputs or prerequisites are absent."""
    source = regular(specification, Path.cwd())
    spec = read_json(source)
    rd = Path(rundir).expanduser().absolute()
    held_before = _is_held_dir(rd)
    try:
        result = _plan(rundir, specification, source, spec, research_binding=research_binding)
        from .research_admission import admission
        errors = admission(rd, 'plan', bind=True)
        if errors: raise ValueError('; '.join(errors))
        if 'goal_binding' in spec:
            from .completion_children import register_child
            register_child(rundir, spec['goal_binding'], run_kind='science')
        return result
    except (ValueError, OSError, ImportError) as exc:
        # The version refusal precedes every input: the held-plan pass must not inventory for it.
        if isinstance(exc, (FileExistsError, LegacyPolicyRefusal)) or (rd.exists() and not held_before) or (
                held_before and not _is_held_dir(rd)) or not isinstance(spec, dict):
            raise
        unmet = _unmet_items(spec, source.parent, exc)
        if unmet is None:
            raise
        return _write_held(rundir, source, spec, unmet)


def _plan(rundir, specification, source, spec, *, research_binding=None):
    validate(spec)
    if spec['schema_version'] == 1:
        if research_binding is not None: raise LegacyPolicyRefusal('research dispatch binding requires a v2 study')
        if _new_capability(spec):
            raise LegacyPolicyRefusal('this capability requires a prospective version 2 science review policy')
        return _plan_v1(rundir, specification)
    prospective = _planning_prospective_owner(rundir)
    input_inventories = []
    with _planning_validation_scope(prospective, spec, prospective=True, _input_inventories=input_inventories) as first:
        supplied_inputs = task_inputs(spec, source.parent, **({'_session': first} if first is not None else {}))
        rd = Path(rundir).expanduser().absolute()
        if any(p.is_symlink() for p in (rd, *rd.parents)):
            raise ValueError('run directory must not traverse symlinks')
        # Validate copied document semantics before consuming a run directory.
        slots, task = [], deepcopy(spec['task'])
        for slot in spec['review_policy']['correction_contract']['input_slots']:
            parts, value = _slot(task, slot['task_path'])
            original = regular(value, source.parent)
            if original not in supplied_inputs:
                raise ValueError('mutable slot is outside the scientific input inventory')
            document = read_json(original)
            _field_list(slot['fields'], document)
            slots.append({**slot, 'source_path': str(original), 'source_sha256': execution.file_hash(original),
                          'baseline': document})
            _set_pointer(task, parts, str(rd / slot['run_path']))
            if first is not None:
                first.require_regular(original)
                first.hash_file(original)
        if first is not None:
            input_inventories.append((supplied_inputs, tuple((type(path), str(path)) for path in supplied_inputs)))
            first.track([str(path) for path in supplied_inputs]); first.track(slots); first.track(task)
    _claim_run_directory(rd)
    rd = root(rd)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        atomic_json(rd / SPEC, spec)
        if research_binding is not None:
            _keys(research_binding, {'root', 'experiment_id'}, 'research binding')
            atomic_json(rd / 'inputs/research-experiment.json', research_binding)
        atomic_json(rd / REVIEW_POLICY, spec['review_policy']['policy'])
        atomic_json(rd / EXECUTION_TASK, {'schema_version': 1, 'task': task})
        for slot in slots:
            destination = rd / slot['run_path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(Path(slot['source_path']).read_bytes())
        with _planning_validation_scope(rd if prospective is not None and all(
                actual is owner for actual, owner in zip((task_inputs, _stage), _PLANNING_CALLABLES)) else None, spec) as second:
            effective = {**spec, 'task': task}
            validate(effective)
            inputs = [SPEC, EXECUTION_TASK, REVIEW_POLICY,
                      *(['inputs/research-experiment.json'] if research_binding is not None else []), *_placement_inputs(spec),
                      *sorted(set(str(p) for p in [*supplied_inputs, *task_inputs(effective, source.parent, **({'_session': second} if second is not None else {}))]))]
            stage = _stage(rd, inputs, 1, base_dir=source.parent, **({'_session': second} if second is not None else {}), **execution.output_policy_fields(spec))
            if second is None:
                binding = execution.plan_stage(rd, 'science', stage['command'], inputs, stage['outputs'], [], rd,
                                               **execution.stage_metadata_fields(stage))
            else:
                binding = _plan_stage(rd, 'science', stage['command'], inputs, stage['outputs'], [], rd, second,
                                      **execution.stage_metadata_fields(stage))
            proposal = {'schema_version': 2, 'mode': spec['mode'], 'base_dir': str(source.parent), 'stages': [stage],
                        'stage_binding': binding, 'max_seconds': spec['max_seconds'], 'max_attempts': spec['max_attempts'],
                        'approval_mode': spec['approval_mode'], 'expert_review': False, 'execution_task': task,
                        'mutable_inputs': slots, 'mutable_paths': spec['review_policy']['policy']['allowed_changed_paths']}
            if research_binding is not None:
                proposal['research_binding'] = deepcopy(research_binding)
            from .prepared_runtime import capture
            proposal['prepared_runtime'] = capture(binding)
            if second is not None:
                second.track(proposal)
        atomic_json(rd / PLAN, proposal)
        atomic_json(rd / 'inputs/checkin1.json', make_checkin(spec, execution.file_hash(rd / PLAN),stage,base=source.parent,rundir=rd))
        (rd / 'CHECKIN1.md').write_text('# Bounded scientific study\n\n' + spec['source'] +
            f'\n\nOne worker, {spec["max_seconds"]} seconds per attempt, {spec["max_attempts"]} prospectively bounded attempts. '
            'Review the exact science plan, copied settings and prospective policy. Scripted assent is not expert review.\n'
            + _applicability_notice(spec['mode'])
            + ('\n' + __import__('ravel.workflow.placement', fromlist=['describe']).describe(rd) if 'execution' in spec else ''))
        if (rd / 'inputs/method-decision.json').exists():
            from .method_selection import refresh_checkin
            refresh_checkin(rd)
        from . import gate_wiring
        gate_wiring.present_steering_policy(rd)
        (rd / 'DEVIATIONS.md').write_text('# Deviations\n\nNone. Numeric repairs require a concrete admitted correction plan.\n')
    packet(rd, write=True)
    return proposal


def approval_input_paths(rundir):
    rd = root(rundir)
    if not review_enabled(rd):
        return _literal_approval_paths(rd)
    paths = [str(regular(p, rd)) for p in (PLAN, SPEC, 'inputs/checkin1.json', REVIEW_POLICY)]
    from . import scientific_autonomy
    paths.extend(scientific_autonomy.input_paths(read_json(rd / SPEC), rd))
    from . import work_dispatch
    paths.extend(work_dispatch.approval_input_paths(rd))
    from .method_selection import DECISION_PATH
    if (rd / DECISION_PATH).exists(): paths.append(str(rd / DECISION_PATH))
    return list(dict.fromkeys(paths))


def _approval_fingerprint(paths):
    from . import provenance
    return provenance.sha256_bytes(''.join(execution.file_hash(p) for p in paths).encode())


@contextmanager
def _validation_scope(rd):
    """One observational check only; never retain hashes across authority phases."""
    session = execution._validation_session(rd)
    try:
        yield session
        errors = session.finish()
        if errors:
            raise ValueError('; '.join(errors))
    finally:
        session.close()


def _plan_stage(rd, stage, command, inputs, outputs, parents, cwd, session, *, output_policy=None, helper_declaration=None):
    # Older injected planners keep their positional seam and independent reads.
    planner = execution.plan_stage
    shared = session is not None and '_session' in inspect.signature(planner).parameters
    kwargs = {'_session': session} if shared else {}
    if output_policy is not None:
        kwargs['output_policy'] = output_policy
    if helper_declaration is not None:
        kwargs['helper_declaration'] = helper_declaration
    if not shared:
        return planner(rd, stage, command, inputs, outputs, parents, cwd, **kwargs)
    execution._check_validation_session(rd, session)
    if not command or any(type(value) is not str or not value for value in command):
        return planner(rd, stage, command, inputs, outputs, parents, cwd, **kwargs)
    request = {'rundir': str(rd), 'stage': stage, 'command': command, 'inputs': inputs,
               'outputs': outputs, 'parents': parents, 'cwd': str(cwd),
               'output_policy': output_policy, 'helper_declaration': helper_declaration}
    def typed(value):
        # JSON-equivalent Python types are not interchangeable declarations:
        # e.g. the original output-policy validator requires a list, not tuple.
        kind = type(value)
        if kind is dict:
            rows = [(typed(k), typed(v)) for k, v in value.items()]
            rows.sort(key=lambda row: execution.digest(row[0]))
            return ['dict', rows]
        if kind in (list, tuple):
            return [kind.__name__, [typed(item) for item in value]]
        if kind in (str, int, float, bool, type(None)):
            return [kind.__name__, value]
        raise TypeError('custom non-JSON request has no typed stage proof')

    try:
        key = ('science-stage-binding', id(planner), execution.digest(typed(request)))
    except (TypeError, ValueError):
        # A custom callable may accept non-JSON arguments. It acquires no proof.
        return planner(rd, stage, command, inputs, outputs, parents, cwd, **kwargs)

    def track_types(value):
        session.track(value)
        before = execution.digest(typed(value))
        def ending_types():
            if execution.digest(typed(value)) != before:
                raise ValueError('supplied state or plan changed types during validation')
        session.retain_final_check(ending_types)

    def observation():
        # The planner implicitly selects these files/paths. Capture membership
        # separately from the session's individual input byte/identity census.
        import shutil
        source_root = Path(execution.__file__).resolve().parents[1]
        source_members = tuple(str(path) for path in sorted(source_root.rglob('*.py')))
        executable = shutil.which(command[0]) if not Path(command[0]).is_absolute() else command[0]
        if not executable or not Path(executable).is_file():
            raise ValueError(f'missing executable: {command[0]}')
        scripts = []
        for arg in command[1:]:
            if arg.startswith('-'):
                continue
            candidate = Path(arg) if Path(arg).is_absolute() else Path(cwd) / arg
            if candidate.suffix in ('.py', '.sh') and candidate.is_file():
                scripts.append(str(candidate.resolve()))
        return (str(source_root), source_members, str(Path(executable).resolve()),
                tuple(scripts), str(Path(cwd).resolve()),
                tuple(str(execution.resolve_path(rd, value, output=True)) for value in outputs))

    previous = session.proofs.get(key)
    if previous is not None:
        owner, binding, observed = previous
        if owner is not planner or observation() != observed:
            raise ValueError('stage source membership or selected paths changed during validation')
        result = deepcopy(binding)
        track_types(request)
        track_types(result)
        return result
    observed = observation()
    binding = planner(rd, stage, command, inputs, outputs, parents, cwd, **kwargs)
    if observation() != observed:
        raise ValueError('stage source membership or selected paths changed while planning')
    # Only this live call owns the proof. Caller mutations cannot change the
    # retained binding, and finish still checks every originally consumed file,
    # ledger/runtime, mutable request and returned object before authority exits.
    binding = deepcopy(binding)
    track_types(request)
    track_types(binding)
    def ending():
        if observation() != observed:
            raise ValueError('stage source membership or selected paths changed before return')
    session.retain_final_check(ending)
    session.proofs[key] = (planner, binding, observed)
    result = deepcopy(binding)
    track_types(result)
    return result


def _verify_v2_common(rd, *, _session=None, _read=None, _readonly=None):
    read = _read if _read is not None else (_session.read_document if _session is not None else read_json)
    p, spec = read(rd / PLAN), read(rd / SPEC)
    validate(spec)
    _keys(p, {'schema_version', 'mode', 'base_dir', 'stages', 'stage_binding', 'max_seconds', 'max_attempts',
              'approval_mode', 'expert_review', 'execution_task', 'mutable_inputs', 'mutable_paths'} | ({'prepared_runtime'} if 'prepared_runtime' in p else set())
          | ({'research_binding'} if 'research_binding' in p else set()), 'science plan')
    from .prepared_runtime import validate_plan
    validate_plan(p)
    if (spec['schema_version'] != 2 or p['schema_version'] != 2 or p['mode'] != spec['mode']
            or p['max_seconds'] != spec['max_seconds'] or p['max_attempts'] != spec['max_attempts']
            or p['approval_mode'] != spec['approval_mode'] or p['expert_review'] is not False
            or read(rd / REVIEW_POLICY) != spec['review_policy']['policy']
            or any((rd / x).exists() for x in ('inputs/native_execution_plan.json', 'inputs/checkin1_approval.json', 'inputs/task_contract.json'))):
        raise ValueError('science plan, prospective policy or immutable envelope changed')
    if 'research_binding' in p:
        if read(rd/'inputs/research-experiment.json') != p['research_binding']:
            raise ValueError('research execution binding changed')
    initial = deepcopy(spec['task'])
    declared_slots = spec['review_policy']['correction_contract']['input_slots']
    if len(p['mutable_inputs']) != len(declared_slots):
        raise ValueError('mutable scientific input inventory changed')
    original_inputs = task_inputs(spec, p['base_dir'], _session=_session,
        **({} if _readonly is None else {'_readonly': _readonly, '_readonly_role': 'original'}))
    for actual, slot in zip(p['mutable_inputs'], declared_slots):
        _keys(actual, {'task_path', 'run_path', 'fields', 'source_path', 'source_sha256', 'baseline'}, 'copied input binding')
        if any(actual[k] != slot[k] for k in slot):
            raise ValueError('copied input correction envelope changed')
        parts, value = _slot(initial, slot['task_path'])
        source = regular(value, p['base_dir'])
        if (str(source) != actual['source_path'] or execution.file_hash(source) != actual['source_sha256']
                or read_json(source) != actual['baseline']):
            raise ValueError('original scientific inputs changed')
        _field_list(slot['fields'], actual['baseline'])
        _set_pointer(initial, parts, str(rd / slot['run_path']))
    if execution.digest(initial) != execution.digest(p['execution_task']):
        raise ValueError('original execution recipe differs from the approved task mapping')
    effective = execution_spec(rd, _proposal=p, _spec=spec, _session=_session)
    expected_inputs = [SPEC, EXECUTION_TASK, REVIEW_POLICY,
                       *(['inputs/research-experiment.json'] if 'research_binding' in p else []), *_placement_inputs(spec),
                       *sorted(set(str(x) for x in [*original_inputs, *task_inputs(effective, p['base_dir'], _session=_session,
                           **({} if _readonly is None else {'_readonly': _readonly, '_readonly_role': 'effective'}))]))]
    stage = _stage(rd, expected_inputs, 1, base_dir=p['base_dir'], _session=_session, **execution.output_policy_fields(spec))
    if p['stages'] != [stage]:
        raise ValueError('study plan or scientific input inventory changed')
    binding = _plan_stage(rd, 'science', stage['command'], expected_inputs, stage['outputs'], [], rd, _session,
                          **execution.stage_metadata_fields(stage))
    original = p['stage_binding']
    mutable = {str(rd / value) for value in p['mutable_paths']} | {str(rd / EXECUTION_TASK)}
    if (binding['command'] != original['command'] or binding['cwd'] != original['cwd']
            or binding['inputs'] != original['inputs'] or binding['outputs'] != original['outputs']
            or binding['parents'] != original['parents'] or binding['runtime'] != original['runtime']
            or execution.stage_metadata_fields(binding) != execution.stage_metadata_fields(original)
            or original['fingerprint'] != execution.digest({k: v for k, v in original.items() if k != 'fingerprint'})
            or {k: v for k, v in binding['input_snapshot'].items() if k not in mutable}
                != {k: v for k, v in original['input_snapshot'].items() if k not in mutable}):
        raise ValueError('stale study: fixed runtime, source or scientific input bytes changed')
    from . import work_dispatch
    if work_dispatch.checkin_content(read(rd / 'inputs/checkin1.json'), rd, session=_session) != make_checkin(spec, execution.file_hash(rd / PLAN),stage,base=p['base_dir'],rundir=rd):
        raise ValueError('check-in does not describe the current scientific proposal')
    return p, spec


def _verify_v2_approval(rd, spec, *, _session=None, _read=None):
    from .method_selection import require_launch
    require_launch(rd, spec=spec)
    read = _read if _read is not None else (_session.read_document if _session is not None else read_json)
    receipt = read(rd / APPROVAL)
    if not isinstance(receipt, dict):
        raise ValueError('science approval requires an object')
    _keys(receipt, {'schema_version', 'generated_by', 'quote', 'approval_mode', 'expert_review', 'plan_sha256',
                    'checkin_sha256', 'utc', 'input_fingerprint'} | ({'authority','delegation','delegate_actor','proposal_approval_mode'} if receipt.get('schema_version')==3 else ({'authority'} if 'authority' in receipt else set())), 'science approval')
    from .approval_authority import AUTHORITIES
    if 'authority' in receipt and receipt['authority'] not in (*AUTHORITIES, 'machine_under_user_delegation'):
        raise ValueError('invalid science approval authority')
    from .launch_authorization import parse_utc
    parse_utc(receipt['utc'])
    delegated_approval=receipt.get('schema_version')==3
    if delegated_approval:
        if type(receipt['schema_version']) is not int:raise ValueError('exact delegated approval version required')
        from . import scientific_autonomy
        scientific_autonomy.verify_decision(spec,receipt,rd)
    if (receipt['schema_version'] != (3 if delegated_approval else 2) or receipt['generated_by'] != ('ravel.workflow.science.approve_delegated' if delegated_approval else 'ravel.workflow.science.approve')
            or receipt['plan_sha256'] != execution.file_hash(rd / PLAN)
            or receipt['checkin_sha256'] != execution.file_hash(rd / 'inputs/checkin1.json')
            or receipt['input_fingerprint'] != _approval_fingerprint(approval_input_paths(rd))
            or receipt['approval_mode'] != ('delegated_machine' if delegated_approval else spec['approval_mode'])
            or (delegated_approval and receipt['proposal_approval_mode']!=spec['approval_mode']) or not isinstance(receipt['quote'], str)
            or not receipt['quote'].strip() or receipt['expert_review'] is not False):
        raise ValueError('missing or stale study approval')


def _verify_v2(rd, *, approved=False, _session=None, _readonly=None):
    read = _session.read_document if _session is not None else read_json
    p, spec = _verify_v2_common(rd, _session=_session, _read=read,
        **({} if _readonly is None else {'_readonly': _readonly}))
    if approved:
        _verify_v2_approval(rd, spec, _session=_session, _read=read)
    return p


def verify_plan(rundir, approved=False, *, _session=None, _recheck=False, _readonly=None):
    rd = root(rundir)
    if approved:
        from .method_selection import require_launch
        require_launch(rd)
    from .research_admission import admission
    errors = admission(rd, 'launch' if approved else 'approve_plan')
    if errors: raise ValueError('; '.join(errors))
    if review_enabled(rd):
        if _session is not None:
            execution._check_validation_session(rd, _session)
            # Reuse a completed source/input proof only inside this observation.
            # read_document/snapshots track its full custody, and finish() still
            # checks every file/inventory, runtime, ledger and returned object.
            key = ('science-v2-plan', bool(approved))
            if not _recheck and key in _session.proofs:
                return _session.proofs[key]
            proposal = _verify_v2(rd, approved=approved, _session=_session,
                **({} if _readonly is None else {'_readonly': _readonly}))
            _session.proofs[key] = proposal
            if approved:
                _session.proofs[('science-v2-plan', False)] = proposal
            return proposal
        with _validation_scope(rd) as session:
            return _verify_v2(rd, approved=approved, _session=session)
    if _new_capability(read_json(rd / SPEC)):
        raise ValueError('this capability requires a prospective version 2 science review policy')
    return _verify_plan_v1(rd, approved=approved)


def verify_approval_envelope(rundir, *, _session=None):
    try:
        rd = root(rundir)
        if not review_enabled(rd):
            _literal_delegation_spec(read_json(rd/SPEC),read_json(rd/PLAN)['base_dir'])
        verify_plan(rd, approved=True, _session=_session)
        return []
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return [str(exc)]


def approve(rundir, quote, *, scripted=False, _delegated=False):
    if type(_delegated) is not bool:raise ValueError('delegated approval switch must be boolean')
    rd = root(rundir)
    from .method_selection import require_launch
    require_launch(rd)
    if not review_enabled(rd):
        if _delegated:return _approve_literal_delegated(rd)
        return _approve_v1(rd, quote, scripted=scripted)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        p = verify_plan(rd)
        from . import scientific_autonomy
        delegated=scientific_autonomy.plan_authority(rd) if _delegated else None
        if delegated is not None:quote=delegated['value']['quote']
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError('actual assent text required')
        operator = delegated is None and _operator_reapproval(rd, p, scripted)
        if delegated is None and not operator and scripted != (p['approval_mode'] == 'scripted_yes'):
            raise ValueError('approval mode must match the proposal; scripted assent is not expert review')
        authority = ('delegated_machine' if delegated is not None else 'unknown' if operator else
                     'scripted_experiment' if p['approval_mode'] == 'scripted_yes' else 'unknown')
        reapproval = _admit_approval(rd, authority)
        from .launch_authorization import operational_utc
        from .approval_authority import classify
        receipt = {'authority': classify(scripted=scripted, delegated=delegated is not None, quote=quote),
                   'schema_version': 2, 'generated_by': 'ravel.workflow.science.approve', 'quote': quote,
                   'approval_mode': p['approval_mode'], 'expert_review': False,
                   'plan_sha256': execution.file_hash(rd / PLAN), 'checkin_sha256': execution.file_hash(rd / 'inputs/checkin1.json'),
                   'utc': operational_utc(), 'input_fingerprint': _approval_fingerprint(approval_input_paths(rd))}
        if delegated is not None:
            receipt.update(schema_version=3,generated_by='ravel.workflow.science.approve_delegated',
                authority='delegated_machine',delegation=scientific_autonomy._run_document(rd)[1]['autonomy'],
                approval_mode='delegated_machine',proposal_approval_mode=p['approval_mode'],
                delegate_actor=delegated['value']['delegate_actor'])
        from copy import deepcopy
        intended=deepcopy(receipt)
        _register_approval(rd, deepcopy(intended), authority=authority, reapproval=reapproval,
                           fingerprint=lambda: _approval_fingerprint(approval_input_paths(rd)),
                           details={'proposal_approval_mode': p['approval_mode']} if operator else None)
        verify_plan(rd,approved=True)
        if delegated is not None and scientific_autonomy.plan_authority(rd)!=delegated:raise ValueError('delegation changed before machine plan decision return')
        if read_json(rd/APPROVAL)!=intended:raise ValueError('plan approval differs from intended approval receipt')
    packet(rd, write=True)
    return 0


def approve_delegated(rundir):
    """Public initial-prompt/CI1 opt-in, exact machine assent, no compute dispatch."""
    rd=root(rundir)
    if not review_enabled(rd):return _approve_literal_delegated(rd)
    return approve(rd,'delegated quote resolved from committed user text',scripted=True,_delegated=True)


def execution_spec(rundir, *, _proposal=None, _spec=None, _session=None):
    rd = root(rundir)
    read = _session.read_document if _session is not None else read_json
    p = _proposal or read(rd / PLAN)
    spec = deepcopy(_spec or read(rd / SPEC))
    if p['schema_version'] == 1:
        return spec
    document = read(regular(EXECUTION_TASK, rd))
    _keys(document, {'schema_version', 'task'}, 'science execution task')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('invalid science execution task version')
    _numeric_delta(p['execution_task'], document['task'], spec['review_policy']['correction_contract']['task_fields'])
    for slot in p['mutable_inputs']:
        _numeric_delta(slot['baseline'], read(regular(slot['run_path'], rd)), slot['fields'])
    spec['task'] = document['task']
    validate(spec)
    return spec


def _correction_path(number):
    return f'inputs/science-correction-{number - 1}.json'


def _selected(rd, p, attempt=None, *, _session=None):
    read = _session.read_document if _session is not None else read_json
    attempt = attempt or read(rd / 'execution_attempt.json')
    number = attempt.get('attempt')
    if type(number) is not int or not 1 <= number <= p['max_attempts']:
        raise ValueError('execution attempt exceeds the prospective science budget')
    if read(rd / 'logs/science-attempts' / f'{number:08d}.json') != attempt:
        raise ValueError('current science attempt differs from its retained spent-attempt token')
    if number == 1:
        if attempt.get('correction_id') is not None or attempt.get('correction_plan_sha256') is not None:
            raise ValueError('initial attempt cannot claim correction authority')
        stage, budget = p['stages'][0], p['max_seconds']
    else:
        path = regular(_correction_path(number), rd)
        document = read(path)
        _keys(document, {'schema_version', 'attempt', 'plan_sha256', 'max_seconds', 'settings'}, 'science correction plan')
        if (document['schema_version'] != 1 or document['attempt'] != number
                or document['plan_sha256'] != execution.file_hash(rd / PLAN)
                or type(document['max_seconds']) is not int or not 1 <= document['max_seconds'] <= p['max_seconds']
                or document['settings'] != execution.snapshot(rd, p['mutable_paths'])
                or attempt.get('correction_plan_sha256') != execution.file_hash(path)):
            raise ValueError('correction plan, exact settings or budget changed after admission')
        stage = _stage(rd, p['stages'][0]['inputs'], number, correction_sha256=execution.file_hash(path))
        budget = document['max_seconds']
        from . import physics_review
        reg, events = physics_review._read(rd)
        admitted = next((e for e in events if e['event'] == 'correction' and e['correction_id'] == attempt.get('correction_id')), None)
        selected_binding = _plan_stage(rd, 'science', stage['command'], stage['inputs'], stage['outputs'], [], rd, _session,
                                       **execution.stage_metadata_fields(stage))
        expected = physics_review._stage_spec(rd, {**stage, 'inputs': selected_binding['inputs']})
        if (admitted is None or admitted['redo_number'] != number - 1 or admitted['stage_specs'] != [expected]
                or admitted['effective_settings'] != [{'path': path, 'sha256': execution.file_hash(rd / path)}
                                                     for path in review_effective_settings(rd)]):
            raise ValueError('correction lacks its exact decider admission')
    if attempt.get('plan_sha256') != execution.file_hash(rd / PLAN) or attempt.get('budget_seconds') != budget:
        raise ValueError('execution-attempt identity or budget differs from the approved plan')
    binding = _plan_stage(rd, 'science', stage['command'], stage['inputs'], stage['outputs'], [], rd, _session,
                                       **execution.stage_metadata_fields(stage))
    return stage, binding, budget


def review_effective_settings(rundir):
    p = read_json(root(rundir) / PLAN)
    return list(dict.fromkeys([EXECUTION_TASK, *p['mutable_paths']]))


def correct(rundir, *, actor_id, changed_paths, recheck_checks, max_seconds=None, supporting_artifacts=None):
    """Materialize one derivative plan, then admit its exact settings through the decider."""
    rd = root(rundir)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        p = verify_plan(rd, approved=True)
        if p['schema_version'] != 2:
            raise ValueError('corrections require a prospective version 2 study')
        from . import physics_review
        view = physics_review.status(rd)
        if view['state'] not in ('send_back', 'correction_failed') or view['redos_remaining'] <= 0:
            raise ValueError('a correction requires rejected work with a remaining prospective redo')
        number = view['redos_used'] + 2
        budget = p['max_seconds'] if max_seconds is None else max_seconds
        if type(budget) is not int or not 1 <= budget <= p['max_seconds']:
            raise ValueError('correction budget exceeds the original hard ceiling')
        document = {'schema_version': 1, 'attempt': number, 'plan_sha256': execution.file_hash(rd / PLAN),
                    'max_seconds': budget, 'settings': execution.snapshot(rd, p['mutable_paths'])}
        path = rd / _correction_path(number)
        # Drafts can be revised until admission. Preserve every previous draft;
        # the admitted command commits the final document's exact byte digest.
        if path.exists() and read_json(path) != document:
            prior = rd / 'logs/science-correction-drafts' / (execution.file_hash(path) + '.json')
            if not prior.exists():
                prior.parent.mkdir(parents=True, exist_ok=True)
                with prior.open('xb') as stream:
                    stream.write(path.read_bytes())
        atomic_json(path, document)
        stage = _stage(rd, p['stages'][0]['inputs'], number, correction_sha256=execution.file_hash(path))
        binding = execution.plan_stage(rd, 'science', stage['command'], stage['inputs'], stage['outputs'], [], rd)
        # Include implementation/executable custody exactly as the supervisor does.
        admitted_spec = {**stage, 'inputs': binding['inputs']}
        admission = physics_review.authorize_correction(rd, actor_id=actor_id, changed_paths=changed_paths,
            stages=['science'], recheck_checks=recheck_checks, stage_specs=[admitted_spec],
            supporting_artifacts=supporting_artifacts)
        with (rd / 'DEVIATIONS.md').open('a') as stream:
            stream.write(f'\nAdmitted science correction {number - 1}: {admission["correction_id"]}. '
                         f'Exact plan `{_correction_path(number)}`.\n')
    packet(rd, write=True)
    return admission


def launch_binding(rundir, stage, *, _session=None):
    rd = root(rundir)
    if _session is None:
        with _validation_scope(rd) as session:
            return launch_binding(rd, stage, _session=session)
    p = verify_plan(rd, approved=True, _session=_session)
    if p['schema_version'] != 2 or stage != 'science':
        raise ValueError('launch is outside the prospective scientific study')
    selected, binding, budget = _selected(rd, p, _session=_session)
    receipt=read_json(rd/APPROVAL)
    if receipt.get('schema_version')==3:
        from . import scientific_autonomy
        scientific_autonomy.plan_authority(rd)
    return {'stage': selected, 'binding': binding, 'max_seconds': budget}


def _verified_launch_binding(rundir, stage, command, context, *, _session=None):
    """Return only an internally verified selection within this admission phase."""
    rd = root(rundir)
    if _session is None:
        with _validation_scope(rd) as session:
            return _verified_launch_binding(rd, stage, command, context, _session=session)
    selected = launch_binding(rd, stage, _session=_session)
    _check_launch_selection(rd, selected, stage, command, context, _session)
    return selected


def _check_launch_selection(rd, selected, stage, command, context, session, *, _review_session=None):
    from . import physics_review
    expected = physics_review._stage_spec(rd, {**selected['stage'], 'inputs': selected['binding']['inputs']})
    if (list(command) != selected['stage']['command'] or context.get('stage_spec') != expected
            or context.get('max_seconds') != selected['max_seconds']):
        raise ValueError('supervised science command, IO, log or hard budget differs from the exact approved attempt')
    attempt = session.read_document(rd / 'execution_attempt.json')
    correction = attempt['attempt'] > 1
    if context.get('review_action') != ('correction' if correction else 'bulk'):
        raise ValueError('science launch action differs from its admitted attempt')
    if correction:
        errors = physics_review.correction_execution_errors(rd, stage, command, expected['inputs'], expected['outputs'],
                    expected['depends_on'], expected['cwd'], expected['log'],
                    **({} if _review_session is None else {'_session': _review_session}))
    elif physics_review.active(rd):
        errors = ['initial science attempt cannot run after a review cycle has opened']
    else:
        errors = []
        original = session.read_document(rd / PLAN)['stage_binding']
        if selected['binding'] != original:
            errors.append('initial scientific task bytes differ from their original approval')
    if errors:
        raise ValueError('; '.join(errors))


def verify_launch(rundir, stage, command, context, *, _session=None):
    try:
        _verified_launch_binding(rundir, stage, command, context, _session=_session)
        return []
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return [str(exc)]


def launch_input_paths(rundir):
    rd = root(rundir)
    attempt = read_json(rd / 'execution_attempt.json')
    return [str(rd / 'execution_attempt.json'), *([str(rd / _correction_path(attempt['attempt']))]
                                                if attempt['attempt'] > 1 else [])]


def validate_authorization_snapshot(snapshot, event):
    """Validate frozen science approval and selected recipe without today's files."""
    try:
        import json
        from . import provenance
        from .launch_authorization import parse_utc
        _keys(snapshot, {'approval_kind', 'required_plan', 'approval', 'approval_inputs', 'go', 'go_inputs',
                         'review', 'review_inputs', 'science_launch_inputs', 'science_stage_inputs', 'stage_binding'},
              'science launch snapshot')
        if snapshot['approval_kind'] != 'science' or snapshot['required_plan'] != 'science' or snapshot['go'] is not None or snapshot['go_inputs']:
            raise ValueError('science launch borrowed a native compute rung or GO')
        approval = snapshot['approval']
        rd = Path(approval['path']).parent.parent
        if approval['path'] != str(rd / APPROVAL):
            raise ValueError('science launch needs its genuine science receipt')
        if [p['path'] for p in snapshot['approval_inputs'][:4]] != [str(rd / p) for p in (PLAN, SPEC, 'inputs/checkin1.json', REVIEW_POLICY)]:
            raise ValueError('retained science approval input inventory changed')
        all_documents = [approval, *snapshot['approval_inputs'], *snapshot['science_launch_inputs']]
        for pin in all_documents:
            if provenance.sha256_bytes(pin['text'].encode()) != pin['sha256']:
                raise ValueError('retained science authorization document changed')
        p, spec, checkin, policy = [json.loads(pin['text']) for pin in snapshot['approval_inputs'][:4]]
        from . import scientific_autonomy
        sources={row['path']:row['text'].encode() for row in snapshot['approval_inputs']}
        delegated_source=scientific_autonomy.declaration(spec,rd,_sources=sources)
        expected_extra=list(dict.fromkeys(scientific_autonomy.input_paths(spec,rd,sources=sources)))
        from . import method_selection
        method_path = str(rd / method_selection.DECISION_PATH)
        method_record = json.loads(sources[method_path]) if method_path in sources else None
        if method_record is not None:
            allowed, reason = method_selection.escalation_allowed(method_record)
            if not allowed: raise ValueError(reason)
        from . import work_dispatch
        if 'work_obligations_sha256' in checkin:
            expected_extra.append(str(rd / 'inputs/work-obligations.json'))
        if method_record is not None: expected_extra.append(method_path)
        expected_extra=[path for path in expected_extra if path not in [p['path'] for p in snapshot['approval_inputs'][:4]]]
        if [row['path'] for row in snapshot['approval_inputs'][4:]]!=expected_extra:raise ValueError('retained delegation source roster changed')
        validate(spec)
        receipt = json.loads(approval['text'])
        _keys(receipt, {'schema_version', 'generated_by', 'quote', 'approval_mode', 'expert_review', 'plan_sha256',
                        'checkin_sha256', 'utc', 'input_fingerprint'} | ({'authority','delegation','delegate_actor','proposal_approval_mode'} if receipt.get('schema_version')==3 else ({'authority'} if 'authority' in receipt else set())), 'retained science approval')
        delegated_approval=receipt.get('schema_version')==3
        if delegated_approval:scientific_autonomy.verify_decision(spec,receipt,rd,sources=sources)
        if (type(receipt['schema_version']) is not int or receipt['schema_version'] != (3 if delegated_approval else 2)
                or receipt['generated_by'] != ('ravel.workflow.science.approve_delegated' if delegated_approval else 'ravel.workflow.science.approve')
                or spec['schema_version'] != 2 or p['schema_version'] != 2
                or policy != spec['review_policy']['policy'] or p['max_attempts'] != spec['max_attempts']
                or p['max_seconds'] != spec['max_seconds'] or p['approval_mode'] != spec['approval_mode']
                or receipt['approval_mode'] != ('delegated_machine' if delegated_approval else p['approval_mode'])
                or (delegated_approval and receipt['proposal_approval_mode']!=p['approval_mode']) or receipt['expert_review'] is not False
                or not isinstance(receipt['quote'], str) or not receipt['quote'].strip()
                or receipt['plan_sha256'] != snapshot['approval_inputs'][0]['sha256']
                or receipt['checkin_sha256'] != snapshot['approval_inputs'][2]['sha256']
                or receipt['input_fingerprint'] != provenance.sha256_bytes(''.join(pin['sha256'] for pin in snapshot['approval_inputs']).encode())
                or work_dispatch.checkin_content(checkin, rd, sources=sources) != make_checkin(spec, snapshot['approval_inputs'][0]['sha256'],p['stages'][0],base=p['base_dir'],method_decision=method_record)
                or parse_utc(receipt['utc']) > parse_utc(event['utc'])):
            raise ValueError('retained science approval binding or timing is invalid')
        docs = snapshot['science_launch_inputs']
        if not docs or docs[0]['path'] != str(rd / 'execution_attempt.json'):
            raise ValueError('retained science launch has no selected attempt')
        attempt = json.loads(docs[0]['text'])
        number = attempt.get('attempt')
        if (type(number) is not int or not 1 <= number <= p['max_attempts']
                or attempt.get('plan_sha256') != snapshot['approval_inputs'][0]['sha256']
                or parse_utc(attempt.get('started_utc')) > parse_utc(event['utc'])):
            raise ValueError('retained science attempt identity, budget or timing is invalid')
        correction = number > 1
        expected_command = [*p['stages'][0]['command'][:-1], str(number)]
        if 'execution' in spec:
            # A placed stage has exactly one attempt; its command is the backend worker.
            expected_command = list(p['stages'][0]['command'])
        budget = p['max_seconds']
        if correction:
            if len(docs) != 2 or docs[1]['path'] != str(rd / _correction_path(number)) or attempt.get('correction_plan_sha256') != docs[1]['sha256']:
                raise ValueError('retained science correction plan changed')
            document = json.loads(docs[1]['text'])
            _keys(document, {'schema_version', 'attempt', 'plan_sha256', 'max_seconds', 'settings'}, 'retained correction plan')
            budget = document['max_seconds']
            if (type(budget) is not int or not 1 <= budget <= p['max_seconds'] or document['attempt'] != number
                    or document['schema_version'] != 1 or document['plan_sha256'] != attempt['plan_sha256']):
                raise ValueError('retained correction exceeds its original envelope')
            expected_command += ['--correction-sha256', docs[1]['sha256']]
        elif (len(docs) != 1 or attempt.get('correction_id') is not None or attempt.get('correction_plan_sha256') is not None):
            raise ValueError('initial attempt claims nonexistent correction authority')
        binding, original = snapshot['stage_binding'], p['stage_binding']
        declared_helpers = execution.helper_declaration_fields(p['stages'][0])
        if execution.helper_declaration_fields(original) != declared_helpers:
            raise ValueError('retained science helper declaration differs from the plan')
        expected_helpers = execution.relocate_helper_fields(original, rd/'outputs/attempt-1', rd/f'outputs/attempt-{number}')
        if execution.helper_declaration_fields(binding) != expected_helpers:
            raise ValueError('retained science helper declaration differs from the selected attempt')
        declared_policy = execution.output_policy_fields(spec)
        if (execution.output_policy_fields(p['stages'][0]) != declared_policy
                or execution.output_policy_fields(original) != declared_policy
                or execution.output_policy_fields(binding) != declared_policy):
            raise ValueError('retained science output policy differs from its original declaration')
        if (binding['fingerprint'] != execution.digest({k: v for k, v in binding.items() if k != 'fingerprint'})
                or binding['command'] != expected_command or binding['cwd'] != str(rd)
                or binding['inputs'] != original['inputs'] or binding['outputs'] != [f'outputs/attempt-{number}']
                or binding['parents'] != {} or binding['runtime'] != original['runtime']):
            raise ValueError('retained science stage recipe changed')
        mutable = {str(rd / value) for value in p['mutable_paths']} | {str(rd / EXECUTION_TASK)}
        if ({k: v for k, v in binding['input_snapshot'].items() if k not in mutable}
                != {k: v for k, v in original['input_snapshot'].items() if k not in mutable}):
            raise ValueError('retained science launch changed fixed input or source bytes')
        pins = {pin['path']: pin['sha256'] for pin in snapshot['science_stage_inputs']}
        if (len(pins) != len(snapshot['science_stage_inputs']) or set(pins) != set(binding['input_snapshot'])
                or any(value['kind'] != 'file' or len(value['files']) != 1
                       or value['files'][0]['sha256'] != pins[path] for path, value in binding['input_snapshot'].items())):
            raise ValueError('retained stage input digests differ from the exact science binding')
        if correction:
            if document['settings'] != {str(rd / path): binding['input_snapshot'][str(rd / path)] for path in p['mutable_paths']}:
                raise ValueError('retained correction settings differ from the admitted recipe')
            review = snapshot['review']
            if not review:
                raise ValueError('retained science correction has no review admission')
            admission = next(e for e in reversed(review['events']) if e['event'] == 'correction')
            if (admission['correction_id'] != attempt['correction_id'] or admission['redo_number'] != number - 1
                    or any(pins.get(str(rd / pin['path']) if not Path(pin['path']).is_absolute() else pin['path']) != pin['sha256']
                           for pin in admission['effective_settings'])):
                raise ValueError('retained science attempt differs from its decider admission')
        elif binding != original:
            raise ValueError('initial science attempt differs from its original approval')
        from . import physics_review
        stage = {**p['stages'][0], 'command': expected_command, 'inputs': binding['inputs'],
                 'outputs': binding['outputs'], 'log': f'logs/science-worker-{number}.log', **expected_helpers}
        if (event['command'] != expected_command or event['context'].get('kind') != 'science-stage'
                or event['context'].get('stage') != 'science' or event['context'].get('max_seconds') != budget
                or event['context'].get('plan_sha256') != snapshot['approval_inputs'][0]['sha256']
                or attempt.get('budget_seconds') != budget
                or event['context'].get('stage_spec') != physics_review._stage_spec(rd, stage)
                or event['context'].get('review_action') != ('correction' if correction else 'bulk')):
            raise ValueError('retained science launch context differs from the exact selected attempt')
        return []
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration) as exc:
        return [str(exc)]


def _await_worker_registration(rd, *, timeout=5.0):
    return execution.await_worker_registration(rd, 'science', timeout=timeout)


def verify_worker(rundir):
    rd = root(rundir)
    if not review_enabled(rd):
        return _verify_worker_v1(rd)
    _await_worker_registration(rd)
    # This worker admission has its own fresh session, independent of approval,
    # controller and supervisor admission. Repeated checks inside it share bytes.
    with _validation_scope(rd) as session:
        return _verify_worker_observed(rd, session)


def _readonly_worker_boundary(rd, session):
    """Close the existing envelope and current review law inside this worker.

    Only the read-only preparation opts into these observations. Public launch,
    review policy and ordinary Session finish remain unchanged.
    """
    from . import physics_review
    forbidden = ('inputs/native_execution_plan.json', 'inputs/checkin1_approval.json',
                 'inputs/task_contract.json')
    if any(session.observe_exists(rd / value) for value in forbidden):
        raise ValueError('scientific worker has a forbidden task/approval envelope')
    for value in (physics_review.REGISTRATION, physics_review.HEAD):
        path = rd / value
        if session.observe_exists(path):
            session.read_document(path)
    session.require_inventory(rd / physics_review.DIRECTORY / 'events')
    # Existing active() validates positive recorded state and regards corrupted
    # state as active. Explicit absence observations above cover its early false.
    physics_review.active(rd, _session=session)


def _verify_worker_observed(rd, session, *, _readonly=None):
    p = verify_plan(rd, approved=True, _session=session,
        **({} if _readonly is None else {'_readonly': _readonly}))
    stage, binding, budget = _selected(rd, p, _session=session)
    state = execution.load_execution(rd)
    session.track(state)
    record = state['stages'].get('science', {})
    from . import physics_review
    attempt = session.read_document(rd / 'execution_attempt.json')
    context = {'stage_spec': physics_review._stage_spec(rd, {**stage, 'inputs': binding['inputs']}),
               'max_seconds': budget, 'review_action': 'correction' if attempt['attempt'] > 1 else 'bulk'}
    selected = {'stage': stage, 'binding': binding, 'max_seconds': budget}
    if _readonly is not None:
        _readonly_worker_boundary(rd, session)
        session.track(selected)
        session.track(context)
        def current_launch_boundary():
            _readonly_worker_boundary(rd, session)
            _check_launch_selection(rd, selected, 'science', stage['command'], context, session,
                                    _review_session=session)
        _readonly.add_ending_check(current_launch_boundary)
    _check_launch_selection(rd, selected, 'science', stage['command'], context, session,
                            **({} if _readonly is None else {'_review_session': session}))
    custody = execution.worker_custody(rd, 'science', record)
    if record.get('fingerprint') != binding['fingerprint']:
        raise ValueError('scientific worker requires its current approved supervised attempt')
    # A placed stage writes into its attempt's backend staging; the backend fetch
    # moves the hashed result to the declared output afterward.
    output = (stage['outputs'][0] if custody['mode'] == 'direct'
              else str(Path(custody['output_dir']) / Path(stage['outputs'][0]).name))
    return {**p, 'stages': [stage], 'stage_binding': binding, 'max_seconds': budget,
            'output_directory': output, 'attempt': attempt['attempt']}


def review_waypoint_paths(rundir, *, _session=None):
    rd = root(rundir)
    if _session is None:
        with _validation_scope(rd) as session:
            return review_waypoint_paths(rd, _session=session)
    execution._check_validation_session(rd, _session)
    p = verify_plan(rd, approved=True, _session=_session)
    stage, binding, _ = _selected(rd, p, _session=_session)
    record = execution.load_execution(rd)['stages'].get('science', {})
    if record.get('fingerprint') != binding['fingerprint'] or record.get('status') != 'succeeded':
        raise ValueError('science review needs the exact current successful attempt')
    errors = execution.stage_errors(rd, 'science', _session=_session)
    from .launch_authorization import audit_launches
    errors += audit_launches(rd, plan_sha256=execution.file_hash(rd / PLAN), require_science=True)
    if errors:
        raise ValueError('; '.join(errors))
    out = rd / stage['outputs'][0]
    from ravel.validation.validate_checkin import validate as check
    errors = check(read_json(out / 'checkin2.json'))
    if errors:
        raise ValueError('; '.join(errors))
    for name in ('checkin2.json', 'recipe.json', 'verification.json', 'result.json'):
        regular(out / name, rd)
    # The successful receipt commits the complete output census. Pin individual
    # raw artifacts so role packets can inspect arithmetic rather than just the
    # producer's aggregate result label.
    return [str(regular(path, rd)) for path in sorted(out.rglob('*')) if path.is_file()]


def _packet_negative_close(rd, observations):
    """Packet-only absent observations close after every session callback."""
    if not observations.get('canonical'):
        return
    if any((rd / name).exists() for name in
           ('inputs/native_execution_plan.json', 'inputs/checkin1_approval.json', 'inputs/task_contract.json')):
        raise ValueError('science plan, prospective policy or immutable envelope changed')
    if observations.get('approval_missing') and (rd / APPROVAL).exists():
        raise ValueError('study approval appeared during packet observation')


# Callable identities enroll only this source-owned observational route. These
# contain no evidence and do not retain any validation across public calls.
from .validation_io import ValidationSession as _PACKET_SESSION_TYPE
_PACKET_VALIDATORS = (verify_plan, _verify_v2, _verify_v2_common,
                      _verify_v2_approval, review_enabled, _packet_negative_close)


def _packet_v2_observed(rd, session, *, _single_pass=False, _absence_observations=None):
    execution._check_validation_session(rd, session)
    errors, review_errors, status, mode = [], [], 'planned', None
    try:
        canonical = (_single_pass and _absence_observations is not None
            and type(session) is _PACKET_SESSION_TYPE
            and all(actual is expected for actual, expected in zip(
                (verify_plan, _verify_v2, _verify_v2_common, _verify_v2_approval, review_enabled, _packet_negative_close),
                _PACKET_VALIDATORS))
            and review_enabled(rd))
        if canonical:
            _absence_observations['canonical'] = True
            read = session.read_document
            p, spec = _verify_v2_common(rd, _session=session, _read=read)
        else:
            p = verify_plan(rd, _session=session)
        mode = p['mode']
        approval_exists = (rd / APPROVAL).exists()
        if canonical:
            _absence_observations['approval_missing'] = not approval_exists
            if not all(actual is expected for actual, expected in zip(
                    (verify_plan, _verify_v2, _verify_v2_common, _verify_v2_approval, review_enabled, _packet_negative_close),
                    _PACKET_VALIDATORS)):
                raise ValueError('packet validation owners changed during observation')
        if approval_exists:
            if canonical:
                _verify_v2_approval(rd, spec, _session=session, _read=read)
                if not all(actual is expected for actual, expected in zip(
                        (verify_plan, _verify_v2, _verify_v2_common, _verify_v2_approval, review_enabled, _packet_negative_close),
                        _PACKET_VALIDATORS)):
                    raise ValueError('packet validation owners changed during observation')
                session.proofs[('science-v2-plan', True)] = p
                session.proofs[('science-v2-plan', False)] = p
            else:
                verify_plan(rd, approved=True, _session=session)
            status = 'approved'
        elif canonical:
            session.proofs[('science-v2-plan', False)] = p
        from . import physics_review, review_enforcement
        view = physics_review.status(rd, _session=session) if physics_review.active(rd, _session=session) else None
        if view and view['state'] in ('correction_admitted', 'send_back', 'stopped'):
            status = view['state']
            raise RunningStudy()
        if (rd / 'execution_attempt.json').exists():
            stage, binding, _ = _selected(rd, p, _session=session)
            record = execution.load_execution(rd)['stages'].get('science', {})
            if record.get('status') == 'running':
                status = 'running'
                raise RunningStudy()
            errors += execution.validate_completed_execution(rd, [stage], _session=session)
            status = 'failed' if errors else 'completed'
            if not errors:
                out = rd / stage['outputs'][0]
                result = read_json(out / 'result.json')
                verification = read_json(out / 'verification.json')
                if result.get('status') != 'passed' or result.get('physics_validated') is not False:
                    errors.append('scientific adapter postconditions did not pass')
                if (verification.get('passed') is not True or verification.get('scope') != mode
                        or verification.get('physics_validated') is not False or verification.get('expert_review') is not False
                        or verification.get('result_sha256') != execution.file_hash(out / 'result.json')):
                    errors.append('scientific verification did not pass or does not bind the delivered result')
                from ravel.validation.claim_checks import science_errors
                errors += science_errors(rd, mode, [rd / value for value in stage['outputs']], _session=session)
                review_waypoint_paths(rd, _session=session)
                delivery = review_enforcement.delivery_errors
                kwargs = {'_session': session} if '_session' in inspect.signature(delivery).parameters else {}
                review_errors = delivery(rd, **kwargs)
                if review_errors and not errors:
                    status = 'awaiting_review'
        if physics_review.active(rd, _session=session):
            view = physics_review.status(rd, _session=session)
            if view['state'] == 'correction_admitted':
                status = 'correction_admitted'
            elif view['state'] in ('send_back', 'correction_failed', 'stopped') and not errors:
                status = view['state']
    except RunningStudy:
        pass
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        errors.append(str(exc))
        status = 'invalid'
    if errors and status == 'completed':
        status = 'failed'
    next_steps = {'planned': 'Review and approve exact CHECK-IN 1 and prospective policy',
        'approved': 'Run the first supervised attempt', 'running': 'Wait for the owned worker',
        'awaiting_review': 'Use ravel judgment open --rundir <this run> --checks <located-checks>, then ravel judgment advance with configured role Host and explicit model/token/wall bounds; current critic, verifier and decider receipts enter the existing review journal',
        'send_back': 'Prepare only the prospectively allowed numeric repairs, then materialize and admit science-correct',
        'correction_admitted': 'Run the exact admitted correction, then open its successor review with fresh receipt and checks',
        'correction_failed': 'Inspect retained failure; another admission consumes the remaining prospective redo budget',
        'stopped': 'The review stopped this study; retain evidence and resolve outside its envelope',
        'failed': 'Use ravel failed-review intake for the actual failed attempt, then ravel judgment failed-feedback with fresh diagnostic critic/verifier bindings; partial results remain unaccepted and a new experiment needs separate admission', 'invalid': 'Resolve stale or missing artifacts without overwriting evidence',
        'completed': 'Scoped review accepted; reuse only the exact checked products'}
    result = {'schema_version': 2, 'rundir': str(rd), 'task_mode': mode, 'execution': {'status': status},
              'lifecycle_verdict': 'FAIL' if errors else 'PASS' if status == 'completed' else 'PENDING',
              'errors': errors, 'review_errors': review_errors, 'next_required': next_steps[status],
              'physics_validated': False, 'scope': 'Bounded scientific adapter delivery, not scientific closure or authenticated independent review'}
    observed_spec = session.read_document(rd / SPEC)
    if 'goal_binding' in observed_spec:
        from .task_completion import binding_projection
        result['parent_task'] = binding_projection(observed_spec['goal_binding'], base_dir=rd)
    return result

def packet(rundir, *, write=False):
    """One fresh read-only transaction per packet; never share admission phases."""
    rd = root(rundir)
    if write:
        # A refused bind-on-resume is a blocker in the packet, never a traceback.
        from .current_state import _resume_migration
        migration = _resume_migration(rd)
        if migration is not None and migration['status'] == 'refused':
            result = {'schema_version': 2, 'rundir': str(rd), 'task_mode': None,
                      'execution': {'status': 'invalid'}, 'lifecycle_verdict': 'FAIL',
                      'errors': ['research protocol migration refused: ' + migration['reason']],
                      'review_errors': [], 'research_protocol_migration': migration,
                      'next_required': 'Restore the research protocol records named in the error; never reinitialize',
                      'physics_validated': False,
                      'scope': 'Bounded scientific adapter delivery, not scientific closure or authenticated independent review'}
            atomic_json(rd / 'current_state.json', result)
            return result
    if read_json(rd / PLAN).get('schema_version') != 2:
        return _packet_v1(rd, write=write)
    observations = {}
    try:
        with _validation_scope(rd) as session:
            result = _packet_v2_observed(rd, session, _single_pass=True,
                                         _absence_observations=observations)
        if observations.get('canonical'):
            if not all(actual is expected for actual, expected in zip(
                (verify_plan, _verify_v2, _verify_v2_common, _verify_v2_approval, review_enabled, _packet_negative_close),
                _PACKET_VALIDATORS)):
                raise ValueError('packet validation owners changed during observation')
            _packet_negative_close(rd, observations)
            if not all(actual is expected for actual, expected in zip(
                (verify_plan, _verify_v2, _verify_v2_common, _verify_v2_approval, review_enabled, _packet_negative_close),
                _PACKET_VALIDATORS)):
                raise ValueError('packet validation owners changed during observation')
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        result = {'schema_version': 2, 'rundir': str(rd), 'task_mode': None,
            'execution': {'status': 'invalid'}, 'lifecycle_verdict': 'FAIL',
            'errors': [str(exc)], 'review_errors': [],
            'next_required': 'Resolve stale or missing artifacts without overwriting evidence',
            'physics_validated': False,
            'scope': 'Bounded scientific adapter delivery, not scientific closure or authenticated independent review'}
    # Only write the observational product after the final census closes.
    if write:
        atomic_json(rd / 'current_state.json', result)
    return result



def _accepted_resume_observed(rd):
    """Share custody only inside one locked, read-only accepted-reuse decision.

    The scope closes and repeats the final identity/ledger/runtime census before
    returning authority. No hashes survive into a launch or another public call.
    """
    from . import review_enforcement
    with _validation_scope(rd) as session:
        proposal = verify_plan(rd, approved=True, _session=session)
        observed = _packet_v2_observed(rd, session)
        if observed['lifecycle_verdict'] != 'PASS':
            return proposal, False
        stage, _, _ = _selected(rd, proposal, _session=session)
        before = review_enforcement.before_stage
        # Older injected callables keep their public positional/keyword seam.
        # Their independent reads do not acquire an observational cache.
        kwargs = {'_session': session} if '_session' in inspect.signature(before).parameters else {}
        before(rd, 'science', stage['command'], stage['inputs'], stage['outputs'], [],
               str(rd), stage['log'], resume=True, **kwargs)
        return proposal, True


def run(rundir, *, resume=False):
    from .research_evaluation import verify_run_dispatch
    verify_run_dispatch(rundir)
    rd = root(rundir)
    if (rd/APPROVAL).exists() and read_json(rd/APPROVAL).get('schema_version')==3:
        from . import scientific_autonomy
        scientific_autonomy.plan_authority(rd)
    legacy = False
    with file_lock(rd / 'logs/science.lock', blocking=False):
        if resume:
            from .stage_supervisor import recover_previous_attempt
            recover_previous_attempt(rd, 'science', grace=2)
        if resume and review_enabled(rd):
            p, reused = _accepted_resume_observed(rd)
            if reused:
                return 0
        else:
            p = verify_plan(rd, approved=True)
        if p.get('schema_version', 1) == 1:
            legacy = True
        else:
            from . import physics_review, review_enforcement
            view = physics_review.status(rd) if physics_review.active(rd) else None
            if view and view['state'] == 'correction_admitted':
                admission = physics_review.admitted_correction(rd)
                number = admission['redo_number'] + 1
                correction_path = regular(_correction_path(number), rd)
                document = read_json(correction_path)
                stage = _stage(rd, p['stages'][0]['inputs'], number, correction_sha256=execution.file_hash(correction_path))
                budget = document['max_seconds']
                attempt = {'attempt': number, 'correction_id': admission['correction_id'],
                           'correction_plan_sha256': execution.file_hash(correction_path)}
            elif _attempt_spent(rd):
                raise ValueError('the approved attempt is spent; accepted reuse or an admitted correction is required')
            else:
                stage, budget, attempt = p['stages'][0], p['max_seconds'], {'attempt': 1, 'correction_id': None, 'correction_plan_sha256': None}
            requested_binding = execution.plan_stage(rd, 'science', stage['command'], stage['inputs'], stage['outputs'], [], rd,
                                                  **execution.stage_metadata_fields(stage))
            _steering_admission(rd)
            review_enforcement.before_stage(rd, 'science', stage['command'], requested_binding['inputs'], stage['outputs'], [],
                                           str(rd), stage['log'], **execution.helper_declaration_fields(stage))
            attempt.update(plan_sha256=execution.file_hash(rd / PLAN), budget_seconds=budget, started_utc=execution.utc_now())
            # Preserve every spent attempt token. Deleting the current token cannot
            # erase either execution receipts or admitted redo history.
            journal = rd / 'logs/science-attempts' / f'{attempt["attempt"]:08d}.json'
            journal.parent.mkdir(parents=True, exist_ok=True)
            with journal.open('x') as stream:
                import json
                json.dump(attempt, stream, indent=2, allow_nan=False)
                stream.write('\n')
            atomic_json(rd / 'execution_attempt.json', attempt)
            from .stage_supervisor import supervise
            placed = rd / 'inputs/backend-plan.json' if 'execution' in read_json(rd / SPEC) else None
            code = supervise('science', str(rd), 0, stage['log'], stage['command'], kill_secs=budget, poll=.2, grace=2,
                             inputs=stage['inputs'], outputs=stage['outputs'], depends_on=[], cwd=str(rd),
                         **execution.stage_metadata_fields(stage), **({'backend_plan': str(placed)} if placed else {}))
            _release_refused_attempt(rd, attempt)
    if legacy:
        return _run_v1(rd, resume=resume)
    state = packet(rd, write=True)
    return code or (3 if state['lifecycle_verdict'] == 'FAIL' else 0)


# Initial injected interfaces keep the original path. Captures are identities,
# never source/custody authority and never exported to another process.
_READONLY_WORKER_BASELINE = verify_worker
_READONLY_CORE_BINDINGS = (
    ('verify_worker', verify_worker), ('verify_plan', verify_plan),
    ('_verify_v2', _verify_v2), ('_verify_v2_common', _verify_v2_common),
    ('task_inputs', task_inputs), ('execution_spec', execution_spec),
    ('adapter', adapter), ('_await_worker_registration', _await_worker_registration),
    ('_selected', _selected), ('_check_launch_selection', _check_launch_selection),
    ('_verify_worker_observed', _verify_worker_observed),
    ('_readonly_worker_boundary', _readonly_worker_boundary))
_READONLY_SESSION_FACTORY = execution._validation_session
_READONLY_PROCESS_READER = execution.process_identity


def prepare_readonly_worker(rundir, *, verifier, attempt=None, correction_sha256=None):
    """Full independent admission; optional pure bundle before any output."""
    if (verifier is not _READONLY_WORKER_BASELINE
            or any(globals().get(name) is not function for name, function in _READONLY_CORE_BINDINGS)
            or execution._validation_session is not _READONLY_SESSION_FACTORY
            or execution.process_identity is not _READONLY_PROCESS_READER):
        return None
    rd = root(rundir)
    if not review_enabled(rd):
        return None
    _await_worker_registration(rd)
    from .readonly_preparation import WorkerReadOnlyObservation
    initial_process = (os.getpid(), os.getppid(), execution.process_identity(os.getpid()))
    initial_factory = execution._validation_session
    process_reader = execution.process_identity
    with WorkerReadOnlyObservation(rd, process_binding=(execution, process_reader, initial_process)) as owner:
        proposal = _verify_worker_observed(rd, owner.session, _readonly=owner)
        # Unknown/effectful adapters keep the current complete admission and
        # then the old independently read execution_spec/run path.
        if owner.descriptor is None:
            errors = owner.session.finish()
            if errors:
                raise ValueError('; '.join(errors))
            return proposal, None
        if (attempt is not None and str(proposal.get('attempt')) != attempt
                or correction_sha256 is not None and correction_sha256 !=
                   owner.session.read_document(rd / 'execution_attempt.json').get('correction_plan_sha256')):
            raise ValueError('worker arguments differ from the exact admitted attempt')
        specification = execution_spec(rd, _session=owner.session)
        if adapter(specification) is not owner.module:
            raise ValueError('effective calculation adapter differs from admitted source')
        def ending_owner():
            if (any(globals().get(name) is not function for name, function in _READONLY_CORE_BINDINGS)
                    or execution._validation_session is not initial_factory
                    or execution.process_identity is not process_reader
                    or (os.getpid(), os.getppid(), execution.process_identity(os.getpid())) != initial_process):
                raise ValueError('independent worker owner changed before read-only return')
            current = owner.session.read_document(rd / 'execution_attempt.json')
            if (current.get('attempt') != proposal['attempt']
                    or attempt is not None and str(current.get('attempt')) != attempt
                    or correction_sha256 is not None and current.get('correction_plan_sha256') != correction_sha256):
                raise ValueError('exact worker attempt changed before read-only return')
        owner.add_ending_check(ending_owner)
        result = owner.calculate(specification['task'], Path(proposal['base_dir']))
        owner.materialize(proposal, specification, result)
        prepared = owner.finish()
        return prepared.proposal, prepared
