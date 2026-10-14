"""CB4-09: an ordinary delegated study reaches an accepted review with a blind normalization auditor.

The study is a synthetic, ordinary (non-science-mode) epoch-two run whose CHECK-IN 1 is a real
machine approval under the user's delegation; nothing mocks the approval envelope. The
auditor worker is mocked on the transport side only: it runs the card's must_check on the
run's ledger, writes a worker receipt, and the dispatcher's transport re-verification is
simulated by registering that receipt with its verified label. Every credit decision is made
by the merged review-point engine. No model, network or native tool is called; the live cell
(``RAVEL_LIVE_CELL=1``, run by root through scripts/live/ordinary_review_cell.sh) is the one
place a real sandboxed worker runs.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

# Also collectable as an explicit file without the unit suite in the invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unit'))
import intake_sidecar_fixtures as fx
from test_physics_review import make_attempt, check_packet
from test_auditor_ledger_recompute import audit_ledger, ledger, pinned_table, wrong_order
from test_result_templates import HEPDATA, edges, table

from ravel.workflow import (agent_worker, gate_wiring, physics_review as pr, rdj_custody, result_templates as rt,
                            review_points as rp, role_registry, scientific_autonomy as autonomy,
                            workflow_state as ws)
from ravel.workflow.request_plan import provisional_label
from ravel.workflow.state_io import atomic_json

PROMPT = ("Run autonomously: compute the expected signal yield per missing-momentum bin for a synthetic "
          "700 GeV chargino with a 150 GeV LSP and fill the supplied result template.")
CLAIM = 'C1'
POINT = 'RP5:' + CLAIM
AUDITOR = 'normalization-auditor'
LEDGER = 'inputs/normalization_ledger.json'
RESULT = 'inputs/result.json'
# The ledger is an effective setting: the only file a bounded correction may change.
SETTINGS = ['inputs/settings.cfg', LEDGER]
# Producer numbers and headline that a blind auditor must never receive.
PRODUCER_VALUES = (12.3456789, 4.0987654)
HEADLINE = 'Headline: the synthetic signal yield is 16.4444443 events'
REVIEWERS = (('physics_critic', 'critic'), ('skeptical_verifier', 'skeptic'), ('physics_decider', 'physicist'))


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    """Per-test custody ledgers; a live cell keeps the transport qualification records it was given."""
    import shutil
    state = tmp_path / 'custody'
    given = os.environ.get('RAVEL_STATE_DIR')
    if given and (Path(given) / 'transports').is_dir():
        shutil.copytree(Path(given) / 'transports', state / 'transports')
    monkeypatch.setenv('RAVEL_STATE_DIR', str(state))
    # The R2 approve_plan decision has its own tests (test_gate_wiring_r2r3); this module isolates the
    # review path after CHECK-IN 1, so only that one gate is stubbed and every other gate stays live.
    # Handoff: build an authorized R2 plan_approval case here instead.
    original = gate_wiring.require_delegated
    monkeypatch.setattr(gate_wiring, 'require_delegated',
                        lambda rundir, gate, action: None if gate == 'approve_plan' else original(rundir, gate, action))
    return state


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def review_policy():
    return {"schema_version": 1,
            "actors": {"proposer": "worker", "executor": "worker", "physics_decider": "physicist",
                       "skeptical_verifier": "skeptic", "physics_critic": "critic"},
            "max_redos": 1, "allowed_changed_paths": [LEDGER], "allowed_stages": ["detector"],
            "required_checks": [{"id": "integrity", "kind": "integrity"}, {"id": "agreement", "kind": "scientific"}],
            "claim_scopes": {"diagnostic": {"checks": ["integrity"], "actions": ["delivery"]}}}


def study(base, *, order=None):
    """A delegated ordinary study through CHECK-IN 1 to an open review cycle."""
    rd = Path(base).resolve() / 'run'
    claim = fx.claim(CLAIM, kind='calculation', statement='expected signal yield per bin of the synthetic point',
                     deliverable={'artifact': 'binned_values', 'template': None}, level='expected',
                     comparison={'target': 'none', 'locator': None, 'metric': None, 'tolerance': None},
                     basis_declared=['generated_prediction'])
    nodes = [fx.node(operation='literal-calculation', review={'claim_scope': 'diagnostic', 'actions': ['delivery']})]
    # The plan's own derived label: an ordinary calculation, not a research route.
    draft = fx.plan({'path': 'inputs/reading.json', 'sha256': '0' * 64}, PROMPT, claims=[claim], nodes=nodes)
    label = provisional_label(fx.reading(PROMPT), draft)
    contract, reading, plan = fx.pinned_run(rd, prompt=PROMPT, plan_overrides={'claims': [claim], 'nodes': nodes,
                                                                               'label': label},
                                            contract_overrides={'task_mode': label['task_mode']})
    user = rd / 'inputs/initial-user-message.txt'
    user.write_text(PROMPT)
    declared = autonomy.prepare_declaration(
        contract, rd / 'inputs/delegation.json',
        user_text={'path': str(user), 'sha256': hashlib.sha256(PROMPT.encode()).hexdigest()},
        quote='Run autonomously:', origin='initial_prompt', delegate_actor='ravel-coordinator',
        actions=['approve_plan'],
        bounds={'compute_plans': ['none'], 'allowed_changed_paths': [LEDGER], 'allowed_stages': ['detector'],
                'max_redos': 1},
        task_class='research_analysis', base_dir=rd)
    fx.write_json(rd / 'inputs/task_contract.json', declared['document'])
    # The release intake records the prompt and the run_init snapshot once the contract is final.
    gate_wiring.record_run_init(rd)
    checkin1 = fx.checkin1(plan, reading)
    checkin1['variant'] = label['task_mode']
    checkin1['sections'].update({
        'formula': 'yield_i = sigma * BR * L * sumw_i / sumw_generated', 'conventions': 'pb, fb^-1, signed weights',
        'inputs': {'ledger': LEDGER}, 'precision': 'exact recomputation', 'check_value': 'unit weights return sigma*BR*L'})
    fx.write_json(rd / 'inputs/checkin1.json', checkin1)
    fx.write_json(rd / 'inputs/cost_preflight.json', {'schema_version': 1, 'generated_by': 'cost_preflight.py',
                                                       'mode': 'none', 'walltime_h': [0, 0]})
    atomic_json(rd / pr.POLICY, review_policy())
    ws.record_delegated_approval(rd, 'none')
    (rd / 'inputs/settings.cfg').write_text('synthetic=1\n')
    (rd / 'inputs/held-fixed.txt').write_text('fixed\n')
    atomic_json(rd / 'inputs/reference.json', {'reference': 1})
    atomic_json(rd / LEDGER, ledger(order=order))
    atomic_json(rd / RESULT, table(edges((250, 350), (350, 450), values=list(PRODUCER_VALUES))))
    (rd / 'RESULT.md').write_text(HEADLINE + '\n')
    attempt = run_stage(rd)
    pr.open_cycle(rd, effective_settings=SETTINGS, stage_receipts=[attempt['attempt_record']],
                  check_results='inputs/checks.json')
    return rd


def run_stage(rd, value=1):
    attempt = make_attempt(rd, value=value, extra_inputs=[LEDGER, RESULT])
    check_packet(rd, attempt)
    return attempt


def point(rd):
    return next(p for p in rp.derive(rp._facts(rd)) if p['id'] == POINT)


def auditor_errors(rd):
    """review_points errors at CHECK-IN 2 acceptance that concern the auditor point."""
    errors = rp.gate_errors(rd, 'checkin2_accept', {'claim_id': CLAIM})
    return [e for e in errors if any(pin.startswith(POINT) for pin in e.pins)
            or e.code == 'blocking_finding']


def pending_auditor(rd):
    return any(e.code == 'review_point_pending' and POINT + ':' + AUDITOR + ':1' in e.pins for e in auditor_errors(rd))


def auditor_receipt(rd, node, *, findings=(), subject=None, mode='transport_attested_cli', label='transport_attested',
                    register=True, modified=False):
    """The receipt a sandboxed auditor worker leaves; ``label`` is the dispatcher's transport re-verification."""
    folder = rd / 'agent-work' / node / '1'
    folder.mkdir(parents=True)
    final = {'completed': True, 'disposition': 'not_supported' if findings else 'supported', 'findings': list(findings)}
    (folder / 'final.json').write_text(json.dumps(final, sort_keys=True))
    # U1 receipt version 2: the review subject (scope and digest) a review receipt needs for credit.
    expected = rp.review_subject(rp._facts(rd), point(rd))
    receipt = {'schema_version': 2, 'kind': 'agent-worker-receipt', 'node_id': node, 'attempt': 1,
               'review_point_id': POINT, 'role': {'id': AUDITOR}, 'status': 'ok', 'execution_mode': mode,
               'review_subject': {**expected, 'sha256': subject} if subject else expected,
               'session_id': 'session-' + node, 'actor_id': 'actor-' + node, 'run_tree': {'modified': modified},
               'final_record': {'valid': True, 'path': 'final.json', 'sha256': sha(folder / 'final.json')},
               'model': {'family': 'synthetic-family'}}
    (folder / 'receipt.json').write_text(json.dumps(receipt, sort_keys=True))
    rel = (folder / 'receipt.json').relative_to(rd).as_posix()
    if register:
        rdj_custody.register_worker_receipt(rd, rel, verified_label=label)
    return rel


