"""Analysis-route rows: the reproduce, reinterpret and scan route refuses at its own transitions.

The route adapter (``ravel.controller.routes.analysis``) is called by the controller graph at fixed points:
``admit`` before a dispatch, ``checkin`` at an authority point, ``gate`` at a gate node and ``step`` when a
step outcome is joined. The adversary asks for generation before the inputs evidence and CHECK-IN 1, chooses
a check-in variant the pinned request does not admit, omits a manifest point from a harvest, keeps a
published gallery or number in a withheld plan, swaps a fast-response plan under a full-simulation request,
attaches a routine with another final state, targets a figure from memory, skips the smoke rung, or arms a
watcher without its preflight. Oracles are the adapter's typed refusals (code, row, named step or point),
the launch counter of a dispatcher that starts a step only on an empty refusal list, and files observed
from outside a confined launch; every positive control goes through the same entry with the governed input.

The run is a controller-owned store (real authority records, real adopted bytes with custody records); the
workers are inert and nothing here calls a model, a provider, the network or a native scientific tool.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import HostileLaunch, checkin_view, controller_run, store_root
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register, returns

ROUTE = 'ravel.controller.routes.analysis'
PREPARE = ('env', 'inputs.census', 'inputs.route', 'inputs.traps', 'inputs.figures', 'inputs.cost')
PRODUCTION_RUNGS = ('smoke', 'pilot', 'full', 'scan')
FAST_RESPONSE = 'container'  # a contract detector mode that supplies a fast detector response
STATISTIC = 'best-sr-counting'
FULL_SIMULATION_HEADLINE = ('Full simulation of the detector is requested; the available fast response does not '
                            'supply that fidelity.')
ANALYSIS_ID = 'toy-widget-search'


# ---------------------------------------------------------------- the fictional request and its evidence

def _reading(*, scan=False, values=(100, 200, 300), full_simulation=False, panels=1):
    facts = [{'id': 'F1', 'type': 'model_term', 'value': {'text': 'widget pair'}}]
    if scan:
        facts.append({'id': 'F2', 'type': 'parameter_values',
                      'value': {'text': 'masses ' + ', '.join(map(str, values)), 'values': list(values),
                                'unit': 'GeV', 'variable': 'm_widget'}})
    deliverables = [{'id': 'D1', 'artifact': {'kind': 'inference', 'require': {}}, 'claim_kind': 'exclusion'}]
    deliverables += [{'id': f'D{n + 2}', 'artifact': {'kind': 'figure', 'require': {}}, 'claim_kind': 'exclusion'}
                     for n in range(panels)]
    boundaries = []
    if full_simulation:
        boundaries.append({'id': 'B1', 'class': 'inaccessible_input', 'statement': FULL_SIMULATION_HEADLINE})
    return {'kind': 'request-reading', 'facts': facts, 'deliverables': deliverables, 'constraints': [],
            'boundaries': boundaries, 'ambiguities': []}


def _contract(task_mode='reproduce', **extra):
    return {'schema_version': 1, 'task_mode': task_mode, 'detector_mode': FAST_RESPONSE, 'stat_mode': STATISTIC,
            'compute_plan': 'scan' if task_mode == 'scan' else 'full', **extra}


def _withheld_contract(task_mode='reproduce'):
    restriction = {'kind': 'blinded', 'identifiers': {'analysis': [ANALYSIS_ID]}, 'origin': 'request',
                   'statement': 'the published limits of the toy search stay withheld until delivery',
                   'evidence': [{'start': 0, 'end': 8, 'text': 'withheld'}]}
    return _contract(task_mode, targets={'analysis': [ANALYSIS_ID]}, forbidden_sources=[restriction])


def _route_document(**extra):
    document = {'summary': 'We reproduce the toy widget search limit with the preserved selection and a fast '
                           'detector response, checking a cheap cutflow first.',
                'routine': {'id': 'TOY_ROUTINE_1', 'ecosystem': 'native'}, 'model': 'toy widget pair model',
                'final_state': 'two jets and missing momentum', 'energy': '13 TeV', 'detector_mode': FAST_RESPONSE,
                'stat_mode': STATISTIC, 'method': 'smoke rung first, then the full rung', 'hepdata_record': 'rec-7',
                'assumptions': [{'id': 'A1', 'statement': 'The widget decays promptly.',
                                 'reason': 'the model card fixes a short lifetime',
                                 'alternatives': ['displaced decays'], 'result_sensitive': True}],
                'decisions': [], 'approximations': [], 'mismatches': [], 'escalate': []}
    document.update(extra)
    return document


def _trap_record(*, flagged=True):
    from ravel.workflow.trap_sweep import build
    verdicts = [{'id': f'T{n}', 'hit': False, 'evidence': f'checked trap T{n} against the toy card'}
                for n in range(1, 13)]
    verdicts[7] = {'id': 'T8', 'hit': True, 'evidence': 'the toy selection uses an outdated efficiency',
                   'consequence': 'acceptance may shift by a few percent', 'flag_number': 2 if flagged else None}
    return build({'verdicts': verdicts})


def _figure_target(*, panels=1, axes=True, source=True):
    targets = []
    for n in range(panels):
        row = {'figure_id': f'Panel {n + 1}', 'role': 'summary', 'caption_snippet': 'Limits on the widget mass'}
        if axes:
            row['axes'] = {'x': 'linear', 'y': 'log', 'source': 'read-from-published'}
        if source:
            row['source'] = 'figure-inspection'
        targets.append(row)
    return {'targets': targets}


def _prepare_documents(*, withheld=False, panels=1, cost_mode='full', cost_points=1, gallery_canary=None):
    if withheld:
        figure_target, gallery = {'targets': []}, {'figures': []}
        waypoint = {'withheld_waypoints': [{'kind': 'cutflow-monotone', 'counts': [1000, 640, 300, 41]}]}
    else:
        figure_target = _figure_target(panels=panels)
        gallery = {'figures': [{'figure_id': 'Panel 1', 'caption': 'Limits on the widget mass'}]}
        waypoint = {'element': 'the first three cutflow rows at smoke statistics',
                    'expectation': 'within ten percent of the published rows',
                    'why_cheap': 'one smoke point of one thousand events'}
    if gallery_canary:
        gallery = {'figures': [{'figure_id': 'Panel 1', 'caption': gallery_canary}]}
    return {
        'env': {'outputs/environment.json': {
            'tools': [{'name': 'event generator', 'status': 'available', 'required': True},
                      {'name': 'statistics engine', 'status': 'available', 'required': True}],
            'operations': ['acquire-published', 'analysis-lifecycle', 'figure-comparison', 'lifecycle-routine-recast',
                           'lifecycle-scan-aggregation']}},
        'inputs.census': {'outputs/inputs/resource_census.json': {
            'rungs': {'records': {'status': 'OK'}, 'routines': {'status': 'OK'}, 'code-search': {'status': 'ABSENT'}}}},
        'inputs.route': {'outputs/route_analysis.json': _route_document()},
        'inputs.traps': {'outputs/trap_sweep.json': _trap_record()},
        'inputs.figures': {'outputs/figure_target.json': figure_target, 'outputs/gallery.json': gallery,
                           'outputs/waypoint.json': waypoint},
        'inputs.cost': {'outputs/cost_preflight.json': {'mode': cost_mode, 'points': cost_points,
                                                        'status': 'uncalibrated',
                                                        'basis': 'no matched pilot on this host yet',
                                                        'walltime_h': None}},
    }


class _Run:
    """One controller-owned analysis run: the store, the run directory, the compiled plan and the evidence."""

    def __init__(self, nc, *, name='nc-run-one', scan=False, values=(100, 200, 300), reading=None, contract=None):
        self.nc = nc
        self.routes, self.analysis = require_controller('routes', 'routes.analysis')
        self.scan = scan
        self.store, self.dir = controller_run(nc, name, mode='autonomous')
        self.reading = reading or _reading(scan=scan, values=values)
        self.contract = contract or _contract('scan' if scan else 'reproduce')
        self.plan = self.routes.compile(self.routes.find('analysis.scan' if scan else 'analysis'), self.reading,
                                        self.contract)
        self.states, self.reviews, self.ci1 = {}, {}, None

    def context(self):
        return {'store': self.store, 'run_dir': str(self.dir), 'plan': self.plan, 'reading': self.reading,
                'contract': self.contract, 'state': {'steps': self.states, 'reviews': self.reviews}, 'supplied': []}

    def step(self, step_id):
        return next(s for s in self.plan['steps'] if s['id'] == step_id)

    def points(self):
        return [s for s in self.plan['steps'] if s['id'].startswith('scan.point.')]

    def adopt(self, step_id, path, document):
        """Write ``document`` where the governed step adopts a declared output and record its custody."""
        import hashlib
        raw = (json.dumps(document, indent=1, sort_keys=True) + '\n').encode()
        target = self.dir / 'steps' / step_id / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        self.store.append('custody', {'schema_version': 1, 'artifact': f'{step_id}:{path}', 'step_id': step_id,
                                      'attempt': 1, 'path': path, 'destination': f'steps/{step_id}/{path}',
                                      'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'accepted'})

    def finish(self, step_id, status='completed', reason=None):
        """The controller's own record that the step ended (the outcome the join folds into the run state)."""
        step = self.step(step_id)
        found = {'step_id': step_id, 'attempt': 1, 'status': status, 'outputs': [], 'receipts': [f'receipt-{step_id}'],
                 'reason': reason}
        self.store.append('step-outcome', {'step_id': step_id, 'attempt': 1, 'status': status, 'outcome': found})
        self.states[step_id] = {'status': status, 'attempts': 1, 'receipts': found['receipts'], 'reason': reason}
        return found

    def prepare(self, *, withheld=False, panels=None, skip=(), claim_only=False):
        """Adopt the prepare-phase evidence (or only claim the steps done) and bind the plan to it."""
        grid = (self.plan.get('parameters') or {}).get('grid') or {}
        documents = _prepare_documents(withheld=withheld, panels=panels or 1, cost_mode='scan' if self.scan else 'full',
                                       cost_points=len(grid.get('points') or ()) or 1)
        for step_id, files in documents.items():
            if step_id in skip:
                continue
            for path, document in files.items():
                if not claim_only:
                    self.adopt(step_id, path, document)
            self.finish(step_id)
        bound = self.analysis.bind(self.plan, self.context())
        if bound is not None:
            self.plan = bound

    def grant_ci1(self, rung=None):
        authority = require_controller('authority')
        self.ci1 = authority.request(self.store, 'approve_plan',
                                     {'view': checkin_view(self.store, 'approve_plan', plan_sha256=self.plan['sha256'])},
                                     {'rung': rung or ('scan' if self.scan else 'full')})
        assert self.ci1.get('decision') == 'approve', self.ci1
        return self.ci1

    def grant_go(self):
        authority = require_controller('authority')
        view = checkin_view(self.store, 'go', approve_plan=self.ci1['id'], waypoint_sha256='b' * 64)
        record = authority.request(self.store, 'go', {'view': view}, {'rung': 'scan' if self.scan else 'full'})
        assert record.get('decision') == 'go', record
        return record


