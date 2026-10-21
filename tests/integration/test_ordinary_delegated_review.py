"""CB4-09: an ordinary delegated study reaches an accepted review with a blind normalization auditor.

The study is a synthetic, ordinary (non-science-mode) epoch-two run whose CHECK-IN 1 is a real
machine approval under the user's delegation; nothing mocks the approval envelope. The
auditor worker is mocked on the transport side only: it runs the card's must_check on the
run's ledger, writes a worker receipt, and the dispatcher's part is simulated by registering
that receipt with its verified label and the actor the dispatcher assigns at spawn. Every
credit decision is made by the merged review-point engine. No model, network or native tool is called; the live cell
(``RAVEL_LIVE_CELL=1``, run by root through scripts/live/ordinary-review-cell.sh) is the one
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
from bound_review import bound_review
from inert_dispatch import inert_dispatch  # noqa: F401
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
# The claim's generated-prediction basis also derives the conditional absolute-prediction staffing
# (spawn row K5: two re-derivers and a second, independent normalization auditor), blind like RP5.
SPECIALIST = 'K5:' + CLAIM
AUDITOR = 'normalization-auditor'
LEDGER = 'inputs/normalization_ledger.json'
RESULT = 'inputs/result.json'
# The ledger is an effective setting: the only file a bounded correction may change.
SETTINGS = ['inputs/settings.cfg', LEDGER]
# Producer numbers and headline that a blind auditor must never receive.
PRODUCER_VALUES = (12.3456789, 4.0987654)
HEADLINE = 'Headline: the synthetic signal yield is 16.4444443 events'
REVIEWERS = (('physics_critic', 'critic'), ('skeptical_verifier', 'skeptic'), ('physics_decider', 'physicist'))
VOTERS = ('physics-critic', 'skeptical-verifier', 'physics-decider')
TRANSPORT = 'synthetic-cli'


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
        # A recorded vote is the bound response of a dispatched role, and a delegated run consumes it only
        # when its delegation names accept_recommendation (the plan gate stays the one stubbed below).
        actions=['approve_plan', 'accept_recommendation'],
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


def point(rd, point_id=POINT):
    return next(p for p in rp.derive(rp._facts(rd)) if p['id'] == point_id)


def auditor_errors(rd):
    """review_points errors at CHECK-IN 2 acceptance that concern the auditor point."""
    errors = rp.gate_errors(rd, 'checkin2_accept', {'claim_id': CLAIM})
    return [e for e in errors if any(pin.startswith(POINT) for pin in e.pins)
            or e.code == 'blocking_finding']


def pending_auditor(rd):
    return any(e.code == 'review_point_pending' and POINT + ':' + AUDITOR + ':1' in e.pins for e in auditor_errors(rd))


def auditor_receipt(rd, node, *, findings=(), subject=None, mode='transport_attested_cli', label='transport_attested',
                    register=True, modified=False, point_id=POINT, role=AUDITOR, actor='dispatcher', session=None,
                    worker_session=None):
    """The receipt a sandboxed review worker leaves, registered as the dispatcher registers it.

    ``label`` is the dispatcher's transport re-verification. ``actor='dispatcher'`` is the
    identity the dispatcher assigns at spawn and registers in custody; ``'declared'`` is an
    ``actor_id`` the receipt states on its own; ``None`` leaves it out.
    """
    folder = rd / 'agent-work' / node / '1'
    folder.mkdir(parents=True)
    final = {'completed': True, 'disposition': 'not_supported' if findings else 'supported', 'findings': list(findings)}
    (folder / 'final.json').write_text(json.dumps(final, sort_keys=True))
    assigned = rdj_custody.actor_record(TRANSPORT, 'synthetic-model', worker_session or 'worker-session-' + node,
                                        node + '/1', family='synthetic-family')
    expected = rp.review_subject(rp._facts(rd), point(rd, point_id))
    receipt = {'schema_version': 3, 'kind': 'agent-worker-receipt', 'node_id': node, 'attempt': 1,
               'review_point_id': point_id, 'role': {'id': role}, 'status': 'ok', 'execution_mode': mode,
               'review_subject': {**expected, 'sha256': subject} if subject else expected,
               'session_id': session or 'session-' + node, 'run_tree': {'modified': modified},
               'actor_id': {'dispatcher': assigned['actor_id'], 'declared': 'actor-' + node, None: None}[actor],
               'transport': {'id': TRANSPORT, 'transport_kind': 'cli-worker'},
               'final_record': {'valid': True, 'path': 'final.json', 'sha256': sha(folder / 'final.json'),
                                'schema': 'reviewer.v1'},
               'model': {'family': 'synthetic-family'}}
    (folder / 'receipt.json').write_text(json.dumps(receipt, sort_keys=True))
    rel = (folder / 'receipt.json').relative_to(rd).as_posix()
    if register:
        rdj_custody.register_worker_receipt(rd, rel, verified_label=label,
                                            **({'actor': assigned} if actor == 'dispatcher' else {}))
    return rel


def vote(rd, role):
    """One RP4 voting reviewer: a separate worker session with its own dispatcher-assigned actor."""
    return auditor_receipt(rd, 'vote-' + role, point_id=f'RP4:{CLAIM}:{role}', role=role)


def voting_pending(rd):
    return sorted(pin for e in rp.gate_errors(rd, 'checkin2_accept', {'claim_id': CLAIM})
                  if e.code == 'review_point_pending' for pin in e.pins if pin.startswith('RP4:'))


@pytest.fixture
def review_delivery(monkeypatch):
    """The delivery gate reduced to the review-point provider's credit decisions.

    The R3 decision case with its human approval, the staffing rows and the request-fidelity
    map have their own suites; this module tests review credit after CHECK-IN 1. A test
    without this fixture runs the whole wired gate.
    """
    def credit_only(rundir, gate, action):
        return [e for e in rp.gate_errors(Path(rundir), gate, action)
                if e.code in ('review_point_pending', 'blocking_finding')]
    monkeypatch.setattr(gate_wiring, 'check_transition', credit_only)


def run_auditor(rd, node):
    """Mocked blind auditor: its must_check on the run's ledger, then its receipt.

    It reads only the pinned ledger; producer numbers and the headline never enter. The
    check result it cites is the one RAVEL's own run of the registered validator records.
    """
    from ravel.physics import normalization_ledger
    result, findings = audit_ledger(json.loads((rd / LEDGER).read_text()), check_id=node)
    recorded = normalization_ledger.record_check(rd, LEDGER, check_id=node)
    assert recorded['status'] == result['status'] and recorded['pins'] == [{'path': LEDGER, 'sha256': sha(rd / LEDGER)}]
    assert rdj_custody.check_result(rd, node)['producer'] == normalization_ledger.PRODUCER
    auditor_receipt(rd, node, findings=findings)
    return findings


def accept_all(rd, *, closes=()):
    """Critic, skeptic and decider accept through bound responses; a declared name is advice only."""
    for role, _ in REVIEWERS:
        bound_review(rd, role=role, verdict='accept', summary='Evidence supports the stated scope',
                     claim_scope='diagnostic', closes=list(closes))


def recorded_acceptance(rd, monkeypatch, *, template_gate_alone=False):
    """An acceptance already on record from bound votes alone, without the attested review-point
    receipts: the epoch-two receipt rule is kept off while it is recorded, as when it was written
    before acceptance needed those receipts. It stays readable; what it authorizes is tested.

    ``template_gate_alone`` keeps the legacy cycle's own receipt rule off for the rest of the
    test, so the template's decision gate is the only barrier left to observe.
    """
    if template_gate_alone:
        monkeypatch.setattr(rp, 'legacy_accept_refusal', lambda rundir: None)
        accept_all(rd)
    else:
        with monkeypatch.context() as patch:
            patch.setattr(rp, 'legacy_accept_refusal', lambda rundir: None)
            accept_all(rd)
    assert pr.status(rd)['state'] == 'accepted'


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
                                     'run_modified', 'declared_actor', 'no_actor'])
def test_forged_or_weak_receipts_earn_no_auditor_credit(tmp_path, forgery):
    rd = study(tmp_path)
    options = {'unregistered': {'register': False}, 'self_attested': {'label': None},
               'host_label': {'label': 'host_attested'}, 'human_manual': {'mode': 'human_manual'},
               'wrong_subject': {'subject': '0' * 64}, 'run_modified': {'modified': True},
               'declared_actor': {'actor': 'declared'}, 'no_actor': {'actor': None}}[forgery]
    auditor_receipt(rd, 'forged-' + forgery.replace('_', '-'), **options)
    assert not rp.satisfied(rd, POINT)
    assert pending_auditor(rd)


# ---------------------------------------------------------------- planted error, correction, acceptance, delivery

def test_planted_order_label_then_correction_reaches_acceptance_and_fills_the_template(tmp_path, review_delivery,
                                                                                       inert_dispatch):
    rd = study(tmp_path, order=wrong_order())
    assert pending_auditor(rd)
    findings = run_auditor(rd, 'auditor-planted')
    [finding] = findings
    assert finding['evidence_class'] == 'code_check' and finding['materiality'] == 'A'
    assert 'sigma_table_mismatch' in finding['summary']
    assert report_for(rd, 'auditor-planted')['attestation'] == 'transport_attested'
    # The auditor's located finding is recorded as a bound critic send-back (a decider vote is dispatched only
    # after both independent decisions; the correction below is still admitted by the decider's actor);
    # the rejected cycle cannot then be accepted.
    bound_review(rd, role='physics_critic', verdict='send_back',
                 summary='Normalization auditor: order label differs from the pinned table',
                 findings=[{'id': 'F-norm', 'summary': finding['summary'],
                            'evidence': [{'path': LEDGER, 'location': '$.sigma.order'}],
                            'check_ids': ['agreement'], 'required_paths': [LEDGER],
                            'required_stages': ['detector']}])
    with pytest.raises(ValueError, match='rejected cycle'):
        bound_review(rd, role='skeptical_verifier', verdict='accept', summary='x', claim_scope='diagnostic')
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
    # The voting points need three more worker sessions, each with its own dispatcher-assigned actor:
    # until they are credited no reviewer name can accept, and no template is filled.
    with pytest.raises(ValueError, match='attested receipts: .*RP4:C1:physics-critic'):
        accept_all(rd, closes=['F-norm'])
    with pytest.raises(ValueError):
        fill(rd, tmp_path)
    for role in VOTERS:
        vote(rd, role)
    assert voting_pending(rd) == []
    accept_all(rd, closes=['F-norm'])
    state = pr.status(rd)
    assert state['state'] == 'accepted' and state['claim_scope'] == 'diagnostic' and state['redos_used'] == 1
    record = fill(rd, tmp_path)
    assert record['acceptance']['review_accepted'] and record['acceptance']['claim_scope'] == 'diagnostic'
    assert record['acceptance']['delivery_label'] == 'diagnostic' and record['acceptance']['accepted'] is False
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

def test_planted_ledger_error_blocks_checkin2_acceptance(tmp_path, inert_dispatch):
    """U-1: the normalization-ledger check is a registered validator, so its failed result blocks."""
    rd = study(tmp_path, order=wrong_order())
    assert run_auditor(rd, 'auditor-planted')
    assert any(e.code == 'blocking_finding' for e in auditor_errors(rd))
    for role in VOTERS:
        vote(rd, role)
    # Every review point is credited; the auditor's evidence-bearing finding alone refuses acceptance.
    assert rp.satisfied(rd, POINT) and voting_pending(rd) == []
    with pytest.raises(ValueError, match='CHECK-IN 2 acceptance refused'):
        rp.accept_checkin2(rd, {'claim_id': CLAIM})


def sandboxed_auditor(rd, node):
    """A blind auditor as its sandbox leaves it: findings in its receipt, nothing registered in custody.

    The worker cannot reach the custody store, so it never records a check result. Its
    finding names the registered validator's check by id.
    """
    from ravel.physics import normalization_ledger
    _, findings = audit_ledger(json.loads((rd / LEDGER).read_text()), check_id=normalization_ledger.CHECK_ID)
    auditor_receipt(rd, node, findings=findings)
    return findings


def test_the_review_path_records_the_ledger_check_the_auditor_cannot(tmp_path, inert_dispatch):
    """U-1: RAVEL runs the registered validator itself; a failed result blocks with no help from the worker."""
    from ravel.physics import normalization_ledger
    rd = study(tmp_path, order=wrong_order())
    [finding] = sandboxed_auditor(rd, 'auditor-sandboxed')
    assert finding['evidence_locators'] == ['check:' + normalization_ledger.CHECK_ID]
    assert rdj_custody.rows(rd, 'checks') == []
    for role in VOTERS:
        vote(rd, role)
    assert rp.satisfied(rd, POINT) and voting_pending(rd) == []
    assert any(e.code == 'blocking_finding' for e in auditor_errors(rd))
    with pytest.raises(ValueError, match='CHECK-IN 2 acceptance refused'):
        rp.accept_checkin2(rd, {'claim_id': CLAIM})
    assert rdj_custody.rows(rd, 'review_acceptances') == []
    recorded = rdj_custody.check_result(rd, normalization_ledger.CHECK_ID)
    assert recorded['status'] == 'failed' and recorded['producer'] == normalization_ledger.PRODUCER
    assert recorded['pins'] == [{'path': LEDGER, 'sha256': sha(rd / LEDGER)}]
    # One record per ledger state: inspecting the gate again adds none.
    auditor_errors(rd)
    assert len(rdj_custody.rows(rd, 'checks')) == 1


def test_a_passing_ledger_makes_the_same_finding_unverified(tmp_path):
    """The worker's word alone never blocks: the trusted run of the validator decides."""
    from ravel.physics import normalization_ledger
    rd = study(tmp_path)
    finding = {'id': 'NA-claimed', 'summary': 'claimed ledger failure', 'materiality': 'A',
               'evidence_class': 'code_check', 'evidence_locators': ['check:' + normalization_ledger.CHECK_ID],
               'location': '$.sigma', 'status': 'open'}
    auditor_receipt(rd, 'auditor-claims', findings=[finding])
    assert not any(e.code == 'blocking_finding' for e in auditor_errors(rd))
    assert rdj_custody.check_result(rd, normalization_ledger.CHECK_ID)['status'] == 'passed'


