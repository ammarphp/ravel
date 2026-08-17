#!/usr/bin/env python
"""Independent exclusion cross-check via a reinterpretation database (SModelS).

Feeds an SLHA + cross-section to SModelS (digitised ATLAS+CMS efficiency maps) and reports its
r = σ_pred/σ_UL per analysis (r>1 ⇒ excluded). Use it to corroborate our pyhf limit: for a given
analysis, r ≈ 1/µ₉₅, so SModelS's r should be close to 1/(our µ₉₅). Run in the `reinterp` env.

Usage:
  reinterpret_db.py --slha CARD.dat --sigma-pb S --proc "1000021 1000021" \
      [--our-mu95 0.10 --analysis ATLAS-SUSY-2015-06] --out DIR
"""
import argparse, os, re, subprocess, sys


def add_xsection(slha, sigma_pb, proc):
    """Append a pyslha-format XSECTION block (LO, 13 TeV) for the production process."""
    t = open(slha, errors="replace").read()
    t = re.sub(r"\nXSECTION.*?(?=\n[A-Za-z#]|\Z)", "\n", t, flags=re.S)  # drop old blocks
    # pyslha value line: scale_scheme qcd_order ew_order kappa_f kappa_r pdf_id value code
    block = (f"XSECTION  1.30E+04  2212 2212 2 {proc}\n"
             f"  0  0  0  1.0  1.0  0  {sigma_pb:.4E}  MG5LO\n")
    open(slha, "w").write(t.rstrip() + "\n" + block)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slha", required=True)
    ap.add_argument("--sigma-pb", type=float, required=True)
    ap.add_argument("--proc", required=True, help="space-separated final-state PDG ids, e.g. '1000021 1000021'")
    ap.add_argument("--our-mu95", type=float)
    ap.add_argument("--analysis", help="analysis code to compare head-to-head, e.g. ATLAS-SUSY-2015-06")
    ap.add_argument("--data-select", choices=["all", "efficiencyMap", "upperLimit"], default="all",
                    help="restrict the database result type: 'efficiencyMap' is the FOLDING route "
                         "(step 4 Option D) — per-SR published A×ε folded over the model point, "
                         "enabling expected limits + best-SR reporting; 'upperLimit' is the "
                         "digitized-UL lookup; 'all' (default) = the cross-check mode")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    work = os.path.join(args.out, os.path.basename(args.slha))
    open(work, "w").write(open(args.slha, errors="replace").read())
    add_xsection(work, args.sigma_pb, args.proc)

    cmd = ["runSModelS.py", "-f", work, "-o", args.out]
    if args.data_select != "all":
        # -p REPLACES the default config wholesale, so patch SModelS's own default ini rather
        # than writing a minimal one (a bare [database] without 'path' crashes loadDatabase)
        import configparser
        try:
            import smodels
            default_ini = os.path.join(os.path.dirname(smodels.__file__),
                                       "etc", "parameters_default.ini")
        except Exception:
            default_ini = None
        cp = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
        if default_ini and os.path.exists(default_ini):
            cp.read(default_ini)
        if not cp.has_section("database"):
            cp.add_section("database")
        if not cp.has_option("database", "path"):
            cp.set("database", "path", "official")
        cp.set("database", "dataselector", args.data_select)
        pfile = os.path.join(args.out, "parameters_dataselect.ini")
        with open(pfile, "w") as f:
            cp.write(f)
        cmd += ["-p", pfile]
    try:
        subprocess.run(cmd, check=True,
                       capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        sys.exit("runSModelS.py not found — run in the 'reinterp' env (pip install smodels).")
    except subprocess.CalledProcessError as e:
        sys.exit(f"SModelS failed: {e.stderr[-400:]}")

    res = work + ".smodels"
    txt = open(res, errors="replace").read() if os.path.exists(res) else ""
    rows = re.findall(r"^\s*([A-Za-z0-9-]+)\s+[\d.E+-]+\s+[\d.]+\s+[\d.E+-]+\s+[\d.E+-]+\s+([\d.E+-]+)\s+([\d.E+-]+)",
                      txt, re.M)
    print(f"SModelS results -> {res}")
    seen = {}
    for ana, robs, rexp in rows:
        seen.setdefault(ana, (robs, rexp))
    for ana, (robs, rexp) in sorted(seen.items(), key=lambda kv: -float(kv[1][0]))[:8]:
        print(f"  {ana:22s} r_obs={float(robs):.2f}  r_exp={float(rexp):.2f}"
              + ("  <- excluded" if float(robs) >= 1 else ""))
    if args.analysis and args.our_mu95:
        m = seen.get(args.analysis)
        if m:
            r_them = float(m[0]); r_us = 1.0 / args.our_mu95
            print(f"\nhead-to-head on {args.analysis}: SModelS r_obs={r_them:.2f}  vs  our 1/µ₉₅={r_us:.2f}  "
                  f"(ratio {r_them/r_us:.2f})")


if __name__ == "__main__":
    main()
