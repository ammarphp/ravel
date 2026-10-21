"""Route contract doubles and source-backed adapters, selected without fallback.

The local doubles contain data checks, never row identifiers or expected outcomes. Real probes
exercise actual route checks when those packages are installed. Publication/ledger peers remain
explicit harness doubles; a component test is not whole-controller scientific acceptance.
"""
from copy import deepcopy
from importlib import import_module
import json


def fixture(kind):
    return {'kind': kind, 'route_pinned': True, 'request_kind': 'development',
            'deliverables': ['supplied-result', 'generated-result'],
            'covered': ['supplied-result', 'generated-result'], 'requested_stages': ['generate', 'detector'],
            'stages': ['generate', 'detector'],
            'expected': {'units': 'GeV', 'statistic': 'delta_chi2'},
            'actual': {'units': 'GeV', 'statistic': 'delta_chi2'},
            'build_custody': True, 'training': False,
            'requested_final_state': 'two jets', 'routine_final_state': 'two jets',
            'panels': [{'figure_id': 'Panel 1', 'axes': {'x': 'linear', 'y': 'log'},
                        'source': 'read-from-published'}], 'requested_panels': 1,
            'recipe': {'path': 'inputs/recipe.json', 'sha256': 'a' * 64, 'retained': True},
            'steps': [{'id': 'smoke', 'rung': 'smoke', 'waypoint': True, 'depends_on': []},
                      {'id': 'full', 'rung': 'full', 'depends_on': ['smoke']}],
            'watcher': {'durable': True, 'preflight': True, 'required': 5, 'arguments': ['a', 'b', 'c', 'd', 'e']}}


def guard(p):
    errors = []
    kind = p['kind']
    if kind == 'dispatch' and not p['route_pinned']:
        errors.append('route_not_pinned')
    if kind == 'population' and set(p['deliverables']) - set(p['covered']):
        errors.append('missing_deliverable')
    if kind == 'stages' and set(p['requested_stages']) - set(p['stages']):
        errors.append('missing_stage')
    if kind == 'manuscript' and not p['build_custody']:
        errors.append('manuscript_unreceipted')
    if kind == 'quantity':
        if 'units' in p['expected'] and p['actual'].get('units') != p['expected']['units']:
            errors.append('units_changed_or_missing')
        if 'statistic' in p['expected'] and p['actual'].get('statistic') != p['expected']['statistic']:
            errors.append('statistic_changed_or_missing')
    if kind == 'inference' and p['training']:
        errors.append('training_not_admitted')
    if kind == 'routine' and p['routine_final_state'] != p['requested_final_state']:
        errors.append('routine_final_state_mismatch')
    if kind == 'figure':
        if len(p['panels']) < p['requested_panels']:
            errors.append('figure_panels_dropped')
        if any(not row.get('source') or row.get('axes', {}).get('x') not in ('linear', 'log')
               or row.get('axes', {}).get('y') not in ('linear', 'log') for row in p['panels']):
            errors.append('figure_source_missing')
    if kind == 'recipe' and not p['recipe'].get('retained'):
        errors.append('external_recipe_missing')
    if kind == 'ladder':
        above = {row['id'] for row in p['steps'] if row.get('waypoint')}
        if any(row.get('rung') in ('full', 'scan') and not above.intersection(row.get('depends_on', []))
               for row in p['steps']):
            errors.append('rung_ladder_skipped')
    if kind == 'watcher':
        if not p['watcher']['durable']:
            errors.append('watcher_target_not_durable')
        if not p['watcher']['preflight'] or len(p['watcher']['arguments']) < p['watcher']['required']:
            errors.append('watcher_preflight_failed')
    return {'errors': errors, 'notices': [], 'disclosures': []}


def fake_probe(nc, p):
    return guard(p)


