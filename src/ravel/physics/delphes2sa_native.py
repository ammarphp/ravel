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

from ..paths import native_build_root


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--help"] or arguments == ["-h"]:
        print(__doc__)
        return 0
    tools = native_build_root() / "tools/miniforge3/envs"
    recast = Path(os.environ.get("RECAST", str(tools / "recast")))
    script = Path(os.environ.get("D2SA", str(tools / "pipeline/share/mapyde/scripts/Delphes2SA.py")))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
