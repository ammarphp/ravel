"""Scientific workers for approved scoped workflows (invoked by the supervisor)."""
from collections import Counter
import gzip
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from ravel.workflow.state_io import atomic_json, read_json
from ravel.workflow.execution import digest
from ravel.physics import final_state_observables as fso


def number(token):
    value = float(token.replace("D", "e").replace("d", "e"))
    if not math.isfinite(value):
        raise ValueError("nonfinite scientific number")
    return value


def scalar(token):
    text = token.strip().strip("'\"")
    if text.lower() in ("true", ".true.", "false", ".false."):
        return text.lower() in ("true", ".true.")
    try:
        return number(text)
    except ValueError:
        if text.lower() in ("nan", "inf", "+inf", "-inf", "infinity"):
            raise ValueError("nonfinite scientific value")
        return " ".join(text.lower().split())


def run_card(text):
    result = {}
    for line in text.splitlines():
        active = re.split(r"[!#]", line, maxsplit=1)[0].strip()
        if not active:
            continue
        if "=" not in active:
            raise ValueError(f"unparsed run-card line: {active}")
        value, key = (p.strip() for p in active.rsplit("=", 1))
        key = key.lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in result:
            raise ValueError(f"invalid/duplicate run-card key: {key}")
        result[key] = scalar(value)
    if not result:
        raise ValueError("empty effective run card")
    return result


def parameter_recipe(text):
    """Keep every active SLHA row; only comments, whitespace and number spelling vary.

    Ordering is deliberately preserved. A conservative mismatch is safer than
    sorting decay rows or unfamiliar model blocks into a false equivalence.
    """
    rows = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            rows.append([scalar(token) for token in line.split()])
    if not rows or not any(row[0] == "block" for row in rows):
        raise ValueError("missing effective SLHA parameters")
    return rows


