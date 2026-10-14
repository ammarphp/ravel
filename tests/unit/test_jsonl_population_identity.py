"""A JSON-lines cohort is an evaluation population by its decoded records."""
import json
import pytest
from ravel.physics import ml_exposure
from ravel.workflow import research_cycle as cycle, research_evaluation as evaluation


def cohort(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return cycle._pin(path)


ROWS = [{'event_id': '0', 'group_id': 'g', 'weights': {'nominal': 2}, 'fills': [[.5]]},
        {'event_id': '1', 'group_id': 'g', 'weights': {'nominal': -1}, 'fills': [[.5]]}]


def test_identity_is_decoded_content_with_events_groups_and_label_free_values(tmp_path):
    pin = cohort(tmp_path / 'records.jsonl', ROWS)
    identity = evaluation.population_identity(pin, tmp_path)
    assert identity['event_ids'] == ['0', '1'] and identity['group_ids'] == ['g']
    assert identity['byte_sha256'] == pin['sha256'] and len(identity['value_hashes']) == 2
    # Line encoding is not identity: the same records with other spacing and key order.
    other = tmp_path / 'respaced.jsonl'
    other.write_text('\n'.join(json.dumps(dict(reversed(list(row.items()))), indent=None, separators=(', ', ': '))
                               for row in ROWS) + '\n\n')
    again = evaluation.population_identity(cycle._pin(other), tmp_path)
    assert again['byte_sha256'] != identity['byte_sha256']
    assert {k: again[k] for k in ('sha256', 'event_ids', 'group_ids', 'value_hashes')} == {
        k: identity[k] for k in ('sha256', 'event_ids', 'group_ids', 'value_hashes')}


def test_shared_events_groups_and_relabelled_copies_overlap_while_fresh_records_do_not(tmp_path):
    base = evaluation.population_identity(cohort(tmp_path / 'base.jsonl', ROWS), tmp_path)
    relabelled = [{**row, 'event_id': 'r' + row['event_id'], 'group_id': 'other'} for row in ROWS]
    fresh = [{'event_id': 'f0', 'group_id': 'h', 'weights': {'nominal': 7}, 'fills': [[.25]]}]
    shared_group = [{**fresh[0], 'group_id': 'g'}]
    shared_event = [{**fresh[0], 'event_id': '1'}]
    seen = {name: evaluation.population_identity(cohort(tmp_path / (name + '.jsonl'), rows), tmp_path)
            for name, rows in [('relabelled', relabelled), ('fresh', fresh), ('group', shared_group), ('event', shared_event)]}
    assert ml_exposure.overlaps(base, seen['relabelled']) and ml_exposure.overlaps(base, seen['group'])
    assert ml_exposure.overlaps(base, seen['event']) and not ml_exposure.overlaps(base, seen['fresh'])
    assert set(base['value_hashes']) == set(seen['relabelled']['value_hashes'])


@pytest.mark.parametrize('text', ['', '\n', '[1, 2]\n', '{"event_id": "0"}\n{"event_id": "0"}\n',
                                  '{"weights": 1}\n', '{"event_id": "0"}\nnot json\n'])
def test_empty_malformed_or_ambiguous_cohorts_are_refused(tmp_path, text):
    path = tmp_path / 'records.jsonl'
    path.write_text(text or ' ')
    with pytest.raises(ValueError):
        evaluation.population_identity(cycle._pin(path), tmp_path)


def test_changed_bytes_are_refused(tmp_path):
    pin = cohort(tmp_path / 'records.jsonl', ROWS)
    (tmp_path / 'records.jsonl').write_text(json.dumps(ROWS[0]) + '\n')
    with pytest.raises(ValueError, match='changed'):
        evaluation.population_identity(pin, tmp_path)
