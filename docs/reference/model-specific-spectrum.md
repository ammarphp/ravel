# Named NMSSM spectrum and model-point preparation

The named profile NMSSM-FlexibleSUSY-2.9.0 extends the existing generated-spectrum
operation. It uses the released 2.9.0 common framework and pregenerated NMSSM C++
solver, preserving every admitted source member and mode. It does not invoke
SARAH or Wolfram to regenerate the solver. The existing schema-1 CMSSM operation
is retained; the named profile uses schema 2.

The provider, CLI and Graph route are implemented. Portable controls use inert
native returns and synthetic review stand-ins. Actual compiler compatibility,
solver convergence, decay results and physical model validity are unqualified.

## Source, input and runtime

The named source capsule contains 1,003 files from the official framework export
and 127 released generated NMSSM files. Its whole file/hash/mode census must equal
the shipped profile. A model name or a few representative files cannot replace
this check. The source is GPL-licensed; LICENSE.FlexibleSUSY.txt accompanies the
profile. The public release and its generation workflow are primary sources:
[2.9.0 release](https://github.com/FlexibleSUSY/FlexibleSUSY/releases/tag/v2.9.0),
[README](https://github.com/FlexibleSUSY/FlexibleSUSY/blob/v2.9.0/README.rst),
[model packaging](https://github.com/FlexibleSUSY/FlexibleSUSY/blob/v2.9.0/.github/workflows/package-models.yml).

The config selects operation flexiblesusy-2.9.0-generated-NMSSM, profile
NMSSM-FlexibleSUSY-2.9.0, source/Boost/Eigen capsules, fixed compiler tools,
explicit runtime file pins, a supplied input_card pin, calculate_decays, and
loop_library. The existing compiler contract selects the regular clang-22 driver
and creates the C++ argv0 wrapper. Compiler/GSL/system support still needs actual
runtime selection; a finite file census does not establish complete SDK or OS
closure.

All six NMSSM inputs are explicit: MINPAR 1 m0, 2 m12, 3 TanBeta, 4 SignvS,
5 Azero, and EXTPAR 61 LambdaInput. SignvS is +/-1 and TanBeta is positive.
The supplied card must explicitly disable force_output and choose loop-library
setting 31. All ten FlexibleDecay settings are recorded. The adapter selects no
implicit spectrum point and changes no original card.

Decay calculation requires an explicitly selected Collier or LoopTools build,
complete pinned include/library directories, and the matching native input
choice. HiggsTools and Lilith subprocess options are excluded. With decays
disabled, absent widths cannot become zero or exporter defaults. With decays
enabled, a total width does not establish complete channels or lifetime accuracy.

## Ordinary build and return

Use ravel model-spectrum prepare --request REQUEST.json --out PROPOSAL to create
an ordinary generated-spectrum specification. The request is schema 1 with
operation build, pinned config and review_policy, explicit supervisor_seconds,
and the original goal_binding or null. Graph uses the model-spectrum-plan action
with request_input and output_dir; source/card/policy/parent dependencies must be
actual Graph inputs. Preparation grants no execution authority. A fresh ordinary
plan, exact Check-In 1 assent and an owned native lease remain necessary.

The shared engine performs isolated configure, make -j1 and run_NMSSM.x phases
with inherited 120/1200/60-second caps within a 1440-second stage. It uses
--with-models=NMSSM and --disable-meta. Every original restored source/header
member, input card, fixed driver and compiled target is checked across phases.
Selected input is copied into the fresh work directory. Native stdout/stderr,
phase returns, compiled target and raw NMSSM.slha are retained. Partial/failing
returns remain failed; no retry or fabricated success is supplied.

generated-spectrum.json contains the raw-return pin, all original SLHA lines,
all block occurrences and scale tokens, scalar/opaque rows, decay totals and
channels, and every SPINFO/DCINFO row. Signed masses and complex mixing blocks
remain unchanged. A successful process or transport result is not physics_validated.
Unknown block bodies remain visible. Unsupported headers or malformed arithmetic
refuse the interpreted delivery while the original native file remains available.

## Spectrum-to-UFO point

Use ravel model-spectrum point --request REQUEST.json --out FRESH_POINT only
after actual accepted generated_model_spectrum_transport and model_source_derivation
reviews exist. The request selects the spectrum_run, derivation_run and a pinned
mapping. The bridge calls the existing qualified_handoff API and rechecks both
review roots at the final boundary. It never edits the accepted UFO or either
historical card.

The mapping has schema_version 2, profile, basis, source_evidence and rows. Each
row gives parameter, external block/codes, origin spectrum or input, selector
{block,codes,scale}, operation, source_unit, target_unit and convention. Operation
must be exactly identity and the explicit source/target unit labels must be equal.
Nonidentity operations and unequal units refuse; no conversion is evaluated. The
convention text remains unverified source annotation, never transform syntax or
a proof of physical basis/unit equivalence. Every external UFO address/name must
occur exactly once. A scale is its literal source token or null; missing,
duplicate or ambiguous source rows refuse. Every external DECAY value must be
an actual returned total width. SPINFO/DCINFO error code 4 prevents point delivery.

Only explicitly declared identity mappings are supported. For example, the
released GAUGE 1 is non-GUT-normalized gY; the bridge performs no hidden sqrt(5/3)
conversion. Coupling definitions, phases, bases and renormalization scales need
source-backed review. A complete address map alone does not prove amplitude or
physical model equivalence.

The new param_card.dat and point-handoff.json retain the complete raw/input
censuses, mapping evidence and original source pins. Ending review/input/output
changes prevent a successful handoff and leave failed partials. The original
model inputs are never repaired or replaced after a refusal.

## Existing native/event consumers

ravel model-spectrum downstream prepares model-tool-bridge or model-events from
the accepted point and an original pinned config. It changes only the explicit
model/card/spectrum_origin join and pathname relocation, preserving the original
processes, seeds, generation regime, weights and budgets. Every target adapter
validates the complete origin, re-derives the card map and expands parent custody
into ordinary inputs. Original goal dependencies remain external and visible to
Graph. This preparation runs no model, amplitude, spectrum or event generator.

Actual NMSSM UFO export acceptance, a reviewed complete basis map, compatible
native runtime, convergence/error review, decay/lifetime evidence and detector/
likelihood inputs remain separate obligations before a recasting result.
