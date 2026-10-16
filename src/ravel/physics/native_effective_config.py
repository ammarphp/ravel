"""Translate declared native controls and distinguish prepared cards from execution.

The MadGraph Pythia interface card is not a native ``Pythia.readFile`` card.
Only its documented inactive unmerged interface controls are removed here. The
actual physics settings are retained, or rejected before generation. This module
does not certify a tune, detector response, or historical runtime version.
"""
from __future__ import annotations

import math
from pathlib import Path
import re

from .native_normalization import fingerprint
from ravel.workflow.state_io import atomic_json, read_json

MANIFEST = "output/native_effective_settings.json"

# These are adapter choices, made explicit in the actual native card. They are
# not an assertion that every mapyde/ATLAS runtime selected these defaults.
ADAPTER_BASELINE = {"Tune:pp": "14", "PartonLevel:MPI": "on"}


def tool_version_labels(cfg):
    """Recipe-ledger input: labels remain distinct from observed versions."""
    return {key: {"declared": cfg[key]["version"],
                  "disposition": "label_only_native_runtime_version_unverified"}
            for key in ("madgraph", "pythia", "delphes", "simpleanalysis")
            if "version" in cfg.get(key, {})}


SETTING_NAMES = (
    "Tune:pp", "Tune:ee", "PartonLevel:MPI", "PartonLevel:ISR", "PartonLevel:FSR",
    "PartonLevel:all", "HadronLevel:all", "HadronLevel:Hadronize", "HadronLevel:Decay",
    "SLHA:useDecayTable", "SLHA:readFrom", "SLHA:keepSM", "SLHA:minMassSM",
    "Random:setSeed", "Random:seed", "Print:quiet", "Next:numberShowEvent",
    "Next:numberCount", "Next:numberShowInfo", "Next:numberShowProcess", "Check:epTolErr",
    "SpaceShower:alphaSvalue", "TimeShower:alphaSvalue", "SpaceShower:pTmaxMatch",
    "TimeShower:pTmaxMatch", "MultipartonInteractions:pT0Ref", "MultipartonInteractions:ecmPow",
    "BeamRemnants:primordialKT", "ColourReconnection:reconnect", "PDF:pSet",
    "Beams:frameType", "Beams:LHEF", "Main:numberOfEvents", "JetMatching:merge",
)
CANONICAL = {key.lower(): key for key in SETTING_NAMES}
INTERFACE_SENTINELS = {
    "hepmcoutput:file": "auto", "jetmatching:qcut": "-1", "jetmatching:njetmax": "-1",
    "jetmatching:doshowerkt": "off", "merging:tms": "-1", "merging:process": "<set_by_user>",
    "merging:njetmax": "-1", "syscalc:fullcutvariation": "off",
}


def equivalent(left, right):
    def normalized(value):
        text = str(value).strip().strip("'\"").lower()
        if text in ("true", ".true.", "on"): return True
        if text in ("false", ".false.", "off"): return False
        try:
            number = float(text.replace("d", "e"))
            if not math.isfinite(number): raise ValueError("nonfinite card setting")
            return number
        except ValueError:
            if text in ("nan", "inf", "+inf", "-inf"): raise ValueError("nonfinite card setting")
            return text
    return normalized(left) == normalized(right)


def assignments(text, *, run=False, strict=False):
    """Read effective values, detecting case-insensitive duplicate settings."""
    result = {}
    seen = set()
    for number, raw in enumerate(text.splitlines(), 1):
        line = re.split(r"[#!]", raw, maxsplit=1)[0].strip()
        if not line: continue
        if "=" not in line:
            if strict: raise ValueError(f"shower line {number} is not a setting assignment")
            continue
        left, right = (part.strip() for part in line.split("=", 1))
        key, value = (right, left) if run else (left, right)
        lowered = key.lower()
        if lowered in seen: raise ValueError(f"duplicate card assignment: {key}")
        seen.add(lowered)
        key = lowered if run else CANONICAL.get(lowered, key)
        if not key or not value or "{{" in value or "}}" in value or ";" in value:
            raise ValueError(f"unresolved or malformed card setting: {key}")
        result[key] = value.strip("'\"")
    return result


