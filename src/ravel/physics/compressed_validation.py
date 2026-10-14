"""Source-bound event traces and supplied cutflow comparisons with shared-event moments."""
from __future__ import annotations
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from . import reviewed_source as records


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class CutflowDefinition:
    def __init__(self, pin, base="."):
        if pin is None or (isinstance(pin,dict) and (not pin.get('path') or not pin.get('sha256'))):
            raise records.SourceRecordError('missing_cutflow_definition','explicit byte-bound cutflow definition required')
        value, sources, inputs, capture = records.load(pin, base, "cutflow-definition", "missing_cutflow_definition")
        predicates = set(value['predicates'])
        if value['selection_source'] not in sources or not set(value['unavailable']) <= predicates:
            raise records.SourceRecordError('source_scope_mismatch', 'selection source or unavailable predicates absent')
        if not set(value['object_preconditions']) <= predicates:
            raise records.SourceRecordError('source_scope_mismatch', 'object preconditions absent from predicate population')
        for flow in value['flows'].values():
            if not set(flow) <= predicates:
                raise records.SourceRecordError('source_scope_mismatch', 'flow contains undefined predicates')
        for member in value['membership']:
            if member['flow'] not in value['flows'] or member['through'] not in value['flows'][member['flow']]:
                raise records.SourceRecordError('source_scope_mismatch', 'membership flow or terminal predicate absent')
            if not member['regions'] or len(set(member['regions'])) != len(member['regions']):
                raise records.SourceRecordError('source_scope_mismatch', 'membership needs unique explicit regions')
        for reference in value['references']:
            if reference['flow'] not in value['flows'] or reference['source'] not in sources:
                raise records.SourceRecordError('source_scope_mismatch', 'reference flow or source absent')
            if len({row['index'] for row in reference['rows']}) != len(reference['rows']):
                raise records.SourceRecordError('source_scope_mismatch', 'duplicate reference row mapping')
            if any(row['predicate'] not in predicates and row['predicate'] != 'inclusive_normalization' for row in reference['rows']):
                raise records.SourceRecordError('source_scope_mismatch', 'undefined reference predicate')
        capture.finish()
        self._value_json = records.encoded(value)
        self.sources = MappingProxyType(sources)
        self._inputs_json = records.encoded(inputs)

    @property
    def value(self):
        return records.document(self._value_json)

    @property
    def inputs(self):
        return records.document(self._inputs_json)

    @property
    def pin(self):
        return self.inputs[0]

    def new_event(self, event_id, weight):
        return new_event(event_id, weight, self)

    def write_trace(self, path, data, metadata):
        return write_trace(path, data, metadata, self)

    def summarize_trace(self, path, definition=None):
        return summarize_trace(path, self if definition is None else definition)


def bind(pin, base="."):
    return CutflowDefinition(pin, base)


def native_plan_inputs(pin, base, producer):
    """Prepare trace flags and byte dependencies; the existing planner owns launch.

    ``producer`` is the source file of the selected routine that writes the trace (the
    supplied analysis package's selection); the definition must bind exactly its bytes."""
    definition = bind(pin, base)
    producer = Path(producer)
    selected = definition.sources[definition.value['selection_source']]
    if hashlib.sha256(selected).hexdigest() != file_hash(producer):
        raise records.SourceRecordError('source_scope_mismatch','cutflow definition must bind the selected native producer bytes')
    dependencies = [Path(pin['path']) for pin in definition.inputs]
    dependencies.extend((Path(__file__),Path(records.__file__),Path(__file__).with_name('ma5_saf.py')))
    return {'arguments':['--validation-definition',definition.pin['path'],
                         '--validation-definition-sha256',definition.pin['sha256']],
            'inputs':dependencies}


def _definition(definition):
    if definition is None:
        raise records.SourceRecordError('missing_cutflow_definition', 'explicit byte-bound cutflow definition required')
    return definition if isinstance(definition, CutflowDefinition) else bind(definition)


def new_event(event_id, weight, definition=None):
    definition = _definition(definition)
    if type(event_id) is not int or type(weight) not in (int, float) or not math.isfinite(weight):
        raise ValueError('trace needs an integer event ID and finite original weight')
    value = definition.value
    return {'event_id':event_id, 'weight_pb':float(weight),
            'predicates':dict.fromkeys(value['predicates']), 'objects':{}, 'kinematics':{},
            'rjr_status':'not_reached', 'origin_state':None, 'accepted_regions':[],
            'trace_definition':{'predicates':value['predicates'], 'unavailable':value['unavailable'],
                'object_preconditions':value['object_preconditions'], 'binding':definition.pin}}


