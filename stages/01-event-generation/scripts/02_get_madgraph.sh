#!/usr/bin/env bash
# 02_get_madgraph.sh
# -----------------------------------------------------------------------------
# PURPOSE: Fetch the MadGraph5_aMC@NLO event generator source.
#
# WHAT MADGRAPH IS: a "matrix element" generator. Given a model (here the MSSM)
#   and a process (here slepton-pair production), it (1) writes the Feynman
#   amplitudes, (2) generates Fortran code to compute the squared matrix element,
#   (3) integrates that over phase space (the "MadEvent" sub-package) to get a
#   cross-section, and (4) draws unweighted parton-level events, written as a
#   Les Houches Event (LHE) file. That LHE file is the deliverable of this stage.
#
# VERSION: v2.9.27 — the latest patch in the 2.9 series carried by the official
#   GitHub repo (github.com/mg5amcnlo/mg5amcnlo). The paper used v2.9.3, which is
#   NOT tagged on GitHub (tags start at v2.9.10); LO slepton matrix-element
#   physics is identical across 2.9.x patch releases, so any 2.9.x reproduces it.
#
# A shallow clone (--depth 1) of just this tag keeps the download small.
# -----------------------------------------------------------------------------
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${BUILD_DIR:-$PROJECT/build}"   # local-only build area (gitignored); override with BUILD_DIR=...
DEST="$BUILD/tools/mg5amcnlo"
TAG="v2.9.27"
REPO="https://github.com/mg5amcnlo/mg5amcnlo"

if [ -d "$DEST" ]; then
  echo "[skip] MadGraph already present at $DEST"
else
  echo "[1/2] Shallow-cloning MadGraph $TAG ..."
  git clone --depth 1 --branch "$TAG" "$REPO" "$DEST"
fi

echo "[2/2] Checking mg5_aMC launches under the env's Python 3.10 ..."
"$BUILD/tools/miniforge3/bin/conda" run -n mg5 python "$DEST/bin/mg5_aMC" --version

echo "[done] MadGraph at $DEST"
