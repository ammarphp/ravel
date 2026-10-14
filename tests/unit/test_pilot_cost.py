"""Measured pilot cost: supervised pilots on this machine -> forecast -> schema-3 record -> approval."""
import json
from pathlib import Path

import pytest

from ravel.workflow import pilot_cost, scoped, workflow_state
from ravel.workflow import cost_preflight
from ravel.workflow.state_io import atomic_json, read_json
from ravel.validation.validate_task_contract import validate as validate_contract

from test_scoped_generation_front_end import lepton_spec, native, plan


def pilot(tmp_path, name, events):
    spec = lepton_spec(native(tmp_path))
    spec["generation"]["events"] = events
    rd, _ = plan(tmp_path, spec, name)
    assert scoped.approve(rd, "Run this pilot", scripted=True) == 0
    assert scoped.run(rd) == 0, (rd / "logs/scoped-worker.log").read_text() if (rd / "logs/scoped-worker.log").exists() else ""
    return rd


def observation(units, wall, disk=1000, profile="p" * 64, machine=None):
    return {"schema_version": 1, "kind": "supervised_pilot_observation", "rundir": f"/pilot-{units}",
            "route": "scoped", "mode": "generate", "unit": "events", "units": units, "profile_sha256": profile,
            "wall_seconds": wall, "output_bytes": disk, "machine": machine or pilot_cost.machine_identity(),
            "plan_sha256": "0" * 64, "scaling_note": "events"}


@pytest.fixture
def target(monkeypatch):
    monkeypatch.setattr(pilot_cost, "scaling", lambda route, spec, base=None: ("events", spec["events"], "p" * 64, "events"))
    return {"mode": "generate", "events": 1000}


def test_two_pilot_sizes_give_a_line_and_a_conservative_upper_bound(target):
    result = pilot_cost.forecast([observation(10, 20.0), observation(20, 30.0)], target, route="scoped",
                                 margin=1.5, ceiling_seconds=1e6)
    assert result["fit"]["fixed_seconds"] == pytest.approx(10.0)
    assert result["fit"]["seconds_per_unit"] == pytest.approx(1.0)
    assert result["wall_seconds"][0] == pytest.approx(1010.0)
    assert result["wall_seconds"][1] == pytest.approx(1.5 * 2000.0)  # proportional scaling of the 10-event pilot
    assert result["disk_bytes_peak"] == pytest.approx(1.5 * 1000 * 100)
    assert result["decision"] == "fits_ceiling"


def test_single_pilot_scales_proportionally(target):
    result = pilot_cost.forecast([observation(100, 50.0)], target, route="scoped", margin=2)
    assert result["wall_seconds"] == pytest.approx([50.0, 1000.0])
    assert result["fit"] is None


def test_admission_refuses_a_budget_over_the_ceiling(target, tmp_path):
    result = pilot_cost.forecast([observation(100, 50.0)], target, route="scoped", margin=2, ceiling_seconds=600)
    assert result["decision"] == "exceeds_ceiling"
    path = tmp_path / "forecast.json"
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="exceeds the ceiling"):
        pilot_cost.record(path, mode="full")


@pytest.mark.parametrize("change,match", [
    (lambda o: o.update(profile_sha256="q" * 64), "differs from the target"),
    (lambda o: o["machine"].update(hostname="elsewhere"), "another machine"),
    (lambda o: o.update(units=5000), "larger than the target"),
])
def test_pilots_that_cannot_calibrate_are_refused(target, change, match):
    obs = observation(100, 50.0)
    change(obs)
    with pytest.raises(ValueError, match=match):
        pilot_cost.forecast([obs], target, route="scoped", margin=2)


def test_without_a_pilot_there_is_no_forecast(target):
    with pytest.raises(ValueError, match="at least one completed pilot"):
        pilot_cost.forecast([], target, route="scoped", margin=2)
    flat = pilot_cost.forecast([observation(10, 30.0), observation(20, 20.0)], target, route="scoped", margin=2)
    assert flat["fit"] is None and "fixed costs dominate" in flat["method"]
    assert flat["wall_seconds"] == pytest.approx([30.0, 2 * 3000.0])


