#!/usr/bin/env python3
"""verify_pack.py -- mechanical-integrity assertions over a run's artifact JSONs.

The scripted half of Tier A of the ADVERSARIAL VERIFICATION PANEL
(workflow/steps/09-verify.md + workflow/checklists/verification-panel.md).
Given a rundir, it finds the artifact JSONs the run carries and asserts their
INTERNAL consistency -- it reads artifacts only, re-runs no physics, modifies
nothing. Checks:

  * every artifact JSON parses (a corrupt artifact is a FAIL);
  * figures.json: every figure file (png + declared pdf) exists on disk;
    captions (what_it_shows) recorded (WARN when not); the embedded figure
    contract's targets fulfilled or WARNed; n_figures bookkeeping;
  * result.json: verdict/limit self-consistency (excluded_obs == (mu95_obs<1),
    mu95_exp == band median, band ordered), pointers resolve on disk,
    n_figures matches figures.json;
  * scan-shaped JSONs (n_planned/n_done/points): coverage bookkeeping
    (n_planned == n_done + n_missing, len(points) == n_done,
    len(missing_tags) == n_missing), unique tags, per-point verdict/band/
    Delta-m self-consistency;
  * scan_manifest.json vs the scan: planned-lattice bookkeeping;
  * sensitivity.json: window keys consistent between background and signals,
    no negative yields;
  * every plot referenced by an artifact JSON or by RESULT.md exists on disk;
  * DEVIATIONS.md exists whenever any artifact JSON carries a 'deviations' key
    or a renorm/rebase-style provenance block (a mid-run protocol adjustment
    that the deviations ledger must mirror -- see checklists/check-ins.md and
    the NUMBER-INTEGRITY rule in checklists/verification-panel.md).

What it CANNOT do (stays with the [agent]): trace numbers quoted in PROSE to
their artifact values, check units, or judge physics -- see the checklist.

Report lines are formatted for direct pasting into the panel's Tier-A section.
Exit 0 = no FAIL (WARNs allowed), 1 = at least one FAIL, 2 = usage error.

Usage:  verify_pack.py <rundir>
"""
import json
import math
import os
import re
import sys

# directories never containing deliverable artifacts (heavy / regenerable)
SKIP_DIRS = {"build", "logs", "__pycache__", ".git", "Events"}
REL_TOL = 1e-6


class Report:
    def __init__(self):
        self.lines = []          # (level, artifact, message)

    def add(self, level, artifact, message):
        self.lines.append((level, artifact, message))

    def ok(self, artifact, message):
        self.add("PASS", artifact, message)

    def warn(self, artifact, message):
        self.add("WARN", artifact, message)

    def fail(self, artifact, message):
        self.add("FAIL", artifact, message)

    def info(self, artifact, message):
        self.add("INFO", artifact, message)

    def emit(self):
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "INFO": 0}
        for level, artifact, message in self.lines:
            counts[level] += 1
            print(f"[{level}] {artifact} — {message}")
        print(f"\nverify_pack: {counts['PASS']} PASS, {counts['WARN']} WARN, "
              f"{counts['FAIL']} FAIL  ({counts['INFO']} info)")
        return 1 if counts["FAIL"] else 0


def close(a, b, rel=REL_TOL):
    try:
        return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=1e-12)
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
#  discovery
# --------------------------------------------------------------------------- #

