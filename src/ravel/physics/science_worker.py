"""Private supervised entrypoint for approved supplied-data scientific studies."""
from pathlib import Path
import sys
import time
from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow import execution
from ravel.workflow.science import verify_worker, regular, adapter, execution_spec


def diagnostic_presentation(mode, result):
    from ravel.workflow.operation_definitions import presentation_for
    presented = presentation_for(mode, result)
    if presented is not None:
        return presented
    if mode in ('formula-grid', 'coupling-morphing', 'prescribed-statistic', 'search-statistics', 'differential-likelihood'):
        from .inference.common import SCOPE
        if result.get('status_scope') != SCOPE or result.get('physics_validated') is not False:
            raise ValueError('an inference record cannot claim physics validation')
        lines = list(result.get('summary') or [])
        return {'status_scope': SCOPE, 'physics_validated': False, 'primary': lines,
                'statistic_origin': result.get('statistic_origin')}, ' '.join(lines)
    if mode in ('amplitude-integration', 'amplitude-predictions', 'weighted-events', 'amplitude-crosscheck'):
        if result.get('physics_validated') is not False:
            raise ValueError('an amplitude-basis record cannot claim physics validation')
        lines = list(result.get('summary') or [])
        return {'status_scope': result.get('status_scope'), 'physics_validated': False}, ' '.join(lines)
    """Carry a completed source diagnosis without promoting it to card approval."""
    if mode == 'tree-array-export':
        from .tree_array_export import SCOPE, delivery_scope
        if result.get('status_scope') != SCOPE or any(result.get(k) is not False for k in ('physics_validated', 'preprocessing_executed', 'training_executed', 'inference_executed', 'original_task_complete')):
            raise ValueError('raw array delivery cannot acquire preprocessing/training/physics authority')
        return {'status_scope': SCOPE, 'physics_validated': False}, delivery_scope()
    if mode in ('symbolic-evaluation','feynarts-amplitude'):
        from .symbolic_evaluation import SCOPE
        if mode=='feynarts-amplitude':
            from .feynarts_amplitude import SCOPE
        if (result.get('status_scope') != SCOPE or result.get('physics_validated') is not False
                or result.get('original_task_complete') is not False
                or result.get('numerical_equivalence_qualified') is not False):
            raise ValueError('symbolic delivery cannot acquire scientific equivalence or whole-task authority')
        return {'status_scope': SCOPE, 'physics_validated': False}, 'Complete declared symbolic/Python delivery only; formula validity and numerical equivalence remain separate.'
    if mode in ('feyn-graph','diagram-analysis'):
        from . import feyn_graph, diagram_analysis
        scope=(feyn_graph.SCOPE if mode=='feyn-graph' else diagram_analysis.SCOPE)
        if result.get('status_scope')!=scope or any(result.get(k) is not False for k in ('physics_validated','original_task_complete')):
            raise ValueError('diagram delivery cannot acquire amplitude or whole-task authority')
        return {'status_scope':scope,'physics_validated':False}, 'Complete model-bound diagram population and explicit supported/unsupported consumer rows; native diagram exports are presentation evidence, not independent amplitude or physics validation.'
    if mode=='parameter-space-sampling':
        from .parameter_space_sampling import SCOPE
        if result.get('status_scope')!=SCOPE or result.get('physics_validated') is not False:
            raise ValueError('original EasyScan delivery cannot acquire sampler/physics qualification')
        return {'status_scope':SCOPE,'physics_validated':False}, 'Original native programme and sampler delivery only; raw callback, chain, dwell and nested-weight populations are distinct. Convergence, posterior/evidence meaning, runtime/engine fidelity and physical applicability require independent review.'
    if mode=='mssm-observable-map':
        from .mssm_observable_map import SCOPE
        if (result.get('status_scope') != SCOPE or
                result.get('population',{}).get('requested_points') != len(result.get('points',[])) or
                result.get('population',{}).get('delivered_points') != len(result.get('points',[])) or
                any(result.get(k) is not False for k in ('physics_validated','execution_authorized','original_task_complete','supplied_cards_changed')) or
                result.get('native_calls') != 0):
            raise ValueError('supplied MSSM map cannot acquire solver/physics/execution/whole-task authority')
        return {'status_scope':SCOPE,'physics_validated':False,'original_task_complete':False}, 'Complete supplied MSSM pole/mixing/decay/lifetime population only; native spectrum/decay accuracy, production, response and inference remain separate.'
    if mode=='nmssm-yukawa-map':
        from .nmssm_yukawa_map import SCOPE
        if (result.get('status_scope') != SCOPE or result.get('population', {}).get('channels') != 81 or
                len(result.get('couplings_and_channels', [])) != 81 or
                any(result.get(k) is not False for k in ('physics_validated', 'execution_authorized',
                    'rge_applied', 'eft_matching_applied', 'supplied_total_width_replaced', 'branching_ratios_predicted')) or
                result.get('native_calls') != 0):
            raise ValueError('finite tree map cannot acquire physical model/total-width/execution authority')
        return {'status_scope': SCOPE, 'physics_validated': False}, 'Complete declared NMSSM tree coupling/channel map only; native amplitude, perturbative accuracy, total widths, production and EFT matching remain unqualified.'
    if mode in ('ntuple-inventory', 'mc-expected-construction', 'mc-closure'):
        from ravel.physics import ntuple_inventory, mc_expected_construction, mc_closure
        SCOPE = ({'ntuple-inventory':ntuple_inventory,'mc-expected-construction':mc_expected_construction,'mc-closure':mc_closure}[mode]).SCOPE
        if result.get('status_scope') != SCOPE or any(result.get(k) is not False for k in
                ('physics_validated', 'execution_authorized', 'original_task_complete')):
            raise ValueError('Ntuple preparation cannot acquire whole-analysis authority')
        return {'status_scope': SCOPE, 'physics_validated': False}, 'Complete supplied ntuple inventory and nominal kernel preparation; ROOT processing, backgrounds, validation, discovery sensitivity and note remain separately governed.'
    if mode == 'asimov-sensitivity':
        from ravel.physics.asimov_sensitivity import SCOPE
        if result.get('status_scope')!=SCOPE or result.get('physics_validated') is not False or result.get('original_task_complete') is not False:
            raise ValueError('paired Asimov delivery cannot acquire whole-analysis/physics authority')
        if result.get('status')=='passed':
            diagnostic=result['inference']['delivery']['diagnostic']
            if diagnostic['coverage_qualified'] is not False or diagnostic['optimizer_globality_qualified'] is not False or diagnostic['observed_significance'] is not None or diagnostic['global_significance'] is not None:
                raise ValueError('expected local proxy cannot acquire observed/global discovery authority')
        return {'status_scope':SCOPE,'physics_validated':False}, 'Same-source Asimov null/free diagnostic only; full fit/state/auxiliary custody, no observed/global significance, calibration or optimizer globality.'
    if mode == 'root-stream':
        from ravel.physics.root_stream import SCOPE
        if result.get('status_scope') != SCOPE or result.get('physics_validated') is not False:
            raise ValueError('stream delivery cannot acquire physics qualification')
        return {'status_scope':SCOPE,'physics_validated':False}, 'Complete source member-entry streaming and conditional weighted moments only; no native ABI, analysis-law, detector, background, likelihood or sensitivity qualification.'
    if mode == 'full-auxiliary-calibration':
        if result.get('physics_validated') is not False:
            raise ValueError('calibration delivery cannot acquire physics authority')
        if result.get('status') == 'passed':
            delivery=result['inference']['delivery']
            if delivery.get('coverage_qualified') is not False or delivery.get('optimizer_globality_qualified') is not False:
                raise ValueError('calibration diagnostic cannot acquire globality/coverage qualification')
        return {'status_scope':'pointwise_full_auxiliary_calibration_delivery','coverage_qualified':False,'optimizer_globality_qualified':False}, 'Full fixed-truth repeated-sampling diagnostics and unresolved-slot envelopes only; not uniform coverage, calibrated CLs or optimizer globality.'
    if mode=='published-classifier':
        from ravel.physics.published_classifier import SCOPE
        if (result.get('status_scope')!=SCOPE or result.get('physics_validated') is not False or
                any(result.get(k) is not False for k in ('training_executed','native_bitwise_equivalence','calibration_qualified'))):
            raise ValueError('published classifier cannot acquire training/calibration/physics authority')
        return {'status_scope':SCOPE,'physics_validated':False}, 'Published source feature/inference/weighted quantity delivery only; native equivalence, applicability and calibration require independent review.'
    if mode in ('analysis-response-features','classifier-inputs'):
        if result.get('status')!='passed' or result.get('physics_validated') is not False:
            raise ValueError('source/feature delivery must preserve its limited successful scope')
        if mode=='analysis-response-features' and (result.get('new_native_calls')!=0 or result.get('native_noninterference_qualified') is not False):
            raise ValueError('retained observation cannot infer native or calibration qualification')
        if mode=='classifier-inputs' and result.get('inference_executed') is not False:
            raise ValueError('classifier preparation cannot infer native inference')
        return {'status_scope':'source_and_retained_feature_delivery','physics_validated':False}, 'Source or complete supplied native observations only; detector/inference accuracy, noninterference and inference qualification remain separate.'
    if mode=='llp-plane-recipe':
        if (result.get('status_scope')!='supplied_llp_plane_recipe_construction' or
                any(result.get(k) is not False for k in ('physics_validated','execution_authorized','original_task_complete')) or
                any(result.get(k)!=0 for k in ('generated_events','fits')) or
                result.get('prepared_cells',-1)+result.get('blocked_cells',-1)!=len(result.get('cells',[]))):
            raise ValueError('LLP construction cannot acquire physics/execution or parent-task authority')
        return {'status_scope':result['status_scope'],'original_task_complete':False}, 'Complete supplied LLP mass/spectrum/lifetime population and conditional response moments only; charged calibration, sampling-law validity and likelihood/physics qualification remain source obligations.'
    if mode=='mass-width-grid':
        if (result.get('status_scope')!='supplied_whole_mass_width_grid_construction' or any(result.get(k) is not False for k in ('physics_validated','execution_authorized','original_task_complete')) or any(result.get(k)!=0 for k in ('generated_events','fits'))):
            raise ValueError('width input construction cannot acquire original-task or inference authority')
        return {'status_scope':result['status_scope'],'original_task_complete':False}, 'Complete supplied mass/width input construction only; original reproduction, response, interference, native parity and interval calibration remain separate.'
    if mode=='svj-recipe':
        from .svj_recipe import SCOPE
        if (result.get('status_scope')!=SCOPE or
                any(result.get(k) is not False for k in ('physics_validated','execution_authorized','original_task_complete')) or
                any(result.get(k)!=0 for k in ('generated_events','fits')) or
                result.get('prepared_cells',-1)+result.get('blocked_cells',-1)!=len(result.get('cells',[]))):
            raise ValueError('SVJ recipe construction cannot acquire execution/physics or whole-task authority')
        return {'status_scope':result['status_scope'],'original_task_complete':False}, 'Complete supplied parameter/scenario recipe; missing source, response and likelihood inputs remain explicit. No events, fits, ROC or luminosity projection.'
    if mode == 'numerical-reference-check':
        if result.get('status_scope') != 'supplied_heldout_numerical_comparison' or any(result.get(k) is not False for k in ('physics_validated', 'oracle_independence_proven', 'withholding_chronology_verified')):
            raise ValueError('supplied numerical comparison cannot acquire independent physics authority')
        return {'status_scope': result['status_scope'], 'oracle_independence_proven': False, 'withholding_chronology_verified': False}, 'Complete supplied held-out deck comparison; physical applicability, oracle independence and withholding chronology remain unqualified.'
    if mode == 'contur-companion':
        from ravel.physics.contur_companion import SCOPE
        if (result.get('status_scope') != SCOPE or result.get('kind') != 'native-contur-companion'
                or any(result.get(k) is not False for k in ('physics_validated', 'calibration_qualified', 'original_task_complete'))):
            raise ValueError('native Contur companion cannot acquire calibration or scientific authority')
        return {'status_scope': SCOPE, 'physics_validated': False}, 'Original native SM/Herwig/plot delivery only; source applicability, native ABI, uncertainty calibration and original-task acceptance require independent evidence.'
    if mode == 'finite-integrals':
        if result.get('status_scope')!='finite_scalar_integral_delivery' or result.get('qualified_enclosure') is not False or result.get('numerical_qualification')!='unknown' or result.get('oracle_independence_proven') is not False:
            raise ValueError('finite integral production cannot acquire numerical enclosure or independent qualification')
        return {'status_scope':result['status_scope'],'qualified_enclosure':False}, 'Native finite scalar integral values and reported QMC errors only; independent accuracy and model interpretation remain unqualified.'
    if mode == 'eft-toolchain':
        if (result.get('status_scope') != 'eft-toolchain-fixed-point-delivery' or result.get('physics_validated') is not False
                or result.get('automatic_redo') is not False or any(result.get(k) != 'unknown' for k in
                ('eft_applicability','numerical_qualification','coverage_calibration','interval_qualification'))):
            raise ValueError('EFT fixed-point delivery cannot acquire physics/interval qualification')
        return {'status_scope':result['status_scope'],'physics_validated':False}, ('Native EFT running/matching and fixed precision quantities only. '
            'Physical matching, numerical accuracy and statistical interpretation require independent evidence.')
    if mode=='sfitter-observed-events':
        if result.get('status_scope')!='sfitter_observed_event_rate_delivery' or any(result.get(k) is not False for k in ('physics_validated','execution_authorized','native_fit_completed','sampling_law_validated','independence_proven')) or result.get('native_calls')!=0:
            raise ValueError('observed-event transport cannot acquire native/physics/sampling authority')
        return {'status_scope':result['status_scope'],'physics_validated':False}, 'Complete source-bound LHE/analysis joins and explicit group sampling estimator only; generator, selection, detector, EFT and inference qualification remain separate.'
    if mode=='sfitter-scan-extraction':
        if result.get('status_scope')!='sfitter_signed_scan_extraction' or any(result.get(k) is not False for k in ('physics_validated','execution_authorized','native_fit_completed','independence_proven')):
            raise ValueError('scan extraction cannot acquire physics/fit/independence authority')
        return {'status_scope':result['status_scope'],'physics_validated':False}, ('Complete supplied signed scan extraction. Rank, condition, covariance and residual diagnoses remain explicit; native fit/MC likelihood and source/physics qualification are separate.')
    if mode=='eft-convention-transport':
        if (result.get('status_scope')!='eft-convention-algebra-delivery' or result.get('physics_validated') is not False or
            result.get('physical_basis_equivalence')!='unknown' or result.get('eft_applicability')!='unknown' or
            any(result.get(k) is not False for k in ('rge_applied','normalization_applied','uncertainties_changed','execution_authorized'))):
            raise ValueError('EFT convention algebra cannot acquire scientific or execution authority')
        return {'status_scope':result['status_scope'],'physics_validated':False}, ('Exact supplied coefficient-coordinate algebra. '
            'Physical basis equivalence, EFT applicability and downstream numerical/statistical qualification remain unknown.')
    if mode == 'sfitter-native-fit':
        if result.get('status_scope') != 'sfitter-native-delivery' or result.get('physics_validated') is not False or result.get('automatic_redo') is not False or any(result.get(k) != 'unknown' for k in ('profile_search_qualification','interval_qualification','eft_applicability','coverage_calibration')):
            raise ValueError('native SFitter delivery cannot acquire scientific qualification')
        return {'status_scope':'sfitter-native-delivery','physics_validated':False}, ('Native SFitter delivery only. The raw score/profile convention is retained. '
            'Convergence, globality, intervals, coverage and EFT applicability remain unknown; no retry is authorized.')
    if mode=='analyze' and result.get('kind')=='agentrivet-source-materialization':
        if (result.get('candidate_disposition')!='unreviewed_source' or
                result.get('prior_reviews_carried')!=[] or
                result.get('execution_authorized') is not False or result.get('physics_validated') is not False):
            raise ValueError('supplied AgentRivet source must retain unreviewed scope')
        return {'status_scope':'supplier_source_materialization_delivery',
            'candidate_disposition':'unreviewed_source','prior_reviews_carried':[],
            'execution_authorized':False,'physics_validated':False}, (
                'Completed supplier-source materialization, including domain declarations. '
                'Independent paper/dependency/runtime/build/event review remains required.')
    if mode=='analyze' and result.get('kind')=='native-construction-materialization':
        if (result.get('candidate_disposition')!='unreviewed_source' or
                result.get('prior_reviews_carried')!=[] or
                result.get('execution_authorized') is not False or result.get('physics_validated') is not False):
            raise ValueError('native source materialization must retain unreviewed challenger scope')
        return {'status_scope':'native_source_materialization_delivery',
            'candidate_disposition':'unreviewed_source','prior_reviews_carried':[],
            'execution_authorized':False,'physics_validated':False}, (
                'Completed source-only materialization. The challenger remains unreviewed and requires '
                'fresh dependency/runtime/build/event plans and independent reviews; incumbent votes are history.')
    if mode == 'analyze' and result.get('kind') == 'routine-construction-feedback':
        disposition = result.get('candidate_disposition')
        triggers = {'typed_compiler_refused': {'typed_compiler'},
                    'native_build_refused': {None, 'native_compiler'},
                    'event_mismatch': {'event_selection'},
                    'verified_on_supplied_events': {None}}
        source_scope = result.get('source_scope')
        if (disposition not in triggers or result.get('failure_trigger') not in triggers[disposition]
                or result.get('physics_validated') is not False
                or result.get('execution_authorized') is not False
                or not isinstance(source_scope, dict)
                or source_scope.get('kind') not in ('complete_routine', 'supplied_object_port')
                or not isinstance(result.get('source_dependency_review'), dict)):
            raise ValueError('routine construction must retain candidate disposition, source scope and authority boundaries')
        fields = {key: result[key] for key in ('candidate_disposition', 'failure_trigger',
                  'source_scope', 'source_dependency_review', 'execution_authorized', 'physics_validated')}
        fields['status_scope'] = 'construction_diagnostic_delivery'
        return fields, ('Candidate disposition: ' + disposition + '. Diagnostic delivery records '
                        'the compiler and supplied-event outcome. It does not approve the candidate '
                        'as a complete physical analysis or authorize further execution.')
    if mode != 'model-inputs':
        return {}, ''
    disposition = result.get('preflight_disposition')
    details = result.get('details')
    policy = result.get('downstream_policy')
    scope = result.get('status_scope')
    if (disposition not in ('static_inventory', 'refused')
            or not isinstance(scope, str) or not scope.strip()
            or not isinstance(details, dict) or not isinstance(details.get('findings'), list)
            or details.get('preflight_disposition') != disposition
            or result.get('execution_authorized') is not False
            or not isinstance(policy, dict) or policy.get('execution_authorized') is not False
            or policy.get('physics_validated') is not False
            or policy.get('source_findings_do_not_set_workflow_approval') is not True):
        raise ValueError('model-input diagnosis must preserve source disposition and downstream authority boundaries')
    if disposition == 'refused' and not details['findings']:
        raise ValueError('refused model-input diagnosis requires retained source findings')
    return {'status_scope': scope, 'preflight_disposition': disposition,
            'source_findings': details['findings'], 'downstream_policy': policy}, (
                'Source disposition: ' + disposition + '. Diagnostic delivery does not accept '
                'the card or authorize model execution. Review every retained source finding.')


