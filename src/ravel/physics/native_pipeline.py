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
from .analysis_packages import PackageInputError, load_package
from .native_normalization import fingerprint, positive

# A routine declaring this helper output writes a per-event cutflow trace.
TRACE_OUTPUT = 'compressed_trace.jsonl.gz'


def read_config(path):
    try:
        import tomllib
    except ImportError as exc:
        raise RuntimeError("Native TOML execution requires Python 3.11 or 3.12") from exc
    with Path(path).open("rb") as stream:
        cfg = tomllib.load(stream)
    if cfg.get("base", {}).get("template"):
        raise ValueError("native planning does not evaluate inherited mapyde templates; supply a resolved TOML or explicit native cards")
    return cfg


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


def require_legacy_regime(cfg):
    """Never silently erase an explicitly requested general generator regime."""
    mg=cfg.get('madgraph',{})
    for name in ('madspin','reweight'):
        value=mg.get(name,'OFF')
        if value not in ('OFF',False,None):
            raise ValueError('requested '+name+' requires the explicit model-events generation route; the legacy pipeline is unmerged LO')
    if mg.get('order','LO') != 'LO' or mg.get('scheme','unmerged_lo') != 'unmerged_lo':
        raise ValueError('requested perturbative/matching regime requires model-events; it cannot become unmerged LO')
    for section in (mg,mg.get('run',{}),cfg.get('generation',{})):
        for name in ('matching','merging','systematics','use_syst','reweight_scale','reweight_pdf'):
            if name in section and section[name] not in ('OFF','none',False,None,0):
                raise ValueError('requested '+name+' requires explicit model-events; legacy generation cannot silently disable it')
        if section.get('ickkw',0)!=0 or section.get('order','LO')!='LO' or section.get('scheme','unmerged_lo')!='unmerged_lo':
            raise ValueError('requested generation regime requires explicit model-events; legacy generation cannot silently replace it')


def require_claim_inputs(cfg, rundir, statistics):
    """Apply native input requirements to operation and ordinary claim records."""
    native = cfg.get("ravel", {}).get("native", {})
    claims = set()
    for logical in ("inputs/plan.json", "inputs/task_contract.json"):
        path = Path(rundir)/logical
        if path.is_file():
            record = json.loads(path.read_text())
            claims.update(row.get("kind") for row in record.get("claims", []))
            if record.get("task_mode") == "reproduce":
                claims.add("agreement")
    if statistics == "mapped-likelihood" or "exclusion" in claims:
        missing = [key for key in ("mc_stat",) if key not in native]
        if missing:
            raise ValueError("native exclusion requires explicit " + ", ".join(missing))
    if "agreement" in claims and not (native.get("inputs", {}).get("delphes_card") or cfg.get("delphes", {}).get("card")):
        raise ValueError("native agreement requires an explicitly declared delphes_card; fallback detector cards are refused")


def output_root(plan):
    return Path(plan.get('output_directory', Path(plan['rundir']) / 'output'))


def log_root(plan):
    return Path(plan.get('log_directory', Path(plan['rundir']) / 'logs'))


def approved_plan_path(rundir):
    """Resolve the saved proposal pinned by this run's task contract."""
    root = Path(rundir).resolve()
    contract = root / 'inputs/task_contract.json'
    if contract.is_file():
        pin = json.loads(contract.read_text()).get('execution_plan')
        if pin is not None:
            path = (root / pin['path']).resolve()
            if not path.is_relative_to(root):
                raise ValueError('native execution plan escapes the run directory')
            return path
    return root / 'inputs/native_execution_plan.json'


