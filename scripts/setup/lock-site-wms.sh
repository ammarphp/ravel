#!/usr/bin/env bash
# Generate the production lock in the network-enabled release lane.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$REPO/.work/site-lock/cache}"
export TMPDIR="${TMPDIR:-$REPO/.work/site-lock/tmp}"
mkdir -p "$UV_CACHE_DIR" "$TMPDIR"
# The lock header names this script, not the machine paths of the checkout that ran it.
export UV_CUSTOM_COMPILE_COMMAND="bash scripts/setup/lock-site-wms.sh"
exec uv pip compile "$REPO/requirements-site-wms.in" --python-version 3.12 --universal \
  --generate-hashes --output-file "$REPO/requirements-site-wms.lock"
