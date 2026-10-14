#!/usr/bin/env bash
# One-command RAVEL installer.
#
#   bash scripts/setup/install.sh                    # everything for this machine
#   bash scripts/setup/install.sh --profile site     # a Linux analysis facility
#   bash scripts/setup/install.sh --plan             # show what would happen
#   bash scripts/setup/install.sh --help
#
# This script checks the machine, installs a pinned Miniforge into the RAVEL
# prefix (no Python needed beforehand), then hands over to install.py with the
# same arguments. It never edits your shell start-up files, conda settings,
# container settings in your home directory, Wolfram settings or agent settings.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MINIFORGE_VERSION=26.5.3-0
PROFILE=default
PREFIX_ARG=""
CHECK_DISK=1
PREFLIGHT_ONLY=0
PLAN=0
OFFLINE=0
ARGS=()

usage() {
  cat <<'EOF'
Usage: bash scripts/setup/install.sh [options]

  --profile NAME       site (Linux analysis facility); omit for the default toolchain
  --only GROUPS        install only these groups (comma-separated) and what they need
  --skip GROUPS        leave these groups out
  --prefix PATH        where tools go (default: native/build inside this checkout)
  --plan               print the ordered steps and change nothing
  --dry-run            print every action, size estimate and network fetch, and change nothing
  --resume             continue after a failure; finished steps are skipped
  --offline            use only the download cache
  --adopt              keep existing environments and checkouts in the prefix as they are
  --jobs N             build parallelism (default: half the cores)
  --accept-licenses    accept the upstream licences without asking
  --no-disk-check      skip the free-space check
  --preflight-only     run the machine checks and stop

After installing, check everything with: .venv/bin/ravel doctor
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --profile) PROFILE="${2:?--profile needs a name}"; ARGS+=("$1" "$2"); shift 2 ;;
    --profile=*) PROFILE="${1#*=}"; ARGS+=("$1"); shift ;;
    --prefix) PREFIX_ARG="${2:?--prefix needs a path}"; shift 2 ;;
    --prefix=*) PREFIX_ARG="${1#*=}"; shift ;;
    --no-disk-check) CHECK_DISK=0; shift ;;
    --preflight-only) PREFLIGHT_ONLY=1; shift ;;
    --plan|--dry-run) PLAN=1; ARGS+=("$1"); shift ;;
    --offline) OFFLINE=1; ARGS+=("$1"); shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

say() { printf '%s\n' "$*"; }
fail() { printf 'install: %s\n' "$*" >&2; exit "${2:-1}"; }

# ---------------------------------------------------------------- platform
SYSTEM="$(uname -s)"
MACHINE="$(uname -m)"
case "$SYSTEM" in
  Darwin)
    if [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || echo 0)" = 1 ]; then
      fail "this terminal runs under Rosetta (Intel emulation). Open a native Apple-silicon terminal and rerun." 3
    fi
    case "$MACHINE" in
      arm64) PLATFORM=macos-arm64; ASSET=Miniforge3-$MINIFORGE_VERSION-MacOSX-arm64.sh
             SHA=0d765919d3ccfd1f89147aa1cf8133bfc55b3a3c13f5bacdcc091c33132fddd2 ;;
      x86_64) PLATFORM=macos-x86_64; ASSET=Miniforge3-$MINIFORGE_VERSION-MacOSX-x86_64.sh
              SHA=0266a7bfeb12165286133145717bef0d88070f1b76710beb6a62fec4e88371a1 ;;
      *) fail "unsupported Mac architecture $MACHINE" 3 ;;
    esac ;;
  Linux)
    case "$MACHINE" in
      x86_64) PLATFORM=linux-x86_64; ASSET=Miniforge3-$MINIFORGE_VERSION-Linux-x86_64.sh
              SHA=14db468222ad564658656f769506056209b6dc375f5e7dfd31eb5ebbf08fa529 ;;
      aarch64|arm64) PLATFORM=linux-aarch64; ASSET=Miniforge3-$MINIFORGE_VERSION-Linux-aarch64.sh
              SHA=0391e42075a7632e9665d6e728387ee6b905f6c3e704d3513e1c1133d0d69b89 ;;
      *) fail "unsupported Linux architecture $MACHINE" 3 ;;
    esac ;;
  *) fail "RAVEL installs on macOS or Linux; this is $SYSTEM" 3 ;;
