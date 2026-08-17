# Checklist — the SUMMARY-PLOT track  ·  task_mode=summary_plot  ·  no event generation

The track behind "show me the searches sensitive to X" / "summary plot of limits on Y"
(2 of the 7 standing prompts; Reinterpretation-Forum product type 2). The base path generates
NOTHING — it harvests, converts, and overlays PUBLISHED limits. Worked precedent: the
2026-07-06 HVT Z′→WW survey run (census → harvested limits → coverage finding). `stat_mode` stays
`none-survey`; the deliverable never claims a new limit.

## 1. Sensitivity census ([judgment] — protocol P6 + trap T4)
- Candidate analyses from: the resource sweep per signature keyword, recast-DB listings, the
  experiments' summary-plot pages, INSPIRE. For EACH candidate: the final state, mass range
  actually covered (trigger/boosted floors — trap T4), σ×BR convention of its published limit,
  obs+exp availability, HEPData record.
- A candidate is IN when its published limit constrains the requested model/range; OUT with a
  one-line reason (out-of-range, wrong final state, superseded). The physicist sees the census
  table at CHECK-IN 1 — inclusion is reviewable, not silent.

## 2. Harvest (mechanical)
`hepdata_fetch.py --tables` per included analysis → the limit-vs-mass table(s); record per curve:
table name, obs|exp, ±Nσ bands present, units, the exact quantity limited (σ, σ×BR, σ×BR×A, µ
on which reference σ). NO digitization when HEPData has the table; digitize (declared) only when
it does not.

## 3. BASIS MANIFEST (the gate — protocol P2 / trap T9; nothing renders before it)
`<rundir>/inputs/basis_manifest.json`:
```json
{"schema_version": 1,
 "target_basis": {"quantity": "sigma x BR(Z'->WW) [pb]", "model": "HVT model A, g_V=1",
                   "sqrt_s": "13 TeV", "notes": "theory curve source + order"},
 "curves": [{"source": "<analysis id + table>", "kind": "observed|expected",
             "native_basis": "<exactly what the paper limits>",
             "transformation": "<the algebra onto target_basis, factor(s) + source>",
             "identity_check": "<where verifiable, e.g. on-contour UL/sigma_model=1, or NONE>"}]}
```
- REFUSE the overlay until every curve has its transformation written (a curve that cannot be
  mapped is dropped WITH a stated reason, not force-fit).
- Model-variant conventions (HVT A vs B, charge/flavor sums) are basis entries, not footnotes.
- **Exact values in check tables (CR-130, catalogue A9):** every identity/spot-check row shown to
  the physicist (any check-in, the ladder) uses the EXACT harvested value once a harvest exists;
  figure read-offs are pre-harvest only and must be labeled "read-off". A survey read-off quoted
  where the exact number sat on disk shipped a 2.5%-off row to a physicist-facing table.

## 4. Render (mechanical; the usual gates)
One panel, common axes; per-curve provenance in the legend (analysis + obs/exp); house style +
the CR-016 lint gate; theory σ×BR curve(s) overlaid where the ask implies them; **coverage gaps
drawn as first-class** — an uncovered mass window is shaded/annotated, not silently absent
(the HVT survey's low-mass asymmetry finding is the pattern).

## 5. Deliverable + labels
The figure + the census table + the basis manifest ARE the deliverable. Labels: `none-survey`;
"published limits, re-expressed on <target basis>; no new limit is derived here." Ladder rungs:
R6 only (+ the identity checks of §3) — say so in VERIFICATION-LADDER.md.

## Stop conditions
- Two candidate papers limit INCOMPATIBLE quantities with no published conversion → present both
  panels or escalate; never a silent unit fudge.
- The ask's range is outside every published limit (T4 everywhere) → the coverage statement IS
  the deliverable.
