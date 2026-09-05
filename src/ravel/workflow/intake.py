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


def validate_interpretation(value, prompt):
    errors = _schema_errors(value, INTERPRETATION_SCHEMA, "interpretation")
    if errors:
        return errors
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


def requests_discovery(text):
    active = actionable_text(text)
    return bool(re.search(r"\b(?:discover\s+(?:a|the|new)|claim\s+(?:a\s+)?(?:discovery|5\s*(?:sigma|σ))|"
                          r"announce\s+(?:a\s+)?discovery|(?:tell|report|measure|compute|calculate|find|give).{0,60}"
                          r"(?:significance\s+of\s+(?:the\s+)?excess|5\s*(?:sigma|σ)\s+(?:discovery|result)))", active, re.I))


def method_request(text):
    active = actionable_text(text)
    return bool(re.search(r"\b(?:invent|develop|design|propose|create|improve|devise)\b.{0,100}"
                          r"\b(?:method|strategy|algorithm|classifier|representation|learning|approach)\b", active, re.I)
                and re.search(r"colli(?:der|sion)|\bLHC\b|\bHEP\b|particle|anomal|search|topolog", active, re.I))


def infer_kind(text):
    """Action-oriented draft defaults; unfamiliar intent is supplied through the host interface."""
    active = actionable_text(text)
    if method_request(active):
        return "method_study"
    if re.search(r"\b(?:recreate|replicate|repeat|reconstruct|recover)\b.{0,80}(?:analysis|published|result|figure|limit|cutflow)", active, re.I):
        return "reproduce"
    if re.search(r"\b(?:list|map|catalogue|catalog|compare|collect)\b.{0,70}(?:published\s+)?(?:searches|analyses|constraints)", active, re.I):
        return "survey"
    if re.search(r"\b(?:vary|sweep|sample)\b.{0,90}(?:masses|parameters|grid|plane)", active, re.I):
        return "scan"
    return None


def proposal(prompt, interpretation=None):
    if interpretation is not None:
        errors = validate_interpretation(interpretation, prompt)
        if errors:
            raise ValueError("; ".join(errors))
        return {**interpretation, "source": "host-agent", "review_status": "draft"}
    if not method_request(prompt):
        return None
    return {"schema_version": 1, "prompt_sha256": prompt_hash(prompt), "kind": "method_study",
            "objective": prompt.strip(), "source": "local-parser", "review_status": "draft",
            "requested_outputs": ["Research proposal with candidate mechanisms, baselines and falsification tests"],
            "evidence": [{"start": 0, "end": len(prompt), "text": prompt}],
            "unresolved": ["dataset and permitted data access", "training, development and protected final evaluation splits",
                           "baseline methods and statistical calibration protocol", "compute budget and method-training executor"]}
