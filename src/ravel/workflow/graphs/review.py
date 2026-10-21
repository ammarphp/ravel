"""Review points on the graph substrate: ``review.points`` and its item graph ``review.item``.

    guard ─► derive(review_points.pending at one ``when.at``) ─► fanout(item packets)
      ─► map(Send: one item per (point, role, n) of each ready point) ─► join ─► divergence ─► guard
    completed dispatch:        A finding ─► correction_required (evidence retained)
                               human approver ─► interrupt(checkin2|3_response) ─► gate
                               otherwise ─► gate(<point gate>)

The decision gate owns derivation, receipt counting and the gate providers; this graph only
executes them. Every round re-derives ``pending``, so a re-run dispatches only the
role counts that still lack credited receipts ("k of N"). A reviewer that
depends on other points (the skeptical verifier, the decider) receives their
evidence-bearing findings, never a verdict. A human resume proves nothing: the
gate after it requires the run's ``science.approve`` record.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import TypedDict

from .. import graph_nodes as nodes, graph_registry, graph_substrate
from ..agent_graph import GraphError
from ..state_io import atomic_json, read_json

POINTS = 'review.points'
ITEM = 'review.item'
MAX_ROUNDS = 6
ITEM_BUDGETS = {'max_turns': 60, 'max_wall_seconds': 3600, 'max_broker_calls': 400, 'max_cost_usd': None}
# Review rows 1, 4-8, 10, 11 and 14 use the panel dispatcher. Investigation,
# decision and protocol rows retain their dedicated providers and graphs.
ROLES = ('analysis-author', 'discrepancy-attributor', 'figure-critic', 'integrity-auditor', 'normalization-auditor',
         'object-selection-mapper', 'physics-critic', 'physics-decider', 'plan-critic', 'skeptical-verifier',
         'trap-auditor')
# Every seat the item graph can dispatch: the core panel plus each specialist seat the conditional
# staffing catalogue adds. A finite source vocabulary keeps the graph's node declarations statically
# enumerable; the test suite checks it against the catalogue, and dispatch_roles() routes installed seats.
DISPATCH_ROLES = ('analysis-author', 'assumption-auditor', 'comparative-reviewer', 'discrepancy-attributor',
                  'figure-critic', 'higgs-combination-reviewer', 'higgs-theory-uncertainty-auditor',
                  'integrity-auditor', 'model-critic', 'normalization-auditor', 'object-selection-mapper',
                  'physics-critic', 'physics-decider', 'plan-critic', 're-deriver', 'second-method-deriver',
                  'skeptical-verifier', 'trap-auditor')


def dispatch_roles():
    """Installed specialist seats declared by the conditional staffing policy."""
    from .. import role_registry, spawn_rows
    installed = role_registry.registry_document()['roles']
    conditional = {role['role'] for row in spawn_rows.catalogue()['rows']
                   if row['mode'] == 'specialist' for role in row['roles']}
    return tuple(sorted(set(ROLES) | (conditional & installed.keys())))


GATES = ('approve_plan', 'checkin2_accept', 'correction', 'delivery', 'failed_stage_feedback', 'final_task',
         'launch', 'report_integrity')
UNDISPATCHED_MODES = ('rdj', 'protocol', 'investigation')
FINDING_FIELDS = ('id', 'materiality', 'severity', 'evidence_class', 'evidence_locators', 'summary', 'claim',
                  'location', 'status')
APPROVER = 'ravel.workflow.science.approve'
PACKETS = 'review/packets'


def dispatchable(point):
    """Core panel seats and conditional specialist reviews use the review dispatcher."""
    return (point['mode'] not in UNDISPATCHED_MODES
            and (type(point['row']) is int or point['mode'] == 'specialist'))


class State(nodes.BaseState, total=False):
    points: dict
    items: list
    round: int
    branch: str
    findings: dict
    receipts: dict
    divergence: dict


class ItemView(TypedDict):
    meta: dict
    item: dict


class ItemState(nodes.BaseState, total=False):
    item: dict


def _root(state):
    return Path(state['meta']['scope_root'])


def _at(state):
    return state['meta']['instance']['at']


def gate_for(at, points=()):
    """The gate a review point set at ``at`` reports to."""
    blocking = [p['gate'] for p in points if p.get('blocking') and p.get('gate')]
    if blocking:
        return blocking[0]
    if at == 'checkin1':
        return 'approve_plan'
    if at.startswith('checkin2'):
        return 'checkin2_accept'
    if at == 'checkin3':
        return 'final_task'
    if at == 'delivery':
        return 'delivery'
    if at.startswith('on_failure:'):
        return 'failed_stage_feedback'
    if at.startswith('on_decision:'):
        return at.split(':', 1)[1]
    return points[0]['gate'] if points else None


def visible_findings(records):
    """Evidence-bearing findings without verdicts, votes or free-form decision fields."""
    from .. import review_points
    found = []
    for finding in records:
        if type(finding) is not dict:
            continue
        value = review_points.finding_record(finding)
        found.append({k: deepcopy(value[k]) for k in FINDING_FIELDS if k in value})
    return found


def _receipt_findings(root, facts, point_ids):
    from .. import review_points
    result = {}
    for record in review_points._receipt_records(root, facts):
        if record['_eligible'] and record.get('review_point_id') in point_ids and record.get('status') == 'ok':
            result.setdefault(record['review_point_id'], []).extend(visible_findings(record.get('findings', [])))
    return {key: result[key] for key in sorted(result)}


def _a_findings(root, facts, point_ids):
    from .. import review_points
    found = []
    for record in review_points._receipt_records(root, facts):
        if not record['_eligible'] or record.get('review_point_id') not in point_ids:
            continue
        for finding in record.get('findings', []):
            value = review_points.finding_record(finding)
            if value.get('materiality') == 'A' and review_points.blocking_finding(root, finding):
                found.append({'point_id': record['review_point_id'], **visible_findings([finding])[0]})
    return found


def derive(root, at, round_):
    """Pending points at ``at``, the items to dispatch this round, and the route."""
    from .. import review_points, spawn_rows
    facts = review_points._facts(root)
    if facts.get('agent_layer_epoch') != 2:
        raise nodes.RecoveryHold('review_points_epoch_two_only',
                                 'epoch-one runs keep the legacy research-orchestrate review path')
    every = [p for p in review_points.population(facts) if review_points.matches_at(p, at)]
    require_roles(every)
    pending = [p for p in [*review_points.pending(root), *spawn_rows.pending(root)]
               if review_points.matches_at(p, at)]
    items = []
    for point in pending:
        if not dispatchable(point) or not point.get('ready', True):
            continue
        subject = review_points.subject_digest(facts, point)
        evidence = (_receipt_findings(root, facts, set(point['depends_on'])) if point['depends_on'] else {})
        for entry in point['roles']:
            for n in range(1, entry['count'] + 1):
                key = f"r{round_}:{point['id']}:{entry['role']}:{n}"
                items.append({'key': key, 'point_id': point['id'], 'role': entry['role'], 'n': n, 'round': round_,
                              'at': point['when']['at'], 'subject_sha256': subject, 'claim_id': point.get('claim_id'),
                              'node_id': point.get('node_id'), 'gate': point['gate'], 'mode': point['mode'],
                              'findings': evidence})
                if isinstance(point['row'], str):
                    items[-1]['policy'] = deepcopy(next(p for p in every if p['id'] == point['id']))
    a_findings = _a_findings(root, facts, {p['id'] for p in every})
    from .. import review_projection  # a divergence beyond tolerance is an A finding
    a_findings += review_projection.divergence_a_findings(root, {p['id'] for p in every if p['id'].endswith(':divergence')})
    gate = gate_for(at, every)
    if items:
        branch = 'dispatch'
    elif a_findings:
        branch = 'correction_required'
    elif not facts.get('delegated') and at.startswith('checkin2'):
        branch = 'checkin2'
    elif not facts.get('delegated') and at == 'checkin3':
        branch = 'checkin3'
    elif gate in GATES:
        branch = gate
    else:
        branch = 'unrouted'
    points = {p['id']: {'gate': p['gate'], 'mode': p['mode'], 'blocking': p['blocking'], 'missing': p['roles'],
                        'ready': p.get('ready', True)} for p in pending}
    return {'points': points, 'items': items, 'branch': branch, 'findings': {'A': a_findings}}


def require_roles(points):
    """Resolve every applicable dispatched role before reserving or starting its panel."""
    from .. import role_registry
    missing = []
    for identity in sorted({role['role'] for point in points if dispatchable(point)
                            for role in point['roles']}):
        try:
            role_registry.load(identity)
        except ValueError:
            missing.append(identity)
    if missing:
        raise nodes.RecoveryHold('review_role_unavailable',
                                 'Install the required specialist cards and their knowledge bindings: '
                                 + ', '.join(missing))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def packet_path(item):
    return f"{PACKETS}/{_digest(item['key'])[:32]}.json"


def write_packets(root, items):
    """The code-computed item packet each reviewer receives (role, subject, dependency findings)."""
    written = {}
    for item in items:
        packet = {'schema_version': 1, 'kind': 'review-item-packet', **{k: deepcopy(item[k]) for k in (
            'point_id', 'role', 'n', 'round', 'at', 'subject_sha256', 'claim_id', 'node_id', 'gate', 'findings')}}
        if 'policy' in item:
            packet['policy'] = deepcopy(item['policy'])
        path = root / packet_path(item)
        if not path.exists():
            atomic_json(path, packet)
        if read_json(path) != packet:
            raise ValueError('review item packet changed: ' + packet_path(item))
        written[item['key']] = hashlib.sha256(path.read_bytes()).hexdigest()
    return written


def authentic_packet(root, rel, document):
    """Whether run file ``rel`` is the item packet this graph computes now for the item it names.

    The file name is the digest of the item key, the fields are exactly the packet's own, the
    subject is the point's current subject and the dependency findings are the ones the
    registered receipts carry. A hand-written file for the same role and point is none of that.
    """
    from .. import review_points
    fields = {'schema_version', 'kind', 'point_id', 'role', 'n', 'round', 'at', 'subject_sha256', 'claim_id',
              'node_id', 'gate', 'findings'}
    if (type(document) is not dict or set(document) not in (fields, fields | {'policy'})
            or document['kind'] != 'review-item-packet'
            or type(document['n']) is not int or type(document['round']) is not int):
        return False
    key = f"r{document['round']}:{document['point_id']}:{document['role']}:{document['n']}"
    if rel != packet_path({'key': key}):
        return False
    facts = review_points._facts(root)
    point = next((p for p in review_points.population(facts) if p['id'] == document['point_id']), None)
    entry = next((r for r in (point or {}).get('roles', []) if r['role'] == document['role']), None)
    if entry is None or not 1 <= document['n'] <= entry['count']:
        return False
    evidence = _receipt_findings(root, facts, set(point['depends_on'])) if point['depends_on'] else {}
    return document == {'schema_version': 1, 'kind': 'review-item-packet', 'point_id': point['id'],
                        'role': entry['role'], 'n': document['n'], 'round': document['round'],
                        'at': point['when']['at'], 'subject_sha256': review_points.subject_digest(facts, point),
                        'claim_id': point.get('claim_id'), 'node_id': point.get('node_id'), 'gate': point['gate'],
                        'findings': evidence, **({'policy': point} if isinstance(point['row'], str) else {})}


def reservation_budget(root, instance):
    """Bound all direct workers from the pinned population, including later dependent points.

    Items do not reserve controller child steps. Their parent reserves this entire bound;
    settlement sums authenticated item usage, including parallel worker seconds.
    Token and cost usage have no per-item ceiling and retain M17's measured-after policy.
    """
    from .. import review_points
    graph_registry.check_instance(graph_registry.get(POINTS), instance)
    facts = review_points._facts(root)
    if facts.get('agent_layer_epoch') != 2:
        raise ValueError('review reservations require the pinned epoch-two population')
    points = [point for point in review_points.population(facts) if review_points.matches_at(point, instance['at'])]
    require_roles(points)
    items = sum(role['count'] for point in points if dispatchable(point)
                for role in point['roles'])
    workers = MAX_ROUNDS * items
    return {'wall_seconds': workers * ITEM_BUDGETS['max_wall_seconds'],
            'model_calls': workers * ITEM_BUDGETS['max_turns'], 'children': max(1, workers)}


def worker_spec(root, item, *, invocation=None):
    """The governed reviewer worker for one item; credit is checked by review_points, not here."""
    from .. import review_points, role_registry
    card = role_registry.load(item['role'])
    path = root / packet_path(item)
    preferences_path = root / 'inputs/agent_preferences.json'
    preferences = read_json(preferences_path) if preferences_path.exists() else {}
    preference = preferences.get('transport_preference') if type(preferences) is dict else None
    identity = item['key'] if invocation is None else {'item': item['key'], 'parent': invocation}
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': 'review-' + _digest(identity)[:24],
            'attempt': 1,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': role_registry.card_sha256(item['role'])},
            'transport_preference': list(preference) if type(preference) is list and preference else ['default'],
            'inputs': [{'pin': {'path': packet_path(item), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
                        'as': 'inputs/review-packet.json'}],
            'declared_outputs': [{'path': 'outputs/review.json', 'kind': 'review-findings', 'required': True}],
            'budgets': deepcopy(ITEM_BUDGETS),
            'final_record_schema': 'reviewer.v1', 'work_order': None, 'rdj_challenges': None,
            # The subject rides on the dispatch, so the worker writes a version-2 receipt that can earn credit.
            'parent': {'review_point_id': item['point_id'], 'map_id': 'review:' + item['at'], 'rca_ticket': None,
                       'review_subject': {'scope': review_points.subject_scope(item), 'sha256': item['subject_sha256']}}}


def approval_errors(root, gate, response):
    """A human CHECK-IN resume is data; acceptance needs the run's exact science.approve record."""
    def error(code, message, pins=()):
        return {'code': code, 'gate': gate, 'provider': 'review_graph', 'message': message,
                'fix': 'record the approval with ravel.workflow.science.approve and answer with its path and sha256',
                'pins': list(pins)}
    if response is None:
        return [error('human_response_missing', 'no recorded human response precedes this gate')]
    value = response['value']
    if value.get('decision') != 'approve':
        return [error('human_not_approved', 'the human response is ' + str(value.get('decision')))]
    record = value.get('record')
    if type(record) is not dict:
        return [error('science_approve_missing', 'the human response names no science.approve record')]
    from ..science import APPROVAL
    expected = (root / APPROVAL).resolve()
    try:
        path = (root / record['path']).resolve()
    except (OSError, ValueError):
        path = None
    if path != expected or not expected.is_file():
        return [error('science_approve_missing', 'the named record is not this run\'s science.approve receipt',
                      [str(record.get('path'))])]
    raw = expected.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record['sha256']:
        return [error('science_approve_invalid', 'the science.approve record differs from the pinned bytes', [APPROVAL])]
    try:
        approval = json.loads(raw)
    except ValueError:
        approval = None
    if (type(approval) is not dict or approval.get('generated_by') != APPROVER or approval.get('schema_version') != 2
            or type(approval.get('quote')) is not str or not approval['quote'].strip()):
        return [error('science_approve_invalid', 'the record is not a human science.approve receipt', [APPROVAL])]
    return []


