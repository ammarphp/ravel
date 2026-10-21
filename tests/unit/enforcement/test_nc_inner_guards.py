"""Inner guards (G01-G14): the named code checks the controller keeps, attacked directly.

Each case drives the guard's own entry with one mutation of a valid fictional fixture, asserts
the refusal (or the recorded decision, for the labelled G13 and G14) from outside the guard, and
runs a positive control through the same entry. That these guards are reachable only through the
controller path is asserted by the controller and switch cases, not here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from nc_adversary import InstalledWorker
from nc_cases import INSTALLED, case, controller_installed
from nc_mutations import Mutation, constant, passes_through, register, returns

UNREGISTERED_ROLE = 'fictional-unregistered-role'


# ---------------------------------------------------------------- G01 role resolution

@case('G01', binding=INSTALLED)
def test_G01_an_unregistered_role_is_refused_at_resolution_before_any_worker_starts(nc):
    from ravel.workflow import agent_worker, role_registry
    from ravel.workflow.transports import cli_worker
    worker = InstalledWorker(nc)
    worker.scenario({'actions': [{'op': 'call', 'name': 'ws_write',
                                  'arguments': {'path': 'outputs/result.txt', 'content': 'x'}}],
                     'final': {'completed': True, 'summary': 'x'}})
    spec = worker.spec(role='analysis-author')
    # The adversary keeps a valid card digest and names a role the registry does not hold.
    spec['role'] = dict(spec['role'], id=UNREGISTERED_ROLE)
    ws = agent_worker.workspace(worker.run, spec['node_id'], spec['attempt'])
    for folder in ('inputs', 'outputs', 'scratch', 'calls'):
        (ws / folder).mkdir(parents=True)
    with pytest.raises(ValueError, match='unregistered role'):
        cli_worker.prepare_launch(worker.run, spec, ws)
    assert not (ws / 'scratch' / 'prompt.txt').exists() and worker.broker_calls() == []
    # Positive control: the registered role resolves through the same entry to a launch descriptor.
    good = worker.spec(role='analysis-author', node_id='nc.control')
    good_ws = agent_worker.workspace(worker.run, good['node_id'], good['attempt'])
    for folder in ('inputs', 'outputs', 'scratch', 'calls'):
        (good_ws / folder).mkdir(parents=True)
    descriptor = cli_worker.prepare_launch(worker.run, good, good_ws)
    assert descriptor['argv'][0] == worker.probe['executable_path']
    assert role_registry.card_sha256('analysis-author') == good['role']['card_sha256']


def _substitute_unknown_roles(original):
    def identity(role_id, document):
        if role_id not in document['roles'] and role_id not in document['aliases']:
            role_id = 'analysis-author'
        return original(role_id, document)
    return identity


register(Mutation('G01', 'ravel.workflow.role_registry:_identity', _substitute_unknown_roles, ('G01',),
                  why='role resolution substitutes a registered card for an unknown id'))


# ---------------------------------------------------------------- G02 / G11 decision gate

def _epoch_two_run(root):
    plan = {'agent_layer_epoch': 2, 'delegated': True, 'nodes': [], 'claims': [], 'edges': []}
    path = root / 'inputs' / 'plan.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan))
    import hashlib
    pin = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (root / 'inputs' / 'task_contract.json').write_text(json.dumps(
        {'agent_layer_epoch': 2, 'delegated': True, 'request_plan': pin}))
    return root


def _without_module(nc, module_name):
    from importlib import util
    real = util.find_spec
    nc.patch.setattr(util, 'find_spec', lambda name, *a: None if name == module_name else real(name, *a))


@case('G02', binding=INSTALLED)
def test_G02_a_missing_required_provider_refuses_the_epoch_two_gate(nc):
    from ravel.workflow import decision_gate
    run = _epoch_two_run(nc.root / 'run')
    action = {'digest': 'a' * 64, 'node_id': 'N1'}
    # Positive control: with every provider installed, no provider is reported inactive.
    assert not [e for e in decision_gate.check(run, 'unblind', action) if e.code == 'provider_inactive']
    # A run-tree copy of the provider registry that drops the provider is not read.
    registry = json.loads((decision_gate.files('ravel') / 'data/gates/providers.json').read_text())
    registry['required_providers'] = {}
    registry['providers'] = [p for p in registry['providers'] if p['id'] != 'rdj']
    for relative in ('gates/providers.json', '.ravel/providers.json', 'inputs/providers.json'):
        nc.write_json(f'run/{relative}', registry)
    _without_module(nc, 'ravel.workflow.rdj_loop')
    errors = decision_gate.check(run, 'unblind', action)
    inactive = [e for e in errors if e.code == 'provider_inactive']
    assert [e.provider for e in inactive] == ['rdj'] and inactive[0].pins == ('provider:rdj',)
    assert errors, 'a missing required provider must refuse, never pass as an empty check'


def _drop_required_providers(original):
    def registry():
        document = original()
        document['required_providers'] = {}
        document['required_scopes'] = []
        return document
    return registry


register(Mutation('G02', 'ravel.workflow.decision_gate:_registry', _drop_required_providers, ('G02',),
                  why='the gate stops requiring its providers'))


@case('G11', binding=INSTALLED)
def test_G11_an_epoch_one_layout_cannot_pass_unblind_or_spend_above_ceiling(nc):
    from ravel.workflow import decision_gate
    legacy = nc.root / 'legacy'
    legacy.mkdir()
    (legacy / 'task_contract.json').write_text(json.dumps({'schema_version': 1}))
    for gate in ('unblind', 'spend_above_ceiling'):
        errors = decision_gate.check(legacy, gate, {'digest': 'a' * 64})
        assert [e.code for e in errors] == ['epoch_gate_unsupported'], gate
        assert errors[0].pins == ('contract:agent_layer_epoch',)
    # Positive control: an epoch-two run reaches the providers instead of the epoch refusal.
    run = _epoch_two_run(nc.root / 'run')
    errors = decision_gate.check(run, 'unblind', {'digest': 'a' * 64, 'node_id': 'N1'})
    assert 'epoch_gate_unsupported' not in [e.code for e in errors]


register(Mutation('G11', 'ravel.workflow.decision_gate:EPOCH_TWO_ONLY', constant(frozenset()), ('G11',),
                  why='epoch-one layouts keep a legacy decision for every gate'))


# ---------------------------------------------------------------- G07 aggregate reservations

LIMITS = {'max_seconds': 100, 'max_events': 1000, 'max_children': 3}

RACE = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from ravel.workflow import completion_budget
try:
    completion_budget.reserve(sys.argv[2], sys.argv[3], {"max_seconds": 60, "max_events": 10}, json.loads(sys.argv[4]))
    print("granted")
except ValueError as exc:
    print("refused:" + str(exc))
'''


@case('G07', binding=INSTALLED)
def test_G07_child_reservations_above_the_aggregate_ceiling_are_refused_under_the_lock(nc):
    from ravel.workflow import completion_budget
    from nc_cases import ROOT
    root = nc.root / 'parent'
    (root / 'inputs').mkdir(parents=True)
    record = completion_budget.reserve(root, 'child-a', {'max_seconds': 60, 'max_events': 500}, LIMITS)
    assert [c['child'] for c in record['children']] == ['child-a']  # positive control
    ledger = root / 'inputs' / 'delegation_reservations.json'
    before = ledger.read_bytes()
    with pytest.raises(ValueError, match='aggregate delegated ceiling exceeded'):
        completion_budget.reserve(root, 'child-b', {'max_seconds': 41, 'max_events': 10}, LIMITS)
    with pytest.raises(ValueError, match='aggregate delegated ceiling exceeded'):
        completion_budget.reserve(root, 'child-c', {'max_seconds': 1, 'max_events': 501}, LIMITS)
    assert ledger.read_bytes() == before
    # Two processes race for the last 40 seconds: exactly one reservation is granted.
    race = nc.root / 'race'
    (race / 'inputs').mkdir(parents=True)
    completion_budget.reserve(race, 'seed', {'max_seconds': 0, 'max_events': 0}, LIMITS)
    procs = [subprocess.Popen([sys.executable, '-B', '-c', RACE, str(ROOT / 'src'), str(race), f'racer-{n}',
                               json.dumps(LIMITS)], stdout=subprocess.PIPE, text=True) for n in range(2)]
    outcomes = sorted(p.communicate(timeout=60)[0].strip() for p in procs)
    assert outcomes == ['granted', 'refused:aggregate delegated ceiling exceeded'], outcomes
    children = json.loads((race / 'inputs' / 'delegation_reservations.json').read_text())['children']
    assert sum(c['max_seconds'] for c in children) <= LIMITS['max_seconds']


def _no_ceiling(original):
    def reserve(root, child, requested, limits):
        widened = {k: 10 ** 9 for k in limits}
        from pathlib import Path
        path = Path(root) / 'inputs/delegation_reservations.json'
        if path.exists():
            document = json.loads(path.read_text())
            document['limits'] = widened
            path.write_text(json.dumps(document))
        return original(root, child, requested, widened)
    return reserve


register(Mutation('G07', 'ravel.workflow.completion_budget:reserve', _no_ceiling, ('G07',),
                  why='the aggregate ceiling is not compared'))


# ---------------------------------------------------------------- G03 blind reviewer packet

BLIND_REVIEWERS = ('critic', 'verifier', 'physics_critic', 'skeptical_verifier', 'rdj_critic', 'rdj_verifier')
PACKET_REFUSAL = 'critic and verifier require a matching digest-bound review packet'


class _ModelTransport:
    """The control object an agent host calls through: a model call is recorded, never performed."""

    def __init__(self):
        self.calls = []

    def cancelled(self):
        return False

    def check_cancelled(self):
        return None

    def call(self, label, kind, request, function, output_tokens=0):
        self.calls.append({'label': label, 'kind': kind})
        raise AssertionError(f'a model transport call was made: {label}')


def _review_packet(nc, role):
    """A synthetic role packet with no artifacts, pinned by the digest of its manifest."""
    from ravel.workflow import execution
    directory = nc.root / f'{role}-packet'
    (directory / 'artifacts').mkdir(parents=True)
    body = {'schema_version': 1, 'role': role, 'run_id': 'fictional-run', 'cycle_id': 'fictional-cycle',
            'source_event_sha256': '0' * 64, 'artifacts': [], 'omissions': [], 'findings': [], 'reviews': []}
    manifest = {**body, 'sha256': execution.digest(body)}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return {'path': str(directory), 'manifest_sha256': manifest['sha256']}


@case('G03', binding=INSTALLED)
def test_G03_a_blind_reviewer_without_a_matching_packet_is_refused_before_any_model_call(nc):
    from ravel.workflow import agent_host as host
    from test_agent_host import node, request
    transport = _ModelTransport()
    for role in BLIND_REVIEWERS:
        unpinned = node(role=role)  # a reviewer node whose context is bound to no review packet
        with pytest.raises(host.HostFailure, match=PACKET_REFUSAL):
            host.AgentHost().execute(unpinned, request(unpinned), transport)
        with pytest.raises(host.HostFailure, match=PACKET_REFUSAL):
            host.AgentHost().prepare_model_context(unpinned, request(unpinned))
    assert transport.calls == []
    # A packet that does not match the node is no better than none: another role's packet, a changed digest.
    pin = _review_packet(nc, 'critic')
    foreign = node(role='skeptical_verifier', packet=pin)
    with pytest.raises(host.HostFailure, match='review packet role does not match node role'):
        host.AgentHost().prepare_model_context(foreign, request(foreign))
    altered = node(role='physics_critic', packet=dict(pin, manifest_sha256='f' * 64))
    with pytest.raises(host.HostFailure, match='role packet differs from creation digest'):
        host.AgentHost().prepare_model_context(altered, request(altered))
    # Positive control: the same entry builds the context of a reviewer bound to its matching packet.
    bound = node(role='physics_critic', packet=pin)
    context = host.AgentHost().prepare_model_context(bound, request(bound))['context']
    assert context['role'] == 'physics_critic'
    assert context['review_packet']['manifest_sha256'] == pin['manifest_sha256']
    assert 'input_artifacts' not in context and transport.calls == []


def _packet_assumed_present(original):
    def packet(self, node, *, _observations=None):
        found = original(self, node, _observations=_observations)
        return {'manifest_sha256': '0' * 64, 'context': {}, 'artifacts': []} if found is None else found
    packet.__wrapped__ = original
    return packet


register(Mutation('G03', 'ravel.workflow.agent_host:AgentHost._packet', _packet_assumed_present, ('G03',),
                  why='a reviewer context without a pinned packet is treated as having one'))


# ---------------------------------------------------------------- G04 / G09 review enforcement at a stage boundary

def _reviewed_run(nc):
    """A synthetic run with a recorded stage attempt and its check packet, as the review suite builds it."""
    from ravel.workflow import physics_review as review, workflow_state
    from ravel.workflow.state_io import atomic_json
    from test_physics_review import check_packet, make_attempt, policy
    root = nc.root / 'run'
    (root / 'inputs').mkdir(parents=True)
    atomic_json(root / review.POLICY, policy())
    atomic_json(root / 'inputs/checkin1_approval.json', {'fixture': 'approval verification is tested elsewhere'})
    nc.patch.setattr(workflow_state, 'approval_input_paths', lambda rd: [str(Path(rd) / review.POLICY)])
    nc.patch.setattr(workflow_state, 'verify_approval', lambda *a, **kw: [])
    (root / 'inputs/settings.cfg').write_text('efficiency=0.8\n')
    (root / 'inputs/held-fixed.txt').write_text('fixed recipe\n')
    atomic_json(root / 'inputs/reference.json', {'reference': 1})
    record = make_attempt(root)
    check_packet(root, record)
    return root, record


def _next_stage(root, record):
    """The positional arguments of a further launch of the recorded stage, with fresh outputs."""
    return (root, 'detector', record['command'], record['inputs'], ['outputs/future.json'], [], str(root),
            'logs/future.log')


@case('G04', binding=INSTALLED)
def test_G04_a_stage_is_refused_while_the_active_review_has_blocking_errors(nc):
    from ravel.workflow import review_enforcement
    from test_physics_review import accept, opened
    root, record = _reviewed_run(nc)
    opened((root, record))
    stage = _next_stage(root, record)
    ledger = (root / 'execution_state.json').read_bytes()
    for resume in (False, True):
        with pytest.raises(ValueError, match='scientific review blocks stage: scientific review is awaiting_review'):
            review_enforcement.before_stage(*stage, resume=resume)
    assert (root / 'execution_state.json').read_bytes() == ledger and not (root / 'logs/future.log').exists()
    # Positive control: once all three reviewers accept, the same stage is admitted at the same entry.
    accept(root)
    for resume in (False, True):
        assert review_enforcement.before_stage(*stage, resume=resume) is None


register(Mutation('G04', 'ravel.workflow.physics_review:gate_errors', returns([]), ('G04',),
                  why='the review reports no blocking error to the stage boundary'))


@case('G09', binding=INSTALLED)
def test_G09_an_observation_session_cannot_admit_a_fresh_launch(nc):
    from ravel.workflow import execution, review_enforcement
    from test_physics_review import accept, opened
    root, record = _reviewed_run(nc)
    opened((root, record))
    accept(root)
    stage = _next_stage(root, record)
    ledger = (root / 'execution_state.json').read_bytes()
    session = execution._validation_session(root)
    try:
        with pytest.raises(ValueError, match='observation session is confined to accepted reuse; '
                                             'fresh launch admission required'):
            review_enforcement.before_stage(*stage, resume=False, _session=session)
        assert (root / 'execution_state.json').read_bytes() == ledger and not (root / 'logs/future.log').exists()
        # Positive control: the same session serves accepted reuse.
        assert review_enforcement.before_stage(*stage, resume=True, _session=session) is None
    finally:
        session.close()
    # The accepted review itself admits a fresh launch, so the refusal came from the session's confinement.
    assert review_enforcement.before_stage(*stage, resume=False) is None


def _session_reads_as_reuse(original):
    def before_stage(root, stage, command, inputs, outputs, depends_on, cwd, log, *, resume=False,
                     helper_declaration=None, _session=None):
        return original(root, stage, command, inputs, outputs, depends_on, cwd, log,
                        resume=resume or _session is not None, helper_declaration=helper_declaration,
                        _session=_session)
    before_stage.__wrapped__ = original
    return before_stage


register(Mutation('G09', 'ravel.workflow.review_enforcement:before_stage', _session_reads_as_reuse, ('G09',),
                  why='a fresh launch admission through an observation session is read as accepted reuse'))


# ---------------------------------------------------------------- G05 launch-time authority

def _approved_native_run(nc):
    """A synthetic native plan approved for the smoke rung; the fictional build holds no real tool."""
    from ravel.physics import native_pipeline as pipeline
    from test_native_dispatch import approve_fixture, configuration, synthetic_build
    synthetic_build(nc.root, nc.patch)
    run = nc.root / 'run'
    run.mkdir()
    approve_fixture(pipeline.build_execution_plan(run, configuration(run)))
    return run


@case('G05', binding=INSTALLED)
def test_G05_launch_authority_changed_after_approval_is_refused_at_capture(nc):
    from ravel.workflow import launch_authorization
    run = _approved_native_run(nc)
    approval = run / 'inputs/checkin1_approval.json'
    approved_sha = hashlib.sha256(approval.read_bytes()).hexdigest()
    # Positive control: the unchanged authority is captured and the snapshot pins the approval receipt.
    assert launch_authorization._capture(run, 'smoke')['approval']['sha256'] == approved_sha
    # An approved generator card is edited after the approval.
    card = run / 'cards/run.dat'
    approved_card = card.read_bytes()
    card.write_bytes(approved_card + b'# unapproved revision\n')
    with pytest.raises(ValueError, match='launch authorization refused: .*cards/run.dat'):
        launch_authorization._capture(run, 'smoke')
    card.write_bytes(approved_card)
    assert launch_authorization._capture(run, 'smoke')['approval']['sha256'] == approved_sha
    # The approval receipt itself is missing at launch time.
    receipt = approval.read_bytes()
    approval.unlink()
    with pytest.raises(ValueError, match='launch authorization refused'):
        launch_authorization._capture(run, 'smoke')
    approval.write_bytes(receipt)
    # The launch asks for a rung above the one the approval covers.
    with pytest.raises(ValueError, match='launch authorization refused'):
        launch_authorization._capture(run, 'full')
    assert launch_authorization._capture(run, 'smoke')['approval']['sha256'] == approved_sha
    assert not (run / launch_authorization.JOURNAL).exists()


register(Mutation('G05', 'ravel.workflow.workflow_state:verify_approval', returns([]), ('G05',),
                  why='the launch-time check reports no change of the approved authority'))


# ---------------------------------------------------------------- G06 delegated authority

DELEGATION_COMMAND = 'Run autonomously within this exact bounded task; keep scientific review.'
REVOKED_REFUSAL = 'user delegation revoked; explicit escalation required'
SCOPE_REFUSAL = 'decision outside explicit delegation'


def _pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def _delegated_run(nc, actions):
    """A synthetic run whose original prompt delegates exactly ``actions`` to a machine coordinator."""
    from ravel.workflow import scientific_autonomy as autonomy, workflow_state
    from ravel.workflow.state_io import atomic_json
    from ravel.workflow.task_completion import initial_requirements
    root = nc.root / 'run'
    (root / 'inputs').mkdir(parents=True)
    prompt = 'Keep the complete fictional research task.\n' + DELEGATION_COMMAND
    (root / 'user-message.txt').write_text(prompt)
    declared = autonomy.prepare_declaration(
        {'task_mode': 'research', 'compute_plan': 'smoke', 'prompt': prompt,
         'task_requirements': initial_requirements(prompt)},
        root / 'delegation.json', user_text=_pin(root / 'user-message.txt'), quote=DELEGATION_COMMAND,
        origin='initial_prompt', delegate_actor='machine-coordinator', actions=actions,
        bounds={'compute_plans': ['smoke'], 'allowed_changed_paths': ['inputs/settings.cfg'],
                'allowed_stages': ['detector'], 'max_redos': 1},
        task_class='research_analysis', base_dir=root)
    atomic_json(root / 'inputs/task_contract.json', declared['document'])
    # The approval verifier is an independently tested boundary of the authorization.
    nc.patch.setattr(workflow_state, 'verify_approval', lambda *a, **kw: [])
    return root


@case('G06', binding=INSTALLED)
def test_G06_a_revoked_or_out_of_scope_delegated_decision_is_refused(nc):
    from ravel.workflow import scientific_autonomy as autonomy
    root = _delegated_run(nc, ['accept_recommendation'])
    # A decision the user did not delegate is refused while the delegation stands.
    with pytest.raises(ValueError, match=SCOPE_REFUSAL):
        autonomy.authorize(root, 'approve_plan')
    # Positive control: the delegated decision is authorized as a machine decision under user delegation.
    granted = autonomy.authorize(root, 'accept_recommendation')
    assert granted['authority_label'] == 'machine_under_user_delegation'
    assert granted['human_identity_authenticated'] is False
    assert granted['value']['actions'] == ['accept_recommendation']
    # The user revokes the delegation in their own words; the delegated decision now needs escalation.
    steering = root / 'revoke.txt'
    steering.write_text('Stop autonomous work; I will steer the next stage.\n')
    receipt = autonomy.revoke(root, user_text=_pin(steering), quote=steering.read_text().strip())
    assert receipt['execution_authorized'] is False
    with pytest.raises(ValueError, match=REVOKED_REFUSAL):
        autonomy.authorize(root, 'accept_recommendation')
    with pytest.raises(ValueError, match=REVOKED_REFUSAL):
        autonomy.authorize(root, 'approve_plan')


def _revocation_unread(original):
    def authorize(root, action):
        from ravel.workflow import scientific_autonomy as module
        written = module.REVOCATION
        module.REVOCATION = 'inputs/never-written-revocation.json'
        try:
            return original(root, action)
        finally:
            module.REVOCATION = written
    authorize.__wrapped__ = original
    return authorize


def _every_decision_delegated(original):
    def declaration(document, base, **kwargs):
        from ravel.workflow import scientific_autonomy as module
        found = original(document, base, **kwargs)
        return found if found is None else {**found, 'value': {**found['value'], 'actions': sorted(module.ACTIONS)}}
    declaration.__wrapped__ = original
    return declaration


register(Mutation('G06', 'ravel.workflow.scientific_autonomy:authorize', _revocation_unread, ('G06',),
                  why='the authorization no longer consults the revocation receipt'),
         Mutation('G06', 'ravel.workflow.scientific_autonomy:declaration', _every_decision_delegated, ('G06',),
                  why='every decision reads as delegated'))


# ---------------------------------------------------------------- G08 work-order fidelity at adoption

@case('G08', binding=INSTALLED)
def test_G08_worker_output_that_differs_from_the_sealed_work_order_is_not_adopted(nc):
    from ravel.workflow import work_dispatch
    from test_work_dispatch import fixture
    root = nc.root / 'run'
    order, workspace = fixture(root)
    node = order['node_id']
    sidecar = workspace / order['obligations'][0]['output']
    faithful = sidecar.read_bytes()
    answers = json.loads(faithful)
    unanswered = sorted(answers['obligations'])[0]
    del answers['obligations'][unanswered]  # the worker's answer to one sealed obligation is missing
    sidecar.write_text(json.dumps(answers))
    with pytest.raises(ValueError, match=f'work-order fidelity: obligation pointer does not resolve: {unanswered}'):
        work_dispatch.adopt(root, node, 1)
    assert not (root / 'outputs').exists()
    # The pinned obligations file is edited after CHECK-IN 1 pinned it.
    sidecar.write_bytes(faithful)
    pinned = root / 'inputs/work-obligations.json'
    sealed = pinned.read_bytes()
    pinned.write_bytes(sealed + b'\n')
    with pytest.raises(ValueError, match='work-order fidelity: obligations sidecar differs from CHECK-IN 1 pin'):
        work_dispatch.adopt(root, node, 1)
    assert not (root / 'outputs').exists()
    # Positive control: the faithful output of the sealed order is adopted, byte for byte.
    pinned.write_bytes(sealed)
    adopted = work_dispatch.adopt(root, node, 1)
    assert (root / 'outputs/result.json').read_bytes() == faithful
    assert [copy['to'] for copy in adopted['copied']] == [str(root / 'outputs/result.json')]
    assert adopted['contract_checks'] == ['check:obligation_coverage', 'check:work_order_content']


register(Mutation('G08', 'ravel.workflow.work_order_fidelity:require_fidelity',
                  returns(['check:obligation_coverage', 'check:work_order_content']), ('G08',),
                  why='adoption no longer compares the worker output with the sealed order'))


# ---------------------------------------------------------------- G10 / G14 strict execution guard

# Commands whose visible part the strict guard allows, each with one hidden effect appended.
HIDDEN_EFFECTS = (
    ('output redirection', 'snakemake -n > hidden-output.txt'),
    ('appending redirection', 'git status >> hidden-output.txt'),
    ('input redirection', 'git status < hidden-input.txt'),
    ('command substitution', 'snakemake -n $(printf fictional)'),
    ('backticks', 'git status `printf fictional`'),
    ('background job', 'snakemake -n &'),
    ('braced parameter expansion', 'git status ${FICTIONAL_TARGET}'),
)
VISIBLE_COMMANDS = {'snakemake -n': 'snakemake-dry-run', 'git status': 'git-status'}


@case('G10', binding=INSTALLED)
def test_G10_a_hidden_effect_behind_an_allowed_command_is_unparsable_in_strict_mode(nc):
    from ravel.workflow import execution_guard as guard
    from test_execution_guard import make_project
    project = make_project(nc.root / 'project')
    for label, command in HIDDEN_EFFECTS:
        decision = guard.decide(command, project)
        assert (decision['mode'], decision['allowed'], decision['rule']) == ('strict', False, 'unparsable'), label
        assert decision['why'], label
        with pytest.raises(guard.Unparsable):
            guard.statements(command)
    # The 1.3.0 build adds the bare parameter-expansion form (coverage row G10); asserted once it is installed.
    if controller_installed():
        for command in ('git status $FICTIONAL_TARGET', 'snakemake -n $1'):
            decision = guard.decide(command, project)
            assert (decision['allowed'], decision['rule']) == (False, 'unparsable'), command
    # Positive control: the visible commands alone are allowed, and parse to their own words.
    for command, rule in VISIBLE_COMMANDS.items():
        decision = guard.decide(command, project)
        assert decision['allowed'] is True and decision['rule'] == rule, command
        assert guard.statements(command) == [command.split()]


def _strip_hidden_effects(original):
    import re
    hidden = re.compile(r'\$\([^)]*\)|`[^`]*`|\$\{[^}]*\}|\d*[<>]+&?\s*\S+|\s&\s*$')

    def statements(command):
        return original(hidden.sub('', command))
    statements.__wrapped__ = original
    return statements


register(Mutation('G10', 'ravel.workflow.execution_guard:statements', _strip_hidden_effects, ('G10',),
                  why='the parser drops redirections, substitutions and background jobs instead of refusing them'))


@case('G14', binding=INSTALLED)
def test_G14_every_strict_decision_is_logged_with_rule_and_digest_never_the_command_text(nc):
    from ravel.workflow import execution_guard as guard
    from test_execution_guard import make_project
    project = make_project(nc.root / 'project')
    canary = nc.effects.canary('G14')
    inspection = f'grep -n {canary.value} workflow/Snakefile'
    direct = f'python {canary.value}.py'
    outcomes = []
    for command in (inspection, direct):
        event = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'session_id': 'fictional-session'}
        outcomes.append(guard.hook(json.dumps(event), project))
    assert outcomes[0] == (True, '')
    assert outcomes[1][0] is False and 'direct-code' in outcomes[1][1]
    rows = guard.read_log(project)
    assert [(row['decision'], row['rule']) for row in rows] == [('allowed', 'inspect-grep'), ('refused', 'direct-code')]
    assert [row['command_sha256'] for row in rows] == [hashlib.sha256(c.encode()).hexdigest()
                                                       for c in (inspection, direct)]
    assert all(row['kind'] == 'execution-guard-decision' and row['mode'] == 'strict'
               and row['session_id'] == 'fictional-session' for row in rows)
    assert canary.found_in(project) == []  # only digests are retained, never the command text


register(Mutation('G14', 'ravel.workflow.execution_guard:record', returns(None), ('G14',),
                  why='a decision is taken and nothing is retained of it'))


# ---------------------------------------------------------------- G12 scan launch history

UNAVAILABLE = 'scan launch authorization unavailable: '


def _scan_of_two_points(nc):
    """A fictional scan: an aggregate run, a manifest of two points and one run directory per point."""
    aggregate = nc.root / 'scan'
    aggregate.mkdir()
    points, plans = [], {}
    for tag in ('point-a', 'point-b'):
        run = nc.root / 'points' / tag
        (run / 'inputs').mkdir(parents=True)
        plans[tag] = hashlib.sha256(tag.encode()).hexdigest()
        (run / 'inputs/native_execution_plan.json').write_text(json.dumps(
            {'required_compute_plan': 'scan', 'plan_sha256': plans[tag]}))
        points.append({'tag': tag, 'run_dir': str(run)})
    return aggregate, points, plans


@case('G12', binding=INSTALLED)
def test_G12_a_scan_result_without_a_distinct_manifested_launch_history_per_point_is_refused(nc):
    from ravel.workflow import launch_authorization, workflow_state
    aggregate, points, plans = _scan_of_two_points(nc)
    audited, asked = [], {}

    def launch_history(path, **kwargs):
        audited.append(Path(path).name)
        asked[Path(path).name] = (kwargs['plan_sha256'], kwargs['require_generation'])
        return []

    # The audits of a point's GO and of its launch events are their own boundaries; here they answer clean
    # and record which point, plan and requirement they were asked about.
    nc.patch.setattr(workflow_state, 'verify_checkin2_go', lambda path: [])
    nc.patch.setattr(launch_authorization, 'audit_launches', launch_history)

    def audit(manifest_points, result_tags):
        audited.clear()
        return launch_authorization.audit_scan_launches(aggregate, {'points': manifest_points},
                                                        {'points': [{'tag': tag} for tag in result_tags]})

    # Positive control: every reported point is manifested once and has its own run.
    assert audit(points, ['point-a', 'point-b']) == [] and audited == ['point-a', 'point-b']
    assert asked == {tag: (sha, True) for tag, sha in plans.items()}
    attacks = (
        ('duplicate result tag', points, ['point-a', 'point-a'], [],
         'scan population has a missing, duplicate or unmanifested point tag'),
        ('unmanifested result tag', points, ['point-a', 'point-z'], [],
         'scan population has a missing, duplicate or unmanifested point tag'),
        ('duplicate manifest tag', [points[0], dict(points[1], tag='point-a')], ['point-a'], [],
         'scan manifest needs distinct string point tags'),
        ('aggregate for a point', [dict(points[0], run_dir=str(aggregate)), points[1]], ['point-a', 'point-b'], [],
         "scan aggregate cannot stand in for its point's launch history"),
        ('one run for two points', [points[0], dict(points[1], run_dir=points[0]['run_dir'])],
         ['point-a', 'point-b'], ['point-a'], "distinct scan points cannot reuse one run's launch history"),
    )
    for label, manifested, reported, expected_audits, reason in attacks:
        assert audit(manifested, reported) == [UNAVAILABLE + reason], label
        assert audited == expected_audits, label  # the offending row is never audited as if it were valid


register(Mutation('G12', 'ravel.workflow.launch_authorization:audit_scan_launches',
                  passes_through(lambda errors, *args, **kwargs: [e for e in errors if not e.startswith(UNAVAILABLE)]),
                  ('G12',), why='the scan audit drops its point tag and launch history refusals'))


# ---------------------------------------------------------------- G13 site-tool observation (labelled)

def _json_sha256(value):
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _observations(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


@case('G13', binding=INSTALLED)
def test_G13_the_site_tool_observer_retains_classification_digests_and_authority_when_invoked(nc):
    from ravel.paths import package_data_path
    from ravel.workflow import site_tools
    from test_site_tool_admission import approve, call
    for name in ('CLAUDE_CODE_SESSION_ID', 'RAVEL_SESSION_ID', 'CLAUDECODE', 'CLAUDE_PROJECT_DIR'):
        nc.patch.delenv(name, raising=False)
    canary = nc.effects.canary('G13').value
    policy_sha = hashlib.sha256(package_data_path('site_tools', 'policy.json').read_bytes()).hexdigest()
    bare = nc.root / 'bare-project'
    bare.mkdir()
    log = bare / 'logs/site-tools.jsonl'

    def retained(data, **expected):
        """Observe one call in the bare project and compare the newest retained row with ``expected``."""
        before = len(_observations(log))
        site_tools.observe({**data, 'tool_response': {'result': canary}}, project=bare)
        rows = _observations(log)
        assert len(rows) == before + 1, 'the observation was not retained'
        assert {key: rows[-1][key] for key in expected} == expected
        assert rows[-1]['kind'] == 'site-tool-observation' and rows[-1]['policy_sha256'] == policy_sha
        assert rows[-1]['tool_response_sha256'] == _json_sha256({'result': canary})
        return rows[-1]

    lookup, submit = call('lookup_dataset', query=canary), call('submit_job', jobs=2)
    # A read-only call is classified and its arguments retained only as a digest; no run holds authority.
    retained(lookup, tool_name=lookup['tool_name'], tool_input_sha256=_json_sha256(lookup['tool_input']),
             classification='read-only', effects=[], approval_sha256=None, current_decision='allow')
    # An effectful call without an approved run is observed, with the authority it lacked at that time.
    retained(submit, tool_input_sha256=_json_sha256(submit['tool_input']), classification='effectful',
             effects=['job-submit'], approval_sha256=None, current_decision='deny')
    # In an approved run the observation retains the digest of the approval receipt in force at that time.
    run = approve(nc.root, submit)
    site_tools.observe({**submit, 'cwd': str(run), 'tool_response': {'result': canary}}, project=nc.root)
    [approved] = _observations(run / 'logs/site-tools.jsonl')
    receipt = (run / 'inputs/checkin1_approval.json').read_bytes()
    assert approved['approval_sha256'] == hashlib.sha256(receipt).hexdigest()
    assert (approved['classification'], approved['current_decision']) == ('effectful', 'allow')
    # An admission check that cannot run is recorded fail-closed: effectful, an unknown effect, denied.
    nc.patch.setattr(site_tools, 'policy', lambda: (_ for _ in ()).throw(ValueError('invalid policy')))
    retained(lookup, classification='effectful', effects=['unknown'], approval_sha256=None, current_decision='deny')
    # A call that is not an MCP call is refused and leaves no row.
    rows = len(_observations(log))
    with pytest.raises(ValueError, match='observation requires an MCP tool call'):
        site_tools.observe({'tool_name': 'Bash', 'tool_input': {'command': 'echo mcp__fictional'}}, project=bare)
    assert len(_observations(log)) == rows
    assert canary not in log.read_text() and nc.effects.canary('G13').found_in(bare, run) == []


def _observer_that_retains_nothing(original):
    def observe(data, *, project, rundir=None):
        if (type(data) is not dict or not isinstance(data.get('tool_name'), str)
                or not data['tool_name'].startswith('mcp__')):
            raise ValueError('observation requires an MCP tool call')
        return {}
    observe.__wrapped__ = original
    return observe


register(Mutation('G13', 'ravel.workflow.site_tools:observe', _observer_that_retains_nothing, ('G13',),
                  why='the observer accepts the call and writes no row'))


register(Mutation('M26', 'ravel.workflow.role_registry:_identity', _substitute_unknown_roles, ('G01',),
                  why='an inner guard (role resolution) stops refusing'),
         Mutation('M26', 'ravel.workflow.decision_gate:EPOCH_TWO_ONLY', constant(frozenset()), ('G11',),
                  why='an inner guard (epoch-two-only gates) stops refusing'))
