"""Agreement-target records: what an agreement claim is compared with, and how.

An agreement claim of the pinned request plan names its comparison only as a target class,
a locator, a metric and a tolerance. ``inputs/agreement_targets.json`` adds one target
record per agreement claim: the reference kind and its pins, the result and reference
quantities with any declared conversion, the reference family, the node lattice, the
tolerance rule and a noise-model reference. One claim has one target; a second comparator
is a second agreement claim. The structure is ``data/claims/agreement_target.schema.json``.

This module is a CHECK-IN 1 section provider registered in ``data/checkin/sections.json``.
``checkin_section`` renders the ``agreement_targets`` section, including each target's
node coverage of its reference lattice, into the CHECK-IN 1 bytes; ``checkin_errors``
refuses a CHECK-IN 1 whose agreement claim has no valid target record. Consumers (residual
diagnosis, recipe ledger, calibration, review rows) read ``targets(rundir)``.
"""
import hashlib
import json
import os
import re
from importlib.resources import files

RECORD = os.path.join('inputs', 'agreement_targets.json')
PUBLISHED_TARGETS = ('published_figure', 'published_table', 'published_value', 'published_limit_set')
# The plan's comparison target class each reference kind may serve.
REFERENCE_TARGETS = {'published_result': PUBLISHED_TARGETS, 'published_reproduction': PUBLISHED_TARGETS,
                     'supplied': ('supplied',), 'other_claim': ('other_claim',)}
_DIGITS = 9


def schema():
    return json.loads(files('ravel').joinpath('data/claims/agreement_target.schema.json').read_text())


def _schema_errors(record):
    from jsonschema import Draft202012Validator
    errors = []
    for err in sorted(Draft202012Validator(schema()).iter_errors(record), key=lambda e: list(e.absolute_path)):
        where = '/'.join(str(p) for p in err.absolute_path) or '(root)'
        errors.append(f'{RECORD} schema: {where}: {err.message}'[:500])
    return errors


def validate(target, claim=None, claims=()):
    """Refusals for one target record: its schema and, given its plan claim, the semantic checks."""
    from jsonschema import Draft202012Validator
    document = schema()
    single = {'$schema': document['$schema'], '$defs': document['$defs'], '$ref': '#/$defs/target'}
    errors = []
    for err in sorted(Draft202012Validator(single).iter_errors(target), key=lambda e: list(e.absolute_path)):
        where = '/'.join(str(p) for p in err.absolute_path) or '(root)'
        errors.append(f'target schema: {where}: {err.message}'[:500])
    if errors:
        return errors
    if claim is None:
        return ['a target record is validated against its plan claim']
    return target_errors(target, claim, list(claims) or [claim])


def _reject_constant(name):
    raise ValueError(f'non-finite number {name}')


def _plan_claims(context):
    """Claims of the pinned request plan, or None when the run pins no readable plan."""
    base_dir = context.get('base_dir')
    if base_dir is None:
        return None
    from ravel.validation.validate_checkin import pinned_records
    try:
        _, plan = pinned_records(base_dir, context.get('contract'))
    except (ValueError, OSError):
        return None
    if not isinstance(plan, dict) or not isinstance(plan.get('claims'), list):
        return None
    return [c for c in plan['claims'] if isinstance(c, dict)]


def _key(node):
    return tuple(round(float(x), _DIGITS) for x in node)


def node_coverage(nodes):
    """Coverage of the reference lattice by the compared nodes, in lattice order."""
    lattice = [_key(n) for n in nodes['reference_lattice']]
    compared = [_key(n) for n in nodes['compared']]
    on_lattice = set(lattice)
    covered = set(compared) & on_lattice
    return {'reference_nodes': len(lattice), 'compared_nodes': len(compared), 'covered_nodes': len(covered),
            'fraction': round(len(covered) / len(lattice), 6),
            'missing': [list(n) for n in lattice if n not in covered],
            'off_lattice': [list(n) for n in compared if n not in on_lattice]}


def _node_errors(nodes):
    width = len(nodes['coordinates'])
    errors = []
    for name in ('reference_lattice', 'compared'):
        keys = [_key(n) for n in nodes[name]]
        if any(len(k) != width for k in keys):
            errors.append(f'every {name} node needs {width} coordinates {nodes["coordinates"]}')
        if len(set(keys)) != len(keys):
            errors.append(f'{name} repeats a node')
    return errors


