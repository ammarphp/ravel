"""Review regressions: each attack preserves a successful authorized control."""
from copy import deepcopy
import json
import os
import subprocess
import sys

import pytest

from test_p06_support import autonomous, frozen_store, new_store, operator_home, ownership, view
from test_p06_request import ci1, go, effect, PLAN_A, PLAN_B
from test_p06_stop import operator_command
from test_gate_wiring import run
from rdj_fixtures import prepare_case
from ravel.controller import authority as a
from ravel.controller.authority import common, operator, mode, stop


def test_F01_unsigned_and_tampered_records_cannot_manufacture_authority(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approved = ci1(store)
    assert a.verify(store, approved['id'], kind='ci1')
    forged = deepcopy(store.scan('authority')[0])
    forged.pop('issuer', None)
    forged['uid'] = common.uid()
    forged['subject']['pins']['plan_sha256'] = PLAN_B
    store.append('authority', forged)
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, forged['uid'], kind='ci1')


def test_F01_rehashed_operator_configuration_is_not_authentication(operator_home):
    from ravel.workflow import rdj_custody
    autonomous()
    assert operator.operator_config()['mode'] == 'autonomous'
    body = deepcopy(operator._ledger_rows()[-1]['record'])
    body.pop('issuer', None)
    body['config']['budgets']['events'] = 10**12
    body['config_sha256'] = common.digest(body['config'])
    rdj_custody._append(operator.ledger_path(), body)
    with pytest.raises(a.AuthorityRefused):
        operator.operator_config()


def test_F01_automated_pty_is_unattested(tmp_path):
    from test_p06_terminal import HELPER
    path = tmp_path / 'pty_probe.py'
    path.write_text(HELPER)
    done = subprocess.run([sys.executable, str(path), 'answer'], text=True, capture_output=True, timeout=60)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    # The exchange succeeds, but supplies no evidence that the author was human.
    answer = result.get('result', result)
    assert answer['decision'] == 'approve'
    assert answer.get('attestation') == 'terminal_operator_unattested'


def test_F02_successful_legacy_respond_keeps_machine_provenance(run):
    from ravel.workflow import gate_wiring, rdj_custody, rdj_loop
    case_id = prepare_case(run, 'launch', 'bulk_launch')
    result = gate_wiring.respond(run.root, f'approve {case_id}', approve=[case_id])
    assert result['decisions'][0]['case_id'] == case_id
    assert not rdj_custody.approvals(run.root, case_id, run.action_pin['sha256'])
    assert result['governance'] == 'NOT GOVERNED'
    assert result['provenance']['human_approval'] is False
    assert result['provenance']['review_credit'] is False
    case, state, _ = rdj_loop._load(run.root, case_id)
    receipt = rdj_loop._attestation_summary(run.root, case, state)
    assert receipt['human_approver'] is False
    assert receipt['independent'] is False


@pytest.mark.parametrize('budget', [100001, 10**9])
def test_F03_defaults_never_exceed_the_delegation(operator_home, tmp_path, budget):
    autonomous(r3_policy='conservative_default')
    store = frozen_store(tmp_path)
    from test_p06_support import retain_view
    source = view(store, 'r3_action')
    source['options'][1]['bounds'] = {'rung': 'smoke', 'stages': ['derive'], 'budget': {'events': 10}}
    retain_view(store, 'r3_action', source)
    subject = {'view': source, 'conservative_default': 'proceed'}
    bad = a.request(store, 'r3_action', subject, {'budget': {'events': budget}})
    assert 'pending' in bad or not bad['authorizes_effects']
    good = a.request(store, 'r3_action', subject, {'budget': {'events': 10}})
    assert good['decision'] == 'default' and a.verify(store, good['id'], kind='r3_action')


