# Checklist — CHECK-INS (the physicist-facing layer)  ·  [judgment] composes every check-in
# (escalation IS a check-in: a weak model composes the flag and waits; it never skips one)

Check-ins are the ONLY interface the physicist sees; everything else is machinery. A colleague — not
an operator — is on the other end: they must be able to catch a wrong plan before compute is spent,
a wrong pipeline before the scan, and a wrong number before it is believed. Every check-in is
written for a reader with limited time and attention (optimize for a reader with ADHD): skimmable
headers, short numbered lists, nothing important buried mid-paragraph.

Four standardized check-ins plus one immediate class. The physicist session entrypoint
(`docs/workflow/start.md`, at the workflow root) promises exactly this sequence.

| check-in | when | the ask |
|---|---|---|
| **1 — PLAN** | after step 2, before ANY heavy compute | approve / redirect the plan |
| **2 — EARLY VERIFICATION** | at the declared waypoint, before the bulk of compute | go / adjust |
| **DEVIATION** (a class, not a slot) | the moment a mid-run judgment changes course | informed (run continues) |
| **FINAL — RESULTS DECK** | after step 7/8, gated by the step-9 panel | accept / revisit |

## Two rules that govern EVERY check-in

**THE CAPTION RULE.** Every figure displayed to the physicist — at any check-in, at any point in the
run — carries a physics-judgment caption optimized for clarity and readability: name the visual
elements (which curve/band/point is which), the axes, what to look at, and what it means. A filename
is not a caption; neither is the paper's caption verbatim when it assumes context the reader does
not have yet.