def resolve_path(value, *, rundir, share, cfg):
    """Resolve only named path tokens; never evaluate arbitrary Jinja expressions."""
    if not isinstance(value, str) or not value.strip(): raise ValueError("card path must be nonblank")
    replacements = {"MAPYDE_CARDS": str(Path(share)/"cards"), "PWD": str(Path(rundir).resolve())}
    for name, replacement in replacements.items():
        value = re.sub(r"\{\{\s*" + name + r"\s*\}\}", lambda _: replacement, value)
    # The two data-only substitutions used by the shipped mapyde template.
    for expression, replacement in (
        (r"madgraph\[['\"]params['\"]\]", cfg.get("madgraph", {}).get("params")),
        (r"madgraph\[['\"]proc['\"]\]\[['\"]name['\"]\]", cfg.get("madgraph", {}).get("proc", {}).get("name")),
    ):
        if isinstance(replacement, str):
            value = re.sub(r"\{\{\s*"+expression+r"\s*\}\}", lambda _, v=replacement: v, value)
    if "{{" in value or "}}" in value or "://" in value:
        raise ValueError(f"unsupported/unresolved card path template: {value}; supply an explicit local path")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (Path(rundir)/path).resolve()


def configured_card(cfg, role, *, rundir, share, fallback=None):
    """Resolve a configured mapyde card without silently selecting another card."""
    base = cfg.get("base", {})
    fields = {"pythia": (cfg.get("pythia", {}).get("card"), "pythia_path", "pythia"),
              "run": (cfg.get("madgraph", {}).get("run", {}).get("card"), "run_path", "run"),
              "param": (cfg.get("madgraph", {}).get("paramcard"), "param_path", "param"),
              "delphes": (cfg.get("delphes", {}).get("card"), "delphes_path", "delphes"),
              "process": (cfg.get("madgraph", {}).get("proc", {}).get("card"), "process_path", "process")}
    card, base_key, folder = fields[role]
    if card is None:
        if fallback is None: raise ValueError(f"declare the {role} card explicitly")
        path = Path(fallback).resolve()
    else:
        card_path = resolve_path(card, rundir=rundir, share=share, cfg=cfg)
        # A bare card name follows mapyde's configured directory. A supplied
        # relative path with directories is relative to the run directory.
        if not Path(card).is_absolute() and len(Path(card).parts) == 1:
            directory = resolve_path(base.get(base_key, str(Path(share)/"cards"/folder)),
                                     rundir=rundir, share=share, cfg=cfg)
            path = (directory/card_path.name).resolve()
        else: path = card_path
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"configured {role} card missing or empty: {path}; select the intended local card")
    return path


def registered_process(cfg, *, rundir, share, registered):
    """Use the registered source only when the configured MG source agrees.

    The shipped mapyde card ends with ``output -f``. That command belongs to
    mapyde's launch protocol; native preparation supplies its own output and
    launch commands. No other configured process difference is discarded.
    """
    proc = cfg.get("madgraph", {}).get("proc", {})
    if proc.get("contents"):
        raise ValueError("native preparation cannot consume madgraph.proc.contents; supply native.inputs.process_card")
    if not proc.get("card") and "process_path" not in cfg.get("base", {}):
        return None, {"selection": "explicit registered adapter baseline", "source": str(registered)}
    source = configured_card(cfg, "process", rundir=rundir, share=share)
    def commands(path):
        return [line.split("#", 1)[0].strip() for line in Path(path).read_text().splitlines()
                if line.split("#", 1)[0].strip()]
    selected, expected = commands(source), commands(registered)
    removed = bool(selected and selected[-1] == "output -f")
    if removed: selected = selected[:-1]
    if selected != expected:
        raise ValueError(f"configured process card {source} differs from registered isrslep; supply native.inputs.process_card to use that exact process")
    return source, {"selection": "configured process verified against registered native source",
                    "configured_source": fingerprint(source), "source": str(registered),
                    "disposition": "terminal mapyde output -f replaced by native launch protocol" if removed else "exact process commands retained"}


