#!/usr/bin/env python
"""Convert native SimpleAnalysis ROOT weighted yields to a HistFactory signal patch.

Selected weights and their squares are retained, with explicit optional shapesys
or staterror constraints from the actual MC moments. A complete supplied channel map declares every signal region, flavour mask
and zero-signal channel. Negative net yields and unresolved multiplicative uncertainties fail.
The patch follows original workspace channel order. A provenance sidecar records
all moments and precision omissions; no detector or theory nuisances are copied.

Usage: -i <SA.root> -o <patch.json> -n <name> -b <bkgonly.json> -l <lumi> -c
       --channel-map <mapping.json> --mc-stat shapesys --signal-metadata <path>
Repeated inputs sum independent physical components; they do not pool independent
seeds of the same process. Multiple inputs require an explicit combination choice.
"""
from __future__ import annotations

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse, copy, hashlib, json, math, re
from contextlib import ExitStack
from pathlib import Path


def selected_weights(branches, sr_name, flavour=None):
    import numpy as np
    try:
        values = np.asarray(branches[sr_name], dtype=float)
    except (KeyError, ValueError, IndexError) as exc:
        raise ValueError(f"missing or invalid SR branch: {sr_name}") from exc
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise ValueError(f"SR branch {sr_name} must contain finite scalar weights")
    if flavour is not None:
        try:
            mask_values = np.asarray(branches[flavour], dtype=float)
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError(f"missing or invalid flavour branch: {flavour}") from exc
        if mask_values.shape != values.shape or not np.all(np.isfinite(mask_values)) or np.any(mask_values < 0):
            raise ValueError(f"flavour branch {flavour} must be finite, nonnegative and aligned with {sr_name}")
        # Preserve the event alignment for overlap checks between model channels.
        values = np.where(mask_values > 0, values, 0.0)
    return values


def selected_weight_moments(branches, sr_name, flavour=None):
    values = selected_weights(branches, sr_name, flavour)
    try:
        total = math.fsum(map(float, values))
        squared = math.fsum(float(value)*float(value) for value in values)
    except OverflowError as exc:
        raise ValueError(f"weight moments overflow in region {sr_name}") from exc
    if not math.isfinite(total) or not math.isfinite(squared):
        raise ValueError(f"weight moments overflow in region {sr_name}")
    return {"sumw": total, "sumw2": squared,
            "nonzero_weights": int((values != 0).sum()),
            "negative_weights": int((values < 0).sum())}


def selected_weight_sum(branches, sr_name, flavour=None):
    return selected_weight_moments(branches, sr_name, flavour)["sumw"]


class MissingChannelMap(ValueError):
    """Signal injection requires a complete supplied channel map."""


def compressed_channel_map(workspace, mode=None, *, mapping=None):
    """Compatibility entry point; region definitions belong to supplied inputs."""
    if mapping is None:
        raise MissingChannelMap('explicit complete channel map required')
    return validate_channel_map(mapping, workspace)


def JSONtoSA(SRname, background):
    """Legacy implicit name conversion cannot establish channel semantics."""
    raise MissingChannelMap('explicit complete channel map required')


def validate_channel_map(mapping, workspace):
    """Explicit one-bin channel mapping; null means declared zero signal there."""
    names = {channel["name"] for channel in workspace["channels"]}
    if not isinstance(mapping,dict) or set(mapping) != names:
        raise ValueError("channel map must cover every workspace channel exactly")
    for channel in workspace["channels"]:
        entry = mapping[channel["name"]]
        if entry is None:
            continue
        if not isinstance(entry,dict) or set(entry)-{"region","flavour"} or not isinstance(entry.get("region"),str) or not entry["region"]:
            raise ValueError("channel map entries require a named region and optional flavour")
        if entry.get("flavour") is not None and (not isinstance(entry["flavour"],str) or not entry["flavour"]):
            raise ValueError("channel-map flavour must be a named branch")
        if any(len(sample["data"]) != 1 for sample in channel["samples"]):
            raise ValueError("mapped native yields require single-bin signal channels")
    if not any(entry is not None for entry in mapping.values()):
        raise ValueError("channel map declares no signal channel")
    return mapping