def main(argv=None):
    worker_started=time.monotonic()
    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (1, 3, 5) or len(args) > 1 and args[1] != '--attempt' or len(args) == 5 and args[3] != '--correction-sha256':
        raise ValueError('one approved run directory and its exact selected attempt required')
    rd = Path(args[0]).resolve()
    from ravel.workflow.science import prepare_readonly_worker
    preparation = prepare_readonly_worker(rd, verifier=verify_worker,
        attempt=args[2] if len(args) > 1 else None,
        correction_sha256=args[4] if len(args) == 5 else None)
    proposal, prepared = (verify_worker(rd), None) if preparation is None else preparation
    if len(args) > 1 and (str(proposal.get('attempt')) != args[2]
            or len(args) == 5 and args[4] != read_json(rd / 'execution_attempt.json').get('correction_plan_sha256')):
        raise ValueError('worker arguments differ from the exact admitted attempt')
    spec = execution_spec(rd) if prepared is None else prepared.specification
    out = rd / proposal.get('output_directory', 'outputs')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(exist_ok=False)
    mode, task, base = spec['mode'], spec['task'], Path(proposal['base_dir'])
    if prepared is not None:
        implementation = adapter(spec)
        destination = out if not prepared.fresh_directory else out / mode
        result = prepared.write(destination)
    elif mode == 'quantities':
        import json
        from ravel.physics.quantities import calculate
        contract = read_json(regular(task['contract'], base))
        # Strict JSON per row, including duplicate keys and nonfinite numbers.
        from ravel.workflow.state_io import _unique
        def reject(s):
            raise ValueError('nonfinite record: ' + s)
        with regular(task['records'], base).open() as stream:
            records = (json.loads(line, object_pairs_hook=_unique, parse_constant=reject) for line in stream if line.strip())
            result = calculate(contract, records)
        atomic_json(out / 'quantities.json', result)
        result = {'status': 'passed', 'physics_validated': False, 'quantities': result,
                  'scope': 'Declared weighted bin quantities and conditional group MC covariance',
                  'limitations': ['Weight semantics and fills are supplied; this does not validate an event generator.']}
    else:
        # These adapters own a fresh directory and reject existing outputs.
        # The worker already owns the attempt directory for its common records.
        destination = out / mode if mode in ('ntuple-inventory', 'mc-expected-construction', 'mc-closure', 'manuscript-build', 'task-completion-context', 'root-stream', 'tree-array-export', 'parameter-space-sampling', 'dataset-query-quantities', 'published-classifier', 'mssm-observable-map', 'nmssm-yukawa-map', 'analysis-response-features', 'classifier-inputs', 'measurement', 'contur-import', 'normalized-measurement',
                                           'ratio-measurement', 'group-normalization', 'group-composition', 'source-tables', 'mass-width-grid', 'svj-recipe', 'llp-plane-recipe', 'scientific-delivery', 'published-summary', 'native-group-acquisition', 'retained-shower', 'numerical-reference-check', 'cosmology-solver', 'finite-integrals', 'cosmic-evolution', 'derived-quantities', 'workspace-combination-study', 'cr-signal-qualification', 'diagrammatica-code', 'feyn-graph', 'diagram-analysis', 'ma5-saf', 'background-discrete-profile', 'native-statistical-construction') else out
        if spec['schema_version'] == 2 and mode == 'analyze' and task.get('backend') in ('rivet', 'rivet-built'):
            destination = out / 'analysis'
        implementation=adapter(spec)
        run_in_worker=getattr(implementation,'run_in_worker',None)
        result=(implementation.run(task,base,destination) if run_in_worker is None else
            run_in_worker(task,base,destination,worker_started=worker_started))
    predictive_guard = None
    if mode == 'quantitative-predictive':
        predictive_guard = implementation.Guard(result, task, base, out)
    stream_guard = None
    if mode == 'root-stream':
        from ravel.physics.root_stream import guard
        stream_guard = guard(result, destination)
    # No module may silently upgrade adapter delivery to scientific certification.
    if result.get('physics_validated') is not False:
        raise ValueError('adapter must state its scientific evidence boundary')
    status = result.get('status')
    if status not in ('passed', 'failed'):
        raise ValueError('adapter result lacks an explicit postcondition status')
    diagnostic_fields, diagnostic_text = diagnostic_presentation(mode, result)
    publications = None
    emit_json = atomic_json
    if mode == 'literal-calculation':
        from ravel.physics.literal_calculation import Publications
        publications = Publications(out)
        emit_json = publications.json
    if mode == 'cosmic-evolution':
        from ravel.physics.cosmic_evolution_core import Publications
        from ravel.physics.cosmic_evolution import _capture
        publications = Publications(_capture(task, base)[1]['resources'])
        emit_json = publications.json
    if mode == 'analysis-response-features':
        from ravel.physics.analysis_response_features import _Emitted
        _Emitted(out).json(out / 'result.json', result)
    elif mode == 'root-stream':
        from ravel.physics import root_stream
        # The root-stream guard binds canonical promised bytes, not only JSON values.
        root_stream.write_new(out / 'result.json', result)
    elif mode == 'domain' and task.get('domain') == 'detector-response':
        from ravel.physics.detector_response import write_complete_json
        write_complete_json(result, out / 'result.json')
    else:
        emit_json(out / 'result.json', result)
    quantitative_delivery = None
    if 'quantitative_check' in spec:
        from ravel.workflow.quantitative_predictive_checks import Delivery
        quantitative_delivery = Delivery(spec['quantitative_check'], base, out / 'result.json', status == 'passed')
        quantitative_delivery.write(out / 'quantitative-check.json')
    from ravel.plotting.science_figures import render
    figure_out = destination if mode == 'analyze' and spec['schema_version'] == 2 and task.get('backend') in ('rivet', 'rivet-built') else out
    figures = render(spec, result, base, figure_out)
    if figure_out != out:
        prefix = figure_out.relative_to(out).as_posix() + '/'
        for artifact in [*figures.get('figures', []), *figures.get('tables', [])]:
            artifact['stem'] = prefix + artifact['stem']
            artifact['files'] = [prefix + name for name in artifact['files']]
    emit_json(out / 'figures.json', figures)
    emit_json(out / 'recipe.json', {'specification': spec, 'input_snapshot': proposal['stage_binding']['input_snapshot'],
                                     'sha256': execution.digest(spec)})
    emit_json(out / 'verification.json', {'passed': status == 'passed', 'scope': mode,
        'physics_validated': False, 'expert_review': False, 'result_sha256': execution.file_hash(out / 'result.json'),
        **diagnostic_fields})
    emit_json(out / 'checkin2.json', {'schema_version': 1, 'kind': 'checkin2', 'sections': {
        'waypoint': {'scope': mode, 'status': status, 'result': (out / 'result.json').relative_to(rd).as_posix(),
                     **diagnostic_fields},
        'expectation': 'Review the declared quantities and comparisons. Adapter checks do not establish detector fidelity, paper closure or expert review.' + (' ' + diagnostic_text if diagnostic_text else ''),
        'ask': {'options': ['GO', 'ADJUST'], 'scope': 'Any follow-up calculation requires its own concrete plan and approval.'}}})
    (publications.text if publications is not None else lambda p, t: p.write_text(t))(out / 'RESULT.md', '# Scientific adapter result\n\n' + mode + ': ' + status + '.\n\n' +
        (diagnostic_text + '\n\n' if diagnostic_text else '') +
        ''.join('![Diagnostic](' + f['stem'] + '.png)\n\n' for f in figures.get('figures', [])) +
        ''.join('[' + Path(name).name + '](' + name + ')\n\n'
                for table in figures.get('tables', []) for name in table['files']) +
        ('The complete quantitative diagnostics are in [quantitative-check.md](quantitative-check.md) and quantitative-check.json.\n\n' if quantitative_delivery is not None else '') +
        'The values, postconditions and limitations are in `result.json`. The exact input identities are in '
        '`recipe.json`; review `checkin2.json` before additional work.\n\nAssumptions:\n\n' +
        '\n'.join('- ' + a for a in spec['assumptions']) + '\n\nNo paper reproduction or physics certification is inferred.\n')
    if stream_guard is not None:
        for table in figures.get('tables', []):
            stream_guard.publications.extend(table['intended_commitments'])
        stream_guard.finish(result, common=out)
        capture=root_stream.core.Capture();config_path,_,_,analysis=root_stream._load(task,base,capture)
        if analysis['blinding'] is not None and result['status']=='passed':
            declaration=analysis['blinding']['source'];policy_path,_=capture.read(declaration,config_path.parent)
            accepted={**declaration,'path':str(policy_path)}
            paths=[str(out/name) for name in ('result.json','root-stream-report.json','root-stream-report.md')]
            observation=root_stream.blinding_check(result,destination,paths,accepted)
            stream_guard.publications.append(root_stream.write_new(out/'root-stream-blinding-check.json',observation))
        capture.finish();stream_guard.finish(result,common=out)
    if mode == 'tree-array-export':
        from ravel.physics.tree_array_export import finalize
        finalize(result, destination, common=out)
    if mode == 'cosmic-evolution':
        for table in figures.get('tables', []):
            row = table['intended_commitment']
            publications.rows[row['pin']['path']] = row
        implementation.finish_delivery(result, task, base, destination)
        publications.finish()
    if mode == 'model-events':
        from ravel.physics.model_event_commitment import finalize
        finalize(result, out)
    if mode in ('feyn-graph','diagram-analysis'):
        implementation.finalize(result,destination,common=out)
    if mode in ('symbolic-evaluation','feynarts-amplitude'):
        from ravel.physics.symbolic_evaluation import finalize
        finalize(result, out)
    if mode == 'literal-calculation':
        from ravel.physics.literal_calculation import validate_result
        validate_result(result, task, base)
        publications.finish()

    if predictive_guard is not None:
        predictive_guard.finish(result)
    if quantitative_delivery is not None:
        quantitative_delivery.finish()
    if prepared is not None:
        prepared.check_delivery(destination, out, result)
    return 0 if status == 'passed' else 3


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError, ImportError, RuntimeError) as exc:
        print('Scientific study failed: ' + str(exc), file=sys.stderr)
        sys.exit(2)
