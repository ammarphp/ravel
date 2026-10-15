#!/bin/bash
# Build JHUGen and MELA inside the toolchain image (run through the container launcher).
#
# Usage: build-jhugen-mela.sh SOURCE_DIR BUILD_DIR BASE_IMAGE_JSON [FETCH_CACHE_DIR]
# The container has no network. FETCH_CACHE_DIR (mounted read-only) holds the files MELA's setup scripts download
# (COLLIER, the precompiled MCFM and MadGraph libraries, the NNPDF grid); wget-from-cache.sh serves them by name.
# SOURCE_DIR receives the two upstream checkouts at the commits recorded in BASE_IMAGE_JSON. The script
# refuses to run while either commit is unrecorded: a build from a moving branch is not reproducible.
# The upstream build steps follow the JHUGen and MELA READMEs; they are confirmed by the first approved
# build, which is why the group is labelled not built until then.
set -euo pipefail
SRC=$1; BUILD=$2; RECORD=$3; CACHE=${4:-}
field() { python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d[sys.argv[2]][sys.argv[3]] or "")' "$RECORD" "$1" "$2"; }
JHUGEN_COMMIT=$(field jhugen commit); MELA_COMMIT=$(field mela commit)
test -n "$JHUGEN_COMMIT" && test -n "$MELA_COMMIT" || { echo "refusing: record the JHUGen and MELA commits in $RECORD first" >&2; exit 2; }
mkdir -p "$SRC" "$BUILD"
fetch() { # name url commit
  test -d "$SRC/$1/.git" || git clone --quiet "$2" "$SRC/$1"
  git -C "$SRC/$1" checkout --quiet "$3"
  test "$(git -C "$SRC/$1" rev-parse HEAD)" = "$3"
}
fetch JHUGen "$(field jhugen repository)" "$JHUGEN_COMMIT"
fetch JHUGenMELA "$(field mela repository)" "$MELA_COMMIT"
( cd "$SRC/JHUGen/JHUGenerator" && make )
# MELA's setup reads ROOTSYS and ROOFITSYS; the image installs ROOT under /usr.
export ROOTSYS=${ROOTSYS:-/usr} ROOFITSYS=${ROOFITSYS:-/usr}
ARCH=${SCRAM_ARCH:-el9_amd64_gcc12}
if [ -n "$CACHE" ]; then
  # Serve downloads from the cache. MELA's precompiled libraries are published for the gcc 12 / EL9 build
  # (el9_amd64_gcc12), the newest set; the image's gcc is newer, so name the set through SCRAM_ARCH.
  shim=$(mktemp -d); ln -s /opt/ravel/bin/wget-from-cache.sh "$shim/wget"
  export PATH="$shim:$PATH" RAVEL_FETCH_CACHE="$CACHE" SCRAM_ARCH=$ARCH
fi
( cd "$SRC/JHUGenMELA/MELA" && ./setup.sh )
cat > "$BUILD/ravel_jhugen_mela" <<LAUNCH
#!/bin/bash
# JHUGen/MELA launcher: library and module paths of this build
export PYTHONPATH="$SRC/JHUGenMELA/MELA/python:\${PYTHONPATH:-}"
export LD_LIBRARY_PATH="$SRC/JHUGenMELA/MELA/data/$ARCH:\${LD_LIBRARY_PATH:-}"
exec python3 "\$@"
LAUNCH
chmod 0755 "$BUILD/ravel_jhugen_mela"
python3 - "$BUILD" "$JHUGEN_COMMIT" "$MELA_COMMIT" <<'PY'
import hashlib, json, sys
build, jhugen, mela = sys.argv[1:4]
digest = hashlib.sha256(open(build + "/ravel_jhugen_mela", "rb").read()).hexdigest()
json.dump({"schema_version": 1, "launcher_sha256": digest, "jhugen_commit": jhugen, "mela_commit": mela},
          open(build + "/build-receipt.json", "w"), indent=2)
PY
