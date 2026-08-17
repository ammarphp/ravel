# Benchmark: `conf2016054_gluino_onestep_1500_60`

- **Analysis**: ATLAS_2016_CONF_2016_054
- **Model point**: gluino one-step x=1/2 (m_go=1500, m_C1=780, m_LSP=60), go->qq'C1, C1->W N1, NLO+NNLL (k=1.985)
- **Published s95 (obs)**: 5.5
- **Reproduced s95 (obs/exp)**: 5.0246 / 6.44594
- **s95 ratio (obs)**: 0.913563  →  **Δ = 8.6%**
- **Best signal region**: `GG-4j-0lowx` (matches published choice: True)
- **Verdict tier**: Ideal (required: Ideal); gate ok = True
- **µ95 stability check**: True (rtol 0.1)
- **Provenance checks**: True
- **Wall time (pyhf re-fit)**: 10.9s

**Regenerate**:
```bash
python3 framework/benchmark/run_benchmark.py --case conf2016054_gluino_onestep_1500_60
```

Ground truth transcribed from the published analysis (reference + table noted in
`framework/benchmark/cases.json`); the fast gate re-fits the cached artifacts
through the real pyhf layer on every run.
