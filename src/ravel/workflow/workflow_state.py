#!/usr/bin/env python3
"""workflow_state.py -- the LIVE per-run state machine (the keystone ledger).

Writes and drives <rundir>/run_state.json: the single source of truth for which skills were
invoked, what compute was launched, which subagents ran, what was edited, and -- via `advance` --
how far the lifecycle has progressed. The PostToolUse observer (and its step-doc fallback twin)
call `record`; every later gate (DRIVE, skill-coverage, phantom-bg, provenance) READS this file.

Reuses validate_run_state.py's declarative lifecycle model (STAGE_ORDER / STAGE_MATRIX /
resolve_level / evaluate) so `advance` refuses to move past a stage whose required predecessors are
not satisfied -- the post-hoc judge turned into a live driver.

Usage:
  workflow_state.py init    --rundir <dir> [--session-id <id>] [--force]
  workflow_state.py record  (--rundir <dir> | --project-dir <dir>) --kind skill|compute|subagent|edit --payload <json>
  workflow_state.py advance --rundir <dir> --to <stage> [--json]
  workflow_state.py status  --rundir <dir> [--json]
  workflow_state.py next    --rundir <dir> [--json]
  workflow_state.py require --rundir <dir> --kind skill|command|artifact|stage --what <str>
  workflow_state.py --selftest

Exit codes: 0 OK * 1 precondition/require FAIL * 2 usage / not-a-dir / bad payload * 3 no|invalid contract
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import json
import os
import sys
from functools import wraps
from pathlib import Path
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from ravel.workflow import provenance               # noqa: E402
from ravel.workflow import session_lock             # noqa: E402
from ravel.validation import validate_run_state       # noqa: E402
from ravel.validation import validate_task_contract   # noqa: E402
from ravel.workflow.state_io import atomic_json, file_lock, read_json
from ravel.workflow.launch_authorization import operational_utc

RUN_STATE_NAME = "run_state.json"
SCHEMA_VERSION = 1
GENERATOR = "workflow_state.py"

# every appendable list-key present at init so no downstream reader KeyErrors on a fresh ledger
LIST_KEYS = ("skills_invoked", "compute_launched", "subagents", "edits",
             "obligations", "open_failure_records", "open_defect_notes",
             "armed_watchers", "checkins")


def _state_path(rundir):
    return os.path.join(rundir, RUN_STATE_NAME)


def load_state(rundir):
    """Return (state_dict, err). err is a str on failure, else None."""
    p = _state_path(rundir)
    if not os.path.isfile(p):
        return None, f"no {RUN_STATE_NAME} in {rundir} (run `workflow_state.py init` first)"
    try:
        state = read_json(p)
        if not isinstance(state, dict):
            raise ValueError("run state must be an object")
        return state, None
    except (OSError, ValueError) as e:
        return None, f"cannot read/parse {RUN_STATE_NAME}: {e}"


class StateConflict(ValueError):
    """The caller read an older revision; re-read before changing the ledger."""


def write_state(rundir, state, *, replace=False):
    """Serialize writers and reject lost updates; keep forced reset evidence."""
    path = Path(_state_path(rundir))
    with file_lock(Path(rundir) / "logs/state/write.lock"):
        current = read_json(path) if path.exists() else {}
        expected = state.get("revision", 0)
        actual = current.get("revision", 0)
        if type(expected) is not int or type(actual) is not int:
            raise ValueError("state revision must be an integer")
        if not replace and actual != expected:
            raise StateConflict(f"run state changed: expected revision {expected}, found {actual}")
        if replace and current:
            from ravel.workflow.execution import utc_now
            backup = Path(rundir) / "logs/state" / f"revision-{actual}-{time.time_ns()}.json"
            atomic_json(backup, {"archived_utc": utc_now(), "state": current})
        updated = {**state, "revision": actual + 1}
        atomic_json(path, updated)
        state["revision"] = updated["revision"]


def retry_conflict(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        for attempt in range(12):
            try:
                return function(*args, **kwargs)
            except StateConflict:
                if attempt == 11:
                    print("workflow_state: concurrent updates did not settle; retry this operation",
                          file=sys.stderr)
                    return 3
                time.sleep(0.005 * (attempt + 1))
    return wrapped


def new_state(rundir, contract, contract_path, session_id):
    """Build a fresh run_state dict with EVERY schema key populated (lists empty)."""
    state = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id or "",
        "task_mode": contract.get("task_mode"),
        "stat_mode": contract.get("stat_mode"),
        "detector_mode": contract.get("detector_mode"),
        "compute_plan": contract.get("compute_plan"),
        "current_step": None,
        "ladder_rung": None,
        "cursor_utc": provenance._resolve_timestamp(),
        "routed": False,
        "next_required": None,
    }
    for k in LIST_KEYS:
        state[k] = []
    state.update(provenance.provenance_pair(GENERATOR, [os.path.abspath(contract_path)]))
    return state


def cmd_init(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state init: not a directory: {rundir}", file=sys.stderr)
        return 2
    if os.path.isfile(_state_path(rundir)) and not args.force:
        print(f"workflow_state init: {RUN_STATE_NAME} already exists in {rundir} "
              "(use --force to overwrite)", file=sys.stderr)
        return 3
    contract, cpath, err = validate_run_state.load_contract_for(rundir, None)
    if err:
        print(f"workflow_state init: {err}", file=sys.stderr)
        return 3
    errs = validate_task_contract.validate(contract)
    if errs:
        print("workflow_state init: task_contract.json is invalid:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 3
    from .research_admission import admission
    protocol_errors = admission(rundir, 'plan', contract=contract, bind=True)
    if protocol_errors:
        print('; '.join(protocol_errors), file=sys.stderr)
        return 3
    state = new_state(rundir, contract, cpath, args.session_id)
    write_state(rundir, state, replace=args.force)
    print(f"workflow_state: initialized {_state_path(rundir)} "
          f"(task_mode={state['task_mode']}, compute_plan={state['compute_plan']})")
    return 0


def _norm_skill(p):
    if "skill" not in p:
        raise ValueError("skill payload requires a 'skill' field")
    return {"skill": p["skill"]}


def _norm_compute(p):
    if "cmd" not in p:
        raise ValueError("compute payload requires a 'cmd' field")
    return {
        "cmd": p["cmd"],
        "bg_kind": p.get("bg_kind"),
        "bg_id": p.get("bg_id"),
        "logfile": p.get("logfile"),
        "done_condition": p.get("done_condition"),
        "next_action": p.get("next_action"),
        "supervised": bool(p.get("supervised", False)),
    }


def _norm_subagent(p):
    return {"agent_type": p.get("agent_type", "")}


def _norm_edit(p):
    if "path" not in p:
        raise ValueError("edit payload requires a 'path' field")
    return {"path": p["path"]}


# --- state-mutator kinds: list_key is None, so the normalizer takes (state, payload, utc)
#     and mutates `state` directly rather than returning a dict to append. These are the real
#     writers of `routed` + `open_failure_records`; the hooks INVOKE them. Return True iff state
#     was mutated -- False tells cmd_record to skip the write entirely.
def _norm_route(state, payload, utc):
    """route: mark the run routed and leave an audit entry carrying the chosen route/target (via
    --payload {"route":...} or the --what shortcut). A payload with NO routing content is a silent
    no-op: the router hook fires this blind on every physics-looking prompt, and a
    contentless append is pure ledger noise ({"utc": ""} rows) whose rewrite also refreshes the
    file mtime -- the loop that kept a closed run looking 'active' forever."""
    audit = {"utc": utc}
    for k in ("route", "next", "what"):
        if payload.get(k):
            audit[k] = payload[k]
    if len(audit) == 1:
        return False
    state["routed"] = True
    state.setdefault("routes", []).append(audit)
    return True


def _norm_failure(state, payload, utc):
    """failure: register an OPEN failure record -- the logs/<stage>.failure.json relpath
    stage_supervisor.py just wrote -- so the CATCH fallback + Stop open-failure branch can see it.
    Requires the relpath (via --what, or --payload {"ref"|"path": ...}); de-duplicates."""
    ref = payload.get("ref") or payload.get("path") or payload.get("what")
    if not ref:
        raise ValueError("failure payload requires the failure.json relpath (--what or 'ref')")
    open_recs = state.setdefault("open_failure_records", [])
    if ref not in open_recs:
        open_recs.append(ref)
    return True


# kind -> (run_state list key, payload normalizer). Later phases register new kinds here.
# A str list_key => list-append kind (normalizer (payload)->dict); None => state-mutator kind
# (normalizer (state, payload, utc) mutates state).
RECORD_KINDS = {
    "skill":    ("skills_invoked",   _norm_skill),
    "compute":  ("compute_launched", _norm_compute),
    "subagent": ("subagents",        _norm_subagent),
    "edit":     ("edits",            _norm_edit),
    "route":    (None,               _norm_route),      # sets state["routed"]=True
    "failure":  (None,               _norm_failure),    # appends to open_failure_records
}


# liveness window for the SESSION.lock heartbeat; matches session_lock's --stale-hours default
LOCK_FRESH_HOURS = 24.0


def _rundir_is_active(rundir, fresh_hours=LOCK_FRESH_HOURS):
    """A rundir counts as ACTIVE for auto-resolution iff it is not closed (no RESULT.md -- the
    run's closing record) and carries the ownership mark: a SESSION.lock with a heartbeat
    inside fresh_hours. NOT ledger-mtime freshness -- that rule is unsound: any maintenance write
    to a stale ledger (even a noise scrub) resurrects it, and each misdirected append then keeps
    it fresh forever. Runtime-only wall-clock comparison (like session_lock itself) -- nothing
    here is recorded, so the no-datetime.now() emitter rule is not in play."""
    if os.path.isfile(os.path.join(rundir, "RESULT.md")):
        return False
    lock = session_lock._read(os.path.join(rundir, session_lock.LOCK))
    return bool(lock) and \
        session_lock._age_hours(lock.get("renewed", lock.get("acquired", ""))) < fresh_hours


def find_active_rundir(project_dir):
    """Resolve the ledger `record --project-dir` (the observer + router hooks) should append to.
    Resolution order:
      1. cwd inside a trial-runs/* rundir that has a run_state.json -> that rundir (the session is
         working IN that run -- unambiguous, even for a closed run being backfilled);
      1b. else the run the host session registered (R-50 active_run registry), if not closed;
      2. else the newest trial-runs/*/run_state.json among ACTIVE rundirs (live SESSION.lock, no
         RESULT.md -- see _rundir_is_active) -> its rundir;
      3. else None (record self-scopes to a no-op).
    'Active' used to mean just 'newest mtime', which matched long-closed runs forever -- every
    misdirected append refreshed the mtime that made the run look newest (the route-noise
    class, the {"utc": ""} rows in closed runs' ledgers)."""
    base = os.path.join(project_dir, "trial-runs")
    base_abs = os.path.abspath(base)
    cwd = os.path.abspath(os.getcwd())
    if cwd.startswith(base_abs + os.sep):
        name = cwd[len(base_abs) + 1:].split(os.sep)[0]
        rd = os.path.join(base, name)
        if os.path.isfile(os.path.join(rd, RUN_STATE_NAME)):
            return rd
    # R-50: the run this host session registered (ravel initiate/plan), unless it is closed.
    from . import active_run
    registered = active_run.lookup(active_run.session_from_env())
    if registered is not None and not os.path.isfile(os.path.join(registered, "RESULT.md")):
        return str(registered)
    best, best_mtime = None, -1.0
    try:
        entries = os.listdir(base)
    except OSError:
        return None
    for name in entries:
        rd = os.path.join(base, name)
        cand = os.path.join(rd, RUN_STATE_NAME)
        try:
            m = os.path.getmtime(cand)
        except OSError:
            continue
        if m > best_mtime and _rundir_is_active(rd):
            best, best_mtime = rd, m
    return best


@retry_conflict
def cmd_record(args):
    rundir = args.rundir
    if rundir is None:
        if not args.project_dir:
            print("workflow_state record: need --rundir or --project-dir", file=sys.stderr)
            return 2
        rundir = find_active_rundir(args.project_dir)
        if rundir is None:
            return 0                    # observer best-effort: no active run -> no-op, never block
    rundir = rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state record: not a directory: {rundir}", file=sys.stderr)
        return 2
    if args.payload is not None:
        try:
            payload = json.loads(args.payload)
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object")
        except ValueError as e:
            print(f"workflow_state record: bad --payload: {e}", file=sys.stderr)
            return 2
    elif args.what is not None:
        payload = {"what": args.what}     # --what shortcut for string-valued kinds (route/failure)
    else:
        payload = {}                      # e.g. a bare `record --kind route`; the normalizer decides
    state, err = load_state(rundir)
    if err:
        print(f"workflow_state record: {err}", file=sys.stderr)
        return 3
    list_key, norm = RECORD_KINDS[args.kind]
    utc = provenance._resolve_timestamp()
    try:
        if list_key is None:                          # state-mutator kind (route/failure)
            if not norm(state, payload, utc):
                return 0                              # nothing recorded -> no write, no mtime touch
        else:                                         # list-append kind (skill/compute/subagent/edit)
            entry = norm(payload)
            entry["utc"] = utc
            state.setdefault(list_key, []).append(entry)
    except ValueError as e:
        print(f"workflow_state record: {e}", file=sys.stderr)
        return 2
    state["cursor_utc"] = utc
    write_state(rundir, state)
    return 0


def _prev_stage(stage):
    i = validate_run_state.STAGE_ORDER.index(stage)
    return validate_run_state.STAGE_ORDER[i - 1] if i > 0 else None


def compute_next_required(rundir, contract):
    """The first unmet requirement as a next-action hint, else None. A missing CHECK-IN 1
    approval precedes every post-approval stage. Read-only (validate_run_state.next_required)."""
    from ravel.workflow.execution import validate_execution
    execution_errors = validate_execution(rundir)
    if execution_errors:
        return {"kind": "execution", "what": "repair or resume invalid stage",
                "why": "; ".join(execution_errors)}
    return validate_run_state.next_required(rundir, contract)


@retry_conflict
def cmd_advance(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state advance: not a directory: {rundir}", file=sys.stderr)
        return 2
    state, err = load_state(rundir)
    if err:
        print(f"workflow_state advance: {err}", file=sys.stderr)
        return 3
    contract, _cpath, cerr = validate_run_state.load_contract_for(rundir, None)
    if cerr:
        print(f"workflow_state advance: {cerr}", file=sys.stderr)
        return 3
    target = args.to
    prev = _prev_stage(target)
    blockers = validate_task_contract.validate(contract)
    if prev is not None and not blockers:
        result = validate_run_state.evaluate(rundir, contract, stage_limit=prev)
        for s in result["stages"]:
            if s["status"] == "FAIL":
                blockers.append(f"stage {s['name']}: FAIL ({s['status']})")
        for inv in result["invariants"]:
            if inv["status"] == "FAIL":
                blockers.append(f"invariant {inv['name']}: {inv['detail']}")
    payload = {"target": target, "blockers": blockers}
    if blockers:
        payload["advanced"] = False
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"workflow_state advance: REFUSED advance to {target!r} -- unmet preconditions:",
                  file=sys.stderr)
            for b in blockers:
                print(f"  - {b}", file=sys.stderr)
        return 1
    state["current_step"] = target
    state["cursor_utc"] = provenance._resolve_timestamp()
    state["next_required"] = compute_next_required(rundir, contract)
    write_state(rundir, state)
    payload["advanced"] = True
    payload["next_required"] = state["next_required"]
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        nr = state["next_required"]
        print(f"workflow_state advance: now at {target!r}; next_required="
              f"{nr['what'] if nr else '(none -- required prefix satisfied)'}")
    return 0


APPROVAL_VERSION = 2
APPROVAL_GENERATOR = "workflow_state.py approve"
APPROVAL_PLANS = ("none", "dry", "smoke", "full", "scan")
# Compute beyond the smoke run: the bulk of the compute that CHECK-IN 2 gates.
BULK_PLANS = ("full", "scan")
# The scoped routes (`ravel plan`/`ravel run`) carry one fixed, bounded calculation with no waypoint,
# so CHECK-IN 2 does not apply to them.
NO_CHECKIN2_TASK_MODES = ("generate", "likelihood")


def approval_input_paths(rundir):
    """The single ordered input binding, shared by approval emission and verification."""
    rundir = os.path.abspath(rundir)
    rel = validate_run_state.find_first_existing(rundir, "inputs/task_contract.json", "task_contract.json")
    paths = [os.path.join(rundir, rel or "inputs/task_contract.json"),
             os.path.join(rundir, "inputs", "checkin1.json"),
             os.path.join(rundir, "inputs", "cost_preflight.json")]
    # The bounded correction envelope is approved before the first experiment.
    # Adding, deleting, or editing it afterwards changes the first approval's
    # fingerprint; it cannot silently expand the human's recorded scope.
    if os.path.isfile(paths[0]):
        contract = validate_task_contract.load_contract(paths[0])
        requirements = contract.get('task_requirements', {}) if isinstance(contract, dict) else {}
        amendments = requirements.get('amendments', []) if isinstance(requirements, dict) else []
        if isinstance(amendments, list):
            for pin in amendments:
                path = pin.get('path') if isinstance(pin, dict) else None
                if isinstance(path, str) and os.path.isabs(path): paths.append(path)
        # A pinned reading and plan, and with a plan the delegated adapter-default
        # justifications, enter the fingerprint only when the contract pins them, so
        # contracts without pins keep their path list and fingerprint.
        pinned = validate_task_contract.pinned_paths(rundir, contract)
        paths.extend(pinned)
        if isinstance(contract, dict) and "request_plan" in contract:
            from ravel.validation.intake_records import DELEGATED_DEFAULTS_PATH
            paths.append(os.path.join(rundir, DELEGATED_DEFAULTS_PATH))
    for rel in ('inputs/review_points_approval.json', 'inputs/agent_ceilings.json'):
        extra = os.path.join(rundir, rel)
        if os.path.isfile(extra):
            paths.append(extra)
    policy = os.path.join(rundir, "inputs", "physics_review_policy.json")
    if os.path.exists(policy):
        paths.append(policy)
    # Execution-backend plans are approved inputs: a plan pinned after approval changes the fingerprint.
    placed = os.path.join(rundir, "inputs", "backend-plan.json")
    if os.path.isfile(placed):
        paths.append(placed)
    plans = os.path.join(rundir, "inputs", "backend-plans")
    if os.path.isdir(plans):
        paths.extend(os.path.join(plans, name) for name in sorted(os.listdir(plans)) if name.endswith(".json"))
    from . import scientific_autonomy
    if os.path.isfile(paths[0]): paths.extend(scientific_autonomy.input_paths(validate_task_contract.load_contract(paths[0]), rundir))
    if os.path.isfile(paths[0]):
        from .approval_inputs import operation_inputs
        operation_paths, _rendered = operation_inputs(rundir, contract)
        paths.extend(operation_paths)
    from . import work_dispatch
    paths.extend(work_dispatch.approval_input_paths(rundir))
    from . import site_tools
    paths.extend(site_tools.approval_input_paths(rundir))
    from .method_selection import DECISION_PATH
    method = os.path.join(rundir, DECISION_PATH)
    if os.path.exists(method):
        paths.append(method)
    return list(dict.fromkeys(paths))


def _approval_inputs_snapshot(rundir, paths):
    from . import approval_inputs
    contract = validate_task_contract.load_contract(paths[0])
    _files, rendered = approval_inputs.operation_inputs(rundir, contract)
    return approval_inputs.capture(rundir, paths, rendered)


def verify_approval(rundir, record=None, *, required_plan=None, disclose=False):
    """Return strict live-approval errors. This checks integrity, not human identity.

    Verification is read-only. A launch path passes ``disclose=True`` to append the
    changed approved inputs to DEVIATIONS.md when it refuses; status, review and
    certification reads never write the ledger.

    Version-1 approvals have no content binding and must be re-recorded before live
    compute. No legacy waiver is available here. All declared source bytes must still
    match the canonical provenance fingerprint captured by the approve command.
    A full or scan launch also needs an admitted method decision; its refusal follows
    the approval's own errors.
    """
    from .method_selection import launch_errors
    errors = _verify_approval_record(rundir, record, required_plan=required_plan, disclose=disclose)
    return errors + [error for error in launch_errors(rundir, required_plan) if error not in errors]


def _verify_approval_record(rundir, record, *, required_plan, disclose):
    if record is None:
        try:
            record = validate_task_contract.load_contract(
                os.path.join(rundir, "inputs", "checkin1_approval.json"))
        except (OSError, ValueError, UnicodeError, RecursionError) as e:
            return [f"checkin1_approval.json cannot be read: {e}"]
    if type(record) is not dict:
        return ["checkin1_approval.json must be an object"]
    delegated=record.get("schema_version")==3
    fields = {"schema_version", "generated_by", "generated_utc", "approved_plan", "quote",
              "task_contract", "checkin1", "cost_preflight", "input_fingerprint"}
    if delegated:fields|={"authority","delegation","delegate_actor"}
    optional = {"approved_inputs", "input_changes", "authority"}
    errors = [f"approval missing required field {key!r}" for key in sorted(fields - record.keys())]
    errors += [f"approval has unknown field {key!r}" for key in record.keys() - fields - optional]
    if type(record.get("schema_version")) is not int or record.get("schema_version") != (3 if delegated else APPROVAL_VERSION):
        errors.append("approval schema_version must be integer 2; unbound version-1 archives "
                      "must be re-recorded with workflow_state.py approve before live compute")
    for key in fields - {"schema_version", "delegation"}:
        value = record.get(key)
        if type(value) is not str or (key != "generated_utc" and not value.strip()):
            errors.append(f"approval.{key} must be a " + ("string" if key == "generated_utc" else "nonblank string"))
    from .approval_authority import AUTHORITIES
    if 'authority' in record and record['authority'] not in (*AUTHORITIES, 'machine_under_user_delegation'):
        errors.append('approval authority must be an evidence-based authority label')
    if errors:
        return errors
    generator="workflow_state.py delegated-approve" if delegated else APPROVAL_GENERATOR
    if record["generated_by"] != generator:
        errors.append(f"approval.generated_by must be {APPROVAL_GENERATOR!r}")
    plan = record["approved_plan"]
    if plan not in APPROVAL_PLANS:
        errors.append("approval.approved_plan must be none|dry|smoke|full|scan")
    if required_plan is not None:
        from ravel.workflow.launch_authorization import parse_utc
        try:
            parse_utc(record["generated_utc"])
        except ValueError as exc:
            errors.append(f"approval timestamp is invalid for live compute: {exc}")
        if required_plan not in APPROVAL_PLANS:
            errors.append("required_plan must be none|dry|smoke|full|scan")
        elif plan in APPROVAL_PLANS and (
                APPROVAL_PLANS.index(plan) < APPROVAL_PLANS.index(required_plan)):
            errors.append(f"explicit {required_plan} launch exceeds approved_plan={plan}")
    try:
        paths = approval_input_paths(rundir)
        snapshot = _approval_inputs_snapshot(rundir, paths)
        from . import approval_inputs
        if 'approved_inputs' in record:
            changed = approval_inputs.changes(rundir, record['approved_inputs'], snapshot, approval_record=record)
            if changed:
                if disclose:
                    approval_inputs.record_deviations(rundir, changed)
                return ["stale or unbound approval: approved input changed: " +
                        ", ".join(r['path'] for r in changed) +
                        "; record an amendment and re-approve CHECK-IN 1"]
        elif any(k in validate_task_contract.load_contract(paths[0]) for k in ('execution_plan', 'request_plan')):
            return ['stale or unbound approval: operation inputs lack byte commitments; re-approve CHECK-IN 1']
    except (OSError, ValueError, KeyError, TypeError) as exc:
        from . import approval_inputs
        if disclose:
            try:
                approval_inputs.record_deviations(rundir, approval_inputs.observed_changes(rundir, record))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return [f'stale or unbound approval: {exc}; amend and re-approve CHECK-IN 1']
    for key, path in zip(("task_contract", "checkin1", "cost_preflight"), paths):
        if record[key] != os.path.relpath(path, rundir):
            errors.append(f"approval.{key} must name {os.path.relpath(path, rundir)!r}")
    if errors:
        return errors
    contract, _cpath, error = validate_run_state.load_contract_for(rundir, None)
    errors = [error] if error else validate_task_contract.validate(contract)
    if errors:
        return ["invalid task_contract.json: " + "; ".join(errors)]
    from .research_admission import admission
    protocol_errors = admission(rundir, 'launch' if required_plan is not None else 'approve_plan', contract=contract)
    if protocol_errors: return protocol_errors
    if delegated:
        try:
            from . import scientific_autonomy
            d=scientific_autonomy.verify_decision(contract,record,rundir)
            if plan not in d['value']['bounds']['compute_plans']:raise ValueError('approval exceeds delegated compute plans')
            if required_plan is not None:scientific_autonomy.plan_authority(rundir,required_plan=plan)
        except (OSError,ValueError,KeyError,TypeError) as exc:return [str(exc)]
    ladder = ("none", "dry", "smoke", "full", "scan")
    if ladder.index(plan) > ladder.index(contract["compute_plan"]):
        return [f"approved plan={plan} exceeds task_contract compute_plan={contract['compute_plan']}"]
    try:
        from ravel.validation import validate_checkin
        checkin = validate_task_contract.load_contract(paths[1])
        errors = validate_checkin.validate(checkin, base_dir=rundir)
        if type(checkin) is dict:
            if type(checkin.get("schema_version")) is not int:
                errors.append("checkin1.schema_version must be an exact integer")
            if checkin.get("kind") != "checkin1":
                errors.append("checkin1.kind must be checkin1")
    except (OSError, ValueError, UnicodeError, RecursionError) as e:
        errors = [str(e)]
    if errors:
        return ["invalid checkin1.json: " + "; ".join(errors)]
    try:
        budget = validate_task_contract.load_contract(paths[2])
        errors = validate_task_contract.validate(
            {**contract, "compute_plan": plan, "cost_estimate": budget})
        if type(budget) is dict and (type(budget.get("schema_version")) is not int
                                    or budget.get("schema_version") not in (1, 2, 3)
                                    or budget.get("generated_by") != "cost_preflight.py"):
            errors.append("cost artifact requires historical schema1, explicit uncalibrated schema2 or measured "
                          "schema3 and generated_by=cost_preflight.py")
        if type(budget) is dict and budget.get("schema_version") == 3 and not errors:
            from ravel.workflow.pilot_cost import verify_record
            errors += verify_record(budget)
    except (OSError, ValueError, UnicodeError, RecursionError) as e:
        errors = [str(e)]
    if errors:
        return ["invalid cost_preflight.json: " + "; ".join(errors)]
    if required_plan in BULK_PLANS and budget.get('calibration_status') == 'uncalibrated':
        return ['Production cost is uncalibrated for this process/model/settings/machine. '
                'Run an approved pilot (a smoke plan of the same process), then '
                '`ravel pilot-cost observe`, `ravel pilot-cost forecast` and '
                '`cost_preflight --from-forecast` to record the measured cost before bulk launch.']
    # Check again after validation reads. Rendered cards are committed as virtual
    # bytes in the plan, so their actual files also need a final fresh check.
    if 'approved_inputs' in record:
        try:
            current = _approval_inputs_snapshot(rundir, approval_input_paths(rundir))
            changed = approval_inputs.changes(rundir, record['approved_inputs'], current, approval_record=record)
            if changed:
                if disclose:
                    approval_inputs.record_deviations(rundir, changed)
                return ['stale or unbound approval: approved input changed: ' +
                        ', '.join(row['path'] for row in changed) + '; amend and re-approve CHECK-IN 1']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return [f'stale or unbound approval: {exc}; amend and re-approve CHECK-IN 1']
    matches, reason = provenance.verify_pair(record, generator, paths)
    if not matches:
        return ["stale or unbound approval: " + reason + "; re-record approval for the current inputs"]
    # Compute beyond the smoke run also waits for the CHECK-IN 2 go. Every launch path that names its
    # size (the native pipeline, the scan budget, the Bash guard's scan launches) checks it here.
    if required_plan in BULK_PLANS and contract.get("task_mode") not in NO_CHECKIN2_TASK_MODES:
        return checkin2_gate_errors(rundir, required_plan)
    return []


def verify_approval_envelope(rundir, required_plan):
    """Check the unchanged first approval and compute ceiling for a bounded correction.

    This does not confer action authority. Callers must additionally validate the
    exact admitted correction command and its frozen inputs before launching.
    """
    from .method_selection import launch_errors
    method_errors = launch_errors(rundir, required_plan)
    if method_errors:
        return method_errors
    errors = verify_approval(rundir)
    if errors:
        return errors
    from ravel.workflow.launch_authorization import parse_utc
    try:
        record = validate_task_contract.load_contract(os.path.join(rundir, "inputs/checkin1_approval.json"))
        parse_utc(record["generated_utc"])
        if required_plan not in APPROVAL_PLANS or APPROVAL_PLANS.index(required_plan) > APPROVAL_PLANS.index(record["approved_plan"]):
            raise ValueError("correction exceeds the first approval compute ceiling")
        return []
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]


@retry_conflict
def cmd_approve(args):
    """Record approval of the declared operation inputs, rendered cards and scope."""
    rd = args.rundir.rstrip("/")
    if not os.path.isdir(rd):
        print(f"workflow_state approve: not a directory: {rd}", file=sys.stderr)
        return 2
    from .method_selection import launch_errors
    method_errors = launch_errors(rd, args.plan)
    if method_errors:
        print('; '.join(method_errors), file=sys.stderr)
        return 1
    from .research_admission import admission
    protocol_errors = admission(rd, 'approve_plan', bind=True)
    if protocol_errors:
        print('; '.join(protocol_errors), file=sys.stderr)
        return 1
    try:
        from .completion_lifecycle import ensure_policy
        ensure_policy(rd)
        from . import review_points
        review_points.approve(Path(rd))
        paths = approval_input_paths(rd)
        snapshot = _approval_inputs_snapshot(rd, paths)
        from . import approval_inputs
        operation_paths, _rendered = approval_inputs.operation_inputs(rd, validate_task_contract.load_contract(paths[0]))
        missing = [p for p in operation_paths if not os.path.isfile(p)]
        if missing:
            raise ValueError('missing planned operation inputs: ' + ', '.join(missing))
        previous = read_json(Path(rd) / approval_inputs.APPROVAL) if (Path(rd) / approval_inputs.APPROVAL).exists() else {}
        changed = approval_inputs.changes(rd, previous.get('approved_inputs', []), snapshot,
                                         approval_record=previous) if previous else []
        if previous:
            prior_sha = provenance.sha256_file(Path(rd) / approval_inputs.APPROVAL)
            changed = [{**row, 'prior_approval_sha256': prior_sha} for row in changed]
        approval_custody(rd)  # an unreadable custody ledger refuses before anything is written
        stamp = operational_utc()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"workflow_state approve: REFUSED -- {exc}", file=sys.stderr)
        return 1
    # Fingerprint BEFORE validation; verify_approval recomputes after all reads. An edit
    # during validation cannot silently become part of the newly recorded approval.
    from .approval_authority import classify
    rec = {"authority": classify(scripted=getattr(args, "scripted", False), quote=args.quote),
           "schema_version": APPROVAL_VERSION,
           "generated_utc": stamp,
           "approved_plan": args.plan, "quote": args.quote,
           "task_contract": os.path.relpath(paths[0], rd),
           "checkin1": "inputs/checkin1.json", "cost_preflight": "inputs/cost_preflight.json",
           "approved_inputs": snapshot,
           "input_changes": previous.get('input_changes', []) + changed,
           **provenance.provenance_pair(APPROVAL_GENERATOR, paths)}
    errors = verify_approval(rd, rec)
    if errors:
        print("workflow_state approve: REFUSED -- " + "; ".join(errors), file=sys.stderr)
        return 1
    out = os.path.join(rd, "inputs", "checkin1_approval.json")
    approval_inputs.record_deviations(rd, changed, quote=args.quote)
    atomic_json(out, rec)
    record_approval_custody(rd, out, rec["authority"])
    # The approved plan, not a model, produces the run's research preregistration.
    try:
        from .research_launch import produce_if_required
        produce_if_required(rd)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"workflow_state approve: preregistration REFUSED -- {exc}", file=sys.stderr)
        return 1
    state, _ = load_state(rd)
    if state is not None:
        state.setdefault("checkins", []).append(
            {"id": "CHECKIN1-APPROVAL", "artifact": "inputs/checkin1_approval.json",
             "utc": rec["generated_utc"]})
        write_state(rd, state)
    print(f"approval recorded -> {out} (plan={args.plan}, authority={rec['authority']})")
    return 0


