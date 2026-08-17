# framework/tests/test_precommit_hook.py
import os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "trial-runs/_infrastructure/install_git_hooks.sh"
CENSUS = REPO / "trial-runs/_infrastructure/check_agent_surface.py"

def _hooks_dir():
    out = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=REPO,
                         capture_output=True, text=True).stdout.strip()
    return (REPO / out) if not os.path.isabs(out) else Path(out)

def test_installer_creates_executable_hook():
    subprocess.run(["bash", str(INSTALLER)], cwd=REPO, capture_output=True, text=True, check=True)
    hook = _hooks_dir() / "pre-commit"
    assert hook.is_file(), "pre-commit hook not installed"
    assert os.access(hook, os.X_OK), "pre-commit hook not executable"
    assert "check_agent_surface.py" in hook.read_text()

def test_hook_propagates_check_agent_surface_exit():
    subprocess.run(["bash", str(INSTALLER)], cwd=REPO, capture_output=True, text=True, check=True)
    hook = _hooks_dir() / "pre-commit"
    direct = subprocess.run([sys.executable, str(CENSUS)], cwd=REPO, capture_output=True, text=True)
    viahook = subprocess.run(["bash", str(hook)], cwd=REPO, capture_output=True, text=True)
    assert viahook.returncode == direct.returncode, (
        f"hook rc={viahook.returncode} != check_agent_surface rc={direct.returncode}")
