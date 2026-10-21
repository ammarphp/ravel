# Step 9 — Adversarial verification panel  ·  [agent] mechanics / [judgment] adversary  ·  MANDATORY · CHECK-IN

## On the controller

On a controller run the panel is three plan steps after the result, then the controller's own final review:

- `verify.mechanical` (Tier A, kind `review`, worker `integrity-auditor`): `outputs/tier_a.json` with a `PASS` or
  `FAIL` verdict and every reported number traced to an accepted artifact. A `FAIL` verdict holds the step;
  each numerical source must have current accepted custody and unchanged bytes, so a fabricated artifact
  name or a changed source also fails the step.
- `verify.adversary` (Tier B and P8, worker `physics-critic`): `outputs/tier_b.json` with three written attacks
  (basis, acceptance, statistics), each with how it was tested.
- `synthesize` (the results deck, worker `coordinator`): the headline, every number with its artifact, the claims
  and the recipe ledger with every unknown row unchanged. Its numerical sources receive the same
  custody checks as Tier A; source artifacts can be JSON records, tables or other adopted files.

The controller then runs the final review triad (physics critic, skeptical verifier, physics decider) in fresh
sessions, renders the final check-in from the accepted artifacts and delivers only through the sink. A bounded
ending delivers a qualified result that states every obligation's status.

On a run the controller does not own, the host follows the procedure below as before; such a run's
results read NOT GOVERNED, and the controller refuses its legacy commands for a controller-owned run.

## Procedure

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

No result reaches the physicist without passing through this step. Steps 7/8 end with a RESULT-PACK
(`result.json` + `figures.json`) or a scan pack (`scan.json`) and a drafted final check-in / `RESULT.md`.
Before that check-in is **sent**, the panel attacks it. The panel exists to catch **our own** mistakes —
transcription errors, silent protocol drift, unjustified physics judgments — not to defend the result.
Its full checklist form is `docs/workflow/checklists/verification-panel.md`; read it alongside this step.

For a parent with registered children, run `ravel task-completion compose --rundir PARENT`
and retain the computed claim records before the final review. CHECK-IN 3 must list
the composition's full `ci3_list`, including RDJ choices and adopted adapter defaults,
and research deliveries must carry `completion_disclosure.build(PARENT)` unchanged.
Every delivered quantity reports N trials, the selected confirmation and the
optimistic best-of-N selection value. Its evidence status is derived from current
receipts, never a free certification label. See [task completion](../reference/task-completion.md)
for the records and consumer APIs. Tier B is read from the current review journal
when a prospective policy is present. Published-overlay summaries are recomputed
through the summary audit, and PASS trap discharge requires a current artifact pin.

## Two tiers, two classes of agent (tiered model usage — deliberate)
| tier | who | what it verifies |
|---|---|---|
| **A — MECHANICAL INTEGRITY** | [agent] — cheap models (Haiku/Sonnet-class) are sufficient; the checks are look-ups, not judgment | every number quoted traces to a machine artifact; units; figures exist + captioned; coverage claims; deviations ledger |
| **B — PHYSICS ADVERSARY** | [judgment] — a strong model (Opus/Fable-class), and a **fresh context**, not the agent that produced the run | independently attack the physics judgments and try to REFUTE the headline claims from the artifacts alone |

## Tier A — mechanical integrity ([agent], cheap)
The single sources of truth are the machine artifacts: `scan.json` / `result.json` /
`sensitivity.json` / `figures.json`. Prose (`RESULT.md`, the check-in text) is *generated from* them,
never the other way around. Tier A asserts:
- **Number tracing** — every number quoted in the final check-in and `RESULT.md` (limits, yields,
  k-factors, coverage, masses) appears in — or is arithmetically derived, with the derivation shown,
  from — one of those artifacts. **A quoted number with no artifact source, or disagreeing with its
  artifact, is an automatic FAIL** (the number-integrity rule, `docs/workflow/checklists/verification-panel.md`).
