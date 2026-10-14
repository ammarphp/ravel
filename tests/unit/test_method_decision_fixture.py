"""Synthetic fixture admission and explicit machine decision recording."""
from copy import deepcopy
import pytest
from method_decision_fixture import admit_method
from ravel.workflow import method_selection as method
from ravel.workflow.state_io import read_json


def test_fixture_admits_full_and_scan_and_labels_machine(tmp_path):
    path = admit_method(tmp_path, refresh=False)
    assert method.launch_errors(tmp_path, 'full') == []
    assert method.launch_errors(tmp_path, 'scan') == []
    assert read_json(path)['provenance']['authority'] == 'scripted_experiment'


def test_no_scientific_run_directory_has_no_inferred_compute_plan():
    # Existing backend test-domain leases have no scientific run directory.
    assert method.scientific_plan(None) is None
    assert method.scientific_plan(None, 'full') == 'full'
    # A scientific requirement without its run directory still fails closed.
    with pytest.raises(ValueError, match='run directory'):
        method.scientific_plan(None, 'science')
    with pytest.raises(ValueError, match='run directory'):
        method.require_launch(None, 'science')


def test_machine_writer_requires_a_complete_decision_and_preserves_records(tmp_path):
    original = read_json(admit_method(tmp_path / 'source', refresh=False))
    original['provenance']['authority'] = 'human_operator'
    path = method.record_machine_decision(tmp_path / 'run', original, authority='scripted_experiment', refresh=False)
    assert read_json(path)['provenance']['authority'] == 'scripted_experiment'
    assert original['provenance']['authority'] == 'human_operator'
    assert method.record_machine_decision(tmp_path / 'run', original, authority='scripted_experiment', refresh=False) == path
    changed = deepcopy(original); changed['required_output'] = 'Different fictional output'
    with pytest.raises(FileExistsError):
        method.record_machine_decision(tmp_path / 'run', changed, authority='scripted_experiment', refresh=False)
    assert read_json(path)['required_output'] == original['required_output']


@pytest.mark.parametrize('authority', ['human_operator', 'human_relayed', 'unknown'])
def test_machine_writer_cannot_claim_human_authority(tmp_path, authority):
    with pytest.raises(ValueError, match='machine authority'):
        method.record_machine_decision(tmp_path, {}, authority=authority, refresh=False)
    assert not (tmp_path / method.DECISION_PATH).exists()


def test_machine_writer_refuses_incomplete_or_unadmitted_records(tmp_path):
    with pytest.raises(ValueError):
        method.record_machine_decision(tmp_path, {}, authority='delegated_machine', refresh=False)
    assert not (tmp_path / method.DECISION_PATH).exists()
    record = read_json(admit_method(tmp_path / 'source', 'parameter_scan', refresh=False))
    record['cost_forecast']['status'] = 'unknown'
    with pytest.raises(ValueError, match='Top-two-rung'):
        method.record_machine_decision(tmp_path, record, authority='delegated_machine', refresh=False)
    assert not (tmp_path / method.DECISION_PATH).exists()
