# Source-bound routine builds

`mode: analyze`, `task.backend: routine-build` builds supplied unchanged source
and runs a declared executable/listing probe. It does not process events or
certify a detector, selection, paper reproduction or statistical interpretation.
It uses the supplied-study approval, supervision and review lifecycle described
in [scientific studies](../workflow/reference/scientific-studies.md).

The task has exactly two fields:

```json
{"backend": "routine-build", "input": "routine-build.json"}
```

The source can be a catalogue seed or an explicit capsule for a previously
unknown routine. Routine-name registration is not an admission requirement.
`analysis_sources.from_catalogue(catalogue, row, root)` verifies selected pinned
blob bytes and generates an incomplete dependency-review seed. Review its
dynamic assets, helper includes, submodules and runtime requirements before
proposing a build. A missing feature match cannot prove no dependency.

## Source capsule

The `analysis-source-capsule/v1` document has exactly these fields:

```json
{
  "schema_version": 1,
  "kind": "analysis-source-capsule",
  "framework": "cpp",
  "routine": "MyRoutine",
  "source": {
    "repository": "supplied",
    "revision": null,
    "description": "Explicit supplied source and dependency review"
  },
  "root": "source",
  "files": [
    {"path": "main.cc", "sha256": "<64 hex characters>", "role": "compile"},
    {"path": "include/helper.hh", "sha256": "<64 hex characters>", "role": "header"}
  ],
  "layout": {"include_dirs": ["include"], "asset_dirs": []},
  "dependencies": [
    {"name": "local helper", "kind": "source", "status": "resolved",
     "files": ["include/helper.hh"], "reason": "Included helper bytes are bound"}
  ],
  "dependency_review": {"complete": true, "description": "Scope of the supplied review"},
  "submodules": []
}
```

Framework is `cpp`, `rivet` or `simpleanalysis`. Git sources use an HTTPS
repository and exact 40-character commit instead of `supplied`/`null`. These Git
identities and review-completeness declarations remain supplied assertions;
the capsule verifier establishes the actual declared file bytes and layout.

File roles are `compile`, `header`, `model`, `preprocessing`, `reference`,
`calibration`, `configuration`, `license`, `build`, and `data`. Paths are unique,
normalized and relative. Symlink traversal, missing files, changed bytes and
Git LFS pointer content are rejected. Equal basenames in different declared
directories retain distinct identities. Layout directories must contain declared
files. A source-booked routine need not have a reference YODA file for its build.

Dependency kind is `source`, `asset`, `submodule`, `runtime` or `package`.
Status is `resolved` or `unresolved`. Source/asset/submodule obligations marked
resolved need declared files. Every unresolved obligation prevents a build.
Submodules contain `path`, HTTPS `repository`, exact `revision`, and must have
their effective content explicitly represented in the file inventory.

Positive ONNX helper/include cues require explicit bound model files and an asset
obligation. This catches helper-constructed paths missed by the old literal scan.
It is not a complete C++ dependency parser. For example, SimpleAnalysis
`TriHiggs6b` constructs twelve model/preprocessing filenames from three network
names and even/odd folds. Resolve the actual files in a reviewed capsule rather
than treating unmatched suffix literals as proof of missing assets.

## Build input

`routine-build.json` has `schema_version`, `source_capsule`, `recipe`, `runtime`
and `probe`:

```json
{
  "schema_version": 1,
  "source_capsule": "capsule.json",
  "recipe": {
    "name": "cpp-executable",
    "compile_units": ["main.cc"],
    "output": "my-probe",
    "flags": ["-std=c++17", "-O0"]
  },
  "runtime": {
    "tools": {"compiler": {"path": "/absolute/path/clang++", "sha256": "<64 hex characters>"}},
    "artifacts": [],
    "environment": {}
  },
  "probe": {
    "executable": "$BUILD_OUTPUT",
    "arguments": ["--list"],
    "expected_exit_code": 0,
    "stdout_contains": ["MyRoutine"]
  }
}
```

Planning and `inputs(task, base)` read and hash every declared source, tool and
runtime artifact. They execute no compiler, source script, Git command or runtime
probe. Paths in the build configuration and capsule root resolve against the
study specification's input base. The generated plan retains this `base_dir`.

The three closed recipes are:

- `cpp-executable`: compile declared units and include directories, then probe
  the actual produced executable. Accepted flags are standard language versions,
  optimization/debug/warning flags and simple macro definitions. Arbitrary plugin,
  linker, response-file and forced-include flags are refused.
