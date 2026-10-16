# Recursive Decision Justification

Recursive Decision Justification (RDJ) is the procedure by which RAVEL decides whether a consequential action
proceeds. An agent that proposes an action must answer a chain of "why" questions. Each answer
must itself be justified, recursively, until every branch ends in evidence that RAVEL can verify from bytes it
holds. Independent reviewers judge each step of the chain, and code, never an agent, issues the authorization.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/methodology-decision-justification.svg">
  <img src="../figures/svg/light/methodology-decision-justification.svg" width="100%" alt="Recursive Decision Justification. A proposed action is the root of a justification tree. Code asks why the action should be taken; claims support it, an alternative is recorded as chosen over, and each claim is asked why it should be believed until every branch ends in a verified anchor such as a tool output, a measurement, an input file, a quoted user requirement or a registered invariant. An edge reviewer judges every hop, a critic files findings, the proposer revises, and a verifier resolves each finding. Code then authorizes, gathers evidence or escalates, and writes a receipt. Every step is appended to a hash-chained custody ledger held outside the run.">
</picture>

## Terms

- **Action.** A concrete step at a gate: approving a plan, launching a scan, accepting the CHECK-IN 2 evidence,
  promoting a research candidate, delivering a result. An action is identified by its *action digest*: the
  SHA-256 of the one artifact it acts on, or, for several artifacts, a canonical digest of their pins (path and
  SHA-256) sorted by path.
- **SHA-256.** A cryptographic hash: a 64-character fingerprint of a file's exact bytes. Changing any byte
  changes the fingerprint, so a recorded SHA-256 shows that a file is the one that was checked.
- **Gate.** A point in the workflow that refuses to proceed without a current authorization for the action
  digest in front of it.
- **Case.** The record that justifies one action: the justification tree, its anchors, the reviews, the critique,
  the revisions and the verification.
- **Anchor.** A piece of evidence that RAVEL checks against bytes it holds, independently of the agent that cites it.
- **Custody.** Append-only, hash-chained ledgers that RAVEL keeps outside the run directory.

## Risk classes

Code assigns each action one of four risk classes, R0 to R3. The gate sets the base class; the action kind,
irreversibility, a scope change, a method new to the run and high consequence (50 or more points, 8 or more
hours of wall time, or any spend) raise it. A launch whose kind is a dry run, a smoke launch, a single-point
launch or the reuse of an accepted stage can be lowered below the gate's class, unless a consequence fact fires
or the launch is a bulk or scan launch. The class fixes how deep the justification must go and who reviews it.

| Class | Required depth | Reviewers | Revision rounds | Independence | Model calls | Typical gates |
|---|---|---|---|---|---|---|
| R0 | 1 | none | 0 | none | 0 | dry and smoke runs, reading an index |
| R1 | 1–2 | edge reviewer | 1 | self-attested allowed | 6 | screening choices, feedback on a failed stage |
| R2 | 2–5 | edge reviewer, critic, verifier | 2 | transport-attested or human | 24 | CHECK-IN 1 plan, launch, CHECK-IN 2, corrections, deviations, promotions |
| R3 | 3–7 | edge reviewer, critic, verifier | 3 | transport-attested | 40 | delivery, final task, report integrity, export, unblinding, spend above the ceiling, method-performance claims |

R2 and R3 also require a recorded alternative: the case must say what else was considered and why it was not
chosen. R3 requires that every supporting path reach a tool output or a measurement. Export, unblinding and
spend above the ceiling are irreversible, so they also require a recorded human approval of the case. A run has
a budget of 200 model calls for RDJ, 80 per action, and at most 3 cases per action.

## The justification tree

A case is a directed acyclic graph rooted at the action.

| Element | Kinds |
|---|---|
| Node | `action` (the root, exactly one), `claim`, `assumption`, `alternative` |
| Edge | `supports` (child establishes parent), `chosen_over` (an alternative to the action), `rules_out` (a claim that eliminates an alternative) |
| Anchor | tool output, measurement, input artifact, user requirement, invariant, retrieved document, external fact |