def file_index(rundir):
    """All files under the rundir (skipping heavy dirs), as rundir-relative paths."""
    index = []
    for root, dirs, files in os.walk(rundir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            index.append(os.path.relpath(os.path.join(root, f), rundir))
    return index


def find_artifact_jsons(rundir):
    """Artifact JSONs: top-level *.json + everything under inputs/ and outputs/."""
    found = []
    for f in sorted(os.listdir(rundir)):
        if f.endswith(".json") and os.path.isfile(os.path.join(rundir, f)):
            found.append(f)
    for sub in ("inputs", "outputs"):
        top = os.path.join(rundir, sub)
        if not os.path.isdir(top):
            continue
        for root, dirs, files in os.walk(top):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in sorted(files):
                if f.endswith(".json"):
                    found.append(os.path.relpath(os.path.join(root, f), rundir))
    return found


def resolve_ref(rundir, index, ref):
    """Resolve a referenced path: rundir-relative, repo-relative, then a unique
    suffix match against the file index (prose often cites basenames/suffixes)."""
    if os.path.isfile(os.path.join(rundir, ref)):
        return ref
    # repo-relative (e.g. 'trial-runs/<run>/plots/x.png' cited from inside the run)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(rundir)))
    if os.path.isfile(os.path.join(repo, ref)):
        return ref
    base = os.path.basename(ref)
    hits = [p for p in index if p.endswith(base)]
    return hits[0] if hits else None


# --------------------------------------------------------------------------- #
#  per-shape checks
# --------------------------------------------------------------------------- #

def check_figures(rep, rundir, index, name, doc):
    figs = doc.get("figures", [])
    n_declared = doc.get("n_figures")
    if n_declared is not None and n_declared != len(figs):
        rep.fail(name, f"n_figures={n_declared} but figures[] has {len(figs)} entries")
    else:
        rep.ok(name, f"n_figures bookkeeping consistent ({len(figs)} figure(s))")
    missing, uncaptioned = [], []
    for fig in figs:
        for key in ("filename", "pdf"):
            ref = fig.get(key)
            if ref and not resolve_ref(rundir, index, ref):
                missing.append(ref)
        if not fig.get("what_it_shows"):
            uncaptioned.append(fig.get("filename", "(unnamed)"))
    if missing:
        rep.fail(name, "figure file(s) NOT on disk: " + ", ".join(missing))
    elif figs:
        rep.ok(name, "every declared figure file exists on disk")
    if uncaptioned:
        rep.warn(name, "displayed figure(s) lack a caption (what_it_shows null): "
                 + ", ".join(uncaptioned))
    check_figure_target(rep, rundir, index, name, doc.get("figure_target"))


def check_figure_target(rep, rundir, index, name, tgt_doc):
    if not tgt_doc:
        return
    for tgt in tgt_doc.get("targets", []):
        fid = tgt.get("figure_id") or "(description-only)"
        gen = tgt.get("generated_counterpart")
        # PRIMARY targets echoed at check-in are a HARD gate (D5/D9): the deck headline must be
        # bound to the approved target. Non-primary declared-but-unrendered targets stay advisory.
        primary = bool(tgt.get("primary") and tgt.get("declared_at_checkin"))
        if not gen:
            if primary:
                rep.fail(name, f"figure-contract PRIMARY target {fid} declared at check-in but no "
                         "generated counterpart attached (headline not bound to the approved target)")
            else:
                rep.warn(name, f"figure-contract target {fid} DECLARED but no generated "
                         "counterpart attached (contract unfulfilled)")
            continue
        if primary and not tgt.get("side_by_side"):
            rep.fail(name, f"figure-contract PRIMARY target {fid} has a generated counterpart but no "
                     "composed side_by_side (run `figure_target.py compose`)")
        for label, ref in (("generated counterpart", (gen or {}).get("path")),
                           ("side-by-side", (tgt.get("side_by_side") or {}).get("path")
                            if isinstance(tgt.get("side_by_side"), dict)
                            else tgt.get("side_by_side"))):
            if ref and not resolve_ref(rundir, index, ref):
                rep.fail(name, f"figure-contract target {fid}: {label} path not on disk: {ref}")
            elif ref:
                rep.ok(name, f"figure-contract target {fid}: {label} exists on disk")


def check_result(rep, rundir, index, name, doc, figures_doc):
    mu = doc.get("mu95_obs")
    excl = doc.get("excluded_obs")
    if mu is not None and excl is not None:
        if bool(excl) == (float(mu) < 1.0):
            rep.ok(name, f"verdict self-consistent: excluded_obs={excl} vs mu95_obs={mu:.4g}")
        else:
            rep.fail(name, f"verdict INCONSISTENT: excluded_obs={excl} but mu95_obs={mu:.4g}")
    band = doc.get("mu95_exp_band")
    exp = doc.get("mu95_exp")
    if band and exp is not None:
        if len(band) == 5 and close(exp, band[2]):
            rep.ok(name, "mu95_exp equals the expected-band median")
        else:
            rep.fail(name, f"mu95_exp={exp} is not the 5-entry band median (band={band})")
        if band == sorted(band):
            rep.ok(name, "expected band is ordered (-2σ … +2σ)")
        else:
            rep.warn(name, f"expected band not monotonically ordered: {band}")
    for what, ref in (doc.get("pointers") or {}).items():
        if not ref:
            continue
        if resolve_ref(rundir, index, ref):
            rep.ok(name, f"pointer '{what}' resolves on disk ({ref})")
        else:
            rep.fail(name, f"pointer '{what}' does NOT resolve on disk: {ref}")
    if figures_doc is not None and doc.get("n_figures") is not None:
        nf = figures_doc.get("n_figures")
        if doc["n_figures"] == nf:
            rep.ok(name, f"n_figures matches figures.json ({nf})")
        else:
            rep.fail(name, f"n_figures={doc['n_figures']} but figures.json says {nf}")


def check_scan(rep, name, doc):
    n_planned = doc.get("n_planned")
    n_done = doc.get("n_done")
    n_missing = doc.get("n_missing", 0)
    points = doc.get("points", [])
    missing_tags = doc.get("missing_tags", [])
    problems = []
    if n_planned is not None and n_done is not None and n_planned != n_done + n_missing:
        problems.append(f"n_planned={n_planned} != n_done={n_done} + n_missing={n_missing}")
    if n_done is not None and len(points) != n_done:
        problems.append(f"len(points)={len(points)} != n_done={n_done}")
    if len(missing_tags) != n_missing:
        problems.append(f"len(missing_tags)={len(missing_tags)} != n_missing={n_missing}")
    if problems:
        rep.fail(name, "coverage bookkeeping INCONSISTENT: " + "; ".join(problems))
    else:
        rep.ok(name, f"coverage bookkeeping self-consistent: n_done={n_done}/"
               f"n_planned={n_planned}, n_missing={n_missing}")
    tags = [p.get("tag") for p in points]
    dupes = sorted({t for t in tags if t and tags.count(t) > 1})
    if dupes:
        rep.fail(name, "duplicate point tags: " + ", ".join(dupes))
    bad_verdict, bad_band, bad_dm = [], [], []
    for p in points:
        tag = p.get("tag", "?")
        mu = p.get("mu95_obs")
        if mu is not None and p.get("excluded_obs") is not None \
                and bool(p["excluded_obs"]) != (float(mu) < 1.0):
            bad_verdict.append(tag)
        band, exp = p.get("mu95_exp_band"), p.get("mu95_exp")
        if band is not None and exp is not None \
                and not (len(band) == 5 and close(exp, band[2])):
            bad_band.append(tag)
        mp, ml, dm = p.get("m_parent"), p.get("m_lsp"), p.get("dm")
        if None not in (mp, ml, dm) and not close(dm, mp - ml, rel=1e-4):
            bad_dm.append(tag)
    for bad, what in ((bad_verdict, "excluded_obs vs mu95_obs<1"),
                      (bad_band, "mu95_exp vs band median"),
                      (bad_dm, "dm vs m_parent - m_lsp")):
        if bad:
            rep.fail(name, f"per-point INCONSISTENCY ({what}) at: " + ", ".join(bad[:8])
                     + ("…" if len(bad) > 8 else ""))
    if points and not (bad_verdict or bad_band or bad_dm):
        rep.ok(name, f"all {len(points)} points self-consistent "
               "(verdict, expected-band median, Δm arithmetic)")


def check_manifest(rep, name, doc, scan_doc, scan_name):
    n_points = doc.get("n_points")
    points = doc.get("points", [])
    if n_points is not None and n_points != len(points):
        rep.fail(name, f"n_points={n_points} but points[] has {len(points)} entries")
    else:
        rep.ok(name, f"planned-lattice bookkeeping consistent ({len(points)} point(s))")
    if scan_doc is None:
        return
    if n_points is not None and scan_doc.get("n_planned") is not None \
            and n_points != scan_doc["n_planned"]:
        rep.fail(name, f"n_points={n_points} disagrees with {scan_name} "
                 f"n_planned={scan_doc['n_planned']}")
    manifest_tags = {p.get("tag") for p in points}
    stray = [p.get("tag") for p in scan_doc.get("points", [])
             if p.get("tag") not in manifest_tags]
    if stray:
        rep.fail(name, f"{scan_name} carries point(s) not in the planned lattice: "
                 + ", ".join(str(t) for t in stray[:8]))
    else:
        rep.ok(name, f"every {scan_name} point is on the planned lattice")


def check_sensitivity(rep, name, doc):
    windows = doc.get("windows")
    if not isinstance(windows, dict):
        rep.info(name, "no 'windows' block — parsed OK, shape-specific checks skipped")
        return
    wkeys = set(windows)
    negatives = []
    bkg = doc.get("background")
    if isinstance(bkg, dict) and set(bkg) != wkeys:
        rep.fail(name, f"background windows {sorted(bkg)} != declared windows {sorted(wkeys)}")
    for side in ("background", "signals"):
        block = doc.get(side)
        if not isinstance(block, dict):
            continue
        for key, sub in block.items():
            if not isinstance(sub, dict):
                continue
            yields = sub.get("yields_at_lumi")
            if isinstance(yields, dict):
                for yk, yv in yields.items():
                    if isinstance(yv, (int, float)) and yv < 0:
                        negatives.append(f"{side}.{key}.{yk}")
    if negatives:
        rep.fail(name, "negative yield(s): " + ", ".join(negatives[:8]))
    else:
        rep.ok(name, f"window bookkeeping consistent ({len(wkeys)} window(s)), "
               "no negative yields found")


# --------------------------------------------------------------------------- #
#  cross-cutting checks
# --------------------------------------------------------------------------- #

PLOT_RE = re.compile(r"[\w][\w./\\-]*\.(?:png|pdf)\b")
PLOT_BRACE_RE = re.compile(r"([\w][\w./\\-]*)\.\{(png|pdf)(?:,(png|pdf))?\}")


def iter_json_strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from iter_json_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_json_strings(v)
    elif isinstance(node, str):
        yield node


def check_plot_refs(rep, rundir, index, docs):
    """Every plot referenced by an artifact JSON or by RESULT.md exists on disk."""
    refs = {}   # ref -> where it was cited
    for name, doc in docs.items():
        for s in iter_json_strings(doc):
            if PLOT_RE.fullmatch(s):
                refs.setdefault(s, name)
    result_md = os.path.join(rundir, "RESULT.md")
    if os.path.isfile(result_md):
        text = open(result_md, encoding="utf-8", errors="replace").read()
        for m in PLOT_BRACE_RE.finditer(text):
            for ext in m.groups()[1:]:
                if ext:
                    refs.setdefault(f"{m.group(1)}.{ext}", "RESULT.md")
        for m in PLOT_RE.finditer(text):
            refs.setdefault(m.group(0), "RESULT.md")
    else:
        rep.warn("RESULT.md", "absent — the run has no human-narrative deliverable to verify")
    unresolved = sorted(r for r in refs if not resolve_ref(rundir, index, r))
    if unresolved:
        rep.fail("plot-refs", "referenced plot(s) NOT found on disk: "
                 + ", ".join(f"{r} (cited in {refs[r]})" for r in unresolved[:8])
                 + ("…" if len(unresolved) > 8 else ""))
    elif refs:
        rep.ok("plot-refs", f"all {len(refs)} referenced plot file(s) exist on disk")
    else:
        rep.info("plot-refs", "no plot references found in artifacts/RESULT.md")


def deviation_blocks(name, doc):
    """Key-paths in an artifact that record a mid-run protocol adjustment:
    an explicit 'deviations' key, or renorm/rebase-style provenance blocks."""
    hits = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k).lower()
                if key == "deviations" or "renorm" in key or "rebase" in key \
                        or key == "model_basis":
                    hits.append(f"{name}:{'.'.join(path + [str(k)])}")
                walk(v, path + [str(k)])
        elif isinstance(node, list):
            for v in node:
                walk(v, path)

    walk(doc, [])
    return hits


