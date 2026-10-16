"""Plan check for a request plan (``inputs/plan.json``): vocabularies, schemas and typed errors.

A request plan is a directed acyclic graph of registered operations, authored steps,
inputs and open-research envelopes, joined by typed artifact edges, with the claims each
deliverable will make. This module holds the closed vocabularies of the intake
architecture, the reading and plan schemas (written only in the JSON Schema keywords
``validate_task_contract._schema_errors`` evaluates), and ``check``, which returns the plan
errors that do not need full operation signatures. Every error uses the refusal envelope
``{error_class, reason, action_required, suggested_next_operation, evidence_ids}``.

Stage 1 shows and pins the plan; it does not govern. Nothing here approves compute, and
nothing here reads the request's identity context (benchmark, challenge or task labels).
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import re
import sys

from ravel.validation.validate_task_contract import TASK_MODES, _schema_errors

# --------------------------------------------------------------------------- vocabularies
# The closed vocabularies and the reading and plan schemas are stated once, in
# ravel.validation.intake_records; this module adds the plan check's own tables.
from ravel.validation.intake_records import (  # noqa: E402,F401
    ANALYTIC_FROM, ARTIFACT_KIND as KIND, ARTIFACT_KINDS, AUTHOR_ACTORS, AUTHORED_IMPLEMENTATIONS, BASES,
    BOUNDARY_CLASSES, BUDGET_BASES, CLAIM_KINDS, COMPARISON_TARGETS, CONSTRAINT_TYPES, DISMISSALS, EDGE_ACCEPTANCE,
    EDGE_RESOLUTIONS, EFFECTS, EVENT_LEVELS, FACT_AUTHORITY, FIELD_AUTHORITY, IMPLEMENTATIONS, INPUT_SOURCES,
    INPUT_STATUSES, LABEL_RULES, LEVELS, MAX_NODES, NAMESPACED_KIND, NODE_KINDS, NODE_STATUSES, PLAN_SCHEMA,
    READING_SCHEMA, REVIEW_ACTIONS, RUNGS, SELECTION_ORIGINS, STATISTIC_SOURCES, WAYPOINT_KINDS,
    WHOLE_REQUEST_BOUNDARIES)
from ravel.validation import intake_records as _records  # noqa: E402

# Requested-stage names, in the order of a staged study (the deterministic reader's names).
STAGES = ('model-derivation', 'spectrum', 'generation', 'lhe-transform', 'shower', 'detector', 'analysis',
          'statistic', 'figure', 'output-template')
SIGNATURE_IMPLEMENTATIONS = ('science-mode', 'scoped-adapter', 'lifecycle-stage', 'command')
# Effects that make a node compute: the minimum rung of such a node is above ``none``.
COMPUTE_EFFECTS = ('generates_events', 'executes_native', 'runs_authored_code')
BULK_RUNGS = ('full', 'scan')
STATISTIC_KINDS = ('exclusion', 'estimate', 'significance')
NO_STATISTIC_KINDS = ('prediction', 'calculation', 'finding', 'document', 'method_performance')
# The claim kinds a delivered artifact admits (the kind floor). Checks never key on the kind.
KIND_FLOOR = {'inference': ('exclusion', 'estimate', 'significance', 'agreement', 'method_performance'),
              'inference_with_limits': ('exclusion', 'estimate')}
POLICY_DEFAULTS = {'exclusion': '95% CLs', 'estimate': 'profile-likelihood interval',
                   'significance': 'profile-likelihood q0'}
EXPECTED_SIGNIFICANCE_DEFAULT = 'Asimov profile-likelihood q0'
# Source classes whose restriction withholds a published acceptance anchor.
ANCHOR_CLASSES = ('published-results', 'hepdata', 'tables', 'figures', 'paper')
ANCHOR_RE = re.compile(_records.ANCHOR_REFERENCE)
SIGNATURES = 'data/operation_signatures.json'

# --------------------------------------------------------------------------- schemas
TEXT = {'type': 'string', 'minLength': 1}
SHA = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
SPAN = _records.SPAN
PIN = _records.PIN
NULL = {'type': 'null'}


def _obj(properties, required=None, additional=False):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else list(required),
            'additionalProperties': additional}


def _enum(values):
    return {'type': 'string', 'enum': list(values)}


def _array(items, minimum=None, maximum=None):
    schema = {'type': 'array', 'items': items}
    if minimum is not None:
        schema['minItems'] = minimum
    if maximum is not None:
        schema['maxItems'] = maximum
    return schema


def _nullable(schema):
    return {'anyOf': [NULL, schema]}


def _id(prefix):
    return {'type': 'string', 'pattern': '^' + prefix + '[1-9][0-9]*$'}


COUNT = {'type': 'integer', 'minimum': 0}
_SLOT = _obj({'slot': TEXT, 'kind': KIND, 'cardinality': {'type': 'string', 'pattern': r'^[0-9]+\.\.(?:[0-9]+|\*)$'},
              'task_pointer': _nullable({'type': 'string', 'pattern': '^/'}), 'require': {'type': 'object'},
              'optional': {'type': 'boolean'}}, required=('slot', 'kind'))
_ADD = _obj({'element': _enum(BASES[:-1]), 'origin': _enum(SELECTION_ORIGINS), 'origin_from': TEXT,
             'level': _enum(EVENT_LEVELS), 'level_from': TEXT, 'form': TEXT, 'what': TEXT,
             'from': _enum(ANALYTIC_FROM), 'when': {'type': 'object'}}, required=('element',))
SIGNATURE_SCHEMA = _obj({
    'summary': TEXT,
    'implementation': _obj({'kind': _enum(SIGNATURE_IMPLEMENTATIONS), 'mode': TEXT, 'module': TEXT, 'stage': TEXT},
                           required=('kind',)),
    'consumes': _array(_SLOT), 'produces': _array(_SLOT), 'effects': _array(_enum(EFFECTS)),
    'cost': _obj({'unit': TEXT, 'forecast': _nullable(TEXT), 'ceiling_pointer': _nullable(TEXT)}),
    'critical_fields': _array({'type': 'string', 'pattern': '^/'}),
    'basis': _obj({'adds': _array(_ADD), 'passes': _array(TEXT)}),
    'tools': _array(TEXT), 'stages': _array(_enum(STAGES)),
    'review': _obj({'checks': _array(TEXT)}),
    'fidelity_rank': {'type': 'integer', 'minimum': 0, 'maximum': 9},
    'quantity_relations': _array(_obj({'relation': _enum(('equal', 'disjoint')),
                                     'slots': _array(TEXT, minimum=1),
                                     'fields': _array(TEXT, minimum=1),
                                     'group_by': _array(TEXT, minimum=1)}, required=('relation', 'slots', 'fields')))},
    required=('summary', 'implementation', 'consumes', 'produces', 'effects', 'cost', 'critical_fields',
              'basis', 'tools', 'stages', 'review', 'fidelity_rank'))
SIGNATURES_SCHEMA = _obj({'schema_version': {'type': 'integer', 'const': 1},
                          'kind': {'type': 'string', 'const': 'operation-signatures'},
                          'scope': TEXT, 'operations': {'type': 'object', 'additionalProperties': SIGNATURE_SCHEMA}})


def reading_schema_errors(reading):
    return _schema_errors(reading, READING_SCHEMA, 'reading')


def plan_schema_errors(plan):
    return _schema_errors(plan, PLAN_SCHEMA, 'plan')


# --------------------------------------------------------------------------- registry
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def entry_sha256(entry):
    """The hash a plan pins for one signature entry."""
    return hashlib.sha256(canonical(entry)).hexdigest()


@lru_cache(maxsize=1)
def _signature_document():
    return json.loads(files('ravel').joinpath(SIGNATURES).read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _checked_signatures():
    document = _signature_document()
    errors = _schema_errors(document, SIGNATURES_SCHEMA, 'signatures')
    if errors:
        raise ValueError('operation signatures are invalid: ' + '; '.join(errors[:5]))
    return document['operations']


def signatures():
    """The operation signatures: name -> entry (consumes, produces, effects, basis contributions)."""
    return _checked_signatures()


@lru_cache(maxsize=1)
def _registered_modes():
    from ravel.workflow.science import MODES
    from ravel.workflow.scoped_spec import MODES as SCOPED
    return frozenset(MODES) | frozenset(SCOPED)


@lru_cache(maxsize=1)
def _registry():
    signed = signatures()
    names = set(_registered_modes())
    names |= {name for name, entry in signed.items() if entry['implementation']['kind'] in ('lifecycle-stage', 'command')}
    return tuple((name, signed.get(name)) for name in sorted(names))


def registry():
    """Registered operations with their signatures (None for a registered mode without one)."""
    return dict(_registry())


# --------------------------------------------------------------------------- graph helpers
def _error(error_class, reason, action, next_operation=None, ids=()):
    return {'error_class': error_class, 'reason': reason, 'action_required': action,
            'suggested_next_operation': next_operation, 'evidence_ids': sorted(set(ids))}


def _index(plan):
    nodes = {n['id']: n for n in plan.get('nodes', [])}
    inputs = {i['id']: i for i in plan.get('inputs', [])}
    claims = {c['id']: c for c in plan.get('claims', [])}
    return nodes, inputs, claims


def _parents(plan):
    parents = {}
    for edge in plan.get('edges', []):
        parents.setdefault(edge['to']['ref'], []).append(edge['from']['ref'])
    for claim in plan.get('claims', []):
        parents.setdefault(claim['id'], []).extend(claim.get('inherits', []))
    return parents


def ancestors(plan, ref):
    """Every node, input and claim upstream of ``ref`` through edges and ``inherits``."""
    parents, seen, stack = _parents(plan), set(), [ref]
    while stack:
        for parent in parents.get(stack.pop(), ()):
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    seen.discard(ref)
    return seen


def _cycle(plan):
    parents = _parents(plan)
    state = {}
    for start in parents:
        if state.get(start):
            continue
        stack = [(start, iter(parents.get(start, ())))]
        state[start] = 1
        while stack:
            ref, children = stack[-1]
            nxt = next(children, None)
            if nxt is None:
                state[ref] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                return [r for r, _ in stack]
            elif not state.get(nxt):
                state[nxt] = 1
                stack.append((nxt, iter(parents.get(nxt, ()))))
    return None


def _effects(node, reg):
    if node['kind'] == 'authored':
        signature = reg.get(node['operation']) if node.get('operation') else None
        return set(signature['effects'] if signature else ()) | {'runs_authored_code'}
    if node['kind'] != 'operation' or not node.get('operation'):
        return set()
    signature = reg.get(node['operation'])
    effects = set(signature['effects']) if signature else set()
    if node.get('fan_out'):
        effects.add('varies_parameters')
    return effects


def _field(node, pointer, default=None):
    for row in node.get('fields', []):
        if row['pointer'] == pointer:
            return row['value']
    return default


def _norm(text):
    return re.sub(r'[^0-9a-z]+', '', str(text).casefold())


def _incoming(plan, ref, slot):
    return [e for e in plan.get('edges', []) if e['to']['ref'] == ref and e['to']['slot'] == slot]


def _resolve_property(plan, node, inputs, path, pointer):
    """``slot.property`` from the incoming edge or input; a node field overrides."""
    if pointer is not None and _field(node, pointer) is not None:
        return _field(node, pointer)
    slot, _, prop = path.partition('.')
    for edge in _incoming(plan, node['id'], slot):
        if prop in edge.get('require', {}) and type(edge['require'][prop]) is str:
            return edge['require'][prop]
        source = inputs.get(edge['from']['ref'])
        if source and type(source['provides']['require'].get(prop)) is str:
            return source['provides']['require'][prop]
    return 'unresolved'


def _when(rule, node):
    return all(_field(node, pointer) in values for pointer, values in rule.items())


def _contributions(plan, ref, reg, inputs, nodes):
    """Basis elements one node or input contributes, with their properties."""
    if ref in inputs:
        item = inputs[ref]
        require = item['provides']['require']
        rows = []
        if item['source'] == 'requester':
            rows.append({'element': 'supplied_inputs', 'what': item['provides']['kind']})
        elif item['source'] == 'published':
            rows.append({'element': 'published_results', 'form': item['provides']['kind']})
            if item['provides']['kind'] == 'statistical_model':
                rows.append({'element': 'published_statistical_model'})
        if require.get('contains_observed_data') is True or require.get('observed') is True:
            rows.append({'element': 'observed_data'})
        return rows
    node = nodes.get(ref)
    if node is None:
        return []
    if node['kind'] == 'envelope':
        return [{'element': 'unclassified'}]
    if node['kind'] == 'input':
        return [{'element': 'supplied_inputs', 'what': 'input-node'}]
    rows = []
    signature = reg.get(node['operation']) if node.get('operation') else None
    if node['kind'] == 'authored':
        rows.append({'element': 'authored_code'})
        rows += [{'element': b} for b in (node.get('authored') or {}).get('signature', {}).get('basis', ())
                 if b in BASES]
        if signature is None:
            return rows
    elif signature is None:
        return [{'element': 'unclassified'}]
    for add in signature['basis']['adds']:
        if 'when' in add and not _when(add['when'], node):
            continue
        row = {'element': add['element']}
        if 'origin' in add or 'origin_from' in add:
            row['origin'] = add.get('origin') or _resolve_property(plan, node, inputs, add['origin_from'],
                                                                   '/selection_origin')
        if 'level' in add or 'level_from' in add:
            row['level'] = add.get('level') or _resolve_property(plan, node, inputs, add['level_from'], '/event_level')
        for key in ('form', 'what', 'from'):
            if key in add:
                row[key] = add[key]
        rows.append(row)
    return rows


def computed_bases(plan, reg=None):
    """Claim id -> computed basis rows ``{element, via, ...properties}`` from the plan's lineage."""
    reg = registry() if reg is None else reg
    nodes, inputs, claims = _index(plan)
    result = {}
    for claim_id in claims:
        merged = {}
        for ref in sorted(ancestors(plan, claim_id)):
            for row in _contributions(plan, ref, reg, inputs, nodes):
                key = json.dumps(row, sort_keys=True)
                merged.setdefault(key, dict(row, via=[]))['via'].append(ref)
        result[claim_id] = sorted(merged.values(), key=lambda r: (BASES.index(r['element']), json.dumps(r, sort_keys=True)))
    return result


