"""Construct and revise quantitative report slots from delivered tool facts.

This composes scientific_artifact's delivery and scientific_context's measured
outputs. It does not infer scientific meaning from a number, inspect image pixels,
verify tool truth, or certify unstructured model interpretation.
"""
from copy import deepcopy
import csv
import io
import json
import math
from pathlib import Path
import re

from . import candidate_experiments as ce, scientific_artifact as sa, scientific_context as sc

MAX_FACTS = 128
MAX_SLOTS = 1024
MAX_TEXT_BYTES = 128000


def _text(value, maximum=8000):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError("bounded explicit report text required")


def _pointer(value, pointer):
    if type(pointer) is not str or len(pointer) > 1024 or pointer and not pointer.startswith("/"):
        raise ValueError("literal report JSON pointer required")
    if not pointer:
        return value
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError("valid report JSON pointer escape required")
        key = token.replace("~1", "/").replace("~0", "~")
        if type(value) is list:
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise ValueError("canonical report array index required")
            value = value[int(key)]
        elif type(value) is dict:
            value = value[key]
        else:
            raise ValueError("report pointer crosses a scalar")
    return value


def _select(value, selector):
    if type(selector) is not dict:
        raise ValueError("explicit report fact selector required")
    if selector.get("kind") == "direct":
        ce.keys(selector, ["kind", "pointer"])
        return _pointer(value, selector["pointer"])
    if selector.get("kind") != "record":
        raise ValueError("direct or identity-selected report fact required")
    ce.keys(selector, ["kind", "pointer", "id_field", "row_id", "field"])
    ce.identity(selector["id_field"]); ce.identity(selector["field"])
    rows = _pointer(value, selector["pointer"])
    if type(rows) is not list or not 1 <= len(rows) <= 256:
        raise ValueError("bounded complete report record population required")
    ids, selected = [], []
    for row in rows:
        if type(row) is not dict or selector["id_field"] not in row:
            raise ValueError("report record identity absent")
        identity = ce.digest(row[selector["id_field"]])
        if identity in ids:
            raise ValueError("duplicate report record identity")
        ids.append(identity)
        if identity == ce.digest(selector["row_id"]):
            selected.append(row)
    if len(selected) != 1:
        raise ValueError("declared report record absent")
    return selected[0][selector["field"]]


def _context(pin, base):
    if pin is None:
        return None
    document = ce.read_pin(pin, base)
    current = sc.compile_context(document["request"], base)
    for step in document["steps"]:
        attempt = {"id": step["id"], "outputs": {
            row["id"]: {"path": row["path"], "sha256": row["sha256"]} for row in step["outputs"]},
            "code_status": step["code_status_reported"], "actor_complete": step["actor_complete_reported"],
            "question": step["question"], "next_experiment": step["next_experiment"]}
        current = sc.apply_step(current, attempt, base)
    if current != document:
        raise ValueError("report context differs from replayed requested quantities")
    return current


