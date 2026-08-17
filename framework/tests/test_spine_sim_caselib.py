# framework/tests/test_spine_sim_caselib.py
"""framework/spine_sim/_case_lib.py -- the shared spine_sim case toolkit (Task 6.2).

Tested against REAL, already-on-disk infra only (validate_run_state.py + the existing card-guard
hook), so it is green with zero dependence on the unbuilt enforcement phases. Import by file path;
run from /tmp (py.py shadow).
"""
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CASELIB = REPO / "framework" / "spine_sim" / "_case_lib.py"


def _load():
    spec = importlib.util.spec_from_file_location("case_lib_uut", CASELIB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_write_contract_is_validate_task_contract_valid():
    L = _load()
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_x")
        c = L.write_contract(rd, task_mode="scan", stat_mode="best-sr-counting",
                             compute_plan="scan", detector_mode="simpleanalysis-delphes-native")
        assert os.path.isfile(os.path.join(rd, "inputs", "task_contract.json"))
        assert c["task_mode"] == "scan"
        res, rc = L.run_validate(rd)   # scan.json missing etc -> some FAILs, but JSON parses
        assert "invariants" in res and "stages" in res


def test_invariant_status_locates_a_named_invariant():
    L = _load()
    with L.tempdir() as td:
        # a scan with scan.json but NO resource_census -> the census invariant is a known FAIL
        rd = os.path.join(td, "2026-07-09_census")
        L.write_contract(rd, task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
                         detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "scan.json", {"schema_version": 1, "n_planned": 1, "n_done": 1,
                                       "n_missing": 0, "points": [{"tag": "p1"}], "missing_tags": []})
        res, rc = L.run_validate(rd)
        assert L.invariant_status(res, "resource-census-before-route") in ("FAIL", "waived-legacy") \
            or L.stage_status(res, "resource_census") == "FAIL"


def test_drive_hook_blocks_on_the_real_card_guard():
    L = _load()
    # the existing PreToolUse card-guard: a stdin naming a pristine card must exit 2
    stdin = {"tool_name": "Edit", "tool_input": {
        "file_path": "$DSRLAB_ROOT/proc_card.dat"}}
    cp = L.drive_hook(".claude/hooks/protect-original-cards.sh", stdin)
    assert cp.returncode == 2 and cp.stderr.strip()


def test_gate_fired_and_case_main_exit_discipline():
    L = _load()

    @L.case_main
    def _pass():
        L.gate_fired(True, "ok")

    @L.case_main
    def _fail():
        L.gate_fired(False, "nope")

    @L.case_main
    def _setup():
        raise L.CaseSetupError("missing tool")

    assert _pass() == 0
    assert _fail() == 1
    assert _setup() == 2


def test_tool_path_raises_setup_error_for_absent_tool():
    L = _load()
    try:
        L.tool_path("definitely_not_a_real_tool_xyz.py")
        assert False, "expected CaseSetupError"
    except L.CaseSetupError:
        pass
