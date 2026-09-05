---
name: figure-contract
description: Declare, extract, echo, and fulfil the published-figure contract in hep-agentic-pipeline — WHICH published ATLAS/CMS figure a run reproduces, its extracted image, the axes-as-facts, the generated counterpart, and the side-by-side composite. Use at step 2 (declare), step 5/8 (attach+compose), and for multi-panel figures or archetype figure selection.
when_to_use: declaring the target figure for a run; attaching/composing published-vs-produced side-by-sides; the figure is multi-panel; choosing the discriminating figure for an analysis archetype
allowed-tools: Bash, Read
---
# Skill — the figure contract (declare → extract → echo → counterpart → compose)

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.

Every reproduction claims a SPECIFIC published figure; the contract makes that claim
machine-checkable and kills the caption-imagined-figure class (catalogue A1/A2). Checklist:
`docs/workflow/checklists/figure-contract.md`; this skill is the operational order.

## 1. DECLARE (step 2, before generation)
```bash
CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda
$CONDA run -n rivet python scripts/run.py ravel.workflow.hepdata_fetch --inspire insNNNN --out <rundir>/outputs/hepdata
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target resolve \
  --analysis <ID> --hepdata-manifest <rundir>/outputs/hepdata/hepdata_manifest.json \
  --role summary --model-keywords "<model words>"     # ranked candidates; [judgment] CHOOSES
$CONDA run -n rivet python scripts/run.py ravel.plotting.fetch_figures --inspire insNNNN --figure <N> --out <rundir>/outputs/published
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target declare --rundir <rundir> \
  --role summary --primary --figure-id "Figure <N>" --source <user-prompt|registry-hint|...> \
  --caption "<first sentence of the PAPER caption>" --inspire insNNNN \
  --axes-x <linear|log> --axes-y <linear|log>
```
- FETCH the figure BEFORE declaring (the caption + axes are read OFF the extracted figure).
- **AXES ARE CONTRACT FACTS** (catalogue A2): record the published scales at declaration;
  renderers consume them via `--figure-target`; a heuristic axis needs `axes.source="assumed"`.
- `resolve` never auto-picks. The archetype recipe (`figure_manifest.py`) proposes the
  discriminating figure per archetype A–D; an ESCAPE classification = per-paper [judgment].
- No extractable image → attach the precise TEXTUAL reference (a valid degraded state, shown
  under its textual-reference banner) — never skip the declaration.

## 2. MULTI-PANEL figures (Figs 5–6 grids etc. — CR-010 interim rule)
The tooling is one-image-per-target: declare EACH panel as its own target
(`--figure-id "Figure 5a"`, "Figure 5b", …), attach + compose per panel, and present the
panel set together in the check-in. Do not stretch one target across panels.

## 3. ECHO (CHECK-IN 1) · COUNTERPART + COMPOSE (steps 5/8)
`figure_target.py show` prints the check-in block (the gallery echo). At the ACTUAL check-in,
`figure_target.py checkin --rundir <rundir>` flips `declared_at_checkin=True` on the single
primary target (or a `--figure-id` one) and re-echoes the block — the lifecycle step
(declare → attach → **checkin** → compose → fulfil-primary) the CHECK-IN waypoint gate keys on;
only a checked-in target counts as bound to the approved contract. When the counterpart
exists:
```bash
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target attach-generated \
  --rundir <rundir> --figure-id "Figure <N>" --path <the counterpart .png> --step <NN-step>
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target compose --rundir <rundir> --figure-id "Figure <N>"
```
The side-by-side composite (published | produced) is the check-in headline; for a scan the
`__fig3` single-panel output is the counterpart, not the grid diagnostic (step 8).

Once the physicist has signed off against that composite, close the lifecycle with:
```bash
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target fulfil-primary \
  --rundir <rundir> --by "<physicist>" [--utc <ts>] [--note "<one-line sign-off>"]
```
`fulfil-primary` is the ONLY write site of `verified_by_physicist` — a WRITTEN lifecycle field, not
a dead one — and it refuses unless the single primary already has a composed `side_by_side` on disk
(you verify against the side-by-side, never a bare number).

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "The caption tells me what this figure looks like" | Catalogue A1: the first difference map was INVENTED from caption text — two supervisor rejections. Extract and LOOK before declaring. |
| "Log axes are obviously right for this quantity" | Catalogue A2: axis guessing failed BOTH directions; axes are read OFF the extracted figure — `axes.source="assumed"` only when nothing is extractable. |
| "One target can stand in for the whole panel grid" | Trial gap G-CMS-04: multi-panel is not first-class; each panel is its own target (the CR-010 interim rule above). |

## Stop conditions
- No declared target by the end of step 2 → CHECK-IN 1 cannot go out (the gallery/waypoint
  sections depend on it).
- A counterpart without its extracted-or-textual published sibling never ships (A1 guard);
  `verify_pack.py` (step 9) asserts contract fulfilment — fulfil or WARN, never silently drop.

- **compose stamps provenance** (`composed_by {tool, utc}`): the run-state gate hard-FAILs a PRIMARY whose `side_by_side` is hand-populated (path not on disk, or no stamp) — only `figure_target.py compose` output satisfies the primary contract (A2, trial QI.2).
