---
name: madgraph-launch
description: Use when generating parton-level events with MadGraph5_aMC@NLO - preparing run, process or shower cards, writing a launch script, or checking that the run used the requested event count, seed, beams and matching. Explains RAVEL's typed model-events path, which writes complete cards and checks them before and after the run.
license: Apache-2.0
compatibility: RAVEL model-events mode with the pinned MadGraph5_aMC@NLO 2.9.27 tree from the toolchain manifest; card syntax notes apply to that version.
allowed-tools: Bash Read
metadata:
  ravel-requires-modes: "model-events"
  upstream-version: "madgraph:madgraph=2.9.27"
  ravel-parameters: "model-events.cards.run model-events.cards.process model-events.cards.pythia model-events.generation.events model-events.generation.seed model-events.generation.beam_type model-events.generation.energy_gev model-events.generation.scheme model-events.generation.run_settings model-events.shower.backend model-events.shower.merging_scale_gev"
  last-reviewed: "2026-10-11"
---

# MadGraph launch

## Use RAVEL's typed path

Generate through the `model-events` mode. Its configuration declares the
physics (`model-events.generation.events`, `model-events.generation.seed`,
`model-events.generation.beam_type`, `model-events.generation.energy_gev`,
`model-events.generation.scheme`) and pins complete card files
(`model-events.cards.run`, `model-events.cards.process`, `model-events.cards.pythia`).
Extra run-card keys you rely on go in `model-events.generation.run_settings`.

RAVEL then:

1. reads the supplied cards and refuses any that disagree with the declaration
   (`ravel.physics.model_events.check_cards`);
2. writes the build script (`import model <ufo>-full`, the process lines,
   `output <dir>`) and a launch script with switch answers only
   (`shower=`, `madspin=`, `reweight=`, `detector=OFF`, `analysis=OFF`), then
   two `0` answers. It never sends `set` lines, because the cards are already complete;
3. after the run, re-reads the cards MadGraph actually used and checks them
   again with the same function in observed mode.

So the event count, seed, beams and matching switches you declared are the ones
the run used, or the run is refused.

## When you edit a card yourself

Edit the card file by key, then let `check_cards` compare it with the
declaration. A pattern substitution on the whole line can hit a comment or
miss a row; the block below refuses a key that is absent or duplicated.

```python ravel-block=run-card-keyed-edit
import re

def set_run_card(text, values):
    """Set ``value = key`` rows of a MadGraph run card by key."""
    lines = text.splitlines()
    for key, value in values.items():
        rows = [i for i, line in enumerate(lines)
                if re.search(r"=\s*%s\b" % re.escape(key), line.split("#", 1)[0].split("!", 1)[0])]
        if len(rows) != 1:
            raise ValueError(f"run card has {len(rows)} rows for {key}")
        i = rows[0]
        lines[i] = re.sub(r"^\s*\S+(\s*=)", lambda m: f" {value}{m.group(1)}", lines[i], count=1)
    return "\n".join(lines) + "\n"
```

Then update the matching field (for example `model-events.generation.events`
for `nevents`) so the declaration and the card agree.

## Launch scripts outside model-events

A launch script answers two prompts. The first `0` (or `done`) closes the
switch menu; card edits such as `set nevents 50000` go between it and the
second `0`. The check below refuses a script whose `set` lines fall outside
that window.

```python ravel-block=launch-edit-window
def check_launch_edits(script):
    """Refuse `set` lines outside the window between the two answers that end a launch."""
    lines = [l.strip() for l in script.splitlines() if l.strip() and not l.strip().startswith("#")]
    start = next((i for i, l in enumerate(lines) if l.startswith("launch")), None)
    if start is None:
        raise ValueError("no launch command")
    done = [i for i in range(start + 1, len(lines)) if lines[i] in ("0", "done")]
    if len(done) < 2:
        raise ValueError("a launch needs two answers ending its menus")
    for i, line in enumerate(lines[start + 1:], start + 1):
        if line.startswith("set ") and not done[0] < i < done[1]:
            raise ValueError(f"line {line!r} is outside the card-edit window and is not applied to this run")
    return True
```

## Pitfalls

- A card that disagrees with the declaration (event count, seed, beam types,
  beam energies, `ickkw`, systematics switch) runs to completion with the wrong
  physics. Caught by `ravel.physics.model_events.check_cards`.
- The run uses MadGraph's own copy of each card in the process directory, not
  the file you supplied. Caught by `ravel.physics.model_events.check_cards` in
  observed mode on those copies.
- Advisory: in a hand-written launch script, `set` lines after the second `0`
  are not applied to that run, so MadGraph generates with the card defaults
  (`nevents = 10000` in the 2.9.27 run card) and exits 0. Use the
  `launch-edit-window` block; model-events avoids this by sending no `set` lines.
- A generation that reports done can leave an empty `Events/` directory or a
  partly written LHE file. Caught by `ravel.validation.validate_run_state.lhe_producer_complete`;
  see C3 in `docs/reference/failure-modes.md`.
- An MLM sample showered without matching double-counts jets. Caught by
  `ravel.physics.model_events.check_cards`, which requires the matching
  settings in the Pythia card; recipe in `docs/workflow/checklists/merging.md`.
- Advisory: `iseed` is reset by MadGraph after a run; re-set it in the card for
  every reproduction (`.claude/rules/madgraph-pythia.md`).

More: `references/launch-script.md` (prompt order and switch names) and
`references/review.md`.