Each node carries an assertion, a short rationale, a confidence (low, medium or high), its anchors, its
assumptions and any open questions. A node that is material to the decision cannot be supported by a
non-material one.

**Recursion.** Code generates every question; the proposing agent answers. The first question is *Why should
this action be taken?* Each answer becomes a child node, and code then asks of it *Why should this be believed?*
For each edge the reviewer is shown the exact question *Why does "child" establish "parent"?*, or *Why was this
action chosen over "alternative"?* The tree grows until every branch closes.

**When a branch closes.** A node can declare typed `evidence_obligations`: required anchor kinds.
A branch can close at any depth when externally verified evidence of each kind supports its obligated node.
Low confidence or weak support requires additional distinct evidence sources. Identical content counts once
even under different paths, receipts or retrieval routes; distinct bytes alone do not prove scientific
independence. A conflict stays held until resolved. The class maximum depth remains an upper bound. Without typed obligations, a leaf closes when it
holds a verified external anchor at the required depth, with three exceptions. At R0 and R1 an invariant alone cannot ground a leaf. A path with a hop the edge reviewer
judged *generated_only* stays open. At R3 the path needs a tool-output or measurement anchor. The
required depth is the class minimum plus one for each sign of weakness on the path: a low-confidence node, two
anchors that report different values for the same quantity, a partial *entailment* (the child establishes part
of the parent), a weak relevance, or a hop that needs more grounding. At the class's maximum depth an unclosed branch is recorded as unresolved. An open
question on a node holds its branch until a queued evidence item answers it with files that verify.

**What counts as evidence.** Code, not the proposer, sets each anchor's status.

| Anchor | Verified against |
|---|---|
| Tool output, measurement | A stage receipt in the execution ledger, registered in custody, that lists the output with this SHA-256 and names as producer a recognised RAVEL module, a physics tool in RAVEL's native build, or a script inside the run whose executed bytes the stage pinned (`script_sha256`). A measurement also names a registered validator. |
| Input artifact | The input snapshot taken in custody at run start and at CHECK-IN 1. |
| User requirement | A character span of the recorded request, CHECK-IN 1 response or steering text that matches the quoted text exactly. |
| Invariant | An entry of the shipped invariant registry, for example "an exclusion is never reported as a discovery" or "no event generation before CHECK-IN 1 approval". |
| Retrieved document, external fact | An external fact bound to a reference-data record is checked as an input artifact. A retrieved excerpt must match the exact content and byte span authenticated by the acquisition ledger. |

Files an agent wrote, board posts, RDJ's own records and review verdicts are *generated*: they can be cited but
never close a branch. An anchor that points at the action's own bytes, or at the output of the stage that produced
the action, is *circular* and invalid. Reviewers see the value read from the verified bytes, never the value the
proposer typed. At R3 and at the delivery gates, two unrelated claims that rest on one shared source are flagged
as a common-mode dependence.

**Authoritative-practice grounding.** At R2 and above, a claim that recommends an analysis choice (a cut, a
method, a tolerance) needs an *authoritative-practice anchor* in its support: your recorded words, a registry
invariant marked as practice, or acquired content whose source type is joined to an independently supplied,
pinned scientific-reference descriptor. An arbitrary citation cannot establish this authority.
Without one the claim stays *exploratory*. An explicit bounded exploration contract for broker operations can authorize
selection of that research choice with the same class reviews, while denying scientific acceptance and
execution. It cannot authorize launch, promotion or delivery; those retain their own gates.

## The review loop

Three reviewer roles act on the tree. Each differs from every author; the independence rules below say when
they share a session.

1. **Edge reviewer** (`rdj-edge-reviewer`) judges one hop at a time: *entailment* (holds, partial, fails),
   *relevance* (relevant, weak, irrelevant) and *grounding* (anchored, needs depth, generated). A hop that
   fails or is irrelevant blocks the case until a revision changes it.
