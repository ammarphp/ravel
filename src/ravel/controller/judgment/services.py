"""The judgment graph's only door to the rest of the controller.

Every collaborator is reached through the binding interfaces of the 1.3.0 controller build:
the run store (``ravel.controller.store.RunStore``), the governed step
(``ravel.controller.step.run``), the obligation ledger (``ravel.controller.ledger``), the
authority service (``ravel.controller.authority``) and the sole sink
(``ravel.controller.sink``). They are imported when first used; an absent component is a
typed hold, never a silent pass. ``capability_routing.catalogue`` supplies the operation
catalogue. The controller clock is ``time.time``; no environment variable sets it.

The shapes read here are the collaborators' published ones: store records come back as
envelopes ``{id, kind, seq, record, ...}``; a step outcome has ``status`` (completed, failed,
held, escalated, budget_exhausted, stopped), ``outputs`` (``{artifact, path, sha256}``, adopted
under ``steps/<step id>/<path>`` of the run directory), ``review`` and ``escalation``; an
authority answer is an ``authority-record.v1`` with ``decision`` and ``option``, or
``{"pending": {...}}``.

Tests replace collaborators in process with ``overridden(...)``, which is refused unless the
controller test harness enabled seams in this process (``ravel.controller.testing``). Nothing
outside the process can reach it.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import stat
import time

NAMES = ("open_store", "step_run", "ledger_materialise", "ledger_record", "ledger_gate", "ledger_pending", "plan_bind",
         "authority_request", "authority_verify", "authority_capture", "authority_disposition", "stop_state",
         "operator_config", "sink_deliver", "sink_bounded_end", "catalogue",
         "route_specs", "roles", "recovery_hints", "now", "sleep")
_OVERRIDES: ContextVar[dict | None] = ContextVar("ravel_judgment_services", default=None)
_LOCAL_SEAMS = {"enabled": False}
SUCCESS = ("completed", "adopted", "ok", "satisfied", "done")
HELD = ("held", "hold", "pending", "waiting", "blocked", "escalated")
STOPPED = ("stopped", "stop_requested", "draining", "drained", "paused")
EXHAUSTED = ("budget_exhausted", "exhausted", "ceiling_exceeded")
ESCALATIONS = ("stop", "checkin_flag", "decision_block", "new_experiment_required", "ask", "route")
GRANTING = ("approve", "approved", "answer", "accept", "go", "authorize", "authorized", "granted")
DECLINING = ("reject", "rejected", "decline", "declined", "deny", "denied", "refuse", "refused", "adjust", "rework",
             "revise", "stop", "hold", "held", "no")


class ComponentAbsent(Exception):
    """A controller component this graph needs is not installed (a typed hold)."""
    not_dispatched = True

    def __init__(self, component, cause):
        super().__init__(f"controller component {component} is not installed: {cause}")
        self.component = component
        self.reason = "controller_component_absent"
        self.would_make_possible = f"install ravel.controller.{component}"


def seams_enabled() -> bool:
    """True only when the test harness enabled controller seams in this process."""
    try:
        testing = import_module("ravel.controller.testing")
    except ImportError:
        return _LOCAL_SEAMS["enabled"]
    probe = getattr(testing, "seams_enabled", None)
    return bool(probe()) if callable(probe) else _LOCAL_SEAMS["enabled"]


def enable_local_seams():
    """In-process seam switch for this package's tests while the controller harness is absent."""
    _LOCAL_SEAMS["enabled"] = True


@contextmanager
def overridden(**functions):
    if not seams_enabled():
        raise RuntimeError("controller test seams are not enabled in this process")
    unknown = sorted(set(functions) - set(NAMES))
    if unknown:
        raise ValueError(f"unknown judgment services {unknown}")
    token = _OVERRIDES.set({**(_OVERRIDES.get() or {}), **functions})
    try:
        yield
    finally:
        _OVERRIDES.reset(token)


def call(name, *args, **kwargs):
    """The collaborator ``name``: an override installed under enabled seams, else the installed component."""
    function = (_OVERRIDES.get() or {}).get(name)
    if function is not None:
        return function(*args, **kwargs)
    return DEFAULTS[name](*args, **kwargs)


def _component(name):
    try:
        return import_module("ravel.controller." + name)
    except ImportError as exc:
        raise ComponentAbsent(name, exc) from None


def _open_store(run):
    module = _component("store")
    root = run.get("store_root")
    return module.RunStore(run["run_id"], root=Path(root) if root else None)