def check_deviations_ledger(rep, rundir, docs):
    hits = []
    for name, doc in docs.items():
        hits += deviation_blocks(name, doc)
    ledger = os.path.join(rundir, "DEVIATIONS.md")
    if hits and not os.path.isfile(ledger):
        rep.fail("DEVIATIONS.md", "artifact(s) carry deviation/renorm/rebase provenance "
                 "but the run has NO DEVIATIONS.md ledger (checklists/check-ins.md): "
                 + ", ".join(hits[:6]) + ("…" if len(hits) > 6 else ""))
    elif hits:
        rep.ok("DEVIATIONS.md", f"ledger present; {len(hits)} provenance block(s) to "
               "cross-check against it by hand: " + ", ".join(hits[:6]))
    elif os.path.isfile(ledger):
        rep.info("DEVIATIONS.md", "ledger present (no deviation-style provenance "
                 "blocks found in the artifacts)")
    else:
        rep.info("DEVIATIONS.md", "no ledger and no deviation-style provenance blocks "
                 "found — confirm by hand that the run truly had zero mid-run adjustments")


def check_open_defect(rep, rundir):
    """N5 OPEN-DEFECT: a helper flagged with an OPEN defect note must not feed a comparison/check-in.
    verify_pack is the pre-delivery comparison gate, so any open note here is a FAIL."""
    p = os.path.join(rundir, "run_state.json")
    if not os.path.isfile(p):
        rep.info("run_state.json", "no run_state.json -- open-defect gate not evaluated")
        return
    try:
        st = json.load(open(p))
    except (json.JSONDecodeError, OSError) as e:
        rep.warn("run_state.json", f"present but unreadable ({e}) -- open-defect gate skipped")
        return
    notes = st.get("open_defect_notes") or []
    open_notes = [n for n in notes if isinstance(n, dict) and n.get("status") == "open"]
    if not open_notes:
        rep.info("run_state.json", f"{len(notes)} defect note(s), none open -- open-defect gate clear")
        return
    for n in open_notes:
        rep.fail("run_state.json", f"OPEN defect note on helper {n.get('helper')!r} "
                 f"({str(n.get('note', ''))[:120]}) -- a number from a helper with an open defect must "
                 "not feed a comparison/check-in until the note is resolved (status=fixed) or a blessed "
                 "tool substituted (N5).")


