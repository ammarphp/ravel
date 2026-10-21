"""Consequence classes R0-R3 from code tables, never from model output.

The table is ``data/judgment/consequence-classes.json`` joined with two existing tables
read from the installed package: the RDJ policy's gate and action-kind classes
(``data/rdj/policy.json``) and the research protocol's ``rdj_classes``. Gates are the
decision gates of ``decision_gate.GATES``; ``unblind`` and ``spend_above_ceiling`` are
always R3. A planner or worker may declare a class; it can only raise the computed
one. An unknown action, kind, gate, choice, rung or effect is R3.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import json

CLASSES = ("R0", "R1", "R2", "R3")
RANK = {name: index for index, name in enumerate(CLASSES)}
UNKNOWN = "R3"
FIELDS = ("kind", "gate", "research_choice", "step_kind", "rung")
REQUIREMENTS = {"R0": "record", "R1": "report_at_next_checkin", "R2": "rdj_review", "R3": "authority"}


def _package_json(*parts):
    return json.loads(files("ravel").joinpath("data", *parts).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def tables() -> dict:
    """The joined class tables, read once from the installed package."""
    own = _package_json("judgment", "consequence-classes.json")
    if own.get("schema_version") != 1 or own.get("kind") != "judgment-consequence-classes":
        raise ValueError("judgment consequence-class table has an unexpected schema")
    if tuple(own["classes"]) != CLASSES or own["unknown"] != UNKNOWN or own["requirements"] != REQUIREMENTS:
        raise ValueError("judgment consequence classes must be R0-R3 with unknown at R3 and their requirements")
    rdj = _package_json("rdj", "policy.json")
    research = _package_json("research", "protocol-default.json")
    from ravel.workflow.decision_gate import GATES
    gates = {}
    for gate in GATES:
        row = rdj.get("gates", {}).get(gate)
        cls = row.get("class") if isinstance(row, dict) else None
        gates[gate] = cls if cls in RANK else UNKNOWN
    for gate in own["gates"]["always_r3"]:
        if gate not in GATES:
            raise ValueError(f"always-R3 gate {gate!r} is not a decision gate")
        gates[gate] = "R3"
    kinds = {}
    for source in (rdj.get("action_kinds", {}), own["action_kinds"]):
        for kind, cls in source.items():
            if cls not in RANK:
                raise ValueError(f"action kind {kind!r} has no valid class")
            kinds[kind] = max(kinds.get(kind, "R0"), cls, key=RANK.get)
    choices = {}
    for choice, cls in research.get("rdj_classes", {}).items():
        if cls not in RANK:
            raise ValueError(f"research choice {choice!r} has no valid class")
        choices[choice] = cls
    for name in ("effects", "step_kinds", "rungs"):
        if any(cls not in RANK for cls in own[name].values()):
            raise ValueError(f"judgment {name} table holds an invalid class")
    return {"kind": kinds, "gate": gates, "research_choice": choices, "step_kind": dict(own["step_kinds"]),
            "rung": dict(own["rungs"]), "effects": dict(own["effects"]),
            "requirements": dict(own["requirements"])}


def explain(action) -> dict:
    """The computed class and every factor behind it.

    ``class`` is the effective class: the maximum of the table classes of every
    present field and effect, raised (never lowered) by ``declared_class``. With no
    classifiable field, or any unknown value, the class is R3.
    """
    if type(action) is not dict:
        return {"class": UNKNOWN, "computed": UNKNOWN, "declared": None, "factors": [],
                "unknown": ["action is not an object"], "declared_lower": False}
    table = tables()
    factors, unknown = [], []
    for field in FIELDS:
        if field not in action or action[field] is None:
            continue
        value = action[field]
        cls = table[field].get(value) if type(value) is str else None
        if cls is None:
            unknown.append(f"{field}={value!r}")
        else:
            factors.append({"field": field, "value": value, "class": cls})
    effects = action.get("effects")
    if effects is not None:
        if type(effects) is not list:
            unknown.append("effects is not a list")
        else:
            for effect in effects:
                cls = table["effects"].get(effect) if type(effect) is str else None
                if cls is None:
                    unknown.append(f"effect={effect!r}")
                else:
                    factors.append({"field": "effects", "value": effect, "class": cls})
    declared = action.get("declared_class")
    if declared is not None and declared not in RANK:
        unknown.append(f"declared_class={declared!r}")
        declared = None
    if unknown or not factors:
        computed = UNKNOWN
    else:
        computed = max((f["class"] for f in factors), key=RANK.get)
    effective = computed if declared is None else max(computed, declared, key=RANK.get)
    return {"class": effective, "computed": computed, "declared": declared, "factors": factors,
            "unknown": unknown if factors or unknown else ["no classifiable field"],
            "declared_lower": declared is not None and RANK[declared] < RANK[computed]}


def classify(action: dict) -> str:
    """R0|R1|R2|R3 for ``action`` from the code tables; unknown is R3."""
    return explain(action)["class"]


def requirement(cls: str) -> str:
    """What the controller requires before the effect of a call of class ``cls``."""
    if cls not in RANK:
        raise ValueError("consequence class must be R0-R3")
    return REQUIREMENTS[cls]


def at_least(*classes: str) -> str:
    """The highest of ``classes``; an invalid value counts as R3."""
    return max((c if c in RANK else UNKNOWN for c in classes), key=RANK.get, default="R0")
