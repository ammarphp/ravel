"""P13: one credit decision over controller-observed evidence; no cross-family requirement anywhere.

Independence rests on a separate observed session, a distinct actor and an artifact-only packet.
A same-family reviewer is credited and labelled; a family never refuses. Inert controls only:
an in-memory run store with the controller store's signatures, synthetic cards and models, no
model call, network or native job. Test names carry the coverage row they close.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import types

import pytest

from ravel.workflow import (physics_review, rdj_anchor, review_context, review_dispatch, review_independence as ri,
                            review_points as rp, review_projection, role_registry, spawn_rows, transport_registry as tr)

SHA = {k: c * 64 for k, c in (('subject', 'a'), ('receipt', 'b'), ('output', 'c'), ('packet', 'd'))}
EXPOSURE = {'author_identity': 'permitted', 'author_rationale': 'withheld', 'reference_values': 'permitted',
            'peer_verdicts': 'withheld'}


class LocalRunStore:
    """In-memory stand-in with the signatures of ``ravel.controller.store.RunStore`` (P01)."""
    runs = {}

    def __init__(self, run_id, *, root=None):
        self.run_id = run_id
        self.kinds = LocalRunStore.runs.setdefault(run_id, {})

    def append(self, kind, record):
        rows = self.kinds.setdefault(kind, [])
        rows.append(deepcopy(record))
        return f'{kind}:{len(rows)}'

    def read(self, kind, record_id):
        return deepcopy(self.kinds[kind][int(record_id.rsplit(':', 1)[1]) - 1])

    def scan(self, kind):
        return deepcopy(self.kinds.get(kind, []))

    def checkpointer(self):
        raise NotImplementedError

    def path(self, *parts):
        raise NotImplementedError


@pytest.fixture
def controller(monkeypatch):
    """Install the in-memory controller store; ``own(run)`` makes a run directory controller-owned."""
    owned = {}
    module = types.ModuleType('ravel.controller.store')
    module.RunStore = LocalRunStore

    def controller_owned(run_dir):
        value = owned.get(str(Path(run_dir).resolve()))
        if isinstance(value, Exception):
            raise value
        return value
    module.controller_owned = controller_owned
    if 'ravel.controller' not in sys.modules:
        package = types.ModuleType('ravel.controller')
        package.__path__ = []
        monkeypatch.setitem(sys.modules, 'ravel.controller', package)
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', module)
    LocalRunStore.runs.clear()

    def own(run, run_id='run-1', *, unknown=False):
        owned[str(Path(run).resolve())] = ValueError('store unreadable') if unknown else run_id
        return None if unknown else LocalRunStore(run_id)
    return own


def query(run, role='plan-critic', **changes):
    return {'run': str(Path(run).resolve()), 'role': role, 'subject_sha256': SHA['subject'],
            'receipt_sha256': SHA['receipt'], 'output_sha256': SHA['output'], 'packet_sha256': SHA['packet'],
            **changes}


def session(session_id, role, kind, *, seat=None, actor=None, model='claude-synthetic-a', **changes):
    return {'session_id': session_id, 'seat': seat or 'step-1:' + role, 'step_id': 'step-1', 'role': role,
            'card_id': role, 'role_kind': kind, 'actor_id': actor or 'actor-' + session_id, 'model': model,
            'transport_id': 'claude-cli-worker', 'transport_kind': 'cli-worker', 'fresh': True,
            'parent_transcript_supplied': False, **changes}


def review(binding, session_id, seat, **changes):
    return {'binding': binding, 'seat': seat, 'session_id': session_id, 'dispatch_id': 'dispatch-' + session_id,
            'packet': {'builder': 'ravel.workflow.review_projection', 'projection_verified': True,
                       'author_summary': False, 'sha256': binding['packet_sha256'],
                       'subject_sha256': binding['subject_sha256']},
            'read_boundary': 'packet_only', 'read_boundary_verified': True, 'exposure': dict(EXPOSURE),
            'exposure_verified': True, 'output_unmodified': True, **changes}


def staffed(store, run, *, reviewer='plan-critic', producer='screen-producer', reviewer_model='claude-synthetic-b',
            producer_model='claude-synthetic-a', **reviewer_changes):
    q = query(run, role=reviewer)
    review_dispatch.record_session(store, session('s-producer', producer, 'producer', model=producer_model))
    review_dispatch.record_session(store, session('s-reviewer', reviewer, 'reviewer', model=reviewer_model,
                                                  **reviewer_changes))
    review_dispatch.record_review(store, review(q, 's-reviewer', 'step-1:' + reviewer,
                                                subject_session_ids=['s-producer']))
    return q


# ---- credit from the controller store (I06, V02, C35, M16) --------------------------------------

def test_I06_CF14_CT06_same_family_reviewer_in_a_separate_session_is_credited_with_the_label(tmp_path, controller):
    store = controller(tmp_path)
    decision = ri.decide(staffed(store, tmp_path))
    assert decision['independent'] is True and decision['advisory'] is None
    assert decision['evidence_boundary'] == ri.CONTROLLER_STORE
    assert decision['family_relation'] == 'same' and decision['label'] == 'separate session, same model family'
    assert decision['context_id'] == 's-reviewer'


def test_I06_different_and_unknown_families_are_labels_too(tmp_path, controller):
    store = controller(tmp_path)
    assert ri.decide(staffed(store, tmp_path, reviewer_model='gpt-synthetic'))['label'] == \
        'separate session, different model family'
    store = controller(tmp_path / 'other', 'run-2')
    (tmp_path / 'other').mkdir()
    assert ri.decide(staffed(store, tmp_path / 'other', reviewer_model='opaque-local-model'))['label'] == \
        'separate session, model family unknown'


def test_V02_C35_a_controller_run_ignores_installed_resolvers_and_declarations(tmp_path, controller):
    controller(tmp_path)
    calls = []

    def perfect(q):
        calls.append(q)
        return {'binding': q, 'authority_boundary': ri.INSTALLED_RESOLVER}
    with ri.authority_session(perfect):
        decision = ri.decide(query(tmp_path))
    assert decision['independent'] is False and decision['advisory'] == 'trusted_dispatch_missing_or_changed'
    assert calls == []  # the installed resolver is never consulted for a controller-owned run


def test_I06_session_reuse_is_refused(tmp_path, controller):
    store = controller(tmp_path)
    q = staffed(store, tmp_path)
    assert ri.decide(q)['independent']
    # The same session also holds another seat: one session, never two independent seats.
    review_dispatch.record_session(store, session('s-reviewer', 'physics-critic', 'reviewer', seat='step-2:critic'))
    decision = ri.decide(q)
    assert decision['independent'] is False and decision['advisory'] == 'trusted_dispatch_missing_or_changed'


def test_CF10_ROLE_independence_a_named_actor_or_a_resumed_session_is_refused(tmp_path, controller):
    store = controller(tmp_path)
    # XF01: ml-reviewer on the trainer's own family is credited while its actor differs from the trainer's.
    q = staffed(store, tmp_path, reviewer='ml-reviewer', producer='ml-trainer', reviewer_model='claude-synthetic-b')
    assert ri.decide(q)['independent'] and ri.decide(q)['family_relation'] == 'same'
    for changes in ({'actor': 'actor-s-producer'}, {'fresh': False}):
        run = tmp_path / ('case-' + next(iter(changes)))
        run.mkdir()
        store = controller(run, 'run-' + next(iter(changes)))
        q = staffed(store, run, reviewer='ml-reviewer', producer='ml-trainer', **changes)
        assert ri.decide(q)['independent'] is False


def test_I06_a_reviewer_with_the_producers_actor_is_refused(tmp_path, controller):
    store = controller(tmp_path)
    # plan-critic names only the coordinator in distinct_actor_from; the producer's actor is refused anyway.
    q = staffed(store, tmp_path, actor='actor-s-producer')
    assert ri.decide(q)['independent'] is False


@pytest.mark.parametrize('changes', [{'actor_id': None}, {'actor_id': ''}, {'fresh': None},
                                   {'card_id': 'screen-producer'}])
def test_CF10_incomplete_or_wrong_card_session_evidence_is_refused(tmp_path, controller, changes):
    store = controller(tmp_path)
    q = staffed(store, tmp_path)
    store.kinds[review_dispatch.SESSION_KIND][-1].update(changes)
    assert ri.decide(q)['independent'] is False


@pytest.mark.parametrize('named', [[], ['not-recorded'], ['s-producer', 's-producer'], 's-producer'])
def test_I06_subject_census_cannot_erase_or_replace_the_observed_producer(tmp_path, controller, named):
    store = controller(tmp_path)
    q = staffed(store, tmp_path, actor='actor-s-producer')
    store.kinds[review_dispatch.REVIEW_KIND][-1]['subject_session_ids'] = named
    assert ri.decide(q)['independent'] is False


def test_SW06_relay_host_and_one_shot_sessions_never_hold_a_seat(tmp_path, controller):
    store = controller(tmp_path)
    for kind in tr.CONTROLLER_SEATLESS:
        with pytest.raises(ValueError, match='cannot hold a review seat'):
            review_dispatch.record_session(store, session('s-x', 'plan-critic', 'reviewer', transport_kind=kind))
    assert store.scan(review_dispatch.SESSION_KIND) == []
    # Even a record that bypassed the writer earns nothing.
    q = query(tmp_path)
    store.append(review_dispatch.SESSION_KIND, session('s-relay', 'plan-critic', 'reviewer',
                                                       transport_kind='external-relay'))
    review_dispatch.record_review(store, review(q, 's-relay', 'step-1:plan-critic'))
    assert ri.decide(q)['independent'] is False


def test_V02_unknown_ownership_is_never_read_as_ungoverned(tmp_path, controller):
    controller(tmp_path, unknown=True)
    with ri.authority_session(lambda q: {'binding': q, 'authority_boundary': ri.INSTALLED_RESOLVER}):
        assert ri.decide(query(tmp_path))['advisory'] == 'controller_ownership_unknown'


@pytest.mark.parametrize('error', [ImportError('broken controller import'),
                                 ModuleNotFoundError('missing dependency', name='synthetic_dependency')])
def test_V02_a_broken_controller_import_does_not_disable_governance(tmp_path, monkeypatch, error):
    import builtins
    original = builtins.__import__

    def broken(name, *args, **kwargs):
        if name == 'ravel.controller.store':
            raise error
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', broken)
    with ri.authority_session(lambda q: _legacy_evidence(q, ri.INSTALLED_RESOLVER)):
        assert ri.decide(query(tmp_path))['advisory'] == 'controller_ownership_unknown'


def _legacy_evidence(q, boundary):
    return {'binding': deepcopy(q), 'authority_boundary': boundary, 'dispatch_id': 'd', 'context_id': 'ctx-review',
            'author_context_ids': ['ctx-author'], 'author_census_complete': True, 'other_review_context_ids': [],
            'review_census_complete': True, 'parent_transcript_supplied': False,
            'packet': {'builder': 'ravel.workflow.review_projection', 'projection_verified': True,
                       'author_summary': False, 'sha256': q['packet_sha256'] or SHA['packet'],
                       'subject_sha256': q['subject_sha256']},
            'read_boundary': 'packet_only', 'read_boundary_verified': True, 'exposure': dict(EXPOSURE),
            'exposure_verified': True, 'output_unmodified': True,
            'models': {'reviewer': {'model': 'claude-x'}, 'author:ctx-author': {'family': 'anthropic'}}}


@pytest.mark.parametrize('boundary,credited', [(ri.SAME_USER_STATE, True), (ri.INSTALLED_RESOLVER, True),
                                               (ri.CONTROLLER_STORE, False), ('same_user_files', False)])
def test_V02_ungoverned_runs_credit_only_known_boundaries_and_label_them(tmp_path, controller, boundary, credited):
    q = query(tmp_path)
    with ri.authority_session(lambda _: _legacy_evidence(q, boundary)):
        decision = ri.decide(q)
    assert decision['independent'] is credited
    if credited:
        assert decision['evidence_boundary'] == boundary and decision['family_relation'] == 'same'


def test_V02_the_legacy_resolver_no_longer_claims_controller_custody(tmp_path, monkeypatch):
    monkeypatch.setattr(review_dispatch, 'census', lambda run, exclude=None: (['author'], []))
    monkeypatch.setattr(review_dispatch, 'author_models', lambda run, exclude=None: {'author': {'family': 'anthropic'}})
    proof = review_dispatch._proof(query(tmp_path), dispatch_id='d', context='c', run=tmp_path, packet={},
                                   read_boundary='packet_only', exposure_value={}, output_unmodified=True,
                                   reviewer_model={'model': 'claude-x'})
    assert proof['authority_boundary'] == ri.SAME_USER_STATE
    assert ri.family_relation(proof['models']) == 'same'


# ---- labels, never requirements (XF02, XF03, XF05, XF06, XF07, CT06) -----------------------------

@pytest.mark.parametrize('models,relation', [
    ({'reviewer': 'claude-a', 'author': 'claude-b'}, 'same'),
    ({'reviewer': 'claude-a', 'author': 'gpt-b'}, 'different'),
    ({'reviewer': 'claude-a', 'author': 'opaque-b'}, 'unknown'),
    ({'reviewer': {'family': 'anthropic'}, 'author': {'model': 'claude-b'}}, 'same'),
    ({'reviewer': 'claude-a'}, 'unknown'),
    ({'first': 'gpt-a', 'second': 'gpt-b', 'third': 'claude-c'}, 'same'),
    (None, 'unknown'),
])
def test_CT06_family_relation_is_a_label(models, relation):
    assert ri.family_relation(models) == relation
    assert ri.family_label(relation).startswith('separate session, ')


def test_XF02_selection_keeps_the_legacy_assignment_argument_without_a_family_gate():
    import inspect
    assert 'assigned' in inspect.signature(tr.select).parameters
    assert {'controller', 'qualifications'} <= set(inspect.signature(tr.select).parameters)


def test_XF03_receipt_time_family_check_returns_labels_and_never_refuses():
    card = {'id': 'critic', 'model': {'distinct_family_from': ['producer']}}
    assert tr.check_distinct_families(card, {'critic': 'claude-a', 'producer': 'claude-b'}) == 'same'
    assert tr.check_distinct_families(card, {'critic': 'gpt-a', 'producer': 'claude-b'}) == 'different'
    assert tr.check_distinct_families(card, {'critic': 'mystery-1', 'producer': 'mystery-1'}) == 'unknown'
    assert tr.check_distinct_families(card, {'critic': 'claude-a'}) == 'unknown'
    assert tr.check_distinct_families({'id': 'critic', 'model': {}}, {'critic': 'claude-a'}) == 'unknown'


def test_XF01_CF14_no_shipped_card_requires_another_family_and_session_separation_stays():
    cards = {c['id']: c for c in role_registry.all_cards()}
    assert [c for c, card in cards.items() if card['model'].get('distinct_family_from')] == []
    reviewer = cards['ml-reviewer']
    assert reviewer['model']['distinct_family_from'] == []
    assert set(reviewer['independence']['distinct_actor_from']) >= {'ml-trainer', 'ml-planner'}
    assert reviewer['independence']['fresh_session'] is True and reviewer['sees']['profile'] == 'spec-denied'


def test_XF05_a_credited_receipt_reports_its_family_label():
    receipt = {'_path': 'agent-work/r/1/receipt.json', '_label': 'transport_attested', '_eligible': True,
               '_advisory': None, '_independence': {'independent': True, 'family_relation': 'same'}}
    report = rp._receipt_report(receipt)
    assert report['independent'] and report['label'] == 'separate session, same model family'
    receipt['_independence'] = ri.advisory('self_attested')
    assert 'label' not in rp._receipt_report(receipt)


def test_XF06_k4_accepts_one_author_family_with_a_label():
    row = next(r for r in spawn_rows.catalogue()['rows'] if r['row'] == 'K4')
    assert row['min_model_families'] == 1
    assert spawn_rows.family_label({'anthropic'}) == 'single model family'
    assert spawn_rows.family_label({'anthropic', 'openai'}) == 'several model families'
    assert spawn_rows.family_label(set()) == 'model family unknown'


def test_XF07_the_rdj_r3_family_flag_stays_off():
    assert rdj_anchor.policy()['r3_distinct_family'] is False


def test_XF08_owned_documents_no_longer_mandate_a_second_family():
    root = Path(__file__).resolve().parents[3]
    owned = ['docs/reference/transports.md', 'docs/reference/glossary.md', 'docs/methodology/agent-architecture.md',
             'docs/workflow/checklists/ml-training.md', 'docs/workflow/reference/scientific-judgment.md',
             'docs/workflow/checklists/independent-numerics.md']
    mandates = ('family distinct from', 'family must differ', 'can require a model family', 'a different transport family',
                'needs a registered transport family', 'can require a family different')
    for rel in owned:
        text = (root / rel).read_text(encoding='utf-8').lower()
        assert not [m for m in mandates if m in text], rel


# ---- answers from outside the controller (SW06-SW09, SW21) ----------------------------------------

def test_SW07_review_journal_commands_are_refused_for_a_controller_run(tmp_path, controller, monkeypatch):
    calls = []
    monkeypatch.setattr(physics_review, 'submit_review', lambda root, **kw: calls.append(kw) or {'state': 'ok'})
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'role': 'physics_critic', 'actor_id': 'declared', 'verdict': 'accept',
                                   'summary': 'declared'}))
    run = tmp_path / 'run'
    run.mkdir()
    controller(run)
    with pytest.raises(SystemExit):
        physics_review.main(['--rundir', str(run), 'review', '--request', str(request)])
    assert calls == []
    other = tmp_path / 'ungoverned'
    other.mkdir()
    assert physics_review.main(['--rundir', str(other), 'review', '--request', str(request)]) == 0
    assert len(calls) == 1


def test_SW08_absent_registration_is_not_permission_for_a_controller_run(tmp_path, controller):
    run = tmp_path / 'run'
    run.mkdir()
    assert physics_review.active(run) is False  # ungoverned: the first smoke produces the evidence
    store = controller(run)
    assert physics_review.active(run) is True  # no registration is not an exemption
    store.append(physics_review.REGISTRATION_KIND, {'registration_sha256': 'e' * 64, 'run_id': 'r'})
    assert physics_review.active(run) is True  # files deleted after registration: still gated
    unknown = tmp_path / 'unknown'
    unknown.mkdir()
    controller(unknown, unknown=True)
    assert physics_review.active(unknown) is True


PASSED_STEPS = [{'step': name, 'passed': True} for name in sorted(tr.QUALIFICATION_STEPS)]


def _qualified(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    document = {'id': 'synthetic-cli-worker', 'transport_kind': 'cli-worker', 'qualification': {'status': 'declared'}}
    probe = {'executable_sha256': 'f' * 64, 'probed': True}
    record = {'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': document['id'],
              'status': 'live_qualified', 'record_path': 'r', 'executable_path': 'e',
              'executable_sha256': 'f' * 64, 'declaration_sha256': tr.declaration_sha256(document),
              'probe_sha256': tr.digest(probe), 'receipt': {}, 'observed': {}, 'steps': PASSED_STEPS, 'rundir': 'run',
              'qualified_utc': '2026-01-01T00:00:00Z'}
    path = tr.qualification_path(document['id'])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    return document, probe, record


def test_SW09_a_hand_written_qualification_counts_only_when_the_operator_registered_it(tmp_path, monkeypatch):
    document, probe, record = _qualified(tmp_path, monkeypatch)
    register = tmp_path / 'operator-store' / tr.QUALIFICATION_REGISTER
    assert tr.read_qualification(document, probe) == record  # ungoverned selection: as before
    assert tr.read_qualification(document, probe, registered=tr.registered_qualifications(register)) is None
    assert tr.qualification_status(document, probe, registered=frozenset()) == 'declared'
    row = tr.register_qualification(record, register)
    assert row['record_sha256'] == tr.digest(record)
    registered = tr.registered_qualifications(register)
    assert tr.read_qualification(document, probe, registered=registered) == record
    assert tr.qualification_status(document, probe, registered=registered) == 'live_qualified'
    with pytest.raises(ValueError):
        tr.register_qualification({**record, 'status': 'declared'}, register)


def test_liveness_a_registered_qualification_makes_a_shipped_sandbox_worker_blind_capable(tmp_path, monkeypatch):
    """Cross-review predicate 7: blind seats need a qualified blind-capable transport. The real probe never
    confirms blindness for a CLI (help text cannot), so only the live qualification can."""
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(tr, 'executor_problem', lambda document: None)
    monkeypatch.setattr(tr, 'sandbox_available', lambda: True)
    document = tr.load('claude-cli-worker', installed_only=True)
    assert document['capabilities']['blind_capable'] and document['capabilities']['isolation'] in tr.SANDBOX_ISOLATION
    probe = {'schema_version': 1, 'kind': 'transport-probe', 'transport_id': document['id'],
             'declaration_sha256': tr.declaration_sha256(document), 'cli_version': 'synthetic 0.0.0',
             'help_sha256': 'b' * 64, 'flags': {flag: 'confirmed' for flag in tr.template_flags(document)},
             'capabilities_confirmed': {key: bool(document['capabilities'][key]) and key != 'blind_capable'
                                        for key in tr.BOOLEAN_CAPABILITIES},
             'unusable': [], 'probed_utc': '2026-01-01T00:00:00Z', 'executable_path': '/synthetic/cli',
             'executable_sha256': 'f' * 64, 'exit_status': 0}
    card = role_registry.load('ml-reviewer')
    unqualified, _ = tr.effective_capabilities(document, probe, registered=frozenset())
    assert unqualified['blind_capable'] is False and unqualified['isolation'] == 'cli-policy'
    record = {'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': document['id'],
              'status': 'live_qualified', 'record_path': 'r', 'executable_path': '/synthetic/cli',
              'executable_sha256': 'f' * 64, 'declaration_sha256': tr.declaration_sha256(document),
              'probe_sha256': tr.digest(probe), 'receipt': {}, 'observed': {}, 'steps': PASSED_STEPS, 'rundir': 'run',
              'qualified_utc': '2026-01-01T00:00:00Z'}
    path = tr.qualification_path(document['id'])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    # Written but not registered by the operator: still not blind in controller selection.
    assert tr.effective_capabilities(document, probe, registered=frozenset())[0]['blind_capable'] is False
    register = tmp_path / 'operator-store' / tr.QUALIFICATION_REGISTER
    tr.register_qualification(record, register)
    registered = tr.registered_qualifications(register)
    qualified, _ = tr.effective_capabilities(document, probe, registered=registered)
    assert qualified['blind_capable'] is True and qualified['isolation'] in tr.SANDBOX_ISOLATION
    assert tr.blind_admissible(document, qualified)
    assert not {'blind', 'qualification', 'isolation'} & set(tr.unmet(document, qualified, card, probe,
                                                                     registered=registered))


def test_SW21_controller_selection_reads_installed_declarations_only(tmp_path, monkeypatch):
    extra = tmp_path / 'user-transports'
    extra.mkdir()
    (tmp_path / '.ravel' / 'transports').mkdir(parents=True)
    monkeypatch.setenv('RAVEL_TRANSPORT_PATH', str(extra))
    monkeypatch.chdir(tmp_path)
    assert tr.search_dirs(installed_only=True) == [tr.BUILTIN_DIR]
    assert len(tr.search_dirs()) == 3


def test_SW06_controller_selection_refuses_relay_host_and_one_shot_routes(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    card = role_registry.load('plan-critic')
    order = ['external-relay', 'host-subagent-claude', 'claude-cli-oneshot']
    preferences = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card['family']: order},
                   'tier_models': {'judgment': {t: 'claude-synthetic' for t in order}}}
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card, preferences, probes={}, executables={}, controller=True)
    assert set(refused.value.missing) == {'controller:external-relay', 'controller:host-subagent',
                                          'controller:cli-oneshot'}
    try:  # positive control: outside controller selection these kinds are judged on their capabilities
        tr.select(card, preferences, probes={}, executables={})
    except tr.TransportRefusal as legacy:
        assert not any(code.startswith('controller:') for code in legacy.missing)


# ---- seats, screening and must_check verdicts (CF08, CF09, CF10, CF12, M14) -----------------------

def test_CF08_reviewed_by_adds_the_reviewer_seats_and_cannot_be_selected_away():
    owed = rp.reviewed_by_seats('analysis-author')
    assert [s['role'] for s in owed] == ['object-selection-mapper', 'physics-critic']
    assert all(s['blocking'] and s['gate'] == 'delivery' and s['count'] == 1 for s in owed)
    assert [s['role'] for s in rp.reviewed_by_seats('analysis-author', ['physics-critic'])] == ['object-selection-mapper']
    assert rp.reviewed_by_seats('plan-critic') == []


def test_CF09_ROLE_sees_workspace_profile_cards_are_screened(tmp_path):
    rels = ['inputs/spec.json', 'inputs/held_out/canary.json', 'claims/C1.json', 'graphs/state.json']
    kept, removed = review_projection.screen_inputs(tmp_path, 'detector-calibrator', rels)
    assert kept == ['inputs/spec.json']
    assert {r['path']: r['class'] for r in removed} == {'inputs/held_out/canary.json': 'held_out_artifacts',
                                                        'claims/C1.json': 'claim_quantity',
                                                        'graphs/state.json': 'graph_or_review_state'}
    for role in ('ml-trainer', 'ml-planner'):  # their classes are now known to the projection
        kept, removed = review_projection.screen_inputs(
            tmp_path, role, ['inputs/split/confirm.parquet', 'inputs/truth_labels.json', 'inputs/train.parquet'])
        assert kept == ['inputs/train.parquet'] and len(removed) == 2
    with pytest.raises(review_projection.ProjectionRefused):
        review_projection.screen_inputs(tmp_path, 'detector-calibrator', ['../outside.json'])


@pytest.mark.parametrize('card,session,others,reason', [
    ({'independence': {'fresh_session': True}}, {'session_id': 's', 'fresh': False}, [], 'session_not_fresh'),
    ({'independence': {}}, {'session_id': 's'}, [{'session_id': 's', 'seat': 'other'}], 'session_reused'),
    ({'independence': {'distinct_actor_from': ['producer']}}, {'session_id': 's', 'actor_id': 'a'},
     [{'session_id': 't', 'role': 'producer', 'actor_id': 'a'}], 'actor_not_distinct:producer'),
    ({'independence': {'distinct_actor_from': ['producer']}}, {'session_id': 's'}, [], 'actor_not_distinct:producer'),
    ({'independence': {}}, {'session_id': ''}, [], 'session_unobserved'),
    ({'independence': {'fresh_session': True, 'distinct_actor_from': ['producer']}},
     {'session_id': 's', 'fresh': True, 'actor_id': 'a'}, [{'session_id': 't', 'role': 'producer', 'actor_id': 'b'}],
     None),
])
def test_CF10_seat_refusal(card, session, others, reason):
    assert ri.seat_refusal(card, session, [session, *others]) == reason


def test_M14_credit_needs_a_verdict_with_evidence_for_every_must_check_item():
    items = ['check:ml-baseline-set', 'check:ml-stopping-rule']
    record = {'checklist': [{'unit': items[0], 'status': 'done', 'evidence': 'outputs/review.json#/baseline'},
                            {'unit': items[1], 'status': 'not_applicable', 'note': 'single-stage study'}]}
    assert rp.must_check_missing(items, record) == []
    for row in ({'unit': items[1], 'status': 'blocked', 'evidence': 'x'}, {'unit': items[1], 'status': 'done'},
                {'unit': items[1], 'status': 'not_applicable'}):
        assert rp.must_check_missing(items, {'checklist': [record['checklist'][0], row]}) == [items[1]]
    assert rp.must_check_missing(items, {}) == items


# ---- liveness (cross-review predicate 7) --------------------------------------------------------

def test_liveness_second_method_deriver_projects_and_withholds_the_first_method(tmp_path):
    card = review_projection._card('second-method-deriver')
    forbidden = sorted(card['sees']['forbidden_inputs'])
    assert review_projection._classify('outputs/width.json', forbidden, lambda rel: False, True) == 'first_method'
    assert review_projection._classify('inputs/first_derivation.json', forbidden, lambda rel: False, True) \
        == 'first_method'
    assert review_projection._classify('inputs/model.json', forbidden, lambda rel: False, True) is None


def test_liveness_review_context_read_is_a_bounded_packet_reader(monkeypatch):
    packet = {'path': '/fictional/packet', 'manifest_sha256': 'e' * 64}
    seen = []
    monkeypatch.setattr(review_context, 'read_artifact_page', lambda *a, **k: seen.append(('page', a, k)) or {})
    monkeypatch.setattr(review_context, 'read_index_page', lambda *a, **k: seen.append(('index', a, k)) or {})
    review_context.broker_read(packet, {'artifact_id': 'item', 'offset': 0, 'max_bytes': 1024})
    review_context.broker_read(packet, {'section': 'artifacts', 'query': 'x'})
    assert [s[0] for s in seen] == ['page', 'index']
    assert seen[0][1] == ('/fictional/packet', 'item') and seen[0][2]['expected_manifest_sha256'] == 'e' * 64
    for bad in ({'artifact_id': 'item', 'path': '/etc/passwd'}, {'path': 'x'}, ['item']):
        with pytest.raises(ValueError):
            review_context.broker_read(packet, bad)
    with pytest.raises(ValueError):
        review_context.broker_read({'path': 'x'}, {'artifact_id': 'item'})
    assert len(seen) == 2


CARDS = sorted(card['id'] for card in role_registry.all_cards())


@pytest.mark.parametrize('role', CARDS, ids=lambda role: f'ROLE-{role}-sees')
def test_ROLE_sees_every_card_is_screenable_on_the_classes_it_forbids(tmp_path, role):
    """Each card's forbidden classes are known to the projection, so a packet of any profile is screened."""
    card = review_projection._card(role)
    planted = {'held_out_artifacts': 'inputs/held_out/canary.json', 'claim_quantity': 'claims/canary.json',
               'producer_numbers': 'outputs/canary.json', 'lessons': 'inputs/lessons/canary.md',
               'board_prose': 'research/board/canary.md', 'critic_reasoning': 'review/critic/canary.json',
               'final_partitions': 'inputs/split/confirm.parquet', 'evaluator_truth_columns': 'inputs/truth.json',
               'first_method': 'inputs/first_derivation.json', 'other_verdicts': 'review/canary.json',
               'producer_headline': 'summary.md'}
    rels = [planted[c] for c in card['sees'].get('forbidden_inputs', []) if c in planted]
    kept, removed = review_projection.screen_inputs(tmp_path, role, rels)
    assert kept == [] and len(removed) == len(rels)


