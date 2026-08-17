#!/usr/bin/env python
"""Turn a Rivet routine's bundled REF data + a signal YODA into per-SR counting
inputs (observed, background+-unc, signal) for pyhf_exclude.py.

Rivet search routines bundle the published HEPData distributions under /REF/ --
typically y01 = observed data, y02 = total SM background (with its uncertainty).
A signal region is "m_eff > threshold", so the SR's observed and background
counts are the integral of those distributions above the threshold. The signal
yield is the routine's own SR counter (already scaled to the analysis luminosity).

This step is necessarily routine-aware (which REF table maps to which SR, and the
SR's threshold) -- that mapping is the [Opus] input, passed in as a small JSON
spec read from the routine's .cc (book(...) table indices + the SR cuts).

Spec JSON:
  {"routine": "ATLAS_2016_I1458270", "data_y": "y01", "bkg_y": "y02",
   "signal_regions": [
     {"name": "2jl", "ref_table": "d04-x01", "threshold_gev": 1200, "counter": "2jl"}, ...]}

Background-uncertainty handling: the per-bin REF uncertainties are partially
correlated, so the quadrature sum understates the true inclusive-SR systematic.
We therefore floor the relative SR background uncertainty at --bkg-rel-floor
(default 0.15, a realistic correlated value for these regions) and report both the
quadrature and linear sums for transparency.

PREFERRED over the REF integration, when the analysis publishes per-SR CR-FITTED
backgrounds (its results table, e.g. arXiv:1605.03814 Table 6): pass them via
--fitted-bkg FITTED.json = {"<sr>": {"b": <fitted>, "db": <fitted unc>}, ...,
"_source": "<citation>"}. The fitted values then REPLACE the integrated b/db
(the analysis's own background estimate beats the pre-fit-MC REF integral, whose
quadrature sum understates correlated systematics on big SRs and can overstate
precision on small ones). Observed n and signal s are unaffected. The output
records which source was used per SR.

Hard guards (exit nonzero — these failure modes used to be silent):
  * CUTFLOW-ONLY routine: this tool needs scalar SR counters (`/routine/<counter>`).
    A routine that books only Cutflow/BinnedEstimate1D objects (e.g. recursive-jigsaw
    EWK searches) has none — its data path is the run-local cutflow adapter, NOT this
    script: see workflow/reference/example-rivet-ewk-path.md.
  * XCHECK enforcement: 'xcheck' (the signal m_eff integral above the spec threshold)
    must match 'signal_s' (the routine's SR counter) within --xcheck-tol (default 0.10)
    whenever both are finite and signal_s > 0. Divergence means the sr_spec threshold
    has drifted from the routine's actual cut, or the counter mapping is wrong.
  * REF background integral must be > 0 for every SR not overridden by --fitted-bkg
    (b<=0 means the threshold is beyond the REF range or the ref_table is wrong).

Known approximation (documented, not fixed): REF uncertainties enter via errAvg(),
which symmetrises asymmetric published error bars; the quadrature sum additionally
treats per-bin errors as uncorrelated. Both are superseded wherever --fitted-bkg
provides the analysis's own b±db.

Usage:
  rivet_ref_yields.py --signal SIG.yoda --ref REF.yoda.gz --spec SPEC.json \
      --out SRS.json [--bkg-rel-floor 0.15] [--fitted-bkg FITTED.json] [--xcheck-tol 0.10]
"""
import argparse, json, math, sys
import yoda


