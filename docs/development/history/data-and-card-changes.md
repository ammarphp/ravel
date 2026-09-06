# Change registry — Data & cards

Every change made to the physics-input cards. Originals are kept pristine; edits are applied to
copies in `inputs/` or inside the generated process directory under `build/`.

## September 2026 RRR closure campaign

**Qualification of historical D4 below.** Its reported wrong-mass observation remains a
historical result, but the universal MSOFT-overrides-MASS explanation was not established.
The currently inspected MSSM_SLHA2 UFO exposes `Mneu1` through `MASS[1000022]` and NMIX
independently. A dependency review bound the installed model, restriction/cache and importer
inputs; the prospective 100/98 and 50/45 cards change only seven physical mass entries and
seeds. Those cards preserve inherited mixing/widths and do not claim a freshly diagonalized
MSSM spectrum or validated low-gap decays. The active [model-card checklist](../../workflow/checklists/model-cards.md)
now requires the actual interface and generated products to be checked. Pythia 8.312 can
import explicit branching-ratio rows without MODSEL; missing MODSEL alone does not explain
every no-decay failure. The older narrative is retained below as history, not current guidance.

The prospective lower-parton control retains the 150/140 four-state physics inputs and
changes leading-parton `ptj1min` from 50 to 20 GeV, alongside independent seeds. This tests
cut dependence within the unmerged one-parton approximation. It neither changes the nominal
recipe nor implements zero/one/two-parton merging.

New dated campaign inputs explicitly generate the four selectron/smuon left/right diagonal
opposite-charge channels at 150/140 GeV, with one parton, cteq6l1, 13 TeV, ptj=20 GeV and
ptj1min=50 GeV. They retain the public tuned Delphes response and scalar decay tables,
declare the Monash tune and shower settings explicitly, and apply the 1.18 recipe factor
once. The likelihood uses 139/fb; published cutflows remain at their declared 140/fb. These
are frozen study choices, not an ATLAS simulation prescription or a measured NLO correction.

The first two 1,000-event attempts intentionally share seeds to test the repaired parser.
Their LHE and compressed HepMC products are byte-identical and must not be pooled as
independent samples. The subsequent 20,000-event sample uses independent generation,
shower and detector seeds. Effective cards and receipts are retained in the dated campaign.
Further precision replicas change only exposure and those seeds, with distinct run records.

The inclusive four-state control removes the matrix-element parton and sets ptj1min=0.
Its initial copied positive ptj1min required a jet and yielded zero cross section; the
failed attempt, old cards and revised approval remain intact. The successful LO rate is
0.1350625 ± 0.0003703 pb. This controls the inclusive reporting basis and does not certify
the unmerged ISR acceptance. No original workspace card or historical scan was rewritten.

Use the [native normalization and configuration reference](../../workflow/reference/native-pipeline.md)
for the operational checks and the [merging checklist](../../workflow/checklists/merging.md)
for the interpretation of fixed-multiplicity, MLM and CKKW-L prescriptions. Generic Delphes
b-tag flags and inherited all-true lepton ID bits remain detector approximations, explicitly
distinct from separately calibrated experimental working points.

---

## D1 — Process card: name the output directory
- **Change:** the final line `output -f -nojpeg` → `output <build/runs/PROC> -f -nojpeg`. Nothing
  else altered. Applied at runtime by the driver; the pristine `inputs/proc_card.dat` is not edited.
- **Mechanism:** `sed "s|^output .*|output $PROC -f -nojpeg|"`.
- **Physics impact:** none (bookkeeping — sets where generated code is written).

## D2 — Parameter card: normalize non-standard DECAY lines
- **Change:** 12 SM-particle `DECAY` header lines in the ATLAS HEPData card use a non-standard form
  (`DECAY 6 decay 6 1.42E+00`) and were rewritten to standard SLHA (`DECAY 6 1.42E+00`). Affected
  PDG codes: 6, 23, 24, 25 and 1, 2, 3, 4, 5, 11, 13, 15.
- **Mechanism:** `scripts/normalize_param_card.py`. Pristine original
  `inputs/param_card_200_150.dat`; normalized copy `inputs/param_card_200_150.normalized.dat`.
