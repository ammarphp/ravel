# FAILURE CATALOGUE — the failure modes this project actually hit

> Records track. Every entry is a REAL incident: **what happened → how it was caught →
> where the guard now lives.** Entries marked *guard: PENDING* are open fixes tracked in
> `docs/development/change-registry.md` (CR-001/CR-002; dev repo: OPERABILITY-CHARTER §3 F6). New
> incidents that survive verification get an entry here via the postmortem-capture skill; the
> entries also seed the P4 routing/behavior evals. Paths marked *(dev repo)* are development
> records not present in the public distribution.

## A. Figure & comparison integrity

**A1 — Caption-imagined figure.** The first RRR-Fig-3 difference map was rendered as a smooth filled
heatmap invented from the CAPTION TEXT, without ever extracting the published figure (which is a sparse
blocky per-cell map). Caught: extracting Fig 3 itself from the arXiv source and putting the side-by-side
in the check-in — the form mismatch was immediate (dev-repo commit a1b41bf). Guard: the figure contract —
no counterpart ships without `extracted_image` + a side-by-side composite (`checklists/figure-contract.md`,
`figure_target.py declare/attach/compose`, the check-in figure gallery in `checklists/check-ins.md`).

**A2 — Axis-scale overcorrection (failed BOTH ways).** Counterparts were rendered linear where the
published axis is log; then, after a log-Δm house rule was adopted, log where the published axis is
LINEAR. Caught: the side-by-side against the extracted published figure. Guard: axes are CONTRACT
FACTS, not defaults — read off the published figure at declaration into `figure_target.json:axes` and
consumed by renderers via `--figure-target` (`figure_target.py`, `checklists/plot-guidelines.md`,
`checklists/check-ins.md`); heuristics allowed only with `axes.source="assumed"`.

