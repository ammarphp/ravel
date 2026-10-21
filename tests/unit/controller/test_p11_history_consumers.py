"""Exercise the six full-snapshot history consumers against real authenticated deltas.

No source gate is replaced and no scientific worker, provider, or generator runs
in these engineering controls.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.physics import root_stream_partitions
from ravel.workflow import (fresh_replication, literature_context, manuscript_production, manuscript_workflow,
                            procedure_export, research_cycle as cycle, state_io)
from test_research_cycle import contract


@pytest.fixture
def consumers():
    return {'procedure_export': procedure_export, 'manuscript_workflow': manuscript_workflow,
            'literature_context': literature_context, 'manuscript_production': manuscript_production,
            'fresh_replication': fresh_replication, 'root_stream_partitions': root_stream_partitions}


@pytest.fixture
def journal(tmp_path):
    base = tmp_path.resolve() / 'science'
    base.mkdir()
    root = base / 'campaign'
    cycle.create(root, contract(base), base_dir=base, evaluation_harness=True)
    _, state = cycle._load(root)
    original = deepcopy(state)
    # The census consumes whole experiment populations, including retained runs.
    first, second = base / 'first-run', base / 'second-run'
    first.mkdir(); second.mkdir()
    state['experiments'].append({'rundir': str(first)})
    first_state = cycle._commit(root, state, 'fixture_first_run')
    state = deepcopy(first_state)
    state['experiments'].append({'rundir': str(second)})
    state = cycle._commit(root, state, 'fixture_second_run')
    return root, original, first_state, state, [first, second]


def test_procedure_export_rehydrates_all_runs_and_retains_every_history_pin(consumers, journal):
    root, original, first, current, runs = journal
    pe = consumers['procedure_export']
    actual, pins, roots = pe._campaign_runs(root)
    assert actual == runs
    assert roots == [str(root)]
    assert current['revision'] == 2
    assert state_io.read_json(root / 'history/0002.json')['kind'] == 'research-history-delta.v1'
    expected = {str(root / 'head.json'), *(str(root / 'history' / f'{i:04d}.json') for i in range(3))}
    assert {row['path'] for row in pins} == expected
    for pin in pins:
        assert pe._source(pin['path']) == pin


def test_manuscript_selection_uses_hydrated_state_sha_and_authenticates_tail(consumers, journal):
    root, original, first, current, _ = journal
    mw = consumers['manuscript_workflow']
    stored = state_io.read_json(root / 'history/0001.json')
    assert stored['sha256'] != first['sha256']
    assert mw._history_state(root, current, sha256=first['sha256']) == first
    assert mw._history_state(root, current, revision=0) == original
    with pytest.raises(ValueError, match='absent'):
        mw._history_state(root, current, sha256=stored['sha256'])
    tail = root / 'history/0002.json'
    broken = state_io.read_json(tail)
    broken['changes'] = []
    state_io.atomic_json(tail, broken)
    # Even a genesis match cannot bypass a corrupted later revision.
    with pytest.raises(ValueError):
        mw._history_state(root, current, sha256=original['sha256'])


def test_literature_scope_journal_rehydrates_and_observes_every_record(consumers, journal):
    root, _, _, current, _ = journal
    lc = consumers['literature_context']
    authority = lc._Reader(root)
    head_pin, current_pin, snapshot = lc._scope_journal(root, authority, cycle)
    assert snapshot == current
    assert current_pin == cycle._pin(root / 'history/0002.json')
    assert {pin['path'] for pin in authority.pins()} == {
        str(root / 'head.json'), *(str(root / 'history' / f'{i:04d}.json') for i in range(3))}
    authority.finish()
    (root / 'history/0001.json').write_bytes(b'{}\n')
    with pytest.raises(ValueError):
        authority.finish()


def test_literature_scope_real_loader_handles_delta_head(consumers, tmp_path):
    base = tmp_path.resolve() / 'scope-science'; base.mkdir()
    root = base / 'campaign'
    cycle.create(root, contract(base), base_dir=base, evaluation_harness=True)
    _, state = cycle._load(root)
    state = cycle._commit(root, state, 'fixture_context_observation')
    lc = consumers['literature_context']
    scope = {'root': str(root), 'contract_sha256': cycle.ce.digest(state['contract'])}
    projection = lc._scope(scope, lc._Reader(base))
    assert projection['question'] == state['contract']['question']
    assert projection['contract_sha256'] == scope['contract_sha256']
    assert lc._SCOPE_VERIFICATION.get() == ()


def test_consumers_read_journal_beyond_old_128_revision_ceiling(consumers, journal):
    root, original, first, state, runs = journal
    for index in range(state['revision'] + 1, 130):
        state = cycle._commit(root, state, 'fixture_history_observation', index=index)
    assert state['revision'] == 129
    pe = consumers['procedure_export']
    assert pe._campaign_runs(root)[0] == runs
    mw = consumers['manuscript_workflow']
    assert mw._history_state(root, state, sha256=first['sha256']) == first
    lc = consumers['literature_context']
    authority = lc._Reader(root)
    assert lc._scope_journal(root, authority, cycle)[2] == state
    assert len(authority.pins()) == 131  # Head plus genesis and 129 deltas.
    authority.finish()


def test_origin_capture_and_replication_read_journal_beyond_old_128_revision_ceiling(consumers, journal,
                                                                                     monkeypatch):
    root, original, first, state, _ = journal
    for index in range(state['revision'] + 1, 130):
        state = cycle._commit(root, state, 'fixture_history_observation', index=index)
    production = consumers['manuscript_production']
    class QuantityContextRequired(Exception):
        pass
    def unavailable(*args):
        raise QuantityContextRequired('history verified; original scientific quantities still required')
    monkeypatch.setattr(production.scientific_report, '_context', unavailable)
    view = object.__new__(production._OriginView)
    state_io.atomic_json(root/'quantities.json', {'kind': 'quantity-context-pending'})
    supplied = {'documents': {'quantitative_report': {'context': {}}},
                'request': {'quantitative_report': {'path': str(root/'quantities.json')}},
                'source_base': root}
    with pytest.raises(QuantityContextRequired):
        view.__init__({'campaign': str(root)}, supplied)
    assert len(view.records) == 130 and view.records[:2] == [original, first] and view.records[-1] == state
    assert view.records == [cycle.historical_state(root, i) for i in range(130)]
    assert view.pins == [cycle._pin(root/'history'/f'{i:04d}.json') for i in range(130)]
    view.close()
    replication = consumers['fresh_replication']
    document = {'kind': 'fresh-replication-request', 'cycle_root': str(root), 'revision': 1,
        'state_sha256': first['sha256'], 'originals': [], 'inputs': [], 'base_dir': str(root),
        'report': {}, 'method_id': 'supplied-control', 'check_contract': {}}
    monkeypatch.setattr(replication, '_envelope', lambda *args: {})
    monkeypatch.setattr(replication, '_json', lambda *args: deepcopy(document))
    seen = []
    def reconstruct(*args, _state, **kwargs):
        seen.append(deepcopy(_state))
        return deepcopy(document)
    monkeypatch.setattr(replication, '_request', reconstruct)
    current, returned, _ = replication._prepared(root, cycle._pin(root/'head.json'))
    assert current == state and returned == document and seen == [first]
    (root/'history/0064.json').write_bytes(b'{}')
    with pytest.raises(ValueError):
        view.close()


def test_manuscript_origin_capture_hydrates_states_and_keeps_raw_record_pins(consumers, journal, monkeypatch):
    root, original, first, current, _ = journal
    production = consumers['manuscript_production']
    class QuantityContextRequired(Exception):
        pass
    def unavailable(*args):
        raise QuantityContextRequired('history verified; original scientific quantities still required')
    monkeypatch.setattr(production.scientific_report, '_context', unavailable)
    view = object.__new__(production._OriginView)
    state_io.atomic_json(root/'quantities.json', {'kind': 'quantity-context-pending'})
    supplied = {'documents': {'quantitative_report': {'context': {}}},
                'request': {'quantitative_report': {'path': str(root/'quantities.json')}},
                'source_base': root}
    with pytest.raises(QuantityContextRequired):
        view.__init__({'campaign': str(root)}, supplied)
    assert view.current == current and view.records == [original, first, current]
    assert view.owner is None  # A hydrated history is not scientific author approval.
    assert view.pins == [cycle._pin(root/'history'/f'{i:04d}.json') for i in range(3)]
    view.close()
    (root/'history/0001.json').write_bytes(b'{}')
    with pytest.raises(ValueError):
        view.close()


def test_replication_reconstructs_original_delta_state_before_producer_comparison(consumers, journal, monkeypatch):
    root, original, first, current, _ = journal
    replication = consumers['fresh_replication']
    document = {'kind': 'fresh-replication-request', 'cycle_root': str(root), 'revision': 1,
        'state_sha256': first['sha256'], 'originals': [], 'inputs': [], 'base_dir': str(root),
        'report': {}, 'method_id': 'supplied-control', 'check_contract': {}}
    pin = cycle._pin(root/'head.json')
    # The issued document and quantitative producer are peer seams. The original
    # historical ancestry and old-state/whole-contract comparisons remain real.
    monkeypatch.setattr(replication, '_envelope', lambda *args: {})
    monkeypatch.setattr(replication, '_json', lambda *args: deepcopy(document))
    seen = []
    def reconstruct(*args, _state, **kwargs):
        seen.append(deepcopy(_state))
        return deepcopy(document)
    monkeypatch.setattr(replication, '_request', reconstruct)
    state, returned, consumed = replication._prepared(root, pin)
    assert state == current and returned == document and seen == [first]
    document['state_sha256'] = state_io.read_json(root/'history/0001.json')['sha256']
    with pytest.raises(ValueError, match='original replication state'):
        replication._prepared(root, pin)
    assert seen == [first]


def test_stream_reservation_uses_declared_capacity_after_128_revisions(consumers, tmp_path):
    base = tmp_path/'reservation'; base.mkdir()
    root = base/'campaign'
    cycle.create(root, contract(base), base_dir=base, evaluation_harness=True)
    _, state = cycle._load(root)
    for index in range(129):
        state = cycle._commit(root, state, 'fixture_before_reservation', index=index)
    partitions = consumers['root_stream_partitions']
    source = root/'master.json'; state_io.atomic_json(source, {'kind': 'fictional-inert-reservation'})
    pin = cycle._pin(source)
    master = {'base_spec': {'sha256': 'a'*64}, 'master_pin': pin,
        'partitions': [{'id': 'one'}], 'budget': {'max_total_seconds': 1},
        'owner': {'kind': 'research_cycle', 'cycle': str(root),
            'contract_sha256': cycle.ce.digest(state['contract']),
            'context_request_sha256': state['context']['request_sha256'],
            'attempt_journal': {'directory': str(root/'root-stream-attempts'/('a'*64)), 'capacity': 2}}}
    partitions.reserve_master(master)
    final = cycle._load(root)[1]
    assert final['revision'] == 130
    assert final['resource_ledger'][-1] == partitions.reservation(master)
    assert (Path(master['owner']['attempt_journal']['directory'])/'history/00000.json').is_file()
    assert not (root/'execution_attempt.json').exists()
    with pytest.raises(ValueError, match='reservation cannot be reset'):
        partitions.reserve_master(master)
