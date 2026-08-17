# The generality census (Session 3, 2026-06-11) — arbitrary analyses, autonomous overnight

_The product claim under test: a physicist brings ANY published search + a hypothetical model; the
pipeline autonomously delivers the overlay and the 95% CLs verdict. The only honest test of "any" is
a pre-registered census — no curation. This report is the measurement._

## Pre-registration (committed before any processing — commit 28d2b02 lineage)
- **Predicate** (verbatim in `framework/overnight-s3/census.json` + RULES.md): installed Rivet share,
  Experiment ATLAS|CMS, beam 13 TeV (`[13000]` or `[[6500,6500]]`; reject 13.6 TeV), `/search/i`
  anywhere in the `.info`, minus OBSOLETE/SupersededBy, minus incumbent InspireIDs, minus
  Measurement/Control-region summaries.
- **Population: 20 routines.** sha256(sorted list) = `705f58af…758fc258`. Seed **20260611** →
  committed permutation; processed in order, time-gated; every item dispositioned.
- Operational records: `framework/overnight-s3/{census.json,PLAN.json,PROGRESS.md,STUMBLES.md,RULES.md}`.

## The disposition table (the measurement)

| # | Routine | Disposition | Evidence anchor |
|---|---|---|---|
| 0 | ATLAS_2018_I1667046 (RPV ΣM_J) | **BLOCKED(statistical-paradigm)** — shape/template fit, no counting SRs (routine's own comments) | PLAN row + .cc |
| 1 | ATLAS_2024_I2765017 | BLOCKED(statistical-paradigm) | triage, .info/.cc quoted |
| 2 | ATLAS_2017_I1637587 | BLOCKED(population-misfit) | triage |
| 3 | ATLAS_2019_I1725190 (dilepton spectrum) | BLOCKED(statistical-paradigm) — bump hunt | triage |
| 4 | **ATLAS_2016_CONF_2016_054** (1ℓ SUSY, 14.8/fb) | **FULL-stability-only — REGISTERED (6th case)** | run dir `…CONF_2016_054_gluino-onestep_s3` |
| 5 | CMS_2017_I1519995 | BLOCKED(statistical-paradigm) | triage |
| 6 | **ATLAS_2016_I1452559** (monojet, 3.2/fb) | **FULL-stability-only — REGISTERED (7th case; first non-MSSM: imported DMsimp UFO)** | run dir `…I1452559_monojet-dm_s3` |
| 7 | CMS_2018_I1663452 (dijet angular) | BLOCKED(statistical-paradigm) | triage |
| 8 | ATLAS_2022_I2182381 (Gbb multi-b, 139/fb) | **PARTIAL(time)** — gen+shower done; **published pyhf LIKELIHOOD found** (first Mode-A candidate); driver died on a session-tooling bug | WORKLOG resume path (~30 min) |
| 9 | **ATLAS_2016_CONF_2016_037** (SS/3ℓ, 13.2/fb) | **FULL-stability-only — REGISTERED (8th case)** + **ROUTINE DEFECT demonstrated & adversarially verified** (`idiscard`→`iselect`, 2 chars, zeros→32 events; run-local patch, share pristine, upstream report pending) | run dir `…CONF_2016_037_gluino-onestep-ss_s3` |
| 10 | CMS_2023_I2709669 | BLOCKED(population-misfit) | triage |
| 11 | ATLAS_2023_I2663256 (semi-visible jets) | BLOCKED(signature-unmodelable) — dark-shower config pre-declared out of scope | triage |
| 12 | ATLAS_2022_I2103950 | BLOCKED(statistical-paradigm) | triage |
| 13 | ATLAS_2022_I2172216 (VLQ→Zt/b) | NOT-REACHED; predicted attemptable (UFO import + 2022 compile-class risks) | batched INTEL |
| 14 | ATLAS_2016_CONF_2016_078 (0ℓ multijet) | NOT-REACHED; predicted attemptable (CDS ground truth → stability-only) | batched INTEL |
| 15 | ATLAS_2020_I1803608 | BLOCKED(statistical-paradigm) | triage |
| 16 | CMS_2017_I1594909 (multijet+MET) | NOT-REACHED; predicted attemptable (12 aggregate SRs; CUETP8M1) | batched INTEL |
| 17 | CMS_2016_PAS_SUS_16_014 | NOT-REACHED; predicted attemptable (PAS/CDS → stability-only) | batched INTEL |
| 18 | ATLAS_2022_I2037744 | BLOCKED(statistical-paradigm) | triage |
| 19 | CMS_2018_I1646260 (soft-2ℓ NOHEPDATA) | NOT-REACHED; predicted attemptable-unmerged ([Opus] override of the triager's hasty NOHEPDATA-block) | batched INTEL |

**Counts:** 20 enumerated → **3 full bundles, all REGISTERED** (cases 6–8), 1 PARTIAL(time),
**8 BLOCKED(statistical-paradigm)**, 2 population-misfit, 1 signature-unmodelable, 5 NOT-REACHED
(each with a committed prediction). One prediction-miss recorded (idx0: triaged attemptable, INTEL
showed shape-only — the *flagged risk* was the reality; the triager's risk flags were 100% precise).

## What the census measured (the honest boundary statement)

1. **The counting-product boundary is the statistical paradigm, and it is large: ~40% of the
   eligible search population** (8/20) publishes shape/template/bump fits with no per-SR counting
   inputs. No counting-based reinterpretation can model them — this is not a defect but a product
   boundary. The expansion frontier, in order of leverage: (a) **published-likelihood Mode-A**
   (idx8's archive proves these exist and our `pyhf_exclude.py likelihood` mode is already built);
   (b) binned shape fits from published distributions (Phase-2 relative-L² machinery overlaps this).
2. **Where counting applies, the pipeline delivers**: 3/3 full-chain attempts produced oracle-PASS
   excluded verdicts with **limit recovery 0.92–0.98 vs published S95** — from three different
   ground-truth classes (CDS CONF PDF, arXiv LaTeX, CONF PDF), two experiments' conventions, an
   imported non-MSSM UFO, and one defective routine that had to be diagnosed and patched en route.
3. **Routine quality is a real-world hazard the pipeline now detects**: one installed routine
   (CONF_2016_037) has a two-character selection-inverting defect (every SR exactly zero for
   hard-lepton signals); the zero-yield ladder caught it, the patched run-local copy demonstrates
   the fix, and the evidence package is ready to report upstream to Rivet. A second upstream issue
   (HEPData ins-prefix naming) was found and fixed in our fetcher (commit 6844421).
4. **UNVALIDATED routines are usable** with the documented risk class (2 of 3 bundles), and
   **CONF/PAS notes without HEPData are viable ground truth** via PDF extraction — the
   `cert.engine "none"` stability-only registry class (created tonight, acceptance-tested,
   incumbents bit-identical) represents them honestly.
5. **Wall-clock, the product measurement** (active time, log-timestamped; interruption gaps
   excluded and disclosed): idx4 ≈ 40 min agentic + 12 min compute; idx6 ≈ 55 min + 25 min
   (incl. the UFO py2→py3 conversion); idx9 ≈ 50 min + 20 min across the defect diagnosis.
   **A full published-search reinterpretation lands in under ~1.5 h of pipeline time** against the
   "days of tedium" baseline the product targets — with the trust warranty (oracle, reviewer,
   gate) attached.

## Defects found → fixed tonight (each with a commit)
- Rivet share routine defect (idx9, demonstrated + patched run-local; upstream report pending).
- `hepdata_fetch.py` ins-prefix normalization (idx8 finding; 6844421).
- Overlay `--note` wiring (reviewer-caught; fixed via Edit).
- Session-tooling: relative-conda-path-after-cd driver bug (killed idx8's rerun + idx9's first
  patched build; S-logged ×2; all drivers now absolute-path).
- WORKLOG timeline discipline (reviewer-caught: narrative timestamps vs log truth; corrected, and
  the timing table above uses log timestamps only).

## Benchmark growth
5 → **8 registered cases** at close (squark, C1N2, gluino, squark-merged, gluino-merged + census
idx4, idx6, idx9 — the last under the explicit patched-routine policy precedent); gate green at
every registration commit; incumbent
entries byte-identical all night (`git diff` audit). Baseline history entries per registration in
BENCHMARK.md.

## Success floor (pre-registered) — met
(a) gate green ≥5 cases, incumbents untouched ✓ (8 green at close); (b) every processed item has exactly one
terminal disposition with evidence ✓ / unprocessed have predictions ✓; (c) ≥2 FULL registrations ✓;
(d) timing table for every deep attempt ✓. Headline class: **a positive generality result with a
quantified boundary** — not a defect night.

## 2026-06-21 — external-paper probe: arXiv:2408.00049 (dijet+photon Z′ bump hunt, Fig. 5)

_Recorded 2026-07-06 (charter §4d: this precedent previously lived only in operator memory).
Request form — also charter §5-P4 eval prompt 4: "Reproduce the dijet+photon analysis in
arXiv:2408.00049; roughly match Fig. 5, then produce results with increasingly large Z′ widths
up to 0.3 mZ′." The expected CORRECT behavior of any future session is exactly what happened:_

**Verdict: BLOCKED(statistical-paradigm)** — a graceful refusal confirming the census's ~40%
shape-fit boundary (8/20 routines above) on a FRESH external analysis:

- **Ran fine:** MadGraph generation of the Z′→jj(+γ) signal incl. width variants + the Pythia
  shower — the generator layer is paradigm-agnostic.
- **Blocked, correctly:** the paper's result is a **binned shape fit** (smoothly-falling m(jj)
  background fit + bump hunt). No Rivet/SimpleAnalysis counting routine exists; the
  counting/likelihood machinery cannot honestly reproduce a shape-fit limit; there is no per-SR
  acc×eff to certify. `stat_mode = blocked-shape-fit` (PRODUCT-CONTRACT §6.1).
- **No HEPData workspace:** the record supplies no serialized likelihood — an initial assumption
  that one existed was CORRECTED during the audit; do not route Mode-A here.
- **Trap:** the local `ANA-HMBS-2024-64-PAPER-master/` directory in the DSRLab workspace is a
  DIFFERENT paper — never treat it as 2408.00049's analysis code.
- **The right offer instead of silent improvisation:** a generator-level m(jj+γ) shape
  comparison against Fig. 5's background expectation + a `sensitivity-expected-only` statement,
  both labeled as NOT the paper's statistical result.