class _Dispatcher:
    """A dispatcher that starts a step only when the adapter's ``admit`` answers no refusal.

    A start is a file under the case's own root, so the launch count is observed from outside the adapter.
    """

    def __init__(self, nc, run):
        self.run, self.root = run, nc.root / 'launches'
        self.root.mkdir(parents=True, exist_ok=True)

    def __call__(self, step):
        refusals = self.run.analysis.admit(step, self.run.context())
        if not refusals:
            (self.root / step['id']).write_text('started')
        return refusals

    def started(self):
        return sorted(p.name for p in self.root.iterdir())


def _codes(errors):
    return {e['code'] for e in errors}


def _rows(errors):
    return {e['row'] for e in errors}


def _graph_state(run):
    """The graph state the controller keeps for ``run`` (ids and digests; the bytes are in the store)."""
    def blob(value):
        return run.store.put_blob(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                             allow_nan=False).encode())
    intake = run.store.append('intake', {'contract_blob': blob(run.contract), 'reading_blob': blob(run.reading),
                                         'task_mode': run.contract.get('task_mode')})
    return {'run': {'run_id': run.store.run_id, 'run_dir': str(run.dir), 'store_root': str(run.store.store_root)},
            'request': {'intake_record_id': intake}, 'route': {'id': run.plan['route']['id']},
            'plan': {'sha256': run.plan['sha256'], 'blob': blob(run.plan), 'revision': run.plan.get('revision', 0)},
            'steps': deepcopy(run.states), 'authority': {}}


