"""Deterministic draft request plan (``inputs/plan.json``) from a reading and its contract.

``draft(reading, contract)`` composes a plan from the reading's deliverables, facts and
constraints, the operation signatures, the analysis catalogue and the generic plan templates
in ``data/plan_templates``. It is a proposal (status ``draft``): the host may restructure it
before CHECK-IN 1, and ``validate_request_plan.check`` decides whether it is admissible.
The draft never refuses: what no template serves becomes an open-research envelope, a held
node or a boundary row, and every obligation of the census is covered.

Reading conventions the draft reads (everything else is carried, never interpreted). The
deterministic reader's own facts are first mapped onto them (``_reader_view``): a ``supplied_file``
or ``supplied_input`` becomes a supplied input of its artifact kind, an ``identifier`` a published
locator, a ``parameter_range`` or ``parameter_values`` fact a scan axis, a ``level`` fact an event
level, an observed ``event_count`` with a ``stated_value`` a stated counts table, a deliverable's
``require.reference`` a published-figure comparison and a ``semantic-kind`` route hint that names a
literal calculation the ``literal`` feature. A host may state the conventions below directly.

- ``deliverables[]``: ``claim_kind``, ``artifact.kind`` and, in ``artifact.require``, an optional
  ``level`` (observed, expected, not_applicable), ``comparison`` ``{target, locator}`` and event
  ``level`` (parton, particle, detector, reconstructed);
- ``facts[]`` whose ``value.artifact`` names an artifact kind are inputs (``supplied`` authority:
  supplied files; ``user_quoted``: stated values; ``source_document``: located sources), with
  ``value.locator`` and ``value.require``; facts of type ``analysis``, ``publication``, ``record``,
  ``routine``, ``measurement``, ``dataset``, ``workspace`` or ``figure`` with ``value.locator`` are
  published locators; ``parameter_range``, ``scan_axis`` or ``parameter_grid`` facts are scan axes
  (``value.name``, ``value.unit``, ``value.values``); a ``literal_calculation`` fact marks arithmetic
  on stated values;
- constraints by type: ``requested_stage`` and ``negated_stage`` (``value.stage``),
  ``requested_tool`` (``value.tool``), ``prescribed_statistic`` (``value.verbatim``, else the span),
  ``source_restriction`` (``value.classes``, ``value.identifiers``, ``value.kind``), ``blinding`` and
  ``template`` (``value.locator``). Benchmark, challenge and task labels are never read.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
from pathlib import Path

from ravel.validation import validate_request_plan as rp

PLAN = 'inputs/plan.json'
READING = 'inputs/reading.json'
TEMPLATES = 'data/plan_templates'
# Constraint types that may shape a plan. The identity context is deliberately absent.
ROUTING_CONSTRAINTS = ('requested_stage', 'negated_stage', 'requested_tool', 'tool_allowlist', 'prescribed_statistic',
                       'source_restriction', 'blinding', 'template', 'keep_fixed', 'budget', 'delegation')
LOCATOR_TYPES = ('analysis', 'publication', 'record', 'routine', 'measurement', 'dataset', 'workspace', 'figure')
ROUTINE_LOCATOR_TYPES = ('analysis', 'publication', 'record', 'routine')
AXIS_TYPES = ('parameter_range', 'parameter_values', 'scan_axis', 'parameter_grid')
INPUT_AUTHORITIES = {'supplied': ('requester', 'supplied'), 'user_quoted': ('requester', 'supplied'),
                     'source_document': ('published', 'located')}
SOURCE_CLASSES = ('paper', 'hepdata', 'tables')
# The operation that serves a requested stage the chosen templates did not place.
STAGE_OPERATIONS = {'model-derivation': 'model-derivation-bridge', 'spectrum': 'simplified-spectrum',
                    'generation': 'model-events', 'lhe-transform': 'lhe-transform', 'shower': 'event-production',
                    'detector': 'event-production', 'analysis': 'columnar-analysis', 'statistic': 'search-statistics',
                    'figure': 'figure-comparison', 'output-template': 'fill-template'}
STATEMENTS = {
    'exclusion': 'Which region of the stated parameters is disfavoured against the stated null hypothesis',
    'estimate': 'The value or allowed region of the requested quantity',
    'significance': 'The test-statistic value of the stated signal hypothesis against the null hypothesis',
    'prediction': 'What the stated model predicts for the requested observable',
    'agreement': 'How the compared results relate under the declared metric and tolerance',
    'calculation': 'The value or form of the stated calculation',
    'finding': 'What the published results or literature state on the question asked',
    'method_performance': 'How the method performs on the declared data against the declared baseline',
    'document': 'The requested document, carrying the other claims of this plan',
}
AUTHOR = {'actor': 'local-proposer', 'host': None, 'model': None, 'invocation_id': None, 'fresh_context': None,
          'record': None}
EMPTY_BUDGET = {'basis': 'uncalibrated', 'max_seconds': None, 'events': None, 'disk_bytes': None, 'native_attempts': None}


# --------------------------------------------------------------------------- bytes and pins
def document_bytes(value):
    """The exact bytes RAVEL writes for an intake record (``state_io.atomic_json``)."""
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode('utf-8')


def pin(path, value):
    return {'path': path, 'sha256': hashlib.sha256(document_bytes(value)).hexdigest()}


def write(rundir, plan):
    """Write ``inputs/plan.json`` and return its run-relative pin."""
    from ravel.workflow.state_io import atomic_json
    atomic_json(Path(rundir) / PLAN, plan)
    data = (Path(rundir) / PLAN).read_bytes()
    if data != document_bytes(plan):
        raise ValueError('written request plan differs from the intended plan')
    return {'path': PLAN, 'sha256': hashlib.sha256(data).hexdigest()}


def checkin_sections(reading, plan):
    """Project the pinned draft into CHECK-IN 1 without claiming certification."""
    from ravel.validation.validate_checkin import needs_route_label
    from ravel.validation.intake_records import NOT_CERTIFIED
    flags, claims = [], []
    for claim in plan['claims']:
        row = {key: deepcopy(claim[key]) for key in ('id', 'kind', 'statement')}
        row['fidelity'] = 'Proposed claim; execution and review remain required'
        if needs_route_label(claim, plan):
            row.update(fidelity=NOT_CERTIFIED,
                       explanation='This scoped plan has no executed acceptance certificate for the declared claim and its scientific inputs.',
                       certifiable_route='Obtain an applicable source-bound acceptance comparison and independent review before claiming certified fidelity.')
            flags.append({'text': claim['id'] + ': ' + NOT_CERTIFIED + '; see claims table'})
        claims.append(row)
    for ambiguity in reading['ambiguities']:
        if ambiguity['status'] == 'open':
            flags.append({'text': ambiguity['id'] + ': ' + ambiguity['issue']})
    sections = {'plan': deepcopy(plan['nodes']), 'claims': claims,
                'coverage': deepcopy(plan['coverage']), 'ambiguities': deepcopy(reading['ambiguities'])}
    if plan['boundaries']:
        sections['boundaries'] = [{'id': identity} for identity in plan['boundaries']]
    authored = [n for n in plan['nodes'] if n['kind'] == 'authored']
    if authored:
        sections['authored'] = deepcopy(authored)
    return sections, flags


# --------------------------------------------------------------------------- templates
@lru_cache(maxsize=1)
def _template_rows():
    root = files('ravel').joinpath(TEMPLATES)
    rows = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.name.endswith('.json'):
            rows.append(json.loads(entry.read_text(encoding='utf-8')))
    return tuple(sorted(rows, key=lambda t: (t['priority'], t['id'])))


def templates():
    """The generic plan templates in proposal order."""
    return [deepcopy(t) for t in _template_rows()]


def _holds(rule, features):
    if not rule:
        return True
    if any(f not in features for f in rule.get('all', ())):
        return False
    if any(f in features for f in rule.get('none', ())):
        return False
    return all(any(f in features for f in group) for group in rule.get('any', ()))


# --------------------------------------------------------------------------- the reader's conventions
# File suffix -> (artifact kind, what the suffix states about it).
FILE_ARTIFACTS = (
    (r'\.(?:hepmc\d?|hepmc\.gz)$', 'event_sample', {'format': 'hepmc', 'level': 'particle'}),
    (r'\.lhef?(?:\.gz)?$', 'event_sample', {'format': 'lhe', 'level': 'parton'}),
    (r'\.root$', 'event_sample', {}),
    (r'\.slha$', 'parameter_point', {}),
    (r'\.(?:ya?ml|csv|tsv|yoda|txt)$', 'table', {}),
    (r'\.(?:cc|cpp|cxx)$', 'selection', {'form': 'code'}),
    (r'\.onnx$', 'selection', {'form': 'classifier'}),
    (r'\.(?:pdf|tex)$', 'document', {}),
)
# Identifier scheme -> published locator type.
IDENTIFIER_LOCATORS = {'analysis': 'analysis', 'routine': 'routine', 'arxiv': 'publication',
                       'inspire': 'publication', 'hepdata': 'record'}


def _file_artifact(fact):
    import re
    path = str(fact['value'].get('path') or fact['value'].get('text') or '')
    for pattern, kind, require in FILE_ARTIFACTS:
        if re.search(pattern, path, re.I):
            return kind, dict(require)
    return None, {}


def _grid(value):
    """The stated points of a range with a step, in the range's unit, or []."""
    step = value.get('step') if isinstance(value.get('step'), dict) else None
    low, high = value.get('low'), value.get('high')
    if step is None or not all(isinstance(x, (int, float)) for x in (low, high, step.get('value'))):
        return []
    from ravel.workflow.request_reading import _gev
    unit, low_unit, step_unit = value.get('unit'), value.get('low_unit') or value.get('unit'), step.get('unit')
    try:
        scale = lambda x, u: _gev(x, u) if u else x  # noqa: E731
        lo, hi, st = scale(low, low_unit), scale(high, unit), scale(step['value'], step_unit or unit)
    except (KeyError, TypeError, ValueError):
        return []
    if not st or st <= 0 or hi < lo or (hi - lo) / st > 512:
        return []
    out, x = [], lo
    while x <= hi * (1 + 1e-9):
        out.append(round(x / (scale(1, unit) or 1), 10))
        x += st
    return out


