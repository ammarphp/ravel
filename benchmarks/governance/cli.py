#!/usr/bin/env python3
"""Evaluation-harness command line (slice design §2, §10): python3 benchmarks/governance/cli.py <command>.

Commands: ``build-synthetic`` (freeze a synthetic fake-host campaign), ``run`` (process its
assignments with the fake adapter), ``audit`` (the independent evaluator, audit.audit_campaign,
once every assignment is sealed), ``report`` (outcomes.json from audit.py's judge reports, then
the v1 summary and the analysis), ``verify`` (campaign manifest and judge-report provenance),
``treatment-diff`` (the four arm manifests differ only in the declared factors; with
``--behavioral`` also the same stale and clean probe through a real broker per arm, checked by
treatment.behavioral_diff, so a no-op guard fails) and ``incident-decision`` (a HUMAN reviewer
records the decision on one run whose seal does not reconcile; outcomes then carry the
evaluator's null-judgment row for it). Every command, including a usage error, prints one JSON
object and exits 0 on success, 1 when a check fails and 2 on an error. Nothing here calls a model:
the only host wired to ``run`` is the synthetic fake subject. The mechanism-study variant is not
carried by any campaign in this slice, so ``treatment-diff --mechanism-study`` is refused.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

GOVERNANCE_DIR = Path(__file__).resolve().parent
BENCHMARKS = GOVERNANCE_DIR.parent
# Run as a script, Python puts this file's directory first on sys.path, where analysis.py, stages/,
# oracle/ and tasks/ would shadow top-level modules of the same names: drop it, import the package.
if sys.path and sys.path[0] and os.path.realpath(sys.path[0]) == str(GOVERNANCE_DIR):
    sys.path.pop(0)
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from governance import campaign_manifest, canonical, runner, treatment  # noqa: E402
from governance.canonical import ContractError  # noqa: E402

BUDGET_OPTIONS = {"usd_per_run": float, "seconds_per_run": float, "max_broker_ops": int, "max_fits": int,
                  "global_usd_cap": float, "global_seconds_cap": float}


class _Parser(argparse.ArgumentParser):
    """argparse that raises instead of printing usage text and exiting, so errors print as JSON."""

    def error(self, message):
        raise ContractError(f"usage: {message}")


def _campaign(args) -> Path:
    return Path(args.campaign).resolve()


def cmd_build_synthetic(args) -> dict:
    budget = {name: getattr(args, name) for name in BUDGET_OPTIONS if getattr(args, name) is not None}
    campaign_dir = runner.build_synthetic_campaign(
        Path(args.store).resolve(), campaign_id=args.campaign_id, created_utc=args.created_utc, seeds=args.seed,
        schedule_seed=args.schedule_seed, subjects_root=Path(args.subjects_root).resolve(), budget=budget,
        sandbox=args.sandbox)
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    return {"ok": True, "synthetic": True, "campaign_dir": str(campaign_dir), "runs": len(registry["runs"]),
            "registry_sha256": registry["registry_sha256"]}


def cmd_run(args) -> dict:
    manifest = canonical.strict_load(_campaign(args) / campaign_manifest.MANIFEST)
    if manifest["host"]["adapter"] != "fake":
        raise ContractError("only the synthetic fake host is wired to this command; live hosts need RAVEL_EVAL_LIVE=1, "
                            "an approved campaign and a separate launcher")
    plan = canonical.strict_load(args.behavior_plan) if args.behavior_plan else None
    result = runner.run_campaign(_campaign(args), adapter_factory=runner.fake_adapter_factory, behavior_plan=plan,
                                 only=args.only)
    return {"ok": True, **result}


def cmd_audit(args) -> dict:
    """Judge every sealed assignment; refuses while any is unsealed (audit.py would otherwise write a
    permanent report for a run the coordinator has not finished)."""
    campaign_dir = _campaign(args)
    with runner.campaign_lock(campaign_dir):
        unsealed = runner.unsealed_runs(campaign_dir)
        if unsealed:
            raise ContractError(f"refusing to audit: {len(unsealed)} assignment(s) not sealed yet "
                                f"(run them first): {unsealed[:5]}")
        audit = runner.audit_module()
        if audit is None:
            return {"ok": False, "error": "governance.audit is not installed in this checkout (audit.py missing); "
                                          "no judge reports were written"}
        reports = audit.audit_campaign(campaign_dir)
    return {"ok": True, "scorer_id": audit.SCORER_ID, "judge_reports": len(reports),
            "status_counts": dict(sorted(Counter(r["status"] for r in reports).items())),
            "synthetic": all(r["synthetic"] for r in reports)}


def cmd_report(args) -> dict:
    outcomes = runner.write_outcomes(_campaign(args))
    result = runner.report(_campaign(args), bootstrap_seed=args.bootstrap_seed, n_bootstrap=args.n_bootstrap)
    return {"ok": True, "outcomes": str(outcomes), **result}


def cmd_verify(args) -> dict:
    campaign_dir = _campaign(args)
    verified = campaign_manifest.verify(campaign_dir)
    reports = []
    if verified["ok"]:
        registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
        for run in registry["runs"]:
            path = campaign_dir / "runs" / run["run_id"] / "judge_report.json"
            if path.is_file():
                reports.append(canonical.strict_load(path))
    provenance = campaign_manifest.verify_run_provenance(campaign_dir, reports)
    return {"ok": verified["ok"] and provenance["ok"], "campaign": verified, "provenance": provenance,
            "judge_reports": len(reports)}


MECHANISM_STUDY_UNSUPPORTED = (
    "the mechanism-study variant is library-level only in this slice: no campaign can carry it (a campaign "
    "manifest declares no design, runner.arm_manifests freezes the primary 2x2 and a campaign load rejects any "
    "other arms), so there is no mechanism-study campaign to check")


def cmd_treatment_diff(args) -> dict:
    if args.mechanism_study:
        raise ContractError(MECHANISM_STUDY_UNSUPPORTED)
    manifest = canonical.strict_load(_campaign(args) / campaign_manifest.MANIFEST)
    diff = treatment.treatment_diff(manifest["arms"])
    if not args.behavioral:
        return diff
    behavioral = runner.behavioral_check(_campaign(args))
    return {"ok": diff["ok"] and behavioral["ok"], "manifest": diff, "behavioral": behavioral}


def cmd_incident_decision(args) -> dict:
    path = runner.record_incident_decision(_campaign(args), args.run_id, decided_by=args.decided_by,
                                           reason=args.reason, decided_utc=args.decided_utc)
    return {"ok": True, "record": str(path), "decision": canonical.strict_load(path)}


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="cli.py", description=__doc__.splitlines()[0])
    commands = p.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-synthetic", help="freeze a synthetic fake-host campaign")
    build.add_argument("--store", required=True)
    build.add_argument("--campaign-id", required=True)
    build.add_argument("--created-utc", required=True, help="ISO-8601 UTC timestamp supplied by the caller")
    build.add_argument("--seed", type=int, action="append", required=True, help="repeat for several seeds")
    build.add_argument("--schedule-seed", type=int, required=True)
    build.add_argument("--subjects-root", required=True)
    build.add_argument("--sandbox", choices=("seatbelt", "none_test_only"), default="seatbelt")
    for name, kind in BUDGET_OPTIONS.items():
        build.add_argument("--" + name.replace("_", "-"), dest=name, type=kind)
    build.set_defaults(func=cmd_build_synthetic)
    run = commands.add_parser("run", help="process assignments with the synthetic fake host")
    run.add_argument("--campaign", required=True)
    run.add_argument("--behavior-plan", help="JSON file {default, by_task_arm}")
    run.add_argument("--only", action="append", help="a run_id to process (repeatable)")
    run.set_defaults(func=cmd_run)
    for name, func, text in (("audit", cmd_audit, "write judge reports (audit.py) once every run is sealed"),
                             ("verify", cmd_verify, "verify the campaign and judge-report provenance")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--campaign", required=True)
        sub.set_defaults(func=func)
    report = commands.add_parser("report", help="outcomes.json, v1 summary.json and analysis.json")
    report.add_argument("--campaign", required=True)
    report.add_argument("--bootstrap-seed", type=int, default=0)
    report.add_argument("--n-bootstrap", type=int, default=2000)
    report.set_defaults(func=cmd_report)
    diff = commands.add_parser("treatment-diff", help="check the four arm manifests differ only in declared factors")
    diff.add_argument("--campaign", required=True)
    diff.add_argument("--behavioral", action="store_true",
                      help="also send the same stale and clean probe through a real broker per arm (runs the kernel)")
    diff.add_argument("--mechanism-study", action="store_true", help="refused: no campaign carries this variant")
    diff.set_defaults(func=cmd_treatment_diff)
    incident = commands.add_parser("incident-decision",
                                   help="HUMAN decision on a run whose seal does not reconcile (null-judgment row)")
    incident.add_argument("--campaign", required=True)
    incident.add_argument("--run-id", required=True)
    incident.add_argument("--decided-by", required=True, help="the accountable reviewer's name")
    incident.add_argument("--reason", required=True)
    incident.add_argument("--decided-utc", help="ISO-8601 time of the decision (default: now)")
    incident.set_defaults(func=cmd_incident_decision)
    return p


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
        result = args.func(args)
        code = 0 if result.get("ok") else 1
    except Exception as exc:  # every failure is one JSON object and exit 2, never a bare traceback
        result, code = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 2
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
