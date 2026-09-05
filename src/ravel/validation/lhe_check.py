#!/usr/bin/env python3
"""Pre-shower LHE sanity guard (stdlib-only; reads .lhe or .lhe.gz).

Run this between MadGraph and Pythia — the failure modes it catches are the ones that
otherwise fail SILENTLY downstream (exit 0, plausible-but-wrong yields; see
.claude/rules/madgraph-pythia.md and docs/workflow/checklists/model-cards.md):

  * WRONG GENERATED MASS (--expect-mass PDG:MASS, repeatable): for MSSM_SLHA2 the MASS
    block is overridden by MSOFT/HMIX, so a card that *says* 300 can generate 181. The
    check reads the FIRST event's particle masses (the ground truth of what was generated)
    and the banner's SLHA MASS block, asserting both within --mass-tol (default 1 GeV).
  * MISSING MODSEL: without `Block MODSEL` (1 1) Pythia keeps internal SUSY off. Measured
    nuance (Pythia 8.31x, this pipeline's certified runs): explicit SLHA DECAY tables WITH
    branching-ratio rows in the banner still decay fine (`SLHA:useDecayTable = on` imports
    them regardless of MODSEL), but particles whose card has width-only DECAY entries (no
    BR rows) rely on Pythia's internal SUSY machinery and will NOT decay -> empty SRs.
    MadGraph does NOT inject MODSEL into the banner — only what the input card carries.
    Default WARN; make it fatal with --require-modsel.
  * WEIGHT SIGN: the first N (--n-events, default 200) events must carry one weight sign
    (mixed signs at LO = misconfiguration; NLO samples legitimately mix — then this guard
    does not apply). Reports sigma from the <init> block.
  * MULTIWEIGHT (<rwgt>/<wgt> tags): single-weight pipelines must run
    `rivet --skip-weights` and generate with use_syst=False (docs/workflow/steps/04-analyze.md).
  * MERGED vs UNMERGED (run-card ickkw): ickkw=1 -> "MERGED (use pythia_shower_merged)";
    plain `pythia_shower` would double-count the ME jets. Absent/0 -> plain shower.

Exit nonzero on any failed assertion; everything is printed as a one-screen report.

A JSON sidecar is ALWAYS written (default <lhe>.lhe_check.json, --json-out overrides) with
the earned verdict + every check — validate_run_state.py's lhe-check-before-shower invariant
(A1) gates shower products on exactly this artifact, so a shower that skipped the guard is a
lifecycle FAIL, not a silent omission.

Usage:
  lhe_check.py EVENTS.lhe[.gz] [--expect-mass 1000021:1000] [--expect-mass 1000022:100]
               [--mass-tol 1.0] [--require-modsel] [--n-events 200] [--json-out PATH]
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

import argparse
import gzip
import json
import math
import os
import re
import sys


def opener(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", errors="replace")
    return open(path, "rt", errors="replace")


def parse_param_card(path):
    """CR-021 card preflight: read the INPUT param card directly (never hand-typed numbers).

    Returns (mass_by_pdg, lint) where lint = [(severity, message)]:
      FAIL  width-only DECAY table (total width, ZERO BR rows) for a BSM particle — the C1
            silent killer: Pythia imports nothing, sparticles never decay, SRs empty, exit 0.
      FAIL  unrendered {{placeholder}} anywhere in the card (the {{ecms}} crash class).
      WARN  MSSM-style MSOFT/HMIX blocks present — the MASS block is OVERRIDDEN for gauginos/
            higgsinos (T11): the derived spectrum, not MASS, is what generates; the banner-mass
            cross-check downstream is the real arbiter.
    """
    mass, lint = {}, []
    txt = open(path, errors="replace").read()
    if "{{" in txt:
        ph = sorted(set(re.findall(r"\{\{[^}]+\}\}", txt)))
        lint.append(("FAIL", f"unrendered placeholder(s) {ph} — the card never went through "
                             f"the renderer ({{ecms}} crash class)"))
    block, decay_pdg, decay_rows = None, None, {}
    for raw in txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("block"):
            block = low.split()[1] if len(low.split()) > 1 else ""
            decay_pdg = None
            continue
        if low.startswith("decay"):
            parts = line.split()
            try:
                decay_pdg = abs(int(parts[1]))
                decay_rows.setdefault(decay_pdg, 0)
            except (IndexError, ValueError):
                decay_pdg = None
            block = None
            continue
        if block == "mass":
            parts = line.split()
            try:
                mass[abs(int(parts[0]))] = float(parts[1])
            except (IndexError, ValueError):
                pass
        elif decay_pdg is not None:
            # any non-empty line inside a DECAY table = a BR row
            decay_rows[decay_pdg] += 1
    widthonly = sorted(p for p, n in decay_rows.items() if n == 0 and p >= 1000000)
    # severity is decided in main(): width-only on a PRODUCED state (present in the events) is
    # the C1 empty-SR killer -> FAIL; on unproduced spectators it is harmless -> compact WARN.
    if widthonly:
        lint.append(("WIDTHONLY", widthonly))
    if re.search(r"(?im)^block\s+msoft\b", txt) or re.search(r"(?im)^block\s+hmix\b", txt):
        lint.append(("WARN", "MSOFT/HMIX present: gaugino/higgsino masses derive from them and "
                             "OVERRIDE the MASS block (T11) — trust the banner-mass cross-check "
                             "below, not the card's MASS lines, for those states"))
    if not mass:
        lint.append(("FAIL", "no parsable Block MASS in the card"))
    return mass, lint


def parse_banner_slha_mass(banner):
    """PDG -> mass from the banner's SLHA MASS block (between 'Block mass' and the next block)."""
    masses = {}
    in_mass = False
    for line in banner:
        s = line.split("#")[0].strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("block") or low.startswith("decay"):
            in_mass = low.startswith("block") and low.split()[1].startswith("mass")
            continue
        if in_mass:
            parts = s.split()
            if len(parts) >= 2:
                try:
                    masses[abs(int(parts[0]))] = float(parts[1])
                except ValueError:
                    pass
    return masses