# --------------------------------------------------------------------------- #
#  main
# --------------------------------------------------------------------------- #

def _verify_pack_selftest():
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory(prefix="verify_pack_selftest_") as td:
        rd = os.path.join(td, "run"); os.makedirs(rd)
        with open(os.path.join(rd, "run_state.json"), "w") as f:
            json.dump({"open_defect_notes": [{"helper": "read_yoda.py",
                      "note": "A x e reads 956%", "status": "open"}]}, f)
        rc = main(["verify_pack.py", rd])
        ok1 = (rc == 1)
        print(f"[selftest] 1 open defect note -> verify_pack FAIL (exit 1): {'ok' if ok1 else 'FAIL'}")
        if not ok1: fails.append(f"open-defect gate did not FAIL (rc={rc})")
        with open(os.path.join(rd, "run_state.json"), "w") as f:
            json.dump({"open_defect_notes": [{"helper": "read_yoda.py",
                      "note": "fixed", "status": "fixed"}]}, f)
        rc2 = main(["verify_pack.py", rd])
        ok2 = (rc2 == 0)
        print(f"[selftest] 2 fixed defect note -> no open-defect FAIL (exit 0): {'ok' if ok2 else 'FAIL'}")
        if not ok2: fails.append(f"open-defect gate still firing after fix (rc={rc2})")
    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("verify_pack selftest: PASS (2 case(s))")
    return 0


