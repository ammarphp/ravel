"""Compare declared physics with the MadGraph cards that actually ran.

The physics intent is a structured declaration: processes and charge-conjugate
scope, coupling orders, masses, widths, active parameters, PDF, collision
energy, fiducial selection, virtuality windows and particles left undecayed for
the shower. The simulation side is read from the proc, run and parameter cards
(before launch from the staged inputs, after the run from the LHE banner).

Every invariant is deterministic. A mismatch is a violation and blocks the run;
a check that the cards cannot decide is listed as unknown.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys

ORDER = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)(\^2)?\s*(==|<=|>=|=|<|>)\s*(-?\d+)")
FIDUCIAL_KEYS = {"lepton": ("ptl", "etal"), "jet": ("ptj", "etaj"), "photon": ("pta", "etaa"), "b": ("ptb", "etab")}
GENERATOR_CUTS = ("ptl", "ptj", "pta", "ptb", "mmll", "mmjj", "drll", "drjj", "draa", "drjl")
INTENT_KEYS = ("processes", "conjugates", "orders", "masses_gev", "widths", "active_parameters", "bsm_blocks",
               "accept_model_defaults", "pdf", "sqrt_s_gev", "fiducial", "virtuality_windows_gev",
               "undecayed_unstable", "max_width_over_mass")
REL = 1e-9


def validate_intent(intent):
    errors = []
    if type(intent) is not dict or not intent:
        return ["physics intent must be a nonempty object"]
    errors += [f"unknown physics-intent field: {k}" for k in sorted(set(intent) - set(INTENT_KEYS))]
    if "processes" in intent and (type(intent["processes"]) is not list or not intent["processes"]
                                  or any(type(p) is not str or ">" not in p for p in intent["processes"])):
        errors.append("processes must list MadGraph process strings")
    if intent.get("conjugates", "inclusive") not in ("inclusive", "as_written"):
        errors.append("conjugates must be inclusive or as_written")
    if "orders" in intent:
        orders = intent["orders"]
        if type(orders) is not dict or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\^2)?", k) or type(v) is not str
                                           or not re.fullmatch(r"(==|<=|>=|<|>)\d+", v.replace(" ", ""))
                                           for k, v in orders.items()):
            errors.append("orders map names such as QCD or NP^2 to '<=N', '==N' or '>=N'")
    for key in ("masses_gev",):
        for pdg, value in intent.get(key, {}).items():
            if not re.fullmatch(r"-?\d+", str(pdg)) or type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                errors.append(f"{key}[{pdg}] must be a finite non-negative number")
    for pdg, row in intent.get("widths", {}).items():
        if type(row) is not dict or row.get("mode") not in ("auto", "fixed") or (
                row["mode"] == "fixed" and (type(row.get("value_gev")) not in (int, float) or row["value_gev"] < 0)):
            errors.append(f"widths[{pdg}] must be {{'mode': 'auto'}} or {{'mode': 'fixed', 'value_gev': x}}")
    for row in intent.get("active_parameters", []):
        if (type(row) is not dict or set(row) != {"block", "code", "value"} or type(row["block"]) is not str
                or type(row["code"]) is not list or type(row["value"]) not in (int, float)):
            errors.append("active_parameters rows need block, code (list of integers) and value")
    if type(intent.get("accept_model_defaults", False)) is not bool:
        errors.append("accept_model_defaults must be true or false")
    if "pdf" in intent and (type(intent["pdf"]) is not dict or type(intent["pdf"].get("lhaid")) is not int):
        errors.append("pdf needs an integer lhaid")
    for cls, row in intent.get("fiducial", {}).items():
        if cls == "mll_min_gev":
            continue
        if cls not in FIDUCIAL_KEYS or type(row) is not dict or set(row) - {"pt_min_gev", "abs_eta_max"}:
            errors.append(f"fiducial.{cls}: classes are {sorted(FIDUCIAL_KEYS)} with pt_min_gev/abs_eta_max")
    for pdg, window in intent.get("virtuality_windows_gev", {}).items():
        if type(window) is not list or len(window) != 2 or not window[0] < window[1]:
            errors.append(f"virtuality_windows_gev[{pdg}] must be [low, high]")
    return errors


def parse_slha(text):
    """Blocks and decay tables of an SLHA card; values keep 'auto' for Auto widths."""
    blocks, decays, current = {}, {}, None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        head = fields[0].lower()
        if head == "block":
            current = ("block", fields[1].upper())
            blocks.setdefault(fields[1].upper(), {})
        elif head == "decay":
            width = fields[2] if len(fields) > 2 else "auto"
            decays[int(fields[1])] = {"width": "auto" if width.lower() == "auto" else _float(width), "channels": []}
            current = ("decay", int(fields[1]))
        elif current and current[0] == "block":
            *codes, value = fields
            blocks[current[1]][tuple(int(c) for c in codes)] = "auto" if value.lower() == "auto" else _float(value)
        elif current and current[0] == "decay":
            decays[current[1]]["channels"].append((_float(fields[0]), [int(x) for x in fields[2:]]))
    return {"blocks": blocks, "decays": decays}


def _float(token):
    value = float(token.replace("D", "e").replace("d", "e"))
    if not math.isfinite(value):
        raise ValueError("nonfinite card value")
    return value


def process_lines(proc_lines):
    """Definitions and generate/add process lines of an MG5 process card."""
    definitions, processes, model = {}, [], None
    for raw in proc_lines:
        line = " ".join(raw.split("#", 1)[0].split())
        if line.startswith("define "):
            name, value = line[len("define "):].split("=", 1)
            definitions[name.strip()] = value.split()
        elif line.startswith("generate "):
            processes.append(line[len("generate "):])
        elif line.startswith("add process "):
            processes.append(line[len("add process "):])
        elif line.startswith("import model "):
            model = line[len("import model "):]
    return {"definitions": definitions, "processes": processes, "model": model}


def split_process(text):
    """(initial labels, final labels, orders, decay-chain flag) of one MG process line."""
    text = re.sub(r"@\s*\d+", "", text)
    text = re.sub(r"\[.*?\]", "", text)
    chain = "," in text
    core = text.split(",", 1)[0]
    orders = {}
    for name, squared, op, value in ORDER.findall(core):
        op = "<=" if op == "=" else op
        orders[name + (squared or "")] = op + value
    core = ORDER.sub("", core)
    core = re.sub(r"\$\$?\s*\S+|/\s*\S+", "", core)
    parts = [p.split() for p in core.split(">")]
    return parts[0], [x for p in parts[1:] for x in p], orders, chain


def conjugate_name(name):
    swaps = {"+": "-", "-": "+"}
    if name.endswith("~"):
        return name[:-1]
    if name[-1] in swaps:
        return name[:-1] + swaps[name[-1]]
    return name + "~"


def _expand(label, definitions):
    return frozenset(definitions.get(label, [label]))


def _conjugate_set(names, self_conjugate):
    return frozenset(n if n in self_conjugate else conjugate_name(n) for n in names)


# Self-conjugate SM states and the MadGraph default multiparticles p and j (charge-symmetric sets).
SELF_CONJUGATE = {"g", "a", "z", "h", "p", "j"}


def simulation_from_cards(proc_lines, run_settings, param_text=None):
    sim = process_lines(proc_lines)
    sim["run"] = dict(run_settings)
    sim["param"] = parse_slha(param_text) if param_text else None
    return sim


def reconcile(intent, sim, *, stage):
    errors = validate_intent(intent)
    if errors:
        raise ValueError("invalid physics intent: " + "; ".join(errors))
    violations, unknowns, checks, flags = [], [], [], []
    run, param, definitions = sim["run"], sim["param"], sim["definitions"]
    parsed = [split_process(p) for p in sim["processes"]]

    def check(name, ok, detail):
        checks.append({"check": name, "status": "satisfied" if ok else "violated", "detail": detail})
        if not ok:
            violations.append(f"{name}: {detail}")

    def unknown(name, detail):
        checks.append({"check": name, "status": "unknown", "detail": detail})
        unknowns.append(f"{name}: {detail}")

    if "processes" in intent:
        declared = sorted(" ".join(p.split()) for p in intent["processes"])
        actual = sorted(" ".join(re.sub(r"@\s*\d+", "", p).split()) for p in sim["processes"])
        check("process", declared == actual, f"declared {declared}, cards {actual}")
    if intent.get("conjugates", "inclusive") == "inclusive" and parsed:
        if any(chain for *_, chain in parsed):
            unknown("charge conjugates", "decay-chain syntax; conjugate coverage is not decided from the cards")
        else:
            def signature(labels, conjugate=False):
                sets = [_expand(x, definitions) for x in labels]
                if conjugate:
                    sets = [_conjugate_set(x, SELF_CONJUGATE) for x in sets]
                return tuple(sorted(tuple(sorted(x)) for x in sets))
            present = {(signature(i), signature(f)) for i, f, _, _ in parsed}
            missing = [" ".join(i) + " > " + " ".join(f) for i, f, _, _ in parsed
                       if (signature(i, True), signature(f, True)) not in present]
            check("charge conjugates", not missing,
                  "inclusive intent: conjugate process absent for " + ", ".join(missing) if missing else "conjugates covered")
    if "orders" in intent:
        want = {k: v.replace(" ", "") for k, v in intent["orders"].items()}
        for line, (_, _, orders, _) in zip(sim["processes"], parsed):
            check("coupling orders", orders == want, f"'{line}' has {orders}, declared {want}")
    if "pdf" in intent:
        check("PDF set", run.get("lhaid") == intent["pdf"]["lhaid"],
              f"run card lhaid {run.get('lhaid')!r}, declared {intent['pdf']['lhaid']}")
    if "sqrt_s_gev" in intent:
        e1, e2 = run.get("ebeam1"), run.get("ebeam2")
        if e1 is None or e2 is None:
            unknown("collision energy", "beam energies absent from the run card")
        else:
            value = 2 * math.sqrt(e1 * e2)
            check("collision energy", math.isclose(value, intent["sqrt_s_gev"], rel_tol=1e-6),
                  f"2*sqrt(ebeam1*ebeam2) = {value:g} GeV, declared {intent['sqrt_s_gev']:g} GeV")
    fiducial = intent.get("fiducial", {})
    for cls, (pt_key, eta_key) in FIDUCIAL_KEYS.items():
        row = fiducial.get(cls)
        for key, declared, looser in ((pt_key, (row or {}).get("pt_min_gev"), lambda g, f: g <= f),
                                      (eta_key, (row or {}).get("abs_eta_max"), lambda g, f: g <= 0 or g >= f)):
            if key not in run:
                if declared is not None:
                    unknown(f"generator cut {key}", "absent from the run card")
                continue
            if declared is None:
                if key.startswith("pt") and run[key] > 0:
                    unknown(f"generator cut {key}", f"{key}={run[key]} has no declared fiducial counterpart")
                continue
            check(f"generator cut {key}", looser(run[key], declared),
                  f"{key}={run[key]} must be looser than the fiducial {declared}")
    if "mll_min_gev" in fiducial:
        if "mmll" in run:
            check("generator cut mmll", run["mmll"] <= fiducial["mll_min_gev"],
                  f"mmll={run['mmll']} must not exceed the fiducial {fiducial['mll_min_gev']}")
        else:
            unknown("generator cut mmll", "absent from the run card")
    if param is None:
        if any(k in intent for k in ("masses_gev", "widths", "active_parameters", "bsm_blocks",
                                     "virtuality_windows_gev", "undecayed_unstable")):
            unknown("parameter card", "no parameter card available at this stage; mass, width and coupling checks wait for the banner")
    else:
        masses = param["blocks"].get("MASS", {})
        decays = param["decays"]
        for pdg, value in intent.get("masses_gev", {}).items():
            card = masses.get((int(pdg),))
            check(f"mass {pdg}", card is not None and card != "auto" and math.isclose(card, value, rel_tol=REL, abs_tol=1e-12),
                  f"card {card!r}, declared {value}")
        for pdg, row in intent.get("widths", {}).items():
            card = decays.get(int(pdg), {}).get("width")
            if row["mode"] == "fixed":
                check(f"width {pdg}", card not in (None, "auto") and math.isclose(card, row["value_gev"], rel_tol=REL, abs_tol=1e-15),
                      f"card {card!r}, declared fixed {row['value_gev']}")
            elif stage == "pre-launch":
                check(f"width {pdg}", card == "auto", f"card {card!r}, declared Auto (computed at this point)")
            else:
                check(f"width {pdg}", card == "auto" or (card is not None and card > 0),
                      f"card {card!r}, declared Auto")
        for pdg in intent.get("masses_gev", {}):
            if pdg not in intent.get("widths", {}):
                card = decays.get(int(pdg), {}).get("width")
                if card not in (None, 0, 0.0):
                    check(f"width {pdg} declared", False,
                          f"mass is declared but the width ({card!r}) is not; declare Auto or the fixed width at this mass")
        threshold = intent.get("max_width_over_mass")
        for pdg, row in decays.items():
            mass = masses.get((abs(pdg),))
            if threshold and row["width"] not in ("auto", 0, 0.0) and mass not in (None, "auto", 0, 0.0):
                if row["width"] / abs(mass) > threshold:
                    flags.append(f"PDG {pdg}: width/mass = {row['width'] / abs(mass):.3g} exceeds {threshold}")
        active = {(r["block"].upper(), tuple(r["code"])): r["value"] for r in intent.get("active_parameters", [])}
        for (block, code), value in active.items():
            card = param["blocks"].get(block, {}).get(code)
            check(f"parameter {block} {list(code)}", card is not None and card != "auto"
                  and math.isclose(card, value, rel_tol=REL, abs_tol=1e-15), f"card {card!r}, declared {value}")
        if not intent.get("accept_model_defaults", False):
            for block in intent.get("bsm_blocks", []):
                rows = param["blocks"].get(block.upper())
                if rows is None:
                    check(f"block {block}", False, "declared BSM block absent from the card")
                    continue
                stray = [list(code) for code, value in rows.items()
                         if (block.upper(), code) not in active and value not in (0, 0.0)]
                check(f"undeclared couplings in {block}", not stray,
                      f"nonzero entries {stray} are not declared active (set them to zero or declare them)")
        bw = run.get("bwcutoff")
        for pdg, (low, high) in intent.get("virtuality_windows_gev", {}).items():
            mass, width = masses.get((int(pdg),)), decays.get(int(pdg), {}).get("width")
            if bw is None or mass in (None, "auto") or width in (None, "auto"):
                unknown(f"bwcutoff {pdg}", "bwcutoff, mass or numeric width unavailable at this stage")
                continue
            lo, hi = mass - bw * width, mass + bw * width
            check(f"bwcutoff {pdg}", lo <= low and hi >= high,
                  f"m +- bwcutoff*width = [{lo:g}, {hi:g}] GeV must cover the declared window [{low:g}, {high:g}]")
        for pdg in intent.get("undecayed_unstable", []):
            row = decays.get(int(pdg))
            ok = row is not None and row["width"] not in (0, 0.0) and bool(row["channels"])
            if row is not None and row["width"] == "auto" and stage == "pre-launch":
                unknown(f"decay table {pdg}", "Auto width; branching ratios are written by the generator")
                continue
            check(f"decay table {pdg}", ok, "a particle left undecayed for the shower needs a width and branching-ratio rows")
    return {"schema_version": 1, "kind": "spec_reconciliation", "stage": stage,
            "satisfied": not violations, "violations": violations, "unknowns": unknowns,
            "flags": flags, "checks": checks}


def intent_for(generation, overrides=()):
    """The intent a scoped generation declares: its process and PDF, the optional
    physics_intent, and one parameter point's card overrides (masses, widths and
    other parameters become declared values for that point)."""
    from copy import deepcopy
    intent = deepcopy(generation.get("physics_intent", {}))
    intent.setdefault("processes", [generation["process"]])
    intent.setdefault("conjugates", "as_written")
    if "lhaid" in generation["run_settings"]:
        intent.setdefault("pdf", {"lhaid": generation["run_settings"]["lhaid"]})
    for o in overrides:
        block, code = o["block"].upper(), [int(c) for c in o["code"]]
        if block == "MASS":
            intent.setdefault("masses_gev", {})[str(code[0])] = o["value"]
        elif block == "DECAY":
            intent.setdefault("widths", {})[str(code[0])] = (
                {"mode": "auto"} if o["value"] == "Auto" else {"mode": "fixed", "value_gev": o["value"]})
        else:
            rows = [r for r in intent.get("active_parameters", [])
                    if not (r["block"].upper() == block and list(r["code"]) == code)]
            intent["active_parameters"] = rows + [{"block": block, "code": code, "value": o["value"]}]
    return intent


def apply_overrides(param, overrides):
    """A parsed parameter card with one point's overrides applied (pre-launch view)."""
    from copy import deepcopy
    card = deepcopy(param)
    for o in overrides:
        block, code = o["block"].upper(), tuple(int(c) for c in o["code"])
        value = "auto" if o["value"] == "Auto" else o["value"]
        if block == "DECAY":
            card["decays"].setdefault(code[0], {"width": value, "channels": []})["width"] = value
            if value == "auto":
                card["decays"][code[0]]["channels"] = []
        else:
            card["blocks"].setdefault(block, {})[code] = value
    return card