def run_auditor(rd, node):
    """Mocked blind auditor: its must_check on the run's ledger, a registered result, then its receipt.

    It reads only the pinned ledger; producer numbers and the headline never enter.
    """
    result, findings = audit_ledger(json.loads((rd / LEDGER).read_text()), check_id=node)
    result['pins'] = [{'path': LEDGER, 'sha256': sha(rd / LEDGER)}]
    (rd / 'checks').mkdir(exist_ok=True)
    (rd / 'checks' / (node + '.json')).write_text(json.dumps(result, sort_keys=True))
    rdj_custody.register_check_result(rd, 'checks/' + node + '.json')
    auditor_receipt(rd, node, findings=findings)
    return findings


def accept_all(rd, *, closes=()):
    for role, actor in REVIEWERS:
        pr.submit_review(rd, role=role, actor_id=actor, verdict='accept', summary='Evidence supports the stated scope',
                         claim_scope='diagnostic', closes=list(closes))


def fill(rd, base, name='filled.yaml'):
    template = Path(base) / 'template.yaml'
    if not template.exists():
        template.write_text(HEPDATA)
    return rt.fill(template, rd / RESULT, Path(base) / name, rundir=rd, claim_scope='diagnostic', base_dir=base)


def report_for(rd, node):
    records = list(rp._receipt_records(rd, rp._facts(rd)))
    return rp._receipt_report(next(r for r in records if r['node_id'] == node))