def audit_lhe(path, generation, *, seed=None):
    """Stream the entire completed LHE, checking every event, not a preview.

    Positive uniform nominal LO weights only. Extra reweighting information is
    rejected until its normalization has a supported contract. ``seed`` replaces
    the generation seed for one point of a parameter batch.
    """
    path = Path(path)
    seed = generation["seed"] if seed is None else seed
    opener = gzip.open if path.suffix == ".gz" else open
    header, init = None, None
    masses, weights, checks = [], [], {}
    typed = "observables" in generation
    observable = generation.get("observable", {})
    census = observable["final_state_pdg"] if "observable" in generation else generation.get("final_state_pdg")
    final_expected = Counter(census) if census is not None else None
    observed = {row["id"]: [] for row in generation.get("observables", [])}
    with opener(path, "rt", encoding="utf-8") as stream:
        parser = ET.iterparse(stream, events=("end",))
        for event, node in parser:
            if node.tag == "header":
                header = {child.tag: child.text or "" for child in node}
            elif node.tag == "init":
                init = [line.split("#", 1)[0].strip().split() for line in (node.text or "").splitlines()
                        if line.split("#", 1)[0].strip()]
            elif node.tag == "event":
                if any(child.tag in ("rwgt", "weights") for child in node):
                    raise ValueError("reweighted LHE is outside the uniform LO contract")
                lines = [line.split("#", 1)[0].strip().split() for line in (node.text or "").splitlines()
                         if line.split("#", 1)[0].strip()]
                if not lines or len(lines[0]) != 6:
                    raise ValueError("invalid LHE event header")
                count = int(lines[0][0])
                if count < 2 or len(lines) != count + 1:
                    raise ValueError("LHE particle census mismatch")
                for token in lines[0]:
                    number(token)
                weights.append(number(lines[0][2]))
                momenta, final_ids, final_particles = [], [], []
                incoming = []
                for row in lines[1:]:
                    if len(row) != 13:
                        raise ValueError("invalid LHE particle row")
                    values = [number(token) for token in row]
                    pdg, status = int(row[0]), int(row[1])
                    p = values[6:10]
                    if p[3] < 0:
                        raise ValueError("negative particle energy")
                    if status == -1:
                        incoming.append(p)
                    if status != 1:
                        continue
                    mass_squared = p[3] ** 2 - sum(v * v for v in p[:3])
                    if abs(mass_squared - values[10] ** 2) > 1e-5 * max(1, p[3] ** 2):
                        raise ValueError("final-state momentum is inconsistent with its recorded mass")
                    final_ids.append(pdg)
                    momenta.append(p)
                    final_particles.append((pdg, p[0], p[1], p[2], p[3]))
                    pt = math.hypot(p[0], p[1])
                    if pt + 1e-7 < observable.get("min_pt_gev", 0):
                        raise ValueError("event fails declared final-state pT control")
                    if "max_abs_eta" in observable and (pt == 0 or abs(math.asinh(p[2] / pt)) > observable["max_abs_eta"] + 1e-7):
                        raise ValueError("event fails declared final-state eta control")
                if (final_expected is not None and Counter(final_ids) != final_expected) or len(incoming) != 2:
                    raise ValueError("event final state or incoming-particle census differs from plan")
                total = [sum(v) for v in zip(*momenta)]
                initial = [sum(v) for v in zip(*incoming)]
                if any(abs(a - b) > 1e-5 * max(1, initial[3]) for a, b in zip(total, initial)):
                    raise ValueError("event fails four-momentum conservation")
                m2 = total[3] ** 2 - sum(v * v for v in total[:3])
                if m2 < -1e-6 * max(1, total[3] ** 2):
                    raise ValueError("spacelike final-state system")
                mass = math.sqrt(max(0, m2))
                if mass + 1e-7 < observable.get("min_mass_gev", 0):
                    raise ValueError("event fails declared invariant-mass control")
                if typed:
                    for key, filled in fso.evaluate(final_particles, generation["observables"]).items():
                        observed[key].extend(filled)
                elif "observable" in generation:
                    masses.append(mass)
                node.clear()
        if parser.root.tag != "LesHouchesEvents":
            raise ValueError("invalid LHE root element")
    if not header or not init or len(init[0]) != 10:
        raise ValueError("missing LHE banner or invalid init")
    fields = init[0]
    nproc = int(fields[9])
    if nproc < 1 or len(init) != nproc + 1 or any(len(row) != 4 for row in init[1:]):
        raise ValueError("invalid LHE process census")
    processes = [[number(v) for v in row] for row in init[1:]]
    if any(row[0] <= 0 or row[1] < 0 for row in processes):
        raise ValueError("invalid cross section or integration uncertainty")
    if not weights or min(weights) <= 0 or not math.isclose(min(weights), max(weights), rel_tol=1e-10):
        raise ValueError("nonpositive or variable nominal weights are not supported")
    if int(fields[8]) not in (-4, -3, 3, 4):
        raise ValueError("unsupported LHE weight convention")
    settings = run_card(header.get("MGRunCard", ""))
    expected = {**generation["run_settings"], "nevents": generation["events"],
                "iseed": seed, "use_syst": False, "systematics_program": "none", "ickkw": 0}
    for key, value in expected.items():
        if key not in settings or settings[key] != value:
            raise ValueError(f"effective run setting differs from plan: {key} ({settings.get(key)!r} != {value!r})")
    if len(weights) != generation["events"]:
        raise ValueError("completed event count differs from approved budget")
    from ravel.physics.beam_content import readback_errors
    beam_errors = readback_errors(generation["beam_pdg"], settings, fields)
    if beam_errors:
        raise ValueError("LHE beam identity differs from plan: " + "; ".join(beam_errors))
    if [number(v) for v in fields[2:4]] != [settings["ebeam1"], settings["ebeam2"]]:
        raise ValueError("LHE beam energies differ from plan")
    lhaid = generation["run_settings"]["lhaid"]
    if [int(v) for v in fields[6:8]] != [lhaid, lhaid]:
        raise ValueError("LHE PDF identity differs from plan")
    process = []
    for line in header.get("MG5ProcCard", "").splitlines():
        line = " ".join(line.split("#", 1)[0].split())
        if re.match(r"^(?:import model|define |generate |add process |set )", line) and not re.match(
                r"^set (?:automatic_html_opening|nb_core|run_mode) ", line):
            process.append(line)
    if ([line for line in process if line.startswith(("generate ", "add process "))] != [f"generate {generation['process']}"]
            or [line for line in process if line.startswith("import model ")] != [f"import model {generation['model']}"]):
        raise ValueError("effective process/model differs from plan")
    for name, value in generation["definitions"].items():
        aliases = [line for line in process if line.startswith(f"define {name} = ")]
        if not aliases or aliases[-1] != f"define {name} = {value}":
            raise ValueError(f"effective alias differs from plan: {name}")
    recipe = {"kind": "parton_lo", "process_card": process,
              "parameters": parameter_recipe(header.get("slha", "")),
              "run_settings": {k: v for k, v in settings.items() if k not in ("nevents", "iseed", "run_tag")},
              "beam_pdg": generation["beam_pdg"], "pdf_ids": [lhaid, lhaid],
              "weight_convention": int(fields[8]), "shower": "OFF", "detector": "OFF"}
    if typed:
        recipe["observables"] = generation["observables"]
        recipe["final_state_pdg"] = census
    elif "observable" in generation:
        recipe["observable"] = observable
    else:
        recipe["cross_section_only"] = True
    result = {"passed": True, "scope": "positive uniform LO parton events; no detector or precision-theory certification",
              "events": len(weights), "cross_section_pb": sum(row[0] for row in processes),
              "integration_error_pb": math.sqrt(sum(row[1] ** 2 for row in processes)),
              "sampling": {"events": len(weights), "seed": seed},
              "recipe": recipe, "header": header}
    if typed:
        result["observables"] = observed
    elif "observable" in generation:
        result["masses_gev"] = masses
    return result