# ---------------------------------------------------------------- R07: no generation before inputs and CHECK-IN 1

@case('R07', binding=CONTROLLER)
def test_R07_a_reproduction_request_routed_to_generation_is_refused_before_inputs_evidence_and_check_in_1(nc):
    routes, analysis = require_controller('routes', 'routes.analysis')
    run = _Run(nc)
    by_id = {s['id']: s for s in run.plan['steps']}

    def ancestors(step_id):
        seen, stack = set(), list(by_id[step_id]['depends_on'])
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(by_id[current]['depends_on'])
        return seen

    # The route graph itself: every production step has the environment and 02-inputs steps below it, so no
    # edge leads from the request's intake to generation without them.
    production = [s for s in run.plan['steps'] if s.get('rung') in PRODUCTION_RUNGS]
    assert {s['id'] for s in production} >= {'recast.smoke', 'run.full'}
    for step in production:
        assert set(PREPARE) <= ancestors(step['id']), step['id']

    # A. Straight to generation: nothing prepared, no CHECK-IN 1 authority.
    dispatch = _Dispatcher(nc, run)
    refused = dispatch(run.step('recast.smoke'))
    assert _codes(refused) == {'prepare_step_open', 'checkin1_missing'}, refused
    assert _rows(refused) == {'R07'}
    assert {e['step'] for e in refused if e['code'] == 'prepare_step_open'} == set(PREPARE)
    for step in production:
        assert dispatch(step), f'{step["id"]} was admitted without the inputs evidence'
    assert 'prepare_step_open' in _codes(analysis.gate('checkin1->execute', run.context()))
    assert dispatch.started() == [], 'a production step started'

    # B. The steps are claimed done in the run state but no evidence was adopted for them.
    claimed = _Run(nc, name='nc-run-two')
    claimed.prepare(claim_only=True)
    claimed.grant_ci1()
    dispatch_claimed = _Dispatcher(nc, claimed)
    refused = dispatch_claimed(claimed.step('recast.smoke'))
    assert 'evidence_missing' in _codes(refused) and 'prepare_step_open' not in _codes(refused), refused
    assert dispatch_claimed.started() == []

    # Positive control: evidence adopted for every prepare step and the CHECK-IN 1 authority record exists.
    ready = _Run(nc, name='nc-run-three')
    ready.prepare()
    dispatch_ready = _Dispatcher(nc, ready)
    assert _codes(dispatch_ready(ready.step('recast.smoke'))) == {'checkin1_missing'}  # evidence alone is not CHECK-IN 1
    ready.grant_ci1()
    assert dispatch_ready(ready.step('recast.smoke')) == []
    assert dispatch_ready.started() == ['recast.smoke']
    assert _codes(dispatch_ready(ready.step('run.full'))) == {'checkin2_go_missing'}  # the bulk rung also waits for GO