CHECKIN2_GO_VERSION = 3
CHECKIN2_GO_GENERATOR = "workflow_state.py go"


def checkin2_go_input_paths(rundir):
    """Bind the check-in, first approval, manifest and every reviewed evidence file."""
    from ravel.workflow.waypoint_evidence import bound_paths
    from ravel.workflow.physics_review import bound_paths as review_paths
    return [os.path.join(rundir, "inputs", "checkin2.json"),
            os.path.join(rundir, "inputs", "checkin1_approval.json"),
            *bound_paths(rundir), *review_paths(rundir)]


def verify_checkin2_go(rundir, record=None):
    """Return the errors that stop a CHECK-IN 2 go from authorising compute beyond the smoke run.

    The go binds the check-in, first approval and every file in the waypoint manifest.
    Editing any reviewed evidence or re-recording the first approval voids it.
    Like the first approval, this checks integrity, not who answered.
    """
    if record is None:
        try:
            record = validate_task_contract.load_contract(os.path.join(rundir, "inputs", "checkin2_go.json"))
        except (OSError, ValueError, UnicodeError, RecursionError) as e:
            return [f"checkin2_go.json cannot be read: {e}"]
    if type(record) is not dict:
        return ["checkin2_go.json must be an object"]
    delegated = record.get("schema_version") == 4
    fields = {"schema_version", "generated_by", "generated_utc", "decision", "quote", "checkin2",
              "checkin1_approval", "evidence_manifest", "input_fingerprint"}
    if delegated: fields |= {"authority", "delegation", "delegate_actor"}
    errors = [f"CHECK-IN 2 go missing required field {key!r}" for key in sorted(fields - record.keys())]
    errors += [f"CHECK-IN 2 go has unknown field {key!r}" for key in sorted(record.keys() - fields)]
    if type(record.get("schema_version")) is not int or record.get("schema_version") != (4 if delegated else CHECKIN2_GO_VERSION):
        errors.append(f"CHECK-IN 2 go schema_version must be integer {CHECKIN2_GO_VERSION}")
    for key in fields - {"schema_version", "delegation"}:
        value = record.get(key)
        if type(value) is not str or (key != "generated_utc" and not value.strip()):
            errors.append(f"CHECK-IN 2 go {key} must be a " + ("string" if key == "generated_utc" else "nonblank string"))
    if errors:
        return errors
    generator = "workflow_state.py delegated-go" if delegated else CHECKIN2_GO_GENERATOR
    if delegated:
        try:
            from . import scientific_autonomy
            d = scientific_autonomy.authorize(rundir, "checkin2_go")
            document = scientific_autonomy.effective_document(validate_task_contract.load_contract(os.path.join(rundir, "inputs", "task_contract.json")),Path(rundir))
            if (record["authority"] != "machine_under_user_delegation" or record["delegation"] != document["autonomy"]
                    or record["delegate_actor"] != d["value"]["delegate_actor"]):
                raise ValueError("machine decision exceeds its exact delegation")
        except (OSError, ValueError, KeyError, TypeError) as exc: return [str(exc)]
    if record["generated_by"] != generator:
        errors.append(f"CHECK-IN 2 go generated_by must be {CHECKIN2_GO_GENERATOR!r}")
    if record["decision"] != "GO":
        errors.append("CHECK-IN 2 go decision must be GO; an ADJUST changes the plan instead")
    try:
        paths = checkin2_go_input_paths(rundir)
        from ravel.workflow.launch_authorization import parse_utc
        parse_utc(record["generated_utc"])
    except (OSError, ValueError, TypeError) as exc:
        return [f"invalid CHECK-IN 2 evidence or timestamp: {exc}"]
    for key, path in zip(("checkin2", "checkin1_approval", "evidence_manifest"), paths):
        if record[key] != os.path.relpath(path, rundir):
            errors.append(f"CHECK-IN 2 go {key} must name {os.path.relpath(path, rundir)!r}")
    if errors:
        return errors
    approval_errors = verify_approval(rundir)
    if approval_errors:
        return ["the CHECK-IN 1 approval this go follows is invalid: " + "; ".join(approval_errors)]
    try:
        approval = read_json(paths[1])
        if parse_utc(approval["generated_utc"]) > parse_utc(record["generated_utc"]):
            return ["stale CHECK-IN 2 GO: timestamp precedes the current first approval"]
    except (OSError, ValueError) as exc:
        return [f"first approval needs an operational timestamp before GO: {exc}"]
    try:
        from ravel.validation import validate_checkin
        checkin = validate_task_contract.load_contract(paths[0])
        errors = validate_checkin.validate(checkin, base_dir=rundir)
        if type(checkin) is dict and checkin.get("kind") != "checkin2":
            errors.append("checkin2.kind must be checkin2")
    except (OSError, ValueError, UnicodeError, RecursionError) as e:
        errors = [str(e)]
    if errors:
        return ["invalid checkin2.json: " + "; ".join(errors)]
    from ravel.workflow.physics_review import gate_errors
    errors = gate_errors(rundir, "bulk")
    if errors:
        return ["CHECK-IN 2 physics review: " + "; ".join(errors)]
    matches, reason = provenance.verify_pair(record, generator, paths)
    if not matches:
        return ["stale or unbound CHECK-IN 2 go: " + reason
                + "; record the go again for the current CHECK-IN 2 and approval"]
    return []


