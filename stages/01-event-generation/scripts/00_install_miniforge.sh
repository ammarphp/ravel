#!/usr/bin/env bash
# 00_install_miniforge.sh
# -----------------------------------------------------------------------------
# PURPOSE: Provide a self-contained, user-space scientific toolchain.
#
# WHY: This machine has NO Fortran compiler (gfortran) and NO package manager
#      (no brew/conda/pyenv), and only Python 3.13 (too new for MadGraph 2.9.x,
#      which depends on the `imp`/`distutils` modules removed in Python 3.12+).
#      Miniforge installs conda into a single user-owned directory (NO admin
#      rights needed) and lets us pull a properly-configured arm64 `gfortran`
#      plus a compatible Python 3.10 from conda-forge. Everything needed to
#      compile MadGraph's Fortran matrix elements then lives in one prefix.
#
# IDEMPOTENT: skips the install if tools/miniforge3 already exists.
# -----------------------------------------------------------------------------
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${BUILD_DIR:-$PROJECT/build}"   # local-only build area (gitignored); override with BUILD_DIR=...
TOOLS="$BUILD/tools"
INSTALLER="$TOOLS/Miniforge3-MacOSX-arm64.sh"
PREFIX="$TOOLS/miniforge3"
URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh"

mkdir -p "$TOOLS"

if [ -d "$PREFIX" ]; then
  echo "[skip] Miniforge already installed at $PREFIX"
  exit 0
fi

echo "[1/2] Downloading Miniforge installer (arm64) ..."
curl -L --fail --retry 3 -o "$INSTALLER" "$URL"

echo "[2/2] Installing Miniforge to $PREFIX (batch mode, no admin) ..."
# -b = batch (non-interactive), -p = install prefix
bash "$INSTALLER" -b -p "$PREFIX"

echo "[done] conda available at: $PREFIX/bin/conda"
"$PREFIX/bin/conda" --version