- `rivet-plugin`: use a bound `build` tool with one worker and a `RivetNAME.so`
  output, then a bound `probe` runtime tool whose expected stdout includes the
  exact routine identity. The preserved source/metadata/model layout is exposed
  through explicit Rivet analysis, info, reference and data search paths. Build
  paths cannot contain whitespace because of the upstream builder's protocol.
- `simpleanalysis-analysisbase`: require bound CMake, compiler,
  `AnalysisBaseConfig.cmake`, explicit `CMAKE_PREFIX_PATH`, root CMake source,
  submodule content and every staged compile unit. A portable ROOT/RestFrames
  hand-port environment does not meet this prerequisite. The declared output may
  be a build-relative path such as a platform `bin/simpleAnalysis` path. The CMake
  target is its basename. This recipe's actual compatibility still requires an
  observed build; schema support is not that evidence.

Runtime tool names are `compiler`, `build`, `cmake` and `probe`; each binds its
path and SHA256. Executable aliases preserve invocation semantics while their
actual target bytes are hashed. Runtime artifacts are explicit ordinary
`{path, sha256}` files. Environment keys are limited to `PATH`, `SDKROOT`,
`LIBRARY_PATH`, `LD_LIBRARY_PATH`, `DYLD_LIBRARY_PATH`, `PYTHONPATH`,
`PKG_CONFIG_PATH` and `CMAKE_PREFIX_PATH`. The worker clears inherited credentials
and ambient compiler flags, stages a private source copy and limits build workers.
This is not OS isolation. External C++ and CMake execute code and require an
appropriate trusted or isolated worker under the approved study.

## Observed outputs and limits

Actual execution writes `source-inventory.json`, `build-plan.json`,
`compiler.log`, one `build-N.log` per command, `probe.log`, the staged source and
binary, and `build-receipt.json`. Process logs are JSON containing exact argv,
return code and raw base64 stdout/stderr. A failed compile or probe retains its
log and cannot produce a passing receipt. A successful zero exit without every
declared expected probe string also fails. Original source/runtime identities and
staged source bytes are rechecked after execution.

`verify_receipt(receipt, plan, base, outroot)` performs no execution. It rebinds
the original build input/capsule, complete source inventory, declared runtime,
commands, staged source, binary, every process log, compiler observation and
probe stdout. Changing a log and merely updating its hash cannot bypass command,
return-code or expected-output checks. The receipt verifier establishes retained
evidence integrity; authentication of arbitrary caller-supplied process logs
requires lifecycle custody. Every result retains `physics_validated: false`.

A registered executable is useful evidence of buildability and a loaded runtime
interface. Complete event exposure, selection/observable semantics, calibrated
response, reference agreement, full output denominator and inference/data-use
closure are separate admission obligations. An ONNX routine may catch a missing
model exception and still fill inclusive observables. A listing probe does not
close that event-execution hazard.

## Reuse on supplied events

The separate `rivet-built` analyze backend consumes an observed `rivet-plugin`
build receipt. It accepts a source-booked routine absent from the catalogue and
uses the delivered plugin without rebuilding. Its exact task fields are:

```json
{
  "backend": "rivet-built",
  "routine": "MyRoutine",
  "build_receipt": "built/build-receipt.json",
  "build_plan": "built/build-plan.json",
  "events": "events.hepmc",
  "metadata": "event-metadata.json",
  "runtime": {"python": "/bound/runtime/bin/python", "version": "4.1.3"},
  "observables": [
    {"path": "/MyRoutine/pT", "axes": [{"name": "pT", "unit": "GeV"}],
     "representation": "integrated", "normalization": "absolute", "unit": "pb"},
    {"path": "/MyRoutine/count", "axes": [], "quantity_kind": "scalar_counter",
     "representation": "integrated", "normalization": "absolute", "unit": "1"}
  ],
  "options": {},
  "seed": 23
}
```

This backend requires the science specification version 2 lifecycle, prospective
review policy, bounded attempts, genuine CHECK-IN 1 assent, supervised execution
and scoped scientific review. Receipt integrity alone does not authenticate a
caller-supplied process history. The original `rivet` backend retains its exact
continuous-observable contract and catalogue/reference-binning requirements.

The delivered receipt and plan must retain their conventional filenames in the
same original output directory. Read-only planning rebinds the complete original
build configuration, capsule, source, runtime, staged source layout, compiler and
probe logs, source inventory and binary. These are all scientific-stage inputs.
The selected Python must belong to the unchanged bound build runtime. The Rivet
executable and environment come from that build plan. Callers cannot replace the
plugin, supply a fallback source directory or override runtime dependencies.