def record_delegated_go(rundir):
    """Existing GO gate, machine-labelled and bounded by retained user delegation."""
    from . import scientific_autonomy
    rd = scientific_autonomy.review_context._safe_path(rundir)
    d = scientific_autonomy.authorize(rd, 'checkin2_go')
    from . import gate_wiring  # R2: a delegated epoch-two GO needs the checkin2_accept gate
    gate_wiring.require_delegated(rd, 'checkin2_accept', gate_wiring.checkin2_action(rd))
    contract = scientific_autonomy.effective_document(validate_task_contract.load_contract(str(rd/'inputs/task_contract.json')),rd)
    if contract.get('compute_plan') not in d['value']['bounds']['compute_plans']:
        raise ValueError('compute plan outside original delegated envelope; escalate')
    paths = checkin2_go_input_paths(str(rd))
    rec = {'schema_version':4, 'generated_utc':operational_utc(), 'decision':'GO',
           'quote':d['value']['quote'], 'authority':'machine_under_user_delegation',
           'delegation':contract['autonomy'], 'delegate_actor':d['value']['delegate_actor'],
           'checkin2':'inputs/checkin2.json', 'checkin1_approval':'inputs/checkin1_approval.json',
           'evidence_manifest':os.path.relpath(paths[2],rd),
           **provenance.provenance_pair('workflow_state.py delegated-go',paths)}
    errors = verify_checkin2_go(str(rd),rec)
    if errors:raise ValueError('; '.join(errors))
    from copy import deepcopy
    from . import execution
    intended=deepcopy(rec)
    path=rd/'inputs/checkin2_go.json'
    if path.exists():
        previous=validate_task_contract.load_contract(str(path))
        if not verify_checkin2_go(str(rd),previous):return previous
        # A fresh accepted cycle may stale an old GO. Preserve that actual record
        # before a new explicitly machine-labelled decision; never relabel it.
        history=rd/'logs/checkin2-go-history';history.mkdir(parents=True,exist_ok=True)
        raw=path.read_bytes();import hashlib
        old_sha=hashlib.sha256(raw).hexdigest()
        retained=history/(old_sha+'.json')
        if retained.exists():
            if retained.read_bytes()!=raw:raise ValueError('retained GO history changed')
        else:
            with retained.open('xb') as stream:stream.write(raw)
        if path.read_bytes()!=raw:raise ValueError('current GO changed during preservation')
        scientific_autonomy.authorize(rd,'checkin2_go')
        atomic_json(path,deepcopy(intended))
    else:
        from . import scientific_judgment
        scientific_judgment._new(path,deepcopy(intended))
    if verify_checkin2_go(str(rd)):raise ValueError('delegated GO changed before return')
    if execution.digest(read_json(path))!=execution.digest(intended):raise ValueError('delegated decision bytes differ from intended machine receipt')
    return intended