def certificate_relevant(rows):
    """The P0-S1' trigger: a published or reimplemented selection, or a published or stand-in fit."""
    return _records.certificate_relevant(rows)


def _constraints(reading, kind):
    return [c for c in reading.get('constraints', []) if c['type'] == kind]


def _prescription(constraint):
    """The prescribed statistic's text: the reader's ``statistic`` (recorded verbatim), a host's
    ``verbatim`` string, else the span that prescribes it."""
    for key in ('statistic', 'verbatim'):
        value = constraint['value'].get(key)
        if type(value) is str and value.strip():
            return value
    return constraint['evidence'][0]['text']


def withheld(reading):
    """True when a source restriction or blinding withholds published reference values."""
    if _constraints(reading, 'blinding'):
        return True
    for row in _constraints(reading, 'source_restriction'):
        classes = {str(c).casefold() for c in row['value'].get('classes', ())}
        if row['value'].get('kind') in ('blinded', 'no-value-extraction') or classes & set(ANCHOR_CLASSES):
            return True
    return False


def _restricted_terms(reading):
    terms = []
    for row in _constraints(reading, 'source_restriction'):
        value = row['value']
        terms += [(str(c), row['id']) for c in value.get('classes', ())]
        identifiers = value.get('identifiers', ())
        if isinstance(identifiers, dict):
            identifiers = [x for group in identifiers.values() for x in (group if isinstance(group, list) else [group])]
        terms += [(str(x), row['id']) for x in identifiers]
        if type(value.get('source')) is str:
            terms.append((value['source'], row['id']))
    return [(t, k) for t, k in terms if _norm(t)]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def on_lifecycle(plan, claim_id, reg):
    nodes, _, _ = _index(plan)
    return any(nodes[r]['implementation'] == 'lifecycle-stage' for r in ancestors(plan, claim_id) if r in nodes)


