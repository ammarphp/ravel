"""The controller's command-line entries: ``ravel drive``, ``ravel ask`` and ``ravel status --run``.

``ravel drive --request-file F [--unattended] [--rundir R] [--input KIND=PATH ...]`` and
``ravel ask TEXT [...]`` start a controller run: the request bytes come only from the user's
argument or file (the operator's or the harness's file when unattended), are stored in the run's
protected store and are the only request the ``controller.run`` graph reads (CT01). No host
interpretation, environment variable or run-directory file can replace them.

``ravel drive --resume RUN_ID`` continues the same run from its store: the same graph thread, the
same budgets, attempts and records. A run whose store does not verify, or whose directory was
copied, moved or replaced, or now shows a layout written outside the controller, is refused (R11,
C41, SW26). A new run never starts in an existing directory; a legacy layout is refused with its
typed reason (L01), and a supplied run directory is classified and labelled.

Before anything is created or appended, ``ravel ask`` and both controller forms of ``ravel drive``
run the confinement package's identity check (``identity.require_governed_install``). Code that is
not governed runs through the current sealed runtime (``ravel governed-runtime seal``) when that
runtime holds the same bytes: the command re-executes itself through the runtime's launcher with
the same arguments and environment. Otherwise it refuses with the typed reason and its fix and
creates no run directory or store.

Every drive first declares this process the controller of the run (the agent tripwire blocks from
then on, SW15) and takes the confinement admission (installed or sealed code identity and the
operator's source policy); both are recorded in the store, where the intake rows they prove are
recorded from.

``ravel drive --rundir R`` (and ``ravel drive respond``) for a run the controller does not own
delegates to the legacy ``lifecycle.drive`` graph unchanged, so no earlier capability is lost; its
output carries the ``NOT GOVERNED`` label. For a controller-owned run those forms are refused by
the command policy.

``ravel status --run RUN_ID`` reads the run's progress from its store and never writes.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import time

from . import NOT_GOVERNED
from .store import RunStore, StoreError, StoreTampered, controller_owned, store_root

GRAPH_ID = "controller.run"
AUTHORITY_SCHEMA = "controller_authority"
POLL_SECONDS = 30.0
MAX_POLL_ROUNDS = 100000
CONTROLLER_FLAGS = ("--request-file", "--resume")
# Supplied-input kinds inferred from a file name when ``--input`` names no kind.
SUFFIX_KINDS = {".lhe": "events", ".lhe.gz": "events", ".hepmc": "events", ".hepmc.gz": "events", ".root": "events",
                ".parquet": "events", ".slha": "model", ".ufo": "model", ".yoda": "measurement",
                ".csv": "measurement", ".yaml": "measurement", ".yml": "measurement"}
NOT_GOVERNED_NOTE = ("this run is not owned by the controller: the legacy lifecycle ran it and its results are "
                     "NOT GOVERNED; start a governed run with `ravel drive --request-file`")


class EntryError(ValueError):
    """The entry refuses the invocation (bad arguments, a missing or misplaced run).

    ``code`` and ``row`` type a refusal an obligation names (``legacy_layout`` for L01).
    """

    def __init__(self, message, *, code=None, row=None):
        super().__init__(message)
        self.code, self.row = code, row


def _controller_form(argv):
    return any(a == flag or a.startswith(flag + "=") for a in argv for flag in CONTROLLER_FLAGS)


# ---- legacy delegation -------------------------------------------------------------------

def legacy_drive(argv):
    """Run the legacy ``lifecycle.drive`` entry unchanged and label its result NOT GOVERNED."""
    from importlib import import_module
    lifecycle = import_module("ravel.workflow.graphs.lifecycle")
    if any(a in ("-h", "--help") for a in argv):
        return lifecycle.main(list(argv))
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            result = lifecycle.main(list(argv))
    finally:
        text = captured.getvalue()
        try:
            value = json.loads(text) if text.strip() else None
        except ValueError:
            value = None
        if type(value) is dict:
            value["governance"] = {"label": NOT_GOVERNED, "reason": NOT_GOVERNED_NOTE}
            print(json.dumps(value, indent=2, sort_keys=True, default=str))
        elif text:
            sys.stdout.write(text)
        print(f"{NOT_GOVERNED}: {NOT_GOVERNED_NOTE}", file=sys.stderr)
    return result


# ---- starting a run ------------------------------------------------------------------------

def _operator_config():
    from .store import _operator_config
    return _operator_config()


HARNESS_SESSION = "harness-session"
SESSION_KEYS = {"schema_version", "kind", "session_id", "executable", "executable_sha256", "model", "effort"}


def _file_sha256(path):
    import hashlib
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def harness_binding(config):
    """Bind the operator's harness arm: a closed configuration and the retained session it pins.

    The configuration names the pinned executable (path and digest), model, reasoning effort,
    the retained harness-session record and the trusted-side results file. The session record
    must be an ordinary file naming exactly the same executable, digest, model and effort, and
    the executable's current bytes must still have that digest. Anything else refuses the
    harness channel before a run exists; a terminal message never stands in for this record.
    """
    from importlib.resources import files
    from jsonschema import Draft202012Validator
    schema = json.loads(files("ravel").joinpath("data/controller/schemas/operator-config.v1.json").read_text())
    harness = schema["properties"]["harness"]
    errors = sorted(e.message for e in Draft202012Validator(harness).iter_errors(config))
    if type(config) is not dict or errors:
        raise EntryError("the harness configuration is outside its closed schema: " + "; ".join(errors[:4]),
                         code="harness_config")
    executable = Path(config["executable"])
    if executable.is_symlink() or not executable.is_file():
        raise EntryError(f"the harness executable {executable} is not an ordinary file", code="harness_executable")
    if _file_sha256(executable) != config["executable_sha256"]:
        raise EntryError("the harness executable differs from its pinned digest", code="harness_executable")
    session = Path(config["session_record"])
    if session.is_symlink() or not session.is_file() or session.stat().st_size > 64 * 1024:
        raise EntryError("the retained harness session record is missing", code="harness_session_missing")
    raw = session.read_bytes()
    try:
        record = json.loads(raw)
    except ValueError:
        record = None
    if (type(record) is not dict or set(record) != SESSION_KEYS or record["schema_version"] != 1
            or record["kind"] != HARNESS_SESSION or type(record["session_id"]) is not str or not record["session_id"]):
        raise EntryError("the retained harness session record is not a harness-session record",
                         code="harness_session_stale")
    for key in ("executable", "executable_sha256", "model", "effort"):
        if record[key] != config[key]:
            raise EntryError(f"the retained harness session names another {key.replace('_', ' ')}",
                             code="harness_" + ("executable" if key.startswith("executable") else key))
    import hashlib
    return {"session_id": record["session_id"], "session_record": str(session),
            "session_sha256": hashlib.sha256(raw).hexdigest(), "executable": config["executable"],
            "executable_sha256": config["executable_sha256"], "model": config["model"], "effort": config["effort"],
            "results_file": config["results_file"]}


def verify_harness_binding(binding):
    """Whether a bound harness session still holds now: the same session bytes and executable digest."""
    import hashlib
    try:
        session = Path(binding["session_record"])
        if session.is_symlink() or hashlib.sha256(session.read_bytes()).hexdigest() != binding["session_sha256"]:
            return "the retained harness session record changed after the run started"
        executable = Path(binding["executable"])
        if executable.is_symlink() or _file_sha256(executable) != binding["executable_sha256"]:
            return "the harness executable changed after the run started"
    except (OSError, KeyError, TypeError):
        return "the retained harness session or its executable is unavailable"
    return None


def _supplied(values, cwd, *, data_classification=None):
    from ravel.workflow import provider_policy
    try:
        policy = provider_policy.supplied_classification(cwd, data_classification) if values else None
    except provider_policy.PolicyRefused as exc:
        raise EntryError(f'supplied input policy refused: {exc}; supply a classification within the project policy',
                         code='input_classification_refused') from exc
    rows = []
    for value in values or ():
        kind, sep, path = value.partition("=")
        if not sep:
            kind, path = None, value
        target = Path(path).expanduser()
        target = target if target.is_absolute() else Path(cwd) / target
        if not target.exists():
            raise EntryError(f"supplied input {path} does not exist")
        if kind is None:
            name = target.name.lower()
            kind = next((k for suffix, k in sorted(SUFFIX_KINDS.items(), key=lambda i: -len(i[0]))
                         if name.endswith(suffix)), "file" if target.is_file() else "directory")
        digest = None
        if target.is_file():
            import hashlib
            with target.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        rows.append({"kind": kind, "path": str(Path(os.path.realpath(target))), "sha256": digest,
                     "size": target.stat().st_size if target.is_file() else None,
                     "data_classification": policy, "restricted": policy['level'] == 'restricted'})
    # A supplied run directory becomes a legacy or controller run, labelled NOT GOVERNED unless governed (L01).
    from .routes import legacy
    return legacy.classify_supplied(rows)


def _output_placement(request, directory, workspace):
    """Reasons the run directory would itself violate the output contract the request declares."""
    from ..workflow import output_contract
    try:
        rows = output_contract.census_rows(request.decode("utf-8"), room=64, workspace=workspace)
    except (UnicodeDecodeError, ValueError):
        return []  # intake refuses an unreadable or overfull declaration with its own reason
    return output_contract.placement_conflicts(rows, directory)


def start(request: bytes, *, channel, rundir=None, unattended=False, supplied=(), root=None, origin=None,
          harness=None):
    """Create the run and its store and pin the request bytes; returns the ``RunStore``.

    The request record keeps the directory in which the request was received (``workspace``):
    intake binds the output paths the request declares to it, and a run directory that would
    itself violate those declarations is refused before anything is created.
    """
    if type(request) is not bytes or not request.strip():
        raise EntryError("the request is empty")
    if (channel == "harness") != (harness is not None):
        raise EntryError("the harness channel needs its bound harness session, and only that channel takes one",
                         code="harness_session_missing")
    if unattended:
        # The operator grant covers this run, or nothing is created (N1): an unauthenticated or edited ledger, an
        # expired grant or a directory outside the grant's project scope is refused before the run exists.
        from .authority import autonomy, common as authority_common
        try:
            autonomy.intake_refusal(_operator_config(), Path(rundir).expanduser() if rundir else Path.cwd())
        except authority_common.AuthorityRefused as exc:
            code = str(exc).split(":", 1)[0]
            raise EntryError(str(exc), code=code if code in autonomy.END_CODES + autonomy.WAIT_CODES
                             else "authority_invalid") from None
    from .store import new_run_id
    run_id = new_run_id()
    workspace = os.path.realpath(os.getcwd())
    directory = Path(rundir).expanduser() if rundir else Path.cwd() / "ravel-runs" / run_id
    conflicts = _output_placement(request, directory.absolute(), workspace)
    if conflicts:
        raise EntryError("the run directory conflicts with the output contract the request declares; nothing was "
                         "created: " + "; ".join(conflicts), code="output_contract_placement")
    owner = controller_owned(directory)  # the nearest existing ancestor decides, through aliases
    if owner:
        raise EntryError(f"{directory} lies inside the controller-owned run {owner}; choose a directory outside it")
    # A legacy layout is inspectable, never adopted for new science; the controller creates its own directory.
    from .routes import legacy
    view = legacy.check(directory)
    refusal = legacy.admit_new_run(directory)
    if refusal and view["layout"] in legacy.LEGACY_LAYOUTS:
        raise EntryError(refusal, code="legacy_layout", row="L01")
    if refusal:
        raise EntryError(refusal, code="run_directory_exists")
    from ravel.workflow import provider_policy
    supplied = list(supplied)
    if any(type(row) is not dict or ('restricted' in row and type(row['restricted']) is not bool)
           for row in supplied):
        raise EntryError('supplied inputs require manifest objects and boolean restricted flags; '
                         'supply classified file rows', code='input_classification_refused')
    try:
        supplied = [{**row, 'data_classification': provider_policy.supplied_classification(
            directory, row.get('data_classification'))} for row in supplied]
    except provider_policy.PolicyRefused as exc:
        raise EntryError(f'supplied input policy refused: {exc}; supply a classification within the project policy',
                         code='input_classification_refused') from exc
    supplied = [{**row, 'restricted': row['data_classification']['level'] == 'restricted'
                 or row.get('restricted', False)} for row in supplied]
    from .store import previous_claim
    earlier = previous_claim(directory, root)
    store = RunStore.create(directory, root=root, run_id=run_id, origin=origin or {"channel": channel})
    if earlier is not None and earlier["run_id"] != store.run_id:
        # A path an earlier run used (its directory deleted): the new run is its own run; the earlier one never
        # resumes from here (G4).
        store.append("path-reuse", {"previous_run": earlier["run_id"], "previous_store": earlier["store_exists"],
                                    "path": str(store.run_dir)})
    store.append("legacy-admission", {"path": view["path"], "layout": view["layout"], "refusal": refusal})
    digest = store.put_blob(request)
    store.append("request", {"sha256": digest, "channel": channel, "bytes": len(request),
                             "source": (origin or {}).get("source"), "unattended": bool(unattended),
                             "workspace": workspace})
    if harness is not None:
        from .sink.common import DELIVERY_TARGET
        store.append(HARNESS_SESSION, dict(harness))
        store.append(DELIVERY_TARGET, {"path": harness["results_file"]})
    store.append("supplied", {"inputs": list(supplied)})
    adopt_qualifications(store)
    return store


def adopt_qualifications(store):
    """Adopt the operator's current transport qualifications into the new run's store (G5); never fails the start."""
    try:
        from .authority import qualifications
    except ImportError:
        return []
    try:
        return qualifications.adopt(store)
    except (ValueError, OSError, KeyError) as exc:
        store.append(qualifications.ADOPTION, {"schema_version": 1, "status": "refused",
                                               "reason": f"{type(exc).__name__}: {exc}"[:500]})
        return []


def declare_controller(store):
    """Declare this process the controller of ``store``'s run, before any graph or transport is imported.

    From the declaration on, the agent tripwire blocks in this process whatever ``RAVEL_AGENT_TRIPWIRE``
    says (SW15); the observed mode and the host findings are kept in the store (``host-observation``).
    """
    from ..workflow import agent_tripwire, host_governance
    agent_tripwire.declare_controller_process(store.run_id)
    mode, requested = agent_tripwire.effective_mode()
    findings = host_governance.observe_host(None, source="controller", rundir=store.run_dir)
    return store.append("host-observation", {
        "source": "controller",
        "tripwire": {"mode": mode, "requested": requested, "declared": store.run_id,
                     "controller_process": agent_tripwire.controller_process()},
        "host_findings": sorted({str(f.get("code")) for f in findings or () if type(f) is dict})})


def _identity_check():
    """The confinement package's ``identity.require_governed_install``; None for a stand-in service without it."""
    import inspect
    from importlib import import_module
    from .graph import service
    confine = service("confine")
    if inspect.ismodule(confine):
        return import_module(confine.__name__ + ".identity").require_governed_install
    check = getattr(confine, "require_governed_install", None)
    return check if callable(check) else None