DELEGATED_APPROVAL_LOG='logs/delegated-approvals.jsonl'
REVIEW_POINTS_APPROVAL='inputs/review_points_approval.json'


def approval_custody(rundir):
    """Custody rows of the CHECK-IN 1 approvals RAVEL recorded for this run, oldest first."""
    from . import rdj_custody
    return rdj_custody.rows(rundir,'checkin1_approvals')


def record_approval_custody(rundir,path,authority):
    """Record a written CHECK-IN 1 approval's digest outside the run directory."""
    from . import rdj_custody
    return rdj_custody.append(rundir,'checkin1_approvals',{'approval_sha256':provenance.sha256_file(path),
                                                          'authority':authority})


def record_delegated_approval(rundir,plan):
    """Machine approval under a user delegation; a re-approval stays inside the delegation's bounds.

    A re-approval classifies every changed approved input against the prior record and
    refuses any path outside ``bounds.allowed_changed_paths``. It records the changes and
    their deviation rows, as the human path does. A missing prior approval is refused.
    """
    from .method_selection import require_launch
    require_launch(rundir, plan)
    from . import scientific_autonomy,execution
    from copy import deepcopy
    rd=scientific_autonomy.review_context._safe_path(rundir)
    d=scientific_autonomy.plan_authority(rd,required_plan=plan)
    from . import gate_wiring  # R2: a delegated epoch-two approval needs the approve_plan gate
    gate_wiring.require_delegated(rd,'approve_plan',gate_wiring.plan_action(rd,plan))
    document=scientific_autonomy.effective_document(validate_task_contract.load_contract(str(rd/'inputs/task_contract.json')),rd)
    from .research_admission import admission
    protocol_errors = admission(rd, 'approve_plan', contract=document, bind=True)
    if protocol_errors: raise ValueError('; '.join(protocol_errors))
    from .completion_lifecycle import ensure_policy
    ensure_policy(rd)
    from .completion_budget import reserve_delegated
    reserve_delegated(document, d, rd)
    from . import approval_inputs, review_points
    path=rd/'inputs/checkin1_approval.json'
    previous=read_json(path) if path.exists() else None
    recorded=approval_custody(rd)
    allowed=set(d['value']['bounds']['allowed_changed_paths'])
    if previous is None:
        # A deleted approval must not let the machine re-bind changed bytes as a first approval.
        state,_=load_state(str(rd))
        if recorded or (rd/DELEGATED_APPROVAL_LOG).exists() or (state is not None and any(
                c.get('id')=='CHECKIN1-APPROVAL' for c in state.get('checkins',[]))):
            raise ValueError(f'a recorded CHECK-IN 1 approval is missing (custody holds {len(recorded)}); delegated '
                             're-approval classifies changes against it and cannot start over')
    else:
        if 'approved_inputs' not in previous:
            raise ValueError('the prior approval has no byte commitments; a human re-approval is required')
        prior_sha=provenance.sha256_file(path)
        if recorded and recorded[-1]['record']['approval_sha256']!=prior_sha:
            raise ValueError('the prior approval differs from the custody record of the last CHECK-IN 1 approval; '
                             'it is not a baseline and a human re-approval is required')
        # The bounds check runs before RAVEL rewrites any approval input, so a refusal leaves
        # the standing approval as it was.
        before=_approval_inputs_snapshot(str(rd),approval_input_paths(str(rd)))
        outside=[row['path'] for row in approval_inputs.changes(str(rd),previous['approved_inputs'],before,
                                                                 approval_record=previous)
                 if row['path'] not in allowed]
        if outside:
            raise ValueError('delegated re-approval refuses changed inputs outside allowed_changed_paths: '
                             +', '.join(outside)+'; a human re-approval is required')
    review_points.approve(rd)
    paths=approval_input_paths(str(rd))
    snapshot=_approval_inputs_snapshot(str(rd), paths)
    changed=[]
    if previous is not None:
        changed=approval_inputs.changes(str(rd),previous['approved_inputs'],snapshot,approval_record=previous)
        # The derived review-points record is RAVEL's own write from the approved plan.
        outside=[row['path'] for row in changed if row['path'] not in allowed and row['path']!=REVIEW_POINTS_APPROVAL]
        if outside:
            raise ValueError('delegated re-approval refuses changed inputs outside allowed_changed_paths: '
                             +', '.join(outside)+'; a human re-approval is required')
        changed=[{**row,'prior_approval_sha256':prior_sha} for row in changed]
    record={'schema_version':3,'generated_utc':operational_utc(),'approved_plan':plan,'quote':d['value']['quote'],
        'task_contract':os.path.relpath(paths[0],rd),'checkin1':'inputs/checkin1.json','cost_preflight':'inputs/cost_preflight.json',
        'authority':'delegated_machine','delegation':document['autonomy'],'delegate_actor':d['value']['delegate_actor'],
        'approved_inputs':snapshot,
        **provenance.provenance_pair('workflow_state.py delegated-approve',paths)}
    if previous is not None:
        record['input_changes']=previous.get('input_changes',[])+changed
    errors=verify_approval(str(rd),record)
    if errors:raise ValueError('; '.join(errors))
    from . import scientific_judgment
    intended=deepcopy(record)
    approval_inputs.record_deviations(str(rd),changed,quote=record['quote'])
    if previous is None:
        scientific_judgment._new(path,deepcopy(intended))
    else:
        atomic_json(path,deepcopy(intended))
    from .research_launch import produce_if_required
    produce_if_required(rd)
    errors=verify_approval(str(rd))
    if errors or read_json(path)!=intended:raise ValueError('delegated CI1 decision changed: '+'; '.join(errors))
    record_approval_custody(rd,path,intended['authority'])
    log=rd/DELEGATED_APPROVAL_LOG
    log.parent.mkdir(parents=True,exist_ok=True)
    with open(log,'a',encoding='utf-8') as stream:
        stream.write(json.dumps({'utc':intended['generated_utc'],'approval_sha256':provenance.sha256_file(path),
                                 'input_changes':[row['path'] for row in changed]},sort_keys=True)+'\n')
    state,_=load_state(str(rd))
    if state is not None:
        state.setdefault('checkins',[]).append({'id':'CHECKIN1-APPROVAL','artifact':'inputs/checkin1_approval.json',
                                                'utc':intended['generated_utc'],'authority':intended['authority']})
        write_state(str(rd),state)
    return intended