def object_preconditions(record):
    return record['trace_definition']['object_preconditions']


def _validated(record, definition=None):
    if type(record.get('event_id')) is not int:
        raise ValueError('trace event ID must be an integer')
    weight = record.get('weight_pb')
    if type(weight) not in (int, float) or not math.isfinite(weight):
        raise ValueError('trace weight must be finite')
    declared = record.get('trace_definition')
    if not isinstance(declared, dict) or set(declared) != {'predicates','unavailable','object_preconditions','binding'}:
        raise records.SourceRecordError('missing_cutflow_definition', 'trace lacks supplied definition')
    if definition is None:
        definition = bind(declared['binding'])
    if definition is not None:
        value = definition.value
        expected = {'predicates':value['predicates'], 'unavailable':value['unavailable'],
                    'object_preconditions':value['object_preconditions'], 'binding':definition.pin}
        if declared != expected:
            raise records.SourceRecordError('source_scope_mismatch', 'trace definition differs from bound header')
    predicates = record.get('predicates')
    if not isinstance(predicates, dict) or set(predicates) != set(declared['predicates']):
        raise ValueError('trace predicate population is incomplete or unknown')
    if any(value is not None and type(value) is not bool for value in predicates.values()):
        raise ValueError('trace predicates must be boolean or null')
    if any(predicates[key] is not None for key in declared['unavailable']):
        raise ValueError('unrepresented predicates cannot be promoted to measured decisions')
    regions = record.get('accepted_regions')
    if not isinstance(regions, list) or any(not isinstance(x, str) for x in regions) or len(set(regions)) != len(regions):
        raise ValueError('trace region membership must contain unique names')
    records.encoded(record)
    return record


def write_trace(path, data, metadata, definition=None):
    definition = _definition(definition)
    seen = set()
    with Path(path).open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
        header = {'kind':'header', 'schema_version':1, 'level':'reco', 'weight_unit':'pb',
                  'metadata':metadata, 'cutflow_definition':definition.pin}
        stream.write(records.encoded(header) + b'\n')
        for record in data:
            _validated(record, definition)
            if record['event_id'] in seen:
                raise ValueError('duplicate trace event ID')
            seen.add(record['event_id'])
            stream.write(records.encoded(record) + b'\n')


def _and(left, right):
    return False if left is False or right is False else (None if left is None or right is None else True)


def _moments():
    return {"count": 0, "sumw_pb": 0.0, "sumw2_pb2": 0.0, "unknown_count": 0}


def _add(moment, weight, passed):
    if passed is True:
        moment["count"] += 1
        moment["sumw_pb"] += weight
        moment["sumw2_pb2"] += weight*weight
    elif passed is None:
        moment["unknown_count"] += 1


def _ratio(numerator, denominator):
    # Nested masks share events: Cov(sumw_pass,sumw_before) = sumw2_pass.
    d, n = denominator["sumw_pb"], numerator["sumw_pb"]
    if d == 0 or numerator["unknown_count"] or denominator["unknown_count"]:
        return {"status": "unresolved", "ratio": None, "mc_standard_error": None}
    ratio = n/d
    if numerator["count"] == 0 or numerator["sumw2_pb2"] == 0:
        return {"status": "zero_selected_precision_unresolved", "ratio": ratio,
                "mc_standard_error": None, "method": "No finite-MC upper bound inferred from zero selected weight"}
    variance = (numerator["sumw2_pb2"]*(1-2*ratio)
                + ratio*ratio*denominator["sumw2_pb2"])/(d*d)
    return {"status": "estimated", "ratio": ratio,
            "mc_standard_error": math.sqrt(max(0.0, variance)),
            "method": "delta method with shared-event covariance; no reference uncertainty included"}