Execution rechecks that evidence before launching events and after export. It
uses only the delivered binary in `RIVET_ANALYSIS_PLUGINS`, preserves the staged
source and asset directory layout, checks the actual runtime version, uses one
worker and an explicit seed, and reconciles the all-event RAW event counters with
the independent HepMC census. Changed event or metadata bytes, an omitted
requested output, a changed dependency or a changed binary fail. Outputs retain
`histograms.yoda`, `observables.json`, event census, execution/export logs,
`runtime-version.json` and `build-reuse.json`. Every result has
`physics_validated: false` and `rebuild: false`.

Continuous requests have the existing five fields. A scalar request explicitly
adds `quantity_kind: scalar_counter` and requires empty axes, `integrated`
representation and `absolute` normalization. It accepts a Counter or finalized
Estimate0D with a matching RAW Counter. The export retains a singleton bin with
empty edges, finalized value and marginal uncertainties, direct RAW sumW,
sumW2 and entries, and direct finalized Counter moments when that object exists.
A finalized Estimate0D does not acquire invented Counter moments. A selected
RAW Counter uses its own moments. Missing or wrong RAW storage, incompatible
entries, unknown scalar types and invalid weighted moments fail.

Scalar output bypasses continuous bin-width operations. It does not provide
cross-counter covariance, a count-data likelihood or permission to reinterpret
a weighted yield as Poisson observations. Units remain an explicit scientific
obligation. For example, SYN_9011_I1400 scales counters to an expected yield
at 35.9/fb; those finalized outputs have unit `1`, rather than a cross-section
unit inferred merely from the supplied cross section.

## Source-bound centrality calibration preloads

Both `rivet` and `rivet-built` tasks may supply `centrality_preload` in a
schema-2 scientific study. Set `options.cent` explicitly to `GEN`, `IMP` or
`USR`; these modes require the exact source-declared generated calibration
object, with `_IMP` or `_USR` appended for those modes. `USR` requires HepMC3;
this does not establish that its event attributes are applicable.

The closed contract contains `schema_version: 1`, one calibration-only file
`path` and `sha256`, `mode`, `calibration_analysis`, `histogram`, the bound
`routine_source` excerpt and `source_dependencies` excerpts, `provenance`,
`weight_policy: source_calibration_unverified`, and an `origin` object with the
full original calibration output's `path` and `sha256`. Each source excerpt has
`path`, `sha256`, `first_line`, `last_line`, and literal `text`. The routine call
source must be present in the selected source/build input graph. Excerpt binding
is lexical evidence; it does not prove the C++ branch or projection was executed.

`ravel.physics.rivet_preload.prepare(source_path, expected_sha256=...,
object_path=..., output_path=...)` extracts the chosen Estimate1D block verbatim
into a fresh file. It retains the complete original output as a separate input.
No calibration values, flow states, native marginal errors, widths or weights
are changed. The normal scientific `plan`, `approve`, `run` and review workflow
then consumes the contract; this helper grants no approval or native authority.

Only a single calibration object/file is currently admitted. Rivet4.1.3/4.1.4
`AnalysisHandler.readData` replaces its preload map on each call, so multiple
files would silently discard earlier ones. RAW/global counters and unrelated
objects are excluded from the dispatched subset to prevent accidental resumed
histograms or exposure. The V1 domain is a continuous Estimate1D with finite
nonnegative central bin values and positive finite area/value sum; signed,
masked, multidimensional and other preload purposes require separate support.
The source percentile constructor sums finite values without widths; the helper
never substitutes a width-weighted CDF or calculates percentiles.

The event command supplies `--preload-file` and writes
`centrality-preload.json` with the literal native object, origin and dispatched
command. Files/excerpts are checked again after execution. Native consumption,
calibration weights, generator/beam matching, centrality selection, detector and
paper applicability remain unverified until an actual source-qualified study.
Omitting the field preserves the existing command/default `cent=REF` behavior.

Calibration admission uses a closed V3 native-writer grammar. One literal `---`
separates annotations from data. Annotation keys must be plain scalar names,
unique, with a literal matching `Path` and, if present, `Type: Estimate1D`.
Quoted/aliased/multiline keys and values outside the closed plain scalar subset
are unserved, even where general YAML could parse them. Geometry/error labels
must occur in the data phase before the numerical header. Any masking directive
is refused, including forms with indentation that the native reader trims.
Native numeric/header padding is retained. No input is canonicalized or repaired.
These checks are source-only admission; runtime reader/version behavior still
requires native qualification.
