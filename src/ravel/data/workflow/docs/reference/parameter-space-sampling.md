# Supplied EasyScan scan contracts

`parameter-space-sampling` wraps the source-bound EasyScan CLI through the ordinary scientific-study
lifecycle. The required toolchain includes the framework, samplers and selected physics
programmes. Cold context and planning import no native engine and perform no installation.
A delivery retains raw source outputs; it does not qualify convergence, posterior coverage,
engine accuracy or scientific interpretation.

## Contract and intake

The task is `{"config":{"path":"operation.json","sha256":"...","size":123}}`.
The selected operation must satisfy the [scan contract schema](../../src/ravel/data/easyscan/scan-contract.schema.json).
Paths resolve relative to its pinned document. Use
`ravel parameter-space-sampling context --task task.json --output fresh-context.json` for cold inspection.
There is no installed question population or population command.

| Field | Supplied meaning |
|---|---|
| `schema_version` | `2` |
| `operation` | `run`, `read-returned`, or `continue-native` |
| `study_id` | Arbitrary nonempty identity; never selects an algorithm or physical convention |
| `question`, `ini` | Digest and size pins for the complete request/source record and attributed INI |
| `framework`, `workspace` | Each `{root, manifest}`; manifest has `schema_version:1, files:{relative_path:{sha256,size,mode}}` |
| `programmes` | Ordered numeric `programN` entries, each with `section, inputs, outputs, intermediates, mutable_paths, units, status` |
| `runtime` | `{python, trees, site_roots, versions}`; pinned interpreter, captured runtime trees, explicit package sites and version premises; `null` permits cold context only |
| `resources` | Explicit `max_seconds, max_ram_mib, max_evaluations, max_programme_calls, max_output_bytes, max_output_members, max_copy_bytes` |
| `report` | `{format, path, table}`; `format` is `json` or `csv`, `path` is the relative export destination, `table` selects a retained native table relative to the work root |
| `continuation`, `returned` | Exact predecessor/return-manifest pins for those operations, otherwise `null` |

The INI supplies the sampler, arbitrary named parameter axes and bounds, grid intervals or
point setting, worker count, initialization, constraints, programme chain, mappings,
result folder and plot directives. `Parallel threads` is explicit; multiple workers also
require `Parallel folder`. EMCEE requires explicit walkers. GRID retains the native
endpoint-inclusive interval law; it can have any supplied dimensionality. Serial-only
native sampler interfaces retain that limitation. Required fields or mappings omitted
from the contract raise `ScanInputError`, with `reason="missing_scan_input"` and the missing
`field`. Missing mappings are checked before external trees are inspected. No study identity
creates an intentional refusal, changes a count or supplies missing scientific input.

Each programme uses canonical relative paths. Its INI file mappings must match the supplied
ordered inputs and outputs, and every output variable must have a supplied unit. `status`
is a source-interface convention (`native` or the admitted PhaseTracer interface), never
an implicit study selection. Declare all retained intermediates and mutable logs explicitly.
Executable/source code cannot be declared mutable. Commands, expressions, bounds, units,
constraints and compiler/library choices remain source premises requiring scientific review.
Expression mappings are forwarded to the native tool; cold context never evaluates them.

The selected JSON export preserves the complete parsed table, row ordinals, raw lexemes and
invalid-row classifications. CSV preserves the source header fields and raw data rows,
including malformed, blank and nonfinite rows. An unavailable selected table is refused,
never replaced by a fabricated empty result. Native plot directives retain their source
format and supplied names; JSON/CSV selection controls the table export. Source-required
native table names are upstream interfaces rather than study-specific layouts.

## Migration and authority

A version-1 identity-bound document needs explicit migration: supply `study_id`, set
`schema_version` to `2`, and supply `report`. Preserve the selected request and INI bytes,
complete manifests, programme mappings, constraints, intermediates, status conventions and
resource ceilings. There is no conversion from an installed question identity and no
inferred parameter population. An old document lacking `study_id` gets the typed missing
input reason. Changing scientific inputs changes their commitments and requires a fresh
plan and approval. Old continuation/return identities must be regenerated against the
selected schema-2 contract; no stale identity is silently accepted.

`ravel.physics.parameter_space_sampling.specification(task, source=..., assumptions=..., actors=...,
max_seconds=...)` creates an unapproved schema-2 science specification. Supply proposer,
executor, physics critic, skeptical verifier and decider. Use `ravel plan --rundir fresh-study
--spec science.json`, actual approval, then `ravel run`. The existing method decision,
admission and supervised native-launch guard remain in force. The scope
`complete-original-parameter-space-sampling-delivery` permits delivery only, one attempt and no
automatic redo. Integrity, complete-population and native-semantics checks require ordinary
reviews. Cold context grants no execution authority.

The Graph `parameter-space-sampling-context` tool requires a pinned task and all dependencies returned by
`parameter_space_sampling.context_inputs(task, base)`. Supplied request/INI/config pins replace the
removed population dependency. Blinded critic and verifier roles cannot invoke this
producer tool. The source manifest retains the admitted framework interface revision;
source/runtime membership is checked by planning and again around dispatch.

## Native observations and numerical boundaries

The child authenticates source/runtime assets, binds argv and cwd, and calls the native CLI
once in a private work copy. Recording wrappers forward programme and sampler calls once,
preserving returns and exceptions. Raw cards, outputs, intermediates, full sampler arrays,
worker exits and nonfinite payloads remain retained. Shared resource ceilings stop further
dispatch; exceeded bounds yield failed partial output. Root exit zero cannot establish
parallel-worker success. Immutable source bytes, permissions and complete membership are
rechecked. Intended emitted bytes are committed before writing and checked immediately
and at ending reads. These finite observations do not establish arbitrary shell descendant
containment or detect every restored transient mutation.

RANDOM counts prior trials separately from successful saved rows. BESTFIT's point setting
is a native iteration ceiling, not a likelihood-call count. EMCEE preserves full scheduled
step/walker slots separately from its finite exported chain; physical coordinates bind to
the actual captured native prior projection. DYNESTY retains samples, likelihoods, weights,
evidence arrays and call counts; diagnostic weights use the final evidence normalization,
with unavailable/overflowing normalization explicit. Gaussian normalization constants are
omitted by the native likelihood, so absolute physical evidence is unqualified. MCMC retains
the source acceptance, dwell and proposal conventions. Rows and weights are not independent
collision events. Python random seeding does not establish complete parallel or sampler
reproducibility. Supplied initial points outside their prior remain disclosed and unclamped.

`continue-native` supports only native MCMC final-row continuation on a complete private
predecessor copy with exact configuration/runtime identities. Its manifest fields are
`schema_version, config_identity, runtime_identity, method, root, files`. Required predecessor
tables and complete membership are authenticated. No sampler/RNG checkpoint is restored.
Ordinary Ravel resume verifies its existing attempt rather than reinitializing a scan.
`read-returned` consumes a supplied complete frozen work return with
`schema_version, config_identity, runtime_identity, root, files, observation`; it never
claims fresh execution or manufactures native custody from supplied observations.

Finite ceilings remain wall time at most 3600 seconds, sampled RSS 512 through 8192 MiB,
evaluations/programme calls at most 100000 each, complete source/runtime trees at most 20000
members and 4 GiB, member size at most 64 MiB, and explicit bounded output and copy resources.
Detached timed/Popen programme executors are refused. No download, installation or build
occurs through the scan adapter. Native runtime, engine, sampler and cleanup qualification
requires separately admitted execution. Software fixture tests establish interface behavior.
