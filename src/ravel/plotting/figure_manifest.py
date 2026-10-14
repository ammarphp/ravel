#!/usr/bin/env python
"""Figure discovery suggestions from declared observables and source metadata.

The request supplies the actual figure, its role and coordinate definitions.
Archetype suggestions do not select a source, figure or required deliverable.
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import re
import argparse
import json
from pathlib import Path
import sys


# ----------------------------------------------------------------- the recipe table (data-driven)
# Observable categories supply discovery suggestions; the request selects the actual figure.
ARCHETYPES = {'A': {'name': '0-lepton jets+MET (m_eff / MET)',
       'anchor': 'Supplied analysis source',
       'discriminating_figure': 'effective-mass (m_eff) or E_T^miss distribution per signal region',
       'observable': 'm_eff [GeV] (or E_T^miss [GeV])',
       'ref_table': 'Supplied source table and quantity definitions',
       'overlay_recipe': {'primitive': 'per-SR-yield bars + distribution (where REF ships)',
                          'tool': 'overlay_on_data.py',
                          'how': 'Supply the requested observable, axis metadata, source table and '
                                 'presentation arguments.'},
       'cert_primitive': {'kind': 'acc x eff vs published HEPData grid',
                          'tool': 'validate_cutflow.py'}},
 'B': {'name': 'multilepton / EW-ino (per-SR-yield or cutflow-final-row)',
       'anchor': 'Supplied analysis source',
       'discriminating_figure': 'per-signal-region yield (data + bkg band + signal) across SRs',
       'observable': 'signal-region index (counting); SR-yield',
       'ref_table': 'Supplied source table and quantity definitions',
       'overlay_recipe': {'primitive': 'per-SR-yield bars',
                          'tool': 'overlay_on_data.py (per-SR mode) / plot_simpleanalysis.py',
                          'how': 'Supply the requested observable, axis metadata, source table and '
                                 'presentation arguments.'},
       'cert_primitive': {'kind': 'cutflow tables / acc x eff vs published',
                          'tool': 'validate_cutflow.py'}},
 'C': {'name': '1-lepton+jets (mT / m_eff counters)',
       'anchor': 'Supplied analysis source',
       'discriminating_figure': 'per-signal-region yield (data + bkg band + signal) across SRs',
       'observable': 'signal-region index (counting); m_T / m_eff counters',
       'ref_table': 'Supplied source table and quantity definitions',
       'overlay_recipe': {'primitive': 'per-SR-yield bars',
                          'tool': 'overlay_on_data.py (per-SR mode)',
                          'how': 'Supply the requested observable, axis metadata, source table and '
                                 'presentation arguments.'},
       'cert_primitive': {'kind': 'CONF-note cutflow only', 'tool': 'validate_cutflow.py'}},
 'D': {'name': 'monojet / MET-binned (MET-threshold counter array)',
       'anchor': 'Supplied analysis source',
       'discriminating_figure': 'E_T^miss distribution (point-binned, inclusive MET-threshold '
                                'counters)',
       'observable': 'E_T^miss [GeV]',
       'ref_table': 'Supplied source table and quantity definitions',
       'overlay_recipe': {'primitive': 'point-binned MET distribution',
                          'tool': 'overlay_on_data.py',
                          'how': 'Supply the requested observable, axis metadata, source table and '
                                 'presentation arguments.'},
       'cert_primitive': {'kind': 'acc x eff vs published', 'tool': 'validate_cutflow.py'}},
 'ESCAPE': {'name': 'Source-declared classifier or fiducial observable',
            'anchor': 'Supplied analysis source',
            'discriminating_figure': 'bespoke -- the NN-score distribution or the hand-rolled '
                                     'fiducial observable; choose per paper (FLAGGED, not auto)',
            'observable': 'NN score / bespoke fiducial observable',
            'ref_table': 'Supplied source table and quantity definitions',
            'overlay_recipe': {'primitive': 'bespoke (flag for the [judgment] step)',
                               'tool': 'overlay_on_data.py if a 1-D REF exists; else hand-built',
                               'how': 'Supply the requested observable, axis metadata, source '
                                      'table and presentation arguments.'},
            'cert_primitive': {'kind': 'paper-specific',
                               'tool': 'validate_cutflow.py (where a cutflow/acc x eff is '
                                       'published)'}}}

# Cross-cutting renderer division of labour: ONE source of truth (per-SR yields JSON / the signal
# .yoda + the published REF / the HEPData contour) feeds THREE renderers. The figure form is selected by the request
# and its source metadata; the renderers below are how that same form is drawn for each audience. This is
# the "one source, multiple renderers" contract -- it applies to every figure regardless of archetype,
# so the oracle prints it alongside the archetype recipe.
RENDERERS = {
    "primary": {
        "renderer": "mplhep",
        "role": "PRIMARY publication figures",
        "tools": "overlay_on_data.py (distribution / per-SR-yield over data), mass_plane_overlay.py "
                 "(the mass-plane summary)",
        "note": "the publication path -- ATLAS/CMS house style via mplhep_style.py; the figures that "
                "go in the paper / RESULT.md.",
    },
    "interchange": {
        "renderer": "YODA",
        "role": "interchange / persistence",
        "tools": "write_yoda.py",
        "note": "persist the per-SR yields (+ histos) as Rivet-native .yoda so the yields are "
                "re-plottable and handed off WITHOUT re-running the pipeline. Rivet's native "
                "interchange format -- the colleagues' re-plot/hand-off substrate.",
    },
    "mirror": {
        "renderer": "ROOT",
        "role": "colleague-facing mirror",
        "tools": "root_figures.py (TGraph/THStack mirrors of the two key figures)",
        "note": "the same two key figures drawn in ROOT for colleagues whose norm is ROOT -- from the "
                "SAME source of truth (per-SR yields JSON / .yoda), in ATLAS ROOT style (four-side "
                "inward ticks, no stat box, sqrt(s)+lumi header, '95% CL exclusion, not discovery'). "
                "NOT a re-derivation -- a mirror of the mplhep figures.",
    },
}

# Renderer suggestion; the request owns the deliverable.
MASS_PLANE_SUMMARY = {'summary_figure': 'Requested parameter-plane contour with declared coordinates',
 'applies_when': 'The request selects a compatible parameter-plane renderer.',
 'ref_table': 'Supplied complete coordinate and contour metadata',
 'tool': 'mass_plane_overlay.py',
 'how': 'Supply coordinates, labels, limit statuses, experiment, energy, luminosity and output '
        'destination.',
 'note': 'The requested quantity and source metadata determine the figure.'}

# Compatibility registries are empty; callers supply source-derived hints.
KNOWN_ANALYSES = {}
FIGURE_HINTS = {}
ANALYSIS_ALIASES = {}


def canon_analysis(a):
    """Normalize a user-supplied analysis id (Inspire id, PUB code, SA routine name, or the Rivet-style
    key) to the canonical KNOWN_ANALYSES key, so the identifiers a physicist naturally uses resolve."""
    if not a:
        return a
    if a in KNOWN_ANALYSES:
        return a
    return ANALYSIS_ALIASES.get(a.strip().lower(), a)


def _has(description, *phrases):
    """True if any phrase matches `description` on whole-WORD boundaries (not raw substring).

    `\b` alone treats '-'/'_' as word breaks, so 'mono-jet' / 'm_eff' / 'nn-score' work as written;
    non-alphanumerics inside a phrase match any run of non-alphanumerics. This is what stops
    'centimeter' from reading as 'met' and 'meffective' from reading as 'meff'.
    """
    for p in phrases:
        toks = [tok for tok in re.split(r"[^0-9a-z]+", p) if tok]
        if not toks:
            continue
        pat = r"\b" + r"[^0-9a-z]+".join(re.escape(tok) for tok in toks) + r"\b"
        if re.search(pat, description):
            return True
    return False


# Keyword sets per archetype, matched on word boundaries (see _has). Order of EVALUATION matters: the
# escape patterns win outright; then the lepton-count (B / C) branches are scored BEFORE the bare-MET
# (D) branch so a "3-lepton + MET" EW-ino search is NOT mis-routed to D. D additionally REQUIRES a real
# monojet / MET-binning cue -- the bare word 'threshold' is not a monojet signature.
_ESCAPE_KW = ("onnx", "neural net", "neural network", "nn score", "nn-score", "nn classifier",
              "fiducial reco", "hand-rolled", "hand rolled", "graph network", "gnn", "bdt score")
_B_KW = ("multilepton", "multi-lepton", "two-lepton", "two lepton", "three-lepton", "three lepton",
         "dilepton", "di-lepton", "trilepton", "tri-lepton", "same-sign", "same sign",
         "opposite-sign", "2l", "3l", "4l", "ew-ino", "ewkino", "electroweakino", "electroweak-ino",
         "chargino", "neutralino", "slepton", "wino", "higgsino")
_C_KW = ("1-lepton", "one-lepton", "one lepton", "single lepton", "single-lepton")
_A_KW = ("0-lepton", "zero-lepton", "zero lepton", "jets+met", "jets + met", "m_eff", "meff",
         "effective mass", "squark", "gluino")
# D fires only on a genuine monojet / inclusive-MET-binning cue -- NOT on the bare word 'threshold'.
_D_KW = ("monojet", "mono-jet", "mono jet", "met-threshold", "met threshold", "inclusive met bin",
         "inclusive met bins", "met-binned", "met binned", "missing-et threshold")


def classify(description):
    """Heuristic archetype guess from a free-text routine description. Returns (archetype, reason).

    Scores EVERY archetype on word-boundary keyword hits (not raw substrings), then resolves in a fixed
    priority -- ESCAPE patterns first, then the lepton-count branches (B then C) BEFORE the bare-MET (D)
    branch, then A, with D requiring a real monojet / MET-binning cue. When two independent archetypes
    both match (e.g. a lepton cue AND a monojet cue), the result is FLAGGED as ambiguous so the [judgment]
    step reads the routine instead of trusting a silent first-match.

    This is a HINT for the [judgment] step, not a substitute for reading the routine -- when it lands on
    ESCAPE or is flagged ambiguous, fall back to human judgement.
    """
    d = description.lower()

    # Escape patterns are decisive: a NN-score / hand-rolled-fiducial routine does not fit A-D.
    if _has(d, *_ESCAPE_KW):
        return "ESCAPE", "matches a per-paper escape pattern (NN-score or hand-rolled fiducial reco)"

    # Score the four counting archetypes independently (word-boundary hits).
    hits = {
        "B": _has(d, *_B_KW),
        "C": _has(d, *_C_KW) and _has(d, "jet", "jets"),
        "D": _has(d, *_D_KW),
        "A": _has(d, *_A_KW),
    }
    matched = [k for k, v in hits.items() if v]

    # Ambiguity flag: a lepton-count archetype (B/C) AND the monojet (D) branch both fire -- these are
    # mutually exclusive final states, so a routine hitting both is described inconsistently. Surface it
    # for the [judgment] step rather than letting the priority order silently swallow one of them.
    lepton_hit = hits["B"] or hits["C"]
    if lepton_hit and hits["D"]:
        chosen = "B" if hits["B"] else "C"
        return chosen, (f"AMBIGUOUS: matched both a lepton-count cue ({chosen}) and a monojet/MET-bin "
                        f"cue (D) -- chose {chosen}; CONFIRM by reading the routine ([judgment])")

    # Fixed priority: B (multilepton/EW-ino) and C (1-lepton+jets) are tested BEFORE the bare-MET D
    # branch so "3-lepton + MET" is never mis-routed to D.
    if hits["B"]:
        return "B", "multilepton / electroweakino (counting per-SR or cutflow-final-row)"
    if hits["C"]:
        return "C", "1-lepton+jets (mT / m_eff counters)"
    if hits["D"]:
        return "D", "monojet / inclusive-MET-threshold counter array"
    if hits["A"]:
        return "A", "0-lepton jets+MET (m_eff / MET)"
    return "ESCAPE", "no archetype matched -- inspect the routine + paper by hand"


def recipe_for(archetype, analysis=None, susy=False, *, figure_hint=None):
    """Build the structured recipe dict for an archetype (+ the mass-plane summary for SUSY)."""
    arch = archetype.upper()
    if arch not in ARCHETYPES:
        sys.exit(f"unknown archetype {archetype!r}; choose from {list(ARCHETYPES)}")
    rec = {
        "analysis": analysis,
        "archetype": arch,
        "archetype_name": ARCHETYPES[arch]["name"],
        "anchor": ARCHETYPES[arch]["anchor"],
        "discriminating_figure": ARCHETYPES[arch]["discriminating_figure"],
        "observable": ARCHETYPES[arch]["observable"],
        "ref_table": ARCHETYPES[arch]["ref_table"],
        "overlay_recipe": ARCHETYPES[arch]["overlay_recipe"],
        "cert_primitive": ARCHETYPES[arch]["cert_primitive"],
        "renderers": RENDERERS,
    }
    # The FIGURE CONTRACT hook: which SPECIFIC published figure this run reproduces is declared
    # in <rundir>/inputs/figure_target.json (figure_target.py); the recipe carries the resolution
    # precedence + the optional curated hint so the step-2 [judgment] pass knows how to fill it.
    rec["figure_target"] = {
        "resolution_order": ["user-prompt", "hepdata-table-name (figure_index)",
                             "paper-inspection", "description-only + CHECK-IN"],
        "hint": figure_hint,
        "declare_with": "figure_target.py declare",
        "note": "the [judgment] step picks among resolve candidates; never auto-select",
    }
    if susy:
        rec["summary_recipe"] = MASS_PLANE_SUMMARY
    return rec


def print_recipe(rec):
    a = rec
    print(f"=== figure-selection recipe ===")
    if a.get("analysis"):
        print(f"analysis              : {a['analysis']}")
    print(f"archetype             : {a['archetype']}  ({a['archetype_name']})")
    print(f"anchor                : {a['anchor']}")
    print(f"discriminating figure : {a['discriminating_figure']}")
    print(f"observable            : {a['observable']}")
    print(f"REF table             : {a['ref_table']}")
    ov = a["overlay_recipe"]
    print(f"OVERLAY primitive     : {ov['primitive']}")
    print(f"  tool                : {ov['tool']}")
    print(f"  how                 : {ov['how']}")
    ce = a["cert_primitive"]
    print(f"CERT primitive        : {ce['kind']}  (tool: {ce['tool']})")
    if "figure_target" in a:
        ft = a["figure_target"]
        print(f"FIGURE TARGET         : declare with {ft['declare_with']} "
              f"({ft['note']})")
        print(f"  resolution order    : {' > '.join(ft['resolution_order'])}")
        if ft.get("hint"):
            print(f"  registry hint       : {ft['hint']}  (curated; confirm against resolve)")
    if "renderers" in a:
        print(f"RENDERERS (one source, multiple renderers):")
        for r in a["renderers"].values():
            print(f"  {r['renderer']:8s} = {r['role']}")
            print(f"           tools: {r['tools']}")
    if "summary_recipe" in a:
        s = a["summary_recipe"]
        print(f"SUMMARY (mass plane)  : {s['summary_figure']}")
        print(f"  applies when        : {s['applies_when']}")
        print(f"  REF table           : {s['ref_table']}")
        print(f"  tool                : {s['tool']}")
        print(f"  how                 : {s['how']}")
        print(f"  note                : {s['note']}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # --list / --classify / --archetype pick one mode; they are mutually exclusive (--analysis pairs
    # with --archetype, or stands alone as a registry lookup, so it is NOT in the group).
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--archetype", help="A | B | C | D | ESCAPE")
    mode.add_argument("--classify", metavar="DESCRIPTION",
                      help="heuristically guess the archetype from a free-text routine description")
    mode.add_argument("--list", action="store_true", help="list all archetypes + the summary recipe")
    ap.add_argument("--analysis", help="supplied analysis id; used to look up the "
                                       "archetype if --archetype is omitted, and cross-checked against "
                                       "--archetype when both are given")
    ap.add_argument("--strict", action="store_true",
                    help="treat an --archetype/--analysis vs registry mismatch as a fatal ERROR "
                         "(default: WARN to stderr and proceed with the explicit --archetype)")
    ap.add_argument("--summary", action="store_true", help="include an explicitly requested parameter-plane summary")
    ap.add_argument("--figure-hint", type=Path, help="supplied JSON figure hint")
    ap.add_argument("--no-susy", action="store_true",
                    help="omit the mass-plane summary recipe (non-SUSY / no exclusion contour)")
    ap.add_argument("--json", action="store_true", help="emit the recipe as JSON")
    args = ap.parse_args()

    if args.list:
        out = {"archetypes": ARCHETYPES, "renderers": RENDERERS,
               "summary": MASS_PLANE_SUMMARY, "known_analyses": KNOWN_ANALYSES}
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            for k, v in ARCHETYPES.items():
                print(f"{k:7s} {v['name']}  (anchor: {v['anchor']})")
            print("\nRENDERERS (cross-cutting, one source -> multiple renderers):")
            for r in RENDERERS.values():
                print(f"  {r['renderer']:8s} = {r['role']}  (tools: {r['tools']})")
            print(f"\nSUMMARY (explicitly requested parameter plane): "
                  f"{MASS_PLANE_SUMMARY['summary_figure']}\n  tool: {MASS_PLANE_SUMMARY['tool']}")
            print("\nknown analyses -> archetype:")
            for k, v in KNOWN_ANALYSES.items():
                print(f"  {k} -> {v}")
        return

    if args.classify:
        arch, reason = classify(args.classify)
        if args.json:
            print(json.dumps({"archetype": arch, "reason": reason}, indent=2))
        else:
            print(f"archetype: {arch}\nreason   : {reason}")
        if arch == "ESCAPE" or reason.startswith("AMBIGUOUS"):
            print("NOTE: ESCAPE / ambiguous -- confirm by reading the routine + paper ([judgment]).",
                  file=sys.stderr)
        return

    archetype = args.archetype
    registered = KNOWN_ANALYSES.get(canon_analysis(args.analysis)) if args.analysis else None
    if archetype is None:
        if args.analysis:
            if registered is None:
                sys.exit(f"ERROR: analysis {args.analysis!r} not in the known-analysis registry; pass "
                         f"--archetype, or --classify a description")
            archetype = registered
        else:
            ap.error("give --archetype, or --analysis (a known id), or --classify, or --list")
    elif registered is not None and registered.upper() != archetype.upper():
        # An explicit --archetype that contradicts the registry must NOT be obeyed silently.
        msg = (f"--archetype {archetype.upper()!r} contradicts the registry, which lists "
               f"{args.analysis} as archetype {registered!r}")
        if args.strict:
            sys.exit(f"ERROR: {msg} (use a matching --archetype, or drop --archetype to use the "
                     f"registry; --strict made this fatal)")
        print(f"[WARN] {msg}; proceeding with the explicit --archetype {archetype.upper()!r} "
              f"(pass --strict to make this an error, or drop --archetype to use the registry).",
              file=sys.stderr)

    hint=json.loads(args.figure_hint.read_text()) if args.figure_hint else None
    rec = recipe_for(archetype, analysis=args.analysis, susy=args.summary and not args.no_susy, figure_hint=hint)
    if args.json:
        print(json.dumps(rec, indent=2))
    else:
        print_recipe(rec)


if __name__ == "__main__":
    main()


PUBLISHED_SEARCH_SUMMARY = {
    'figure_class': 'published-search-summary',
    'role': 'summary',
    'primary_renderer': 'summary_overlay.render_summary_panels',
    'source_contract': 'published_summary.validate_requested_summary',
    'required_products': ['summary.png', 'summary.pdf', 'figure_target.json',
                          'task-fulfillment.json', 'search-census.json', 'source-references.json'],
    'requirements': ['parent_requested_quantity', 'complete_declared_current_census',
                     'source_bound_dispositions', 'model_production_width_panels',
                     'publication_house_style', 'experiment_energy_header',
                     'observed_expected_labels', 'geometric_lint'],
    'not_applicable': ['data_background_ratio_panel', 'new_limit_calculation'],
    'scope': 'Published search limits; different model/production bases remain separate panels. '
             'The supplied discovery census requires independent scientific review.',
}


def summary_recipe(figure_class):
    """Select the existing summary renderer by scientific figure class."""
    from copy import deepcopy
    if figure_class != PUBLISHED_SEARCH_SUMMARY['figure_class']:
        raise ValueError('unsupported published summary figure class')
    return deepcopy(PUBLISHED_SEARCH_SUMMARY)
