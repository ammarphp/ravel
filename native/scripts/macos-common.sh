#!/usr/bin/env bash
# Shared Bash 3.2-compatible checks. Sourcing this file never installs anything.
ravel_macos_arch() {
  local system machine translated silicon major subdir
  system="$(uname -s)"; machine="$(uname -m)"
  [ "$system" = Darwin ] || { echo "ERROR: this provisioning recipe requires macOS, got $system" >&2; return 1; }
  translated="$(sysctl -in sysctl.proc_translated 2>/dev/null || true)"
  silicon="$(sysctl -in hw.optional.arm64 2>/dev/null || true)"
  if [ "$translated" = 1 ] || { [ "$machine" = x86_64 ] && [ "$silicon" = 1 ]; }; then
    echo 'ERROR: Rosetta process detected. Use a native Apple Silicon terminal and Python; do not mix Intel and ARM environments.' >&2
    return 1
  fi
  case "$machine" in arm64) subdir=osx-arm64 ;; x86_64) subdir=osx-64 ;; *) echo "ERROR: unsupported macOS architecture: $machine" >&2; return 1 ;; esac
  major="$(sw_vers -productVersion)"; major="${major%%.*}"
  case "$major" in ''|*[!0-9]*) echo 'ERROR: could not determine macOS version' >&2; return 1 ;; esac
  [ "$major" -ge 11 ] || { echo 'ERROR: these Miniforge recipes require macOS 11 or newer' >&2; return 1; }
  if [ -n "${CONDA_SUBDIR:-}" ] && [ "$CONDA_SUBDIR" != "$subdir" ]; then
    echo "ERROR: CONDA_SUBDIR=$CONDA_SUBDIR conflicts with native $machine" >&2; return 1
  fi
  printf '%s\n' "$machine"
}

ravel_check_macos_binary() {
  local binary="$1" arch="$2" description
  [ -x "$binary" ] || { echo "ERROR: missing executable: $binary" >&2; return 1; }
  description="$(file -b -L "$binary")"
  case "$description" in *Mach-O*) ;; *) echo "ERROR: expected a Mach-O binary: $binary ($description)" >&2; return 1 ;; esac
  case "$description" in *"$arch"*) ;; *) echo "ERROR: $binary does not contain native $arch code ($description)" >&2; return 1 ;; esac
}

ravel_check_conda() {
  local prefix="$1" arch="$2"
  [ -x "$prefix/bin/conda" ] && [ -d "$prefix/conda-meta" ] || {
    echo "ERROR: incomplete Miniforge prefix: $prefix; preserve it and select a new RAVEL_NATIVE_BUILD" >&2; return 1;
  }
  ravel_check_macos_binary "$prefix/bin/python" "$arch"
  # The isolated base interpreter bounds this query even on systems without timeout(1).
  "$prefix/bin/python" -I -B -c '
import os, re, subprocess, sys
try:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.argv[1], "--version"], capture_output=True, text=True, timeout=15, check=True, env=env)
except (OSError, subprocess.SubprocessError) as exc:
    sys.exit("ERROR: conda version probe failed: " + str(exc))
if not re.fullmatch(r"conda \d+\.\d+[^\s]*", result.stdout.strip()):
    sys.exit("ERROR: unrecognized conda version response")
' "$prefix/bin/conda"
}
