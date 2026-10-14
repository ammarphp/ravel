#!/usr/bin/env bash
# Print the path of a working, activated wolframscript and exit 0; otherwise exit 1.
# Reads the kernel version only. It never activates Wolfram or changes its settings.
set -u
candidates=()
command -v wolframscript >/dev/null 2>&1 && candidates+=("$(command -v wolframscript)")
for pattern in /Applications/Wolfram*.app/Contents/MacOS/wolframscript \
               /Applications/Mathematica*.app/Contents/MacOS/wolframscript \
               /usr/local/Wolfram/*/*/Executables/wolframscript /usr/local/Wolfram/*/Executables/wolframscript \
               /opt/Wolfram/*/*/Executables/wolframscript; do
  for path in $pattern; do [ -x "$path" ] && candidates+=("$path"); done
done
for ws in ${candidates[@]+"${candidates[@]}"}; do
  version="$("$ws" -code '$VersionNumber' </dev/null 2>/dev/null || true)"
  case "$version" in [0-9]*) echo "$ws"; exit 0 ;; esac
done
exit 1
