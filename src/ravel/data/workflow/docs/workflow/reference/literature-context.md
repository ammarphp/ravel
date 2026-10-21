# Located literature and missing-source work

The research coordinator can select three ordinary services: literature-acquire,
literature-pdf, and literature-context. They preserve the original research
contract, its acquisition obligations, and its current source evidence. Source
preparation produces located material for the existing physics knowledge and
manuscript services. It does not accept a scientific claim.

Start with exact known sources and the complete missing-source roster. A
literature-context-request contains cycle_binding, documents, the existing
knowledge query, source annotations, explicit generated hypotheses, typed
edges, and ordered acquisition_tasks. Each task retains obligation_id,
query, source_scope, claim_ids, and failure_or_missing. Documents retain
their exact pin, citation, version, license or explicitly unknown license,
access record, media type, parents, task IDs and actual acquisition/extraction
bindings. The result retains all tasks and their `failed`, `missing`, `unsupported` or unlinked status.
An initial story can use this incomplete context; it must not manufacture a
complete bibliography from it.

Use research_tools.prepare_literature_context(root, request_pin, output_dir,
premise_map=None, reason=...) after the selecting Graph returns. Its return is
{product, knowledge_request, context}. literature_context.consume(product_pin,
base_dir=...) rederives the complete current product and checks the original
bytes, every generated file and output membership. An optional complete
premise_map delegates to research_cycle.bind_knowledge. Missing source
material supplies no dummy fact. Retrieval keeps the existing requires,
contradicts, and motivates closure and omitted-node census.

For a selected public source, research_tools.acquire_literature(root,
request_pin, output_dir, host, max_wall_seconds=...) prepares and executes one
ordinary campaign-charged executor tool. The closed request declares an exact
HTTPS URL, media format, optional prospective SHA256, byte and wall bounds, and
the selected exact scout tasks. Host configuration must explicitly declare
literature_origins, for example ["https://arxiv.org"]; the default empty
list permits no acquisition. Existing local_only privacy refuses it.
Credentials in URLs, private/local peers, redirects, environment proxies,
cookies and provider credentials are not used. The response status, selected
headers, peer, wall observation and actual captured body remain authenticated.
A failed or truncated response is retained as a failure and supplies no
original source. DNS/native socket calls have their own system behavior; the
existing outer supervisor owns the hard interruption. There is no search
scheduler or invented cached success.

PDF is a first-class next action. research_tools.extract_literature_pdf(root,
request_pin, output_dir, host, max_wall_seconds=...) runs a single ordinary
executor tool using the existing required PDFium 5.14.0 renderer/runtime
census. Its request declares the original pin, maximum pages, complete text
byte budget and wall allowance. The original can use the existing 64MiB
artifact policy through this registered operational-data custody path.
Model/request/helper text limits remain unchanged. Checks authenticate the
original at entry and ending; extraction budgets do not imply hard
preemption inside a native page call.

Every admitted original page has an ordered text outcome: extracted, empty or
failed. Empty/image-only pages and page failures remain explicit. Whole-document
resource or parsing failure retains the original and reported page count
without advertising an extracted subset. Text extraction does not establish
visual, OCR, equation or table completeness. The context retains those
unknowns and asks for actual source-bound visual/OCR/structured follow-up.
The existing visual transport has its own admitted page/source/raster limits;
large raw custody is not permission to bypass them or claim all pages were
seen by a model.

HTML, TeX, Markdown and UTF-8 text produce a structural forest of exact source
intervals, including sections, paragraphs, table/figure/caption/equation
containers and fragments outside the declared grammar. This is lexical structure,
not semantic equation or layout validation. Unclosed or unmatched structure
is retained as unresolved. Every supported character survives; original
assertions have located excerpt hashes and derivation parents. Tags,
conventions and applicability are explicitly caller-authored annotations.
Generated summaries and hypotheses remain a separate unsourced population.
A source assertion means that the supplied document says it, not that it is
correct, measured, peer reviewed or read by a model.

The typed literature-original-custody/v1 manifest joins complete original
PDFs and ordinary extraction/acquisition receipts into the existing knowledge
kernel. It independently authenticates all referenced originals and intended
derived bytes. The normal 2MiB knowledge member/document bound, 512-node limit
and 512KiB retrieval packet limit remain. There are at most 32 original
documents, 64MiB per original, 256MiB in total and 4096 source units.
Exceeding a complete-population bound refuses; it never truncates the source
roster or silently removes conflicts. Ordinary Graph input and model
presentation bounds continue to apply to callers. A custody hash or index row
never supplies excerpt/page reading credit.

The staged writer authenticates its actual citation-scout response, checks
exact ordered task equality before preparation and again in the consumed
context, then retains both resolved and failed outcomes. Actual selected
excerpts/pages must be presented in each consuming role's ordinary context.
Final manuscript integrity review, real build, visual CI3 and original task
completion remain the existing consumers.

## Closing custody and HTTP body framing

The bounded ending check rereads every remembered input/output/runtime leaf of all participating readers, then performs one closing canonical-path and identity sweep across the whole remembered population and finally rechecks the exact flat output membership. Earlier files or late extra outputs changed during the last reread refuse. This is a sequential observation, not an atomic filesystem snapshot or a lock against changes after return. Complete sources, original assignment and ordinary receipt checks remain separate and unchanged.

