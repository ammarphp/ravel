"""Open-question harness: synthetic sibling questions as research parents on ``research.loop``.

Each fixture under ``tests/fixtures/open_questions`` is a structure-preserving synthetic
sibling: a routed parent request, a declared quantity, two rival idea streams and a
synthetic answer. The harness runs it through the graph engine on stub transports: the
scripted host answers model nodes with fixed public records and the stage roles are
delivered as external stub receipts. No provider, model call, native run or physics
inference happens here; every number is synthetic.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / 'tests' / 'unit'
if str(UNIT) not in sys.path:
    sys.path.insert(0, str(UNIT))

from ravel.workflow import graph_environment  # noqa: E402,F401  (strict msgpack before LangGraph)
from ravel.workflow import (agent_graph, effect_ledger, graph_substrate as gs,  # noqa: E402
                            hypothesis_board as board, research_board as rb, research_cycle as cycle,
                            research_orchestrator as orch, research_protocol as protocol, review_context,
                            route_prompt, task_completion)

from test_agent_graph import external_response  # noqa: E402
from test_langgraph_research_orchestration import ScriptedResearchHost  # noqa: E402
from test_research_default_protocol import STAGES, synthetic_artifacts, write  # noqa: E402

FIXTURES = ROOT / 'tests' / 'fixtures' / 'open_questions'
QUESTIONS = tuple(sorted(p.stem for p in FIXTURES.glob('*.json')))
EXTERNAL = {'model': 'host-agent', 'reasoning_effort': 'high', 'adapter': 'external'}
STAGE_ROLES = sorted({r for row in protocol.default_protocol()['stages'] for r in row['roles']})
STREAMS = ('citation_led', 'speculative')
# The loop's own model and worker nodes (research_orchestrator._open_plan).
LOOP_NODES = {'declare_call', 'assessment_call', 'idea_call', 'decision_call', 'stage_commit'}


def loop_admits_register_fields():
    """Research-loop seam: the idea calls' public schema carries the typed register declaration that
    ``idea_adopt`` requires (``research_coordinator_decisions.REGISTER_FIELDS``). Without it no
    open question passes the ``ideas`` turn of ``research.loop`` on this base."""
    from ravel.workflow import research_coordinator_decisions as decisions
    return hasattr(decisions, 'REGISTER_FIELDS')


def role_models():
    """Stage-role models: one declared external stub model. With the research-loop fix, judgment-tier cards need the
    run's declared judgment models, so that model is also the run's judgment tier."""
    roles = {r: dict(EXTERNAL) for r in STAGE_ROLES}
    if not loop_admits_register_fields():
        return roles, None
    return roles, {'judgment': [{k: EXTERNAL[k] for k in ('model', 'reasoning_effort')}]}


# A stage at R2 or above needs a critic from a model family distinct from its proposer. On stubs the
# family of the external model is unreadable, and the research loop holds a stage whose roles need different models
# until research_protocol.prepare_stage dispatches each role on its own model (research-protocol handoff).
FAMILY_BLOCKERS = ('distinct_family_from', 'unknown-family', 'stage_awaits_prepare_stage_role_models')


def blocker(exc):
    """The named handoff a stub run waits for, or None when ``exc`` is an ordinary failure."""
    if any(marker in str(exc) for marker in FAMILY_BLOCKERS):
        return 'awaits the prepare_stage(role_models) handoff: ' + str(exc)[:600]
    return None


def question(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def stage_roles(stage_id):
    return next(row['roles'] for row in protocol.default_protocol()['stages'] if row['id'] == stage_id)


# ---- stub transports ----------------------------------------------------------------------------

def deliver(graph_root, log, models=None):
    """External stub delivery for every pending role of a stage graph; each delivery is logged and
    reports the model its role was assigned."""
    for role, row in agent_graph.status(graph_root)['nodes'].items():
        if row['status'] == 'completed':
            continue
        pending = agent_graph.prepare_external(graph_root, role)
        fields = json.loads(Path(pending['request_file']).read_text())['parameters']['output_schema']['properties']
        public = {k: fields[k]['const'] for k in ('stage', 'role_id', 'subject_sha256')}
        public.update(verdict='accept', findings=['Synthetic transport control only.'], attributed_claim_ids=[])
        model = ((models or {}).get(role) or EXTERNAL)['model']
        response = external_response(pending, Path(graph_root).parent / (role + '-response.json'), value=public,
                                     actor_id='synthetic-' + role, observed_model=model)
        agent_graph.deliver_external(graph_root, role, response)
        log.append({'graph': str(graph_root), 'stage': public['stage'], 'role': role})


def deliver_all(out, log, models=None):
    for graph_root in sorted(Path(out).glob('turns/*/effect/protocol/graph')):
        if not agent_graph.status(graph_root)['complete']:
            deliver(graph_root, log, models)


class StubHost(ScriptedResearchHost):
    """The scripted host: it answers the loop's model nodes from the fixture and presents every
    artifact of a role packet. It never chooses a role or a stage; the loop's code does."""

    def __init__(self, callback):
        super().__init__(callback)
        self.items = []
        self.errors = []

    def execute(self, item, request, control):
        self._item = item
        self.items.append({'id': item['id'], 'kind': item['kind'], 'role': item.get('role')})
        try:
            return super().execute(item, request, control)
        except Exception as exc:
            self.errors.append({'id': item['id'], 'role': item.get('role'), 'error': repr(exc)[:1500]})
            raise

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
def inert_decision_provider():
    """The gate-wiring decision provider reads ``inputs/task_contract.json`` at the campaign root, which the
    open-research campaign does not write on this base (the research-loop fix wires the gate calls). For these
    transport fixtures it is an inert seam, as in the research-loop fixtures; gate refusal is tested in
    test_gate_wiring and test_decision_gate."""
    real = protocol.decision_errors
    protocol.decision_errors = lambda *a, **k: []
    try:
        yield
    finally:
        protocol.decision_errors = real