def _response(state, schema_id):
    found = [v for v in (state.get('responses') or {}).values() if v.get('schema_id') == schema_id]
    return found[-1] if found else None


def _action(state, gate):
    at = _at(state)
    action = {'kind': 'review.points', 'summary': 'review points at ' + at, 'pins': [], 'node_id': None,
              'rung': None, 'scope': None}
    if at.startswith('checkin2:'):
        action['claim_id'] = at.split(':', 1)[1]
    if at.startswith(('node:', 'on_failure:')):
        action['node_id'] = at.split(':', 1)[1]
    action['digest'] = _digest({'at': at, 'gate': gate, 'points': state.get('points') or {},
                                'receipts': state.get('receipts') or {}})
    return action


def human_gate(gate_name, schema_id):
    """The gate after a human interrupt: the ordinary providers plus the approval record check."""
    base = nodes.gate(gate_name, lambda s: _action(s, gate_name))

    def body(state):
        update = base.function(state)
        verdict = update['gates'][gate_name]
        extra = approval_errors(_root(state), gate_name, _response(state, schema_id))
        verdict['errors'] = verdict['errors'] + extra
        verdict['providers'] = sorted({e.get('provider', '') for e in verdict['errors']})
        return update
    body.__name__ = 'human_gate_' + gate_name
    return nodes.Node('gate', body, gate=gate_name)


