"""Inert route attacks at installed controller consumers, with real bounded endings.

The fixture supplies trusted compiler/custody observations. It never turns a
probe verdict into a ledger transition, review credit or an accepted result.
The parent owns the start counter; the byte-only child cannot alter it. These
are admission/adoption controls, not an end-to-end scientific execution proof.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import subprocess
import sys

from ravel.validation.intake_records import CONSTRAINT_TYPES

from nc_cases import require_controller
from nc_controller import checkin_view, controller_run
from nc_env import Env


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@dataclass
class Observation:
    errors: tuple
    effects: int
    report: dict
    ending: dict
    receipt: dict
    sink: bytes
    producer: bytes | None
    source: dict


class RouteHarness:
    def __init__(self, nc):
        self.nc, self.sequence = nc, 0

    def run(self, payload):
        self.sequence += 1
        env = Env(self.nc.root / f'route-entry-{self.sequence}', self.nc.patch)
        try:
            env.enter_domain()
            store, root = controller_run(env, 'route-entry', mode='autonomous')
            entry = Entry(env, store, root, deepcopy(payload))
            errors = tuple(entry.guard())
            store, root = entry.store, entry.root
            # Admission is the actual consumer's answer, never the case's oracle.
            starts, produced = 0, None
            if not errors:
                target = root / 'steps' / 'effect' / 'result.txt'
                target.parent.mkdir(parents=True, exist_ok=True)
                starts += 1
                process = subprocess.run([sys.executable, '-I', '-B', '-c',
                    'import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b"fictional route output\\n")',
                    str(target)], capture_output=True, timeout=30)
                assert process.returncode == 0, process.stderr
                produced = target.read_bytes()
                assert produced == b'fictional route output\n'
            entry.pin(route_record=payload['kind'] != 'dispatch' or payload['route_pinned'])
            ledger = require_controller('ledger')
            ledger.materialise(store, 'intake', {'run_id': store.run_id, 'task_mode': entry.contract['task_mode'],
                'route': entry.plan['route']['id'], 'deliverables': [r['id'] for r in entry.reading['deliverables']]})
            ledger.materialise(store, 'plan', {'plan': entry.plan, 'route': entry.plan['route']['id'],
                'task_mode': entry.contract['task_mode']})
            graph, sink = require_controller('graph', 'sink')
            reason = '; '.join(errors) or 'inert admission control; scientific execution not attempted'
            graph.bounded_end({**entry.state, 'status': {'reason': reason}})
            receipt = sink.receipt(store)
            directory = root / 'delivery'
            raw = (directory / 'qualified-delivery.json').read_bytes()
            ending = json.loads(raw)
            saved = json.loads((directory / 'RECEIPT.json').read_bytes())
            assert saved['sha256'] == receipt['sha256']
            assert ending['reason'] == reason
            assert ending['scientific_claims_adopted'] == []
            assert ending['parent_task_accepted'] is False and ending['execution_authorized'] is False
            assert not receipt['accepted'] and not receipt['architecture_complete']
            assert 'Architecture complete: no' in (directory / 'DELIVERY.md').read_text()
            assert not store.verify(), 'real store chain must verify'
            return Observation(errors, starts, entry.report, ending, receipt, raw, produced,
                               {'plan': deepcopy(entry.plan), 'reading': deepcopy(entry.reading)})
        finally:
            env.close()


class Entry:
    def __init__(self, env, store, root, payload):
        self.env, self.store, self.root, self.payload = env, store, root, payload
        self.report = {}
        self.reading = {'deliverables': [{'id': 'result'}], 'constraints': [], 'boundaries': []}
        self.contract = {'task_mode': 'calculation', 'prompt': 'Development: calculate a fictional quantity.'}
        self.plan = {'schema_version': 1, 'route': {'id': 'judgment', 'version': 1}, 'parameters': {},
                     'steps': [{'id': 'effect', 'kind': 'author', 'depends_on': [], 'parameters': {},
                                'outputs': [{'path': 'result.txt', 'kind': 'artifact', 'required': True}]}],
                     'deliverables': [{'id': 'result', 'status': 'mapped', 'step': 'effect', 'output': 'result.txt'}],
                     'open_obligations': [], 'obligations': [], 'instruction_sources': []}

    def adopt(self, artifact, document):
        step, name = artifact.split(':', 1)
        raw = document if isinstance(document, bytes) else json.dumps(document, sort_keys=True).encode()
        destination = 'steps/' + step + '/' + name
        path = self.root / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.store.append('custody', {'artifact': artifact, 'step_id': step, 'attempt': 1, 'path': name,
            'destination': destination, 'sha256': _sha(raw), 'status': 'accepted'})

    def pin(self, *, route_record=True):
        routes = require_controller('routes')
        self.plan['sha256'] = routes.plan_sha256(self.plan)
        blob = lambda obj: self.store.put_blob(json.dumps(obj, sort_keys=True).encode())
        intake = self.store.append('intake', {'contract_blob': blob(self.contract), 'reading_blob': blob(self.reading)})
        plan_blob = blob(self.plan)
        self.store.append('plan', {'plan_sha256': self.plan['sha256'], 'blob': plan_blob, 'route': self.plan['route']['id']})
        route = {'id': self.plan['route']['id']}
        if route_record:
            route['record_id'] = self.store.append('route', {'route': route['id']})
        self.state = {'run': {'run_id': self.store.run_id, 'run_dir': str(self.root),
                             'store_root': str(self.store.store_root)},
            'request': {'intake_record_id': intake}, 'route': route,
            'plan': {'sha256': self.plan['sha256'], 'blob': plan_blob, 'route': route['id']}, 'steps': {}}

    def context(self):
        return {'store': self.store, 'run_dir': str(self.root), 'plan': self.plan,
                'reading': self.reading, 'contract': self.contract, 'state': {}, 'supplied': []}

    def guard(self):
        p, kind = self.payload, self.payload['kind']
        if kind == 'dispatch':
            graph, routes = require_controller('graph', 'routes')
            selected = routes.select(self.contract, self.reading, [])
            assert selected['route'] not in ('inspect', 'legacy')
            self.pin(route_record=p['route_pinned'])
            admitted, held, holds = graph._admitted(self.state, self.store, self.plan, ['effect'], {})
            self.report = {'admitted': admitted, 'held': held, 'holds': holds}
            return ['route_not_pinned'] if not admitted else []
        if kind in ('population', 'stages'):
            return self.scope_guard()
        if kind in ('quantity', 'recipe'):
            return self.evidence_guard()
        if kind in ('routine', 'figure', 'comparison'):
            return self.join_guard()
        if kind == 'manuscript':
            return self.manuscript_guard()
        if kind == 'inference':
            ml, authority = require_controller('routes.ml', 'authority')
            from ravel.workflow.production_executor import executors
            step = self.plan['steps'][0]
            step.update(kind='operate', operation='published-classifier', role=executors()['operations']['published-classifier'],
                        parameters={'task': {'mode': 'published-classifier', 'training': p['training']}})
            self.pin()
            decision = authority.request(self.store, 'approve_plan',
                {'view': checkin_view(self.store, 'approve_plan', plan_sha256=self.plan['sha256'])}, {'rung': 'dry'})
            assert decision.get('decision') == 'approve', decision
            found = ml.admit(step, plan=self.plan, authority=lambda kind, pins: authority.current(self.store, kind, pins))
            self.report = {'findings': found}
            assert {r['code'] for r in found} <= {'ml_inference_requests_training'}, found
            return ['training_not_admitted'] if found else []
        if kind == 'ladder':
            from ravel.controller.routes.analysis import guard
            self.plan['steps'] = deepcopy(p['steps'])
            self.plan['deliverables'][0]['step'] = self.plan['steps'][-1]['id']
            for step in self.plan['steps']:
                step.setdefault('kind', 'derive')
                step.setdefault('outputs', [{'path': 'result.txt', 'kind': 'artifact', 'required': True}])
            found = guard.ladder_errors(self.plan)
            self.report = {'findings': found}
            return ['rung_ladder_skipped'] if found else []
        if kind == 'watcher':
            from ravel.workflow import preflight_watcher
            target = self.root / ('inputs' if p['watcher']['durable'] else 'scratch') / 'watch.sh'
            target.parent.mkdir(parents=True)
            target.write_text('test -n "$5"\n')
            if p['watcher']['durable']:
                # A controller-retained input, unlike the adversary's scratch-only script.
                self.store.append('custody', {'artifact': 'prepare:watch.sh', 'step_id': 'prepare',
                    'path': 'watch.sh', 'destination': 'inputs/watch.sh',
                    'sha256': _sha(target.read_bytes()), 'status': 'accepted'})
                self.plan['steps'][0]['inputs'] = [{'artifact': 'prepare:watch.sh', 'required': True}]
            fire = 'sh ' + str(target) + ' ' + ' '.join(p['watcher']['arguments'])
            found, relative = preflight_watcher.arm_watcher(str(self.root), 'fictional-watcher', fire, str(target))
            assert json.loads((self.root / relative).read_bytes()) == found
            self.report = found
            if found['verdict'] != 'pass':
                # Observe the product's own typed refusal; a failure without one is the generic preflight refusal.
                return list(found.get('refusal_codes') or ['watcher_preflight_failed'])
            # No replacement durability guard is installed when the product lacks one.
            return []
        raise AssertionError('unimplemented controller-entry scenario: ' + kind)

    def scope_guard(self):
        from ravel.controller.routes import study
        p = self.payload
        self.contract['task_mode'] = 'likelihood'
        self.plan['route']['id'] = 'scoped'
        self.reading['deliverables'] = [{'id': value} for value in p['deliverables']]
        wanted = p['requested_stages'] if p['kind'] == 'stages' else ['likelihood']
        self.reading['constraints'] = [{'type': 'requested_stage', 'value': {'stage': value}} for value in wanted]
        self.plan['deliverables'] = [{'id': value, 'status': 'mapped', 'step': 'effect', 'output': 'result.txt'}
                                     for value in p['deliverables']]
        self.adopt(study.SPEC_ARTIFACT, {'schema_version': 1, 'mode': 'likelihood',
            'source': 'fictional supplied counting model', 'assumptions': ['Finite fictional counting control.'],
            'max_seconds': 10, 'approval_mode': 'physicist', 'likelihood': {
                'counting': {'observed': 3, 'background': 2.5, 'background_uncertainty': 0.5, 'signal': 1.0},
                'poi_cap': 10, 'normalization': {'kind': 'signal_strength'}}})
        self.adopt(study.SCOPE_ARTIFACT, {'schema_version': 1, 'kind': 'study-scope',
            'deliverables': p['covered'], 'stages': p['stages'] if p['kind'] == 'stages' else ['likelihood'],
            'child_rundir': 'children/fictional-counting'})
        self.plan = study.bind(self.plan, self.context())
        self.pin()
        graph = require_controller('graph')
        admitted, held, holds = graph._admitted(self.state, self.store, self.plan, ['effect'], {})
        self.report = {'admitted': admitted, 'held': held, 'holds': holds,
                       'open_obligations': self.plan['open_obligations']}
        return [('missing_stage' if p['kind'] == 'stages' else 'missing_deliverable')] if not admitted else []

    def evidence_guard(self):
        from ravel.controller.routes.study import evidence
        p = self.payload
        step = self.plan['steps'][0]
        if p['kind'] == 'quantity':
            self.adopt('expected:descriptor.json', p['expected'])
            self.adopt('observed:descriptor.json', p['actual'])
            binding = {'row': 'R08', 'expected': 'expected:descriptor.json', 'observed': 'observed:descriptor.json'}
            phase = 'adopt'
        else:
            step.update(operation='scoped-generate')
            self.adopt('recipe:source.json', {'source': 'retained fictional external recipe'})
            binding = {'row': 'E09', 'expected': 'recipe:recipe.json'}
            if p['recipe']['retained']:
                self.adopt(binding['expected'], {'kind': 'external-generation-recipe', 'schema_version': 1,
                    'operation': step['operation'], 'instructions': 'Run the fictional byte producer.',
                    'sources': ['recipe:source.json']})
            phase = 'dispatch'
        step['parameters']['evidence_requirements'] = [binding]
        found = evidence.check(self.store, step, self.context(), phase=phase)
        self.report = {'findings': found, 'records': [r['record'] for r in self.store.scan('study-evidence')]}
        if not found:
            return []
        assert {r['code'] for r in found} == {'scientific_evidence_unresolved'}, found
        return ['units_changed_or_missing' if p['kind'] == 'quantity' else 'external_recipe_missing']

    def join_guard(self):
        from test_nc_analysis_route import _Run, _route_document, _graph_state
        p = self.payload
        run = _Run(self.env, name='analysis-join')
        if p['kind'] == 'routine':
            assert 'keep_fixed' in CONSTRAINT_TYPES
            requested = p['requested_final_state']
            fixed = 'Keep the final state fixed at ' + requested + '.'
            run.contract['prompt'] = 'Reproduce a fictional selection. ' + fixed
            start = run.contract['prompt'].index(fixed)
            run.reading['constraints'] = [{'id': 'K1', 'type': 'keep_fixed',
                'value': {'text': fixed, 'final_state': requested},
                'evidence': [{'start': start, 'end': start + len(fixed), 'text': fixed}]}]
            step_id = 'inputs.route'
            run.adopt(step_id, 'outputs/route_analysis.json', _route_document(final_state=p['routine_final_state']))
        elif p['kind'] == 'figure':
            run.reading['deliverables'] = [{'id': 'fig-' + str(i), 'artifact': {'kind': 'figure'}}
                                            for i in range(p['requested_panels'])]
            step_id = 'inputs.figures'
            run.adopt(step_id, 'outputs/figure_target.json', {'targets': p['panels']})
            run.adopt(step_id, 'outputs/waypoint.json', {'element': 'first cutflow',
                'expectation': 'within declared tolerance', 'why_cheap': 'one inert point'})
        else:
            step_id = 'compare.reference'
            for label in ('noise', 'replica-a', 'replica-b'):
                run.adopt('inputs.route', 'outputs/' + label + '.json', {'value': 1, 'fictional': True})
            document = {'comparator': {'source': 'fictional retained reference'}, 'tolerance': 0.1,
                'lattice': 'fictional-grid', 'basis_manifests': [
                    {'quantity': 'yield', 'basis': 'count', 'unit': 'events'}] * 2,
                'attributions': [{'cause': 'fictional binning difference',
                    'model_output': 'artifact:inputs.route:outputs/noise.json',
                    'replicas': ['artifact:inputs.route:outputs/replica-a.json',
                                 'artifact:inputs.route:outputs/replica-b.json'],
                    'noise_model': p['noise_model'], 'above_noise': p['above_noise']}]}
            run.adopt(step_id, 'outputs/comparison.json', document)
        outcome = run.finish(step_id)
        state = _graph_state(run)
        state['loop'] = {'number': 1, 'phase': 'prepare', 'items': [{'step': run.step(step_id), 'attempt': 1}]}
        state['results'] = {step_id + '@1': {'results': {'step': outcome}}}
        update = require_controller('graph').join(state)
        self.report = update
        # Keep the actual join's store/route as the final bounded-ending subject.
        self.store, self.root, self.plan, self.reading, self.contract = run.store, run.dir, run.plan, run.reading, run.contract
        found = update['steps'][step_id]
        code = {'routine': 'routine_final_state_mismatch', 'figure': 'figure_source_missing',
                'comparison': 'attribution_below_noise'}[p['kind']]
        return [code] \
            if found['status'] != 'completed' else []

    def manuscript_guard(self):
        from io import BytesIO
        from pypdf import PdfWriter
        from ravel.controller.routes import manuscript
        pdf = PdfWriter()
        pdf.add_blank_page(width=612, height=792)
        stream = BytesIO()
        pdf.write(stream)
        manuscript_pdf = stream.getvalue()
        self.plan['route']['id'] = 'manuscript'
        self.plan['steps'] = [
            {'id': 'author', 'kind': 'author', 'depends_on': [], 'outputs': [
                {'path': 'claims.json', 'kind': manuscript.CLAIM_MAP_KIND, 'required': True}]},
            {'id': 'assemble', 'kind': 'subgraph', 'graph': {'id': 'manuscript.build'}, 'depends_on': ['author']},
            {'id': 'build', 'kind': 'operate', 'operation': 'manuscript-build', 'depends_on': ['assemble'],
             'outputs': [{'path': 'result.pdf', 'kind': 'document', 'required': True}]}]
        self.plan['deliverables'] = [{'id': 'result', 'status': 'mapped', 'artifact_kind': 'document',
                                     'step': 'build', 'output': 'result.pdf'}]
        for step in self.plan['steps']:
            self.store.append('step-outcome', {'step_id': step['id'], 'status': 'completed', 'attempt': 1})
            if step['id'] != 'build' or self.payload['build_custody']:
                self.adopt(step['id'] + ':' + ('result.pdf' if step['id'] == 'build' else 'stage.json'),
                           manuscript_pdf if step['id'] == 'build' else {})
        found = manuscript.delivery_errors_from_store(self.store, self.plan)
        self.report = {'findings': found}
        assert {r['code'] for r in found} <= {'manuscript_unreceipted'}, found
        return ['manuscript_unreceipted'] if found else []
