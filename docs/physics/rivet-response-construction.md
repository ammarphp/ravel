# Native Rivet response construction

`ravel.physics.rivet_response_component` constructs native detector-response source. Rivet performs every random draw, transformation, constituent/tag update and MET calculation. The compiler samples no events and infers no calibration. The released source interface is explicitly Rivet 4.1.4; a differently labelled or merely installed runtime is not admitted by this source version declaration.

The optional `response` stage in `rivet_event_components.compile_component` and `instantiate` runs after the existing particle/dilepton/FastJets/MissingMomentum construction and before optional event-shape access. Older recipes and their returned source are unchanged. `SmearedParticles` takes an existing ParticleFinder, ordered callbacks and explicit reconstructed-object cuts. `SmearedJets` takes an existing JetFinder, ordered callbacks and explicit b/c tag functions. A null tag function means the native truth-tag fallback; it does not mean zero efficiency or the default native perfect-tag argument. `SmearedMET` takes a prior **MissingMomentum**, not another SmearedMET. `TauFinder` constructs native unstable-generator taus with explicit decay/origin/cuts; it is not detector tau reconstruction.

## Recipe

The response stage is a closed object:

```json
{"schema_version":1,"kind":"native-rivet-response-components","native_api":"4.1.4","functions":[],"nodes":[]}
```

A function has `id`, `type` and `value`. The six callback types are `particle_eff`, `particle_smear`, `jet_eff`, `jet_smear`, `met_params` and `met_smear`. A builtin value is `{"kind":"builtin","name":"ELECTRON_SMEAR_ATLAS_RUN2"}` and must match the released literal type. The finite 162-name catalogue covers native literal signatures. Parameterized factories, inline lambdas and source-local functions use `source_expression` instead:

```json
{"kind":"source_expression","binding":{"path":"response-proofs/original.cc","sha256":"FULL_SOURCE_DIGEST","size":1234,"start":100,"end":200,"expression_sha256":"EXACT_SPAN_DIGEST"}}
```

`source_units` supplies immutable complete bytes for that ordinary capsule-relative file. The compiler authenticates full bytes and the exact byte span, uses the expression unchanged, and records the complete source dependency. This is a source/type declaration, not proof that the expression compiles or has correct physical applicability. The capsule must retain the complete proof file as header, configuration or calibration. No separate unchecked pathname reread is used.

Nodes have `kind`, distinct `id`, `projection_name` and explicit `outputs`. Additional fields are:

| Kind | Fields | Native meaning |
|---|---|---|
| particles | input, steps, cuts, pids | ordered native transforms, then reco cuts |
| jets | input, steps, b_tag, c_tag | ordered native transforms, then tags on smeared kinematics |
| met | input, params, smear | vector callback, parameter callback, or both; native vector precedence |
| tau | decay, origin, cuts, pids | native unstable tau decay/origin selection |

Particle/jet outputs use explicit access and cuts; truth access and `taus()` do not silently consume unsupported cuts. MET output names distinguish missing/visible, scalar/vector, pT/Et, resolution and significance. Momentum units are explicitly GeV, significance is dimensionless. Resolution/significance requires a parameter callback. An empty output list leaves the existing enclosing native routine's access and analysis body intact.

## Ordinary source/build/event delivery

The pure public API follows the existing pipeline:

1. `rivet_event_components.compile_component(recipe, source_units=files)` lowers the combined typed IR; `instantiate(template_bytes, expected_sha256=..., recipe=..., source_units=files)` fills the three exact whole-line EVENT slots.
2. `rivet_response_component.materialize(original_capsule, compile_unit=..., template=..., expected_sha256=..., recipe=..., files=..., root=..., build_template=...)` writes a fresh **complete** source tree. `files` must contain every original capsule member as immutable bytes with the original expected digest, including full model/reference/calibration/configuration assets. Only the selected compile unit changes. The optional build template is an ordinary routine-build/v1 configuration; it retains its fields except the new capsule path. Runtime pins must be supplied before actual admission; the API invents none.
3. The returned `capsule` is a normal `analysis-source-capsule`. `analysis_sources.inventory` and `bindings` inspect it. It has a fresh identity, incomplete dependency review and changed-native-source obligations. The returned `build_task` can enter existing native construction/source review and `routine_build.inputs`/`build_plan`; normal admission refuses until fresh source and complete dependency/runtime review are supplied.
4. After root-authorized ordinary build and build/source reviews, the existing built-Rivet event route in `existing_events` consumes the build evidence. Existing quantity contracts, native output tables, complete named weight vectors, RAW counterparts, counter/flow/group covariance and normalization checks remain unchanged. This compiler does not create event authority, an output contract or a physics vote.

Before any write, materialization refuses equal, descendant or ancestor overlap with the original source root, including canonical overlap through existing aliases or dot segments. Existing original-root and destination-ancestor device/inode identities also detect directory aliases whose case spelling is retained by canonical path resolution. Relative capsule roots are interpreted against the invocation working directory; callers loading a capsule from another base must make that root absolute. The original root need not exist for this lexical/canonical protection, and no new source-liveness authority is inferred. This guard is an endpoint observation, not a filesystem lock against adversarial concurrent renames. Materialization also refuses a preexisting destination, missing/extra/substituted original files, unretained callback proof, unsafe aliases and changed generated source/asset/metadata. It records every generated digest and size, checks the committed leaf identities after consumption and repeats endpoint/ancestor identity observations before return. This is a time-local custody check, not a lock or permanent proof against changes after return. Partial files remain on a refused operation as failure evidence.

## Native laws and limitations retained

Particle efficiency draws short-circuit only as the native source does; reco cuts follow all transforms and kept objects gain original constituents. Jets recover original constituent/tag vectors when a smear function drops them, then tag on smeared kinematics. Released 4.1.4's nontrivial c-tag random branch uses **beff** rather than **ceff**. This implementation preserves that source and records a review obligation; it does not certify an idealized c-tag law.

MET keeps original scalar sums; vector smearing uses SPT for the pT vector and SET for the Et vector, while native parameter sampling for pT uses SET. Native significance/resolution access has its own source semantics, including the released Et accessor returning pResolution. Missing vectors retain the native negative-visible convention. `RIVET_DISABLE_SMEARING`, source function addresses/lambda equivalence, RNG state and projection-cache behavior require actual runtime witnesses. The API neither sets the environment nor substitutes an identity model.

The source inventory's 547 denominator is unchanged. Twenty lexical opportunities reduce to 18 noncomment routine references; SYN_9018_I1134 and SYN_9019_I1185 mention TauFinder only in comments. Some remaining class references are includes without a corresponding constructor. Prepared complete source capsules and mapped constructor spans are source facts; three complete changed-source controls and pure tests are not qualification of all 18 routines.
