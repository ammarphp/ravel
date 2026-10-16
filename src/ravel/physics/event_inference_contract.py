"""Pinned quantity handoffs for the generated-event, selection and template chain.

Only the explicitly declared independent-event counting model is projected to
bin covariance. This does not qualify that sampling model or the supplied domain.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import gzip
import xml.etree.ElementTree as ET

from ravel.validation import core, semantic_composition as semantic
from ravel.workflow.state_io import read_json, atomic_json

NORMALIZATION = dict(per_luminosity=False, per_bin_width=False, per_event=False)
REQUIRED = [*semantic.CORE, 'scale', 'normalization.per_luminosity',
            'normalization.per_bin_width', 'normalization.per_event',
            'exposure.id', 'exposure.revision', 'event_population.id',
            'event_population.revision', 'event_population.grouping',
            'event_population.events', 'event_population.sumw', 'event_population.sumw2',
            'event_population.negative_events', 'applicability.id',
            'applicability.parameters', 'applicability.assumptions', 'covariance.status',
            'covariance.basis', 'covariance.source']


class QuantityObligations(ValueError):
    """Located missing facts; no numerical adapter may fill them by inference."""
    def __init__(self, rows):
        self.obligations = rows
        super().__init__('; '.join(semantic.message(row) for row in rows)
                         + '; repair=supply the missing producer facts before this consumer')


def require_quantity(quantity, expected, location):
    report = semantic.compare(quantity, expected, location)
    if report['errors']:
        raise ValueError('; '.join(semantic.message(row) for row in report['errors'])
                         + '; repair=correct the producer contract or choose a compatible consumer')
    if report['obligations']:
        raise QuantityObligations(report['obligations'])
    return quantity


def file_pin(path):
    from ravel.workflow.science import regular
    from ravel.physics.model_event_commitment import _file
    path = regular(str(path), '.')
    observed = _file(path)
    return {key: observed[key] for key in ('path', 'sha256')}


def bound(pin, base, field):
    from ravel.workflow.science import regular
    core.validate_pin(pin, field=field)
    path = regular(pin['path'], base)
    actual = file_pin(path)
    core.pin(actual['sha256'], pin['sha256'], field=field + '.sha256')
    return path


def read_bound(pin, base, field):
    path = bound(pin, base, field)
    if path.stat().st_size > 16 * 1024**2:
        core.fail(field, path.stat().st_size, 'contract at most 16 MiB')
    value = read_json(path)
    core.finite_json_tree(value, field=field)
    bound(pin, base, field)
    return path, value


def generation_declaration(value):
    core.finite_json_tree(value, field='composition')
    core.closed_object(value, ('quantity', 'sampling_model', 'normalization_model'), field='composition')
    core.pin(value['sampling_model'], 'independent_poisson_events', field='composition.sampling_model')
    core.pin(value['normalization_model'], 'fixed_cross_section_luminosity_and_sumw',
             field='composition.normalization_model')
    errors = semantic.descriptor_errors(value['quantity'], 'composition.quantity')
    if errors:
        raise ValueError('; '.join(map(semantic.message, errors)))
    return value


def independent_event_framing(path):
    """Explicit event groups cannot be projected to independent counting errors."""
    opener = gzip.open if Path(path).suffix == '.gz' else open
    with opener(path, 'rb') as stream:
        root = None
        for action, node in ET.iterparse(stream, events=('start', 'end')):
            if root is None:
                root = node
            if action == 'start' and node.tag == 'eventgroup':
                core.fail('generation.event_population.grouping', 'eventgroup', 'individual events',
                          repair='retain grouped-event covariance in a compatible sampling model')
            if action == 'end':
                node.clear()
                if node.tag == 'event':
                    root.clear()


def selection_identity(recipe_sha256, descriptor_sha256, region):
    digest = hashlib.sha256((recipe_sha256 + ':' + descriptor_sha256).encode()).hexdigest()
    return digest + ':' + region


def generated_sample(result, declaration, event_file):
    """Export observed bytes/moments, retaining supplied factors and domain facts."""
    generation_declaration(declaration)
    core.pin(result.get('status'), 'passed', field='generation.status')
    core.pin(result.get('physics_validated'), False, field='generation.physics_validated')
    population = result['population']
    core.pin(population.get('complete_eof'), True, field='generation.population.complete_eof')
    pin = file_pin(event_file)
    core.pin(pin['sha256'], population['raw_sha256'], field='generation.events.sha256')
    independent_event_framing(event_file)
    identity = pin['sha256']
    moments = population['weight_moments']['nominal']
    group = {'id': identity, 'revision': identity, 'grouping': 'event',
             'events': population['generated_events'], 'sumw': float(moments['sumw']),
             'sumw2': float(moments['sumw2']),
             'negative_events': population['signed_nominal_counts']['negative']}
    observed = {'kind': 'sample_exposure', 'unit': 'events', 'scale': 1,
                'normalization': NORMALIZATION, 'weight_convention': 'signed',
                'exposure': {'id': identity, 'revision': identity}, 'event_population': group,
                'covariance': {'status': 'unknown', 'basis': [], 'matrix': None,
                               'source': 'generation records weight moments without a fitted covariance'}}
    intended = result['intended']
    observed['model_point'] = {
        'model_source_sha256': intended['model_tree']['manifest']['sha256'],
        'parameter_card_sha256': intended['cards']['parameter']['sha256']}
    observed['selection'] = 'cards:' + hashlib.sha256(''.join(
        intended['cards'][name]['sha256'] for name in ('process', 'run')).encode()).hexdigest()
    declared = deepcopy(declaration['quantity'])
    if 'model_point' in declared:
        core.pin(declared['model_point'], observed['model_point'], field='generation.quantity.model_point')
    # Partial supplied facts may not contradict observations, even before a consumer.
    errors = semantic.compare(observed, {k: v for k, v in declared.items() if k in observed},
                              'generation.quantity')['errors']
    if errors:
        raise ValueError('; '.join(map(semantic.message, errors)))
    quantity = {**declared, **deepcopy(observed)}
    rate = math.fsum(float(row['cross_section_pb']) for row in population['init']['processes'])
    core.finite_number(rate, field='generation.cross_section.value', minimum=0)
    rate_quantity = {**deepcopy(quantity), 'kind': 'cross_section', 'unit': 'pb',
                     'normalization': {**NORMALIZATION, 'per_luminosity': True}}
    return {'schema_version': 1, 'kind': 'generated-sample-contract', 'events': [pin],
            'quantity': quantity, 'cross_section': {'value': rate, 'quantity': rate_quantity},
            'sampling_model': declaration['sampling_model'],
            'normalization_model': declaration['normalization_model'],
            'sampling_model_origin': 'supplied_assumption'}


def validate_generated_sample(sample, path, location):
    """Require the same supplied sample contract at selection and inference."""
    core.closed_object(sample, ('schema_version', 'kind', 'events', 'quantity', 'cross_section',
                               'sampling_model', 'normalization_model', 'sampling_model_origin'), field='generated_sample')
    core.pin(sample['schema_version'], 1, field='generated_sample.schema_version')
    core.pin(sample['kind'], 'generated-sample-contract', field='generated_sample.kind')
    require_quantity(sample['quantity'], {'required': REQUIRED, 'kind': 'sample_exposure',
                     'unit': 'events', 'scale': 1, 'normalization': NORMALIZATION,
                     'event_population': {'grouping': 'event'}}, location + '.events')
    core.pin(sample['sampling_model'], 'independent_poisson_events', field='generated_sample.sampling_model')
    core.pin(sample['sampling_model_origin'], 'supplied_assumption', field='generated_sample.sampling_model_origin')
    core.pin(sample['normalization_model'], 'fixed_cross_section_luminosity_and_sumw',
             field='generated_sample.normalization_model')
    core.closed_object(sample['cross_section'], ('value', 'quantity'), field='generated_sample.cross_section')
    rate = sample['cross_section']
    core.finite_number(rate['value'], field='generated_sample.cross_section.value', minimum=0)
    require_quantity(rate['quantity'], {'required': REQUIRED, **{k: v for k, v in sample['quantity'].items()
                     if k not in ('kind', 'unit', 'normalization')}, 'kind': 'cross_section', 'unit': 'pb',
                     'scale': 1, 'normalization': {**NORMALIZATION, 'per_luminosity': True}},
                     location + '.cross_section')
    if type(sample['events']) is not list or len(sample['events']) != 1:
        core.fail(location + '.inputs', sample['events'], 'one original generated event file',
                  repair='use the compatible adapter for a different event population')
    expected = [file_pin(bound(p, path.parent, 'generated_sample.events')) for p in sample['events']]
    identity = expected[0]['sha256']
    for field in ('id', 'revision'):
        core.pin(sample['quantity']['event_population'][field], identity, field='event_population.' + field)
        core.pin(sample['quantity']['exposure'][field], identity, field='exposure.' + field)
    return expected


def selection_inputs(task, base, plan, normalization, events):
    """Admit this opt-in chain before any event is selected."""
    path, sample = read_bound(task['generated_sample'], base, 'generated_sample')
    expected = validate_generated_sample(sample, path, 'columnar-analysis')
    actual = [file_pin(p) for p in events]
    core.pin(actual, expected, field='columnar-analysis.inputs')
    if (len(actual) != 1 or plan.dataset is not None or plan.descriptor.format != 'lhe'
            or plan.descriptor.origin.get('kind') != 'file'):
        core.fail('columnar-analysis.inputs', actual, 'one original generated event file',
                  repair='use the compatible adapter for a different event population')
    independent_event_framing(events[0])
    # No implicit reuse of a selected denominator or reapplication of included factors.
    core.pin(normalization.get('mode'), 'cross-section', field='normalization.mode')
    core.pin(normalization.get('cross_section_pb'), {'lhe_init': True}, field='normalization.cross_section_pb')
    core.pin(normalization.get('sum_of_weights'), 'all-input-events', field='normalization.sum_of_weights')
    if 'factor' in normalization:
        core.fail('normalization.factor', normalization['factor'], 'no second application of included factors',
                  repair='supply a distinct normalization contract for additional factors')
    if (plan.doc['weights']['factors'] or plan.doc.get('event_weights')
            or any('weight' in step or 'efficiency' in step for step in plan.doc['objects'])):
        core.fail('columnar-analysis.weights', plan.doc['weights'], 'generator weights without additional factors',
                  repair='supply explicit factor accounting before extending this chain')
    generator = plan.doc['weights']['generator']
    core.pin(plan.descriptor.doc['event'].get(generator), 'nominal',
             field='columnar-analysis.weights.generator')
    luminosity = core.finite_number(normalization.get('luminosity_ifb'), field='normalization.luminosity_ifb', minimum=0)
    if luminosity == 0:
        core.fail('normalization.luminosity_ifb', luminosity, 'positive integrated luminosity')
    if len(plan.histograms) != 1 or any(s.kind == 'efficiency' and s.spec['application'] == 'enumerate' for s in plan.steps):
        core.fail('columnar-analysis.histograms', len(plan.histograms), 'one exclusive event histogram without subset enumeration',
                  repair='provide a consumer with the full shared-event covariance')
    histogram = plan.histograms[0]
    if histogram.normalization != 'yield' or histogram.value_unit not in (None, 'events'):
        core.fail('columnar-analysis.histogram.normalization', histogram.normalization, 'integrated event yield',
                  repair='declare the yield representation before producing templates')
    return path, sample


def selection_outputs(task, base, plan, normalization, events, summary, out):
    source_path, sample = selection_inputs(task, base, plan, normalization, events)
    group = sample['quantity']['event_population']
    observed = summary['events']
    for target, key in (('events', 'n'), ('sumw', 'sum_generator'), ('sumw2', 'sum_generator2'),
                        ('negative_events', 'negative')):
        value = core.finite_number(observed[key], field='columnar-analysis.events.' + key)
        if not math.isclose(value, group[target], rel_tol=1e-12, abs_tol=1e-12):
            core.fail('columnar-analysis.events.' + key, value, group[target],
                      repair='restore the full generated event population')
    norm = summary['normalization']
    core.pin(norm['cross_section_pb'], sample['cross_section']['value'], field='columnar-analysis.cross_section_pb')
    histogram = plan.histograms[0]
    entry = summary['histograms'][histogram.name]['nominal']
    doc = read_json(Path(out) / entry['file'])
    ids = [histogram.region + ':' + str(i) for i in range(len(doc['bins']))]
    matrix = [[v if i == j else 0.0 for j in range(len(ids))] for i, v in enumerate(doc['sumw2'])]
    quantity = {**deepcopy(sample['quantity']), 'kind': 'event_count', 'bin_ids': ids,
                'selection': selection_identity(plan.recipe_sha256, plan.descriptor.sha256, histogram.region),
                'regional_exposures': {histogram.region: deepcopy(sample['quantity']['exposure'])},
                'luminosity': {'value': norm['luminosity_ifb'], 'unit': 'fb^-1', 'scale': 1},
                'covariance': {'status': 'known', 'basis': ids, 'matrix': matrix,
                               'source': 'supplied independent_poisson_events with fixed_cross_section_luminosity_and_sumw; exclusive event bins'}}
    doc.update(quantity=quantity, covariance=matrix)
    doc['provenance'].update(bin_ids=ids, generated_sample=file_pin(source_path),
                             selection_recipe=file_pin(Path(base) / task['recipe']),
                             selection_format=file_pin(plan.descriptor.origin['path']),
                             sampling_model_origin=sample['sampling_model_origin'])
    from ravel.physics.binned_values import validate
    validate(doc)
    output = Path(out) / 'quantity-contract.json'
    atomic_json(output, doc)
    return file_pin(output)


def prediction(pin, base, sample, channel):
    """Pair exact numerical arrays and covariance with the producing selection."""
    path, document = read_bound(pin, base, 'template.prediction')
    from ravel.physics.binned_values import validate
    validate(document)
    required = [*REQUIRED, 'bin_ids', 'regional_exposures', 'luminosity.value',
                'luminosity.unit', 'luminosity.scale', 'covariance.matrix']
    q = require_quantity(document.get('quantity'), {'required': required, 'kind': 'event_count',
                         'unit': 'events', 'scale': 1, 'normalization': NORMALIZATION,
                         'luminosity': {'unit': 'fb^-1', 'scale': 1},
                         'covariance': {'status': 'known'}}, 'signal-template.yields')
    source_path, generation = read_bound(document['provenance']['generated_sample'], path.parent,
                                         'template.prediction.generated_sample')
    validate_generated_sample(generation, source_path, 'template.prediction.generated_sample')
    _, recipe = read_bound(document['provenance']['selection_recipe'], path.parent,
                          'template.prediction.selection_recipe')
    _, descriptor = read_bound(document['provenance']['selection_format'], path.parent,
                              'template.prediction.selection_format')
    from ravel.physics.columnar.formats import Descriptor
    digest = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    core.pin(q['selection'], selection_identity(digest, Descriptor(descriptor).sha256, channel),
             field='template.prediction.selection')
    for key in ('model_point', 'included_factors', 'event_population', 'exposure', 'applicability'):
        core.pin(q[key], generation['quantity'][key], field='template.prediction.' + key)
    core.pin(q['regional_exposures'], {channel: q['exposure']},
             field='template.prediction.regional_exposures')
    expected = sample.get('prediction_requirements')
    names = ('selection', 'model_point', 'included_factors', 'exposure', 'event_population',
             'luminosity', 'applicability')
    if not isinstance(expected, dict) or any(expected.get(name) is None for name in names):
        raise QuantityObligations([{'location': 'signal-template.requirements', 'field': name,
                                   'observed': None, 'expected': 'explicit consumer requirement',
                                   'repair': 'declare the intended template population and domain'}
                                  for name in names if not isinstance(expected, dict) or expected.get(name) is None])
    require_quantity(q, expected, 'signal-template.prediction')
    ids = [channel + ':' + str(i) for i in range(len(document['bins']))]
    core.pin(q['bin_ids'], ids, field='template.prediction.bin_ids')
    core.pin(q['covariance']['basis'], ids, field='template.prediction.covariance.basis')
    core.pin(q['covariance']['matrix'], document.get('covariance'), field='template.prediction.covariance.matrix')
    if q['event_population']['negative_events']:
        core.fail('template.prediction.event_population.negative_events', q['event_population']['negative_events'], 0,
                  repair='use a likelihood with justified signed-event sampling')
    values = [row['value'] for row in document['bins']]
    core.pin(sample['data'], values, field='template.data')
    core.pin(sample['mc_stat'].get('mode'), 'supplied', field='template.mc_stat.mode')
    core.pin(sample['mc_stat'].get('sumw'), values, field='template.mc_stat.sumw')
    core.pin(sample['mc_stat'].get('sumw2'), document['sumw2'], field='template.mc_stat.sumw2')
    matrix = q['covariance']['matrix']
    for i, row in enumerate(matrix):
        for j, value in enumerate(row):
            expected_covariance = document['sumw2'][i] if i == j else 0
            core.pin(value, expected_covariance, field=f'template.prediction.covariance.matrix.{i}.{j}')
    return {'source': file_pin(path), 'quantity': deepcopy(q), 'requirements': deepcopy(expected)}


def prediction_inputs(pin, base):
    """Every transitive byte input read by prediction validation."""
    path, document = read_bound(pin, base, 'template.prediction')
    source, generation = read_bound(document['provenance']['generated_sample'], path.parent,
                                     'template.prediction.generated_sample')
    recipe = bound(document['provenance']['selection_recipe'], path.parent, 'template.prediction.selection_recipe')
    descriptor = bound(document['provenance']['selection_format'], path.parent, 'template.prediction.selection_format')
    return [path, source, recipe, descriptor, *[bound(event, source.parent, 'template.prediction.events')
                                   for event in generation['events']]]


def inference_output(contract, compiled, result):
    """Retain input quantities separately from the dimensionless fitted strength."""
    records = contract.manifest().get('quantity_contracts')
    if not records:
        return None
    signal = deepcopy(records[0]['quantity'])
    inherited = {k: deepcopy(v) for k, v in signal.items() if k not in
                 ('kind', 'unit', 'bin_ids', 'covariance', 'regional_exposures')}
    quantity = {**inherited, 'kind': 'inference', 'unit': '1', 'scale': 1,
                'covariance': {'status': 'not_applicable', 'basis': [], 'matrix': None,
                               'source': 'upper limit on strength; signal covariance is retained with its input'}}
    return {'schema_version': 1, 'kind': 'event-inference-contract',
            'input_quantities': records, 'likelihood': {
                'workspace_sha256': contract.manifest()['workspace_compact_sha256'],
                'channel_order': compiled['channel_order'], 'parameter_order': compiled['parameter_order'],
                'auxiliary_information': compiled['constraints'], 'auxdata': compiled['auxdata']},
            'quantity': quantity, 'expected_limits': deepcopy(result['exp_limits']),
            'limit_status': deepcopy(result['limit_status']), 'physics_validated': False}