def _resolve(request, base_dir):
    ce.keys(request, ["schema_version", "title", "artifact_request", "context", "facts", "sections", "interpretation",
                      *(["task_completion", "delivery"] if "task_completion" in request else []),
                      *(["final_results_review"] if "final_results_review" in request else [])])
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("scientific report/v1 required")
    _text(request["title"], 400)
    base = Path(base_dir).resolve(strict=True)
    delivered = sa.compose(request["artifact_request"], base_dir=base)
    context = _context(request["context"], base)
    if type(request["facts"]) is not list or not 1 <= len(request["facts"]) <= MAX_FACTS:
        raise ValueError("bounded nonempty complete report fact census required")
    tool_fields = {row["field"] for row in delivered["tool_provenance"]}
    facts = {}
    measurements = {} if context is None else {row["id"]: row for row in context["measured_quantities"]}
    for row in request["facts"]:
        ce.keys(row, ["id", "selector", "quantity_id", "context_selector", "label", "unit", "scope", "population", "limitations"])
        identity = ce.identity(row["id"])
        if identity in facts:
            raise ValueError("duplicate report fact")
        for field in ("label", "unit", "scope", "population"):
            _text(row[field], 2000)
        if type(row["limitations"]) is not list or not row["limitations"] or len(row["limitations"]) > 16:
            raise ValueError("explicit report fact limitations required")
        for limitation in row["limitations"]:
            _text(limitation)
        pointer = row["selector"].get("pointer") if type(row["selector"]) is dict else None
        if type(pointer) is not str or not pointer.startswith("/"):
            raise ValueError("report fact must name a delivered tool field")
        top_field = pointer[1:].split("/")[0].replace("~1", "/").replace("~0", "~")
        if top_field not in tool_fields:
            raise ValueError("model interpretation cannot become a delivered report fact")
        value = _select(delivered["artifact"], row["selector"])
        if type(value) not in {str, int, float, bool} or type(value) is float and not math.isfinite(value):
            raise ValueError("report slots require delivered finite JSON scalars")
        if context is None:
            if row["quantity_id"] is not None or row["context_selector"] is not None:
                raise ValueError("requested-quantity linkage needs the actual supplied context")
            requested_check = None
        else:
            measurement = measurements.get(row["quantity_id"])
            if measurement is None or not measurement["passed"]:
                raise ValueError("report fact lacks a completed current requested quantity")
            compared = _select(measurement["value"], row["context_selector"])
            if ce.digest(compared) != ce.digest(value):
                raise ValueError("delivered report fact differs from current requested quantity")
            requested_check = row["quantity_id"]
        facts[identity] = {**deepcopy(row), "value": value, "requested_quantity_checked": requested_check,
                           "delivered_tool_field": top_field}
    if type(request["sections"]) is not list or not 1 <= len(request["sections"]) <= 32:
        raise ValueError("finite report section census required")
    slots, sections, ids, used = {}, [], set(), set()
    for section in request["sections"]:
        ce.keys(section, ["id", "kind", "caption", "columns", "rows"])
        identity = ce.identity(section["id"])
        if identity in ids or section["kind"] not in {"statement", "table", "figure-data"}:
            raise ValueError("distinct supported report section required")
        ids.add(identity); _text(section["caption"])
        if type(section["columns"]) is not list or not 1 <= len(section["columns"]) <= 16:
            raise ValueError("finite report columns required")
        for label in section["columns"]:
            _text(label, 400)
        if type(section["rows"]) is not list or not 1 <= len(section["rows"]) <= 256:
            raise ValueError("complete declared report rows required")
        if section["kind"] == "statement" and (len(section["columns"]) != 1 or len(section["rows"]) != 1):
            raise ValueError("statement has one declared fact")
        row_ids = set()
        for row in section["rows"]:
            ce.keys(row, ["id", "facts"]); rid = ce.identity(row["id"])
            if rid in row_ids or type(row["facts"]) is not list or len(row["facts"]) != len(section["columns"]):
                raise ValueError("complete distinct rectangular report rows required")
            row_ids.add(rid)
            for index, fact_id in enumerate(row["facts"]):
                if fact_id not in facts:
                    raise ValueError("report section names a foreign fact")
                fact = facts[fact_id]; used.add(fact_id)
                slot = f"{identity}/{rid}/{index}"
                slots[slot] = {"fact_id": fact_id, **{key: deepcopy(fact[key]) for key in ("value", "unit", "scope", "population")}}
        sections.append(deepcopy(section))
    if used != facts.keys() or len(slots) > MAX_SLOTS:
        raise ValueError("all requested report facts must be exposed within the finite slot budget")
    if type(request["interpretation"]) is not list or len(request["interpretation"]) > 32:
        raise ValueError("bounded explicitly unverified interpretation required")
    for paragraph in request["interpretation"]:
        _text(paragraph)
    if len(json.dumps(request, allow_nan=False).encode()) > 512000:
        raise ValueError("report request exceeds finite preparation budget")
    return delivered, context, facts, sections, slots


def _display(value):
    # Display already-delivered JSON primitives; no new rounding/conversion.
    return value if type(value) is str else json.dumps(value, allow_nan=False)


