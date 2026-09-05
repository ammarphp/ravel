"""A compact, derived handoff. The packet is a view, never an authority to execute."""
from pathlib import Path

from ravel.validation import validate_run_state, validate_task_contract
from . import execution, workflow_state
from .state_io import atomic_json


def build_packet(rundir):
    root = Path(rundir).resolve()
    contract, contract_path, error = validate_run_state.load_contract_for(str(root), None)
    if error:
        raise ValueError(error)
    contract_hash = execution.file_hash(contract_path)
    errors = validate_task_contract.validate(contract)
    if errors:
        raise ValueError("invalid current contract: " + "; ".join(errors))
    state, error = workflow_state.load_state(str(root))
    if error:
        raise ValueError(error)
    state_hash = execution.file_hash(root / "run_state.json")
    gate = validate_run_state.evaluate(str(root), contract, strict=True)
    execution_errors = execution.validate_execution(root)
    execution_present = (root / execution.STATE_NAME).exists()
    blocked = [{"kind": "execution", "what": error} for error in execution_errors]
    blocked.extend({"kind": "stage", "what": s["name"], "status": s["status"]}
                   for s in gate["stages"] if s["required"] == "R"
                   and s["status"] not in ("PASS", "N/A"))
    blocked.extend({"kind": "invariant", "what": i["name"], "detail": i["detail"]}
                   for i in gate["invariants"] if i["status"] == "FAIL")
    approval_errors = workflow_state.verify_approval(str(root))
    stage_records = execution.load_execution(root)["stages"] if execution_present and not execution_errors else {}
    if (execution.file_hash(contract_path) != contract_hash or
            execution.file_hash(root / "run_state.json") != state_hash):
        raise ValueError("run inputs changed while deriving current state; retry the status command")
    return {
        "schema_version": 1, "generated_utc": execution.utc_now(), "rundir": str(root),
        "role": "derived view; revalidate source artifacts before execution or delivery",
        "sources": {"contract": str(contract_path), "contract_sha256": contract_hash,
                    "run_state_revision": state.get("revision", 0),
                    "run_state_sha256": state_hash},
        "request": {"task_mode": contract["task_mode"], "stat_mode": contract["stat_mode"],
                    "compute_plan": contract["compute_plan"], "targets": contract.get("targets", {}),
                    "intent": contract.get("intake", {}).get("objective", contract["prompt"])[:1600]},
        "approval": {"valid": not approval_errors, "errors": approval_errors,
                     "note": "A status view does not authorize a new command; executors verify scope again."},
        "lifecycle_verdict": gate["verdict"],
        "execution": {"status": "invalid" if execution_errors else "verified" if execution_present else "absent",
                      "errors": execution_errors,
                      "stages": {name: {"status": r["status"], "attempt": r["attempt_id"],
                                        "receipt_sha256": r.get("receipt_sha256")}
                                 for name, r in stage_records.items()}},
        "next_required": blocked[0] if blocked else None, "blockers": blocked,
        "required_user_inputs": contract["required_user_inputs"],
        "instructions": ["docs/workflow/start.md", "docs/workflow/checklists/check-ins.md"],
    }


def write_packet(rundir):
    packet = build_packet(rundir)
    atomic_json(Path(rundir) / "current_state.json", packet)
    return packet