_FAMILIES = ('observed', 'expected')
_COMPARED_KINDS = ('exclusion', 'estimate', 'significance')


def result_family(target, claim, claims):
    """(family, error) of the result the agreement claim compares; family None when unresolved.

    The drafter records ``level='not_applicable'`` on every agreement claim; the compared
    result's family lives on the limit, estimate or significance claim it compares.
    ``target['compares']`` names that claim and decides the family; an agreement claim whose
    own level names a different family is refused. Without it, a claim whose own level is
    observed or expected keeps it; otherwise the plan's compared claims with a declared
    family that share the agreement claim's comparison target must agree on one family.
    """
    own = claim.get('level')
    by_id = {c.get('id'): c for c in claims}
    named = target.get('compares')
    if named is not None:
        compared = by_id.get(named)
        if compared is None or compared.get('kind') not in _COMPARED_KINDS or named == claim['id']:
            return None, f'compares names {named}, which is not a limit, estimate or significance claim of the plan'
        family = compared.get('level')
        if own in _FAMILIES and own != family:
            return None, (f'the agreement claim declares the {own} level but compares {named}, a {family}-family '
                          'result; the compared claim decides the family')
        return family, None
    if own in _FAMILIES:
        return own, None
    plan_target = (claim.get('comparison') or {}).get('target')
    candidates = [c for c in claims if c.get('kind') in _COMPARED_KINDS and c.get('level') in _FAMILIES]
    sharing = [c for c in candidates if (c.get('comparison') or {}).get('target') == plan_target] or candidates
    families = sorted({c['level'] for c in sharing})
    if len(families) > 1:
        ids = ', '.join(c['id'] for c in sharing)
        return None, (f'the compared result is ambiguous between {ids} of different families; '
                      'name the compared claim in compares')
    return (families[0] if families else None), None


_REMOTE = re.compile(r'^[A-Za-z][\w+.-]*:')
# A plan tolerance {aggregation: threshold}; every node within a bound is the bound on the maximum.
_SAME_AGGREGATION = {'per_node': 'max_abs', 'max_abs': 'max_abs'}


def target_pins(target):
    """(role, pin) for every pin a target record names."""
    rows = [('reference', p) for p in target['reference']['pins']]
    rows += [('recipe', p) for p in target['reference']['recipe_pins']]
    rows += [('conversion', p) for p in (target['conversion'] or {}).get('pins', [])]
    if target['noise_model']['pin'] is not None:
        rows.append(('noise model', target['noise_model']['pin']))
    return rows


def pin_errors(base_dir, target):
    """(errors, unverified locators): run-relative and absolute pins must hold their bytes.

    A locator with a scheme (``https:``, ``doi:``, ``arXiv:``) cannot be read here; it is
    listed in the CHECK-IN 1 section as unverified rather than accepted silently.
    """
    errors, unverified = [], []
    for role, pin in target_pins(target):
        locator = pin['locator']
        if _REMOTE.match(locator) and not os.path.isabs(locator):
            unverified.append(locator)
            continue
        path = locator if os.path.isabs(locator) else os.path.join(base_dir, locator)
        try:
            with open(path, 'rb') as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
        except FileNotFoundError:
            errors.append(f'{role} pin {locator} is missing')
            continue
        except OSError as exc:
            errors.append(f'{role} pin {locator} is unreadable: {exc}')
            continue
        if digest != pin['sha256']:
            errors.append(f'{role} pin {locator} has sha256 {digest}, not the pinned {pin["sha256"]}')
    return errors, unverified


_AGGREGATIONS = ('per_node', 'fraction_within', 'median_abs', 'max_abs')


