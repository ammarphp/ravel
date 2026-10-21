"""The outer research.loop traverses the staged cascade under real authority.

All responses are inert. The loop runs approved studies, separate CI2 triads, an
RDJ-bound revision, selection, confirmation and every declared protocol stage.
The completed campaign retains all original scientific obligations as qualified
progress, then receives a fresh final review and a recomputed architecture receipt.
"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from ravel.workflow import graph_environment  # noqa: F401
from ravel.workflow import (agent_graph, research_cycle as cycle, research_orchestrator as orch,
    research_protocol as protocol, research_evaluation, science)
from test_langgraph_research_orchestration import open_fixture, METHOD_REQUEST_BYTES, presented_effects
from test_research_cycle import experiment, write
from test_research_default_protocol import synthetic_artifacts
from test_research_full_cycle import (CASE, complete_stage, deliver_stage, evaluation, real_decision,
    stage_settings)
from test_research_full_cycle_transport import InertReviewHost
from method_decision_fixture import admit_method
from test_research_full_cycle_authority import Authority, authorize, intake, satisfy_initial_staffing


class OuterHost(InertReviewHost):
    """Actual host contexts and accounted inert review calls, with full packet presentation."""
    def __init__(self, callback):
        super().__init__(callback, max_request_bytes=METHOD_REQUEST_BYTES)
        self.review_calls = []

    def execute(self, item, request, control):
        if 'audit' in item.get('parameters', {}).get('output_schema', {}).get('properties', {}):
            self.review_calls.append({'id': item['id'], 'packet': item['packet']})
            return InertReviewHost().execute(item, request, control)
        return super().execute(item, request, control)


def final_recipe(base, root, rd, state):
    """Use the open flow's authenticated declaration, not a legacy fixture alias."""
    basis = deepcopy(state['scientific_context_declaration']['request'])
    source, _ = cycle._check_pin(basis, state['base_dir'])
    basis['path'] = str(source.relative_to(base))
    context_path = root/'synthesis-context'/(state['context']['context_sha256']+'.json')
    context_pin = write(context_path, state['context'])
    context_pin['path'] = str(context_path.relative_to(base))
    result = cycle._pin(rd/'outputs/attempt-1/result.json')
    result['path'] = str(Path(result['path']).relative_to(base))
    return {'schema_version': 1, 'title': 'Supplied signed-record investigation',
        'artifact_request': {'schema_version': 1, 'contract': {
            'source_scope': 'Conditional supplied arithmetic only.',
            'tool_fields': [{'field': 'variance', 'type': 'number', 'source': {
                'kind': 'direct', 'tool_id': 'study', 'pointer': '/quantities/covariance/0/0'}}],
            'interpretation_fields': [], 'unresolved_semantics': [], 'max_artifact_bytes': 2048},
            'basis': [basis], 'tools': {'study': result}, 'interpretation': {}},
        'context': context_pin, 'facts': [{'id': 'conditional',
            'selector': {'kind': 'direct', 'pointer': '/variance'}, 'quantity_id': 'conditional-variance',
            'context_selector': {'kind': 'direct', 'pointer': '/0/0'},
            'label': 'Conditional group variance', 'unit': '1', 'scope': 'synthetic_given_groups',
            'population': 'Both supplied signed records',
            'limitations': ['No native event acquisition, model benefit or physics qualification.']}],
        'sections': [{'id': 'complete', 'kind': 'table', 'caption': 'Complete supplied conditional quantity.',
            'columns': ['Variance'], 'rows': [{'id': 'paired', 'facts': ['conditional']}]}],
        'interpretation': ['The initial separate-group control did not discriminate the rival hypotheses; '
            'the paired follow-up did, conditional on supplied group semantics.']}


