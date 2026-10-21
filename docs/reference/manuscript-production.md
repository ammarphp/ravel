# Manuscript production API and contracts

The normal coordinator choice discriminator is `manuscript-author`. Required source-bound author request is a closed JSON object with schema_version=1 and:

- profile: internal-note, research-paper, epjc, prd, nature, page-limited-note or user; author_id is the actual scientific actor identity, not a human author authentication.
- original_task: pin3 to literal UTF-8 whole original prompt. quantitative_report: pin3 to a complete existing scientific_report request with current context. source_manifest: pin3 to {schema_version,evidence:[{id,description,located}]}.
- environment: pin3 {schema_version,description,assets:[pin3]}; code_manifest: pin3 {schema_version,git_commit:40hex,dirty:bool,files:[pin3]}; skills: full selected software skill pin3 list.
- methods: [{id,description,operations:[{id,description,code:[located],execution:null|{rundir,receipt:pin3},results:[located],differences:[text]}],citation_ids:[id],uncertainties:[text]}]. Actual code and returned evidence must be current input/output leaves of the same existing recorded stage when execution is asserted. Failed stage is diagnostic; unrelated output is refused.
- citations: [{id,bibliography:{title,authors:[text],year,identifiers:[text]},identity_evidence:[{source_role:primary-paper|author-repository|publisher-metadata|secondary,source_url,located}],uncertainties:[text]}]. No DOI/URL hash asserts bibliography truth.
- figures: [{id,image:pin3,contract:pin3,evidence_ids:[id],comparison:null|{reference:pin3,generated:pin3,composite:pin3}}]. Actual composite image must be the exposed image. Native SVG/TikZ diagram sidecars are preserved outside the scalar quantity system; SVG uses a separately bound renderer if selected, TikZ requires explicit compatible source template/runtime rather than a fictitious image.
- runtime: {model,model_build,action:model|external,reasoning_effort,max_output_tokens,max_input_tokens,max_context_bytes,max_wall_seconds}. All bounds positive. The actual model-build observation and token usage must exist; unknowns must not be replaced by the requested alias.
- revision: null|{previous_package:pin3,feedback_binding:actual judgment binding}; challenge_requirements: null|pin3 (required when the note rule pack says so); template: null|pin3; formatting: pin3. An originally blinded task also requires blinding_policy:pin3, blinding_sources:pin3 to genuine public-projection lineage, and source_review:{request:pin3,bindings:[actual original-role bindings]} before author dispatch. These optional fields do not give arbitrary data a safe label.

`pin3={path,sha256,size}`; located is `{artifact:pin3,format:text|json,location:exact Unicode span|JSON pointer,value:actual located content}`. Every selected artifact has exact current bytes. The full public source presentation is bounded; missing/oversized populations refuse without truncation.

Formatting is a closed source contract: `{schema_version:1,profile,stage,article_type,render,rules,template_assets:[pin3],sections?:[{id,heading,semantics:[role],placement:main|post-references|appendix}],rule_pack?:pin3}`. Literal custom headings and section order determine the writer's output schema and native renderer. Semantic roles preserve complete title/abstract/methods/results/scope conditions obligations without forcing the headings to those names. `render={class:article|revtex4-2|svjour3|source-template,frontmatter:title-before-abstract|abstract-before-title,graphics:inline|separate,line_numbers:bool,appendices:none|before-references|after-references,citation_style:numeric-brackets|numeric-superscript|author-year,post_reference_sections:[section],quantitative_position:main|appendix}`. Nature final post-reference order is methods,data-availability,code-availability,acknowledgements,funding,author-contributions,competing-interests,additional-information,extended-data-legends. Requirements determine which sections actually exist; this renderer sequence does not invent research/author data. All original rule rows `{id,kind,scope,value,origin:publisher|challenge|user,source_basis:located|null}` remain visible. Publisher/challenge origin requires source_basis. `excluded_sections` uses an explicit main-pages/main-words scope; a located venue exclusion can preserve legitimate Online Methods treatment, while a rule pack can forbid user exclusions. No implied universal word/page count.

