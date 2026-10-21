"""Inert HTTP replies through the actual provider parser and Graph custody."""
import json
import hashlib
from copy import deepcopy
from contextvars import Context
from pathlib import Path
from threading import RLock, Event, Thread

import pytest

from ravel.workflow import agent_host, provider_transport
from test_scientific_judgment import FakeHost
from test_physics_review import run  # noqa: F401

_HTTP_PATCH = RLock()


@pytest.mark.parametrize('role', ['edge_reviewer', 'critic', 'verifier'])
def test_rdj_public_schemas_admit_the_strict_provider_dialect(role):
    from ravel.validation.core import validate_schema
    from ravel.workflow.rdj_loop import OUTPUT_SCHEMAS
    validate_schema(OUTPUT_SCHEMAS[role])


@pytest.mark.parametrize('public_request', [None,
    {'kind': 'evidence', 'description': 'Read the current measurement.'},
    {'kind': 'experiment', 'description': 'Compare the two bounded cases.', 'max_broker_calls': 64}])
@pytest.mark.parametrize('alternative', [False, True])
@pytest.mark.parametrize('withdrawn', [False, True])
def test_rdj_public_optional_shapes_preserve_semantic_records(public_request, alternative, withdrawn):
    from ravel.validation.core import validate_value
    from ravel.workflow import decision_case as dc, rdj_loop
    actor = {'actor_id': 'schema-control', 'session_receipt': None, 'attestation': 'self_attested'}
    finding = {'id': 'F1', 'code': 'missing_evidence', 'targets': ['N1'],
        'materiality': 'B', 'evidence_class': 'opinion', 'evidence_locators': [], 'request': public_request}
    if alternative:
        finding.update(code='alternative_not_considered', alternative='Compare the fixed baseline.')
    public = {'findings': [finding]}
    if withdrawn:
        public['withdrawn'] = ['F0']
    assert validate_value(public, rdj_loop.OUTPUT_SCHEMAS['critic']) == public
    dc.critique({'reviewer': actor, 'findings': [finding]})
    edge = {'edge_id': 'E1', 'entailment': 'holds', 'relevance': 'relevant',
        'grounding': 'anchored', 'code': 'no_issue', 'reason': 'The pinned evidence supports this hop.',
        'request': public_request}
    validate_value({'reviews': [edge]}, rdj_loop.OUTPUT_SCHEMAS['edge_reviewer'])
    dc.edge_review({**{key: value for key, value in edge.items() if key != 'edge_id'},
                    'reviewer': actor, 'edge_sha256': 'a' * 64})
    validate_value({'per_finding': [{'finding_id': 'F1', 'resolved': 'no', 'reason': 'Evidence is pending.'}],
                    'outcome': 'gather_evidence'}, rdj_loop.OUTPUT_SCHEMAS['verifier'])


@pytest.mark.parametrize('change', ['extra_root', 'extra_finding', 'missing_request',
    'unknown_code', 'unrelated_alternative', 'missing_alternative', 'bad_request_kind',
    'extra_request', 'negative_budget', 'bool_budget', 'over_budget', 'long_description'])
def test_rdj_public_schemas_refuse_unclosed_or_invalid_records(change):
    from ravel.validation.core import MechanicalValidationError, validate_value
    from ravel.workflow.rdj_loop import OUTPUT_SCHEMAS
    finding = {'id': 'F1', 'code': 'missing_evidence', 'targets': ['N1'],
        'materiality': 'B', 'evidence_class': 'opinion', 'evidence_locators': [], 'request': None}
    public = {'findings': [finding]}
    if change == 'extra_root':
        public['plan'] = 'Replace the experiment.'
    elif change == 'extra_finding':
        finding['rewrite'] = 'Replace the experiment.'
    elif change == 'missing_request':
        del finding['request']
    elif change == 'unknown_code':
        finding['code'] = 'approve_anyway'
    elif change == 'unrelated_alternative':
        finding['alternative'] = 'Compare the baseline.'
    elif change == 'missing_alternative':
        finding['code'] = 'alternative_not_considered'
    else:
        finding['request'] = request = {'kind': 'evidence', 'description': 'Read the measurement.'}
        if change == 'bad_request_kind':
            request['kind'] = 'rewrite'
        elif change == 'extra_request':
            request['override'] = True
        elif change == 'long_description':
            request['description'] = 'x' * 301
        else:
            request['max_broker_calls'] = {'negative_budget': -1, 'bool_budget': True, 'over_budget': 65}[change]
    with pytest.raises(MechanicalValidationError):
        validate_value(public, OUTPUT_SCHEMAS['critic'])


