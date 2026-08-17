#!/usr/bin/env python
"""Verify a Rivet routine declares its own DETECTOR SMEARING — the Rivet-path fidelity gate.

This is the Rivet-path analogue of the SimpleAnalysis/Delphes acc×eff certification
(`validate_cutflow.py`): before trusting a Rivet routine's per-SR yields as detector-level, we
confirm the routine itself applies detector smearing/efficiency at the source. A Rivet routine is
detector-level ONLY if it declares Smeared* projections (SmearedJets / SmearedParticles /
SmearedMET) or efficiency-bearing projections — these fold in the experiment's published object
resolution and reco efficiency at the analysis level. A routine with no such projection runs at
TRUTH (particle) level: its objects are generator-truth, so its "acceptance" carries no detector
response. Feeding a BSM signal through a truth-level routine and reading its SRs as if they were
detector-level is the silent failure this gate catches (the degeneracy story: the wrong path makes
acceptance ~2× off because the detector response is simply absent).

WHY a grep gate and not a re-run: the smearing declaration is a STATIC property of the routine
source — `declare(SmearedJets(...), "RecoJets")` etc. It is decidable by reading the .cc, with no
event generation, no Delphes, no Rivet pass. So this gate is cheap (read one file) and deterministic.

The source is scanned AFTER stripping C/C++ comments and string/char literals, and PASS is gated on the
STRUCTURAL declaration `declare(Smeared...(...), "name")` — not a bare `Smeared*` token. So a routine
that merely *mentions* SmearedJets in a `// comment` or a "string literal" is NOT laundered into a
detector-level PASS (the silent false-positive this gate must never produce).

VERDICT (mirrors validate_cutflow.py's three-state authority — PASS / WARN / FAIL):
  - PASS  = detector-level. The routine structurally DECLARES ≥1 Smeared* projection
            (declare(SmearedJets(...), "RecoJets") etc. — SmearedJets / SmearedParticles / SmearedMET).
            Its SR yields fold detector response; the Rivet path is the right path. The note records
            WHICH projections + a best-effort era/experiment (e.g. ATLAS_RUN2) read off the
            smearing/efficiency constant names.
  - WARN  = particle-level only. No structurally-declared Smeared* projection found. The routine either
            carries an efficiency-only projection (efficiency without resolution smearing — a partial
            detector treatment) or has no RECOGNIZED smearing/efficiency projection at all (a custom
            idiom may still be present — this is 'not recognized', not a proof of pure truth level). The
            Delphes-routing advice forks on search-vs-measurement (detector-fidelity.md), read off the
            routine's .info Keywords (search/susy/bsm/exotica) + the id name patterns (_SUSY_/_SUS_/
            _EXOT_/_EXO_):
              · MEASUREMENT/fiducial routine → particle-level BY DESIGN; do NOT run Delphes (the result
                is already unfolded — applying detector effects would be physically wrong). Truth-to-truth.
              · BSM SEARCH with no self-smearing → truth-level search; route to SimpleAnalysis/Delphes
                (tune object efficiencies to the published curves) or mark the result approximate.
            Never read a WARN routine's SRs as detector-level BSM acceptance.
  - FAIL  = the routine source could not be located/read (unusable input: bad --routine/--cc, or the
            .cc is missing under the installed Rivet share). Nothing to verify.

Like validate_cutflow.py the verdict is the authority and is written to JSON; exit code is 0 for any
produced verdict (PASS/WARN/FAIL all exit 0 — the benchmark gate parses the `verdict` field), nonzero
only when arguments are unusable before any verdict can be formed.

Usage:
  verify_smearing.py --routine ATLAS_2016_I1458270 --out framework/validation/NAME.md
  verify_smearing.py --routine MyRoutine --cc /path/to/MyRoutine.cc --out OUT.md
"""
import argparse, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Where the installed Rivet routines live in the `rivet` conda env's share dir.
RIVET_SHARE = os.path.join(
    ROOT, "stages", "01-event-generation", "build", "tools",
    "miniforge3", "envs", "rivet", "share", "Rivet")