@contextmanager
def goal_bound_stage_specs():
    """As the research-loop parity fixtures: complete_stage re-checks its reservation with the campaign's
    inherited goal binding (research-orchestration handoff)."""
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


# ---- a synthetic sibling as a research parent -----------------------------------------------------

def parent(base, q):
    """Route the sibling's prompt by code and add its two deliverables."""
    prompt = q['prompt']
    contract = route_prompt.route(prompt)
    contract.setdefault('task_requirements', task_completion.initial_requirements(prompt))
    req = contract['task_requirements']
    for identity, meaning in [('result', 'The declared quantity with its verdict.'),
                              ('note', 'Internal note with negative evidence.')]:
        req['obligations'].append({'id': identity, 'kind': 'deliverable', 'statement': meaning,
                                   'criteria': {'deliverable': meaning},
                                   'evidence': [{'start': 0, 'end': len(prompt), 'text': prompt}]})
    req['assignments'] = [{'id': 'original-task', 'purpose': 'Preserve the complete original research request.',
                           'coverage': [{'obligation_id': r['id'], 'criteria': deepcopy(r['criteria'])}
                                        for r in req['obligations']]}]
    from test_langgraph_research_orchestration import write as write_pin
    return contract, write_pin(base / 'parent/inputs/task_contract.json', contract)


