---
name: run-stage
description: Run a pipeline stage in hep-agentic-pipeline with the correct conda/background idioms — MadGraph generation, Pythia shower, Rivet analysis, OR the SimpleAnalysis/Delphes NATIVE chain (the step-8 default backend). Use when generating events, showering to HepMC, running a Rivet routine, or running a native/container SimpleAnalysis point.
when_to_use: generating events, showering, running Rivet or SimpleAnalysis (native or container), or any long MadGraph/Pythia/Delphes job in hep-agentic-pipeline
allowed-tools: Bash, Read, Edit, Write
---
# Skill — run a pipeline stage

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.

`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda`. Full domain detail:
`.claude/rules/madgraph-pythia.md`. Long jobs always run in the **background** (`timeout` is
absent here) and buffer to their own log — poll it, don't block. Background long jobs via the harness
`run_in_background`, **NOT** `nohup`/`start_new_session`; a detached job is admissible ONLY with a
`run_state` `compute_launched` entry carrying `logfile`+`done_condition`+`next_action` AND a live
heartbeat (logfile mtime within `DETACH_HEARTBEAT_SECS=600` s) — the Stop dispatcher (`stop_dispatch.py`
`branch_detach`, DETACH/N6) refuses turn-end otherwise (FALLBACK: `workflow_state.py status` lists
detached entries).

## Generate (env `mg5`)
1. Steering `.mg5`: `import model …`, `generate …` (+ `add process … j`/`… j j` if ≥4-jet SRs —
   `docs/workflow/checklists/merging.md`), `output <procdir> -f -nojpeg`.
2. `$CONDA run -n mg5 $RAVEL_NATIVE_BUILD/tools/mg5amcnlo/bin/mg5_aMC <steering.mg5>`
   (the absolute binary path — an env-relative `$CONDA_PREFIX/..` idiom does NOT resolve here).
3. `cp <param_card_copy> <procdir>/Cards/param_card.dat`; edit `run_card.dat` with a **keyed
   Python** edit (not greedy sed): `nevents`, `ebeam1/2`=½√s, `iseed`, `use_syst=False`, and for
   merging `ickkw=1`+`xqcut`. Then `generate_events -f <run>` — **inside the mg5 env**: the
   procdir's `bin/generate_events` outside it fails with exit 0 (the compiler error hides in
   the procdir debug log — FAILURE-CATALOGUE C3).
4. **Verify — mechanically, not by eye**: `Events/<run>/` non-empty (MG can report done with
   an empty events dir), then the MANDATORY pre-shower gate:
   ```bash
   $CONDA run -n rivet python scripts/run.py ravel.validation.lhe_check \
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
- Plain: `$CONDA run -n rivet $RAVEL_NATIVE_BIN/pythia_shower <cfg> <out.hepmc> <N>`.
- **`<N>` is MANDATORY (🔴 silent trap, CR-145)**: with no count (arg or cfg
  `Main:numberOfEvents`), Pythia's default showers exactly **1000** of the LHE's N events with
  exit 0 — per-σ normalization survives, statistics are silently 1000/N. Pass `<N>` = the LHE
  event count AND gate downstream: analyzed-event count must equal the LHE count (the
  campaign-driver hard gate).
- **Merged (MLM)**: `pythia_shower_merged` with a cfg setting `JetMatching:merge=on scheme=1
  setMad=off qCut≥xqcut nJetMax=2 nQmatch=4` (else qCut defaults to 10 and vetoes everything).
- cfg essentials: `Beams:frameType=4`, `Beams:LHEF=<lhe>`, `SLHA:useDecayTable=on`, `<LSP>:mayDecay=off`.

## Analyze — Option A: Rivet routine (env `rivet`)
- `$CONDA run -n rivet bash -c "cd <rundir>/build && rivet -a <RIVET_ID> <out.hepmc> -o analysis.yoda"`.
- **Single-weight / NOTREENTRY routines** (check `rivet --show-analysis <ID>`): add
  `--skip-weights`, produce one YODA, never reentrant-merge. Confirm the "Only using nominal
  weight" log line.

## Analyze — Option B: SimpleAnalysis (native DEFAULT; container fallback)
- **Native (registered model/routine combinations; scope: `docs/workflow/reference/native-pipeline.md`)**:
  ```bash
  python3 scripts/run.py ravel.physics.native_pipeline plan \
    --rundir <abs> --config <config.toml> --write
  # Review the exact plan, pin its path/SHA256 in the task contract, and record
  # the user's actual CHECK-IN 1 approval with workflow_state approve.
  python3 scripts/run.py ravel.physics.native_pipeline run \
    --plan <abs>/inputs/native_execution_plan.json
  ```
  The explicit-card adapter supports declared unmerged LO MSSM families and the actual
  EwkCompressed, eRJR, and zero-lepton routines. The specific slepton template remains a
  separate preparation capability. Required luminosity, PDF/card controls, and correction
  are explicit; missing cross sections never become a numerical default. The LHE rate,
  shower units/count, and converted nominal weights must reconcile.

  Every stage uses the durable supervisor with declared inputs, outputs, and dependencies.
  `execution_state.json` records process ownership, source/runtime hashes, dependency
  receipts, and outputs. Repeating `run --plan` reuses only valid matching stages. Changed
  inputs require a newly reviewed/pinned plan and renewed actual approval. Earlier logs
  and outputs are archived per attempt. MadGraph uses fresh retained working directories
  and stable compressed/unpacked LHE outputs. There is no `STAGE_SUPERVISED=0` fallback.
  Do not remove STATUS, receipts, or intermediate dependencies to force recovery; repair
  the input/tool and resume through the supervisor. Quiet logs alone do not establish a
  hang. Disk estimates must cover retained attempts and their dependencies.

  A scan uses `scan_orchestrator launch --backend native --write-plans` to save proposals,
  `--go` after each point's bound approval, and `--resume --go` for repaired durable failures.
  Yields-only plans end with `native_execution_result.json`; only registered statistical
  adapters also produce `exclusion.json`. Registration and execution success do not certify
  experimental physics or authorize serving an exclusion.
- **Container**: the canonical scan dispatcher emits dry diagnostics only and refuses live
  `--backend container --go` until an exact plan/approval adapter exists. Legacy mapyde
  implementation notes remain in `docs/workflow/analysis-simpleanalysis/`.

Record σ, seeds, tool versions and the σ source in the run's `RESULT.md` — that is the audit's
**R5 provenance** requirement (`docs/development/status.md` rigor table; scored by `scripts/audit.py`).
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