def build_execution_plan(rundir, config, *, model=None, analysis_id=None, m_parent=None, m_lsp=None, pdf=None, campaign_points=1):
    rundir = Path(rundir).resolve()
    config = Path(config)
    config = config.resolve() if config.is_absolute() else (rundir/config).resolve()
    cfg = read_config(config)
    require_legacy_regime(cfg)
    from . import native_effective_config as effective
    native = cfg.get("ravel", {}).get("native", {})
    declared_model = native.get("model", model)
    if model is not None and declared_model != model:
        raise ValueError("scan model and native model declaration disagree")
    routine = cfg.get("simpleanalysis", {}).get("name")
    require_claim_inputs(cfg, rundir, native.get('statistics'))
    required_bindings = ('model', 'preparation', 'detector', 'statistics', 'analysis_package')
    missing = [key for key in required_bindings if not native.get(key)]
    if missing:
        raise PackageInputError('missing_native_binding', ', '.join(missing))
    preparation, detector, statistics = (native[key] for key in ('preparation', 'detector', 'statistics'))
    if preparation not in ('explicit-cards', 'slepton-bino') or detector != 'simpleanalysis-delphes' or declared_model not in MODEL_PDGS:
        raise PackageInputError('unsupported_native_binding', 'preparation, detector or model interface is not implemented')
    if statistics not in ('yields', 'mapped-likelihood'):
        raise PackageInputError('unsupported_native_statistics', 'supply yields or mapped-likelihood')
    selected_package = Path(native['analysis_package'])
    selected_package = selected_package if selected_package.is_absolute() else rundir / selected_package
    require_claim_inputs(cfg, rundir, statistics)
    capability = resolve_capability(routine, declared_model, preparation, detector, statistics, analysis_id,
                                    analysis_package=selected_package)
    routine = capability["routine"]  # the adapter key from here on; the supplied name is upstream_routine
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
    if 'compressed_signal_model' in native:
        raise PackageInputError('unsupported_native_binding', 'selection controls belong to the supplied package')
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
    for section in ("madgraph", "delphes", "simpleanalysis"):
        if cfg.get(section, {}).get("skip", False) is not False:
            raise ValueError(f"native workflow requires {section}; skip must be false")
    for section in ("delphes", "simpleanalysis"):
        if cfg.get(section, {}).get("additional_opts", ""):
            raise ValueError(f"native {section}.additional_opts is unsupported; declare validated native adapter controls instead")
    effective.requested_shower(cfg)  # reject controls that the native path would ignore
    inputs, rendered = {}, {}
    source_paths = [config, Path(__file__)]
    if statistics_python is not None:
        source_paths.append(Path(statistics_python))
    source_paths.extend((Path(__file__).parents[1]/"paths.py",Path(__file__).parents[1]/"_bootstrap.py",
                         Path(__file__).parents[1]/"validation/lhe_check.py"))
    source_paths.extend(Path(__file__).with_name(name) for name in
                        ("native_capabilities.py","native_normalization.py","native_event_io.py","native_effective_config.py","prepare_native_slepton.py",
                         "delphes2sa_native.py","native_simpleanalysis.py","sa_native_core.py",
                         "sa2json_native.py","pyhf_exclude.py"))
    source_paths.extend(Path(pin['path']) for pin in capability['source_pins'])
    source_paths.extend((Path(__file__).with_name('analysis_packages.py'),
                         Path(__file__).parent / 'sa_routines' / '__init__.py'))
    trace_contract = None
    if TRACE_OUTPUT in capability['routine_interface']['helper_outputs']:
        # A routine that declares an event trace binds the supplied reviewed cutflow definition
        # to its own selection bytes; every definition dependency joins the approval census.
        from .compressed_validation import native_plan_inputs
        trace_contract = native_plan_inputs(native.get("cutflow_definition"), rundir,
                                            capability['source_pins'][1]['path'])
        source_paths.extend(trace_contract["inputs"])
    elif native.get("cutflow_definition") is not None:
        raise PackageInputError('unsupported_native_binding',
                                'cutflow_definition needs a selected routine that declares an event trace output')
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
    delphes_card = input_file('delphes_card')
    if preparation == "slepton-bino":
        from .prepare_native_slepton import prepare_for_plan
        (rendered, shower_translation, generation_controls, expected_masses,
         selected_pdf, process_selection) = prepare_for_plan(
            cfg, rundir=rundir, input_file=input_file, nevents=nevents,
            seed=seed, ecms=ecms, pdf=pdf, model=declared_model)
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
        selected_pdf = pdf or native.get("pdf")
        if pdf is not None and native.get("pdf") is not None and pdf != native["pdf"]:
            raise ValueError("--pdf conflicts with the native PDF declaration")
        expected_pdf = "lhapdf" if selected_pdf == "nnpdf30" else selected_pdf
        if expected_pdf is not None and (expected_pdf != assignments["pdlabel"] or
                selected_pdf == "nnpdf30" and assignments.get("lhaid") != "260000"):
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
        shower_translation = effective.explicit_shower_controls(cfg, inputs["shower_card"])
        generation_controls = {**run.get("options", {}), **required, "pdlabel": assignments["pdlabel"], "use_syst": False}
        if "lhaid" in assignments: generation_controls["lhaid"] = assignments["lhaid"]
        for key, value in generation_controls.items():
            if key not in assignments or not effective.equivalent(assignments[key], value):
                raise ValueError(f"requested generation control {key} disagrees with explicit run_card; edit a copy")
    validate_process_card(inputs["process_card"], declared_model)
    if statistics != "yields":
        background = input_file("likelihood")
        workspace = json.loads(background.read_text())
        import pyhf
        try:
            pyhf.Workspace(workspace)
        except Exception as exc:
            raise ValueError("likelihood is not a valid pyhf workspace") from exc
        from .sa2json_native import signal_poi
        signal_poi(workspace)  # A unique, signal-only POI is derived from the supplied workspace.
        channels = workspace.get('channels', [])
        if not channels or len({c['name'] for c in channels}) != len(channels):
            raise ValueError('likelihood needs distinct named channels')
        mapping = json.loads(input_file('channel_map').read_text())
        from .sa2json_native import validate_channel_map
        validate_channel_map(mapping, workspace)
        interface = capability['routine_interface']
        regions = set(interface['regions']) | set(capability['control_regions'])
        flags = set(interface['flavour_flags'])
        if any(entry is not None and (entry['region'] not in regions or
               entry.get('flavour') is not None and entry['flavour'] not in flags) for entry in mapping.values()):
            raise ValueError('channel map names a region or flavour absent from the selected package')
    override_path = rundir / 'inputs/active-point-override.json'
    override_record = None
    if override_path.is_file():
        from ravel.workflow import point_overrides as overrides
        override_record = json.loads(override_path.read_text())
        overrides.verify(override_record, config)
    attempt = (rundir / 'attempts' / override_record['receipt_sha256']
               if override_record else rundir)
    out = attempt / "output"
    if override_record:
        rendered = {name: text.replace(str(rundir / 'output'), str(out))
                    for name, text in rendered.items()}
    plan_path = attempt / "inputs/native_execution_plan.json"
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
        generation_linker = linker_contract(rundir, decision_path, decision, output_directory=out)
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
    effective_path = out / Path(effective.MANIFEST).name
    stage("prepare", local("prepare", "--plan", plan_path), [*source_paths, plan_path], [*cards,effective_path], [])
    lhe = out/"madgraph/unweighted_events.lhe"
    stage("madgraph", local("generate", "--plan", plan_path), [plan_path,*cards[:3]],
          [str(lhe)+".gz", *([generation_linker["execution_record"]] if generation_linker else [])], ["prepare"])
    stage("unpack_lhe", local("unpack", "--input", str(lhe)+".gz", "--output", lhe), [str(lhe)+".gz"], [lhe], ["madgraph"])
    gate = out/"lhe_check.json"
    gate_args = [arg for pdg, mass in expected_masses.items() for arg in ("--expect-mass", f"{pdg}:{mass}")]
    stage("lhe_check", python("rivet","ravel.validation.lhe_check",lhe,"--expect-from-card",cards[0],"--json-out",gate,*gate_args), [lhe,cards[0]], [gate], ["unpack_lhe"])
    hepmc = out/("madgraph/events.hepmc.gz" if event_storage == "gzip" else "madgraph/events.hepmc")
    shower_command = python("rivet", "ravel.physics.native_event_io", "shower",
                            "--binary", native_binary("pythia_shower"), "--card", cards[3],
                            "--output", hepmc, "--events", nevents, "--encoding", event_storage)
    shower_outputs = [hepmc, str(hepmc)+".storage.json"] if event_storage == "gzip" else [hepmc]
    shower_outputs.append(str(hepmc)+".shower.json")
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
    logs_dir = rundir / 'logs' / 'attempts' / override_record['receipt_sha256'] if override_record else rundir / 'logs'
    logs = [logs_dir / 'madgraph.log', logs_dir / 'pythia.log']
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
    interface = capability['routine_interface']
    helper_outputs = [out / name for name in interface['helper_outputs']]
    extra += interface['arguments']
    if trace_contract is not None:
        extra += trace_contract['arguments']
    stage('simpleanalysis', python('rivet', 'ravel.physics.native_simpleanalysis', '--input', sa_input,
          '--output', out, '--ngen', nevents, *extra, '--routine', routine,
          '--analysis-package', capability['analysis_package'], '--execution-plan', plan_path),
          [sa_input, *(pin['path'] for pin in capability['source_pins'])],
          [*outputs, *helper_outputs], ['analysis'])
    if statistics != "yields":
        patch = out/(routine+"_patch.json")
        args = ["-i",outputs[0],"-o",patch,"-n","native_signal","-b",inputs["likelihood"],"-l",lumi]
        args += ["--channel-map",inputs["channel_map"]]
        signal_metadata = out/"signal_model.json"
        args += ["--mc-stat", mc_stat, "--signal-metadata", signal_metadata]
        stage("sa2json",python("rivet","ravel.physics.sa2json_native",*args),[outputs[0],inputs["likelihood"],*([inputs["channel_map"]] if "channel_map" in inputs else [])],[patch,signal_metadata],["simpleanalysis"])
        statistics_env = "recast" if fit_backend == "jax" else "rivet"
        fit_args = ["likelihood","--bkg",inputs["likelihood"],"--patch",patch,"--out",out,"--backend",fit_backend]
        fit_command = (module_command("ravel.physics.pyhf_exclude", *fit_args, python=statistics_python)
                       if statistics_python is not None else
                       python(statistics_env,"ravel.physics.pyhf_exclude",*fit_args))
        stage("pyhf",fit_command,[inputs["likelihood"],patch,signal_metadata],[out/"exclusion.json"],["sa2json"])
    quantity_outputs = list(dict.fromkeys(path for item in stages
        if item['stage'] in ('normalization', 'simpleanalysis', 'sa2json', 'pyhf')
        for path in item['outputs']))
    stage("native_report",local("report","--plan",plan_path),[plan_path,*quantity_outputs],[out/"native_execution_result.json"],[stages[-1]["stage"]])
    plan = {"schema_version":1,"rundir":str(rundir),"config":str(config),"plan_path":str(plan_path),
            "capability":capability,"nevents":nevents,"seed":seed,"ecms_gev":ecms,
            "luminosity_pb_inverse":lumi,"kfactor":kfactor,"expected_masses_gev":expected_masses,
            "event_storage":event_storage,
            "mc_stat":mc_stat,"pyhf_backend":fit_backend,
            "statistics_python":statistics_python,
            "campaign_points":campaign_points,"required_compute_plan":("scan" if campaign_points > 1 else "full" if nevents > 1000 else "smoke"),
            "inputs":inputs,"rendered":rendered,"sources":[fingerprint(p) for p in source_paths],
            "generator_command":[conda,"run","--live-stream","-p",str(tools/"miniforge3/envs/mg5"),str(tools/"mg5amcnlo/bin/mg5_aMC"),str(cards[2])],
            "stages":stages,"required_tools":required_tools,"required_backend_files":[str(converter)],"compute_authorized":False,
            "limitations":["Unmerged LO MSSM generation only", "Execution registration is not physics certification"]}
    plan["quantity_outputs"] = quantity_outputs
    if override_record:
        plan['output_directory'] = str(out)
        plan['log_directory'] = str(logs_dir)
    plan["effective_settings"] = str(effective_path)
    plan["shower_translation"] = shower_translation
    plan["effective_controls"] = {
        "generation": generation_controls,
        "process": {"model": declared_model, "source": inputs["process_card"],
                    "declared_mapyde_process": cfg.get("madgraph", {}).get("proc", {}),
                    **({"selection": "explicit native source", "disposition": "native.inputs.process_card is authoritative"}
                       if "process_card" in declared_inputs else process_selection)},
        "statistics": {"luminosity_pb_inverse": lumi, "kfactor": kfactor, "statistics_adapter": statistics,
                       "mc_stat": mc_stat, "pyhf_backend": fit_backend},
        "tool_version_labels": effective.tool_version_labels(cfg)}
    for item in stages:
        if item["stage"] != "prepare": item["inputs"].append(str(effective_path))
    if generation_linker is not None:
        plan["generation_linker"] = generation_linker
        plan["generator_command"] = activated_command(plan)
    if lhe_provenance is not None:
        plan["lhe_provenance"] = {"policy": lhe_provenance, "sidecar": str(sidecar),
            "verification": str(provenance_report), "wrapper_source": str(wrapper_source),
            "scope": "New-generation original-LHA identity only; no replay byte equality or physics certification"}
    # A scan override is a source of the executable proposal, never an approval bypass.
    if override_record:
        record = override_record
        override_path = rundir / ('inputs/point-overrides/' + record['receipt_sha256'] + '.json')
        if not override_path.is_file():
            override_path = rundir / 'inputs/active-point-override.json'
        plan['point_override'] = record
        plan['sources'].append(fingerprint(override_path))
        for stage in stages:
            stage['inputs'].append(str(override_path))
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
    require_claim_inputs(read_config(plan["config"]), plan["rundir"], plan["capability"]["statistics_adapter"])
    return plan