# ---------------------------------------------------------------- the ordinary delegated cycle

def test_ordinary_delegated_study_opens_a_cycle_on_its_actual_approval(tmp_path):
    rd = study(tmp_path)
    approval = json.loads((rd / 'inputs/checkin1_approval.json').read_text())
    assert approval['authority'] == 'delegated_machine' and approval['schema_version'] == 3
    assert ws.verify_approval(str(rd)) == []
    # Ordinary, not science mode; the absent optional delegated-defaults record is not pinned.
    assert not pr._science_run(rd)
    plan = json.loads((rd / 'inputs/plan.json').read_text())
    assert plan['label']['task_mode'] == 'calculation' and pr.gate_errors(rd, 'delivery')
    assert pr.status(rd)['state'] not in {'invalid', 'accepted'} and pr.status(rd)['cycle_id']
    registration = json.loads((rd / pr.REGISTRATION).read_text())
    assert pr.POLICY in [b['path'] for b in registration['bindings']]
    p = point(rd)
    assert p['gate'] == 'checkin2_accept' and p['blocking'] and p['mode'] == 'specialist'
    assert p['roles'] == [{'role': AUDITOR, 'count': 1, 'distinct_family_from': []}]
    card = role_registry.load(AUDITOR)
    assert card['requires']['blind'] is True and 'producer_numbers' in card['knowledge']['forbidden']


# ---------------------------------------------------------------- NEG 1: credit is never synthesized

def test_no_worker_receipt_never_reaches_checkin2_acceptance(tmp_path):
    rd = study(tmp_path)
    assert not rp.satisfied(rd, POINT)
    assert pending_auditor(rd)
    with pytest.raises(ValueError, match='CHECK-IN 2 acceptance refused'):
        rp.accept_checkin2(rd, {'claim_id': CLAIM})
    assert rdj_custody.rows(rd, 'review_acceptances') == []
    # Opening the cycle, reading status and inspecting gates wrote no receipt.
    assert not (rd / 'agent-work').exists()


