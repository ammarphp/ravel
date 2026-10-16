"""Synthetic cross-operation quantity faults through ordinary composition checks."""
from copy import deepcopy
import json

import pytest

from request_plan_corpus import Reading
from ravel.physics.binned_values import build
from ravel.validation import signature_conformance as signatures
from ravel.validation import validate_request_plan as check
from ravel.validation.semantic_composition import CORE, compare, descriptor_errors
from ravel.workflow import request_plan


def quantity(kind='event_count', unit='events'):
    return {'kind': kind, 'unit': unit, 'scale': 1,
            'normalization': {'per_luminosity': kind in ('cross_section', 'differential_cross_section'),
                              'per_bin_width': False, 'per_event': False},
            'included_factors': [{'name': 'decay_mode', 'kind': 'branching_fraction',
                                  'value': 0.4, 'source': 'supplied:decay-table'}],
            'weight_convention': 'signed', 'selection': 'fiducial-a',
            'model_point': {'model': 'model-a', 'mass': 80},
            'event_population': {'id': 'sample-a', 'revision': 'revision-a', 'grouping': 'event',
                                 'events': 10, 'sumw': 10, 'sumw2': 10, 'negative_events': 0},
            'applicability': {'id': 'declared-domain', 'parameters': {}, 'assumptions': []},
            'covariance': {'status': 'unknown', 'basis': [], 'matrix': None, 'source': 'synthetic declaration'},
            'luminosity': {'value': 1, 'unit': 'fb^-1', 'scale': 1},
            'bin_ids': ['region-a:0', 'region-b:0'],
            'exposure': {'id': 'sample-a', 'revision': 'revision-a'},
            'regional_exposures': {'region-a': {'id': 'sample-a', 'revision': 'revision-a'},
                                   'region-b': {'id': 'sample-a', 'revision': 'revision-a'}}}


def histogram(q=None):
    q = quantity() if q is None else q
    return build(axes=[{'name': 'coordinate', 'unit': '1'}],
                 bins=[{'low': [0], 'high': [1], 'value': 2, 'sumw2': 1},
                       {'low': [1], 'high': [2], 'value': 3, 'sumw2': 2}],
                 unit=q['unit'], normalization={'kind': 'absolute'},
                 provenance={'bin_ids': q['bin_ids']}, quantity=deepcopy(q))


def composed():
    reading = Reading('Compute binned values from supplied events.dat.')
    reading.fact('supplied_file', {'artifact': 'event_sample', 'locator': 'events.dat'},
                 'events.dat', authority='supplied')
    oid = reading.obligation('deliverable', 'binned values')
    reading.deliverable('binned_values', 'prediction', [oid])
    plan = request_plan.draft(reading.doc, reading.contract(), catalogue=lambda _: False)
    registry = deepcopy(check.registry())
    producer = next(n for n in plan['nodes'] if n['operation'] == 'columnar-analysis')
    consumer = deepcopy(producer)
    consumer.update(id='N2', operation='signal-template', fields=[])
    plan['nodes'].append(consumer)
    for row in plan['coverage']:
        if row['obligation_id'] in consumer['covers']:
            row['by'].append('N2')
    # Add a real generated-rate input and supplied likelihood companions.
    def supplied(kind, slot, target, artifact):
        iid, eid = f'I{len(plan["inputs"]) + 1}', f'E{len(plan["edges"]) + 1}'
        plan['inputs'].append({'id': iid, 'provides': {'kind': kind, 'require': {}},
                               'source': 'requester', 'locator': iid + '.json',
                               'evidence': [], 'pin': None, 'status': 'located'})
        plan['edges'].append({'id': eid, 'from': {'ref': iid, 'slot': 'provided'},
                              'to': {'ref': target, 'slot': slot}, 'kind': kind, 'require': {},
                              'resolution': 'compatible', 'converter': None, 'acceptance': 'accepted_review'})
        artifacts[eid] = artifact
        return eid

    artifacts = {}
    incoming = next(e for e in plan['edges'] if e['to']['slot'] == 'events')
    artifacts[incoming['id']] = {'files': ['events.dat'], 'quantity': quantity('sample_exposure')}
    delivery = next(e for e in plan['edges'] if e['to']['ref'] == 'C1')
    delivery['from'] = {'ref': 'N2', 'slot': 'patch'}
    rate = supplied('scalar', 'cross_section', producer['id'],
                    {'value': 2, 'unit': 'pb', 'quantity': quantity('cross_section', 'pb')})
    signal = f'E{len(plan["edges"]) + 1}'
    plan['edges'].append({'id': signal, 'from': {'ref': producer['id'], 'slot': 'histograms'},
                          'to': {'ref': 'N2', 'slot': 'yields'}, 'kind': 'binned_values', 'require': {},
                          'resolution': 'compatible', 'converter': None, 'acceptance': 'accepted_review'})
    artifacts[signal] = histogram()
    model = {'channels': [], 'quantity': {**quantity('statistical_model'), 'auxiliary_information': ['observation-a', 'observation-b']}}
    workspace = supplied('statistical_model', 'workspace', 'N2', model)
    plan['claims'][0]['basis_declared'] = sorted(
        {b['element'] for b in check.computed_bases(plan, registry)['C1']}, key=check.BASES.index)
    return reading, plan, registry, artifacts, {'rate': rate, 'signal': signal, 'workspace': workspace,
                                              'control': signal}


