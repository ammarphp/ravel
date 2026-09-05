# Benchmark: `ins1458270_squark_merged_800_100`

- Analysis: `ins1458270`; routine: `ATLAS_2016_I1458270`.
- Model: squark-pair (800,100) MLM-merged (+1j,+2j ME, xqcut=80, qCut=100), matched sigma NLO+NNLL (k=0.855); masses (parent, LSP): (800.0, 100.0) GeV.
- Historical baseline timestamp: `2026-07-09T02:22:22+00:00`.
- Recorded regression status: OK; gate ok: True.

## Statistical layer

Metric: driving-signal-region model-independent S95, measured in events.
Observed ratio: 0.997607; deviation |1 − ratio|: 0.2%.
Observed/expected S95 from the replay: 43.8947 / 55.2266.
Best signal region: `2jl`; limit tier: Ideal.
Observed cross-section-limit ratio (when available): None.
Numerical stability against the stored baseline: True.
Stability measures repeatability, not agreement with the experiment.

## Selection acceptance and efficiency

Certification verdict: PASS; regression tier: Ideal.
Recorded residual: 3.94%.
A regression gate can pass its historically locked floor while certification is WARN or FAIL.

## Reproduce

```bash
python3 framework/benchmark/run_benchmark.py --case ins1458270_squark_merged_800_100
```

The public quickstart ships the fast case's cached inputs. Other cases require the
development evidence named in the registry; absent inputs must produce a failure.
This command re-fits cached inputs. Fresh generation and detector validation are separate work.