@pytest.mark.parametrize('forgery', ['unregistered', 'self_attested', 'host_label', 'human_manual', 'wrong_subject',
                                     'run_modified'])
def test_forged_or_weak_receipts_earn_no_auditor_credit(tmp_path, forgery):
    rd = study(tmp_path)
    options = {'unregistered': {'register': False}, 'self_attested': {'label': None},
               'host_label': {'label': 'host_attested'}, 'human_manual': {'mode': 'human_manual'},
               'wrong_subject': {'subject': '0' * 64}, 'run_modified': {'modified': True}}[forgery]
    auditor_receipt(rd, 'forged-' + forgery.replace('_', '-'), **options)
    assert not rp.satisfied(rd, POINT)
    assert pending_auditor(rd)


# ---------------------------------------------------------------- planted error, correction, acceptance, delivery

def test_planted_order_label_then_correction_reaches_acceptance_and_fills_the_template(tmp_path):
    rd = study(tmp_path, order=wrong_order())
    assert pending_auditor(rd)
    findings = run_auditor(rd, 'auditor-planted')
    [finding] = findings
    assert finding['evidence_class'] == 'code_check' and finding['materiality'] == 'A'
    assert 'sigma_table_mismatch' in finding['summary']
    assert report_for(rd, 'auditor-planted')['attestation'] == 'transport_attested'
    # The decider acts on the auditor's located finding; the rejected cycle cannot then be accepted.
    pr.submit_review(rd, role='physics_decider', actor_id='physicist', verdict='send_back',
                     summary='Normalization auditor: order label differs from the pinned table',
                     findings=[{'id': 'F-norm', 'summary': finding['summary'],
                                'evidence': [{'path': LEDGER, 'location': '$.sigma.order'}],
                                'check_ids': ['agreement'], 'required_paths': [LEDGER],
                                'required_stages': ['detector']}])
    with pytest.raises(ValueError, match='rejected cycle'):
        pr.submit_review(rd, role='physics_critic', actor_id='critic', verdict='accept', summary='x',
                         claim_scope='diagnostic')
    corrected = json.loads((rd / LEDGER).read_text())
    corrected['sigma']['order'] = corrected['target_normalization']['order'] = pinned_table()['convention']['order']
    atomic_json(rd / LEDGER, corrected)
    admitted = pr.authorize_correction(rd, actor_id='physicist', changed_paths=[LEDGER], stages=['detector'],
                                       recheck_checks=['agreement'])
    fresh = run_stage(rd, value=2)
    pr.open_cycle(rd, effective_settings=SETTINGS, stage_receipts=[fresh['attempt_record']],
                  check_results='inputs/checks.json', correction_id=admitted['correction_id'])
    assert run_auditor(rd, 'auditor-corrected') == []
    assert rp.satisfied(rd, POINT) and auditor_errors(rd) == []
    accept_all(rd, closes=['F-norm'])
    state = pr.status(rd)
    assert state['state'] == 'accepted' and state['claim_scope'] == 'diagnostic' and state['redos_used'] == 1
    record = fill(rd, tmp_path)
    assert record['acceptance']['accepted'] and record['acceptance']['claim_scope'] == 'diagnostic'
    assert not record['physics_validated']
    import yaml
    filled = yaml.safe_load((tmp_path / 'filled.yaml').read_text())
    assert [v['value'] for v in filled['dependent_variables'][0]['values']] == list(PRODUCER_VALUES)
    # Machine review throughout: delegated machine approval, transport-attested worker credit,
    # declared (unauthenticated) reviewer actors. No record claims a human review.
    assert json.loads((rd / 'inputs/checkin1_approval.json').read_text())['authority'] == 'delegated_machine'
    receipts = rp.checkin3_section(rd)['review_receipts']
    assert {r['attestation'] for r in receipts if r['review_point_id'] == POINT} == {'transport_attested'}
    assert 'not authenticated' in state['attestation']
    assert 'human' not in json.dumps(receipts).lower()


# ---------------------------------------------------------------- handoffs found in step 0 (failing tests)