def served_off_route_a(plan, claim_id, reg=None):
    """Rule P0-S1': True when a claim needs a certificate (its basis is certificate-relevant) and is
    not served in place on route A, so it carries "not certified on this route".

    The basis is the claim's computed lineage when the plan has one, else its declared basis (an
    undeclared selection origin counts as relevant). In place means a route-A lifecycle node in the
    claim's lineage, or a plan whose derived rule is D3. The CHECK-IN 1 claims section and the plan's
    flags both use this, so they agree on which claims carry the label.
    """
    reg = signatures() if reg is None else reg
    claim = next((c for c in plan['claims'] if c['id'] == claim_id), None)
    if claim is None:
        return False
    rows = computed_bases(plan, reg).get(claim_id) if ancestors(plan, claim_id) else None
    if not rows:
        rows = [{'element': element} for element in claim['basis_declared']]
    if not certificate_relevant(rows):
        return False
    return not ((plan.get('label') or {}).get('rule') == 'D3' or on_lifecycle(plan, claim_id, reg))


def route_a_available(plan, claim_id, reg, catalogue=None):
    """P0-S1' condition 1: a preserved routine (catalogue) or a published workspace in the lineage."""
    nodes, inputs, _ = _index(plan)
    for ref in ancestors(plan, claim_id):
        if ref in inputs:
            provided = inputs[ref]['provides']
            if (provided['kind'] == 'statistical_model' and provided['require'].get('origin') == 'published'
                    and inputs[ref]['source'] == 'published'):
                return True
        elif ref in nodes and nodes[ref]['implementation'] == 'lifecycle-stage':
            locator = _field(nodes[ref], '/analysis')
            if type(locator) is str and preserved_routine(locator, catalogue):
                return True
    return False


def preserved_routine(locator, catalogue=None):
    """True when the analysis catalogue resolves ``locator`` to exactly one preserved routine."""
    if catalogue is not None:
        return bool(catalogue(locator))
    from ravel import analysis_catalog
    try:
        analysis_catalog.resolve(_catalog(), locator)
    except (ValueError, OSError):  # no match, or no local catalogue built on this machine
        return False
    return True


@lru_cache(maxsize=1)
def _catalog():
    from ravel import analysis_catalog
    return analysis_catalog.load_catalog()


def _anchor(plan, claim_id, anchors, reading):
    """P0-S1' condition 2: None before the resource census; then whether an unwithheld anchor exists."""
    if withheld(reading):
        return False
    if anchors is None:
        return None
    nodes, _, _ = _index(plan)
    locators = {_field(nodes[r], '/analysis') for r in ancestors(plan, claim_id) if r in nodes}
    for row in anchors:
        if row.get('withheld'):
            continue
        if row.get('claim') == claim_id or (row.get('locator') and row['locator'] in locators):
            return True
    return False


