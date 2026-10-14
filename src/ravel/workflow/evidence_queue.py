"""Typed work items from decision-justification requests (RDJ §5.8).

An unresolved branch, a blocking edge review or a critic finding can carry a
request. Each request becomes one work item that names its case and target:

- ``evidence`` goes to an investigation worker;
- ``experiment`` goes to the research cycle or a correction proposal;
- ``requirement_clarification`` becomes a question at the next CHECK-IN.

Items live at ``<rundir>/rdj/queue/<item_id>.json``. Enqueueing the same request
for the same target in the same revision round returns the existing item; a later
round opens a new item. An item closes as ``done`` only with pins that verify. A critic's
discriminating test closes with a ``verdict``: ``upholds`` (the test failed the claim, so
the finding stands) or ``refutes``. Consumers re-verify the pins (``rdj_loop``): this
file is run-writable and its status alone proves nothing.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .decision_case import REQUEST_KINDS, jdigest, request_v2
from .state_io import atomic_json, file_lock, read_json

KIND = "rdj-evidence-item"
ROUTES = {"evidence": "investigation_worker", "experiment": "research_cycle",
          "requirement_clarification": "checkin_question"}
STATUSES = ("open", "done", "withdrawn")
VERDICTS = ("upholds", "refutes")
SOURCES = ("unresolved_branch", "edge_review", "critic_finding", "node_unknown")
ITEM_ID = re.compile(r"q-[0-9a-f]{16}")


def _dir(rundir):
    return Path(rundir) / "rdj" / "queue"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def enqueue(rundir, case_id, *, source, target, request, round_=0):
    """Create (or return) the work item for ``request`` on ``target`` in ``case_id`` at revision ``round_``."""
    request_v2(request)
    if request is None or request["kind"] not in REQUEST_KINDS:
        raise ValueError("a work item needs a typed request")
    if source not in SOURCES:
        raise ValueError(f"work item source must be one of {SOURCES}")
    if type(round_) is not int or round_ < 0:
        raise ValueError("work item round must be a nonnegative integer")
    key = {"case_id": case_id, "target": target, "request": request}
    item_id = "q-" + jdigest(key if round_ == 0 else {**key, "round": round_})[:16]
    directory = _dir(rundir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (item_id + ".json")
    with file_lock(directory / "queue.lock"):
        if path.exists():
            return read_json(path)
        item = {"schema_version": 1, "kind": KIND, "item_id": item_id, "case_id": case_id,
                "case": {"path": f"rdj/cases/{case_id}.json"}, "source": source, "target": target,
                "request": dict(request), "route": ROUTES[request["kind"]], "status": "open", "round": round_,
                "created_utc": _now(), "resolution": None}
        atomic_json(path, item)
        return item


def items(rundir, *, case_id=None, status=None, route=None):
    directory = _dir(rundir)
    rows = []
    for path in sorted(directory.glob("q-*.json")) if directory.is_dir() else ():
        item = read_json(path)
        if item.get("schema_version") != 1 or item.get("kind") != KIND:
            raise ValueError(f"unknown evidence item record: {path.name}")
        if (case_id is None or item["case_id"] == case_id) and (status is None or item["status"] == status) \
                and (route is None or item["route"] == route):
            rows.append(item)
    return rows


def resolve(rundir, item_id, *, status, note, pins=(), verdict=None):
    """Close an item as ``done`` (with the receipts that answer it and, for a requested test,
    its ``verdict`` on the finding) or ``withdrawn``."""
    if status not in ("done", "withdrawn"):
        raise ValueError("an item resolves as done or withdrawn")
    if verdict is not None and (status != "done" or verdict not in VERDICTS):
        raise ValueError(f"a test verdict is one of {VERDICTS}, given only when the item is done")
    if not isinstance(note, str) or not note.strip():
        raise ValueError("resolution needs a note")
    if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id):
        raise ValueError("unknown work item id")
    pins = [dict(p) for p in pins]
    if status == "done":
        if not pins:
            raise ValueError("a done item names the pins that answer it")
        root = Path(rundir).resolve()
        for pin in pins:
            path = (root / pin["path"]).resolve()
            if set(pin) != {"path", "sha256"} or not path.is_relative_to(root) or not path.is_file() \
                    or hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]:
                raise ValueError(f"resolution pin does not verify: {pin.get('path')}")
    directory = _dir(rundir)
    path = directory / (item_id + ".json")
    with file_lock(directory / "queue.lock"):
        item = read_json(path)
        if item["status"] != "open":
            raise ValueError("item is already resolved")
        item["status"] = status
        item["resolution"] = {"note": note.strip(), "pins": pins, "resolved_utc": _now(),
                              **({"verdict": verdict} if verdict else {})}
        atomic_json(path, item)
        return item