class InertDecisionDispatcher:
    """Original RDJ Graph dispatcher with only the provider HTTP replies inert."""
    MODELS = {'edge_reviewer': 'gpt-5', 'critic': 'claude-x', 'verifier': 'gpt-5'}
    OBSERVED_MODELS = {}

    def __init__(self):
        self.calls = []

    def dispatch(self, rundir, request):
        from ravel.workflow import rdj_loop, rdj_custody
        from rdj_fixtures import reviewer, critic, verifier
        responders = {'edge_reviewer': reviewer(), 'critic': critic(), 'verifier': verifier()}
        role = request['role']
        expected = deepcopy(request['payload'])
        def respond(node, context):
            assert node['role'] == request['agent_role']
            if role == 'edge_reviewer':
                assert node['packet'] is None and 'review_packet' not in context
                artifacts = context['input_artifacts']
            else:
                assert node['inputs'] == [] and node['packet'] is not None
                assert not context.get('input_artifacts')
                artifacts = context['review_packet']['artifacts']
            payloads = [row for row in artifacts if row['id'] == 'rdj-payload']
            assert len(payloads) == 1
            shown = payloads[0]
            assert shown.get('sha256', shown.get('source_sha256')) == request['payload_sha256']
            payload = json.loads(shown['content'])
            assert payload == expected
            assert hashlib.sha256(shown['content'].encode()).hexdigest() == request['payload_sha256']
            # These helpers provide only the public response. Their synthetic
            # actor, family, attestation and worker receipts are never used.
            return responders[role](payload)['output']
        host = InertReviewHost(respond, max_request_bytes=8_000_000,
            observed_model=self.OBSERVED_MODELS.get(role))
        rdj_custody.register_host(rundir, host.identity)  # Original operator API.
        dispatcher = rdj_loop.AgentHostDispatcher(host, model=self.MODELS[role],
            reasoning_effort='high', max_output_tokens=1024, max_wall_seconds=900)
        reference = dispatcher.dispatch(rundir, request)
        self.calls.append({'request': deepcopy(request), 'reference': deepcopy(reference)})
        return reference


class InertReviewHost(agent_host.AgentHost):
    """Replace only HTTP I/O; request presentation and receipt classification stay real."""
    def __init__(self, callback=None, *, max_request_bytes=2_000_000, observed_model=None):
        super().__init__(adapter='chat_completions',
            endpoint='https://inert.example/v1/chat/completions', api_key='FICTIONAL',
            max_request_bytes=max_request_bytes,
            capabilities={'output_mode': 'tool_call', 'token_limit_field': 'max_tokens',
                'reasoning_efforts': ['high'], 'max_context_bytes': 16_000_000,
                'max_output_tokens': 8192})
        self.callback = callback
        self.observed_model = observed_model
        self.actual_contexts = []

    def execute(self, node, request, control):
        return self._execute(node, request, control)

    def _execute(self, node, request, control):
        if node['kind'] == 'tool':
            return super().execute(node, request, control)
        class ValueOnly:
            def call(self, label, kind, body, function, output_tokens=0):
                return function()
        if self.callback is None:
            value = FakeHost().execute(node, request, ValueOnly())['value']
        else:
            context = self.prepare_model_context(node, request)['context']
            self.actual_contexts.append(context)
            # A remote responder cannot inherit the caller's graph callbacks or
            # resumable-task context. Keep that boundary for the inert service,
            # including any separately prepared outside decision it returns.
            value = Context().run(self.callback, node, context)
        if 'anyOf' in node['parameters'].get('output_schema', {}):
            value = {'public_record': value}
        document = {'id': 'inert-'+request['request_id'],
            'model': self.observed_model if self.observed_model is not None else node['parameters']['model'],
            'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                'content': None, 'tool_calls': [{'id': 'inert-return', 'type': 'function',
                    'function': {'name': provider_transport.FUNCTION, 'arguments': json.dumps(value)}}]}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 16, 'total_tokens': 17}}
        class Response:
            status = 200
            def read(self, bound): return json.dumps(document).encode()[:bound]
            def close(self): pass
        class Connection:
            def __init__(self, hostname, port, timeout): self.sock = None
            def connect(self): pass
            def request(self, method, path, body, headers):
                assert method == 'POST' and json.loads(body)['model'] == node['parameters']['model']
            def getresponse(self): return Response()
            def close(self): pass
        # Only the actual provider call needs the process-global HTTP patch.
        # A responder may request another real Graph on a separate worker, so
        # neither context construction nor its callback may hold this lock.
        with _HTTP_PATCH:
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(agent_host.http.client, 'HTTPSConnection', Connection)
                return super().execute(node, request, control)


