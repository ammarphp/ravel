"""One governed seat attempt per path, observed through an inert CLI worker.

P03 instruction delivery and the protected ledger are real. Existing P04
authority/confinement/independence peers and the inert CLI are explicit seams.
Each approved plan names one seat; separate path tests exercise its surrounding
route, scientific consumer and review population. No scientific acceptance is
inferred from a scripted final record.
"""
import hashlib
import json

import pytest
from jsonschema import Draft202012Validator

from ravel.controller import instructions
from ravel.controller.step.services import digest
from ravel.workflow import agent_worker
from test_p04_ledger_contract import contract_env, instructed_env, run_contract  # noqa: F401
from test_p04_support import graphs, inert_worker, run_env, services_installed, make_step  # noqa: F401
from test_scoped_path_packets import CASES, source_card


@pytest.mark.parametrize('case', CASES, ids=[case[0] for case in CASES])
@pytest.mark.parametrize('malformed', [False, True], ids=['valid-record', 'missing-escalation'])
def test_path_seat_receives_real_packet_and_schema_controls_adoption(
        instructed_env, inert_worker, graphs, case, malformed, record_property, monkeypatch):
    name, role, operation, stage, source, snippet, readings, _, packet_schema, tool = case
    env = instructed_env
    current = make_step('slice-' + name, role=role,
                        kind='review' if name in ('review', 'plan-review') else 'author',
                        outputs=(('outputs/value.json', 'document'),),
                        parameters={'target_operation': operation})
    current.update(stage=stage, instruction_sources=[source], seats=[])
    current['outputs'] += source_card(role)['output']['declared_outputs']
    contract_path = env.run_dir / 'inputs/task_contract.json'
    contract = json.loads(contract_path.read_text())
    contract['escalate'] = ['stat_mode is deferred to the following consumer.']
    contract_path.write_text(json.dumps(contract))
    if role == 'literature-scout':
        (env.run_dir / 'inputs/resource_census.json').write_text(json.dumps({
            'schema_version': 1, 'rungs': {'supplied-record': {'status': 'OK', 'source': 'fictional fixture'}}}))
    if role == 'manuscript-writer' and not malformed:
        from test_p04_support import toy_comparison_certificate
        current['parameters']['check_inputs'] = {
            'check:validation.certificates.validate_certificate': toy_comparison_certificate(env.run_dir)}
    if role in ('physics-critic', 'plan-critic'):
        # The existing inert transport seam supplies this seat's declared blind
        # eligibility; source/custody/schema/instruction checks remain real.
        from test_p04_graph import _qualified_blind_worker
        _qualified_blind_worker(monkeypatch)
    # Review policy has its own graph slice. This explicit one-seat plan exercises
    # dispatch/delivery/schema only and binds the full card without changing it.
    if malformed:
        inert_worker.scenario(drop=['escalation'])
    result = run_contract(env, current)
    dispatch = [r['record'] for r in env.store.scan('step-dispatch')]
    assert [(r['step_id'], r['seat']) for r in dispatch] == [('slice-' + name, None)], result
    launched = [agent_worker._record(env.run_dir, r['node_id'], r['attempt'])['spec'] for r in dispatch]
    assert [s['role']['id'] for s in launched] == [role]
    assert [digest(s) for s in launched] == [r['spec_sha256'] for r in dispatch]
    packets = [r['record'] for r in env.store.scan('instruction-packet')]
    assert len(packets) == 1
    committed = packets[0]
    packet, manifest, card = committed['packet'], committed['manifest'], committed['card']
    assert card['id'] == role and packet['schema_id'] == packet_schema
    assert card['purpose'] == source_card(role)['purpose']
    assert tuple(card['knowledge']['must_read']) == readings
    assert snippet in packet['text']
    assert instructions.check_packet(packet, manifest, card, committed['step_spec'], committed['inputs'],
                                     budget=packet['budget']) == []
    assert any(row['id'] == 'op:' + operation for row in packet['capability_context']['catalogue']['entries'])
    assert any(row['id'] == 'tool:affordance/' + tool for row in packet['capability_context']['catalogue']['entries'])
    session_rows = env.store.scan('worker-session')
    workspace = agent_worker.workspace(env.run_dir, dispatch[0]['node_id'], 1)
    actual_prompt = (workspace / 'scratch/prompt.txt').read_text()
    actual_tools = json.loads((workspace / 'scratch/tools.json').read_text())
    assert tool == 'submit_final' or tool in actual_tools
    assert 'ws_write' in actual_tools
    assert packet['text'] in actual_prompt
    assert json.dumps(card, indent=1, sort_keys=True, ensure_ascii=False) in actual_prompt
    assert hashlib.sha256(packet['text'].encode()).hexdigest() == dispatch[0]['packet_sha256']
    completion_rows = env.store.scan('worker-completion')
    # A malformed final record can be refused by the worker before its completion
    # is eligible for ledger credit. The controller keeps its dispatch evidence.
    adopted = [r['record'] for r in env.store.scan('custody') if r['record']['status'] == 'accepted']
    if malformed:
        assert result['status'] == 'failed', result
        assert set(result['reason'].split(',')) == {
            'worker_receipt_failed', 'final_record_schema', 'card_output_schema', 'escalation_field_missing'}, result
        assert adopted == []
    else:
        assert result['status'] == 'completed', (result, env.store.scan('step-validation'))
        assert {a['artifact'] for a in adopted} == {
            'slice-' + name + ':' + row['path'] for row in current['outputs']} | {'slice-' + name + ':final-record.json'}
        assert len(session_rows) == len(completion_rows) == 1, result
        completed = completion_rows[0]['record']
        final = completed['final_record']
        assert list(Draft202012Validator(packet['schema']).iter_errors(final)) == []
        with instructions.observed_completion(env.store, session=session_rows[0]['id'],
                                               completion_id=completion_rows[0]['id']):
            assert instructions.check_ack(manifest, final, [a['path'] for a in completed['artifacts']]) == []
        deliveries = [r['record'] for r in env.store.scan('instruction-delivery')
                      if r['record'].get('kind') == 'instruction-delivery-session']
        assert len(deliveries) == 1 and deliveries[0]['packet_sha256'] == packet['sha256']
    record_property('path_dispatch', json.dumps({'path': name, 'malformed': malformed,
        'expected_roles': [role], 'actual_roles': [s['role']['id'] for s in launched],
        'schema': packet_schema, 'status': result['status'], 'reason': result['reason']}, sort_keys=True))