def signal_poi(workspace):
    """The injected signal must use the workspace's declared, signal-only POI."""
    measurements=workspace.get("measurements",[])
    pois={m.get("config",{}).get("poi") for m in measurements}
    if len(pois)!=1 or not all(isinstance(poi,str) and poi for poi in pois):
        raise ValueError("native signal injection requires one unambiguous measurement POI")
    poi=next(iter(pois))
    if any(modifier.get("name")==poi for channel in workspace["channels"]
           for sample in channel["samples"] for modifier in sample.get("modifiers",[])):
        raise ValueError("signal POI already modifies a background sample")
    return poi


def build_signal_patch(spec, branchsets, *, name, mapping, lumi, scale=1.0,
                       mc_stat=None, input_combination=None):
    """Build a nominal signal with an explicit finite-MC approximation.

    Each branch holds the event's signed, normalized weight or zero. Sumw2
    therefore survives the ROOT interchange without assuming uniform weights.
    shapesys uses an effective-Poisson constraint; staterror uses a Gaussian
    constraint. Neither supplies detector, trigger, ISR, or theory variations.
    """
    import jsonpatch
    import numpy as np
    import pyhf
    if mc_stat not in ("none", "shapesys", "staterror"):
        raise ValueError("explicit mc_stat must be none, shapesys or staterror")
    if not name or not all(math.isfinite(v) and v > 0 for v in (lumi, scale, lumi*scale)):
        raise ValueError("signal name and finite positive yield scale are required")
    validate_channel_map(mapping, spec)
    if not branchsets:
        raise ValueError("signal inputs are empty")
    combination = input_combination or "sum-independent-components"
    if combination == "pool-replicas":
        raise ValueError("replica pooling requires source-bound same-process identity and original generated exposures; "
                         "use a validated pooling helper, never infer exposure from selected ROOT rows")
    if combination != "sum-independent-components":
        raise ValueError("unknown signal input combination")
    if len(branchsets) > 1 and input_combination is None:
        raise ValueError("multiple signal inputs require explicit sum-independent-components; replicas must not be summed")
    poi = signal_poi(spec)
    newspec = copy.deepcopy(spec)
    reserved = {modifier["name"] for channel in spec["channels"] for sample in channel["samples"]
                for modifier in sample["modifiers"]}
    reserved.update(parameter["name"] for measurement in spec.get("measurements", [])
                    for parameter in measurement["config"].get("parameters", []))
    metadata = {"schema_version": 1, "sample": name, "poi": poi,
                "luminosity_pb_inverse": lumi, "additional_scale": scale,
                "mc_stat_policy": mc_stat,
                "input_combination": combination,
                "input_combination_note": "Additive independent physical components. Independent seeds of the same process are not pooled.",
                "mc_stat_interpretation": {"none": "omitted",
                    "shapesys": "effective-Poisson approximation from selected sumw and sumw2",
                    "staterror": "Gaussian approximation from selected sumw and sumw2"}[mc_stat],
                "detector_trigger_ISR_theory_variations": "not supplied",
                "acceptance_certified": False, "channels": []}
    occupied = [None for _ in branchsets]
    factor = lumi*scale
    for index, channel in enumerate(spec["channels"]):
        entry = mapping[channel["name"]]
        record = {"channel": channel["name"], "workspace_index": index, "mapping": entry}
        if entry is None:
            record.update(status="declared-signal-omission", precision_status="unresolved")
            metadata["channels"].append(record)
            continue
        if any(sample["name"] == name for sample in channel["samples"]):
            raise ValueError(f"signal sample {name} already exists in {channel['name']}")
        moments = []
        for stream_index, branches in enumerate(branchsets):
            values = selected_weights(branches, entry["region"], entry.get("flavour"))
            if mc_stat != "none":
                active = values != 0
                previous = occupied[stream_index]
                if previous is not None and (previous.shape != active.shape or np.any(previous & active)):
                    raise ValueError("independent signal MC uncertainties require aligned, disjoint model channels")
                occupied[stream_index] = active if previous is None else previous | active
            moments.append(selected_weight_moments(branches, entry["region"], entry.get("flavour")))
        try:
            total = math.fsum(moment["sumw"] for moment in moments)
            squared = math.fsum(moment["sumw2"] for moment in moments)
        except OverflowError as exc:
            raise ValueError("merged signal weight moments overflow") from exc
        yld, error = total*factor, math.sqrt(squared)*factor
        if not all(map(math.isfinite, (total, squared, yld, error))) or yld < 0:
            raise ValueError(f"channel {channel['name']} has nonfinite or negative net signal yield; "
                             "this Poisson template cannot represent it")
        modifiers = [{"name": poi, "type": "normfactor", "data": None}]
        record.update(sumw=total, sumw2=squared, nominal_yield=yld, mc_stat_error=error,
                      nonzero_weights=sum(moment["nonzero_weights"] for moment in moments),
                      negative_weights=sum(moment["negative_weights"] for moment in moments),
                      effective_events=(total/math.sqrt(squared))**2 if squared > 0 else None,
                      status="nominal-signal", precision_status="estimated-from-weight-moments",
                      mc_stat_modifier=None)
        if total == 0 and squared == 0:
            record["precision_status"] = "zero-selected/precision-unresolved"
            record["precision_note"] = "No nonzero selected weights; zero-weight selected events are indistinguishable. No finite-MC precision is certified."
        elif total == 0:
            record["precision_status"] = "signed-cancellation/precision-unresolved"
            if mc_stat != "none":
                raise ValueError(f"channel {channel['name']} has zero net yield but positive sumw2; "
                                 "multiplicative MC nuisance would silently discard its uncertainty")
        elif mc_stat != "none":
            effective = record["effective_events"]
            if not math.isfinite(effective) or effective <= 0 or error <= 0:
                raise ValueError("signal MC constraint is numerically unresolved")
            suffix = hashlib.sha256((name + "\0" + channel["name"]).encode()).hexdigest()[:20]
            nuisance = f"native_signal_mcstat_{suffix}"
            if nuisance in reserved or nuisance == poi:
                raise ValueError("signal MC nuisance name collides with an existing parameter")
            reserved.add(nuisance)
            modifiers.append({"name": nuisance, "type": mc_stat, "data": [error]})
            record["mc_stat_modifier"] = nuisance
        newspec["channels"][index]["samples"].append({"name": name, "data": [yld], "modifiers": modifiers})
        metadata["channels"].append(record)
    # Compile only; no fit. This catches invalid modifier combinations/bindings.
    pyhf.Workspace(newspec).model()
    return jsonpatch.make_patch(spec, newspec).patch, metadata


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return {"path": str(Path(path).resolve()), "sha256": digest.hexdigest(),
            "bytes": Path(path).stat().st_size}



