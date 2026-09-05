# Benchmark: `conf2016054_gluino_onestep_1500_60`

- Analysis: `ATLAS-CONF-2016-054`; routine: `ATLAS_2016_CONF_2016_054`.
- Model: gluino one-step x=1/2 (m_go=1500, m_C1=780, m_LSP=60), go->qq'C1, C1->W N1, NLO+NNLL (k=1.985); masses (parent, LSP): (1500.0, 60.0) GeV.
- Historical baseline timestamp: `2026-07-09T02:22:22+00:00`.
- Recorded regression status: OK; gate ok: True.

## Statistical layer

Metric: driving-signal-region model-independent S95, measured in events.
Observed ratio: 0.913563; deviation |1 − ratio|: 8.6%.
Observed/expected S95 from the replay: 5.0246 / 6.44594.
Best signal region: `GG-4j-0lowx`; limit tier: Ideal.
Observed cross-section-limit ratio (when available): None.
Numerical stability against the stored baseline: True.
Stability measures repeatability, not agreement with the experiment.

## Selection acceptance and efficiency

Unscorable: no published acceptance reference is certified by this benchmark.
A successful S95 comparison does not fill this gap.

## Reproduce

```bash
python3 scripts/run.py ravel.validation.benchmark --case conf2016054_gluino_onestep_1500_60
```

The public quickstart ships the fast case's cached inputs. Other cases require the
development evidence named in the registry; absent inputs must produce a failure.
This command re-fits cached inputs. Fresh generation and detector validation are separate work.
