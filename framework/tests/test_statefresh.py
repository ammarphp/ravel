"""The `statefresh` guard (Task 2B): the upgraded `check_agent_surface.py` readiness check.

Prose in the guarded current-claim files (STATUS.md, README.md, KNOWN-LIMITATIONS.md, CLAUDE.md,
DIRECTORY.md, PRODUCT-CONTRACT.md, the step-4/effmap/projection-replane/decision-shape-fit docs)
must reconcile to `framework/capability-matrix.json`: (1) the gen_status.py generated blocks are
fresh, (2) served/partial/unbuilt counts + readiness% + R9 status/score quoted in prose equal the
matrix-derived truth, (3) no forbidden stale-claim phrasing survives once its matrix guard flips.

The CRITICAL requirement (a gate that cries wolf on history gets disabled) is that legitimate
DATED HISTORY — session-log entries, dated bullets, `(historical)`/SUPERSEDED/`kept for the
record` lines, and the gen_status.py `<!-- CAPABILITY-STATUS:*:BEGIN/END -->` marker blocks
themselves — is never flagged. These tests prove both directions.

Import the module under test by file path (not by package import): `check_agent_surface.py`
lives in `trial-runs/_infrastructure/`, and the repo root carries a `py.py` file that shadows
the `py` package pytest can depend on if the repo root ends up on sys.path — hence this file is
meant to be run from OUTSIDE the repo (`cd /tmp && python3 -m pytest <this file's abspath> -q`),
and does not itself insert the repo root onto sys.path.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAS_PATH = REPO / "trial-runs" / "_infrastructure" / "check_agent_surface.py"


def _load_cas():
    spec = importlib.util.spec_from_file_location("check_agent_surface_under_test", CAS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_clean_repo_passes():
    """The live repo (post Task-2A reconciliation) must pass the whole gate, statefresh incl."""
    result = subprocess.run([sys.executable, str(CAS_PATH)], cwd=REPO,
                             capture_output=True, text=True)
    assert result.returncode == 0, (
        "check_agent_surface.py must exit 0 on the clean live repo:\n"
        + result.stdout + result.stderr)
    assert "[FAIL] statefresh" not in result.stdout, result.stdout


def test_catches_stale_claim(tmp_path):
    """An injected stale current-claim line (shape-fit still 'paradigm-blocked') must FAIL and
    the failure must name the offending line — P4/G2b are BUILT in the live matrix, so the old
    blanket-refusal claim is now a contradiction."""
    cas = _load_cas()
    truths = cas._matrix_truths(str(REPO))
    assert truths is not None, "matrix truths must be computable against the live repo"

    guarded_file = tmp_path / "framework" / "KNOWN-LIMITATIONS.md"
    guarded_file.parent.mkdir(parents=True)
    stale_line = ("shape/template fits are paradigm-blocked; binned shape fits remain "
                  "Phase-2 scope.")
    guarded_file.write_text(
        "# Known limitations\n\n"
        "## Physics fidelity\n"
        f"- {stale_line}\n")

    errs = cas.check_statefresh_contradictions(str(tmp_path), truths)
    assert errs, "statefresh must FAIL on an injected stale shape-fit-blocked claim"
    assert any("paradigm-blocked" in e for e in errs), (
        f"the FAIL must name the injected line; got: {errs}")


def test_history_line_not_flagged(tmp_path):
    """A DATED bullet quoting an old readiness%/R9/count AND an old paradigm-blocked mention
    must NOT be flagged by either Part 2 (counts) or Part 3 (contradictions) — proves the
    dated-bullet history exemption, the exact failure mode that would get the gate disabled."""
    cas = _load_cas()
    truths = cas._matrix_truths(str(REPO))
    assert truths is not None

    guarded_file = tmp_path / "framework" / "KNOWN-LIMITATIONS.md"
    guarded_file.parent.mkdir(parents=True)
    guarded_file.write_text(
        "# Known limitations\n\n"
        "## History\n"
        "- **2026-06-11** readiness · 96%; shape/template-fit remains paradigm-blocked; "
        "demand board 1/7 prompts fully served, 6 partial, 1 unbuilt; R9 WARN 0.50.\n")

    count_errs = cas.check_statefresh_counts(str(tmp_path), truths)
    contra_errs = cas.check_statefresh_contradictions(str(tmp_path), truths)
    assert count_errs == [], f"a dated-bullet history line must be exempt (counts); got: {count_errs}"
    assert contra_errs == [], (
        f"a dated-bullet history line must be exempt (contradictions); got: {contra_errs}")
