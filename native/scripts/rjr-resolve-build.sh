#!/usr/bin/env bash
# Use the exact environment prefix; --dry-run probes and prints without building.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO/native/scripts/paths.sh"
source "$REPO/native/scripts/macos-common.sh"
ARCH="$(ravel_macos_arch)"
PREFIX="$RAVEL_NATIVE_BUILD/tools/miniforge3"
ENV="$PREFIX/envs/recast"
ravel_check_conda "$PREFIX" "$ARCH"
ravel_check_macos_binary "$ENV/bin/python" "$ARCH"
[ -z "${OUT:-}" ] || set -- --out "$OUT" "$@"
[ -z "${RF_PREFIX:-}" ] || set -- --restframes "$RF_PREFIX" "$@"
exec "$PREFIX/bin/conda" run --no-capture-output --prefix "$ENV" python -B "$REPO/scripts/run.py" \
  ravel.physics.native_build rjr --prefix "$ENV" "$@"
