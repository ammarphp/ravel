"""research.loop and research.stage on the graph substrate.

Dual-run parity with the legacy engine, failures as decision turns, drain through
``ravel graph stop``, and per-role models from card tiers. Synthetic sibling fixtures
on stub transports only: no native run, no model call, no physics inference.
"""
from contextlib import contextmanager
import os
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

import pytest

from ravel.workflow import graph_environment  # noqa: F401  (strict msgpack before LangGraph)
from ravel.workflow import (agent_graph, effect_ledger, graph_registry, graph_substrate, research_cycle as cycle,
                            research_coordinator_decisions as decisions, research_orchestrator as orch,
                            research_protocol as protocol, review_context, transport_registry)
from ravel.workflow.graphs import hosts, stage as stage_graph

from test_agent_graph import external_response
from test_langgraph_research_orchestration import ScriptedResearchHost, context, open_fixture, parent
from test_research_default_protocol import STAGES, governed_cycle, register, synthetic_artifacts, write

EXTERNAL = {'model': 'host-agent', 'reasoning_effort': 'high', 'adapter': 'external'}
STAGE_SETTINGS = {**EXTERNAL, 'max_output_tokens': 1024, 'max_wall_seconds': 900}
SCREEN = STAGES.index('screen')  # the first R2 stage; R2+ stages wait for per-role models
STAGE_ROLES = sorted({r for row in protocol.default_protocol()['stages'] for r in row['roles']})



@pytest.fixture(autouse=True)
def inert_decision_provider(monkeypatch):
    """The external decision provider is an inert seam for these transport and parity controls, as
    in the upstream protocol transport fixtures; test_gate_wiring and test_decision_gate test refusal."""
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])

# ---- stub transports ----------------------------------------------------------------------------

def deliver(graph_root):
    """Host delivery for every pending role of a stage Graph: accept, no findings (synthetic)."""
    for role, row in agent_graph.status(graph_root)['nodes'].items():
        if row['status'] == 'completed':
            continue
        pending = agent_graph.prepare_external(graph_root, role)
        fields = json.loads(Path(pending['request_file']).read_text())['parameters']['output_schema']['properties']
        public = {k: fields[k]['const'] for k in ('stage', 'role_id', 'subject_sha256')}
        public.update(verdict='accept', findings=['Synthetic transport control only.'], attributed_claim_ids=[])
        response = external_response(pending, Path(graph_root).parent / (role + '-response.json'), value=public,
                                     actor_id='synthetic-' + role, observed_model='host-agent')
        agent_graph.deliver_external(graph_root, role, response)


def deliver_all(out):
    for graph_root in sorted(Path(out).glob('turns/*/effect/protocol/graph')):
        if not agent_graph.status(graph_root)['complete']:
            deliver(graph_root)


class PresentingHost(ScriptedResearchHost):
    """A stub host that presents every artifact of a role packet (complete presentation)."""

    def __init__(self, callback, *, gate=None):
        super().__init__(callback)
        self.gate = gate

    def execute(self, item, request, control):
        self._item = item
        if self.gate is not None:
            self.gate(item)
        return super().execute(item, request, control)

    def _presented_result(self, result, context):
        result = super()._presented_result(result, context)
        packet = (getattr(self, '_item', None) or {}).get('packet')
        if packet and 'evidence_presentation' in result.get('isolation', {}):
            manifest = review_context.verify_packet(packet['path'], expected_manifest_sha256=packet['manifest_sha256'])
            shown = result['isolation']['evidence_presentation']
            shown['presented_subject_sha256s'] = sorted(set(shown['presented_subject_sha256s'])
                                                        | {a['sha256'] for a in manifest['artifacts']})
        return result


@contextmanager
def goal_bound_stage_specs():
    """Apply the campaign's inherited goal binding to a stage spec before its reservation re-check,
    identically for both engines. complete_stage now applies the same binding itself
    (test_goal_bound_stage_completion), so this wrapper changes no outcome."""
    real = cycle.validate_graph_reservation

    def bound(state, graph_root, spec):
        if 'goal_binding' in state['contract'] and 'goal_binding' not in spec:
            spec = {**spec, 'goal_binding': state['contract']['goal_binding']}
        return real(state, graph_root, spec)
    cycle.validate_graph_reservation = bound
    try:
        yield
    finally:
        cycle.validate_graph_reservation = real


# ---- the synthetic open question -----------------------------------------------------------------