def admit_before_start(command, argv):
    """The identity admission of ``ravel <command> <argv>`` before anything is created (P05 identity).

    Governed code continues in this process. Code that is not governed re-executes through the
    current sealed runtime's launcher (``os.execv``: the same arguments, no new environment value)
    when that runtime holds the same tree digest and passes the same check. Otherwise the entry is
    refused with the reason and its fix. Returns the admission decision, or None without a check.
    """
    check = _identity_check()
    if check is None:
        return None
    from ..setup import governed_runtime
    decision = governed_runtime.admission(check)
    if decision["status"] != "ready":
        raise EntryError(decision["reason"], code="ungoverned_install")
    if decision["runs"] == "sealed":
        launcher = decision["launcher"]
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            os.execv(launcher, [launcher, command, *argv])
        except OSError as exc:
            raise EntryError(f"the sealed runtime launcher {launcher} could not start ({exc}); "
                             "`ravel governed-runtime status` shows the runtime", code="ungoverned_install") from exc
    return decision


def admit(store):
    """The confinement admission before every new or resumed drive (P05 ``policy.admission``).

    It records the running code's identity and pins the operator's restricted-source policy in the
    store; the controller records the intake rows it proves from those records. A refusal (code
    that is not an installed or sealed, read-only RAVEL; a missing or changed source policy) refuses
    the run. Without a confinement package nothing is admitted and those rows stay pending.
    """
    from .graph import service_function
    admission = service_function("confine", "policy", "admission")
    if admission is None:
        return None
    try:
        return admission(store, run_dir=store.run_record()["run_dir"])
    except ValueError as exc:
        raise EntryError(f"run {store.run_id} is not admitted: {exc}") from exc


