#!/bin/bash
# Installation check for a container-built JHUGen/MELA tree (no physics inputs needed).
#
# Usage: check-jhugen-mela.sh BUILD_DIR
# Confirms the launcher exists, matches the build receipt and that Python can import the MELA module.
# Prints one JSON line. Physics qualification is the amplitude cross-check point oracle, not this script.
set -euo pipefail
BUILD=$1
LAUNCH="$BUILD/ravel_jhugen_mela"
test -x "$LAUNCH" || { echo '{"status":"failed","reason":"launcher missing"}'; exit 1; }
SHA=$(sha256sum "$LAUNCH" | cut -d' ' -f1)
RECEIPT=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["launcher_sha256"])' "$BUILD/build-receipt.json")
test "$SHA" = "$RECEIPT" || { echo '{"status":"failed","reason":"launcher differs from build receipt"}'; exit 1; }
"$LAUNCH" -c 'import ROOT, Mela' >/dev/null 2>&1 || { echo '{"status":"failed","reason":"Mela does not import"}'; exit 1; }
echo "{\"status\":\"passed\",\"launcher_sha256\":\"$SHA\"}"