def test_review_points_recognize_the_actual_delegation(tmp_path):
    """U-4: the contract's autonomy pin is the delegation record."""
    rd = study(tmp_path)
    assert 'autonomy' in json.loads((rd / 'inputs/task_contract.json').read_text())
    # Consequence: a host-attested auditor receipt earns specialist credit on a delegated run.
    auditor_receipt(rd, 'host-external', mode='host_attested_external', label='host_attested')
    assert not rp.satisfied(rd, POINT)
    assert rp._facts(rd)['delegated'] is True
    assert point(rd)['attestation_min'] == 'transport'
    plan = point(rd, 'RP1:plan')
    assert plan['blocking'] and plan['mode'] == 'voting' and plan['attestation_min'] == 'transport'


def test_a_delegation_recorded_at_checkin1_is_read_like_the_contract_pin(tmp_path):
    """U-4: the delegation record is the contract plus the CHECK-IN 1 transition beside it."""
    from executor_fixtures import plan, run_root
    root = run_root(tmp_path)
    plan(root, nodes=[{'id': 'N1', 'operation': 'literal-calculation', 'rung': 'smoke'}],
         claims=[{'id': CLAIM, 'kind': 'agreement'}])
    gate_wiring.record_run_init(root)
    contract = json.loads((root / 'inputs/task_contract.json').read_text())
    assert 'autonomy' not in contract and not rp._facts(root)['delegated']
    assert point(root, 'RP4:C1:physics-critic')['attestation_min'] == 'self'
    assert not point(root, 'RP1:plan')['blocking']
    # The contract is byte-bound to run_init, so a delegation granted in the CHECK-IN 1 response is this sidecar.
    binding = {'kind': 'checkin1_response', 'rundir': str(root)}
    declaration = root / 'inputs/checkin1-delegation.json'
    atomic_json(declaration, {'origin': 'checkin1_response', 'source_binding': binding})
    atomic_json(root / autonomy.TRANSITION, {
        'schema_version': 1, 'kind': 'checkin1_delegation_transition', 'objective_sha256': autonomy.objective(contract),
        'declaration': {'path': str(declaration), 'sha256': sha(declaration)}, 'source_binding': binding})
    facts = rp._facts(root)
    assert facts['delegated'] is True and gate_wiring._is_delegated(facts)
    assert point(root, 'RP4:C1:physics-critic')['attestation_min'] == 'transport'
    plan_point = point(root, 'RP1:plan')
    assert plan_point['blocking'] and plan_point['mode'] == 'voting' and plan_point['attestation_min'] == 'transport'
    # The delegated transition gates this run: the whole wired gate answers, not an empty list.
    assert gate_wiring.delegated_errors(root, 'delivery', gate_wiring.delivery_action(root))
    # A transition that does not belong to this contract is a refusal, never a quiet "not delegated".
    atomic_json(root / autonomy.TRANSITION, {
        'schema_version': 1, 'kind': 'checkin1_delegation_transition', 'objective_sha256': '0' * 64,
        'declaration': {'path': str(declaration), 'sha256': sha(declaration)}, 'source_binding': binding})
    with pytest.raises(ValueError, match='transition'):
        rp._facts(root)


