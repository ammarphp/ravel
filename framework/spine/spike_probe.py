#!/usr/bin/env python3
"""spike_probe -- record & re-verify the L0 harness-behaviour spikes (SPK-1/2/3).

stdlib-only, read-only, fail-loud. Confirms the three load-bearing runtime assumptions of the
workflow-adherence spine and writes a durable PASS artifact + a per-spike
hook-primary|fallback-primary decision that HOOK-PRIMACY.json consumes.

  SPK-1  hooks fire        Stop/PostToolUse/UserPromptSubmit each fire; Stop exit-2 blocks turn-end + feeds its reason back
  SPK-2  bg re-invocation  a harness run_in_background job's stdout re-invokes the agent on completion
  SPK-3  timed wake        a scheduled wake re-fires at ~the set time

Usage:
  spike_probe.py --new-token
  spike_probe.py --spike SPK-1 --probe-log <log> --transcript <txt> --record <out.json> [--json]
  spike_probe.py --spike SPK-2 --evidence <evidence.json> --record <out.json> [--json]
  spike_probe.py --spike SPK-3 --evidence <evidence.json> --record <out.json> [--json]
  spike_probe.py --spike SPK-1 --check <artifact.json> [--json]
  spike_probe.py --primacy [--spikes-dir <dir>] --out <HOOK-PRIMACY.json> [--json]
  spike_probe.py --check-primacy <HOOK-PRIMACY.json> [--json]
  spike_probe.py --selftest

Exit codes: 0 PASS (WARNs allowed) * 1 spike/consistency FAIL * 2 usage / not-a-file * 3 malformed evidence/artifact
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)   # sibling _infrastructure imports resolve when run as a script

SCHEMA_VERSION = 1
GENERATOR = "spike_probe.py"
SPIKES = ("SPK-1", "SPK-2", "SPK-3")


def _resolve_timestamp(cli_timestamp=None):
    """generated_utc: --timestamp, else $SPIKE_PROBE_UTC, else "" -- never datetime.now()."""
    if cli_timestamp:
        return cli_timestamp
    return os.environ.get("SPIKE_PROBE_UTC", "")


def _fingerprint(evidence):
    """sha256 over the canonical JSON of the spike's evidence dict (provenance)."""
    blob = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _parse_utc(s):
    """Parse an ...Z or offset ISO-8601 stamp to an aware datetime; None on failure."""
    if not isinstance(s, str) or not s:
        return None
    t = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---- per-spike verifiers: each returns (verdict, decision, checks). verdict defaults NON-passing. --

def verify_spk1(evidence):
    log = evidence.get("probe_log", "") or ""
    transcript = evidence.get("transcript", "") or ""
    ups = "USERPROMPTSUBMIT" in log
    ptu = "POSTTOOLUSE" in log
    stop_n = len(re.findall(r"(?m)^STOP\b", log))
    stop_fired = stop_n >= 1
    stop_blocked_then_released = stop_n >= 2      # blocked once (exit 2), then allowed (exit 0)
    fed_back = "SPK1-STOP-BLOCK" in transcript
    checks = [
        {"name": "UserPromptSubmit fired", "ok": ups, "detail": "sentinel in probe log"},
        {"name": "PostToolUse fired", "ok": ptu, "detail": "sentinel in probe log"},
        {"name": "Stop fired", "ok": stop_fired, "detail": f"STOP sentinels={stop_n}"},
        {"name": "Stop exit-2 blocked then released", "ok": stop_blocked_then_released,
         "detail": f"needs >=2 STOP lines (block, then allow); got {stop_n}"},
        {"name": "exit-2 reason fed back", "ok": fed_back,
         "detail": "reason string SPK1-STOP-BLOCK present in the -p transcript"},
    ]
    ok = ups and ptu and stop_fired and stop_blocked_then_released and fed_back
    verdict = "PASS" if ok else "unproven"
    decision = "hook-primary" if ok else "fallback-primary"
    return verdict, decision, checks


def verify_spk2(evidence):
    token = evidence.get("token", "") or ""
    launch = evidence.get("launch_cmd", "") or ""
    reinvoke = evidence.get("reinvoke_text", "") or ""
    tok_ok = bool(token) and len(token) >= 8
    in_launch = tok_ok and token in launch
    in_reinvoke = tok_ok and token in reinvoke
    checks = [
        {"name": "token well-formed", "ok": tok_ok, "detail": f"token={token!r}"},
        {"name": "token embedded in bg launch", "ok": in_launch, "detail": "token in launch_cmd"},
        {"name": "re-invocation carried the job stdout", "ok": in_reinvoke,
         "detail": "token round-tripped through the completion re-invoke"},
    ]
    ok = tok_ok and in_launch and in_reinvoke
    verdict = "PASS" if ok else "unproven"
    decision = "harness-reinvoke-primary" if ok else "poll-fallback-primary"
    return verdict, decision, checks


