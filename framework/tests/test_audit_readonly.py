"""framework/audit.py must be read-only by default (Task 1.1, write-suppression only).

audit.py used to write framework/AUDIT.md unconditionally as a side effect of running it —
so every verification/publish run dirtied a committed baseline. These tests pin the fix:
running audit.py with no flags computes + prints and writes NOTHING; `--write [--out PATH]`
is the opt-in that regenerates the report. This is NOT a diff-and-fail gate — content drift
is expected as the pipeline improves and is not asserted here.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT_PY = REPO / "framework" / "audit.py"
AUDIT_MD = REPO / "framework" / "AUDIT.md"


def test_check_writes_nothing():
    before = AUDIT_MD.read_bytes()
    result = subprocess.run([sys.executable, str(AUDIT_PY)], cwd=REPO,
                             capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    after = AUDIT_MD.read_bytes()
    assert after == before, "framework/audit.py (no args) must not modify framework/AUDIT.md"


def test_write_to_tmp(tmp_path):
    out = tmp_path / "AUDIT.md"
    result = subprocess.run(
        [sys.executable, str(AUDIT_PY), "--write", "--out", str(out)],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert out.exists(), "--write --out PATH must create PATH"
    text = out.read_text()
    assert "readiness" in text.lower()
    assert "R9" in text
