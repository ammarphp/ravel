# Visual-fidelity check — ATLAS_2016_I1458270 (gluino/squark, Rivet path)

Does our model overlay reproduce the experiment's published figure? Compared our
`overlay_on_data.py` plot + `sr_yields.json` against the actual published figures
(fetched via `fetch_figures.py`: `outputs/published/figures/`).

## Published figures inspected (read directly)
- **fig2a** — m_eff(incl) distribution (CRγ for SR4j): log-y, 800–3500 GeV, 200-GeV bins, data points
  over a stacked SM background, with a Data/MC ratio panel and the SR threshold arrow.
- **fig4** — signal-region yields: the 7 SRs (2jl…6jt) with data points over the stacked SM total
  (W+jets, t̄t, Z+jets, Diboson, Multi-jet) and a Data/SM-Total ratio panel.

## Numerical fidelity (our values vs the published figure)
Our per-SR observed + background (from the bundled REF, = the HEPData numbers behind fig4) reproduce
the figure's values:
| SR | our obs / bkg | fig4 (read off) |
|---|---|---|
| 2jl | 263 / 296 | data ≈ 260, SM ≈ 290 ✓ |
| 2jt | 26 / 23 | data ≈ 26, SM ≈ 24 ✓ |
| 5j | 7 / 13.6 | data ≈ 7, SM ≈ 13 ✓ |
| 6jt | 3 / 3.8 | data ≈ 3, SM ≈ 3–4 ✓ |
The data + total background our overlay sits on ARE the published numbers (same HEPData source), so the
overlay is genuinely *on the published histogram* — the intended new-model test.

## Structural fidelity (our overlay vs the published style)
Match: same observable + range + log-y; data points; a background histogram; a ratio panel; the
signal drawn on top (the new-model contribution). For the gluino/squark, signal+background rises
clearly above the data in the sensitive SRs — visible exclusion, the publishable view.

## Gaps to the exact published figure (documented)
1. **No per-process background stack.** The bundled REF gives only the *total* SM background (`y02`);
   ATLAS shows the decomposition (γ/W/t̄t/Z/Diboson). Reproducing the stack would need the per-process
   tables (now fetchable via `hepdata-cli`) — a future refinement.
2. **Re-plot, not the ATLAS figure.** Matplotlib styling, no ATLAS systematic-band hatching.
3. ATLAS's published m_eff distributions are mostly control/validation regions (fig2); our SR m_eff
   overlay is the N−1-style distribution the routine fills.

## Verdict: PASS (numerically faithful; documented styling gaps)
The overlay reproduces the published data + total background (values match the figure) and adds the
model signal — the experiment-comparable test the workflow promises. The only gaps are cosmetic
(background decomposition + styling), not numerical.