def errors(reading, plan, registry, artifacts):
    return check.check(reading.doc, plan, reg=registry, artifacts=artifacts,
                       obligations=reading.obligations, catalogue=lambda _: False)


@pytest.mark.parametrize('fault,field', [
    ('rate_scale', 'unit'), ('double_factor', 'included_factors'), ('wrong_bin', 'bin_ids'),
    ('duplicate_auxiliary', 'auxiliary_information'), ('absolute_weights', 'weight_convention'),
    ('stale_control', 'exposure'),
])
def test_fault_siblings_and_unmodified_controls_through_real_plan(fault, field):
    reading, plan, registry, artifacts, ids = composed()
    assert errors(reading, plan, registry, artifacts) == []
    assert not [f for f in check.flags(reading.doc, plan, reg=registry, artifacts=artifacts,
                                     catalogue=lambda _: False) if f['flag'] == 'quantity_obligation']
    original = deepcopy(artifacts)
    if fault == 'rate_scale':
        # This consumer's declared convention is fb; control is fb, planted input is pb.
        port = next(s for s in registry['columnar-analysis']['consumes'] if s['slot'] == 'cross_section')
        port['require']['quantity']['unit'] = 'fb'
        artifacts[ids['rate']]['unit'] = 'fb'
        artifacts[ids['rate']]['quantity']['unit'] = 'fb'
        assert errors(reading, plan, registry, artifacts) == []
        planted = original[ids['rate']]
        original = deepcopy(artifacts)
        artifacts[ids['rate']] = planted
    elif fault == 'double_factor':
        factors = artifacts[ids['signal']]['quantity']['included_factors']
        factors.append(deepcopy(factors[0]))
        artifacts[ids['signal']]['bins'][0]['value'] *= factors[0]['value']
    elif fault == 'wrong_bin':
        artifacts[ids['signal']]['quantity']['bin_ids'].reverse()
        artifacts[ids['signal']]['provenance']['bin_ids'].reverse()
    elif fault == 'duplicate_auxiliary':
        artifacts[ids['workspace']]['quantity']['auxiliary_information'] = ['observation-a', 'observation-a']
    elif fault == 'absolute_weights':
        artifacts[ids['signal']]['quantity']['weight_convention'] = 'absolute'
    elif fault == 'stale_control':
        artifacts[ids['signal']]['quantity']['exposure']['revision'] = 'revision-b'
        artifacts[ids['signal']]['quantity']['regional_exposures']['region-a']['revision'] = 'revision-b'
        artifacts[ids['signal']]['bins'][0]['value'] = 7
    failures = errors(reading, plan, registry, artifacts)
    assert failures and all(e['error_class'] == 'quantity_incompatible' for e in failures), failures
    assert any(field in e['reason'] and 'observed' in e['reason'] and 'expected' in e['reason'] for e in failures)
    assert all(e['evidence_ids'][0].startswith('E') for e in failures)
    assert errors(reading, plan, registry, original) == []


def test_legacy_receipts_remain_loadable_and_missing_facts_are_checkin_flags():
    reading, plan, registry, artifacts, ids = composed()
    for artifact in artifacts.values():
        artifact.pop('quantity', None)
    assert errors(reading, plan, registry, artifacts) == []
    flags = check.flags(reading.doc, plan, reg=registry, artifacts=artifacts, catalogue=lambda _: False)
    obligations = [f for f in flags if f['flag'] == 'quantity_obligation']
    assert obligations and any(ids['signal'] in f['ids'] and 'kind' in f['text'] for f in obligations)
    assert check.plan_schema_errors(plan) == []
    assert json.loads(json.dumps(plan)) == plan