def _tolerance_errors(rule, tolerance):
    """The plan tolerance names one aggregation and threshold; the target rule must equal it.

    Other keys (a note, a label) do not change the bound. A null plan tolerance is flagged in
    the section and refused for a certified claim by the CHECK-IN 1 claims check.
    """
    if tolerance is None:
        return []
    named = [k for k in tolerance if k in _AGGREGATIONS] if isinstance(tolerance, dict) else []
    if len(named) != 1:
        return [f'the plan claim tolerance names {len(named)} recognized aggregations {named}; exactly one of '
                f'{list(_AGGREGATIONS)} with a numeric threshold bounds the claim']
    aggregation = named[0]
    threshold = tolerance[aggregation]
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        return [f'the plan claim tolerance {aggregation} needs a numeric threshold, not {threshold!r}']
    same = _SAME_AGGREGATION.get(rule['aggregation'], rule['aggregation']) == _SAME_AGGREGATION.get(aggregation, aggregation)
    if not same or abs(rule['threshold'] - threshold) > 1e-12 * max(1.0, abs(threshold)):
        return [f'tolerance rule {rule["aggregation"]} {rule["threshold"]} differs from the plan claim '
                f'tolerance {aggregation} {threshold}']
    return []


def target_errors(target, claim, claims, base_dir=None):
    """Semantic refusals for one schema-valid target record against its plan claim."""
    errors = []
    claim_ids = {c.get('id') for c in claims}
    reference, comparison = target['reference'], claim.get('comparison') or {}
    kind, plan_target = reference['kind'], comparison.get('target')
    if plan_target in (None, 'none'):
        errors.append('the agreement claim declares no comparison target in the request plan')
    elif plan_target not in REFERENCE_TARGETS[kind]:
        errors.append(f'reference kind {kind} cannot serve the plan comparison target {plan_target}')
    if kind == 'other_claim':
        if reference['claim_id'] not in claim_ids or reference['claim_id'] == claim['id']:
            errors.append('an other_claim reference names another claim of the pinned request plan')
    else:
        if reference['claim_id'] is not None:
            errors.append(f'a {kind} reference names no claim id')
        if not reference['pins']:
            errors.append(f'a {kind} reference needs content pins')
    if kind in ('published_result', 'published_reproduction') and target['noise_model']['pin'] is None:
        errors.append(f'a {kind} reference needs a pinned noise model: the spread that decides agreement '
                      'must be fixed before the comparison')
    if kind == 'published_reproduction' and not reference['recipe_pins']:
        errors.append('a published_reproduction reference needs recipe pins: the reproduced recipe '
                      '(cards, settings, code) must be pinned before its numbers are a target')

    family, family_error = result_family(target, claim, claims)
    reference_family = target['family']['reference']
    if family_error:
        errors.append(family_error)
    elif family is None:
        errors.append('the compared result family is unresolved: no compared claim declares an observed or '
                      'expected family; name the compared claim in compares')
    elif family not in _FAMILIES and kind in ('published_result', 'published_reproduction'):
        errors.append(f'the compared result family is unresolved ({family}); a {kind} reference compares an '
                      'observed or expected result')
    elif family != reference_family:
        errors.append(f'compares a {family}-family result with a {reference_family}-family reference; '
                      'the family must match')

    result, ref = target['quantity']['result'], target['quantity']['reference']
    if result['name'] != ref['name'] and (result['basis'], result['unit']) == (ref['basis'], ref['unit']) \
            and target['conversion'] is None:
        errors.append(f'compares {result["name"]} with {ref["name"]}: different quantities need a declared conversion')
    if (result['basis'], result['unit']) != (ref['basis'], ref['unit']):
        conversion = target['conversion']
        if conversion is None:
            errors.append(f'compares {result["basis"]} [{result["unit"]}] with {ref["basis"]} [{ref["unit"]}] '
                          'without a declared conversion')
        else:
            if {conversion['from'], conversion['to']} != {result['basis'], ref['basis']} or (
                    result['basis'] != ref['basis'] and conversion['from'] == conversion['to']):
                errors.append(f'the declared conversion {conversion["from"]} -> {conversion["to"]} does not join '
                              f'{result["basis"]} and {ref["basis"]}')
            if not conversion['pins']:
                errors.append('the declared conversion needs pins for its inputs')

    metric = comparison.get('metric')
    if metric is not None and metric != target['tolerance_rule']['metric']:
        errors.append(f'tolerance rule metric {target["tolerance_rule"]["metric"]!r} differs from the claim '
                      f'metric {metric!r}')

    errors += _tolerance_errors(target['tolerance_rule'], comparison.get('tolerance'))
    if base_dir is not None:
        errors += pin_errors(base_dir, target)[0]

    node_errors = _node_errors(target['nodes'])
    errors += node_errors
    if not node_errors:
        off = node_coverage(target['nodes'])['off_lattice']
        if off:
            errors.append(f'{len(off)} compared node(s) lie off the reference lattice: {off[:8]}')
    return errors


