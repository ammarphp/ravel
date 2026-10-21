"""Actor identity for review credit.

An actor is one worker session. The dispatcher assigns its id at spawn, keeps it in the
worker's custody record, writes it into the receipt and registers it with the receipt.
Review credit at voting, specialist, producer and blind auditor points reads the custody
registration; a receipt that only declares an ``actor_id`` earns nothing. Synthetic plans
and inert children only: no model, network or native tool is involved.
"""
import hashlib
import json
import os

import pytest

from inert_dispatch import inert_dispatch  # noqa: F401
from test_review_points import receipt, run
from worker_supervision import descriptor, review_packet, supervised

from ravel.workflow import (agent_worker as worker, machine_lease, rdj_custody, rdj_loop, review_points as rp,
                            role_registry)

CLAIM = {'id': 'C1', 'kind': 'agreement', 'absolute_yield': True, 'basis_declared': ['authored_code']}
CRITIC, VERIFIER, DECIDER = 'RP4:C1:physics-critic', 'RP4:C1:skeptical-verifier', 'RP4:C1:physics-decider'
AUDITOR, SPECIALIST, PRODUCER, MAPPER = 'RP5:C1', 'RP7:C1', 'RP6:C1:divergence', 'RP6:C1'


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'run'
    root.mkdir()
    run(root, claims=[CLAIM])
    return root


def point(root, point_id):
    return next(p for p in rp.derive(rp._facts(root)) if p['id'] == point_id)


def report(root, node):
    record = next(r for r in rp._receipt_records(root, rp._facts(root)) if r['node_id'] == node)
    return rp._receipt_report(record)


# ---------------------------------------------------------------- the identity and where it is assigned

def test_actor_id_is_the_digest_of_transport_model_session_and_attempt():
    parts = ['transport-a', 'model-a', 'session-a', 'node/1']
    expected = hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert rdj_custody.actor_id(*parts) == expected
    record = rdj_custody.actor_record(*parts, family='family-a')
    assert record == {'actor_id': expected, 'transport_id': 'transport-a', 'model_id': 'model-a',
                      'worker_session_id': 'session-a', 'attempt_id': 'node/1', 'family': 'family-a'}
    for index in range(4):
        changed = list(parts)
        changed[index] += 'x'
        assert rdj_custody.actor_id(*changed) != expected
        with pytest.raises(ValueError):
            rdj_custody.actor_id(*[None if i == index else p for i, p in enumerate(parts)])


def spec(node='reviewer', *, point_id=None, subject=None):
    parent = {'review_point_id': point_id, 'map_id': None, 'rca_ticket': None}
    if subject is not None:
        parent['review_subject'] = subject
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node, 'attempt': 1,
            'role': {'id': 'executor', 'version': '1', 'card_sha256': '1' * 64},
            'transport_preference': ['stub'], 'inputs': [], 'declared_outputs': [],
            'budgets': {'max_turns': 5, 'max_wall_seconds': 20, 'max_broker_calls': 20, 'max_cost_usd': None},
            'final_record_schema': 'reviewer.v1', 'work_order': None, 'rdj_challenges': None, 'parent': parent}


def registered(role):
    """The role pin a dispatcher writes: the registered card's own version and digest."""
    return {'id': role, 'version': role_registry.load(role)['version'], 'card_sha256': role_registry.card_sha256(role)}


class FakeSupervisor:
    pid = 2 ** 22 + 7


def test_launch_assigns_the_actor_at_spawn_and_the_receipt_takes_it_from_custody(study, monkeypatch, inert_dispatch):
    """Where assigned (launch, before the supervisor starts), where bound (custody record, receipt, registration)."""
    started = []
    monkeypatch.setattr(worker.sandbox, 'available', lambda: 'test')
    monkeypatch.setattr(worker.subprocess, 'Popen', lambda argv, **kw: started.append(kw) or FakeSupervisor())
    facts = rp._facts(study)
    s = spec(point_id=CRITIC, subject=rp.review_subject(facts, point(study, CRITIC)))
    s['role'] = registered('physics-critic')
    descriptor = {'argv': ['/bin/sleep', '0'], 'transport': {'id': 'synthetic-cli', 'transport_kind': 'cli-worker'},
                  'model': {'requested': 'synthetic-model', 'observed': None, 'family': 'synthetic', 'effort': None}}
    assert worker.launch(study, s, launch_spec=descriptor, wait=False)['status'] == 'running'
    actor = worker._record(study, 'reviewer', 1)['actor']
    assert actor['transport_id'] == 'synthetic-cli' and actor['model_id'] == 'synthetic-model'
    assert actor['attempt_id'] == 'reviewer/1' and actor['family'] == 'synthetic' and actor['worker_session_id']
    assert actor['actor_id'] == rdj_custody.actor_id('synthetic-cli', 'synthetic-model', actor['worker_session_id'],
                                                     'reviewer/1')
    # The supervisor's whole environment carries the test lock domain's grant (test isolation).
    [options] = started
    assert options['env'][machine_lease.GRANT_ENV] == os.environ[machine_lease.GRANT_ENV]
    # A re-attach never assigns a second actor, and a later binding is refused.
    worker.launch(study, s, launch_spec=descriptor, wait=False)
    assert worker._record(study, 'reviewer', 1)['actor'] == actor and len(started) == 1
    with pytest.raises(ValueError, match='before the worker starts'):
        worker.bind_actor(study, 'reviewer', 1, transport_id='other', model_id='other')
    # The receipt names the custody actor whatever the execution record states.
    done = worker.finish(study, s, final={'completed': True, 'disposition': 'supported', 'findings': []},
                         execution={'exit_status': 0, 'session_id': 'observed-session', 'actor_id': 'declared',
                                    'attestation': 'transport_attested', 'transport': descriptor['transport'],
                                    'model': descriptor['model']})
    assert done['status'] == 'ok' and done['schema_version'] == 3 and done['actor_id'] == actor['actor_id']
    row = rdj_custody.worker_row(study, 'agent-work/reviewer/1/receipt.json',
                                 hashlib.sha256((study / 'agent-work/reviewer/1/receipt.json').read_bytes()).hexdigest())
    assert row['actor'] == actor and row['verified_label'] == 'transport_attested'
    assert rp.satisfied(study, CRITIC) and report(study, 'reviewer')['independent']


