"""Validate and compile a declarative columnar analysis recipe.

A recipe (``kind: columnar-analysis-recipe``, ``schema_version: 1``) is JSON data:

- ``weights``: ``{"generator": <event field or null>, "factors": [...]}``.
  Factors are event-field strings, ``{"field": <event field>}``,
  ``{"object_product": {"objects": <selected collection>, "field": <field>}}`` or
  ``{"trigger_or_sf": {"objects": <selected collection>, "data_eff": <field>,
  "mc_eff": <field>}}``. Products over empty collections are one; trigger ratios
  with zero MC acceptance refuse. Any factor may add ``applies_when: {field, in}``.
  Event-field factors may add ``optional_in_files: true`` for absent ROOT branches;
- ``efficiency_maps``: named maps (see ``efficiency.load_map``);
- ``event_weights``: named scale-factor maps keyed by one or two declared observables,
  with ``out_of_range`` refuse/clamp/one and optional ``variations`` {pass name: map};
- ``objects``: an ordered list of object steps (definitions, unions, overlap removal,
  isolation, efficiency application and pair splitting);
- ``observables``: an ordered list of per-event quantities (see ``observables``);
- ``regions``: named regions with ordered, named cuts (expressions over observables
  or ``any_of_by_period: {period_field, table}`` over numeric event fields),
  optionally starting from a ``base`` region's cuts;
- ``histograms``: binned observables in a region with declared edges, units,
  natural-language labels, normalisation and flow conventions;
- ``systematics``: weight, branch and efficiency-map variations of the whole pass;
- ``event_record``: an optional per-event record of the first events for review;
- ``features``: an optional bounded nominal feature population with sample role,
  exact event/group identities, deterministic sampling and explicit weight policies.

Every name is checked when the recipe is compiled, before any event is read.
"""
import hashlib
import json
import math
import re
from dataclasses import dataclass, field

import numpy as np

from . import efficiency
from .expressions import compile_expression
from .observables import compile_observable

NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
NORMALIZATIONS = ('yield', 'raw', 'fraction', 'density', 'yield-per-width')
MAX_BINS = 100_000
MAX_RECORD = 10_000
APPLICATIONS = ('select', 'enumerate', 'all-required-weight')
MAX_ENUMERATED = 12
DEFAULT_ENUMERATED = 8


def _keys(value, required, optional=(), label='entry'):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')
    missing, extra = set(required) - set(value), set(value) - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f'{label}: missing {sorted(missing)} or unexpected {sorted(extra)}; '
                         f'allowed keys are {sorted(set(required) | set(optional))}')


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    return value.strip()


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return float(value)


def natural_label(value, label):
    """A display label in plain words; scientific math between $...$ is allowed."""
    from ravel.plotting.display_labels import label_errors
    text = _text(value, label)
    problems = label_errors(text)
    if problems:
        raise ValueError(f'{label} {text!r} is not a natural-language label: {"; ".join(problems)}')
    return text


@dataclass
class ObjectStep:
    kind: str
    spec: dict
    expressions: dict = field(default_factory=dict)


@dataclass
class Histogram:
    name: str
    region: str
    observables: list
    edges: list
    units: list
    labels: list
    normalization: str
    overflow: str
    underflow: str
    fraction_denominator: str
    precision_target: object
    value_unit: object
    value_label: object
    slice_width: object = None

    @property
    def shape(self):
        return tuple(len(e) - 1 for e in self.edges)


@dataclass
class Plan:
    doc: dict
    descriptor: object
    maps: dict
    steps: list
    observables: list
    regions: dict
    histograms: list
    systematics: list
    record: object
    object_fields: dict
    source_collections: list
    event_fields: list
    variations: list
    recipe_sha256: str
    identity: str
    card_report: object = None
    spec_nodes: dict = field(default_factory=dict)
    event_weights: list = field(default_factory=list)
    weight_entries: list = field(default_factory=list)
    skim: object = None
    features: object = None

    def variation_names(self):
        return ['nominal'] + [s['name'] for s in self.systematics]


def _event_field(value, descriptor, label):
    if not isinstance(value, str) or value not in descriptor.event:
        raise ValueError(f'{label}: {value!r} is not an event field of the format descriptor')
    return value


def _period_values(value, label):
    if not isinstance(value, list) or not value:
        raise ValueError(f'{label} must be a nonempty list of finite numeric period values')
    return [_number(v, label) for v in value]


