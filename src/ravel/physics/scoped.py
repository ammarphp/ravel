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


def audit_lhe(path, generation):
    """Stream the entire completed LHE, checking every event, not a preview.

    Positive uniform nominal LO weights only. Extra reweighting information is
    rejected until its normalization has a supported contract.
    """
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    header, init = None, None
    masses, weights, checks = [], [], {}
    final_expected = Counter(generation["observable"]["final_state_pdg"])
    observable = generation["observable"]
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
                momenta, final_ids = [], []
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
                    pt = math.hypot(p[0], p[1])
                    if pt + 1e-7 < observable.get("min_pt_gev", 0):
                        raise ValueError("event fails declared final-state pT control")
                    if "max_abs_eta" in observable and (pt == 0 or abs(math.asinh(p[2] / pt)) > observable["max_abs_eta"] + 1e-7):
                        raise ValueError("event fails declared final-state eta control")
                if Counter(final_ids) != final_expected or len(incoming) != 2:
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
                "iseed": generation["seed"], "use_syst": False, "systematics_program": "none", "ickkw": 0}
    for key, value in expected.items():
        if key not in settings or settings[key] != value:
            raise ValueError(f"effective run setting differs from plan: {key} ({settings.get(key)!r} != {value!r})")
    if len(weights) != generation["events"]:
        raise ValueError("completed event count differs from approved budget")
    if [int(v) for v in fields[:2]] != generation["beam_pdg"]:
        raise ValueError("LHE beam identity differs from plan")
    if [number(v) for v in fields[2:4]] != [settings["ebeam1"], settings["ebeam2"]]:
        raise ValueError("LHE beam energies differ from plan")
    if [int(v) for v in fields[6:8]] != [10042, 10042]:
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
              "beam_pdg": generation["beam_pdg"], "pdf_ids": [10042, 10042],
              "weight_convention": int(fields[8]), "shower": "OFF", "detector": "OFF",
              "observable": observable}
    return {"passed": True, "scope": "positive uniform LO parton events; no detector or precision-theory certification",
            "events": len(weights), "cross_section_pb": sum(row[0] for row in processes),
            "integration_error_pb": math.sqrt(sum(row[1] ** 2 for row in processes)),
            "masses_gev": masses, "sampling": {"events": len(weights), "seed": generation["seed"]},
            "recipe": recipe, "header": header}


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