def test_bind_actor_assigns_once_and_only_before_the_receipt(study):
    s = spec('bound')
    worker.materialize(study, s)
    actor = worker.bind_actor(study, 'bound', 1, transport_id='synthetic-cli', model_id='synthetic-model')
    assert actor['attempt_id'] == 'bound/1' and worker._record(study, 'bound', 1)['actor'] == actor
    with pytest.raises(ValueError, match='exactly one'):
        worker.bind_actor(study, 'bound', 1, transport_id='synthetic-cli', model_id='synthetic-model')
    other = spec('finished')
    worker.materialize(study, other)
    done = worker.finish(study, other, final={'completed': True, 'disposition': 'supported', 'findings': []},
                         execution={'exit_status': 0, 'actor_id': 'declared'})
    assert done['actor_id'] is None
    with pytest.raises(ValueError, match='before the worker starts'):
        worker.bind_actor(study, 'finished', 1, transport_id='synthetic-cli', model_id='synthetic-model')


def review_spec(study, node, point_id, role):
    s = spec(node, point_id=point_id, subject=rp.review_subject(rp._facts(study), point(study, point_id)))
    s['role'] = registered(role)
    return s


FINAL = {'completed': True, 'disposition': 'supported', 'findings': []}


def test_a_completion_the_host_writes_itself_is_never_transport_attested(study):
    """No supervised launch observed this worker, so nothing a caller states makes it transport-attested."""
    s = review_spec(study, 'host-done', SPECIALIST, 'discrepancy-attributor')
    worker.materialize(study, s)
    worker.bind_actor(study, 'host-done', 1, transport_id='synthetic-cli', model_id='synthetic-model')
    done = worker.finish(study, s, final=FINAL, execution={
        'exit_status': 0, 'session_id': 'anything', 'attestation': 'transport_attested',
        'transport': descriptor()['transport'], 'model': descriptor()['model']})
    assert done['status'] == 'ok' and done['schema_version'] == 3
    assert done['attestation'] == 'host_attested'
    rel = 'agent-work/host-done/1/receipt.json'
    row = rdj_custody.worker_row(study, rel, hashlib.sha256((study / rel).read_bytes()).hexdigest())
    assert row['verified_label'] == 'host_attested'
    found = report(study, 'host-done')
    assert found['attestation'] == 'self_attested' and not found['independent']
    assert not rp.satisfied(study, SPECIALIST)


def test_a_supervised_launch_with_a_transport_observation_earns_the_credit(study):
    """The same worker through launch and supervise: the adapter's observation is the label."""
    s = review_spec(study, 'supervised', SPECIALIST, 'discrepancy-attributor')
    done = supervised(study, s, final=FINAL, session='observed-session',
                      packet=review_packet(study, SPECIALIST, 'discrepancy-attributor'))
    assert done['status'] == 'ok' and done['attestation'] == 'transport_attested'
    actor = worker._record(study, 'supervised', 1)['actor']
    assert done['actor_id'] == actor['actor_id'] and actor['transport_id'] == 'synthetic-cli'
    assert report(study, 'supervised')['independent'] and rp.satisfied(study, SPECIALIST)
    # An observation that falls short of transport attestation stays short.
    weak = review_spec(study, 'weak', CRITIC, 'physics-critic')
    assert supervised(study, weak, final=FINAL, session='weak-session', attestation='host_attested',
                      packet=review_packet(study, CRITIC, 'physics-critic'))['status'] == 'ok'
    assert not report(study, 'weak')['independent'] and not rp.satisfied(study, CRITIC)


def test_custody_refuses_an_actor_row_that_is_not_its_own_digest(study):
    receipt(study, SPECIALIST, 'discrepancy-attributor', register=False)
    rel = 'agent-work/discrepancy-attributor1/1/receipt.json'
    actor = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', 'ws', 'discrepancy-attributor1/1')
    for forged in ({**actor, 'worker_session_id': 'other'}, {**actor, 'actor_id': 'a' * 64},
                   {k: v for k, v in actor.items() if k != 'family'}, 'declared'):
        with pytest.raises(ValueError, match='actor'):
            rdj_custody.register_worker_receipt(study, rel, verified_label='transport_attested', actor=forged)


# ---------------------------------------------------------------- every point class

@pytest.mark.parametrize('point_id, role', [(CRITIC, 'physics-critic'), (SPECIALIST, 'discrepancy-attributor'),
                                            (AUDITOR, 'normalization-auditor'), (MAPPER, 'object-selection-mapper')])
