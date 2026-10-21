"""The command policy: state-writing commands are refused for controller-owned runs (CONTROLLER-SPEC 3.6).

``check(argv)`` runs before any command dispatch (``cli._ordinary_main``, before the focused
commands and the argument parser) and returns a refusal reason, or None. A command is in scope
when one of its arguments or option values, or the working directory, lies in a controller-owned
run directory or a run's store (``store.controller_owned``: symlink aliases, copies and paths
inside the run count). For such a command:

1. the controller's own entries pass (``ask``, ``operator``, ``drive --request-file``,
   ``drive --resume``, ``status --run``);
2. the rows of ``refused`` are refused with their switch id (SW01-SW05, SW11, SW13): approvals,
   responses, steering, the legacy lifecycle, ``--clear-stop``, run registration, graph control,
   work orders, review submission, transport qualification and result writers;
3. the rows of ``read_only`` pass (``status`` without ``--write``, ``doctor``, ``knowledge``,
   ``modes``, ``validate`` and the listed read-only subcommands);
4. every other command is refused (switch SW13): hidden or unreleased focused commands included.

An abbreviated long option counts as every option it could expand to (the argument parser accepts
an unambiguous prefix, so ``--wri`` is ``--write``) in the refused and read-only rows; a controller
entry is recognised by its exact option only. ``refusal(argv)`` returns the refusal with its switch
id for tests and case bindings; the text shown to the user names the run and the way forward.

Commands that touch no controller-owned run are unaffected: the 1.1.0 commands keep working on
legacy runs, whose results the controller labels NOT GOVERNED. Module entry points that write run
state call ``check([<pseudo-command>, *argv])`` with the pseudo-commands the table names
(``workflow_state``, ``gate_wiring``, ``active_run``, ``graph_substrate``, ``lifecycle``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import DATA

POLICY = DATA / "command_policy.json"
HELP = ("-h", "--help", "--version")
_CACHE: dict = {}


def policy():
    if "policy" not in _CACHE:
        document = json.loads(POLICY.read_text(encoding="utf-8"))
        if document.get("kind") != "controller-command-policy" or document.get("schema_version") != 1:
            raise ValueError("the controller command policy is malformed")
        _CACHE["policy"] = document
    return _CACHE["policy"]


def _options(arguments):
    """``(flags, values)``: option names (``--x``, including ``--x=v``) and every candidate value."""
    flags, values = set(), []
    for argument in arguments:
        if type(argument) is not str:
            continue
        if argument.startswith("--"):
            name, sep, value = argument.partition("=")
            flags.add(name)
            if sep:
                values.append(value)
        elif argument.startswith("-") and len(argument) == 2:
            flags.add(argument)
        else:
            values.append(argument)
    return flags, values


def _pathlike(value):
    if not value or "\n" in value or len(value) > 4096:
        return False
    if value.startswith(("/", "./", "../", "~")) or value in (".", "..") or os.sep in value:
        return True
    try:
        return Path(value).exists()
    except (OSError, ValueError):
        return False


def _owner(path):
    """The owning run id, or a fail-closed label when the directory's controller marker is damaged."""
    from . import store
    try:
        return store.controller_owned(path)
    except getattr(store, "StoreError", ValueError):
        return "unknown (damaged controller-run marker)"


def targets(argv, *, cwd=None):
    """``[(argument, run id)]`` for every argument, option value or working directory in a controller run."""
    controller_owned = _owner
    found = []
    _, values = _options(argv[1:])
    for value in values:
        if _pathlike(value):
            owner = controller_owned(Path(value).expanduser() if Path(value).expanduser().is_absolute()
                                     else Path(cwd or os.getcwd()) / Path(value).expanduser())
            if owner:
                found.append((value, owner))
    try:
        here = Path(cwd) if cwd is not None else Path(os.getcwd())
    except OSError:
        here = None
    if here is not None:
        owner = controller_owned(here)
        if owner:
            found.append((str(here), owner))
    return found


def _subcommand(arguments):
    return next((a for a in arguments if type(a) is str and not a.startswith("-")), None)


def _hits(flags, names, prefix):
    """Whether ``flags`` name any of ``names``; with ``prefix``, an abbreviation (``--wri``) names ``--write``."""
    names = set(names)
    if flags & names:
        return True
    return prefix and any(f.startswith("--") and len(f) > 2 and n.startswith(f) for f in flags for n in names)


def _matches(row, command, arguments, flags, *, prefix=True):
    if "command" in row and row["command"] != command:
        return False
    if "subcommands" in row and _subcommand(arguments) not in row["subcommands"]:
        return False
    if "flags" in row and not _hits(flags, row["flags"], prefix):
        return False
    if "flag" in row and not _hits(flags, [row["flag"]], prefix):
        return False
    if "unless_flags" in row and _hits(flags, row["unless_flags"], prefix):
        return False
    return True


def refusal(argv: list[str]) -> dict | None:
    """``{reason, switch, run_id, where, command}`` when ``argv`` targets a controller-owned run with a
    command it may not run; else None."""
    argv = [a for a in (argv or []) if type(a) is str]
    if not argv or argv[0] in HELP:
        return None
    command, arguments = argv[0], argv[1:]
    flags, _ = _options(arguments)
    if flags & set(HELP):
        return None
    table = policy()
    for row in table["controller_entries"]:
        if _matches(row, command, arguments, flags, prefix=False):
            return None
    hits = targets(argv)
    if not hits:
        return None
    where, run_id = hits[0]
    for row in table["refused"]:
        if _matches(row, command, arguments, flags):
            return _refusal(command, run_id, where, row)
    for row in table["read_only"]:
        if _matches(row, command, arguments, flags):
            return None
    return _refusal(command, run_id, where, table["default"])


def check(argv: list[str]) -> str | None:
    """A refusal reason when ``argv`` targets a controller-owned run with a command it may not run; else None."""
    found = refusal(argv)
    return found["reason"] if found else None


def _refusal(command, run_id, where, row):
    reason = (f"`ravel {command}` is refused for the controller-owned run {run_id} ({where}): {row['reason']}. "
              f"Read it with `ravel status --run {run_id}`; continue it with `ravel drive --resume {run_id}`; "
              "operator actions use `ravel operator`.")
    return {"reason": reason, "switch": row["switch"], "run_id": run_id, "where": where, "command": command}


def require(argv):
    """Raise ``PermissionError`` with the refusal reason (for module entry points); returns None otherwise."""
    reason = check(argv)
    if reason:
        raise PermissionError(reason)