def summarize_trace(path, definition=None):
    with gzip.open(path, 'rt') as stream:
        header = records.document(next(stream))
        if header.get('schema_version') != 1 or header.get('kind') != 'header' or header.get('level') != 'reco' or header.get('weight_unit') != 'pb':
            raise ValueError('unsupported trace header')
        if 'cutflow_definition' not in header:
            raise records.SourceRecordError('missing_cutflow_definition', 'trace header lacks selected definition')
        selected = _definition(definition or header['cutflow_definition'])
        if header['cutflow_definition'] != selected.pin:
            raise records.SourceRecordError('source_scope_mismatch', 'selected definition differs from trace header')
        value = selected.value
        if any(header['metadata'].get(k) != v for k,v in value['normalization']['population_metadata'].items()):
            raise records.SourceRecordError('normalization_population_mismatch', 'trace population differs from normalization contract')
        rows = value['flows']
        moments = {flow:{key:_moments() for key in keys} for flow,keys in rows.items()}
        all_events, seen, regions = _moments(), set(), {}
        for line in stream:
            record = _validated(records.document(line), selected)
            event_id, weight = record['event_id'], record['weight_pb']
            if event_id in seen:
                raise ValueError('duplicate trace event ID')
            seen.add(event_id)
            _add(all_events, weight, True)
            for region in record['accepted_regions']:
                _add(regions.setdefault(region, _moments()), weight, True)
            masks = {}
            for flow,keys in rows.items():
                mask = True
                for key in keys:
                    mask = _and(mask, record['predicates'][key])
                    masks[(flow,key)] = mask
                    _add(moments[flow][key], weight, mask)
            for member in value['membership']:
                mask = masks[(member['flow'],member['through'])]
                count = len(set(record['accepted_regions']) & set(member['regions']))
                if (member['exclusive'] and count > 1) or (count and mask is None) or (mask is not None and bool(count) != mask):
                    raise ValueError('trace predicates disagree with declared production membership')
    if not seen:
        raise ValueError('empty event trace')
    expected = header['metadata'].get('input_events')
    if expected is not None and (type(expected) is not int or expected != len(seen)):
        raise ValueError('trace event population disagrees with declared input count')
    cutflows = {}
    for flow,keys in rows.items():
        previous = all_events
        cutflows[flow] = []
        for key in keys:
            current = moments[flow][key]
            cutflows[flow].append({'predicate':key, **current, 'conditional':_ratio(current,previous),
                                  'cumulative':_ratio(current,all_events)})
            previous = current
    comparisons = {}
    luminosity = value['normalization']['luminosity_pb_inverse']
    for reference in value['references']:
        raw = selected.sources[reference['source']]
        import yaml
        # JSON is YAML-compatible; parsing is data-only, never a source import.
        table = yaml.safe_load(raw)
        weighted = records.select(table, reference['values_pointer'])
        if not isinstance(weighted, list) or any(type(x) not in (int,float) or not math.isfinite(x) or x < 0 for x in weighted):
            raise ValueError('finite nonnegative supplied reference values required')
        flow = reference['flow']
        if flow in comparisons:
            raise ValueError('one reference per declared flow required')
        comparison_rows = []
        for mapping in reference['rows']:
            index, key = mapping['index'], mapping['predicate']
            if not index < len(weighted):
                raise ValueError('reference row index outside supplied population')
            native = all_events if key == 'inclusive_normalization' else moments[flow].get(key)
            comparable = native is not None and not native['unknown_count'] and not value['unavailable']
            comparison_rows.append({'reference_row_index':index, 'predicate':key,
                'reference_weighted_events':weighted[index],
                'reference_conditional_ratio':weighted[index]/weighted[index-1] if index and weighted[index-1] else None,
                'native_cumulative_weighted_events_at_reference_lumi':native['sumw_pb']*luminosity if native and not native['unknown_count'] else None,
                'status':'diagnostic_only' if comparable else 'diagnostic_only_unmatched_prior_predicates'})
        comparisons[flow] = {'source_sha256':hashlib.sha256(raw).hexdigest(),
            'reference_luminosity_pb_inverse':luminosity, 'rows':comparison_rows}
    result = {'schema_version':1, 'trace_sha256':file_hash(path), 'source_metadata':header['metadata'],
        'context':deepcopy(value['context']), 'normalization':deepcopy(value['normalization']),
        'definition_inputs':selected.inputs, 'level':'reco', 'all_events':all_events,
        'cutflows':cutflows, 'regions':regions, 'unknown_reference_predicates':deepcopy(value['unavailable']),
        'truth_acceptance':{'status':'unavailable'},
        'input_population_status':'verified_count' if expected is not None else 'input_count_not_declared',
        'first_comparable_reference_divergence':None, 'reference_cutflows':comparisons,
        'comparison_status':'diagnostic_only', 'physics_validated':False}
    records.encoded(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', required=True)
    parser.add_argument('--definition', required=True, help='supplied reviewed cutflow definition')
    parser.add_argument('--definition-sha256', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--format', choices=('json','jsonl'), required=True)
    args = parser.parse_args(argv)
    report = summarize_trace(args.trace, {'path':args.definition,'sha256':args.definition_sha256})
    Path(args.out).write_text(json.dumps(report, indent=2 if args.format=='json' else None, allow_nan=False)+'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