def main(argv):
    if "--selftest" in argv[1:]:
        return _verify_pack_selftest()
    args = [a for a in argv[1:] if not a.startswith("-")]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    rundir = args[0].rstrip("/")
    if not os.path.isdir(rundir):
        print(f"verify_pack: not a directory: {rundir}", file=sys.stderr)
        return 2

    rep = Report()
    index = file_index(rundir)
    check_open_defect(rep, rundir)
    docs = {}
    for rel in find_artifact_jsons(rundir):
        path = os.path.join(rundir, rel)
        try:
            with open(path) as f:
                docs[rel] = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            rep.fail(rel, f"NOT valid JSON ({e}) — corrupt artifact")
    if not docs:
        rep.warn(os.path.basename(rundir), "no artifact JSONs found — nothing machine-"
                 "checkable; the run cannot pass a mechanical-integrity tier")
        return rep.emit()
    rep.info(os.path.basename(rundir), f"{len(docs)} artifact JSON(s) parsed: "
             + ", ".join(sorted(docs)))

    figures_doc = docs.get("figures.json")
    scan_docs = {n: d for n, d in docs.items()
                 if isinstance(d, dict) and "points" in d and "n_done" in d}
    for name, doc in sorted(docs.items()):
        base = os.path.basename(name)
        if not isinstance(doc, dict):
            continue
        if base == "figures.json":
            check_figures(rep, rundir, index, name, doc)
        elif base == "result.json":
            check_result(rep, rundir, index, name, doc, figures_doc)
        elif name in scan_docs:
            check_scan(rep, name, doc)
        elif base == "scan_manifest.json":
            primary = ("scan.json" if "scan.json" in scan_docs
                       else next(iter(sorted(scan_docs)), None))
            check_manifest(rep, name, doc, scan_docs.get(primary), primary or "scan.json")
        elif base == "sensitivity.json":
            check_sensitivity(rep, name, doc)
        elif base == "figure_target.json":
            check_figure_target(rep, rundir, index, name, doc)

    check_plot_refs(rep, rundir, index, docs)
    check_deviations_ledger(rep, rundir, docs)
    return rep.emit()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