def test_fill_template_refuses_while_the_auditor_point_is_pending(tmp_path, monkeypatch):
    """U-2: physics-review acceptance alone does not deliver a template."""
    rd = study(tmp_path)
    recorded_acceptance(rd, monkeypatch, template_gate_alone=True)
    assert pr.status(rd)['state'] == 'accepted' and pending_auditor(rd)
    with pytest.raises(ValueError, match='review_point_pending.*' + POINT):
        fill(rd, tmp_path)
    assert not (tmp_path / 'filled.yaml').exists()


def test_a_recorded_acceptance_fills_no_template_while_the_votes_are_pending(tmp_path, monkeypatch, review_delivery,
                                                                             inert_dispatch):
    rd = study(tmp_path)
    assert run_auditor(rd, 'auditor-ok') == []
    recorded_acceptance(rd, monkeypatch, template_gate_alone=True)
    with pytest.raises(ValueError, match='RP4:C1:physics-critic'):
        fill(rd, tmp_path)
    assert not (tmp_path / 'filled.yaml').exists()


def test_declared_reviewer_names_alone_never_reach_acceptance(tmp_path, capsys, inert_dispatch):
    """The legacy cycle names reviewers by policy; a declared name is retained advice and never an acceptance,
    and on an epoch-two run even a recorded (bound) acceptance needs the attested receipts."""
    rd = study(tmp_path)
    before = pr.status(rd)['events']
    for role, actor in REVIEWERS:
        # A declared name no longer reaches the receipt rule: it is retained as advice with no credit.
        advice = pr.submit_review(rd, role=role, actor_id=actor, verdict='accept', summary='Evidence supports the scope',
                                  claim_scope='diagnostic')
        assert advice['kind'] == 'review_advice' and advice['independent'] is False
    request = tmp_path / 'accept.json'
    request.write_text(json.dumps({'role': 'physics_critic', 'actor_id': 'critic', 'verdict': 'accept',
                                   'summary': 'Evidence supports the scope', 'claim_scope': 'diagnostic'}))
    capsys.readouterr()
    # The command route is the same declared call: retained advice, which is not a recorded vote (exit 1).
    assert pr.main(['--rundir', str(rd), 'review', '--request', str(request)]) == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed['kind'] == 'review_advice' and printed['independent'] is False
    state = pr.status(rd)
    assert state['state'] != 'accepted' and state['events'] == before
    # Receipts that are registered but carry only a declared actor change nothing.
    for role in VOTERS:
        auditor_receipt(rd, 'declared-' + role, point_id=f'RP4:{CLAIM}:{role}', role=role, actor='declared')
    auditor_receipt(rd, 'declared-auditor', actor='declared')
    with pytest.raises(ValueError, match='accept requires the attested receipts'):
        accept_all(rd)
    for role in VOTERS:
        vote(rd, role)
    assert run_auditor(rd, 'auditor-ok') == []
    accept_all(rd)
    assert pr.status(rd)['state'] == 'accepted'


