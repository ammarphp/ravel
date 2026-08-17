# framework/tests/test_green_board.py
"""framework/green_board.py -- the aggregate make-green board (Task 6.7). Fabricated-rung fixtures
(never the slow real stack) prove aggregation + informational handling + exit code; one real fast
subprocess proves cwd=repo plumbing. Import by file path; run from /tmp.
"""
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GB = REPO / "framework" / "green_board.py"


def _load():
    spec = importlib.util.spec_from_file_location("green_board_uut", GB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rungs(path, body):
    p = path / "rungs.json"
    p.write_text(json.dumps(body))
    return p


def test_all_pass_exits_0(tmp_path, capsys):
    mod = _load()
    rj = _rungs(tmp_path, [["ok1", "python3 -c \"import sys; sys.exit(0)\"", False],
                           ["ok2", "python3 -c \"print('hi')\"", False]])
    rc = mod.main(["--rungs-json", str(rj)])
    out = capsys.readouterr().out
    assert rc == 0 and "2 PASS / 0 FAIL" in out


def test_one_failing_rung_exits_1(tmp_path, capsys):
    mod = _load()
    rj = _rungs(tmp_path, [["ok", "python3 -c \"import sys; sys.exit(0)\"", False],
                           ["bad", "python3 -c \"import sys; sys.exit(1)\"", False]])
    rc = mod.main(["--rungs-json", str(rj)])
    out = capsys.readouterr().out
    assert rc == 1 and "bad" in out


def test_informational_rung_never_fails_the_board(tmp_path, capsys):
    mod = _load()
    rj = _rungs(tmp_path, [["ok", "python3 -c \"import sys; sys.exit(0)\"", False],
                           ["audit", "python3 -c \"import sys; sys.exit(3)\"", True]])
    rc = mod.main(["--rungs-json", str(rj)])
    out = capsys.readouterr().out
    assert rc == 0                      # informational rung's nonzero does not sink the board
    assert "audit" in out


def test_default_rungs_include_the_four_stack_members():
    mod = _load()
    names = {r[0] for r in mod.RUNGS}
    # The REAL as-built L6 spine checks: the per-gate harness, the agent-surface coherence gate, the
    # lifecycle/invariant selftest, and the informational audit. (The legacy CR-030..043 verify_fixes
    # board is intentionally not a rung -- see green_board.py docstring.)
    assert {"spine_sim", "validate_run_state", "audit", "check_agent_surface"} <= names


def test_real_fast_rung_executes_from_repo_root(tmp_path, capsys):
    mod = _load()
    rj = _rungs(tmp_path, [["contract",
                            "python3 trial-runs/_infrastructure/validate_task_contract.py --selftest",
                            False]])
    rc = mod.main(["--rungs-json", str(rj)])
    out = capsys.readouterr().out
    assert rc == 0, out