def cmd_delegated_approve(args):
    try:record=record_delegated_approval(args.rundir,args.plan)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1
    print(json.dumps(record,indent=2,sort_keys=True));return 0


def cmd_delegated_go(args):
    try:record=record_delegated_go(args.rundir)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1
    print(json.dumps(record,indent=2,sort_keys=True));return 0


def cmd_revoke_delegation(args):
    from . import scientific_autonomy
    try:
        record=scientific_autonomy.revoke(args.rundir,user_text={'path':args.user_text,'sha256':args.user_text_sha256},quote=args.quote)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(str(exc),file=sys.stderr);return 1
    print(json.dumps(record,indent=2,sort_keys=True));return 0


def checkin2_gate_errors(rundir, required_plan):
    """Errors that block a launch at `required_plan`. Compute beyond the smoke run (full, scan) waits
    for a valid CHECK-IN 2 go; the smoke run that produces the waypoint, and anything smaller, never does."""
    if required_plan not in BULK_PLANS:
        return []
    errors = verify_checkin2_go(rundir)
    if not errors:
        return []
    return [f"CHECK-IN 2: a {required_plan} launch waits for a valid recorded human or delegated-machine GO -- "
            + "; ".join(errors) + "; record it with `workflow_state.py go --rundir <rd> --quote '<the reply>'`"]


