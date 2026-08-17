import json, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "trial-runs/_infrastructure/resource_census.py"

def test_resource_census_selftest_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_recipe_search_bad_mode_exits_2():
    r = subprocess.run([sys.executable, str(SCRIPT), "--debug", "not-a-mode",
                        "--tool", "madgraph", "--model", "SVJ"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr

def test_recipe_search_offline_record_assembly(tmp_path):
    # build_recipe_search_record is pure/offline: import by file path and check the schema.
    import importlib.util
    spec = importlib.util.spec_from_file_location("rc", SCRIPT)
    rc = importlib.util.module_from_spec(spec); spec.loader.exec_module(rc)
    searches = {"github": {"status": "OK", "hits": {"t1": {"repos": [1, 2], "code": [3]}}},
                "inspire": {"status": "ERROR", "reason": "offline"}}
    rec = rc.build_recipe_search_record("madgraph", "SVJ", "undecayed empty SR", searches)
    assert rec["mode"] == "recipe-search" and rec["n_hits"] == 3
    assert rec["searches_ok"] == ["github"] and rec["co_primary"] is True
    assert rec["generated_by"] == "resource_census.py --debug recipe-search"
    assert rec["input_fingerprint"] == rc._fingerprint("madgraph", "SVJ", "undecayed empty SR")

def test_assert_recipe_search_close_block(tmp_path):
    import os
    rd = tmp_path / "2026-07-09_svj"
    (rd / "logs").mkdir(parents=True)
    (rd / "logs" / "madgraph.failure.json").write_text(
        json.dumps({"stage": "madgraph", "failure_class": "tool_generator_model"}))
    (rd / "run_state.json").write_text(
        json.dumps({"open_failure_records": ["logs/madgraph.failure.json"]}))
    blocked = subprocess.run([sys.executable, str(SCRIPT), "--assert-recipe-search",
                              "--rundir", str(rd)], cwd=REPO, capture_output=True, text=True)
    assert blocked.returncode == 1, blocked.stdout + blocked.stderr
    (rd / "inputs").mkdir()
    (rd / "inputs" / "recipe_search.json").write_text(
        json.dumps({"schema_version": 1, "mode": "recipe-search"}))
    opened = subprocess.run([sys.executable, str(SCRIPT), "--assert-recipe-search",
                             "--rundir", str(rd)], cwd=REPO, capture_output=True, text=True)
    assert opened.returncode == 0, opened.stdout + opened.stderr

def test_recipe_search_stop_branch(tmp_path):
    # D-4/G8: the branch THIS task registers in stop_dispatch.py must BLOCK (exit 2 + token) a turn-end
    # left with an OPEN generator-model failure and no recipe_search.json, and clear once it is present.
    STOP = REPO / "trial-runs/_infrastructure/stop_dispatch.py"
    rd = tmp_path / "2026-07-09_svj"
    (rd / "logs").mkdir(parents=True)
    (rd / "logs" / "madgraph.failure.json").write_text(
        json.dumps({"stage": "madgraph", "failure_class": "tool_generator_model"}))
    (rd / "run_state.json").write_text(json.dumps(
        {"session_id": "T", "open_failure_records": ["logs/madgraph.failure.json"]}))
    blocked = subprocess.run([sys.executable, str(STOP), "--rundir", str(rd),
                              "--last-message", "Here is the results deck.",
                              "--branch", "recipe-search"], cwd=REPO, capture_output=True, text=True)
    assert blocked.returncode == 2 and "G8-RECIPE-SEARCH" in blocked.stderr, blocked.stdout + blocked.stderr
    (rd / "inputs").mkdir()
    (rd / "inputs" / "recipe_search.json").write_text(
        json.dumps({"schema_version": 1, "mode": "recipe-search"}))
    allowed = subprocess.run([sys.executable, str(STOP), "--rundir", str(rd),
                              "--last-message", "Here is the results deck.",
                              "--branch", "recipe-search"], cwd=REPO, capture_output=True, text=True)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr

def test_assert_pre_generate(tmp_path):
    rd = tmp_path / "2026-07-09_svj"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(
        json.dumps({"targets": {"model": "SVJ (dark quark)"}}))
    blocked = subprocess.run([sys.executable, str(SCRIPT), "--assert-pre-generate",
                              "--rundir", str(rd)], cwd=REPO, capture_output=True, text=True)
    assert blocked.returncode == 1, blocked.stdout + blocked.stderr
    (rd / "inputs" / "generation_recipe.json").write_text(
        json.dumps({"model": "SVJ", "process": "p p > ..."}))
    allowed = subprocess.run([sys.executable, str(SCRIPT), "--assert-pre-generate",
                              "--rundir", str(rd)], cwd=REPO, capture_output=True, text=True)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr

def test_assert_pre_generate_no_model_passes(tmp_path):
    rd = tmp_path / "2026-07-09_nomodel"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps({"targets": {"model": None}}))
    r = subprocess.run([sys.executable, str(SCRIPT), "--assert-pre-generate", "--rundir", str(rd)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_gen_launch_re_matches_cmnd_and_madevent():
    """A4: the trial's bespoke .cmnd-driven shower + a raw madevent call must trip the guard."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("resource_census_under_test_a4", SCRIPT)
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    assert rc.GEN_LAUNCH_RE.search("nohup pythia8-run hv_shower.cmnd &")
    assert rc.GEN_LAUNCH_RE.search("cd proc && ./bin/madevent run")
