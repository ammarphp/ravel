"""Default research methodology synthetic controls; no native or scientific qualification."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import research_protocol as protocol
from ravel.workflow import research_cycle as cycle, agent_graph


STAGES = ('limitation_census', 'ideas', 'baseline', 'screen', 'validate',
          'critique_to_experiments', 'acceptance', 'meta_review', 'integrity')


def test_default_has_ordered_stage_roles_and_parallel_idea_streams():
    value = protocol.default_protocol()
    assert tuple(s['id'] for s in value['stages']) == STAGES
    assert all(s['roles'] and s['required_inputs'] and s['required_outputs'] for s in value['stages'])
    ideas = value['stages'][1]
    assert ideas['dispatch'] == 'map'
    assert ideas['roles'][:2] == ['idea-proposer-a', 'idea-proposer-b']


def test_absent_stage_artifact_and_missing_protocol_block(tmp_path):
    protocol.bind_default(tmp_path)
    assert protocol.methodology_errors(tmp_path)
    (tmp_path / 'research/protocol.json').unlink()
    with pytest.raises(ValueError, match='protocol'):
        protocol.methodology_status(tmp_path)


def test_mechanism_without_ablation_is_refused(tmp_path, monkeypatch):
    # Isolate the existing artifact contract; production producer refusal is tested separately.
    monkeypatch.setattr(protocol, 'producer_pending', lambda: [])
    claim = {'id': 'K1', 'kind': 'mechanism', 'verdict': 'accepted', 'N': 2}
    with pytest.raises(ValueError, match='ablation'):
        protocol.validate_stage_artifact('acceptance', {'claims': [claim]}, base_dir=tmp_path,
                                         regime='open_exploratory')


@pytest.mark.parametrize('mutation', ['omit', 'reorder', 'skip_without_reason'])
def test_stage_cannot_be_silently_skipped(tmp_path, mutation):
    protocol.bind_default(tmp_path)
    path = tmp_path / 'research/protocol.json'
    value = json.loads(path.read_text())
    if mutation == 'omit':
        value['stages'].pop(0)
    elif mutation == 'reorder':
        value['stages'].reverse()
    else:
        value['stages'][0].update(status='not_applicable', reason='')
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        protocol.methodology_status(tmp_path)


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return cycle._pin(path)


def synthetic_artifacts(root):
    """Pinned synthetic records, including explicit fake RDJ evidence."""
    evidence = write(root, 'source.json', {'value': 1, 'synthetic': True})
    audit = write(root, 'audit.json', {'status': 'passed', 'synthetic': True})
    case = write(root, 'case.json', {'schema_version': 2, 'synthetic': True})
    independent = write(root, 'independent.json', {'verdict': 'accept', 'synthetic': True})
    def decision(name, row, level):
        import hashlib
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=False).encode()).hexdigest()
        return {**row, 'rdj_receipt': write(root, 'rdj/'+name+'.json', {
            'schema_version': 1, 'kind': 'rdj-receipt', 'outcome': 'authorize',
            'gate': 'research_choice', 'action_digest': digest, 'class': level,
            'case': case, 'case_sha256': case['sha256'], 'open_a_findings': 0,
            'unresolved_branches': 0, 'attestation_summary': {
                'distinct_sessions': True, 'distinct_actors': True}})}
    select_result = write(root, 'select-result.json', {'kind': 'research-select-result', 'exposure': 'adaptive_full',
        'candidate': 'Ia', 'family': 'synthetic', 'status': 'success', 'decision': 'better', 'cost': 1})
    trial_pins = [write(root, 'trial-'+str(i)+'.json', {'candidate': 'I'+stream, 'value': 1-i,
        'cells': ['select'], 'seeds': [10+i], 'generation': 'select-data', 'status': 'success'})
        for i, stream in enumerate(('a', 'b'))]
    selection_request = {'rule': {'direction': 'maximize', 'metric': 'response', 'k': 1, 'alpha': .05},
        'regime': 'open_exploratory', 'trials': [{'id': 't'+str(i), 'candidate': 'I'+stream, 'result': trial_pins[i]}
            for i, stream in enumerate(('a', 'b'))]}
    selected = protocol.selection_receipt(selection_request, base_dir=root)
    selected_pin = write(root, 'selected.json', selected)
    confirmed = write(root, 'confirm.json', {'candidate': 'Ia', 'value': 1., 'p_value': .001,
        'cells': ['confirm'], 'seeds': [30], 'generation': 'confirm-data', 'status': 'success'})
    selection_report = write(root, 'selection-report.json', protocol.selection_report(selected, [confirmed], base_dir=root))
    cell = {'value': 1, 'unit': '1', 'uncertainty': 0, 'source': evidence}
    artifacts = {
        'limitation_census': {'limitations': [{'id': 'L1', 'subject': 'reference_method',
            'flaw': 'One regime is untested.', 'consequence': 'Generalization is unknown.',
            'opportunity': 'Test a second regime.', 'evidence': ['source:1'],
            'testable_signature': 'The response changes with regime.'}]},
        'ideas': {'ideas': [{'id': 'I'+stream, 'stream': stream, 'seed': 'limitation:L1',
            'hypothesis': 'The response depends on regime.', 'operator': 'limitation_fix', 'prediction': 'A held-out contrast changes.',
            'novelty': {'rank': index, 'prior_art': [], 'scout_receipt': evidence}}
            for index, stream in enumerate(('a', 'b'), 1)]},
        'baseline': {'three_columns': [{'quantity': 'response', 'ours': cell,
            'reproduced': cell, 'published': cell, 'published_source': evidence}]},
        'screen': {'subset': {'cells': ['development']}, 'omitted_regimes': ['confirmation'],
            'verdicts': [decision('screen', {'idea': 'Ia', 'verdict': 'promote', 'mutable_paths': []}, 'R2')]},
        'validate': {'withheld_cells': ['confirm'], 'rounds': [{'round': 1,
            'candidates': ['Ia'], 'successes': 1, 'results': [select_result], 'seed_reinjection': ['Ib'], 'trace': evidence}],
            'stop': {'successes': 1, 'max_rounds': 2, 'budget': 3, 'coverage_floor': 1,
                     'families': ['synthetic'], 'reason': 'successes'},
            'selection': decision('selection', {'rule': 'reviewed_dominance', 'comparison': evidence,
                'receipt': selected_pin, 'confirmation_pins': [confirmed]}, 'R2')},
        'critique_to_experiments': {'concerns': []},
        'acceptance': {'claims': [decision('claim', {'id': 'K1', 'kind': 'finding', 'N': 2, 'selection_receipt': selected_pin, 'selection_report': selection_report,
            'verdict': 'accepted', 'independent_review': independent}, 'R3')]},
        'meta_review': {'transport_id': 'external', 'receipt': evidence, 'verdict': {'outcome': 'accept'}},
        'integrity': {'receipt': evidence, 'report_integrity': evidence,
            'rerun': audit, 'references': audit, 'paper_vs_code': audit},
    }

    ideas = artifacts['ideas']
    ideas['dispatch_receipts'] = {stream: write(root, 'dispatch-'+stream+'.json', {
        'kind': 'research-idea-dispatch', 'stream': stream,
        'ideas_sha256': protocol.ce.digest([r for r in ideas['ideas'] if r['stream'] == stream]),
        'committed_sequence': 1, 'execution_observation': 'host_attested_external'}) for stream in ('a', 'b')}
    ideas['tests'] = []
    ideas['operator_yield'] = {'limitation_fix': {'ideas': 2, 'screen': {'tested': 0, 'passed': 0},
                                               'full': {'tested': 0, 'passed': 0}}}
    return artifacts



def governed_cycle(root):
    from test_research_cycle import contract
    c = contract(root)
    c['research_protocol_required'] = True
    c['budget'].update(calls=64, output_tokens=200000, wall_seconds=3600)
    run = root / 'cycle'
    cycle.create(run, c, base_dir=root, evaluation_harness=True)
    return run


def register(root):
    pin = write(root, 'preregistration.json', {
        'schema_version': 1, 'kind': 'research-preregistration', 'approximations': [],
        'selection_rule': {'direction': 'maximize', 'metric': 'response', 'k': 1, 'alpha': .05},
        'stop_rule': {'successes': 1, 'max_rounds': 2, 'budget': 3, 'coverage_floor': 1, 'families': ['synthetic']},
        'expected_effect': {'statement': 'A synthetic unit contrast; no physical inference.'},
        'evaluator_not_applicable': {k: 'Supplied dimensionless arithmetic only.' for k in
                                   ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}})
    protocol.preregister(root, pin, {}, evaluation_harness=True)


@pytest.mark.parametrize('unattributed_mechanism', [False, True])
def test_synthetic_transport_reports_stop_without_evaluation_observations(tmp_path, monkeypatch, unattributed_mechanism):
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])  # isolated Graph/Host transport contract
    root = governed_cycle(tmp_path)
    register(root)
    artifacts = synthetic_artifacts(root)
    if unattributed_mechanism:
        import hashlib
        claim = artifacts['acceptance']['claims'][0]
        claim.update(kind='mechanism', ablation={'arm_without_mechanism': cycle._pin(root/'source.json'),
                                               'controls_fixed': ['sample', 'budget']})
        receipt = json.loads((root/'rdj/claim.json').read_text())
        payload = {k: v for k, v in claim.items() if k != 'rdj_receipt'}
        receipt['action_digest'] = hashlib.sha256(json.dumps(payload, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        claim['rdj_receipt'] = write(root, 'rdj/claim.json', receipt)
    monkeypatch.setattr(cycle, 'validate_graph_reservation', lambda *a: None)
    def receipt(graph_root, node_id, **kwargs):
        path = root / ('review-'+stage) / node_id / 'packet/manifest.json'
        manifest = json.loads(path.read_text())
        return {'context_transport_separated': True, 'execution_observation': 'host_attested_external',
                'presented_subject_sha256s': [r['sha256'] for r in manifest['artifacts']],
                'synthetic_stub': True}
    monkeypatch.setattr(agent_graph, 'role_receipt', receipt)
    for stage in STAGES:
        if stage == 'validate':
            selected = protocol._method_json(artifacts['validate']['selection']['receipt'], root)
            request = {'rule': selected['rule'], 'regime': selected['regime'],
                'trials': [{k: r[k] for k in ('id','candidate','result')} for r in selected['trials']]}
            with pytest.raises(ValueError, match='observ|evaluation|census'):
                protocol.commit_selection(root, write(root, 'selection-request.json', request))
            assert protocol.methodology_status(root)['next_stage'] == 'validate'
            return
        artifact = write(root, stage+'.json', artifacts[stage])
        prepared = protocol.prepare_stage(root, stage, artifact, root / ('review-'+stage), model='stub')
        spec = json.loads(open(prepared['specification']['path']).read())
        assert all(node['action'] == 'external' for node in spec['nodes'])
        assert prepared['roles'] == next(r for r in protocol.default_protocol()['stages'] if r['id'] == stage)['roles']
        def result(graph_root, node_id):
            return {'value': {'value': {'stage': stage, 'role_id': node_id,
                'subject_sha256': prepared['subject']['sha256'], 'verdict': 'accept', 'findings': [],
                'attributed_claim_ids': []}}}
        monkeypatch.setattr(cycle, '_graph_result', result)
        if unattributed_mechanism and stage == 'acceptance':
            with pytest.raises(ValueError, match='did not attribute'):
                protocol.complete_stage(root, prepared, root / ('graph-'+stage))
            assert protocol.methodology_status(root)['next_stage'] == 'acceptance'
            return
        status = protocol.complete_stage(root, prepared, root / ('graph-'+stage))
        assert next(r for r in status['record']['stages'] if r['id'] == stage)['status'] == 'done'
    assert status['complete'] and not status['scientific_acceptance']
    assert cycle._load(root)[1]['methodology'] == status['record']


def test_campaign_cannot_delete_or_disable_its_required_protocol(tmp_path):
    root = governed_cycle(tmp_path)
    (root / 'research/protocol.json').unlink()
    with pytest.raises(ValueError, match='protocol'):
        cycle.select(root)


def test_missing_role_delivery_blocks_stage_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])  # isolate actual role receipt requirement
    root = governed_cycle(tmp_path)
    artifact = write(root, 'census.json', synthetic_artifacts(root)['limitation_census'])
    prepared = protocol.prepare_stage(root, 'limitation_census', artifact, root/'review', model='stub')
    monkeypatch.setattr(cycle, 'validate_graph_reservation', lambda *a: None)
    monkeypatch.setattr(cycle, '_graph_result', lambda *a: (_ for _ in ()).throw(ValueError('role missing')))
    with pytest.raises(ValueError, match='role missing'):
        protocol.complete_stage(root, prepared, root/'graph')
    assert protocol.methodology_status(root)['next_stage'] == 'limitation_census'


def test_exploratory_finding_needs_R3_and_independent_review(tmp_path, monkeypatch):
    monkeypatch.setattr(protocol, 'producer_pending', lambda: [])
    value = synthetic_artifacts(tmp_path)['acceptance']
    row = value['claims'][0]
    receipt_path = tmp_path/'rdj/claim.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['class'] = 'R2'
    row['rdj_receipt'] = write(tmp_path, 'rdj/claim.json', receipt)
    with pytest.raises(ValueError, match='R3'):
        protocol.validate_stage_artifact('acceptance', value, base_dir=tmp_path, regime='open_exploratory')


def test_world_digest_changes_with_ruled_out_evidence_and_retains_scope(tmp_path):
    root = governed_cycle(tmp_path)
    before = protocol.world_digest(root)
    assert before['verified_results'] == [] and before['ruled_out_directions'] == []
    assert not protocol.methodology_status(root)['complete']


def test_protocol_gate_matches_decision_gate_signature_and_is_read_only(tmp_path, monkeypatch):
    import sys
    from dataclasses import make_dataclass
    from types import SimpleNamespace
    error = make_dataclass('GateError', [('code', str), ('gate', str), ('provider', str),
        ('message', str), ('fix', str), ('pins', tuple, ())])
    monkeypatch.setitem(sys.modules, 'ravel.workflow.decision_gate', SimpleNamespace(GateError=error))
    protocol.bind_default(tmp_path)
    before = (tmp_path/'research/protocol.json').read_bytes()
    errors = protocol.gate_errors(tmp_path, 'research_choice', {'scope': 'acceptance'})
    assert errors and all(e.provider == 'research_protocol' for e in errors)
    assert (tmp_path/'research/protocol.json').read_bytes() == before


def test_keyless_stage_uses_real_external_delivery_and_stays_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])  # isolate existing transport/round contract
    from ravel.workflow import research_orchestrator, agent_host
    root = governed_cycle(tmp_path)
    artifact = write(root, 'census.json', synthetic_artifacts(root)['limitation_census'])
    value = research_orchestrator.run_protocol_stage(root, artifact, root/'stage',
        host=agent_host.AgentHost(), settings={'model': 'host-agent', 'reasoning_effort': 'high',
            'adapter': 'external', 'max_output_tokens': 1024, 'max_wall_seconds': 30})
    assert value['kind'] == 'research-stage-delivery-required' and not value['complete']
    assert protocol.methodology_status(root)['next_stage'] == 'limitation_census'
    assert cycle._load(root)[1]['resource_ledger']


def test_keyless_stage_consumes_real_graph_receipts_from_synthetic_host_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])  # isolate existing transport/round contract
    from test_agent_graph import external_response
    from ravel.workflow import research_orchestrator, agent_host
    root = governed_cycle(tmp_path)
    artifact = write(root, 'census.json', synthetic_artifacts(root)['limitation_census'])
    settings = {'model': 'host-agent', 'reasoning_effort': 'high', 'adapter': 'external',
                'max_output_tokens': 1024, 'max_wall_seconds': 60}
    value = research_orchestrator.run_protocol_stage(root, artifact, root/'stage',
        host=agent_host.AgentHost(), settings=settings)
    graph_root = root/'stage/graph'
    for role in value['graph']['nodes']:
        pending = agent_graph.prepare_external(graph_root, role)
        document = json.loads(open(pending['request_file']).read())
        fields = document['parameters']['output_schema']['properties']
        public = {key: fields[key]['const'] for key in ('stage', 'role_id', 'subject_sha256')}
        public.update(verdict='accept', findings=['Synthetic transport control only.'], attributed_claim_ids=[])
        response = external_response(pending, root/(role+'-response.json'), value=public,
                                     actor_id='synthetic-'+role, observed_model='host-agent')
        agent_graph.deliver_external(graph_root, role, response)
    result = research_orchestrator.run_protocol_stage(root, artifact, root/'stage',
        host=agent_host.AgentHost(), settings=settings)
    assert result['complete'] and not result['scientific_acceptance']
    assert protocol.methodology_status(root)['next_stage'] == 'ideas'
    assert agent_graph.status(graph_root)['usage']['calls'] == 2


def test_stage_review_round_bound_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])  # isolate existing transport/round contract
    root = governed_cycle(tmp_path)
    artifact = write(root, 'census.json', synthetic_artifacts(root)['limitation_census'])
    for index in range(2):
        protocol.prepare_stage(root, 'limitation_census', artifact, root/('review'+str(index)), model='stub')
    with pytest.raises(ValueError, match='round bound'):
        protocol.prepare_stage(root, 'limitation_census', artifact, root/'review2', model='stub')


def test_prepare_open_binds_default_without_authored_protocol(tmp_path):
    from test_langgraph_research_orchestration import open_fixture
    request, _, _, _ = open_fixture(tmp_path)
    status = protocol.methodology_status(tmp_path/'request')
    assert status['next_stage'] == 'limitation_census'
    assert tuple(row['id'] for row in status['record']['stages']) == STAGES
    assert request['path'].endswith('request.json')