def verify_spk3(evidence):
    mech = evidence.get("mechanism", "") or ""
    sched = _parse_utc(evidence.get("scheduled_utc", ""))
    fired = _parse_utc(evidence.get("fired_utc", ""))
    tol = evidence.get("tolerance_s", None)
    mech_ok = bool(mech)
    times_ok = sched is not None and fired is not None and isinstance(tol, (int, float)) and tol >= 0
    delta = abs((fired - sched).total_seconds()) if times_ok else None
    within = times_ok and delta <= tol
    checks = [
        {"name": "wake mechanism named", "ok": mech_ok, "detail": f"mechanism={mech!r}"},
        {"name": "scheduled/fired timestamps parse", "ok": times_ok,
         "detail": "scheduled_utc/fired_utc/tolerance_s all present & valid"},
        {"name": "re-fired within tolerance", "ok": within,
         "detail": (f"|fired-scheduled|={delta:.1f}s <= {tol}s" if delta is not None else "n/a")},
    ]
    ok = mech_ok and times_ok and within
    verdict = "PASS" if ok else "unproven"
    decision = "wake-primitive-primary" if ok else "bg-sleep-reinvoke-fallback"
    return verdict, decision, checks


_VERIFIERS = {"SPK-1": verify_spk1, "SPK-2": verify_spk2, "SPK-3": verify_spk3}


def build_record(spike, evidence, timestamp=None):
    verdict, decision, checks = _VERIFIERS[spike](evidence)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _resolve_timestamp(timestamp),
        "generator": GENERATOR,
        "generated_by": GENERATOR,
        "input_fingerprint": _fingerprint(evidence),
        "spike": spike,
        "verdict": verdict,
        "decision": decision,
        "evidence": evidence,
        "checks": checks,
        "exit": 0 if verdict == "PASS" else 1,
    }


# ---- per-branch primacy synthesis ---------------------------------------------------------------
# Fixed enforcement-branch -> (governing spike, hook-primary label, fallback description). The
# SPK-1 branches are every hook-enforced branch in L3/L4; SPK-2/SPK-3 branch the non-hook levers.
BRANCH_MAP = {
    "userpromptsubmit_route":        ("SPK-1", "hook", "agent runs route_prompt.py + a run_state 'routed' precondition"),
    "posttooluse_observer":          ("SPK-1", "hook", "step docs instruct the agent to run workflow_state.py record"),
    "posttooluse_edit_deviations":   ("SPK-1", "hook", "step docs require a DEVIATIONS row before a baselined-file edit lands"),
    "posttooluse_pregenerate_guard": ("SPK-1", "hook", "steps/03-generate.md pre-generate recipe-fetch gate the agent must pass"),
    "pretooluse_skill_precedence":   ("SPK-1", "hook", "INITIATE.md mandates physicist-intake first; validate_run_state routed-check"),
    "stop_primary_d18":              ("SPK-1", "hook", "check-in docs require validate_run_state --rundir exit 0 before a deck/RESULT.md"),
    "stop_drive_d4":                 ("SPK-1", "hook", "workflow_state.py next + step-doc rule: no turn-end with next_required pending"),
    "stop_catch_d6":                 ("SPK-1", "hook", "step docs require open *.failure.json to be resolved before turn-end"),
    "stop_skill_coverage":           ("SPK-1", "hook", "step docs require the step's mandated skill in run_state.skills_invoked"),
    "stop_integrity_d5d9":           ("SPK-1", "hook", "figure-contract skill + inv_figure_contract_fulfilled at check-in"),
    "stop_detach_n6":                ("SPK-1", "hook", "run_state schema requires logfile+done_condition+next_action for a detached job"),
    "drive_completion_reinvoke":     ("SPK-2", "harness-reinvoke", "agent polls the logfile for the done_condition before turn-end"),
    "progress_reporter_30min":       ("SPK-3", "wake-primitive", "run_in_background sleep+echo re-invoke (SPK-2 path) as a timed wake"),
    "scheduled_wake":                ("SPK-3", "wake-primitive", "run_in_background sleep+echo re-invoke (SPK-2 path)"),
}


