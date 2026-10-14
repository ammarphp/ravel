"""trap_sweep writes exactly the record the lifecycle validator reads."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ravel.validation import validate_run_state as vrs
from ravel.workflow import trap_sweep

TRAPS = [f"T{i}" for i in range(1, 13)]


def clean_verdicts(**hits):
    rows = []
    for trap in TRAPS:
        if trap in hits:
            rows.append({"id": trap, "hit": True, **hits[trap]})
        else:
            rows.append({"id": trap, "hit": False, "evidence": f"checked {trap}: not applicable here"})
    return rows


def write_input(tmp_path, document):
    path = tmp_path / "sweep-input.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def validator_status(rundir):
    facts = {"trap_sweep_path": "inputs/trap_sweep.json"}
    return vrs.check_trap_sweep(str(rundir), {}, facts, "R", False)


def test_clean_sweep_records_all_traps_and_passes_the_lifecycle_check(tmp_path):
    run = tmp_path / "run"
    (run / "inputs").mkdir(parents=True)
    out = trap_sweep.write(run, {"verdicts": clean_verdicts()})
    doc = json.loads(out.read_text())
    assert out == run / "inputs" / "trap_sweep.json"
    assert doc["traps_checked"] == TRAPS
    assert doc["traps_hit"] == [] and doc["none_hit"] is True
    status, _, checks = validator_status(run)
    assert status == "PASS", checks


def test_flagged_hit_gets_verdict_row_and_pending_obligation(tmp_path):
    run = tmp_path / "run"
    hit = {"evidence": "requested width over mass reaches 0.2", "consequence": "width-dependent shape study",
           "flag_number": 3}
    out = trap_sweep.write(run, {"verdicts": clean_verdicts(T8=hit)})
    doc = json.loads(out.read_text())
    assert [h["id"] for h in doc["traps_hit"]] == ["T8"]
    assert doc["traps_hit"][0]["flag_number"] == 3
    verdict = next(v for v in doc["verdicts"] if v["id"] == "T8")
    assert verdict["flag_number"] == 3 and verdict["hit"] is True
    assert [(o["trap"], o["status"]) for o in doc["obligations"]] == [("T8", "PENDING")]
    status, _, checks = validator_status(run)
    assert status == "PASS", checks
    assert any(c["name"] == "traps_hit_disposition" and c["level"] == "PASS" for c in checks)


def test_escalated_hit_without_flag_is_accepted(tmp_path):
    run = tmp_path / "run"
    hit = {"evidence": "shared initial and final state with a large SM process",
           "consequence": "coherent signal-plus-background model needed"}
    doc = {"verdicts": clean_verdicts(T1=hit),
           "escalations": [{"id": "T1", "reason": "statistical model choice needs physicist input"}]}
    trap_sweep.write(run, doc)
    status, _, checks = validator_status(run)
    assert status == "PASS", checks


def test_basis_traps_do_not_open_trap_obligations(tmp_path):
    run = tmp_path / "run"
    hit = {"evidence": "charge-summed reference against single-charge grid", "consequence": "basis manifest",
           "flag_number": 1}
    doc = json.loads(trap_sweep.write(run, {"verdicts": clean_verdicts(T9=hit)}).read_text())
    assert doc["obligations"] == []


def test_supplied_obligations_are_kept_and_not_duplicated(tmp_path):
    run = tmp_path / "run"
    hit = {"evidence": "displaced vertices selected", "consequence": "efficiency-map folding", "flag_number": 2}
    supplied = [{"trap": "T2", "obligation_kind": "efficiency-map-folding", "artifact": "inputs/effmaps.json",
                 "status": "PASS"}]
    doc = json.loads(trap_sweep.write(run, {"verdicts": clean_verdicts(T2=hit), "obligations": supplied}).read_text())
    assert doc["obligations"] == supplied


@pytest.mark.parametrize("change,message", [
    (lambda d: d["verdicts"].pop(), "T12"),
    (lambda d: d["verdicts"].append({"id": "T1", "hit": False, "evidence": "again"}), "duplicate"),
    (lambda d: d["verdicts"].append({"id": "T13", "hit": False, "evidence": "x"}), "T13"),
    (lambda d: d["verdicts"][0].update(hit=True, consequence="route change"), "flag_number"),
    (lambda d: d["verdicts"][0].update(hit=True, flag_number=1), "consequence"),
    (lambda d: d["verdicts"][0].update(evidence=" "), "evidence"),
    (lambda d: d["verdicts"][0].update(hit="yes"), "hit"),
    (lambda d: d["verdicts"][0].update(hit=True, consequence="c", flag_number=0), "flag_number"),
    (lambda d: d.update(obligations=[{"trap": "T1", "obligation_kind": "k", "artifact": None,
                                      "status": "DONE"}]), "status"),
    (lambda d: d.update(obligations=[{"trap": "T1", "obligation_kind": "k", "artifact": None,
                                      "status": "PASS"}]), "artifact"),
    (lambda d: d.update(extra=1), "extra"),
])
def test_incomplete_or_ambiguous_sweeps_are_refused(tmp_path, change, message):
    document = {"verdicts": clean_verdicts()}
    change(document)
    with pytest.raises(ValueError, match=message):
        trap_sweep.write(tmp_path / "run", document)
    assert not (tmp_path / "run" / "inputs" / "trap_sweep.json").exists()


def test_existing_sweep_is_replaced_only_on_request(tmp_path):
    run = tmp_path / "run"
    trap_sweep.write(run, {"verdicts": clean_verdicts()})
    with pytest.raises(FileExistsError):
        trap_sweep.write(run, {"verdicts": clean_verdicts()})
    hit = {"evidence": "soft leptons from a compressed spectrum", "consequence": "ISR treatment declared",
           "flag_number": 4}
    trap_sweep.write(run, {"verdicts": clean_verdicts(T6=hit)}, replace=True)
    assert trap_sweep.validate(run)["traps_hit"] == ["T6"]


def test_validate_reports_validator_failures_and_undischarged_obligations(tmp_path):
    run = tmp_path / "run"
    hit = {"evidence": "groomed-jet substructure selection", "consequence": "published tagger efficiency",
           "flag_number": 5}
    trap_sweep.write(run, {"verdicts": clean_verdicts(T10=hit)})
    report = trap_sweep.validate(run)
    assert report["status"] == "PASS" and report["undischarged"] == ["T10"]
    assert trap_sweep.validate(run, require_discharged=True)["status"] == "FAIL"
    path = run / "inputs" / "trap_sweep.json"
    doc = json.loads(path.read_text())
    doc["verdicts"] = [v for v in doc["verdicts"] if v["id"] != "T10"]
    path.write_text(json.dumps(doc))
    assert trap_sweep.validate(run)["status"] == "FAIL"


def test_validate_reports_missing_file(tmp_path):
    report = trap_sweep.validate(tmp_path)
    assert report["status"] == "FAIL"


def test_command_line_write_and_validate(tmp_path):
    run = tmp_path / "run"
    source = write_input(tmp_path, {"verdicts": clean_verdicts()})
    src = Path(trap_sweep.__file__).resolve().parents[2]
    env = {"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}
    wrote = subprocess.run([sys.executable, "-m", "ravel.workflow.trap_sweep", "write", "--rundir", str(run),
                            "--input", str(source)], capture_output=True, text=True, env=env, timeout=60)
    assert wrote.returncode == 0, wrote.stderr
    checked = subprocess.run([sys.executable, "-m", "ravel.workflow.trap_sweep", "validate", "--rundir", str(run),
                              "--json"], capture_output=True, text=True, env=env, timeout=60)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["status"] == "PASS"
    again = subprocess.run([sys.executable, "-m", "ravel.workflow.trap_sweep", "write", "--rundir", str(run),
                            "--input", str(source)], capture_output=True, text=True, env=env, timeout=60)
    assert again.returncode == 2 and "exists" in again.stderr