def test_inert_reply_uses_original_provider_parser_and_receipt_classification(run, tmp_path):
    from test_physics_review import opened
    from test_scientific_judgment import prepare
    from ravel.workflow import scientific_judgment, agent_graph
    root = run[0]
    opened(run)
    binding = prepare(root, tmp_path/'review', 'critic')
    result = scientific_judgment.execute_role(binding, InertReviewHost())
    assert result['complete'], json.dumps(result['nodes'], sort_keys=True)
    receipt = agent_graph.role_receipt(binding['graph_root'], binding['node_id'],
        expected_subject_sha256=binding['subject_sha256'], require_exact_subject=True)
    assert receipt['execution_observation'] == 'remote_transport_observed'
    assert receipt['context_transport_separated']
    assert receipt['attestation'] == 'transport_attested'
    assert receipt['transport']['observed_model'] == 'control'


def test_parallel_inert_replies_keep_their_exact_role_requests(run, tmp_path):
    from test_physics_review import opened
    from test_scientific_judgment import prepare
    from ravel.workflow import agent_graph
    root = run[0]
    opened(run)
    binding = prepare(root, tmp_path/'source', 'critic')
    specification = json.loads((Path(binding['graph_root'])/agent_graph.SPEC).read_text())
    first = specification['nodes'][0]
    second = deepcopy(first)
    second['id'] = 'independent-critic'
    second['parameters']['model'] = 'second-control'
    specification['nodes'].append(second)
    specification['budget'].update(max_nodes=2, max_calls=2, max_output_tokens=2048)
    graph_root = tmp_path/'parallel'
    agent_graph.create(graph_root, specification)
    result = agent_graph.execute(graph_root, InertReviewHost(), workers=2)
    assert all(row['status'] == 'completed' for row in result['nodes'].values()), result['nodes']
    receipts = [agent_graph.role_receipt(graph_root, node['id'],
        expected_subject_sha256=binding['subject_sha256'], require_exact_subject=True)
        for node in specification['nodes']]
    assert len({receipt['request_id'] for receipt in receipts}) == 2
    assert [receipt['transport']['observed_model'] for receipt in receipts] == ['control', 'second-control']


def test_callback_can_run_a_genuine_nested_graph_without_holding_http_patch(run, tmp_path):
    from test_physics_review import opened
    from test_scientific_judgment import prepare
    from ravel.workflow import agent_graph
    root = run[0]
    opened(run)
    binding = prepare(root, tmp_path/'source', 'critic')
    specification = json.loads((Path(binding['graph_root'])/agent_graph.SPEC).read_text())
    outer_root, inner_root = tmp_path/'outer', tmp_path/'inner'
    agent_graph.create(outer_root, specification)
    receipts = []
    def nested(node, context):
        acquired = Event()
        def acquire_independently():
            with _HTTP_PATCH:
                acquired.set()
        probe = Thread(target=acquire_independently, daemon=True)
        probe.start()
        # Fail promptly under the old implementation, before attempting a
        # nested Graph that would otherwise deadlock indefinitely.
        assert acquired.wait(2), 'responder callback holds the global HTTP patch lock'
        probe.join(2)
        agent_graph.create(inner_root, specification)
        result = agent_graph.execute(inner_root, InertReviewHost(), workers=1)
        assert result['nodes']['critic']['status'] == 'completed', result['nodes']
        receipt = agent_graph.role_receipt(inner_root, 'critic',
            expected_subject_sha256=binding['subject_sha256'], require_exact_subject=True)
        receipts.append(receipt)
        return receipt['public_value']
    result = agent_graph.execute(outer_root, InertReviewHost(nested), workers=1)
    assert result['nodes']['critic']['status'] == 'completed', result['nodes']
    receipts.append(agent_graph.role_receipt(outer_root, 'critic',
        expected_subject_sha256=binding['subject_sha256'], require_exact_subject=True))
    assert len({receipt['request_id'] for receipt in receipts}) == 2
    assert all(receipt['execution_observation'] == 'remote_transport_observed' for receipt in receipts)