def _host_authored(state):
    """the CHECK-IN packet lists the plan nodes the host authored under a waiver."""
    from .. import production_executor
    return production_executor.host_authored_nodes(_root(state))


def _standard(builder, graph_id, reason):
    nodes.add(builder, 'decision_turn', nodes.decision_turn(graph_id), graph_id=graph_id)
    nodes.add(builder, 'reconcile', nodes.reconcile_node(), graph_id=graph_id)
    nodes.add(builder, 'hold', nodes.hold(reason), graph_id=graph_id)


def _projection(run, item):
    """the reviewer's workspace receives the packet its card's ``sees`` permits (None for a producer)."""
    from .. import review_projection
    return review_projection.packet_for(run, item)


def _screen(run, receipt):
    from .. import review_projection
    return review_projection.screen_receipt(run, receipt)


def build_item(ctx):
    """One reviewer worker per item, routed by its registered role."""
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(ItemState, input_schema=ItemView)
    run = ctx.scope_root
    _standard(builder, ITEM, 'review_item_hold')
    paths = {}
    roles = dispatch_roles()
    for role in DISPATCH_ROLES:
        name = role.replace('-', '_')
        paths[role] = name
        agent = nodes.agent('review.worker', rundir=run, spec=lambda s: worker_spec(Path(run), s['item'],
                            invocation=ctx.extras.get('worker_usage_binding')),
                            segment=lambda s: {'point': s['item']['point_id'], 'round': s['item']['round'],
                                               'role': s['item']['role'], 'n': s['item']['n']},
                            packet=lambda s: _projection(run, s['item']),
                            to_state=lambda s, receipt: {'results': {'review': {
                                'status': receipt['status'], 'node_id': receipt['node_id'],
                                'attempt': receipt['attempt'], 'review_point_id': receipt.get('review_point_id'),
                                'findings': _screen(run, receipt)}}})
        agent.kind, agent.role = 'agent', role
        nodes.add(builder, name, agent, graph_id=ITEM)
        builder.add_edge(name, END)
    nodes.add(builder, 'unregistered', nodes.hold('review_role_unregistered',
                                                 'register the role in review.item before dispatching it'), graph_id=ITEM)
    paths['unregistered'] = 'unregistered'
    nodes.connect(builder, START, nodes.route(
        lambda s: s['item']['role'] if s['item']['role'] in roles else 'unregistered', paths))
    return builder


