#!/bin/bash
# Stand-in for wget inside the network-less build container. MELA's setup scripts call wget for COLLIER,
# the precompiled MCFM and MadGraph libraries and the NNPDF grid. The host fetches those files once, records
# their digests, and mounts the directory named by RAVEL_FETCH_CACHE; this script serves them by file name
# and fails for anything else, so a build can never reach the network or pick up an unrecorded file.
set -euo pipefail
cache=${RAVEL_FETCH_CACHE:?RAVEL_FETCH_CACHE names the directory of pre-fetched files}
out=""
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -O) out=$2; shift 2 ;;
    -*) shift ;;
    *) url=$1; shift ;;
  esac
done
name=$(basename "${url%%\?*}")
test -n "$name" && test -f "$cache/$name" || { echo "wget-from-cache: $name is not in $cache" >&2; exit 8; }
cp "$cache/$name" "${out:-$name}"