def _run_input(store, *, unattended, workers):
    record = store.run_record()
    return {"run": {"run_id": store.run_id, "run_dir": record["run_dir"], "store_root": str(store.store_root),
                    "controller_mode": "unattended" if unattended else "interactive",
                    "unattended": bool(unattended), "host_kind": "controller", "composition_sha256": None,
                    "workers": workers}}


def _pending(observation):
    return [i for i in observation.get("interrupts") or () if i.get("schema_id") == AUTHORITY_SCHEMA]


def poll_wait(pending, poll_seconds=POLL_SECONDS):
    """Seconds to wait before polling a pending authority answer again, or None when it sets no bound.

    The authority's pending answer states how long it has waited and the operator's wait bound
    (``waited_seconds``, else ``since_ns``, and ``wait_bound_seconds``). Polls come at least
    ``poll_seconds`` apart and often enough to reach the bound well within the graph's poll limit; the
    poll at the bound lets the authority take its recorded default, or the graph hold the branch.
    """
    from .graph import MAX_POLLS
    if type(pending) is not dict or pending.get("poll") is False:
        return None
    bound, waited = pending.get("wait_bound_seconds"), pending.get("waited_seconds")
    if type(bound) not in (int, float) or bound < 0:
        return None
    if type(waited) not in (int, float):
        since = pending.get("since_ns")
        if type(since) is not int:
            return None
        waited = (time.time_ns() - since) / 1e9
    interval = max(float(poll_seconds), bound / (MAX_POLLS // 2))
    return max(0.0, min(interval, bound - waited))


def _autonomy():
    """The authority service's autonomy module, or None where the authority service is not installed."""
    import inspect
    from .graph import service
    installed = service("authority")
    found = getattr(installed, "autonomy", None)
    if found is None and inspect.ismodule(installed):
        from .authority import autonomy as found
    return found if callable(getattr(found, "settle", None)) else None


def _waiting(observation):
    terminal = observation.get("terminal") or {}
    return terminal.get("status") == "stopped" and str(terminal.get("reason") or "").startswith("waiting_for_human")


def human_wait(store, *, unattended, sleep=time.sleep, poll_seconds=POLL_SECONDS):
    """Hold the driver while the run waits for a human; the open waits when it must keep waiting, else [].

    Every current wait is recorded and notified once. A cleared wait is resolved; a wait past the operator's
    wait bound is recorded expired and the run continues to its qualified ending (the graph's guard ends it). An
    interactive driver returns at once with the open waits; an unattended driver polls until they clear or expire.
    """
    autonomy = _autonomy()
    if autonomy is None:
        return []
    from .graph import MAX_POLLS
    for row in autonomy.findings(store):
        if row["kind"] == "wait":
            autonomy.open_wait(store, row)
    rounds = 0
    while True:
        _, remaining = autonomy.settle(store)
        if not remaining:
            return []
        late = [w for w in remaining if autonomy.overdue(w)]
        if late:
            for wait in late:
                autonomy.expire(store, wait)
            return []
        if not unattended or rounds >= MAX_POLL_ROUNDS:
            return remaining
        bound = min(float(w.get("wait_bound_seconds") or 0) for w in remaining)
        waited = max((time.time_ns() - w["since_ns"]) / 1e9 for w in remaining)
        sleep(max(0.0, min(max(float(poll_seconds), bound / (MAX_POLLS // 2)), bound - waited)))
        rounds += 1


def drive(store, *, unattended=False, workers=1, resume=False, sleep=time.sleep, poll_seconds=POLL_SECONDS,
          gate_check=None, gate_providers=None):
    """Run or continue the ``controller.run`` graph for ``store``; returns the last observation.

    ``gate_check``/``gate_providers`` are the substrate's in-process seams; the substrate refuses
    them for a controller run unless the test harness enabled them (SW30).
    """
    from . import execution_manifest
    pin = execution_manifest.ensure(store, GRAPH_ID, resume=resume)
    declare_controller(store)
    seams = {"gate_check": gate_check, "gate_providers": gate_providers}
    from ..workflow import graph_substrate
    from .testing import mark_controller_process
    mark_controller_process()
    scope = store.graph_scope()
    instance = {"run_id": store.run_id}
    status = graph_substrate.status(scope) if resume else {"threads": []}
    started = any(t.get("graph_id") == GRAPH_ID and t.get("thread_id") == pin['thread_id']
                  for t in status.get("threads") or ())
    current = graph_substrate.status(scope, GRAPH_ID, instance) if resume else None
    if resume and (status.get('threads') and not started or
                   current.get('state') == 'absent' and store.latest('intake')):
        raise execution_manifest.ExecutionRefused('the pinned checkpoint thread is missing',
                                                   'restore the complete verified run bundle, then run: ' +
                                                   execution_manifest.resume_command(store, pin))
    started = started or bool(resume and current.get('state') != 'absent')
    admit(store)
    if resume and started:
        # The driver's own start is a boundary: a run waiting for a human resumes only once the wait clears or
        # passes its bound (N3, N7, G1).
        waiting = human_wait(store, unattended=unattended, sleep=sleep, poll_seconds=poll_seconds)
        if waiting:
            current = graph_substrate.status(scope, GRAPH_ID, instance)
            return {**current, "waiting_for_human": [w["code"] for w in waiting]}
        current = graph_substrate.status(scope, GRAPH_ID, instance)
        pending = _pending(current)
        if pending:
            observation = graph_substrate.respond(scope, GRAPH_ID, instance,
                                                  {p["id"]: {"kind": "authority_poll"} for p in pending},
                                                  workers=workers, **seams)
        elif current.get("interrupts"):
            return current  # reconcile evidence: the operator answers it; nothing is assumed
        else:
            observation = graph_substrate.run(scope, GRAPH_ID, instance, workers=workers, **seams)
    else:
        observation = graph_substrate.run(scope, GRAPH_ID, instance,
                                          input=_run_input(store, unattended=unattended, workers=workers),
                                          workers=workers, **seams)
    rounds, overdue, held = 0, 0, 0
    while True:
        observation, rounds, overdue = _poll_authority(store, observation, unattended=unattended, workers=workers,
                                                       sleep=sleep, poll_seconds=poll_seconds, rounds=rounds,
                                                       overdue=overdue, seams=seams)
        if not _waiting(observation) or held >= MAX_POLL_ROUNDS:
            return observation
        waiting = human_wait(store, unattended=unattended, sleep=sleep, poll_seconds=poll_seconds)
        if waiting:
            return {**observation, "waiting_for_human": [w["code"] for w in waiting]}
        held += 1
        observation = graph_substrate.run(scope, GRAPH_ID, instance, workers=workers, **seams)


def _poll_authority(store, observation, *, unattended, workers, sleep, poll_seconds, rounds, overdue, seams):
    from ..workflow import graph_substrate
    scope, instance = store.graph_scope(), {"run_id": store.run_id}
    while unattended and _pending(observation) and rounds < MAX_POLL_ROUNDS:
        wait = poll_wait((_pending(observation)[0].get("payload") or {}).get("pending"), poll_seconds)
        if wait is None:
            break  # no bounded wait: the run waits for the operator, who resumes it
        overdue = overdue + 1 if wait <= 0 else 0
        if overdue > 2:
            break  # still pending past the bound: the operator resumes it
        rounds += 1
        sleep(wait)
        observation = graph_substrate.respond(scope, GRAPH_ID, instance,
                                              {p["id"]: {"kind": "authority_poll"} for p in _pending(observation)},
                                              workers=workers, **seams)
    return observation, rounds, overdue


def summary(store, observation):
    pending = _pending(observation)
    delivery = None
    row = store.latest('receipt')
    if row:
        delivery = row['record']
    from .outcomes import outcome
    verified = None
    if delivery and delivery.get('receipt_blob'):
        from .sink.deliver import receipt as audit_delivery
        audit = audit_delivery(store)
        verified = dict(audit, delivery_dir=(audit.get('delivery') or {}).get('directory'))
        if not (audit.get('verification') or {}).get('delivery_intact'):
            verified = None
    if observation.get('next') or observation.get('interrupts'):
        verified = None
    return {"outcome": outcome(delivery=verified, terminal=observation.get('terminal'), run_id=store.run_id,
                               evidence=str(store.root / 'journal.jsonl')),
            "run_id": store.run_id, "run_dir": str(store.run_dir), "store": str(store.root),
            "graph": GRAPH_ID, "thread_id": observation.get("thread_id"), "next": observation.get("next"),
            "terminal": observation.get("terminal"),
            "waiting_for": [{"kind": (p.get("payload") or {}).get("authority_kind"),
                             "reason": ((p.get("payload") or {}).get("pending") or {}).get("reason")} for p in pending],
            "delivery": delivery, "governance": "controller",
            "resume": f"ravel drive --resume {store.run_id}" if pending or observation.get("next") else None}


def terminal_note(unattended):
    """Warn when an interactive run has no controlling terminal: every check-in would wait."""
    if unattended:
        return None
    try:
        from .authority import terminal
    except ImportError:
        return None
    available = getattr(terminal, "available", None)
    if callable(available) and not available():
        note = ("no controlling terminal: the check-ins will wait; resume from a terminal with "
                "`ravel drive --resume <run-id>`, or run --unattended under an operator configuration")
        print(f"ravel: {note}", file=sys.stderr)
        return note
    return None


def _workers(value):
    if value is not None:
        return value
    budget = (_operator_config().get("budgets") or {}) if type(_operator_config().get("budgets")) is dict else {}
    concurrency = budget.get("concurrency")
    return int(concurrency) if type(concurrency) is int and 1 <= concurrency <= 16 else 1


def _drive_parser(prog):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0])
    parser.add_argument("--unattended", action="store_true",
                        help="unattended: authority from the operator's configuration; waits are bounded")
    parser.add_argument("--rundir", type=Path, help="new run directory (default ./ravel-runs/<run id>)")
    parser.add_argument("--input", action="append", default=[], metavar="[KIND=]PATH",
                        help="a supplied input (events, model, workspace, measurement); repeatable")
    parser.add_argument("--input-classification", type=Path, metavar="POLICY_JSON",
                        help="classification for supplied files: level and allowed_providers; absent project policy defaults to restricted")
    parser.add_argument("--workers", type=int, help="concurrent steps per wave (1-16)")
    return parser


def _input_policy(args):
    if args.input_classification is None:
        return None
    if not args.input:
        raise EntryError('--input-classification requires --input; supply the files being classified')
    from ravel.workflow import provider_policy
    from ravel.workflow.state_io import read_json
    try:
        return provider_policy.classification(read_json(args.input_classification.expanduser()))
    except (ValueError, OSError) as exc:
        raise EntryError(f'invalid --input-classification: {exc}; supply a classification JSON object') from exc


def drive_main(argv=None):
    """``ravel drive``: a new governed run, a resume, or the legacy lifecycle for a legacy run."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not _controller_form(argv):
        return legacy_drive(argv)
    parser = _drive_parser("ravel drive")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--request-file", type=Path, help="the request, read verbatim from this file")
    choice.add_argument("--resume", metavar="RUN_ID", help="continue a controller run from its store")
    args = parser.parse_args(argv)
    try:
        admit_before_start("drive", argv)
        if args.resume:
            if args.input or args.input_classification:
                raise EntryError("supplied inputs belong to a new run; a resumed run keeps the inputs it started with")
            store = open_for_resume(args.resume, rundir=args.rundir)
            # A run started unattended stays unattended: the mode is the run's, not the resuming command's.
            started = ((store.latest("request") or {}).get("record") or {}).get("unattended") is True
            observation = drive(store, unattended=args.unattended or started, workers=_workers(args.workers),
                                resume=True)
        else:
            request = args.request_file.expanduser().read_bytes()
            unattended = args.unattended
            terminal_note(unattended)
            channel = "harness" if unattended and _operator_config().get("harness") else (
                "operator-file" if unattended else "terminal")
            harness = harness_binding(_operator_config()["harness"]) if channel == "harness" else None
            store = start(request, channel=channel, rundir=args.rundir, unattended=unattended,
                          supplied=_supplied(args.input, os.getcwd(), data_classification=_input_policy(args)),
                          harness=harness,
                          origin={"entry": "drive", "source": "request-file", "channel": channel,
                                  "request_file": str(args.request_file)})
            observation = drive(store, unattended=unattended, workers=_workers(args.workers))
        view = summary(store, observation)
    except Exception as exc:
        from .outcomes import error_result
        return error_result('drive', exc, store=locals().get('store'))
    print(json.dumps(view, indent=2, sort_keys=True, default=str))
    return 0


def ask_main(argv=None):
    """``ravel ask TEXT``: the request is the text argument, byte for byte."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _drive_parser("ravel ask")
    parser.add_argument("text", nargs="+", help="the question or request")
    args = parser.parse_args(argv)
    request = " ".join(args.text).encode("utf-8")
    channel = "operator-file" if args.unattended else "terminal"
    try:
        admit_before_start("ask", argv)
        terminal_note(args.unattended)
        store = start(request, channel=channel, rundir=args.rundir, unattended=args.unattended,
                      supplied=_supplied(args.input, os.getcwd(), data_classification=_input_policy(args)),
                      origin={"entry": "ask", "source": "argument", "channel": channel})
        observation = drive(store, unattended=args.unattended, workers=_workers(args.workers))
        view = summary(store, observation)
    except Exception as exc:
        from .outcomes import error_result
        return error_result('ask', exc, store=locals().get('store'))
    print(json.dumps(view, indent=2, sort_keys=True, default=str))
    return 0


# ---- resume and status --------------------------------------------------------------------

def open_for_resume(run_id, *, rundir=None, root=None):
    """The run's store, verified, with its directory binding intact; refuses copies and tampering."""
    base = Path(root) if root is not None else store_root()
    if not (base / run_id / "run.json").is_file():
        raise EntryError(f"no controller run {run_id} in the store {base}")
    store = RunStore(run_id, root=base)
    try:
        store.recover()
    except StoreError as exc:
        raise EntryError(f"run {run_id} cannot be resumed: {exc}", code='journal_recovery_refused') from exc
    problems = store.verify()
    try:
        problems += store.check_binding(rundir)
        if store.run_dir is not None:
            # A run whose directory now shows a layout written outside the controller is refused (SW26).
            from .routes import legacy
            problems += legacy.resume_errors(store.run_dir, run_id)
        request = store.latest("request")
        if request is None:
            problems.append("the run's request record is missing")
        else:
            try:
                store.get_blob(request["record"]["sha256"])
            except StoreError as exc:
                problems.append(str(exc))
    except StoreTampered as exc:  # every journal read verifies the chain head; a tampered journal is not resumed
        problems += [str(exc)] if str(exc) not in problems else []
    if problems:
        text = "; ".join(problems)
        try:
            bound = (store.run_record() or {}).get("run_dir")
        except StoreError:  # a tampered journal names no trustworthy directory
            bound = None
        if "moved, renamed or deleted" in text or "is not the run's directory" in text:
            code, remedy = "run_relocated", f"return the run directory to {bound} (a run resumes only there)"
        elif "original directory" in text or "names another run" in text:
            code, remedy = "run_directory_replaced", (f"{bound} now holds another directory or run; this run cannot "
                                                      "resume; start a new run")
        else:
            code, remedy = "run_unverified", "the store or its directory does not verify; nothing is resumed"
        raise EntryError(f"run {run_id} cannot be resumed ({code}): {text}; {remedy}", code=code)
    return store


def status(run_id, *, root=None):
    """A read-only view of the run from its store (nothing is created, locked or written)."""
    base = Path(root) if root is not None else store_root()
    if not (base / run_id / "run.json").is_file():
        raise EntryError(f"no controller run {run_id} in the store {base}")
    store = RunStore(run_id, root=base)
    with store.snapshot():
        return _status_store(store)


def _status_store(store):
    run_id = store.run_id
    view = {"run_id": run_id, "store": str(store.root), "run_dir": str(store.run_dir),
            "verify": store.verify(), "binding": store.check_binding(), "head": store.head()}
    for kind in ("intake", "route", "plan", "wave", "wave-result", "gate", "authority", "receipt", "ending"):
        latest = store.latest(kind)
        view[kind] = latest["record"] if latest else None
    view["counts"] = {kind: store.count(kind) for kind in ("ledger", "authority", "wave", "gate", "judgment")}
    threads = store.root / "graph" / "framework" / "threads"
    view["threads"] = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(threads.glob("*.json"))] \
        if threads.is_dir() else []
    stop = store.root / "graph" / "framework" / "STOP"
    view["stop"] = json.loads(stop.read_text(encoding="utf-8")) if stop.is_file() else None
    view["governance"] = "controller"
    try:
        from . import model_cost
        view['model_cost'] = model_cost.summary(store)
    except Exception as exc:
        view['model_cost'] = {'status': 'unknown', 'error': type(exc).__name__}
    return view


def status_main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="ravel status", description="read a controller run's state from its store")
    parser.add_argument("--run", required=True, metavar="RUN_ID")
    args = parser.parse_args(argv)
    try:
        view = status(args.run)
    except (EntryError, StoreError, OSError) as exc:
        print(f"ravel status: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(view, indent=2, sort_keys=True, default=str))
    return 0 if not view["verify"] else 1


def main(argv=None):
    """``python -m ravel.controller.entry drive|ask|status ...``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    command, rest = (argv[0], argv[1:]) if argv else (None, [])
    entries = {"drive": drive_main, "ask": ask_main, "status": status_main}
    if command not in entries:
        print("usage: python -m ravel.controller.entry {drive|ask|status} ...", file=sys.stderr)
        return 2
    return entries[command](rest)


if __name__ == "__main__":
    raise SystemExit(main())