def build(ctx):
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(State)
    add = lambda name, node: nodes.add(builder, name, node, graph_id=POINTS)
    child_ctx = graph_substrate.BuildContext(ctx.scope_root, ITEM, graph_registry.get(ITEM)['version'],
                                             ctx.instance, extras=ctx.extras)
    child = graph_substrate.build(ITEM, child_ctx)
    _standard(builder, POINTS, 'review_point_pending')

    def policy(state):
        failed = any(v != 'ok' for v in (state.get('receipts') or {}).values())
        if state.get('round', 0) >= MAX_ROUNDS:
            return 'escalate' if failed else 'exhausted'
        return 'go'
    add('guard', nodes.guard(policy, {'go': 'derive'}))

    def derive_node(state):
        return {**derive(_root(state), _at(state), state.get('round', 0)), 'round': state.get('round', 0)}
    add('derive', nodes.Node('effect', derive_node))
    routes = {'dispatch': 'fanout', 'correction_required': 'correction_required', 'checkin2': 'checkin2', 'checkin3': 'checkin3',
              'unrouted': 'hold', **{g: 'gate_' + g for g in GATES}}
    nodes.connect(builder, 'derive', nodes.route(lambda s: s['branch'], routes))

    def publish_items(state, identity):
        written = write_packets(_root(state), state['items'])
        record = ctx.extras.get('record_worker_items')
        if callable(record):
            record([{'spec': worker_spec(_root(state), item, invocation=ctx.extras.get('worker_usage_binding')),
                     'graph': {'id': ITEM, 'version': child_ctx.version}} for item in state['items']])
        return written

    add('fanout', nodes.effect('review.packets', kind='journal',
        segment=lambda s: {'round': s['round']},
        identity=lambda s: {'at': _at(s), 'items': _digest(s['items'])},
        run=publish_items,
        to_state=lambda s, result: {}))
    edge, mapped = nodes.map_node(lambda s: s['items'], lambda item: item['key'], child,
                                  lambda s, item: {'item': item}, name='review_item')
    add('review_item', mapped)
    nodes.connect(builder, 'fanout', edge)
    builder.add_edge('review_item', 'join')

    def join(state):
        results = state.get('results') or {}
        outcomes = {item['key']: results.get(item['key'], {}).get('outcome', 'failed') for item in state['items']}
        return {'receipts': {**(state.get('receipts') or {}), **outcomes}, 'round': state['round'] + 1}
    add('join', nodes.Node('effect', join))

    def divergence(state):
        """Implementation-divergence comparator: compares each credited analysis-author pair."""
        from .. import review_projection
        return {'divergence': {'status': 'compared', 'points': review_projection.compare_divergence(_root(state), _at(state))}}
    add('divergence', nodes.Node('effect', divergence))
    builder.add_edge('divergence', 'guard')
    builder.add_edge('join', 'divergence')

    add('correction_required', nodes.hold('review_correction_required',
        'Record a correction for the evidence-bearing findings, then re-review the affected subjects.'))

    for schema_id, gate_name in (('checkin2_response', 'checkin2_accept'), ('checkin3_response', 'final_task')):
        name = schema_id.split('_')[0]
        add(name, nodes.interrupt(schema_id, lambda s: {'at': _at(s), 'points': s.get('points') or {},
                                                        'receipts': s.get('receipts') or {},
                                                        'host_authored_nodes': _host_authored(s)},
                                  segment=lambda s: {'at': _at(s)}))
        add(name + '_gate', human_gate(gate_name, schema_id))
        builder.add_edge(name, name + '_gate')
        nodes.connect(builder, name + '_gate', nodes.gate_route(gate_name, passed=END, refused='refused'))
    for gate_name in GATES:
        add('gate_' + gate_name, nodes.gate(gate_name, lambda s, g=gate_name: _action(s, g)))
        nodes.connect(builder, 'gate_' + gate_name, nodes.gate_route(gate_name, passed=END, refused='refused'))
    add('refused', nodes.hold('review_gate_refused', 'clear the gate errors recorded in gates, then '
                              'ravel review run with the next --attempt'))
    builder.add_edge(START, 'guard')
    return builder


