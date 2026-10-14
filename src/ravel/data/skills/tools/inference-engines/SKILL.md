---
name: inference-engines
description: Use when selecting a supplied-number inference engine, retaining a requester-prescribed statistic as the primary quantity, building an SR/CR likelihood, checking coupling morph closure, or profiling a signed differential prediction with covariance in RAVEL.
license: Apache-2.0
compatibility: RAVEL inference document schema 1 with pyhf 0.7.6, iminuit 2.32.0 and SciPy 1.14.1. Engine applicability and calibration remain part of the scientific contract.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "formula-grid coupling-morphing prescribed-statistic search-statistics differential-likelihood"
  upstream-version: "pypi:pyhf=0.7.6 pypi:iminuit=2.32.0 pypi:scipy=1.14.1"
  last-reviewed: "2026-10-11"
---

# Inference engines

## Choose the quantity and engine

Record the requested statistic before selecting an engine. An exclusion
request without a prescribed statistic gets 95% CLs. When the requester supplies
a formula, N-sigma rule, delta-chi-square threshold or another admitted statistic,
retain the wording and deliver that quantity as primary. A companion CLs result
does not replace it. Exclusion and discovery are different quantities.

| Science mode | Source operation | Contract |
|---|---|---|
| `formula-grid` | Checked expressions on declared axes | Supplied constants with citations or explicit requester assumptions |
| `coupling-morphing` | Polynomial fit with design conditioning and held-out closure | A declared basis and width treatment; every held-out comparison passes |
| `prescribed-statistic` | Closed formula or independent-bin Poisson profile | Verbatim statistic, threshold and region or signal law |
| `search-statistics` | pyhf SR/CR model and diagnostic fits | Region roles, signal in all affected regions, modifiers and MC adequacy |
| `differential-likelihood` | Gaussian measurement profile with covariance | Difference-to-reference signal and declared covariance scaling |

`ravel inference modes` lists these modes. `example --mode <mode>` prints a
synthetic document. `check --mode <mode> --input doc.json` validates and inventories
inputs. `spec` writes a schema 2 study with sources, numbered assumptions, review
policy and budget. Computation uses `ravel plan`, approval and `ravel run`.
The block below is the worker operation exercised only on a tiny synthetic
closed-form document in tests; a production study still uses that lifecycle.

```python ravel-block=evaluate-prescribed-statistic
from pathlib import Path
from ravel.physics.inference import prescribed_statistic

def evaluate_prescribed(document_path, output_dir):
    """Worker operation on a supplied document; no approval is granted by this helper."""
    path = Path(document_path).resolve()
    task = {'input': str(path)}
    prescribed_statistic.validate(task)
    return prescribed_statistic.run(task, path.parent, Path(output_dir))
```

## Preserve the statistical model

The binned profile engine has one independent nuisance per bin, with its declared
Gaussian-linear, Poisson-gamma, lognormal or fixed-background law. Use a native
likelihood when its correlations or functions cannot be represented by that
contract. Shared nuisance names and the correlation declaration in the search
systematics registry determine the pyhf model. Validation regions stay outside
the fit; blinded observations stay null until admitted.

A differential signal is a signed difference from the stated reference, not a
second copy of the full prediction. Preserve all covariance components and their
fixed, ratio or square-root-ratio scaling. A nonpositive-definite or ill-conditioned
covariance makes that point unavailable. The engine does not repair it. Width
variation can make coupling dependence nonpolynomial; the morph's held-out
closure is required before its coefficients become usable.

## Read the result before delivery

Every engine writes `inference.json`: statistic definition and origin, quantity
and role, grid, input hashes, diagnostics, assumptions, limitations and
`physics_validated: false`. A closed-form one-axis prescribed rule writes a
primary `contour` with interval data; a binned profile writes delta-NLL quantities.
Do not infer the quantity from the filename alone.

An interval edge is resolved, a declared domain boundary, or beyond the scan.
An unresolved edge requires a wider approved study. Keep nonfinite points and
failed fits. `regression_triggers.evaluate` derives computed alarms from the
record. Scientific review recomputes them from retained outputs; failures block
scientific claims. A good numerical fit does not calibrate coverage or prove
model applicability. Toy budgets, seeds and auxiliary generation laws are inputs.

See `docs/reference/inference-engines.md`, the pyhf-workspace-patching handbook,
and roofit-histfactory for preserved native models.

## Pitfalls

- An uncited constant is presented as a sourced physics input. Caught by
  `ravel.physics.inference.formula.Program`.
- The requester statistic is omitted or demoted to a companion quantity. Caught
  by `ravel.physics.inference.prescribed_statistic.load` for wording and by
  `ravel.physics.inference.record.validate` for primary-result presence.
- A morph with missing held-out runs, poor conditioning or failed closure is
  used as a prediction. Caught by `ravel.physics.inference.morphing.fit`; consumers
  also require a usable morph.
- A full reference is included again in the signed difference, or the covariance
  is invalid. Caught by `ravel.physics.inference.differential.Model` for declared
  convention and point-level covariance checks; a false declaration needs review.
- A crossing beyond the evaluated grid is quoted as a resolved bound. Caught by
  `ravel.physics.inference.intervals.allowed_regions` and
  `ravel.validation.regression_triggers.evaluate`.
- Advisory: an asymptotic threshold or a numerically successful fit need not have
  the requested coverage for sparse, bounded or signed data. Candidate check
  IN-A1 in `references/checks.md` requires a calibrated repeated-data study.

## Wrong versus right

| Wrong | Right | RAVEL check |
|---|---|---|
| Mark an arbitrary constant cited | Supply its citation or explicit requester statement | `inference.formula.Program` |
| Replace the prescribed rule with default CLs | Preserve wording and primary role | `inference.record.validate` |
| Fit a polynomial and skip holdouts | Require conditioning and independent closure | `inference.morphing.fit` |
| Add reference to a full prediction again | Supply a declared difference-to-reference | `inference.differential.Model` |
| Report the last scan point as a limit | Retain the unresolved edge and extend the scan | `inference.intervals.allowed_regions` |

More: `references/checks.md` and `references/review.md`. Upstream references:
pyhf 0.7.6 documentation (models, modifiers and inference); iminuit 2.32.0
documentation (fit validity); Cowan et al., arXiv:1007.1727 (2011), asymptotic
likelihood tests; SciPy 1.14.1 reference for numerical solvers.