# --------------------------------------------------------------------------- the check
def check(reading, plan, reg=None, delegation=None, *, obligations=None, anchors=None, catalogue=None, artifacts=None):
    """Typed plan errors (§2.6.3) for a plan against its reading. An empty list means the plan checks.

    ``obligations`` is the contract's obligation census (``task_requirements.obligations``); without it
    the census is the whole request plus the obligation ids the reading names. ``anchors`` are the
    resource census's recorded acceptance anchors (``[{locator|claim, withheld}]``) once the census has
    run; before it, P0-S1' condition 2 is undecided. ``delegation`` holds the declared plan bounds.
    """
    if not isinstance(plan, dict):
        return [_error('schema', 'the plan is not a JSON object', 'write inputs/plan.json as an object')]
    if isinstance(plan.get('nodes'), list) and len(plan['nodes']) > MAX_NODES:
        return [_error('size_limit', f'the plan has {len(plan["nodes"])} nodes; at most {MAX_NODES} are allowed',
                       'split the work into a parent with child plans or an envelope')]
    schema = plan_schema_errors(plan)
    if schema:
        return [_error('schema', e, 'correct the plan to the request-plan schema') for e in schema[:20]]
    reg = registry() if reg is None else reg
    errors = []
    nodes, inputs, claims = _index(plan)
    reading_ids = {x['id'] for key in ('facts', 'constraints', 'deliverables', 'ambiguities', 'boundaries')
                   for x in reading.get(key, [])}
    ambiguities = {a['id']: a for a in reading.get('ambiguities', [])}
    if plan['prompt_sha256'] != reading.get('prompt_sha256'):
        errors.append(_error('schema', 'the plan and the reading bind different prompts',
                             'draft the plan from the reading of this request'))
    ids = [x['id'] for x in (*plan['nodes'], *plan['inputs'], *plan['claims'], *plan['edges'], *plan['waypoints'])]
    duplicates = sorted({x for x in ids if ids.count(x) > 1} | (set(ids) & reading_ids))
    if duplicates:
        errors.append(_error('schema', 'identifiers are not unique: ' + ', '.join(duplicates),
                             'give every node, input, claim, edge and waypoint its own id', ids=duplicates))
    cycle = _cycle(plan)
    if cycle:
        errors.append(_error('cycle', 'the plan graph has a cycle through ' + ' -> '.join(cycle),
                             'remove an edge so that the plan is acyclic', ids=cycle))
    refs = set(nodes) | set(inputs) | set(claims)
    for edge in plan['edges']:
        for end in ('from', 'to'):
            if edge[end]['ref'] not in refs:
                errors.append(_error('edge_incompatible', f'{edge["id"]} {end} names unknown {edge[end]["ref"]}',
                                     'connect edges to nodes, inputs and claims of this plan', ids=[edge['id']]))
        if edge['from']['ref'] in claims:
            errors.append(_error('edge_incompatible', f'{edge["id"]} starts at a claim',
                                 'a claim is a delivered statement; use inherits for document claims', ids=[edge['id']]))
    errors += _operations(plan, reg, nodes)
    errors += _slots(plan, reg, nodes, inputs, claims)
    from ravel.validation.semantic_composition import plan_report, message
    errors += [_error('quantity_incompatible', message(row),
                      'supply compatible quantity facts or an explicit conversion operation',
                      ids=[row['location'].split()[0]]) for row in plan_report(plan, reg, artifacts)['errors']]
    errors += _unresolved(plan, nodes)
    errors += _critical_fields(plan, reg, nodes, ambiguities)
    errors += _coverage(reading, plan, nodes, inputs, claims, obligations)
    errors += _tools(reading, plan, reg, nodes)
    errors += _negated(reading, plan, reg, nodes)
    errors += _sources(reading, plan, reg, nodes, inputs)
    errors += _orphans(plan, nodes, claims)
    errors += _rungs(plan, reg, nodes)
    errors += _conservation(reading)
    bases = computed_bases(plan, reg)
    errors += _claims(reading, plan, reg, nodes, claims, bases)
    errors += _retention(reading, plan, reg, claims, bases, anchors, catalogue)
    errors += _waypoints(plan, reg, nodes, delegation)
    errors += _budgets(plan, nodes, reg, delegation)
    errors += _lease(plan, reg, nodes)
    errors += _boundaries(reading, plan)
    return errors


def _operations(plan, reg, nodes):
    errors = []
    for node in nodes.values():
        operation = node.get('operation')
        if node['kind'] == 'operation':
            if operation is None or operation not in reg:
                errors.append(_error('unknown_operation', f'{node["id"]} names operation {operation!r}, which is not registered',
                                     'use a registered operation, an authored node or a held source-development node',
                                     'ravel modes list', [node['id']]))
            elif node['implementation'] not in SIGNATURE_IMPLEMENTATIONS:
                errors.append(_error('unknown_operation', f'{node["id"]} runs {operation} as {node["implementation"]}',
                                     'an operation node runs a science mode, scoped adapter, lifecycle stage or command',
                                     ids=[node['id']]))
            elif reg[operation] is not None and reg[operation]['implementation']['kind'] != node['implementation']:
                errors.append(_error('unknown_operation', f'{node["id"]} runs {operation} as {node["implementation"]}, '
                                     f'but it is registered as {reg[operation]["implementation"]["kind"]}',
                                     'use the registered implementation', ids=[node['id']]))
        elif node['kind'] == 'authored':
            if node['implementation'] not in AUTHORED_IMPLEMENTATIONS or node.get('authored') is None:
                errors.append(_error('unknown_operation', f'{node["id"]} is authored without an authored implementation and contract',
                                     'declare purpose, signature, known-answer tests and attempt budget', ids=[node['id']]))
            if operation is not None and operation not in reg:
                errors.append(_error('unknown_operation', f'{node["id"]} names operation {operation!r}, which is not registered',
                                     'name a registered authored-step operation or none', ids=[node['id']]))
        elif operation is not None:
            errors.append(_error('unknown_operation', f'{node["id"]} is an {node["kind"]} node but names an operation',
                                 'only operation and authored nodes name operations', ids=[node['id']]))
        if node['status'] in ('held', 'doctor-blocked') and not node.get('held_by'):
            errors.append(_error('unknown_operation', f'{node["id"]} is {node["status"]} without the row or doctor finding that holds it',
                                 'name what would release the node in held_by', ids=[node['id']]))
    return errors


def _kind_ok(edge_kind, slot_kind):
    return edge_kind == slot_kind


def _require_ok(declared, required):
    for key, allowed in required.items():
        if key == 'quantity':  # Nested quantity contracts have located obligations and errors.
            continue
        if key not in declared:
            continue
        options = allowed if isinstance(allowed, list) else [allowed]
        values = declared[key] if isinstance(declared[key], list) else [declared[key]]
        if any(v not in options for v in values):
            return False
    return True


def _slots(plan, reg, nodes, inputs, claims):
    errors = []
    for edge in plan['edges']:
        source = edge['from']['ref']
        if edge['resolution'] == 'convertible' and not edge.get('converter'):
            errors.append(_error('edge_incompatible', f'{edge["id"]} is convertible without a converter node',
                                 'add the registered converter as a node', ids=[edge['id']]))
        if edge['resolution'] == 'convertible' and edge.get('converter') and edge['converter'] not in nodes:
            errors.append(_error('edge_incompatible', f'{edge["id"]} names converter {edge["converter"]}, which is not a node',
                                 'add the converter to the plan as a node', ids=[edge['id']]))
        if source in inputs and inputs[source]['provides']['kind'] != edge['kind']:
            errors.append(_error('edge_incompatible', f'{edge["id"]} carries {edge["kind"]} from input {source}, '
                                 f'which provides {inputs[source]["provides"]["kind"]}',
                                 'connect an input of the consumed kind or add a converter', ids=[edge['id'], source]))
        producer = nodes.get(source)
        if producer and producer['kind'] == 'operation' and reg.get(producer['operation']):
            slots = {s['slot']: s for s in reg[producer['operation']]['produces']}
            slot = slots.get(edge['from']['slot'])
            if slot is None or not _kind_ok(edge['kind'], slot['kind']):
                errors.append(_error('edge_incompatible', f'{edge["id"]}: {producer["operation"]} produces no '
                                     f'{edge["kind"]} in slot {edge["from"]["slot"]!r}',
                                     'connect a produced slot of the right kind', ids=[edge['id'], source]))
        target = edge['to']['ref']
        consumer = nodes.get(target)
        if consumer and consumer['kind'] == 'operation' and reg.get(consumer['operation']) and consumer['status'] == 'available':
            slots = {s['slot']: s for s in reg[consumer['operation']]['consumes']}
            slot = slots.get(edge['to']['slot'])
            if slot is None or not _kind_ok(edge['kind'], slot['kind']):
                errors.append(_error('edge_incompatible', f'{edge["id"]}: {consumer["operation"]} consumes no '
                                     f'{edge["kind"]} in slot {edge["to"]["slot"]!r}',
                                     'connect to a consumed slot of the right kind, or add a converter node',
                                     ids=[edge['id'], target]))
            elif not _require_ok(edge.get('require', {}), slot.get('require', {})):
                errors.append(_error('edge_incompatible', f'{edge["id"]}: declared properties {edge["require"]} do not meet '
                                     f'{consumer["operation"]}.{slot["slot"]} {slot["require"]}',
                                     'add a converter node or choose a compatible producer', ids=[edge['id'], target]))
        if target in claims and edge['to']['slot'] == 'deliverable' and edge['kind'] != claims[target]['deliverable']['artifact']:
            errors.append(_error('edge_incompatible', f'{edge["id"]} delivers {edge["kind"]} to {target}, which declares '
                                 f'{claims[target]["deliverable"]["artifact"]}',
                                 'make the claim deliverable the artifact its producer delivers', ids=[edge['id'], target]))
    for node in nodes.values():
        signature = reg.get(node['operation']) if node['kind'] == 'operation' and node.get('operation') else None
        if signature is None or node['status'] != 'available':
            continue
        for slot in signature['consumes']:
            if not slot.get('optional') and not _incoming(plan, node['id'], slot['slot']):
                errors.append(_error('slot_unfilled', f'{node["id"]} ({node["operation"]}) has nothing for its required '
                                     f'{slot["kind"]} slot {slot["slot"]!r}',
                                     'connect a producer, an input or an authored step to the slot',
                                     'request_plan.draft', [node['id']]))
    for claim in claims.values():
        if not _incoming(plan, claim['id'], 'deliverable') and not claim['inherits']:
            errors.append(_error('slot_unfilled', f'{claim["id"]} has no node that delivers its {claim["deliverable"]["artifact"]}',
                                 'connect the producing node to the claim deliverable', ids=[claim['id']]))
    return errors