def prepare_workspace(spec, base):
    try:
        import pyhf
    except ImportError as exc:
        raise ValueError("Likelihood workflows require pip install 'ravel-hep[replay]'.") from exc
    s = spec["likelihood"]
    if "counting" in s:
        c = s["counting"]
        model = pyhf.simplemodels.uncorrelated_background(
            signal=[c["signal"]], bkg=[c["background"]], bkg_uncertainty=[c["background_uncertainty"]])
        workspace = {"version": "1.0.0", "channels": model.spec["channels"],
                     "observations": [{"name": "singlechannel", "data": [c["observed"]]}],
                     "measurements": [{"name": "counting", "config": {"poi": "mu", "parameters": [
                         {"name": "mu", "bounds": [[0, s["poi_cap"]]], "inits": [min(1, s["poi_cap"] / 2)]}]}}]}
    else:
        from ravel.workflow.scoped_spec import input_file
        workspace = read_json(input_file(s["workspace"], base))
    ws = pyhf.Workspace(workspace)
    if len(ws.measurement_names) > 1 and "measurement" not in s:
        raise ValueError("multiple measurements require explicit measurement selection")
    model = ws.model(measurement_name=s.get("measurement"))
    if model.config.poi_index is None or model.config.suggested_fixed()[model.config.poi_index]:
        raise ValueError("likelihood requires a free scalar POI")
    poi_modifiers = [m for channel in workspace["channels"] for sample in channel["samples"]
                     for m in sample["modifiers"] if m["name"] == model.config.poi_name]
    if not poi_modifiers or any(m["type"] != "normfactor" for m in poi_modifiers):
        raise ValueError("the scoped signal-strength POI must be a normfactor")
    bounds = model.config.suggested_bounds()[model.config.poi_index]
    if bounds[0] != 0 or bounds[1] < s["poi_cap"]:
        raise ValueError("supplied POI bounds must start at zero and contain poi_cap; no silent bound edits")
    data = ws.data(model)
    if any(not math.isfinite(float(v)) for v in data) or any(v < 0 for v in data[:model.config.nmaindata]):
        raise ValueError("invalid likelihood data")
    # A POI with no observable effect has no finite exclusion crossing.
    p0 = model.config.suggested_init()
    p1 = list(p0)
    p0[model.config.poi_index], p1[model.config.poi_index] = 0, min(1, s["poi_cap"])
    if all(float(a) == float(b) for a, b in zip(model.expected_actualdata(p0), model.expected_actualdata(p1))):
        raise ValueError("POI does not change the expected event counts")
    return workspace


LAUNCH_SWITCHES = ["shower=OFF", "detector=OFF", "analysis=OFF", "madspin=OFF", "reweight=OFF", "done"]


def mg_commands(rd, g, proc):
    """The complete MadGraph command file: one output, one launch per point."""
    commands = ["set automatic_html_opening False", "set nb_core 1", "set run_mode 0"]
    if "lhapdf_config" in g["runtime"]:
        commands.append(f"set lhapdf {g['runtime']['lhapdf_config']}")
    commands.append(f"import model {g['model']}")
    commands += [f"define {name} = {value}" for name, value in g["definitions"].items()]
    commands += [f"generate {g['process']}", f"output {proc}"]
    for index, point in enumerate(points(g)):
        name = f" --name=point_{point['id']}" if point else ""
        commands += [f"launch {proc}{name}", *LAUNCH_SWITCHES]
        if "parameter_card" in g:
            commands.append(str(rd / g["parameter_card"]))
        for o in (point or {}).get("overrides", []):
            commands.append(f"set {o['block'].lower()} {' '.join(str(c) for c in o['code'])} {o['value']}")
        settings = {**g["run_settings"], "nevents": g["events"], "iseed": g["seed"] + index,
                    "use_syst": False, "systematics_program": "none", "ickkw": 0}
        commands += [f"set {key} {value}" for key, value in settings.items()]
        commands.append("done")
    return commands


def points(g):
    return g.get("parameter_points") or [None]


