# Step 9 — Adversarial verification panel  ·  [agent] mechanics / [judgment] adversary  ·  MANDATORY · CHECK-IN
`CONDA=stages/01-event-generation/build/tools/miniforge3/bin/conda` — every `$CONDA` below.

No result reaches the physicist without passing through this step. Steps 7/8 end with a RESULT-PACK
(`result.json` + `figures.json`) or a scan pack (`scan.json`) and a drafted final check-in / `RESULT.md`.
Before that check-in is **sent**, the panel attacks it. The panel exists to catch **our own** mistakes —
transcription errors, silent protocol drift, unjustified physics judgments — not to defend the result.
Its full checklist form is `checklists/verification-panel.md`; read it alongside this step.

## Two tiers, two classes of agent (tiered model usage — deliberate)
| tier | who | what it verifies |
|---|---|---|
| **A — MECHANICAL INTEGRITY** | [agent] — cheap models (Haiku/Sonnet-class) are sufficient; the checks are look-ups, not judgment | every number quoted traces to a machine artifact; units; figures exist + captioned; coverage claims; deviations ledger |
| **B — PHYSICS ADVERSARY** | [judgment] — a strong model (Opus/Fable-class), and a **fresh context**, not the agent that produced the run | independently attack the physics judgments and try to REFUTE the headline claims from the artifacts alone |

## Tier A — mechanical integrity ([agent], cheap)
The single sources of truth are the machine artifacts: `scan.json` / `result.json` /
`sensitivity.json` / `figures.json`. Prose (`RESULT.md`, the check-in text) is *generated from* them,
never the other way around. Tier A asserts:
- **Number tracing** — every number quoted in the final check-in and `RESULT.md` (limits, yields,
  k-factors, coverage, masses) appears in — or is arithmetically derived, with the derivation shown,
  from — one of those artifacts. **A quoted number with no artifact source, or disagreeing with its
  artifact, is an automatic FAIL** (the number-integrity rule, `checklists/verification-panel.md`).
- **Units** — every quoted quantity carries its unit, and the unit matches the artifact's convention
  (fb vs pb is the classic slip; GeV on masses; fb⁻¹ on lumi).
- **Figures** — every figure file cited exists on disk; every *displayed* figure has a caption
  (`what_it_shows` in `figures.json`); declared figure-contract targets are fulfilled or WARNed.
- **Coverage** — any "N of M points" / "full grid" claim matches `n_done`/`n_planned`/`missing_tags`
  in `scan.json`; a partial grid must be stated as partial.
- **Deviations ledger** — the run's `DEVIATIONS.md` exists and **every mid-run adjustment of protocol,
  tolerance, selection, or instruction appears in it** (its check-in is defined in
  `checklists/check-ins.md`). Renorm/rebase-style provenance blocks in the artifacts (e.g. a post-hoc
  re-normalization) each need a matching ledger entry.
- **Recipe-search close-block (G8 / D8 RESOLVE)** — if `run_state.open_failure_records` still names a
  generator-model failure (its record's `stage` is a generation stage, or
  `failure_class == "tool_generator_model"`), then
  `resource_census.py --assert-recipe-search --rundir <rd>` must PASS (exit 0) before the deck ships:
  a diagnosed generator failure cannot be closed on local diagnosis alone — `inputs/recipe_search.json`
  (the CO-PRIMARY external search, `--debug recipe-search`) must exist first. This is NON-invariant (it
  is not a lifecycle stage), so it does NOT ride the D18 umbrella; it has its own Stop-branch.
- **Open-defect close-block (N5 / G26)** — an OPEN `run_state.open_defect_notes` entry (a helper flagged
  mid-run with a `status:"open"` defect note) is a **FAIL**: a number from a helper carrying an open
  defect must not feed a comparison/check-in. `verify_pack.py <rd>` FAILs (exit 1) on any open note —
  fix the helper or substitute the blessed tool, then flip the note `status:"fixed"`. This is
  NON-invariant (not a lifecycle stage), so it does NOT ride the D18 umbrella; it has its own
  DELIVERY-only Stop-branch (`branch_open_defect`, token `G26-OPEN-DEFECT:`).

