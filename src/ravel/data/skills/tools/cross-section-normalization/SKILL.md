---
name: cross-section-normalization
description: Use when looking up a sourced production cross section under a declared order, PDF and scale convention, checking charge and state multiplicities, deriving branching and filter factors, or reconciling generated signed weights with delivered yields in RAVEL.
license: Apache-2.0
compatibility: RAVEL cross-section registry and normalization ledger schema 1. NumPy 1.26.4 and SciPy 1.14.1 are the pinned numerical stack; the physics tables have separate source hashes.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "cross-section simplified-spectrum group-normalization"
  upstream-version: "pypi:numpy=1.26.4 pypi:scipy=1.14.1"
  last-reviewed: "2026-10-11"
---

# Cross sections and normalization

## RAVEL's path

Read the process and sample convention before any lookup. `cross-section` is a
science mode; `normalization` and `normalization-ledger` are focused commands,
not science modes. `group-normalization` is the grouped-quantity route.

`ravel xsec lookup --request request.json` reads the packaged registry in
`src/ravel/data/cross_sections/`. The request supplies production basis, energy,
masses, order, PDF and scale prescription, with charge and state multiplicity
where needed. `as-published` accepts the table convention explicitly. A missing
convention is a declared gap; it does not select another order.
The requested order must match what the analysis states.
A charge-summed basis must be requested explicitly with `charge: "sum"`.
Declare different partner content in `spectrum: {decoupling, state_count}`;
`spectrum.state_count` must agree with request `state_count`. A nonempty
`spectrum_assumption` states any approximation to the table's own spectrum;
the returned record preserves both descriptions. A recorded state-rescaling rule
permits its documented correction, while an unsupported declared approximation
retains the table value without inventing a state factor.
`ravel xsec verify` checks retained table hashes. Fetching a table requires
network access and is outside this handbook's executable examples.

Interior nodes use log sigma against log mass. Empty nodes, missing grid
rectangles and extrapolation are refused. This block demonstrates the same
arithmetic on a supplied table; it does not select or authenticate that table:

```python ravel-block=interpolate-supplied-table
from ravel.physics import cross_sections

def interpolate_supplied_table(entry, data, masses):
    """Interpolate only inside a supplied positive grid and return its uncertainty."""
    return cross_sections.interpolate(entry, data, masses)
```

A generator cross section is a separate source, with its actual order, PDF,
scales, charge and state count. `cross_sections.k_factor` compares compatible
records. Never attach a flat correction to an unavailable table convention.
`simplified-spectrum` writes a declared SLHA2 spectrum and checks decay closure;
its masses and branching fractions do not constitute a cross-section calculation.

## The normalization ledger

For an ordinary cross-section-normalized sample the delivered bin yield is
sigma[pb] times luminosity[pb^-1] times k, branching fractions and filter
efficiency, times selected sumw divided by generated sumw. One fb^-1 is
1000 pb^-1. Keep generated and selected sumw2 for uncertainty. The denominator
is the processed signed sum, not the requested event count or absolute weights.
The ordinary ledger refuses a nonpositive generated sum. Absolute signed
amplitude streams use the attempted-draw estimator instead.

`ravel normalization factors --settings settings.json --out factors.json` reads
the actual decay and filter settings. A forced decay or filter must not be
applied again if already included in the cross section.

`ravel normalization-ledger check --ledger ledger.json --delivered yields.json`
recomputes yields, reports typed causes and never rescales them. Use `engine`
to prepare the columnar normalization block; `check_engine_scale` then compares
the applied scale with the same ledger. The ledger binds factor conventions,
sources, bin representation and generated moments. A registry table ID or sha256
in `sigma.source` binds its own order, full PDF label and production basis. The
builder retains every constituent hash for charge sums. Ambiguous IDs require a
hash; unknown table PDFs remain `as-published`. Free-text sources are accepted
with a `source_unpinned` review warning.

Optional `sigma_alternates: [{order, pdf, value_pb, source}]` entries retain other
conventions beside the primary. The check reports recomputed alternate bins,
integrated totals and ratios, with all other ledger factors held fixed. Listed
regions are summed without deduplicating overlap. Carry the ledger and check
report into delivery; the alternate never changes primary delivered numbers:


```python ravel-block=audit-normalization
from ravel.physics import normalization_ledger

def audit_normalization(ledger, delivered):
    """Return the audit; a false passed flag blocks using these delivered yields."""
    return normalization_ledger.check(ledger, delivered=delivered)
```

Per-unit-width bins divide each integrated yield by its own bin width.
Branching and filter provenance and the production receipt accompany the
`binned_values` result, cutflow and downstream statistical model. Preserve
warnings about negative weights and a normalization order different from the
target; they are review obligations, not automatic rescaling instructions.
See `docs/reference/models-and-normalization.md`.

## Pitfalls

- A lookup substitutes another order, PDF, scale or charge convention for the
  requested one. Caught by `ravel.physics.cross_sections.lookup`.
- A mass outside a table or a hole is filled by extrapolation. Caught by
  `ravel.physics.cross_sections.interpolate`.
- A correction factor relates different production bases, states, energy or masses.
  Caught by `ravel.physics.cross_sections.k_factor`; ledger basis disagreement is
  also caught by `ravel.physics.normalization_ledger.check`.
- A pb/fb swap, duplicated k, branching fraction or filter changes all bins by a
  common factor. Caught by `ravel.physics.normalization_ledger.check` when
  delivered bins are supplied; undeclared sources are refused by
  `ravel.physics.normalization_ledger.validate`.
- The requested event count replaces signed sumw, or integrated bins are treated
  as densities. Caught by `ravel.physics.normalization_ledger.check` for a declared
  denominator or mismatching delivered values. The declarations themselves need review.
- Advisory: a sourced inclusive normalization does not prove its applicability
  to a differently selected final state or a signal-interference difference.
  Candidate check XS-A1 in `references/checks.md` binds both estimator and basis.

## Wrong versus right

| Wrong | Right | RAVEL check |
|---|---|---|
| Choose the nearest available order | Require the requested convention or report the gap | `cross_sections.lookup` |
| Extend the last two nodes beyond the table | Stay inside positive bracketing nodes | `cross_sections.interpolate` |
| Divide incompatible cross sections for k | Match basis, energy, masses and state convention | `cross_sections.k_factor` |
| Apply k to an already corrected sigma | Record numerator/denominator order and apply once | `normalization_ledger.check` |
| Normalize by requested N or forget bin widths | Use processed signed sumw and declare the bin convention | `normalization_ledger.check` |

More: `references/checks.md` and `references/review.md`. Upstream references:
LHC SUSY Cross Section Working Group table documentation (edition and version
come from each registry entry); SUSY Les Houches Accord 2, arXiv:0801.0045 (2008);
NumPy 1.26 and SciPy 1.14.1 reference manuals for numerical operations.