def _unresolved(plan, nodes):
    errors = []
    guarded = {ref for w in plan['waypoints'] if w['kind'] in ('condition', 'known_answer', 'closure') and w['check']
               for ref in w['before']}
    for edge in plan['edges']:
        if edge['resolution'] == 'unresolved' and edge['to']['ref'] not in guarded:
            errors.append(_error('edge_unresolved', f'{edge["id"]} has a property known only at runtime',
                                 'add a witness check or waypoint before the consumer, or ask it at CHECK-IN 1',
                                 ids=[edge['id']]))
    return errors


def _critical_fields(plan, reg, nodes, ambiguities):
    errors = []
    for node in nodes.values():
        signature = reg.get(node['operation']) if node.get('operation') else None
        critical = set(signature['critical_fields']) if signature else set()
        for row in node['fields']:
            if row['pointer'] not in critical:
                continue
            if row['authority'] == 'agent_inference':
                decided = ambiguities.get(row['evidence'] or '')
                if not decided or decided['status'] != 'resolved':
                    errors.append(_error('critical_field_unsourced', f'{node["id"]}{row["pointer"]} is a physics-critical '
                                         'value the agent inferred without a decided ambiguity row',
                                         'take the value from the request, a supplied file or a cited source, or ask it',
                                         ids=[node['id']]))
            elif row['authority'] == 'adapter_default' and not ANCHOR_RE.match(row['evidence'] or ''):
                errors.append(_error('critical_field_unsourced', f'{node["id"]}{row["pointer"]} is an adapter default on a '
                                     'physics-critical field without a recorded anchor',
                                     'record the justification: a request span, a registered invariant or a practice reference',
                                     ids=[node['id']]))
    return errors


def census_ids(reading, obligations=None):
    if obligations is not None:
        return [o['id'] for o in obligations]
    ids = ['original-request']
    for key in ('deliverables', 'boundaries'):
        for row in reading.get(key, []):
            ids += [x for x in row['obligation_ids'] if x not in ids]
    ids += [_records.RANGE_PREFIX + f['id'] for f in reading.get('facts', [])
            if f['type'] in _records.RANGE_FACTS and f['evidence']]
    return ids


def _coverage(reading, plan, nodes, inputs, claims, obligations):
    errors = []
    allowed = set(nodes) | set(inputs) | set(claims) | {a['id'] for a in reading.get('ambiguities', [])} | \
        {b['id'] for b in reading.get('boundaries', [])}
    by = {}
    for row in plan['coverage']:
        unknown = [x for x in row['by'] if x not in allowed]
        if unknown:
            errors.append(_error('obligation_uncovered', f'{row["obligation_id"]} is covered by unknown ids {unknown}',
                                 'cover obligations with nodes, inputs, claims, ambiguity rows or boundaries',
                                 ids=[row['obligation_id'], *unknown]))
        by.setdefault(row['obligation_id'], []).extend(x for x in row['by'] if x in allowed)
    census = census_ids(reading, obligations)
    for obligation in census:
        if not by.get(obligation):
            errors.append(_error('obligation_uncovered', f'obligation {obligation} is covered by nothing in the plan',
                                 'add a node, input, claim, ambiguity row or boundary that covers it',
                                 'request_plan.draft', [obligation]))
    # A stated range is covered by a node that fans out over it, by its open scan question or by a
    # boundary; a single-point node or a claim alone collapses the range to a point.
    asked = {a['id'] for a in reading.get('ambiguities', [])} | {b['id'] for b in reading.get('boundaries', [])}
    for obligation in census:
        if not obligation.startswith(_records.RANGE_PREFIX) or not by.get(obligation):
            continue
        flat = [x for x in by[obligation] if x in nodes and not nodes[x]['fan_out']]
        if flat or not any(x in asked or (x in nodes and nodes[x]['fan_out']) for x in by[obligation]):
            errors.append(_error('obligation_uncovered', f'the range obligation {obligation} is covered only by '
                                 'single-point work' + (f' ({", ".join(flat)} does not fan out)' if flat else ''),
                                 'fan a node out over the range, or ask its grid at CHECK-IN 1',
                                 'request_plan.draft', [obligation, *flat]))
    known = set(census)
    for node in nodes.values():
        for obligation in node['covers']:
            if obligation in known and node['id'] not in by.get(obligation, ()):
                errors.append(_error('obligation_uncovered', f'{node["id"]} covers {obligation}, but the coverage table omits it',
                                     'list the node in the coverage row of the obligation', ids=[node['id'], obligation]))
    for claim in claims.values():
        missing = [o for o in claim['obligation_ids'] if o not in known]
        if missing:
            errors.append(_error('obligation_uncovered', f'{claim["id"]} names obligations outside the census: {missing}',
                                 'bind claims to census obligations', ids=[claim['id'], *missing]))
    return errors


def _node_tools(node, reg):
    signature = reg.get(node['operation']) if node.get('operation') else None
    tools = {_norm(t) for t in (signature['tools'] if signature else ())}
    pinned = _field(node, '/tool')
    if pinned is not None:
        tools |= {_norm(t) for t in (pinned if isinstance(pinned, list) else [pinned])}
    return tools