2. **Critic** (`rdj-critic`) reads the whole tree and files findings from a closed list: unsupported claim,
   missing evidence, alternative not considered, contradiction, risk underestimated, chain stopped early, decision
   does not follow, self-grounding, unmarked choice, circular justification, irrelevant support, post-hoc
   rationalisation. Each finding has a *materiality*: A or B marks a finding material to the decision, C a
   finding that is not. Each finding also has an *evidence class*, the kind of support it rests on: a new
   receipt, a code check, a citation or an opinion. A finding blocks when it is material (A or B) and either rests on
   a new receipt or a code check or requests evidence or an experiment; any other finding is recorded as advisory.
3. The proposer **revises**, naming the findings it addresses. Each revision records the content before and after.
4. **Verifier** (`rdj-verifier`) marks each finding resolved, unresolved or a new issue, and returns an outcome.
   It cannot add findings, and it cannot resolve a blocking finding that no revision addressed.

Every node and edge carries a *Merkle digest*, a hash that covers its own content and the digests of everything
below it, so a change anywhere underneath changes it: a node hashes its content, its anchors and its outgoing
edges, and an edge hashes its parent's content and its child's digest. A review binds the edge digest, so any change at or
below a hop invalidates that review and the hop is judged again. The critique and the verification bind the
digest of the root.

**Requests for evidence.** A finding, a blocking review or an unresolved branch can request work. Each request
becomes an item in the evidence queue and is routed by kind: *evidence* to an investigation worker, *experiment*
to the research cycle, *requirement clarification* to a question at the next check-in. An item closes as done
with files whose SHA-256 verifies; a requested test closes with a verdict that upholds or refutes the finding.

**Decision.** Code computes the outcome from the case as it stands:

| Outcome | Condition |
|---|---|
| `authorize` | Every branch closed, every hop reviewed and unblocked, every blocking finding resolved, the attestation sufficient for the class |
| `gather_evidence` | What remains open is unresolved branches or pending findings that new evidence can close |
| `escalate` | The revision or call budget is spent, or the verifier escalates; the decision goes to the physicist |

An authorization writes a receipt that binds the case digest, the action digest, the gate, the class, the
attestation summary and the policy digest. The gate accepts the receipt for that action digest and no other.
An authorized change to a tuning parameter, or a deviation, also appends a row to the run's `DEVIATIONS.md`.

## Independence

Role identity comes from receipts that the host writes when it dispatches a worker, not from what a model says
about itself. Each actor is labelled *transport-attested*, *host-attested*, *self-attested* or *human*.

- The edge reviewer differs from every author, the critic and the verifier.
- The critic differs from every author, edge reviewer and verifier.
- The verifier differs from every author and edge reviewer. At R3 it is a session distinct from the critic's; the
  policy can also require a different *model family* (the vendor family of the model, read from its
  identifier), and the shipped policy leaves that off. Below R3 a verifier in the critic's session needs a recorded
  human approval of the case and is labelled self-attested.
- The critic and verifier receive a digest-bound projection of the case with reviewer reasons withheld.

A human approval enters as a custody record that quotes the physicist's CHECK-IN 1 response or steering text,
recorded after the case was opened, naming the case or the first 12 characters of its action digest.

## Custody

Custody is kept under the RAVEL machine state directory, keyed to the run identity, outside the run directory
that agents write to. Each ledger is a JSON-lines file. Every line holds a sequence number, the digest of the
previous line, a timestamp, the record and its own SHA-256 over all of these. Reading a ledger re-verifies every
line, so an edited line, or a deleted line with lines after it, breaks the chain at that point. The chain alone
does not detect lines cut from the end; for a decision case, the journal replay below checks the case against its
last saved digests.

The ledgers record input snapshots, user text, approvals, acquisitions, check results, worker and host
registrations, stage receipts, roles, cases, receipts and one journal per case. The first journal event of a case
is its proposal, committed before any question is asked. Each later save of the case is journaled by digest.
When a case is loaded, its run copy is replayed against the journal: the proposal, the policy digest and the last
saved digests must match, and the class must be at or above the committed one. Any difference marks the case *tampered*.

## Auditing a result

A reader can walk any authorized action back to its inputs.

