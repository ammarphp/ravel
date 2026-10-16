"""Small complete supplied-event studies for repair evaluation, never physics runs.

The implementation uses the ordinary normalization ledger and stat-only limit
helper. The reference reconstructs the declared rules separately, with decimal
weight arithmetic and a bisection of the declared likelihood equation. It does
not call the implementation or use an injected-fault label.
"""
from copy import deepcopy
from decimal import Decimal
import math
from statistics import NormalDist

from ravel.physics import normalization_ledger as nl
from ravel.validation.residual_decomposition import sr_asimov_mu95


STAGES = ("cards", "selections", "normalization", "templates", "inference")
TESTS = {
    "cards": "compare_declared_card",
    "selections": "replay_threshold_equality",
    "normalization": "recompute_signed_weight_units",
    "templates": "compare_bin_and_control_census",
    "inference": "solve_declared_likelihood",
}


def study():
    """A fixed finite software control, with a prescribed known-background law."""
    return {
        "schema_version": 1,
        "events": [
            {"id": f"e{i}", "x": x, "weight": w, "region": r}
            for i, (x, w, r) in enumerate([
                (19., 2., "signal"), (20., 1., "signal"), (25., -.25, "signal"),
                (35., 3., "signal"), (45., 1., "signal"), (55., -.5, "signal"),
                (65., 2., "control"), (75., 1., "control"),
            ])
        ],
        "rules": {
            "cards": {"cross_section": 2., "unit": "fb", "luminosity_fb": 3., "factor": 1.25},
            "selections": {"threshold": 20., "inclusive": True},
            "normalization": {"factor_power": 1, "unit_multiplier": 1.},
            "templates": {"signal_order": [0, 1], "control_scale": 1.},
            "inference": {"include_control": True, "result_scale": 1.},
        },
        "bin_edges": [20., 40., 80.],
        "background": {"signal": [6., 1.], "control": [10.]},
        "quantity": {"id": "median_expected_mu95", "unit": "1", "level": .05,
                     "definition": "Known-background independent Poisson channels; background-only expected data; asymptotic CLs."},
        "scope": "Finite synthetic software study; no physical accuracy or statistical coverage claim.",
    }


# Exactly one implementation setting differs from the matched correct control.
FAULTS = (
    {"id": "card_rate", "class": "cards", "stage": "cards", "key": "cross_section", "value": 4.},
    {"id": "selection_equality", "class": "selections", "stage": "selections", "key": "inclusive", "value": False},
    {"id": "factor_missing", "class": "normalization", "stage": "normalization", "key": "factor_power", "value": 0},
    {"id": "factor_doubled", "class": "normalization", "stage": "normalization", "key": "factor_power", "value": 2},
    {"id": "unit_conversion", "class": "normalization", "stage": "normalization", "key": "unit_multiplier", "value": 1000.},
    {"id": "wrong_bin", "class": "templates", "stage": "templates", "key": "signal_order", "value": [1, 0]},
    {"id": "stale_control", "class": "templates", "stage": "templates", "key": "control_scale", "value": .8},
    {"id": "inference_channel", "class": "inference", "stage": "inference", "key": "include_control", "value": False},
    {"id": "inference_scale", "class": "inference", "stage": "inference", "key": "result_scale", "value": .5},
)


def inject(document, fault_id):
    fault = next((f for f in FAULTS if f["id"] == fault_id), None)
    if fault is None:
        raise ValueError("unknown synthetic fault")
    configuration = deepcopy(document["rules"])
    configuration[fault["stage"]][fault["key"]] = deepcopy(fault["value"])
    return configuration


def ledger(document, card, selected):
    basis = {"final_states": ["synthetic"], "multiplicities": {},
             "generation_cuts": {}, "pdf": "synthetic", "scales": "fixed"}
    weights = [e["weight"] for e in document["events"]]
    return {
        "schema_version": 1, "sample": "finite-signed-control",
        "luminosity": {"value": card["luminosity_fb"], "unit": "fb^-1", "source": "supplied control"},
        "sigma": {"value": card["cross_section"], "unit": card["unit"], "order": "LO",
                  "tool": "synthetic", "pdf": "synthetic", "scales": "fixed",
                  "process_basis": "synthetic", "source": "supplied control"},
        "k": {"value": card["factor"], "applied_once": True,
              "numerator_basis": {**basis, "order": "NLO"},
              "denominator_basis": {**basis, "order": "LO"}},
        "generated": {"sumw": math.fsum(weights), "sumw2": math.fsum(w*w for w in weights),
                      "n_events": len(weights), "negative_fraction": sum(w < 0 for w in weights) / len(weights)},
        "selected": deepcopy(selected["moments"]), "bin_convention": "per-bin",
    }


