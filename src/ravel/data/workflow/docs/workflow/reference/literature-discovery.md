# Query discovery, record resolution and located citations

`literature-discover` is an ordinary research coordinator extension. It calls
`research_tools.discover_literature(root, request_pin, fresh_output, host,
max_wall_seconds=...)`. The existing campaign Graph reserves and charges exactly
one `literature-acquire` GET. The Host must explicitly permit
`https://inspirehep.net` under its existing configured network/privacy policy.
This operation does not override policy, discover credentials, retry, paginate,
follow redirects, or initiate a model turn.

The adapter independently follows the official
[INSPIRE REST API](https://github.com/inspirehep/rest-api-doc) and
[HEP metadata schema](https://github.com/inspirehep/inspire-schemas/blob/master/inspire_schemas/records/hep.yml).
The API attribution is Moskovic, *The INSPIRE REST API* (2021),
[10.5281/zenodo.5788550](https://doi.org/10.5281/zenodo.5788550).
It contains no copied upstream implementation. INSPIRE is the supported query
provider in this version. Existing known-URL acquisition, arXiv/DOI metadata
identifiers and the historical resource census retain their distinct routes.

## Typed query and selected record

A source-pinned JSON request has these exact fields:

```json
{
  "schema_version": 1,
  "kind": "literature-discovery-request",
  "id": "original-method",
  "cycle_binding": {"root": "/absolute/existing/campaign", "contract_sha256": "actual-current-original-contract-digest"},
  "provider": "inspire",
  "operation": "query",
  "query": "title Higgs and keyword effective field theory",
  "page": 1,
  "max_results": 10,
  "discovery": null,
  "recid": null,
  "bibliography_selection": null,
  "max_bytes": 200000,
  "max_seconds": 20,
  "tasks": []
}
```

`tasks` carries the complete original scout rows from the existing literature
contract, including unresolved obligations. Each row retains obligation_id,
query, source_scope, claim_ids and failure_or_missing. Query text is encoded as
one parameter, never inserted as a caller-supplied URL or host. Bounds are
25 results, page 1–100, a 512 KiB response, and the declared original service
wall allowance. The byte bound leaves room for the lossless derived product
within the current 2 MiB metadata reader. Large responses fail with their actual
captured prefix retained; nothing is silently discarded.

The complete raw response, original provider record fields, returned order,
remote total/relation when known and selected-page coverage survive. A page is
never labelled an exhaustive search. The remote `next` URL is retained in raw
bytes and is not followed. Exact record ID/control_number disagreement or
repeated IDs leave the page unresolved. No rank-based identity or relevance
acceptance occurs.

For a selected hit make a fresh request with operation `record`, discovery equal
to the actual query product pin, recid equal to its exact returned numeric ID,
and query/page/max_results null. bibliography_selection contains title_index
and year_pointer. A unique title and unique publication year can be taken
literally. Otherwise select an actual title index and an exact
`/metadata/publication_info/<index>/year` or `/metadata/preprint_date` location;
null leaves missing/ambiguous fields unresolved. Contributors retain source
roles: authors are distinct from declared editors/supervisors. Creation/update
timestamps never supply a publication year. No arXiv version or license is
inferred. The record lookup must preserve original campaign/tasks and the
selected query's bibliographic fields and update epoch; a changed epoch requires
a fresh query rather than silently replacing the original record.

## Existing context and author interfaces

`literature-discovered-sources` calls
`research_tools.prepare_discovered_sources(root, product_pin, fresh_output,
reason=...)`. A complete resolved bibliography creates the existing located
context from the *actual acquired secondary JSON source*, retaining its ordinary
acquisition binding and every original scout task. The returned citation has
exact existing manuscript fields id/bibliography/identity_evidence/uncertainties.
Its source_role is `secondary`; its JSON pointer presents the complete original
metadata, which the existing writer/integrity source locator rereads. The
handoff is committed before write and returned with a pin.

Use this citation row in the normal manuscript request and run the existing
source review/author route. Metadata availability does not establish that the
paper was read, independently verify its bibliography, validate its relevance,
or substantiate methodological/physics claims. Primary paper acquisition,
PDF/text extraction, claim-specific located evidence and independent criticism
remain separate ordinary actions. Provider-supplied URLs in metadata are not
silently executed or treated as trusted primary documents. Unknown bibliography,
failed requests, ambiguity, partial search coverage and source-version changes
remain explicit results rather than fabricated references.

Every consume reconstructs the discovery fields from the current original
request and authentic ordinary Graph/acquisition receipt. Raw response changes,
repinned fabricated hits, foreign producers and generated metadata membership
changes refuse. This is bounded sequential custody, not a permanent atomic
snapshot of remote/provider or local mutable state.

## Checked evidence cards and reference following

Use `ravel literature check-cards --rundir RUN --workspace WORKSPACE --request
inputs/cards.json` on a complete JSON list of cards. The request and every source
are descriptor-safe broker reads under the run's knowledge-broker source restrictions. A
refusal retains its broker receipt and card ID without source text. Invalid or
refused cards make the command exit with status 2; their rows remain in the output.
No command here grants network access or starts an acquisition.

An evidence card has `schema_version: 1`, a unique `id`, a verbatim `claim`,
`assertion_kind` (`measurement`, `prediction`, `source_assertion`, or
`speculation`), `quantity: {name, unit}`, literal string `value` and `uncertainty`,
`conditions`, `scope_not_covered`, `locator`, `hepdata`, `superseded_by`, and
`extractor`. Unknown uncertainty is `not_stated`; the optional HEPData identifier
is null when unknown. `superseded_by` is an explicit list of successor IDs.
The locator is `{doc: {path, sha256}, unit, byte_range: [start, end],
excerpt_sha256}`; its range uses zero-based UTF-8 bytes with an exclusive end.
PDF cards locate the authenticated extracted text, preserving the existing
original-PDF/extraction custody separately.

Every number retains its original spelling, every unit is verbatim, and both
source and excerpt hashes must match. A condition is either `not_stated` or
`{value, byte_range}` locating its complete verbatim wording inside the same
excerpt. `observed_or_expected` must be present. The validator does not convert
units, round values, infer conditions, or certify scientific truth.

The decision display contains at most five cards and lists the remaining valid
cards by ID. Its administrative card census retains every supplied ID, failure,
refusal and speculation. Speculation and superseded cards cannot establish a
recipe value or an RDJ anchor. `evidence_card.rdj_anchor` and `recipe_row` are the
RDJ/CJ-2 export seams; the RDJ anchor consumer also rejects structured speculation
card values. Unknown recipe values remain DATA work. Before consumption,
`literature.consume_cards(report, complete_cards, broker=...)` re-derives the
entire census from current originals and checks the matching broker receipts.
A previously checked status cannot survive changed source bytes.

Use `ravel literature follow --rundir RUN --workspace WORKSPACE --request
inputs/follows.json` for a finite explicit citation and code graph. The request
has `sources` (`id`, `path`, `sha256`, `identity`) and `links` (`id`, `from`, `to`,
`kind`, `byte_range`, `text`, `commit`). A citation link has a null commit. A code
link carries the full producing commit, located verbatim with the target identity
in its parent source. Both endpoints are independently checked through the
broker. Unresolved links and refused targets remain in the census. Local source
following does not infer relevance, code licensing or producing-run validity.
Remote acquisition continues through the separately configured and charged
`research_tools.acquire_literature` service.

`ravel literature resolve-title --title TITLE --discovery PRODUCT --base-dir BASE`
resolves an inert `publication_title` witness against an authenticated, explicit
provider-record resolution. The title must match the chosen original title
exactly. Query hits, ambiguous titles and changed metadata are insufficient. The
returned identifiers and discovery pin are a handoff to the intake/route owner;
the original reader witness remains unchanged. `ravel literature tier` checks
that the existing scout card remains at judgment tier.

## Literature and manuscript graph handoffs

The registered run-scoped graphs are `literature.scout`, `literature.source`,
`manuscript.build`, and `manuscript.section`, each with instance
`{request_id: ...}`. The manuscript ID is dotted to follow the substrate registry
schema. The literature graph dispatches the current scout card, maps admitted
source acquisition/extraction requests, obtains cards, performs the literal
check, re-extracts invalid evidence once, and posts the complete result through
the authenticated board seam. Restricted sources are never retried. Failed
checks and attempts remain in effect custody, even if a revised card succeeds.

The graph integration layer supplies `graphs.literature.Services` inside `literature.services(...)`:
`worker_spec(role, state)`, `consume_worker(role, receipt, state)`,
`source_items(state)`, `acquire(state)`, `extract(state)`, `reextract(state)`,
`card_population(state)`, `post(state, report)`, the run-bound source broker, and
an implementation epoch pin. Acquisition/extraction callbacks wrap the existing
ordinary campaign-charged bodies and consumers; `post` uses the board's authenticated
posting. These are trusted integration services, not model-authored executable
callbacks. A missing integration context refuses.

The manuscript graph sequences story, independent sections, synthesis, the
integrity auditor, meta-review, report integrity, computed disclosure, procedure
export, CI3 response and final-task gate. Its `Services` bind the existing
`manuscript_workflow` and `manuscript_production` phase producers/consumers,
section census, exact integrity/final actions and complete record pin. The auditor
must receive the current record and have an actual successful broker read of it.
Disclosure comes from `completion_disclosure`; the procedure note and Snakemake
workflow use the idempotent `procedure_export.export_for_delivery` body behind
`ravel procedure export`. A response to CI3 grants no authority.

The `report_integrity` gate needs its registered provider; the graph refuses
while it is absent. Research-protocol integration is owned by the protocol workflow. These graph
builders and synthetic sequencing checks do not establish live model behavior,
scientific validity, a native manuscript build or delivery acceptance.

Role-card validator modules (`ravel.validation.<module>`) resolve to their exact
source-backed atlas IDs (`check:validation.<module>`). Already canonical IDs are
unchanged; unknown IDs still refuse. After atlas or role changes, regenerate the
affordance census with `python -m ravel.workflow.toolbelt census --write`.