def test_r2_authorization_uses_real_rdj_graph_payloads_and_observed_families(tmp_path):
    from ravel.workflow import rdj_loop, rdj_custody, agent_graph, transport_registry
    from ravel.workflow import research_protocol as protocol
    from test_research_full_cycle_authority import campaign, authorize
    from test_research_cycle import write
    root = campaign(tmp_path)
    proposal = write(root/'inert-decision.json', {'proposal': 'Bounded fictional transport control.'})
    pin = authorize(root, protocol.stage_action('limitation_census', proposal), level='R2')
    receipt = json.loads(Path(pin['path']).read_text())
    assert receipt['outcome'] == 'authorize'
    assert receipt['attestation_summary']['critic'] == 'transport_attested'
    assert receipt['attestation_summary']['verifier'] == 'transport_attested'
    case_id = Path(receipt['case']['path']).stem
    _, state, _ = rdj_loop._load(root, case_id)
    calls = [call['request'] for call in state['calls'] if call['status'] == 'completed']
    assert {call['role'] for call in calls} == {'edge_reviewer', 'critic', 'verifier'}
    assert len({call['graph_root'] for call in calls}) == len(calls)
    families = {}
    for call in calls:
        graph_root = root/call['graph_root']
        model = agent_graph.role_receipt(graph_root, 'rdj',
            expected_subject_sha256=call['payload_sha256'], require_exact_subject=True,
            allowed_roles={call['agent_role']})
        assert model['execution_observation'] == 'remote_transport_observed'
        assert model['attestation'] == 'transport_attested'
        assert model['context_transport_separated'] is (call['role'] in {'critic', 'verifier'})
        assert model['transport']['observed_model'] == InertDecisionDispatcher.MODELS[call['role']]
        assert rdj_custody.host_registered(root, model['host_sha256'])
        assert rdj_custody.graph_receipt_registered(root, call['graph_root'], model['receipt_sha256'], model['host_sha256'])
        families[call['role']] = transport_registry.model_family(model['transport']['observed_model'])
        completed = next(row for row in state['calls'] if row['request'] == call)
        assert completed['family'] == families[call['role']]
        n = json.loads((graph_root/agent_graph.SPEC).read_text())['nodes'][0]
        if call['role'] == 'edge_reviewer':
            payload_path = Path(n['inputs'][0]['path'])
            assert n['packet'] is None
        else:
            assert n['inputs'] == []
            manifest = json.loads((Path(n['packet']['path'])/'manifest.json').read_text())
            assert manifest['artifacts'][0]['sha256'] == call['payload_sha256']
            payload_path = Path(n['packet']['path'])/manifest['artifacts'][0]['path']
        assert json.loads(payload_path.read_text()) == call['payload']
    assert families['critic'] and families['verifier'] and families['critic'] != families['verifier']


