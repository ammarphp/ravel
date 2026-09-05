# Benchmark: `conf2016037_gluino_2step_sleptons_1400_60`

- Analysis: `conf2016037`; routine: `ATLAS_2016_CONF_2016_037 (run-local PATCHED copy)`.
- Model: gluino pair, 2-step slepton-mediated (1400,730,395,60), light flavours, NNLOapprox+NNLL (k=1.975), A14; masses (parent, LSP): (1400.0, 60.0) GeV.
- Historical baseline timestamp: `2026-07-09T02:22:22+00:00`.
- Recorded regression status: OK; gate ok: True.

## Statistical layer

Metric: driving-signal-region model-independent S95, measured in events.
Observed ratio: 0.918208; deviation |1 − ratio|: 8.2%.
Observed/expected S95 from the replay: 4.68286 / 3.80526.
Best signal region: `SR3l2`; limit tier: Ideal.
Observed cross-section-limit ratio (when available): None.
Numerical stability against the stored baseline: True.
Stability measures repeatability, not agreement with the experiment.

## Selection acceptance and efficiency

Unscorable: no published acceptance reference is certified by this benchmark.
A successful S95 comparison does not fill this gap.

scored against a run-local patched copy of the Rivet routine (class renamed _PATCHED; the shared original is untouched): the stock routine books only cutflow objects, and the patch adds physical signal-region counter filling so per-SR yields exist to compare — it does not alter the selection (full provenance in the dev run record)

## Reproduce

```bash
python3 scripts/run.py ravel.validation.benchmark --case conf2016037_gluino_2step_sleptons_1400_60
```

The public quickstart ships the fast case's cached inputs. Other cases require the
development evidence named in the registry; absent inputs must produce a failure.
This command re-fits cached inputs. Fresh generation and detector validation are separate work.