# Detector-projection signatures, grouped by strength.
#   strong  = Smeared* projections: resolution smearing + (for particles/jets) reco efficiency folded
#             in. Presence of any ONE of these ⇒ detector-level ⇒ PASS.
#   efficiency = an efficiency-bearing projection WITHOUT resolution smearing (a partial detector
#             treatment). Counted, surfaced in the note, but on its own does NOT earn PASS — it warns.
STRONG_SIGS = {
    "SmearedJets":     re.compile(r"\bSmearedJets\b"),
    "SmearedParticles": re.compile(r"\bSmearedParticles\b"),
    "SmearedMET":      re.compile(r"\bSmearedMET\b"),
    "SmearedFinalState": re.compile(r"\bSmearedFinalState\b"),
}
# Efficiency-only signatures: a ParticleEffFilter / efficiency lambda, or use of a reco-efficiency
# constant (e.g. *_RECOEFF_*, *_EFF_*) outside a Smeared* call. These indicate SOME detector
# treatment but not full smearing — flagged for review, never auto-PASS on their own.
EFF_SIGS = {
    "ParticleEffFilter": re.compile(r"\bParticleEffFilter\b"),
    "JetEffFilter":      re.compile(r"\bJetEffFilter\b"),
    "Efficiency-projection": re.compile(r"\bEfficiency\s*\("),
    "reco-eff-constant": re.compile(r"\b[A-Z0-9]+_(?:RECOEFF|EFF)_[A-Z0-9_]+\b"),
}

# Era / experiment fingerprints — read off the smearing/efficiency constant names that Rivet ships
# (e.g. JET_SMEAR_ATLAS_RUN2, ELECTRON_RECOEFF_ATLAS_RUN2, MUON_SMEAR_CMS_RUN2). Best-effort only:
# the note says which era the constants name, so a reviewer can confirm it matches the analysis's
# data-taking period (a wrong-era smearing constant is a real fidelity bug this surfaces, softly).
# No \b anchors: the era token is embedded in a longer identifier (…_ATLAS_RUN2_LOOSE), and `_` is a
# word char so \b never fires between `_` and `ATLAS`/after `RUN2`. Match the bare token instead.
ERA_SIG = re.compile(r"(?:ATLAS|CMS)_RUN[0-9]")

# Search-vs-measurement discriminator (Delphes-policy fork, detector-fidelity.md §"Default: do NOT run
# Delphes"). A non-smearing routine is only Delphes-warranted if it is a BSM SEARCH; a non-smearing
# MEASUREMENT/fiducial routine is particle-level by design and must NOT be sent through Delphes (it is
# already unfolded). We read the routine's .info Keywords (search/susy/bsm/exotica) and fall back to the
# Inspire-style id name patterns (_SUSY_/_SUS_/_EXOT_/_EXO_) when no .info is available/conclusive.
SEARCH_KEYWORDS = re.compile(r"\b(?:search|susy|bsm|exotica|exotic)\b", re.I)
SEARCH_NAME_PAT = re.compile(r"_(?:SUSY|SUS|EXOT|EXO)_", re.I)

# C/C++ comment + string/char-literal stripper. Matches (in priority order) line comments, block
# comments, double-quoted strings, and single-quoted char literals; each is replaced by a single space
# so token boundaries are preserved. Source scanned AFTER this strip so a `Smeared*` that appears only
# inside a `// ...` comment or a "..." string literal can never be mistaken for a real projection.
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_STRIP_RE = re.compile(
    r"""//[^\n]*            # line comment
      | /\*.*?\*/           # block comment (non-greedy, spans newlines via DOTALL)
      | "(?:\\.|[^"\\])*"   # double-quoted string literal (handles escaped quotes)
      | '(?:\\.|[^'\\])*'   # single-quoted char literal
    """,
    re.DOTALL | re.VERBOSE,
)


