"""Judgment records (judgment-record.v1): every judgment call, recorded before its effect.

A record states the question, at least two options (or why only one exists) with predicted
consequences, the chosen option and its rationale, the protocol evidence its triggers
require, reversibility and budget impact. The controller writes the consequence class:
it is recomputed from the record's action by ``classes.explain`` and raised, never lowered,
by any class the worker declares. A record that fails these checks is refused, so a step
that takes a judgment without a valid record cannot be closed (JR05). Records are
append-only store entries; outcomes (confirmed, overturned, superseded) are appended later.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from . import classes, protocols, schemas

KIND = "judgment-record"
OUTCOME_KIND = "judgment-outcome"
CONTROLLER_FIELDS = ("class", "class_factors", "reviewer_requirement", "outcome")
OUTCOMES = ("confirmed", "overturned", "superseded")


class JudgmentRecordError(ValueError):
    """A judgment record was refused; ``errors`` lists every problem."""

    def __init__(self, errors):
        super().__init__("judgment record refused: " + "; ".join(errors))
        self.errors = list(errors)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def effective_triggers(record: dict, step: dict | None = None) -> list[str]:
    """The record's triggers plus those its action kind and its step's kind imply."""
    declared = list(record.get("triggers") or [])
    implied = protocols.implied_triggers((step or {}).get("kind"), record.get("action"))
    return sorted(set(declared) | set(implied) | set((step or {}).get("triggers") or []))


def check_record(record, *, step: dict | None = None) -> list[str]:
    """Every problem of a worker-written judgment record; empty means it may be stored."""
    if type(record) is not dict:
        return ["judgment record must be an object"]
    worker = {k: v for k, v in record.items() if k not in CONTROLLER_FIELDS}
    problems = schemas.errors("judgment-record.v1", worker)
    if problems:
        return problems
    options = [o["id"] for o in record["options"]]
    if len(set(options)) != len(options):
        problems.append("option ids must be unique")
    if len(options) < 2 and not record.get("single_option_reason"):
        problems.append("a judgment record needs at least two options or a stated reason why only one exists")
    if record["chosen"] not in options:
        problems.append("the chosen option is not one of the options")
    if record.get("default_option") is not None:
        if record["default_option"] not in options:
            problems.append("the default option is not one of the options")
        if not record.get("default"):
            problems.append("a default option needs its P7 conservative-default record")
    if record.get("default"):
        problems.extend(f"default: {p}" for p in protocols.check("P7", record["default"]))
    if step is not None and record["step"] != step.get("id"):
        problems.append(f"the record names step {record['step']!r}, not {step.get('id')!r}")
    try:
        names = effective_triggers(record, step)
        protocols.required(names)
    except ValueError as exc:
        return problems + [str(exc)]
    problems.extend(protocols.check_required(names, record["protocol_evidence"]))
    if step is not None and step.get("kind") == "decide":
        missing = sorted(set(protocols.protocol_ids_for(names)) - set(step.get("protocols") or []))
        if missing:
            problems.append(f"step {step.get('id')} did not receive the instruction units of {missing}")
    return problems


def classified(record: dict, *, step: dict | None = None, plan_class: str | None = None) -> dict:
    """The record with the controller's class fields; the worker's class fields are replaced."""
    stored = {k: deepcopy(v) for k, v in record.items() if k not in CONTROLLER_FIELDS}
    action = dict(stored["action"])
    effects = list(action.get("effects") or [])
    if stored["reversibility"]["kind"] == "irreversible" and "irreversible" not in effects:
        effects.append("irreversible")
    if effects:
        action["effects"] = effects
    if stored.get("declared_class") and not action.get("declared_class"):
        action["declared_class"] = stored["declared_class"]
    found = classes.explain(action)
    effective = classes.at_least(found["class"], plan_class or "R0")
    supplied = record.get("class")
    stored["class"] = effective
    stored["class_factors"] = {"computed": found["computed"], "declared": found["declared"],
                               "factors": found["factors"], "unknown": found["unknown"],
                               "plan_class": plan_class, "supplied_class": supplied,
                               "recomputed": supplied is not None and supplied != effective,
                               "declared_lower": found["declared_lower"]}
    stored["reviewer_requirement"] = classes.requirement(effective)
    stored["outcome"] = "pending"
    stored.setdefault("authority_record", None)
    stored.setdefault("rdj_case", None)
    stored["triggers"] = effective_triggers(stored, step)
    return stored


def record_judgment(store, record: dict, *, step: dict | None = None, plan_class: str | None = None) -> str:
    """Validate, classify and append one judgment record; return its store record id.

    Raises ``JudgmentRecordError`` with every problem when the record is refused: a
    judgment without a valid record has no effect.
    """
    problems = check_record(record, step=step)
    if problems:
        raise JudgmentRecordError(problems)
    stored = classified(record, step=step, plan_class=plan_class)
    stored["record_sha256"] = digest({k: v for k, v in stored.items() if k != "record_sha256"})
    return store.append(KIND, stored)


def record_outcome(store, judgment_id: str, outcome: str, evidence: dict) -> str:
    """Append the later outcome of a judgment (confirmed, overturned or superseded)."""
    if outcome not in OUTCOMES:
        raise ValueError(f"judgment outcome must be one of {OUTCOMES}")
    if type(evidence) is not dict or not evidence:
        raise ValueError("a judgment outcome needs evidence")
    return store.append(OUTCOME_KIND, {"schema_version": 1, "kind": OUTCOME_KIND, "judgment": judgment_id,
                                       "outcome": outcome, "evidence": deepcopy(evidence)})


def stored(store) -> list[dict]:
    """Every stored judgment record with its store id (``judgment_id``), in append order."""
    from .services import records as store_records
    return [{**body, "judgment_id": identifier} for identifier, body in store_records(store, KIND)]


def for_step(store, step_id: str) -> list[dict]:
    """Stored records of one step, in append order."""
    return [r for r in stored(store) if r.get("step") == step_id]


def by_digest(store, record_sha256: str) -> dict | None:
    """The stored record with this digest, or None."""
    found = [r for r in stored(store) if r.get("record_sha256") == record_sha256]
    return found[-1] if found else None


def outcomes(store) -> dict:
    """Latest outcome per judgment id."""
    from .services import records as store_records
    found = {}
    for _, row in store_records(store, OUTCOME_KIND):
        found[row["judgment"]] = row["outcome"]
    return found


def reviewer_items(record: dict) -> list[dict]:
    """must_check items for the reviewer of a stored record (RDJ seat or authority prompt)."""
    items = [{"id": "JR05:options", "row": "JR05",
              "text": "The options are genuine alternatives with predicted consequences, and the chosen option "
                      "follows from the recorded evidence."},
             {"id": "JR06:class", "row": "JR06",
              "text": f"The consequence class {record.get('class')} computed by the controller fits the effect; "
                      "a class can be raised, never lowered."}]
    return items + protocols.must_check(record.get("triggers") or [])


def authority_subject(run_id: str, record: dict, *, pins: dict, summary: str | None = None) -> dict:
    """An authority-service ``r3_action`` request for a stored R3 judgment record.

    The record's options become the offered options; its conservative default, when it
    carries a P7 record, becomes ``conservative_default``, which the authority service may
    take after the operator's wait bound in an unattended run (JR08).
    """
    view = {"run_id": run_id, "pins": dict(pins),
            "summary": summary or f"R3 judgment of step {record['step']}: {record['question']}",
            "options": [{"id": o["id"], "text": o["description"]} for o in record["options"]],
            "flags": [{"kind": "decision", "text": f"recorded choice {record['chosen']}: {record['rationale']}"}]}
    subject = {"view": view}
    if record.get("default") and record.get("default_option"):
        subject["conservative_default"] = record["default_option"]
    return subject
