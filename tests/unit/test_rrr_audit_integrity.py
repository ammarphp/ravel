"""A retained diagnosis must remain bound to its complete evidence population."""
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_rrr_audits", ROOT / "scripts/check_rrr_audits.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
AUDIT = Path("evidence/audits/2026-09-05-rrr-diagnosis")


def test_retained_diagnosis_is_current():
    assert CHECKER.check() == []


def test_changed_residual_is_rejected(tmp_path):
    shutil.copytree(ROOT / AUDIT, tmp_path / AUDIT)
    report = tmp_path / AUDIT / "diagnosis.json"
    report.write_text(report.read_text().replace('"residual":', '"altered_residual":', 1))
    assert "RRR audit output changed: diagnosis.json" in CHECKER.check(tmp_path)


def test_missing_snapshot_is_rejected(tmp_path):
    shutil.copytree(ROOT / AUDIT, tmp_path / AUDIT)
    (tmp_path / AUDIT / "retained-inputs.json").unlink()
    assert any("retained-inputs.json" in error for error in CHECKER.check(tmp_path))


def test_changed_diagnostic_algorithm_requires_refresh(tmp_path):
    shutil.copytree(ROOT / AUDIT, tmp_path / AUDIT)
    script = tmp_path / AUDIT / "diagnose.py"
    script.write_text(script.read_text() + "\n# changed\n")
    assert any("diagnostic code changed" in error for error in CHECKER.check(tmp_path))


def test_manifest_cannot_hide_changed_output_by_omitting_it(tmp_path):
    shutil.copytree(ROOT / AUDIT, tmp_path / AUDIT)
    path = tmp_path / AUDIT / "provenance.json"
    provenance = json.loads(path.read_text())
    del provenance["outputs"]["points.csv"]
    path.write_text(json.dumps(provenance))
    (tmp_path / AUDIT / "points.csv").write_text("invalid,changed,data\n")
    assert any("output inventory" in error for error in CHECKER.check(tmp_path))


def test_contradictory_snapshot_identity_is_rejected(tmp_path):
    shutil.copytree(ROOT / AUDIT, tmp_path / AUDIT)
    path = tmp_path / AUDIT / "provenance.json"
    provenance = json.loads(path.read_text())
    provenance["source_snapshot_sha256"] = "0" * 64
    path.write_text(json.dumps(provenance))
    assert any("snapshot digest" in error for error in CHECKER.check(tmp_path))