def prepare(plan):
    from ravel.workflow import physics_review
    if physics_review.active(plan["rundir"]) and physics_review.status(plan["rundir"]).get("state") == "correction_admitted":
        raise ValueError("prepare correction cards and derivative plan before admission; admitted effective bytes cannot be regenerated")
    out = output_root(plan)
    out.mkdir(parents=True,exist_ok=True)
    from . import native_effective_config as effective
    if "effective_settings" not in plan:
        raise ValueError("historical plan has no effective-settings contract; create a new prospective plan and approval before execution")
    for name, text in effective.expected_cards(plan).items(): (out/name).write_text(text)
    for dirname in ("madgraph","analysis","delphes"):
        (out/dirname).mkdir(exist_ok=True)
    effective.emit(plan)


def correction_derivative(plan, *, plan_path):
    """Build a conservative amendment with custody of already prepared cards.

    Preparation runs before admission. Its supervised amendment stage only adopts
    the admitted bytes and produces a new receipt, so the original preparation
    receipt need not remain valid after a card correction. All descendants must
    be rerun under this derivative; this is not partial native-result reuse.
    """
    import copy
    root = Path(plan["rundir"]).resolve()
    path = Path(plan_path).resolve()
    if (not path.is_relative_to(root / "inputs") or path == Path(plan["plan_path"]).resolve()
            or path.name in ("task_contract.json", "checkin1.json", "checkin1_approval.json",
                             "checkin2.json", "checkin2_go.json", "cost_preflight.json", "physics_review_policy.json")):
        raise ValueError("native correction needs a distinct derivative plan under inputs/")
    derivative = copy.deepcopy(plan)
    before = plan["plan_path"]
    derivative["plan_path"] = str(path)
    derivative["generator_command"] = [str(path) if value == before else value for value in derivative["generator_command"]]
    for item in derivative["stages"]:
        for field in ("command", "inputs"):
            item[field] = [str(path) if value == before else value for value in item[field]]
    preparation = next(item for item in derivative["stages"] if item["stage"] == "prepare")
    cards = [str(output_root(plan)/name) for name in ("param_card.dat", "run_card.dat", "run.mg5", "shower.cfg")]
    adoption_path = str(output_root(plan)/"native_preparation_adoption.json")
    preparation.update(command=module_command("ravel.physics.native_pipeline", "adopt-preparation", "--plan", str(path)),
                       inputs=list(dict.fromkeys([*preparation["inputs"], *cards, derivative["effective_settings"]])),
                       outputs=[adoption_path], depends_on=[])
    derivative["correction_preparation"] = {"mode": "adopt_frozen_prepared_cards",
        "receipt": adoption_path, "scope": "all_native_descendants_rerun"}
    derivative["plan_sha256"] = plan_hash(derivative)
    return derivative