- **Units** — every quoted quantity carries its unit, and the unit matches the artifact's convention
  (fb vs pb is the classic slip; GeV on masses; fb⁻¹ on lumi).
- **Figures** — every figure file cited exists on disk; every *displayed* figure has a caption
  (`what_it_shows` in `figures.json`); declared figure-contract targets are fulfilled or WARNed.
- **Coverage** — any "N of M points" / "full grid" claim matches `n_done`/`n_planned`/`missing_tags`
  in `scan.json`; a partial grid must be stated as partial.
- **Deviations ledger** — the run's `DEVIATIONS.md` exists and **every mid-run adjustment of protocol,
  tolerance, selection, or instruction appears in it** (its check-in is defined in
  `docs/workflow/checklists/check-ins.md`). Renorm/rebase-style provenance blocks in the artifacts (e.g. a post-hoc
  re-normalization) each need a matching ledger entry.
- **Recipe-search close-block (G8 / D8 RESOLVE)** — if `run_state.open_failure_records` still names a
  generator-model failure (its record's `stage` is a generation stage, or
  `failure_class == "tool_generator_model"`), then
  `resource_census.py --assert-recipe-search --rundir <rd>` must PASS (exit 0) before the deck ships:
  a diagnosed generator failure must not be closed on local diagnosis alone — `inputs/recipe_search.json`
  (the CO-PRIMARY external search, `--debug recipe-search`) must exist first. This is NON-invariant (it
  is not a lifecycle stage), so it does NOT ride the D18 umbrella; it has its own Stop-branch.
- **Open-defect close-block (N5 / G26)** — an OPEN `run_state.open_defect_notes` entry (a helper flagged
  mid-run with a `status:"open"` defect note) is a **FAIL**: a number from a helper carrying an open
  defect must not feed a comparison/check-in. `verify_pack.py <rd>` FAILs (exit 1) on any open note —
  fix the helper or substitute the blessed tool, then flip the note `status:"fixed"`. This is
  NON-invariant (not a lifecycle stage), so it does NOT ride the D18 umbrella; it has its own
  DELIVERY-only Stop-branch (`branch_open_defect`, token `G26-OPEN-DEFECT:`).

The look-up half of Tier A is scripted — run BOTH gates and paste their reports into the panel
output, `validate_run_state.py` FIRST (lifecycle: did the run reach this point with every required
stage present, in order, and its cross-stage invariants satisfied — incl. R5-before-limit-ships and
the likelihood↔selection pairing gate), THEN `verify_pack.py` (artifact integrity: does what's on
disk internally agree with itself):
```bash
$CONDA run -n rivet python scripts/run.py ravel.validation.validate_run_state --rundir <rundir>
#   exit 0 = PASS (WARNs allowed) · exit 1 = a required stage is missing/out-of-order or an
#   invariant FAILed · exit 2 = usage/rundir error · exit 3 = the task contract itself is invalid.
#   A run that fails this gate is not ready for the checks below — fix the lifecycle gap first.

$CONDA run -n rivet python scripts/run.py ravel.validation.validate_run_state --rundir <rundir> --verify-provenance
#   G19 PROVENANCE gate: rejects a PRESENT lifecycle-required artifact whose generated_by
#   is absent/hand-written or whose input_fingerprint no longer recomputes against provenance.py —
#   closes the backfill loophole (a hand-written run_state.json cannot pass). exit 0 = every present
#   target proves its tool produced it (an absent target is N/A, not a FAIL) · exit 1 = any
#   present-but-backfilled artifact. Seeded with run_state.json; later phases extend PROVENANCE_TARGETS.

$CONDA run -n rivet python scripts/run.py ravel.validation.verify_pack <rundir>
#   asserts internal consistency of the artifact JSONs it finds: figure files on disk,
#   figure-contract PRIMARY target fulfilled-or-FAILed (non-primary WARNed), result/scan coverage bookkeeping,
#   verdict/limit self-consistency, DEVIATIONS.md present when any artifact carries a
#   deviations/renorm/rebase provenance block, and NO OPEN run_state.open_defect_notes entry (N5/G26).
#   Exit 1 on any FAIL — fail-loud.
```
Before serving, also follow `docs/reference/scientific-results.md`: known one-sided limits remain bounds, and live acceptance/R5 claims require current artifact-bound certificates under their approved policies. `execution-current` rejects stale durable stage receipts. Neither a numerically resolved root nor a software gate pass certifies physics coverage.

