"""Shadow governance derivation beside the v1 gates (architecture §2.7.1, Stage 2 row 2-01).

``derive(reading, plan, registry, observed=None)`` computes the governance record that the
v2 intake would apply, from the reading, the request plan and the operation signatures:
lineage, bases, the kind floor, admissible levels, effects and minimum rungs, stage levels,
review checks, CHECK-IN 1 flags, review points, launch requirements, the deliverables
index, completion obligations and the label. ``diff(governance, contract)`` compares it
with the gates v1 applies to the same request (``required_stages`` and ``checkin_variant``
of the v1 contract), and ``join(stored, recomputed)`` is the monotone merge a gate would
apply between a stored record and a recomputed one.

This is a shadow: nothing here changes a v1 output. ``shadow`` reads, routes and drafts a
request exactly as v1 does, derives on deep copies, and checks that the v1 records are
byte-identical before and after. Nothing here approves compute or reads identity context.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

from ravel.validation import validate_request_plan as rp

SCHEMA_VERSION = 1
KIND = 'governance-shadow'
STATUS = 'shadow'
# The stage levels v1 states (validate_run_state.required_stages); v2 derives R for a stage a node runs.
REQUIRED = 'R'
DROPPED, TIGHTENED = 'dropped', 'tightened'
# Effects whose node is reviewed at a smoke waypoint before bulk execution.
REVIEWED_EFFECTS = ('generates_events', 'simulates_detector', 'executes_native', 'runs_authored_code',
                    'patches_published_model')
# Deliverables whose claims admit an observed level only with measured data in the lineage.
OBSERVED_ELEMENTS = ('observed_data', 'published_results', 'published_statistical_model')
MEASURED_SLOT = 'measured'


def canonical(value):
    return rp.canonical(value)


def sha256(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _module_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# --------------------------------------------------------------------------- derivation steps
def _lineage(plan, claims):
    """Claim id -> ancestors through edges, plus claims it inherits from and their ancestors."""
    direct = {cid: set(rp.ancestors(plan, cid)) for cid in claims}
    result = {}
    for cid, claim in claims.items():
        seen, stack = set(direct[cid]), list(claim.get('inherits') or ())
        visited = {cid}
        while stack:
            parent = stack.pop()
            if parent in visited or parent not in claims:
                continue
            visited.add(parent)
            seen |= direct[parent] | {parent}
            stack += list(claims[parent].get('inherits') or ())
        result[cid] = sorted(seen)
    return result


def _bases(plan, reg, lineage, observed):
    bases = rp.computed_bases(plan, reg)
    if observed:
        for cid in bases:
            for ref in lineage[cid]:
                for element in (observed.get(ref) or {}).get('basis', ()):
                    if not any(r['element'] == element for r in bases[cid]):
                        bases[cid].append({'element': element, 'via': [ref], 'observed': True})
    return bases


def _kind_floor(plan, claims, nodes, reg):
    rows = {}
    for cid, claim in claims.items():
        delivered = rp._delivered(plan, cid, nodes, reg)
        artifact = claim['deliverable']['artifact']
        admitted = rp.KIND_FLOOR.get(artifact)
        if any(kind == 'inference' and limits for kind, limits in delivered):
            admitted = rp.KIND_FLOOR['inference_with_limits'] if claim['kind'] in rp.KIND_FLOOR[
                'inference_with_limits'] else rp.KIND_FLOOR['inference']
        rows[cid] = {'artifact': artifact, 'admits': list(admitted) if admitted else None,
                     'ok': admitted is None or claim['kind'] in admitted}
    return rows


def _measured(plan, lineage_refs, nodes, inputs):
    """True when published or supplied measured values feed a node of the lineage through a measured slot."""
    for edge in plan['edges']:
        if edge['to']['ref'] in lineage_refs and edge['to']['slot'] == MEASURED_SLOT:
            return True
        source = inputs.get(edge['from']['ref'])
        if source and edge['to']['ref'] in lineage_refs and (
                source['provides']['require'].get('observed') is True
                or source['provides']['require'].get('contains_observed_data') is True):
            return True
    return False


def _levels(plan, claims, bases, lineage, nodes, inputs):
    rows = {}
    for cid, claim in claims.items():
        if claim['kind'] not in rp.STATISTIC_KINDS:
            admissible = ['not_applicable']
        else:
            elements = {r['element'] for r in bases[cid]}
            observed = bool(elements & set(OBSERVED_ELEMENTS)) or _measured(plan, set(lineage[cid]), nodes, inputs)
            admissible = ['observed', 'expected'] if observed else ['expected']
        rows[cid] = {'declared': claim['level'], 'admissible': admissible, 'ok': claim['level'] in admissible}
    return rows


def _effects(nodes, reg):
    rows = {}
    for nid, node in nodes.items():
        effects = sorted(rp._effects(node, reg)) if node['kind'] in ('operation', 'authored') else []
        compute = set(effects) & set(rp.COMPUTE_EFFECTS)
        rows[nid] = {'effects': effects, 'minimum_rung': 'smoke' if compute else 'none', 'rung': node['rung']}
    return rows


def _stages(nodes, reg):
    levels = {}
    for nid, node in sorted(nodes.items()):
        if node['status'] != 'available':
            continue
        for stage in sorted(rp._stages(node, reg)):
            levels.setdefault(stage, {'level': REQUIRED, 'via': []})['via'].append(nid)
    return levels


def _checks(plan, reg, nodes, claims, bases, lineage, *, reading=None):
    per_node = {}
    for nid, node in nodes.items():
        signature = reg.get(node['operation']) if node.get('operation') else None
        checks = list(signature['review']['checks']) if signature else []
        if node['kind'] == 'authored':
            checks.append('known_answer_tests')
        if signature is None and node['kind'] == 'operation':
            checks.append('unclassified_basis')
        per_node[nid] = sorted(set(checks))
    per_claim = {}
    for cid in claims:
        checks = set()
        for ref in lineage[cid]:
            checks |= set(per_node.get(ref, ()))
        if rp.certificate_relevant(bases[cid]):
            checks.add('acceptance_certificate')
        per_claim[cid] = sorted(checks)
    from ravel.validation.claim_checks import resolve
    resolved = resolve(plan, registry=reg, reading=reading)
    for scope, applied in (('nodes', per_node), ('claims', per_claim)):
        for ref, checks in resolved[scope].items():
            applied[ref] = list(checks)
    return per_node, per_claim


def _review(nodes, effects):
    points = []
    for nid in sorted(nodes):
        reviewed = sorted(set(effects[nid]['effects']) & set(REVIEWED_EFFECTS))
        if reviewed:
            points.append({'node': nid, 'kind': 'smoke_review', 'effects': reviewed})
    return {'minimum_policy': 'delivery' if nodes else 'none', 'points': points}


def _launch(nodes, effects, checkin1_flags):
    rows = {}
    compute = False
    for nid, node in sorted(nodes.items()):
        needs = effects[nid]['minimum_rung'] != 'none'
        compute = compute or needs
        rows[nid] = {'maximum_rung': node['rung'], 'go_required': needs, 'lease_required': needs}
    return {'nodes': rows, 'checkin1_required': compute or bool(checkin1_flags)}


def derive(reading, plan, registry=None, observed=None):
    """The shadow governance record of one reading and plan (§2.7.1 steps 1-14)."""
    reg = rp.registry() if registry is None else registry
    reading, plan = copy.deepcopy(reading), copy.deepcopy(plan)
    nodes, inputs, claims = rp._index(plan)
    lineage = _lineage(plan, claims)
    bases = _bases(plan, reg, lineage, observed)
    effects = _effects(nodes, reg)
    flags = rp.flags(reading, plan, reg)
    node_checks, claim_checks = _checks(plan, reg, nodes, claims, bases, lineage, reading=reading)
    used = sorted({n['operation'] for n in nodes.values() if n.get('operation') and reg.get(n['operation'])})
    return {
        'schema_version': SCHEMA_VERSION, 'kind': KIND, 'status': STATUS,
        'derivation_sha256': _module_sha256(),
        'signature_entries': {name: rp.entry_sha256(reg[name]) for name in used},
        'lineage': lineage,
        'bases': {cid: [{k: v for k, v in row.items() if k != 'via'} | {'via': sorted(row['via'])}
                        for row in rows] for cid, rows in bases.items()},
        'kind_floor': _kind_floor(plan, claims, nodes, reg),
        'levels': _levels(plan, claims, bases, lineage, nodes, inputs),
        'effects': effects,
        'stages': _stages(nodes, reg),
        'checks': {'nodes': node_checks, 'claims': claim_checks},
        'checkin1': {'flags': [{'id': f'F{i}', **row} for i, row in enumerate(flags, 1)]},
        'waypoints': [w['id'] for w in plan['waypoints']],
        'review': _review(nodes, effects),
        'launch': _launch(nodes, effects, flags),
        'layout': {cid: claim['deliverable']['artifact'] for cid, claim in sorted(claims.items())},
        'completion': sorted(row['obligation_id'] for row in plan['coverage']),
        'label': dict(plan['label']),
    }


# --------------------------------------------------------------------------- comparison with v1
def applied(contract):
    """The gates v1 applies to a contract: stage levels and the CHECK-IN 1 variants."""
    from ravel.validation.validate_checkin import checkin_variant
    from ravel.validation.validate_run_state import required_stages
    stages = required_stages(contract)
    variant = checkin_variant(contract)
    return {'key': stages['key'], 'levels': dict(stages['levels']), 'checkin1': dict(stages['checkin1']),
            'variants': list(variant['allowed']) if variant['allowed'] is not None else None}


# Requested-stage names (the plan's) to the v1 lifecycle stage keys they correspond to. Stages with no
# v1 lifecycle key (model derivation, spectrum, figure, output template) are compared in Stage 2 row 2-06.
STAGE_KEYS = {'generation': 'generation', 'shower': 'generation', 'lhe-transform': 'generation',
              'detector': 'generation', 'analysis': 'analysis', 'statistic': 'statistics'}


def diff(governance, contract):
    """Rows where the shadow governance and the v1 gates differ, each tightened or dropped."""
    v1 = applied(contract)
    rows = []
    v2_keys = {}
    for stage, row in governance['stages'].items():
        key = STAGE_KEYS.get(stage)
        if key is not None:
            v2_keys.setdefault(key, []).append(stage)
    for key, level in sorted(v1['levels'].items()):
        if key in v2_keys and level != REQUIRED:
            rows.append({'aspect': f'stage:{key}', 'v1': level, 'v2': REQUIRED, 'direction': TIGHTENED,
                         'via': sorted(v2_keys[key])})
    for key in sorted(set(v2_keys) - set(v1['levels'])):
        rows.append({'aspect': f'stage:{key}', 'v1': None, 'v2': REQUIRED, 'direction': TIGHTENED,
                     'via': sorted(v2_keys[key])})
    v2_checkin = governance['launch']['checkin1_required']
    if v2_checkin != v1['checkin1']['required']:
        rows.append({'aspect': 'checkin1', 'v1': v1['checkin1']['required'], 'v2': v2_checkin,
                     'direction': TIGHTENED if v2_checkin else DROPPED})
    return {'v1': v1, 'rows': rows}


def join(stored, recomputed):
    """The monotone merge of a stored and a recomputed record: requirements are kept or added, never dropped.

    Returns ``(joined, report)``; ``report`` lists each requirement the recomputation would
    drop (kept) and each one it adds (tightened after approval).
    """
    joined = copy.deepcopy(recomputed)
    report = []
    for key in ('stages',):
        for stage, row in stored.get(key, {}).items():
            if stage not in joined[key]:
                joined[key][stage] = copy.deepcopy(row)
                report.append({'aspect': f'stage:{stage}', 'direction': DROPPED, 'kept': True})
        for stage in recomputed.get(key, {}):
            if stage not in stored.get(key, {}):
                report.append({'aspect': f'stage:{stage}', 'direction': TIGHTENED})
    for scope in ('nodes', 'claims'):
        old, new = stored.get('checks', {}).get(scope, {}), joined['checks'][scope]
        for ref, checks in old.items():
            merged = sorted(set(checks) | set(new.get(ref, ())))
            for check in sorted(set(checks) - set(new.get(ref, ()))):
                report.append({'aspect': f'check:{ref}:{check}', 'direction': DROPPED, 'kept': True})
            new[ref] = merged
        for ref, checks in recomputed['checks'][scope].items():
            for check in sorted(set(checks) - set(old.get(ref, ()))):
                report.append({'aspect': f'check:{ref}:{check}', 'direction': TIGHTENED})
    old_launch = stored.get('launch', {})
    if old_launch.get('checkin1_required') and not joined['launch']['checkin1_required']:
        joined['launch']['checkin1_required'] = True
        report.append({'aspect': 'checkin1', 'direction': DROPPED, 'kept': True})
    for nid, row in old_launch.get('nodes', {}).items():
        current = joined['launch']['nodes'].get(nid)
        if current is None:
            continue
        for key in ('go_required', 'lease_required'):
            if row.get(key) and not current[key]:
                current[key] = True
                report.append({'aspect': f'launch:{nid}:{key}', 'direction': DROPPED, 'kept': True})
    return joined, report


# --------------------------------------------------------------------------- the shadow run
def v1_records(prompt):
    """The v1 records of one request: reading, contract, plan, plan-check errors, flags and label."""
    from ravel.workflow import derived_label, request_plan, request_reading, route_prompt
    reading = request_reading.document(prompt)
    contract = route_prompt.route(prompt)
    plan = request_plan.draft(reading, contract)
    return {'reading': reading, 'contract': contract, 'plan': plan,
            'plan_errors': rp.check(reading, plan), 'flags': rp.flags(reading, plan),
            'label': derived_label.derive(reading, plan)}


def shadow(prompt, records=None):
    """Derive beside v1 for one request; refuse if the derivation changed any v1 record."""
    records = v1_records(prompt) if records is None else records
    before = canonical(records)
    governance = derive(records['reading'], records['plan'])
    comparison = diff(governance, records['contract'])
    if canonical(records) != before:
        raise RuntimeError('the shadow derivation changed a v1 record')
    return {'prompt_sha256': records['reading']['prompt_sha256'], 'governance': governance,
            'governance_sha256': sha256(governance), 'diff': comparison}


def battery(prompts):
    """Shadow records for a list of prompts, with a summary of the diff rows."""
    results = [shadow(p) for p in prompts]
    counts = {}
    for result in results:
        for row in result['diff']['rows']:
            key = f'{row["aspect"]}:{row["direction"]}'
            counts[key] = counts.get(key, 0) + 1
    return {'cases': len(results), 'with_diff': sum(1 for r in results if r['diff']['rows']),
            'rows': dict(sorted(counts.items())), 'results': results}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel governance-shadow',
                                 description='Shadow v2 governance derivation beside the v1 gates; changes nothing.')
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--prompt', help='one request text')
    group.add_argument('--prompts', type=Path, help='a JSON list of request texts')
    ap.add_argument('--summary', action='store_true', help='print only the diff summary')
    args = ap.parse_args(argv)
    prompts = [args.prompt] if args.prompt is not None else json.loads(args.prompts.read_text())
    if not isinstance(prompts, list) or not all(isinstance(p, str) for p in prompts):
        raise SystemExit('--prompts must hold a JSON list of strings')
    result = battery(prompts)
    if args.summary:
        result = {k: v for k, v in result.items() if k != 'results'}
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
