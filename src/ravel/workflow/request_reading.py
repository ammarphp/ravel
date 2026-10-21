"""The request reading: what a request states, bound to exact spans of its text.

`document(prompt)` is the deterministic reader. It writes the reading floor
(`inputs/reading.json`, schema `request-reading` version 1): typed witness items
found in the text, the facts drawn from them, constraints, deliverables, an
ambiguity ledger, boundaries and the dismissal of every witness item no fact
uses. A host agent may extend the floor with `merge`; it may never delete or
weaken an item the reader found. `check` evaluates the rules the schema cannot.

The reading records the request. It selects no route, authorizes no compute and
grants no authority: a delegation phrase is recorded with `authority_granted`
false, and an `identity_context` constraint is a locator that no decision reads.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path

from ravel.validation.intake_records import (  # noqa: F401  (the one statement of the vocabularies)
    ADDITIONS_KIND, ADDITIONS_SCHEMA, AMBIGUITY_STATUS, ARTIFACT_KINDS, AUTHOR as AUTHOR_SCHEMA, AUTHOR_ACTORS,
    BOUNDARY_CLASSES, CLAIM_KINDS, CONSTRAINT_TYPES, DISMISSALS, FACT_AUTHORITY, FIELD_AUTHORITY, READING_KIND as KIND,
    READING_SCHEMA, SCHEMA_VERSION, WHOLE_REQUEST_BOUNDARIES)

READER_MODULE = "ravel.workflow.request_reading"

# Constraint types that become obligations of the request, with their obligation kind
# (`task_completion.KINDS`) and identifier prefix. A delegation phrase grants nothing and an
# identity context is a locator, so neither is an obligation.
CONSTRAINT_OBLIGATIONS = {
    "requested_stage": ("method", "stage"), "negated_stage": ("quality", "negated-stage"),
    "requested_tool": ("method", "tool"), "tool_allowlist": ("method", "tools"),
    "prescribed_statistic": ("quantity", "statistic"), "source_restriction": ("quality", "source"),
    "blinding": ("quality", "blinding"), "template": ("deliverable", "template"),
    "keep_fixed": ("quality", "fixed"), "budget": ("quality", "budget"),
}
RANGE_FACTS = ("parameter_range", "parameter_values")
ORIGINAL = "original-request"


# The reading schema and the host-additions schema live in ravel.validation.intake_records.
SECTIONS = ("witness", "facts", "constraints", "deliverables", "ambiguities", "boundaries")
ADDABLE = ("facts", "constraints", "deliverables", "ambiguities")


# ------------------------------------------------------------------ spans
def span(prompt, start, end):
    return {"start": start, "end": end, "text": prompt[start:end]}


def locate(prompt, text):
    """The span of `text` in the original request, exact first, then case-insensitive."""
    text = (text or "").strip()
    if not text:
        return None
    index = prompt.find(text)
    if index < 0:
        index = prompt.lower().find(text.lower())
    return span(prompt, index, index + len(text)) if index >= 0 else None


def _sentence(prompt, start, end):
    """The clause around a match, bounded by sentence and line separators."""
    left, right = _sentence_bounds(prompt, start, end)
    return prompt[left:right]


def _sentence_bounds(prompt, start, end):
    left = max(prompt.rfind(c, 0, start) for c in ".;!?\n") + 1
    rights = [i for i in (prompt.find(c, end) for c in ".;!?\n") if i >= 0]
    return left, (min(rights) if rights else len(prompt))


def _normalized_text(text):
    text = unicodedata.normalize("NFKC", text).replace("−", "-").replace("µ", "μ")
    text = text.replace("⁻¹", "^-1").replace("²", "^2")
    return re.sub(r"\s+", " ", text).strip().lower()


def _inside(position, ranges):
    return any(s <= position < e for s, e in ranges)


# ------------------------------------------------------------------ boundaries (WIP reader functions)
# A boundary is a fact about the request's evidence, not a missing parser rule.
_DISCOVERY_DEMAND = re.compile(
    r"\bdiscover\w*\b[^.;\n]{0,80}\b(?:at|with|of)\s+(?:at\s+least\s+|≥\s*|>=\s*)?5\s*(?:sigma|σ)\b|"
    r"\b(?:claim|announce|declare)\s+(?:a\s+|the\s+)?(?:discovery|observation)\b", re.I)
_PRIVATE_DATA = re.compile(
    r"\b(?:private|internal|unpublished|non-?public|proprietary|collaboration[- ]internal|restricted)\s+"
    r"(?:[\w-]+\s+){0,3}?(?:data(?:sets?|bases?)?|samples?|ntuples?|results?|records?|n-?tuples?)\b|"
    r"\b(?:requires?|needs?)\s+(?:\w+\s+){0,2}?credentials\b", re.I)
_SIMULATION_ONLY = re.compile(r"\b(?:only|alone)\b[^.;\n]{0,60}\b(?:simulated|parton[- ]level|Monte\s+Carlo|MC)\b|"
                             r"\b(?:simulated|parton[- ]level|Monte\s+Carlo|MC)\b[^.;\n]{0,60}\b(?:only|alone)\b|"
                             r"\b(?:confirmed|proven?)\s+by\s+(?:the\s+)?(?:attached\s+|supplied\s+)?simulated\b", re.I)
_OBSERVED_CLAIM = re.compile(r"\bobserved\s+(?:\d+%\s+CL\s+)?(?:discovery\s+)?(?:significance|exclusion|limit|excess)\b|"
                             r"\bas\s+measured\s+in\s+data\b|\b(?:is|was|be)\s+confirmed\b|\bannounce\b", re.I)
_REAL_DATA = re.compile(r"\b(?:open\s+data|collision\s+data|recorded\s+data|observed\s+(?:data|counts|events))\b", re.I)
_SUPPLIED = re.compile(r"\b(?:supplied|attached|provided|enclosed|uploaded|I\s+have\s+access|we\s+have\s+access|"
                       r"(?:my|our)\s+(?:own\s+)?(?:private\s+)?(?:data|samples?|ntuples?))\b|"
                       r"(?:^|\s)(?:/|~/|\./)\S+", re.I)


_FULL_SIMULATION = re.compile(
    r"\bfull[- ]?sim(?:ulation)?\b|\bfull\s+(?:detector|Geant4|GEANT4?)(?:[- ]based)?\s+(?:detector\s+)?"
    r"sim(?:ulation)?\b|\bGeant4\s+full[- ]?sim(?:ulation)?\b", re.I)
# A mention that names consumed products of a full simulation, not a demand to run one.
_FULL_SIMULATION_PRODUCT = re.compile(
    r"\s*(?:-based\s+)?(?:efficienc\w*|acceptances?|maps?|tables?|results?|values?|numbers?|cut-?flows?|"
    r"templates?|response\s+(?:matrices|maps?))\b", re.I)
# Consumed products named just before the mention: "efficiencies obtained from full simulation".
_FULL_SIMULATION_SOURCE = re.compile(
    r"\b(?:efficienc\w*|acceptances?|maps?|tables?|results?|values?|numbers?|cut-?flows?|templates?|"
    r"response\s+(?:matrices|maps?))\s+(?:(?:obtained|derived|taken|extracted|computed|determined|produced)\s+)?"
    r"(?:from|with|using|by|in)\s+(?:(?:a|an|the)\s+)?$", re.I)
# A production predicate whose agent is the reference, never this request: a past passive
# ("were produced with") or a reference agent with a past active verb ("the collaboration used").
_REFERENCE_PRODUCTION = re.compile(
    r"\b(?:were|was|had\s+been|have\s+been|has\s+been)\s+(?:\w+\s+){0,2}?(?:produced|generated|simulated|"
    r"derived|obtained|made|processed|computed)\b|"
    r"\b(?:the|its|their)\s+(?:\w+\s+){0,2}?(?:analysis|analyses|experiment|collaboration|authors?|paper|"
    r"publication|study|reference)\s+(?:\w+\s+)?(?:derived|used|produced|generated|simulated|obtained|ran|"
    r"employed|relied|modell?ed|computed)\b|\b(?:derived|obtained|produced)\s+(?:its|their)\b", re.I)


def _segments(active, start, end):
    """The comma segments of the clause around [start, end): (before, own, after) text."""
    left = max(active.rfind(c, 0, start) for c in ".;!?\n") + 1
    rights = [i for i in (active.find(c, end) for c in ".;!?\n") if i >= 0]
    clause_end = min(rights) if rights else len(active)
    own_left = max(left, active.rfind(",", left, start) + 1)
    comma = active.find(",", end, clause_end)
    own_right = comma if comma >= 0 else clause_end
    return active[left:own_left], active[own_left:own_right], active[own_right:clause_end]


def full_simulation_demand(active):
    """The first mention demanding full detector simulation, or None.

    The decision is by role: who must simulate. A mention that names consumed products
    ("full-simulation efficiencies", "efficiencies obtained from full simulation") asks for
    nothing to run. A mention whose comma segment carries a production predicate with the
    reference as its agent ("which was obtained with full simulation", "the collaboration
    used full simulation") describes the reference; so does a leading participial phrase
    whose subject is such an agent ("Using full simulation, the published analysis derived
    its efficiencies"). Otherwise the request is the agent and the mention is a demand,
    whatever published result the same sentence names.
    """
    for m in _FULL_SIMULATION.finditer(active):
        if _FULL_SIMULATION_PRODUCT.match(active, m.end()):
            continue
        before, own, after = _segments(active, m.start(), m.end())
        if _FULL_SIMULATION_SOURCE.search(active[:m.start()][-120:]):
            continue
        if _REFERENCE_PRODUCTION.search(own):
            continue
        if not before.strip() and re.match(r"\s*(?:using|with|via|through)\b", own, re.I) \
                and _REFERENCE_PRODUCTION.search(after):
            continue
        return m
    return None


def boundaries(prompt, active):
    """Genuine boundaries: an observed claim the evidence cannot presuppose, or inaccessible data.

    `active` is the request with negated and quoted clauses removed, so "do not claim
    discovery" is a constraint, not a boundary.
    """
    from ravel.workflow import intake
    found = []
    # A demand to use full detector simulation, not a reference to published full-simulation
    # inputs; a named simulation tool is a requested_tool constraint, not this boundary.
    full_simulation = full_simulation_demand(active)
    if full_simulation:
        found.append({
            'kind': 'full-simulation',
            'statement': 'Full simulation of the detector is requested; the available fast response '
                         'does not supply that fidelity. This request is held and is never silently downgraded.',
            'would_make_possible': 'Supply an authorized full-simulation service and its qualified detector '
                                   'model, or explicitly approve a revised fast-response request.',
            'evidence': [s for s in [locate(prompt, full_simulation.group(0))] if s]})
    # The discovery boundary is narrow: the unchanged lexical
    # rule names a demand to claim or announce an observed discovery. An outcome-neutral request
    # ("discover ... and report its significance") stays a research question.
    if intake.requests_discovery(active):
        hit = _DISCOVERY_DEMAND.search(active) or re.search(r"\bdiscover\w*|\b5\s*(?:sigma|σ)", active, re.I)
        found.append({
            "kind": "observed-discovery-claim",
            "statement": "The request presupposes an observed discovery. A significance is a result of "
                         "accessible data and a validated background model; RAVEL does not presuppose it.",
            "would_make_possible": "Accessible observed data (open data or supplied samples) with a declared "
                                   "background model and test statistic. The request can then ask for the "
                                   "observed local and global significance, whatever value it takes; an "
                                   "expected (prospective) significance needs no observed data.",
            "evidence": [s for s in [locate(prompt, hit.group(0))] if s] if hit else []})
    simulated = _SIMULATION_ONLY.search(active)
    observed = _OBSERVED_CLAIM.search(active)
    if simulated and observed and not found and not _REAL_DATA.search(active):
        found.append({
            "kind": "observed-from-simulation",
            "statement": "The request asks for an observed result (a measurement, an observed limit or a "
                         "confirmation) from simulated or parton-level samples alone; simulation cannot give it.",
            "would_make_possible": "Observed data for the same selection, or restate the result as an expected "
                                   "(prospective) one computed from the simulated samples.",
            "evidence": [s for s in [locate(prompt, observed.group(0))] if s]})
    private = _PRIVATE_DATA.search(active)
    if private and not _SUPPLIED.search(active):
        found.append({
            "kind": "inaccessible-data",
            "statement": "The request depends on private experiment data that the request does not supply.",
            "would_make_possible": "Supply the data or a location the requester may use, or restate the "
                                   "question on public inputs: open data, HEPData records, published "
                                   "likelihoods or simulated samples.",
            "evidence": [s for s in [locate(prompt, private.group(0))] if s]})
    return found


def boundary_blocking(rows):
    return [f"boundary ({row['kind']}): {row['statement']} What would make it possible: "
            f"{row['would_make_possible']} Preserve the original question; do not replace it with an "
            f"exclusion or another quantity." for row in rows]


# ------------------------------------------------------------------ negated clauses
_NEGATION = re.compile(r"(?:\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not|shall\s+not|avoid|no\s+need\s+to)\b|"
                       r"\b(?:without|rather\s+than|instead\s+of)\b)[^.;!?\n]*", re.I)


def negations(prompt):
    """Negated clauses are explicit constraints of the request, retained verbatim."""
    rows = []
    for m in _NEGATION.finditer(prompt):
        text = m.group(0).strip().rstrip(",")
        if len(text) > 6:
            rows.append({"kind": "negation", "statement": text,
                         "evidence": [span(prompt, m.start(), m.start() + len(text))]})
    return rows


# ------------------------------------------------------------------ source restrictions
_SOURCE_CLASSES = (
    ("hepdata", r"\bHEPData\b"),
    ("paper", r"\b(?:paper|publication|article|preprint|arXiv|journal\s+version|auxiliary\s+material)s?\b"),
    ("figures", r"\b(?:figures?|plots?|curves?)\b"),
    ("tables", r"\btables?\b"),
    ("published-results", r"\b(?:published|reference|official|experimental|true|expected)\s+"
                          r"(?:results?|values?|yields?|numbers?|limits?|curves?|distributions?|cut-?flows?|answers?)\b|"
                          r"\bthe\s+answer\b"),
)
_USE = (r"(?:use|using|consult\w*|look(?:ing)?\s+(?:at|up)|read\w*|access\w*|download\w*|fetch\w*|open\w*|"
        r"copy\w*|take|taking|extract\w*|digiti[sz]\w*|transcrib\w*|tun(?:e|ing)\s+(?:to|against)|"
        r"compar\w*\s+(?:to|with|against)|peek\w*\s+at|rely\w*\s+on|refer\w*\s+to)")
_FORBID = re.compile(r"\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not|shall\s+not|may\s+not|cannot|can['’]t|avoid|"
                     r"without|no)\s+(?:\w+\s+){0,2}?" + _USE + r"\b[^.;!?\n]{0,160}", re.I)
_EXTRACTION = re.compile(r"\b(?:extract\w*|digiti[sz]\w*|transcrib\w*|copy\w*|take|taking|tun(?:e|ing))\b|"
                         r"\b(?:values?|numbers?|yields?)\b", re.I)
_BLINDED = re.compile(
    r"\bblind(?:ed)?\s+(?:prediction|study|test|evaluation|challenge|comparison|reproduction)\b|"
    r"\b(?:reference|published|true|expected|target)\s+(?:results?|values?|answers?|yields?|numbers?)\s+"
    r"(?:are|is|remain|will\s+be|stay)\s+(?:withheld|hidden|blinded|sealed|not\s+(?:available|provided|shown|given))\b|"
    r"\bwithout\s+(?:looking\s+at|seeing|access\s+to)\s+the\s+(?:published\s+|reference\s+)?"
    r"(?:results?|answers?|values?|paper)\b", re.I)
_BLINDED_DATA = re.compile(r"\b(?:blinded|blind)\s+(?:signal\s+regions?|data|SRs?)\b|\bunblind\w*\b|"
                           r"\b(?:keep|leave|remain|stay)s?\s+(?:the\s+)?(?:signal\s+regions?|SRs?|data)\s+blind(?:ed)?\b|"
                           r"\bsignal\s+regions?\s+(?:are|is|remain)\s+blind(?:ed)?\b", re.I)
_BLINDED_SEARCH = re.compile(r"\bblind(?:ed)?\s+(?:search|analysis|selection)\b", re.I)


def _identifiers(text):
    from ravel.workflow.route_prompt import ANACODE_RE, ARXIV_RE, HEPDATA_RE, INSPIRE_RE, RIVET_RE
    ids = {"arxiv": ARXIV_RE.findall(text),
           "inspire": [m.group(1) for m in INSPIRE_RE.finditer(text)],
           "hepdata": [m.group(1) or m.group(2) for m in HEPDATA_RE.finditer(text)],
           "analysis": [m.group(1).upper().replace(" ", "-") for m in ANACODE_RE.finditer(text)]}
    for m in RIVET_RE.finditer(text):
        ids["analysis"].append(m.group(1).upper())
        ids["inspire"].append(m.group(2))
    return {k: sorted(set(v)) for k, v in ids.items() if v}


def source_restrictions(prompt):
    """Request-declared forbidden sources, value-extraction bans and blinding, with evidence."""
    rows = []
    for m in _FORBID.finditer(prompt):
        clause = m.group(0)
        classes = [name for name, rx in _SOURCE_CLASSES if re.search(rx, clause, re.I)]
        identifiers = _identifiers(clause)
        if not classes and not identifiers:
            continue
        kind = "no-value-extraction" if _EXTRACTION.search(clause) else "forbidden-source"
        rows.append({"kind": kind, "classes": classes, "identifiers": identifiers,
                     "statement": clause.strip(), "evidence": [span(prompt, m.start(), m.end())]})
    for m in _BLINDED.finditer(prompt):
        rows.append({"kind": "blinded", "classes": ["published-results", "hepdata", "figures", "tables"],
                     "identifiers": _identifiers(_sentence(prompt, m.start(), m.end())),
                     "statement": m.group(0).strip(), "evidence": [span(prompt, m.start(), m.end())]})
    for rx in (_BLINDED_DATA, _BLINDED_SEARCH):
        for m in rx.finditer(prompt):
            rows.append({"kind": "blinded-data", "classes": [], "identifiers": {},
                         "statement": m.group(0).strip(), "evidence": [span(prompt, m.start(), m.end())]})
    return rows


# ------------------------------------------------------------------ requested stages
# Canonical order of a staged collider study. A request may name any subset.
STAGES = (
    ("model-derivation", r"\bFeynRules\b|\bSARAH\b|\bLanHEP\b|\bLagrangian\b|"
                         r"\bderiv\w*\s+(?:the\s+)?(?:Feynman\s+rules|model|vertices|couplings)\b|"
                         r"\b(?:build|write|create|implement|construct|author)\w*\s+(?:a\s+|an\s+|the\s+)?"
                         r"(?:[\w-]+\s+){0,3}?(?:model|UFO)\b"),
    ("spectrum", r"\bSPheno\b|\bSoftSUSY\b|\bFlexibleSUSY\b|\bSuSpect\b|\bspectrum\s+(?:calculat\w*|generat\w*|solver)\b|"
                 r"\b(?:decay\s+(?:widths?|tables?)|branching\s+(?:ratios?|fractions?))\b"),
    ("generation", r"\bMadGraph\w*\b|\bMG5(?:_aMC)?\b|\baMC@NLO\b|\bSherpa\b|\bPowheg\b|\bPOWHEG\b|\bWhizard\b|"
                   r"\bCalcHEP\b|\bCompHEP\b|\bMadSpin\b|\bmatrix[- ]elements?\b|\bevent\s+generation\b|"
                   r"\b(?:generate|simulate|produce)\b[^.;\n]{0,60}?\bevents?\b|\bgenerat(?:e|es|ed|ing)\b"),
    ("lhe-transform", r"\bLHE\b[^.;\n]{0,60}?\b(?:transform\w*|reweight\w*|boost\w*|convert\w*|filter\w*|rescal\w*|modif\w*)\b|"
                      r"\b(?:transform\w*|reweight\w*|convert\w*|filter\w*|rescal\w*)\b[^.;\n]{0,60}?\bLHE\b|\breweight\w*\b"),
    ("shower", r"\bshower\w*\b|\bhadroni[sz]\w*\b|\bPythia\s*\d*\b|\bHerwig\w*\b|\bVincia\b|\bMLM\b|\bCKKW\w*\b|"
               r"\bjet\s+matching\b|\bmerging\b"),
    ("detector", r"\bDelphes\b|\bdetector\s+(?:simulation|response|level|effects?|smearing|card)\b|\bfast[- ]?sim\w*\b|"
                 r"\bsmear\w*\b|\bGeant\s*4?\b|\bfull\s+simulation\b|\breconstruct\w*[- ]level\b"),
    ("analysis", r"\bRivet\b|\bSimpleAnalysis\b|\bMadAnalysis\s*5?\b|\bMA5\b|\bCheckMATE\b|\bcut[- ]?flows?\b|"
                 r"\bsignal\s+regions?\b|\b(?:event\s+)?selections?\b|\bacceptance\b|\banalysis\s+(?:routine|code|cuts)\b|"
                 r"(?-i:\b(?:ATLAS|CMS|LHCB|ALICE)_\d{4}_[IS]\d{4,8}\b)"),
    ("statistic", r"\bpyhf\b|\bHistFactory\b|\bRooFit\b|\bRooStats\b|\blikelihoods?\b|\bCLs\b|\bupper\s+limits?\b|"
                  r"\bexclusion\b|\bexclud\w+\b|\bsignificance\b|\bp[- ]?values?\b|χ\s*²|\bchi[- ]?(?:2|squared)\b|Δ\s*χ|"
                  r"\bcredib\w+\b|\bconfidence\s+(?:levels?|intervals?|regions?)\b|\bS\s*/\s*(?:sqrt|√)"),
    ("figure", r"\b(?:plot|draw|overlay|render|visuali[sz]e|histogram)\w*\b|\b(?:make|produce|show|give)\s+(?:\w+\s+){0,3}?"
               r"(?:figures?|distributions?|spectra|spectrum|curves?|contours?)\b"),
    ("output-template", r"\btemplates?\b|\bYAML\b|\.ya?ml\b|\bresults?\s+file\b|\bsubmission\s+format\b|"
                        r"\bHEPData[- ]format\w*\b|\bfill\s+(?:in\s+)?(?:the\s+)?(?:table|template|form)\b"),
)
_STAGE_RES = tuple((name, re.compile(rx, re.I)) for name, rx in STAGES)
_STAGE_NEGATED = re.compile(r"\b(?:no|without|skip(?:ping)?|omit(?:ting)?|not|never|excluding)\s+(?:[\w-]+\s+){0,3}$", re.I)
# Workflow lifecycle routes that serve a stage outside the science-mode catalogue.
STAGE_WORKFLOW_ROUTES = {
    "detector": ["analysis intake detector_mode simpleanalysis-delphes-native (registered native analyses)",
                 "analysis intake detector_mode delphes-custom-uncertified (labelled proxy without a routine)",
                 "analysis intake detector_mode rivet-smearing"],
    "statistic": ["ravel.physics.pyhf_exclude (published likelihood or counting model)"],
    "figure": ["docs/workflow/checklists/plot-criteria.md renderers"],
    "output-template": ["ravel fill-template (supplied result templates)"],
}
# A stated level negates the stages beyond it.
_LEVEL_RE = re.compile(r"\b(parton|particle|truth|generator)[- ]level\b|\bno\s+detector\b", re.I)


def stages(prompt, *, by_mode=None, candidates=True):
    """Requested stages in canonical order, each with evidence and (optionally) candidate routes."""
    rows = []
    if candidates:
        from ravel.workflow import capability_routing
        by_mode = capability_routing.declared_descriptors() if by_mode is None else by_mode
    for name, rx in _STAGE_RES:
        hits = list(rx.finditer(prompt))
        if not hits:
            continue
        negated = all(_STAGE_NEGATED.search(prompt[max(0, m.start() - 40):m.start()]) for m in hits)
        first = next((m for m in hits if not _STAGE_NEGATED.search(prompt[max(0, m.start() - 40):m.start()])), hits[0])
        row = {"stage": name, "negated": bool(negated), "evidence": [span(prompt, first.start(), first.end())],
               "workflow_routes": list(STAGE_WORKFLOW_ROUTES.get(name, ()))}
        if candidates:
            clause = _sentence(prompt, first.start(), first.end())
            row["candidate_modes"] = [r["mode"] for r in capability_routing.suggest(clause, by_mode)][:4]
        rows.append(row)
    return rows


# ------------------------------------------------------------------ requester-declared inputs
_NUMBER = r"\d+(?:\.\d+)?(?:\s*[×x*]\s*10\^?-?\d+|e-?\d+)?"
REQUESTER_INPUTS = (
    ("efficiency", r"\b(?:efficienc(?:y|ies)|ε|eps(?:ilon)?|acceptance(?:\s*(?:×|x|times)\s*efficiency)?)\s*"
                   r"(?:=|:|of|is|at)\s*" + _NUMBER + r"\s*%?"),
    ("k-factor", r"\b[kK][- ]?factors?\s*(?:=|:|of|is)?\s*" + _NUMBER + r"|\bK\s*=\s*" + _NUMBER),
    ("cross-section", r"\b(?:cross[- ]sections?|σ)\s*(?:=|:|of|is)\s*" + _NUMBER + r"\s*(?:[afpnµum]?b)\b"),
    ("branching-ratio", r"\b(?:branching\s+(?:ratios?|fractions?)|BR)\s*(?:=|:|of|is)\s*" + _NUMBER + r"\s*%?"),
    ("binning", r"\b(?:bins?|bin\s+edges|binning)\b[^.;\n]{0,40}?\b(?:from|of|as\s+in|in)\s+(?:Table|Fig(?:ure)?\.?|"
                r"the\s+(?:paper|HEPData\s+record|template))[^.;,\n]{0,20}|\bbin\s+edges?\s*(?:=|:)?\s*\[[^\]]{1,160}\]"),
    ("pdf-or-scheme", r"\b(?:NNPDF\w*|CT1\d\w*|MSHT\w*|PDF4LHC\w*|cteq\w*|LHAPDF)\b|\bPDF\s+set\b[^.;,\n]{0,30}|"
                      r"\b[45][- ]?flavou?r\s+scheme\b"),
    ("order", r"\b(?:N{1,3}LO|LO)(?:\s*\+\s*N{0,3}LL)?(?:\s+(?:QCD|EW|accuracy|precision))?\b"),
    ("scale", r"\b(?:renormali[sz]ation|factori[sz]ation)\s+scales?\b[^.;\n]{0,40}"),
)
_REQUESTER_RES = tuple((name, re.compile(rx)) for name, rx in REQUESTER_INPUTS)


def requester_inputs(prompt):
    rows = []
    for name, rx in _REQUESTER_RES:
        for m in rx.finditer(prompt):
            rows.append({"kind": name, "statement": m.group(0).strip(),
                         "evidence": [span(prompt, m.start(), m.start() + len(m.group(0).rstrip()))]})
    rows.sort(key=lambda r: r["evidence"][0]["start"])
    return rows


# ------------------------------------------------------------------ request shapes
# A prediction of binned signal yields is a deliverable (a `prediction` claim plus a template
# obligation), never a statistic mode of its own.
SIGNAL_YIELD_RE = re.compile(
    r"\b(?:predict|estimate|compute|calculate|derive|determine|give|provide|report|obtain|fill|produce)\w*\b"
    r"[^.;\n]{0,80}?\b(?:(?:expected\s+|predicted\s+)?signal\s+(?:yields?|event\s+counts?|counts?|events)|"
    r"numbers?\s+of\s+(?:expected\s+|selected\s+)?signal\s+events|"
    r"acceptance(?:\s*(?:×|x|times|and)\s*efficienc(?:y|ies))?|A\s*[×x]\s*ε|cut[- ]?flows?|"
    r"(?:binned\s+|per[- ]bin\s+)?(?:event\s+)?yields?)\b", re.I)
_YIELD_CONTEXT = re.compile(r"\bsignal\s+regions?\b|\bSRs?\b|\bbins?\b|\bselection\b|\banalysis\b|\bsearch\b|"
                            r"\bcategor(?:y|ies)\b|\bchannels?\b|\bcut-?flow", re.I)


def signal_yield_request(text):
    """A prediction of the binned signal yields or acceptance of an analysis at a model point."""
    m = SIGNAL_YIELD_RE.search(text)
    return bool(m and _YIELD_CONTEXT.search(text))


_RECO_SAMPLES = re.compile(r"\bPHYSLITE\b|\bDAOD\w*\b|\bNanoAOD\b|\bMiniAOD\b|\bn-?tuples?\b|"
                           r"\breconstructed\s+(?:\w+\s+){0,2}(?:samples?|events?|data)\b|"
                           r"\b(?:supplied|provided|given|attached|our|my)\s+(?:\w+\s+){0,5}?(?:MC|Monte\s+Carlo|samples?|data\s*sets?|ROOT\s+files?)\b|"
                           # The supplier may follow the noun: "the samples we supply", "the samples provided".
                           r"\b(?:samples?|data\s*sets?)\s+(?:that\s+)?(?:(?:we|I)\s+(?:have\s+)?(?:suppl(?:y|ied)|provided?|attach(?:ed)?)|"
                           r"(?:supplied|provided|attached)\b(?!\s+by\s+the\s+(?:paper|publication|collaboration)))|"
                           r"\bROOT\s+files?\b", re.I)
_NEW_SEARCH = re.compile(r"\b(?:design|develop|perform|carry\s+out|conduct|build|optimi[sz]e|construct|set\s+up|run)\b"
                         r"[^.;\n]{0,80}?\b(?:new\s+|dedicated\s+|blinded\s+|blind\s+)?(?:search|analysis)\b", re.I)


def supplied_sample_search(text):
    """A complete new search on supplied reconstructed samples (not a reinterpretation)."""
    return bool(_NEW_SEARCH.search(text) and _RECO_SAMPLES.search(text)
                and not re.search(r"\b(?:reinterpret|recast|reproduc)\w*", text, re.I))


# ------------------------------------------------------------------ witness extraction
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?(?:[eE][+\-−]?\d+)?"
_ENERGY = r"(?:keV|MeV|GeV|TeV|PeV)"
_UNIT_FAMILIES = (
    ("energy_squared", _ENERGY + r"(?:\s*\^\s*2|²)"),
    ("luminosity", r"(?:ab|fb|pb|nb)\s*(?:\^\s*\{?\s*[-−]\s*1\s*\}?|⁻¹|-1)|/(?:ab|fb|pb|nb)\b|(?:ab|fb|pb)-1"),
    ("energy", _ENERGY + r"\b"),
    ("cross_section", r"(?:ab|fb|pb|nb|mb|μb|µb)\b"),
    ("data_volume", r"(?:kB|MB|GB|TB|PB)\b"),
    ("time", r"(?:CPU[- ]?hours?|core[- ]?hours?|GPU[- ]?hours?|hours?|hrs?|days?|minutes?|mins?|ns|ps)\b"),
    ("length", r"(?:Mpc/h|Mpc|kpc|km|mm|cm|μm|µm|um|nm|m)\b"),
)
_UNIT = "|".join(f"(?:{rx})" for _, rx in _UNIT_FAMILIES)
_UNIT_RES = tuple((name, re.compile(r"^(?:" + rx + r")$", re.I)) for name, rx in _UNIT_FAMILIES)
_GEV = {"kev": 1e-6, "mev": 1e-3, "gev": 1.0, "tev": 1e3, "pev": 1e6}
_QUANTITY_RE = re.compile(r"(?<![\w.^\-−⁻/])(?P<n>" + _NUM + r")\s*(?P<u>" + _UNIT + r")", re.I)
_PERCENT_RE = re.compile(r"(?<![\w.])(?P<n>" + _NUM + r")\s*%")
_BOUND_RE = re.compile(r'\b(?P<parameter>mass|coupling|width|lifetime|coefficient)\s+(?:bound\s+)?'
                       r'(?P<direction>below|above|less\s+than|greater\s+than|at\s+most|at\s+least)\s+'
                       r'(?P<n>' + _NUM + r')\s*(?P<u>' + _UNIT + r')?', re.I)
_RANGE_RE = re.compile(
    r"(?:(?P<kw>from|between)\s+)?(?P<lo>" + _NUM + r")\s*(?P<lu>" + _UNIT + r")?\s*"
    r"(?P<sep>to|and|–|—|-)\s*(?P<hi>" + _NUM + r")\s*(?P<hu>" + _UNIT + r")", re.I)
_INEQUALITY_RE = re.compile(
    r"(?P<lo>" + _NUM + r")\s*(?P<lu>" + _UNIT + r")?\s*(?:<|≤|<=)\s*(?P<var>[^<≤\n]{1,20}?)\s*(?:<|≤|<=)\s*"
    r"(?P<hi>" + _NUM + r")\s*(?P<hu>" + _UNIT + r")?", re.I)
_UNITLESS_RANGE_RE = re.compile(r"(?:(?P<kw>from|between)\s+)?(?P<lo>" + _NUM + r")\s+(?P<sep>to|and)\s+"
                                r"(?P<hi>" + _NUM + r")(?!\s*(?:" + _UNIT + r"|%))", re.I)
_PARAMETER_NOUN = re.compile(r"\b(?:couplings?|mixing|angles?|ratios?|tan\s*β|tan\s*beta|lifetimes?|cτ|ctau|"
                             r"widths?|fractions?|ε|epsilon|g_?\w*|λ|lambda|κ\w*|kappa\w*|values?)\s*"
                             r"(?:\([^)]{0,20}\)\s*)?(?:from|between|in\s+the\s+range|of)?\s*$", re.I)
_STEP_RE = re.compile(r"^\s*,?\s*(?:in\s+(?:steps?\s+of\s+)?(?P<a>" + _NUM + r")\s*(?P<au>" + _UNIT + r")?\s*steps?\b|"
                      r"in\s+steps?\s+of\s+(?P<b>" + _NUM + r")\s*(?P<bu>" + _UNIT + r")?|"
                      r"(?:with\s+)?(?:a\s+)?steps?\s+(?:of|size\s+(?:of\s+)?)\s*(?P<c>" + _NUM + r")\s*(?P<cu>" + _UNIT + r")?|"
                      r"every\s+(?P<d>" + _NUM + r")\s*(?P<du>" + _UNIT + r")?)", re.I)
_LIST_RE = re.compile(r"(?<![\w.^\-−⁻])(?P<body>(?:" + _NUM + r")(?:\s*,\s*(?:" + _NUM + r"))*\s*,?\s*(?:and|or)\s+(?:"
                      + _NUM + r")|(?:" + _NUM + r")(?:\s*,\s*(?:" + _NUM + r")){2,})\s*(?P<u>" + _UNIT + r")", re.I)
_VALUE_UNCERTAINTY_RE = re.compile(r"(?P<c>" + _NUM + r")\s*(?:±|\+/-|\+-)\s*(?P<e>" + _NUM + r")\s*"
                                   r"(?P<u>" + _UNIT + r"|%)?", re.I)
_EVENT_COUNT_RE = re.compile(r"(?<![\w.])(?P<n>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s*[kKM]\b|\d+)\s+"
                             r"(?:[\w+\-~/'′.]+\s+){0,4}?events?\b")
_ORDER_RE = re.compile(r"\bN{1,3}LO(?:\s*\+\s*N{0,3}LL)?(?:\s+(?:QCD|EW|electroweak))?\b|(?-i:\bLO\b)(?:\s+(?:QCD|EW))?|"
                       r"\btree[- ]level\b|\b(?:one|two|three|1|2|3)[- ]loops?\b|\bleading[- ]order\b|"
                       r"\bnext-to-(?:next-to-)?leading[- ]order\b|\blinear\s+order\b|\bquadratic\s+order\b", re.I)
_PDF_RE = re.compile(r"\bNNPDF\s?\d(?:\.\d)?\w*|\bCT1[48]\w*|\bMSHT\d*\w*|\bPDF4LHC\d*\w*|\bCTEQ\w*|\bHERAPDF[\d.]*\w*|"
                     r"\b(?:lepton|photon|electron|muon)\s+PDFs?\b|\b[45][- ]?flavou?r\s+scheme\b", re.I)
_ASSIGNMENT_RE = re.compile(
    r"(?<![\w.])(?P<sym>[A-Za-zα-ωΑ-Ω][\w'′~^{}\-]{0,24}(?:\([^()\s]{1,12}\))?)\s*(?:=|≈)\s*"
    r"(?P<val>[+\-−]?(?:\d+(?:\.\d+)?(?:[eE][+\-−]?\d+)?|[A-Za-z]\w*(?:\^\d+)?\([^()]{1,20}\)))"
    r"(?!\d|\.\d|\s*(?:" + _UNIT + r"|%))", re.I)
TOOLS = (
    ("MadGraph5_aMC@NLO", r"MadGraph5?_aMC@NLO|MG5_aMC@NLO"), ("MadGraph", r"MadGraph5?|MG5(?:_aMC)?"),
    ("aMC@NLO", r"aMC@NLO"), ("Pythia", r"Pythia(?:\s*8(?:\.\d+)?)?"), ("Herwig", r"Herwig(?:\s*7)?"),
    ("Sherpa", r"Sherpa"), ("Powheg", r"POWHEG(?:[- ]BOX)?|Powheg(?:[- ]Box)?"), ("Whizard", r"Whizard"),
    ("CalcHEP", r"CalcHEP"), ("CompHEP", r"CompHEP"), ("MadSpin", r"MadSpin"), ("Delphes", r"Delphes"),
    ("Geant4", r"Geant\s*4"), ("wilson", r"(?-i:wilson)"), ("Rivet", r"Rivet"), ("SimpleAnalysis", r"SimpleAnalysis"),
    ("MadAnalysis5", r"MadAnalysis\s*5?|MA5"), ("CheckMATE", r"CheckMATE"), ("SModelS", r"SModelS"),
    ("Contur", r"Contur"), ("pyhf", r"pyhf"), ("HistFactory", r"HistFactory"), ("RooFit", r"RooFit"),
    ("RooStats", r"RooStats"), ("CAMB", r"(?-i:CAMB)"), ("CLASS", r"(?-i:CLASS)"), ("Cobaya", r"Cobaya"),
    ("MontePython", r"MontePython"), ("flavio", r"flavio"), ("HEPfit", r"HEPfit"), ("smelli", r"smelli"),
    ("FeynRules", r"FeynRules"), ("SARAH", r"(?-i:SARAH)"), ("SPheno", r"SPheno"), ("SoftSUSY", r"SoftSUSY"),
    ("FlexibleSUSY", r"FlexibleSUSY"), ("SuSpect", r"SuSpect"), ("FeynArts", r"FeynArts"),
    ("FeynCalc", r"FeynCalc"), ("FormCalc", r"FormCalc"), ("pySecDec", r"pySecDec"), ("MCFM", r"MCFM"),
    ("XGBoost", r"XGBoost"), ("micrOMEGAs", r"micrOMEGAs"), ("MadDM", r"MadDM"), ("DarkSUSY", r"DarkSUSY"),
    ("HiggsBounds", r"HiggsBounds"), ("HiggsSignals", r"HiggsSignals"), ("HiggsTools", r"HiggsTools"),
    ("Lilith", r"Lilith"), ("Nyx", r"(?-i:Nyx)"), ("LHAPDF", r"LHAPDF"), ("EasyScan", r"EasyScan"),
    ("FastJet", r"FastJet"), ("coffea", r"coffea"), ("TensorFlow", r"TensorFlow"), ("PyTorch", r"PyTorch"),
)
def _census_tool_patterns():
    """Extend the reading floor from packaged bytes without loading a catalogue."""
    from ravel.workflow.tool_census import census_bytes

    def normalized(name):
        return re.sub(r"[\s_-]", "", name).lower()

    seen = {normalized(name) for name, _ in TOOLS}
    patterns = []
    try:
        rows = json.loads(census_bytes())["tools"]
        for row in rows:
            names = row.get("request_names", [])
            fallback = next((n for n in names if not n.startswith("re:")),
                            re.split(r"[\s(]", row["title"], maxsplit=1)[0])
            for entry in names:
                if entry.startswith("re:"):
                    rx = entry[3:]
                    # A scoped case flag changes matching, not a literal tool's identity.
                    identity = rx[5:-1] if rx.startswith("(?-i:") and rx.endswith(")") else rx
                    name = fallback
                else:
                    identity = name = entry
                    rx = re.escape(entry)
                    if entry.isupper():
                        rx = "(?-i:" + rx + ")"
                key = normalized(identity)
                if key not in seen:
                    patterns.append((name, re.compile(r"(?<![\w@])(?:" + rx + r")(?![\w@])", re.I)))
                    seen.add(key)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError, re.error):
        return ()
    return tuple(patterns)


_TOOL_RES = (tuple((name, re.compile(r"(?<![\w@])(?:" + rx + r")(?![\w@])", re.I)) for name, rx in TOOLS)
             + _census_tool_patterns())
_FILE_TOKEN_RE = re.compile(r"[^\s()\[\]{}<>,;\"'`]*\w/[^\s()\[\]{}<>,;\"'`]*|(?<![\w/])[\w+-]+(?:\.[A-Za-z]\w{0,7})+\b")
_FILE_SUFFIX = re.compile(r"\.(?:hepmc\d?|lhe|lhef|root|json|ya?ml|slha|dat|csv|cc|cpp|py|pdf|onnx|yoda|txt|tex|"
                          r"tar|tgz|gz|h5|hdf5|parquet|npz|npy|ufo|zip)$", re.I)
EXPERIMENTS = r"ATLAS|CMS|LHCb|ALICE|Belle\s*II|BaBar|BESIII|NA62|NA64|LHCf|FASER|SHiP|MATHUSLA|IceCube|KM3NeT|" \
              r"Planck|LZ|XENONnT|PandaX(?:-4T)?|DarkSide|SuperCDMS|CMB-S4|LiteBIRD|LISA|DUNE|Hyper-?K|" \
              r"T2K|NOvA|LEP|Tevatron|CDF|D0|HERA|H1|ZEUS|KLOE|CLEO|Fermi-LAT|AMS-02|HESS|CTA"
_EXPERIMENT_RE = re.compile(r"(?<![\w-])(?:" + EXPERIMENTS + r")(?![\w-])")
_BEAMS = ((r"\bmuon\s+collider\b|μ\s*\+\s*μ\s*-\s*collider|\bmu\+\s*mu-\s+collider", "mu+mu-"),
          (r"\be\s*\+\s*e\s*-\s*collider\b|\belectron[- ]positron\s+collider\b|\bFCC-ee\b|\bCEPC\b|\bILC\b|\bCLIC\b",
           "e+e-"),
          (r"\bep\s+collider\b|\bLHeC\b|\bEIC\b", "ep"),
          (r"\b(?:HL-?LHC|LHC|FCC-hh|SPPC)\b|\bproton[- ]proton\b|\bpp\s+collisions?\b", "pp"))
_BEAM_RES = tuple((re.compile(rx, re.I), beams) for rx, beams in _BEAMS)
_COLLIDER_RIGHT = re.compile(r"^\s*(?:[\w+\-]+\s+){0,3}?(?:collider|collisions?|LHC|machine|beams?|run\b|data(?:set)?s?\b|"
                             r"pp\b|e\+e-|ntuples?|samples?|centre|center|c\.o\.m)", re.I)
_MASS_LEFT = re.compile(r"\bmass(?:es)?\b[^.;\n]{0,12}$|\bm_?\{?[\w']{0,8}\}?\s*[=≈~]\s*$|\bM\s*[=≈~]\s*$", re.I)
_WINDOW_LEFT = re.compile(r"(?:plot\w*|distribution|histogram\w*|spectrum|window|invariant\s+mass|\bbins?\b|"
                          r"mass\s+range|range\s+of\s+the\s+(?:plot|histogram))[^.;\n]{0,40}$", re.I)
_LUMI_UNIT = re.compile(_UNIT_FAMILIES[1][1], re.I)


def _unit_family(unit):
    unit = (unit or "").strip()
    for name, rx in _UNIT_RES:
        if rx.match(unit):
            return name
    return None


def _number(text):
    text = text.replace(",", "").replace("−", "-").strip()
    if text[-1:] in "kK":
        return float(text[:-1]) * 1e3
    if text[-1:] == "M":
        return float(text[:-1]) * 1e6
    return float(text)


def _gev(value, unit):
    return value * _GEV[unit.lower()] if unit and unit.lower() in _GEV else None


def _quantity_value(text, number, unit):
    value = _number(number)
    out = {"text": text, "value": value, "unit": unit}
    family = _unit_family(unit)
    if family == "energy":
        out["gev"] = _gev(value, unit)
    return out, family


def _file_tokens(prompt):
    for m in _FILE_TOKEN_RE.finditer(prompt):
        raw = m.group(0)
        token = raw.rstrip(".,;:!?")
        if not token or not re.search(r"[A-Za-z]", token):
            continue
        located = (token.startswith(("/", "~/", "./", "../")) or token.count("/") >= 2
                   or bool(_FILE_SUFFIX.search(token))
                   or bool("/" in token and re.search(r"\b(?:in|from|at|under|into|directory|folder|dir|path|file|run)\s*$",
                                                      prompt[:m.start()], re.I)))
        if located and not re.fullmatch(r"[\w.]+\.(?:\d+|[A-Z]\w*)", token):
            yield m.start(), m.start() + len(token), token


def _witness_candidates(prompt):
    """(start, end, type, value) for every typed item in priority order; overlaps resolve to the first."""
    from ravel.workflow.route_prompt import ANACODE_RE, ARXIV_RE, HEPDATA_RE, INSPIRE_RE, RIVET_RE
    out = []
    from ravel.workflow.intake import publication_titles
    for start, end, title in publication_titles(prompt):
        out.append((start, end, 'publication_title', {'text': title, 'title': title}))
    for m in RIVET_RE.finditer(prompt):
        out.append((m.start(1), m.end(1), "identifier", {"text": m.group(1), "scheme": "routine", "id": m.group(1)}))
    for m in ANACODE_RE.finditer(prompt):
        out.append((m.start(1), m.end(1), "identifier",
                    {"text": m.group(1), "scheme": "analysis", "id": m.group(1).upper().replace(" ", "-")}))
    for m in HEPDATA_RE.finditer(prompt):
        out.append((m.start(), m.end(), "identifier", {"text": m.group(0), "scheme": "hepdata",
                                                       "id": m.group(1) or m.group(2)}))
    for m in INSPIRE_RE.finditer(prompt):
        out.append((m.start(), m.end(), "identifier", {"text": m.group(0), "scheme": "inspire", "id": m.group(1)}))
    for m in ARXIV_RE.finditer(prompt):
        out.append((m.start(1), m.end(1), "identifier", {"text": m.group(1), "scheme": "arxiv", "id": m.group(1)}))
    for name, rx in _TOOL_RES:
        for m in rx.finditer(prompt):
            out.append((m.start(), m.end(), "tool", {"text": m.group(0), "name": name}))
    for start, end, token in _file_tokens(prompt):
        out.append((start, end, "file", {"text": token, "path": token}))
    for m in _BOUND_RE.finditer(prompt):
        out.append((m.start(), m.end(), 'parameter_bound', {'text': m.group(0),
                    'parameter': m.group('parameter'), 'direction': m.group('direction'),
                    'value': _number(m.group('n')), 'unit': m.group('u')}))
    for m in _VALUE_UNCERTAINTY_RE.finditer(prompt):
        out.append((m.start(), m.end(), "value_uncertainty",
                    {"text": m.group(0).strip(), "central": _number(m.group("c")),
                     "uncertainty": _number(m.group("e")), "unit": m.group("u")}))
    for rx in (_INEQUALITY_RE, _RANGE_RE):
        for m in rx.finditer(prompt):
            sep = m.groupdict().get("sep")
            if sep and sep.lower() == "and" and (m.group("kw") or "").lower() != "between":
                continue
            unit = m.group("hu") or m.group("lu")
            if not unit and rx is _INEQUALITY_RE:
                continue
            end = m.end()
            step_m = _STEP_RE.match(prompt[end:])
            step = None
            if step_m:
                key = next(k for k in "abcd" if step_m.group(k))
                step = {"text": step_m.group(0).strip(" ,"), "value": _number(step_m.group(key)),
                        "unit": step_m.group(key + "u") or unit}
                end += len(step_m.group(0).rstrip())
            value = {"text": prompt[m.start():end], "low": _number(m.group("lo")), "high": _number(m.group("hi")),
                     "unit": unit, "low_unit": m.group("lu") or unit, "step": step}
            if m.groupdict().get("var"):
                value["variable"] = m.group("var").strip()
            out.append((m.start(), end, "range", value))
    for m in _UNITLESS_RANGE_RE.finditer(prompt):
        if (m.group("sep").lower() == "and" and (m.group("kw") or "").lower() != "between"):
            continue
        if not _PARAMETER_NOUN.search(prompt[max(0, m.start() - 40):m.start()]):
            continue
        end = m.end()
        step_m = _STEP_RE.match(prompt[end:])
        step = None
        if step_m:
            key = next(k for k in "abcd" if step_m.group(k))
            step = {"text": step_m.group(0).strip(" ,"), "value": _number(step_m.group(key)), "unit": step_m.group(key + "u")}
            end += len(step_m.group(0).rstrip())
        out.append((m.start(), end, "range", {"text": prompt[m.start():end], "low": _number(m.group("lo")),
                                              "high": _number(m.group("hi")), "unit": None, "low_unit": None,
                                              "step": step}))
    for m in _LIST_RE.finditer(prompt):
        values = [_number(n) for n in re.findall(_NUM, m.group("body"))]
        out.append((m.start(), m.end(), "list", {"text": m.group(0), "values": values, "unit": m.group("u")}))
    for m in _QUANTITY_RE.finditer(prompt):
        value, _ = _quantity_value(m.group(0), m.group("n"), m.group("u"))
        out.append((m.start(), m.end(), "quantity", value))
    for m in _PERCENT_RE.finditer(prompt):
        out.append((m.start(), m.end(), "percentage", {"text": m.group(0), "value": _number(m.group("n")), "unit": "%"}))
    for m in _EVENT_COUNT_RE.finditer(prompt):
        n = m.group("n").replace(" ", "")
        out.append((m.start(), m.end(), "event_count", {"text": m.group(0), "count": _number(n)}))
    for m in _ORDER_RE.finditer(prompt):
        out.append((m.start(), m.end(), "perturbative_order", {"text": m.group(0)}))
    for m in _PDF_RE.finditer(prompt):
        out.append((m.start(), m.end(), "pdf", {"text": m.group(0)}))
    for m in _ASSIGNMENT_RE.finditer(prompt):
        out.append((m.start(), m.end(), "assignment", {"text": m.group(0), "symbol": m.group("sym"),
                                                       "value": m.group("val")}))
    taken, kept = [], []
    for start, end, kind, value in out:
        if end <= start or any(s < end and start < e for s, e in taken):
            continue
        taken.append((start, end))
        kept.append((start, end, kind, value))
    return sorted(kept, key=lambda row: (row[0], row[1]))


# ------------------------------------------------------------------ active and context regions
_IDENTITY_KEY = r"(?:benchmark|suite|task|source|context|provenance)\s+(?:id|label|name)"
_IDENTITY_LINE = re.compile(r"^[ \t]*" + _IDENTITY_KEY + r"[ \t]*[:=][^\r\n]*", re.I | re.M)
_IDENTITY_WORDS = re.compile(r"\b(?:task|challenge|benchmark|submission|suite|competition|leaderboard)\b", re.I)
_ACTION_WORDS = re.compile(r"\b(?:reproduce|reinterpret|recast|scan|calculate|compute|evaluate|convert|simplify|fit|"
                           r"generate|simulate|investigate|explore|discover|claim|survey|design|develop|implement|"
                           r"construct|run|execute|deliver|report|estimate|measure|predict|plot|draw|write|train|"
                           r"compare|use|fill|make|produce|find|determine|derive|build|is|are|what|which|how)\b", re.I)


# "For Dr. Jane Smith's group." and similar attributions name people, not physics.
_ATTRIBUTION = re.compile(r"(?:(?<=^)|(?<=[.!?]\s)|(?<=\(\s)|(?<=\())(?:For|On\s+behalf\s+of|From)\s+"
                          r"(?:(?:Dr|Prof|Professor|Mr|Ms|Mrs)\.?\s+)?[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,3}"
                          r"(?:['’]s)?\s+(?:group|team|lab(?:oratory)?|collaboration|students?|class)\.?", re.M)
_TRAILING_PAREN = re.compile(r"\(\s*([^()\n]{3,160}?)\s*\)\s*$")


def _identity_text(text):
    return ((_IDENTITY_WORDS.search(text) or _ATTRIBUTION.fullmatch(text.strip()))
            and not _ACTION_WORDS.search(_ATTRIBUTION.sub(" ", text)))


def _identity_spans(prompt):
    """Context labels: `key: value` lines, a leading verbless sentence naming a task or challenge,
    an attribution to a person or group, and a trailing parenthetical label of either kind."""
    rows = [(m.start(), m.start() + len(m.group(0).rstrip())) for m in _IDENTITY_LINE.finditer(prompt)]

    def add(start, end):
        if not any(s <= start < e or start <= s < end for s, e in rows):
            rows.append((start, end))
    for m in _ATTRIBUTION.finditer(prompt):
        add(m.start(), m.end())
    lead = re.match(r"\s*([^.\n]{3,160}?[.:])(?=\s)", prompt)
    if lead and _IDENTITY_WORDS.search(lead.group(1)) and not _ACTION_WORDS.search(lead.group(1)):
        add(lead.start(1), lead.end(1))
    tail = _TRAILING_PAREN.search(prompt)
    if tail and _identity_text(tail.group(1)):
        add(tail.start(1), tail.end(1))
    return sorted(rows)


# Facts the witness pass has no unit for: operator and Wilson-coefficient names, couplings and
# stated tuples of values, spectral shapes, and an arXiv locator whose characters do not verify.
_EXTRA_FACTS = (
    (re.compile(r"(?<![\w.])(?:(?:Wilson\s+)?coefficients?|operators?)\s+((?:[A-Za-z]_?\{?[A-Za-z0-9]{1,6}\}?)"
                r"(?:\s*(?:,|and)\s*[A-Za-z]_?\{?[A-Za-z0-9]{1,6}\}?)*)"), "operator", False),
    (re.compile(r"(?<![\w.])(?P<sym>tan\s*(?:β|beta))\s*=\s*(?P<val>\d+(?:\.\d+)?)", re.I), "parameter_value", True),
    (re.compile(r"(?<![\w.])(?P<sym>couplings?)\s+(?:of\s+)?(?P<val>\d+(?:\.\d+)?)(?!\d|\.\d|\s*(?:GeV|TeV|MeV|%))", re.I),
     "parameter_value", True),
    (re.compile(r"(?<![\w\-/])(?:[cCO]_\{?[A-Za-z][A-Za-z0-9]{0,5}\}?|C(?:9|10|7)'?)(?![\w])"), "operator", False),
    (re.compile(r"\((?:\s*[+\-−]?\d+(?:\.\d+)?\s*,){1,15}\s*[+\-−]?\d+(?:\.\d+)?\s*\)"), "stated_values", True),
    (re.compile(r"(?<![\w])E\s*(?:\^\s*)?(?:[⁻\-−]\s*)?(?:[⁰¹²³⁴⁵⁶⁷⁸⁹]+|\{?-?\d+(?:\.\d+)?\}?)(?![\w])"), "spectral_shape", True),
    (re.compile(r"\barXiv:\s*(?!\d{4}\.\d{4,5}\b)[^\s,;()]{4,24}", re.I), "unverified_identifier", False),
)


def _inline_quotes(prompt):
    """Text inside double quotation marks: reported speech or a title, not a request of its own."""
    return [m.span() for m in re.finditer(r'"[^"\n]{1,200}"|“[^”\n]{1,200}”', prompt)]


def _quoted_spans(prompt):
    rows = [m.span() for m in re.finditer(r"```.*?```", prompt, re.S)]
    rows += [m.span() for m in re.finditer(r"^[ \t]*>.*$", prompt, re.M)]
    return rows


def _negated_spans(prompt):
    return [(row["evidence"][0]["start"], row["evidence"][0]["end"]) for row in negations(prompt)]


def _outside_identity(prompt):
    """The request outside its identity contexts as trimmed ``(start, end)`` runs.

    A fact about the whole request must not carry a context label in its value or evidence, so a
    label, and the brackets left around it, are left out; a run with no word character is dropped.
    A request with no identity context is one run: the whole request, untrimmed."""
    rows = _identity_spans(prompt)
    if not rows:
        return [(0, len(prompt))]
    runs, cursor = [], 0
    for index, (start, end) in enumerate(rows + [(len(prompt), len(prompt))]):
        text = prompt[cursor:start]
        if re.search(r"\w", text):
            lead = text if cursor == 0 else text.lstrip(" \t\r\n)]}\"'\u201d")
            lead = len(text) - len(lead)
            body = text.rstrip(" \t\r\n") if start == len(prompt) else text.rstrip(" \t\r\n([{\"'\u201c")
            runs.append((cursor + lead, cursor + len(body)))
        cursor = max(cursor, end)
    return runs


def neutral_text(prompt):
    """The request with identity contexts blanked, same length, so spans stay exact."""
    chars = list(prompt)
    from ravel.workflow.intake import publication_titles
    ranges = _identity_spans(prompt) + [(s, e) for s, e, _ in publication_titles(prompt)]
    for s, e in ranges:
        for i in range(s, e):
            if chars[i] not in "\r\n":
                chars[i] = " "
    return "".join(chars)


# ------------------------------------------------------------------ requester-supplied artifacts
# A phrase that hands the run an artifact ("the attached Delphes files", "my two pyhf workspaces",
# "Here are 500 SLHA files") becomes a `supplied_input` fact: {text, artifact, require}. The
# artifact is one of the closed kinds; `require` holds what the words state (level, format,
# observed data). A named file is read separately as a `supplied_file` fact.
_SUPPLIER = (r"\b(?:attached|supplied|provided|enclosed|uploaded|given|my|our|these|this|"
             r"the\s+(?:attached|supplied|provided|enclosed|uploaded|given)|[Hh]ere\s+(?:is|are)\s+(?:the\s+|my\s+|our\s+)?)")
_SUPPLIED_NOUNS = (
    ("event_sample", r"(?:HepMC|LHE|Delphes|ROOT|NanoAOD|MiniAOD|PHYSLITE|DAOD\w*)(?:\s+[\w+\-̄]+){0,3}?\s+(?:files?|samples?|"
                     r"n-?tuples?|events?|data(?:\s*sets?)?)\b|\b(?:NanoAOD|MiniAOD|PHYSLITE|DAOD\w*)\b|\bn-?tuples?\b|"
                     r"\b(?:data\s+)?control\s+samples?\b|\bsamples?\b|\bevents?\s+files?\b|\bdata\s*sets?\b"),
    ("statistical_model", r"\b(?:pyhf\s+|HistFactory\s+|HS3\s+)?(?:workspaces?|likelihoods?)\b"),
    ("parameter_point", r"\b(?:\w+\s+)?SLHA\s+(?:files?|benchmarks?|points?|cards?)\b|\bSLHA\b|\bbenchmarks?\b|"
                        r"\bparam(?:eter)?\s+cards?\b"),
    ("table", r"\bhistograms?\b|\bspectr(?:um|a)\b|\bresponse\s+matri(?:x|ces)\b|\bobserved\s+counts\b|\bcounts\b|"
              r"\byield\s+tables?\b"),
    ("selection", r"\bRivet\s+routines?\b|\broutines?\b|\b(?:ONNX\s+)?(?:b-)?taggers?\b|\bclassifiers?\b|"
                  r"\bselections?\b|\banalysis\s+code\b"),
    ("document", r"\bdrafts?\b|\brun\s+director(?:y|ies)\b|\b(?:finished|completed)\s+(?:\w+\s+){0,2}runs?\b|"
                 r"\b(?:scan|limit|recast)\s+runs?\b"),
    ("expression", r"\bLagrangians?\b"),
    ("model", r"\b(?:UFO|FeynRules)\s+models?\b|\bmodel\s+files?\b"),
)
# One expression: the nearest artifact noun after the supplier word wins (a lazy filler).
_SUPPLIED_RE = re.compile(_SUPPLIER + r"\s*(?:[^\s.;:,?!()]+\s+){0,8}?(?:"
                          + "|".join(f"(?P<k{i}>{rx})" for i, (_, rx) in enumerate(_SUPPLIED_NOUNS)) + ")", re.I)
_SIMULATED = re.compile(r"\b(?:simulated|simulation|MC|Monte\s+Carlo|Delphes|signal|parton[- ]level|LHE|HepMC|"
                        r"generated)\b", re.I)
_OBSERVED = re.compile(r"\b(?:Open\s+Data|observed|collision\s+data|data\s+control|recorded\s+data|data)\b", re.I)


def _supplied_require(kind, text):
    require = {}
    if kind == "event_sample":
        if re.search(r"\bLHE\b", text, re.I):
            require.update(format="lhe", level="parton")
        elif re.search(r"\bHepMC\b", text, re.I):
            require.update(format="hepmc", level="particle")
        elif re.search(r"\bDelphes\b", text, re.I):
            require.update(format="delphes-root", level="detector")
        elif re.search(r"\b(?:NanoAOD|MiniAOD|PHYSLITE|DAOD\w*|n-?tuples?|ROOT)\b", text, re.I):
            require.update(level="reconstructed")
        if re.search(r"\bparton[- ]level\b", text, re.I):
            require["level"] = "parton"
    if kind in ("event_sample", "table") and _OBSERVED.search(text) and not _SIMULATED.search(text):
        require["contains_observed_data"] = True
    if kind == "table" and re.search(r"\bobserved\b", text, re.I):
        require["observed"] = True
    return require


def supplied_inputs(prompt, active_at):
    """(start, end, artifact, require) for each phrase that hands the run an artifact, in request order."""
    rows = []
    for m in _SUPPLIED_RE.finditer(prompt):
        if not active_at(m.start()):
            continue
        kind = next(_SUPPLIED_NOUNS[i][0] for i in range(len(_SUPPLIED_NOUNS)) if m.group(f"k{i}") is not None)
        end = len(m.group(0).rstrip()) + m.start()
        rows.append((m.start(), end, kind, _supplied_require(kind, m.group(0))))
    return rows


# ------------------------------------------------------------------ the reader
def _sha(data):
    return hashlib.sha256(data).hexdigest()


def reader_pin():
    return {"module": READER_MODULE, "source_sha256": _sha(Path(__file__).read_bytes())}


def author(actor="deterministic-reader", *, host=None, model=None, invocation_id=None, fresh_context=None,
           record=None):
    return {"actor": actor, "host": host, "model": model, "invocation_id": invocation_id,
            "fresh_context": fresh_context, "record": record}


def digest(document_value):
    """Canonical hash of a reading or plan record (sorted keys, compact separators)."""
    raw = json.dumps(document_value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return _sha(raw.encode("utf-8"))


class _Builder:
    def __init__(self, prompt):
        self.prompt = prompt
        self.witness, self.facts, self.constraints = [], [], []
        self.deliverables, self.ambiguities, self.boundaries, self.dismissed = [], [], [], []

    def _next(self, rows, prefix):
        return f"{prefix}{len(rows) + 1}"

    def add_witness(self, kind, value, start, end):
        row = {"id": self._next(self.witness, "W"), "type": kind, "value": value, "span": span(self.prompt, start, end)}
        self.witness.append(row)
        return row

    def add_fact(self, kind, value, spans, *, authority="user_quoted", witness=None, critical=False):
        row = {"id": self._next(self.facts, "F"), "type": kind, "value": value, "evidence": spans[:16],
               "authority": authority, "witness": witness, "physics_critical": bool(critical)}
        self.facts.append(row)
        return row

    def add_constraint(self, kind, value, spans):
        row = {"id": self._next(self.constraints, "K"), "type": kind, "value": value, "evidence": spans[:16]}
        self.constraints.append(row)
        return row

    def add_ambiguity(self, issue, readings, spans, *, default=None, critical=True, blocks=(),
                      observable=True, reversible=True):
        row = {"id": self._next(self.ambiguities, "A"), "evidence": spans[:16], "issue": issue,
               "readings": readings, "default": default, "observable_impact": observable,
               "reversible": reversible, "physics_critical": critical, "blocks": list(blocks),
               "status": "open", "resolution": None}
        self.ambiguities.append(row)
        return row

    def add_boundary(self, klass, statement, would, spans, obligations=()):
        row = {"id": self._next(self.boundaries, "B"), "class": klass, "obligation_ids": list(obligations),
               "statement": statement, "would_make_possible": would, "evidence": spans[:16]}
        self.boundaries.append(row)
        return row


def _reading_row(identifier, value, authority, source=None):
    return {"id": identifier, "value": value, "authority": authority, "source": source}


def _content_free(active):
    tokens = re.findall(r"[A-Za-z0-9]+", active)
    stop = {"i", "we", "you", "me", "us", "please", "the", "a", "an", "and", "or", "want", "would", "like", "to",
            "it", "this", "that", "so", "just", "also", "then", "ok", "okay", "thanks", "thank", "hi", "hello"}
    return not [t for t in tokens if t.lower() not in stop]


def _classify_quantity(prompt, start, end, value, family, collision):
    """Fact type and criticality for a single quantity witness."""
    from ravel.workflow import route_prompt
    if family == "luminosity":
        return "luminosity", True
    if family == "cross_section":
        return "cross_section", True
    if family in ("time", "data_volume"):
        left = prompt[max(0, start - 30):start]
        if re.search(r"\b(?:within|budget|limit|at\s+most|up\s+to|no\s+more\s+than)\b[^.;\n]*$", left, re.I):
            return "budget", False
        return "quantity", True
    if family != "energy":
        return "quantity", True
    line_start = prompt.rfind("\n", 0, start) + 1
    line_end = prompt.find("\n", end)
    line_end = len(prompt) if line_end < 0 else line_end
    left = prompt[max(line_start, start - 40):start]
    right = prompt[end:line_end]
    gev = value.get("gev") or 0.0
    if _MASS_LEFT.search(left):
        return "mass", True
    if (_COLLIDER_RIGHT.match(right) or route_prompt.SQRT_S_LEFT_RE.search(left)
            or route_prompt._collision_energy(prompt, start, end, gev,
                                              prompt[max(line_start, start - 40):min(line_end, end + 40)])):
        return "collision_energy", True
    if route_prompt._mass_plausible(prompt, start, end, gev):
        if collision and abs(gev - collision) < 1e-9:
            return "collision_energy", True
        return "mass", True
    return "quantity", True


def _quantity_role(prompt, start):
    left = prompt[max(0, start - 40):start]
    m = re.search(r"(\bwidths?|Γ|\bGamma|\bsplittings?|mass\s+(?:difference|gap)s?|Δ\s*m|\bscale|\bcut-?off|Λ|"
                  r"\bLambda|\bvev|\bthresholds?|\bcuts?|\bp_?\{?T\}?|\bE_?\{?T\}?(?:\^?miss)?|\bMET|\bH_?T|"
                  r"\bbelow|\babove|\bunder|\bover|\bup\s+to|\bdecay\s+constant|\bf_?\{?a\}?)[^.;\n]{0,20}$", left, re.I)
    return re.sub(r"\s+", " ", m.group(1)).lower() if m else None


_STATED_INPUT_AFTER = re.compile(r"\s*(?:of|=|:|≈|is|was)\s*(?:about\s+|roughly\s+)?[(\d]", re.I)
_REFERENCE_BEFORE = re.compile(r"\b(?:published|measured|observed|HEPData|reference)\s+(?:[\w+\-]+\s+){0,2}$",
                               re.I)
_EXPECTED_WORDS = re.compile(r"\b(?:expected(?!\s+(?:number\s+of\s+)?(?:background|SM|Standard))|projected|projection|forecast\w*|prospect\w*|sensitiv\w*|reach|future|"
                             r"HL-LHC|would\s+(?:be|give|add)|Asimov)\b", re.I)
_OBSERVED_WORDS = re.compile(r"\b(?:observed|in\s+(?:the\s+)?data|we\s+see|recorded|measured\s+in|release|open\s+data|"
                             r"counts?\s+per\s+bin)\b", re.I)
_PUBLISHED_FIGURE = re.compile(r"\b(?:overla\w+\s+(?:them\s+|it\s+)?on\s+the\s+published\s+(?:contour|figure|plot|curve)|"
                               r"published\s+(?:contour|figure|plot|curve)s?)\b", re.I)
_PUBLISHED_VALUES = re.compile(r"\bpublished\s+(?:values?|results?|measurements?|cross[- ]sections?|tables?|"
                               r"(?:[\w-]+\s+){0,2}(?:cross\s+section|distribution|spectrum))\b|\bHEPData\s+record\b|"
                               r"\b(?:the\s+)?[\w+]+\s+average\b|\bquoted\s+uncertainty\b", re.I)


def _deliverable_cues(prompt, active_at):
    """(start, end, claim_kind, artifact_kind, require) cues of what the request asks to deliver."""
    from ravel.workflow.route_prompt import FIGURE_RE
    cues = []
    figure_verbs = re.compile(r"\b(?:reproduc\w*|redo|match\w*|compar\w*|overla\w*|validat\w*|recreat\w*|replicat\w*)\b",
                              re.I)
    for m in FIGURE_RE.finditer(prompt):
        sentence_start, sentence_end = _sentence_bounds(prompt, m.start(), m.end())
        if active_at(m.start()) and figure_verbs.search(prompt[sentence_start:sentence_end]):
            cues.append((m.start(), m.end(), "agreement", "figure", {"reference": m.group(0).strip()}, True))
    for m in re.finditer(r"\b(?:reproduc\w*|replicat\w*|recreat\w*|redo)\b[^.;\n]{0,120}?\b(?:contours?|curves?|plots?|"
                         r"distributions?|limits?|figures?|spectr\w+|results?)\b", prompt, re.I):
        if active_at(m.start()) and not any(c[5] for c in cues):
            cues.append((m.start(), m.end(), "agreement", "figure",
                         {"reference": "the published element named in the request"}, True))
    patterns = (
        ("exclusion", "inference", r"\bexclu(?:sion|ded|de|ding)\b|\bupper\s+limits?\b|\b(?:expected|observed)\s+limits?\b|"
                                   r"\blimits?\s+(?:on|across|for)\b|\brule[ds]?\s+out\b|\bcontours?\b|\bstill\s+allowed\b|"
                                   r"\bCLs\b|\b(?:give|report|set|compute|derive|quote)\s+(?:the\s+|a\s+)?(?:combined\s+|"
                                   r"expected\s+|observed\s+)?limits?\b|\breach\b|\brecast\b|\breinterpret(?:s|ed|ing)?\b"),
        ("significance", "inference", r"\bsignificance\b|\bdiscovery\s+(?:reach|sensitivity|potential)\b|\bp[- ]?values?\b|"
                                      r"\b(?:expected\s+)?sensitivity\b(?!\s+(?:to|of)\b)|\bhow\s+sensitive\b|"
                                      r"\b\d+(?:\.\d+)?\s*(?:σ|sigma)\s+discovery\b"),
        ("estimate", "inference", r"(?<![-/\w])fit\b|\bfits?\s+(?:to|the)\b|\bfitting\b|\bconstrain\w*\b|\bmeasure\b|"
                                  r"\bbest[- ]fit\b(?!\s+(?:\w+\s+)?(?:parameters?|values?|point))|"
                                  r"\bposterior\b|\bprecision\s+on\b|\btell\s+(?:us|me)\s+about\b|\bintervals?\b|"
                                  r"\bextract\w*\b|\bconsistent\s+explanation\b|\bhow\s+strongly\b|\bwhat\s+range\s+of\b|"
                                  r"\bcombined\s+value\b|\bcombine\b[^.;\n]{0,60}\bmeasurements?\b|\bbound\s+the\b|"
                                  r"\bforecast\w*\b|\bscale\s+factors?\b|\b(?:energy\s+)?resolution\b|"
                                  r"\bregion\s+compatible\b|\bcompatible\s+with\b|\bbe\s+explained\s+by\b|"
                                  r"\bhow\s+much\s+(?:does|do|would|will)\b[^.;\n?]{0,80}\bchange\b"),
        ("method_performance", "table", r"\b(?:train|develop|design|evaluate|benchmark|optimi[sz]e|study|propose|estimate)\w*\b"
                                        r"[^.;\n]{0,80}\b(?:tagger|classifier|network|method|algorithm|selection|"
                                        r"decision\s+trees?|BDT|flow|transformer|XGBoost|observable|inference)\b|"
                                        r"\bcompare\s+[\w-]+\s+and\s+(?:a\s+)?[\w-]+\s+for\b|\bAUC\b|\bROC\b|"
                                        r"\b(?:simulation-based|likelihood-free|neural)\s+inference\b"),
        ("agreement", "inference", r"\bagree\w*\b|\bconsisten(?:cy|t)\s+with\b|\bcompar\w+\b[^.;\n]{0,80}?\b(?:with|to|against)\b|"
                                   r"\bvalidate\b[^;\n]{0,60}\bagainst\b|\bcheck\s+every\s+number\b|\bmatches\b|"
                                   r"\bwithin\s+its\s+quoted\s+uncertainty\b"),
        ("finding", "table", r"\bwhich\s+(?:[\w-]+\s+){0,2}?(?:searches|analyses|experiments|measurements|results)\b|"
                             r"\bsummary\s+(?:plot|figure)\b|\bsummari[sz]e\b|\boverlay\w*\b|\bliterature\b|"
                             r"\bstrongest\s+(?:current\s+)?(?:limits?|constraints?)\b|\bstatus\s+of\b|\bimply\b|"
                             r"\blist\s+the\b|\bcollect\s+the\s+published\b|\btabulate\b|\bfind\s+the\s+papers\b|"
                             r"\bwhat\s+else\s+would\s+test\b|\bcould\b[^.;?]{0,80}\bbe\s+explained\b|"
                             r"\btheorem\b|\bbounded\s+from\s+below\b|\bcurrent\s+best\s+limits?\b"),
        ("prediction", "binned_values", r"\b(?:plot|histogram\w*|distributions?|spectrum|spectra|yields?|power\s+spectr\w+|"
                                        r"cross[- ]sections?|predict(?:s|ed|ing)?|backgrounds?|rates?)\b"),
        ("document", "document", r"\b(?:write|draft|prepare|compose|produce|turn)\b[^.;\n]{0,60}\b(?:paper|note|report|"
                                 r"manuscript|article|write-?up|letter|poster|section|slides)\b"),
        ("calculation", "scalar", r"\b(?:compute|calculate|evaluate|derive|solve|draw|work\s+out)\b|\bFeynman\s+diagrams?\b|"
                                  r"\bpartial\s+widths?\b|\bbranching\s+ratios?\b|\bRGEs?\b|\bshow\s+that\b|"
                                  r"\bcheck\s+whether\b|\bhow\s+many\s+events\b|\bwidths?\s+(?:into|to)\b|"
                                  r"\bfind\s+the\s+(?:shift|value|bound|scale|width|point)\b|\bunitarity\b|"
                                  r"\bmaster\s+integrals?\b|\brun\s+the\s+[^.;\n]{0,40}\bcoefficients\b"),
    )
    found = {}
    for claim, artifact, rx in patterns:
        for m in re.finditer(rx, prompt, re.I):
            if not active_at(m.start()):
                continue
            if claim == "prediction":
                # A quantity the request states ("a cross section of 1.2e-3 pb", "a background of 2.1") or
                # names as a reference ("the published distribution") is an input, not a deliverable.
                if (_STATED_INPUT_AFTER.match(prompt, m.end())
                        or _REFERENCE_BEFORE.search(prompt[max(0, m.start() - 60):m.start()])
                        and not re.match(r"(?:plot|histogram|predict)", m.group(0), re.I)
                        or re.search(r"\bmodel\s+the\s+(?:[\w-]+\s+)?$", prompt[max(0, m.start() - 40):m.start()],
                                     re.I) and m.group(0).lower().startswith("background")):
                    continue
            found.setdefault(claim, (m.start(), m.end(), claim, artifact, {}, False))
            break
    if "agreement" in found and any(c[5] for c in cues):
        # "Reproduce X and compare it with the published figure" is one comparison: the figure
        # cue already carries it, so the generic cue in the same sentence adds no second claim.
        start = found["agreement"][0]
        bounds = _sentence_bounds(prompt, start, found["agreement"][1])
        if any(c[5] and bounds[0] <= c[0] < bounds[1] for c in cues):
            found.pop("agreement")
    if "method_performance" in found:
        # The method's comparison and sensitivity are its performance metric, not separate claims.
        found.pop("agreement", None)
        if re.search(r"\bcompar\w*\s+(?:its|their|the)\s+sensitivit", prompt, re.I):
            found.pop("significance", None)
    if "calculation" in found and "prediction" in found:
        text = prompt[found["prediction"][0]:found["prediction"][1]].lower()
        # "compute the cross section" asks for a calculation of a scalar; a plot or a distribution
        # stays a prediction and the calculation verb only names how it is made.
        if re.match(r"cross|rate|predict", text) and not set(found) & {"exclusion", "estimate", "significance"}:
            found.pop("prediction")
        else:
            found.pop("calculation")
    if "calculation" in found and set(found) & {"exclusion", "estimate", "significance"}:
        found.pop("calculation")
    if 'document' in found:
        from ravel.workflow.intake import operation_kind
        if operation_kind(prompt) == 'manuscript':
            found = {'document': found['document']}
        else:
            found.pop('calculation', None)
    literature = "finding" in found and (re.search(
        r"\bfind\s+the\s+papers\b|\bliterature\b|\btabulate\b|\bcollect\s+the\s+published\b|\blist\s+the\b",
        prompt, re.I) or not re.search(
        r"\b(?:recast|reinterpret|reproduc\w*|redo|generate|simulate|train|run\s+(?:the|a)\b|fit\b)", prompt, re.I))
    if literature:
        # A question about published results asks for a finding; the limits and spectra it names are
        # what it reads, not what it computes.
        for claim in ("exclusion", "estimate", "prediction"):
            found.pop(claim, None)
    if "exclusion" in found and "estimate" in found and re.search(r"\b(?:recast|reinterpret)\w*", prompt, re.I):
        text = prompt[found["estimate"][0]:found["estimate"][1]].lower()
        if re.match(r"constrain|bound", text):
            found.pop("estimate")
    expected_words = _EXPECTED_WORDS.search(prompt)
    observed_words = (_OBSERVED_WORDS.search(prompt) or re.search(
        r'\b(?:current|present)\b[^.;\n?]{0,100}\brule\s+out\b|'
        r'\bpublished\s+(?:measured\s+|observed\s+)?(?:measurements?|measured\b)', prompt, re.I))
    figure_reference = _PUBLISHED_FIGURE.search(prompt) or any(c[5] for c in cues)
    for claim, row in found.items():
        start, end, _claim, artifact, require, _ = row
        require = dict(require)
        if claim == "prediction":
            text = prompt[start:end].lower()
            after = prompt[end:end + 60].lower()
            artifact = ("figure" if text.startswith("plot") else
                        "scalar" if re.match(r"cross|rate", text) else
                        "binned_values" if not text.startswith("predict") or re.search(
                            r"\b(?:distribution|spectr|histogram|yield|shape)", after) else "scalar")
        if claim == "finding" and re.search(r"\bplot\b|\bfigure\b|\boverlay", prompt[start:end + 60], re.I):
            artifact = "figure"
        if claim == "calculation" and re.search(r"diagram|draw", prompt[start:min(len(prompt), end + 60)], re.I):
            artifact = "figure"
        if claim in ("exclusion", "estimate", "significance"):
            if observed_words and not (expected_words and not re.search(r"\bobserved\b", prompt, re.I)):
                require["level"] = "observed"
            elif expected_words:
                require["level"] = "expected"
            if claim == "exclusion" and figure_reference:
                reference = _PUBLISHED_FIGURE.search(prompt)
                require["comparison"] = {"target": "published_figure",
                                         "locator": reference.group(0) if reference else
                                         "the published element named in the request"}
        if claim == "agreement":
            published = _PUBLISHED_VALUES.search(prompt)
            if published:
                target = ("published_value" if re.search(r"value|average|uncertainty", published.group(0), re.I)
                          else "published_table")
                require["comparison"] = {"target": target, "locator": published.group(0)}
        cues.append((start, end, claim, artifact, require, False))
    return sorted(cues, key=lambda row: (row[0], row[1]))


def _route_hints(prompt, neutral):
    """Lexical route hints from the request (never admission), on the identity-neutral text."""
    from ravel.workflow import intake, route_prompt
    active = intake.actionable_text(intake.routing_text(neutral))
    view = route_prompt.classification_view(active)
    rows = []
    for hint in route_prompt.ranked_hints(view, neutral):
        spans = [span(prompt, s["start"], s["end"]) for s in hint.get("evidence", [])
                 if prompt[s["start"]:s["end"]] == s["text"]]
        value = {"mode": hint["mode"], "rule": hint["rule"], "strength": hint["strength"], "rank": hint["rank"],
                 "matched": hint["matched"]}
        rows.append((value, spans))
    semantic = None if intake.routing_context_unresolved(neutral) else intake.proposal(neutral)
    if semantic is not None:
        if semantic.get('operation') == 'manuscript' or semantic['kind'] == 'calculation':
            for value, _ in rows:
                if value['mode'] != semantic['kind']:
                    value['strength'] = 'weak'
        rows.append(({"mode": semantic["kind"], "rule": "semantic-kind", "strength": "strong", "rank": -2,
                      "operation": semantic.get("operation")}, []))
    inferred = intake.infer_kind(view)
    if inferred is not None:
        rows.append(({"mode": inferred, "rule": "inferred-kind", "strength": "strong", "rank": -1}, []))
    if route_prompt.measurement_fit(view):
        rows.append(({"mode": "likelihood", "rule": "measurement-fit-shape", "strength": "strong", "rank": -1}, []))
    return rows


def _resolution_note(witness, reason):
    return {"negated": "inside a negated clause of the request",
            "quoted_not_requested": "inside quoted or code text, not requested",
            "context_only": "inside an identity or context label; a locator only",
            "duplicate": "repeats an earlier item of the same value",
            "not_a_physics_value": "a formatting or reference number, not a physics value"}[reason]


def document(prompt, interpretation=None):
    """The reading of `prompt`: the deterministic floor, merged with host additions when given."""
    if type(prompt) is not str or not prompt.strip():
        raise ValueError("the request must not be blank")
    floor = _floor(prompt)
    if interpretation is None:
        return floor
    return merge(floor, interpretation, prompt)


def _floor(prompt):
    from ravel.workflow import intake
    b = _Builder(prompt)
    whole = span(prompt, 0, len(prompt))
    identity = _identity_spans(prompt)
    titles = [(s, e) for s, e, _ in intake.publication_titles(prompt)]
    quoted = _quoted_spans(prompt) + titles
    negated = _negated_spans(prompt)
    neutral = neutral_text(prompt)
    active_text = intake.actionable_text(intake.routing_text(neutral))

    def active_at(position):
        return not (_inside(position, identity) or _inside(position, quoted) or _inside(position, negated))

    # ---- witness items and facts
    candidates = _witness_candidates(prompt)
    seen, used = {}, set()
    collision = None
    for start, end, kind, value in candidates:
        if kind == "quantity" and _unit_family(value["unit"]) == "energy":
            ctype, _ = _classify_quantity(prompt, start, end, value, "energy", None)
            if ctype == "collision_energy":
                collision = value.get("gev")
                break
    for start, end, kind, value in candidates:
        w = b.add_witness(kind, value, start, end)
        reason = None
        if _inside(start, identity):
            reason = "context_only"
        elif _inside(start, _quoted_spans(prompt)) or kind != 'publication_title' and _inside(start, titles):
            reason = "quoted_not_requested"
        elif _inside(start, negated):
            reason = "negated"
        key = (kind, _normalized_text(value.get("text", "")))
        if reason is None and key in seen:
            reason = "duplicate"
        if reason is not None:
            b.dismissed.append({"witness": w["id"], "reason": reason, "note": _resolution_note(w, reason)})
            continue
        seen[key] = w["id"]
        spans = [w["span"]]
        if kind == "identifier":
            b.add_fact("identifier", value, spans, witness=w["id"])
        elif kind == 'publication_title':
            b.add_fact('publication_title', {**value, 'resolution_required': True}, spans, witness=w['id'])
        elif kind == 'parameter_bound':
            b.add_fact('parameter_bound', value, spans, witness=w['id'], critical=True)
        elif kind == "tool":
            b.add_fact("tool", value, spans, witness=w["id"])
        elif kind == "file":
            b.add_fact("supplied_file", value, spans, witness=w["id"])
        elif kind == "perturbative_order":
            b.add_fact("perturbative_order", value, spans, witness=w["id"], critical=True)
        elif kind == "pdf":
            b.add_fact("pdf_set", value, spans, witness=w["id"], critical=True)
        elif kind == "assignment":
            b.add_fact("parameter_value", value, spans, witness=w["id"], critical=True)
        elif kind == "value_uncertainty":
            b.add_fact("stated_value", value, spans, witness=w["id"], critical=True)
        elif kind == "event_count":
            observed = re.search(r"\b(?:see|saw|observe\w*|count\w*|recorded|selected\s+in\s+data)\b",
                                 prompt[max(0, start - 30):start], re.I)
            fact_value = {**value, "role": "observed" if observed else "requested"}
            b.add_fact("event_count", fact_value, spans, witness=w["id"], critical=bool(observed))
        elif kind == "percentage":
            right = prompt[end:end + 30]
            if re.match(r"\s*(?:CLs?\b|C\.L\.|confidence|credib)", right, re.I):
                b.add_fact("confidence_level", value, spans, witness=w["id"], critical=True)
            else:
                role = re.match(r"\s*([A-Za-z][\w-]*(?:\s+[\w-]+)?)", right)
                b.add_fact("stated_fraction", {**value, "role": role.group(1).lower() if role else None}, spans,
                           witness=w["id"], critical=True)
        elif kind == "range":
            window = _WINDOW_LEFT.search(prompt[max(0, start - 60):start]) or value.get("variable")
            unit_family = _unit_family(value["unit"]) if value["unit"] else None
            if window and unit_family in ("energy", "energy_squared", None):
                b.add_fact("observable_window", value, spans, witness=w["id"])
            else:
                b.add_fact("parameter_range", value, spans, witness=w["id"], critical=True)
        elif kind == "list":
            fact_value = dict(value)
            if _unit_family(value["unit"]) == "energy":
                fact_value["gev"] = [_gev(v, value["unit"]) for v in value["values"]]
            b.add_fact("parameter_values", fact_value, spans, witness=w["id"], critical=True)
        elif kind == "quantity":
            family = _unit_family(value["unit"])
            ftype, critical = _classify_quantity(prompt, start, end, value, family, collision)
            fact_value = dict(value)
            if ftype == "quantity":
                fact_value["role"] = _quantity_role(prompt, start)
            b.add_fact(ftype, fact_value, spans, witness=w["id"], critical=critical)
        used.add(w["id"])

    if intake.research_question(neutral):
        runs = _outside_identity(prompt)
        b.add_fact('question_form', {'text': ' '.join(prompt[s:e] for s, e in runs), 'outcome_open': True},
                   [whole] if runs == [(0, len(prompt))] else [span(prompt, s, e) for s, e in runs])
    normalization = re.search(
        r'\b(?:selection|routine)\b[^.;\n]{0,60}\b(?:its\s+own|carries)\b[^.;\n]{0,30}\bluminosity\b|'
        r'\b(?:normalization|normalisation|luminosity)\b[^.;\n]{0,60}\b(?:already\s+in|from|in)\b'
        r'[^.;\n]{0,30}\b(?:selection|routine)\b', neutral, re.I)
    if normalization and active_at(normalization.start()):
        b.add_fact('normalization_source', {'text': normalization.group(0), 'from_selection': True},
                   [span(prompt, normalization.start(), normalization.end())])
    for m in re.finditer(r'\b(?:assume|suppose)\b[^.;\n]{0,160}|\bif\b[^,.;\n]{0,100}\b(?:were|had\s+been)\b[^,.;\n]{0,80}', neutral, re.I):
        if active_at(m.start()):
            b.add_fact('assumption', {'text': m.group(0), 'counterfactual': True, 'asserted': False},
                       [span(prompt, m.start(), m.end())])
    for m in re.finditer(r'\bpublished\s+(?:(?:measured|observed)\s+[^.;\n]{1,80}|measurements?\b)', neutral, re.I):
        if active_at(m.start()):
            b.add_fact('published_measurement', {'text': m.group(0), 'artifact': 'table',
                       'locator': m.group(0), 'require': {'contains_observed_data': True, 'measurement': True}},
                       [span(prompt, m.start(), m.end())], authority='source_document')

    # ---- facts without witness values: model terms, experiments, beams, stated level
    from ravel.workflow.route_prompt import extract_models
    for name in extract_models(neutral):
        hit = None
        for m in re.finditer(re.escape(name), prompt):
            if active_at(m.start()):
                hit = m
                break
        if hit:
            b.add_fact("model_term", {"text": hit.group(0)}, [span(prompt, hit.start(), hit.end())])
    experiments = []
    for m in _EXPERIMENT_RE.finditer(prompt):
        if active_at(m.start()) and m.group(0).upper() not in [e.upper() for e in experiments]:
            experiments.append(m.group(0))
            b.add_fact("experiment", {"text": m.group(0)}, [span(prompt, m.start(), m.end())])
    for rx, beams in _BEAM_RES:
        m = rx.search(prompt)
        if m and active_at(m.start()):
            b.add_fact("beams", {"text": m.group(0), "beams": beams}, [span(prompt, m.start(), m.end())],
                       critical=True)
            break
    for m in re.finditer(r"\bcompar\w*\s+(?:it\s+|them\s+|its\s+\w+\s+)?(?:with|to|against)\s+"
                         r"((?:the\s+)?[A-Z][\w+-]*(?:\s+[A-Z][\w+-]*)?)", prompt):
        if active_at(m.start(1)):
            b.add_fact("comparison_target", {"text": m.group(1)}, [span(prompt, m.start(1), m.end(1))])
    level = _LEVEL_RE.search(prompt)
    if level and active_at(level.start()):
        b.add_fact("level", {"text": level.group(0), "level": (level.group(1) or "particle").lower()},
                   [span(prompt, level.start(), level.end())], critical=True)

    # ---- named parameters, operators and stated values that carry no unit
    taken = [(s_["start"], s_["end"]) for f in b.facts for s_ in f["evidence"]]

    def free(start, end):
        return active_at(start) and not any(a < end and start < e for a, e in taken)
    for rx, ftype, critical in _EXTRA_FACTS:
        for m in rx.finditer(prompt):
            start, end = m.span(m.lastindex or 0) if ftype == "operator" else m.span()
            if free(start, end):
                value = {"text": prompt[start:end]}
                if ftype == "parameter_value" and m.groupdict().get("val"):
                    value.update(symbol=m.group("sym"), value=m.group("val"))
                b.add_fact(ftype, value, [span(prompt, start, end)], critical=critical)
                taken.append((start, end))

    # ---- route hints (lexical; inferred, never admission)
    for value, spans in _route_hints(prompt, neutral):
        b.add_fact("route_hint", value, spans, authority="inferred")

    # ---- constraints
    for row in stages(prompt, candidates=False):
        start = row["evidence"][0]["start"]
        if _inside(start, identity) or _inside(start, quoted):
            continue
        # A stage the request describes or cites ("describing the event generation used in run X")
        # is a subject of the text, not a stage to run.
        if re.search(r"\b(?:describ\w*|summari[sz]\w*|explain\w*|document\w*|cit\w+)\s+(?:the\s+|its\s+)?(?:[\w-]+\s+){0,2}$",
                     prompt[max(0, start - 50):start], re.I):
            continue
        negated_stage = row["negated"] or _inside(start, negated)
        b.add_constraint("negated_stage" if negated_stage else "requested_stage", {"stage": row["stage"]},
                         row["evidence"])
    if level and active_at(level.start()):
        lvl = (level.group(1) or "").lower()
        beyond = ["detector"] if lvl in ("particle", "truth", "generator", "") else ["shower", "detector"]
        stated = {c["value"]["stage"] for c in b.constraints if c["type"] == "requested_stage"}
        for stage in beyond:
            if stage not in stated:
                b.add_constraint("negated_stage", {"stage": stage, "by_level": lvl or "no detector"},
                                 [span(prompt, level.start(), level.end())])
    for fact in [f for f in b.facts if f["type"] == "tool"]:
        b.add_constraint("requested_tool", {"tool": fact["value"]["name"], "text": fact["value"]["text"]},
                         fact["evidence"])
    for m in re.finditer(r"\b(?:only|exclusively)\s+(?:use|using|with)\b[^.;\n]{0,120}|\ballowed\s+tools?\b[^.;\n]{0,120}|"
                         r"\btools?\s+(?:allowed|permitted)\b[^.;\n]{0,120}", prompt, re.I):
        if not _inside(m.start(), identity):
            b.add_constraint("tool_allowlist", {"text": m.group(0).strip()}, [span(prompt, m.start(), m.end())])
    from ravel.workflow.route_prompt import prescribed_statistics
    for text in prescribed_statistics(active_text):
        located = locate(prompt, text)
        if located:
            fixed = bool(re.search(r"sqrt|√|\blog\b|\bln\b|/|Δ\s*χ|\\Delta|delta\s*chi|credib|Bayes", text, re.I))
            b.add_constraint("prescribed_statistic", {"statistic": text, "verbatim": True,
                                                      "construction_fixed": fixed}, [located])
    if not any(c["type"] == "prescribed_statistic" for c in b.constraints):
        for m in re.finditer(r"\bposterior\b", prompt, re.I):
            if active_at(m.start()) and not _inside(m.start(), identity):
                b.add_constraint("prescribed_statistic", {"statistic": "posterior", "verbatim": True,
                                                          "construction_fixed": False}, [span(prompt, m.start(), m.end())])
                break
    for row in source_restrictions(prompt):
        kind = "blinding" if row["kind"] in ("blinded", "blinded-data") else "source_restriction"
        b.add_constraint(kind, {"kind": row["kind"], "classes": row["classes"], "identifiers": row["identifiers"],
                                "statement": row["statement"]}, row["evidence"])
    for m in re.finditer(r"\bfill\s+(?:in\s+)?(?:the\s+)?(?:attached\s+|supplied\s+|given\s+|provided\s+)?"
                         r"(?:results?\s+)?(?:template|table|form|YAML)\b|\b(?:results?|output|submission)\s+"
                         r"(?:template|format)\b|\btemplate\b|(?-i:\b[A-Z][A-Za-z]{1,7}[- ](?:format(?:ted)?|style)\b)",
                         prompt, re.I):
        if active_at(m.start()):
            b.add_constraint("template", {"text": m.group(0)}, [span(prompt, m.start(), m.end())])
            break
    for m in re.finditer(r"\bwithout\s+chang\w*\s+(?:its|the|their|any)\s+(?:[\w-]+\s+){0,3}?(?:bin\s+edges|binning|bins|"
                         r"format|columns|layout)\b|\bkeep\w*\s+(?:the\s+)?(?:[\w-]+\s+){0,4}?(?:fixed|unchanged)\b|"
                         r"\b(?:fixed|unchanged)\s+(?:bin\s+edges|binning)\b|\bdo\s+not\s+(?:change|alter|modify)\b"
                         r"[^.;\n]{0,60}|\bheld\s+fixed\b|\bas\s+given\b", prompt, re.I):
        if not _inside(m.start(), identity):
            b.add_constraint("keep_fixed", {"text": m.group(0).strip()}, [span(prompt, m.start(), m.end())])
    for m in re.finditer(r"\bwithin\s+\d+(?:\.\d+)?\s*(?:CPU[- ]?|core[- ]?|GPU[- ]?)?(?:hours?|h|days?|minutes?|GB|TB)\b|"
                         r"\bbudget\s+of\b[^.;\n]{0,40}|\bdeadline\b[^.;\n]{0,60}|\bby\s+(?:\d{1,2}\s+)?(?:January|February|"
                         r"March|April|May|June|July|August|September|October|November|December)(?:\s+\d{1,2})?"
                         r"(?:,?\s+\d{4})?\b", prompt, re.I):
        if not _inside(m.start(), identity):
            b.add_constraint("budget", {"text": m.group(0).strip()}, [span(prompt, m.start(), m.end())])
    for m in re.finditer(r"\b(?:run|proceed|work|operate|act|continue)\s+autonomously\b|\bautonomous(?:ly)?\b|"
                         r"\bwithout\s+(?:asking|checking\s+(?:in|with\s+me))\b|\buse\s+your\s+(?:own\s+)?judg(?:e)?ment\b|"
                         r"\byou\s+decide\b|\bdon['’]t\s+ask\s+me\b", prompt, re.I):
        if _inside(m.start(), negated) or _inside(m.start(), quoted) or _inside(m.start(), _inline_quotes(prompt)):
            continue
        if re.search(r"\b(?:not|never|no)\s+(?:\w+\s+){0,1}$", prompt[max(0, m.start() - 12):m.start()], re.I):
            continue
        if not any(c["type"] == "delegation" and c["evidence"][0]["start"] <= m.start() < c["evidence"][0]["end"]
                   for c in b.constraints):
            b.add_constraint("delegation", {"phrase": m.group(0), "authority_granted": False},
                             [span(prompt, m.start(), m.end())])
    for start, end in identity:
        b.add_constraint("identity_context", {"text": prompt[start:end], "locator_only": True},
                         [span(prompt, start, end)])

    # ---- requester-supplied artifacts named by a phrase
    for start, end, kind, require in supplied_inputs(prompt, active_at):
        if _inside(start, identity):
            continue
        b.add_fact("supplied_input", {"text": prompt[start:end], "artifact": kind, "require": require},
                   [span(prompt, start, end)])

    # ---- deliverables (with a requested_output fact carrying the span)
    cues = _deliverable_cues(neutral, active_at)
    for start, end, claim, artifact, require, comparison in cues:
        d = {"id": b._next(b.deliverables, "D"), "obligation_ids": [],
             "artifact": {"kind": artifact, "require": dict(require)}, "claim_kind": claim}
        b.deliverables.append(d)
        b.add_fact("requested_output", {"text": prompt[start:end], "deliverable": d["id"], "claim_kind": claim,
                                        "published_figure_comparison": comparison},
                   [span(prompt, start, end)])
    if signal_yield_request(active_text) and not any(d["claim_kind"] == "prediction" for d in b.deliverables):
        m = SIGNAL_YIELD_RE.search(prompt)
        if m and active_at(m.start()):
            d = {"id": b._next(b.deliverables, "D"), "obligation_ids": [],
                 "artifact": {"kind": "binned_values", "require": {}}, "claim_kind": "prediction"}
            b.deliverables.append(d)
            b.add_fact("requested_output", {"text": m.group(0), "deliverable": d["id"], "claim_kind": "prediction",
                                            "published_figure_comparison": False}, [span(prompt, m.start(), m.end())])

    # ---- obligation identities for the deliverables
    # A published-figure comparison is always its own quality obligation. A request that asks
    # for exactly one other thing keeps the whole-request obligation as that deliverable.
    for d in b.deliverables:
        comparison = any(f["type"] == "requested_output" and f["value"]["deliverable"] == d["id"]
                         and f["value"].get("published_figure_comparison") for f in b.facts)
        d["obligation_ids"] = [("figure-comparison-" if comparison else "deliverable-") + d["id"]]
    finer = obligation_items(_assemble(prompt, b))
    if (len(b.deliverables) == 1 and b.deliverables[0]["obligation_ids"][0].startswith("deliverable-")
            and all(row["id"].startswith("deliverable-") for row in finer)):
        b.deliverables[0]["obligation_ids"] = [ORIGINAL]

    # ---- ambiguity ledger
    def obligation_for(item_id, prefix):
        return f"{prefix}-{item_id}"

    for fact in [f for f in b.facts if f["type"] == "parameter_range"]:
        if not fact["value"].get("step"):
            b.add_ambiguity(f"scan grid: the range '{fact['value']['text']}' states no step or point count",
                            [_reading_row("requester-step", {"source": "a step or point list stated by the requester"},
                                          "user_quoted"),
                             _reading_row("published-grid", {"source": "the published grid of a cited analysis"},
                                          "source_document")],
                            fact["evidence"], critical=True, blocks=[obligation_for(fact["id"], "range"), fact["id"]])
    statistics = [c for c in b.constraints if c["type"] == "prescribed_statistic"]
    formula_given = any(c["value"]["construction_fixed"] for c in statistics)
    for c in statistics:
        if not c["value"]["construction_fixed"] and not formula_given:
            b.add_ambiguity(f"construction of the prescribed statistic '{c['value']['statistic']}': the test "
                            "statistic and its treatment of nuisances are not stated",
                            [_reading_row("requester", {"source": "the construction the requester states"}, "user_quoted"),
                             _reading_row("located-source", {"source": "the construction of a located reference"},
                                          "source_document")],
                            c["evidence"], critical=True, blocks=[obligation_for(c["id"], "statistic")])
    claims = {d["claim_kind"]: d for d in b.deliverables}
    if "exclusion" in claims and not statistics:
        d = claims["exclusion"]
        b.add_ambiguity("statistic: the request prescribes none; the policy default for an exclusion is 95% CLs",
                        [_reading_row("cls-95", {"statistic": "95% CLs"}, "adapter_default"),
                         _reading_row("requester", {"statistic": "the statistic the requester prescribes"}, "user_quoted")],
                        _output_spans(b, d["id"]), default="cls-95", critical=False, blocks=list(d["obligation_ids"]))
    if "estimate" in claims and not statistics:
        d = claims["estimate"]
        b.add_ambiguity("interval: the confidence or credibility level and the interval construction are not stated",
                        [_reading_row("profile-likelihood", {"interval": "profile-likelihood interval"}, "adapter_default"),
                         _reading_row("requester", {"interval": "the interval the requester states"}, "user_quoted")],
                        _output_spans(b, d["id"]), critical=False, blocks=list(d["obligation_ids"]))
    facts_by_type = {}
    for fact in b.facts:
        facts_by_type.setdefault(fact["type"], []).append(fact)
    rate_claims = [d for d in b.deliverables if d["claim_kind"] in ("exclusion", "estimate", "significance")]
    if (rate_claims and ("collision_energy" in facts_by_type or "beams" in facts_by_type)
            and "luminosity" not in facts_by_type and "identifier" not in facts_by_type
            and 'normalization_source' not in facts_by_type):
        anchor = (facts_by_type.get("beams") or facts_by_type.get("collision_energy"))[0]
        b.add_ambiguity("integrated luminosity: not stated; a requester value or a value cited from a located "
                        "source, never an agent default",
                        [_reading_row("requester", {"source": "the luminosity the requester states"}, "user_quoted"),
                         _reading_row("located", {"source": "a luminosity cited from a located projection"},
                                      "source_document")],
                        anchor["evidence"], critical=True,
                        blocks=[o for d in rate_claims for o in d["obligation_ids"]])
    collision_values = [f["value"].get("gev") for f in facts_by_type.get("collision_energy", [])]
    for fact in facts_by_type.get("mass", []):
        if collision_values and fact["value"].get("gev") and fact["value"]["gev"] > max(collision_values):
            b.add_ambiguity(f"the value '{fact['value']['text']}' read as a mass exceeds the stated collision energy",
                            [_reading_row("mass", {"reading": "a particle mass"}, "user_quoted"),
                             _reading_row("not-a-mass", {"reading": "another quantity"}, "agent_inference")],
                            fact["evidence"], critical=True, blocks=[fact["id"]])
    if re.search(r"\b(?:SMEFT|HEFT|Wilson\s+coefficients?|EFT)\b", active_text) and not re.search(
            r"\b(?:Warsaw|SILH|Higgs\s+basis|HISZ|Green'?s\s+basis)\b", prompt, re.I):
        m = re.search(r"\b(?:SMEFT|HEFT|Wilson\s+coefficients?|EFT)\b", prompt)
        if m:
            b.add_ambiguity("EFT operator basis, normalisation and truncation conventions are not stated",
                            [_reading_row("requester", {"source": "the convention the requester states"}, "user_quoted"),
                             _reading_row("located-source", {"source": "the convention of the cited measurements"},
                                          "source_document")],
                            [span(prompt, m.start(), m.end())], critical=True)

    # ---- boundaries
    non_whole = [row["id"] for row in obligation_items(_assemble(prompt, b))]
    if intake.routing_context_unresolved(prompt):
        spans = [span(prompt, s, e) for s, e in identity] or [whole]
        b.add_boundary("ungrounded_identifier",
                       "A claimed context identifier carries scientific actions, qualifiers or ambiguous content "
                       "that could steer the plan.",
                       "A grounded --interpretation that states the request's intent with exact spans; the whole "
                       "request is retained meanwhile.", spans, [ORIGINAL])
    recognised = (any(f["type"] != "route_hint" for f in b.facts) or b.deliverables
                  or any(c["type"] in CONSTRAINT_OBLIGATIONS for c in b.constraints)
                  or any(f["type"] == "route_hint" and f["value"].get("strength") == "strong" for f in b.facts))
    if (_content_free(active_text) or not recognised) and not boundaries(prompt, active_text):
        b.add_boundary("no_scientific_object",
                       "Nothing actionable remains once negated and quoted text is removed.",
                       "State the scientific question or operation to perform as a positive request.", [whole],
                       [ORIGINAL])
    for row in boundaries(prompt, active_text):
        evidence = row["evidence"] or [whole]
        sentence = _sentence_bounds(prompt, evidence[0]["start"], evidence[0]["end"])
        scoped = [o for o in _obligations_in(b, prompt, sentence)] or non_whole or [ORIGINAL]
        if row['kind'] == 'full-simulation':
            scoped = [ORIGINAL]
        klass = ("unsupportable_claim" if row["kind"] in ("observed-discovery-claim", "observed-from-simulation")
                 else "inaccessible_input")
        b.add_boundary(klass, row["statement"], row["would_make_possible"], evidence, scoped)
    bypass = re.compile(
        r"\b(?:skip|bypass|omit|ignore|without|no)\s+(?:the\s+|any\s+|all\s+)?(?:physics\s+)?(?:reviews?|approvals?|"
        r"check-?ins?|CHECK-IN\s*\d|gates?|sign-?off)\b|\bself-?approv\w*\b|\bapprove\s+(?:it|this|the\s+plan|"
        r"everything)\s+(?:yourself|automatically|for\s+me)\b|\bunblind\w*\b|\b(?:fabricate|invent|make\s+up)\b"
        r"[^.;\n]{0,40}\b(?:values?|numbers?|efficienc\w*|data|results?|covariances?|uncertaint\w*|systematics?)\b|"
        r"\bdon['’]t\s+wait\s+for\s+(?:my\s+)?approval\b|\b(?:has|have)\s+already\s+approved\b|"
        r"\bapprove\s+your\s+own\b", re.I)
    for m in bypass.finditer(prompt):
        if _inside(m.start(), identity) or _inside(m.start(), quoted):
            continue
        if re.search(r"\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not|no\s+need\s+to|not)\s+(?:\w+\s+){0,2}$",
                     prompt[max(0, m.start() - 25):m.start()], re.I):
            continue
        s, e = _sentence_bounds(prompt, m.start(), m.end())
        b.add_boundary("control_bypass_request",
                       f"The sentence asks to bypass governance ('{m.group(0).strip()}'); it is refused and the rest "
                       "of the request proceeds.",
                       "Nothing: approval, review, blinding and the no-invented-inputs rule are not waivable. The "
                       "remaining request proceeds under them.",
                       [span(prompt, s, e).copy() if prompt[s:e].strip() else span(prompt, m.start(), m.end())], [])
    _contradictions(b, prompt, active_at)
    _value_conflicts(b, prompt)

    # ---- every unused witness is dismissed
    accounted = used | {row["witness"] for row in b.dismissed}
    for w in b.witness:
        if w["id"] not in accounted:
            b.dismissed.append({"witness": w["id"], "reason": "not_a_physics_value",
                                "note": _resolution_note(w, "not_a_physics_value")})
    b.boundaries = [_strip_span(row) for row in b.boundaries]
    return _assemble(prompt, b)


def _strip_span(row):
    out = dict(row)
    out["evidence"] = [{k: v for k, v in s.items()} for s in row["evidence"]]
    return out


def _output_spans(b, deliverable_id):
    return [s for f in b.facts if f["type"] == "requested_output" and f["value"]["deliverable"] == deliverable_id
            for s in f["evidence"]]


def _obligations_in(b, prompt, bounds):
    reading = _assemble(prompt, b)
    s, e = bounds
    return [row["id"] for row in obligation_items(reading)
            if any(s <= ev["start"] < e for ev in row["evidence"])]


def _contradictions(b, prompt, active_at):
    """A source both used and forbidden by spans of the same request."""
    for c in [c for c in b.constraints if c["type"] == "source_restriction"]:
        forbidden = c["evidence"][0]
        names = [n for ids in c["value"]["identifiers"].values() for n in ids]
        names += {"hepdata": ["HEPData"], "tables": ["table"], "figures": ["figure"]}.get(
            (c["value"]["classes"] or [""])[0], [])
        for name in names:
            for m in re.finditer(r"\b(?:use|using|from|with|read|take)\s+(?:the\s+)?(?:published\s+)?" + re.escape(name),
                                 prompt, re.I):
                if forbidden["start"] <= m.start() < forbidden["end"] or not active_at(m.start()):
                    continue
                use = span(prompt, m.start(), m.end())
                obligation = f"source-{c['id']}"
                b.add_ambiguity(f"the request both uses and forbids '{name}'",
                                [_reading_row("use", {"source": name, "allowed": True}, "user_quoted"),
                                 _reading_row("forbid", {"source": name, "allowed": False}, "user_quoted")],
                                [use, forbidden], critical=True, blocks=[obligation])
                b.add_boundary("contradiction", f"Two spans of the request conflict on the use of '{name}'.",
                               "The requester states which span holds.", [use, forbidden], [obligation])
                return


_SAME_TARGET = re.compile(r"\b(?:the\s+same\s+sample|that\s+same\s+(?:sample|run)|the\s+only\b)", re.I)


def _value_conflicts(b, prompt):
    """Two different values of one quantity stated for the same sample: a contradiction the user resolves."""
    if not _SAME_TARGET.search(prompt):
        return
    for ftype, key in (("event_count", "count"), ("collision_energy", "gev")):
        rows = [f for f in b.facts if f["type"] == ftype and f["value"].get(key) is not None]
        values = {f["value"][key] for f in rows}
        if len(values) > 1:
            spans = [f["evidence"][0] for f in rows][:16]
            b.add_ambiguity(f"the request states {len(values)} different values of {ftype.replace('_', ' ')} "
                            "for the same sample",
                            [_reading_row(f"value-{i + 1}", {key: v}, "user_quoted") for i, v in enumerate(sorted(values))],
                            spans, critical=True, blocks=[f["id"] for f in rows])
            bounds = (min(x["start"] for x in spans), max(x["end"] for x in spans))
            b.add_boundary("contradiction", f"Two spans of the request give different {ftype.replace('_', ' ')} "
                           "values for the same sample.", "The requester states which value holds.", spans,
                           _obligations_in(b, prompt, bounds) or [ORIGINAL])
            return


def _assemble(prompt, b):
    return {"schema_version": SCHEMA_VERSION, "kind": KIND, "prompt_sha256": _sha(prompt.encode("utf-8")),
            "reader": reader_pin(), "authors": [author()],
            "witness": deepcopy(b.witness), "facts": deepcopy(b.facts), "constraints": deepcopy(b.constraints),
            "deliverables": deepcopy(b.deliverables), "ambiguities": deepcopy(b.ambiguities),
            "boundaries": deepcopy(b.boundaries), "dismissed": deepcopy(b.dismissed)}


# ------------------------------------------------------------------ obligations of a reading
def obligation_items(reading):
    """The finer obligations a reading implies, in request order (the whole request is not included).

    Each row is {id, kind, statement, criteria, evidence}. `task_completion.census_from_reading`
    places them after the verbatim whole-request obligation.
    """
    rows = []
    outputs = {}
    for fact in reading["facts"]:
        if fact["type"] == "requested_output":
            outputs.setdefault(fact["value"]["deliverable"], []).extend(fact["evidence"])
    for d in reading["deliverables"]:
        for obligation in d["obligation_ids"]:
            if obligation == ORIGINAL:
                continue
            spans = outputs.get(d["id"], [])
            text = " / ".join(s["text"] for s in spans) or "a requested output"
            quality = obligation.startswith("figure-comparison-")
            criteria = {"reading_item": d["id"], "artifact": d["artifact"]["kind"], "claim_kind": d["claim_kind"]}
            if quality:
                criteria["published_figure_comparison"] = d["artifact"]["require"].get("reference") or text
            statement = (f"Compare the delivered result with the published element: {text}" if quality else
                         f"Deliver the requested {d['claim_kind'] or 'output'} ({d['artifact']['kind']}): {text}")
            rows.append({"id": obligation, "kind": "quality" if quality else "deliverable", "statement": statement,
                         "criteria": criteria, "evidence": spans[:16]})
    for c in reading["constraints"]:
        if c["type"] not in CONSTRAINT_OBLIGATIONS:
            continue
        kind, prefix = CONSTRAINT_OBLIGATIONS[c["type"]]
        text = " / ".join(s["text"] for s in c["evidence"])
        label = c["type"].replace("_", " ")
        statement = {"negated_stage": f"Do not perform the {c['value'].get('stage')} stage the request excludes: {text}",
                     "prescribed_statistic": f"Deliver the prescribed statistic as the primary result, verbatim: {text}",
                     "requested_stage": f"Serve the requested {c['value'].get('stage')} stage: {text}",
                     "requested_tool": f"Use the requested tool {c['value'].get('tool')}, or record a substitution "
                                       f"the requester accepts: {text}"}.get(c["type"], f"Honour the {label}: {text}")
        criteria = {"reading_item": c["id"], "constraint": c["type"], **{k: v for k, v in c["value"].items()
                                                                          if isinstance(v, (str, bool, int, float))}}
        rows.append({"id": f"{prefix}-{c['id']}", "kind": kind, "statement": statement, "criteria": criteria,
                     "evidence": c["evidence"][:16]})
    for fact in reading["facts"]:
        if fact["type"] in RANGE_FACTS:
            text = fact["value"].get("text") or " / ".join(s["text"] for s in fact["evidence"])
            rows.append({"id": f"range-{fact['id']}", "kind": "coverage",
                         "statement": f"Cover the stated parameter range or values: {text}",
                         "criteria": {"reading_item": fact["id"], "range": text}, "evidence": fact["evidence"][:16]})
    rows = [row for row in rows if row["evidence"]]
    rows.sort(key=lambda row: (row["evidence"][0]["start"], row["id"]))
    return rows[:63]


# ------------------------------------------------------------------ host additions (componently)
def merge(floor, additions, prompt):
    """Add host items to a reading floor. Deleting or weakening a floor item is refused."""
    if type(additions) is not dict:
        raise ValueError("reading additions must be an object")
    from ravel.validation.validate_task_contract import _schema_errors
    if additions.get("kind") == KIND:
        errors = check(additions, prompt, floor=floor)
        if errors:
            raise ValueError("host reading refused: " + "; ".join(errors))
        return deepcopy(additions)
    errors = _schema_errors(additions, ADDITIONS_SCHEMA, "additions")
    if errors:
        raise ValueError("reading additions refused: " + "; ".join(errors))
    if additions["prompt_sha256"] != floor["prompt_sha256"]:
        raise ValueError("reading additions belong to a different request")
    if additions["author"]["actor"] == "deterministic-reader":
        raise ValueError("reading additions require a host, local-proposer or check-in author envelope")
    merged = deepcopy(floor)
    if len(merged["authors"]) >= 8:
        raise ValueError("a reading records at most eight authors")
    merged["authors"].append(deepcopy(additions["author"]))
    for section in ADDABLE:
        existing = {row["id"] for row in merged[section]}
        for row in additions[section]:
            if row["id"] in existing:
                raise ValueError(f"reading additions may not replace {section} item {row['id']}; "
                                 "add a new item instead")
            row = deepcopy(row)
            if section == "facts":
                spans_ok = row["evidence"] and all(_span_ok(prompt, s) for s in row["evidence"])
                text_ok = spans_ok and _quoted_matches(row)
                if row["authority"] in ("user_quoted", "resolved", "supplied", "source_document") and not text_ok:
                    row["authority"] = "inferred"
            if section == "constraints" and row["type"] == "delegation":
                row["value"] = {**row["value"], "authority_granted": False}
            if section == "deliverables" and not row["obligation_ids"]:
                row["obligation_ids"] = [f"deliverable-{row['id']}"]
            merged[section].append(row)
            existing.add(row["id"])
    # An inferred physics-critical fact never takes a default: it becomes a ledger row.
    blocked = {item for row in merged["ambiguities"] for item in row["blocks"]}
    for fact in merged["facts"]:
        if fact["authority"] == "inferred" and fact["physics_critical"] and fact["id"] not in blocked:
            merged["ambiguities"].append({
                "id": f"A{len(merged['ambiguities']) + 1}", "evidence": fact["evidence"],
                "issue": f"the physics-critical value '{fact['type']}' is inferred, not stated; confirm it",
                "readings": [_reading_row("inferred", fact["value"], "agent_inference"),
                             _reading_row("requester", {"source": "the value the requester states"}, "user_quoted")],
                "default": None, "observable_impact": True, "reversible": True, "physics_critical": True,
                "blocks": [fact["id"]], "status": "open", "resolution": None})
    errors = check(merged, prompt, floor=floor)
    if errors:
        raise ValueError("reading additions refused: " + "; ".join(errors))
    return merged


def _span_ok(prompt, value):
    return (type(value) is dict and type(value.get("start")) is int and type(value.get("end")) is int
            and 0 <= value["start"] < value["end"] <= len(prompt) and prompt[value["start"]:value["end"]] == value.get("text"))


def _quoted_matches(fact):
    text = fact["value"].get("text") if type(fact["value"]) is dict else None
    if type(text) is not str:
        return False
    return any(_normalized_text(text) == _normalized_text(s["text"]) or
               _normalized_text(text) in _normalized_text(s["text"]) for s in fact["evidence"])


# ------------------------------------------------------------------ delegated defaults (seam for CHECK-IN 3)
def adopted_defaults(reading):
    """Physics-critical rows a delegated machine resolved with an adapter default or inference.

    Under delegation such a default is not refused; it must carry its justification anchor in
    `resolution.evidence`: a span of the user's text, or a pin of a registered invariant or an
    authoritative-practice reference. CHECK-IN 3 lists every row returned here.
    """
    rows = []
    for row in reading["ambiguities"]:
        resolution = row["resolution"]
        if not row["physics_critical"] or resolution is None or resolution["by"] != "delegation":
            continue
        chosen = next((r for r in row["readings"] if r["id"] == resolution["reading"]), None)
        if chosen is None or chosen["authority"] not in ("adapter_default", "agent_inference"):
            continue
        anchor = resolution["evidence"]
        rows.append({"ambiguity": row["id"], "issue": row["issue"], "reading": chosen["id"],
                     "value": deepcopy(chosen["value"]), "authority": chosen["authority"],
                     "anchor": deepcopy(anchor), "anchor_kind": "user_text" if "text" in anchor else "pinned_reference",
                     "utc": resolution["utc"]})
    return rows


# ------------------------------------------------------------------ check
def _deterministic_floor(reading, prompt):
    """The reader's own floor for `prompt` when `reading` names this reader's exact source, else None."""
    if reading.get("reader") != reader_pin() or reading["authors"][0]["actor"] != "deterministic-reader":
        return None
    try:
        return document(prompt)
    except ValueError:
        return None


def _floor_kept_errors(reading, floor):
    """Items of the deterministic floor a reading deletes or weakens (a re-derived floor).

    An ambiguity row may be resolved and may gain readings; everything else must stand as read.
    """
    errors = []
    for section in (*SECTIONS, "dismissed"):
        key = "witness" if section == "dismissed" else "id"
        current = {row[key]: row for row in reading[section]}
        for row in floor[section]:
            have = current.get(row[key])
            if section == "ambiguities" and have is not None:
                fixed = ("evidence", "issue", "physics_critical", "observable_impact", "reversible", "blocks")
                if (any(have[k] != row[k] for k in fixed)
                        or any(r not in have["readings"] for r in row["readings"])):
                    errors.append(f"the reading deletes or weakens the reader's ambiguities item {row[key]}")
                continue
            if have != row:
                errors.append(f"the reading deletes or weakens the reader's {section} item {row[key]}")
    return errors


def check(reading, prompt, *, floor=None):
    """Errors of a reading against its request; [] when it satisfies every rule.

    Without an explicit `floor`, a reading that names this reader's exact source is compared with
    the floor the reader derives again from the same bytes: a host may add items and resolve
    ambiguity rows, never delete or weaken what the reader found.
    """
    from ravel.validation.validate_task_contract import _schema_errors
    errors = _schema_errors(reading, READING_SCHEMA, "reading")
    if errors:
        return errors
    if reading["prompt_sha256"] != _sha(prompt.encode("utf-8")):
        return ["reading belongs to a different request"]
    if reading["authors"][0]["actor"] != "deterministic-reader":
        errors.append("the first author of a reading is the deterministic reader")
    for section in SECTIONS:
        ids = [row["id"] for row in reading[section]]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate {section} identifiers")

    def spans_of(rows, key="evidence"):
        for row in rows:
            for value in (row[key] if key != "span" else [row["span"]]):
                if "text" in value and not _span_ok(prompt, value):
                    errors.append(f"{row.get('id', row)} evidence span does not match the request")
    spans_of(reading["witness"], "span")
    for section in ("facts", "constraints", "ambiguities", "boundaries"):
        spans_of(reading[section])
    witness = {row["id"] for row in reading["witness"]}
    used = {row["witness"] for row in reading["facts"] if row["witness"] is not None}
    dismissed = [row["witness"] for row in reading["dismissed"]]
    if used - witness or set(dismissed) - witness:
        errors.append("a fact or dismissal names an unknown witness item")
    if used & set(dismissed):
        errors.append("a witness item is both used and dismissed")
    if len(dismissed) != len(set(dismissed)):
        errors.append("a witness item is dismissed twice")
    if witness - used - set(dismissed):
        errors.append("fact_unconserved: witness items " + ", ".join(sorted(witness - used - set(dismissed),
                                                                            key=lambda x: int(x[1:])))
                      + " are neither used nor dismissed")
    blocked = {item for row in reading["ambiguities"] for item in row["blocks"]}
    identity = [(c["evidence"][0]["start"], c["evidence"][0]["end"]) for c in reading["constraints"]
                if c["type"] == "identity_context"]
    for fact in reading["facts"]:
        if fact["authority"] == "user_quoted":
            if not fact["evidence"] or not _quoted_matches(fact):
                errors.append(f"{fact['id']} user_quoted value does not equal a span of the request")
        if fact["authority"] == "inferred" and fact["physics_critical"] and fact["id"] not in blocked:
            errors.append(f"{fact['id']} is an inferred physics-critical value without a ledger row")
        if fact["type"] == "identifier" and any(_inside(s["start"], identity) for s in fact["evidence"]):
            errors.append(f"{fact['id']} identifier comes from an identity context, not the active request")
    for c in reading["constraints"]:
        if c["type"] == "delegation" and c["value"].get("authority_granted") is not False:
            errors.append(f"{c['id']} a delegation phrase grants no authority (authority_granted false)")
    for d in reading["deliverables"]:
        if not d["obligation_ids"]:
            errors.append(f"{d['id']} deliverable maps to no obligation")
    for row in reading["ambiguities"]:
        names = [r["id"] for r in row["readings"]]
        if len(names) != len(set(names)):
            errors.append(f"{row['id']} repeats a reading identifier")
        if row["default"] is not None and row["default"] not in names:
            errors.append(f"{row['id']} default is not one of its readings")
        resolution = row["resolution"]
        if (resolution is None) != (row["status"] == "open"):
            errors.append(f"{row['id']} status and resolution disagree")
        if resolution is not None:
            if resolution["reading"] not in names:
                errors.append(f"{row['id']} resolves to a reading it does not offer")
            anchor = resolution["evidence"]
            if "text" in anchor and not _span_ok(prompt, anchor):
                errors.append(f"{row['id']} resolution anchor span does not match the request")
    if floor is None and not errors:
        derived = _deterministic_floor(reading, prompt)
        if derived is not None:
            errors += _floor_kept_errors(reading, derived)
    if floor is not None:
        if floor["prompt_sha256"] != reading["prompt_sha256"]:
            errors.append("floor belongs to a different request")
        if reading["authors"][:len(floor["authors"])] != floor["authors"]:
            errors.append("the reading drops or changes an author of the floor")
        for section in (*SECTIONS, "dismissed"):
            key = "witness" if section == "dismissed" else "id"
            current = {row[key]: row for row in reading[section]}
            for row in floor[section]:
                if current.get(row[key]) != row:
                    errors.append(f"the reading deletes or weakens the reader's {section} item {row[key]}")
        for section in ("witness", "boundaries", "dismissed"):
            if len(reading[section]) != len(floor[section]):
                errors.append(f"a host may not add {section}")
    return errors