```bash
ravel rdj status --rundir RUN                    # every case, its class, phase and the call budget
ravel rdj case --rundir RUN --case-id CASE       # the stored tree, reviews, critique and verification
ravel rdj check --rundir RUN --case-id CASE      # recompute support closure, critic basis and common-mode anchors
ravel decision-case --case RUN/rdj/cases/CASE.json   # replay every rule; exit 1 unless the latest receipt authorizes this exact case
```

From the case, each tool-output or measurement anchor names a stage receipt, an output path and its SHA-256;
the stage receipt names the producing command and its inputs; the inputs appear in the custody snapshot taken
at run start or CHECK-IN 1. The other anchors bind an input snapshot, a span of recorded user text, an
invariant-registry entry or a supported source record.
Research decisions follow the same path: every screen, promotion and selection in the
[research loop](research-loop.md) carries the receipt of its case (R1 for screening, R2 for promotion and
selection, R3 for a method-performance claim).

## Records

| Record | Location |
|---|---|
| Case, loop state, readable journal | `rdj/cases/`, `rdj/state/`, `rdj/journal/` in the run |
| Receipts | `rdj/receipts/<case>-<n>.json` in the run |
| Evidence queue | `rdj/queue/` in the run |
| Custody ledgers and content blobs | RAVEL machine state, outside the run |
| Policy and invariants | `src/ravel/data/rdj/policy.json`, `invariants.json` |

Implementation: `ravel.workflow.rdj_loop` (cases, questions, roles, authorization), `rdj_anchor` (anchor
verification), `rdj_custody` (ledgers), `decision_case` (schema, Merkle digests, replay), `evidence_queue`.

## Glossary

| Term | Meaning |
|---|---|
| Action digest | SHA-256 of the one artifact an action acts on, or a canonical digest of its sorted artifact pins |
| Authoritative-practice anchor | Your recorded words or a practice invariant; required at R2+ for a claim that recommends an analysis choice |
| Anchor | Evidence RAVEL verifies from bytes it holds |
| Case | The justification record of one action |
| Common-mode dependence | Two unrelated claims resting on one shared source |
| Custody | Hash-chained, append-only ledgers outside the run |
| Edge review | A judgement of one hop: entailment, relevance, grounding |
| Entailment | Whether a child claim establishes its parent: holds, partial or fails |
| Evidence class | What a finding rests on: new receipt, code check, citation or opinion |
| Materiality | A or B for a finding material to the decision, C for one that is not |
| Merkle digest | A hash over a node's or edge's content and the digests below it |
| Generated evidence | Agent-written material; citable, never closes a branch |
| Risk class | R0 to R3; sets depth, reviewers, rounds and independence |
| SHA-256 | A 64-character cryptographic fingerprint of a file's exact bytes |
| Transport attestation | Identity of a worker session established by the host that dispatched it |

See also the [RAVEL glossary](../reference/glossary.md), the [agent architecture](agent-architecture.md) and
the [research loop](research-loop.md).

## Economy and retained refusals

Same-gate reuse checks the current action and evidence again without another model call.
Supplied pins must match the accepted subjects, including their paths; identical bytes
at a different path do not transfer acceptance. An explicitly changed route requires
review even when its risk class cannot increase further.
Cross-gate reuse requires a supplied scope that every original reviewer saw, identical effective
review obligations and unchanged evidence, regime, input, policy and card digests. It creates a
new gate-specific receipt with source lineage and preserves current execution and human checks.
Changed inputs require fresh review. Absolute cost, declared budget fraction, irreversibility and
scientific consequence are recorded separately. The current positive-spend risk floor is
unchanged; a declared budget fraction is not authenticated budget authority, and its risk
threshold remains unset.

The advisory investigation graph offers an opt-in investigator/consultation/boundary-reviewer
team policy. Mandatory gate reviewers remain separate. This permits a scheduling ablation
without changing the default or removing a scientific refusal. See the
[judgment checklist](../workflow/checklists/judgment-protocols.md) for progress histories,
qualified endings, notification configuration and the executable contracts.
Reaching the two-unchanged-redo bound produces the same qualified report as numerical
budget exhaustion without changing the decider route. Executable review credit uses
the latest exact-subject check; a failed later attempt or broken worker custody cannot
retain credit from an earlier successful check.