A page-limited note (`profile: page-limited-note`) names a supplied rule pack: `{schema_version:1,kind:note-rule-pack,id,title,origin:publisher|challenge|user,source_basis:located|null,max_main_pages,excluded_sections,max_figures,max_tables,required_semantics,main_text_semantics,allow_user_count_exclusions,requires_supplied_requirements}`. The contract can tighten the pack's page, figure and table ceilings but not loosen them, every required semantic role must be mapped to a section, main-text roles must not move to an appendix, and the build refuses a page ceiling above the pack's. `ravel note-profile contract` writes the formatting contract from a pack. The requester supplies the rule pack stating the actual note requirements.

Public calls:

```python
prepare_source_review(request, out, *, base_dir)  # blinded tasks only, no vote
prepare_source_role(request, source_request, out, *, base_dir, rundir, role,
    actor_id, model, reasoning_effort, max_output_tokens, max_wall_seconds,
    claim_scope, campaign=None, experiment=None)
consume_source_role(request, source_request, binding, *, base_dir)
prepare_writer(request, out, *, base_dir, campaign)
execute_writer(binding, host)  # outside campaign lock; actual charged Graph
collect(binding, out)
prepare_integrity_role(package_pin, out, *, base_dir, rundir, role, actor_id,
    model, reasoning_effort, max_output_tokens, max_wall_seconds, claim_scope,
    campaign=None, experiment=None)
consume_integrity_role(package_pin, binding, *, base_dir)
prepare_build(package_pin, out, *, base_dir, runtime, review_policy,
    goal_binding, max_seconds=120)
finalize(package_pin, bindings, build_binding, final_manifest,
    completion_request, *, base_dir, rundir)
```

Production returns a pinned package with manuscript.md, note.tex, integrity-request.json, actual prompt/model telemetry, full source/figure/template/format dependencies and all acceptance flags false. Integrity roles create existing exact decision-case bindings; genuine material send-back is the revision input. Build binding is `{rundir,receipt:pin3,result:pin3}` to the real ordinary successful stage. Review bindings are the actual independent original journal roles, not a fabricated three-item JSON list. Final manifest is the exact existing CI3 artifact population, compiled PDF in its visual/figure role. Whole-parent completion request is source-bound and accepted by task_completion.require_final; the shared task-completion-context producer can prepare readiness without granting acceptance. Keep author, build, full artifact population and original parent under a legitimate common review root; must not borrow foreign files or manufacture votes.

Build task is `{config:path}`. Closed build config is `{schema_version:1,package:pin3,runtime,runtime_base:absolute,max_seconds,max_ram_mib,max_output_bytes,max_main_pages:null|positive_int}`. The package preserves its authenticated original source_base; runtime_base separately preserves the caller's runtime directory. Relative formatting/template/source-basis and runtime pins retain their respective bases through different writer, package and ordinary-build directories. Native runtime is `{engine:pdflatex,compiler:pin2,pdfinfo:pin2,svg_converter:null|pin2,asset_trees:[{root,manifest:pin2}],max_ram_mib}`; each tree manifest is `{schema_version:1,files:{relative_path:sha256}}`. Native binaries are required regular files. Exact full selected class/font/bib tree, licenses and actual platform/load/TeX search closure need root qualification. Scientific study max_attempts=1; review max_redos=0; exact claim-scope identifier is `manuscript_pdf_delivery`, action delivery. This scope covers source-bound portable manuscript PDF rendering and page census only. Compilation and page census do not claim scientific acceptance.

Author verification reconsumes the actual charged response and reproduces every emitted manuscript, TeX, asset, bibliography, format assessment and package byte. It checks the complete supplied-template character census as well. Rehashing replaced prose must not borrow an unchanged author binding. The ordinary build counts physical interval unions for every emitted section, including main content after references and visible template prose; unclassified physical pages count conservatively as main text. Only explicit source-defined exclusions apply. Shared pages count once if any main content occupies them.

SVG and JPEG originals remain unchanged source_output artifacts. The selected ordinary build produces actual supported PDF previews: rsvg-convert for SVG, or the same admitted pdflatex with an exact image-only source and recorder for JPEG. CI3 `visual_derivations` rows are `{source:pin3,preview:pin3,build:{rundir,receipt:pin3,result:pin3}}`; both the original and mandatory preview must be in the final population, with the preview in the actual figure roster. Only the authenticated same-build mapping admits the original source media. Generic media rules, actual page/figure presentation and visual judgments remain strict.

