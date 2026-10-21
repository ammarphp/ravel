"""Legacy run layouts: inspectable, never a place for new governed science (L01, SW26).

A run directory the controller did not create keeps working with the legacy commands, whose
outputs carry ``NOT GOVERNED`` (CONTROLLER-SPEC 3.6); ``decision_gate`` keeps its epoch-one
decisions for those commands. The controller itself never adopts such a directory for new work:

- **epoch one**: the contract sits at the run root (``task_contract.json``) with no
  ``inputs/task_contract.json`` copy, or the contract declares no agent-layer epoch two. The
  decision gate treats this layout as predating the agent layer and lets 11 of its 13 gates pass.
- **epoch two (1.x)**: an ``inputs/task_contract.json`` run written by the 1.x lifecycle, not by
  the controller.

Both are inspectable (``inspect`` reads, never writes) and the ``legacy`` route answers questions
about them with read-only steps. A controller-owned run that presents an epoch-one layout (a
run-root contract, a missing or non-epoch-two ``inputs`` contract) has been downgraded from
outside the controller: it is refused for resume and for every further scientific step.

``check`` classifies a directory; ``admit_new_run``, ``resume_errors`` and ``classify_supplied``
are the entry, resume and supplied-input questions the controller asks of it.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

ROUTE_ID = "legacy"
NOT_GOVERNED = "NOT GOVERNED"
ROOT_CONTRACT = "task_contract.json"
INPUTS_CONTRACT = "inputs/task_contract.json"
LAYOUTS = ("absent", "empty", "controller", "controller-downgraded", "epoch-one", "epoch-two", "unrecognised")
LEGACY_LAYOUTS = ("epoch-one", "epoch-two")
# Supplied-input kinds a run directory is reclassified to (the route view reads ``supplied_kinds``).
SUPPLIED_KINDS = {"epoch-one": "legacy-run", "epoch-two": "legacy-run", "controller": "controller-run",
                  "controller-downgraded": "controller-run"}
# Run files whose presence makes a directory without a contract a run-like tree (inspected, never adopted).
RUN_FILES = ("request.txt", "current_state.json", "RESULT.md", "DEVIATIONS.md", "inputs", "framework")
READ_LIMIT = 4 * 1024 * 1024


def _owner_function():
    """The controller's run-ownership question; an install without the controller owns no run."""
    try:
        from ...store import controller_owned
    except ModuleNotFoundError as exc:
        if exc.name != __name__.rsplit(".", 2)[0] + ".store":
            raise  # a broken store module never reads as "no run is owned"
        return lambda run_dir: None
    return controller_owned


def _exists(path):
    return os.path.lexists(path)


def _read_contract(path):
    """``(contract | None, sha256 | None, problem | None)``: a bounded, non-following read."""
    try:
        if path.is_symlink():
            return None, None, f"{path.name} is a symbolic link"
        if not path.is_file():
            return None, None, f"{path.name} is not a regular file"
        if path.stat().st_size > READ_LIMIT:
            return None, None, f"{path.name} exceeds {READ_LIMIT} bytes"
        raw = path.read_bytes()
    except OSError as exc:
        return None, None, f"{path.name} is unreadable: {exc.strerror or exc}"
    digest = hashlib.sha256(raw).hexdigest()
    try:
        value = json.loads(raw)
    except ValueError:
        return None, digest, f"{path.name} is not JSON"
    if type(value) is not dict:
        return None, digest, f"{path.name} is not a JSON object"
    return value, digest, None


def _epoch(contract):
    value = contract.get("agent_layer_epoch", 1)
    return value if type(value) is int else None


def _reason(code, message):
    return {"code": code, "message": message}


