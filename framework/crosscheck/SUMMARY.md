# Independent recasting cross-check — SModelS vs our pyhf

An external, independently-implemented recasting tool (SModelS 3.1.1, with the official 1.3 GB
database of digitised ATLAS+CMS efficiency maps, fetched from Zenodo) run on the **same** gluino
model, to check our pyhf exclusion does not stand alone.

## Input
`gluino_slha.dat` — the gluino simplified model (m(g̃)=1000, m(χ̃₁⁰)=100, g̃→qq̄χ̃₁⁰), with the
LO cross-section σ(g̃g̃)=0.201 pb (our MadGraph value) in an `XSECTION` block.

## SModelS result
SModelS reports `r = σ_predicted / σ_UL^95` per analysis (r > 1 ⇒ excluded):

| Analysis | r_obs | r_exp |
|---|---|---|
| CMS-SUS-16-033 (highest) | **42.3** | 24.6 |
| CMS-SUS-19-006 | 27.3 | 35.3 |
| ATLAS-SUSY-2016-07 | 17.7 | 21.0 |
| **ATLAS-SUSY-2015-06** (= our `ATLAS_2016_I1458270`) | **8.07** | 4.73 |

→ The gluino is **excluded** by many analyses; SModelS confirms our verdict independently.

## Head-to-head with our pyhf, on the same analysis
For ATLAS-SUSY-2015-06, r and the signal-strength limit are reciprocal: r ≈ 1/µ₉₅.

| Quantity | our pyhf (Rivet → counting) | SModelS (digitised eff. maps) |
|---|---|---|
| ATLAS-SUSY-2015-06 | µ₉₅ = 0.10 ⇒ r ≈ **10** | r_obs = **8.07** |

**Agreement ~20%** between two fully independent recasts (our MadGraph→Pythia→Rivet→pyhf chain vs
SModelS's digitised ATLAS efficiency maps + best-SR CLs), both on the same LO cross-section. The
residual difference is the expected level for independent recasting methods (different SR treatment,
efficiency-map binning vs our routine A×ε). This is exactly the corroboration R7 requires.

## Notes
- SModelS's database also serves as a **digitised SR-data source** (efficiency maps + observed/expected
  limits) for analyses Rivet does not bundle — an alternative to the bundled REF.
- MadAnalysis5 + CheckMATE were cloned (`stages/01-event-generation/build/tools/`); their C++/ROOT
  builds are heavy and tracked in `KNOWN-LIMITATIONS.md`. SModelS (pip) is the working cross-check.
- Reproduce: `runSModelS.py -f framework/crosscheck/gluino_slha.dat -o framework/crosscheck/`
  (the XSECTION block format is pyslha's: `scale_scheme qcd_order ew_order kappa_f kappa_r pdf_id value code`).
