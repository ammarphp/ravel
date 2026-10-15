# Checklist — CHECK-INS (the physicist-facing layer)  ·  [judgment] composes every check-in
# (escalation IS a check-in: a weak model composes the flag and waits; it never skips one)

Check-ins are the ONLY interface the physicist sees; everything else is machinery. A colleague — not
an operator — is on the other end: they must be able to catch a wrong plan before compute is spent,
a wrong pipeline before the scan, and a wrong number before it is believed. Every check-in is
written for a reader with limited time and attention: skimmable
headers, short numbered lists, nothing important buried mid-paragraph.

Four standardized check-ins plus one immediate class. The physicist session entrypoint
(`docs/workflow/start.md`, at the workflow root) promises exactly this sequence.

When sealed work orders exist, run `ravel work pin-obligations --rundir RUN`
before CHECK-IN 1 approval. Review the derived card self-checks and review points
in `inputs/work-obligations.json`; its SHA-256 is pinned in the check-in and its
bytes enter the approval fingerprint. See [roles and adoption](../../reference/roles.md).

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

### Cheapest sufficient method

Before approval, write `inputs/method-decision.json` using the packaged
`src/ravel/data/methods/method-decision.schema.json` and the family ladder in
`src/ravel/data/methods/ladders.json`. State the required output, precision in the user's words,
validity domain, permitted approximations and stopping criterion. Account for every
cheaper rung with a reason and evidence. An unchecked cheaper rung blocks escalation
unless the user explicitly requested the chosen method or output and the record quotes
that request. A remote machine is an execution location, not a scientific method rung.

Run `ravel method-decision --rundir RUN` to validate the record and render its method,
cheaper alternatives, forecast and forecast-versus-ceiling status into `inputs/checkin1.json`
and `<run>/CHECKIN1.md`. Review that disclosure before approval. Missing ceilings and unknown
costs read as unknown; a cost forecast is not an authorization ceiling. Full and scan
launches require a valid decision with escalation allowed, including nested and remote
launches. Lookup, explanation, dry and smoke routes do not require this launch gate.
Changing the record changes the approval fingerprint and requires a renewed approval.

Internal callers use `ravel.workflow.method_selection.record_machine_decision` with a
complete decision and explicit `scripted_experiment` or `delegated_machine` authority.
The writer validates escalation, preserves an existing different decision and refreshes
CHECK-IN 1 before approval. It grants no execution approval. Bounded validation callers
use `record_validation_decision` to record the requested current-operation check, its
cheaper alternatives, specification evidence and time ceiling. This choice covers
validation behavior; choose a physics method separately for a physics request.

For `unknown` or `uncalibrated` cost on the top two family rungs, record either
`cost_forecast.bounded_pilot` with positive finite `max_wall_hours` and an `evidence`
list naming its bounded pilot record, or `cost_forecast.physicist_signoff` with
`authority` (`human_operator` or `human_relayed`), the verbatim `quote` and an `evidence`
list naming the retained assent. These are optional evidence fields in the version-one
schema. A free-text cost basis and a machine reviewer label do not establish sign-off.
A bounded pilot does not replace the production-cost or scientific-validation gates.

Approval authority reads as `human_operator` for direct interactive assent without an
agent session marker, `human_relayed` for an agent relay carrying the user's verbatim
quote, `delegated_machine` for a recorded delegation, `scripted_experiment` for
`--scripted`, and `unknown` when evidence establishes none of these. These labels
record provenance; they do not authenticate a person's identity. Historical records
without authority evidence read as unknown. Scripted and delegated decisions do not
become human review. Use `ravel steer` and `ravel respond` for the existing custody
steering and response commands; their `ravel gate-wiring` forms remain available.
The method record's own `provenance.authority` is its author's declaration. CHECK-IN 1
shows a declared human label as unverified; the approval receipt carries the evidenced authority.