def test_a_recorded_acceptance_stays_readable_and_authorizes_nothing_without_receipts(tmp_path, monkeypatch,
                                                                                      inert_dispatch):
    """Acceptance consumers apply the same rule to an acceptance already on record."""
    rd = study(tmp_path)
    recorded_acceptance(rd, monkeypatch)
    state = pr.status(rd)
    assert state['state'] == 'accepted' and state['claim_scope'] == 'diagnostic'
    errors = pr.gate_errors(rd, 'delivery')
    assert state['live_errors'] == errors
    assert errors and 'attested receipts' in errors[0] and POINT in errors[0]
    from ravel.workflow import review_enforcement
    assert review_enforcement.delivery_errors(rd) == errors
    with pytest.raises(ValueError):
        fill(rd, tmp_path)
    assert not (tmp_path / 'filled.yaml').exists()
    for role in VOTERS:
        vote(rd, role)
    assert run_auditor(rd, 'auditor-ok') == []
    assert pr.gate_errors(rd, 'delivery') == []


def test_the_pending_auditor_point_alone_stops_the_template(tmp_path, monkeypatch, review_delivery, inert_dispatch):
    rd = study(tmp_path)
    for role in VOTERS:
        vote(rd, role)
    recorded_acceptance(rd, monkeypatch, template_gate_alone=True)
    assert voting_pending(rd) == [] and pending_auditor(rd)
    with pytest.raises(ValueError, match='decision gate refuses delivery: review_points:review_point_pending.*' + POINT):
        fill(rd, tmp_path)
    assert not (tmp_path / 'filled.yaml').exists()
    assert run_auditor(rd, 'auditor-ok') == []
    acceptance = fill(rd, tmp_path)['acceptance']
    assert acceptance['review_accepted'] and acceptance['delivery_label'] == 'diagnostic'


