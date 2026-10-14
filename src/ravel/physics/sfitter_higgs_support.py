"""Generic supplied defect-registry checks and source-support ledgers."""
from copy import deepcopy
from fractions import Fraction
import json
import math
from . import reviewed_source as records

FIELDS = ('native_law_assumptions', 'scientific_input_support', 'scientific_input_holds')


class HiggsInputSupportError(records.SourceRecordError):
    def __init__(self, support):
        self.support = deepcopy(support)
        super().__init__('unresolved_source_defect', 'input held by reviewed source defect registry', details=support)


def _physical_value(value):
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError('finite physical record required')
        exact = Fraction(value)
        return ('number', exact.numerator, exact.denominator)
    if type(value) is bool:
        return ('boolean', value)
    if value is None:
        return ('null',)
    if type(value) is str:
        return ('string', value)
    if type(value) is list:
        return ('list', tuple(_physical_value(v) for v in value))
    if type(value) is dict and all(type(k) is str for k in value):
        return ('object', tuple((k, _physical_value(v)) for k,v in sorted(value.items())))
    raise ValueError('typed JSON physical record required')


def _physical_record(value):
    return json.dumps(_physical_value({k:v for k,v in value.items() if k not in ('ID', 'name')}),
                      sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(card):
    observations, predictions = card.get('observations'), card.get('predictions')
    if not isinstance(observations, list) or not isinstance(predictions, list) or len(observations) != len(predictions):
        raise records.SourceRecordError('source_scope_mismatch', 'complete paired card required')
    return records.digest([[_physical_record(o), _physical_record(p)] for o,p in zip(observations, predictions)])


def inspect(root, card, registry=None):
    value, sources, inputs, capture = records.load(registry, root, 'defect-registry', 'missing_defect_registry')
    input_fingerprint = fingerprint(card)
    if len({d['id'] for d in value['defects']}) != len(value['defects']):
        raise records.SourceRecordError('invalid_source_record','duplicate defect identity')
    if any(r['defect_id'] not in {d['id'] for d in value['defects']} for r in value['resolutions']):
        raise records.SourceRecordError('invalid_source_record','resolution has no defect record')
    holds = []
    for defect in value['defects']:
        if defect['source'] not in sources:
            raise records.SourceRecordError('invalid_source_record','defect source absent')
        original = records.document(sources[defect['source']])
        observation = records.select(original, defect['observation_pointer'])
        prediction = records.select(original, defect['prediction_pointer'])
        expected = (_physical_record(observation), _physical_record(prediction))
        resolutions = [r for r in value['resolutions'] if r['defect_id'] == defect['id']
                       and r['input_fingerprint'] == input_fingerprint]
        if len(resolutions) > 1:
            raise records.SourceRecordError('invalid_source_record', 'ambiguous defect resolution')
        if resolutions and (not resolutions[0]['evidence'] or any(k not in sources for k in resolutions[0]['evidence'])):
            raise records.SourceRecordError('invalid_source_record', 'resolution requires bound evidence sources')
        for index, (o,p) in enumerate(zip(card['observations'], card['predictions'])):
            if (_physical_record(o), _physical_record(p)) == expected and not resolutions:
                holds.append({**deepcopy(defect), 'input_observation_index': index,
                              'retained_input_observation': deepcopy(o), 'retained_input_prediction': deepcopy(p),
                              'intended_physical_response': None, 'source_bindings': deepcopy(inputs)})
    coverage = [r for r in value['coverage'] if r['input_fingerprint'] == input_fingerprint]
    if len(coverage) != 1 and not holds:
        raise records.SourceRecordError('missing_input_review', 'one matching reviewed input coverage record required')
    if len(coverage)>1:
        raise records.SourceRecordError('invalid_source_record','ambiguous input review')
    capture.finish()
    selected = coverage[0] if len(coverage) == 1 else {'assumptions': [], 'support': {}}
    for placement in selected['support'].get('nuisance_placements',[]):
        if (not placement.get('evidence') or any(label not in sources for label in placement['evidence'])
                or placement.get('native_disposition') != 'retained_unused'):
            raise records.SourceRecordError('invalid_source_record','nuisance placement needs bound evaluator evidence')
    return {'native_law_assumptions': deepcopy(selected['assumptions']),
            'scientific_input_support': {**deepcopy(selected['support']),
                'input_fingerprint': input_fingerprint, 'reviewed_registry': inputs[0],
                'context': deepcopy(value['context']), 'physics_validated': False,
                'input_disposition': 'held_source_defect' if holds else 'reviewed_supplied_input_unqualified'},
            'scientific_input_holds': holds, 'reviewed_inputs': inputs}


def require_supported(root, card, registry=None):
    support = inspect(root, card, registry)
    if support['scientific_input_holds']:
        raise HiggsInputSupportError(support)
    return support


def contract_metadata(contract):
    if contract.get('profile') not in ('top','higgs'):
        return {}
    if not set(FIELDS) <= set(contract):
        raise records.SourceRecordError('missing_defect_registry', 'complete source-support ledger required')
    return {field:deepcopy(contract[field]) for field in FIELDS}


def verify_saved(cap, delivery, contract):
    expected = contract_metadata(contract)
    if any(records.encoded(cap.get(k)) != records.encoded(v) or records.encoded(delivery.get(k)) != records.encoded(v)
           for k,v in expected.items()):
        raise ValueError('saved source assumptions/support/holds differ; source requalification required')