Ordinary reproduction/reinterpretation plans bind the mandatory
[research record contract](../reference/research-protocols.md#execution-enforcement-and-producer-boundaries).
Record prospective evaluator pins and applicability before execution. Selection,
confirmation and stopping evidence comes from observed experiments; a missing
mandatory producer remains `producer_pending:<protocol>` at claim acceptance.

### Variants by task
Every CHECK-IN 1 has the core sections (i) preamble, (iv) plan, (v) numbered flags and
(vi) how to respond. The task adds its own sections. The task contract selects the variant.
When a task admits more than one (research, no_routine), name it in the top-level `variant`
field of `inputs/checkin1.json`.

| variant | task_mode | added sections (keys in `sections`) |
|---|---|---|
| `reproduction` | reproduce, reinterpret, projection, scan, no_routine | (i-b) resource census, (ii) published-figure gallery, (iii) figure target and waypoint |
| `reference_withheld` | every task admitting reproduction, including research and unsupported | (i-b) allowed resource census, `withheld_waypoints`; replaces (ii) and (iii) |
| `calculation` | calculation, likelihood | `formula`, `conventions`, `inputs`, `precision`, `check_value` |
| `method_study` | method-study intake | `dataset`, `splits`, `baselines`, `calibration` |
| `survey` | survey, summary_plot | `census_table` (one row per source, naming it), `coverage_gaps` (a list; `[]` when none) |
| `manuscript` | manuscript intake | `source_runs` (each with its `path`), `template` |
| `generate` | generate | `recipe`, `observable` |
| `new_search` | anomaly_search, no_routine | `blinding`, `regions`, `validation` |

Research tasks may use any variant. Each required section carries real content; empty
values and stand-ins such as `N/A` or `TBD` count as missing.
Write the core sections as described below and add the variant's sections in the same
plain style: what was chosen, why, and what the physicist should check.

**Calculation.** `formula` is the expression to evaluate, with symbols defined. `conventions`
gives normalisations, units and sign choices. `inputs` lists each value with its source.
`precision` states the order and numerical tolerance. `check_value` is a known limit or
independent value the result must reproduce.

**Method study.** `dataset` names the samples and their origin, `splits` the train,
validation and test partition, `baselines` the methods compared against, and
`calibration` how the method's output is calibrated and on which sample.

**Survey or summary.** `census_table` lists each analysis or result found, one row per
source. `coverage_gaps` lists what the request asks for that no public result covers.

**Manuscript.** `source_runs` lists every run whose results the manuscript reports, with
its path and the result file used. `template` names the journal or document template.

**Generate.** `recipe` gives the process, model, generator settings, event count and seed.
`observable` defines the distribution or quantity to produce, with binning.

**New search.** `blinding` states what stays hidden and until when, `regions` defines the
signal, control and validation regions, and `validation` says how the background model is
checked before unblinding.

**Held CHECK-IN 1.** When a scientific study's supplied file or native prerequisite is
not yet available, `ravel plan` writes a held CHECK-IN 1 in the run directory:
`<run>/CHECKIN1.md` and `inputs/science-held.json` list each unmet item as a numbered flag,
marked `input` (a file not found at its path) or `prerequisite` (an engine, package or
runtime to provision). Show it to the physicist. Once the items are available, run the
same `ravel plan --rundir <run> --spec <spec>` again; it writes the concrete plan in
the same directory and keeps the held record under `inputs/held/`.

**Pinned plan.** When the task contract pins a request plan (`request_plan`), CHECK-IN 1 also
carries `plan` (one row per node), `claims`, `coverage` and `ambiguities` (`[]` when the reading
has none), plus `boundaries` and `authored` when the plan has them. Each equals the plan or the
reading; the validator compares them. Every open ambiguity row is a numbered flag in (v).
Each `claims` row gives the claim's `id`, `kind`, `statement` and `fidelity`. A claim served by
child runs whose basis needs an acceptance certificate, R5 closure or a published likelihood reads
`not certified on this route`. Any claim delivered uncertified also gives `explanation`, a
plain-language account for the reviewer of what is not certified and why, `certifiable_route`, the
route that would certify it, and a numbered flag naming the claim and its fidelity.

**Delegated approval.** Under a delegation declaration, a machine may approve a pinned plan only
when no physics-critical ambiguity row waits for user text, no physics-critical fact is inferred,
every claim keeps a prescribed statistic, every boundary or alternative claim was chosen in user
text, and no waypoint is `none`. A physics-critical adapter default is adopted only with an entry in
`inputs/delegated_defaults.json` whose justification cites a span of the request, a registered
invariant or an authoritative-practice reference. A human approval of the same plan is unaffected.
A delegated re-approval compares the current bytes with the prior approval's commitments. It
refuses any changed path outside the delegation's `bounds.allowed_changed_paths`, and records
allowed changes in `input_changes` and `DEVIATIONS.md`, as the human command does. Every
delegated approval appends to `logs/delegated-approvals.jsonl`. When that log or the run
state records an earlier approval and the approval file is missing, delegated approval is refused.

The reproduction variant uses the sections below in this order, each under its own header:

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

### Reference-withheld predictions

Declare `variant: "reference_withheld"` when a `blinded`, `blinded-data` or
`no-value-extraction` rule matches the comparison target. The validator applies
`source_policy.matches` to the identities supplied in `contract.targets`
(`analysis`, `arxiv`, `inspire`, `hepdata`), published-value classes and numeric
quantity kinds. It also checks paths in the record's comparison and figure target
descriptors, resolving the `inputs/` prefix and absolute filesystem aliases
against the input root. Selector-free
blinding rules cover every target; an unrelated identity or quantity restriction
does not select this variant. A restricted ordinary `reproduction` record is
refused with the name of the variant to use.

Keep core sections (i), (iv), (v), (vi), the allowed resource census (i-b), and the
`sources` census. Replace (ii) and (iii) with `withheld_waypoints`, a non-empty
list of checkable records. These are consistency checks independent of a
published comparison value, not physics certification:

| `kind` | Required fields and check |
|---|---|
| `generator-closure` | `generator_sigma_pb`, positive `table_sigma_pb`, `order_difference` (declared perturbative order difference), nonnegative `relative_tolerance`; relative cross-section difference must be within the tolerance. The table is an independently supplied normalization input, declared as `source` with an input-root-relative `path` or `identifiers`; a source that is a contract target or matches a governing restriction is refused. |
| `sigma-br-lumi` | Nonnegative `sigma_pb`, `br` between zero and one, `lumi_fb`, `expected_events`; before-cut events equal `sigma_pb * br * lumi_fb * 1000`. |
| `cutflow-monotone` | `counts`, at least two finite nonnegative counts in nonincreasing order. |
| `mc-precision` | Non-empty finite nonnegative `relative_errors`, one per bin, and positive `target`; each relative statistical error is at most the declared target. |
| `invisible-census` | Distinct integer `detector_particles` and `spectrum_particles` lists; the two sets must agree. |

Any waypoint that declares a `source` is checked the same way. A withheld record
refuses a published-figure gallery, figure target or comparison with published
values, including nested fields. A `gallery` that lists only run-relative files
under `outputs/` and a `comparison` between the run's own numbers that names no
external `source`, `reference`, `path` or identifier are the run's own diagnostics
and are accepted. A later comparison uses the separate top-level
`post_sealing_comparison` record only after delivery. It must state
`result_sealed_first: true`, `phase: "after-delivery"` and
`label: "after-sealing"`, and carries the compared values only, never a gallery or
figure target. These declarations label the comparison; they do not establish
custody or grant permission to read a still-restricted source.
A restricted comparison target is found from the contract `targets`, and from
every `identifiers` object or `path` in the record's comparison and figure targets
and section (iii). Identifiers match in every equivalent spelling.

For qualitative inspection of an allowed supplied document, use
`python -m ravel.plotting.fetch_figures --pdf inputs/fictional-note.pdf --out outputs/gallery`.
Its `figure_manifest.json` says `usage: "qualitative"`, lists page figures and
pins the source document. A `no-value-extraction` rule permits this qualitative
view and document text; `digitize` follows the gallery provenance and refuses
numeric extraction from its pages. A `forbidden-source` rule naming the document
refuses even qualitative inspection. Do not include this gallery in a withheld
CHECK-IN record.

### (iv) PLAN
The concrete plan, skimmable: samples to generate (process, parameters, event counts), observables /
signal regions, the intended statistical treatment (published likelihood vs counting), and the
compute budget — what runs, roughly how long, and what is deferred until after CHECK-IN 2;
the numbers come from `src/ravel/workflow/cost_preflight.py`, never from prose recall.
Keep wall hours, CPU hours, peak RAM, disk footprint, events, model calls, model
tokens and queue hours in separate dimensions. A null value is displayed as
unknown. Do not multiply or add unlike dimensions into a total cost. A ceiling
or reservation is not a measurement.

Cost records carry the selected method rung as `cost_class`, `status`
(`calibrated`, `historical`, `uncalibrated` or `unknown`), `resource_vector`, the
process/configuration/machine `profile` and `uncertainty`. Pilot intervals are
conservative scaling bounds with an explicit margin, not confidence intervals.
Historical references stay historical and cannot calibrate a new profile.

Use `cost_preflight.forecast_for(method_decision, study)` to obtain the selected
rung's record and cheaper alternatives with supplied data. The study supplies
`cost_profiles[method]` and `cost_records[method]`. Alternatively supply
`observed_cost_catalogue` and `cost_targets[method]` with `spec`, `route` and
`margin` (optional `base` and `ceiling_seconds`) to forecast from measured
observations. Each supplied record must
match the method, process, configuration and machine. Missing data stay unknown;
declared ceilings supply no forecast. `cost_records.contract_forecast(record)`
projects the exact shared `cost_forecast` fields for the method decision; keep
the full record with its resource vector and alternative records beside it.

After a completed approved pilot, use `ravel pilot-cost observe --rundir <pilot>
--output <observation> --catalogue <catalogue>` to append measured usage with
receipt pins. Repeated receipts are idempotent; changed receipts are refused.
Use `ravel pilot-cost forecast --catalogue <catalogue> --target <spec> --route
scoped|science --margin <factor> --output <forecast>` to read matched observations.
Choose either `--catalogue` or repeated `--pilot` inputs. Profiles and machines
must match. Completed failed/interrupted observations can be appended through
`cost_records.append_observation`; they remain in the catalogue and supply no
production calibration. This command launches no compute and grants no approval. Retained
output bytes are a disk footprint observation; they do not measure transient
peak disk or cumulative bytes written. Unmeasured CPU, RAM, model and queue
usage remain unknown.

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

The GO binds the actual waypoint evidence. Write a comparison JSON with `status`
(`pass`, `fail`, `warning`, or `diagnostic`), a nonblank `summary`, and a nonempty
`diagnostics` object containing the measured discrepancies. Create its manifest:

```bash
python -m ravel.workflow.waypoint_evidence --rundir <rd> \
  --produced outputs/waypoint.png --reference inputs/published.png \
  --comparison outputs/waypoint-comparison.json --input inputs/generation_recipe.json
```

Repeat `--input` for each relevant input (including a composed side-by-side figure if shown).
Set `sections.evidence_manifest` in `inputs/checkin2.json` to `inputs/waypoint_evidence.json`.
Then `workflow_state.py go --rundir <rd> --quote '<the physicist reply>'` writes the version-3
`inputs/checkin2_go.json`. It binds the check-in, current first approval, manifest, both artifacts,
comparison, inputs, and the complete accepted scientific review. Changing any of them invalidates GO.
Before CHECK-IN 1, declare the review policy and correction budget. At CHECK-IN 2, complete the
[scientific review cycle](../reference/physics-review.md). A failed scientific comparison may
support diagnostic delivery when that scope was declared; it cannot authorize bulk reproduction.
ADJUST is never GO. Old GO versions remain historical evidence and cannot authorize new compute.

| Execution path | Before launch | Retrospective evidence |
|---|---|---|
| Supervised native stages | First approval; evidence-bound GO for full/scan | Exact approvals and digests captured before Popen; separate process-launch event |
| Native scan dispatch | Same checked launch interface; point and budget approval | Dispatch event plus each point's stage/generator events |
| Bash scan guard / campaign budget | Valid current first approval and GO | These checks alone do not establish that a process launched |
| Direct native generator entry without supervisor | Valid current first approval and GO | No automatic historical authorization proof; use supervised execution |
| Other direct single-point commands / custom supervisor | Written CHECK-IN 2 rule; no universal size detection | No automatic historical authorization proof |
| Scoped generate/likelihood route | First approval within scope; no CHECK-IN 2 | Its own scoped execution receipts |

The lifecycle validator requires both a current evidence-bound GO and matching launch-time
receipts for recorded native full/scan generation. Scan aggregates check every reported point's
manifested run directory and generation receipts. A later GO cannot authorize an earlier launch.
Operational approvals carry real UTC timestamps; tests can inject `WORKFLOW_STATE_UTC`. Launch
events under `logs/authorization/` use exclusive creation, consecutive sequence numbers and a
hash chain. These local records establish ordering for the checked interface; they do not
authenticate the respondent or provide an external tamper-proof audit. Runs predating 2026-10-07
with neither a version-2 GO nor launch records remain explicitly `waived-legacy`, never historically
verified. Adding a version-2 GO cannot waive missing launch history, even under an older run name.

CHECK-IN 1 binds the saved executable plan and the files its operations declare
as inputs, including native TOML, generator cards, detector Tcl dependencies,
shower settings, source templates and their rendered cards. It also binds each
stage's resolved executable, its `.py`/`.sh` argument scripts and its registered
helper files, which execution adds as stage inputs. The input set follows
operation reads rather than file extensions. A read beneath a stage output is a
produced intermediate only when its producer runs first: a declared (transitive)
dependency of the reading stage, or an earlier stage when the plan declares no
dependencies. Otherwise the read is bound like any other input. Produced event
files and stage logs are checked through execution receipts. Preparation may materialize the exact
approved rendered bytes; an edit to those bytes requires a new approval.

Approval stores per-path byte commitments. A later changed, added or removed
input refuses launch with the affected path and records an approved-input row in
`DEVIATIONS.md`. Approval verification is read-only; only the launch paths write that row.
That row is disclosure. To proceed, amend the relevant plan and
CHECK-IN 1, update the contract's plan pin if needed, and run
`workflow_state.py approve --rundir <rd> --quote '<approval of the amendment>'`.
The approval command retains the changed paths and amendment quote. Re-approval
also invalidates the previous CHECK-IN 2 GO. Old plan approvals without these
operation byte commitments must be re-recorded before new execution.

After an amendment changes the planned rendering, the old materialized card may
remain until preparation reruns only when a successful execution receipt binds
those bytes to the prior approval. Re-approval retains that approval's digest in
the change history. The current producing stage's receipt controls this allowance;
history alone does not authorize old bytes. Preparation may archive its card
before writing the new rendering while its running receipt binds the new approval.
After preparation, a hand edit, deletion or revert to earlier card bytes refuses
launch and requires amendment re-approval.

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

When the run adopted adapter defaults under delegation, the deck adds `adopted_defaults`: one row
per entry of `inputs/delegated_defaults.json` with its `id`, `node`, `pointer` and `justification`.

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
  exception:** a `compute_launched` entry is ALWAYS written by the DRIVE step-doc's explicit
  `record --kind compute …` (which supplies the N6 `bg_kind`/`logfile`/`done_condition`/`next_action`
  liveness fields) — never by the observer or this fallback, because only DRIVE knows those fields.
- **Emit + validate (the machine gate, G18):** every check-in is emitted as a machine artifact —
  CHECK-IN 1 to `inputs/checkin1.json`, CHECK-IN 2 to `inputs/checkin2.json`, the results deck to
  `inputs/checkin_deck.json` — and validated BEFORE it is sent: run
  `python3 scripts/run.py ravel.validation.validate_checkin inputs/checkin1.json` (likewise for the
  CHECK-IN 2 and deck artifacts). The validator asserts the required SECTIONS carry content — CHECK-IN 1's core sections
  (i, iv, v, vi) plus its variant's sections (the reproduction variant's are i-b, ii, iii), with the
  `F<n>`-numbered flags in (v) and the three response modes in (vi); CHECK-IN 2's GO/ADJUST ask; the deck's eight sections including the
  verbatim step-9 verification-panel verdict — and **a missing required section is a FAIL, not a
  warning**. Same public `validate(obj) -> list[str]` contract as `validate_task_contract.py`; run it
  by hand at each check-in when the emitting composer is unavailable.

