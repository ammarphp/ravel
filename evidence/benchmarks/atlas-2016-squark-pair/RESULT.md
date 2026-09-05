# RESULT — squark-pair vs ATLAS_2016_I1458270 (agentic dogfood trial)

The pipeline run **agentically**: a fresh subagent drove the `[agent]` steps (generate → analyze →
visualize → acquire-data → exclude) from the `workflow/` docs; Opus did the `[Opus]` judgement (routine
+ model + cards + this interpretation) and logged every stumble in `AGENT-LOG.md`.

## Inputs
- **Analysis:** `ATLAS_2016_I1458270` — ATLAS 0-lepton jets+E_T^miss SUSY search, 13 TeV, 3.2 fb⁻¹.
- **Model:** squark-pair production, 8 mass-degenerate light-flavour squarks (ũ,d̃,c̃,s̃ × L,R) at
  **m(q̃) = 800 GeV**, gluino decoupled (5 TeV), **m(χ̃₁⁰) = 100 GeV**, forced **q̃ → q χ̃₁⁰** (BR 1).
  A genuinely different model from the gluino demo: squarks give **2 jets + E_T^miss**, not 4–6.

## Pipeline (all native, no emulation)
| Stage | Tool | Result |
|---|---|---|
| event generation | MadGraph 2.9.27, `p p > sq sq` (8 squarks+conj.) | σ_LO = **0.3044 ± 0.0005 pb**, 10000 events |
| shower + decay | Pythia8 8.312 (`pythia_shower`, HepMC3) | 10000 showered; σ matches (0.3044 pb) |
| analysis | Rivet 4.1.3 `ATLAS_2016_I1458270` | 7 SR counters + m_eff distributions filled |
| visualization | `rivet-mkhtml` + `name_plots.py` | 21 plots + 21 named copies + INDEX (0 unlabeled) |
| data | `rivet_ref_yields.py` (bundled REF); `hepdata_fetch.py` | per-SR obs+bkg; HEPData: 105 tables, **0 likelihoods** |
| exclusion | `pyhf_exclude.py` counting | **observed µ₉₅ = 0.282** (most-sensitive SR: **2jl**) |

## Statistical exclusion (pyhf counting model)
| SR | signal s | background b | observed n | µ₉₅ (obs) | µ₉₅ (exp) |
|---|---|---|---|---|---|
| **2jl** | **232.4** | **296 ± 44** | **263** | **0.28** | **0.35** |
| 2jm | 146.5 | 199 ± 30 | 191 | 0.37 | 0.41 |
| 2jt | 18.2 | 23 ± 3.5 | 26 | 0.82 | 0.69 |
| 4jt | 5.2 | 4.6 ± 0.7 | 7 | 1.60 | 1.12 |
| 5j | 10.3 | 13.6 ± 2.0 | 7 | 0.49 | 0.85 |
| 6jm | 3.5 | 7.0 ± 1.1 | 4 | 1.29 | 1.89 |
| 6jt | 2.0 | 3.8 ± 0.6 | 3 | 2.22 | 2.58 |

**Observed µ₉₅ = 0.282** (expected 0.355, +1σ 0.48 / −1σ 0.26) → **excluded** (~3.6× below nominal).
`outputs/pyhf_exclusion/exclusion.{json,png}`. The observed limit is slightly stronger than expected
because 2jl saw a mild downward fluctuation (263 observed vs 296 background).

**The signal concentrates in the low-multiplicity 2-jet SRs** (2jl/2jm dominate; the high-multiplicity
4j–6j SRs are barely populated) — the **opposite** of the gluino demo, whose sensitivity came from the
5j/6j SRs. The pipeline correctly tracks the model-dependent sensitive region: squarks → 2 jets + MET,
gluinos → many jets + MET.

