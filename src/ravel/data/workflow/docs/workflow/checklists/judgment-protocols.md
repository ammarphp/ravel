# Checklist — judgment protocols  ·  the HOW behind every [judgment] tag

These eight protocols are the difference between knowing physics and *operating* on physics under
limited information. They were extracted from this project's recorded incidents (each cites its
worked case in `docs/reference/failure-modes.md`): a weaker model's physics knowledge is rarely the
gap — its *protocol* is. Run the matching protocol BEFORE taking any [judgment] step; the
`judgment-protocols` skill routes here. They compose: a typical step-2 decision runs P6→P3→P2 in
sequence; a discrepancy runs P5 with P4 anchors; every delivery ends with P8.

---

## P1 — look-first
**WHEN:** about to render, compare against, or describe ANY published artifact (figure, table,
contour, cutflow).
**DO:** 1. Extract the actual artifact (`fetch_figures.py --figure N`, `hepdata_fetch.py`) — not
its caption, not your memory of similar figures. 2. LOOK at it (Read the image). 3. Enumerate its
visual/structural grammar (axes+scales, binning, marker/band conventions, panel structure) into
the figure contract BEFORE building the counterpart.
| Thought | Reality |
|---|---|
| "The caption tells me what the figure shows" | Captions omit the visual grammar — the RS1 Fig-3 color map was rebuilt as a smooth heatmap from its caption and looked "absolutely nothing like" the real sparse blocky lattice (A1). |
| "I know what an exclusion contour looks like" | You know what a GENERIC one looks like. The published one has a specific form, and the physicist compares against THAT. |
**Worked incident:** A1 (caption-imagined figure) — the figure was rejected twice before the artifact
was actually extracted and looked at.

## P2 — basis-manifest
**WHEN:** about to compare ANY two numbers (or curves) where one side is published — limits,
cross-sections, acceptances, yields, significances.
**DO:** 1. Write BOTH sides' conventions explicitly: states summed (charges? flavors? L/R?),
perturbative order + PDF, inclusive-vs-tagged sample, expected-vs-observed column, per-channel vs
combined, and the σ the limit is normalized to. 2. REFUSE the comparison until the two manifests
match (transform one side; record the transformation). 3. Verify with an identity check where one
exists (on the published exclusion contour, UL/σ_model ≡ 1).
| Thought | Reality |
|---|---|
| "Both are 'the cross-section limit', just divide" | Ours was on the ISR-tagged 6-state SAMPLE σ, ATLAS's on the inclusive 4-state MODEL σ — a mass-dependent ×0.56→×1.01 spurious tilt that inflated the headline residual 33% vs the real 26% (A4). |
| "Expected, observed — they're within a band anyway" | Pair like columns and contour roles (A3). Pin the reference role from primary data; a caption or dot style may not specify it. |
**Worked incident:** A4 (σ-comparison-basis) — caught only by the UL/σ_model=1 on-contour identity
(measured 1.10 on the right basis; 1.47/0.74 on wrong ones).

## P3 — trap-sweep
**WHEN:** routing any new analysis/model pair (step 2), and again before generation (step 3).
**DO:** walk `docs/workflow/checklists/physics-traps.md` top to bottom; for each trap answer its CHEAP CHECK;
any hit becomes a numbered CHECK-IN flag with the trap's named route consequence. Never route by
similarity to the last analysis.
| Thought | Reality |
|---|---|
| "It's a resonance search, overlay a Breit-Wigner" | A ~343 GeV A/H→tt̄ signal interferes with SM tt̄ — the signature is a peak–DIP; a naive bump limit is invalid (trap T1). |
| "The paper's model is close enough to the request" | µ–M₂ with M₁=M₂, tanβ=50 is a MIXED wino–bino–higgsino sector, not the paper's pure-higgsino simplified model — σ×BR AND A×ε both move (trap T3). |
**Worked incidents:** a mixed-sector request read as the paper's simplified model (trap T3); a
named shape-fit refusal in place of a silently wrong counting product (trap T5).

