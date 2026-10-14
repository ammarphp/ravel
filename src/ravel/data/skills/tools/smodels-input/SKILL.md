---
name: smodels-input
description: Use when preparing an SLHA or LHE input for SModelS, choosing decomposition settings (sigmacut, mass gaps, prompt and stable widths, data types, signal-region combination), or reading what a SModelS result does and does not say about a model, in RAVEL's model-portfolio mode.
license: Apache-2.0
compatibility: SModelS 3.1.1 with its 3.1.1 database in RAVEL's isolated SModelS environment, as pinned in the toolchain manifest.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "model-portfolio"
  upstream-version: "smodels:smodels=3.1.1"
  last-reviewed: "2026-10-11"
---

# SModelS input

## RAVEL's path

`model-portfolio` runs SModelS on an unchanged supplied SLHA or LHE file with
an explicitly trusted 3.1.1 database pickle and the installed SModelS 3.1.1.
The document names the particle model (`mssm`, `qnumbers` from the input, or a
supplied Python model) and the decomposition protocol: analyses and
topologies, data types (`all`, `efficiencyMap`, `upperLimit`),
`combine_srs`, `sigmacut_fb`, the mass gaps, `maxcond` and the prompt and
stable width boundaries.

## What the input must carry

An SLHA input needs the mass spectrum, decay tables for the unstable new
particles and production cross sections in `XSECTION` blocks; SModelS
provides `smodelsTools.py xseccomputer` to add them. Check before running:

```python ravel-block=slha-input-census
import re

def slha_census(text, unstable_pdgs):
    """Missing pieces of an SLHA input for SModelS."""
    blocks = {m.group(1).upper() for m in re.finditer(r"^BLOCK\s+(\S+)", text, re.M | re.I)}
    decays = {int(m.group(1)) for m in re.finditer(r"^DECAY\s+(-?\d+)", text, re.M | re.I)}
    xsections = len(re.findall(r"^XSECTION\s", text, re.M | re.I))
    return {"mass_block": "MASS" in blocks,
            "missing_decays": sorted(set(unstable_pdgs) - decays),
            "xsection_blocks": xsections}
```

## Pitfalls

- A database or code version other than the qualified 3.1.1 changes which
  results exist. Caught by `ravel.physics.reinterpret_db.validate_document`.
- Settings outside their meaning (a negative `sigmacut_fb`, `maxcond` above
  1, a stable width above the prompt width). Caught by
  `ravel.physics.reinterpret_db.validate_document`.
- Advisory: without `XSECTION` blocks SModelS has no production rates to test;
  use the `slha-input-census` block and record how the cross sections were made.
- Advisory: "not excluded" means no database result constrains the tested
  topologies; topologies missing from the database are listed as untested and
  are not allowed by that fact.
- Advisory: a newer SModelS database can contain results (for example new
  topology maps) that 3.1.1 lacks; name the database version in every result.

More: `references/review.md`. Upstream: the SModelS 3.1 documentation,
https://smodels.readthedocs.io/.