def overrides_reached(header, overrides):
    """Every declared override appears in the executed parameter card."""
    from ravel.workflow.spec_reconciliation import parse_slha
    card = parse_slha(header.get("slha", ""))
    for o in overrides:
        block, code = o["block"].upper(), tuple(o["code"])
        if block == "DECAY":
            value = card["decays"].get(code[0], {}).get("width")
            ok = value is not None and (o["value"] == "Auto" and (value == "auto" or value >= 0)
                                        or o["value"] != "Auto" and value != "auto" and math.isclose(value, o["value"], rel_tol=1e-9, abs_tol=1e-15))
        else:
            value = card["blocks"].get(block, {}).get(code)
            ok = value not in (None, "auto") and math.isclose(value, o["value"], rel_tol=1e-9, abs_tol=1e-15)
        if not ok:
            raise ValueError(f"override {block} {list(code)} = {o['value']} did not reach the executed card ({value!r})")


def point_intent(g, point):
    from ravel.workflow.spec_reconciliation import intent_for
    return intent_for(g, (point or {}).get("overrides", []))


def generate(rd, spec, out=None):
    from ravel.physics import generation_receipt as receipts
    from ravel.workflow.spec_reconciliation import reconcile, simulation_from_cards
    g = spec["generation"]
    out = rd / "outputs" if out is None else out
    work = rd / "work"
    work.mkdir(exist_ok=False)
    runtime = work / "mg5"
    shutil.copytree(rd / "inputs/madgraph", runtime)
    proc = work / "process"
    # MG's command parser does not support arbitrary whitespace/quotes in paths.
    if any(re.search(r"[\s'\";]", str(p)) for p in (runtime, proc)):
        raise ValueError("native MadGraph adapter requires a run path without whitespace or quotes")
    card = out / "commands.mg5"
    card.write_text("\n".join(mg_commands(rd, g, proc)) + "\n")
    env = dict(os.environ, **g["runtime"].get("environment", {}))
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env["PATH"] = str(Path(g["runtime"]["compiler"]).parent) + os.pathsep + env.get("PATH", "")
    with (out / "madgraph.log").open("w") as log:
        result = subprocess.run([g["runtime"]["python"], "-B", str(runtime / "bin/mg5_aMC"), str(card)],
                                cwd=runtime, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError(f"MadGraph failed ({result.returncode}); inspect outputs/madgraph.log")
    log = (out / "madgraph.log").read_text(errors="replace")
    batch = "parameter_points" in g
    if len(re.findall(r"Cross-section\s*:", log)) < len(points(g)):
        raise ValueError("MadGraph did not report a terminal cross section for every launch")
    plan = read_json(rd / "inputs/scoped-plan.json")
    rules = read_json(rd / "inputs/lhe-transform-rules.json") if "lhe_transform" in g else None
    version = (runtime / "VERSION").read_text().strip()
    from ravel.physics.generator_versions import runtime_version
    try:
        release = runtime_version(runtime)
    except ValueError:
        release = version
    point_rows, results, transforms, reconciliations = [], [], {}, {}
    for index, point in enumerate(points(g)):
        pattern = f"point_{point['id']}/unweighted_events.lhe.gz" if point else "run_*/unweighted_events.lhe.gz"
        files = list((proc / "Events").glob(pattern))
        if len(files) != 1:
            raise ValueError("expected exactly one completed LHE sample" + (f" for point {point['id']}" if point else ""))
        target = out / "points" / point["id"] if point else out
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(files[0], target / "events.lhe.gz")
        audit = audit_lhe(target / "events.lhe.gz", g, seed=g["seed"] + index)
        header = audit.pop("header")
        if "parameter_card" in g and not point and parameter_recipe((rd / g["parameter_card"]).read_text()) != parameter_recipe(header["slha"]):
            raise ValueError("executed parameter card differs from supplied scientific parameters")
        if point:
            overrides_reached(header, point["overrides"])
        from ravel.physics.beam_content import scheme_errors
        from ravel.workflow.spec_reconciliation import parse_slha
        scheme = scheme_errors(plan.get("beam_content"), parse_slha(header.get("slha", ""))["blocks"])
        if scheme:
            raise ValueError("; ".join(scheme))
        for tag, name in (("MGRunCard", "run_card.dat"), ("slha", "param_card.dat"), ("MG5ProcCard", "proc_card.dat")):
            (target / name).write_text(header[tag])
        sim = simulation_from_cards(header["MG5ProcCard"].splitlines(), run_card(header["MGRunCard"]), header["slha"])
        record = reconcile(point_intent(g, point), sim, stage="post-run")
        reconciliations[point["id"] if point else "single"] = record
        if not record["satisfied"]:
            atomic_json(out / "spec-reconciliation.json", reconciliations)
            raise ValueError("executed cards differ from the declared physics: " + "; ".join(record["violations"]))
        cards = [{"name": name, **receipts.file_record(target / name, out)}
                 for name in ("proc_card.dat", "run_card.dat", "param_card.dat")]
        lhe = None if g.get("cross_section_only") else receipts.file_record(target / "events.lhe.gz", out)
        if rules is not None:
            from ravel.physics import lhe_transform
            transformed = lhe_transform.transform(target / "events.lhe.gz", target / "events.transformed.lhe.gz", rules)
            transforms[point["id"] if point else "single"] = {
                "output": receipts.file_record(target / "events.transformed.lhe.gz", out),
                "receipt": receipts.file_record(target / "events.transformed.lhe.gz.transform.json", out),
                "census": transformed["census"], "events_changed": transformed["events_changed"]}
        point_rows.append(receipts.point(point["id"] if point else "single", (point or {}).get("overrides", []),
                                         g["seed"] + index, audit, cards, lhe))
        results.append((point, audit))
    atomic_json(out / "spec-reconciliation.json", reconciliations)
    model_identity = {"name": g["model"], "source_sha256": plan["model_source_sha256"],
                      "origin": plan.get("model_origin") or {"kind": "installed in the generator runtime"}}
    recipe_extra = {"model_source_sha256": plan["model_source_sha256"],
                    "generator_source_sha256": plan["generator_source_sha256"], "generator_version": version}
    if plan.get("generator_selection"):
        recipe_extra["generator_selection"] = plan["generator_selection"]
    if not batch:
        result = results[0][1]
        result["recipe"].update(recipe_extra)
        if "lhe_transform" in g:
            result["recipe"]["lhe_transform"] = {"rules_sha256": plan["lhe_transform"]["rules_sha256"],
                                                 "required_downstream_settings": plan["lhe_transform"]["required_downstream_settings"]}
        if "shower" in g:
            from ravel.physics.scoped_shower import run_shower
            source = out / ("events.transformed.lhe.gz" if "lhe_transform" in g else "events.lhe.gz")
            plain = work / "events.lhe"
            with gzip.open(source, "rb") as stream, plain.open("wb") as target:
                shutil.copyfileobj(stream, target)
            shower = run_shower(plain, g["shower"], g["observables"], out / "shower")
            plain.unlink()
            if shower["events_read"] != result["events"] or shower["events_showered"] != result["events"]:
                raise ValueError("shower did not complete every generated event: "
                                 f"{shower['events_showered']} of {result['events']}")
            result["particle_level"] = {"observables": shower["observables"], "events": shower["events_showered"]}
            result["recipe"]["shower"] = {"engine": "pythia8", "version": shower["version"],
                                          "seed": g["shower"]["seed"], "settings": g["shower"]["settings"]}
            result["scope"] = ("positive uniform LO events with a Pythia 8 shower at particle level; "
                               "no detector or precision-theory certification")
        if "observables" in g:
            result["histograms"] = histograms(result, g)
    else:
        result = {"passed": True, "scope": "positive uniform LO parton events per parameter point; no detector or "
                                           "precision-theory certification",
                  "events": sum(a["events"] for _, a in results),
                  "points": [{"id": p["id"], "overrides": p["overrides"], "events": a["events"], "seed": a["sampling"]["seed"],
                              "cross_section_pb": a["cross_section_pb"], "integration_error_pb": a["integration_error_pb"],
                              **({"histograms": histograms(a, g)["parton"]} if "observables" in g else {})}
                             for p, a in results],
                  "recipe": {"kind": "parton_lo_batch", "points": [{"id": p["id"], "recipe": a["recipe"]} for p, a in results],
                             **recipe_extra}}
    if g.get("cross_section_only"):
        result["scope"] = "LO cross sections with integration uncertainty; events were generated only to integrate"
    result["reconciliation"] = {k: {"satisfied": v["satisfied"], "unknowns": v["unknowns"], "flags": v["flags"]}
                                for k, v in reconciliations.items()}
    atomic_json(out / "result.json", result)
    shower_record = result["recipe"].get("shower") if not batch else None
    transform_record = None
    if rules is not None:
        transform_record = {"name": rules["name"], "rules_sha256": plan["lhe_transform"]["rules_sha256"],
                            "required_downstream_settings": plan["lhe_transform"]["required_downstream_settings"],
                            "deviations": plan["lhe_transform"]["deviations"], "points": transforms}
    receipt = receipts.build(
        generator={**plan.get("generator_selection", {"name": "MadGraph5_aMC@NLO"}), "version": release,
                   "source_sha256": plan["generator_source_sha256"]},
        process={"model": g["model"], "definitions": g["definitions"], "generate": g["process"],
                 "command_file": receipts.file_record(card, out)},
        model=model_identity, beams=plan.get("beam_content"), pdf=plan.get("pdf"),
        points=point_rows, weight_convention=results[0][1]["recipe"]["weight_convention"],
        cross_section_only=bool(g.get("cross_section_only")), transform=transform_record, shower=shower_record)
    atomic_json(out / "generation-receipt.json", receipt)
    if batch or g.get("cross_section_only"):
        plot_cross_sections(out, result if batch else {"points": [{"id": "single", "cross_section_pb": result["cross_section_pb"],
                                                                     "integration_error_pb": result["integration_error_pb"]}]})
    elif "observables" in g:
        plot_observables(out, result, g)
    else:
        plot_generation(out, result, g["observable"]["bin_edges_gev"])
    return result["recipe"]


def histograms(result, generation):
    """Parton- and (when showered) particle-level histograms of every observable."""
    levels = {"parton": result["observables"]}
    if "particle_level" in result:
        levels["particle"] = result["particle_level"]["observables"]
    return {level: {row["id"]: fso.histogram(values[row["id"]], row["bin_edges"], row.get("normalization", "events"),
                                              events=result["events"], cross_section_pb=result["cross_section_pb"])
                    for row in generation["observables"]}
            for level, values in levels.items()}


def likelihood(rd, spec, out=None):
    out = rd / "outputs" if out is None else out
    import pyhf
    from ravel.physics.pyhf_exclude import compute, robust_optimizer
    s = spec["likelihood"]
    workspace = read_json(rd / "inputs/workspace.json")
    ws = pyhf.Workspace(workspace)
    model = ws.model(measurement_name=s.get("measurement"))
    data = ws.data(model)
    pyhf.set_backend("numpy", robust_optimizer(tolerance=1e-9), precision="64b")
    diagnostics = {}
    try:
        result = compute(model, data, poi_cap=s["poi_cap"], diagnostic_record=diagnostics)
    finally:
        atomic_json(out / "fit-diagnostics.json", diagnostics)
    result["scope"] = "95% asymptotic CLs for the supplied model; no detector certification or coverage validation"
    result["normalization"] = s["normalization"]
    if "luminosity_fb" in s["normalization"]:
        lumi = s["normalization"]["luminosity_fb"]
        status = result["limit_status"]
        result["visible_cross_section_fb"] = {
            "observed": result["obs_limit"] / lumi if status["observed"] == "resolved" else None,
            "expected": [v / lumi if state == "resolved" else None
                         for v, state in zip(result["exp_limits"], status["expected"])],
            "limit_status": status}
    atomic_json(out / "result.json", result)
    status = result["limit_status"]
    if status["observed"] != "resolved" or any(v != "resolved" for v in status["expected"]):
        raise ValueError("not all six CLs crossings resolved; numerical bounds retained, delivery incomplete")
    plot_likelihood(out, result)
    return {"kind": "supplied_likelihood", "workspace": workspace, "measurement": s.get("measurement", ws.measurement_names[0]),
            "normalization": s["normalization"], "test_statistic": "qtilde", "calculation": "asymptotic_cls",
            "level": 0.05, "pyhf_version": pyhf.__version__, "poi_cap": s["poi_cap"],
            "optimizer": "ravel robust_optimizer", "coverage_validated": False}


def axes():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ravel.plotting import mplhep_style as house
    house.apply_style()
    fig, ax = plt.subplots(figsize=(7.6, 5.2), layout="constrained")
    return fig, ax, house


def save_plot(out, fig, ax, house, contract):
    house.tick_hygiene(ax)
    house.smart_legend(ax)
    house.enforce_lint(fig, where="scoped control")
    fig.savefig(out / "figure.pdf")
    fig.savefig(out / "figure.png", dpi=220)
    atomic_json(out / "figure.json", {**contract, "png_dpi": 220, "plot_lint": "PASS",
                                     "formats": ["PDF", "PNG"], "source": "result.json"})
    import matplotlib.pyplot as plt
    plt.close(fig)


def plot_generation(out, result, edges):
    import numpy as np
    fig, ax, house = axes()
    masses = result["masses_gev"]
    counts, _ = np.histogram(masses, bins=edges)
    centers = (np.array(edges[1:]) + np.array(edges[:-1])) / 2
    widths = np.diff(edges)
    ax.errorbar(centers, counts / widths, yerr=np.sqrt(counts) / widths, xerr=widths / 2,
                fmt="o", color="black", markersize=3,
                label="Generated events (MC counting error)")
    ax.set(xlabel="Final-state invariant mass [GeV]", ylabel="Generated events / GeV",
           title=f"Ravel LO parton control · {result['events']} events", xlim=(edges[0], edges[-1]),
           ylim=(0, max(counts / widths) * 1.35 + .1))
    save_plot(out, fig, ax, house, {"observable": "final-state invariant mass", "bin_edges_gev": edges,
        "counts": counts.tolist(), "normalization": "raw generated counts divided by bin width in GeV; x errors show bin extents",
        "underflow": sum(m < edges[0] for m in masses), "overflow": sum(m > edges[-1] for m in masses),
        "uncertainty": "sqrt(N) MC counting only; integration error separately in result.json"})


def plot_observables(out, result, generation):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from ravel.plotting import mplhep_style as house
    house.apply_style()
    rows = generation["observables"]
    fig, axes_list = plt.subplots(len(rows), 1, figsize=(7.6, 4.6 * len(rows)), layout="constrained", squeeze=False)
    styles = {"parton": ("o", "black", "Parton level"), "particle": ("s", house.OKABE_ITO["blue"], "Particle level (Pythia 8)")}
    for ax, row in zip(axes_list[:, 0], rows):
        edges = np.array(row["bin_edges"], dtype=float)
        centers, half = (edges[1:] + edges[:-1]) / 2, np.diff(edges) / 2
        top = 0.
        for level, hist in result["histograms"].items():
            h = hist[row["id"]]
            marker, color, label = styles[level]
            ax.errorbar(centers, h["values"], yerr=h["errors"], xerr=half, fmt=marker, color=color,
                        markersize=3, label=label + " (MC counting error)")
            top = max(top, max(v + e for v, e in zip(h["values"], h["errors"])))
        unit = fso.KINDS[row["kind"]]
        name = {"invariant_mass": "Invariant mass", "pt": "Transverse momentum", "missing_et": "Missing transverse momentum",
                "eta": "Pseudorapidity", "rapidity": "Rapidity", "phi": "Azimuth"}[row["kind"]]
        xlabel = f"{name} ({row['id'].replace('_', ' ')})" + (f" [{unit}]" if unit != "1" else "")
        ylabel = {"events": "Events / bin", "unit_area": "Normalized to unit area",
                  "cross_section": "dσ/dx [pb per unit x]"}[row.get("normalization", "events")]
        ax.set(xlabel=xlabel, ylabel=ylabel, xlim=(edges[0], edges[-1]), ylim=(0, top * 1.35 + 1e-12))
        house.tick_hygiene(ax)
        house.smart_legend(ax)
    axes_list[0, 0].set_title(f"Ravel generation · {result['events']} events")
    house.enforce_lint(fig, where="scoped observables")
    fig.savefig(out / "figure.pdf")
    fig.savefig(out / "figure.png", dpi=220)
    atomic_json(out / "figure.json", {"observables": [row["id"] for row in rows], "png_dpi": 220, "plot_lint": "PASS",
                                     "formats": ["PDF", "PNG"], "source": "result.json histograms",
                                     "levels": list(result["histograms"]),
                                     "uncertainty": "sqrt(N) MC counting only; integration error separately in result.json"})
    plt.close(fig)


def plot_cross_sections(out, result):
    """Cross section with its integration uncertainty for each parameter point."""
    import numpy as np
    fig, ax, house = axes()
    rows = result["points"]
    x = np.arange(len(rows))
    y = np.array([r["cross_section_pb"] for r in rows])
    e = np.array([r["integration_error_pb"] for r in rows])
    ax.errorbar(x, y, yerr=e, fmt="o", color="black", markersize=4, label="LO cross section (integration error)")
    ax.set_xticks(x, [r["id"] for r in rows], rotation=45 if len(rows) > 6 else 0)
    ax.set(xlabel="Parameter point", ylabel="Cross section [pb]", xlim=(-0.5, len(rows) - 0.5),
           ylim=(0, float(max(y + e)) * 1.35), title=f"Ravel LO cross sections · {len(rows)} point(s)")
    save_plot(out, fig, ax, house, {"observable": "LO cross section per parameter point",
        "points": [r["id"] for r in rows], "values_pb": y.tolist(), "errors_pb": e.tolist(),
        "uncertainty": "integration uncertainty only; no scale, PDF or higher-order uncertainty"})


def plot_likelihood(out, result):
    import numpy as np
    fig, ax, house = axes()
    x, y, e = np.array(result["scan_mu"]), np.array(result["scan_cls_obs"]), np.array(result["scan_cls_exp"])
    ax.plot(x, y, color="black", label="Observed")
    ax.plot(x, e[:, 2], "--", color=house.OKABE_ITO["blue"], label="Median expected")
    ax.axhline(.05, color=house.OKABE_ITO["vermillion"], linestyle=":", label="95% CLs threshold")
    events = result["normalization"]["kind"] == "signal_events"
    ax.set(xlabel="Signal events" if events else "Signal strength μ", ylabel="CLs",
           title="Ravel supplied-likelihood control", ylim=(0, 1.05), xlim=(min(x), max(x)))
    save_plot(out, fig, ax, house, {"observable": "asymptotic CLs", "normalization": result["normalization"],
        "root_source": "verified Brent crossings in result.json; curve samples are display only",
        "expected_convention": "conditional background-only Asimov; no toy coverage validation"})


def main():
    rd = Path(sys.argv[1]).resolve()
    spec = read_json(rd / "inputs/scoped.json")
    # This worker is internal. CLI approval and plan verification happen before
    # supervision; recheck here to close the launch/read gap.
    from ravel.workflow.scoped import verify_worker
    # A placed stage writes into its attempt's backend staging; the backend
    # fetch hashes and moves it to the run's outputs afterward.
    out = Path(verify_worker(rd).get("output_directory", rd / "outputs"))
    out.mkdir(exist_ok=False)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    try:
        recipe = generate(rd, spec, out) if spec["mode"] == "generate" else likelihood(rd, spec, out)
        atomic_json(out / "recipe.json", {"schema_version": 1, "recipe": recipe, "sha256": digest(recipe),
            "provenance": "extracted from completed LHE banner" if spec["mode"] == "generate" else "executed serialized workspace"})
        atomic_json(out / "verification.json", {"passed": True, "scope": spec["mode"],
            "expert_review": False, "approval_mode": spec["approval_mode"],
            "scientific_certification": False, "claim": "scoped workflow delivery and numerical/record integrity"})
        result = read_json(out / "result.json")
        batch = spec["mode"] == "generate" and "points" in result
        numbers = ({"points": [{k: p[k] for k in ("id", "events", "cross_section_pb", "integration_error_pb")}
                               for p in result["points"]]} if batch else
                   {key: result[key] for key in ("events", "cross_section_pb", "integration_error_pb")}
                   if spec["mode"] == "generate" else
                   {key: result[key] for key in ("obs_limit", "exp_limits", "limit_status", "normalization")})
        atomic_json(out / "checkin2.json", {"schema_version": 1, "kind": "checkin2", "sections": {
            "waypoint": {"scope": spec["mode"], "result": numbers, "figure": "outputs/figure.png"},
            "expectation": "Mechanical and scoped scientific checks passed. Review the actual figure and assumptions; no expert review or paper reproduction has been inferred.",
            "ask": {"options": ["GO", "ADJUST"], "scope": "A next experiment needs a new concrete plan and approval; this attempt is complete."}}})
        summary = ("\n".join(f"- point {p['id']}: {p['events']} events, LO cross section {p['cross_section_pb']:.6g} +/- "
                             f"{p['integration_error_pb']:.6g} pb" for p in result["points"])
                   + "\n\nIntegration uncertainty only." if batch else
                   f"{result['events']} completed events. LO cross section {result['cross_section_pb']:.6g} +/- "
                   f"{result['integration_error_pb']:.6g} pb (integration uncertainty only)."
                   if spec["mode"] == "generate" else
                   f"Observed 95% CLs limit {result['obs_limit']:.8g}; median expected {result['exp_limits'][2]:.8g} "
                   f"({result['normalization']['kind']}). All six crossings resolved.")
        (out / "RESULT.md").write_text(
            "# Scoped workflow result\n\n" + summary + "\n\n![Diagnostic figure](figure.png)\n\n" +
            "Source: " + spec["source"] + "\n\nAssumptions:\n\n" +
            "\n".join("- " + a for a in spec["assumptions"]) +
            "\n\nThe executed recipe is in `recipe.json`, numerical/event evidence in `result.json`, "
            "and the result check-in in `checkin2.json`. PDF and PNG figures accompany the values. "
            + ("The generation receipt for downstream stages is `generation-receipt.json`. " if spec["mode"] == "generate" else "") +
            "The receipt establishes scoped delivery and integrity, not expert review, detector fidelity, "
            "coverage or reproduction of a paper. A new experiment requires a new plan.\n")
    except Exception as exc:
        atomic_json(out / "failure.json", {"passed": False, "type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