def _load(base_dir):
    """(record, sha256, errors); record None when absent or unreadable."""
    path = os.path.join(base_dir, RECORD)
    try:
        with open(path, 'rb') as handle:
            raw = handle.read()
    except FileNotFoundError:
        return None, None, []
    except OSError as exc:
        return None, None, [f'{RECORD} unreadable: {exc}']
    digest = hashlib.sha256(raw).hexdigest()
    try:
        record = json.loads(raw.decode('utf-8'), parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        return None, digest, [f'{RECORD} is not strict JSON: {exc}']
    errors = _schema_errors(record)
    return (None if errors else record), digest, errors


def checkin_section(context):
    """The ``agreement_targets`` CHECK-IN 1 section, or None when nothing applies."""
    claims = _plan_claims(context)
    if claims is None:
        return None
    agreement = [c for c in claims if c.get('kind') == 'agreement']
    base_dir = context['base_dir']
    if not agreement and not os.path.exists(os.path.join(base_dir, RECORD)):
        return None
    record, digest, file_errors = _load(base_dir)
    by_claim = {}
    for target in (record or {}).get('targets', []):
        by_claim.setdefault(target['claim_id'], []).append(target)
    rows = []
    for claim in agreement:
        cid, found = claim['id'], by_claim.pop(claim['id'], [])
        row = {'claim_id': cid, 'target': found[0] if len(found) == 1 else None, 'node_coverage': None,
               'unverified_pins': [], 'flags': []}
        if not found:
            row['errors'] = [f'agreement claim {cid} has no agreement-target record in {RECORD}']
        elif len(found) > 1:
            row['errors'] = [f'agreement claim {cid} has {len(found)} target records; two comparators give two '
                             'claims: declare one agreement claim per reference']
        else:
            row['errors'] = target_errors(found[0], claim, claims, base_dir)
            row['unverified_pins'] = pin_errors(base_dir, found[0])[1]
            if (claim.get('comparison') or {}).get('tolerance') is None:
                row['flags'].append('the plan declares no tolerance; the target tolerance rule is the only bound, '
                                    'and a certified claim needs a plan tolerance')
            if not _node_errors(found[0]['nodes']):
                coverage = row['node_coverage'] = node_coverage(found[0]['nodes'])
                if coverage['covered_nodes'] < coverage['reference_nodes']:
                    row['flags'].append(f'compares {coverage["covered_nodes"]} of {coverage["reference_nodes"]} '
                                        'reference nodes; the uncompared nodes carry no agreement claim')
        row['status'] = 'refused' if row['errors'] else 'valid'
        rows.append(row)
    for cid, found in by_claim.items():
        rows.append({'claim_id': cid, 'target': None, 'node_coverage': None, 'unverified_pins': [], 'flags': [],
                     'status': 'refused',
                     'errors': [f'{cid} is not an agreement claim of the pinned request plan']})
    return {'record': RECORD.replace(os.sep, '/'), 'record_sha256': digest, 'errors': file_errors, 'claims': rows}


def checkin_errors(content, context):
    """Refusals for the freshly rendered section; the seam separately binds the document copy."""
    rendered = checkin_section(context)
    if rendered is None:
        return []
    errors = [f'CHECK-IN 1 agreement target: {e}' for e in rendered['errors']]
    for row in rendered['claims']:
        errors += [f'CHECK-IN 1 agreement target ({row["claim_id"]}): {e}' for e in row['errors']]
    return errors


def targets(rundir, contract=None):
    """Valid target records by claim id for consumers; refused rows are omitted."""
    from ravel.validation.validate_checkin import _sibling_contract
    context = {'base_dir': str(rundir), 'contract': contract if contract is not None else _sibling_contract(str(rundir))}
    section = checkin_section(context) or {'claims': []}
    return {row['claim_id']: {**row['target'], 'node_coverage': row['node_coverage']}
            for row in section['claims'] if row['status'] == 'valid'}
