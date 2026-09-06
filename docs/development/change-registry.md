# CHANGES REGISTRY — dated, findable record of every adjustment (ADR-style)

> Binding per `docs/development/history/operability-charter.md` §7: **every change lands here** — pending fixes are
> registered when diagnosed, marked EMBEDDED when the fix + its doc/skill wiring land. Fields per
> entry: **ID · date · what · why · where-embedded · status**. Status ∈ OPEN (diagnosed, fix not
> landed) · DEFERRED (decided, scheduled later) · EMBEDDED (fix + workflow wiring landed) ·
> SUPERSEDED. The `embed-and-commit` closing checklist is the enforcement point (charter §4.3).
> Real incidents behind these entries: `docs/reference/failure-modes.md`.

## Product-contract scope additions (registered 2026-07-08, Task 0.1 — doc-only, ahead of build)

### CR-030 — PRODUCT-CONTRACT §7 claim-integrity gate (I1; registered, OPEN — scope only)
- **Date registered:** 2026-07-08 (audit-and-fix Task 0.1).
- **What:** PRODUCT-CONTRACT §7 gains a claim-integrity rule: every headline/served claim in the
  SHIPPED docs (README, `docs/workflow/reference/*`, PRODUCT-CONTRACT) must map to a shipped,
  sha256-checksummed artifact via `evidence/manifest.json`; `export_distribution.sh` runs
  `check_evidence.py --check --stage` and ABORTS if any served claim lacks a checksum-matching
  shipped artifact. 'Shipped' means present in the export stage, not merely git-tracked in the dev
  repo.
- **Why:** a prose claim can silently outlive the artifact that backed it (the export stage curates
  a subset of the dev tree) — this closes that drift class before it is exploited.
- **Where-embedded:** PRODUCT-CONTRACT §7 (this entry). `evidence/manifest.json` +
  `check_evidence.py` are NOT YET BUILT — tracked as a later build task (`build_evidence.py` /
  `check_evidence.py`, `export_distribution.sh` wiring).
- **Status:** REGISTERED (open) — scope lands now; build is a separate later task.
- **Verify:** `python3 scripts/check_evidence.py --check` (read-only; checksums include
  `benchmarks/cases.json` as a shipped BENCH_* artifact, so this can show a TRANSIENT
  FAIL if run while a session is mid-edit on that file/the gluino-gbb run dir — rerun once that
  session settles, or `--root <export-stage>` to certify the curated public tree instead of dev)

### CR-031 — summary_plot acceptance gate: summary_audit.py R-SA1..8 (I4; registered, OPEN — scope only)
- **Date registered:** 2026-07-08 (audit-and-fix Task 0.1).
- **What:** PRODUCT-CONTRACT §7 gains the `summary_plot` acceptance rule: a `summary_plot`
  deliverable is ACCEPTED only when `summary_audit.py` passes rules R-SA1..8 (survey↔
  basis_manifest bijection; disposition completeness; no keyword-only exclusions — a dropped
  curve needs a physics/out-of-range/superseded reason class; legend label↔channel derivable from
  the candidate's survey `final_state`; superseded curves rendered as cross-check, not co-equal;
  per-curve provenance+lumi+obs/exp labelled; drawn coverage annotations consistent with every
  candidate's stated reach; transformation stated). Until the gate is green the run is a declared
  PARTIAL, never 'served'.
- **Why:** the CR-023 summary-plot track (basis-manifest gate) checks curve MAPPING but not
  disposition/labeling/coverage honesty end-to-end; this closes the acceptance criterion the
  track was missing.
- **Where-embedded:** PRODUCT-CONTRACT §7 (this entry); CR-023 (the track this gate completes).
  `summary_audit.py` is NOT YET BUILT — tracked as a later build task.
- **Status:** REGISTERED (open) — scope lands now; build is a separate later task.
- **Verify:** `python3 src/ravel/validation/summary_audit.py --selftest && python3 src/ravel/validation/summary_audit.py --rundir trial-runs/2026-07-06_SURVEY_hvt-zprime-ww-lowmass`

### CR-032 — R5-as-machine-gate: shape_fit.json + validate_run_state.py blocking (I2; edits §6.1)
- **Date registered:** 2026-07-08 (audit-and-fix Task 0.1).
- **What:** PRODUCT-CONTRACT §6.1 (refusal case 1, R5 CLOSURE bullet) is EDITED: the old text said
  `shape_fit.py` "prints the gate on every run" (advisory only). New contract: `shape_fit.py` emits
  `shape_fit.json` carrying `{mu95_obs, mu95_exp, r5_status ∈ closed|held|na, r5_evidence}`;
  `validate_run_state.py` BLOCKS delivery of any `stat_mode=shape-fit` run whose
  `r5_status ≠ closed` — the gate now bites, not just prints. If R5 will not close, the run
  downgrades to `blocked-shape-fit` + the generator-level offer (unchanged).
  Note: CR-027's engine remains ENGINE EMBEDDED + R5 CLOSED for ins2813982; this entry changes only
  how the gate is ENFORCED (machine-blocking vs printed advisory), not the physics closure already
  won.
- **Why:** a printed gate a weak model can read past is not a gate; charter F1/F3 (weak models must
  be FORCED through scripts) applies to R5 exactly as it applies to every other hard gate in this
  contract.
- **Where-embedded:** PRODUCT-CONTRACT §6.1 (this entry, the R5-line edit). `shape_fit.json`
  emission + `validate_run_state.py`'s blocking check are NOT YET BUILT — tracked as later build
  tasks (the run-state validator + its emitters).
- **Status:** REGISTERED (open) — contract line edited now; build is a separate later task.
- **Verify:** `python3 src/ravel/validation/validate_run_state.py --selftest`

### CR-033 — projection + replane readiness gates (I7, I8; registered, OPEN — scope only)
- **Date registered:** 2026-07-08 (audit-and-fix Task 0.1).
- **What:** PRODUCT-CONTRACT §6 gains two readiness gates as refusal-case items 7–8:
  (a) **projection-readiness** — `task_mode=projection`/`stat_mode=sensitivity-expected-only`
  counting-mode limits are EXPECTED-ONLY and BRACKETED (stat/syst/frozen); a physicist-facing
  projection number ships only after an R5-analog published-projection round-trip closes (the
  stat–syst–frozen band must CONTAIN a published HL-LHC/Run-3 expected limit for a representative
  analysis at the published f); until closure, projection is spec'd-not-delivered, offered only as
  a labeled expected-only sensitivity study. (b) **replane-readiness** — a replane
  (`task_mode=reinterpret` via a composition/plane fold) ships a number only after a round-trip
  reproduces a paper's OWN published contour on the σ×BR leg within tolerance; composition-dependent
  A×ε is NOT re-simulated by the fold (declared caveat, trap T3). In both cases the existing
  self-consistency selftests (f=1 identity/scenario-ordering; round-trip identity/monotonicity) are
  named explicitly as NOT the R5 gate.
- **Why:** CR-024 (projection, spec complete) and CR-025 (replane fold, BUILT + selftested) both
  already carry an R5-class validation requirement in their own spec text, but PRODUCT-CONTRACT §6
  — the binding scope document — did not yet state it as a refusal-line gate; this closes that gap
  so the gate is contractual, not just tool-doc convention.
- **Where-embedded:** PRODUCT-CONTRACT §6 items 7–8 (this entry); CR-024 (projection module) and
  CR-025 (replane module, fold half BUILT) are the tracked build status this gate applies to.
- **Status:** REGISTERED (open) — scope lands now; the R5-analog round-trip validation runs
  themselves remain CR-024/CR-025's own open work (projection: OPEN; replane: fold BUILT,
  validation run remaining).
- **Verify:** `python3 src/ravel/physics/project_limits.py --selftest && python3 src/ravel/physics/replane.py --selftest`

### CR-034 — effmap-folded detector_mode + fidelity label (I6; registered, OPEN — scope only)
- **Date registered:** 2026-07-08 (audit-and-fix Task 0.1).
- **What:** PRODUCT-CONTRACT gains an `effmap-folded` row in both §2 (detector modes: published
  per-object/per-SR efficiency maps folded over truth objects, no detector sim of our own;
  LLP/displaced via D2 or no-routine SUSY via D1; fidelity ceiling = the map's documented accuracy
  e.g. ~25%, R5-gated per analysis, out-of-envelope → conservative under-coverage) and §5 (fidelity
  labels: published efficiency map folded over truth kinematics, no detector model of our own;
  evidence = map version + validity envelope + map systematic recorded in the basis manifest, R5
  closure at ≥2 published points).
- **Why:** CR-020 already BUILT the D1 folding route (`reinterpret_db.py --data-select
  efficiencyMap`) but PRODUCT-CONTRACT's detector-mode/fidelity-label taxonomy (§2/§5) had no entry
  for it — a served capability without a contract row is exactly the drift class this document
  exists to prevent.
- **Where-embedded:** PRODUCT-CONTRACT §2 + §5 (this entry); CR-020 (the D1 route this labels) and
  the D2 LLP design (`docs/workflow/reference/effmap-folding.md`).
- **Status:** REGISTERED (open) — the D1 route is already BUILT (CR-020); this entry is the
  contract-row backfill for it plus the label the D2 build will also carry.
- **Verify:** `python3 src/ravel/validation/validate_task_contract.py --selftest`

### CR-035 — capability-status-legitimacy: no self-upgrading served status (I13; registered, OPEN — scope only)
- **Date registered:** 2026-07-08 (audit-and-fix Task 0.1).
- **What:** PRODUCT-CONTRACT §5 gains a `capability-status-legitimacy` row: a `served`/
  `served-with-refusal` status in `capability-matrix.json` is legitimate ONLY while its named
  machine gate (`gate{kind,ref,artifact,green_when}`) is currently green AND its evidence artifact
  ships with a matching checksum; otherwise the reconciler forces the credited status down and R9
  is capped. A capability status NEVER upgrades itself. A heavy per-analysis R5 closure
  (gate kind=decision/deferred) can never credit `served` without a run. Enforced by
  `scripts/audit.py` reconcile over the per-prompt gate.
- **Why:** CR-019 built R9 (capability-coverage scoring) reading the matrix's status field, but
  nothing yet stops the status field itself from drifting ahead of its evidence — this is the
  no-self-upgrade invariant R9's own credibility depends on.
- **Where-embedded:** PRODUCT-CONTRACT §5 (this entry); CR-019 (R9, the consumer this protects).
  The `gate{}` schema + reconciler DOWNGRADE logic are NOT YET BUILT — tracked as a later build
  task (the audit.py reconcile pass, `.superpowers/sdd/progress.md` Task 5.1).
- **Status:** REGISTERED (open) — scope lands now; build is a separate later task.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_capability_gate.py" -q`

### CR-036 — authority-of-record + the full binding chain (I3, I2; extends §8)
- **Date registered:** 2026-07-08 (audit-and-fix Task 0.1).
- **What:** PRODUCT-CONTRACT §8 gains two additions (appended, the pre-existing binding-chain
  sentence is preserved verbatim): (a) an explicit **authority-of-record** statement —
  `benchmarks/capabilities.json` is the single source of STATE (served/partial/unbuilt;
  consumed by `audit.py`→`AUDIT.md`); `PLAN-OF-RECORD.md` states INTENT; `CAPABILITY-ROADMAP.md`
  states SEQUENCING; every prose readiness/served/refusal claim in
  STATUS.md/README.md/KNOWN-LIMITATIONS.md must reconcile to the matrix, enforced by
  `check_agent_surface.py` failing CI on contradiction; (b) the full run-leg binding chain:
  `route_prompt.py` → `validate_task_contract.py` (schema) → CHECK-IN 1 → [run] →
  `validate_run_state.py` (lifecycle: ordering + completeness + mode-invariants incl. R5 closure
  and likelihood↔selection pairing; stage matrix DERIVED from §1/§2/§3, legacy runs grandfathered)
  → `verify_pack.py` (artifact integrity) → step-9 panel.
- **Why:** three documents (matrix/PLAN-OF-RECORD/ROADMAP) can each look authoritative; without a
  named hierarchy a contradiction between them has no tie-breaker. The original §8 chain also
  stopped at CHECK-IN 1 and never named the POST-run gates (`validate_run_state.py`,
  `verify_pack.py`) that already exist elsewhere in this contract (§7) and in
  `docs/workflow/checklists/verification-panel.md` — §8 now names the full chain in one place.
- **Where-embedded:** PRODUCT-CONTRACT §8 (this entry, appended — NOT a rewording of the existing
  chain sentence, which stands unchanged). `validate_run_state.py` is NOT YET BUILT — tracked as a
  later build task; `check_agent_surface.py` and `verify_pack.py` already exist.
- **Status:** REGISTERED (open) — scope lands now; `validate_run_state.py` build is a separate
  later task.
- **Verify:** `python3 src/ravel/validation/check_agent_surface.py && python3 src/ravel/validation/validate_run_state.py --selftest`

## Audit-and-fix builds (2026-07-08 — landed, EMBEDDED)

### CR-037 — read-only verification tools (I12): audit.py --check default + run_benchmark write-suppression
- **Date registered:** 2026-07-08 (audit-and-fix Phase 1).
- **What:** `scripts/audit.py` gains argparse — default `--check` computes + prints readiness and
  writes NOTHING; `--write [--out]` regenerates `AUDIT.md`. `benchmarks/run_benchmark.py`
  defaults `--out` to a gitignored `.work/results.latest.json`; writing the tracked `results.json`
  baseline requires an explicit `--out` or `--update-baseline`. The existing exit-1 µ95/tier gate is
  unchanged; NO diff-and-fail mode added (a readiness board is DESIGNED to move — content drift is
  not a failure).
- **Why:** both tools overwrote their committed baselines on every run (the charter's "known clobber"
  + manual restore step); a verification/publish run must never dirty a committed artifact.
- **Where-embedded:** `scripts/audit.py`, `benchmarks/run_benchmark.py`,
  `tests/unit/test_audit_readonly.py`, `tests/unit/test_run_benchmark_out.py`; call-site
  docs (`OPERABILITY-CHARTER.md`, `OPS-PUBLISHING.md`, `verification-ladder.md`, `BENCHMARK.md`)
  drop the restore-the-clobber language.
- **Status:** EMBEDDED (2026-07-08).
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_audit_readonly.py" "$REPO/tests/unit/test_run_benchmark_out.py" -q` (read-only: subprocess-runs `audit.py` with no args only; `run_benchmark.py` is exercised via argparse introspection only, no physics execution, so this never touches `benchmarks/`'s shared state)

### CR-038 — single source of truth: gen_status.py + status reconciliation (I3; embeds CR-036)
- **Date registered:** 2026-07-08 (audit-and-fix Phase 2A).
- **What:** new `scripts/gen_status.py` machine-owns the readiness/capability PROSE inside
  `<!-- CAPABILITY-STATUS:* -->` marker blocks in STATUS.md/README.md/KNOWN-LIMITATIONS.md,
  computing the headline % from live `audit.CHECKS` and the board/capabilities from
  `capability-matrix.json` (never from the possibly-stale committed AUDIT.md). `--write` splices,
  `--check` diffs (exit 1 on drift), `--selftest` proves round-trip + count consistency. All stale
  status prose reconciled to the honest state (readiness 95%, R9 0.57, 1/7 served, shape-fit a
  SERVED engine, projection/replane/D2 BUILT); AUDIT.md regenerated to 95%; the authority-inversion
  resolved (matrix=STATE, PLAN-OF-RECORD=INTENT, ROADMAP=SEQUENCING) with LAST-RECONCILED stamps and
  the satisfied PLAN-OF-RECORD supersession clause deleted.
- **Why:** the only prior cross-doc guard checked a headline % in a label format the stale prose
  evaded; STATUS/KNOWN-LIMITATIONS/README/projection-replane/04-analyze/DECISION-SHAPE-FIT/DIRECTORY/
  ROADMAP/PLAN-OF-RECORD all contradicted the matrix (Catalogue D1/D3 drift class).
- **Where-embedded:** `scripts/gen_status.py` + the 13 reconciled docs; the enforcement guard
  is `src/ravel/validation/check_agent_surface.py`'s new `statefresh` check (Phase 2B):
  block-freshness (`gen_status --check`) + count/number consistency + forbidden-contradiction
  regexes keyed to matrix guards, scoped to current-claim lines only (dated-history/session-log/
  marker-block/roadmap lines exempt; a `no longer`-style negation guard prevents flagging current
  sentences that assert the opposite). Tests: `tests/unit/test_statefresh.py` (clean passes,
  stale claim caught, history line not flagged).
- **Status:** EMBEDDED (2026-07-08) — generator + reconciliation + enforced statefresh guard.
- **Verify:** `python3 scripts/gen_status.py --check && python3 src/ravel/validation/check_agent_surface.py`

### CR-039 — the I2 lifecycle-validator build: shape_fit.json/pairing_check.json emitters + validate_run_state.py + gate wiring + flagship backfill (I2; embeds CR-032, CR-036)
- **Date registered:** 2026-07-08 (audit-and-fix Task 3.1–3.3, consolidated).
- **What:** the full lifecycle-gate build CR-032/CR-036 registered as scope-only, landed in three
  parts. (1) **Emitters** (3.1): `shape_fit.py` gains `r5_status ∈ closed|held|na` +
  `r5_evidence` in `shape_fit.json` (the R5-as-machine-gate CR-032 asked for); `pairing_check.py`
  gains a `pairing_check.json` emitter (`{schema_version, bkg_workspace, patch, paired,
  n_channels, mismatches, verdict}`) alongside its unchanged exit-code CLI behaviour. (2) **The
  validator** (3.2): new `validate_run_state.py` — composes `validate_task_contract.validate()`
  (schema) then walks the 11-stage `STAGE_ORDER`/`STAGE_MATRIX` (per task_mode: task_contract,
  resource_census, trap_sweep, route, figure_contract, basis_manifest, generation, analysis,
  statistics, result_pack, verification) and 9 cross-stage invariants (resource-census-before-
  route, trap-sweep-recorded, basis-manifest-before-comparison, figure-contract-fulfilled,
  **R5-before-limit-ships**, **likelihood-selection-pairing** via `pairing_check.py`, blocked-
  shape-fit-refusal-recorded, DEVIATIONS-on-change, result-prose-matches-artifacts). A
  `GATE_EPOCH="2026-07-08"` migration grandfathers pre-epoch/no-`inputs/` runs (missing
  resource_census/trap_sweep/verification downgrade FAIL→WARN as `waived-legacy`; every value
  check that CAN run still runs at full severity). `--backfill-plan` prints (never writes) exactly
  what a run is missing. (3) **Wiring + flagship backfill** (3.3): `docs/workflow/steps/09-verify.md`
  Tier A now runs `validate_run_state.py --rundir` BEFORE `verify_pack.py`;
  `docs/workflow/checklists/verification-panel.md` gains the corresponding checkbox;
  `docs/workflow/steps/07-exclude.md` Mode A notes the `pairing_check.py` pre-limit gate for
  `stat_mode=published-likelihood` runs. The flagship `trial-runs/sleptonscan_fig3_SCAN` (the RRR
  Fig-3 52-point EwkCompressed2018 reproduction, PLAN-OF-RECORD's canonical proof) was backfilled
  with `inputs/{task_contract,resource_census,trap_sweep,figure_target,basis_manifest}.json` +
  `verification.json`, transcribed from its existing `scan.json`/`RESULT.md`/`DEVIATIONS.md`/
  `VERIFICATION-LADDER.md` records (resource_census run live against ins1767649; the other
  artifacts hand-transcribed, not invented) — this makes the run NON-legacy (no date-prefixed
  dirname), held to the full new-run gate rather than grandfathered.
- **Why:** CR-032/CR-036 registered the R5-machine-gate and the full binding chain
  (`route_prompt.py` → contract schema → CHECK-IN 1 → [run] → `validate_run_state.py` →
  `verify_pack.py` → step-9 panel) as scope-only, with the validator itself NOT YET BUILT; a
  printed gate a weak model can read past is not a gate (charter F1/F3), and the chain named in §8
  needs the tool it names to actually exist and be called at the step where the chain says it
  runs. Dogfooding the gate against the flagship (rather than only against synthetic fixtures)
  surfaces what a REAL run's records look like against the schema before the gate is trusted.
- **Where-embedded:** `trial-runs/_infrastructure/{shape_fit.py,pairing_check.py,
  validate_run_state.py}`; tests `tests/unit/{test_shape_fit_json.py,
  test_pairing_check_json.py,test_validate_run_state.py}` (+ `validate_run_state.py --selftest`,
  7 embedded fixture cases); `docs/workflow/steps/09-verify.md`, `docs/workflow/checklists/
  verification-panel.md`, `docs/workflow/steps/07-exclude.md`; `trial-runs/sleptonscan_fig3_SCAN/
  inputs/*.json` + `trial-runs/sleptonscan_fig3_SCAN/verification.json`. PRODUCT-CONTRACT §6.1
  (CR-032) and §8 (CR-036) are the contract rows this build embeds; both remain worded as
  registered there, unedited by this entry.
- **Scan-aggregator discovery (found by dogfooding, then FIXED same task):** the flagship backfill
  initially FAILed `generation`/`analysis` because every `task_mode=scan` aggregator dir (all 5 in
  the repo) keeps its per-point evidence in SIBLING dirs named by `scan_manifest.json`'s
  `points[].run_dir`, never inside the aggregator `--rundir`. FIX: `check_generation`/`check_analysis`
  are now scan-aware — for `task_mode=scan` a valid `scan.json` (points carrying µ95/exclusion) +
  `scan_manifest.json` (`points[]`/`n_done`) ATTEST the per-point chain; per-point sibling artifacts
  are not required (they are routinely cleaned/regenerable). Non-scan modes are unchanged. After the
  fix `validate_run_state --rundir trial-runs/sleptonscan_fig3_SCAN` = exit 0 (WARN — only the
  pre-cleared likelihood-pairing WARN, workspace/patch cleaned off disk). Regression test added.
- **Status:** EMBEDDED (2026-07-08) — emitters + validator (incl. the scan-aware discovery fix) +
  wiring + flagship backfill all landed and green.
- **Verify:** `python3 src/ravel/validation/validate_run_state.py --selftest && python3 src/ravel/validation/validate_run_state.py --rundir trial-runs/sleptonscan_fig3_SCAN` (the second call is the flagship dogfood claim itself: exit 0, verdict=WARN — only the pre-cleared likelihood-pairing WARN)

### CR-040 — summary_audit.py physics-completeness gate + HVT fix + P1 re-promotion (I4; embeds CR-031)
- **Date registered:** 2026-07-08 (audit-and-fix Phase 4).
- **What:** new `src/ravel/validation/summary_audit.py` — the summary_plot physics-completeness
  gate (rules R-SA1..8: survey↔basis_manifest bijection, disposition completeness, no keyword-only
  exclusions, label↔channel derived from each candidate's OWN `final_state` [no per-paper literals],
  superseded-not-co-equal, provenance labelled+consistent, coverage-annotation↔reach, transformation
  present); typed schema additions (survey `candidates[].disposition`+`provenance`; basis_manifest
  `curves[].{survey_id,provenance,draw}`); `summary_overlay.py` honors `draw`/`provenance`. The HVT
  run's F1–F4 defects were fixed on its own records (F1: ATLAS_1710.01123 fully-leptonic curve
  digitized from the correct non-VBF qqA figure — adversarial physics-review CONFIRMED figure/channel/
  units/200-GeV-floor; F2 relabel ℓνqq; F3 demote superseded→crosscheck; F4 coverage floor 200 GeV),
  `summary_audit --rundir` → PASS, P1 re-promoted partial→served and the readiness cascaded 95→96%
  (R9 0.64). Also fixed: `validate_run_state.py` STAGE_MATRIX `figure_contract` for `summary_plot`
  R→O (a none-survey summary synthesizes many limits, it does not reproduce one figure).
- **Why:** summary plots are the highest-value low-compute product but had NO physics-completeness
  gate (only layout lint), so a defective plot was marked served; PRODUCT-CONTRACT §7 (CR-031) now
  requires this gate.
- **Where-embedded:** `trial-runs/_infrastructure/{summary_audit.py,summary_overlay.py,validate_run_state.py}`,
  `tests/unit/{test_summary_audit.py,test_validate_run_state.py}`, the HVT run dir (survey.json,
  basis_manifest.json, plots + qa overlay, VERIFICATION-LADDER.md, summary_audit.json), the P1
  re-promotion cascade (capability-matrix.json, AUDIT.md, STATUS.md, README.md, DIRECTORY.md).
- **Status:** EMBEDDED (2026-07-08). NOTE: P1=served rests on the mechanical `summary_audit` gate +
  an adversarial physics-review of the digitization; the step-9 Tier-B panel is Phase 9.
- **Verify:** `python3 src/ravel/validation/summary_audit.py --selftest && python3 src/ravel/validation/summary_audit.py --rundir trial-runs/2026-07-06_SURVEY_hvt-zprime-ww-lowmass`

### CR-041 — per-capability hard-gate binding: R9 is non-gameable (I13; embeds CR-035)
- **Date registered:** 2026-07-08 (audit-and-fix Phase 5).
- **What:** every prompt P1..P7 gains a `gate{kind,ref,artifact,green_when,flip_when}` (matrix
  schema_version 1→2). `audit.py::c_capability` is now a status-RATIFYING reconciler
  (`_score_capability`/`_gate_verdict`): a `served`/`served-with-refusal` prompt earns its 1.0 R9
  credit ONLY if its named gate resolves GREEN — `kind=artifact` (a run's JSON `green_when` predicate,
  e.g. P1 `summary_audit.json` verdict==PASS), `kind=selftest` (e.g. P4 `shape_fit.py --selftest`
  exit 0). A `kind∈{decision,deferred}` gate can NEVER credit served; a red-gated "served" is credited
  as partial (0.5) with a FAIL line, so R9 cannot be inflated by editing one JSON string. `_gate_verdict`
  never raises (a selftest that can't launch → red, not a crash).
- **Why:** R9 exists precisely so engine-readiness can't masquerade as project-readiness, but it
  trusted a hand-editable status string with no machine check (PRODUCT-CONTRACT §5 / CR-035).
- **Where-embedded:** `benchmarks/capabilities.json` (gate{} per prompt), `scripts/audit.py`,
  `tests/unit/test_capability_gate.py` (14 anti-gaming tests). Readiness unchanged (96%, R9 0.64)
  — P1/P4 gates are green today. The `decision`-gate `flip_when` fields document what moves each partial
  prompt to served (P3/P7 round-trips land in Phase 7).
- **Status:** EMBEDDED (2026-07-08).
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_capability_gate.py" -q`

### CR-042 — evidence pack: claim→artifact→sha256, publicly auditable (I1; embeds CR-030)
- **Date registered:** 2026-07-08 (audit-and-fix Phase 6).
- **What:** `scripts/build_evidence.py` enumerates every served/headline claim (capability-matrix
  prompts' `evidence_artifacts`, benchmark cases' `require_files`, and a curated engine-layer
  HEADLINE_CLAIMS block) → `evidence/manifest.json` + `docs/validation/evidence.md`, sha256 each (13 claims).
  `scripts/check_evidence.py --check [--root <dir>]` fails unless every served claim has a
  present + sha-matching artifact under `--root`; `--root <stage>` lets it certify the PUBLIC export
  tree, not the dev repo. `export_distribution.sh` now ships the curated evidence subsets (flagship
  scan ~1.1 MB, native slepton output, HVT summary) and ABORTS the export if
  `check_evidence --check --root "$STAGE"` fails — so a public reader can reach every headline
  claim's checksummed artifact. Also reconciled the DISTRIBUTION.md prose↔script drift and fixed
  README/native-pipeline.md pointers that sent readers at an omitted `trial-runs/` tree.
- **Why:** SHIPPED docs asserted physics headlines (141/141 bit-for-bit, µ95 0.51%, ~25% residual)
  whose evidence lived only in dev-only run records the export omitted — a claim a public reader
  could read but not verify (PRODUCT-CONTRACT §7 / CR-030).
- **Where-embedded:** `framework/{build_evidence.py,check_evidence.py}`, `evidence/manifest.json`,
  `docs/validation/evidence.md`, `benchmarks/capabilities.json` (evidence_artifacts), `trial-runs/_infrastructure/
  export_distribution.sh`, `docs/development/distribution.md`, `README.md`, `docs/workflow/reference/native-pipeline.md`,
  `tests/unit/test_check_evidence.py` (22 tests). Verified: `check_evidence --check --root $STAGE`
  = 13/13 PASS against a real 4.5 M/245-file assembled stage (no push).
- **Status:** EMBEDDED (2026-07-08).
- **Verify:** `python3 scripts/check_evidence.py --check` (read-only; checksums include
  `benchmarks/cases.json` as a shipped BENCH_* artifact, so this can show a TRANSIENT
  FAIL if run while a session is mid-edit on that file/the gluino-gbb run dir — rerun once that
  session settles, or `--root <export-stage>` to certify the curated public tree instead of dev)

### CR-043 — Option-C reconcile (I5): 3 shipped step-list pieces + DECLINE `asymptotic_ul.py`
- **Date registered:** 2026-07-08 (audit-and-fix Phase 8, Task 8.3).
- **What (reconcile):** `framework/OPTION-C-DESIGN.md`'s step-list was written 2026-07-06 and
  described several pieces as future embeds; three have since SHIPPED and the doc was stale about
  it — verified present on disk before editing: (1) the continuum-background generation recipe
  (step-list item 3) is in `docs/workflow/steps/03-generate.md`'s "Beyond signal samples" section
  (~lines 60-67); (2) the `sensitivity-expected-only` stat_mode (step-list item 5's
  "`result_pack.py --stat-mode sensitivity`") is in `src/ravel/workflow/result_pack.py`'s
  `STAT_MODES` tuple (line 72; landed via CR-009); (3) the first-class Option-C step (step-list
  item 2) is `docs/workflow/steps/04-analyze.md`'s "## Option C — NO routine exists" section, backed by
  `docs/workflow/checklists/option-c-judgment.md` (the physics-judgment protocol; supersedes the doc's
  original `checklists/no-routine.md` placeholder name — that file was never built under that
  name). `OPTION-C-DESIGN.md`'s header + step-list items 2/3/5 updated to mark these SHIPPED with
  pointers, so the doc stops advertising built capability as open. The un-shipped step-list items
  (0, 1, 4, 6) and the heavy Option-C VALIDATION run are untouched by this reconcile and remain
  design/deferred as before (two Option-C validations already exist from the two 2026-07-04
  trials; a third is not scoped by this task).
- **What (decline):** a co-designer suggestion proposed generalizing the CMS/ATLAS-AD trial's
  improvised `build/asymptotic_ul.py` (a CWoLa-injection sensitivity/UL script local to
  `trial-runs/2026-07-04_ATLAS_model-agnostic-AD/build/`, see that run's RESULT.md +
  VERIFICATION-LADDER.md item 11) into a first-class framework module. **DECLINED.** Reasoning:
  (a) redundant — the asymptotic-CLs machinery it would provide already exists twice, generally:
  `pyhf_exclude.py` (via `pyhf.infer.hypotest`, the standard Cowan-et-al. q_mu + background-Asimov
  construction, bracket+bisect to the true CLs=0.05 crossing) and `shape_fit.py` (the same q_mu +
  background-Asimov bisection, hand-implemented for the binned single-spectrum case, CR-027); a
  third module computing the same statistic would be a second source of truth, the exact drift
  class this registry exists to prevent (OPERABILITY-CHARTER §7). (b) the CWoLa-injection framing
  specifically is per-weakly-supervised-paper logic — analysis-hardcoded machinery leaking into
  `trial-runs/_infrastructure/`, the named anti-pattern this framework declines by design (every
  other statistics tool here is analysis-agnostic with per-analysis choices as declared inputs).
  The trial-local script stays exactly where it is — a run-local `build/` artifact, not promoted.
- **Follow-up noted, not built here:** CR-010 (multi-panel figure enumeration in
  `figure_target.py`) is the one genuine residual gap from this same audit item — still DEFERRED,
  cheap and code-only when picked up; the manual per-panel workaround (`--figure-id "Figure Na"`
  per panel) stands in the meantime, so nothing is blocked.
- **Where-embedded:** `framework/OPTION-C-DESIGN.md` header + step-list items 2/3/5 (this entry);
  no `trial-runs/_infrastructure/` build (declined).
- **Status:** EMBEDDED (2026-07-08) — reconcile + decline both recorded; no code written.
- **Verify:** `(decision — no artifact; asymptotic_ul.py intentionally absent; the reconcile's statefresh-green requirement is covered by CR-038's check_agent_surface.py line already in this same board)`

## Open fixes (gate result quality — charter §3 F6 + P2)

### CR-001 — pyhf µ-floor: bracket DOWN on hyper-excluded points
- **Date registered:** 2026-07-06 (diagnosed 2026-07-04)
- **What:** `src/ravel/physics/pyhf_exclude.py` brackets µ upward from 1 only and never
  brackets below 0.1: points with CLs≪0.05 across the whole scanned range return `obs_limit=1.0`
  with a flat `[1,1,1,1,1]` expected band — a floored µ then becomes a huge fake σ-UL. On the fig3
  scan this renders the m60_dm5 / m70_dm5 cells as +1200–1450% dark-red difference-map artifacts.
- **Why:** the floored value is not a measured limit; it corrupts the difference map and any
  downstream σ-UL comparison on strongly-excluded points.
- **Where-embedded (fixed 2026-07-06):** `pyhf_exclude.py` — downward bracket (halve µ until
  every CLs column rises above the level, floor 1e-6), `_cross` distinguishes the all-below case
  (returns the low edge as a BOUND, not the ceiling), new `at_mu_floor` flag + warning symmetric
  to `at_poi_cap`, and geometric low-decade scan points; regression = `pyhf_exclude.py selftest`
  (normal / hyper-excluded / unconstrained — the hyper case now resolves a real µ₉₅≈3.4e-4).
  Propagation guard: `scan_orchestrator.py harvest_point` tags `quality=floored|capped|
  floored-legacy` (legacy = the READING RULE `obs_limit==1.0` + flat band, so PRE-fix artifacts
  are caught without a rescan); `scan_contour.py` draws flagged points as gray '×' excluded from
  the fill AND the µ=1 contour field, with an on-figure note. Benchmark `--full`: GATE OK.
  **Addendum (same day, found by exercising the chain live):** `cmd_assemble` rebuilt each scan
  row by hand and DROPPED the harvest `quality` key — fixed (the tag now survives into
  `scan.json`), then applied to the record scan: fig3 re-assembled + re-rendered, m60_dm5/
  m70_dm5 → `floored-legacy` '×' bounds, headline median 26.2% → **24.9% obs / 24.1% exp over
  the 50 honest cells** (scan `DEVIATIONS.md` + `RESULT.md` addendum + STATUS/PLAN-OF-RECORD
  updated in the same commit).
- **Status:** EMBEDDED (2026-07-06).

### CR-002 — `prepare_native_slepton.py` drops `[madgraph.run.options]` (ptj1min=50)
- **Date registered:** 2026-07-06 (diagnosed 2026-07-04)
- **What:** the native per-point card prep renders the raw run-card template and applies only
  nevents/iseed/ebeam/pdlabel/use_syst — the TOML's `[madgraph.run.options]` block (notably
  `ptj1min = 50`) is silently never applied, so native samples generate at ptj1min=0. Measured
  split at m=200 (500-evt A/B, cteq6l1): σ_tag = 42.83 fb (ptj1min=0) vs 19.99 fb (ptj1min=50) —
  a ×2.14 tag-definition drift vs the container-path reference sample.
- **Why:** tag-definition parity with the reference (RRR/mapyde container path) requires the
  run.options block to be honored; without it the ISR-tag acceptance mix differs.
- **Where-embedded (fixed 2026-07-06):** `prepare_native_slepton.py` `read_run_options()` +
  `render_runcard(..., run_options)` apply the FULL `[madgraph.run.options]` block first,
  fail-loud on a missing file/block/key (`--toml` arg; default = the mapyde `sleptons.toml`
  template); `scan_orchestrator.py` native launch passes the point's own config TOML.
  Verified: a real point TOML renders `ptj1min=50` (+6 more option keys) into the run card.
  Doc: `docs/workflow/reference/native-pipeline.md` states the block is applied + the pre-fix caveat.
  The 52-point grid **rescan at ptj1min=50 remains CR-004** (heavy MC, deferred).
- **Status:** EMBEDDED (2026-07-06; rescan = CR-004).

### CR-003 — `export_distribution.sh` push: fetch-before-push lease
- **Date registered:** 2026-07-06
- **What:** the push step git-inits a fresh staging tree and runs
  `git push -u origin main --force-with-lease` with no remote-tracking ref — the lease has nothing
  to compare against and can fail (or silently fall through to the un-leased retry on line 95).
  Fix: `git fetch origin main` after `git remote add origin`, then
  `git push --force-with-lease=main:origin/main`.
- **Why:** the current fallback (`|| git push -u origin main`) defeats the lease entirely; a
  concurrent push to the distribution repo would be clobbered without warning.
- **Where-embedded (fixed 2026-07-06):** `export_distribution.sh` step 6 (line 96): fetch
  `origin main` first, then `git push --force-with-lease=main:origin/main`; the un-leased
  fallback now runs ONLY when the fetch shows a brand-new/empty remote (nothing to clobber),
  and the leased attempt's `2>/dev/null` is gone so failures are diagnosable.
- **Addendum (2026-07-06, later):** the push was ALSO failing at the transport layer — GitHub
  HTTPS returned `RPC failed; HTTP 400 curl 56` on the ~2 MB pack from this host, which had
  silently stranded the 14 charter-session commits locally (remote sat at the 49e3254 export
  while the dev repo reached 0a5d335). Fixed: the staging repo sets
  `http.postBuffer 524288000` before pushing (buffered, not chunked, transfer); verified by
  re-push + `git ls-remote` (remote main = the 0a5d335 export). Lesson for the W1 gate: the
  export must VERIFY the remote ref after pushing, not trust the push's exit path.
- **Status:** EMBEDDED (2026-07-06).

### CR-044 — `run_benchmark.py`: add a `pyhf_mode="likelihood"` hook (gate checks a proxy, not Mode A)
- **Date registered:** 2026-07-08 (task 7.1 consolidation, adversarial physics review of the
  `ins2182381_gbb_1900_1` gluino-Gbb case).
- **What:** `run_benchmark.py`'s `run_pyhf()` step unconditionally calls `pyhf_exclude.py counting`
  for every registered case — there is no `pyhf_mode="likelihood"` code path that re-applies a
  case's signal patch to its published bkg-only HistFactory workspace and re-derives µ₉₅ from the
  real Mode-A likelihood. Case 9 (`ins2182381_gbb_1900_1`) is this registry's first
  published-likelihood case, but its `required.mu95_stability.baseline_mu95_obs =
  0.17694018928599856` is the **counting**-mode reconstruction of the driving SR
  (`outputs/counting/exclusion.json`), not the Mode-A `obs_limit = 0.17428109495495014`
  (`outputs/likelihood_B/exclusion.json`) that is the run's actual physics headline. The two agree
  closely for this case (+1.53% obs / -4.77% exp — see the case's RESULT.md and `cases.json`
  notes), but that agreement is a property of this one case, not a guarantee the gate would catch
  a future regression in the Mode-A likelihood machinery itself (`pyhf_exclude.py likelihood`, the
  signal-patch builder, or a published bkgonly-workspace edit).
- **Why:** a benchmark case advertised as "gate-verified" should mean the gate re-checks the same
  statistical model the case's headline actually uses. Right now the gate silently substitutes a
  proxy (counting) for the real thing (Mode-A likelihood) with no flag in `results.json` calling
  this out — a future case relying on Mode A would inherit the same silent substitution.
- **Where-embedded:** NOT YET BUILT — tracked here as the Phase-2 follow-up. Needs: a
  `cases.json` per-case `inputs.pyhf_mode` knob (`"counting"` default, `"likelihood"` opt-in,
  mirroring the existing C1N2 `"combined"` knob from CR/S2-1c), `bkg`/`patch` file paths per case,
  and a `run_benchmark.py` branch that calls `pyhf_exclude.py likelihood --bkg ... --patch ...`
  when set, gating `baseline_mu95_obs` against the Mode-A `obs_limit` instead of the counting one.
- **Status:** OPEN / DEFERRED (no build scheduled yet; the honest caveat is disclosed in the
  case 9 RESULT.md and `cases.json` notes in the interim, so the gate's current scope is not
  misrepresented).
- **Verify (once built):** `python3 benchmarks/run_benchmark.py --case
  ins2182381_gbb_1900_1` should re-derive `outputs/likelihood_B/exclusion.json`'s `obs_limit`
  fresh and gate against it, not the counting reconstruction.

## Harness-code gaps from the generality trials (registered 2026-07-06, charter P1 audit A5-06)

### CR-007 — lhe_check: width-aware event-mass tolerance + the drivers now RUN the gate
- **Date:** 2026-07-06. **What:** (a) the fixed ±1 GeV event-mass tolerance falsely FAILed
  Breit-Wigner event-record masses of wide s-channel resonances (Γ≈30–50 GeV; trial gap
  G-CMS-05 / FAILURE-CATALOGUE C2) — `lhe_check.py` now reads each expected PDG's total width
  from the banner's `DECAY` headers and widens the EVENT tolerance to max(--mass-tol, 3Γ)
  while the banner-mass check stays tight; (b) the charter §4b gate map demanded lhe_check
  as the mandatory pre-shower gate but NEITHER pipeline driver ran it (audit A6-03) —
  `run-pipeline-native.sh` now runs it as stage 1b (fail = STOP) and `run-pipeline.sh` runs
  it after mapyde's fused gen+shower stage (still ahead of detector/analysis/stats).
- **Status:** EMBEDDED (2026-07-06).

### CR-008 — hepdata_fetch figure_index: underscore-style figure names
- **Date:** 2026-07-06. **What:** the figure-index regex matched only "Figure 16a"-style
  names; HEPData records also use `fig_01` / `fig_03_jj` / `fig_04a` (trial gap G-AD-04, hit
  live in the ATLAS-AD trial). Regex now accepts `. _ - space` separators and strips leading
  zeros so both styles share one key.
- **Status:** EMBEDDED (2026-07-06).

### CR-009 — result_pack stat_mode enum: sensitivity-expected-only + none-survey
- **Date:** 2026-07-06. **What:** no enum fit an EXPECTED-only sensitivity study (S/√B,
  expected-CLs reach) or a survey deliverable, so both 2026-07-04 generality trials shipped
  without a `result.json` (trial gap G-AD-11). Added `sensitivity-expected-only` and
  `none-survey` to `result_pack.py` STAT_MODES; docs/reference/scope.md carries the taxonomy.
- **Status:** EMBEDDED (2026-07-06).

### CR-010 — figure-contract code completions: multi-panel enumeration + merge-fix regression test
- **Date:** 2026-07-06. **What:** (a) figure_target/fetch_figures treat one image per target;
  multi-panel published figures (Figs 5–6 sensitivity grids) need first-class panel
  enumeration (trial gap G-CMS-04, code half); (b) the two-same-role-target merge bug was
  fixed in commit ad638d6 but its regression test was never written (audit A5-12).
- **Status:** DEFERRED (design work; the figure-contract SKILL documents the manual
  per-panel workaround: declare each panel as its own `--figure-id "Figure Na"` target).

### CR-011 — internal-process (non-LHE) generation guard
- **Date:** 2026-07-06. **What:** Pythia-internal / non-MadGraph generation paths have no
  pre-shower structural gate equivalent to lhe_check (trial gap G-AD-10b — the AD trial
  generated QCD dijets Pythia-internally with zero mechanical checks).
- **Status:** DEFERRED (needs a design: what IS checkable pre-shower without an LHE —
  likely a post-generation sanity script on the HepMC header + process record).

### CR-012 — the operability harness: route/validate/cost/surface-check/sync scripts
- **Date:** 2026-07-06 (charter §4.4 P2a). **What:** five new stdlib-only tools in
  `trial-runs/_infrastructure/`: `route_prompt.py` (prompt → `task_contract.json`,
  deterministic, selftest = the ten charter-P4 prompts), `validate_task_contract.py` (the
  schema gate; `--schema`), `cost_preflight.py` (walltime/disk from the measured 30–50
  min/point; the none→dry→smoke→full→scan ladder), `check_agent_surface.py` (fork agreement,
  dead refs incl. `--stage` export-tree mode, skill frontmatter, mirror parity, DIRECTORY
  two-way map, readiness + step-count agreement, hygiene grep incl. `.claude/`), and
  `sync_skills.py` (`.claude/skills` → `.agents/skills`, single source).
- **Why:** charter F1/F3/F5 — weak models must be FORCED through scripts, not trusted with
  prose; the surface checker makes the doc-drift class mechanically impossible to miss.
- **Where-embedded:** the physicist-intake / route-analysis / cost-preflight skills invoke
  them (P2c); step-02/check-ins cost line (P2e); P3 runs `check_agent_surface.py` to green.
- **Status:** EMBEDDED (2026-07-06; at creation the surface gate correctly FAILs on the five
  known open drifts — fork order, missing mirror, readiness, step count, new-analysis leak —
  each fixed by its named P2c/P2e commit).

### CR-013 — model-tier policy: [Opus] → [judgment] + explicit weak-model behavior
- **Date:** 2026-07-06 (charter §6; audit S0-2 — 62 bare tags, zero weak-model policy).
- **What:** every `[Opus]` tag across `docs/workflow/` + `CLAUDE.md` renamed `[judgment]` (63
  sites); the binding three-behavior policy defined ONCE in `docs/workflow/README.md` §Roles
  (DEFAULT = escalate-to-physicist via a numbered CHECK-IN flag + wait · `script-assisted:
  <tool>` · `proceed-with-flag` + DEVIATIONS entry); nine sites where the escalate default
  would wrongly stall a cheap model carry explicit suffixes (statistics sizing, merging
  decision, SINGLEWEIGHT detect, figure selection 5.0, step-7/8 headers + exclusion-model,
  plot-label map, sr_spec map); Tier-B = strong-model fresh-context subagent or escalate.
- **Why:** a cheap model must never silently take a judgment step NOR stall where a script or
  safe default exists — the §8 success criterion depends on both directions.
- **Status:** EMBEDDED (2026-07-06).

### CR-014 — git curation alignment: the tree now matches the stated policy (both ways)
- **Date:** 2026-07-06 (audit A4-01..A4-09 — the consolidated remediation).
- **What:** `.gitignore` reworked: `**/build/` scoped to `stages/**/build/`; the LaTeX block
  scoped to `pedagogical/**` (its global `*.log/*.out` had silently swallowed every trial-run
  evidence log); `output/` dir-exclude converted to content-exclude with curated negations
  (exclusion.json/png, `*.txt` yields, `*_patch.json` — native_objects.txt re-ignored at
  8 MB/point); trial-run `build/**` with `!*.cc`/`!*.py` (the hand-written sources); the
  `published/` fetch patterns `**`-ified (+png/xml); features CSVs, plots.zip, `inputs/*_src/`
  + `inputs/*.pdf` ignored. UNTRACKED ~87 MB of regenerables (75.2 MB feature CSVs, 8.8 MB
  published-figure PDFs, arXiv authlist junk, a fetchable CONF note); KEPT the 19 HEPData
  patchsets (they pin recorded exclusions) + the two bkg-only likelihoods. TRACKED ~21 MB of
  curated evidence: all 59 scan-point dirs' config+curated output trio, every run's `logs/`
  chain, the 11 build sources, both 2026-07-06 run records, design-review .tex sources.
  Backfilled `RESULT.md` for the native-validation run (A4-07: the run behind "bit-for-bit"
  had no record) and the ttthreshold survey dir (A3-07), each with a machine-readable
  `Deliverable:` header. CLAUDE.md's curation line and the `.gitignore` header now carry ONE
  identical policy statement (A4-09). `git status` unpolluted: 66 → 0 untracked paths.
- **Why:** charter §7 "every number traceable to artifacts" was violated by the flagship
  scan's own evidence being untracked, while 69% of tracked bytes were regenerable bulk.
- **Status:** EMBEDDED (2026-07-06).

### CR-015 — scan_contour legends routed through the house `smart_legend`
- **Date:** 2026-07-06 (supervisor-reported: "every visual … has the text in its legend block
  the actual data").
- **What:** `scan_contour.py` carried four raw `ax.legend(loc=…)` calls (line/grid/fig3/reldiff
  layouts) although the house style's collision-aware `smart_legend` already existed and the other
  renderers used it — a pure enforcement gap. All four now route through
  `mplhep_style.smart_legend` with per-layout candidate/reserved corners (the line layout's
  annotation owns upper-right; fig3's experiment label sits above the axes so inside-top-left is a
  real candidate; explicit proxy handles forward labels too, which `smart_legend` requires).
  Re-render of the 52-point scan verified: identical physics numbers (median |rel diff| 26.2%
  obs / 25.2% exp), legend relocated off the color-map cells. Known remaining occlusion of the
  OTHER kind: the fig3 lower-left annotation box clips the ATLAS dotted contour tail — first
  target for the `plot_lint.py` machine gate (`docs/development/roadmap.md` §7 / W1).
- **Why:** plot-criteria says "legend … occludes nothing" but nothing enforced it; checklists
  don't prevent, gates do. Catalogue incident A5.
- **Status:** EMBEDDED (2026-07-06); the lint gate is the W1 completion — landed as CR-016.

### CR-016 — the plot-lint MACHINE GATE + occupancy-scored annotations (roadmap W1 addendum 2)
- **Date:** 2026-07-06 (overnight roadmap execution, checkpoint C1).
- **What:** `mplhep_style.lint_figure`/`enforce_lint` — measured-bbox checks run INSIDE every house
  renderer at save time, exit 4 on violation (`--no-lint` downgrades to WARN): (a) legend/BOXED-
  annotation occlusion of drawn data (occupancy sampler extended to unfilled CONTOUR LINES; fills
  exempt — a framed box over a color map is standard; BARE in-plot feature labels exempt);
  (b) box↔box overlap; (c) successive tick-label overlap; (d) off-canvas boxes (fixed-canvas savers
  only — tight-bbox savers grow the canvas). Placement is now SOLVED, not hand-tuned:
  `smart_annotate` (new) scores the four corners with the same occupancy sampler, treats the legend
  + other labels as reserved, and falls back to a BELOW-AXES CAPTION when every inside corner is
  occupied (full-plane figures); `smart_legend` callers pass lower-corner candidates where contours
  sweep the top (the fig3 case). Wired: `scan_contour.py` (all four layouts + `--no-lint`),
  `overlay_on_data.py`, `mass_plane_overlay.py`; selftest `plot_lint.py --selftest` (colliding
  figure must FAIL, house-helper figure must PASS — both verified).
- **Why:** catalogue A5 — the supervisor-reported legend-over-data class; checklist lines don't
  prevent, gates do. Live proof during the build: the gate caught (1) the grid panel's
  every-corner-occupied annotation, (2) the fig3 legend sitting on contour LINES that the old
  sampler was blind to — both fixed structurally, then the gate went green on all six scan
  artifacts.
- **Where-embedded:** `mplhep_style.py` (lint_figure/enforce_lint/smart_annotate + sampler
  extension), the three renderers, `plot_lint.py`, `checklists/plot-criteria.md` (machine-gate
  block), `steps/05-visualize.md` §5.5, `.claude/rules/plots.md`; re-rendered record artifacts in
  the fig3 scan dir (RESULT.md addendum notes the CR-001+CR-016 median/layout deltas:
  24.1%/24.9% over 50 ref-matched cells, all-point medians unchanged).
- **Status:** EMBEDDED (2026-07-06).

### CR-017 — the RESOURCE SWEEP: resource_census.py + skill + step-2.0 wiring (roadmap M1)
- **Date:** 2026-07-06 (overnight roadmap execution, checkpoint C3).
- **What:** `resource_census.py` automates source-ladder rungs 1–5 per analysis: HEPData record
  incl. the RESOURCES tab (likelihood/efficiency-map candidates classified), routine resolution
  (routine_fetch), arXiv metadata, GitHub REPO+CODE search (code search is what finds recast
  repos that don't carry the analysis id in their name), INSPIRE forward-citations (theses
  flagged) + Zenodo. Emits `inputs/resource_census.json` + the CHECK-IN 1 census block
  (`--markdown`). Fail-soft per rung with recorded reasons; exit 3 when ALL rungs fail ("that is
  an environment finding, not evidence of absence"). Verified TLS ONLY (certifi via the conda
  envs) — explicitly no ssl-noverify fallback (the mining-flagged residue class). New skill #15
  `resource-sweep`; wired as step 2.0 (mandatory before routing) + CHECK-IN 1 §(i-b).
- **Why:** the missed-RRR-repo failure class (roadmap M1). Live acceptance test on ins1767649:
  all 5 rungs OK — 106 tables, 1 likelihood + 1 efficiency-map resource, 388 forward citations
  (2 theses in sample), and the CODE search surfaces `scipp-atlas/mapyde-tutorial` unprompted —
  the exact repo class previously missed.
- **Status:** EMBEDDED (2026-07-06).

### CR-019 — audit v2: the R9 capability-coverage dimension (roadmap M3)
- **Date:** 2026-07-07 (overnight roadmap execution, checkpoint C5).
- **What:** `audit.py` gains `c_capability()` (R9): reads `benchmarks/capabilities.json`
  (the 7-prompt demand board maintained by the census, C8) and scores served/
  served-with-refusal = 1.0 (a PRODUCT-CONTRACT refusal IS the product), partial = 0.5,
  unbuilt/decision-pending = 0. The AUDIT.md headline carries the R9 line verbatim. First run:
  **95%, R9 WARN (0.50): 1/7 fully served, 5 partial, 1 unbuilt.** README + STATUS rewritten to
  the two-layer statement (engine R1–R8 vs capability R9); STATUS's stale "99%, 13/13" replaced;
  README's stale `[Opus]` tags and 99% removed; R9 added to the R-bar.
- **Why:** the supervisor's standing correction — the old 100%/99% was scoped to the
  reproduce-with-routine engine and read as project readiness. The audit can now never claim
  what the capability layer doesn't have.
- **Status:** EMBEDDED (2026-07-07).

### CR-020 — step-4 Option D: the efficiency-map folding route (G2a; roadmap W3/C10)
- **Date:** 2026-07-07 (overnight roadmap execution, checkpoint C10).
- **What:** (a) `reinterpret_db.py --data-select efficiencyMap|upperLimit|all` — restricting the
  SModelS database result type; the EM selection IS the folding route (published per-SR A×ε grids
  folded over the model point → r_obs AND r_exp + best SR). Implementation note: `-p` REPLACES
  the SModelS default config, so the tool patches the package's own `parameters_default.ini`
  (a minimal ini crashes loadDatabase on the missing `database.path`). (b) `docs/workflow/reference/
  effmap-folding.md`: D1 (built) + D2 (per-object LLP folding DESIGN with the R5 validation gate
  — the P7 unlock, one-session estimate). (c) step-04 gains Option D + routing rules (T2 → D;
  no-routine SUSY → try D1 before Option C).
- **Why:** roadmap G2a — the biggest supply-mass route (90% of SModelS SR-datasets are EM-type);
  the census evidence-gated it OPEN. Live acceptance test: gluino (1000,100) σ=0.325 pb →
  4 analyses fold + exclude (ATLAS-SUSY-2015-06 r_obs=13.04/r_exp=7.66; consistent with the
  UL-type cross-check's 8.07 within result-type semantics).
- **Status:** EMBEDDED (2026-07-07); D2 build = the named next session.
- **DEFER TRIGGER (recorded 2026-07-08, Task 8.1 — I6):** the D2 per-object efficiency-map
  ENGINE (`effmap_fold.py`, selftest 5/5) is BUILT and its statistics-half is VALIDATED on real
  ATLAS-SUSY-2016-06 data (reader parses the real Fig18b map; pyhf reproduces the published
  sigma_vis to within the P7 matrix entry's quoted tolerance). The remaining last mile — a
  truth-level wino event-maker + decay-radius sampler + disappearing-track truth selection, then
  R5 closure on ≥2 published (m,cτ) points — is EVENT GENERATION, so it stays DEFERRED (not
  build-ahead debt; the §2/§5 `effmap-folded` scope rows (CR-034) and the `result_pack.py` enum
  already landed in Phase 0). **TRIGGER** to build it: (a) a dedicated validation-first session,
  or (b) a real physicist LLP/disappearing-track (T2) request — either way routed through
  CHECK-IN 1 + the dry→smoke→full ladder, never opportunistically inside an unrelated task.
  Confirmed: `benchmarks/capabilities.json`'s `P7_displaced_run3_replane` gate is already
  `{kind: decision, flip_when: "effmap >=2 published (m,ctau) points reproduced + replane
  round-trips a paper's OWN plane + a projection round-trip"}` — it already names the effmap
  ≥2-points condition, so no matrix edit is needed here.

### CR-027 — the SCOPED SHAPE-FIT ENGINE (Option B, DECIDED by the supervisor 2026-07-07)
- **Date:** 2026-07-07 (overnight-2 checkpoint D3). Decision record: DECISION-SHAPE-FIT.md (B signed).
- **What:** `shape_fit.py` — binned single-spectrum fits: dijet3/dijet4 functional families AND
  the **template-background transfer-function mode** (the paper's own published background shape
  × exp(poly_K), `--bkg-order`; the most reusable reproduction mode) + optional additive
  non-fitted resonant MC (`--fixed-bkg`) + the paper's published per-bin envelope as a Gaussian
  NLL (`--syst`); signal = published/generated template or Gaussian stand-in; limits via
  asymptotic CLs (q_mu + background-Asimov) bisected to the true crossing. Selftest 4/4 PASS
  (Asimov identity exact; injection recovery; ordering; lumi scaling = 2.00).
- **R5 validation status (ins2813982, the P4 analysis): PARTIAL, honestly bracketed.** Live
  findings, all recorded in the tool's docstrings: (1) a bare dijet family CANNOT fit a
  boosted m_J spectrum (χ²/39 = 24001 — turnover physics; loud, not silent); (2) background
  FLEXIBILITY is the sensitivity-limiting physics — norm+tilt template rigidity gave
  3–10× ANTI-conservative limits, measured; K=3 measured too; (3) the remaining normalization
  chain (SR-template yield ↔ published σ×BF×A "A" convention) is under-determined from HEPData
  alone — even the paper's own two UL tables imply a mass-dependent A ratio. COMPLETING R5 =
  read the paper body's A/ε conventions + likely region-combination; until then NOTHING ships
  from this engine (the R5 gate line prints on every run).
- **R5 CLOSED (2026-07-07 continuation** — full evidence chain:
  `overnight-roadmap/inputs/r5-normalization-closure.md`): the paper's conventions pinned with
  quotes — **140 fb⁻¹** (their defs file carries a stale unused 139), templates at the
  **g_q = 0.2 DM-WG vector benchmark** (309/143/34.2 fb; BF≡1; σ∝g_q² verified to 4 digits;
  the ×5 display scaling verified correctly removed at runtime; a published-caption ERRATUM
  found — the Fig-3a legend proves the middle template is 40 GeV, not the caption's "50"),
  the limit = a 4-region simultaneous fit (SR + 3 CRs via a 6-coeff Bernstein transfer factor;
  single-SR expected 0–12% weak). **Observed gate MET at 20/125 GeV: µ95 within 5.2%/10.9%**
  (g_q within 2.6%/5.6%); the 40-GeV obs gap = the paper's own 2σ excess partly living in CRs
  we don't fit; honest expected-limit closure ≤30% in µ95 with every residual factor measured
  (single-SR + envelope-as-Gaussian modeling). Engine input rule established: spectra must be
  COUNTS — HEPData per-GeV densities need ×binwidth (the measured under-dispersion fix,
  χ²/ndf 19.9→40.3/39); registered as the engine's next code hardening.
- **ROUTING WIRED (2026-07-07 continuation-3, Opus — the P4 flip):** shape-fit is no longer a
  blanket refusal. A new `shape-fit` stat_mode (result_pack + validate_task_contract enums)
  routes shape/template-fit prompts to the engine, R5-gated per analysis. `route_prompt.py` sends
  the hint/blocklist ids to `stat_mode=shape-fit` + `compute_plan=smoke` with an R5-gate escalate
  flag (P4 selftest now expects shape-fit/smoke; all 10 green); PRODUCT-CONTRACT §3 adds the mode
  and §6.1 rewrites refusal-case-1 as the two-gate conditional (representability + R5 closure,
  downgrade to `blocked-shape-fit` only when the engine can't represent the fit or R5 won't
  close); `route-analysis` skill + step-4 Option E carry the route. Capability-matrix **P4 →
  served**, G2b → built; audit R9 0.57 → 0.64. 2408.00049's own R5 (dijet-family turnover) stays
  open, so that limit is gated while the generator-level + widths offer ships — the honest state.
- **Status:** ENGINE EMBEDDED + **R5 CLOSED (ins2813982)** + **ROUTING WIRED** — the shape-fit
  paradigm is a supported product (Option B), R5-gated per analysis. shape-fit products may ship
  class under the recorded caveats; per-analysis R5 re-validation remains mandatory for every
  NEW target (the gate line stays).

### CR-028 — benchmark staleness-check race under load (fixed)
- **Date:** 2026-07-07. The fast gate BREACHED while the 4-parallel rescan loaded all cores:
  `run_pyhf` judged freshness against the WORK-DIR mtime, which the post-subprocess log write
  bumps >1 s later under load — the artifact was fresh and numerically baseline-consistent.
  Fixed: staleness now compares against the step START time (the correct "produced by THIS
  run" semantics). Verified green under the same full-core load that exposed it.
- **Status:** EMBEDDED (2026-07-07).

### CR-023 — the SUMMARY-PLOT track (G1; census candidate #1)
- **Date:** 2026-07-07 (checkpoint C11).
- **What:** `docs/workflow/checklists/summary-plot.md` — the no-generation track behind
  `task_mode=summary_plot`: sensitivity census (P6+T4, physicist-reviewable inclusion table) →
  HEPData harvest → the **basis-manifest GATE** (`inputs/basis_manifest.json` schema v1: target
  basis + per-curve native basis/transformation/identity-check; nothing renders unmapped — G4
  lands as an artifact here) → one-panel overlay w/ per-curve provenance + FIRST-CLASS coverage
  gaps → `none-survey` labels. Worked precedent: the 2026-07-06 HVT survey run. Wired from
  physicist-intake.
- **Why:** census candidate #1 (2/7 prompts; forum type 2); the intake already routed these
  asks to a wall.
- **Status:** EMBEDDED as the declared track (2026-07-07); first full run through it = its
  acceptance test (P1 or P2 re-run).

### CR-024 — projection module (G2c; counting BUILT 2026-07-07 · likelihood BUILT 2026-07-11)
- **Date registered:** 2026-07-07 (checkpoint C12). Spec: `docs/workflow/reference/
  projection-replane.md` (counting mode first: f=L₂/L₁ with three DECLARED bkg-scaling
  scenarios reported together; likelihood mode second; validation gates: f=1 identity + one
  published projection point). Build ≈ one validation-first session.
- **BUILT (likelihood mode, 2026-07-11):** `project_limits.py likelihood` — transforms the
  PATCHED published HistFactory workspace (signal scales with f too) with per-modifier
  documented handling (g_sys/g_stat per scenario; obs := f·data ≡ the CR-profiled Asimov
  analog) and delegates every limit to `pyhf_exclude.py likelihood` via an empty patch (zero
  engine modification). Selftest: f=1 BIT-EXACT workspace identity (all 3 scenarios) + 9
  algebra spot-checks + f=4 toy ordering (frozen ≤ stat ≤ syst) + the counting regression.
  First real exercise: the 2026-07-11 SUSY-2020-04 run — f=1 re-run of the paper's own 34-point
  grid reproduced the published per-point CLs (mean |ΔCLs| ≈ 0.001, max 0.012 in the
  CLs≈0.97 unconstrained corner, expected AND observed).
- **Where-embedded:** `docs/workflow/reference/projection-replane.md` §Projection (likelihood-mode
  paragraph = the CLI + per-modifier table + gate status).
- **Status:** EMBEDDED (likelihood + counting built); OPEN remainder: the R5-analog comparison
  against ONE analysis's own published Run-3/HL-LHC projection point.
- **Verify:** `python3 src/ravel/physics/project_limits.py --selftest`

### CR-025 — replane module (G2d, SUSY slice; BUILT 2026-07-07 continuation-3)
- **Date registered:** 2026-07-07 (checkpoint C12). Spec: same file (spectrum via declared
  mixing-matrix tool + Option-D1 fold as the re-weighting engine; trap T3 composition handling;
  round-trip + published-replane validation gates; eval subject #7's writeup = the acceptance
  test). Non-SUSY replanes stay escalation territory per the census.
- **BUILT (fold half; the spectrum leg was spectrum_mix.py):** `trial-runs/_infrastructure/
  replane.py fold` folds a published simplified-model UPPER-LIMIT curve into a new SUSY plane —
  per target-plane point: spectrum_mix state (mass + gauge composition; charginos use the U/V
  mixing-matrix average) → composition-weighted σ×BR from pure-state references (winos produced
  ~3× higgsinos at equal mass — trap T3 made numeric) → published UL log-interpolated at the state
  mass → r = σ×BR/σ_UL, excluded where r≥1. Emits `replane.json` + a lint-gated (CR-016) r-map
  with the r=1 exclusion contour in the new plane, TeX axis labels, the T3 + tree-level caveats
  stamped, and the R5 gate printed on every run. `--selftest` PASS (4/4): **round-trip identity**
  (direct model = the σ that set the limit → r≡1 on the published contour, i.e. transform→invert),
  monotonicity, composition weighting (r_wino≈3×r_higgsino, mix between), log-interp sanity.
  Live demo: a real 36-point µ–M₂ grid (M₁=M₂, tanβ=50) folded to a clean exclusion contour with
  the composition shifting higgsino-like→wino-like across the plane as physics requires.
- **Status:** BUILT + selftest-verified + live-demo'd (2026-07-07). Remaining for a SHIPPED P7
  replane: the R5 validation run on the actual published limit (round-trip the paper's own plane)
  — the non-negotiable gate, same class as the D2 LLP validation run.
- **2-D UL-SURFACE mode added (2026-07-11):** compressed-spectrum searches limit σ vs BOTH a
  mass and a splitting — `--ul-curve` now also accepts `{mass, dm, sigma_ul_fb}` triplets
  (triangulated-linear interpolation on log UL; ~1e-6·range hull-edge snap guard for
  exactly-on-hull published corners under float noise) + `--dm-extra-curve {mass, value}` (the
  additive loop-splitting channel; the per-point dm is m(C1)−m(N1) tree + this term). Coverage
  is FIRST-CLASS: off-hull points are `covered: false` (r null — not excluded, NOT allowed),
  rendered grey (T4). Selftest grew to 6/6 (planar 2-D round-trip incl. snapped corner + hull
  honesty). Embedded: `docs/workflow/reference/projection-replane.md` §Replane 2-D paragraph.
  First real exercise: the 2026-07-11 SUSY-2020-04 µ–M₂ replane run.

### CR-026 — figure-SPEC block + bounded visual-critique loop (M4b; registered, OPEN — spec complete)
- **Date registered:** 2026-07-07 (checkpoint C13). Spec in `checklists/figure-contract.md`
  §Figure-SPEC: the `style` block (visual grammar read off the extracted figure — facts, not
  defaults) + the fresh-context structural-critique loop (≤2 iterations; survivors become
  caption'd deviations). Owns the CONTENT half of R6 (the CR-016 lint gate owns layout).
  Acceptance test: one live loop on the fig3 side-by-side.
- **ACCEPTANCE PASSED (2026-07-07 continuation** — `overnight-roadmap/inputs/
  figure-critique-fig3.md`): a fresh-context critic ran the loop once, live, on the real
  extraction (provenance double-confirmed): **0 breaks-comparability — the 2026-06 blocky-lattice
  form claim SURVIVES adversarial review** — plus 5 degrades-level mismatches eyeball
  form-verification never flagged (palette family bwr-vs-RdBu_r; the published axis WINDOW
  vs our grid-driven one; the missing DELPHES-default gray series; ours ADDS an ATLAS stamp the
  published figure lacks — a provenance hazard; 'mapyde (native)' naming) + 7 cosmetic. Fix #1
  (the saturated bwr payload palette) APPLIED + re-rendered (medians unchanged); the remaining
  degrades items = caption'd deviations per the protocol + the style-block schema example now
  exists (read off the published pixels).
- **CODE EMBEDDED (2026-07-07 continuation-3, Opus):** the `style`-block half is now BUILT in
  `figure_target.py` — `STYLE_FIELDS` schema (8 visual-grammar facts + source), `merge_style`,
  `read_style` consumption API (mirrors `read_axes`), `--style-json` on declare, style printed in
  `show`, and a `critique` subcommand (EMIT the fresh-context task = composite + style facts +
  9-item structural rubric; `--record` stores findings, surviving mismatches → caption'd
  deviations, loop bounded at 2 with a warning past it). Full lifecycle tested on a scratch
  contract (declare→show→critique-emit-guard→record→iteration-warning) + a LIVE acceptance run on
  the real CMS-EXO-22-026 Figure 5 published-vs-generated side-by-side (style declared off the
  published panel; a fresh-context critic scored the composite blind — `overnight-roadmap/inputs/
  cr026-fig5-critique.json`).
- **Status:** EMBEDDED (2026-07-07). Both halves done — loop proven (fig3) + style-block code
  (built, lifecycle-tested, live-run on Fig 5). The figure contract now carries R6's content half.

### CR-021 — step-3 card/spec PREFLIGHT BUNDLE (SSL half DONE 2026-07-07; card half OPEN)
- **What:** (a) **DONE:** the SSL-residue sweep — `hepdata_fetch.py`, `fetch_figures.py`,
  `nlo_xsec.py` no longer fall back to unverified TLS; policy = certifi-verified or fail with
  instructions (matching CR-017's pattern; compile-checked). (b) **OPEN:** the card preflight —
  `lhe_check --expect-from-card` (masses/decays derived from the card, not hand-typed), a
  card-lint (MSOFT-vs-MASS override, width-only DECAY tables, unrendered placeholders — T11),
  and the MadGraph `set param_card` silent-no-op guard.
- **Why:** mining recurrence class #2 (card/intent mismatches, incl. the 181-as-300 near-miss);
  SSL residue was mining #8.
- **Status:** **FULLY EMBEDDED (2026-07-07 continuation)** — `lhe_check --expect-from-card`
  derives expectations from the card itself (verified live: 1000013:200 derived + matched in
  event+banner on the smoke point) + the card lint (unrendered placeholders FAIL; width-only
  DECAY = FAIL only for PRODUCED states, compact WARN for spectators — the produced/spectator
  severity split was tuned on the live slepton card, which legitimately carries 22 spectator
  width-only tables; MSOFT/HMIX override WARN). Remaining nicety: the MadGraph `set param_card`
  no-op note in the docs (one line, model-cards checklist).

### CR-022 — run-dir SESSION.lock (BUILT 2026-07-07, overnight-2)
- **What:** `session_lock.py` — cooperative, human-readable run-dir ownership: acquire/check/
  release/steal with a stale-hours rule and a recorded takeover history; a live foreign lock
  refuses (exit 3), stealing is explicit and logged. Semantics verified end-to-end (acquire →
  foreign-check refusal → foreign-acquire refusal → recorded steal → release). Wired: the
  `new-analysis` skill acquires the lock FIRST at scaffold (mirrored).
- **Why:** two eval subjects silently shared one run dir 18 s apart; supervisor-vs-charter edit
  races (mining #5).
- **Status:** EMBEDDED (2026-07-07); remaining nicety = orchestrator-level scan-dir locks
  (launch already serializes through the manifest, so per-run locks cover the incident class).

### CR-018 — lhe_check weight-sign false-FAIL on the validated reference LHE (registered, OPEN)
- **Date registered:** 2026-07-06 (transcript mining, recent-sessions pass).
- **What:** `lhe_check.py`'s mixed-weight-sign guard FAILs the project's own validated reference
  LHE (1 negative weight / 200 sampled; re-verified live during mining; never adjudicated). A
  mandatory gate that false-FAILs a known-good input erodes trust in every gate (second
  guard-false-FAIL after catalogue C2's BW-tolerance case).
- **ADJUDICATED + FIXED 2026-07-07 (overnight-2):** the negatives are REAL, BENIGN PDF physics —
  NNPDF30_nlo (lhaid 260000, the container reference's own set) is non-positive-definite at
  large-x sea antiquarks; 19/50,000 events, sign(w)=sign(f₁f₂) verified on ALL 50k, net Σw
  effect −0.076% (invisible vs the 0.51% µ₉₅ parity); zero negatives in 1.01M nn23lo1 events.
  The validated reference STANDS. `lhe_check.py` now applies the fractional policy: FAIL on any
  zero weight or (nneg≥3 AND >0.5%); WARN otherwise with the CR-018 citation (magnitude
  deliberately not a criterion — unweighting quantizes weights to ±σ̂). Reference re-run:
  WARN + RESULT OK. Full evidence: `overnight-roadmap/inputs/cr018-adjudication.md`.
- **Status:** CLOSED (2026-07-07).

## Deferred physics (decided, scheduled after the charter work)

### CR-004 — residual-closure rescan: LHAPDF lhaid=260000 + higher stats + ptj1min=50
- **Date registered:** 2026-07-06
- **What:** re-run the 52-point fig3 grid with (a) LHAPDF/NNPDF `lhaid = 260000` (cteq6l1 was
  used; affects absolute-σ normalization only — acc×eff is σ-independent), (b) >20k events/point,
  (c) `ptj1min = 50` after CR-002 lands, (d) verified Delphes soft-lepton tuning where available.
- **Why:** this is the **only lever on the ~26% median same-basis residual**
  |(mapyde−ATLAS)/ATLAS| — now the leading term after the NLO renorm + comparison-basis rebase.
- **Where-embedded (when done):** a new assembled `scan.json` + refreshed fig3 artifact +
  RESULT.md decomposition; `docs/development/status.md` headline updated.
- **Status (2026-07-07 continuation-3, Opus; line reconciled 2026-08-28 — it stalely said
  "RUNNING + PRELIMINARY"):** COMPLETE — 52/52 points done (`trial-runs/CR004rescan_SCAN/scan.json`:
  n_done=52, n_missing=0); final numbers per `CR004rescan_SCAN/CR004-FULL-RESULT.md` (and the
  FINAL FINDING below): median same-basis |σ-UL residual| = **22.0%** (20.8% obs / 17.0% exp on
  the fig3 panels), point-matched σ-UL(nn23nlo)/σ-UL(cteq6l1) median **+6.5%** — the PDF is a
  minor contributor; entry CLOSED (see the closing Status line). Setup context: CR-002 is fixed; the
  LHAPDF/arm64 link blocker (D1) means the rescan basis is MG-internal `nn23nlo` (NNPDF2.3 NLO) via
  the `--pdf nnpdf30` path now wired into `prepare_native_slepton.py` + `scan_orchestrator launch`.
  The 52-point rescan (`trial-runs/CR004rescan_SCAN`, **same grid + 20k events/point** as the
  cteq6l1 record scan → isolates the PDF term) is driven by `scan_babysitter.py` (CR-029).
- **FINAL FINDING (52/52, both scans on the model-σ basis; `CR004rescan_SCAN/CR004-FULL-RESULT.md`)
  — the PDF is a MINOR contributor, not the dominant lever:** median |(mapyde−ATLAS)/ATLAS| σ-UL
  residual = **22.0%** (vs the cteq6l1 record's ~24–26% — a ~2–4 point trim), and the point-matched
  σ-UL ratio nn23nlo/cteq6l1 has a robust median **+6.5%** (mass-dependent: ≈0 at low mass, larger
  at the higher masses). So cteq6l1 → NNPDF2.3-NLO moves the residual only a few % — it is still
  dominated by **acceptance / fast-sim / statistics**, exactly as the RESULT.md argued. The residual
  levers are higher stats + fast-sim (Delphes) tuning, NOT the PDF (CR-004's original LHAPDF
  hypothesis is thereby answered in the negative).
- **Two bugs caught + fixed on the way to this number (do not repeat):** (1) the automated
  completion-watcher fired at 50/52 (a `scan_orchestrator status` race while 2 points transitioned)
  AND its `rebase` had silently FAILED, so its first-pass numbers (71% / −55.8%) were on the WRONG σ
  basis — never trust a rebase-failed comparison. (2) The rebase failure root cause: a HEALED/re-run
  point's `madgraph.log` lacked the `Cross-section :` summary line (MadGraph reused a cached refine),
  so `sigma_ref_fb` returned None → the point had no σ_ref → rebase aborted. FIXED: `sigma_ref_fb()`
  now falls back to `analysis.log`'s `Using cross section X` (the same pb value fed downstream) when
  madgraph.log lacks the summary — healed points no longer break the rebase. Catalogue C7.
- **Status:** CLOSED (2026-07-07) — the residual-closure question is answered: the PDF is not it.
  Remaining physics levers (higher stats + Delphes tuning) are separate future work, not CR-004.

### CR-029 — scan_babysitter: self-cleaning, disk-safe, auto-healing scan driver
- **Date:** 2026-07-07 (continuation-3). `src/ravel/workflow/scan_babysitter.py`.
- **What:** a native scan leaves ~6 GB regenerable intermediates/point; on this laptop that fills
  the disk (CR-004 rescan lost 8 points to `NoSpaceLeftError`) and a process exit truncates
  in-flight Delphes ROOT files (4 more points → ZeroDivisionError). The babysitter loops: CLEAN
  (drop `output/{madgraph,delphes,PROC_madgraph,analysis}` from completed points, curated trio
  kept), HEAL (reset FAILED + stale-running points to pending), FEED (launch pending to a
  `--parallel` cap only while free-disk ≥ `--min-free-gb`). Reclaimed 218 GB on first run; the
  live-process detector is per-line (never counts the babysitter itself). Catalogue C6.
- **Status:** EMBEDDED (2026-07-07); driving the CR-004 rescan to completion now.

### CR-005 — native-backend generalization beyond slepton/EwkCompressed2018
- **Update 2026-08-16:** ACTIVATED — session protocol written
  (`framework/CR005-NATIVE-SA-GENERALIZATION.md`: shared-core refactor + 2 counting-routine
  ports + the flagship's own bit-for-bit bar), supervisor-approved. The podman VM oracle was
  DELETED the same day (~12 GB reclaimed; 2 months cold; ENVIRONMENT-CHANGES 2026-08-16) — the
  new standard is per-validation re-provision (boot + SA image ≈3–4 GB), then delete again.
- **Date registered:** 2026-07-06
- **What:** generalize `native_simpleanalysis.py` + `prepare_native_slepton.py` +
  `run-pipeline-native.sh` beyond the slepton/EwkCompressed2018 pair so "native default" stops
  silently meaning "this one analysis only" — per `framework/OPTION-C-DESIGN.md` and the porting
  contract in `docs/workflow/reference/native-pipeline.md`.
- **Why:** PLAN-OF-RECORD item 5 (generality); the native default is otherwise a single-analysis
  claim.
- **ADVANCED (2026-07-07 continuation-3, Opus) — the common cut-based case now generalizes:**
  `src/ravel/physics/native_sa_generic.py` is a DECLARATIVE native SimpleAnalysis engine
  for the ~85% of SA analyses that are cut-and-count on standard objects (the 4 archetypes: 0ℓ
  jets+MET, 1ℓ+jets, 2ℓ, monojet — NO recursive jigsaw). It REUSES the validated framework
  primitives from `native_simpleanalysis.py` (Obj, filterObjects, overlapRemoval, invmass, calcMT,
  minDphi — imported, never duplicated; the bit-for-bit EwkCompressed2018 path is UNTOUCHED) and
  runs a JSON analysis spec: baseline object defs → declared overlap-removal order → signal
  tightenings → a derived-variable library (nLep/nJet/nBjet/MET/HT/meff/mTlep/mll/dphiMin/jetNpt/…)
  → a declarative SR cut cascade → per-SR weighted yields. Porting a cut-based analysis is now a
  spec file, not a C++→Python rewrite. `--selftest` PASS: exact SR yields on hand-computed events,
  overlap removal (el-overlapping jet dropped), b-tag counting, mT/meff/dphiMin variables. A
  Delphes-ROOT reader (`run --delphes … --spec … --xs-pb …`) is the real-input path.
- **Status:** ADVANCED — common cut-based case BUILT + selftested. REMAINING: (a) an end-to-end
  validation of the declarative engine on a real Delphes ROOT vs a container SA run for one
  cut-based analysis (the bit-parity claim for the generic path); (b) RJR / bespoke-tagger analyses
  stay per-analysis ports (EwkCompressed2018 is the worked RJR example; the `--objects` interface
  already generalizes the RJR solve); (c) `prepare_native_*` generalization beyond slepton cards.
- **DEFER TRIGGER (recorded 2026-07-08, Task 8.2 — I9):** REMAINING(a) needs the container x86
  path (~9 h/point) + a real sample to validate the declarative engine's bit-parity against a
  CONTAINER SA run for a SECOND (cut-based, non-RJR) analysis family — heavy-gen, so it stays
  DEFERRED. **TRIGGER:** (i) a real physics request routes to a cut-based non-RJR SA analysis, or
  (ii) the heavy-gen/container defer lifts generally; either way then run the
  LIMITATIONS-TRIAGE #14 falsification test (one simple container routine, ONE existing sample,
  per-SR parity) and write the PRODUCT-CONTRACT §2 native-SA-coverage scope row FIRST (not now —
  avoid build-ahead). REMAINING(c) — generalizing `prepare_native_slepton.py` beyond slepton
  cards — stays un-started for the same reason; do not build it ahead of the trigger.
- **Status update 2026-08-16: EMBEDDED — the trigger fired (supervisor: pre-publication
  requirement) and the generalization is BUILT + oracle-proven.** Evidence:
  (a) `sa_native_core.py` = the shared routine-agnostic layer (verbatim-extracted primitives,
  SA header-VERBATIM ID-bit vocabulary, pinned helper semantics: the SORTING `operator+`,
  first-N `sumObjectsPt`/`minDphi`, momentum-tensor `aplanarity`, variable-radius OR).
  Flagship REGRESSION: old-vs-new code byte-identical on a fresh 10k input AND 141/141
  bit-for-bit vs the LIVE container on that same input (three-way anchor).
  (b) TWO new routines ported + oracle-validated bit-for-bit FIRST TRY:
  `ZeroLeptonDiscovery2018` (ATLAS-SUSY-2018-22, 10/10 SRs, squark-pair sample) and
  `EwkThreeLeptonERJR2018` (ATLAS-SUSY-2018-06, 9/9 SRs incl. its boost-emulated RJR
  variables, C1N2 WZ sample) — the LIMITATIONS-TRIAGE #14 falsification test, passed twice.
  (c) `native_sa_generic.py` now imports from the core (one implementation everywhere).
  (d) Recipe + traps embedded: `docs/workflow/reference/native-pipeline.md` §porting; oracle is
  per-use via `cr005_validate.py` (provision → bit-for-bit gate → teardown; VM disk stays
  reclaimed). (e) `run-pipeline-native.sh` lhe_check now falls back to `--expect-from-card`
  for points without slepton-style `[madgraph.masses]` (REMAINING(c) partially served: manual
  rundir materialization is the documented sample path; a generic prep tool stays un-built).
  **Named follow-ups:** per-analysis acc×eff certs + µ95 anchors for the two new routines
  before either SERVES physics results; further routines port-on-demand via §porting.
  - **Follow-up status 2026-08-28:** the acc×eff certs + µ95 anchors for
    `ZeroLeptonDiscovery2018` + `EwkThreeLeptonERJR2018` are **SCHEDULED — not done** — in the
    Aug-28 adversarial campaign (`framework/overnight-roadmap/ADVERSARIAL-CAMPAIGN-2026-08-28.md`,
    Phase-3 board item #2: "CR-005 routine certs + µ95 anchors (benchmark-point smokes)",
    slotted SAT after the P1 scan). The serve-gate above stands until they land.
  - **Follow-up status 2026-08-29: DONE — verdict FAIL for BOTH routines; the serve-gate STAYS CLOSED.**
    Evidence: `trial-runs/CR005cert_{ss_1200_600,gg_2200_600,gg1step_2200_600,c1n2_300_100}/`
    (WORKLOG + cert JSON + µ95 anchors each). Multi-jet lanes MLM-merged at scan-decided xqcut
    (SS 200 → matched/LO 0.996; GG 220 → 0.997); c1n2 deliberately unmerged (EWK skip rule).
    `ZeroLeptonDiscovery2018` (ins1827025): FAIL at all three benchmarks — A×ε ratios ≈0.71
    (2j/4j driving) → 0.67 (5j) → 0.51 (6j) → 0.41–0.56 (hardest-meff SRs): a coherent deficit
    ladder across independent grids/processes (≥10σ, not transcription; candidates recorded
    unconfirmed: fast-sim jet/MET floor + radiation share). `EwkThreeLeptonERJR2018`
    (ins1771533): FAIL (driving SR-low 0.348; ISR family consistent 1.11±0.26). µ95 anchors
    (published bkgonly + CR-142 robust pyhf): exclusion DIRECTION agrees with the paper at every
    point; limits 1.4–2.9× weaker, tracking the acceptance deficits; 6j-3400 escalated+recovered
    (first production firing of the CR-142 guard); CR-142 refuses the sick c1n2 ours-patch
    surface (edm 0.19) — retired-wrapper µ95_ours downgraded to indicative. **Neither routine
    may serve physics results.** Reopen path: per-cut decomposition vs published cut_flow_1/2,
    Delphes jet/MET response audit, qCut 1.5× spot-check; then re-run the lanes (per-lane
    `config/production.sh` + `config/cert_and_anchor.sh`, ~50–85 min each).

### CR-006 — clean-room self-drive proof
- **Date registered:** 2026-07-06
- **What:** a fresh agent, clean state, given only the repo + the physicist prompt, self-drives
  the full reproduction with **zero operator intervention** — the genuine "partial → yes" flip on
  self-drive (PLAN-OF-RECORD success criterion 3, trial item 4).
- **Why:** the canonical proof requires the WORKFLOW to drive, not the operator; never yet run
  clean-room.
- **Status:** DEFERRED (after charter P4 routing evals harden intake/routing).

### CR-045 — spine-hardening isolated worktree (Phase 0 Task 0.1)
- **Date registered:** 2026-07-09
- **What:** a git worktree `wt-spine-hardening` on branch `spine-hardening` off `harness-phase0-3-rework`,
  with the gitignored `stages/01-event-generation/build` conda toolchain symlinked from the main tree, and
  `docs/development/history/worktree.md` documenting the recipe.
- **Why:** the workflow-adherence enforcement spine (Phases 0–7) wires `Stop`/`PostToolUse`/`UserPromptSubmit`
  hooks into `.claude/settings.json`; those must never fire on the concurrently-running live SVJ trial in the
  main tree. An isolated worktree has its own `.claude/settings.json`. The symlink lets later phases' smoke
  compute run in the worktree. (Gotcha found at execution: the `stages/**/build/` dir-pattern does NOT ignore
  a symlink — excluded locally via the worktree `info/exclude`; see WORKTREE.md.)
- **Verify:** `test -L stages/01-event-generation/build && stages/01-event-generation/build/tools/miniforge3/bin/conda --version`

### CR-046 — spike_probe.py L0 spike recorder/verifier (Phase 0 Task 0.2)
- **Date registered:** 2026-07-09
- **What:** `tests/adversarial/spike_probe.py` — a stdlib-only, read-only, fail-loud recorder/verifier for the
  three L0 harness-behaviour spikes that the workflow-adherence spine rests on: **SPK-1** hooks fire
  (Stop/PostToolUse/UserPromptSubmit each fire; the Stop exit-2 blocks turn-end and feeds its reason back),
  **SPK-2** a `run_in_background` job's stdout re-invokes the agent on completion, **SPK-3** a scheduled wake
  re-fires at ~the set time. `build_record(spike, evidence)` verifies one spike's evidence and emits a durable
  artifact (`schema_version`, `generated_by`, `input_fingerprint`, `verdict`, per-spike hook-primary\|
  fallback-primary `decision`, `checks`, `exit`); the `verdict` defaults to the non-passing `unproven` (PASS is
  earned) and `exit`=0 iff PASS. `build_primacy`/`check_primacy` synthesize + re-verify the per-branch
  `HOOK-PRIMACY.json` hook-vs-fallback table (14 enforcement branches, each governed by a spike). CLI:
  `--new-token`, `--spike SPK-{1,2,3} --record/--check`, `--primacy`, `--check-primacy`, `--selftest`; exit
  codes 0 PASS · 1 spike/consistency FAIL · 2 usage/IO · 3 malformed evidence/artifact.
- **Why:** the spine's L3/L4 gates assume the harness actually fires the hooks (and re-invokes on bg-completion
  / timed wake). Those runtime assumptions must be *proven and durably recorded* — with provenance
  (`generated_by`+`input_fingerprint`, so `--check` recomputes and rejects a tampered artifact with exit 3) —
  before any gate is wired to depend on them; `HOOK-PRIMACY.json` then routes each branch to its hook path only
  when its governing spike PASSed, else to the fallback. Presence never satisfies; the artifact must recompute.
- **Where-embedded:** `docs/development/history/worktree.md` (spike-verifier pointer); `DIRECTORY.md` `spine/` row
  (interface + `tests/test_spike_probe.py`). Tests: `tests/unit/test_spike_probe.py` (6) + the built-in
  `--selftest` (14 cases).
- **Status:** EMBEDDED.
- **Verify:** `python3 tests/adversarial/spike_probe.py --selftest && REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_spike_probe.py" -q`

### CR-047 — SPK-1 hooks-fire proof (G0a) (Phase 0 Task 0.3)
- **Date registered:** 2026-07-09
- **What:** Wired three trivial PROBE hooks into the worktree `.claude/settings.json` — `UserPromptSubmit`,
  `PostToolUse` (matcher `Bash|Edit|Write`), and a one-shot `Stop` — alongside the existing `PreToolUse`
  card-guard (kept byte-for-byte), and recorded the G0a spike artifact `evidence/hooks/spk-1.json`
  (`verdict=unproven`, `decision=fallback-primary`) via `spike_probe.py`, from a REAL headless `claude -p`
  turn — NOT from hand-driven sentinels. Observed on this host: the turn fired `UserPromptSubmit` LIVE (one
  sentinel logged, `ok:true`), proving the harness loads the worktree `.claude/settings.json` and invokes
  hooks on a real turn; the nested agent then hit the OAuth login check (`"Not logged in · Please run /login"`,
  `is_error:true` in the recorded `-p` transcript) and exited before any tool call or turn-end, so
  `PostToolUse` and `Stop` never fired and their four checks are honestly `ok:false`. Per the Step-3/4
  decision tree an OAuth-limited host that cannot drive a nested tool call/turn-end yields a valid RECORDED
  `unproven` outcome (not a task failure): `spike_probe.py` records `decision=fallback-primary`, so Task 0.6's
  `HOOK-PRIMACY.json` routes every SPK-1 branch to its fallback (the safe default — an unproven hook is never
  sole authority). The `Stop` exit-2 block feeding its `SPK1-STOP-BLOCK` reason back is corroborated in-repo by
  the `PreToolUse` card-guard precedent (exit-2 blocking already proven) and is exercised in the Phase-5
  `spine_sim`, but is deliberately NOT recorded as a live SPK-1 check. Re-driving Step 3 on an authenticated
  host upgrades G0a to a live PASS/hook-primary with no schema change. The three PROBE blocks are inert once
  SPK-1 is recorded (append-and-`exit 0`; the `Stop` probe is one-shot, guarded by `logs/.spk1-stop-fired`).
- **Why:** the spine's L3/L4 gates assume the harness actually fires the hooks (exit-2 blocks turn-end + feeds
  the reason back). G0a must be *proven and durably recorded* — with provenance (`generated_by` +
  `input_fingerprint`, so `--check` recomputes and rejects a tampered artifact) — before any gate is wired to
  depend on it; `HOOK-PRIMACY.json` then routes each SPK-1 branch to its hook path (PASS) or the fallback.
- **Where-embedded:** `docs/development/history/worktree.md` ("Spike outcomes" section — the SPK-1 `unproven`
  verdict, the real-turn-vs-OAuth-limit evidence, the upgrade path, and the D-1 idempotent-merge rule for
  the probe blocks); `DIRECTORY.md` (`.claude/hooks/spk1-*.sh` probe-scripts row; the `spine/` row already
  indexes `spikes/SPK-{1,2,3}.json`).
- **Status:** EMBEDDED.
- **Verify:** `python3 tests/adversarial/spike_probe.py --spike SPK-1 --check evidence/hooks/spk-1.json --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['consistent'] and d['verdict']=='unproven', d; print('OK: consistent honestly-recorded unproven G0a')"`
  (raw `--check` exits 1 because the recorded verdict is `unproven`, which is correct — `consistent=true`
  confirms the artifact faithfully recomputes from its embedded real-turn evidence; upgrade to a live PASS by
  re-driving Step 3 on an authenticated host).

### CR-048 — SPK-2 completion re-invocation proof (G0b) (Phase 0 Task 0.4)
- **Date registered:** 2026-07-09
- **What:** Recorded the G0b spike artifact `evidence/hooks/spk-2.json` (`verdict=PASS`,
  `decision=harness-reinvoke-primary`) via `spike_probe.py`, from a live token round-trip through the
  harness `run_in_background` completion channel. A per-run unguessable token minted by `--new-token`
  (`SPK-e3acc687cd66`) was echoed by a `run_in_background`-tracked job (`sleep 5; echo "SPK2_DONE <TOK>"`);
  the turn ended WITHOUT polling; the harness re-invoked the agent when the job exited (a
  `<task-notification status=completed>` event carrying the job stdout), so the same unforgeable token
  appears in BOTH `launch_cmd` and the captured `reinvoke_text` (recorded verbatim in
  `evidence/hooks/spk-2.evidence.json`). The verifier was first proven armed (red): the same
  evidence with the token withheld from `reinvoke_text` records `verdict=unproven`,
  `decision=poll-fallback-primary`, exit 1 — so a PASS cannot be fabricated without the genuine round-trip.
- **Why:** the spine's DRIVE lever (`drive_completion_reinvoke`) assumes a backgrounded job's stdout
  re-invokes the agent on completion; G0b must be *proven and durably recorded* (with provenance —
  `generated_by`+`input_fingerprint`, so `--check` recomputes and rejects a tampered artifact) before
  Task 0.6's `HOOK-PRIMACY.json` routes that branch to its harness-reinvoke primary (else the
  poll-the-logfile fallback). N6 constraint: the mechanism MUST be the harness `run_in_background`, never
  `nohup`/`start_new_session` (which silently defeats the completion notification), so DRIVE mandates
  `run_in_background` for every long job.
- **Where-embedded:** `docs/development/history/worktree.md` ("Spike outcomes" — the SPK-2 PASS verdict, the
  token-round-trip evidence, and the N6 `run_in_background`-not-`nohup` rule); `DIRECTORY.md`
  (`framework/spine/spikes/SPK-2.{evidence.json,json}` row).
- **Status:** EMBEDDED.
- **Verify:** `python3 tests/adversarial/spike_probe.py --spike SPK-2 --check evidence/hooks/spk-2.json`
  (exit 0 iff the recorded verdict is PASS and the artifact recomputes from its embedded evidence).

### CR-049 — SPK-3 scheduled-wake proof (G0c) (Phase 0 Task 0.5)
- **Date registered:** 2026-07-09
- **What:** Recorded the G0c spike artifact `evidence/hooks/spk-3.json` (`verdict=PASS`,
  `decision=wake-primitive-primary`) via `spike_probe.py`, from a live de-facto timed wake. A wake was
  scheduled 120 s out on the SPK-2-confirmed harness `run_in_background` completion re-invoke (launch
  `07:10:38Z` + 120 s = scheduled `07:12:38Z`); the turn ended without polling; the harness re-invoked
  the agent on the bg job's completion carrying its stdout (`SPK3_WAKE … bg_done=2026-07-09T07:12:38Z`),
  so `fired_utc = scheduled_utc` to 1 s resolution — **observed wake latency ≈ 0 s**, inside the 30 s
  tolerance that absorbs re-invoke jitter (evidence verbatim in `evidence/hooks/spk-3.evidence.json`).
  The verifier was first proven armed (red): the same evidence with a 30-min-late `fired_utc` records
  `verdict=unproven` / `decision=bg-sleep-reinvoke-fallback` / exit 1, so a PASS cannot be fabricated.
- **Decision (execution adjustment):** the scheduled-wake mechanism is **background-job completion
  re-invocation (bg-sleep-reinvoke)** — the mechanism available AND confirmed in this harness (same as
  SPK-2). A dedicated `ScheduleWakeup` primitive (`mcp__scheduled-tasks__*`) is a secondary/unconfirmed
  path and is deliberately NOT relied on. `spike_probe.py`'s decision enum ties `wake-primitive-primary`
  to the within-tolerance PASS (not to the mechanism string), so the recorded `decision` reads
  `wake-primitive-primary` where the proven wake primitive is the bg-sleep re-invoke; the mechanism +
  `note` fields and the WORKTREE "Spike outcomes" line carry the bg-sleep-reinvoke provenance.
- **Why:** the spine's timed levers (`scheduled_wake`, `progress_reporter_30min`) assume a wake set for
  `T` re-fires at ~`T`; G0c must be *proven and durably recorded* (with provenance —
  `generated_by`+`input_fingerprint`, so `--check` recomputes and rejects a tampered artifact) before
  Task 0.6's `HOOK-PRIMACY.json` routes those branches to their wake-primitive primary (else the
  bg-sleep-reinvoke fallback). The mechanism is the harness `run_in_background`, never
  `nohup`/`start_new_session` (N6: a detached process silently defeats the completion notification).
- **Where-embedded:** `docs/development/history/worktree.md` ("Spike outcomes" — the SPK-3 PASS verdict, the
  bg-sleep-reinvoke decision, the ≈0 s observed wake latency, and the red-case armed proof);
  `DIRECTORY.md` (`framework/spine/spikes/SPK-3.{evidence.json,json}` row).
- **Status:** EMBEDDED.
- **Verify:** `python3 tests/adversarial/spike_probe.py --spike SPK-3 --check evidence/hooks/spk-3.json`
  (exit 0 iff the recorded verdict is PASS and the artifact recomputes from its embedded evidence).

### CR-050 — HOOK-PRIMACY.json per-branch enforcement decision (L0) (Phase 0 Task 0.6)
- **Date registered:** 2026-07-09
- **What:** Synthesized `evidence/hooks/hook-primacy.json` — the authoritative per-branch
  `{governed_by, primary, fallback}` table for all 14 enforcement branches — via
  `spike_probe.py --primacy` over the recorded SPK-1/2/3 verdicts. Result: the 11 SPK-1-governed
  branches route to `primary=fallback` (G0a is the honest `unproven` record, so the agent-invoked twin
  is the enforcement of record); `drive_completion_reinvoke`→`harness-reinvoke` (SPK-2 PASS); and
  `progress_reporter_30min`/`scheduled_wake`→`wake-primitive` (SPK-3 PASS = the confirmed harness
  completion-re-invoke channel). The artifact carries `generated_by`+`input_fingerprint` over the
  embedded spike decisions, so `--check-primacy` recomputes and rejects a tamper AND asserts every
  branch's `primary` is consistent with its governing spike's verdict (14 branches, all consistent).
- **Decision (execution adjustment):** `userpromptsubmit_route` + `pretooluse_skill_precedence` are the
  hook-primary-BY-DESIGN pair (proven-fire basis: `UserPromptSubmit` live-fired in SPK-1 +
  `PreToolUse` card-guard exit-2 precedent) and the first to promote to machine `primary=hook` on a
  live authenticated SPK-1 PASS; every `stop_*` and `posttooluse_*` branch is hook-primary-by-design
  with the **fallback co-authoritative** (turn-end/loop blocking is not live-automatable on this
  OAuth-limited host, so the twin ships as the authoritative enforcement of record until a live
  authenticated worktree session confirms); `drive_completion_reinvoke`/`progress_reporter_30min`/
  `scheduled_wake` are the harness-reinvoke family (SPK-2/SPK-3 confirmed). While SPK-1 is `unproven`
  the machine `primary` for all 11 SPK-1 branches is `fallback` — the safe default that `check_primacy`
  and `test_primacy_flips_on_spk1_fail` both lock in; the hook-primary design intent is recorded as the
  promotion order (in `WORKTREE.md`), not as a trusted sole authority.
- **Why:** this is the L0 decision output the whole spec §4 "hooks + fallback" principle keys on —
  Phases 2/3/4 read it, per branch, to decide whether the hook or its twin is the enforcement of
  record. It must be a PROVENANCED synthesis of the recorded spikes (not a hand-asserted table), so a
  branch is trusted to its hook only when its governing spike PASSed; missing spikes degrade safe
  (every branch → fallback), never to hook-primary.
- **Where-embedded:** `docs/development/history/worktree.md` ("Hook primacy (L0 decision)" — the honest
  per-branch table, the binding rule, and the promotion order); `DIRECTORY.md`
  (`evidence/hooks/hook-primacy.json` row).
- **Status:** EMBEDDED.
- **Verify:** `python3 tests/adversarial/spike_probe.py --check-primacy evidence/hooks/hook-primacy.json`
  (exit 0 iff `input_fingerprint` recomputes from the embedded spike decisions AND every branch's
  `primary` is consistent with its governing spike's verdict).

### CR-051 — provenance base (G19) — generated_by+input_fingerprint shared helper (Phase 1 Task 1.1)
- **Date registered:** 2026-07-10
- **What:** Added `src/ravel/workflow/provenance.py` — the stdlib-only SINGLE source of the
  run_state / lifecycle-required-artifact provenance fingerprint. It exposes `PROV_KEYS`,
  `sha256_bytes`/`sha256_file`, `fingerprint(input_paths)` (deterministic ordered sha256-of-sha256s;
  empty list → the stable empty-string hash), `provenance_pair(tool_id, input_paths)` (the two-field
  `generated_by`+`input_fingerprint` stamp every `--verify-provenance`-checked emitter merges into its
  artifact), `verify_pair(record, tool_id, input_paths)` (recomputes the fingerprint from the same
  declared inputs and rejects a missing/blank/mismatched `generated_by` or a drifted fingerprint), and a
  diff-stable `_resolve_timestamp` mirroring `shape_fit._resolve_timestamp`. `--selftest` runs 6 cases
  (deterministic fingerprint, pair shape, genuine-record verify, hand-written reject, fingerprint-drift
  reject, empty-input stability) → `provenance selftest: PASS (6 case(s))`, exit 0. Test:
  `tests/unit/test_provenance.py` (3 cases, TDD-first).
- **Why:** the spec's "provenance, not presence" principle (design principle 5) needs ONE formula so a
  gate can PROVE a lifecycle-required artifact was PRODUCED by its tool, not hand-written/backfilled.
  Later Phase-1 tasks and Phases 3/4 import these helpers VERBATIM rather than reimplementing the
  fingerprint; DOMAIN SEPARATION (D-7) keeps this disjoint from a domain-specific emitter's own
  fingerprint (e.g. `sr_plausibility.json`), which is deliberately NOT verified against this formula.
- **Where-embedded:** `DIRECTORY.md` (`_infrastructure/` block, the `provenance.py` row); consumed later
  by `validate_run_state.py --verify-provenance` and the run_state emitters (Phase 1 Tasks 1.2+).
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_provenance.py" -q`
  (3 passed) and `python3 src/ravel/workflow/provenance.py --selftest` (exit 0).

### CR-052 — workflow_state.py init + run_state.json schema (L1/L2 keystone) (Phase 1 Task 1.2)
- **Date registered:** 2026-07-10
- **What:** Added `src/ravel/workflow/workflow_state.py` — the LIVE per-run state machine (the
  keystone ledger) that writes and drives `<rundir>/run_state.json`, the single source of truth for
  which skills were invoked, what compute was launched, which subagents ran, what was edited, and
  (via a later `advance`) how far the lifecycle has progressed. This task lands the skeleton + the
  `init` subcommand: `RUN_STATE_NAME`/`SCHEMA_VERSION=1`/`GENERATOR`, the nine appendable `LIST_KEYS`
  (`skills_invoked`/`compute_launched`/`subagents`/`edits`/`obligations`/`open_failure_records`/
  `open_defect_notes`/`armed_watchers`/`checkins`), `_state_path`/`load_state`/`write_state` (atomic
  `.tmp`+`os.replace`), `new_state(rundir, contract, contract_path, session_id)` (every §C schema key
  present, lists empty, provenance stamped via `provenance.provenance_pair(GENERATOR, [contract])`),
  `cmd_init`/`build_parser`/`main`/`selftest`. `init` validates the run's `task_contract.json`
  (`validate_run_state.load_contract_for` then `validate_task_contract.validate`), refuses to clobber
  an existing `run_state.json` without `--force`, and returns the fixed exit codes (0 OK · 2
  not-a-dir · 3 no/invalid contract). Test: `tests/unit/test_workflow_state.py` (5 cases,
  TDD-first; later Phase-1 tasks 1.3/1.4/1.5 APPEND to this same file and register their subcommands).
- **Why:** the "observable before enforceable" principle needs the keystone ledger on disk before any
  gate can read a recorded signal. Phases 2/3/4 read/extend `RUN_STATE_NAME`/`SCHEMA_VERSION`/
  `GENERATOR`/`LIST_KEYS`/`_state_path`/`load_state`/`write_state`/`new_state` VERBATIM; `init` seeds
  the file so no downstream reader KeyErrors on a fresh run. Reuses the wired instruments
  (`provenance`, `validate_run_state`, `validate_task_contract`) rather than parallel-building — no
  second source of truth.
- **Where-embedded:** `DIRECTORY.md` (`_infrastructure/` block, the `workflow_state.py` row after
  `provenance.py`); `docs/workflow/README.md` (Reusable-helpers table — the per-run ledger every gate
  reads).
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_workflow_state.py" -q`
  (5 passed) and `python3 src/ravel/workflow/workflow_state.py --selftest` (exit 0).

### CR-053 — workflow_state record + active-rundir resolution (G2 substrate) (Phase 1 Task 1.3)
- **Date registered:** 2026-07-10
- **What:** Added the observer's write path to `src/ravel/workflow/workflow_state.py`: the
  `record` subcommand + `RECORD_KINDS` extension point + `find_active_rundir` + `cmd_record`. `RECORD_KINDS`
  maps a kind → `(list_key, normalizer)` with two value shapes — a **list-append** kind (str `list_key`;
  normalizer `(payload)→dict` appended to `state[list_key]` with a `utc` stamp) covering
  `skill`/`compute`/`subagent`/`edit`, and a **state-mutator** kind (`list_key is None`; normalizer
  `(state, payload, utc)` mutates `state` directly) covering `route` (sets `state["routed"]=True` + an audit
  entry in `state["routes"]`) and `failure` (de-dup-appends the `logs/<stage>.failure.json` relpath to
  `state["open_failure_records"]`) — D-3, the REAL writers that Phase-2 Tasks 2.10/2.1 invoke. `cmd_record`
  takes either `--rundir` or `--project-dir` (→ `find_active_rundir`, the newest `trial-runs/*/run_state.json`
  by mtime, else `None`), a `--kind`, and a payload via `--payload <json-object>` OR the `--what <str>`
  convenience (for the string-valued route/failure kinds). The `compute` kind carries the N6 fields
  (`cmd`/`bg_kind`/`bg_id`/`logfile`/`done_condition`/`next_action`/`supervised`) but per D-2 is written ONLY
  by the DRIVE `record --kind compute`, never by the observer (which records `skill`/`edit`/`subagent`).
  Exit codes: 0 OK · 2 usage/not-a-dir/bad-payload/missing-required-field · 3 no run_state.json; the
  `--project-dir` observer path with no active run is a deliberate exit-0 no-op (never blocks a tool). Test:
  `tests/unit/test_workflow_state.py` (+6 cases, TDD-first) and 3 new `--selftest` checks (4/5/5a/5b).
- **Why:** "observable before enforceable" — the Phase-2 phantom-bg / DRIVE / skill-coverage gates can only
  enforce a signal the observer first RECORDS to `run_state.json`. `RECORD_KINDS` is the single extension
  point later phases register new kinds against (no parallel writer); `route`/`failure` land `routed` +
  `open_failure_records` so the Phase-2 gates read them from disk rather than re-deriving; `find_active_rundir`
  lets the PostToolUse observer append without the agent threading `--rundir`.
- **Where-embedded:** `DIRECTORY.md` (`_infrastructure/` block, the `workflow_state.py` row — `record` +
  `RECORD_KINDS` list-append vs state-mutator kinds + `find_active_rundir`); consumed later by the Phase-2
  PostToolUse observer, the DRIVE `record --kind compute`, and the phantom-bg / open-failure gates.
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_workflow_state.py" -q`
  (11 passed) and `python3 src/ravel/workflow/workflow_state.py --selftest` (exit 0).

### CR-054 — workflow_state advance — live precondition gate (G3) (Phase 1 Task 1.4)
- **Date registered:** 2026-07-10
- **What:** Added the lifecycle-cursor DRIVE path to `src/ravel/workflow/workflow_state.py`: the
  `advance` subcommand (`--to <stage>` from `validate_run_state.STAGE_ORDER`, `--json`) + two helpers
  `_prev_stage(stage)` (the immediate predecessor in `STAGE_ORDER`, `None` at index 0) and
  `compute_next_required(rundir, contract)` (read-only; the FIRST required stage whose status is not
  `PASS`/`N/A`/`waived-legacy`, as a `{"kind","what","why"}` next-action hint, else `None` when the whole
  required prefix is satisfied). `cmd_advance` REUSES `validate_run_state.evaluate(rundir, contract,
  stage_limit=_prev_stage(target))` — it never re-implements the lifecycle model — collects a `blockers[]`
  list from any FAILing prefix stage or invariant, and on non-empty blockers REFUSES the transition (exit 1,
  the list printed to stderr, or as a JSON payload `{target, blockers, advanced:false}` under `--json`); on
  a clean prefix it stamps `state["current_step"]=target`, refreshes `cursor_utc`, recomputes
  `state["next_required"]` via `compute_next_required`, writes the ledger, and exits 0 (JSON payload adds
  `advanced:true` + `next_required`). Exit codes: 0 advanced · 1 refused (unmet preconditions) · 2
  not-a-dir · 3 no run_state.json / no|invalid contract. Test: `tests/unit/test_workflow_state.py`
  (+3 cases, TDD-first — first-precondition-allowed/out-of-order-refused, `--json` blockers payload,
  missing-state exit 3) and 2 new `--selftest` checks (6/7).
- **Why:** G3 — the post-hoc lifecycle JUDGE (`validate_run_state`) becomes a LIVE DRIVER: a step transition
  can no longer skip past a stage whose required predecessors have not closed. It is the fallback DRIVE
  precondition gate (the hook-driven DRIVE branch and Task 1.5's `status`/`next` read the same
  `current_step`/`next_required`). Reusing `evaluate`/`STAGE_ORDER` keeps a SINGLE source of truth for the
  stage matrix and invariants (no A1-05-style parallel checker); "fail-loud + block, not advise" — an unmet
  precondition EXITS 1, it does not WARN.
- **Where-embedded:** `DIRECTORY.md` (`_infrastructure/` block, the `workflow_state.py` row — the `advance`
  clause now spells out the G3 precondition gate, `blockers[]`, and `compute_next_required`) and
  `docs/workflow/README.md` (the `workflow_state.py` helper row — a step transition runs `advance --to <stage>`,
  the fallback DRIVE precondition gate); consumed by the Phase-2 DRIVE branch + Task 1.5 `status`/`next`.
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_workflow_state.py" -q`
  (14 passed) and `python3 src/ravel/workflow/workflow_state.py --selftest` (exit 0).

### CR-055 — workflow_state status/next/require — read-only fallback gate surface (Phase 1 Task 1.5)
- **Date registered:** 2026-07-10
- **What:** Added the three READ-ONLY query subcommands to `src/ravel/workflow/workflow_state.py`:
  `status --rundir <dir> [--json]` (prints the ledger; `--json` dumps the whole `run_state.json`),
  `next --rundir <dir> [--json]` (recomputes `next_required` fresh from the contract via the existing
  `compute_next_required`), and `require --rundir <dir> --kind skill|command|artifact|stage --what <str>`
  — the belt-and-suspenders FALLBACK gate: exit 0 iff satisfied, exit 1 iff not. `require` satisfaction is
  `skill` ∈ `skills_invoked`, `command` substring of some `compute_launched.cmd`, `artifact` a file present
  under the rundir, or `stage` = `validate_run_state.evaluate(rundir, contract, stage_limit=what)["exit"]==0`
  (the required prefix through `what` PASSes). All three are read-only (no ledger write). Exit codes: 0 OK ·
  1 require-FAIL · 2 not-a-dir · 3 no run_state.json / no|invalid contract. Test:
  `tests/unit/test_workflow_state.py` (+4 cases, TDD-first — skill gate FAIL→PASS-after-record,
  artifact+command gates, stage-prefix gate, status/next `--json` payloads) and 3 new `--selftest` checks
  (8/9/10).
- **Why:** Phase-2 hook FALLBACKS and step-doc precondition checks need a read-only surface over the ledger
  that does not mutate it. `require` is the belt-and-suspenders backstop for the skill-coverage (G2) and
  lifecycle-ordering (G3) gates: at a step boundary, when the PostToolUse hook is unavailable, the agent can
  self-verify one precondition and get a hard exit code. It REUSES `load_state`/`LIST_KEYS`/
  `compute_next_required` and `validate_run_state.load_contract_for`/`evaluate` — no parallel checker
  (avoids the A1-05 drift class); "fail-loud + block, not advise" — an unsatisfied `require` EXITS 1.
- **Where-embedded:** `DIRECTORY.md` (`_infrastructure/` block, the `workflow_state.py` row — the read-only
  query surface + the `require` fallback-gate satisfaction rules now spelled out) and
  `docs/workflow/checklists/check-ins.md` (Composing rules — the step-boundary self-check line: at a step
  boundary the agent may run `workflow_state.py require --kind skill --what <skill>` / `--kind stage --what
  <stage>` when the hook is unavailable); consumed by the Phase-2 DRIVE/skill-coverage hook fallbacks.
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_workflow_state.py" -q`
  (18 passed) and `python3 src/ravel/workflow/workflow_state.py --selftest` (exit 0).

### CR-056 — PostToolUse observer + fallback twin (G2 substrate) (Phase 1 Task 1.6)
- **Date registered:** 2026-07-10
- **What:** Added the L1 PostToolUse OBSERVER `.claude/hooks/posttooluse-observer.sh` and wired it into
  the worktree `.claude/settings.json`. The observer is best-effort and NEVER blocks (always `exit 0`):
  it parses `tool_name`/`tool_input` from the hook stdin JSON and appends a ledger entry to the active
  run's `run_state.json` via `workflow_state.py record --project-dir <dir>` (which resolves the newest
  `trial-runs/*/run_state.json` through `find_active_rundir`). Mapping (**skill|edit|subagent ONLY**):
  `Skill`→`--kind skill` (skill=`tool_input.name`), `Edit|Write|MultiEdit|NotebookEdit`→`--kind edit`
  (path=`tool_input.file_path`), `Agent|Task`→`--kind subagent` (agent_type=`tool_input.subagent_type`).
  Guards: no `workflow_state.py` under the project → `exit 0`; no emitted line → `exit 0`; the `record`
  call is `|| true`. `Bash` is in the matcher (so the hook fires) but is deliberately NOT recorded (D-2):
  a `compute_launched` entry needs the N6 liveness fields (`bg_kind`/`logfile`/`done_condition`/
  `next_action`) the observer cannot know, so those entries come only from the DRIVE `record --kind
  compute` command. The settings.json wiring is the **D-1 idempotent merge** (append the PostToolUse
  block only if absent — never a wholesale write), preserving the PreToolUse card-guard AND the SPK-1
  UserPromptSubmit/PostToolUse/Stop probe blocks. Fallback twin: `docs/workflow/checklists/check-ins.md`
  registers the SAME `record` command the agent runs by hand when the hook is unavailable
  (skill|subagent|edit — compute is always the DRIVE step-doc's job per D-2). Test:
  `tests/unit/test_posttooluse_observer.py` (3 cases, TDD-first — records skill; records edit +
  subagent but NEVER emits a compute_launched entry for Bash; never blocks when no active run).
- **Why:** "Observable before enforceable" — no gate may depend on a signal that isn't first recorded to
  `run_state.json` by the observer. This is the G2 substrate the Phase-2 skill-coverage Stop branch
  consumes: every skill/edit/subagent call becomes a durable ledger fact the moment it happens, without
  the agent passing `--rundir`. Best-effort + always-`exit 0` keeps the L1 observer from ever blocking a
  turn (blocking is the enforcement layer's job); the D-2 Bash exclusion keeps a liveness-blind entry
  from misleading the Stop DETACH/phantom-bg branches. REUSES `workflow_state.py record` +
  `find_active_rundir` — no parallel writer (avoids the A1-05 drift class).
- **Where-embedded:** `DIRECTORY.md` (`.claude/hooks/` block — a new row for `posttooluse-observer.sh`
  and the settings.json row now notes the merge-appended PostToolUse observer block) and
  `docs/workflow/checklists/check-ins.md` (Composing rules — the "Observer fallback" note: the hand-run
  `record` twin + the D-2 compute exception). Consumed by the Phase-2 skill-coverage (G2) Stop branch.
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_posttooluse_observer.py" -q`
  (3 passed).

### CR-057 — verify-provenance mode (G19) — reject backfilled artifacts (Phase 1 Task 1.7)
- **Date registered:** 2026-07-10
- **What:** Added the `--verify-provenance` mode to `validate_run_state.py`: it imports `provenance.py`
  and walks a new `PROVENANCE_TARGETS` registry `((artifact_relpath, generated_by tool_id,
  inputs-resolver), …)` — seeded with `("run_state.json", "workflow_state.py",
  _prov_inputs_task_contract)`. For each PRESENT target it recomputes `provenance.verify_pair(doc,
  tool_id, resolver(rundir, contract))` and rejects (exit 1) any artifact whose `generated_by` is
  absent/hand-written or whose `input_fingerprint` no longer recomputes over its declared inputs
  (the run's `inputs/task_contract.json`). An ABSENT target is N/A, not a FAIL — provenance only judges
  artifacts that exist. `verify_provenance(rundir, contract) -> {"checks", "verdict", "exit"}`; the CLI
  prints one `[STATUS] artifact: detail` line per check (or `--json`) and returns exit 0 (all
  present-match) / 1 (any present-but-backfilled). The `--selftest`'s `5 + 2` fixture literal is
  UNTOUCHED (provenance is a separate mode, not a new embedded selftest case). Test:
  `tests/unit/test_verify_provenance.py` (5 cases, TDD-first: genuine `workflow_state.py init`
  run_state passes; absent run_state is N/A not FAIL; a run_state with `generated_by` deleted is
  rejected; a task_contract edited after the fingerprint was taken drifts and is rejected; the existing
  `--selftest` still passes).
- **Why:** "Provenance, not presence" — a required artifact must PROVE its tool produced it, closing the
  backfill loophole (a hand-written/backfilled `run_state.json` must not satisfy a gate). This is G19's
  enforcement + its seedable trigger: Phase 5's `spine_sim` can hand-write a `run_state.json` and assert
  the gate fires (exit 1). `PROVENANCE_TARGETS` is the extension point — later phases APPEND their
  lifecycle-required emitters. REUSES `provenance.py` as the single fingerprint source (D-7) and
  `find_first_existing`/`load_contract_for` — no parallel checker (avoids the A1-05 drift class).
  Domain-specific emitters (e.g. `sr_plausibility.py`, Phase 4a) that own a SEPARATE `input_fingerprint`
  over a different canonicalization are deliberately NOT registered here (D-7).
- **Where-embedded:** `DIRECTORY.md` (`validate_run_state.py` row now notes the `--verify-provenance`
  mode + the `PROVENANCE_TARGETS` registry) and `docs/workflow/steps/09-verify.md` (Tier A now runs
  `validate_run_state.py --rundir <rundir> --verify-provenance` alongside the lifecycle gate and
  `verify_pack.py`).
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_verify_provenance.py" -q`
  (5 passed).

### CR-058 — stage_supervisor.py — the CATCH watchdog wrapping run_stage (G6/D6) (Phase 2 Task 2.1)
- **Date registered:** 2026-07-10
- **What:** Added `src/ravel/workflow/stage_supervisor.py`, the per-stage CATCH watchdog, and
  wired it into `run-pipeline-native.sh:run_stage`. `timeout` is absent on this macOS host, so this
  stdlib-only python subprocess supervisor replaces the inner `( "$@" )` of `run_stage`: it launches the
  stage command, then polls three signals against per-stage kill thresholds DERIVED from `cost_preflight`
  (`stage_budget_min`: MadGraph budget is linear in events — `(NATIVE_PT_MIN_HI−NATIVE_FLAT_MIN)×events/
  NATIVE_REF_EVENTS` — every other stage sits at the 12-min `NATIVE_FLAT_MIN` flat) — (1) wall-clock past
  `KILL_MARGIN`×budget (5-min `FLOOR_SECS` floor protects legitimately fast stages), (2) progress-stall
  (no log write for a whole budget after the floor), (3) exit-0-implausibility (a MUST_PRODUCE stage that
  returns 0 with an empty log). On a hang it SIGTERM→(grace)→SIGKILLs the process, writes
  `logs/<stage>.failure.json` (`schema_version`/`generated_by`/`generator`/`generated_utc`/
  `input_fingerprint`/`stage`/`status:"open"`/`reason`/`elapsed_s`/`kill_threshold_s`/`logfile`/
  `next_action`) and — RECONCILE D-3 — records the open failure to the run ledger
  (`workflow_state.py record --kind failure --rundir <d> --what <relpath>`, best-effort so a ledger
  hiccup never masks the stage failure) so it lands in `run_state.open_failure_records[]` and the Task 2.5
  Stop CATCH branch + its `workflow_state.py status` fallback see it. It returns nonzero (124 killed-hang
  / 3 exit-0-implausible) so the EXISTING `stage_done` writes the FAIL/STOPPED STATUS.txt line unchanged →
  the bg job completes → the harness completion-notification fires. The wrap is backward-compatible:
  `STAGE_SUPERVISED=0` or a missing supervisor/python3 falls back to the raw `( "$@" ) > logs/<name>.log`
  subshell, so the STATUS.txt contract is identical either way. Test:
  `tests/unit/test_stage_supervisor.py` (TDD-first — the `--selftest` passes as a subprocess;
  `stage_budget_min` matches the cost_preflight-derived budgets at 20k and 40k events). `--selftest`
  itself exercises 3 cases: a wall-clock kill (rc 124 + a `status:"open"` failure.json), a clean stage
  (rc 0, no spurious failure.json), and an empty-log exit-0-implausible producing stage (rc 3 + failure.json).
- **Why:** D6 CATCH — a stage that wedges (infinite loop, deadlock, silent exit-0 with no output) must
  not silently hold a scan slot forever; there is no `timeout` here to lean on. Fail-loud + block: the
  watchdog surfaces the hang as a FAILED point with a durable, provenanced failure record and a
  `next_action`, rather than an advisory WARN. "Observable before enforceable": the failure is recorded to
  `run_state.json` (D-3) so the enforcement layer (Stop CATCH) can act on it. REUSES `cost_preflight`'s
  measured budget model (no parallel timing table — the A1-05 drift class) and `workflow_state.py record`
  (no parallel ledger writer).
- **Where-embedded:** `.claude/skills/run-stage/SKILL.md` (Native section — the native chain now
  self-catches hangs; `STAGE_SUPERVISED=0` disables; a recovered point is reset by removing
  `logs/STATUS.txt`), `docs/workflow/steps/08-scan.md` (the stage-hang CATCH note — the supervisor records the
  failure to `run_state.open_failure_records` via `workflow_state.py record --kind failure` so the Stop
  CATCH branch + its `status` fallback see it, D-3; `scan_babysitter.py`'s HEAL loop is the no-supervisor
  backstop), and `DIRECTORY.md` (`_infrastructure/` `stage_supervisor.py` entry, track: software).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/stage_supervisor.py --selftest` (PASS, 3 cases); and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stage_supervisor.py" -q`
  (2 passed).

### CR-059 — scan_babysitter.py live-hung upgrade — short-tag / fractional-dm liveness (Phase 2 Task 2.2)
- **Date registered:** 2026-07-10
- **What:** Fixed the babysitter's HEAL-loop liveness guard, which had an always-true conjunct
  (SHARED-CONVENTIONS J). `live_points()` now (a) matches a **fractional** Δm (`m[\dp]+_dm[\dp]+`, so a
  decimal tag like `m150_dm2p5` is caught — the old `_m\d+_dm\d+` regex rejected the `p`) and (b) returns
  BOTH the full run-token tag AND the **short manifest tag** (`m<..>_dm<..>`), so a membership test against
  the manifest's `mp['tag']` is meaningful; it also grew a `ps_output=` test seam. The stale-heal condition
  moved into a named helper `stall_heal_due(mtime, tag, live, now, stale_min)` =
  `(tag not in live) and ((now-mtime) > stale_min*60)`, and `cycle`'s running-branch now calls it. Added a
  `_selftest()` (5 checks) intercepted in `__main__`. Previously `live_points()` yielded only the full tag,
  so `tag not in live` was ALWAYS true and the STATUS-mtime alone decided a stale-heal — a genuinely-live
  30–50 min MadGraph stage (STATUS.txt mtime frozen while it works) could be reset out from under itself.
  Test: `tests/unit/test_scan_babysitter_livehung.py` (TDD-first — fractional-dm short+full detection;
  the guard protects a live and a fresh point, heals a dead+stale one).
- **Why:** SHARED-CONVENTIONS J — a liveness guard whose membership test can never match is not a guard.
  The pipeline stage times (30–50 min/point native) mean a working point routinely holds a frozen STATUS
  mtime well past `--stale-min`; without a real liveness check the babysitter would race the supervisor to
  reset a live point, wasting the in-flight compute. Fail-loud correctness with no new dependency
  (stdlib-only `re`), extending the existing tool rather than parallel-building.
- **Where-embedded:** `docs/workflow/steps/08-scan.md` (the stage-hang CATCH backstop note — the HEAL loop's
  liveness guard is now real: a live MadGraph stage is protected from a false stale-heal, a died-mid-stage
  point is still reset). No new file (the `_infrastructure/scan_babysitter.py` DIRECTORY.md row already
  exists).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/scan_babysitter.py --selftest` (PASS, 5 checks); and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_scan_babysitter_livehung.py" -q`
  (2 passed).

### CR-060 — progress_reporter.py + the ~30-min ScheduleWakeup mandate (Phase 2 Task 2.3)
- **Date registered:** 2026-07-10
- **What:** New read-only tool `src/ravel/workflow/progress_reporter.py` — emits ONE progress
  line for a running scan or single point (G7). Given `--rundir <dir>` it reads `scan_manifest.json` and
  classifies each point's `run_dir` (`output/exclusion.json` = **done**, `logs/*.failure.json` = **failed**,
  `logs/STATUS.txt` last line = **running**/**pending**), or, when there is no manifest, reports the single
  run's own `logs/STATUS.txt`. Output is one stdout line
  (`[progress] <run> done=k/N running=… failed=… pending=… free=…GB [last='…']`); `--json` gives the
  machine form; `--selftest` runs a built-in check. stdlib-only, read-only, and it **never gates** —
  exit 0 always (a report is not a gate), exit 2 only on a usage error / not-a-directory. Paired with a
  workflow MANDATE: any compute expected to exceed ~30 min schedules a `ScheduleWakeup` every ~30 min
  running the reporter, so a long run **self-reports** WITHOUT a physicist nudge.
  Test: `tests/unit/test_progress_reporter.py` (TDD-first — the `--selftest` exit-0 case + a
  scan `done=1/1` count from a synthetic manifest).
- **Why:** G7 / the abandoned-anti-idle-primitive — a long scan or native point (30–50 min/point) would
  otherwise sit silent between check-ins, and the earlier ScheduleWakeup self-report habit was dropped.
  This gives the run a cheap, dependency-free, non-gating way to surface progress on a timer. It is the
  **non-hook FALLBACK** for the G7 reporter (a hook cannot wake a sleeping session; a scheduled wake can).
- **Where-embedded:** `docs/workflow/steps/08-scan.md` ("Long-compute self-report (G7)" paragraph, beside the
  stage-hang CATCH backstop) and `.claude/skills/run-scan/SKILL.md` (checkpoint section, "Self-report
  every ~30 min" mandate). `DIRECTORY.md` row added for `progress_reporter.py` (track: software).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/progress_reporter.py --selftest` (PASS, 1 case); and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_progress_reporter.py" -q`
  (2 passed).

### CR-061 — stop_dispatch.py + the D18 umbrella branch + the Stop-hook shim (Phase 2 Task 2.4)
- **Date registered:** 2026-07-10
- **What:** New Stop-hook dispatcher `src/ravel/workflow/stop_dispatch.py` — the one Stop-hook
  brain that resolves the active rundir (the `run_state.json` whose `session_id` matches the Stop JSON,
  else the newest under `trial-runs/*/`), reads the last assistant message from the transcript, and
  evaluates a priority-ordered list of BLOCK branches, exiting **2** (blocking turn-end, stderr = the
  reason fed back to the agent) on the first BLOCK, else **0**. First branch is the **D18 umbrella**
  (`branch_d18`): on a CHECK-IN/RESULT **delivery** turn (matched by `DELIVERY_RE`) it shells out to
  `validate_run_state.py --rundir` and BLOCKS when that gate does not exit 0 — so a lifecycle-broken run
  cannot post a check-in. Reuses the existing lifecycle gate rather than re-deriving it (no second source
  of truth). Companion shim `.claude/hooks/stop-dispatcher.sh` just pipes the Stop JSON on stdin to the
  dispatcher. Deliberate, documented **hook exit mapping**: `2 = BLOCK`, `0 = allow OR fail-open` (a
  dispatcher/validator crash, an unresolvable rundir, or a non-delivery turn never blocks the live agent —
  the step-doc FALLBACK covers it). stdlib-only, read-only. `--selftest` = the D18 block/pass pair.
  CLI overrides (`--rundir --session --transcript --last-message --branch --repo`) exist for the tests.
  Test: `tests/unit/test_stop_dispatch.py` (TDD-first — `--selftest` exit 0, D18 blocks a delivery
  turn on an invalid rundir with `D18` in stderr + exit 2, D18 passes a non-delivery turn with exit 0).
- **Why:** G-tier verification-lifecycle enforcement (D18) — the earlier gates were advisory prose the
  agent could skip on a delivery turn; wiring the lifecycle gate into the Stop hook makes it BLOCK, not
  advise, exactly when a check-in/RESULT is about to go to the physicist. The dispatcher is the extensible
  home (BRANCHES table) for the remaining Phase-2 Stop branches.
- **Where-embedded:** `docs/workflow/steps/09-verify.md` (the "D18 umbrella (Stop dispatcher)" paragraph beside
  the scripted Tier-A gates, naming the `python3 src/ravel/validation/validate_run_state.py --rundir
  <rundir>` FALLBACK the agent runs before posting when the hook is unavailable). `DIRECTORY.md` rows added
  for `stop_dispatch.py` and `.claude/hooks/stop-dispatcher.sh` (track: software).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/stop_dispatch.py --selftest` (PASS) and
  `bash -n .claude/hooks/stop-dispatcher.sh`; and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stop_dispatch.py" -q`
  (3 passed).

### CR-062 — stop_dispatch.py CATCH/D6 branch — BLOCK turn-end on unhandled failure records (Phase 2 Task 2.5)
- **Date registered:** 2026-07-10
- **What:** Second Stop-hook branch `branch_catch` in `src/ravel/workflow/stop_dispatch.py`
  (registered in `BRANCHES` immediately after `d18`). At turn-end it walks the active rundir and BLOCKS
  (exit **2**, stderr = the CATCH/D6 reason fed back to the agent) if any `logs/*.failure.json` record
  carries a `status` outside `{resolved,handled,closed}` and no truthy `handled` — the on-disk failure
  records written by `stage_supervisor.py` (Task 2.1) are authoritative for the hook. So an unresolved
  stage failure cannot be silently ended-over: the agent must resolve each (diagnose+fix or reset the
  point) and set its `"status":"resolved"` before the turn can close. Non-hook FALLBACK =
  `workflow_state.py status`, which lists the same records under `open_failure_records[]` (populated by
  `stage_supervisor.py`'s `record --kind failure`, D-3). stdlib-only, read-only. `--selftest` gains a
  `_selftest_catch` block/pass pair alongside the D18 pair.
  Test: `tests/unit/test_stop_dispatch_catch.py` (TDD-first — CATCH blocks a rundir with an `open`
  `*.failure.json` with `CATCH` in stderr + exit 2; passes a rundir whose only record is `resolved`).
- **Why:** G6/D6 CATCH enforcement — Task 2.1's supervisor already observes and records a hung/failed
  stage, but observation is advisory until a gate blocks on it. This branch turns the recorded open
  failure into a hard turn-end BLOCK (fail-loud + block, not advise), closing the "end the turn and
  move on" loophole. Extends the existing dispatcher rather than adding a second Stop hook (one brain,
  many branches).
- **Where-embedded:** `docs/workflow/steps/08-scan.md` (the "Stage-hang CATCH (G6/D6)" paragraph now
  documents the `branch_catch` behaviour — the `logs/*.failure.json` status test, the exit-2 BLOCK, and
  the `workflow_state.py status` → `open_failure_records[]` FALLBACK — and the resolve-then-set-
  `"status":"resolved"` clearing procedure).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/stop_dispatch.py --selftest` (PASS) and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stop_dispatch_catch.py" -q`
  (2 passed).

### CR-063 — stop_dispatch.py phantom-background branch — BLOCK a turn that claims a job it never launched (Phase 2 Task 2.6)
- **Date registered:** 2026-07-10
- **What:** Third Stop-hook branch `branch_phantom` in `src/ravel/workflow/stop_dispatch.py`
  (registered in `BRANCHES` immediately after `catch`) plus its shared liveness helper `_bg_liveness`.
  At turn-end it BLOCKS (exit **2**, stderr = the PHANTOM/D5-signature reason fed back to the agent)
  when the last assistant message CLAIMS a background job is running (`RUNNING_RE` — "running in the
  background", "kicked off", "backgrounded", "now running", "still running", "monitoring the
  run/job/scan", "will ping/notify … done", …) **and** no live job is found: no
  `run_state.compute_launched[].logfile` whose mtime is within `PHANTOM_WINDOW_SECS=180` s, **and** no
  matching pipeline process (`_PIPE_PROCS`) naming this rundir in `ps`. The logfile-mtime is the robust
  signal (the DRIVE `workflow_state.py record --kind compute` command writes `logfile` onto the entry,
  per RECONCILE D-2 — the observer does not); `ps` is a best-effort backstop for un-recorded jobs.
  stdlib-only, read-only. `--selftest` gains a `_selftest_phantom` block/pass pair alongside the D18 and
  CATCH pairs.
  Test: `tests/unit/test_stop_dispatch_phantom.py` (TDD-first — a claim with no `compute_launched`
  BLOCKS with `PHANTOM` in stderr + exit 2; a claim with a fresh `logfile` mtime passes; a turn with no
  running-claim passes).
- **Why:** G5/D5 phantom-background enforcement — the D5 signature is a turn that ends by *announcing* a
  background job that was never launched (so nothing ever finishes and no watchdog ever fires). Message
  intent alone can't be trusted; this branch cross-checks the claim against an on-disk/`ps` liveness
  signal and turns a false claim into a hard turn-end BLOCK (fail-loud + block, not advise). Extends the
  existing dispatcher rather than adding a second Stop hook (one brain, many branches).
- **Where-embedded:** `docs/workflow/steps/08-scan.md` (new "Phantom-background BLOCK (G5/D5)" paragraph
  documents the `branch_phantom` behaviour — the `RUNNING_RE` claim trigger, the logfile-mtime +
  `ps` liveness test, the exit-2 BLOCK — and the "confirm via `workflow_state.py status` / a live
  logfile before claiming a job is running" FALLBACK + clearing procedure).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/stop_dispatch.py --selftest` (PASS) and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stop_dispatch_phantom.py" -q`
  (3 passed).

### CR-064 — stop_dispatch.py DRIVE/D4 branch — BLOCK a turn that narrates its next step instead of executing it (Phase 2 Task 2.7)
- **Date registered:** 2026-07-10
- **What:** Fourth Stop-hook branch `branch_drive` in `src/ravel/workflow/stop_dispatch.py`
  (registered in `BRANCHES` immediately after `phantom`). At turn-end it **BLOCKS** (exit **2**,
  stderr = the DRIVE/D4 reason fed back to the agent) when `run_state.next_required` is pending **and**
  the turn is not a CHECK-IN/RESULT delivery/human-gate turn (`ctx["is_delivery"]` = `DELIVERY_RE`)
  **and** no live/recent background job exists — reusing the Task 2.6 `_bg_liveness` helper with a
  wider `DRIVE_RECENT_SECS=600` s window (no `compute_launched[].logfile` whose mtime is within 600 s,
  and no matching pipeline process in `ps`). A launched-and-pending compute manifests structurally as a
  live/recent bg job, a cleared `next_required`, or a failure record caught earlier (CATCH), so "this
  turn launched no compute" is captured by those conjuncts. The reason names the pending
  `next_required.what` (+ `why`) and instructs: execute the next step NOW (`run_in_background` for long
  jobs) instead of narrating it. stdlib-only, read-only. `--selftest` gains a `_selftest_drive`
  block/pass/delivery triple alongside the D18/CATCH/PHANTOM pairs.
  Test: `tests/unit/test_stop_dispatch_drive.py` (TDD-first — a pending `next_required` on a
  non-delivery turn with no compute BLOCKS with `DRIVE` in stderr + exit 2; a recent `compute_launched`
  logfile passes; a delivery turn passes; a rundir with no `next_required` passes).
- **Why:** G-tier DRIVE enforcement (D4) — the D4 signature is a turn that ends by *describing* the next
  action ("Next I'll generate the events.") without launching it, so the run stalls waiting on a
  physicist nudge. Message intent + narration alone can't self-drive; this branch cross-checks the
  pending ledger action against a live/recent-compute signal and turns a narrate-and-stop into a hard
  turn-end BLOCK (fail-loud + block, not advise). Extends the existing dispatcher rather than adding a
  second Stop hook (one brain, many branches).
- **Where-embedded:** `docs/workflow/steps/03-generate.md` (new "Self-drive at step end (DRIVE/D4)"
  paragraph documents the `branch_drive` behaviour — the `workflow_state.py next` pending-action check,
  the `DRIVE_RECENT_SECS=600` liveness window, the exit-2 BLOCK, the delivery-turn exemption, and the
  `workflow_state.py next` non-hook FALLBACK) and `docs/workflow/README.md` (the `workflow_state.py` helper
  row now names `next` as the step-end self-drive check and ties it to the DRIVE/D4 Stop branch).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/stop_dispatch.py --selftest` (PASS) and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stop_dispatch_drive.py" -q`
  (4 passed).

### CR-065 — stop_dispatch.py SKILL-COVERAGE/G2 branch — BLOCK a turn-end whose step skipped its governing skill (Phase 2 Task 2.8)
- **Date registered:** 2026-07-10
- **What:** Fifth Stop-hook branch `branch_skill_coverage` in
  `src/ravel/workflow/stop_dispatch.py` (registered in `BRANCHES` immediately after `drive`).
  The `REQUIRED_SKILL_FOR_STEP` map ties governing skills to the **STAGE_ORDER stage names that
  `workflow_state.py advance` actually writes into `run_state.current_step`** — `route`→
  `route-analysis`, `analysis`→`certify`, `verification`→`verification-panel` — by exact match. Because
  `scan` is a **task_mode**, not a STAGE_ORDER stage, its `run-scan` requirement is driven off
  `run_state.task_mode == "scan"` at the `statistics` stage (the step-8 outer loop that produces the
  exclusion contour). At turn-end the branch reads `current_step`; if the stage maps to a required
  skill and `run_state.skills_invoked` carries no matching `{"skill": …}` entry, it **BLOCKS** (exit
  **2**, stderr = the SKILL-COVERAGE/G2 reason fed back to the agent, naming the stage + the missing
  skill). A stage with no required skill, or one whose skill is present in the ledger, passes.
  stdlib-only, read-only. `--selftest` gains a `_selftest_skill` block/pass pair plus the task_mode
  scan block/pass pair alongside the D18/CATCH/PHANTOM/DRIVE cases. Test:
  `tests/unit/test_stop_dispatch_skill.py` (TDD-first, 8 cases on production-shaped
  `current_step` values — a stage mapped to a required skill absent from `skills_invoked` BLOCKS with
  `SKILL-COVERAGE` in stderr + exit 2; the skill present passes; a stage with no required skill
  passes; scan-mode at `statistics` requires `run-scan`; non-scan `statistics` has no requirement).
  **Fix (2026-07-10, review of Task 2.8):** the initial map was keyed on step-doc ids
  (`02-route`/`05-analysis`/`08-scan`/`09-verify`) tested by substring — a dead branch, because
  production never emits those; `advance` writes bare stage names (`route`/`analysis`/`verification`;
  there is no `scan` stage). Re-keyed to the stage names + task_mode-driven scan, exact-match; tests
  and `_selftest_skill` updated to production-shaped values so the green suite exercises the real path.
- **Why:** G-tier skill-coverage enforcement (G2) — governing skills are mandatory
  (route-analysis routes, certify certifies acc×eff, run-scan drives the grid, verification-panel is
  the pre-delivery panel), yet a turn can advance the cursor past one of them without ever invoking
  it. Presence of the ledger cursor without the skill is the coverage gap; this branch turns
  advancing-without-the-skill into a hard turn-end BLOCK (fail-loud + block, not advise). Extends the
  existing dispatcher rather than adding a second Stop hook (one brain, many branches).
- **Where-embedded:** `docs/workflow/README.md` (the "Required skill per stage (SKILL-COVERAGE/G2)"
  paragraph after the step table documents the `route`/`analysis`/`verification` stage→skill bindings,
  the task_mode-driven `scan`→`run-scan` requirement at the `statistics` stage, the exit-2 BLOCK, and
  the non-hook FALLBACK `workflow_state.py require --kind skill --what <skill>`).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/stop_dispatch.py --selftest` (PASS) and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stop_dispatch_skill.py" -q`
  (8 passed).

### CR-066 — stop_dispatch.py DETACH/N6 branch — BLOCK turn-end on a self-detached job without a durable ledger+heartbeat (Phase 2 Task 2.9)
- **Date registered:** 2026-07-10
- **What:** Sixth Stop-hook branch `branch_detach` in `src/ravel/workflow/stop_dispatch.py`.
  It walks `run_state.compute_launched[]` and inspects only the entries with `bg_kind=="detached"` (a
  job the agent self-detached via `nohup`/`start_new_session`, outside the harness's `run_in_background`
  tracking). Such an entry is admissible ONLY if it carries all three of `logfile`+`done_condition`+
  `next_action` AND has a **live heartbeat** — its `logfile` mtime within the new
  `DETACH_HEARTBEAT_SECS=600` s window (absolute path used as-is, else resolved against `rundir`; an
  `OSError`/missing file counts as no heartbeat). Any detached entry missing a required field or a live
  heartbeat makes the branch **BLOCK** (exit **2**, stderr = the DETACH/N6 reason naming the offending
  job(s) and instructing: use harness-tracked `run_in_background`, or record
  logfile+done_condition+next_action AND keep a live heartbeat). Harness-tracked entries
  (`bg_kind!="detached"`) are ignored entirely. stdlib-only, read-only. `--selftest` gains a
  `_selftest_detach` block/pass pair alongside the D18/CATCH/PHANTOM/DRIVE/SKILL cases. Test:
  `tests/unit/test_stop_dispatch_detach.py` (TDD-first, 3 cases via `--branch detach` — an
  incomplete detached entry with no heartbeat BLOCKS with `DETACH` in stderr + exit 2; a complete entry
  with a fresh logfile passes; a `bg_kind=="harness"` entry passes).
  **BRANCHES priority finalized (this task):** the dispatch list is now
  `d18 · catch · detach · phantom · skill-coverage · drive` — delivery(D18)/CATCH/DETACH decide before
  phantom/skill-coverage, and DRIVE is last (it is the residual "you narrated instead of executing"
  catch, so the more specific gates speak first). Per-branch `--branch` tests are order-independent, so
  only the unfiltered production dispatch is affected. `BRANCHES` is a deliberate append-point
  (RECONCILE D-4): Phase 4b appends its predicate-CLI branches after `drive`, keeping this Phase-2
  prefix order intact; every Phase-2 branch shells only Phase-1/2 instruments, so `--selftest` and the
  per-branch tests pass before any Phase-4b tool lands.
- **Why:** N6 enforcement — a self-detached long job (`nohup`/`start_new_session`) leaves the harness
  and this run blind to whether it is alive, done, or dead; the turn can end believing compute is
  progressing when nothing is (a phantom-adjacent failure the PHANTOM branch's message-intent trigger
  does not catch, because a DETACH turn need not *narrate* the launch). Requiring a durable
  `compute_launched` record (logfile+done_condition+next_action) plus a live heartbeat makes a detached
  job observable-and-resumable before it is admissible, and turns a blind detach into a hard turn-end
  BLOCK (fail-loud + block, not advise; observable-before-enforceable). Extends the existing dispatcher
  rather than adding a second Stop hook (one brain, many branches).
- **Where-embedded:** `docs/workflow/steps/03-generate.md` (new "Detached background jobs (DETACH/N6)"
  paragraph documents the `run_in_background`-not-`nohup` rule, the required
  logfile+done_condition+next_action fields, the `DETACH_HEARTBEAT_SECS=600` heartbeat, the exit-2
  BLOCK, and the `workflow_state.py status` non-hook FALLBACK) and `.claude/skills/run-stage/SKILL.md`
  (the long-jobs-in-background note now carries the same DETACH/N6 rule; mirrored to
  `.agents/skills/run-stage/SKILL.md` by `sync_skills.py`).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/stop_dispatch.py --selftest` (PASS) and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stop_dispatch_detach.py" -q`
  (3 passed).

### CR-067 — userpromptsubmit-router.sh — the G1 UserPromptSubmit route/injection hook (Phase 2 Task 2.10)
- **Date registered:** 2026-07-10
- **What:** New `.claude/hooks/userpromptsubmit-router.sh` — the L3+L4 (DRIVE/CATCH phase) prompt
  router. On a physics-looking prompt (a conservative case-insensitive keyword pre-gate:
  `initiate:|reproduc|reinterpret|exclud|arxiv|atlas|cms|figure [0-9]|mass.?plane|scan|limit on|
  summary.?plot|is .* excluded|sensitiv` — never nags a dev/ops prompt) it runs the deterministic
  `src/ravel/workflow/route_prompt.py --prompt "$prompt" --print` (`2>&1` so the
  `ROUTED: task_mode=…` stderr line is captured too), extracts `task_mode` via a python regex, and for
  a routable mode (`reproduce|reinterpret|scan|summary_plot|projection|anomaly_search|survey|
  no_routine|unsupported`) prints exactly one stdout JSON payload
  `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"<INITIATE reminder>"}}`
  and exits 0. The reminder points the executing agent at `docs/workflow/start.md` → the `physicist-intake`
  skill and states the no-heavy-compute-before-CHECK-IN-1 rule. Non-blocking by design (always exit 0;
  the hard blocks live in the PreToolUse Skill guard G22 + the Phase-4 pre-generate guard). Empty prompt
  or non-physics prompt → silent exit 0. **Side effect (RECONCILE D-3):** on a routable mode it records
  `workflow_state.py record --kind route --project-dir "$REPO"` (best-effort `>/dev/null 2>&1 || true`,
  so the ledger write never lands on stdout and never fails the hook) — this is the `route` state-mutator
  kind that sets `run_state.routed`; `cmd_record` resolves the active rundir via `find_active_rundir`, so
  a fresh prompt with no active run self-scopes to a harmless no-op, and it never clobbers an unrelated
  run. `physicist-intake` re-asserts `routed` once the run scaffold exists. p1's `record` CLI has NO
  `--session` flag → `--project-dir` is passed (D-3 / RR4). stdlib-only (bash + inline python3),
  read-only except the best-effort ledger write. Test: `tests/unit/test_userpromptsubmit_router.py`
  (TDD-first, 3 cases: `bash -n` syntax, reminder injected on a physics prompt, silent on a dev prompt).
- **Why:** G1 — the workspace router (parent-dir CLAUDE.md) closes the turn-1 routing gap for a
  physicist session, but a session launched INSIDE the repo still relies on the agent reading
  INITIATE.md unprompted (Catalogue D3: 5/5 fresh physicist sessions failed to route before an explicit
  reminder existed). This hook makes the route deterministic and observable: every physics prompt gets
  the INITIATE reminder injected as context AND marks the run `routed` in the ledger so the downstream
  lifecycle gate (`validate_run_state.py`) can see routing happened. Non-blocking keeps it fail-open (a
  route mis-classification never wedges a live agent); the hard blocks stay with the Skill/pre-generate
  guards (fail-loud where it matters, advise where a false positive would be costly). Observable-before-
  enforceable: the `route` record is the signal a later gate consumes.
- **Where-embedded:** `docs/workflow/start.md` (new blockquote under "AGENT EXECUTING THIS REQUEST —
  your procedure" documents the auto-injected G1 reminder + the `--kind route` ledger write + that THIS
  procedure is the FALLBACK when the hook does not fire) and `DIRECTORY.md` (new `.claude/hooks/
  userpromptsubmit-router.sh` software row).
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_userpromptsubmit_router.py" -q` (3 passed).

### CR-068 — pretooluse-skill.sh — the G22/N1 PreToolUse-on-Skill precedence guard, session-scoped contract check (Phase 2 Task 2.11)
- **Date registered:** 2026-07-10
- **What:** New `.claude/hooks/pretooluse-skill.sh` — the L3+L4 (DRIVE/CATCH phase) skill-precedence
  HARD guard. On a `PreToolUse` for a `Skill` tool it reads the hook JSON on stdin, extracts
  `tool_input.skill` (falls back to `tool_input.name`), and if that skill is in the
  contract-presupposing set (`new-analysis|run-scan|run-stage|certify|route-analysis|verification-panel`)
  it BLOCKS (exit 2, stderr reason fed back to the agent) UNLESS the ACTIVE run already carries a
  `task_contract.json` (at its root or `inputs/`). `physicist-intake` and every other skill pass
  (exit 0). **The active run is resolved SESSION-SCOPED, not by a repo-wide glob (RECONCILE / R8
  critical):** first from the tool-call `cwd` when it sits inside a `trial-runs/<rundir>` tree, else
  from `session_id` via the `trial-runs/*/run_state.json` whose `session_id` matches; that run's
  contract is what is checked. If no active run is resolvable at all → BLOCK (conservative default:
  a physics session must run `physicist-intake` first). A repo-wide glob would be WRONG — a mature
  repo carries many old `trial-runs/*/inputs/task_contract.json`, which would make the guard
  permanently pass and G22 dead. Empty/absent skill → exit 0. stdlib-only (bash + inline python3),
  read-only. Test: `tests/unit/test_pretooluse_skill.py` (TDD-first, 7 cases: `bash -n` syntax,
  the R8-critical mature-repo block, the no-resolvable-run conservative block, `physicist-intake`
  allowed, gated-skill-with-contract-in-active-run allowed via cwd, gated-skill allowed when the run
  is resolved by `session_id`, ungated skill ignored).
- **Why:** G1's `UserPromptSubmit` router (CR-067) only INJECTS an advisory reminder; a fresh
  physicist session can still invoke a heavy contract-presupposing skill before `physicist-intake`
  has routed the request, run the survey, and composed CHECK-IN 1 (Catalogue D3: fresh sessions
  improvise a route / spend budget before the plan is approved). This is the fail-loud counterpart —
  it HARD-BLOCKS those skills until the contract exists, so intake-first is enforced, not merely
  advised. The session/cwd scoping is the R8-critical correctness point: the earlier naive design
  (a repo-wide contract glob) silently dies in a mature repo full of old contracts; scoping to the
  active run keeps the guard live for every fresh run.
- **Where-embedded:** `.claude/skills/physicist-intake/SKILL.md` (new "Enforced (G22/N1)" blockquote —
  mirrored to `.agents/skills/` via `sync_skills.py`) and `docs/workflow/start.md` (new PreToolUse Skill
  guard blockquote under "AGENT EXECUTING THIS REQUEST — your procedure"), both documenting the hard
  block + that the contract check is **session/cwd-scoped to the active run** (not a repo-wide glob) so
  it fires even in a mature repo full of old contracts; FALLBACK = the INITIATE routing rule. New
  `.claude/hooks/pretooluse-skill.sh` software row in `DIRECTORY.md`. **Cross-file note for Phase 5
  (G22 spine_sim, p5):** the case must drive this hook against an isolated fixture whose ACTIVE run
  (matched by the fixture `cwd`/`session_id`) has no `task_contract.json` — a repo-wide contract no
  longer satisfies the guard, so the case isolates cleanly.
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_pretooluse_skill.py" -q` (7 passed).

### CR-069 — worktree `.claude/settings.json` wires the full hook spine via the D-1 idempotent merge (Phase 2 Task 2.12)
- **Date registered:** 2026-07-10
- **What:** The worktree `.claude/settings.json` now wires the complete workflow-adherence hook spine.
  Applied via the RECONCILE **D-1 idempotent merge** (a small `json.load`→append→`json.dump` pass,
  NEVER a wholesale `Write`): the merge APPENDS ONLY three blocks — PreToolUse·`Skill` →
  `pretooluse-skill.sh` (G22/N1), UserPromptSubmit·`""` → `userpromptsubmit-router.sh` (G1,
  timeout 20), Stop·`""` → `stop-dispatcher.sh` (timeout 150, → `stop_dispatch.py`'s
  D18/CATCH/PHANTOM/DRIVE/SKILL-COVERAGE/DETACH branches). It leaves the pre-existing PreToolUse
  card-guard block, the SPK-1 (G0a) probe blocks, and the Phase-1 PostToolUse **observer** block —
  including the observer's full `Bash|Edit|Write|MultiEdit|NotebookEdit|Skill|Agent|Task` matcher —
  byte-for-byte intact, and de-dupes by exact `command` so re-running the merge is a no-op (no
  duplicate blocks). Test (TDD-first): `tests/unit/test_settings_wiring.py` (3 cases: valid
  JSON + all five hooks wired; observer matcher NOT re-narrowed + each of stop-dispatcher /
  userpromptsubmit-router / pretooluse-skill / protect-original-cards appears exactly once;
  `bash -n` on all four scripts).
- **Why:** Phase 2 built the four hook scripts + the Stop-dispatcher brain, but a script that is not
  wired into `settings.json` never fires. This is the L3+L4 mechanization step that makes the belt
  live for the isolated self-drive, while the append-only D-1 merge protects the concurrently
  running trial's guarantees — the card-guard and the observer's full matcher are never disturbed.
- **Where-embedded:** `docs/workflow/README.md` gains a "Mechanized enforcement (hooks)" section listing
  every hook, the gate it mechanizes, and its non-hook FALLBACK command (card-guard, PreToolUse-Skill
  G22, PostToolUse observer, UserPromptSubmit router G1, and the Stop dispatcher's
  D18/CATCH/PHANTOM/DRIVE/SKILL-COVERAGE/DETACH branches), so the belt-and-suspenders fallbacks are
  discoverable. `DIRECTORY.md`'s `.claude/settings.json` row updated to record the full-spine wiring +
  cite the test.
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_settings_wiring.py" -q` (3 passed).

### CR-070 — retire the SPK-1 probe hooks + reconcile stale DIRECTORY rows (Phase 2 close-out)
- **Date registered:** 2026-07-10
- **What:** removed the three spent `spk1-*.sh` SPK-1 probe hooks (scripts + `.claude/settings.json` wiring + DIRECTORY row) now that SPK-1 is recorded to `SPK-1.json`; removed the stale `trial-runs/_scratch-squark-3j/` DIRECTORY row (gitignored scratch, cleaned from disk by the concurrent trial). `.claude/settings.json` now wires exactly the real spine hooks (PreToolUse card-guard + skill-guard, UserPromptSubmit router, PostToolUse observer, Stop dispatcher) via the D-1 idempotent merge.
- **Why:** the one-shot `spk1-stop.sh` was live-armed (its `logs/.spk1-stop-fired` marker absent) and would block a real worktree turn-end once; the stale DIRECTORY row was the sole `check_agent_surface.py` FAIL, blocking the green board. Both isolated to `spine-hardening`; the live trial's trial-runs files are untouched.
- **Verify:** `python3 src/ravel/validation/check_agent_surface.py` exits 0; `python3 -c "import json;h=json.load(open('.claude/settings.json'))['hooks'];assert 'spk1' not in json.dumps(h)"`

### CR-071 — figure_target `primary` subcommand + single-primary invariant (D9)
- **Date registered:** 2026-07-10
- **What:** added a `primary` subcommand to `src/ravel/plotting/figure_target.py` that owns
  the SINGLE-PRIMARY invariant nothing in the tool enforced before. `declare --primary` only ever
  SET `primary:true` and never cleared the flag on the other targets, so a run that declared two
  figures each `--primary` ended up with TWO primary targets — and the consumption resolver
  (`_resolve_target`, used by `read_axes`/`read_style`/`critique`) silently picked the FIRST primary
  it found, a source of quiet figure-selection drift. `primary --rundir R --figure-id ID` (or
  `--role summary|overlay`) now makes exactly that target primary and clears every other in one
  write; `primary --rundir R` with no selector is a QUERY that prints the current primary, dies
  `AMBIGUOUS` when several are marked, or points you at `--figure-id` when none is. Stdlib-only,
  fail-loud, additive (no existing subcommand touched). Test (TDD-first):
  `tests/unit/test_figure_target_primary.py` (2 cases: the two-primary bug repro → single
  primary after `primary`, and the AMBIGUOUS query verdict).
- **Why:** the figure contract is only checkable if exactly ONE published figure is the run's primary
  target — the G9 integrity gate and the deck's headline both key off it. An unenforced invariant
  (two targets both `primary`) let the resolver choose non-deterministically; this closes that
  loophole with a fail-loud command instead of a silent first-match.
- **Where-embedded:** `figure_target.py`'s module-docstring Usage block now lists
  `primary --rundir R [--figure-id ID | --role summary|overlay]` alongside the other subcommands.
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_figure_target_primary.py::test_primary_enforces_single_primary" -q`

### CR-072 — figure_target `checkin` lifecycle step (D5/D9)
- **Date registered:** 2026-07-10
- **What:** added a `checkin` subcommand to `src/ravel/plotting/figure_target.py` — the
  explicit lifecycle step that records the CHECK-IN-time primary declaration. `declare` sets the
  per-target `declared_at_checkin` flag EAGERLY (at declaration), which conflated "a target exists"
  with "the primary was echoed at an ACTUAL check-in". `checkin --rundir R` now flips
  `declared_at_checkin=True` on the single primary (or the `--figure-id` target) and re-echoes the
  check-in-ready block (published image / generated counterpart / side-by-side); it refuses
  fail-loud when zero or several targets are marked primary and no `--figure-id` disambiguates.
  This is the only output the Phase-2 waypoint Stop-gate (G11) treats as satisfying the CHECK-IN-2
  figure waypoint — presence of a declaration alone no longer counts. Stdlib-only, fail-loud,
  additive (no existing subcommand touched). Test (TDD-first):
  `tests/unit/test_figure_target_primary.py` (2 cases: `checkin` flips the flag True on a
  single primary and echoes `declared_at_checkin=True`; refuses exit 1 when two targets are primary).
- **Why:** "observable before enforceable" + "provenance, not presence" — the CHECK-IN-2 waypoint
  gate must key on a lifecycle EVENT (the primary echoed at check-in), not on the eager flag any
  `declare` sets. Separating the check-in event from declaration closes the backfill loophole where
  a never-checked-in declaration would satisfy the waypoint.
- **Where-embedded:** `figure_target.py`'s module-docstring Usage block now lists
  `checkin --rundir R [--figure-id ID]`; `.claude/skills/figure-contract/SKILL.md` §3 (ECHO /
  CHECK-IN) documents the declare → attach → **checkin** → compose → fulfil-primary lifecycle step.
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_figure_target_primary.py::test_checkin_marks_declared_at_checkin_on_primary" "$REPO/tests/unit/test_figure_target_primary.py::test_checkin_refuses_without_a_single_primary" -q`

### CR-073 — fulfil-primary writes verified_by_physicist (D5)
- **Date registered:** 2026-07-10
- **What:** added a `fulfil-primary` subcommand to `src/ravel/plotting/figure_target.py` — the
  ONLY write site of the `verified_by_physicist` field. That field was DEAD: initialized to `None` at
  declare, printed by `show`/`checkin`, and never written anywhere. `fulfil-primary --rundir R --by
  WHO [--utc TS] [--note "..."]` now sets `verified_by_physicist = {by, utc, note}` on the single
  primary target — but ONLY after the composed `side_by_side` exists on disk (it refuses fail-loud
  otherwise: the physicist signs off AGAINST the side-by-side composite, not a bare number). Refuses
  fail-loud when zero or several targets are marked primary. `load_contract` returns a live reference
  into the doc, so the command mutates the target and `save_contract`s directly. Stdlib-only,
  fail-loud, additive (no existing subcommand touched). Test (TDD-first):
  `tests/unit/test_figure_target_primary.py::test_fulfil_primary_writes_verified_by_physicist`
  (refuses exit 1 with no side_by_side; writes the field once a real composite is on disk).
- **Why:** "provenance, not presence" — a field the workflow claimed to carry (physicist verification)
  but never populated is a silent gap: `show`/`checkin` would forever print `None`. This closes the
  D5 dead-field loophole with a lifecycle write site gated on the composite existing, so verification
  is recorded against the side-by-side the physicist actually saw.
- **Where-embedded:** `figure_target.py`'s module-docstring Usage block now lists
  `fulfil-primary --rundir R --by WHO [--utc TS] [--note "..."]` and states `verified_by_physicist`
  is a WRITTEN lifecycle field; `.claude/skills/figure-contract/SKILL.md` §3 documents the closing
  `fulfil-primary` step (declare → attach → checkin → compose → **fulfil-primary**).
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_figure_target_primary.py::test_fulfil_primary_writes_verified_by_physicist" -q`

### CR-074 — primary-aware compose (D5)
- **Date registered:** 2026-07-10
- **What:** `src/ravel/plotting/figure_target.py compose`'s `--figure-id` is now OPTIONAL.
  Extracted a `resolve_compose_target(doc, figure_id)` resolver: with an explicit `--figure-id` it
  behaves exactly as before (normalize → `find_target` → fail-loud if unparseable/undeclared); with
  the id OMITTED it falls back to the single PRIMARY target (the deck default), and fails loud when
  there is not exactly one primary (`found N -- pass --figure-id or set the primary with
  `primary --figure-id ID``). The resolver mirrors `find_target` on the ALREADY-LOADED doc (NOT
  `_resolve_target`, which reloads a detached copy that cannot be saved through) so `compose` keeps
  mutating and `save_contract`-ing the SAME doc. The whole PIL body below the head is unchanged — it
  already consumed `fig_id`/`tgt`/`doc`. The `compose` subparser drops `required=True` on
  `--figure-id`. Tests (TDD-first),
  `tests/unit/test_figure_target_primary.py`:
  `test_resolve_compose_target_falls_back_to_primary` (omit → the sole primary; explicit id → that
  target), `test_resolve_compose_target_ambiguous_without_id_raises` (two primaries + no id →
  `SystemExit`), `test_compose_figure_id_is_optional_in_argparse` (missing id reaches
  `load_contract`'s die, not an argparse "required" error).
- **Why:** the single-primary lifecycle (CR-071 `primary` / CR-072 `checkin` / CR-073
  `fulfil-primary`) already treats the sole primary as the deck default, but `compose` still forced
  an explicit `--figure-id` — a needless mismatch that made the common single-figure run pass the id
  redundantly and diverge from the other subcommands. `compose` now resolves the target the same way
  they do.
- **Where-embedded:** `figure_target.py`'s module-docstring Usage line now reads
  `compose --rundir R [--figure-id ID] [--out PNG]  # omit id -> primary`; the compose subparser
  help states "omit to compose the single PRIMARY target (deck default)". Existing docs that pass
  `compose --figure-id <ID>` remain valid (the flag is backward-compatible; omitting it is the new
  convenience).
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_figure_target_primary.py" -q`

### CR-075 — primary-aware inv_figure_contract_fulfilled (D9/G10)
- **Date registered:** 2026-07-10
- **What:** `src/ravel/validation/validate_run_state.py`'s `inv_figure_contract_fulfilled`
  invariant is now PRIMARY-aware and hard-FAILs (not WARNs) in EVERY task_mode. Once generation is
  complete (`facts["generation_hits"]` non-empty) and `inputs/figure_target.json` exists, the
  invariant loads the contract and: (a) FAILs if MORE than one target is marked `primary`
  (`N figure targets marked primary (...) -- exactly one must be primary` — enforces the
  single-primary invariant at validate time, not only on the write path via `figure_target.py
  primary`); (b) for the single primary target that carries `declared_at_checkin`, FAILs if its
  `generated_counterpart` is null (`PRIMARY target ... has no generated counterpart`) OR its
  `side_by_side` is null (`PRIMARY target ... no composed side_by_side (run `figure_target.py
  compose`)`). This fires even where the figure_contract STAGE is only level O (scan/reinterpret),
  which does NOT stage-check `side_by_side`. Below this new head the pre-existing legacy delegation
  (N/A when level != "R"; else `check_figure_contract` fulfilment) is unchanged. Non-primary
  declared-but-unrendered targets stay advisory (the `result_pack.py` WARN). New fixture
  `_fixture_primary_unfulfilled` + selftest case 8 (count literal bumped `5+2` → `6+2`).
- **Why:** the figure_contract STAGE only hard-checks `side_by_side` for `task_mode == reproduce`;
  a scan/reinterpret run could ship a headline primary figure with a bound counterpart but no
  composed published-vs-generated side-by-side (or a hand-edited/declare-twice contract with two
  primaries) and pass validate. G10/D9 make the PRIMARY target's fulfilment a hard gate in all
  modes, closing that hole while leaving secondary targets advisory.
- **Where-embedded:** `docs/workflow/checklists/figure-contract.md` Emission-contract section (the new
  `validate_run_state.py` PRIMARY-aware hard-FAIL bullet).
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state.py::test_primary_missing_side_by_side_fails_in_non_reproduce_mode" -q`
  and `cd /tmp && python3 "$REPO/src/ravel/validation/validate_run_state.py" --selftest` (8 cases).

### CR-076 — verify_pack primary-aware FAIL (D9/G10)
- **Date registered:** 2026-07-10
- **What:** `src/ravel/validation/verify_pack.py`'s `check_figure_target` (the shared checker for
  BOTH callers — the embedded `figures.json.figure_target` block via `check_figures`, and the
  standalone `figure_target.json` artifact) is now PRIMARY-aware. A target that is both `primary` and
  `declared_at_checkin` is a HARD gate: it FAILs (flips verify_pack exit 0 → 1) when its
  `generated_counterpart` is null (`PRIMARY target ... no generated counterpart attached (headline not
  bound to the approved target)`) OR when it has a counterpart but a null `side_by_side`
  (`PRIMARY target ... has a generated counterpart but no composed side_by_side (run
  `figure_target.py compose`)`). A non-primary declared-but-unrendered target stays the pre-existing
  advisory WARN, and the on-disk path-resolution checks below the head are unchanged. Tests
  (TDD-first), `tests/unit/test_verify_pack_primary.py`:
  `test_primary_unfulfilled_counterpart_fails` (null counterpart → FAIL),
  `test_primary_counterpart_without_side_by_side_fails` (counterpart, no side-by-side → FAIL),
  `test_nonprimary_unfulfilled_is_warn_only` (non-primary null counterpart → WARN, no FAIL). Called
  directly with a `Report` so the DECLARED-but-unfulfilled branches need no rundir/on-disk artifacts.
- **Why:** verify_pack (Tier-A of the step-9 verification panel) previously WARNed every unfulfilled
  figure-contract target, so a deck could headline a PRIMARY figure whose approved-at-check-in target
  had no bound counterpart or no composed side-by-side and still pass the artifact-integrity gate.
  D9/G10 make the PRIMARY target's fulfilment fail-loud in the artifact panel too, mirroring the
  validate-time hard gate (CR-075) so both halves of Tier-A agree; secondary targets stay advisory.
- **Where-embedded:** `docs/workflow/steps/09-verify.md`'s `verify_pack.py` invocation comment now reads
  `figure-contract PRIMARY target fulfilled-or-FAILed (non-primary WARNed)`.
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_verify_pack_primary.py" -q` (3 cases).

### CR-077 — validate_parameters.py + validations.json (D10)
- **Date registered:** 2026-07-10
- **What:** new stdlib-only tool `src/ravel/validation/validate_parameters.py` (Phase 3, G12)
  owning `<rundir>/inputs/validations.json` (schema_version 1; provenance `generated_by` +
  `input_fingerprint` over `inputs/task_contract.json`; obligation status defaults `PENDING`, PASS is
  EARNED). Three subcommands: `emit --rundir <d> --param NAME[:varied|fixed]` (repeatable) seeds a
  PENDING obligation per named param AND AUTO-EMITs a `trap_obligation` for each of
  `GATED_TRAPS=(T3,T6,T7,T8)` recorded as hit in `inputs/trap_sweep.json` (`traps_hit[]`, accepting
  list[str] or list[{id}]); each auto-emitted obligation carries the concrete check that trap demands
  (`TRAP_VALIDATION_CHECKS`, mirroring the physics-traps T-catalogue — per-point spectrum/σ×BR/A×ε
  re-weight for T3, ME/PS/ISR + run-card jet-cut audit for T6, HV-parameter sourcing + truth-level
  validation for T7, per-width generation for T8). `record --param <name> --status PASS|FAIL
  --evidence …` sets one obligation — a PASS is EARNED: recording PASS with no `--evidence` is refused
  (exit 1). `check --rundir <d> --require-nonempty` is the GATE: exit 1 while any varied-param/trap
  obligation is not PASS OR the obligation set is empty, exit 0 only when all PASS. Exit codes 0 PASS /
  1 domain FAIL / 2 usage-or-not-a-dir / 3 unparseable-validations.json; `--selftest` runs 5 cases
  (emit-seeds-gated-traps-not-T1 + provenance, check-blocks-while-PENDING, bare-PASS-refused,
  check-passes-all-PASS, FAIL-record-re-blocks). Public API: `validations_path`, `load_validations`,
  `save_validations`, `cmd_emit`/`cmd_record`/`cmd_check`, `GATED_TRAPS`, `main(argv=None)`.
  TDD-first test `tests/unit/test_validate_parameters.py` (3 cases: subprocess `--selftest`,
  emit auto-seeds gated traps only, check blocks until all PASS).
- **Why:** a trap sweep (P3) that flags T3/T6/T7/T8 was "recorded" but nothing forced the flagged
  physics to actually be VALIDATED before a scan's varied parameters reached long compute — the D10
  gap. This makes each gated trap hit an obligation the run must discharge with evidence, fail-loud and
  provenance-stamped (presence never satisfies the gate), before the scan grid runs.
- **Where-embedded:** `.claude/skills/judgment-protocols/SKILL.md` (new "P3 → the D10
  parameter-validation contract" section + the P3 row note; re-mirrored to `.agents/skills/` via
  `sync_skills.py`); `DIRECTORY.md` `_infrastructure/` cell row for the new tool.
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 "$REPO/src/ravel/validation/validate_parameters.py" --selftest`
  (5 cases) and `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_parameters.py" -q` (3 cases).

### CR-078 — inv_param_validated_before_scan (D10/G12)
- **Date registered:** 2026-07-10
- **What:** new invariant `inv_param_validated_before_scan` registered inside
  `src/ravel/validation/validate_run_state.py`'s `INVARIANTS` tuple (keyed to the `analysis`
  stage, after `figure-contract-fulfilled`) — the enforcement half of CR-077's parameter-validation
  contract. It gates ONLY `task_mode=="scan"`, and only once the scan is actually SHIPPING
  (`scan_manifest.json` present, or `statistics_artifact_name=="scan.json"` with a resolved
  `statistics_path`) so an in-progress scan is never prematurely blocked. When shipping: a missing
  `inputs/validations.json` FAILs (unless the run is legacy → `waived-legacy`); an unparseable one
  FAILs; a validations.json carrying no varied-param/`trap` obligation FAILs; any obligation whose
  `status != "PASS"` FAILs (naming each `name=status`); all-PASS → PASS. New selftest case 9 ("scan
  shipping with a PENDING param validation → FAIL"), fixture `_fixture_scan_param_pending` (ships
  scan.json + scan_manifest.json, validations.json PENDING), and the `--selftest` count literal bumped
  `{6+2}`→`{7+2}` (now 9 cases). TDD-first test
  `tests/unit/test_validate_run_state.py::test_scan_with_pending_param_validation_fails` (PENDING →
  FAIL; flip to PASS → invariant clears). The existing regression test
  `test_scan_aggregator_without_sibling_intermediates_passes_generation_and_analysis` was patched to
  carry an all-PASS validations.json (its shipping scan would otherwise newly FAIL). `import json` added
  to the test module (the new test uses it).
- **Why:** CR-077 gave a run the OBLIGATION to validate a scan's varied params but nothing forced it —
  a scan could ship `scan.json` with `validations.json` still PENDING (or absent) and pass the
  lifecycle gate. This makes the unvalidated-scan a hard `validate_run_state.py` FAIL (fail-loud + block,
  not advise), closing the observe→enforce loop for D10/G12. Presence never satisfies it: an obligation
  set that is empty or not-all-PASS FAILs.
- **Where-embedded:** `.claude/skills/run-scan/SKILL.md` (new "## 1b. Validate the varied params BEFORE
  launch" gate; re-mirrored to `.agents/skills/` via `sync_skills.py`) and `docs/workflow/steps/08-scan.md`
  (step "1b) VALIDATE THE VARIED PARAMS BEFORE LAUNCH" before the LAUNCH command) — both run
  `validate_parameters.py check --rundir <scandir> --require-nonempty` (exit 0 required) before launch.
  MIGRATION: the one live non-legacy shipping scan `trial-runs/sleptonscan_fig3_SCAN` (has `inputs/` →
  non-legacy, ships `scan.json`, had no `validations.json`) was backfilled with an all-PASS
  `inputs/validations.json` (m_slepton varied + T6 trap, both recorded PASS with backfill evidence) in
  this commit; the other four `*_SCAN` dirs are grandfathered (date < GATE_EPOCH or no `inputs/`).
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state.py::test_scan_with_pending_param_validation_fails" -q`;
  `cd /tmp && python3 "$REPO/src/ravel/validation/validate_run_state.py" --selftest` (9 cases);
  `python3 "$REPO/src/ravel/validation/validate_run_state.py" --rundir "$REPO/trial-runs/sleptonscan_fig3_SCAN"` (exit 0).

### CR-079 — deviations-on-change broadened to baselined-input edits (D15)
- **Date registered:** 2026-07-10
- **What:** broadened `inv_deviations_on_change` in `src/ravel/validation/validate_run_state.py`
  (registered as the `DEVIATIONS-on-change` invariant, `result_pack` stage) to ALSO trigger on a
  post-CHECK-IN-1 edit to any CHECK-IN-1-baselined input. New module surface: `BASELINED_INPUTS`
  constant (`task_contract.json`, `resource_census.json`, `trap_sweep.json`, `figure_target.json`,
  `basis_manifest.json`, `validations.json`), `load_run_state(rundir)` (reads `run_state.json` locally,
  degrades to `None` when absent), and `baselined_inputs_changed(rundir)` (basenames of baselined
  `inputs/` files that `run_state.json.edits[]` records an edit to, but only once a `CHECKIN1` is on
  record). The invariant now FAILs when a baselined input changed after CHECK-IN 1 and `DEVIATIONS.md`
  is absent OR carries no row NAMING each changed file; the existing trap/stat-mode/escalate triggers
  are unchanged, and with no `run_state.json` behavior is identical to before (degrades safely). New
  selftest case 10 (`_fixture_baselined_edit_no_deviation` — a full-PASS survey plus a `run_state.json`
  recording CHECK-IN 1 + an edit to `inputs/task_contract.json` and a generic `DEVIATIONS.md`), and the
  `--selftest` count literal bumped `{7+2}`→`{8+2}` (now 10 cases).
- **Why:** D15/G17 (post-hoc half). CHECK-IN 1 freezes the approved plan, but nothing forced a
  DEVIATIONS.md row when one of those baselined inputs was edited afterward — a run could silently
  change its contract/census/trap-sweep/figure-target/basis/validations after approval and still pass
  the lifecycle gate. This makes an undocumented baselined-input edit a hard `validate_run_state.py`
  FAIL (fail-loud + block, not advise). Observable-before-enforceable: the trigger reads only what the
  Phase-1 observer already logs to `run_state.json` (`checkins[]` with `id=="CHECKIN1"`, `edits[]`
  `{path,utc}`); presence never satisfies it — a generic DEVIATIONS.md that fails to name the file
  still FAILs.
- **Where-embedded:** `docs/workflow/checklists/check-ins.md` (DEVIATION CHECK-INS section — a new note that
  editing a CHECK-IN-1-baselined input is itself a course change needing a `DEVIATIONS.md` row naming
  the file, enforced by the `DEVIATIONS-on-change` invariant).
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state.py::test_baselined_input_edit_without_deviation_row_fails" "$REPO/tests/unit/test_validate_run_state.py::test_deviations_invariant_unchanged_without_run_state" -q`;
  `cd /tmp && python3 "$REPO/src/ravel/validation/validate_run_state.py" --selftest` (10 cases).

### CR-080 — edit-time DEVIATIONS guard on baselined-input edits (D15/G17)
- **Date registered:** 2026-07-10
- **What:** the moment-of-change twin of CR-079. New `edit_guard(changed_path)` in
  `src/ravel/validation/validate_run_state.py` (returns 0 allow / 1 block: 1 iff `changed_path`
  is a `BASELINED_INPUTS` file directly under an `inputs/` dir whose sibling-rundir `DEVIATIONS.md`
  does not name it), exposed as `--edit-guard PATH` (dispatched right after `--selftest`; exit 1 =
  block with the reason on stderr, else 0). New `PostToolUse` hook `.claude/hooks/deviations-guard.sh`
  parses the tool-call JSON on stdin, extracts the edited path with python3, calls `--edit-guard`, and
  maps the tool's exit 1 → the hook's blocking exit 2 (its stderr reason is fed back to the agent).
  Wired into the worktree `.claude/settings.json` as an `Edit|Write|MultiEdit` PostToolUse block via
  the D-1 idempotent merge (append-only, presence-checked — the PreToolUse card-guard and the Phase-1
  PostToolUse observer both survive untouched). New selftest case 11 (`--edit-guard` blocks a baselined
  edit lacking a DEVIATIONS row, allows once named); the `--selftest` count literal bumped
  `{8+2}`→`{8+3}` (now 11 cases).
- **Why:** D15/G17. CR-079's `DEVIATIONS-on-change` invariant catches an undocumented baselined-input
  edit AFTER the fact (at the lifecycle gate); this catches it AT the moment of the edit and BLOCKS the
  turn, so a run cannot silently continue on a changed contract/census/trap-sweep/figure-target/basis/
  validations after CHECK-IN 1 (fail-loud + block, not advise). Belt-and-suspenders: the two halves are
  independent — the hook fires per-edit in-session, the invariant re-checks from the ledger at gate
  time. Reuses the single source of truth (`BASELINED_INPUTS` + `validate_run_state.py`); no parallel
  checker.
- **Where-embedded:** `docs/workflow/checklists/check-ins.md` (DEVIATION CHECK-INS — the baselined-input note
  now names the `deviations-guard.sh` PostToolUse block and the by-hand
  `validate_run_state.py --edit-guard <path>` fallback); `DIRECTORY.md` row for
  `.claude/hooks/deviations-guard.sh`.
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_deviations_guard.py" -q`;
  `cd /tmp && python3 "$REPO/src/ravel/validation/validate_run_state.py" --selftest` (11 cases).

### CR-081 — inv_ladder_order: full/scan reaching generation requires a smoke-rung PASS (D11/G13)
- **Date registered:** 2026-07-10
- **What:** new invariant `inv_ladder_order` registered inside
  `src/ravel/validation/validate_run_state.py`'s `INVARIANTS` tuple as the `ladder-order`
  invariant, keyed to the `generation` stage (first entry, before `resource-census-before-route`). It
  gates only `compute_plan in {full,scan}` runs, and only once the run has actually REACHED generation —
  `facts["generation_hits"]` or `facts["result_pack_paths"]` non-empty, or (task_mode=scan)
  `scan_json_ok(facts) and scan_manifest_ok(facts)` — so an in-progress full/scan is never prematurely
  blocked (returns PASS "gate not yet active"). Once reached: legacy runs → `waived-legacy`; otherwise the
  run MUST carry a smoke-rung PASS record (a new fact `ladder_record_path` =
  `find_first_existing(rundir, "logs/ladder.json", "inputs/ladder.json")`, whose `rungs[]` carries an
  entry `{"rung":"smoke","status":"PASS"}`) or the invariant hard-FAILs ("the dry→smoke→full→scan ladder
  was skipped"). New fact `ladder_record_path` added in `discover_facts` after `result_pack_paths`. New
  selftest case 12 ("full/scan reaches generation without a smoke-rung PASS → FAIL"), fixture
  `_fixture_scan_no_smoke_ladder` (ships scan.json + scan_manifest.json but no ladder record), and the
  `--selftest` count literal bumped `{8+3}`→`{9+3}` (now 12 cases). TDD-first test in the new module
  `tests/unit/test_validate_run_state_lifecycle.py::test_ladder_order_fails_without_smoke_rung`
  (no ladder → FAIL + verdict FAIL/exit 1; write a `logs/ladder.json` smoke-rung PASS → invariant clears).
  The existing regression test `test_scan_aggregator_without_sibling_intermediates_passes_generation_and_analysis`
  was patched to carry an `inputs/ladder.json` smoke-rung PASS (its complete scan attests generation and
  would otherwise newly FAIL); kept under `inputs/` (not `logs/`) so it stays a run-level provenance
  artifact and generation still PASSes via the scan-attestation path that test exercises.
- **Why:** D11/G13. The `none→dry→smoke→full→scan` compute ladder is a load-bearing safety rail
  (`cost-preflight` skill; global constraint "compute laddered"), but nothing forced a run to prove it
  climbed the cheap rungs — a full/scan could jump straight from dry to a full grid, spending hours of
  compute the smoke rung would have caught. This makes a full/scan that reached generation without a
  recorded smoke-rung PASS a hard `validate_run_state.py` FAIL (fail-loud + block, not advise). It is the
  enforcement half of the ladder-record contract; the producer half (a tool auto-emitting
  `logs/ladder.json`) is not yet wired, so a completed scan records the smoke rung by hand per the schema
  (as trap_sweep.json et al. are), until a producer lands.
- **Where-embedded:** `docs/workflow/steps/08-scan.md` (new "Record the smoke rung before the full scan
  (D11/G13)" note after the cost_preflight disk-budget block — names the `logs/ladder.json` schema and
  the `ladder-order` FAIL); `docs/workflow/checklists/verification-panel.md` (Tier-A `validate_run_state.py`
  invariant list now reads "R5/pairing/ladder-order" and the exit-0 bullet spells out the smoke-rung
  requirement).
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py::test_ladder_order_fails_without_smoke_rung" -q`;
  `cd /tmp && python3 "$REPO/src/ravel/validation/validate_run_state.py" --selftest` (exit 0, 12 cases).

### CR-082 — inv_certify_before_limit: a non-FAIL acc×eff cert must precede any shipped limit (D12/G14)
- **Date registered:** 2026-07-10
- **What:** new invariant `inv_certify_before_limit` registered inside
  `src/ravel/validation/validate_run_state.py`'s `INVARIANTS` tuple as the `certify-before-limit`
  invariant, keyed to the `statistics` stage (first entry, before `ladder-order`). It gates only
  cert-required stat modes — new tuple `CERT_REQUIRED_STAT_MODES = (published-likelihood,
  simplified-likelihood, best-sr-counting, combined-counting, stability-only)` — and only once the limit
  stage is actually REACHED: `facts["statistics_path"]` or `facts["result_pack_paths"]` non-empty, OR
  (task_mode=scan) `scan_json_ok(facts)` (a complete scan is a limit-shipping mode). Not-yet-reached →
  PASS ("limit stage not yet reached"); legacy runs → `waived-legacy`. Once reached, a new helper
  `_find_limit_cert(rundir, contract, facts)` discovers a verdict-bearing acc×eff cert — the analysis-stage
  cert pointer (`facts["analysis_path"]` when kind ∈ {cutflow_cert,cert}) for non-scan, else
  `result_pack.find_cert` on the routine — and **deliberately never reads `scan.json` per-point attestation
  as a cert**. Missing cert → hard FAIL (with a scan-specific note that per-point attestation does not
  satisfy D12); a cert whose `verdict=="FAIL"` → hard FAIL; only `verdict ∈ {PASS,WARN}` passes. This keys
  on the shared `verdict` field both `certify_acceptance.py` (per-run) and `validate_cutflow.py` (one-time)
  write. Two new fixtures — `_fixture_reproduce_cert_fail` (a reproduce run whose `outputs/cutflow_cert.json`
  is `verdict=FAIL`; the analysis stage only WARNs, this invariant hard-FAILs) and
  `_fixture_scan_cert_attestation_only` (a COMPLETE scan carrying scan.json+scan_manifest but NO cert) —
  plus selftest case 13 (`_certify_check`: the reproduce FAIL-cert case AND, inline, the cert-less complete
  scan both FAIL); `--selftest` count literal bumped `{9+3}`→`{10+3}` (now 13 cases). TDD-first tests
  `tests/unit/test_validate_run_state_lifecycle.py::{test_certify_before_limit_fails_on_fail_cert,
  test_certify_before_limit_scan_attestation_insufficient}`. The existing regression test
  `test_scan_aggregator_without_sibling_intermediates_passes_generation_and_analysis`
  (`tests/unit/test_validate_run_state.py`) — a complete scan aggregator that ships a
  published-likelihood limit — was patched to carry an `outputs/cutflow_cert.json` aggregate PASS cert (it
  would otherwise newly FAIL D12); the scan-attestation generation/analysis path it guards is unchanged
  (a cutflow_cert is not a generation artifact and scan-mode analysis reads scan.json), same pattern as
  CR-081's patch of that test for the ladder gate.
- **Why:** D12/G14. Acceptance×efficiency vs the published values is the one-time (per routine) /
  per-run quality gate that certifies the pipeline reproduces the analysis — but nothing forced that cert
  to exist, and be non-FAIL, BEFORE a µ₉₅ limit shipped. The analysis stage's existing behaviour only
  WARNs on a FAIL cert (records the pointer, "delivery is the panel's call"), which is advisory, not a
  block — a FAIL or entirely-absent cert could still feed a limit. This makes a limit-shipping run whose
  acc×eff cert is FAIL/absent a hard `validate_run_state.py` FAIL (fail-loud + block, not advise), closing
  the gap for scans in particular: a completed scan's per-point `scan.json` attestation proves the point
  RAN, not that its acceptance matched published, so it never substitutes for the cert.
- **Where-embedded:** `docs/workflow/steps/07-exclude.md` ("Make the limit trustworthy" section — new
  **Enforced (D12/G14)** note spelling out that `certify-before-limit` hard-blocks a FAIL/absent cert and
  that scan attestation does not waive it); `docs/workflow/checklists/verification-panel.md` (Tier-A
  `validate_run_state.py` invariant list now reads "R5/pairing/ladder-order/certify-before-limit" and the
  exit-0 bullet spells out the acc×eff-cert requirement).
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py::test_certify_before_limit_fails_on_fail_cert" "$REPO/tests/unit/test_validate_run_state_lifecycle.py::test_certify_before_limit_scan_attestation_insufficient" -q`;
  `cd /tmp && python3 "$REPO/src/ravel/validation/validate_run_state.py" --selftest` (exit 0, 13 cases).

### CR-083 — inv_trap_obligations: a PASS obligation per obligation-bearing trap hit before generation ships (D13/G15)
- **Date registered:** 2026-07-10
- **What:** new invariant `inv_trap_obligations` registered inside
  `src/ravel/validation/validate_run_state.py`'s `INVARIANTS` tuple as the
  `trap-obligations-discharged` invariant, keyed to the `generation` stage (first entry, before
  `certify-before-limit`). It triggers once generation is reached (`facts["generation_hits"]` or
  `facts["result_pack_paths"]` non-empty, OR task_mode=scan with `scan_json_ok(facts)`); until then →
  PASS ("generation not yet reached"). Once triggered it takes the trap hits (`traps_hit_ids`) and
  EXCLUDES **T3/T9** — those are already driven by the basis-manifest gate
  (`inv_basis_manifest_before_comparison`), so gating them here would double-gate. For each remaining
  (obligation-bearing) hit it requires a `trap_sweep.json` `obligations[]` entry `{trap,
  obligation_kind, artifact, status ∈ PENDING|PASS|FAIL}` with `status=="PASS"`; a missing entry or a
  non-PASS status → hard FAIL (detail names each undischarged hit + its worst obligation status). Legacy
  runs → `waived-legacy`; a missing `trap_sweep.json` under trigger → FAIL. The `_trap_sweep_doc` selftest
  builder gained an `obligations=` kwarg (default: a discharged PASS obligation per non-T3/T9 hit, so
  existing hit-fixtures stay green; existing `_trap_sweep_doc()` no-arg callers now carry an empty
  `obligations[]`). New fixture `_fixture_trap_obligation_pending` (a reproduce run with a T8 hit whose
  only obligation is `status=PENDING` + a generation artifact) drives selftest case 14 (`_trap_obl_check`);
  `--selftest` count literal bumped `{10+3}`→`{11+3}` (now 14 cases). The `--backfill-plan` trap_sweep
  string now names the `obligations[]` field. TDD-first test
  `tests/unit/test_validate_run_state_lifecycle.py::test_trap_obligations_pending_blocks` (T8 PENDING
  → FAIL with "T8" in detail; flip to PASS → the invariant clears).
- **Why:** D13/G15. The trap sweep (judgment-protocols P3) records which physics traps a run hit, and the
  existing `trap-sweep-recorded` invariant only checks each hit is *referenced* in escalate[]/DEVIATIONS.md
  (a WARN). Nothing forced the hit's ROUTE CONSEQUENCE to actually be discharged before the run shipped its
  generation — a T8 wide-resonance hit could be "recorded" while its per-width regeneration never ran (exit
  0, silently wrong acceptance). This adds a hard, per-hit obligation ledger to `trap_sweep.json` and a
  generation-stage gate that FAILs (fail-loud + block, not advise) until every obligation-bearing hit
  carries a `status==PASS` obligation. It composes with — does not duplicate — the T3/T9 basis-manifest gate
  and the scan-only D10 `validations.json` ledger (`param-validated-before-scan`): this one gates ALL task
  modes at generation over the trap-sweep artifact's own `obligations[]`.
- **Where-embedded:** `docs/workflow/checklists/physics-traps.md` (Sweep output section — the `obligations[]`
  field is now part of the sweep-output contract, with the "every obligation-bearing hit needs a
  `status==PASS` entry before generation ships / T3-T9 excluded" rule and the `trap-obligations-discharged`
  invariant named); `.claude/skills/judgment-protocols/SKILL.md` P3 → D10 section (a new paragraph
  documenting the `trap_sweep.json` `obligations[]` ledger and the generation-time `inv_trap_obligations`
  gate, distinguished from the scan-only `validations.json` ledger), re-mirrored to `.agents/skills/` via
  `sync_skills.py`.
- **Status:** EMBEDDED.
- **Verify:** `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py" "$REPO/tests/unit/test_validate_run_state.py" -q` (25 passed);
  `cd "$REPO" && python3 src/ravel/validation/validate_run_state.py --selftest` (exit 0, 14 cases).

### CR-084 — `sr_plausibility.py`: the D14 analysis→statistics plausibility EMITTER (new stdlib tool)
- **Date registered:** 2026-07-10
- **What:** new stdlib-only tool `src/ravel/validation/sr_plausibility.py` (Phase 4, L5b). It
  reads a run's `outputs/sr_yields.json` (non-empty array of `{name,n,b,db,s}`) +
  `outputs/pyhf_exclusion/exclusion.json` (`obs_limit`/`best_sr`/optional `excluded_obs`) and EMITS
  `outputs/sr_plausibility.json` with an EARNED `verdict ∈ {plausible, implausible}` — it NEVER defaults
  to `plausible` (SHARED-CONVENTIONS §B: earns it only if EVERY check passes). Four analysis→statistics
  sanity checks: (1) `nontrivial-sr` ≥1 SR carries signal>0; (2) `mu95-in-band` `obs_limit` finite and
  off the floor(`MU95_FLOOR=1e-3`)/ceiling(`MU95_CEIL=1e6`) — a runaway/degenerate µ₉₅ fails; (3)
  `excluded-obs-consistent` a stored `excluded_obs` must equal `(µ₉₅ < 1.0)`; (4) `driving-accxeff-in-band`
  — ONLY when `--sigma-ref-fb F --lumi-fb F` are supplied — the driving-SR acc×eff `= s/(σ_ref·L)` banded
  to `(0, ACCXEFF_CEIL=1.0]`, catching the "956% acc×eff" unphysical-fraction defect class. Module API:
  `assess(...)`, `write_sr_plausibility_json(...)`, `compute_input_fingerprint(rundir, input_rels=INPUT_RELS)`,
  `INPUT_RELS`, `main(argv=None)`. Exit 0 plausible / 1 implausible / 2 usage-IO-not-a-dir / 3
  required-input-missing-or-invalid. The record carries its OWN plausibility-domain `input_fingerprint`
  (canonical-JSON sha256 over the two consumed inputs, fixed order) — the same p4a-local canonicalization
  `validate_run_state.recompute_input_fingerprint` will recompute (Task 4.9) — deliberately SEPARATE from
  p1's `provenance.py` lifecycle fingerprint (D-7): `sr_plausibility.json` is a domain-separate artifact,
  NOT a `--verify-provenance`-checked one.
- **Why:** D14, L5b physics-lifecycle invariant. A run could emit SR yields and a µ₉₅ that are internally
  self-consistent JSON yet physically nonsensical (all-zero yields with a runaway µ₉₅ sentinel; an
  acc×eff >1; an `excluded_obs` flag inconsistent with its own limit) and still flow downstream. This
  emitter gives the analysis→statistics boundary an on-disk, machine-checkable plausibility verdict that a
  later gate can require, fail-loud (exit 1) the moment a check trips.
- **Where-embedded:** `docs/workflow/steps/07-exclude.md` (a **Plausibility emitter (D14)** note after the
  `certify-before-limit` D12/G14 paragraph — emit `sr_plausibility.py --rundir <rundir>` once SR yields +
  exclusion exist and BEFORE the limit ships); `DIRECTORY.md` `_infrastructure/` row (tool description
  added, keeping `check_agent_surface.py` dirmap green).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/validation/sr_plausibility.py --selftest` (exit 0, 3 cases);
  `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_sr_plausibility.py" -q` (3 passed).

### CR-085 — `check_statistics`: fold an `sr_plausibility.json` implausible verdict into a hard statistics FAIL (D14/G16)
- **Date registered:** 2026-07-10
- **What:** `validate_run_state.py`'s `check_statistics` (statistics stage) now GATES on the
  `sr_plausibility.json` that CR-084's emitter produces, for single-point limit modes only (statistics
  artifact `exclusion.json` or `shape_fit.json` — scan mode's `scan.json` points are attested per-point
  elsewhere and are untouched). Two folds: (a) when the artifact stores both `excluded_obs` and
  `mu95_obs` (the `shape_fit.json` case), an `excluded_obs` that contradicts `mu95_obs < 1.0` is a hard
  FAIL; (b) a sibling `outputs/sr_plausibility.json` with `verdict == "implausible"` (or invalid JSON)
  is a hard FAIL, its `reasons[]` carried into the check msg. A `plausible` verdict is a PASS check; a
  MISSING `sr_plausibility.json` is INFO at required-level (advisory, never gating). New
  `_fixture_implausible_stats` (all-zero yields + runaway µ₉₅ → implausible) + selftest case 15; selftest
  count 14 → 15.
- **Why:** D14, L5b physics-lifecycle invariant. CR-084 EMITS the plausibility verdict but nothing gated
  on it, so an all-zero-yield run with a runaway µ₉₅ sentinel could still ship a vacuous "not excluded".
  This closes the analysis→statistics boundary: the moment the emitter records `implausible`, the
  statistics stage fails loud (exit 1) rather than passing a physically nonsensical limit downstream.
- **Where-embedded:** `docs/workflow/steps/07-exclude.md` (a **Plausibility FOLD (D14, enforced)** note after
  the emitter block — `check_statistics` folds `implausible` into a hard statistics FAIL; all-zero yields
  no longer ship a vacuous "not excluded").
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/validation/validate_run_state.py --selftest` (exit 0, 15 cases);
  `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py::test_implausible_sr_plausibility_fails_statistics" -q` (1 passed).

### CR-086 — `inv_outputs_in_tree`: primary compute evidence must resolve in-tree (N2/G23)
- **Date registered:** 2026-07-10
- **What:** `validate_run_state.py` gains a new cross-stage invariant `outputs-in-tree` (registered on
  the `generation` stage) plus a `_path_is_within(child_real, parent_real)` helper. It fires once a run
  has any generation output on disk OR a `scan_manifest.json`, and hard-FAILs when a generation hit's
  realpath, or a `scan_manifest.json` point's `run_dir` (+ any on-disk `output/exclusion.json` /
  `output/sr_yields.json` / `logs/STATUS.txt` under it), resolves OUTSIDE both the run dir and the repo
  tree (`result_pack._repo_root`) — the `/tmp` / `/private/tmp` / session-scratchpad class. Absolute and
  repo-relative point `run_dir`s both resolve correctly (repo-relative against the repo root). New
  `_fixture_scan_output_in_tmp` (a scan whose `p2` point `run_dir` is `/tmp/rogue_scan_point_p2`) +
  selftest case 16; selftest count 15 → 16.
- **Why:** N2, L5b physics-lifecycle invariant. A scan point (or a generation output) whose evidence lives
  under `/tmp` or a session scratchpad is invisible to `verify_pack.py`, `directory-keeper`, and
  `.gitignore` — all of which key on the run dir — so a limit assembled from it rests on evidence no gate
  can trace and no export can carry, and the path vanishes when the temp dir is reaped. This fails loud
  (exit 1) the moment such an out-of-tree pointer appears in the manifest.
- **Where-embedded:** `docs/workflow/steps/08-scan.md` (a **Keep every point's evidence IN-TREE (N2/G23)** note
  after the smoke-rung/`ladder-order` paragraph — point each `run_dir` at a `trial-runs/` sibling, never a
  temp dir; the `outputs-in-tree` invariant hard-FAILs otherwise).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/validation/validate_run_state.py --selftest` (exit 0, 16 cases);
  `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py::test_outputs_in_tree_fails_on_tmp_point" -q` (1 passed).

### CR-087 — `inv_producer_complete`: the MadGraph→LHE producer barrier (N4/G25)
- **Date registered:** 2026-07-10
- **What:** `validate_run_state.py` gains a new cross-stage invariant `producer-complete` (registered on
  the `generation` stage) plus two helpers — `locate_lhe_gz(rundir)` (first `*.lhe.gz` under the rundir,
  walking INTO `Events/`) and `lhe_producer_complete(rundir, lhe_path) -> (ok, reason)` — and a new fact
  `lhe_gz_path`. The invariant fires once an `.lhe.gz` is on disk and hard-FAILs when it is not a COMPLETE
  MadGraph product: no terminal `Cross-section :` line in any `logs/*.log` (producer still running), a
  gzip that does not decompress to EOF (`OSError`/`EOFError`/`BadGzipFile` — truncated mid-write), or a
  banner `nevents` that does not equal the counted `<event>` records. No `.lhe.gz` on disk
  (consumed+cleaned, or not a generation run) → PASS (nothing to barrier). New `_fixture_lhe_mid_write`
  (banner nevents=3 but only 2 `<event>` records, with a complete `Cross-section :` log) + selftest case
  17; selftest count 16 → 17.
- **Why:** N4, L5b physics-lifecycle invariant. A downstream stage that showers a half-written LHE —
  because the producer was still running, the gzip was truncated, or the file was grabbed mid-write
  (the "7031 not 10000 events" class) — silently loses events (exit 0, plausible-but-wrong yields) with
  no gate catching it. This fails loud (exit 1) the moment an incomplete `.lhe.gz` sits where a consumer
  would read it.
- **Where-embedded:** `docs/workflow/steps/03-generate.md` (a **Producer barrier — don't consume a mid-write
  LHE (N4/G25)** note after the pre-shower guard, before the shower step) and `.claude/rules/madgraph-pythia.md`
  (a "Never consume a mid-write `.lhe.gz`" idiom under Invocation idioms) — both name the three completeness
  checks and the `producer-complete` invariant that enforces them.
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/validation/validate_run_state.py --selftest` (exit 0, 17 cases);
  `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py::test_producer_barrier_fails_on_event_count_mismatch" -q` (1 passed).

### CR-088 — `verify_provenance_lifecycle`: `--verify-provenance` rejects a hand-written required lifecycle artifact (G19, part 1)
- **Date registered:** 2026-07-10
- **What:** `validate_run_state.py` gains `verify_provenance_lifecycle(rundir, contract, facts) -> list[str]`
  plus a `LIFECYCLE_REQUIRED_PROVENANCE` registry `((display, expected_generator, finder, input_rels), …)`
  seeded with `sr_plausibility.json` (expected generator `sr_plausibility.py`), and two helpers —
  `_canonical_bytes(obj)` and `recompute_input_fingerprint(rundir, input_rels)` (a sha256 over the
  canonical JSON of the declared inputs in fixed order — the same plausibility-domain canonicalization
  `sr_plausibility.compute_input_fingerprint` uses, deliberately NOT `provenance.py`'s p1 fingerprint,
  D-7). The function rejects a REQUIRED lifecycle artifact whose `generated_by` is absent/empty/hand-written
  (`HANDWRITTEN_GENERATORS = {"", "hand-written", "handwritten", "manual", "human"}`) or `!=` its expected
  generator. Wired into the Phase-1 `--verify-provenance` branch of `main` (CR-057): the branch now also
  runs the lifecycle check, prints each violation `PROVENANCE FAIL: …` to stderr, and returns
  `1 if (lifecycle_violations or pv["exit"] == 1) else 0`. New inline selftest case 18 (a hand-written
  `sr_plausibility.json` with no `generated_by` is rejected); selftest count 17 → 18. The
  `recompute_input_fingerprint` helper is staged for Task 4.9's input_fingerprint-recompute branch
  (marked insertion point inside the function).
- **Why:** G19 / "provenance, not presence". `sr_plausibility.json` is a required analysis→statistics
  lifecycle artifact whose implausible verdict hard-FAILs statistics (CR-085/D14). Presence-only gates let
  an agent backfill a `{"verdict": "plausible"}` by hand to clear the gate, defeating the check. This fails
  loud the moment a required lifecycle artifact was not actually PRODUCED by its tool.
- **Where-embedded:** `docs/workflow/checklists/verification-panel.md` (a Tier A checkbox running
  `validate_run_state.py --rundir <rundir> --verify-provenance` and naming the hand-written/backfilled
  rejection that closes the loophole); the mode is already invoked in `docs/workflow/steps/09-verify.md`.
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/validation/validate_run_state.py --selftest` (exit 0, 18 cases);
  `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py::test_verify_provenance_rejects_handwritten_artifact" -q` (1 passed).

### CR-089 — `verify_provenance_lifecycle`: `--verify-provenance` rejects a required artifact whose `input_fingerprint` mismatches a recompute (G19, part 2)
- **Date registered:** 2026-07-10
- **What:** `verify_provenance_lifecycle` in `validate_run_state.py` gains the `input_fingerprint`-recompute
  branch at the marked insertion point (staged by CR-088): for each `LIFECYCLE_REQUIRED_PROVENANCE` entry
  it now calls `recompute_input_fingerprint(rundir, input_rels)` over the artifact's declared inputs
  (`outputs/sr_yields.json` + `outputs/pyhf_exclusion/exclusion.json`) and appends an `input_fingerprint
  mismatch` violation when the stored fingerprint is absent/non-str or `!=` the recompute (inputs unreadable
  → a distinct "cannot verify" violation). Because the recompute uses the identical p4a-local
  canonicalization `sr_plausibility.compute_input_fingerprint` emits (sha256 over canonical JSON in fixed
  order, `\x00`-separated; deliberately NOT `provenance.py`'s p1 fingerprint, D-7), a faithfully-emitted
  `sr_plausibility.json` matches (clean) and a stale one left in place after its inputs changed does not.
  New inline selftest case 19 (a faithful artifact is accepted, then a tampered input is rejected); selftest
  count 18 → 19.
- **Why:** G19 / "provenance, not presence", part 2. CR-088 closed the hand-written path (`generated_by`);
  this closes the STALE-artifact path — a genuine `sr_plausibility.json` kept in place after the yields/limit
  underneath it moved carries a verdict that no longer describes the current inputs, yet a presence-or-
  `generated_by`-only gate would still pass it and certify a physics claim the tool never made about THESE
  inputs. Fails loud the moment a required lifecycle artifact's inputs changed after emission (a backfill).
- **Where-embedded:** `docs/workflow/checklists/verification-panel.md` (the `--verify-provenance` Tier-A checkbox
  now also names the `input_fingerprint` recompute and the stale-after-inputs-changed rejection);
  `docs/reference/failure-modes.md` D4 (backfilled/stale required artifact → caught by `--verify-provenance`
  → guard in `verify_provenance_lifecycle`).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/validation/validate_run_state.py --selftest && python3 src/ravel/validation/sr_plausibility.py --selftest` (both exit 0; validate_run_state prints 19 cases);
  `cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py" "$REPO/tests/unit/test_sr_plausibility.py" "$REPO/tests/unit/test_validate_run_state.py" -q` (task's own `test_verify_provenance_rejects_fingerprint_mismatch` + lifecycle/sr_plausibility suites pass; one PRE-EXISTING unrelated failure `test_validate_run_state.py::test_scan_aggregator_without_sibling_intermediates_passes_generation_and_analysis` from CR-086's `inv_outputs_in_tree` N2 gate vs a tmp-sibling `run_dir` fixture, present on HEAD before this CR).

### CR-090 — Phase 4 close-out: scan-aggregator test fixture uses in-tree per-point run_dirs
- **Date registered:** 2026-07-10
- **What:** `test_scan_aggregator_without_sibling_intermediates` put per-point `run_dir` at siblings under the pytest temp dir; since a temp dir has no repo root, `inv_outputs_in_tree` (N2/G23) correctly read them as out-of-tree and FAILed. Fixture now references in-tree per-point dirs under the rundir (still non-existent, preserving the "cleaned per-point dirs" intent).
- **Why:** the invariant is correct (real scans keep per-point dirs under `trial-runs/` = repo tree; only /tmp-scratchpad evidence FAILs); the fixture was an artifact of the no-repo temp context. Caught at the Phase-4 boundary integration check.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state.py" -q` (21 passed); `python3 src/ravel/validation/validate_run_state.py --selftest` (19 cases)

### CR-091 — `resource_census.py --debug recipe-search` + offline `--selftest` (D8/G8, tool+model+symptom recipe search)
- **Date registered:** 2026-07-10
- **What:** `resource_census.py` gains a `--debug recipe-search` mode and an offline `--selftest`.
  New pure/offline helpers: `_resolve_timestamp(cli=None)` (env `$RESOURCE_CENSUS_UTC` else `""`, never
  `datetime.now()` — reproducible artifacts), `_fingerprint(*parts)` (sha256 over `\x00`-separated parts),
  `_count_recipe_hits(s)`, and `build_recipe_search_record(tool, model, symptom, searches, timestamp="")`
  which assembles `recipe_search.json` (`schema_version=1`, `generated_by="resource_census.py --debug
  recipe-search"`, `input_fingerprint`, `mode="recipe-search"`, `query{tool,model,symptom}`, `searches`,
  `searches_ok`, `n_hits`, `co_primary=true`). `_recipe_search_main(argv)` runs the CLI — reuses the
  existing `rung_github` code-search rung + an INSPIRE literature query, writes `<rundir>/inputs/
  recipe_search.json`, exit 2 on a bad `--debug` value, exit 3 when EVERY search failed (a network finding,
  NOT "no recipe exists"). `main()` → `main(argv=None)` returning an int on every path (SHARED-CONVENTIONS
  §B): the census-body `sys.exit(3)` becomes `return 3`, a trailing `return 0` is appended, and
  `--selftest`/`--debug` dispatch BEFORE the `--inspire`-required parse (§J pre-parse pattern, shape_fit);
  entrypoint is now `sys.exit(main())`.
- **Why:** D8/G8 — a diagnosed generator/detector-model failure (undecayed sparticles → empty SR, a card
  that won't build, a merge that vetoes every event) is a search target, not just a debugging session; the
  published fix (card, run config, recast repo, thesis appendix) is often already online. Searching it
  CO-PRIMARY (not last) is the resolve; the exit-3 loud-fail keeps a down network from being read as "no
  recipe exists".
- **Where-embedded:** `.claude/skills/resource-sweep/SKILL.md` ("When a STAGE FAILS: `--debug
  recipe-search`" section + the `--selftest` self-check), referenced from `docs/workflow/steps/09-verify.md`
  (the FAIL-verdict path fires the recipe search before improvising a stage-level fix).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/resource_census.py --selftest` (exit 0, `PASS (3 case(s))`);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_resource_census_gates.py" -q` (3 passed).

### CR-092 — `resource_census.py --assert-recipe-search` D8 close-block gate (G8) + its `stop_dispatch.py` Stop-branch
- **Date registered:** 2026-07-10
- **What:** `resource_census.py` gains an `--assert-recipe-search --rundir <d> [--json]` CLI mode and the
  pure predicate `assert_recipe_search(rundir) -> (exit_code, messages)`: it reads
  `run_state.open_failure_records`, resolves each referenced `*.failure.json`, and classifies a
  generator-model failure via `_is_generator_model_failure` (record `failure_class ==
  "tool_generator_model"`, or its `stage` in `GEN_STAGES = {madgraph, pythia, shower, lhe_check,
  generate, generation}`, else a filename-keyword fallback). Exit 1 iff an OPEN generator-model failure
  exists and `inputs/recipe_search.json` is absent; exit 0 otherwise (present, or none open); exit 2 on a
  bad `--rundir`. Helper `_load_run_state` reads `run_state.json` fail-soft. `main()` dispatches
  `--assert-recipe-search` BEFORE the `--inspire`-required parse (alongside `--selftest`/`--debug`);
  `_selftest` gains cases 4+5 (open gen-model failure w/o recipe → exit 1; recipe present → exit 0), count
  `3 → 5`. **Non-invariant wiring (D-4/G8):** `stop_dispatch.py` gains `branch_recipe_search` (shells
  `resource_census.py --assert-recipe-search --rundir`; exit 1 → BLOCK exit 2, token `G8-RECIPE-SEARCH:`;
  fail-open on a predicate crash) appended to `BRANCHES` as `("recipe-search", …)`, plus
  `_selftest_recipe_search` in `selftest()`. G8 is NON-invariant, so it rides its own Stop-branch, NOT the
  D18 umbrella (`branch_d18`).
- **Why:** D8 RESOLVE / "fail-loud + block, not advise". A diagnosed generator-model failure (undecayed
  sparticles → empty SR, a card that won't build, a merge that vetoes every event) cannot be closed on
  local diagnosis alone — the published fix (card, run config, recast repo, thesis appendix) is often
  already online, so the CO-PRIMARY external search (`--debug recipe-search`, CR-091) must have run first.
  This gate makes closing such a failure without `inputs/recipe_search.json` a hard block at turn-end,
  closing the "closed on local diagnosis, external recipe never searched" hole.
- **Where-embedded:** `docs/workflow/steps/09-verify.md` (Tier-A "Recipe-search close-block (G8)" bullet + the
  D18-umbrella note that the sibling `branch_recipe_search` shells the command at turn-end; fallback =
  the `stage-recovery` skill / this step-doc).
- **Status:** EMBEDDED.
- **Verify:** `python3 src/ravel/workflow/resource_census.py --selftest && python3 src/ravel/workflow/stop_dispatch.py --selftest` (both exit 0; resource_census prints `PASS (5 case(s))`, stop_dispatch's `PASS` now includes the `recipe-search` branch case);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_resource_census_gates.py" -q` (5 passed, incl. `test_assert_recipe_search_close_block` + `test_recipe_search_stop_branch`).

### CR-093 — `stage-recovery` skill: the D8-RESOLVE recovery procedure (recipe-search CO-PRIMARY on a stage failure, G8)
- **Date registered:** 2026-07-10
- **What:** new skill `.claude/skills/stage-recovery/SKILL.md` (+ its generated `.agents/skills/` mirror via
  `sync_skills.py`). It is the operating procedure that consumes the CR-091/CR-092 engine: on ANY stage
  failure (nonzero rc, empty/degenerate output, a `stage_supervisor` `logs/*.failure.json`) it (1) records
  the failure via `workflow_state.py record --kind failure` into `run_state.open_failure_records`, (2) runs
  **Branch A local diagnosis** (judgment-protocols discrepancy-decomposition / anchor-chain; the known
  SLHA/`MSOFT`/`xqcut`/env traps) AND **Branch B external recipe search CO-PRIMARY** — `resource_census.py
  --debug recipe-search --tool <t> --model <m> --symptom <s> --rundir <d>` — at the SAME time, both
  first-class, never search-last, and (3) enforces the close-block: a `tool_generator_model` failure may not
  be closed until `inputs/recipe_search.json` exists (`resource_census.py --assert-recipe-search` exit 0,
  which the Stop-dispatcher `branch_recipe_search` runs at turn-end). Skill count 15 → 16.
- **Why:** D8/G8 — the CR-091 fix-finder and CR-092 close-block gate need a named procedure that fires them
  at the point of failure; without it the external fix-search stays ordered LAST (or never) while the run
  improvises around "the tool is broken". The skill makes diagnose-locally + search-externally CO-PRIMARY
  the default recovery move.
- **Where-embedded:** CLAUDE.md skills roster (16; added `stage-recovery` + the previously-unlisted
  `resource-sweep`); `DIRECTORY.md` `.claude/skills/` row; referenced from `docs/workflow/steps/03-generate.md`
  (generation-failure bullet) and `docs/workflow/steps/08-scan.md` (Stage-hang CATCH clear-it clause).
- **Status:** EMBEDDED.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stage_recovery_skill.py" -q`
  (1 passed); `python3 scripts/maintenance/sync_skills.py && python3 src/ravel/validation/check_agent_surface.py`
  (exit 0; `skills`/`mirror`/`dirmap`/`refs`/`hygiene` PASS).

### CR-094 — `resource_census.py --assert-pre-generate` D7 PREVENT recipe gate (G9)
- **Date registered:** 2026-07-10
- **What:** `resource_census.py` gains an `--assert-pre-generate --rundir <d> [--json]` CLI mode and the
  pure predicate `assert_pre_generate(rundir) -> (exit_code, messages)`: it loads the task contract
  (`_load_contract` tries `inputs/task_contract.json` then `task_contract.json`, fail-soft) and reads
  `targets.model`. Conservative gate — no declared `targets.model` → exit 0 (`N/A`, never a false block on
  SM/unknown). With a declared BSM/HV model it exits 1 iff NONE of `RECIPE_ARTIFACTS =
  ("inputs/recipe_search.json", "inputs/generation_recipe.json", "inputs/model_recipe.json")` is a file
  present under the rundir, else exit 0; exit 2 on a bad `--rundir`. `main()` dispatches
  `--assert-pre-generate` BEFORE the `--inspire`-required parse (alongside `--selftest`/`--debug`/
  `--assert-recipe-search`). `_selftest` gains cases 6+7 (declared model w/o recipe → exit 1; recipe added →
  exit 0), count `5 → 7`.
- **Why:** D7 PREVENT / "fail-loud + block, not advise". Launching MadGraph on a declared BSM/HV model
  without first FETCHING that model's generation recipe (UFO / restrict-card / process syntax) is how a run
  improvises a wrong or unbuildable card and burns compute — the recipe is usually already online
  (`--debug recipe-search`, CR-091). This predicate makes a declared model with no fetched recipe a hard
  block BEFORE generation, closing the "generated first, looked for the recipe later" hole. G9 is the
  PREVENT sibling to G8's close-block (CR-092).
- **Where-embedded:** deferred to the G9 step-doc paragraph in the follow-on doc task (workflow gate
  paragraph + Stop-branch wiring land there); this CR lands the code + predicate + `--selftest` cases.
- **Status:** CODE LANDED — doc embed pending in the G9 gate-paragraph task.
- **Verify:** `python3 src/ravel/workflow/resource_census.py --selftest` (exit 0, `PASS (7 case(s))`);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_resource_census_gates.py" -q` (7 passed, incl. `test_assert_pre_generate` + `test_assert_pre_generate_no_model_passes`).

### CR-095 — pre-generate recipe gate: `03-generate.md` step-doc paragraph + `pre-generate-guard.sh` PostToolUse hook (D7 PREVENT / G9)
- **Date registered:** 2026-07-10
- **What:** the G9 embed + backstop for CR-094's `--assert-pre-generate` predicate. (1) `resource_census.py`
  gains a `--pre-generate-hook --command <cmd> [--project-dir <d>]` mode (`_pre_generate_hook_main`,
  dispatched in `main` before the `--inspire`-required parse): it returns 0 unless the command matches
  `GEN_LAUNCH_RE` (`generate_events`\|`mg5_aMC`\|`mg5`\|`pythia_shower`\|`run-pipeline-native.sh`), resolves
  the run dir from the command via `_resolve_rundir_from_command` (a `trial-runs/…` token walked up to the
  dir carrying `inputs/task_contract.json`), and returns **2** (PostToolUse block) iff
  `assert_pre_generate(rundir)` == 1 (declared BSM/HV model, no fetched recipe). Unresolvable run dir or a
  present recipe → 0. `_selftest` gains case 8 (hook blocks a `run-pipeline-native.sh` launch w/o recipe → 2,
  no-ops on `ls -la` → 0), count `7 → 8`. (2) `.claude/hooks/pre-generate-guard.sh` — a `Bash`-matcher
  PostToolUse hook that extracts `tool_input.command` from stdin JSON (inline python3) and calls the hook
  mode, re-exiting its status. (3) `steps/03-generate.md` gains the `[judgment — script-assisted:
  resource_census.py]` **Pre-generate recipe gate** paragraph (the authoritative half) before the hard-process
  list item. (4) `.claude/settings.json` (worktree) gains the pre-generate-guard as a THIRD `PostToolUse`
  block via the D-1 idempotent merge (`setdefault` array + presence-checked append) — coexisting with Phase-1's
  observer + Phase-3's deviations-guard, PreToolUse card-guard untouched.
- **Why:** D7 PREVENT / "fail-loud + block, not advise" + "observable before enforceable". CR-094 landed the
  predicate; the workflow IS the product, so the gate is not done until it is embedded in the step-doc (the
  authoritative half) AND backstopped at moment-of-launch by a hook that fires on a raw
  `mg5`/`run-pipeline-native.sh` command the step-doc gate could be skipped past. The Bash matcher + step-doc
  paragraph make "generated first, looked for the recipe later" a hard block.
- **Where-embedded:** `docs/workflow/steps/03-generate.md` (the gate paragraph); `.claude/settings.json` (the merged
  PostToolUse block); `DIRECTORY.md` (the `pre-generate-guard.sh` row). Closes CR-094's deferred doc-embed.
- **Status:** LANDED.
- **Verify:** `python3 src/ravel/workflow/resource_census.py --selftest` (exit 0, `PASS (8 case(s))`);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_pre_generate_guard.py" "$REPO/tests/unit/test_settings_wiring.py" "$REPO/tests/unit/test_deviations_guard.py" -q` (green — the pre-generate-guard, the observer, and the deviations-guard all coexist in `PostToolUse`).

### CR-096 — `preflight_watcher.py --arm` — completion-watcher FIRE-COMMAND preflight (N3/G24)
- **Date registered:** 2026-07-10
- **What:** new stdlib-only tool `src/ravel/workflow/preflight_watcher.py`. Before a backgrounded
  *completion-watcher* (a job that sleeps until SCAN-DONE then FIRES an assembly/aggregation command) is
  armed, `--arm --rundir <d> --name <w> --fire "<cmd>" [--target <script>]` exercises its fire command:
  (1) `probe_fire_command(fire, target) -> (verdict, checks)` runs `bash -n -c <fire>` for a **syntax**
  check, then an **arity** probe — `_count_positionals` counts the positional args the fire passes (skipping
  the interpreter/target tokens and `-`-flags) vs `_target_required_arity`, the target's declared
  required-positional count (an argparse `--help` usage parse for a `.py` target, a `$N` positional scan
  for a shell target; `None`/undetectable → INFO, syntax-only). `verdict = "fail"` if either check FAILs.
  (2) `arm_watcher` writes `<rundir>/logs/<name>.preflight.json` (`schema_version=1`, `generated_by`,
  `input_fingerprint`, `watcher`, `fire`, `target`, `checks`, `verdict`). (3) CLI `--arm` exits **0 iff
  verdict==pass else 1** and prints `ARMED: name=<w> preflight=logs/<w>.preflight.json verdict=<v>` to
  stderr (the DRIVE step records the armed watcher into `run_state.armed_watchers` via `workflow_state.py`).
  `--selftest` = 5 cases (arity-detect=5; 3-arg→fail; 5-arg→pass; broken `bash -n` syntax→fail; `--arm` bad
  fire → exit 1 + preflight.json written). **Bug fixed while transcribing the drafted engine:** the
  usage-line continuation regex used `\n\s+\S` — `\s` matches newlines, so it jumped the blank line after
  the usage line and swallowed the whole `--help` body (counting 17 word-tokens, not the 5 real
  positionals); constrained to `\n[ \t]+\S` (horizontal whitespace only) so it stops at the blank line while
  still capturing genuinely wrapped usage continuations.
- **Why:** N3/G24 — a backgrounded completion-watcher is never smoke-tested, so a fire command that is a
  3-arg call to a 5-arg script crashes hours later at SCAN-DONE, invisibly (nothing ever assembles and no
  watchdog fires). "Fail-loud + block, not advise": a fire that fails the preflight never gets armed
  (nonzero exit), and the refusal + evidence land in `logs/<name>.preflight.json` ("provenance, not
  presence"). Cheap, read-only except that one artifact, no new dependency.
- **Where-embedded:** `docs/workflow/steps/08-scan.md` (the DRIVE Watcher-preflight ARM (N3/G24) paragraph);
  `DIRECTORY.md` (the `_infrastructure/` software-track row). Surface coherence re-checked with
  `check_agent_surface.py`.
- **Status:** LANDED.
- **Verify:** `python3 src/ravel/workflow/preflight_watcher.py --selftest` (exit 0,
  `preflight_watcher selftest: PASS (5 case(s))`);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_preflight_watcher.py" -q` (2 passed).

### CR-097 — `preflight_watcher.py --assert-all` — the armed-watcher Stop-branch (N3/G24) + its `stop_dispatch.py` Stop-branch
- **Date registered:** 2026-07-10
- **What:** turn-end enforcement for the CR-096 completion-watcher preflight. (1) `preflight_watcher.py`
  gains `--assert-all --rundir <d> [--json]` → `assert_all_watchers(rundir) -> list[str]` walks
  `run_state.armed_watchers` and returns a problem per entry whose `preflight` pointer is missing, whose
  artifact is absent/unreadable on disk, or whose `verdict != "pass"`; the CLI exits **1 iff any armed
  watcher lacks a passing preflight artifact**, else 0 (exit 2 = usage/not-a-dir). `--selftest` grows to 7
  cases (5: a passing preflight → clean; 6: a missing preflight → 1 problem). (2) `stop_dispatch.py` gains
  `branch_armed_watcher`, appended to `BRANCHES` after `recipe-search`: at the Stop hook it shells
  `preflight_watcher.py --assert-all --rundir <rundir>` and, on exit 1, BLOCKs turn-end (exit 2) with the
  token `G24-ARMED-WATCHER:` + the failing tail + the arm-before-backgrounding remedy; it fail-opens on a
  predicate crash (a hook never wedges the live agent — the DRIVE step-doc fallback covers it). A
  `_selftest_armed_watcher` case (block on a missing ghost preflight, pass when no watcher is armed) joins
  `stop_dispatch selftest`.
- **Why:** N3/G24 — CR-096 preflights a watcher's fire command AT ARM TIME, but nothing forced the agent to
  arm it; an un-preflighted completion-watcher could still be backgrounded and crash invisibly at SCAN-DONE.
  "Observable before enforceable": the DRIVE step records each armed watcher into `run_state.armed_watchers`,
  and this gate makes that record enforceable at turn-end. "Fail-loud + block, not advise": the Stop hook
  BLOCKs (exit 2), it does not WARN. G24 is **non-invariant** (it is not a per-run structural invariant of
  `validate_run_state.py`), so it is wired as its own `stop_dispatch.py` branch rather than under the D18
  umbrella (mirrors the G8 `recipe-search` branch, CR-092).
- **Where-embedded:** `docs/workflow/steps/08-scan.md` (the DRIVE Watcher-preflight ARM (N3/G24) paragraph now
  carries the `--assert-all` turn-end enforcement + the `branch_armed_watcher` Stop-branch). Surface
  coherence re-checked with `check_agent_surface.py`.
- **Status:** LANDED.
- **Verify:** `python3 src/ravel/workflow/preflight_watcher.py --selftest && python3 src/ravel/workflow/stop_dispatch.py --selftest`
  (exit 0; `preflight_watcher selftest: PASS (7 case(s))`; `stop_dispatch selftest: PASS`);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_preflight_watcher.py" -q` (5 passed).

### CR-098 — `verify_pack.py` open-defect gate (N5/G26) + its `stop_dispatch.py` DELIVERY-only Stop-branch
- **Date registered:** 2026-07-10
- **What:** the pre-delivery comparison/check-in gate now FAILs on a helper flagged with an OPEN defect
  note. (1) `verify_pack.py` gains `check_open_defect(rep, rundir)` — wired in `main` right after
  `file_index` (so it fires even when the run carries only `run_state.json`) — which reads
  `run_state.open_defect_notes` (SHARED-CONVENTIONS §C: `[{"helper","note","status":"open|fixed"}]`) and
  appends a `FAIL` for every `status=="open"` entry (a missing/unreadable run_state.json is an INFO/WARN
  skip, not a FAIL). A new `--selftest` intercept + `_verify_pack_selftest` exercises 2 cases (1 open
  note → exit 1; the note flipped to fixed → exit 0) and prints `verify_pack selftest: PASS (2 case(s))`.
  (2) `stop_dispatch.py` gains `branch_open_defect`, appended to `BRANCHES` after `armed-watcher`: at a
  Stop hook on a DELIVERY turn (`ctx['is_delivery']`) it shells `verify_pack.py <rundir>` and, on exit 1
  with `open defect note` in the output, BLOCKs turn-end (exit 2) with the token `G26-OPEN-DEFECT:` + the
  resolve/substitute remedy; it is gated on `is_delivery` so ordinary mid-run turns are never blocked and
  fail-opens on a predicate crash. A `_selftest_open_defect` case (delivery→block, non-delivery→pass,
  fixed→pass) joins `stop_dispatch selftest`.
- **Why:** N5/G26 — a number produced by a helper known to be defective (e.g. `read_yoda.py` reporting
  A×e as 956%) must not feed a comparison or a check-in until the defect is resolved. "Observable before
  enforceable": `postmortem-capture` records a defective helper as an OPEN entry in
  `run_state.open_defect_notes`, and this gate makes that record enforceable at the pre-delivery panel and
  at the delivery turn-end. "Fail-loud + block, not advise": both the panel gate (exit 1) and the Stop
  hook (exit 2) BLOCK, they do not WARN. G26 is **non-invariant** (not a per-run structural invariant of
  `validate_run_state.py`), so — like the G8 recipe-search (CR-092) and G24 armed-watcher (CR-097)
  branches — it is wired as its own `stop_dispatch.py` branch rather than under the D18 umbrella, and
  `branch_d18` does not cover it.
- **Where-embedded:** `docs/workflow/steps/09-verify.md` (Tier A gains the N5/G26 open-defect close-block bullet,
  the `verify_pack.py` block comment lists the open-note check, and the D18 umbrella paragraph names the
  `branch_open_defect` sibling Stop-branch + its FALLBACK), `docs/workflow/checklists/verification-panel.md`
  (Tier A "No OPEN defect note (N5/G26)" checkbox), and the `postmortem-capture` skill (record a defective
  helper as an OPEN `run_state.open_defect_notes` entry). Surface coherence re-checked with
  `check_agent_surface.py`.
- **Status:** LANDED.
- **Verify:** `python3 src/ravel/validation/verify_pack.py --selftest && python3 src/ravel/workflow/stop_dispatch.py --selftest`
  (exit 0; `verify_pack selftest: PASS (2 case(s))`; `stop_dispatch selftest: PASS`);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_verify_pack_open_defect.py" -q` (4 passed).

### CR-099 — `validate_checkin.py` CHECK-IN schema validator (G18)
- **Date registered:** 2026-07-10 (spine-hardening Phase 4b Task 4.18).
- **What:** a new stdlib-only validator `src/ravel/validation/validate_checkin.py` that gates an
  emitted CHECK-IN artifact against `docs/workflow/checklists/check-ins.md`, mirroring
  `validate_task_contract.py` (same public `validate(obj) -> list[str]` contract returning a list of
  error strings, plus `SCHEMA`/`--schema`/`--selftest`/single-argument CLI with exit 0 valid / 1 invalid
  + itemized errors). It encodes each check-in's required SECTIONS as assertions keyed on `kind`:
  `checkin1` requires the SEVEN lettered sections (`i, i-b, ii, iii, iv, v, vi`), the `F<n>`-numbered
  flags in §(v) (each id matching `^F\d+$`, at least one present), the THREE response modes in §(vi),
  and the EARLY-VERIFICATION waypoint in §(iii); `checkin2` requires `waypoint`+`expectation`+the ask's
  two named options `GO` and `ADJUST`; `deck` requires the 8 numbered sections incl. §7 `panel_verdict`
  (the step-9 verification-panel verdict, carried verbatim). A missing required section is a FAIL, not a
  WARN. `--selftest` exercises 3 good + 5 bad fixtures and prints
  `validate_checkin selftest: PASS (3 good + 5 bad)`.
- **Why:** G18 — the physicist-facing check-ins are the only interface the physicist sees, yet nothing
  mechanically asserted a check-in carried its required sections before it was sent; a dropped §(i-b)
  census, a missing waypoint, or a deck without the verbatim panel verdict could ship silently. This is
  the check-in analog of the `validate_task_contract.py` schema gate — an emitted machine artifact
  (`inputs/checkin{1,2,_deck}.json`) is validated before the message goes out.
- **Where-embedded:** `docs/workflow/checklists/check-ins.md` (the closing "Emit + validate (the machine gate,
  G18)" composing rule — emit each check-in as its `inputs/checkin{1,2,_deck}.json` artifact and run the
  validator before sending); the `physicist-intake` skill (step 4 — emit + validate `inputs/checkin1.json`
  before sending CHECK-IN 1) and the `verification-panel` skill (emit + validate the deck's
  `inputs/checkin_deck.json` with its verbatim §7 panel verdict before delivery); `DIRECTORY.md` software
  row (`_infrastructure/`). Skill mirror re-synced (`sync_skills.py`) and surface coherence re-checked
  with `check_agent_surface.py` (all PASS).
- **Status:** LANDED.
- **Verify:** `python3 src/ravel/validation/validate_checkin.py --selftest`
  (exit 0; `validate_checkin selftest: PASS (3 good + 5 bad)`);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_checkin.py" -q` (5 passed).

### CR-100 — `install_git_hooks.sh` git pre-commit surface-gate hook (D16/G20)
- **Date registered:** 2026-07-10 (spine-hardening Phase 4b Task 4.19).
- **What:** a new tracked installer `scripts/maintenance/install-git-hooks.sh` that writes an
  executable `pre-commit` hook into the git hooks dir resolved by `git rev-parse --git-path hooks`. The
  installed hook runs the read-only `check_agent_surface.py` and propagates its exit code, so a commit
  that would leave the agent surface inconsistent (dead ref / missing `DIRECTORY.md` row / unmirrored
  skill / stale readiness or step-count claim) is BLOCKED at commit time with a stderr reason, not merely
  advised by the manual `embed-and-commit` §2 step. The installer is stdlib/bash-only (`set -uo pipefail`,
  no `set -e` so it captures and forwards the check's exit code), handles both the worktree case (where
  `git rev-parse --git-path hooks` returns the absolute shared common `.git/hooks`) and the plain-clone
  relative-path case, and is idempotent (re-running overwrites the managed hook). The installed
  `pre-commit` itself is UNTRACKED by design — it lives in the git common dir, shared across worktrees —
  so the tracked installer is the reproducible source; run it once per clone/worktree.
- **Arch-robustness (a drafted-not-run fix):** `check_agent_surface.py` is not truly pure-stdlib in its
  transitive selftest execution — its `statefresh` check runs `audit.py`'s R9, which runs
  `shape_fit.py --selftest`, which imports numpy. On this Apple-Silicon host the system `git`
  (`/usr/local/git`, an x86_64 binary) spawns the hook — and its `python3` — under Rosetta, where the
  native arm64 numpy `.so` cannot load (`incompatible architecture (have 'arm64', need 'x86_64')`); the
  naive hook from the brief therefore FALSE-FAILed the gate on an arch mismatch (R9 0.64→0.57 →
  `statefresh` FAIL) and would have blocked EVERY commit, incl. the shared main tree's live run — the
  "a cries-wolf gate gets disabled, worse than no gate" failure the constraints warn about. The installed
  hook re-runs the gate under `arch -arm64` when it detects a translated process on arm64 hardware
  (`uname -s == Darwin && sysctl.proc_translated == 1 && hw.optional.arm64 == 1 && arch present`); a no-op
  on native arm64 / Intel / Linux. So the hook blocks only on genuine surface drift, as the design intends.
- **Why:** D16/G20 — the surface gate existed only as a manual step an agent could forget, re-opening the
  A1-04/A1-05 drift class (a routing surface that 404s or contradicts itself). Making it a git pre-commit
  hook turns "run the gate before committing" from advice into enforcement ("fail-loud + block, not
  advise"): a surface-drifting commit cannot land. Because the hook only ever runs the read-only
  `check_agent_surface.py` (resolving `git rev-parse --show-toplevel` at commit time, so it checks
  whichever worktree is committing), it can block only on genuine surface drift.
- **Where-embedded:** the `embed-and-commit` skill §2 (the surface-gate bullet gains the "now ALSO a git
  pre-commit hook — install once per clone/worktree with `install_git_hooks.sh`" note); `DIRECTORY.md`
  software row (`_infrastructure/`, noting the `.git/hooks/pre-commit` it writes is untracked by design +
  shared across worktrees via the git common dir). Skill mirror re-synced (`sync_skills.py`) and surface
  coherence re-checked with `check_agent_surface.py` (all PASS).
- **Worktree caveat:** `git rev-parse --git-path hooks` resolves to the SHARED common `.git/hooks`, so the
  hook applies to every worktree/clone sharing that git dir; it only ever runs the read-only
  `check_agent_surface.py`, so it blocks only on genuine surface drift.
- **Status:** LANDED.
- **Verify:** `bash scripts/maintenance/install-git-hooks.sh` (exit 0; prints the installed hook
  path) and `python3 src/ravel/validation/check_agent_surface.py` (exit 0);
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_precommit_hook.py" -q` (2 passed).

### CR-101 — `spine_sim` run-simulation engine: the L6 per-gate verification board (G0a–G27)
- **Date registered:** 2026-07-10 (spine-hardening Phase 6 Task 6.1).
- **What:** a new tracked engine `tests/adversarial/run_suite.py` (stdlib-only, modeled on
  `scripts/verify_fixes.py`'s subprocess-board shape) plus its `tests/adversarial/cases/` seed dir.
  For every gate in the workflow-adherence spine (`EXPECTED_GATES` = G0a/G0b/G0c + G1..G27 = the 30
  rows spec §5 calls "~28") a sibling `cases/case_<GATE>.py` script SEEDS a throwaway fixture that trips
  the trigger and asserts the matching gate FIRES. The engine discovers those case scripts
  (`discover_cases`), runs each as a subprocess FROM THE REPO ROOT (`run_case`), and prints one board
  row per gate (`G13 | case_G13.py | PASS`). Case exit convention: 0 = gate FIRED (PASS) · 1 = gate did
  NOT fire (FAIL/regression) · 2 = fixture/setup error (ERROR). CLI: `--json` (machine board, same exit
  code), `--only G1,G2` (subset), `--require-all` (ALSO fail if any EXPECTED gate has no case file, via a
  MISSING row), `--cases DIR` (test hook), `--with-self-drive`, `--selftest` (fabricated PASS/FAIL/ERROR
  cases prove the aggregator). Exit 0 iff every run case is PASS/SKIP and (under `--require-all`) all 30
  are present.
- **Self-drive SKIP semantics:** a SELF-DRIVE gate (`SELF_DRIVE_GATES = {G21}`) attests the live
  clean-room artifact (`clean_room.py --live`, `SELF_DRIVE_ARTIFACT`). When that artifact is absent AND
  `--with-self-drive` was not passed it is reported SKIP (never sinks the board) so the default
  `make green` stays green; `make green-self-drive` produces the artifact and `--with-self-drive` forces
  the case to run and PASS — so the gate is never silently weakened, only deferred to the self-drive lane.
- **Why:** L6 of the spine — the gates built across Phases 0–5 each need a live, per-gate regression case
  that proves the gate FIRES on its trigger (not merely that its tool is on disk). A single board over
  `cases/case_<G>.py` turns "are all the gates still enforcing?" from a manual audit into one command,
  and `--require-all` makes an unwritten case a FAIL rather than a silent coverage hole. The family tasks
  (6.x) fill `cases/` one gate at a time; this task lands the aggregator + its `.gitkeep`ed seed dir.
- **Where-embedded:** `tests/adversarial/README.md` (one-paragraph orientation); `DIRECTORY.md`
  software rows for `tests/adversarial/` and `tests/adversarial/run_suite.py`. Case scripts and
  the `make green` / `make green-self-drive` targets land in the sibling 6.x family tasks.
- **Status:** LANDED (engine + selftest; `cases/` seeded empty for the family tasks).
- **Verify:** `python3 tests/adversarial/run_suite.py --selftest` (exit 0, prints
  `run_spine_sim selftest: PASS`) and
  `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_spine_sim.py" -q` (10 passed).

### CR-102 — `spine_sim/_case_lib.py` — the shared case toolkit (fixtures, hook/tool drivers, gate assertions)
- **Date registered:** 2026-07-10 (spine-hardening Phase 6 Task 6.2).
- **What:** a new tracked, stdlib-only module `tests/adversarial/_case_lib.py` that every
  `cases/case_<G>.py` imports so a gate case stays a tiny script. It provides: **fixtures** — `tempdir`
  (throwaway rundir), `write_json`/`write_text`, `write_contract(rd, **over)` (built from
  `validate_run_state._base_contract` and re-validated with `validate_task_contract.validate`, so the
  emitted `inputs/task_contract.json` always validates; it backfills a placeholder `cost_estimate` for
  `full`/`scan` plans, which `validate_task_contract` requires), and `write_run_state`; **drivers** —
  `run_validate(rd)` (runs `validate_run_state.py --json` as a subprocess and returns `(res, rc)`;
  raises `CaseSetupError` on exit 2/3 or non-JSON) with `invariant_status`/`stage_status` locators,
  `run_tool`/`tool_path` (searches `trial-runs/_infrastructure` then `framework/`; absent tool →
  `CaseSetupError`), `drive_hook(hook_rel, stdin_obj)` (feeds a hook JSON on stdin with
  `CLAUDE_PROJECT_DIR` set), `drive_stop`, and the `HOOKS`/`STOP_TOKENS` relpath maps (a moved hook
  touches one line, not every case); **attestation** — `spike_check`, `attest`; **gate discipline** —
  `case_main` (wraps a case: `CaseSetupError`→exit 2 / `GateDidNotFire`→exit 1 / unexpected→2 /
  otherwise fired→0), `gate_fired(cond, msg)`, `assert_block(cp, token)`, and the two exceptions.
- **Why:** the 6.x family fills `cases/` one gate at a time; without a shared toolkit each case would
  re-implement fixture building and subprocess driving (the A1-05 parallel-source-of-truth drift). By
  building contracts through `_base_contract` and driving the REAL `validate_run_state.py` + the
  existing card-guard hook, the toolkit and its test are green independent of the still-unbuilt
  enforcement phases, so 6.2 lands before its sibling case tasks.
- **Where-embedded:** `tests/adversarial/README.md` (the "Case toolkit" paragraph); `DIRECTORY.md`
  software row for `tests/adversarial/_case_lib.py`.
- **Status:** LANDED (toolkit + test; case scripts import it in the sibling 6.x tasks).
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_spine_sim_caselib.py" -q`
  (5 passed) and `python3 -c "import sys; sys.path.insert(0,'framework/spine_sim'); import _case_lib as L; print('caselib ok', bool(L.HOOKS), bool(L.STOP_TOKENS))"` (prints `caselib ok True True`).

### CR-103 — `spine_sim` invariant-family cases (G10/G12–G16/G23/G25)
- **Date registered:** 2026-07-10 (spine-hardening Phase 6 Task 6.3).
- **What:** 8 new tracked case scripts under `tests/adversarial/cases/` — `case_G10.py`, `case_G12.py`,
  `case_G13.py`, `case_G14.py`, `case_G15.py`, `case_G16.py`, `case_G23.py`, `case_G25.py` — plus the
  integration test `tests/unit/test_spine_sim_invariants.py`. Each imports `_case_lib`, seeds a
  throwaway rundir with a bad fixture, drives the REAL `validate_run_state.py --json`, and asserts the
  named enforcement FAILs (case exit 0 = gate fired): G10 → inv `figure-contract-fulfilled` (D9,
  primary target with `side_by_side: null`, generation reached so the primary-aware block is live);
  G12 → inv `param-validated-before-scan` (D10, a shipping scan whose `inputs/validations.json`
  varied-param obligation is `PENDING`); G13 → inv `ladder-order` (D11, full/scan at generation with no
  smoke-rung PASS in `logs/ladder.json`); G14 → inv `certify-before-limit` (D12, scan shipping an
  exclusion with no discoverable acc×eff cert — scan.json point attestation does not substitute);
  G15 → inv `trap-obligations-discharged` (D13, T8 hit with a `PENDING` obligation, generation reached);
  G16 → the `statistics` STAGE (D14, all-zero yields → degenerate huge µ95 → `sr_plausibility.json`
  verdict `implausible` folded by `check_statistics`); G23 → inv `outputs-in-tree` (N2, a
  `scan_manifest.json` point whose `run_dir` resolves under `/tmp`); G25 → inv `producer-complete` (N4,
  a real `.lhe.gz` whose banner `nevents=3` ≠ its 2 counted `<event>` records, Cross-section line
  present so the FAIL isolates to the count mismatch).
- **As-built verification:** each case was RUN against the worktree's on-disk `validate_run_state.py`
  (not the brief's assumptions) and confirmed to FIRE — the fixtures mirror the tool's own selftest
  builders (`_fixture_primary_unfulfilled`/`_fixture_scan_param_pending`/`_fixture_scan_no_smoke_ladder`/
  `_fixture_scan_cert_attestation_only`/`_fixture_trap_obligation_pending`/`_fixture_implausible_stats`/
  `_fixture_scan_output_in_tmp`/`_fixture_lhe_mid_write`), so a case fires on the exact trigger the real
  code checks (invariant/fixture-key names, exit codes) rather than a weakened proxy.
- **Why:** L6 of the spine — the Phase 3/4 physics-lifecycle invariants each need a live per-gate
  regression that proves the gate FIRES on its trigger, not merely that its tool is on disk. This is the
  integration lane of `spine_sim`: it drives the REAL invariants/stages, so it goes green only once those
  landed (this phase runs last).
- **Where-embedded:** `tests/adversarial/README.md` (new "Case coverage" table, 8 rows);
  `DIRECTORY.md` `tests/adversarial/cases/` folder row listing the 8 case files + their enforcement.
- **Status:** LANDED (8 cases + integration test; all fire against the as-built enforcement).
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_spine_sim_invariants.py" -q`
  (1 passed) and `python3 tests/adversarial/run_suite.py --only G10,G12,G13,G14,G15,G16,G23,G25`
  (board shows all 8 PASS, exit 0).

### CR-104 — `spine_sim` Stop-dispatch + watchdog cases (G2/G4/G5/G6/G8/G11/G27)
- **Date registered:** 2026-07-10 (spine-hardening Phase 6 Task 6.4).
- **What:** 7 new tracked case scripts under `tests/adversarial/cases/` — `case_G2.py`, `case_G4.py`,
  `case_G5.py`, `case_G6.py`, `case_G8.py`, `case_G11.py`, `case_G27.py` — plus the integration test
  `tests/unit/test_spine_sim_stop.py`. Each imports `_case_lib`, seeds a throwaway rundir, and
  drives the REAL Phase 2 `stop_dispatch.py` at ONE `--branch`, asserting exit 2 + the branch's
  `STOP_TOKENS` token (case exit 0 = gate fired): G4 → `drive`/`DRIVE` (D4, a `next_required` turn with
  no compute and no live bg); G5 → `phantom`/`PHANTOM` (D5-signature, claims a bg job but the liveness
  probe finds none); G2 → `skill-coverage`/`SKILL-COVERAGE` (G2, a `scan` task at the `statistics` step
  with `run-scan` never in `skills_invoked`); G27 → `detach`/`DETACH` (N6, a `bg_kind=detached` entry
  missing `logfile`/`done_condition`/`next_action`); G11 → `d18`/`D18` (D5 waypoint, a CHECK-IN-2
  delivery turn whose PRIMARY figure target has `side_by_side: null`, so `validate_run_state.py --rundir`
  exits nonzero under the umbrella); G8 → `recipe-search`/`G8-RECIPE-SEARCH` (D8/D-4 non-invariant
  branch, an OPEN `tool_generator_model` failure with no `inputs/recipe_search.json`, via
  `resource_census.py --assert-recipe-search`). G6 also RUNs `stage_supervisor.py --selftest` (the
  hang→kill→`failure.json` watchdog, exit 0) before its `catch`/`CATCH` assertion (D6, an unhandled
  `*.failure.json`).
- **As-built verification:** the branch names + tokens were grepped from the on-disk `stop_dispatch.py`
  `BRANCHES` list and `_case_lib.STOP_TOKENS`, and each case was RUN against the worktree's live
  `stop_dispatch.py`/`stage_supervisor.py`/`resource_census.py` (not the brief's assumptions) and
  confirmed to FIRE. The brief's `case_G2` placeholder `current_step="08-scan"` matched no branch key —
  the CASE was corrected to the as-built `current_step="statistics"` + `task_mode="scan"` (the run-scan
  obligation keys on task_mode `scan` at the `statistics` stage, since `scan` is a task_mode, not a
  STAGE_ORDER stage), never the enforcement.
- **Why:** L6 of the spine — the Phase 2 Stop-hook branches and the Phase 2 watchdog each need a live
  per-gate regression that proves the branch BLOCKS turn-end (exit 2) on its trigger, not merely that the
  dispatcher is on disk. This is the second integration lane of `spine_sim`, driving the REAL
  `stop_dispatch.py`/`stage_supervisor.py`, so it goes green only once those landed (this phase runs last).
- **Where-embedded:** `tests/adversarial/README.md` (the "Case coverage" table gains 7 rows and its
  intro/column now name the Stop-dispatch + watchdog lane); `DIRECTORY.md` `tests/adversarial/cases/`
  folder row listing the 7 case files + their Stop branch/token.
- **Status:** LANDED (7 cases + integration test; all fire against the as-built enforcement).
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_spine_sim_stop.py" -q`
  (1 passed) and `python3 tests/adversarial/run_suite.py --only G2,G4,G5,G6,G8,G11,G27`
  (board shows all 7 PASS, exit 0).

### CR-105 — `spine_sim` hook + tool cases (G0a–c/G1/G3/G7/G9/G17–G20/G22/G24/G26)
- **Date registered:** 2026-07-10 (spine-hardening Phase 6 Task 6.5).
- **What:** 14 new tracked case scripts under `tests/adversarial/cases/` — `case_G0a.py`,
  `case_G0b.py`, `case_G0c.py`, `case_G1.py`, `case_G3.py`, `case_G7.py`, `case_G9.py`, `case_G17.py`,
  `case_G18.py`, `case_G19.py`, `case_G20.py`, `case_G22.py`, `case_G24.py`, `case_G26.py` — plus the
  integration test `tests/unit/test_spine_sim_hooks_tools.py`. This is the THIRD `spine_sim`
  integration lane, spanning Phases 0–4: the Phase-0 spike re-checks (G0a–G0c re-run
  `tests/adversarial/spike_probe.py --spike SPK-{1,2,3} --check` on the recorded artifacts); the
  Phase-1/2/3/4 hook SCRIPTS driven directly with a crafted stdin JSON (G1 `userpromptsubmit-router.sh`
  injects the INITIATE/route reminder naming physicist-intake; G9 `pre-generate-guard.sh` exit 2 on a
  no-recipe BSM `run-pipeline-native.sh` launch/D7; G17 `deviations-guard.sh` exit 2 on a baselined
  `inputs/task_contract.json` edit with no DEVIATIONS row/D15; G22 `pretooluse-skill.sh` exit 2 on
  new-analysis-before-contract/N1); the wired infra tools (G3 `workflow_state.py advance --to statistics`
  refuses an out-of-order jump; G7 `progress_reporter.py --selftest`; G18 `validate_checkin.py` exit 1
  on a thin CHECK-IN; G19 `validate_run_state.py --verify-provenance` exit 1 on a hand-written
  `outputs/sr_plausibility.json`; G20 `check_agent_surface.py --stage` dead-ref FAIL + the
  worktree-resolved `pre-commit` hook/D16); and the two D-4 NON-invariant Stop branches (G24
  `armed-watcher`/`G24-ARMED-WATCHER`/N3, G26 `open-defect`/`G26-OPEN-DEFECT`/N5).
- **As-built verification:** every mechanism was RUN against the worktree's live hooks/tools (not the
  brief's assumptions) and confirmed to FIRE before transcription. TWO brief corrections landed in the
  CASES, never the enforcement: (1) per the recorded spike state + the EXECUTION ADJUSTMENT, SPK-1 is
  recorded `verdict=unproven`/`decision=fallback-primary` (this harness could not auth `claude -p` for a
  full-turn probe), so `spike_probe --spike SPK-1 --check` correctly exits 1 (a CONSISTENT
  recorded-not-PASS, not a tamper/exit 3) — `case_G0a` attests that HONEST recorded state (exit 1), NOT a
  PASS this environment cannot produce (the recorder-not-vacuous property is separately proven by
  `spike_probe --selftest`'s seeded-FAIL cases); SPK-2/SPK-3 are recorded PASS → exit 0. (2) The brief's
  G0a/G0b/G0c used `_case_lib.spike_check`, but `tool_path` searches only `_infrastructure/` + `framework/`
  and `spike_probe.py` lives in `framework/spine/`, so `spike_check` raises `CaseSetupError` — the three
  cases invoke `spike_probe.py` directly at its real path instead (no `_case_lib.py` edit, keeping the
  commit to this task's file set).
- **Why:** L6 of the spine — the Phase-0 spikes, the hook scripts, the infra tools, and the D-4 Stop
  branches each need a live per-gate regression that proves the enforcement FIRES on its trigger, not
  merely that the instrument is on disk. Per the SPK-1 auth finding the hook-based gates are direct-driven
  (crafted stdin JSON → assert exit + message), not via a live agent turn.
- **Where-embedded:** `tests/adversarial/README.md` (the "Case coverage" table gains 14 rows; the
  intro now names the hook + tool lane as the third integration lane and its direct-drive discipline);
  `DIRECTORY.md` `tests/adversarial/cases/` folder row listing the 14 case files + their
  hook/tool/branch.
- **Status:** LANDED (14 cases + integration test; all fire against the as-built enforcement).
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_spine_sim_hooks_tools.py" -q`
  (1 passed) and `python3 tests/adversarial/run_suite.py --only G0a,G0b,G0c,G1,G3,G7,G9,G17,G18,G19,G20,G22,G24,G26`
  (board shows all 14 PASS, exit 0).

### CR-106 — clean-room self-drive launcher + G21 (D17)
- **Date registered:** 2026-07-10 (spine-hardening Phase 6 Task 6.6).
- **What:** `tests/adversarial/clean_room.py` (stdlib-only, the D17 un-hinted self-drive launcher) +
  `tests/adversarial/cases/case_g21.py` + `tests/adversarial/self_drive/.gitkeep` + the test
  `tests/unit/test_clean_room.py` (6). `clean_room.py` builds an **un-hinted** launch command
  (`build_launch_cmd` → `claude -p` from the DSRLab **PARENT** cwd with `--setting-sources user` +
  `--strict-mcp-config`, so the project `CLAUDE.md`/settings do NOT auto-load — the parent-cwd routing
  gap D17 exists to close) and scores the `--output-format json` transcript with the PURE
  `evaluate_transcript` verdict engine: PASS iff a valid `task_contract.json` was emitted AND CHECK-IN 1
  (optionally CHECK-IN 2) was reached AND no dev-repo survey preceded the route AND no generation
  preceded the go-ahead. CLI: `--live [--checkin 1|2] [--out] [--json]` (real launch → writes
  `self_drive/last_verdict.json`), `--replay <payload.json>` (score a captured transcript offline),
  `--selftest`. `case_G21.py` `attest`s the recorded verdict == PASS; the L6 engine
  (`run_spine_sim.py`, CR-101) already SKIPs G21 when the artifact is absent unless `--with-self-drive`
  is passed, so the default board stays green.
- **Why:** D17 — five of five fresh physicist sessions launched from the DSRLab parent dir failed to
  route before the parent-cwd router existed (FAILURE-CATALOGUE D3). G21 is the integration proof that
  the router + INITIATE gate actually make an un-hinted agent reach CHECK-IN 1 nudge-free, with no
  survey and no premature compute — the whole spine's headline behaviour, verified end to end.
- **As-built / EXECUTION ADJUSTMENT (auth finding):** headless `claude -p` is **NOT authenticated in
  this environment**, so the LIVE round-trip cannot run here — the honest design (recorded in the
  module docstring + `spine_sim/README.md`) is an **authenticated in-harness subagent** (or an
  authenticated interactive `claude`) driving the un-hinted prompt from `PARENT_CWD`, whose captured
  transcript is scored offline via `--replay`. The deterministic core (`evaluate_transcript` /
  `--replay` / `--selftest`) is what the pytest drives; the LIVE G21 gate runs **on-demand** and is
  **SKIP by default** (never faked to PASS — running `--live` unauthenticated would write a FAIL
  verdict, so it is deliberately not run here). This is the same SPK-1 auth finding recorded for G0a
  (CR-105). The `self_drive/last_verdict.json` live artifact is gitignored (regenerable); the dir is
  tracked via `.gitkeep`.
- **Where-embedded:** `tests/adversarial/README.md` (self-drive lane paragraph + G21 coverage row),
  `docs/workflow/steps/09-verify.md` (the "enforcement spine is itself verified (L6)" note),
  `DIRECTORY.md` (rows for `clean_room.py` + `self_drive/` + the G21 case), `.gitignore` (the live
  artifact). This is the LAST 6.x case, so all 30 gates G0a–G27 now have a case (board:
  29 PASS / 1 SKIP (G21) / 0 FAIL of 30).
- **Status:** LANDED (launcher + verdict engine + G21 case + test; G21 SKIP-by-default, on-demand live).
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_clean_room.py" -q`
  (6 passed), `python3 tests/adversarial/clean_room.py --selftest` (exit 0), and
  `python3 tests/adversarial/run_suite.py --require-all` (29 PASS / 1 SKIP / 0 FAIL, exit 0).

### CR-107 — `green_board.py` + `make green` (the one aggregate L6 green bar)
- **Date registered:** 2026-07-10 (spine-hardening Phase 6 Task 6.7).
- **What:** `scripts/green_board.py` (stdlib-only) + the repo-root `Makefile` (`green` /
  `green-self-drive` / `spine-sim` targets) + the test `tests/unit/test_green_board.py` (5).
  `green_board.py` runs, from the repo root in one exit code, the whole enforcement stack as a list of
  `RUNGS` `(name, cmd, informational)`: `spine_sim` (`run_spine_sim.py --require-all` — every G0a–G27
  fires), `verify_fixes` (the CR board), `check_agent_surface` (routing/docs coherence), and `audit`
  (readiness report, **informational** — never sinks the board). `run_rung` shells each command with
  `cwd=REPO_ROOT` and a 1800 s per-rung timeout; `build_board` maps it over the rungs; `main` prints a
  human board (or `--json`) and exits **0 iff every non-informational rung PASSed**. `--with-self-drive`
  FIRST runs `clean_room.py --live --checkin 2` (records the fresh verdict) then swaps in
  `run_spine_sim.py --require-all --with-self-drive` so the G21 self-drive case actually asserts against
  that verdict instead of SKIPping; the default `make green` SKIPs G21 (no live artifact). `--rungs-json`
  is a test hook that overrides the rung list.
- **Why:** L6 (verification: all gates GREEN) needs ONE command a human runs before merging the spine
  worktree back — not four separate invocations. `make green` is that aggregate bar; `make
  green-self-drive` adds the live clean-room proof. Aggregation, informational-rung handling, exit code,
  and cwd=repo plumbing are all pinned by fabricated-rung fixtures (never the slow real stack) plus one
  real fast subprocess.
- **Where-embedded:** `docs/workflow/README.md` (the "one aggregate green bar" note under Mechanized
  enforcement), `DIRECTORY.md` (rows for `scripts/green_board.py` + the root `Makefile`).
- **Status:** LANDED (board + Makefile + test; audit rung informational; G21 SKIP-by-default in the
  default board). NOTE: a plain `make green` is not yet exit-0 in-repo — `verify_fixes`/CR-039
  (`validate_run_state.py --rundir trial-runs/sleptonscan_fig3_SCAN`) is currently red, independent of
  this change; the full `make green` exit-0 is asserted in Task 6.8 once the stack is fully green.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_green_board.py" -q`
  (5 passed), and `python3 scripts/green_board.py --json` lists the four stack rungs.

### CR-108 — `spine_sim` completeness gate + verification record (L6 all-GREEN)
- **Date registered:** 2026-07-10 (spine-hardening Phase 6 Task 6.8).
- **What:** the whole-spine completeness gate `tests/unit/test_spine_sim_complete.py` (2 tests) —
  it asserts (a) every one of the 30 `EXPECTED_GATES` (G0a–G27) has a `cases/case_<G>.py` script and
  (b) `run_spine_sim.py --require-all --json` exits 0 with ≥30 results (29 PASS / 1 SKIP G21 / 0 FAIL).
  Plus the verification RECORD: `tests/adversarial/README.md` finalized to carry the sorted 30-row
  coverage table (gate | trigger | mechanism | case | GREEN assertion); `docs/reference/scope.md` §9 scope
  row ("harness + self-drive green" is this cycle's bar, NOT a physicist-vetted full-physics run — spec
  §2 non-goal); the `FAILURE-CATALOGUE.md` D4 `verified-by: spine_sim case_G19.py` back-reference (the
  D5–D18/N1–N6 narrative rows + their back-refs are owned by the doc-embed phase, Task 7.2). And the
  make-green resolution CR-107 explicitly deferred here: `scripts/green_board.py` swaps the red legacy
  `verify_fixes` rung for `validate_run_state.py --selftest`, so `make green` is exit-0 over the three
  REAL as-built L6 checks (spine_sim `--require-all`, check_agent_surface, validate_run_state selftest)
  plus the informational audit; `tests/unit/test_green_board.py`'s default-rung assertion updated
  to match.
- **Why:** L6 (verification: all gates GREEN) is only real when the harness is EXHAUSTIVE — a gate with
  no case is a silent hole. `--require-all` already MISSING-FAILs an unwritten gate; this test pins the
  completeness in pytest so it cannot regress. The `verify_fixes`/CR-039 rung was intrinsically red — it
  hard-validates the frozen `trial-runs/sleptonscan_fig3_SCAN`, which predates and so FAILs the
  ladder-order / certify-before-limit / trap-obligations invariants this spine ADDED (a consequence, not
  a spine regression) — so the aggregate L6 board is defined over the three checks that do not depend on
  that stale rundir (`verify_fixes.py` still runs standalone). G0a is honestly recorded
  unproven-but-attested (the harness could not auth headless `claude -p`), never a false PASS; G21 is
  SKIP-by-default, forced green on-demand by `make green-self-drive`.
- **Where-embedded:** `tests/adversarial/README.md` (the 30-row coverage table + completeness-gate
  lead-in), `docs/reference/scope.md` (§9 verification-scope row), `docs/reference/failure-modes.md` (the D4
  back-reference), `DIRECTORY.md` (the `spine_sim/` completeness-gate + `green_board.py` rung + `Makefile`
  rows).
- **Status:** LANDED — `make green` exit 0 (4 PASS / 0 FAIL: spine_sim, check_agent_surface,
  validate_run_state; audit informational); the per-gate board is 29 PASS / 1 SKIP (G21) / 0 FAIL over
  all 30 gates G0a–G27.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_spine_sim_complete.py" -q`
  (2 passed), and `make green` exits 0.

### CR-109 — DIRECTORY.md reconcile for the workflow-adherence spine (Phase 7 Task 7.1)
- **Date registered:** 2026-07-10 (spine-hardening Phase 7, Task 7.1).
- **What:** the directory-keeper reconcile that closes the map against the landed spine + its regression
  guard. `tests/unit/test_directory_reconciled.py` (2 tests) pins the directory-keeper contract:
  every landed spine file — the `_infrastructure/` spine tools (`workflow_state`/`provenance`/
  `progress_reporter`/`stop_dispatch`/`stage_supervisor`/`validate_parameters`/`validate_checkin`/
  `preflight_watcher`/`sr_plausibility`/`install_git_hooks`), the four `.claude/hooks/*.sh` spine hooks,
  `tests/adversarial/`, and `evidence/hooks/hook-primacy.json` — carries a DIRECTORY.md row, and the
  `<run>/run_state.json` ledger convention is documented. Phases 0–6 had already landed those rows (the
  `_infrastructure/` catch-all + the dedicated `spine/`/`spine_sim/`/hook rows), so the guard is green on
  arrival; the drift this task fixes: (a) the `.claude/settings.json` DIRECTORY row still claimed "the
  SPK-1 (G0a) probe blocks are left intact alongside" (that scaffolding was retired in CR-070) AND omitted
  `deviations-guard.sh` + `pre-generate-guard.sh` from its PostToolUse list — rewritten to the real
  four-event wiring (PreToolUse card-guard + skill-precedence; UserPromptSubmit router; PostToolUse
  observer + deviations-guard + pre-generate-guard; Stop dispatcher); (b) the spine design record
  `docs/superpowers/` (the validated design SPEC + the phase-by-phase implementation PLAN behind Phases
  0–7) was a tracked-but-unmapped top-level straggler — now a `## Repository root` row that clears the last
  `check_agent_surface` dirmap WARN; (c) `trial-runs/README.md`'s per-run layout now lists `run_state.json`.
- **Why:** the directory-keeper contract + the D16/G20 pre-commit `check_agent_surface.py` gate — an
  unmapped file WARNs and a stale/mis-mapped row misleads a fresh session; the pytest guard means a future
  spine file cannot land unmapped without a red test.
- **Where-embedded:** `DIRECTORY.md` (the `.claude/settings.json` row rewrite + the `docs/superpowers/`
  row), `trial-runs/README.md` (per-run layout), `tests/unit/test_directory_reconciled.py`.
- **Status:** LANDED (2026-07-10) — `check_agent_surface.py` exit 0 with `[PASS] dirmap` + `[PASS] refs`
  and no WARN.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_directory_reconciled.py" -q && cd "$REPO" && python3 src/ravel/validation/check_agent_surface.py`

### CR-110 — FAILURE-CATALOGUE spine classes D4–D18 + N1–N6, each naming the gate that now catches it (Phase 7 Task 7.2)
- **Date registered:** 2026-07-10 (spine-hardening Phase 7, Task 7.2).
- **What:** embed the workflow-adherence spine's failure classes into `docs/reference/failure-modes.md` as
  append-only entries continuing the D-series, each in the standard record form (what happened → how
  caught → **Guard: G# + where it lives** → verified-by: spine_sim `case_G<n>`): D4 DRIVE/**G4**, D5
  waypoint-INTEGRITY/**G11**, D6 CATCH/**G6**, D7 PREVENT/**G9**, D8 RESOLVE/**G8**, D9 primary-INTEGRITY/
  **G10**, D10 VALIDATE/**G12**, D11 LADDER/**G13**, D12 CERTIFY/**G14**, D13 TRAP-OBLIGATIONS/**G15**, D14
  PLAUSIBILITY/**G16**, D15 DEVIATIONS-at-change/**G17**, D16 EMBED-COMMIT/**G20**, D17 SELF-DRIVE/**G21**,
  D18 the **umbrella** (`validate_run_state --rundir`, folds `verify_pack` + every invariant), plus the
  2026-07-09 transcript completeness-critic signatures N1 skill-precedence/**G22**, N2 in-tree-outputs/
  **G23**, N3 armed-command/**G24**, N4 producer-barrier/**G25**, N5 open-defect/**G26**, N6 detach-drive/
  **G27**. `tests/unit/test_failure_catalogue_spine.py` (3 tests) is the durable regression: every
  spine class carries a bold `**Cn —` entry, names its gate id, and the D18 block names the
  `validate_run_state` umbrella. The Tier-B attack-list paragraph is extended from `A1–D3` to
  `A1–D19 + N1–N6` so the step-9 adversary walks the full spine as its attack list.
- **Reconcile:** a prior task's provenance entry was mis-numbered `**D4 —` (it is gate **G19**, not the
  spec's D4=DRIVE). Renumbered to **D19** (the cross-cutting provenance invariant surfaced during the spine
  build, mnemonic G19↔D19) with content preserved (`verify_provenance_lifecycle`, verified-by
  `case_G19.py`); the stale "remaining rows … owned by Task 7.2" handoff note it carried is now discharged.
- **Why:** the FAILURE-CATALOGUE is the durable records-track memory + the Tier-B attack list + a seed for
  the P4 routing/behavior evals; a spine class that fired a real trial failure but is not recorded with its
  guard is invisible to a fresh session and to the adversary. The pytest guard makes the class↔gate map
  non-droppable.
- **Where-embedded:** `docs/reference/failure-modes.md` (the D4–D19 + N1–N6 entries + the extended Tier-B
  paragraph), `tests/unit/test_failure_catalogue_spine.py`.
- **Status:** LANDED (2026-07-10) — the spine test is 3 PASS; the class↔gate map matches
  `tests/adversarial/README.md` (G0a–G27) and the landed `stop_dispatch.py`/`validate_run_state.py`
  guards.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_failure_catalogue_spine.py" -q` (3 passed).

### CR-111 — PRODUCT-CONTRACT scope rows: skill-precedence / detached-job / in-tree-outputs (Phase 7 Task 7.3)
- **Date registered:** 2026-07-10 (spine-hardening Phase 7, Task 7.3).
- **What:** §6 refusal items 9 (N1 skill-precedence, physicist-intake-first, G22) and 10 (N6
  detached-job, run_state.json+heartbeat, G27); §7 semantics bullet (N2 in-tree-outputs, G23).
  No new enum value — the enum-mirror invariant is now guarded by a test
  (`test_stat_mode_enum_mirrored`: every canonical `result_pack.STAT_MODES` member must appear in
  PRODUCT-CONTRACT, so a future enum add forces a §3 row first).
- **Why:** §8 binds "any new mode/label/refusal lands HERE first"; these three spine policies are
  named refusals/semantics, not silent improvisations.
- **Where-embedded:** docs/reference/scope.md §6/§7; `tests/unit/test_product_contract_policies.py`
  (4 tests: the three policy rows + the enum-mirror guard).
- **Status:** EMBEDDED (2026-07-10) — 4 PASS; `check_agent_surface.py` green.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_product_contract_policies.py" -q` (4 passed).

### CR-112 — ROUTING-EVALS skill-trigger behavior evals: should/shouldn't-trigger sets + TRAIN/HELD-OUT split for the two NEW spine triggers (Phase 7 Task 7.4)
- **Date registered:** 2026-07-10 (spine-hardening Phase 7, Task 7.4).
- **What:** append a `## Skill-trigger behavior evals` section to `docs/research/routing-evaluation.md` — a P4-style
  DOC eval (candidate prompt set, not yet a live run) for the two behavior triggers the spine ADDS:
  **skill-precedence** (physicist-intake-FIRST, N1 / guard G22) and **stage-recovery** (recipe-search
  CO-PRIMARY on a diagnosed stage failure, D8 / guard G8). Each trigger carries a should-trigger set (the
  move must fire) and a shouldn't-trigger set (firing would be a false-positive: intake forced on a
  dev/resume session; stage-recovery on a clean stage), each split into a TRAIN subset (may shape the fork
  text) and a HELD-OUT subset (scored blind, the honest number). Same launch-context-faithful condition as
  the P4 charter set (fresh cheap-model subagent, workspace-parent cwd, no directory hint).
- **Why:** the spine_sim `case_G22`/`case_G8` cases prove the GUARD fires on a crafted artifact, but not
  that a fresh cheap model reaches for the right skill on natural language BEFORE the guard has to catch it
  (a should-trigger miss is exactly the N1/D8 transcript signature) — nor that the guard does not induce an
  over-fit (a shouldn't-trigger false-positive). These behavior evals are that layer of proof, above the
  mechanical floor; they also seed the next launch-context-faithful eval pass.
- **Where-embedded:** `docs/research/routing-evaluation.md` (the new section); `tests/unit/test_routing_evals_skill_triggers.py`
  (2 tests: required anchors present; min should/shouldn't counts + the TRAIN/HELD-OUT split); `DIRECTORY.md`
  (ROUTING-EVALS row refreshed).
- **Status:** EMBEDDED (2026-07-10) — 2 PASS.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_routing_evals_skill_triggers.py" -q` (2 passed).

### CR-113 — workflow-adherence spine: records sweep + green board (Phase 7 close)
- **Date registered:** 2026-07-10 (spine-hardening Phase 7, Task 7.5).
- **What:** the closing green-board sweep — `tests/unit/test_records_reconciled.py` provides the
  G20 GREEN baseline (`check_agent_surface` exit 0) that spine_sim's G20 case perturbs, PLUS the
  deterministic proof that a dangling DIRECTORY row (a row pointing at a file not on disk) makes
  `check_dirmap` error (the G20 seed the pre-commit hook blocks on). The §1 embed audit sweep
  confirms every earlier-phase spine tool/flag is referenced in the agent surface
  (`grep -rIE '<tool>' docs/workflow/ .claude/` ≥1 hit for each — `spike_probe.py` is the sole 0-hit and
  is correct: a records-track L0 spike verifier documented in `DIRECTORY.md`, not the operational
  surface). Confirms the full board: `check_agent_surface` OK, `sync_skills` mirror parity, and
  `green_board.py` exit 0 (spine_sim G0a–G27 all fire, `check_agent_surface` + `validate_run_state`
  --selftest all PASS, audit informational).
- **Why:** the phase's exit gate (spec §4 L6 "GREEN = every harness gate fires + the self-drive
  passes + the surface/board stays green"); the D16/G20 hygiene half of the spine. `green_board.py`
  (not `verify_fixes.py`) is the spine's aggregate L6 gate — `verify_fixes.py`'s CR-039 line
  hard-validates the frozen `sleptonscan_fig3_SCAN`, which predates and therefore FAILs the
  ladder-order/certify-before-limit/trap invariants this spine ADDED (a documented consequence, not a
  regression), so it is intentionally not a `green_board.py` rung.
- **Where-embedded:** `tests/unit/test_records_reconciled.py`; the board commands above;
  `docs/workflow/README.md` + `docs/workflow/steps/09-verify.md` (the aggregate `green_board.py`/`make green`
  board); `Makefile` (`make green`).
- **Status:** EMBEDDED (2026-07-10) — 2 PASS.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_records_reconciled.py" -q && cd "$REPO" && python3 src/ravel/validation/check_agent_surface.py && python3 scripts/green_board.py`

### CR-114 — G21 clean-room self-drive: live PASS (authenticated subagent)
- **Date registered:** 2026-07-10
- **What:** ran the clean-room self-drive (G21/D17) with an authenticated in-harness subagent (claude -p auth-blocked per SPK-1). A fresh un-hinted agent given only a physics request read docs/workflow/start.md FIRST, loaded physicist-intake FIRST (no repo survey), produced a validated task_contract.json, and stopped at CHECK-IN 1 (validate_checkin.py passing) with run_state.json recording route+skill and the run-dir locked — zero compute, BLOCKED awaiting approval. Recorded tests/adversarial/self_drive/last_verdict.json (verdict=PASS) + the curated evidence run dir.
- **Why:** the antithesis of the SVJ-trial failure (which loaded new-analysis first + surveyed dev docs); proves the routing + physicist-intake + CHECK-IN gate + run_state observability drive a fresh agent correctly end-to-end. Flips spine_sim G21 SKIP->PASS.
- **Verify:** `python3 tests/adversarial/cases/case_g21.py` exit 0; `python3 tests/adversarial/run_suite.py --require-all` -> 30 PASS

### CR-115 — curated-export: reword dev-only dead references in two shipped agent docs
- **Date registered:** 2026-07-11
- **What:** the curated-export dry-run (`export_distribution.sh … --allow-placeholder-license`) failed
  gate 4c (`check_agent_surface.py --stage`) with 10 staged-tree dead references — two SHIPPED
  agent-facing docs backtick-referenced files that are INTENTIONALLY dev/CI/operator-only and excluded
  from the distributable stage (`.claude/hooks/`, `tests/unit/`, and the spine_sim/green_board
  verification harness). Reworded ONLY those dead references to describe each by its role instead of a
  backtick repo path, keeping the enforcement description intact: in `docs/workflow/README.md` the five
  hook scripts became "the PreToolUse card-guard / the skill-precedence guard / the PostToolUse
  observer / the UserPromptSubmit router / the Stop dispatcher", `tests/unit/test_settings_wiring.py`
  → "the settings-wiring test (dev-repo/CI only)", `scripts/green_board.py` → "the `make green`
  aggregate board", `tests/unit/test_spine_sim_complete.py` → "the spine_sim completeness test
  (dev-repo, CR-108)"; in `docs/workflow/steps/09-verify.md` `tests/adversarial/run_suite.py` → "the
  spine_sim verification board (run on-demand in the dev repo)" and `tests/adversarial/self_drive/` →
  "the spine_sim self-drive record directory". Tokens that DO ship (`stop_dispatch.py`,
  `workflow_state.py`, `route_prompt.py`, `run_state.json`, `validate_run_state.py`, `make green`) were
  left untouched. No file was added to the export whitelist; nothing dev-only now ships.
- **Why:** a shipped doc must not name, as a must-exist backtick path, a file the distribution
  deliberately omits — `check_agent_surface.py --stage` treats such a token as a dead reference and
  blocks the export. Describing the operator-only guards by role keeps the docs honest for a
  distribution reader (who cannot run a dev-repo command) while preserving the accurate account of what
  each guard enforces.
- **Where-embedded:** `docs/workflow/README.md` (hook table + the L6 aggregate-board / settings-wiring /
  spine_sim-completeness lines); `docs/workflow/steps/09-verify.md` (the L6 spine-verification section).
- **Status:** EMBEDDED (2026-07-11).
- **Verify:** `rm -rf /tmp/hep-dist && bash scripts/maintenance/export-distribution.sh /tmp/hep-dist --allow-placeholder-license` exits 0 (gate 4c clean, evidence gate 14 PASS, size guard clean); `python3 src/ravel/validation/check_agent_surface.py` exit 0; `python3 scripts/green_board.py` exit 0.

### CR-116 — lhe_check JSON sidecar (default-on) + `lhe-check-before-shower` invariant (A1)
- **Date registered:** 2026-07-11
- **What:** `src/ravel/validation/lhe_check.py` now ALWAYS writes a JSON sidecar (default
  `<lhe>.lhe_check.json`, `--json-out PATH` overrides) with `{schema_version:1,
  generated_by:"lhe_check.py", generated_utc ($LHE_CHECK_UTC, diff-stable), lhe:<abspath>,
  verdict:"PASS"|"FAIL", checks:[{name,level,msg}]}` — every printed report line is mirrored into
  `checks`, and the verdict is EARNED (`FAIL` unless checks exist and none is level FAIL; never
  defaults passing). Printed output and exit-code semantics are unchanged. On the gate side,
  `validate_run_state.py` gains `inv_lhe_check_before_shower` (registered
  `("lhe-check-before-shower", "generation", …)`): shower products on disk
  (`facts["hepmc_hits"]`: `*.hepmc`/`*.hepmc.gz`) with no `*.lhe_check.json`
  (`facts["lhe_check_artifacts"]`) FAIL post-epoch (legacy → `waived-legacy`); a sidecar with
  `verdict=FAIL`, or none recording `verdict=PASS`, also FAILs. Discovery uses the new
  `find_all_matching()` glob helper that walks INTO `Events/`/`logs/` (like `locate_lhe_gz`) so a
  sidecar written next to the LHE inside a MadGraph procdir is seen. Selftest case 20
  (`_fixture_shower_without_lhe_check`) + count literal `{17 + 3}`.
- **Why:** trial QM.2 (SVJ adherence audit): the trial showered base+matched+anchor samples with
  `logs/` empty — the mandatory pre-shower gate left NO artifact, so nothing downstream could
  prove (or enforce) that `lhe_check` ever ran. The sidecar makes the guard auditable; the
  invariant makes skipping it a hard lifecycle FAIL instead of a silent omission.
- **Where-embedded:** `docs/workflow/steps/03-generate.md` (pre-shower guard paragraph: sidecar
  default-on + gated); `.claude/skills/run-stage/SKILL.md` step 4 (+ `.agents/skills/` mirror via
  `sync_skills.py`); `tests/unit/test_lhe_check_gate.py` (10 tests: emitter sidecar/verdict/
  `--json-out`, invariant FAIL/PASS/legacy-waiver/no-defaulting, registration + selftest).
- **Status:** EMBEDDED (2026-07-11).
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_lhe_check_gate.py" "$REPO/tests/unit/test_validate_run_state.py" -q && cd "$REPO" && python3 src/ravel/validation/validate_run_state.py --selftest` (prints `20 case(s)`).

### CR-117 — compose provenance stamp + hand-populated-primary hard gate (A2)
- **Date registered:** 2026-07-11
- **What:** `figure_target.py compose` stamps `composed_by {tool, utc}` next to `side_by_side`; `validate_run_state.inv_figure_contract_fulfilled` extends the PRIMARY gate: the side_by_side FILE must exist on disk AND carry the compose stamp (legacy runs WARN). Selftest case 21 (`{18 + 3}`); 5 new pytest cases in test_figure_target_primary.py.
- **Why:** trial QI.2 — the SVJ run's primary Figure-5 side_by_side path was hand-populated into the JSON with no producing script, and the field-only check passed it. The stamp makes a composed output distinguishable from a forged path.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_figure_target_primary.py" -q` (14 passed) and `python3 src/ravel/validation/validate_run_state.py --selftest` (21 cases)

### CR-118 — fan-out-before-routing guard + shower-regex + generation skill-map (A3/A4/A5)
- **Date registered:** 2026-07-11
- **What:** (a) the UserPromptSubmit router leaves a session-keyed `logs/.route-pending-<session>` marker on physics classification; the PreToolUse guard (matcher now `Skill|Agent|Task`) BLOCKS Agent/Task fan-out for that session until `task_contract.json` exists, then consumes the marker (N8, trial QA.1's 8-agent pre-routing survey). (b) `GEN_LAUNCH_RE` gains `\.cmnd\b|madevent` — the trial's bespoke `.cmnd`-driven HV shower now trips the pre-generate guard (A4). (c) `REQUIRED_SKILL_FOR_STEP["generation"]="run-stage"` — the bespoke-generation path that lost lhe_check/supervisor idioms now blocks at turn-end without the run-stage skill (A5, trial QE.8). Pre-existing unmapped-step test re-anchored to basis_manifest.
- **Why:** trial QA.1/QF/QE.8 — the three mechanisms by which the run went bespoke before/instead of the gated path.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_pretooluse_skill.py" "$REPO/tests/unit/test_userpromptsubmit_router.py" "$REPO/tests/unit/test_settings_wiring.py" "$REPO/tests/unit/test_resource_census_gates.py" "$REPO/tests/unit/test_stop_dispatch_skill.py" -q` (37 passed)

### CR-119 — sensitivity integrity: pyhf method + acc*eff cert required (A7/A8)
- **Date registered:** 2026-07-11
- **What:** `check_statistics` hard-FAILs (legacy WARN) a `sensitivity-expected-only` artifact with no pyhf `method` (the A*eff-borrow guard); `CERT_REQUIRED_STAT_MODES` gains `sensitivity-expected-only` so `inv_certify_before_limit` demands a non-FAIL cert before a sensitivity claim ships. PRODUCT-CONTRACT §6b row. Selftest case 22 (`{19 + 3}`); 4 pytest cases in test_validate_run_state_lifecycle.py.
- **Why:** trial QM.2/QM.4 — the SVJ "expected limit" was a 1/A*eff borrow of ATLAS's published absolute limit with zero certification ("the biggest physics gap"); both were structurally un-gated for the sensitivity mode.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py" -q` (14 passed) and `python3 src/ravel/validation/validate_run_state.py --selftest` (22 cases)

### CR-120 — CHECK-IN gallery integrity: cited images must exist, no file links (A6)
- **Date registered:** 2026-07-11
- **What:** `validate_checkin.validate(c, base_dir=None)` — with a base_dir (the CLI derives it for `<rundir>/inputs/checkin*.json`), every `.png`/`.pdf` token cited in the CHECK-IN 1 gallery must exist on disk, and `file://` URIs are rejected. Pure-schema mode unchanged (back-compat). 4 new pytest cases.
- **Why:** trial QD.1/QM.1 — the delivered deck was un-viewable (link-only gallery, one of the three human catches); the validator asserted section presence but never that the cited figures exist.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_checkin.py" -q` (9 passed)

### CR-121 — FAILURE-CATALOGUE: N7/N8 classes + observed-in-the-wild trial evidence (A9)
- **Date registered:** 2026-07-11
- **What:** two new classes — **N7 assert-blocked-without-attempt** (QB.4 "Cloudflare-blocked" written with no fetch attempt; guard = the census obligation under the D18 umbrella + P6) and **N8 fan-out-before-routing** (QA.1's 8-agent pre-contract survey; guard = the CR-118 G22 extension) — plus observed-in-the-wild evidence lines on D4/D6/D7/D9/D10/N3/N5/N6 citing the 2026-07-06 SVJ trial's audit facts. Inventory test extended to N1–N8.
- **Why:** the trial's adherence interrogation is the catalogue's first full field test; its evidence belongs on the classes it validated, and the two uncatalogued classes needed entries + named gates.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_failure_catalogue_spine.py" -q`

### CR-122 — SVJ trial run closure: records trued + in-place fixes (B1–B5)
- **Date registered:** 2026-07-11
- **What:** the 2026-07-06 SVJ run's records now match its disk (Track B of the trial-audit
  gap-closure plan, Task 7). (a) `RESULT.md` rewritten from the stale pre-approval "PARTIAL" header
  to the executed final state: the corrected-R_inv dark-mass scan (1-D 30 pts + 2-D 15-pt map) ran
  to completion, CHECK-IN 2 + results deck delivered, step-9 panel PASS WITH CAVEATS; the
  A×ε-borrow caveat stated per §6.6b; a 9-item GAPS census (audit QM.2/QM.4); pointer to
  `TRIAL-ADHERENCE-SELF-AUDIT.md` as the adherence record. (b) `DEVIATIONS.md` closure ledger:
  the Contur s-channel-template origin of the traceHVcols hang (recipe-after-generation), the
  R_inv discard/re-run cross-reference, the 13×→6.4× normalization non-reconcile, the A×ε-borrow
  caveat, lhe_check + acceptance-cert never ran (honest gaps, NOT backfilled — pre-epoch run), and
  the two closure fixes. (c) `build/read_yoda.py` fixed in place: it divided the weight-scaled
  /RAW/ histogram sumW by the raw event count → "A*eff = 956%" on the matched anchor; the
  denominator is now the `/RAW/_EVTCOUNT` generator weight-sum (exactly once), `n_generated`
  demoted to metadata; live-verified on the two surviving anchor yodas (0.5689% base / 16.16%
  matched, both in (0,1]; the buggy 956.85% reproduces as 16.16% × the avg-weight×consumed/ngen
  factor). Headline numbers untouched — both assemblers consume only `sr_9bin_expected_139fb`.
  (d) plots deduped: byte-identical `darkmass_2dmap.png` + 3 zero-reference intermediates
  (`darkmass_variation_preview.png`, `fig_03a__r200.png`, `fig_05__r200.png`) removed; every
  surviving plot greps ≥1 in the run's records. (e) `DIRECTORY.md`: the run's row rewritten (was
  "survey-only, zero compute") + a top-level `logs/` row (session-ephemeral route-pending markers,
  CR-118), with root-anchored `/logs/` added to `.gitignore` so the row is true — the
  `check_agent_surface` dirmap WARN is gone. Finalized uncommitted run files (incl. the audit,
  the deck, `scan.json`/`scan_2dmap.json`) committed per the curation policy.
- **Why:** spec §1 Track B (B1–B5) — audit QM.4-5/6/7 (stale RESULT/DIRECTORY, plot litter,
  trap-provenance ledger gap) + QM.4-2 (the shipped-unfixed 956% helper defect, catalogue G26's
  in-the-wild instance). A run whose records contradict its disk is the exact class the spine
  exists to prevent; the pre-epoch run records its gaps honestly instead of faking gate artifacts.
- **Verify:** `grep -c "TRIAL-ADHERENCE-SELF-AUDIT" trial-runs/2026-07-06_*SVJ*/RESULT.md` ≥1 and
  `grep -c "blocked at CHECK-IN 1" trial-runs/2026-07-06_*SVJ*/RESULT.md` = 0;
  `grep -ci contur trial-runs/2026-07-06_*SVJ*/DEVIATIONS.md` ≥1; `md5 -q trial-runs/2026-07-06_*SVJ*/plots/*.png | sort | uniq -d` empty;
  `grep "SVJ-tchannel" DIRECTORY.md | grep -c "zero compute"` = 0; `python3 src/ravel/validation/check_agent_surface.py` exit 0 (no logs WARN).
- **Status:** EMBEDDED.

### CR-123 — cost_preflight artifact + cost-preflight-recorded invariant (R3/H4)
- **Date registered:** 2026-07-11
- **What:** `cost_preflight.py --rundir RD` writes `inputs/cost_preflight.json` (provenance-stamped est record); new invariant `cost-preflight-recorded` (generation) FAILs smoke/full/scan compute with no recorded budget (legacy waived). Selftest case 23 (`{20 + 3}`).
- **Why:** trial QD.5 — cost_preflight ran but recorded nothing; the budget lived only in the hand-editable contract block. The approval gate (CR-124) requires this artifact.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_cost_preflight_artifact.py" -q`

### CR-124 — the approval chain: workflow_state approve + pre-exec Bash compute gate + invariant (R3/H1)
- **Date registered:** 2026-07-11
- **What:** `workflow_state.py approve` writes `inputs/checkin1_approval.json` (refuses without a valid checkin1 + a cost_preflight artifact — the chain checkin1→budget→approval→compute is forced); NEW `.claude/hooks/pretooluse-bash.sh` (PreToolUse, matcher Bash) blocks a GEN_LAUNCH_RE command BEFORE execution when detached (nohup/setsid), pre-intake (marker+no run), unapproved (smoke/full/scan without the artifact), recipe-less (D7 pre-exec via assert_pre_generate), or unsupervised (no run_stage/stage_supervisor/run-pipeline-native.sh); invariant `approval-before-compute` (case 24, `{21 + 3}`) is the post-hoc twin (anti-handroll: generated_by must be the approve tool). Gotcha captured in-file: hook JSON travels via env var — a heredoc swallows piped stdin (the CLAUDE.md conda gotcha applies to hooks).
- **Why:** the audit's core finding — the workflow's most important gate (no heavy compute before the CHECK-IN 1 go-ahead) had NO artifact and NO pre-exec enforcement; the old pre-generate guard fired only AFTER the launch returned.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_approval_chain.py" -q` (15 passed incl. settings wiring)

### CR-125 — stage-drift + ledger-empty Stop branch (R3/H2+H8)
- **Date registered:** 2026-07-11
- **What:** `stop_dispatch.py` gains `branch_stage_drift` ("stage-drift"): BLOCKS turn-end when the disk-derived stage (sr_yields/exclusion/scan/result artifacts) is AHEAD of `run_state.current_step` (the cursor is not optional — run `workflow_state.py advance`), and when the run progressed to ≥generation with BOTH `skills_invoked` and `compute_launched` empty (observer-dead alarm → use the record fallback + check the wiring). Selftest case + 5 pytest cases. (The DRIVE branch already surfaces next_required — verified as-built.)
- **Why:** R3 audit H2/H8 — the state machine was voluntary (skip `advance` and every step-keyed gate stays unarmed) and a dead observer was silent.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_stop_dispatch_drift.py" -q`

### CR-126 — enforcement-surface self-protection (R3/H3, catalogue N9)
- **Date registered:** 2026-07-11
- **What:** NEW `.claude/hooks/protect-enforcement.sh` (second command in the Edit-family PreToolUse block): during a PHYSICS session (route-pending marker or session-scoped run_state), Edit/Write to the enforcement surface (`settings.json`, `.claude/hooks/`, `spine_sim/`, `green_board.py`, `Makefile`, the 12 gate tools) exits 2. Dev sessions untouched. 4 pytest cases.
- **Why:** R3 audit H3 — the gates could be disarmed mid-run ("edit the test, not the code"); the card-guard protected only the two pristine cards.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_protect_enforcement.py" -q`

### CR-127 — SessionStart orientation + artifact-keyed delivery detection (R3/H6+H7)
- **Date registered:** 2026-07-11
- **What:** best-effort `.claude/hooks/sessionstart-orient.sh` (always exit 0) injects the newest run's `current_step`/`next_required` + the machinery-is-mandatory reminder at session start; `stop_dispatch.is_delivery` = `DELIVERY_RE(last_message) OR _delivery_artifacts_fresh(rundir)` (checkin2/results_deck/RESULT.md mtime ≤30 min) so the D18 umbrella + open-defect gates key on disk facts, not only prose. 4 pytest cases.
- **Why:** R3 audit H6/H7 — cross-session resume was prose-only; delivery detection was a message-regex heuristic a bland closing line could slip.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_sessionstart_orient.py" -q`

### CR-128 — catalogue N9: enforcement-disarm (pre-emptive class, R3)
- **Date registered:** 2026-07-11
- **What:** FAILURE-CATALOGUE gains **N9 — enforcement-disarm attempt** (guard = `protect-enforcement.sh`, CR-126); inventory test extended to N1–N9.
- **Verify:** `REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_failure_catalogue_spine.py" -q`

## Backfill note (changes that predate this registry)
Adjustments made before 2026-07-06 were not registered here. Their diagnoses and provenance live in
the run records — primarily the scan's RESULT.md (dev repo: `trial-runs/sleptonscan_fig3_SCAN/
RESULT.md`, which carries the µ-floor and ptj1min diagnoses, the NLO-renorm and comparison-basis
rebase provenance), `docs/validation/benchmark-guide.md` (dated re-lock history), and the
`docs/development/status.md` session log. Backfill an entry here only when a pre-registry change is
touched again.

## CR-123 · 2026-07-11 · lhe_check: non-MASS-block UFO masses + median-mass mode
- **What:** read the expected mass via its UFO lhablock (e.g. RHOINPUTS) when Block MASS lacks the
  PDG entry; add an event-median mass check mode (BW-tail robust). **Why:** catalogue C11 — the gate
  false-positived a good HVT LHE (banner MASS stale at the UFO default) and would do so for every
  non-SLHA-convention UFO. **Where-embedded:** interim guard in
  trial-runs/2026-07-08_PROJ_hvt-zprime-ww-isr-boosted/build/process_sample.sh (median gate).
- **Status:** DEFERRED — trigger: next run importing any non-SLHA UFO (or the next lhe_check touch).

## CR-124 · 2026-07-11 · pyhf_exclude: `median_at_cap` flag distinct from `at_poi_cap`
- **What:** emit a flag that is true only when the MEDIAN expected limit sits at the poi cap;
  document that `at_poi_cap` = bracket reached the cap (granularity, not a capped limit).
  **Why:** catalogue N9 — a deliverable drew finite limits as ">cap" arrows off the ambiguous flag.
  **Where-embedded:** consumer-side guard in the run's build/run_limits.py (capped := median ≥ 127.9).
- **Status:** EMBEDDED 2026-08-28 (CR-142 pickup — the registered trigger, "next pyhf_exclude.py
  touch", fired): `pyhf_exclude.compute` emits `median_at_cap` (true iff the MEDIAN expected CLs
  never crossed the level anywhere in the scan, i.e. the median limit IS the scan ceiling) with a
  LOUD WARN; `at_poi_cap` documented as bracket granularity in `docs/workflow/steps/07-exclude.md`
  §honesty flags; regression = `selftest` (`unconstrained` asserts the flag true, `normal` false).

## CR-125 · 2026-07-11 · projection runs: limit-basis declaration is mandatory (B3 guard)
- **What:** any projection/sensitivity run must declare, in its own inputs/basis_manifest.json, the
  reference σ basis of every limit curve (inclusive vs fiducial, with the transformation + fiducial
  fraction if generation cuts exist), and the Tier-B attack list gains "generation-cut ⇒ fiducial
  basis?" **Why:** catalogue B3 — a fiducial-basis limit shipped 17–53× too strong onto an inclusive
  axis; caught only by the panel. **Where-embedded:** the run's basis_manifest.json (template) +
  FAILURE-CATALOGUE B3 (Tier-B walks the catalogue); extract_yields.py field names
  (`s_at_1pb_incl`, `isr_fraction`) make the basis explicit.
- **Status:** EMBEDDED (template + catalogue); checklist-text generalization DEFERRED to the next
  summary-plot/projection checklist touch.

## CR-129 · 2026-07-11 · data-acquisition: browser-AJAX HEPData route + transcription checksum
- **What:** when hepdata.net bulk endpoints are blocked server-side (403/robot-check), harvest via
  the in-app browser: record JSON at /record/ins<ID>?format=json, table values at the site's own
  /record/data/<recid>/<table_id>/<version> AJAX endpoint; verify by a SECOND independent in-browser
  fetch with per-column sums + endpoint spot values; store as outputs/hepdata/*.json with provenance
  "browser-transcribed, internally checksummed, R6-validated". **Why:** catalogue N10 — the
  toponium-summary harvest was fully blocked at the API level. **Where-embedded:**
  docs/workflow/checklists/data-acquisition.md (browser-route recipe block).
- **Status:** EMBEDDED.

## CR-130 · 2026-07-11 · summary-plot: exact harvested values in physicist-facing check tables
- **What:** identity/spot-check rows shown at any check-in use the EXACT harvested values wherever a
  harvest exists; figure read-offs are permitted only before harvest and must be labeled "read-off".
  **Why:** catalogue A9 — CHECK-IN 2 quoted a 2.5%-off survey read-off while the exact HEPData value
  sat in outputs/hepdata/. **Where-embedded:** docs/workflow/checklists/summary-plot.md §3 (identity
  checks) + §4 (waypoint).
- **Status:** EMBEDDED.

## CR-131 · 2026-07-11 · intake initializes run_state.json for every contract (compute=none included)
- **What:** physicist-intake/route_prompt writes a minimal run_state.json (session id, contract
  pointer, empty open_defect_notes) at contract creation so verify_pack's open-defect gate (N5/G26)
  evaluates on every run. **Why:** catalogue N11 — the gate was [INFO]-skipped for the whole
  toponium-summary run. **Where-embedded:** owner = src/ravel/workflow/route_prompt.py +
  .claude/skills/physicist-intake.
- **Status:** EMBEDDED 2026-08-28 — picked up on the registered trigger (the CR-133 route_prompt
  touch): `route_prompt.py --out` now best-effort-initializes the rundir's minimal
  `run_state.json` via `workflow_state.new_state` (session id from `CLAUDE_SESSION_ID`, contract
  pointer, every ledger list empty). Regression:
  `tests/unit/test_intake_u1_defects.py::test_contract_write_initializes_run_state`.

## CR-132 · 2026-07-11 · fan-out agents persist findings incrementally
- **What:** multi-agent survey/verify fan-outs write per-agent findings to disk as they go
  (inputs/survey/<agent>.json), so a session-limit death loses only unfinished agents, not
  completed research. **Why:** catalogue D20 — 6/8 sweeps + the whole verify tier lost at a
  session limit. **Where-embedded:** owner = ORCHESTRATION.md (multi-agent practice section).
- **Status:** DEFERRED — trigger: next multi-agent survey session (interim practice: save agent
  returns to inputs/survey/ immediately, as the toponium-summary run did post-hoc).

### CR-132 — pyhf_exclude robustness: degenerate-band WARN + optimizer fallback (registered, DEFERRED)
- **Date registered:** 2026-07-13 (run 2026-07-11_SUSY-2020-04_higgsino-proj-replane close-out;
  catalogue B4 + B5). Two exit-0 failure modes observed in the house engine's domain:
  (a) expected-band DEGENERACY at weakly-constrained points (five quantiles identical; the
  band spans ×1.005 where healthy qtilde bands span ×2.5–4) — the reported µ95_exp is
  unusable while looking plausible; (b) the default scipy/SLSQP optimizer returns silently
  wrong CLs (≡1.0/0.0, neighbor-inconsistent, cross-scenario monotonicity violations) on
  tightly-constrained (luminosity-projected) workspaces, plus hard FailedMinimization crashes.
- **What (when picked up):** in `pyhf_exclude.compute`: (i) band-sanity check
  (exp_limits[4]/exp_limits[0] < 1.5 → LOUD WARN + `band_degenerate: true` in exclusion.json,
  quote as bound only); (ii) minuit-first-or-fallback optimizer policy with per-fit isolation.
  Benchmark `--full` re-baseline required (engine is benchmark-gated infra).
- **Why:** both modes shipped exit-0 wrong numbers in a live run and were caught only by
  run-local audits (band-ratio filter; cross-scenario monotonicity). The guards belong in the
  engine, not in per-run driver scripts.
- **Where-embedded (interim):** run-local guards in the SUSY-2020-04 run's build/proj_cls.py
  (minuit-first + monotonicity audit) and build/replane_run.py (BAND_RATIO_MIN filter);
  catalogue B4/B5 carry the attack signatures for Tier-B.
- **Status:** EMBEDDED 2026-08-28 (CR-142 pickup — "next dev session on statistics infra" fired):
  (i) band-sanity check landed as `band_degenerate` (+2σ/−2σ limit ratio < 1.5 → LOUD WARN +
  flag in exclusion.json, quote as bound only); (ii) the optimizer policy landed as
  `robust_optimizer` (SLSQP-first + guarded-MIGRAD fallback + sticky per-model escalation —
  per-fit isolation subsumed by escalation, which CR-005's 2018-06 evidence showed is REQUIRED:
  SLSQP is silently stuck even in NaN-free minimizations on a pocketed surface). Benchmark
  `--full` run per the pickup mandate: numerics bit-identical, no re-baseline needed.

## CR-133 · 2026-08-28 · router word-context guards + mass plausibility filtering (route_prompt.py)
- **What:** classification and mass extraction run on a VIEW of the prompt with model-description
  content masked (symbol-glossary bullets like "- $P_L$ is the left-handed projection operator."
  dropped whole; `$…$`/`$$…$$` math blanked; "projection operator" excluded as a phrase), and the
  mass extractor gained (a) comma/'and' lists sharing one trailing unit ("750, 1000, … 5000 GeV")
  and (b) plausibility guards: markdown-table rows, binning context (bins/bin edges/histogram),
  and √s/beam constants in collider context are NOT candidate masses (same-line context window).
- **Why:** the 2026-08-27 U1-leptoquark head-to-head (adjudication §II.4 honesty item 1,
  catalogue N12) classified task_mode=projection off Lagrangian glossary text and extracted
  masses [13000 (=√s), 5000, 3200 (=mT bin edge)] instead of the request's 9-value grid.
- **Where-embedded:** owner = `src/ravel/workflow/route_prompt.py`
  (`classification_view`/`extract_masses`); regression = the verbatim run-record prompt in
  `route_prompt.py --selftest` (dev tree) + the synthetic twins in
  `tests/unit/test_intake_u1_defects.py` (both trees).
- **Status:** EMBEDDED.

## CR-134 · 2026-08-28 · detector_mode `delphes-custom-uncertified` (enum + gate/check-in threading)
- **What:** new task-contract detector mode `delphes-custom-uncertified` — Delphes fast-sim
  driving a CUSTOM selection with no certified routine (the Option-C detector variant). Threaded:
  `validate_task_contract.DETECTOR_MODES` + `result_pack.DETECTOR_MODES` accept it;
  `validate_run_state.check_route` WARNs with the no-exclusion-of-record obligation (instead of a
  blank PASS); `validate_checkin` (rundir mode) FAILs a CHECK-IN 1 that does not surface the
  uncertified status when the sibling contract declares the mode; PRODUCT-CONTRACT §2 carries the
  row (fidelity ceiling: uncertified fast-sim proxy until per-SR acc×eff certification closes, T10).
- **Why:** adjudication §II.4 honesty item 6 / catalogue N13 — the U1 run had to be recorded
  detector_mode=particle-level with the actual route buried in an assumptions note.
- **Where-embedded:** owners above; regression = `tests/unit/test_intake_u1_defects.py`
  (enum acceptance, route-gate WARN, check-in surfacing) + the validators' own `--selftest`s.
- **Status:** EMBEDDED.

## CR-135 · 2026-08-28 · ledger route-noise fix: active-run resolution + contentless-route no-op
- **What:** two `workflow_state.py` defects behind the `{"utc": ""}` rows accumulating in CLOSED
  runs' `run_state.json` `routes` lists. (1) `find_active_rundir` defined "active" as "newest
  mtime", so a long-closed run matched forever — and each misdirected append refreshed the very
  mtime that kept it "newest". Now resolution is: cwd-inside-rundir first (unambiguous, even for
  a closed run being backfilled); else the newest ACTIVE ledger only — not closed (no
  `RESULT.md`) and carrying the CR-022 ownership mark (a `SESSION.lock` with a heartbeat inside
  `LOCK_FRESH_HOURS` = 24 h, session_lock's own staleness rule); else None (record self-scopes
  to a no-op). A ledger-mtime freshness arm was tried and REJECTED during the fix: the noise
  scrub itself resurrected the 2026-07-10 ledger into the window and the end-to-end hook check
  landed a fresh noise row there — any maintenance write reopens the loop. (2)
  `_norm_route` appended an audit row and rewrote the file even with an EMPTY payload (the
  router hook fires `record --kind route` blind on every physics-looking prompt; `utc` is ""
  because `WORKFLOW_STATE_UTC` is unset in hook context). State-mutator normalizers now return
  mutated-or-not; a contentless route record is a full no-op (no `routed` flip, no row, no
  rewrite). The router hook now passes `--what "$tmode"` so the D-3 reconcile write carries
  real routing content — and can only ever land on a genuinely active run. Both polluted
  ledgers scrubbed (2026-07-11 higgsino-proj-replane: 30 rows; 2026-07-10 wino-c1n2: 23 rows;
  every row was the degenerate `{"utc": ""}` shape — ledger noise, not evidence; `routed: true`
  kept as the historical fact; git history preserves the defect evidence).
- **Why:** 30+ degenerate route rows in the working tree of a run closed 2026-07-11 (some
  already committed), appended by unrelated DEV sessions whose prompts matched the router's
  physics pre-gate — ledger noise in the evidence chain, plus a standing wrong-run write hazard
  for every `--project-dir` record (observer included).
- **Where-embedded:** owner = `src/ravel/workflow/workflow_state.py`
  (`find_active_rundir`/`_rundir_is_active`/`_norm_route`/`cmd_record`) +
  `.claude/hooks/userpromptsubmit-router.sh` (`--what "$tmode"`); regression =
  `tests/unit/test_workflow_state.py` (contentless-route no-op; closed-run, stale-ledger,
  live-lock, cwd-rundir resolution) + `workflow_state.py --selftest` case 5c; DIRECTORY.md
  router-hook row updated.
- **Status:** EMBEDDED.

## CR-136 · 2026-08-28 · Annotation-number provenance guard (figure annotations must trace to artifacts)
- **What:** guard candidate against catalogue N14 (guessed annotation text on a rendered
  figure): numeric literals in `smart_annotate`/caption strings should be composed from the
  artifact dict in code, and/or a render-gate check that flags annotation numbers not present in
  any run artifact JSON.
- **Why:** run 2026-08-28_SMMEAS_hvt-zprime-ww-lowmass shipped-to-lint a waypoint figure whose
  annotation quoted a plan-stage GUESS (185–360 GeV) contradicting the machine artifact written
  by the same script invocation (140–220 GeV); caught only by eyeball at the session's last
  breath. A second same-class instance ("~3–5%" gloss) surfaced in the close-out audit.
- **Where-embedded:** owner surface = `src/ravel/plotting/mplhep_style.py`
  (`smart_annotate`/`lint_figure`) or a sibling `annotation_trace.py`; interim procedural guard =
  the close-out annotation audit recorded in that run's `VERIFICATION-LADDER.md`.
- **Status:** DEFERRED (trigger: next dev session touching mplhep_style; the run-level audit
  pattern is documented in the run's ladder + RESULT.md as the manual recipe).

## CR-137 · 2026-08-28 · Deviation entries must name every artifact carrying a superseded reading
- **What:** extend the DEVIATIONS discipline (checklists/check-ins.md): an entry that
  resolves/overturns a physics reading names each on-disk artifact that still carries the
  superseded text, so none is left stale (catalogue N15: survey.json contradicted D2 for the
  rest of the run).
- **Why:** two contradictory on-disk statements about the same EWPT bound coexisted for the
  whole run; only the close-out cross-read caught it.
- **Where-embedded:** owner surface = `docs/workflow/checklists/check-ins.md` §DEVIATION check-ins
  (doc rule) + optionally `validate_run_state.py` (grep-level: artifact named in a
  conflict-resolving entry must have mtime >= the entry's).
- **Status:** DEFERRED (trigger: next dev session in the workflow-docs track; procedural rule
  recorded here and in the run's DEVIATIONS D4).

## CR-138 · 2026-08-28 · `--live-stream` on all supervised native stages (conda-run capture defeated the stall watchdog)
- **What:** `native/scripts/run-pipeline-native.sh` — `"$CONDA" run --live-stream -n <env>`
  on exactly the eight supervised stages (madgraph, lhe_check, pythia, delphes, analysis,
  simpleanalysis, sa2json, pyhf; sub-second helper calls left captured), plus the
  `pyhf_exclude.py` cls_at() per-hypotest stderr heartbeat (flush=True, print-only).
- **Why:** plain `conda run` (conda 26.3.2) buffers child output until exit → log mtime frozen →
  `stage_supervisor.py` progress-stall kills healthy long stages (two smoke pyhf kills, rc=124;
  catalogue N16). Under capture every stage longer than its stall budget dies mid-scan.
- **Where-embedded:** the two tool files (edits in-tree); evidence chain in
  trial-runs/2026-08-28_SUSY-2018-16_slepton-fig3-fresh/DEVIATIONS.md + smoke failure.json ×2.
- **Status:** APPLIED in-tree, commit + workflow-doc embed DEFERRED to the orchestrating session
  (campaign constraint: no commits from the physics session). 52/52-point scan ran on it.

## CR-139 · 2026-08-28 · pyhf stage budget = measured floor (PYHF_MEASURED_MIN=20 min)
- **What:** `src/ravel/workflow/stage_supervisor.py` stage_budget_min(): a 20.0-min floor
  for the pyhf stage (stall 20 min / wall-kill 60 min); all other stages unchanged; selftest 3/3.
- **Why:** the "MadGraph-linear + 12-min-flat-rest" model under-budgets the workspace-sized,
  event-count-INDEPENDENT 141-SR CLs scan (measured 17.3 min solo full-stat, 18.5 min smoke);
  at 12 min the 36-min wall kill sat inside parallel=3 contention range → spurious mid-scan
  kills, each costing a full ~25-min babysitter-healed rerun.
- **Where-embedded:** stage_supervisor.py (edit in-tree); measurement provenance in the run's
  DEVIATIONS.md.
- **Status:** APPLIED in-tree, commit + embed DEFERRED to the orchestrating session (as CR-138).

## CR-140 · 2026-08-28 · certify_acceptance denominator-basis guard (A4 re-hit at the cert surface)
- **What:** guard candidate: `certify_acceptance.py` should WARN (mirroring scan_contour's
  `_basis_guard`) when the acceptance denominator σ traces to a generation log (tagged-sample σ)
  rather than a model-σ table, and its docstring should carry the tagged→inclusive conversion
  recipe (f = σ_tag/σ_incl_LO from the same table the rebase uses).
- **Why:** the fresh flagship waypoint cert FAILed with a uniform ~2.7× excess — the A4
  tagged-6 vs inclusive-4 σ-basis trap, already fixed at the limit surface (rebase), re-hit at
  the cert surface where nothing warned (catalogue A4 re-hit entry, 2026-08-28).
- **Where-embedded:** owner surface = `src/ravel/validation/certify_acceptance.py` +
  `.claude/skills/certify/SKILL.md` trap list; interim recipe in the run's DEVIATIONS.md.
- **Status:** EMBEDDED 2026-08-30 (with CR-148, the dev session that touched the file). Built as a
  SYMPTOM fingerprint rather than a σ-provenance check — the cert never sees the generation log, so
  it warns (`BASIS SUSPICION`, json `basis_suspicion`; verdict unchanged) when every evaluated
  non-tail SR sits at the same ratio (spread ≤1.25×, ≥20% from unity): uniform EXCESS names the A4
  tagged-vs-inclusive trap with the conversion recipe (A×ε_incl = A×ε_tag × f, f = σ_tag/σ_incl_LO
  from the same table the rebase uses — also in the tool docstring), uniform DEFICIT names the
  global single-cause suspects. Wired: certify SKILL.md trap row + verdict bullet,
  detector-fidelity.md §B(b) BASIS SUSPICION bullet. Detector validated on synthetic uniform-excess
  (2.69×) and uniform-deficit (0.70×) fixtures; stays quiet on the real 0L cert lanes
  (spread 1.27× > 1.25 — those are attributed to the merging-deficit ladder, not σ-basis).

## CR-141 · 2026-08-28 · Check-in anchors must be tool-computed from assembled artifacts (N17 guard)
- **What:** guard candidate: a small `anchor_check.py` (or a scan_orchestrator subcommand) that,
  given a rundir + point + reference yaml, emits the UL comparison line (mu95 x sigma_ref vs the
  published column, like-columns, with the basis chain printed) — and the check-in checklist
  requires anchor lines to come from it; validate_checkin flags a numeric anchor with no
  tool-provenance field.
- **Why:** the fresh flagship's CHECK-IN 2 anchor was hand-derived with a double-counted
  k-factor (+0.1%/-15.1% claimed; -15.6%/-28.5% actual) and the error survived until the
  step-9 Tier-B adversary (catalogue N17). Hand math around a multi-step basis chain
  (raw-mu -> flat-k patch -> per-mass k renorm -> model-sigma rebase) is exactly where a
  x1.186 slips through.
- **Where-embedded:** owner surface = `trial-runs/_infrastructure/` (new helper or
  scan_orchestrator subcommand) + `docs/workflow/checklists/check-ins.md` anchor rule +
  `validate_checkin.py`; interim recipe = the corrected derivation in the fresh run's
  DEVIATIONS close-out entry.
- **Status:** DEFERRED (trigger: next dev session in the check-in/validation track).

## CR-142 · 2026-08-28 · pyhf_exclude robust optimizer — the CR-005 silent-SLSQP failure class closed in the engine
- **What:** `pyhf_exclude.py` now runs EVERY minimization through `robust_optimizer`
  (scipy/SLSQP first — bit-identical on clean surfaces — with a NaN-guarded iminuit-MIGRAD
  fallback on any distrust signal: NaN evaluated mid-fit, reported failure, non-finite
  minimum, drifted fixed parameter; loud RuntimeError if MIGRAD finds no valid minimum).
  One distrusted fit ESCALATES the whole model to MIGRAD-first and `compute()` recomputes
  any CLs points cached before the flip — measured on 2018-06, SLSQP is silently stuck even
  in minimizations that never evaluate NaN, so per-fit signals alone leave a corrupt
  non-monotonic curve (factor-3 wrong limit). `exclusion.json` gains an `"optimizer"`
  provenance block (`escalated`, `n_minimizations`, `n_fallback`, `n_nan_flagged`,
  `n_escalated`) plus honesty flags `median_at_cap` (CR-124) and `band_degenerate` (CR-132).
- **Why:** CR-005 routine certifications (2026-08-28): on the ATLAS-SUSY-2018-06 published
  likelihood (ins1771533) the −2lnL surface has NaN pockets (histosys interpolation drives
  bins negative) and pyhf 0.7.6's default SLSQP returned the INIT vector claiming success —
  free fit −2lnL 302.52 vs the true 271.79 with mu_hat==init==1.0 — shipping mu95_obs=1.192
  with obs==exp and no error. pyhf's own minuit backend also aborts there (EDM blow-up, no
  NaN guard). Validation: the hardened tool reproduces the CR005cert anchor
  (`trial-runs/CR005cert_c1n2_300_100/outputs/anchor_official/exclusion.json`) to 4 decimals
  — mu95 0.826/0.584 vs the PUBLISHED sigma95/sigma_theory 0.828/0.587 (sub-percent) —
  and benchmark `--fast`+`--full` numerics are bit-identical to the committed baseline
  (the only `--full` deltas are two provenance BREACHes from a concurrent session's
  in-flight yoda regeneration, pre-existing this change).
- **Where-embedded:** `src/ravel/physics/pyhf_exclude.py` (`robust_optimizer` +
  `compute()` flags + `selftest` cases `nan-pocket` and `2018-06-freefit`);
  `trial-runs/_infrastructure/testdata/susy-2018-06/` (committed single-point fixture,
  provenance in its README); `docs/workflow/steps/07-exclude.md` §Optimizer robustness +
  §honesty flags; `.claude/rules/statistics.md` 🔴-trap entry;
  `docs/workflow/checklists/troubleshooting.md` symptom row. Reference implementation retired:
  the run-local `CR005cert_c1n2_300_100/config/pyhf_tnc_exclude.py` wrapper is superseded
  by the in-engine guard.
- **Status:** EMBEDDED (regression: `pyhf_exclude.py selftest`, 5/5 incl. the committed
  2018-06 fixture; benchmark fast gate OK, full gate numerics unmoved).

## CR-143 · 2026-08-28 · Census R1 absence-vs-outage verdict (a 404 is a fact, a 503 is an outage)
- **What:** `resource_census.py`'s R1 HEPData rung now CLASSIFIES its failures instead of
  collapsing them into one ERROR: a served **404** from the open record-JSON API
  (`/record/insNNNN?format=json`) returns status **`ABSENT`** — definitively no HEPData record
  exists — corroborated against INSPIRE's `external_system_identifiers` (schema `HEPDATA`);
  403/5xx/network trouble returns `ERROR` + `classification: outage-or-block` with an explicit
  "NOT evidence of absence" meaning; API-404-but-INSPIRE-lists-an-id returns
  `classification: inconsistent` (re-check manually, never conclude absence). `ABSENT` counts as
  a walked rung (`_rung_ok`), and the CHECK-IN 1 markdown line (`_r1_markdown_line`) carries the
  distinction into the physicist-facing text ("plan around absence, do not wait for an outage").
- **Why:** measured defect (taunu U1 run 2026-08-27/28, RESULT.md gap G2): the census reported
  "Cloudflare-blocked / 503" for CMS ins1684340 when in fact NO HEPData record exists (open API
  404s; INSPIRE lists no HEPDATA id) — the drop-CMS-vs-wait physicist decision hinged on a
  distinction the tool could not express. Live re-verified 2026-08-28: ins1684340 → `ABSENT`
  (404, corroborated); ins1649273 → `OK` (8 tables) unchanged.
- **Where-embedded:** `src/ravel/workflow/resource_census.py`
  (`hepdata_absence_verdict` + `_inspire_hepdata_xcheck` + `_rung_ok` + `_r1_markdown_line`;
  selftest cases 9–10); `.claude/skills/resource-sweep/SKILL.md` (+ mirror) §R1 absence-vs-outage
  + stop condition; `docs/workflow/steps/02-inputs.md` sweep block; `docs/workflow/checklists/troubleshooting.md`
  symptom row; pytest `tests/unit/test_resource_census_r1_absence.py` (7 cases).
- **Status:** EMBEDDED (selftest 10/10; new pytest 7/7 + existing census tests green; live
  verdicts reproduced on both records).

## CR-144 · 2026-08-28 · hepdata_fetch --tables fallback via the open /record/data endpoint
- **What:** `hepdata_fetch.py --tables` now auto-falls back to the OPEN internal endpoint
  `https://www.hepdata.net/record/data/<recid>/<table_id>/<version>` (recid, table ids, and
  version all read from the open record JSON — `record_data_index`) when the hepdata-cli route
  is unavailable or fails. Same verify-after-download integrity contract as the primary route:
  EVERY table the record lists must land, parse as JSON, and carry a non-empty `values[]`, else
  RuntimeError → the loud nonzero exit; tables land as `tables/<slug>_data.json`, classified by
  the (now module-level, shared) `classify`; the manifest records `tables_route` +
  `tables_route_note`. Also fixed in passing: `_open()`'s TLS retry referenced an undefined
  `_VERIFIED_CTX` (latent NameError; now the module-level certifi context, never bypassing
  verification per CR-021).
- **Why:** measured defect (taunu U1 run 2026-08-28, RESULT.md gap G3): the tool documented the
  `/download/table/...` Cloudflare-403 but did not know the open internal endpoint that serves
  the identical content — the run fetched all 8 tables of ins1649273 through it by hand
  (`build/r5_parse_tables.py` provenance, recid 80812 v3). Live re-verified 2026-08-28: with no
  hepdata-cli in the env, `--tables --inspire ins1649273` falls back, lands 8/8 verified tables
  (values bit-identical to the run's saved copies), exit 0.
- **Where-embedded:** `src/ravel/workflow/hepdata_fetch.py` (docstring source hierarchy
  + `record_data_index` + `fetch_tables_via_record_data` + `_tables_via_hepdata_cli` refactor);
  `docs/workflow/README.md` tool table; `docs/workflow/checklists/data-acquisition.md` full-table route
  row; `docs/workflow/steps/06-acquire-data.md` §6.4 comment + last-resort paragraph (browser demoted
  to after BOTH script routes); `docs/workflow/checklists/troubleshooting.md` symptom row; pytest
  `tests/unit/test_hepdata_fetch_tables_fallback.py` (7 cases).
- **Status:** EMBEDDED (pytest 7/7; live fallback fetch verified on ins1649273).

## CR-145 · 2026-08-29 · pythia_shower `<N>` marked MANDATORY (silent 1000/N truncation, catalogue C13)
- **What:** run-stage skill §Shower now flags the third positional arg `<N>` as a 🔴 silent
  trap: omitted, Pythia's `Main:numberOfEvents` default showers exactly 1000 events of any LHE
  with exit 0 (σ-normalization survives; statistics silently 1000/N). Documented pairing: pass
  `<N>` = the LHE event count AND gate analyzed-count == LHE-count downstream (the 2408.00049
  width run's `build/gen_point.py` 8b hard gate is the worked example).
- **Why:** measured incident (2408.00049 width run 2026-08-28, DEVIATIONS entry 3): the first
  20k campaign wave showered 1000/20000 per point, exit 0; caught only by a cutflow-vs-LHE
  count diff. The binary itself cannot warn (compiled); the call-site idiom is the owner.
- **Where-embedded:** `.claude/skills/run-stage/SKILL.md` §Shower; catalogue C13 (attack
  replay: diff analyzed-event count vs banner nevents per point).
- **Status:** EMBEDDED (doc guard; driver-gate pattern proven in-run — 18/18 points verified
  20000/20000).

## CR-146 · 2026-08-29 · lhe_check width-aware mode (per-event mass gate false-FAILs wide lineshapes, catalogue C14)
- **What:** give `lhe_check.py` a `--width-aware`/`--gamma-over-m` mode: above a width
  threshold (Γ/m ≳ few %) replace the per-event ±3Γ mass check with banner assertions (MASS
  exact, DECAY width within tolerance) while keeping producer-complete/weights/merged gates.
- **Why:** measured incident (2408.00049 width run, DEVIATIONS entry 6): the ±3Γ per-event
  check rejected a legitimate bwcutoff=15Γ tail event at Γ/m=0.15; the run worked around it
  in-driver (narrow points keep the full gate, wide points banner-assert).
- **Where-embedded:** recipe in catalogue C14 + the run's `inputs/width_conventions.md` (W4) and
  `build/gen_point.py`; tool change not yet made.
- **Status:** DEFERRED — trigger: the next run generating hand-set-width (Γ/m ≥ 0.05) samples.

## CR-147 · 2026-08-29 · plot-lint occupancy sampler must interpolate along segments (catalogue N20)
- **What:** `mplhep_style._occupancy_points` samples only artist VERTICES; a legend/annotation
  box over a sparse polyline (few markers, long segments) counts ≤tol_points vertices and
  passes while the translucent frame visibly washes the curve. Fix: densify each Line2D by
  interpolating points along segments (e.g. every ~1% of the axes diagonal) before scoring.
- **Why:** measured miss (2408.00049 width figure 2026-08-29, DEVIATIONS entry 10): a 9-entry
  legend at upper-center faded three 6-vertex curves; `enforce_lint` passed; caught by eye.
- **Where-embedded:** `src/ravel/plotting/mplhep_style.py::_occupancy_points` now
  transforms the actual Line2D path into display coordinates, clips to the visible rectangle,
  and samples segments at roughly 1% of the axes diagonal (bounded per segment). Mixed
  axes/data and logarithmic transforms, step paths, and nonfinite subpath breaks are preserved;
  marker-only and invisible artists do not acquire a fictitious connecting stroke.
- **Verification:** `tests/unit/test_plot_lint_segments.py`: 11 regression cases pass,
  including sparse crossing/noncrossing lines, mixed/log transforms, nonfinite gaps, steps,
  marker-only/invisible lines, and distant clipped endpoints. Four crossing regressions failed
  before the change. `python3 src/ravel/validation/plot_lint.py --selftest` passes with
  the colliding fixture rejected and the house-helper fixture clean.
- **Status:** IMPLEMENTED 2026-09-05 (development session). Occupancy remains an approximate
  geometric lint; visual figure review remains necessary.

## CR-148 · 2026-08-30 · certify_acceptance FAIL CAUSE names the actual driving_ok=False cause
- **What:** `certify_acceptance.py` printed the unevaluable-lookup FAIL cause ("could not be
  evaluated against a published value … comparison unusable") for EVERY driving_ok=False —
  including driving SRs that WERE read at an exact published grid node and simply missed
  `--driving-tol`. The reason ladder now splits the two causes: **unevaluable** (missing/unmapped
  published value or routine yield → fix the inputs) vs **evaluated-but-over-tolerance** (names
  the SRs + worst residual → the comparison worked, diagnose the physics via the attribution
  rows); the mixed case prints both, the ladder FAIL (bounded-tol exceeds 1.5× the µ95 bound /
  off-grid) gets its own named cause, and the json gains `fail_reason` + `basis_suspicion`
  fields. Verdict logic and the machine-parsed `verdict` field are untouched.
- **Why:** observed 4× (CR005cert_c1n2_300_100 WORKLOG 2026-08-28; the three 0L cert lanes
  CR005cert_{ss_1200_600,gg_2200_600,gg1step_2200_600} 2026-08-29, logs/cert.log): every lane had
  real evaluated ratios (0.5–0.7) yet the FAIL CAUSE sent the reader hunting a --grid/--region-map
  lookup problem that did not exist.
- **Where-embedded:** `src/ravel/validation/certify_acceptance.py` (reason ladder +
  docstring); `docs/workflow/checklists/detector-fidelity.md` §B(b) "FAIL CAUSE" bullet — and that
  block's invocation corrected to the real interface (stale `--acceff`/`--exclusion` flags →
  `--acceptance`, `--region-map`, `--acc-unit-scale`, `--dm`); `.claude/skills/certify/SKILL.md`
  verdict bullets (mirrored). Verified on 6 synthetic fixture scenarios (over-tol / unmapped /
  mixed / PASS / uniform-excess / uniform-deficit) + a re-run of the real CR005cert_ss_1200_600
  cert: identical verdict/residuals, corrected cause line.
- **Status:** EMBEDDED (benchmark fast gate OK; not in the benchmark's gated-infra path).


## CR-149 · 2026-09-05 · strict contracts, bound approvals, scoped evidence, reproducible distribution
- **What:** strict task-contract schema and JSON parsing at CLI/approval/lifecycle/preexecution
  entry points; v2 approvals bound to contract/check-in/budget bytes; explicit scan-rung checks;
  standalone cached-replay wheel with hashed dependency lock; complete historical validation
  pages separated by statistical/acceptance/end-to-end scope; source-complete integrity gates;
  safe non-destructive export and fast-forward publication; prospective crossed-experiment accounting.
- **Why:** reproduced malformed contracts, validator bypasses in live paths, malformed/stale
  approval acceptance, missing claim/artifact masking, headline overstatement, and a public/local
  distribution gap. The fresh full cached replay also retained two missing-YODA breaches.
- **Where-embedded:** `docs/development/history/2026-09-05-hardening.md` records the full diagnosis and
  next scientific experiments; `docs/reference/task-contract.md`, `docs/cli.md`,
  `docs/research/2026-09-05-competitive-design-and-validation.md`, the tests and CI bind the changes.
- **Status:** IMPLEMENTED with regression validation. This is engineering evidence, not a new
  acceptance closure, unhinted autonomy measurement, or causal superiority result. Remaining
  command-recognition and actual resource-consumption boundaries are documented explicitly.


## CR-150 · 2026-09-05 · scientific result contracts and durable capability execution
- **What:** implement the seven architecture priorities together: lossless limits with primary-source binding; approved artifact-bound comparison certificates; explicit native normalization; exact capability plans and executor approval; grounded intent; current entry/state handoff; durable attempts, dependencies, process ownership and failure recovery.
- **Why:** concrete local/public diagnosis plus independent review exposed scientific value inconsistencies, unsupported observed projection semantics, denied-intent drift, process/output ownership gaps, missing new-entry approval checks and overclaimed task completion.
- **Where-embedded:** `docs/reference/scientific-results.md`, `docs/workflow/reference/durable-execution.md`, `docs/workflow/reference/native-pipeline.md`, `docs/cli.md`, the intake/certify/run-stage/run-scan skills, statistics/verification steps and current state/roadmap. Full implementation and verification record: `docs/development/history/2026-09-05-architecture-hardening.md`.
- **Status:** EMBEDDED and source-verified. All twelve independent findings were repaired and rechecked; 1,089 source tests and all 40 enabled wheel/CLI tests passed. Source publication, aggregate and evidence gates passed. Public export additionally exposed and repaired two fixture-only native-tool assumptions; twelve paired portability/preflight checks passed in both checkouts. The final public suite passed 1,081 tests with ten development-fixture skips and both wheel checks enabled. Remote CI is verified at publication. Historical benchmark baselines, original scientific runs and pristine cards remain preserved. These engineering changes do not establish new detector fidelity, coverage or autonomous scientific superiority.

- **CI portability addendum:** Linux CI exposed three subprocess tests that inherited the local test runner's PYTHONPATH. The current-state and durable-execution tests now use the documented module bootstrap and remove PYTHONPATH explicitly, retaining their real concurrency/termination/orphan assertions. Both test files pass in source and public checkouts; production code is unchanged. See the architecture report's clean-CI addendum.

## CR-151 · 2026-09-05 · full-population RRR diagnosis and fixed-template refits
- **What:** retain a replayable extraction of 156 campaign-point records from three 52-point slepton campaigns; expose signed residuals, interpolation brackets, nonmonotonic samples, four incomplete detector exposures and concurrent generation/PDF changes. Separately retain three resolved native refit anchors and the fourth anchor's numerical failure, the official ATLAS 150/130 GeV control and signal-model omission controls.
- **Why:** a red relative-limit cell inside an exclusion contour was mistaken for an event excess; broad negative residuals and historical median shifts had been attributed too confidently to detector/PDF effects. The source evidence contains numerical and sample-accounting defects that require separate diagnosis.
- **Where-embedded:** `evidence/audits/2026-09-05-rrr-diagnosis/`, `evidence/audits/2026-09-05-rrr-refits/`, `tests/unit/test_detector_exposure.py`, `docs/research/2026-09-05-rrr-diagnosis-and-research-program.md` and `docs/development/history/2026-09-05-rrr-and-portability.md`.
- **Status:** EMBEDDED as diagnosis, not physics closure. The forensic verifier records 1,627 unchanged archived/reference inputs and twelve focused tests. Four detector-exposure regressions independently pass. The official model agrees with the published limits within 1%; the nominal-SR-only omission control strengthens observed/expected limits by about 14%/12%. Neither result repairs the three archived scans or identifies the complete cause of the native residual. No new events were generated, and the failed native anchor remains in the four-point denominator.
- **Publication binding:** `scripts/check_rrr_audits.py` checks retained-file hashes and recomputes the diagnosis from the complete snapshot; `tests/unit/test_rrr_audit_integrity.py` adds six passing integrity controls, including independent-review regressions for omitted output inventory and contradictory snapshot identity. The publication gate also requires the cached-refit `summarize.py --check` and candidate-catalog validator. The refit's `test_summarize.py` adds nine passing retained-input/result binding tests; together with the twelve forensic tests, the 21 audit tests pass in 0.88 seconds. These are artifact/arithmetic checks, not new likelihood fits or scientific certificates.

## CR-152 · 2026-09-05 · matching contour families and reproduction closure obligations
- **What:** filter reference contours by the requested observed/expected panel and provide the expected ATLAS contour to the scan demonstration. Keep residual-cell agreement, exclusion contours, numerical convergence, detector exposure and certified reproduction as separate obligations. Embed full-population accounting and controlled effect-isolation requirements in the workflow.
- **Why:** a matching expected residual fill could still be overlaid with an observed reference contour, producing an apparent like-for-like figure. A small median or plausible detector explanation also does not establish per-point numerical/physics closure.
- **Where-embedded:** `src/ravel/plotting/scan_contour.py`, `benchmarks/plot_scan_demo.py`, `tests/unit/test_scan_rendering.py`, `evidence/audits/2026-09-05-scan-fidelity/atlas-expected-contour.yaml`, `docs/workflow/checklists/reproduction-closure.md`, `docs/workflow/checklists/scan-and-contour.md`, `docs/workflow/checklists/judgment-protocols.md` and `docs/workflow/steps/07-exclude.md`.
- **Status:** EMBEDDED. Historical scan values and median residuals remain unchanged; the expected panel now receives its own reference family. Full-suite/publication verification for this follow-up is tracked in the dated history rather than borrowed from CR-150.
- **Integration check:** the first follow-up source suite reported 1,150 passes, two skips and one stale-renderer-provenance failure. After refreshing the demonstration, the previously failing case passed within a 44-test wheel/fidelity check, which also enables both installed-wheel cases. The final complete source suite passes 1,155 tests with two release-only skips and 243 warnings in 228.48 seconds. Publication, fourteen focused evidence checks and agent-surface checks pass. The adversarial board retains 29 PASS, zero FAIL and one optional G21 SKIP; no fresh live-agent attestation is claimed. The fast cached benchmark passes without upgrading acceptance. Public-export and remote-CI verification are separate commit checks; no failure was hidden by loosening the integrity check.

## CR-153 · 2026-09-05 · macOS architecture, prerequisite and build portability
- **What:** add a read-only native doctor, ARM/Intel/Rosetta checks, compiler/SDK and conda-version probes, explicit environment prefixes, checksum-pinned Miniforge assets, pinned MG5 source acquisition and staged native builds. Add an Intel/ARM Python 3.12 CI matrix that exercises absent-stack and fake-tool cases without installing HEP software.
- **Why:** the previous bootstrap downloaded only an ARM installer, environment-name resolution could select another prefix, and the shower recipe hardcoded one compiler triplet. Presence-only checks, implicit compiler selection and direct build output replacement could hide predictable failures or damage an existing installation.
- **Where-embedded:** `src/ravel/validation/native_doctor.py`, `src/ravel/physics/native_build.py`, `environment/scripts/`, `native/scripts/`, `.github/workflows/ci.yml`, `tests/unit/test_native_portability.py`, `docs/reference/native-portability.md` and `environment/README.md`.
- **Status:** EMBEDDED with bounded local verification. Fifty-four portability tests plus two existing path tests pass; the existing Apple Silicon stack passes 33 prerequisite checks and all three build dry runs. Independent review repaired and rechecked explicit `CXX` precedence; isolated child probes now suppress bytecode writes. Independent archive/symlink-output controls pass, and all twelve reviewed file hashes remained stable. No outstanding material finding remains in this helper scope. Remote CI, clean-Mac provisioning and native Intel HEP execution are not credited until separately verified; no installed toolchain was changed by this work.

## CR-154 · 2026-09-05 · public-analysis census without unsupported capability promotion
- **What:** publish 26 curated expansion routes, a 45-entry ATLAS discovery index, primary-source metadata and repository pins, with per-route data/model/detector/statistical admission requirements. Add integrity checks that reject unsupported validation or execution promotion, missing sources, changed identities and altered saved metadata.
- **Why:** source-code availability, portal membership and compatible statistics machinery are different from an installed, scientifically validated analysis. Measurements, lifetime maps, finite-width signals, anomaly methods and open-data studies require distinct representations and closure evidence.
- **Where-embedded:** `docs/research/2026-09-05-public-hep-analysis-landscape.md`, `evidence/audits/2026-09-05-analysis-landscape/` and the research-program/closure workflow linked above.
- **Status:** EMBEDDED as a dated survey. Its positive integrity check, five rejection controls and report/link census pass. The 26 and 45 counts overlap and must not be added; the survey reports zero new scientific validations and does not upgrade the reference-task or executable-capability boards. Failed resource retrievals remain acquisition failures, not evidence of resource absence.

### CR-155 — RRR reproduction closure: profile minima, complete signal bookkeeping and retained execution
- **Date registered:** 2026-09-06 (UTC).
- **What:** Repair successful-but-inconsistent profile fits with bounded multistart, nesting, original-objective/bound/gradient checks and frozen-portfolio root validation. Add the six paper-defined slepton control regions, explicit native MC moment models, per-event reconstruction traces, source-bound replica pooling, durable compressed event I/O, native shower failure checks and stricter process/normalization planning.
- **Why:** The retained RRR discrepancy combines numerical and physical-model questions. A local-minimum branch switch, omitted control-region signal, unrepresented simulation uncertainty, a six-state/four-state comparison and incomplete provenance cannot be treated as one global normalization correction. Fresh execution also exposed valid LHE metadata parsing, zero-parton jet-existence cuts and interpreter-symlink input duplication.
- **Where-embedded:** `src/ravel/physics/pyhf_exclude.py`, `native_simpleanalysis.py`, `sa2json_native.py`, `compressed_validation.py`, `pool_replicas.py`, `native_event_io.py`, `native_pipeline.py`, `native_normalization.py`; `native/src/pythia_shower.cc`; corresponding unit/ROOT controls; `.claude/rules/statistics.md`; `docs/workflow/reference/native-pipeline.md`. The active campaign, literal authorization, prospective budget, unchanged reference sources, failures and frozen runtimes are under `trial-runs/2026-09-05_SUSY-2018-16_rrr-closure/`.
- **Status:** OPEN — the independent 20k and 40k four-state samples and six-state 20k control have completed all twelve stages and all six numerical roots. The first 60k pooled fit failed its original one-hour cap; its moments remain valid and a separate bounded retry is in preparation. Paired b-tag controls and independent figures are complete, without detector-calibration or equivalence claims. The lower-parton control is active. The retained 52-point numerical batch is paused with five successes, two preserved timeout failures and 45 ready points; the separate once-only timeout phase resolved both failures and its worker-validated summary records seven resolved and 45 ready points, preserving both original failed attempts. No full fresh-grid, truth-acceptance or physics-closure claim.
- **Verify:** The latest complete source suite passes 1,475 tests with 12 skips; the relevant native/ROOT suite passes 230 and the freshly built-wheel CLI suite passes all 40, including both isolated wheel checks. Fresh native/statistical audits replaced the stale-current-audit failure with actual revalidation, preserving the original audit bytes. A separate relevant ROOT suite passed 225 cases. Later checks include 199 integration passes with ten ROOT skips, 38 integrity passes, 50 publication/evidence passes, 59 origin tests and independently repeated derivative/reader controls. The independent 20k conditional-likelihood control matches saved CLs values within 3.975e−8 at two tested roots. The full benchmark retains two genuine missing-YODA provenance failures and unresolved acceptance cases. Final release verification remains pending after the last relevant changes.
- **Additional embedding:** `slepton_origin.py` and its tests preserve signed parent pairs, unresolved categories and original exposure; `truth_reco_response.py` supplies strict ancestry/reference joins. `campaign_budget.py` charges failed/current/archived generation attempts and pending reservations. The explicit complete-execution API leaves partial-resume semantics intact. C++ RISR output uses round-trip precision, with an independently exercised physical boundary fixture; already running frozen binaries were preserved. Read the dedicated origin history and current audit records for exact scope and hashes.

- **2026-09-06 execution/procedure follow-up:** Repair bounded cleanup and terminal timeout recording; enforce the registered 1.26-million ceiling under the original 1.28-million allocation; isolate/fix Git-hook installation tests. All 64 supervisor checks, 38 admission/storage checks plus 14 independent controls, and 75 hook/fixture checks passed. V5 preserves all common physics/inference bytes. Source-backed model-interface review replaces a universal MSOFT override claim; active merging guidance no longer exempts leptonic recoil-sensitive searches or treats a historical 5% rate comparison as a universal law. The complete follow-up source suite passes 1,533 cases with 12 optional skips. Fresh staged verification and public release remain pending. See [the follow-up record](history/2026-09-06-rrr-execution-followup.md).