def context(base, q):
    from test_langgraph_research_orchestration import write as write_pin
    source = write_pin(base / 'method.py', q['method'])
    quantity = q['quantity']
    return source, {
        'schema_version': 1, 'task_id': q['id'], 'task': q['prompt'], 'source_capsules': [],
        'api_documents': [{'id': 'method', 'pin': {k: source[k] for k in ('path', 'sha256')}, 'language': 'python',
                           'role': 'api', 'version': 'Synthetic supplied method.', 'dependencies': []}],
        'queries': [{'id': 'method-law', 'symbol': q['method'].split('(')[0].split()[-1], 'mode': 'definition',
                     'documents': ['method'], 'required': True}],
        'requested_quantities': [{'id': quantity['id'], 'artifact': 'measurement', 'pointer': '/quantities/value',
                                  'check': {'kind': 'exact', 'value': q['answer']['value']},
                                  'meaning': quantity['meaning']}],
        'compatibility_groups': [{'id': 'current-control', 'artifacts': ['measurement'], 'carryover': False,
                                  'basis': 'Every experiment preserves the complete supplied records.'}],
        'max_source_bytes': 128000, 'max_context_bytes': 16000, 'max_steps': 6}


def register_declaration(q, stream):
    """The typed register declaration of one rival: operator, signature, kill condition and a
    typed reopening predicate (P09)."""
    return {'operator': 'limitation_fix',
            'identity_signature': {'observable': q['quantity']['id'], 'scope': 'synthetic records',
                                   'prediction': stream + '-law'},
            'kill_condition': {'comparison': 'differs', 'observable': q['quantity']['id']},
            'reopening_trigger': {'kind': 'changed_input', 'field': 'revision', 'op': 'gt', 'value': 0},
            'what_is_new': None}


def hypothesis(q, stream, source):
    """One rival per idea stream, with its register declaration."""
    return {'id': stream + '-law', 'statement': q['hypotheses'][stream], 'stream': stream, 'premise_ids': [],
            'source_basis': [source], 'parents': [], **register_declaration(q, stream)}


def question_artifacts(root, q):
    """The default synthetic stage artifacts, carrying this question's rivals and quantity."""
    a = synthetic_artifacts(root)
    ideas = a['ideas']
    for row, stream in zip(ideas['ideas'], STREAMS):
        row['hypothesis'] = q['hypotheses'][stream]
        row['prediction'] = 'The ' + q['quantity']['id'] + ' contrast changes on held-out cells.'
    for name in ('a', 'b'):
        rows = [r for r in ideas['ideas'] if r['stream'] == name]
        ideas['dispatch_receipts'][name] = write(root, 'dispatch-' + name + '.json', {
            'kind': 'research-idea-dispatch', 'stream': name, 'ideas_sha256': protocol.ce.digest(rows),
            'committed_sequence': 1, 'execution_observation': 'host_attested_external'})
    # The validate record keeps the prospectively registered stop rule, so the stage boundary that
    # refuses it on stubs is the selection journal (P16), not a changed bound.
    a['validate']['stop'] = {**STOP, 'reason': 'successes'}
    column = a['baseline']['three_columns'][0]
    cell = {**column['ours'], 'value': q['answer']['value'], 'unit': q['quantity']['unit']}
    a['baseline']['three_columns'] = [{**column, 'quantity': q['quantity']['id'], 'ours': cell,
                                       'reproduced': dict(cell), 'published': dict(cell)}]
    return a


ANSWER_POINTER = '/three_columns/0/ours/value'


class Run:
    """One sibling run: its paths, host, delivery log and outcome."""

    def __init__(self, base, q):
        self.base, self.q = base, q
        self.root = base / 'campaign'
        self.out = self.root / 'coordinator'
        self.deliveries = []
        self.outcome = None
        self.artifacts = {}
        self.contract = None


# The decider's protocol-stage turns on stubs: the stages a stub transport can complete, then an
# unobserved ``validate`` that the selection boundary (P16) must refuse as an observation.
LOOP_TURNS = ('ideas', 'baseline', 'screen', 'validate')