register(Mutation('M01', f'{ROUTE}.guard:prepare_errors', returns(lambda: []), ('R07',), binding=MUTATION_CONTROLLER,
                  why='a production step is admitted whatever the prepare phase holds'),
         Mutation('M02', f'{ROUTE}.checkins:latest_authority', returns('authority-record-forged'), ('R07',),
                  binding=MUTATION_CONTROLLER, why='a CHECK-IN 1 authority record is assumed to exist'))


# ---------------------------------------------------------------- P04: no omitted point in the harvest

def _assembly(grid_points, statuses, *, claim_full=True):
    rows = [{'tag': p['id'], 'parameters': p['parameters'], 'status': statuses[p['id']]}
            for p in grid_points if p['id'] in statuses]
    completed = [r for r in rows if r['status'] == 'completed']
    document = {'n_planned': len(grid_points), 'n_done': len(completed), 'point_population': rows,
                'points': [{'tag': r['tag'], 'statistic': 'CLs'} for r in completed]}
    document['n_missing'] = 0 if claim_full else len(grid_points) - len(completed)
    document['missing_tags'] = [] if claim_full else [p['id'] for p in grid_points if p['id'] not in
                                                      {r['tag'] for r in completed}]
    return document


def _harvest(run, document, *, states):
    """The assembly step's outcome joined by the controller: ``(errors)`` after the point states are folded."""
    for step_id, (status, reason) in states.items():
        run.finish(step_id, status, reason)
    assemble = run.step('scan.assemble')
    run.adopt('scan.assemble', 'outputs/scan.json', document)
    outcome = run.finish('scan.assemble')
    return run.analysis.step(assemble, outcome, run.context())