**D18 umbrella (Stop dispatcher).** The Stop hook `stop_dispatch.py` runs
`validate_run_state.py --rundir` on any CHECK-IN/RESULT **delivery** turn and BLOCKS turn-end
(exit 2, reason fed back) if it does not exit 0 — so a lifecycle-broken run must not post a
check-in. FALLBACK (when the hook is missing): the agent runs
`python3 scripts/run.py ravel.validation.validate_run_state --rundir <rundir>` itself before posting.
The G8 recipe-search close-block above is NON-invariant, so it rides its OWN sibling Stop-branch
(`branch_recipe_search` in `stop_dispatch.py`, G8) — which shells
`resource_census.py --assert-recipe-search --rundir` at turn-end and BLOCKS (exit 2, token
`G8-RECIPE-SEARCH:`) — not the D18 umbrella. FALLBACK: the `stage-recovery` skill / this step-doc runs
the same command before closing the failure. The N5/G26 open-defect close-block is likewise
NON-invariant, riding its OWN DELIVERY-only sibling Stop-branch (`branch_open_defect` in
`stop_dispatch.py`, G26) — which shells `verify_pack.py <rundir>` at a delivery turn-end and BLOCKS
(exit 2, token `G26-OPEN-DEFECT:`) when an open defect note is present. FALLBACK: the agent runs
`python3 scripts/run.py ravel.validation.verify_pack <rundir>` itself before posting.

Review prose for the number-tracing and coverage-**claim** checks (artifact ↔ check-in
text) remain the [agent]'s job, artifact value next to quoted value, line by line.