def requested_shower(cfg):
    options = cfg.get("pythia", {})
    if not isinstance(options, dict): raise ValueError("[pythia] must be a table")
    unknown = set(options) - {"skip", "card", "additional_opts", "mpi", "version"}
    if unknown: raise ValueError(f"unsupported native [pythia] controls {sorted(unknown)}; use setting lines in additional_opts")
    if options.get("skip", False) is not False: raise ValueError("native workflow requires Pythia; pythia.skip must be false")
    extra = options.get("additional_opts", "")
    if not isinstance(extra, str): raise ValueError("pythia.additional_opts must contain Pythia setting lines")
    result = assignments(extra, strict=True)
    if "mpi" in options:
        value = options["mpi"]
        if not isinstance(value, str) or value.lower() not in ("on", "off"):
            raise ValueError("pythia.mpi must be the explicit string on or off")
        if "PartonLevel:MPI" in result and not equivalent(result["PartonLevel:MPI"], value):
            raise ValueError("pythia.mpi conflicts with additional_opts PartonLevel:MPI")
        result["PartonLevel:MPI"] = value.lower()
    return result


def _supported_setting(key, value):
    if key.lower() not in CANONICAL and not re.fullmatch(r"[1-9]\d*:mayDecay", key, re.I):
        raise ValueError(f"unsupported native shower setting {key}; register its translation or provide a validated explicit native shower_card")
    if key == "JetMatching:merge" and not equivalent(value, "off"):
        raise ValueError("native unmerged adapter cannot enable JetMatching:merge")
    equivalent(value, value)  # reject nonfinite numbers
    flags = {name for name in SETTING_NAMES if name.startswith(("PartonLevel:", "HadronLevel:"))}
    flags.update(("SLHA:useDecayTable", "SLHA:keepSM", "Random:setSeed", "Print:quiet",
                  "BeamRemnants:primordialKT", "ColourReconnection:reconnect", "JetMatching:merge"))
    if key in flags or key.lower().endswith(":maydecay"):
        if str(value).lower() not in ("on", "off", "true", "false", "1", "0"):
            raise ValueError(f"native shower flag {key} needs on/off or true/false")
    elif key not in ("Beams:LHEF", "PDF:pSet"):
        try: number = float(value)
        except ValueError as exc: raise ValueError(f"native shower setting {key} must be numeric") from exc
        integer = key.startswith(("Tune:", "Next:")) or key in (
            "SLHA:readFrom", "Random:seed", "SpaceShower:pTmaxMatch", "TimeShower:pTmaxMatch",
            "Beams:frameType", "Main:numberOfEvents")
        if not math.isfinite(number) or integer and not number.is_integer():
            raise ValueError(f"native shower setting {key} needs a finite {'integer' if integer else 'number'}")
        if key == "Random:seed" and not -1 <= number <= 900000000:
            raise ValueError("Random:seed is outside Pythia's supported -1..900000000 range")


def shower_seed(settings):
    """Require a fixed positive Pythia seed, rather than time/default seeding."""
    if not equivalent(settings.get("Random:setSeed", "off"), "on"):
        raise ValueError("Random:seed requires explicit Random:setSeed = on; otherwise Pythia ignores the requested seed")
    value = settings.get("Random:seed", "")
    if not re.fullmatch(r"\+?\d+", str(value)) or not 1 <= int(value) <= 900000000:
        raise ValueError("Random:seed must be a fixed integer in 1..900000000")
    return int(value)


def seeded_shower(settings, cfg):
    """Preserve explicit seeding, or add a disclosed deterministic baseline."""
    settings = dict(settings)
    dispositions = []
    if "Random:seed" not in settings:
        if "Random:setSeed" in settings and not equivalent(settings["Random:setSeed"], "on"):
            raise ValueError("Random:setSeed = off cannot provide a reproducible shower seed")
        seed = cfg.get("madgraph", {}).get("run", {}).get("seed", 1)
        if type(seed) is not int or not 0 <= seed <= 900000000:
            raise ValueError("shower seed source must be an integer in 0..900000000")
        settings.update({"Random:setSeed": "on", "Random:seed": str(seed or 1)})
        dispositions.append({"setting": "Random:seed", "value": seed or 1,
                             "disposition": "explicit_adapter_seed",
                             "reason": "positive generation seed reused; absent/automatic generation seed selects fixed shower seed 1"})
    return settings, shower_seed(settings), dispositions


