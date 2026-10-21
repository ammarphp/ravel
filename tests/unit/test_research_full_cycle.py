"""Complete multi-model research stages plus constructive ordinary research.

Fictional supplied arithmetic only. Model and review responses are inert;
ordinary approval, execution, evaluation, RDJ and stage completion stay real.
"""
import json
from pathlib import Path
import shutil

import pytest

from ravel.workflow import graph_environment  # noqa: F401
from ravel.workflow import (agent_graph, agent_host, graph_substrate, physics_review,
    research_cycle as cycle, research_orchestrator as orch,
    research_protocol as protocol, research_evaluation, review_context, science,
    scientific_judgment as judgment, final_results_review)
from ravel.workflow.graphs import hosts, stage as stage_graph
from test_agent_graph import external_response
from test_research_cycle import (actual_context_graph, hypotheses, experiment,
    actual_revision_graph, report_request, write)
from test_research_default_protocol import synthetic_artifacts
from test_research_full_cycle_transport import InertReviewHost
from test_autonomy_final_results import package
from rdj_fixtures import canonical
from test_research_full_cycle_authority import Authority, authorize, campaign, satisfy_initial_staffing

CASE = Path(__file__).parents[1]/'fixtures/research_full_cycle/case.json'
MODELS = {'producer': 'gpt-5', 'reviewer': 'claude-x'}


def run_one(base, root, experiment, *, designed=False):
    if not designed: cycle.design(root, experiment)
    rd = base / (experiment['id']+'-run')
    cycle.prepare_experiment(root, experiment['id'], rd)
    satisfy_initial_staffing(rd, campaign_root=root)
    from method_decision_fixture import admit_method
    admit_method(rd)
    with pytest.raises((ValueError, OSError)):
        cycle.run_experiment(root, experiment['id'])
    assert not (rd/'execution_attempt.json').exists()
    science.approve(rd, 'Explicit inert arithmetic approval.', scripted=True)
    authorize(root, research_evaluation.prepare_dispatch_action(root, experiment['id']))
    assert cycle.run_experiment(root, experiment['id']) == 0
    cycle.observe(root, experiment['id'])
    return rd


def stage_settings():
    from ravel.workflow import role_registry
    roles = {r for row in protocol.default_protocol()['stages'] for r in row['roles']}
    rows = {r: {'model': MODELS['producer' if role_registry.load(r)['independence']['kind'] == 'producer'
                              else 'reviewer'], 'reasoning_effort': 'high', 'adapter': 'external'} for r in roles}
    return {'model': 'gpt-5', 'reasoning_effort': 'high', 'adapter': 'external',
        'max_output_tokens': 1024, 'max_wall_seconds': 900, 'roles': rows,
        'tiers': {'judgment': [{'model': m, 'reasoning_effort': 'high'} for m in MODELS.values()]}}


def deliver_stage(graph_root, *, omit=None):
    """One fresh external response per node, using its actual assigned model and packet."""
    status = agent_graph.status(graph_root)
    for role, row in status['nodes'].items():
        if role == omit or row['status'] == 'completed':
            continue
        request = agent_graph.prepare_external(graph_root, role)
        document = json.loads(Path(request['request_file']).read_text())
        fields = document['parameters']['output_schema']['properties']
        value = {key: fields[key]['const'] for key in ('stage', 'role_id', 'subject_sha256')}
        value.update(verdict='accept', findings=['Inert complete-stage transport control.'], attributed_claim_ids=[])
        response = external_response(request, Path(graph_root).parent/(role+'-response.json'), value=value,
            actor_id='inert-'+fields['stage']['const']+'-'+role,
            invocation_id='inert-'+fields['stage']['const']+'-'+role,
            observed_model=document['parameters']['model'])
        agent_graph.deliver_external(graph_root, role, response)


def review_receipt(study):
    """The independent review's bounded receipt: registration, head and journal digest, never the whole journal.

    A stage packet presents every artifact to every role, so the pinned evidence is the review's
    authenticated identity (a reviewer re-reads the journal from its pins), not a copy of it.
    """
    snapshot = physics_review.snapshot(study, action='delivery')
    return {'schema_version': 1, 'kind': 'review-snapshot-receipt', 'action': snapshot['action'],
            'stage': snapshot['stage'], 'run_id': snapshot['registration']['run_id'],
            'registration_sha256': snapshot['registration']['sha256'], 'checkpoint': snapshot['checkpoint'],
            'events_sha256': protocol.ce.digest(snapshot['events']), 'event_count': len(snapshot['events'])}