def test_a_delegated_template_delivery_passes_the_whole_wired_gate(tmp_path, inert_dispatch):
    """With every review point credited, the R3 decision case still gates a delegated delivery."""
    rd = study(tmp_path)
    for role in VOTERS:
        vote(rd, role)
    assert run_auditor(rd, 'auditor-ok') == []
    assert rp.satisfied(rd, POINT) and voting_pending(rd) == []
    accept_all(rd)
    with pytest.raises(ValueError, match='decision gate refuses delivery: .*rdj:rdj_receipt_missing'):
        fill(rd, tmp_path)


def test_an_undelegated_template_delivery_keeps_every_review_gate_refusal(tmp_path, inert_dispatch):
    """U-2 on a run without delegation: the whole review-point provider speaks, not two of its codes."""
    from executor_fixtures import plan, run_root
    from test_review_points import credit_pending
    root = run_root(tmp_path)
    plan(root, claims=[{'id': CLAIM, 'kind': 'agreement'}])
    assert gate_wiring.record_run_init(root) and not rp._facts(root)['delegated']
    rp.approve(root)
    assert {e.code for e in rt.delivery_gate_errors(root)} == {'review_point_pending'}
    assert credit_pending(root)
    assert rt.delivery_gate_errors(root) == []
    # The approved review obligations no longer match the plan: reviews look complete, the gate still refuses.
    approval = root / 'inputs/review_points_approval.json'
    atomic_json(approval, {**json.loads(approval.read_text()), 'derived_points_sha256': '0' * 64})
    assert [e.code for e in rt.delivery_gate_errors(root)] == ['obligations_changed']
    rp.approve(root)
    assert rt.delivery_gate_errors(root) == []
    # An original requirement no accepted output maps to is a refusal of the same provider.
    contract = root / 'inputs/task_contract.json'
    document = json.loads(contract.read_text())
    prompt = document['prompt']
    document['task_requirements'] = {**document['task_requirements'], 'obligations': [
        {'id': 'Q1', 'evidence': [{'start': 0, 'end': 4, 'text': prompt[:4]}]}]}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(rp, '_facts', lambda rundir, facts=rp._facts(root): {**facts, 'contract': document})
        assert [e.code for e in rt.delivery_gate_errors(root)] == ['request_fidelity']


def auditor_spec(rd, inputs, node='auditor-real'):
    card = role_registry.load(AUDITOR)
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node, 'attempt': 1,
            'role': {'id': card['id'], 'version': card['version'], 'card_sha256': role_registry.card_sha256(AUDITOR)},
            'transport_preference': ['default'], 'inputs': inputs, 'declared_outputs': [],
            'budgets': {'max_turns': 40, 'max_wall_seconds': 1200, 'max_broker_calls': 200, 'max_cost_usd': 2.0},
            'final_record_schema': 'reviewer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': POINT, 'map_id': 'review:checkin2:' + CLAIM, 'rca_ticket': None}}


def test_blind_auditor_refuses_a_raw_producer_input(tmp_path):
    """U-3: the card's requires.blind governs every dispatch of the role."""
    rd = study(tmp_path)
    spec = auditor_spec(rd, [{'pin': {'path': RESULT, 'sha256': sha(rd / RESULT)}, 'as': 'inputs/result.json'}])
    with pytest.raises(ValueError, match='blind'):
        agent_worker.materialize(rd, spec)
    assert not agent_worker.workspace(rd, spec['node_id'], 1).exists()
    # The headline and another reviewer's packet are refused the same way; the ledger its card admits is copied.
    (rd / 'review/packets').mkdir(parents=True, exist_ok=True)
    atomic_json(rd / 'review/packets/other.json', {'schema_version': 1, 'kind': 'review-item-packet',
                                                    'point_id': 'RP4:' + CLAIM + ':physics-critic',
                                                    'role': 'physics-critic'})
    for index, rel in enumerate(('RESULT.md', 'review/packets/other.json')):
        refused = auditor_spec(rd, [{'pin': {'path': rel, 'sha256': sha(rd / rel)}, 'as': 'inputs/x'}],
                               node=f'auditor-refused-{index}')
        with pytest.raises(ValueError, match='blind'):
            agent_worker.materialize(rd, refused)
    admitted = auditor_spec(rd, [{'pin': {'path': LEDGER, 'sha256': sha(rd / LEDGER)}, 'as': 'inputs/ledger.json'}],
                            node='auditor-ledger')
    workspace = agent_worker.materialize(rd, admitted)
    assert (workspace / 'inputs/ledger.json').read_bytes() == (rd / LEDGER).read_bytes()


