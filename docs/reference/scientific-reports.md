# Quantity-bound scientific reports

`ravel.workflow.scientific_report.compose(request, base_dir=...)` builds text,
tables and CSV plot data from explicitly selected scalar facts in supplied tool
artifacts. `inspect_draft` compares every declared slot; `revise` constructs the
corrected report and retains the original draft, discrepancies and foreign claims.

The closed schema-1 request contains `title`, `artifact_request`, optional
`context`, `facts`, `sections` and `interpretation`. A fact specifies its exact
JSON selector, quantity/context selector, label, unit, scope, population and
scope conditions. Every declared fact must appear in a section. The artifact and
context APIs verify their own source and supplied-result pins.

Ordinary AgentHost tool actions `scientific-report` and `report-revise` take
`request_input` and, for revision, `draft_input`. All nested source/result/context
pins must be explicit graph inputs. Critic and verifier roles must not receive
these authoring actions. The graph charges the tool call and refuses changed
source or input identities on reuse.

Delivered Markdown lists every requested quantity, its supplied check status and
the facts that expose it. Missing quantities and passed-but-unexposed quantities
remain visible after revision. Exact selectors delimit coverage: exposing one
record does not prove a whole vector was reported. Context completion, report
exposure and full-task scientific acceptance are separate fields. Labels, units,
interpretation, tool truth and image pixels remain unverified by this adapter.

Requests, facts, sections and text have finite bounds. An oversized complete
report refuses instead of silently truncating. The portable controls exercise
actual Host/Graph routes with synthetic supplied artifacts; they establish no
scientific efficacy or multi-iteration research outcome.
