"""Plan and execute registered native workflows without implicit physics inputs.

New configurations declare [ravel.native] model, preparation, detector and
statistics, with [ravel.native.inputs] paths relative to the run directory.
The explicit-cards preparation requires process_card, param_card, run_card,
shower_card and delphes_card. It supports bounded unmerged MSSM LO generation;
it does not derive arbitrary model cards from the slepton template.

Plans use stages {stage, command, inputs, outputs, depends_on}; execution always
uses the durable stage supervisor. Producing a plan does not authorize compute.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from ravel.paths import module_command, native_binary, native_build_root
from .native_capabilities import MODEL_PDGS, resolve_capability
from .native_normalization import fingerprint, positive


def read_config(path):
    try:
        import tomllib
    except ImportError as exc:
        raise RuntimeError("Native TOML execution requires Python 3.11 or 3.12") from exc
    with Path(path).open("rb") as stream:
        return tomllib.load(stream)


def integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def card_assignments(path, style="run"):
    result = {}
    for raw in Path(path).read_text().splitlines():
        line = re.split(r"[#!]", raw, maxsplit=1)[0].strip()
        if not line or "=" not in line:
            continue
        left, right = [x.strip() for x in line.split("=", 1)]
        key, value = (right, left) if style == "run" else (left, right)
        if key in result:
            raise ValueError(f"duplicate card assignment: {key}")
        result[key] = value.strip("'\"")
    return result


def validate_process_card(path, model, *, with_jet_count=False):
    """Bound command surface and check declared production family, before MG."""
    commands = [x.split("#", 1)[0].strip() for x in Path(path).read_text().splitlines()]
    commands = [x for x in commands if x]
    if any("{{" in x or ";" in x or "!" in x for x in commands):
        raise ValueError("process card contains unresolved or non-process commands")
    if sum(x.startswith("import model ") for x in commands) != 1:
        raise ValueError("process card must import exactly one declared model")
    if "import model MSSM_SLHA2" not in commands:
        raise ValueError("this native generation adapter only supports MSSM_SLHA2")
    if any(not x.startswith(("import model ", "define ", "generate ", "add process ", "set ")) for x in commands):
        raise ValueError("process card may only define the model and generation process")
    productions = [x for x in commands if x.startswith(("generate ", "add process "))]
    if not productions or sum(x.startswith("generate ") for x in productions) != 1:
        raise ValueError("process card needs one generate command")
    # Resolve declared aliases; names alone must not hide a wrong-family process.
    aliases = {}
    generation_started = False
    for line in commands:
        if line.startswith(("generate ","add process ")):
            generation_started = True
        if line.startswith("define "):
            if generation_started:
                raise ValueError("process aliases must be defined before generation")
            match = re.fullmatch(r"define\s+(\S+)\s*=\s*(.+)", line)
            if not match:
                raise ValueError("invalid process alias")
            aliases[match[1]] = match[2].split()
    def expand(token, seen=()):
        if token not in aliases:
            return [token]
        if token in seen:
            raise ValueError("cyclic process alias")
        return [x for part in aliases[token] for x in expand(part, (*seen, token))]
    expected = {
        "slepton-bino": {"el-", "el+", "er-", "er+", "mul-", "mul+", "mur-", "mur+", "ta1-", "ta1+", "ta2-", "ta2+"},
        "c1n2-wz": {"x1+", "x1-", "n2"},
        "squark-neutralino": {f"{q}{s}{bar}" for q in ("u", "d", "c", "s") for s in ("l", "r") for bar in ("", "~")},
        "gluino-neutralino": {"go"},
    }[model]
    partons = {"g","u","u~","d","d~","c","c~","s","s~","b","b~"}
    if "p" in aliases and (not expand("p") or not set(expand("p")) <= partons):
        raise ValueError("proton alias contains unsupported incoming particles")
    produced = set()
    jet_multiplicities = set()
    for line in productions:
        # Decays are supplied in the SLHA. This bounded adapter does not support
        # MG decay-chain syntax or perturbative/NLO brackets hidden in the card.
        if any(x in line for x in (",", "[", "]", "(", ")")):
            raise ValueError("explicit-cards adapter supports unmerged LO production with SLHA decays")
        body = line.split(">", 1)
        if len(body) != 2 or body[0].split()[-2:] != ["p", "p"]:
            raise ValueError("registered native production must be p p scattering")
        final = re.split(r"\s[/@$]|\s[A-Za-z]+\s*=", body[1], maxsplit=1)[0].split()
        families = [expand(token) for token in final]
        bsm_slots = [xs for xs in families if any(x not in partons | {"j"} for x in xs)]
        bsm = [x for xs in bsm_slots for x in xs]
        if len(bsm_slots) != 2:
            raise ValueError("registered models require two produced BSM particles")
        jet_multiplicities.add(len(families)-len(bsm_slots))
        if not bsm or any(x not in expected for x in bsm):
            raise ValueError("process final states disagree with the declared model family")
        if model == "c1n2-wz" and not any(set(bsm_slots[i])=={"n2"} and set(bsm_slots[1-i])<={"x1+","x1-"} for i in (0,1)):
            raise ValueError("c1n2-wz requires chargino-neutralino associated production")
        produced.update(bsm)
    if len(jet_multiplicities)!=1:
        raise ValueError("mixed jet multiplicities overlap and require a matching/merging adapter")
    pdgs = {"el":1000011,"er":2000011,"mul":1000013,"mur":2000013,
            "ta1":1000015,"ta2":2000015,"x1":1000024,"n2":1000023,"go":1000021}
    pdgs.update({q+s:(1000000 if s == "l" else 2000000)+index
                 for q,index in (("d",1),("u",2),("s",3),("c",4)) for s in ("l","r")})
    produced_pdgs = {pdgs[token.rstrip("+-~")] for token in produced}
    return (produced_pdgs, next(iter(jet_multiplicities))) if with_jet_count else produced_pdgs


def validate_param_card(path, model, m_parent=None, m_lsp=None, *, produced=None):
    from ravel.validation.lhe_check import parse_param_card
    masses, lint = parse_param_card(str(path))
    failures = [message for level, message in lint if level == "FAIL"]
    if failures:
        raise ValueError("; ".join(failures))
    parents, child = MODEL_PDGS[model]
    present = [p for p in parents if p in masses]
    if not present or child not in masses:
        raise ValueError("parameter card lacks the declared model masses")
    if produced is not None and not set(produced) <= set(present):
        raise ValueError("parameter card lacks masses for actual produced parents")
    if model == "c1n2-wz" and len(present) != 2:
        raise ValueError("c1n2-wz needs both chargino and neutralino masses")
    decay, widths, current = {}, {}, None
    for raw in Path(path).read_text().splitlines():
        line = raw.split("#",1)[0].strip().split()
        if not line:
            continue
        if line[0].lower() == "block": current = None
        elif line[0].lower() == "decay":
            current = abs(int(line[1])); widths[current] = float(line[2]); decay[current] = []
        elif current is not None:
            if len(line) < 2 or int(line[1]) != len(line)-2:
                raise ValueError("malformed SLHA decay row")
            decay[current].append((float(line[0]),[int(x) for x in line[2:]]))
    if child in widths and widths[child] != 0:
        raise ValueError("declared neutralino LSP must be stable")
    def declared_decay(pdg,daughters):
        if daughters.count(child)!=1:
            return False
        other=sorted(d for d in daughters if d!=child)
        if model=="c1n2-wz":
            if pdg==1000023:
                return other==[23] or len(other)==2 and other[0]==-other[1] and abs(other[0]) in (1,2,3,4,5,6,11,12,13,14,15,16)
            return other==[24] or tuple(other) in {tuple(sorted(pair)) for pair in
                [(-11,12),(-13,14),(-15,16),*((u,-d) for u in (2,4,6) for d in (1,3,5))]}
        if model=="slepton-bino":
            return other==[{1000011:11,2000011:11,1000013:13,2000013:13,1000015:15,2000015:15}[pdg]]
        if model=="squark-neutralino":
            return other==[pdg%1000000]
        return len(other)==2 and other[0]==-other[1] and abs(other[0]) in (1,2,3,4,5,6)
    for pdg in present:
        positive(widths.get(pdg), "produced-parent width")
        rows = decay.get(pdg, [])
        # SLHA templates commonly retain disabled BR=0 modes with other
        # daughters. Validate topology only for positive-probability decays.
        if not rows or any(not math.isfinite(br) or br < 0 or br > 1 for br,daughters in rows):
            raise ValueError("declared model requires explicit parent-to-LSP branching rows")
        if any(br>0 and not declared_decay(pdg,daughters) for br,daughters in rows):
            raise ValueError("branching daughters disagree with declared model topology or charge")
        if not math.isclose(math.fsum(br for br,_ in rows),1.,abs_tol=1e-6):
            raise ValueError("parent branching fractions must sum to one")
    lsp = float(masses[child])
    if not math.isfinite(lsp) or lsp < 0:
        raise ValueError("LSP mass must be finite and nonnegative")
    if m_lsp is not None and not math.isclose(lsp, float(m_lsp), rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError("parameter-card LSP differs from scan point")
    for pdg in present:
        parent = positive(masses[pdg], "parent mass")
        if parent <= lsp:
            raise ValueError("parent must be heavier than the LSP")
        if m_parent is not None and not math.isclose(parent, float(m_parent), rel_tol=1e-10):
            raise ValueError("explicit parameter card differs from requested scan mass; render a new card")
    return {str(p): masses[p] for p in (*present, child)}


def build_execution_plan(rundir, config, *, model=None, analysis_id=None, m_parent=None, m_lsp=None, pdf=None, campaign_points=1):
    rundir = Path(rundir).resolve()
    config = Path(config)
    config = config.resolve() if config.is_absolute() else (rundir/config).resolve()
    cfg = read_config(config)
    native = cfg.get("ravel", {}).get("native", {})
    declared_model = native.get("model", model)
    if model is not None and declared_model != model:
        raise ValueError("scan model and native model declaration disagree")
    routine = cfg.get("simpleanalysis", {}).get("name")
    # Compatibility is tied to the manifest's explicit model plus both named
    # mapyde adapters; a missing arbitrary model is never inferred from masses.
    legacy = (not native and model == "slepton-bino" and routine == "EwkCompressed2018"
              and cfg.get("madgraph", {}).get("params") == "SleptonBino"
              and cfg.get("madgraph", {}).get("proc", {}).get("name") == "isrslep")
    preparation = native.get("preparation", "slepton-bino" if legacy else None)
    detector = native.get("detector", "simpleanalysis-delphes" if legacy else None)
    statistics = native.get("statistics", "compressed-likelihood" if legacy else None)
    capability = resolve_capability(routine, declared_model, preparation, detector, statistics, analysis_id)
    if cfg.get("analysis", {}).get("script") != "Delphes2SA.py":
        raise ValueError("registered detector adapter requires Delphes2SA.py")
    analysis = cfg["analysis"]
    lumi = positive(analysis.get("lumi"), "luminosity (pb^-1)")
    kfactor = positive(analysis.get("kfactor"), "explicit kfactor")
    event_storage = native.get("event_storage", "plain")
    if event_storage not in ("plain", "gzip"):
        raise ValueError("native event_storage must be plain or gzip")
    lhe_provenance = native.get("lhe_provenance")
    if "lhe_provenance" in native and lhe_provenance != "original-v1":
        raise ValueError("native lhe_provenance must be the explicit original-v1 policy")
    if lhe_provenance is not None and preparation != "explicit-cards":
        raise ValueError("original-v1 requires explicit unmerged nominal source cards")
    compressed_signal_model = native.get("compressed_signal_model", "full")
    if compressed_signal_model not in ("full", "sr-only-diagnostic"):
        raise ValueError("compressed_signal_model must be full or sr-only-diagnostic")
    mc_stat = native.get("mc_stat", "none")
    if mc_stat not in ("none", "shapesys", "staterror"):
        raise ValueError("native mc_stat must be none, shapesys or staterror")
    fit_backend = native.get("pyhf_backend", "numpy")
    if fit_backend not in ("numpy", "jax"):
        raise ValueError("native pyhf_backend must be numpy or jax")
    statistics_python = native.get("statistics_python")
    if statistics_python is not None:
        if not isinstance(statistics_python, str) or not Path(statistics_python).is_absolute():
            raise ValueError("native statistics_python must be an absolute interpreter path")
        if not Path(statistics_python).is_file() or not os.access(statistics_python, os.X_OK):
            raise ValueError("native statistics_python is not an executable interpreter")
    if analysis.get("XSoverride", -1) != -1:
        raise ValueError("XSoverride is unsupported: normalize to generated LHE rate and one explicit correction")
    run = cfg.get("madgraph", {}).get("run", {})
    nevents, seed = integer(run.get("nevents"), "nevents"), integer(run.get("seed"), "seed", 0)
    campaign_points = integer(campaign_points,"campaign point count")
    ecms = positive(run.get("ecms"), "collision energy (GeV)")
    inputs, rendered = {}, {}
    source_paths = [config, Path(__file__)]
    if statistics_python is not None:
        source_paths.append(Path(statistics_python))
    source_paths.extend((Path(__file__).parents[1]/"paths.py",Path(__file__).parents[1]/"_bootstrap.py",
                         Path(__file__).parents[1]/"validation/lhe_check.py"))
    source_paths.extend(Path(__file__).with_name(name) for name in
                        ("native_capabilities.py","native_normalization.py","native_event_io.py","prepare_native_slepton.py",
                         "delphes2sa_native.py","native_simpleanalysis.py","sa_native_core.py",
                         "sa2json_native.py","pyhf_exclude.py"))
    if routine != "EwkCompressed2018":
        from .sa_routines import REGISTRY
        source_paths.append(Path(__file__).parent/"sa_routines"/(REGISTRY[routine].rsplit(".",1)[1]+".py"))
    else:
        source_paths.append(Path(__file__).with_name("compressed_validation.py"))
    declared_inputs = native.get("inputs", {})
    linker_policy = native.get("lhapdf_linker")
    if (linker_policy is None) != ("lhapdf_link_decision" not in declared_inputs):
        raise ValueError("LHAPDF linker policy and decision must be supplied together")
    if linker_policy is not None:
        from .native_lhapdf import GENERATION_POLICY
        if linker_policy != GENERATION_POLICY or preparation != "explicit-cards":
            raise ValueError("Unsupported native LHAPDF linker policy/preparation")
    share = native_build_root()/"tools/miniforge3/envs/pipeline/share/mapyde"
    def input_file(key, fallback=None):
        value = declared_inputs.get(key, fallback)
        if not value or not isinstance(value, (str, Path)) or "{{" in str(value):
            raise ValueError(f"explicit {key} input is unresolved")
        path = Path(value)
        path = path.resolve() if path.is_absolute() else (rundir/path).resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"{key} input missing or empty: {path}")
        inputs[key] = str(path); source_paths.append(path)
        return path
    delphes_card = input_file("delphes_card", share/"cards/delphes"/str(cfg.get("delphes", {}).get("card", "")) if legacy else None)
    if preparation == "slepton-bino":
        from . import prepare_native_slepton as prep
        masses = cfg.get("madgraph", {}).get("masses", {})
        parent = positive(masses.get("MSLEP"), "slepton mass")
        child = float(masses.get("MN1", math.nan))
        if not math.isfinite(child) or child < 0 or child >= parent:
            raise ValueError("invalid slepton-bino masses")
        if m_parent is not None and parent != m_parent or m_lsp is not None and child != m_lsp:
            raise ValueError("TOML masses disagree with the scan point")
        selected_pdf = pdf or native.get("pdf")
        if selected_pdf not in ("cteq6l1", "nn23nlo", "nnpdf30"):
            raise ValueError("slepton preparation requires an explicit supported PDF")
        input_file("param_template", prep.BASE_PARAM); input_file("run_template", prep.BASE_RUNCARD)
        input_file("process_card", prep.GEN_TEMPLATE)
        # Reuse only the specifically registered adapter. Rendering to a string
        # allows a dry plan to check every input without modifying the run.
        rendered = prep.render_inputs(parent, child, nevents, seed, run.get("options"), selected_pdf, ecms,
                                      param_template=inputs["param_template"], run_template=inputs["run_template"])
        expected_masses = {str(p): parent for p in MODEL_PDGS[declared_model][0]}
        expected_masses["1000022"] = child
    else:
        for key in ("process_card", "param_card", "run_card", "shower_card"):
            input_file(key)
        produced, matrix_element_jets = validate_process_card(inputs["process_card"], declared_model, with_jet_count=True)
        expected_masses = validate_param_card(inputs["param_card"], declared_model, m_parent, m_lsp,produced=produced)
        assignments = card_assignments(inputs["run_card"])
        if matrix_element_jets == 0:
            # MadGraph's cuts.f rejects zero-jet events when either of these
            # positive cuts requests a jet, even in a 2->2 process. A nominally
            # inclusive denominator must not inherit the tagged sample's cut.
            for key in ("ptj1min", "htjmin"):
                if key in assignments:
                    value = float(assignments[key])
                    if not math.isfinite(value) or value > 0:
                        raise ValueError(f"zero-parton process conflicts with jet-existence cut {key}")
        required = {"nevents": nevents, "iseed": seed, "ebeam1": ecms/2, "ebeam2": ecms/2, "ickkw": 0}
        for key, value in required.items():
            try:
                actual = float(assignments[key])
            except (KeyError, ValueError) as exc:
                raise ValueError(f"explicit run card is missing numeric {key}") from exc
            if not math.isfinite(actual) or actual != value:
                raise ValueError(f"explicit run card {key} disagrees with plan (unmerged LO only)")
        if assignments.get("use_syst", "").lower() not in ("false", ".false."):
            raise ValueError("explicit run card must disable extra systematic weights")
        if not assignments.get("pdlabel"):
            raise ValueError("explicit run card lacks PDF choice")
        if pdf is not None and pdf != assignments["pdlabel"]:
            raise ValueError("--pdf disagrees with the explicit run card; cards are never silently rewritten")
        shower = card_assignments(inputs["shower_card"], "shower")
        if shower.get("Beams:frameType") != "4" or shower.get("JetMatching:merge", "off").lower() not in ("off", "false"):
            raise ValueError("shower card must explicitly select LHE input and unmerged showering")
        if any(key.startswith("Merging:") and value.lower() not in ("off","false","0","0.0") for key,value in shower.items()):
            raise ValueError("merging settings need a different normalization adapter")
        if "Beams:LHEF" not in shower:
            raise ValueError("shower card must declare Beams:LHEF (path will be bound to generated events)")
        if "Main:numberOfEvents" in shower and float(shower["Main:numberOfEvents"]) != nevents:
            raise ValueError("shower event count disagrees with plan")
    validate_process_card(inputs["process_card"], declared_model)
    if statistics != "yields":
        background = input_file("likelihood", share/"likelihoods"/str(cfg.get("pyhf", {}).get("likelihood", "")) if legacy else None)
        workspace = json.loads(background.read_text())
        import pyhf
        try:
            pyhf.Workspace(workspace)
        except Exception as exc:
            raise ValueError("likelihood is not a valid pyhf workspace") from exc
        from .sa2json_native import signal_poi
        if signal_poi(workspace)!="mu_SIG" and statistics=="compressed-likelihood":
            raise ValueError("compressed likelihood adapter requires its declared mu_SIG POI")
        channels = workspace.get("channels", [])
        if not channels or len({c["name"] for c in channels}) != len(channels):
            raise ValueError("likelihood needs distinct named channels")
        if statistics == "mapped-likelihood":
            mapping = json.loads(input_file("channel_map").read_text())
            from .sa2json_native import validate_channel_map
            validate_channel_map(mapping, workspace)
            import importlib
            module = (importlib.import_module("ravel.physics.native_simpleanalysis") if routine == "EwkCompressed2018"
                      else importlib.import_module(REGISTRY[routine]))
            regions = set(module.sr_order())
            flags = set(getattr(module,"FLAVOUR_FLAGS",("isee","ismm")))
            if any(entry is not None and (entry["region"] not in regions or entry.get("flavour") is not None and entry["flavour"] not in flags) for entry in mapping.values()):
                raise ValueError("channel map names a region or flavour absent from the requested routine")
        else:
            from .sa2json_native import compressed_channel_map
            from .native_simpleanalysis import sr_order, cr_order
            regions = set(sr_order()) | set(cr_order())
            mapping = compressed_channel_map(workspace, compressed_signal_model)
            for entry in mapping.values():
                if entry is not None and entry["region"] not in regions:
                    raise ValueError("compressed likelihood channel is not a supported region/flavour")
    out = rundir/"output"
    plan_path = rundir/"inputs/native_execution_plan.json"
    tools = native_build_root()/"tools"
    conda = str(tools/"miniforge3/bin/conda")
    required_tools = [conda,str(tools/"mg5amcnlo/bin/mg5_aMC"),str(native_binary("pythia_shower")),
                      str(tools/"miniforge3/envs/recast/bin/DelphesHepMC3")]
    required_tools += [str(tools/"miniforge3/envs"/env/"bin/python") for env in ("mg5","rivet","recast")]
    converter = tools/"miniforge3/envs/pipeline/share/mapyde/scripts/Delphes2SA.py"
    # The installed converter is an explicit declared dependency, not whatever
    # an inherited D2SA environment variable happens to select during execution.
    if converter.is_file():
        source_paths.append(converter)
    if capability["needs_restframes"]:
        required_tools.append(str(native_binary("rjr_resolve")))
    source_paths.extend(Path(p) for p in required_tools if Path(p).is_file())
    if statistics_python is not None:
        # A virtual environment often symlinks Python to an already declared
        # native interpreter. Its configuration still selects a different
        # package environment, while the executable is only one input artifact.
        environment_config = Path(statistics_python).parent.parent / "pyvenv.cfg"
        if environment_config.is_file():
            source_paths.append(environment_config)
    generation_linker = None
    if linker_policy is not None:
        from . import native_lhapdf as link
        decision_path = input_file("lhapdf_link_decision")
        decision = link.validate_generation_decision(link.read_decision(decision_path), tools/"miniforge3/envs/mg5")
        assignments = card_assignments(inputs["run_card"])
        if assignments.get("pdlabel") != "lhapdf" or assignments.get("lhaid") != str(link.PDF_ID):
            raise ValueError("The linker policy requires explicit LHAPDF260000 central-member cards")
        if any(line.split("#", 1)[0].strip().startswith("set ") for line in Path(inputs["process_card"]).read_text().splitlines()):
            raise ValueError("This linker policy does not accept process-card environment overrides")
        generation_linker = linker_contract(rundir, decision_path, decision)
        source_paths.extend(Path(item["path"]) for item in decision["sources"].values())
        source_paths.append(Path(link.__file__))
    if lhe_provenance is not None:
        wrapper_source = Path(__file__).resolve().parents[3]/"native/src/pythia_shower.cc"
        if not wrapper_source.is_file() or wrapper_source.is_symlink():
            raise ValueError("original-v1 requires the wrapper source checkout and separately built binary")
        source_paths += [Path(__file__).with_name("lhe_provenance.py"), wrapper_source]
    source_paths = list(dict.fromkeys(Path(p).resolve() for p in source_paths))
    def python(env, module, *args):
        return module_command(module, *args, python=[conda, "run", "--live-stream", "-p", str(tools/"miniforge3/envs"/env), "python"])
    def local(*args):
        return module_command("ravel.physics.native_pipeline", *args)
    stages = []
    from ravel.workflow.workflow_state import approval_input_paths
    approval_paths = [*approval_input_paths(str(rundir)),str(rundir/"inputs/checkin1_approval.json")]
    def stage(name, command, ins, outputs, dependencies):
        # Code and source configuration are explicit inputs of every stage, so
        # a changed routine or adapter invalidates existing execution receipts.
        ins = list(dict.fromkeys(str(Path(p).resolve()) for p in [*ins,*source_paths,*approval_paths]))
        stages.append({"stage": name, "command": list(map(str, command)), "inputs": ins,
                       "outputs": list(map(str, outputs)), "depends_on": dependencies})
    cards = [out/n for n in ("param_card.dat", "run_card.dat", "run.mg5", "shower.cfg")]
    stage("prepare", local("prepare", "--plan", plan_path), [*source_paths, plan_path], cards, [])
    lhe = out/"madgraph/unweighted_events.lhe"
    stage("madgraph", local("generate", "--plan", plan_path), [plan_path,*cards[:3]],
          [str(lhe)+".gz", *([generation_linker["execution_record"]] if generation_linker else [])], ["prepare"])
    stage("unpack_lhe", local("unpack", "--input", str(lhe)+".gz", "--output", lhe), [str(lhe)+".gz"], [lhe], ["madgraph"])
    gate = out/"lhe_check.json"
    gate_args = [arg for pdg, mass in expected_masses.items() for arg in ("--expect-mass", f"{pdg}:{mass}")]
    stage("lhe_check", python("rivet","ravel.validation.lhe_check",lhe,"--expect-from-card",cards[0],"--json-out",gate,*gate_args), [lhe,cards[0]], [gate], ["unpack_lhe"])
    hepmc = out/("madgraph/events.hepmc.gz" if event_storage == "gzip" else "madgraph/events.hepmc")
    shower_command = (python("rivet", "ravel.physics.native_event_io", "shower",
                            "--binary", native_binary("pythia_shower"), "--card", cards[3],
                            "--output", hepmc, "--events", nevents)
                      if event_storage == "gzip" else
                      [conda,"run","--live-stream","-p",str(tools/"miniforge3/envs/rivet"),native_binary("pythia_shower"),cards[3],hepmc,nevents])
    shower_outputs = [hepmc, str(hepmc)+".storage.json"] if event_storage == "gzip" else [hepmc]
    shower_inputs = [lhe, cards[3], gate]
    if lhe_provenance is not None:
        sidecar = out/"madgraph/original-lhe.jsonl"
        provenance_report = out/"madgraph/lhe-provenance.json"
        shower_command = python("rivet", "ravel.physics.native_event_io", "shower-original",
            "--binary", native_binary("pythia_shower"), "--card", cards[3],
            "--output", hepmc, "--events", nevents, "--encoding", event_storage,
            "--lhe", lhe, "--sidecar", sidecar, "--verification", provenance_report,
            "--wrapper-source", wrapper_source, "--run-card", cards[1])
        shower_inputs += [cards[1]]
        shower_outputs += [sidecar, provenance_report]
    stage("pythia",shower_command, shower_inputs, shower_outputs, ["lhe_check"])
    normalization = out/"normalization.json"
    logs = [rundir/"logs/madgraph.log",rundir/"logs/pythia.log"]
    stage("normalization",module_command("ravel.physics.native_normalization","--lhe",lhe,"--madgraph-log",logs[0],"--shower-log",logs[1],"--kfactor",kfactor,"--nevents",nevents,"--out",normalization),[lhe,*logs], [normalization],["pythia"])
    detector_output = out/"delphes/delphes.root"
    detector_binary = tools/"miniforge3/envs/recast/bin/DelphesHepMC3"
    detector_command = (python("recast", "ravel.physics.native_event_io", "delphes",
                              "--binary", detector_binary, "--card", delphes_card,
                              "--output", detector_output, "--input", hepmc)
                        if event_storage == "gzip" else
                        [conda,"run","--live-stream","-p",str(tools/"miniforge3/envs/recast"),str(detector_binary),delphes_card,detector_output,hepmc])
    stage("delphes",detector_command, [hepmc,delphes_card], [detector_output], ["normalization"])
    sa_input = out/"analysis/Delphes2SA.root"
    stage("analysis",python("recast","ravel.physics.delphes2sa_native","--input",detector_output,"--output",sa_input,"--lumi",lumi,"--normalization",normalization,"--converter-script",converter,"--recast-env",tools/"miniforge3/envs/recast"),[detector_output,normalization,converter], [sa_input,str(sa_input)+".normalization.json"],["delphes"])
    outputs = [out/(routine+".root"),out/(routine+".txt")]
    extra = ["--rjr-binary",native_binary("rjr_resolve"),"--recast-env",tools/"miniforge3/envs/recast","--rjr-conda",conda] if capability["needs_restframes"] else []
    helper_outputs = [out/"native_objects.txt",out/"native_rjr.csv"] if capability["needs_restframes"] else []
    if routine == "EwkCompressed2018":
        parents, child_pdg = MODEL_PDGS[declared_model]
        parent_masses = {float(expected_masses[str(p)]) for p in parents if str(p) in expected_masses}
        if len(parent_masses) != 1:
            raise ValueError("compressed validation needs one declared degenerate parent mass")
        extra += ["--validation-masses", str(next(iter(parent_masses))), str(expected_masses[str(child_pdg)]),
                  "--compressed-signal-model", compressed_signal_model]
        helper_outputs += [out/"compressed_trace.jsonl.gz", out/"compressed_validation.json"]
    stage("simpleanalysis",python("rivet","ravel.physics.native_simpleanalysis","--input",sa_input,"--output",out,"--ngen",nevents,*extra,"--routine",routine),[sa_input],[*outputs,*helper_outputs],["analysis"])
    if statistics != "yields":
        patch = out/(routine+"_patch.json")
        args = ["-i",outputs[0],"-o",patch,"-n","native_signal","-b",inputs["likelihood"],"-l",lumi]
        args += ["-c"] if statistics == "compressed-likelihood" else ["--channel-map",inputs["channel_map"]]
        signal_metadata = out/"signal_model.json"
        args += ["--mc-stat", mc_stat, "--signal-metadata", signal_metadata]
        if statistics == "compressed-likelihood":
            args += ["--compressed-signal-model", compressed_signal_model]
        stage("sa2json",python("rivet","ravel.physics.sa2json_native",*args),[outputs[0],inputs["likelihood"],*([inputs["channel_map"]] if "channel_map" in inputs else [])],[patch,signal_metadata],["simpleanalysis"])
        statistics_env = "recast" if fit_backend == "jax" else "rivet"
        fit_args = ["likelihood","--bkg",inputs["likelihood"],"--patch",patch,"--out",out,"--backend",fit_backend]
        fit_command = (module_command("ravel.physics.pyhf_exclude", *fit_args, python=statistics_python)
                       if statistics_python is not None else
                       python(statistics_env,"ravel.physics.pyhf_exclude",*fit_args))
        stage("pyhf",fit_command,[inputs["likelihood"],patch,signal_metadata],[out/"exclusion.json"],["sa2json"])
    stage("native_report",local("report","--plan",plan_path),[plan_path,*outputs,normalization],[out/"native_execution_result.json"],[stages[-1]["stage"]])
    plan = {"schema_version":1,"rundir":str(rundir),"config":str(config),"plan_path":str(plan_path),
            "capability":capability,"nevents":nevents,"seed":seed,"ecms_gev":ecms,
            "luminosity_pb_inverse":lumi,"kfactor":kfactor,"expected_masses_gev":expected_masses,
            "event_storage":event_storage,"compressed_signal_model":compressed_signal_model,
            "mc_stat":mc_stat,"pyhf_backend":fit_backend,
            "statistics_python":statistics_python,
            "campaign_points":campaign_points,"required_compute_plan":("scan" if campaign_points > 1 else "full" if nevents > 1000 else "smoke"),
            "inputs":inputs,"rendered":rendered,"sources":[fingerprint(p) for p in source_paths],
            "generator_command":[conda,"run","--live-stream","-p",str(tools/"miniforge3/envs/mg5"),str(tools/"mg5amcnlo/bin/mg5_aMC"),str(cards[2])],
            "stages":stages,"required_tools":required_tools,"required_backend_files":[str(converter)],"compute_authorized":False,
            "limitations":["Unmerged LO MSSM generation only", "Execution registration is not physics certification"]}
    if generation_linker is not None:
        plan["generation_linker"] = generation_linker
        plan["generator_command"] = activated_command(plan)
    if lhe_provenance is not None:
        plan["lhe_provenance"] = {"policy": lhe_provenance, "sidecar": str(sidecar),
            "verification": str(provenance_report), "wrapper_source": str(wrapper_source),
            "scope": "New-generation original-LHA identity only; no replay byte equality or physics certification"}
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def plan_hash(plan):
    content = {k:v for k,v in plan.items() if k != "plan_sha256"}
    return hashlib.sha256(json.dumps(content,sort_keys=True,allow_nan=False).encode()).hexdigest()


def write_plan(plan):
    path = Path(plan["plan_path"])
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(plan,indent=2,allow_nan=False)+"\n")
    return path


def load_plan(path):
    plan = json.loads(Path(path).read_text())
    if plan_hash(plan) != plan.get("plan_sha256"):
        raise ValueError("native execution plan changed")
    for source in plan["sources"]:
        if fingerprint(source["path"])["sha256"] != source["sha256"]:
            raise ValueError(f"native input changed since planning: {source['path']}")
    return plan


def prepare(plan):
    out = Path(plan["rundir"])/"output"
    out.mkdir(parents=True,exist_ok=True)
    inputs = plan["inputs"]
    if plan["capability"]["preparation"] == "slepton-bino":
        for name,text in plan["rendered"].items():
            (out/name).write_text(text)
        shower = "Beams:frameType = 4\nBeams:LHEF = GENERATED\nPrint:quiet = on\n"
    else:
        for name in ("param_card", "run_card"):
            shutil.copyfile(inputs[name],out/(name+".dat"))
        shower = Path(inputs["shower_card"]).read_text()
    lhe = out/"madgraph/unweighted_events.lhe"
    shower = re.sub(r"(?m)^\s*Beams:LHEF\s*=.*$",f"Beams:LHEF = {lhe}",shower)
    (out/"shower.cfg").write_text(shower)
    process = Path(inputs["process_card"]).read_text().rstrip()
    # The generator runs in its own fresh attempt directory. Relative PROC is
    # intentional; stable downstream LHE files are never inside that directory.
    (out/"run.mg5").write_text(f"{process}\noutput PROC_madgraph\nlaunch PROC_madgraph\nmadspin=OFF\nshower=OFF\nreweight=OFF\ndone\n{out/'param_card.dat'}\n{out/'run_card.dat'}\ndone\n")
    for dirname in ("madgraph","analysis","delphes"):
        (out/dirname).mkdir(exist_ok=True)


def linker_contract(rundir, decision_path, decision):
    """Deterministic opt-in extension; no default-plan or toolchain mutation."""
    from .native_lhapdf import GENERATION_POLICY
    root = Path(rundir).resolve()
    return {"policy": GENERATION_POLICY, "decision": fingerprint(decision_path),
            "prefix": decision["prefix"], "python": decision["python"],
            "payload_command": [decision["python"], "-O", "-B",
                                decision["sources"]["madgraph"]["path"], "-s", str(root/"output/run.mg5")],
            "execution_record": str(root/"output/madgraph/linker_execution.json")}


def activated_command(plan):
    contract = plan["generation_linker"]
    prefix = Path(contract["prefix"])
    conda = prefix.parents[1]/"bin/conda"
    return module_command("ravel.physics.native_pipeline", "generate-activated", "--plan", plan["plan_path"],
                          python=[str(conda), "run", "--live-stream", "-p", str(prefix),
                                  str(prefix/"bin/python"), "-B"])


def checked_linker(plan):
    from . import native_lhapdf as link
    contract = plan.get("generation_linker")
    if not isinstance(contract, dict):
        raise ValueError("Activated generation requires an explicit prospective linker contract")
    decision_path = plan["inputs"].get("lhapdf_link_decision")
    if not decision_path:
        raise ValueError("Missing approved linker decision")
    decision = link.validate_generation_decision(link.read_decision(decision_path), contract.get("prefix"))
    expected = linker_contract(plan["rundir"], decision_path, decision)
    if link.canonical(contract) != link.canonical(expected) or plan["generator_command"] != activated_command(plan):
        raise ValueError("Activated command or contract differs from its pinned decision")
    sources = {item["path"]: item["sha256"] for item in plan["sources"]}
    if len(sources) != len(plan["sources"]):
        raise ValueError("Duplicate native source pins")
    for item in [expected["decision"], *decision["sources"].values()]:
        if sources.get(item["path"]) != item["sha256"] or fingerprint(item["path"]) != item:
            raise ValueError("Linker decision source was omitted or changed")
    assignments = card_assignments(plan["inputs"]["run_card"])
    if assignments.get("pdlabel") != "lhapdf" or assignments.get("lhaid") != str(link.PDF_ID):
        raise ValueError("Activated generation requires the exact declared reference PDF")
    if any(line.split("#", 1)[0].strip().startswith("set ") for line in Path(plan["inputs"]["process_card"]).read_text().splitlines()):
        raise ValueError("Process card overrides are outside the activated policy")
    return expected, decision


def write_new_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def activated_result(plan, attempt, decision, contract, *, status, returncode=None):
    return {"schema_version": 1, "status": status, "plan_sha256": plan["plan_sha256"],
            "decision_input": contract["decision"], "actual_decision": decision,
            "command": contract["payload_command"], "cwd": str(attempt),
            "returncode": returncode, "physics_certified": False}


def generate_activated(plan):
    """Run only inside the selected activated environment, under the outer stage.

    This entry does not activate conda again. It reuses original approval and
    emits an explicit subprocess record; only the supervisor can accept a stage.
    """
    verify_execution_approval(plan)
    contract, expected = checked_linker(plan)
    root = Path(plan["rundir"]).resolve(); attempt = Path.cwd().resolve()
    if attempt.parent != (root/"work/madgraph").resolve() or not attempt.name.startswith("attempt-"):
        raise ValueError("Activated MG must run in the outer stage's retained fresh attempt")
    from . import native_lhapdf as link
    actual = None
    try:
        effective, actual = link.generation_decision(contract["prefix"])
        if link.canonical(actual) != link.canonical(expected):
            raise ValueError("Actual activated environment differs from the approved decision")
        before = activated_result(plan, attempt, actual, contract, status="preparation_verified")
        write_new_json(attempt/"linker_preflight.json", before)
        # Explicit -O matches MG's normal optimized entry, -s avoids its optional
        # caffeinate child, and inherited bytecode suppression reaches all Python
        # descendants. No shell expansion or second activation occurs here.
        result = subprocess.run(contract["payload_command"], cwd=attempt, env=effective)
        if result.returncode:
            failed = dict(before, status="madgraph_subprocess_failed", returncode=result.returncode)
            write_new_json(attempt/"linker_failure.json", failed)
            return result.returncode
        load_plan(plan["plan_path"])
        verify_execution_approval(plan)
        checked_linker(plan)
        source = attempt/"PROC_madgraph/Events/run_01/unweighted_events.lhe.gz"
        if not source.is_file() or not source.stat().st_size:
            raise ValueError("MadGraph did not produce a complete compressed LHE")
        completed = activated_result(plan, attempt, actual, contract,
                                     status="madgraph_subprocess_completed", returncode=0)
        completed["retained_lhe"] = fingerprint(source)
        write_new_json(contract["execution_record"], completed)
        return 0
    except Exception as exc:
        failure = {"schema_version": 1, "status": "activated_generation_failed",
                   "plan_sha256": plan["plan_sha256"], "decision_input": contract["decision"],
                   "actual_decision": actual, "cwd": str(attempt), "error": str(exc),
                   "physics_certified": False}
        path = attempt/"linker_failure.json"
        if not path.exists():
            write_new_json(path, failure)
        raise


def verify_activated_result(plan, attempt):
    from . import native_lhapdf as link
    contract, decision = checked_linker(plan)
    record = link.read_decision(contract["execution_record"])
    expected = activated_result(plan, attempt, decision, contract,
                                status="madgraph_subprocess_completed", returncode=0)
    source = attempt/"PROC_madgraph/Events/run_01/unweighted_events.lhe.gz"
    expected["retained_lhe"] = fingerprint(source)
    if link.canonical(record) != link.canonical(expected):
        raise ValueError("Actual MG completion record disagrees with the approved generation")
    return record


def generate(plan):
    """Keep each mutable MadGraph PROC and publish only its completed LHE."""
    verify_execution_approval(plan)
    linked = "generation_linker" in plan
    if linked:
        if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
            raise ValueError("Activated generation requires inherited bytecode suppression")
        checked_linker(plan)
    root = Path(plan["rundir"])
    attempts = root/"work/madgraph"
    attempts.mkdir(parents=True,exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="attempt-",dir=attempts))
    print(f"MadGraph working directory: {attempt}",flush=True)
    result = subprocess.run(plan["generator_command"],cwd=attempt)
    if result.returncode:
        return result.returncode
    if linked:
        load_plan(plan["plan_path"])
        verify_execution_approval(plan)
        verify_activated_result(plan, attempt)
    source = attempt/"PROC_madgraph/Events/run_01/unweighted_events.lhe.gz"
    target = root/"output/madgraph/unweighted_events.lhe.gz"
    if not source.is_file() or not source.stat().st_size:
        raise ValueError("MadGraph did not produce a complete compressed LHE")
    # Exclusive creation catches undeclared reuse; the supervisor archives a
    # prior declared output before a retry. The attempt directory is retained.
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src,dst)
    return 0


def verify_execution_approval(plan):
    """Bind current human-recorded approval to this exact executable proposal."""
    from ravel.workflow.workflow_state import verify_approval,approval_input_paths
    from ravel.workflow.state_io import read_json
    root=Path(plan["rundir"])
    if plan_hash(plan)!=plan.get("plan_sha256"):
        raise ValueError("native execution plan changed")
    required="scan" if plan["campaign_points"]>1 else "full" if plan["nevents"]>1000 else "smoke"
    if plan.get("required_compute_plan")!=required:
        raise ValueError("execution compute rung disagrees with actual point/event scope")
    errors=verify_approval(str(root),required_plan=required)
    if errors:
        raise ValueError("native compute approval refused: "+"; ".join(errors))
    paths=approval_input_paths(str(root))
    contract,budget=read_json(paths[0]),read_json(paths[2])
    pin=contract.get("execution_plan")
    if not isinstance(pin,dict) or (root/pin["path"]).resolve()!=Path(plan["plan_path"]):
        raise ValueError("task contract must pin this saved native execution plan before approval")
    saved=Path(plan["plan_path"])
    if fingerprint(saved)["sha256"]!=pin["sha256"] or plan_hash(load_plan(saved))!=plan_hash(plan):
        raise ValueError("saved execution plan does not match the approved bytes")
    cap=plan["capability"];targets=contract.get("targets",{})
    if targets.get("model")!=cap["model"] or not set(targets.get("analysis",[])).intersection(cap["analysis_ids"]):
        raise ValueError("approved model/analysis scope disagrees with execution")
    if contract.get("detector_mode")!="simpleanalysis-delphes-native":
        raise ValueError("approved detector scope disagrees with native execution")
    allowed_stats=("stability-only",) if cap["statistics_adapter"]=="yields" else ("published-likelihood","simplified-likelihood")
    if contract.get("stat_mode") not in allowed_stats:
        raise ValueError("approved statistical scope disagrees with actual native outputs")
    if not math.isclose(positive(targets.get("lumi_fb"),"approved luminosity")*1000,plan["luminosity_pb_inverse"],rel_tol=1e-12):
        raise ValueError("approved luminosity disagrees with native execution")
    approved_masses=targets.get("masses_gev",[])
    if any(not any(math.isclose(mass,value,rel_tol=1e-12,abs_tol=1e-12) for value in approved_masses)
           for mass in plan["expected_masses_gev"].values()):
        raise ValueError("actual point masses are outside approved scope")
    if (budget.get("backend")!="native" or integer(budget.get("points"),"approved points")<plan["campaign_points"]
            or integer(budget.get("events_per_point"),"approved events per point")<plan["nevents"]):
        raise ValueError("actual native computation exceeds approved backend/point/event budget")
    return True


def execute_plan(plan, *, supervisor=None, resume=True):
    verify_execution_approval(plan)
    missing = [path for path in plan["required_tools"] if not Path(path).is_file() or not os.access(path,os.X_OK)]
    missing.extend(path for path in plan["required_backend_files"] if not Path(path).is_file())
    if missing:
        raise ValueError("native backend is unavailable: " + ", ".join(missing))
    if supervisor is None:
        from ravel.workflow.stage_supervisor import supervise
        supervisor = supervise
    rundir = Path(plan["rundir"])
    # Approval pins these existing bytes. Do not rewrite or regenerate a plan
    # after approval, including on resume.
    for stage in plan["stages"]:
        # Revalidate original inputs before every stage, including resumed runs.
        load_plan(plan["plan_path"])
        verify_execution_approval(plan)
        result = supervisor(stage["stage"],str(rundir),plan["nevents"],str(rundir/"logs"/(stage["stage"]+".log")),
                            stage["command"],inputs=stage["inputs"],outputs=stage["outputs"],
                            depends_on=stage["depends_on"],resume=resume,cwd=str(rundir))
        if result != 0:
            return result
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action",required=True)
    for action in ("plan","run"):
        p = subs.add_parser(action);p.add_argument("--rundir");p.add_argument("--config");p.add_argument("--model")
        p.add_argument("--analysis-id");p.add_argument("--pdf");p.add_argument("--plan");p.add_argument("--write",action="store_true")
    for action in ("prepare","generate","generate-activated","report"):
        p = subs.add_parser(action);p.add_argument("--plan",required=True)
    p=subs.add_parser("unpack");p.add_argument("--input",required=True);p.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    try:
        if args.action == "unpack":
            with gzip.open(args.input,"rb") as source, open(args.output,"wb") as target:
                shutil.copyfileobj(source,target)
            return 0
        if args.action in ("prepare","generate","generate-activated","report"):
            plan=load_plan(args.plan)
            if args.action == "prepare": prepare(plan)
            elif args.action == "generate": return generate(plan)
            elif args.action == "generate-activated": return generate_activated(plan)
            else:
                out=Path(plan["rundir"])/"output"
                actual=plan["capability"]["routine"]
                for extension in (".root",".txt"):
                    if not (out/(actual+extension)).is_file():raise ValueError("requested routine outputs are missing")
                result={"analysis":actual,"model":plan["capability"]["model"],"detector":plan["capability"]["detector"],
                        "statistics":plan["capability"]["statistics_adapter"],"plan_sha256":plan["plan_sha256"],
                        "physics_certified":False,"normalization":fingerprint(out/"normalization.json"),
                        "outputs":[fingerprint(out/(actual+ext)) for ext in (".root",".txt")]}
                (out/"native_execution_result.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
            return 0
        if args.plan: plan=load_plan(args.plan)
        else:
            if not args.rundir or not args.config:parser.error("--rundir and --config are required without --plan")
            plan=build_execution_plan(args.rundir,args.config,model=args.model,analysis_id=args.analysis_id,pdf=args.pdf)
        if args.action == "plan":
            if args.write:write_plan(plan)
            print(json.dumps(plan,indent=2,allow_nan=False));return 0
        return execute_plan(plan)
    except (ValueError,OSError,KeyError) as exc:
        parser.exit(2,f"native_pipeline: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