def _compile_weights(factors, descriptor, fields, event_fields):
    """Compile each factor to {kind, field(s), applies_when?, optional_in_files?}."""
    if not isinstance(factors, list):
        raise ValueError('weights.factors must be a list of typed weight entries or event fields')
    entries = []
    for i, original in enumerate(factors):
        label = f'weight factor {i + 1}'
        spec = {'field': original} if isinstance(original, str) else original
        if not isinstance(spec, dict):
            raise ValueError(f'{label} must be an event field or a typed weight entry')
        kinds = set(spec) & {'field', 'object_product', 'trigger_or_sf'}
        if len(kinds) != 1:
            raise ValueError(f'{label} needs exactly one of field, object_product or trigger_or_sf')
        kind = next(iter(kinds))
        _keys(spec, (kind,), ('applies_when', 'optional_in_files'), label)
        entry = {'kind': 'event-field' if kind == 'field' else kind}
        if kind == 'field':
            entry['field'] = _event_field(spec['field'], descriptor, label)
            event_fields.append(entry['field'])
        else:
            required = ('objects', 'field') if kind == 'object_product' else ('objects', 'data_eff', 'mc_eff')
            _keys(spec[kind], required, (), label)
            entry.update(spec[kind])
            collection = entry['objects']
            if not isinstance(collection, str) or collection not in fields:
                raise ValueError(f'{label}: unknown selected collection {collection!r}')
            for key in required[1:]:
                if not isinstance(entry[key], str) or entry[key] not in fields[collection]:
                    raise ValueError(f'{label}: {collection!r} has no field {entry[key]!r}')
        if 'optional_in_files' in spec:
            if type(spec['optional_in_files']) is not bool:
                raise ValueError(f'{label}: optional_in_files must be true or false')
            if kind != 'field' or descriptor.format != 'root':
                raise ValueError(f'{label}: optional_in_files requires an event-field factor in ROOT files')
            entry['optional_in_files'] = spec['optional_in_files']
        if 'applies_when' in spec:
            condition = spec['applies_when']
            _keys(condition, ('field', 'in'), (), label)
            name = _event_field(condition['field'], descriptor, label)
            entry['applies_when'] = {'field': name, 'in': _period_values(condition['in'], label)}
            event_fields.append(name)
        entries.append(entry)
    return entries


class PeriodCut:
    """An event-field cut with the same evaluation interface as an expression."""
    uses_event_fields = True

    def __init__(self, spec, descriptor, event_fields):
        _keys(spec, ('period_field', 'table'), (), 'any_of_by_period')
        self.period_field = _event_field(spec['period_field'], descriptor, 'period_field')
        event_fields.append(self.period_field)
        if not isinstance(spec['table'], dict) or not spec['table']:
            raise ValueError('any_of_by_period table must be a nonempty object')
        self.table = {}
        for key, names in spec['table'].items():
            try:
                period = float(key)
            except (TypeError, ValueError):
                raise ValueError(f'trigger table period {key!r} must be numeric') from None
            if not np.isfinite(period) or period in self.table:
                raise ValueError(f'trigger table period {key!r} is nonfinite or duplicated')
            if not isinstance(names, list) or not names:
                raise ValueError(f'trigger table period {key!r} needs a nonempty list of boolean event fields')
            self.table[period] = [_event_field(n, descriptor, 'trigger field') for n in names]
            event_fields.extend(names)
        self.text = json.dumps({'any_of_by_period': spec}, sort_keys=True)

    def evaluate_cut(self, namespace):
        periods = np.asarray(namespace[self.period_field])
        known = np.isin(periods, list(self.table))
        if not known.all():
            raise ValueError(f'any_of_by_period: unknown period {periods[np.flatnonzero(~known)[0]]!r}')
        result = np.zeros(len(periods), bool)
        for period, names in self.table.items():
            active = periods == period
            for name in names:
                values = np.asarray(namespace[name])[active]
                if not np.isin(values, [0, 1]).all():
                    raise ValueError(f'trigger event field {name!r} must contain boolean values (0 or 1)')
                result[active] |= values.astype(bool)
        return result


class _OptionalEventDescriptor:
    """Recipe-local read policy; the shared format descriptor remains unchanged.

    Both planning's check_file and execution's read use the same optional-field policy.
    Only a missing nominal branch is optional; malformed present branches still refuse.
    """
    def __init__(self, descriptor, optional):
        self._descriptor, self._optional = descriptor, frozenset(optional)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_descriptor'), name)

    def _fields(self, path, event_fields):
        import uproot
        fields = list(self.event) if event_fields is None else list(event_fields)
        with uproot.open(path) as stream:
            try:
                tree = stream[self.doc['tree']]
            except KeyError:
                raise ValueError(f'{path} has no tree {self.doc["tree"]!r}') from None
            available = {b.name for b in tree.values(recursive=True)}
        missing = sorted(f for f in fields if f in self._optional
                         and 'branch' in self.event[f] and self.event[f]['branch'] not in available)
        return [f for f in fields if f not in missing], missing

    def check_file(self, path, *, event_fields=None, **kwargs):
        fields, missing = self._fields(path, event_fields)
        report = self._descriptor.check_file(path, event_fields=fields, **kwargs)
        report['optional_weights_missing'] = missing
        return report

    def read(self, path, *, event_fields, **kwargs):
        fields, _ = self._fields(path, event_fields)
        yield from self._descriptor.read(path, event_fields=fields, **kwargs)