def integ_above(obj, thr):
    """(sum of bin values, quadrature err, linear err) for bins with xMin >= thr."""
    s = q = lin = 0.0
    for b in obj.bins():
        if b.xMin() >= thr - 1e-6:
            s += b.val()
            try:
                e = b.errAvg()
            except Exception:
                e = 0.0  # signal distributions carry no error map; value-only sum
            q += e ** 2
            lin += abs(e)
    return s, math.sqrt(q), lin


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signal", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bkg-rel-floor", type=float, default=0.15)
    ap.add_argument("--fitted-bkg", help="JSON {'<sr>': {'b':..,'db':..}, '_source': cite} of "
                                         "published CR-fitted backgrounds; overrides REF b/db")
    ap.add_argument("--xcheck-tol", type=float, default=0.10,
                    help="max relative |xcheck/signal_s - 1| tolerated before erroring out "
                         "(threshold-drift / counter-mismatch guard; checked when both finite "
                         "and signal_s > 0)")
    args = ap.parse_args()

    fitted = json.load(open(args.fitted_bkg)) if args.fitted_bkg else {}
    fitted_source = fitted.get("_source", args.fitted_bkg)

    spec = json.load(open(args.spec))
    routine = spec["routine"]
    data_y = spec.get("data_y", "y01")
    bkg_y = spec.get("bkg_y", "y02")
    sig = yoda.read(args.signal)

    # --- cutflow-only / missing-counter guard (used to silently emit s=NaN) ---------------
    prefix = f"/{routine}/"
    scalar_keys = sorted(k for k, o in sig.items() if k.startswith(prefix) and hasattr(o, "val"))
    missing = [f"/{routine}/{sr['counter']}" for sr in spec["signal_regions"]
               if f"/{routine}/{sr['counter']}" not in sig
               or not hasattr(sig[f"/{routine}/{sr['counter']}"], "val")]
    if missing:
        binned = [k for k, o in sig.items() if k.startswith(prefix) and hasattr(o, "bins")]
        if not scalar_keys and binned:
            sys.exit(
                f"ERROR: {args.signal} has NO scalar SR counters under {prefix} but does have "
                f"{len(binned)} Cutflow/binned objects — this is a CUTFLOW-ONLY routine. Its per-SR "
                "yields come from the cutflow bins via the run-local adapter path, not from this "
                "script: see workflow/reference/example-rivet-ewk-path.md "
                f"(missing: {', '.join(missing)})")
        sys.exit(
            f"ERROR: requested SR counter(s) not in {args.signal}: {', '.join(missing)}.\n"
            f"Scalar keys available under {prefix}: {', '.join(scalar_keys) or '(none)'} — "
            "fix the spec 'counter' fields (read them from the routine .cc book() calls).")

    ref = yoda.read(args.ref)

    srs = []
    xcheck_fails = []
    print(f"{'SR':6s} {'thr':>5s} {'obs':>5s} {'bkg':>8s} {'dB_quad':>8s} {'dB_lin':>7s} "
          f"{'dB_used':>8s} {'signal_s':>9s} {'xcheck':>8s}")
    for sr in spec["signal_regions"]:
        thr = sr["threshold_gev"]
        rt = sr["ref_table"]
        # observed + background from the published REF distribution
        obs, _, _ = integ_above(ref[f"/REF/{routine}/{rt}-{data_y}"], thr)
        bkg, db_q, db_l = integ_above(ref[f"/REF/{routine}/{rt}-{bkg_y}"], thr)
        if bkg <= 0 and sr["name"] not in fitted:
            sys.exit(f"ERROR: REF background integral <= 0 for SR {sr['name']} "
                     f"(table {rt}-{bkg_y}, threshold {thr} GeV) — the threshold is beyond the "
                     "REF distribution's range or the ref_table mapping is wrong.")
        db = max(db_q, args.bkg_rel_floor * bkg)
        bkg_source = f"REF integral (floor {args.bkg_rel_floor:.0%})"
        if sr["name"] in fitted:
            bkg, db = float(fitted[sr["name"]]["b"]), float(fitted[sr["name"]]["db"])
            bkg_source = f"published CR-fit ({fitted_source})"
        # signal: the routine's SR counter (scaled to the analysis lumi)
        ckey = f"/{routine}/{sr['counter']}"
        s = sig[ckey].val() if ckey in sig else float("nan")
        # cross-check: integral of the signal m_eff distribution above threshold
        skey = f"/{routine}/{rt}-{data_y}"
        xcheck = integ_above(sig[skey], thr)[0] if skey in sig else float("nan")
        if math.isfinite(s) and s > 0 and math.isfinite(xcheck):
            rel = abs(xcheck / s - 1.0)
            if rel > args.xcheck_tol:
                xcheck_fails.append((sr["name"], s, xcheck, rel))
        print(f"{sr['name']:6s} {thr:5d} {obs:5.0f} {bkg:8.2f} {db_q:8.2f} {db_l:7.2f} "
              f"{db:8.2f} {s:9.2f} {xcheck:8.2f}")
        srs.append({"name": sr["name"], "n": round(obs), "b": round(bkg, 3),
                    "db": round(db, 3), "s": round(s, 4), "_bkg_source": bkg_source})

    if xcheck_fails:
        for name, s, xc, rel in xcheck_fails:
            print(f"XCHECK FAIL {name}: signal_s={s:.4g} vs m_eff-integral xcheck={xc:.4g} "
                  f"({rel:.1%} > tol {args.xcheck_tol:.0%})", file=sys.stderr)
        sys.exit("ERROR: xcheck/signal_s disagreement above --xcheck-tol — the sr_spec threshold "
                 "has drifted from the routine's cut, or the counter mapping is wrong. "
                 "No output written.")

    json.dump(srs, open(args.out, "w"), indent=2)
    print(f"\nwrote {args.out} ({len(srs)} SRs)")
    print("note: 'xcheck' (signal m_eff integral above threshold) should match 'signal_s' (SR counter); "
          f"enforced at {args.xcheck_tol:.0%}")


if __name__ == "__main__":
    main()