@retry_conflict
def cmd_go(args):
    """Record the physicist's CHECK-IN 2 GO, bound to the CHECK-IN 2 artefact and the current approval."""
    rd = args.rundir.rstrip("/")
    if not os.path.isdir(rd):
        print(f"workflow_state go: not a directory: {rd}", file=sys.stderr)
        return 2
    errors = verify_approval(rd)
    if errors:
        print("workflow_state go: REFUSED -- " + "; ".join(errors), file=sys.stderr)
        return 1
    try:
        paths = checkin2_go_input_paths(rd)
        stamp = operational_utc()
    except (OSError, ValueError, TypeError) as exc:
        print(f"workflow_state go: REFUSED -- invalid checkin2 evidence: {exc}", file=sys.stderr)
        return 1
    # Fingerprint BEFORE validation, as for the approval: an edit during validation cannot slip in.
    rec = {"schema_version": CHECKIN2_GO_VERSION,
           "generated_utc": stamp,
           "decision": "GO", "quote": args.quote,
           "checkin2": "inputs/checkin2.json", "checkin1_approval": "inputs/checkin1_approval.json",
           "evidence_manifest": os.path.relpath(paths[2], rd),
           **provenance.provenance_pair(CHECKIN2_GO_GENERATOR, paths)}
    errors = verify_checkin2_go(rd, rec)
    if errors:
        print("workflow_state go: REFUSED -- " + "; ".join(errors), file=sys.stderr)
        return 1
    out = os.path.join(rd, "inputs", "checkin2_go.json")
    atomic_json(out, rec)
    from .approval_authority import classify
    record_approval_custody(rd, out, classify(quote=args.quote))
    state, _ = load_state(rd)
    if state is not None:
        state.setdefault("checkins", []).append(
            {"id": "CHECKIN2-GO", "artifact": "inputs/checkin2_go.json", "utc": rec["generated_utc"]})
        write_state(rd, state)
    print(f"CHECK-IN 2 go recorded -> {out}")
    return 0