def strip_comments(src):
    """Return `src` with C/C++ comments (// … and /* … */) blanked to a space, string literals kept.

    Used for the STRUCTURAL declare(Smeared...(...), "name") scan: a real projection's quoted name is a
    string literal we must keep, but a declare-shaped line sitting inside a `// comment` must NOT count
    (the comment-only false-PASS). Blanking comments alone removes the latter without losing the former."""
    return _COMMENT_RE.sub(" ", src)


def strip_comments_and_strings(src):
    """Return `src` with C/C++ comments AND string/char literals blanked to a space.

    Why: the bare-token regexes (and the bare `Smeared*` search) cannot tell code from prose, so a
    routine that merely *mentions* `SmearedJets` in a `// comment` or a "string literal" would score a
    false PASS (a truth-level routine laundered into 'detector-level'). Stripping first removes that
    whole class of false positives while leaving real `declare(SmearedJets(...), "RecoJets")` code
    intact (its quoted name is recovered by the separate comments-only pass, strip_comments)."""
    return _STRIP_RE.sub(" ", src)


def find_cc(routine, cc):
    """Resolve the routine .cc path. Explicit --cc wins; else look under the installed Rivet share.
    Returns (path, note) where path is None if nothing readable was found."""
    if cc:
        if os.path.isfile(cc):
            return cc, f"explicit --cc {cc}"
        return None, f"--cc path does not exist: {cc}"
    cand = os.path.join(RIVET_SHARE, f"{routine}.cc")
    if os.path.isfile(cand):
        return cand, f"installed Rivet share: {cand}"
    return None, (f"no source for routine '{routine}': not at {cand} and no --cc given "
                  f"(is the routine name right / installed in the rivet env?)")


def classify_routine_kind(routine, cc_path):
    """Decide whether a routine is a BSM SEARCH or a MEASUREMENT/fiducial routine.

    Drives the WARN (non-smearing) branch's Delphes-routing advice (detector-fidelity.md): a
    non-smearing SEARCH is the only Delphes-warranted case; a non-smearing MEASUREMENT is particle-level
    by design (already unfolded) and must NOT be sent through Delphes. Signal, in order:
      1. the sibling `.info` Keywords (search/susy/bsm/exotica) — the authoritative source;
      2. the routine-id name patterns (_SUSY_/_SUS_/_EXOT_/_EXO_) as a fallback when no .info is found.
    Returns ("search"|"measurement", note) — defaults to "measurement" (the 94.8% majority) when no
    search signal is found, so the conservative 'do not Delphes' advice is the default."""
    # 1) sibling .info Keywords (next to the .cc if installed; else next to an explicit --cc).
    info = os.path.splitext(cc_path)[0] + ".info" if cc_path else ""
    if not (info and os.path.isfile(info)):
        cand = os.path.join(RIVET_SHARE, f"{routine}.info")
        info = cand if os.path.isfile(cand) else ""
    if info:
        try:
            meta = open(info, errors="replace").read()
        except OSError:
            meta = ""
        m = SEARCH_KEYWORDS.search(meta)
        if m:
            return "search", f".info Keywords match '{m.group(0).lower()}'"
        # an .info exists and has NO search keyword → trust it as a measurement.
        if "Keywords" in meta:
            return "measurement", ".info Keywords carry no search/susy/bsm/exotica term"
    # 2) fall back to the routine-id name pattern.
    nm = SEARCH_NAME_PAT.search(routine)
    if nm:
        return "search", f"routine-id name pattern '{nm.group(0)}'"
    return "measurement", "no .info search keyword and no _SUSY_/_EXOT_ name pattern (default)"