def translate_shower(cfg, source, *, lhe, nevents):
    """Translate the mapyde/MG interface card for the unmerged native wrapper."""
    values = assignments(Path(source).read_text(), strict=True)
    translated, dispositions = {}, []
    for key, value in values.items():
        lower = key.lower()
        if lower in INTERFACE_SENTINELS:
            if not equivalent(value, INTERFACE_SENTINELS[lower]):
                raise ValueError(f"active or unsupported MadGraph-interface setting {key}={value}; native adapter supports unmerged LO only")
            dispositions.append({"setting": key, "requested": value, "disposition": "inactive_interface_control_removed",
                                 "reason": "MadGraph interface sentinel has no native-wrapper operation in unmerged LO"})
            continue
        _supported_setting(key, value)
        translated[key] = value
    extra = requested_shower(cfg)
    for key, value in extra.items():
        _supported_setting(key, value)
        if key in translated and not equivalent(translated[key], value):
            if key == "PartonLevel:MPI" and "mpi" in cfg.get("pythia", {}):
                dispositions.append({"setting": key, "source_value": translated[key], "requested": value,
                                     "disposition": "explicit_mpi_override", "reason": "mapyde pythia.mpi selects this override"})
            else:
                raise ValueError(f"shower option {key} conflicts with the selected source card; edit a source copy explicitly")
        translated[key] = value
    for key, value in ADAPTER_BASELINE.items():
        if key not in translated:
            translated[key] = value
            dispositions.append({"setting": key, "value": value, "disposition": "explicit_adapter_baseline",
                                 "reason": "native adapter baseline, not verified historical mapyde or ATLAS runtime"})
    translated, seed, seed_dispositions = seeded_shower(translated, cfg)
    dispositions.extend(seed_dispositions)
    for key, value in {"Beams:frameType": "4", "Main:numberOfEvents": str(nevents)}.items():
        if key in translated and not equivalent(translated[key], value) and not (
                key == "Main:numberOfEvents" and equivalent(translated[key], "-1")):
            raise ValueError(f"source/extra shower setting {key} conflicts with native input/event count")
        if key in translated and not equivalent(translated[key], value):
            dispositions.append({"setting": key, "requested": translated[key], "effective": value,
                                 "disposition": "native_wrapper_event_count", "reason": "the native wrapper takes the approved event count"})
        translated[key] = value
    if "Beams:LHEF" in extra: raise ValueError("Beams:LHEF is managed by native preparation; do not override it")
    if "Beams:LHEF" in translated:
        dispositions.append({"setting": "Beams:LHEF", "source_value": translated["Beams:LHEF"], "effective": str(lhe),
                             "disposition": "native_generated_input_binding", "reason": "consume this plan's generated LHE"})
    translated["Beams:LHEF"] = str(lhe)
    translated.setdefault("Print:quiet", "on")
    text = "! Translated unmerged native card. See native_effective_settings.json for dispositions.\n"
    # Reading a tune applies many dependent settings. Put tunes first so the
    # later explicit alphaS/MPI/response controls actually override that tune.
    ordered = sorted(translated, key=lambda key: (not key.startswith("Tune:"), key))
    text += "".join(f"{key} = {translated[key]}\n" for key in ordered)
    return text, {"source": fingerprint(source), "requested_overlays": extra, "dispositions": dispositions, "seed": seed}


