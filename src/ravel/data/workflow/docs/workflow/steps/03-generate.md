# Step 3 — Generate events  ·  [judgment] cards / [agent] run

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

Produce showered events (HepMC) for the model. `MG=$RAVEL_NATIVE_BUILD/tools/mg5amcnlo/bin/mg5_aMC`

**Declared generation controls.** For a scoped generation specification, optional
`generation.nb_core` selects MadGraph's cores. The default remains one core and
`run_mode 0`. A larger count requires native `execution.backend_plan.resources.cpus`
at least as large; the plan and approved machine-lease binding record the count,
and the worker refuses a missing or insufficient live grant. Multicore uses
`run_mode 2` inside the existing one-native-job lease. It does not authorize
another job or change CHECK-IN 1, pilot, time or event budgets.

To name an external PDF, set `generation.pdf_set` to a row in
`native/setup/pdf-sets.json`, with its explicit `pdlabel: "lhapdf"` and `lhaid`
in `run_settings`. `generation.pdf_install_record` optionally locates the
installer's `<native-prefix>/state/install-state.json`. Planning requires the named set in a
completed installation record, its complete local members and the matching
LHAPDF data path. A refusal prints the install command; planning never installs
it. The completed LHE must still report the declared PDF identifiers.

For shower-only decay daughters absent from the UFO, provide the full SLHA
`parameter_card` and `generation.decay_states` with `produced`, `stable` and
`invisible` PDG lists. Literal UFO particle identities determine model membership.
Outside-model states need declared masses and zero-width tables and must be
stable and invisible. Planning records the outside states, retains
`inputs/shower-spectrum.slha`, and supplies a separate generator card without
those states or channels. The declared parent widths are retained. A declared
scoped shower reads the full card through `SLHA:file` and `SLHA:readFrom = 2`.
For event production, provide `model.ufo` and the full `model.slha`; the invisible
census performs the same membership check and every shower variant must retain
that SLHA file. These are closure and transport checks, not decay-model validation.

Shower declarations accept a named `tune`. `pythia_cards.resolve_tune` reads
`src/ravel/data/shower/tunes.json`: Monash is the event-production default and
uses the built-in index 14. Each preset records its source and PDF requirement;
settings-list presets retain their citation. `monash-no-reconnection` is a
declared variation, not an independently fitted tune. Commands record the preset
name, apply its settings before explicit overrides and refuse conflicting tune
indices or PDFs. Scoped showers retain their existing behavior when `tune` is
absent. Native initialization and physical tune qualification remain separate.

An MLM `model-events-native.json` can be supplied as
`events.generation_receipt` to event-production planning. A passed receipt must
pin the selected LHE, process, run and shower cards. The consumer checks the
declared multiplicities and actual `xqcut` and fills the complete matching block
from the recorded shower card. Missing explicit settings refuse; a hand-typed
`shower.merging` block must agree. This handoff requires the original LHE and
currently uses LHE-init normalization; multiweight analysis, transformed MLM
receipts and native matching validation need their own qualified route.

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
   `verdict=PASS` sidecar — skipping the guard is a lifecycle FAIL, not a silent omission.

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
- **Continuum background generation (the COST DRIVER for shape work).** A waypoint
  or distribution comparison needing simulated QCD/DY background dwarfs the signal cost: slice
  the phase space (e.g. HT/mass bins), size per-slice statistics to the region you display,
  stitch by σ-weight, and put the slice plan + event counts through `cost_preflight.py` BEFORE
  CHECK-IN 1 promises a background curve. Record slice definitions in the run's config.
- **Pythia-internal (non-MadGraph) generation.** For processes generated directly in
  Pythia (QCD dijets, minimum bias): there is NO LHE, so the `lhe_check.py` gate cannot run —
  state that explicitly in `DEVIATIONS.md` (gate skipped: no LHE exists), verify the process
  switches + phase-space cuts in the .cmnd against the intent, and sanity-check the FIRST HepMC
  events (process id, σ estimate) before full statistics.
- **Environment trap:** `<procdir>/bin/generate_events` OUTSIDE the mg5
  conda env exits 0 with no events (the compiler error hides in the procdir debug log). Always
  run generation through `$CONDA run -n mg5 …` and verify `Events/<run>/` is non-empty.
- **On a stage failure, fire `stage-recovery` (RESOLVE/D8).** The moment generation exits nonzero or
  comes out empty/degenerate (undecayed sparticles → empty SRs, an env-trap zero-event run, a merge
  that vetoes every event), run the `stage-recovery` skill: local diagnosis AND an external
  recipe/fix search run **CO-PRIMARY** (`resource_census.py --debug recipe-search`), never search-last.
  A diagnosed generator-model failure cannot be closed until `inputs/recipe_search.json` exists
  (`resource_census.py --assert-recipe-search` must exit 0 — the Stop-dispatcher enforces this).

**Specialist failure advice.** `ravel.workflow.failure_router.classify(observations)`
uses recorded exit/signal, stderr, supervisor/provisioning fields, missing outputs,
failed checks and quantity witnesses. A model suggestion cannot select the class.
`from_supervisor(record, ...)` translates a retained supervisor failure;
`recovery_packet(observations, evidence=..., rca_ticket=...)` retains its evidence
and proposes the next diagnostic action without authorizing retry or closing it.
`denominators(classifications)` separates infrastructure, provisioning and tool
failures. Optional `recovery_routes(..., signal_basis=..., routine_ids=...)`
attaches prospective route ranks without changing the observed failure class.