def compile_recipe(doc, descriptor, base, *, detector_card=None):
    """Return a Plan; raises ValueError naming the first problem.

    Any object step, observable, event weight, cut or histogram may carry ``spec_item`` (an id of a typed
    analysis specification item, or a list of ids); they are collected in ``Plan.spec_nodes``.

    ``detector_card`` (a Delphes card) checks each efficiency map's semantics against the
    card's efficiency modules (``efficiency.check_card``).
    """
    from .skim import InputDescriptor
    while isinstance(descriptor, (InputDescriptor, _OptionalEventDescriptor)):
        descriptor = descriptor.descriptor if isinstance(descriptor, InputDescriptor) else descriptor._descriptor
    _keys(doc, ('schema_version', 'kind', 'name', 'weights', 'objects', 'observables', 'regions', 'histograms'),
          ('description', 'efficiency_maps', 'systematics', 'event_record', 'event_weights', 'skim', 'features'),
          'recipe')
    if doc['schema_version'] != 1 or doc['kind'] != 'columnar-analysis-recipe':
        raise ValueError('recipe needs schema_version 1 and kind columnar-analysis-recipe')
    _text(doc['name'], 'recipe name')
    canonical = json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False)
    recipe_sha256 = hashlib.sha256(canonical.encode()).hexdigest()
    doc, spec_nodes = _strip_spec_items(doc)

    weights = doc['weights']
    _keys(weights, ('generator', 'factors'), (), 'weights')
    event_fields = []
    if weights['generator'] is not None:
        event_fields.append(_event_field(weights['generator'], descriptor, 'generator weight'))

    maps = {}
    for name, spec in (doc.get('efficiency_maps') or {}).items():
        _text(name, 'efficiency map name')
        maps[name] = efficiency.load_map(name, spec, base)
    card_report = efficiency.check_card(maps, detector_card) if detector_card is not None else None

    # ------------------------------------------------------------ objects
    fields, steps, sources, step_names = {}, [], [], set()

    def object_name(value, label):
        if not isinstance(value, str) or not NAME.match(value):
            raise ValueError(f'{label} {value!r} must be a name of letters, digits and _')
        return value

    def known(value, label):
        if value not in fields:
            raise ValueError(f'{label}: unknown object {value!r} (defined so far: {sorted(fields)})')
        return value

    def new(name):
        if name in fields:
            raise ValueError(f'object {name!r} is defined twice')

    def select(expr, names, label):
        return None if expr is None else compile_expression(expr, allowed=names)

    if not isinstance(doc['objects'], list):
        raise ValueError('objects must be an ordered list of steps')
    for i, step in enumerate(doc['objects']):
        label = f'object step {i + 1}'
        if not isinstance(step, dict):
            raise ValueError(f'{label} must be an object')
        if 'from' in step:
            _keys(step, ('name', 'from'), ('select', 'sort'), label)
            name = object_name(step['name'], label); new(name)
            if step['from'] not in descriptor.collections:
                raise ValueError(f'{label}: {step["from"]!r} is not a collection of the format descriptor '
                                 f'({sorted(descriptor.collections)})')
            available = set(descriptor.collections[step['from']]) | ({'flavour'} if 'pdg_id' in descriptor.collections[step['from']] else set())
            if descriptor.format == 'lhe':
                available = {'pt', 'eta', 'phi', 'mass', 'e', 'pdg_id', 'flavour'} | (
                    {'charge'} if descriptor.collections[step['from']]['charge_sign'] is not None else set())
            sources.append(step['from'])
            steps.append(ObjectStep('define', step, {'select': select(step.get('select'), available, label)}))
            fields[name] = available
        elif 'from_object' in step:
            _keys(step, ('name', 'from_object'), ('select', 'sort'), label)
            name = object_name(step['name'], label); new(name)
            parent = known(step['from_object'], label)
            steps.append(ObjectStep('subset', step, {'select': select(step.get('select'), fields[parent], label)}))
            fields[name] = set(fields[parent])
        elif 'union' in step:
            _keys(step, ('name', 'union'), ('select',), label)
            name = object_name(step['name'], label); new(name)
            if not isinstance(step['union'], list) or len(step['union']) < 2:
                raise ValueError(f'{label}: union needs two or more objects')
            common = set.intersection(*[fields[known(x, label)] for x in step['union']])
            steps.append(ObjectStep('union', step, {'select': select(step.get('select'), common, label)}))
            fields[name] = common
        elif 'overlap_removal' in step:
            _keys(step, ('overlap_removal',), (), label)
            spec = step['overlap_removal']
            _keys(spec, ('remove', 'near', 'dr'), ('remove_select', 'near_select'), label)
            a, b = known(spec['remove'], label), known(spec['near'], label)
            exprs = {'remove_select': select(spec.get('remove_select'), fields[a], label),
                     'near_select': select(spec.get('near_select'), fields[b], label)}
            if isinstance(spec['dr'], str):
                exprs['dr'] = compile_expression(spec['dr'], allowed=fields[a])
            elif _number(spec['dr'], f'{label} dr') <= 0:
                raise ValueError(f'{label}: dr must be positive')
            steps.append(ObjectStep('overlap', spec, exprs))
        elif 'isolation' in step:
            _keys(step, ('isolation',), (), label)
            spec = step['isolation']
            _keys(spec, ('object', 'against', 'cone', 'field', 'relative'), ('against_select', 'min_cone'), label)
            a, b = known(spec['object'], label), known(spec['against'], label)
            if not NAME.match(str(spec['field'])) or spec['field'] in fields[a]:
                raise ValueError(f'{label}: isolation field {spec["field"]!r} must be a new field name')
            cone = _number(spec['cone'], f'{label} cone'); inner = _number(spec.get('min_cone', 0.0), f'{label} min_cone')
            if not 0 <= inner < cone or type(spec['relative']) is not bool:
                raise ValueError(f'{label}: need 0 <= min_cone < cone and relative true or false')
            steps.append(ObjectStep('isolation', spec, {'against_select': select(spec.get('against_select'), fields[b], label)}))
            fields[a] = fields[a] | {spec['field']}
        elif 'efficiency' in step:
            _keys(step, ('efficiency',), (), label)
            spec = step['efficiency']
            _keys(spec, ('name', 'object', 'map', 'coordinates', 'application', 'card_efficiency'), ('seed', 'max_objects'), label)
            step_name = _text(spec['name'], f'{label} name')
            if step_name in step_names:
                raise ValueError(f'{label}: efficiency step {step_name!r} is named twice')
            step_names.add(step_name)
            a = known(spec['object'], label)
            if spec['map'] not in maps:
                raise ValueError(f'{label}: unknown efficiency map {spec["map"]!r}')
            _text(spec['card_efficiency'], f'{label} card_efficiency (how double counting with the detector card is avoided)')
            if not isinstance(spec['coordinates'], list) or len(spec['coordinates']) != len(maps[spec['map']].axes):
                raise ValueError(f'{label}: give one coordinate expression per map axis')
            if spec['application'] not in APPLICATIONS:
                raise ValueError(f'{label}: application must be one of {APPLICATIONS}; all-required-weight is exact '
                                 'only when the selection requires every object, enumerate is exact for any selection')
            if 'max_objects' in spec and (spec['application'] != 'enumerate' or type(spec['max_objects']) is not int
                                          or not 1 <= spec['max_objects'] <= MAX_ENUMERATED):
                raise ValueError(f'{label}: max_objects (1 to {MAX_ENUMERATED}) belongs to the enumerate application')
            if spec['application'] == 'select' and (type(spec.get('seed')) is not int or not 0 <= spec['seed'] < 2 ** 63):
                raise ValueError(f'{label}: select application needs an integer seed')
            exprs = {f'c{k}': compile_expression(c, allowed=fields[a]) for k, c in enumerate(spec['coordinates'])}
            steps.append(ObjectStep('efficiency', spec, exprs))
        elif 'pair_split' in step:
            _keys(step, ('pair_split',), (), label)
            spec = step['pair_split']
            _keys(spec, ('from', 'charge', 'flavour', 'choose', 'pair', 'rest'), ('target_mass', 'source'), label)
            parent = known(spec['from'], label)
            if spec['charge'] not in ('opposite', 'any') or spec['flavour'] not in ('same', 'any'):
                raise ValueError(f'{label}: charge is opposite or any; flavour is same or any')
            need = ({'charge'} if spec['charge'] == 'opposite' else set()) | ({'flavour'} if spec['flavour'] == 'same' else set())
            if need - fields[parent]:
                raise ValueError(f'{label}: object {parent!r} has no {sorted(need - fields[parent])} field')
            if spec['choose'] not in ('closest-to-mass', 'leading', 'highest-mass'):
                raise ValueError(f'{label}: choose is closest-to-mass, leading or highest-mass')
            if spec['choose'] == 'closest-to-mass':
                _number(spec.get('target_mass'), f'{label} target_mass'); _text(spec.get('source'), f'{label} source')
            for out in (spec['pair'], spec['rest']):
                new(object_name(out, label))
                fields[out] = set(fields[parent])
            steps.append(ObjectStep('pair_split', spec))
        else:
            raise ValueError(f'{label} must define an object (from, from_object, union) or be overlap_removal, '
                             'isolation, efficiency or pair_split')

    weight_entries = _compile_weights(weights['factors'], descriptor, fields, event_fields)

    # ------------------------------------------------------------ observables
    observables, names, met_names = [], set(), {'met'}
    if not isinstance(doc['observables'], list):
        raise ValueError('observables must be an ordered list')
    for i, spec in enumerate(doc['observables']):
        obs = compile_observable(spec, fields=fields, previous=set(names), met_names=met_names,
                                 label=f'observable {i + 1}', base=base, event_fields=descriptor.event)
        if obs.op == 'model_score':
            if any(s.kind == 'efficiency' and s.spec.get('application') == 'enumerate' for s in steps):
                raise ValueError('model_score refuses enumerated event replicas')
            event_fields.append(obs.spec['group_id'])
        if obs.name in names:
            raise ValueError(f'observable {obs.name!r} is defined twice')
        names.add(obs.name)
        observables.append(obs)
        if obs.op == 'met_override':
            met_names.add(obs.name)

    # Event maps use the shared, pinned map reader, but their range policy belongs to
    # the event application rather than the object-efficiency application.
    event_weights, event_variations = [], []
    if not isinstance(doc.get('event_weights', []), list):
        raise ValueError('event_weights must be a list')
    for i, spec in enumerate(doc.get('event_weights', [])):
        label = f'event weight {i + 1}'
        _keys(spec, ('name', 'map', 'observables', 'out_of_range'), ('variations',), label)
        name = _text(spec['name'], f'{label} name')
        if name in {s['name'] for s in event_weights}:
            raise ValueError(f'{label}: name {name!r} is defined twice')
        coords = spec['observables']
        if not isinstance(coords, list) or not 1 <= len(coords) <= 2:
            raise ValueError(f'{label}: give one or two declared event observables')
        for coord in coords:
            if not isinstance(coord, str) or coord not in names:
                raise ValueError(f'{label}: undeclared event observable {coord!r}')
        if spec['out_of_range'] not in ('refuse', 'clamp', 'one'):
            raise ValueError(f'{label}: out_of_range must be refuse, clamp or one')

        def check_map(key):
            if key not in maps or maps[key].semantics != 'scale_factor':
                raise ValueError(f'{label}: map {key!r} must be a declared scale_factor map')
            if len(maps[key].axes) != len(coords):
                raise ValueError(f'{label}: give one observable per map axis')
            for coord, axis in zip(coords, maps[key].axes):
                obs = next(o for o in observables if o.name == coord)
                if obs.unit is not None and obs.unit != axis['unit']:
                    raise ValueError(f'{label}: observable {coord!r} unit differs from map axis')
        check_map(spec['map'])
        alternatives = spec.get('variations', {})
        if not isinstance(alternatives, dict):
            raise ValueError(f'{label}: variations must map pass names to maps')
        for variation, key in alternatives.items():
            check_map(key)
            if maps[key].axes != maps[spec['map']].axes:
                raise ValueError(f'{label}: varied map axes differ from nominal axes')
            event_variations.append({'name': variation, 'kind': 'event-weight-map', 'weight': name, 'map': key})
        event_weights.append(dict(spec))

    # ------------------------------------------------------------ regions
    regions = {}
    if not isinstance(doc['regions'], list):
        raise ValueError('regions must be a list')
    for i, spec in enumerate(doc['regions']):
        label = f'region {i + 1}'
        _keys(spec, ('name', 'cuts'), ('base', 'description'), label)
        name = _text(spec['name'], f'{label} name')
        if name in regions:
            raise ValueError(f'region {name!r} is defined twice')
        cuts = []
        if 'base' in spec:
            if spec['base'] not in regions:
                raise ValueError(f'{label}: base region {spec["base"]!r} must be defined earlier')
            cuts = list(regions[spec['base']])
        if not isinstance(spec['cuts'], list):
            raise ValueError(f'{label}: cuts must be a list')
        for j, cut in enumerate(spec['cuts']):
            _keys(cut, ('name',), ('expr', 'any_of_by_period'), f'{label} cut {j + 1}')
            if ('expr' in cut) == ('any_of_by_period' in cut):
                raise ValueError(f'{label} cut {j + 1}: give exactly one of expr or any_of_by_period')
            compiled = (compile_expression(cut['expr'], allowed=names) if 'expr' in cut else
                        PeriodCut(cut['any_of_by_period'], descriptor, event_fields))
            cuts.append((_text(cut['name'], 'cut name'), compiled))
        if len({c[0] for c in cuts}) != len(cuts):
            raise ValueError(f'{label}: cut names must be unique within the region')
        regions[name] = cuts

    # ------------------------------------------------------------ histograms
    histograms = []
    if not isinstance(doc['histograms'], list):
        raise ValueError('histograms must be a list')
    seen = set()
    for i, spec in enumerate(doc['histograms']):
        histograms.append(_histogram(spec, regions, names, f'histogram {i + 1}'))
        if histograms[-1].name in seen:
            raise ValueError(f'histogram {histograms[-1].name!r} is defined twice')
        seen.add(histograms[-1].name)
    slugs = [slug(h.name) for h in histograms]
    if len(set(slugs)) != len(slugs):
        raise ValueError('histogram names must give distinct file names')

    # ------------------------------------------------------------ systematics
    systematics, variations = [], []
    for i, spec in enumerate([*(doc.get('systematics') or []), *event_variations]):
        label = f'systematic {i + 1}'
        if not isinstance(spec, dict) or spec.get('kind') not in ('weight-factor', 'branch-variation', 'efficiency-map', 'event-weight-map'):
            raise ValueError(f'{label}: kind must be weight-factor, branch-variation, efficiency-map or event-weight-map')
        name = _text(spec.get('name'), f'{label} name')
        if name == 'nominal' or name in {s['name'] for s in systematics}:
            raise ValueError(f'{label}: name {name!r} must be unique and not nominal')
        if spec['kind'] == 'weight-factor':
            _keys(spec, ('name', 'kind'), ('replace', 'multiply', 'generator', 'sum_of_weights'), label)
            replace, multiply = spec.get('replace', {}), spec.get('multiply', [])
            if not isinstance(replace, dict) or not isinstance(multiply, list) or not (replace or multiply or 'generator' in spec):
                raise ValueError(f'{label}: give replace, multiply or generator')
            for old, new_field in replace.items():
                if old not in [e['field'] for e in weight_entries if e['kind'] == 'event-field']:
                    raise ValueError(f'{label}: {old!r} is not a weight factor of the recipe')
            for f in [*replace.values(), *multiply, *([spec['generator']] if 'generator' in spec else [])]:
                if f not in descriptor.event:
                    raise ValueError(f'{label}: {f!r} is not an event field of the format descriptor')
                if f not in event_fields:
                    event_fields.append(f)
            if 'generator' in spec and spec.get('sum_of_weights') not in ('nominal', 'varied'):
                raise ValueError(f'{label}: a replaced generator weight needs sum_of_weights nominal or varied')
        elif spec['kind'] == 'branch-variation':
            _keys(spec, ('name', 'kind', 'variation'), (), label)
            if spec['variation'] not in descriptor.variations:
                raise ValueError(f'{label}: {spec["variation"]!r} is not a variation of the format descriptor')
            variations.append(spec['variation'])
        elif spec['kind'] == 'event-weight-map':
            _keys(spec, ('name', 'kind', 'weight', 'map'), (), label)
            target = next((s for s in event_weights if s['name'] == spec['weight']), None)
            if target is None or spec['map'] not in maps:
                raise ValueError(f'{label}: unknown event weight or map')
            alternative, nominal = maps[spec['map']], maps[target['map']]
            if alternative.semantics != 'scale_factor' or alternative.axes != nominal.axes:
                raise ValueError(f'{label}: event weight alternative needs matching scale_factor axes')
        else:
            _keys(spec, ('name', 'kind', 'step', 'map'), (), label)
            if spec['step'] not in step_names or spec['map'] not in maps:
                raise ValueError(f'{label}: unknown efficiency step or map')
            target = next(s for s in steps if s.kind == 'efficiency' and s.spec['name'] == spec['step'])
            if len(maps[spec['map']].axes) != len(maps[target.spec['map']].axes):
                raise ValueError(f'{label}: the alternative map needs the same axes as the nominal map')
        systematics.append(dict(spec))

    record = doc.get('event_record')
    if record is not None:
        _keys(record, ('max_events', 'observables'), ('regions',), 'event_record')
        if type(record['max_events']) is not int or not 1 <= record['max_events'] <= MAX_RECORD:
            raise ValueError(f'event_record.max_events must be 1 to {MAX_RECORD}')
        for n in record['observables']:
            if n not in names:
                raise ValueError(f'event_record: unknown observable {n!r}')
        for r in record.get('regions', []):
            if r not in regions:
                raise ValueError(f'event_record: unknown region {r!r}')

    skim = None
    if 'skim' in doc:
        from .skim import compile_skim
        skim = compile_skim(doc['skim'], descriptor, regions, steps)

    features = None
    if 'features' in doc:
        from .features import compile_features
        features = compile_features(doc['features'], descriptor, regions, names, steps)
        event_fields += [features['event_id'], features['group_id']]

    identity = hashlib.sha256(json.dumps({'recipe': recipe_sha256, 'descriptor': descriptor.sha256,
                                          'maps': {k: m.provenance['sha256'] for k, m in sorted(maps.items())}},
                                         sort_keys=True).encode()).hexdigest()
    descriptor = descriptor.requiring({name for step in steps for expr in step.expressions.values()
                                       if hasattr(expr, 'names') for name in expr.names}
                                      | {o.spec['field'] for o in observables if o.op == 'field'}) if descriptor.format == 'root' else descriptor
    optional = {e['field'] for e in weight_entries if e.get('optional_in_files')}
    required = {e['field'] for e in weight_entries if e['kind'] == 'event-field' and not e.get('optional_in_files')}
    required.update(e['applies_when']['field'] for e in weight_entries if 'applies_when' in e)
    required.add(weights['generator'])
    for cuts in regions.values():
        for _, cut in cuts:
            if isinstance(cut, PeriodCut):
                required.add(cut.period_field)
                required.update(n for row in cut.table.values() for n in row)
    for spec in systematics:
        if spec['kind'] == 'weight-factor':
            required.update(spec.get('replace', {}).values())
            required.update(spec.get('multiply', []))
            required.add(spec.get('generator'))
    # Feature identities and model-score groups are read on every event; they are never optional.
    required.update(o.spec['group_id'] for o in observables if o.op == 'model_score')
    if features is not None:
        required.update((features['event_id'], features['group_id']))
    optional -= required
    if optional:
        descriptor = _OptionalEventDescriptor(descriptor, optional)
    return Plan(doc, InputDescriptor(descriptor), maps, steps, observables, regions, histograms, systematics, record, fields,
                list(dict.fromkeys(sources)), list(dict.fromkeys(event_fields)), variations, recipe_sha256, identity,
                card_report, spec_nodes, event_weights, weight_entries, skim, features)


