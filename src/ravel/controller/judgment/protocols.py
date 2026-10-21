"""The eight judgment protocols as structured evidence.

Each protocol P1-P8 of ``docs/workflow/checklists/judgment-protocols.md`` and the two
judgment evidence kinds that the workflow requires at named sites (the method ladder of
CHECK-IN 1 and stage recovery) become a schema plus a semantic check. A trigger names
the evidence a judgment call must carry (``data/judgment/triggers.json``). Presence and
completeness are enforced here; whether the answer is right is the reviewer's judgment,
so each trigger also yields a reviewer must_check item.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import json
import math

from . import schemas

CONVENTION_FIELDS = ("states_summed", "order", "pdf", "sample", "column", "channel", "normalization")
LADDER = {1: "publication", 2: "data_record", 3: "public_code", 4: "recast_database", 5: "citing_work",
          6: "ask_physicist"}
WALKED = ("OK", "ABSENT")
AXES = ("basis", "acceptance", "statistics")


@lru_cache(maxsize=1)
def triggers() -> dict:
    document = json.loads(files("ravel").joinpath("data", "judgment", "triggers.json").read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or document.get("kind") != "judgment-protocol-triggers":
        raise ValueError("judgment trigger table has an unexpected schema")
    known = set(document["evidence_ids"])
    for name, row in document["triggers"].items():
        if not row["requires"] or set(row["requires"]) - known:
            raise ValueError(f"trigger {name!r} requires unknown evidence")
    return document


def implied_triggers(step_kind=None, action=None) -> list[str]:
    """Triggers implied by a step kind or an action kind, beyond those a step declares."""
    table = triggers()
    found = list(table["step_kind_triggers"].get(step_kind or "", ()))
    kind = (action or {}).get("kind") if type(action) is dict else None
    found += table["action_kind_triggers"].get(kind or "", ())
    return sorted(set(found))


def required(trigger_names) -> list[str]:
    """Evidence ids the named triggers require; an unknown trigger raises."""
    table = triggers()["triggers"]
    result = set()
    for name in trigger_names:
        if name not in table:
            raise ValueError(f"unknown judgment trigger {name!r}")
        result.update(table[name]["requires"])
    return sorted(result)


def must_check(trigger_names) -> list[dict]:
    """Reviewer must_check items for the named triggers (census row and text)."""
    table = triggers()["triggers"]
    return [{"id": f"{table[name]['row']}:{name}", "row": table[name]["row"], "text": table[name]["must_check"]}
            for name in sorted(set(trigger_names)) if name in table]


def protocol_ids_for(trigger_names) -> list[str]:
    """The P1-P8 protocols whose instruction units a step with these triggers must receive."""
    protocols = set(triggers()["protocol_ids"])
    return sorted(set(required(trigger_names)) & protocols)


# ---- semantic checks -------------------------------------------------------------------------

def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _p1(value):
    return []  # the schema already requires looked_at to be literally true and the grammar fields


def _p2(value):
    problems = []
    left, right = value["manifests"]
    transformation = value["transformation"]
    applied = transformation["applied_to"]
    if applied is None:
        if transformation["result"] is not None:
            problems.append("P2 transformation result must be null when no side is transformed")
        compared = (left, right)
    else:
        result = transformation["result"]
        if type(result) is not dict:
            return ["P2 transformation applied to a side must record the transformed manifest"]
        missing = [f for f in CONVENTION_FIELDS if f not in result]
        if missing:
            return [f"P2 transformed manifest lacks {missing}"]
        other = right if applied == 0 else left
        compared = (result, other)
    differing = [f for f in CONVENTION_FIELDS if compared[0].get(f) != compared[1].get(f)]
    if differing:
        problems.append(f"P2 manifests still differ in {differing}; the comparison is refused until they match")
    check = value["identity_check"]
    if "unavailable_reason" in check:
        if set(check) != {"unavailable_reason"}:
            problems.append("P2 identity check is either a measurement or an unavailable reason")
    elif not {"kind", "expected", "measured", "tolerance"} <= set(check):
        problems.append("P2 identity check needs kind, expected, measured and tolerance, or an unavailable reason")
    elif abs(check["measured"] - check["expected"]) > check["tolerance"]:
        problems.append("P2 identity check fails: the two sides are not on one basis")
    return problems


def _p3(value):
    from ravel.workflow import trap_sweep
    try:
        rebuilt = trap_sweep.build({"verdicts": [{k: v for k, v in row.items() if v is not None or k in ("id", "hit", "evidence")}
                                                for row in value["verdicts"]],
                                    "escalations": value["escalations"], "obligations": value["obligations"]})
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return [f"P3 trap sweep is invalid: {exc}"]
    keys = ("traps_checked", "none_hit", "verdicts", "traps_hit", "escalations")
    if any(rebuilt[k] != value[k] for k in keys):
        return ["P3 trap sweep differs from the record its verdicts build"]
    return []


def _p4(value):
    problems = []
    for row in value["rows"]:
        anchor = row["anchor"]["value"]
        if anchor == 0 or not _finite(row["value"]) or not _finite(anchor):
            problems.append(f"P4 {row['quantity']}: the anchor value must be finite and nonzero")
            continue
        if not math.isclose(row["ratio"], row["value"] / anchor, rel_tol=1e-6, abs_tol=1e-12):
            problems.append(f"P4 {row['quantity']}: ratio differs from value / anchor")
        outside = abs(row["ratio"] - 1.0) > row["tolerance"]
        if outside and row["action"] == "proceed" and not row["regime_reason"]:
            problems.append(f"P4 {row['quantity']}: a ratio outside tolerance proceeds only with a named regime reason")
    if not value["rows"] and not value.get("unavailable"):
        problems.append("P4 records at least one anchor row or one unavailable anchor with its bounded test")
    return problems


def _p5(value):
    problems = []
    causes = sorted(value["causes"], key=lambda c: c["cost_rank"])
    tested = [c["status"] != "untested" for c in causes]
    if not any(tested):
        problems.append("P5 tests at least the cheapest discriminating cause")
    if any(later and not earlier for earlier, later in zip(tested, tested[1:])):
        problems.append("P5 tests run in cost order: a cheaper cause is untested while a costlier one was tested")
    if len({c["id"] for c in causes}) != len(causes):
        problems.append("P5 cause ids must be unique")
    return problems


def _p6(value):
    problems = []
    seen = {}
    for row in value["rungs"]:
        if LADDER.get(row["rung"]) != row["name"]:
            problems.append(f"P6 rung {row['rung']} is {LADDER.get(row['rung'])}, not {row['name']}")
        if row["rung"] in seen:
            problems.append(f"P6 rung {row['rung']} appears twice")
        seen[row["rung"]] = row
        if row["status"] == "NOT_APPLICABLE" and not row["reason"]:
            problems.append(f"P6 rung {row['rung']} not applicable needs a reason")
    if value["claim"] == "unavailable":
        for rung in range(1, 6):
            row = seen.get(rung)
            if row is None:
                problems.append(f"P6 unavailable claim lacks rung {rung} ({LADDER[rung]})")
            elif row["status"] not in WALKED + ("NOT_APPLICABLE",):
                problems.append(f"P6 rung {rung} is {row['status']}: an outage or a skipped rung is not absence")
            elif row["status"] == "OK":
                problems.append(f"P6 rung {rung} found the resource; the unavailable claim contradicts it")
    return problems


def _p7(value):
    problems = []
    if not value["direction_established"] and value["expected_sign"] not in ("unknown", "propagated"):
        problems.append("P7 a bias sign without established direction is not inferred; state it unknown or propagate it")
    if value["physics_critical"] and value["justification"] is None:
        problems.append("P7 a physics-critical default needs a justification citing a request span, a registered "
                        "invariant or an authoritative-practice reference")
    return problems


def _p8(value):
    axes = sorted(a["axis"] for a in value["attacks"])
    if axes != sorted(AXES):
        return [f"P8 needs one attack on each of {list(AXES)}; found {axes}"]
    return []


def _method_ladder(value):
    try:
        from ravel.workflow import method_selection
        problems = method_selection.validate_method_decision(value)
    except ImportError as exc:
        return [f"method ladder cannot be validated here ({exc}); escalation stays refused"]
    except (ValueError, TypeError, KeyError) as exc:
        return [f"method ladder is invalid: {exc}"]
    return [f"method ladder: {p}" for p in problems]


def _recovery(value):
    if not value["local_diagnosis"]["evidence"]:
        return ["recovery needs local diagnosis evidence"]
    return []


SEMANTIC = {"P1": _p1, "P2": _p2, "P3": _p3, "P4": _p4, "P5": _p5, "P6": _p6, "P7": _p7, "P8": _p8,
            "method_ladder": _method_ladder, "recovery": _recovery}


def check(evidence_id: str, value) -> list[str]:
    """Schema and semantic problems of one evidence object."""
    if evidence_id == "method_ladder":
        if type(value) is not dict:
            return ["method ladder evidence must be an object"]
        return _method_ladder(value)
    problems = schemas.protocol_errors(evidence_id, value)
    if problems:
        return [f"{evidence_id} {p}" for p in problems]
    return SEMANTIC[evidence_id](value)


def check_required(trigger_names, evidence: dict) -> list[str]:
    """Problems of ``evidence`` for the named triggers: every required id present and valid."""
    if type(evidence) is not dict:
        return ["protocol evidence must be an object keyed by protocol"]
    try:
        needed = required(trigger_names)
    except ValueError as exc:
        return [str(exc)]
    problems = []
    for evidence_id in needed:
        if evidence_id not in evidence:
            problems.append(f"missing {evidence_id} evidence required by the call's triggers")
    for evidence_id, value in sorted(evidence.items()):
        problems.extend(check(evidence_id, value))
    return problems


def check_attacks(document, *, plan_sha256: str, draft_sha256: str) -> list[str]:
    """Problems of a judgment-attacks.v1 document for this plan and draft (JR09).

    Exactly three attacks, one on each of basis, acceptance and statistics, each with its
    test, outcome and evidence, naming the exact plan and drafted result they attack.
    """
    problems = schemas.errors("judgment-attacks.v1", document)
    if problems:
        return problems
    problems = check("P8", {"attacks": document["attacks"]})
    if document["subject"] != {"plan_sha256": plan_sha256, "draft_sha256": draft_sha256}:
        problems.append("the attacks name a different plan or draft")
    return problems
