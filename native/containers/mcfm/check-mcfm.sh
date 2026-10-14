#!/bin/bash
# Installation check for a container-built MCFM binary (no physics inputs needed).
#
# Usage: check-mcfm.sh BUILD_DIR
# Confirms the binary is a Linux ELF for this machine and that every shared
# library resolves inside the image. Prints one JSON line. The physics-level
# check is the amplitude-integration point-oracle operation (see README.md).
set -euo pipefail
BUILD=$1
BIN="$BUILD/ravel_mcfm_amplitudes"
test -x "$BIN" || { echo '{"status":"failed","reason":"binary missing"}'; exit 1; }
ARCH=$(uname -m)
DESCRIPTION=$(file -b "$BIN")
MISSING=$(ldd "$BIN" | grep -c 'not found' || true)
case "$DESCRIPTION" in
  *ELF*) ;; *) echo "{\"status\":\"failed\",\"reason\":\"not an ELF binary\"}"; exit 1 ;;
esac
if [ "$MISSING" != "0" ]; then
  echo "{\"status\":\"failed\",\"reason\":\"$MISSING shared libraries do not resolve\"}"; exit 1
fi
SHA=$(sha256sum "$BIN" | cut -d' ' -f1)
RECEIPT=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["binary_sha256"])' "$BUILD/build-receipt.json")
test "$SHA" = "$RECEIPT" || { echo '{"status":"failed","reason":"binary differs from build receipt"}'; exit 1; }
echo "{\"status\":\"passed\",\"machine\":\"$ARCH\",\"binary_sha256\":\"$SHA\"}"