def prepare(base, q, *, turns=LOOP_TURNS):
    """Route, declare and assess the question, run both idea streams, then the decider takes the
    ``turns`` protocol stages in order and reports progress. Returns the prepared run."""
    run = Run(base, q)
    contract, cp = parent(base, q)
    run.contract = contract
    source, declared = context(base, q)
    campaign = {'id': 'synthetic-' + q['id'], 'budget': {'calls': 64, 'output_tokens': 600000,
                'wall_seconds': 86400, 'native_attempts': 2}, 'max_experiments': 4, 'exploration_every': 2,
                'required_experiments': [], 'premises': []}
    runtime = {'model': 'scripted-control', 'reasoning_effort': 'high', 'adapter': 'model', 'max_output_tokens': 2048,
               'max_wall_seconds': 900}
    run.models, tiers = role_models()
    runtime['roles'] = run.models
    if tiers is not None:
        runtime['tiers'] = tiers
    mapping = [{'obligation_id': r['id'], 'original': deepcopy(r),
                'quantities': [q['quantity']['id']] if r['id'] == 'original-request' else [],
                'method': 'Synthetic protocol traversal; no physics inference.', 'sources': [source],
                'unresolved': '' if r['id'] == 'original-request' else r['statement']}
               for r in contract['task_requirements']['obligations']]
    rp = orch.prepare_open(cp, base / 'request', base_dir=base, campaign=campaign, runtime=runtime,
                           evidence=[{'pin': source, 'purpose': 'model_context'}], candidate_modes=['quantities'],
                           review={'arguments': {}, 'allow_control': True}, max_decisions=len(turns) + 1)
    remaining = tuple(turns)

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
            return {'hypotheses': [hypothesis(q, core['stream'], source)]}
        turn = len(core['prior_operation_effects'])
        action, arguments = (('protocol-stage', {'artifact': run.artifacts[remaining[turn]]}) if turn < len(remaining)
                             else ('progress', {'reason': 'Synthetic traversal complete; no acceptance.'}))
        return {'kind': 'research-action', 'action': action, 'reason': 'Synthetic control choice.',
                'arguments_json': json.dumps(arguments)}
    run.host = StubHost(callback)
    run.rp = rp
    orch._open_plan(run.root, rp, run.out, host=run.host)
    synthetic = question_artifacts(run.root, q)
    for name in STAGES:
        run.artifacts[name] = write(run.root, 'artifacts/' + name + '.json', synthetic[name])
    run.settings = {k: v for k, v in {**runtime, **EXTERNAL}.items() if k != 'roles'}
    run_stage(run, 'limitation_census', base / 'setup-census')
    preregister(run)
    return run


RULE = {'direction': 'maximize', 'metric': 'response', 'k': 1, 'alpha': .05}
STOP = {'successes': 2, 'max_rounds': 1, 'budget': 30, 'coverage_floor': 1, 'families': ['f0']}


def preregister(run):
    """The prospective record: selection rule, stop rule and a withheld confirmation cell."""
    from test_research_cycle import write as pin
    hidden = pin(run.base / 'hidden-population.json', {'ids': ['held-out'], 'synthetic': True})
    run.hidden = hidden
    declaration = {
        'schema_version': 1, 'kind': 'research-preregistration', 'approximations': [],
        'selection_rule': RULE, 'stop_rule': STOP, 'withheld_cells': [{'id': 'confirm', 'population': hidden}],
        'expected_effect': {'statement': 'A synthetic unit contrast; no physical inference.'},
        'evaluator_not_applicable': {k: 'Supplied dimensionless arithmetic only.' for k in
                                     ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}}
    if 'precision_target' in run.q:
        # Searches and method studies are sized from a declared precision target, never a smoke size.
        declaration['precision_target'] = run.q['precision_target']
        declaration['sizing'] = protocol.precision_size(declaration)
    record = pin(run.root / 'preregistration.json', declaration)
    protocol.preregister(run.root, record, {}, evaluation_harness=True)


def run_stage(run, name, out):
    """The legacy stage runner for one bound stage, with stub role delivery."""
    artifact = run.artifacts[name]
    orch.run_protocol_stage(run.root, artifact, out, host=run.host, settings=run.settings)
    deliver(out / 'graph', run.deliveries, run.models)
    result = orch.run_protocol_stage(run.root, artifact, out, host=run.host, settings=run.settings)
    assert result['complete'], result
    return result


