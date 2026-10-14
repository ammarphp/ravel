#!/usr/bin/env python
"""Persist the final per-SR counting yields to a re-plottable YODA2 file (rivet env).

YODA is Rivet's native interchange/persistence format, but today the pipeline only
ever READS it (rivet_ref_yields.py, overlay_on_data.py). The per-SR counting yields
(sr_yields.json: observed n, SM background b +- db, expected signal s) live ONLY in
JSON -- they are never written back to YODA, so re-plotting the yield overlay or
handing a colleague the numbers means carrying around an ad-hoc JSON instead of the
experiment's native format. This step closes that gap: it serialises sr_yields.json
to a YODA2 file whose per-SR scalars round-trip exactly, re-readable with yoda.read
WITHOUT re-running MadGraph -> Pythia -> Rivet.

Object model (yoda 2.1.3, the NEW 2.x model -- Estimate0D + Counter, no v1 Scatter):
  per SR <name>, under /<label>/<name>/ :
    signal      Estimate0D  val = s   (no error in the JSON -> errorless)
    observed    Counter     sumW = n  (an integer event count; Counter is the
                                       natural YODA type for a raw observed count)
    background  Estimate0D  val = b, err = db  (set under source "stats", so
                                       .quadSum() returns (-db, +db) on read-back --
                                       matching how Rivet writes its own Estimate0D)
The signal Estimate0D mirrors the Rivet-written /<routine>/<SR> Estimate0D (same
type, same val), so a downstream reader can treat either source identically.

If a Rivet-written .yoda(.gz) is also passed (--histos), every Histo1D-family object
in it (Histo1D / BinnedHisto1D -- the cutflow CF-* and m_eff distributions) is cloned
through into the output, so the one file carries BOTH the final scalar yields and the
underlying histograms.

Usage:
  write_yoda.py --srs sr_yields.json --out yields.yoda [--label gluino] \
      [--histos gluino.yoda.gz]
  # gzip is chosen automatically when --out ends in .gz; yoda.read handles both.

Fail-loud guarantees (a physicist must never get a confident-but-wrong/blank file):
  * every n/b/db/s is checked with math.isfinite, and the JSON parser is told to
    REJECT NaN/Infinity tokens -- a non-finite scalar aborts naming the SR+field;
  * duplicate SR names are detected up front and abort (they would otherwise
    collide on the same YODA path and silently drop a row);
  * a non-integer observed n aborts (it is stored verbatim but printed rounded --
    we refuse to display one number and persist another);
  * SR names / label are validated so '/' or an empty token cannot mangle the path;
  * when --histos is given, at least one Histo1D-family object MUST be clonable
    (a truncated/corrupt .yoda.gz that yields zero is an error, not a silent skip).

Round-trip is self-checked at the end: the written file is read back, the object
count is asserted equal to what was written, and EVERY per-SR scalar (s, n, b, db)
is asserted equal to the input (exit nonzero on any mismatch).
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse
import json
import math
import sys


# error source label; matches how Rivet writes its per-SR Estimate0D (sources=['stats'])
# so .quadSum() / .errAvg("stats") behave identically on read-back.
ERR_SOURCE = "stats"


def estimate0d(path, val, err=None, title=None):
    """An Estimate0D at `path` with central value `val` and optional symmetric `err`.

    err is registered under ERR_SOURCE so .quadSum() returns (-err, +err) on read-back
    (the same convention as the Rivet-written per-SR Estimate0D). err=None -> errorless.
    """
    import yoda
    e = yoda.Estimate0D(path)
    if title is not None:
        e.setTitle(title)
    if err is None:
        e.setVal(val)
    else:
        e.set(val, err, ERR_SOURCE)
    return e


def counter(path, n, title=None):
    """A Counter at `path` carrying an integer event count `n` (sumW = numEntries = n)."""
    import yoda
    c = yoda.Counter(path)
    if title is not None:
        c.setTitle(title)
    c.set(n, n, n)  # (numEntries, sumW, sumW2) -- a unit-weight count of n events
    return c


def _forbid_nan(s):
    """json.load(parse_constant=...) hook: reject the NaN/Infinity/-Infinity tokens.

    Python's json accepts these non-standard tokens by default; a NaN/Inf yield
    would be written verbatim and slip past a naive self-check (inf == inf), so we
    refuse them at parse time before any SR is ever constructed.
    """
    sys.exit(f"ERROR: --srs JSON contains a forbidden token {s!r} "
             f"(NaN/Infinity are not valid yields).")


def _finite(val, field, name):
    """Coerce `val` to float, aborting (naming the SR + field) if it is not finite."""
    try:
        f = float(val)
    except (TypeError, ValueError):
        sys.exit(f"ERROR: SR {name!r} field {field!r} is not a number: {val!r}")
    if not math.isfinite(f):
        sys.exit(f"ERROR: SR {name!r} field {field!r} is not finite: {val!r}")
    return f


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--srs", required=True,
                    help="per-SR yields JSON (list of {name, n, b, db, s})")
    ap.add_argument("--out", required=True,
                    help="output YODA file (.yoda or .yoda.gz)")
    ap.add_argument("--label", default="yields",
                    help="top-level path label for the SR scalars (/<label>/<sr>/...)")
    ap.add_argument("--histos",
                    help="optional Rivet .yoda(.gz) whose Histo1D-family objects "
                         "(cutflows + m_eff distributions) are cloned through")
    args = ap.parse_args()
    import yoda

    # parse_constant forbids the non-standard NaN/Infinity tokens at parse time, so
    # a corrupt yield can never reach the YODA file (where inf==inf would mask it).
    rows = json.load(open(args.srs), parse_constant=_forbid_nan)
    if not isinstance(rows, list) or not rows:
        sys.exit(f"ERROR: {args.srs} is not a non-empty JSON list of SR dicts.")

    label = args.label.strip("/")
    if not label or "/" in label:
        sys.exit(f"ERROR: --label {args.label!r} is empty or contains '/' after "
                 f"trimming -- it would mangle the /<label>/<sr>/... YODA path.")

    aos = []
    seen = {}  # sanitized name -> source row index, to catch path collisions up front
    clean = []  # per-row validated (name, s, n, b, db) tuples for the self-check
    print(f"{'SR':6s} {'signal s':>10s} {'observed n':>11s} {'bkg b':>9s} {'db':>8s}")
    for i, r in enumerate(rows):
        for k in ("name", "n", "b", "db", "s"):
            if k not in r:
                sys.exit(f"ERROR: SR row missing '{k}': {r}")
        name = str(r["name"]).strip()
        if not name or "/" in name:
            sys.exit(f"ERROR: SR name {r['name']!r} is empty or contains '/' -- it "
                     f"would mangle the /<label>/<sr>/... YODA path.")
        if name in seen:
            sys.exit(f"ERROR: duplicate SR name {name!r} (rows {seen[name]} and {i}) -- "
                     f"they collide on the same YODA path and one would be lost.")
        seen[name] = i

        s = _finite(r["s"], "s", name)
        n = _finite(r["n"], "n", name)
        b = _finite(r["b"], "b", name)
        db = _finite(r["db"], "db", name)
        # n is an observed integer event count and is printed rounded; refuse to
        # store-what-we-don't-display (a non-integer n is a corrupted count).
        if n != round(n):
            sys.exit(f"ERROR: SR {name!r} observed n = {n!r} is not an integer "
                     f"(observed counts must be whole events).")

        base = f"/{label}/{name}"
        aos.append(estimate0d(f"{base}/signal", s, title=f"{name} expected signal"))
        aos.append(counter(f"{base}/observed", n, title=f"{name} observed data"))
        aos.append(estimate0d(f"{base}/background", b, db, title=f"{name} SM background"))
        clean.append((name, s, n, b, db))
        print(f"{name:6s} {s:10.4f} {n:11.0f} {b:9.3f} {db:8.3f}")
    n_srs = len(rows)

    # optional: clone every Histo1D-family object from the Rivet YODA through
    n_histos = 0
    if args.histos:
        try:
            src = yoda.read(args.histos)
        except Exception as exc:  # truncated/corrupt gz, unreadable file, ...
            sys.exit(f"ERROR: could not read --histos {args.histos}: {exc}")
        for path, obj in sorted(src.items()):
            if "Histo1D" in type(obj).__name__:  # Histo1D / BinnedHisto1D
                aos.append(obj.clone())
                n_histos += 1
        # A truncated/corrupt .yoda.gz often READS as an empty (or histogram-free)
        # dict instead of raising -- requiring >=1 clone turns that silent no-op
        # (which previously still reported "round-trip OK") into a loud failure.
        if n_histos == 0:
            sys.exit(f"ERROR: --histos {args.histos} yielded 0 Histo1D-family "
                     f"object(s) to clone (truncated/corrupt/wrong file?).")
        print(f"\ncloned {n_histos} Histo1D-family object(s) from {args.histos}")

    yoda.write(aos, args.out)
    print(f"wrote {args.out}: {n_srs} SR x 3 scalars + {n_histos} histo(s) "
          f"= {len(aos)} object(s)")

    # --- round-trip self-check: every per-SR scalar must reproduce byte-for-byte -----
    back = yoda.read(args.out)
    bad = []
    # 1) object count: catches any path collision / dropped object up front.
    if len(back) != len(aos):
        bad.append(f"object count: wrote {len(aos)} but read back {len(back)} "
                   f"(a path collision or dropped object)")
    # 2) every scalar (s, n, b, db) -- not just signal -- read back exactly.
    #    (obj-name, label, value, getter); db is read off the same background object.
    for name, s, n, b, db in clean:
        base = f"/{label}/{name}"
        for obj_name, field, want, getter in (
            ("signal", "s", s, lambda o: o.val()),
            ("observed", "n", n, lambda o: o.sumW()),
            ("background", "b", b, lambda o: o.val()),
            ("background", "db", db, lambda o: o.errAvg(ERR_SOURCE)),
        ):
            key = f"{base}/{obj_name}"
            if key not in back:
                bad.append(f"{key}: missing on read-back")
                continue
            got = getter(back[key])
            if got != want:
                bad.append(f"{key} [{field}]: read {got!r} != input {want!r}")
    if bad:
        for b in bad:
            print("ROUND-TRIP FAIL:", b, file=sys.stderr)
        sys.exit("ERROR: per-SR yields did not round-trip exactly.")
    print(f"round-trip OK: {n_srs}/{n_srs} SRs (s, n, b, db) read back exactly equal "
          f"to input; {len(back)}/{len(aos)} objects present")


if __name__ == "__main__":
    main()