For blinded production, pre-author source preparation presents the complete source-derived data/support/machinery/custody census. Existing original independent roles and CI2 judge the exact current source context before the writer can see it; analytical data must already have genuine public-projection proof. Machine-side stage captures are rechecked but are never returned as model evidence. Final source lineage uses authenticated authored_manuscript or manuscript_build producers plus the original independently derived blind policy. No caller safe-pin list, class name or reviewer judgment proves secrecy or scientific truth.

A search note's input must distinguish prepared source inventories from later event moments, the expected-data (Asimov) model, the profiled discovery sensitivity and any comparison with a previous analysis. No yields/data/figures are inferred from an inventory, and none exist merely because this route can author a document.


## Regular snapshot runtime/v2 and qualification

Keep the existing config/runtime v1 for its historical supplied regular runtime.
For a larger explicit selected closure, config/v2 adds `custody_limits` and
runtime/v2 adds `schema_version:2`, `purpose`, `environment`, `closure_manifest`
(pin3), `snapshot_root` and `platform`; all original runtime fields remain.
`prepare_build(..., custody_limits=policy)` emits this same ordinary configuration.
The policy is exactly `{max_files,max_bytes,max_metadata_bytes}`: legacy defaults
4096 files,16GiB,2,000,000 metadata bytes; supported ceilings20,000 files,16GiB,
16MiB. The complete author/build/output union must fit. These are operational
capacities, never execution approval or larger scientific/model context limits.

Use `python -m ravel.workflow.publication_runtime --source-inventory SOURCE
--out SOURCE-INVENTORY.json --allowed-target-root EXPLICIT-REGULAR-TARGET
--limits JSON` to capture complete selected source/link identities. Inventory
must be outside every selected tree. A pinned preparation request has exact fields
`schema_version:1,trees:[{source_root:absolute,destination:relative,inventory:pin3}],
allowed_target_roots,tools:{compiler:relative,pdfinfo:relative,svg_converter:null|relative},
environment,platform,platform_dependencies,custody_limits`. Destinations must be disjoint. Select the complete needed dependency closure and original licence/source
records; do not copy unrelated whole TeX installations or omit consumed members.

`--materialize REQUEST.json --sha256 SHA --out FRESH-DIRECTORY` resolves complete
bounded aliases, captures every spelling/target/terminal identity and streams
exact admitted bytes into regular copies preserving modes/layout. Compiler must
remain named `pdflatex`, even when its source alias names `pdftex`. The output has
`runtime/`, the existing relative-name/hash `tree-manifest.json`, and a pinned
`closure-manifest.json` retaining source provenance and explicit qualification
state. Cycles, dangling/escaped links, special files, changed source bytes or
membership, duplicate destination names and excess capacities refuse. Failed
partial output stays held; copying does not establish runtime qualification.

Each selected tool has a closed explicit environment. Search roots must be
admitted regular snapshot directories; empty/trailing search elements and host
fallback, interpolation, preload and undeclared variables refuse. Compiler has
explicit TEXMF/search/cache roots, `openin_any=p,openout_any=p,shell_escape=f`,
`MKTEXPK=MKTEXTFM=MKTEXFMT=0`. `{work}/relative` is allowed only for owned scratch
variables; no `HOME`, `home` or `CODEX_HOME` override. All five original numerical
thread variables remain1. Explicit environment receipts retain PID, invocation,
working directory and actual effective environment; unrelated native adapters
keep their existing behavior when no explicit environment is supplied.

Set runtime `purpose:qualification` for the first ordinarily declared/approved
bounded build. It uses the same compiler, two passes, page census, complete input
custody and supervisor, and captures current native image/TeX recorder evidence.
Its result explicitly remains `runtime_qualified:false` and must not satisfy final
manuscript delivery/CI3. It emits `runtime-observation-TOOL.json` pin3 values.
Bind each observation to the same successful ordinary `{rundir,receipt:pin3,
observation:pin3}` and the original immutable qualification configuration. Do not
rewrite that configuration to prepare a later build: the original receipt must
remain current.

