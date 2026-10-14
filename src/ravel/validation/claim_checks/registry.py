"""Resolve registered check functions from the typed graph, never from a claim label."""
from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
from functools import lru_cache
import json

from ravel.validation import validate_request_plan as rp
from . import rows


@lru_cache(maxsize=1)
def _registry_bytes():
    return files('ravel').joinpath('data/claim_checks.json').read_text(encoding='utf-8')


def registry():
    """A fresh copy of the packaged check registry, so callers cannot mutate future gates."""
    doc = json.loads(_registry_bytes())
    if type(doc.get('schema_version')) is not int or doc['schema_version'] != 1 or doc.get('kind') != 'claim-check-registry':
        raise ValueError('claim-check registry schema 1 required')
    return doc['checks']


def evaluator(check_id):
    from .legacy import EVALUATORS
    return rows.EVALUATORS.get(check_id) or EVALUATORS.get(check_id)


def computed_id(check_id):
    """Computed identifiers include namespaced aliases and inference alarm instance ids."""
    from ravel.validation.regression_triggers import TRIGGERS
    if not isinstance(check_id, str):
        return False
    value = check_id.removeprefix('check:')
    return value in registry() or value.removeprefix('regression/').split('@', 1)[0] in TRIGGERS


def conformance(registry=None, checks=None):
    """Every route's review terms resolve to a callable machine check; missing routes fail."""
    reg = rp.registry() if registry is None else registry
    checks = globals()['registry']() if checks is None else checks
    errors = []
    for name, row in checks.items():
        if row.get('computed') is not True or row.get('evaluator') != name or not callable(evaluator(name)):
            errors.append(f'unresolved computed check {name}')
    for name in sorted(rp._registered_modes() - set(reg)):
        errors.append(f'unresolved route {name}')
    for name, signature in sorted(reg.items()):
        if signature is None:
            errors.append(f'unresolved route {name}: no operation signature')
            continue
        for check in signature.get('review', {}).get('checks', []):
            if check not in checks or not callable(evaluator(check)):
                errors.append(f'unresolved check {check} on route {name}')
    return errors


def documents(artifacts, refs):
    """Documents of these exact lineage refs (a ref may retain multiple artifacts)."""
    found = []
    for ref in sorted(refs):
        values = (artifacts or {}).get(ref, [])
        if isinstance(values, dict):
            values = [values]
        if not isinstance(values, list):
            raise ValueError('artifacts map a lineage ref to a document or list of documents')
        for value in values:
            if not isinstance(value, dict):
                raise ValueError('claim artifacts are retained document objects')
            found.append((ref, value))
    return found


def _properties(plan, refs):
    props = []
    for item in plan.get('inputs', []):
        if item['id'] in refs:
            props.append(item.get('provides', {}).get('require', {}))
    for node in plan.get('nodes', []):
        if node['id'] in refs:
            props += [f.get('value') for f in node.get('fields', []) if isinstance(f.get('value'), dict)]
            props.append({f['pointer'].rsplit('/', 1)[-1]: f.get('value') for f in node.get('fields', [])})
    return props


def _context_checks(plan, refs, docs, effects, bases, stages):
    properties = _properties(plan, refs) + [d for _, d in docs]
    check_ids = {key for p in properties for key in p.get('claim_evidence', {})}
    if any(p.get('generator_cuts') is not None for p in properties) or ('generation' in stages and 'analysis' in stages):
        check_ids.add('generation_cut_consistency')
    if 'lhe-transform' in stages or any('required_downstream' in p for p in properties):
        check_ids.add('downstream_settings_after_transforms')
    if any(p.get('shared_sm_amplitude') is True and (p.get('declared_powers') or p.get('power_law') or p.get('morph_basis')) for p in properties):
        check_ids.add('interference_size')
    if any(p.get('level') == 'unfolded' or p.get('event_level') == 'unfolded' for p in properties):
        check_ids.add('measurement_applicability')
    if any(p.get('correlation_declared') is False or 'correlation_range' in p for p in properties):
        check_ids.add('agreement_correlation_range')
    if any('relative_mc_precision' in p or 'relative_target' in p for p in properties):
        check_ids.add('per_bin_mc_precision')
    if any(p.get('eft') or 'cutoff' in p for p in properties):
        check_ids.add('eft_validity')
    if any(p.get('learned') is True or p.get('selection_origin') == 'learned' for p in properties) or 'trained_model' in bases:
        check_ids |= {'learned_selection_sculpting', 'split_integrity', 'baseline_first'}
    if any(p.get('attribution') is True for p in properties):
        check_ids.add('attribution_above_noise')
    if any(p.get('calibration') is True for p in properties):
        check_ids.add('signal_model_complete_before_calibration')
    return check_ids


