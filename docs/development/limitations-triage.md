# KNOWN-LIMITATIONS triage — DRAFT headers (roadmap §6 / W2c, checkpoint C6)

> Drafted 2026-07-07 by inspection of existing evidence ONLY (no re-investigation, no new
> experiments). One block per bold-titled bullet in `docs/reference/limitations.md`, walked in file
> order. The main session applies these headers to the file after review; this draft does not edit
> KNOWN-LIMITATIONS.md. Calibration precedent: the HEPData-download "limitation" fell to a single
> try of the documented CLI (the file's Resolved section) — every falsification-test below is held
> to that bar: the cheapest concrete experiment, runnable in ≤ a session, that would show the
> limitation is actually easy to remove. Grades: `none` = no investigation record found · `brief` =
> dated record exists but the key claim is reasoned/documented, not measured · `thorough` = measured
> and/or adversarially verified with artifacts.

---

## Physics fidelity

### 1. Cutflow fidelity is tiered, not perfect (R1)
- `entry:` cutflow-fidelity-tiered (Physics fidelity)
- `investigated-to: thorough` (2026-06-09→2026-07-06) — `framework/validation/` (4 per-analysis
  certs), `docs/validation/benchmark-guide.md` (8-case locked baseline, 2.4–13.2% with dated re-lock
  history), residual decomposed by measurement in `docs/research/reviews/shower-decay.md` (tune
  A/B: 13.2%→4.4%) and `interrogations/merging.md` (merged case 8.1%, registered), scan-scale in
  `trial-runs/sleptonscan_fig3_SCAN/RESULT.md` (24.9% same-basis median, decomposition §Honest
  assessment).
- `falsification-test:` Re-shower the certified gluino LHE with `Tune:pp=21` and re-run the cert
  (the A/B cfg recipe is in shower-decay.md; ~1–2 h) — if PASS@4.4% reproduces, the headline tier
  improves with zero new physics work, showing the "~13%" figure is a policy artifact, not a floor.
- `reopen-cost: session` (tune-policy decision + benchmark re-locks; see queue #6).
- `confidence: high` — the tiering and the ~10–20% compressed-point floor are real and repeatedly
  measured.
- **STALE:** "(gluino, attributed to merging)" — attribution CORRECTED S5/S7 (2026-06-09/10): the
  13.2% is a hard-radiation *excess* (tune-dominated; merging *reduces* it to 8.1%);
  `cases.json` notes + BENCHMARK/STATUS already carry the correction. Entry text lags them.

### 2. Higher-order σ is a flat k-factor, not a recomputation
- `entry:` flat-k-not-NLO-events (Physics fidelity)
- `investigated-to: thorough` (2026-06-09) — `docs/research/reviews/statistics.md` (k-trap
  measured: flavour-sum + single-charge; verified like-for-like k for all four cases),
  `interrogations/generation.md` (§k-verification story; NLO-event-generation deferral with stated
  cost rationale), BENCHMARK.md re-lock history. The *shape* effect of flat k is the one unmeasured
  piece (deferred with reason: "revisit only if a case's σ-shape becomes the attributed residual").
- `falsification-test:` Run aMC@NLO for the squark process at ~1k events and check the
  negative-weight fraction + whether `lhe_check`'s single-weight contract survives — directly tests
  the "heavyweight, breaks the contract" assumption keeping this a limitation.
- `reopen-cost: multi-session` (real NLO event adoption touches generation, shower weights, gates).
- `confidence: high` — as stated; the standing degeneracy/charge trap is documented and guarded.
- **STALE (minor):** "the slepton run keeps its documented flat k=1.18" — true only of the
  2026-06-06 single-point run; the flagship fig3 scan was re-normalized 2026-07-04 to per-mass
  NLO+NLL k(m)=1.381–1.407 (`scan_orchestrator assemble --nlo-renorm`, scan RESULT.md).

### 3. PDF and scale uncertainty bands are NOT propagated
- `entry:` pdf-scale-bands-not-propagated (Physics fidelity)
- `investigated-to: brief` (2026-06-09) — `docs/research/reviews/generation.md` GEN-D2/D3 +
  §Deferred (dated, honest statement of the use_syst=True vs single-weight-contract conflict); no
  measurement of the band's size on any case exists anywhere (no PDF-member or µR/µF variation has
  ever been run).
- `falsification-test:` Push one existing multiweight test LHE through the current Rivet invocation
  once (without `--skip-weights`) and inspect the YODA — if per-weight histograms come out usable,
  the claimed hard conflict with the analysis path is soft, and band propagation is plumbing, not a
  rebuild.
- `reopen-cost: multi-session` (per entry's own honest resolution: multiweight LHEs + per-weight
  analysis path + gate re-lock).
- `confidence: high` — the limitation is real and its partial-coverage statement (k central value
  only) is correctly scoped.

### 4. Shower tune: Monash 2013, not ATLAS A14
- `entry:` shower-tune-monash-not-a14 (Physics fidelity)
- `investigated-to: thorough` (2026-06-09/10) — `docs/research/reviews/shower-decay.md` SD-D1
  (measured A/B, bit-identical Monash control, per-SR table, −8%/−17% shifts, WARN→PASS) +
  `interrogations/merging.md` (tune × merging: all four combinations measured, A14-merged
  PASS@7.4%); `docs/development/status.md` records the per-experiment-emulation-for-NEW-runs decision.
- `falsification-test:` Re-shower the two squark certified LHEs under A14 and re-cert (~1–2 h
  total) — the predicted 1–2% shifts are the only unmeasured input left before the pipeline-wide
  adoption decision; if they hold, the limitation reduces to a bookkeeping re-lock.
- `reopen-cost: session` (decision + 4 re-shower/re-certs + BENCHMARK re-lock entries).
- `confidence: high` — best-evidenced entry in the file; numbers already in it.
- Not stale (entry already says "STILL OPEN post-Session-3" and cites the study).

### 5. Decay spin correlations / polarization not modeled
- `entry:` slha-decay-spin-correlations (Physics fidelity)
- `investigated-to: brief` (2026-06-09) — `docs/research/reviews/shower-decay.md` SD-D3: the
  isotropy hierarchy is carefully argued (scalar exact / gluino mild / C1N2 real loss) and the
  rapidityOrder myth was source-verified dead, but the polarization effect on lepton acceptance was
  never *measured* — "secondary to the fast-sim floor" is a judgment, not a number.
- `falsification-test:` MadSpin-decay one existing C1N2 LHE (mg5 env, LHE-level, ~1 h) and compare
  lepton-pT spectra + SR3L yields against the phase-space sample — a null result closes the entry
  at the certified point; a real shift sizes it.
- `reopen-cost: session` (the falsification test IS most of the fix's evaluation).
- `confidence: high` that the modeling gap is real; `med` on the "secondary" scoping (unmeasured).

### 6. Fast detector model (no Geant4)
- `entry:` fast-detector-no-geant4 (Physics fidelity)
- `investigated-to: thorough` (2026-06-09→2026-07-04) — bounded per-analysis by the certs
  (`framework/validation/`, BENCHMARK baselines); named THE leading residual of the flagship scan
  after normalization+basis fixes (fig3 RESULT.md decomposition item 3, ~26%→24.9% median);
  slepton SA-path bound in `validation/ATLAS-SUSY-2018-16_slepton.md` (~2×, causes enumerated).
- `falsification-test:` One compressed scan point regenerated at high stats (~100k) with the
  verified soft-lepton Delphes tuning (the CR-004 recipe, single point ≈ 1 h native) — if its cell
  residual drops well below ~20%, the "dominant intrinsic limitation" is partly tuning debt, not
  floor.
- `reopen-cost: blocked-external` for full sim (no Geant4 on this hardware, ever) /
  `session` for the tuning-debt component.
- `confidence: high`.
- **STALE (minor):** "Neither tunes the low-pT efficiencies" overstates — the SA/Delphes path used
  in the fig3 scan carries the RRR §3.2-tuned soft-lepton card (scan RESULT.md); *verified
  ATLAS-grade* tuning remains absent (that clause stands).

### 7. R6 visual fidelity is checklist-verified, not machine-scored
- `entry:` r6-visual-fidelity-not-machine-scored (Physics fidelity)
- `investigated-to: brief` — mechanics side is thorough (2026-06-09 `interrogations/
  visualization.md` full defect table; 2026-07-06 CR-015/CR-016 with live-caught defects +
  selftest), but the actual residual gap — machine-scoring figure CONTENT against the published
  figure — has design notes only (BENCHMARK.md Phase-2 hooks; CAPABILITY-ROADMAP §7 Tier 2).
- `falsification-test:` Run ONE bounded visual-critique pass (roadmap §7 protocol: fresh-context
  agent, side-by-side, structural-mismatch list) on the existing fig3 composite — if it emits
  correct structural diffs in one shot, "not machine-scored" is a session's build, not research.
- `reopen-cost: session` (and it is already scheduled: overnight checkpoint C13 owns exactly this).
- `confidence: high` the content-scoring gap is real; the entry's framing is outdated.
- **STALE — needs rewrite to the two-tier state:** (a) CR-016 landed the machine LINT gate
  (occlusion/box-overlap/tick collisions now exit-4-enforced inside every house renderer —
  "figure content could regress silently" is now only true of *physics* content, not layout);
  (b) the figure-contract (declare/extract/compose + check-in side-by-side, catalogue A1/A2)
  guards content by workflow gate; (c) the C1N2 run-local overlay divergence note remains valid
  (run record, deliberately untouched).

## Statistical / data

### 8. Signal-MC statistical uncertainty not in the counting model
- `entry:` signal-mc-stat-not-in-model (Statistical / data)
- `investigated-to: brief` (2026-06-09) — `interrogations/statistics.md` §Deferred +
  `interrogations/analysis.md` AN-D8: dated, quantified deferral rationale (tail SRs report-only,
  O(1%) of combined sensitivity), but the O(1%) was estimated, never measured.
- `falsification-test:` Add per-SR `s ± ds` (from the existing YODA sumW2) as a shapesys to ONE
  case's counting model and re-run `pyhf_exclude` (no MC; hours) — µ₉₅ shift <1% confirms and
  effectively closes the entry; more reopens it with a number attached.
- `reopen-cost: hours` (single-case A/B) to `session` (adopting the model upgrade + re-locks).
- `confidence: med` — direction certain, magnitude asserted.

### 9. Published-grid certification off-node is 1-D, span-limited
- `entry:` grid-cert-1d-interpolation (Statistical / data)
- `investigated-to: thorough` (2026-06-09) — `interrogations/analysis.md` AN-D2/D6: the missing
  (1000,100) node verified, the nearest-node tie exposed, 1-D interp built, span guard
  physics-justified (A×ε ~5× across the 600 GeV gap), all paths exercised with regression evidence.
- `falsification-test:` Run `scipy.interpolate.LinearNDInterpolator` (2-D barycentric) over the
  published triangular gluino grid and evaluate at (1000,100), comparing to the flagged
  NEAREST-(1000,0) value — an afternoon script that directly tests whether the 2-D upgrade
  dissolves the known-instance bias.
- `reopen-cost: session` (2-D interp in `validate_cutflow.py`, regression-free on exact-node cases).
- `confidence: high`.
- **STALE (one clause):** "a registry-notes correction is an open item" — done: `cases.json`
  gluino entries now state "NO (1000,100) node exists; the cert compares against the nearest node
  (1000,0)" with the corrected attribution. Residual open item is the 2-D interpolation only.

### 10. Counting model is an approximation
- `entry:` counting-model-approximation (Statistical / data)
- `investigated-to: thorough` (2026-06-09) — `interrogations/statistics.md` (fitted-bkg input
  fix measured 1.49×→1.01; combined C1N2 mode adopted with honest accumulation; toys spot-check
  0.0467 vs 0.05); BENCHMARK.md per-case caveat quantifies the worst case (C1N2 5.0× vs published
  combined fit, causes named). Mode-A (published likelihood) is built but never yet exercised
  end-to-end on a real case.
- `falsification-test:` Complete the idx8 Mode-A resume (ATLAS_2022_I2182381: published pyhf
  likelihood already on disk, WORKLOG commands recorded, ~30 min) and compare Mode-A vs counting
  µ₉₅ on the same signal — the first direct measurement of what the approximation costs.
- `reopen-cost: hours` (idx8 resume) for the measurement; `multi-session` for likelihood-first
  breadth.
- `confidence: high`.

### 11. Likelihood↔selection pairing
- `entry:` likelihood-selection-pairing (Statistical / data)
- `investigated-to: none` — no investigation record found (the entry's own sentence is the entire
  record). Weak implicit evidence only: the native patch applies cleanly to the published bkg-only
  workspace (a gross structural mismatch would crash pyhf) and native-vs-container parity is 0.51%
  — neither is a semantic pairing check.
- `falsification-test:` Structurally diff the signal patch's channel/bin names + counts against the
  published EwkCompressed2018 bkg-only workspace (`pyhf inspect` / jq, minutes) and spot-check
  three SR names against the paper's SR definitions — clean result verifies the assertion and
  closes the entry.
- `reopen-cost: hours`.
- `confidence: med` — the assertion is plausibly fine, but "asserted, not verified" is literally
  the current state.

### 12. Result-quality fixes land via the CHANGES-REGISTRY
- `entry:` cr-registry-pointer (pre-fix ptj1min=0 native basis) (Statistical / data)
- `investigated-to: thorough` (2026-07-06) — CR-001 (measured hyper-excluded pathology, fix +
  selftest + record-scan re-assembly: 26.2%→24.9%/24.1% over 50 honest cells) and CR-002 (measured
  ×2.14 σ_tag split at m=200, 500-evt A/B) in `docs/development/change-registry.md` +
  FAILURE-CATALOGUE B1/B2. The residual limitation = every pre-2026-07-06 native sample sits on the
  ptj1min=0 basis until CR-004.
- `falsification-test:` Regenerate ONE fig3 point (e.g. m200_dm10) native at ptj1min=50/20k events
  (~30–50 min) and diff µ₉₅ + per-SR yields vs the recorded point — sizes whether CR-004's full
  rescan can move the 24.9% headline before committing an overnight of MC.
- `reopen-cost: session` (single-point probe) / `multi-session` (full 52-point CR-004, ~7–11 h
  wall at 4-way parallel).
- `confidence: high`. Entry is current (written 2026-07-06).

## Coverage / complexity

### 13. Complex routines: demonstrated, not yet broad
- `entry:` complex-routines-breadth (Coverage / complexity)
- `investigated-to: brief` — the demonstration leg is thorough (jigsaw run certified,
  `validation/ATLAS_2018_I1676551_c1n2.md`, `checklists/complex-analysis.md`), and the S3 census
  (`interrogations/generality.md`) measured breadth where counting applies (3/3 full-chain, 0.92–
  0.98 recovery, incl. a combined 7-channel fit); but the specific remaining claim — multi-bin /
  control-region-likelihood breadth — has zero cases (idx8 Mode-A is the queued first).
- `falsification-test:` Same as entry 10: the idx8 Mode-A resume (~30 min) is simultaneously the
  first CR-constrained multi-bin-likelihood case; landing it converts "demonstrated, not broad"
  into "one likelihood case, N counting cases" with a number.
- `reopen-cost: hours` (idx8) to `multi-session` (the 5 NOT-REACHED census targets).
- `confidence: high` the breadth gap is real; scope should be restated post-census.
- **STALE (minor):** "(Session 3)" — Session 3 happened (2026-06-11) and added 3 registered cases;
  the entry predates the census's own boundary measurement and STATUS's queued-resumes list.

### 14. Native SimpleAnalysis backend is single-analysis today (CR-005)
- `entry:` native-sa-single-analysis (Coverage / complexity)
- `investigated-to: thorough` (2026-06-16, record backfilled 2026-07-06) — the port itself is
  validated bit-for-bit (141/141 SRs; µ₉₅ parity 0.51%; `trial-runs/2026-06-16_slepton_200-150_native/
  RESULT.md`), and the generalization boundary is precisely scoped in
  `docs/workflow/reference/native-pipeline.md` §SCOPE (RJR `--objects` interface already general;
  object-selection + SR-cascade is the per-analysis work) + CR-005.
- `falsification-test:` Port ONE more SA routine's object selection + SR cascade (pick a simple
  counting-style routine from the container set) and check per-SR parity against the container on
  one existing sample — if a day yields bit-parity, "single-analysis" is backlog, not architecture.
- `reopen-cost: session` per simple analysis; `multi-session` for RJR-class analyses.
- `confidence: high`. Current (CR-005 registered 2026-07-06).

### 15. SimpleAnalysis routine availability (container fallback)
- `entry:` sa-routine-availability-container (Coverage / complexity)
- `investigated-to: brief` (2026-07-06/07) — the availability question is now enumerated by the
  overnight censuses (`overnight-roadmap/inputs/census-substrate-local.md`: 79 local SA routines
  classified; `census-substrate-web.md`: 81 public routines, ~95% SUSY), but the claimed remedy
  path (runtime-add / container rebuild "needs build rights") has never been attempted — no record.
- `falsification-test:` Compile one extra `.cxx` inside the running `:master` container once
  (SimpleAnalysis supports add-on analysis builds) — if it compiles and runs under emulation, the
  "needs container build rights" barrier is overstated.
- `reopen-cost: session` (podman emulation makes even a compile slow).
- `confidence: med` — the availability fact is solid; the remedy-cost claim is untested.

### 16. Statistical-paradigm boundary: ~40% shape/template-fit
- `entry:` paradigm-boundary-40pct-shape-fit (Coverage / complexity)
- `investigated-to: thorough` (2026-06-11, external confirmation 2026-06-21 recorded 2026-07-06) —
  pre-registered seeded census, 8/20, `interrogations/generality.md`; confirmed on a fresh external
  paper (arXiv:2408.00049 BLOCKED(statistical-paradigm), same file §2026-06-21); refusal behavior
  contracted in PRODUCT-CONTRACT §6.1 + CR-009 stat_mode enums.
- `falsification-test:` Prototype a binned shape fit for ONE published bump-hunt spectrum (HEPData
  binned data + smooth-background parametrization in pyhf) at a single mass point and compare to
  the published limit — a half-day spike that tests whether the boundary is a build away rather
  than a paradigm wall.
- `reopen-cost: multi-session` (a real binned-fit product); the costed decision memo is
  `session` and is already scheduled (overnight C14).
- `confidence: high` — the strongest-evidenced boundary in the file.

## Infrastructure

### 17. MadAnalysis5 built; CheckMATE2 runtime-blocked (Pythia ABI)
- `entry:` checkmate2-runtime-blocked (Infrastructure)
- `investigated-to: thorough` — the entry itself is the dated saga (build chain, shim, 8.2-vs-8.3
  ABI diagnosis, failed master-Delphes attempt, bounded remaining path), corroborated by
  `framework/overnight/PROGRESS.md` + `ENVIRONMENT.md` (recast/py82 envs); R7 independence is
  explicitly decoupled (SModelS working + MA5 built; `docs/validation/studies/gluino-crosscheck.md`, AUDIT R7
  PASS with 4 recorded cross-checks).
- `falsification-test:` Build a pinned Delphes 3.5.0 against the py82 Pythia + conda ROOT (the
  entry's own named path) and run one CheckMATE example — a configure+make afternoon that directly
  tests the "packaging, not code defect" claim.
- `reopen-cost: session` (bounded path) — but see queue: deliberately ranked OUT (R7 is green
  without it; third engine is redundant).
- `confidence: high` — the diagnosis is precise and multiply recorded.

### 18. Recursive-jigsaw EWK search — done
- `entry:` rjr-ewk-done (Infrastructure) — **not a limitation; a resolved record.**
- `investigated-to: thorough` (2026-06-08/09) — run + cert (`validation/ATLAS_2018_I1676551_c1n2.md`),
  registered benchmark case, the k<1 guard and card-trap fixes it produced are embedded.
- `falsification-test:` n/a (nothing to falsify — it is a completion notice).
- `reopen-cost:` n/a. `confidence: high`.
- **STALE (placement):** belongs in the "Resolved" section (or deletion), not under Infrastructure;
  keeping "done" items in the limitations list dilutes the file's contract.

### 19. Container path (legacy SA fallback) is slow
- `entry:` container-fallback-slow (Infrastructure)
- `investigated-to: thorough` (2026-06-16→2026-07-06) — the ~9 h/point sequential cost and its
  replacement are measured and recorded (`docs/workflow/reference/native-pipeline.md`: native 30–50
  min/point, parallel, validated; FAILURE-CATALOGUE D2 documents the doc-drift class and the
  reconciliation grep). Known split (operator record): the cost is dominated by MadGraph under x86
  emulation, not SimpleAnalysis itself (~seconds) — the repo states the aggregate, not the split.
- `falsification-test:` Run ONE hybrid point — native MadGraph/Pythia/Delphes feeding only the SA
  stage into the warm x86 container — if the point lands in well under an hour, the fallback's
  "~9 h" scoping collapses to "SA-in-container is cheap; never emulate generation".
- `reopen-cost: session` (hybrid driver is a recombination of existing stages).
- `confidence: high` for the numbers as stated; `med` for the implicit "the whole fallback chain
  must be slow" framing the hybrid test would refute.

## Resolved this pass (HEPData retrievability) — no header needed
Not a bold-titled limitation: it is the file's own calibration precedent (a "limitation" that fell
to one documented-CLI try). Keep verbatim as the Resolved exemplar the triage points at.

---

## Ranked re-investigation queue (payoff × ease; top 8)

Separate deep-dive sessions are opened only for queue heads, per roadmap §6. Items 1–5 are
hour-scale; 6–8 are session-scale.

1. **idx8 Mode-A likelihood case** (entries 10+13) — ~30 min resume, likelihood already on disk;
   first-ever Mode-A case simultaneously measures the counting-model approximation AND breaks the
   multi-bin/CR breadth zero. Highest payoff per minute in the repo.
2. **CR-018 — lhe_check weight-sign false-FAIL adjudication** (routed here from CHANGES-REGISTRY;
   mining CH-5) — hours: gunzip the 2026-06-06 reference LHE, count ALL negative weights (not the
   200-sample), decide numerical-artifact vs leak, then either a fractional threshold (FAIL >~0.5%
   negative at LO) or a per-sample exemption + FAILURE-CATALOGUE C-entry. A MANDATORY gate that
   false-FAILs a validated input is the second guard-false-FAIL (after C2) — gate trust is the
   payoff.
3. **Likelihood↔selection pairing structural diff** (entry 11) — hours; closes the file's only
   `none`-graded entry with a jq/pyhf-inspect afternoon; either verifies a standing assertion under
   the flagship analysis or catches a real mismatch early.
4. **Signal-MC staterror one-case A/B** (entry 8) — hours, no MC; converts an estimated "O(1%)"
   into a measured number and probably closes the entry.
5. **Single-point ptj1min=50 probe** (entry 12 / CR-004 sizing) — ~1 h MC; tells whether the full
   52-point rescan can actually move the 24.9% headline before anyone spends an overnight on it.
6. **A14 tune decision package** (entries 1+4) — session; the squark A14 re-shower is the last
   unmeasured input, then adopt/decline pipeline-wide with re-locks. Biggest single already-measured
   fidelity lever (gluino 13.2%→4.4%).
7. **2-D grid interpolation** (entry 9) — session; removes the last flagged NEAREST bias
   ((1000,0) vs (1000,100)) from the gluino cert; the falsification script is half the
   implementation.
8. **Multiweight-Rivet blocker probe** (entry 3) — session; one multiweight LHE through the
   current Rivet invocation tests the claimed hard conflict that keeps PDF/scale bands parked in
   Phase-2.

**Deliberately ranked out / owned elsewhere:** R6 Tier-2 content scoring (entry 7) — owned by
overnight C13 (one-shot critique loop is the falsification test; promote to the queue only if C13
is skipped). Shape-fit boundary (entry 16) — owned by C14's costed decision memo; the pyhf
binned-fit spike enters the queue only if the memo recommends building. CheckMATE runtime (entry
17) — R7 is green with SModelS+MA5; a redundant third engine does not beat any item above on
payoff. SA runtime-add probe (entry 15) and the MadSpin A/B (entry 5) are the next two below the
cut, in that order.
