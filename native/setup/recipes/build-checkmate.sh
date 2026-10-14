#!/usr/bin/env bash
# Build Delphes 3.5.1 against Pythia 8.244, then CheckMATE 2 against both.
# CheckMATE needs the Pythia 8.2 interface; Pythia 8.3 is not compatible.
# Usage: build-checkmate.sh --checkmate DIR --delphes-src DIR --delphes-out DIR --pythia ENV
#                           --env ENV --madgraph DIR --jobs N
set -euo pipefail
. "$(dirname "$0")/common.sh"
JOBS=2
while [ $# -gt 0 ]; do case "$1" in
  --checkmate) CM="$2"; shift 2 ;; --delphes-src) DSRC="$2"; shift 2 ;; --delphes-out) DOUT="$2"; shift 2 ;;
  --pythia) PY8="$2"; shift 2 ;; --env) ENV="$2"; shift 2 ;; --madgraph) MG="$2"; shift 2 ;;
  --jobs) JOBS="$2"; shift 2 ;; *) ravel_die "unknown argument $1" ;; esac; done
ravel_activate "$ENV"
if [ "$(uname -s)" = Darwin ]; then
  # Six macOS defects are handled by one compiler wrapper (a temporary script; nothing in the sources changes):
  # 1. conda-forge's libc++ headers mark newer C++ library functions (std::from_chars for floating point) as
  #    unavailable on the SDK's deployment target with an attribute the compiler rejects. The libc++ in the
  #    environment provides the functions, so availability markup is switched off.
  # 2. CheckMATE's configure appends -std=gnu++11, which conda-forge ROOT's headers reject; ROOT 6.40 needs C++20.
  # 3. conda-forge installs the ONNX Runtime headers one level below the include path CheckMATE is given.
  # 4. Some CheckMATE analyses narrow double to float in initializer lists; gcc warns, clang rejects.
  # 5. ROOT's libraries sit in the environment's lib directory next to Pythia 8.3, so the 8.2 library directory is
  #    listed first at link time and added to the run path.
  # 6. Without the environment's activation script CXX falls back to Apple's c++, so the environment's clang is used.
  case "$CXX" in c++|"") real="$ENV/bin/clang++" ;; *) real="${CXX%% *}" ;; esac
  wrapper_dir="$(mktemp -d)"
  cat > "$wrapper_dir/clang++" <<WRAP
#!/bin/sh
for a in "\$@"; do shift; case "\$a" in -std=gnu++11|-std=c++11|-std=gnu++0x|-std=c++0x) a=-std=c++20 ;; esac; set -- "\$@" "\$a"; done
exec "$real" -std=c++20 -D_LIBCPP_DISABLE_AVAILABILITY -Wno-c++11-narrowing -I"$ENV/include/onnxruntime/core/session" -L"$PY8/lib" -Wl,-rpath,"$PY8/lib" -Wno-unused-command-line-argument "\$@"
WRAP
  chmod +x "$wrapper_dir/clang++"
  export CXX="$wrapper_dir/clang++"
fi
[ -x "$PY8/bin/pythia8-config" ] || ravel_die "Pythia 8.244 environment missing: $PY8"
if [ ! -f "$DOUT/libDelphes.so" ]; then
  partial="$DOUT.partial-$$"
  mkdir -p "$partial"
  git -C "$DSRC" archive HEAD | tar -x -C "$partial"
  # conda-forge ROOT depends on Pythia 8.3, so $ENV/include holds 8.3 headers that ROOT's flags put first, and
  # ROOT's Makefile.arch overwrites CXXFLAGS and CXX. Carry the 8.2 include path in the compiler command, which
  # comes first on every compile line, and pass it on the make command line, which wins over the Makefile.
  # On macOS the shared library link does not add Pythia, so the linker command carries it.
  (cd "$partial" && ./configure && make -j"$JOBS" CXX="$CXX -I$PY8/include" \
     LD="$CXX -L$PY8/lib -lpythia8 -Wl,-rpath,$PY8/lib" HAS_PYTHIA8=true PYTHIA8="$PY8")
  ravel_finish "$partial" "$DOUT"
fi
cd "$CM"
autoreconf -i -f
./configure --with-rootsys="$ENV" --with-delphes="$DOUT" --with-hepmc="$ENV" --with-pythia="$PY8" \
  --with-madgraph="$MG" --with-onnx="$ENV" --with-python="$ENV/bin/python"
make -j"$JOBS"
[ -x bin/CheckMATE ] || ravel_die "CheckMATE was not built"
