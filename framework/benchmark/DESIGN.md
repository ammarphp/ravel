# Benchmark — design spec (phased)

The objective **"are we publication-grade?"** instrument: reproduce known-answer published analyses
and score against ground truth, as a regression gate run each session. Built on what already exists
(`validate_cutflow.py`); inspired by the **Collider-Bench** effort (a 2026 benchmark of AI agents
reproducing CMS SUSY analyses — physicist-in-the-loop baseline, relative-L² fidelity with a ~0.33
threshold, a provenance audit). **Verify the exact arXiv id + figures before citing in the paper**
(the methodology is what we borrow, not specific numbers).

## Phase 1 (Session 1 builds this — lean regression gate)

**Cases (known-answer analyses we have certified):** start with `ATLAS_2016_I1458270` (squark-pair, and
gluino-pair) and `ATLAS_2018_I1676551` (the C1N2→WZ jigsaw). Add one CMS case in Session 3. A
`framework/benchmark/cases.json` registers each: `{analysis_id, run_dir, routine, grid, m_parent,
m_lsp, sigma_pb, lumi_fb, driving_sr, srs[], tables_dir, published_limit_mu95, published_excluded}`.

**Ground truth** (no internet needed at run time if pre-fetched): published acc×eff grids
(`outputs/hepdata/tables/HEPData-ins<id>-v1-yaml`), the public pyhf likelihood when one exists, and the
published 95% CL exclusion (µ₉₅ or the contour point) transcribed into `cases.json`.

**Metrics per case** (reuse helpers — do not reinvent):
1. **acc×ε residual per SR** — `validate_cutflow.py` (tiered); record the driving-SR residual + the
   per-tier pass/fail + the attribution rows.
2. **limit recovery** — our µ₉₅ (from `pyhf_exclude.py`, NLO-scaled) vs the published value; record the
   relative offset and whether the excluded/allowed verdict matches.
3. **provenance check** — confirm the yields trace to a real run (a non-empty `analysis.yoda` +
   `RESULT.md` provenance block + matching σ), not hand-entered numbers. (Phase 2 upgrades this to an
   LLM-judge audit of the run log.)

**Tiers** (the bar from `STATUS.md` / the plan):

| Tier | driving-SR acc×ε residual | limit recovery | 
|---|---|---|
| Acceptable | ≤20–30% | verdict matches; µ₉₅ within ~2× |
| **Good (publication-grade)** | **≤10%** | µ₉₅ within ~20% |
| Ideal | ≤5% | µ₉₅ within ~10% |

**Gates** (exit non-zero on breach, for CI/`/goal`):
- `--fast`: one case (the squark), minutes — the per-session smoke gate.
- `--full`: all registered cases — the milestone gate.
- (Phase 2) `--publication`: all cases ≥ Good **and** ≥50% at Ideal.

## Deliverables (Session 1)
- `framework/benchmark/cases.json` — the registry.
- `framework/benchmark/run_benchmark.py` — loads `cases.json`, runs the three metrics per case (calling
  the existing helpers), prints a tier table, writes `framework/benchmark/results.json`, and exits
  non-zero if any registered case's **driving** SR breaches its required tier (default Good for the
  squark, Acceptable elsewhere until improved).
- `framework/benchmark/BENCHMARK.md` — what it measures, how to run it, and the **baseline scores**
  (the current tier per case) so Session 2's refinements are measured against a fixed reference.

## Phase 2 (later sessions — grow toward Collider-Bench)
Add: relative-L² distance on the discriminating distribution (not just SR yields), a
normalization-vs-shape split (δ_norm), an **LLM-judge provenance audit** of the run trace (catch
fabricated/short-circuited runs), more cases (CMS breadth from Session 3), and the `--publication`
gate. Keep every threshold justified by a cited community tolerance (MadAnalysis5/SModelS ~10–15%).