def open_question(base, *, stages=4, failing_turn=None, roles=None, gate=None):
    """A synthetic open question: declare, assess, two idea streams, then the decider runs the next
    ``stages`` protocol stages (a failing action at ``failing_turn``) and reports progress."""
    contract, cp = parent(base)
    source, declared = context(base)
    roles = roles or {r: dict(EXTERNAL) for r in STAGE_ROLES}
    judges = list({row['model']: {k: row[k] for k in ('model', 'reasoning_effort')} for row in
                   [EXTERNAL, *roles.values()]}.values())
    campaign = {'id': 'synthetic-open-question', 'budget': {'calls': 48, 'output_tokens': 400000,
                'wall_seconds': 86400, 'native_attempts': 2}, 'max_experiments': 4, 'exploration_every': 2,
                'required_experiments': [], 'premises': []}
    runtime = {'model': 'scripted-control', 'reasoning_effort': 'high', 'adapter': 'model', 'max_output_tokens': 2048,
               'max_wall_seconds': 900, 'tiers': {'judgment': judges}, 'roles': roles}
    mapping = [{'obligation_id': r['id'], 'original': deepcopy(r),
                'quantities': ['conditional-variance'] if r['id'] == 'original-request' else [],
                'method': 'Synthetic protocol traversal; no physics inference.', 'sources': [source],
                'unresolved': '' if r['id'] == 'original-request' else r['statement']}
               for r in contract['task_requirements']['obligations']]
    rp = orch.prepare_open(cp, base / 'request', base_dir=base, campaign=campaign, runtime=runtime,
                           evidence=[{'pin': source, 'purpose': 'model_context'}], candidate_modes=['quantities'],
                           review={'arguments': {}, 'allow_control': True},
                           max_decisions=stages + (failing_turn is not None) + 1)
    root = base / 'campaign'
    out = root / 'coordinator'
    artifacts = {}

    def callback(item, ctx):
        if item['role'] in {'critic', 'verifier'}:
            return {'kind': 'context-method-assessment',
                    'subject_sha256': item['parameters']['output_schema']['properties']['subject_sha256']['const'],
                    'verdict': 'adequate_for_prospective_tests', 'findings': ['Synthetic control.'],
                    'summary': 'Original obligations remain unresolved.'}
        core = json.loads(next(p['content'] for p in ctx['input_artifacts'] if p['id'] == 'scientific-core'))
        if core['phase'] == 'declare-context':
            return {'kind': 'research-context-declaration', 'context_json': json.dumps(declared),
                    'obligation_mapping_json': json.dumps(mapping), 'modes': [], 'reason': 'Synthetic declaration.'}
        if core['phase'] == 'hypotheses':
            stream = core['stream']
            return {'hypotheses': [{'id': stream + '-law', 'statement': 'A synthetic rival law.', 'stream': stream,
                                    'premise_ids': [], 'source_basis': [source], 'parents': [],
                                    'operator': 'limitation_fix', 'identity_signature': {
                                        'observable': 'relation', 'scope': 'synthetic records',
                                        'prediction': stream + '-law'},
                                    'kill_condition': {'comparison': 'differs', 'observable': 'relation'},
                                    'reopening_trigger': {'kind': 'changed_input', 'field': 'revision',
                                                          'op': 'gt', 'value': 0},
                                    'what_is_new': None}]}
        turn = len(core['prior_operation_effects'])
        remaining = STAGES[1:1 + stages]
        if turn == failing_turn:
            action, arguments = 'synthesize', {'report_request': {
                'path': str(base / 'absent-report.json'), 'sha256': '0' * 64, 'size': 1}}
        else:
            index = turn - (1 if failing_turn is not None and turn > failing_turn else 0)
            action, arguments = (('protocol-stage', {'artifact': artifacts[remaining[index]]}) if index < len(remaining)
                                 else ('progress', {'reason': 'Synthetic traversal complete; no acceptance.'}))
        return {'kind': 'research-action', 'action': action, 'reason': 'Synthetic control choice.',
                'arguments_json': json.dumps(arguments)}
    host = PresentingHost(callback, gate=gate)
    # Shared preparation for both engines: campaign, operation, limitation census, preregistration.
    orch._open_plan(root, rp, out, host=host)
    synthetic = synthetic_artifacts(root)
    for name in STAGES:
        artifacts[name] = write(root, 'artifacts/' + name + '.json', synthetic[name])
    settings = {k: v for k, v in {**runtime, **EXTERNAL}.items() if k != 'roles'}
    census = base / 'setup-census'
    orch.run_protocol_stage(root, artifacts['limitation_census'], census, host=host, settings=settings)
    deliver(census / 'graph')
    assert orch.run_protocol_stage(root, artifacts['limitation_census'], census, host=host, settings=settings)['complete']
    register(root)
    return rp, host, root, out


def run_legacy(root, rp, out, host):
    for _ in range(20):
        deliver_all(out)
        result = orch.open_research(root, rp, out, host=host)
        if result.get('phase') != 'ordinary_effect_required':
            return result
    raise AssertionError('legacy engine did not finish: ' + json.dumps(result, default=str)[:3000])


def answer(root):
    return {'response': {'path': str(root / 'head.json'), 'sha256': cycle._pin(root / 'head.json')['sha256']}}


def run_graph(root, rp, out, host):
    result = orch.run_graph(root, rp, out, host=host, experimental=True)
    for _ in range(30):
        if result.get('phase') != 'ordinary_effect_required':
            return result
        deliver_all(out)
        result = orch.respond_graph(root, rp, out, {i['id']: answer(root) for i in result['checkpoint']['interrupts']},
                                    host=host, experimental=True)
    raise AssertionError('graph engine did not finish')


def dual(tmp_path, build, legacy, graph):
    """Run one fixture on each engine at the same paths, one after the other; return both snapshots."""
    base = (tmp_path / 'run').resolve()
    base.mkdir()
    old_outcome = legacy(*build(base))
    old = orch.parity_snapshot(base / 'campaign' if (base / 'campaign').exists() else base / 'cycle')
    base.rename(tmp_path / 'legacy')
    base.mkdir()
    new_outcome = graph(*build(base))
    new = orch.parity_snapshot(base / 'campaign' if (base / 'campaign').exists() else base / 'cycle')
    return old, new, old_outcome, new_outcome


