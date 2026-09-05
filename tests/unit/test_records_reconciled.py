import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_check_agent_surface():
    path = REPO / "src" / "ravel" / "validation" / "check_agent_surface.py"
    spec = importlib.util.spec_from_file_location("check_agent_surface_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_surface_green():
    # the reconciled records (7.1-7.4) leave the whole surface GREEN -- the G20 baseline the
    # spine_sim G20 case perturbs.
    r = subprocess.run(
        [sys.executable, "src/ravel/validation/check_agent_surface.py"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    assert r.returncode == 0, f"check_agent_surface FAIL (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"


def test_dirmap_flags_dangling_row_the_g20_trigger(tmp_path):
    # G20 FIRES: an incomplete doc/dir reconcile (a DIRECTORY row pointing at a file not on disk)
    # produces a dirmap error -> the pre-commit hook (Phase 4b) blocks. This proves the seed
    # spine_sim's G20 case uses.
    cas = _load_check_agent_surface()
    # The fixture simulates the DEV repo, where dangling rows are hard errors -- so it must
    # carry the dev sentinel (ORCHESTRATION.md). In DISTRIBUTION trees (no sentinel) dirmap
    # deliberately downgrades dev-only rows to WARN (2026-07-30 export policy).
    (tmp_path / "ORCHESTRATION.md").write_text("dev sentinel\n", encoding="utf-8")
    (tmp_path / "DIRECTORY.md").write_text(
        "## Repository root\n"
        "| Path | Track | Purpose |\n"
        "|---|---|---|\n"
        "| `ghost_spine_tool_xyz.py` | meta | a reconcile that never landed on disk |\n",
        encoding="utf-8",
    )
    errs, warns = cas.check_dirmap(str(tmp_path))
    assert any("not on disk" in e for e in errs), f"dirmap did not flag the dangling row: {errs}"
    # Public maps now describe the actual selected tree, so omissions fail there too.
    (tmp_path / "ORCHESTRATION.md").unlink()
    errs2, warns2 = cas.check_dirmap(str(tmp_path))
    assert any("not on disk" in e for e in errs2)
    assert not any("dev-only" in w for w in warns2)


def test_empty_public_checkout_accepts_run_patterns_but_not_missing_guide(tmp_path):
    checker = _load_check_agent_surface()
    doc = tmp_path / "README.md"
    doc.write_text("Artifacts use `trial-runs/*/inputs/task_contract.json`. "
                   "Read `trial-runs/README.md`.\n")
    errors = checker.check_refs(str(tmp_path), [str(doc)], "dev")
    assert len(errors) == 1
    assert "trial-runs/README.md" in errors[0]
