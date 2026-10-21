# Failure catalogue

Each entry is a failure class: **what goes wrong → how it is caught → where the guard lives.**
Entries marked *guard: PENDING* are open fixes.
New classes that survive verification get an entry here.

## A. Figure & comparison integrity

**A1 — Caption-imagined figure.** A counterpart figure is drawn from the caption text instead of the
published figure, so its form (for example a smooth heatmap where the published figure is a sparse
per-cell map) does not match. Caught: extracting the published figure and placing the side-by-side in
the check-in. Guard: the figure contract — no counterpart ships without `extracted_image` + a
side-by-side composite (`checklists/figure-contract.md`, `figure_target.py declare/attach/compose`,
the check-in figure gallery in `checklists/check-ins.md`).

**A2 — Axis-scale overcorrection.** A counterpart uses a linear axis where the published axis is log,
or the reverse after a house rule is applied. Caught: the side-by-side against the extracted published
figure. Guard: axes are contract facts, not defaults — read off the published figure at declaration
into `figure_target.json:axes` and consumed by renderers via `--figure-target` (`figure_target.py`,
`checklists/plot-guidelines.md`, `checklists/check-ins.md`); heuristics are allowed only with
`axes.source="assumed"`.

**A3 — Expected-vs-observed column mixup.** A reference overlay compares an observed limit with a
published expected contour (or the reverse). Caught: decoding which column the published markers
represent before trusting the overlay. Guard: the like-columns rule — `scan_contour.py --plot-spec`
refuses a reference or residual layer whose quantity differs from the scan layer's
(`checklists/figure-contract.md`); the check-in caption states which column is drawn.

**A4 — σ-comparison-basis mismatch.** A σ-UL quoted on a tagged sample cross section is compared with
a published UL on the inclusive model cross section, producing a mass-dependent spurious tilt. Caught:
the on-contour identity check — on the published exclusion contour, UL/σ_model must equal 1 within
its uncertainty. Guard: `scan_orchestrator rebase --process` maps ULs onto the published model σ and
records the basis in `scan.json:model_basis`.

**A5 — Legend/annotation text occluding the data.** A renderer places legend or annotation boxes over
drawn data. Caught: visual review. Guard: all renderers route through `mplhep_style.smart_legend`,
and `mplhep_style.lint_figure` runs inside every house renderer at save time and
exits 4 on legend/boxed-annotation occlusion of drawn data, box↔box overlap, or tick-label collisions
(`plot_lint.py --selftest` proves both directions). `smart_annotate` scores corners and falls back to a
below-axes caption when every corner is occupied.

**A6 — Ungrounded "consistent with the publication" claims.** Agreement is asserted in prose without
an artifact-level comparison. The words "matches", "consistent", "agrees" carry a debt: which published
number or figure, which artifact of ours, at what tolerance. Caught: a reviewer challenge. Guard: the
verification ladder (`checklists/verification-ladder.md`) — agreement claims are rung statuses with
evidence citations, gaps are confirmed only by bracketing; panel Tier-A FAILs a missing ladder; Tier-B
attack: pick any prose agreement claim and demand its rung row.

## B. Statistics & normalization

**B1 — pyhf µ-floor on hyper-excluded points.** A µ bracket that only searches upward from 1 returns
`obs_limit=1.0` with a flat band for points with CLs≪0.05, and a floored µ becomes a huge fake σ-UL.
Caught: saturated difference-map cells plus flat-band inspection of `exclusion.json`. Guard:
`pyhf_exclude.py` brackets down (floor 1e-6) + `at_mu_floor` flag (`selftest` is the regression);
`scan_orchestrator harvest_point` tags floored/capped/legacy points `quality=...`; `scan_contour`
renders them as '×' bounds, never colored as measurements.

**B2 — Run options silently dropped by native card preparation.** A preparation step that renders
the raw run-card template and applies only some keys drops the rest of `[madgraph.run.options]`
(for example a generation-level jet cut), changing the sampled cross section and tag definition.
Caught: a cross-run σ_ref consistency check chased down to a small A/B. Guard: the
preparation applies the full block fail-loud (missing file/block/key = die) from the point's own TOML.

