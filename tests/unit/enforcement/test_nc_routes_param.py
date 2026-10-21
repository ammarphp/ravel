"""Stage and route rows over the installed population: STAGE (research protocol) and ROUTE (task modes).

STAGE rows come from the installed research protocol (``research/protocol-default.json``); the oracle for
each stage is written here from that data: the inputs, outputs, roles, review point and review-round bound a
stage declares, and the refusals that follow when a bound run, an artifact or an advancement lacks one of
them. The adversary edits the bound protocol record, drops an artifact field, marks a stage done out of order
or without a role receipt, requests a stage whose predecessors are incomplete, or asks for a review round
past the bound; each attack sits beside its positive control (the untouched record, the conforming artifact,
the complete receipts). These cases are INSTALLED: the guards exist in the installed RAVEL.

ROUTE rows come from the task modes. A mode with a fixed route spec compiles to a plan of that route; every
other mode is planned by the judgment route (a frame and a typed plan). The adversary drops a route stage or
a deliverable's step from the compiled plan (and reseals its digest, so that only the structural checks can
refuse it), dispatches a bulk step before the check-ins, drops a mapping rule, or drops a frame deliverable;
the oracle is that the route's stage checks refuse the plan and that every reading deliverable stays either
mapped or an explicit open obligation. These cases are CONTROLLER: the route compiler exists only with the
controller build.

Everything is fictional and inert: no model, provider, network or native tool.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from nc_cases import CONTROLLER, INSTALLED, dimension_case, dimension_rows, require_controller
from nc_mutations import (CONTROLLER as MUTATION_CONTROLLER, INSTALLED as MUTATION_INSTALLED, Mutation,
                          passes_through, register, returns)

REGIME = 'closed_scored'
PROTOCOL = 'research/protocol.json'


# ---------------------------------------------------------------- STAGE: the installed research protocol

def _research():
    from ravel.workflow import research_cycle as cycle, research_protocol as protocol
    return protocol, cycle


def _declared():
    """The stages as the packaged protocol data declares them (read as data, not through the mechanism)."""
    from ravel.paths import package_data_path
    return json.loads(package_data_path('research', 'protocol-default.json').read_text())['stages']


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _write(root, name, value):
    _, cycle = _research()
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return cycle._pin(path)


def _authorized(root, name, action, level):
    """The action with an authorizing decision receipt for exactly its digest (fictional evidence)."""
    case = _write(root, f'decisions/{name}-case.json', {'schema_version': 2, 'fictional': True})
    receipt = {'schema_version': 1, 'kind': 'rdj-receipt', 'outcome': 'authorize', 'gate': 'research_choice',
               'action_digest': _digest(action), 'class': level, 'case': case, 'case_sha256': case['sha256'],
               'open_a_findings': 0, 'unresolved_branches': 0,
               'attestation_summary': {'distinct_sessions': True, 'distinct_actors': True}}
    return {**action, 'rdj_receipt': _write(root, f'decisions/{name}.json', receipt)}


def _artifacts(root):
    """A conforming fictional artifact for every stage, with the records it pins written under ``root``."""
    protocol, _ = _research()
    source = _write(root, 'evidence/source.json', {'value': 1, 'fictional': True})
    audit = _write(root, 'evidence/audit.json', {'status': 'passed', 'fictional': True})
    cell = {'value': 1, 'unit': '1', 'uncertainty': 0, 'source': source}
    result = _write(root, 'evidence/select-result.json', {
        'kind': 'research-select-result', 'exposure': 'adaptive_full', 'candidate': 'Ia', 'family': 'fam',
        'status': 'success', 'decision': 'better', 'cost': 1})
    ideas = [{'id': 'I' + stream, 'stream': stream, 'seed': 'limitation:L1', 'operator': 'limitation_fix',
              'hypothesis': 'The response depends on the regime.', 'prediction': 'A held-out contrast changes.',
              'novelty': {'rank': rank, 'prior_art': [], 'scout_receipt': source}}
             for rank, stream in enumerate('ab', 1)]
    receipts = {stream: _write(root, f'evidence/dispatch-{stream}.json', {
        'kind': 'research-idea-dispatch', 'stream': stream, 'committed_sequence': 1,
        'ideas_sha256': protocol.ce.digest([row for row in ideas if row['stream'] == stream]),
        'execution_observation': 'host_attested_external'}) for stream in 'ab'}
    return {
        'limitation_census': {'limitations': [{
            'id': 'L1', 'subject': 'reference_method', 'flaw': 'One regime is untested.',
            'consequence': 'Generalization is unknown.', 'opportunity': 'Test a second regime.',
            'evidence': ['source:1'], 'testable_signature': 'The response changes with the regime.'}]},
        'ideas': {'ideas': ideas, 'tests': [], 'dispatch_receipts': receipts,
                  'operator_yield': {'limitation_fix': {'ideas': 2, 'screen': {'tested': 0, 'passed': 0},
                                                        'full': {'tested': 0, 'passed': 0}}}},
        'baseline': {'three_columns': [{'quantity': 'response', 'ours': cell, 'reproduced': cell,
                                        'published': cell, 'published_source': source}]},
        'screen': {'subset': {'cells': ['development']}, 'omitted_regimes': ['confirmation'],
                   'verdicts': [_authorized(root, 'screen', {'idea': 'Ia', 'verdict': 'promote',
                                                             'mutable_paths': []}, 'R2')]},
        'validate': {'withheld_cells': ['confirm'],
                     'rounds': [{'round': 1, 'candidates': ['Ia'], 'successes': 1, 'results': [result],
                                 'seed_reinjection': ['Ib'], 'trace': source}],
                     'stop': {'successes': 1, 'max_rounds': 2, 'budget': 3, 'coverage_floor': 1,
                              'families': ['fam'], 'reason': 'successes'},
                     'selection': _authorized(root, 'selection', {'rule': 'reviewed_dominance',
                                                                  'comparison': source}, 'R2')},
        'critique_to_experiments': {'concerns': []},
        'acceptance': {'claims': [{'id': 'K1', 'kind': 'finding', 'N': 0, 'verdict': 'exploratory'}]},
        'meta_review': {'transport_id': 'external', 'receipt': source, 'verdict': {'outcome': 'accept'}},
        'integrity': {'receipt': source, 'report_integrity': source, 'rerun': audit, 'references': audit,
                      'paper_vs_code': audit},
    }


def _complete(root, row, artifacts, roles=None):
    """Mark a bound-record stage done, with its artifact and one receipt per role (or per ``roles``)."""
    row.update(status='done', artifact=_write(root, f'artifacts/{row["id"]}.json', artifacts[row['id']]),
               worker_receipts={role: _write(root, f'receipts/{row["id"]}-{role}.json', {'role': role})
                                for role in (row['roles'] if roles is None else roles)})


def _bound_run(nc, name, done):
    """A run directory bound to the default protocol whose first ``done`` stages are complete.

    Returns ``(root, artifacts)``; the bound record is ``root/research/protocol.json``.
    """
    protocol, _ = _research()
    root = nc.root / 'stage-runs' / name
    root.mkdir(parents=True)
    protocol.bind_default(root, regime=REGIME)
    artifacts = _artifacts(root)
    path = root / PROTOCOL
    record = json.loads(path.read_text())
    record['preregistration'] = _write(root, 'preregistration.json', {
        'schema_version': 1, 'kind': 'research-preregistration', 'approximations': []})
    for row in record['stages'][:done]:
        _complete(root, row, artifacts)
    path.write_text(json.dumps(record))
    return root, artifacts


def _edit(root, change):
    """Rewrite the bound record with ``change(record)`` applied; returns the original text."""
    path = root / PROTOCOL
    original = path.read_text()
    record = json.loads(original)
    change(record)
    path.write_text(json.dumps(record))
    return original


@dimension_case('STAGE', binding=INSTALLED)
@pytest.mark.parametrize('row', dimension_rows('STAGE'), ids=str)
def test_research_stage_does_not_advance_without_its_declared_inputs_outputs_roles_review_points_or_bound(nc, row):
    protocol, _ = _research()
    stage = row.removeprefix('STAGE-')
    stages = _declared()
    index = [entry['id'] for entry in stages].index(stage)
    declared, before = stages[index], [entry['id'] for entry in stages[:index]]
    for field in ('roles', 'required_inputs', 'required_outputs', 'review_points'):
        assert declared[field], (row, field)  # the data declares every contract the stage is held to
    assert declared['review_points'] == [f'RP13:{stage}'] and declared['bound']['max_rounds'] >= 1, row

    # 1. Outputs. The conforming artifact is accepted; one without a declared output is refused for that output,
    # and a bare not-applicable statement does not stand in for outputs.
    root, artifacts = _bound_run(nc, 'artifact', done=0)
    artifact = artifacts[stage]
    assert set(declared['required_outputs']) <= set(artifact), row  # the fixture conforms to the data
    assert protocol.validate_stage_artifact(stage, artifact, base_dir=root, regime=REGIME) == artifact
    for output in declared['required_outputs']:
        without = {key: value for key, value in artifact.items() if key != output}
        with pytest.raises(ValueError, match=f'missing required artifact field: {output}'):
            protocol.validate_stage_artifact(stage, without, base_dir=root, regime=REGIME)
    with pytest.raises(ValueError, match='computed applicability does not permit not_applicable'):
        protocol.validate_stage_artifact(stage, {'status': 'not_applicable', 'reason': 'a fictional reason'},
                                         base_dir=root, regime=REGIME)

    # 2. Declared inputs, outputs, roles, review points and bound. The bound record carries the stage exactly as
    # declared; a copy that lacks one of them, or that widens the review bound, is not the bound protocol.
    root, artifacts = _bound_run(nc, 'definition', done=index)
    status = protocol.methodology_status(root)
    assert status['next_stage'] == stage and status['pending'][0] == stage and not status['complete'], row
    bound = next(entry for entry in status['record']['stages'] if entry['id'] == stage)
    assert all(bound[field] == declared[field] for field in declared), row  # positive control
    for field in ('required_inputs', 'required_outputs', 'roles', 'review_points'):
        original = _edit(root, lambda record, f=field: record['stages'][index].update({f: record['stages'][index][f][:-1]}))
        with pytest.raises(ValueError, match='role/input/output definition differs'):
            protocol.methodology_status(root)
        (root / PROTOCOL).write_text(original)
    original = _edit(root, lambda record: record['stages'][index]['bound'].update(
        max_rounds=declared['bound']['max_rounds'] + 1))
    with pytest.raises(ValueError, match='role/input/output definition differs'):
        protocol.methodology_status(root)
    (root / PROTOCOL).write_text(original)
    assert protocol.methodology_status(root)['next_stage'] == stage  # restored: the record is accepted again

    # 3. Roles and order. A stage is done only with a receipt of every declared role and only after its predecessor.
    root, artifacts = _bound_run(nc, 'receipts', done=index)
    for roles, reason in [(declared['roles'][:-1], 'a role without its receipt'),
                          (declared['roles'] + ['fictional-extra-role'], 'a receipt of an undeclared role')]:
        original = _edit(root, lambda record: _complete(root, record['stages'][index], artifacts, roles))
        with pytest.raises(ValueError, match='requires every role receipt'):
            protocol.methodology_status(root)
        (root / PROTOCOL).write_text(original)
    _edit(root, lambda record: _complete(root, record['stages'][index], artifacts))  # positive control
    advanced = protocol.methodology_status(root)
    following = [entry['id'] for entry in stages[index + 1:]]
    assert advanced['pending'] == following and advanced['next_stage'] == (following[0] if following else None), row
    assert advanced['complete'] == (not following), row
    if index:
        root, artifacts = _bound_run(nc, 'skipped', done=index - 1)
        _edit(root, lambda record: _complete(root, record['stages'][index], artifacts))
        with pytest.raises(ValueError, match='skipped its pending predecessor'):
            protocol.methodology_status(root)

    # 4. The research-choice gate names every incomplete predecessor, and none once they are complete.
    root, _ = _bound_run(nc, 'gate-open', done=0)
    refused = protocol.gate_errors(root, 'research_choice', {'scope': stage})
    assert [error.message for error in refused] == [f'required research stage incomplete: {s}' for s in before], row
    assert all(error.gate == 'research_choice' for error in refused), row
    unknown = protocol.gate_errors(root, 'research_choice', {'scope': 'fictional-stage'})
    assert [error.message for error in unknown] == ['research choice requires a declared protocol stage'], row
    root, _ = _bound_run(nc, 'gate-done', done=index)
    assert protocol.gate_errors(root, 'research_choice', {'scope': stage}) == []  # positive control

    # 5. The review-round bound. The decision gate is tested above and is isolated here (as the protocol's own
    # tests do), so that the refusal is the bound's. A round below the bound is not refused for it.
    nc.patch.setattr(protocol, 'decision_errors', lambda *args, **kwargs: [])
    limit = declared['bound']['max_rounds']
    root, artifacts = _bound_run(nc, 'bound', done=index)
    pin = _write(root, 'proposal.json', artifacts[stage])
    _edit(root, lambda record: record['stages'][index].update(round=limit))
    with pytest.raises(ValueError, match='review round bound exhausted'):
        protocol.prepare_stage(root, stage, pin, root / 'review-exhausted', model='fictional-model')
    _edit(root, lambda record: record['stages'][index].update(round=limit - 1))
    try:
        protocol.prepare_stage(root, stage, pin, root / 'review-open', model='fictional-model')
    except Exception as exc:  # the fixture run has no research cycle; anything later than the bound is not the bound
        assert 'round bound' not in str(exc), (row, exc)


def _gate_open(original):
    return lambda *args, **kwargs: []


def _unvalidated(original):
    return lambda stage_id, value, **kwargs: deepcopy(value)


def _done_status(original):
    return lambda root: {'schema_version': 1, 'kind': 'research-methodology-status', 'record': {'stages': []},
                         'pending': [], 'next_stage': None, 'complete': True, 'scientific_acceptance': False}


STAGE_CATCH = ('test_research_stage_does_not_advance_without_its_declared_inputs_outputs_roles_review_points_or_'
               'bound[STAGE-baseline]',)

register(
    Mutation('M01', 'ravel.workflow.research_protocol:gate_errors', _gate_open, STAGE_CATCH,
             binding=MUTATION_INSTALLED, why='the research-choice gate admits a stage whose predecessors are open'),
    Mutation('M01', 'ravel.workflow.research_protocol:validate_stage_artifact', _unvalidated, STAGE_CATCH,
             binding=MUTATION_INSTALLED, why='a stage artifact is accepted without its declared outputs'),
    Mutation('M01', 'ravel.workflow.research_protocol:methodology_status', _done_status, STAGE_CATCH,
             binding=MUTATION_INSTALLED, why='the bound protocol is not compared with its declared definition'))


# ---------------------------------------------------------------- ROUTE: the compiled route graph per task mode

# The routes the installed specs serve; every other task mode is planned by the judgment route.
FIXED = {'scan': 'analysis.scan', 'reproduce': 'analysis', 'reinterpret': 'analysis'}
RESULT_STEP = {'scan': 'scan.assemble', 'reproduce': 'run.full', 'reinterpret': 'run.full'}
# The stages every plan of a fixed route keeps (the per-point or full-run result stage is added per mode).
KEPT = ('env', 'inputs.census', 'inputs.route', 'inputs.traps', 'inputs.figures', 'inputs.cost', 'recast.smoke',
        'visualize.waypoint', 'acquire.data', 'visualize.final', 'compare.reference', 'verify.mechanical',
        'verify.adversary', 'synthesize')
CHECKINS = ('checkin1', 'checkin2', 'checkin3')
CONTRACT = {'schema_version': 1}


def _reading(scan=False):
    """A fictional reading: two deliverables a fixed route serves and one it does not."""
    facts = [{'id': 'F1', 'type': 'model_term', 'value': {'text': 'toy pair'}}]
    if scan:
        facts.append({'id': 'F2', 'type': 'parameter_values',
                      'value': {'text': 'masses 100, 200', 'values': [100, 200], 'unit': 'GeV', 'variable': 'm_toy'}})
    return {'kind': 'request-reading', 'facts': facts, 'constraints': [], 'boundaries': [], 'ambiguities': [],
            'deliverables': [{'id': 'd1', 'artifact': {'kind': 'inference', 'require': {}}, 'claim_kind': 'exclusion'},
                             {'id': 'd2', 'artifact': {'kind': 'figure', 'require': {}}, 'claim_kind': 'estimate'},
                             {'id': 'd3', 'artifact': {'kind': 'table', 'require': {}}, 'claim_kind': 'estimate'}]}


def _resealed(plan):
    plan['sha256'] = _digest({key: value for key, value in plan.items() if key != 'sha256'})
    return plan


def _without_step(plan, step_id):
    """The plan with one step removed from the graph, its edges and waypoints cleaned and its digest resealed."""
    found = deepcopy(plan)
    found['steps'] = [step for step in found['steps'] if step['id'] != step_id]
    for step in found['steps']:
        step['depends_on'] = [parent for parent in step['depends_on'] if parent != step_id]
    found['waypoints'] = [waypoint for waypoint in found['waypoints'] if waypoint != step_id]
    return _resealed(found)


class _Store:
    """The run store as the route guards read it: ``scan(kind)`` over appended records."""

    def __init__(self, *records):
        self.rows = [dict(row) for row in records]

    def scan(self, kind):
        return [row for row in self.rows if row.get('record_kind') == kind]


def _grants(*kinds):
    return _Store(*({'record_kind': 'authority', 'kind': kind, 'decision': 'approve', 'uid': f'grant-{kind}'}
                    for kind in kinds))


def _codes(errors):
    return {error['code'] for error in errors}


FOREACH_PREFIXES = ('scan.point.',)  # expansions of a foreach template follow the route's parameters


def _fixed_route(nc, mode, routes, modules):
    """Plan, drop and deliver checks of a task mode served by a fixed route spec."""
    analysis, checkins, guard, scan, compiler = modules
    spec_id = FIXED[mode]
    reading = _reading(scan=mode == 'scan')
    contract = dict(CONTRACT, task_mode=mode)
    spec = routes.find(spec_id)
    plan = routes.compile(spec, reading, contract)

    # Positive control: the compiled plan is sound, keeps every route stage and check-in, and leaves nothing open
    # but the deliverable the route cannot produce.
    assert routes.plan_errors(plan) == [] and plan['route']['id'] == spec_id, mode
    assert routes.plan_errors(plan, spec) == [], mode  # and it conforms to the route spec it claims
    steps = [step['id'] for step in plan['steps']]
    assert set(KEPT) <= set(steps) and RESULT_STEP[mode] in steps, (mode, steps)
    assert [item['id'] for item in plan['checkins']] == list(CHECKINS), mode
    assert checkins.stage_errors(plan) == [] and guard.ladder_errors(plan) == [], mode
    assert scan.membership_errors(plan) == [], mode
    rows = {item['id']: item for item in plan['deliverables']}
    assert sorted(rows) == ['d1', 'd2', 'd3'], mode  # no reading deliverable is dropped
    assert [rows[name]['status'] for name in ('d1', 'd2', 'd3')] == ['mapped', 'mapped', 'open'], mode
    assert (rows['d1']['step'], rows['d2']['step']) == (RESULT_STEP[mode], 'visualize.final'), mode
    assert [item['id'] for item in plan['open_obligations']] == ['d3'], mode
    assert compiler.population_holes(['d1', 'd2', 'd3'], ['d1', 'd2']) == ['d3'], mode
    assert compiler.population_holes(['d1', 'd2', 'd3'], ['d1', 'd2', 'd3']) == [], mode

    # Attack 1: a stage of the route is dropped from the compiled graph (digest resealed). The route's stage
    # check refuses the plan for every stage; a result stage that carries a deliverable also breaks the mapping.
    for dropped in [*KEPT, RESULT_STEP[mode]]:
        attacked = _without_step(plan, dropped)
        assert attacked['sha256'] != plan['sha256'], (mode, dropped)
        missing = checkins.stage_errors(attacked)
        assert missing and _codes(missing) == {'route_stage_missing'}, f'{mode}: dropping {dropped} was not refused'
        if not dropped.startswith(FOREACH_PREFIXES):
            assert any(f'route stage {dropped} is missing' in p for p in routes.plan_errors(attacked, spec)), dropped
        if dropped in ('run.full', 'visualize.final'):
            assert any(f'maps to unknown step {dropped}' in problem for problem in routes.plan_errors(attacked)), dropped
    # Attack 1b: a route check-in, or one of its seats, is dropped from the compiled plan (digest resealed).
    for checkin in plan['checkins']:
        without = deepcopy(plan)
        without['checkins'] = [c for c in without['checkins'] if c['id'] != checkin['id']]
        assert any(f"route check-in {checkin['id']} is missing" in p
                   for p in routes.plan_errors(_resealed(without), spec)), (mode, checkin['id'])
        if checkin.get('seats'):
            seatless = deepcopy(plan)
            next(c for c in seatless['checkins'] if c['id'] == checkin['id'])['seats'] = []
            assert any('lost its seats' in p for p in routes.plan_errors(_resealed(seatless), spec)), (mode, checkin['id'])
    waypoint = _without_step(plan, 'visualize.waypoint')
    assert 'waypoint_missing' in _codes(guard.ladder_errors(waypoint)), mode  # the rung ladder needs its waypoint
    # An edit that is not resealed is not the compiled plan at all.
    edited = deepcopy(plan)
    edited['steps'] = [step for step in edited['steps'] if step['id'] != 'verify.adversary']
    assert any('sha256' in problem for problem in routes.plan_errors(edited)), mode
    if mode == 'scan':
        point = next(step['id'] for step in plan['steps'] if step['id'].startswith('scan.point.'))
        assert 'scan_point_unplanned' in _codes(scan.membership_errors(_without_step(plan, point))), mode

    # Attack 2: a bulk step is dispatched before the check-ins. Without CHECK-IN 1 authority the production
    # step is refused; at the full or scan rung it also needs the CHECK-IN 2 GO. With both, neither is owed.
    bulk = next(step for step in plan['steps'] if step.get('rung') in ('full', 'scan'))
    from nc_controller import controller_run, checkin_view
    authority = require_controller('authority')
    store, _ = controller_run(nc, 'route-' + mode, mode='autonomous')
    context = {'plan': plan, 'store': store, 'state': {'steps': {}}, 'reading': reading, 'contract': contract}
    early = _codes(guard.admit(bulk, context))
    assert {'checkin1_missing', 'checkin2_go_missing'} <= early, (mode, early)
    ci1 = authority.request(store, 'approve_plan', {'view': checkin_view(store, 'approve_plan',
        plan_sha256=plan['sha256'])}, {'rung': bulk['rung']})
    assert ci1.get('decision') == 'approve', ci1
    only_plan = _codes(guard.admit(bulk, context))
    assert 'checkin1_missing' not in only_plan and 'checkin2_go_missing' in only_plan, (mode, only_plan)
    go = authority.request(store, 'go', {'view': checkin_view(store, 'go', plan_sha256=plan['sha256'],
        approve_plan=ci1['id'], waypoint_sha256='b' * 64)}, {'rung': bulk['rung']})
    assert go.get('decision') == 'go', go
    approved = _codes(guard.admit(bulk, context))
    assert not approved & {'checkin1_missing', 'checkin2_go_missing'}, (mode, approved)  # positive control

    # Attack 3: a deliverable's mapping is dropped from the route spec. The deliverable stays an explicit
    # open obligation next to the one the route never served; it is neither dropped nor reported mapped.
    reduced = deepcopy(spec)
    reduced['deliverables'] = [rule for rule in spec['deliverables'] if rule['step'] != 'visualize.final']
    assert len(reduced['deliverables']) < len(spec['deliverables']), mode
    open_plan = routes.compile(reduced, reading, contract)
    rows = {item['id']: item for item in open_plan['deliverables']}
    assert sorted(rows) == ['d1', 'd2', 'd3'], mode
    assert [rows[name]['status'] for name in ('d1', 'd2', 'd3')] == ['mapped', 'open', 'open'], mode
    assert [(item['kind'], item['id']) for item in open_plan['open_obligations']] == [
        ('deliverable', 'd2'), ('deliverable', 'd3')], mode
    assert routes.plan_errors(open_plan) == [], mode  # an open obligation is explicit, not an unsound plan


def _frame(request_sha256, deliverables=('d1', 'd2', 'd3')):
    return {'schema_version': 1, 'kind': 'question-frame', 'request_sha256': request_sha256,
            'objective': 'Compute three fictional quantities of the toy model.',
            'deliverables': [{'id': f'D{number}', 'reading_ref': ref, 'description': f'fictional quantity {number}',
                              'acceptance': 'finite value with its uncertainty', 'statistic': 'none',
                              'units': 'fictional unit'} for number, ref in enumerate(deliverables, 1)],
            'constraints': [], 'unknowns': [],
            'assumptions': [{'number': 1, 'statement': 'The toy model has unit coupling.',
                             'basis': 'stated in the request', 'physics_critical': False}],
            'boundaries': []}


def _step(step_id):
    return {'id': step_id, 'kind': 'derive', 'purpose': 'fictional derive step', 'inputs': [],
            'outputs': [{'path': f'outputs/{step_id}.json', 'kind': 'result', 'required': True}], 'depends_on': [],
            'budget_share': {'fraction': 0.2}, 'protocols': [], 'review': [], 'obligations': []}


def _plan(frame, steps):
    return {'schema_version': 1, 'kind': 'judgment-plan', 'frame_sha256': _digest(frame), 'steps': steps,
            'deliverables': [{'id': f'D{number}', 'status': 'planned',
                              'outputs': [{'step': step['id'], 'path': step['outputs'][0]['path']}]}
                             for number, step in enumerate(steps, 1)]}


def _judgment_route(mode, routes, planning, expected_route=None):
    """Frame and plan checks of a task mode that no fixed route serves."""
    reading = _reading()
    sha = hashlib.sha256(f'fictional request of mode {mode}'.encode()).hexdigest()
    frame = _frame(sha)
    plan = _plan(frame, [_step('s1'), _step('s2'), _step('s3')])

    # Positive control: the complete frame and plan are adopted.
    assert planning.check_frame(frame, reading, sha) == [], mode
    assert planning.check_plan(plan, frame) == [], mode

    # Attack 1 (frame): a reading deliverable is dropped from the frame.
    dropped = planning.check_frame(_frame(sha, deliverables=('d1', 'd2')), reading, sha)
    assert any('reading deliverable d3 is missing from the frame' in problem for problem in dropped), (mode, dropped)

    # Attack 2 (plan): a frame deliverable is dropped; it stays an open obligation of the frame, so the plan is refused.
    without = deepcopy(plan)
    without['deliverables'] = [row for row in without['deliverables'] if row['id'] != 'D3']
    problems = planning.check_plan(without, frame)
    assert any('frame deliverable D3 is dropped by the plan; it stays an open obligation' in p for p in problems), problems

    # Attack 3 (plan): the step that produces a deliverable is dropped while its mapping stays.
    orphaned = deepcopy(plan)
    orphaned['steps'] = [step for step in orphaned['steps'] if step['id'] != 's3']
    problems = planning.check_plan(orphaned, frame)
    assert any('deliverable D3 maps to s3:outputs/s3.json, which is not declared' in p for p in problems), problems

    # Attack 4 (plan): a deliverable is held without saying why. A stated hold is the explicit form and is adopted.
    silent = deepcopy(plan)
    silent['deliverables'][2] = {'id': 'D3', 'status': 'held', 'outputs': []}
    assert any('held deliverable D3 states no held reason' in p for p in planning.check_plan(silent, frame)), mode
    held = deepcopy(silent)
    held['deliverables'][2]['held_reason'] = 'the fictional input is not supplied'
    assert planning.check_plan(held, frame) == [], mode  # positive control: a held deliverable is explicit

    # The edge from route selection is the judgment route, with its evidence; nothing is refused.
    decision = routes.select(dict(CONTRACT, task_mode=mode), reading, [])
    assert decision['route'] == (expected_route or routes.JUDGMENT) and decision['evidence'], decision
    if expected_route is None:
        assert decision['spec_sha256'] is None, decision
    else:
        # A newly installed ordinary route still needs its adopted typed scope.
        from ravel.controller.routes import study
        compiled = routes.compile(routes.find(expected_route), reading, dict(CONTRACT, task_mode=mode))
        assert routes.plan_errors(compiled) == [], compiled
        assert {r['id'] for r in compiled['deliverables']} == {r['id'] for r in reading['deliverables']}
        if expected_route == 'research':
            # The research route releases delivery only on complete campaign evidence: none exists here.
            import tempfile
            from ravel.controller.routes import research
            with tempfile.TemporaryDirectory() as run_dir:
                refused = research.gate('checkin3', {'plan': compiled, 'run_dir': run_dir})
            assert [row['code'] for row in refused] == ['research_evidence_incomplete'], refused
        else:
            assert study.gate('checkin1', {'plan': compiled}) == [
                {'code': 'study_not_bound', 'message': 'adopt the complete typed specification before CI1'}]


@dimension_case('ROUTE', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROUTE'), ids=str)
def test_route_request_keeps_its_stages_checkins_reviews_and_deliverables(nc, row):
    routes = require_controller('routes')
    mode = row.removeprefix('ROUTE-')
    reading = _reading(scan=mode == 'scan')
    decision = routes.select(dict(CONTRACT, task_mode=mode), reading, [])
    ordinary = {'generate': 'scoped', 'likelihood': 'scoped', 'calculation': 'calculation',
                'research': 'research', 'anomaly_search': 'research'}
    expected = FIXED.get(mode, ordinary.get(mode, routes.JUDGMENT))
    assert decision['route'] == expected, (row, decision['route'])
    if mode in FIXED:
        modules = tuple(require_controller(name) for name in (
            'routes.analysis', 'routes.analysis.checkins', 'routes.analysis.guard', 'routes.analysis.scan',
            'routes.compiler'))
        _fixed_route(nc, mode, routes, modules)
    else:
        _judgment_route(mode, routes, require_controller('judgment.planning'), ordinary.get(mode))


register(
    Mutation('M01', 'ravel.controller.routes.analysis.checkins:stage_errors', returns([]),
             ('test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-reproduce]',
              'test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-scan]'),
             binding=MUTATION_CONTROLLER, why='a plan without one of its route stages is not refused'),
    Mutation('M01', 'ravel.controller.routes.analysis.guard:admit', returns([]),
             ('test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-reinterpret]',),
             binding=MUTATION_CONTROLLER, why='a bulk step is dispatched before the check-ins'),
    Mutation('M01', 'ravel.controller.routes.analysis.guard:ladder_errors', returns([]),
             ('test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-reproduce]',),
             binding=MUTATION_CONTROLLER, why='a plan without its waypoint reaches the bulk rung'),
    Mutation('M27', 'ravel.controller.routes.compiler:population_holes', returns([]),
             ('test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-reproduce]',),
             binding=MUTATION_CONTROLLER, why='population equality reports no hole'),
    Mutation('M27', 'ravel.controller.routes.compiler:map_deliverables',
             passes_through(lambda found, *args, **kwargs: ([row for row in found[0] if row['status'] == 'mapped'],
                                                            found[1])),
             ('test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-scan]',),
             binding=MUTATION_CONTROLLER, why='an unserved deliverable is dropped instead of kept as an open obligation'),
    Mutation('M27', 'ravel.controller.judgment.planning:check_plan', returns([]),
             ('test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-survey]',
              'test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-research]'),
             binding=MUTATION_CONTROLLER, why='a judgment plan that drops a frame deliverable is adopted'),
    Mutation('M27', 'ravel.controller.judgment.planning:check_frame', returns([]),
             ('test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-calculation]',),
             binding=MUTATION_CONTROLLER, why='a frame that drops a reading deliverable is adopted'))


register(Mutation('M02', ('ravel.controller.routes.compiler:conformance_errors', 'ravel.controller.routes:conformance_errors'),
                  returns([]), ('test_route_request_keeps_its_stages_checkins_reviews_and_deliverables[ROUTE-reproduce]',),
                  binding=MUTATION_CONTROLLER, why='a plan is not compared with the route spec it claims'))