def _load_spike_decisions(spikes_dir):
    out = {}
    for s in SPIKES:
        p = os.path.join(spikes_dir, f"{s}.json")
        try:
            art = json.load(open(p))
            out[s] = {"verdict": art.get("verdict", "unproven"), "decision": art.get("decision", "")}
        except (ValueError, OSError):
            out[s] = {"verdict": "unproven", "decision": ""}
    return out


def build_primacy(spike_decisions, timestamp=None):
    branches = {}
    for name, (gov, hook_primary, fallback) in sorted(BRANCH_MAP.items()):
        passed = spike_decisions.get(gov, {}).get("verdict") == "PASS"
        branches[name] = {"governed_by": gov, "primary": hook_primary if passed else "fallback",
                          "fallback": fallback}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _resolve_timestamp(timestamp),
        "generator": GENERATOR,
        "generated_by": GENERATOR,
        "input_fingerprint": _fingerprint(spike_decisions),
        "spikes": spike_decisions,
        "branches": branches,
    }


def check_primacy(path, as_json=False):
    if not os.path.isfile(path):
        print(f"spike_probe: not a file: {path}", file=sys.stderr)
        return 2
    try:
        doc = json.load(open(path))
    except (ValueError, OSError) as e:
        print(f"spike_probe: malformed HOOK-PRIMACY.json: {e}", file=sys.stderr)
        return 3
    for k in ("schema_version", "spikes", "branches", "input_fingerprint"):
        if k not in doc:
            print(f"spike_probe: HOOK-PRIMACY.json missing key {k!r}", file=sys.stderr)
            return 3
    spikes = doc["spikes"]
    if _fingerprint(spikes) != doc["input_fingerprint"]:
        print("spike_probe: input_fingerprint does not recompute from spikes (tampered)", file=sys.stderr)
        return 3
    errs = []
    for name, br in doc["branches"].items():
        gov = br.get("governed_by")
        if gov not in SPIKES:
            errs.append(f"branch {name}: unknown governing spike {gov!r}")
            continue
        passed = spikes.get(gov, {}).get("verdict") == "PASS"
        prim = br.get("primary")
        if passed and prim == "fallback":
            errs.append(f"branch {name}: governing {gov} PASSed but primary=fallback")
        if (not passed) and prim != "fallback":
            errs.append(f"branch {name}: governing {gov} not PASS but primary={prim!r} (must be fallback)")
    result = {"branches": len(doc["branches"]), "errors": errs, "exit": 0 if not errs else 1}
    if as_json:
        print(json.dumps(result, indent=2))
    elif errs:
        for e in errs:
            print(f"[check-primacy] FAIL: {e}")
    else:
        print(f"[check-primacy] OK: {len(doc['branches'])} branches consistent with the spike verdicts")
    return result["exit"]


# ---- CLI dispatch -------------------------------------------------------------------------------

def _print_human(record):
    print(f"[spike] {record['spike']}: verdict={record['verdict']} decision={record['decision']}")
    for c in record["checks"]:
        print(f"  [{'ok' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}")


def _load_text(path):
    with open(path, "r", errors="replace") as fh:
        return fh.read()


def cmd_record(spike, args):
    if spike == "SPK-1":
        if not (args.probe_log and args.transcript):
            print("spike_probe: SPK-1 --record needs --probe-log and --transcript", file=sys.stderr)
            return 2
        for p in (args.probe_log, args.transcript):
            if not os.path.isfile(p):
                print(f"spike_probe: not a file: {p}", file=sys.stderr)
                return 2
        evidence = {"probe_log": _load_text(args.probe_log), "transcript": _load_text(args.transcript)}
    else:
        if not args.evidence:
            print(f"spike_probe: {spike} --record needs --evidence <evidence.json>", file=sys.stderr)
            return 2
        if not os.path.isfile(args.evidence):
            print(f"spike_probe: not a file: {args.evidence}", file=sys.stderr)
            return 2
        try:
            evidence = json.load(open(args.evidence))
        except (ValueError, OSError) as e:
            print(f"spike_probe: malformed evidence JSON: {e}", file=sys.stderr)
            return 3
        if not isinstance(evidence, dict):
            print("spike_probe: evidence must be a JSON object", file=sys.stderr)
            return 3
    record = build_record(spike, evidence, timestamp=args.timestamp)
    if args.record:
        with open(args.record, "w") as fh:
            json.dump(record, fh, indent=2)      # no trailing newline (match shape_fit/pairing_check)
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        _print_human(record)
    return record["exit"]