def _reader_view(reading):
    """Facts in the draft's conventions, derived from the deterministic reader's own fact types.

    Each derived fact keeps the id and evidence of the reader fact it comes from, so coverage,
    pins and spans still point at the reading. Facts already in the draft's conventions pass
    through unchanged.
    """
    facts = reading['facts']
    files = {}
    out = []
    for fact in facts:
        value = fact['value']
        if fact['type'] == 'publication_title':
            # Only separately resolved identifiers enter the locator/input conventions.
            continue
        if fact['type'] == 'supplied_file' and 'artifact' not in value:
            kind, require = _file_artifact(fact)
            if kind is None:
                continue
            files.setdefault(kind, []).append(fact)
            out.append(dict(fact, authority='supplied', value={
                'artifact': kind, 'locator': str(value.get('path') or value.get('text')), 'require': require}))
        elif fact['type'] == 'supplied_input' and value.get('artifact') in rp.ARTIFACT_KINDS:
            out.append(dict(fact, authority='supplied', value={
                'artifact': value['artifact'], 'locator': value.get('text'), 'require': dict(value.get('require') or {})}))
        elif fact['type'] == 'identifier' and value.get('scheme') in IDENTIFIER_LOCATORS and 'locator' not in value:
            out.append(dict(fact, type=IDENTIFIER_LOCATORS[value['scheme']],
                            value={'locator': str(value.get('id') or value.get('text'))}))
        elif fact['type'] in ('parameter_range', 'parameter_values') and not ('name' in value and 'values' in value):
            values = value.get('values') if isinstance(value.get('values'), list) else _grid(value)
            out.append(dict(fact, value={**value, 'name': value.get('name') or value.get('text') or fact['type'],
                                         'unit': value.get('unit') or '', 'values': values}))
        else:
            out.append(fact)
    # A phrase naming the same kind of artifact as a named file adds nothing new.
    out = [f for f in out if not (f['type'] == 'supplied_input' and files.get(f['value'].get('artifact')))]
    # Stated counts: an observed event count with a stated background is a counts table.
    observed = [f for f in facts if f['type'] == 'event_count' and f['value'].get('role') == 'observed']
    stated = [f for f in facts if f['type'] == 'stated_value']
    if observed and stated:
        out.append({'id': observed[0]['id'], 'type': 'stated_counts', 'authority': 'user_quoted',
                    'evidence': observed[0]['evidence'] + stated[0]['evidence'], 'witness': None,
                    'physics_critical': True,
                    'value': {'artifact': 'table', 'locator': observed[0]['value'].get('text') or 'stated counts',
                              'require': {'observed': True, 'contains_observed_data': True}}})
    if any(f['type'] == 'route_hint' and f['value'].get('operation') == 'literal-calculation' for f in facts):
        out.append({'id': 'literal', 'type': 'literal_calculation', 'authority': 'inferred', 'evidence': [],
                    'witness': None, 'physics_critical': False, 'value': {}})
    return out