def _strip_spec_items(doc):
    """A copy of the recipe without spec_item keys, and {node label: [spec item ids]}."""
    doc = json.loads(json.dumps(doc))
    nodes = {}

    def take(node, label):
        if isinstance(node, dict) and 'spec_item' in node:
            value = node.pop('spec_item')
            ids = value if isinstance(value, list) else [value]
            if not ids or any(not isinstance(v, str) or not v.strip() for v in ids):
                raise ValueError(f'{label}: spec_item is an item id or a list of item ids')
            nodes[label] = ids
        else:
            nodes[label] = []

    for i, step in enumerate(doc.get('objects') or []):
        inner = next((step[k] for k in ('overlap_removal', 'isolation', 'efficiency', 'pair_split') if isinstance(step, dict) and k in step), None)
        name = step.get('name') if isinstance(step, dict) else None
        label = f'object step {i + 1}' + (f' ({name})' if name else '')
        take(step, label)
        if inner is not None and 'spec_item' in inner:
            take(inner, label)
    for spec in doc.get('observables') or []:
        if isinstance(spec, dict):
            take(spec, f'observable {spec.get("name")}')
    for spec in doc.get('event_weights') or []:
        if isinstance(spec, dict):
            take(spec, f'event weight {spec.get("name")}')
    for region in doc.get('regions') or []:
        if isinstance(region, dict):
            for cut in region.get('cuts') or []:
                if isinstance(cut, dict):
                    take(cut, f'cut {region.get("name")} / {cut.get("name")}')
    for spec in doc.get('histograms') or []:
        if isinstance(spec, dict):
            take(spec, f'histogram {spec.get("name")}')
    return doc, nodes


