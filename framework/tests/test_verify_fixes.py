"""framework/verify_fixes.py — the ONE aggregated `verify:` board for the audit-and-fix CRs
(Task 9, the hybrid verification layer). Smoke-tests only: the parser finds the real CRs, and the
PASS/FAIL aggregation + informational-marker handling behave correctly against fabricated fixtures
(never against the real CHANGES-REGISTRY.md, so this file stays fast and does not re-run the real
audit-and-fix commands already exercised by their own test files).

Import the module under test by file path (not by package import): the repo root carries a
`py.py` file that shadows the `py` package pytest depends on if the repo root ends up on
sys.path — hence this file is meant to be run from OUTSIDE the repo:
    cd /tmp && python3 -m pytest <this file's abspath> -q
and does not itself insert the repo root onto sys.path.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERIFY_FIXES_PY = REPO / "framework" / "verify_fixes.py"
REAL_REGISTRY = REPO / "framework" / "CHANGES-REGISTRY.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_fixes_under_test", VERIFY_FIXES_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_registry(tmp_path, body):
    p = tmp_path / "CHANGES-REGISTRY.md"
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# Parser, against the REAL registry (text only, nothing executed)
# ---------------------------------------------------------------------------

def test_real_registry_carries_at_least_14_verify_entries():
    mod = _load_module()
    entries = mod.parse_verify_entries(REAL_REGISTRY.read_text())
    assert len(entries) >= 14, sorted(entries)
    for cr_id in entries:
        assert cr_id in mod.CR_RANGE, cr_id


def test_real_registry_entries_cover_cr030_through_cr043():
    mod = _load_module()
    entries = mod.parse_verify_entries(REAL_REGISTRY.read_text())
    missing = [cr for cr in mod.CR_RANGE if cr not in entries]
    assert not missing, f"CR(s) with no `- **Verify:**` line: {missing}"


# ---------------------------------------------------------------------------
# Parser + runner, against FABRICATED fixtures (fast, deterministic)
# ---------------------------------------------------------------------------

FIXTURE_ALL_PASS = """\
# CHANGES REGISTRY (fixture)

### CR-030 — fabricated passing entry
- **Status:** EMBEDDED (fixture).
- **Verify:** `python3 -c "import sys; sys.exit(0)"`

### CR-031 — fabricated passing entry two
- **Status:** EMBEDDED (fixture).
- **Verify:** `python3 -c "print('ok')"`

## Some other section (must not be parsed as a CR)
### CR-999 — out of the tracked CR-030..043 range
- **Verify:** `python3 -c "import sys; sys.exit(1)"`
"""

FIXTURE_ONE_FAILING = """\
# CHANGES REGISTRY (fixture)

### CR-030 — fabricated passing entry
- **Status:** EMBEDDED (fixture).
- **Verify:** `python3 -c "import sys; sys.exit(0)"`

### CR-032 — fabricated FAILING entry
- **Status:** EMBEDDED (fixture).
- **Verify:** `python3 -c "import sys; sys.exit(1)"`
"""

FIXTURE_DECISION_MARKER = """\
### CR-043 — fabricated decision-only entry
- **Status:** EMBEDDED (fixture).
- **Verify:** `(decision — no artifact; fabricated for the test)`
"""

FIXTURE_DEFERRED_MARKER = """\
### CR-033 — fabricated deferred-only entry
- **Status:** DEFERRED (fixture).
- **Verify:** `(deferred — build not landed yet, fabricated for the test)`
"""


def test_out_of_range_cr_ids_are_ignored():
    mod = _load_module()
    entries = mod.parse_verify_entries(FIXTURE_ALL_PASS)
    assert "CR-999" not in entries
    assert set(entries) == {"CR-030", "CR-031"}


def test_board_all_pass_exits_0(tmp_path, capsys):
    mod = _load_module()
    registry = _write_registry(tmp_path, FIXTURE_ALL_PASS)
    rc = mod.main(["--registry", str(registry)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2 PASS / 0 FAIL" in out


def test_fabricated_failing_verify_makes_board_exit_1(tmp_path, capsys):
    mod = _load_module()
    registry = _write_registry(tmp_path, FIXTURE_ONE_FAILING)
    rc = mod.main(["--registry", str(registry)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "CR-032" in out
    assert "FAIL" in out
    assert "1 PASS / 1 FAIL" in out


def test_decision_marker_is_informational_pass_and_never_executed(tmp_path, monkeypatch):
    mod = _load_module()

    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called for a `(decision...)` marker")

    monkeypatch.setattr(mod.subprocess, "run", _boom)
    result = mod.run_verify("CR-043", "(decision — no artifact; fabricated for the test)")
    assert result["status"] == "PASS"
    assert result["informational"] is True


def test_deferred_marker_is_also_informational_pass(tmp_path):
    mod = _load_module()
    result = mod.run_verify("CR-033", "(deferred — build not landed yet, fabricated for the test)")
    assert result["status"] == "PASS"
    assert result["informational"] is True


def test_json_output_is_valid_and_matches_text_verdict(tmp_path, capsys):
    import json
    mod = _load_module()
    registry = _write_registry(tmp_path, FIXTURE_ONE_FAILING)
    rc = mod.main(["--registry", str(registry), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 1
    assert payload["all_pass"] is False
    statuses = {r["cr"]: r["status"] for r in payload["results"]}
    assert statuses == {"CR-030": "PASS", "CR-032": "FAIL"}


def test_missing_registry_file_is_a_clean_error_not_a_crash(tmp_path):
    mod = _load_module()
    rc = mod.main(["--registry", str(tmp_path / "does-not-exist.md")])
    assert rc == 1


# ---------------------------------------------------------------------------
# One real, FAST end-to-end subprocess execution (proves the runner actually
# shells out and honors cwd=repo-root, without paying for the slow CRs).
# ---------------------------------------------------------------------------

def test_real_command_executes_via_subprocess_from_repo_root(tmp_path):
    mod = _load_module()
    # validate_task_contract.py --selftest is fast (<2s) and repo-root-relative, exactly the
    # calling convention verify_fixes.py uses for every real CR verify command.
    result = mod.run_verify(
        "CR-034", "python3 trial-runs/_infrastructure/validate_task_contract.py --selftest")
    assert result["status"] == "PASS", result
    assert result["returncode"] == 0


def test_cli_smoke_via_subprocess(tmp_path):
    """One real subprocess invocation of the CLI itself (not just _load_module()), against a
    fabricated registry, confirms argv parsing + exit code plumbing end to end."""
    registry = _write_registry(tmp_path, FIXTURE_ALL_PASS)
    result = subprocess.run(
        [sys.executable, str(VERIFY_FIXES_PY), "--registry", str(registry)],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 PASS / 0 FAIL" in result.stdout
