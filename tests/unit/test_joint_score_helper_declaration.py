"""Portable authority-transport checks with supplied contracts, no model work."""
from pathlib import Path
import sys

import pytest

from ravel.physics import joint_score as score
from ravel.workflow import helper_registration as registration


@pytest.fixture
def context(tmp_path, monkeypatch):
    source = tmp_path / "historical.py"
    source.write_text("# supplied helper source\n")
    contract = {"boundary_source": registration.pin(source),
                "old_runtime": {"interpreter_invocation": sys.executable,
                                "interpreter_binary": registration.binary_pin(Path(sys.executable).resolve())},
                "source_epoch": 1}
    calls = []
    def capture(task, base):
        calls.append((task, base))
        return {"qualification": {"contract": contract}}
    monkeypatch.setattr(score, "_capture", capture)
    monkeypatch.setattr(registration, "KernelObserver", lambda *a, **k: pytest.fail("No kernel observer in planning"))
    monkeypatch.setattr(registration.socket, "socket", lambda *a, **k: pytest.fail("No registration socket in planning"))
    monkeypatch.setattr(registration.os, "fork", lambda *a, **k: pytest.fail("No process in planning"))
    return contract, calls, source


def test_exact_attempt_roots_and_contract_with_no_reservation(context, tmp_path):
    contract, calls, _ = context
    output = tmp_path / "outputs" / "attempt-1"
    result = score.helper_declaration({"input": "supplied"}, tmp_path, output)
    assert not output.exists()
    assert calls == [({"input": "supplied"}, tmp_path)]
    actual = {r["key"]: r for r in result["helpers"]}
    assert set(actual) == {"initial", "final"}
    for phase in actual:
        assert actual[phase]["request_root"] == str(output / "historical-qualification" / phase)
        assert actual[phase]["contract_sha256"] == registration.digest(contract)
        assert actual[phase]["helper_source"] == contract["boundary_source"]
    assert result["max_helpers"] == 2


def test_new_attempt_changes_static_declaration_without_side_effect(context, tmp_path):
    first = score.helper_declaration({}, tmp_path, tmp_path / "attempt-1")
    second = score.helper_declaration({}, tmp_path, tmp_path / "attempt-2")
    assert registration.digest(first) != registration.digest(second)
    assert not (tmp_path / "attempt-1").exists()
    assert not (tmp_path / "attempt-2").exists()


def test_same_session_does_not_cache_old_contract_authority(context, tmp_path):
    contract, calls, _ = context
    session = object()
    first = score.helper_declaration({}, tmp_path, tmp_path / "attempt", _session=session)
    contract["source_epoch"] = 2
    second = score.helper_declaration({}, tmp_path, tmp_path / "attempt", _session=session)
    assert len(calls) == 2
    assert first["helpers"][0]["contract_sha256"] != second["helpers"][0]["contract_sha256"]


def test_changed_helper_bytes_refuse_before_declaration(context, tmp_path):
    _, _, source = context
    source.write_text("# changed after captured pin\n")
    with pytest.raises(ValueError):
        score.helper_declaration({}, tmp_path, tmp_path / "attempt")
    assert not (tmp_path / "attempt").exists()


def test_symlinked_attempt_root_refuses(context, tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError):
        score.helper_declaration({}, tmp_path, alias / "attempt")
    assert list(actual.iterdir()) == []


def test_failed_qualification_cannot_mint_a_declaration(context, tmp_path, monkeypatch):
    def failed(*a):
        raise ValueError("Historical law no longer admitted")
    monkeypatch.setattr(score, "_capture", failed)
    monkeypatch.setattr(registration, "declaration", lambda *a, **k: pytest.fail("No authority after failed qualification"))
    with pytest.raises(ValueError, match="Historical law no longer admitted"):
        score.helper_declaration({}, tmp_path, tmp_path / "attempt")


def test_registration_refusal_propagates_without_fallback(context, tmp_path, monkeypatch):
    def refused(*a, **k):
        raise ValueError("Unsupported declared owner")
    monkeypatch.setattr(registration, "declaration", refused)
    with pytest.raises(ValueError, match="Unsupported declared owner"):
        score.helper_declaration({}, tmp_path, tmp_path / "attempt")


def test_composite_process_and_registry_bounds_keep_mathematical_budget():
    design = {"resource_bounds": {"processes": 1, "execution_seconds": 150, "maximum_objective_calls": 2000}}
    design.update(cases=[{'id':c,'expected_free_coordinates':{'free':2,'fixed':1},'original_named_seeds':[{'id':str(i)} for i in range(3)]} for c in ('CASE-0001','CASE-0002')],objectives=[{'id':'free','fixed_mu':None},{'id':'fixed','fixed_mu':1.}])
    before = dict(design["resource_bounds"])
    bounds = score._bounds(design)
    assert bounds["processes"] == bounds["peak_processes_including_supervisor"] == 5
    assert bounds["maximum_mathematical_workers"] == 1
    assert bounds["peak_processes_during_math_including_supervisor"] == 2
    assert bounds["maximum_fit_calls"] == 4 and bounds["original_seed_denominator"] == 12
    assert bounds["execution_seconds"] == 150 and bounds["maximum_objective_calls"] == 2000
    assert bounds["owner_registry_output_bytes"] == 1024**2
    assert bounds["helper_owner_cleanup_reserve_seconds"] == 3
    assert bounds["owner_registry_counts_against_worker_144MiB"] is False
    assert design["resource_bounds"] == before