# Science-mode protocol: task {"intent", "proc_card", "run_card", "param_card"} (paths).

def validate(task):
    if type(task) is not dict or set(task) - {"intent", "proc_card", "run_card", "param_card"} or not {
            "intent", "proc_card", "run_card"} <= set(task):
        raise ValueError("generation-reconciliation task needs intent, proc_card and run_card (param_card optional)")
    return dict(task)


def _path(value, base):
    p = Path(value)
    p = p if p.is_absolute() else Path(base) / p
    if p.is_symlink() or not p.is_file():
        raise ValueError(f"regular file required: {p}")
    return p.resolve()


def inputs(task, base):
    validate(task)
    return [_path(task[k], base) for k in ("intent", "proc_card", "run_card", "param_card") if k in task]


def execution_seconds(task, base):
    return 30


def _from_task(task, base):
    from ravel.physics.scoped import run_card
    from ravel.workflow.state_io import read_json
    intent = read_json(_path(task["intent"], base))
    sim = simulation_from_cards(_path(task["proc_card"], base).read_text().splitlines(),
                                run_card(_path(task["run_card"], base).read_text()),
                                _path(task["param_card"], base).read_text() if "param_card" in task else None)
    return intent, sim


def run(task, base, output):
    validate(task)
    intent, sim = _from_task(task, base)
    record = reconcile(intent, sim, stage="post-run")
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    result = {**record, "status": "passed" if record["satisfied"] else "failed", "physics_validated": False}
    with (out / "spec-reconciliation.json").open("x") as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
    if not record["satisfied"]:
        raise ValueError("physics intent and simulation cards disagree: " + "; ".join(record["violations"]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ravel spec-reconcile",
                                     description="Compare a physics-intent declaration with MadGraph cards (read only).")
    parser.add_argument("--intent", required=True, type=Path)
    parser.add_argument("--proc-card", required=True, type=Path)
    parser.add_argument("--run-card", required=True, type=Path)
    parser.add_argument("--param-card", type=Path)
    parser.add_argument("--stage", choices=("pre-launch", "post-run"), default="post-run")
    args = parser.parse_args(argv)
    task = {"intent": str(args.intent), "proc_card": str(args.proc_card), "run_card": str(args.run_card)}
    if args.param_card:
        task["param_card"] = str(args.param_card)
    intent, sim = _from_task(task, Path.cwd())
    record = reconcile(intent, sim, stage=args.stage)
    print(json.dumps(record, indent=2))
    return 0 if record["satisfied"] else 1


if __name__ == "__main__":
    sys.exit(main())
