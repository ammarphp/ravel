#!/usr/bin/env bash
# Run the full mapyde pipeline stage-by-stage with per-stage logs + a STATUS file.
# Usage: run-pipeline.sh <run-dir-abs> <config-file-relative-to-run-dir>
# Requires: podman machine 'mg-vm' running; images pulled.
set -uo pipefail
RUNDIR="$1"; CONFIG="$2"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"  # repo root (location-relative)
source "$REPO/trial-runs/_infrastructure/pipeline-env.sh"
cd "$RUNDIR" || { echo "bad run dir"; exit 1; }
export PWD="$RUNDIR"
mkdir -p logs
STATUS="logs/STATUS.txt"
: > "$STATUS"
echo "pipeline start $(date '+%F %T')  config=$CONFIG" | tee -a "$STATUS"

# Remove any stale mapyde containers from a previous (e.g. interrupted) run, since
# mapyde reuses fixed per-stage container names (output__mgpy, ...) which would collide.
podman rm -f $(podman ps -aq) >/dev/null 2>&1 || true

# Full detector-level chain (SimpleAnalysis path): pyhf consumes the sa2json patch,
# which needs simpleanalysis, which reads analysis/Delphes2SA.root.
stages=(madgraph delphes analysis simpleanalysis sa2json pyhf)
for s in "${stages[@]}"; do
  echo "===== STAGE $s START $(date '+%T') =====" | tee -a "$STATUS"
  t0=$(date +%s)
  mapyde run "$s" "$CONFIG" > "logs/${s}.log" 2>&1
  rc=$?
  t1=$(date +%s)
  if [ $rc -eq 0 ]; then
    echo "PASS  $s  ($((t1-t0))s)" | tee -a "$STATUS"
  else
    echo "FAIL  $s  rc=$rc  ($((t1-t0))s) -> logs/${s}.log" | tee -a "$STATUS"
    echo "STOPPED at stage: $s" | tee -a "$STATUS"
    exit $rc
  fi
  if [ "$s" = "madgraph" ]; then
    # LHE GATE (gate map, charter 4b; FAILURE-CATALOGUE C1): mapyde's madgraph stage fuses
    # generation+shower in one container, so the check runs here -- it still stops a bad
    # spectrum / width-only decay table before detector/analysis/stats consume it.
    LHE_GZ="output/madgraph/PROC_madgraph/Events/run_01/unweighted_events.lhe.gz"
    echo "===== GATE lhe_check $(date '+%T') =====" | tee -a "$STATUS"
    "$TOOLS/miniforge3/bin/conda" run -n rivet python \
        "$REPO/trial-runs/_infrastructure/lhe_check.py" "$LHE_GZ" > logs/lhe_check.log 2>&1
    grc=$?
    if [ $grc -eq 0 ]; then
      echo "PASS  lhe_check" | tee -a "$STATUS"
    else
      echo "FAIL  lhe_check  rc=$grc -> logs/lhe_check.log" | tee -a "$STATUS"
      echo "STOPPED at gate: lhe_check" | tee -a "$STATUS"
      exit $grc
    fi
  fi
done
echo "ALL_STAGES_COMPLETE $(date '+%F %T')" | tee -a "$STATUS"