def complete_stage(root, name, artifact, engine, settings):
    out = root/'coordinator/stages'/name
    if not (out/'preparation.json').exists():
        if name == 'ideas':
            from test_research_full_cycle_ideas import actual_ideas
            proposal = actual_ideas(root, protocol._method_json(artifact, root), root/'idea-dispatches')
            artifact = write(Path(artifact['path']), proposal)
        authorize(root, protocol.stage_action(name, artifact))
    host = agent_host.AgentHost()
    if engine == 'legacy':
        result = orch.run_protocol_stage(root, artifact, out, host=host, settings=settings)
        from ravel.workflow import research_controller
        # Outside a controller scope the stage still waits for its external role deliveries.
        if research_controller.active() is None or not result['complete']:
            assert result['complete'] is False
            deliver_stage(out/'graph')
        result = orch.run_protocol_stage(root, artifact, out, host=host, settings=settings)
        assert result['complete']
    else:
        gates = lambda scope, gate, action: protocol.gate_errors(root, gate, action)
        instance = {'campaign': 'full-cycle', 'request': protocol.ce.digest(name)}
        with hosts(host) as key:
            request = stage_graph.request(artifact=artifact, out=out, settings=settings,
                host_key=key, operation_sha256='0'*64)
            result = graph_substrate.run(root, stage_graph.GRAPH_ID, instance,
                input={'stage_request': request}, gate_check=gates)
            from ravel.workflow import research_controller
            if research_controller.active() is not None and not result['interrupts']:
                assert result['terminal'] is None and result['next'] == [], result
            else:
                assert [i['kind'] for i in result['interrupts']] == ['external_delivery'], result
                deliver_stage(out/'graph')
                result = graph_substrate.respond(root, stage_graph.GRAPH_ID, instance,
                    {result['interrupts'][0]['id']: {'response': {k: v for k, v in cycle._pin(root/'head.json').items()
                                                               if k != 'size'}}}, gate_check=gates)
                assert result['terminal'] is None and result['next'] == [], result
                assert result['effects']['completed'] >= 3
    # Both runners have just called complete_stage, including its full live
    # evidence check. Inspect that committed journal here; the complete parity
    # snapshots below re-run methodology_status over the final population.
    # Re-validating every prior scientific snapshot again at this assertion
    # duplicates the production checks without adding a distinct control.
    record = cycle.state_io.read_json(protocol._method_path(root))
    row = next(r for r in record['stages'] if r['id'] == name)
    assert row['status'] == 'done'
    assert set(row['worker_receipts']) == set(row['roles'])
    receipts = [protocol._method_json(p, root) for p in row['worker_receipts'].values()]
    assert all(r['context_transport_separated'] for r in receipts)
    spec = protocol._method_json(row['active_preparation']['specification'], root)
    assert len({n['packet']['path'] for n in spec['nodes']}) == len(row['roles'])
    assert len({r['request_id'] for r in receipts}) == len(row['roles'])
    assert len({r['transport']['invocation_id'] for r in receipts}) == len(row['roles'])
    for node in spec['nodes']:
        receipt = protocol._method_json(row['worker_receipts'][node['id']], root)
        expected = settings['roles'][node['id']]
        assert node['parameters']['model'] == receipt['transport']['observed_model'] == expected['model']
        manifest = review_context.verify_packet(node['packet']['path'],
            expected_manifest_sha256=node['packet']['manifest_sha256'])
        assert {r['sha256'] for r in manifest['artifacts']} <= set(receipt['presented_subject_sha256s'])
    return out


def review_result(root, rd, identity, *, final=False):
    """Real review graph per critic, verifier and decider; only HTTP replies are inert."""
    if not final:
        record = science.execution.load_execution(rd)['stages']['science']
        write(rd/'inputs/checks.json', {'schema_version': 1, 'checks': [
            {'id': key, 'status': 'pass', 'evidence': [{'path': 'outputs/attempt-1/result.json',
                'location': '$.quantities'}], 'attempt_ids': [record['attempt_id']]}
            for key in ('integrity', 'math')]})
        physics_review.open_cycle(rd, effective_settings=science.review_effective_settings(rd),
            stage_receipts=[record['attempt_record']], check_results='inputs/checks.json')
    actors = physics_review._read(physics_review._root(rd))[0]['policy']['actors']
    for role, policy_role in [('critic', 'physics_critic'), ('verifier', 'skeptical_verifier'),
                               ('synthesizer', 'physics_decider')]:
        binding = judgment.prepare_role(rd, rd/('ci3' if final else 'ci2')/role,
            role=role, actor_id=actors[policy_role], model='control', reasoning_effort='high',
            max_output_tokens=2048, max_wall_seconds=30, claim_scope='supplied_math_diagnostic',
            allow_control=True, campaign=root, experiment=identity)
        judgment.execute_role(binding, InertReviewHost())
        judgment.consume(rd, binding, allow_control=True)
    assert physics_review.status(rd)['state'] == 'accepted'
    assert physics_review.gate_errors(rd, 'delivery') == []
    if final:
        return None
    from ravel.workflow import gate_wiring
    row = next(e for e in cycle._load(root)[1]['experiments'] if e['id'] == identity)
    authorize(rd, gate_wiring.research_choice_action(rd, root, identity, row, write=True))
    gate_wiring.require_research_choice(root, identity)
    return cycle.adjudicate(root, identity)


