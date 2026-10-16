"""Plan, approve, execute and verify scoped workflows using shared custody gates."""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import re
import shutil

from ravel.paths import module_command
from ravel.validation.validate_task_contract import validate as validate_contract
from ravel.workflow import execution, placement, workflow_state
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
    if 'goal_binding' in spec:
        from .completion_children import checkin_projection
        parent_projection = checkin_projection(spec['goal_binding'], source.parent)
    else:
        parent_projection = {}
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
            grant = spec.get("execution", {}).get("backend_plan", {}).get("resources", {}).get("cpus", 1)
            generation_plan = prepare_generation(rd, g, source.parent, inputs, lease_cpus=grant)
            model_hash = generation_plan.pop("model_source_sha256")
        atomic_json(rd / SPEC, frozen)
        stage = {"stage": "parton" if spec["mode"] == "generate" else "likelihood",
                 "command": module_command("ravel.physics.scoped", rd), "cwd": str(rd),
                 "inputs": inputs, "outputs": ["outputs"], "depends_on": []}
        if "execution" in spec:
            stage["command"], plan_path = placement.pin(rd, stage["stage"], stage["command"], stage["outputs"],
                                                        spec["execution"]["backend_plan"], spec["max_seconds"])
            inputs.append(plan_path)
        binding = execution.plan_stage(rd, stage["stage"], stage["command"], inputs, stage["outputs"], [], rd)
        proposal = {"schema_version": 1, "mode": spec["mode"], "stages": [stage],
                    **(generation_plan if spec["mode"] == "generate" else {}),
                    "stage_binding": binding, "model_source_sha256": model_hash,
                    "generator_source_sha256": (execution.digest(binding["input_snapshot"][str(rd / "inputs/madgraph")])
                                                if spec["mode"] == "generate" else None),
                    "max_seconds": spec["max_seconds"], "max_attempts": 1,
                    "approval_mode": spec["approval_mode"], "expert_review": False}
        from .prepared_runtime import capture
        proposal["prepared_runtime"] = capture(binding)
        atomic_json(rd / PLAN, proposal)
        cost = {"schema_version": 1, "generated_by": "cost_preflight.py", "generated_utc": "",
                "mode": "full", "points": 1, "parallel": 1, "backend": "native",
                "walltime_h": [0, spec["max_seconds"] / 3600],
                "note": "User-specified hard ceiling for one scoped execution attempt, including a failed attempt."}
        if spec["mode"] == "generate":
            cost["events_per_point"] = spec["generation"]["events"]
            cost["points"] = len(spec["generation"].get("parameter_points") or [None])
        if spec["mode"] == "generate":
            contract["detector_mode"] = "particle-level" if "shower" in spec["generation"] else "parton-level"
        contract.update(compute_plan="full", cost_estimate=cost, required_user_inputs=[],
                        assumptions=spec["assumptions"], blocking=[],
                        execution_plan={"path": PLAN, "sha256": execution.file_hash(rd / PLAN)})
        errors = validate_contract(contract)
        if errors:
            raise ValueError("invalid planned contract: " + "; ".join(errors))
        previous = execution.file_hash(rd / "inputs/task_contract.json")
        atomic_json(rd / "inputs/task_contract.json", contract)
        # a release run's run_init snapshot follows RAVEL's own planning rewrite (pre-CHECK-IN 1).
        from ravel.workflow import gate_wiring
        gate_wiring.record_contract_rewrite(rd, previous, reason="scoped_plan")
        from .completion_lifecycle import seal_cost
        cost = seal_cost(rd, cost)
        atomic_json(rd / "inputs/cost_preflight.json", cost)
        checkin = {"schema_version": 1, "kind": "checkin1", "sections": {
            "i": {"request": contract["prompt"], "source": spec["source"], "scope": spec["mode"], **parent_projection},
            "i-b": {"recipe": frozen, "execution_plan_sha256": execution.file_hash(rd / PLAN),
                    **({key: proposal[key] for key in ("generator_selection", "beam_content", "pdf", "model_origin",
                                                       "lhe_transform", "spec_reconciliation", "generation_convention") if proposal.get(key)}
                       if spec["mode"] == "generate" else {}),
                    **({"placement": placement.checkin(rd)} if "execution" in spec else {})},
            "ii": {"figure": figure_description(spec),
                   "scope": "scoped diagnostic; no external paper figure or detector comparison is claimed"},
            "iii": {"waypoint": "Stop after one supervised attempt; inspect every event or all six numerical crossings before comparison."},
            "iv": cost,
            "v": [{"id": f"F{i + 1}", "assumption": value} for i, value in enumerate(spec["assumptions"])],
            "vi": [{"mode": mode, "text": text} for mode, text in (
                ("answer", "Approve this exact recipe and ceiling"), ("ask", "Clarify an assumption before approval"),
                ("propose", "Create a revised plan in a new run"))],
        }}
        if spec["mode"] == "generate":
            record = proposal["generation_convention"]
            for key in ("basis_identifier", "ew_input_scheme", "validity_cutoff", "terms"):
                if record[key] is None:
                    checkin["sections"]["v"].append({"id": f"F{len(checkin['sections']['v']) + 1}",
                        "assumption": "CHECK-IN: generation " + key + " undeclared"})
        from ravel.validation.validate_checkin import validate, pinned_records, with_registered_sections
        reading, request = pinned_records(rd, contract)
        if request is not None:
            from .request_plan import checkin_sections
            sections, flags = checkin_sections(reading, request)
            checkin['sections'].update(sections)
            for flag in flags:
                checkin['sections']['v'].append({'id': f"F{len(checkin['sections']['v']) + 1}", **flag})
        # The trusted registry adds the sections every route shows, after the numbered flags they read.
        checkin = with_registered_sections(checkin, str(rd))
        errors = validate(checkin, base_dir=str(rd))
        if errors:
            raise ValueError("invalid concrete check-in: " + "; ".join(errors))
        atomic_json(rd / "inputs/checkin1.json", checkin)
        if 'goal_binding' in spec:
            from .completion_children import register_child
            register_child(rd, spec['goal_binding'], run_kind='scoped')
        (rd / "CHECKIN1.md").write_text(
            "# CHECK-IN 1: scoped execution proposal\n\n" + contract["prompt"] +
            "\n\nReview `inputs/checkin1.json` for the exact recipe, source and assumptions. "
            f"The ceiling is {spec['max_seconds']} seconds, one worker, one attempt including failures. "
            f"Approval mode: {spec['approval_mode']}. Scripted assent is not expert scientific review.\n\n"
            + generation_scope(spec) + generation_notes(proposal)
            + (placement.describe(rd) if "execution" in spec else "") +
            "Likelihood inference applies only to the supplied model. "
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


def _resolve(value, base):
    path = Path(value).expanduser()
    return (Path(base) / path).resolve() if not path.is_absolute() else path.resolve()


def prepare_generation(rd, g, base, inputs, *, lease_cpus=1):
    """Bind the generator runtime, model, PDF, transform and intent of a generation plan.

    Mutates the frozen generation section ``g`` (runtime paths, copied inputs),
    appends bound inputs and returns the plan fields recorded for CHECK-IN 1 and
    the worker.
    """
    from ravel.physics import beam_content, generator_versions
    from ravel.workflow import spec_reconciliation
    from ravel.physics.scoped import generation_resources, installed_pdf
    resources = generation_resources(g, lease_cpus)
    plan = {"generation_resources": resources} if "nb_core" in g else {}
    install = installed_pdf(g, base)
    if install:
        g["pdf_install_record"] = install["path"]
        inputs.append(install["path"])
        inputs.append(install["set_path"])
    if "runtime" in g and "generator" in g:
        raise ValueError("supply either runtime paths or a generator version, not both")
    beams, errors = beam_content.content(g)
    if errors:
        raise ValueError("; ".join(errors))
    if "generator" in g:
        chosen, record = generator_versions.select(g["generator"]["version"], beams["minimum_generator_version"],
                                                   generator_versions.installed_madgraph())
        g["runtime"] = {"madgraph": chosen["tree"], "python": chosen["python"], "compiler": chosen["compiler"]}
        if g["run_settings"]["pdlabel"] == "lhapdf":
            g["runtime"]["lhapdf_config"] = chosen["lhapdf_config"]
        plan["generator_selection"] = record
    runtime = _resolve(g["runtime"]["madgraph"], base)
    if not (runtime / "bin/mg5_aMC").is_file() or not (runtime / "VERSION").is_file():
        raise ValueError("MadGraph runtime is missing its executable or version")
    try:
        version = generator_versions.runtime_version(runtime)
    except ValueError:
        version = None
    # Snapshot a private, dereferenced runtime. MG can update model caches
    # and configuration only in the worker's copy, not the installation.
    for name in ("python", "compiler"):
        p = _resolve(g["runtime"][name], base)
        if not p.is_file():
            raise ValueError(f"missing native {name}: {p}")
        g["runtime"][name] = str(p)
        inputs.append(str(p))
    origin = None
    if "model_origin" in g:
        from ravel.physics.model_derivation_bridge import read_qualified_handoff
        ufo, handoff, handoff_pin = read_qualified_handoff(_resolve(g["model_origin"], base))
        if not (g["model"] == ufo.name or g["model"].startswith(ufo.name + "-")):
            raise ValueError(f"model {g['model']!r} does not name the qualified UFO {ufo.name!r}")
        if (runtime / "models" / ufo.name).exists():
            raise ValueError(f"the generator runtime already has a model named {ufo.name}; rename the derived UFO")
        origin = {"kind": "qualified_ufo", "handoff": handoff_pin, "ufo": str(ufo),
                  "ufo_manifest": handoff["ufo_manifest"], "accepted_review": handoff["accepted_review"]}
        model_dir_source = ufo
    else:
        candidates = [d for d in (runtime / "models").iterdir()
                      if d.is_dir() and (g["model"] == d.name or g["model"].startswith(d.name + "-"))]
        if not candidates:
            raise ValueError("requested model is not installed in the supplied runtime; "
                             "a derived model needs a reviewed model_origin handoff")
        model_dir_source = max(candidates, key=lambda p: len(p.name))
    restriction = g["model"][len(model_dir_source.name):].lstrip("-")
    if restriction and not (model_dir_source / f"restrict_{restriction}.dat").is_file():
        raise ValueError("requested model restriction is absent")
    shutil.copytree(runtime, rd / "inputs/madgraph", symlinks=False,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo", "*.pkl"))
    if origin:
        shutil.copytree(model_dir_source, rd / "inputs/madgraph/models" / model_dir_source.name, symlinks=False,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.pyo", "*.pkl"))
        shutil.copyfile(origin["handoff"]["path"], rd / "inputs/qualified-ufo.json")
        g["model_origin"] = "inputs/qualified-ufo.json"
        inputs.append(g["model_origin"])
        plan["model_origin"] = origin
    g["runtime"]["madgraph"] = "inputs/madgraph"
    inputs.append("inputs/madgraph")
    # Use relative file names in model identity so two independent run
    # directories can compare equivalent model bytes.
    files = rd / "inputs/madgraph/models" / model_dir_source.name
    plan["model_source_sha256"] = execution.digest({str(p.relative_to(files)): execution.file_hash(p)
                                                    for p in sorted(files.rglob("*")) if p.is_file()})
    flavours = None
    if "lhapdf_config" in g["runtime"]:
        lhaid = g["run_settings"]["lhaid"]
        row = beam_content.pdf_manifest_row(lhaid)
        config, info = lhapdf_set(g["runtime"]["lhapdf_config"], lhaid, base)
        if install and info.resolve().parent.parent != Path(install["data_path"]).resolve():
            raise ValueError("LHAPDF data path differs from the declared install record")
        if info.parent.name != row["name"]:
            raise ValueError(f"LHAPDF identifier {lhaid} is installed as {info.parent.name}, "
                             f"but native/setup/pdf-sets.json pins {row['name']}")
        flavours = beam_content.read_info_flavours(info)
        g["runtime"]["lhapdf_config"] = str(config)
        inputs += [x for x in (str(config), str(info)) if x not in inputs]
        plan["pdf"] = {"pdlabel": "lhapdf", "lhaid": lhaid, "name": row["name"], "manifest_sha256": row["sha256"],
                       "digest_status": row["digest_status"], "info_sha256": execution.file_hash(info),
                       "flavours": flavours}
        if install:
            plan["pdf"]["install_record"] = install
    else:
        plan["pdf"] = {"pdlabel": g["run_settings"]["pdlabel"], "lhaid": g["run_settings"]["lhaid"],
                       "builtin": True}
    beams, errors = beam_content.content(g, pdf_flavours=flavours, generator_version=version, census_required=True)
    if errors:
        raise ValueError("; ".join(errors))
    plan["beam_content"] = beams
    if "shower" in g:
        if "tune" in g["shower"]:
            from ravel.physics.pythia_cards import tune_commands
            g["shower"]["settings"], plan["shower_tune"] = tune_commands(g["shower"]["tune"], g["shower"]["settings"])
            from importlib.resources import files as package_files
            inputs.append(str(package_files('ravel').joinpath('data/shower/tunes.json')))
        for line in g["shower"]["settings"]:
            if line.split('=', 1)[0].strip().lower() == "slha:file":
                source_slha = input_file(line.split('=', 1)[1].strip(), base)
                inputs.append(str(source_slha))
        from ravel.physics.scoped_shower import probe
        python = Path(g["shower"]["python"]).expanduser()
        python = (Path(base) / python).absolute() if not python.is_absolute() else python
        if not python.is_file():
            raise ValueError(f"missing shower python: {python}")
        g["shower"]["python"] = str(python)
        inputs += [x for x in dict.fromkeys([str(python), *[str(p) for p in probe(python)]]) if x not in inputs]
    param_text = None
    if "parameter_card" in g:
        card = input_file(g["parameter_card"], base)
        shutil.copyfile(card, rd / "inputs/param_card.dat")
        g["parameter_card"] = "inputs/param_card.dat"
        inputs.append(g["parameter_card"])
        param_text = (rd / g["parameter_card"]).read_text()
        if "decay_states" in g:
            from ravel.physics import simplified_spectrum as ss
            doc = ss.parse_slha(param_text)
            states = g["decay_states"]
            closure = ss.check_card(doc, **states, sm_masses={}, model_pdgs=ss.ufo_particle_pdgs(files))
            if not closure["passed"]:
                raise ValueError("decay-state plan refused: " + "; ".join(f["message"] for f in closure["findings"]))
            outside = closure["outside_model"]
            plan["decay_states"] = closure
            if outside:
                shower_card = rd / "inputs/shower-spectrum.slha"
                shower_card.write_text(param_text)
                inputs.append("inputs/shower-spectrum.slha")
                plan["shower_slha"] = {"path": "inputs/shower-spectrum.slha", "sha256": execution.file_hash(shower_card)}
                param_text = ss.write_slha(ss.generator_document(doc, outside))
                (rd / g["parameter_card"]).write_text(param_text)
                if "shower" in g:
                    from ravel.physics.pythia_cards import shower_decay_commands
                    g["shower"]["settings"] = shower_decay_commands(g["shower"]["settings"], shower_card, outside)
    if "lhe_transform" in g:
        from ravel.physics import lhe_transform
        rules = lhe_transform.load_rules(input_file(g["lhe_transform"], base))
        implied = lhe_transform.validate_rules(rules)
        if "shower" in g:
            missing = lhe_transform.missing_settings({"required_downstream_settings": implied["required_settings"]},
                                                     g["shower"]["settings"])
            if missing:
                raise ValueError("the LHE transform requires these shower settings: " + ", ".join(missing))
        atomic_json(rd / "inputs/lhe-transform-rules.json", rules)
        g["lhe_transform"] = "inputs/lhe-transform-rules.json"
        inputs.append(g["lhe_transform"])
        deviations = [f"LHE transform '{rules['name']}' rule {r['id']}: status {r['match']['status']} PDG "
                      f"{r['match']['pdg']} -> {r['replace_pdg']}" + (f", mass {r['mass_gev']} GeV" if "mass_gev" in r else "")
                      + f". {r['rationale']}" for r in rules["rules"]]
        plan["lhe_transform"] = {"name": rules["name"], "rationale": rules["rationale"],
                                 "approximation": rules.get("approximation"),
                                 "rules_sha256": execution.file_hash(rd / g["lhe_transform"]),
                                 "declared_changes": implied["breaks"],
                                 "required_downstream_settings": implied["required_settings"],
                                 "deviations": deviations}
    proc_lines = [f"import model {g['model']}", *[f"define {k} = {v}" for k, v in g["definitions"].items()],
                  f"generate {g['process']}"]
    from ravel.physics import generation_conventions
    process_card = rd / "inputs/generation-process.dat"
    process_card.write_text("\n".join(proc_lines) + "\n")
    inputs.append("inputs/generation-process.dat")
    plan["generation_convention"] = generation_conventions.build(process_card.read_text(),
        {"path": str(process_card), "sha256": execution.file_hash(process_card)},
        {"identifier": g["model"], "pin": plan["model_source_sha256"], "restriction": restriction or "default"},
        g.get("conventions"))
    from ravel.physics.scoped import run_card
    settings = run_card("\n".join(f"{v} = {k}" for k, v in g["run_settings"].items()))
    sim = spec_reconciliation.simulation_from_cards(proc_lines, settings, param_text)
    records = {}
    for point in g.get("parameter_points") or [None]:
        overrides = (point or {}).get("overrides", [])
        view = dict(sim, param=spec_reconciliation.apply_overrides(sim["param"], overrides) if sim["param"] else None)
        record = spec_reconciliation.reconcile(spec_reconciliation.intent_for(g, overrides), view, stage="pre-launch")
        records[point["id"] if point else "single"] = record
        if not record["satisfied"]:
            raise ValueError("declared physics and the staged cards disagree"
                             + (f" at point {point['id']}" if point else "") + ": " + "; ".join(record["violations"]))
    plan["spec_reconciliation"] = {k: {"satisfied": v["satisfied"], "unknowns": v["unknowns"], "flags": v["flags"]}
                                   for k, v in records.items()}
    deviations = list(plan.get("lhe_transform", {}).get("deviations", []))
    if plan.get("shower_slha"):
        deviations.append("Outside-model stable invisible states and their decay channels are excluded from the generation card; "
                          "full supplied SLHA is retained for the shower: " + str(plan["decay_states"]["outside_model"]))
    (rd / "DEVIATIONS.md").write_text("# Deviations\n\n" + ("\n".join("- " + d for d in deviations) if deviations else
                                     "None. A changed specification requires a new plan.") + "\n")
    return plan


def lease_resources(rundir):
    """CPU grant carried by the machine lease's reverified approved binding."""
    rd = Path(rundir).resolve()
    if not (rd / PLAN).is_file():
        return None
    proposal = read_json(rd / PLAN)
    if proposal.get("mode") != "generate" or "generation_resources" not in proposal:
        return None
    proposal = verify_plan(rd, require_approval=True)
    spec = read_json(rd / SPEC)
    from ravel.physics.scoped import generation_resources
    grant = spec.get("execution", {}).get("backend_plan", {}).get("resources", {}).get("cpus", 1)
    expected = generation_resources(spec["generation"], grant)
    if expected != proposal["generation_resources"]:
        raise ValueError("generation CPU grant differs from the approved plan")
    return expected


def generation_notes(proposal):
    notes = []
    if proposal.get("mode") != "generate":
        return ""
    if proposal.get("generator_selection"):
        sel = proposal["generator_selection"]
        notes.append(f"Generator: MadGraph {sel['selected']} ({sel['reason']}).")
    beams = proposal.get("beam_content") or {}
    if beams.get("lepton_or_photon_partons"):
        notes.append(f"Lepton or photon partons from the proton: {beams['lepton_or_photon_partons']} "
                     f"through LHAPDF set {proposal['pdf'].get('name')} ({proposal['pdf']['lhaid']}).")
    if proposal.get("model_origin"):
        notes.append("Model: reviewed derived UFO from " + proposal["model_origin"]["handoff"]["path"] + ".")
    if proposal.get("generation_resources"):
        notes.append("MadGraph resources under one native-job lease: " + str(proposal["generation_resources"]) + ".")
    if proposal.get("decay_states"):
        notes.append("Outside-model stable invisible states: " + str(proposal["decay_states"]["outside_model"]) + ".")
    if proposal.get("shower_tune"):
        notes.append("Shower preset: " + proposal["shower_tune"]["name"] + "; source: " + proposal["shower_tune"]["source"] + ".")
    if proposal.get("lhe_transform"):
        t = proposal["lhe_transform"]
        notes.append(f"LHE transform '{t['name']}' before the shower: " + " ".join(t["deviations"])
                     + (f" Required shower settings: {', '.join(t['required_downstream_settings'])}."
                        if t["required_downstream_settings"] else "") + (f" Approximation: {t['approximation']}" if t.get("approximation") else ""))
    unknown = sorted({u for v in (proposal.get("spec_reconciliation") or {}).values() for u in v["unknowns"]})
    if unknown:
        notes.append("Physics-intent checks the staged cards cannot decide yet: " + "; ".join(unknown) + ".")
    return ("\n".join(notes) + "\n\n") if notes else ""


def lhapdf_set(config, lhaid, base):
    """Resolve an installed LHAPDF set by identifier; nothing is downloaded."""
    import subprocess
    path = Path(config).expanduser()
    path = (Path(base) / path).absolute() if not path.is_absolute() else path
    if not path.is_file():
        raise ValueError(f"missing lhapdf-config: {path}")
    done = subprocess.run([str(path), "--datadir"], capture_output=True, text=True, timeout=60)
    datadir = Path(done.stdout.strip().split()[-1]) if done.returncode == 0 and done.stdout.strip() else None
    if datadir is None or not (datadir / "pdfsets.index").is_file():
        raise ValueError("lhapdf-config does not report a data directory with pdfsets.index")
    for line in (datadir / "pdfsets.index").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == str(lhaid):
            info = datadir / fields[1] / (fields[1] + ".info")
            if not info.is_file():
                raise ValueError(f"LHAPDF set {fields[1]} ({lhaid}) is indexed but not installed")
            return path, info
    raise ValueError(f"LHAPDF identifier {lhaid} is not in the installed pdfsets.index")


def figure_description(spec):
    if spec["mode"] != "generate":
        return "Observed and median expected CLs with the 0.05 threshold"
    g = spec["generation"]
    if "observables" not in g:
        return "Final-state mass with MC error bars"
    levels = "parton and particle level" if "shower" in g else "parton level"
    return "Typed observables (" + ", ".join(row["id"] for row in g["observables"]) + f") at {levels} with MC error bars"


def generation_scope(spec):
    if spec["mode"] != "generate":
        return ""
    if "shower" in spec["generation"]:
        return "Generation ends at audited parton events showered by Pythia 8 at particle level, without detector simulation. "
    return "Generation ends at audited parton events. "


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
    from .prepared_runtime import validate_plan
    validate_plan(proposal)
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
    worker = module_command("ravel.physics.scoped", rd)
    if "execution" in spec:
        placement.verify(rd, expected_name, worker, ["outputs"], spec["execution"]["backend_plan"], spec["max_seconds"])
        worker = placement.worker_command(rd, expected_name)
    if (stage["stage"] != expected_name or stage["command"] != worker
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
        code = workflow_state.cmd_approve(argparse.Namespace(rundir=str(rd), plan="full", quote=quote, scripted=scripted))
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
    if (record.get("status") != "running"
            or record.get("fingerprint") != proposal["stage_binding"]["fingerprint"]):
        raise ValueError("worker must be launched by its current supervised attempt")
    if record.get("supervisor_pid") == os.getppid():
        if record.get("child_pid") not in (None, os.getpid()):
            raise ValueError("worker must be launched by its current supervised attempt")
        return proposal
    # A placed stage: this worker is the payload of the attempt's native backend job.
    custody = execution.await_worker_registration(rd, stage)
    if custody.get("mode") != "backend":
        raise ValueError("worker must be launched by its current supervised attempt")
    return {**proposal, "output_directory": str(Path(custody["output_dir"]) / "outputs")}


def verify_supervised_stage(rundir, stage, command, inputs, outputs, depends_on, cwd, log, kill_secs, events,
                            *, resume=False, allow_running=False):
    """Admit only the exact genuinely approved zero-event likelihood stage.

    A numerical-only calculation has no meaningful generated-event count. Its
    immutable scoped plan and actual full CHECK-IN 1 approval supply the launch
    authority instead; they do not relax admission for generic commands.
    """
    rd = root_path(rundir)
    proposal = verify_plan(rd, require_approval=True)
    if proposal['mode'] != 'likelihood' or type(events) is not int or events != 0:
        raise ValueError('zero-event scoped launch requires the approved likelihood-only mode')
    declared = proposal['stages'][0]
    if (stage != declared['stage'] or type(kill_secs) not in (int, float)
            or kill_secs != proposal['max_seconds']
            or execution.log_path(rd, log) != execution.log_path(rd, 'logs/scoped-worker.log')):
        raise ValueError('scoped stage, log or hard ceiling differs from the approved likelihood plan')
    actual = execution.plan_stage(rd, stage, list(command), list(inputs), list(outputs),
                                  list(depends_on), cwd)
    expected = proposal['stage_binding']
    def scope(binding, key):
        return {str(execution.resolve_path(rd, value, output=key == 'outputs'))
                for value in binding[key]}
    if (any(actual[key] != expected[key] for key in
            ('command', 'cwd', 'input_snapshot', 'parents', 'runtime'))
            or any(scope(actual, key) != scope(expected, key) for key in ('inputs', 'outputs'))):
        raise ValueError('scoped command, input/output scope, dependencies or runtime differs from the approved plan')
    attempt = read_json(rd / 'execution_attempt.json')
    if (type(attempt.get('attempt')) is not int or attempt['attempt'] != 1
            or attempt.get('plan_sha256') != execution.file_hash(rd / PLAN)
            or attempt.get('budget_seconds') != proposal['max_seconds']):
        raise ValueError('scoped launch requires its bound one-attempt budget receipt')
    record = execution.load_execution(rd)['stages'].get(stage)
    if record is not None:
        if type(record) is not dict:
            raise ValueError('invalid scoped stage receipt')
        current = (allow_running and record.get('status') == 'running'
                   and record.get('supervisor_pid') == os.getpid()
                   and record.get('fingerprint') == expected['fingerprint'])
        reusable = resume and execution.reusable(rd, stage, expected)
        if not current and not reusable:
            raise ValueError('the one approved scoped attempt is already spent; only verified resume is permitted')
    return proposal


def run(rundir, *, resume=False):
    from . import wms_policy
    wms_policy.require_dispatch(rundir)
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
        # Generation launches under its approved full rung with its declared event
        # population; a likelihood-only stage has no events and its own envelope.
        if proposal["mode"] == "generate":
            g = read_json(rd / SPEC)["generation"]
            events, required = g["events"] * len(g.get("parameter_points") or [None]), "full"
        else:
            events, required = 0, None
        placed = "execution" in read_json(rd / SPEC)
        code = supervise(stage["stage"], str(rd), events, "logs/scoped-worker.log", stage["command"],
                         kill_secs=proposal["max_seconds"], poll=placement.WORKER_POLL, grace=2,
                         inputs=stage["inputs"], outputs=stage["outputs"], depends_on=[], cwd=str(rd),
                         required_plan=required,
                         backend_plan=str(rd / placement.PLAN) if placed else None)
        state, error = workflow_state.load_state(str(rd))
        if not error:
            state["current_step"] = "verification" if not code else ("generation" if proposal["mode"] == "generate" else "statistics")
            state["next_required"] = workflow_state.compute_next_required(str(rd), read_json(rd / "inputs/task_contract.json"))
            workflow_state.write_state(str(rd), state)
        from ravel.workflow.current_state import write_packet
        packet = write_packet(rd)
        return code or (0 if packet["lifecycle_verdict"] == "PASS" else 3)


def evaluate(rundir, contract, stage_limit=None):
    from ravel.validation.validate_run_state import STAGE_ORDER, required_stages
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
    levels = required_stages(contract)["levels"]
    order = STAGE_ORDER[:STAGE_ORDER.index(stage_limit) + 1] if stage_limit else STAGE_ORDER
    for name in order:
        level = levels[name]
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