def test_a_blind_auditor_gets_no_producer_text_through_a_work_order(tmp_path):
    """Only the sealed order of a production node is a work order; a hand-written one never reaches a blind role."""
    rd = study(tmp_path)
    spec = auditor_spec(rd, [], node='auditor-ordered')
    atomic_json(rd / 'inputs/order.json', {'kind': 'work-order', 'node_id': 'auditor-ordered', 'notes': HEADLINE})
    spec['work_order'] = {'path': 'inputs/order.json', 'sha256': sha(rd / 'inputs/order.json')}
    with pytest.raises(ValueError, match='blind role.*sealed'):
        agent_worker.materialize(rd, spec)
    assert not agent_worker.workspace(rd, 'auditor-ordered', 1).exists()


def test_a_blind_auditor_gets_only_the_item_packet_the_review_graph_computes(tmp_path):
    """A hand-written packet for the same role and point is not the code-computed one.

    Both normalization-auditor seats (the core RP5 point and the conditional K5 staffing) obey it;
    the K5 packet carries its staffing policy, which is part of the computed packet too.
    """
    rd = study(tmp_path)
    graph, items = auditor_items(rd)
    graph.write_packets(rd, items)
    for item in items:
        genuine = json.loads((rd / graph.packet_path(item)).read_text())
        forged = {'extra-text': {**genuine, 'notes': HEADLINE},
                  'forged-findings': {**genuine, 'findings': {'RP4:C1:physics-critic': [{'summary': HEADLINE}]}},
                  'other-subject': {**genuine, 'subject_sha256': '0' * 64},
                  'renamed': genuine}
        if item['point_id'] == SPECIALIST:
            assert genuine['policy']['id'] == SPECIALIST and genuine['policy']['blind_to_producer_numbers'] is True
            forged.update({'policy-unblinded': {**genuine, 'policy': {**genuine['policy'],
                                                                     'blind_to_producer_numbers': False}},
                           'policy-dropped': {k: v for k, v in genuine.items() if k != 'policy'}})
        else:
            assert 'policy' not in genuine
        for name, document in forged.items():
            rel = f"review/packets/{name}-{item['point_id'].split(':')[0]}.json"
            atomic_json(rd / rel, document)
            spec = auditor_spec(rd, [{'pin': {'path': rel, 'sha256': sha(rd / rel)}, 'as': 'inputs/review-packet.json'}],
                                node='auditor-' + Path(rel).stem)
            with pytest.raises(ValueError, match='blind'):
                agent_worker.materialize(rd, spec)
            assert not agent_worker.workspace(rd, spec['node_id'], 1).exists()
        # The packet the graph wrote for this item is accepted, and a re-attach does not question it again.
        spec = graph.worker_spec(rd, item)
        workspace = agent_worker.materialize(rd, spec)
        assert json.loads((workspace / 'inputs/review-packet.json').read_text()) == genuine
        assert agent_worker.materialize(rd, spec) == workspace


def test_a_blind_auditor_gets_admitted_json_without_the_fields_its_card_withholds(tmp_path):
    """A raw JSON input passes the same field redaction as the card's projection."""
    rd = study(tmp_path)
    atomic_json(rd / 'inputs/context.json', {'kept': 1, 'headline': HEADLINE,
                                             'rows': [{'conclusion': HEADLINE, 'verdict': 'accept', 'kept': 2}]})
    pin = {'path': 'inputs/context.json', 'sha256': sha(rd / 'inputs/context.json')}
    spec = auditor_spec(rd, [{'pin': pin, 'as': 'inputs/context.json'}], node='auditor-context')
    workspace = agent_worker.materialize(rd, spec)
    raw = (workspace / 'inputs/context.json').read_bytes()
    assert json.loads(raw) == {'kept': 1, 'rows': [{'kept': 2}]} and b'Headline' not in raw
    # The copy is the dispatcher's record of what the worker was given: a re-attach verifies it.
    assert agent_worker.materialize(rd, spec) == workspace
    # A file with nothing to withhold is still copied byte for byte.
    plain = auditor_spec(rd, [{'pin': {'path': LEDGER, 'sha256': sha(rd / LEDGER)}, 'as': 'inputs/ledger.json'}],
                         node='auditor-plain')
    assert (agent_worker.materialize(rd, plain) / 'inputs/ledger.json').read_bytes() == (rd / LEDGER).read_bytes()