The selected GET now retains Transfer-Encoding alongside Content-Length. A supplied ASCII decimal Content-Length must equal the complete captured HTTP entity byte count, and the ordinary acquisition consumer independently enforces the same check. A short 200 response remains failed with captured bytes and full original tasks; it must not become a supplied source merely because an optional prior SHA was absent. Ambiguous Transfer-Encoding plus Content-Length and transfer coding other than `chunked` refuse. The existing HTTPResponse chunk parser must reach its terminal chunk successfully; a connection-close response without either header establishes only observed EOF and captured bytes, not verified remote entity/version completeness. No optional version hash is universally required, and source bytes are never rewritten, decompressed or promoted into reading/physics credit.

## Deterministic metadata navigation

`literature_relations.build_graph` projects admitted `SourceDocument` snapshots
into a separate disposable index. `GraphQuery` offers only implementations,
published_artifacts, related_papers, models and coverage. Exact identifiers,
versions and source JSON pointers remain attached to each path. Code and
statistical workspaces are retrievable items; descriptions alone never classify
attachments. Conflicting identifiers remain quarantined instead of being merged.

`literature_coverage.coverage_report` applies exact signature, production, energy
and backend filters to explicitly supplied dated populations. Missing mappings,
unknown rows, conflicts and upstream qualification labels remain separate. A list
entry is not proof of physics applicability or a complete literature census.

The broker supplies current denied source IDs and canonical identifiers before
traversal. Alias, content-copy and complete derivative lineage remain filtered.
Pin the graph generation in the retrieval manifest; recheck original source
custody when serving exact excerpts. Graph nodes and paths locate candidates;
they provide neither reading credit, physics verification nor execution authority.
Keep the global literature rescue path when graph metadata is incomplete.

## Structured TeX evidence and discovery sources

New located products record `literature-forest-law/3`. TeX tables retain exact
`table-row` and `table-cell` intervals with zero-based row/column, column span,
explicit header and verbatim unit tokens. Figure children retain caption text,
file references and source-written axis labels. These are lexical source slices;
macros outside the declared grammar, ragged rows, nested tables and population overflows remain
unresolved. Retrieval returns this structure in `location.located_unit` while
preserving original excerpt hashes. Rebuild older TeX products from their
original requests; their derivation pins are never edited. Non-TeX law-2 products
and legacy law-1 verification retain their original rules.

`literature_discovery_sources.DiscoverySource` supplies query and citation URLs,
page parsing and identifier projection. Trusted registration selects the source;
a scope must not select a provider or grant network access. Sources use the same
charged acquisition and replay custody. The installed source retains its current
query semantics. Re-ranking remains enabled.

## Excluding transformed source material

Trusted retrieval settings accept `excluded_origins` as a list of `{kind, value}`
entries or an absolute path to a `literature-excluded-origins` document with
`schema_version: 1` and `origins`. Kinds are `document`, `pin`, `run` and `path`;
pin values are SHA256 digests and paths are canonical corpus-relative paths.
Supply identities only, without copying blinded questions, answers or documents.

The corpus driver and benchmark runner pass this policy to index construction.
A matching original or lineage descriptor refuses the complete build before
splitting, embedding or publishing. Derived records without source ancestry also
refuse when exclusions are configured. The manifest binds the normalized policy
digest; a settings/index mismatch requires a fresh build. Serving excludes these
origins before ranking and checks every returned row. Existing indexes are not
made clean by filtering their outputs: rebuild under the current exclusion set.

Lesson writes, promotion, updates, loading and materialization apply the trusted
installation origin policy. Writes additionally require the supplied blinded
screen when origin exclusions are configured. Frozen local snapshots retain their
own digest as `local_snapshot_sha256`; `snapshot_sha256` identifies all loaded
lesson bytes, including shipped lessons. An uninspected provenance chain must not
establish absence of blinded material.

The generality and restricted-source scanners inspect archive contents in memory
under cumulative expansion, member and nesting bounds. Every member outside the declared scan contract,
malformed, encrypted, special, truncated or over-budget container/member produces
an `unscanned-*` finding. A scan with such a finding must not be reported clean.
Use synthetic fixtures for these controls; blinded material stays outside all
indexes and model contexts.

## Development embedding comparison

`ravel literature benchmark --corpus CORPUS --base-dir ORIGINALS --questions
DEVELOPMENT_QUESTIONS --out FRESH_OUTPUT --model CURRENT --model CANDIDATE`
builds distinct pinned indexes and performs governed hybrid retrieval with the
same enabled reranker. Explicit `--excluded-root` values supplement installation
origin exclusions. Inspect and qualify models offline; fetching requires the
separate explicit model-prefetch action. The manifest records models, corpus,
questions, code, build costs and cold/warm latency; scoring is external.

Use only an approved development split and a decision margin and latency budget
registered before running. Record missing models or inputs as missing evidence.
A synthetic adapter test establishes software behavior only. Preserve the current
default until the registered comparison supplies sufficient measured evidence.
Held-out questions and blind-audit material never enter this workflow or a model
context.
