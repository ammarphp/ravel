#!/usr/bin/env bash
# Build native (arm64) crogan/RestFrames v1.0.1 against the recast-env ROOT 6.40.
#
# The install (lib/libRestFrames.dylib + include/RestFrames/*.hh) lands under
#   stages/01-event-generation/build/tools/restframes-native/
# which is gitignored + regenerable (per repo convention). Run this once to
# (re)create it, then build the resolver with rjr_resolve_build.sh.
#
# Usage (no conda env needed up front; the script uses `conda run -n recast`):
#   bash native/scripts/restframes-native-build.sh
#
# Why this script and not the bundled autotools `make`:
#   1. The 2016 config.guess/config.sub in the tarball don't recognise
#      aarch64-apple-darwin -> we swap in the recast-env automake-1.17 copies.
#   2. ROOT 6.40's rootcling rejects the old Makefile's `-s lib.so -rml -rmf`
#      grouping ("-s option may not occur within a group"). The ROOT dictionary
#      is only needed for TTree streaming of RestFrames objects, which the
#      standalone resolver never does -> we skip the dict and compile the 52
#      .cc sources straight into a .dylib.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO/native/scripts/paths.sh"
CONDA="$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda"
RECAST="$RAVEL_NATIVE_BUILD/tools/miniforge3/envs/recast"
TARBALL="$RAVEL_NATIVE_BUILD/tools/simple-analysis-src/Ext_RestFrames/data/tarball"
INSTALL="$RAVEL_NATIVE_BUILD/tools/restframes-native"

WORK="$(mktemp -d /tmp/rf_build.XXXXXX)"
echo "Work dir: $WORK"
tar xzf "$TARBALL" -C "$WORK"
SRC="$WORK/RestFrames-1.0.1"

# 1. modern config.guess/config.sub
AUX="$RECAST/share/automake-1.17"
cp "$AUX/config.guess" "$SRC/config.guess"
cp "$AUX/config.sub"   "$SRC/config.sub"
cp "$AUX/config.guess" "$SRC/config/config.guess" 2>/dev/null || true
cp "$AUX/config.sub"   "$SRC/config/config.sub"   2>/dev/null || true

# 2. configure (generates inc/RestFrames headers + Makefiles)
ROOTSYS="$("$CONDA" run -n recast root-config --prefix)"
( cd "$SRC" && "$CONDA" run -n recast ./configure \
    --prefix="$INSTALL" --enable-shared --disable-static \
    --with-rootsys="$ROOTSYS" )

# 3. compile the 52 sources -> dylib (skip the broken rootcling dict step)
mkdir -p "$INSTALL/lib" "$INSTALL/include"
cat > "$WORK/compile.sh" <<'CEOF'
set -e
SRC="$1"; INSTALL="$2"
cd "$SRC"
CXX=$(root-config --cxx)
mkdir -p obj
for f in src/*.cc; do
  base=$(basename "$f" .cc)
  [ "$base" = "libRestFrames_rdict" ] && continue
  $CXX $(root-config --cflags) -fPIC -I./inc -c "$f" -o "obj/$base.o"
done
$CXX -dynamiclib -install_name "$INSTALL/lib/libRestFrames.dylib" \
  -o "$INSTALL/lib/libRestFrames.dylib" obj/*.o $(root-config --libs)
CEOF
"$CONDA" run -n recast bash "$WORK/compile.sh" "$SRC" "$INSTALL"

# 4. headers
cp -r "$SRC/inc/RestFrames" "$INSTALL/include/"

echo "Native RestFrames installed at: $INSTALL"
"$CONDA" run -n recast otool -D "$INSTALL/lib/libRestFrames.dylib"
echo "  ($(ls "$INSTALL/include/RestFrames"/*.hh | wc -l | tr -d ' ') headers)"
rm -rf "$WORK"
