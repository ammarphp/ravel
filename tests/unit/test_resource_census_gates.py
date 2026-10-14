import json, subprocess, sys
import pytest
from ravel.workflow import resource_census as rc
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/workflow/resource_census.py"

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
    # G8: the recipe-search branch of stop_dispatch.py must BLOCK (exit 2 + token) a turn-end
    # left with an OPEN generator-model failure and no recipe_search.json, and clear once it is present.
    STOP = REPO / "src/ravel/workflow/stop_dispatch.py"
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
    """A bespoke .cmnd-driven shower + a raw madevent call must trip the guard."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("resource_census_under_test_a4", SCRIPT)
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    assert rc.GEN_LAUNCH_RE.search("nohup pythia8-run hv_shower.cmnd &")
    assert rc.GEN_LAUNCH_RE.search("cd proc && ./bin/madevent run")


@pytest.mark.parametrize("command", [
    "ravel run --rundir trial-runs/x",
    "ravel partitions run --rundir r --stage s --spec p.json --workdir w",
    "ravel backend launch --rundir r --stage s --launcher l.json --workdir w --execute -- tool",
    "python -m ravel.workflow.partitioned_execution run --spec p.json --workdir w",
    "python -m ravel.workflow.execution_backend launch --launcher l.json --workdir w -- tool",
])
def test_generation_launch_pattern_matches_ravel_launch_forms(command):
    assert rc.GEN_LAUNCH_RE.search(command)


@pytest.mark.parametrize("command", ["ravel runs", "ravel partitions plan --spec p.json",
                                     "ravel backend launcher --out l.json", "ravel run-stage"])
def test_generation_launch_pattern_ignores_non_launch_forms(command):
    assert not rc.GEN_LAUNCH_RE.search(command)


@pytest.mark.parametrize("command", [
    "python -m ravel.cli run --rundir r",
    "python3 -m ravel run --rundir r",
    "'ravel' 'run' --rundir r",
    "\"ravel\" run --rundir r",
    "python -m ravel.workflow.stage_supervisor --stage s --rundir r --log logs/s.log --backend-plan p.json",
    "python -m ravel.workflow.execution_backend worker --rundir r --stage s --plan p.json",
    "python -m ravel.workflow.backends.native launch --job j -- tool",
    "python -c 'from ravel.physics import backend_driver; backend_driver.drive_stage(spec, store)'",
])
def test_generation_launch_pattern_matches_equivalent_launch_spellings(command):
    assert rc.is_generation_launch(command)


def test_the_launch_hook_finds_the_run_from_rundir_without_a_trial_runs_path(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/task_contract.json").write_text("{}")
    command = f"python -m ravel.cli run --rundir {tmp_path}"
    assert rc._resolve_rundir_from_command(command, str(tmp_path)) == str(tmp_path)


@pytest.mark.parametrize("command", [
    "python -c 'from ravel.physics.backend_driver import drive as d; d(spec, a, b)'",
    "python3 -c 'import ravel.physics.backend_driver as bd; bd.drive(spec, a, b)'",
    "python -c 'from ravel.workflow import execution_backend as x; x.submit(plan, a)'",
    "python -c 'from ravel.workflow.execution_backend import submit as s; s(plan, a)'",
    "python -c 'import importlib; m = importlib.import_module(\"ravel.workflow.execution_backend\"); m.submit(p, a)'",
    "python -c 'from ravel.workflow import partitioned_execution as p; p.run(spec, w, authority=a)'",
    "python -c 'from ravel.workflow import machine_lease as m; m.acquire(\"x\")'",
])
def test_generation_launch_pattern_matches_import_alias_spellings(command):
    assert rc.is_generation_launch(command)


@pytest.mark.parametrize("command", ["grep -rn backend_driver src", "python -m ravel.workflow.execution_backend describe --plan p.json"])
def test_generation_launch_pattern_ignores_reading_the_launch_modules(command):
    assert not rc.is_generation_launch(command)


def test_a_quoted_run_path_keeps_its_spaces(tmp_path):
    run = tmp_path / "trial-runs" / "a run with spaces"
    (run / "inputs").mkdir(parents=True)
    (run / "inputs/task_contract.json").write_text("{}")
    assert rc._resolve_rundir_from_command(f'ravel run --rundir "{run}"', str(tmp_path)) == str(run)
    assert rc._resolve_rundir_from_command(f"ravel run --rundir='{run}'", str(tmp_path)) == str(run)
    assert rc._resolve_rundir_from_command(f'mg5_aMC "{run}/proc/run.mg5"', str(tmp_path)) == str(run)


def test_a_study_run_without_a_task_contract_is_identified(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/science-plan.json").write_text("{}")
    assert rc._resolve_rundir_from_command(f"ravel run --rundir {tmp_path}", str(tmp_path)) == str(tmp_path)


def test_a_launch_whose_run_cannot_be_identified_is_refused(tmp_path, capsys):
    code = rc._pre_generate_hook_main(["--pre-generate-hook", "--command", "mg5_aMC proc/run.mg5",
                                       "--project-dir", str(tmp_path)])
    assert code == 2 and "--rundir" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["grep -rn generate_events src", "cat notes.txt | grep mg5_aMC",
                                     "git log -S madevent"])
def test_a_read_only_command_that_mentions_a_launch_is_not_refused(tmp_path, command):
    assert rc._pre_generate_hook_main(["--pre-generate-hook", "--command", command,
                                       "--project-dir", str(tmp_path)]) == 0


@pytest.mark.parametrize("command", ["cat /dev/null\nravel backend launch --execute -- true",
                                     "echo start\r\nmg5_aMC proc/run.mg5"])
def test_a_launch_on_a_later_line_after_a_read_only_command_is_refused(tmp_path, command):
    assert rc.launches(command)
    assert rc._pre_generate_hook_main(["--pre-generate-hook", "--command", command,
                                       "--project-dir", str(tmp_path)]) == 2