# ---- entry points ---------------------------------------------------------------------

def instance(at, attempt=1):
    if type(at) is not str or not at or type(attempt) is not int or attempt < 1:
        raise ValueError('review instance requires a when.at value and a positive attempt')
    return {'at': at, 'attempt': attempt}


def run(rundir, at, *, attempt=1, responses=None, gate_check=None, gate_providers=None, clear_stop=False,
        max_steps=None, workers=None):
    """Start or continue the review of the points at ``at``; returns the substrate observation."""
    key = instance(at, attempt)
    if responses:
        return graph_substrate.respond(rundir, POINTS, key, responses, workers=workers, gate_check=gate_check,
                                       gate_providers=gate_providers, clear_stop=clear_stop)
    return graph_substrate.run(rundir, POINTS, key, workers=workers, gate_check=gate_check,
                               gate_providers=gate_providers, clear_stop=clear_stop, max_steps=max_steps)


def delegates(rundir):
    """True for an epoch-two run with the inputs/ contract layout; others keep the legacy review."""
    root = Path(rundir)
    if not (root / 'inputs/task_contract.json').is_file():
        return False
    from .. import review_points
    return review_points._facts(root).get('agent_layer_epoch') == 2


def orchestrated(rundir, claim_scope=None):
    """The research_orchestrator.review delegation: one review.points run, never an acceptance."""
    at = 'checkin2:' + claim_scope if type(claim_scope) is str and claim_scope else 'checkin3'
    observation = run(rundir, at)
    return {'phase': 'review_points', 'at': at, 'observation': observation, 'execution_authorized': False,
            'scientific_acceptance': False}


def main(argv=None):
    """``ravel review run|dispatch``; every other review subcommand is review_points' own."""
    import argparse
    import sys
    from .. import review_points
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in {'run', 'dispatch'}:
        return review_points.main(arguments)
    parser = argparse.ArgumentParser(prog='ravel review ' + arguments[0],
                                     description='Run the review.points graph for one review point set.')
    parser.add_argument('--rundir', type=Path, required=True)
    parser.add_argument('--at', required=True, help='when.at of the points, e.g. checkin2:C1 or checkin3')
    parser.add_argument('--attempt', type=int, default=1, help='a new attempt re-derives and dispatches only missing roles')
    parser.add_argument('--respond', type=Path, help='JSON map of pending interrupt id to response value')
    parser.add_argument('--clear-stop', action='store_true')
    args = parser.parse_args(arguments[1:])
    try:
        responses = read_json(args.respond) if args.respond else None
        value = run(args.rundir, args.at, attempt=args.attempt, responses=responses, clear_stop=args.clear_stop)
        print(json.dumps(value, indent=2, sort_keys=True, default=str))
        return 0
    except (ValueError, OSError, KeyError, TypeError, GraphError) as exc:
        print('review: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