@pytest.mark.parametrize('field,value', [('selection', 'fiducial-b'), ('model_point', {'model': 'model-b'}),
                                        ('normalization', {'per_bin_width': True}), ('kind', 'differential_cross_section')])
def test_semantic_selection_model_and_normalization_mismatches(field, value):
    reading, plan, registry, artifacts, ids = composed()
    artifacts[ids['signal']]['quantity'][field] = value
    if field == 'kind':
        artifacts[ids['signal']]['quantity']['normalization'].update(per_bin_width=True, per_luminosity=True)
    assert any(field in e['reason'] for e in errors(reading, plan, registry, artifacts))


def test_signature_edge_query_reports_absent_metadata_and_refuses_declared_mismatch():
    registry = deepcopy(check.registry())
    report = signatures.edge_report('columnar-analysis', 'histograms', 'signal-template', 'yields', registry)
    assert report['errors'] == [] and report['obligations']
    assert signatures.edge_errors('columnar-analysis', 'histograms', 'signal-template', 'yields', registry,
                                  artifact=histogram()) == []
    bad = histogram()
    bad['quantity']['unit'] = 'fb'
    assert any('unit' in e for e in signatures.edge_errors('columnar-analysis', 'histograms',
                                                         'signal-template', 'yields', registry, artifact=bad))


@pytest.mark.parametrize('field', CORE)
def test_missing_descriptor_property_is_located_and_never_defaulted(field):
    q = quantity()
    q.pop(field)
    report = compare(q, {'required': list(CORE)}, 'E7 producer.rate -> consumer.signal')
    assert report['errors'] == []
    assert any(r['field'] == field and r['location'].startswith('E7') for r in report['obligations'])


def test_explicit_false_and_empty_factor_list_satisfy_requirements():
    q = quantity()
    q['included_factors'] = []
    assert compare(q, {'required': list(CORE)}, 'edge') == {'errors': [], 'obligations': []}


def test_malformed_numeric_factor_is_refused_without_new_dependencies():
    q = quantity()
    q['included_factors'][0]['value'] = True
    assert descriptor_errors(q)


def test_edge_cannot_relabel_declared_producer_units():
    reading, plan, registry, artifacts, ids = composed()
    edge = next(e for e in plan['edges'] if e['id'] == ids['rate'])
    item = next(i for i in plan['inputs'] if i['id'] == edge['from']['ref'])
    item['provides']['require']['quantity'] = {'kind': 'cross_section', 'unit': 'pb'}
    edge['require']['quantity'] = {'kind': 'cross_section', 'unit': 'fb'}
    assert any('unit' in e['reason'] for e in errors(reading, plan, registry, artifacts))


def test_missing_factor_source_is_an_obligation():
    q = quantity()
    del q['included_factors'][0]['source']
    report = compare(q, {'required': list(CORE)}, 'E1 source.rate -> target.yields')
    assert report['errors'] == []
    assert any(r['field'] == 'included_factors.0.source' for r in report['obligations'])


def test_moment_projection_retains_descriptor_and_legacy_projection_stays_loadable():
    from ravel.physics.statistics_links import search_yields, measurement_prediction
    doc = histogram()
    doc['covariance'] = [[1, 0], [0, 2]]
    assert search_yields(doc)['quantity'] == doc['quantity']
    assert measurement_prediction(doc)['quantity'] == doc['quantity']
    projected = search_yields(doc)
    projected['quantity']['model_point']['mass'] = 90
    assert doc['quantity']['model_point']['mass'] == 80


def test_partition_merge_refuses_different_descriptors():
    from ravel.workflow.partitioned_execution import merge_documents
    left = histogram()
    left['normalization']['kind'] = 'unnormalized'
    right = deepcopy(left)
    assert merge_documents('binned_values', [left, right])['quantity'] == left['quantity']
    right['quantity']['weight_convention'] = 'absolute'
    with pytest.raises(ValueError, match='quantity'):
        merge_documents('binned_values', [left, right])


def test_distinct_model_points_do_not_share_an_exposure_revision_requirement():
    from ravel.validation.semantic_composition import relations
    first, second = quantity(), quantity()
    second['model_point']['mass'] = 90
    second['exposure']['revision'] = 'revision-b'
    rows = [{'slot': 'signal', 'quantity': q, 'location': f'E{i}'} for i, q in enumerate((first, second), 1)]
    rules = check.registry()['search-statistics']['quantity_relations']
    assert relations(rows, rules, 'N1') == {'errors': [], 'obligations': []}
    second['model_point']['mass'] = 80
    assert relations(rows, rules, 'N1')['errors']


