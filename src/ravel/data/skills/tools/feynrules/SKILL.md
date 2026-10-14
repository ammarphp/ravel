---
name: feynrules
description: Use when writing or checking a FeynRules model file, deriving Feynman rules, exporting a UFO for MadGraph, or reviewing hermiticity, mass spectrum and two-body widths of a new model through RAVEL's model-sources, model-derivation-bridge and model-provider-bridge modes.
license: Apache-2.0
compatibility: FeynRules 2.3.49 on a licensed Wolfram kernel 14.3 or 15.0, as pinned in the toolchain manifest. RAVEL never activates a Wolfram licence.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "model-sources model-derivation-bridge model-provider-bridge"
  upstream-version: "wolfram:feynrules=2.3.49"
  last-reviewed: "2026-10-11"
---

# FeynRules

## RAVEL's path

1. `model-provider-bridge` qualifies the Wolfram kernel and the FeynRules
   package before any model work.
2. `model-sources` detects and exports a symbolic model source.
3. `model-derivation-bridge` loads a trusted `.fr` model, runs the selected
   checks and writes a fresh UFO. Its checks are separate claims: native
   derivation, the selected numeric checks and physical validity are reported
   apart. See `docs/reference/model-sources.md`.

The selected checks are built by `ravel.physics.model_physical_checks.script`:
`CheckHermiticity` on the Lagrangian (with flavour expansion), the recorded
`FeynmanGauge` setting, and `ComputeWidths` for at most eight declared two-body
channels, optionally compared with an independent scalar-to-fermion-pair width.

## Writing the model file

Write the model so the checks can run: one Lagrangian symbol per sector,
parameters declared with values and `Description`, external parameters in
named blocks, and masses and widths declared on every new particle. Keep the
model file and every restriction file under one directory and pin it.

## Pitfalls

- A non-hermitian Lagrangian exports without error. Caught by
  `ravel.physics.model_physical_checks.script` when the request sets
  `hermiticity`; the result is recorded, not assumed.
- Masses in the model file can disagree with the mass matrices. Caught by
  `ravel.physics.model_derivation_bridge.mass_witness`, which compares each
  returned mass with the model-file value (0.1% relative); rows that the native
  spectrum call omits stay unresolved.
- A restriction file that fails to load leaves parameters unrestricted.
  Caught by `ravel.physics.model_derivation_bridge.restriction_witness`.
- FeynRules 2.3.49 writes some UFO error statements in Python 2 form
  (`raise UFOError, "message"`), which Python 3 cannot import. Caught by
  `ravel.physics.ufo_interop.convert_text`; it rewrites only that form and
  journals each edit:

```python ravel-block=python2-raise-rewrite
from ravel.physics import ufo_interop

def rewrite_ufo_text(text):
    """Python 3 form of FeynRules 2.3.49 literal UFOError raises, with the edit list."""
    converted, edits = ufo_interop.convert_text(text)
    return converted, [(e["line"], e["message"]) for e in edits]
```

- Advisory: widths computed by `ComputeWidths` are two-body tree-level
  widths of the vertices you select; they are not total widths of the model.
  Record which channels were included.
- Advisory: the exported UFO carries the gauge setting (`FeynmanGauge`) in
  force at export; run the checks with the same setting you export with.

More: `references/checks.md` and `references/review.md`.
