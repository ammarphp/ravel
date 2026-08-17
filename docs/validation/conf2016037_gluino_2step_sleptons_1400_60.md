# Benchmark: `conf2016037_gluino_2step_sleptons_1400_60`

- **Analysis**: ATLAS_2016_CONF_2016_037 (run-local PATCHED copy)
- **Model point**: gluino pair, 2-step slepton-mediated (1400,730,395,60), light flavours, NNLOapprox+NNLL (k=1.975), A14
- **Published s95 (obs)**: 5.1
- **Reproduced s95 (obs/exp)**: 4.68286 / 3.80526
- **s95 ratio (obs)**: 0.918208  →  **Δ = 8.2%**
- **Best signal region**: `SR3l2` (matches published choice: True)
- **Verdict tier**: Ideal (required: Ideal); gate ok = True
- **µ95 stability check**: True (rtol 0.1)
- **Provenance checks**: True
- **Wall time (pyhf re-fit)**: 8.4s

- **Note**: scored against a run-local patched copy of the Rivet routine (class renamed _PATCHED; the shared original is untouched): the stock routine books only cutflow objects, and the patch adds physical signal-region counter filling so per-SR yields exist to compare — it does not alter the selection (full provenance in the dev run record)
**Regenerate**:
```bash
python3 framework/benchmark/run_benchmark.py --case conf2016037_gluino_2step_sleptons_1400_60
```

Ground truth transcribed from the published analysis (reference + table noted in
`framework/benchmark/cases.json`); the fast gate re-fits the cached artifacts
through the real pyhf layer on every run.
