#!/usr/bin/env bash
# Make a FeynCalc-compatible copy of FeynArts with FeynCalc's FAPatch.
# The original FeynArts tree is kept unchanged. Wolfram is loaded with a
# process-local $Path; no init.m or user setting is written.
# Usage: patch-feynarts.sh --original DIR --patched DIR --feyncalc DIR
set -euo pipefail
. "$(dirname "$0")/common.sh"
while [ $# -gt 0 ]; do case "$1" in
  --original) ORIG="$2"; shift 2 ;; --patched) PATCHED="$2"; shift 2 ;; --feyncalc) FC="$2"; shift 2 ;;
  *) ravel_die "unknown argument $1" ;; esac; done
WS="$(bash "$(dirname "$0")/find-wolframscript.sh")" || ravel_die "no activated Wolfram kernel found"
partial="$PATCHED.partial-$$"
cp -R "$ORIG" "$partial"
rm -f "$partial/.ravel-archive.json"
"$WS" -code "
\$FeynCalcStartupMessages = False;
FeynCalc\`\$FeynArtsDirectory = \"$partial\";
PrependTo[\$Path, \"$FC\"];
Get[\"FeynCalc\`\"];
FAPatch[Quiet -> True];
" </dev/null
grep -q "FeynCalc" "$partial/FeynArts.m" || ravel_die "FAPatch did not patch $partial; see the log above"
ravel_finish "$partial" "$PATCHED"