# --------------------------------------------------------------------------- reading features
class _Reading:
    """The parts of a reading the draft may use, with derived features."""

    def __init__(self, reading, catalogue):
        self.doc = reading
        self.constraints = [c for c in reading['constraints'] if c['type'] in ROUTING_CONSTRAINTS]
        self.features = set()
        for row in self.constraints:
            self.features.add('constraint:' + row['type'])
            stage = row['value'].get('stage')
            if row['type'] == 'requested_stage' and stage in rp.STAGES:
                self.features.add('stage:' + stage)
            if row['type'] == 'negated_stage' and stage in rp.STAGES:
                self.features.add('negated:' + stage)
        self.negated = {c['value']['stage'] for c in self.constraints
                        if c['type'] == 'negated_stage' and c['value'].get('stage') in rp.STAGES}
        self.requested = {c['value']['stage']: c for c in self.constraints
                          if c['type'] == 'requested_stage' and c['value'].get('stage') in rp.STAGES
                          and c['value']['stage'] not in self.negated}
        if rp.withheld(reading):
            self.features.add('withheld')
        # Collider context: a beam, a collision energy or an event count, or a generation-side stage.
        if any(f['type'] in ('collision_energy', 'beams', 'event_count') for f in reading['facts']):
            self.features.add('collider')
        # Strong lexical route hints propose a template family; they never admit a route.
        for fact in reading['facts']:
            hint = fact['value'] if fact['type'] == 'route_hint' else None
            if hint and hint.get('strength') == 'strong' and hint.get('rule') not in ('semantic-kind', 'inferred-kind'):
                self.features.add('hint:' + str(hint.get('mode')))
        self.restricted = {rp._norm(t) for t, _ in rp._restricted_terms(reading)}
        self.inputs, self.locators, self.axes = {}, [], []
        self.catalogue_fact = None
        self.levels = {f['value'].get('level') for f in reading['facts'] if f['type'] == 'level'} & set(rp.EVENT_LEVELS)
        for level in self.levels:
            self.features.add('level:' + level)
        for fact in _reader_view(reading):
            value = fact['value']
            artifact = value.get('artifact')
            if artifact in rp.ARTIFACT_KINDS and fact['authority'] in INPUT_AUTHORITIES:
                self.inputs.setdefault(artifact, []).append(fact)
                self.features.add(('supplied:' if fact['authority'] == 'supplied' else 'stated:') + artifact)
                require = value.get('require') if isinstance(value.get('require'), dict) else {}
                if require.get('contains_observed_data') is True or require.get('observed') is True:
                    self.features.add('observed_data')
            locator = value.get('locator')
            if fact['type'] in LOCATOR_TYPES and type(locator) is str and locator.strip() and artifact is None:
                self.locators.append(fact)
                self.features |= {'locator:any', 'locator:' + fact['type']}
                if (self.catalogue_fact is None and fact['type'] in ROUTINE_LOCATOR_TYPES
                        and rp.preserved_routine(locator, catalogue)):
                    self.catalogue_fact = fact
                    self.features.add('catalogue:routine')
            if fact['type'] in AXIS_TYPES:
                self.axes.append(fact)
                self.features.add('fan_out')
            if fact['type'] == 'literal_calculation':
                self.features.add('literal')

    def source_classes(self):
        return [c for c in SOURCE_CLASSES if rp._norm(c) not in self.restricted]

    def selection_origin(self):
        if self.inputs.get('selection'):
            return 'requester'
        if any(f['type'] in ROUTINE_LOCATOR_TYPES for f in self.locators):
            return 'reimplemented'
        return 'designed'

    def event_format(self):
        for fact in self.inputs.get('event_sample', ()):
            require = fact['value'].get('require')
            if isinstance(require, dict) and type(require.get('format')) is str:
                return require['format']
        return None

    def deliverable_features(self, deliverable):
        require = deliverable['artifact']['require']
        rows = {'claim:' + (deliverable['claim_kind'] or 'none'), 'artifact:' + deliverable['artifact']['kind']}
        level = require.get('level')
        if level in rp.LEVELS:
            rows.add('level:' + level)
        event_level = require.get('event_level')
        if event_level in rp.EVENT_LEVELS:
            rows.add('level:' + event_level)
        target = comparison_of(deliverable)[0]
        if target != 'none':
            rows.add('compare:' + target)
        return rows


def comparison_of(deliverable):
    """(target, locator) a deliverable asks to compare with: ``require.comparison``, or a reader
    deliverable whose ``require.reference`` names a published element (a published figure)."""
    require = deliverable['artifact']['require']
    comparison = require.get('comparison')
    if isinstance(comparison, dict) and comparison.get('target') in rp.COMPARISON_TARGETS:
        locator = comparison.get('locator')
        return comparison['target'], locator if type(locator) is str and locator else None
    reference = require.get('reference')
    if type(reference) is str and reference.strip() or any(
            o.startswith('figure-comparison-') for o in deliverable['obligation_ids']):
        return 'published_figure', reference if type(reference) is str and reference.strip() else None
    return 'none', None