Registered CHECK-IN 1 sections are declared in `src/ravel/data/checkin/sections.json`.
Each trusted package row has `id`, integer `order`, and either JSON `content` or
`module` and `render`; an optional `validate` function belongs to that same module.
The render function receives a context mapping with `document`, `base_dir`, and
`contract`, and returns content or `None` when it does not apply. The validation
function receives `(content, context)` and returns errors. Registrations sort by
`(order, id)`. `validate_checkin.with_registered_sections` composes the sections;
`validate_checkin.checkin_bytes` encodes the exact JSON bytes. The ordinary science
composer calls this seam, and validation refuses omitted or changed applicable content.
The review-points producer supplies `checkin_section(context)` through one registered
call; its absent implementation remains a dependency, not computed review evidence.

Source restrictions are request or harness rows with optional input-root-relative
`paths` globs and, for `no-value-extraction`, optional `scope.quantities`.
`source_policy.from_reading`, `digest`, and `matches` preserve these keys.
The contract's `forbidden_sources` must equal the pinned reading's rows; routing writes
them into the contract from the reading. Under restrictions, CHECK-IN 1 must carry a
nonempty `sources` census listing every source descriptor the run reads. A run that reads
no external source lists the single row `{"none": "<reason>"}`.
The knowledge broker checks source descriptors before opening bytes. These direct
entry points call `restriction_guard.require(tool, source, rundir=..., output=...)`
before any network request, source read or output write:

- `hepdata_fetch`: `main`, `_open`, `get_json`, `fetch_tables_via_record_data`,
  `_tables_via_hepdata_cli` and `fetch_offline_fixture`, which also admits every
  fixture member (`record.json`, tables, `likelihoods.json`, models) by its own path.
- `fetch_figures`: `main`, `_open`, `arxiv_from_inspire`, `extract_figure_files`,
  `_read_tex_members`, `build_figure_map`, `pdf_page_route`, `resolve_figure` and
  the `--pdf` gallery.
- `digitize`: `run_spec`, `inventory`, `parse_pdf_page`, `load_series` and
  `sha256_file`, and through them the `figure_comparison` command line.

Other modules that read published tables, likelihoods, reference curves or
documents do not call this guard; inside a governed run, read sources through
the knowledge broker or one of the entry points above.
The restriction is a property of a run. Discovery anchors are an explicit run
directory, the output path and the current directory: each anchor and its
ancestors, before and after symlink resolution, are checked for
`inputs/task_contract.json`, and every discovered run binds with its own contract,
even when two runs share one contract file. A source path inside a run does not
by itself discover that run: with the current directory and output outside the
run and no explicit run directory, nothing binds. An unreadable or invalid
contract is a refusal. No environment setting or tool flag lifts it. Numeric
retrieval from an opaque cached source whose identity cannot be established under
an identity restriction is refused before reading source bytes. A record's own
identities are kept alongside any identity the caller supplies. Identity matching
treats an arXiv version suffix and a zero-padded record number as the same
source. Path rules match input-root-relative paths only; a file outside the run
is matched through the provenance of every qualitative gallery manifest that
lists it, never by its basename. Public text, cards and object definitions stay
readable unless a governing rule names them; `no-value-extraction` distinguishes
metadata and qualitative viewing from numeric extraction, and a numeric
extraction whose quantities are not declared in advance is bound by every
quantity a rule scopes. A record lookup without `--tables` or
`--download-likelihood` reads metadata only; figure retrieval carries the figure
classes and its record identity into the cached files it reads.
`source_policy.require_read` refuses prohibited sources with a receipt naming each
rule. Direct refusals retain write-new numbered JSON receipts under
`logs/source-receipts/` and name their paths in the exception. Brokers retain
receipts in their existing call ledger, and `inventory` excludes withheld
descriptors while retaining receipts. A CHECK-IN `sources` census uses
the same refusal. Resolve filesystem aliases against input roots before matching.
Quantity scopes permit definitions outside the banned quantities, while a matching
path remains prohibited. Patterns come from request evidence or harness rows.