def check(run_dir, *, owner=None) -> dict:
    """Classify ``run_dir`` (read only): its layout, ownership and what the controller may do there.

    ``owner`` is the ownership question (default ``ravel.controller.store.controller_owned``).
    The result is JSON-safe; ``new_science`` is true only for a controller run whose layout is
    intact and for a directory that does not exist yet (the controller creates it).
    """
    owned = owner or _owner_function()
    raw = Path(run_dir).expanduser()
    path = Path(os.path.abspath(raw))
    view = {"schema_version": 1, "kind": "legacy-layout", "path": str(path), "layout": None, "controller_run": None,
            "legacy": False, "inspectable": False, "new_science": False, "governance": None, "reasons": [],
            "evidence": {"contract": None, "contract_sha256": None, "agent_layer_epoch": None,
                         "root_contract": False, "inputs_contract": False}}
    if not _exists(path):
        view.update(layout="absent", new_science=True)
        return view
    if path.is_symlink() and path.is_dir():
        # An alias is classified as the directory it reaches (ownership resolves links the same way).
        view["evidence"]["alias_of"] = os.path.realpath(path)
        path = Path(view["evidence"]["alias_of"])
    if path.is_symlink() or not path.is_dir():
        view.update(layout="unrecognised", inspectable=False)
        view["reasons"].append(_reason("not_a_directory", f"{path} is not a run directory"))
        return view
    try:
        run_id = owned(path)
    except Exception as exc:  # an ownership question that cannot be answered never yields the weaker answer
        view.update(layout="unrecognised", inspectable=True)
        view["reasons"].append(_reason("ownership_unknown", f"run ownership cannot be established: {exc}"[:500]))
        return view
    root_present, inputs_present = _exists(path / ROOT_CONTRACT), _exists(path / INPUTS_CONTRACT)
    view["evidence"].update(root_contract=root_present, inputs_contract=inputs_present)
    contract, digest, problem, where = None, None, None, None
    if inputs_present:
        where = INPUTS_CONTRACT
    elif root_present:
        where = ROOT_CONTRACT
    if where:
        contract, digest, problem = _read_contract(path / where)
        view["evidence"].update(contract=where, contract_sha256=digest,
                                agent_layer_epoch=_epoch(contract) if contract is not None else None)
    view["inspectable"] = True
    if type(run_id) is str and run_id:
        view["controller_run"] = run_id
        view["governance"] = "controller"
        downgrade = []
        if root_present:
            downgrade.append(_reason("run_root_contract", "a task_contract.json at the run root makes the decision "
                                     "gate read the run as epoch one; the controller writes only inputs/"))
        if where == INPUTS_CONTRACT:
            if problem:
                downgrade.append(_reason("contract_unreadable", problem))
            elif _epoch(contract) != 2:
                downgrade.append(_reason("contract_not_epoch_two", "inputs/task_contract.json does not declare "
                                         "agent_layer_epoch 2"))
        elif root_present:
            downgrade.append(_reason("inputs_contract_missing", "inputs/task_contract.json is absent while a "
                                     "run-root contract exists (the epoch-one layout)"))
        if downgrade:
            view.update(layout="controller-downgraded", legacy=True, new_science=False)
            view["reasons"] = downgrade + [_reason("downgraded", f"controller run {run_id} presents a legacy layout "
                                                   "written outside the controller; it is refused, not resumed")]
        else:
            view.update(layout="controller", new_science=True)
        return view
    if run_id is not None:
        view.update(layout="unrecognised")
        view["reasons"].append(_reason("ownership_unknown", f"the ownership answer {run_id!r} is not a run id"))
        return view
    view["governance"] = NOT_GOVERNED
    if where is None:
        try:
            entries = [entry.name for entry in os.scandir(path)]
        except OSError as exc:
            view["reasons"].append(_reason("unreadable", f"{path} cannot be listed: {exc.strerror or exc}"))
            view.update(layout="unrecognised", governance=None)
            return view
        if not entries:
            view.update(layout="empty", governance=None)
            view["reasons"].append(_reason("existing_directory", "the controller creates its own run directory; "
                                           "an existing directory is never adopted"))
            return view
        view.update(layout="unrecognised", governance=None)
        found = sorted(set(entries) & set(RUN_FILES))
        view["reasons"].append(_reason("no_contract", "no task contract in this directory" +
                                       (f" (run files present: {', '.join(found)})" if found else "")))
        return view
    if where == ROOT_CONTRACT or problem or _epoch(contract) != 2:
        layout = "epoch-one"
        why = ("the contract sits at the run root without an inputs/ copy" if where == ROOT_CONTRACT
               else problem or "inputs/task_contract.json does not declare agent_layer_epoch 2")
        if where == ROOT_CONTRACT and contract is not None and _epoch(contract) not in (None, 1):
            why += "; a run-root contract cannot declare a later epoch"
        view["reasons"].append(_reason("epoch_one_layout", why))
    else:
        layout = "epoch-two"
        view["reasons"].append(_reason("not_controller_owned", "an epoch-two run the 1.x lifecycle wrote; the "
                                       "controller does not own it"))
    view.update(layout=layout, legacy=True)
    view["reasons"].append(_reason("legacy_inspection_only", "inspectable; new governed science is refused here; "
                                   "legacy commands still run it with NOT GOVERNED results"))
    return view