def scan(raw_src):
    """Scan routine source → dict of findings: strong projections, efficiency-only signals, eras.

    Two passes over the source:
      • the bare-token scans (strong/eff/era) run on the COMMENT+STRING-STRIPPED source, so a
        `Smeared*` (or an era/eff constant) that appears only in prose cannot register; and
      • the STRUCTURAL declared-projection scan — declare(Smeared...(...), "Name") — runs on the
        COMMENT-stripped (but string-KEPT) source, because the quoted projection name it anchors on is
        itself a string literal we must keep, while a declare-shaped line inside a `// comment` must NOT
        count. The structural form requires the full declare(...) call syntax, so it is not foolable by
        a bare token the way the token scan was.
    PASS is gated on `declared` (this structural match), not on the strong-token booleans."""
    src = strip_comments_and_strings(raw_src)
    strong = {name: bool(rx.search(src)) for name, rx in STRONG_SIGS.items()}
    eff = {name: bool(rx.search(src)) for name, rx in EFF_SIGS.items()}
    # eras: dedup, preserve first-seen order
    eras = []
    for m in ERA_SIG.finditer(src):
        if m.group(0) not in eras:
            eras.append(m.group(0))
    # the specific declared object projections (for the note + the PASS gate): the structural
    # declare(Smeared...(...), "Name") wired into init(). `[\s\S]*?` (not `[^;]`) so the inner argument
    # list may span newlines AND contain `;` (e.g. a Jets-efficiency lambda body `return 0.;`); the
    # non-greedy match stops at the first following `, "name")`. Run on COMMENT-stripped source so a
    # declare-shaped line in a comment cannot match, while the real string-literal name is preserved.
    decl_src = strip_comments(raw_src)
    declared = []
    for m in re.finditer(r'declare\(\s*(Smeared\w+)\s*\([\s\S]*?\)\s*,\s*"([^"]+)"\s*\)', decl_src):
        declared.append(f'{m.group(1)}→"{m.group(2)}"')
    return {"strong": strong, "eff": eff, "eras": eras, "declared": declared}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--routine", required=True, help="Rivet routine id, e.g. ATLAS_2016_I1458270")
    ap.add_argument("--cc", default="", help="explicit path to the routine .cc (overrides the "
                    "installed-share lookup; use for an uninstalled/local routine)")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cc_path, src_note = find_cc(args.routine, args.cc)
    label = args.label or args.routine

    routine_kind, routine_kind_note = None, None
    if cc_path is None:
        # Unusable input: no source to verify. FAIL verdict, nonzero exit (mirrors validate_cutflow's
        # unreadable-input behaviour — a verdict the gate can parse is still written first).
        verdict = "FAIL"
        findings = {"strong": {}, "eff": {}, "eras": [], "declared": []}
        reason = src_note
        strong_found, eff_found = [], []
    else:
        try:
            src = open(cc_path, errors="replace").read()
        except OSError as e:
            sys.exit(f"ERROR: cannot read routine source {cc_path}: {e}")
        findings = scan(src)
        strong_found = [n for n, hit in findings["strong"].items() if hit]
        eff_found = [n for n, hit in findings["eff"].items() if hit]
        # PASS is gated on the STRUCTURAL declaration, not the bare token: a real
        # declare(SmearedJets(...), "RecoJets") wired into init() (findings["declared"]), so a Smeared*
        # that survives only as a free-standing token (e.g. a typedef/forward-decl, or anything the
        # comment/string strip couldn't reach) cannot by itself earn 'detector-level'.
        if findings["declared"]:
            verdict = "PASS"
            reason = (f"detector-level: declares {', '.join(findings['declared'])}"
                      + (f"; era={'/'.join(findings['eras'])}" if findings["eras"] else
                         "; era=UNKNOWN (no ATLAS/CMS_RUNx constant name found — confirm by hand)"))
        else:
            verdict = "WARN"
            routine_kind, routine_kind_note = classify_routine_kind(args.routine, cc_path)
            kind = routine_kind
            # The Delphes-routing fork (detector-fidelity.md): a non-smearing MEASUREMENT is
            # particle-level by design (already unfolded → do NOT Delphes); a non-smearing BSM SEARCH is
            # the only Delphes-warranted case (route to SimpleAnalysis/Delphes or mark approximate).
            if kind == "measurement":
                route = (f"measurement/fiducial routine ({routine_kind_note}): particle-level by design; "
                         f"do NOT run Delphes (already unfolded). Compare truth-to-truth.")
            else:
                route = (f"BSM search ({routine_kind_note}) with no self-smearing: truth-level search; "
                         f"route to SimpleAnalysis/Delphes or mark approximate.")
            if eff_found:
                reason = (f"particle-level with efficiency-only signal(s) {', '.join(eff_found)} but no "
                          f"structurally-declared Smeared* projection — partial detector treatment, NOT "
                          f"full smearing. {route} Do not read SRs as detector-level acceptance.")
            else:
                reason = (f"particle-level: no structurally-declared Smeared* and no RECOGNIZED "
                          f"smearing/efficiency projection (a custom idiom may still be present). The "
                          f"Rivet path gives a fiducial/truth result. {route}")

    # --- markdown report (mirrors validate_cutflow.py: header + table + reasoning + bold verdict) ---
    lines = [f"# Detector-smearing verification — {args.routine} · {label}", "",
             "The Rivet-path fidelity gate: a routine is detector-level only if it STRUCTURALLY declares "
             "its own Smeared* / efficiency projections (declare(SmearedJets(...), \"name\") — folding "
             "the experiment's object resolution + reco efficiency at the analysis level; a bare token "
             "in a comment or string does not count). No such declaration ⇒ the routine runs at truth "
             "(particle) level and its SRs are fiducial, not detector-level BSM acceptance.", "",
             f"- routine source: `{cc_path or '— NOT FOUND —'}` ({src_note})", ""]
    lines += ["| signature | kind | found |", "|---|---|---|"]
    for name, hit in findings["strong"].items():
        lines.append(f"| {name} | strong (smearing) | {'✓' if hit else '·'} |")
    for name, hit in findings["eff"].items():
        lines.append(f"| {name} | efficiency-only | {'✓' if hit else '·'} |")
    if findings["declared"]:
        lines += ["", "Declared detector projections: " +
                  ", ".join(f"`{d}`" for d in findings["declared"]) + "."]
    if findings["eras"]:
        lines += ["", f"Era/experiment fingerprint(s) from constant names: "
                  f"**{', '.join(findings['eras'])}** — confirm this matches the analysis's "
                  f"data-taking period (a wrong-era smearing constant is a fidelity bug)."]
    lines += ["", f"**Verdict: {verdict}.** {reason}"]
    if verdict == "PASS":
        lines.append("The Rivet path is correct for this routine — its yields fold detector response. "
                     "(This certifies the detector PATH, not per-SR acc×eff — for that use the "
                     "published-acc×eff cert on the SimpleAnalysis/Delphes path.)")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w").write("\n".join(lines) + "\n")
    json.dump({"routine": args.routine, "label": label, "verdict": verdict,
               "cc_path": cc_path, "source_note": src_note, "reason": reason,
               "strong_projections": strong_found, "efficiency_signals": eff_found,
               "eras": findings["eras"], "declared_projections": findings["declared"],
               "routine_kind": routine_kind, "routine_kind_note": routine_kind_note},
              open(args.out.replace(".md", ".json"), "w"), indent=2)

    flag = "" if verdict == "PASS" else "  <-- not detector-level (see verdict)"
    print(f"{verdict}: {args.routine} -> {args.out}{flag}")
    print(f"  source: {cc_path or 'NOT FOUND'}")
    print(f"  strong: {strong_found or '(none)'}  eff-only: {eff_found or '(none)'}  "
          f"era: {findings['eras'] or '(unknown)'}")
    print(f"  {reason}")


if __name__ == "__main__":
    main()