def tool_stages(reading, constraint):
    """The requested stages whose request span contains the span naming a requested tool."""
    return {c['value'].get('stage') for c in _constraints(reading, 'requested_stage')
            if any(t['start'] < s['end'] and s['start'] < t['end'] for t in constraint['evidence'] for s in c['evidence'])}


def _tools(reading, plan, reg, nodes):
    errors = []
    substituted = {ref for a in reading.get('ambiguities', []) if a['status'] == 'resolved'
                   and (a.get('resolution') or {}).get('by') == 'user' for ref in a['blocks']}
    for row in _constraints(reading, 'requested_tool'):
        if row['id'] in substituted:
            continue
        tool = row['value'].get('tool') or row['evidence'][0]['text']
        pinned = [n['id'] for n in nodes.values() if _field(n, '/tool') is not None and _norm(tool) in _node_tools(n, reg)]
        if not pinned:
            errors.append(_error('requested_tool_unserved', f'the request names {tool!r} ({row["id"]}) and no node pins it',
                                 'pin the tool on the node that runs it, hold a development node for it, or record the '
                                 "requester's substitution", ids=[row['id']]))
        stages = tool_stages(reading, row)
        for node in nodes.values():
            if (node['status'] == 'available' and _stages(node, reg) & stages
                    and _norm(tool) not in _node_tools(node, reg)):
                errors.append(_error('requested_tool_unserved', f'{node["id"]} runs {sorted(_stages(node, reg) & stages)} '
                                     f'without the requested tool {tool!r} ({row["id"]})',
                                     "run the stage with the requested tool, hold it, or record the requester's substitution",
                                     ids=[node['id'], row['id']]))
    return errors


def _stages(node, reg):
    signature = reg.get(node['operation']) if node.get('operation') else None
    return set(signature['stages']) if signature else set()


def _negated(reading, plan, reg, nodes):
    negated = {}
    for row in _constraints(reading, 'negated_stage'):
        stage = row['value'].get('stage')
        if stage:
            negated[stage] = row['id']
    errors = []
    for node in nodes.values():
        for stage in sorted(_stages(node, reg) & set(negated)):
            errors.append(_error('negated_stage_present', f'{node["id"]} ({node["operation"]}) performs {stage}, '
                                 f'which the request excludes ({negated[stage]})',
                                 'remove the node or use an operation that does not perform the stage',
                                 ids=[node['id'], negated[stage]]))
    return errors


def _sources(reading, plan, reg, nodes, inputs):
    terms = _restricted_terms(reading)
    if not terms:
        return []
    errors = []
    consumers = [(i['id'], [i['locator'], *(_strings(i['provides']['require']))]) for i in inputs.values()
                 if i['source'] == 'published']
    for node in nodes.values():
        if 'acquires_published' in _effects(node, reg) or node.get('operation') in ('figure-comparison', 'published-summary',
                                                                                     'source-tables'):
            consumers.append((node['id'], [*_strings([r['value'] for r in node['fields']]), node.get('request') or '']))
    for ref, strings in consumers:
        haystack = ' '.join(_norm(s) for s in strings)
        for term, constraint in terms:
            if _norm(term) and _norm(term) in haystack:
                errors.append(_error('forbidden_source', f'{ref} consumes {term!r}, which the request forbids ({constraint})',
                                     'remove the source or replace it with an allowed one', ids=[ref, constraint]))
                break
    return errors


def _orphans(plan, nodes, claims):
    covered = {x for row in plan['coverage'] for x in row['by']}
    feeding = set()
    for claim in claims:
        feeding |= ancestors(plan, claim)
    errors = []
    for node in nodes.values():
        if node['rung'] != 'none' and node['id'] not in covered and node['id'] not in feeding:
            errors.append(_error('orphan_compute', f'{node["id"]} computes but covers no obligation and feeds no claim',
                                 'remove the node or bind it to the obligation it serves', ids=[node['id']]))
    return errors


def _rungs(plan, reg, nodes):
    errors = []
    for node in nodes.values():
        effects = _effects(node, reg) & set(COMPUTE_EFFECTS)
        if effects and node['rung'] == 'none':
            errors.append(_error('rung_below_effects', f'{node["id"]} has effects {sorted(effects)} at rung none',
                                 'plan the node at smoke or above, behind approval', ids=[node['id']]))
    return errors


def _conservation(reading):
    used = {f['witness'] for f in reading.get('facts', []) if f.get('witness')}
    dismissed = {d['witness'] for d in reading.get('dismissed', [])}
    errors = []
    for item in reading.get('witness', []):
        if item['id'] not in used | dismissed:
            errors.append(_error('fact_unconserved', f'witness item {item["id"]} ({item["span"]["text"]!r}) is neither '
                                 'used by a fact nor dismissed', 'use it as a fact witness or dismiss it with a closed reason',
                                 ids=[item['id']]))
    return errors


def _delivered(plan, claim_id, nodes, reg):
    rows = []
    for edge in _incoming(plan, claim_id, 'deliverable'):
        producer = nodes.get(edge['from']['ref'])
        limits = edge['require'].get('limits') is True
        if producer and producer.get('operation') and reg.get(producer['operation']):
            for slot in reg[producer['operation']]['produces']:
                if slot['slot'] == edge['from']['slot'] and slot.get('require', {}).get('limits') is True:
                    limits = True
        rows.append((edge['kind'], limits))
    return rows


def _claims(reading, plan, reg, nodes, claims, bases):
    errors = []
    prescriptions = _constraints(reading, 'prescribed_statistic')
    for claim in claims.values():
        cid = claim['id']
        computed = {r['element'] for r in bases[cid]}
        missing = sorted(computed - set(claim['basis_declared']), key=BASES.index)
        if missing:
            errors.append(_error('claim_basis_understated', f'{cid} declares {claim["basis_declared"]} but its lineage '
                                 f'computes {sorted(computed, key=BASES.index)}', 'declare every computed basis element',
                                 ids=[cid]))
        for kind, limits in _delivered(plan, cid, nodes, reg):
            floor = KIND_FLOOR['inference_with_limits'] if limits else KIND_FLOOR.get(kind)
            if floor and claim['kind'] not in floor:
                errors.append(_error('claim_kind_inconsistent', f'{cid} is a {claim["kind"]} claim but delivers '
                                     f'{"an inference with limits" if limits else "an " + kind}; admissible kinds are {list(floor)}',
                                     'declare the kind the delivered artifact implies', ids=[cid]))
                break
        errors += _statistic(claim, prescriptions, plan['status'])
        if claim['comparison']['target'] == 'published_figure':
            lineage = ancestors(plan, cid)
            if not any(nodes[r].get('operation') == 'figure-comparison' for r in lineage if r in nodes):
                errors.append(_error('published_figure_unserved', f'{cid} compares with a published figure but no '
                                     'figure-comparison node digitises and compares it',
                                     'add a figure-comparison node between the producer and the claim',
                                     'figure-comparison', [cid]))
        if claim['kind'] == 'document' and claim['statistic']['source'] not in ('not_applicable',):
            errors.append(_error('statistic_policy_violation', f'{cid} is a document claim with its own statistic',
                                 'a document claim inherits the statistics of the claims it carries', ids=[cid]))
    return errors


