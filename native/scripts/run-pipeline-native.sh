#!/usr/bin/env bash
# Native execution uses the same validated package plan as the scan launcher.
# No unsupervised fallback: every stage must earn its declared artifact receipt.
set -euo pipefail
if [ "$#" -ne 2 ]; then echo "Usage: $0 RUN_DIRECTORY CONFIG_FILE" >&2; exit 2; fi
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "${RAVEL_PYTHON:-python3}" "$REPO/scripts/run.py" ravel.physics.native_pipeline run --rundir "$1" --config "$2"
