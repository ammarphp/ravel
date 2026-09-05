#!/usr/bin/env bash
# 03_run_madgraph.sh
# -----------------------------------------------------------------------------
# PURPOSE: The actual event-generation stage. Turns the three "cards" into a
#          parton-level Les Houches Event (LHE) file. Three sub-steps:
#
#   (D) GENERATE PROCESS CODE   mg5_aMC reads the steering script (= the process
#       card with a named output dir). It picks the MSSM model, draws every
#       Feynman diagram for pp -> slepton slepton (+0,1,2 jets), writes Fortran
#       matrix-element code into runs/slepton_200_150/, and AUTO-GENERATES the
#       default run_card.dat + param_card.dat. (This is the "run card generated
#       at runtime" the workflow refers to.)
#
#   (E) INSTALL PHYSICS INPUTS  We overwrite the default param card with the
#       ATLAS 200/150 SLHA card (after normalizing its non-standard DECAY lines
#       so MadGraph's parser accepts it), and edit a handful of run-card knobs.
#
#   (F) GENERATE EVENTS         bin/generate_events compiles the matrix elements
#       with gfortran, integrates the cross-section over phase space (MadEvent),
#       draws unweighted events, and writes Events/<run>/unweighted_events.lhe.gz.
#       With no Pythia/Delphes installed, the chain stops at parton level (LHE).
#
# Re-runnable: pass a run name as $1 (default run_02). The process dir is only
# regenerated if missing.
# -----------------------------------------------------------------------------
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$PROJECT/../native/scripts/paths.sh"
BUILD="${BUILD_DIR:-$RAVEL_NATIVE_BUILD}"   # local-only build area (gitignored); override with BUILD_DIR=...
CONDA="$BUILD/tools/miniforge3/bin/conda"
MG5="$BUILD/tools/mg5amcnlo/bin/mg5_aMC"
PROC="$BUILD/runs/slepton_200_150"
# Original source cards remain provenance-bound; public users supply their own.
CARD_DIR="${RAVEL_CARDS_DIR:-$RAVEL_REPO/stages/01-event-generation/inputs}"
PROCCARD="${RAVEL_PROC_CARD:-$CARD_DIR/proc_card.dat}"
PARAMCARD="${RAVEL_PARAM_CARD:-$CARD_DIR/param_card_200_150.dat}"
for card in "$PROCCARD" "$PARAMCARD"; do
  if [ ! -f "$card" ]; then
    echo "Missing input card: $card" >&2
    echo "Set RAVEL_PROC_CARD and RAVEL_PARAM_CARD to your process and parameter cards." >&2
    exit 2
  fi
done
NORMALIZED="$BUILD/param_card.normalized.dat"
STEER="$BUILD/slepton_generation.generated.mg5" # steering file generated at runtime
RUNNAME="${1:-run_02}"
NEVENTS="${NEVENTS:-1000}"

# ---- (D) Generate the process code + default cards (once) -------------------
# Build the MG5 steering file from the process card, pointing 'output' at $PROC.
# The ONLY edit vs the verbatim process card is naming the output directory, so
# this works regardless of where the build lives (no hard-coded absolute paths).
mkdir -p "$BUILD"
sed "s|^output .*|output ${PROC} -f -nojpeg|" "$PROCCARD" > "$STEER"
if [ ! -f "$PROC/bin/generate_events" ]; then
  echo "[D] Generating process code with mg5_aMC -> $PROC ..."
  # Run from inside $BUILD so MadGraph's PLY cache (py.py) stays in the build area.
  ( cd "$BUILD" && "$CONDA" run -n mg5 python "$MG5" "$STEER" )
else
  echo "[D] Process dir already present -> $PROC (skipping generation)"
fi

# ---- (E) Install the param card (normalized) + edit the run card ------------
echo "[E] Normalizing + installing the ATLAS 200/150 param card ..."
"$CONDA" run -n mg5 python "$PROJECT/scripts/normalize_param_card.py" \
    "$PARAMCARD" \
    "$NORMALIZED"
cp "$NORMALIZED" "$PROC/Cards/param_card.dat"

echo "[E] Setting run-card parameters (name-anchored, robust to defaults) ..."
RC="$PROC/Cards/run_card.dat"
# Edit value-before-'= name'; the trailing '! comment' is preserved.
#  ebeam1/2 (6500), iseed (0), pdlabel (nn23lo1), ptj (20) are already correct
#  in MadGraph's auto-generated default, so only these four are changed:
sed -i.bak \
  -e "s/^[[:space:]]*[0-9]*[[:space:]]*= nevents/  ${NEVENTS} = nevents/" \
  -e "s/^[[:space:]]*[0-9]*[[:space:]]*= ickkw /  0 = ickkw /" \
  -e "s/^[[:space:]]*[0-9.eE+-]*[[:space:]]*= xqcut /  0.0 = xqcut /" \
  -e "s/^[[:space:]]*[A-Za-z]*[[:space:]]*= use_syst/   False = use_syst/" \
  "$RC"
rm -f "$RC.bak"

# ---- (F) Generate events -> LHE ---------------------------------------------
echo "[F] Generating ${NEVENTS} events as '${RUNNAME}' (compile + integrate + unweight) ..."
"$CONDA" run -n mg5 bash -c "cd '$PROC' && ./bin/generate_events -f '$RUNNAME'"

LHE="$PROC/Events/$RUNNAME/unweighted_events.lhe.gz"
echo "[done] LHE written: $LHE"
echo "       events: $(gunzip -c "$LHE" | grep -c '<event>')"
