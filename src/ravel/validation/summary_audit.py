#!/usr/bin/env python3
"""summary_audit.py -- the SUMMARY-PLOT physics-completeness gate (rules R-SA1..8;
docs/reference/scope.md Sec 7 / CR-031).

Layout lint (`plot_lint.py`) checks a figure LOOKS right; it cannot see whether the figure is
PHYSICS-complete -- every candidate the survey found accounted for, no curve mislabeled against
its own final state, superseded results not drawn co-equal with their successor, coverage gaps
consistent with what's actually drawn. A defective HVT Z'->WW summary plot shipped with exactly
these defects (F1..F4 in benchmarks/capabilities.json) with nothing to catch it; this is that
gate. Until it is green a `summary_plot` deliverable is a declared PARTIAL, never 'served'.

GENERAL by construction: every rule below reads FIELDS off the survey candidates / manifest
curves it is given -- schema enums, cross-references, and a small generic HEP final-state
taxonomy (semileptonic / fully-leptonic / fully-hadronic -- standard diboson-search vocabulary,
not any one paper's title or arXiv id). Nothing here names a specific analysis, model, or number.

Reads (schema additions this task introduces -- see the two *_doc() schemas below or
docs/workflow/checklists/summary-plot.md):
  survey.json   candidates[].disposition = {state, reason, reason_class, reviewer, superseded_by}
                candidates[].provenance  = "digitized" | "hepdata-machine"
  basis_manifest.json  curves[].survey_id  = back-ref into survey candidates[].id
                        curves[].provenance = "digitized" | "hepdata-machine" (must == the
                                              referenced candidate's)
                        curves[].draw       = "primary" | "crosscheck" | "none"

Usage:
  summary_audit.py --rundir <dir> [--check]              # <dir>/outputs/survey.json +
                                                           # <dir>/inputs/basis_manifest.json
  summary_audit.py --survey <survey.json> --manifest <basis_manifest.json> [--out <path>]
  summary_audit.py --selftest

Writes <rundir>/outputs/summary_audit.json (or --out): a per-rule PASS/FAIL record + the
offending items each rule named, plus an overall verdict.

Exit codes: 0 PASS  *  2 usage / artifact missing / invalid JSON  *  3 physics-FAIL (>=1 rule FAIL)
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = 1

DISPOSITION_STATES = ("plotted", "excluded", "superseded")
REASON_CLASSES = ("physics", "out-of-range")   # the ONLY reason_class values a state==excluded
                                                # candidate may carry -- R-SA3
PROVENANCE_VALUES = ("digitized", "hepdata-machine")
DRAW_VALUES = ("primary", "crosscheck", "none")

# A small, GENERAL diboson/dilepton final-state taxonomy -- standard particle-physics decay-mode
# vocabulary applicable to any semileptonic/fully-leptonic/fully-hadronic resonance search, not a
# per-paper literal. R-SA4 derives its forbidden-label set from whichever of these families a
# CANDIDATE's own `final_state` text declares -- nothing here is keyed to a specific candidate id.
CHANNEL_LEXICON = {
    "l-nu-qq":        "semileptonic",
    "l-nu-qqbar":     "semileptonic",
    "lvqq":           "semileptonic",
    "semileptonic":   "semileptonic",
    "semi-leptonic":  "semileptonic",
    "e-nu-mu-nu":     "fully-leptonic",
    "fully leptonic": "fully-leptonic",
    "fully-leptonic": "fully-leptonic",
    "dilepton":       "fully-leptonic",
    "qqqq":           "fully-hadronic",
    "qqbar-qqbar":    "fully-hadronic",
    "fully hadronic": "fully-hadronic",
    "fully-hadronic": "fully-hadronic",
}

_BELOW_RE = re.compile(r"below\s+([\d.]+)\s*ge?v", re.IGNORECASE)


# --------------------------------------------------------------------------- #
#  small helpers
# --------------------------------------------------------------------------- #

def _candidate_index(survey):
    idx = {}
    for c in survey.get("candidates", []) or []:
        cid = c.get("id")
        if cid:
            idx[cid] = c
    return idx


def _own_families(final_state_text):
    text = (final_state_text or "").lower()
    return {fam for tok, fam in CHANNEL_LEXICON.items() if tok in text}


def _forbidden_tokens(final_state_text):
    """Tokens from every family the candidate's OWN final_state does NOT declare. Empty if the
    final_state text matches none of the lexicon -- a conservative no-op, never a guess."""
    own = _own_families(final_state_text)
    if not own:
        return set()
    return {tok for tok, fam in CHANNEL_LEXICON.items() if fam not in own}


def _curve_label(c, i):
    return c.get("source") or f"curve[{i}]"


def _parse_gaps(manifest):
    """[(lo_gev, hi_gev, note), ...] from coverage_gaps[] (structured) plus any free-text
    'below N GeV' floor found in a coverage_gaps note or a top-level annotations[] string."""
    gaps = []
    window = manifest.get("window_gev") or [None, None]
    lo_default = window[0] if window and window[0] is not None else 0.0

    def _try_below(text):
        m = _BELOW_RE.search(text or "")
        if m:
            gaps.append((lo_default, float(m.group(1)), text))

    for g in manifest.get("coverage_gaps", []) or []:
        lo, hi = g.get("lo_gev"), g.get("hi_gev")
        note = g.get("note", "")
        if lo is not None and hi is not None:
            gaps.append((float(lo), float(hi), note))
        else:
            _try_below(note)
    for note in manifest.get("annotations", []) or []:
        _try_below(str(note))
    return gaps


# --------------------------------------------------------------------------- #
#  R-SA1..8
# --------------------------------------------------------------------------- #

def rule_sa1_bijection(survey, manifest, cand_idx):
    """Every manifest curve's survey_id resolves to a survey candidate, and every survey
    candidate appears either as a manifest curve (by survey_id) OR carries a non-plotted
    disposition (excluded/superseded legitimately explains its absence from curves[])."""
    offenders = []
    referenced = set()
    for i, c in enumerate(manifest.get("curves", []) or []):
        sid = c.get("survey_id")
        label = _curve_label(c, i)
        if not sid:
            offenders.append(f"curve '{label}' (index {i}) has no survey_id")
            continue
        if sid not in cand_idx:
            offenders.append(f"curve '{label}' survey_id={sid!r} does not resolve to any "
                              f"survey candidate")
            continue
        referenced.add(sid)
    for cid, cand in cand_idx.items():
        if cid in referenced:
            continue
        state = (cand.get("disposition") or {}).get("state")
        if state in ("excluded", "superseded"):
            continue
        offenders.append(f"candidate {cid!r} appears as neither a manifest curve nor carries a "
                          f"non-plotted disposition (state={state!r})")
    return {"id": "R-SA1", "name": "bijection",
            "status": "FAIL" if offenders else "PASS", "offenders": offenders}


def rule_sa2_disposition_completeness(survey, manifest, cand_idx):
    """Every survey candidate carries a disposition; excluded/superseded carry reason+reviewer;
    superseded carries superseded_by. (reason_class validity is R-SA3's job, not this rule's.)"""
    offenders = []
    for cid, cand in cand_idx.items():
        disp = cand.get("disposition")
        if not isinstance(disp, dict):
            offenders.append(f"candidate {cid!r} carries no disposition")
            continue
        state = disp.get("state")
        if state not in DISPOSITION_STATES:
            offenders.append(f"candidate {cid!r} disposition.state={state!r} not in "
                              f"{DISPOSITION_STATES}")
            continue
        if state in ("excluded", "superseded"):
            if not disp.get("reason"):
                offenders.append(f"candidate {cid!r} (state={state}) missing disposition.reason")
            if not disp.get("reviewer"):
                offenders.append(f"candidate {cid!r} (state={state}) missing "
                                  f"disposition.reviewer")
        if state == "superseded" and not disp.get("superseded_by"):
            offenders.append(f"candidate {cid!r} (state=superseded) missing "
                              f"disposition.superseded_by")
    return {"id": "R-SA2", "name": "disposition completeness",
            "status": "FAIL" if offenders else "PASS", "offenders": offenders}


def rule_sa3_no_keyword_exclusion(survey, manifest, cand_idx):
    """Any state==excluded candidate whose reason_class isn't in {physics, out-of-range} --
    e.g. 'mechanical'/'keyword'/'TODO'/absent -- is an unreviewed drop, not a physics judgement."""
    offenders = []
    for cid, cand in cand_idx.items():
        disp = cand.get("disposition") or {}
        if disp.get("state") != "excluded":
            continue
        rc = disp.get("reason_class")
        if rc not in REASON_CLASSES:
            offenders.append(f"candidate {cid!r} excluded with reason_class={rc!r} "
                              f"(must be one of {REASON_CLASSES})")
    return {"id": "R-SA3", "name": "no keyword-only exclusion",
            "status": "FAIL" if offenders else "PASS", "offenders": offenders}


def rule_sa4_label_channel(survey, manifest, cand_idx):
    """For each drawn curve (draw != none), its legend/source string must not contain a
    forbidden-family token built from its OWN candidate's final_state (R-SA1 already flags an
    unresolved survey_id, so this rule skips those to avoid a duplicate report)."""
    offenders = []
    for i, c in enumerate(manifest.get("curves", []) or []):
        if (c.get("draw") or "none") == "none":
            continue
        sid = c.get("survey_id")
        cand = cand_idx.get(sid)
        if cand is None:
            continue
        forbidden = _forbidden_tokens(cand.get("final_state"))
        if not forbidden:
            continue
        label = (c.get("source") or "").lower()
        hit = sorted(tok for tok in forbidden if tok in label)
        if hit:
            offenders.append(f"curve '{c.get('source')}' (survey_id={sid}) label contains "
                              f"{hit} which contradicts candidate final_state "
                              f"{cand.get('final_state')!r}")
    return {"id": "R-SA4", "name": "label<->channel",
            "status": "FAIL" if offenders else "PASS", "offenders": offenders}


def rule_sa5_supersession(survey, manifest, cand_idx):
    """Every state==superseded candidate whose curve IS present must have draw != primary (not
    drawn co-equal with its successor); superseded_by must resolve to a candidate that is itself
    state==plotted (superseding into another superseded/excluded entry is not a resolution)."""
    offenders = []
    curves_by_sid = {}
    for c in manifest.get("curves", []) or []:
        sid = c.get("survey_id")
        if sid:
            curves_by_sid.setdefault(sid, []).append(c)
    for cid, cand in cand_idx.items():
        disp = cand.get("disposition") or {}
        if disp.get("state") != "superseded":
            continue
        for c in curves_by_sid.get(cid, []):
            if c.get("draw") == "primary":
                offenders.append(f"superseded candidate {cid!r} curve drawn draw=primary "
                                  f"(co-equal); must be crosscheck or none")
        sb = disp.get("superseded_by")
        if not sb or sb not in cand_idx:
            offenders.append(f"superseded candidate {cid!r} superseded_by={sb!r} does not "
                              f"resolve to a survey candidate")
        elif ((cand_idx[sb].get("disposition") or {}).get("state")) != "plotted":
            offenders.append(f"superseded candidate {cid!r} superseded_by={sb!r} is not itself "
                              f"plotted (state="
                              f"{(cand_idx[sb].get('disposition') or {}).get('state')!r})")
    return {"id": "R-SA5", "name": "supersession not co-equal",
            "status": "FAIL" if offenders else "PASS", "offenders": offenders}


def rule_sa6_provenance(survey, manifest, cand_idx):
    """Every curve's provenance is present and equals its candidate's; a digitized curve's
    native_basis/source/identity_check text must carry a 'digitiz...' qualifier -- silently
    citing 'HEPData Table N' as the source of a hand-digitized curve is exactly what this rule
    exists to catch."""
    offenders = []
    for i, c in enumerate(manifest.get("curves", []) or []):
        sid = c.get("survey_id")
        cand = cand_idx.get(sid)
        if cand is None:
            continue  # R-SA1 already reports an unresolved survey_id
        label = _curve_label(c, i)
        curve_prov = c.get("provenance")
        cand_prov = cand.get("provenance")
        if curve_prov not in PROVENANCE_VALUES:
            offenders.append(f"curve '{label}' provenance={curve_prov!r} not in "
                              f"{PROVENANCE_VALUES}")
            continue
        if cand_prov not in PROVENANCE_VALUES:
            offenders.append(f"candidate {sid!r} provenance={cand_prov!r} not in "
                              f"{PROVENANCE_VALUES}")
            continue
        if curve_prov != cand_prov:
            offenders.append(f"curve '{label}' provenance={curve_prov!r} != candidate "
                              f"{sid!r} provenance={cand_prov!r}")
            continue
        if curve_prov == "digitized":
            blob = " ".join(str(c.get(k, "")) for k in
                             ("native_basis", "source", "identity_check")).lower()
            if "digitiz" not in blob:
                offenders.append(f"curve '{label}' provenance=digitized but its "
                                  f"native_basis/source/identity_check text carries no "
                                  f"'digitiz...' qualifier (must not assert a HEPData table as "
                                  f"the source without saying the curve was digitized)")
    return {"id": "R-SA6", "name": "provenance labelled + consistent",
            "status": "FAIL" if offenders else "PASS", "offenders": offenders}


def rule_sa7_coverage_reach(survey, manifest, cand_idx):
    """No IN-CHANNEL (state==plotted) candidate's mass_range_gev may overlap a coverage-gap
    annotation's [lo,hi] -- a plotted curve reaching into a window the manifest itself labels
    'no published limit' contradicts the annotation, not the candidate."""
    offenders = []
    gaps = _parse_gaps(manifest)
    if not gaps:
        return {"id": "R-SA7", "name": "coverage annotation<->reach", "status": "PASS",
                "offenders": offenders}
    for cid, cand in cand_idx.items():
        if (cand.get("disposition") or {}).get("state") != "plotted":
            continue
        mr = cand.get("mass_range_gev")
        if not (isinstance(mr, (list, tuple)) and len(mr) == 2):
            continue
        m_lo, m_hi = float(mr[0]), float(mr[1])
        for lo, hi, note in gaps:
            if m_lo < hi and m_hi > lo:
                offenders.append(f"candidate {cid!r} mass_range_gev={list(mr)} overlaps "
                                  f"coverage gap [{lo},{hi}] ({note!r})")
    return {"id": "R-SA7", "name": "coverage annotation<->reach",
            "status": "FAIL" if offenders else "PASS", "offenders": offenders}


def rule_sa8_transformation_present(survey, manifest, cand_idx):
    """Every drawn curve (draw != none) states a non-empty transformation and an explicit
    identity_check (the literal string 'NONE' is fine; a missing key or empty string is not)."""
    offenders = []
    for i, c in enumerate(manifest.get("curves", []) or []):
        if (c.get("draw") or "none") == "none":
            continue
        label = _curve_label(c, i)
        if not str(c.get("transformation") or "").strip():
            offenders.append(f"curve '{label}' has no transformation")
        if not str(c.get("identity_check") if c.get("identity_check") is not None else "").strip():
            offenders.append(f"curve '{label}' has no identity_check (write 'NONE' explicitly "
                              f"if there is none)")
    return {"id": "R-SA8", "name": "transformation present",
            "status": "FAIL" if offenders else "PASS", "offenders": offenders}


RULES = (
    rule_sa1_bijection,
    rule_sa2_disposition_completeness,
    rule_sa3_no_keyword_exclusion,
    rule_sa4_label_channel,
    rule_sa5_supersession,
    rule_sa6_provenance,
    rule_sa7_coverage_reach,
    rule_sa8_transformation_present,
)


def audit(survey, manifest):
    """Run all R-SA rules; return the machine record (schema below), verdict = AND of all rules."""
    cand_idx = _candidate_index(survey)
    rules = [r(survey, manifest, cand_idx) for r in RULES]
    verdict = "PASS" if all(r["status"] == "PASS" for r in rules) else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "summary_audit.py",
        "n_candidates": len(cand_idx),
        "n_curves": len(manifest.get("curves", []) or []),
        "rules": rules,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- #
#  --selftest fixtures (TDD; NO per-paper literals -- synthetic candidate ids/labels only)
# --------------------------------------------------------------------------- #

def _clean_fixture():
    survey = {"schema_version": 1, "survey_target": "selftest fixture", "candidates": [
        {"id": "SIM_A1", "final_state": "l-nu-qq (one W leptonic, other hadronic)",
         "mass_range_gev": [300, 3000], "provenance": "hepdata-machine",
         "disposition": {"state": "plotted"}},
        {"id": "SIM_A2", "final_state": "l-nu-qq (one W leptonic, other hadronic)",
         "mass_range_gev": [300, 3000], "provenance": "hepdata-machine",
         "disposition": {"state": "superseded", "reason": "superseded by SIM_A1 (same channel, "
                          "higher luminosity)", "reviewer": "agent:selftest",
                          "superseded_by": "SIM_A1"}},
        {"id": "SIM_B1", "final_state": "e-nu-mu-nu fully leptonic (no jets)",
         "mass_range_gev": [200, 3000], "provenance": "hepdata-machine",
         "disposition": {"state": "excluded", "reason": "fully leptonic channel does not "
                          "constrain this target basis", "reason_class": "physics",
                          "reviewer": "agent:selftest"}},
        {"id": "SIM_C1", "final_state": "l-nu-qq", "mass_range_gev": [2000, 6000],
         "provenance": "hepdata-machine",
         "disposition": {"state": "excluded", "reason": "mass reach entirely above the "
                          "requested window", "reason_class": "out-of-range",
                          "reviewer": "agent:selftest"}},
        {"id": "SIM_D1", "final_state": "e-nu-mu-nu fully leptonic dilepton",
         "mass_range_gev": [200, 1000], "provenance": "digitized",
         "disposition": {"state": "plotted"}},
    ]}
    manifest = {"schema_version": 1,
                "target_basis": {"quantity": "95% CL UL [pb]", "model": "TEST", "sqrt_s": "13 TeV"},
                "window_gev": [100, 3500],
                "curves": [
                    {"source": "Experiment A search 1, l-nu-qq semileptonic", "survey_id": "SIM_A1",
                     "provenance": "hepdata-machine", "draw": "primary",
                     "native_basis": "95% CL UL [pb] vs mass [GeV] (HEPData Table 1)",
                     "transformation": "IDENTITY", "identity_check": "NONE"},
                    {"source": "Experiment A search 2, l-nu-qq semileptonic (superseded)",
                     "survey_id": "SIM_A2", "provenance": "hepdata-machine", "draw": "crosscheck",
                     "native_basis": "95% CL UL [pb] vs mass [GeV] (HEPData Table 1)",
                     "transformation": "IDENTITY", "identity_check": "NONE"},
                    {"source": "Experiment D search, digitized, e-nu-mu-nu fully leptonic "
                     "dilepton", "survey_id": "SIM_D1", "provenance": "digitized",
                     "draw": "primary",
                     "native_basis": "digitized from the published figure (no HEPData table)",
                     "transformation": "IDENTITY; pixel calibration", "identity_check": "NONE"},
                ],
                "coverage_gaps": [{"lo_gev": 0, "hi_gev": 200,
                                    "note": "no published limit below 200 GeV"}]}
    return survey, manifest


def _defective_fixture():
    """One isolated trip per rule R-SA1..8 (SIM_X2 doubles as the R-SA2 case; SIM_X6's curve
    carries the missing survey_id that also leaves SIM_X6 itself uncovered -- both still land
    under R-SA1)."""
    survey = {"schema_version": 1, "survey_target": "selftest fixture (defective)", "candidates": [
        {"id": "SIM_X1", "final_state": "l-nu-qq semileptonic", "mass_range_gev": [300, 3000],
         "provenance": "hepdata-machine", "disposition": {"state": "plotted"}},
        {"id": "SIM_X2", "final_state": "l-nu-qq semileptonic", "mass_range_gev": [1200, 3000],
         "provenance": "hepdata-machine"},                       # R-SA2: no disposition at all
        {"id": "SIM_X3", "final_state": "l-nu-qq semileptonic", "mass_range_gev": [1300, 3000],
         "provenance": "hepdata-machine",
         "disposition": {"state": "excluded", "reason": "dropped for pipeline convenience",
                          "reason_class": "mechanical",           # R-SA3: not physics/out-of-range
                          "reviewer": "agent:selftest"}},
        {"id": "SIM_X4", "final_state": "l-nu-qq semileptonic", "mass_range_gev": [1400, 3000],
         "provenance": "hepdata-machine",
         "disposition": {"state": "superseded", "reason": "superseded by SIM_X1",
                          "reviewer": "agent:selftest", "superseded_by": "SIM_X1"}},
        {"id": "SIM_X5", "final_state": "l-nu-qq semileptonic", "mass_range_gev": [200, 3000],
         "provenance": "hepdata-machine", "disposition": {"state": "plotted"}},
        {"id": "SIM_X6", "final_state": "l-nu-qq semileptonic", "mass_range_gev": [1000, 3000],
         "provenance": "hepdata-machine", "disposition": {"state": "plotted"}},
        {"id": "SIM_X7", "final_state": "l-nu-qq semileptonic", "mass_range_gev": [1500, 3000],
         "provenance": "digitized", "disposition": {"state": "plotted"}},
        {"id": "SIM_X8", "final_state": "l-nu-qq semileptonic", "mass_range_gev": [1800, 3000],
         "provenance": "hepdata-machine", "disposition": {"state": "plotted"}},
    ]}
    manifest = {"schema_version": 1,
                "target_basis": {"quantity": "95% CL UL [pb]", "model": "TEST", "sqrt_s": "13 TeV"},
                "window_gev": [100, 3500],
                "curves": [
                    {"source": "Experiment X search 1, fully leptonic dilepton",  # R-SA4: mislabel
                     "survey_id": "SIM_X1", "provenance": "hepdata-machine", "draw": "primary",
                     "native_basis": "95% CL UL [pb] (HEPData Table 1)",
                     "transformation": "IDENTITY", "identity_check": "NONE"},
                    {"source": "Experiment X search 2, l-nu-qq semileptonic",
                     "survey_id": "SIM_X2", "provenance": "hepdata-machine", "draw": "crosscheck",
                     "native_basis": "95% CL UL [pb] (HEPData Table 2)",
                     "transformation": "IDENTITY", "identity_check": "NONE"},
                    # SIM_X3: excluded, no curve -- fine under R-SA1
                    {"source": "Experiment X search 4, l-nu-qq semileptonic (older)",
                     "survey_id": "SIM_X4", "provenance": "hepdata-machine",
                     "draw": "primary",                          # R-SA5: superseded drawn co-equal
                     "native_basis": "95% CL UL [pb] (HEPData Table 4)",
                     "transformation": "IDENTITY", "identity_check": "NONE"},
                    {"source": "Experiment X search 5, l-nu-qq semileptonic wide reach",
                     "survey_id": "SIM_X5", "provenance": "hepdata-machine", "draw": "primary",
                     "native_basis": "95% CL UL [pb] (HEPData Table 5)",
                     "transformation": "IDENTITY", "identity_check": "NONE"},
                    {"source": "Experiment X search 6, l-nu-qq semileptonic",
                     "provenance": "hepdata-machine", "draw": "primary",   # R-SA1: no survey_id
                     "native_basis": "95% CL UL [pb] (HEPData Table 6)",
                     "transformation": "IDENTITY", "identity_check": "NONE"},
                    {"source": "Experiment X search 7, l-nu-qq semileptonic",
                     "survey_id": "SIM_X7", "provenance": "digitized", "draw": "primary",
                     "native_basis": "HEPData Table 9",           # R-SA6: no digitiz qualifier
                     "transformation": "IDENTITY", "identity_check": "NONE"},
                    {"source": "Experiment X search 8, l-nu-qq semileptonic",
                     "survey_id": "SIM_X8", "provenance": "hepdata-machine", "draw": "primary",
                     "native_basis": "95% CL UL [pb] (HEPData Table 8)",
                     "transformation": "",                        # R-SA8: no transformation
                     "identity_check": "NONE"},
                ],
                "coverage_gaps": [{"lo_gev": 0, "hi_gev": 300,     # R-SA7: SIM_X5 reaches to 200
                                    "note": "no published limit below 300 GeV"}]}
    return survey, manifest


def _selftest():
    fails = []

    clean_survey, clean_manifest = _clean_fixture()
    clean = audit(clean_survey, clean_manifest)
    print(f"[selftest] clean fixture: verdict={clean['verdict']}")
    for r in clean["rules"]:
        print(f"    [{r['status']:>4}] {r['id']} {r['name']}")
        for off in r["offenders"]:
            print(f"           - {off}")
    if clean["verdict"] != "PASS":
        fails.append(f"clean fixture expected verdict=PASS, got {clean['verdict']}")
    bad_rules = [r["id"] for r in clean["rules"] if r["status"] != "PASS"]
    if bad_rules:
        fails.append(f"clean fixture: rule(s) unexpectedly FAIL: {bad_rules}")

    def_survey, def_manifest = _defective_fixture()
    defective = audit(def_survey, def_manifest)
    print(f"[selftest] defective fixture: verdict={defective['verdict']}")
    for r in defective["rules"]:
        print(f"    [{r['status']:>4}] {r['id']} {r['name']}")
        for off in r["offenders"]:
            print(f"           - {off}")
    if defective["verdict"] != "FAIL":
        fails.append(f"defective fixture expected verdict=FAIL, got {defective['verdict']}")
    expect_tripped = {f"R-SA{i}" for i in range(1, 9)}
    tripped = {r["id"] for r in defective["rules"] if r["status"] == "FAIL"}
    missing = expect_tripped - tripped
    if missing:
        fails.append(f"defective fixture: rule(s) expected to trip but PASSed: {sorted(missing)}")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("summary_audit selftest: PASS (clean fixture all-PASS; defective fixture trips "
          "all 8 rules R-SA1..8)")
    return 0


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def _resolve_paths(args):
    if args.survey and args.manifest:
        return args.survey, args.manifest
    if args.rundir:
        return (os.path.join(args.rundir, "outputs", "survey.json"),
                os.path.join(args.rundir, "inputs", "basis_manifest.json"))
    return None, None


def _resolve_out(args, survey_path):
    if args.out:
        return args.out
    if args.rundir:
        return os.path.join(args.rundir, "outputs", "summary_audit.json")
    return os.path.join(os.path.dirname(os.path.abspath(survey_path)), "summary_audit.json")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return _selftest()

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir", help="run dir; default paths outputs/survey.json + "
                                      "inputs/basis_manifest.json")
    ap.add_argument("--survey", help="override survey.json path")
    ap.add_argument("--manifest", help="override basis_manifest.json path")
    ap.add_argument("--out", help="summary_audit.json output path "
                                   "(default: <rundir>/outputs/summary_audit.json)")
    ap.add_argument("--check", action="store_true",
                     help="run the gate (this is the default and only action; kept as an "
                          "explicit flag so PRODUCT-CONTRACT's 'summary_audit.py --check' "
                          "invocation is literal)")
    ap.add_argument("--selftest", action="store_true", help="run the embedded fixture selftest")
    args = ap.parse_args(argv)

    survey_path, manifest_path = _resolve_paths(args)
    if not survey_path or not manifest_path:
        print("summary_audit: need --rundir, OR both --survey and --manifest", file=sys.stderr)
        return 2
    if not os.path.isfile(survey_path):
        print(f"summary_audit: survey not found: {survey_path}", file=sys.stderr)
        return 2
    if not os.path.isfile(manifest_path):
        print(f"summary_audit: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    try:
        with open(survey_path) as f:
            survey = json.load(f)
        with open(manifest_path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        print(f"summary_audit: invalid JSON: {e}", file=sys.stderr)
        return 2

    record = audit(survey, manifest)
    record["survey_path"] = survey_path
    record["manifest_path"] = manifest_path

    out_path = _resolve_out(args, survey_path)
    outdir = os.path.dirname(os.path.abspath(out_path))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(record, f, indent=2)

    for r in record["rules"]:
        print(f"[{r['status']:>4}] {r['id']} {r['name']}")
        for off in r["offenders"]:
            print(f"        - {off}")
    print(f"wrote {out_path}")
    print(f"summary_audit: verdict={record['verdict']}  "
          f"({record['n_candidates']} candidate(s), {record['n_curves']} curve(s))")

    return 3 if record["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
