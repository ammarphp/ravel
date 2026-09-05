#!/usr/bin/env python
"""Native (arm64, no container) driver for mapyde's Delphes2SA.py.

Runs the UNMODIFIED mapyde Delphes2SA.py converter against a Delphes ntuple, but
points the Delphes includes/lib at the recast conda env instead of the container's
/usr/local/share/delphes layout. Verified bit-for-bit identical to the container
output (all 55 SA-ntuple branches, incl. the XS-normalised mcWeights and the
muon-corrected met_pt; see MISSION C findings).

Usage (run inside the recast conda env):
  conda run -n recast python delphes2sa_native.py \
      --input  <delphes.root> --output <Delphes2SA.root> \
      --lumi <lumi_pb> --XS <xsec_pb>

The mapyde container command this reproduces (runner.py:258-266):
  /scripts/Delphes2SA.py --input <delphes.root> --output <out> --lumi <L> --XS <xsec>
"""
from __future__ import annotations

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import os
from pathlib import Path
import sys
import argparse
import json
import math

from ..paths import native_build_root
from .native_normalization import positive, weight_summary, reconcile_weights, load_normalization, fingerprint


def read_weights(ROOT, path, *, converted=False):
    stream = ROOT.TFile.Open(str(path))
    if not stream or stream.IsZombie():
        raise ValueError(f"cannot open weight source {path}")
    try:
        tree = stream.Get("ntuple" if converted else "Delphes")
        branch = "mcWeights" if converted else "Event"
        if not tree or not tree.GetBranch(branch):
            raise ValueError(f"input lacks required nominal weights: {branch}")
        weights = []
        for index in range(tree.GetEntries()):
            tree.GetEntry(index)
            row = getattr(tree, branch)
            if converted:
                if len(row) < 1:
                    raise ValueError("missing converted nominal weight")
                weights.append(float(row[0]))
            else:
                if row.GetEntries() != 1:
                    raise ValueError("Delphes needs exactly one nominal event record")
                weights.append(float(row.At(0).Weight))
        weight_summary(weights)
        return weights
    finally:
        stream.Close()


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--help"] or arguments == ["-h"]:
        print(__doc__)
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lumi", type=float, required=True)
    parser.add_argument("--XS", type=float)
    parser.add_argument("--normalization")
    parser.add_argument("--converter-script")
    parser.add_argument("--recast-env")
    args, extra = parser.parse_known_args(arguments)
    lumi = positive(args.lumi, "luminosity (pb^-1)")
    record = load_normalization(args.normalization) if args.normalization else None
    xs = positive(record["applied_cross_section_pb"] if record else args.XS, "cross section (pb)")
    if record and args.XS is not None and not math.isclose(xs,positive(args.XS,"explicit XS"),rel_tol=1e-12):
        raise ValueError("explicit XS disagrees with normalization evidence")
    arguments = ["--input",args.input,"--output",args.output,"--lumi",str(lumi),"--XS",str(xs),*extra]
    tools = native_build_root() / "tools/miniforge3/envs"
    recast = Path(args.recast_env or os.environ.get("RECAST", str(tools / "recast")))
    script = Path(args.converter_script or os.environ.get("D2SA", str(tools / "pipeline/share/mapyde/scripts/Delphes2SA.py")))
    if not script.is_file():
        raise FileNotFoundError(f"mapyde converter missing: {script}. Set D2SA or RAVEL_NATIVE_BUILD.")
    import ROOT

    # The native Delphes headers and library differ from the container layout.
    for suffix in ("", "/classes", "/ExRootAnalysis"):
        ROOT.gInterpreter.AddIncludePath(f"{recast}/include{suffix}")
    ROOT.gInterpreter.Declare(f'#include "{recast}/include/classes/DelphesClasses.h"')
    ROOT.gInterpreter.Declare(f'#include "{recast}/include/ExRootAnalysis/ExRootTreeReader.h"')
    library = recast / "lib" / ("libDelphes.dylib" if sys.platform == "darwin" else "libDelphes.so")
    ROOT.gSystem.Load(str(library))
    raw_weights = read_weights(ROOT,args.input)
    before = weight_summary(raw_weights)
    if record:
        generated = record["generation"]
        if before["n_events"] != generated["n_events"] or before["negative_weights"] != generated["negative_weights"]:
            raise ValueError("detector event count or weight signs disagree with generation")
        # A global HepMC weight unit conversion is harmless; a change in relative
        # weight moments is not. Each conversion weight is checked below as well.
        if not math.isclose(math.sqrt(before["sumw2"])/before["sumw"],
                            math.sqrt(generated["sumw2"])/generated["sumw"],rel_tol=2e-5):
            raise ValueError("detector weight moments disagree with generation")

    # Prevent the upstream script repeating incompatible container-specific loads.
    original_load, original_declare = ROOT.gSystem.Load, ROOT.gInterpreter.Declare
    original_environment = os.environ.get("DELPHES_PATH")
    original_argv = sys.argv
    try:
        ROOT.gSystem.Load = lambda name, *a, **k: (1 if "libDelphes" in str(name)
                                                    else original_load(name, *a, **k))
        ROOT.gInterpreter.Declare = lambda text: (True if ("DelphesClasses.h" in text
                                                          or "ExRootTreeReader.h" in text)
                                                  else original_declare(text))
        os.environ["DELPHES_PATH"] = f"{recast}/include"
        sys.argv = [str(script), *arguments]
        namespace = {"__name__": "__main__", "__file__": str(script)}
        exec(compile(script.read_text(), str(script), "exec"), namespace)
    finally:
        ROOT.gSystem.Load, ROOT.gInterpreter.Declare = original_load, original_declare
        sys.argv = original_argv
        if original_environment is None:
            os.environ.pop("DELPHES_PATH", None)
        else:
            os.environ["DELPHES_PATH"] = original_environment
    audit = reconcile_weights(raw_weights,read_weights(ROOT,args.output,converted=True),xs)
    audit.update({"schema_version":1,"luminosity_pb_inverse":lumi,
                  "generation_reconciled":record is not None,
                  "sources":[fingerprint(args.input),fingerprint(script)],
                  "output":fingerprint(args.output)})
    if record:
        audit["normalization"] = fingerprint(args.normalization)
    Path(args.output+".normalization.json").write_text(json.dumps(audit,indent=2,allow_nan=False)+"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
