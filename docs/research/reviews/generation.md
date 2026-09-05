# Interrogation — generation (Session 2, 2026-06-09)

_Stage S6: MadGraph 2.9.27 event generation — steering/proc cards, run-card settings, σ bookkeeping,
and the ME/PS matching scale. Centerpiece: the **measured merged-gluino xqcut σ-stability scan**
(Wave-0 of this session) that replaces the "xqcut ≈ m/4" rule of thumb with a normative, measured
method — and exposes that the two agent docs carried *mutually inconsistent* scale guidance (m/4
headline vs an m/10 example). Approved scope: docs + read-only card audit; **no regeneration of
certified events** (the 10k merged-gluino production run was in flight in
`trial-runs/_scratch-gluino-merged/` throughout — never written to). Single
`run_benchmark.py --full` at stage close._

## Defects found

| ID | Sev | Where | Finding | Status |
|---|---|---|---|---|
| GEN-D1 | major | run cards (audit below) | **`use_syst` inconsistency across certified runs**: gluino/squark-pair generated with `False` (the intent), but squark-merged **and** C1N2 ran with the MG default `True` (cards + banners agree). Measured impact: **none on physics this time** — both LHEs verified single-weight (zero `<initrwgt>`/`<rwgt>` tags in banner+events; with the internal `nn23lo1` PDF the systematics module never wrote variation weights) — but with an LHAPDF set the same miss produces a multiweight LHE silently entering the single-weight analysis path | **FIXED (docs + guard)**: `use_syst=False` declared the pipeline norm in `checklists/generation-settings.md` (with the leak rationale); `lhe_check.py` (S4) is the run-time detector, now named in `steps/03-generate.md` as what catches exactly this. Certified runs untouched (they are records; their LHEs are clean) |
| GEN-D2/D3 | major | provenance | **PDF set (`pdlabel`/`lhaid`) + `dynamical_scale_choice` were undocumented** in run provenance — a reproducibility hole (all four runs used nn23lo1 / lhaid 230000 / dyn-scale −1, but only the cards knew) | **FIXED in S3** for the two enriched stamps (`docs/research/reviews/data-acquisition.md` D-DA-001/-003 set the schema); **this stage makes it a checklist requirement** for every new run (`generation-settings.md` provenance block). Backfill of the two skinny stamps (gluino/squark-pair) stays deferred per S3's D-DA-003 posture |
| GEN-D4 | major (advisory) | `nevents` sizing | **Tail-SR MC statistics**: at 10k events a tail SR holding 2–5 raw events carries a 45–70% MC stat error — any "certification" there is noise. No doc stated how to size `nevents` against the SRs actually being certified | **FIXED (advisory shipped)**: `steps/03-generate.md` now requires ≥25 raw events in the weakest SR to be certified (≲20% MC error) or an explicit report-only declaration tied to the cert's tail tier |
| GEN-D5 | major | σ capture | **MadGraph integration error on σ never recorded** (and per-subprocess σ lines lost for merged samples) — downstream k-factors and matched/LO ratios were quoted without their input error | **FIXED in S3** stamps (σ ± error, per-subprocess); **now a checklist requirement** at generation time (`generation-settings.md`) |
| GEN-D6 | minor | steering scripts | **Proc-card portability is a mixed convention** (measured): 3 of 5 certified steering scripts carry absolute machine-local `output` paths, the C1N2 pair use repo-root-relative paths that only work from one cwd; nothing recorded which convention a script assumes, and no MG5 version pin | **FIXED (doc rule)**: `generation-settings.md` — pick a convention, state it, pin the MG5 version in provenance |
| GEN-D7 | major | weight validation | No generation-side check that the LHE weight structure matches the single-weight pipeline contract | **FIXED in S4** (`lhe_check.py`: multiweight tags, weight sign, ickkw, masses, MODSEL); this stage extends the step-3 line declaring it the mandatory pre-shower gate |
| GEN-D8 | minor | param cards | **Decoupled-mass convention undocumented**. Audit: all four certified cards in fact decouple at **4.5e9 GeV consistently** (two cosmetic format variants, `4.5E9` vs `4500000000.0`) — but nothing said why that value or that it must stay uniform | **FIXED (doc)**: `generation-settings.md` — 4.5e9 consistently; ≳1e10 risks numeric issues; mixed conventions are audit-flagged |
| GEN-D9 | minor | run-card semantics | **The recorded card under-reports the applied jet cuts when `auto_ptj_mjj=T`**: the merged squark card/banner read `ptj=20` with `xqcut=80`, but the *applied* cut follows xqcut — verified at LHE level (min final-state light-parton pT = **80.18 GeV** over 2000 events). A provenance reader trusting the literal `ptj` line records the wrong generation cut | **FIXED (doc)**: `merging.md` + `generation-settings.md` — record `xqcut`, not the stale `ptj` line; the LHE-level check is the verification idiom |
| GEN-D10 | major (docs) | `checklists/merging.md` (+ echo in `.claude/rules/madgraph-pythia.md`) | **Internally inconsistent matching-scale guidance**: headline "xqcut ~ m/4–m/6" next to the example "e.g. 60–100 GeV for a TeV gluino" (= m/10–m/17); the rules file likewise says "¼·m(parent) (e.g. 80 for 800 GeV squarks)" (= m/10). An agent following either literal example lands a factor ~2.5 from the headline rule with no way to tell which is right | **FIXED in `merging.md`** (the normative method is now the measured matched-σ stability scan, with the gluino scan as the worked example and the ≤5% acceptance); the **rules-file echo is outside the approved list** → flagged for the orchestrator (same posture as S5's stale-MODSEL echoes) |

## Card-invariants audit (read-only; all four certified runs)

`build_madgraph/Cards/run_card.dat` (C1N2: `outputs/c1n2_mg5/Cards/`) + the run banners
(`Events/<run>/*_banner.txt`; the post-run card always reads `iseed=0` — MadGraph resets it):

| Run | nevents | ebeam1/2 | iseed card → banner | use_syst | PDF / scale | merging block | vs RESULT.md |
|---|---|---|---|---|---|---|---|
| gluino-pair | 10000 | 6500.0 ✓ | 0 → **21** (auto) | **False** ✓ | nn23lo1 / 230000 / dyn −1 | absent (unmerged card — MG hides the block) | ✓ LO unmerged, as claimed |
| squark-pair | 10000 | 6500.0 ✓ | 0 → **42** (run_smoke), **43** (run01) | **False** ✓ | nn23lo1 / 230000 / dyn −1 | absent | ✓ LO unmerged |
| squark-merged | 10000 | 6500.0 ✓ | 0 → **21** (auto) | **True** (GEN-D1; LHE verified single-weight) | nn23lo1 / 230000 / dyn −1 | `ickkw=1, xqcut=80`, literal `ptj=20` + `auto_ptj_mjj=T` → effective ptj 80 (GEN-D9, LHE-verified 80.18) | ✓ RESULT/provenance claim ickkw=1, xqcut=80, qCut=100 (=1.25×), nJetMax=2 — all match |
| C1N2-WZ | 20000 | 6500.0 ✓ | 0 → **21** (intended 424242; **sed pattern missed** — STUMBLES S14 confirmed: the card kept 0, MG auto-assigned 21, recorded in banner + RESULT.md L141 + provenance `iseed_banner`) | **True** (GEN-D1; LHE verified single-weight) | nn23lo1 / 230000 / dyn −1 | absent (deliberate, EWK 2→2) | ✓ |

Reading: ebeam/PDF/scale are uniform and correct everywhere; the two real findings are GEN-D1
(use_syst drift — exactly the two runs whose run-card edit scripts didn't set it) and the confirmed
iseed sed failure (the field evidence behind the keyed-Python-only rule, now in both docs). The
banner — not the post-run card — is the seed record; first auto-assigned seed in a fresh procdir is
deterministically 21 in this MG (observed in three independent procdirs).

## The measured centerpiece — merged-gluino xqcut σ-stability scan (Wave-0, this session)

Setup: `p p > go go` + j + jj (MSSM_SLHA2, 10 subprocess dirs), certified gluino param card
(m_g̃=1000, m_LSP=100), MLM `ickkw=1`, `qCut = 1.25×xqcut`, `nJetMax=2`, `nQmatch=4`, 1k events/point,
`iseed=42`, `use_syst=False` (the norm — note the scan itself complies with GEN-D1):

| xqcut [GeV] | pre-veto σ [pb] | matched σ [pb] | matched/LO |
|---|---|---|---|
| 100 | 0.3972 | 0.1887 | 0.939 |
| 150 | 0.3110 | 0.1926 | 0.958 |
| 250 | 0.2484 | 0.1972 | 0.981 |

LO reference 0.201 pb. **Plateau: 4.4% total matched-σ variation over a 2.5× scale span** — the MLM
veto preserves the inclusive rate across the whole bracket. [Opus] production choice: **xqcut=250
(= m/4, the checklist headline rule; best inclusive-rate preservation, −1.9%, inside the 5%
acceptance)**. The 10k production run at xqcut=250 is in flight in `trial-runs/_scratch-gluino-merged/`
(read-only this stage; `logs/scan_progress.log` confirms `nevents=10000 ickkw=1 xqcut=250 iseed=42
use_syst=False`). Scoring it against the published grid — including the one-qCut-variant (1.5×)
spot-check — is S7's job; expected effect: the gluino case's 13.2% Acceptable A×ε residual is
attacked from the merging side (the S5 tune study showed most of the 13.2% is a tune *excess*,
1.132 → 1.044 under A14 — the two effects must be disentangled on the merged sample before any
re-lock).

This table is now the worked example in `docs/workflow/checklists/merging.md` (numbers only, no
trial-run dir names — DISTRIBUTION hygiene), and the scan is the **normative method**: the old
"xqcut ≈ ¼·m(parent)" headline survives only as the bracket's starting guess.

## The k-verification story (σ normalization, cited for the record)

- **Gluino k = 1.915** (S1): HEPi `pp13_gluino_NNLO+NNLL` grid is g̃g̃ with squarks decoupled —
  an **exact setup match** to our sample; verified like-for-like before the S2/1a re-lock.
- **Squark k = 0.862 / 0.855** (pair / merged): the HEPi squark grid is **10-fold degenerate** qq̃*;
  rescaled ×8/10 to our 8-fold degeneracy. The earlier "k=1.08" was the **flavour-sum trap** — same
  class as the C1N2 single-charge k=0.421 (single-charge NLO over both-charge LO). k<1 is real here
  (LO-PDF overshoot): a bare-LO limit is not automatically conservative.
- Authority: `benchmarks/cases.json` `sigma_scale_k` is the ONLY k source; never read k
  from run-dir helper outputs (`.claude/rules/statistics.md`).

The generation-stage lesson: every k comparison is a *convention* comparison (degeneracy, charge
states, decoupling) — which is why the checklist now requires the σ ± error and the exact process/
degeneracy facts in provenance at generation time.

## Fixes applied (docs + checks; no certified artifact touched)

| Fix | File | Evidence |
|---|---|---|
| use_syst norm + iseed/banner rule + keyed-Python-only edits + decoupling convention + portability + provenance-field block (GEN-D1/2/3/5/6/8) | `docs/workflow/checklists/generation-settings.md` (rewritten) | Card audit above is the motivating evidence; provenance block mirrors the S3 enriched-stamp schema (fields described, no trial-run names) |
| sed block replaced by the keyed-Python rule; σ±err+provenance note; tail-SR statistics advisory (GEN-D4); merging brief aligned to the scan method; lhe_check declared the mandatory gate (GEN-D7, one-line extension of S4's block) | `docs/workflow/steps/03-generate.md` | The removed sed recipe is the one that demonstrably failed in the field (C1N2 STUMBLES S14 iseed miss) |
| Matching-scale guidance made consistent + measured (GEN-D10, D9): scan = normative, worked-example table, \|matched/LO−1\| ≤ 5% acceptance, qCut = 1.25×xqcut with the 1.25-vs-MG-default-1.5 factor documented + S7 variant spot-check, auto_ptj_mjj note, provenance fields | `docs/workflow/checklists/merging.md` | Scan table above (measured this session); squark-merged 0.9% match as the lower-plateau counter-example |
| PDF/scale-band entry (GEN-D2/D3 residual) | `docs/reference/limitations.md` | One new Physics-fidelity entry: bands not propagated; NLO+NNLL central value partially covers normalization; use_syst=True-vs-single-weight-path tension stated honestly |
| Hygiene | `docs/workflow/`, `README.md` | `grep -rIl -E 'gluino-pair|squark-pair|slepton_200|2026-06' docs/workflow/ README.md` → **DISTRIBUTION.md only** (clean, verified after all edits) |

## Deferred (with why)

- **PDF/scale uncertainty-band propagation** — needs `use_syst=True` multiweight LHEs + a
  multiweight-aware analysis path (per-weight Rivet or post-hoc reweighting), which conflicts with
  the current single-weight contract that `lhe_check.py` enforces; Phase-2/Session-3 (KNOWN-LIMITATIONS
  entry shipped).
- **NLO event generation** (aMC@NLO instead of flat k) — heavyweight (loop libraries, negative
  weights break the single-weight contract); flat verified-k is within the fast-sim floor at current
  fidelity. Revisit only if a case's σ-shape (not normalization) becomes the attributed residual.
- **Automatic nevents scaling** (helper that reads a dry-run cert and proposes nevents per the
  ≥25-raw-events rule) — the advisory ships the policy; the helper is mechanical Session-3 work.
- **Enriched-stamp backfill** for gluino/squark-pair provenance (S3's D-DA-003 posture: additive,
  benchmark pins their σ already).
- **`.claude/rules/madgraph-pythia.md` xqcut example** ("¼·m(parent) (e.g. 80 for 800 GeV squarks)"
  — the GEN-D10 inconsistency's echo) → orchestrator follow-up; outside the approved file list.
- **Scoring the in-flight xqcut=250 production run** (+ the 1.5×qCut variant) → S7, with the
  tune-vs-merging disentangling from S5 on the table before any benchmark re-lock.

## Gate (the single `--full` run at stage close)

`python3 benchmarks/run_benchmark.py --full` → **exit 0, 4/4 OK**; `results.json` identical
to the committed baseline apart from `generated`/timing (field-stripped comparison): squark A×ε 2.4%
Ideal / s95 1.01/1.03 / µ₉₅ 0.22254; merged 3.9% Ideal / 1.01/1.03 / 0.22580; gluino 13.2%
Acceptable / 1.00/1.02 / 0.05237 (WARN, attributed — unchanged by design); C1N2 6.4% Good / 2.7123.
This stage changed documentation, one KNOWN-LIMITATIONS entry, and this file — no run artifact, no
helper the gate invokes, no registry; regression-free by construction.