def build_correction_plan(rundir, config, *, plan_path, **kwargs):
    """Write and prepare a distinct derivative only before correction admission."""
    from ravel.workflow import physics_review
    root = Path(rundir).resolve()
    if physics_review.status(root).get("state") not in ("send_back", "correction_failed"):
        raise ValueError("prepare a native derivative after send-back and before admission")
    reg, events = physics_review._read(root)
    cycle = physics_review._view(reg, events)["cycle"]
    path = Path(plan_path).resolve()
    allowed = {str((root/value).resolve()) for value in reg["policy"]["allowed_changed_paths"]}
    settings = {str((root/value["path"]).resolve()) for value in cycle["effective_settings"]}
    if str(path) not in allowed & settings:
        raise ValueError("derivative plan path must be a prospectively allowed setting in the rejected cycle")
    plan = correction_derivative(build_execution_plan(root, config, **kwargs), plan_path=plan_path)
    write_plan(plan)
    prepare(plan)
    return plan


def adopt_preparation(plan):
    """Verify admitted prepared bytes and write a separate supervised custody witness."""
    verify_execution_approval(plan)
    verify_effective_settings(plan)
    verify_native_stage_authority(plan, "prepare", inside_supervised=True)
    if native_correction(plan) is None:
        raise ValueError("prepared-card adoption requires a current admitted correction")
    from . import native_effective_config as effective
    cards = [fingerprint(output_root(plan)/name) for name in effective.expected_cards(plan)]
    write_new_json(plan["correction_preparation"]["receipt"], {
        "schema_version": 1, "mode": "adopt_frozen_prepared_cards", "plan_sha256": plan["plan_sha256"],
        "effective_settings": fingerprint(plan["effective_settings"]), "cards": cards,
        "physics_certified": False})