def _check_artifact(spike, path, as_json=False):
    if not os.path.isfile(path):
        print(f"spike_probe: not a file: {path}", file=sys.stderr)
        return 2
    try:
        art = json.load(open(path))
    except (ValueError, OSError) as e:
        print(f"spike_probe: malformed artifact JSON: {e}", file=sys.stderr)
        return 3
    for k in ("spike", "verdict", "decision", "evidence", "input_fingerprint"):
        if k not in art:
            print(f"spike_probe: artifact missing key {k!r}", file=sys.stderr)
            return 3
    if art["spike"] != spike:
        print(f"spike_probe: artifact spike {art['spike']!r} != requested {spike!r}", file=sys.stderr)
        return 3
    recomputed = build_record(spike, art["evidence"], timestamp=art.get("generated_utc"))
    ok_fp = recomputed["input_fingerprint"] == art["input_fingerprint"]
    ok_verdict = recomputed["verdict"] == art["verdict"]
    ok_decision = recomputed["decision"] == art["decision"]
    consistent = ok_fp and ok_verdict and ok_decision
    if not consistent:
        code = 3
    elif art["verdict"] != "PASS":
        code = 1
    else:
        code = 0
    result = {"spike": spike, "verdict": art["verdict"], "decision": art["decision"],
              "fingerprint_matches": ok_fp, "verdict_recomputes": ok_verdict,
              "decision_recomputes": ok_decision, "consistent": consistent, "exit": code}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"[check] {spike}: verdict={art['verdict']} decision={art['decision']} "
              f"consistent={consistent} -> exit {code}")
    return code


def new_token():
    print("SPK-" + uuid.uuid4().hex[:12])
    return 0


