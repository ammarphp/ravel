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
import os, sys
import ROOT

import os as _os
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root (location-relative; repo is relocatable)
RECAST = os.environ.get(
    "RECAST",
    f"{REPO}/stages/01-event-generation/build/tools/miniforge3/envs/recast",
)
D2SA = os.environ.get(
    "D2SA",
    f"{REPO}/stages/01-event-generation/build/tools/miniforge3/envs/pipeline/share/mapyde/scripts/Delphes2SA.py",
)

# conda Delphes layout differs from the container: headers live under include/
# (classes/, ExRootAnalysis/) NOT include/external/..., and the lib is a .dylib.
ROOT.gInterpreter.AddIncludePath(f"{RECAST}/include")
ROOT.gInterpreter.AddIncludePath(f"{RECAST}/include/classes")
ROOT.gInterpreter.AddIncludePath(f"{RECAST}/include/ExRootAnalysis")
ROOT.gInterpreter.Declare(f'#include "{RECAST}/include/classes/DelphesClasses.h"')
ROOT.gInterpreter.Declare(f'#include "{RECAST}/include/ExRootAnalysis/ExRootTreeReader.h"')
ROOT.gSystem.Load(f"{RECAST}/lib/libDelphes.dylib")

# The mapyde script ALSO does its own DELPHES_PATH-based Load("...libDelphes.so") +
# Declare of the relative headers. On macOS the .so load + the container-relative
# header paths fail; everything is already declared/loaded above, so neutralise them.
_orig_load = ROOT.gSystem.Load
ROOT.gSystem.Load = (lambda name, *a, **k:
    1 if "libDelphes" in str(name) else _orig_load(name, *a, **k))
_orig_declare = ROOT.gInterpreter.Declare
ROOT.gInterpreter.Declare = (lambda s:
    True if ("DelphesClasses.h" in s or "ExRootTreeReader.h" in s)
    else _orig_declare(s))
os.environ["DELPHES_PATH"] = f"{RECAST}/include"

# Hand the mapyde script its argv unmodified (it uses argparse: --input/--output/--lumi/--XS).
# sys.argv already carries the flags from the conda-run invocation.
g = {"__name__": "__main__", "__file__": D2SA}
exec(compile(open(D2SA).read(), D2SA, "exec"), g)
