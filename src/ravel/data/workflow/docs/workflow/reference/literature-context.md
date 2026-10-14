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
bindings. Failed, missing, unsupported and unlinked tasks remain in the result.
An initial story can use this incomplete context; it cannot manufacture a
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
byte budget and wall allowance. The original may use the existing 64MiB
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
containers and otherwise unsupported fragments. This is lexical structure,
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

The selected GET now retains Transfer-Encoding alongside Content-Length. A supplied ASCII decimal Content-Length must equal the complete captured HTTP entity byte count, and the ordinary acquisition consumer independently enforces the same check. A short 200 response remains failed with captured bytes and full original tasks; it cannot become a supplied source merely because an optional prior SHA was absent. Ambiguous Transfer-Encoding plus Content-Length and unsupported transfer coding refuse. The existing HTTPResponse chunk parser must reach its terminal chunk successfully; a connection-close response without either header establishes only observed EOF and captured bytes, not verified remote entity/version completeness. No optional version hash is universally required, and source bytes are never rewritten, decompressed or promoted into reading/physics credit.