@case('P04', binding=CONTROLLER)
def test_P04_a_point_omitted_from_the_harvest_is_refused_by_population_equality_and_the_hole_stays_explicit(nc):
    routes, analysis = require_controller('routes', 'routes.analysis')
    run = _Run(nc, scan=True, values=(100, 200, 300))
    grid = run.plan['parameters']['grid']
    by_mass = {p['parameters']['m_widget']: p['id'] for p in grid['points']}
    assert sorted(by_mass) == [100, 200, 300], 'the approved grid is the request\'s three masses'
    steps = {p['parameters']['point_id']: p['id'] for p in run.points()}
    done = {steps[tag]: ('completed', None) for tag in by_mass.values()}

    # A. The harvest leaves the 200 GeV point out of its population and still claims every point.
    omitted = _harvest(run, _assembly(grid['points'], {by_mass[100]: 'completed', by_mass[300]: 'completed'}),
                       states=done)
    gap = [e for e in omitted if e['code'] == 'scan_point_omitted']
    assert len(gap) == 1 and gap[0]['row'] == 'SW33', omitted
    assert gap[0]['pins'] == [by_mass[200]] and by_mass[200] in gap[0]['message'], gap
    assert 'scan_missing_tags' in _codes(omitted), 'the claim of no missing tags disagrees with the population'

    # B. A point the controller saw fail is claimed completed: full coverage over a hole is refused.
    failed = _Run(nc, name='nc-run-two', scan=True, values=(100, 200, 300))
    grid_b = failed.plan['parameters']['grid']
    tags = {p['parameters']['m_widget']: p['id'] for p in grid_b['points']}
    steps_b = {p['parameters']['point_id']: p['id'] for p in failed.points()}
    states_b = {steps_b[tags[100]]: ('completed', None), steps_b[tags[200]]: ('failed', 'toy native crash'),
                steps_b[tags[300]]: ('completed', None)}
    overclaimed = _harvest(failed, _assembly(grid_b['points'], {t: 'completed' for t in tags.values()}), states=states_b)
    assert {'scan_coverage_overclaimed', 'scan_point_substituted'} <= _codes(overclaimed), overclaimed
    assert next(e for e in overclaimed if e['code'] == 'scan_coverage_overclaimed')['pins'] == [tags[200]]
    # The hole is explicit in the original domain: ending the run records the failed point with its status.
    population = analysis.ending('qualified ending', failed.context())
    assert population['holes'] == [tags[200]] and sorted(population['completed']) == sorted([tags[100], tags[300]])
    kept = failed.store.latest('analysis-scan-population')['record']
    assert [(h['point'], h['status'], h['reason']) for h in kept['holes']] == [(tags[200], 'failed', 'toy native crash')]

    # Positive controls: every point listed with its status passes, and an honest assembly that lists the
    # failed point as a hole is not an error of the assembly either.
    full = _Run(nc, name='nc-run-three', scan=True, values=(100, 200, 300))
    grid_c = full.plan['parameters']['grid']
    steps_c = {p['parameters']['point_id']: p['id'] for p in full.points()}
    all_done = {steps_c[p['id']]: ('completed', None) for p in grid_c['points']}
    assert _harvest(full, _assembly(grid_c['points'], {p['id']: 'completed' for p in grid_c['points']}),
                    states=all_done) == []
    honest = _Run(nc, name='nc-run-four', scan=True, values=(100, 200, 300))
    grid_d = honest.plan['parameters']['grid']
    ids = [p['id'] for p in grid_d['points']]
    steps_d = {p['parameters']['point_id']: p['id'] for p in honest.points()}
    states_d = {steps_d[ids[0]]: ('completed', None), steps_d[ids[1]]: ('failed', 'toy native crash'),
                steps_d[ids[2]]: ('completed', None)}
    assert _harvest(honest, _assembly(grid_d['points'], {ids[0]: 'completed', ids[1]: 'failed', ids[2]: 'completed'},
                                      claim_full=False), states=states_d) == []


