#!/usr/bin/env python3
"""validate_parameters -- the D10 PARAMETER-VALIDATION contract.  stdlib-only, fail-loud.

Owns <rundir>/inputs/validations.json (schema_version 1): the obligations a run must DISCHARGE
(status PENDING -> PASS) before a scan's varied physics reaches long compute. Subcommands:
  emit    create/refresh validations.json: a PENDING obligation per named --param, AND an
          auto-emitted trap_obligation for each of T3/T6/T7/T8 hit in inputs/trap_sweep.json.
  record  set one obligation's status to PASS/FAIL with evidence (PASS is EARNED, never a default).
  check   GATE: exit 1 if any varied-param/trap obligation is not PASS; exit 0 if all PASS.
Exit codes: 0 PASS * 1 domain FAIL (a not-PASS obligation / missing manifest on check) *
2 usage/not-a-dir * 3 domain-specific-invalid (unparseable validations.json).
"""
import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SCHEMA_VERSION = 1
GATED_TRAPS = ("T3", "T6", "T7", "T8")
# The validation each gated trap demands (mirrors the judgment-protocols T-catalogue T3/T6/T7/T8).
TRAP_VALIDATION_CHECKS = {
    "T3": "per-point spectrum + sigma*BR re-weight + A*e revalidation (simplified-model purity holds "
          "at every scanned point)",
    "T6": "ME/PS/ISR treatment declared + run-card jet cuts audited vs the anchor sigma "
          "(compressed-spectrum acceptance)",
    "T7": "every HV/dark-shower parameter sourced-or-flagged + a truth-level validation vs a "
          "published gen-level distribution before detector sim",
    "T8": "per-width generation with acceptance recomputed per width (no narrow-template rescaling)",
}
ROLES = ("varied", "fixed")


def _die(msg, code=2):
    print(f"validate_parameters: {msg}", file=sys.stderr)
    return code


def _resolve_timestamp(cli_timestamp=None):
    if cli_timestamp:
        return cli_timestamp
    return os.environ.get("VALIDATE_PARAMETERS_UTC", "")


def _contract_path(rundir):
    for rel in ("inputs/task_contract.json", "task_contract.json"):
        p = os.path.join(rundir, rel)
        if os.path.isfile(p):
            return p
    return None


def _fingerprint(rundir):
    p = _contract_path(rundir)
    if not p:
        return ""
    try:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


def validations_path(rundir):
    return os.path.join(os.path.abspath(rundir), "inputs", "validations.json")


def load_validations(rundir, must_exist=False):
    path = validations_path(rundir)
    if not os.path.isfile(path):
        if must_exist:
            return None, f"no validations.json at {path} -- run `validate_parameters.py emit` first"
        return {"schema_version": SCHEMA_VERSION, "generated_utc": "",
                "generator": "validate_parameters.py", "generated_by": "validate_parameters.py",
                "input_fingerprint": "", "params": []}, None
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        return None, f"{path} is not valid JSON: {e}"
    if doc.get("schema_version") != SCHEMA_VERSION:
        return None, f"{path} schema_version {doc.get('schema_version')!r} != {SCHEMA_VERSION}"
    if not isinstance(doc.get("params"), list):
        return None, f"{path} carries no 'params' list"
    return doc, None


def save_validations(rundir, doc, timestamp=None):
    doc["schema_version"] = SCHEMA_VERSION
    doc["generator"] = "validate_parameters.py"
    doc["generated_by"] = "validate_parameters.py"
    doc["generated_utc"] = _resolve_timestamp(timestamp)
    doc["input_fingerprint"] = _fingerprint(rundir)
    path = validations_path(rundir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=2)   # NO trailing newline -- match shape_fit/pairing_check (§B)
    return path


def _find(doc, name, trap=None):
    for p in doc["params"]:
        if trap is not None and p.get("trap") == trap:
            return p
        if trap is None and p.get("name") == name and not p.get("trap"):
            return p
    return None


def _obligation(name, kind, role, trap, check):
    return {"name": name, "kind": kind, "role": role, "trap": trap, "check": check,
            "status": "PENDING", "expected": None, "observed": None, "evidence": None, "utc": ""}