def slug(name):
    out = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return out or 'histogram'


def _edges(spec, label):
    if 'edges' in spec:
        edges = spec['edges']
        if not isinstance(edges, list) or len(edges) < 2:
            raise ValueError(f'{label}: edges need at least two values')
        edges = np.array([_number(x, f'{label} edge') for x in edges])
    else:
        binning = spec
        if not isinstance(binning, dict) or len(binning) != 1 or next(iter(binning)) not in ('uniform', 'log'):
            raise ValueError(f'{label}: binning is uniform or log with low, high and bins')
        kind, b = next(iter(binning.items()))
        _keys(b, ('low', 'high', 'bins'), (), label)
        low, high = _number(b['low'], 'low'), _number(b['high'], 'high')
        if type(b['bins']) is not int or not 1 <= b['bins'] <= MAX_BINS:
            raise ValueError(f'{label}: bins must be a positive integer')
        if kind == 'log' and low <= 0:
            raise ValueError(f'{label}: log binning needs a positive low edge')
        edges = np.linspace(low, high, b['bins'] + 1) if kind == 'uniform' else np.geomspace(low, high, b['bins'] + 1)
    if not np.all(np.diff(edges) > 0):
        raise ValueError(f'{label}: edges must increase')
    if len(edges) - 1 > MAX_BINS:
        raise ValueError(f'{label}: too many bins')
    return edges