@pytest.mark.xfail(strict=True, reason='the RDJ policy: the normalization-ledger check is not a '
                   'registered validator (data/rdj/policy.json measurement_validators), so the auditor\'s code_check '
                   'finding is advisory and cannot block CHECK-IN 2')
def test_planted_ledger_error_blocks_checkin2_acceptance(tmp_path):
    rd = study(tmp_path, order=wrong_order())
    assert run_auditor(rd, 'auditor-planted')
    assert any(e.code == 'blocking_finding' for e in auditor_errors(rd))


@pytest.mark.xfail(strict=True, reason='review_points: _facts reads contract keys '
                   '"delegated"/"delegation", but the delegation record is the contract\'s "autonomy" pin (as '
                   'gate_wiring._is_delegated reads it), so a delegated run gets attestation_min self: a host-attested '
                   'auditor receipt earns credit, and the plan point is advisory')
def test_review_points_recognize_the_actual_delegation(tmp_path):
    rd = study(tmp_path)
    assert 'autonomy' in json.loads((rd / 'inputs/task_contract.json').read_text())
    # Consequence: a host-attested auditor receipt earns specialist credit on a delegated run.
    auditor_receipt(rd, 'host-external', mode='host_attested_external', label='host_attested')
    assert not rp.satisfied(rd, POINT)
    assert rp._facts(rd)['delegated'] is True
    assert point(rd)['attestation_min'] == 'transport'


@pytest.mark.xfail(strict=True, reason='task_completion._accepted_review: '
                   'fill-template accepts physics_review acceptance without the epoch-two delivery decision gate, '
                   'so a pending blocking auditor point does not stop delivery')
def test_fill_template_refuses_while_the_auditor_point_is_pending(tmp_path):
    rd = study(tmp_path)
    accept_all(rd)
    assert pr.status(rd)['state'] == 'accepted' and pending_auditor(rd)
    with pytest.raises(ValueError):
        fill(rd, tmp_path)


def auditor_spec(rd, inputs, node='auditor-real'):
    card = role_registry.load(AUDITOR)
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node, 'attempt': 1,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': role_registry.card_sha256(AUDITOR)},
            'transport_preference': ['default'], 'inputs': inputs, 'declared_outputs': [],
            'budgets': {'max_turns': 40, 'max_wall_seconds': 1200, 'max_broker_calls': 200, 'max_cost_usd': 2.0},
            'final_record_schema': 'reviewer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': POINT, 'map_id': 'review:checkin2:' + CLAIM, 'rca_ticket': None}}


@pytest.mark.xfail(strict=True, reason='handoff U-3 (agent_worker owner): blindness is enforced only for '
                   'agent_graph.BLIND_GRAPH_ROLES, not from the card\'s requires.blind, so a raw producer input '
                   'reaches the auditor workspace')
def test_blind_auditor_refuses_a_raw_producer_input(tmp_path):
    rd = study(tmp_path)
    spec = auditor_spec(rd, [{'pin': {'path': RESULT, 'sha256': sha(rd / RESULT)}, 'as': 'inputs/result.json'}])
    with pytest.raises(ValueError, match='blind'):
        agent_worker.materialize(rd, spec)


# ---------------------------------------------------------------- seams on unmerged packages

def merged_review_graph():
    """The review.points module when present, else None."""
    try:
        from ravel.workflow.graphs import review
    except ImportError:
        return None
    return review if all(hasattr(review, n) for n in ('derive', 'write_packets', 'worker_spec', 'packet_path')) else None


def review_graph():
    review = merged_review_graph()
    if review is None:
        pytest.xfail('awaits the review.points graph (derive, write_packets, worker_spec)')
    return review


def auditor_item(rd):
    graph = review_graph()
    items = [i for i in graph.derive(rd, 'checkin2:' + CLAIM, 1)['items'] if i['role'] == AUDITOR]
    assert [i['point_id'] for i in items] == [POINT]
    return graph, items[0]