def parse_banner_slha_width(banner):
    """PDG -> total width from the banner's SLHA 'DECAY <pdg> <width>' headers (CR-007)."""
    widths = {}
    for line in banner:
        m = re.match(r"\s*decay\s+(-?\d+)\s+([0-9.eE+-]+)", line.split("#")[0], re.I)
        if m:
            try:
                widths[abs(int(m.group(1)))] = float(m.group(2))
            except ValueError:
                pass
    return widths


def parse_run_card_value(banner, key):
    """The run-card line '<value> = <key>' from the banner; None if absent."""
    pat = re.compile(rf"^\s*(\S+)\s*=\s*{key}\b", re.I)
    for line in banner:
        m = pat.match(line)
        if m:
            return m.group(1)
    return None


def parse_init_sigma(init_lines):
    """Sum of XSECUP (pb) over the process lines of the <init> block; None if unparseable."""
    sigma = None
    for line in init_lines[1:]:  # line 0 = beam line
        parts = line.split()
        if len(parts) >= 4:
            try:
                sigma = (sigma or 0.0) + float(parts[0])
            except ValueError:
                pass
    return sigma


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lhe", help="LHE file (.lhe or .lhe.gz)")
    ap.add_argument("--expect-from-card", default=None, metavar="PARAM_CARD",
                    help="CR-021 card preflight: derive the expected masses FROM the card "
                         "itself (never hand-typed — the 181-as-300 near-miss class) for every "
                         "BSM PDG in the first event, AND lint the card: width-only DECAY "
                         "tables (the C1 empty-SR killer), unrendered {{placeholders}}, and the "
                         "MASS-vs-MSOFT override note for MSSM_SLHA2")
    ap.add_argument("--expect-mass", action="append", default=[], metavar="PDG:MASS",
                    help="assert this PDG's mass (first event + banner MASS block) within "
                         "--mass-tol; repeatable, e.g. --expect-mass 1000021:1000")
    ap.add_argument("--mass-tol", type=float, default=1.0, help="GeV (default 1)")
    ap.add_argument("--require-modsel", action="store_true",
                    help="missing 'Block MODSEL' is an ERROR instead of a WARN")
    ap.add_argument("--n-events", type=int, default=200,
                    help="events scanned for weight-sign / multiweight checks (default 200)")
    ap.add_argument("--json-out", default=None,
                    help="sidecar JSON path (default <lhe>.lhe_check.json)")
    args = ap.parse_args()

    expects = []
    for em in args.expect_mass:
        try:
            pdg, mass = em.split(":")
            expects.append((abs(int(pdg)), float(mass)))
        except ValueError:
            sys.exit(f"ERROR: bad --expect-mass {em!r} (want PDG:MASS, e.g. 1000021:1000)")

    card_expects, card_lint = {}, []
    if args.expect_from_card:
        card_expects, card_lint = parse_param_card(args.expect_from_card)

    banner, init_lines = [], []
    first_event_masses = {}          # abs(pdg) -> list of masses in the FIRST event
    weights, n_events = [], 0
    multiweight = False
    wgt_pat = re.compile(r"<(rwgt|wgt|initrwgt)[\s>]")
    in_init = in_event = False
    event_lines = []

    with opener(args.lhe) as fh:
        for line in fh:
            if not in_event and n_events == 0:
                banner.append(line)
            if wgt_pat.search(line):
                multiweight = True
            stripped = line.strip()
            if stripped.startswith("<init"):
                in_init = True
                continue
            if stripped.startswith("</init"):
                in_init = False
                continue
            if in_init:
                init_lines.append(line)
                continue
            if stripped.startswith("<event"):
                in_event, event_lines = True, []
                continue
            if stripped.startswith("</event"):
                in_event = False
                n_events += 1
                if event_lines:
                    try:
                        weights.append(float(event_lines[0].split()[2]))
                    except (IndexError, ValueError):
                        pass
                    if n_events == 1:  # particle masses from the FIRST event
                        for pl in event_lines[1:]:
                            parts = pl.split()
                            if len(parts) >= 11 and not pl.lstrip().startswith("<"):
                                try:
                                    first_event_masses.setdefault(
                                        abs(int(parts[0])), []).append(float(parts[10]))
                                except ValueError:
                                    pass
                if n_events >= args.n_events:
                    break
                continue
            if in_event and not stripped.startswith("<"):
                event_lines.append(line)

    if n_events == 0:
        sys.exit(f"ERROR: no <event> blocks found in {args.lhe}")

    fails, report, checks = [], [], []

    def note(level, name, msg):
        """One check = one printed report line AND one sidecar record (same content)."""
        report.append(f"[{level}] {msg}")
        checks.append({"name": name, "level": level, "msg": msg})

    banner_mass = parse_banner_slha_mass(banner)
    banner_width = parse_banner_slha_width(banner)
    sigma = parse_init_sigma(init_lines)

    # --- CR-021 card preflight: card-derived expectations + card lint ---------------------
    if card_lint:
        for sev, msg in card_lint:
            if sev == "WIDTHONLY":
                produced = sorted(set(msg) & set(first_event_masses))
                spectators = [p for p in msg if p not in first_event_masses]
                if produced:
                    note("FAIL", "card-widthonly-produced",
                         f"card: width-only DECAY (no BR rows) for PRODUCED "
                         f"PDG {produced} — Pythia imports nothing, they will NOT "
                         f"decay (empty SRs, exit 0; catalogue C1)")
                    fails.append("card lint (produced width-only DECAY)")
                if spectators:
                    note("WARN", "card-widthonly-spectators",
                         f"card: {len(spectators)} unproduced BSM state(s) "
                         f"carry width-only DECAY tables — harmless unless produced "
                         f"(first few: {spectators[:4]})")
                continue
            note(sev, "card-lint", f"card: {msg}")
            if sev == "FAIL":
                fails.append("card lint")
    if card_expects:
        already = {p for p, _ in expects}
        derived = []
        for pdg in sorted(first_event_masses):
            if pdg >= 1000000 and pdg in card_expects and pdg not in already:
                expects.append((pdg, card_expects[pdg]))
                derived.append(f"{pdg}:{card_expects[pdg]:g}")
        note("PASS", "card-derived-expectations",
             f"card-derived expectations for {len(derived)} BSM PDG(s) in the "
             f"first event: {', '.join(derived) or '(none present)'} "
             f"(--expect-from-card; hand-typed --expect-mass takes precedence)")

    # --- expected masses -----------------------------------------------------------------
    for pdg, want in expects:
        seen = first_event_masses.get(pdg)
        bm = banner_mass.get(pdg)
        # WIDTH-AWARE event tolerance (CR-007; FAILURE-CATALOGUE C2): the event-record mass of
        # a wide resonance is Breit-Wigner-distributed (spread ~ Gamma) while the banner mass
        # is exact -- a fixed +-1 GeV falsely FAILs wide s-channel signals (Gamma ~ 30-50 GeV).
        # The banner's own 'DECAY <pdg> <width>' supplies Gamma: event tolerance widens to
        # max(--mass-tol, 3*Gamma); the banner-mass check stays at the tight --mass-tol.
        gamma = banner_width.get(pdg, 0.0)
        ev_tol = max(args.mass_tol, 3.0 * gamma)
        where = []
        ok = True
        if seen:
            worst = max(abs(m - want) for m in seen)
            where.append(f"event1 m={seen[0]:g}" + ("" if len(seen) == 1 else f" (x{len(seen)})"))
            if worst > ev_tol:
                ok = False
        if bm is not None:
            where.append(f"banner MASS m={bm:g}")
            if abs(bm - want) > args.mass_tol:
                ok = False
        if not seen and bm is None:
            ok = False
            where.append("NOT FOUND in first event or banner MASS block")
        tag = "PASS" if ok else "FAIL"
        tol_note = (f" (event tol 3*Gamma={ev_tol:g})" if ev_tol > args.mass_tol else "")
        note(tag, f"mass-{pdg}",
             f"mass {pdg}: expect {want:g} +- {args.mass_tol:g} GeV{tol_note} | "
             + "; ".join(where))
        if not ok:
            fails.append(f"mass check pdg={pdg}")

    # --- MODSEL --------------------------------------------------------------------------
    has_modsel = any(re.match(r"\s*block\s+modsel", ln, re.I) for ln in banner)
    if has_modsel:
        note("PASS", "modsel", "banner SLHA carries 'Block MODSEL'")
    else:
        msg = ("banner has NO 'Block MODSEL' — Pythia keeps internal SUSY off. Explicit DECAY "
               "tables with BR rows still apply (SLHA:useDecayTable=on), but width-only entries "
               "will NOT decay (empty SRs). MadGraph does not add MODSEL for you.")
        if args.require_modsel:
            note("FAIL", "modsel", msg)
            fails.append("MODSEL missing (--require-modsel)")
        else:
            note("WARN", "modsel", msg)

    # --- weight sign ---------------------------------------------------------------------
    npos = sum(1 for w in weights if w > 0)
    nneg = sum(1 for w in weights if w < 0)
    nzer = len(weights) - npos - nneg
    sig_s = f"; sigma(init)={sigma:g} pb" if sigma is not None else "; sigma(init) unparsed"
    # CR-018 adjudication (2026-07-07): at LO/single-weight the sign check is FRACTIONAL, not
    # binary — rare negatives (<=0.2% typical) are the known-benign signature of a
    # non-positive-definite PDF set (e.g. NNPDF NLO, lhaid 260000) sampling large-x sea
    # antiquarks (verified sign(w)=sign(f1*f2) on the full 50k reference). Magnitude carries no
    # signal in unweighted files (weights quantize to +-sigma-hat), so it is not part of the
    # criterion. The nneg>=3 count guard keeps small windows sane (1/200 must WARN, not FAIL).
    frac = nneg / len(weights) if weights else 0.0
    if nzer:
        note("FAIL", "weight-sign",
             f"weights: {npos} positive / {nneg} negative / {nzer} ZERO in first "
             f"{len(weights)} events — zero weights = corruption/misconfiguration{sig_s}")
        fails.append("weight sign (zero weights)")
    elif npos and nneg and nneg >= 3 and frac > 0.005:
        note("FAIL", "weight-sign",
             f"weights: {npos} positive / {nneg} negative ({100*frac:.2f}%) in "
             f"first {len(weights)} events — above the 0.5% negative-PDF ceiling for LO "
             f"single-weight samples: NLO contamination or misconfiguration{sig_s}")
        fails.append("weight sign")
    elif npos and nneg:
        note("WARN", "weight-sign",
             f"weights: {nneg}/{len(weights)} negative ({100*frac:.2f}%) — "
             f"known-benign at LO with a non-positive-definite PDF set (e.g. NNPDF NLO, "
             f"lhaid 260000) sampling large-x sea antiquarks (CR-018). Net sigma effect "
             f"~ -2x{100*frac:.2f}%. Verify pdlabel/lhaid if unexpected{sig_s}")
    else:
        note("PASS", "weight-sign",
             f"weights: all {len(weights)} scanned events one sign "
             f"({'+' if npos else '-'}){sig_s}")

    # --- multiweight ---------------------------------------------------------------------
    if multiweight:
        note("WARN", "multiweight",
             "multiweight LHE (<rwgt>/<wgt>/<initrwgt> tags present): a "
             "single-weight pipeline must run `rivet --skip-weights` (and regenerate "
             "with use_syst=False) — see docs/workflow/steps/04-analyze.md")
    else:
        note("PASS", "multiweight", "single-weight LHE (no <rwgt>/<wgt> tags in scanned events)")

    # --- merged vs unmerged --------------------------------------------------------------
    ickkw = parse_run_card_value(banner, "ickkw")
    xqcut = parse_run_card_value(banner, "xqcut")
    if ickkw is not None and ickkw.split(".")[0].lstrip("+-").isdigit() and int(float(ickkw)) == 1:
        note("INFO", "merging-mode",
             f"run card ickkw=1, xqcut={xqcut or '?'} -> MERGED "
             "(use pythia_shower_merged with qCut >= xqcut; plain pythia_shower "
             "would double-count ME jets; the init sigma above is the PRE-matching "
             "multiplicity sum — the matched sigma comes from the shower log)")
    else:
        note("INFO", "merging-mode",
             f"run card ickkw={ickkw if ickkw is not None else 'absent'} -> "
             "unmerged (plain pythia_shower)")

    print(f"lhe_check: {args.lhe}  ({n_events} events scanned)")
    for ln in report:
        print("  " + ln)

    # --- sidecar (ALWAYS written; the lhe-check-before-shower invariant gates on it) -------
    # verdict is EARNED, never defaulted: FAIL unless checks exist and none is level FAIL.
    verdict = "PASS" if all(c["level"] != "FAIL" for c in checks) and checks else "FAIL"
    out = args.json_out or (os.path.abspath(args.lhe) + ".lhe_check.json")
    rec = {"schema_version": 1, "generated_by": "lhe_check.py",
           "generated_utc": os.environ.get("LHE_CHECK_UTC", ""),
           "lhe": os.path.abspath(args.lhe), "verdict": verdict, "checks": checks}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    print(f"lhe_check sidecar -> {out} (verdict={verdict})")

    if fails:
        print(f"RESULT: FAIL ({', '.join(fails)})")
        sys.exit(1)
    print("RESULT: OK")


if __name__ == "__main__":
    main()
