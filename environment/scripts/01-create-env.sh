#!/usr/bin/env bash
# Resolve a platform-specific MG5 environment and retain its explicit package lock.
# These constraints are not a pre-solved multi-platform environment lock.
set -euo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT/../native/scripts/paths.sh"
source "$PROJECT/../native/scripts/macos-common.sh"
DRY=0
case "${1:-}" in --dry-run) DRY=1 ;; '') ;; *) echo "Usage: $0 [--dry-run]" >&2; exit 2 ;; esac
[ "$#" -le 1 ] || { echo 'Unexpected arguments' >&2; exit 2; }
ARCH="$(ravel_macos_arch)"
BUILD="${BUILD_DIR:-$RAVEL_NATIVE_BUILD}"
PREFIX="$BUILD/tools/miniforge3"
ENV="$PREFIX/envs/mg5"
ravel_check_conda "$PREFIX" "$ARCH"
if [ -e "$ENV" ] || [ -L "$ENV" ]; then
  echo "ERROR: environment already exists at $ENV; use the native doctor to inspect it, or select a new build prefix" >&2
  exit 1
fi
CMD=("$PREFIX/bin/conda" create --yes --prefix "$ENV" --override-channels --strict-channel-priority -c conda-forge python=3.10 'gfortran=13.*' make six numpy)
printf '%q ' "${CMD[@]}"; printf '\n'
[ "$DRY" = 0 ] || exit 0
"${CMD[@]}"
ravel_check_macos_binary "$ENV/bin/python" "$ARCH"
# No login shell: conda's activation must control compiler/Python discovery.
"$PREFIX/bin/conda" run --prefix "$ENV" python --version
"$PREFIX/bin/conda" run --prefix "$ENV" gfortran --version
"$PREFIX/bin/conda" list --prefix "$ENV" --explicit > "$ENV/ravel-explicit-packages.txt"
echo "[done] Environment and resolved package record: $ENV"
