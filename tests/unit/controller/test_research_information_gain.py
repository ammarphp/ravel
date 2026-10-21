"""Qualitative information gain gates real research.loop effects before dispatch."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import pytest

from p11_fakes import FakeRunStore, FakeStep, installed_step
from ravel.controller.routes.research import loop_budget
from ravel.workflow import (graph_substrate, research_controller as bridge,
    research_coordinator_decisions as decisions, research_orchestrator as orch,
    research_cycle as cycle, research_protocol as protocol)
from test_langgraph_research_orchestration import (
    METHOD_REQUEST_BYTES, context, open_fixture, presented_effects)
from test_research_cycle import write
from test_research_default_protocol import synthetic_artifacts
from test_research_full_cycle import CASE, complete_stage, stage_settings
from test_research_full_cycle_authority import authorize, intake, satisfy_initial_staffing
from test_research_full_cycle_outer import OuterHost


@pytest.mark.parametrize('worthwhile', [True, False], ids=['continue-then-stop', 'stop-before-effect'])
def test_information_gain_controls_checkpointed_research_loop(tmp_path, monkeypatch, worthwhile):
    actual_prepare = orch.prepare_open

    def prepare(parent, out, **kwargs):
        _, parent = intake(tmp_path)
        settings = stage_settings()
        kwargs['runtime'] = {**kwargs['runtime'], 'roles': settings['roles'],
                             'tiers': settings['tiers'], 'max_wall_seconds': 900}
        kwargs['campaign']['budget'].update(calls=128, output_tokens=500000, wall_seconds=86400)
        kwargs['review']['arguments'] = {'model': 'control', 'reasoning_effort': 'high',
            'max_output_tokens': 2048, 'max_wall_seconds': 120,
            'claim_scope': 'supplied_math_diagnostic'}
        return actual_prepare(parent, out, **kwargs)

    with monkeypatch.context() as setup:
        setup.setattr(orch, 'prepare_open', prepare)
        request, template, source, _ = open_fixture(tmp_path, max_request_bytes=METHOD_REQUEST_BYTES)
    _, declaration = context(tmp_path)
    seen = []

    def callback(node, presentation):
        cores = [p for p in presentation.get('input_artifacts', []) if p['id'] == 'scientific-core']
        if not cores or json.loads(cores[0]['content'])['phase'] != 'action':
            return template.callback(node, presentation)
        core = decisions.expand_decision_context(json.loads(cores[0]['content']))
        effects = presented_effects(core, presentation)
        # This is a real, successful local preparation operation, with no science or network call.
        action = 'preparation-tool' if not effects else 'progress'
        args = {'action': 'scientific-context', 'parameters': {'request_input': 'request'},
            'inputs': [{'id': 'request', 'pin': {'generated_record': 'context-request', 'field': 'pin3'}},
                       {'id': 'method', 'pin': source}],
            'records': [{'id': 'context-request', 'purpose': 'prospective_configuration',
                'value': deepcopy(declaration), 'source_basis': [source]}]} if not effects else {
                    'reason': 'Prepared context retained; no further discriminating comparison is justified.'}
        decision = 'continue' if worthwhile and not effects else 'stop'
        assert 'information_gain' in node['parameters']['output_schema']['required']
        assert node['parameters']['output_schema']['properties']['information_gain'] == loop_budget.assessment_schema()
        projection = core['loop_budget']['per_cycle']
        assessment = {'decision': decision,
            'expected_gain': ('Resolve the supplied source configuration once.' if decision == 'continue'
                              else 'Another preparation would add no discriminating evidence.'),
            'cost_justification': (f"The shown per_cycle high projection {projection['high']['cost_usd']} USD "
                + ('is justified by resolving the source configuration.' if decision == 'continue'
                   else 'is not justified by repeated source configuration.')),
            'evidence_input_ids': ['scientific-core']}
        seen.append({'action': action, 'assessment': assessment, 'core': deepcopy(core), 'effects': deepcopy(effects)})
        return {'kind': 'research-action', 'action': action, 'reason': assessment['expected_gain'],
                'arguments_json': json.dumps(args), 'information_gain': assessment}

    store = FakeRunStore('information-gain-' + str(worthwhile), root=tmp_path.parent / (tmp_path.name + '-store'))
    peer = FakeStep(OuterHost(callback))
    root = tmp_path / 'campaign'
    budget = loop_budget.declare(decisions.request(request), [], tier='full')
    step = bridge._step('campaign', 'subgraph', outputs=['outputs/progress.json'])
    step.update(graph={'id': 'research.loop', 'instance': {}}, parameters={
        'research_request': request, 'campaign': str(root), 'research_loop_budget': budget})
    controller_context = {'run_dir': str(tmp_path), 'plan_sha256': cycle.ce.digest({'steps': [step]}),
                          'research_loop_budget': budget, 'research_campaign': str(root)}
    with installed_step(peer), bridge.bound(store, controller_context):
        held = bridge.invoke(store, step, controller_context)
        assert held['phase'] == 'ordinary_effect_required'
        assert seen == []
        satisfy_initial_staffing(root)
        parent = Path(orch._read(request)['parent_contract']['path']).parent.parent
        satisfy_initial_staffing(parent, campaign_root=root)
        artifacts = synthetic_artifacts(root)
        for stage in ('limitation_census', 'ideas'):
            complete_stage(root, stage, write(root / (stage + '.json'), artifacts[stage]), 'graph', stage_settings())
        case = json.loads(CASE.read_text())
        protocol.preregister(root, write(root / 'prospective.json', {
            'schema_version': 1, 'kind': 'research-preregistration',
            'selection_rule': case['selection_rule'], 'stop_rule': case['stop_rule'], 'approximations': [],
            'withheld_cells': [], 'expected_effect': {'statement': 'Supplied software configuration only.'},
            'evaluator_not_applicable': {k: 'No measurement in this preparation control.' for k in
                ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}}), {}, evaluation_harness=True)
        response = {k: v for k, v in cycle._pin(root / 'head.json').items() if k != 'size'}
        responses = {item['id']: {'response': response} for item in held['checkpoint']['interrupts']}
        for item in held['checkpoint']['interrupts']:
            pending = item['payload']['payload']
            action = (orch.stage_delivery_action(root, pending, responses[item['id']])
                      if pending['kind'] == 'research-stage-delivery-required' else
                      orch.delivery_action(root, pending['failure_id'], responses[item['id']]))
            authorize(parent, action)
        result = bridge.invoke(store, step, {**controller_context, 'responses': responses})
        assert seen, result
        records = [r['record'] for r in store.scan(loop_budget.DECISION)]
        assert [r['assessment'] for r in records] == [r['assessment'] for r in seen]
        assert len(records) == (2 if worthwhile else 1)
        for record in records:
            assert record['budget_sha256'] == budget['sha256']
            assert record['next_cycle_projection'] == budget['per_cycle']
            assert record['observation_sha256'] in {
                r['record']['receipt_sha256'] for r in store.scan('step-observation')}
            assert hashlib.sha256(Path(record['output']['path']).read_bytes()).hexdigest() == record['output']['sha256']
            assert [p['id'] for p in record['evidence']] == ['scientific-core']
            for pin in record['evidence']:
                raw = Path(pin['path']).read_bytes()
                assert len(raw) == pin['size'] and hashlib.sha256(raw).hexdigest() == pin['sha256']
        _, state = cycle._load(root)
        effects = [e for e in state['events'] if e['kind'] == 'coordinator_effect_committed']
        if worthwhile:
            assert records[0]['action_admitted'] is True
            assert records[-1]['action'] == 'progress' and records[-1]['assessment']['decision'] == 'stop'
            assert effects
            assert not store.scan('research-budget-boundary')
            assert result['kind'] == 'research_progress_synthesis'
            assert seen[-1]['core']['prior_operation_effects']
            assert len(seen[-1]['effects']) == 1
            assert seen[-1]['effects'][0]['actual_effect']['status'] == 'prepared'
            assert seen[-1]['effects'][0]['actual_effect']['actual_preparation']['value']['action'] == 'scientific-context'
        else:
            assert records[0]['action'] == 'preparation-tool' and records[0]['action_admitted'] is False
            assert effects == []
            boundaries = [r['record'] for r in store.scan('research-budget-boundary')]
            assert [r['kind'] for r in boundaries] == ['research_information_gain']
            assert result['kind'] == 'research_bounded_synthesis'
            assert result['delivery_receipt']['qualified'] is True
            assert result['delivery_receipt']['accepted'] is False
        used = loop_budget.committed(store, budget)
        assert used['cycles'] < budget['max_cycles']
        assert used['children'] < budget['max_children']
        assert used['cost_usd'] < budget['cost_ceiling_usd']
        assert time.time() < state['timing']['deadline_epoch']
        receipt = store.scan('research-subgraph')[-1]['record']
        assert receipt['observation']['checkpoint_id']
        assert (Path(receipt['scope']) / graph_substrate.DB).exists()
        before = deepcopy((seen, effects, records, peer.calls))
        bridge.invoke(store, step, controller_context)
        assert (seen, [e for e in cycle._load(root)[1]['events'] if e['kind'] == 'coordinator_effect_committed'],
                [r['record'] for r in store.scan(loop_budget.DECISION)], peer.calls) == before