def _ledger_pending(store, **scope):
    pending = getattr(_component("ledger"), "pending", None)
    return list(pending(store, **scope)) if callable(pending) else []


def _route_specs():
    """Installed route-spec ids (``data/controller/routes/*.json``); the judgment route is not one."""
    from importlib.resources import files
    directory = files("ravel").joinpath("data", "controller", "routes")
    found = set()
    try:
        entries = list(directory.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return found
    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        try:
            document = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = document.get("routes") if isinstance(document, dict) and isinstance(document.get("routes"), list) \
            else [document]
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                found.add(row["id"])
    found.discard("judgment")
    return found


def _roles():
    from ravel.workflow import role_registry
    return {card["id"] for card in role_registry.all_cards()}


_CATALOGUE = {}


def _catalogue():
    """``capability_routing.catalogue()``, read once per process."""
    if "value" not in _CATALOGUE:
        from ravel.workflow import capability_routing
        _CATALOGUE["value"] = capability_routing.catalogue()
    return _CATALOGUE["value"]


DEFAULTS = {
    "open_store": _open_store,
    "step_run": lambda store, step, context: _component("step").run(store, step, context),
    "ledger_materialise": lambda store, stage, context: _component("ledger").materialise(store, stage, context),
    "ledger_record": lambda store, entry_id, status, evidence: _component("ledger").record(store, entry_id, status,
                                                                                          evidence),
    "ledger_gate": lambda store, transition: _component("ledger").gate(store, transition),
    "ledger_pending": _ledger_pending,
    "plan_bind": lambda store, plan, **options: _component("step.binding").record_plan_rows(
        store, plan, ledger=_component("ledger"), **options),
    "authority_request": lambda store, kind, subject, bounds: _component("authority").request(store, kind, subject,
                                                                                              bounds),
    "authority_verify": lambda store, record_id, **scope: _component("authority").verify(store, record_id, **scope),
    "authority_capture": lambda store, kind, **sources: _component("authority.retained").capture(store, kind,
                                                                                             **sources),
    "authority_disposition": lambda store, record_id, **scope: _component("authority").disposition(store, record_id,
                                                                                                   **scope),
    "stop_state": lambda store: _component("authority").stop_state(store),
    "operator_config": lambda: _component("authority").operator_config(),
    "sink_deliver": lambda store, plan: _component("sink").deliver(store, plan),
    "sink_bounded_end": lambda store, reason: _component("sink").bounded_end(store, reason),
    "catalogue": _catalogue,
    "route_specs": _route_specs,
    "roles": _roles,
    "recovery_hints": lambda prompt, contract, reading: import_module(
        "ravel.controller.judgment.recovery").hints(prompt, contract, reading),
    "now": time.time,
    "sleep": time.sleep,
}


# ---- store records ------------------------------------------------------------------------------

def unwrap(entry):
    """``(id, record)`` of a store row: an envelope ``{id, kind, seq, record}`` or a bare record."""
    if type(entry) is dict and type(entry.get("record")) is dict and "seq" in entry and "kind" in entry:
        return entry.get("id"), entry["record"]
    return (entry.get("id") if type(entry) is dict else None), entry


def records(store, kind) -> list[tuple]:
    """``[(id, record)]`` of one kind, in append order."""
    return [unwrap(entry) for entry in store.scan(kind)]


def record(store, kind, record_id) -> dict:
    return unwrap(store.read(kind, record_id))[1]


def blob_json(store, digest):
    """A JSON blob of the store, verified by the store against its digest."""
    return json.loads(store.get_blob(digest).decode("utf-8"))


# ---- normalised views of collaborator results ---------------------------------------------------

VERDICTS = {"pass": ("pass", "accept", "accepted", "approve", "approved", "ok", "credited", "passed"),
            "revise": ("revise", "send_back", "sent_back", "needs_revision", "revision", "rework"),
            "fail": ("fail", "failed", "reject", "rejected", "refuse", "refused")}


def normalize_verdict(value) -> str:
    """pass, revise or fail; anything unrecognised is fail."""
    text = str(value or "").lower()
    for verdict, spellings in VERDICTS.items():
        if text in spellings:
            return verdict
    return "fail"


def normalize_outcome(outcome) -> dict:
    """One shape for a governed step outcome.

    status: adopted | held | stopped | exhausted | failed. Outputs keep artifact, path and sha256.
    """
    if type(outcome) is not dict:
        return {"status": "failed", "raw_status": None, "reason": "the governed step returned no outcome",
                "step_id": None, "outputs": [], "credited": False, "verdict": None, "escalation": None,
                "receipts": [], "judgments": [], "tier": None, "request": None}
    raw = str(outcome.get("status") or "").lower()
    status = ("adopted" if raw in SUCCESS else "held" if raw in HELD else "stopped" if raw in STOPPED
              else "exhausted" if raw in EXHAUSTED else "failed")
    outputs = []
    for row in outcome.get("outputs") or []:
        if type(row) is dict and type(row.get("path")) is str:
            outputs.append({"artifact": row.get("artifact"), "path": row["path"], "sha256": row.get("sha256")})
    review = outcome.get("review") if type(outcome.get("review")) is dict else {}
    escalation = outcome.get("escalation")
    if type(escalation) is dict:
        escalation = escalation.get("kind") or escalation.get("value")
    model = outcome.get("model") if type(outcome.get("model")) is dict else {}
    return {"status": status, "raw_status": raw or None, "reason": outcome.get("reason"),
            "step_id": outcome.get("step_id"), "outputs": outputs, "credited": review.get("credited") is True,
            "verdict": review.get("verdict"), "escalation": escalation if escalation in ESCALATIONS or escalation
            is None else "stop", "receipts": list(outcome.get("receipts") or []),
            "judgments": list(outcome.get("judgments") or []), "tier": outcome.get("tier") or model.get("tier"),
            "request": deepcopy(outcome.get("request"))}


def normalize_authority(result, *, store=None, kind=None, subject=None) -> dict:
    """Normalize an answer; granting states require current, verified effect authority.

    A decision word or an unattested terminal response is evidence of an answer only.
    Verification reads the retained record for this run, kind and current subject pins;
    its returned bytes supply the chosen option and label. A final acceptance is never a
    grant: it becomes ``accepted`` only as an authenticated current disposition.
    """
    if type(result) is not dict:
        return {"state": "declined", "record_id": None, "label": None, "answer": None, "since": None,
                "wait_bound": None, "detail": "the authority service returned no record"}
    if "pending" in result:
        pending = result["pending"] if type(result["pending"]) is dict else {}
        since = pending.get("since_ns")
        return {"state": "pending", "record_id": None, "label": pending.get("label"), "answer": None,
                "since": since / 1e9 if type(since) in (int, float) else pending.get("since"),
                "wait_bound": pending.get("wait_bound_seconds", pending.get("wait_bound")),
                "detail": pending.get("status_line") or pending.get("reason") or "waiting for an answer",
                "request": pending.get("request")}
    decision = str(result.get("decision") or "").lower()
    if kind == "final" and decision in GRANTING:
        return _final_disposition(result, store=store, subject=subject)
    if decision in ("default", "defaulted") and result.get("authorizes_effects") is not True:
        return _no_effect_default(result, store=store, kind=kind, subject=subject)
    if decision in GRANTING + ("default", "defaulted"):
        problem = "the answer has no verified effect authorization"
        verified = None
        if result.get("authorizes_effects") is True and store is not None and kind is not None:
            try:
                verified = call("authority_verify", store, result.get("id") or result.get("record_id"),
                                kind=kind, subject=subject)
            except ValueError as exc:
                problem = str(exc)
        if type(verified) is not dict or verified.get("authorizes_effects") is not True:
            return {"state": "pending", "record_id": result.get("id") or result.get("record_id"),
                    "label": result.get("label"), "answer": None, "since": None,
                    "wait_bound": None, "detail": problem}
        result = verified
        decision = str(result.get("decision") or "").lower()
    if decision in ("default", "defaulted"):
        state = "defaulted"
    elif decision in GRANTING:
        state = "granted"
    elif decision in DECLINING or not decision:
        state = "declined"
    else:
        state = "declined"
    return {"state": state, "record_id": result.get("id") or result.get("record_id"), "label": result.get("label"),
            "answer": result.get("option") if result.get("option") is not None else decision or None,
            "since": None, "wait_bound": None, "detail": result.get("comment") or result.get("reason")}


FINAL_ACCEPT = "accept"


def _final_disposition(result, *, store, subject) -> dict:
    """A final acceptance authorizes no effect, so the effect verifier never passes it.

    It counts only as the authenticated, current disposition of this result, read through
    ``authority.disposition`` for the current subject pins: state ``accepted``. The stored
    record's bytes supply the decision and label; anything unauthenticated stays pending.
    """
    record_id = result.get("id") or result.get("record_id")
    problem, found = "the final acceptance has no authenticated current disposition", None
    if store is not None:
        try:
            found = call("authority_disposition", store, record_id, kind="final", subject=subject)
        except ValueError as exc:
            problem = str(exc)
    if type(found) is dict and found.get("authorizes_effects") is False:
        chosen = str(found.get("decision") or "").lower()
        state = "accepted" if chosen == FINAL_ACCEPT else "declined" if chosen in DECLINING else None
        if state is not None:
            return {"state": state, "record_id": found.get("id") or record_id, "label": found.get("label"),
                    "answer": chosen, "since": None, "wait_bound": None,
                    "detail": found.get("comment") or found.get("reason")}
    return {"state": "pending", "record_id": record_id, "label": result.get("label"), "answer": None,
            "since": None, "wait_bound": None, "detail": problem}


def _no_effect_default(result, *, store, kind, subject) -> dict:
    """A conservative default whose option takes no effect (keep held, decline) grants nothing.

    It is ``defaulted`` with the stored option only when ``authority.disposition`` authenticates
    it as the current record for the subject pins; a default that would take an effect goes
    through the effect verifier instead, and anything else stays pending.
    """
    from .control import AUTHORIZE
    record_id = result.get("id") or result.get("record_id")
    problem, found = "the conservative default has no authenticated current record", None
    if store is not None and kind is not None:
        try:
            found = call("authority_disposition", store, record_id, kind=kind, subject=subject)
        except ValueError as exc:
            problem = str(exc)
    if (type(found) is dict and found.get("authorizes_effects") is False
            and str(found.get("decision") or "").lower() in ("default", "defaulted")
            and found.get("option") is not None and found.get("option") != AUTHORIZE):
        return {"state": "defaulted", "record_id": found.get("id") or record_id, "label": found.get("label"),
                "answer": found.get("option"), "since": None, "wait_bound": None,
                "detail": found.get("comment") or found.get("reason")}
    return {"state": "pending", "record_id": record_id, "label": result.get("label"), "answer": None,
            "since": None, "wait_bound": None, "detail": problem}


def _regular_bytes(location):
    try:
        if not stat.S_ISREG(os.lstat(location).st_mode):
            return None, "is not a regular file"
        return location.read_bytes(), None
    except OSError as exc:
        return None, f"cannot be read: {exc.strerror}"


def read_output(run: dict, outcome: dict, *, path: str, step_id: str | None = None):
    """The JSON document of one adopted output, verified by digest; ``(None, reason)`` when absent.

    The governed step adopts a declared output under ``steps/<step id>/<path>`` of the run
    directory; an absolute or run-relative location is accepted as written.
    """
    rows = [o for o in outcome.get("outputs") or [] if o.get("path") == path
            or str(o.get("artifact") or "").endswith(":" + path)]
    if not rows:
        return None, f"no adopted output {path}"
    row = rows[-1]
    owner = step_id or outcome.get("step_id") or str(row.get("artifact") or "").split(":", 1)[0]
    base = Path(run.get("run_dir") or "")
    candidates = [Path(row["path"])] if Path(row["path"]).is_absolute() else []
    if run.get("run_dir"):
        candidates += ([base / "steps" / owner / row["path"]] if owner else []) + [base / row["path"]]
    problem = "the run directory is unknown"
    for location in candidates:
        raw, problem = _regular_bytes(location)
        if raw is None:
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if row.get("sha256") and row["sha256"] != sha:
            return None, f"adopted output {path} differs from its adopted digest"
        try:
            return json.loads(raw), {"path": str(location), "sha256": sha}
        except ValueError:
            return None, f"adopted output {path} is not JSON"
    return None, f"adopted output {path} {problem}"


def read_pin(run: dict, pin) -> tuple[bytes | None, str | None]:
    """Bytes of a run-relative or absolute ``{path, sha256}`` pin, verified."""
    if type(pin) is not dict or type(pin.get("path")) is not str or type(pin.get("sha256")) is not str:
        return None, "pin needs path and sha256"
    location = Path(pin["path"])
    if not location.is_absolute():
        if not run.get("run_dir"):
            return None, "a relative pin needs the run directory"
        location = Path(run["run_dir"]) / location
    raw, problem = _regular_bytes(location)
    if raw is None:
        return None, f"{pin['path']} {problem}"
    if hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        return None, f"{pin['path']} differs from its pinned digest"
    return raw, None
