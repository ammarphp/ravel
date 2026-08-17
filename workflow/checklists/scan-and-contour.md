# Checklist — scan → exclusion contour (the RRR deliverable)

Read with `workflow/steps/08-scan.md`. The reference paper (arXiv:2306.11055) reports **contours from
grid scans**, never single points. This checklist keeps a scan honest.

## Before scanning
- [ ] **Mode is explicit.** *Reproduction* (re-derive ATLAS's published contour → validation; the
      figure of merit is the relative difference of the limits vs ATLAS) **or** *reinterpretation*
      (a model ATLAS never considered → the scanned contour *is* the new result, no reference exists).
- [ ] **Grid is on-grid.** Every point is inside the published acc×eff grid and the kinematically
      sensible region. The slepton-bino search has a **max Δm** (soft leptons fall below efficiency) and
      a **min Δm** — staying inside them is mandatory (off-grid points are uninformative — an off-grid point has been retracted as
      uninformative on exactly this basis before; record any such retraction in the run's own RESULT.md).
- [ ] **Spec drives it.** One grid spec JSON (`points` | `line` | `grid`); masses substituted by the
      orchestrator's keyed line edit (never a greedy sed — `.claude/rules/madgraph-pythia.md`).
- [ ] **Each point is a full pipeline run** (steps 3–7). Per-point fidelity (the detector gate, NLO σ,
      the cutflow cert) applies to **every** point, not just one — the cert is per-routine, so it carries
      across points, but the per-point yields still pass step-7 sanity.

## Compute honesty
- [ ] **State the cost — native is the default, the 2-D grid is the target.** NATIVE backend
      (`--backend native`, the default): a full-chain point is **~30–50 min** and points run in
      **PARALLEL** (`--max`), so a **coarse 2-D grid (≈12–18 points) is HOURS, not days**, on this laptop
      with NO VM. The **2-D grid is the deliverable**; a 1-D Δm line at one mass is only a *partial PoC*,
      not the target. A publication-dense plane (~100 pts) is cluster work (REANA/batch). The legacy
      CONTAINER backend (~9 h/point, strictly sequential, amd64 under emulation) is days locally — use
      only when no native backend exists for the chosen analysis.
- [ ] **Report coverage, never hide it.** `scan.json` carries `n_done` / `n_planned` / `missing_tags`.
      A contour from a partial grid must say so on the figure and in `RESULT.md`. A scan is not "done"
      because the orchestrator ran — it is done when the points it claims are actually harvested.

## Normalization
- [ ] **The limit is on the NLO+NLL σ, not the sample's flat LO k.** After harvesting, re-assemble with
      `--nlo-renorm <process>` (wired: slepton) — µ′₉₅ = µ₉₅ × flat_k/k(m) with the per-mass
      like-for-like k(m) (single state ÷ single state; `.claude/rules/statistics.md`); keep the LO
      assembly as `scan_lo.json`. The σ-UL **difference map is invariant** under this pure
      re-normalization (µ and σ_ref scale inversely) — only the µ₉₅=1 contour moves; verify the median
      |rel-diff| is unchanged after the renorm.
      Beware: if your σ-UL already sits BELOW ATLAS's (over-constraining acceptance), the renorm moves
      the contour further OUT — the flat-LO under-normalization had been partially cancelling the
      acceptance-side offset. That outward move is the honest result; say so.
- [ ] **THE COMPARISON-BASIS RULE: a σ-UL comparison is only meaningful on the SAME model-σ basis.**
      Compare µ limits like RRR does — both sides divided by the **same** σ_model^NLO+NLL. The
      experiment's per-point UL grid (e.g. ATLAS-SUSY-2018-16 Fig 44ab) is the UL on the **inclusive
      simplified-model σ** (fourfold-degenerate ẽµ̃ for "direct slepton"; verify the basis by checking
      UL/σ_model ≈ 1 *on* the published exclusion contour). Your scan's `sigma_ref_fb` out of assemble
      is the **sample σ** (e.g. the ISR-*tagged* subset from the MadGraph log, possibly with extra
      states like τ̃) — a **different, mass-dependently tilted basis** (slepton: tagged-6-state ÷
      inclusive-4-state = 0.56 at m=50 → 1.01 at m=300). Fix with `scan_orchestrator.py rebase
      <scandir> --process <p>` AFTER `--nlo-renorm`: the UL on the event count is basis-free, so
      UL(σ_incl) = µ₉₅ × σ_incl^LO(same cards/PDF) × k(m), and µ is re-expressed against the WG model
      σ (µ_SUSY). `scan_contour.py` warns loudly if a scan without `model_basis` is compared to
      `--atlas-limit`. Note the µ₉₅=1 contour meaning also shifts under rebasing (µ is now per the
      *model* σ, the same statement the published contour makes) — recompute which points are excluded.
- [ ] **LIKE-COLUMNS RULE: expected against expected, observed against observed — never mixed.**
      Published UL tables usually carry both columns; the scan carries `mu95_obs` and `mu95_exp`.
      `scan_contour.py --limit-kind observed|expected|both` selects the pair on BOTH sides at once;
      render both variants and lead with the one matching the published comparison figure (RRR Fig 3
      is expected-vs-expected). Which column the published figure used is a per-analysis fact — pin
      it via the figure contract, don't assume.
- [ ] **NEVER INTERPOLATE THE REFERENCE.** A published per-point UL grid is a set of exact
      statements at its own lattice — σ-UL varies ~10× between adjacent Δm rows, so interpolating
      (or worse, nearest-extrapolating) it fabricates reference values that were never published.
      The headline fill colors ONLY exact (tolerance-snapped) lattice matches
      (`scan_contour._exact_grid_lookup`); design the scan grid ON the published lattice so the
      comparison is point-for-point.
- [ ] **WHITE ≠ HOLE — state the semantics on the figure.** Three cell states: scanned+published →
      colored; scanned but NO published point → **white + gray circle** with an on-figure note (white
      alone would falsely read "agrees within 5%" — the published RRR figure leaves exactly this
      ambiguous, ours must not); not scanned → hole (not computed). Scan-only Δm rows are dropped
      from the fill mesh but still feed the µ₉₅=1 contour.

## The contour itself
- [ ] **Interpolated, not asserted.** The boundary is the **µ₉₅ = 1 crossing** interpolated across the
      grid (`scan_contour.py`: 1-D linear crossing for a line; `tricontour` level 1.0 for a grid). A
      contour needs enough points to triangulate; too few → no contour drawn (the tool says so, loudly).
- [ ] **Excluded = µ₉₅ < 1**, allowed = µ₉₅ ≥ 1. The same CLs verdict as a single point, now as a region.
- [ ] **95% CL exclusion (CLs), never a 5σ discovery** — on the figure and in the prose.
- [ ] **Reproduction shows BOTH curves.** Overlay the ATLAS HEPData reference contour
      (`--atlas-contour`) so "the mapyde contour follows the ATLAS contour" is read directly; quote the
      relative-difference of the reach (the 1-D analogue of the paper's color map) where available.
- [ ] **The headline is the Fig-3 FORM.** With both `--atlas-contour` and `--atlas-limit` on a 2-D grid,
      `scan_contour.py` writes `<out>__fig3` (observed) and `<out>__fig3_expected` — ONE panel each:
      rel-diff fill (exact reference matches only) + ATLAS contour + smooth mapyde µ₉₅=1 contour on
      the **log-Δm** compressed-plane convention (`plot-guidelines.md`). Those single panels, not the
      two-panel diagnostics, are the artifacts to show — lead with the variant matching the published
      figure's column (like-columns rule above).

## Record
- [ ] The scan dir's `RESULT.md` is generated-from / cross-checked against `scan.json` (numbers in the
      prose = numbers in the pack), exactly as a single run's `RESULT.md` tracks `result.json` (step 7).
- [ ] CHECK IN with the requester: show the contour/slice, state coverage and (reproduction) the ATLAS
      agreement or (reinterpretation) the newly-excluded region.