def explicit_shower_controls(cfg, source):
    """Keep explicit-card semantics; reject a requested overlay that would be lost."""
    actual = assignments(Path(source).read_text())
    for key, value in actual.items():
        if key.lower() in INTERFACE_SENTINELS:
            raise ValueError(f"explicit native shower_card contains MadGraph-interface setting {key}; translate it through slepton preparation or supply a native Pythia card")
    for key, value in requested_shower(cfg).items():
        if key not in actual or not equivalent(actual[key], value):
            raise ValueError(f"requested shower setting {key} is absent/different in explicit shower_card; edit a copy of that card")
    _, seed, dispositions = seeded_shower(actual, cfg)
    return {"source": fingerprint(source), "requested_overlays": requested_shower(cfg), "dispositions": dispositions, "seed": seed,
            "selection": "explicit native shower_card is authoritative; no mapyde card translation"}


def expected_cards(plan):
    from .native_pipeline import output_root
    out = output_root(plan)
    legacy = plan["capability"]["preparation"] == "slepton-bino"
    result = {name: plan["rendered"][name] if legacy else Path(plan["inputs"][name.removesuffix(".dat")]).read_text()
              for name in ("param_card.dat", "run_card.dat")}
    shower = plan["rendered"]["shower.cfg"] if legacy else Path(plan["inputs"]["shower_card"]).read_text()
    # Case-insensitive input spelling is accepted by Pythia. Preserve all other
    # explicit card bytes while changing only its single managed input line.
    shower, count = re.subn(r"(?im)^\s*Beams:LHEF\s*=.*$", lambda _: f"Beams:LHEF = {out/'madgraph/unweighted_events.lhe'}", shower)
    if count != 1: raise ValueError("prepared shower needs exactly one managed Beams:LHEF assignment")
    settings = assignments(shower, strict=True)
    if "Random:seed" not in settings:
        if "Random:setSeed" not in settings:
            shower = shower.rstrip()+"\nRandom:setSeed = on\n"
        shower = shower.rstrip()+f"\nRandom:seed = {plan['shower_translation']['seed']}\n"
    if shower_seed(assignments(shower)) != plan["shower_translation"]["seed"]:
        raise ValueError("prepared shower seed differs from planned seed")
    result["shower.cfg"] = shower
    process = Path(plan["inputs"]["process_card"]).read_text().rstrip()
    result["run.mg5"] = f"{process}\noutput PROC_madgraph\nlaunch PROC_madgraph\nmadspin=OFF\nshower=OFF\nreweight=OFF\ndone\n{out/'param_card.dat'}\n{out/'run_card.dat'}\ndone\n"
    from .prepare_native_slepton import rendered_launch_card
    result["run.mg5"] = rendered_launch_card(plan, result["run.mg5"])
    return result