def _histogram(spec, regions, names, label):
    _keys(spec, ('name', 'region', 'observable', 'unit', 'label', 'normalization'),
          ('edges', 'binning', 'overflow', 'underflow', 'fraction_denominator', 'mc_precision_target',
           'value_unit', 'value_label', 'description', 'slice_width'), label)
    name = _text(spec['name'], f'{label} name')
    if spec['region'] not in regions:
        raise ValueError(f'{label}: unknown region {spec["region"]!r}')
    observables = spec['observable'] if isinstance(spec['observable'], list) else [spec['observable']]
    ndim = len(observables)
    if not 1 <= ndim <= 3 or any(o not in names for o in observables):
        raise ValueError(f'{label}: observable must name 1-3 declared observables')
    if ('edges' in spec) == ('binning' in spec):
        raise ValueError(f'{label}: give edges or binning')
    if ndim == 1:
        edges = [_edges(spec if 'edges' in spec else spec['binning'], label)]
        units, labels = [spec['unit']], [spec['label']]
    else:
        raw = spec['edges'] if 'edges' in spec else spec['binning']
        if not isinstance(raw, list) or len(raw) != ndim:
            raise ValueError(f'{label}: give edges or binning for each axis')
        edges = [_edges({'edges': e} if isinstance(e, list) else e, label) for e in raw]
        units, labels = spec['unit'], spec['label']
        if not isinstance(units, list) or not isinstance(labels, list) or len(units) != ndim or len(labels) != ndim:
            raise ValueError(f'{label}: give a unit and a label for each axis')
    if math.prod(len(e) - 1 for e in edges) > MAX_BINS:
        raise ValueError(f'{label}: too many bins')
    units = [_text(u, f'{label} unit (use "1" for dimensionless)') for u in units]
    labels = [natural_label(x, f'{label} label') for x in labels]
    if spec['normalization'] not in NORMALIZATIONS:
        raise ValueError(f'{label}: normalization must be one of {NORMALIZATIONS}')
    overflow, underflow = spec.get('overflow', 'separate'), spec.get('underflow', 'separate')
    if overflow not in ('separate', 'last-bin') or underflow not in ('separate', 'first-bin'):
        raise ValueError(f'{label}: overflow is separate or last-bin; underflow is separate or first-bin')
    if ndim > 1 and (overflow != 'separate' or underflow != 'separate'):
        raise ValueError(f'{label}: flow placement in an edge bin is defined for one axis only')
    if spec['normalization'] in ('density', 'yield-per-width') and (overflow != 'separate' or underflow != 'separate'):
        raise ValueError(f'{label}: a per-width normalisation cannot absorb flow into an edge bin')
    denominator = spec.get('fraction_denominator')
    if spec['normalization'] in ('fraction', 'density'):
        if denominator not in ('in-range', 'all'):
            raise ValueError(f'{label}: fraction and density need fraction_denominator in-range or all')
    elif denominator is not None:
        raise ValueError(f'{label}: fraction_denominator applies to fraction and density only')
    target = spec.get('mc_precision_target')
    if target is not None and not 0 < _number(target, f'{label} mc_precision_target') < 1:
        raise ValueError(f'{label}: mc_precision_target is a relative uncertainty between 0 and 1')
    value_unit = spec.get('value_unit')
    if value_unit is not None:
        _text(value_unit, f'{label} value_unit')
    value_label = spec.get('value_label')
    if value_label is not None:
        natural_label(value_label, f'{label} value_label')
    slice_width = None
    if 'slice_width' in spec:
        sw = spec['slice_width']
        _keys(sw, ('value', 'unit', 'variable'), (), f'{label} slice_width')
        slice_width = _number(sw['value'], f'{label} slice_width value')
        _text(sw['unit'], f'{label} slice_width unit'); _text(sw['variable'], f'{label} slice_width variable')
        if slice_width <= 0 or spec['normalization'] not in ('density', 'yield-per-width'):
            raise ValueError(f'{label}: a positive slice_width applies to density and yield-per-width histograms')
    return Histogram(name, spec['region'], observables, edges, units, labels, spec['normalization'], overflow,
                     underflow, denominator, target, value_unit, value_label, slice_width)
