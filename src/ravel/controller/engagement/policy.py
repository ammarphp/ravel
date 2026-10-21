"""Pure tier selection and conservative, duty-preserving seat compilation."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import math

from .records import TIERS, EngagementRefused, data, digest
from .facts import action_of


def load_policy():
    policy = data('policy.json')
    if policy.get('sha256') != digest({k: v for k, v in policy.items() if k != 'sha256'}):
        raise EngagementRefused('installed engagement policy digest mismatch')
    return policy


def tier(facts, policy):
    """Return tier, fact minima and source-citing reasons; unknown is always full."""
    minima, reasons = {}, []
    for name in ('route', 'deliverables', 'consequence', 'compute', 'novelty', 'special'):
        row = facts.get(name, {})
        value = row.get('value')
        checked = row.get('checker', '').startswith('code') and bool(row.get('source'))
        index = 2
        if checked:
            if name == 'deliverables' and type(value) is int and value >= 0:
                index = 0 if value <= policy['claim_limits']['lean'] else 1 if value <= 6 else 2
            elif name == 'special' and isinstance(value, list):
                index = max((policy['special'].get(v, 2) for v in value if isinstance(v, str)), default=0)
                if any(not isinstance(v, str) for v in value):
                    index = 2
            elif name != 'special' and isinstance(value, str):
                index = policy['tier_rules'].get(name, {}).get(value, 2)
        minima[name] = TIERS[index]
        reasons.append({'fact': name, 'value': deepcopy(value), 'minimum_tier': TIERS[index],
                        'source': row.get('source', 'missing'), 'checker': row.get('checker', 'unknown'),
                        'rule': name if checked and value is not None else 'unknown-means-complex'})
    chosen = max(TIERS.index(v) for v in minima.values())
    return {'tier': TIERS[chosen], 'minimum_tiers': minima, 'reasons': reasons,
            'sha256': digest({'facts': facts, 'policy': policy['sha256'], 'tier': TIERS[chosen]})}


def raise_only(computed, requested):
    """A minimum or raise applies only upwards; a lower value never lowers or aborts the decision."""
    if requested is None:
        return computed
    if requested not in TIERS:
        raise EngagementRefused('unknown engagement tier requested: ' + repr(requested))
    return TIERS[max(TIERS.index(computed), TIERS.index(requested))]


def role_cards():
    from ravel.workflow.role_registry import all_cards, registry_document
    cards = {c['id']: c for c in all_cards()}
    for alias, target in registry_document().get('aliases', {}).items():
        if target in cards:
            cards[alias] = cards[target]
    return cards


def declared_seats(plan, cards):
    seats = []
    for step in plan.get('steps', []):
        role = step.get('role')
        reviewers = list(step.get('review', [])) + list(cards.get(role, {}).get('reviewed_by', []))
        for reviewer in sorted(set(reviewers)):
            seats.append({'key': f"step:{step['id']}:{reviewer}", 'step_id': step['id'],
                          'role': reviewer, 'category': 'step',
                          'step': {**deepcopy(step), 'role': reviewer, 'kind': 'review'}})
        if role in ('integrity-auditor', 'physics-critic') and step.get('kind') == 'review':
            seats.append({'key': f"producer:{step['id']}:{role}", 'step_id': step['id'], 'role': role,
                          'category': 'integrity' if role == 'integrity-auditor' else 'attack',
                          'step': deepcopy(step)})
    from ravel.controller.review_seats import canonical_role, review_seat_counts, review_point_bindings
    for checkin in plan.get('checkins', []):
        counts = review_seat_counts(plan, checkin['id'])
        roles = [r['role'] if isinstance(r, dict) else r for r in checkin.get('seats', [])]
        spellings = {}
        for declared in roles:
            spellings.setdefault(canonical_role(declared), declared)
        for role, spelling in spellings.items():
            count = counts.get(role, 1)
            for n in range(1, count + 1):
                identity = spelling + (f'.{n}' if n > 1 else '')
                descriptor = {'key': f"checkin:{checkin['id']}:{identity}",
                              'step_id': checkin['id'], 'role': role, 'category': checkin['id'],
                              'step': {'id': checkin['id'], 'kind': 'review', 'role': role,
                                       'checkin': checkin['id'], 'instruction_sources': plan.get('instruction_sources', [])}}
                purpose = {'checkin1': 'plan', 'checkin2': 'waypoint', 'checkin3': 'final'}.get(checkin['id'])
                bindings = review_point_bindings(plan, purpose, role, n)
                if bindings:
                    descriptor['step']['parameters'] = {'review_points': bindings}
                if count > 1:
                    descriptor.update(n=n, required_count=count)
                seats.append(descriptor)
    return seats


def _constraints(card):
    independence = card.get('independence', {})
    sees = card.get('sees', {})
    result = {'fresh_session': bool(independence.get('fresh_session')),
              'distinct_actor_from': sorted(set(independence.get('distinct_actor_from', []))),
              'forbidden_inputs': sorted(set(sees.get('forbidden_inputs', []) + card.get('knowledge', {}).get('forbidden', []))),
              'required_inputs': sorted(set(sees.get('required_inputs', []))),
              'blind': bool(independence.get('blind') or sees.get('blind') or card.get('blind'))}
    for folded in card.get('folded_cards', []):
        other = _constraints(folded)
        for field in ('distinct_actor_from', 'forbidden_inputs', 'required_inputs'):
            result[field] = sorted(set(result[field]) | set(other[field]))
        result['fresh_session'] |= other['fresh_session']
        result['blind'] |= other['blind']
    return result


def _carried_roles(card):
    yield card.get('id')
    for folded in card.get('folded_cards', []):
        yield from _carried_roles(folded)


def fold_constraints(target, folded):
    a, b = _constraints(target), _constraints(folded)
    merged = {k: sorted(set(a[k] + b[k])) for k in ('distinct_actor_from', 'forbidden_inputs', 'required_inputs')}
    merged['fresh_session'] = a['fresh_session'] or b['fresh_session']
    merged['blind'] = a['blind'] or b['blind']
    # One actor carries every folded role, so no carried role may be one the union must stay distinct from.
    carried = set(_carried_roles(target)) | set(_carried_roles(folded))
    if (carried & set(merged['distinct_actor_from'])
            or set(merged['forbidden_inputs']) & set(merged['required_inputs'])
            or (merged['blind'] and target.get('blind_capable') is False)):
        return None
    return merged


def _constraint_card(seat):
    """An internal constraint union, never an instruction catalogue card."""
    result = deepcopy(seat['card'])
    result['folded_cards'] = deepcopy(seat['folded_cards'])
    constraints = seat['constraints']
    result['independence'] = {**result.get('independence', {}),
                              **{k: deepcopy(constraints[k]) for k in
                                 ('fresh_session', 'distinct_actor_from', 'blind')}}
    result['sees'] = {**result.get('sees', {}),
                      **{k: deepcopy(constraints[k]) for k in ('forbidden_inputs', 'required_inputs', 'blind')}}
    return result


def _packet_step(seat, scope):
    """Carry folded duties beside the unchanged card in the pinned step bytes."""
    step = deepcopy(seat['step'])
    step['engagement'] = {**deepcopy(scope), 'items': deepcopy(seat['items']),
                          'folded_cards': deepcopy(seat['folded_cards']),
                          'folded_manifests': deepcopy(seat['manifests'][1:]),
                          'constraints': deepcopy(seat['constraints'])}
    return step


def _registered_operation_review(seat, plan):
    """Source evidence for a registered producer's own mandatory reviewer, never an extra seat."""
    if seat['category'] != 'step':
        return None
    originals = [step for step in plan.get('steps', []) if step['id'] == seat['step_id']]
    if len(originals) != 1:
        return None
    producer = originals[0]
    from ravel.controller.step import operations
    from ravel.workflow import role_registry
    signature = operations.signatures().get(producer.get('operation'))
    if signature is None:
        return None
    try:
        if operations.executor_errors(producer, signature):
            return None
        card = role_registry.load(producer.get('role'))
    except (KeyError, TypeError, ValueError):
        return None
    if seat['role'] not in card.get('reviewed_by', []):
        return None
    return {'source': 'registered_operation_producer_reviewed_by', 'operation': producer['operation'],
            'producer_role': card['id'], 'reviewer': seat['role'], 'card_sha256': digest(card)}


