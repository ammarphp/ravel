# A×ε certification (SimpleAnalysis/Delphes path, tiered + attribution) — 

A×ε = (selected events)/(generated events); published = 'synthetic-model' acceptance×efficiency at (m_parent=100, Δm=10). Driving SRs ≤15%, contributing ≤25%, tail (<5 events) report-only; driving residual bound 10%. Driving SR = the most-occupied bin (and within 1.5×). Published acc×eff = acceptance(×0.001) × efficiency at the same grid node.

| SR | region | role | my A×ε | pub A×ε | node | ratio | tol | ok | residual |
|---|---|---|---|---|---|---|---|---|---|
| SR_A | region-A | driving | 0.1 | 0.1 | grid node (100,10) | 1.00 | 15% | OK | 0% |

**Verdict: PASS.** Driving SR(s) within ±15%; worst driving residual = 0% (bound 10%). This checks point-estimate selection agreement at the stated normalization; it does not isolate detector response or certify statistical coverage. MC and published uncertainties are not propagated. A discrepancy requires diagnosis of selection, normalization, generation and detector response before any retuning.