## C. Silent generation & environment failures (exit 0, wrong output)

**C1 — Width-only DECAY tables → empty SRs.** MadGraph's default restrict card writes total widths with
no BR rows; Pythia imports nothing and the sparticles never decay — plausible LHE, empty signal regions,
exit 0. Caught: empty-SR forensics traced to the source (`SLHAinterface.cc` + a direct shower test).
Guard: `lhe_check.py` is mandatory pre-shower (`.claude/rules/madgraph-pythia.md`;
`checklists/model-cards.md`: explicit BR rows + MODSEL).

**C2 — A guard itself false-FAILing: lhe_check on wide resonances.** A fixed ±1 GeV mass tolerance
FAILs Breit-Wigner event-record masses of wide s-channel signals although the banner mass is exact.
Caught: a generality check on a wide-resonance model. Guard: `lhe_check.py` reads each expected
PDG's Γ from the banner's `DECAY` headers and widens the event-mass tolerance to max(--mass-tol, 3Γ);
the banner-mass check stays tight. Both pipeline drivers run the gate (native: stage 1b pre-shower;
container: post-madgraph, ahead of detector/analysis).

**C3 — MadGraph "success" with no events.** `<procdir>/bin/generate_events` outside the mg5 conda env
exits 0 while "A fortran compiler is required" appears only in the procdir debug log; more generally
MadGraph can report done with an empty `Events/`. Caught: the "confirm `Events/<run>/` non-empty" rule.
Guard: that rule + the `run-stage` skill — never trust generation exit 0.

**C4 — `conda run <<heredoc` passes no stdin.** The script body silently never executes (exit 0).
Caught: a driver whose steps did nothing. Guard: `.claude/rules/madgraph-pythia.md` — write
`/tmp/x.py` then `conda run -n <env> python /tmp/x.py` (or `python -c`), as `run-pipeline-native.sh`
does.

**C5 — Unrendered `{{ecms}}` placeholder reaches MadGraph.** A jinja run-card template with an
unrendered placeholder crashes generation with "'{{X}}' can not be mapped to a float". Guard: a
fail-loud placeholder scan after rendering — any remaining `{{` dies naming the leftovers
(`prepare_native_slepton.py`, render guard).