def _snapshot(plan):
    from .native_pipeline import output_root
    out = output_root(plan)
    expected = expected_cards(plan)
    cards = {}
    for name, text in expected.items():
        path = out/name
        if path.read_bytes() != text.encode(): raise ValueError(f"prepared effective card differs from requested plan: {name}")
        cards[name] = fingerprint(path)
    cards["delphes_card"] = fingerprint(plan["inputs"]["delphes_card"])
    if cards["delphes_card"] not in plan["sources"]:
        raise ValueError("effective detector card differs from its declared source identity")
    run = assignments((out/"run_card.dat").read_text(), run=True)
    shower = assignments((out/"shower.cfg").read_text())
    process = [line.split("#", 1)[0].strip() for line in Path(plan["inputs"]["process_card"]).read_text().splitlines()]
    from .native_pipeline import validate_process_card
    from ravel.validation.lhe_check import parse_param_card
    produced = validate_process_card(plan["inputs"]["process_card"], plan["capability"]["model"])
    actual_masses, mass_lint = parse_param_card(str(out/"param_card.dat"))
    mass_errors = [message for level, message in mass_lint if level == "FAIL"]
    if mass_errors: raise ValueError("; ".join(mass_errors))
    controls = plan["effective_controls"]
    checks = []
    for pdg, mass in plan["expected_masses_gev"].items():
        actual = actual_masses.get(int(pdg))
        if actual is None or not math.isclose(float(actual), float(mass), rel_tol=1e-10, abs_tol=1e-10):
            raise ValueError(f"requested mass {pdg} differs from effective parameter card")
        checks.append({"domain": "mass", "setting": pdg, "requested": mass, "effective": actual, "status": "match"})
    for key, value in controls["generation"].items():
        if key not in run or not equivalent(run[key], value): raise ValueError(f"requested generation control {key} differs from effective run card")
        checks.append({"domain": "generation", "setting": key, "requested": value, "effective": run[key], "status": "match"})
    for key, value in plan["shower_translation"]["requested_overlays"].items():
        if key not in shower or not equivalent(shower[key], value): raise ValueError(f"requested shower control {key} differs from effective shower card")
        checks.append({"domain": "shower", "setting": key, "requested": value, "effective": shower[key], "status": "match"})
    commands = {s["stage"]: {"command": s["command"], "inputs": s["inputs"]} for s in plan["stages"] if s["stage"] != "prepare"}
    return {"schema_version": 1, "generated_by": "native_effective_config.py", "plan_sha256": plan["plan_sha256"],
            "cards": cards, "source_identities": plan["sources"], "requested_controls": controls,
            "effective": {"generation": run, "shower": shower, "process_commands": [x for x in process if x],
                          "model": plan["capability"]["model"],
                          "mass_parameters_gev": {str(pdg): mass for pdg, mass in actual_masses.items()},
                          "produced_masses_gev": {str(pdg): actual_masses[pdg] for pdg in produced},
                          "produced_parent_pdgs": sorted(produced),
                          "detector_card": cards["delphes_card"], "statistics": controls["statistics"]},
            "comparison": checks, "shower_translation": plan["shower_translation"], "stage_bindings": commands,
            "runtime_consumption": "UNVERIFIED: prepared cards and planned commands are not execution receipts",
            "limitations": ["Declared container/tool version labels do not select or authenticate native runtime versions",
                            "Settings agreement is not physics or detector certification"]}


def emit(plan):
    record = _snapshot(plan)
    atomic_json(Path(plan["effective_settings"]), record)
    return record


def validate(plan, record=None):
    try:
        if "effective_settings" not in plan:
            raise ValueError("historical plan predates effective-settings custody; runtime consumption remains unverified")
        from .native_pipeline import plan_hash
        if plan_hash(plan) != plan.get("plan_sha256"):
            raise ValueError("effective-settings execution plan changed")
        for source in plan["sources"]:
            if fingerprint(source["path"]) != source: raise ValueError(f"effective-settings source changed: {source['path']}")
        record = read_json(Path(plan["effective_settings"])) if record is None else record
        if record != _snapshot(plan): raise ValueError("effective-settings manifest differs from current cards, controls or plan")
        return []
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]


def runtime_evidence(plan):
    """Report receipt custody separately; never promote card existence to consumption."""
    from ravel.workflow.execution import load_execution, stage_errors
    try: state = load_execution(plan["rundir"])
    except (OSError, ValueError) as exc: return {"status": "unverified", "reason": str(exc), "stages": []}
    output = []
    for item in plan["stages"]:
        if item["stage"] not in ("madgraph", "pythia", "normalization", "delphes", "analysis", "simpleanalysis", "sa2json", "pyhf"): continue
        record = state["stages"].get(item["stage"])
        if record is None:
            output.append({"stage": item["stage"], "status": "unverified", "reason": "no execution receipt"}); continue
        errors = stage_errors(plan["rundir"], item["stage"], state)
        def resolved(paths):
            return {str((Path(plan["rundir"])/path).resolve()) for path in paths}
        # The supervisor adds executable and package identities to inputs.
        # All planned inputs must be present; stage_errors verifies the full
        # expanded snapshot and transitive successful receipt chain.
        if record.get("command") != item["command"] or not resolved(item["inputs"]) <= resolved(record.get("inputs", [])):
            errors.append("receipt command/input declarations differ from the effective-settings plan")
        output.append({"stage": item["stage"], "status": "invalid" if errors else "receipt_verified",
                       "receipt_sha256": record.get("receipt_sha256"), "errors": errors})
    return {"status": "receipt_verified" if output and all(x["status"] == "receipt_verified" for x in output) else "unverified",
            "scope": "Matching successful command/input/output receipts; not independent observation of internal tool settings",
            "stages": output}
