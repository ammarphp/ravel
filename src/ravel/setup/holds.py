"""Holds that the toolchain manifest records for requests a tool cannot serve yet.

MadLoop (CutTools, Ninja and COLLIER inside MadGraph) failed at link and run time in its only live
attempt. A loop-induced or NLO loop generation request is therefore held with that reason, at
planning time, instead of failing at link time inside MadGraph.
"""
from __future__ import annotations

import re

from . import manifest as mf

_NLO = re.compile(r"\[\s*(?:(?:virt|real|LOonly|sqrvirt)\s*=\s*)?(?:QCD|QED|all)\b[^\]]*\]", re.I)
_LOOP_INDUCED = re.compile(r"\[\s*noborn\b[^\]]*\]|\bloop[-_ ]induced\b", re.I)


def request_classes(text):
    """The held request classes a process line or request text falls into (possibly empty)."""
    text = str(text or "")
    classes = []
    if _LOOP_INDUCED.search(text):
        classes.append("loop-induced")
    if _NLO.search(text):
        classes.append("nlo-loop")
    return classes


def loop_request_hold(text, manifest=None, repo=None):
    """A hold record for a loop-induced or NLO loop request, or None when the request needs no MadLoop."""
    classes = request_classes(text)
    if not classes:
        return None
    manifest = manifest or mf.load(repo or mf.repo_root())[0]
    declared = mf.by_id(manifest).get("madloop")
    if declared is None:
        # A toolchain without the group cannot serve the request either.
        return {"status": "held", "group": "madloop", "request_classes": classes, "qualification": None,
                "reason": "this toolchain does not declare the madloop group that serves loop requests"}
    group = declared["hold"]
    held = [c for c in classes if c in group["request_classes"]]
    if not held:
        return None
    return {"status": "held", "group": "madloop", "request_classes": held, "qualification": group["status"],
            "reason": group["reason"]}