def cmd_status(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state status: not a directory: {rundir}", file=sys.stderr)
        return 2
    state, err = load_state(rundir)
    if err:
        print(f"workflow_state status: {err}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(state, indent=2))
    else:
        print(f"run_state: {_state_path(rundir)}")
        print(f"  task_mode={state.get('task_mode')} compute_plan={state.get('compute_plan')} "
              f"routed={state.get('routed')}")
        print(f"  current_step={state.get('current_step')} ladder_rung={state.get('ladder_rung')}")
        for k in LIST_KEYS:
            print(f"  {k}: {len(state.get(k) or [])}")
        nr = state.get("next_required")
        print(f"  next_required={nr['what'] if nr else None}")
    return 0


def cmd_next(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state next: not a directory: {rundir}", file=sys.stderr)
        return 2
    _state, err = load_state(rundir)
    if err:
        print(f"workflow_state next: {err}", file=sys.stderr)
        return 3
    contract, _cpath, cerr = validate_run_state.load_contract_for(rundir, None)
    if cerr:
        print(f"workflow_state next: {cerr}", file=sys.stderr)
        return 3
    nr = compute_next_required(rundir, contract)
    if args.json:
        print(json.dumps(nr, indent=2))
    else:
        print(nr["what"] if nr else "(none -- required prefix satisfied)")
    return 0


def cmd_require(args):
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"workflow_state require: not a directory: {rundir}", file=sys.stderr)
        return 2
    state, err = load_state(rundir)
    if err:
        print(f"workflow_state require: {err}", file=sys.stderr)
        return 3
    kind, what = args.kind, args.what
    ok = False
    if kind == "skill":
        ok = any(e.get("skill") == what for e in state.get("skills_invoked") or [])
    elif kind == "command":
        ok = any(what in (e.get("cmd") or "") for e in state.get("compute_launched") or [])
    elif kind == "artifact":
        ok = os.path.isfile(os.path.join(rundir, what))
    elif kind == "stage":
        contract, _c, cerr = validate_run_state.load_contract_for(rundir, None)
        if cerr:
            print(f"workflow_state require: {cerr}", file=sys.stderr)
            return 3
        ok = validate_run_state.evaluate(rundir, contract, stage_limit=what)["exit"] == 0
    if ok:
        print(f"workflow_state require: OK ({kind}={what!r} satisfied)")
        return 0
    print(f"workflow_state require: FAIL ({kind}={what!r} not satisfied)", file=sys.stderr)
    return 1


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--rundir", required=True)
    pi.add_argument("--session-id", default="")
    pi.add_argument("--force", action="store_true")
    pi.set_defaults(func=cmd_init)

    pr = sub.add_parser("record")
    pr.add_argument("--rundir")
    pr.add_argument("--project-dir")
    pr.add_argument("--kind", required=True, choices=sorted(RECORD_KINDS))
    pr.add_argument("--payload")                 # JSON object (skill/compute/subagent/edit)
    pr.add_argument("--what")                    # string shortcut for route/failure
    pr.set_defaults(func=cmd_record)

    pa = sub.add_parser("advance")
    pa.add_argument("--rundir", required=True)
    pa.add_argument("--to", required=True, choices=validate_run_state.STAGE_ORDER)
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=cmd_advance)

    pv = sub.add_parser("approve")
    pv.add_argument("--rundir", required=True)
    pv.add_argument("--scripted", action="store_true", help="record scripted experiment assent")
    pv.add_argument("--quote", required=True,
                    help="the physicist's go-ahead reply, quoted verbatim")
    pv.add_argument("--plan", default="smoke", choices=APPROVAL_PLANS)
    pv.set_defaults(func=cmd_approve)

    pg = sub.add_parser("go")
    pg.add_argument("--rundir", required=True)
    pg.add_argument("--quote", required=True,
                    help="the physicist's CHECK-IN 2 GO reply, quoted verbatim")
    pg.set_defaults(func=cmd_go)

    pm = sub.add_parser("delegated-approve")
    pm.add_argument("--rundir",required=True)
    pm.add_argument("--plan",required=True,choices=APPROVAL_PLANS)
    pm.set_defaults(func=cmd_delegated_approve)
    pd = sub.add_parser("delegated-go")
    pd.add_argument("--rundir",required=True)
    pd.set_defaults(func=cmd_delegated_go)
    px = sub.add_parser("revoke-delegation")
    px.add_argument("--rundir",required=True)
    px.add_argument("--user-text",required=True)
    px.add_argument("--user-text-sha256",required=True)
    px.add_argument("--quote",required=True)
    px.set_defaults(func=cmd_revoke_delegation)

    ps = sub.add_parser("status")
    ps.add_argument("--rundir", required=True)
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_status)

    pn = sub.add_parser("next")
    pn.add_argument("--rundir", required=True)
    pn.add_argument("--json", action="store_true")
    pn.set_defaults(func=cmd_next)

    pq = sub.add_parser("require")
    pq.add_argument("--rundir", required=True)
    pq.add_argument("--kind", required=True, choices=("skill", "command", "artifact", "stage"))
    pq.add_argument("--what", required=True)
    pq.set_defaults(func=cmd_require)
    return ap