**THE "WHY" RULE** (the fix for "we don't understand what it's doing or why"). Every decision is
narrated as **question → options considered → choice → reason**, in physics terms. Internal tool and
term names never appear bare — each gets a one-clause gloss on first use ("Pythia8, the parton-shower
simulator"; "pyhf, the statistical-fit tool"). If a sentence only makes sense to someone who has
read this repository, rewrite it.

## CHECK-IN 1 — "PLAN"  (after step 2 · before ANY heavy compute)

The detailed, granular one — the physicist's single best chance to redirect the run cheaply.
Sections in this order, each under its own header:

### (i) Plain-language preamble
2–4 sentences: what you understood the physicist wants, what you are about to do, and why — zero
internal jargon (any tool/term gets its one-clause gloss). This is the "did you understand me?" test.

### (i-b) Resource census — "what exists online for this analysis"
The `--markdown` block from `resource_census.py` (step 2.0): HEPData tables + likelihood/
efficiency-map resources, routine hits, GitHub repos found (with one line on what each is),
forward-citation theses/recasts, and which manual rungs stay open. What a rung FOUND that changes
the plan (a full likelihood, an efficiency map, a recast repo with cards) gets a numbered flag;
what is genuinely absent is stated as the cap it imposes.

### (ii) Published-figure GALLERY
`fetch_figures.py --map-captions` extracts ALL the reference paper's figures + captions into
`figure_map.json` — use it. DISPLAY several candidate figures spanning distinct categories (e.g. an
exclusion-contour summary, a kinematic-distribution overlay, a cutflow/yield comparison), each with
a one-line caption per the caption rule. The physicist picks or confirms the target from pictures,
not from HEPData table names.

### (iii) Figure target(s) + the EARLY-VERIFICATION WAYPOINT
- The declared figure contract: which published figure(s) this run reproduces (`figure_target.py
  show`; `docs/workflow/checklists/figure-contract.md`), with the published axis scales recorded at declaration
  (the `axes` fields of `figure_target.json` — facts read off the extracted figure, not defaults).
- **The WAYPOINT ([judgment] — deliberately a physics-judgment selection, not a procedure):** pick ONE
  PARTIAL element of a published figure that the pipeline can reproduce EARLY, at cheap statistics,
  before the heavy compute. The classic pattern: the simulation-only background component drawn in a
  published spectrum (the "grey QCD-MC line" pattern) — reproducible from a fast background-only
  sample. PROPOSE it here: "at CHECK-IN 2 you will see this element side-by-side with the published
  one, so we both know the pipeline is not catastrophically wrong before the expensive part." There
  is no formula for the choice — it is judged by what is (a) reachable early and (b) diagnostic.

### (iv) PLAN
The concrete plan, skimmable: samples to generate (process, parameters, event counts), observables /
signal regions, the intended statistical treatment (published likelihood vs counting), and the
compute budget — what runs, roughly how long, and what is deferred until after CHECK-IN 2;
the numbers come from `src/ravel/workflow/cost_preflight.py` (events × points ×
walltime × disk, the dry→smoke→full→scan ladder), never from prose recall.

### (v) NUMBERED FLAGGED ASSUMPTIONS + DECISIONS
Every assumption and judgment call, numbered `F1, F2, …`, each with WHY it was made and the
alternatives considered (one line each). Nothing buried: if it could change the result and the
physicist might disagree, it is a numbered flag, not a footnote.

### (vi) "HOW TO RESPOND" footer
Name the THREE response modes as equals — never present flag-answering as the only channel:
1. **Answer the flags** (any subset; unanswered flags proceed as proposed — say so);
2. **Ask clarifying questions** — anything unclear is a defect of this check-in, not of the reader;
3. **Propose alterations beyond the flags** — a different figure, model point, or scope; the plan is
   a proposal, not a fait accompli.

## CHECK-IN 2 — "EARLY VERIFICATION"  (at the waypoint · before the bulk of compute)

Short. The waypoint side-by-side: **published element | produced element** (compose it with the
`docs/workflow/checklists/figure-contract.md` mechanics), captioned per the caption rule — and say explicitly what
should already match and what is expected to differ at this statistics/level. Then the ask:
- **GO** — the element matches at the expected level; heavy compute starts.
- **ADJUST** — state what looks wrong, what you will change, and what the change costs.
A mismatch caught here is a cheap catch — that is the waypoint's whole purpose. Never proceed to
heavy compute past a mismatch without an explicit go.

## DEVIATION CHECK-INS  (immediate · own message · never batched)

Whenever a mid-run judgment CHANGES COURSE from the approved plan — physics level (a cut, a
tolerance, a sample, a normalization) or analysis level (a different table, statistical mode, or
grid scope) — emit a deviation check-in AT THAT MOMENT, as its own message: not folded into the next
scheduled check-in, never batched to the end of the run. It carries:
- what changed, from what, to what — narrated per the "why" rule (question → options → choice →
  reason);
- the alternatives considered and why they lost (one line each);
- the impact: which downstream numbers/figures it touches, and whether anything already shown to the
  physicist is now stale.
**ALSO append the same entry to the run's `DEVIATIONS.md` ledger** — what changed, from what, to
what, why, what it touches — at the moment the change is made. The ledger is the number-integrity
deliverable the verification panel audits (`docs/workflow/checklists/verification-panel.md`, `docs/workflow/steps/09-verify.md`);
an unlogged change discovered later is itself a FAIL-severity finding. The check-in informs the
human; the ledger entry is the auditable record. Both, always.

**Editing a CHECK-IN-1-baselined input is itself a course change.** The inputs frozen at CHECK-IN 1
— `task_contract.json`, `resource_census.json`, `trap_sweep.json`, `figure_target.json`,
`basis_manifest.json`, `validations.json` — are the approved plan; any post-CHECK-IN-1 edit to one of
them needs a `DEVIATIONS.md` row that NAMES the changed file. `validate_run_state.py`'s
`DEVIATIONS-on-change` invariant enforces this: once `run_state.json` records a CHECK-IN 1 and an edit
to one of those files, a `DEVIATIONS.md` that does not name it is a FAIL (D15/G17).
A `PostToolUse` hook (`.claude/hooks/deviations-guard.sh`) enforces the SAME rule at the moment of the
edit — it BLOCKS the turn (exit 2) when you edit a baselined `inputs/` file whose `DEVIATIONS.md` does
not name it, so you cannot silently continue. If a turn is blocked, add the `DEVIATIONS.md` row first,
then re-do the edit. To check by hand: after editing any baselined input, run
`python3 scripts/run.py ravel.validation.validate_run_state --edit-guard <path>` — a nonzero exit means
add the `DEVIATIONS.md` row naming that file before proceeding.

## FINAL CHECK-IN — "RESULTS DECK"  (after step 7/8 · only after the step-9 panel)

Slide-deck-like, concise, standardized — the detail lives in CHECK-IN 1 and the run's `RESULT.md`,
not here. Sections in order:
1. **Title line** — analysis, model, deliverable, verdict, in one sentence.
2. **Headline figure(s)** — displayed, EACH with a physics-judgment caption (caption rule: elements,
   axes, what to look at, what it means). For a reproduction the published-vs-produced side-by-side
   is the headline.
3. **Key-numbers table** — every number with its unit AND its artifact-file provenance (the
   `result.json` / `scan.json` / `exclusion.json` field it comes from), per the number-integrity
   rule (`docs/workflow/checklists/verification-panel.md`).
4. **Validation verdict** — the certification/anchor outcome: one line + a pointer.
5. **Limitations** — the honest bounds, from `limitations[]`, in plain language.
6. **Deviations summary** — count + one line each, pointing at `DEVIATIONS.md`.
7. **Verification-panel verdict** — appended VERBATIM (verdict + itemized findings with dispositions
   + the `verify_pack.py` report), per `docs/workflow/steps/09-verify.md`. Never silently fixed.
8. **Next steps** — what a follow-up session could do (finer grid, another model, another analysis).

## Composing rules (all check-ins)
- Analysis-agnostic machinery, analysis-specific content: this template never changes; every physics
  choice inside it is a declared [judgment] input of the current run.
- Numbers shown at any check-in obey the number-integrity rule: read from the machine artifacts,
  never re-typed from memory or prose.
- Gates vs notices: CHECK-INs 1 and 2 are GATES (heavy compute waits for the response); deviation
  check-ins are immediate notices (the run continues); the results deck is blocked only by a FAIL
  panel verdict (`docs/workflow/steps/09-verify.md`).
- Step-boundary self-check (the fallback gate): each check-in sits at a step boundary. When the
  PostToolUse hook that normally enforces a precondition is unavailable, the agent may self-verify
  one before composing the check-in with `src/ravel/workflow/workflow_state.py require
  --rundir <dir> --kind skill --what <skill>` (also `--kind stage --what <stage>`, `--kind artifact
  --what <relpath>`, `--kind command --what <cmd>`) — exit 0 iff satisfied, exit 1 iff not. This is
  the belt-and-suspenders backstop for the skill-coverage (G2) and lifecycle-ordering (G3) gates,
  never a substitute for the hook.
- Observer fallback (the L1 twin): `run_state.json` is normally kept current by the PostToolUse
  observer (`.claude/hooks/posttooluse-observer.sh`), which records every `Skill` / `Edit|Write|
  MultiEdit|NotebookEdit` / `Agent|Task` call. When that hook is unavailable, run the SAME command
  the observer would have — after invoking a skill, spawning a subagent, or editing a baselined
  input, run `python3 scripts/run.py ravel.workflow.workflow_state record --rundir <rundir> --kind
  skill|subagent|edit --payload '<json>'` (e.g. `--kind skill --payload '{"skill":
  "physicist-intake"}'`) so the ledger stays the ground truth either way. **Compute is the one
  exception (D-2):** a `compute_launched` entry is ALWAYS written by the DRIVE step-doc's explicit
  `record --kind compute …` (which supplies the N6 `bg_kind`/`logfile`/`done_condition`/`next_action`
  liveness fields) — never by the observer or this fallback, because only DRIVE knows those fields.
- **Emit + validate (the machine gate, G18):** every check-in is emitted as a machine artifact —
  CHECK-IN 1 to `inputs/checkin1.json`, CHECK-IN 2 to `inputs/checkin2.json`, the results deck to
  `inputs/checkin_deck.json` — and validated BEFORE it is sent: run
  `python3 scripts/run.py ravel.validation.validate_checkin inputs/checkin1.json` (likewise for the
  CHECK-IN 2 and deck artifacts). The validator asserts the required SECTIONS are present — CHECK-IN 1's
  seven lettered sections (i, i-b, ii, iii, iv, v, vi) with the `F<n>`-numbered flags in (v) and the
  three response modes in (vi); CHECK-IN 2's GO/ADJUST ask; the deck's eight sections including the
  verbatim step-9 verification-panel verdict — and **a missing required section is a FAIL, not a
  warning**. Same public `validate(obj) -> list[str]` contract as `validate_task_contract.py`; run it
  by hand at each check-in when the emitting composer is unavailable.

> **Mechanized (A6):** `validate_checkin.py` on `<rundir>/inputs/checkin*.json` verifies every gallery-cited image EXISTS on disk and rejects `file://` links — attach/render figures, never bare file paths (the trial's un-viewable-deck failure, QM.1).

> **Mechanized (R3/H1):** the go-ahead is an ARTIFACT — `workflow_state.py approve --rundir <rd> --quote '<the physicist reply>'` (refuses without a VALID `checkin1.json` + a `cost_preflight.json`). The pre-exec Bash guard refuses smoke/full/scan generation without it, refuses `nohup`/detached or unsupervised launches, and refuses generation with no recorded recipe — BEFORE the process starts.