register(Mutation('M27', f'{ROUTE}.scan:population_holes', returns(lambda: []), ('P04',), binding=MUTATION_CONTROLLER,
                  why='population equality never reports a hole'))


# ---------------------------------------------------------------- C04: the CHECK-IN 1 variant is the pinned request's

@case('C04', binding=CONTROLLER)
def test_C04_a_variant_the_pinned_request_does_not_admit_or_cannot_bind_holds_the_approval(nc):
    routes, analysis = require_controller('routes', 'routes.analysis')
    graph = require_controller('graph')
    from ravel.workflow import graph_nodes

    # A. The pinned request is a calculation, whose only admitted CHECK-IN 1 variant is its own; the analysis
    #    view would silently present the reproduction form.
    mismatched = _Run(nc, contract=_contract('calculation'))
    mismatched.prepare()
    view = analysis.checkin('approve_plan', mismatched.context())
    unfit = [e for e in view['errors'] if e['code'] == 'checkin_variant_unfit']
    assert view['variant'] is None and len(unfit) == 1 and unfit[0]['row'] == 'C04', view['errors']
    assert 'calculation' in unfit[0]['message'] and 'reproduction' not in unfit[0]['message'].split('admit')[-1]
    with pytest.raises(graph_nodes.RecoveryHold) as held:
        graph.checkin_view('checkin1', _graph_state(mismatched), mismatched.store)
    assert held.value.reason == 'checkin_incomplete' and 'checkin_variant_unfit' in str(held.value.would_make_possible), held.value

    # B. A research request admits every variant; its source-restriction census is unreadable, so no variant
    #    can be bound and nothing is chosen for it.
    broken = _Run(nc, name='nc-run-two', contract=_contract('research', forbidden_sources=[
        {'kind': 'blinded', 'reason': 'no statement and no evidence'}]))
    broken.prepare()
    view = analysis.checkin('approve_plan', broken.context())
    assert view['variant'] is None and 'source_restrictions_invalid' in _codes(view['errors']), view['errors']
    assert {e['row'] for e in view['errors'] if e['code'] == 'source_restrictions_invalid'} == {'C04'}

    # Positive control: a valid research census binds the variant the pinned request selects, with no C04 refusal.
    valid = _Run(nc, name='nc-run-three', contract=dict(_withheld_contract(), task_mode='research'))
    valid.prepare(withheld=True)
    view = analysis.checkin('approve_plan', valid.context())
    assert view['variant'] == 'reference_withheld', view['errors']
    assert not [e for e in view['errors'] if e['row'] == 'C04'], view['errors']
    plain = _Run(nc, name='nc-run-four')
    plain.prepare()
    view = analysis.checkin('approve_plan', plain.context())
    assert view['variant'] == 'reproduction' and view['errors'] == [], view['errors']
    graph.checkin_view('checkin1', _graph_state(plain), plain.store)  # the graph shows it: no hold


