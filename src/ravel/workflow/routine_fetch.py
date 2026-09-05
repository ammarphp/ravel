#!/usr/bin/env python
"""Map a paper (ATLAS/CMS code, Inspire id, arXiv, or keyword) to its analysis routine(s),
across BOTH ecosystems the pipeline supports: Rivet and SimpleAnalysis.

- Rivet: scans the bundled routine `.info` files (Name + References carry the ATLAS/CMS code,
  arXiv, Inspire id) and returns the routine id (e.g. ATLAS_2016_I1458270) for step 4A.
- SimpleAnalysis: scans the source repo's `ANA-<CODE>.cxx` files for `DefineAnalysis(<name>)`
  and returns the routine name to put in the mapyde TOML `[simpleanalysis] name` for step 4B,
  plus whether it is in the `:master` container image (≈ available without a rebuild).

This makes step 2 ("obtain the routine") cover both routine types; the same query resolves to
whichever ecosystem(s) implement the analysis. A CMS/other routine type would slot in the same way.

Usage:
  routine_fetch.py --query "ATLAS-SUSY-2018-16" \
      [--rivet-share <…/envs/rivet/share/Rivet>] [--sa-src <…/simple-analysis-src>] [--index]
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse, glob, os, re, sys


def scan_rivet(share, query):
    hits = []
    q = query.lower()
    qnum = re.search(r"(\d{6,7})", query)  # an Inspire id buried in the query
    for info in glob.glob(os.path.join(share, "*.info")):
        txt = open(info, errors="replace").read()
        rid = os.path.basename(info)[:-5]
        blob = txt.lower()
        if q in blob or rid.lower() == q or (qnum and qnum.group(1) in rid):
            refs = re.findall(r"-\s*'?([A-Z]+-[A-Z]+-\d{4}-\d+)'?", txt)
            status = (re.search(r"Status:\s*(.+)", txt) or [None, "?"])[1].strip()
            hits.append({"routine": rid, "codes": sorted(set(refs)), "status": status})
    return hits


def scan_simpleanalysis(sa_src, query):
    hits = []
    q = query.lower()
    # SimpleAnalysis names its files `ANA-<CODE>.cxx` where <CODE> DROPS the experiment prefix
    # (ANA-SUSY-2018-16, not ANA-ATLAS-SUSY-2018-16). So match on the CORE code (SUSY-2018-16),
    # tolerating a leading experiment token in the query (ATLAS-SUSY-2018-16). Matching the full
    # ATLAS-... string against ANA-SUSY-... was the bug that returned 0 hits for the exact analysis.
    m = re.search(r"(?:([A-Z]+)-)?([A-Z]+-\d{4}-\d+)", query.upper())
    core = m.group(2) if m else None                      # e.g. SUSY-2018-16
    srcdir = os.path.join(sa_src, "SimpleAnalysisCodes", "src")
    for cxx in glob.glob(os.path.join(srcdir, "*.cxx")):
        base = os.path.basename(cxx)
        txt = open(cxx, errors="replace").read()
        filecode = re.search(r"ANA-([A-Z]+-\d{4}-\d+)", base)
        match = (q in base.lower() or q in txt.lower() or
                 (core and core in base.upper()))
        if match:
            names = re.findall(r"DefineAnalysis\(\s*([A-Za-z0-9_]+)\s*\)", txt)
            hits.append({"file": base, "code": filecode.group(1) if filecode else "?",
                         "names": names})
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True, help="paper code / Inspire id / arXiv / keyword")
    ap.add_argument("--rivet-share", default="stages/01-event-generation/build/tools/miniforge3/envs/rivet/share/Rivet")
    ap.add_argument("--sa-src", default="stages/01-event-generation/build/tools/simple-analysis-src")
    ap.add_argument("--index", action="store_true", help="also print total coverage of each ecosystem")
    args = ap.parse_args()

    print(f"query: {args.query}\n")
    rv = scan_rivet(args.rivet_share, args.query) if os.path.isdir(args.rivet_share) else []
    print(f"== Rivet routines ({len(rv)} match) ==")
    for h in rv:
        print(f"  {h['routine']}  [{h['status']}]  codes={h['codes']}")
        print(f"     → step 4A: rivet -a {h['routine']} <hepmc> -o analysis.yoda")
    if not rv:
        print("  (none — try a different code/keyword, or it may be CMS/other)")

    sa = scan_simpleanalysis(args.sa_src, args.query) if os.path.isdir(args.sa_src) else []
    print(f"\n== SimpleAnalysis routines ({len(sa)} match) ==")
    for h in sa:
        print(f"  {h['file']}  (code {h['code']})  DefineAnalysis: {h['names']}")
        for n in h["names"]:
            print(f"     → step 4B: mapyde TOML [simpleanalysis] name = \"{n}\"  "
                  f"(in the :master container; else rebuild/add the .cxx)")
    if not sa:
        if not os.path.isdir(args.sa_src):
            print(f"  (SA source not cloned at {args.sa_src}; "
                  f"git clone --depth 1 https://gitlab.cern.ch/atlas-sa/simple-analysis)")
        else:
            print("  (no ANA-*.cxx in the cloned SA src matched. NOTE: match on the analysis CODE "
                  "(e.g. 'SUSY-2018-16'), not the Inspire/arXiv id — SA .cxx files key on the code, "
                  "not the id. If the code is right and still no hit, the routine may live only in the "
                  ":master image: list it with `podman run --rm gitlab-registry.cern.ch/atlas-sa/"
                  "simple-analysis:master simpleAnalysis --list`, or fetch the submodules "
                  "(git submodule update --init) so SimpleAnalysisCodes/src/ is fully populated.)")

    if args.index:
        nrv = len(glob.glob(os.path.join(args.rivet_share, "*.info")))
        nsa = len(glob.glob(os.path.join(args.sa_src, "SimpleAnalysisCodes", "src", "ANA-*.cxx")))
        print(f"\ncoverage: Rivet bundles {nrv} routines; SimpleAnalysis repo has {nsa} ANA-*.cxx")


if __name__ == "__main__":
    main()