def test_a_dispatcher_assigned_actor_earns_credit_and_a_declared_or_missing_one_does_not(study, point_id, role,
                                                                                         inert_dispatch):
    assert point(study, point_id)['mode'] in rp.ACTOR_MODES
    receipt(study, point_id, role, 1, actor_id='declared-actor')
    receipt(study, point_id, role, 2, actor_id=None)
    assert not rp.satisfied(study, point_id)
    for number in (1, 2):
        found = report(study, role + str(number))
        assert found['advisory'] == 'actor_unassigned' and not found['independent']
    receipt(study, point_id, role, 3)
    assert rp.satisfied(study, point_id)
    # A credited seat reports its family label; the inert controller records no models, so it is unknown.
    assert report(study, role + '3') == {'path': f'agent-work/{role}3/1/receipt.json',
                                         'attestation': 'transport_attested', 'independent': True, 'advisory': None,
                                         'family_relation': 'unknown', 'label': 'separate session, model family unknown'}


def test_a_receipt_cannot_borrow_another_sessions_actor(study):
    """The registered actor names its own attempt and transport; a copy on another receipt is not that actor."""
    borrowed = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', 'ws-other', 'other-node/1')
    receipt(study, SPECIALIST, 'discrepancy-attributor', 1, actor_id=borrowed['actor_id'], register=False)
    rdj_custody.register_worker_receipt(study, 'agent-work/discrepancy-attributor1/1/receipt.json',
                                        verified_label='transport_attested', actor=borrowed)
    assert not rp.satisfied(study, SPECIALIST)
    own = rdj_custody.actor_record('other-transport', 'synthetic-model', 'ws-2', 'discrepancy-attributor2/1')
    receipt(study, SPECIALIST, 'discrepancy-attributor', 2, actor_id=own['actor_id'], register=False,
            transport={'id': 'synthetic-cli', 'transport_kind': 'cli-worker'})
    rdj_custody.register_worker_receipt(study, 'agent-work/discrepancy-attributor2/1/receipt.json',
                                        verified_label='transport_attested', actor=own)
    assert not rp.satisfied(study, SPECIALIST)


def test_voting_points_need_distinct_actors_and_fresh_sessions(study, inert_dispatch):
    """The three votes of one claim: a worker session, or an observed session, is credited once."""
    receipt(study, CRITIC, 'physics-critic', worker_session='shared-worker-session')
    receipt(study, VERIFIER, 'skeptical-verifier', worker_session='shared-worker-session')
    receipt(study, DECIDER, 'physics-decider', session_id='physics-critic1')
    # The critic's session is the one shared with both others; the verifier and the decider are
    # two distinct sessions. Never all three: the largest consistent set is those two.
    # New rule: a context shared by two seats is independent for neither: the critic and decider share one observed session.
    assert not rp.satisfied(study, CRITIC)
    assert rp.satisfied(study, VERIFIER) and not rp.satisfied(study, DECIDER)
    receipt(study, CRITIC, 'physics-critic', 2)
    assert rp.satisfied(study, CRITIC) and rp.satisfied(study, VERIFIER) and not rp.satisfied(study, DECIDER)


def synthetic(node, role, point_id, *, family='alpha', worker_session=None, session=None):
    actor = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', worker_session or 'ws-' + node, node + '/1',
                                     family=family)
    session_id = session or 's-' + node
    # The seat matcher reads the independence decision ``_receipt_records`` attaches to each record.
    return {'node_id': node, 'attempt': 1, 'review_point_id': point_id, 'role': {'id': role}, 'status': 'ok',
            'run_tree': {'modified': False}, 'final_record': {'valid': True}, 'session_id': session_id,
            'actor_id': actor['actor_id'], 'model': {'family': family}, '_label': 'transport_attested', '_actor': actor,
            '_independence': {'independent': True, 'advisory': None, 'dispatch_id': 'synthetic:' + node,
                              'context_id': session_id, 'exposure': None}}


def panel(count=3, **role):
    return {'id': 'P1', 'row': 4, 'claim_id': 'C1', 'mode': 'voting', 'attestation_min': 'transport',
            'roles': [{'role': 'voter', 'count': count, 'distinct_family_from': [], **role}]}


def test_a_voting_point_with_count_k_needs_k_distinct_actor_ids():
    import itertools
    one, same_worker, same_session = (synthetic('v1', 'voter', 'P1'), synthetic('v2', 'voter', 'P1', worker_session='ws-v1'),
                                      synthetic('v3', 'voter', 'P1', session='s-v1'))
    unassigned = {**synthetic('v4', 'voter', 'P1'), '_actor': None}
    # A session shared either way is one vote, and a receipt without an assigned actor is none.
    for pair in ([one, same_worker], [one, same_session], [one, unassigned]):
        assert rp._missing([panel()], pair)['P1'] == [{'role': 'voter', 'count': 2, 'distinct_family_from': []}]
    # v2 and v3 each share a session with v1 and none with each other: two distinct votes, in any order.
    votes = [one, same_worker, same_session, unassigned]
    for order in itertools.permutations(votes):
        assert rp._missing([panel()], list(order))['P1'] == [{'role': 'voter', 'count': 1, 'distinct_family_from': []}]
    votes += [synthetic('v5', 'voter', 'P1'), synthetic('v6', 'voter', 'P1')]
    assert rp._missing([panel()], votes)['P1'] == []


