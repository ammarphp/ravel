# Incomplete research delivery and indexed native meta-review

The existing research cycle owns the journal, experiment denominator, cumulative
budget and scientific gates. These operations add useful progress reporting and
bounded material preparation. They grant no execution approval, scientific vote,
parent acceptance or measured research benefit.

## Progress before completion

Use the existing public command, including before an experiment is designed:

```sh
ravel research-cycle progress --cycle /absolute/campaign
```

The Python call is `research_cycle.progress_synthesis(campaign)`. It returns
`research_progress_synthesis`, a deterministic report text, every requested
quantity, every required and actually admitted experiment, the full staged
protocol, hypotheses/premises, current parent obligations, resource ledger,
actual Graph usage and outcome metrics. Failed, unknown, never-designed and
unissued entries stay visible. Previous accepted evidence is distinguished from
current scoped reuse. Zero accepted facts is a useful valid progress report.

An optional ordinary scientific-report recipe can select current accepted facts:

```sh
ravel research-cycle progress --cycle /absolute/campaign \
  --request /absolute/current-report-recipe.json --base-dir /absolute/input-base
```

Every fact must map to a applicable, scope-accepted experiment and the
exact requested output source. Equal numbers from a different source do not
substitute for that evidence. The existing artifact/report composer retains
coordinates, units and tool provenance. An exact existing parent-completion
request can expose actual child outcomes; otherwise all original parent
obligations remain open. The wrapper always returns `final_delivery=false` and
`parent_task_accepted=false`.

The existing final `synthesize` function and scientific-report/task-completion
gates are unchanged. Reporting incomplete work must not satisfy them. The fixed
report text bound refuses an oversized complete census instead of truncating it.
Current evidence and parent dependencies are checked again before return.

## Preparing complete native evidence with bounded presentation

Small workflows retain the default `presentation='inline'` behavior. For large
or binary native dependencies, explicitly use `presentation='indexed'` on
`research_protocol.context`, `prepare_host_request` or `prepare_meta_review`.
The context CLI accepts an optional strict JSON options document:

```json
{"presentation":"indexed","role":"critic","evidence_pages":[],"max_presented_bytes":2000000}
```

```sh
ravel research-protocol context --cycle /absolute/campaign \
  --request /absolute/options.json --out /absolute/fresh-context.json
```

A complete inventory authenticates the original question/context, parent,
protocol, premises, hypotheses, every experiment dependency and observed
receipt/result/review. Canonical failed-stage sources, returned files, missing
outputs, launch/runtime/ledger proofs and directory membership use the existing
ordinary validators. The new canonical-intake reader alone uses the existing
16MiB diagnostic bound; generic research declaration JSON remains limited to
2,000,000 bytes. A failed intake never grants accepted-scientific-evidence reuse.
Large canonical inputs are held transitively through their exact intake pin
rather than copying thousands of duplicate rows into a campaign declaration.

`research_presentation.inventory(campaign)[1]` returns the fresh complete index
for coordinator discovery. Entries have deterministic canonical-path-sorted
`sourceNNNNNN` IDs, exact path/hash/size and origin roles. The index permits at
most20,000 unique files and a16MiB serialized commitment. It reports missing
output obligations separately. It is a custody census, not a claim that a
reviewer read or understood those files. Actual source proof I/O can exceed
packet I/O; no total operation time or I/O ceiling is asserted. Per-call
`ValidationSession` reuse retains the mandatory ending census; no across-call
cache exists.

The bounded core retains the complete question/parent, candidate/cell/stage/
comparison/claim census, actual typed scientific results, domains/units/laws,
failed/null states, resource history and actual review/objection content.
The role packet uses indexed textual source slices with pinned original identities. If mandatory material exceeds the
unchanged finite presentation budget, preparation refuses honestly. A narrower
review does not discharge unseen whole-question obligations.

Select source content explicitly, for example:

```json
{"artifact_id":"source000023","offset":0,"max_bytes":4096}
```

At most32 selections, each up to65,536 bytes, can reference only the exact
current inventory. The whole selected source is authenticated within the
existing64MiB role-artifact bound, existing role-sensitive projection is applied,
and the exact byte interval is embedded into a fresh role packet. Split UTF-8 or
binary pages have an explicit base64 encoding. Each page binds the inventory,
original source, full projected digest, total size, interval and page digest.
A page is an excerpt; it is never credited as a whole-source read or physics
applicability proof. Files beyond the selected-artifact bound require an already
supported bounded witness.

`prepare_meta_review` retains separate critic/verifier actors and creates the
ordinary one-call, zero-redo Graph without executing it. An indexed model result
must include located `evidence_citations` for actually presented core/page
artifacts. Application requires the exact core and every selected page digest
in the actual Host role receipt. Merely marking an entry inline is insufficient:
Host budgets can still defer it. Index-only citations refuse, and a later API
read does not retroactively credit a previous response. Fresh page selection
requires fresh role preparation and the existing cumulative charge route.

Indexed Host preparation writes the core, full external inventory and a small
exact inventory commitment. Only request/core/commitment are normal Graph inputs,
within the unchanged128-input and per-input2MB limits. The normal Host operation
freshly verifies the external inventory and every original through its full
ordinary gates, both at preparation and consumption. The original input population remains bound after inventory regeneration. The current Graph reservation is the only allowed intervening
ledger change. Read-only `status`, `context`, `progress`, and the existing scoped
comparison preparation remain on the ordinary `research-protocol` tool route.

Generated core, inventory, selected page, manifest, Graph spec, Host subject
and request commitments derive from intended serialized bytes before writing.
An immediate reread and the ending checks must match those original commitments;
changed first-read bytes must not become a new baseline. Default small JSON
serialization is preserved, and occupied generated paths refuse before overwriting.

Fresh output directories and exact ending output commitments preserve old role
packets. Source/path/leaf/membership checks are time-local observations, not
filesystem locks, perpetual namespace guarantees or OS-enforced blinding.

A meta action changes protocol state only with independent credit from
`review_independence.decide`; by default that is the graph runner's record of an
observed fresh model request without tools. Unauthenticated external and control
transport meta responses are retained as `review_advice`, with the proposed action
intact and `independent=false`. They do not alter protocol state, premises, stage
validity or objection resolution. Objection closure requires a fresh authenticated resolution. Historical conservative holds remain until a fresh
authenticated resolution; existing premise changes are not silently undone.
`meta_review_independence` in the protocol status reports current evidence for
saved actions.