def resolve(plan, *, reading=None, registry=None, artifacts=None):
    """Return ``{nodes: {id: [checks]}, claims: {id: [checks]}}`` for any registered route.

    ``artifacts`` maps graph refs to retained document objects. Inherited claims retain
    all ancestor requirements; a label change never removes an artifact/lineage check.
    An unresolved operation or review term is a hard error, including on a dry plan.
    """
    reg = rp.registry() if registry is None else registry
    failures = conformance(registry=reg)
    if failures:
        raise ValueError('; '.join(failures))
    nodes, inputs, claims = rp._index(plan)
    per_node = {}
    for nid, node in nodes.items():
        operation = node.get('operation')
        if node.get('kind') == 'operation' and not operation:
            raise ValueError(f'unresolved route for {nid}: no operation')
        if operation and reg.get(operation) is None:
            raise ValueError(f'unresolved route {operation}')
        signature = reg.get(operation) if operation else None
        checks = set(signature['review']['checks']) if signature else set()
        if node.get('kind') == 'authored':
            checks.add('known_answer_tests')
        if node.get('fields') or (signature and signature['critical_fields']):
            checks.add('field_authority')
        stages = set(signature['stages']) if signature else set()
        checks |= _context_checks(plan, {nid}, documents(artifacts, {nid}), set(), set(), stages)
        per_node[nid] = sorted(checks)
    bases = rp.computed_bases(plan, reg)
    per_claim = {}
    for cid, claim in claims.items():
        refs = rp.ancestors(plan, cid) | {cid}
        docs = documents(artifacts, refs)
        checks = {check for ref in refs for check in per_node.get(ref, [])}
        checks -= {'acceptance_certificate', 'r5'}
        signatures = [reg[nodes[r]['operation']] for r in refs & set(nodes) if nodes[r].get('operation')]
        effects = {e for s in signatures for e in s['effects']}
        stages = {stage for s in signatures for stage in s['stages']}
        b = {row['element'] for row in bases[cid]}
        checks |= _context_checks(plan, refs, docs, effects, b, stages)
        # Include delivered and inherited artifacts, not only the final display template.
        edges = [e for e in plan.get('edges', []) if e['to']['ref'] in refs]
        kinds = {e['kind'] for e in edges} | {claim['deliverable']['artifact']} | {d.get('kind') for _, d in docs}
        has_limits = any(e.get('require', {}).get('limits') is True for e in edges) or any('limits' in d or 'mu95' in d or any(r.get('quantity') == 'cls-limit' for r in d.get('results', [])) for _, d in docs)
        if 'inference' in kinds:
            checks.add('fit_alarms')
        if has_limits:
            checks.add('limit_status')
        if 'document' in kinds:
            checks.add('prose')
        comparison = claim.get('comparison', {})
        compares = comparison.get('target', 'none') != 'none' or any(d.get('comparison_target') for _, d in docs)
        if compares or claim.get('kind') == 'agreement':
            checks |= {'agreement_target_declared', 'comparison_family_match', 'independent_reference'}
        if comparison.get('target') == 'published_figure':
            checks.add('figure_comparison')
        if 'patches_published_model' in effects:
            checks.add('likelihood_pairing')
        if 'reimplemented_statistical_model' in b and has_limits:
            checks.add('r5')
        if claim.get('statistic', {}).get('definition') is not None:
            checks.add('statistic_matches_claim')
        if claim.get('level') == 'observed':
            checks.add('observed_admissible')
        if claim.get('conventions', {}).get('basis_conversion') or any(p.get('basis_conversion') for p in _properties(plan, refs)):
            checks.add('basis_manifest')
        for row in bases[cid]:
            if row['element'] != 'simulated_acceptance':
                continue
            if row.get('level') == 'particle' and row.get('origin') == 'published':
                checks.add('routine_validation')
            elif row.get('level') in ('detector', 'reconstructed') and (has_limits or compares or 'inference' in kinds):
                anchor = any(d.get('acceptance_anchor') for _, d in docs) or any(p.get('acceptance_anchor') for p in _properties(plan, refs))
                if rp.withheld(reading or {}):
                    checks.add('reference_withheld')
                elif row.get('origin') in ('published', 'reimplemented') and anchor:
                    checks.add('acceptance_certificate')
                else:
                    checks.add('designed_selection_bundle')
                checks.add('per_bin_mc_precision')
        for check in checks:
            if check not in globals()['registry']() or not callable(evaluator(check)):
                raise ValueError(f'unresolved check {check} for {cid}')
        per_claim[cid] = sorted(checks)
    return {'nodes': per_node, 'claims': per_claim}