REVIEWED = sorted((card['id'], reviewer) for card in role_registry.all_cards() for reviewer in card['reviewed_by'])


@pytest.mark.parametrize('role,reviewer', REVIEWED,
    ids=[f"ROLE-{role}-reviewed_by-{role_registry.load(role)['reviewed_by'].index(reviewer)}"
         for role, reviewer in REVIEWED])
def test_ROLE_reviewed_by_every_named_reviewer_becomes_a_seat(role, reviewer):
    owed = rp.reviewed_by_seats(role)
    assert reviewer in {s['role'] for s in owed}
    assert reviewer not in {s['role'] for s in rp.reviewed_by_seats(role, [reviewer])}


def _consumer(kind, run, monkeypatch):
    """(query, call) for one consumer entry point of the shared credit decision."""
    run = Path(run).resolve()
    if kind == 'worker_receipt':  # review points, spawn rows, RDJ worker roles
        receipt = {'role': {'id': 'plan-critic'}, 'final_record': {'sha256': SHA['output']}}
        q = ri.worker_query(run, receipt, SHA['receipt'], subject_sha256=SHA['subject'])
        return q, lambda: ri.decide(q)
    value = {'verdict': 'accept', 'summary': 'synthetic', 'findings': [], 'closes': [], 'claim_scope': None,
             'subject_sha256': SHA['subject']}
    receipt = {'role': 'critic', 'subject_sha256': SHA['subject'], 'receipt_sha256': SHA['receipt'],
               'public_value': value, 'context_manifest_sha256': SHA['packet']}
    q = ri.graph_query(run, receipt)
    if kind == 'graph_receipt':  # research protocol stages, scientific judgment, RDJ graph roles
        return q, lambda: ri.graph_decision(run, receipt)
    if kind == 'meta_review':  # research protocol meta review
        return q, lambda: ri.meta_decision({'independence_query': q, 'role_receipt': receipt})
    from ravel.workflow import scientific_judgment  # journal: physics review votes, completion credit
    monkeypatch.setattr(scientific_judgment, '_read_pin', lambda pin: {
        'rundir': q['run'], 'role': 'critic', 'cycle_id': 'cycle-1', 'phase': 'result_review'})
    event = {'role': 'physics_critic', 'cycle_id': 'cycle-1',
             **{k: value[k] for k in ('verdict', 'summary', 'findings', 'closes', 'claim_scope')},
             'independence_evidence': {'query': q, 'response': value,
                                       'request': {'path': 'request.json', 'sha256': SHA['subject']}}}
    return q, lambda: ri.journal_decision(run, event)


