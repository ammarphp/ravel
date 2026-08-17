#!/usr/bin/env bash
# run-pipeline-native.sh — VM-FREE native arm64 mapyde pipeline.
#
# Drop-in replacement for run-pipeline.sh: same 2 args, same STATUS.txt format,
# same output/ layout, so scan_orchestrator.py status/launch and the downstream
# harness (pyhf_exclude.py -> exclusion.json, certify, result_pack.py) are
# unchanged. NO podman: every stage runs in a native conda env.
#
#   MadGraph (mg5 env)  ->  Pythia8 shower (rivet env, pythia_shower -> HepMC3)
#   ->  Delphes (recast env, DelphesHepMC3)  ->  Delphes2SA (recast env, ROOT+Delphes)
#   ->  SimpleAnalysis (Mission A/B native SA)  ->  SAtoJSON (rivet env, uproot+pyhf)
#
# Stages MadGraph/Pythia/Delphes/Delphes2SA/SAtoJSON are VERIFIED native and
# (for Delphes2SA + SAtoJSON) bit-for-bit identical to the container. The
# SimpleAnalysis binary is provided by Mission A/B (set SA_BIN below).
#
# Usage: run-pipeline-native.sh <run-dir-abs> <config-file-relative-to-run-dir>
set -uo pipefail
RUNDIR="$1"; CONFIG="$2"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"  # repo root (location-relative)
TOOLS="$REPO/stages/01-event-generation/build/tools"
CONDA="$TOOLS/miniforge3/bin/conda"
MG5="$TOOLS/mg5amcnlo/bin/mg5_aMC"
RECAST="$TOOLS/miniforge3/envs/recast"
INFRA="$REPO/trial-runs/_infrastructure"
MAPYDE_SHARE="$TOOLS/miniforge3/envs/pipeline/share/mapyde"

# SimpleAnalysis is the NATIVE Python+RestFrames port (trial-runs/_infrastructure/
# native_simpleanalysis.py) -- no x86 container, no ATLAS AnalysisBase. It reproduces
# EwkCompressed2018 bit-for-bit (verified: 141/141 SRs, identical pyhf patch). Stage 5
# calls it directly; there is no native `simpleAnalysis` binary to point at.

cd "$RUNDIR" || { echo "bad run dir"; exit 1; }
mkdir -p logs output
STATUS="logs/STATUS.txt"
: > "$STATUS"
echo "pipeline start $(date '+%F %T')  config=$CONFIG  (NATIVE)" | tee -a "$STATUS"

# Read the keys run-pipeline.sh needs out of the mapyde TOML. Stdlib tomllib (py3.11+).
# NB: pass the code via `python -c` (an ARG), NOT a heredoc — `conda run ... <<heredoc`
# does NOT pass stdin to `python -`, so a heredoc silently yields EMPTY output (a
# documented repo gotcha, .claude/rules/madgraph-pythia.md). That bug made every
# TOML-derived var empty and stalled the shower stage with numberOfEvents="".
read_toml() {  # read_toml <dotted.key>
  "$CONDA" run -n pipeline python -c '
import sys, tomllib
cfg = tomllib.load(open(sys.argv[1], "rb"))
cur = cfg
for k in sys.argv[2].split("."):
    cur = cur[k]
print(cur)
' "$CONFIG" "$1"
}
MASS_PARENT=$(read_toml madgraph.masses.MSLEP 2>/dev/null || echo "")
MASS_LSP=$(read_toml madgraph.masses.MN1 2>/dev/null || echo "")
NEVENTS=$(read_toml madgraph.run.nevents)
SEED=$(read_toml madgraph.run.seed)
DELPHES_CARD_NAME=$(read_toml delphes.card)
DELPHES_OUT=$(read_toml delphes.output)                # delphes/delphes.root
ANA_OUT=$(read_toml analysis.output)                   # analysis/Delphes2SA.root
ANA_LUMI=$(read_toml analysis.lumi)                    # pb-1
KFACTOR=$(read_toml analysis.kfactor)
SA_NAME=$(read_toml simpleanalysis.name)               # EwkCompressed2018
PYHF_BKG=$(read_toml pyhf.likelihood)                  # Slepton_bkgonly.json
DELPHES_CARD="$MAPYDE_SHARE/cards/delphes/$DELPHES_CARD_NAME"
BKG_JSON="$MAPYDE_SHARE/likelihoods/$PYHF_BKG"

stage_start() { echo "===== STAGE $1 START $(date '+%T') =====" | tee -a "$STATUS"; }
stage_done()  { # <name> <rc> <secs>
  if [ "$2" -eq 0 ]; then echo "PASS  $1  ($3s)" | tee -a "$STATUS"
  else echo "FAIL  $1  rc=$2  ($3s) -> logs/$1.log" | tee -a "$STATUS"
       echo "STOPPED at stage: $1" | tee -a "$STATUS"; exit "$2"; fi
}
run_stage() { # <name> <command...>  -> logs to logs/<name>.log, records PASS/FAIL+secs
  local name="$1"; shift
  stage_start "$name"; local t0; t0=$(date +%s); local rc
  if [ "${STAGE_SUPERVISED:-1}" = "1" ] && [ -f "$INFRA/stage_supervisor.py" ] && command -v python3 >/dev/null 2>&1; then
    python3 "$INFRA/stage_supervisor.py" --stage "$name" --rundir "$RUNDIR" \
      --events "${NEVENTS:-0}" --log "logs/${name}.log" -- "$@"; rc=$?
  else
    ( "$@" ) > "logs/${name}.log" 2>&1; rc=$?
  fi
  stage_done "$name" "$rc" "$(( $(date +%s) - t0 ))"
}