def test_two_auxiliary_inputs_cannot_count_the_same_information_twice():
    reading = Reading('Set a 95% CLs limit using supplied model.json.')
    reading.fact('supplied_file', {'artifact': 'statistical_model', 'locator': 'model.json'},
                 'model.json', authority='supplied')
    oid = reading.obligation('deliverable', '95% CLs limit')
    reading.deliverable('inference', 'exclusion', [oid])
    plan = request_plan.draft(reading.doc, reading.contract(), catalogue=lambda _: False)
    node = next(n for n in plan['nodes'] if n['operation'] == 'likelihood')
    model_edge = next(e for e in plan['edges'] if e['to']['slot'] == 'model')
    iid, eid = f'I{len(plan["inputs"]) + 1}', f'E{len(plan["edges"]) + 1}'
    plan['inputs'].append({'id': iid, 'provides': {'kind': 'table', 'require': {}},
                           'source': 'requester', 'locator': 'constraint.json',
                           'evidence': [], 'pin': None, 'status': 'supplied'})
    plan['edges'].append({'id': eid, 'from': {'ref': iid, 'slot': 'provided'},
                          'to': {'ref': node['id'], 'slot': 'counts'}, 'kind': 'table', 'require': {},
                          'resolution': 'compatible', 'converter': None, 'acceptance': 'accepted_review'})
    artifacts = {model_edge['id']: {'channels': [], 'quantity': {
                     'bin_ids': ['bin-a'], 'auxiliary_information': ['constraint-observation-a']}},
                 eid: {'rows': [], 'quantity': {'auxiliary_information': ['constraint-observation-b']}}}
    registry = check.registry()
    assert errors(reading, plan, registry, artifacts) == []
    artifacts[eid]['quantity']['auxiliary_information'] = ['constraint-observation-a']
    failures = errors(reading, plan, registry, artifacts)
    assert failures and all(e['error_class'] == 'quantity_incompatible' for e in failures)
    assert any('auxiliary_information' in e['reason'] for e in failures)


@pytest.mark.parametrize('property', ['source', 'kind', 'value'])
def test_null_factor_property_is_an_obligation(property):
    q = quantity()
    q['included_factors'][0][property] = None
    report = compare(q, {'required': list(CORE)}, 'E1 producer.rate -> consumer.counts')
    assert report['errors'] == []
    assert any(r['field'] == 'included_factors.0.' + property for r in report['obligations'])


def test_awaited_input_records_obligations_not_the_consumer_requirement_as_facts():
    reading = Reading('Use DelphesHepMC3 for detector.')
    reading.constraint('requested_tool', {'tool': 'DelphesHepMC3'}, 'DelphesHepMC3')
    reading.constraint('requested_stage', {'stage': 'detector'}, 'DelphesHepMC3')
    plan = request_plan.draft(reading.doc, reading.contract(), catalogue=lambda _: False)
    awaited = [i for i in plan['inputs'] if i['status'] == 'awaited']
    assert awaited and not any('quantity' in i['provides']['require'] for i in awaited)
    assert not any('quantity' in e['require'] for e in plan['edges'])
    assert check.check(reading.doc, plan, obligations=reading.obligations, catalogue=lambda _: False) == []
    flagged = {i for f in check.flags(reading.doc, plan, catalogue=lambda _: False)
               if f['flag'] == 'quantity_obligation' for i in f['ids']}
    assert flagged & {e['id'] for e in plan['edges'] if e['from']['ref'] in {i['id'] for i in awaited}}


@pytest.mark.parametrize('kind,unit,flag', [('cross_section', 'pb', False), ('differential_cross_section', 'pb/GeV', False),
                                            ('event_count', 'events', True)])
def test_luminosity_normalization_contradicting_the_kind_is_refused(kind, unit, flag):
    q = quantity(kind, unit)
    q['normalization']['per_bin_width'] = kind == 'differential_cross_section'
    q['normalization']['per_luminosity'] = flag
    assert any(e['field'] == 'normalization.per_luminosity' for e in descriptor_errors(q))
    q['normalization']['per_luminosity'] = not flag
    assert descriptor_errors(q) == []


@pytest.mark.parametrize('operation,signal_slot', [('signal-template', 'yields'),
                                                 ('lifecycle-workspace-limit', 'signal')])