@pytest.mark.parametrize('restriction', ['budget', 'stages', 'steering_stages', 'steering_rungs'])
def test_F04_A01_G05_C37_effect_uses_every_applicable_bound(operator_home, tmp_path, restriction):
    autonomous()
    store = frozen_store(tmp_path)
    bounds = {'rung': 'smoke', 'budget': {'events': 10}, 'stages': ['derive']}
    a.request(store, 'ci1', {'view': view(store, 'approve_plan')}, bounds)
    assert a.authorize_effect(store, effect(stage='derive', budget={'events': 10}))
    if restriction == 'budget':
        denied = effect(stage='derive', budget={'events': 11})
    elif restriction == 'stages':
        a.request(store, 'ci1', {'view': view(store, 'approve_plan')}, {**bounds, 'stages': []})
        denied = effect(stage='derive')
    else:
        policy = {'bounds': {'allowed_stages': []}} if restriction == 'steering_stages' else {
            'bounds': {'rungs': ['none', 'dry']}}
        a.request(store, 'steering', {'view': view(store, 'steering'), 'policy': policy}, {})
        denied = effect(stage='derive')
    with pytest.raises(a.AuthorityRefused):
        a.authorize_effect(store, denied)


@pytest.mark.parametrize('kind', ['ci1', 'go'])
def test_F05_old_record_is_not_current_after_replacement(operator_home, tmp_path, kind):
    autonomous()
    store = frozen_store(tmp_path)
    old = ci1(store)
    if kind == 'go':
        approval = old
        old = go(store, approval)
        new = go(store, approval, waypoint='f'*64)
    else:
        new = ci1(store, plan=PLAN_B)
    assert a.verify(store, new['id'], kind=kind)
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, old['id'], kind=kind)


def test_F05_cached_request_and_verify_respect_stop(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approved = ci1(store)
    assert ci1(store)['id'] == approved['id']
    operator_command(store, 'stop')
    assert 'pending' in ci1(store)
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, approved['id'], kind='ci1')


@pytest.mark.parametrize('drop', ['items', 'flags', 'pins'])
def test_F06_C05_retained_state_survives_mutating_the_source_view(operator_home, tmp_path, drop):
    autonomous()
    store = frozen_store(tmp_path)
    source = view(store, 'approve_plan')
    # The fixture retains the independent compiler/reading snapshot before returning the view.
    good = deepcopy(source)
    source[drop] = {} if drop != 'flags' else []
    if drop == 'pins':
        source[drop] = {'plan_sha256': PLAN_B}
    held = a.request(store, 'ci1', {'view': source}, {'rung': 'smoke'})
    assert 'pending' in held
    accepted = a.request(store, 'ci1', {'view': good}, {'rung': 'smoke'})
    assert a.verify(store, accepted['id'], kind='ci1')