def selftest():
    fails = []

    def _case(label, ok):
        print(f"[selftest] {label}: {'ok' if ok else '  FAIL'}")
        if not ok:
            fails.append(label)

    # -- SPK-1
    log_ok = "USERPROMPTSUBMIT 1\nPOSTTOOLUSE 1\nSTOP 1\nSTOP 2\n"
    r = build_record("SPK-1", {"probe_log": log_ok, "transcript": "...SPK1-STOP-BLOCK..."})
    _case("SPK-1 full-fire -> PASS/hook-primary/exit0",
          r["verdict"] == "PASS" and r["decision"] == "hook-primary" and r["exit"] == 0)
    r = build_record("SPK-1", {"probe_log": "USERPROMPTSUBMIT 1\nSTOP 1\nSTOP 2\n",
                               "transcript": "SPK1-STOP-BLOCK"})
    _case("SPK-1 missing PostToolUse -> unproven/fallback-primary/exit1",
          r["verdict"] == "unproven" and r["decision"] == "fallback-primary" and r["exit"] == 1)
    r = build_record("SPK-1", {"probe_log": "USERPROMPTSUBMIT 1\nPOSTTOOLUSE 1\nSTOP 1\n",
                               "transcript": "SPK1-STOP-BLOCK"})
    _case("SPK-1 single STOP (no block/release) -> unproven/exit1",
          r["verdict"] == "unproven" and r["exit"] == 1)
    r = build_record("SPK-1", {"probe_log": log_ok, "transcript": "no reason fed back"})
    _case("SPK-1 reason-not-fed-back -> unproven/exit1",
          r["verdict"] == "unproven" and r["exit"] == 1)

    # -- SPK-2
    tok = "SPK-abc123def456"
    r = build_record("SPK-2", {"token": tok, "launch_cmd": f"sleep 20; echo {tok}",
                               "reinvoke_text": f"background job done: {tok}"})
    _case("SPK-2 token round-trips -> PASS/harness-reinvoke-primary/exit0",
          r["verdict"] == "PASS" and r["decision"] == "harness-reinvoke-primary" and r["exit"] == 0)
    r = build_record("SPK-2", {"token": tok, "launch_cmd": f"sleep 20; echo {tok}",
                               "reinvoke_text": "job finished (no stdout captured)"})
    _case("SPK-2 token missing from re-invoke -> unproven/poll-fallback-primary/exit1",
          r["verdict"] == "unproven" and r["decision"] == "poll-fallback-primary" and r["exit"] == 1)

    # -- SPK-3
    r = build_record("SPK-3", {"mechanism": "ScheduleWakeup", "scheduled_utc": "2026-07-09T00:02:00Z",
                               "fired_utc": "2026-07-09T00:02:07Z", "tolerance_s": 30})
    _case("SPK-3 within tolerance -> PASS/wake-primitive-primary/exit0",
          r["verdict"] == "PASS" and r["decision"] == "wake-primitive-primary" and r["exit"] == 0)
    r = build_record("SPK-3", {"mechanism": "ScheduleWakeup", "scheduled_utc": "2026-07-09T00:02:00Z",
                               "fired_utc": "2026-07-09T00:20:00Z", "tolerance_s": 30})
    _case("SPK-3 outside tolerance -> unproven/bg-sleep-reinvoke-fallback/exit1",
          r["verdict"] == "unproven" and r["decision"] == "bg-sleep-reinvoke-fallback" and r["exit"] == 1)

    # -- record/--check round-trip + tamper rejection
    with tempfile.TemporaryDirectory(prefix="spike_probe_selftest_") as td:
        art = build_record("SPK-2", {"token": tok, "launch_cmd": f"echo {tok}", "reinvoke_text": tok})
        p = os.path.join(td, "SPK-2.json")
        json.dump(art, open(p, "w"), indent=2)
        _case("SPK-2 recorded PASS re-checks green (exit 0)", _check_artifact("SPK-2", p) == 0)
        tampered = dict(art)
        tampered["evidence"] = {"token": tok, "launch_cmd": "echo x", "reinvoke_text": "x"}
        p2 = os.path.join(td, "SPK-2-tampered.json")
        json.dump(tampered, open(p2, "w"), indent=2)
        _case("SPK-2 fingerprint-tampered artifact rejected (exit 3)", _check_artifact("SPK-2", p2) == 3)

    # -- primacy synthesis + consistency
    allpass = {"SPK-1": {"verdict": "PASS", "decision": "hook-primary"},
               "SPK-2": {"verdict": "PASS", "decision": "harness-reinvoke-primary"},
               "SPK-3": {"verdict": "PASS", "decision": "wake-primitive-primary"}}
    doc = build_primacy(allpass)
    _case("primacy all-PASS -> no fallback-primary SPK-1 branches",
          all(b["primary"] != "fallback" for b in doc["branches"].values() if b["governed_by"] == "SPK-1"))
    spk1fail = dict(allpass); spk1fail["SPK-1"] = {"verdict": "unproven", "decision": "fallback-primary"}
    doc2 = build_primacy(spk1fail)
    _case("primacy SPK-1 FAIL -> all SPK-1 branches fallback-primary",
          all(b["primary"] == "fallback" for b in doc2["branches"].values() if b["governed_by"] == "SPK-1"))
    with tempfile.TemporaryDirectory(prefix="spike_probe_primacy_") as td:
        pg = os.path.join(td, "HOOK-PRIMACY.json")
        json.dump(doc, open(pg, "w"), indent=2)
        _case("check-primacy consistent doc -> exit 0", check_primacy(pg) == 0)
        bad = dict(doc); bad["branches"] = {k: dict(v) for k, v in doc["branches"].items()}
        some = next(n for n, b in bad["branches"].items() if b["governed_by"] == "SPK-1")
        bad["branches"][some]["primary"] = "fallback"     # inconsistent: SPK-1 PASSed
        pb = os.path.join(td, "HOOK-PRIMACY-bad.json")
        json.dump(bad, open(pb, "w"), indent=2)
        _case("check-primacy inconsistent branch -> exit 1", check_primacy(pb) == 1)

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("spike_probe selftest: PASS (14 case(s) judged correctly.)")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spike", choices=SPIKES)
    ap.add_argument("--probe-log")
    ap.add_argument("--transcript")
    ap.add_argument("--evidence")
    ap.add_argument("--record")
    ap.add_argument("--check")
    ap.add_argument("--primacy", action="store_true")
    ap.add_argument("--spikes-dir")
    ap.add_argument("--out")
    ap.add_argument("--check-primacy")
    ap.add_argument("--timestamp")
    ap.add_argument("--new-token", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.new_token:
        return new_token()
    if args.check_primacy:
        return check_primacy(args.check_primacy, args.json)
    if args.primacy:
        spikes_dir = args.spikes_dir or os.path.join(HERE, "spikes")
        doc = build_primacy(_load_spike_decisions(spikes_dir), timestamp=args.timestamp)
        if args.out:
            with open(args.out, "w") as fh:
                json.dump(doc, fh, indent=2)
        if args.json:
            print(json.dumps(doc, indent=2))
        else:
            nfb = sum(1 for b in doc["branches"].values() if b["primary"] == "fallback")
            print(f"[primacy] {nfb} fallback-primary / {len(doc['branches'])} branches from {spikes_dir}")
        return 0
    if not args.spike:
        print(__doc__, file=sys.stderr)
        return 2
    if args.check:
        return _check_artifact(args.spike, args.check, args.json)
    return cmd_record(args.spike, args)


if __name__ == "__main__":
    sys.exit(main())
