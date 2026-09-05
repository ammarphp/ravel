# Benchmarks

This directory separates registered physics regression checks from a prospective
study of agent behavior. Software tests live in [`tests/`](../tests/).

| Path | Contents |
|---|---|
| `cases.json` | Case definitions, published references, required artifacts, and numerical floors |
| `results.json` | Committed historical benchmark baseline |
| `run_benchmark.py` | Runs selected cases through the statistical and provenance checks |
| `capabilities.json` | Internal classifications for reference physicist tasks; not an autonomous success-rate dataset |
| `specs/` | Recorded scan specifications |
| `governance/` | Prospective experiment registry and descriptive scorer; no completed campaign results |

## Start with the bundled replay

After [installation](../docs/installation.md):

```bash
ravel replay --out ravel-replay-benchmark
```

This reruns the statistics for the bundled fast case. Simulation inputs are
cached, and acceptance may use the recorded certification. The fresh output is
separate from `results.json`. Choose a new output directory for each attempt.

The [benchmark guide](../docs/validation/benchmark-guide.md) describes individual
case selection and full-set execution. The public distribution includes only a
curated subset of raw run artifacts; a full replay can fail when required inputs
are unavailable. Preserve and report these breaches rather than treating the
historical baseline as a fresh result.

Read [validation results](../docs/validation/results.md) for the distinction
between statistical recovery, acceptance certification, implementation parity,
and end-to-end agreement. See the [governance protocol](governance/README.md) for
assignment accounting and its separate scientific limitations.
