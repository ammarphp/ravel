---
name: ma5-expert
description: Use when working with MadAnalysis 5 - expert-mode C++ analyses, recast PAD analyses run through SampleAnalyzer, or reading SAF output files (cut-flow counters, region selections, histograms) for RAVEL's ma5-saf and ma5-pad modes.
license: Apache-2.0
compatibility: MadAnalysis 5 v1.11.1 with SampleAnalyzer from RAVEL's ma5 toolchain group, built against the recast-base ROOT and Delphes.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "ma5-saf ma5-pad"
  upstream-version: "ma5:ma5=1.11.1"
  last-reviewed: "2026-10-11"
---

# MadAnalysis 5

## RAVEL's path

- `ma5-pad` runs an already-built PAD analysis with the original
  SampleAnalyzer executable on a fixed list of event files. Building,
  installing and generating events are separate operations.
- `ma5-saf` takes supplied SAF output and keeps every printed value, both
  weight-sign channels and the under- and overflow bins. It does not combine
  populations or invent missing uncertainties.

## Reading SAF output

A SAF counter block holds the cut name and three rows (entries, sum of
weights, sum of squared weights), each with a positive-weight and a
negative-weight column. Read them with RAVEL's reader and keep both columns:

```python ravel-block=saf-counters
from ravel.physics import ma5_saf_reader

def cutflow(saf_text):
    """[(cut, positive sumw, negative sumw)] from a SAF cut-flow file."""
    counters = ma5_saf_reader.counters(saf_text)
    rows = [counters["initial"], *counters["cuts"]]
    return [(r["name"], r["positive"]["sumw"], r["negative"]["sumw"]) for r in rows]
```

## Expert mode

Expert mode writes a standalone SampleAnalyzer work directory whose analysis
is C++ you edit and compile. The expert-mode paper (arXiv:1405.3982) describes
the layout and build steps; check them against the v1.11.1 help output.

```bash ravel-block=expert-mode-shape
./bin/ma5 -E <work-dir> <analysis-name>
```

## Pitfalls

- A cut-flow file with a counter row missing, or with the two sign channels
  merged, loses information silently. Caught by
  `ravel.physics.ma5_saf_reader.counters`.
- Two cuts or two regions with the same name make the cut-flow ambiguous.
  Caught by `ravel.physics.ma5_saf_reader.counters` and
  `ravel.physics.ma5_saf_reader.regions`.
- Advisory: PAD analyses come with a detector tune (a Delphes card or SFS
  description); running them on events made with another card changes the
  efficiencies. Record the tune used.
- Advisory: MA5 and its PAD analyses are versioned separately; record the PAD
  analysis version with the MA5 version.

More: `references/review.md`. Upstream: https://madanalysis.irmp.ucl.ac.be/,
Conte, Fuks and Serret, Comput. Phys. Commun. 184 (2013) 222, arXiv:1206.1599;
expert mode: Conte, Dumont, Fuks and Wymant, arXiv:1405.3982.