esac

# ---------------------------------------------------------------- tools
for tool in curl git tar; do
  command -v "$tool" >/dev/null 2>&1 || fail "the '$tool' command is required; install it and rerun" 3
done
GIT_VERSION="$(git --version)" || fail "cannot read git --version; install a newer git" 3
GIT_NUMBER="$(printf '%s\n' "$GIT_VERSION" | awk '{print $3}')"
GIT_MAJOR="${GIT_NUMBER%%.*}"
GIT_REST="${GIT_NUMBER#*.}"
GIT_MINOR="${GIT_REST%%.*}"
case "$GIT_MAJOR:$GIT_MINOR" in
  *[!0-9:]*|:*) fail "cannot parse $GIT_VERSION; install a newer git" 3 ;;
esac
if [ "$GIT_MAJOR" -lt 2 ] || { [ "$GIT_MAJOR" -eq 2 ] && [ "$GIT_MINOR" -lt 19 ]; }; then
  fail "$GIT_VERSION is too old; git 2.19 or newer is required. On macOS put Apple's git first with PATH=/usr/bin:\$PATH, or install a newer git." 3
fi
if command -v shasum >/dev/null 2>&1; then SHACMD=(shasum -a 256)
elif command -v sha256sum >/dev/null 2>&1; then SHACMD=(sha256sum)
else fail "shasum or sha256sum is required" 3; fi

if [ "$SYSTEM" = Darwin ]; then
  xcode-select -p >/dev/null 2>&1 || fail "the Xcode Command Line Tools are missing. Run 'xcode-select --install', \
wait for it to finish, then rerun this command." 3
  if [ "$PLATFORM" = macos-arm64 ] && ! /usr/bin/arch -x86_64 /usr/bin/true >/dev/null 2>&1; then
    say "note: Rosetta 2 is not installed. The CMS Combine and ATLAS SimpleAnalysis images need it;"
    say "      run 'softwareupdate --install-rosetta' yourself when convenient (ravel doctor will remind you)."
  fi
fi