def test_a_blind_projection_never_carries_a_forbidden_subject(tmp_path):
    """An explicit packet subject passes the card's forbidden classes and field redaction like any other file."""
    from ravel.workflow import review_projection
    rd = study(tmp_path)
    (rd / 'outputs').mkdir(exist_ok=True)
    atomic_json(rd / 'outputs/result.json', {'values': list(PRODUCER_VALUES)})
    for subject in ('outputs/result.json', RESULT, 'RESULT.md'):
        with pytest.raises(review_projection.ProjectionRefused) as refused:
            review_projection.build(rd, AUDITOR, subjects=[subject])
        assert refused.value.code == 'subject_forbidden'
    atomic_json(rd / 'inputs/context.json', {'kept': 1, 'headline': HEADLINE})
    manifest, files = review_projection.build(rd, AUDITOR, subjects=['inputs/context.json'])
    carried = b''.join(raw for _, raw in files)
    assert b'Headline' not in carried and not any(repr(v).encode() in carried for v in PRODUCER_VALUES)
    assert [s['source_path'] for s in manifest['subjects']] == ['inputs/context.json']


def test_a_blind_role_is_dispatched_only_against_its_current_readable_card(tmp_path, monkeypatch):
    rd = study(tmp_path)
    stale = auditor_spec(rd, [], node='auditor-stale')
    stale['role']['card_sha256'] = '1' * 64
    with pytest.raises(ValueError, match='blind role card'):
        agent_worker.materialize(rd, stale)
    # A registered card that cannot be read is never treated as a card without blindness.
    raw = auditor_spec(rd, [{'pin': {'path': RESULT, 'sha256': sha(rd / RESULT)}, 'as': 'inputs/result.json'}],
                       node='auditor-unreadable')

    def unreadable(role_id, **options):
        raise OSError('card file is unreadable')
    monkeypatch.setattr(role_registry, 'load', unreadable)
    with pytest.raises(ValueError, match='card'):
        agent_worker.materialize(rd, raw)
    assert not agent_worker.workspace(rd, 'auditor-unreadable', 1).exists()


def test_a_card_blind_role_is_never_launched_with_an_action_beyond_its_card(tmp_path):
    """One blind flag for the whole dispatch: the supervisor reads the card's blindness, not only the graph's."""
    from worker_supervision import descriptor, supervised
    rd = study(tmp_path)
    graph, items = auditor_items(rd)
    graph.write_packets(rd, items)
    card = role_registry.load(AUDITOR)
    for item in items:
        spec = graph.worker_spec(rd, item)
        put_review(rd, spec)
        record = agent_worker._record(rd, spec['node_id'], 1)
        assert record['card_blind'] and not record['blind'], item['point_id']
        assert record['blind_actions'] == sorted({'read', 'write', *card['tools']['ravel_actions']})
        launch = {**descriptor(transport_id=TRANSPORT), 'allowed_actions': ['read', 'write', 'exec']}
        session = 'session-wide-' + item['point_id'].replace(':', '-')
        receipt = supervised(rd, spec, final=FINAL, session=session, launch_spec=launch)
        assert receipt['status'] == 'refused' and receipt['failure']['code'] == 'blind_action_refused', item['point_id']
    assert not rp.satisfied(rd, POINT)
    assert AUDITOR in specialist_missing(rd)


def test_the_launch_toolbelt_of_a_card_blind_role_stays_inside_its_card():
    from ravel.workflow import transport_registry
    from ravel.workflow.transports import cli_worker
    document = next(d for d in sorted(transport_registry.all_declarations(), key=lambda d: d['id'])
                    if d['transport_kind'] == 'cli-worker')
    card = role_registry.load(AUDITOR)
    card['tools']['ravel_actions'] = []
    wide = deepcopy(card)
    wide['tools']['ravel_actions'] = role_registry.load(AUDITOR)['tools']['ravel_actions']
    belt = cli_worker.toolbelt_for(wide, document, False, blind_actions=agent_worker.blind_actions(card))
    actions = {t['executes_through']['action'] for t in belt['tools']} - {None}
    assert actions <= {'read', 'write'} and any(o['reason'] == 'blind_role' for o in belt['omitted'])


# ---------------------------------------------------------------- the review graph and the real receipt

def review_graph():
    from ravel.workflow.graphs import review
    return review


def auditor_items(rd):
    """Every normalization-auditor item the review graph dispatches at the claim's CHECK-IN 2."""
    graph = review_graph()
    items = [i for i in graph.derive(rd, 'checkin2:' + CLAIM, 1)['items'] if i['role'] == AUDITOR]
    assert [i['point_id'] for i in items] == [POINT, SPECIALIST]
    assert all(i['n'] == 1 and i['claim_id'] == CLAIM for i in items)
    return graph, items


def auditor_item(rd):
    """The core RP5 auditor item; the conditional K5 seat is a separate item with its own credit."""
    graph, items = auditor_items(rd)
    return graph, items[0]


def specialist_missing(rd):
    """The roles the conditional K5 staffing still owes."""
    from ravel.workflow import spawn_rows
    [row] = [r for r in spawn_rows.report(rd) if r['id'] == SPECIALIST]
    return [entry['role'] for entry in row['roles']] if row['pending'] else []


def test_auditor_packet_carries_no_producer_numbers_or_headline(tmp_path):
    rd = study(tmp_path)
    graph, items = auditor_items(rd)
    graph.write_packets(rd, items)
    forbidden = [repr(v).encode() for v in PRODUCER_VALUES] + [HEADLINE.encode(), b'Headline']
    facts = rp._facts(rd)
    population = {p['id']: p for p in rp.population(facts)}
    assert population[POINT] == point(rd)
    for item in items:
        raw = (rd / graph.packet_path(item)).read_bytes()
        assert not any(token in raw for token in forbidden), item['point_id']
        packet = json.loads(raw)
        assert packet['role'] == AUDITOR and packet['point_id'] == item['point_id']
        assert packet['subject_sha256'] == rp.subject_digest(facts, population[item['point_id']])
        spec = graph.worker_spec(rd, item)
        assert [i['pin']['path'] for i in spec['inputs']] == [graph.packet_path(item)]
        workspace = agent_worker.materialize(rd, spec)
        for path in (workspace / 'inputs').rglob('*'):
            if path.is_file():
                assert not any(token in path.read_bytes() for token in forbidden), path


