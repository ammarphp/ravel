#!/usr/bin/env python3
"""sr_plausibility.py -- analysis->statistics plausibility gate (D14).  stdlib-only, fail-loud.
Reads outputs/sr_yields.json + outputs/pyhf_exclusion/exclusion.json and EMITS
outputs/sr_plausibility.json with an EARNED verdict in {plausible, implausible} (NEVER defaults to
plausible). Checks: >=1 non-trivial SR (some signal); mu95_obs finite & off the floor/ceiling;
excluded_obs == (mu95_obs < 1.0); driving-SR acc*eff in band (only when --sigma-ref-fb + --lumi-fb
given -- catches the '956% acc*eff' defect class).
Usage:  sr_plausibility.py --rundir <dir> [--sigma-ref-fb F --lumi-fb F] [--out P] [--timestamp T] [--json]
        sr_plausibility.py --selftest
Exit:   0 plausible * 1 implausible * 2 usage/IO/not-a-dir * 3 required input missing/invalid
"""
import argparse
import hashlib
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SCHEMA_VERSION = 1
MU95_FLOOR = 1e-3          # below this, mu95 is a degenerate floor (would exclude everything)
MU95_CEIL = 1e6            # above this, mu95 is a runaway/degenerate sentinel
ACCXEFF_CEIL = 1.0         # acc*eff is a fraction in (0,1]; >1 is unphysical (the '956%' defect)
INPUT_RELS = ("outputs/sr_yields.json", "outputs/pyhf_exclusion/exclusion.json")


def _resolve_timestamp(cli_timestamp=None):
    if cli_timestamp:
        return cli_timestamp
    return os.environ.get("SR_PLAUSIBILITY_UTC", "")


def _canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_input_fingerprint(rundir, input_rels=INPUT_RELS):
    """sha256 over the canonical JSON of the consumed inputs, in fixed order -- the SAME p4a-local
    formula validate_run_state.recompute_input_fingerprint uses to detect a backfill. This is a
    plausibility-domain canonicalization, deliberately SEPARATE from p1's provenance.py fingerprint
    (D-7): sr_plausibility.json is not a provenance.py-verified artifact."""
    h = hashlib.sha256()
    for rel in input_rels:
        with open(os.path.join(rundir, rel)) as fh:
            h.update(_canonical_bytes(json.load(fh)))
        h.update(b"\x00")
    return h.hexdigest()


def _normalize_sr(name):
    return name.split("[", 1)[1].rstrip("]") if "[" in name else name


def assess(sr_yields, exclusion, sigma_ref_fb=None, lumi_fb=None):
    """Return (verdict, checks, summary). verdict='plausible' only if EVERY check passes."""
    checks = []
    nontrivial = [r for r in sr_yields if isinstance(r, dict)
                  and isinstance(r.get("s"), (int, float)) and float(r["s"]) > 0.0]
    checks.append({"name": "nontrivial-sr", "ok": len(nontrivial) >= 1,
                   "detail": f"{len(nontrivial)} SR(s) carry signal>0 of {len(sr_yields)}"})

    mu = exclusion.get("obs_limit")
    ok_mu = isinstance(mu, (int, float)) and math.isfinite(mu) and (MU95_FLOOR < float(mu) < MU95_CEIL)
    checks.append({"name": "mu95-in-band", "ok": ok_mu,
                   "detail": f"mu95_obs={mu} (band {MU95_FLOOR}..{MU95_CEIL})"})

    excluded_obs = (float(mu) < 1.0) if isinstance(mu, (int, float)) and math.isfinite(mu) else None
    stored = exclusion.get("excluded_obs")
    ok_excl = (stored is None) or (excluded_obs is not None and bool(stored) == excluded_obs)
    checks.append({"name": "excluded-obs-consistent", "ok": ok_excl,
                   "detail": f"stored={stored} vs computed(mu95<1)={excluded_obs}"})

    driving = _normalize_sr(exclusion.get("best_sr") or "")
    accxeff = None
    if sigma_ref_fb and lumi_fb:
        drow = next((r for r in sr_yields if _normalize_sr(r.get("name", "")) == driving), None)
        s = drow.get("s") if isinstance(drow, dict) else None
        if isinstance(s, (int, float)) and float(sigma_ref_fb) > 0 and float(lumi_fb) > 0:
            accxeff = float(s) / (float(sigma_ref_fb) * float(lumi_fb))
            ok_ae = 0.0 < accxeff <= ACCXEFF_CEIL
        else:
            ok_ae = False
        checks.append({"name": "driving-accxeff-in-band", "ok": ok_ae,
                       "detail": f"driving={driving!r} accxeff={accxeff} (0<accxeff<={ACCXEFF_CEIL})"})

    verdict = "plausible" if all(c["ok"] for c in checks) else "implausible"
    summary = {"n_srs": len(sr_yields), "n_nontrivial_srs": len(nontrivial),
               "driving_sr": driving or None, "driving_accxeff": accxeff,
               "mu95_obs": mu, "excluded_obs": excluded_obs}
    return verdict, checks, summary