def _statistic(claim, prescriptions, status):
    cid, statistic, kind = claim['id'], claim['statistic'], claim['kind']

    def bad(reason, action, ids=()):
        return [_error('statistic_policy_violation', f'{cid}: {reason}', action, ids=[cid, *ids])]
    if prescriptions and kind in STATISTIC_KINDS:
        verbatim = [_prescription(p) for p in prescriptions]
        if statistic['source'] != 'prescribed' or statistic['definition'] not in verbatim:
            return bad('the request prescribes ' + ' / '.join(repr(v) for v in verbatim) + ', which must stay primary',
                       'make the prescription the primary statistic verbatim; RAVEL statistics go alongside',
                       [p['id'] for p in prescriptions])
        spans = {json.dumps(s, sort_keys=True) for p in prescriptions for s in p['evidence']}
        if not statistic['evidence'] or any(json.dumps(s, sort_keys=True) not in spans for s in statistic['evidence']):
            return bad('the prescribed statistic carries no span of the prescription', 'cite the prescription span')
        return []
    if statistic['source'] == 'prescribed':
        return bad('declares a prescribed statistic the request does not contain', 'use the policy default or declare one')
    if kind in NO_STATISTIC_KINDS:
        if statistic['source'] != 'not_applicable' or statistic['secondary']:
            return bad(f'a {kind} claim has no statistic; declare its uncertainty budget, precision or metric instead',
                       'set the statistic source to not_applicable')
        return []
    if kind == 'agreement':
        if statistic['source'] != 'declared':
            return bad('an agreement claim declares its metric and tolerance', 'set the statistic source to declared')
        if status == 'proposed' and (claim['comparison']['metric'] is None or claim['comparison']['tolerance'] is None
                                     or statistic['definition'] is None):
            return bad('the agreement metric, tolerance and covariance treatment are not declared',
                       'declare them before CHECK-IN 1')
        return []
    if statistic['source'] == 'not_applicable':
        return bad(f'a {kind} claim needs a statistic', 'apply the statistic policy')
    if statistic['source'] == 'policy_default':
        expected = POLICY_DEFAULTS[kind]
        allowed = {expected, EXPECTED_SIGNIFICANCE_DEFAULT} if kind == 'significance' else {expected}
        if statistic['definition'] not in allowed:
            return bad(f'the policy default for {kind} is {expected!r}', 'use the policy default or declare the statistic')
    elif status == 'proposed' and statistic['definition'] is None:
        return bad('the declared statistic has no definition', 'declare the statistic before CHECK-IN 1')
    return []


def _retention(reading, plan, reg, claims, bases, anchors, catalogue):
    errors = []
    for cid in claims:
        if not certificate_relevant(bases[cid]):
            continue
        in_place = on_lifecycle(plan, cid, reg)
        available = route_a_available(plan, cid, reg, catalogue)
        anchored = _anchor(plan, cid, anchors, reading)
        if in_place and (not available or anchored is False):
            errors.append(_error('in_place_retention', f'{cid} stays on a route-A lifecycle node, but '
                                 + ('route A cannot produce its artifact' if not available
                                    else 'its certificate anchor is withheld or not recorded'),
                                 'serve the claim from children and label it "not certified on this route"',
                                 ids=[cid]))
        elif not in_place and available and anchored is True:
            errors.append(_error('in_place_retention', f'{cid} has a preserved route and a recorded certificate anchor '
                                 'but is served off route A', 'keep the claim on the route-A lifecycle node', ids=[cid]))
    return errors


def _waypoints(plan, reg, nodes, delegation):
    errors = []
    for waypoint in plan['waypoints']:
        for ref in [waypoint['after'], *waypoint['before']]:
            if ref is not None and ref not in nodes:
                errors.append(_error('waypoint_none_invalid' if waypoint['kind'] == 'none' else 'schema',
                                     f'{waypoint["id"]} names unknown node {ref}', 'name nodes of this plan',
                                     ids=[waypoint['id']]))
        if waypoint['kind'] != 'none':
            continue
        compute = [n for n in nodes.values() if n['rung'] != 'none']
        reasons = []
        if len(compute) != 1:
            reasons.append(f'{len(compute)} nodes are above rung none')
        elif compute[0]['fan_out'] is not None:
            reasons.append('the node fans out')
        elif compute[0]['rung'] == 'scan':
            reasons.append('the node runs at scan rung')
        elif compute[0]['kind'] != 'operation' or compute[0]['implementation'] not in ('scoped-adapter', 'science-mode'):
            reasons.append('the node is not a single bounded stage')
        if delegation is not None:
            reasons.append('only a human approval can select waypoint none')
        if reasons:
            errors.append(_error('waypoint_none_invalid', f'{waypoint["id"]}: ' + '; '.join(reasons),
                                 'keep the smoke rung and CHECK-IN 2 GO before bulk compute', ids=[waypoint['id']]))
    return errors


def _budgets(plan, nodes, reg, delegation):
    errors = []
    aggregate = plan['aggregate_budget']
    pairs = (('max_seconds', 'wall_seconds'), ('events', 'events'), ('disk_bytes', 'disk_bytes'),
             ('native_attempts', 'native_attempts'))
    for node_key, plan_key in pairs:
        ceiling = aggregate[plan_key]
        values = [n['budget'][node_key] for n in nodes.values() if n['budget'][node_key] is not None]
        if ceiling is not None and sum(values) > ceiling:
            errors.append(_error('budget_exceeds', f'node {node_key} total {sum(values)} exceeds the plan {plan_key} {ceiling}',
                                 'reduce node budgets or raise the declared ceiling at CHECK-IN 1'))
    if delegation:
        limits = {'wall_seconds': aggregate['wall_seconds'], 'native_attempts': aggregate['native_attempts'],
                  'events': aggregate['events'], 'disk_bytes': aggregate['disk_bytes'], 'calls': aggregate['calls'],
                  'output_tokens': aggregate['output_tokens']}
        for key, value in limits.items():
            bound = delegation.get(key)
            if bound is not None and (value is None or value > bound):
                errors.append(_error('delegation_exceeds', f'the plan {key} {value} is not within the delegated bound {bound}',
                                     'state a plan budget within the delegation bounds'))
        if delegation.get('max_nodes') is not None and len(nodes) > delegation['max_nodes']:
            errors.append(_error('delegation_exceeds', f'{len(nodes)} nodes exceed the delegated {delegation["max_nodes"]}',
                                 'reduce the plan or ask the requester'))
        kinds = delegation.get('node_kinds')
        denied = set(delegation.get('denied_effects', ()))
        for node in nodes.values():
            if kinds is not None and node['kind'] not in kinds:
                errors.append(_error('delegation_exceeds', f'{node["id"]} is a {node["kind"]} node, not delegated',
                                     'ask the requester', ids=[node['id']]))
            if node['kind'] == 'authored' and not delegation.get('authored_nodes', False):
                errors.append(_error('delegation_exceeds', f'{node["id"]} is authored; the delegation does not enable authored nodes',
                                     'ask the requester to enable authored nodes', ids=[node['id']]))
            hit = (_effects(node, reg) & denied) | ({'writes_external'} & _effects(node, reg))
            if hit:
                errors.append(_error('delegation_exceeds', f'{node["id"]} has effects {sorted(hit)} that delegation cannot approve',
                                     'ask the requester', ids=[node['id']]))
    return errors


