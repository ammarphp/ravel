# Benchmark: `ins1458270_squark_merged_800_100`

- **Analysis**: ATLAS_2016_I1458270
- **Model point**: squark-pair (800,100) MLM-merged (+1j,+2j ME, xqcut=80, qCut=100), matched sigma NLO+NNLL (k=0.855)
- **Published s95 (obs)**: 44.0
- **Reproduced s95 (obs/exp)**: 43.8947 / 55.2266
- **s95 ratio (obs)**: 0.997607  →  **Δ = 0.2%**
- **Best signal region**: `2jl` (matches published choice: True)
- **Verdict tier**: Ideal (required: Ideal); gate ok = True
- **µ95 stability check**: True (rtol 0.1)
- **Provenance checks**: True
- **Wall time (pyhf re-fit)**: 11.0s

**Regenerate**:
```bash
python3 framework/benchmark/run_benchmark.py --case ins1458270_squark_merged_800_100
```

Ground truth transcribed from the published analysis (reference + table noted in
`framework/benchmark/cases.json`); the fast gate re-fits the cached artifacts
through the real pyhf layer on every run.
