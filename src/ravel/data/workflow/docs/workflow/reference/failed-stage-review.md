# Failed scientific-stage diagnostics

A failed scientific stage can contain useful returned numerical witnesses. Its
process failure and any unresolved fits still prohibit ordinary acceptance,
delivery and reuse. `failed-review` records a separate diagnostic premise so an
independent critic can propose mechanisms, an improver can construct a useful
intervention, and a skeptical verifier can assess that experiment design.

This path does not create a `physics_review` cycle. It does not cast acceptance
votes, admit a correction, grant a retry, create an approval, lift a hold, change
an old result or run a process. Keep the original failed run and all old evidence.
A successor requires its own actual scientific plan, source/input contract,
resource bounds, approval, execution records and fresh result review.

## Failure distinctions

`infrastructure_failure` retains missing or empty outputs, malformed raw output,
tool/runtime failures and unavailable result evidence as operational information.
An absent scientific result must not be described as a rejected hypothesis.

`scientific_unresolved` requires a nonempty actual returned result with a retained
`failed`, `unresolved` or `inconclusive` status and no aggregate infrastructure
fatal/custody refusal. All declared output roots must exist, and the caller's
explicit required numerical-output files must be present and nonempty. Machine
passes on part of the declared fit population do not establish the whole result.

A successful experiment can contradict a hypothesis. That negative scientific
outcome uses the ordinary successful-receipt review path, with its actual scope.
It is not admitted here as a failed execution.

## Read-only intake

Supply a strict request with these exact fields:

```json
{
  "schema_version": 1,
  "stage_receipt": {"path": "logs/execution/science/ACTUAL_ID/record.json", "sha256": "ACTUAL_FILE_DIGEST"},
  "failure_kind": "scientific_unresolved",
  "result": {"path": "outputs/attempt-1/result.json", "sha256": "ACTUAL_FILE_DIGEST"},
  "evidence": [{"path": "outputs/attempt-1/result.json", "sha256": "ACTUAL_FILE_DIGEST", "location": "$.unresolved_fit"}],
  "required_returned_outputs": ["outputs/attempt-1/result.json", "outputs/attempt-1/raw.json"]
}
```

The SHA placeholders in this example must be replaced by actual lowercase
SHA-256 digests. `result` may be `null` only for infrastructure diagnosis. Required
outputs are canonical run-relative individual file paths under the actual stage
output declaration. Evidence paths may also bind source or independently retained
diagnostic files. Locations are declarations for the reviewer to inspect.

```bash
ravel failed-review --rundir FAILED_RUN --request REQUEST.json --out SEPARATE/intake.json
```

The output must be outside the failed run, and an existing output is never
replaced. The API also exposes `validate(request)`, `intake(request, base_dir=run)`,
`inputs(request, base_dir=run)` and `verify(document, base_dir=run)`.

Intake verifies the exact current terminal failed attempt, a nonzero exit code,
the retained attempt record, the original specification fingerprint, complete
original input/source snapshot, parent receipts, and a fresh complete returned
output census. An actual scientific run also needs its retained observed launch.
Its selected historical recipe must match every recorded immutable member,
including optional helper/resource/output declarations. A self-rehashed removed
or changed declaration cannot replace the launch's original binding.

Historical helper metadata is compared as retained data. It is not admitted by
the current helper launcher or imported/executed from its historical source.
The original runtime and source identities remain visible. This allows diagnosis
across source epochs without qualifying a new execution or reusing an old result.

Successful execution commits its output receipt at completion. A failed attempt
may have no such commitment. This diagnostic path explicitly labels its output
custody as a fresh capture of retained bytes, not a successful execution receipt.
It cannot establish that arbitrary returned bytes were unchanged before capture.
Retain external source/collector commitments when that distinction matters.

Every observation uses a fresh existing `ValidationSession`, consumes ending
file/inventory/ledger mutation checks, and closes it before returning. Verification
re-observes the complete premise; changed sources, outputs, added directory
members, a superseded attempt or changed launch journal make it stale.

## Separate role packets and actual feedback