def _lease(plan, reg, nodes):
    errors = []
    for node in nodes.values():
        parallel = _field(node, '/parallel')
        if 'executes_native' in _effects(node, reg) and type(parallel) is int and parallel > 1:
            errors.append(_error('lease_conflict', f'{node["id"]} runs {parallel} native jobs at once',
                                 'one native job runs at a time; set parallel to 1', ids=[node['id']]))
    return errors


def _boundaries(reading, plan):
    rows = {b['id']: b for b in reading.get('boundaries', [])}
    errors = []
    for ref in plan['boundaries']:
        row = rows.get(ref)
        if row is None or row['class'] not in BOUNDARY_CLASSES or not row['evidence']:
            errors.append(_error('boundary_unjustified', f'{ref} is not a reading boundary in one of the six classes with evidence',
                                 'bound work only by a reading boundary row with evidence', ids=[ref]))
    return errors


# --------------------------------------------------------------------------- flags
def flags(reading, plan, reg=None, *, catalogue=None, artifacts=None):
    """Numbered CHECK-IN 1 flags the plan raises without being in error."""
    reg = registry() if reg is None else reg
    nodes, _, claims = _index(plan)
    rows = []
    for node in nodes.values():
        if node['kind'] == 'operation' and node.get('operation') in reg and reg[node['operation']] is None:
            rows.append({'flag': 'unclassified', 'ids': [node['id']],
                         'text': f'{node["operation"]} has no operation signature; its evidence basis is unclassified'})
        if node['kind'] == 'envelope':
            rows.append({'flag': 'open_research', 'ids': [node['id']],
                         'text': 'open research: the host or research coordinator proposes the operations'})
        if node['status'] != 'available':
            rows.append({'flag': 'held', 'ids': [node['id']], 'text': f'{node["id"]} is {node["status"]} by {node["held_by"]}'})
        for field in node['fields']:
            if field['authority'] == 'adapter_default':
                rows.append({'flag': 'adapter_default', 'ids': [node['id']],
                             'text': f'{node["id"]}{field["pointer"]} uses an adapter default (anchor {field["evidence"]})'})
    bases = computed_bases(plan, reg)
    for cid in claims:
        rows += _certifiability(reading, plan, reg, nodes, cid, bases[cid], catalogue)
        for row in bases[cid]:
            if 'unresolved' in (row.get('origin'), row.get('level')):
                rows.append({'flag': 'basis_property_unresolved', 'ids': [cid, *row['via']],
                             'text': f'{cid}: {row["element"]} has an unresolved selection origin or event level'})
    for row in reading.get('ambiguities', []):
        if row['status'] == 'open':
            rows.append({'flag': 'physics_critical_open' if row['physics_critical'] else 'ambiguity_open',
                         'ids': [row['id']], 'text': row['issue']})
    for edge in plan['edges']:
        if edge['resolution'] == 'unresolved':
            rows.append({'flag': 'edge_unresolved', 'ids': [edge['id']], 'text': f'{edge["id"]} is checked by its witness'})
    from ravel.validation.semantic_composition import plan_report, message
    rows += [{'flag': 'quantity_obligation', 'ids': [row['location'].split()[0]],
              'text': message(row)} for row in plan_report(plan, reg, artifacts)['obligations']]
    return rows


def _certifiability(reading, plan, reg, nodes, cid, rows, catalogue):
    """Flags for a claim with no certifiable route, each with a plain explanation and a proposed route."""
    flags_ = []
    infers = any(kind == 'inference' for kind, _ in _delivered(plan, cid, nodes, reg))
    if certificate_relevant(rows) and withheld(reading):
        flags_.append({'flag': 'reference_withheld', 'ids': [cid], 'text': (
            f'{cid}: the request withholds the published reference values, so the acceptance cannot be certified '
            'against them. It delivers labelled "blinded-prediction" with an alternative waypoint and a check that no '
            'withheld value entered the lineage.')})
    elif served_off_route_a(plan, cid, reg):
        proposal = ('Route A can carry it once the resource census records an acceptance anchor.'
                    if route_a_available(plan, cid, reg, catalogue) else
                    'A certifiable route needs a preserved routine or a published workspace for the analysis and an '
                    'acceptance anchor recorded by the resource census.')
        flags_.append({'flag': 'not_certified_on_this_route', 'ids': [cid],
                       'text': f'{cid}: not certified on this route. {proposal}'})
    designed = [r for r in rows if r['element'] == 'simulated_acceptance'
                and r.get('origin') in ('designed', 'requester', 'unresolved')]
    if infers and designed:
        flags_.append({'flag': 'no_certifiable_route', 'ids': [cid, *designed[0]['via']], 'text': (
            f'{cid}: the selection is designed or supplied, so no published acceptance exists to certify it. The '
            'result is delivered labelled "uncertified-proxy" with MC closure, a cutflow review and an MC-statistics '
            'target, and any limit stays out of record. To certify it, use a published or reimplemented selection '
            'whose acceptance anchor the resource census records.')})
    return flags_


def adapter_defaults(plan):
    """Adopted adapter defaults with their anchors, for CHECK-IN 3 (the decision-control seam)."""
    return [{'node': n['id'], 'operation': n.get('operation'), 'pointer': f['pointer'], 'value': f['value'],
             'anchor': f['evidence']}
            for n in plan.get('nodes', []) for f in n.get('fields', []) if f['authority'] == 'adapter_default']


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check a request plan against its reading (no compute).')
    parser.add_argument('--reading', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--contract', help='task contract whose obligation census the plan must cover')
    parser.add_argument('--anchors', help='JSON list of recorded acceptance anchors from the resource census')
    args = parser.parse_args(argv)
    with open(args.reading, encoding='utf-8') as stream:
        reading = json.load(stream)
    with open(args.plan, encoding='utf-8') as stream:
        plan = json.load(stream)
    obligations = anchors = None
    if args.contract:
        with open(args.contract, encoding='utf-8') as stream:
            obligations = json.load(stream).get('task_requirements', {}).get('obligations')
    if args.anchors:
        with open(args.anchors, encoding='utf-8') as stream:
            anchors = json.load(stream)
    errors = check(reading, plan, obligations=obligations, anchors=anchors)
    report = {'errors': errors, 'flags': [] if errors else flags(reading, plan)}
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
