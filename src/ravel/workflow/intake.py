"""Grounded, draft scientific intent independent of execution authorization.

The local parser handles ordinary action/negation clauses. A host agent can supply
a semantic interpretation for unfamiliar phrasing, bound to exact request bytes and
evidence spans. Structural validation does not certify that agent's judgment.
"""
import hashlib
import re

from ravel.validation.validate_task_contract import _schema_errors, INTERPRETATION_SCHEMA


def prompt_hash(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


# Operation kinds name concrete deliverables that need no analysis lifecycle
# stages. Each is planned under the zero-compute parent whose completion
# contract fits it, and the stored intake keeps the operation.
OPERATION_KINDS = {"manuscript": "research", "diagram": "calculation",
                   "measurement_fit": "calculation", "supplied_events": "calculation"}


def validate_interpretation(value, prompt):
    errors = _schema_errors(value, INTERPRETATION_SCHEMA, "interpretation")
    if errors:
        return errors
    operation = value.get("operation")
    if operation is not None and value["kind"] not in (operation, OPERATION_KINDS[operation]):
        errors.append("interpretation operation disagrees with its kind")
    if value["prompt_sha256"] != prompt_hash(prompt):
        errors.append("interpretation belongs to a different request")
    seen = set()
    for span in value["evidence"]:
        start, end = span["start"], span["end"]
        if not (start < end <= len(prompt)) or prompt[start:end] != span["text"]:
            errors.append("interpretation evidence span does not match the original request")
        if (start, end) in seen:
            errors.append("duplicate interpretation evidence span")
        seen.add((start, end))
    # Interpretations may summarize intent, not introduce a different known analysis.
    from ravel.workflow.route_prompt import ANACODE_RE, ARXIV_RE, INSPIRE_RE
    def identities(text):
        return ({("analysis", m.group(1).upper().replace(" ", "-")) for m in ANACODE_RE.finditer(text)}
                | {("arxiv", v) for v in ARXIV_RE.findall(text)}
                | {("inspire", m.group(1)) for m in INSPIRE_RE.finditer(text)})
    source_ids = identities(actionable_text(prompt))
    summary = " ".join([value["objective"], *value["requested_outputs"]])
    proposed_ids = identities(actionable_text(summary))
    if proposed_ids - source_ids:
        errors.append("interpretation introduces an analysis/reference absent from the request")
    if requests_discovery(summary):
        errors.append("interpretation requests a discovery claim outside the supported scientific scope")
    return errors


def actionable_text(text):
    """Remove non-request quotations/code and negated clauses, retaining positive actions."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^\s*>.*$", " ", text, flags=re.M)
    text = re.sub(r",\s*(?=(?:I|we)\s+(?:want|would|need)|(?:please\s+)?(?:reproduce|survey|scan)\b)", "; ", text, flags=re.I)
    clauses = re.split(r"[;!?](?:\s+|$)|\.(?=\s+[A-Z]|$)|\n|\bbut\b", text, flags=re.I)
    active = []
    for clause in clauses:
        clause = clause.strip()
        # A negative policy at the end must not invert an earlier positive request.
        clause = re.split(r"\b(?:without|rather than|instead of)\b", clause, maxsplit=1, flags=re.I)[0]
        negative = re.search(r"\b(?:do\s+not|don['’]t|never|avoid|must\s+not|should\s+not|no\s+need\s+to)\b", clause, re.I)
        if negative:
            clause = clause[:negative.start()]
        if re.search(r"\bneither\b", clause, re.I) or re.match(r"^(?:please\s+)?(?:not\b|no\s+(?:discovery|claim|reproduction|scan))", clause, re.I):
            continue
        if clause.strip():
            active.append(clause.strip())
    return "\n".join(active)


def _routing_context(text):
    """Separate explicit opaque identifiers from scientific request content.

    This is only a classification view. The contract, evidence and Host receive
    the complete original text. Arbitrary titles/colon prefixes are never cut.
    A claimed identifier containing actions, units or qualifiers is ambiguous,
    so local routing leaves it for the existing grounded interpretation path.
    """
    key = r"(?:benchmark|suite|task|source|context|provenance)\s+(?:id|label|name)"
    meaningful = (r"\b(?:reproduce|reinterpret|scan|calculate|compute|evaluate|convert|simplify|"
                  r"fit|generate|simulate|investigate|explore|discover|claim|survey|design|develop|"
                  r"implement|construct|run|execute|deliver|report|estimate|measure|"
                  r"do|not|never|without|if|unless|must|only|expected|observed|significance|"
                  r"constraint|limit|mass|masses|width|coupling|luminosity|GeV|TeV|MeV|fb|pb)\b")
    # Level/only qualifiers are scientific modifiers, independent of their
    # subject name. A claimed metadata row cannot erase the current detector
    # approximation or scoped operation. Keep uncertain content for the Host.
    qualifier = (r"\b[A-Za-z]+(?:[-_ ]?level|[-_ ]only)\b|"
                 r"\b(?:no|without)\s+(?:detector|events?|generation|shower)\b|"
                 r"\b(?:detector|reconstruction|fiducial|inclusive|exclusive|binned|unbinned|"
                 r"weighted|unweighted|signed|blinded|protected|uncertainty|precision|"
                 r"covariance|correlation|normalization)\b")
    # A title is a locator for source resolution. Its words provide no routing evidence.
    chars = list(text)
    for start, end, _ in publication_titles(text):
        chars[start:end] = [' ' if c not in '\r\n' else c for c in chars[start:end]]
    text = ''.join(chars)
    retained, ambiguous = [], False
    for line in text.splitlines(keepends=True):
        row = re.fullmatch(r"\s*(" + key + r")\s*[:=]\s*([^\r\n]*)(?:\r?\n)?", line, re.I)
        if row is None:
            retained.append(line)
            continue
        value = row.group(2).strip()
        opaque = bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./-]{0,199}", value))
        if opaque and not re.search(meaningful + "|" + qualifier, value, re.I):
            # Preserve line separation rather than joining neighbouring clauses.
            retained.append("\n" if line.endswith("\n") else "")
        else:
            retained.append(line)
            ambiguous = True
    return "".join(retained), ambiguous


def routing_text(text):
    """Conservative generic classification/candidate view, never input authority."""
    return _routing_context(text)[0]


def routing_context_unresolved(text):
    return _routing_context(text)[1]


def publication_titles(text):
    """Explicit quoted publication titles, with their original spans; no identity inference."""
    rows = []
    rx = r'\b(?:paper|article|publication|preprint|title)\s*(?:(?:titled|called|named)\s*|:\s*)?["“]([^"”\n]{1,300})["”]'
    for match in re.finditer(rx, text, re.I):
        rows.append((match.start(1), match.end(1), match.group(1)))
    return rows


def research_question(text):
    """Outcome-open assessment forms, excluding polite commands and bounded operations."""
    active = actionable_text(routing_text(text))
    return bool(re.search(
        r'\b(?:assess|evaluate|determine|check|test)\s+(?:whether|the\s+viability)\b|'
        r'^(?:can|could|does|do|would|is|are)\s+(?!you\b)[^.;\n?]{0,160}'
        r'\b(?:explain|reconcile|account|rule\s+out|ruled\s+out|consistent|viable)\b|'
        r'\bhow\s+(?:strongly|well|robust)\b|'
        r'\bcompare\b[^.;\n]{0,160}\band\s+(?:judge|assess|determine)\b|'
        r'\bwhich\s+of\b[^.;\n]{0,100}\b(?:explain|viable|consistent)\b', active, re.I | re.M))


def prospective_significance_request(text):
    """An explicitly prospective statistic is distinct from an observed claim.

    This identifies study intent, not an implemented/calibrated significance
    engine. Direct demands to claim/announce discovery still remain blocked.
    """
    active = actionable_text(routing_text(text))
    prospective = bool(re.search(r"\b(?:expected|prospective|forecast|Asimov)\b.{0,100}(?:5\s*(?:sigma|σ)|significance|discovery[- ]reach|discovery\s+(?:sensitivity|reach))", active, re.I))
    actual_claim = bool(re.search(r"\b(?:discover\s+(?:a|the|new)|claim\s+(?:a\s+)?discovery|announce\s+(?:a\s+)?discovery|significance\s+of\s+(?:the\s+)?excess)\b", active, re.I))
    return prospective and not actual_claim


def luminosity_projection_request(text):
    """A hypothetical tagger/parameter extension does not ask for future luminosity."""
    return bool(re.search(r"hl.?lhc|future\s+(?:run|lumi)|target\s+lumi|(?:project|extrapolat).{0,70}(?:lumi|run.?[34]|fb)|(?:lumi|run.?[34]).{0,70}(?:project|extrapolat)", actionable_text(routing_text(text)), re.I))


def requests_discovery(text):
    active = actionable_text(routing_text(text))
    if prospective_significance_request(active):
        return False
    return bool(re.search(r"\b(?:claim\s+(?:a\s+)?(?:discovery|5\s*(?:sigma|σ))|"
                          r"announce\s+(?:a\s+)?discovery|(?:tell|report|measure|compute|calculate|find|give).{0,60}"
                          r"(?:5\s*(?:sigma|σ)\s+(?:discovery|result)))", active, re.I))


def method_request(text):
    active = actionable_text(routing_text(text))
    return bool(re.search(r"\b(?:invent|develop|design|propose|create|improve|devise|train|build|fine-?tune)\b.{0,100}"
                          r"\b(?:method|strategy|algorithm|classifier|representation|learning|approach|technique|"
                          r"tagger|anomaly[- ]detector|(?:neural|graph)[- ]?(?:network|net)s?|GNNs?|transformers?|"
                          r"BDTs?|boosted\s+decision\s+trees?|regressors?|normali[sz]ing\s+flows?|autoencoders?)\b", active, re.I)
                and re.search(r"colli(?:der|sion)|\bLHC\b|\bHEP\b|particle|anomal|search|topolog|\bjets?\b|"
                              r"jet[- ]tagg|\btagg|\btag\b|\bboosted\b|\bb-?jets?\b|\bHiggs\b|\btop\s+quarks?\b|"
                              r"trigger|calorimet|\btrack|vertex|\bevents?\b", active, re.I))


GENERATOR_TOOLS = (r"MadGraph|MG5(?:_aMC)?|aMC@NLO|Pythia\s*\d*|Sherpa|Powheg|POWHEG|Herwig|"
                   r"Whizard|WHIZARD|CalcHEP|CompHEP")
_EVENT_FILE = (r"\.(?:hepmc\d?|lhe|lhef|yoda)(?:\.gz)?\b|\bHepMC\d?\b|(?-i:\bLHE\b)|\bevent\s+files?\b|"
               r"\b(?:supplied|attached|provided|given|existing|my|our)\s+(?:\w+\s+){0,2}events?\b")
_EVENT_ANALYSIS = (r"\bRivet\b|(?-i:\b(?:ATLAS|CMS|LHCB|ALICE)_\d{4}_[IS]\d{4,8}\b)|"
                   r"\b(?:CheckMATE|MadAnalysis|SimpleAnalysis)\b")
_BROADER_ANALYSIS = r"\b(?:reproduce|reinterpret|recast|scan)\b"


_ARTIFACT_TYPES = (('hepmc', 'HepMC'), ('lhe', 'LHE'), ('lhef', 'LHE'), ('yoda', 'YODA'), ('root', 'ROOT file'),
                   ('slha', 'SLHA'), ('onnx', 'ONNX model'), ('saf', 'SAF'), ('tex', 'LaTeX'))


def _artifact_labels(token):
    from pathlib import Path
    suffixes = [part.lower() for part in Path(token.rstrip('/')).name.split('.')[1:]]
    return ' '.join(label for suffix, label in _ARTIFACT_TYPES
                    if any(s in (suffix, suffix + '2', suffix + '3') for s in suffixes))


def strip_locations(text):
    """Replace paths and file names by their recognized artifact types.

    A location names where inputs live, not what to do with them. A slash also
    joins ordinary terms (SR/CR, numerator/denominator), so only a token shaped
    like a location counts as a path.
    """
    def path(match):
        raw = match.group(0); token = raw.rstrip('.,;:!?')
        located = (token.startswith(('/', '~/', './', '../')) or token.count('/') >= 2
                   or re.search(r'\.[A-Za-z]\w{0,7}$', token)
                   or re.search(r'\b(?:in|from|at|under|into|directory|folder|dir|path|file|run)\s*$',
                                text[:match.start()], re.I))
        return ' ' + _artifact_labels(token) + ' ' + raw[len(token):] if located else raw
    text = re.sub(r'[^\s()\[\]{}<>,;"]*\w/[^\s()\[\]{}<>,;"]*', path, text)
    return re.sub(r'(?<![\w/])[\w+-]+(?:\.[A-Za-z]\w{0,7})+\b', lambda m: ' ' + _artifact_labels(m.group(0)) + ' ', text)


def operation_kind(text):
    """A concrete deliverable that needs no analysis lifecycle stages, or None."""
    if routing_context_unresolved(text):
        return None
    active = strip_locations(actionable_text(routing_text(text)))
    if re.search(r"\b(?:draw|enumerate|list|generate|produce|render|show|count|find|give|plot)\b[^.;\n]{0,80}"
                 r"\b(?:Feynman\s+diagrams?|(?:tree|one|two|multi)[- ](?:level|loop)\s+diagrams?)", active, re.I):
        return "diagram"
    generation = re.search(r"\b(?:generate|simulate)\b", active, re.I)
    if (not generation and re.search(_EVENT_FILE, active, re.I)
            and re.search(_EVENT_ANALYSIS, active, re.I)):
        return "supplied_events"
    question = re.match(r"\s*(?:which|what)\b", active, re.I)
    if (not question and not generation and not re.search(_BROADER_ANALYSIS, active, re.I)
            and re.search(r"\b(?:measurements?|STXS|HEPData|data\s+points|cross[- ]section\s+data)\b", active, re.I)
            and re.search(r"\b(?:fit|fits|fitting|constrain|bound|determine|extract|global\s+fit)\b", active, re.I)
            and re.search(r"\b(?:coefficients?|Wilson|parameters?|couplings?|SMEFT|EFT|kappas?)\b|κ|\bC_?\{?[A-Za-z]",
                          active, re.I)):
        return "measurement_fit"
    writing = re.search(r"\b(?:write|draft|prepare|compose|typeset)\b[^.;\n]{0,60}\b(?:paper|manuscript|article|"
                        r"letter|preprint|write-?up|internal\s+note|note|report)\b", active, re.I)
    if (writing and not generation and not research_request(active[:writing.start()])
            and not re.search(_BROADER_ANALYSIS, active[:writing.start()], re.I)
            and not re.search(r'(?:\b(?:and|then)|\n)\s+(?:also\s+)?(?:reproduce|reinterpret|recast|scan|search\s+for)\b',
                              active[writing.end():], re.I)):
        return "manuscript"
    return None


def requested_stages(text):
    """Generation stages beyond parton level that the request names explicitly."""
    active = actionable_text(routing_text(text))
    stages = []
    if re.search(r"\b(?:shower\w*|hadroni[sz]\w*|Pythia|Herwig)\b", active, re.I):
        stages.append("parton shower and hadronization")
    if (re.search(r"\b(?:detector|Delphes|fast[- ]?sim\w*|reconstruct\w*)\b", active, re.I)
            and not re.search(r"\bno\s+detector\b|\b(?:parton|particle|truth|generator)[- ]level\b", active, re.I)):
        stages.append("detector simulation")
    if re.search(r"\b(?:lepton|photon|electron|muon)\s+PDFs?\b|\bPDF\s+set\b|\bLHAPDF\b", active, re.I):
        stages.append("declared PDF set")
    return stages


def infer_kind(text):
    """Action-oriented draft defaults; unfamiliar intent is supplied through the host interface."""
    if routing_context_unresolved(text):
        return None
    active = strip_locations(actionable_text(routing_text(text)))
    if research_request(active):
        return "research"
    if method_request(active):
        return "method_study"
    operation = operation_kind(active)
    if operation:
        return OPERATION_KINDS[operation]
    # Narrow routes require an explicit scoped request. Mentioning a generator or
    # likelihood inside an end-to-end reproduction must not truncate that request.
    # A requested shower or detector stage is a generation component, retained as
    # an explicit intake requirement rather than vetoing the generation route.
    if not re.search(_BROADER_ANALYSIS + r"|summary\s*plot|overlay|published\s+limits", active, re.I):
        if (re.search(r"\b(?:generate|simulate|produce)\s+(?:[\w'+~>*.,()-]+\s+){0,6}?events?\b", active, re.I)
                or (re.search(r"\b(?:generate|simulate|produce|compute|calculate|evaluate)\b", active, re.I)
                    and re.search(r"\b(?:with|using|in|via|through)\s+(?:" + GENERATOR_TOOLS + r")", active, re.I))):
            return "generate"
        if re.search(r"\b(?:generation[- ]only|parton[- ]level)\b", active, re.I) and re.search(
                r"\b(?:generate|simulate|produce|generation|distributions?|histograms?|spectr(?:um|a)|shapes?|events?)\b",
                active, re.I):
            return "generate"
    broader = re.search(r"\b(?:reproduce|reinterpret|scan|detector|shower)\b", active, re.I)
    if not broader:
        if re.search(r"\b(?:likelihood[- ]only|statistics[- ]only|statistical[- ]only)\b", active, re.I):
            return "likelihood"
        if re.search(r"\b(?:fit|compute|calculate|evaluate)\b", active, re.I) and re.search(
                r"\b(?:supplied|provided|given)\b.{0,60}\b(?:workspace|likelihood|counting model)\b", active, re.I):
            return "likelihood"
    if re.search(r"\b(?:recreate|replicate|repeat|reconstruct|recover)\b.{0,80}(?:analysis|published|result|figure|limit|cutflow)", active, re.I):
        return "reproduce"
    # A requested survey is the action; "constrain" can describe its subject.
    # Match request heads, not the noun in "use survey results to constrain".
    if re.search(r"^(?:please\s+)?(?:(?:(?:I|we)\s+(?:want|need|would like)\s+"
                 r"(?:you\s+)?to|(?:can|could|would)\s+you(?:\s+please)?)\s+)?survey\b",
                 active, re.I | re.M):
        return "survey"
    if re.search(r"\b(?:list|map|catalogue|catalog|compare|collect)\b.{0,70}(?:published\s+)?(?:searches|analyses|constraints)", active, re.I):
        return "survey"
    if re.search(r"\b(?:vary|sweep|sample)\b.{0,90}(?:masses|parameters|grid|plane)", active, re.I):
        return "scan"
    # A compact calculation keeps its own numerical question. A broader scan,
    # analysis or discovery workflow must not become one arithmetic component.
    if (not re.search(r"\b(?:reproduce|reinterpret|scan|grid|search|detector|shower)\b", active, re.I)
            and re.search(r"\b(?:calculate|compute|evaluate|convert|simplify)\b|^what is\s+[-+0-9.(]", active, re.I)):
        return "calculation"
    return None


def research_request(text):
    active = actionable_text(routing_text(text))
    if research_question(active):
        return True
    # A background estimate for a new search is research; a published one used
    # inside a reinterpretation or reproduction is not.
    if ((re.search(r"\bbackground\s+estimat(?:e|es|ion)\b", active, re.I)
            or re.search(r"\bestimat\w*\b[^.;\n]{0,40}?\bbackgrounds?\b", active, re.I))
            and re.search(r"\b(?:search|signal[- ]regions?|blind\w*)\b", active, re.I)
            and not re.search(r"\b(?:reinterpret|reproduc|recast|published\s+background)\w*", active, re.I)):
        return True
    from .request_reading import supplied_sample_search
    if supplied_sample_search(active):
        return True
    return bool(re.search(r"\b(?:discover\s+(?:a|the|new)|investigate|explore)\b|"
                          r"\b(?:design|develop)\b.{0,80}\b(?:background estimat(?:e|es|ion)|search strategy)\b|"
                          r"\b(?:design|develop|construct|build|derive|perform|provide|produce|validate|make)\b"
                          r"[^.;\n]{0,80}\bbackground\s+estimat(?:e|es|ion)\b|"
                          r"\b(?:design|plan|devise|prepare)\s+and\s+(?:then\s+)?(?:carry\s+out|perform|execute|run|conduct)\b"
                          r"[^.;\n]{0,80}\bsearch\b|"
                          r"\b(?:carry\s+out|conduct)\s+(?:(?:a|an|the|our|my|new|blinded|blind|dedicated|full|complete)\s+)*search\b|"
                          r"\b(?:estimate|evaluate|compute|calculate|measure)\b.{0,80}\b(?:significance|p[- ]?value)\b|"
                          r"\b(?:expected|observed|prospective)\s+(?:significance|p[- ]?value)\s*:\s*"
                          r".{0,80}\b(?:estimate|evaluate|compute|calculate|measure)\b|"
                          r"\b(?:implement|construct|develop|create|run|execute|perform)\b.{0,100}\b"
                          r"(?:search analysis|analysis workflow|(?:custom\s+)?(?:collider\s+|physics\s+)?analysis routine|custom routine)\b|"
                          r"\b(?:run|execute|perform)\b.{0,140}\b(?:simulation|event generation)\b"
                          r".{0,140}\b(?:selections?|bins|report)\b", active, re.I))


OPERATION_UNRESOLVED = {
    "manuscript": ["source run directories, accepted results and figures the text may cite",
                   "target format, template, length and audience",
                   "claims each section may state from accepted evidence"],
    "diagram": ["model definition (UFO, model file or named theory), process, perturbative order and external states",
                "diagram engine availability, filtering conventions and rendering format"],
    "measurement_fit": ["measurement inventory with central values, uncertainties and covariance or correlations",
                        "theory predictions as functions of the fitted parameters, with their convention and scale",
                        "fit statistic, parameter ranges and interval definition"],
    "supplied_events": ["supplied event files, format, generator provenance and cross-section normalization",
                        "analysis routine identity, version and its reference data",
                        "comparison statistic and requested outputs"],
}
_METHOD_ACTIONS = (r"develop|design|devise|invent|propose|create|improve|implement|train|evaluate|benchmark|"
                   r"compare|test|validate|assess|measure|quantify|report|study|demonstrate|apply")


def _normalized(value):
    kind, operation = value["kind"], value.get("operation")
    if kind in OPERATION_KINDS:
        operation, kind = kind, OPERATION_KINDS[kind]
    result = {**value, "kind": kind}
    if operation is not None:
        result["operation"] = operation
    return result


def _stage_items(stages):
    return [f"requested {stage} stage: serve it with a declared route or keep it as an unmet stage at CHECK-IN 1"
            for stage in stages]


def _requested_actions(prompt):
    """Each requested method action is an output; a proposal is only intermediate."""
    active = actionable_text(routing_text(prompt))
    clauses = re.split(r"[.;:\n]|\b(?:and\s+)?then\b|,\s*(?:and\s+)?(?=(?:" + _METHOD_ACTIONS + r")\b)|"
                       r"\band\s+(?=(?:" + _METHOD_ACTIONS + r")\b)", active, flags=re.I)
    actions = [c.strip(" ,") for c in clauses
               if c and re.search(r"\b(?:" + _METHOD_ACTIONS + r")\w*\b", c, re.I) and len(c.strip(" ,")) > 3]
    return actions or [prompt.strip()]


def proposal(prompt, interpretation=None):
    if interpretation is not None:
        errors = validate_interpretation(interpretation, prompt)
        if errors:
            raise ValueError("; ".join(errors))
        result = {**_normalized(interpretation), "source": "host-agent", "review_status": "draft"}
        if result["kind"] == "generate":
            named = "\n".join([prompt, result["objective"], *result["requested_outputs"]])
            missing = [item for item in _stage_items(requested_stages(named)) if item not in result["unresolved"]]
            result["unresolved"] = [*result["unresolved"], *missing]
        return result
    if routing_context_unresolved(prompt):
        return None
    if requests_discovery(prompt):
        return None
    kind = None if prospective_significance_request(prompt) else infer_kind(prompt)
    base = {"schema_version": 1, "prompt_sha256": prompt_hash(prompt), "objective": prompt.strip(),
            "source": "local-parser", "review_status": "draft",
            "evidence": [{"start": 0, "end": len(prompt), "text": prompt}]}
    if kind in ("calculation", "research"):
        operation = operation_kind(prompt)
        if (operation is None or OPERATION_KINDS[operation] != kind
                or research_request(prompt) or method_request(prompt)):
            operation = None
        unresolved = (OPERATION_UNRESOLVED[operation] if operation else
                      ["exact numerical inputs, units, conventions and requested precision",
                       "compatible supplied-science operation or source-backed calculation implementation"]
                      if kind == "calculation" else
                      ["complete data/source inventory, access permissions and blinded/protected partitions",
                       "candidate mechanisms, backgrounds, validation and full requested scientific outputs",
                       "actual context, compatible ordinary experiment specifications and finite campaign resources"])
        result = {**base, "kind": kind, "requested_outputs": [prompt.strip()], "unresolved": list(unresolved)}
        if operation:
            result["operation"] = operation
        return result
    if kind == "generate":
        stages = requested_stages(prompt)
        if not stages:
            return None
        return {**base, "kind": "generate", "requested_outputs": [prompt.strip()],
                "unresolved": ["explicit scoped specification for ravel plan --spec", *_stage_items(stages)]}
    if prospective_significance_request(prompt):
        return {**base, "kind": "method_study",
                "requested_outputs": ["Prospective significance/discovery-reach study for the original requested metric"],
                "unresolved": ["explicit statistical model, test statistic, nuisance and background/response assumptions",
                               "calibration/validation appropriate to the requested significance; expected CLs is not a replacement",
                               "bounded source/runtime qualification and compute budget"]}
    if not method_request(prompt):
        return None
    return {**base, "kind": "method_study",
            "requested_outputs": [*_requested_actions(prompt),
                                  "Research proposal with candidate mechanisms, baselines and falsification tests"],
            "unresolved": ["dataset and permitted data access", "training, development and protected final evaluation splits",
                           "baseline methods and statistical calibration protocol", "compute budget and method-training executor"]}


def method_study_contract(prompt, targets, semantic):
    """A method study is its own zero-compute planning parent, not a literature survey."""
    return {"schema_version": 1, "prompt": prompt, "task_mode": "survey", "targets": targets,
            "detector_mode": "none", "stat_mode": "none-survey",
            "required_user_inputs": list(semantic["unresolved"]),
            "assumptions": ["Whole original task retained; the method proposal is an intermediate planning artifact.",
                            "Grounded intent is a draft interpretation, not execution approval or a physics validation.",
                            "Method development, training and evaluation run only under a separately approved plan."],
            "compute_plan": "none",
            "cost_estimate": {"mode": "none", "walltime_h": [0.0, 0.0], "disk_gb_peak": 0.0,
                              "note": "no compute at intake; the method plan sets its budget at CHECK-IN 1"},
            "approval_required": True, "blocking": [],
            "escalate": ["method design: agree data access, training/development/protected evaluation splits, "
                         "baselines, calibration and compute at CHECK-IN 1"],
            "intake": semantic}


# Scientific parents retain their original taxonomy; this is preparation
# applicability, never execution, review or claim authority.
WHOLE_GOAL_KINDS = frozenset(('research', 'method_study', 'reproduce', 'reinterpret', 'scan', 'survey',
                              'summary_plot', 'projection', 'anomaly_search', 'no_routine'))
# Open-ended goals use the research coordinator. Analysis-shaped parents use the
# documented step-2 intake and CHECK-IN 1. Named operations and calculations use
# the bounded intake planner, which prepares an ordinary scientific study.
RESEARCH_ROUTE_KINDS = frozenset(('research', 'method_study', 'anomaly_search'))
CHECKIN_ROUTE_KINDS = frozenset(('reproduce', 'reinterpret', 'scan', 'projection', 'survey',
                                 'summary_plot', 'no_routine'))


def handoff_applicable(contract):
    kind = contract.get('intake', {}).get('kind', contract.get('task_mode'))
    return kind == 'calculation' or kind in WHOLE_GOAL_KINDS


def open_parent(contract, reading):
    """True when the reading derives an open D5 parent for this research contract."""
    if reading is None or contract.get('task_mode') != 'research':
        return False
    from .derived_label import derive
    intent = contract.get('intake') if contract.get('intake', {}).get('source') == 'host-agent' else None
    label = derive(reading, None, intent=intent)
    return label['rule'] == 'D5' and label['open']


def read_reading(base_dir, prompt):
    """The reading sidecar of a run (inputs/reading.json), checked against its request, or None."""
    import json
    from pathlib import Path
    path = Path(base_dir) / 'inputs/reading.json'
    if not path.is_file():
        return None
    from .request_reading import check
    reading = json.loads(path.read_text(encoding='utf-8'))
    errors = check(reading, prompt)
    if errors:
        raise ValueError('inputs/reading.json does not read this request: ' + '; '.join(errors[:3]))
    return reading


def handoff_route(contract, reading=None):
    """Name the next documented step for an applicable parent: one table, keyed by kind.

    With the run's reading sidecar, a research parent that no rule recognised takes the
    `open` route: its stages are composed from the operation catalogue.
    """
    intent = contract.get('intake', {})
    kind = intent.get('kind', contract.get('task_mode'))
    if not handoff_applicable(contract):
        return None
    if open_parent(contract, reading):
        return 'open'
    if intent.get('operation'):
        return 'operation'
    if kind == 'calculation':
        return 'calculation'
    return 'research' if kind in RESEARCH_ROUTE_KINDS else 'checkin'


def operation_modes(operation):
    """Scientific modes whose declared descriptor serves this named operation."""
    import json
    from pathlib import Path
    descriptors = json.loads((Path(__file__).resolve().parents[1] / 'data/mode_descriptors.json').read_text())
    return sorted(mode for mode, row in descriptors['modes'].items() if operation in row.get('operations', ())
                  and row.get('applicability', {}).get('scope') != 'source-bound')


def execution_handoff(contract_pin, *, base_dir):
    """Authenticate an intake and name its documented next step.

    The host fills the real context, source inputs and operation specifications.
    Normal Graph presentation/call accounting and public science admission still
    apply. This is a derived preparation record, not an executable job or vote.
    """
    from copy import deepcopy
    from .task_completion import _Inputs, _contract
    inputs = _Inputs(base_dir)
    try:
        contract, requirements, _, _ = _contract(contract_pin, inputs)
        kind = contract.get("intake", {}).get("kind", contract["task_mode"])
        if not handoff_applicable(contract):
            raise ValueError("a complete scientific parent or calculation intake is required")
        assignments = [row for row in requirements["assignments"] if row["id"] == "original-task"]
        expected = [{"obligation_id": row["id"], "criteria": row["criteria"]}
                    for row in requirements["obligations"]]
        if len(assignments) != 1 or assignments[0]["coverage"] != expected:
            raise ValueError("handoff requires an exact complete original-task assignment")
        reading = read_reading(base_dir, contract["prompt"])
        route = handoff_route(contract, reading)
        operation = contract.get("intake", {}).get("operation")
        calculation = None
        if kind == 'calculation':
            from .calculation_completion import completion_route
            calculation = completion_route(contract_pin, base_dir=base_dir)
        result = {"schema_version": 1, "kind": "intake-execution-handoff", "task_kind": kind, "task_mode": contract["task_mode"],
            "route": route, "original_request": contract["prompt"], "parent_contract": deepcopy(contract_pin),
            "goal_binding": {"contract": deepcopy(contract_pin), "assignment_id": "original-task"},
            "obligations": deepcopy(requirements["obligations"]),
            "requested_outputs": deepcopy(contract.get("intake", {}).get("requested_outputs", [contract["prompt"]])),
            "unresolved": deepcopy(contract["required_user_inputs"]),
            "host_next_action": "prepare a bounded intake-planner request, execute its charged designer plus preparation Graph, then review the ordinary plan or isolated source-development work",
            "planning_apis": ["ravel.workflow.intake_planner.prepare", "ravel.workflow.intake_planner.graph_spec",
                              "ravel.workflow.agent_graph.execute"],
            "instructions": ["docs/workflow/start.md", "docs/reference/intake-and-challenges.md"],
            "child_api": "ravel.workflow.science.plan", "child_schema_version": calculation['child_schema_version'] if calculation else 2,
            "child_directory_policy": "fresh ordinary child; preserve the original parent intake",
            "presentation": "present this exact record and source inputs through the existing bounded Host/Graph",
            "calculation_collection_api": calculation['collection_api'] if calculation else None,
            "completion_api": (calculation['completion_api'] if calculation
                               else "ravel.workflow.task_completion.require_final"),
            "proposal_is_intermediate": True, "parent_task_accepted": False,
            "compute_authorized": False, "physics_validated": False}
        if route == 'operation':
            result['operation'] = operation
            result['candidate_modes'] = operation_modes(operation)
            result['host_next_action'] = (
                'prepare a typed scientific specification for the named operation from the declared candidate '
                'modes and the actual supplied inputs; present it with `ravel plan` as CHECK-IN 1, or use the '
                'bounded intake planner to choose between candidates or source development')
            result['planning_apis'] = ['ravel.workflow.capability_routing.plan', 'ravel.workflow.science.plan',
                                       'ravel.workflow.intake_planner.prepare']
            result['instructions'] = ['docs/workflow/reference/scientific-studies.md',
                                      'docs/reference/intake-and-challenges.md']
        elif route == 'open':
            from .capability_routing import declared_descriptors, suggest
            stages = [c for c in reading['constraints'] if c['type'] == 'requested_stage']
            modes = []
            for row in suggest(contract['prompt'], declared_descriptors()):
                if row['mode'] not in modes:
                    modes.append(row['mode'])
            result['host_next_action'] = (
                'compose the whole request from the operation catalogue: read inputs/reading.json (facts, '
                'requested stages, deliverables, open ambiguity rows) and the draft plan when present, then '
                'prepare ordinary component studies with `ravel plan --spec`, extend the reading componently with '
                '`ravel initiate --resolve <run> --interpretation additions.json`, or run the research '
                'coordinator for open-ended research. Every obligation in the census stays open until covered.')
            result['candidate_modes'] = modes
            result['requested_stages'] = [c['value']['stage'] for c in stages]
            result['reading'] = 'inputs/reading.json'
            result['needs_interpretation'] = False
            result['planning_apis'] = ['ravel.workflow.capability_routing.plan', 'ravel.workflow.science.plan',
                                       'ravel.workflow.research_orchestrator.prepare_open']
            result['instructions'] = ['docs/workflow/start.md', 'docs/reference/intake-and-challenges.md']
        elif route == 'research':
            result['host_next_action']='prepare the complete original-goal research request, then run/resume the default durable design/independent hypothesis/experiment/RCA/revision/synthesis coordinator under explicit original limits'
            result['planning_apis']=['ravel.workflow.research_orchestrator.prepare_open',
                'ravel.workflow.research_orchestrator.open_research','ravel.workflow.research_cycle.execute_graph']
            result['presentation']='full original obligation/context/input purpose census through charged source-bound Host/Graph decisions; checkpoints and custody inventories are not reading or scientific credit'
            result['instructions'] = ['docs/workflow/start.md', 'docs/workflow/reference/research-orchestration.md']
        elif route == 'checkin':
            result['host_next_action'] = (
                'resolve inputs with the step-2 resource census and route analysis, then prepare, validate and '
                'present CHECK-IN 1 for approval before any generation')
            result['planning_apis'] = ['ravel.workflow.resource_census', 'ravel.workflow.routine_fetch',
                                       'ravel.validation.validate_checkin']
            result['presentation'] = 'CHECK-IN 1 restating the whole request, with plan, budget and numbered assumptions'
            result['instructions'] = ['docs/workflow/steps/02-inputs.md', 'docs/workflow/checklists/check-ins.md']
            result['child_api'] = None
            result['child_directory_policy'] = 'this run directory continues through the analysis workflow'
        inputs.finish()
        return deepcopy(result)
    finally:
        inputs.close()