# ---- 1. madgraph (LHE only; native mg5_aMC in mg5 env) -----------------------
# Uses the same param/run cards mapyde's madgraph.generate_mg5config would build,
# materialised under output/ by a small helper (mass substitution from the TOML).
run_stage madgraph "$CONDA" run -n mg5 "$MG5" "output/run.mg5"
LHE="output/PROC_madgraph/Events/run_01/unweighted_events.lhe"
[ -s "${LHE}.gz" ] && gunzip -f "${LHE}.gz"

# ---- 1b. PRE-SHOWER GATE: lhe_check (gate map, charter 4b; FAILURE-CATALOGUE C1/C2) ------
# Mandatory before ANY shower time: masses vs the TOML's intent, decay-table structure,
# weight structure. A width-only DECAY table or a wrong MSOFT-derived spectrum is a silent
# exit-0 killer downstream (empty SRs). Nonzero exit STOPs the point via stage_done.
GATE_ARGS=()
[ -n "$MASS_PARENT" ] && GATE_ARGS+=(--expect-mass "1000011:$MASS_PARENT")
[ -n "$MASS_LSP" ]    && GATE_ARGS+=(--expect-mass "1000022:$MASS_LSP")
# CR-005: the 1000011/1000022 mapping above is slepton-specific. A point whose TOML carries no
# [madgraph.masses] derives its expectations from the rendered param card itself instead
# (CR-021 --expect-from-card) — the gate stays STRONG for any process, never silently weaker.
if [ ${#GATE_ARGS[@]} -eq 0 ] && [ -f "output/param_card.dat" ]; then
  GATE_ARGS+=(--expect-from-card "output/param_card.dat")
fi
# ${arr[@]+...} idiom: bash 3.2 (this macOS) errors on empty-array expansion under set -u
run_stage lhe_check "$CONDA" run -n rivet python "$INFRA/lhe_check.py" "$LHE" \
    ${GATE_ARGS[@]+"${GATE_ARGS[@]}"}

# ---- 2. pythia shower (rivet env -> HepMC3) ----------------------------------
HEPMC="output/madgraph/tag_1_pythia8_events.hepmc"
mkdir -p "$(dirname "$HEPMC")"
run_stage pythia "$CONDA" run -n rivet "$INFRA/pythia_shower" \
    "output/shower.cfg" "$HEPMC" "$NEVENTS"

# ---- 3. delphes (recast env; DelphesHepMC3 reads the HepMC3 from pythia_shower) -
mkdir -p "output/$(dirname "$DELPHES_OUT")"
rm -f "output/$DELPHES_OUT"
run_stage delphes "$CONDA" run -n recast "$RECAST/bin/DelphesHepMC3" \
    "$DELPHES_CARD" "output/$DELPHES_OUT" "$HEPMC"

# ---- 4. analysis = Delphes2SA (recast env; bit-identical to container) --------
# XS comes from the MadGraph log (Cross-section), x kfactor — same logic as
# runner.run_ana. Parse it from logs/madgraph.log.
XS=$("$CONDA" run -n pipeline python -c '
import sys, re
xs = 1000.0
for line in open(sys.argv[1], errors="ignore"):
    m = re.search(r"Cross-section\s*:\s*([0-9.eE+-]+)", line)
    if m: xs = float(m.group(1))
print(xs * float(sys.argv[2]))
' "logs/madgraph.log" "$KFACTOR")
mkdir -p "output/$(dirname "$ANA_OUT")"
run_stage analysis "$CONDA" run -n recast python "$INFRA/delphes2sa_native.py" \
    --input "output/$DELPHES_OUT" --output "output/$ANA_OUT" \
    --lumi "$ANA_LUMI" --XS "$XS"

# ---- 5. simpleanalysis (NATIVE Python+RestFrames port; no container/AnalysisBase) -
# native_simpleanalysis.py reproduces EwkCompressed2018 bit-for-bit (141/141 SRs) and
# emits EwkCompressed2018.{txt,root}: the .txt (unweighted counts+acceptance) for the
# acc x eff cert, the .root (per-SR eventWeight ntuple + isee/ismm) for sa2json. It
# computes R_ISR/M_S via the native rjr_resolve (recast env) on its own signalJets --
# no container values. --ngen is the generated-event denominator for acceptance.
run_stage simpleanalysis "$CONDA" run -n rivet python "$INFRA/native_simpleanalysis.py" \
    --input "output/$ANA_OUT" --output "output" --ngen "$NEVENTS"

# ---- 6. sa2json (rivet env; bit-identical to container w/ float() cast) -------
# Use the float()-cast wrapper sa2json_native.py (numpy>=2 returns float32 which
# the stock mapyde SAtoJSON cannot JSON-serialise under py3.14).
PATCH_OUT="output/${SA_NAME}_patch.json"
run_stage sa2json "$CONDA" run -n rivet python "$INFRA/sa2json_native.py" \
    -i "output/${SA_NAME}.root" -o "$PATCH_OUT" -n output \
    -b "$BKG_JSON" -l "$ANA_LUMI" -c

# ---- 7. pyhf exclusion (harness limit-setter -> exclusion.json) --------------
# The harness uses its OWN pyhf_exclude.py (true CLs=0.05 crossing), not mapyde's
# fixed-grid muscan.py. result_pack.py then assembles result.json from
# exclusion.json + sr_yields.json + provenance.json + cert json.
run_stage pyhf "$CONDA" run -n rivet python "$INFRA/pyhf_exclude.py" likelihood \
    --bkg "$BKG_JSON" --patch "$PATCH_OUT" --out "output"

echo "ALL_STAGES_COMPLETE $(date '+%F %T')" | tee -a "$STATUS"