def answer(root):
    return {'response': {'path': str(root / 'head.json'), 'sha256': cycle._pin(root / 'head.json')['sha256']}}


def _engine(function):
    """Research-loop seam: a graph engine without a current parity record runs only when labelled
    experimental. The open-question study asks whether the loop dispatches by code, not whether parity is recorded,
    so it passes the flag where the signature has it and keeps the label on the run."""
    import inspect
    return {'experimental': True} if 'experimental' in inspect.signature(function).parameters else {}


def drive(run, *, max_rounds=40):
    """Run ``research.loop`` to its end, delivering stage roles at each external-delivery turn."""
    result = orch.run_graph(run.root, run.rp, run.out, host=run.host, **_engine(orch.run_graph))
    run.trace = []
    for _ in range(max_rounds):
        run.trace.append({'phase': result.get('phase'), 'failures': [
            {k: f.get(k) for k in ('node', 'error_type', 'message')} for f in result.get('failures') or []][-1:]})
        if result.get('phase') != 'ordinary_effect_required':
            run.outcome = result
            run.engine = 'graph'
            return result
        deliver_all(run.out, run.deliveries, run.models)
        result = orch.respond_graph(run.root, run.rp, run.out,
                                    {i['id']: answer(run.root) for i in result['checkpoint']['interrupts']},
                                    host=run.host, **_engine(orch.respond_graph))
    raise AssertionError('research.loop did not finish: ' + json.dumps(
        {'trace': run.trace[-3:], 'host_errors': run.host.errors[-3:]}, default=str)[:3000])


def stage_records(root):
    return protocol.methodology_status(root)['record']['stages']


def committed(root):
    """The artifact pins the run itself committed through its stage records."""
    return {(row['artifact']['path'], row['artifact']['sha256']) for row in stage_records(root)
            if row['status'] == 'done' and row.get('artifact')}


def run_answer(run):
    """The run's answer: the stub verdict and the quantity read from the committed baseline artifact."""
    baseline = next(row for row in stage_records(run.root) if row['id'] == 'baseline')
    pin = baseline['artifact']
    value = json.loads(Path(pin['path']).read_text())
    for part in ANSWER_POINTER.split('/')[1:]:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return {'verdict': run.q['answer']['verdict'],
            'quantity': {'id': run.q['quantity']['id'], 'value': value, 'unit': run.q['quantity']['unit'],
                         'evidence': {'path': pin['path'], 'sha256': pin['sha256'], 'pointer': ANSWER_POINTER}}}


# ---- the board season (P01, P02) ------------------------------------------------------------------

PRODUCER = 'or4-synthetic-producer'
SEASON = {'season': 'season-1', 'producer': PRODUCER}
SEASON_ROOT = 'research/board/season-1'


def board_season(run):
    """A sealed season in the run's scope: each idea stream commits its rival, then all reveal.
    Stub producers carry no attested distinct session, so the season is labelled unsealed."""
    q = run.q

    def produce(packet):
        actor = packet['actor']['actor_id']
        rival = {'id': 'H1', 'statement': q['hypotheses'][actor],
                 'predictions': {k: (actor if k == 'direction' else None) for k in packet['prediction_keys']},
                 'artifact_refs': [], 'contradicts': [], 'register': register_declaration(q, actor)}
        return {'submission': {'schema_version': 1, 'actor_id': actor, 'session_id': 'session-' + actor,
                               'nonce': 'initial-nonce-for-' + actor, 'hypotheses': [rival]}, 'receipt': None}
    rb.register_producer(PRODUCER, produce, replace=True)
    charter = {'board_id': 'synthetic-' + q['id'], 'season': SEASON['season'], 'mode': 'production',
               'participants': [{'actor_id': s, 'model_id': 'declared-model-' + s, 'session_id': 'session-' + s,
                                 'fresh_generation': True, 'broker': {'node_id': 'proposer-' + s, 'attempt': 1}}
                                for s in STREAMS],
               'prediction_keys': ['direction', 'magnitude'], 'limits': dict(board.DEFAULT_LIMITS),
               'artifact_pins': [], 'max_wall_seconds': 600, 'opened_utc': None}
    try:
        observation = gs.run(run.root, rb.SEASON_GRAPH, SEASON, input={'charter': charter}, workers=2)
    finally:
        rb.PRODUCERS.pop(PRODUCER, None)
    assert observation['terminal'] is None and observation['next'] == [], observation
    return rb.journal_root(run.root, SEASON['season'])