## P4 — anchor-chain
**WHEN:** any produced number is about to be used downstream (σ, A×ε, yield, µ₉₅).
**DO:** 1. Before using it, obtain an INDEPENDENT order-of-magnitude anchor (WG σ tables, the
paper's own quoted σ·A×ε, HEPData yields, an SModelS r-value). 2. If |ratio−1| is outside the
regime you can name a reason for, STOP and run P5 — do not proceed hoping it averages out.
3. Record number+anchor+ratio in the run (the verify-pack traces them).
For novel quantities without a published value, seek independent limiting cases, dimensional
checks, sum rules or a genuinely independent calculation. State what each check can establish.
If a needed anchor remains unavailable, hold the dependent numerical claim and design a bounded
test; the missing expected answer does not prohibit hypothesis generation or independent work.
| Thought | Reality |
|---|---|
| "MadGraph ran clean, the σ is what it is" | 59.9 fb vs the 24 fb anchor was not parsing noise — the card prep had silently dropped ptj1min=50 (B2, a ×2.14 normalization error caught BY the anchor). |
| "The fit converged, µ₉₅ is fine" | A converged fit on a floored bracket returned obs_limit=1.0 exactly — an artifact, not a limit (B1). Anchors catch what convergence flags don't. |
**Worked incident:** B2 (ptj1min drop) — found because the anchor disagreed, not because anything
errored.

## P5 — discrepancy-decomposition
**WHEN:** two numbers/curves that should agree, don't (beyond stated tolerances).
**DO:** 1. Enumerate EVERY candidate cause you can name (basis, normalization, acceptance,
statistics, implementation, reference-decoding). 2. Rank by the CHEAPEST discriminating test, not
by prior plausibility. 3. Run tests in cost order; each test kills or confirms a cause; STOP at
the first confirmed cause, subtract it, re-measure the residual, repeat. 4. The final statement
decomposes the discrepancy into named parts + an honest irreducible remainder.
| Thought | Reality |
|---|---|
| "It's probably statistics, regenerate with more events" | The 33% residual decomposed into a σ-basis artifact (0…−44%, mass-dependent, fixed by a re-normalization costing NOTHING) + a genuine 26% acceptance/fast-sim floor. Regeneration would have spent hours and explained nothing. |
| "One cause explains it" | Discrepancies are usually sums. Subtract the confirmed cause and LOOK at what remains before declaring victory. |
**Worked incident:** the 33% → (basis + 26%) decomposition on the fig3 scan (A4 + RESULT.md §7).

## P6 — source-ladder
**WHEN:** required information is missing (efficiencies, cutflows, likelihoods, model files,
generator settings).
**DO:** climb in order, recording each rung's outcome in `inputs/resource_census.json`
(`resource-sweep` skill automates rungs 1–5): 1. the paper body + auxiliary material; 2. HEPData
record INCLUDING the resources tab (full likelihoods and efficiency maps live there, not under
"tables"); 3. the collaboration's public analysis code/glance pages + GitHub orgs; 4. recast DBs
(Rivet, SimpleAnalysis, SModelS, CheckMATE, MA5-PAD); 5. INSPIRE forward-citations — recast papers
and THESES (theses carry the cutflows the paper cut); 6. ask the physicist WITH the ladder's
evidence + named options. Never invent the missing number; never stop at rung 1.
| Thought | Reality |
|---|---|
| "The paper doesn't provide it, so it's unavailable" | An analysis's public code repository went unread for weeks; HEPData full tables were declared "impossible to download" until a second pass found the working endpoint in minutes. |
| "I checked HEPData" | You checked the TABLES. The resources tab is where reinterpretation material lives. |
**Worked incident:** the HEPData-download "limitation" and the unread analysis repository.

## P7 — conservative-default
**WHEN:** an assumption must be made within the approved scope, including an authorized
delegated decision or a site that says proceed-with-flag.
**DO:** 1. For an exclusion, prefer a demonstrably weaker claim where the direction of the
effect is established. For a measurement, parameter fit or research comparison, retain
alternative assumptions and propagate their effects on the requested quantity; a smaller
number is not automatically conservative. Do not infer a bias sign without evidence.
2. Implement it REVERSIBLY (a config/
normalization knob, never baked into generated events when avoidable). 3. Flag it numbered in the
check-in + `DEVIATIONS.md`, with the expected sign+size of the bias.
| Thought | Reality |
|---|---|
| "LO σ is the conservative choice" | Not automatically: for the squark cases k<1 (LO-PDF overshoot) — bare LO OVER-excluded. Conservative means you CHECKED the sign, not that you picked the lower-order option. |
| "It's a small effect, no flag needed" | Unflagged assumptions are how 2% effects get stacked five deep into a 15% surprise. The flag costs one line. |
**Worked incident:** the flat k=1.18 → per-mass k(m)=1.38–1.41 fix moved the contour OUTWARD —
the "safe" LO-ish choice had been anti-conservative the whole time.

## P8 — kill-the-result
**WHEN:** a result is drafted for delivery (final check-in, RESULT.md, deck) — ALWAYS, as step 9.
**DO:** before the verification panel sees it, argue your own result is wrong three specific ways:
1. BASIS — which convention mismatch would produce exactly this agreement/disagreement? 2.
ACCEPTANCE — which selection/object/detector shortcut would fake it? 3. STATISTICS — which
floor/cap/stat-fluctuation would fake it? Write the three attacks + why each fails (or doesn't) —
they seed the Tier-B adversary, which walks the failure catalogue as its attack list.
| Thought | Reality |
|---|---|
| "It matches, we're done" | The 141/141 "bit-faithful" SA port matched because it was RJR-CIRCULAR — it read R_ISR from the container it claimed to reproduce. An adversarial pass found it; the agreement was the disguise. |
| "The panel will catch anything I missed" | The panel is a NET, not a substitute — a drafted attack list is what makes Tier-B sharp instead of ceremonial. |
**Worked incident:** the RJR-circularity catch; the panel's number-integrity rule (quoted-number
vs artifact discrepancy = automatic FAIL) exists because prose drifted from artifacts twice.

---

## Using these under the model-tier policy
The [judgment] policy (`docs/workflow/README.md` §Roles) still binds: a cheap model's job at a judgment site
is to RUN the protocol mechanically (extract, manifest, sweep, anchor) and present the structured
evidence. Manual mode escalates unresolved scientific judgments to the physicist. An explicit
delegation recorded through `docs/workflow/start.md` instead uses the authorized scientific
reviewers and coordinator within the declared scope, resources and correction bounds. CI2 and
CI3 review remain independent; neither the protocol nor a machine approval establishes expert
human review. Escalate unavailable required expertise and decisions outside the delegation.

## Finding classification and bounded repair

New review findings use `findings.v2`; it also accepts unchanged version 1 documents.
Version 1 findings remain unclassified and retain their prior routing. For a defect,
`classification` contains `kind: defect`, the reviewed `artifact_sha256`, one `target`
step or node, and `rework_evidence` explaining why its repair changes the result.
For a limitation it contains `kind: limitation`, the reviewed `artifact_sha256`, and
`claims` with each `claim_id`, `effect` (`bounds` or `invalidates`) and `bound` (or
`unbounded`). Severity and evidence authority remain separate from classification.

`ravel agent-graph rework --graph <graph> --findings <document> --reason <reason>`
repairs exactly the named defect nodes and their descendants. `--nodes` must match
those targets if supplied. Limitations enter the retained limitation census and
claim disposition without spending rework budget, even when the budget is exhausted.
The old `--nodes` interface is reserved for legacy unclassified/manual repairs.
Repeated objections against unchanged artifact bytes do not spend another repair.
Scientific findings use the same classification fields alongside their located
journal evidence; a defect names its owning execution stage or a domain-mapped phase node.

Use `ravel review --rundir <run> reclassify --request <json>` for an open journal finding: the declared
decider supplies a reason and replacement classification; the original vote and
classification remain in the hash-chained journal. Reclassification grants no new
execution authority. A limitation-only send-back does not authorize correction;
the decider must explicitly accept a permitted supported scope before delivery.
A decider send-back must carry a defect, and no reclassification may leave an
acceptance carrying a defect or a decider send-back without one.
Acceptance may carry limitations. Each bounded affected claim must be qualified
or withdrawn; invalidated or unbounded claims are withdrawn. The actual manuscript
claim census and its visible reasons must retain these effects. Honest withdrawal
of a headline claim permits delivery of the negative result without regeneration.
Research methodology status and its census handoff include these journal limitations.

Journal defect targets must name an allowed owning stage when submitted as well as
when reclassified. Each review policy claim scope may explicitly list `claim_ids`;
without that field its own scope identifier is the claim identifier. A limitation
must name a claim in this policy census. Historical unbound findings remain readable
but cannot pass delivery as if their scope had been established.

For every delivery route with retained limitations, the accepting decider supplies
one existing full claim-disposition package (`plan`, `rows`, `value`, `evidence`)
among its pinned `supporting_artifacts`. Its literal final prose must retain every
required qualification or withdrawal. The journal retains the bounded package bytes
so live, detached and retained review checks can enforce the same rule. In ordinary
role orchestration the package can be an explicit source-bound case anchor, which
is forwarded to review support. A generated summary does not replace this witness.
The accepted scope cannot contain a withdrawn or unresolved claim; a separate
diagnostic scope can still deliver a supported negative result after headline withdrawal.

## Progress, bounded endings and unattended waits

A redo must change the cited artifact bytes or the affected check result. The review
journal compares the retained evidence/check values across correction cycles; changed
settings, a new attempt identifier and a restated finding are not progress. After two
consecutive unchanged redos, status supplies a `limitation_candidate` with the original
finding and correction history for the decider. It does not reclassify the finding or
accept a claim. The existing stricter refusal of a repeated classified defect on the
same bytes remains. Repeated refused graph requests also retain a decider handoff,
without invalidating nodes again or consuming model calls.

Use `ravel status --rundir "$RUN"` to read per-stage redo counts, the last accepted
review-cycle timestamp, elapsed seconds and any human wait. No accepted progress is
reported as unknown, rather than as the time of a failed attempt. A wait states
`WAITING FOR A HUMAN since <time>: <reason>, <what is needed>`; repeated reads preserve
the start time. A recorded escalation blocks later acceptance/compute use of that
cycle; historical receipts remain intact.

An explicitly configured local notification command is optional:

```sh
ravel status --rundir "$RUN" --notification-command '["local-notifier"]'
```

The command receives two additional arguments: the run path and a one-line reason.
It runs without a shell, inherited stdin or default network action. It receives no
request text, findings or scientific data. Each explicit invocation can notify once;
status alone sends nothing. The command's success is not run approval.

When bounds are exhausted or the review escalates, produce a qualified ending:

```sh
ravel task-completion qualified --rundir "$RUN"
```

This writes `outputs/completion/qualified-delivery.json`, a located boundary record
and an appended `DEVIATIONS.md` entry. Every original obligation is stated as
`satisfied`, `negative`, `partial` or `blocked`. The optional `--request` is an existing
completion request: its contributions must pass the ordinary current child-evidence
and review checks. Without such a request the conservative ending marks every
obligation blocked. It preserves unresolved findings and limitation candidates.
Limitation-affected claims are withdrawn through the shared disposition contract.
An optional `--claim-package` supplies the existing plan/rows/value/evidence document
shape; every planned claim must be withdrawn with its literal final scope and reason.
No new scientific claim is adopted by this fallback.

A valid delegation is labelled `machine-produced under delegation`; otherwise the
artifact is a machine-produced status summary. Neither label authenticates a human
or approves anything new. The ordinary final-delivery and execution gates remain
closed. Escalation and exhausted defect-review or correction-failure mutations
automatically attempt this ending after committing the journal event. Exhaustion
includes the two-unchanged-redo bound even when numerical redo capacity remains.
That bound keeps the existing decider route; reporting does not reclassify a
finding, spend another redo, add an escalation or declare a human wait.
Their responses include `qualified_ending` with `recorded` or `unavailable` status
and a repair reason when unavailable; the review CLI exits unsuccessfully for an
unavailable report. Reporting failure preserves the terminal event and its refusal.
An identical escalation retries reporting without adding another journal event.
The publication lock is acquired before observing the report's source custody,
which is checked again immediately before final publication. Failed publication
restores prior reporting bytes where they still match this attempt; separate edits
are preserved and an incomplete restoration is reported. This is not a transaction
across arbitrary concurrent writers or a crash-atomic update of multiple files.
Status remains observational; use the explicit command above for an older terminal
journal or to supply an existing completion request. Upstream execution consumers
must retain the returned reporting metadata to expose a publication failure.

## Evidence obligations and exploration

An RDJ node may declare a nonempty `evidence_obligations` list of required anchor
kinds. A branch closes when externally verified evidence of each required kind
supports its obligated node; it need not reach the class's minimum depth. Untyped
branches retain their minimum-depth rule. The maximum depth, edge reviews, unknowns,
common-source checks, alternatives and transport requirements still apply. Low
confidence or weak reviewed support requires additional distinct sources for each
kind. Identical content counts once across paths, producer receipts and acquisition
routes; copying evidence cannot discharge an additional-evidence requirement or
hide shared support across claims. Different bytes alone do not prove independent
scientific provenance. Contradictory external evidence keeps a typed branch held until resolved.
The highest risk class still needs a tool-output or measurement anchor on each path.

Retrieved evidence must join an authenticated acquisition receipt, exact content
bytes and a UTF-8 excerpt at declared byte offsets. Practice authority additionally
requires a separately pinned, independently supplied `scientific-practice-reference`
descriptor joining the exact source identity, full content digest and a policy source
category. A citation or proposer-authored category is not authority. Provenance and
source type do not prove applicability; reviewers still judge the claim.

A bounded unfamiliar choice can use an explicit exploration-only RDJ case. The
supplied `rdj-exploration-contract` binds the exact `research_choice` /
`screening_choice` action digest, hypothesis, question, expected outputs, stop
condition and finite broker/model bounds under current policy. Set the action's
`authorization_scope` to `exploration_only` and pass the independent contract pin to
`open_case`. Every reviewer sees that contract. The receipt authorizes the selection
only, explicitly denies execution and scientific acceptance, and retains the full
risk class and its reviews. It cannot be reused for launch, promotion or delivery,
and does not establish the route as accepted practice. Executing any experiment
still needs the ordinary execution authorization and resource accounting.

Current same-gate decision reuse revalidates the action, evidence, class, scope and
policy and spends no additional model calls. An accepted route whose source evidence
changed no longer suppresses the novelty trigger. Supplied action pins must identify
the same current subjects as the accepted case; another path with identical content
does not inherit its review. An explicitly changed route requires review even when
both routes already have the highest risk class. Existing callers that supply only
the action digest retain their current case-custody checks.

Cross-gate reuse is explicit and bounded. Before the source review, supply an
independent `rdj-review-scope` input with `schema_version: 1`, a scope and regime,
canonical `compatible_gates`, the exact action (`kind`, `summary`, `digest`, `pins`)
and nonempty `semantic_inputs` pins to independently supplied JSON. Pass that pin
as `review_scope` to `open_case`; all reviewers see the complete compatible gate set,
semantic content, input hashes and actual policy/card contracts. A later
`open_case(..., review_scope=pin, reuse_from=receipt_id)` creates its own scoped case.

Only equal effective gate obligations, unchanged decision/evidence/regime/input
digests, the same proposer and a clean accepted bundle permit reuse. Original
transport outputs and source authority are reverified. The shipped `delivery` and
`final_task` review contracts form a compatible pair; each still runs its own ordinary
execution, completion and human-approval checks. Human approval does not transfer.
Changed context, risk, policy, cards or typed obligations removes reused verdicts
and requires current review. Legacy, exploratory, revised or finding-bearing bundles
receive no cross-gate review credit. The new receipt records its source lineage;
the old receipt never gains another gate.

Cost policy records absolute cost, declared budget fraction, irreversibility and
scientific consequence separately. The existing positive-spend risk floor is
preserved. A budget number or fraction alone does not prove authorization and never
lowers risk. The fractional threshold remains unset pending an owner decision.

## Executable reviewer checks

A tightening rubric overlay may add `executable_checks` for named reviewer roles.
Each check binds an existing permitted document-validator identifier, an exact
run-relative subject pin, an optional producer broker-receipt pin and whether a
distinct method is required. The review approval binds these obligations. Removing
or changing them after approval refuses review credit.

Credit requires the reviewer's own broker execution against the dispatcher-pinned,
unredacted subject in its review packet. The current input and result bytes must
match their receipts. Missing, failed, inconclusive or empty checks do not earn
credit. A later check of the same subject that raises, or broken later worker
custody, cannot retain credit from an earlier pass. Completed checks identify their
subject through normalized input pins, including equivalent path spellings.
A later validator exception without a subject pin also holds credit when its
argument digest differs: the digest alone cannot exclude another spelling of the
same path. A completed check with a pinned different subject leaves prior credit intact.
A declaration or self-reported check is insufficient. Existing review
requirements remain in effect when no overlay is selected.

The receipt report separates actor independence from authenticated callable
identity. It records `same_callable`, `distinct_callable` or `unknown` by comparing
the registered module and function in producer and reviewer executions on the same
subject. A different callable does not prove an independent scientific method;
`scientific_independence_proven` remains false. `method_independence` stays
`unverified` until an authenticated checker contract establishes an independent
computation of the same quantity. The current registry supplies no such relationship,
so `require_distinct_method` remains an open requirement. Producer diagnostics require
one current matching subject input and one correctly identified, substantive passed
output. A passed label with material findings cannot earn reviewer credit.
These checks currently use existing
document validators. The existing `review.normalization_recompute` check independently
recomputes the scalar yield from supplied cross section, luminosity, branching fraction,
correction factor and efficiency; a wrong yield or missing input refuses credit.
This checks arithmetic, not the applicability of those inputs or event-level closure.
It does not authorize native execution. The registered likelihood comparison can
compare supplied frozen-point values through the same packet and broker path; this
does not authenticate their producing engines or independently recompute a model.
Specialist point credit needs its consumer to enforce these rubric obligations.
Run-only cut checks still need a transitive-source contract before they can satisfy
an executable document obligation. Independent model recomputation and verified
method relationships remain separate integration work.

## Selectable investigation team

A graph may opt into `team_shape.policy = investigator_consult_reviewer`, naming one
investigator node, non-voting consultations (each with its specialty), and one blind
reviewer for each declared consequential subject. The policy censuses every agent,
requires the reviewer to depend on its subject, and refuses hidden agent populations
or a changed team arm during revision. Its ordinary graph budgets and fresh-context
review transport checks remain active. Omission selects the existing team behavior.

This is an advisory investigation-scheduling arm for ablation. It does not delete or
replace the mandatory reviewers required by a scientific decision gate. Graph
completion remains separate from scientific acceptance and execution authority.