def test_F06_empty_plan_is_not_approvable(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    source = view(store, 'approve_plan')
    source['items'] = {}
    assert 'pending' in a.request(store, 'ci1', {'view': source}, {'rung': 'smoke'})


def test_F07_child_inherits_live_parent_restrictions(operator_home, tmp_path, monkeypatch):
    autonomous()
    parent = frozen_store(tmp_path)
    stores = {parent.run_id: parent}
    monkeypatch.setattr(common, 'open_store', lambda identifier: stores[identifier])
    child = new_store(tmp_path, 'child')
    stores[child.run_id] = child
    a.freeze_child(child, parent, {'prompt': 'Compute the child observable.'})
    assert a.effective_bounds(child)['budgets']['events'] == 100000
    a.request(parent, 'steering', {'view': view(parent, 'steering'), 'policy': {'budgets': {'events': 1}}}, {})
    assert a.effective_bounds(child)['budgets']['events'] == 1
    second = new_store(tmp_path, 'second')
    assert a.freeze_child(second, parent, {'prompt': 'Second child.'})['budgets']['events'] == 1
    operator_command(parent, 'pause')
    with pytest.raises(a.AuthorityRefused):
        a.authorize_effect(child, effect('dry'))
    operator_command(parent, 'resume')
    assert a.authorize_effect(child, effect('dry'))
    operator_command(parent, 'revoke')
    with pytest.raises(a.AuthorityRefused):
        a.authorize_effect(child, effect('dry'))


def test_F08_returned_id_roundtrips_through_binding_store(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    record = ci1(store)
    body = store.read('authority', record['id'])
    assert body['uid'] == record['uid']
    assert a.verify(store, record['id'], kind='ci1')['id'] == record['id']


def test_F01_issuer_key_is_private_fixed_and_never_auto_created(operator_home, tmp_path, monkeypatch):
    from ravel.controller.authority import issuer
    assert not (issuer.home() / 'issuer.key').exists()
    with pytest.raises(a.AuthorityRefused):
        issuer.seal({'kind': 'fabricated'}, 'record')
    autonomous()
    path = issuer.home() / 'issuer.key'
    assert path.stat().st_mode & 0o777 == 0o600
    before = issuer.home()
    monkeypatch.setenv('RAVEL_AUTHORITY_KEY', str(tmp_path / 'fake.key'))
    monkeypatch.setenv('HOME', str(tmp_path / 'fake-home'))
    assert issuer.home() == before
    assert issuer.require_confined_spec({'backend': 'bwrap', 'reads': [str(tmp_path / 'input')], 'writes': []})
    for exposed in (issuer.home(), issuer.home().parent, issuer.home() / 'issuer.key'):
        with pytest.raises(a.AuthorityRefused):
            issuer.require_confined_spec({'backend': 'bwrap', 'reads': [str(exposed)], 'writes': []})
    with pytest.raises(a.AuthorityRefused):
        issuer.require_confined_spec({'backend': 'unconfined', 'reads': [], 'writes': []})
    assert 'unconfined process' in issuer.receipt()['same_user_risk']


@pytest.mark.parametrize('attack', ['truncate', 'edit', 'cross_kind', 'copy_run'])
def test_F01_authenticated_history_rejects_rewrite_and_replay(operator_home, tmp_path, attack):
    autonomous()
    store = frozen_store(tmp_path)
    first = ci1(store)
    assert a.verify(store, first['id'], kind='ci1')
    if attack == 'truncate':
        ci1(store, plan=PLAN_B)
        path = store.path('authority.jsonl')
        path.write_text(path.read_text().splitlines()[0] + '\n')
    elif attack == 'edit':
        from test_p06_support import _digest
        path = store.path('authority.jsonl')
        row = json.loads(path.read_text())
        row['record']['bounds']['budget'] = {'events': 10**12}
        row['digest'] = _digest({k: v for k, v in row.items() if k != 'digest'})
        path.write_text(json.dumps(row) + '\n')
    elif attack == 'cross_kind':
        store.append('authority', store.scan('mode')[0])
    else:
        other = new_store(tmp_path, 'copied')
        other.append('authority', store.scan('authority')[0])
        store = other
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, first['id'], kind='ci1')


def test_F06_C07_retained_disclosures_cannot_be_omitted(operator_home, tmp_path):
    from test_p06_support import retain_view
    autonomous()
    store = frozen_store(tmp_path)
    source = view(store, 'approve_plan')
    retain_view(store, 'approve_plan', source, request_pins={'quantity': {'requested': 'x', 'planned': 'y'}},
                facts=['An essential response was inferred.'])
    held = a.request(store, 'ci1', {'view': source}, {'rung': 'smoke'})
    assert 'pending' in held
    assert 'requested quantity' in held['pending']['reason'] and 'inferred critical facts' in held['pending']['reason']
    retain_view(store, 'approve_plan', source, request_pins={'quantity': {'requested': 'x', 'planned': 'x'}})
    assert a.request(store, 'ci1', {'view': source}, {'rung': 'smoke'})['label'] == a.MACHINE


def test_F04_GO_and_deviation_resource_bounds_restrict_effects(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    grant = a.request(store, 'go', {'view': view(store, 'go', approve_plan=approval['id'], waypoint_sha256='c'*64)},
                      {'rung': 'full', 'budget': {'events': 10}})
    assert a.authorize_effect(store, effect('full', budget={'events': 10}))['go'] == grant['id']
    with pytest.raises(a.AuthorityRefused):
        a.authorize_effect(store, effect('full', budget={'events': 11}))
    from test_p06_request import deviation
    change = {'parameter': 'tolerance', 'from': '0.10', 'to': '0.05', 'why': 'tighter',
              'touches': ['s01'], 'direction': 'tighten'}
    a.request(store, 'deviation', {'view': view(store, 'deviation', approve_plan=approval['id'],
               plan_sha256=PLAN_B, previous_plan_sha256=PLAN_A), 'change': change},
               {'rung': 'full', 'budget': {'events': 3}})
    assert a.authorize_effect(store, effect('smoke', plan_sha256=PLAN_B, budget={'events': 3}))
    with pytest.raises(a.AuthorityRefused):
        a.authorize_effect(store, effect('smoke', plan_sha256=PLAN_B, budget={'events': 4}))


def test_F02_machine_quote_is_never_labelled_human():
    from ravel.workflow import approval_authority
    label = approval_authority.classify(quote='approved', agent_session=True, interactive=True)
    assert 'human' not in label
    assert approval_authority.classify(delegated=True) == 'delegated_machine'


def test_F04_missing_stage_or_budget_cannot_hide_restricted_effect(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    a.request(store, 'ci1', {'view': view(store, 'approve_plan')},
              {'rung': 'smoke', 'stages': ['derive'], 'budget': {'events': 2}})
    assert a.authorize_effect(store, effect(stage='derive', budget={'events': 2}))
    for hidden in (effect(budget={'events': 1}), effect(stage='derive')):
        with pytest.raises(a.AuthorityRefused):
            a.authorize_effect(store, hidden)


def _consumer_approval(store, *, rung='smoke'):
    """Retain the actual branch declarations independently of the effect request."""
    from test_p06_support import retain_view
    source = view(store, 'approve_plan', plan_sha256=PLAN_A)
    source['items']['steps'] = [
        {'id': 'launch', 'kind': 'operate', 'operation': 'fictional-compute'},
        {'id': 'review', 'kind': 'subgraph', 'graph': {'id': 'review.points', 'instance': {}}}]
    retain_view(store, 'approve_plan', source)
    budget = {'model_calls': 7, 'tokens': 1500, 'wall_seconds': 30, 'events': 0, 'review_rounds': 2}
    approval = a.request(store, 'ci1', {'view': source}, {'rung': rung, 'budget': budget})
    assert approval['decision'] == 'approve'
    return approval, budget


@pytest.mark.parametrize('checkpoint', ['ci1', 'go'])
def test_launch_requires_only_the_resources_its_approved_branch_consumes(operator_home, tmp_path, checkpoint):
    autonomous()
    store = frozen_store(tmp_path)
    approval, approved = _consumer_approval(store, rung='full' if checkpoint == 'go' else 'smoke')
    if checkpoint == 'go':
        grant = a.request(store, 'go', {'view': view(store, 'go', approve_plan=approval['id'],
                                                  waypoint_sha256='c' * 64)},
                          {'rung': 'full', 'budget': approved})
        assert grant['decision'] == 'go'
    requested = {key: value for key, value in approved.items() if key != 'review_rounds'}
    launch = {**effect('full' if checkpoint == 'go' else 'smoke', budget=requested), 'id': 'launch'}
    before = deepcopy(launch)
    assert a.authorize_effect(store, launch)['approve_plan'] == approval['id']
    assert launch == before


@pytest.mark.parametrize('dimension', ['model_calls', 'tokens', 'wall_seconds', 'events'])
def test_launch_cannot_omit_an_approved_launch_resource(operator_home, tmp_path, dimension):
    autonomous()
    store = frozen_store(tmp_path)
    _, approved = _consumer_approval(store)
    # Include the non-launch dimension too, so only the consumed omission explains refusal.
    requested = {key: value for key, value in approved.items() if key != dimension}
    with pytest.raises(a.AuthorityRefused, match='omits an explicitly approved resource budget'):
        a.authorize_effect(store, {**effect(budget=requested), 'id': 'launch'})


@pytest.mark.parametrize('rounds', [None, 2, 3])
def test_review_subgraph_authority_still_enforces_approved_rounds(operator_home, tmp_path, rounds):
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    autonomous()
    store = frozen_store(tmp_path)
    approval, approved = _consumer_approval(store)
    requested = {key: value for key, value in approved.items() if key != 'review_rounds'}
    if rounds is not None:
        requested['review_rounds'] = rounds
    step = {'id': 'review', 'kind': 'subgraph', 'rung': 'smoke', 'budget': requested}
    ctx = {'plan_sha256': PLAN_A}
    if rounds == 2:
        assert graph._authorize(store, ctx, step, requested)['approve_plan'] == approval['id']
        assert len(store.scan('step-authority')) == 1
    else:
        with pytest.raises(StepHold) as refused:
            graph._authorize(store, ctx, step, requested)
        assert refused.value.reason == 'authority_refused'
        assert ('omits an explicitly approved resource budget' if rounds is None else
                'review_rounds=3 exceeds the ceiling 2') in refused.value.would_make_possible
        assert store.scan('step-authority') == []


def test_unclassified_effect_cannot_discard_approved_dimensions(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    _, approved = _consumer_approval(store)
    requested = {key: value for key, value in approved.items() if key != 'review_rounds'}
    # A caller-supplied kind does not replace the authenticated plan's declaration.
    with pytest.raises(a.AuthorityRefused, match='omits an explicitly approved resource budget'):
        a.authorize_effect(store, {**effect(budget=requested), 'id': 'unknown', 'kind': 'launch'})


def test_authority_consumer_declarations_cover_compiler_and_launch_resources():
    from ravel.controller.authority import service
    from ravel.controller.routes.compiler import AUTHORITY_BUDGET
    from ravel.controller.step.budget import DIMENSIONS
    assert set(AUTHORITY_BUDGET.values()) <= set(service.RESOURCE_CONSUMERS)
    launch = {key for key, consumers in service.RESOURCE_CONSUMERS.items() if 'launch' in consumers}
    assert launch == set(DIMENSIONS) | {'batch_jobs'}


def test_amended_plan_branch_scopes_every_approved_bound(operator_home, tmp_path):
    from test_p06_support import retain_view
    autonomous()
    store = frozen_store(tmp_path)
    approval, approved = _consumer_approval(store)
    source = view(store, 'deviation', approve_plan=approval['id'], approved_plan_sha256=PLAN_A,
                  plan_sha256=PLAN_B)
    # The amended effect was previously a subgraph: classification must use the renewed plan.
    source['items']['steps'] = [{'id': 'review', 'kind': 'operate', 'operation': 'fictional-compute'}]
    retain_view(store, 'deviation', source)
    amendment = a.request(store, 'deviation', {'view': source, 'change': {
        'parameter': 'execution branch', 'from': 'subgraph', 'to': 'launch', 'why': 'Use supplied compute.',
        'touches': ['review'], 'direction': 'tighten'}}, {'rung': 'smoke', 'budget': approved})
    assert amendment['decision'] == 'approve'
    requested = {key: value for key, value in approved.items() if key != 'review_rounds'}
    launch = {**effect(plan_sha256=PLAN_B, budget=requested), 'id': 'review'}
    assert a.authorize_effect(store, launch)['deviation'] == amendment['id']
    with pytest.raises(a.AuthorityRefused, match='omits an explicitly approved resource budget'):
        a.authorize_effect(store, {**launch, 'budget': {key: value for key, value in requested.items()
                                                     if key != 'events'}})


def test_F03_default_requires_the_selected_options_actual_effect_bounds(operator_home, tmp_path):
    from test_p06_support import retain_view
    autonomous(r3_policy='conservative_default')
    store = frozen_store(tmp_path)
    source = view(store, 'r3_action')
    bounds = {'rung': 'smoke', 'stages': ['derive'], 'budget': {'events': 10}}
    held = a.request(store, 'r3_action', {'view': source, 'conservative_default': 'proceed'}, bounds)
    assert 'pending' in held
    source['options'][1]['bounds'] = bounds
    retain_view(store, 'r3_action', source)
    valid = a.request(store, 'r3_action', {'view': source, 'conservative_default': 'proceed'}, bounds)
    assert a.verify(store, valid['id'], kind='r3_action')


def test_F01_unattested_terminal_needs_explicit_authenticated_operator_command(operator_home, tmp_path, monkeypatch, capfd):
    from ravel.controller.authority import terminal
    monkeypatch.setattr(terminal, 'ask', lambda *args, **kwargs: {
        'decision': 'approve', 'comment': 'Automated PTY response', 'device': {'name': '/dev/pts/9', 'rdev': 9},
        'prompt_sha256': 'a'*64, 'response_sha256': 'b'*64, 'nonce_sha256': 'c'*64, 'attempts': 1})
    store = frozen_store(tmp_path)  # operator initialized interactive, never delegated
    held = ci1(store)
    assert 'pending' in held and held['unattested_record']
    unattested = common.read(store, common.AUTHORITY, held['unattested_record'], common.SCHEMA)
    assert unattested['label'] == a.LEGACY_TERMINAL and unattested['authorizes_effects'] is False
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, unattested['id'], kind='ci1')
    import re
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    pending = common.scan(store, common.REQUESTS)[-1]
    with pytest.raises(a.AuthorityRefused):
        a.answer(store, pending['id'], 'wrong-code', 'approve')
    approved = a.answer(store, pending['id'], code, 'approve')
    assert approved['label'] == a.OPERATOR_COMMAND and not approved['human_identity_authenticated']
    assert a.authorize_effect(store, effect('smoke'))['approve_plan'] == approved['id']


def test_F06_request_comparison_is_derived_from_frozen_contract_and_retained_plan(operator_home, tmp_path):
    from ravel.controller.authority import retained
    autonomous()
    store = frozen_store(tmp_path, {'prompt': 'Compute x.', 'request_pins': {'quantity': 'x'}})
    # No helper source is captured: construct the independent compiler/reading handoff.
    source = {'run_id': store.run_id, 'pins': {'plan_sha256': PLAN_A},
              'sections': [{'id': 'preamble', 'title': 'Task', 'lines': ['Compute the specified quantity.']}],
              'items': {'steps': ['derive'], 'deliverables': ['value'], 'boundaries': []}, 'flags': []}
    plan = {'sha256': PLAN_A, 'steps': ['derive'], 'deliverables': ['value'], 'boundaries': [],
            'request_pins': {'quantity': 'y'}}
    reading = {'flags': [], 'request_pins': {}, 'inferred_critical_facts': []}
    retained.capture(store, 'ci1', plan=plan, reading=reading, view=source)
    held = a.request(store, 'ci1', {'view': source}, {'rung': 'smoke'})
    assert 'requested quantity' in held['pending']['reason']
    plan['request_pins']['quantity'] = 'x'
    retained.capture(store, 'ci1', plan=plan, reading=reading, view=source)
    assert a.request(store, 'ci1', {'view': source}, {'rung': 'smoke'})['label'] == a.MACHINE


def test_F01_operator_ledger_rollback_is_not_a_configuration_change(operator_home):
    autonomous()
    first = operator.ledger_path().read_text()
    operator.set_values({'budgets': {'events': 1}})
    assert operator.operator_config()['budgets']['events'] == 1
    operator.ledger_path().write_text(first)
    with pytest.raises(a.AuthorityRefused):
        operator.operator_config()


@pytest.mark.parametrize('kind', ['mode', 'authority-request', 'authority-context', 'stop-observation'])
def test_F01_every_authority_input_authenticates_its_issuer(operator_home, tmp_path, kind):
    autonomous()
    store = frozen_store(tmp_path)
    assert ci1(store)['label'] == a.MACHINE
    store.append(kind, {'schema': 'fabricated', 'uid': common.uid(), 'run_id': store.run_id})
    with pytest.raises(a.AuthorityRefused):
        common.scan(store, kind)


def test_capture_and_request_agree_on_a_nonempty_plan_view(operator_home, tmp_path):
    import fakes
    from ravel.controller import routes
    from ravel.controller.authority import retained
    autonomous()
    store = frozen_store(tmp_path)
    reading = {'deliverables': [{'id': 'value', 'artifact': {'kind': 'number'}}],
               'request_pins': {}, 'inferred_critical_facts': [],
               'boundaries': [{'class': 'scope', 'would_make_possible': 'Use only the declared finite domain.'}],
               'flags': [{'kind': 'assumption', 'text': 'Use the specified finite domain.'}],
               'items': {'questions': ['Which precision is required?']}}
    spec = fakes._spec('toy-route', 7, {'field': 'task_mode', 'eq': 'calculation'},
                       [fakes.make_step('derive', outputs=['outputs/value.json'])],
                       [{'match': {'any': True}, 'step': 'derive', 'output': 'outputs/value.json'}])
    plan = routes.compile(spec, reading, {'prompt': 'Calculate a toy observable.'})
    assert plan['steps'] and plan['deliverables'] and routes.plan_errors(plan) == []
    source = {'run_id': store.run_id,
              'pins': {'plan_sha256': plan['sha256'], 'source_sha256': 'c' * 64},
              'sections': [{'id': 'preamble', 'title': 'Task', 'lines': ['Calculate the specified toy value.']}],
              'flags': reading['flags'], 'items': retained.view_items(plan, reading)}
    snapshot = retained.capture(store, 'ci1', plan=plan, reading=reading, view=source)
    assert snapshot['view']['items'] == source['items']
    assert source['items']['boundaries'] == reading['boundaries']
    accepted = a.request(store, 'ci1', {'view': source}, {'rung': 'smoke'})
    assert a.verify(store, accepted['id'], kind='ci1')
    assert 'derive' in a.checkin_text(a.render_checkin('ci1', source))
    for field in ('deliverable', 'flag', 'source_pin', 'step', 'boundary'):
        changed = deepcopy(source)
        if field == 'deliverable':
            changed['items']['deliverables'][0]['id'] = 'other'
        elif field == 'flag':
            changed['flags'][0]['text'] = 'A different assumption.'
        elif field == 'source_pin':
            changed['pins']['source_sha256'] = 'd' * 64
        elif field == 'boundary':
            changed['items']['boundaries'][0]['would_make_possible'] = 'Use a different domain.'
        else:
            changed['items']['steps'][0]['outputs'][0]['path'] = 'outputs/other.json'
        refused = a.request(store, 'ci1', {'view': changed}, {'rung': 'smoke'})
        assert 'pending' in refused and refused['pending']['errors']
    assert a.request(store, 'ci1', {'view': source}, {'rung': 'smoke'})['id'] == accepted['id']


def test_disposition_authenticates_final_currency_and_subject(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    pins = {'approve_plan': approval['id'], 'result_sha256': 'd' * 64}
    final = a.request(store, 'final', {'view': view(store, 'final', **pins)}, {})
    read = a.disposition(store, final['id'], kind='final', subject=pins)
    assert read == final and not read['authorizes_effects'] and not read['review_credit']
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, final['id'], kind='final')
    with pytest.raises(a.AuthorityRefused):
        a.disposition(store, final['id'], kind='final', subject={**pins, 'result_sha256': 'e' * 64})
    replacement = a.request(store, 'final', {'view': view(store, 'final', **{**pins, 'result_sha256': 'e' * 64})}, {})
    assert a.disposition(store, replacement['id'], kind='final', subject={'result_sha256': 'e' * 64}) == replacement
    with pytest.raises(a.AuthorityRefused):
        a.disposition(store, final['id'], kind='final', subject=pins)


@pytest.mark.parametrize('damage', ['modified', 'mac_invalid'])
def test_disposition_refuses_modified_or_mac_invalid_final(operator_home, tmp_path, monkeypatch, damage):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    pins = {'approve_plan': approval['id'], 'result_sha256': 'd' * 64}
    final = a.request(store, 'final', {'view': view(store, 'final', **pins)}, {})
    assert a.disposition(store, final['id'], kind='final', subject=pins) == final
    scan = store.scan
    def corrupt(kind):
        rows = deepcopy(scan(kind))
        if kind == 'authority':
            if damage == 'modified':
                rows[-1]['decision'] = 'reject'
            else:
                rows[-1].pop('issuer')
        return rows
    monkeypatch.setattr(store, 'scan', corrupt)
    with pytest.raises(a.AuthorityRefused):
        a.disposition(store, final['id'], kind='final', subject=pins)


def test_terminal_approval_stays_pending_with_retained_unattested_id(operator_home, tmp_path, monkeypatch):
    from ravel.controller.authority import terminal
    monkeypatch.setattr(terminal, 'ask', lambda *args, **kwargs: {
        'decision': 'approve', 'comment': 'Continue.', 'device': {'name': '/dev/pts/9', 'rdev': 9},
        'prompt_sha256': 'a' * 64, 'response_sha256': 'b' * 64, 'nonce_sha256': 'c' * 64, 'attempts': 1})
    store = frozen_store(tmp_path)
    held = ci1(store)
    assert 'pending' in held and held['unattested_record']
    assert a.ledger_evidence(store)['CT07'] == {'authority': held['unattested_record']}
    record = common.read(store, common.AUTHORITY, held['unattested_record'], common.SCHEMA)
    assert record['label'] == a.LEGACY_TERMINAL and record['decision'] == 'approve'
    assert not record['authorizes_effects']
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, record['id'], kind='ci1')
    repeated = ci1(store)
    assert repeated['unattested_record'] == record['id'] and 'pending' in repeated
    assert len(store.scan('authority')) == 1


def test_authenticated_reader_registers_with_ledger_hook(operator_home, tmp_path):
    from types import SimpleNamespace
    from ravel.controller.graph import services
    registered = []
    autonomous()
    store = frozen_store(tmp_path)
    approved = ci1(store)
    with services(ledger=SimpleNamespace(register_authority_reader=registered.append)):
        a.register_ledger_reader()
    assert len(registered) == 1
    assert registered[0](store, approved['id']) == approved
    with pytest.raises(a.AuthorityRefused):
        registered[0](store, 'missing')


def test_mechanism_evidence_is_issued_from_authenticated_records(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approved = ci1(store)
    rows = a.ledger_evidence(store)
    assert {'A02', 'A03', 'C09', 'SW01', 'SW02'} <= set(rows)
    own_ids = {r['id'] for kind in (common.MODE, common.AUTHORITY, common.REQUESTS, common.OBSERVATIONS)
               for r in common.scan(store, kind)}
    assert all(set(evidence) == {'authority'} and evidence['authority'] in own_ids for evidence in rows.values())
    assert a.plan_authority(store, {'plan_sha256': PLAN_A})[0]['id'] == approved['id']
    assert a.plan_authority(store, {'plan_sha256': PLAN_B}) == (None, None)
    store.append('authority', {'schema': common.SCHEMA, 'uid': 'forged', 'run_id': store.run_id})
    with pytest.raises(a.AuthorityRefused):
        a.ledger_evidence(store)


def test_mechanism_evidence_tracks_each_executed_boundary(operator_home, tmp_path):
    from test_p06_request import deviation, r3
    autonomous()
    store = frozen_store(tmp_path)
    initial = a.ledger_evidence(store)
    assert set(initial) == {'A02', 'A03', 'C09', 'SW01', 'SW02'}
    approval = ci1(store)
    steering = a.request(store, 'steering', {'view': view(store, 'steering'),
                                          'policy': {'budgets': {'events': 100}}}, {})
    for key in ('C37', 'C38', 'C39', 'SW03'):
        assert a.ledger_evidence(store)[key] == {'authority': steering['id']}
    held = r3(store, gate='unblind', default=None)
    for key in ('A11', 'G11'):
        assert a.ledger_evidence(store)[key] == {'authority': held['pending']['request']}
    amendment = deviation(store, approval)
    for key in ('A09', 'C20', 'C21', 'C32'):
        assert a.ledger_evidence(store)[key] == {'authority': amendment['id']}
    control = operator_command(store, 'stop')
    rows = a.ledger_evidence(store)
    for key in ('A10', 'G06', 'B05', 'C40', 'SW05'):
        assert rows[key] == {'authority': control['id']}
    a.observe_stop(store, 'draining', {'descendants': ['child']})
    observed = a.observe_stop(store, 'stopped', {'descendants': []})
    for key in ('B05', 'C40', 'SW05'):
        assert a.ledger_evidence(store)[key] == {'authority': observed['id']}
    expected = {'A02', 'A03', 'C09', 'SW01', 'SW02', 'C37', 'C38', 'C39', 'SW03',
                'A11', 'G11', 'A10', 'G06', 'B05', 'C40', 'SW05', 'A09', 'C20', 'C21', 'C32'}
    assert set(a.ledger_evidence(store)) == expected


def test_public_plan_authority_preserves_amendment_chain(operator_home, tmp_path):
    from test_p06_request import deviation
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    first = deviation(store, approval)
    final_pin = 'f' * 64
    change = {'parameter': 'precision', 'from': '0.05', 'to': '0.01', 'why': 'Tighten the control.',
              'touches': ['derive'], 'direction': 'tighten'}
    latest = a.request(store, 'deviation', {
        'view': view(store, 'deviation', approve_plan=approval['id'],
                     previous_plan_sha256=PLAN_B, plan_sha256=final_pin), 'change': change}, {'rung': 'full'})
    original, renewal = a.plan_authority(store, {'plan_sha256': final_pin})
    assert original['id'] == approval['id'] and renewal['id'] == latest['id']
    assert renewal['_lineage_bounds'] == [latest['bounds'], first['bounds']]
    assert a.plan_authority(store, {'plan_sha256': PLAN_B}) == (None, None)
    with pytest.raises(a.AuthorityRefused):
        a.verify(store, first['id'], kind='deviation')
    broken_pin = 'e' * 64
    a.request(store, 'deviation', {
        'view': view(store, 'deviation', approve_plan=approval['id'],
                     previous_plan_sha256='0' * 64, plan_sha256=broken_pin), 'change': change}, {'rung': 'full'})
    assert a.plan_authority(store, {'plan_sha256': broken_pin}) == (None, None)
