---
name: columnar-analysis
description: Use when compiling an ordered reconstructed-event recipe, reading Delphes or a declared ntuple schema, splitting one event sample into partitions, merging weighted histograms, or inspecting authored analysis and ntuple preparation in RAVEL.
license: Apache-2.0
compatibility: RAVEL columnar schema 1 with uproot 5.3.12, Awkward Array 2.6.7 and NumPy 1.26.4. Native routine and site execution need their own pinned runtime.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "columnar-analysis authored-analysis reco-ntuple-routine ntuple-inventory mc-expected-construction root-stream"
  upstream-version: "pypi:uproot=5.3.12 pypi:awkward=2.6.7 pypi:numpy=1.26.4"
  last-reviewed: "2026-10-11"
---

# Columnar analysis

## RAVEL's path

Start with the supplied event files, production receipt and selection definition.
Use `ravel columnar-analysis` for inspection and partition preparation. A complete
study uses mode `columnar-analysis` through `ravel plan`, CHECK-IN 1 approval and
`ravel run`. The focused command also exposes `analyse`, `merge` and `finalize`;
these are analysis steps, not substitutes for study approval.

`columnar.formats` maps source branches, units and event weights into named
fields. Its built-in `delphes` descriptor describes the standard Delphes tree.
Other layouts require a supplied descriptor. A fixed mass or a unit conversion
needs its declared source. LHE particles are parton-level inputs; their selection
alone does not establish reconstructed detector response.

`columnar.recipe` compiles ordered object steps, observables, named region cuts,
histograms, efficiency maps and systematic variations. Definitions precede their
uses. Each systematic is a complete pass, so migrated objects and bins are kept.
Undefined observables fail cuts and have a separate histogram census.

```python ravel-block=compile-columnar-recipe
from ravel.physics.columnar import formats, recipe

def compile_checked(document, descriptor, base):
    """Compile a supplied recipe; inspect input files separately before approval."""
    schema = formats.load_descriptor(descriptor, base)
    return recipe.compile_recipe(document, schema, base)
```

`columnar.engine.analyse` produces additive moments. Split a sample by disjoint
file entry ranges, retain its file indices, then merge before normalization:

```python ravel-block=merge-columnar-partitions
from ravel.physics.columnar import engine

def merge_checked(partials):
    """Merge only compatible plans with disjoint input ranges."""
    return engine.merge(partials)
```

`finalize` writes `histograms/<name>.json` as `binned_values`, `cutflow.json`
and `analysis-result.json` under `columnar-analysis/`. Keep sumw, sumw2, raw counts,
flow and undefined counts, units, recipe identity and input hashes. Histograms
feed `ravel fill-template`; cutflow and production provenance travel with them.

## Choose the actual route

`authored-analysis` uses a reviewed Python source capsule when the recipe cannot
represent the requested operation. It needs its own source and output witnesses.
`reco-ntuple-routine` runs a native analysis with an explicit reconstructed
format descriptor. `ntuple-inventory` prepares a nominal selection and can emit a
`root-stream` specification. `mc-expected-construction` transports a completed
stream's full SR/CR basis into statistical construction. These preparation and native paths have
separate admission and result scopes; recipe compilation does not qualify them.

See `docs/reference/columnar-analysis.md`, `columnar-analysis-modes.md`
and the cross-section-normalization handbook.

## Pitfalls

- A typo in a weight, object, observable or histogram field changes the selection.
  Caught by `ravel.physics.columnar.recipe.compile_recipe` before events are read.
- A branch exists in the first file but is missing in another member of the sample.
  Caught by `ravel.physics.columnar_analysis.inputs`, which inspects each member.
- Overlapping entry ranges or a different recipe are merged as one sample.
  Caught by `ravel.physics.columnar.engine.merge`.
- Negating a cut on an undefined observable accepts an event with no value.
  Caught by `ravel.physics.columnar.expressions.compile_expression`; its
  compiled cut evaluation masks undefined inputs even under negation.
- A cross-section ledger and a separate normalization factor both apply the same
  branching or filter correction. Caught by
  `ravel.physics.columnar.engine.resolve_normalization` when the ledger path is used.
- Advisory: branch compatibility and recipe arithmetic do not establish detector
  response or agreement with a source selection. Candidate check CA-A1 in
  `references/checks.md` compares independent event decisions and source cutflows.

## Wrong versus right

| Wrong | Right | RAVEL check |
|---|---|---|
| Reference an undeclared weight | Declare the descriptor field before compilation | `columnar.recipe.compile_recipe` |
| Check only one ROOT member | Inspect every member's required branches | `columnar_analysis.inputs` |
| Repeat the first partition | Keep disjoint ranges and stable file indices | `columnar.engine.merge` |
| Treat missing as false before negation | Keep undefined values masked | `columnar.expressions.compile_expression` |
| Add a second factor beside a ledger | Take the ledger's split sigma and BR/filter exactly once | `columnar.engine.resolve_normalization` |

More: `references/checks.md` and `references/review.md`. Upstream references:
Uproot 5.3.12 documentation (TTree reading); Awkward Array 2.6.7 documentation
(jagged arrays and broadcasting); NumPy 1.26 reference (array operations).
