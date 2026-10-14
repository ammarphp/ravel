"""Pure JSON construction of a CR-signal contrast; no pyhf import/evaluation.

Both endpoints retain every original template, modifier and constraint setting.
An additional fixed, unconstrained multiplicative normfactor is attached only
to the named signal in the declared control channels. Its zero endpoint removes
the complete signal response, including additive template variations. This is
a prospective recipe. Compiled parameter/auxiliary identity must be checked in
a separately admitted model operation before any likelihood interpretation.
"""
import copy
import hashlib
import json

SWITCH = "ravel_diagnostic_CR_signal_multiplier"


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def construct(workspace, *, signal_name, control_channels, measurement_name, level):
    require(type(level) is int and level in (0, 1), "Only literal fixed endpoints 0 or 1")
    require(type(signal_name) is str and signal_name, "Explicit signal name required")
    require(type(control_channels) in (list, tuple) and control_channels and
            len(set(control_channels)) == len(control_channels), "Unique explicit CR names required")
    before = digest(workspace)
    names = [c["name"] for c in workspace["channels"]]
    require(len(set(names)) == len(names) and set(control_channels) <= set(names),
            "Missing or repeated workspace control channel")
    measurements = [m for m in workspace["measurements"] if m["name"] == measurement_name]
    require(len(measurements) == 1, "Exactly one declared measurement required")
    require(all(m["name"] != SWITCH for c in workspace["channels"] for s in c["samples"]
                for m in s["modifiers"]) and all(p["name"] != SWITCH
                for m in workspace["measurements"] for p in m["config"].get("parameters", [])),
            "Diagnostic name collides with existing parameter or modifier")
    for c in workspace["channels"]:
        if c["name"] in control_channels:
            require(sum(s["name"] == signal_name for s in c["samples"]) == 1,
                    "Each declared control must have exactly one named signal")
    out = copy.deepcopy(workspace)
    for c in out["channels"]:
        if c["name"] in control_channels:
            next(s for s in c["samples"] if s["name"] == signal_name)["modifiers"].append(
                {"name": SWITCH, "type": "normfactor", "data": None})
    measurement = next(m for m in out["measurements"] if m["name"] == measurement_name)
    measurement["config"].setdefault("parameters", []).append(
        {"name": SWITCH, "inits": [float(level)], "bounds": [[0.0, 1.0]], "fixed": True})
    require(digest(workspace) == before, "Input workspace was mutated")
    # A structural reversible witness: only the newly declared factor/config
    # entries may differ. This does not claim compiled-model equivalence.
    restored = copy.deepcopy(out)
    for c in restored["channels"]:
        for s in c["samples"]:
            s["modifiers"] = [m for m in s["modifiers"] if m["name"] != SWITCH]
    rm = next(m for m in restored["measurements"] if m["name"] == measurement_name)
    rm["config"]["parameters"] = [p for p in rm["config"]["parameters"] if p["name"] != SWITCH]
    if "parameters" not in measurements[0]["config"]:
        del rm["config"]["parameters"]
    require(canonical(restored) == canonical(workspace), "Unexpected original scientific JSON change")
    return out
