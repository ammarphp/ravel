# Shared helpers for RAVEL's build recipes. Sourced, never executed directly.
# Recipes build into "<target>.partial-<pid>" and rename on success, so a
# failed build never replaces a working one.

ravel_die() { echo "ERROR: $*" >&2; exit 1; }

# Activate a conda environment without conda itself: set the prefix, PATH and
# the compiler variables from its activation scripts.
ravel_activate() {
  local env="$1" script
  [ -d "$env/conda-meta" ] || ravel_die "missing conda environment: $env"
  export CONDA_PREFIX="$env" PATH="$env/bin:$PATH"
  set +u
  for script in "$env"/etc/conda/activate.d/*.sh; do
    [ -f "$script" ] && . "$script"
  done
  set -u
  export CXX="${CXX:-c++}" CC="${CC:-cc}"
}

ravel_jobs() { echo "${RAVEL_JOBS:-${1:-2}}"; }

ravel_finish() {  # ravel_finish <partial> <final>
  [ ! -e "$2" ] || ravel_die "$2 already exists; it was left untouched"
  mv "$1" "$2"
}

ravel_dylib_ext() { if [ "$(uname -s)" = Darwin ]; then echo dylib; else echo so; fi; }