# ---- past validate: an observed selection and confirmation (P16) ----------------------------------

def _attempt(rundir, result):
    from test_research_cycle import write as pin
    pin(rundir / 'attempt.json', {'status': 'succeeded', 'wall_seconds': 1})
    pin(rundir / 'outputs/attempt-1/result.json', result)


def observe_selection(run, monkeypatch):
    """Fixture-authority observations on the campaign journal: one adaptive trial is observed and
    selected, then one confirmation on the withheld cell is dispatched and observed. The science
    executor is a stub (its packet and execution record are fixed); nothing executes."""
    from copy import deepcopy
    from test_research_cycle import write as pin
    from ravel.workflow import science
    monkeypatch.setattr(science, 'verify_plan', lambda *a, **k: None)
    monkeypatch.setattr(science, 'packet', lambda *a, **k: {'execution': {'status': 'succeeded'}, 'errors': []})
    monkeypatch.setattr(science.execution, 'load_execution', lambda *a, **k: {'stages': {'science': {
        'status': 'succeeded', 'attempt_id': 'attempt-1', 'attempt_record': 'attempt.json'}}})
    root = run.root
    _, state = cycle._load(root)
    target = sorted(cycle.replay_register(state['events'], base_dir=run.base))[0]
    select = run.base / 'select-run'
    _attempt(select, {'metric': 1, 'p': .5, 'decision': 'worse'})
    experiment = {'id': 'e0', 'rundir': str(select), 'observation': None, 'premise_bindings': {},
                  'study': pin(run.base / 'study.json', {'synthetic': True}), 'input_pins': [], 'plan': None,
                  'observable': {'pointer': '/metric', 'outcomes': {'positive': 1, 'zero': 0}},
                  'predictions': {target: 'positive'}, 'context_outputs': {}, 'question': 'measure',
                  'change': 'measure', 'evaluation': {
                      'candidate': 'c0', 'family': 'f0', 'round': 1, 'purpose': 'full', 'cells': ['select'],
                      'seeds': [11], 'generation': 'g0', 'value_pointer': '/metric', 'p_value_pointer': '/p',
                      'decision_pointer': '/decision'}}
    state['experiments'].append(experiment)
    cycle._commit(root, state, 'fixture_prepared')
    state = cycle.observe(root, 'e0')
    request = {'rule': RULE, 'regime': protocol.methodology_status(root)['record']['regime'], 'trials': [
        {'id': 'e0', 'candidate': 'c0', 'result': state['experiments'][-1]['observation']['result']}]}
    receipt = protocol.commit_selection(root, pin(run.base / 'select-request.json', request))
    _, state = cycle._load(root)
    confirm = deepcopy(experiment)
    rundir = run.base / 'confirm-run'
    confirm.update(id='confirm', observation=None, rundir=str(rundir), input_pins=[run.hidden])
    confirm['evaluation'].update(purpose='confirm', cells=['confirm'], seeds=[31], generation='g1',
                                 population_pins=[run.hidden])
    _attempt(rundir, {'metric': 1, 'p': .001, 'decision': 'better'})
    state['experiments'].append(confirm)
    state = cycle._commit(root, state, 'fixture_confirmation_prepared')
    protocol.record_confirmation_dispatch(root, state, 'confirm')
    cycle.observe(root, 'confirm')
    return receipt, protocol.produce_selection_report(root)


