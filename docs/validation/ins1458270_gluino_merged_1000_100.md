# Benchmark: `ins1458270_gluino_merged_1000_100`

- **Analysis**: ATLAS_2016_I1458270
- **Model point**: gluino-pair MLM-merged (+j,+jj, xqcut=250=m/4 from measured stability scan), matched sigma, NLO+NNLL (k=1.939)
- **Published s95 (obs)**: 5.4
- **Reproduced s95 (obs/exp)**: 5.08311 / 8.82545
- **s95 ratio (obs)**: 0.941317  →  **Δ = 5.9%**
- **Best signal region**: `5j` (matches published choice: True)
- **Verdict tier**: Ideal (required: Ideal); gate ok = True
- **µ95 stability check**: True (rtol 0.1)
- **Provenance checks**: True
- **Wall time (pyhf re-fit)**: 9.7s

**Regenerate**:
```bash
python3 framework/benchmark/run_benchmark.py --case ins1458270_gluino_merged_1000_100
```

Ground truth transcribed from the published analysis (reference + table noted in
`framework/benchmark/cases.json`); the fast gate re-fits the cached artifacts
through the real pyhf layer on every run.