def keep_parity_result(fixture_id, test_name, old, new, tmp_path):
    """The computed parity result of one fixture; appended to $RAVEL_PARITY_RESULTS when set, which
    ``research_orchestrator parity --write --results`` turns into the kept record."""
    result = orch.parity_result(fixture_id, 'tests/unit/test_research_loop_graph.py::' + test_name, old, new,
                                run_path=(tmp_path / 'run').resolve())
    target = os.environ.get('RAVEL_PARITY_RESULTS')
    if target:
        with open(target, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(result, sort_keys=True) + '\n')
    return result


def receipts(root, status=None):
    return [r for r in effect_ledger.receipts(root) if status is None or r['status'] == status]


# ---- 1. dual-run parity ----------------------------------------------------------------------------

def test_open_question_runs_equal_on_both_engines(tmp_path):
    def build(base):
        rp, host, root, out = open_question(base, stages=2)
        return root, rp, out, host
    with goal_bound_stage_specs():
        old, new, old_outcome, new_outcome = dual(tmp_path, build, run_legacy, run_graph)
    assert keep_parity_result('synthetic-open-question', 'test_open_question_runs_equal_on_both_engines',
                              old, new, tmp_path)['equal']
    assert old == new and old['sha256'] == new['sha256']
    assert old_outcome['kind'] == new_outcome['kind'] == 'research_progress_synthesis'
    assert [s['status'] for s in new['stages']][:3] == ['done'] * 3
    assert [e['action'] for e in new['coordinator_effects']] == ['protocol-stage'] * 2
    # The graph engine took every role through the substrate's ledger: no open effect remains.
    root = tmp_path / 'run' / 'campaign'
    assert receipts(root, 'started') == receipts(root, 'ambiguous') == []
    assert {r['identity']['node'] for r in receipts(root) if 'node' in r['identity']} >= {
        'declare_call', 'assessment_call', 'idea_call', 'decision_call', 'stage_commit'}


def test_stage_graph_matches_the_legacy_stage_runner_through_the_first_r2_stage(tmp_path):
    """Every R0 stage completes, and the first R2 stage is refused at dispatch, identically on both engines."""
    def build(base):
        root = governed_cycle(base)
        register(root)
        return root, synthetic_artifacts(root)

    def legacy(root, artifacts):
        host = __import__('ravel.workflow.agent_host', fromlist=['AgentHost']).AgentHost()
        for name in STAGES[:SCREEN]:
            artifact, out = write(root, name + '.json', artifacts[name]), root / 'coordinator/stages' / name
            if not orch.run_protocol_stage(root, artifact, out, host=host, settings=STAGE_SETTINGS)['complete']:
                deliver(out / 'graph')
                assert orch.run_protocol_stage(root, artifact, out, host=host, settings=STAGE_SETTINGS)['complete']
        artifact, out = write(root, 'screen.json', artifacts['screen']), root / 'coordinator/stages/screen'
        with pytest.raises(transport_registry.TransportRefusal, match='unknown-family'):
            orch.run_protocol_stage(root, artifact, out, host=host, settings=STAGE_SETTINGS)

    def graph(root, artifacts):
        host = __import__('ravel.workflow.agent_host', fromlist=['AgentHost']).AgentHost()
        gates = lambda scope, gate, action: protocol.gate_errors(root, gate, action)
        with hosts(host) as key:
            for name in STAGES[:SCREEN + 1]:
                artifact, out = write(root, name + '.json', artifacts[name]), root / 'coordinator/stages' / name
                instance = {'campaign': 'parity', 'request': hashlib.sha256(name.encode()).hexdigest()}
                request = stage_graph.request(artifact=artifact, out=out, settings=STAGE_SETTINGS, host_key=key,
                                              operation_sha256='0' * 64)
                seen = graph_substrate.run(root, stage_graph.GRAPH_ID, instance, input={'stage_request': request},
                                           gate_check=gates)
                if name == 'screen':
                    assert seen['terminal']['status'] == 'decision_required' and not seen['interrupts']
                    continue
                assert [i['kind'] for i in seen['interrupts']] == ['external_delivery']
                deliver(out / 'graph')
                seen = graph_substrate.respond(root, stage_graph.GRAPH_ID, instance,
                                               {seen['interrupts'][0]['id']: answer(root)}, gate_check=gates)
                assert seen['terminal'] is None and seen['next'] == []
    old, new, _, _ = dual(tmp_path, build, legacy, graph)
    assert keep_parity_result('synthetic-protocol-stages',
                              'test_stage_graph_matches_the_legacy_stage_runner_through_the_first_r2_stage', old, new, tmp_path)['equal']
    assert old == new and new['methodology_complete'] is False
    assert [s['status'] for s in new['stages']][:SCREEN + 1] == ['done'] * SCREEN + ['pending']
    # An R2 stage on one host model whose family RAVEL cannot read is refused before any review is prepared.
    assert not (tmp_path / 'run/cycle/coordinator/stages/screen/review').exists()