## Comparison to the publication
ATLAS-SUSY-2015-06 (arXiv:1605.03814) interprets this search in a squark simplified model (8 degenerate
light-flavour squarks, q̃→qχ̃₁⁰), excluding **m(q̃) up to ≈1.05 TeV for a massless LSP** (slightly lower,
≈1.0 TeV, for m(χ̃₁⁰)=100). Our point at **m(q̃)=800 GeV is well inside that reach**, so it should be —
and is — excluded (µ₉₅=0.28 ≪ 1). The cross-check holds against the sister run: the gluino at 1 TeV gave
µ₉₅=0.10 (reach ≈1.35 TeV), more strongly excluded than the 800 GeV squark, as expected from the larger
gluino cross-section and the search's design. **Verdict: consistent with the published exclusion.**

Caveats (as for the other runs): LO cross-section with no k-factor (the LHC-SUSY-xsec NLO+NLL value for
8 squarks at 800 GeV is ≈0.4–0.5 pb vs our LO 0.30 pb → our limit is mildly conservative); counting
model rather than a published likelihood (none exists for this 2016 search).

## Agentic-trial outcome (see `AGENT-LOG.md`)
The subagent completed all five `[agent]` steps from the docs and produced the artifacts. It surfaced
**three doc stumbles**, all now fixed: (1) step 3's run-card edit only showed `nevents` (ebeam/iseed/
use_syst were a bare comment); (2) step 5's `rivet-mkhtml -o` was a relative path after a `cd`; (3) the
`name_plots.py`/`hepdata_fetch.py` invocations used a bare `python` (no `python` on PATH → must be
`$CONDA run -n rivet python`). The breadth scouting (why CMS/EWK-jigsaw/7 TeV routines were not chosen)
is in `AGENT-LOG.md` and `workflow/checklists/choosing-routine.md`.

## Reproduce
```
config/squark.mg5                          # MadGraph process (define sq = ul ur dl dr cl cr sl sr + conj.)
inputs/param_card_squark800_n1_100.dat     # SLHA: 8 squarks=800, gluino=5000, chi10=100, q~->q chi10
config/shower.cfg                          # Pythia8 LHEF->HepMC3 (set Beams:LHEF to this run's LHE)
inputs/sr_spec.json, inputs/plot_labels.json   # reused from the gluino run (same routine)
# then steps 3–7 of workflow/WORKFLOW.md
```

## Session-2 addendum (2026-06-09)

**Honest correction — the LO limit was mildly AGGRESSIVE, not "conservative" as claimed above.**
The body's caveat ("the NLO+NLL value for 8 squarks is ≈0.4–0.5 pb vs our LO 0.30 pb → mildly
conservative") was the flavour-sum trap: the HEPi `pp13_squark_NNLO+NNLL` grid is **10-fold**
degenerate q̃q̃* (gluino decoupled); this sample is 8-fold. Rescaled like-for-like,
σ_NLO+NNLL = 0.328 × 8/10 = **0.2624 pb** over σ_LO = 0.3044 pb → **k = 0.862 < 1** (an LO-PDF
overshoot; the k transfers the normalization onto the verified WG NLO+NNLL value).

**Counting inputs upgraded to the analysis's own CR-fitted backgrounds** (arXiv:1605.03814 Table 6,
b±δb per SR; observed n cross-checked identical to the REF integration in all 7 SRs) →
`outputs/sr_yields_fitted.json` (via `rivet_ref_yields.py --fitted-bkg`). The original REF-integrated
inputs (15% floor) are preserved in `outputs/sr_yields.json` as evidence: that input choice — not the
limit machinery — was the entire 1.49× driving-SR s95 residual.

**New exclusion (benchmark-locked scored value, `framework/benchmark/cases.json`):
µ₉₅(obs) = 0.2225** (NLO+NNLL, k=0.862; this directory's `outputs/pyhf_exclusion/exclusion.json`
remains the original LO+floor artifact, µ₉₅ = 0.28). Driving-SR (2jl) s95 recovery vs the paper's
model-independent S95: **1.49× → 1.01 obs / 1.03 exp**. Verdict unchanged: (800,100) excluded.