def seat_plan(plan, selected_tier, policy=None, *, cards=None, instructions=None, projection=False):
    policy = policy or load_policy()
    if selected_tier not in TIERS:
        raise EngagementRefused('unknown tier')
    cards = role_cards() if cards is None else cards
    if instructions is None:
        from ravel.controller import instructions
    route = (plan.get('route') or {}).get('id', plan.get('id', 'judgment'))
    # Abstract cost-model templates have no approved grid; retain their full upper bound.
    scan_review = None if projection else scan_declaration(plan, selected_tier)
    seats = declared_seats(plan, cards)
    if scan_review:
        declared = []
        for seat in seats:
            population = scan_review['steps'].get(seat['step_id'])
            if seat['category'] == 'step' and population is not None:
                if not population['review_point_ids']:
                    continue
                seat['point_ids'] = deepcopy(population['review_point_ids'])
            declared.append(seat)
        seats = declared
    claims = [d.get('id', f'claim-{i}') for i, d in enumerate(plan.get('deliverables', []))]
    if len(claims) != len(set(claims)):
        raise EngagementRefused('duplicate deliverable identity')
    governed = route not in policy['no_review_routes']
    if not governed:
        result = {'seats': [], 'bindings': {}, 'actions': {}, 'errors': [], 'authority_nodes': [],
                  'rdj_cases': [], 'r3_authority': [], 'attacks_required': 0, 'claim_coverage': {}}
        return {**result, 'sha256': digest(result)}
    if selected_tier == 'lean' and len(claims) > policy['claim_limits']['lean'] and not projection:
        raise EngagementRefused('lean claim coverage exceeded')
    existing = {s['key'] for s in seats}
    def ensure(key, role, category):
        if key not in existing:
            existing.add(key)
            step = {'id': category, 'kind': 'review', 'role': role,
                    'instruction_sources': plan.get('instruction_sources', [])}
            if category in ('checkin1', 'checkin2', 'checkin3'):
                step['checkin'] = category
            if category == 'attack':
                step['protocols'] = ['P8']
            seats.append({'key': key, 'role': role, 'step_id': category, 'category': category,
                          'step': step, 'floor': True})
    ensure('checkin:checkin1:plan-critic', 'plan-critic', 'checkin1')
    # Fixed review floor exists independently of a route's incompletely declared roster.
    for role in policy['final_verification']['full']:
        ensure('checkin:checkin3:' + role, role, 'checkin3')
    if not any(s['category'] == 'attack' for s in seats):
        ensure('floor:attack:physics-critic', 'physics-critic', 'attack')
    if not any(s['category'] == 'integrity' for s in seats):
        ensure('floor:integrity:integrity-auditor', 'integrity-auditor', 'integrity')
    for i in range(1, math.ceil(len(claims) / 6)):
        ensure(f'floor:claims:{i}', 'skeptical-verifier', 'checkin3')
    all_seats, errors = {}, []
    rules = policy['seat_plans'].get(route, {})
    for seat in seats:
        role = seat['role']
        if role not in cards:
            raise EngagementRefused('unknown seat role kept separate: ' + role)
        card = deepcopy(cards[role])
        seat['step']['role'] = card['id']
        manifest = instructions.manifest(seat['step'], card)
        items = [{**deepcopy(item), 'source_item_id': item['id'], 'source_seat': seat['key'],
                  'id': seat['key'] + '/' + item['id']}
                 for item in instructions.reviewer_items(manifest, card)]
        seat.update(card=card, folded_roles=[], folded_cards=[], source_seats=[seat['key']], items=items,
                    manifests=[manifest], constraints=_constraints(card), conditional=None)
        # Template expansion maps back only through an explicit compiler template_id.
        lookup = seat['key']
        template_id = seat['step'].get('template_id')
        if template_id:
            lookup = lookup.replace(':' + seat['step_id'] + ':', ':' + template_id + ':')
        mandatory = seat.get('required_count', 1) > 1 or any(
            isinstance(binding.get('point', {}).get('row'), str)
            and binding['point'].get('blocking') is True
            and binding['point'].get('mode') in ('specialist', 'voting', 'advisory')
            for binding in (seat['step'].get('parameters') or {}).get('review_points', []))
        if mandatory:
            seat['mandatory_review_point'] = True
        classified = ({tier: 'keep' for tier in TIERS} if mandatory else
                      rules.get(lookup) or policy.get('dynamic_seat_roles', {}).get(route, {}).get(role))
        if classified is None:
            source = _registered_operation_review(seat, plan)
            if source is not None:
                classified = {tier: 'keep' for tier in TIERS}
                seat['classification_source'] = source
        if classified is None and seat['category'] in ('checkin2', 'checkin3'):
            # Installed phase-compatible policy roles keep every duty at every tier,
            # including dynamically declared specialists on fixed routes.
            from ravel.workflow import review_points, spawn_rows
            if seat['category'] == 'checkin2':
                applicable_roles = {r if isinstance(r, str) else r['role']
                                    for row in [*review_points._catalogue()['rows'], *spawn_rows.catalogue()['rows']]
                                    if row['gate'] == 'checkin2_accept'
                                    and row['mode'] in review_points.CONTROLLER_SEAT_MODES for r in row['roles']}
            else:
                applicable_roles = {r if isinstance(r, str) else r['role']
                                    for row in [*review_points._catalogue()['rows'], *spawn_rows.catalogue()['rows']]
                                    if any(review_points._weighs(row, gate, {}) for gate in review_points.CONTROLLER_FINAL_GATES)
                                    and row['mode'] in review_points.CONTROLLER_SEAT_MODES for r in row['roles']}
            if role in applicable_roles:
                classified = {tier: 'keep' for tier in ('lean', 'standard', 'full')}
        if classified is None and not seat.get('floor'):
            errors.append('unclassified seat kept: ' + seat['key'])
        seat['rule'] = (classified or {'lean': 'keep', 'standard': 'keep', 'full': 'keep'})[selected_tier]
        all_seats[seat['key']] = seat
    final_key = 'checkin:checkin3:skeptical-verifier'
    attack_key = next(s['key'] for s in seats if s['category'] == 'attack')
    # Finalize every item and constraint before probing a union. Nothing added
    # after an accepted probe may increase its packet or change its independence.
    coverage = {}
    verifiers = [s for s in all_seats.values() if s['category'] == 'checkin3' and s['role'] == 'skeptical-verifier']
    producers = {s['role'] for s in plan.get('steps', []) if s.get('role')}
    for i, claim in enumerate(claims):
        seat = verifiers[i // 6]
        coverage[claim] = seat['key']
        seat['items'].append({'id': 'claim:' + claim, 'kind': 'claim', 'claim_id': claim})
        seat['constraints']['fresh_session'] = True
        seat['constraints']['distinct_actor_from'] = sorted(set(seat['constraints']['distinct_actor_from']) | producers)
    attack = all_seats[attack_key]
    attack['constraints']['fresh_session'] = True
    attack['constraints']['distinct_actor_from'] = sorted(set(attack['constraints']['distinct_actor_from']) | producers)
    attack['attacks_required'] = 3
    attack['attacks_before_verdict'] = True
    attack['items'] += [{'id': f'attack:{i}', 'kind': 'attack', 'requires': ['written', 'tested', 'before_verdict']}
                        for i in range(1, 4)]
    active = deepcopy(all_seats)
    bindings, actions = {}, {}
    claim_steps = {d.get('step') for d in plan.get('deliverables', [])}
    waypoint_steps = [s['id'] for s in plan.get('steps', []) if s.get('waypoint')]
    ordered = [s['id'] for s in plan.get('steps', [])]
    for key, original in all_seats.items():
        original = active[key]
        target = None
        category, role = original['category'], original['role']
        step = original['step']
        fixed = ((step.get('parameters') or {}).get('phase') == 'prepare' or category == 'checkin1'
                 or (route == 'manuscript' and role == 'integrity-auditor')
                 or (category in ('attack', 'integrity') and bool(step.get('outputs')))
                 or 'point_ids' in original or original.get('mandatory_review_point')
                 or original.get('required_count', 1) > 1)
        action = original['rule']
        if original.get('floor'):
            action = 'tiered'
        if not fixed and selected_tier != 'full' and action != 'keep':
            if category in ('attack', 'integrity'):
                target = final_key if selected_tier == 'lean' else None
            elif category == 'checkin3' and key != final_key and not key.startswith('floor:claims:'):
                target = final_key
            elif category == 'step':
                if selected_tier == 'lean' or original['step_id'] not in claim_steps or role == 'physics-critic':
                    if role == 'physics-critic' and selected_tier == 'standard':
                        target = attack_key
                    else:
                        # The next checkpoint in execution order; never a prior waypoint.
                        pos = ordered.index(original['step_id'])
                        future = [w for w in waypoint_steps if ordered.index(w) >= pos]
                        candidates = [s for s in seats if s['category'] == 'checkin2'] if future else []
                        target = candidates[0]['key'] if candidates else final_key
            elif category == 'checkin2':
                candidates = [s for s in seats if s['category'] == 'checkin2']
                target = candidates[0]['key'] if candidates and candidates[0]['key'] != key else None
        targets = [target] if target and target != key and target in active else []
        if target == final_key and category == 'step':
            # A final verifier may have to stay distinct from this role. An
            # already required final seat of the same role can carry the review
            # at the same checkpoint, with its complete duties and constraints.
            compatible = [s['key'] for s in active.values() if s['category'] == 'checkin3'
                          and s['role'] == role and s['key'] != key and not s['conditional']]
            if len(compatible) == 1 and compatible[0] not in targets:
                targets.append(compatible[0])
        folded = False
        for target in targets:
            constraints = fold_constraints(_constraint_card(active[target]), _constraint_card(original))
            if constraints is not None:
                merged = deepcopy(active[target])
                merged['constraints'] = constraints
                merged['folded_roles'] += [role] + original['folded_roles']
                merged['folded_cards'] += [deepcopy(original['card'])] + deepcopy(original['folded_cards'])
                merged['source_seats'] += original['source_seats']
                merged['items'] += deepcopy(original['items'])
                merged['manifests'] += deepcopy(original['manifests'])
                if original.get('attacks_required'):
                    merged['attacks_required'] = original['attacks_required']
                    merged['attacks_before_verdict'] = original['attacks_before_verdict']
                # The instruction builder packs the complete union. Refusal keeps this seat separate, with no truncation.
                try:
                    union_step = _packet_step(merged, policy['packet_scope'][selected_tier])
                    union_manifest = instructions.manifest(union_step, merged['card'])
                    instructions.packet(union_manifest, merged['card'], union_step, [])
                except (ValueError, RuntimeError) as exc:
                    original['retained_reason'] = 'fold packet refused: ' + str(exc)
                else:
                    active[target] = merged
                    del active[key]
                    bindings[key] = target
                    actions[key] = 'fold:' + target
                    folded = True
                    break
        if folded:
            continue
        actions[key] = 'keep'
        bindings[key] = key
    # Resolve transitive folds and transfer their exact item unions.
    for key in bindings:
        seen = set()
        target = bindings[key]
        while target in bindings and bindings[target] != target:
            if target in seen:
                raise EngagementRefused('cyclic seat folding')
            seen.add(target)
            target = bindings[target]
        bindings[key] = target
    coverage = {claim: bindings[key] for claim, key in coverage.items()}
    # A standard decider is conditional, but its duties already reach the verifier.
    if selected_tier == 'standard':
        conditional = deepcopy(all_seats['checkin:checkin3:physics-decider'])
        conditional['key'] = 'conditional:disagreement:physics-decider'
        conditional['conditional'] = 'attacker_verifier_disagree'
        active[conditional['key']] = conditional
    for seat in active.values():
        seat['step'] = _packet_step(seat, policy['packet_scope'][selected_tier])
    rdj, authority = [], []
    try:
        from ravel.controller.judgment import classify
    except ImportError:
        classify = lambda action: 'R3'
    for step in plan.get('steps', []):
        if step.get('kind') == 'decide':
            consequence = classify(action_of(step))
            if consequence not in ('R0', 'R1'):
                rdj.append({'step_id': step['id'], 'before_effect': True})
            if consequence not in ('R0', 'R1', 'R2'):
                authority.append(step['id'])
    result = {'seats': list(active.values()), 'bindings': bindings, 'actions': actions, 'errors': errors,
              'authority_nodes': sorted({c['id'] for c in plan.get('checkins', [])} | {'checkin1', 'checkin3'}),
              'rdj_cases': rdj, 'r3_authority': authority, 'attacks_required': 3,
              'claim_coverage': coverage}
    if scan_review:
        result['scan_review'] = scan_review
    result['sha256'] = digest(result)
    return result


def deduplicate(seats):
    """Share credit only for an exact role, subject, attempt, constraints and duties."""
    kept, bindings, seen = [], {}, {}
    for seat in seats:
        identity = (seat['role'], seat.get('subject_sha256'), seat.get('attempt'), digest(seat.get('constraints')),
                    digest(seat.get('items', [])))
        bound = bool(identity[1]) and type(identity[2]) is int and identity[2] >= 1
        if bound and identity in seen:
            bindings[seat['key']] = seen[identity]
        else:
            kept.append(deepcopy(seat))
            bindings[seat['key']] = seat['key']
            if bound:
                seen[identity] = seat['key']
    return kept, bindings


def scan_declaration(plan, selected_tier):
    """Declare review populations before dispatch, seeded by the immutable scientific plan.

    The declaration lives in the seat plan, hence in the applied plan's digest. It never
    changes the grid or producer steps. New anomalies require a newly pinned plan and review.
    """
    from ravel.controller.routes.analysis import scan

    grid = scan.approved_grid(plan)
    grouped = scan.point_steps(plan)
    steps = plan.get('steps', [])
    if grid is None and not grouped and not any(s.get('points') for s in steps):
        return None
    seed = plan.get('sha256')
    if seed != digest({k: v for k, v in plan.items() if k != 'sha256'}):
        raise EngagementRefused('scan review needs the current scientific plan digest')
    populations, local = [], {}

    def declare(identity, points, anomalies, members):
        if (not isinstance(points, list) or not points
                or any(not isinstance(p, str) or not p for p in points)
                or not isinstance(anomalies, list)
                or any(not isinstance(p, str) for p in anomalies)):
            raise EngagementRefused('scan review population is missing or invalid')
        reviewed = scan_sample(points, selected_tier, seed, anomalies)
        populations.append({'id': identity, 'point_ids': sorted(points),
                            'review_point_ids': reviewed, 'anomalies': sorted(set(anomalies))})
        for step_id, point_ids in members.items():
            local[step_id] = {'point_ids': list(point_ids),
                              'review_point_ids': sorted(set(point_ids) & set(reviewed))}

    if grid is not None or grouped:
        if scan.membership_errors(plan):
            raise EngagementRefused('scan review requires every approved point planned exactly once')
        points = [p['id'] for p in grid['points']]
        declare('grid', points, (plan.get('parameters') or {}).get('scan_anomalies', []),
                {rows[0]['id']: [point] for point, rows in grouped.items()})
    for step in steps:
        if step.get('points') and step['id'] not in local:
            declare(step['id'], step['points'], step.get('scan_anomalies', []),
                    {step['id']: step['points']})
    return {'seed_sha256': seed, 'tier': selected_tier, 'populations': populations, 'steps': local}


def scan_sample(points, selected_tier, plan_sha256, anomalies=()):
    if selected_tier not in ('standard', 'full'):
        raise EngagementRefused('scan review requires at least standard')
    if len(points) != len(set(points)) or not set(anomalies) <= set(points):
        raise EngagementRefused('scan population or anomaly outside declared points')
    if len(plan_sha256) != 64 or any(c not in '0123456789abcdef' for c in plan_sha256):
        raise EngagementRefused('scan sample needs the plan digest')
    n = min(len(points), math.ceil((2 if selected_tier == 'full' else 1) * math.sqrt(len(points))))
    ordered = sorted(points, key=lambda p: (sha256((plan_sha256 + ':' + p).encode()).hexdigest(), p))
    return sorted(set(ordered[:n]) | set(anomalies))


def check_scan(points, receipts, reviewed, selected_tier, plan_sha256, anomalies=()):
    expected = set(scan_sample(points, selected_tier, plan_sha256, anomalies))
    observed = [r.get('point_id') for r in receipts if r.get('governed') is True and r.get('receipt_id')]
    return {'missing_receipts': sorted(set(points) - set(observed)),
            'surplus_receipts': sorted(set(observed) - set(points)),
            'duplicate_receipts': sorted(p for p in set(observed) if observed.count(p) != 1),
            'missing_reviews': sorted(expected - set(reviewed))}


def review_errors(seat, record):
    """Structural per-item coverage and written/tested attacks; credit stays with its owner."""
    errors = []
    required = {i['id'] for i in seat['items']}
    verdicts = record.get('item_verdicts', [])
    present = [v.get('item') for v in verdicts if isinstance(v, dict)]
    if set(present) != required or len(present) != len(set(present)):
        errors.append('folded item verdict population differs from the seat')
    for item in verdicts:
        if (not isinstance(item, dict) or item.get('verdict') not in ('pass', 'fail', 'unresolved', 'not_applicable')
                or not item.get('evidence')):
            errors.append('each folded item needs a verdict and evidence')
    if seat.get('attacks_required'):
        attacks = record.get('attacks', [])
        if (len(attacks) < seat['attacks_required']
                or len({a.get('id') for a in attacks if isinstance(a, dict)}) != len(attacks)):
            errors.append('three distinct written attacks are required before the verdict')
        for attack in attacks:
            if (not isinstance(attack, dict) or not all(attack.get(k) for k in ('id', 'attack', 'test', 'evidence'))
                    or attack.get('before_verdict') is not True):
                errors.append('each attack must be written and tested before the verdict')
    return sorted(set(errors))


def conditional_seats(seats, reviews):
    """Unknown, uncredited or mismatched subjects cannot suppress the decider."""
    attack, verifier = reviews.get('attacker', {}), reviews.get('verifier', {})
    comparable = (attack.get('credited') is True and verifier.get('credited') is True
                  and attack.get('subject_sha256') and attack.get('subject_sha256') == verifier.get('subject_sha256')
                  and attack.get('verdict') in ('accept', 'revise', 'unresolved')
                  and verifier.get('verdict') in ('accept', 'revise', 'unresolved'))
    disagree = not comparable or attack['verdict'] != verifier['verdict']
    return [deepcopy(s) for s in seats if not s.get('conditional') or disagree]