def test_open_question_engines_agree_where_both_stop_on_the_baseline_failure(tmp_path):
    """The base presentation check stops both engines at the first assessment: equal receipts,
    and the graph engine ends in a typed decision status where the legacy engine raises."""
    def build(base):
        rp, host, _, _ = open_fixture(base)
        return base / 'campaign', rp, base / 'campaign/coordinator', host

    def legacy(root, rp, out, host):
        with pytest.raises(ValueError, match='presentation'):
            orch.open_research(root, rp, out, host=host)
        return None
    old, new, _, outcome = dual(tmp_path, build, legacy, lambda root, rp, out, host: orch.run_graph(
        root, rp, out, host=host, experimental=True))
    assert keep_parity_result('open-question-baseline-failure',
                              'test_open_question_engines_agree_where_both_stop_on_the_baseline_failure',
                              old, new, tmp_path)['equal']
    assert old == new
    assert outcome['phase'] == 'decision_required' and outcome['status']['reason'] == 'exception'
    assert outcome['failures'][-1]['node'] == 'assessment_call'


def _results(equal=True):
    return [{'id': fixture, 'test': 'tests/unit/test_research_loop_graph.py::test_' + fixture.replace('-', '_'),
             'legacy_sha256': 'a' * 64, 'graph_sha256': ('a' if equal else 'b') * 64}
            for fixture in orch.PARITY_FIXTURES]


def test_default_engine_switches_only_on_a_computed_current_parity_record(tmp_path, monkeypatch):
    path = tmp_path / 'parity.json'
    monkeypatch.setattr(orch, 'PARITY_RECORD', path)
    assert orch.default_engine() == 'legacy'
    record = orch.parity_record(_results())
    assert all(f['equal'] for f in record['fixtures']) and record['sha256'] == orch.parity_digest(record)
    path.write_text(json.dumps(record))
    assert orch.parity_status()['passed'] and orch.default_engine() == 'graph'
    # Equality is computed from the recorded snapshot digests, never read from a flag.
    record = orch.parity_record(_results(equal=False))
    assert not any(f['equal'] for f in record['fixtures'])
    path.write_text(json.dumps(record))
    assert orch.default_engine() == 'legacy'
    forged = {**record, 'fixtures': [{**f, 'equal': True} for f in record['fixtures']]}
    path.write_text(json.dumps({**forged, 'sha256': orch.parity_digest(forged)}))
    assert orch.parity_status()['reason'] == 'a parity fixture differs' and orch.default_engine() == 'legacy'
    # The digest covers the record; a hand edit without recomputation is refused.
    good = orch.parity_record(_results())
    path.write_text(json.dumps({**good, 'recorded_by': 'someone else'}))
    assert orch.parity_status()['reason'] == 'parity record digest differs' and orch.default_engine() == 'legacy'
    # A missing fixture, another loop structure, another child graph or changed implementation bytes lapse it.
    short = orch.parity_record(_results()[:1])
    path.write_text(json.dumps(short))
    assert orch.parity_status()['reason'] == 'parity fixtures missing' and orch.default_engine() == 'legacy'
    for field, value in (('structure_sha256', '0' * 64), ('closure', [['research.loop', 1, '0' * 64]]),
                         ('implementation', {'workflow/research_orchestrator.py': '0' * 64})):
        changed = {**good, 'bindings': {**good['bindings'], field: value}}
        path.write_text(json.dumps({**changed, 'sha256': orch.parity_digest(changed)}))
        assert orch.parity_status()['reason'] == 'parity record is for another loop implementation', field
        assert orch.default_engine() == 'legacy'


def test_graph_engine_without_a_current_parity_record_is_refused_unless_experimental(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, 'PARITY_RECORD', tmp_path / 'absent.json')
    fresh = tmp_path / 'fresh'
    with pytest.raises(ValueError, match='--experimental-engine'):
        orch.engine_for(fresh, fresh / 'coordinator', 'graph')
    assert orch.engine_for(fresh, fresh / 'coordinator', 'graph', experimental=True) == 'graph'
    assert orch.engine_for(fresh, fresh / 'coordinator') == 'legacy'
    # The graph runner itself refuses before any preparation, and labels an explicit experimental run.
    with pytest.raises(ValueError, match='--experimental-engine'):
        orch.run_graph(fresh, {'path': str(tmp_path / 'request.json'), 'sha256': '0' * 64, 'size': 1},
                       fresh / 'coordinator', host=None)
    assert orch.engine_label(experimental=True) == {'engine': 'graph', 'engine_label': 'experimental-engine',
                                                     'parity_passed': False}
    path = tmp_path / 'parity.json'
    path.write_text(json.dumps(orch.parity_record(_results())))
    monkeypatch.setattr(orch, 'PARITY_RECORD', path)
    assert orch.engine_label() == {'engine': 'graph', 'engine_label': 'graph', 'parity_passed': True}
    assert orch.engine_label(experimental=True)['engine_label'] == 'graph'


