# Model-bound diagrams, estimates and amplitudes

RAVEL connects a selected model and process to complete FeynGraph diagram enumeration, source-matched HEPTAPOD NDA/Diagrammatica EDA consumers, and an explicit FeynArts/FeynCalc amplitude operation. The ordinary science lifecycle supplies source/runtime capture, bounded execution, reports and review. The [required installation procedures](../installation.md#what-gets-installed) provision the engines in project-owned prefixes.

## Select the operation

| Operation | Actual source calls | Delivered population |
|---|---|---|
| `feyn-graph` | `Model.from_ufo`, `Model.from_qgraf` or explicitly selected `Model`; `DiagramGenerator(..., model, selector).generate()` | Every selected diagram, external and internal identities, momentum assignments, symmetry/sign/order data, model readback and requested native SVG/TikZ exports |
| `diagram-analysis` | Existing finite UFO compiler and `diagrammatica_code`; released `EstimateDecayWidthNDATool._run` when an NDA runtime is supplied | One row per enumerated diagram, including unsupported/failed rows; source-matched scalar EDA code, approximate NDA results and exact unapproved scalar-symbolic handoffs |
| `feynarts-amplitude` | `CreateTopologies`, `InsertFields`, `CreateFeynAmp`, `FCFAConvert`; `Paint`/`Export` for requested PDFs | Whole inserted/converted amplitude population, its coherent symbolic total, raw canonical tensor formulas and actual native PDF exports |

A supplied UFO is passed to the real engine. The builtin Standard Model in Feynman gauge is a distinct explicit model choice. The HEPTAPOD UFO placeholder and its model-omitting generator call are not used. QGraf uses the released compatibility parser, not every possible QGraf option. FeynGraph particle spin is `2s`; the static UFO compiler separately interprets UFO `2s+1` conventions.

## Ordinary and research entry points

All three operations accept `task={"input": "/absolute/request.json", "input_sha256": "<actual SHA256>"}`. Each request pins the original task, complete source trees and their manifests, selected physical inputs, runtime, conventions and finite wall/RAM/output limits. A tree manifest is the existing `model_tool_bridge.source_tree(root)` schema1 complete file map. Native runtime trees use the existing `finite_integrals.runtime_tree` schema and supplied interpreter; they are not loose package names.

```sh
ravel feyn-graph inspect --input enumeration.json --input-sha256 "$ENUMERATION_SHA256"
ravel diagram-analysis inspect --input consumers.json --input-sha256 "$CONSUMERS_SHA256"
ravel feynarts-amplitude inspect --input amplitude.json --input-sha256 "$AMPLITUDE_SHA256"
ravel plan --rundir "$STUDY" --spec "$STUDY_SPECIFICATION"
ravel status --rundir "$STUDY" --write
```

The specification uses the selected operation as its mode in the existing schema2 science/research blueprint. Its prospective policy admits one attempt, zero redos and only the operation's delivery claim scope: `complete_model_bound_diagram_delivery`, `model_bound_diagram_analysis_delivery` or `source_bound_feynarts_amplitude_delivery`. Planning and inspection grant no execution authority. The normal approved study route runs the supplied task; a follow-up scalar evaluation gets its own concrete plan.

The research coordinator's existing `research_tools.prepare`/`plan_workflow` reads these actual adapter APIs and materializes the ordinary blueprint. A Graph `diagram-context` tool has parameters `{"mode":"feyn-graph|diagram-analysis|feynarts-amplitude", "request_input":"<declared Graph input ID>"}`. Use one literal implemented mode; declare the task and every dependency returned by `context_inputs` as exact Graph inputs. Complete source/runtime trees are verified against their authenticated manifest pins; the compact Graph inventory does not claim their whole bytes were presented to a model. The ordinary execution inventory retains every physical member. This is drafting context and cannot act as a blinded vote or launch the engine. Research budgets, parent quantity obligations and the normal three-role review remain with the existing cycle.

## Complete enumeration and rendered exports

The enumeration request explicitly supplies the ordered process list (`id`, `incoming`, `outgoing`, `loops`, full external/loop `momentum_labels`, and ordered source-defined `selectors`), the admitted model tree/entry/gauge, complete original UFO vertex names and conventions. The source roster follows `vertices.py`/`Vertex` then `CT_vertices.py`/`CTVertex`, preserving declaration order and every counterterm name; the native splitting roster must match it exactly. Vertex names use a single plain quoted literal, optionally with the released lowercase `r` prefix, whose unchanged interior equals its Python value; escapes, concatenated or multiline literals and other prefixes refuse before dispatch. A `None` splitting alone does not prove existence: every unsplit name and every split target must occur in the actual native vertex census, and the full UFO source-to-native membership must cover that census. Native-ignored two-point counterterms therefore remain an explicit incomplete-model refusal, with the original source and native census retained. Selectors expose only the released typed methods; no implicit one-particle-irreducible default is added. `max_diagrams` bounds each whole process; exceeding it preserves a failed partial native record rather than exporting a truncated complete population.

`render.formats` selects native `svg`, `tikz`, or both. `max_visualize` bounds presentation only. The whole structured census remains in `native/enumeration.json` and `diagram-result.json`. Result pointers are `/delivery/processes/<index>/diagrams` and `/delivery/processes/<index>/renders`; each render retains diagram ID, source-native format, relative path, SHA256 and size. Paths are relative to the adapter's `native/` directory. The ordinary report embeds the actual SVG and links every requested export.

A manuscript may use a source-native self-contained SVG with its selected, source-bound SVG-to-PDF renderer, or a native FeynArts PDF directly. SVG/TikZ availability does not imply a FeynGraph-native PDF or numerical comparison. A render/figure contract and independent caption/model/process review still apply.

## Source-matched estimates and scalar EDA

`diagram-analysis` pins a complete delivered enumeration, the actual existing UFO request template, a whole HEPTAPOD705b03 source tree, and an explicitly selected NDA runtime or scalar symbolic template. The exact existing EDA backend stays cb771f8c: source epochs are retained separately. The compiler binds actual vertex/PDGs, source leg order, masses, Lorentz/color tensor projection and complex coupling coordinates. Supported EDA remains neutral one-vertex tree SSS/SFF/VFF with its original finite restrictions. Split vertices, crossing, unsupported fermion structures and loops are explicit rows rather than silently dropped diagrams. A passed source-bound enumeration is not an independently accepted physics result; the consumer retains that distinction.

Released NDA receives explicit model-derived masses, spins and real coupling coordinates; complex phases are refused by that approximation. NDA scaling estimates are approximate per-diagram widths. Squared diagrams cannot be summed as an exact coherent process amplitude or branching ratio.

For a supplied scalar symbolic template, each supported diagram gets an exact generated `decay.wl`, a complete source manifest and `symbolic-handoff.json`. `rows[*].symbolic_handoff` contains the ordinary mode/task/result identity and original diagram lineage. The source-derived marker census, `ravelWidthPoint`, units and complex substitutions feed the existing HEPTAPOD parser/converter. These handoffs are prepared, not executed by `diagram-analysis`; an exact symbolic or numerical result requires the later admitted `symbolic-evaluation`. No width or BR is inferred from a prepared script.

## FeynArts source preparation

FeynArts3.12 and FeynCalc10.1.0 are exact required sources. Preserve the licensed application's existing user/license location and global initialization. Start with the official archive SHA256 `190cb5a2ecbbe35136f218d462b03731c6b797ecf65f088affc89ea01ef5784a` and FeynCalc revision `fe6645114a794c2aed96d4f6c3512ef1b1affac6`. Copy FeynArts into a fresh project-owned prefix before patching; never patch the pristine archive/source.

The following is a source-provisioning Wolfram script for the authorized user/root, with literal absolute prefixes substituted from the admitted installation. It is not run during planning or RAVEL evaluation:

```wl
$LoadAddOns = {};
$FAPatch = False;
FeynCalc`$FeynArtsDirectory = "/absolute/fresh/project/feynarts-patched";
Get["/absolute/pinned/feyncalc/FeynCalc/FeynCalc.m"];
FAPatch[Quiet -> True, FAModelsDirectory -> "/absolute/fresh/project/feynarts-patched/Models"];
Get[FileNameJoin[{FeynCalc`$FeynArtsDirectory, "FeynArts.m"}]];
ravelPreparedFeynArtsDirectory = FeynArts`$FeynArtsDir;
If[!StringQ[ravelPreparedFeynArtsDirectory] ||
   FileNameSplit[ExpandFileName[ravelPreparedFeynArtsDirectory]] =!=
   FileNameSplit[ExpandFileName[FeynCalc`$FeynArtsDirectory]], Abort[]];
```

```sh
cp -R "$RAVEL_NATIVE_BUILD/tools/feynarts-original/FeynArts-3.12" "$RAVEL_NATIVE_BUILD/tools/feynarts-patched"
"$WOLFRAM_KERNEL" -noinit -noprompt -script "$SOURCE_PATCH_SCRIPT"
```

The selected Classes `.mod` and Generic `.gen` files must belong to an explicitly supplied, already-patched whole model tree. A separate custom model may use the released `FAPatch[PatchModelsOnly->True,FAModelsDirectory->...]` on its fresh project-owned copy. FeynRules-exported models carry their actual export/source lineage; this operation does not invent a UFO-to-FeynArts conversion.

Record the exact original archive and FeynCalc revision, whole patched FeynArts/model file maps, source attribution and `physics_validated:false` in `patched_source_receipt` with schema1/operation `FeynCalc_FAPatch_source_preparation`. Runtime admission checks those exact current trees. The receipt binds declared source preparation; it does not certify a model or a successful amplitude oracle. Evaluation disables automatic patching, binds the loader through ``FeynCalc`$FeynArtsDirectory``, and records ``FeynArts`$FeynArtsDir`` from the actual loaded source before and after the amplitude script. Its configured and loaded directories must match the staged admitted component; the explicit ``FeynArts`$ModelPath`` must match the staged model tree. A shadowing ``Global`$FeynArtsDirectory`` is not loaded-source evidence.

## Amplitude request and consumers

`feynarts-amplitude` uses the existing symbolic request schema2, adding an explicit `feynarts` record: version3.12, complete tree and model_tree, entry `FeynArts.m`, literal classes_model/generic_model names and patched_source_receipt. Scripts add a typed `feynarts_process` record: explicit field kinds/indices/signs, ordered external and loop momenta, loop order, vertex-adjacency scope, diagram cap and native PDF choice. Generate the exact source with:

```sh
ravel feynarts-amplitude script --input process.json --output fresh-process.wl
```

Each script supplies exactly one result with the process ID, symbol `ravelAmplitude`, representation `feyncalc_tensor`, explicit variables/units/dimension/conventions/assumptions and no guessed scalar numerical points. The operation checks the source script equals the deterministic typed process. `Truncated->False` retains spinors; `FCFAConvert` retains sums and returns the complete list before coherent `Total`. Actual topologies, insertions, original and converted amplitudes remain in each script's canonical sidecar and result `scripts[*].feynarts`.

The delivered tensor is canonical InputForm, not a fabricated Python scalar or completed loop integral. `results[*]` retains representation, formula, declared basis/units and literal delivered status. The existing scientific-context `symbolic-record-census` can require that exact ID/formula population; it checks delivery, not algebraic truth. Native PDFs appear in `scripts[*].rendered_pdf` as exact path/SHA256/size and in the ordinary report. Scalar reduction, independent free-variable/basis verification, phase-space/spin/color integration and integral convergence remain separate requested scientific operations. Existing finite scalar pySecDec calls do not supply those missing tensor reductions.

## Source and validation scope

The [API map and licenses](../../src/ravel/data/diagram_tools/) identify actual released code. FeynGraph is MPL2.0, HEPTAPOD/Diagrammatica remains external GPL, FeynArts retains its release LGPL notice, and FeynCalc retains its upstream license. RAVEL authors typed transport, source/census checks and ordinary joins; original algorithms are not relabelled as RAVEL work.

Source construction and pure software controls do not establish compiled Rust/CAS readiness, gauge/model correctness, amplitude accuracy or a complete research question. Failed, partial and unsupported entries stay in the original population and result denominator. Native oracles, actual licensed/kernel loading, rendering and scientific validation require separate root admission.
