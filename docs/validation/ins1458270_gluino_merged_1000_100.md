# Benchmark: `ins1458270_gluino_merged_1000_100`

- Analysis: `ins1458270`; routine: `ATLAS_2016_I1458270`.
- Model: gluino-pair MLM-merged (+j,+jj, xqcut=250=m/4 from measured stability scan), matched sigma, NLO+NNLL (k=1.939); masses (parent, LSP): (1000.0, 100.0) GeV.
- Historical baseline timestamp: `2026-07-09T02:22:22+00:00`.
- Recorded regression status: OK; gate ok: True.

## Statistical layer

Metric: driving-signal-region model-independent S95, measured in events.
Observed ratio: 0.941317; deviation |1 − ratio|: 5.9%.
Observed/expected S95 from the replay: 5.08311 / 8.82545.
Best signal region: `5j`; limit tier: Ideal.
Observed cross-section-limit ratio (when available): None.
Numerical stability against the stored baseline: True.
Stability measures repeatability, not agreement with the experiment.

## Selection acceptance and efficiency

Certification verdict: PASS; regression tier: Good.
Recorded residual: 8.08%.
A regression gate can pass its historically locked floor while certification is WARN or FAIL.

## Reproduce

```bash
python3 framework/benchmark/run_benchmark.py --case ins1458270_gluino_merged_1000_100
```

The public quickstart ships the fast case's cached inputs. Other cases require the
development evidence named in the registry; absent inputs must produce a failure.
This command re-fits cached inputs. Fresh generation and detector validation are separate work.
