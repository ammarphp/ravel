"""Pure engineering controls; no model/native execution or repair efficacy claim."""
from copy import deepcopy
import json
import random

import pytest

from ravel.physics import routine_candidate as candidate

def event(identity, *, jets=2, weight=1.0, pt=40.0):
    return {'event_id': identity, 'group_id': identity,
            'weights': {'nominal': weight},
            'objects': {'electron': [], 'muon': [], 'jet': [
                {'pt': pt, 'eta': 0.0, 'phi': 0.0, 'mass': 0.0, 'charge': 0, 'idbits': 0}
                for _ in range(jets)]}, 'met': {'pt': 0.0, 'phi': 0.0}}


def witness(row, nodes, *, left=('SR',), right=('SR',), interface=False):
    selection = interface or set(left) != set(right)
    return {'event_id': row['event_id'], 'first_divergent_node': nodes[0] if nodes else None,
            'source_output_differences': [{'node': name, 'expected': 1.0, 'actual': 2.0}
                                          for name in nodes],
            'selection_changed': selection,
            'change_kind': 'selection_changed' if selection else 'numerical_only',
            'left_regions': list(left), 'right_regions': list(right),
            'input_event_sha256': candidate._digest(row), 'object_lineage': {'jet': []}}


def body_size(rows, events):
    by_id = {row['event_id']: row for row in events}
    body = {'witnesses': rows, 'events': [by_id[row['event_id']] for row in rows]}
    return len(json.dumps(body, sort_keys=True, allow_nan=False).encode())


def atoms(rows):
    return set().union(*(candidate._repair_witness_atoms(row) for row in rows))


def clustered():
    events = [event('repeat' + str(i), jets=8) for i in range(4)]
    rows = [witness(row, ['n_jets']) for row in events]
    for row in rows:
        row['source_output_differences'][0].update(expected=8, actual=7)
    # These are source-output names in the actual witness schema, not new
    # inferred fault categories. They do not instantiate a physics dataset.
    for identity, node, kwargs, differences in [
        ('boundary', 'passes_pt', {'pt': 30.0}, {'left': (), 'right': ('SR',)}),
        ('sign', 'signed_weight', {'weight': -0.5}, {}),
        ('normalization', 'normalised_yield', {}, {}),
    ]:
        row = event(identity, **kwargs)
        events.append(row)
        rows.append(witness(row, [node], **differences))
        expected, actual = {'boundary': (False, True), 'sign': (-0.5, 0.5),
                            'normalization': (0.25, 1.0)}[identity]
        rows[-1]['source_output_differences'][0].update(expected=expected, actual=actual)
    return rows, events


def test_late_obligations_displace_redundant_prefix_without_extra_context():
    rows, events = clustered()
    selected = candidate._select_repair_witnesses(rows, events)
    assert len(selected) == 4
    assert {'boundary', 'sign', 'normalization'} <= {row['event_id'] for row in selected}
    assert len(atoms(rows[:4])) == 1
    assert len(atoms(selected)) == 5
    assert atoms(selected) == atoms(rows)
    assert body_size(selected, events) <= body_size(rows[:4], events)


def test_full_underlying_feedback_and_selected_event_bytes_remain_unchanged():
    rows, events = clustered()
    before = json.dumps({'witnesses': rows, 'events': events}, sort_keys=True)
    selected = candidate._select_repair_witnesses(rows, events)
    assert all(row['input_event_sha256'] == candidate._digest(next(
        event for event in events if event['event_id'] == row['event_id'])) for row in selected)
    selected[0]['source_output_differences'][0]['actual'] = 999.0
    assert json.dumps({'witnesses': rows, 'events': events}, sort_keys=True) == before


def test_duplicate_obligations_need_only_one_example_and_keep_full_failure_denominator():
    events = [event('same' + str(i)) for i in range(7)]
    rows = [witness(row, ['n_jets']) for row in events]
    selected = candidate._select_repair_witnesses(rows, events)
    assert len(selected) == 1
    assert len(rows) == len(events) == 7
    assert atoms(selected) == atoms(rows)
    assert body_size(selected, events) <= body_size(rows[:4], events)


def test_selection_membership_and_interface_use_only_actual_schema_fields():
    row = event('boundary')
    assert candidate._repair_witness_atoms(witness(row, [], left=('SR',), right=('CR',))) == {
        ('membership', 'SR'), ('membership', 'CR')}
    assert candidate._repair_witness_atoms(witness(row, [], interface=True)) == {('selection_interface',)}
    assert candidate._repair_witness_atoms(witness(row, ['signed_weight'])) == {('output', 'signed_weight')}


def test_oversized_late_context_cannot_widen_existing_byte_allowance():
    events = [event('small' + str(i)) for i in range(4)]
    rows = [witness(row, ['n_jets']) for row in events]
    big = event('late', jets=200)
    events.append(big)
    rows.append(witness(big, ['a', 'b', 'c', 'd', 'e']))
    selected = candidate._select_repair_witnesses(rows, events)
    assert 'late' not in {row['event_id'] for row in selected}
    assert body_size(selected, events) <= body_size(rows[:4], events)


def test_equal_allowance_ties_and_permutations_are_deterministic():
    events = [event('e' + str(i)) for i in range(8)]
    rows = [witness(row, ['obs_' + chr(97 + i)]) for i, row in enumerate(events)]
    expected = candidate._select_repair_witnesses(rows, events)
    allowance = body_size(rows[:4], events)
    generator = random.Random(83091)
    for _ in range(20):
        generator.shuffle(rows); generator.shuffle(events)
        assert body_size(rows[:4], events) == allowance
        assert candidate._select_repair_witnesses(rows, events) == expected
    assert len(expected) == 4


def test_greedy_set_cover_counterexample_preserves_better_prefix():
    # Four-observation budget: greedy takes a,b,c,d and covers ten atoms;
    # the original prefix b,c,d,e covers twelve. The fallback is required.
    labels = {'b': ['a', 'b', 'x', 'y'], 'c': ['c', 'd', 'z', 'w'],
              'd': ['p', 'q'], 'e': ['r', 's'], 'a': ['a', 'b', 'c', 'd']}
    events = [event(name, jets=12 if name in 'bcde' else 2) for name in labels]
    rows = [witness(row, labels[row['event_id']]) for row in events]
    selected = candidate._select_repair_witnesses(rows, events)
    assert len(atoms(rows[:4])) == 12
    assert len(atoms(selected)) == 12
    assert {row['event_id'] for row in selected} == {'b', 'c', 'd', 'e'}
    assert body_size(selected, events) <= body_size(rows[:4], events)


@pytest.mark.parametrize('failure', ['wrong_hash', 'missing_event', 'duplicate_witness', 'duplicate_event'])
def test_wrong_or_ambiguous_original_event_custody_is_refused(failure):
    row = event('e0'); rows = [witness(row, ['n'])]; events = [row]
    if failure == 'wrong_hash': rows[0]['input_event_sha256'] = '0' * 64
    if failure == 'missing_event': events = []
    if failure == 'duplicate_witness': rows.append(deepcopy(rows[0]))
    if failure == 'duplicate_event': events.append(deepcopy(row))
    with pytest.raises(ValueError):
        candidate._select_repair_witnesses(rows, events)


def test_empty_feedback_exposes_no_event():
    assert candidate._select_repair_witnesses([], [event('e0')]) == []