def test_real_worker_receipt_earns_auditor_credit(tmp_path):
    """A receipt written by agent_worker itself, with no hand registration, earns the credit."""
    from worker_supervision import review_packet
    rd = study(tmp_path)
    graph, item = auditor_item(rd)
    graph.write_packets(rd, [item])
    spec = graph.worker_spec(rd, item)
    # The review graph hands the dispatcher the card's projection of the item; credit needs that packet.
    receipt = finish_as_dispatcher(rd, spec, 'session-real',
                                   packet=review_packet(rd, POINT, AUDITOR, item['n'], round_=item['round']))
    assert receipt['status'] == 'ok' and receipt['schema_version'] == 3
    assert receipt['execution_mode'] == 'transport_attested_cli' and receipt['review_subject']['scope'] == 'claim:' + CLAIM
    report = report_for(rd, spec['node_id'])
    assert report['attestation'] == 'transport_attested' and report['independent']
    assert rp.satisfied(rd, POINT)
    # The RP5 receipt is the RP5 seat's; the conditional K5 auditor seat still needs its own receipt.
    assert AUDITOR in specialist_missing(rd)


def put_review(rd, spec, packet=None):
    """The worker's declared review output goes through the broker, as a transport adapter writes it."""
    from ravel.workflow import broker
    workspace = agent_worker.materialize(rd, spec, packet=packet)
    tool = broker.Broker(rd, workspace, node_id=spec['node_id'], attempt=spec['attempt'], allowed_actions=['write'],
                         max_calls=10)
    reply = tool.call({'call_id': 'put-review', 'action': 'write',
                       'args': {'path': 'outputs/review.json', 'content': json.dumps({'findings': []})}})
    assert reply['status'] == 'ok', reply


FINAL = {'completed': True, 'disposition': 'supported', 'findings': []}
EXECUTION = {'exit_status': 0, 'attestation': 'transport_attested',
             'transport': {'id': TRANSPORT, 'transport_kind': 'cli-worker'},
             'model': {'requested': 'synthetic-model', 'observed': None, 'family': 'synthetic', 'effort': 'high'}}


def finish_as_dispatcher(rd, spec, session, packet=None):
    """One review worker through the dispatcher's transport path: launch, supervision, observation, receipt."""
    from worker_supervision import descriptor, supervised
    put_review(rd, spec, packet)
    return supervised(rd, spec, final=FINAL, session=session, launch_spec=descriptor(transport_id=TRANSPORT),
                      **({'packet': packet} if packet is not None else {}))


def finish_as_host(rd, spec, session, *, bind, declared=None):
    """The host completes the worker itself: no launch, no supervisor, only what it states."""
    put_review(rd, spec)
    if bind:
        agent_worker.bind_actor(rd, spec['node_id'], spec['attempt'], transport_id=TRANSPORT,
                                model_id='synthetic-model', family='synthetic')
    return agent_worker.finish(rd, spec, final=FINAL, execution={
        **deepcopy(EXECUTION), 'session_id': session, **({'actor_id': declared} if declared else {})})


def test_a_host_authored_completion_earns_no_auditor_credit(tmp_path):
    """A coordinator that binds an actor and writes the completion itself was observed by no transport."""
    rd = study(tmp_path)
    graph, item = auditor_item(rd)
    graph.write_packets(rd, [item])
    spec = graph.worker_spec(rd, item)
    receipt = finish_as_host(rd, spec, 'anything', bind=True)
    assert receipt['status'] == 'ok' and receipt['schema_version'] == 3 and receipt['actor_id']
    assert receipt['attestation'] == 'host_attested'
    report = report_for(rd, spec['node_id'])
    assert report['attestation'] == 'self_attested' and not report['independent']
    assert not rp.satisfied(rd, POINT) and pending_auditor(rd)


def test_a_worker_cannot_declare_its_own_actor(tmp_path):
    """Without the dispatcher's assignment the receipt has no actor, whatever the execution states."""
    rd = study(tmp_path)
    graph, item = auditor_item(rd)
    graph.write_packets(rd, [item])
    receipt = finish_as_host(rd, graph.worker_spec(rd, item), 'session-declared', bind=False,
                             declared='actor-declared')
    assert receipt['status'] == 'ok' and receipt['actor_id'] is None
    report = report_for(rd, receipt['node_id'])
    assert not report['independent'] and report['advisory'] == 'actor_unassigned'
    assert not rp.satisfied(rd, POINT) and pending_auditor(rd)


# ---------------------------------------------------------------- live cell (root only)

@pytest.mark.skipif(os.environ.get('RAVEL_LIVE_CELL') != '1',
                    reason='live cell: root runs scripts/live/ordinary-review-cell.sh --run')
def test_live_cell_real_sandboxed_auditor_earns_machine_credit(tmp_path):
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
