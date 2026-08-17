#!/usr/bin/env bash
# 01_create_env.sh
# -----------------------------------------------------------------------------
# PURPOSE: Create an isolated conda environment named `mg5` that holds the exact
#          interpreter + compiler MadGraph 2.9.x needs.
#
# WHY each package:
#   python=3.10  MadGraph 2.9.x is a Python program. It targets Python 3.7-3.11
#                and uses modules (`imp`, `distutils`) that were REMOVED in
#                Python 3.12+. The system Python here is 3.13, which would crash
#                MadGraph on import. 3.10 is a safe, well-tested choice.
#   gfortran=13  MadGraph's physics core (matrix elements, the MadEvent phase-
#                space integrator) is Fortran 77/90. There is NO Fortran compiler
#                on this machine. conda-forge's gfortran ships with the proper
#                arm64 activation scripts (SDKROOT etc.) so linking "just works".
#                Pinned to the 13.x series for maturity with this MadGraph era.
#   make         Build driver used to compile the generated Fortran.
#
# The environment is kept SEPARATE from conda `base` (which is Python 3.13) so
# the two interpreters never collide.
# -----------------------------------------------------------------------------
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${BUILD_DIR:-$PROJECT/build}"   # local-only build area (gitignored); override with BUILD_DIR=...
CONDA="$BUILD/tools/miniforge3/bin/conda"

echo "[1/2] Creating conda env 'mg5' (python 3.10 + gfortran 13 + make) ..."
"$CONDA" create -y -n mg5 -c conda-forge \
    python=3.10 "gfortran=13.*" make

echo "[2/2] Verifying the toolchain inside the env ..."
"$CONDA" run -n mg5 bash -lc 'python --version; gfortran --version | head -1; make --version | head -1'

echo "[done] env 'mg5' ready."