`create_context(document, role, out, base_dir=run)` produces immutable packets for
`critic`, `improver`, `verifier` and `synthesizer`. These use the ordinary
`review_context.read_artifact` reader and AgentGraph/AgentHost packet format.
Every role receives the exact failure premise and its complete source/returned/
missing census. Located evidence is projected using the existing scientific and
known-judgment masks for critic/verifier. No claim scope or ordinary review vote
is supplied. Oversized evidence is listed explicitly as an omitted witness to
request; it is not silently read through a raw path. The packet reader is an
allowlist, not an operating-system sandbox.

`graph_feedback(document, critic_binding, verifier_binding, base_dir=run)` checks
two current actual model-call receipts through `agent_graph.model_receipt`.
Each binding has exactly `graph_root`, `node_id`, `context_manifest_sha256` and
`actor_id`. The original stage-input review policy supplies declared separate
critic and verifier actors. Both actual role packets must present the exact
failure premise. Their roles, subject and packet hashes, current graph generation,
call custody, fresh separated transport and different actual request IDs are
checked. The resulting feedback retains the structured judgments and failure
class. It grants no scientific acceptance or action authority.

The canonical premise digest is its document identity. Its serialized JSON file
has a separate byte digest. Graph receipt checks bind the former as a packet
source identity, then verify the actually presented premise bytes equal the
complete document. A digest for an unrelated projection cannot substitute for it.

Reconciled/manual attestation, incomplete graphs and unestablished transports do
not count as actual diagnostic feedback. `allow_control=True` is only for explicitly
labeled engineering controls; loopback/stub observations and terminal-ledger-only
fixtures remain `control_only`. They do not demonstrate live reviewer accuracy.
Declared actor IDs and observed transport do not authenticate actor identity or
prove scientific independence.

The frontier `research_cycle` consumer composes this intake/feedback with its existing
Graph-bound `improver` revision operation. The proposal must bind the exact failed
parent experiment and feedback, retain rival predictions, identify one concrete
intervention, and supply all new scientific source/input/resource obligations.
The improver is a proposer, not an additional result-acceptance vote. A verifier
at this stage assesses diagnosis and experiment design; it cannot close numerical
repair objections before the successor executes. New actual outputs need their
own ordinary critic/verifier/decider review.

Existing independent diagnostic reports may predate the Graph. Do not invent a
past Graph call, fresh context or transport receipt for them.
`historical_feedback(document, index_pin, critic_binding, verifier_binding,
base_dir=run)` binds their original bytes with explicit provenance. Each binding
has `actor_id`, `report` (an exact path/digest pin), `actor_pointer`, `subject`
(an exact pin already bound in the failed premise) and `subject_pointer`. The
actor and subject pointers locate actual fields in the report. The two reports
must have distinct identities and the same exact failed subject, and the explicit
index must contain both reports and that subject. Every index pin is rechecked.

This output is `failed_stage_historical_feedback`, with
`feedback_source: "retained_attributed_reports"`,
`fresh_role_transport_observed: false`, no Graph receipt, no acceptance and no new
model calls. Actor attribution is checked against the original role policy and
located report fields; authorship and scientific independence remain unauthenticated.
The report's favorable words do not become an ordinary acceptance vote.

`verify_feedback(document, feedback, base_dir=run)` freshly recomputes either
diagnostic route from its exact original bindings. Changed report/index bytes,
role or subject grafts, stale Graph generations and self-resealed authority flags
are refused. Its default also refuses engineering-control feedback.

`bind_successor(document, feedback, proposal_pin, candidate_inputs, base_dir=run)`
binds the exact source proposal and complete candidate inputs to the failed record,
original source/returned-output census identities and revalidated critique. It is
a source-input binding for the existing research-cycle design operation. It does
not inspect arbitrary prose for scientific correctness, provide a resource
approval, or replace the full hypotheses, rival predictions, held-fixed quantities,
rechecks and resource contract that the consumer must declare.

## Executed scope of the private control

The retained stau four-fit campaign is an actual failure with exit code 2. All
four fits and 12 starts returned. Three fit summaries passed their machine gates;
DS280 with free strength retained bounded line-search/iteration failure. The
complete stage remains failed and unresolved. Twelve independent endpoint-density
parities do not close optimization, globality, calibration or physics validity.

