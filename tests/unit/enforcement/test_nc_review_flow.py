"""Review-flow rows: credit is bound to the exact subject, a separate context and the RAVEL-built packet.

The adversary copies a verdict onto another subject or declares a role name, reviews work whose
lineage it authored in an earlier phase, delivers a meta-review through a relay or as the producer,
and presents a packet other than the projection the controller built, or reads the author's workspace
from the reviewer seat. Oracles are the one credit decision (``review_independence.decide``) over the
controller's own store records, the seat-session recorder's refusal, and the sandboxed worker's
observed reads and outputs; positive controls credit the exact binding of a fresh, separate session.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

META = 'research-meta-reviewer'


def _helpers():
    import test_nc_review_credit as credit
    return credit


def _review_record(query, session_id, *, lineage=('session-producer',), packet=None, **changes):
    credit = _helpers()
    record = credit._review(query, session_id)
    record['subject_session_ids'] = list(lineage)
    if packet is not None:
        record['packet'] = packet
    record.update(changes)
    return record


@case('V02', binding=CONTROLLER)
def test_V02_credit_binds_the_exact_subject_and_receipt_never_a_copied_verdict_or_a_declared_role(nc):
    require_controller('store')
    from ravel.workflow import review_dispatch, review_independence as independence
    credit = _helpers()
    _, _, query = credit._recorded(nc)
    assert independence.decide(query)['independent'] is True  # positive control
    for field, value in (('subject_sha256', 'e' * 64), ('receipt_sha256', '9' * 64), ('output_sha256', '8' * 64)):
        copied = independence.decide(dict(query, **{field: value}))
        assert copied['independent'] is False, (field, copied)
    assert independence.decide(dict(query, role='plan-critic'))['independent'] is False
    # A role declared in the review record only: the seat session the controller started is another role's.
    store, run_dir = controller_run(nc, 'nc-run-declared')
    review_dispatch.record_session(store, credit._session('session-producer', credit.PRODUCER, 'producer',
                                                         'actor-producer'))
    review_dispatch.record_session(store, credit._session('session-declared', 'analysis-author', 'reviewer',
                                                         'actor-declared'))
    declared = credit._query(run_dir)
    review_dispatch.record_review(store, _review_record(declared, 'session-declared'))
    assert independence.decide(declared)['independent'] is False


def _binding_by_run_only(original):
    """The store evidence is found by run alone and rebound to whatever the consumer asked."""
    def store_lookup(query, store):
        from ravel.workflow import review_dispatch as dispatch
        for review in dispatch._records(store, dispatch.REVIEW_KIND):
            binding = review.get('binding') if isinstance(review, dict) else None
            if isinstance(binding, dict) and binding.get('run') == query.get('run'):
                proof = original(dict(binding), store)
                return dict(proof, binding=deepcopy(query)) if proof else None
        return None
    return store_lookup


register(Mutation('M16', 'ravel.workflow.review_dispatch:store_lookup', _binding_by_run_only, ('V02',),
                  binding=MUTATION_CONTROLLER, why='a verdict counts for any subject of the run it was recorded in'))


@case('V03', binding=CONTROLLER)
def test_V03_a_reviewer_who_authored_part_of_the_subject_in_an_earlier_phase_is_never_credited(nc):
    require_controller('store')
    from ravel.workflow import review_dispatch, review_independence as independence
    credit = _helpers()
    store, run_dir = controller_run(nc, 'nc-run-phases')
    earlier = dict(credit._session('session-prepare', credit.PRODUCER, 'producer', 'actor-x'), step_id='s01')
    review_dispatch.record_session(store, earlier)
    review_dispatch.record_session(store, credit._session('session-producer', credit.PRODUCER, 'producer',
                                                         'actor-producer'))
    lineage = ('session-prepare', 'session-producer')
    # The earlier phase's session continues as the reviewer of a later phase.
    reused = dict(credit._query(run_dir), subject_sha256='1' * 64)
    review_dispatch.record_session(store, credit._session('session-prepare', credit.REVIEWER, 'reviewer', 'actor-x'))
    review_dispatch.record_review(store, _review_record(reused, 'session-prepare', lineage=lineage))
    assert independence.decide(reused)['independent'] is False
    # A fresh session of the actor that produced an upstream node of the subject in the earlier phase.
    upstream = dict(credit._query(run_dir), subject_sha256='2' * 64)
    review_dispatch.record_session(store, credit._session('session-x-review', credit.REVIEWER, 'reviewer', 'actor-x'))
    review_dispatch.record_review(store, _review_record(upstream, 'session-x-review', lineage=lineage))
    assert independence.decide(upstream)['independent'] is False
    # Positive control: a fresh session of an actor that produced nothing in the subject's lineage.
    clean = dict(credit._query(run_dir), subject_sha256='3' * 64)
    review_dispatch.record_session(store, credit._session('session-clean', credit.REVIEWER, 'reviewer', 'actor-clean'))
    review_dispatch.record_review(store, _review_record(clean, 'session-clean', lineage=lineage))
    assert independence.decide(clean)['independent'] is True


def _lineage_forgotten(original):
    def records(store, kind):
        rows = original(store, kind)
        return [dict(r, subject_session_ids=[]) if isinstance(r, dict) and 'binding' in r else r for r in rows]
    return records


register(Mutation('M16', 'ravel.workflow.review_dispatch:_records', _lineage_forgotten, ('V03',),
                  binding=MUTATION_CONTROLLER, why='the subject\'s producer lineage is not part of the census'))


@case('V08', binding=CONTROLLER)
def test_V08_a_meta_review_through_a_relay_or_by_the_producer_is_never_a_seat(nc):
    require_controller('store')
    from ravel.workflow import review_dispatch, review_independence as independence
    credit = _helpers()
    store, run_dir = controller_run(nc, 'nc-run-meta')
    review_dispatch.record_session(store, credit._session('session-producer', credit.PRODUCER, 'producer',
                                                         'actor-producer'))
    for kind in ('external-relay', 'host-subagent', 'cli-oneshot'):
        with pytest.raises(ValueError):
            review_dispatch.record_session(store, credit._session(f'session-{kind}', META, 'reviewer', 'actor-relay',
                                                                 transport_kind=kind))
    # The producer's own actor in a fresh session on the meta-review seat.
    by_producer = dict(credit._query(run_dir), role=META, subject_sha256='4' * 64)
    review_dispatch.record_session(store, credit._session('session-meta-producer', META, 'reviewer', 'actor-producer'))
    review_dispatch.record_review(store, _review_record(by_producer, 'session-meta-producer', seat=META))
    assert independence.decide(by_producer)['independent'] is False
    # Positive control: a fresh, distinct meta-reviewer session is credited.
    distinct = dict(credit._query(run_dir), role=META, subject_sha256='5' * 64)
    review_dispatch.record_session(store, credit._session('session-meta', META, 'reviewer', 'actor-meta'))
    review_dispatch.record_review(store, _review_record(distinct, 'session-meta', seat=META))
    assert independence.decide(distinct)['independent'] is True


register(Mutation('M06', 'ravel.workflow.review_dispatch:SEATLESS_TRANSPORTS', lambda original: frozenset(), ('V08',),
                  binding=MUTATION_CONTROLLER, why='a relay or one-shot session may hold a review seat'))


@case('I06', binding=CONTROLLER)
def test_I06_credit_needs_the_ravel_built_packet_and_a_reviewer_cannot_read_the_author_workspace(nc):
    require_controller('store')
    from ravel.workflow import review_dispatch, review_independence as independence
    credit = _helpers()
    store, run_dir = controller_run(nc, 'nc-run-packet')
    review_dispatch.record_session(store, credit._session('session-producer', credit.PRODUCER, 'producer',
                                                         'actor-producer'))
    review_dispatch.record_session(store, credit._session('session-reviewer', credit.REVIEWER, 'reviewer',
                                                         'actor-reviewer'))
    projected = 'd' * 64
    query = dict(credit._query(run_dir), packet_sha256=projected)
    review_dispatch.record_review(store, _review_record(query, 'session-reviewer'))
    assert independence.decide(query)['independent'] is True  # positive control: the projection it was given
    other = dict(credit._query(run_dir), subject_sha256='6' * 64, packet_sha256='7' * 64)
    review_dispatch.record_review(store, _review_record(other, 'session-reviewer'))
    assert independence.decide(other)['independent'] is False, 'a packet other than the projection is not credited'
    authored = dict(credit._query(run_dir), subject_sha256='8' * 64)
    packet = {'builder': 'author-summary', 'projection_verified': False, 'author_summary': True,
              'sha256': projected, 'subject_sha256': authored['subject_sha256']}
    review_dispatch.record_review(store, _review_record(authored, 'session-reviewer', packet=packet))
    assert independence.decide(authored)['independent'] is False
    # The reviewer seat's own process cannot read a planted author-only canary outside its packet.
    from nc_adversary import InstalledWorker, sandbox_or_skip
    sandbox_or_skip(nc)
    canary = nc.effects.canary('author-only')
    author = nc.path('author-workspace', 'notes.txt')
    author.write_text(f'the producer concludes: {canary.value}\n')
    worker = InstalledWorker(nc)
    worker.scenario({'actions': [{'op': 'native_read', 'path': str(author)},
                                 {'op': 'call', 'name': 'ws_write',
                                  'arguments': {'path': 'outputs/result.txt', 'content': 'fictional review'}}],
                     'final': {'completed': True, 'summary': 'fictional review written'}})
    spec = worker.spec(role=credit.REVIEWER)
    receipt = worker.dispatch(spec)
    tried = [a for a in worker.adversary_log(spec)['log'] if a['op'] == 'native_read']
    assert tried and tried[0].get('ok') is not True, tried
    assert canary.found_in(worker.workspace(spec)) == [] and canary.value not in str(receipt)


register(Mutation('M16', 'ravel.workflow.review_independence:decide',
                  lambda original: lambda query: original(dict(query, packet_sha256=None) if type(query) is dict
                                                          and 'packet_sha256' in query else query),
                  ('I06',), binding=MUTATION_CONTROLLER, why='any packet digest is accepted for credit'))


@case('V01', binding=CONTROLLER)
def test_V01_review_seats_derive_from_installed_data_whatever_the_run_tree_or_the_plan_says(nc):
    graph = require_controller('step.graph')
    import json
    from importlib.resources import files
    from ravel.workflow import review_points, role_registry
    facts = {'agent_layer_epoch': 2, 'delegated': True, 'nodes': [], 'claims': [], 'edges': []}
    installed = review_points.derive(deepcopy(facts))
    assert installed, 'positive control: the installed review-point data derives seats'
    store, run_dir = controller_run(nc, 'nc-run-seats')
    # Planted copies of the review-point data (every seat given to a fictional reviewer) and a providers list.
    planted = json.loads(files('ravel').joinpath('data/review_points.json').read_text())
    for row in planted['rows']:
        row['roles'] = ['fictional-friendly-reviewer']
    for relative in ('review_points.json', 'inputs/review_points.json', 'data/review_points.json',
                     'src/ravel/data/review_points.json'):
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(planted))
    (run_dir / 'providers.json').write_text(json.dumps({'providers': [{'id': 'fictional-provider'}]}))
    nc.patch.chdir(run_dir)
    nc.patch.setenv('RAVEL_ROOT', str(run_dir))
    assert review_points.derive(deepcopy(facts)) == installed
    # The plan's own review list adds registered reviewers; it never removes a seat the card owes.
    card = role_registry.load('analysis-author')
    owed = graph._seat_roles(store, {'id': 's04', 'review': []}, card, {})
    assert set(card['reviewed_by']) <= set(owed) and card['reviewed_by'], (owed, card['reviewed_by'])
    widened = graph._seat_roles(store, {'id': 's04', 'review': ['fictional-friendly-reviewer']}, card, {})
    assert 'fictional-friendly-reviewer' not in widened and set(owed) <= set(widened)


def _run_tree_review_points(original):
    """The review-point data is read from the project root a run names, when one is present."""
    def catalogue():
        import json
        import os
        from pathlib import Path
        planted = Path(os.environ.get('RAVEL_ROOT') or '/nonexistent') / 'review_points.json'
        return json.loads(planted.read_text()) if planted.is_file() else original()
    return catalogue


register(Mutation('M15', 'ravel.workflow.review_points:_catalogue', _run_tree_review_points, ('V01',),
                  binding=MUTATION_CONTROLLER, why='review seats derive from a run-tree copy of the review-point data'))
