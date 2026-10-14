---
name: pyhf-workspace-patching
description: Use when applying a signal patch to a published background-only HistFactory workspace with pyhf, choosing a patch from a released patchset by its coordinates, checking that a patch belongs to the workspace, or building signal templates for a published likelihood, in RAVEL's published-model and signal-template modes.
license: Apache-2.0
compatibility: pyhf 0.7.6 and jsonpatch 1.33 as pinned in RAVEL's Python dependencies.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "published-model signal-template"
  upstream-version: "pypi:pyhf=0.7.6 pypi:jsonpatch=1.33"
  last-reviewed: "2026-10-11"
---

# pyhf workspace patching

## How a released likelihood is built

A published likelihood is a background-only workspace plus a patchset. Each
patch is a JSON Patch (RFC 6902) that adds the signal samples for one model
point, and the patchset metadata names the coordinate labels and the SHA-256
digest of the background-only workspace it was made for. pyhf computes that
digest from the workspace as sorted JSON, and RAVEL reproduces it:

```python ravel-block=patch-with-digest
import jsonpatch
import pyhf
from ravel.physics.published_model import canonical_background_digest

def patched_model(background, patch_ops, expected_digest):
    """Apply one signal patch after checking it belongs to this background."""
    found = canonical_background_digest(background)
    if found != expected_digest:
        raise ValueError(f"patch was made for background {expected_digest}, this one is {found}")
    workspace = pyhf.Workspace(jsonpatch.apply_patch(background, patch_ops))
    model = workspace.model()
    return model, workspace.data(model)
```

## RAVEL's path

`published-model` opens the released archive by hash, checks the patchset's
background digest and coordinate labels, and selects one patch by its exact
coordinates. Omitted signal additions are marked absent, not zero.
`signal-template` builds complete signal-region and control-region templates
for a published model. Limits are set as described in
`.claude/rules/statistics.md`.

## Pitfalls

- A patch from a patchset made for another background version addresses
  samples by position and lands in the wrong place without error. Caught by
  `ravel.physics.published_model.load_published_model` (background digest).
- Requested coordinates that differ from the patchset's labels. Caught by
  `ravel.physics.published_model.load_published_model`.
- A minimiser that reports success at a point that is not the minimum. Caught
  by `ravel.physics.pyhf_exclude.profile_fit_consistency`.
- Advisory: signal added only to signal regions ignores contamination of the
  control regions; use the released channel definitions where the patch
  covers them.

More: `references/review.md`. Upstream: https://pyhf.readthedocs.io/ and
Heinrich et al., JOSS 6 (2021) 2823; JSON Patch: RFC 6902.
