# Released weak-scale MSSM spectrum construction

The `generated-spectrum` adapter supports the released FlexibleSUSY 2.9.0
`lowMSSM` solver alongside the existing CMSSM and NMSSM routes. This is a
source construction and transport operation. A returned native spectrum still
requires numerical and physical review.

The provider accepts Mu as an input and solves the Higgs soft masses through
EWSB. It therefore does not replace the requested Mu–M2 plane with CMSSM
universality or an NMSSM limit. The released model uses real DRbar soft and
trilinear inputs at its iterated SUSY boundary; TanBeta is imposed at the MZ
boundary. It does not accept an arbitrary Qin or complex-soft prescription.
`GAUGE 1` is the source's non-GUT-normalized gY. Signed pole masses and all
imaginary mixing rows remain in the complete original SLHA return.

**This release has no generated decay calculation.** Use
`calculate_decays: false` and `loop_library: null`. Missing widths and lifetimes
remain unknown. A displaced-track or LLP result additionally needs an actual,
source-bound decay return, production, response and likelihood inputs. Native
spectrum success does not supply those inputs or close the original research
request.

## Complete selected input

Select `schema_version: 2`,
`operation: flexiblesusy-2.9.0-generated-lowMSSM`, and
`profile: lowMSSM-FlexibleSUSY-2.9.0` in the existing generated-spectrum config.
Supply the exact source capsule, full input-card pin, Boost/Eigen header
capsules, selected tools and complete runtime inventory required by that
adapter. The source profile binds all 1,121 files and modes: 1,003 common
FlexibleSUSY files plus all 118 released lowMSSM files. Previously configured,
compiled or substituted sources are refused.

The complete card must explicitly contain all 129 selected scalar addresses:

- `MINPAR 3` TanBeta; `HMIXIN 1` Mu and `101` BMu;
  `MSOFTIN 1,2,3` M1, M2, M3.
- All nine entries of `TEIN`, `TDIN`, `TUIN` in GeV, and
  `MSQ2IN`, `MSL2IN`, `MSD2IN`, `MSU2IN`, `MSE2IN` in GeV².
  The latter real matrices must be symmetric. An A parameter is not silently
  converted into a T parameter.
- The released 16 SMINPUTS addresses, all FlexibleSUSY settings 0–32, and
  explicit MODSEL 6 and 12. The bounded profile requires both MODSEL entries
  zero, BSM masses enabled, force output and force-positive masses disabled,
  no additional observables, and the released two-scale algorithm.

Missing rows never select native zero/default settings. Nonzero imaginary
input blocks and nonempty EXTPAR, FLEXIBLEDECAY, VCKMIN or UPMNSIN blocks are
refused rather than interpreted as an alternative model. Other unknown rows
are retained as unverified annotations. The bundled upstream example is a
source example, not a human-selected physical prescription.

## Supplied finite grids

Use `ravel model-spectrum prepare --request REQUEST --out OUT` for one selected
point, or `ravel model-spectrum grid --request REQUEST --out OUT` for a finite
parameter grid. Graph's ordinary `model-spectrum-plan` action uses the same
`parameter-grid` operation and source-only preparation path.

The request contains `schema_version:1`, `operation:"parameter-grid"`, pinned
`config`, `review_policy` and `grid`, explicit `supervisor_seconds`, and an
explicitly nullable parent `goal_binding`. The grid document supplies
`schema_version:1`, `study_id`, ordered `axes:[{name,values}]`, `bindings`,
`relations`, `dataset_population`, `source_evidence` and `delivery`.
Each binding is `{parameter,block,codes}`. A relation is either
`{parameter,operation:"constant",value}` or
`{parameter,operation:"affine",source,scale,offset}`. All operands and card
addresses are supplied; relations must follow dependency order without cycles.
Every axis and related parameter must be bound. Datasets are distinct
`{id,source}` records with pinned source documents. Delivery selects
`{format:"json"|"tsv",filename}`.

Preparation preserves every nonselected byte, including comments and complete
matrices. Missing or multiply occurring card addresses are refused. Each copied
card is validated by the selected provider, and every Cartesian point receives
one unapproved ordinary specification. The point count and aggregate proposed
budget derive from the supplied axes. Source, grid, dataset and parent evidence
must be actual Graph inputs. No build, solver, shared executable or grid launch
occurs during preparation. Each child needs the existing actual CHECK-IN 1,
method-decision admission, root lease and independent review.

See [input preparation](../workflow/steps/02-inputs.md) for the common schema and
fit-campaign input requirements. Omitted required fields have the typed reason
`missing_input`; no old population or parameter relation is substituted.

## Complete return and subsequent operations

The existing engine retains raw SLHA, SPINFO/DCINFO rows, signed masses,
scale/occurrence-aware couplings and mixing matrices, native errors, selected
input witness, source/restored/runtime inventories and the retained compiled
target. Known emitted result bytes are authenticated before delivery; corrupt
partial returns remain failed artifacts.

An existing `model-spectrum point` identity map can select this profile after
actual accepted spectrum and UFO-source transport reviews. It must cover
all external UFO addresses with explicit matching units/scales. A missing
DECAY width cannot be replaced by zero. Existing downstream model-tool/event
preparation then uses that accepted card and source tree unchanged.

The MSSM observable-map point origin may be
`{"kind":"accepted_lowmssm_spectrum","run":"..."}`. It verifies the actual
accepted ordinary generated-spectrum run, profile, operation, exact config,
selected input, full raw return and no-decay disposition. Axis bindings use
HMIXIN 1 and MSOFTIN 2; M1−M2 uses MSOFTIN 1−2 and TanBeta uses MINPAR 3.
The user's exact CP, mixing-scale and provider convention declarations still
apply. Missing widths stay open in the map and LLP handoff. No fitted exclusion,
detector response, lifetime or loop-accuracy claim follows from source transport.

## Source provenance and later obligations

Primary sources are the [official 2.9.0 release](https://github.com/FlexibleSUSY/FlexibleSUSY/releases/tag/v2.9.0),
its [released lowMSSM asset](https://github.com/FlexibleSUSY/FlexibleSUSY/releases/download/v2.9.0/lowMSSM.tar.gz),
the [model definition](https://github.com/FlexibleSUSY/FlexibleSUSY/blob/v2.9.0/model_files/lowMSSM/FlexibleSUSY.m.in)
and [input example](https://github.com/FlexibleSUSY/FlexibleSUSY/blob/v2.9.0/model_files/lowMSSM/LesHouches.in.lowMSSM).
The profile records their literal hashes plus the framework commit and complete
file/mode census. FlexibleSUSY source attribution and GPL license are retained;
no upstream solver formulas were reimplemented.

Later qualification must establish a compatible selected compiler/runtime,
actual lowMSSM configure/build/solver return, exact source/phase noninterference,
EWSB/error dispositions, scale and mixing conventions, numerical comparisons,
and any separately selected decay calculation. Full original projection also
needs the missing physical soft/SM/loop prescription and analysis inputs.
Software controls and source fidelity establish none of these physical results.