def real_decision(root, run, name, value, level):
    choice = run.put('outputs/'+name+'-choice.json', canonical(value))
    assert choice['sha256'] == protocol.ce.digest(value)
    action = {'kind': 'screening_choice', 'digest': choice['sha256'],
        'summary': 'Bound fictional research choice '+name, 'pins': [choice]}
    pin = authorize(run.root, action, level=level)
    return {**value, 'rdj_receipt': pin}


def evaluation(base, e, *, round, confirm=False, goal=None):
    # Exposure must name an actual execution input. Give each prospective study
    # a distinct finite record population. Confirmation uses a fresh signed pair
    # with the same sum, rather than relabelling the adaptive records.
    records = base/e['id']/'records.jsonl'
    rows = [json.loads(line) for line in records.read_text().splitlines()]
    for index, row in enumerate(rows):
        row['event_id'] = e['id']+'-'+row['event_id']
        row['group_id'] = e['id']+'-'+row['group_id']
        if confirm:
            row['weights']['nominal'] = (3, -2)[index]
    records.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    population = cycle._pin(records)
    if goal is not None:
        spec = cycle._read(e['study'], base)
        spec['goal_binding'] = goal
        e['study'] = write(Path(e['study']['path']), spec)
    e['evaluation'] = {'candidate': 'paired' if confirm else e['id'], 'family': 'signed-records',
        'round': round, 'purpose': 'confirm' if confirm else 'full',
        'cells': ['confirm' if confirm else 'development'], 'seeds': [30+round],
        'generation': e['id']+'-data', 'population_pins': [population],
        'value_pointer': '/quantities/covariance/0/0'}
    return e


def assert_architecture(root, confirmation):
    from ravel.workflow import architecture_receipt
    receipt = architecture_receipt.build_receipt(confirmation,
        [{'path': 'outputs/attempt-1/result.json', 'kind': 'number'}])
    predicates = receipt['architecture_predicates']
    evidence = json.dumps({
        'predicates': predicates,
        'research_errors': receipt['research']['errors'], 'role_errors': receipt['roles']['errors'],
        'missing_roles': receipt['roles']['missing'], 'blocking_points': receipt['roles']['blocking_points'],
        'ordinary_final': receipt['roles'].get('ordinary_final'),
        'governed': receipt['admissibility']['governed']}, sort_keys=True)
    # The full cycle proves the research join and the credited required roles. A run the controller does not own
    # is never architecture-complete: its receipt carries NOT GOVERNED and a false controller-mode predicate.
    assert predicates['research_join_complete'] and predicates['required_roles_credited'], evidence
    assert predicates['controller_mode'] is False and receipt['architecture_complete'] is False, evidence
    assert architecture_receipt.NOT_GOVERNED in receipt['notices'], receipt['notices']
    assert receipt['roles']['missing'] == []
    assert receipt['research']['campaign'] == str(root)
    assert receipt['host']['whole_host_enforcement'] == 'unknown'
    assert len(receipt['research']['experiments']) == 3
    assert [row['stage'] for row in receipt['research']['stages']] == json.loads(CASE.read_text())['expected_stages']
    return receipt


