"""A compact, derived handoff. The packet is a view, never an authority to execute."""
from pathlib import Path

from ravel.validation import validate_run_state, validate_task_contract
from ravel.paths import workflow_instruction
from . import execution, study_deadline, workflow_state
from .state_io import atomic_json


BLOCKER_INSTRUCTIONS = {
    "task_contract": "docs/workflow/start.md",
    "resource_census": "docs/workflow/steps/02-inputs.md",
    "trap_sweep": "docs/workflow/checklists/physics-traps.md",
    "route": "docs/workflow/checklists/choosing-routine.md",
    "figure_contract": "docs/workflow/checklists/figure-contract.md",
    "basis_manifest": "docs/workflow/steps/02-inputs.md",
    "generation": "docs/workflow/steps/03-generate.md",
    "analysis": "docs/workflow/steps/04-analyze.md",
    "statistics": "docs/workflow/steps/07-exclude.md",
    "result_pack": "docs/workflow/steps/05-visualize.md",
    "verification": "docs/workflow/steps/09-verify.md",
}


def build_packet(rundir):
    root = Path(rundir).resolve()
    if (root / "inputs/science-plan.json").exists():
        from ravel.workflow.science import packet
        return packet(rundir)
    if (root / "inputs/science-held.json").exists():
        from ravel.workflow.science import held_packet
        return held_packet(root)
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
    from . import physics_review, review_enforcement
    review = physics_review.status(root) if review_enforcement.required(root) else None
    if review is not None:
        review_errors = review.get("errors", []) + review.get("live_errors", [])
        blocked[:0] = [{"kind": "physics_review", "what": error,
                        "state": review["state"]} for error in review_errors]
        if review["state"] == "correction_admitted" and not review_errors:
            blocked.insert(0, {"kind": "physics_review", "state": review["state"],
                "what": "execute only the admitted correction, then open and review its fresh evidence",
                "next_stage": review.get("next_correction_stage"), "correction_id": review["correction_id"]})
    # A missing CHECK-IN 1 approval precedes every post-approval stage.
    status_of = {s["name"]: s["status"] for s in gate["stages"]}
    for item in validate_run_state.ordered_blockers(str(root), contract, gate, satisfied=("PASS", "N/A")):
        if item["kind"] == "artifact":
            blocked.append({"kind": "stage", "what": item["what"], "status": status_of[item["what"]]})
        elif item["kind"] == "invariant":
            blocked.append({"kind": "invariant", "what": item["what"], "detail": item["why"]})
        else:
            blocked.append(item)
    approval_errors = workflow_state.verify_approval(str(root))
    calculation_accepted = contract["task_mode"] == "calculation" and gate.get("parent_task_accepted") is True
    literal_accepted = calculation_accepted and gate.get('completion_scope') == 'complete_literal_dimensionless_calculation'
    if calculation_accepted:
        # Literal completion rechecks its ordinary approval/worker. Scientific
        # completion retains its existing current child and whole-parent reviews.
        approval_errors = []
    stage_records = execution.load_execution(root)["stages"] if execution_present and not execution_errors else {}
    handoff = None
    from .intake import handoff_applicable
    if handoff_applicable(contract) and any(
            row['id'] == 'original-task' for row in contract.get('task_requirements', {}).get('assignments', [])):
        from .intake import execution_handoff
        handoff = execution_handoff({"path": str(contract_path), "sha256": contract_hash,
                                     "size": Path(contract_path).stat().st_size}, base_dir=root)
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
        "intake_handoff": handoff,
        "parent_task": {"original_request": contract["prompt"],
                        "obligations": contract.get("task_requirements", {}).get("obligations", []),
                        "assignments": contract.get("task_requirements", {}).get("assignments", []),
                        "completion": gate.get("parent_task_accepted", "not evaluated; successful stages do not close the parent goal")},
        "approval": {"valid": not approval_errors, "errors": approval_errors,
                     "note": ("Actual bound literal child approval and execution reverified; no new command authority." if literal_accepted
                              else "Existing scoped child and whole-parent scientific completion reverified; no new command authority." if calculation_accepted
                              else "A status view does not authorize a new command; executors verify scope again.")},
        "lifecycle_verdict": gate["verdict"],
        "physics_review": review,
        "execution": {"status": "invalid" if execution_errors else "verified" if execution_present else "absent",
                      "errors": execution_errors,
                      "stages": {name: {"status": r["status"], "attempt": r["attempt_id"],
                                        "receipt_sha256": r.get("receipt_sha256")}
                                 for name, r in stage_records.items()}},
        # Declared delivery deadline: time left, margin warning and the one action that delivers.
        "study_deadline": study_deadline.packet_block(root, contract=contract, review=review,
                                                      execution_errors=execution_errors),
        "next_required": blocked[0] if blocked else None, "blockers": blocked,
        "next_instruction": (workflow_instruction("docs/reference/intake-and-challenges.md")
                             if blocked and contract["task_mode"] == "calculation"
                             else workflow_instruction("docs/workflow/checklists/check-ins.md")
                             if blocked and blocked[0].get("kind") == "checkin"
                             else workflow_instruction(BLOCKER_INSTRUCTIONS[blocked[0]["what"]])
                             if blocked and blocked[0].get("kind") == "stage"
                             and blocked[0].get("what") in BLOCKER_INSTRUCTIONS else None),
        "required_user_inputs": contract["required_user_inputs"],
        "instructions": ["docs/workflow/start.md", "docs/workflow/checklists/check-ins.md"],
        "instruction_resources": [workflow_instruction(logical) for logical in
                                  ("docs/workflow/start.md", "docs/workflow/checklists/check-ins.md")],
    }


def _resume_migration(rundir):
    """Bind an existing unbound run on resume; the receipt records the machine action."""
    from .research_launch import migrate
    try:
        receipt = migrate(rundir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'refused', 'reason': str(exc)}
    return None if receipt is None else {'status': 'migrated', 'receipt': 'research/migration.json',
                                         'prior_results': receipt['prior_results']['label']}


def _ended_status(packet):
    """Procedure status of a run that has ended, else None; read from fields real packets carry."""
    parent = packet.get('parent_task', {})
    stages = [r.get('status') for r in packet.get('execution', {}).get('stages', {}).values()]
    if 'running' in stages: return None
    if parent.get('completion') is True: return packet.get('lifecycle_verdict', 'incomplete')
    if (packet.get('physics_review') or {}).get('state') == 'stopped': return 'aborted'
    if parent and any(s in ('failed', 'aborted') for s in stages):
        return 'aborted' if 'aborted' in stages else 'failed'
    return None


def write_packet(rundir):
    migration = _resume_migration(rundir)
    packet = build_packet(rundir)
    if migration is not None:
        packet['research_protocol_migration'] = migration
    status = _ended_status(packet)
    if status is not None:
        from .procedure_export import export_for_delivery
        try:
            packet['procedure_export'] = export_for_delivery(rundir, status=status)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # A refused export stays visible without blocking the status refresh.
            packet['procedure_export'] = {'status': 'refused', 'reason': str(exc), 'execution_authorized': False}
    atomic_json(Path(rundir) / "current_state.json", packet)
    return packet
