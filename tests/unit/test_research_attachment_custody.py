"""Own source-only returned-result custody guard; no plan or worker runs."""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import research_cycle as cycle, failed_stage_review as failed
from test_research_cycle import write
from test_research_negative_continuation import observed_failure


def test_changed_previously_observed_result_refuses_canonical_attachment(tmp_path, monkeypatch):
    root, intake_pin, _ = observed_failure(tmp_path, monkeypatch)
    document = cycle._read(intake_pin, tmp_path)
    result_path = Path(document['result']['path'])
    _, state = cycle._load(root)
    state['experiments'][0]['observation']['result'] = cycle._pin(result_path)
    cycle._commit(root, state, 'own_observed_returned_result_fixture')
    changed = cycle._read(cycle._pin(result_path), tmp_path)
    changed['diagnostic_payload_changed_after_observation'] = True
    fresh_result = write(result_path, changed)
    request = deepcopy(document['request'])
    request['result']['sha256'] = fresh_result['sha256']
    for row in request['evidence']:
        if str(Path(row['path'])) == str(result_path):
            row['sha256'] = fresh_result['sha256']
    fresh_intake = write(tmp_path / 'later-capture.json', failed.intake(request, base_dir=document['run_dir']))
    _, before = cycle._load(root)
    # The existing ordinary consumer recognizes this stale result pin.
    with pytest.raises(ValueError):
        cycle._current_evidence(before, before['experiments'][0])
    with pytest.raises(ValueError):
        cycle.attach_failed_stage(root, 'paired', fresh_intake)
    assert cycle._load(root)[1] == before
