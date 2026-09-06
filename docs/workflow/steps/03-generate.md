# Step 3 — Generate events  ·  [judgment] cards / [agent] run

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

Produce showered events (HepMC) for the model. `MG=$RAVEL_NATIVE_BUILD/tools/mg5amcnlo/bin/mg5_aMC`

**Pre-generate recipe gate ([judgment — script-assisted: resource_census.py], mandatory before any
`generate_events`).** For a BSM/HV model you may NOT run the hard process until the model's external
generation recipe (UFO / restrict card / process syntax) has been fetched and recorded. Fetch it with
`resource_census.py --debug recipe-search --tool madgraph --model <model>` (writes
`inputs/recipe_search.json`) or hand-record `inputs/generation_recipe.json`, then assert:
`$CONDA run -n rivet python scripts/run.py ravel.workflow.resource_census --assert-pre-generate
--rundir <rundir>` — nonzero exit = fetch the recipe first. A PostToolUse guard
(`.claude/hooks/pre-generate-guard.sh`) backstops this on a raw `mg5`/`run-pipeline-native.sh` launch.

1. **Hard process (MadGraph → LHE).** Steering script = the process card with an `output <dir>` line:
   ```bash
   $CONDA run -n mg5 python $MG <steering.mg5>                 # writes the process dir
   cp <param_card> <procdir>/Cards/param_card.dat             # set masses/decays
   # Run-card edits: a KEYED PYTHON replace, never sed (a greedy sed silently misses — an iseed
   # sed miss was observed in the field). Snippet + field table: checklists/generation-settings.md.
   # Set: nevents · ebeam1/2 (= HALF the routine's sqrt(s): 6500 -> 13 TeV) · an explicit iseed
   # (reproducibility) · use_syst=False (single nominal weight — the pipeline norm).
   $CONDA run -n mg5 bash -c "cd <procdir> && ./bin/generate_events -f run01"
   ```
   The generation √s **must match the routine's beam energy** (`02-inputs.md`); more in
   `docs/workflow/checklists/generation-settings.md`. Note σ ± its integration error from the run banner and
   record it with the PDF/scale settings in `provenance.json` (the checklist lists the fields).
   (MadGraph resets `iseed` to 0 in the run card after each run — re-set it before another run; the
   seed actually used is recorded in the banner.)

   **Statistics sizing ([judgment — proceed-with-flag]: the ≥25-raw-events rule below is the safe default; size by it, flag it).** With 10k events a tail SR holding 2–5 raw events carries a
   45–70% MC statistical error — unusable for certification. Scale `nevents` so the **weakest SR
   you intend to certify** holds ≥25 raw events (≲20% MC error), or declare those SRs
   **report-only** (the cert's tail tier, `validate_cutflow.py`).

   **Radiation and merging review.** Read the publication's generator, multiplicities, PDF,
   shower, tune and matching prescription, and identify how recoil enters the selection.
   A lepton or monojet label does not justify skipping this review. Declare the chosen
   approximation in `RESULT.md`; test generation-cut dependence and relevant rate/shape
   changes with their uncertainties. Follow [the merging checklist](../checklists/merging.md)
   for the separate MLM and CKKW-L requirements. Do not reuse the historical example's scale
   or its 5% inclusive-rate comparison as a universal gate. The explicit-card native adapter
   currently rejects merged samples pending audited veto/weight accounting; do not bypass it.
   **Pre-shower guard (always, before any shower time):**
   `$CONDA run -n rivet python scripts/run.py ravel.validation.lhe_check <procdir>/Events/run01/unweighted_events.lhe.gz --expect-mass <PDG>:<mass> …`
   — asserts the generated particle masses (first event + banner MASS block; catches the
   wrong-card/model-interface failures), checks weight sign + multiweight tags + `MODSEL` presence, and
   reports merged-vs-unmerged (ickkw) so the right shower bridge is used. Nonzero exit = fix the
   cards before showering. This is the **mandatory pre-shower gate** for every LHE, merged or not —
   it is also what catches a multiweight (`use_syst=True`) LHE before it leaks into the
   single-weight analysis path. The gate ALWAYS writes a JSON sidecar (`<lhe>.lhe_check.json`,
   `--json-out` overrides) with the earned verdict, and `validate_run_state.py`'s
   `lhe-check-before-shower` invariant FAILs any run whose shower products (`*.hepmc[.gz]`) lack a
   `verdict=PASS` sidecar — skipping the guard is a lifecycle FAIL, not a silent omission (CR-116).

   **Producer barrier — don't consume a mid-write LHE (N4/G25).** `validate_run_state.py`'s
   `producer-complete` invariant (registered on the `generation` stage) hard-FAILs (exit 1) when an
   on-disk `.lhe.gz` under the rundir is not a COMPLETE MadGraph product: no terminal `Cross-section :`
   line in `logs/*.log` (producer still running), a gzip that does not decompress to EOF (truncated
   mid-write), or a banner `nevents` that does not equal the counted `<event>` records — the "grabbed
   the LHE mid-write, 7031 not 10000" class, where a downstream stage showers a half-written file and
   silently loses events. A run whose LHE has already been consumed and cleaned trips nothing (no
   `.lhe.gz` on disk → nothing to barrier). Let generation finish (confirm the banner σ line) before
   any consumer reads the LHE.

2. **Shower (Pythia8 → HepMC3).** Write a Pythia cfg reading the LHE; let the SLHA decay table act:
   ```
   Beams:frameType = 4
   Beams:LHEF = <procdir>/Events/run01/unweighted_events.lhe   # gunzip first
   SLHA:useDecayTable = on
   <stable LSP>:mayDecay = off
   Print:quiet = on
   ```
   ```bash
   $CONDA run -n rivet $RAVEL_NATIVE_BIN/pythia_shower <cfg> <out.hepmc> <nEvents>
   ```
   The HepMC carries the cross-section (Rivet reads it). Budget its retained size before
   generation. Preserve the original product or a verified lossless compressed copy while
   validation, recovery or downstream receipts depend on it.

**Verify:** the HepMC begins `HepMC::Version 3`; the printed σ matches MadGraph.
## Beyond signal samples — the two recipes prose forgot
- **Continuum background generation (the COST DRIVER for shape work — G-CMS-06).** A waypoint
  or distribution comparison needing simulated QCD/DY background dwarfs the signal cost: slice
  the phase space (e.g. HT/mass bins), size per-slice statistics to the region you display,
  stitch by σ-weight, and put the slice plan + event counts through `cost_preflight.py` BEFORE
  CHECK-IN 1 promises a background curve. Record slice definitions in the run's config.
- **Pythia-internal (non-MadGraph) generation — G-AD-10.** For processes generated directly in
  Pythia (QCD dijets, minimum bias): there is NO LHE, so the `lhe_check.py` gate cannot run —
  state that explicitly in `DEVIATIONS.md` (gate skipped: no LHE exists), verify the process
  switches + phase-space cuts in the .cmnd against the intent, and sanity-check the FIRST HepMC
  events (process id, σ estimate) before full statistics (guard design tracked as CR-011).
- **Environment trap (G-AD-12, catalogue C3):** `<procdir>/bin/generate_events` OUTSIDE the mg5
  conda env exits 0 with no events (the compiler error hides in the procdir debug log). Always
  run generation through `$CONDA run -n mg5 …` and verify `Events/<run>/` is non-empty.
- **On a stage failure, fire `stage-recovery` (RESOLVE/D8).** The moment generation exits nonzero or
  comes out empty/degenerate (undecayed sparticles → empty SRs, an env-trap zero-event run, a merge
  that vetoes every event), run the `stage-recovery` skill: local diagnosis AND an external
  recipe/fix search run **CO-PRIMARY** (`resource_census.py --debug recipe-search`), never search-last.
  A diagnosed generator-model failure cannot be closed until `inputs/recipe_search.json` exists
  (`resource_census.py --assert-recipe-search` must exit 0 — the Stop-dispatcher enforces this).

**Self-drive at step end (DRIVE/D4).** A step must never END by merely *narrating* the next action.
At every step end, run `python3 scripts/run.py ravel.workflow.workflow_state next --rundir <rundir>`:
if it reports a pending action (anything but `(none …)`), **execute it this turn** — long jobs
(generation, shower, scan) via `run_in_background`, recorded with `workflow_state.py record --kind
compute` so a logfile is stamped onto `compute_launched[]` — instead of describing it and stopping.
The Stop branch `stop_dispatch.py` `branch_drive` (CR-064) enforces this: at turn-end it **BLOCKS**
(exit **2**) when `run_state.next_required` is pending **and** the turn is not a CHECK-IN/RESULT
delivery/human-gate turn **and** no live/recent background job exists (no `compute_launched[].logfile`
whose mtime is within `DRIVE_RECENT_SECS=600` s, and no matching pipeline process in `ps`). The
`workflow_state.py next` command is the non-hook FALLBACK the agent runs itself when the hook is
unavailable. A legitimate stop — a check-in awaiting approval — is exempt (delivery turn); a launched
long job clears the gate structurally (its live/recent logfile).

**Detached background jobs (DETACH/N6).** Background long jobs (generation, shower, scan) via the
harness `run_in_background`, **NOT** `nohup`/`start_new_session` — a self-detached job leaves the
harness (and this run) blind to whether it is alive, done, or dead. A detached job is admissible
**ONLY** with a `run_state` `compute_launched` entry carrying `logfile`+`done_condition`+`next_action`
AND a live heartbeat (its `logfile` mtime within `DETACH_HEARTBEAT_SECS=600` s). The Stop dispatcher
`stop_dispatch.py` `branch_detach` refuses turn-end (exit **2**) otherwise — any `compute_launched`
entry with `bg_kind=="detached"` that is missing one of those fields or has no live heartbeat BLOCKS.
Harness-tracked (`bg_kind!="detached"`) jobs are unaffected. FALLBACK when the hook is unavailable:
`python3 scripts/run.py ravel.workflow.workflow_state status` lists the detached entries so the agent
can check them itself.

**Next:** `docs/workflow/steps/04-analyze.md`

> **Pre-exec gate (R3/H1):** a generation command is blocked BEFORE execution unless the approval artifact + recipe exist and the launch is supervised and non-detached (the pre-exec Bash PreToolUse hook).