register(Mutation('M05', f'{ROUTE}.checkins:variant', returns(lambda: ('reproduction', [])), ('C04',),
                  binding=MUTATION_CONTROLLER, why='the variant is chosen silently, whatever the pinned request says'))


# ---------------------------------------------------------------- C10: the withheld reference stays unshown

@case('C10', binding=CONTROLLER)
def test_C10_a_withheld_plan_that_keeps_a_published_gallery_or_number_is_refused_before_display(nc):
    routes, analysis = require_controller('routes', 'routes.analysis')
    caption = nc.effects.canary('published-caption')
    run = _Run(nc, contract=_withheld_contract())
    run.prepare(withheld=True)
    figures = run.step('inputs.figures')
    outcome = {'status': 'completed', 'attempt': 1, 'receipts': ['receipt-inputs.figures']}
    assert analysis.step(figures, outcome, run.context()) == [], 'positive control: internal diagnostics are allowed'

    # A. A published gallery kept in the withheld plan's figure evidence (the figure target names a panel).
    run.adopt('inputs.figures', 'outputs/figure_target.json', {'targets': [
        {'figure_id': 'Panel 1', 'caption_snippet': caption.value, 'axes': {'x': 'linear', 'y': 'log'},
         'source': 'figure-inspection'}]})
    run.adopt('inputs.figures', 'outputs/gallery.json', {'figures': [{'figure_id': 'Panel 1', 'caption': caption.value}]})
    refused = analysis.step(figures, outcome, run.context())
    assert _codes(refused) == {'figure_target_withheld'} and _rows(refused) == {'C10'}, refused
    assert 'figure_target_withheld' in _codes(analysis.gate('checkin1->execute', run.context()))
    view = analysis.checkin('approve_plan', run.context())
    assert view['variant'] == 'reference_withheld' and 'gallery' not in view['required_sections']
    assert caption.value not in json.dumps(view, sort_keys=True), 'the published caption reached the displayed check-in'

    # B. A published numeric reference nested inside the withheld waypoint evidence.
    nested = _Run(nc, name='nc-run-two', contract=_withheld_contract())
    nested.prepare(withheld=True)
    nested.adopt('inputs.figures', 'outputs/waypoint.json', {
        'withheld_waypoints': [{'kind': 'cutflow-monotone', 'counts': [1000, 640, 300, 41]}],
        'diagnostic': {'published_comparison': {'value': 1.7, 'unit': 'fb'}}})
    refused = analysis.step(nested.step('inputs.figures'), outcome, nested.context())
    assert _codes(refused) == {'waypoint_withheld_reference'} and _rows(refused) == {'C10'}, refused
    assert 'published_comparison' in refused[0]['message']

    # C. The executed waypoint evidence shown at CHECK-IN 2 carries the published number.
    for target, extra in ((nested, {'published_comparison': {'value': 1.7}}), (None, None)):
        run2 = target or _Run(nc, name='nc-run-three', contract=_withheld_contract())
        if target is None:
            run2.prepare(withheld=True)
        run2.grant_ci1()
        doc = {'summary': 'The smoke cutflow is monotone.', 'element': 'cutflow counts', 'expectation': 'monotone',
               'evidence': 'counts fall at each cut'}
        run2.adopt('visualize.waypoint', 'outputs/waypoint.json', dict(doc, **(extra or {})))
        run2.finish('visualize.waypoint')
        go = analysis.checkin('go', run2.context())
        if extra:
            assert _codes(go['errors']) == {'waypoint_withheld_reference'} and _rows(go['errors']) == {'C10'}, go['errors']
        else:
            assert go['errors'] == [], go['errors']  # positive control: the same waypoint without the reference