def selftest():
    import tempfile
    fails = []

    def check(label, ok, detail=""):
        print(f"[selftest] {label}: {detail}  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append(label)

    def _reproduce_rundir(td):
        # A reproduction requires the census and trap sweep before route.
        rd = os.path.join(td, "run")
        os.makedirs(os.path.join(rd, "inputs"))
        contract = {"schema_version": 1, "prompt": "selftest", "task_mode": "reproduce", "detector_mode": "rivet-smearing",
                    "stat_mode": "best-sr-counting", "required_user_inputs": [], "assumptions": ["fx"],
                    "compute_plan": "none", "approval_required": True}
        with open(os.path.join(rd, "inputs", "task_contract.json"), "w") as fh:
            json.dump(contract, fh)
        return rd

    with tempfile.TemporaryDirectory(prefix="workflow_state_selftest_") as td:
        rd = _reproduce_rundir(td)
        rc = main(["init", "--rundir", rd])
        state, err = load_state(rd)
        ok = rc == 0 and err is None and state is not None
        check("1 init writes run_state", ok, f"rc={rc}")
        if ok:
            check("2 init populates every schema key",
                  all(k in state for k in LIST_KEYS) and state["generated_by"] == GENERATOR
                  and len(state["input_fingerprint"]) == 64 and state["task_mode"] == "reproduce")
            check("3 init refuses to clobber", main(["init", "--rundir", rd]) == 3)
        # --- record ---
        assert main(["record", "--rundir", rd, "--kind", "skill",
                     "--payload", json.dumps({"skill": "physicist-intake"})]) == 0
        s2, _ = load_state(rd)
        check("4 record appends skill", [e.get("skill") for e in s2["skills_invoked"]] == ["physicist-intake"])
        check("5 record bad payload exits 2",
              main(["record", "--rundir", rd, "--kind", "edit", "--payload", "{}"]) == 2)
        # route/failure state-mutator kinds -- the real writers of routed + open_failure_records
        check("5a record route flips routed",
              main(["record", "--rundir", rd, "--kind", "route", "--what", "reproduce"]) == 0
              and load_state(rd)[0]["routed"] is True)
        check("5b record failure registers open_failure_records",
              main(["record", "--rundir", rd, "--kind", "failure", "--what", "logs/gen.failure.json"]) == 0
              and load_state(rd)[0]["open_failure_records"] == ["logs/gen.failure.json"])
        # a route record with no routing content is a silent no-op (no row, no rewrite)
        _pre = open(_state_path(rd), "rb").read()
        check("5c record route without content is a no-op",
              main(["record", "--rundir", rd, "--kind", "route"]) == 0
              and open(_state_path(rd), "rb").read() == _pre)
        # --- advance ---
        check("6 advance to resource_census allowed",
              main(["advance", "--rundir", rd, "--to", "resource_census"]) == 0)
        check("7 advance to route refused (census/trap_sweep unmet)",
              main(["advance", "--rundir", rd, "--to", "route"]) == 1)
        # --- require (fallback gate) ---
        # NB: use a skill NOT recorded by any earlier selftest case -- case 4 already recorded
        # 'physicist-intake' into this SHARED rundir, so the first `require` on it would return 0.
        # 'verification-panel' is unrecorded here, so the first require legitimately FAILs (exit 1).
        check("8 require skill FAIL then PASS after record",
              main(["require", "--rundir", rd, "--kind", "skill", "--what", "verification-panel"]) == 1
              and main(["record", "--rundir", rd, "--kind", "skill",
                        "--payload", json.dumps({"skill": "verification-panel"})]) == 0
              and main(["require", "--rundir", rd, "--kind", "skill", "--what", "verification-panel"]) == 0)
        check("9 require stage route refused",
              main(["require", "--rundir", rd, "--kind", "stage", "--what", "route"]) == 1)
        check("10 status/next read-only exit 0",
              main(["status", "--rundir", rd]) == 0 and main(["next", "--rundir", rd]) == 0)

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("workflow_state selftest: PASS")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
