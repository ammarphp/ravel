"""Plan, approve, execute and verify scoped workflows using shared custody gates."""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import re
import shutil

from ravel.paths import module_command
from ravel.validation.validate_task_contract import validate as validate_contract
from ravel.workflow import execution, workflow_state
from ravel.workflow.scoped_spec import MODES, input_file, require_valid
from ravel.workflow.state_io import atomic_json, file_lock, read_json

PLAN = "inputs/scoped-plan.json"
SPEC = "inputs/scoped.json"


def root_path(value):
    raw = Path(value).expanduser().absolute()
    if raw.is_symlink() or not raw.is_dir():
        raise ValueError("rundir must be an existing directory, not a symlink")
    if any((raw / rel).is_symlink() for rel in ("inputs", "outputs", "work", "logs", "run_state.json", "execution_state.json", "execution_attempt.json")):
        raise ValueError("scoped state and artifact roots must not be symlinks")
    return raw.resolve()


def plan(rundir, spec_path):
    rd = root_path(rundir)
    source = Path(spec_path).expanduser().resolve()
    spec = read_json(source)
    require_valid(spec)
    contract = read_json(rd / "inputs/task_contract.json")
    errors = validate_contract(contract)
    if errors:
        raise ValueError("invalid intake contract: " + "; ".join(errors))
    if contract["task_mode"] != spec["mode"]:
        raise ValueError("specification mode differs from the original request; use an explicit new intake")
    with file_lock(rd / "logs/scoped.lock", blocking=False):
        if any((rd / p).exists() for p in (PLAN, SPEC, "execution_state.json", "inputs/checkin1_approval.json")):
            raise ValueError("a plan or execution already exists; preserve it and create a new run for a changed proposal")
        frozen = deepcopy(spec)
        inputs = [SPEC]
        model_hash = None
        if spec["mode"] == "likelihood":
            from ravel.physics.scoped import prepare_workspace
            try:
                workspace = prepare_workspace(spec, source.parent)
            except Exception as exc:
                raise ValueError(f"supplied likelihood cannot be executed: {exc}") from exc
            atomic_json(rd / "inputs/workspace.json", workspace)
            inputs.append("inputs/workspace.json")
            if "workspace" in frozen["likelihood"]:
                frozen["likelihood"]["workspace"] = "inputs/workspace.json"
        else:
            g = frozen["generation"]
            if re.search(r"[\s'\";]", str(rd)):
                raise ValueError("native MadGraph adapter requires a run path without whitespace or quotes")
            runtime = Path(g["runtime"]["madgraph"]).expanduser()
            runtime = (source.parent / runtime).resolve() if not runtime.is_absolute() else runtime.resolve()
            if not (runtime / "bin/mg5_aMC").is_file() or not (runtime / "VERSION").is_file():
                raise ValueError("MadGraph runtime is missing its executable or version")
            # Snapshot a private, dereferenced runtime. MG can update model caches
            # and configuration only in the worker's copy, not the installation.
            for name in ("python", "compiler"):
                p = Path(g["runtime"][name]).expanduser()
                p = (source.parent / p).resolve() if not p.is_absolute() else p.resolve()
                if not p.is_file():
                    raise ValueError(f"missing native {name}: {p}")
                g["runtime"][name] = str(p)
                inputs.append(str(p))
            model_name = g["model"]
            candidates = [d for d in (runtime / "models").iterdir()
                          if d.is_dir() and (model_name == d.name or model_name.startswith(d.name + "-"))]
            if not candidates:
                raise ValueError("requested model is not installed in the supplied runtime")
            model_dir = max(candidates, key=lambda p: len(p.name))
            restriction = model_name[len(model_dir.name):].lstrip("-")
            if restriction and not (model_dir / f"restrict_{restriction}.dat").is_file():
                raise ValueError("requested model restriction is absent")
            shutil.copytree(runtime, rd / "inputs/madgraph", symlinks=False,
                            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo", "*.pkl"))
            g["runtime"]["madgraph"] = "inputs/madgraph"
            inputs.append("inputs/madgraph")
            # Use relative file names in model identity so two independent run
            # directories can compare equivalent model bytes.
            files = rd / "inputs/madgraph/models" / model_dir.name
            model_hash = execution.digest({str(p.relative_to(files)): execution.file_hash(p)
                                           for p in sorted(files.rglob("*")) if p.is_file()})
            if "parameter_card" in g:
                card = input_file(g["parameter_card"], source.parent)
                shutil.copyfile(card, rd / "inputs/param_card.dat")
                g["parameter_card"] = "inputs/param_card.dat"
                inputs.append(g["parameter_card"])
        atomic_json(rd / SPEC, frozen)
        stage = {"stage": "parton" if spec["mode"] == "generate" else "likelihood",
                 "command": module_command("ravel.physics.scoped", rd), "cwd": str(rd),
                 "inputs": inputs, "outputs": ["outputs"], "depends_on": []}
        binding = execution.plan_stage(rd, stage["stage"], stage["command"], inputs, stage["outputs"], [], rd)
        proposal = {"schema_version": 1, "mode": spec["mode"], "stages": [stage],
                    "stage_binding": binding, "model_source_sha256": model_hash,
                    "generator_source_sha256": (execution.digest(binding["input_snapshot"][str(rd / "inputs/madgraph")])
                                                if spec["mode"] == "generate" else None),
                    "max_seconds": spec["max_seconds"], "max_attempts": 1,
                    "approval_mode": spec["approval_mode"], "expert_review": False}
        atomic_json(rd / PLAN, proposal)
        cost = {"schema_version": 1, "generated_by": "cost_preflight.py", "generated_utc": "",
                "mode": "full", "points": 1, "parallel": 1, "backend": "native",
                "walltime_h": [0, spec["max_seconds"] / 3600],
                "note": "User-specified hard ceiling for one scoped execution attempt, including a failed attempt."}
        if spec["mode"] == "generate":
            cost["events_per_point"] = spec["generation"]["events"]
        contract.update(compute_plan="full", cost_estimate=cost, required_user_inputs=[],
                        assumptions=spec["assumptions"], blocking=[],
                        execution_plan={"path": PLAN, "sha256": execution.file_hash(rd / PLAN)})
        errors = validate_contract(contract)
        if errors:
            raise ValueError("invalid planned contract: " + "; ".join(errors))
        atomic_json(rd / "inputs/task_contract.json", contract)
        atomic_json(rd / "inputs/cost_preflight.json", cost)
        checkin = {"schema_version": 1, "kind": "checkin1", "sections": {
            "i": {"request": contract["prompt"], "source": spec["source"], "scope": spec["mode"]},
            "i-b": {"recipe": frozen, "execution_plan_sha256": execution.file_hash(rd / PLAN)},
            "ii": {"figure": "Final-state mass with MC error bars" if spec["mode"] == "generate" else "Observed and median expected CLs with the 0.05 threshold",
                   "scope": "scoped diagnostic; no external paper figure or detector comparison is claimed"},
            "iii": {"waypoint": "Stop after one supervised attempt; inspect every event or all six numerical crossings before comparison."},
            "iv": cost,
            "v": [{"id": f"F{i + 1}", "assumption": value} for i, value in enumerate(spec["assumptions"])],
            "vi": [{"mode": mode, "text": text} for mode, text in (
                ("answer", "Approve this exact recipe and ceiling"), ("ask", "Clarify an assumption before approval"),
                ("propose", "Create a revised plan in a new run"))],
        }}
        from ravel.validation.validate_checkin import validate
        errors = validate(checkin, base_dir=str(rd))
        if errors:
            raise ValueError("invalid concrete check-in: " + "; ".join(errors))
        atomic_json(rd / "inputs/checkin1.json", checkin)
        (rd / "CHECKIN1.md").write_text(
            "# CHECK-IN 1: scoped execution proposal\n\n" + contract["prompt"] +
            "\n\nReview `inputs/checkin1.json` for the exact recipe, source and assumptions. "
            f"The ceiling is {spec['max_seconds']} seconds, one worker, one attempt including failures. "
            f"Approval mode: {spec['approval_mode']}. Scripted assent is not expert scientific review.\n\n"
            "Generation ends at audited parton events. Likelihood inference applies only to the supplied model. "
            "Neither establishes detector acceptance, coverage, or reproduction of a paper.\n\n"
            "After approval: `ravel run --rundir <this-run>`. A changed recipe or failed attempt needs a new plan.\n")
        state, error = workflow_state.load_state(str(rd))
        if error:
            raise ValueError(error)
        state.update(compute_plan="full", next_required={"kind": "checkin", "what": "CHECK-IN 1 approval", "why": "concrete scoped plan is ready"})
        workflow_state.write_state(str(rd), state)
    from ravel.workflow.current_state import write_packet
    write_packet(rd)
    return proposal


def verify_plan(rundir, *, require_approval=False):
    rd = root_path(rundir)
    contract = read_json(rd / "inputs/task_contract.json")
    errors = validate_contract(contract)
    if errors or contract["task_mode"] not in MODES:
        raise ValueError("not a valid scoped contract: " + "; ".join(errors))
    pin = contract.get("execution_plan", {})
    if pin.get("path") != PLAN or execution.file_hash(rd / PLAN) != pin.get("sha256"):
        raise ValueError("missing or stale approved execution-plan binding")
    proposal = read_json(rd / PLAN)
    spec = read_json(rd / SPEC)
    require_valid(spec)
    if proposal.get("mode") != contract["task_mode"] or spec["mode"] != proposal["mode"]:
        raise ValueError("scope changed after intake")
    if proposal.get("max_attempts") != 1 or proposal.get("max_seconds") != spec["max_seconds"]:
        raise ValueError("scoped budget differs from specification")
    if proposal.get("approval_mode") != spec["approval_mode"]:
        raise ValueError("approval mode differs from specification")
    if len(proposal["stages"]) != 1:
        raise ValueError("scoped adapter requires exactly its one supervised stage")
    stage = proposal["stages"][0]
    expected_name = "parton" if spec["mode"] == "generate" else "likelihood"
    if (stage["stage"] != expected_name or stage["command"] != module_command("ravel.physics.scoped", rd)
            or stage["outputs"] != ["outputs"] or stage["depends_on"]):
        raise ValueError("execution plan does not invoke the supported scoped worker")
    binding = execution.plan_stage(rd, stage["stage"], stage["command"], stage["inputs"],
                                   stage["outputs"], stage["depends_on"], stage["cwd"])
    if binding != proposal["stage_binding"]:
        raise ValueError("stale plan: source, runtime or scientific input bytes changed; create a new plan")
    if require_approval:
        errors = workflow_state.verify_approval(str(rd), required_plan="full")
        if errors:
            raise ValueError("; ".join(errors))
    return proposal


def approve(rundir, quote, *, scripted=False):
    rd = root_path(rundir)
    with file_lock(rd / "logs/scoped.lock", blocking=False):
        proposal = verify_plan(rd)
        if scripted != (proposal["approval_mode"] == "scripted_yes"):
            raise ValueError("approval mode must match the reviewed proposal; scripted assent is not physicist review")
        code = workflow_state.cmd_approve(argparse.Namespace(rundir=str(rd), plan="full", quote=quote))
        if not code:
            state, error = workflow_state.load_state(str(rd))
            if error:
                raise ValueError(error)
            state.update(routed=True, current_step="route")
            workflow_state.write_state(str(rd), state)
        return code


def verify_worker(rundir):
    """An approved plan alone does not authorize an unsupervised/repeated worker."""
    rd = root_path(rundir)
    proposal = verify_plan(rd, require_approval=True)
    attempt = read_json(rd / "execution_attempt.json")
    if attempt.get("attempt") != 1 or attempt.get("plan_sha256") != execution.file_hash(rd / PLAN):
        raise ValueError("worker requires the budgeted attempt receipt")
    stage = proposal["stages"][0]["stage"]
    record = execution.load_execution(rd)["stages"].get(stage, {})
    if (record.get("status") != "running" or record.get("supervisor_pid") != os.getppid()
            or record.get("child_pid") not in (None, os.getpid())
            or record.get("fingerprint") != proposal["stage_binding"]["fingerprint"]):
        raise ValueError("worker must be launched by its current supervised attempt")
    return proposal


def run(rundir, *, resume=False):
    rd = root_path(rundir)
    with file_lock(rd / "logs/scoped.lock", blocking=False):
        proposal = verify_plan(rd, require_approval=True)
        stage = proposal["stages"][0]
        if (rd / "execution_attempt.json").exists() or (rd / "execution_state.json").exists():
            errors = execution.validate_completed_execution(rd, proposal["stages"])
            if not resume or errors:
                raise ValueError("the one approved attempt is already spent; --resume only verifies a valid completed result. "
                                 "Inspect retained failures and create a new plan before additional compute")
            return 0 if evaluate(rd, read_json(rd / "inputs/task_contract.json"))["verdict"] == "PASS" else 1
        atomic_json(rd / "execution_attempt.json", {"plan_sha256": execution.file_hash(rd / PLAN),
                    "attempt": 1, "budget_seconds": proposal["max_seconds"], "started_utc": execution.utc_now()})
        from ravel.workflow.stage_supervisor import supervise
        code = supervise(stage["stage"], str(rd), 0, "logs/scoped-worker.log", stage["command"],
                         kill_secs=proposal["max_seconds"], poll=.2, grace=2,
                         inputs=stage["inputs"], outputs=stage["outputs"], depends_on=[], cwd=str(rd))
        state, error = workflow_state.load_state(str(rd))
        if not error:
            state["current_step"] = "verification" if not code else ("generation" if proposal["mode"] == "generate" else "statistics")
            state["next_required"] = workflow_state.compute_next_required(str(rd), read_json(rd / "inputs/task_contract.json"))
            workflow_state.write_state(str(rd), state)
        from ravel.workflow.current_state import write_packet
        packet = write_packet(rd)
        return code or (0 if packet["lifecycle_verdict"] == "PASS" else 3)


def evaluate(rundir, contract, stage_limit=None):
    from ravel.validation.validate_run_state import STAGE_ORDER, STAGE_MATRIX
    rd = Path(rundir)
    plan_error, approval_errors, execution_errors, result_errors = [], [], [], []
    try:
        proposal = verify_plan(rd)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        proposal = None
        plan_error = [str(exc)]
    if proposal:
        approval_errors = workflow_state.verify_approval(str(rd), required_plan="full")
        execution_errors = execution.validate_completed_execution(rd, proposal["stages"])
        if not execution_errors:
            try:
                verification = read_json(rd / "outputs/verification.json")
                result = read_json(rd / "outputs/result.json")
                recipe = read_json(rd / "outputs/recipe.json")
                figure = read_json(rd / "outputs/figure.json")
                from ravel.validation.validate_checkin import validate as validate_checkin
                checkin_errors = validate_checkin(read_json(rd / "outputs/checkin2.json"))
                if checkin_errors:
                    raise ValueError("invalid result check-in: " + "; ".join(checkin_errors))
                if verification.get("passed") is not True or verification.get("scope") != contract["task_mode"]:
                    raise ValueError("missing scoped verification")
                if not recipe.get("recipe") or recipe["sha256"] != execution.digest(recipe["recipe"]):
                    raise ValueError("missing or invalid executed recipe")
                if figure.get("plot_lint") != "PASS" or figure.get("png_dpi", 0) < 200:
                    raise ValueError("figure quality gate did not pass")
                if contract["task_mode"] == "generate" and result.get("passed") is not True:
                    raise ValueError("event audit did not pass")
                if contract["task_mode"] == "likelihood":
                    status = result["limit_status"]
                    if status["observed"] != "resolved" or any(v != "resolved" for v in status["expected"]):
                        raise ValueError("unresolved likelihood crossings")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                result_errors = [str(exc)]
    stages = []
    order = STAGE_ORDER[:STAGE_ORDER.index(stage_limit) + 1] if stage_limit else STAGE_ORDER
    for name in order:
        level = STAGE_MATRIX[contract["task_mode"]][name]
        errors = []
        if name != "task_contract" and level == "R":
            errors += plan_error
            if name == "route":
                errors += approval_errors
            if name in ("generation", "statistics", "result_pack", "verification"):
                errors += approval_errors + execution_errors + result_errors
        status = "N/A" if level == "N/A" else "FAIL" if errors else "PASS"
        stages.append({"name": name, "required": level, "status": status, "artifact": PLAN if proposal else None,
                       "checks": [{"name": "scoped-contract", "level": "FAIL" if errors else "INFO",
                                   "msg": "; ".join(errors) if errors else f"{contract['task_mode']} scoped obligation"}]})
    passed = all(stage["status"] in ("PASS", "N/A") for stage in stages)
    return {"rundir": str(rd), "task_mode": contract["task_mode"], "stat_mode": contract["stat_mode"],
            "compute_plan": contract["compute_plan"], "legacy": False, "stages": stages, "invariants": [],
            "verdict": "PASS" if passed else "FAIL", "exit": 0 if passed else 1,
            "scope": "scoped workflow delivery; no detector/coverage/paper-reproduction certification"}


def differences(left, right, path="recipe"):
    if isinstance(left, dict) and isinstance(right, dict):
        return [d for k in sorted(left.keys() | right.keys()) for d in (
            differences(left[k], right[k], f"{path}.{k}") if k in left and k in right else
            [{"field": f"{path}.{k}", "left": left.get(k), "right": right.get(k)}])]
    return [] if type(left) is type(right) and left == right else [{"field": path, "left": left, "right": right}]


def compare(left, right):
    records = []
    errors = []
    for label, path in (("left", left), ("right", right)):
        try:
            rd = root_path(path)
            verify_plan(rd, require_approval=True)
            result = evaluate(rd, read_json(rd / "inputs/task_contract.json"))
            if result["verdict"] != "PASS":
                raise ValueError("scoped delivery/integrity has not passed")
            records.append(read_json(rd / "outputs/recipe.json")["recipe"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{label}: {exc}")
    mismatch = differences(*records) if not errors else []
    return {"schema_version": 1, "comparable": not errors and not mismatch, "errors": errors,
            "differences": mismatch, "left": str(Path(left).absolute()), "right": str(Path(right).absolute()),
            "scope": "effective recipe equivalence only; not agreement, accuracy ranking, uncertainty closure or expert review"}