`--qualify REQUEST.json --sha256 SHA --out FRESH-QUALIFIED-CLOSURE.json` consumes
`{snapshot:pin3,observations:{compiler:binding,pdfinfo:binding,svg_converter:binding
if selected}}`. It authenticates original source/runtime/configuration and current
successful ordinary input/output custody, exact effective environment, native
PID-tagged loader image records, and the TeX recorder's admitted `pdflatex.fmt`.
This is a read-only evidence consumer, not a native job or a successful Boolean.
Then make a fresh runtime `purpose:qualified` configuration using the derived
closure pin and run a normal ordinarily approved build for final delivery.

The first supported loader observation format is Apple's primary dyld UUID/path
log, with `DYLD_PRINT_LIBRARIES=1` and `DYLD_PRINT_LIBRARIES_POST_LAUNCH=1`.
Every non-system loaded image needs the exact admitted snapshot leaf. Declared
system images carry path/UUID and the current kernel/platform identity, without
invented regular shared-cache file pins. Missing/suppressed or logs outside the declared format,
changed UUID/host/bytes, undeclared dependencies or missing recorder inputs keep
qualification held. Linux preparation is representable but native qualification
is held until an actual supported loader evidence interface exists. This finite
scope does not establish whole shared-cache identity, universal ABI compatibility,
scientific correctness, visual acceptance or publisher applicability.

Report integrity exposes one `CustodyInputs()` identity map with a separate
presented-text tally and one explicit `CustodyAccumulator(policy)` through initial
and ending `_dependency`, `_operational_json` and `_executed` reads. The policy
must match the accumulator exactly. `_operational_new` commits complete serialized
bytes before writing and verifies the intended hash immediately; preserve the
returned pin for ending reads. Scientific `_raw` and `_new` bounds remain fixed.
`verified_result` obtains policy from the actual original ordinary config before
reading the saved result; finalization repeats current complete source/runtime
custody and all original integrity/whole-parent/CI3 gates.

## External author usage policy

Writer runtime accepts optional `usage_policy` (`strict_reported`, the compatible default, or `reserved_unknown`) and `max_output_bytes`. Reserved unknown requires external action and an explicit finite public-output byte bound. It keeps input/output/total usage null, rechecks the exact completed one-call reservation and campaign/source/model/actor joins, and never returns consumed calls or output reservations. Actual input/output token ceilings remain unverified; the full source-context and public-output byte bounds remain enforced without truncation. Strict mode requires complete reported telemetry satisfying both token ceilings.

External-response/v1 remains unknown. External-response/v2 adds a closed `usage_report`: `state`, exact three-key `tokens`, and `source`. Unknown requires null counts/source. Host-reported counts require a pinned public usage-only receipt containing schema_version1, kind (`provider_response` or `host_meter`), original request_id/request_sha256, invocation_id, observed_model, complete_invocation=true and the exact usage. The source object carries kind, invocation_id and its ordinary path/SHA256/size artifact pin. This retained host assertion is classified `external_host_reported`; it never becomes provider-observed transport or authenticates the actor. Account-level percentages and token estimates are not completion telemetry.

New prepared requests seal finite `completion_limits`. Completion files are bounded before parsing; the complete public value is bounded independently. Role receipt, manuscript collect and verify_author re-read the original response and usage evidence, including ending checks. Model provenance retains policy, nullable measurements, full reservation/call evidence and unverified token-bound status. These accounting modes grant no scientific, template, visual, publisher or execution authority.


## Initial runtime validation within one observation

Ordinary manuscript-build validation uses the existing live scientific
`ValidationSession` to share deterministic facts about an initially unqualified
runtime and its complete asset trees. Every original build load still reconsumes
its actual author, Graph, external response and source/review bindings. No author
receipt, approval, execution ceiling or acceptance result is memoized.

The first runtime proof uses the original full-byte validators. Every reuse
checks current controlling documents, exact selected policy, complete membership,
strict path/alias rules, modes and original guarded file identities. The final
session callback repeats the uncached original runtime/tree validators, followed
by the original complete session census. Any difference holds the observation.
The proof is discarded on success or error and is never shared across public
calls, approval writes, packet writes, worker/native execution or final review.
Legacy, qualified and custom-validator paths retain their ordinary validation.
This change does not qualify a runtime or establish measured performance.