# ---------------------------------------------------------------- prefix
if [ -n "$PREFIX_ARG" ]; then PREFIX="$PREFIX_ARG"
elif [ -n "${RAVEL_NATIVE_BUILD:-}" ]; then PREFIX="$RAVEL_NATIVE_BUILD"
elif [ -f "$REPO/.ravel/native-prefix" ]; then PREFIX="$(head -n 1 "$REPO/.ravel/native-prefix")"
elif [ -d "$REPO/stages/01-event-generation/build" ]; then PREFIX="$REPO/stages/01-event-generation/build"
else PREFIX="$REPO/native/build"; fi
case "$PREFIX" in "~"*) PREFIX="$HOME${PREFIX#\~}" ;; esac
case "$PREFIX" in /*) ;; *) PREFIX="$(pwd)/$PREFIX" ;; esac
case "$PREFIX" in *[[:space:]]*) fail "the prefix '$PREFIX' contains a space, which Miniforge refuses; choose another with --prefix" 3 ;; esac

# ---------------------------------------------------------------- disk
# Fixed-format JSON: the default target is the top-level "default" object (header one space,
# disk_gb two); a named profile sits under "profiles" (header two spaces, disk_gb three).
# This is the manifest's value; preflight requires no Python interpreter.
case "$PROFILE" in
  default) HEADER=' "default": {'; FIELD='^  "disk_gb":'; CLOSE='^ }' ;;
  *) HEADER="  \"$PROFILE\": {"; FIELD='^   "disk_gb":'; CLOSE='^  }' ;;
esac
DISK_GB="$(awk -v header="$HEADER" -v field="$FIELD" -v close_="$CLOSE" '
  $0 == header { selected=1; next }
  selected && $0 ~ field { value=$2; sub(/,$/, "", value); print value; exit }
  selected && $0 ~ close_ { exit }
' "$REPO/native/setup/toolchain-manifest.json")"
case "$DISK_GB" in
  ''|*[!0-9.]*|*.*.*|.*|*.) fail "unknown profile $PROFILE, or it has no numeric disk_gb in native/setup/toolchain-manifest.json; choose site, or omit --profile" 2 ;;
esac
# The free-space comparison is in whole GB, rounded up.
NEED_GB="${DISK_GB%%.*}"
case "$DISK_GB" in *.*[1-9]*) NEED_GB=$((NEED_GB + 1)) ;; esac
probe_dir="$PREFIX"
while [ ! -d "$probe_dir" ]; do probe_dir="$(dirname "$probe_dir")"; done
FREE_KB="$(df -Pk "$probe_dir" | awk 'NR==2 {print $4}')"
FREE_GB=$(( ${FREE_KB:-0} / 1024 / 1024 ))
say "RAVEL installer: $PLATFORM, target $PROFILE, prefix $PREFIX ($FREE_GB GB free, about $DISK_GB GB needed)"
if [ "$CHECK_DISK" = 1 ] && [ "$PLAN" = 0 ] && [ "$FREE_GB" -lt "$NEED_GB" ]; then
  fail "not enough free disk space for the $PROFILE target ($FREE_GB GB free, about $DISK_GB GB needed).
Choose a larger volume with --prefix /path/on/that/volume,
or keep an existing toolchain with --adopt --prefix /path/to/it. Use --no-disk-check to proceed anyway." 4
fi
[ "$PREFLIGHT_ONLY" = 1 ] && { say "preflight: ok"; exit 0; }

# ---------------------------------------------------------------- Miniforge
MF="$PREFIX/tools/miniforge3"
if [ -x "$MF/bin/python" ] && [ -x "$MF/bin/conda" ]; then
  say "Miniforge: using $MF"
elif [ "$PLAN" = 1 ]; then
  say "Miniforge $MINIFORGE_VERSION would be installed into $MF (sha256 $SHA)."
  say "  network fetch: https://github.com/conda-forge/miniforge/releases/download/$MINIFORGE_VERSION/$ASSET"
  command -v python3 >/dev/null 2>&1 || exit 0
  # Before Miniforge exists the step list is printed by the python3 on PATH, which must be 3.11 or newer.
  if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
    say "The step list needs Python 3.11 or newer, and the python3 on PATH is older."
    say "Install as usual (the installer brings its own Python), or put a newer python3 first on PATH and rerun."
    exit 0
  fi
  exec python3 -I -B "$REPO/scripts/setup/install.py" --prefix "$PREFIX" ${ARGS[@]+"${ARGS[@]}"}
else
  [ ! -e "$MF" ] || fail "$MF exists but has no working conda; move it aside and rerun" 5
  CACHE="$PREFIX/downloads/sha256"
  mkdir -p "$CACHE" "$PREFIX/downloads/quarantine" "$PREFIX/downloads/tmp"
  if [ ! -f "$CACHE/$SHA" ]; then
    [ "$OFFLINE" = 0 ] || fail "offline: the Miniforge installer $ASSET is not in the download cache ($CACHE/$SHA); place it there or rerun without --offline" 5
    URL="https://github.com/conda-forge/miniforge/releases/download/$MINIFORGE_VERSION/$ASSET"
    TMP="$PREFIX/downloads/tmp/$ASSET.$$"
    say "Downloading $ASSET"
    curl --proto '=https' --tlsv1.2 -fL --retry 3 -o "$TMP" "$URL" || fail "download failed: $URL" 5
    ACTUAL="$("${SHACMD[@]}" "$TMP" | awk '{print $1}')"
    if [ "$ACTUAL" != "$SHA" ]; then
      mv "$TMP" "$PREFIX/downloads/quarantine/$ASSET.$ACTUAL"
      fail "Miniforge checksum mismatch (expected $SHA, got $ACTUAL). The file was quarantined and not run." 5
    fi
    mv "$TMP" "$CACHE/$SHA"
  fi
  say "Installing Miniforge $MINIFORGE_VERSION into $MF"
  # Upstream's installer refuses to run unless its own file name ends in .sh, and the cache is named by checksum.
  LAUNCH="$PREFIX/downloads/tmp/Miniforge-install.$$.sh"
  ln -s "$CACHE/$SHA" "$LAUNCH"
  bash "$LAUNCH" -b -p "$MF" || { rm -f "$LAUNCH"; fail "the Miniforge installer failed" 5; }
  rm -f "$LAUNCH"
  printf '%s  %s\n' "$SHA" "$ASSET" > "$MF/ravel-bootstrap.sha256"
fi

exec "$MF/bin/python" -I -B "$REPO/scripts/setup/install.py" --prefix "$PREFIX" ${ARGS[@]+"${ARGS[@]}"}
