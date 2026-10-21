"""P11 history: authenticated deltas and real resource boundaries."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import research_cycle as cycle
from ravel.workflow import research_history as history
from ravel.workflow import state_io


@pytest.fixture
def genesis(tmp_path):
    root = tmp_path.resolve() / "campaign"
    state = cycle._seal({
        "revision": 0, "parent_sha256": None, "events": [], "resource_ledger": [],
        "contract": {"budget": {"calls": 128, "output_tokens": 100000,
                                  "wall_seconds": 3600, "native_attempts": 20},
                     "max_experiments": 3, "premises": []},
        "methodology": {"stages": [
            {"id": f"stage-{index}", "roles": ["producer", "reviewer"],
             "bound": {"max_rounds": 2}} for index in range(9)]},
        "unchanged_payload": "retained scientific context; " * 2400,
    })
    path = root / "history" / "0000.json"
    state_io.atomic_json(path, state)
    state_io.atomic_json(root / "head.json", cycle._pin(path))
    return root, state


def test_170_appends_restart_historical_reads_and_storage(genesis):
    root, state = genesis
    selected = {0: deepcopy(state)}
    full_snapshot_bytes = len(json.dumps(state).encode())
    for index in range(1, 171):
        state = cycle._commit(root, state, "fixture_observation", index=index)
        full_snapshot_bytes += len(json.dumps(state).encode())
        if index in (1, 85, 170):
            selected[index] = deepcopy(state)
        record = state_io.read_json(root / "history" / f"{index:04d}.json")
        assert record["kind"] == history.KIND
        assert "unchanged_payload" not in record
        assert all(row["path"] != ["unchanged_payload"] for row in record["changes"])
        appended = [row for row in record["changes"] if row["op"] == "append" and row["path"] == ["events"]]
        assert appended == [{"op": "append", "path": ["events"], "value": [
            {"revision": index, "kind": "fixture_observation", "index": index}]}]

    # Restart through the real loader, independently of the in-memory working state.
    loaded_root, restarted = cycle._load_history(root)
    assert loaded_root == root
    assert restarted == state
    assert len(restarted["events"]) == 170
    for revision, expected in selected.items():
        assert cycle.historical_state(root, revision) == expected
    stored_bytes = sum(path.stat().st_size for path in (root / "history").glob("*.json"))
    assert stored_bytes < full_snapshot_bytes / 5


def test_declared_stages_and_calls_raise_structural_capacity(genesis):
    _, state = genesis
    initial = history.capacity(state)
    assert initial > 170
    more_stages = deepcopy(state)
    more_stages["methodology"]["stages"].append(deepcopy(state["methodology"]["stages"][0]))
    assert history.capacity(more_stages) > initial
    more_calls = deepcopy(state)
    more_calls["contract"]["budget"]["calls"] += 1
    assert history.capacity(more_calls) > initial
    more_rounds = deepcopy(state)
    more_rounds['methodology']['stages'][0]['bound']['max_rounds'] += 1
    assert history.capacity(more_rounds) > initial


def small_genesis(root):
    state = cycle._seal({
        "revision": 0, "parent_sha256": None, "events": [], "resource_ledger": [],
        "contract": {"budget": {"calls": 0, "output_tokens": 0, "wall_seconds": 0, "native_attempts": 0},
                     "max_experiments": 0, "premises": []}})
    path = root / "history" / "0000.json"
    state_io.atomic_json(path, state)
    state_io.atomic_json(root / "head.json", cycle._pin(path))
    return state


def test_capacity_never_falls_below_the_former_fixed_journal_bound(tmp_path):
    state = small_genesis(tmp_path.resolve() / 'campaign')
    assert history.LEGACY_REVISIONS == 128
    assert history.capacity(state) == history.LEGACY_REVISIONS


def test_replay_admits_exactly_the_revisions_its_commits_admitted(tmp_path, monkeypatch):
    """A protocol bound after genesis raises capacity for later commits and replay alike."""
    monkeypatch.setattr(history, 'LEGACY_REVISIONS', 0)
    root = tmp_path.resolve() / 'campaign'
    state = small_genesis(root)
    initial = history.capacity(state)
    bound = deepcopy(state)
    bound['methodology'] = {'stages': [{'id': 'stage', 'roles': ['producer', 'reviewer'],
                                        'bound': {'max_rounds': 2}}]}
    state = cycle._commit(root, bound, 'protocol_bound')
    assert history.capacity(state) > initial + 4
    while state['revision'] < initial + 3:
        state = cycle._commit(root, state, 'fixture_observation')
    with history._LOCK:
        history._VERIFIED.clear()
    assert cycle._load_history(root)[1] == state
    assert cycle.historical_state(root, 1)['methodology'] == bound['methodology']


def test_legacy_snapshots_within_the_former_bound_stay_readable_and_extendable(tmp_path):
    root = tmp_path.resolve() / 'campaign'
    state = small_genesis(root)
    # The structural ceiling alone is 17 here; these records were admitted under the former bound.
    for revision in range(1, 21):
        legacy = deepcopy(state)
        legacy['revision'] = revision
        legacy['parent_sha256'] = legacy.pop('sha256')
        legacy['events'].append({'revision': revision, 'kind': 'legacy_full_snapshot'})
        state = cycle._seal(legacy)
        path = root / 'history' / f'{revision:04d}.json'
        state_io.atomic_json(path, state)
    state_io.atomic_json(root / 'head.json', cycle._pin(path))
    assert cycle._load_history(root)[1] == state
    current = cycle._commit(root, state, 'new_delta')
    assert cycle._load_history(root)[1] == current


def test_forged_record_beyond_capacity_is_refused_by_commit_and_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(history, 'LEGACY_REVISIONS', 24)
    root = tmp_path.resolve() / 'campaign'
    state = small_genesis(root)
    assert history.capacity(state) == 24
    while state['revision'] < 23:
        state = cycle._commit(root, state, 'fixture_observation')
    before = sorted(path.name for path in (root / 'history').iterdir())
    with pytest.raises(ValueError, match='structural capacity'):
        cycle._commit(root, state, 'beyond')
    assert sorted(path.name for path in (root / 'history').iterdir()) == before
    prior_record = state_io.read_json(root / 'history' / '0023.json')
    newer = deepcopy(state)
    newer['revision'] = 24
    newer['parent_sha256'] = newer.pop('sha256')
    newer['events'].append({'revision': 24, 'kind': 'forged'})
    newer = cycle._seal(newer)
    forged = cycle._seal({'kind': history.KIND, 'revision': 24, 'parent_sha256': state['sha256'],
                          'parent_record_sha256': prior_record['sha256'], 'result_sha256': newer['sha256'],
                          'changes': history.changes(state, newer)})
    path = root / 'history' / '0024.json'
    state_io.atomic_json(path, forged)
    state_io.atomic_json(root / 'head.json', cycle._pin(path))
    with pytest.raises(ValueError, match='structural capacity'):
        cycle._load_history(root)
    with pytest.raises(ValueError, match='structural capacity'):
        cycle.historical_state(root, 0)


@pytest.mark.parametrize('through', [True, False, 0.0, 1.0, '0', [], {}, -1, 2])
def test_replay_requires_exact_integer_revision(genesis, through):
    root, state = genesis
    state = cycle._commit(root, state, 'first')
    head = state_io.read_json(root / 'history' / '0001.json')
    with pytest.raises(ValueError, match='invalid research history revision'):
        history.replay(root, head, through=through)


@pytest.mark.parametrize('operations', [
    None, {}, [None], [{'op': [], 'path': []}], [{'op': {}, 'path': []}],
    [{'op': 'set', 'path': ['items', True], 'value': 1}],
    [{'op': 'set', 'path': ['items', 0.0], 'value': 1}],
    [{'op': 'set', 'path': ['items', -1], 'value': 1}],
    [{'op': 'set', 'path': ['items', 1], 'value': 1}],
    [{'op': 'set', 'path': [[], 'nested'], 'value': 1}],
    [{'op': 'append', 'path': [{}], 'value': []}],
    [{'op': 'delete', 'path': [False]}],
    [{'op': 'set', 'path': ['missing', 'nested'], 'value': 1}],
    [{'op': 'set', 'path': 'items', 'value': 1}],
])
def test_malformed_delta_refuses_without_mutating_state(operations):
    state = {'items': [{'nested': 0}]}
    before = deepcopy(state)
    with pytest.raises(ValueError):
        history.apply(state, operations)
    assert state == before


def test_delta_copies_values_and_preserves_input_on_late_failure():
    state = {'items': [{'nested': 0}]}
    operations = [{'op': 'set', 'path': ['items', 0, 'nested'], 'value': {'value': []}}]
    result = history.apply(state, operations)
    result['items'][0]['nested']['value'].append(1)
    assert state == {'items': [{'nested': 0}]}
    assert operations[0]['value'] == {'value': []}
    with pytest.raises(ValueError):
        history.apply(state, operations + [{'op': 'delete', 'path': ['items', 0]}])
    assert state == {'items': [{'nested': 0}]}


def test_resealed_intermediate_checksum_with_relinked_descendants_is_refused(genesis):
    root, original = genesis
    states = [original]
    for index in range(1, 4):
        states.append(cycle._commit(root, states[-1], 'fixture', index=index))

    forged = deepcopy(states[1])
    forged['sha256'] = '0' * 64
    previous_record = original
    prior = original
    for revision in range(1, 4):
        if revision > 1:
            successor = deepcopy(states[revision])
            successor['parent_sha256'] = forged['sha256']
            successor.pop('sha256')
            forged = cycle._seal(successor)
        record = cycle._seal({
            'kind': history.KIND, 'revision': revision,
            'parent_sha256': prior['sha256'],
            'parent_record_sha256': previous_record['sha256'],
            'result_sha256': forged['sha256'],
            'changes': history.changes(prior, forged),
        })
        path = root / 'history' / f'{revision:04d}.json'
        state_io.atomic_json(path, record)
        prior, previous_record = deepcopy(forged), record
    state_io.atomic_json(root / 'head.json', cycle._pin(path))
    for through in (None, 0, 2, 3):
        with pytest.raises(ValueError, match='reconstructed research history content differs'):
            history.replay(root, previous_record, through=through)


def test_streamed_states_are_detached_and_verify_head(genesis):
    root, original = genesis
    current = cycle._commit(root, original, 'first')
    head = state_io.read_json(root / 'history' / '0001.json')
    iterator = history.states(root, head)
    first = next(iterator)
    first['events'].append({'forged': True})
    first['contract']['budget']['calls'] = 0
    assert next(iterator) == current
    with pytest.raises(StopIteration):
        next(iterator)
    assert cycle.historical_state(root, 0) == original
    forged_head = deepcopy(head)
    forged_head['result_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='research head differs'):
        list(history.states(root, forged_head))


def test_genesis_must_have_no_parent(genesis):
    root, original = genesis
    forged = {**original, 'parent_sha256': '0' * 64}
    forged.pop('sha256')
    forged = cycle._seal(forged)
    state_io.atomic_json(root / 'history' / '0000.json', forged)
    with pytest.raises(ValueError, match='research ancestry differs'):
        history.replay(root, forged)


@pytest.mark.parametrize("damage", ["tamper", "reorder", "delete", "parent_state", "parent_record"])
def test_history_damage_refuses_current_and_historical_reads(genesis, damage):
    root, state = genesis
    for index in range(1, 4):
        state = cycle._commit(root, state, "fixture_observation", index=index)
    first = root / "history" / "0001.json"
    second = root / "history" / "0002.json"
    if damage == "tamper":
        record = state_io.read_json(first)
        record["changes"].append({"op": "set", "path": ["unchanged_payload"], "value": "forged"})
        state_io.atomic_json(first, record)
    elif damage == "reorder":
        first_bytes, second_bytes = first.read_bytes(), second.read_bytes()
        first.write_bytes(second_bytes)
        second.write_bytes(first_bytes)
    elif damage == "delete":
        first.unlink()
    else:
        record = state_io.read_json(second)
        key = "parent_sha256" if damage == "parent_state" else "parent_record_sha256"
        record[key] = "0" * 64
        del record["sha256"]
        # Re-seal the damaged record: ancestry must be checked beyond its own content digest.
        state_io.atomic_json(second, cycle._seal(record))

    for read in (lambda: cycle._load_history(root), lambda: cycle.historical_state(root, 0)):
        with pytest.raises((ValueError, OSError)):
            read()


def test_stale_commit_refuses_without_new_history_or_changed_head(genesis):
    root, stale = genesis
    current = cycle._commit(root, stale, "first")
    before_head = (root / "head.json").read_bytes()
    before_files = sorted(path.name for path in (root / "history").iterdir())
    with pytest.raises(ValueError, match="stale campaign state"):
        cycle._commit(root, stale, "stale")
    assert (root / "head.json").read_bytes() == before_head
    assert sorted(path.name for path in (root / "history").iterdir()) == before_files
    assert cycle._load_history(root)[1] == current


def test_legacy_full_snapshot_then_new_delta_replays(genesis):
    root, original = genesis
    legacy = deepcopy(original)
    legacy["revision"] = 1
    legacy["parent_sha256"] = legacy.pop("sha256")
    legacy["events"].append({"revision": 1, "kind": "legacy_full_snapshot"})
    legacy = cycle._seal(legacy)
    path = root / "history" / "0001.json"
    state_io.atomic_json(path, legacy)
    state_io.atomic_json(root / "head.json", cycle._pin(path))
    assert cycle._load_history(root)[1] == legacy
    current = cycle._commit(root, legacy, "new_delta")
    assert state_io.read_json(root / "history" / "0002.json")["kind"] == history.KIND
    assert cycle._load_history(root)[1] == current
    assert cycle.historical_state(root, 0) == original
    assert cycle.historical_state(root, 1) == legacy
    assert cycle.historical_state(root, 2) == current


def test_real_call_budget_raises_value_error_before_ledger_mutation(genesis):
    _, state = genesis
    amount = {key: 0 for key in cycle.VECTORS}
    cycle._charge(state, "first-reservation", {**amount, "calls": 127}, {"fixture": "first"})
    before = deepcopy(state)
    with pytest.raises(ValueError, match="resource ceiling exhausted: calls") as refused:
        cycle._charge(state, "excess-reservation", {**amount, "calls": 2}, {"fixture": "excess"})
    assert isinstance(refused.value, cycle.CampaignBudgetExhausted)
    assert isinstance(refused.value, cycle.OperationalBoundaryError)
    assert state == before


def test_research_history_and_controller_are_in_the_frozen_implementation_closure():
    from pathlib import Path
    from ravel.workflow import research_orchestrator as orchestrator, research_controller, research_history, research_protocol
    pins = {row['path']: row for row in orchestrator._sources()}
    for module in (research_controller, research_history, research_protocol):
        path = Path(module.__file__).resolve()
        assert str(path) in pins
        assert pins[str(path)] == cycle._pin(path)
    assert {'workflow/research_history.py', 'workflow/research_controller.py'} <= set(orchestrator.PARITY_SOURCES)
