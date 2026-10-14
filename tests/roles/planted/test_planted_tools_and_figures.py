"""Full-tool reviewer through the broker (check run, AG-3, refused reads) and the figure-critique gate."""
import hashlib
import json
from pathlib import Path

import pytest

from planted_fixtures import EXPECTED_YIELD, NORMALIZATION, run_tree, write


def _spec(root, role, inputs):
    from ravel.workflow import role_registry
    card = role_registry.load(role)
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': 'rv-' + role, 'attempt': 1,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': role_registry.card_sha256(role)},
            'transport_preference': ['default'], 'inputs': inputs,
            'declared_outputs': [{'path': 'outputs/review.json', 'kind': 'review-findings', 'required': False}],
            'budgets': {'max_turns': 5, 'max_wall_seconds': 60, 'max_broker_calls': 20, 'max_cost_usd': None},
            'final_record_schema': 'reviewer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}


@pytest.fixture
def reviewer(tmp_path):
    """A normalization auditor's real workspace and broker, with its projection packet and one pinned input."""
    from ravel.workflow import agent_worker, broker, review_projection, review_projection_checks, role_registry
    run = run_tree(tmp_path.resolve() / 'run')
    pin = write(run / 'inputs/normalization.json', {**NORMALIZATION, 'reported_yield': EXPECTED_YIELD / 1.25})
    packet = review_projection.project(run, 'normalization-auditor', key='tools')
    spec = _spec(run, 'normalization-auditor',
                 [{'pin': {'path': 'inputs/normalization.json', 'sha256': pin['sha256']}, 'as': 'inputs/normalization.json'}])
    ws = agent_worker.materialize(run, spec, packet=packet)
    card = role_registry.load('normalization-auditor')
    target = broker.Broker(run, ws, node_id=spec['node_id'], attempt=1, allowed_actions=['read', 'check run'],
                           max_calls=20)
    review_projection_checks.register(target, card)
    return run, ws, target, packet


def test_reviewer_recomputes_from_pinned_inputs_and_catches_the_omitted_k_factor(reviewer):
    run, ws, target, _ = reviewer
    reply = target.call({'call_id': 'c1', 'action': 'check run',
                         'args': {'check_id': 'review.normalization_recompute', 'paths': ['inputs/normalization.json']}})
    assert reply['status'] == 'failed', reply  # the check ran and its verdict is a failure
    out = json.loads(reply['stdout_tail'])
    value = json.loads((ws / out['result']).read_text())
    assert value['status'] == 'failed' and value['diagnostics']['cause'] == 'k_factor_omitted'
    receipt = json.loads((ws / 'calls/1.json').read_text())
    assert receipt['derivation'] == 'registered_validator' and receipt['exit_status'] == 1
    assert receipt['validator_id'] == 'review.normalization_recompute'
    assert receipt['output_pins'] and receipt['input_pins']


def test_check_outside_the_card_and_reads_outside_the_workspace_are_refused_with_receipts(reviewer):
    run, ws, target, _ = reviewer
    denied = target.call({'call_id': 'c1', 'action': 'check run',
                          'args': {'check_id': 'review.manuscript_audit', 'paths': ['inputs/normalization.json']}})
    assert denied['status'] == 'refused' and denied['error']['code'] == 'not_allowlisted'
    escape = target.call({'call_id': 'c2', 'action': 'read', 'args': {'path': '../../RESULT.md'}})
    assert escape['status'] == 'refused' and escape['error']['code'] == 'forbidden_source'
    for n in (1, 2):
        assert json.loads((ws / f'calls/{n}.json').read_text())['status'] == 'refused'


def test_finding_counts_only_with_receipt_or_pinned_input_evidence(reviewer):
    from ravel.workflow import review_projection
    run, ws, target, packet = reviewer
    reply = target.call({'call_id': 'c1', 'action': 'check run',
                         'args': {'check_id': 'review.normalization_recompute', 'paths': ['inputs/normalization.json']}})
    manifest, _ = review_projection.load(packet)

    def errors(locators, cls='code_check'):
        finding = {'summary': 's', 'materiality': 'A', 'evidence_class': cls, 'evidence_locators': locators}
        return [e['code'] for e in review_projection.finding_errors(run, finding, node_id='rv-normalization-auditor',
                                                                     attempt=1, packet_manifest=manifest)]
    assert errors(['receipt:' + reply['receipt_id']]) == []
    assert errors(['pin:' + manifest['artifacts'][0]['sha256']]) == []
    assert errors(['outputs/yields.json']) == ['non_receipt_pin']
    assert errors(['receipt:rv-normalization-auditor/1/99']) == ['receipt_unknown']
    refused = target.call({'call_id': 'c2', 'action': 'check run',
                           'args': {'check_id': 'review.manuscript_audit', 'paths': ['inputs/normalization.json']}})
    assert refused['status'] == 'refused' and errors(['receipt:' + refused['receipt_id']]) == ['receipt_unknown']
    assert errors([]) == ['finding_unpinned']
    assert errors(['outputs/yields.json'], cls='opinion') == []     # advisory, never blocking


def test_allowlist_governs_registered_validators(tmp_path):
    from ravel.workflow import agent_worker, broker, review_projection_checks
    rows = {r['id'] for r in review_projection_checks.allowlist()['validators']}
    assert set(review_projection_checks.CHECKS) <= rows and 'check-run' in rows
    run = tmp_path.resolve() / 'run'
    run.mkdir()
    ws = agent_worker.workspace(run, 'n1', 1)
    ws.mkdir(parents=True)
    target = broker.Broker(run, ws, node_id='n1', attempt=1, allowed_actions=['x'], max_calls=1)
    with pytest.raises(ValueError, match='allowlist'):
        target.register('x', lambda args: {}, derivation='registered_validator', validator_id='not-on-the-list')


# ---- figure critique ---------------------------------------------------------------------

def test_figure_red_flag_blocks_delivery_until_a_clean_critique_of_the_current_bytes(tmp_path):
    from ravel.workflow import decision_gate, review_projection_figures as figures
    run = tmp_path.resolve() / 'run'
    write(run / 'plots/fig1.png', 'synthetic-image-v1')
    assert any(p['id'] == 'figure_critique' and p['active'] for p in decision_gate.providers('delivery'))
    assert figures.gate_errors(run, 'delivery', {}) == []
    figures.record(run, figure='plots/fig1.png', figure_id='F1',
                   red_flags=[{'code': 'axis_mislabelled', 'summary': 'the y axis names the wrong quantity'}])
    assert [e.code for e in figures.gate_errors(run, 'delivery', {})] == ['figure_red_flag']
    assert figures.gate_errors(run, 'approve_plan', {}) == []
    write(run / 'plots/fig1.png', 'synthetic-image-v2')
    assert [e.code for e in figures.gate_errors(run, 'final_task', {})] == ['figure_critique_stale']
    figures.record(run, figure='plots/fig1.png', figure_id='F1', mismatches=['legend order differs'])
    assert figures.gate_errors(run, 'delivery', {}) == []
    with pytest.raises(ValueError):
        figures.record(run, figure='plots/fig1.png', figure_id='F1', red_flags=[{'code': 'ugly', 'summary': 'x'}])