def admit_new_run(run_dir, *, owner=None) -> str | None:
    """The refusal when the controller would start new work in ``run_dir``; None for a new directory."""
    view = check(run_dir, owner=owner)
    layout = view["layout"]
    if layout == "absent":
        return None
    if layout in LEGACY_LAYOUTS:
        return (f"{view['path']} is a legacy {layout} run: it is inspectable, but new science is refused in a "
                "legacy layout (legacy commands still run it, NOT GOVERNED); start a governed run in a new "
                "directory and supply this run as an input to read it")
    if layout == "controller":
        return (f"{view['path']} belongs to controller run {view['controller_run']}; continue it with "
                f"`ravel drive --resume {view['controller_run']}`")
    if layout == "controller-downgraded":
        return (f"{view['path']} is controller run {view['controller_run']} with a legacy layout written outside "
                "the controller: " + "; ".join(r["message"] for r in view["reasons"]))
    return f"{view['path']} exists; the controller creates its own run directory (" + \
        "; ".join(r["message"] for r in view["reasons"]) + ")"


def resume_errors(run_dir, run_id, *, owner=None) -> list[str]:
    """Why ``run_id`` may not continue in ``run_dir``: its layout must be the controller's own, intact."""
    view = check(run_dir, owner=owner)
    if view["layout"] == "controller" and view["controller_run"] == run_id:
        return []
    if view["layout"] == "controller":
        return [f"{view['path']} belongs to controller run {view['controller_run']}, not {run_id}"]
    if view["layout"] == "controller-downgraded":
        return [f"run {run_id} presents a legacy layout written outside the controller (SW26): " +
                "; ".join(r["message"] for r in view["reasons"][:-1])]
    if view["layout"] in LEGACY_LAYOUTS:
        return [f"{view['path']} is a legacy {view['layout']} run, not controller run {run_id}"]
    return [f"{view['path']} is not controller run {run_id} ({view['layout']})"]


def governed_errors(run_dir, run_id, *, owner=None) -> list[str]:
    """The same test for every further scientific step of a controller run (a downgrade mid-run holds it)."""
    return resume_errors(run_dir, run_id, owner=owner)


def classify_supplied(supplied, *, owner=None) -> list[dict]:
    """Supplied inputs with run directories reclassified (``legacy-run``, ``controller-run``) and labelled.

    A legacy run supplied as an input stays readable; its results carry ``NOT GOVERNED`` so no
    later step reports them as governed evidence. The input rows are copied, never changed.
    """
    rows = []
    for row in supplied or ():
        row = deepcopy(row)
        path = row.get("path") if type(row) is dict else None
        if type(path) is str and path and row.get("kind") in (None, "directory", "run") and Path(path).is_dir():
            view = check(path, owner=owner)
            kind = SUPPLIED_KINDS.get(view["layout"])
            if kind:
                row.update(kind=kind, layout=view["layout"], governance=view["governance"]
                           if view["layout"] == "controller" else NOT_GOVERNED)
                if view["controller_run"]:
                    row["controller_run"] = view["controller_run"]
        rows.append(row)
    return rows


def inspect(run_dir, *, owner=None, limit=200) -> dict:
    """A read-only description of a run directory for an inspection step (writes nothing).

    The layout (with the contract's path and digest), the governance label and the top-level
    entries with their sizes; a legacy run's description is labelled ``NOT GOVERNED``. Contract
    labels are not read: the inspecting step reads the contract file itself.
    """
    view = check(run_dir, owner=owner)
    path = Path(view["path"])
    described = {"layout": deepcopy(view), "label": NOT_GOVERNED if view["legacy"] else view["governance"],
                 "entries": [], "truncated": False}
    if not view["inspectable"]:
        return described
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name)
    except OSError:
        return described
    for entry in entries[:limit]:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        kind = "link" if entry.is_symlink() else "directory" if entry.is_dir(follow_symlinks=False) else "file"
        described["entries"].append({"name": entry.name, "kind": kind,
                                     "size": info.st_size if kind == "file" else None})
    described["truncated"] = len(entries) > limit
    return described
