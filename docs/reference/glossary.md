# Glossary

The terms used in the [README](../../README.md) and the methodology pages, in alphabetical order. Each entry
links to the page that describes the term in full.

## Ablation

An experiment in the [research loop](../methodology/research-loop.md) that changes exactly one component of a
candidate method (removes, replaces or adds it) and holds every other input fixed. Ablations attribute a
measured gain to the component that produces it.

## Anchor

The end of a justification branch in [Recursive Decision Justification](../methodology/decision-justification.md):
evidence RAVEL verifies itself. Anchors are tool outputs with a registered stage receipt, measurements, input
files held in custody, your recorded words and shipped invariants. Agent-written text and review verdicts can
be cited, but they never close a branch; an anchor on the output of the step under decision is circular and
invalid.

## Approval scope

What an approval permits. At CHECK-IN 1 it is the largest compute plan the study can run, and never more than
the request asked for. On a driver-written plan the rungs are ordered as follows:

| Rung | Meaning |
|---|---|
| `none` | No compute: surveys and summaries of published results |
| `dry` | Render cards and configurations; no events |
| `smoke` | One point at small statistics: the CHECK-IN 2 waypoint |
| `full` | One point at full statistics, after the CHECK-IN 2 GO |
| `scan` | Every point of the declared grid, after the CHECK-IN 2 GO |

The meaning depends on the route. A scoped calculation planned from a specification (`ravel plan`) is approved
at `full`, which there means the complete calculation in one attempt, with no detector simulation or scan and no
CHECK-IN 2. A science-mode plan's approval binds that exact plan rather than a rung. A review's acceptance also names a claim scope: the uses its evidence supports. See
[check-ins](../workflow/checklists/check-ins.md) and the
[study specification](../workflow/reference/scoped-workflows.md).

## Authoritative-practice grounding

The support a claim that recommends an analysis choice (a cut, a method, a tolerance) needs at risk class R2
and above: an anchor holding your recorded words, or a registry invariant marked as practice. Without it the
claim stays exploratory and the decision case is not authorized. See
[Recursive Decision Justification](../methodology/decision-justification.md).

## CHECK-IN 1, 2 and 3

The three points where a study stops for a decision. CHECK-IN 1 approves the plan, its numbered assumptions and
its budget before any event generation. CHECK-IN 2 is the early verification: reviewers judge the first evidence
and the answer is GO or ADJUST. CHECK-IN 3 presents the final results and the whole task, reviewed by a fresh
panel, before delivery. A plan built from a specification has no CHECK-IN 2: its approval covers the run, and
its result review offers GO or ADJUST for the next proposal. You decide each check-in, or delegate three
actions to an agent within declared limits: plan approval, the CHECK-IN 2 GO and acceptance of a
recommendation. See [check-ins](../workflow/checklists/check-ins.md).

## Custody

Hash-chained ledgers kept outside the run directory, appended to and never rewritten. They record input snapshots, your recorded
words, approvals, check results, stage receipts, worker and role records, and each decision case with its
journal. Every load replays the journal, so an edited case is refused. See
[Recursive Decision Justification](../methodology/decision-justification.md).

## Deviation

A change to the approved plan. It is reported at once as its own message and recorded in the study's
`DEVIATIONS.md`, with the check-in it affects. See [check-ins](../workflow/checklists/check-ins.md).

## Driver agent

The coding-agent session you talk to. It holds the coordinator role: it reads the request, writes the plan,
dispatches work to other roles and presents each check-in. It does not review its own work. See
[agent architecture](../methodology/agent-architecture.md).

## Entailment

Whether a child claim establishes its parent claim in a justification tree. The edge reviewer records it as
holds, partial or fails; a partial entailment requires a deeper branch and a failed one blocks the case. See
[Recursive Decision Justification](../methodology/decision-justification.md).

## Evidence class

What a reviewer's finding rests on: a new receipt, a code check, a citation or an opinion. A material finding
that rests on a new receipt or a code check blocks a decision; a cited or opinion finding is advisory unless it
requests evidence or an experiment. See [Recursive Decision Justification](../methodology/decision-justification.md).

## Fidelity

How completely a research-loop cell reproduces the final evaluation. A screening cell runs on a declared subset
and cannot claim full fidelity; full-fidelity cells are the ones selection and the stop rule count. See
[the research loop](../methodology/research-loop.md).

## Generic controls

Everything an ablation holds fixed besides the mechanism under test: the candidate's held scientific inputs and
its other components. Holding them fixed attributes a gain to the mechanism. See
[the research loop](../methodology/research-loop.md).

## Hypothesis board

The shared board where research roles post hypotheses, predictions, rival hypotheses, evidence requests,
findings and refutations. Posting is sealed: every participant commits a digest before any hypothesis is
revealed. Code, not a post, changes a hypothesis's state. See
[the research loop](../methodology/research-loop.md).

## Hypothesis family

A named group of related hypotheses. The research loop's stop rule lists the families, and its coverage floor
sets how many of them need a full evaluation before a success stop. See
[the research loop](../methodology/research-loop.md).

## Materiality

The weight of a reviewer's finding on the decision: A or B for a finding material to it, C for one that is not.
A material finding can block; a C finding is advisory. See
[Recursive Decision Justification](../methodology/decision-justification.md).