def test_a_same_family_reviewer_in_a_separate_session_is_credited():
    first = {'id': 'P0', 'row': 4, 'claim_id': 'C1', 'mode': 'voting', 'attestation_min': 'transport',
             'roles': [{'role': 'author', 'count': 1, 'distinct_family_from': []}]}
    second = panel(count=1)
    author = synthetic('a1', 'author', 'P0', family='alpha')
    # One family, two observed sessions: two independent seats. An unknown family changes nothing.
    for family in ('alpha', None, 'beta'):
        assert rp._missing([first, second], [author, synthetic('v1', 'voter', 'P1', family=family)]) == \
            {'P0': [], 'P1': []}
    # The author's session, observed again or drawn again by the dispatcher, earns no second seat.
    for shared in (synthetic('v2', 'voter', 'P1', session='s-a1'), synthetic('v3', 'voter', 'P1', worker_session='ws-a1')):
        assert rp._missing([first, second], [author, shared])['P1'] == [{'role': 'voter', 'count': 1,
                                                                       'distinct_family_from': []}]


def test_producer_points_need_distinct_actors_and_a_producer_never_reviews(study, inert_dispatch):
    assert point(study, PRODUCER)['mode'] == 'producer' and point(study, PRODUCER)['roles'][0]['count'] == 2
    receipt(study, PRODUCER, 'analysis-author', 1)
    receipt(study, PRODUCER, 'analysis-author', 2, worker_session='ws-analysis-author1')
    assert not rp.satisfied(study, PRODUCER)
    receipt(study, PRODUCER, 'analysis-author', 3)
    assert rp.satisfied(study, PRODUCER)
    # The producer's own session, by its observed session or its worker session, earns no reviewer credit.
    receipt(study, MAPPER, 'object-selection-mapper', 1, session_id='analysis-author1')
    receipt(study, MAPPER, 'object-selection-mapper', 2, worker_session='ws-analysis-author3')
    assert not rp.satisfied(study, MAPPER)
    # Neither does a receipt whose final record is a producer record.
    final = study / 'agent-work/object-selection-mapper3/1/final.json'
    final.parent.mkdir(parents=True)
    final.write_text('{"findings": []}')
    receipt(study, MAPPER, 'object-selection-mapper', 3,
            final_record={'valid': True, 'path': 'final.json', 'schema': 'producer.v1',
                          'sha256': hashlib.sha256(final.read_bytes()).hexdigest()})
    assert not rp.satisfied(study, MAPPER)
    receipt(study, MAPPER, 'object-selection-mapper', 4)
    assert rp.satisfied(study, MAPPER)


def test_blind_auditor_credit_needs_a_separate_attested_actor(study, inert_dispatch):
    card = __import__('ravel.workflow.role_registry', fromlist=['load']).load('normalization-auditor')
    assert card['requires']['blind'] is True and point(study, AUDITOR)['attestation_min'] == 'transport'
    receipt(study, PRODUCER, 'analysis-author', 1)
    receipt(study, AUDITOR, 'normalization-auditor', 1, session_id='analysis-author1')
    receipt(study, AUDITOR, 'normalization-auditor', 2, verified_label='host_attested')
    receipt(study, AUDITOR, 'normalization-auditor', 3, actor_id='declared')
    assert not rp.satisfied(study, AUDITOR)
    receipt(study, AUDITOR, 'normalization-auditor', 4)
    assert rp.satisfied(study, AUDITOR)


def test_an_earlier_version_two_receipt_has_no_actor_and_earns_no_actor_credit(study):
    """A version-2 receipt written before actors existed still loads as a record; it is advisory here."""
    receipt(study, SPECIALIST, 'discrepancy-attributor', 1, actor_id=None)
    found = report(study, 'discrepancy-attributor1')
    assert found['advisory'] == 'actor_unassigned' and not rp.satisfied(study, SPECIALIST)
    assert worker.RECEIPT_VERSIONS[2] < worker.RECEIPT_VERSIONS[3]
    assert worker.RECEIPT_VERSIONS[3] - worker.RECEIPT_VERSIONS[2] == {'execution_mode'}


def test_the_spawn_rows_use_the_same_actor_rule(study):
    """A staffing row counts receipts through the same check: a declared actor fills none of its roles."""
    from ravel.workflow import spawn_rows
    pending = {p['id'] for p in spawn_rows.pending(study)}
    assert pending
    target = next(p for p in spawn_rows.derive(rp._facts(study)) if p['id'] in pending and p['roles'])
    role = target['roles'][0]
    for number in range(role['count']):
        node = f'spawn-{number}'
        final = study / 'agent-work' / node / '1/final.json'
        final.parent.mkdir(parents=True)
        final.write_text('{"findings": []}')
        value = {'schema_version': 3, 'kind': 'agent-worker-receipt', 'node_id': node, 'attempt': 1,
                 'review_point_id': target['id'], 'role': {'id': role['role']}, 'status': 'ok',
                 'execution_mode': 'transport_attested_cli', 'review_subject': rp.review_subject(rp._facts(study), target),
                 'session_id': node, 'actor_id': 'declared-' + node, 'run_tree': {'modified': False},
                 'model': {'family': 'alpha'},
                 'final_record': {'valid': True, 'path': 'final.json',
                                  'sha256': hashlib.sha256(final.read_bytes()).hexdigest()}}
        (final.parent / 'receipt.json').write_text(json.dumps(value))
        rdj_custody.register_worker_receipt(study, f'agent-work/{node}/1/receipt.json',
                                            verified_label='transport_attested')
    still = next(p for p in spawn_rows.pending(study) if p['id'] == target['id'])
    assert still['roles'] == target['roles']