def test_auditor_packet_carries_no_producer_numbers_or_headline(tmp_path):
    rd = study(tmp_path)
    graph, item = auditor_item(rd)
    graph.write_packets(rd, [item])
    raw = (rd / graph.packet_path(item)).read_bytes()
    forbidden = [repr(v).encode() for v in PRODUCER_VALUES] + [HEADLINE.encode(), b'Headline']
    assert not any(token in raw for token in forbidden)
    packet = json.loads(raw)
    assert packet['role'] == AUDITOR and packet['subject_sha256'] == rp.subject_digest(rp._facts(rd), point(rd))
    spec = graph.worker_spec(rd, item)
    assert [i['pin']['path'] for i in spec['inputs']] == [graph.packet_path(item)]
    workspace = agent_worker.materialize(rd, spec)
    for path in (workspace / 'inputs').rglob('*'):
        if path.is_file():
            assert not any(token in path.read_bytes() for token in forbidden), path


def test_real_worker_receipt_earns_auditor_credit(tmp_path):
    """A receipt written by agent_worker itself, with no hand registration, earns the credit."""
    if 'review_subject' not in getattr(agent_worker, 'RECEIPT_VERSIONS', {}).get(2, ()):
        pytest.xfail('awaits U1-RECEIPT: agent_worker receipts carry no review_subject or execution_mode, '
                     'and the dispatcher registers no transport-verified label')
    rd = study(tmp_path)
    if merged_review_graph() is not None:
        graph, item = auditor_item(rd)
        graph.write_packets(rd, [item])
        spec = graph.worker_spec(rd, item)
    else:
        packet = rd / 'review/packets/auditor.json'
        atomic_json(packet, {'schema_version': 1, 'kind': 'review-item-packet', 'point_id': POINT, 'role': AUDITOR,
                             'subject_sha256': rp.subject_digest(rp._facts(rd), point(rd)), 'claim_id': CLAIM})
        spec = auditor_spec(rd, [{'pin': {'path': 'review/packets/auditor.json', 'sha256': sha(packet)},
                                  'as': 'inputs/review-packet.json'}])
    workspace = agent_worker.materialize(rd, spec)
    # The worker's declared review output goes through the broker, as a transport adapter writes it.
    from ravel.workflow import broker
    tool = broker.Broker(rd, workspace, node_id=spec['node_id'], attempt=spec['attempt'], allowed_actions=['write'],
                         max_calls=10)
    reply = tool.call({'call_id': 'put-review', 'action': 'write',
                       'args': {'path': 'outputs/review.json', 'content': json.dumps({'findings': []})}})
    assert reply['status'] == 'ok', reply
    receipt = agent_worker.finish(rd, spec, final={'completed': True, 'disposition': 'supported', 'findings': []},
                                  execution={'exit_status': 0, 'session_id': 'session-real', 'actor_id': 'actor-real',
                                             'attestation': 'transport_attested',
                                             'model': {'requested': None, 'observed': None, 'family': 'synthetic',
                                                       'effort': 'high'}})
    assert receipt['status'] == 'ok'
    assert rp.satisfied(rd, POINT)


# ---------------------------------------------------------------- live cell (root only)

@pytest.mark.skipif(os.environ.get('RAVEL_LIVE_CELL') != '1',
                    reason='live cell: root runs scripts/live/ordinary_review_cell.sh --run')
def test_live_cell_real_sandboxed_auditor_earns_machine_credit(tmp_path):
    if 'review_subject' not in getattr(agent_worker, 'RECEIPT_VERSIONS', {}).get(2, ()):
        pytest.xfail('awaits U1-RECEIPT: a real receipt cannot earn review credit yet')
    rd = study(tmp_path)
    atomic_json(rd / 'inputs/agent_preferences.json', {'transport_preference': ['claude-cli-worker']})
    graph, item = auditor_item(rd)
    graph.write_packets(rd, [item])
    spec = deepcopy(graph.worker_spec(rd, item))
    spec['budgets']['max_cost_usd'] = 2.0
    receipt = agent_worker.dispatch(rd, spec)
    summary = {'status': receipt['status'], 'failure': receipt.get('failure'), 'transport': receipt['transport'],
               'usage': receipt['usage'], 'model': receipt['model'], 'node_id': receipt['node_id']}
    out = os.environ.get('RAVEL_LIVE_CELL_OUT')
    if out:
        Path(out).write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    assert receipt['status'] == 'ok', summary
    report = report_for(rd, receipt['node_id'])
    assert report['attestation'] == 'transport_attested' and report['independent'], report
    assert rp.satisfied(rd, POINT)
    assert 'human' not in json.dumps(report).lower()
