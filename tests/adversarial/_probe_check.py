#!/usr/bin/env python3
"""_probe_check -- read-only re-verification of the recorded hook probes (SPK-1/2/3).

The recorded probes under tests/fixtures/hook-probes/ hold the evidence of three harness
behaviours that the workflow enforcement relies on, the verdict and decision derived from that
evidence, and a sha256 fingerprint of the evidence:

  SPK-1  hooks fire        Stop/PostToolUse/UserPromptSubmit each fire; Stop exit-2 blocks turn-end + feeds its reason back
  SPK-2  bg re-invocation  a harness run_in_background job's stdout re-invokes the agent on completion
  SPK-3  timed wake        a scheduled wake re-fires at ~the set time

This checker re-derives each verdict and decision from the recorded evidence and recomputes the
fingerprint, so an edited record fails; it also checks that hook-primacy.json assigns every
enforcement branch the primary its governing probe allows. It records nothing: recording a probe
needs a live agent harness. Gates G0a-G0c run it.

Usage:
  _probe_check.py --spike SPK-1 --check <record.json> [--json]
  _probe_check.py --check-primacy <hook-primacy.json> [--json]

Exit codes: 0 consistent PASS * 1 consistent not-PASS, or an inconsistent primacy branch *
2 usage / not a file * 3 malformed or inconsistent record
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

SPIKES = ("SPK-1", "SPK-2", "SPK-3")


def fingerprint(evidence):
    """sha256 over the canonical JSON of a probe's evidence (or of the primacy spike table)."""
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


# ---- per-probe verifiers: each returns (verdict, decision, checks). verdict defaults NON-passing. --

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


VERIFIERS = {"SPK-1": verify_spk1, "SPK-2": verify_spk2, "SPK-3": verify_spk3}


def derive(spike, evidence):
    """(verdict, decision, checks) re-derived from a probe's recorded evidence."""
    return VERIFIERS[spike](evidence)


def _fail(message, code):
    print(f"probe check: {message}", file=sys.stderr)
    return code


def check_record(spike, path, as_json=False):
    """Re-verify one recorded probe: its fingerprint, verdict and decision must recompute from its
    evidence. Exit 0 for a consistent PASS, 1 for a consistent not-PASS, 3 for a malformed or
    inconsistent record, 2 when the file is absent."""
    if not os.path.isfile(path):
        return _fail(f"not a file: {path}", 2)
    try:
        record = json.load(open(path, encoding="utf-8"))
    except (ValueError, OSError) as e:
        return _fail(f"malformed probe record JSON: {e}", 3)
    if not isinstance(record, dict):
        return _fail("a probe record must be a JSON object", 3)
    for k in ("spike", "verdict", "decision", "evidence", "input_fingerprint"):
        if k not in record:
            return _fail(f"probe record missing key {k!r}", 3)
    if record["spike"] != spike:
        return _fail(f"probe record spike {record['spike']!r} != requested {spike!r}", 3)
    if not isinstance(record["evidence"], dict):
        return _fail("probe record evidence must be a JSON object", 3)
    verdict, decision, _checks = derive(spike, record["evidence"])
    ok_fp = fingerprint(record["evidence"]) == record["input_fingerprint"]
    ok_verdict = verdict == record["verdict"]
    ok_decision = decision == record["decision"]
    consistent = ok_fp and ok_verdict and ok_decision
    if not consistent:
        code = 3
    elif record["verdict"] != "PASS":
        code = 1
    else:
        code = 0
    result = {"spike": spike, "verdict": record["verdict"], "decision": record["decision"],
              "fingerprint_matches": ok_fp, "verdict_recomputes": ok_verdict,
              "decision_recomputes": ok_decision, "consistent": consistent, "exit": code}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"[check] {spike}: verdict={record['verdict']} decision={record['decision']} "
              f"consistent={consistent} -> exit {code}")
    return code


def check_primacy(path, as_json=False):
    """hook-primacy.json: its fingerprint recomputes from its spike table, and every branch whose
    governing probe PASSed is hook-primary while every other branch is fallback-primary."""
    if not os.path.isfile(path):
        return _fail(f"not a file: {path}", 2)
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except (ValueError, OSError) as e:
        return _fail(f"malformed hook-primacy JSON: {e}", 3)
    for k in ("schema_version", "spikes", "branches", "input_fingerprint"):
        if not isinstance(doc, dict) or k not in doc:
            return _fail(f"hook-primacy record missing key {k!r}", 3)
    spikes = doc["spikes"]
    if fingerprint(spikes) != doc["input_fingerprint"]:
        return _fail("input_fingerprint does not recompute from spikes (edited record)", 3)
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spike", choices=SPIKES)
    ap.add_argument("--check")
    ap.add_argument("--check-primacy")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.check_primacy:
        return check_primacy(args.check_primacy, args.json)
    if not (args.spike and args.check):
        print(__doc__, file=sys.stderr)
        return 2
    return check_record(args.spike, args.check, args.json)


if __name__ == "__main__":
    sys.exit(main())
