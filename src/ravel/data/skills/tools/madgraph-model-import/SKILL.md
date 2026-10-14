---
name: madgraph-model-import
description: Use when loading a UFO model into MadGraph5_aMC@NLO - choosing between the restricted and full model, checking that a UFO directory is complete, or preparing a UFO from FeynRules for RAVEL's model-events or model-tool-bridge modes.
license: Apache-2.0
compatibility: MadGraph5_aMC@NLO 2.9.27 model import as pinned in the toolchain manifest; UFO directories supplied as trusted source trees.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "model-events model-tool-bridge"
  upstream-version: "madgraph:madgraph=2.9.27"
  ravel-parameters: "model-events.model_tree model-events.cards.parameter"
  last-reviewed: "2026-10-11"
---

# MadGraph model import

## What RAVEL does

`model-events` takes the UFO as a pinned source tree (`model-events.model_tree`)
and refuses one that lacks any of the seven core UFO modules. It imports the
model as `<ufo>-full`, so no restriction file is applied, and the parameter
values come only from the supplied card (`model-events.cards.parameter`).
`model-tool-bridge` checks UFO parameters and tree-level processes through
MadGraph before any generation.

## Full or restricted

MadGraph 2.9.27 applies `restrict_default.dat` when a model directory carries
one, and loads the unrestricted model when the name ends in `-full` (stated by
`help import` in that version). A restriction can remove parameters and
interactions from the loaded model, so a later parameter card cannot bring
them back. List the restriction files before choosing:

```python ravel-block=ufo-census
from pathlib import Path

CORE = ("__init__.py", "parameters.py", "particles.py", "vertices.py",
        "couplings.py", "object_library.py", "lorentz.py")

def ufo_census(path):
    """Missing core modules and the restriction cards of a UFO directory."""
    root = Path(path)
    return {"missing": [n for n in CORE if not (root / n).is_file()],
            "restrictions": sorted(p.name for p in root.glob("restrict_*.dat"))}
```

## Pitfalls

- A UFO missing a core module fails late or imports partially. Caught by
  `ravel.physics.model_events.inputs`, which requires all seven modules.
- Advisory: importing without `-full` applies `restrict_default.dat` when it
  exists; parameters it fixes cannot be changed by a later card. RAVEL's
  model-events imports `-full`; scripts outside it should do the same unless
  the restriction is intended and recorded.
- UFO output from FeynRules 2.3.49 can contain Python 2 `raise X, "msg"`
  statements, which Python 3 cannot import. Caught by
  `ravel.physics.ufo_interop.convert_text`, which rewrites only that form and
  records each edit; see the feynrules handbook.
- Parameter-card masses and decays must be what the shower needs; a width-only
  DECAY table leaves particles undecayed. Caught by
  `src/ravel/validation/lhe_check.py`; see C1 in `docs/reference/failure-modes.md`
  and `docs/workflow/checklists/model-cards.md`.
- Advisory: a UFO is executable Python. Import only trees you trust and pin
  them by hash, as model-events does.

More: `references/review.md`.
