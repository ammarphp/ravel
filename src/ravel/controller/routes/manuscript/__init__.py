"""The manuscript route: staged authoring, ``manuscript.build``, then an ordinary PDF build (R03).

A manuscript, note or paper from existing results is written with staged authoring and claim
mapping, assembled by the registered ``manuscript.build`` graph (computed disclosure and the
integrity review) and built into a PDF by the ``manuscript-build`` science mode
(``docs/workflow/start.md``). Source-result and claim custody holds only when every part ran.

- ``structure_errors``: a ``manuscript.build`` subgraph step depends on a staged authoring step
  that declares the claim map (an ``author`` step with a ``manuscript:claim-map`` output); a
  ``manuscript-build`` operation step depends on a ``manuscript.build`` step. The governed step
  applies it through ``ravel.controller.routes.ml.admit``.
- ``delivery_errors``: the sink's check. A manuscript deliverable (any delivered document in a
  manuscript plan, and any delivered PDF document in any plan) is accepted only from a completed
  ``manuscript-build`` step whose output custody is accepted and whose staged authoring and
  ``manuscript.build`` ancestors completed with accepted outputs. A PDF a worker built anywhere
  else is unreceipted and refused.
"""
from __future__ import annotations

ROUTE_ID = "manuscript"
MODE = "manuscript-build"
BUILD_GRAPH = "manuscript.build"
CLAIM_MAP_KIND = "manuscript:claim-map"
DOCUMENT = "document"
OUTCOME = "step-outcome"
CUSTODY = "custody"


def _error(code, step, **detail):
    return {"code": code, "step": step.get("id") if type(step) is dict else step, **detail}


def _steps(plan):
    return {row["id"]: row for row in plan.get("steps") or () if type(row) is dict and type(row.get("id")) is str}


def _ancestors(plan, step_id):
    from ..ml.modes import ancestors
    return ancestors(plan, step_id)


def is_authoring(step):
    return (type(step) is dict and step.get("kind") == "author"
            and any(type(o) is dict and o.get("kind") == CLAIM_MAP_KIND and o.get("required")
                    for o in step.get("outputs") or ()))


def is_build_graph(step):
    return type(step) is dict and type(step.get("graph")) is dict and step["graph"].get("id") == BUILD_GRAPH


def is_pdf_build(step):
    return type(step) is dict and step.get("kind") == "operate" and step.get("operation") in (MODE, "manuscript-note-pdf")


NOTE_OPERATIONS = ("manuscript-note-sources", "manuscript-note-pdf")


def is_note_stage(step):
    """A step of the governed note build (sources bound to delivered results, then the PDF)."""
    return type(step) is dict and step.get("operation") in NOTE_OPERATIONS


def structure_errors(step, plan):
    """Staged authoring before ``manuscript.build``; ``manuscript.build`` before the PDF build."""
    if is_note_stage(step):
        from . import staged
        return staged.structure_errors(step, plan)
    steps = _steps(plan)
    above = [steps[s] for s in _ancestors(plan, step.get("id")) if s in steps]
    errors = []
    if is_build_graph(step):
        if step.get("kind") != "subgraph":
            errors.append(_error("manuscript_build_kind", step, kind=step.get("kind")))
        if not any(is_authoring(row) for row in above):
            errors.append(_error("manuscript_claim_map_missing", step,
                                 detail="manuscript.build needs a staged authoring step that declares the claim map"))
        return errors
    if step.get("kind") != "operate":
        errors.append(_error("manuscript_build_kind", step, kind=step.get("kind"),
                             detail="the PDF build is an operate step of the manuscript-build mode"))
    if not any(is_build_graph(row) for row in above):
        errors.append(_error("manuscript_staging_missing", step,
                             detail="the PDF build depends on the manuscript.build graph (staged authoring, "
                                    "disclosure and integrity review)"))
    if not any(is_authoring(row) for row in above):
        errors.append(_error("manuscript_claim_map_missing", step))
    return errors