def execute_stage(stage, parameters, previous, document):
    """Closed synthetic stage operations; no command, source execution or IO."""
    if stage == "cards":
        return {"card": deepcopy(parameters), "events": deepcopy(document["events"])}
    if stage == "selections":
        bins = {"signal": [[], []], "control": [[]]}
        members = {"signal": [[], []], "control": [[]]}
        for event in previous["events"]:
            accepted = (event["x"] >= parameters["threshold"] if parameters["inclusive"]
                        else event["x"] > parameters["threshold"])
            if not accepted:
                continue
            region = event["region"]
            index = 0 if region == "control" or event["x"] < document["bin_edges"][1] else 1
            bins[region][index].append(event["weight"])
            members[region][index].append(event["id"])
        return {"card": deepcopy(previous["card"]), "members": members,
                "moments": {r: {"sumw": [math.fsum(v) for v in groups],
                                "sumw2": [math.fsum(w*w for w in v) for v in groups]}
                            for r, groups in bins.items()}}
    if stage == "normalization":
        book = ledger(document, previous["card"], previous)
        scale = nl.scale(book) * previous["card"]["factor"] ** (parameters["factor_power"] - 1)
        scale *= parameters["unit_multiplier"]
        yields = {r: [v*scale for v in row["sumw"]] for r, row in previous["moments"].items()}
        return {"yields": yields, "scale": scale, "ledger_check": nl.check(book, delivered=yields)}
    if stage == "templates":
        signal = previous["yields"]["signal"]
        return {"signal": [signal[i] for i in parameters["signal_order"]],
                "control": [v*parameters["control_scale"] for v in previous["yields"]["control"]],
                "background": deepcopy(document["background"])}
    if stage == "inference":
        regions = ("signal", "control") if parameters["include_control"] else ("signal",)
        signal = [x for r in regions for x in previous[r]]
        background = [x for r in regions for x in previous["background"][r]]
        value = sr_asimov_mu95(signal, background)
        if value is None:
            raise ValueError("synthetic likelihood has no positive sensitivity")
        return {"quantity": document["quantity"]["id"], "unit": "1",
                "value": value * parameters["result_scale"], "channels": list(regions)}
    raise ValueError("unknown synthetic stage")


def reference(document):
    """Reconstruct source rules, independently of execute_stage and its settings."""
    d = lambda x: Decimal(str(x))
    card = deepcopy(document["rules"]["cards"])
    rule = document["rules"]["selections"]
    populations = {"signal": [[], []], "control": [[]]}
    for event in document["events"]:
        x = d(event["x"])
        if x < d(rule["threshold"]) or (x == d(rule["threshold"]) and not rule["inclusive"]):
            continue
        region = event["region"]
        index = 0 if region == "control" else int(x >= d(document["bin_edges"][1]))
        populations[region][index].append(event)
    moments = {r: {"sumw": [float(sum((d(e["weight"]) for e in group), Decimal(0))) for group in groups],
                   "sumw2": [float(sum((d(e["weight"])**2 for e in group), Decimal(0))) for group in groups]}
               for r, groups in populations.items()}
    denominator = sum((d(e["weight"]) for e in document["events"]), Decimal(0))
    unit = {"fb": Decimal(1), "pb": Decimal(1000)}[card["unit"]]
    scale = d(card["cross_section"]) * unit * d(card["luminosity_fb"]) * d(card["factor"]) / denominator
    yields = {r: [float(scale*d(w)) for w in row["sumw"]] for r, row in moments.items()}
    signal = yields["signal"] + yields["control"]
    background = document["background"]["signal"] + document["background"]["control"]
    target = NormalDist().inv_cdf(1-document["quantity"]["level"]/2)**2
    def q(mu):
        return sum(2*(mu*s-b*math.log(1+mu*s/b)) for s, b in zip(signal, background))
    low, high = 0., 1.
    for _ in range(64):
        if q(high) >= target:
            break
        high *= 2
    else:
        raise ValueError("reference root not bracketed")
    for _ in range(100):
        middle = (low+high)/2
        if q(middle) < target:
            low = middle
        else:
            high = middle
    return {
        "cards": {"card": card, "events": deepcopy(document["events"])},
        "selections": {"card": card, "moments": moments,
                       "members": {r: [[e["id"] for e in group] for group in groups] for r, groups in populations.items()}},
        "normalization": {"yields": yields, "scale": float(scale)},
        "templates": {**yields, "background": deepcopy(document["background"])},
        "inference": {"quantity": document["quantity"]["id"], "unit": "1", "value": (low+high)/2,
                      "channels": ["signal", "control"]},
    }


def equivalent(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-12)
    if type(left) is dict and type(right) is dict:
        return set(left) == set(right) and all(equivalent(left[k], right[k]) for k in left)
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def comparisons(document, artifacts):
    expected = reference(document)
    result = []
    for stage in STAGES:
        observed = deepcopy(artifacts[stage])
        if stage == "normalization":
            observed.pop("ledger_check")
        result.append({"stage": stage, "passed": equivalent(observed, expected[stage]),
                       "observed": observed, "expected": expected[stage]})
    return result
