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
    # the reconciled records leave the whole surface GREEN -- the G20 baseline the
    # adversarial G20 case perturbs.
    r = subprocess.run(
        [sys.executable, "src/ravel/validation/check_agent_surface.py"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    assert r.returncode == 0, f"check_agent_surface FAIL (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"


def test_dirmap_flags_dangling_row_the_g20_trigger(tmp_path):
    # G20 FIRES: an incomplete doc/dir reconcile (a DIRECTORY row pointing at a file not on disk)
    # produces a dirmap error -> the pre-commit hook blocks. This proves the seed
    # adversarial G20 case uses.
    cas = _load_check_agent_surface()
    # A map describes the actual tree, so a dangling row is a hard error in every tree.
    (tmp_path / "DIRECTORY.md").write_text(
        "## Repository root\n"
        "| Path | Track | Purpose |\n"
        "|---|---|---|\n"
        "| `ghost_gate_tool_xyz.py` | meta | a reconcile that never landed on disk |\n",
        encoding="utf-8",
    )
    errs, warns = cas.check_dirmap(str(tmp_path))
    assert any("not on disk" in e for e in errs), f"dirmap did not flag the dangling row: {errs}"
    assert not any("undistributed" in w for w in warns)


def test_empty_public_checkout_accepts_run_patterns_but_not_missing_guide(tmp_path):
    checker = _load_check_agent_surface()
    doc = tmp_path / "README.md"
    doc.write_text("Artifacts use `trial-runs/*/inputs/task_contract.json`. "
                   "Read `trial-runs/README.md`.\n")
    errors = checker.check_refs(str(tmp_path), [str(doc)], "dev")
    assert len(errors) == 1
    assert "trial-runs/README.md" in errors[0]