Full detector simulation is held when the available route supplies only fast
response. A demand is any active mention such as "full detector simulation", "Geant4 full
simulation", "fullsim" or "must be full simulation". The reader decides who must simulate.
"Reproduce the published contour using full simulation of the detector" is a demand: the run
simulates, whatever result the sentence names. A mention is not a demand when it names consumed
products ("full-simulation efficiencies from the supplied table", "efficiencies obtained from full
simulation"), or when its clause gives the reference as the simulating agent ("which was obtained
with full simulation", "the collaboration used full simulation"). Preserve its reason and requested fidelity; an explicitly revised request
is required before using a different response. A held whole-request input has rung
`none`, and its task contract cannot authorize compute.

`source_policy.accepted(rundir, declared_outputs=[...], claim_scope=...)` consumes
current accepted review custody and returns only the exact declared output files.
Reviewed extras appear under `undeclared_outputs`; missing declared files are refused.
Declare paths relative to the run under `outputs/`. Review acceptance remains distinct
from receipt-derived evidence status: a `certified` label at either check-in or delivery
requires a freshly derived `validated` evidence row from the completion claim validator.

**Agreement targets.** Every `agreement` claim of the pinned request plan needs one record in
`inputs/agreement_targets.json` (schema `src/ravel/data/claims/agreement_target.schema.json`):
the reference kind and its content pins, the result and reference quantities, the reference
family, the node lattice, the tolerance rule and a noise-model reference. The registered
`agreement_targets` section puts each record and its node coverage of the reference lattice in
the CHECK-IN 1 bytes. CHECK-IN 1 is refused when an agreement claim has no record, compares an
observed result with an expected reference (or the reverse), changes basis or unit without a
declared conversion, cites a `published_reproduction` without recipe pins, or compares nodes
off the reference lattice. One claim has one reference; a second comparator is a second claim.
The compared family is the family of the result the agreement claim compares. The drafter sets
`level: not_applicable` on agreement claims, so the family comes from the limit, estimate or
significance claim that shares the comparison target. When the plan holds such claims of both
families, name the compared claim in the record's `compares`. A run-relative or absolute pin must
exist and match its sha256; a remote locator is listed under `unverified_pins`. The tolerance rule
must equal the plan claim's `comparison.tolerance` (`per_node` and `max_abs` are the same bound).
Different quantity names need a declared conversion. A published reference needs a pinned noise
model. Partial lattice coverage is flagged in the section.

**Residual diagnosis.** At CHECK-IN 1, pin the agreement target's noise model as a
`residual-reference-noise` record. For each compared node it holds the coordinates, the reference
value and the reference `staterror` of each region, plus an optional `alpha` (default 0.05). The
approval binds it. Once an agreement claim has results, a registered tool stage writes
`residual_model.json` in the run's `claims/` directory. Per node it holds:
- numeric coordinates, and our and the reference's limit;
- replicas of ours, each `{value, seed}`, with at least three distinct producer-recorded seeds;
- declared fingerprint values;
- per region, the background, our signal yields with `sumw2`, and the reference's yields with
  `staterror`.

Run `python -m ravel.validation.residual_decomposition --rundir <run> --claim <id>
--model-receipt stage:<name>:<attempt_id> [--attributions <claims.json>]`.

What the diagnosis accepts:
- It reads the target only from the approved CHECK-IN 1.
- It accepts the model only as the registered output of that receipt.
- It refuses nodes that differ from the target's compared nodes.
- It refuses reference values or `staterror` that differ from the approved noise model.
- It takes `alpha` from that model and from no caller argument.

How it decomposes:
- It splits each node's log residual exactly into a rate term, a shape term and a likelihood
  term, per flavour and per signal region. The shape term is a stat-only signal-region Asimov μ95
  computed identically for both sides, leaving out bins without background. The likelihood term is
  the remainder: control-region signal, systematics and the construction of the statistic.
- It correlates each term with the fingerprints and the reference's control-region signal
  fraction, with a Holm correction over every term and variable.
- Our side of the total takes the larger of the propagated noise and the 95% upper bound of the
  replica scatter. The likelihood term is attributable only with replicas.

Thresholds sit at the approved false-alarm rate (Šidák per node, median standard error per scope).
Records go under `claims/residual/<claim>/`. `check:attribution_above_noise`
(`attribution_check.json`) refuses an attribution claim on a term below its threshold, on a term
without a noise budget, or on an unsupported fingerprint correlation.

When the residual exceeds the target tolerance beyond noise, one trigger goes to the RCA ticket
and board-epoch producers. While those modules are absent it is queued in `rca_triggers.json`.

At CHECK-IN 3 and at the `delivery` gate, `residual_decomposition.delivery_errors` requires, for
each approved agreement claim, a stored decomposition equal to its recomputation from these
custody inputs. It also recomputes any stored attribution check. A term above noise is a feature
to explain, not a cause.

**Acceptance certification tolerances.** Before composing a CHECK-IN 1 for
`ravel.validation.certify_acceptance`, write `inputs/certification_tolerances.json`.
An empty object proposes the existing defaults; override only the named controls.
A planned run (pinned request plan) whose statistics mode ships a certified limit shows
the defaults in this section even without a proposal file:
`driving_tol: 0.15`, `contributing_tol: 0.25`, `mu95_bound: 0.10`,
`tail_events: 5`, `driving_factor: 1.5`, `interp_max_span: 200.0` GeV.
Compose with `validate_checkin.checkin_bytes(document, rundir)`; the registered
provider fills all six values in `sections.certification_tolerances`, and validation
refuses omitted, changed or invalid content. A composer may instead pass the proposal
as `context={"certification_tolerances": {...}}`. Show these actual bytes before
recording approval. Retain the proposed file with the run inputs.

Invoke `certify_acceptance --rundir <run>` for governed certification. The producer
also discovers governance beside its acceptance input and output; explicit and
discovered run directories must agree. Omitted flags use the approved section,
including approved overrides. The live approval verifier must pass. An old approval
without this section cannot authorize a new governed certificate: compose the
section and record the renewed approval first. Legacy CHECK-IN documents keep their prior bytes.

A looser control than approved (a larger tolerance, bound, tail threshold or
interpolation span, or a smaller driving factor) is refused: compose the changed section
and record a renewed CHECK-IN 1 approval. A deviation row never loosens an approved value.
A later tighter CLI value leaves the approved CHECK-IN intact and requires one
exact row in the run's `DEVIATIONS.md` table with columns `parameter`, `from`, `to`,
`why`, `touches`. Name the control (underscore spelling or its CLI flag), the
approved numeric value and the new numeric value; supply a nonblank reason and
affected artifacts. A prose mention, wrong values or unrelated row does not suffice.
Emit the deviation check-in described above. The report records approved and
effective controls, the approval fingerprint, hashes of the approval and CHECK-IN,
and any matched deviation rows and ledger hash. It rechecks these before writing.
Certificate consumers call
`ravel.validation.certification_tolerances.verify_report(rundir, report)` and refuse
nonempty errors. The live acceptance certificate does this for every named acceptance
report, and refuses a certificate plan whose `relative_tolerance` exceeds the approved
`driving_tol`. Outside any run, `certify_acceptance` refuses unless `--diagnostic` is
given; a diagnostic report is marked as such and no consumer accepts it. This verifies recorded integrity; it grants no physics certification
or human-authentication claim. Other selection and normalization inputs retain
their separate contracts.

> **Mechanized (A6):** `validate_checkin.py` on `<rundir>/inputs/checkin*.json` verifies every gallery-cited image EXISTS on disk and rejects `file://` links — attach/render figures, never bare file paths.

> **Mechanized:** the go-ahead is an ARTIFACT — `workflow_state.py approve --rundir <rd> --quote '<the physicist reply>'` (refuses without a VALID `checkin1.json` + a `cost_preflight.json`). The pre-exec Bash guard refuses smoke/full/scan generation without it, refuses `nohup`/detached or unsupervised launches, and refuses generation with no recorded recipe — BEFORE the process starts.

> **Mechanized (research preregistration):** the same approval writes the run's research preregistration, derived in code from the approved plan. Launch refuses without it. If approval reports `preregistration REFUSED`, fix the named plan input and run `ravel research-preregister --rundir <rd>`. Never write the record by hand. See [launch preregistration](../reference/research-protocols.md#launch-preregistration-resume-migration-and-route-applicability).

## Epoch-two agent review and resource section

For contracts with `agent_layer_epoch: 2`, the CHECK-IN 1 integration calls
`run_ceilings.checkin_section(rundir)` and displays and fingerprints
`inputs/agent_ceilings.json`. Missing API-transport caps refuse approval.
Retain `review_points.derive(review_points._facts(rundir))` with the approved
policy. Before each consequential action, the lifecycle owner consumes the
read-only `decision_gate.check(rundir, gate, action)` errors, including missing
provider and receipt IDs. These APIs do not themselves install lifecycle hooks.
CHECK-IN 3 includes `review_points.checkin3_section(rundir)` so observed-data
calibration choices remain visible. See the scientific judgment reference for
receipt, parallel-safety and exact output-to-requirement bindings.

CHECK-IN 1 also includes the registered `recipe_ledger` section. A deviated row
requires an exact numbered flag or a verified RDJ deviation receipt; the launch
provider rechecks it against current input bytes and approval. CHECK-IN 3 must
include `recipe_ledger.checkin3_section(rundir)` under `sections.recipe_ledger`,
including every unknown row. `recipe_ledger.with_checkin3_section` composes these
bytes; the delivery validator refuses omissions or mutations. See
[recipe ledger](../reference/native-pipeline.md#recipe-ledger-before-full-execution-and-at-delivery)
for observation pins, flags and prospective RDJ payloads.

For epoch-two CHECK-IN 1, call `review_points.approve(rundir)` before sealing the
approval fingerprint, including `inputs/review_points_approval.json` and
`inputs/agent_ceilings.json`. The ordinary and delegated workflow-state approval
writers do this; other route-specific writers must use the same seam. Record the
contract's `run_init` snapshot at intake, and the actual CHECK-IN 1 response
snapshot through its trusted producer. Report receipt `independent` and advisory
labels from `review_points.pending`; self-attested workers never fill independent
slots. At CHECK-IN 2 pass `action.claim_id` for a single claim; omit it to check all
claims. Delivery checks all claims and calibration obligations. The §5/§6 details
and remaining wiring prerequisites are in the scientific judgment reference.

## Live physicist steering

Set the study policy before CHECK-IN 1 with `ravel gate-wiring steer policy
--rundir <run> --set <file>`. The JSON file declares autonomy (`manual` or
`bounded_delegated`), check-in thresholds and hard ceilings for cpu_hours,
wall_hours, disk_gb, events and model_calls, mandatory signoff_steps, unknown_cost
(`ask` or `pilot_first`), on_pause (`drain` or `cancel`), and result_acceptance
(`physicist` or `review_only`). Null resource values state no additional steering
limit; ordinary admission still applies. Custody retains the exact source text
and authority. `inputs/steering/policy.json` is a readable mirror. Same-user
operator text has authority `unknown`; machine acts use `delegated_machine` or
`scripted_experiment`. These labels do not attest human identity.
Steering enforces `autonomy`, `signoff_steps` and `on_pause`. The check-in
thresholds, hard ceilings, `unknown_cost` and `result_acceptance` are recorded
and presented at CHECK-IN 1 for the plan and for the ordinary budget and review
checks; steering does not enforce them, so a ceiling of zero events here does
not by itself refuse a launch.

The flags form uses `--set flags --autonomy manual --hard-ceiling events=0
--checkin-threshold wall_hours=1 --signoff-step <operation> --unknown-cost ask
--on-pause drain --result-acceptance physicist`. The source text retains the
argument sequence. Show the custody policy in CHECK-IN 1's registered
`steering_policy` section and read `ravel gate-wiring checkin1 --rundir <run>`.
A policy change increments the steering epoch and requires current plan
reapproval. It does not enlarge a machine delegation.
Each scope event records `approval_sha256_at_event`. Reapproval needs a custody
approval row with a current receipt digest different from that event's digest.
An unchanged receipt leaves the hold in force. Machine reapproval requires
`bounded_delegated` autonomy and no affected node, descendant, operation or rung
in `signoff_steps`, under both the current policy and the policy recorded with
the event. After a plan approval, the recorded policy is the one in force before
the event, so a policy change cannot authorize its own machine reapproval.
Reapprove with `ravel approve --rundir <run> --quote <text>`. For a scientific
study this keeps the replaced receipt under `inputs/science-approvals/` and
makes the new one current; it is refused when no steering hold needs it.

Use `ravel gate-wiring steer note|require|redirect|pause|resume|veto|priority
--rundir <run> --text <exact instruction> [--affects <node-ids>]`. Node IDs are
comma separated; an empty set addresses the study. A note records context and
has no execution effect. Requirements and redirects hold affected work and its
descendants until acknowledged and reconciled. Redirects require plan reapproval;
use `--within-scope` only for a redirect inside the approved scope. Add
`--scope-increase` to any instruction that enlarges the approved scope: it then
requires plan reapproval whatever its effect, and its acknowledgement approves
nothing. Veto denies
the step and descendants. Release it with `resume --supersedes <veto-event-id>`
and acknowledge that release. Priority uses `--priority <integer>`; larger
numbers reorder eligible pending work without increasing any resource ceiling.

Before each dispatch, the coordinator and study workers read
`ravel gate-wiring steer state --rundir <run>`, acknowledge new events with
`steer ack <event-id> --interpretation <text> [--amended-plan <path>]`, and re-plan.
Requirements and redirects need a JSON amended-plan artifact whose content is
pinned by the acknowledgement. Apply the amended plan through the ordinary
planning route; acknowledgement does not install a plan or approve a scope
increase. Include `--expected-epoch <integer>` when answering a saved view; stale
answers fail. Acknowledging an event after a later instruction was recorded
requires `--expected-epoch`, so an answer written before that instruction
cannot pass unnoticed; the newest event needs none. Every launch calls `dispatch_permitted` and retains ordinary
approval and budget checks. Unbound launch identities hold conservatively when
affected work is blocked. Board posts remain advisory.
A supervised stage is admitted or refused by the plan node that owns it: the node with
that id, or the one node whose `stage.name` is the stage name. A veto on another branch
leaves such a stage admitted. A stage the plan gives no single owner holds while any
branch is blocked, and a launch that names a different node than the plan does is refused.

Pause refuses new dispatch immediately. The execution controls drain current
work or cancel registered processes according to policy. Steering is decided
again at every backend submission and container start inside an authorized
stage: a partition driver or backend worker that was already running submits
nothing further after a pause, its queued partitions stay pending without
spending an attempt, and the jobs it had running drain. A nested backend stage
follows the steering of the run and stage that own it. An in-process graph node
is admitted under the steering lock and recorded as running work before its body
starts: a pause that commits first refuses the node, a later pause finds it
`draining`, and a cancelling pause never signals the process that runs it. State distinguishes
`requested`, `draining`, and `observed-stopped`; requesting a stop does not prove
processes stopped. Acknowledged resume clears this steering pause's stop markers.
Restart preserves custody's epoch. After renaming a bound run, use the existing
custody relocation operation before serving it; changing directories does not
reset authority. Earlier results stay preserved.
An unbound run with steering mirrors and missing custody refuses dispatch;
restore its original location and custody before continuing.
Dispatch needs a steering journal that custody initialized for the run location.
`ravel initiate`, `ravel plan`, a research study, a scan plan and a graph scope
record it when they create their directory; a child run is bound to its parent
and carries `inputs/steering/parent-binding.json` as a readable mirror. A
directory without that record is refused, so a renamed or copied run (or child)
does not launch outside its veto, hold or pause. For a run directory prepared by
hand the operator records it once with `ravel gate-wiring steer init --rundir
<run>`; agent sessions are denied that command. Steering recorded before the
run directory holds any run content starts the journal itself.
`steer init` does not make a copied or renamed run new. RAVEL writes
`run-identity.json` into each directory it creates or initializes and binds that
identity to the location. The command refuses a directory that carries the
identity of a run recorded elsewhere, or (without an identity record) the task
contract or recorded steering text of one; it names the recorded location and
records nothing. Return the directory to that location, or work there: the pause,
veto and parent binding recorded for the run still apply. At the recorded
location the command is idempotent and keeps every control. Do not delete or
copy `run-identity.json` between run directories.

Record the physicist's result response with `ravel gate-wiring respond
accept|reject|rework --rundir <run> --text <exact response>
[--expected-epoch <integer>]`. Result disposition is recorded separately from
scientific-review acceptance and does not authorize a new run. The top-level
`ravel steer` and `ravel respond` aliases use these same subcommands when the
alias package is installed.