@pytest.mark.parametrize('kind', [
    pytest.param('worker_receipt', id='review-points'),
    pytest.param('graph_receipt', id='rdj'),
    pytest.param('meta_review', id='research-protocol'),
    pytest.param('graph_receipt', id='scientific-judgment'),
    pytest.param('journal', id='completion'),
])
def test_CT06_every_consumer_credits_a_same_family_reviewer_with_the_label(tmp_path, monkeypatch, kind):
    q, call = _consumer(kind, tmp_path, monkeypatch)
    evidence = _legacy_evidence(q, ri.INSTALLED_RESOLVER)
    with ri.authority_session(lambda asked: evidence if asked == q else None):
        decision = call()
    assert decision['independent'] is True, decision
    assert decision['label'] == 'separate session, same model family'
    # Session reuse is refused in every consumer: the reviewer's context already reviewed in this run.
    reused = {**evidence, 'other_review_context_ids': [evidence['context_id']]}
    with ri.authority_session(lambda asked: reused if asked == q else None):
        assert call()['advisory'] == 'review_context_reused'


def test_V01_seats_derive_from_installed_data_never_a_run_tree_copy(tmp_path, monkeypatch):
    from importlib.resources import files
    installed = json.loads(files('ravel').joinpath('data/review_points.json').read_text())
    planted = tmp_path / 'data'
    planted.mkdir()
    (planted / 'review_points.json').write_text(json.dumps({**installed, 'rows': []}))
    monkeypatch.chdir(tmp_path)
    assert rp._catalogue() == installed and rp._catalogue()['rows']
    # A caller's seat list can add a seat but never removes one a producer card owes.
    assert {s['role'] for s in rp.reviewed_by_seats('ml-trainer', ['physics-critic'])} == {'ml-reviewer'}


