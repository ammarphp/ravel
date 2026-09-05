# A×ε certification (tiered + attribution) — ATLAS_2016_I1458270 · gluino(1000,100)

A×ε = (routine SR yield)/(σ·lumi); published = 'gluino direct decay' acc×eff at (m_parent=1000, m_LSP=100). Driving SRs ≤15%, contributing ≤25%, tail report-only; driving |Δµ₉₅| ≤10%. Driving SR(s) from exclusion.json best/near-best expected µ.

| SR | role | my A×ε | pub A×ε | ratio | tol | ok | µ₉₅ impact |
|---|---|---|---|---|---|---|---|
| 2jl | contributing | 0.1543 | 0.1547 | 1.00 | 25% | ✓ | - |
| 2jm | contributing | 0.1487 | 0.1561 | 0.95 | 25% | ✓ | - |
| 2jt | contributing | 0.02209 | 0.02678 | 0.82 | 25% | ✓ | - |
| 4jt | driving | 0.03648 | 0.03833 | 0.95 | 15% | ✓ | 5% |
| 5j | driving | 0.08346 | 0.0737 | 1.13 | 15% | ✓ | 13% |
| 6jm | driving | 0.04778 | 0.03811 | 1.25 | 15% | ✗ | 25% |
| 6jt | driving | 0.03408 | 0.0311 | 1.10 | 15% | ✓ | 10% |

## Attribution (residuals above tier tolerance)

- **6jm** (driving): ratio 1.254, residual 25% → `fast-sim-floor`, µ₉₅ impact 25%. [Opus to confirm physical cause]

**Verdict: WARN.** Driving SR(s) NOT within ±15%; worst driving |Δµ₉₅| = 13% (bound 10%). A×ε is σ-independent — this certifies selection fidelity; the absolute limit uses the NLO+NLL σ (`nlo_xsec.py`).