**C6 — Disk-full mid-scan + orphaned-Delphes truncation.** Regenerable per-point intermediates
(MadGraph events and procdir, Delphes ROOT, HepMC) fill the disk and points die with
`NoSpaceLeftError`; separately, when the driving process exits, in-flight Delphes stages are killed
mid-write, leaving a truncated `delphes.root` with no `Delphes` tree → `sumweights=0` →
`ZeroDivisionError` in Delphes2SA. Caught: `df` at 100% + the analysis-log "missing named tree"
Delphes`. Guard: `scan_babysitter.py` cleans the heavy regenerable subdirectories from every completed
point (curated outputs preserved), heals failed and stale-running points back to pending (removing the
truncated intermediates), and feeds pending points only while free disk ≥ `--min-free-gb`.

**C7 — Healed-point σ_ref harvest gap → silent rebase failure → wrong-basis numbers.** A re-run point
can produce a `madgraph.log` without the `Cross-section :` summary line (MadGraph reused a cached
refine). A harvest that parses only that line returns no σ_ref, `scan_orchestrator rebase` aborts, and
the σ-UL comparison silently runs on the wrong basis. A completion watcher that fires on a `status`
race compounds it. Caught: a residual far from a clean partial and `model_basis` False after a
"successful" run. Guard: `sigma_ref_fb()` falls back to `analysis.log`'s `Using cross section X` (the
same pb value fed downstream); never trust a σ-UL comparison whose `rebase` did not print "rebased N
points onto the inclusive model-σ basis" or whose scan.json `model_basis` is not True.

**C8 — Rivet `pluginONNX` routine with no shipped `.onnx` weight file → unconditional `init()` crash.**
A `pluginONNX` routine whose `init()` unconditionally calls `getONNX(name())` fails to compile without
`onnxruntime` in the Rivet environment, and even with it, throws at `init()` when upstream never
committed the matching `.onnx` weight file. The stall is easy to mis-attribute to an unrelated
environment problem. Caught: a direct read of `rivet_build.log` plus a check of the upstream repository
tree. Guard/fix: when a `pluginONNX` routine's `init()` crashes or will not compile, check for the
`.onnx` file's existence (locally and upstream) before assuming an environment fix will help. If the
target SR family does not read the NN discriminant (verify by source read: no shared variables, no
`vetoEvent` in the NN-scoped block), a run-local patch removing the ONNX load and the disjoint NN block
(documented in `RESULT.md`/`DEVIATIONS.md`, share untouched) unblocks the non-NN yields with no physics
impact on them. Report the missing data file upstream.

## D. Doc & process drift

**D1 — 1-D-line collapse.** A session shrinks the deliverable to a single point or a 1-D Δm line when
the product is the 2-D mass-plane contour. Guard: step 8's deliverable is the 2-D contour
(`steps/08-scan.md`; `checklists/scan-and-contour.md`: "a 1-D Δm line … is only a partial PoC").

**D2 — VM-default doc drift.** Docs route SimpleAnalysis to the podman/amd64 container although the
native chain is the default, reinstalling a container-speed cost model. Caught: the reconciliation grep
`podman|VM|container|emulat|amd64` over docs/workflow/. Guard: native is the default
(`reference/native-pipeline.md`, steps 04/08); every container mention must be tagged legacy/fallback;
re-run the grep after doc edits.

**D3 — Fresh-session routing failure.** A physics session does not route on its request and surveys
development docs instead, or starts a survey before routing and leaves output outside the run tree.
Guard: the two-route fork at the top of CLAUDE.md/AGENTS.md + `docs/workflow/start.md`. A session
launched with its working directory at the repository's parent sees the repository's CLAUDE.md only as
lazy-loaded nested memory, invisible at turn 1; a parent-level router file that points into the
repository closes that gap.

### Workflow-adherence gates (D4–D18) — one hard gate per class

> Each class below names the gate that fires on its trigger and the adversarial case
> (`tests/adversarial/run_suite.py`) that re-fires it every `make green`. These continue the D-series
> above; the map is authoritative in `tests/adversarial/README.md` (G0a–G27).

**D4 — Narrate-without-execute; nothing forces the next compute (no DRIVE).** An agent ends a turn by
*describing* the next stage ("next I'll generate…") without launching it — no mechanism forces the
compute, so the run stalls between gates until a human nudges it. Caught: a turn with a pending `run_state.next_required`, no
`compute_launched`, and no live background job, that is not blocked at a named human gate. Guard: **G4** —
the `stop_dispatch.py` DRIVE branch exits 2 on exactly that signature and feeds the D4 reason
back to the agent; the step-end self-drive rule lives in `docs/workflow/steps/03-generate.md` ("Self-drive at
step end (DRIVE/D4)"). verified-by: **`case_g4.py`**.

**D5 — Hand-rolled plot substitutes for the contracted waypoint figure (INTEGRITY, waypoint).** A
CHECK-IN-2 turn ships an ad-hoc matplotlib plot in place of the contracted `figure_target compose`
output, so the waypoint figure was never bound to the declared published target. Caught: a CHECK-IN-2
delivery turn whose PRIMARY `figure_target.json` has `side_by_side: null` → `validate_run_state.py
--rundir` exits nonzero and the umbrella blocks. Guard: **G11** — only `figure_target.py checkin` output
satisfies the waypoint-aware `inv_figure_contract_fulfilled`, enforced through the D18 umbrella Stop
branch (moves the binding forward from step 9 to the CHECK-IN-2 waypoint). verified-by:
**`case_g11.py`**.

**D6 — A live hang never self-reports (no CATCH).** A stage hangs (100% CPU, no forward progress) silently
for hours with no watchdog, caffeination or timer to notice, and no failure record to force
re-invocation. Caught: wall-clock overrun vs `cost_preflight` + an unhandled `*.failure.json` under
the rundir. Guard: **G6** — `stage_supervisor.py` wraps the stage (wall-clock + progress-stall + flat-RSS
+ exit-0-plausibility) and SIGTERM/SIGKILLs the hang so the background job completes and the harness
completion notification fires carrying a `failure.json` + next action; the `stop_dispatch.py` CATCH
branch refuses turn-end while an unhandled `*.failure.json` exists. verified-by: **`case_g6.py`**.

**D7 — Generation recipe not fetched before generating a BSM/HV model (no PREVENT).** A `mg5`/shower
launch for a BSM / hidden-valley model proceeded without first fetching the external generation recipe
(the census R6 rung), risking a silently wrong process or card. Caught: a `run-pipeline-native.sh
<rundir>` launch whose contract declares a BSM model with no fetched recipe on disk.
Guard: **G9** — `resource_census.py --assert-pre-generate` + the `pre-generate-guard.sh`
PostToolUse guard hook BLOCK (exit 2) any generation Bash call before the recipe is fetched; the
gate is documented in `docs/workflow/steps/03-generate.md`. verified-by: **`case_g9.py`**.

**D8 — External fix-search ordered last, not co-primary, on a diagnosed failure (no RESOLVE).** On a
diagnosed stage failure the agent debugged locally and reached for the external recipe/fix search only as
a last resort, so a known upstream fix was found late (or not at all). Caught: an OPEN
`failure_class=tool_generator_model` record with no `inputs/recipe_search.json`. Guard: **G8** —
`resource_census.py --debug recipe-search` (tool+model+symptom-keyed) runs CO-PRIMARY inside the
`stage-recovery` skill; `--assert-recipe-search` + the `stop_dispatch.py` recipe-search branch
 refuse to close the failure without a `recipe_search.json`. verified-by: **`case_g8.py`**.

**D9 — Headline artifact not bound to the approved target; mid-flight amnesia of the contract (INTEGRITY,
primary).** The delivered headline figure drifted from the CHECK-IN-1-approved published target — a
counterpart was rendered with no composed side-by-side against the declared figure. Caught: a deck turn
whose PRIMARY `figure_target.json` has a `generated_counterpart` but `side_by_side: null`. Guard: **G10** —
`figure_target.py primary/fulfil-primary` + the now primary-aware `inv_figure_contract_fulfilled` in
`validate_run_state.py`, which hard-FAILs on a null PRIMARY counterpart/side-by-side in ALL modes.
verified-by: **`case_g10.py`**.

**D10 — Parameter validation dropped/mis-filed before a scan (no VALIDATE).** The varied-parameter
validation was skipped or written to the wrong place, so wrong physics could reach a launched scan
unchecked. Caught: a scan launch whose `inputs/validations.json` varied-param obligation is still
`PENDING`. Guard: **G12** — `validate_parameters.py` writes `inputs/validations.json` and the
`inv_param_validated_before_scan` invariant in `validate_run_state.py` FAILs a scan with a PENDING/FAIL
validation. verified-by: **`case_g12.py`**.

**D11 — The dry→smoke→full→scan ladder is ungated (no ladder waypoint).** A full/scan launch could skip
the smoke waypoint entirely, spending long compute on an unproven configuration. Caught: a full/scan run
that reached generation with no smoke-rung PASS in `logs/ladder.json`. Guard: **G13** — the
`inv_ladder_order` invariant in `validate_run_state.py` (+ the `run-scan` pre-launch refusal) blocks
unless the smoke rung has a PASS artifact. verified-by: **`case_g13.py`**.

**D12 — acc×eff cert not forced before yields feed a limit (no certify).** A limit-shipping mode
(including scan) could publish an exclusion with no acceptance×efficiency certification behind the yields.
Caught: a scan shipping an exclusion with no discoverable acc×eff cert (the per-point `scan.json`
attestation does not substitute). Guard: **G14** — the `inv_certify_before_limit` invariant in
`validate_run_state.py` FAILs any limit-shipping mode without a non-FAIL cert before statistics/result_pack
pass. verified-by: **`case_g14.py`**.

**D13 — Trap route-consequences flagged but never checked (no trap-obligations).** A physics trap (T1
interference / T8 per-width / T12 scheme) was flagged in the trap sweep, but its route-consequence
obligation was never discharged before the gated stage. Caught: a T8 hit with a `PENDING` (undischarged)
`trap_sweep.json` obligation at generation. Guard: **G15** — typed `{trap, obligation_kind, artifact,
status}` obligations + the `check_trap_sweep` / `inv trap-obligations-discharged` invariant in
`validate_run_state.py` require `status==PASS` before the gated stage (generalizes D10 to T1/T8/T12).
verified-by: **`case_g15.py`**.

**D14 — No analysis→statistics plausibility gate; a vacuous "not excluded" ships (no plausibility).**
All-zero SR yields flowed straight into statistics, producing a degenerate huge µ95 and a vacuous "not
excluded" that BOTH cutflow validators PASSed. Caught: all-zero SR yields → degenerate huge µ95 →
`sr_plausibility.json` verdict `implausible`. Guard: **G16** — the `sr_plausibility.py` emitter (≥1
non-trivial SR; driving-SR acc×eff in band; µ95 not floor/degenerate) is folded into `check_statistics`
 as a hard FAIL, not a PASS. verified-by: **`case_g16.py`**.

**D15 — DEVIATIONS gate is post-hoc + narrow-trigger, not moment-of-change.** A CHECK-IN-1-baselined file
was edited without a DEVIATIONS row, and the old post-hoc/narrow-trigger check did not catch it at the
moment of change. Caught: an Edit to the baselined `inputs/task_contract.json` with no DEVIATIONS.md row
naming it. Guard: **G17** — the edit-time `deviations-guard.sh` PostToolUse hook (+ the
`deviations_on_change` invariant) BLOCKS (exit 2) a baselined-file edit lacking its DEVIATIONS row.
verified-by: **`case_g17.py`**.

**D16 — `directory-keeper` advisory → drift ships (no commit gate).** A tool
could be added without a workflow-doc embed or a `DIRECTORY.md`/agent-surface reconcile, so drift shipped
uncaught. Caught: a staged export tree whose `docs/workflow/*.md` references a nonexistent path. Guard: **G20** —
the installed git `pre-commit` hook (`install_git_hooks.sh`) runs `check_agent_surface.py --stage`
and BLOCKS the commit on a dead ref / FAIL. verified-by: **`case_g20.py`**.

**D17 — Unguided routing unproven; D3 recurs.** There is no repeatable proof
that a fresh session launched from the workspace parent routes correctly instead of
surveying the repository (the D3 failure recurring). Caught: a fresh session that surveys the
repository, never emits `task_contract.json`, or generates before CHECK-IN 1. Operational guard: **G22**
blocks individual workflow steps before their intake contract; it does not establish whole-session
routing. verified-by: **`case_g22.py`**.

**D18 — The verification lifecycle is invoke-only; a run can skip step 9 wholesale (the umbrella).**
Nothing forces the step-9 verification panel — a run could deliver a CHECK-IN / results deck / RESULT.md
without ever running the panel and no gate fired. Caught: a delivery-signature turn whose rundir does not
pass `validate_run_state.py --rundir`. Guard: the **umbrella** — the `stop_dispatch.py` D18 PRIMARY branch
blocks any delivery turn unless `validate_run_state.py --rundir` exits 0, folding `verify_pack` + every
invariant (D5/D9–D14/N2/N4 + provenance) into one Stop gate; the specific classes above are what the
`validate_run_state` umbrella enforces. verified-by: the umbrella re-fires through `case_g11.py`
(the D5 waypoint via the `d18` branch) and every invariant-family case.

**D19 — Backfilled/stale required artifact clears a presence-only gate (PROVENANCE).** A required
physics-lifecycle artifact (`sr_plausibility.json`, whose implausible verdict hard-FAILs statistics,
D14) can be faked two ways once gates check presence alone: (a) an agent hand-types `{"verdict":
"plausible"}` with no `generated_by`, or (b) a genuine artifact is left in place after the
`sr_yields.json` / `exclusion.json` underneath it changed, so the recorded verdict no longer describes the
current inputs. Either way a green gate certifies a physics claim the tool never actually produced.
Caught: `validate_run_state.py --rundir <rundir> --verify-provenance` — the `generated_by` check rejects
(a) (G19 part 1), and an `input_fingerprint` recompute over the declared inputs (the same
plausibility-domain canonicalization the emitter uses) rejects (b) when the stored fingerprint no longer
matches (G19 part 2). Guard: **G19** — `verify_provenance_lifecycle` in `validate_run_state.py` (selftest
cases 18–19; wired into the step-9 Tier-A `--verify-provenance` checkbox, `checklists/verification-panel.md`)
— provenance, not presence. verified-by: **`case_g19.py`**, which re-fires this exact class every `make green`. (D19 is the cross-cutting provenance
invariant, gate G19, a principle the umbrella runs.)

### Run-behaviour signatures (N1–N9)

> Each entry names the gate that catches the signature.

**N1 — A physics request loads a downstream skill before the mandatory intake gate (skill-precedence).**
A session's first `Skill` is `new-analysis`, skipping the mandatory `physicist-intake` gate. Caught: a first `Skill` ≠
`physicist-intake` with no active-run `task_contract.json`. Guard: **G22** — the `pretooluse-skill.sh`
PreToolUse-on-`Skill` guard exits 2 unless `physicist-intake` is first (no `new-analysis`/`run-*` before
the contract exists). verified-by: **`case_g22.py`**.

**N2 — Primary compute runs in the /tmp scratchpad, outside the rundir (in-tree-outputs).** Per-point
yields written under `/tmp` instead of the rundir are invisible to `verify_pack` /
`directory-keeper` / `.gitignore` (all of which key on the rundir). Caught: a `scan_manifest.json` point
whose `run_dir` resolves under `/tmp`. Guard: **G23** — the launcher rejects a `/tmp`/scratchpad `OUTDIR`
and the `inv outputs-in-tree` invariant in `validate_run_state.py` FAILs if a manifest point's evidence is
not under the rundir. verified-by: **`case_g23.py`**.

**N3 — A backgrounded watcher's fire-command is never smoke-tested (armed-command-unvalidated).** A
completion-watcher's fire-command (for example a call with the wrong arity) is launched un-tested and
crashes hours later at SCAN-DONE, invisibly. Caught: an armed watcher with no preflight artifact on disk at
turn-end. Guard: **G24** — `preflight_watcher.py --arm` (`bash -n` + arity probe) refuses to arm a
watcher whose fire-command fails preflight and writes `logs/<watcher>.preflight.json`; the
`stop_dispatch.py` armed-watcher branch (`--assert-all`) refuses turn-end without it. verified-by:
**`case_g24.py`**.

**N4 — A generation output is consumed while still being written (producer-barrier).** A downstream stage
reads an LHE mid-write and loses events; C3's non-empty check passes a half-written file. Caught: a `.lhe.gz` whose banner `nevents` ≠ its counted `<event>` records.
Guard: **G25** — the `inv producer-complete` invariant in `validate_run_state.py` blocks the consumer
until MadGraph's terminal `Cross-section :` line is present, the gzip decompresses to EOF, AND banner
`nevents` == counted events. verified-by: **`case_g25.py`**.

**N5 — A helper flagged defective is worked around, not fixed (open-defect-reuse).** A helper named in an
unresolved defect note is worked around rather than fixed, so it re-emits the wrong number across the
run. Caught: a delivery turn-end with an unresolved
`open_defect_notes[]` entry. Guard: **G26** — the `verify_pack.py` open-defect gate + the `stop_dispatch.py`
open-defect branch (gated on `is_delivery`) block a number sourced from the flagged helper from
feeding a comparison/check-in until the note is resolved or the blessed tool is substituted. verified-by:
**`case_g26.py`**.

**N6 — `nohup` detachment silently defeats the completion-notification lever (detach-defeats-drive).** A
`nohup`-detached long job silently defeats the harness completion-notification lever the DRIVE/CATCH
design depends on and hides the job from the physicist. Caught: a `bg_kind=detached`
`compute_launched` entry missing `logfile`/`done_condition`/`next_action` with no live heartbeat. Guard:
**G27** — the `stop_dispatch.py` detach branch refuses turn-end for such a job; DRIVE mandates
harness-tracked `run_in_background`, or a durable `run_state.json` (pid/logfile/done-condition/next-action)
+ a harness-visible heartbeat for a genuinely detached job. verified-by: **`case_g27.py`**.

**N7 — A source is asserted blocked/missing without a recorded attempt (assert-blocked-without-attempt).**
A survey records a source as blocked (for example "HEPData is Cloudflare-blocked") without ever trying
`hepdata_fetch.py --tables`, and the false belief drives over-conservatism. Caught: the mandatory step-2 resource
census records REAL fetch attempts + results per rung, so an "missing" claim without a recorded
attempt has no census row backing it. Guard: **D18** umbrella — `inv_resource_census_before_route`
requires `inputs/resource_census.json` (the attempt ledger) before routing ships; source-ladder protocol
P6 orders the retry. verified-by: the census invariant selftest + `test_resource_census_gates.py`.

**N8 — Subagent fan-out before routing (fan-out-before-routing).** On a fresh physics prompt an agent
launches a multi-agent survey before any task contract exists — a wrong-granularity sibling of N1's
wrong-skill-first: a guard that covers `Skill` only lets Agent/Task fan-out past the intake gate. Caught: an Agent/Task tool call in a session whose route-pending marker
(`logs/.route-pending-<session>`, touched by the UserPromptSubmit router on physics classification) is
present with no session-scoped `task_contract.json`. Guard: **G22** extension — the PreToolUse
guard (matcher `Skill|Agent|Task`) exits 2 until the contract exists, then consumes the marker.
verified-by: `test_pretooluse_skill.py::test_agent_fanout_blocked_while_route_pending`.

**N9 — The enforcement surface is edited mid-run to escape a gate (enforcement-disarm).** An agent that
finds a gate inconvenient edits `.claude/settings.json`, a hook, or a gate tool instead of satisfying the
gate — the agentic sibling of "edit the test, not the code". This entry is pre-emptive. Caught: a PreToolUse Edit/Write to the
enforcement surface (settings/hooks/adversarial harness/green_board/Makefile/the gate tools) in a session with a
route-pending marker or a session-scoped run_state. Guard: **G22**-family PreToolUse —
`protect-enforcement.sh` exits 2 with "make enforcement changes in a dev session".
verified-by: `test_protect_enforcement.py`.

## Tier-B adversary: use this catalogue as your attack list
When running the step-9 verification panel's **Tier B** (`docs/workflow/checklists/verification-panel.md`),
walk this catalogue top to bottom BEFORE free-form attacks: for each entry A1–D19 + N1–N9, attempt the
same failure class against the current run's artifacts (was the published figure actually extracted? axes
from the figure or assumed? like columns? same σ basis? any floored `obs_limit=1.0` flat-band point?
run.options honored? empty-`Events/` / undecayed-sparticle signatures? 1-D collapse? untagged container
routing?). For the spine classes D4–D19 + N1–N6, walk the same attack list the adversarial
harness fires: did every narrated next step actually launch compute (D4), or did a turn claim a
background job that wasn't live (phantom)? did every long job self-report and get caught by the watchdog
(D6)? was the generation recipe fetched before generating a BSM/HV model (D7), and a fix-search run
co-primary on a diagnosed failure (D8)? is the PRIMARY figure bound to the approved target with a composed
side-by-side (D9), and is the CHECK-IN-2 waypoint plot the contracted `figure_target` output, not a
hand-rolled one (D5)? were varied parameters validated before the scan (D10), the smoke rung PASSed before
full/scan (D11), acc×eff certified before the limit (D12), every trap obligation discharged (D13), and the
SR yields plausible before statistics (D14)? did every baselined-file edit carry a DEVIATIONS row (D15),
was the tool surface-reconciled at commit (D16), every step routed through intake (D17), the step-9
umbrella (`validate_run_state --rundir`) actually reached (D18), and every required artifact
provenance-checked, not backfilled (D19)? did the first `Skill` in a physics session route through
`physicist-intake` (N1), did all point/scan outputs land in-tree, not `/tmp` (N2), was every armed
fire-command preflighted (N3), every LHE consumed only after its producer completed (N4), no number
sourced from an open-defect helper (N5), and every long job harness-tracked rather than `nohup`-detached
(N6)? An attack that lands becomes a panel finding in the standard format; skip an inapplicable attack class. New failure classes that survive verification are added here (what goes
wrong → how it is caught → where the guard lives).