def real_probe(nc, p):
    kind = p['kind']
    errors = []
    if kind == 'dispatch':
        from nc_contract import FakeRunStore
        routes = import_module('ravel.controller.routes')
        graph = import_module('ravel.controller.graph')
        reading = {'kind': 'request-reading', 'facts': [], 'constraints': [], 'boundaries': [],
                   'ambiguities': [], 'deliverables': [{'id': 'd1', 'artifact': {'kind': 'inference', 'require': {}},
                                                       'claim_kind': 'calculation'}]}
        decision = routes.select({'task_mode': 'calculation', 'prompt': 'Development: compute a toy rate.'}, reading, [])
        assert decision['route'] not in ('inspect', 'legacy'), 'development phrasing dropped scientific obligations'
        store = FakeRunStore('dispatch', root=nc.root / 'store')
        route = {'id': 'judgment'}
        if p['route_pinned']:
            route['record_id'] = store.append('route', {'route': 'judgment'})
        admitted, _, _ = graph._admitted({'route': route}, store, {'steps': [{'id': 'step-one'}]}, ['step-one'], {})
        if not admitted:
            errors.append('route_not_pinned')
    elif kind in ('population', 'stages'):
        contracts = import_module('ravel.controller.routes.study.contracts')
        reading = {'deliverables': [{'id': item} for item in p['deliverables']],
                   'constraints': [{'type': 'requested_stage', 'value': {'stage': item}}
                                   for item in p['requested_stages']]}
        missing = contracts.scope(reading, p['covered'], p['stages'])
        if any(row['kind'] == ('stage' if kind == 'stages' else 'deliverable') for row in missing):
            errors.append('missing_stage' if kind == 'stages' else 'missing_deliverable')
    elif kind == 'quantity':
        contracts = import_module('ravel.controller.routes.study.contracts')
        for error in contracts.quantity_errors(p['expected'], p['actual']):
            if error.startswith('units '):
                errors.append('units_changed_or_missing')
            elif error.startswith('statistic '):
                errors.append('statistic_changed_or_missing')
            else:
                raise AssertionError(f'unexpected quantity refusal: {error}')
    elif kind == 'manuscript':
        manuscript = import_module('ravel.controller.routes.manuscript')
        steps = [{'id': 'author', 'kind': 'author', 'depends_on': [],
                  'outputs': [{'path': 'claims.json', 'kind': 'claim_map', 'required': True}]},
                 {'id': 'assemble', 'kind': 'subgraph', 'graph': {'id': 'manuscript.build'}, 'depends_on': ['author']},
                 {'id': 'build', 'kind': 'operate', 'operation': 'manuscript-build', 'depends_on': ['assemble'],
                  'outputs': [{'path': 'result.pdf', 'kind': 'document', 'required': True}]}]
        plan = {'route': {'id': 'manuscript'}, 'steps': steps,
                'deliverables': [{'id': 'd', 'status': 'mapped', 'artifact_kind': 'document',
                                  'step': 'build', 'output': 'result.pdf'}]}
        outcomes = {step['id']: {'status': 'completed'} for step in steps}
        custody = {step['id']: {'step_id': step['id'], 'path': 'result.pdf' if step['id'] == 'build' else 'stage.json',
                                'status': 'accepted', 'sha256': 'a' * 64} for step in steps}
        if not p['build_custody']:
            custody.pop('build')
        observed = manuscript.delivery_errors(plan, outcomes=outcomes, custody=custody)
        for item in observed:
            assert item['code'] == 'manuscript_unreceipted', observed
            errors.append('manuscript_unreceipted')
    elif kind == 'inference':
        training = import_module('ravel.controller.routes.ml.training')
        step = {'id': 'infer', 'kind': 'operate', 'operation': 'ml-inference',
                'parameters': {'task': {'training': p['training']}}}
        observed = training.inference_errors(step, {'route': {'id': 'ml.inference'}, 'steps': [step]})
        if observed:
            assert {row['code'] for row in observed} == {'ml_inference_requests_training'}
            errors.append('training_not_admitted')
    elif kind in ('routine', 'figure'):
        from test_nc_analysis_route import _Run, _route_document, _figure_target
        evidence = import_module('ravel.controller.routes.analysis.evidence')
        run = _Run(nc)
        if kind == 'routine':
            run.reading['constraints'] = [{'type': 'final_state', 'value': {'final_state': p['requested_final_state']}}]
            run.adopt('inputs.route', 'outputs/route_analysis.json', _route_document(final_state=p['routine_final_state']))
            found = run.finish('inputs.route')
            observed = evidence.route_analysis(run.step('inputs.route'), found, run.context())
            if any(row.get('code') == 'route_final_state_mismatch' for row in observed):
                errors.append('routine_final_state_mismatch')
            else:
                assert not observed, observed
        else:
            run.reading['deliverables'] = [{'id': f'fig-{i}', 'artifact': {'kind': 'figure'}}
                                           for i in range(p['requested_panels'])]
            run.adopt('inputs.figures', 'outputs/figure_target.json', {'targets': p['panels']})
            run.adopt('inputs.figures', 'outputs/waypoint.json', {'element': 'first cutflow',
                      'expectation': 'within declared tolerance', 'why_cheap': 'one inert point'})
            found = run.finish('inputs.figures')
            observed = evidence.figures(run.step('inputs.figures'), found, run.context())
            mapping = {'figure_source_missing': 'figure_source_missing', 'figure_axes_unrecorded': 'figure_source_missing',
                       'figure_panels_dropped': 'figure_panels_dropped'}
            for row in observed:
                assert row['code'] in mapping, observed
                code = mapping[row['code']]
                if code not in errors:
                    errors.append(code)
    elif kind == 'recipe':
        # This adapter is wired by the integration fragment at the ordinary study dispatch boundary.
        study = import_module('ravel.controller.routes.study')
        context = {'external_recipe': p['recipe'], 'run_dir': str(nc.root)}
        recipe = nc.path(p['recipe']['path'])
        if p['recipe']['retained']:
            recipe.write_text('retained source recipe\n')
            context['external_recipe']['sha256'] = __import__('hashlib').sha256(recipe.read_bytes()).hexdigest()
        observed = study.external_recipe_errors({'parameters': {'effects': ['generates_events']}}, context)
        if observed:
            assert {row['code'] for row in observed} == {'external_recipe_missing'}
            errors.append('external_recipe_missing')
    elif kind == 'ladder':
        check = import_module('ravel.controller.routes.analysis.guard')
        observed = check.ladder_errors({'steps': p['steps']})
        if observed:
            assert {row['code'] for row in observed} <= {'waypoint_missing', 'rung_ladder_skipped'}
            errors.append('rung_ladder_skipped')
    elif kind == 'watcher':
        from ravel.workflow import preflight_watcher
        # A shell target is parsed for arity; it never executes its positional arguments.
        target = nc.path('durable', 'watch.sh') if p['watcher']['durable'] else nc.path('scratch', 'watch.sh')
        target.write_text('test -n "$5"\n')
        if not p['watcher']['durable']:
            observed = preflight_watcher.durable_target_errors(nc.root, target)
            if observed:
                errors.append('watcher_target_not_durable')
        fire = 'sh ' + str(target) + ' ' + ' '.join(p['watcher']['arguments'])
        verdict, _ = preflight_watcher.probe_fire_command(fire, str(target))
        if verdict != 'pass' or not p['watcher']['preflight']:
            errors.append('watcher_preflight_failed')
    else:
        raise AssertionError(f'unregistered route component: {kind}')
    return {'errors': errors, 'notices': [], 'disclosures': []}