Prepare specialist advice with `consults.prepare_failure(rundir, node_id=...,
observations=..., budgets=..., transport_preference=..., evidence=...)`, using the
existing worker budget fields and configured transports. It returns a run-relative
request pin. Run `graph_substrate.run(rundir, 'consult.case', {'request': pin})`.
Infrastructure and provisioning routes hold without a worker. A tool route needs
the targeted knowledge-bundle provider; an absent provider or required handbook
holds before dispatch. The consultant receives full bound handbooks, failure-mode
rows, allowed lessons and a read-only toolbelt. Each proposed fix must cite an
offered handbook pitfall and its check. A successful governed worker receipt
binds the resulting advisory record; advice is never an acceptance vote.

Before materializing the producer's next worker, the production owner calls
`consults.next_turn_spec(rundir, spec, request=pin)` to include the pinned record.
Failed-stage/RCA callers use `consults.diagnostic_inputs(rundir, request=pin)` as
additional diagnostic inputs and retain their existing feedback-admission checks.
The `consult.ask` preparation seam is `consults.prepare_question` with explicit
node, tool, question, budgets and transports: three distinct questions per node,
durable reservations, idempotent repeats, and the same charged answer graph.
Broker action and automatic production-loop registration belong to their owners.
The existing intake planner runs its charged designer through the named
`intake.plan` agent node; original request checks and preparation receipts remain.

**Self-drive at step end (DRIVE/D4).** A step must never END by merely *narrating* the next action.
At every step end, run `python3 scripts/run.py ravel.workflow.workflow_state next --rundir <rundir>`:
if it reports a pending action (anything but `(none …)`), **execute it this turn** — long jobs
(generation, shower, scan) via `run_in_background`, recorded with `workflow_state.py record --kind
compute` so a logfile is stamped onto `compute_launched[]` — instead of describing it and stopping.
The Stop branch `stop_dispatch.py` `branch_drive` enforces this: at turn-end it **BLOCKS**
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

> **Pre-exec gate:** a generation command is blocked BEFORE execution unless the approval artifact + recipe exist and the launch is supervised and non-detached (the pre-exec Bash PreToolUse hook).


## Production worker self-checks

Before finishing a production work order, run each sealed `self_check` through the
worker broker's `check run` action. Use `{"check_id": "<exact validator id>", "paths": []}`
for a run check. The broker supplies the run directory and verified sealed work order
to an explicit in-process adapter. Document checks take one workspace JSON path.
Only allowlisted checks permitted by the role or its sealed order execute. The receipt
names the exact validator that ran. Failed or inconclusive checks produce failing
receipts; missing inputs produce failure without claiming validator execution.
The worker earns self-check credit only from successful custody receipts for every
required validator id. A receipt names a validator only after that validator ran:
its success needs the handler's explicit report that it executed and its stated
outcome, and a validator that raises after it was entered keeps its identity on
the failed receipt.

A plan node's production worker carries that node's sealed work order. The
dispatcher refuses one without it (or with another order) before anything is
created, and the production gate counts a worker receipt only when the
dispatcher's record binds the sealed order as it is now. A worker dispatched
through `ravel work dispatch --spec` outside the production executor may carry no
order or a pinned order in the same format: the order is validated at dispatch
(node and role), the worker's broker takes it as the check input the dispatcher
pinned, the role alone decides which checks it may run, and its receipt never
counts as production credit for a plan node.

Trap knowledge references such as `trap:T6` resolve to
`check:validation.validate_run_state.check_trap_sweep` when orders are sealed.
That validator checks the full trap-sweep record, including hit dispositions.
A trap reference never executes as a validator or earns a receipt under its own id.
Unknown trap references stop order creation.

Declare non-default inputs in the plan node's typed `fields` before sealing.
Use a field with `pointer: /check_inputs`, the parameter object as `value`, and
the input's declared `authority` and `evidence`. This object maps each exact validator id to its parameter object and stays in the
sealed work order:

- Normalization: `ledger` is a run-relative JSON path; the default is
  `inputs/normalization_ledger.json`. Optional `delivered` names the JSON yield map
  to recompute against that ledger.
- Cutflow: declare `signal`, `routine`, `sigma_pb`, `lumi_fb`, `tables_dir`, `grid`,
  `m_parent`, `m_lsp` and `srs`. Paths are run-relative. Optional parameters are
  `sr_reader`, `label`, `exclusion`, `driving_sr_override`, `driving_tol`,
  `contributing_tol`, `mu95_bound`, `interp_max_span` and `certification_context`.
  The adapter invokes the existing validator in-process, writes a new workspace
  report and requires its `PASS` verdict. A zero process exit alone earns no credit.
- Input closure: `fit` and `reference` are path/SHA-256 pins.
- Certificate: declare `path`, `kind` and optional `required_subjects`. Validation
  binds the current contract and applies live checks.
- Calibration specification: `spec` names the run-relative JSON specification.

Route, contract and trap-sweep checks read the corresponding run inputs.
The deviation-ledger check inspects the run's artifact documents and `DEVIATIONS.md`.
These receipts record software checks; scientific acceptance follows the review gates.
