---
name: run-stage
description: Run a pipeline stage in hep-agentic-pipeline with the correct conda/background idioms — MadGraph generation, Pythia shower, Rivet analysis, OR the SimpleAnalysis/Delphes NATIVE chain (the step-8 default backend). Use when generating events, showering to HepMC, running a Rivet routine, or running a native/container SimpleAnalysis point.
when_to_use: generating events, showering, running Rivet or SimpleAnalysis (native or container), or any long MadGraph/Pythia/Delphes job in hep-agentic-pipeline
allowed-tools: Bash, Read, Edit, Write
---
# Skill — run a pipeline stage

`CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda`. Full domain detail:
`.claude/rules/madgraph-pythia.md`. Long jobs always run in the **background** (`timeout` is
absent here) and buffer to their own log — poll it, don't block. Background long jobs via the harness
`run_in_background`, **NOT** `nohup`/`start_new_session`; a detached job is admissible ONLY with a
`run_state` `compute_launched` entry carrying `logfile`+`done_condition`+`next_action` AND a live
heartbeat (logfile mtime within `DETACH_HEARTBEAT_SECS=600` s) — the Stop dispatcher (`stop_dispatch.py`
`branch_detach`, DETACH/N6) refuses turn-end otherwise (FALLBACK: `workflow_state.py status` lists
detached entries).

## Generate (env `mg5`)
1. Steering `.mg5`: `import model …`, `generate …` (+ `add process … j`/`… j j` if ≥4-jet SRs —
   `workflow/checklists/merging.md`), `output <procdir> -f -nojpeg`.
2. `$CONDA run -n mg5 stages/01-event-generation/build/tools/mg5amcnlo/bin/mg5_aMC <steering.mg5>`
   (the absolute binary path — an env-relative `$CONDA_PREFIX/..` idiom does NOT resolve here).
3. `cp <param_card_copy> <procdir>/Cards/param_card.dat`; edit `run_card.dat` with a **keyed
   Python** edit (not greedy sed): `nevents`, `ebeam1/2`=½√s, `iseed`, `use_syst=False`, and for
   merging `ickkw=1`+`xqcut`. Then `generate_events -f <run>` — **inside the mg5 env**: the
   procdir's `bin/generate_events` outside it fails with exit 0 (the compiler error hides in
   the procdir debug log — FAILURE-CATALOGUE C3).
4. **Verify — mechanically, not by eye**: `Events/<run>/` non-empty (MG can report done with
   an empty events dir), then the MANDATORY pre-shower gate:
   ```bash
   $CONDA run -n rivet python trial-runs/_infrastructure/lhe_check.py \
     <procdir>/Events/<run>/unweighted_events.lhe.gz --expect-mass <PDG>:<mass> [...]
   ```
   It asserts first-event + banner masses (width-aware: the event tolerance auto-widens to 3Γ
   from the banner DECAY table), MODSEL, decay-table structure, weight structure, merged-flag —
   the silent killers (MASS/MSOFT override; width-only DECAY → empty SRs). Never hand-read the
   LHE as the check. Note σ from the banner. The gate always leaves a `<lhe>.lhe_check.json`
   sidecar (verdict earned, never defaulted); shower products without a `verdict=PASS` sidecar
   hard-FAIL `validate_run_state.py`'s `lhe-check-before-shower` invariant, so the gate cannot
   be silently skipped (CR-116).

## Shower (env `rivet`)
- Plain: `$CONDA run -n rivet trial-runs/_infrastructure/pythia_shower <cfg> <out.hepmc> <N>`.
- **Merged (MLM)**: `pythia_shower_merged` with a cfg setting `JetMatching:merge=on scheme=1
  setMad=off qCut≥xqcut nJetMax=2 nQmatch=4` (else qCut defaults to 10 and vetoes everything).
- cfg essentials: `Beams:frameType=4`, `Beams:LHEF=<lhe>`, `SLHA:useDecayTable=on`, `<LSP>:mayDecay=off`.

## Analyze — Option A: Rivet routine (env `rivet`)
- `$CONDA run -n rivet bash -c "cd <rundir>/build && rivet -a <RIVET_ID> <out.hepmc> -o analysis.yoda"`.
- **Single-weight / NOTREENTRY routines** (check `rivet --show-analysis <ID>`): add
  `--skip-weights`, produce one YODA, never reentrant-merge. Confirm the "Only using nominal
  weight" log line.

## Analyze — Option B: SimpleAnalysis (native DEFAULT; container fallback)
- **Native (the step-8 default; scope: `workflow/reference/native-pipeline.md`)** — a single
  point end-to-end:
  ```bash
  python3 trial-runs/_infrastructure/prepare_native_slepton.py --rundir <abs> \
    --m-parent <M> --m-lsp <M> --nevents <N> --toml <config.toml>   # applies run.options (CR-002)
  bash trial-runs/_infrastructure/run-pipeline-native.sh <abs-rundir> <config-rel>
  ```
  The driver chains MadGraph → lhe_check gate → Pythia → Delphes → Delphes2SA → native
  SimpleAnalysis → sa2json → pyhf, writing `logs/STATUS.txt` + `output/exclusion.json`;
  a grid of points goes through `scan_orchestrator.py` (the `run-scan` skill).
  - **Self-catches hangs (G6/D6 CATCH).** Each `run_stage` is wrapped by
    `trial-runs/_infrastructure/stage_supervisor.py` — since `timeout` is absent here, this python
    subprocess supervisor polls wall-clock + progress-stall + exit-0-plausibility against per-stage
    kill thresholds derived from `cost_preflight` (`stage_budget_min`), SIGTERM→SIGKILLs a hung
    stage, writes `logs/<stage>.failure.json` (+ a `next_action`), records the open failure to the
    run ledger (`workflow_state.py record --kind failure`), and returns nonzero so `stage_done`
    writes the FAIL/STOPPED line — no more silently-wedged point holding a scan slot. Set
    `STAGE_SUPERVISED=0` to disable (falls back to the raw subshell; the STATUS.txt contract is
    unchanged either way). A recovered point is reset by removing `logs/STATUS.txt` (or via
    `scan_babysitter.py`'s HEAL loop) so the babysitter re-runs it.
- **Container (legacy, other SA analyses only)**: `run-pipeline.sh` via mapyde/podman —
  ~9 h/point, sequential; see `workflow/analysis-simpleanalysis/`.

Record σ, seeds, tool versions and the σ source in the run's `RESULT.md` — that is the audit's
**R5 provenance** requirement (`framework/STATUS.md` rigor table; scored by `framework/audit.py`).
Then `certify` the run.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "Exit 0 — generation worked" | Catalogue C3: MadGraph reports done with an EMPTY `Events/` (the compiler error hides in the procdir debug log). Verify the dir, then run the gate. |
| "The LHE banner looks right; skip lhe_check this once" | Catalogue C1: width-only DECAY tables shower to EMPTY SRs at exit 0 — only the gate catches it before the shower burns the walltime. |
| "lhe_check FAILed, but it's probably the wide width — override" | Catalogue C2: that false-FAIL class is FIXED (width-aware 3Γ tolerance, CR-007); a remaining FAIL is real. Diagnose, never override. |

## Stop conditions
- `Events/<run>/` empty, or the lhe_check gate FAILs → stop that point; nothing downstream
  (shower/detector/analysis) runs past a failed gate.
- Merged process but the shower cfg lacks the matching block (or `qCut` unset) → stop; the
  plain shower double-counts ME jets and `setMad=on` silently vetoes every event.