def verify_effective_settings(plan):
    from . import native_effective_config as effective
    errors = effective.validate(plan)
    if errors: raise ValueError("native effective settings refused: " + "; ".join(errors))


def native_correction(plan):
    """A derivative is authorized by exact correction snapshots, not the old plan hash.

    The original CI1 approval and its budget remain immutable. A corrected plan
    and manifest must themselves have been scientific settings in the initial
    cycle and be frozen in the admitted amendment. Every source identity stays
    within that amendment; ordinary original-plan approval is never synthesized.
    """
    from ravel.workflow import physics_review
    root = Path(plan["rundir"])
    correction = physics_review.current_correction(root)
    if correction is None:
        return None
    pins = {str((root/item["path"]).resolve()): item["sha256"] for item in correction["snapshots"]}
    required = [plan["plan_path"], plan.get("effective_settings", ""), *(source["path"] for source in plan["sources"])]
    settings = {str((root/item["path"]).resolve()) for item in correction["effective_settings"]}
    if not {str(Path(plan["plan_path"]).resolve()), str(Path(plan.get("effective_settings", "")).resolve())} <= settings:
        raise ValueError("native correction derivative plan and effective manifest must be explicitly bound effective settings")
    for value in required:
        path = str(Path(value).resolve())
        if path not in pins or fingerprint(path)["sha256"] != pins[path]:
            raise ValueError(f"native correction derivative input is outside its exact admitted snapshots: {path}")
    adoption = plan.get("correction_preparation")
    prepare_stage = next((item for item in plan["stages"] if item["stage"] == "prepare"), None)
    expected_receipt = str(output_root(plan)/"native_preparation_adoption.json")
    expected_command = module_command("ravel.physics.native_pipeline", "adopt-preparation", "--plan", plan["plan_path"])
    expected_cards = {str(output_root(plan)/name) for name in ("param_card.dat", "run_card.dat", "run.mg5", "shower.cfg")}
    if (adoption != {"mode": "adopt_frozen_prepared_cards", "receipt": expected_receipt,
                     "scope": "all_native_descendants_rerun"}
            or prepare_stage is None or prepare_stage["command"] != expected_command
            or prepare_stage["outputs"] != [expected_receipt] or prepare_stage["depends_on"]
            or not expected_cards | {plan["plan_path"], plan["effective_settings"]} <= set(prepare_stage["inputs"])):
        raise ValueError("native correction requires isolated adoption of its frozen prepared cards")
    _verify_correction_stage_graph(plan)
    if set(correction["stages"]) != {item["stage"] for item in plan["stages"]}:
        raise ValueError("native correction must rerun adoption and every native descendant")
    verify_effective_settings(plan)
    return correction