def _md(value):
    return _display(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>").replace("\r", "")


def _quantity_census(context, facts):
    if context is None:
        return []
    return [{"id": row["id"], "passed": row["passed"], "exposed_fact_ids": [
        fact["id"] for fact in facts.values() if fact["requested_quantity_checked"] == row["id"]]}
        for row in context["measured_quantities"]]


def _render(request, facts, sections, slots, quantity_completion, quantity_census):
    lines = [request["title"], "", "Declared quantitative slots are transcribed from supplied tool artifacts.", ""]
    lines.extend(["Requested quantities and report exposure", ""])
    if quantity_completion is None:
        lines.extend(["Requested-quantity checks: unchecked; no scientific context was supplied.", ""])
    else:
        status = "complete" if quantity_completion else "incomplete"
        lines.extend([f"Supplied context quantity completion: {status}.", "",
                      "| Requested quantity | Supplied check status | Exposed fact IDs |",
                      "| --- | --- | --- |"])
        for row in quantity_census:
            check = "passed" if row["passed"] else "not completed"
            exposed = ", ".join(row["exposed_fact_ids"]) if row["exposed_fact_ids"] else "not exposed"
            lines.append(f"| {_md(row['id'])} | {check} | {_md(exposed)} |")
        lines.append("")
    lines.extend(["Report exposure covers only the exact selected facts below. Passing a supplied quantity check or exposing one fact does not establish complete record/vector coverage.", "",
                  "Full-task scientific acceptance: unchecked. Labels, units, scopes and interpretation remain caller declarations.", "",
                  "| Fact ID | Requested quantity | Delivered selector | Context selector |",
                  "| --- | --- | --- | --- |"])
    for fact in facts.values():
        quantity = fact["requested_quantity_checked"] or "unchecked"
        delivered_selector = json.dumps(fact["selector"], sort_keys=True, allow_nan=False)
        context_selector = "unchecked" if fact["context_selector"] is None else json.dumps(fact["context_selector"], sort_keys=True, allow_nan=False)
        lines.append(f"| {_md(fact['id'])} | {_md(quantity)} | {_md(delivered_selector)} | {_md(context_selector)} |")
    lines.append("")
    plot_data = {}
    for section in sections:
        lines.extend([section["caption"], ""])
        if section["kind"] == "statement":
            fact = facts[section["rows"][0]["facts"][0]]
            lines.extend([f"{_md(fact['label'])}: {_md(fact['value'])} [{_md(fact['unit'])}].", ""])
        else:
            lines.append("| " + " | ".join(_md(x) for x in section["columns"]) + " |")
            lines.append("| " + " | ".join("---" for _ in section["columns"]) + " |")
            rows = []
            for row in section["rows"]:
                values = [facts[identity]["value"] for identity in row["facts"]]
                lines.append("| " + " | ".join(_md(value) for value in values) + " |")
                rows.append(values)
            lines.append("")
            if section["kind"] == "figure-data":
                stream = io.StringIO(newline="")
                writer = csv.writer(stream); writer.writerow(section["columns"])
                writer.writerows([[_display(value) for value in row] for row in rows])
                plot_data[section["id"]] = {"columns": section["columns"], "rows": rows, "csv_text": stream.getvalue(),
                                            "image_pixels_verified": False, "scope": "Supplied plot data only; no rendered image/caption correctness claim"}
    lines.extend(["Quantity scope and limits", ""])
    for fact in facts.values():
        lines.extend([f"{_md(fact['label'])} [{_md(fact['unit'])}]; scope: {_md(fact['scope'])}; population: {_md(fact['population'])}.",
                      " ".join(_md(x) for x in fact["limitations"]), ""])
    if request["interpretation"]:
        lines.extend(["Unverified interpretation supplied by the author", "", *request["interpretation"], ""])
    text = "\n".join(lines)
    if len(text.encode()) > MAX_TEXT_BYTES:
        raise ValueError("complete report exceeds text budget; no silent truncation")
    return text, plot_data


def compose(request, *, base_dir, _draft_final=False):
    """Produce the actual quantitative text/tables/plot data from delivered facts."""
    if type(_draft_final) is not bool:raise ValueError('explicit draft preparation required')
    delivered, context, facts, sections, slots = _resolve(request, base_dir)
    if _draft_final and (request.get('delivery')!='final' or 'final_results_review' in request):
        raise ValueError('prepare an unreviewed exact final recipe, not an accepted presentation')
    quantity_completion = None if context is None else context["quantity_completion"]
    quantity_census = _quantity_census(context, facts)
    text, plot_data = _render(request, facts, sections, slots, quantity_completion, quantity_census)
    completion = None
    if "task_completion" in request:
        from . import task_completion
        if request["delivery"] not in ("progress", "final"): raise ValueError("progress or final task delivery required")
        check = task_completion.require_final if request["delivery"] == "final" and not _draft_final else task_completion.evaluate
        completion = check(request["task_completion"], base_dir=base_dir)
        if request["delivery"] == "final" and completion["report_recipe_sha256"] != ce.digest({k: v for k, v in request.items() if k not in ("task_completion", "delivery", "final_results_review")}):
            raise ValueError("final report differs from the exact parent-reviewed delivery recipe")
        text += "\nOriginal requested task\n\n" + _md(completion["original_request"]) + "\n\n"
        text += "| Obligation | Original criteria | Effective criteria | State |\n| --- | --- | --- | --- |\n"
        for row in completion["obligation_census"]:
            text += "| " + " | ".join(_md(x) for x in (row["id"], row["original"]["criteria"], row["effective"]["criteria"], row["state"])) + " |\n"
        if request["delivery"]=='final':
            # Draft and accepted presentation retain identical scientific text;
            # the changing approval verdict belongs to the separate gate result.
            text += "\nWhole-parent completion requires the current accepted review. Child review does not close open parent obligations.\n"
        else:
            text += "\nParent task accepted: " + str(completion["parent_task_accepted"]) + ". Child review does not close open parent obligations.\n"
        from .completion_claims import render
        text += render(completion.get('claim_records'))
        if len(text.encode()) > MAX_TEXT_BYTES: raise ValueError("complete report including original goal exceeds budget")
    final_review = None
    accepted_final = None if completion is None else completion.get('final_results_review')
    if not _draft_final and request.get('delivery')=='final' and accepted_final is not None:
        if 'final_results_review' not in request:
            raise ValueError('research final presentation requires its exact parent CHECK-IN 3 binding')
        binding=request['final_results_review']
        ce.keys(binding, ['rundir','manifest'])
        from . import physics_review,final_results_review
        rd=Path(binding['rundir']);rd=rd if rd.is_absolute() else Path(base_dir)/rd
        rd=physics_review._root(rd)
        if str(rd)!=accepted_final['rundir']:
            raise ValueError('final presentation cannot borrow another parent final review')
        supplied=physics_review._path(rd,binding['manifest']['path'])
        accepted=physics_review._path(rd,accepted_final['manifest']['path'])
        if supplied!=accepted or binding['manifest']['sha256']!=accepted_final['manifest']['sha256']:
            raise ValueError('final presentation manifest differs from exact authenticated parent CI3')
        final_review=final_results_review.gate(rd,binding['manifest'],report=text,
            recipe={k:v for k,v in request.items() if k!='final_results_review'})
        if final_review!=accepted_final:raise ValueError('parent final review changed during presentation')
    elif 'final_results_review' in request:
        # Explicit standalone final review still has no authority over a different
        # parent task; a parent final path must use the authenticated result above.
        if completion is not None:
            raise ValueError('final review binding does not belong to this parent completion')
        from . import final_results_review
        binding=request['final_results_review'];ce.keys(binding,['rundir','manifest'])
        rd=Path(binding['rundir']);rd=rd if rd.is_absolute() else Path(base_dir)/rd
        final_review=final_results_review.gate(rd,binding['manifest'],report=text,
            recipe={k:v for k,v in request.items() if k!='final_results_review'})
    procedure = None
    if not _draft_final and request.get('delivery') == 'final' and completion is not None:
        from .procedure_export import attach_to_report
        procedure = attach_to_report(request['task_completion'], base_dir=base_dir)
    return {"kind": "scientific_quantitative_report_draft" if _draft_final else "scientific_quantitative_report", **({"delivery_authorized":False,"review_pending":True} if _draft_final else {}), **({"final_results_review": final_review} if final_review is not None else {}), "request_sha256": ce.digest(request),
            "report_text": text, "task_completion": completion, **({"procedure_export": procedure} if procedure is not None else {}), "expected_slots": slots, "facts": list(facts.values()), "plot_data": plot_data,
            "delivered_artifact": delivered, "context_sha256": None if context is None else context["context_sha256"],
            "declared_fact_census_complete": True,
            "requested_quantity_completion": quantity_completion,
            "requested_quantity_census": quantity_census,
            "whole_quantity_exposure_checked": False,
            "free_prose_scientifically_checked": False,
            "tool_truth_verified": False, "scientific_acceptance": False, "execution_authorized": False}


def prepare_final(request, *, base_dir):
    """Materialize draft bytes for CI3 without circular scientific acceptance.

    The exact final recipe is captured separately, without final_results_review.
    After acceptance, compose receives that recipe plus the accepted manifest.
    Draft output is explicitly unauthorized for final delivery.
    """
    return compose(request,base_dir=base_dir,_draft_final=True)


def inspect_draft(request, draft, *, base_dir):
    """Find concrete differences in every declared quantitative report slot."""
    expected = compose(request, base_dir=base_dir)
    ce.keys(draft, ["slots", "interpretation"])
    if type(draft["slots"]) is not dict or len(draft["slots"]) > MAX_SLOTS:
        raise ValueError("bounded draft slot census required")
    if type(draft["interpretation"]) is not list or len(draft["interpretation"]) > 32:
        raise ValueError("bounded draft interpretation required")
    if len(json.dumps(draft, allow_nan=False).encode()) > 2 * MAX_TEXT_BYTES:
        raise ValueError("complete draft exceeds finite inspection budget")
    for paragraph in draft["interpretation"]:
        _text(paragraph)
    changes = []
    for slot, current in expected["expected_slots"].items():
        old = draft["slots"].get(slot)
        if old is None:
            changes.append({"slot": slot, "field": "complete_slot", "before": None, "after": current, "reason": "declared quantitative slot absent"})
            continue
        ce.keys(old, current.keys())
        for field, value in current.items():
            if ce.digest(old[field]) != ce.digest(value):
                changes.append({"slot": slot, "field": field, "before": deepcopy(old[field]), "after": deepcopy(value),
                                "reason": "draft differs from delivered value or declared quantity meaning"})
    foreign = {key: deepcopy(value) for key, value in draft["slots"].items() if key not in expected["expected_slots"]}
    return {"kind": "quantitative_report_discrepancies", "request_sha256": expected["request_sha256"],
            "draft_sha256": ce.digest(draft), "changes": changes, "unrequested_slots": foreign,
            "declared_slots_match": not changes and not foreign, "complete_underlying_draft": deepcopy(draft),
            "free_prose_checked": False, "scientific_acceptance": False}


def revise(request, draft, *, base_dir):
    """Apply a useful corrected report while retaining all original discrepancies."""
    inspection = inspect_draft(request, draft, base_dir=base_dir)
    result = compose(request, base_dir=base_dir)
    if result["request_sha256"] != inspection["request_sha256"]:
        raise ValueError("report request changed during revision")
    revised = {"slots": deepcopy(result["expected_slots"]), "interpretation": deepcopy(draft["interpretation"])}
    render_request = {**request, "interpretation": revised["interpretation"]}
    text, plot_data = _render(render_request, {row["id"]: row for row in result["facts"]}, request["sections"], revised["slots"],
                             result["requested_quantity_completion"], result["requested_quantity_census"])
    if result.get("task_completion") is not None:
        text = result["report_text"]
    return {**result, "report_text": text, "plot_data": plot_data, "revised_draft": revised,
            "inspection": inspection, "unrequested_slots_still_unresolved": bool(inspection["unrequested_slots"]),
            "interpretation_revised": False, "native_runtime_consumption_verified": False,
            "limits": ["Only explicitly declared slots/metadata are checked; free prose, references and image pixels remain unverified",
                       "Quantity labels/units/scopes are supplied by the request, not inferred or scientifically certified",
                       "Foreign quantitative claims remain in the original draft and unresolved; corrected declared output omits them explicitly"]}


def input_pins(request, *, base_dir):
    _resolve(request, base_dir)
    pins = sa.input_pins(request["artifact_request"], base_dir=base_dir)
    if request["context"] is not None:
        pins = [*pins, deepcopy(request["context"])]
        context = _context(request["context"], Path(base_dir).resolve(strict=True))
        pins.extend({"path": str(Path(row["path"])), "sha256": row["sha256"],
                     "size": Path(row["path"]).stat().st_size}
                    for row in sc.step_pins(context, {"outputs": {}}, base_dir))
    if "task_completion" in request:
        from . import task_completion
        pins.extend(task_completion.evaluate(request["task_completion"], base_dir=base_dir)["input_pins"])
    if "final_results_review" in request:
        from . import final_results_review
        binding=request['final_results_review'];ce.keys(binding,['rundir','manifest'])
        rd=Path(binding['rundir']);rd=rd if rd.is_absolute() else Path(base_dir)/rd
        pins.extend(final_results_review.input_pins(rd,binding['manifest']))
    return pins


def manuscript(request, *, base_dir, bindings=None, final=False):
    """Optional full manuscript audit/delivery; arithmetic report gates unchanged."""
    from . import report_integrity
    return report_integrity.manuscript(request, base_dir=base_dir, bindings=bindings, final=final)
