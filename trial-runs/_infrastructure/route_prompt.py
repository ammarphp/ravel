#!/usr/bin/env python3
"""Deterministic first-pass router: physicist prompt -> task_contract.json.

A WEAK model must not free-hand the request classification (charter F5): this script maps the
prompt to the PRODUCT-CONTRACT.md taxonomy with ordered keyword rules — no LLM, no network —
then `validate_task_contract.py` gates the result and CHECK-IN 1 presents it. The [judgment]
half stays explicit: every TBD-judgment field and every `escalate` line is a numbered flag for
the physicist, NEVER a silent guess. Heavy compute is structurally blocked:
approval_required=true always; compute beyond `smoke` requires the CHECK-IN 1 go-ahead.

Stdlib-only. Usage:
  route_prompt.py --prompt "Initiate: reproduce Figure 3 of ..." --out <rundir>/task_contract.json
  route_prompt.py --prompt-file req.txt --print          # contract to stdout only
  route_prompt.py --selftest                              # the 10 charter-P4 prompts must route
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_task_contract import validate  # noqa: E402
import cost_preflight  # noqa: E402

# ---------------------------------------------------------------- extraction
ARXIV_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
INSPIRE_RE = re.compile(r"\bins(\d{6,8})\b", re.I)
ANACODE_RE = re.compile(r"\b((?:ATLAS|CMS)[- ](?:SUSY|EXO|HIG|B2G|CONF|HDBS|HMBS)[- ]?\d{4}[- ]?\d+"
                        r"|(?:SUSY|EXO|HIG|B2G)-\d{4}-\d+)\b", re.I)
FIGURE_RE = re.compile(r"\bfig(?:ure)?s?\.?\s*(\d+[a-z]?(?:\s*[-–&,]\s*\d+[a-z]?)*)", re.I)
MASS_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(GeV|TeV)\b", re.I)
LUMI_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*fb(?:\^?-1|⁻¹|-1)?\b", re.I)

# analyses whose result is a binned shape/template fit -> route to the shape_fit.py engine
# (Option B, DECISION-SHAPE-FIT.md), R5-gated per analysis. framework/interrogations/generality.md
# records the precedents; extend as new shape-fit analyses are identified.
SHAPE_FIT_BLOCKLIST = {
    "2408.00049": "dijet+photon Z' bump hunt (shape fit; 2026-06-21 audit, now Option-B engine route)",
}
SHAPE_FIT_HINTS = re.compile(r"bump.?hunt|shape.?fit|template.?fit|(dijet|diphoton|dilepton)\s+"
                             r"(mass\s+)?(spectrum|resonance)\s+(search|fit)", re.I)
# analyses with a native SimpleAnalysis port (PRODUCT-CONTRACT section 2 / CR-005 scope)
NATIVE_SA = re.compile(r"ewkcompressed|1767649|slepton|SUSY-2018-16", re.I)

# ---------------------------------------------------------------- classification rules
# Ordered: the FIRST matching rule sets task_mode. Keep summary/anomaly ahead of the generic
# verbs; projection ahead of reproduce so "expected Run-3 contour ... reinterpret Fig 3" routes
# to the projection deliverable with the reinterpretation recorded as its second half.
RULES = (
    ("summary_plot", re.compile(r"summary.?plot|summary of (the )?(search|limit|analys)|"
                                r"overlay.*(searches|analyses|limits)|combined? (published )?limits", re.I)),
    ("anomaly_search", re.compile(r"model.?agnostic|anomal(y|ous)|strange (event )?topolog|"
                                  r"unusual topolog|CWoLa|weakly.?supervised", re.I)),
    ("projection", re.compile(r"projection|extrapolat|hl.?lhc|run.?[34]\b|future (run|lumi)|"
                              r"expected .{0,40}(limit|contour|exclusion|reach|sensitivit)|"
                              r"hypothetical .{0,30}(tagger|detector|trigger)", re.I)),
    ("reproduce", re.compile(r"\breproduc|re.?deriv|\bmatch (fig|the published)|validate against", re.I)),
    ("scan", re.compile(r"\bscan\b|mass.?plane|\bgrid\b|exclusion contour|contour in the", re.I)),
    ("reinterpret", re.compile(r"reinterpret|is .{0,40}excluded|what (does|do) .{0,40}say about|"
                               r"(limit|constraint)s? on .{0,50}(model|signal|scenario|from)|"
                               r"constrain|expand .{0,40}to", re.I)),
    ("survey", re.compile(r"which analys|what (search|analys)|sensitive to|survey|"
                          r"interested in|anything (say|known) about|"
                          r"is .{0,40}(dead|ruled out|still (viable|alive))|status of", re.I)),
)
UNSUPPORTED_RE = re.compile(r"discover|5\s*(sigma|σ)|observe .{0,30}excess|significance of the excess", re.I)
PARTICLE_LEVEL_RE = re.compile(r"particle.?level|truth.?level|generator.?level|no detector", re.I)
SENSITIVITY_RE = re.compile(r"sensitivit|s/\s*(sqrt|√)\s*b|expected.?only|tagger|discriminat", re.I)


def route(prompt):
    p = prompt.strip()
    targets = {
        "model": None, "process": None,
        "analysis": [m.group(1).upper().replace(" ", "-") for m in ANACODE_RE.finditer(p)],
        "arxiv": ARXIV_RE.findall(p),
        "inspire": [f"ins{m.group(1)}" for m in INSPIRE_RE.finditer(p)],
        "figures": [f"Figure {m.group(1)}" for m in FIGURE_RE.finditer(p)],
        "masses_gev": [float(v) * (1000.0 if u.lower() == "tev" else 1.0)
                       for v, u in MASS_RE.findall(p)],
        "lumi_fb": (float(LUMI_RE.search(p).group(1)) if LUMI_RE.search(p) else None),
    }
    # model hints (free-text, best-effort; the physicist confirms at CHECK-IN 1)
    m = re.search(r"\b(HVT|Z'?′?|W'|slepton|higgsino|wino|bino|toponium|heavy higgs|dark (pion|rho)|"
                  r"semi.?visible jets?|SVJ|pMSSM|axial|pseudo.?scalar|supersymmetry|SUSY)\b", p, re.I)
    targets["model"] = m.group(0) if m else None

    blocking, escalate, assumptions, missing = [], [], [], []

    task_mode = None
    if UNSUPPORTED_RE.search(p):
        task_mode = "unsupported"
        blocking.append("discovery-language: this tool sets 95% CLs exclusion limits, never a "
                        "5-sigma/discovery claim (PRODUCT-CONTRACT section 6.2) — re-phrase as "
                        "an exclusion question")
    if task_mode is None:
        for mode, rx in RULES:
            if rx.search(p):
                task_mode = mode
                break
    if task_mode is None:
        task_mode = "unsupported"
        blocking.append("no supported task mode matched (PRODUCT-CONTRACT section 1) — if this "
                        "IS a reproduction/reinterpretation/survey ask, name the analysis and "
                        "the deliverable")

    # ---- stat mode
    stat_mode = "TBD-judgment"
    blocked_ids = [a for a in targets["arxiv"] if a in SHAPE_FIT_BLOCKLIST]
    if blocked_ids or SHAPE_FIT_HINTS.search(p):
        # Option B (DECISION-SHAPE-FIT.md, signed 2026-07-07): shape/template fits route to the
        # scoped shape_fit.py engine, NOT a blanket refusal. Two per-analysis gates decide whether
        # the limit ships or the run downgrades to blocked-shape-fit (PRODUCT-CONTRACT section 6.1).
        stat_mode = "shape-fit"
        for a in blocked_ids:
            escalate.append(f"arXiv:{a} is a shape-fit analysis ({SHAPE_FIT_BLOCKLIST[a]}): route "
                            f"to the shape_fit.py engine (Option B). REPRESENTABILITY gate — the "
                            f"engine handles binned 1-D shape/bump fits; downgrade to "
                            f"blocked-shape-fit if the fit is unbinned/multi-observable/NN-based. "
                            f"R5 gate — no limit ships until the engine reproduces the paper's own "
                            f"published limit within tolerance (verification-ladder R5); until then "
                            f"the generator-level shape comparison + sensitivity-expected-only is "
                            f"the shippable offer. See framework/interrogations/generality.md.")
        if not blocked_ids:
            escalate.append("shape/template-fit paradigm (~40% boundary): route to the shape_fit.py "
                            "engine (Option B, PRODUCT-CONTRACT section 6.1). Confirm at CHECK-IN 1 "
                            "the target figure to reproduce; the R5 gate holds the limit until the "
                            "engine reproduces the paper's own published fit within tolerance.")
    elif task_mode in ("summary_plot", "survey"):
        stat_mode = "none-survey"
    elif task_mode in ("projection", "anomaly_search") or SENSITIVITY_RE.search(p):
        stat_mode = "sensitivity-expected-only"
    elif NATIVE_SA.search(p):
        stat_mode = "published-likelihood"
    if stat_mode == "TBD-judgment":
        escalate.append("stat_mode: published likelihood vs counting is a per-analysis fact — "
                        "resolve from HEPData at step 2 (workflow/steps/06-acquire-data.md), "
                        "confirm at CHECK-IN 1")

    # ---- detector mode
    if PARTICLE_LEVEL_RE.search(p):
        detector_mode = "particle-level"
        assumptions.append("particle-level requested: results carry the particle-level-proxy "
                           "fidelity label, not an exclusion of record (PRODUCT-CONTRACT 5)")
    elif NATIVE_SA.search(p):
        detector_mode = "simpleanalysis-delphes-native"
    elif task_mode in ("summary_plot", "survey"):
        detector_mode = "particle-level"
        assumptions.append("survey/summary mode: no detector simulation of our own is run")
    else:
        detector_mode = "TBD-judgment"
        escalate.append("detector_mode: Rivet-smearing vs SA/Delphes is a per-analysis fact — "
                        "resolve the routine at step 2 (routine_fetch.py), confirm at CHECK-IN 1")

    # ---- compute plan + cost
    if task_mode in ("summary_plot", "survey", "unsupported") or stat_mode == "blocked-shape-fit":
        compute_plan = "none"
        cost = cost_preflight.estimate("none", 0, 0, "native", 1)
    elif stat_mode == "shape-fit":
        # the shape-fit engine needs signal templates (generation + shower, particle-level) and
        # the fit — a smoke rung first, expanded only after the R5 gate closes on this analysis
        compute_plan = "smoke"
        cost = cost_preflight.estimate("smoke", 1, 2000, "native", 1)
        assumptions.append("shape-fit route (Option B): smoke-rung signal-template generation "
                           "first; the R5 gate must close (reproduce the paper's own fit) before "
                           "any width/mass scan expands — CHECK-IN 1 confirms the target figure")
    elif task_mode in ("anomaly_search", "no_routine"):
        compute_plan = "smoke"
        cost = cost_preflight.estimate("smoke", 1, 1000, "native", 1)
    else:
        compute_plan = "scan"
        n_pts = 12  # the coarse-grid default; the plan check-in refines to the published lattice
        backend = "native" if detector_mode == "simpleanalysis-delphes-native" else "native"
        cost = cost_preflight.estimate("scan", n_pts, 20000, backend, 4)
        assumptions.append(f"compute sized for a coarse {n_pts}-point grid at 20k events/point; "
                           f"CHECK-IN 1 refines to the published lattice")

    # ---- missing inputs
    if task_mode in ("reproduce", "reinterpret", "projection", "scan") and not (
            targets["analysis"] or targets["arxiv"] or targets["inspire"]):
        missing.append("analysis identifier (arXiv id, Inspire id, or analysis code)")
    if task_mode in ("reinterpret", "scan") and not (targets["model"] or targets["masses_gev"]):
        missing.append("model definition (spectrum/cards or the mass-plane ranges)")
    if task_mode == "projection" and not targets["lumi_fb"]:
        missing.append("target luminosity for the projection")
    if task_mode == "survey":
        escalate.append("survey scope (which scenario class / mass range / experiments) is "
                        "confirmed at CHECK-IN 1 before any candidate list is deep-read")

    escalate.append("figure target + early-verification waypoint: [judgment] picks at "
                    "CHECK-IN 1 (checklists/check-ins.md) — never auto-selected")

    contract = {
        "schema_version": 1,
        "prompt": prompt,
        "task_mode": task_mode,
        "targets": targets,
        "detector_mode": detector_mode,
        "stat_mode": stat_mode,
        "required_user_inputs": missing,
        "assumptions": assumptions,
        "compute_plan": compute_plan,
        "cost_estimate": cost,
        "approval_required": True,
        "blocking": blocking,
        "escalate": escalate,
    }
    return contract


# ------------------------------------------------------------------ selftest: the P4 prompts
P4_EXPECT = [
    ("Consider a model (say HVT) with a Z'->WW. Construct a summary plot of ATLAS+CMS searches "
     "sensitive to Z'->WW for m(Z') < 500 GeV.", "summary_plot", "none"),
    ("Assuming toponium is a new resonance (e.g. heavy Higgs), produce a summary plot assessing "
     "limits on this signal from other LHC analyses.", "summary_plot", "none"),
    ("Expand ATLAS non-resonant semi-visible jets (Run 2) to expected limits across a wide range "
     "of dark pion/dark rho masses; assess improvements from a hypothetical dedicated SVJ "
     "tagger.", "projection", "scan"),
    ("Reproduce the dijet+photon analysis in arXiv:2408.00049; roughly match Fig. 5, then "
     "produce results with increasingly large Z' widths up to 0.3 mZ'.", "reproduce", "smoke"),
    ("Reproduce a simplified particle-level version of CMS A->BC (arXiv:2412.03747); match the "
     "inclusive/2-prong/3-prong/AD sensitivity comparisons in Figs. 5-6 at 3 and 5 TeV.",
     "reproduce", "scan"),
    ("I'm interested in model-agnostic searches at ATLAS - strange event topologies in "
     "low-energy regions.", "anomaly_search", "smoke"),
    ("Construct an expected Run-3 (400 fb-1) exclusion contour for the ATLAS displaced-track "
     "analysis (arXiv:2401.14046 + HEPData), overlaid on Fig. 3; also reinterpret Fig. 3 in "
     "the mu-M2 plane (higgsino, M1=M2, tanb=50); captions + procedure.", "projection", "scan"),
    # the three adversarial classes (charter P4): ambiguous, unsupported, missing-inputs
    ("Is supersymmetry dead?", "survey", "none"),          # ambiguous -> survey, zero compute
    ("Discover a new particle in the ATLAS data and tell me its significance.",
     "unsupported", "none"),
    ("Reproduce the analysis and tell me if my model is excluded.", "reproduce", "scan"),
]


def selftest():
    fails = []
    for i, (prompt, want_mode, want_plan) in enumerate(P4_EXPECT, 1):
        c = route(prompt)
        errs = validate(c)
        ok_mode = c["task_mode"] == want_mode
        ok_plan = c["compute_plan"] == want_plan
        ok_valid = not errs
        # prompt 4 now routes to the shape-fit ENGINE (Option B), R5-gated via an escalate flag;
        # prompt 10 must name missing inputs
        extra = True
        if "2408.00049" in prompt:
            extra = (c["stat_mode"] == "shape-fit"
                     and any("R5 gate" in e for e in c["escalate"]))
        if prompt.startswith("Reproduce the analysis and"):
            extra = bool(c["required_user_inputs"])
        tag = "PASS" if (ok_mode and ok_plan and ok_valid and extra) else "FAIL"
        print(f"  [{tag}] P{i}: {c['task_mode']:14s} plan={c['compute_plan']:5s} "
              f"stat={c['stat_mode']:26s} missing={len(c['required_user_inputs'])} "
              f"blocking={len(c['blocking'])}")
        if tag == "FAIL":
            fails.append(f"P{i} (want {want_mode}/{want_plan}, got "
                         f"{c['task_mode']}/{c['compute_plan']}, valid={ok_valid}, extra={extra})")
    if fails:
        sys.exit("route_prompt selftest FAILED:\n  " + "\n  ".join(fails))
    print("route_prompt selftest: all 10 charter-P4 prompts route + validate correctly.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt")
    g.add_argument("--prompt-file")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", help="write task_contract.json here (e.g. <rundir>/inputs/)")
    ap.add_argument("--print", dest="do_print", action="store_true", help="contract to stdout")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    prompt = args.prompt if args.prompt else open(args.prompt_file).read()
    contract = route(prompt)
    errs = validate(contract)
    if errs:  # the router must never emit an invalid contract — this is a router bug
        sys.exit("route_prompt: produced an INVALID contract (router bug):\n  " +
                 "\n  ".join(errs))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        json.dump(contract, open(args.out, "w"), indent=2)
        print(f"wrote {args.out}")
    if args.do_print or not args.out:
        print(json.dumps(contract, indent=2))
    print(f"\nROUTED: task_mode={contract['task_mode']}  detector={contract['detector_mode']}  "
          f"stat={contract['stat_mode']}  plan={contract['compute_plan']}", file=sys.stderr)
    print("NEXT: compose CHECK-IN 1 from this contract (checklists/check-ins.md) — heavy "
          "compute BLOCKS until the physicist approves.", file=sys.stderr)


if __name__ == "__main__":
    main()