# --------------------------------------------------------------------------- plan builder
class _Builder:
    def __init__(self, reading, census, catalogue):
        self.r = reading
        self.census = census
        self.catalogue = catalogue
        self.nodes, self.inputs, self.edges, self.claims, self.waypoints = [], [], [], [], []
        self.groups = {}       # node id -> deliverable obligations the node serves
        self.deliverable_of = {}  # claim id -> reading deliverable

    def _next(self, rows, prefix):
        return f'{prefix}{1 + max((int(row["id"][len(prefix):]) for row in rows), default=0)}'

    # ------------------------------------------------------------ substitutions
    def _context(self, deliverable):
        fact = self.r.catalogue_fact
        return {'$selection_origin': self.r.selection_origin(), '$event_format': self.r.event_format(),
                '$catalogue_locator': fact['value']['locator'] if fact else None,
                '$catalogue_fact': fact['id'] if fact else None,
                '$locator_fact': self.r.locators[0]['id'] if self.r.locators else None,
                '$source_classes': self.r.source_classes() or None,
                '$locators': [f['value']['locator'] for f in self.r.locators
                              if rp._norm(f['value']['locator']) not in self.r.restricted],
                '$deliverable_kind': deliverable['artifact']['kind']}

    @staticmethod
    def _sub(value, context):
        if isinstance(value, str) and value.startswith('$'):
            return context.get(value)
        if isinstance(value, dict):
            return {k: _Builder._sub(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [_Builder._sub(v, context) for v in value]
        return value

    @staticmethod
    def _clean(require):
        return {k: v for k, v in require.items() if v is not None}

    # ------------------------------------------------------------ inputs
    def _bound(self, spec, context):
        kind = spec['provides']['kind']
        require = self._clean(self._sub(spec['provides']['require'], context))
        bind = spec.get('bind')
        rows = []
        if bind == 'template':
            for row in [c for c in self.r.constraints if c['type'] == 'template']:
                locator = row['value'].get('locator')
                rows.append({'provides': {'kind': kind, 'require': require}, 'source': 'requester',
                             'locator': locator if type(locator) is str and locator.strip() else row['evidence'][0]['text'],
                             'evidence': row['evidence'], 'pin': None,
                             'status': 'supplied' if type(locator) is str and locator.strip() else 'awaited'})
        elif bind:
            for fact in self.r.inputs.get(bind, ()):
                source, status = INPUT_AUTHORITIES[fact['authority']]
                declared = fact['value'].get('require') if isinstance(fact['value'].get('require'), dict) else {}
                locator = fact['value'].get('locator')
                text = fact['evidence'][0]['text'] if fact['evidence'] else spec['locator']
                rows.append({'provides': {'kind': kind, 'require': {**require, **declared}}, 'source': source,
                             'locator': locator if type(locator) is str and locator.strip() else text,
                             'evidence': fact['evidence'], 'pin': None, 'status': status})
        if not rows:
            rows.append({'provides': {'kind': kind, 'require': require}, 'source': spec['source'],
                         'locator': spec['locator'], 'evidence': [], 'pin': None, 'status': spec['status']})
        ids = []
        for row in rows:
            same = next((i for i in self.inputs if {k: v for k, v in i.items() if k != 'id'} == row), None)
            if same is None:
                same = {'id': self._next(self.inputs, 'I'), **row}
                self.inputs.append(same)
            ids.append(same['id'])
        return ids

    # ------------------------------------------------------------ templates
    def _admissible(self, template, features, context, reg):
        if not _holds(template['match'], features):
            return None
        nodes = [n for n in template['nodes'] if _holds(n.get('when'), features)]
        keys = {n['key'] for n in nodes}
        for node in nodes:
            operation = node['operation']
            # A template needing an operation this tree does not register is not proposed.
            if operation and operation not in reg:
                return None
            signature = reg.get(operation) if operation else None
            if signature and set(signature['stages']) & self.r.negated:
                return None
            for field in node.get('fields', ()):
                if self._sub(field['value'], context) in (None, []) and field['pointer'] != '/locators':
                    return None
        options = [d for d in template['deliverable'] if _holds(d.get('when'), features)
                   and d['from'].split('.')[0] in keys]
        if not options:
            return None
        return nodes, keys, options

    def instantiate(self, template, deliverable, features, reg):
        context = self._context(deliverable)
        admitted = self._admissible(template, features, context, reg)
        if admitted is None:
            return None
        nodes, keys, options = admitted
        wanted = deliverable['artifact']['kind']
        option = next((d for d in options if self._sub(d['kind'], context) == wanted), options[0])
        ids = {}
        fan = template.get('fan_out') if 'fan_out' in features else None
        for spec in nodes:
            node = self._node(spec, context, reg, fan)
            # One chain serves every deliverable that needs the same operation with the same fields.
            reuse = next((n for n in self.nodes if n['kind'] == node['kind'] and n['operation'] == node['operation']
                          and n['fields'] == node['fields'] and n['status'] == 'available'
                          and node['operation'] is not None), None)
            if reuse is None:
                node['id'] = self._next(self.nodes, 'N')
                self.nodes.append(node)
                reuse = node
            ids[spec['key']] = reuse['id']
            self.groups.setdefault(reuse['id'], set()).update(deliverable['obligation_ids'])
        if fan:
            members = [ids[k] for k in fan['subgraph'] if k in ids]
            if members:
                first = next(n for n in self.nodes if n['id'] == members[0])
                first['fan_out'] = {'axes': self._axes(), 'subgraph': members, 'aggregate': fan['aggregate']}
                for node in self.nodes:
                    if node['id'] in members and node['rung'] != 'none':
                        node['rung'] = 'scan'
        inputs = {spec['key']: self._bound(spec, context) for spec in template['inputs']}
        for spec in template['edges']:
            if not _holds(spec.get('when'), features):
                continue
            source, target = spec['from'], spec['to']
            target_key, target_slot = target.split('.', 1)
            if target_key not in ids:
                continue
            require = self._clean(self._sub(spec['require'], context))
            if source.startswith('input:'):
                for ref in inputs[source[6:]]:
                    self._edge(ref, 'provided', ids[target_key], target_slot, spec['kind'], require)
            else:
                source_key, source_slot = source.split('.', 1)
                if source_key in ids:
                    self._edge(ids[source_key], source_slot, ids[target_key], target_slot, spec['kind'], require)
        producer_key, producer_slot = option['from'].split('.', 1)
        claim_edges = [(ids[e['from'].split('.')[0]], e['from'].split('.', 1)[1], e['slot'], e['kind'])
                       for e in template.get('claim_edges', ()) if e['from'].split('.')[0] in ids]
        return ids[producer_key], producer_slot, self._sub(option['kind'], context), claim_edges

    def _axes(self):
        rows = []
        for fact in self.r.axes:
            value = fact['value']
            rows.append({'name': str(value.get('name') or value.get('parameter') or fact['type']),
                         'unit': str(value.get('unit') or ''),
                         'values': value['values'] if isinstance(value.get('values'), list) else [],
                         'fact': fact['id']})
        return rows or [{'name': 'parameter', 'unit': '', 'values': [], 'fact': None}]

    def _node(self, spec, context, reg, fan):
        operation = spec['operation']
        signature = reg.get(operation) if operation else None
        implementation = spec.get('implementation') or (signature['implementation']['kind'] if signature else 'science-mode')
        fields = []
        for field in spec.get('fields', ()):
            value = self._sub(field['value'], context)
            evidence = self._sub(field['evidence'], context) if field['evidence'] else None
            if value in (None, []):
                continue
            fields.append({'pointer': field['pointer'], 'value': value, 'authority': field['authority'],
                           'evidence': evidence})
        authored = deepcopy(spec.get('authored'))
        if authored is not None:
            authored.setdefault('specification', None)
        return {'id': None, 'kind': spec['kind'], 'operation': operation, 'implementation': implementation,
                'status': 'available', 'held_by': None, 'covers': [], 'fields': fields, 'rung': spec['rung'],
                'budget': dict(EMPTY_BUDGET), 'placement': {'backend_plan': None}, 'fan_out': None,
                'spec_template': None, 'review': {'claim_scope': 'pending', 'actions': ['delivery']},
                'authored': authored, 'request': None}

    def _edge(self, source, source_slot, target, target_slot, kind, require):
        row = {'from': {'ref': source, 'slot': source_slot}, 'to': {'ref': target, 'slot': target_slot}, 'kind': kind,
               'require': require, 'resolution': 'compatible', 'converter': None, 'acceptance': 'accepted_review'}
        if any({k: v for k, v in e.items() if k != 'id'} == row for e in self.edges):
            return
        self.edges.append({'id': self._next(self.edges, 'E'), **row})

    # ------------------------------------------------------------ claims
    def claim(self, deliverable, producer, slot, kind, claim_edges):
        cid = self._next(self.claims, 'C')
        self.deliverable_of[cid] = deliverable
        obligations = [o for o in deliverable['obligation_ids'] if o in self.census] or ['original-request']
        claim_kind = deliverable['claim_kind']
        target, locator = comparison_of(deliverable)
        self.claims.append({
            'id': cid, 'kind': claim_kind, 'statement': f'{STATEMENTS[claim_kind]} ({deliverable["id"]}).',
            'obligation_ids': obligations, 'deliverable': {'artifact': kind, 'template': None},
            'level': 'not_applicable', 'statistic': self._statistic(claim_kind, deliverable),
            'comparison': {'target': target, 'locator': locator, 'metric': None, 'tolerance': None},
            'conventions': {'basis_conversion': False}, 'basis_declared': [], 'inherits': []})
        self._edge(producer, slot, cid, 'deliverable', kind, {})
        for source, source_slot, claim_slot, edge_kind in claim_edges:
            self._edge(source, source_slot, cid, claim_slot, edge_kind, {})
        if target == 'published_figure':
            self._figure(cid, producer, slot, kind, locator, deliverable)
        return cid

    def _figure(self, cid, producer, slot, kind, locator, deliverable):
        """A published-figure comparison: digitise the published figure and compare the produced artifact."""
        if 'figures' in self.r.restricted:
            return
        figure_locator = locator or 'published figure named in the request'
        # One figure-comparison node per published figure: a second claim on the same figure reuses it.
        node = next((n for n in self.nodes if n['operation'] == 'figure-comparison' and n['status'] == 'available'
                     and any(e['to']['ref'] == n['id'] and e['to']['slot'] == 'published'
                             and any(i['id'] == e['from']['ref'] and i['locator'] == figure_locator for i in self.inputs)
                             for e in self.edges)), None)
        if node is None:
            node = self._node({'key': 'compare', 'kind': 'operation', 'operation': 'figure-comparison', 'rung': 'full'},
                              {}, rp.registry(), None)
            node['id'] = self._next(self.nodes, 'N')
            self.nodes.append(node)
        self.groups.setdefault(node['id'], set()).update(deliverable['obligation_ids'])
        figure = self._bound({'provides': {'kind': 'figure', 'require': {'reference': 'published'}}, 'source': 'published',
                              'locator': locator or 'published figure named in the request', 'status': 'awaited'}, {})
        for ref in figure:
            self._edge(ref, 'provided', node['id'], 'published', 'figure', {'reference': 'published'})
        if kind in ('binned_values', 'inference'):
            self._edge(producer, slot, node['id'], 'result' if kind == 'binned_values' else 'inference', kind, {})
        self._edge(node['id'], 'comparison', cid, 'comparison', 'figure', {})

    def _statistic(self, kind, deliverable):
        prescriptions = [c for c in self.r.constraints if c['type'] == 'prescribed_statistic']
        # A prescription whose construction the request fixes (a stated formula) is the primary one.
        prescriptions.sort(key=lambda c: c['value'].get('construction_fixed') is not True)
        if kind in rp.STATISTIC_KINDS and prescriptions:
            return {'source': 'prescribed', 'definition': rp._prescription(prescriptions[0]),
                    'evidence': prescriptions[0]['evidence'], 'secondary': []}
        if kind in rp.STATISTIC_KINDS:
            definition = rp.POLICY_DEFAULTS[kind]
            if kind == 'significance' and deliverable['artifact']['require'].get('level') == 'expected':
                definition = rp.EXPECTED_SIGNIFICANCE_DEFAULT
            return {'source': 'policy_default', 'definition': definition, 'evidence': [], 'secondary': []}
        if kind == 'agreement':
            return {'source': 'declared', 'definition': None, 'evidence': [], 'secondary': []}
        return {'source': 'not_applicable', 'definition': None, 'evidence': [], 'secondary': []}

    # ------------------------------------------------------------ holds and stage nodes
    def held(self, operation, held_by, request, obligations, tool=None, constraint=None, reg=None):
        signature = reg.get(operation) if operation else None
        kind = 'operation' if signature else 'authored'
        node = self._node({'key': 'held', 'kind': kind, 'operation': operation if signature else None,
                           'implementation': None if signature else 'source-development',
                           'rung': 'full'}, {}, reg, None)
        if kind == 'authored':
            node['authored'] = {'purpose': request, 'signature': {}, 'specification': None,
                                'known_answer_tests': ['declared with the development request'], 'attempt_budget': 0}
        node.update(id=self._next(self.nodes, 'N'), status='held', held_by=held_by, request=request)
        if tool is not None:
            node['fields'].append({'pointer': '/tool', 'value': tool, 'authority': 'user_quoted', 'evidence': constraint})
        self.nodes.append(node)
        self.groups.setdefault(node['id'], set()).update(obligations)
        return node


def _overlaps(a, b):
    return any(x['start'] < y['end'] and y['start'] < x['end'] for x in a for y in b)


def _census(reading, contract):
    obligations = ((contract or {}).get('task_requirements') or {}).get('obligations')
    if obligations:
        return obligations
    rows = [{'id': 'original-request', 'kind': 'whole_request', 'evidence': [], 'criteria': {}}]
    for key in ('deliverables', 'boundaries'):
        for row in reading[key]:
            for oid in row['obligation_ids']:
                if all(r['id'] != oid for r in rows):
                    rows.append({'id': oid, 'kind': 'deliverable' if key == 'deliverables' else 'coverage',
                                 'evidence': [], 'criteria': {}})
    return rows


# --------------------------------------------------------------------------- draft
def draft(reading, contract, *, catalogue=None):
    """A deterministic draft plan for ``reading`` (§2.5.1) under ``contract`` (a v1 task contract or its
    ``task_requirements``). ``catalogue(locator) -> bool`` overrides the analysis-catalogue lookup.
    """
    errors = rp.reading_schema_errors(reading)
    if errors:
        raise ValueError('the reading does not match the request-reading schema: ' + '; '.join(errors[:5]))
    prompt = (contract or {}).get('prompt')
    if type(prompt) is str and hashlib.sha256(prompt.encode()).hexdigest() != reading['prompt_sha256']:
        raise ValueError('the reading and the contract bind different prompts')
    reg = rp.registry()
    view = _Reading(reading, catalogue)
    obligations = _census(reading, contract)
    census = [o['id'] for o in obligations]
    b = _Builder(view, census, catalogue)
    boundaries = reading['boundaries']
    whole = [x for x in boundaries if x['class'] in rp.WHOLE_REQUEST_BOUNDARIES
             or (x['class'] == 'inaccessible_input' and x['obligation_ids'] == ['original-request'])]
    bounded = {o for x in boundaries for o in x['obligation_ids']}
    if whole:
        node = b.held(None, whole[0]['id'], whole[0]['would_make_possible'], ['original-request'], reg=reg)
        node.update(kind='envelope', implementation='research-coordinator', rung='none', authored=None)
    else:
        # Question form is an explicit reading fact, independent of template priority.
        # Keep concrete proposed children alongside the whole-question coordinator.
        if any(f['type'] == 'question_form' for f in reading['facts']):
            envelope = b._node({'kind': 'envelope', 'operation': None,
                                'implementation': 'research-coordinator', 'rung': 'none'}, {}, reg, None)
            envelope['id'] = b._next(b.nodes, 'N')
            b.nodes.append(envelope)
            b.groups[envelope['id']] = {'original-request'}
        for deliverable in reading['deliverables']:
            if deliverable['obligation_ids'] and set(deliverable['obligation_ids']) <= bounded:
                continue
            features = view.features | view.deliverable_features(deliverable)
            for template in templates():
                made = b.instantiate(template, deliverable, features, reg)
                if made is not None:
                    break
            producer, slot, kind, claim_edges = made
            if deliverable['claim_kind'] is not None:
                b.claim(deliverable, producer, slot, kind, claim_edges)
        _tool_pins(b, view, reg, obligations)
        _stage_nodes(b, view, reg, obligations)
        if not b.nodes:
            node = b._node({'key': 'envelope', 'kind': 'envelope', 'operation': None,
                            'implementation': 'research-coordinator', 'rung': 'none'}, {}, reg, None)
            node['id'] = b._next(b.nodes, 'N')
            non_whole = [o for o in census if o != 'original-request']
            if boundaries and non_whole and set(non_whole) <= bounded:
                node.update(status='held', held_by=boundaries[0]['id'], request=boundaries[0]['would_make_possible'])
            b.nodes.append(node)
            b.groups[node['id']] = set()
    for claim in b.claims:
        if claim['kind'] == 'document':
            claim['inherits'] = [c['id'] for c in b.claims if c['kind'] != 'document']
    return _assemble(reading, b, reg, obligations, view, catalogue)


def _tool_candidates(b, view, reg, tool, stages, node=None):
    """Signed operations running the tool, with compatible outgoing artifact kinds.

    Inputs can be requested during drafting; output kinds cannot be invented. Prefer
    the narrowest operation and preserve existing port names when possible.
    """
    outgoing = [e for e in b.edges if node and e['from']['ref'] == node['id']]
    candidates = []
    for name, signature in reg.items():
        if not signature or rp._norm(tool) not in {rp._norm(t) for t in signature['tools']}:
            continue
        declared = set(signature['stages'])
        if (stages and not stages <= declared) or declared & view.negated:
            continue
        if any(not any(p['kind'] == e['kind'] for p in signature['produces']) for e in outgoing):
            continue
        candidates.append(name)
    return sorted(candidates, key=lambda name: (tool not in reg[name]['tools'], len(set(reg[name]['stages']) - stages),
                                               len(reg[name]['consumes']), name))


def _tool_node(b, view, reg, operation, node=None):
    """Substitute a signed producer, retaining typed dependencies and awaiting missing inputs."""
    signature = reg[operation]
    if node is None:
        node = b._node({'kind': 'operation', 'operation': operation,
                        'rung': 'full' if signature['effects'] else 'none'}, {}, reg, None)
        node['id'] = b._next(b.nodes, 'N')
        b.nodes.append(node)
    else:
        node.update(operation=operation, implementation=signature['implementation']['kind'],
                    kind='operation', authored=None)
    incoming = [e for e in b.edges if e['to']['ref'] == node['id']]
    b.edges[:] = [e for e in b.edges if e not in incoming]
    for edge in b.edges:
        if edge['from']['ref'] == node['id']:
            outputs = [p for p in signature['produces'] if p['kind'] == edge['kind']]
            port = next((p for p in outputs if p['slot'] == edge['from']['slot']), outputs[0])
            edge['from']['slot'] = port['slot']
    used = set()
    for port in signature['consumes']:
        matches = [e for e in incoming if e['id'] not in used and e['kind'] == port['kind']
                   and rp._require_ok(e['require'], port.get('require', {}))]
        match = next((e for e in matches if e['to']['slot'] == port['slot']), next(iter(matches), None))
        if match:
            used.add(match['id'])
            b._edge(match['from']['ref'], match['from']['slot'], node['id'], port['slot'],
                    port['kind'], match['require'])
        elif not port.get('optional'):
            # A quantity requirement is not a supplied fact; the awaited input leaves it as an obligation.
            require = {k: v for k, v in port.get('require', {}).items() if k != 'quantity'}
            refs = b._bound({'provides': {'kind': port['kind'], 'require': require},
                             'source': 'requester', 'status': 'awaited',
                             'locator': f'{operation} {port["slot"]} input', 'bind': port['kind']}, {})
            for ref in refs:
                b._edge(ref, 'provided', node['id'], port['slot'], port['kind'], require)
    return node


def _tool_pins(b, view, reg, obligations):
    """Pin each requested tool on the nodes that run it; hold the stage it names when no operation runs it."""
    for row in [c for c in view.constraints if c['type'] == 'requested_tool']:
        tool = row['value'].get('tool') or row['evidence'][0]['text']
        serves = lambda n: n.get('operation') and reg.get(n['operation']) and rp._norm(tool) in {
            rp._norm(t) for t in reg[n['operation']]['tools']}
        served = [n for n in b.nodes if n['status'] == 'available' and serves(n)]
        stages = rp.tool_stages(view.doc, row)
        # Replace other producers of that stage with a signed, tool-satisfying operation.
        substituted = [n for n in b.nodes if n['status'] == 'available' and n not in served
                       and rp._stages(n, reg) & stages]
        for node in substituted:
            candidates = _tool_candidates(b, view, reg, tool, rp._stages(node, reg) & stages, node)
            # A second requested tool on the same node remains a constraint.
            pinned = [f['value'] for f in node['fields'] if f['pointer'] == '/tool']
            candidates = [name for name in candidates if all(rp._norm(t) in {
                rp._norm(v) for v in reg[name]['tools']} for t in pinned)]
            if candidates:
                served.append(_tool_node(b, view, reg, candidates[0], node))
                continue
            alternatives = _tool_candidates(b, view, reg, tool, rp._stages(node, reg) & stages)
            if alternatives:
                # The tool runs this stage, but its output cannot replace this producer.
                # Draft it, and keep an explicit held bridge for the original deliverable.
                operation = alternatives[0]
                producer = next((n for n in served if n['operation'] == operation), None)
                if producer is None:
                    producer = _tool_node(b, view, reg, operation)
                    served.append(producer)
                previous = reg[node['operation']]
                request = f'compose {operation} outputs into the requested artifacts without substituting their kinds'
                node.update(kind='authored', operation=None, implementation='source-development',
                            status='held', held_by='plan-composition', request=request,
                            authored={'purpose': request, 'signature': {'produces': deepcopy(previous['produces'])},
                                      'specification': None, 'known_answer_tests': ['preserve requested output kinds'],
                                      'attempt_budget': 0})
                if reg[operation]['produces']:
                    port = reg[operation]['produces'][0]
                    b._edge(producer['id'], port['slot'], node['id'], 'tool_output', port['kind'], {})
                continue
            node.update(status='held', held_by='source-development',
                        request=f'run {", ".join(sorted(rp._stages(node, reg) & stages))} with the requested tool {tool}, '
                                'which no registered operation runs')
            node['fields'].append({'pointer': '/tool', 'value': tool, 'authority': 'user_quoted', 'evidence': row['id']})
        if not served and not substituted:
            candidates = _tool_candidates(b, view, reg, tool, stages)
            if candidates:
                served.append(_tool_node(b, view, reg, candidates[0]))
        for node in served:
            node['fields'].append({'pointer': '/tool', 'value': tool, 'authority': 'user_quoted', 'evidence': row['id']})
            b.groups.setdefault(node['id'], set()).update(_matching(obligations, row['evidence'], row['id']))
        if served or substituted:
            continue
        matched = _matching(obligations, row['evidence'], row['id']) or ['original-request']
        b.held(None, 'source-development', f'integrate the requested tool {tool} as a governed operation', matched,
               tool=tool, constraint=row['id'], reg=reg)


def _stage_nodes(b, view, reg, obligations):
    for stage, row in view.requested.items():
        if any(stage in rp._stages(n, reg) for n in b.nodes):
            continue
        operation = STAGE_OPERATIONS[stage]
        matched = _matching(obligations, row['evidence'], row['id']) or ['original-request']
        if set(reg[operation]['stages']) & view.negated:
            b.held(None, 'source-development', f'run the requested {stage} stage without the stages the request '
                   f'excludes ({", ".join(sorted(view.negated))}); no registered operation separates them', matched,
                   reg=reg)
            continue
        b.held(operation, 'plan-composition', f'compose the requested {stage} stage into the plan before CHECK-IN 1',
               matched, reg=reg)


def _matching(obligations, evidence, reading_id):
    rows = []
    for obligation in obligations:
        if obligation['id'] == 'original-request':
            continue
        criteria = json.dumps(obligation.get('criteria', {}), sort_keys=True)
        if f'"{reading_id}"' in criteria or _overlaps(obligation.get('evidence', []), evidence):
            rows.append(obligation['id'])
    return rows


def _coverage(reading, b, obligations, view):
    """Obligation id -> covering ids (claims, nodes, inputs, ambiguity rows, boundaries)."""
    by = {o['id']: [] for o in obligations}
    claims_for = {}
    for claim in b.claims:
        for oid in claim['obligation_ids']:
            claims_for.setdefault(oid, []).append(claim['id'])
    for node in b.nodes:
        for oid in sorted(b.groups.get(node['id'], ())):
            if oid in by:
                by[oid].append(node['id'])
    for boundary in reading['boundaries']:
        for oid in boundary['obligation_ids']:
            if oid in by:
                by[oid].append(boundary['id'])
    for row in reading['ambiguities']:
        for oid in row['blocks']:
            if oid in by:
                by[oid].append(row['id'])
    for oid, ids in claims_for.items():
        if oid in by:
            by[oid] = ids + by[oid]
    # A range obligation is served by the nodes that fan out over its fact.
    for node in b.nodes:
        for axis in (node['fan_out'] or {}).get('axes', ()):
            oid = 'range-' + str(axis.get('fact'))
            if oid in by and node['id'] not in by[oid]:
                by[oid].append(node['id'])
    spanned = [(c, c['evidence']) for c in view.constraints] + [(f, f['evidence']) for f in reading['facts']]
    for obligation in obligations:
        oid = obligation['id']
        if oid == 'original-request' or 'output_contract' in obligation.get('criteria', {}):
            # A declared output path constrains how the whole result is delivered.
            by[oid] = [c['id'] for c in b.claims] + [n['id'] for n in b.nodes] + [
                x['id'] for x in reading['boundaries'] if x['class'] in rp.WHOLE_REQUEST_BOUNDARIES]
            continue
        if by[oid]:
            continue
        for item, evidence in spanned:
            if _overlaps(obligation.get('evidence', []), evidence) or f'"{item["id"]}"' in json.dumps(
                    obligation.get('criteria', {}), sort_keys=True):
                by[oid] += _served_by(item, b)
        if not by[oid]:
            by[oid] = [c['id'] for c in b.claims] or [n['id'] for n in b.nodes if n['kind'] == 'envelope']
    return by


def _served_by(item, b):
    stage = item.get('value', {}).get('stage') if item.get('type') == 'requested_stage' else None
    ids = []
    for node in b.nodes:
        signature = rp.registry().get(node['operation']) if node.get('operation') else None  # cached
        if stage and signature and stage in signature['stages']:
            ids.append(node['id'])
        elif any(f.get('evidence') == item['id'] for f in node['fields']):
            ids.append(node['id'])
        elif item.get('type') == 'template' and node.get('operation') == 'fill-template':
            ids.append(node['id'])
    return ids or [c['id'] for c in b.claims]


def _validation_inputs(builder, registry):
    """Retain required validation evidence as awaited owner actions in every drafted chain."""
    for node in builder.nodes:
        signature = registry.get(node.get('operation'))
        if not signature or node['status'] != 'available':
            continue
        for port in signature['consumes']:
            if (port.get('optional') or not port['kind'].startswith('validation:')
                    or any(edge['to'] == {'ref': node['id'], 'slot': port['slot']} for edge in builder.edges)):
                continue
            require = deepcopy(port.get('require', {}))
            refs = builder._bound({'provides': {'kind': port['kind'], 'require': require},
                                   'source': 'owner_action', 'status': 'awaited',
                                   'locator': f'{node["operation"]} {port["slot"]} validation evidence'}, {})
            for ref in refs:
                builder._edge(ref, 'provided', node['id'], port['slot'], port['kind'], require)


def _assemble(reading, b, reg, obligations, view, catalogue):
    _validation_inputs(b, reg)
    by = _coverage(reading, b, obligations, view)
    if any(not ids for ids in by.values()):
        envelope = next((n for n in b.nodes if n['kind'] == 'envelope'), None)
        if envelope is None:
            envelope = b._node({'key': 'envelope', 'kind': 'envelope', 'operation': None,
                                'implementation': 'research-coordinator', 'rung': 'none'}, {}, reg, None)
            envelope['id'] = b._next(b.nodes, 'N')
            b.nodes.append(envelope)
        for oid, ids in by.items():
            if not ids:
                ids.append(envelope['id'])
        by['original-request'] = list(dict.fromkeys(by.get('original-request', []) + [envelope['id']]))
    for oid in by:
        by[oid] = list(dict.fromkeys(by[oid]))[:32]
    for node in b.nodes:
        node['covers'] = [o['id'] for o in obligations if node['id'] in by[o['id']]][:64]
        if not node['covers']:
            node['covers'] = ['original-request']
            by['original-request'].append(node['id'])
    plan = {
        'schema_version': 1, 'kind': 'request-plan', 'prompt_sha256': reading['prompt_sha256'],
        'reading': pin(READING, reading), 'signatures': {'path': 'ravel/' + rp.SIGNATURES, 'entries': {}},
        'status': 'draft', 'authors': [dict(AUTHOR)], 'inputs': b.inputs, 'nodes': b.nodes, 'edges': b.edges,
        'claims': b.claims, 'waypoints': [], 'boundaries': [x['id'] for x in reading['boundaries']],
        'coverage': [{'obligation_id': o['id'], 'by': by[o['id']]} for o in obligations if by[o['id']]],
        'aggregate_budget': {k: None for k in ('wall_seconds', 'native_attempts', 'events', 'disk_bytes', 'calls',
                                               'output_tokens')},
        'label': {'task_mode': 'research', 'rule': 'D5', 'floor_row': 'research'}}
    bases = rp.computed_bases(plan, reg)
    for claim in plan['claims']:
        rows = bases[claim['id']]
        claim['basis_declared'] = sorted({r['element'] for r in rows}, key=rp.BASES.index)
        claim['level'] = _level(claim, rows, b.deliverable_of[claim['id']])
        if claim['kind'] == 'significance' and claim['level'] == 'expected' and claim['statistic']['source'] == 'policy_default':
            claim['statistic']['definition'] = rp.EXPECTED_SIGNIFICANCE_DEFAULT
    _waypoints(plan, reg)
    _review(plan)
    plan['signatures']['entries'] = {n['operation']: rp.entry_sha256(reg[n['operation']])
                                     for n in sorted(plan['nodes'], key=lambda n: n['operation'] or '')
                                     if n.get('operation') and reg.get(n['operation'])}
    plan['label'] = provisional_label(reading, plan, reg, census=[o['id'] for o in obligations], catalogue=catalogue)
    # The label a plan records is the derived label of its reading and plan (derived_label is the
    # one label authority); the provisional rules above are what it reads off the plan's structure.
    from ravel.workflow import derived_label
    plan['label'] = derived_label.plan_label(reading, plan, catalogue=catalogue)
    return plan


def _level(claim, rows, deliverable):
    level = deliverable['artifact']['require'].get('level')
    if level in rp.LEVELS:
        return level
    if claim['kind'] not in rp.STATISTIC_KINDS:
        return 'not_applicable'
    elements = {r['element'] for r in rows}
    return 'observed' if elements & {'observed_data', 'published_results'} else 'expected'


def _waypoints(plan, reg):
    consumers = {}
    for edge in plan['edges']:
        consumers.setdefault(edge['from']['ref'], []).append(edge['to']['ref'])
    nodes = {n['id'] for n in plan['nodes']}
    for node in plan['nodes']:
        if node['status'] != 'available':
            continue
        if node['kind'] == 'authored':
            before = sorted({c for c in consumers.get(node['id'], ()) if c in nodes})
            if before:
                plan['waypoints'].append({'id': f'WP{len(plan["waypoints"]) + 1}', 'kind': 'known_answer',
                                          'after': node['id'], 'before': before,
                                          'criterion': f'the known-answer tests of {node["id"]} pass before any consumer runs',
                                          'check': 'known_answer_tests', 'on_false': 'stop'})
        if node['rung'] in rp.BULK_RUNGS:
            plan['waypoints'].append({'id': f'WP{len(plan["waypoints"]) + 1}', 'kind': 'smoke_review',
                                      'after': node['id'], 'before': [node['id']],
                                      'criterion': f'CHECK-IN 2 GO on the smoke rung of {node["id"]} before its bulk rung',
                                      'check': None, 'on_false': 'stop'})


def _review(plan):
    claims = {c['id'] for c in plan['claims']}
    waypointed = {w['after'] for w in plan['waypoints']}
    reused = {e['from']['ref'] for e in plan['edges'] if e['to']['ref'] not in claims}
    for node in plan['nodes']:
        fed = sorted(c for c in claims if node['id'] in rp.ancestors(plan, c))
        node['review'] = {'claim_scope': fed[0] if fed else node['id'],
                          'actions': ['delivery'] + (['bulk'] if node['id'] in waypointed else [])
                                     + (['reuse'] if node['id'] in reused else [])}


# --------------------------------------------------------------------------- derived label (provisional)
def provisional_label(reading, plan, reg=None, *, census=None, catalogue=None):
    """The D1-D5 compatibility label and floor row of §4.3 and §2.8.3 for a plan.

    ``derived_label.derive`` (S1-04) is the authority; this is the same rule set, so a draft
    carries a consistent label until intake replaces it.
    """
    reg = rp.registry() if reg is None else reg
    census = rp.census_ids(reading) if census is None else census
    floor = floor_row(reading, plan, reg, census=census)
    nodes = plan['nodes']
    if floor == 'unsupported':
        return {'task_mode': 'unsupported', 'rule': 'D1', 'floor_row': floor}
    requested = {c['value'].get('stage') for c in reading['constraints'] if c['type'] == 'requested_stage'}
    negated = {c['value'].get('stage') for c in reading['constraints'] if c['type'] == 'negated_stage'}
    requested -= negated
    if len(nodes) == 1 and nodes[0]['status'] == 'available':
        node = nodes[0]
        if node['implementation'] == 'scoped-adapter' and requested <= rp._stages(node, reg):
            return {'task_mode': node['operation'], 'rule': 'D2', 'floor_row': floor}
        if node['implementation'] == 'lifecycle-stage' and plan['claims'] and all(
                rp.route_a_available(plan, c['id'], reg, catalogue) for c in plan['claims']):
            shape = floor if floor in ('scan', 'reproduce', 'reinterpret', 'projection') else 'reinterpret'
            return {'task_mode': shape, 'rule': 'D3', 'floor_row': floor}
    if (plan['claims'] and all(c['kind'] == 'calculation' for c in plan['claims'])
            and all(n['kind'] == 'operation' and n['implementation'] == 'science-mode' for n in nodes)):
        return {'task_mode': 'calculation', 'rule': 'D4', 'floor_row': floor}
    return {'task_mode': 'research', 'rule': 'D5', 'floor_row': floor}


def floor_row(reading, plan, reg=None, *, census=None):
    """The first matching floor row of §2.8.3."""
    reg = rp.registry() if reg is None else reg
    census = rp.census_ids(reading) if census is None else census
    boundaries = reading['boundaries']
    bounded = {o for x in boundaries for o in x['obligation_ids']}
    non_whole = [o for o in census if o != 'original-request']
    if any(x['class'] in rp.WHOLE_REQUEST_BOUNDARIES for x in boundaries) or (non_whole and set(non_whole) <= bounded):
        return 'unsupported'
    nodes = plan['nodes']
    requested = {c['value'].get('stage') for c in reading['constraints'] if c['type'] == 'requested_stage'}
    if (len(nodes) == 1 and nodes[0]['implementation'] == 'scoped-adapter'
            and requested <= rp._stages(nodes[0], reg)):
        return nodes[0]['operation']
    bases = rp.computed_bases(plan, reg)

    def selected(cid):
        return any(r['element'] == 'simulated_acceptance' and r.get('origin') in ('published', 'reimplemented')
                   for r in bases[cid])
    claims = plan['claims']
    fan = any(n['fan_out'] for n in nodes)
    generating = any('generates_events' in rp._effects(n, reg) for n in nodes)
    if fan and any(c['kind'] in ('exclusion', 'estimate') and selected(c['id']) for c in claims):
        return 'scan'
    if any(c['comparison']['target'] == 'published_figure' and selected(c['id']) for c in claims):
        return 'reproduce'
    if any(c['kind'] == 'exclusion' and selected(c['id']) for c in claims):
        return 'reinterpret'
    if generating and any(c['level'] == 'expected' and selected(c['id']) for c in claims):
        return 'projection'
    if any(c['kind'] == 'finding' and c['deliverable']['artifact'] == 'figure' for c in claims):
        return 'summary_plot'
    analysing = any(n['kind'] == 'operation' and reg.get(n['operation'])
                    and any(s['kind'] == 'event_sample' for s in reg[n['operation']]['consumes'])
                    and any(s['kind'] in ('binned_values', 'cutflow') for s in reg[n['operation']]['produces'])
                    for n in nodes)
    plain = {'published_results', 'analytic'}
    if claims and not generating and not analysing and all({r['element'] for r in bases[c['id']]} <= plain for c in claims):
        return 'survey' if all(c['kind'] in ('finding', 'agreement') for c in claims) else 'calculation'
    if any(c['kind'] == 'method_performance' for c in claims):
        return 'method_study'
    if claims and all(c['kind'] == 'document' for c in claims):
        return 'manuscript'
    return 'research'
