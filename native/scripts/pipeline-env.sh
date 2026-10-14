#!/usr/bin/env bash
# Source this to get a working podman+mapyde environment for the faithful pipeline.
#   source native/scripts/pipeline-env.sh
# Assumes the podman machine 'mg-vm' has been started (see this folder's README).
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"  # repo root (location-relative)
source "$REPO/native/scripts/paths.sh"
TOOLS="$RAVEL_NATIVE_BUILD/tools"
export PIPE_ENVBIN="$TOOLS/miniforge3/envs/pipeline/bin"          # gvproxy, vfkit, mapyde
export PIPE_PODMAN_REAL="$TOOLS/podman-native/podman-5.8.2/usr/bin/podman"   # native arm64 client
export PIPE_WRAPBIN="$TOOLS/podman-native/bin-wrap"               # wrapper that forces amd64
export CONTAINERS_HELPER_BINARY_DIR="$PIPE_ENVBIN"
export CONTAINERS_MACHINE_PROVIDER=applehv
# wrapper podman first, then env bin (mapyde/gvproxy/vfkit), then the rest
export PATH="$PIPE_WRAPBIN:$PIPE_ENVBIN:$PATH"
# mapyde is launched via the conda env's python entry point on PATH (PIPE_ENVBIN)
