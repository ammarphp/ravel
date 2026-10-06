"""scripts/audit.py must be read-only by default (write-suppression only).

audit.py used to write its committed audit report unconditionally as a side effect of running it —
so every verification/publish run dirtied a committed baseline. These tests pin the fix:
running audit.py with no flags computes + prints and writes NOTHING; `--write [--out PATH]`
is the opt-in that regenerates the report. This is NOT a diff-and-fail gate — content drift
is expected as the pipeline improves and is not asserted here.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT_PY = REPO / "scripts" / "audit.py"
sys.path.insert(0, str(REPO / "src"))
from ravel.evidence_layout import source_settings  # noqa: E402

# The default --write targets: a report that an optional settings file names, if any, and the ignored
# local file. A read-only run must create or change neither.
_REPORT = source_settings(REPO).get("audit_report")
DEFAULT_OUTPUTS = ((REPO / _REPORT,) if _REPORT else ()) + (REPO / "local-runs" / "audit.md",)


def _snapshot():
    return [path.read_bytes() if path.exists() else None for path in DEFAULT_OUTPUTS]


def test_check_writes_nothing():
    before = _snapshot()
    result = subprocess.run([sys.executable, str(AUDIT_PY)], cwd=REPO,
                             capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    after = _snapshot()
    assert after == before, "scripts/audit.py (no args) must not write its report"


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