## Merkle digest

A hash that covers an item's own content and the hashes of everything below it. In a justification tree a node
hashes its content, anchors and outgoing edges, and an edge hashes its parent's content and its child's digest,
so a change at or below a hop invalidates the review of that hop. See
[Recursive Decision Justification](../methodology/decision-justification.md).

## Mode

The science mode an operation runs under. A mode binds the operation to the module that implements it and to
the toolchain groups it needs; `ravel doctor` checks those groups. See [scientific studies](../workflow/reference/scientific-studies.md).

## Model family

The vendor family of a model, read from the model identifier a route reports. A role card can require a model
family different from another role's; the ML reviewer differs from the ML trainer. See
[agent architecture](../methodology/agent-architecture.md).

## Model tier

The class of model a role card requires: `judgment` for physics-judgment work, `agent` for tool work that is
safe to delegate, and `cheap` for the lowest-cost models. A route serves a card when one of its declared models
lists that tier. See [agent architecture](../methodology/agent-architecture.md).

## Operation

A typed unit of scientific work with declared inputs, outputs, tools, effects, cost and review checks. A plan is
a sequence of operations. The README's [family table](../../README.md#what-ravel-covers) counts the operations of
this release.

## Qualification

The recorded level a transport route has reached: declared, stub-tested, probed or live-qualified. A probe runs
the route's command-line help and confirms its flags; `ravel transport qualify` records a live conformance run on
this machine. A voting role refuses a route at the declared level, and a sandboxed command-line worker serves
blind roles after its live qualification. A probe does not establish sandbox isolation. A changed declaration, a
new probe or a replaced executable voids the record. See [transports](transports.md).

## Quorum

A join rule of a map node in the agent graph: `quorum:n` completes when at least *n* of its items succeed,
where `all` needs every item. See [agent architecture](../methodology/agent-architecture.md).

## Receipt

A record, written by code, of an effect: a stage run, a worker call, a model call or a decision. A receipt
states what ran, on which inputs and with which versions or models. Receipts record work; approvals come from
check-ins.

## Recursive Decision Justification (RDJ)

RAVEL's gate for consequential steps such as plan approval, launch, CHECK-IN 2 acceptance, delivery and export.
The proposing agent commits the action; code asks why it should be taken and why each answer should be believed,
recursively, until every branch ends in an anchor. An edge reviewer, a critic and a verifier review the tree;
code then authorizes the step, requests evidence or escalates to you, and writes a receipt. Risk classes R0 to
R3 set the depth, revision rounds and independence. See
[Recursive Decision Justification](../methodology/decision-justification.md).

## Research loop

The staged protocol for open-ended questions and method studies: a limitation census, two independent idea
streams, then experiments as baseline, screen, full run, withheld confirmation, and ablations and objection
tests. Each comparison is decided as better, equivalent, worse or unknown by a rule fixed in advance. Critique,
acceptance, meta-review and an integrity audit complete it. A plain reproduction or reinterpretation skips the
candidate-search and confirmation stages. See [the research loop](../methodology/research-loop.md).

## Reviewer

A role that judges evidence and votes. At CHECK-IN 2 each claim passes a physics critic, a skeptical verifier
and a physics decider; specialist reviewers join when a claim needs them. Reviewers run in fresh sessions,
separate from the driver agent. See [agent architecture](../methodology/agent-architecture.md).

## Run directory

The folder that holds one study: the request and its reading, the plan, approvals, inputs, outputs, figures,
reviews and working records. The custody ledgers that authenticate them are kept outside it, in RAVEL's machine
state. `ravel status --rundir` rebuilds its current state.

## SHA-256

A cryptographic hash: a 64-character fingerprint of a file's exact bytes. Changing any byte changes the
fingerprint, so a recorded SHA-256 shows that a file is the one that was checked.

## Stage

One supervised tool run within a study, such as event generation, showering, an analysis routine or a fit. Each
stage leaves a receipt.

## Study

One question carried from request to delivered result, in one run directory.

## Supervisor

The process that runs a stage. It enforces the stage's wall-time limit, stops a stage that exceeds it, and
writes a failure record that the investigation roles read. Log silence is not a failure signal; a stall limit
applies to a tool with a documented live progress stream when its caller sets one.

## Transport

The route a role's call takes: a hosted model API, a command-line agent session, a sandboxed worker process, a
sub-agent of the host, or a relay. Reviewer independence is a property of the transport, attested by a session
receipt for each call; a host's own sub-agent is host-attested at most and serves no voting or blind role. See
[transports](transports.md).

## Withheld confirmation

The confirmation stage of the research loop. Its data are disjoint from every input used for selection, and are
read after the selection is committed as a hashed record. Each withheld population is consumed once in a ledger
shared across the study. See [the research loop](../methodology/research-loop.md).

## Worker

A role that does scientific work, such as event generation, analysis code, models, fits or calculations. A
worker runs in a fresh session and its own workspace with a budget of turns, wall time, calls and cost, writes
to its own outputs, and the dispatcher writes its receipt. On a command-line route it runs inside an
operating-system sandbox; the route's isolation is recorded in the receipt.