- **Physics impact:** none — every width, PDG code, and comment is preserved; only the spurious
  `decay <pdg>` tokens are removed (MadGraph's parser rejects them).

## D3 — Run card: four parameter edits
Applied to the auto-generated `Cards/run_card.dat`. Defaults already matched the reference for
`ebeam=6500`, `pdlabel=nn23lo1`, `iseed=0`, `ptj=20`; only these four changed:

| Field | default → set | Reason (factual) |
|---|---|---|
| `nevents` | 10000 → 1000 | requested sample size |
| `ickkw` | 1 → 0 | merging performed downstream in the shower (CKKW-L), not by MadGraph MLM |
| `xqcut` | 30.0 → 0.0 | MLM cut inactive when `ickkw=0` |
| `use_syst` | True → False | systematic-weight variations not requested |

- **Physics impact:** `ickkw`/`xqcut` change how jet multiplicities combine (inclusive σ
  double-counts until the shower merges); `nevents`/`use_syst` do not affect physics.

## D4 — EWKino param card (ATLAS_2018_I1676551 run): correct inconsistent spectrum + add MODSEL
- **Context:** run `trial-runs/2026-06-08_ATLAS_2018_I1676551_C1N2-WZ/`. The provided card
  `inputs/param_card_c1n2_300_100.dat` (pristine, md5 `1af8326a5cccf254c76770a87fd316a2`, **untouched**)
  has its `MASS` block at N1=100/N2=300/C1=300 but its `MSOFT` block at M1=101.4/M2=191.5 (μ=357.7) and
  **no MODSEL block**. MadGraph's MSSM_SLHA2 derives gaugino masses from M1/M2/μ → generated a
  **181 GeV** wino (σ_LO=0.903 pb), not the intended 300 GeV (σ_LO=0.313 pb); and Pythia, finding no
  MODSEL, kept SUSY off and ignored the SLHA DECAY tables (C1/N2 never decayed → zero leptons).
- **Change:** working copy `inputs/param_card_c1n2_300_100_fixed.dat` (md5
  `a9e040c7e0931c5bb62f74f1d8b06909`): set MSOFT M1=100, M2=300; raised HMIX μ→2000 (keep C1/N2 cleanly
  wino); inserted `Block modsel` (`1 1`). Verified the LHE then carries m(C1)=m(N2)=300.0 and that
  C1→W N1 / N2→Z N1 fire in the shower.
- **Physics impact:** **decisive** — moves the run from the wrong (181) to the intended (300,100)
  mass point and enables the forced simplified decays. Full diagnosis: the run's `STUMBLES.md` **S1**
  (workflow-level) and `RESULT.md` D7 (provenance). Pedagogical pointer: this is the canonical
  "MASS block alone is insufficient for MSSM_SLHA2; soft params + MODSEL govern the spectrum" lesson.

## D5 — slepton LO reference cross-section table (NLO+NLL re-normalization, 2026-07-04)
- **Context:** the 52-point slepton-bino scan (`trial-runs/sleptonscan_fig3_SCAN/`) was normalized
  to σ_LO(cteq6l1) × flat k=1.18; ATLAS/RRR normalize to NLO+NLL. The per-mass k(m)=σ_NNLL/σ_LO
  needs a like-for-like LO denominator (the HEPi slepton file is a SINGLE state — ẽ_L pair).
- **Change:** new generated data file `src/ravel/data/cross_sections/slepton_selL_lo_cteq6l1.json` —
  σ_LO(p p > el- el+), MG5_aMC 2.9.27, cteq6l1, 2k events, 12 masses 50–300 GeV (MC unc ~0.25%);
  full provenance + regeneration recipe in the file header. Cards were rendered from the pristine
  mapyde `SleptonBino.slha` template (untouched) via `prepare_native_slepton.render_param`.
- **Physics impact:** normalization-only — consumed by `nlo_xsec.slepton_k` /
  `scan_orchestrator assemble --nlo-renorm slepton` (µ′₉₅ = µ₉₅ × 1.18/k(m), k∈1.381–1.407); the
  σ-UL difference map is invariant by construction. Workflow-level record: the scan's `RESULT.md`.
  Pedagogical pointer: the like-for-like (single-state ÷ single-state) k lesson of
  `.claude/rules/statistics.md`, now with a slepton worked example.

## Deliberately NOT changed
- `mmjj` left at default (a large min-dijet-mass cut would be a VBF-style selection inconsistent
  with this ISR-jet sample).

## How to inspect what was actually used
The generated LHE embeds the full run card and SLHA banner:
```bash
gunzip -c build/runs/slepton_200_150/Events/run_02/unweighted_events.lhe.gz | sed -n '/<MGRunCard>/,/<\/MGRunCard>/p'
```

## 2026-09-05 — RRR diagnostics and controlled likelihood omissions

No generator, parameter, shower or detector card was changed. Added the unmodified
HEPData v5 table 9 expected contour alongside the retained observed table 10.
The new RRR refit audit copies the existing background likelihood and selected
native patches. It retains an official 150/130 GeV ATLAS benchmark patch plus two
explicit counterfactual derivatives: remove signal nuisance modifiers, then remove
six control-region signal samples. These are diagnostic inputs, not replacement
physics templates or a new baseline. Source/result hashes, failures and source
versions are retained in `evidence/audits/2026-09-05-rrr-refits/`.