def _full_cycle(tmp_path, record_property, *, engines=('legacy', 'graph')):
    """Complete every bound stage after actual studies, reviews, revision and confirmation.

    With two engines, the later stages run on each engine from one frozen campaign and
    their parity is asserted. Returns the campaign and its confirmation run.
    """
    from ravel.workflow import rdj_custody
    custody = rdj_custody._state()
    case = json.loads(CASE.read_text())
    root = campaign(tmp_path)
    goal = cycle._load(root)[1]['contract']['goal_binding']
    actual_context_graph(root, tmp_path)
    rivals = [{**h, 'operator': 'limitation_fix', 'what_is_new': None,
        'identity_signature': {'observable': 'variance', 'scope': 'signed records', 'prediction': h['id']},
        'kill_condition': {'comparison': 'differs', 'observable': 'variance'},
        'reopening_trigger': {'kind': 'changed_input', 'field': 'revision', 'op': 'gt', 'value': 0}}
        for h in hypotheses()]
    cycle.propose(root, rivals, origin={'kind': 'supplied_source',
        'pin': write(tmp_path/'hypotheses.json', rivals), 'description': 'Inert fictional rival declarations.'})
    artifacts = synthetic_artifacts(root)
    settings = stage_settings()
    for name in ('limitation_census', 'ideas'):
        complete_stage(root, name, write(root/(name+'.json'), artifacts[name]), 'graph', settings)
    confirm = evaluation(tmp_path, experiment(tmp_path, 'confirmation', grouped=True), round=3, confirm=True, goal=goal)
    prereg = write(root/'prospective.json', {'schema_version': 1, 'kind': 'research-preregistration',
        'selection_rule': case['selection_rule'], 'stop_rule': case['stop_rule'], 'approximations': [],
        'withheld_cells': [{'id': 'confirm', 'population': confirm['evaluation']['population_pins'][0]}],
        'expected_effect': {'statement': 'Exact fictional supplied-record contrast.'},
        'evaluator_not_applicable': {k: 'Supplied dimensionless arithmetic only.' for k in
            ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}})
    protocol.preregister(root, prereg, {}, evaluation_harness=True)
    first = run_one(tmp_path, root, evaluation(tmp_path, experiment(tmp_path, 'separate', grouped=False), round=1, goal=goal))
    review_result(root, first, 'separate')
    challenger = evaluation(tmp_path, experiment(tmp_path, 'paired', grouped=True, parent='separate'), round=2, goal=goal)
    graph, result = actual_revision_graph(tmp_path, root, 'separate', challenger)
    assert result['complete']
    revised = cycle.adopt_revision(root, graph_root=graph, node_id='improve')
    assert revised['revisions'][-1]['old_votes_carried'] == []
    second = run_one(tmp_path, root, challenger, designed=True)
    review_result(root, second, 'paired')
    run = Authority(root)
    artifacts['screen']['verdicts'] = [real_decision(root, run, 'screen',
        {'idea': 'Ia', 'verdict': 'promote', 'mutable_paths': []}, 'R2')]
    for name in ('baseline', 'screen'):
        complete_stage(root, name, write(root/(name+'.json'), artifacts[name]), 'graph', settings)
    _, state = cycle._load(root)
    selection_request = write(root/'select.json', {
        'rule': case['selection_rule'], 'regime': 'open_exploratory',
        'trials': [{'id': e['id'], 'candidate': e['id'], 'result': e['observation']['result']}
                   for e in state['experiments']]})
    authorize(root, protocol.selection_action(selection_request))
    selected = protocol.commit_selection(root, selection_request)
    assert selected['selected'] == ['paired'] and selected['N'] == 2
    confirmation = run_one(tmp_path, root, confirm)
    # The confirmation repeats the paired arithmetic, with fresh exposure and fresh review.
    review_result(root, confirmation, 'confirmation')
    _, state = cycle._load(root)
    selected_pin = write(root/'selected.json', selected)
    confirm_pin = state['experiments'][-1]['observation']['result']
    report = protocol.selection_report(selected, [confirm_pin], base_dir=root, state=state)
    report_pin = write(root/'selection-report-current.json', report)
    assert report['promoted'] == ['paired']
    record_property('full_cycle_phase', 'ordinary-executions-and-reviews-complete')
    full = research_evaluation.stop_records(state)
    artifacts['validate'] = {'withheld_cells': ['confirm'],
        'rounds': [{'round': i, 'candidates': [e['candidate']], 'successes': 0, 'results': [e['source']],
                    'seed_reinjection': []} for i, e in enumerate(full, 1)],
        'stop': {**case['stop_rule'], 'reason': 'max_rounds'},
        'selection': real_decision(root, run, 'selection', {'rule': 'reviewed_dominance',
            'comparison': cycle._pin(second/'outputs/attempt-1/result.json'),
            'receipt': selected_pin, 'confirmation_pins': [confirm_pin]}, 'R2')}
    artifacts['acceptance']['claims'] = [real_decision(root, Authority(confirmation), 'claim', {
        'id': 'K1', 'kind': 'finding', 'N': 2, 'selection_receipt': selected_pin,
        'selection_report': report_pin, 'verdict': 'exploratory',
        'independent_review': write(root/'independent-current.json', review_receipt(second))}, 'R3')]
    # Inert arithmetic and role calls cannot establish a research finding.
    # Preserve the base's missing-producer refusal; reporting an exploratory
    # finding is the admissible full-stage control, not scientific acceptance.
    claim = artifacts['acceptance']['claims'][0]
    assert protocol._rdj(claim, 'R3', root)['outcome'] == 'authorize'
    if protocol.producer_pending():
        with pytest.raises(ValueError, match='producer_pending'):
            protocol.validate_stage_artifact('acceptance', {'claims': [{**claim, 'verdict': 'accepted'}]},
                base_dir=root, regime='open_exploratory')
    record_property('full_cycle_phase', 'rdj-and-exploratory-artifacts-complete')
    # Freeze the actual observed studies and reviewed RDJ decisions. Both stage
    # engines then consume identical evidence at identical paths; clocks and
    # random external delivery identifiers use the existing parity normalizer.
    if len(engines) > 1:
        frozen = tmp_path/'frozen-campaign'
        shutil.copytree(root, frozen)
        frozen_custody = tmp_path/'frozen-decision-custody'
        shutil.copytree(custody, frozen_custody)
    snapshots = []
    for engine in engines:
        if engine != engines[0]:
            shutil.rmtree(root)
            shutil.copytree(frozen, root)
            shutil.rmtree(custody)
            shutil.copytree(frozen_custody, custody)
        for name in case['expected_stages'][4:]:
            complete_stage(root, name, write(root/('current-'+name+'.json'), artifacts[name]), engine, settings)
            record_property('full_cycle_phase', engine+':'+name)
        snapshots.append(orch.parity_snapshot(root))
    parity = None
    if len(engines) > 1:
        parity = orch.parity_result('synthetic-research-full-cycle',
            'tests/unit/test_research_full_cycle.py::test_all_stages_complete_after_actual_review_revision_and_confirmation',
            *snapshots, run_path=tmp_path)
        record_property('research_full_cycle_parity', json.dumps(parity, sort_keys=True))
        assert parity['equal'], {'parity': parity, 'different_sections': [key for key in snapshots[0]
            if orch._normalized(snapshots[0][key]) != orch._normalized(snapshots[1][key])]}
    status = protocol.methodology_status(root)
    assert status['complete'] and [r['status'] for r in status['record']['stages']] == ['done']*9
    assert status['scientific_acceptance'] is False
    request = report_request(tmp_path, root, confirmation)
    request['artifact_request']['basis'][0]['path'] = 'context-request.json'
    request['artifact_request']['tools']['study']['path'] = str(confirmation.relative_to(tmp_path)/'outputs/attempt-1/result.json')
    synthesis = cycle.synthesize(root, request, base_dir=tmp_path)
    assert len(synthesis['all_evidence_including_negative_and_reopened']) == 3
    assert not synthesis['benefit_measured'] and not synthesis['physics_validated']
    predecessor = physics_review._view(*physics_review._read(confirmation))['cycle']
    manifest, final = package(confirmation, predecessor)
    report_text = synthesis['report']['report_text']
    write(confirmation/'final-draft/report.json', {
        'kind': 'scientific_quantitative_report_draft', 'report_text': report_text})
    write(confirmation/'final-draft/recipe.json', request)
    for row in final['artifacts']:
        row['sha256'] = cycle._pin(row['path'])['sha256']
    for row in final['changes_since_checkin2']:
        row['current_sha256'] = cycle._pin(row['path'])['sha256']
    manifest = {k: v for k, v in write(Path(manifest['path']), final).items() if k != 'size'}
    judgment.open_final_cycle(confirmation, manifest=manifest, check_results='inputs/checks-final.json')
    assert physics_review.gate_errors(confirmation, 'delivery')
    review_result(root, confirmation, 'confirmation', final=True)
    assert final_results_review.gate(confirmation, manifest, report=report_text, recipe=request)
    assert_architecture(root, confirmation)
    if parity is not None:
        record = orch.parity_record([parity])
        record_property('research_parity_source_identity', json.dumps({
            key: record[key] for key in ('bindings', 'fixture_sources')}, sort_keys=True))
    return root, confirmation


def full_cycle(tmp_path, record_property, *, engines=('legacy', 'graph')):
    import sys
    controller_tests = str(Path(__file__).parent/'controller')
    if controller_tests not in sys.path:
        sys.path.insert(0, controller_tests)
    from p11_fakes import captured_operator
    with captured_operator(tmp_path):
        return _full_cycle(tmp_path, record_property, engines=engines)


def test_all_stages_complete_after_actual_review_revision_and_confirmation(tmp_path, record_property):
    """Extend the old first-R2 parity boundary through every bound stage, without fabricated evaluations."""
    full_cycle(tmp_path, record_property)