register(Mutation('M15', 'ravel.validation.checkin_withheld:_published_fields', returns(lambda: iter(())), ('C10',),
                  binding=MUTATION_CONTROLLER, why='published fields are never found in a withheld plan'),
         Mutation('M14', f'{ROUTE}.evidence:withheld', returns(False), ('C10',), binding=MUTATION_CONTROLLER,
                  why='no plan is treated as reference-withheld'))


# ---------------------------------------------------------------- C26: the requested detector fidelity is pinned

@case('C26', binding=CONTROLLER)
def test_C26_a_fast_response_plan_or_result_never_satisfies_a_full_simulation_request(nc):
    routes, analysis = require_controller('routes', 'routes.analysis')
    fidelity = analysis.fidelity
    # The sink half of this row (the delivery sink refusing a result below the pinned fidelity) belongs to the
    # delivery package; here the plan-side and result-side refusals of the route and its gate are the oracle.
    run = _Run(nc, reading=_reading(full_simulation=True))
    assert run.plan['parameters']['fidelity'] == 'full-simulation', 'the request headline is pinned at compile'
    run.prepare()
    assert {s['id'] for s in run.plan['steps'] if (s['parameters'].get('task') or {}).get('detector_mode')} == \
        {'recast.smoke', 'run.full'}

    # A. The plan keeps the full-simulation headline but both of its detector steps use the fast response.
    plan_gate = analysis.gate('checkin1->execute', run.context())
    downgraded = [e for e in plan_gate if e['code'] == 'fidelity_downgraded']
    assert sorted(e['step'] for e in downgraded) == ['recast.smoke', 'run.full'], plan_gate
    assert _rows(downgraded) == {'C26'} and all(e['pins'] == ['B1'] for e in downgraded)
    assert {'recast.smoke', 'run.full'} <= {e['step'] for e in plan_gate if e['row'] == 'C26'}

    # B. A fast-response result is delivered for the full-simulation request.
    run.adopt('run.full', 'outputs/limits.json', {'statistic': 'CLs', 'detector_mode': FAST_RESPONSE})
    deliver = analysis.gate('checkin3->deliver', run.context())
    late = [e for e in deliver if e['code'] == 'fidelity_delivered_below_request']
    assert len(late) == 1 and late[0]['row'] == 'C26' and 'run.full:outputs/limits.json' in late[0]['message'], deliver
    assert [e['code'] for e in fidelity.result_errors(run.reading, run.contract, {'x': FAST_RESPONSE})] == \
        ['fidelity_delivered_below_request']

    # The scope stays held until an actual revised request authorizes it: the same plan under a request that
    # asks for a detector stage (a fast response is then the requested fidelity) is not refused, and a result
    # at full simulation satisfies the full-simulation request.
    revised = _reading()
    revised['constraints'].append({'id': 'K1', 'type': 'requested_stage', 'value': {'stage': 'detector'}})
    assert fidelity.plan_errors(revised, run.contract, run.plan) == []
    assert fidelity.result_errors(revised, run.contract, {'x': FAST_RESPONSE}) == []
    assert fidelity.result_errors(run.reading, run.contract, {'x': 'full-simulation'}) == []
    assert fidelity.plan_errors(run.reading, run.contract, run.plan), 'the unrevised request still holds the scope'


register(Mutation('M11', f'{ROUTE}.fidelity:below', returns(False), ('C26',), binding=MUTATION_CONTROLLER,
                  why='a lower detector fidelity never ranks below the request'),
         Mutation('M02', f'{ROUTE}.fidelity:requested', returns(lambda: {'level': None, 'evidence': []}), ('C26',),
                  binding=MUTATION_CONTROLLER, why='the fidelity pinned at intake is ignored'))
