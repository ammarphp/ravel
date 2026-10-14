#!/usr/bin/env python
"""Map a paper (analysis code, Inspire id, arXiv, or keyword) to its analysis routine(s),
across BOTH ecosystems the pipeline supports: Rivet and SimpleAnalysis.

- Rivet: scans the bundled routine `.info` files (Name + References carry the analysis code,
  arXiv, Inspire id) and returns the routine id (<EXP>_<YEAR>_I<inspire>) for step 4A.
- SimpleAnalysis: scans the source repo's `ANA-<CODE>.cxx` files for `DefineAnalysis(<name>)`
  and returns the routine name to put in the mapyde TOML `[simpleanalysis] name` for step 4B,
  plus whether it is in the `:master` container image (≈ available without a rebuild).

- Catalogue snapshot: the local analysis catalogue (`ravel catalogue`, then `ravel analyses list`)
  is always consulted, so a lookup works without the local source trees. A source tree that is not on
  disk is reported as "not checked", never as zero matches.

This makes step 2 ("obtain the routine") cover both routine types; the same query resolves to
whichever ecosystem(s) implement the analysis. A CMS/other routine type would slot in the same way.

Usage:
  routine_fetch.py --query "<EXP>-<GROUP>-<YEAR>-<NN>" \
      [--rivet-share <…/envs/rivet/share/Rivet>] [--sa-src <…/simple-analysis-src>] [--index] [--json]
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse, glob, json, os, re, sys

from ravel.paths import native_build_root


def scan_rivet(share, query):
    hits = []
    q = query.lower()
    qnum = re.search(r"(?:^|ins|_I)(\d{1,8})$", query.strip(), re.I)  # an Inspire id as the query
    for info in glob.glob(os.path.join(share, "*.info")):
        txt = open(info, errors="replace").read()
        rid = os.path.basename(info)[:-5]
        blob = txt.lower()
        if q in blob or rid.lower() == q or (qnum and rid.upper().endswith("_I" + qnum.group(1))):
            refs = re.findall(r"-\s*'?([A-Z]+-[A-Z]+-\d{4}-\d+)'?", txt)
            status = (re.search(r"Status:\s*(.+)", txt) or [None, "?"])[1].strip()
            hits.append({"routine": rid, "codes": sorted(set(refs)), "status": status})
    return hits


def scan_simpleanalysis(sa_src, query):
    hits = []
    q = query.lower()
    # SimpleAnalysis names its files `ANA-<CODE>.cxx` where <CODE> DROPS the experiment prefix
    # (ANA-<GROUP>-<YEAR>-<NN>, not ANA-<EXP>-<GROUP>-...). So match on the core code
    # <GROUP>-<YEAR>-<NN>, tolerating a leading experiment token in the query. Matching the full
    # prefixed string against the file name was the bug that returned 0 hits for the exact analysis.
    m = re.search(r"(?:([A-Z]+)-)?([A-Z]+-\d{4}-\d+)", query.upper())
    core = m.group(2) if m else None                      # <GROUP>-<YEAR>-<NN>
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


def default_sources():
    tools = native_build_root() / "tools"
    return (tools / "miniforge3/envs/rivet/share/Rivet", tools / "simple-analysis-src")


def catalog_matches(query, catalog=None):
    """Rows of the local analysis catalogue that match an INSPIRE id, an analysis code
    (with or without the experiment prefix), an arXiv id, a routine name, or title words."""
    from ravel.analysis_catalog import load_catalog, search
    catalog = catalog or load_catalog()
    q = query.strip()
    rows = []
    ins = re.search(r"(?:^|ins|_I|literature/)(\d{1,8})$", q, re.I)
    code = re.search(r"(?:([A-Z]+)-)?([A-Z]+-\d{4}-\d+)", q.upper())
    arxiv = re.search(r"(\d{4}\.\d{4,5})", q)
    for row in catalog["entries"]:
        hit = ((ins and row.get("inspire_id") == ins.group(1))
               or (code and code.group(2) in {a.upper() for a in row.get("analysis_ids") or []})
               or (arxiv and any(u.rstrip("/").endswith(arxiv.group(1))
                                 for u in row.get("publication_urls") or []))
               or q.casefold() in {row["id"].casefold(), row["name"].casefold()})
        if hit:
            rows.append(row)
    if not rows and not (ins or code or arxiv):
        rows = search(catalog, q)
    return [{"id": r["id"], "framework": r["framework"], "name": r["name"],
             "experiment": r.get("experiment"), "title": r.get("title"),
             "analysis_ids": r.get("analysis_ids") or [], "inspire_id": r.get("inspire_id")}
            for r in rows]


def find_routines(query, rivet_share=None, sa_src=None, catalog=None):
    """Structured lookup across the local Rivet share, the local SimpleAnalysis source and the
    local analysis catalogue. A missing tree or catalogue is `checked: False` with the reason."""
    default_rivet, default_sa = default_sources()
    rivet_share = str(rivet_share or default_rivet)
    sa_src = str(sa_src or default_sa)
    out = {"query": query}
    for key, path, scan, label in (("rivet", rivet_share, scan_rivet, "Rivet share"),
                                   ("simpleanalysis", sa_src, scan_simpleanalysis,
                                    "SimpleAnalysis source")):
        if os.path.isdir(path):
            out[key] = {"checked": True, "source": path, "matches": scan(path, query)}
        else:
            out[key] = {"checked": False, "source": path, "matches": [],
                        "reason": f"{label} not found at {path}"}
    try:
        out["catalog"] = {"checked": True, "source": "local analysis catalogue",
                          "matches": catalog_matches(query, catalog)}
    except Exception as e:                       # a damaged install is a finding, not a crash
        out["catalog"] = {"checked": False, "source": "local analysis catalogue",
                          "matches": [], "reason": f"{type(e).__name__}: {e}"[:200]}
    return out


def format_report(found):
    lines = [f"query: {found['query']}", ""]
    rv = found["rivet"]
    if rv["checked"]:
        lines.append(f"== Rivet routines ({len(rv['matches'])} match) ==")
        for h in rv["matches"]:
            lines.append(f"  {h['routine']}  [{h['status']}]  codes={h['codes']}")
            lines.append(f"     → step 4A: rivet -a {h['routine']} <hepmc> -o analysis.yoda")
        if not rv["matches"]:
            lines.append("  (none — try a different code/keyword, or it may be CMS/other)")
    else:
        lines.append(f"== Rivet routines: not checked ({rv['reason']}) ==")
    sa = found["simpleanalysis"]
    lines.append("")
    if sa["checked"]:
        lines.append(f"== SimpleAnalysis routines ({len(sa['matches'])} match) ==")
        for h in sa["matches"]:
            lines.append(f"  {h['file']}  (code {h['code']})  DefineAnalysis: {h['names']}")
            for n in h["names"]:
                lines.append(f"     → step 4B: mapyde TOML [simpleanalysis] name = \"{n}\"  "
                             f"(in the :master container; else rebuild/add the .cxx)")
        if not sa["matches"]:
            lines.append("  (no ANA-*.cxx in the cloned SA src matched. Match on the analysis CODE "
                         "(the experiment's code for the analysis), not the Inspire/arXiv id — SA .cxx files key on "
                         "the code. If the code is right and still no hit, the routine may live "
                         "only in the :master image (`simpleAnalysis --list` inside it), or the "
                         "submodules need `git submodule update --init`.)")
    else:
        lines.append(f"== SimpleAnalysis routines: not checked ({sa['reason']}; clone with "
                     f"git clone --depth 1 https://gitlab.cern.ch/atlas-sa/simple-analysis) ==")
    cat = found["catalog"]
    lines.append("")
    if cat["checked"]:
        lines.append(f"== Packaged catalogue snapshot ({len(cat['matches'])} match; "
                     f"`ravel analyses show <id>` for details) ==")
        for m in cat["matches"][:40]:
            codes = ", ".join(m["analysis_ids"])
            lines.append(f"  {m['name']}  [{m['framework']}]  {codes}  {m['title'] or ''}".rstrip())
    else:
        lines.append(f"== Packaged catalogue snapshot: not checked ({cat['reason']}) ==")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", required=True, help="paper code / Inspire id / arXiv / keyword")
    default_rivet, default_sa = default_sources()
    ap.add_argument("--rivet-share", default=str(default_rivet))
    ap.add_argument("--sa-src", default=str(default_sa))
    ap.add_argument("--index", action="store_true", help="also print total coverage of each ecosystem")
    ap.add_argument("--json", action="store_true", help="print the structured lookup as JSON")
    args = ap.parse_args(argv)

    found = find_routines(args.query, args.rivet_share, args.sa_src)
    if args.json:
        print(json.dumps(found, indent=1))
        return 0
    print(format_report(found))
    if args.index:
        nrv = len(glob.glob(os.path.join(args.rivet_share, "*.info")))
        nsa = len(glob.glob(os.path.join(args.sa_src, "SimpleAnalysisCodes", "src", "ANA-*.cxx")))
        print(f"\ncoverage: Rivet bundles {nrv} routines; SimpleAnalysis repo has {nsa} ANA-*.cxx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
