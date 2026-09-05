#!/usr/bin/env python
"""Convert native SimpleAnalysis ROOT weighted yields to a HistFactory signal patch.

The existing mapyde-compatible channel-name mapping and CLI are retained. Selected
weights are summed with their signs, including when applying flavour masks. Every
requested SR branch must exist and contain finite weights. The patch follows the
original workspace channel order; pyhf's sorted channel view must not index raw JSON.
Negative net signal expectations are rejected because this ordinary Poisson-template
path cannot interpret them. This is weighted-yield preservation, not a claim that
the complete inference pipeline supports arbitrary signed templates or MC errors.

Same CLI as the mapyde container command (runner.run_sa2json):
  python SAtoJSON.py -i <SA.root> -o <patch.json> -n <name> -b <bkgonly.json> -l <lumi> -c
"""
from __future__ import annotations

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse, copy, json, math
from contextlib import ExitStack


def selected_weight_sum(branches, sr_name, flavour=None):
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
        values = values[mask_values > 0]
    return math.fsum(map(float, values))


def JSONtoSA(SRname, background):
    parts = SRname.split("_")
    if "CR" in parts[0]:
        return None
    if "MonoJet" in background:
        return SRname.replace("_cuts", "")
    SAname = "SR"
    if "MT2" in parts[1]:
        SAname += "_S_"
        if "hghmet" in parts[2]:
            SAname += "high_"
        elif "lowmet" in parts[2] and "MT2" in parts[1]:
            SAname += "low_"
        SAname += parts[1]
    else:
        SAname += "_E_"
        if "Onelep1track" in parts[2]:
            SAname += "lT_"
        elif "hghmet" in parts[2]:
            SAname += "high_"
        elif "lowmet" in parts[2] and "low" in parts[4]:
            SAname += "med_"
        elif "lowmet" in parts[2] and "high" in parts[4]:
            SAname += "low_"
        SAname += parts[1]
    return SAname



def main(argv=None):
    p = argparse.ArgumentParser(description="SA ROOT -> HiFa pyhf patch (native).")
    p.add_argument("-i", "--input", action="append", required=True, help="SA output .root (repeatable)")
    p.add_argument("-b", "--background", required=True, help="background-only HistFactory JSON")
    p.add_argument("-o", "--output", required=True, help="output patch JSON")
    p.add_argument("-n", "--name", required=True, help="signal sample name")
    p.add_argument("-l", "--lumi", type=float, required=True, help="luminosity (pb-1)")
    p.add_argument("-s", "--scale", type=float, default=1.0, help="extra weight scale")
    p.add_argument("-c", "--compressed", action="store_true",
                   help="compressed search: apply ee/mm flavour masks")
    args = p.parse_args(argv)
    import jsonpatch, pyhf, uproot
    for name in ("lumi", "scale"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            p.error(f"--{name} must be finite and positive")

    print("Using luminosity=%f" % float(args.lumi))
    if args.compressed:
        print("Applying ee/mm masks to SA output as needed")


    with open(args.background) as f:
        spec = json.load(f)
    newspec = copy.deepcopy(spec)
    ws = pyhf.Workspace(spec)

    with ExitStack() as stack:
        rootfiles = [stack.enter_context(uproot.open(i)) for i in args.input]
        trees = [r["ntuple"] for r in rootfiles]
        branchsets = [t.arrays() for t in trees]

    for c_index, specification in enumerate(spec["channels"]):
        channel = specification["name"]
        SAname = JSONtoSA(channel, args.background)
        if SAname is None:
            continue
        if any(len(sample["data"]) != 1 for sample in specification["samples"]):
            raise ValueError(f"channel {channel} is not single-bin; an aggregate SR yield cannot define its shape")
        if any(sample["name"] == args.name for sample in specification["samples"]):
            raise ValueError(f"signal sample {args.name} already exists in {channel}")
        flavname = ("isee" if "ee" in channel else "ismm") if args.compressed else None
        yld = math.fsum(selected_weight_sum(branches, SAname, flavname) for branches in branchsets)
        yld *= args.lumi * args.scale
        if not math.isfinite(yld) or yld < 0:
            raise ValueError(f"channel {channel} has a nonfinite or negative net signal yield ({yld}); "
                             "this Poisson signal-template path cannot represent it")
        print("%3d  %40s  %40s  %.2e" % (c_index, channel, SAname, yld))
        newspec["channels"][c_index]["samples"].append({
            "name": args.name,
            "data": [float(yld)],
            "modifiers": [{"name": "mu_SIG", "type": "normfactor", "data": None}],
        })

    patch = jsonpatch.make_patch(spec, newspec)
    with open(args.output, "w") as f:
        json.dump(patch.patch, f, sort_keys=True, indent=4, allow_nan=False)


if __name__ == "__main__":
    main()
