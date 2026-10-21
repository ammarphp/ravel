#!/usr/bin/env python3
"""Deterministic first-pass router: physicist prompt -> task_contract.json.

A WEAK model must not free-hand the request classification: this script maps the
prompt to the docs/reference/scope.md taxonomy with ordered keyword rules — no LLM, no network —
then `validate_task_contract.py` gates the result and CHECK-IN 1 presents it. The [judgment]
half stays explicit: every TBD-judgment field and every `escalate` line is a numbered flag for
the physicist, NEVER a silent guess. Heavy compute is structurally blocked:
approval_required=true always; compute beyond `smoke` requires the CHECK-IN 1 go-ahead.

Stdlib-only. Usage:
  route_prompt.py --prompt "Initiate: reproduce Figure 3 of ..." --out <rundir>/task_contract.json
  route_prompt.py --prompt-file req.txt --print          # contract to stdout only
  route_prompt.py --selftest                              # the reference prompts must route
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ravel.validation.validate_task_contract import validate  # noqa: E402
from ravel.workflow import cost_preflight  # noqa: E402

# ---------------------------------------------------------------- extraction
ARXIV_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
INSPIRE_RE = re.compile(r"\bins(\d{1,8})\b", re.I)
# An analysis code in its general shape: an optional collaboration prefix, an optional preliminary-note
# marker, a group code in capitals, a two- or four-digit year field and a two- or three-digit number,
# separated by hyphens or spaces (no list of collaborations or groups).
ANACODE_RE = re.compile(r"\b((?:[A-Z][A-Za-z]{1,6}[- ])?(?:PAS[- ])?[A-Z][A-Z0-9]{1,6}[- ](?:\d{2}|\d{4})[- ]\d{2,3})\b")
FIGURE_RE = re.compile(r"\bfig(?:ure)?s?\.?\s*(\d+[a-z]?(?:\s*[-–&,]\s*\d+[a-z]?)*)", re.I)
# Rivet routine names carry the experiment, year and INSPIRE record: EXPT_YYYY_I<inspire>, for any
# experiment token (no list of experiments).
RIVET_RE = re.compile(r"\b([A-Z][A-Z0-9]{0,9}_\d{4}_I(\d{1,8})(?:_[A-Za-z0-9]+)?)\b", re.I)
HEPDATA_RE = re.compile(r"\bHEPData\s+(?:record|entry|table)?\s*(?:#|no\.?\s*|number\s+)?(\d{4,7})\b|"
                        r"\bhepdata\.net/record/(\d{4,7})\b", re.I)
_UNIT_GEV = {"kev": 1e-6, "mev": 1e-3, "gev": 1.0, "tev": 1000.0}
MASS_RE = re.compile(r"(?<![\w^\-−⁻.])(\d+(?:\.\d+)?)\s*(keV|MeV|GeV|TeV)\b", re.I)
# a comma/'and' list of numbers sharing ONE trailing unit ("750, 1000, 1250 GeV") — the U1
# leptoquark request's grid form that the single-number regex missed (item 1b).
# A list never starts inside an exponent such as fb^-1.
MASS_LIST_RE = re.compile(r"(?<![\w^\-−⁻.])\d+(?:\.\d+)?(?:\s*(?:,|and)\s*\d+(?:\.\d+)?)+\s*"
                          r"(keV|MeV|GeV|TeV)\b", re.I)
LUMI_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*fb(?:\^?-1|⁻¹|-1)?\b", re.I)
# A collision energy written as one: "at 13 TeV", "√s = 13.6 TeV", "13 TeV data/searches", and an
# energy coordinated with the luminosity of the same "at" phrase ("at 139 fb^-1 and 13 TeV").
SQRT_S_LEFT_RE = re.compile(r"(?:\bat|@|\bpp|\bp\s*p|√\s*s|sqrt\s*\(?\s*s\s*\)?|\bE_?\s*cm|"
                            r"(?:\bat|@)\s*\d+(?:\.\d+)?\s*[afp]b\s*(?:\^?\s*[-−]\s*1|⁻¹)\s*(?:,\s*(?:and\s+)?|and\s+)|"
                            r"\b(?:beam|collision|collider)\s+energy(?:\s+(?:of|is))?|"
                            r"\bcent(?:er|re)[- ]of[- ]mass(?:\s+energy)?(?:\s+of)?)\s*[=:~≈]?\s*$", re.I)
SQRT_S_RIGHT_RE = re.compile(r"^\s*(?:[\w-]+\s+){0,2}?(?:data|dataset|collisions?|measurements?|searches|"
                             r"search|analys[ie]s|events|LHC|pp|run|centre|center|c\.o\.m|collider|"
                             r"beam|proton)\b", re.I)
# Quantities that are not particle masses: widths, decay constants, splittings, bounds, cuts.
NON_MASS_LEFT_RE = re.compile(
    r"(?:\bGamma|Γ|\bwidths?|\bf_?\{?(?:a|π|pi|\\pi|phi|ϕ)\}?|decay\s+constant|\bsplittings?|"
    r"mass\s+(?:difference|gap)s?|Δ\s*m|\bdelta\s*[-_]?\s*m|\bdm|\bbelow|\babove|\bunder|\bover|"
    r"less\s+than|more\s+than|greater\s+than|lower\s+than|higher\s+than|smaller\s+than|"
    r"larger\s+than|at\s+(?:least|most)|up\s+to|beyond|exceed\w*|[<>≤≥⩽⩾]=?|"
    r"\bp_?\{?T\}?|\bE_?\{?T\}?(?:\^?miss)?|\bMET|\bH_?T|\bcuts?|\bthresholds?|"
    r"\bscale|\bcut-?off|\bLambda|Λ|\bvev|\bv\s*=)"
    r"(?:\s*\([^)]{0,20}\))?\s*(?:of|is|=|:|~|≈|at|around|about|near)?\s*$", re.I)
NON_MASS_RIGHT_RE = re.compile(r"^\s*(?:total\s+|decay\s+)?(?:widths?|splittings?|mass\s+(?:difference|gap)s?|"
                               r"decay\s+constant|cuts?|thresholds?|bins?|scale\b|cut-?off|"
                               r"(?:missing|transverse|visible)\s+(?:energy|momentum|mass))\b", re.I)

# ------------------------------------------------- plausibility + word-context guards
# A prompt that pastes a model description carries numbers and jargon that are NOT the task:
# one such prompt was classified task_mode=projection off
# "left-handed projection operator" in a Lagrangian glossary bullet, and extracted sqrt(s)=13000
# and an mT bin edge (3200) as candidate masses. Classification and mass extraction therefore
# run on a VIEW of the prompt with symbol-glossary bullets and $…$/$$…$$ math masked, and each
# mass candidate must survive the context checks below.
GLOSSARY_LINE_RE = re.compile(r"^\s*[-*•]\s*\$[^$\n]+\$\s*(?:is|are|denotes|stands\s+for)\b",
                              re.I)
MATH_SPAN_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]*\$", re.S)
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
BINNING_CUE_RE = re.compile(r"\bbins?\b|bin.?edges?|\bbinned\b|histogram", re.I)
# Standard hadron-collider energies. A bare "at" can attach a mass to the preceding noun ("a slepton at
# 300 GeV", "a mass scan at 750, 1000 GeV"); it states a collision energy for one of these values, or
# when the "at" phrase opens its own clause ("..., at 42.75 TeV"). Explicit syntax admits any value.
COLLIDER_SQRT_S_GEV = {900.0, 2760.0, 5020.0, 6500.0, 6800.0, 7000.0, 8000.0,
                       13000.0, 13600.0, 14000.0}
BARE_AT_RE = re.compile(r"(?:\bat|@)\s*$", re.I)
CLAUSE_AT_RE = re.compile(r"(?:^|[,;:(]|\band|\bor)\s*(?:\bat|@)\s*$", re.I)
COLLIDER_CUE_RE = re.compile(r"collider|\bLHC\b|sqrt\s*\(?\s*s\b|√s|\bbeam\b|"
                             r"cent(?:er|re).of.mass|\bc\.o\.m\b|\bfb\s*(?:\^?-1|⁻¹)|"
                             r"integrated\s+luminosity", re.I)


def classification_view(text):
    """The prompt minus model-DESCRIPTION content: symbol-glossary bullets ('- $P_L$ is the
    left-handed projection operator.') dropped whole, then math spans blanked."""
    lines = [l for l in text.splitlines() if not GLOSSARY_LINE_RE.match(l)]
    return MATH_SPAN_RE.sub(" ", "\n".join(lines))


def _mass_plausible(text, start, end, value_gev):
    """False for candidates that are collider constants, binning/table data — not particle masses."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    line = text[line_start:line_end]
    if TABLE_ROW_RE.match(line):
        return False
    # context window clipped to the candidate's own line: a neighbouring line's binning/collider
    # prose must not veto a legitimate mass
    window = text[max(line_start, start - 40):min(line_end, end + 40)]
    if BINNING_CUE_RE.search(window):
        return False
    if _collision_energy(text, start, end, value_gev, window):
        return False
    left = text[max(line_start, start - 60):start]
    if NON_MASS_LEFT_RE.search(left) or NON_MASS_RIGHT_RE.search(text[end:line_end]):
        return False
    return True


def _collision_energy(text, start, end, value_gev, window):
    """A quantity with its own adjacent collision-energy syntax."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    left = text[max(line_start, start - 80):start]
    stated = bool(SQRT_S_LEFT_RE.search(left))
    if stated and BARE_AT_RE.search(left) and not (round(value_gev, 3) in COLLIDER_SQRT_S_GEV
                                                   or CLAUSE_AT_RE.search(left)):
        stated = False
    return stated or bool(SQRT_S_RIGHT_RE.search(text[end:line_end]))


def _quantities(text):
    """(start, end, value_gev, list_span) for every number with an energy unit."""
    out, list_spans = [], []
    for m in MASS_LIST_RE.finditer(text):
        list_spans.append(m.span())
        unit = _UNIT_GEV[m.group(1).lower()]
        for n in re.findall(r"\d+(?:\.\d+)?", m.group(0)):
            out.append((m.start(), m.end(), float(n) * unit, True))
    for m in MASS_RE.finditer(text):
        if any(s <= m.start() < e for s, e in list_spans):
            continue
        out.append((m.start(), m.end(), float(m.group(1)) * _UNIT_GEV[m.group(2).lower()], False))
    return sorted(out, key=lambda row: row[0])


def extract_masses(text):
    """Candidate particle masses in GeV from the classification view, list-aware + plausibility-
    filtered. Collision energies, widths, decay constants, splittings, bounds and cuts
    are not masses. Order-preserving, de-duplicated; the physicist confirms at CHECK-IN 1."""
    out = [v for start, end, v, _ in _quantities(text) if _mass_plausible(text, start, end, v)]
    seen = set()
    return [v for v in out if not (v in seen or seen.add(v))]


def has_mass_list(text):
    """True when one unit is shared by a list of values ("500, 750 and 1000 GeV")."""
    return any(is_list and _mass_plausible(text, s, e, v) for s, e, v, is_list in _quantities(text))


def extract_sqrt_s(text):
    """The first collision energy written as such, in GeV, else None."""
    for start, end, v, _ in _quantities(text):
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        line_end = len(text) if line_end < 0 else line_end
        window = text[max(line_start, start - 40):min(line_end, end + 40)]
        if _collision_energy(text, start, end, v, window):
            return v
    return None


_VOCABULARY = None


def bsm_vocabulary():
    """Generic new-physics aliases from the packaged routing data file, in file order."""
    global _VOCABULARY
    if _VOCABULARY is None:
        from importlib.resources import files
        data = json.loads(files("ravel").joinpath("data/routing/bsm-vocabulary.json")
                          .read_text(encoding="utf-8"))
        if data.get("kind") != "bsm-vocabulary" or data.get("schema_version") != 1:
            raise ValueError("bsm-vocabulary.json requires kind bsm-vocabulary, schema_version 1")
        terms = []
        for entry in data["entries"]:
            terms.extend(t for t in entry["aliases"] if t not in terms)
        _VOCABULARY = tuple(terms)
    return _VOCABULARY


def _term_pattern(term):
    body = "".join("['′’]" if ch == "'" else r"[\s-]+" if ch in " -" else re.escape(ch)
                   for ch in term)
    # acronyms and primed symbols are case-sensitive ("ALP", "Z'"); names are not
    flags = 0 if term == term.upper() else re.I
    return re.compile(r"(?<![\w'′’])" + body + r"(?:e?s)?(?![\w'′’])", flags)


def extract_models(text):
    """Every vocabulary term in the request, longest first, as written; no overlaps."""
    taken, found = [], []
    for term in sorted(bsm_vocabulary(), key=len, reverse=True):
        for m in _term_pattern(term).finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            taken.append(m.span())
            found.append((m.start(), m.group(0)))
    out = []
    for _, name in sorted(found):
        if name.lower() not in {n.lower() for n in out}:
            out.append(name)
    return out

# Generic wording for a binned shape/template fit. The statistical route is decided from
# the request text and source inspection at statistical admission, never from a paper ID;
# docs/reference/scope.md section 6 states the policy.
SHAPE_FIT_HINTS = re.compile(r"bump.?hunt|shape.?fit|template.?fit|(dijet|diphoton|dilepton)\s+"
                             r"(mass\s+)?(spectrum|resonance)\s+(search|fit)", re.I)
def native_analysis_hint(text):
    """Resolve exact registered analysis identities, never a particle-name hint.

    A request mentioning two registered analyses still needs an explicit analysis
    choice. Registration describes execution support, not validated acceptance.
    """
    from ravel.physics.native_capabilities import discover_capabilities
    CAPABILITIES = discover_capabilities()
    found = []
    for capability in CAPABILITIES.values():
        aliases = set(capability['analysis_ids'])
        aliases.update(value.removeprefix('ATLAS-') for value in tuple(aliases)
                       if value.startswith('ATLAS-'))
        if any(re.search(r'(?<![\w-])' + re.escape(alias).replace(r'\-', r'[- ]') + r'(?![\w-])',
                         text, re.I) for alias in aliases):
            found.append(capability)
    return found[0] if len(found) == 1 else None

# ---------------------------------------------------------------- classification rules
# A request that names one model point, benchmark or spectrum, or asks to recast, is a
# reinterpretation even when its verb is only "constrain".
POINT_CUE_RE = re.compile(
    r"\b(?:my|our|this|that|the\s+(?:supplied|given|provided|following|attached))\s+"
    r"(?:[\w'′-]+\s+){0,2}?(?:model|benchmark|point|scenario|signal|spectrum|card)s?\b|"
    r"\bbenchmark|\b(?:model|parameter|mass|signal|single)\s+point\b|\brecast|\breinterpret|"
    r"\bparam(?:eter)?[_ ]card", re.I)
SEARCH_CUE_RE = re.compile(r"\b(?:search|analysis|analyses|signal\s+regions?)\b", re.I)
# A literature question asks which results exist or how strong they are.
SURVEY_QUESTION_RE = re.compile(
    r"(?:^(?:\w+:\s*)?|\b(?:tell\s+me|list|show\s+me|identify|find|know|determine|ask|summari[sz]e)\s+)"
    r"(?:which|what)(?:\s+[\w'′-]+){0,4}?\s+(?:searches|analyses|measurements|results|experiments)\b|"
    r"(?:^(?:\w+:\s*)?|\b(?:tell\s+me|list|show\s+me|identify|find|know|summari[sz]e)\s+)"
    r"what\s+(?:are|were|is)\s+(?:the\s+|their\s+|its\s+)?(?:strongest|current|latest|best|existing|"
    r"leading|most\s+stringent|tightest|present)\s+(?:[\w'′-]+\s+){0,3}?"
    r"(?:limits?|constraints?|bounds?|exclusions?)\b", re.I | re.M)
# A fit of published measurements is a likelihood built from their values and covariance.
FIT_ACTION_RE = re.compile(r"\b(?:constrain\w*|fit\w*|bound(?:s|ing)?|extract\w*|determin\w*|"
                           r"confidence\s+(?:intervals?|regions?))\b", re.I)
FIT_TARGET_RE = re.compile(r"\bwilson\s+coefficients?|\bSMEFT\b|\bHEFT\b|"
                           r"\bEFT\s+(?:operators?|coefficients?|parameters?)|"
                           r"\bdimension[- ]?(?:six|6|eight|8)\s+operators?|\bcoupling\s+modifiers?|"
                           r"\bkappa|κ|\banomalous\s+couplings?", re.I)
MEASURED_RE = re.compile(r"\bmeasurements?\b|\bSTXS\b|\bsignal[- ]strengths?\b|\bunfolded\b|"
                         r"\b(?:differential|fiducial)\s+cross[- ]sections?\b|\bprecision\s+"
                         r"(?:data|observables|measurements)\b|\belectroweak\s+precision\b", re.I)
FIT_PARAMETER_RE = re.compile(r"\b(?:coefficients?|parameters?|couplings?|operators?|modifiers?)\b", re.I)


def measurement_fit(view):
    """A fit of model parameters to published measurements, not a search reinterpretation."""
    if not FIT_ACTION_RE.search(view) or re.search(r"reinterpret|recast|\bsearch(?:es)?\b", view, re.I):
        return False
    return bool(FIT_TARGET_RE.search(view) or (MEASURED_RE.search(view) and FIT_PARAMETER_RE.search(view)))


def _constrain_is_reinterpret(view):
    return bool(POINT_CUE_RE.search(view) or extract_masses(view)
                or (extract_models(view) and SEARCH_CUE_RE.search(view)))


# Keyword rules are ranked HINTS, never the reading of the request. Each rule is
# (task_mode, pattern, guard, strength, rule_id); the guard, when present, must also hold.
# A strong hint names the request's action ("reproduce", "scan", "is X excluded by");
# a weak hint is an incidental word ("grid", "sensitive to", "Run 3"). Among strong hints the
# documented order decides: summary/anomaly ahead of the generic verbs, projection ahead of
# reproduce so "Run-3 contour ... reinterpret Fig 3" keeps the projection deliverable with the
# reinterpretation recorded as its second half, a literature question ahead of
# reinterpretation. A request with only weak hints takes the open research route with the
# hints attached; a keyword never overrides the semantic reading.
STRONG, WEAK, VETOED = "strong", "weak", "vetoed"
# Data-driven anomaly detection, as opposed to a measured tension ("the W-mass anomaly").
ANOMALY_METHOD_RE = re.compile(
    r"model.?agnostic|anomaly[- ]?(?:detection|detectors?|search(?:es)?|scores?|taggers?|tagging)|"
    r"anomalous\s+(?:events?|jets?|signatures?|topolog\w*)|strange (?:event )?topolog|unusual topolog|"
    r"CWoLa|weakly.?supervised|unsupervised|out[- ]of[- ]distribution", re.I)
ANOMALY_WORD_RE = re.compile(r"\banomal(?:y|ies|ous)\b", re.I)
PROJECTION_RE = re.compile(r"projection(?!\s+operator)|extrapolat|hl.?lhc|future (?:run|lumi)|"
                           r"hypothetical .{0,30}(?:tagger|detector|trigger)|"
                           r"\bexpected\b.{0,40}\brun.?[34]\b|\brun.?[34]\b.{0,40}(?:expected|projected|\d+\s*fb)", re.I)


def _limits_on_model(view):
    return bool(SEARCH_CUE_RE.search(view) or POINT_CUE_RE.search(view))


RULES = (
    ("summary_plot", re.compile(r"summary.?plot|summary of (the )?(search|limit|analys)|"
                                r"overlay.*(searches|analyses|limits)|combined? (published )?limits", re.I), None,
     STRONG, "summary-plot"),
    ("anomaly_search", ANOMALY_METHOD_RE, None, STRONG, "anomaly-detection"),
    # "projection operator" is the Dirac-algebra object, never a task ask
    ("projection", PROJECTION_RE, None, STRONG, "projection"),
    ("reproduce", re.compile(r"\breproduc|re.?deriv|\bmatch (fig|the published)|validate against", re.I), None,
     STRONG, "reproduce"),
    ("likelihood", re.compile(r"\S"), measurement_fit, STRONG, "measurement-fit"),
    ("scan", re.compile(r"\bscan\b|mass.?plane|exclusion contour|contour in the", re.I), None, STRONG, "scan"),
    ("survey", SURVEY_QUESTION_RE, None, STRONG, "literature-question"),
    ("reinterpret", re.compile(r"reinterpret|recast|"
                               r"\b(?:is|are|was|were|would|could|will|does|do|be|been)\b[^?.;\n]{0,200}?"
                               r"\b(?:excluded|disfavou?red)\b|"
                               r"\b(?:excluded|ruled\s+out|disfavou?red)\s+by\b|"
                               r"what (does|do) .{0,40}say about", re.I), None, STRONG, "reinterpret"),
    ("reinterpret", re.compile(r"(limit|constraint)s? on .{0,50}(model|signal|scenario|from)", re.I), _limits_on_model,
     STRONG, "limits-on-model"),
    ("reinterpret", re.compile(r"\bconstrain", re.I), _constrain_is_reinterpret, STRONG, "constrain-model-point"),
    ("survey", re.compile(r"which analys|what (search|analys)|survey|anything (say|known) about|"
                          r"is .{0,40}(dead|ruled out|still (viable|alive))|status of", re.I), None, STRONG, "survey"),
    ("generate", re.compile(r"\b(?:generate|simulate|produce)\b(?:\s+[\w,.~+>()/-]+){0,10}?\s+events?\b|"
                            r"\bgenerate\b.{0,80}\bwith\s+(?:MadGraph|MG5|Pythia|Sherpa|Powheg|Herwig|"
                            r"Whizard|CalcHEP)", re.I), None, STRONG, "generate"),
    # Weak hints: incidental words. They are recorded, never selected on their own.
    ("projection", re.compile(r"\brun.?[34]\b", re.I), None, WEAK, "run-period"),
    ("scan", re.compile(r"\bgrid\b", re.I), None, WEAK, "grid"),
    ("reinterpret", re.compile(r"(limit|constraint)s? on .{0,50}(model|signal|scenario|from)|expand .{0,40}to", re.I),
     None, WEAK, "limits-wording"),
    ("survey", re.compile(r"sensitive to|interested in", re.I), None, WEAK, "interest-wording"),
)
UNSUPPORTED_RE = re.compile(r"discover|5\s*(sigma|σ)|observe .{0,30}excess|significance of the excess", re.I)
PARTICLE_LEVEL_RE = re.compile(r"particle.?level|truth.?level|generator.?level|no detector", re.I)
SENSITIVITY_RE = re.compile(r"sensitivit|s/\s*(sqrt|√)\s*b|expected.?only|tagger|discriminat", re.I)


def ranked_hints(view, prompt=None):
    """Every rule that matches, in rank order, with the matched text and its span in the request."""
    from .request_reading import locate
    prompt = view if prompt is None else prompt
    hints, seen = [], set()
    for rank, (mode, rx, guard, strength, rule) in enumerate(RULES):
        m = rx.search(view)
        if not m or (guard is not None and not guard(view)) or (mode, rule) in seen:
            continue
        seen.add((mode, rule))
        matched = m.group(0).strip()[:200] or view.strip()[:200]
        located = locate(prompt, matched) if rule != "measurement-fit" else None
        hints.append({"mode": mode, "rule": rule, "strength": strength, "rank": rank, "matched": matched,
                      "evidence": [located] if located else []})
    word = ANOMALY_WORD_RE.search(view)
    if word and not ANOMALY_METHOD_RE.search(view):
        located = locate(prompt, word.group(0))
        hints.append({"mode": "anomaly_search", "rule": "anomaly-word", "strength": VETOED,
                      "rank": len(RULES), "matched": word.group(0),
                      "evidence": [located] if located else [],
                      "note": "'anomaly' here names a measured tension or deviation, not data-driven "
                              "anomaly detection; the word does not select a search mode"})
    return hints


def classify(view):
    """The highest-ranked STRONG hint, else None (weak hints alone never select a mode)."""
    return next((h["mode"] for h in ranked_hints(view) if h["strength"] == STRONG), None)


# ---------------------------------------------------------------- compute size
PLANE_CUE_RE = re.compile(
    r"\bscan|\bplanes?\b|\bgrids?\b|\bcontours?\b|\branges?\b|\bacross\b|\bvar(?:y|ying|ied)\b|"
    r"\bsweep|\blattice|\bfunction\s+of\b|\bincreasing(?:ly)?\b|\bseveral\s+(?:masses|points|values)|"
    r"\bmultiple\s+(?:masses|points|values)|\bfrom\s+[\d.]+\s*(?:[kMGT]eV)?\s+(?:to|up\s+to)\s+[\d.]+|"
    r"\bbetween\s+[\d.]+\s*(?:[kMGT]eV)?\s+and\s+[\d.]+|\bup\s+to\s+[\d.]+", re.I)
SINGLE_POINT_RE = re.compile(r"\bbenchmark|\b(?:model|parameter|mass|signal|single|one|this|that)\s+"
                             r"(?:mass\s+)?point\b|\bspectrum\b|\bparam(?:eter)?[_ ]card", re.I)


# A yes/no exclusion question about one hypothesis ("Is my Z' excluded by ...?") asks
# about one point even when it names no mass.
YES_NO_EXCLUSION_RE = re.compile(r"\b(?:is|are|was|were|would|could|will|does|do)\b[^?.;\n]{0,200}?"
                                 r"\b(?:excluded|disfavou?red|ruled\s+out|allowed|viable)\b", re.I)


def single_point_request(view, masses):
    """One model point: no plane/grid/range cue, no shared-unit list, and a point cue."""
    if PLANE_CUE_RE.search(view) or has_mass_list(view):
        return False
    return bool(SINGLE_POINT_RE.search(view) or 1 <= len(masses) <= 3
                or (YES_NO_EXCLUSION_RE.search(view) and not re.search(r"\breproduc", view, re.I)))


# ---------------------------------------------------------------- prescribed statistics
_SIGMA = r"(?:sigma|σ|std\.?\s*dev\w*|standard\s+deviations?)"
_STAT_NOUN = r"(?:region|contour|band|area|interval|limit|level|bound)"
PRESCRIBED_STAT_RES = (
    re.compile(r"\b\d+(?:\.\d+)?\s*[- ]?\s*" + _SIGMA + r"(?:\s+[\w-]+){0,2}?\s+(?:excluded|exclusion|"
               r"excluding|allowed|preferred|" + _STAT_NOUN + r")\b(?:\s+" + _STAT_NOUN + r")?", re.I),
    re.compile(r"\b(?:excluded|exclusion|allowed)\s+" + _STAT_NOUN + r"\s+(?:at|of)\s+\d+(?:\.\d+)?\s*[- ]?\s*"
               + _SIGMA, re.I),
    re.compile(r"(?:Δ|\\Delta\s*|\bdelta\s*[-_ ]?\s*)(?:χ|\\chi|chi)\s*(?:\^?\s*\{?2\}?|²|[-_ ]?squared?)"
               r"(?:\s*(?:[<>≤≥=]=?|of|equal\s+to)\s*\d+(?:\.\d+)?)?", re.I),
    re.compile(r"(?<![\d.])(?!95(?:\.0+)?\s*%)\d{2}(?:\.\d+)?\s*%\s*(?:CLs?|C\.L\.|confidence(?:\s+level)?|"
               r"credib\w*)(?!\w)", re.I),
    re.compile(r"\bcredib(?:le|ility)\s+(?:intervals?|regions?)|\bBayes(?:ian)?\s+(?:limits?|intervals?|"
               r"posteriors?)", re.I),
    re.compile(r"\b(?:Z(?:_?\{?\w+\}?)?|significance|sensitivity|q_?\{?0\}?|q_?\{?mu\}?|statistic|metric|"
               r"figure\s+of\s+merit|FOM)\s*(?:=|≡|:=|defined\s+as|given\s+by)\s*[^;\n]*?"
               r"(?:sqrt|√|\blog|\bln|/)[^;\n]*?(?=\s+(?:for|with|at|using|where|when|and\s+(?:report|plot|"
               r"show|quote|draw))\b|[;\n]|\.(?:\s|$)|$)", re.I),
    re.compile(r"\bS\s*/\s*(?:sqrt|√)\s*\(?\s*B[^;\n,]{0,30}?(?=\s+(?:for|with|at|using|where|when|and)\b|"
               r"[;\n,]|\.(?:\s|$)|$)", re.I),
)


# A statistic named and then written as a formula without "=": "the significance 2(sqrt(S+B) - sqrt(B))".
FORMULA_STAT_RE = re.compile(r"\b(?:significance|test\s+statistic|statistic|metric|figure\s+of\s+merit|FOM)\s+"
                             r"(?:of\s+|as\s+)?(?=[\d(√A-Za-z][^;\n]{0,80}?(?:sqrt|√|\blog\b|\bln\b))", re.I)


def _formula_matches(text):
    """(start, end) of a named statistic followed by a formula, ending at its balanced parentheses."""
    for m in FORMULA_STAT_RE.finditer(text):
        depth, end, seen = 0, None, False
        for i in range(m.end(), min(len(text), m.end() + 160)):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    break
                if depth == 0:
                    end = i + 1
                    seen = seen or bool(re.search(r"sqrt|√|log|ln", text[m.end():end], re.I))
            elif depth == 0 and (ch in ";\n," or re.match(r"\s+(?:with|for|at|using|where|when|and)\b", text[i:])):
                break
        if end is not None and seen:
            yield m.start(), end


def prescribed_statistics(text):
    """Exact spans of statistics the request prescribes (formula, N-sigma region, Δχ², CL)."""
    spans = []
    formulas = list(_formula_matches(text))
    for rx in (*PRESCRIBED_STAT_RES, None):
        for m in (rx.finditer(text) if rx is not None else
                  (re.compile(re.escape(text[s:e])).search(text, s) for s, e in formulas)):
            if any(s <= m.start() and m.end() <= e for s, e, _ in spans):
                continue
            spans = [row for row in spans if not (m.start() <= row[0] and row[1] <= m.end())]
            spans.append((m.start(), m.end(), m.group(0).strip()))
    return [span for _, _, span in sorted(spans)]


def _record_prescribed(contract, spans):
    if not spans:
        return
    contract["stat_mode_note"] = "requested statistic: " + "; ".join(spans)
    contract["escalate"] = [e for e in contract["escalate"] if not e.startswith("stat_mode:")]
    contract["escalate"].insert(0, "requested statistic: " + "; ".join(f"'{s}'" for s in spans) +
                                " is the requested quantity. Deliver it as the primary result with its "
                                "exact definition; a 95% CLs limit may accompany it, never replace it.")


# ---------------------------------------------------------------- generation stages
GENERATION_STAGES = (
    ("shower", re.compile(r"\bshower\w*|\bhadroni[sz]\w*|\bPythia|\bHerwig|\bparticle[- ]level", re.I)),
    ("detector", re.compile(r"\bdetector\w*|\bDelphes|\breconstruct\w*|\bfast[- ]?sim\w*|\bsmear\w*", re.I)),
    ("analysis", re.compile(r"\bacceptance|\bcut[- ]?flow|\bsignal\s+regions?|\bRivet|\bSimpleAnalysis|"
                            r"\bselection\s+efficienc\w*", re.I)),
)
# A served stage still blocks when the request names a program the scoped stage does not run
# (the scoped shower stage is Pythia 8 only).
UNSERVED_STAGE_PROGRAMS = {"shower": re.compile(r"\bHerwig\w*|\bSherpa", re.I)}
_NEGATED_STAGE_RE = re.compile(r"\b(?:no|without|skip(?:ping)?|omit(?:ting)?|not|before)\s+(?:[\w-]+\s+){0,2}$", re.I)


def unserved_generation_stages(text):
    """Blocking entries for requested stages the scoped generate adapter cannot serve."""
    from ravel.workflow import scoped_spec
    served = " ".join(scoped_spec.GENERATION["properties"]).lower()
    out = []
    for stage, rx in GENERATION_STAGES:
        hits = [m for m in rx.finditer(text) if not _NEGATED_STAGE_RE.search(text[max(0, m.start() - 40):m.start()])]
        program = UNSERVED_STAGE_PROGRAMS.get(stage)
        program = program.search(text) if hits and program is not None else None
        if hits and (stage not in served or program is not None):
            named = (program or hits[0]).group(0)
            out.append(f"requested {stage} stage ('{named}') has no scoped generate route; "
                       f"the parton-level adapter does not serve it. Keep it as an unmet stage of the "
                       f"original request and resolve a route for it at CHECK-IN 1.")
    return out


def _check_target_identities(override, prompt):
    """A host interpretation may correct targets, never introduce an unstated identifier."""
    flat = re.sub(r"[\s_-]+", "", prompt).lower()
    for key in ("analysis", "arxiv", "inspire", "hepdata"):
        for value in override.get(key, []):
            needle = re.sub(r"[\s_-]+", "", value).lower()
            if key == "inspire":
                needle = needle.removeprefix("ins")
            if needle not in flat:
                raise ValueError(f"interpretation target {key} {value!r} is absent from the request")


def extract_targets(active, view):
    analysis = [m.group(1).upper().replace(" ", "-") for m in ANACODE_RE.finditer(active)]
    inspire = [f"ins{m.group(1)}" for m in INSPIRE_RE.finditer(active)]
    for m in RIVET_RE.finditer(active):
        routine = m.group(1).upper()
        analysis.append(routine if not routine.startswith("MC_") else m.group(1))
        inspire.append(f"ins{m.group(2)}")
    hepdata = [m.group(1) or m.group(2) for m in HEPDATA_RE.finditer(active)]
    models = extract_models(active)
    lumi = LUMI_RE.search(active)

    def unique(values):
        seen = set()
        return [v for v in values if not (v in seen or seen.add(v))]
    return {
        "model": ", ".join(models) if models else None,
        "models": models,
        "process": None,
        "analysis": unique(analysis),
        "arxiv": ARXIV_RE.findall(active),
        "inspire": unique(inspire),
        "hepdata": unique(hepdata),
        "figures": [f"Figure {m.group(1)}" for m in FIGURE_RE.finditer(active)],
        "masses_gev": extract_masses(view),
        "sqrt_s_gev": extract_sqrt_s(view),
        "lumi_fb": float(lumi.group(1)) if lumi else None,
    }


def _stated_population(reading):
    """Points and events the request states: (points or None, events or None). Never a default."""
    points = events = None
    for fact in reading["facts"]:
        value = fact["value"]
        if fact["type"] == "parameter_values" and points is None:
            points = len(value["values"])
        elif fact["type"] == "parameter_range" and points is None and value.get("step") and value["step"].get("value"):
            def scaled(number, unit):
                factor = _UNIT_GEV.get((unit or "").lower())
                return number * factor if factor is not None else (number if unit == value.get("unit") else None)
            low, high = scaled(value["low"], value.get("low_unit")), scaled(value["high"], value.get("unit"))
            step = scaled(value["step"]["value"], value["step"].get("unit") or value.get("unit"))
            if None not in (low, high, step) and step > 0 and high >= low:
                points = int(round((high - low) / step)) + 1
        elif fact["type"] == "event_count" and value.get("role") != "observed" and events is None:
            events = int(value["count"])
    return points, events


def _decide(prompt, interpretation, semantic, view, reading):
    """The Stage 1 label (derived_label D1-D5) for this request; hints never admit."""
    from ravel.workflow import derived_label
    intent = semantic if (semantic is not None and semantic.get("source") == "host-agent") else None
    label = derived_label.derive(reading, None, intent=intent)
    return {"task_mode": label["task_mode"], "rule": label["rule"],
            "status": "open" if label["open"] else label["status"],
            "blocking": list(label["blocking"]), "label": label}


def _open_contract(prompt, targets, decision, reading):
    """D5 open parent: the whole request is retained and composed from the catalogue; no compute."""
    rows = [a["issue"] for a in reading["ambiguities"] if a["status"] == "open" and a["physics_critical"]]
    return {"schema_version": 1, "prompt": prompt, "task_mode": "research", "targets": targets,
            "detector_mode": "none", "stat_mode": "TBD-judgment", "required_user_inputs": rows,
            "assumptions": ["Whole original task retained. An open research parent composes the request from the "
                            "operation catalogue; each child runs under its own contract and CHECK-IN 1.",
                            "Route hints in inputs/reading.json are recorded, never admitted; no rule narrowed "
                            "the request to one bounded shape."],
            "compute_plan": "none", "approval_required": True, "blocking": [],
            "escalate": ["stat_mode: choose the original requested calculation or research metric from actual "
                         "source inputs; no exclusion metric is substituted."]}


def _finish(contract, decision, prescribed):
    if contract["task_mode"] != "unsupported":
        _record_prescribed(contract, prescribed)
    return contract


def _route(prompt, interpretation=None, reading=None, records=None):
    from ravel.workflow import intake, request_reading
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("the request must not be blank")
    reading = request_reading.document(prompt) if reading is None else reading
    semantic = intake.proposal(prompt, interpretation)
    p = prompt.strip()
    active = intake.actionable_text(intake.routing_text(p))
    view = classification_view(active)
    native = native_analysis_hint(view)
    targets = extract_targets(active, view)
    if interpretation is not None and interpretation.get("targets"):
        override = interpretation["targets"]
        _check_target_identities(override, prompt)
        targets.update(override)
        if "model" in override and "models" not in override:
            targets["models"] = [override["model"]] if override["model"] else []
        elif "models" in override and "model" not in override:
            targets["model"] = ", ".join(override["models"]) or None
    prescribed = prescribed_statistics(active)

    blocking, escalate, assumptions, missing = [], [], [], []
    decision = _decide(prompt, interpretation, semantic, view, reading)
    if records is not None:
        records["label"] = decision["label"]
    task_mode = decision["task_mode"]
    blocking.extend(decision["blocking"])
    if semantic is not None and semantic.get("source") != "host-agent":
        # The local parser's draft is kept only where it agrees with the derived label.
        if ("survey" if semantic["kind"] == "method_study" else semantic["kind"]) != task_mode:
            semantic = None
    if decision["status"] == "open":
        return _finish(_open_contract(prompt, targets, decision, reading), decision, prescribed)

    if task_mode in ("calculation", "research"):
        contract = {"schema_version": 1, "prompt": prompt, "task_mode": task_mode,
            "targets": targets, "detector_mode": "none", "stat_mode": "TBD-judgment",
            "required_user_inputs": list(semantic["unresolved"]) if semantic else [],
            "assumptions": ["Whole original task retained; initial preparation is not scientific completion."],
            "compute_plan": "none", "approval_required": True, "blocking": [],
            "escalate": ["stat_mode: choose the original requested calculation or research metric from actual source inputs; no exclusion metric is substituted."]}
        if semantic:
            contract["intake"] = semantic
        return _finish(contract, decision, prescribed)

    if task_mode in ("generate", "likelihood"):
        contract = {
            "schema_version": 1, "prompt": prompt, "task_mode": task_mode,
            "targets": targets,
            "detector_mode": "parton-level" if task_mode == "generate" else "none",
            "stat_mode": "none-generation" if task_mode == "generate" else "provided-likelihood",
            "required_user_inputs": ["explicit scoped specification for ravel plan --spec"],
            "assumptions": ["Scoped delivery does not certify detector acceptance or reproduce a paper."],
            "compute_plan": "none", "approval_required": True, "blocking": [],
            "escalate": ["Review the concrete recipe, observable, approximation and budget at CHECK-IN 1."],
        }
        if task_mode == "generate":
            requested = "\n".join([active, *(([semantic["objective"], *semantic["requested_outputs"]])
                                              if semantic else [])])
            contract["blocking"].extend(unserved_generation_stages(requested))
        elif measurement_fit(view):
            contract["required_user_inputs"] = [
                "published central values, uncertainties and correlation/covariance of every fitted measurement",
                "prediction of each measurement as a function of the fitted parameters, with its convention and order",
                "fitted parameters, their ranges and any parameters held fixed"]
            contract["escalate"].insert(0, "fit of published measurements: build the likelihood from the "
                                           "published values and covariance; no event generation is planned. "
                                           "Confirm the measurement set, parameterisation and statistic at CHECK-IN 1.")
        if semantic:
            contract["intake"] = semantic
        return _finish(contract, decision, prescribed)

    if task_mode == "survey" and semantic and semantic["kind"] == "method_study":
        return _finish(intake.method_study_contract(prompt, targets, semantic), decision, prescribed)

    # ---- stat mode
    stat_mode = "TBD-judgment"
    if semantic and semantic["kind"] == "method_study":
        stat_mode = "none-survey"
    elif SHAPE_FIT_HINTS.search(view):
        # The scoped shape-fit policy (docs/reference/scope.md section 6): shape/template fits route to the
        # scoped shape_fit.py engine, NOT a blanket refusal. Two per-analysis gates decide whether
        # the limit ships or the run downgrades to blocked-shape-fit (docs/reference/scope.md section 6.1).
        stat_mode = "shape-fit"
        escalate.append("shape/template fit: inspect the published workspace, channels, nuisance "
                        "modifiers, signal contamination and native runtime before choosing a "
                        "statistical engine. Confirm the target at CHECK-IN 1; the R5 gate holds "
                        "the limit until the selected route reproduces the paper's own fit "
                        "within its stated tolerance. A shape label does not select shape_fit.py.")
    elif task_mode in ("summary_plot", "survey"):
        stat_mode = "none-survey"
    elif task_mode in ("projection", "anomaly_search") or SENSITIVITY_RE.search(view):
        stat_mode = "sensitivity-expected-only"
    elif native and any(s in native['statistics'] for s in ('compressed-likelihood', 'mapped-likelihood')):
        stat_mode = "published-likelihood"
    if prescribed and stat_mode != "none-survey" and task_mode != "unsupported":
        stat_mode = "prescribed-statistic"
    if stat_mode == "TBD-judgment":
        escalate.append("stat_mode: published likelihood, counting or shape/template fit is a per-analysis fact — "
                        "resolve from HEPData at step 2 (docs/workflow/steps/06-acquire-data.md), "
                        "confirm at CHECK-IN 1")

    # ---- detector mode
    if PARTICLE_LEVEL_RE.search(view):
        detector_mode = "particle-level"
        assumptions.append("particle-level requested: results carry the particle-level-proxy "
                           "fidelity label, not an exclusion of record (docs/reference/scope.md section 5)")
    elif native:
        detector_mode = "simpleanalysis-delphes-native"
    elif task_mode in ("summary_plot", "survey"):
        detector_mode = "particle-level"
        assumptions.append("survey/summary mode: no detector simulation of our own is run")
    else:
        detector_mode = "TBD-judgment"
        escalate.append("detector_mode: Rivet-smearing vs SA/Delphes is a per-analysis fact — "
                        "resolve the routine at step 2 (routine_fetch.py), confirm at CHECK-IN 1")

    # ---- compute plan + cost (sized only from what the request states)
    stated_points, stated_events = _stated_population(reading)
    if task_mode in ("summary_plot", "survey", "unsupported") or stat_mode == "blocked-shape-fit":
        compute_plan = "none"
        cost = cost_preflight.estimate("none", 0, 0, "native", 1)
    elif stat_mode == "shape-fit" and re.search(r"\b(?:supplied|provided|given)\b.{0,100}\b(?:workspace|likelihood|templates?|histograms?)\b|without\s+(?:new\s+)?(?:events?|generat)|no\s+(?:new\s+)?events?", active, re.I):
        compute_plan = "none"
        cost = cost_preflight.estimate("none", 0, 0, "native", 1)
        assumptions.append("Prepare the supplied statistical-input route and explicit solver budget; "
                           "no event generation is inferred from a shape-fit label. Full reproduction "
                           "and its validation remain the original deliverable.")
    elif stat_mode == "shape-fit":
        # the shape-fit engine needs signal templates (generation + shower, particle-level) and
        # the fit — a smoke rung first, expanded only after the R5 gate closes on this analysis
        compute_plan = "smoke"
        cost = cost_preflight.estimate("smoke", 1, 2000, "native", 1)
        assumptions.append("shape-fit route: smoke-rung signal-template generation "
                           "first; the R5 gate must close (reproduce the paper's own fit) before "
                           "any width/mass scan expands — CHECK-IN 1 confirms the target figure")
    elif task_mode in ("anomaly_search", "no_routine"):
        # The rung keeps approval and the ladder in force; its statistics are a CHECK-IN 1 question.
        compute_plan = "smoke"
        cost = cost_preflight.estimate("smoke", 1, stated_events, "native", 1)
        escalate.append("smoke statistics: the request states no event count; CHECK-IN 1 asks for it")
    elif task_mode != "scan" and single_point_request(view, targets["masses_gev"]):
        compute_plan = "full"
        cost = cost_preflight.estimate("full", 1, stated_events, "native", 1)
        if stated_events is None:
            escalate.append("statistics: the request states no event count for its model point; "
                            "CHECK-IN 1 asks for it")
    else:
        compute_plan = "scan"
        cost = cost_preflight.estimate("scan", stated_points or 1, stated_events, "native", 1)
        if stated_points is None:
            escalate.append("scan grid: the request states no grid; CHECK-IN 1 asks for the points "
                            "(the estimate counts one point until then)")
        if stated_events is None:
            escalate.append("statistics: the request states no events per point; CHECK-IN 1 asks for them")

    # ---- missing inputs
    if task_mode in ("reproduce", "reinterpret", "projection", "scan") and not (
            targets["analysis"] or targets["arxiv"] or targets["inspire"]):
        escalate.append("analysis identity unresolved: discover the public paper/catalogue/source "
                        "from the original description before requesting an identifier; do not "
                        "narrow a multi-analysis request to a single default analysis")
    if task_mode in ("reinterpret", "scan") and not (targets["model"] or targets["masses_gev"]):
        missing.append("model definition (spectrum/cards or the mass-plane ranges)")
    if task_mode == "projection" and intake.luminosity_projection_request(view) and not targets["lumi_fb"]:
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
    if semantic and task_mode != "unsupported":
        contract["intake"] = semantic
        contract["required_user_inputs"].extend(semantic["unresolved"])
        contract["assumptions"].append("Grounded intent is a draft interpretation, not execution approval or a physics validation.")
    return _finish(contract, decision, prescribed)


# ------------------------------------------------------------ selftest: the reference prompts
# Generic request shapes, one per route family. Held-out evaluation prompts never appear here.
REFERENCE_PROMPTS = [
    ("Make a summary plot of published ATLAS and CMS limits on a heavy neutral vector boson "
     "decaying to boson pairs below 2 TeV.", "summary_plot", "none"),
    ("Which LHC searches constrain a light pseudoscalar decaying to muon pairs?", "survey", "none"),
    ("Extend a published search to expected limits across a wide range of mediator masses and "
     "assess the gain from a hypothetical improved jet tagger.", "projection", "scan"),
    ("Reproduce the resonance analysis in the attached paper; roughly match Fig. 2, then produce "
     "results for increasingly large resonance widths.", "reproduce", "scan"),
    ("Reproduce a simplified particle-level version of a CMS three-body resonance search "
     "(the attached paper); match its sensitivity comparisons in Figs. 4-5 at 3 and 5 TeV.",
     "reproduce", "scan"),
    ("I'm interested in model-agnostic searches for unusual event topologies at low energy.",
     "anomaly_search", "smoke"),
    ("Construct an expected Run-3 (300 fb-1) exclusion contour for a displaced-vertex analysis "
     "(the attached paper + HEPData), overlaid on Fig. 2; also reinterpret Fig. 2 in a "
     "two-parameter mass plane; captions + procedure.", "projection", "scan"),
    # ambiguous, unsupported and missing-input requests
    ("Is supersymmetry dead?", "survey", "none"),
    ("Discover a new particle in the ATLAS data and tell me its significance.",
     "research", "none"),
    ("Reproduce the analysis and tell me if my model is excluded.", "reproduce", "scan"),
    # one model point, a fit to published measurements, staged generation, prescribed statistic
    ("Would a 1.1 TeV gluino with a 200 GeV neutralino be excluded by the multijet search?",
     "reinterpret", "full"),
    ("Fit two Wilson coefficients to published Higgs measurements with their covariance.",
     "calculation", "none"),
    ("Generate 10k Drell-Yan events with MadGraph, shower them with Pythia and plot the dimuon mass.",
     "generate", "none"),
    ("Find the 2-sigma excluded region for a W' boson in the coupling-mass plane.", "scan", "scan"),
]


def _selftest_extra(prompt, c):
    """Shape-specific checks beyond task_mode/compute_plan."""
    if "resonance analysis in arXiv" in prompt:
        # an identifier alone never selects the statistic; generic shape-fit wording does
        hinted = route(prompt.replace("resonance analysis", "bump hunt"))
        return (c["stat_mode"] == "TBD-judgment"
                and any(e.startswith("stat_mode:") for e in c["escalate"])
                and hinted["stat_mode"] == "shape-fit"
                and any("R5 gate" in e for e in hinted["escalate"]))
    if prompt.startswith("Reproduce the analysis and"):
        return bool(c["required_user_inputs"]) or any("analysis identity unresolved" in e for e in c["escalate"])
    if prompt.startswith("Would a"):
        return c["cost_estimate"]["points"] == 1 and c["targets"]["masses_gev"] == [1100.0, 200.0]
    if prompt.startswith("Generate"):
        # the scoped Pythia 8 shower stage serves this; a Herwig shower is a stage the scoped
        # adapter does not run, so the request becomes a research parent that keeps it as an obligation
        herwig = route(prompt.replace("Pythia", "Herwig"))
        return (not any("shower" in b for b in c["blocking"]) and herwig["task_mode"] == "research"
                and any(o["criteria"].get("stage") == "shower" for o in herwig["task_requirements"]["obligations"]))
    if "2-sigma" in prompt:
        return c["stat_mode"] == "prescribed-statistic" and "2-sigma excluded region" in c["stat_mode_note"]
    if prompt.startswith("Fit two"):
        return c["targets"]["masses_gev"] == [] and c["blocking"] == []
    return True


def selftest():
    fails = []
    for i, (prompt, want_mode, want_plan) in enumerate(REFERENCE_PROMPTS, 1):
        c = route(prompt)
        errs = validate(c)
        ok_mode = c["task_mode"] == want_mode
        ok_plan = c["compute_plan"] == want_plan
        ok_valid = not errs
        extra = _selftest_extra(prompt, c)
        tag = "PASS" if (ok_mode and ok_plan and ok_valid and extra) else "FAIL"
        print(f"  [{tag}] P{i}: {c['task_mode']:14s} plan={c['compute_plan']:5s} "
              f"stat={c['stat_mode']:26s} missing={len(c['required_user_inputs'])} "
              f"blocking={len(c['blocking'])}")
        if tag == "FAIL":
            fails.append(f"P{i} (want {want_mode}/{want_plan}, got "
                         f"{c['task_mode']}/{c['compute_plan']}, valid={ok_valid}, extra={extra})")
    if fails:
        sys.exit("route_prompt selftest FAILED:\n  " + "\n  ".join(fails))
    print(f"route_prompt selftest: all {len(REFERENCE_PROMPTS)} reference prompts route + validate correctly.")


def _init_run_state(out_path, contract):
    """(catalogue N11): EVERY contract write initializes the minimal run_state.json in the
    rundir, including compute=none tracks. Failed ledger writes fail intake."""
    from ravel.workflow import workflow_state
    d = os.path.dirname(os.path.abspath(out_path))
    rundir = os.path.dirname(d) if os.path.basename(d) == "inputs" else d
    if os.path.isfile(os.path.join(rundir, "run_state.json")):
        raise ValueError("run ledger already exists; preserve the existing request and use an explicit new run")
    state = workflow_state.new_state(rundir, contract, out_path,
                                     os.environ.get("CLAUDE_SESSION_ID", ""))
    workflow_state.write_state(rundir, state)
    print(f"initialized {os.path.join(rundir, 'run_state.json')}")



def route(prompt, interpretation=None):
    """Every route retains the literal whole request, including refusal/recovery."""
    return route_records(prompt, interpretation)[0]


def route_records(prompt, interpretation=None, additions=None, *, output_workspace=None, output_retained=None,
                  output_census=True):
    """(contract, reading, label): the v1 contract, its reading sidecar and the derived label.

    The reading is the deterministic floor, extended componently by `additions` when given. The
    obligation census (`task_completion.census_from_reading`) is attached to every request.
    """
    from .request_reading import document
    from .task_completion import census_from_reading
    reading = document(prompt, additions)
    records = {}
    contract = _route(prompt, interpretation=interpretation, reading=reading, records=records)
    contract['task_requirements'] = census_from_reading(prompt, reading, output_workspace=output_workspace,
                                                        output_retained=output_retained,
                                                        output_census=output_census)
    # The contract carries the reading's source restrictions; validate_pins requires equality.
    from .source_policy import from_reading
    restrictions = from_reading(reading)
    if restrictions:
        contract['forbidden_sources'] = restrictions
    from .completion_lifecycle import mark_new_contract
    mark_new_contract(contract)
    from .intake import handoff_applicable
    if handoff_applicable(contract):
        from copy import deepcopy
        requirements = contract['task_requirements']
        requirements['assignments'] = [{"id": "original-task", "purpose": "Complete the exact original scientific task, preserving all outputs and unresolved requirements.",
            "coverage": [{"obligation_id": row['id'], "criteria": deepcopy(row['criteria'])}
                         for row in requirements['obligations']]}]
    return contract, reading, records.get('label')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt")
    g.add_argument("--prompt-file")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", help="write task_contract.json here (e.g. <rundir>/inputs/)")
    ap.add_argument("--print", dest="do_print", action="store_true", help="contract to stdout")
    ap.add_argument("--interpretation", help="grounded host-agent interpretation JSON")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    prompt = args.prompt if args.prompt else open(args.prompt_file).read()
    from ravel.workflow.state_io import read_json
    contract = route(prompt, interpretation=read_json(args.interpretation) if args.interpretation else None)
    errs = validate(contract)
    if errs:  # the router must never emit an invalid contract — this is a router bug
        sys.exit("route_prompt: produced an INVALID contract (router bug):\n  " +
                 "\n  ".join(errs))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "x", encoding="utf-8") as stream:
            json.dump(contract, stream, indent=2, allow_nan=False)
        _init_run_state(args.out, contract)
        print(f"wrote {args.out}")
        # Listed legacy path: this contract carries no agent_layer_epoch and no pinned reading
        # or plan, so the epoch-two decision gates and custody recorders do not decide its run.
        print("route_prompt: WARNING: this contract is not release-shaped (no agent_layer_epoch 2, no custody "
              "run_init); the decision gates keep their pre-release decision for it. Use `ravel initiate` "
              "for the release intake.", file=sys.stderr)
    if args.do_print or not args.out:
        print(json.dumps(contract, indent=2))
    print(f"\nROUTED: task_mode={contract['task_mode']}  detector={contract['detector_mode']}  "
          f"stat={contract['stat_mode']}  plan={contract['compute_plan']}", file=sys.stderr)
    print("NEXT: compose CHECK-IN 1 from this contract (checklists/check-ins.md) — heavy "
          "compute BLOCKS until the physicist approves.", file=sys.stderr)


if __name__ == "__main__":
    main()
