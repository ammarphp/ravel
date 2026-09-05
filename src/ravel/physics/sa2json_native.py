#!/usr/bin/env python
"""Native (no-container) sa2json — mapyde SAtoJSON.py with the one numpy>=2 fix.

mapyde's SAtoJSON.py builds a pyhf patch by summing uproot-read SR weights into
`yld` and writing `"data": [yld]`. Under the rivet env (uproot 5 + numpy 2.x +
py3.14) that sum is a numpy.float32, which json.dump refuses to serialise
(TypeError: Object of type float32 is not JSON serializable). The container's
older numpy returned a python-castable float. The ONLY change here is casting
yld -> float(); the patch is otherwise byte-for-byte identical to the container's
(verified: 32 SR insertions, maxrel=0.0). Run in the rivet env (uproot, pyhf,
jsonpatch).

Same CLI as the mapyde container command (runner.run_sa2json):
  python SAtoJSON.py -i <SA.root> -o <patch.json> -n <name> -b <bkgonly.json> -l <lumi> -c
"""
from __future__ import annotations

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse, copy, json


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

    print("Using luminosity=%f" % float(args.lumi))
    if args.compressed:
        print("Applying ee/mm masks to SA output as needed")


    with open(args.background) as f:
        spec = json.load(f)
    newspec = copy.deepcopy(spec)
    ws = pyhf.Workspace(spec)

    rootfiles = [uproot.open(i) for i in args.input]
    trees = [r["ntuple"] for r in rootfiles]
    branchsets = [t.arrays() for t in trees]

    for channel in ws.channels:
        c_index = ws.channels.index(channel)
        SAname = JSONtoSA(channel, args.background)
        if SAname is None:
            continue
        yld = 0.0
        for tree, branches in zip(trees, branchsets):
            if SAname in tree:
                mask = branches[SAname] > 0
                if args.compressed:
                    flavname = "isee" if "ee" in channel else "ismm"
                    mask = (branches[SAname] > 0) & (branches[flavname] > 0)
                yld += sum(branches[SAname][mask])
        yld = float(yld) * float(args.lumi) * float(args.scale)   # <-- the only fix: float()
        print("%3d  %40s  %40s  %.2e" % (c_index, channel, SAname, yld))
        newspec["channels"][c_index]["samples"].append({
            "name": args.name,
            "data": [float(yld)],
            "modifiers": [{"name": "mu_SIG", "type": "normfactor", "data": None}],
        })

    patch = jsonpatch.make_patch(spec, newspec)
    with open(args.output, "w") as f:
        json.dump(patch.patch, f, sort_keys=True, indent=4)


if __name__ == "__main__":
    main()
