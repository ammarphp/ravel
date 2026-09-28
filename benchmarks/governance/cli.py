#!/usr/bin/env python3
"""Evaluation-harness command line (slice design §2, §10): python3 benchmarks/governance/cli.py <command>.

Commands: ``build-synthetic`` (freeze a synthetic fake-host campaign), ``run`` (process its
assignments), ``audit`` (the independent evaluator, audit.audit_campaign, once every assignment is
sealed), ``rejudge`` (score a sealed campaign with the current evaluator into a new directory outside it,
read-only on the campaign: judge reports, outcomes.json and rejudge.json with the sealed and re-judged
cells per run), ``report`` (outcomes.json from audit.py's judge reports, then the v1 summary and the
analysis), ``verify`` (campaign manifest and judge-report provenance), ``treatment-diff`` (the four
arm manifests differ only in the declared factors; with ``--behavioral`` also the same stale and
clean probe through a real broker per arm, checked by treatment.behavioral_diff, so a no-op guard
fails) and ``incident-decision`` (a HUMAN reviewer records the decision on one run whose seal does
not reconcile; outcomes then carry the evaluator's null-judgment row for it).

Real host (the synthetic engineering smoke with the Claude Code CLI; configuration, procedure and stop
rules in docs/development/evaluation-study/smoke-request.md). Refused without ``RAVEL_EVAL_LIVE=1``:
``build-live`` (freeze a campaign with a pinned CLI, a task subset, the budget owner's single-use
approval and the host launch declaration; the credential file is only stat'ed), ``host-probe``
(HP-01..HP-13, non-model, no egress; ``--dry-start`` and ``--rehearse`` run the pinned binary with
DUMMY credentials, the latter against a local mock API; ``--catalog-rates`` lets HP-13 accept the pinned
binary's own catalog price entry when it equals the measured rates; it installs the same signal handlers
as ``run``, and a probe launch whose census is unclean fails the record), ``preflight`` (PF-01..PF-14,
every condition for a paid launch, stat-only for the credential) and ``run`` on a live campaign (it
installs SIGHUP/SIGTERM handlers that interrupt the coordinator so its launch is killed by census, sets a
hard core-file limit of 0, re-derives the stop rules of every sealed run before anything else, then
requires preflight and the run-start credential validation, whose failure is a pause (exit 1,
``paused``, nothing journaled), and applies the stop rules after each sealed run; ``--limit N`` processes
at most N unsealed assignments, a pause; once run 1 was launched no further run launches until
``go-no-go`` recorded a go (a hold: exit 1, ``held`` true); ``--only`` is refused; under
``coordinator/stop.json`` it runs no preflight, launches nothing and closes the remaining assignments
not_started, still evaluating a lost launch it seals; every S2 trigger prints the REVOKE ``action``, even
one that found a stop already in place). Loading a live campaign needs the flag too, so
``treatment-diff --behavioral`` does. Without the flag, since they read and write only the store:
``live-checks`` (LC-01..LC-23 per sealed run, written to ``runs/<id>/live_checks.json``; ``--costs`` adds
the cost reconciliation), ``go-no-go`` (S10a: the recorded review of run 1, written once to
``coordinator/go_no_go.json``; a go needs run 1's live checks without a failure or a stop and LC-16
passed, or ``--accept-unverified-cost`` naming a recorded decision; a no-go also writes a human stop) and
``stop`` (a human stop, S8, written to ``coordinator/stop.json``; it takes effect between runs). To abort
a running launch press Ctrl-C in the coordinator's terminal, never a kill by name or pid; the command
then ends with Python's KeyboardInterrupt report. Otherwise every command, including a usage error,
prints one JSON object and exits 0 on success (a ``--limit`` pause included), 1 when a check fails, a
stop is in effect, the S10a gate holds the run or the credential validation paused it, and 2 on an error
or a SIGHUP/SIGTERM interruption (an interrupted ``run`` is resumed by running it again). The mechanism-study variant is not carried by
any campaign in this slice, so ``treatment-diff --mechanism-study`` is refused. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import signal
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

from governance import campaign_manifest, canonical, credentials, isolation, live, runner, treatment  # noqa: E402
from governance.canonical import ContractError  # noqa: E402

BUDGET_OPTIONS = {"usd_per_run": float, "seconds_per_run": float, "max_broker_ops": int, "max_fits": int,
                  "max_stage_executions": int, "global_usd_cap": float, "global_seconds_cap": float}


class _Parser(argparse.ArgumentParser):
    """argparse that raises instead of printing usage text and exiting, so errors print as JSON."""

    def error(self, message):
        raise ContractError(f"usage: {message}")


def _campaign(args) -> Path:
    return Path(args.campaign).resolve()


def require(condition, message):
    if not condition:
        raise ContractError(message)


def cmd_build_synthetic(args) -> dict:
    budget = {name: getattr(args, name) for name in BUDGET_OPTIONS if getattr(args, name) is not None}
    campaign_dir = runner.build_synthetic_campaign(
        Path(args.store).resolve(), campaign_id=args.campaign_id, created_utc=args.created_utc, seeds=args.seed,
        schedule_seed=args.schedule_seed, subjects_root=Path(args.subjects_root).resolve(), budget=budget,
        sandbox=args.sandbox, tasks=args.task)
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    return {"ok": True, "synthetic": True, "campaign_dir": str(campaign_dir), "runs": len(registry["runs"]),
            "tasks": [t["id"] for t in registry["spec"]["tasks"]], "registry_sha256": registry["registry_sha256"]}


def _interrupt(signum, frame):
    isolation.interrupt(runner.CoordinatorInterrupted(f"signal {signal.Signals(signum).name}"))


def _keyboard(signum, frame):
    """Ctrl-C stays Python's KeyboardInterrupt, held like the other interrupts while a launch's start is recorded or
    an interrupted launch is killed (E-81)."""
    isolation.interrupt(KeyboardInterrupt())


def install_live_handlers() -> None:
    """M8 (R12b, R12e): SIGHUP and SIGTERM raise CoordinatorInterrupted in the main thread (isolation.launch's finally
    kills the launch by census; the broker and proxy stop) and SIGINT raises KeyboardInterrupt, each deferred while a
    launch's start is being recorded or an interrupted launch is being killed (isolation.interrupts_deferred, E-81),
    and the hard core-file limit becomes 0."""
    for signum in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(signum, _interrupt)
    signal.signal(signal.SIGINT, _keyboard)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def cmd_run(args) -> dict:
    manifest = canonical.strict_load(_campaign(args) / campaign_manifest.MANIFEST)
    plan = canonical.strict_load(args.behavior_plan) if args.behavior_plan else None
    if manifest["host"]["adapter"] == "fake":
        result = runner.run_campaign(_campaign(args), adapter_factory=runner.fake_adapter_factory, behavior_plan=plan,
                                     only=args.only, limit=args.limit)
        return {"ok": True, **result}
    require_live("run")
    if manifest["host"]["adapter"] != "claude_cli":
        raise ContractError(f"no launcher is wired for a {manifest['host']['adapter']} host")
    if args.only:   # E-79: every run in registry order, so a lost launch is resumed, charged and stopped first
        raise ContractError("run --only is refused for a real host; run the campaign (with --limit N to pause)")
    install_live_handlers()
    try:
        result = runner.run_campaign(_campaign(args), behavior_plan=plan, limit=args.limit)
    except runner.CredentialPause as exc:
        return {"ok": False, "paused": True, "error": str(exc)}
    stopped = result.get("stopped")
    out = {"ok": stopped is None and not result.get("held"), **result}
    if (stopped is not None and stopped.get("rule") == "S2") or any(t["rule"] == "S2" for t in result["triggers"]):
        out["action"] = live.REVOKE
    return out


def require_live(what):
    if os.environ.get(live.LIVE_FLAG) != "1":
        raise ContractError(f"{what}: a real host needs {live.LIVE_FLAG}=1 (smoke spec §3 S2)")


def cmd_build_live(args) -> dict:
    require_live("build-live")
    pin = live.HostPin(adapter="claude_cli", executable=args.executable, executable_sha256=args.executable_sha256,
                       version=args.host_version, model=args.model, effort=args.effort)
    approval = Path(args.approval_file).read_bytes()
    budget = {"usd_per_run": args.usd_per_run, "seconds_per_run": args.seconds_per_run,
              "global_seconds_cap": args.global_seconds_cap}
    for name in ("max_broker_ops", "max_fits", "max_stage_executions", "global_usd_cap"):
        if getattr(args, name) is not None:
            budget[name] = getattr(args, name)
    claude = {"max_turns": args.max_turns} if args.max_turns is not None else None
    credential = os.path.abspath(os.path.expanduser(args.credential_file))
    campaign_dir = live.build_live_campaign(
        Path(args.store).resolve(), campaign_id=args.campaign_id, created_utc=args.created_utc, seeds=args.seed,
        schedule_seed=args.schedule_seed, subjects_root=Path(args.subjects_root), host_state_root=args.host_state_root,
        tasks=args.task, pin=pin, credential_file=credential, approval_bytes=approval, budget=budget, claude=claude)
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    return {"ok": True, "synthetic": True, "campaign_dir": str(campaign_dir), "runs": len(registry["runs"]),
            "registry_sha256": registry["registry_sha256"],
            "approval_sha256": canonical.sha256_bytes(approval),
            "host_binding_sha256": canonical.sha256_file(campaign_dir / runner.COORDINATOR / runner.HOST_BINDING),
            "credential_present": credentials.check_credential_file(credential)["present"]}


def cmd_preflight(args) -> dict:
    require_live("preflight")
    return live.preflight(_campaign(args))


def cmd_host_probe(args) -> dict:
    require_live("host-probe")
    require(not args.catalog_rates or args.rehearse, "--catalog-rates applies to HP-13: it needs --rehearse")
    install_live_handlers()   # E-96: a probe launch is started, recorded and killed like a run's (E-81)
    return live.host_probe(_campaign(args), dry_start=args.dry_start, rehearse=args.rehearse,
                           catalog=args.catalog_rates)


def cmd_go_no_go(args) -> dict:
    """S10a (E-92): the recorded review of run 1, which opens (go) or stops (no-go, S8) the rest of a live campaign."""
    campaign_dir = _campaign(args)
    with runner.campaign_lock(campaign_dir):
        record = live.record_go_no_go(campaign_dir, decision=args.decision, decided_by=args.by, reason=args.reason,
                                      accept_unverified_cost=args.accept_unverified_cost)
        return {"ok": True, "go_no_go": record, "stop": runner.read_stop(campaign_dir)}


def cmd_live_checks(args) -> dict:
    campaign_dir = _campaign(args)
    with runner.campaign_lock(campaign_dir):
        checks = [live.live_checks(campaign_dir, args.run_id)] if args.run_id else live.live_checks_all(campaign_dir)
        out = {"ok": all(c["stop"] is None and all(x["status"] != "fail" for x in c["checks"]) for c in checks),
               "runs": checks, "stop": runner.read_stop(campaign_dir)}
        if args.costs:
            out["costs"] = live.costs(campaign_dir)
    if any((c.get("stop") or {}).get("rule") == "S2" for c in checks):
        out["action"] = live.REVOKE
    return out


def cmd_stop(args) -> dict:
    campaign_dir = _campaign(args)
    require((campaign_dir / runner.COORDINATOR).is_dir(), f"{campaign_dir}: not a runner-built campaign")
    existing = runner.read_stop(campaign_dir)
    if existing is not None:
        return {"ok": True, "stop": existing, "note": "already stopped"}
    record, written = runner.record_stop(campaign_dir, run_id=None, rule="S8", reason=args.reason,
                                         set_by=f"cli.py stop ({args.by})")
    if not written:   # an automated stop was written first (both are exclusive: neither overwrites the other)
        return {"ok": True, "stop": record, "note": "already stopped"}
    return {"ok": True, "stop": record, "note": "takes effect between runs; a running launch finishes (Ctrl-C in the "
                                                "coordinator's terminal aborts it)"}


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
    # an evaluator defect becomes a permanent unscorable_record row (E-150): report it and fail (E-181)
    marker = "unscorable_record: " + getattr(audit, "EVALUATOR_ERROR", "evaluator error ")
    errors = [r.get("run_id") for r in reports
              if any(str(item).startswith(marker) for item in r.get("unresolved_items") or ())]
    result = {"ok": not errors, "scorer_id": audit.SCORER_ID, "judge_reports": len(reports),
              "status_counts": dict(sorted(Counter(r["status"] for r in reports).items())),
              "synthetic": all(r["synthetic"] for r in reports), "evaluator_errors": len(errors)}
    if errors:
        result["evaluator_error_runs"] = errors
        result["note"] = ("the evaluator raised on these runs and wrote unscorable_record rows, which are never "
                          "overwritten: fix the evaluator and re-audit under its new scorer id elsewhere")
    return result


def _cells(report) -> dict | None:
    """The per-run cells a re-judgment compares (None: no sealed judge report)."""
    if report is None:
        return None
    return {"scorer_id": report["scorer_id"], "status": report["status"],
            "unsupported_claim": report["v1_outcome"]["unsupported_claim"],
            "refusal_valid": report["v1_outcome"]["refusal_valid"],
            "reason_matched": report["refusal"]["reason_matched"],
            "unresolved_items": len(report["unresolved_items"]),
            "attempted_invalid": report["quantities"]["attempted_invalid"],
            "delivered_invalid": report["quantities"]["delivered_invalid"]}


def cmd_rejudge(args) -> dict:
    """Re-judge a sealed campaign with the current evaluator into a separate directory (decision E-189), read-only on
    the campaign: it verifies the campaign, refuses while any assignment is unsealed, judges every assignment with
    audit.build_report (which writes nothing) and writes only under ``--out``, a new directory outside the campaign:
    runs/<run_id>/judge_report.json, outcomes.json and rejudge.json (the scorer ids and, per run, the sealed report's
    cells beside the re-judged ones). The campaign's own judge reports stay its record; nothing there is written."""
    campaign_dir, out = _campaign(args), Path(args.out).resolve()
    require(out != campaign_dir and campaign_dir not in out.parents and out not in campaign_dir.parents,
            f"--out must lie outside the campaign (and not contain it): {out}")
    require(not out.exists() and not out.is_symlink(), f"refusing to write into an existing path {out}: a re-judgment "
                                                       "is written once, into a new directory")
    verified = campaign_manifest.verify(campaign_dir)
    require(verified["ok"], f"campaign does not verify: {verified['errors']}")
    unsealed = runner.unsealed_runs(campaign_dir)
    require(not unsealed, f"refusing to re-judge: {len(unsealed)} assignment(s) not sealed yet: {unsealed[:5]}")
    audit = runner.audit_module()
    require(audit is not None, "governance.audit is not installed in this checkout (audit.py missing)")
    manifest = canonical.strict_load(campaign_dir / campaign_manifest.MANIFEST)
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    reports, rows = [], []
    for run in registry["runs"]:
        report = audit.build_report(campaign_dir, run["run_id"])
        sealed = campaign_dir / "runs" / run["run_id"] / "judge_report.json"
        before = canonical.strict_load(sealed) if sealed.is_file() and not sealed.is_symlink() else None
        reports.append(report)
        rows.append({"run_id": run["run_id"], "task_id": run["task_id"], "arm": run["arm"],
                     "sealed": _cells(before), "rejudged": _cells(report)})
    errors = audit.evaluator_errors(reports)
    record = {"schema_version": 1, "kind": "rejudge", "campaign_id": manifest["campaign_id"],
              "registry_sha256": registry["registry_sha256"], "scorer_id": audit.SCORER_ID,
              "review_state": audit.REVIEW_STATE, "synthetic": all(r["synthetic"] for r in reports),
              "sealed_scorer_ids": sorted({row["sealed"]["scorer_id"] for row in rows if row["sealed"]}),
              "evaluator_error_runs": errors, "runs": rows,
              "note": "a re-judgment of sealed evidence by a later scorer; the campaign's own judge reports remain its "
                      "record (E-189)"}
    (out / "runs").mkdir(parents=True)
    for report in reports:
        (out / "runs" / report["run_id"]).mkdir()
        canonical.write_once(out / "runs" / report["run_id"] / "judge_report.json",
                             canonical.canonical_bytes(report) + b"\n")
    canonical.write_once(out / "outcomes.json", canonical.canonical_bytes(audit.outcomes_document(registry, reports))
                         + b"\n")
    canonical.write_once(out / "rejudge.json", canonical.canonical_bytes(record) + b"\n")
    return {"ok": not errors, "out": str(out), "scorer_id": audit.SCORER_ID,
            "sealed_scorer_ids": record["sealed_scorer_ids"], "judge_reports": len(reports),
            "evaluator_errors": len(errors), "runs": rows}


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
    build.add_argument("--task", action="append", help="a bank task id (repeatable; default: every runnable task)")
    for name, kind in BUDGET_OPTIONS.items():
        build.add_argument("--" + name.replace("_", "-"), dest=name, type=kind)
    build.set_defaults(func=cmd_build_synthetic)
    run = commands.add_parser("run", help="process assignments (the fake host, or a live host with RAVEL_EVAL_LIVE=1)")
    run.add_argument("--campaign", required=True)
    run.add_argument("--behavior-plan", help="JSON file {default, by_task_arm}")
    run.add_argument("--only", action="append", help="a run_id to process (repeatable)")
    run.add_argument("--limit", type=int, help="process at most N unsealed assignments (a pause, not a stop)")
    run.set_defaults(func=cmd_run)
    live_build = commands.add_parser("build-live", help="freeze a real-host synthetic smoke campaign (RAVEL_EVAL_LIVE=1)")
    for name in ("--store", "--campaign-id", "--created-utc", "--subjects-root", "--host-state-root", "--executable",
                 "--executable-sha256", "--host-version", "--model", "--effort", "--credential-file", "--approval-file"):
        live_build.add_argument(name, required=True)
    live_build.add_argument("--seed", type=int, action="append", required=True)
    live_build.add_argument("--schedule-seed", type=int, required=True)
    live_build.add_argument("--task", action="append", required=True, help="a family task id (repeatable)")
    live_build.add_argument("--usd-per-run", type=float, required=True)
    live_build.add_argument("--seconds-per-run", type=float, required=True)
    live_build.add_argument("--global-seconds-cap", type=float, required=True)
    live_build.add_argument("--global-usd-cap", type=float)
    live_build.add_argument("--max-broker-ops", type=int)
    live_build.add_argument("--max-fits", type=int)
    live_build.add_argument("--max-stage-executions", type=int)
    live_build.add_argument("--max-turns", type=int)
    live_build.set_defaults(func=cmd_build_live)
    probe = commands.add_parser("host-probe", help="HP-01..HP-13 for a live campaign (no model, no egress)")
    probe.add_argument("--campaign", required=True)
    probe.add_argument("--dry-start", action="store_true", help="HP-09: the pinned binary, a DUMMY token, no egress")
    probe.add_argument("--rehearse", action="store_true", help="HP-13: the offline rehearsal against a local mock API")
    probe.add_argument("--catalog-rates", action="store_true",
                       help="HP-13 may accept the pinned binary's own catalog price entry for the model, located in "
                            "its bytes, when it equals the measured rates exactly (H-27)")
    probe.set_defaults(func=cmd_host_probe)
    pre = commands.add_parser("preflight", help="every condition for a paid launch (stat-only for the credential)")
    pre.add_argument("--campaign", required=True)
    pre.set_defaults(func=cmd_preflight)
    checks = commands.add_parser("live-checks", help="LC-01..LC-23 of the sealed runs of a live campaign")
    checks.add_argument("--campaign", required=True)
    checks.add_argument("--run-id")
    checks.add_argument("--costs", action="store_true", help="add the cost reconciliation (smoke spec §5)")
    checks.set_defaults(func=cmd_live_checks)
    review = commands.add_parser("go-no-go", help="S10a: record the review of run 1 before runs 2 to 8 (E-92)")
    review.add_argument("--campaign", required=True)
    review.add_argument("--decision", required=True, choices=live.GO_DECISIONS)
    review.add_argument("--by", required=True, help="the reviewer's name")
    review.add_argument("--reason", required=True)
    review.add_argument("--accept-unverified-cost", metavar="DECISION_ID",
                        help="a go with LC-16 at warn (an unverified recompute) names the decision that accepts it")
    review.set_defaults(func=cmd_go_no_go)
    stop = commands.add_parser("stop", help="a human stop (S8): no further launch; takes effect between runs")
    stop.add_argument("--campaign", required=True)
    stop.add_argument("--reason", required=True)
    stop.add_argument("--by", required=True, help="the person stopping the campaign")
    stop.set_defaults(func=cmd_stop)
    for name, func, text in (("audit", cmd_audit, "write judge reports (audit.py) once every run is sealed"),
                             ("verify", cmd_verify, "verify the campaign and judge-report provenance")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--campaign", required=True)
        sub.set_defaults(func=func)
    rejudge = commands.add_parser("rejudge", help="re-judge a sealed campaign with the current evaluator into a new "
                                                  "directory outside it (read-only on the campaign)")
    rejudge.add_argument("--campaign", required=True)
    rejudge.add_argument("--out", required=True, help="a new directory outside the campaign")
    rejudge.set_defaults(func=cmd_rejudge)
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
    except runner.CoordinatorInterrupted as exc:   # SIGHUP/SIGTERM: the launch was killed by census on the way out
        result, code = {"ok": False, "interrupted": str(exc),
                        "note": "the coordinator was interrupted; run the same command to resume (a lost launch is "
                                "sealed interrupted, charged its cap and never relaunched)"}, 2
    except Exception as exc:  # every failure is one JSON object and exit 2, never a bare traceback
        result, code = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 2
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