def test_CF12_ml_trainer_checks_hold_unverified_computation_instead_of_fabricating_an_ok_receipt():
    """The 13 owed checks are registered, but document verdicts alone cannot close this liveness item."""
    from ravel.workflow import review_projection_checks as checks
    card = role_registry.load('ml-trainer')
    owed = sorted(set(card['must_check']) | set(role_registry.self_checks('ml-trainer')))
    assert len(owed) == 13 and all(c.startswith('check:ml-') for c in owed)
    effective = {**card, 'must_check': owed}
    document = {'checks': {c: {'verdict': 'pass'} for c in owed}}
    for check in owed:
        assert checks.permitted(effective, check), check
        result = checks.run_check(check, document)
        assert result['status'] == 'inconclusive' and result['outcome'] == 'computation_unverified', check
    # An unresolved verdict never counts as a pass.
    assert checks.run_check(owed[0], {'checks': {owed[0]: {'verdict': 'unresolved'}}})['status'] == 'inconclusive'


def test_M14_reviewer_items_are_owed_as_verdicts_and_never_run_as_validations():
    from ravel.workflow import review_projection_checks as checks
    items = checks.reviewer_items()
    assert items == {'check:ml-baseline-set', 'check:ml-oracle-labelled', 'check:ml-cost-preflight',
                     'check:ml-hypothesis-family', 'check:ml-stopping-rule', 'check:higgs.scalar_basis',
                     'check:higgs.theory_constraints'}
    assert not any(checks.computes(item) for item in items)
    # Other ids have callable adapters; their individual statuses still decide whether they passed.
    named = {c for card in role_registry.all_cards() for c in card['must_check'] if not c.startswith('trap:')}
    assert {c for c in named - items if not checks.computes(c)} == set()
    for item in items:
        assert checks.run_check(item, {'anything': True})['status'] == 'inconclusive'