The private read-only intake bound 468 original source/input files, 44 returned
files and 11 explicit required outputs, and produced four separate role packets.
No model call, refit, new evaluator call, acceptance vote or retry occurred. The
private controls establish custody/routing guards, not diagnostic efficacy.

The source-only continuation also bound the actual historical diagnostic index
and its existing CMS critic/RS1 skeptic reports to the retained principal-face
proposal, design, adapter and solver inputs. It explicitly preserves that these
reports were not observed as Graph model calls. No source binding established a
new scientific result or launched the prospective intervention.

The candidate principal-face Fisher intervention has separate retained source,
design and small analytic controls. A real discriminating successor still needs
source review, a fresh prospective four-fit study and unchanged gates/budgets,
actual execution under its own approved lease, and independent skeptical review
of all returned starts. Neither this intake nor source-control success establishes
that the intervention repairs DS280 or validates a physics result.
# Bounded presentation of complete failed intakes

`create_context` and ordinary `scientific-judgment prepare-failed-role` retain the small-intake packet unchanged. When the complete canonical intake exceeds the existing 2,000,000-byte initial artifact bound, the `premise` artifact becomes a deterministic material presentation. It keeps FAILED status, launch/record/fingerprint pins, failure kind, unresolved or absent numerical outcome, every missing output obligation, actor declarations, limitations and false authority flags. The source/returned census is represented by complete counts, byte totals and canonical digests; these are not numerical acceptance or a claim that every file was read by the model. A bounded source-authenticated `science.json` projection supplies the actual task, source and assumptions initially.

The unchanged complete intake is retained as `full_premise`, an authenticated allowlisted artifact marked `on_demand`. Graph checks authenticate it; Host initially presents its hash, size and access metadata, rather than its contents. Model receipts distinguish bound source bytes from bytes actually presented. Diagnostic feedback revalidates the complete live failed premise and recomputes its initial summary; a deferred/hidden summary cannot supply feedback.

Use the existing reader for an authenticated byte page:

```sh
ravel review-context read --packet ROLE/context --artifact full_premise \
  --manifest-sha256 CREATION_DIGEST --offset 0 --max-bytes 65536
```

Every call authenticates the complete artifact before returning the selected page. The response retains the full/page hashes, byte offset, exact byte count, total and next offset. Split UTF-8 or binary pages use explicitly labeled base64. `review-read` Graph tools accept the same `artifact_id`, `offset` and `max_bytes`; an on-demand artifact defaults to one bounded page. This is bounded returned data, not a bound on total authentication I/O.

The one model invocation has no tools. When more evidence is needed, the coordinator selects exact pages into a fresh ordinary role context:

```sh
ravel judgment prepare-failed-role --rundir FAILED_RUN --intake INTAKE.json \
  --out FRESH_ROLE --role critic --model MODEL --reasoning-effort high \
  --max-output-tokens 3500 --max-wall-seconds 180 --evidence-pages PAGES.json
```

`PAGES.json` is a list of closed `{artifact_id, offset, max_bytes}` objects, with at most 32 entries and 1..65536 bytes per page. API callers pass `evidence_pages` to `prepare_failed_role` or `create_context`. IDs select `full_premise`, existing `eNNNN` located evidence, or `inputNNNNNN`/`returnedNNNNNN` file ordinals. Source/returned ordinals sort the complete flattened census by absolute file path. They resolve only within the original authenticated intake, never to an arbitrary supplied path. Selected source contents retain the same known-judgment/scientific-artifact projections as ordinary critic/verifier evidence. Source/page manifest entries name the exact original file. A source beyond the existing 16MiB retained-artifact ceiling requires a separate bounded witness.

The full-intake census is not the raw content of all source files. Selecting an input/returned ordinal authenticates and copies that specific source, then presents only the requested page. Each fresh preparation preserves prior packets and calls. Dispatch the prepared Graph through the existing Graph API/CLI; attached research campaigns use the existing `research-cycle graph --prepared` reservation route. No reader or preparation launches a model/scientific worker, approves a retry, changes old votes or permits failed-result delivery/reuse. Scientific diagnosis and effectiveness remain separate from this source transport.