def _verify_correction_stage_graph(plan):
    """A conservative amendment cannot drop stages or prerequisites from CI1."""
    from ravel.workflow.workflow_state import approval_input_paths
    from ravel.workflow.state_io import read_json
    root = Path(plan["rundir"])
    contract = read_json(approval_input_paths(str(root))[0])
    pin = contract.get("execution_plan")
    if not isinstance(pin, dict):
        raise ValueError("native amendment needs its immutable original execution-plan pin")
    path = (root/pin["path"]).resolve()
    if fingerprint(path)["sha256"] != pin["sha256"]:
        raise ValueError("original approved native plan bytes changed")
    original = read_json(path)
    if plan_hash(original) != original.get("plan_sha256"):
        raise ValueError("original approved native plan is invalid")
    def graph(value):
        items = value["stages"]
        names = [item["stage"] for item in items]
        if len(names) != len(set(names)):
            raise ValueError("native correction stage names must remain distinct")
        return {item["stage"]: set(item["depends_on"]) for item in items}
    if graph(plan) != graph(original):
        raise ValueError("native correction must preserve the complete approved stage graph")


def accepted_native_derivative(plan):
    """Keep a completed amendment reusable only at its currently accepted exact bytes."""
    from ravel.workflow import physics_review
    root = Path(plan["rundir"])
    if not plan.get("correction_preparation") or not physics_review.active(root):
        return None
    reg, events = physics_review._read(root)
    view = physics_review._view(reg, events)
    if view["state"] != "accepted":
        return None
    # An accepted checkpoint preserves identical settings but does not itself
    # have a correction ID. Locate the amendment supplying those same settings.
    corrected = next((event for event in reversed(events) if event["event"] == "cycle"
                      and event["correction_id"] and event["effective_settings"] == view["cycle"]["effective_settings"]), None)
    if corrected is None:
        return None
    errors = physics_review.gate_errors(root, "reuse")
    if errors:
        raise ValueError("accepted native amendment is not reusable: " + "; ".join(errors))
    pins = {str((root/item["path"]).resolve()): item["sha256"] for item in view["cycle"]["snapshots"]}
    settings = {str((root/item["path"]).resolve()) for item in view["cycle"]["effective_settings"]}
    required = [plan["plan_path"], plan["effective_settings"], *(source["path"] for source in plan["sources"])]
    if not {str(Path(plan["plan_path"]).resolve()), str(Path(plan["effective_settings"]).resolve())} <= settings:
        raise ValueError("accepted native derivative plan and manifest must remain bound effective settings")
    for value in required:
        path = str(Path(value).resolve())
        if path not in pins or fingerprint(path)["sha256"] != pins[path]:
            raise ValueError("accepted native derivative differs from its reviewed exact snapshots: " + path)
    _verify_correction_stage_graph(plan)
    verify_effective_settings(plan)
    return corrected["correction_id"]


