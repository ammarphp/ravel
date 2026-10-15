#!/usr/bin/env bash
# Verify that the isolated supplied-event executable loads one Pythia image: the private 8.244 library.
# Fritz must not use Pythia itself. The private Delphes must name one Pythia library, the run paths of the
# process must reach the private prefix first, and that library must define every Pythia8 symbol Delphes needs.
# Static inspection only (otool, nm); nothing is executed. macOS binaries only.
# Usage: check-checkmate-abi.sh --fritz FILE --delphes FILE --pythia PREFIX
set -euo pipefail
EXPECTED=8.244

die() { printf 'checkmate ABI closure: %s\n' "$1" >&2; exit "${2:-1}"; }

FRITZ=""; DELPHES=""; PYTHIA=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --fritz) FRITZ="${2:-}"; shift 2 ;;
    --delphes) DELPHES="${2:-}"; shift 2 ;;
    --pythia) PYTHIA="${2:-}"; shift 2 ;;
    *) die "unknown argument $1" 2 ;;
  esac
done
[ -n "$FRITZ" ] && [ -n "$DELPHES" ] && [ -n "$PYTHIA" ] || die "--fritz, --delphes and --pythia are required" 2
[ "$(uname -s)" = Darwin ] || die "this check reads macOS binaries" 2
[ -f "$FRITZ" ] || die "Fritz is missing: $FRITZ"
[ -f "$DELPHES" ] || die "private Delphes is missing: $DELPHES"
HEADER="$PYTHIA/include/Pythia8/Pythia.h"
LIBRARY="$PYTHIA/lib/libpythia8.dylib"
[ -f "$HEADER" ] || die "Pythia header is missing: $HEADER"
[ -f "$LIBRARY" ] || die "private Pythia library is missing: $LIBRARY"

# The installed 8.2 header writes the version unquoted (#define PYTHIA_VERSION 8.244); accept either form.
version=$(grep -h 'define PYTHIA_VERSION ' "$HEADER" | sed -n 's/.*PYTHIA_VERSION[[:space:]]*"\{0,1\}\([0-9][0-9.]*\)"\{0,1\}.*/\1/p' | head -n 1)
[ "$version" = "$EXPECTED" ] || die "expected Pythia $EXPECTED, got ${version:-none}"

physical() { (cd "$1" 2>/dev/null && pwd -P); }
pythia_images() { otool -L "$1" | awk 'NR > 1 && $1 ~ /libpythia8/ {print $1}' | sort -u; }
run_paths() { otool -l "$1" | awk '$1 == "cmd" {rpath = ($2 == "LC_RPATH")} rpath && $1 == "path" {sub(/^ *path /, ""); sub(/ \(offset [0-9]+\)$/, ""); print}'; }
pythia_undefined() { nm -u "$1" | awk '{print $NF}' | grep 'Pythia8' | sort -u || true; }

[ -z "$(pythia_images "$FRITZ")" ] || die "Fritz links Pythia directly; it must reach Pythia only through the private Delphes"
[ -z "$(pythia_undefined "$FRITZ")" ] || die "Fritz references Pythia8 symbols; it must be built without Pythia"

images=$(pythia_images "$DELPHES")
[ "$(printf '%s\n' "$images" | sed '/^$/d' | wc -l | tr -d ' ')" = 1 ] \
  || die "the private Delphes must name exactly one Pythia image, found: ${images:-none}"

# The loader searches the run paths of the executable first, then those of the library that names the image.
fritz_dir=$(dirname "$FRITZ"); delphes_dir=$(dirname "$DELPHES"); loaded=""
case "$images" in
  @rpath/*)
    while IFS='|' read -r owner path; do
      [ -n "$path" ] || continue
      case "$path" in
        @loader_path*) path="$owner${path#@loader_path}" ;;
        @executable_path*) path="$fritz_dir${path#@executable_path}" ;;
      esac
      if [ -f "$path/${images#@rpath/}" ]; then loaded="$path/${images#@rpath/}"; break; fi
    done <<EOF
$(run_paths "$FRITZ" | sed "s|^|$fritz_dir\||")
$(run_paths "$DELPHES" | sed "s|^|$delphes_dir\||")
EOF
    [ -n "$loaded" ] || die "the Pythia image $images does not resolve through the run paths of Fritz or the private Delphes" ;;
  /*) loaded="$images" ;;
  *) die "unsupported Pythia image name $images" ;;
esac
[ "$(physical "$(dirname "$loaded")")/$(basename "$loaded")" = "$(physical "$PYTHIA/lib")/libpythia8.dylib" ] \
  || die "the process would load a Pythia image outside the private prefix: $loaded"

exported=$(mktemp); needed=$(mktemp); trap 'rm -f "$exported" "$needed"' EXIT
nm -gU "$LIBRARY" | awk '{print $NF}' | sort -u > "$exported"
pythia_undefined "$DELPHES" > "$needed"
unresolved=$(comm -23 "$needed" "$exported")
[ -z "$unresolved" ] || die "unresolved Pythia8 symbols in the private Delphes: $(printf '%s' "$unresolved" | head -n 5 | tr '\n' ' ')"

printf 'checkmate ABI closure passed: Pythia %s\n' "$version"