def main(argv=None):
    p = argparse.ArgumentParser(description="SA ROOT -> HiFa pyhf patch (native).")
    p.add_argument("-i", "--input", action="append", required=True, help="SA output .root (repeatable)")
    p.add_argument("-b", "--background", required=True, help="background-only HistFactory JSON")
    p.add_argument("-o", "--output", required=True, help="output patch JSON")
    p.add_argument("-n", "--name", required=True, help="signal sample name")
    p.add_argument("-l", "--lumi", type=float, required=True, help="luminosity (pb-1)")
    p.add_argument("-s", "--scale", type=float, default=1.0, help="extra weight scale")
    p.add_argument("-c", "--compressed", action="store_true",
                   help="legacy flag; all region and flavour semantics require --channel-map")
    p.add_argument("--channel-map",help="explicit JSON channel -> {region, flavour?} mapping; null declares zero signal")
    p.add_argument("--compressed-signal-model", choices=("full", "sr-only-diagnostic"),
                   help="legacy signal-model label; --channel-map supplies channel semantics")
    p.add_argument("--mc-stat", choices=("none", "shapesys", "staterror"),
                   help="explicit finite-MC constraint policy; none reports the omission")
    p.add_argument("--signal-metadata", help="weight moments/provenance JSON (default: <output>.metadata.json)")
    p.add_argument("--input-combination", choices=("sum-independent-components", "pool-replicas"),
                   help="required for repeated inputs; additive components only. Replica pooling requires a separately validated helper")
    args = p.parse_args(argv)
    missing = (["--mc-stat"] if args.mc_stat is None else [])
    if not args.channel_map:missing.append("--channel-map")
    if args.compressed and args.compressed_signal_model is None:
        missing.append("--compressed-signal-model")
    if missing:
        p.error("explicit signal-model choices required: " + ", ".join(missing))
    import jsonpatch, pyhf, uproot
    for name in ("lumi", "scale"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            p.error(f"--{name} must be finite and positive")

    print("Using luminosity=%f" % float(args.lumi))
    print(f"Signal MC statistical uncertainty: {args.mc_stat}" + (" (OMITTED)" if args.mc_stat == "none" else ""))
    if args.compressed and args.compressed_signal_model == "sr-only-diagnostic":
        print("DIAGNOSTIC ONLY: control-region signal is omitted")


    with open(args.background) as f:
        spec = json.load(f)
    with open(args.channel_map) as stream:
        mapping = validate_channel_map(json.load(stream),spec)
    pyhf.Workspace(spec)
    signal_poi(spec)

    output = Path(args.output)
    metadata_output = Path(args.signal_metadata or (str(output) + ".metadata.json"))
    inputs = [Path(path).resolve() for path in args.input]
    protected = {*inputs, Path(args.background).resolve()}
    if args.channel_map:
        protected.add(Path(args.channel_map).resolve())
    if output.resolve() in protected or metadata_output.resolve() in protected or output.resolve() == metadata_output.resolve():
        raise ValueError("signal outputs must be distinct from all inputs and each other")
    sources = [fingerprint(path) for path in inputs]
    if len({source["sha256"] for source in sources}) != len(sources):
        raise ValueError("duplicate signal input content would double-count MC events")

    with ExitStack() as stack:
        rootfiles = [stack.enter_context(uproot.open(i)) for i in args.input]
        trees = [r["ntuple"] for r in rootfiles]
        branchsets = [t.arrays() for t in trees]

    patch, metadata = build_signal_patch(spec, branchsets, name=args.name, mapping=mapping,
                                        lumi=args.lumi, scale=args.scale, mc_stat=args.mc_stat,
                                        input_combination=args.input_combination)
    metadata.update(inputs=sources, background=fingerprint(args.background),
                    converter=fingerprint(__file__), compressed_signal_model=(args.compressed_signal_model if args.compressed else None))
    if args.channel_map:
        metadata["channel_map"] = fingerprint(args.channel_map)
    encoded_patch = (json.dumps(patch, sort_keys=True, indent=4, allow_nan=False) + "\n").encode()
    metadata["patch"] = {"path": str(output.resolve()), "sha256": hashlib.sha256(encoded_patch).hexdigest()}
    encoded_metadata = json.dumps(metadata, sort_keys=True, indent=2, allow_nan=False) + "\n"
    for record in metadata["channels"]:
        print(record["channel"], record.get("nominal_yield", "OMITTED"), record["precision_status"])
    metadata_output.write_text(encoded_metadata)
    output.write_bytes(encoded_patch)


if __name__ == "__main__":
    main()