def generate(rd, spec):
    g = spec["generation"]
    out = rd / "outputs"
    work = rd / "work"
    work.mkdir(exist_ok=False)
    runtime = work / "mg5"
    shutil.copytree(rd / "inputs/madgraph", runtime)
    proc = work / "process"
    # MG's command parser does not support arbitrary whitespace/quotes in paths.
    if any(re.search(r"[\s'\";]", str(p)) for p in (runtime, proc)):
        raise ValueError("native MadGraph adapter requires a run path without whitespace or quotes")
    commands = ["set automatic_html_opening False", "set nb_core 1", "set run_mode 0",
                f"import model {g['model']}"]
    commands += [f"define {name} = {value}" for name, value in g["definitions"].items()]
    commands += [f"generate {g['process']}", f"output {proc}", f"launch {proc}",
                 "shower=OFF", "detector=OFF", "analysis=OFF", "madspin=OFF", "reweight=OFF", "done"]
    if "parameter_card" in g:
        commands.append(str(rd / g["parameter_card"]))
    settings = {**g["run_settings"], "nevents": g["events"], "iseed": g["seed"],
                "use_syst": False, "systematics_program": "none", "ickkw": 0}
    commands += [f"set {key} {value}" for key, value in settings.items()]
    commands += ["done"]
    card = out / "commands.mg5"
    card.write_text("\n".join(commands) + "\n")
    env = dict(os.environ, **g["runtime"].get("environment", {}))
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env["PATH"] = str(Path(g["runtime"]["compiler"]).parent) + os.pathsep + env.get("PATH", "")
    with (out / "madgraph.log").open("w") as log:
        result = subprocess.run([g["runtime"]["python"], "-B", str(runtime / "bin/mg5_aMC"), str(card)],
                                cwd=runtime, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError(f"MadGraph failed ({result.returncode}); inspect outputs/madgraph.log")
    log = (out / "madgraph.log").read_text(errors="replace")
    if not re.search(r"Cross-section\s*:", log):
        raise ValueError("MadGraph did not report a terminal cross section")
    files = list((proc / "Events").glob("run_*/unweighted_events.lhe.gz"))
    if len(files) != 1:
        raise ValueError("expected exactly one completed LHE sample")
    shutil.copyfile(files[0], out / "events.lhe.gz")
    result = audit_lhe(out / "events.lhe.gz", g)
    header = result.pop("header")
    if "parameter_card" in g and parameter_recipe((rd / g["parameter_card"]).read_text()) != parameter_recipe(header["slha"]):
        raise ValueError("executed parameter card differs from supplied scientific parameters")
    for tag, name in (("MGRunCard", "run_card.dat"), ("slha", "param_card.dat"), ("MG5ProcCard", "proc_card.dat")):
        (out / name).write_text(header[tag])
    result["recipe"]["model_source_sha256"] = read_json(rd / "inputs/scoped-plan.json")["model_source_sha256"]
    result["recipe"]["generator_source_sha256"] = read_json(rd / "inputs/scoped-plan.json")["generator_source_sha256"]
    result["recipe"]["generator_version"] = (runtime / "VERSION").read_text().strip()
    atomic_json(out / "result.json", result)
    plot_generation(out, result, g["observable"]["bin_edges_gev"])
    return result["recipe"]


def likelihood(rd, spec):
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
        atomic_json(rd / "outputs/fit-diagnostics.json", diagnostics)
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
    atomic_json(rd / "outputs/result.json", result)
    status = result["limit_status"]
    if status["observed"] != "resolved" or any(v != "resolved" for v in status["expected"]):
        raise ValueError("not all six CLs crossings resolved; numerical bounds retained, delivery incomplete")
    plot_likelihood(rd / "outputs", result)
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
    verify_worker(rd)
    (rd / "outputs").mkdir(exist_ok=False)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    try:
        recipe = generate(rd, spec) if spec["mode"] == "generate" else likelihood(rd, spec)
        atomic_json(rd / "outputs/recipe.json", {"schema_version": 1, "recipe": recipe, "sha256": digest(recipe),
            "provenance": "extracted from completed LHE banner" if spec["mode"] == "generate" else "executed serialized workspace"})
        atomic_json(rd / "outputs/verification.json", {"passed": True, "scope": spec["mode"],
            "expert_review": False, "approval_mode": spec["approval_mode"],
            "scientific_certification": False, "claim": "scoped workflow delivery and numerical/record integrity"})
        result = read_json(rd / "outputs/result.json")
        numbers = ({key: result[key] for key in ("events", "cross_section_pb", "integration_error_pb")}
                   if spec["mode"] == "generate" else
                   {key: result[key] for key in ("obs_limit", "exp_limits", "limit_status", "normalization")})
        atomic_json(rd / "outputs/checkin2.json", {"schema_version": 1, "kind": "checkin2", "sections": {
            "waypoint": {"scope": spec["mode"], "result": numbers, "figure": "outputs/figure.png"},
            "expectation": "Mechanical and scoped scientific checks passed. Review the actual figure and assumptions; no expert review or paper reproduction has been inferred.",
            "ask": {"options": ["GO", "ADJUST"], "scope": "A next experiment needs a new concrete plan and approval; this attempt is complete."}}})
        summary = (f"{result['events']} completed events. LO cross section {result['cross_section_pb']:.6g} +/- "
                   f"{result['integration_error_pb']:.6g} pb (integration uncertainty only)."
                   if spec["mode"] == "generate" else
                   f"Observed 95% CLs limit {result['obs_limit']:.8g}; median expected {result['exp_limits'][2]:.8g} "
                   f"({result['normalization']['kind']}). All six crossings resolved.")
        (rd / "outputs/RESULT.md").write_text(
            "# Scoped workflow result\n\n" + summary + "\n\n![Diagnostic figure](figure.png)\n\n" +
            "Source: " + spec["source"] + "\n\nAssumptions:\n\n" +
            "\n".join("- " + a for a in spec["assumptions"]) +
            "\n\nThe executed recipe is in `recipe.json`, numerical/event evidence in `result.json`, "
            "and the result check-in in `checkin2.json`. PDF and PNG figures accompany the values. "
            "The receipt establishes scoped delivery and integrity, not expert review, detector fidelity, "
            "coverage or reproduction of a paper. A new experiment requires a new plan.\n")
    except Exception as exc:
        atomic_json(rd / "outputs/failure.json", {"passed": False, "type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