def verify_native_stage_authority(plan, name, *, resume=False, inside_supervised=False):
    """Validate the full expanded stage spec; direct correction generation needs its supervisor."""
    from ravel.workflow import physics_review, execution
    root = Path(plan["rundir"])
    if not physics_review.active(root): return None
    stage = next((item for item in plan["stages"] if item["stage"] == name), None)
    if stage is None: raise ValueError("native stage is absent from its derivative execution plan")
    correction = native_correction(plan)
    if correction:
        expanded = execution.plan_stage(root, name, stage["command"], stage["inputs"], stage["outputs"], stage["depends_on"], str(root))
        errors = physics_review.correction_execution_errors(root, name, stage["command"], expanded["inputs"],
                    stage["outputs"], stage["depends_on"], str(root), log=str(log_root(plan)/(name+".log")))
        if inside_supervised:
            record = execution.load_execution(root)["stages"].get(name, {})
            if (record.get("status") != "running" or any(record.get(key) != expanded[key] for key in
                    ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents"))):
                errors.append("direct native correction generation requires its exact running supervised stage")
    else:
        errors = physics_review.gate_errors(root, "reuse" if resume else "bulk", name)
    if errors: raise ValueError("native scientific review refused: " + "; ".join(errors))
    return correction["correction_id"] if correction else None


def linker_contract(rundir, decision_path, decision, *, output_directory=None):
    """Deterministic opt-in extension; no default-plan or toolchain mutation."""
    from .native_lhapdf import GENERATION_POLICY
    root = Path(rundir).resolve()
    out = Path(output_directory) if output_directory is not None else root / "output"
    return {"policy": GENERATION_POLICY, "decision": fingerprint(decision_path),
            "prefix": decision["prefix"], "python": decision["python"],
            "payload_command": [decision["python"], "-O", "-B",
                                decision["sources"]["madgraph"]["path"], "-s", str(out/"run.mg5")],
            "execution_record": str(out/"madgraph/linker_execution.json")}


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
    expected = linker_contract(plan["rundir"], decision_path, decision, output_directory=output_root(plan))
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
    from ravel.workflow import wms_policy
    wms_policy.require_custody(plan["rundir"])
    verify_execution_approval(plan)
    verify_effective_settings(plan)
    verify_native_stage_authority(plan, "madgraph", inside_supervised=True)
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
    from ravel.workflow import wms_policy
    wms_policy.require_custody(plan["rundir"])
    verify_execution_approval(plan)
    verify_effective_settings(plan)
    verify_native_stage_authority(plan, "madgraph", inside_supervised=True)
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
        verify_effective_settings(plan)
        verify_activated_result(plan, attempt)
    source = attempt/"PROC_madgraph/Events/run_01/unweighted_events.lhe.gz"
    target = output_root(plan)/"madgraph/unweighted_events.lhe.gz"
    if not source.is_file() or not source.stat().st_size:
        raise ValueError("MadGraph did not produce a complete compressed LHE")
    # Exclusive creation catches undeclared reuse; the supervisor archives a
    # prior declared output before a retry. The attempt directory is retained.
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src,dst)
    return 0


def verify_execution_approval(plan):
    """Bind current human-recorded approval to this exact executable proposal."""
    from ravel.workflow.workflow_state import verify_approval,verify_approval_envelope,approval_input_paths
    from ravel.workflow.state_io import read_json
    root=Path(plan["rundir"])
    if plan_hash(plan)!=plan.get("plan_sha256"):
        raise ValueError("native execution plan changed")
    capability = plan['capability']
    if not capability.get('analysis_package'):
        raise PackageInputError('missing_analysis_package')
    package = load_package(capability['analysis_package'], require_qualification=True)
    if capability.get('routine') != package['package_id'] or capability.get('routine_interface') != package['routine']:
        raise PackageInputError('package_plan_mismatch')
    for field, predicate in (('model', 'models'), ('preparation', 'preparations'), ('detector', 'detectors'), ('statistics_adapter', 'statistics')):
        if capability.get(field) not in package['compatibility'][predicate]:
            raise PackageInputError('unsupported_package_binding', field)
    source_bindings = {pin['path']: pin['sha256'] for pin in plan['sources']}
    if any(source_bindings.get(pin['path']) != pin['sha256'] for pin in package['source_pins']):
        raise PackageInputError('missing_package_source_binding')
    required="scan" if plan["campaign_points"]>1 else "full" if plan["nevents"]>1000 else "smoke"
    if plan.get("required_compute_plan")!=required:
        raise ValueError("execution compute rung disagrees with actual point/event scope")
    if plan.get('point_override'):
        from ravel.workflow import point_overrides as overrides
        overrides.verify(plan['point_override'], plan['config'])
    correction = native_correction(plan)
    amended = correction or accepted_native_derivative(plan)
    errors=(verify_approval_envelope(str(root), required) if correction else verify_approval(str(root),required_plan=required,disclose=True))
    if errors:
        raise ValueError("native compute approval refused: "+"; ".join(errors))
    paths=approval_input_paths(str(root))
    contract,budget=read_json(paths[0]),read_json(paths[2])
    pin=contract.get("execution_plan")
    if not isinstance(pin,dict) or not amended and (root/pin["path"]).resolve()!=Path(plan["plan_path"]):
        raise ValueError("task contract must pin this saved native execution plan before approval")
    saved=Path(plan["plan_path"])
    if (not amended and fingerprint(saved)["sha256"]!=pin["sha256"]) or plan_hash(load_plan(saved))!=plan_hash(plan):
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
    correction = native_correction(plan)
    selected = plan["stages"]
    if correction:
        names = set(correction["stages"])
        selected = [stage for stage in selected if stage["stage"] in names]
        if {stage["stage"] for stage in selected} != names:
            raise ValueError("admitted correction stages are absent from the native derivative plan")
    # Approval pins these existing bytes. Do not rewrite or regenerate a plan
    # after approval, including on resume.
    log_root(plan).mkdir(parents=True, exist_ok=True)
    for stage in selected:
        # Revalidate original inputs before every stage, including resumed runs.
        load_plan(plan["plan_path"])
        verify_execution_approval(plan)
        if stage["stage"] != "prepare": verify_effective_settings(plan)
        verify_native_stage_authority(plan, stage["stage"], resume=resume and not correction)
        result = supervisor(stage["stage"],str(rundir),plan["nevents"],str(log_root(plan)/(stage["stage"]+".log")),
                            stage["command"],inputs=stage["inputs"],outputs=stage["outputs"],
                            depends_on=stage["depends_on"],resume=resume and not correction,cwd=str(rundir),authorization_plan=plan)
        if result != 0:
            return result
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action",required=True)
    for action in ("plan","run"):
        p = subs.add_parser(action);p.add_argument("--rundir");p.add_argument("--config");p.add_argument("--model")
        p.add_argument("--analysis-id");p.add_argument("--pdf");p.add_argument("--plan");p.add_argument("--write",action="store_true")
    for action in ("prepare","adopt-preparation","generate","generate-activated","report"):
        p = subs.add_parser(action);p.add_argument("--plan",required=True)
    p = subs.add_parser("prepare-correction");p.add_argument("--rundir",required=True);p.add_argument("--config",required=True)
    p.add_argument("--out-plan",required=True);p.add_argument("--model");p.add_argument("--analysis-id");p.add_argument("--pdf")
    p=subs.add_parser("unpack");p.add_argument("--input",required=True);p.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    try:
        if args.action == "unpack":
            with gzip.open(args.input,"rb") as source, open(args.output,"wb") as target:
                shutil.copyfileobj(source,target)
            return 0
        if args.action == "prepare-correction":
            plan = build_correction_plan(args.rundir, args.config, plan_path=args.out_plan,
                                        model=args.model, analysis_id=args.analysis_id, pdf=args.pdf)
            print(json.dumps(plan,indent=2,allow_nan=False));return 0
        if args.action in ("prepare","adopt-preparation","generate","generate-activated","report"):
            plan=load_plan(args.plan)
            if args.action == "prepare": prepare(plan)
            elif args.action == "adopt-preparation": adopt_preparation(plan)
            elif args.action == "generate": return generate(plan)
            elif args.action == "generate-activated": return generate_activated(plan)
            else:
                verify_effective_settings(plan)
                out=output_root(plan)
                actual=plan["capability"]["routine"]
                for extension in (".root",".txt"):
                    if not (out/(actual+extension)).is_file():raise ValueError("requested routine outputs are missing")
                result={"analysis":actual,"model":plan["capability"]["model"],"detector":plan["capability"]["detector"],
                        "statistics":plan["capability"]["statistics_adapter"],"plan_sha256":plan["plan_sha256"],
                        "physics_certified":False,"normalization":fingerprint(out/"normalization.json"),
                        "outputs":[fingerprint(out/(actual+ext)) for ext in (".root",".txt")],
                        "quantity_outputs":[fingerprint(path) for path in plan['quantity_outputs']]}
                if plan.get('point_override'):
                    result['point_receipt_sha256'] = plan['point_override']['receipt_sha256']
                    result['regime'] = plan['point_override']['reason']
                from . import native_effective_config as effective
                result["effective_settings"] = fingerprint(plan["effective_settings"])
                result["runtime_settings_evidence"] = effective.runtime_evidence(plan)
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