# ---------------------------------------------------------------- RDJ role calls use the same actor rule

RDJ = {'case_id': 'case-1', 'slot': 'critic-1', 'payload_sha256': 'a' * 64}
REQUEST = {'role': 'critic', 'agent_role': 'decision-critic', 'graph_root': 'rdj/graphs/case-1', **RDJ}


def rdj_receipt(root, node, *, version, declared, assigned, label='transport_attested', mode='transport_attested_cli'):
    """An RDJ role-call receipt in the run, registered with a label and, when ``assigned``, the dispatcher's actor."""
    folder = root / 'agent-work' / node / '1'
    folder.mkdir(parents=True)
    (folder / 'final.json').write_text('{"findings": []}')
    actor = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', 'ws-' + node, node + '/1', family='alpha')
    value = {'schema_version': version, 'kind': 'agent-worker-receipt', 'node_id': node, 'attempt': 1, 'status': 'ok',
             'role': {'id': 'decision-critic'}, 'rdj': dict(RDJ), 'session_id': 'session-' + node,
             'actor_id': actor['actor_id'] if assigned else declared,
             'transport': {'id': 'synthetic-cli', 'transport_kind': 'cli-worker'}, 'model': {'family': 'alpha'},
             'final_record': {'path': 'final.json', 'valid': True,
                              'sha256': hashlib.sha256((folder / 'final.json').read_bytes()).hexdigest()},
             **({'execution_mode': mode} if mode else {})}
    (folder / 'receipt.json').write_text(json.dumps(value))
    rel = f'agent-work/{node}/1/receipt.json'
    rdj_custody.register_worker_receipt(root, rel, verified_label=label, **({'actor': actor} if assigned else {}))
    return {'kind': 'worker_receipt', 'path': rel}, actor


@pytest.mark.parametrize('version', [1, 2, 3])
@pytest.mark.parametrize('declared', ['declared-actor', None])
def test_an_rdj_role_call_takes_no_identity_from_a_declared_or_missing_actor(study, version, declared):
    """A registered, transport-labelled receipt that only states an actor supplies no reviewer identity."""
    ref, _ = rdj_receipt(study, 'rdj-declared', version=version, declared=declared, assigned=False)
    _, session, _ = rdj_loop._resolve(study, REQUEST, ref)
    assert session['actor_id'] != declared and session['actor_id'].startswith('unassigned:')
    assert session['attestation'] == 'self_attested'


@pytest.mark.parametrize('version', [1, 2, 3])
def test_an_rdj_role_call_carries_the_actor_the_dispatcher_registered(study, version, inert_dispatch):
    ref, actor = rdj_receipt(study, 'rdj-assigned', version=version, declared=None, assigned=True)
    _, session, family = rdj_loop._resolve(study, REQUEST, ref)
    assert session == {'actor_id': actor['actor_id'], 'session_receipt': 'synthetic-cli:session-rdj-assigned',
                       'attestation': 'transport_attested'}
    assert family == 'alpha'
    # The registered label still bounds the label, and another session's actor is not this receipt's.
    weak, _ = rdj_receipt(study, 'rdj-weak', version=version, declared=None, assigned=True, label='host_attested')
    assert rdj_loop._resolve(study, REQUEST, weak)[1]['attestation'] == 'self_attested'


def test_the_dispatcher_registers_an_rdj_worker_with_its_actor_and_label(study, inert_dispatch):
    """Ordinary RDJ worker publication: the supervised launch registers the assigned actor and the observed label."""
    s = spec('rdj-worker')
    s['role'] = {'id': 'decision-critic', 'version': '1', 'card_sha256': '1' * 64}
    s['rdj_challenges'] = dict(RDJ)
    done = supervised(study, s, final=FINAL, session='observed-rdj-session')
    assert done['status'] == 'ok' and done['schema_version'] == 1 and done['rdj'] == RDJ
    rel = 'agent-work/rdj-worker/1/receipt.json'
    row = rdj_custody.worker_row(study, rel, hashlib.sha256((study / rel).read_bytes()).hexdigest())
    actor = worker._record(study, 'rdj-worker', 1)['actor']
    assert row['actor'] == actor and row['verified_label'] == 'transport_attested'
    _, session, _ = rdj_loop._resolve(study, REQUEST, {'kind': 'worker_receipt', 'path': rel})
    assert session == {'actor_id': actor['actor_id'], 'session_receipt': 'synthetic-cli:observed-rdj-session',
                       'attestation': 'transport_attested'}
    # The same worker completed by the host, with no supervised launch, is not transport-attested.
    host = spec('rdj-host')
    host['role'], host['rdj_challenges'] = s['role'], {**RDJ, 'slot': 'critic-2'}
    worker.materialize(study, host)
    worker.bind_actor(study, 'rdj-host', 1, transport_id='synthetic-cli', model_id='synthetic-model')
    worker.finish(study, host, final=FINAL, execution={
        'exit_status': 0, 'session_id': 'host-session', 'attestation': 'transport_attested',
        'transport': descriptor()['transport'], 'model': descriptor()['model']})
    _, session, _ = rdj_loop._resolve(study, {**REQUEST, 'slot': 'critic-2'},
                                      {'kind': 'worker_receipt', 'path': 'agent-work/rdj-host/1/receipt.json'})
    assert session['attestation'] == 'self_attested'