## Tier B — physics adversary ([judgment], fresh context)
Hand the adversary the **artifacts + figures only** (not the run narrative's conclusions) and instruct
it to refute the headline. Minimum attack surface, itemized in `docs/workflow/checklists/verification-panel.md`:
- **Basis choices** — is every comparison on a like-for-like basis (σ normalization, charge/flavour
  states, LO vs NLO, sample-σ vs model-σ)? Would a different defensible basis flip the verdict?
- **Statistical treatment** — mode appropriate and declared (`stat_mode`)? limit at the true CLs=0.05
  crossing? expected band sane? single-SR vs combination justified? 95% CL exclusion, never discovery.
- **Proxy validity** — every stand-in (fast-sim, reimplemented selection, AD proxy, truth-level
  shortcut) declared, with its domain of validity covering the quoted region?
- **Assumption-flag completeness** — do `limitations[]` + `RESULT.md` caveats cover every assumption
  the adversary can identify from the artifacts? An unflagged material assumption is a finding.

## Verdict + delivery (never silently fixed)
The panel returns **PASS / CONCERNS / FAIL** with itemized findings. The findings are **APPENDED to
the final check-in verbatim** — even after a fix, the check-in shows what the panel found. Never
silently patch the result and present it as if the panel found nothing.
- **PASS** — deliver; append the panel verdict + the `verify_pack.py` report.
- **CONCERNS** — deliver **with** the findings appended and each one answered (accepted-as-qualification
  in `limitations[]`/`RESULT.md`, or fixed + noted). Unanswered findings block delivery.
- **FAIL** — do not deliver. Fix, log the fix in `DEVIATIONS.md`, **re-run the panel** (both tiers).
  When the FAIL traces to a stage-level defect whose fix is not obvious (an empty-SR spectrum, a
  detector card that won't build, a merge that vetoes every event), fire the D8 external recipe search
  before improvising — `resource_census.py --debug recipe-search --tool <t> --model <m> --symptom <s>
  --rundir <rundir>` writes `inputs/recipe_search.json`; the published fix (card, run config, recast
  repo, thesis appendix) is often already online (see the `resource-sweep` skill).

## CHECK-IN
Attach to the final check-in: the panel verdict, the itemized findings (with dispositions), and the
`verify_pack.py` report. Only then does the result go to the physicist.

Controller delivery includes every recorded assumption from intake, judgment frames,
assumption records and the current scientific plan. `<run>/delivery/ASSUMPTIONS.md`
and `<run>/delivery/ASSUMPTIONS.json` retain each statement, its record locator and digest, including
controlled assumptions and every severity level. Delivered result notices link this
complete appendix; the delivery receipt and inventory bind its bytes.

The controller manuscript graph records a procedure-note request after assembly.
Its native source and rendering commands write directly in the attempt's output
root. Receipts retain the plan's `outputs/` paths; launch custody maps those paths
to the files in that root and checks their inventory digests before adoption.
Isolated module launches read the controller's installed package inside the same
confined environment.
The final sink rechecks the assembly and accepted source bytes, then writes the
procedure, audit and evidence-verification workflow inside the private atomic delivery.
The package records controller outcomes and dependencies alongside source pins;
its completion status follows the recorded step outcomes.

When the accepted result is also a submission (an analysis challenge, a journal or a collaboration
repository), package it after acceptance with `ravel export-submission --request REQUEST --into REPO`,
commit the package, and check it with `ravel export-submission verify --package REPO/submission
--fresh-clone`. The export refuses results that no accepted review captured. See
[challenge operations](../../reference/challenge-operations.md).

Submission environment export uses recorded stage runtimes, never the exporting
interpreter. Call `env_snapshot.capture_runtime(rundir, stage)` inside the executing
stage process; it returns a source pin for `logs/environment/<stage>-<attempt>.json`.
`env_snapshot.runtime_snapshots(rundir)` revalidates every retained attempt. Capture
reads Python metadata, resolved interpreter, OS/machine/libc, an installer-written
`.ravel-site/lcg-view.json`, supplied image records and allowlisted container markers.
It never sources helpers or probes native tools. Supply `doctor_record` explicitly,
or retain JSON in `logs/site-doctor.json` or `logs/site-doctor/*.json`; capture uses
the latest modification time. Site-doctor  prints JSON, so record retention
must be explicit. Missing tool versions or image identity remain unknown.

`environment_export.write(package_dir, runtime_snapshots, wms_lock=None)` exports
`<package>/environment/runtime/`, the recorded package union in `analysis-requirements.txt`,
the repository's `requirements-site-wms.lock` as `wms-requirements.lock`, and
`<package>/environment/setup.sh`. Missing snapshots or the hash lock, changed records, and conflicting
package versions across stages are refused. RAVEL's distribution is excluded from
the union and pinned separately in `<package>/environment/ravel-requirements.txt`. The `allow_fixture_lock=True` seam is only for synthetic
tests. Different pins across the two isolated environments are permitted; exporting
an analysis environment that mixes Snakemake with conflicting WMS pins is refused.

From the package directory, explicitly run `sh environment/setup.sh`, then
`export PATH="$PWD/.bin:$PATH"`. The script creates fresh `.venv-analysis` and
`.venv-wms`, installs their separate requirement files and the separate RAVEL pin,
and links `ravel` and `snakemake` into `.bin/`. It refuses missing RAVEL pins or
existing environment paths. Export never installs anything. Recreate the recorded
Python/OS and provision native tools, facility views and container images separately;
the snapshots establish provenance, not runtime or scientific qualification.

Every closed parent also needs its recorded procedure. Refresh with `ravel status
--rundir RUN --write`: completed parents and terminal failed or aborted parents emit
an immutable evidence export. Non-PASS records carry `procedure_status` of failed,
aborted or incomplete and grant no delivery authority. Open parents remain open.
Final quantitative reports export after the whole-parent gate, and submission
packages include one. For a standalone export, run
`ravel procedure export --rundir RUN --into FRESH_DIRECTORY`.

Procedure refresh binds stage-ledger digests and checks artifact existence, size
and directory membership without reading recorded stage payloads. Set
`RAVEL_PROCEDURE_BYTE_CEILING` to a nonnegative byte count (default 1048576): larger
inputs and outputs remain references, and an unrecorded digest stays unknown.
This limits the exporter; the status packet's existing execution and scientific
checks retain their separate validation requirements. Run
`ravel procedure verify --package EXPORT --deep` for full source-content checking.
Default verification checks package closure plus source existence and size;
Snakemake node rules check their own evidence content and shared source records.
A source without a recorded digest must not pass deep content verification.

Refresh-time package upgrades do not change the export identity. When available,
per-stage runtime snapshots bind the execution environment as source pins; absence
of that interface is disclosed. An optional `inputs/site-profile.json` record with
integer `cores` (1 through 1024) sets the delivery export's local profile; its absence
retains one core. Campaign heads registered in `inputs/completion_sources.json`
under `research_cycles` include each experiment's stage nodes, with distinct run
identities. Exports include the installed replay template when available, or an
explicit inactive placeholder.
The note includes recorded attempts, graph ids/versions/thread ids, the worker census,
the environment snapshot and the computed completion disclosure. Its Snakefile verifies
retained evidence with one rule per recorded node. Scientific recomputation uses the
ordinary approved site workflow; export supplies no approval. See
[site workflows](../../reference/site-workflows.md) for profiles and theory templates.

## The workflow gates are themselves verified
Beyond this per-run panel, the workflow-adherence gates are regression-verified *as software* by the
per-gate simulation (`make green`): every gate G0a–G27 has a `cases/case_<g>.py` that seeds the bad
fixture and asserts the gate FIRES.

After current scope acceptance, use [requester workspace delivery](../../reference/deliver-workspace.md)
for `ravel deliver-workspace --rundir RUN --layout LAYOUT.json --into WORKSPACE`;
recheck the copied files with `ravel deliver-workspace verify --into WORKSPACE`.

For requester-supplied repository or submission requirements, follow the
[conformance checklist](../checklists/conformance.md) and run `ravel conformance
check` with their rule pack. Keep its documentary checks and missing-source
statuses alongside the existing result verification and review records.

For an accepted submission, export with `ravel export-submission --request request.json
--into repository --framework-source vendor --framework-checkout tagged-framework`,
or select `--framework-source release:v1.0.0`. Use `--layout layout.json` for repository
conventions. Follow [portable submission packages](../../reference/site-workflows.md#portable-submission-packages)
for release-tree checks, `make env`, `make check`, `make verify` and the fresh governed
replay approval gate. Use `verify --fresh-clone` to check a second parent directory.
Historical approval records grant no authority to a new replay.

Report the architecture receipt and its plain-language notices before the numerical summary. `ravel result-pack` defaults to diagnostic delivery. `--delivery-label governed` requires current supervisor custody and a matching approval-bound launch for every numerical source and figure; `--delivery-label accepted` additionally requires credited required roles and current review of those exact artifacts. `python -m ravel.validation.verify_pack` recomputes these decisions. Mechanical verification does not establish scientific acceptance. A saved receipt or successful number is not authority. Diagnostic artifacts stay diagnostic. Missing role coverage prints INDEPENDENT REVIEW INCOMPLETE; missing launch coverage prints NOT GOVERNED.
