# A×ε certification (tiered + attribution) — ATLAS_2016_I1458270 · squark(800,100)

A×ε = (routine SR yield)/(σ·lumi); published = 'squark direct decay' acc×eff at (m_parent=800, m_LSP=100). Driving SRs ≤15%, contributing ≤25%, tail report-only; driving |Δµ₉₅| ≤10%. Driving SR(s) from exclusion.json best/near-best expected µ.

| SR | role | my A×ε | pub A×ε | ratio | tol | ok | µ₉₅ impact |
|---|---|---|---|---|---|---|---|
| 2jl | driving | 0.2386 | 0.2446 | 0.98 | 15% | ✓ | 2% |
| 2jm | driving | 0.1504 | 0.153 | 0.98 | 15% | ✓ | 2% |
| 2jt | contributing | 0.0187 | 0.02296 | 0.81 | 25% | ✓ | - |
| 4jt | contributing | 0.0053 | 0.007638 | 0.69 | 25% | ✗ | - |
| 5j | contributing | 0.0106 | 0.01427 | 0.74 | 25% | ✗ | - |
| 6jm | tail | 0.0036 | 0.005527 | 0.65 | - | ✓ | - |
| 6jt | tail | 0.0021 | 0.003271 | 0.64 | - | ✓ | - |

## Attribution (residuals above tier tolerance)

- **4jt** (contributing): ratio 0.694, residual 31% → `merging`, µ₉₅ impact None%. [Opus to confirm physical cause]
- **5j** (contributing): ratio 0.743, residual 26% → `merging`, µ₉₅ impact None%. [Opus to confirm physical cause]

**Verdict: PASS.** Driving SR(s) within ±15%; worst driving |Δµ₉₅| = 2% (bound 10%). A×ε is σ-independent — this certifies selection fidelity; the absolute limit uses the NLO+NLL σ (`nlo_xsec.py`).