def test_research_orchestrate_run_refuses_graph_without_parity(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(orch, 'PARITY_RECORD', tmp_path / 'absent.json')
    for name in ('request.json', 'host.json'):
        (tmp_path / name).write_text('{}')
    code = orch.main(['run', '--cycle', str(tmp_path / 'c'), '--request', str(tmp_path / 'request.json'),
                      '--host-config', str(tmp_path / 'host.json'), '--out', str(tmp_path / 'out'), '--engine', 'graph'])
    assert code == 2 and '--experimental-engine' in capsys.readouterr().out


def test_a_coordinator_continues_on_the_engine_that_started_it(tmp_path, monkeypatch):
    record = tmp_path / 'parity.json'
    record.write_text(json.dumps(orch.parity_record(_results())))
    monkeypatch.setattr(orch, 'PARITY_RECORD', record)
    legacy_cycle, graph_cycle = tmp_path / 'legacy', tmp_path / 'graph'
    (legacy_cycle / 'coordinator/framework').mkdir(parents=True)
    (legacy_cycle / 'coordinator/framework/checkpoints.sqlite').write_bytes(b'')
    (graph_cycle / 'framework').mkdir(parents=True)
    (graph_cycle / graph_substrate.DB).write_bytes(b'')
    assert orch.engine_for(legacy_cycle, legacy_cycle / 'coordinator') == 'legacy'
    assert orch.engine_for(graph_cycle, graph_cycle / 'coordinator') == 'graph'
    with pytest.raises(ValueError, match='legacy engine'):
        orch.engine_for(legacy_cycle, legacy_cycle / 'coordinator', 'graph')
    with pytest.raises(ValueError, match='graph engine'):
        orch.engine_for(graph_cycle, graph_cycle / 'coordinator', 'legacy')
    assert orch.engine_for(tmp_path / 'fresh', tmp_path / 'fresh/coordinator', 'legacy') == 'legacy'


def test_kept_parity_record_is_current_for_the_registered_loop_and_these_fixtures():
    """The kept record was computed by ``parity --write`` from this file's parity results; it lapses
    when the loop graph, its child graphs, the loop implementation or these fixtures change."""
    status = orch.parity_status()
    assert status['passed'], status['reason']
    record = status['record']
    assert {f['id'] for f in record['fixtures']} == set(orch.PARITY_FIXTURES)
    source = Path(__file__).read_text()
    assert all(('def ' + f['test'].split('::')[-1] + '(') in source for f in record['fixtures'])
    assert record['fixture_sources'] == {'tests/unit/test_research_loop_graph.py':
                                         hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


# ---- 2. failures become decision turns --------------------------------------------------------------

def test_failed_action_is_an_observation_for_the_next_decision_turn(tmp_path):
    base = (tmp_path / 'legacy').resolve()
    base.mkdir()
    with goal_bound_stage_specs():
        rp, host, root, out = open_question(base, stages=1, failing_turn=1)
        with pytest.raises((ValueError, OSError)):
            run_legacy(root, rp, out, host)
        base = (tmp_path / 'graph').resolve()
        base.mkdir()
        rp, host, root, out = open_question(base, stages=1, failing_turn=1)
        result = run_graph(root, rp, out, host)
    assert result['kind'] == 'research_progress_synthesis'
    effects = orch.parity_snapshot(root)['coordinator_effects']
    assert [e['action'] for e in effects] == ['protocol-stage', 'synthesize']
    failed = effects[1]['actual_effect']
    assert failed['status'] == 'action_failed' and failed['failure']['node'] == 'action_effect'
    assert failed['scientific_acceptance'] is False and failed['observation_not_falsification'] is True
    # The next decision turn was presented the failure, then reported progress.
    last = json.loads((out / 'turns/2/context/scientific-core.json').read_text())
    assert last['prior_operation_effects'][1]['actual_effect']['status'] == 'action_failed'


def test_refused_stage_dispatch_is_observed_by_the_next_decision_turn(tmp_path):
    same = {'model': 'gpt-5', 'reasoning_effort': 'high', 'adapter': 'external'}
    roles = {r: dict(EXTERNAL) for r in STAGE_ROLES}
    roles.update({'screen-producer': dict(same), 'plan-critic': dict(same)})
    base = tmp_path.resolve()
    with goal_bound_stage_specs():
        rp, host, root, out = open_question(base, stages=3, roles=roles)
        result = run_graph(root, rp, out, host)
    assert result['kind'] == 'research_progress_synthesis'
    effects = orch.parity_snapshot(root)['coordinator_effects']
    refused = effects[2]['actual_effect']
    assert refused['status'] == 'action_failed' and refused['failure']['node'] == 'stage'
    assert 'distinct_family_from:plan-critic:screen-producer' in refused['failure']['message']
    # Refused at dispatch: no screen review was prepared and no screen role was asked.
    assert not (out / 'turns/2/effect/protocol/review').exists()
    assert protocol.methodology_status(root)['next_stage'] == 'screen'


# ---- 3. drain through ravel graph stop -------------------------------------------------------------

def test_drain_through_graph_stop_then_continue_without_repeating_an_effect(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def gate(item):
        if item['role'] == 'designer' and not entered.is_set():
            entered.set()
            assert release.wait(60)
    base = tmp_path.resolve()
    with goal_bound_stage_specs():
        rp, host, root, out = open_question(base, stages=1, gate=gate)
        outcome = {}
        worker = threading.Thread(target=lambda: outcome.update(first=orch.run_graph(root, rp, out, host=host,
                                                                                         experimental=True)))
        worker.start()
        assert entered.wait(120)
        assert graph_substrate.main(['stop', '--scope-root', str(root), '--reason', 'synthetic drain']) == 0
        release.set()
        worker.join(120)
        first = outcome['first']
        assert first['phase'] == 'stopped' and first['status']['reason'] == 'stop_requested'
        assert receipts(root, 'started') == receipts(root, 'ambiguous') == []
        drained = len(host.actual_contexts)
        resumed = orch.run_graph(root, rp, out, host=host, clear_stop=True, experimental=True)
        for _ in range(10):
            if resumed.get('phase') != 'ordinary_effect_required':
                break
            deliver_all(out)
            resumed = orch.respond_graph(root, rp, out, {
                i['id']: answer(root) for i in resumed['checkpoint']['interrupts']}, host=host, experimental=True)
    assert resumed['kind'] == 'research_progress_synthesis'
    calls = [c for c in host.actual_contexts]
    assert len(calls) > drained
    # The call that was running when the stop arrived finished once and was never repeated.
    first_call = json.dumps(calls[0], sort_keys=True)
    assert sum(json.dumps(c, sort_keys=True) == first_call for c in calls) == 1


def test_stop_now_also_drains_every_incomplete_child_graph(tmp_path):
    from ravel.workflow.agent_host import AgentHost
    root = governed_cycle(tmp_path)
    artifact = write(root, 'census.json', synthetic_artifacts(root)['limitation_census'])
    pending = orch.run_protocol_stage(root, artifact, root / 'stage', host=AgentHost(), settings=STAGE_SETTINGS)
    assert pending['complete'] is False
    stopped = orch.stop(root, reason='synthetic stop', now=True)
    assert [c['root'] for c in stopped['children']] == [str(root / 'stage/graph')]
    assert stopped['all_gone'] and stopped['loop']['cancellation_epoch'] is not None
    assert (root / 'stage/graph/effects' / effect_ledger.STOP).exists()


def test_stop_now_is_not_all_gone_while_an_in_process_runner_holds_a_scope(tmp_path):
    """all_gone needs every scope released, not only the registered process groups terminated."""
    root = (tmp_path / 'campaign').resolve()
    root.mkdir()
    with graph_substrate.scope_runner(root, orch.LOOP_GRAPH, 'synthetic-thread'):
        stopped = orch.stop(root, reason='synthetic stop', now=True)
        assert stopped['all_gone'] is False and stopped['running'] == [str(root)]
    stopped = orch.stop(root, reason='synthetic stop', now=True)
    assert stopped['all_gone'] is True and stopped['running'] == []


def test_research_orchestrate_stop_drains_the_loop_scope(tmp_path):
    root = tmp_path / 'campaign'
    root.mkdir()
    assert orch.main(['stop', '--cycle', str(root), '--reason', 'synthetic stop']) == 0
    assert (root / effect_ledger.STOP).exists()
    assert graph_substrate.status(root)['stop']['reason'] == 'synthetic stop'


# ---- 4. per-role models --------------------------------------------------------------------------

BASE = {'model': 'scripted-control', 'reasoning_effort': 'high', 'adapter': 'model', 'max_output_tokens': 64,
        'max_wall_seconds': 30}
JUDGES = {'judgment': [{'model': m, 'reasoning_effort': 'high'} for m in ('gpt-5', 'claude-x', 'claude-y')]}


def test_judgment_tier_roles_dispatch_on_judgment_tier_models():
    roles = ['limitation-census', 'sufficiency-verifier']
    default = decisions.role_assignments(BASE, roles)
    assert {r['model_tier'] for r in default.values()} == {'judgment'} and {r['source'] for r in default.values()} == {'runtime'}
    tiered = decisions.role_assignments({**BASE, 'tiers': {'judgment': {'model': 'claude-judge', 'reasoning_effort': 'max'}}},
                                        roles)
    assert {(r['model'], r['model_tier'], r['source']) for r in tiered.values()} == {('claude-judge', 'judgment', 'tier')}
    assert all(r['qualification'] == 'unqualified' for r in tiered.values())
    with pytest.raises(transport_registry.TransportRefusal) as refused:
        decisions.role_assignments({**BASE, 'tiers': {'cheap': {'model': 'claude-small', 'reasoning_effort': 'low'}},
                                    'roles': {'limitation-census': {'model': 'claude-small', 'reasoning_effort': 'low'}}},
                                   roles)
    assert refused.value.missing == ['tier:limitation-census:judgment']
    with pytest.raises(transport_registry.TransportRefusal):
        decisions.role_assignments({**BASE, 'tiers': {'agent': {'model': 'claude-small', 'reasoning_effort': 'low'}},
                                    'roles': {'sufficiency-verifier': {'model': 'claude-small', 'reasoning_effort': 'low'}}},
                                   roles)


def test_a_role_row_cannot_declare_its_own_tier():
    """F9: the tier a role needs comes from its card; the tier a model serves comes from the run's
    tier map (or the single runtime, the coordinator's judgment model), never from a role row's label."""
    roles = ['limitation-census', 'sufficiency-verifier']
    with pytest.raises(ValueError, match='may not declare a tier'):
        decisions.role_assignments({**BASE, 'roles': {'limitation-census': {
            'model': 'claude-small', 'reasoning_effort': 'low', 'tier': 'judgment'}}}, roles)
    # A role row on a model the tier map does not list serves no tier: a judgment card refuses it.
    with pytest.raises(transport_registry.TransportRefusal) as refused:
        decisions.role_assignments({**BASE, 'roles': {'limitation-census': {
            'model': 'claude-unlisted', 'reasoning_effort': 'high'}}}, roles)
    assert refused.value.missing == ['tier:limitation-census:judgment']
    # A role row on a listed judgment model (one of several) or on the runtime model serves judgment.
    judged = decisions.role_assignments({**BASE, 'tiers': {'judgment': [
        {'model': 'claude-judge', 'reasoning_effort': 'high'}, {'model': 'gpt-judge', 'reasoning_effort': 'high'}]},
        'roles': {'limitation-census': {'model': 'gpt-judge', 'reasoning_effort': 'high'},
                  'sufficiency-verifier': {'model': 'scripted-control', 'reasoning_effort': 'high'}}}, roles)
    assert {r: (row['model'], row['model_tier'], row['source']) for r, row in judged.items()} == {
        'limitation-census': ('gpt-judge', 'judgment', 'role'),
        'sufficiency-verifier': ('scripted-control', 'judgment', 'role')}
    # The tier default is the first listed model.
    default = decisions.role_assignments({**BASE, 'tiers': {'judgment': [
        {'model': 'claude-judge', 'reasoning_effort': 'high'}, {'model': 'gpt-judge', 'reasoning_effort': 'high'}]}},
        roles)
    assert {row['model'] for row in default.values()} == {'claude-judge'}


def test_a_research_run_records_judgment_models_for_every_stage_role(tmp_path):
    base = tmp_path.resolve()
    with goal_bound_stage_specs():
        rp, host, root, out = open_question(base, stages=1)
        run_graph(root, rp, out, host)
    prepared = [r for r in receipts(root, 'completed') if r['path'].endswith('/prepare:stage')]
    assert prepared
    for receipt in prepared:
        assigned = receipt['result']['assignments']
        assert assigned and all(row['model_tier'] == row['card_tier'] == 'judgment' for row in assigned.values())


@pytest.mark.parametrize('stage,level', [('screen', 'R2'), ('validate', 'R2'), ('acceptance', 'R3')])
def test_same_family_critic_is_refused_at_r2_and_above(stage, level):
    roles = next(r for r in protocol.default_protocol()['stages'] if r['id'] == stage)['roles']
    proposers = decisions.stage_proposers(stage)
    assert decisions.stage_level(stage) == level and proposers
    same = {'model': 'gpt-5', 'reasoning_effort': 'high', 'adapter': 'responses'}
    settings = {**BASE, 'tiers': JUDGES, 'roles': {r: dict(same) for r in set(roles) | set(proposers)}}
    with pytest.raises(transport_registry.TransportRefusal) as refused:
        decisions.dispatch_check(stage, decisions.role_assignments(settings, sorted(set(roles) | set(proposers))))
    assert any(m.startswith('distinct_family_from:') for m in refused.value.missing)


def test_r3_stage_checks_its_critics_against_the_earlier_stage_proposer():
    same = {'model': 'gpt-5', 'reasoning_effort': 'high', 'adapter': 'responses'}
    settings = {**BASE, 'tiers': JUDGES,
                'roles': {r: dict(same) for r in ('research-evolver', 'ablation-critic', 'skeptical-verifier')}}
    with pytest.raises(transport_registry.TransportRefusal, match='ablation-critic:research-evolver'):
        stage_graph.model_options('acceptance', settings)
    settings['roles']['research-evolver'] = {**same, 'model': 'claude-x'}
    options, assigned = stage_graph.model_options('acceptance', settings)
    assert set(assigned) == {'ablation-critic', 'skeptical-verifier'} and options['model'] == 'gpt-5'
    assert {row['family_check'] for row in assigned.values()} == {'distinct'}


def test_same_family_is_allowed_below_r2_and_unreadable_families_are_refused_at_dispatch():
    same = {'model': 'gpt-5', 'reasoning_effort': 'high', 'adapter': 'responses'}
    roles = ['limitation-census', 'sufficiency-verifier']
    checked = decisions.dispatch_check('limitation_census', decisions.role_assignments(
        {**BASE, 'tiers': JUDGES, 'roles': {r: dict(same) for r in roles}}, roles))
    assert {c['family_check'] for c in checked.values()} == {'not_required'}
    roles = ['screen-producer', 'plan-critic']
    # F8: a host-delivered (external) critic whose family RAVEL cannot read is refused at dispatch.
    with pytest.raises(transport_registry.TransportRefusal, match='plan-critic:screen-producer:unknown-family'):
        decisions.dispatch_check('screen', decisions.role_assignments({**BASE, **EXTERNAL}, roles))
    with pytest.raises(transport_registry.TransportRefusal, match='unknown-family'):
        decisions.dispatch_check('screen', decisions.role_assignments({**BASE, 'model': 'opaque-model'}, roles))


def test_external_same_family_critic_is_refused_at_dispatch_through_check_distinct_families(monkeypatch):
    """F8: the R2+ family check runs through transport_registry.check_distinct_families at dispatch,
    and a same-family critic on an external adapter is refused."""
    calls = []
    real = transport_registry.check_distinct_families

    def spy(card, observed):
        calls.append((card['id'], dict(observed)))
        return real(card, observed)
    monkeypatch.setattr(transport_registry, 'check_distinct_families', spy)
    settings = {**STAGE_SETTINGS, 'tiers': JUDGES,
                'roles': {'screen-producer': {**EXTERNAL, 'model': 'claude-x'},
                          'plan-critic': {**EXTERNAL, 'model': 'claude-y'}}}
    with pytest.raises(transport_registry.TransportRefusal, match='plan-critic:screen-producer'):
        stage_graph.assignments_for('screen', settings)
    assert ('plan-critic', {'plan-critic': 'claude-y', 'screen-producer': 'claude-x'}) in calls


def test_observed_same_family_critic_is_refused_before_stage_completion(monkeypatch):
    """F8 at receipt: a host may deliver a model other than the one assigned. The observed models of
    the stage's own roles are checked again before complete_stage, on both engines."""
    settings = {**STAGE_SETTINGS, 'tiers': JUDGES,
                'roles': {'screen-producer': {**EXTERNAL, 'model': 'claude-x'},
                          'plan-critic': {**EXTERNAL, 'model': 'gpt-5'}}}
    assigned = {r: row for r, row in decisions.role_assignments(settings, ['screen-producer', 'plan-critic']).items()}
    monkeypatch.setattr(decisions, 'observed_models', lambda graph_root: {'screen-producer': 'claude-x',
                                                                          'plan-critic': 'claude-y'})
    with pytest.raises(transport_registry.TransportRefusal, match='plan-critic:screen-producer'):
        decisions.receipt_family_check('screen', 'graph', settings)
    monkeypatch.setattr(decisions, 'observed_models', lambda graph_root: {'screen-producer': 'claude-x',
                                                                          'plan-critic': 'gpt-5'})
    assert decisions.receipt_family_check('screen', 'graph', settings)['plan-critic']['family_check'] == 'distinct'
    monkeypatch.setattr(decisions, 'observed_models', lambda graph_root: {'screen-producer': 'claude-x'})
    with pytest.raises(transport_registry.TransportRefusal, match='unobserved'):
        decisions.receipt_family_check('screen', 'graph', settings)
    assert assigned['plan-critic']['family'] == 'openai'
    import inspect
    for source in (inspect.getsource(stage_graph._complete), inspect.getsource(orch.run_protocol_stage)):
        assert source.index('receipt_family_check') < source.index('complete_stage')


def test_card_distinct_family_rows_always_apply(monkeypatch):
    from ravel.workflow import role_registry
    real = role_registry.load

    def load(role_id, **kwargs):
        card = real(role_id, **kwargs)
        if role_id == 'sufficiency-verifier':
            card['model']['distinct_family_from'] = ['limitation-census']
        return card
    monkeypatch.setattr(role_registry, 'load', load)
    same = {'model': 'claude-x', 'reasoning_effort': 'high', 'adapter': 'responses'}
    roles = ['limitation-census', 'sufficiency-verifier']
    with pytest.raises(transport_registry.TransportRefusal, match='sufficiency-verifier:limitation-census'):
        decisions.dispatch_check('limitation_census', decisions.role_assignments(
            {**BASE, 'tiers': JUDGES, 'roles': {r: dict(same) for r in roles}}, roles))


@pytest.mark.xfail(strict=True, reason='awaits per-role stage models: research_protocol.prepare_stage(role_models=...)')
def test_distinct_family_critic_prepares_its_r2_stage():
    settings = {**STAGE_SETTINGS, 'tiers': JUDGES, 'roles': {'screen-producer': {**EXTERNAL, 'model': 'claude-x'},
                                            'plan-critic': {**EXTERNAL, 'model': 'gpt-5'}}}
    options, assigned = stage_graph.model_options('screen', settings)
    assert assigned['plan-critic']['family_check'] == 'distinct'
    assert options['role_models']['plan-critic']['model'] == 'gpt-5'


def test_distinct_family_r2_stage_holds_until_stage_roles_take_their_own_models():
    from ravel.workflow import graph_nodes
    settings = {**STAGE_SETTINGS, 'tiers': JUDGES, 'roles': {'screen-producer': {**EXTERNAL, 'model': 'claude-x'},
                                            'plan-critic': {**EXTERNAL, 'model': 'gpt-5'}}}
    with pytest.raises(graph_nodes.RecoveryHold) as held:
        stage_graph.model_options('screen', settings)
    assert held.value.reason == 'awaits_prepare_stage_role_models'


# ---- registry, structure and recorded gaps ---------------------------------------------------------

def test_registered_research_graphs_build_with_their_structure(tmp_path):
    for graph_id in ('research.stage', 'research.loop'):
        ctx = graph_substrate._context(tmp_path, graph_id, {'campaign': 'c', 'request': '0' * 64})
        compiled = graph_substrate.build(graph_id, ctx)
        assert compiled.structure_sha256 == graph_registry.get(graph_id)['structure_sha256']
        assert graph_substrate.lint_graph(compiled) == []
    assert graph_substrate.closure('research.loop') == [['research.loop', 1], ['research.stage', 1]]


def test_goal_bound_stage_completion(tmp_path):
    """A protocol stage completes on a goal-bound campaign without the fixture's binding: complete_stage
    re-checks the reservation with the campaign goal binding that execute_graph inherits."""
    _, _, root, _ = open_question(tmp_path.resolve(), stages=1)
    status = protocol.methodology_status(root)
    assert 'goal_binding' in cycle._load(root)[1]['contract']
    assert status['record']['stages'][0]['status'] == 'done' and status['next_stage'] == 'ideas'