def test_an_rdj_graph_role_call_takes_no_identity_from_the_host_response(tmp_path, monkeypatch):
    """The agent-graph route: the identity is the dispatcher's own request, never actor text a host returns."""
    pytest.importorskip('langgraph')
    from rdj_fixtures import Run, critic, reviewer, two_level_r2, verifier
    from test_rdj_loop import GraphHost
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    stated = 'stated-by-the-host'
    run = Run(tmp_path / 'run')
    host = GraphHost({'edge_reviewer': reviewer(name=stated), 'critic': critic(name=stated),
                      'verifier': verifier(name=stated)})
    rdj_custody.register_host(run.root, host.identity)
    case_id = two_level_r2(run, roles=rdj_loop.AgentHostDispatcher(host, model='m'))
    rdj_loop.run_roles(run.root, case_id, rdj_loop.AgentHostDispatcher(host, model='m'))
    case = run.case(case_id)
    sessions = [e['review']['reviewer'] for e in case['edges']] + [case['critique']['reviewer'],
                                                                   case['verification']['reviewer']]
    ids = [s['actor_id'] for s in sessions]
    assert stated not in ids and all(len(i) == 64 and set(i) <= set('0123456789abcdef') for i in ids)
    # One identity per request the dispatcher issued: the critic and the verifier are two actors.
    assert case['critique']['reviewer']['actor_id'] != case['verification']['reviewer']['actor_id']
    assert {s['attestation'] for s in sessions} == {'transport_attested'}


# ---------------------------------------------------------------- production dispatch earns its producer point

AUTHORED = {'id': 'N3', 'operation': 'authored-analysis', 'rung': 'full', 'authors': 'analysis_code',
            'authored': {'kind': 'analysis_code', 'path': 'analysis/selection.py'}}


@pytest.fixture
def authored_run(tmp_path, monkeypatch):
    from executor_fixtures import no_self_checks, plan, run_root
    from ravel.workflow import production_executor
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = run_root(tmp_path)
    plan(root, nodes=[AUTHORED])
    no_self_checks(monkeypatch)
    production_executor.seal_orders(root)
    return root


def produce(rundir, s, **options):
    """A production worker through the transport path: its order's outputs by the broker, then supervision."""
    from test_agent_worker import put
    ws = worker.materialize(rundir, s)
    order = json.loads((ws / 'inputs/work-order.json').read_text())
    sidecar = {'node_id': order['node_id'],
               'obligations': {row['id']: {'checked': True, 'by': s['role']['id']} for row in order['obligations']}}
    for output in order['declared_outputs']:
        put(rundir, ws, output['path'], json.dumps(sidecar))
    return supervised(rundir, s, final={'completed': True}, session='session-' + s['node_id'])


def test_ordinary_production_dispatch_earns_its_producer_review_point(authored_run, monkeypatch):
    """The node's own production work is the producer obligation: its dispatch names the point and subject."""
    from ravel.workflow import production_executor
    root, point_id = authored_run, 'RP2:N3'
    target = point(root, point_id)
    assert target['mode'] == 'producer' and target['blocking'] and target['gate'] == 'launch'
    assert target['roles'] == [{'role': 'analysis-author', 'count': 1, 'distinct_family_from': []}]
    pending = [e for e in rp.gate_errors(root, 'launch', {'node_id': 'N3'}) if e.code == 'review_point_pending']
    assert [pin for e in pending for pin in e.pins] == ['RP2:N3:analysis-author:1']
    s = production_executor.worker_spec(root, 'N3')
    assert s['parent']['review_point_id'] == point_id and s['parent']['map_id'] == 'production:N3'
    assert s['parent']['review_subject'] == rp.review_subject(rp._facts(root), target)
    monkeypatch.setattr(worker, 'dispatch', produce)
    done = production_executor.dispatch(root, 'N3')
    assert done['status'] == 'ok' and done['schema_version'] == 3 and done['review_point_id'] == point_id
    assert done['execution_mode'] == 'transport_attested_cli' and done['final_record']['schema'] == 'producer.v1'
    actor = worker._record(root, 'N3', 1)['actor']
    row = rdj_custody.worker_row(root, 'agent-work/N3/1/receipt.json',
                                 hashlib.sha256((root / 'agent-work/N3/1/receipt.json').read_bytes()).hexdigest())
    assert row['actor'] == actor and row['verified_label'] == 'transport_attested' and done['actor_id'] == actor['actor_id']
    assert rp.satisfied(root, point_id)
    assert not [e for e in rp.gate_errors(root, 'launch', {'node_id': 'N3'}) if e.code == 'review_point_pending']
    # The executor still reads the same receipt as the node's production credit.
    assert production_executor.worker_receipt(root, 'N3')['actor_id'] == actor['actor_id']


def test_a_production_retry_is_a_fresh_actor_with_its_own_registration(authored_run):
    """A failed first attempt earns nothing; the retry is another worker session and earns the point."""
    from ravel.workflow import production_executor
    root, rows = authored_run, {}
    first = production_executor.worker_spec(root, 'N3')
    worker.materialize(root, first)
    assert supervised(root, first, final={'completed': True}, session='session-first')['status'] == 'failed'
    assert not rp.satisfied(root, 'RP2:N3') and production_executor.worker_receipt(root, 'N3') is None
    second = production_executor.worker_spec(root, 'N3', 2)
    assert second['parent'] == first['parent']
    assert produce(root, second)['status'] == 'ok'
    for attempt in (1, 2):
        rel = f'agent-work/N3/{attempt}/receipt.json'
        rows[attempt] = rdj_custody.worker_row(root, rel, hashlib.sha256((root / rel).read_bytes()).hexdigest())
        assert rows[attempt]['actor'] == worker._record(root, 'N3', attempt)['actor']
    assert rows[1]['actor']['actor_id'] != rows[2]['actor']['actor_id']
    assert rows[1]['actor']['attempt_id'] == 'N3/1' and rows[2]['actor']['attempt_id'] == 'N3/2'
    assert rp.satisfied(root, 'RP2:N3')


