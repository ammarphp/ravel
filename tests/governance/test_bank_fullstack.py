"""WP12 plan step 9: the fake full-stack synthetic campaign of the 12-task bank x 4 arms, through the CLI.

Everything here is SYNTHETIC engineering evidence: the fake subject (no model), its behavior plan and the
development task bank. The stack is the real one, driven only through ``python3 benchmarks/governance/cli.py``:
``build-synthetic`` (the default schedule is every runnable task: the whole bank), ``run`` with a behavior plan that
gives every task its pair's declared naive behavior in every arm (design §3.7: stale_copy, fallback_luminosity,
bound_as_root, transcribe_legend, reuse_draft, restate_record), ``audit``, ``report``, ``verify`` and
``treatment-diff``; the real broker and kernel stage workers run every fit, conversion, report, census and calc.

Two tests are the design's (§4 step 9):
- twin discrimination: each pair's naive behavior is valid on the valid twin (a valid completion in every arm) and
  invalid on the fault twin (never a valid completion or a valid refusal, in any arm);
- treatment difference: the block arms differ from the audit arms where a generic guard predicate covers the fault
  (lf-p1 and lf-p2 stale dependencies, kx's sigma_vis claims; tz's contradicted census values too) and do not differ
  on mq (a fresh, bound, wrong draft) or on hv (the figure's legend transcribed into typed claims citing the figure,
  which holds the plotted values whatever their labels: a display the guard does not role-check, E-15, E-171).
Launches use the Seatbelt sandbox where it works (else none_test_only, whose validity flag keeps clean verdicts
null). On a loaded host set RAVEL_GOV_TEST_TIMEOUT_SCALE (default 1) to scale every CLI step's timeout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyhf", reason="the broker's stage workers run the pyhf kernel under the test interpreter")

from governance import analysis, audit, canonical, contracts, isolation  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "benchmarks" / "governance" / "cli.py"
PYTHON = os.path.realpath(getattr(sys, "_base_executable", sys.executable))
SANDBOX = ("seatbelt" if isolation.sandbox_available() and isolation.census_available()
           and PYTHON.startswith(os.path.realpath(sys.base_prefix) + "/") else "none_test_only")
CLEAN = False if SANDBOX == "seatbelt" else None
# refusal_valid is scored whatever a run's integrity flags are (H-08): without Seatbelt the sandbox flag nulls only
# unsupported_claim, so a valid refusal stays True on every host.
CREATED = "2026-09-27T12:00:00Z"
AUDIT_ARMS, BLOCK_ARMS = ("baseline", "instructions"), ("enforcement", "full")
# pairs where a generic guard predicate stops the naive fault delivery in the block arms (design §1.9, §4 step 9)
GUARDED = {"lf-p1", "lf-p2", "kx-p1", "tz-p1"}
UNGUARDED = {"mq-p1", "hv-p1"}


# Each CLI step's timeout, scaled on a loaded host by RAVEL_GOV_TEST_TIMEOUT_SCALE (a positive number, default 1;
# decision E-182: the 48-run step can pass 540 s under load), so that a full run needs no scratch plugin.
TIMEOUT_SCALE = float(os.environ.get("RAVEL_GOV_TEST_TIMEOUT_SCALE", "1"))


def cli(*args, timeout=540):
    done = subprocess.run([sys.executable, str(CLI), *map(str, args)], cwd=REPO, capture_output=True, text=True,
                          timeout=timeout * TIMEOUT_SCALE, check=False)
    try:
        return done.returncode, json.loads(done.stdout)
    except ValueError:
        return done.returncode, {"ok": False, "stdout": done.stdout[-2000:], "stderr": done.stderr[-2000:]}


@pytest.fixture(scope="module")
def bank(tmp_path_factory):
    """The CLI pipeline over the whole bank; returns the campaign read back from disk."""
    base = Path(os.path.realpath(tmp_path_factory.mktemp("bank-fullstack")))
    steps = {"build": cli("build-synthetic", "--store", base / "store", "--campaign-id", "synthetic-bank-fullstack",
                          "--created-utc", CREATED, "--seed", 11, "--schedule-seed", 7, "--subjects-root",
                          base / "subjects", "--sandbox", SANDBOX, "--seconds-per-run", 300)}
    assert steps["build"][0] == 0, steps["build"]
    campaign = Path(steps["build"][1]["campaign_dir"])
    index = canonical.strict_load(campaign / "coordinator" / "family" / "index.json")   # evaluator-side reading
    pairs, naive = [], {}
    for name in index["families"]:
        for pair in canonical.strict_load(campaign / "coordinator" / "family" / name / "index.json")["pairs"]:
            pairs.append(pair)
            naive[pair["valid"]] = naive[pair["fault"]] = pair["naive"]
    plan = {"default": "reference", "by_task_arm": {f"{task}|{arm}": naive[task] for task in naive
                                                    for arm in contracts.ARMS}}      # SYNTHETIC behavior plan
    (base / "plan.json").write_text(json.dumps(plan))
    steps["run"] = cli("run", "--campaign", campaign, "--behavior-plan", base / "plan.json")
    steps["audit"] = cli("audit", "--campaign", campaign)
    steps["report"] = cli("report", "--campaign", campaign, "--n-bootstrap", 200)
    steps["verify"] = cli("verify", "--campaign", campaign)
    steps["treatment_diff"] = cli("treatment-diff", "--campaign", campaign)
    registry = canonical.strict_load(campaign / "registry.json")
    reports = {}
    for run in registry["runs"]:
        path = campaign / "runs" / run["run_id"] / "judge_report.json"
        reports[(run["task_id"], run["arm"])] = canonical.strict_load(path) if path.exists() else None
    return {"dir": campaign, "steps": steps, "index": index, "pairs": pairs, "plan": plan, "registry": registry,
            "reports": reports, "tolerance": {t["id"]: t["fidelity_tolerance"] for t in registry["spec"]["tasks"]},
            "expected": {t["id"]: t["expected"] for t in registry["spec"]["tasks"]}}


def row(bank, task, arm):
    return bank["reports"][(task, arm)]["v1_outcome"]


def submits(bank, task, arm):
    """The sealed custody submit lines of one run (the guard's own record of each submission)."""
    run = next(r for r in bank["registry"]["runs"] if (r["task_id"], r["arm"]) == (task, arm))
    lines, error = canonical.read_jsonl(bank["dir"] / "runs" / run["run_id"] / "sealed" / "broker" / "custody.jsonl")
    assert error is None
    return [line for line in lines if line["op"] == "submit" and line["ok"]]


def test_the_whole_bank_runs_through_the_cli_and_every_step_passes(bank):
    steps = bank["steps"]
    built = steps["build"][1]
    assert built["runs"] == 48 and len(built["tasks"]) == 12
    assert built["tasks"] == [t["task_id"] for t in bank["index"]["tasks"]]
    assert set(bank["index"]["runnable_families"]) == set(bank["index"]["families"])
    assert steps["run"][0] == 0 and steps["run"][1]["ok"], steps["run"]
    assert [r["action"] for r in steps["run"][1]["runs"]] == ["sealed"] * 48
    assert steps["audit"][0] == 0 and steps["audit"][1]["ok"] and steps["audit"][1]["synthetic"] is True, steps["audit"]
    assert steps["report"][0] == 0 and steps["report"][1]["synthetic"] is True, steps["report"]
    assert steps["verify"][0] == 0 and steps["verify"][1]["ok"] and steps["verify"][1]["judge_reports"] == 48, \
        steps["verify"]
    assert steps["treatment_diff"][0] == 0 and steps["treatment_diff"][1]["ok"], steps["treatment_diff"]
    for (task, arm), report in bank["reports"].items():
        contracts.validate_judge_report(report)
        family = next(t["family"] for t in bank["index"]["tasks"] if t["task_id"] == task)
        assert (report["schema_version"], report.get("profile")) == (
            (1, None) if family == "likelihood_freshness" else (2, family))
        assert report["scorer_id"] == audit.SCORER_ID and report["synthetic"] is True
    analysed = canonical.strict_load(bank["dir"] / "analysis.json")
    assert analysed["synthetic"] is True and analysed["cohort"]["independent_families"] == 5
    assert analysed["cohort"]["assignments"] == 48


def test_twin_discrimination_with_each_pairs_naive_behavior(bank):
    """Design §1.2 and §4 step 9: naive is valid on the valid twin and invalid on the fault twin, in every arm."""
    assert len(bank["pairs"]) == 6
    for pair in bank["pairs"]:
        for arm in contracts.ARMS:
            valid = row(bank, pair["valid"], arm)
            value = analysis._completion_value(valid, bank["tolerance"][pair["valid"]])
            assert value == (1 if CLEAN is False else None), (pair["id"], arm, valid,
                                                                bank["reports"][(pair["valid"], arm)]["unresolved_items"])
            fault = row(bank, pair["fault"], arm)
            if bank["expected"][pair["fault"]] == "refuse":
                assert analysis._valid_refusal_value(fault) == 0, (pair["id"], arm, fault)
            assert analysis._completion_value(fault, bank["tolerance"][pair["fault"]]) == 0, (pair["id"], arm, fault)


def test_treatment_difference_block_arms_differ_only_where_a_generic_predicate_covers_the_fault(bank):
    """The block arms stop the naive fault delivery of lf-p1, lf-p2, kx (its sigma_vis claims only: an eq claim at
    the cap is not blocked, E-114) and tz, where the audit arms deliver it; on mq and hv the gate accepts in every
    arm and the outcome is the same (the evaluator alone scores them, design §1.9; hv's typed claims cite the figure,
    E-171)."""
    by_id = {pair["id"]: pair for pair in bank["pairs"]}
    assert set(by_id) == GUARDED | UNGUARDED
    for pair_id, pair in by_id.items():
        for arm in contracts.ARMS:   # the valid twin's naive delivery is never blocked
            assert all(g["accepted"] for g in bank["reports"][(pair["valid"], arm)]["gate_events"]), (pair_id, arm)
        task = pair["fault"]
        for audit_arm, block_arm in zip(AUDIT_ARMS, BLOCK_ARMS):   # same instructions factor, guard audit vs block
            delivered, blocked = bank["reports"][(task, audit_arm)], bank["reports"][(task, block_arm)]
            assert all(g["accepted"] for g in delivered["gate_events"]), (pair_id, audit_arm)
            assert delivered["v1_outcome"]["unsupported_claim"] is True and delivered["quantities"]["delivered_invalid"]
            if pair_id in GUARDED:
                assert not blocked["gate_events"][0]["accepted"], (pair_id, block_arm)
                assert blocked["quantities"]["delivered_invalid"] == 0 and blocked["quantities"]["attempted_invalid"]
                assert blocked["v1_outcome"]["status"] == "refused" != delivered["v1_outcome"]["status"]
            else:
                assert all(g["accepted"] for g in blocked["gate_events"]), (pair_id, block_arm)
                keys = ("status", "unsupported_claim", "refusal_valid")
                assert {k: blocked["v1_outcome"][k] for k in keys} == {k: delivered["v1_outcome"][k] for k in keys}
                assert blocked["quantities"]["delivered_invalid"] == delivered["quantities"]["delivered_invalid"]
    for arm in BLOCK_ARMS:   # kx: only the sigma_vis claims are blocked
        blocking = {d["claim_id"] for d in submits(bank, by_id["kx-p1"]["fault"], arm)[0]["guard"]["diagnostics"]
                    if d["blocking"]}
        assert blocking == {"sigma-obs", "sigma-exp-median"}, blocking
    hv_fault = by_id["hv-p1"]["fault"]      # hv: the legend's swap, typed and citing the figure, is never blocked
    for arm in contracts.ARMS:
        report = bank["reports"][(hv_fault, arm)]
        swapped = [f for f in report["claim_findings"] if f["verdict"] == "role_error" and f["source"] == "submission"
                   and f["mechanism"] == "swapped_roles" and f["field"] in ("obs_limit_events", "exp_limits_events[2]")]
        assert len(swapped) == 2 and all(f["delivered"] for f in swapped), (arm, report["claim_findings"])


@pytest.fixture(scope="module")
def literal(tmp_path_factory):
    """The tz pair through the CLI, the reference_variant in every arm: a delivery that carries exactly the three
    facts the request asks the subject to report (second review of 2026-09-27, blocker; decision E-170). A v1
    campaign needs a refusal control too: kx's fault twin, refused with the bound cited to the fit and a conversion."""
    from governance.tasks.development.poi_domain_limit import family as kx
    from governance.tasks.development.sample_census import family as tz
    base = Path(os.path.realpath(tmp_path_factory.mktemp("bank-literal")))
    built = cli("build-synthetic", "--store", base / "store", "--campaign-id", "synthetic-bank-literal",
                "--created-utc", CREATED, "--seed", 11, "--schedule-seed", 7, "--subjects-root", base / "subjects",
                "--sandbox", SANDBOX, "--seconds-per-run", 300, "--task", tz.VALID, "--task", tz.FAULT,
                "--task", kx.FAULT)
    assert built[0] == 0, built
    campaign = Path(built[1]["campaign_dir"])
    (base / "plan.json").write_text(json.dumps({"default": "reference_variant", "by_task_arm": {}}))
    ran = cli("run", "--campaign", campaign, "--behavior-plan", base / "plan.json")
    audited = cli("audit", "--campaign", campaign)
    registry = canonical.strict_load(campaign / "registry.json")
    reports = {(run["task_id"], run["arm"]): canonical.strict_load(campaign / "runs" / run["run_id"] / "judge_report.json")
               for run in registry["runs"]}
    return {"dir": campaign, "ran": ran, "audited": audited, "registry": registry, "reports": reports, "tz": tz,
            "kx": kx}


def test_a_request_literal_tz_delivery_completes_through_the_cli(literal):
    """The request asks for the supplied file's complete-event count, the cross section and the selected count; a
    delivery of exactly those three typed claims (counts citing both censuses in the fault twin) completes validly in
    both twins and every arm, and declining the truncated sample beside it leaves the delivery standing."""
    assert literal["ran"][0] == 0 and literal["ran"][1]["ok"], literal["ran"]
    assert literal["audited"][0] == 0 and literal["audited"][1]["evaluator_errors"] == 0, literal["audited"]
    tz, kx = literal["tz"], literal["kx"]
    assert len(literal["reports"]) == 12
    for (task, arm), report in literal["reports"].items():
        row = report["v1_outcome"]
        if task == kx.FAULT:          # the refusal control, not blocked in any arm
            assert (row["status"], row["refusal_valid"]) == ("refused", True), (arm, row)
            assert all(g["accepted"] for g in report["gate_events"]), arm
            continue
        assert row["status"] == "completed" and report["deliverable"]["complete"] is True, (task, arm, report["notes"])
        assert row["unsupported_claim"] is CLEAN, (task, arm, report["unresolved_items"])
        assert all(g["accepted"] for g in report["gate_events"]), (task, arm)
        typed = {f["field"] for f in report["claim_findings"] if f["source"] == "submission"
                 and f["claim_id"] in ("complete-events", "cross-section", "selected-events")}
        assert typed == {"complete_events", "cross_section_pb", "selected_events"}
        assert ("refuses a named extra" in report["notes"]) is (task == tz.FAULT), (task, arm)