def _verify_pins(value, root):
    from ravel.validation.certificates import local_path, digest
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            rows.pin(value)
            if digest(local_path(root, value['path'])) != value['sha256']:
                raise ValueError('claim evidence pin differs from the retained artifact')
        for child in value.values():
            _verify_pins(child, root)
    elif isinstance(value, list):
        for child in value:
            _verify_pins(child, root)


def evaluate_check(check_id, payload, **context):
    """Compute one row. Missing or invalid raw evidence fails; a supplied status has no authority."""
    if check_id not in registry() or not callable(evaluator(check_id)):
        raise ValueError(f'unresolved check {check_id}')
    try:
        if not isinstance(payload, dict):
            raise ValueError('raw claim evidence must be an object')
        if context.get('root') is not None:
            _verify_pins(payload, context['root'])
        fn = evaluator(check_id)
        value = fn(payload) if check_id in rows.EVALUATORS else fn(payload, **context)
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, ZeroDivisionError) as exc:
        value = rows.result(False, 'missing or invalid evidence: ' + str(exc))
    return {'id': check_id, 'computed': True, **value}


def evaluate(plan, *, reading=None, artifacts=None, registry=None, **context):
    """Machine rows for S2 delivery consumers, scoped to each claim's exact lineage.

    Every retained payload is checked separately. A later passing record cannot hide
    an earlier violation. No payload for a required check yields a failure.
    """
    resolution = resolve(plan, reading=reading, registry=registry, artifacts=artifacts)
    results = []
    for cid, checks in resolution['claims'].items():
        refs = rp.ancestors(plan, cid) | {cid}
        docs = documents(artifacts, refs)
        claim = next(c for c in plan['claims'] if c['id'] == cid)
        for check in checks:
            payloads = [(ref, d['claim_evidence'][check]) for ref, d in docs if check in d.get('claim_evidence', {})]
            if not payloads:
                payloads = [(cid, {})]
            for ref, payload in payloads:
                effective = deepcopy(payload) if isinstance(payload, dict) else {}
                malformed = not isinstance(payload, dict)
                declared = {}
                for node in plan.get('nodes', []):
                    if node['id'] not in refs:
                        continue
                    for field in node.get('fields', []):
                        if field['pointer'] in ('/task/claim_checks/' + check, '/claim_checks/' + check):
                            if not isinstance(field['value'], dict):
                                raise ValueError('declared claim-check bounds must be an object')
                            for key, value in field['value'].items():
                                if key in declared and rp.canonical(declared[key]) != rp.canonical(value):
                                    raise ValueError('conflicting declared claim-check bounds')
                                declared[key] = value
                mismatch = any(key in effective and rp.canonical(effective[key]) != rp.canonical(value) for key, value in declared.items())
                effective.update(declared)
                row = evaluate_check(check, effective, plan=plan, claim=claim, documents=docs, reading=reading or {}, **context)
                if mismatch or malformed:
                    row.update(status='fail', detail='invalid raw payload' if malformed else 'delivered check bounds differ from the approved plan')
                results.append({**row, 'claim_id': cid, 'source_ref': ref})
    return results