def test_a_host_waiver_records_no_producer_and_earns_no_producer_credit(authored_run):
    """A waiver is an operational record of who authors the node; it is not review credit."""
    from ravel.workflow import production_executor
    production_executor.waive(authored_run, 'N3', 'the host authors this synthetic node')
    assert production_executor.waiver_errors(authored_run, 'N3') == []
    assert not rp.satisfied(authored_run, 'RP2:N3')
    assert not (authored_run / 'agent-work').exists()


def test_a_node_without_a_producer_point_keeps_its_plain_production_dispatch(tmp_path, monkeypatch):
    from executor_fixtures import plan, run_root
    from ravel.workflow import production_executor
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = run_root(tmp_path)
    plan(root, nodes=[{'id': 'N2', 'operation': 'event-production', 'rung': 'full', 'tool': 'synthetic-tool'}])
    production_executor.seal_orders(root)
    parent = production_executor.worker_spec(root, 'N2')['parent']
    assert parent == {'review_point_id': None, 'map_id': 'production:N2', 'rca_ticket': None}


def test_two_producer_obligations_on_one_node_are_refused_not_dispatched_twice(authored_run, monkeypatch):
    from ravel.workflow import production_executor
    derive = rp.derive

    def doubled(facts):
        points = derive(facts)
        twin = next(p for p in points if p['id'] == 'RP2:N3')
        return points + [{**twin, 'id': 'RP2:N3:second'}]
    monkeypatch.setattr(rp, 'derive', doubled)
    with pytest.raises(ValueError, match='RP2:N3, RP2:N3:second'):
        production_executor.worker_spec(authored_run, 'N3')
    with pytest.raises(ValueError, match='one receipt credits one producer review point'):
        production_executor.dispatch(authored_run, 'N3')


# ---------------------------------------------------------------- families come from the registration

AUTHOR = {'id': 'P0', 'row': 4, 'claim_id': 'C1', 'mode': 'voting', 'attestation_min': 'transport',
          'roles': [{'role': 'author', 'count': 1, 'distinct_family_from': []}]}


def test_a_retired_family_list_on_a_role_entry_changes_nothing():
    # A role entry that still names distinct_family_from is credited by sessions alone, whatever the families.
    reviewer = panel(count=1, distinct_family_from=['author'])
    author = synthetic('a1', 'author', 'P0', family='alpha')
    for voter in (synthetic('v1', 'voter', 'P1', family='alpha'), synthetic('v2', 'voter', 'P1', family=None),
                  {**synthetic('v3', 'voter', 'P1', family='alpha'), 'model': {'family': 'beta'}}):
        assert rp._missing([AUTHOR, reviewer], [author, voter]) == {'P0': [], 'P1': []}
    # Without the named role's receipt the reviewer seat is still filled; the author seat stays open.
    assert rp._missing([AUTHOR, reviewer], [synthetic('v4', 'voter', 'P1', family='beta')])['P1'] == []


def test_a_receipt_whose_family_differs_from_its_registration_has_no_actor(study):
    receipt(study, SPECIALIST, 'discrepancy-attributor', 1, register=False)
    rel = 'agent-work/discrepancy-attributor1/1/receipt.json'
    stated = json.loads((study / rel).read_text())
    actor = rdj_custody.actor_record('synthetic-cli', 'synthetic-model', 'ws-discrepancy-attributor1',
                                     'discrepancy-attributor1/1', family='alpha')
    assert stated['model']['family'] != 'alpha' and stated['actor_id'] == actor['actor_id']
    rdj_custody.register_worker_receipt(study, rel, verified_label='transport_attested', actor=actor)
    assert rp.registered_actor(stated, {'actor': actor}) is None
    assert report(study, 'discrepancy-attributor1')['advisory'] == 'actor_unassigned'
    assert not rp.satisfied(study, SPECIALIST)
    # An unknown family on either side is not a disagreement; it is simply unknown.
    assert rp.registered_actor({**stated, 'model': {'family': None}}, {'actor': actor}) == actor


# ---------------------------------------------------------------- a producer is excluded from its own output only

def test_an_unregistered_producer_record_denies_no_reviewer(study, inert_dispatch):
    """Producer identity comes from verified custody; a loose record naming a reviewer's session changes nothing."""
    reviewer = receipt(study, SPECIALIST, 'discrepancy-attributor', 1)
    assert rp.satisfied(study, SPECIALIST)
    final = study / 'agent-work/analysis-author1/1/final.json'
    final.parent.mkdir(parents=True)
    final.write_text('{"findings": []}')
    forged = {'session_id': reviewer['session_id'], 'actor_id': reviewer['actor_id'],
              'final_record': {'valid': True, 'path': 'final.json', 'schema': 'producer.v1',
                               'sha256': hashlib.sha256(final.read_bytes()).hexdigest()}}
    receipt(study, PRODUCER, 'analysis-author', 1, register=False, **forged)
    assert rp.satisfied(study, SPECIALIST)
    # Registered, but with an actor it only declares: still no producer identity.
    final2 = study / 'agent-work/analysis-author2/1/final.json'
    final2.parent.mkdir(parents=True)
    final2.write_text('{"findings": []}')
    receipt(study, PRODUCER, 'analysis-author', 2, **{**forged, 'final_record': {
        **forged['final_record'], 'sha256': hashlib.sha256(final2.read_bytes()).hexdigest()}})
    assert rp.satisfied(study, SPECIALIST)