def _trap_sweep_hits(rundir):
    for rel in ("inputs/trap_sweep.json", "trap_sweep.json"):
        p = os.path.join(rundir, rel)
        if os.path.isfile(p):
            try:
                with open(p) as fh:
                    doc = json.load(fh)
            except (OSError, json.JSONDecodeError):
                return set()
            ids = set()
            for h in (doc.get("traps_hit") or []):
                if isinstance(h, str):
                    ids.add(h)
                elif isinstance(h, dict) and h.get("id"):
                    ids.add(h["id"])
            return ids
    return set()


def cmd_emit(args):
    if not os.path.isdir(args.rundir):
        return _die(f"not a directory: {args.rundir}")
    doc, err = load_validations(args.rundir)
    if err:
        return _die(err, 3)
    added = []
    for spec in (args.param or []):
        name, _, role = spec.partition(":")
        role = role or "varied"
        if role not in ROLES:
            return _die(f"--param role must be one of {ROLES}, got {role!r}")
        if _find(doc, name):
            continue
        doc["params"].append(_obligation(name, "param_validation", role, None,
                                          "physics value validated before it reaches the scan grid"))
        added.append(name)
    hits = _trap_sweep_hits(args.rundir)
    for trap in GATED_TRAPS:
        if trap in hits and not _find(doc, trap, trap=trap):
            doc["params"].append(_obligation(trap, "trap_obligation", "varied", trap,
                                              TRAP_VALIDATION_CHECKS[trap]))
            added.append(trap)
    path = save_validations(args.rundir, doc, args.timestamp)
    not_pass = sum(1 for p in doc["params"] if p["status"] != "PASS")
    print(f"validations.json -> {path}  ({len(added)} added: {', '.join(added) or 'none'}; "
          f"{len(doc['params'])} total, {not_pass} not-yet-PASS)")
    return 0


def cmd_record(args):
    if not os.path.isdir(args.rundir):
        return _die(f"not a directory: {args.rundir}")
    if args.status not in ("PASS", "FAIL"):
        return _die("--status must be PASS or FAIL", 1)
    if args.status == "PASS" and not args.evidence:
        return _die("recording PASS requires --evidence (a PASS is EARNED, never asserted bare)", 1)
    doc, err = load_validations(args.rundir, must_exist=True)
    if err:
        return _die(err, 1)
    tgt = _find(doc, args.param, trap=args.param if args.param in GATED_TRAPS else None)
    if tgt is None:
        return _die(f"no obligation named {args.param!r} in validations.json -- `emit` it first", 1)
    tgt["status"] = args.status
    tgt["expected"] = args.expected
    tgt["observed"] = args.observed
    tgt["evidence"] = args.evidence
    tgt["utc"] = _resolve_timestamp(args.timestamp)
    if args.check:
        tgt["check"] = args.check
    save_validations(args.rundir, doc, args.timestamp)
    print(f"recorded {args.param}: {args.status}" + (f"  ({args.evidence})" if args.evidence else ""))
    return 0


def cmd_check(args):
    if not os.path.isdir(args.rundir):
        return _die(f"not a directory: {args.rundir}")
    doc, err = load_validations(args.rundir, must_exist=True)
    if err:
        return _die(err, 1)
    obligations = [p for p in doc["params"] if p.get("role") == "varied" or p.get("trap")]
    if not obligations:
        if args.require_nonempty:
            print("PARAMETER VALIDATION EMPTY: no varied-param/trap obligation recorded before a "
                  "scan ships", file=sys.stderr)
            return 1
        print("validate_parameters: no varied-param/trap obligations recorded -- nothing to gate")
        return 0
    not_pass = [f"{p['name']}={p['status']}" for p in obligations if p.get("status") != "PASS"]
    if not_pass:
        print("PARAMETER VALIDATION INCOMPLETE: " + ", ".join(not_pass), file=sys.stderr)
        return 1
    print(f"parameter validation PASS: {len(obligations)} obligation(s) all PASS")
    return 0