def _is_manuscript(row, plan, steps):
    if type(row) is not dict or row.get("status") != "mapped":
        return False
    artifact, claim = row.get("artifact_kind"), row.get("claim_kind")
    if not (artifact == DOCUMENT or (artifact is None and claim == DOCUMENT)):
        return False
    route = plan.get("route") if type(plan.get("route")) is dict else {}
    if route.get("id") == ROUTE_ID:
        return True
    producer = steps.get(row.get("step")) or {}
    if is_pdf_build(producer):
        return True
    output = str(row.get("output") or "")
    return output.lower().endswith(".pdf") and any(
        type(o) is dict and o.get("path") == output and o.get("kind") == DOCUMENT for o in producer.get("outputs") or ())


def _accepted(custody, step_id, path=None):
    rows = [r for r in custody.values() if r.get("step_id") == step_id and (path is None or r.get("path") == path)]
    return bool(rows) and all(r.get("status") == "accepted" and r.get("sha256") for r in rows)


def delivery_errors(plan: dict, *, outcomes: dict, custody: dict, assemblies=()) -> list[dict]:
    """Why the plan's manuscript deliverables may not be delivered (empty when every one is receipted).

    ``outcomes``: step id -> latest ``step-outcome`` record; ``custody``: artifact -> latest
    ``custody`` record (the governed step's store records).
    """
    steps = _steps(plan)
    errors = []
    for row in plan.get("deliverables") or ():
        if not _is_manuscript(row, plan, steps):
            continue
        producer = steps.get(row.get("step"))
        if not is_pdf_build(producer):
            errors.append(_error("manuscript_built_outside_mode", row.get("step"), deliverable=row.get("id"),
                                 detail="a manuscript is delivered only from a manuscript-build step"))
            continue
        problems = structure_errors(producer, plan)
        if problems:
            errors += [{**p, "deliverable": row.get("id")} for p in problems]
            continue
        if (outcomes.get(producer["id"]) or {}).get("status") != "completed" or not _accepted(
                custody, producer["id"], row.get("output")):
            errors.append(_error("manuscript_unreceipted", producer["id"], deliverable=row.get("id"),
                                 detail="the PDF build has no completed outcome with accepted output custody"))
            continue
        above = [steps[s] for s in _ancestors(plan, producer["id"]) if s in steps]
        for stage in [r for r in above if is_build_graph(r) or is_authoring(r)]:
            assembled = [a for a in assemblies if a.get("step_id") == stage["id"]
                         and a.get("plan_sha256") == plan.get("sha256") and a.get("status") == "completed"]
            graph_custody = bool(assembled) and any(r.get("sha256") == assembled[-1].get("bundle_sha256")
                and r.get("step_id") == assembled[-1].get("source_step") and r.get("path") == "outputs/bundle.json"
                and r.get("status") == "accepted" for r in custody.values())
            accepted = (graph_custody and _accepted(custody, stage["id"], "outputs/assembly.json")) if is_build_graph(stage) and producer.get("operation") == "manuscript-note-pdf" else _accepted(custody, stage["id"])
            if (outcomes.get(stage["id"]) or {}).get("status") != "completed" or not accepted:
                errors.append(_error("manuscript_stage_unreceipted", stage["id"], deliverable=row.get("id"),
                                     detail="staged authoring and manuscript.build need completed, accepted receipts"))
    return errors


def store_records(store):
    """``(outcomes, custody)`` from the run store: the latest record per step and per artifact."""
    def unwrap(row):
        return row["record"] if type(row) is dict and type(row.get("record")) is dict else row
    outcomes, custody = {}, {}
    for row in store.scan(OUTCOME):
        record = unwrap(row)
        if type(record) is dict and type(record.get("step_id")) is str:
            outcomes[record["step_id"]] = record
    for row in store.scan(CUSTODY):
        record = unwrap(row)
        if type(record) is dict and type(record.get("artifact")) is str:
            custody[record["artifact"]] = record
    return outcomes, custody


def delivery_errors_from_store(store, plan: dict) -> list[dict]:
    """``delivery_errors`` over the run store's step outcomes and custody (the sink's call)."""
    outcomes, custody = store_records(store)
    from ..ml.staged import records
    return delivery_errors(plan, outcomes=outcomes, custody=custody, assemblies=records(store, "manuscript-assembly"))