def test_a_producer_is_excluded_from_its_own_claim_and_not_from_an_independent_one(tmp_path, monkeypatch,
                                                                                   inert_dispatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'run'
    root.mkdir()
    run(root, claims=[CLAIM, {**CLAIM, 'id': 'C2'}])
    receipt(root, PRODUCER, 'analysis-author', 1)
    # The same session reviewing the claim it produced earns nothing ...
    receipt(root, MAPPER, 'object-selection-mapper', 1, session_id='analysis-author1')
    assert not rp.satisfied(root, MAPPER)
    # ... and, new rule, an observed session the producer used is independent at no point, whatever the claim.
    receipt(root, 'RP6:C2', 'object-selection-mapper', 2, session_id='analysis-author1')
    assert not rp.satisfied(root, 'RP6:C2')
    # A reviewer that shares only the producer's worker session is a valid reviewer of the other claim, whose
    # output it did not produce.
    receipt(root, 'RP6:C2', 'object-selection-mapper', 4, worker_session='ws-analysis-author1')
    assert rp.satisfied(root, 'RP6:C2')
    # Review of the whole delivery covers every claim: no producer of the run reviews it.
    parent = next(p for p in rp.derive(rp._facts(root)) if p['row'] == 11 and p['mode'] in rp.REVIEWER_MODES)
    receipt(root, parent['id'], parent['roles'][0]['role'], 3, session_id='analysis-author1')
    assert not rp.satisfied(root, parent['id'])


# ---------------------------------------------------------------- credit does not depend on traversal order

def test_a_fresh_retry_is_chosen_when_the_first_receipt_shares_the_reviewers_session():
    reviewer = panel(count=1)
    earlier = synthetic('a1', 'author', 'P0', session='s-v1')
    retry = synthetic('a2', 'author', 'P0')
    vote_ = synthetic('v1', 'voter', 'P1')
    for receipts in ([earlier, retry, vote_], [retry, earlier, vote_], [vote_, earlier, retry]):
        assert rp._missing([AUTHOR, reviewer], receipts) == {'P0': [], 'P1': []}


def test_points_are_credited_in_any_listed_order():
    reviewer = panel(count=1)
    receipts = [synthetic('a1', 'author', 'P0', family='alpha'), synthetic('v1', 'voter', 'P1', family='alpha')]
    assert rp._missing([reviewer, AUTHOR], receipts) == rp._missing([AUTHOR, reviewer], receipts) == {'P1': [], 'P0': []}


def test_one_session_string_from_two_transports_is_two_sessions():
    def on(transport, node):
        actor = rdj_custody.actor_record(transport, 'synthetic-model', 'ws-' + node, node + '/1', family='alpha')
        return {**synthetic(node, 'voter', 'P1', session='1'), 'actor_id': actor['actor_id'], '_actor': actor}
    assert rp._missing([panel(count=2)], [on('transport-a', 'v1'), on('transport-b', 'v2')])['P1'] == []
    # The same string on one transport is one session.
    assert rp._missing([panel(count=2)], [on('transport-a', 'v1'), on('transport-a', 'v3')])['P1']


def test_a_shared_session_does_not_cost_a_point_its_fresh_receipt():
    """Two points of one claim: the first has a receipt that shares a session with the second's only receipt, and a fresh one."""
    first = {**AUTHOR, 'id': 'PA', 'roles': [{'role': 'first', 'count': 1, 'distinct_family_from': []}]}
    second = {**AUTHOR, 'id': 'PB', 'roles': [{'role': 'second', 'count': 1, 'distinct_family_from': []}]}
    shared = synthetic('f1', 'first', 'PA', session='shared')
    fresh = synthetic('f2', 'first', 'PA')
    other = synthetic('s1', 'second', 'PB', session='shared')
    for receipts in ([shared, fresh, other], [other, fresh, shared]):
        assert rp._missing([first, second], receipts) == {'PA': [], 'PB': []}
    assert rp._missing([first, second], [shared, other])['PB']


def test_named_roles_no_longer_order_or_block_credit():
    """Roles a point names in its retired family list are not waited for: sessions alone decide."""
    def at(point_id, role, **entry):
        return {**AUTHOR, 'id': point_id, 'roles': [{'role': role, 'count': 1, 'distinct_family_from': [], **entry}]}
    points = [at('P1', 'voter', distinct_family_from=['author']), at('P2', 'author'),
              at('P3', 'author', distinct_family_from=['source']), at('P4', 'source')]
    receipts = [synthetic('s1', 'source', 'P4', family='gamma'), synthetic('a1', 'author', 'P2', family='alpha'),
                synthetic('a2', 'author', 'P3', family='beta'), synthetic('v1', 'voter', 'P1', family='beta')]
    for order in (points, points[::-1]):
        assert not any(rp._missing(order, receipts).values())
