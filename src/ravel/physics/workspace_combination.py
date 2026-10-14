"""Explicit source-workspace combination using the existing pyhf compiler.

This private API compiles but never fits or evaluates a density. Caller-supplied
event-population independence remains a scientific assumption, not a name test.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(compact(value)).hexdigest()


def parameter_contract(parameter):
    result = {"dimension": parameter.n_parameters, "scalar": parameter.is_scalar,
              "initial": list(parameter.suggested_init),
              "bounds": [list(row) for row in parameter.suggested_bounds],
              "fixed": list(parameter.suggested_fixed),
              "constrained": parameter.constrained}
    if parameter.constrained:
        result.update(pdf=parameter.pdf_type, observed=list(parameter.auxdata))
        if parameter.pdf_type == "normal":
            result["sigma"] = list(parameter.width())
        elif parameter.pdf_type == "poisson":
            result["factors"] = list(parameter.factors)
        else:
            raise ValueError("unsupported auxiliary law")
    compact(result)
    return result


def combine(components, policy):
    """Compile disjoint complete channels with explicit latent correlations.

Every modifier name must be mapped, even when unchanged. Every cross-component
name collision must be declared with its exact component roster. Shared vector
parameters are deliberately refused until an explicit bin-coordinate join is
provided; scalar histosys and normsys can share one Normal auxiliary.
    """
    import pyhf
    if set(policy) != {"measurement", "poi", "shared_parameters", "independence"}:
        raise ValueError("closed combination policy required")
    if not isinstance(components, list) or not 2 <= len(components) <= 8:
        raise ValueError("two to eight complete components required")
    if not isinstance(policy["independence"], str) or not policy["independence"].strip():
        raise ValueError("explicit source-backed channel-population independence statement required")
    for key in ("measurement", "poi"):
        if not isinstance(policy[key], str) or not policy[key]:
            raise ValueError("named common measurement and POI required")
    workspaces, originals, identities, channels, contracts = [], [], [], set(), []
    occurrences = {}
    for row in components:
        if set(row) != {"id", "workspace", "measurement", "parameter_map"}:
            raise ValueError("closed component declaration required")
        identity = row["id"]
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("distinct component identities required")
        identities.append(identity)
        original = deepcopy(row["workspace"])
        spec = deepcopy(original)
        measurements = [m for m in spec["measurements"] if m["name"] == row["measurement"]]
        if len(measurements) != 1:
            raise ValueError("one exact source measurement required")
        measurement = measurements[0]
        names = {m["name"] for ch in spec["channels"] for s in ch["samples"] for m in s["modifiers"]}
        names.add(measurement["config"]["poi"])
        mapping = row["parameter_map"]
        if not isinstance(mapping, dict) or set(mapping) != names:
            raise ValueError("complete exact source parameter map required")
        if any(not isinstance(v, str) or not v for v in mapping.values()):
            raise ValueError("nonempty target parameter names required")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("merging distinct source parameters is forbidden")
        if mapping[measurement["config"]["poi"]] != policy["poi"]:
            raise ValueError("common POI differs from mapped source POI")
        local_channels = [ch["name"] for ch in spec["channels"]]
        if len(local_channels) != len(set(local_channels)) or channels.intersection(local_channels):
            raise ValueError("complete channel populations must have distinct names")
        observed_names = [observation["name"] for observation in spec["observations"]]
        if Counter(observed_names) != Counter(local_channels):
            raise ValueError("exactly one observation for every source channel required")
        dimensions = {ch["name"]: len(ch["samples"][0]["data"]) for ch in spec["channels"]}
        for observation in spec["observations"]:
            if (len(observation["data"]) != dimensions[observation["name"]]
                    or any(type(n) not in (float, int) or not math.isfinite(n) or n < 0 for n in observation["data"])):
                raise ValueError("finite nonnegative complete observed bins required")
        channels.update(local_channels)
        # Validate the released source before a rename can repair invalid input.
        source_workspace = pyhf.Workspace(original)
        source_model = source_workspace.model(measurement_name=row["measurement"])
        source_contract = {name: parameter_contract(source_model.config.param_set(name))
                           for name in source_model.config.par_order}
        for channel in spec["channels"]:
            for sample in channel["samples"]:
                for modifier in sample["modifiers"]:
                    modifier["name"] = mapping[modifier["name"]]
        config = measurement["config"]
        config["poi"] = policy["poi"]
        for parameter in config["parameters"]:
            if parameter["name"] not in mapping:
                raise ValueError("configured parameter missing from source map")
            parameter["name"] = mapping[parameter["name"]]
        measurement["name"] = policy["measurement"]
        spec["measurements"] = [measurement]
        workspace = pyhf.Workspace(spec)
        model = workspace.model(measurement_name=policy["measurement"])
        contract = {name: parameter_contract(model.config.param_set(name)) for name in model.config.par_order}
        mapped_source_contract = {mapping[name]: parameter for name, parameter in source_contract.items()}
        if contract != mapped_source_contract:
            raise ValueError("parameter mapping changed the original effective source law")
        for name in contract:
            occurrences.setdefault(name, []).append(identity)
        workspaces.append(workspace)
        contracts.append(contract)
        originals.append({"id": identity, "workspace_sha256": digest(original),
                          "mapped_workspace_sha256": digest(spec),
                          "source_measurement": row["measurement"], "parameter_map": deepcopy(mapping),
                          "source_parameters": source_contract,
                          "mapped_source_parameters": mapped_source_contract,
                          "parameters": contract})
    shared = {name: sorted(ids) for name, ids in occurrences.items() if len(ids) > 1}
    declared = policy["shared_parameters"]
    if (not isinstance(declared, dict) or any(not isinstance(v, list) or v != sorted(set(v)) for v in declared.values())
            or declared != shared):
        raise ValueError("every shared parameter needs its exact declared component roster")
    expected = {}
    for contract in contracts:
        for name, parameter in contract.items():
            if name in expected:
                if not parameter["scalar"] or parameter != expected[name]:
                    raise ValueError("shared parameter law, domain or coordinate identity differs: " + name)
            expected[name] = parameter
    result = workspaces[0]
    for workspace in workspaces[1:]:
        result = pyhf.Workspace.combine(result, workspace, join="outer", merge_channels=False)
    joined_model = result.model(measurement_name=policy["measurement"])
    actual = {name: parameter_contract(joined_model.config.param_set(name)) for name in joined_model.config.par_order}
    if actual != expected:
        raise ValueError("combination changed an effective parameter or auxiliary law")
    if Counter(ch["name"] for ch in result["channels"]) != Counter(channels):
        raise ValueError("combination lost or duplicated channels")
    auxiliary_terms = sum(p["dimension"] for p in actual.values() if p["constrained"])
    if joined_model.config.nauxdata != auxiliary_terms:
        raise ValueError("combined auxiliary census is not the unique parameter-law union")
    report = {"schema_version": 1, "components": originals, "policy": deepcopy(policy),
              "workspace_sha256": digest(dict(result)), "parameters": actual,
              "channels": sorted(channels), "parameter_dimension": joined_model.config.npars,
              "auxiliary_terms": auxiliary_terms, "shared_parameters": shared,
              "compiler": {"implementation": "pyhf.Workspace.combine(outer, merge_channels=False)",
                           "pyhf_version": pyhf.__version__},
              "scope": "complete workspace and unique effective parameter-law compilation only",
              "density_evaluations": 0, "fits": 0, "physics_validated": False}
    return {"workspace": dict(result), "report": report}
