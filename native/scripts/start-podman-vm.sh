#!/bin/bash
# Start the podman SimpleAnalysis/Delphes VM on Apple Silicon.
# Root cause of the "vfkit exited unexpectedly / rosetta is unsupported on non-arm64" failure:
# the conda-forge podman in env `pipeline` is an x86_64 build, so under Rosetta it launches vfkit
# as its x86 slice, and an x86 vfkit refuses the Rosetta device the amd64 SimpleAnalysis containers
# need. Fix: force vfkit to run as arm64 (it is a universal binary) via an `arch -arm64` wrapper that
# podman picks up through CONTAINERS_HELPER_BINARY_DIR.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
source "$REPO/native/scripts/paths.sh"
PBIN="$RAVEL_NATIVE_BUILD/tools/miniforge3/envs/pipeline/bin"
CONDA="$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda"
HELP="$(mktemp -d -t podman-helpers-XXXX)"
printf '#!/bin/bash\nexec arch -arm64 "%s" "$@"\n' "$PBIN/vfkit" > "$HELP/vfkit"
chmod +x "$HELP/vfkit"
ln -sf "$PBIN/gvproxy" "$HELP/gvproxy"
export CONTAINERS_HELPER_BINARY_DIR="$HELP"
echo "[start_podman_vm] helper dir $HELP ; starting mg-vm ..."
"$CONDA" run -n pipeline podman machine start mg-vm
echo "[start_podman_vm] export CONTAINERS_HELPER_BINARY_DIR=$HELP   # for any later 'podman machine' op"
