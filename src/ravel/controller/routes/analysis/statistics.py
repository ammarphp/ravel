"""Statistics on the analysis route: the catalogue the statistics seats receive, and the step-07 check.

The seats that set a statistic (``run.full`` and every ``scan.point``) receive the statistics-situation
catalogue as data: after the prepare phase ``bind`` writes the catalogue export as a content-addressed
run input (``inputs/statistics/situations-<digest>.json``) and pins it by digest in those steps' inputs, so
the approved plan names exactly the catalogue the seat worked from and a changed file holds the step. The
row fills the operation signature's declared context-document slot (kind ``document``); its
content-addressed path identifies it.

``errors`` is the step-07 enforcement. The result a statistics step writes must carry

- ``statistics``: the engine's statistics record (``ravel.physics.inference.situations``). It is
  recomputed with ``situations.audit``; a record that does not follow from its own facts and evidence
  is refused. A ``held`` outcome is refused with its hold labels: an owed validity check failed or did
  not run. A ``qualified`` outcome must show every one of its labels in the result's ``limitations``,
  so the qualification travels with the number;
- ``uncertainty``: the uncertainty statement of the reported limit (statistical, systematic and method
  components, what is included and what is not), checked with ``uncertainty.statement_errors``.

A worker's own verdict is never evidence: the outcome and the labels are recomputed here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .common import error

CONTEXT_DIR = "inputs/statistics"
STEP_ADAPTERS = ("exclude", "scan.point")
# The operation signatures declare a context-document slot; the catalogue fills it.
INPUT_KIND = "document"
INPUT_PREFIX = f"{CONTEXT_DIR}/situations-"


def _export_bytes():
    from ravel.physics.inference import situations
    return (json.dumps(situations.export(), indent=1, sort_keys=True, allow_nan=False) + "\n").encode()


def context_input(run_dir) -> dict | None:
    """The catalogue export as a content-addressed run input; None without a run directory."""
    if not run_dir:
        return None
    raw = _export_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    relative = f"{CONTEXT_DIR}/situations-{sha[:16]}.json"
    target = Path(run_dir) / relative
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(raw)
        temporary.replace(target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
        raise ValueError(f"{relative} differs from its content address")
    return {"artifact": relative, "sha256": sha, "kind": INPUT_KIND, "required": True}


def is_catalogue_input(row) -> bool:
    """Whether a step input row is the pinned statistics catalogue."""
    return isinstance(row, dict) and str(row.get("artifact") or "").startswith(INPUT_PREFIX)


def _statistics_step(step) -> bool:
    return ((step or {}).get("parameters") or {}).get("adapter") in STEP_ADAPTERS


def bind(plan, context):
    """The plan with the catalogue input pinned in every statistics step (unchanged without a run directory)."""
    row = context_input((context or {}).get("run_dir"))
    if row is None:
        return plan
    changed = deepcopy(plan)
    for step in changed.get("steps") or ():
        if not _statistics_step(step):
            continue
        inputs = [r for r in step.setdefault("inputs", []) if not is_catalogue_input(r)]
        inputs.append(dict(row))
        step["inputs"] = inputs
    return changed


def _limitation_texts(document):
    texts = []
    for row in document.get("limitations") or ():
        if isinstance(row, str):
            texts.append(row)
        elif isinstance(row, dict):
            texts.extend(str(v) for k, v in row.items() if k in ("note", "text", "label") and isinstance(v, str))
    return texts


def _facts_errors(document, block) -> list:
    """The record must assess the counts the limit was computed from, not an empty description."""
    from ravel.physics.inference import situations
    return situations.result_document_errors(block, document)


def errors(document, step, *, row="STEP-07-exclude") -> list:
    """The step-07 statistics refusals for one adopted result document."""
    from ravel.physics.inference import situations, uncertainty
    step_id = (step or {}).get("id")
    out = []
    block = document.get("statistics")
    if block is None:
        out.append(error("statistics_record_missing",
                         "the result carries no statistics record (the engine's situations, chosen methods, validity "
                         "checks and outcome under 'statistics')", row=row, step=step_id,
                         fix="write the statistics record the limit-setting engine attached to its result"))
    else:
        problems = situations.audit(block) or _facts_errors(document, block)
        if problems:
            out.append(error("statistics_record_invalid", "the statistics record does not recompute: "
                             + "; ".join(problems)[:1500], row=row, step=step_id))
        else:
            outcome = block["validity"]["outcome"]
            labels = situations.labels(block)
            if outcome == "held":
                out.append(error("statistics_held", "the statistics outcome is held: " + "; ".join(labels)[:1500],
                                 row=row, step=step_id,
                                 fix="resolve the hold: run the owed validity checks or a method whose checks pass"))
            elif outcome == "qualified":
                shown = _limitation_texts(document)
                missing = [label for label in labels if not any(label in text for text in shown)]
                if missing:
                    out.append(error("statistics_qualification_unlabelled",
                                     "the result is qualified but its limitations do not state: "
                                     + "; ".join(missing)[:1500], row=row, step=step_id,
                                     fix="add every qualification label of the statistics record to limitations"))
    statement = document.get("uncertainty")
    problems = ["the result states no uncertainty"] if statement is None else (
        uncertainty.statement_errors(statement) or uncertainty.document_errors(document))
    if problems:
        out.append(error("uncertainty_unstated", "the reported limit's uncertainty statement is missing or invalid: "
                         + "; ".join(problems)[:1500], row=row, step=step_id,
                         fix="write the engine's uncertainty statement (components, included, not included)"))
    return out