def _selftest():
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory(prefix="validate_parameters_selftest_") as td:
        rd = os.path.join(td, "run")
        os.makedirs(os.path.join(rd, "inputs"))
        with open(os.path.join(rd, "inputs", "task_contract.json"), "w") as fh:
            json.dump({"task_mode": "scan"}, fh)
        with open(os.path.join(rd, "inputs", "trap_sweep.json"), "w") as fh:
            json.dump({"schema_version": 1, "traps_hit": ["T6", "T8", "T1"]}, fh)
        ns = lambda **k: argparse.Namespace(**k)

        rc = cmd_emit(ns(rundir=rd, param=["m_slepton:varied"], timestamp="X"))
        doc, _ = load_validations(rd, must_exist=True)
        names = {p["name"] for p in doc["params"]}
        ok1 = rc == 0 and {"m_slepton", "T6", "T8"} <= names and "T1" not in names \
            and doc.get("generated_by") == "validate_parameters.py" and "input_fingerprint" in doc
        print(f"[selftest] 1 emit seeds varied param + gated traps (T6,T8) not T1 + provenance: "
              f"{sorted(names)}  {'ok' if ok1 else 'FAIL'}")
        if not ok1:
            fails.append("emit did not seed the expected obligations/provenance")

        ok2 = cmd_check(ns(rundir=rd, require_nonempty=True)) == 1
        print(f"[selftest] 2 check on all-PENDING -> exit 1  {'ok' if ok2 else 'FAIL'}")
        if not ok2:
            fails.append("check did not FAIL while obligations PENDING")

        rc_bare = cmd_record(ns(rundir=rd, param="m_slepton", status="PASS", evidence=None,
                                expected=None, observed=None, check=None, timestamp="X"))
        ok3 = rc_bare == 1
        print(f"[selftest] 3 record PASS without --evidence refused -> exit 1  {'ok' if ok3 else 'FAIL'}")
        if not ok3:
            fails.append("bare PASS (no evidence) was accepted")

        for nm in ("m_slepton", "T6", "T8"):
            cmd_record(ns(rundir=rd, param=nm, status="PASS", evidence="checked", expected="e",
                          observed="o", check=None, timestamp="X"))
        ok4 = cmd_check(ns(rundir=rd, require_nonempty=True)) == 0
        print(f"[selftest] 4 check after all PASS -> exit 0  {'ok' if ok4 else 'FAIL'}")
        if not ok4:
            fails.append("check did not PASS after all obligations PASS")

        cmd_record(ns(rundir=rd, param="T8", status="FAIL", evidence="mismatch", expected="e",
                      observed="o", check=None, timestamp="X"))
        ok5 = cmd_check(ns(rundir=rd, require_nonempty=True)) == 1
        print(f"[selftest] 5 a FAIL record re-blocks the gate -> exit 1  {'ok' if ok5 else 'FAIL'}")
        if not ok5:
            fails.append("check did not FAIL after a FAIL record")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("validate_parameters selftest: 5 case(s) judged correctly.")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return _selftest()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("emit", help="create/refresh validations.json + auto-emit T3/T6/T7/T8 obligations")
    pe.add_argument("--rundir", required=True)
    pe.add_argument("--param", action="append", metavar="NAME[:varied|fixed]",
                    help="a varied (default) or fixed parameter to validate (repeatable)")
    pe.add_argument("--timestamp")
    pe.set_defaults(fn=cmd_emit)

    pr = sub.add_parser("record", help="set an obligation's status to PASS/FAIL with evidence")
    pr.add_argument("--rundir", required=True)
    pr.add_argument("--param", required=True)
    pr.add_argument("--status", required=True, choices=("PASS", "FAIL"))
    pr.add_argument("--check")
    pr.add_argument("--expected")
    pr.add_argument("--observed")
    pr.add_argument("--evidence")
    pr.add_argument("--timestamp")
    pr.set_defaults(fn=cmd_record)

    pc = sub.add_parser("check", help="gate: exit 1 unless every varied/trap obligation is PASS")
    pc.add_argument("--rundir", required=True)
    pc.add_argument("--require-nonempty", action="store_true",
                    help="treat an empty obligation set as FAIL (a scan must validate SOMETHING)")
    pc.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