def _outer_cycle(tmp_path, monkeypatch, record_property, *, driver=None):
    case = json.loads(CASE.read_text())
    proposed = {}
    actual_prepare = orch.prepare_open

    def prepare(parent, out, **kwargs):
        _, parent = intake(tmp_path)
        goal = {'contract': parent, 'assignment_id': 'original-task'}
        extra = []
        for number, (name, grouped, ancestor) in enumerate([
            ('separate', False, None), ('paired', True, 'separate'), ('confirmation', True, 'paired')], 1):
            e = evaluation(tmp_path, experiment(tmp_path, name, grouped=grouped, parent=ancestor),
                           round=number, confirm=name == 'confirmation')
            e['predictions'] = {'separate-law': 'independent',
                                'paired-law': 'shared' if grouped else 'independent'}
            spec = cycle._read(e['study'], tmp_path)
            spec['goal_binding'] = goal
            spec['task'] = {key: str(tmp_path/name/value) for key, value in spec['task'].items()}
            e['study'] = write(Path(e['study']['path']), spec)
            proposed[name] = (e, spec)
            for dependency in science.task_inputs(spec, Path(e['study']['path']).parent):
                pin = cycle._pin(dependency)
                extra.append({'pin': pin, 'purpose': 'execution_dependency' if
                    name == 'confirmation' and pin['sha256'] == e['evaluation']['population_pins'][0]['sha256']
                    else 'model_context'})
        kwargs['evidence'] = list({(e['pin']['path'], e['pin']['sha256']): e
                                  for e in [*kwargs['evidence'], *extra]}.values())
        settings = stage_settings()
        kwargs['runtime'] = {**kwargs['runtime'], 'roles': settings['roles'], 'tiers': settings['tiers'],
                             'max_wall_seconds': 900}
        kwargs['campaign']['budget'].update(calls=128, output_tokens=500000, wall_seconds=86400, native_attempts=6)
        kwargs['max_decisions'] = 24
        kwargs['review']['arguments'] = {'model': 'control', 'reasoning_effort': 'high',
            'max_output_tokens': 2048, 'max_wall_seconds': 120, 'claim_scope': 'supplied_math_diagnostic'}
        return actual_prepare(parent, out, **kwargs)

    monkeypatch.setattr(orch, 'prepare_open', prepare)
    rp, template, source, parent_contract = open_fixture(tmp_path, max_request_bytes=METHOD_REQUEST_BYTES)
    monkeypatch.setattr(orch, 'prepare_open', actual_prepare)
    request = orch._read(rp)
    assert request['handoff']['original_request'] == parent_contract['prompt']
    root, out = tmp_path/'campaign', tmp_path/'campaign/coordinator'
    artifacts, checks, run_dirs = {}, {}, {}
    selected = None
    decision_run = None
    mapping = [{'obligation_id': r['id'], 'original': deepcopy(r),
        'quantities': ['conditional-variance'] if r['id'] == 'original-request' else [],
        'method': 'Fictional supplied-record arithmetic; no whole-parent acceptance.', 'sources': [source],
        'unresolved': '' if r['id'] == 'original-request' else r['statement']}
        for r in parent_contract['task_requirements']['obligations']]

    def callback(item, context):
        cores = [p for p in context.get('input_artifacts', []) if p['id'] == 'scientific-core']
        if not cores or json.loads(cores[0]['content'])['phase'] != 'action':
            return template.callback(item, context)
        core = json.loads(cores[0]['content'])
        effects = presented_effects(core, context)
        for prior in effects:
            actual = prior['actual_effect']
            assert actual.get('status') != 'action_failed', actual.get('failure')
        turn = len(effects)
        if turn in (0, 3, 8):
            identity = {0: 'separate', 3: 'paired', 8: 'confirmation'}[turn]
            e, spec = proposed[identity]
            action, args = 'experiment', {'study': spec,
                'experiment': {k: v for k, v in e.items() if k != 'study'}, 'records': [], 'source_mapping': mapping}
        elif turn == 9:
            prepared = effects[8]['actual_effect']
            assert prepared['status'] == 'prepared_not_admitted'
            action, args = 'experiment', {'prepared_experiment': prepared['prepared_experiment']}
        elif turn in (1, 4, 10):
            action, args = 'run-selected', {}
        elif turn in (2, 5, 11):
            identity = {2: 'separate', 5: 'paired', 11: 'confirmation'}[turn]
            from ravel.workflow import gate_wiring
            row = next(e for e in cycle._load(root)[1]['experiments'] if e['id'] == identity)
            rd = Path(row['rundir'])
            authorize(rd, gate_wiring.research_choice_action(rd, root, identity, row, write=True))
            action, args = 'review', {'experiment': identity, 'check_results': checks[identity]}
        elif turn in (6, 7) or 12 <= turn <= 16:
            if turn == 6:
                stage = 'baseline'
            elif turn == 7:
                stage = 'screen'
            else:
                stage = case['expected_stages'][turn - 8]
            # The operator authorized this exact stage action before dispatch.
            # A model callback never opens decision cases on the running campaign.
            action, args = 'protocol-stage', {'artifact': artifacts[stage]}
        else:
            action, args = 'progress', {'reason': 'Methodology completed; original figure/note obligations remain open.'}
        public = {'kind': 'research-action', 'action': action, 'reason': 'Inert source-bound full-loop control.',
                  'arguments_json': json.dumps(args)}
        if 'information_gain' in item['parameters']['output_schema']['properties']:
            public['information_gain'] = {'decision': 'stop' if action == 'progress' else 'continue',
                'expected_gain': 'Complete the remaining prospective comparison and independent review.'
                                 if action != 'progress' else 'All prospective comparisons have been completed.',
                'cost_justification': 'The remaining discriminating comparison justifies the projected cycle.'
                                      if action != 'progress' else 'Repeated comparisons do not justify another cycle.',
                'evidence_input_ids': ['scientific-core']}
        return public

    host = OuterHost(callback)
    result = (driver.run(root, rp, host) if driver is not None else
              orch.run_graph(root, rp, out, host=host, experimental=True))
    assert result['phase'] == 'ordinary_effect_required'
    satisfy_initial_staffing(root)
    satisfy_initial_staffing(Path(request['parent_contract']['path']).parent.parent, campaign_root=root)
    synthetic = synthetic_artifacts(root)
    for stage in ('limitation_census', 'ideas'):
        complete_stage(root, stage, write(root/('initial-'+stage+'.json'), synthetic[stage]), 'graph', stage_settings())
    prereg = write(root/'prospective-full-loop.json', {'schema_version': 1, 'kind': 'research-preregistration',
        'selection_rule': case['selection_rule'], 'stop_rule': case['stop_rule'], 'approximations': [],
        'withheld_cells': [{'id': 'confirm', 'population': proposed['confirmation'][0]['evaluation']['population_pins'][0]}],
        'expected_effect': {'statement': 'Exact fictional arithmetic only.'},
        'evaluator_not_applicable': {k: 'Supplied dimensionless arithmetic.' for k in
            ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}})
    protocol.preregister(root, prereg, {}, evaluation_harness=True)
    decision_run = Authority(root)
    synthetic['screen']['verdicts'] = [real_decision(root, decision_run, 'screen',
        {'idea': 'Ia', 'verdict': 'promote', 'mutable_paths': []}, 'R2')]
    artifacts.update({name: write(root/('full-loop-'+name+'.json'), synthetic[name])
                      for name in ('baseline', 'screen')})
    # Pre-dispatch authority: each exact stage proposal receives its registered
    # decision while the loop is paused, never from inside a model response.
    for name in ('baseline', 'screen'):
        authorize(root, protocol.stage_action(name, artifacts[name]))

    for _ in range(24):
        for graph_root in out.glob('turns/*/effect/protocol/graph'):
            if not agent_graph.status(graph_root)['complete']:
                deliver_stage(graph_root)
        # The screen must complete before the selection gate can freeze the
        # adaptive denominator; confirmation remains undispatched until it does.
        if selected is None and protocol.methodology_status(root)['next_stage'] == 'validate':
            _, current = cycle._load(root)
            selection_request = write(root/'select-full-loop.json', {
                'rule': case['selection_rule'], 'regime': 'open_exploratory',
                'trials': [{'id': row['id'], 'candidate': row['id'], 'result': row['observation']['result']}
                           for row in current['experiments'] if row['observation'] is not None]})
            authorize(root, protocol.selection_action(selection_request))
            selected = protocol.commit_selection(root, selection_request)
        _, state = cycle._load(root)
        for e in state['experiments']:
            if e['rundir'] is None or e['observation'] is not None:
                continue
            rd = Path(e['rundir'])
            assert not (rd/science.APPROVAL).exists()
            assert not (rd/'execution_attempt.json').exists()
            assert e['adjudication'] is None
            satisfy_initial_staffing(rd, campaign_root=root)
            if e['id'] == 'paired':
                # The first CI2 is already consumed by the outer review action.
                # Bind an actual R2 decision before approving the revision's run.
                assert cycle._load(root)[1]['experiments'][0]['adjudication']['view']['state'] == 'accepted'
                revision = real_decision(root, decision_run, 'revision', {
                    'parent': 'separate', 'candidate': 'paired',
                    'feedback': cycle.feedback_packet(root, 'separate')}, 'R2')
                assert protocol._rdj(revision, 'R2', root)['outcome'] == 'authorize'
            admit_method(rd)
            science.approve(rd, 'Explicit inert arithmetic control; no native or physical authority.', scripted=True)
            authorize(root, research_evaluation.prepare_dispatch_action(root, e['id']))
            assert cycle.run_experiment(root, e['id']) == 0
            cycle.observe(root, e['id'])
            # Preparation of the first CI2 occurs here; the outer review action
            # performs its three separate role calls when the coordinator resumes.
            record = science.execution.load_execution(rd)['stages']['science']
            checks[e['id']] = write(rd/'inputs/checks.json', {'schema_version': 1, 'checks': [
                {'id': name, 'status': 'pass', 'evidence': [{'path': 'outputs/attempt-1/result.json',
                 'location': '$.quantities'}], 'attempt_ids': [record['attempt_id']]}
                for name in ('integrity', 'math')]})
            run_dirs[e['id']] = rd
            if e['id'] == 'confirmation':
                # Make every later stage proposal current before its dispatch.
                # The ordinary CI2 of confirmation runs on the next root turn.
                _, current = cycle._load(root)
                report = protocol.selection_report(selected, [current['experiments'][-1]['observation']['result']],
                    base_dir=root, state=current)
                selected_pin = write(root/'selected-full-loop.json', selected)
                report_pin = write(root/'report-full-loop.json', report)
                rdj = decision_run
                assert rdj is not None
                full = research_evaluation.stop_records(current)
                synthetic['validate'] = {'withheld_cells': ['confirm'], 'rounds': [
                    {'round': i, 'candidates': [r['candidate']], 'successes': 0, 'results': [r['source']],
                     'seed_reinjection': []} for i, r in enumerate(full, 1)],
                    'stop': {**case['stop_rule'], 'reason': 'max_rounds'},
                    'selection': real_decision(root, rdj, 'selection', {'rule': 'reviewed_dominance',
                        'comparison': cycle._pin(run_dirs['paired']/'outputs/attempt-1/result.json'),
                        'receipt': selected_pin, 'confirmation_pins': [current['experiments'][-1]['observation']['result']]}, 'R2')}
                synthetic['acceptance']['claims'] = [real_decision(root, Authority(rd), 'claim', {
                    'id': 'K1', 'kind': 'finding', 'N': 2, 'selection_receipt': selected_pin,
                    'selection_report': report_pin, 'verdict': 'exploratory'}, 'R3')]
                artifacts.update({name: write(root/('full-loop-'+name+'.json'), synthetic[name])
                                  for name in case['expected_stages'][4:]})
                for name in case['expected_stages'][4:]:
                    authorize(root, protocol.stage_action(name, artifacts[name]))
        if result.get('phase') != 'ordinary_effect_required':
            break
        response = {k: v for k, v in cycle._pin(root/'head.json').items() if k != 'size'}
        responses = {item['id']: {'response': response} for item in result['checkpoint']['interrupts']}
        parent_root = Path(request['parent_contract']['path']).parent.parent
        for item in result['checkpoint']['interrupts']:
            # Every resume after outside work needs its own pinned decision in the original parent.
            pending = item['payload']['payload']
            if pending['kind'] == 'research-stage-delivery-required':
                action = orch.stage_delivery_action(root, pending, responses[item['id']])
            else:
                action = orch.delivery_action(root, pending['failure_id'], responses[item['id']])
            authorize(parent_root, action)
        result = (driver.respond(root, rp, responses, host) if driver is not None else
                  orch.respond_graph(root, rp, out, responses, host=host, experimental=True))
    record_property('outer_loop_result', json.dumps(result, sort_keys=True))
    record_property('outer_loop_review_calls', json.dumps(host.review_calls, sort_keys=True))
    _, state = cycle._load(root)
    record_property('outer_loop_campaign_events', json.dumps(
        Counter(event['kind'] for event in state['events']), sort_keys=True))
    assert result['kind'] == 'research_progress_synthesis', result
    assert result['parent_task_accepted'] is False
    assert state['revision'] > 128
    status = protocol.methodology_status(root)
    assert status['complete'] is True and status['scientific_acceptance'] is False
    assert [row['id'] for row in status['record']['stages'] if row['status'] == 'done'] == case['expected_stages']
    for row in status['record']['stages']:
        assert set(row['worker_receipts']) == set(row['roles'])
        receipts = [protocol._method_json(pin, root) for pin in row['worker_receipts'].values()]
        assert len({receipt['request_id'] for receipt in receipts}) == len(row['roles'])
        assert len({receipt['context_manifest_sha256'] for receipt in receipts}) == len(row['roles'])
    assert state['contract']['goal_binding'] == request['handoff']['goal_binding']
    assert [e['id'] for e in state['experiments']] == ['separate', 'paired', 'confirmation']
    assert state['experiments'][1]['parent'] == 'separate'
    assert all(e['observation'] is not None and e['adjudication']['view']['state'] == 'accepted'
               for e in state['experiments'])
    assert state['experiments'][-1]['evaluation']['purpose'] == 'confirm'
    assert len(host.review_calls) == 9
    assert len({r['packet']['path'] for r in host.review_calls}) == 9
    effects = [cycle._read(event['effect'], state['base_dir']) for event in state['events']
               if event['kind'] == 'coordinator_effect_committed']
    planned = (['experiment', 'run-selected', 'review'] * 2 + ['protocol-stage'] * 2
               + ['experiment', 'experiment', 'run-selected', 'review'] + ['protocol-stage'] * 5)
    assert [effect['action'] for effect in effects] == planned
    assert all(effect['parent_task_accepted'] is False and effect['scientific_authority_from_checkpoint'] is False
               for effect in effects)
    # Complete the existing final-review and delivery predicates on the same campaign.
    from test_research_full_cycle import review_result, assert_architecture
    from test_autonomy_final_results import package
    from ravel.workflow import physics_review, scientific_judgment, final_results_review
    confirmation = run_dirs['confirmation']
    recipe = final_recipe(tmp_path, root, confirmation, state)
    synthesis = cycle.synthesize(root, recipe, base_dir=tmp_path)
    predecessor = physics_review._view(*physics_review._read(confirmation))['cycle']
    manifest, final = package(confirmation, predecessor)
    report_text = synthesis['report']['report_text']
    write(confirmation/'final-draft/report.json', {
        'kind': 'scientific_quantitative_report_draft', 'report_text': report_text})
    write(confirmation/'final-draft/recipe.json', recipe)
    for row in final['artifacts']:
        row['sha256'] = cycle._pin(row['path'])['sha256']
    for row in final['changes_since_checkin2']:
        row['current_sha256'] = cycle._pin(row['path'])['sha256']
    manifest = {key: value for key, value in write(Path(manifest['path']), final).items() if key != 'size'}
    scientific_judgment.open_final_cycle(confirmation, manifest=manifest, check_results='inputs/checks-final.json')
    review_result(root, confirmation, 'confirmation', final=True)
    assert final_results_review.gate(confirmation, manifest, report=report_text, recipe=recipe)
    assert_architecture(root, confirmation)
    assert len(host.review_calls) == 9  # The final triad has its own observed host calls.


def outer_cycle(tmp_path, monkeypatch, record_property, *, driver=None):
    import sys
    controller_tests = str(Path(__file__).parent/'controller')
    if controller_tests not in sys.path:
        sys.path.insert(0, controller_tests)
    from p11_fakes import captured_operator
    with captured_operator(tmp_path):
        return _outer_cycle(tmp_path, monkeypatch, record_property, driver=driver)


def test_outer_loop_traverses_all_stages_and_delivers_a_qualified_result(tmp_path, monkeypatch, record_property):
    import sys
    controller_tests = str(Path(__file__).parent/'controller')
    if controller_tests not in sys.path:
        sys.path.insert(0, controller_tests)
    from test_p11_composition import run_composition
    return run_composition(tmp_path, monkeypatch, record_property)