The look-up half of Tier A is scripted — run BOTH gates and paste their reports into the panel
output, `validate_run_state.py` FIRST (lifecycle: did the run reach this point with every required
stage present, in order, and its cross-stage invariants satisfied — incl. R5-before-limit-ships and
the likelihood↔selection pairing gate), THEN `verify_pack.py` (artifact integrity: does what's on
disk internally agree with itself):
```bash
$CONDA run -n rivet python trial-runs/_infrastructure/validate_run_state.py --rundir <rundir>
#   exit 0 = PASS (WARNs allowed) · exit 1 = a required stage is missing/out-of-order or an
#   invariant FAILed · exit 2 = usage/rundir error · exit 3 = the task contract itself is invalid.
#   A run that fails this gate is not ready for the checks below — fix the lifecycle gap first.

$CONDA run -n rivet python trial-runs/_infrastructure/validate_run_state.py --rundir <rundir> --verify-provenance
#   G19 PROVENANCE gate (Task 1.7): rejects a PRESENT lifecycle-required artifact whose generated_by
#   is absent/hand-written or whose input_fingerprint no longer recomputes against provenance.py —
#   closes the backfill loophole (a hand-written run_state.json cannot pass). exit 0 = every present
#   target proves its tool produced it (an absent target is N/A, not a FAIL) · exit 1 = any
#   present-but-backfilled artifact. Seeded with run_state.json; later phases extend PROVENANCE_TARGETS.

$CONDA run -n rivet python trial-runs/_infrastructure/verify_pack.py <rundir>
#   asserts internal consistency of the artifact JSONs it finds: figure files on disk,
#   figure-contract PRIMARY target fulfilled-or-FAILed (non-primary WARNed), result/scan coverage bookkeeping,
#   verdict/limit self-consistency, DEVIATIONS.md present when any artifact carries a
#   deviations/renorm/rebase provenance block, and NO OPEN run_state.open_defect_notes entry (N5/G26).
#   Exit 1 on any FAIL — fail-loud.
```
**D18 umbrella (Stop dispatcher).** The Stop hook `stop_dispatch.py` runs
`validate_run_state.py --rundir` on any CHECK-IN/RESULT **delivery** turn and BLOCKS turn-end
(exit 2, reason fed back) if it does not exit 0 — so a lifecycle-broken run cannot post a
check-in. FALLBACK (when the hook is unavailable): the agent runs
`python3 trial-runs/_infrastructure/validate_run_state.py --rundir <rundir>` itself before posting.
The G8 recipe-search close-block above is NON-invariant, so it rides its OWN sibling Stop-branch
(`branch_recipe_search` in `stop_dispatch.py`, D-4/G8) — which shells
`resource_census.py --assert-recipe-search --rundir` at turn-end and BLOCKS (exit 2, token
`G8-RECIPE-SEARCH:`) — not the D18 umbrella. FALLBACK: the `stage-recovery` skill / this step-doc runs
the same command before closing the failure. The N5/G26 open-defect close-block is likewise
NON-invariant, riding its OWN DELIVERY-only sibling Stop-branch (`branch_open_defect` in
`stop_dispatch.py`, D-4/G26) — which shells `verify_pack.py <rundir>` at a delivery turn-end and BLOCKS
(exit 2, token `G26-OPEN-DEFECT:`) when an open defect note is present. FALLBACK: the agent runs
`python3 trial-runs/_infrastructure/verify_pack.py <rundir>` itself before posting.

The script cannot read prose: the number-tracing and coverage-**claim** checks (artifact ↔ check-in
text) remain the [agent]'s job, artifact value next to quoted value, line by line.

## Tier B — physics adversary ([judgment], fresh context)
Hand the adversary the **artifacts + figures only** (not the run narrative's conclusions) and instruct
it to refute the headline. Minimum attack surface, itemized in `checklists/verification-panel.md`:
- **Basis choices** — is every comparison on a like-for-like basis (σ normalization, charge/flavour
  states, LO vs NLO, sample-σ vs model-σ)? Would a different defensible basis flip the verdict?
- **Statistical treatment** — mode appropriate and declared (`stat_mode`)? limit at the true CLs=0.05
  crossing? expected band sane? single-SR vs combination justified? 95% CL exclusion, never discovery.
- **Proxy validity** — every stand-in (fast-sim, reimplemented selection, AD proxy, truth-level
  shortcut) declared, with its domain of validity covering the quoted region?
- **Assumption-flag completeness** — do `limitations[]` + `RESULT.md` caveats cover every assumption
  the adversary can identify from the artifacts? An unflagged material assumption is a finding.

## Verdict + delivery (never silently fixed)
The panel returns **PASS / CONCERNS / FAIL** with itemized findings. The findings are **APPENDED to
the final check-in verbatim** — even after a fix, the check-in shows what the panel found. Never
silently patch the result and present it as if the panel found nothing.
- **PASS** — deliver; append the panel verdict + the `verify_pack.py` report.
- **CONCERNS** — deliver **with** the findings appended and each one answered (accepted-as-limitation
  in `limitations[]`/`RESULT.md`, or fixed + noted). Unanswered findings block delivery.
- **FAIL** — do not deliver. Fix, log the fix in `DEVIATIONS.md`, **re-run the panel** (both tiers).
  When the FAIL traces to a stage-level defect whose fix is not obvious (an empty-SR spectrum, a
  detector card that won't build, a merge that vetoes every event), fire the D8 external recipe search
  before improvising — `resource_census.py --debug recipe-search --tool <t> --model <m> --symptom <s>
  --rundir <rundir>` writes `inputs/recipe_search.json`; the published fix (card, run config, recast
  repo, thesis appendix) is often already online (see the `resource-sweep` skill).

## CHECK-IN
Attach to the final check-in: the panel verdict, the itemized findings (with dispositions), and the
`verify_pack.py` report. Only then does the result go to the physicist.

## The enforcement spine is itself verified (L6)
Beyond this per-run panel, the workflow-adherence gates are regression-verified *as software* by the L6
spine_sim verification board (run on-demand in the dev repo, aka `make green`): every gate G0a–G27 has a `cases/case_<G>.py` that seeds the bad
fixture and asserts the gate FIRES. The **clean-room self-drive** gate (G21/D17) is the integration
green — a fresh *un-hinted* `claude` launched from the DSRLab **parent** cwd must autonomously route to
a `task_contract.json` and reach CHECK-IN 1 with no dev-repo survey and no premature generation.
It runs **on-demand** in the dev repo (aka `make green-self-drive`) and records the `last_verdict.json`
verdict under the spine_sim self-drive record directory; `--with-self-drive`
asserts it. Absent that live artifact (e.g. where headless `claude -p` is not authenticated) G21 is
SKIPped so the default board stays green — never faked to PASS.
