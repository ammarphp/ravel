---
name: delphes-cards
description: Use when choosing, editing or auditing a Delphes detector card - which particles reach the calorimeters, how missing transverse momentum is built, which new stable particles a stock card treats as visible (for example a gravitino or sneutrino) - before running Delphes on showered events for RAVEL's analyze or ma5-pad modes.
license: Apache-2.0
compatibility: Delphes 3.5.1 from RAVEL's recast-base toolchain group; TCL card syntax of that version.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "analyze ma5-pad"
  upstream-version: "recast-base:delphes=3.5.1"
  last-reviewed: "2026-10-11"
---

# Delphes cards

## How a card decides what is invisible

Calorimeter modules give each stable particle an energy fraction per
calorimeter with `add EnergyFraction {abs(PDG)} {fractions}`. A particle with
no row of its own takes the `{0}` default row. In the Delphes 3.5.1 stock CMS
and ATLAS cards the ECAL default is 0 and the HCAL default is 1, and the
zero-fraction rows list the neutrinos (12, 14, 16), the muon (13) and the
neutralinos (1000022, 1000023, 1000025, 1000035, 1000045). The reconstructed
`MissingET` module is built from the merged particle-flow objects, so it
balances only what the detector saw. The generator-level `GenMissingET` uses a
`PdgCodeFilter` that lists the neutrinos only.

So a stable gravitino (1000039) or sneutrino (1000012) deposits all its
energy in the HCAL of those stock cards: it becomes jets, not missing energy.
Run the census for every stable invisible state of the model:

```python ravel-block=invisible-census
from ravel.physics import delphes_cards

def escaping_states_report(card_text, pdg_codes):
    """Which declared invisible states the card would make visible."""
    census = delphes_cards.invisible_census(card_text, pdg_codes)
    return {code: {"visible": not row["invisible_to_calorimeters"],
                   "calorimeter_fractions": row["calorimeters"],
                   "in_generator_met": row["in_generator_met_filter"]}
            for code, row in census.items()}
```

To make a state invisible, add a zero row to every calorimeter module (for
example `add EnergyFraction {1000039} {0.0}` in ECAL and `{0.0}` in HCAL) and,
when generator-level MET is used, add its code to the neutrino filter. Record
the edited card as a deviation from the stock card.

## Pitfalls

- A new stable invisible particle missing from the calorimeter rows becomes
  visible energy and is removed from MET. Caught by
  `ravel.physics.delphes_cards.invisible_census` (run it on the card you use).
- A Delphes output without its `Delphes` tree or with an event lacking its
  single weight record (for example a file cut short by a killed job). Caught by
  `ravel.physics.delphes2sa_native.read_weights`; see C6 in
  `docs/reference/failure-modes.md`.
- Advisory: object efficiencies and resolutions in a stock card are generic
  parametrisations; compare them with the analysis's published efficiencies
  before trusting acceptance (`docs/workflow/checklists/detector-fidelity.md`).
- Advisory: pile-up cards need a pile-up file and change isolation and MET;
  use the card the reference analysis or tool tune names.

More: `references/review.md`. Upstream: https://delphes.github.io/ and the
cards in the Delphes 3.5.1 source tree.