def complete_past_validate(run, monkeypatch):
    """validate .. integrity through the stage runner on the observed journal. The acceptance stage
    refuses while the P04/P06/P17 producers (of the review graph) are absent; that refusal is recorded on the run
    and the producers are then treated as present, as in test_research_launch."""
    from test_research_launch import rebind_rdj
    receipt, report = observe_selection(run, monkeypatch)
    root = run.root
    selected = write(root, 'committed-selection.json', receipt)
    validate = protocol.validation_trace(root)
    synthetic = question_artifacts(root, run.q)
    validate.update(withheld_cells=['confirm'], selection={
        **synthetic['validate']['selection'], 'receipt': selected,
        'confirmation_pins': [r['result'] for r in protocol._method_json(report, root)['selected_result_on_confirm']]})
    claim = synthetic['acceptance']['claims'][0]
    claim.update(N=receipt['N'], selection_receipt=selected, selection_report=report)
    for name, row in (('selection', validate['selection']), ('claim', claim)):
        rebind_rdj(root, name, row)
    run.selection = {'receipt': selected, 'report': report}
    run.artifacts['validate'] = write(root, 'artifacts/validate-observed.json', validate)
    run.artifacts['acceptance'] = write(root, 'artifacts/acceptance-observed.json', synthetic['acceptance'])
    for name in STAGES[STAGES.index('validate'):]:
        if name == 'acceptance':
            try:
                run_stage(run, name, run.base / 'stages' / (name + '-producers'))
            except ValueError as exc:
                run.producer_refusal = str(exc)
            present = protocol.protocol_producers_present()
            monkeypatch.setattr(protocol, 'protocol_producers_present',
                                lambda **k: {**present, 'missing': [], 'valid': True})
        run_stage(run, name, run.base / 'stages' / name)
    return run


# ---- one complete sibling run ---------------------------------------------------------------------

def build(base, name, monkeypatch):
    """One synthetic sibling as a research parent, end to end on stubs:

    1. route and prepare the campaign (limitation census, preregistration);
    2. a sealed board season of the two idea streams;
    3. ``ideas``, ``baseline`` and ``screen`` as the decider's protocol-stage turns on
       ``research.loop``, then an unobserved ``validate`` turn refused as an observation; where the
       loop cannot yet adopt typed hypotheses (research-loop fix), the stage runner takes those three stages and
       ``run.engine`` says so; the revealed season is then imported into the campaign register;
    4. ``validate`` .. ``integrity`` on an observed selection and confirmation.

    A stage that a stub cannot complete because its R2+ critic needs a distinct, readable model
    family leaves ``run.blocked`` naming that handoff instead of failing the build.
    """
    from open_question_grader import declaration
    from test_research_cycle import write as pin
    q = question(name)
    with inert_decision_provider(), goal_bound_stage_specs():
        run = prepare(base, q)
        run.grading = pin(base / 'grading-declaration.json', declaration(q))
        run.season = board_season(run)
        run.engine, run.blocked = 'stage-runner', None
        if loop_admits_register_fields():
            drive(run)
            if run.outcome.get('phase') == 'hold':
                status = json.dumps(run.outcome.get('status'), sort_keys=True)
                assert any(marker in status for marker in FAMILY_BLOCKERS), status
                run.blocked = 'awaits the prepare_stage(role_models) handoff: research.loop holds ' + status
                return run
        try:
            # Any turn the loop could not commit runs on the stage runner, in the bound order.
            done = {r['id'] for r in stage_records(run.root) if r['status'] == 'done'}
            for stage in LOOP_TURNS[:-1]:
                if stage not in done:
                    run_stage(run, stage, base / 'stages' / stage)
            # The revealed season joins the campaign register after the loop's own declaration turn.
            cycle.import_board(run.root, run.season, streams={s: s for s in STREAMS})
            complete_past_validate(run, monkeypatch)
        except ValueError as exc:
            run.blocked = blocker(exc)
            if run.blocked is None:
                raise
    return run