**A3 — Expected-vs-observed column mixup.** The published-reference comparison initially mixed limit
columns: RRR Fig 3's "ATLAS" dots decode to the Fig 16a EXPECTED contour (tip m≈238 GeV), so overlaying
our OBSERVED µ₉₅ against them compared unlike columns. Caught: forensically decoding the published
figure's dots/cells before trusting the overlay. Guard: the LIKE-COLUMNS rule — `scan_contour.py
--limit-kind observed|expected|both` renders only self-consistent variants (`steps/08-scan.md`,
dev-repo commit acb1b62); the check-in caption states which column is drawn.

**A4 — σ-comparison-basis mismatch.** Our σ-UL was quoted on the ISR-TAGGED 6-state SAMPLE σ while the
published UL is on the INCLUSIVE 4-state MODEL σ — a mass-dependent ×0.56→×1.01 spurious tilt that
inflated the headline residual (33% vs the real 26%). Caught: the on-contour identity check — ON the
published exclusion contour, UL/σ_model must equal 1 (measured 1.10 on the right basis; 1.47/0.74 on
wrong ones). Guard: `scan_orchestrator rebase --process` maps ULs onto the published model σ and records
the basis in `scan.json:model_basis`; decomposition in the scan's RESULT.md *(dev repo:
`trial-runs/sleptonscan_fig3_SCAN/RESULT.md`)*.

**A5 — Legend/annotation text occluding the data.** Rendered figures repeatedly placed legend text on
top of the drawn data (supervisor-reported across visuals); root cause was an ENFORCEMENT gap, not a
missing rule: the house style's collision-aware `smart_legend` existed and two renderers used it, while
`scan_contour.py` bypassed it with four raw `ax.legend(loc=…)` calls — a checklist line
("legend … occludes nothing", plot-criteria) with no gate behind it. Caught: supervisor eyeball, twice.
Guard: all renderers route through `mplhep_style.smart_legend` (CR-015), and the machine gate LANDED
2026-07-06 (CR-016): `mplhep_style.lint_figure` runs inside every house renderer at save time and
exits 4 on legend/boxed-annotation occlusion of drawn data, box↔box overlap, or tick-label collisions
(`plot_lint.py --selftest` proves both directions). The residual class that motivated it — fixed-corner
ANNOTATION boxes clipping data (the fig3 lower-left box vs the ATLAS contour tail) — is closed the same
way: `smart_annotate` scores corners and falls back to a below-axes caption when every corner is
occupied, and the gate verified the fix on the live 52-point artifacts (it caught the grid panel's
uncleanable corners AND the fig3 legend's contour-line occlusion before passing the final render).

**A6 — Ungrounded "consistent with the publication" claims.** Agreement was asserted in prose without
an artifact-level comparison behind it (user-caught twice in the early sessions; the transcript mining
ranked it the #1 user-caught class). The words "matches", "consistent", "agrees" carry a debt: WHICH
published number/figure, WHICH artifact of ours, at WHAT tolerance. Caught: supervisor challenge, both
times. Guard: the verification ladder (`checklists/verification-ladder.md`) — agreement claims are rung
statuses with evidence citations, gaps are CONFIRMED only by bracketing; panel Tier-A FAILs a missing
ladder; Tier-B attack: pick any prose agreement claim and demand its rung row.

## B. Statistics & normalization

**B1 — pyhf µ-floor on hyper-excluded points.** `pyhf_exclude.py` bracketed µ upward from 1 and never
DOWN: points with CLs≪0.05 across the whole grid returned `obs_limit=1.0` with a flat [1,1,1,1,1]
band — a floored µ then becomes a huge fake σ-UL. Caught: dark-red saturated diff-map cells
(+1200–1450%) plus flat-band inspection of `exclusion.json`. Guard (CR-001, 2026-07-06):
`pyhf_exclude.py` brackets DOWN (floor 1e-6) + `at_mu_floor` flag (`selftest` is the regression);
`scan_orchestrator harvest_point` tags floored/capped/legacy points `quality=...`;
`scan_contour` renders them as '×' bounds, never colored as measurements.

**B2 — `ptj1min` silently dropped by the native card prep.** `prepare_native_slepton.py` rendered the
raw run-card template and applied only nevents/iseed/ebeam/pdlabel/use_syst — the TOML's
`[madgraph.run.options]` (ptj1min=50) was never applied natively, so samples generated at ptj1min=0.
Measured: σ_tag 42.83 vs 19.99 fb (×2.14), a tag-definition drift vs the reference sample. Caught: a
cross-run σ_ref consistency check (same card, ×2.1 σ) chased down to a 500-event A/B. Guard (CR-002,
2026-07-06): the prep applies the full block fail-loud (missing file/block/key = die) from the point's
own TOML; pre-fix samples are flagged in `reference/native-pipeline.md`; the rescan is CR-004.

## C. Silent generation & environment failures (exit 0, wrong output)

**C1 — Width-only DECAY tables → empty SRs.** MadGraph's default restrict card writes total widths with
NO BR rows; Pythia imports nothing and the sparticles never decay — plausible LHE, empty signal regions,
exit 0. Caught: empty-SR forensics traced to the source (`SLHAinterface.cc` + a direct shower test).
Guard: `lhe_check.py` is MANDATORY pre-shower (CLAUDE.md; `.claude/rules/madgraph-pythia.md`;
`checklists/model-cards.md`: explicit BR rows + MODSEL).

**C2 — A guard itself false-FAILing: lhe_check on wide resonances.** The fixed ±1 GeV mass tolerance
FAILed Breit-Wigner event-record masses of wide s-channel signals (Γ≈30–50 GeV) though the banner mass
is exact; a conscious override was needed. Caught: the CMS dijet generality trial's GAP list (protocol
`framework/TRIAL-CMS-ABC-DIJET.md`, dev repo). Guard (CR-007, 2026-07-06): `lhe_check.py` reads each
expected PDG's Γ from the banner's `DECAY` headers and widens the EVENT-mass tolerance to
max(--mass-tol, 3Γ); the banner-mass check stays tight. Both pipeline drivers now RUN the gate
(native: stage 1b pre-shower; container: post-madgraph, ahead of detector/analysis).

**C3 — MadGraph "success" with no events.** `<procdir>/bin/generate_events` outside the mg5 conda env
exits 0 while "A fortran compiler is required" appears only in the procdir debug log; more generally MG
can report done with an empty `Events/`. Caught: the CLAUDE.md "confirm `Events/<run>/` non-empty" rule
(~10 min lost, ATLAS AD trial). Guard: that rule + the `run-stage` skill — never trust generation exit 0.

**C4 — `conda run <<heredoc` passes NO stdin.** The script body silently never executes (exit 0).
Caught: live native-scan driver debugging (read_toml did nothing). Guard: CLAUDE.md gotcha +
`.claude/rules/madgraph-pythia.md` — write `/tmp/x.py` then `conda run -n <env> python /tmp/x.py`
(or `python -c`), as `run-pipeline-native.sh` now does.

**C5 — Unrendered `{{ecms}}` placeholder reaches MadGraph.** The mapyde base run card is a jinja
template; an unrendered placeholder crashes generation with "'{{X}}' can not be mapped to a float".
Caught: a live scan point crashed. Guard: fail-loud placeholder scan after rendering — any remaining
`{{` dies naming the leftovers (`prepare_native_slepton.py`, render guard).

**C6 — Disk-full mid-scan + orphaned-Delphes truncation (a scan killed itself two ways).** The
CR-004 rescan left ~6 GB of regenerable intermediates PER POINT (MadGraph events + procdir, Delphes
ROOT, HepMC) with no cleanup → the disk hit 100% and 8 points died with `NoSpaceLeftError` at the
MadGraph stage; separately, when the driving process exited, in-flight Delphes stages were killed
mid-write, leaving a truncated `delphes.root` with no `Delphes` tree → `sumweights=0` →
`ZeroDivisionError` in Delphes2SA (4 more points, FAIL@analysis, rc=1 in ~3 s). Both classes were
transient (35 sibling points succeeded on the same cards). Caught: `df` at 100% + the analysis-log
`Cannot find tree with name Delphes`. Guard: **`scan_babysitter.py`** — cleans the heavy regenerable
subdirs from every COMPLETED point (curated exclusion.json/*.txt/*_patch.json/*.png preserved per the
.gitignore curation policy), HEALS failed + stale-running points back to pending (removing the
truncated intermediates), and FEEDS pending points only while free-disk ≥ `--min-free-gb`. Reclaimed
218 GB on first run; the record-scan lesson is now a tool, not a manual chore.

**C7 — Healed-point σ_ref harvest gap → silent rebase failure → wrong-basis numbers.** A scan point
that FAILED and was re-run by `scan_babysitter.py` (CR-029) can produce a `madgraph.log` WITHOUT the
`Cross-section :` summary line (MadGraph reused a cached refine and did not re-print it). `sigma_ref_fb`
parsed only that line → returned None → the point had no σ_ref → `scan_orchestrator rebase` aborted →
the σ-UL comparison silently ran on the WRONG basis (sample σ, not model σ), inflating the CR-004
residual to a bogus 71% / −56% before it was caught. TWO compounding faults: the harvest fragility AND
a completion-watcher that fired at 50/52 on a `status` race (2 points mid-transition read as done).
Caught: the number was wildly off the clean partial (−0.8%) and the model_basis flag was False after a
"successful" run. Guard: `sigma_ref_fb()` falls back to `analysis.log`'s `Using cross section X` (the
same pb value fed downstream) when madgraph.log lacks the summary; and NEVER trust a σ-UL comparison
whose `rebase` did not print "rebased N points onto the inclusive model-σ basis" / whose scan.json
`model_basis` is not True. The honest full-grid CR-004 number is 22.0% residual / PDF +6.5%
(`docs/development/change-registry.md` CR-004 FINAL).

**C8 — Rivet `pluginONNX` routine with no shipped `.onnx` weight file → unconditional `init()` crash
(masquerading as an unrelated conda-path bug).** `ATLAS_2022_I2182381.cc`'s `init()` unconditionally
calls `_nn = getONNX(name())`; `rivet-build` on the stock share `.cc` first fails to compile
(`onnxruntime/onnxruntime_cxx_api.h` not found — `onnxruntime` isn't in the `rivet` conda env), and
even after installing `onnxruntime` (available on conda-forge, `osx-arm64`, confirmed) the routine
would still throw at `init()`: upstream Rivet (`gitlab.com/hepcedar/rivet`,
`analyses/pluginONNX/ATLAS_2022_I2182381.*`) ships the `.cc/.info/.plot` but NEVER committed the
matching `.onnx` weight file — confirmed absent both in the installed rivet 4.1.3 conda package and
upstream (GitLab API tree listing of `analyses/pluginONNX/`; sibling analyses in the same directory
DO ship their `.onnx`, e.g. `ATLAS_2022_I2172216.onnx`, `CMS_2026_I3125663.onnx`). A prior session's
WORKLOG mis-attributed this stall to the unrelated relative-conda-path bug (a real but different
class of failure seen elsewhere in the census) because the Jun-15 retry died silently on the compile
error without updating the record. Caught: task 7.1 resume — direct read of `rivet_build.log` plus a
GitLab API cross-check of the upstream repo tree. Guard/fix: when a `pluginONNX` routine's `init()`
crashes or won't compile, check for the `.onnx` file's existence (locally AND upstream) before
assuming an environment fix will help — some `pluginONNX` analyses are missing their weight file
entirely. If the target SR family doesn't read the NN discriminant (verify by source read: no shared
variables, no `vetoEvent` in the NN-scoped block), a run-local patch removing the ONNX
load + the disjoint NN block (documented `RESULT.md`/`DEVIATIONS.md`, share untouched — same
registrar-owned precedent as the `conf2016037` routine-defect case) unblocks the CC/non-NN yields
with zero physics impact on them. File an upstream Rivet report (missing data file, not a code
defect) — not yet done for this analysis.

## D. Doc & process drift

**D1 — 1-D-line collapse.** Sessions repeatedly shrank the deliverable to a single point or a 1-D Δm
line when the product is the 2-D mass-plane contour; a stale checklist line ("the 1-D line is the local
ceiling") kept reinstalling the drift. Caught: user re-assertion + the full transcript audit
(`docs/development/history/mission-and-plan.md` drift list). Guard: step 8's deliverable is the 2-D contour
(`steps/08-scan.md`; `checklists/scan-and-contour.md`: "a 1-D Δm line … is only a partial PoC").

**D2 — VM-default doc drift.** Docs kept routing SimpleAnalysis to the podman/amd64 container although
the native chain is proven bit-for-bit (141/141 SRs; full-point µ₉₅ parity to 0.51%) — hedging
reinstalled a ~9 h/point cost model. Caught: the reconciliation grep `podman|VM|container|emulat|amd64`
over docs/workflow/. Guard: native is THE default (`reference/native-pipeline.md`, steps 04/08); every
container mention must be tagged legacy/fallback; re-run the grep after doc edits.

**D3 — Fresh-session routing failure.** Real physicist sessions did not route on "Initiate…" and burned
tokens surveying dev docs (4 sessions); mild recurrence later: a survey launched before routing left a
stray output dir outside the run tree (cleaned; recorded in that run's DEVIATIONS.md). Caught: live
physicist trials. Guard: the two-session fork at the top of CLAUDE.md/AGENTS.md + `docs/workflow/start.md`
(dev-repo commit 0467f6e) — NOT yet verified on cheap models; the charter P4 routing evals own that proof.
**ROOT MECHANISM found (2026-07-06 transcript mining):** fresh sessions launch with cwd at the repo's
PARENT (`DSRLab/`), where the repo's CLAUDE.md is lazy-loaded nested memory — INVISIBLE at turn 1; 5/5
un-hinted sessions failed, and a one-sentence workspace pointer was proven sufficient in a live relaunch.
Guard (landed): the PARENT-LEVEL router `DSRLab/CLAUDE.md` (reproducible copy:
`framework/parent-router-CLAUDE.md.template` — re-install it if the workspace moves). CAVEAT recorded in
ROUTING-EVALS.md: the P4 7/7 PASS injected the working-directory hint into every subject prompt — i.e.
it measured the POST-router condition before the router existed; the un-hinted launch is the honest
re-eval condition now that the router is installed.

### The workflow-adherence spine (D4–D18) — one hard gate per class

> The 2026-07-08 spine build (design spec `docs/superpowers/specs/2026-07-08-workflow-adherence-hardening-design.md`)
> converted the invoke-only gate layer into mechanized enforcement. Each class below is a REAL failure
> mode of the 10h16m SVJ t-channel trial (session `8cc9ce64`: 22 supervisor interventions, no
> deliverable) or its five forensic audits, and each now names the gate that FIRES on its trigger
> (spec §5) and the `framework/spine_sim` case that re-fires it every `make green`. These CONTINUE the
> D-series above; the map is authoritative in `tests/adversarial/README.md` (G0a–G27).

**D4 — Narrate-without-execute; nothing forces the next compute (no DRIVE).** In the SVJ trial the agent
repeatedly ended a turn by *describing* the next stage ("next I'll generate…") without launching it — no
mechanism forced the compute, so the run stalled between gates until a human nudged it (a core driver of
the 22 interventions). Caught: the transcript audit — a turn with a pending `run_state.next_required`, no
`compute_launched`, and no live background job, that is not blocked at a named human gate. Guard: **G4** —
the `stop_dispatch.py` DRIVE branch (CR-064) exits 2 on exactly that signature and feeds the D4 reason
back to the agent; the step-end self-drive rule lives in `docs/workflow/steps/03-generate.md` ("Self-drive at
step end (DRIVE/D4)"). verified-by: spine_sim **`case_G4.py`**. *Observed in the wild (2026-07-06 SVJ trial, pre-spine): ≥2 turn-ends on next-step prose with no compute ("Starting the card build now"; "I'll go quiet while generation runs") — QA.6, ~4 load-bearing nudges to CHECK-IN 2 (QL.1).*

**D5 — Hand-rolled plot substitutes for the contracted waypoint figure (INTEGRITY, waypoint).** A
CHECK-IN-2 turn shipped an ad-hoc matplotlib plot in place of the contracted `figure_target compose`
output, so the waypoint figure was never bound to the declared published target. Caught: a CHECK-IN-2
delivery turn whose PRIMARY `figure_target.json` has `side_by_side: null` → `validate_run_state.py
--rundir` exits nonzero and the umbrella blocks. Guard: **G11** — only `figure_target.py checkin` output
satisfies the waypoint-aware `inv_figure_contract_fulfilled`, enforced through the D18 umbrella Stop
branch (moves the binding forward from step 9 to the CHECK-IN-2 waypoint). verified-by: spine_sim
**`case_G11.py`**.

**D6 — A live hang never self-reports (no CATCH).** A stage that hung (100% CPU, no forward progress) sat
silently for hours; there was no watchdog, caffeination, or timer to notice, and no failure record to
force re-invocation. Caught: wall-clock overrun vs `cost_preflight` + an unhandled `*.failure.json` under
the rundir. Guard: **G6** — `stage_supervisor.py` wraps the stage (wall-clock + progress-stall + flat-RSS
+ exit-0-plausibility) and SIGTERM/SIGKILLs the hang so the background job completes and the harness
completion notification fires carrying a `failure.json` + next action; the `stop_dispatch.py` CATCH
branch refuses turn-end while an unhandled `*.failure.json` exists. verified-by: spine_sim **`case_G6.py`**. *Observed in the wild (SVJ trial): the first merged shower hung in traceHVcols and was killed by an external SIGTERM after a physicist nudge — no monitor existed (QG.2); two believed-alive processes were dead/hung when checked (QG.4).*

**D7 — Generation recipe not fetched before generating a BSM/HV model (no PREVENT).** A `mg5`/shower
launch for a BSM / hidden-valley model proceeded without first fetching the external generation recipe
(the census R6 rung), risking a silently wrong process or card. Caught: a `run-pipeline-native.sh
trial-runs/<run>` launch whose contract declares `targets.model=SVJ` with no fetched recipe on disk.
Guard: **G9** — `resource_census.py --assert-pre-generate` (CR-094) + the `pre-generate-guard.sh`
PostToolUse guard hook (CR-095) BLOCK (exit 2) any generation Bash call before the recipe is fetched; the
gate is documented in `docs/workflow/steps/03-generate.md`. verified-by: spine_sim **`case_G9.py`**. *Observed in the wild (SVJ trial): the correct generation recipe (eshwen/SemivisibleJets, CMS svjHelper) was cloned Jul 8 19:18 — AFTER the 17:55–18:04 shower attempts had already hung on a mismatched Contur s-channel template (QF.1).*

**D8 — External fix-search ordered last, not co-primary, on a diagnosed failure (no RESOLVE).** On a
diagnosed stage failure the agent debugged locally and reached for the external recipe/fix search only as
a last resort, so a known upstream fix was found late (or not at all). Caught: an OPEN
`failure_class=tool_generator_model` record with no `inputs/recipe_search.json`. Guard: **G8** —
`resource_census.py --debug recipe-search` (tool+model+symptom-keyed, CR-091) runs CO-PRIMARY inside the
`stage-recovery` skill (CR-093); `--assert-recipe-search` + the `stop_dispatch.py` recipe-search branch
(CR-092) refuse to close the failure without a `recipe_search.json`. verified-by: spine_sim **`case_G8.py`**.

**D9 — Headline artifact not bound to the approved target; mid-flight amnesia of the contract (INTEGRITY,
primary).** The delivered headline figure drifted from the CHECK-IN-1-approved published target — a
counterpart was rendered with no composed side-by-side against the declared figure. Caught: a deck turn
whose PRIMARY `figure_target.json` has a `generated_counterpart` but `side_by_side: null`. Guard: **G10** —
`figure_target.py primary/fulfil-primary` + the now primary-aware `inv_figure_contract_fulfilled` in
`validate_run_state.py`, which hard-FAILs on a null PRIMARY counterpart/side-by-side in ALL modes.
verified-by: spine_sim **`case_G10.py`**. *Observed in the wild (SVJ trial): the primary Figure-5 side_by_side path was hand-populated into figure_target.json with no producing script; compose ran only for the non-primary Figure 3a; the assembler had 0 references to the contract (QI.2).*

**D10 — Parameter validation dropped/mis-filed before a scan (no VALIDATE).** The varied-parameter
validation was skipped or written to the wrong place, so wrong physics could reach a launched scan
unchecked. Caught: a scan launch whose `inputs/validations.json` varied-param obligation is still
`PENDING`. Guard: **G12** — `validate_parameters.py` writes `inputs/validations.json` and the
`inv_param_validated_before_scan` invariant in `validate_run_state.py` FAILs a scan with a PENDING/FAIL
validation. verified-by: spine_sim **`case_G12.py`**. *Observed in the wild (SVJ trial): f_inv floored at ~0.56 while labelled R_inv 0.1–0.9; the scan + CHECK-IN 2 anchor ran on the broken axis; f_inv validation ran belatedly at the physicist's insistence → full discard + re-run (DEVIATIONS.md:142, QJ) — inputs/validations.json did not exist.*

**D11 — The dry→smoke→full→scan ladder is ungated (no ladder waypoint).** A full/scan launch could skip
the smoke waypoint entirely, spending long compute on an unproven configuration. Caught: a full/scan run
that reached generation with no smoke-rung PASS in `logs/ladder.json`. Guard: **G13** — the
`inv_ladder_order` invariant in `validate_run_state.py` (+ the `run-scan` pre-launch refusal) blocks
unless the smoke rung has a PASS artifact. verified-by: spine_sim **`case_G13.py`**.

**D12 — acc×eff cert not forced before yields feed a limit (no certify).** A limit-shipping mode
(including scan) could publish an exclusion with no acceptance×efficiency certification behind the yields.
Caught: a scan shipping an exclusion with no discoverable acc×eff cert (the per-point `scan.json`
attestation does not substitute). Guard: **G14** — the `inv_certify_before_limit` invariant in
`validate_run_state.py` FAILs any limit-shipping mode without a non-FAIL cert before statistics/result_pack
pass. verified-by: spine_sim **`case_G14.py`**.

**D13 — Trap route-consequences flagged but never checked (no trap-obligations).** A physics trap (T1
interference / T8 per-width / T12 scheme) was flagged in the trap sweep, but its route-consequence
obligation was never discharged before the gated stage. Caught: a T8 hit with a `PENDING` (undischarged)
`trap_sweep.json` obligation at generation. Guard: **G15** — typed `{trap, obligation_kind, artifact,
status}` obligations + the `check_trap_sweep` / `inv trap-obligations-discharged` invariant in
`validate_run_state.py` require `status==PASS` before the gated stage (generalizes D10 to T1/T8/T12).
verified-by: spine_sim **`case_G15.py`**.

**D14 — No analysis→statistics plausibility gate; a vacuous "not excluded" ships (no plausibility).**
All-zero SR yields flowed straight into statistics, producing a degenerate huge µ95 and a vacuous "not
excluded" that BOTH cutflow validators PASSed. Caught: all-zero SR yields → degenerate huge µ95 →
`sr_plausibility.json` verdict `implausible`. Guard: **G16** — the `sr_plausibility.py` emitter (≥1
non-trivial SR; driving-SR acc×eff in band; µ95 not floor/degenerate) is folded into `check_statistics`
(CR-085) as a hard FAIL, not a PASS. verified-by: spine_sim **`case_G16.py`**.

**D15 — DEVIATIONS gate is post-hoc + narrow-trigger, not moment-of-change.** A CHECK-IN-1-baselined file
was edited without a DEVIATIONS row, and the old post-hoc/narrow-trigger check did not catch it at the
moment of change. Caught: an Edit to the baselined `inputs/task_contract.json` with no DEVIATIONS.md row
naming it. Guard: **G17** — the edit-time `deviations-guard.sh` PostToolUse hook (+ the
`deviations_on_change` invariant) BLOCKS (exit 2) a baselined-file edit lacking its DEVIATIONS row.
verified-by: spine_sim **`case_G17.py`**.

**D16 — `directory-keeper` / `embed-and-commit` advisory → drift ships (no embed/commit gate).** A tool
could be added without a workflow-doc embed or a `DIRECTORY.md`/agent-surface reconcile, so drift shipped
uncaught. Caught: a staged export tree whose `docs/workflow/*.md` references a nonexistent path. Guard: **G20** —
the installed git `pre-commit` hook (`install_git_hooks.sh`, CR-100) runs `check_agent_surface.py --stage`
and BLOCKS the commit on a dead ref / FAIL. verified-by: spine_sim **`case_G20.py`**.

**D17 — Clean-room un-hinted routing unproven; D3 recurs (no self-drive gate).** There was no repeatable
proof that a fresh, un-hinted session launched from the DSRLab parent cwd routes correctly instead of
surveying the dev repo (the D3 failure recurring). Caught: a fresh un-hinted `claude` that surveys the dev
repo, never emits `task_contract.json`, or generates before CHECK-IN 1. Guard: **G21** —
`tests/adversarial/clean_room.py --live` (CR-106) launches the un-hinted self-drive and records
`self_drive/last_verdict.json`; `make green-self-drive` attests the recorded verdict == PASS (SKIP, never
a false PASS, when the artifact is absent). verified-by: spine_sim **`case_G21.py`**.

**D18 — The verification lifecycle is invoke-only; a run can skip step 9 wholesale (the umbrella).**
Nothing forced the step-9 verification panel — a run could deliver a CHECK-IN / results deck / RESULT.md
without ever running the panel and no gate fired. Caught: a delivery-signature turn whose rundir does not
pass `validate_run_state.py --rundir`. Guard: the **umbrella** — the `stop_dispatch.py` D18 PRIMARY branch
blocks any delivery turn unless `validate_run_state.py --rundir` exits 0, folding `verify_pack` + every
invariant (D5/D9–D14/N2/N4 + provenance) into one Stop gate; the specific classes above are what the
`validate_run_state` umbrella enforces. verified-by: the umbrella re-fires through spine_sim `case_G11.py`
(the D5 waypoint via the `d18` branch) and every invariant-family case.

**D19 — Backfilled/stale required artifact clears a presence-only gate (PROVENANCE).** A required
physics-lifecycle artifact (`sr_plausibility.json`, whose implausible verdict hard-FAILs statistics,
D14/CR-085) can be faked two ways once gates check presence alone: (a) an agent hand-types `{"verdict":
"plausible"}` with no `generated_by`, or (b) a genuine artifact is left in place after the
`sr_yields.json` / `exclusion.json` underneath it changed, so the recorded verdict no longer describes the
current inputs. Either way a green gate certifies a physics claim the tool never actually produced.
Caught: `validate_run_state.py --rundir <rundir> --verify-provenance` — the `generated_by` check rejects
(a) (G19 part 1, CR-088), and an `input_fingerprint` recompute over the declared inputs (the same
plausibility-domain canonicalization the emitter uses) rejects (b) when the stored fingerprint no longer
matches (G19 part 2). Guard: **G19** — `verify_provenance_lifecycle` in `validate_run_state.py` (selftest
cases 18–19; wired into the step-9 Tier-A `--verify-provenance` checkbox, `checklists/verification-panel.md`)
— provenance, not presence. verified-by: spine_sim **`case_G19.py`** — the L6 per-gate harness
(`framework/spine_sim`) re-fires this exact class every `make green`. (Numbered D19 — the cross-cutting
provenance invariant surfaced during the spine build; it is gate G19, a principle the umbrella runs, not
one of the spec's D4–D18 spine classes above.)

### Transcript-only signatures (N1–N6) — the 2026-07-09 completeness critic

> Added 2026-07-09 by the transcript completeness-critic re-reading the SVJ trial: the failure set is
> larger than the first five-audit enumeration. Each cites the trial turn(s) that exhibited it and the
> gate that now catches it (spec §5).

**N1 — A physics request loads a downstream skill before the mandatory intake gate (skill-precedence).**
The session's first `Skill` was `new-analysis` (trial [10]→[107]), skipping the mandatory
`physicist-intake` gate; the physicist had to correct it ([69]). Caught: a first `Skill` ≠
`physicist-intake` with no active-run `task_contract.json`. Guard: **G22** — the `pretooluse-skill.sh`
PreToolUse-on-`Skill` guard exits 2 unless `physicist-intake` is first (no `new-analysis`/`run-*` before
the contract exists). verified-by: spine_sim **`case_G22.py`**.

**N2 — Primary compute ran in the /tmp scratchpad, outside the curated rundir (in-tree-outputs).** 26
per-point yields were written under `/tmp` instead of the rundir, invisible to `verify_pack` /
`directory-keeper` / `.gitignore` (all of which key on the rundir). Caught: a `scan_manifest.json` point
whose `run_dir` resolves under `/tmp`. Guard: **G23** — the launcher rejects a `/tmp`/scratchpad `OUTDIR`
and the `inv outputs-in-tree` invariant in `validate_run_state.py` FAILs if a manifest point's evidence is
not under the rundir. verified-by: spine_sim **`case_G23.py`**.

**N3 — A backgrounded watcher's fire-command is never smoke-tested (armed-command-unvalidated).** A
completion-watcher's fire-command (a 3-arg call to a 5-arg script) was launched un-tested and crashed
hours later at SCAN-DONE, invisibly. Caught: an armed watcher with no preflight artifact on disk at
turn-end. Guard: **G24** — `preflight_watcher.py --arm` (`bash -n` + arity probe, CR-096) refuses to arm a
watcher whose fire-command fails preflight and writes `logs/<watcher>.preflight.json`; the
`stop_dispatch.py` armed-watcher branch (`--assert-all`, CR-097) refuses turn-end without it. verified-by:
spine_sim **`case_G24.py`**. *Observed in the wild (SVJ trial): the wait_and_assemble watcher held a 3-arg call to a 5-positional script — it would have crashed at SCAN DONE; the physicist hand-wrote the corrected rearm (QG.3).*

**N4 — A generation output is consumed while still being written (producer-barrier).** A downstream stage
read an LHE mid-write — "grabbed the LHE mid-write, 7031 not 10000 events" ([548]); C3's non-empty check
passes a half-written file. Caught: a `.lhe.gz` whose banner `nevents` ≠ its counted `<event>` records.
Guard: **G25** — the `inv producer-complete` invariant in `validate_run_state.py` blocks the consumer
until MadGraph's terminal `Cross-section :` line is present, the gzip decompresses to EOF, AND banner
`nevents` == counted events. verified-by: spine_sim **`case_G25.py`**.

**N5 — A helper flagged defective is worked around, not fixed (open-defect-reuse).** A helper named in an
unresolved defect note (`read_yoda.py`, "A×ε reads 956%") was worked around rather than fixed, so it
re-emitted the wrong number across the run ([548]→[913]). Caught: a delivery turn-end with an unresolved
`open_defect_notes[]` entry. Guard: **G26** — the `verify_pack.py` open-defect gate + the `stop_dispatch.py`
open-defect branch (CR-098, gated on `is_delivery`) block a number sourced from the flagged helper from
feeding a comparison/check-in until the note is resolved or the blessed tool is substituted. verified-by:
spine_sim **`case_G26.py`**. *Observed in the wild (SVJ trial): read_yoda.py's 956% A×ε bug stayed on disk unfixed through run end (QM.4).*

**N6 — `nohup` detachment silently defeats the completion-notification lever (detach-defeats-drive).** A
`nohup`-detached long job silently defeated the harness completion-notification lever the DRIVE/CATCH
design depends on and blinded the physicist ([1313]/[1319]). Caught: a `bg_kind=detached`
`compute_launched` entry missing `logfile`/`done_condition`/`next_action` with no live heartbeat. Guard:
**G27** — the `stop_dispatch.py` detach branch refuses turn-end for such a job; DRIVE mandates
harness-tracked `run_in_background`, or a durable `run_state.json` (pid/logfile/done-condition/next-action)
+ a harness-visible heartbeat for a genuinely detached job. verified-by: spine_sim **`case_G27.py`**. *Observed in the wild (SVJ trial): "I see no background tasks" — nohup-detached scan jobs were invisible to the harness and the physicist for hours (QG.5: run_state.json absent, the autonomous-completion guarantee hollow).*

**N7 — A source is asserted blocked/unavailable without a recorded attempt (assert-blocked-without-attempt).**
The SVJ trial wrote "HEPData is Cloudflare-blocked" into its survey notes (survey_tagger.md:15,
survey_routine.md:22) without ever trying `hepdata_fetch.py --tables` in the `reinterp` env — the JSON
API worked; the false belief drove over-conservatism (trial QB.4). Caught: the mandatory step-2 resource
census records REAL fetch attempts + results per rung, so an "unavailable" claim without a recorded
attempt has no census row backing it. Guard: **D18** umbrella — `inv_resource_census_before_route`
requires `inputs/resource_census.json` (the attempt ledger) before routing ships; source-ladder protocol
P6 orders the retry. verified-by: the census invariant selftest + `test_resource_census_gates.py`.

**N8 — Subagent fan-out before routing (fan-out-before-routing).** On the fresh physics prompt the trial
launched an 8-agent survey Workflow BEFORE any task contract existed (trial QA.1) — a wrong-GRANULARITY
sibling of N1's wrong-skill-first: the guard covered `Skill` only, so Agent/Task fan-out sailed past the
intake gate. Caught: an Agent/Task tool call in a session whose route-pending marker
(`logs/.route-pending-<session>`, touched by the UserPromptSubmit router on physics classification) is
present with no session-scoped `task_contract.json`. Guard: **G22** extension (CR-118) — the PreToolUse
guard (matcher `Skill|Agent|Task`) exits 2 until the contract exists, then consumes the marker.
verified-by: `test_pretooluse_skill.py::test_agent_fanout_blocked_while_route_pending`.

**N9 — The enforcement surface is edited mid-run to escape a gate (enforcement-disarm).** An agent that
finds a gate inconvenient edits `.claude/settings.json`, a hook, or a gate tool instead of satisfying the
gate — the agentic sibling of "edit the test, not the code". Never yet observed in a trial (this entry is
pre-emptive: R3 made it impossible before it was ever attempted). Caught: a PreToolUse Edit/Write to the
enforcement surface (settings/hooks/spine_sim/green_board/Makefile/the 12 gate tools) in a session with a
route-pending marker or a session-scoped run_state. Guard: **G22**-family PreToolUse —
`protect-enforcement.sh` (CR-126) exits 2 with "make enforcement changes in a dev session".
verified-by: `test_protect_enforcement.py`.

## Tier-B adversary: use this catalogue as your attack list
When running the step-9 verification panel's **Tier B** (`docs/workflow/checklists/verification-panel.md`),
walk this catalogue top to bottom BEFORE free-form attacks: for each entry A1–D19 + N1–N6, attempt the
same failure class against the current run's artifacts (was the published figure actually extracted? axes
from the figure or assumed? like columns? same σ basis? any floored `obs_limit=1.0` flat-band point?
run.options honored? empty-`Events/` / undecayed-sparticle signatures? 1-D collapse? untagged container
routing?). For the spine classes D4–D19 + N1–N6, walk the same attack list the `framework/spine_sim`
harness fires: did every narrated next step actually launch compute (D4), or did a turn claim a
background job that wasn't live (phantom)? did every long job self-report and get caught by the watchdog
(D6)? was the generation recipe fetched before generating a BSM/HV model (D7), and a fix-search run
co-primary on a diagnosed failure (D8)? is the PRIMARY figure bound to the approved target with a composed
side-by-side (D9), and is the CHECK-IN-2 waypoint plot the contracted `figure_target` output, not a
hand-rolled one (D5)? were varied parameters validated before the scan (D10), the smoke rung PASSed before
full/scan (D11), acc×eff certified before the limit (D12), every trap obligation discharged (D13), and the
SR yields plausible before statistics (D14)? did every baselined-file edit carry a DEVIATIONS row (D15),
was the tool embedded + surface-reconciled at commit (D16), the un-hinted self-drive green (D17), the step-9
umbrella (`validate_run_state --rundir`) actually reached (D18), and every required artifact
provenance-checked, not backfilled (D19)? did the first `Skill` in a physics session route through
`physicist-intake` (N1), did all point/scan outputs land in-tree, not `/tmp` (N2), was every armed
fire-command preflighted (N3), every LHE consumed only after its producer completed (N4), no number
sourced from an open-defect helper (N5), and every long job harness-tracked rather than `nohup`-detached
(N6)? An attack that lands becomes a panel finding in the standard format; an attack class that cannot
apply is skipped silently. New incidents that survive verification are APPENDED here (what
happened → how caught → where the guard lives) — this file is append-only and also seeds the routing/
behavior evals (dev repo: charter P4).

## Appended 2026-07-11 — run 2026-07-08_PROJ_hvt-zprime-ww-isr-boosted (projection, Option C)
- **B3 — fiducial-generation-cut limit compared on the inclusive σ×BR axis (T9 class; the run's headline error).**
  What happened: projected limits were normalized per 1 pb of σ(pp→Z'+jet, ptj>150)×B (the sample's
  own fiducial basis) and overlaid on the inclusive σ(pp→Z')×B axis with theory + published curves —
  17–53× too strong; the interim "excludes HVT Model A" reading was false. How caught: step-9 Tier-B
  fresh-context adversary (review 1, FAIL), by comparing the sig_vzj vs thy_vz banners. Where the
  guard lives: run-level `inputs/basis_manifest.json` now REQUIRED to carry the limit curve's own
  basis + transformation (this run's file is the template); extract-stage signal normalization must
  name its reference σ basis explicitly (`s_at_1pb_incl`, `isr_fraction` fields); Tier-B attack list:
  "does any generation-level cut make the sample fiducial, and is every limit axis explicitly
  inclusive-or-fiducial?" Registry: CR-125.
- **C9 — UFO analytic width formulas go COMPLEX below decay thresholds (authors' model, low-mass regime).**
  What happened: HVT_UFO internal WVz/WVc analytic total widths contain per-channel phase-space roots
  (√(M⁴−4m_t²M²)) that go complex below the tt̄ threshold → MadGraph "Width should be real number"
  crash for every m(Vz)<2m_t — the entire target window. How caught: generation crash at param-card
  load (loud, not silent). Where the guard lives: run recipe — externalize widths + `set W<X> Auto`
  (MadWidth evaluates open channels only); recorded in the run's `inputs/model/PROVENANCE.txt` +
  DEVIATIONS D1. Registry: CR-123 note.
- **C10 — MadWidth returns a NEGATIVE partial width just above a 2-body threshold (Γ(Vz→WW)<0 at m=170, m/2m_W≈1.04).**
  What happened: the m=170 extension point crashed with "Partial width for vz > W- W+ negative";
  the follow-on launch then silently re-ran the previous (1000 GeV) card. How caught: generation log
  + banner mass check on the produced run. Where the guard lives: near-threshold points are OUT of
  the standard chain's validity (β³ suppression + NWA breakdown anyway) — declare, don't patch
  (DEVIATIONS D5); always re-verify the banner mass of any run produced after an in-script exception.
- **C11 — lhe_check banner-MASS false-positive for UFOs that store the BSM mass outside Block MASS.**
  What happened: the gate FAILed a good m=200 LHE ("banner MASS m=2000") because HVT_UFO keeps m(Vz)
  in RHOINPUTS and the Block MASS line is a stale dependent copy; the first-event check also fired on
  a legitimate BW tail (Γ=8.4 GeV, bwcutoff 15Γ). How caught: direct banner read (RHOINPUTS=200) +
  5000-event mass median (202.7). Where the guard lives: PENDING (CR-123) — lhe_check should read the
  mass param via its lhablock when Block MASS lacks the PDG, and offer a median-mass mode; interim
  guard = the run's process_sample.sh median gate.
- **N9 — pyhf_exclude `at_poi_cap` marks bracket granularity, not a capped limit.**
  What happened: `at_poi_cap:true` fires whenever the doubling bracket reaches the 128 cap (any +2σ
  crossing >64), so finite median limits (50–94 pb) were drawn as ">128 pb" arrows on the deliverable.
  How caught: Tier-B review 2 (post-fix), cross-checking `capped` flags against `exp_limits`. Where
  the guard lives: consumers must define capped := median ≥ cap (this run's run_limits.py does);
  proper fix PENDING (CR-124) — pyhf_exclude should emit `median_at_cap` distinct from `at_poi_cap`.
- **D19 — check-in-promised figures delivered as prose; deliverable shipped with one figure (PHYSICIST-caught).**
  What happened: CHECK-IN 1 §(iii) promised two waypoint artifacts at CHECK-IN 2 (mass-peak
  distribution; σ-vs-theory identity figure); the waypoint was recorded as PASS with text numbers
  only, no intermediate-stage figures were drawn, the figure contract was never declared, and the
  final deck carried a single overlay — the physicist had to ask "where are the plots?". How caught:
  physicist feedback after delivery (the deck validator checks figure PRESENCE, not the
  promised-artifact list; the step-9 panel attacked numbers, not the visual-completeness contract).
  Where the guard lives: PENDING (CR-126) — validate_checkin should cross-check deck figures[]
  against CHECK-IN 1's promised waypoint artifacts + require the composed side_by_side for the
  primary figure-contract target on any run that generated samples; interim guard = the D6 artifact
  set pattern (waypoint pair + intermediate trio + staged summary + composites) as the deck's
  default figure complement.
- **A8 — a digitized curve's first point placed at a mass outside the paper's stated derivation range.**
  What happened: the survey digitized ATLAS 1710.01123's qqA HVT limit with its first point at
  200 GeV; the paper text derives qqA limits FROM 250 GeV — the point cannot exist at 200. The
  "coverage reaches 200 GeV" claim propagated into two runs' conclusions. How caught: the (belated)
  figure-contract declaration for Figure 11a forced a read of the paper's limit-range sentence (D7).
  Where the guard lives: digitization must record the paper's STATED mass range alongside the
  digitized arrays and assert first/last point inside it (basis-manifest field `stated_range_gev`);
  the figure-contract declare step is the natural place this gets read — declare BEFORE digitizing.
- **D20 — 8-agent survey fan-out died at a session limit; 6/8 sweeps + 15/15 verify agents lost (nothing persisted).**
  What happened: the toponium-summary run launched an 8-sweep + 15-verify workflow; the session
  token limit hit mid-flight, every unfinished agent errored out, and only the 2 sweeps that had
  already returned structured output survived (as in-context results, not files) — the verification
  tier was lost entirely and the run shipped with survey-grade literature numbers under an approved
  flag (F6). How caught: workflow task-notification with per-agent "session limit" errors; the gap
  is visible as RESULT.md limitation[2] of trial-runs/2026-07-06_ttthreshold-excess-summary_*.
  Where the guard lives: PENDING (CR-132) — fan-out agents write findings to disk incrementally
  (per-agent scratch JSON) so partial research survives; interim practice = save returned agent
  output to inputs/survey/*.json immediately (this run did, post-hoc).
- **N10 — HEPData bulk endpoints blocked server-side from this host; harvest rerouted through the in-app browser's AJAX endpoint.**
  What happened: hepdata_fetch.py and direct HTTP (curl/WebFetch) drew 403s + robot-check timeouts
  on hepdata.net record/download endpoints, blocking the summary-plot harvest. How caught:
  immediately (fetch failures at step 2.0). Where the guard lives: EMBEDDED (CR-129) —
  docs/workflow/checklists/data-acquisition.md now carries the browser-route recipe: record JSON via
  /record/ins<ID>?format=json in the browser pane, table values via the site's own
  /record/data/<recid>/<table_id>/<version> AJAX endpoint, double-transcription checksum
  (independent second in-browser fetch, per-column sums + endpoints), provenance JSONs under
  outputs/hepdata/ marked "browser-transcribed, internally checksummed, R6-validated".
- **N11 — intake produced no run_state.json for a summary_plot contract; the open-defect gate never evaluated.**
  What happened: route_prompt.py + physicist-intake scaffolding wrote task_contract.json but no
  run_state.json for the compute=none track; verify_pack.py could only [INFO]-skip the
  open-defect (G26/N5) gate for the whole run. How caught: verify_pack [INFO] line at step 9.
  Where the guard lives: PENDING (CR-131) — intake initializes a minimal run_state.json
  (session id, contract pointer, empty open_defect_notes) for EVERY contract, compute=none included.
- **A9 — a physicist-facing spot-check quoted a survey read-off where the exact harvested value existed.**
  What happened: CHECK-IN 2's identity table carried "ATLAS 4-top tanβ≈1.2 → ct≈0.833@400" from the
  survey's figure read-off while the harvest JSON already held the exact HEPData value
  (1.17110074 → 0.85390); the two differ by 2.5%. The deliverable was unaffected (the renderer
  reads only harvest files) — the defect lived in the check-in table. How caught: step-9 Tier-A
  hand line-check (claim-vs-artifact). Where the guard lives: EMBEDDED (CR-130) —
  docs/workflow/checklists/summary-plot.md now requires identity/spot-check rows to use exact harvested
  values wherever a harvest exists; read-offs are pre-harvest only and must be labeled "read-off".

## Appended 2026-07-13 — run 2026-07-11_SUSY-2020-04_higgsino-proj-replane (projection + replane, no-generation)
- **B4 — pyhf_exclude expected-band DEGENERACY at weakly-constrained points (exit 0, wrong band).**
  What happened: at f=1 grid point (mH=125, dM=0.25) the engine's five expected-band quantiles
  came back identical to 3 decimals (all ≡1.94) while the observed limit was 59.7 and the
  published-equivalent µ95 ≈ 47 — an unusable "band" delivered with exit 0. How caught: the
  replane driver's band-width sanity (healthy qtilde ±2σ bands span ×2.5–4; this one spanned
  ×1.005) + cross-check against the direct CLs(µ=1) hypotest which matched the published value.
  Where the guard lives: run-locally in build/replane_run.py (BAND_RATIO_MIN=1.5 filter +
  mu95_dropped_points.json); engine-level guard PENDING (CR-132: degenerate/narrow-band WARN in
  pyhf_exclude.compute; quote such points as bounds only).
- **B5 — scipy/SLSQP SILENT wrong CLs (≡1.0/0.0) on tightly-constrained workspaces (exit 0).**
  What happened: on luminosity-projected workspaces (relative uncertainties tightened ×1/√f or
  ×1/f), single-µ hypotest with the default scipy optimizer returned CLs values of exactly
  1.0000/0.0000 scattered non-monotonically across the grid (e.g. frozen (150,0.75)=1.0000
  between two ≈0.01 neighbors), plus 8/102 hard FailedMinimization crashes in the engine's
  µ-scans. How caught: a cross-scenario monotonicity audit (CLs_frozen ≤ CLs_stat ≤ CLs_syst
  point-wise) + per-scenario grid inspection; minuit on identical workspaces gave smooth grids
  (0 violations; Tier-B reproduced 3 points to 6 digits). Where the guard lives: run-locally in
  build/proj_cls.py (minuit-first + per-point isolation + the monotonicity audit in its output);
  engine-level optimizer-robustness PENDING (CR-132).
- **B6 — published per-point σ-UL tables on an UNSTATED ≈σ_total/4 normalization (T9 in the wild).**
  What happened: figaux_04a/b "cross-section upper-limit per signal point" values divided by the
  (validated) per-point µ95 gave a σ(m) curve ×3.93 BELOW the paper's own quoted total
  (3.95 pb at (150, 0.5)); the table description does not state which σ is limited. How caught:
  the F9 self-consistency extraction's external anchor (the paper's own sentence) FAILED at 10%
  tolerance; P5 decomposition separated it from the (independent) B4 artifact point. Where the
  guard lives: the F9 anchor pattern itself (extract → anchor against the paper's own quoted
  number → STOP on fail) is now precedent; deliverables route around absolute σ entirely
  (signal-strength-space fold, DEVIATIONS D2). Upstream note candidate for the analysis contacts.
- **A10 — published exclusion contour NOT reproducible from the published per-point map (tip gap).**
  What happened: the Fig-3 expected contour's tip sits at m(N1)=168.47 while linear AND cubic
  interpolation of the published 34-node CLs map cannot cross 0.05 beyond ≈159 — the published
  curve encodes a finer internal map that was not published. How caught: the f=1 waypoint overlay
  (branches coincided; only the tip diverged), then a direct interpolation-ceiling test. Where
  the guard lives: DEVIATIONS D1 precedent — contour comparisons declare the shared lattice
  convention and quote the residual as a bound; the deliverable overlays the published curve
  itself so nothing hides. Upstream: finer published CLs maps would close it.
- **A11 — replane fold queried the exclusion surface at the WRONG mass coordinate (caught by Tier-B).**
  What happened: the (µ, M₂) fold built its CLs surfaces on m(χ̃₁⁰) but queried them at the fold
  row's m(χ̃₁±) — a systematic ~Δm (0.4–0.9 GeV) offset; impact 11/7992 points (conservative
  direction), no headline feature moved. How caught: step-9 Tier-B fresh-context review
  (finding 8), which also MEASURED the fix's expected impact; the applied fix landed exactly on
  the panel's numbers (991→996). Where the guard lives: fixed in build/replane_run.py with the
  coordinate convention now stated at the query site; the panel's own re-derivation preserved as
  build/reach_crosscheck.py; catalogue entry = the attack ("check every surface lookup's
  coordinate convention against the surface's construction").
- **C12 — a GUARD script silently no-ops via the conda-stdin trap (the gate that always passes).**
  What happened: process_repro.sh (REPRO run 2026-07-11) fed its median-mass gate via
  `conda run python - <<heredoc` — the documented C-class stdin trap, but INSIDE a guard: python
  received an empty script, exited 0, and the gate "passed" for all 5 samples without ever running
  (it was also hardcoded to the wrong PDG for 2 of them, which is how Tier-B caught it: the WZ
  samples could never have passed a gate that actually ran). How caught: Tier-B finding 4
  (process-integrity audit); masses were independently verified correct (LHE medians + retro-runs
  of the fixed gate, 5/5 PASS). Where the guard lives: gates must be FILE-BASED scripts with a
  loud zero-match FAIL path, and a gate's own output line in the log is the evidence it ran — a
  chain log with no gate line is a skipped gate. The deeper lesson: the conda-stdin trap is worst
  inside guards, where exit-0-on-empty-script masquerades as PASS.

## Appended 2026-08-28 — run 2026-08-27_taunu-recast-ins1649273-ins1684340_U1-leptoquark (head-to-head test B intake; adjudication §II.4 honesty ledger)
- **N12 — deterministic router classified off keyword hits inside model-DESCRIPTION text; the mass extractor accepted √s and a bin edge as masses.**
  What happened: the verbatim U1-leptoquark recast prompt (a pasted research note with Lagrangian
  + glossary + binned-data tables) drew task_mode=projection from the literal word "projection" in
  "- $P_L$ is the left-handed projection operator.", and masses_gev came back
  [13000 (=√s), 5000, 3200 (=an mT bin edge)] — the request's actual 9-value 750–5000 GeV grid
  ("750, 1000, …, 5000 GeV", one trailing unit) was unparsed. How caught: the live run's agent
  flagged both in the contract (assumption rows + flag F1) and the adjudication recorded them as
  honesty items; the gates held (no compute was mis-spent), but the front door misread the ask.
  Where the guard lives: EMBEDDED (CR-133) — route_prompt.py classifies and extracts on a
  model-prose-masked view (glossary bullets + math dropped; "projection operator" phrase-excluded)
  with list-aware, plausibility-filtered mass extraction (table rows / binning context / √s-in-
  collider-context are not masses). Regression: the verbatim prompt in `route_prompt.py --selftest`
  (dev tree) + `tests/unit/test_intake_u1_defects.py` (both trees).
- **N13 — no detector_mode existed for "custom Delphes, uncertified"; the route nuance lived in a free-text assumption.**
  What happened: the run's plan used Delphes (stock ATLAS/CMS cards) driving custom, uncertified
  selections — no enum value fit, so the contract recorded detector_mode=particle-level with the
  actual route buried in assumptions[] where no gate reads it. How caught: adjudication §II.4
  honesty item 6. Where the guard lives: EMBEDDED (CR-134) — `delphes-custom-uncertified` in the
  contract + result-pack enums and PRODUCT-CONTRACT §2; validate_run_state's route gate WARNs
  with the no-exclusion-of-record obligation; validate_checkin FAILs a CHECK-IN 1 that hides the
  uncertified status.

## Appended 2026-08-28 — run 2026-08-28_SMMEAS_hvt-zprime-ww-lowmass (SM-measurement-derived Z'->WW estimates; usage-limit interruption + successor close-out)
- **N14 — figure annotation text GUESSED from a plan-stage prediction instead of read from the machine artifact the same script had just written.**
  What happened: the CHECK-IN 2 waypoint figure's annotation said the m=300 GeV signal template
  "peaks in the 185–360 GeV bins" — pasted from the CHECK-IN 1 waypoint PREDICTION
  (`inputs/checkin1.json` §iii) — while the renderer's own machine artifact
  (`outputs/waypoint_m300.json`, written in the same invocation) showed the template actually
  peaks in the 140–220 GeV bins (endpoint 276.6 GeV analytic). The physics direction (below the
  resonance mass) was right; the numbers were a guess. How caught: the original session's final
  self-review of the rendered figure — its literally last act before a usage-limit kill (fix
  edited + re-rendered at 01:05, session died ~01:06); the successor session then re-rendered
  through the lint gate (byte-identical) and swept EVERY remaining numeric prose/figure claim
  against its artifact (28-check audit, `VERIFICATION-LADDER.md`), finding one more instance of
  the same class (a "~3–5%" gloss of per-bin residuals +3.7/+4.3/+1.8/+5.6/−1.8% in
  `inputs/checkin2.json`, amended pre-resolution). Where the guard lives: PENDING (CR-136) —
  annotation strings containing numbers should be composed FROM the artifact dict in code, or an
  annotation-vs-artifact number-trace should join the render gate; until then the manual
  annotation audit at close-out is the (procedural) guard. Attack replay for Tier-B: grep every
  `smart_annotate`/caption numeric literal and demand its artifact field.
- **N15 — a DEVIATIONS entry overturned a physics reading but the artifact carrying the superseded reading was not touched; two contradictory statements coexisted on disk.**
  What happened: `outputs/survey.json`'s EWPT candidate said "Model A g_V=1 requires
  M_V ≳ 1.3–1.5 TeV … the ENTIRE 150–500 GeV window is EWPT-disfavored" (written 00:56); minutes
  later DEVIATIONS D2 resolved the two-pass source conflict the OTHER way (no robust sub-TeV
  EWPT bound for Model A g_V=1, the conservative reading) — and the census entry was left
  stale for the rest of the run. How caught: the successor session's close-out audit
  cross-reading survey.json against the DEVIATIONS ledger (D4f). Where the guard lives:
  PENDING (CR-137) — a deviation that resolves/overturns a reading should NAME every artifact
  carrying the superseded text (like the D15/G17 rule already does for baselined-input edits);
  procedural until embedded.

## Appended 2026-08-28 — run 2026-08-28_SUSY-2018-16_slepton-fig3-fresh (fresh flagship 52-point scan; the CR-006 clean-room self-drive evidence run)
- **N16 — `conda run` captures child stdout/stderr until process exit, so the stage-supervisor's log-mtime stall watchdog sees a frozen log and kills healthy long stages.**
  What happened: the smoke-rung pyhf stage was killed rc=124 'progress-stall' TWICE — first for
  the real signal-starved-log defect (pyhf_exclude's CLs bracketing scan emits nothing for ~18
  min), then AGAIN after a flush=True heartbeat was added, because plain `conda run` (conda
  26.3.2, this host) buffers ALL child output and replays it only at exit: the log stayed 0 bytes
  for the entire stage and the mtime watchdog cannot distinguish that from a hang. Under capture,
  EVERY stage longer than its stall budget would be spuriously killed — the primary failure mode
  for an unattended 12-h scan. How caught: the second kill's 0-byte `pyhf.log` contradicted the
  in-code heartbeat; a 6-s heartbeat probe run both ways (captured vs `--live-stream`) bracketed
  the cause (smoke_m150_dm20/logs/pyhf.failure.json ×2 kept as evidence). Where the guard lives:
  `run-pipeline-native.sh` — `--live-stream` on exactly the 8 supervised stages + the
  `pyhf_exclude.py` cls_at() heartbeat + `stage_supervisor.py` PYHF_MEASURED_MIN=20 (the 12-min
  flat budget under-measured the workspace-sized, event-count-independent 17.3-min CLs scan);
  selftest 3/3 PASS. Tool edits applied in-tree, commit deferred to the orchestrating session
  (CR-138/CR-139). Attack replay for Tier-B: for any supervised stage, ask whether its log grows
  DURING the stage on this launcher, not just after.
- **A4 re-hit (new surface) — the tagged-sample vs inclusive-model σ-basis trap reached `certify_acceptance.py` as a uniform ~2.7× acceptance excess.**
  What happened: the first waypoint cert FAILed with every SR ~2.7× high — the run's `acceptance`
  column divides by the generated ISR-TAGGED 6-state σ while the published Fig 32a-f denominator
  is the inclusive 4-state model σ; exactly the A4 basis class the record scan's rebase fixed at
  the LIMIT surface, now re-hit at the CERT surface, where no guard or docstring warned. How
  caught: the uniform (SR-independent) excess pattern pointed at a denominator, not the detector
  chain; conversion f=σ_tag6/σ_incl4_LO=0.3843 (the same table the rebase uses) turned FAIL into
  PASS at 1.01–1.06 (outputs/acceff_cert_m150_dm20{,_incl4}.md, both kept). Where the guard
  lives: PENDING (CR-140) — certify_acceptance should warn (like `_basis_guard` in scan_contour)
  when the denominator σ source is a generation log rather than a model-σ table; until then the
  recipe lives in this run's DEVIATIONS entry and the certify skill's known-trap list is the
  procedural pointer.
- **N17 — a check-in's verification NUMBER was derived by hand OUTSIDE the assembler's basis path: the k-factor was double-counted and the wrong anchor survived into the proxy go-ahead.**
  What happened: the fresh flagship's CHECK-IN 2 waypoint anchor computed the UL as
  mu95_raw x sigma_incl4_LO x k_nlo=1.4 by hand — but mu95_raw already carries the flat k=1.18
  signal normalization baked into the fit patch, so the derivation applied x1.186 too much and
  reported "+0.1% exp / -15.1% obs" vs ATLAS Fig 44ab where the assembler's own path
  (scan.json mu95 x sigma_ref) gives -15.6% / -28.5%. The flattering wrong number fed the
  physicist-proxy PROCEED and propagated into DEVIATIONS, RESUME, the verification ladder and
  the RESULT draft. How caught: the step-9 Tier-B fresh-context adversary re-derived the anchor
  from scan.json + the published UL grid (finding 1, MAJOR); all affected records corrected at
  close-out (CR-137 discipline: every artifact carrying the superseded number named + fixed).
  Where the guard lives: PENDING (CR-141) — anchor comparisons quoted at any check-in must be
  COMPUTED by a tool that reads the assembled artifacts (scan.json/exclusion.json + the
  reference yaml), never hand math in check-in prose; same class as N14 (guessed annotation),
  one level up: hand-DERIVED, not hand-copied. Attack replay for Tier-B: re-derive every
  check-in anchor from the artifacts and diff.
- **C13 — `pythia_shower` with no event count showers Pythia's default 1000 events of a 20k LHE, exit 0 (silent 1/20 statistics).**
  What happened (2408.00049 width run, 2026-08-28): the first 20k campaign wave passed no `<N>`
  arg and no `Main:numberOfEvents` in the cfg; every point showered exactly 1000/20000 events
  with exit 0 — per-σ normalization unaffected (weights carry σ), statistics silently 1/20 of
  the approved plan. The 1k smoke masked it (counts matched there by coincidence). How caught:
  per-point cutflow `all` (=analyzed events) vs the LHE `<event>` count during wave-1 review.
  Where the guard lives: run driver `build/gen_point.py` passes `<N>` explicitly AND hard-fails
  on analyzed≠LHE count (the 8b gate); run-stage skill §Shower now marks `<N>` MANDATORY
  (CR-145). Attack replay for Tier-B: diff every point's analyzed-event count against its
  banner `nevents`.
- **C14 — the narrow-state per-event mass gate (±3Γ) false-FAILs a legitimately wide lineshape (bwcutoff tail).**
  What happened (same run): `lhe_check --expect-mass` rejected the first Γ/m=0.15 point on a
  tail event at m=42 GeV — a legitimate member of the bwcutoff=15Γ lineshape; the check is
  calibrated for narrow states and is meaningless by construction at large Γ/m. How caught:
  stage failure triage read the event against the declared width convention (W4). Where the
  guard lives: width-aware gating in the run driver — narrow (auto-width) points keep the full
  gate; wide points run `lhe_check` WITHOUT `--expect-mass` (producer-complete/weights still
  gated) plus direct banner assertions (MASS exact; DECAY width within 1%); recorded as the
  W-convention interaction in the run's `inputs/width_conventions.md` (CR-146 owner: lhe_check
  `--width-aware` mode PENDING).
- **N18 — a stale-output cleanup glob (`m20_w*.json`) also matched an anchor artifact (`m20_wnarrow.json`) and deleted it AFTER fits had consumed it.**
  What happened (same run): the wide-point relaunch cleanup glob was written for the five
  `m20_w{05..30}` width tags but `m20_w*` also matches `m20_wnarrow`; the anchor's per-point
  provenance JSON (+yoda) vanished after the L2 fits had used it. How caught: the missing file
  surfaced at the fit-aggregation re-read; the regenerated point (identical seed 101) was
  diffed at close — template rebuild BIT-IDENTICAL (integral 2949.387674, max per-bin Δ 0.0),
  so no quoted number was touched. Where the guard lives: procedural — cleanup deletions must
  enumerate exact tags (never glob a tag prefix that is itself a prefix of another tag), and
  any deleted-then-regenerated input is diffed against the consuming record before close
  (this run's DEVIATIONS entries 7/8 are the worked example). Attack replay: ask whether every
  fit input still exists on disk and matches its consuming record.
- **N19 — orphan-cleanup `pkill` patterns matched by PROCESS NAME, not rundir, and killed a concurrent session's MadGraph worker.**
  What happened (same run): `pkill -f madevent|pythia_shower|generate_events` during a
  campaign relaunch killed at least one madevent worker of the CONCURRENT run
  (CR005cert_ss_1200_600); MG's survey loop respawned it (self-healing), but the kill crossed
  session boundaries on a shared machine. How caught: the other session's log showed the pid
  death; the pkill pattern audit followed. Where the guard lives: procedural rule — kill
  strictly by rundir-path match (`pkill -f <this-rundir-path>`), never by bare tool name;
  memory note `concurrent-overnight-sessions.md` carries the shared-machine discipline.
- **N20 — the plot-lint occupancy sampler counts only data VERTICES, so a legend frame (framealpha 0.85) visibly washed out sparse 6-point curves while the gate passed.**
  What happened (this run's width figure, 2026-08-29): the 9-entry legend landed on the curve
  region; its translucent white frame faded line SEGMENTS between widely-spaced markers — only
  ≤3 sampled vertices sat inside the box, under `tol_points=3`, so `enforce_lint` passed a
  visibly occluded figure. How caught: human-eye review of the rendered PNG at step 8.5.
  Where the guard lives: FIXED 2026-09-05 (CR-147) — `_occupancy_points` now samples visible
  transformed line segments at bounded display-space spacing, preserving NaN breaks, steps,
  marker-only lines and clipping. Sparse crossings, log axes and off-axes cases are covered
  in `tests/unit/test_plot_lint_segments.py`; `plot_lint.py --selftest` passes.
- **N21 — fit artifacts stamped `r5_status: closed` from a SUPERSEDED validation configuration (the as-run density-bug closure numbers), one anchor silently absent; the headline "layered tolerance met" re-labeled layer failures.**
  What happened (2408.00049 width run, caught 2026-08-29): `inputs/r5_points.json` carried the
  R5 closure doc's AS-RUN numbers ("obs 0.948/0.891", 2 anchors) while the run's own L1 fits
  used the CORRECTED counts config whose observed ratios are 0.944/0.534/0.513 — the 0.891 was
  the doc's own documented accidental cancellation, and m40 was absent from the reference list
  entirely; RESULT.md then summarized F6 as "MET WITH ONE MARGINAL ELEMENT" though L1(125) obs
  missed by 28% in g and L2/L1 exceeded its 15% target at 2 of 3 anchors. How caught: the
  step-9 Tier-B fresh-context adversary recomputed every anchor ratio from the artifacts
  (round-1 FAIL). Where the guard lives: procedural + the panel itself — R5 reference points
  must quote the SAME input configuration the run fits (cite the closure table variant), name
  ALL anchors, and state the closure axis + tolerance (closure-doc rec. 3: expected axis);
  reproduction verdicts must be stated layer-by-layer against the pre-agreed criteria, never
  net-envelope-only. Same family as N15 (superseded reading left in an artifact) and A6
  (ungrounded "consistent with publication"), new surface: the machine-readable r5 stamp.
  Attack replay for Tier-B: recompute r5_reference_points from the artifacts + the published
  grid and diff against the stamped basis text; check every pre-agreed tolerance layer
  separately.