def test_background_only_workspace_never_acquires_signal_model_requirements(operation, signal_slot):
    from ravel.validation.semantic_composition import plan_report
    reading, plan, registry, artifacts, ids = composed()
    next(n for n in plan['nodes'] if n['id'] == 'N2')['operation'] = operation
    next(e for e in plan['edges'] if e['id'] == ids['signal'])['to']['slot'] = signal_slot
    workspace = artifacts[ids['workspace']]['quantity']
    # Only the likelihood's own requirements are supplied; a background-only
    # likelihood has no signal model point, selection or sample exposure.
    artifacts[ids['workspace']]['quantity'] = {key: workspace[key]
        for key in ('kind', 'bin_ids', 'auxiliary_information')}
    assert plan_report(plan, registry, artifacts) == {'errors': [], 'obligations': []}
    if operation == 'signal-template':
        assert errors(reading, plan, registry, artifacts) == []
    artifacts[ids['workspace']]['quantity']['model_point'] = {'model': 'model-a', 'mass': 90}
    report = plan_report(plan, registry, artifacts)
    assert any(r['field'] == 'model_point.mass' and ids['workspace'] in r['location'] for r in report['errors'])
    assert not report['obligations']


def test_partial_relation_dictionaries_compare_only_shared_facts_across_every_pair():
    from ravel.validation.semantic_composition import relations
    rows = [{'slot': 'yields', 'quantity': {'model_point': point}, 'location': f'E{i}'}
            for i, point in enumerate(({'model': 'model-a'}, {'mass': 80}, {'mass': 90}), 1)]
    rules = [{'relation': 'equal', 'slots': ['yields'], 'fields': ['model_point']}]
    report = relations(rows, rules, 'N2')
    assert not report['obligations']
    assert len(report['errors']) == 1 and report['errors'][0]['field'] == 'model_point.mass'
    rows[-1]['quantity']['model_point']['mass'] = 80
    assert relations(rows, rules, 'N2') == {'errors': [], 'obligations': []}


def test_only_consuming_slot_requests_missing_relation_fields():
    from ravel.validation.semantic_composition import plan_report
    _, plan, registry, artifacts, ids = composed()
    artifacts[ids['workspace']]['quantity'].pop('model_point')
    artifacts[ids['signal']]['quantity'].pop('model_point')
    report = plan_report(plan, registry, artifacts)
    assert not report['errors']
    missing = [r for r in report['obligations'] if r['field'] == 'model_point']
    assert len(missing) == 1 and ids['signal'] in missing[0]['location']


@pytest.mark.parametrize('producer,slot', [('model-events', 'events'), ('event-production', 'events'),
                                         ('columnar-analysis', 'histograms'), ('columnar-analysis', 'cutflow'),
                                         ('signal-template', 'patch')])
def test_sign_preserving_producers_declare_their_convention(producer, slot):
    signature = check.registry()[producer]
    produced = next(s for s in signature['produces'] if s['slot'] == slot)
    assert produced['require']['quantity']['weight_convention'] == 'signed'


def test_undeclared_producer_weights_are_located_obligations_without_refusal():
    reading, plan, registry, artifacts, ids = composed()
    produced = next(s for s in registry['columnar-analysis']['produces'] if s['slot'] == 'histograms')
    produced['require'].pop('quantity')
    artifacts[ids['signal']]['quantity'].pop('weight_convention')
    assert errors(reading, plan, registry, artifacts) == []
    flags = check.flags(reading.doc, plan, reg=registry, artifacts=artifacts, catalogue=lambda _: False)
    assert any(f['flag'] == 'quantity_obligation' and ids['signal'] in f['ids']
               and 'weight_convention' in f['text'] for f in flags)
    report = signatures.edge_report('columnar-analysis', 'histograms', 'signal-template', 'yields', registry,
                                    artifact=artifacts[ids['signal']])
    assert not report['errors']
    assert any(r['field'] == 'weight_convention' and 'histograms' in r['location'] for r in report['obligations'])


def test_declared_signed_producer_refuses_absolute_relabeling_without_actual_bytes():
    reading, plan, registry, _, ids = composed()
    edge = next(e for e in plan['edges'] if e['id'] == ids['signal'])
    edge['require']['quantity'] = {'weight_convention': 'absolute'}
    assert any('weight_convention' in e['reason'] for e in errors(reading, plan, registry, None))
    doc = histogram()
    doc['quantity']['weight_convention'] = 'absolute'
    assert any('weight_convention' in e for e in signatures.edge_errors(
        'columnar-analysis', 'histograms', 'signal-template', 'yields', artifact=doc))