def write_sr_plausibility_json(out_path, *, rundir, sr_yields, exclusion, sigma_ref_fb, lumi_fb, timestamp):
    verdict, checks, summary = assess(sr_yields, exclusion, sigma_ref_fb, lumi_fb)
    record = {"schema_version": SCHEMA_VERSION, "generated_utc": timestamp,
              "generator": "sr_plausibility.py", "generated_by": "sr_plausibility.py",
              "input_fingerprint": compute_input_fingerprint(rundir), "verdict": verdict,
              "reasons": [f"{c['name']}: {c['detail']}" for c in checks if not c["ok"]], "checks": checks}
    record.update(summary)
    outdir = os.path.dirname(os.path.abspath(out_path))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(record, fh, indent=2)
    return record


def _load(rundir, rel):
    with open(os.path.join(rundir, rel)) as fh:
        return json.load(fh)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir")
    ap.add_argument("--out", default=None)
    ap.add_argument("--sigma-ref-fb", type=float, default=None)
    ap.add_argument("--lumi-fb", type=float, default=None)
    ap.add_argument("--timestamp", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.rundir:
        print(__doc__, file=sys.stderr)
        return 2
    if not os.path.isdir(args.rundir):
        print(f"sr_plausibility: not a directory: {args.rundir}", file=sys.stderr)
        return 2
    try:
        sr_yields = _load(args.rundir, INPUT_RELS[0])
        exclusion = _load(args.rundir, INPUT_RELS[1])
    except (OSError, json.JSONDecodeError) as e:
        print(f"sr_plausibility: cannot read required inputs: {e}", file=sys.stderr)
        return 3
    if not isinstance(sr_yields, list) or not sr_yields:
        print("sr_plausibility: sr_yields.json must be a non-empty array", file=sys.stderr)
        return 3
    if not isinstance(exclusion, dict):
        print("sr_plausibility: exclusion.json must be an object", file=sys.stderr)
        return 3
    out = args.out or os.path.join(args.rundir, "outputs", "sr_plausibility.json")
    rec = write_sr_plausibility_json(out, rundir=args.rundir, sr_yields=sr_yields, exclusion=exclusion,
                                     sigma_ref_fb=args.sigma_ref_fb, lumi_fb=args.lumi_fb,
                                     timestamp=_resolve_timestamp(args.timestamp))
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        print(f"wrote {out}  verdict={rec['verdict']}"
              + ("" if rec["verdict"] == "plausible" else "  reasons: " + "; ".join(rec["reasons"])))
    return 0 if rec["verdict"] == "plausible" else 1


def selftest():
    fails = []
    with tempfile.TemporaryDirectory(prefix="sr_plausibility_selftest_") as td:
        rd = os.path.join(td, "bad")
        os.makedirs(os.path.join(rd, "outputs", "pyhf_exclusion"))
        json.dump([{"name": "SR1", "n": 0, "b": 0.0, "db": 0.0, "s": 0.0}],
                  open(os.path.join(rd, "outputs", "sr_yields.json"), "w"))
        json.dump({"obs_limit": 1e9, "exp_limits": [1, 1, 1, 1, 1], "per_sr": {}, "best_sr": "SR1"},
                  open(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"), "w"))
        rc = main(["--rundir", rd])
        rec = json.load(open(os.path.join(rd, "outputs", "sr_plausibility.json")))
        ok1 = (rc == 1 and rec["verdict"] == "implausible" and rec["generated_by"] == "sr_plausibility.py")
        print(f"[selftest] 1 all-zero yields + runaway mu95 -> implausible (exit 1)  {'ok' if ok1 else 'FAIL'}")
        if not ok1:
            fails.append("all-zero fixture should be implausible with exit 1")

        rg = os.path.join(td, "good")
        os.makedirs(os.path.join(rg, "outputs", "pyhf_exclusion"))
        json.dump([{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0},
                   {"name": "SR2", "n": 2, "b": 2.0, "db": 0.5, "s": 0.0}],
                  open(os.path.join(rg, "outputs", "sr_yields.json"), "w"))
        json.dump({"obs_limit": 0.7, "exp_limits": [0.4, 0.55, 0.7, 0.95, 1.3], "per_sr": {},
                   "best_sr": "SR1", "excluded_obs": True},
                  open(os.path.join(rg, "outputs", "pyhf_exclusion", "exclusion.json"), "w"))
        rc = main(["--rundir", rg])
        rec2 = json.load(open(os.path.join(rg, "outputs", "sr_plausibility.json")))
        ok2 = (rc == 0 and rec2["verdict"] == "plausible"
               and rec2["input_fingerprint"] == compute_input_fingerprint(rg)
               and rec2["excluded_obs"] is True)
        print(f"[selftest] 2 healthy yields + in-band mu95 -> plausible (exit 0)  {'ok' if ok2 else 'FAIL'}")
        if not ok2:
            fails.append("healthy fixture should be plausible with a matching input_fingerprint")

        rc = main(["--rundir", rg, "--sigma-ref-fb", "0.001", "--lumi-fb", "1.0",
                   "--out", os.path.join(rg, "outputs", "sr_plausibility_ae.json")])
        rec3 = json.load(open(os.path.join(rg, "outputs", "sr_plausibility_ae.json")))
        ok3 = (rc == 1 and rec3["verdict"] == "implausible"
               and rec3["driving_accxeff"] is not None and rec3["driving_accxeff"] > ACCXEFF_CEIL)
        print(f"[selftest] 3 driving acc*eff > 1 (the 956% defect) -> implausible  {'ok' if ok3 else 'FAIL'}")
        if not ok3:
            fails.append("acc*eff>1 should be implausible")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("sr_plausibility selftest: 3 case(s) judged correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
