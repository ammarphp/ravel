"""Interference measurement instance of an existing research parent.

``prepare`` retains a literal original question, supplied conventions, component
documents and their signatures. ``run`` composes Python quantity adapters and
requires injected ordinary-study runners for integration and event analysis.
With no runner those stages are held; this module never launches native tools or
grants approval. Runners use ``(stage, *, base_dir, output_dir, goal_binding)``.

Completed receipts are verified on resume. An effect without a receipt is held
for reconciliation, not replayed. Native same-run survey restoration remains the
``model-events`` integration_checkpoint interface; Gram integration resumes its
existing schedule. These services retain their own approvals and reservations.
The scientific methodology and whole-parent acceptance remain separate gates.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np

from ravel.workflow import research_cycle as custody, research_protocol, state_io, task_completion
from . import amplitude_basis as ab, amplitude_integration as integration, amplitude_polynomial, rivet_fit
from . import amplitude_predictions as predictions, amplitude_records, amplitude_store as store, weighted_events, yield_hub
from .inference import applicability, common, differential, differential_likelihood, documents, gof, intervals, record

INSTANCE = 'interference-measurement'
STAGES = (
    ('conventions', 'amplitude-interference-context'),
    ('integration', 'amplitude-integration'),
    ('events', 'weighted-events'),
    ('predictions', 'amplitude-predictions'),
    ('interference', 'amplitude-interference-check'),
    ('inference', 'differential-likelihood'),
    ('ablation', 'differential-likelihood'),
    ('deliverable', 'amplitude-interference-delivery'),
)
DOCUMENTS = ('conventions', 'integration', 'events', 'predictions', 'measurement', 'comparison')
NATIVE = {'amplitude-integration', 'weighted-events'}


def _read(pin):
    return custody._read(pin, Path(pin['path']).parent)


def _check(pin):
    custody._check_pin(pin, Path(pin['path']).parent)


def _write(path, value):
    path = custody._ordinary(path)
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    expected = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    ab.require(custody._pin(path) == expected, 'emitted interference artifact changed')
    return expected


def _signature(operation):
    from ravel.validation.validate_request_plan import registry
    entry = registry().get(operation)
    source = 'operation_signatures'
    if entry is None:
        source = 'owned-seam'
        entry = {'implementation': {'kind': 'research-instance-helper', 'module': __name__},
                 'operation': operation, 'effects': []}
    raw = json.dumps(entry, sort_keys=True, allow_nan=False).encode()
    return {'source': source, 'sha256': hashlib.sha256(raw).hexdigest(), 'entry': entry}


def instances():
    """Registration seam for the parent coordinator; no prompt identity routing."""
    return [{'schema_version': 1, 'kind': 'research-parent-instance', 'id': INSTANCE,
             'module': __name__, 'entrypoints': ['prepare', 'run'], 'execution_authorized': False,
             'stages': [{'id': name, 'operation': op, 'signature': _signature(op)} for name, op in STAGES],
             'methodology_stages': [s['id'] for s in research_protocol.default_protocol()['stages']],
             'continuation': {'model-events': 'integration_checkpoint (same run, original reservation)',
                              'amplitude-integration': 'completed warmups and blocks in the original Gram store'}}]


def _sources():
    return [custody._pin(m.__file__) for m in (ab, integration, predictions, amplitude_records, store, weighted_events,
        yield_hub, amplitude_polynomial, rivet_fit, differential_likelihood, common, differential, documents, intervals, gof, applicability,
        record, research_protocol, task_completion, custody, state_io)] + [custody._pin(__file__)]


def _measurement(request):
    """Resolve supplied file-backed vectors/matrices from their original base."""
    ctx = documents.Context(request['measurement']['path'], Path.cwd())
    value = deepcopy(ctx.document)
    value['measurement']['values'] = ctx.vector(value['measurement']['values'], 'measured values').tolist()
    for component in value['covariance']:
        component['matrix'] = ctx.matrix(component['matrix'], 'measurement covariance').tolist()
    for nuisance in value.get('nuisances', []):
        for name in ('shift', 'relative'):
            if isinstance(nuisance.get(name), (list, dict)):
                nuisance[name] = ctx.vector(nuisance[name], 'nuisance ' + name).tolist()
    return value, [custody._pin(p['path']) for p in ctx.inputs()]


def _validate(request):
    required = {'schema_version', 'kind', 'question', 'goal_binding', 'histogram', *DOCUMENTS}
    ab.require(type(request) is dict and required <= set(request) <= required | {'born_comparison'}, 'complete interference research request required')
    ab.require(request['schema_version'] == 1 and request['kind'] == 'interference-research-request',
               'interference research request version 1 required')
    parent = task_completion.binding_projection(request['goal_binding'], base_dir=Path.cwd())
    ab.require(request['question'] == parent['original_request'], 'preserve the complete original question')
    docs = {name: _read(request[name]) for name in DOCUMENTS}
    conventions = docs['conventions']
    ab.require(conventions.get('schema_version') == 1 and conventions.get('kind') == 'interference-conventions',
               'supplied interference conventions required before amplitude choices')
    ab.text(conventions.get('phase_convention'), 'phase_convention')
    ab.require(conventions.get('interference_definition') == '2 Re(A_fixed* A_scaled)',
               'interference convention must state the signed cross term')
    for name in ('assumptions', 'interpretation_traps'):
        ab.require(type(conventions.get(name)) is list and conventions[name], f'supplied {name} required')
        for row in conventions[name]:
            ab.text(row, name)
    rivet_fit.tolerance(request.get('born_comparison'))
    pred, events, measurement = (docs[n] for n in ('predictions', 'events', 'measurement'))
    ab.require(pred.get('kind') == 'amplitude-predictions' and pred.get('coupling_scaling'),
               'predictions must declare a coupling polynomial')
    ids = [h['id'] for h in pred['hypotheses']]
    ab.require(len(ids) >= 2 and pred['reference'] in ids and len(set(ids)) == len(ids),
               'distinct hypotheses and an existing reference required')
    scaled = pred['coupling_scaling']['states']
    ab.require(len(set(scaled)) == len(scaled) and scaled and all(type(i) is int and i >= 0 for i in scaled),
               'distinct scaled state indices required')
    reference = next(h for h in pred['hypotheses'] if h['id'] == pred['reference'])
    ab.require(not any(i < len(reference['states']) for i in scaled), 'reference cannot contain scaled states')
    for hypothesis in pred['hypotheses']:
        if hypothesis['id'] != pred['reference']:
            ab.require(all(i < len(hypothesis['states']) for i in scaled), 'scaled states must exist in every tested hypothesis')
    ab.require(events.get('kind') == 'weighted-events' and events.get('operation') == 'rivet',
               'weighted-events RAW analysis required')
    histogram = next((h for h in events['rivet']['histograms'] if h['path'] == request['histogram']), None)
    ab.require(histogram is not None and histogram['representation'] == pred['normalization']['representation']
               and events['unit'] == pred['normalization']['unit'], 'RAW and prediction units/representation differ')
    ab.require('factor' not in pred['normalization'], 'RAW handoff requires absolute normalization without an extra factor')
    for name in ('hypotheses', 'reference', 'reference_description', 'coupling_scaling'):
        ab.require(events.get(name) == pred[name], 'event and prediction hypothesis/reference contracts differ')
    root = Path(request['predictions']['path']).parent
    store_dir = predictions._regular(pred['store'], root)
    for name in ('integration', 'events'):
        ab.require(predictions._regular(docs[name]['store'], Path(request[name]['path']).parent) == store_dir,
                   'every amplitude stage must use the same store')
    ab.require(docs['integration']['operation'] == 'blocks', 'block integration required')
    ab.require(measurement.get('schema_version') == 1 and measurement.get('kind') == 'interference-measurement-input',
               'supplied measurement and covariance required')
    statistic = measurement['statistic']
    if statistic.get('verbatim') is None:
        toys = statistic.get('toys') or {}
        ab.require(toys.get('method') == 'cls' and toys.get('confidence_level') == .95,
                   'an unprescribed exclusion requires 95% CLs')
    else:
        ab.text(statistic['verbatim'], 'prescribed statistic')
    unit = pred['normalization']['unit']
    if pred['normalization']['representation'] == 'differential':
        unit += '/' + pred['observable']['unit']
    ab.require(measurement['measurement']['unit'] == unit, 'measurement and prediction units differ')
    edges, _ = predictions._edges(pred['binning'], root)
    ab.require(measurement['measurement'].get('bin_edges') == edges.tolist(), 'measurement and prediction bin edges differ')
    ab.require(measurement['observable']['name'] == pred['observable']['name'] and
               measurement['observable']['unit'] == pred['observable']['unit'], 'measurement observable differs')
    ab.require(measurement['scan']['parameter'] == pred['coupling_scaling']['parameter'], 'measurement scan parameter differs')
    comparator = docs['comparison']
    ab.require(comparator.get('schema_version') == 1 and comparator.get('kind') == 'interference-comparator',
               'supplied comparison required')
    ab.require(comparator['statistic'] == measurement['statistic'], 'comparison statistic differs')
    for field in ('quantity', 'unit', 'source'):
        ab.text(comparator.get(field), 'comparison ' + field)
    ab.require(bool(comparator.get('values')), 'supplied comparison values required')
    # Capture external members before the first effect; documents alone are not
    # the integration card/component or a file-backed measurement's full closure.
    inputs = [*parent['input_pins'], *[request[n] for n in DOCUMENTS]]
    inputs += [custody._pin(p) for p in integration.inputs({'input': request['integration']['path']}, root)]
    docs['measurement'], measurement_inputs = _measurement(request)
    inputs += measurement_inputs
    for pin in inputs:
        _check(pin)
    return docs, inputs, parent


def prepare(request, output_dir):
    """Prepare a registered instance without running any tool or approving a child."""
    docs, inputs, parent = _validate(request)
    output_dir = custody._ordinary(output_dir)
    ab.require(not output_dir.exists(), 'fresh interference parent instance directory required')
    manifest = {'schema_version': 1, 'kind': 'interference-research-parent', 'instance': instances()[0],
                'request': deepcopy(request), 'input_pins': inputs, 'source_pins': _sources(),
                'parent_task': parent, 'execution_authorized': False, 'parent_task_accepted': False}
    pin = _write(output_dir / 'interference-parent.json', manifest)
    research_protocol.bind_default(output_dir, regime='open_exploratory')
    return pin


def audit_interference(task, base, prediction_pin):
    """Check signed terms using quadratic evaluations at opposite amplitude signs.

    I = (|A_fixed+A_scaled|^2 - |A_fixed-A_scaled|^2)/2. This
    independently checks the producer's explicit bilinear cross term on the
    same stored points; it is an algebra/custody witness, not amplitude accuracy.
    Bins and both flows are checked, with representation and input hashes bound.
    """
    ctx = predictions.load(task, base)
    record = _read(prediction_pin)
    inputs = [custody._pin(p) for p in predictions.inputs(task, base)]
    expected = {(p['path'], p['sha256']) for p in inputs}
    ab.require({(p['path'], p['sha256']) for p in record['inputs']} == expected, 'prediction inputs differ')
    doc = ctx['doc']
    ab.require(record['normalization'] == doc['normalization'] and record['edges'] == ctx['edges'].tolist()
               and record['selection'] == doc['selection'] and record['observable'] == doc['observable'],
               'prediction quantity contract differs')
    scaling = doc['coupling_scaling']
    definitions = []
    for hypothesis in ctx['hypotheses']:
        if hypothesis['id'] == doc['reference']:
            continue
        fixed, scaled = predictions._split(hypothesis, scaling['states'])

        def witness(gram, invariant, fixed=fixed, scaled=scaled):
            c0 = ab.coefficients(fixed, ctx['basis'], invariant)
            c1 = ab.coefficients(scaled, ctx['basis'], invariant)
            return (ab.evaluate(gram, c0 + c1) - ab.evaluate(gram, c0 - c1)) / 2.
        definitions.append((hypothesis['id'], 'witness', witness))
    cohorts, census = predictions.block_vectors(ctx, definitions)
    joint = ab.centered_blocks(cohorts)
    nb = len(ctx['edges']) - 1
    divide = np.diff(ctx['edges']) if doc['normalization']['representation'] == 'differential' else np.ones(nb)
    result = {}
    for index, (name, _, _) in enumerate(definitions):
        mean = joint['mean'][index * (nb + 2):(index + 1) * (nb + 2)]
        reference = np.r_[mean[:nb] / divide, mean[nb:]]
        term = record['streams'][name + ':interference']
        observed = np.asarray([*term['values'], term['underflow'], term['overflow']], dtype=float)
        ab.require(observed.shape == reference.shape and np.isfinite(observed).all()
                   and np.allclose(observed, reference, rtol=1e-9, atol=1e-12 * max(float(np.max(np.abs(reference))), 1e-300)),
                   f'interference sign or size differs for {name}')
        result[name] = {'values': term['values'], 'signs': [int(np.sign(v)) for v in term['values']],
                        'underflow': term['underflow'], 'overflow': term['overflow'],
                        'max_abs': float(np.max(np.abs(observed))), 'witness': reference.tolist(),
                        'max_abs_residual': float(np.max(np.abs(observed - reference))),
                        'mc_uncertainty': term['uncertainty']}
    for pin in [*inputs, prediction_pin]:
        _check(pin)
    return {'schema_version': 1, 'kind': 'interference-sign-size', 'status': 'passed',
            'definition': '2 Re(A_fixed* A_scaled)', 'witness_definition': '(F(+1)-F(-1))/2',
            'hypotheses': result, 'inputs': inputs, 'prediction': prediction_pin,
            'coupling_scaling': scaling, 'hypothesis_inputs': doc['hypotheses'],
            'normalization': doc['normalization'], 'blocks': census, 'physics_validated': False,
            'scope': 'Signed-term consistency of the supplied stored amplitudes; not physical accuracy'}


def _selected(docs, ctx, raw):
    histogram = raw[docs['histogram']]
    selected = rivet_fit.selected_prediction(docs['events'], ctx['hypotheses'], histogram, edges=ctx['edges'])
    ab.require(selected['provenance']['histogram'] == docs['histogram'], 'RAW selected histogram differs')
    expected = [{'id': b['id'], 'cohort': b['cohort'], 'attempted': b['summary']['attempted'], 'events': b['points']}
                for b in ctx['manifest']['blocks']]
    ab.require(selected['census'] == expected, 'RAW exposure differs from the stored blocks')
    ab.require(histogram['provenance']['representation'] == ctx['doc']['normalization']['representation'],
               'RAW representation differs')
    return selected


def _quantity_parity(docs, prediction, raw):
    """Retain the Born comparison as a diagnostic, with explicit tolerances."""
    selected = rivet_fit.selected_prediction(docs['events'], docs['events']['hypotheses'], raw[docs['histogram']],
                                             edges=prediction['edges'])
    return rivet_fit.born_diagnostic(prediction, selected, declared_tolerance=docs.get('born_comparison'))


def _likelihood(docs, ctx, prediction, *, ablated):
    measurement = deepcopy(docs['measurement'])
    measurement['kind'] = 'differential-likelihood'
    fragment = rivet_fit.likelihood_input(docs['events'], ctx['hypotheses'], prediction, ablated=ablated)
    measurement['signal'] = fragment['signal']
    measurement['reference'] = fragment['reference_prediction']
    measurement['hypotheses'] = fragment['hypotheses']
    if ablated:
        # A nuisance referring to a removed term needs a new declared contract.
        ab.require(not measurement.get('nuisances'), 'interference ablation with nuisances requires an explicit arm mapping')
    return measurement


def run(parent_pin, *, runners=None):
    """Compose the instance; runner omissions hold, stale receipts refuse reuse."""
    manifest = _read(parent_pin)
    request = manifest['request']
    docs, current_inputs, parent = _validate(request)
    ab.require(manifest['instance'] == instances()[0], 'registered instance stages/signatures changed')
    ab.require(manifest['source_pins'] == _sources(), 'interference component source changed')
    ab.require(parent == manifest['parent_task'], 'original parent projection changed')
    for pin in manifest['input_pins']:
        _check(pin)
    ab.require(current_inputs == manifest['input_pins'], 'prepared input closure changed')
    docs = {**docs, 'histogram': request['histogram'], 'born_comparison': request.get('born_comparison')}
    out = Path(parent_pin['path']).parent
    progress_path = out / 'progress.json'
    progress = state_io.read_json(progress_path) if progress_path.exists() else []
    ab.require(type(progress) is list and len(progress) <= len(STAGES), 'complete stage receipt roster required')
    receipts = {}
    for index, row in enumerate(progress):
        name, operation = STAGES[index]
        receipt = _read(row['receipt'])
        ab.require(row['id'] == name and row['operation'] == operation and receipt['operation'] == operation
                   and receipt['goal_binding'] == request['goal_binding'], 'stage receipt assignment differs')
        for pin in [*receipt['inputs'], *receipt['outputs']]:
            _check(pin)
        receipts[name] = receipt
    final_path = out / 'deliverable.json'
    if len(progress) == len(STAGES):
        result = _read(receipts['deliverable']['outputs'][-1])
        ab.require(result['stages'] == progress[:-1], 'delivered receipt roster differs')
        final = {**result, 'stages': progress}
        final_pin = custody._pin(final_path)
        ab.require(_read(final_pin) == final, 'finished parent delivery changed')
        return {'status': 'passed', 'physics_validated': False, 'parent_task_accepted': False,
                'execution_authorized': False, 'deliverable': final_pin}
    runners = runners or {}
    for name, operation in STAGES[len(progress):]:
        if operation in NATIVE and operation not in runners:
            return {'status': 'held', 'held_stage': name, 'operation': operation,
                    'execution_authorized': False, 'stages': progress,
                    'reason': 'An ordinary approved component runner is required; instance preparation grants no execution authority.'}
        stage_dir = out / 'stages' / name
        ab.require(not stage_dir.exists(), 'unreceipted stage effect requires reconciliation; do not replay')
        stage_dir.mkdir(parents=True)
        upstream = [pin for receipt in receipts.values() for pin in receipt['outputs']]
        inputs = [parent_pin, *manifest['input_pins'], *upstream]
        if name == 'events':
            inputs += [custody._pin(p) for p in weighted_events.inputs({'input': request['events']['path']}, stage_dir)]
        elif name not in ('conventions', 'integration'):
            inputs += [custody._pin(p) for p in predictions.inputs({'input': request['predictions']['path']}, stage_dir)]
        if name == 'conventions':
            outputs = [_write(stage_dir / 'context.json', {'question': request['question'], 'parent_task': parent,
                       'conventions': docs['conventions'], 'execution_authorized': False})]
        elif operation in NATIVE:
            stage = {'id': name, 'operation': operation, 'input': request[name], 'signature': _signature(operation)}
            result = runners[operation](stage, base_dir=Path(request[name]['path']).parent,
                                        output_dir=stage_dir, goal_binding=deepcopy(request['goal_binding']))
            ab.require(result['status'] == 'passed', f'{name} component did not pass')
            if name == 'integration':
                ctx = integration.load({'input': request[name]['path']}, stage_dir)
                sm = store.store_blocks(ctx['store'])
                ab.require(sm['status'] == 'complete', 'integration store is incomplete')
                outputs = [custody._pin(stage_dir / 'integration.json'), custody._pin(ctx['store'] / store.MANIFEST)]
            else:
                outputs = [custody._pin(stage_dir / 'weighted-events.json'), custody._pin(stage_dir / 'predictions.json')]
        elif name == 'predictions':
            predictions.run({'input': request[name]['path']}, stage_dir, stage_dir)
            outputs = [custody._pin(stage_dir / 'predictions.json'), custody._pin(stage_dir / 'differential-likelihood-input.json')]
            raw = _read(receipts['events']['outputs'][1])
            ctx = predictions.load({'input': request['predictions']['path']}, stage_dir)
            selected = _selected(docs, ctx, raw)
            diagnostic = _quantity_parity(docs, _read(outputs[0]), raw)
            outputs += [_write(stage_dir / 'born-rivet-diagnostic.json', diagnostic),
                        _write(stage_dir / 'rivet-likelihood-input.json',
                               rivet_fit.likelihood_input(docs['events'], ctx['hypotheses'], selected))]
        elif name == 'interference':
            audit = audit_interference({'input': request['predictions']['path']}, stage_dir, receipts['predictions']['outputs'][0])
            outputs = [_write(stage_dir / 'interference.json', audit)]
        elif name in ('inference', 'ablation'):
            ctx = predictions.load({'input': request['predictions']['path']}, stage_dir)
            prediction = _selected(docs, ctx, _read(receipts['events']['outputs'][1]))
            document = _likelihood(docs, ctx, prediction, ablated=name == 'ablation')
            input_pin = _write(stage_dir / 'input.json', document)
            result = differential_likelihood.run({'input': input_pin['path']}, stage_dir, stage_dir)
            ab.require(result['status'] == 'passed', f'{name} inference remains unresolved')
            outputs = [custody._pin(stage_dir / 'inference.json'), input_pin]
        else:
            ctx = predictions.load({'input': request['predictions']['path']}, stage_dir)
            prediction = _selected(docs, ctx, _read(receipts['events']['outputs'][1]))
            signed = [yield_hub.write(stage_dir / (h['id'] + '-interference.json'),
                       weighted_events._binned(next(spec for spec in docs['events']['rivet']['histograms']
                                                   if spec['path'] == docs['histogram']), ctx['edges'].tolist(),
                                              h['id'] + ':interference', prediction['streams'][h['id'] + ':interference'],
                                              docs['events']['unit']))
                      for h in ctx['hypotheses'] if h['id'] != ctx['doc']['reference']]
            signed = [custody._pin(p['path']) for p in signed]
            checks = yield_hub.delivery_checks(out, path='stages/inference/inference.json')
            ab.require(not any(c['status'] == 'fail' for c in checks), 'yield delivery check failed')
            report = {'schema_version': 1, 'kind': 'interference-measurement-delivery', 'question': request['question'],
                'goal_binding': request['goal_binding'], 'stages': deepcopy(progress),
                'prediction': receipts['predictions']['outputs'][0],
                'fitted_prediction': receipts['events']['outputs'][1], 'fitted_stage': prediction['provenance'],
                'fitted_terms': receipts['predictions']['outputs'][3],
                'born_comparison': _read(receipts['predictions']['outputs'][2]), 'interference': _read(receipts['interference']['outputs'][0]),
                'inference': receipts['inference']['outputs'][0], 'ablation': receipts['ablation']['outputs'][0],
                'three_columns': {'ours': {'quantity': docs['comparison']['quantity'], 'unit': docs['comparison']['unit'],
                    'statistic': docs['measurement']['statistic'], 'source': receipts['inference']['outputs'][0],
                    'uncertainty': 'Supplied measured covariance and complete polynomial MC covariance; no coverage certification'},
                    'published': docs['comparison'],
                    'reproduced_reference': {'values': prediction['streams'][ctx['doc']['reference']]['values'],
                        'quantity': ctx['doc']['observable'], 'unit': docs['measurement']['measurement']['unit'],
                        'mc_uncertainty': prediction['streams'][ctx['doc']['reference']]['uncertainty'],
                        'source': receipts['events']['outputs'][1], 'stage': prediction['provenance']}},
                'ablation_controls': {'removed': 'interference terms and their MC covariance rows/columns',
                    'fixed': ['original question', 'stored amplitudes', 'measurement', 'experimental covariance laws',
                              'reference prediction', 'scan', 'domain', 'statistic', 'pure-signal and constant terms'],
                    'mechanism_claim_accepted': False},
                'signed_binned': signed, 'yield_checks': checks, 'physics_validated': False, 'parent_task_accepted': False,
                'limitations': ['Mock or ordinary component delivery is not scientific acceptance.',
                    'Fitted terms are Rivet-selected; the Born comparison is diagnostic and does not certify shower accuracy.',
                    'MC covariance retains all term cross-covariances from independent blocks; coverage is not calibrated.',
                    'Whole-question methodology, independent amplitude accuracy, detector and phase qualification remain separate.']}
            outputs = [*signed, _write(stage_dir / 'measurement-delivery.json', report)]
        for pin in [*inputs, *outputs, *manifest['source_pins']]:
            _check(pin)
        receipt = {'schema_version': 1, 'kind': 'interference-stage-receipt', 'stage': name, 'operation': operation,
                   'signature': _signature(operation), 'goal_binding': request['goal_binding'],
                   'inputs': inputs, 'outputs': outputs, 'physics_validated': False, 'status': 'passed'}
        receipt_pin = _write(stage_dir / 'receipt.json', receipt)
        progress.append({'id': name, 'operation': operation, 'receipt': receipt_pin})
        state_io.atomic_json(progress_path, progress)
        receipts[name] = receipt
    report = _read(receipts['deliverable']['outputs'][-1])
    final_pin = _write(final_path, {**report, 'stages': progress})
    return {'status': 'passed', 'physics_validated': False, 'parent_task_accepted': False,
            'execution_authorized': False, 'deliverable': final_pin}
