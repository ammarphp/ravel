"""Composition callbacks: canonical transitions, complete refusals and authenticated waiver reads.

Cross-owner handoff (the external fragment destination was rejected by the filesystem sandbox):

At trusted composition, register stable provider callables explicitly::

    ledger.register_gate_hook('engagement', engagement.gate_errors)
    ledger.register_authority_reader(ledger_authority_reader)

In the engagement provider, replace the comparison
``if transition == 'checkin1->execute':`` with ``if transition == 'checkin1→execute':``.
The authority owner can supply the following callable, using its authenticated history and current verifier::

    def ledger_authority_reader(store, record_id):
        for record in common.scan(store, common.AUTHORITY, common.SCHEMA):
            if record_id in (record['id'], record.get('uid')):
                return service.verify(store, record['id'], kind=record['kind'])
        raise KeyError(record_id)

Two old unsigned waiver fixtures require an explicit authentication fake. Add this helper to
``p02_support.py``; no existing assertion needs changing::

    @pytest.fixture
    def authenticated_authority_reader(monkeypatch):
        # Unsigned scope/class fixtures only; this fake makes no production authentication claim.
        import importlib
        module = importlib.import_module('ravel.controller.ledger.record')
        monkeypatch.setattr(module, '_authority_reader', None)

        def read(store, record_id):
            for envelope in store.scan('authority'):
                body = envelope.get('record', envelope)
                if record_id in (body.get('uid'), envelope.get('id'), body.get('id')):
                    return body
            raise KeyError(record_id)

        ledger.register_authority_reader(read)

Add ``from p02_support import authenticated_authority_reader`` in both ``test_p02_gates.py`` and
``test_p02_real_store.py``. Change exactly these signatures to request that fixture::

    def test_p02_deviation_and_escalation_occurrences_gate_their_return_to_execute(
            fixture_store, authenticated_authority_reader):
    def test_p02_authority_records_are_found_through_store_envelopes(
            tmp_path, monkeypatch, authenticated_authority_reader):

Directory reconciliation: this new file is software test coverage; add the following map row::

    | `tests/unit/controller/test_p02_hooks.py` | software | Explicit gate callbacks, canonical transitions, stored-plan custody and authenticated waiver-reader controls |

The documentation owner should put both callback signatures from the ledger public API and the explicit
registration requirement in the controller composition instructions, then register the change at the fold.
No environment, cards or data changed. The only repository edits are the five owned paths, left uncommitted.

Completion record: read-only interface inspection and unchanged-rule verification were delegated to
gpt-6-luna at medium effort, without nested delegation, edits or tests. Parent inspected the returned source
references and implementation diff and independently ran the cluster checks. Evidence keys and original class
rules match the parent version; the existing record-test file has additions only.
Failing-first run 20261018T055227Z-33403 (949c9a2): 1 passed, 26 failed, no errors.
Wider run 20261018T055405Z-37340 (f98ff9a): 129 passed, 2 failed, no errors; both failures are exactly the old
unsigned fixtures above, preserved without weakening their assertions.
Final run 20261018T055607Z-41079 (87d1996): 182 passed, zero failures/errors, six complete files, no skips.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib
import json
import subprocess
import sys
import types

import pytest

from ravel.controller import ledger
from ravel.controller.ledger import chain, gates, state as state_module
from ravel.workflow import decision_gate
from p02_support import (INTAKE, PLAN, RUN, FakeStore, authority, fixture_catalogue, fixture_rows,
                              install_controller, row, satisfy, use_catalogue)

record_module = importlib.import_module('ravel.controller.ledger.record')


@pytest.fixture(autouse=True)
def callbacks(monkeypatch):
    # Isolate composition state without requiring either peer package to be installed.
    monkeypatch.setattr(gates, '_GATE_HOOKS', {}, raising=False)
    monkeypatch.setattr(record_module, '_authority_reader', None, raising=False)


@pytest.fixture
def run(tmp_path, monkeypatch):
    rows = fixture_rows() + [row('X-ENGAGEMENT', 'step.dispatch', 'seat', 'seat', package='P18')]
    use_catalogue(monkeypatch, fixture_catalogue(rows))
    store = FakeStore(RUN, root=tmp_path / 'store')
    ledger.materialise(store, 'intake', INTAKE)
    ledger.materialise(store, 'plan', {'plan': PLAN})
    yield store
    state_module.forget(store)


@pytest.mark.parametrize('transition', list(ledger.TRANSITIONS) + ['checkin1->execute'])
def test_p02_catalogued_provider_cannot_be_silently_absent(run, transition):
    assert 'engagement_provider_missing' in {r['reason'] for r in ledger.gate(run, transition)}


def test_p02_catalogue_without_peer_rows_keeps_the_existing_gate(tmp_path, monkeypatch):
    use_catalogue(monkeypatch, fixture_catalogue())
    store = FakeStore(RUN, root=tmp_path)
    ledger.materialise(store, 'intake', INTAKE)
    satisfy(store, ledger.pending(store))
    assert ledger.gate(store, 'intake->route_select') == []


def test_p02_every_hook_gets_the_canonical_transition_and_resolved_plan(run):
    calls = []
    plan = deepcopy(PLAN)
    plan['sha256'] = chain.digest({k: v for k, v in plan.items() if k != 'sha256'})
    ledger.materialise(run, 'plan', {'plan': plan})
    run.append('plan', {'plan_sha256': plan['sha256'], 'plan': plan})

    def first(store, transition, *, plan):
        calls.append(('first', store, transition, deepcopy(plan)))
        plan.clear()  # a callback cannot change what the next callback or the ledger reads
        return [{'row': 'X-HOOK', 'reason': 'additional_review'}]

    def second(store, transition, *, plan):
        calls.append(('second', store, transition, deepcopy(plan)))
        return []

    ledger.register_gate_hook('first', first)
    ledger.register_gate_hook('second', second)
    for spelling in ('checkin1->execute', 'checkin1→execute'):
        result = ledger.gate(run, spelling)
        assert 'additional_review' in {r['reason'] for r in result}
        assert 'engagement_provider_missing' not in {r['reason'] for r in result}
        assert any(r['reason'] == 'pending' for r in result)  # ordinary checks remain active
    assert [(p, s is run, t, v) for p, s, t, v in calls] == [
        (p, True, 'checkin1→execute', plan) for _ in range(2) for p in ('first', 'second')]


def test_p02_hook_can_pass_and_cannot_replace_another_provider(run):
    def provider(store, transition, *, plan):
        return []

    ledger.register_gate_hook('extension', provider)
    ledger.register_gate_hook('extension', provider)  # composition is idempotent
    assert ledger.gate(run, 'deliver[qualified]') == []
    with pytest.raises(ValueError):
        ledger.register_gate_hook('extension', lambda *args, **kwargs: [])
    with pytest.raises(ValueError):
        ledger.register_gate_hook('', provider)
    with pytest.raises(TypeError):
        ledger.register_gate_hook('invalid', None)


@pytest.mark.parametrize('result', [None, {}, [None], [{'reason': ''}], [{'reason': 'x', 'row': []}],
                                 [{'reason': 'x', 'message': True}], [{'reason': 'x', 'entry': []}],
                                 [{'reason': 'x', 'consequence': 'ignored'}], [{'reason': 'x', 'value': object()}]])
def test_p02_invalid_hook_results_refuse(run, result):
    ledger.register_gate_hook('invalid', lambda *args, **kwargs: result)
    assert 'gate_hook_invalid' in {r['reason'] for r in ledger.gate(run, 'deliver[qualified]')}


def test_p02_a_failed_hook_does_not_skip_the_other_hooks(run):
    calls = []

    def failed(*args, **kwargs):
        raise RuntimeError('provider unavailable')

    ledger.register_gate_hook('failed', failed)
    ledger.register_gate_hook('other', lambda *args, **kwargs: calls.append(True) or [])
    assert 'gate_hook_failed' in {r['reason'] for r in ledger.gate(run, 'deliver[qualified]')}
    assert calls == [True]


def test_p02_decide_uses_the_hooks_and_never_discharges_a_refusal(run, tmp_path, monkeypatch):
    rundir = tmp_path / 'run'
    rundir.mkdir()
    install_controller(monkeypatch, {str(rundir): RUN}, tmp_path / 'store')
    monkeypatch.setattr(decision_gate, '_facts', lambda path: {'agent_layer_epoch': 2})
    monkeypatch.setattr(decision_gate, '_provider_errors', lambda *args: [])
    action = {'kind': 'controller.approve_plan', 'digest': 'a' * 64, 'summary': 'fixture', 'pins': []}
    key = ledger.instance_key('GATE-approve_plan', RUN, {})
    satisfy(run, [k for k in ledger.pending(run) if k != key])
    before = ledger.verify(run)
    errors = ledger.decide(run, rundir, 'approve_plan', action)
    assert 'ledger_engagement_provider_missing' in {e.code for e in errors}
    assert ledger.verify(run) == before
    assert state_module.load(run, full=True).instances[key].status == 'pending'
    calls = []
    ledger.register_gate_hook('extension', lambda store, transition, *, plan:
                              calls.append((transition, plan)) or [])
    errors = ledger.decide(run, rundir, 'approve_plan', action)
    # The review population is still required even though every pending instance was satisfied.
    assert errors and len(calls) == 1 and calls[0][0] == 'checkin1→execute'
    review = ledger.materialise(run, 'review', {'step': 'plan_review', 'seat': 'checker', 'attempt': 1})
    satisfy(run, review)
    assert ledger.decide(run, rundir, 'approve_plan', action) == []
    assert state_module.load(run, full=True).instances[key].status == 'satisfied'


def test_p02_decide_consults_hooks_when_the_decision_provider_returns_early(run, tmp_path, monkeypatch):
    monkeypatch.setattr(decision_gate, '_controller_owner', lambda *args: RUN)
    monkeypatch.setattr(decision_gate, 'check', lambda *args: [])
    before = ledger.verify(run)
    errors = ledger.decide(run, tmp_path, 'approve_plan', {})
    assert [e.code for e in errors] == ['ledger_engagement_provider_missing']
    assert ledger.verify(run) == before
    calls = []
    ledger.register_gate_hook('extension', lambda store, transition, *, plan:
                              calls.append(transition) or [{'reason': 'review_required'}])
    errors = ledger.decide(run, tmp_path, 'approve_plan', {})
    assert [e.code for e in errors] == ['ledger_review_required']
    assert calls == ['checkin1→execute']
    assert ledger.verify(run) == before


@pytest.mark.parametrize('spelling', ['checkin2->execute[s1]', 'checkin2→execute[s1]'])
def test_p02_qualified_transitions_pass_the_canonical_name(run, spelling):
    calls = []
    ledger.register_gate_hook('extension', lambda store, transition, *, plan: calls.append(transition) or [])
    ledger.gate(run, spelling)
    assert calls == ['checkin2→execute']


@pytest.mark.parametrize('mutation', [None, 'blob', 'plan', 'pin', 'path'])
def test_p02_hooks_resolve_and_verify_the_stored_plan_blob(run, mutation):
    plan = deepcopy(PLAN)
    plan['sha256'] = chain.digest({k: v for k, v in plan.items() if k != 'sha256'})
    ledger.materialise(run, 'plan', {'plan': plan})
    stored = deepcopy(plan)
    if mutation == 'plan':
        stored['steps'][0]['operation'] = 'changed'
    raw = json.dumps(stored).encode()
    digest = sha256(raw).hexdigest()
    path = run.path('blobs', digest)
    path.parent.mkdir()
    path.write_bytes(raw if mutation != 'blob' else b'{}')
    blob = {'path': '../outside', 'sha256': digest} if mutation == 'path' else digest
    run.append('plan', {'plan_sha256': '0' * 64 if mutation == 'pin' else plan['sha256'], 'blob': blob})
    calls = []
    ledger.register_gate_hook('extension', lambda store, transition, *, plan: calls.append(plan) or [])
    unmet = ledger.gate(run, 'deliver[qualified]')
    if mutation is None:
        assert unmet == [] and calls == [plan]
    else:
        assert 'gate_hook_plan_unavailable' in {r['reason'] for r in unmet}
        assert calls == [None]


def test_p02_ledger_import_does_not_require_collaborating_packages():
    source = ("import sys; sys.modules['ravel.controller.authority'] = None; "
              "sys.modules['ravel.controller.engagement'] = None; "
              "from ravel.controller import ledger; "
              "assert callable(ledger.register_gate_hook); assert callable(ledger.register_authority_reader)")
    result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_p02_raw_waiver_without_an_authenticated_reader_is_refused(run):
    uid = authority(run, obligations=['X-ROUTE'])
    key = ledger.instance_key('X-ROUTE', RUN, {})
    before = ledger.verify(run)
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.record(run, key, 'waived', {'authority': uid})
    assert raised.value.code == 'authority_unverified'
    assert ledger.verify(run) == before
    assert state_module.load(run, full=True).instances[key].status == 'pending'


def test_p02_every_controller_process_composes_the_authority_services_reader(tmp_path, monkeypatch):
    # Building the controller graph (at start and at every resume) installs the authority service's
    # authenticated reader, so a waiver recorded in a process that asked nothing yet is still read through it.
    import fakes
    from ravel.controller import authority, graph
    from ravel.workflow import graph_registry, graph_substrate as gs
    fakes.isolate(tmp_path, monkeypatch)
    with fakes.stand_in_graphs():
        ctx = gs._context(tmp_path, graph.GRAPH_ID, {'run_id': 'run-composition'})
        graph_registry.builder(ctx.row)(ctx)
    assert record_module._authority_reader is authority.read_authority
    graph.compose_services()                                    # idempotent: the same reader again
    assert record_module._authority_reader is authority.read_authority


def test_p02_one_controller_graph_build_registers_the_authority_reader_exactly_once(tmp_path, monkeypatch):
    # The composition has one path: a build registers the authority service's reader once, never a second time
    # through a duplicate composition callback.
    import fakes
    from ravel.controller import authority, graph
    from ravel.workflow import graph_registry, graph_substrate as gs
    fakes.isolate(tmp_path, monkeypatch)
    calls, register = [], ledger.register_authority_reader
    monkeypatch.setattr(ledger, 'register_authority_reader', lambda reader: (calls.append(reader), register(reader))[1])
    with fakes.stand_in_graphs():
        ctx = gs._context(tmp_path, graph.GRAPH_ID, {'run_id': 'run-composition-once'})
        graph_registry.builder(ctx.row)(ctx)
    assert calls == [authority.read_authority]
    assert record_module._authority_reader is authority.read_authority


def test_p02_a_stand_in_authority_composes_no_reader(monkeypatch):
    from ravel.controller import graph
    with graph.services(authority=types.SimpleNamespace(installed=False)):
        graph.compose_services()
    assert record_module._authority_reader is None
