---
name: pythia-shower-cards
description: Use when writing or checking a Pythia 8 settings card for showering LHE events - event count, HepMC output, MLM or CKKW-L merging settings, SLHA decay tables - or when comparing the card a run used with the one that was planned, in RAVEL's model-events and retained-shower modes.
license: Apache-2.0
compatibility: Pythia 8.312 from RAVEL's rivet-shower toolchain group; card syntax per the Pythia 8.3 online manual.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "model-events retained-shower"
  upstream-version: "rivet-shower:pythia8=8.312"
  ravel-parameters: "model-events.cards.pythia model-events.shower.backend model-events.shower.settings model-events.shower.merging_scale_gev model-events.shower.max_jets model-events.shower.minimum_returned_events"
  last-reviewed: "2026-10-11"
---

# Pythia shower cards

## How RAVEL reads a card

`ravel.physics.pythia_cards.parse` reads every `Key = value` line literally.
A key that appears twice is refused rather than letting the last value win,
and ordered decay-table commands (`oneChannel`, `addChannel`) are kept in
order. `ravel.physics.pythia_cards.compare` compares a planned card with the
one a run used and lists every setting that differs:

```python ravel-block=pythia-card-compare
from ravel.physics import pythia_cards

def card_differences(planned_text, used_text):
    """Settings that differ between a planned and a used Pythia card."""
    report = pythia_cards.compare(planned_text, used_text)
    return report["mismatches"] if not report["matched"] else []
```

In model-events the shower is declared by `model-events.shower.backend`,
`model-events.shower.settings`, `model-events.shower.merging_scale_gev`,
`model-events.shower.max_jets` and `model-events.shower.minimum_returned_events`,
and the card is pinned as `model-events.cards.pythia`.

## Settings that must agree with the generation

- `Main:numberOfEvents` equals the generated event count.
- `HEPMCoutput:file = auto` in the planned card; the run names the file.
- MLM: `JetMatching:merge = on`, `JetMatching:scheme = 1`,
  `JetMatching:qCut` equal to the declared merging scale and
  `JetMatching:nJetMax` equal to the highest jet multiplicity.
- CKKW-L: `Merging:TMS`, `Merging:Process` and `Merging:nJetMax` as declared.
- An unmerged sample has neither `JetMatching:merge = on` nor a positive
  `Merging:TMS`.

The MLM recipe and its validation are in `docs/workflow/checklists/merging.md`.

## Pitfalls

- Any of the settings above disagreeing with the generation. Caught by
  `ravel.physics.model_events.check_cards`.
- A setting given twice, where Pythia would use the last value. Caught by
  `ravel.physics.pythia_cards.parse`.
- The card the shower used differs from the planned card. Caught by
  `ravel.physics.pythia_cards.compare`.
- A DECAY table with a total width and no branching-ratio rows: Pythia imports
  no channels, the new particles stay undecayed, and the signal regions come
  out empty with exit 0. Caught by `src/ravel/validation/lhe_check.py` before
  the shower; see C1 in `docs/reference/failure-modes.md`.
- Advisory: with `JetMatching:setMad = on`, Pythia reads matching parameters
  from the LHE header; RAVEL's records show a header it could not read, which
  left `qCut` at its default and vetoed every event. Set the matching values
  explicitly with `setMad = off` (`.claude/rules/madgraph-pythia.md`).
- Advisory: showering a merged sample needs a shower program with the matching
  hook (`pythia_shower_merged` in RAVEL's native build); the plain shower has
  none.

More: `references/review.md`. Upstream manual: https://pythia.org/latest-manual/
(pages "Jet Matching", "CKKW-L Merging", "SUSY Les Houches Accord").