@pytest.mark.parametrize('observation', ['distinct', 'same_family', 'unknown_family'])
def test_r3_authority_labels_actual_families_with_separate_role_sessions(tmp_path, monkeypatch, observation):
    from ravel.workflow import rdj_loop, rdj_anchor, agent_graph, science, research_cycle as cycle
    from ravel.workflow import research_protocol as protocol, transport_registry, research_evaluation
    from method_decision_fixture import admit_method
    from test_research_cycle import contract, hypotheses, experiment, write, actual_context_graph
    from test_research_full_cycle import stage_settings, complete_stage, evaluation
    from test_research_default_protocol import synthetic_artifacts, register
    from test_research_full_cycle_authority import authorize, intake, satisfy_initial_staffing
    # A retained legacy family-policy flag must not veto separate role sessions.
    policy = rdj_anchor.policy()
    policy['r3_distinct_family'] = True
    monkeypatch.setattr(rdj_anchor, 'policy', lambda: policy)
    _, original = intake(tmp_path)
    binding = {'contract': original, 'assignment_id': 'original-task'}
    definition = contract(tmp_path)
    definition['goal_binding'] = binding
    definition['budget'].update(calls=96, output_tokens=300000, wall_seconds=86400)
    root, rd = tmp_path/'cycle', tmp_path/'run'
    cycle.create(root, definition, base_dir=tmp_path, evaluation_harness=True)
    satisfy_initial_staffing(tmp_path/'parent', campaign_root=root)
    satisfy_initial_staffing(root)
    actual_context_graph(root, tmp_path)
    rivals = [{**hypothesis, 'operator': 'limitation_fix', 'what_is_new': None,
        'identity_signature': {'observable': 'variance', 'scope': 'signed records',
                               'prediction': hypothesis['id']},
        'kill_condition': {'comparison': 'differs', 'observable': 'variance'},
        'reopening_trigger': {'kind': 'changed_input', 'field': 'revision', 'op': 'gt', 'value': 0}}
        for hypothesis in hypotheses()]
    cycle.propose(root, rivals, origin={'kind': 'supplied_source',
        'pin': write(tmp_path/'hypotheses.json', rivals), 'description': 'Inert fictional rival declarations.'})
    artifacts = synthetic_artifacts(root)
    settings = stage_settings()
    for name in ('limitation_census', 'ideas'):
        complete_stage(root, name, write(root/(name+'.json'), artifacts[name]), 'legacy', settings)
    register(root)
    candidate = experiment(tmp_path, 'paired', grouped=True)
    study = json.loads(Path(candidate['study']['path']).read_text())
    study['goal_binding'] = binding
    candidate['study'] = write(Path(candidate['study']['path']), study)
    candidate = evaluation(tmp_path, candidate, round=1, goal=binding)
    cycle.design(root, candidate)
    cycle.prepare_experiment(root, 'paired', rd)
    satisfy_initial_staffing(rd, campaign_root=root)
    admit_method(rd)
    science.approve(rd, 'Execute the exact fictional supplied arithmetic.', scripted=True)
    authorize(root, research_evaluation.prepare_dispatch_action(root, 'paired'))
    assert cycle.run_experiment(root, 'paired') == 0
    result = cycle._pin(rd/'outputs/attempt-1/result.json')
    # The observed arithmetic is evidence for a subsequent prospective choice;
    # using the result itself as the action digest would be circular grounding.
    proposal = write(rd/'prospective-r3-choice.json', {
        'choice': 'Retain the bounded supplied-record result for independent review.', 'evidence': result})
    action = protocol.stage_action('independent_replication', proposal)
    observed = {} if observation == 'distinct' else {
        'critic': 'gpt-5' if observation == 'same_family' else 'opaque-provider-model'}
    monkeypatch.setattr(InertDecisionDispatcher, 'OBSERVED_MODELS', observed)
    pin = authorize(rd, action, level='R3')
    receipt = json.loads(Path(pin['path']).read_text())
    assert receipt['class'] == 'R3' and receipt['outcome'] == 'authorize'
    assert rdj_loop.authorizing_receipt(rd, 'research_choice', action) is not None
    summary = receipt['attestation_summary']
    relationship = {'distinct': 'different', 'same_family': 'same', 'unknown_family': 'unknown'}[observation]
    assert summary['distinct_sessions'] and summary['distinct_actors']
    assert summary['verifier_family_relationships']
    assert all(row['relationship'] == relationship
               and row['label'] == f'separate session, {relationship} model family'
               for row in summary['verifier_family_relationships'])
    # Read original Graph/Host receipts for both independent role sessions.
    # No fixture family field is supplied: classification follows HTTP model.
    families, substitutions = {}, []
    for path in rd.rglob(agent_graph.SPEC):
        specification = json.loads(path.read_text())
        for node in specification['nodes']:
            if node.get('role') not in {'rdj_critic', 'rdj_verifier'}:
                continue
            role = {'rdj_critic': 'critic', 'rdj_verifier': 'verifier'}[node['role']]
            manifest = json.loads((Path(node['packet']['path'])/'manifest.json').read_text())
            subject = manifest['artifacts'][0]['sha256']
            model = agent_graph.role_receipt(path.parent, node['id'], expected_subject_sha256=subject,
                expected_packet_sha256=node['packet']['manifest_sha256'], require_exact_subject=True,
                allowed_roles={node['role']})
            requested = node['parameters']['model']
            actual = model['transport']['observed_model']
            assert requested == InertDecisionDispatcher.MODELS[role]
            assert actual == observed.get(role, requested)
            assert model['execution_observation'] == 'remote_transport_observed'
            assert model['attestation'] == 'transport_attested'
            families[role] = transport_registry.model_family(actual)
            if requested != actual:
                substitutions.append(role)
    assert set(families) == {'critic', 'verifier'}
    if observation == 'distinct':
        assert families['critic'] == 'anthropic' and families['verifier'] == 'openai'
        assert not substitutions
    elif observation == 'same_family':
        assert families['critic'] == families['verifier'] == 'openai'
        assert 'critic' in substitutions
    else:
        assert families['critic'] == 'unknown'
        assert 'critic' in substitutions