def test_measured_record_validates_and_is_bound_to_its_basis(target, tmp_path, monkeypatch):
    result = pilot_cost.forecast([observation(10, 20.0), observation(20, 30.0)], target, route="scoped",
                                 margin=1.5, ceiling_seconds=1e6)
    path = tmp_path / "forecast.json"
    path.write_text(json.dumps(result))
    record = pilot_cost.record(path, mode="full", events_per_point=1000)
    assert record["calibration_status"] == "measured" and record["schema_version"] == 3
    assert record["walltime_h"][1] == pytest.approx(3000.0 / 3600)
    assert not pilot_cost.verify_record(record)
    path.write_text(json.dumps({**result, "margin": 1.0}))
    assert "changed" in pilot_cost.verify_record(record)[0]
    path.write_text(json.dumps(result))
    monkeypatch.setattr(pilot_cost, "machine_identity", lambda: {**result["machine"], "logical_cpus": 1024})
    assert "another machine" in pilot_cost.verify_record(record)[0]


def test_supervised_pilots_calibrate_an_approvable_bulk_launch(tmp_path):
    first, second = pilot(tmp_path, "pilot-a", 3), pilot(tmp_path, "pilot-b", 6)
    observed = [pilot_cost.observe(first), pilot_cost.observe(second)]
    assert [o["units"] for o in observed] == [3, 6] and all(o["wall_seconds"] > 0 for o in observed)
    assert observed[0]["profile_sha256"] == observed[1]["profile_sha256"]
    for i, obs in enumerate(observed):
        (tmp_path / f"obs{i}.json").write_text(json.dumps(obs))
    target_spec = lepton_spec(native(tmp_path))
    target_spec["generation"]["events"] = 12
    atomic_json(tmp_path / "target.json", target_spec)
    assert pilot_cost.main(["forecast", "--pilot", str(tmp_path / "obs0.json"), "--pilot", str(tmp_path / "obs1.json"),
                            "--target", str(tmp_path / "target.json"), "--route", "scoped", "--margin", "1.5",
                            "--output", str(tmp_path / "forecast.json")]) in (0, 1)
    forecast = read_json(tmp_path / "forecast.json")
    if forecast["decision"] != "fits_ceiling":
        pytest.skip("pilot timing on this machine exceeds the synthetic ceiling")
    rd, _ = plan(tmp_path, target_spec, "production")
    assert cost_preflight.main(["--mode", "full", "--events", "12", "--from-forecast", str(tmp_path / "forecast.json"),
                                "--rundir", str(rd)]) == 0
    record = read_json(rd / "inputs/cost_preflight.json")
    assert record["calibration_status"] == "measured"
    assert not validate_contract({**read_json(rd / "inputs/task_contract.json"), "cost_estimate": record})
    assert scoped.approve(rd, "Approve the measured production run", scripted=True) == 0
    assert workflow_state.verify_approval(str(rd), required_plan="full") == []
    # The forecast basis is part of the approval: editing it withdraws admission.
    (tmp_path / "forecast.json").write_text((tmp_path / "forecast.json").read_text() + " ")
    assert any("basis changed" in e for e in workflow_state.verify_approval(str(rd), required_plan="full"))


def test_uncalibrated_record_is_still_refused_for_bulk(tmp_path):
    rd, _ = plan(tmp_path, lepton_spec(native(tmp_path)), "uncalibrated")
    est = cost_preflight.estimate("full", 1, 3, "native", 1)
    atomic_json(rd / "inputs/cost_preflight.json", {"generated_by": "cost_preflight.py", "generated_utc": "", **est})
    assert scoped.approve(rd, "approve", scripted=True) == 0
    errors = workflow_state.verify_approval(str(rd), required_plan="full")
    assert errors and "uncalibrated" in errors[0]
