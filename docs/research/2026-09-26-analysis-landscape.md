# Public LHC analysis landscape and Ravel expansion plan

The earlier survey was too small to support a broad capability roadmap. This
September 26 inventory covers **633 entries: 554 Rivet LHC metadata entries and
79 public SimpleAnalysis registrations**. It inventories every selected entry in
two pinned source trees, rather than adding another small set of papers.
It also provides an implemented, installed-package discovery interface and a
per-routine adaptation packet. It does **not** validate 633 analyses, execute
competitors, or repair the remaining RRR physics discrepancy.

Start with the [searchable browser](../../evidence/audits/2026-09-26-analysis-landscape/index.html),
[complete CSV](../../evidence/audits/2026-09-26-analysis-landscape/routines.csv),
[concrete validation targets](2026-09-26-validation-targets.md), and
[competitor capability assessment](2026-09-26-competitor-capability-map.md).
The package's [machine catalogue](../../src/ravel/data/analysis-catalog.json)
contains the source identities and evidence boundaries behind every entry.

## Coverage and denominator

| Source | Frozen population | What the number means |
|---|---:|---|
| Rivet 4.1.4 | 554 | LHC metadata entries selected from 2,058 `.info` files; aliases and calibration routines remain identified |
| SimpleAnalysis | 79 | Literal registered routines in all 79 public analysis source files, spanning 58 distinct ATLAS analysis IDs |
| ATLAS probability-model index | 45 | Separate discovery records; 24 routine entries match by exact analysis or INSPIRE identity |
| Competitor/adjacent tools | 12 | Seven agent systems, four established recasting/inference tools, and one benchmark; 11 public HEAD pins |

The counts are not additive paper counts. Multiple routines can implement one
paper; a combined result can cover several configurations; a calibration is an
auxiliary input. The 24 model-index matches correspond to routine entries, not
24 distinct independent likelihoods. No match means **unknown**, not that a model
does not exist. HEPData hosts several framework formats beyond this one index.
[HEPData framework integration](https://hepdata-submission.readthedocs.io/en/latest/analyses.html).

| Experiment grouping | Rivet entries | SimpleAnalysis entries |
|---|---:|---:|
| ATLAS | 252 | 79 |
| ATLAS / ALFA | 1 | 0 |
| CMS | 154 | 0 |
| CMS / TOTEM | 1 | 0 |
| ALICE | 54 | 0 |
| LHCb | 81 | 0 |
| LHCf | 7 | 0 |
| TOTEM | 3 | 0 |
| FASER | 1 | 0 |

Rivet is pinned to release **4.1.4**, commit
`74816bd4cf29a9d71447f8c122887d498d3dea3a`, rather than an unqualified moving
branch. Its September 10 release adds LHCb/ALICE routines and runtime fixes;
Rivet 4 also uses the YODA 2 API. SimpleAnalysis is pinned to
`5a33033d788619bb1039a5b8116fdf43c46fc72a`. The accessible Git sources supply the
census; the SimpleAnalysis documentation endpoint returned 403 during retrieval.
[Rivet release notes](https://heprivet.org/releases/),
[pinned Rivet source](https://gitlab.com/hepcedar/rivet/-/tree/74816bd4cf29a9d71447f8c122887d498d3dea3a),
[pinned SimpleAnalysis source](https://gitlab.cern.ch/atlas-sa/simple-analysis/-/tree/5a33033d788619bb1039a5b8116fdf43c46fc72a).

This is complete for the declared repository selection, not the whole universe
of LHC analyses. It excludes private/embargoed implementations, independent
unmerged repositories, a PAD-wide/CheckMATE-wide inventory, and analyses without
a routine in these trees. The non-LHC SND experiment at VEPP and generic MC
validation plugins are excluded. No SND@LHC or LHCb fixed-target implementation
is claimed from an ambiguous name match. The older 26-candidate survey and its
45-record discovery index remain intact as historical evidence.

## What the source inspection actually establishes

There are **630 entries with an identified source implementation**, including
one explicit alias, and three unresolved metadata-only entries:
`ATLAS_2012_I1093734`, `ATLAS_2012_I1094061`, and `ATLAS_2017_I1598613_BB`.
The extractor accounts for every LHC source file in the six experiment plugin
directories: no unmatched `.cc` file remains there. It records Git blob identities
for source, metadata, plotting/reference files and literal external assets.

**518 entries have a same-stem reference YODA file in the Git tree.** This is
file-presence evidence. It does not certify reference contents, covariance,
bin semantics, normalization, or a usable exclusion likelihood. The three
missing direct sources remain visible rather than disappearing from the
survey denominator.

Upstream status is preserved separately from Ravel's validation status.
There are 475 entries marked exactly `VALIDATED`, alongside qualified statuses,
27 `UNVALIDATED`, 13 `OBSOLETE`, and other declarations. One upstream status is
literally `True`; it is retained as a string and receives no validation credit.
SimpleAnalysis does not declare per-routine validation status through the
registration macro. None of these upstream labels certify a Ravel adapter.

The survey also exposes real metadata and dependency hazards:

- `CMS_2018_I1646260` declares `Experiment: ATLAS`, although its name, source
  directory, paper reference and title identify a CMS result. Grouping uses the
  routine namespace, preserves the original field and flags the conflict.
- Some `.info` files contain malformed YAML in long descriptions. The extractor
  reads named metadata blocks independently and never repairs physics prose.
- Twelve routines contain explicit RestFrames usage signals. Five contain ONNX
  signals, and three MVA signals. These overlap with other requirements and are
  **lower bounds from lexical inspection**, not dependency-completeness claims.
- Some SimpleAnalysis routines reference calibration assets outside their data
  directory. TriHiggs constructs filenames dynamically. Unresolved literals are
  exposed in the planning packet and block selected-byte verification; the
  catalogue does not incorrectly declare those assets absent everywhere.
- `SINGLEWEIGHT` and non-reentrant-finalize declarations generate explicit
  requirements. A successful merge or a positive event count cannot establish
  that weighted or normalized histograms were combined correctly.

The tests specifically distinguish neutrinos in an ordinary ZZ final state from
FASER neutrino flux physics, a displaced TOTEM interaction point from an LLP
search, and leading-jet text from lead-ion beams. These examples demonstrate
why a keyword-derived map needs adversarial controls and explicit review limits.

## Adaptation landscape

The following mutually exclusive families are automated triage categories.
They guide engineering review; they are not individual paper assessments.
Dependency tags overlap, and beam/observable details still require manual review.

| Family | Entries | Required adaptation and decisive validation |
|---|---:|---|
| Fiducial measurements | 406 | Fixed HepMC input, particle/object definitions, Rivet/YODA version, weight accounting, bin measures and reference overlays; covariance and SM theory before inference |
| Search recasts | 125 | Trigger/object response, region membership and overlap, signal/control mapping, normalization and exact statistical model |
| Hadron/flavor observables | 46 | Fragmentation, prompt/feed-down separation, decay/amplitude model, branching and normalized-observable conventions |
| Heavy-ion/nuclear | 28 | Nuclear beams, centrality where used, nuclear normalization and medium/background/correlation treatment |
| Forward/diffractive | 14 | Forward acceptance, beam optics where needed, elastic/diffractive generation and gap definitions |
| Long-lived particles | 8 | Proper-time/boost transport, decay geometry, non-prompt efficiencies, timing/track response and benchmark lifetime closure |
| Auxiliary calibrations | 5 | Calibration sample and beam/energy applicability; not standalone search evidence |
| Forward neutrino | 1 | Flux, transport, neutrino interactions, target response and correlated uncertainties |

A filename classifier cannot prove that a routine is simple. Do not rely on the
old native engine docstring's unsupported “~85%” generality estimate. Its source
is preserved because historical scientific receipts bind those exact bytes;
this catalogue supplies no replacement percentage of native compatibility.
Common cut-based routines are candidates for the declarative engine, but each
still needs proof that its observables, object flags and selections are
representable. In particular, “has a public routine” does not imply “works with
Ravel's Delphes converter” or “has an exclusion model.”

The [validation-target matrix](2026-09-26-validation-targets.md) makes these
families concrete. Its estimates describe relative adaptation work, not promised
completion times or physics validation. The first controls deliberately test
common fundamentals before more difficult compressed/ML/LLP analyses.

## What is implemented now

The new `ravel analyses` interface works offline from the installed package:

```bash
ravel analyses summary
ravel analyses list --experiment CMS --query "Drell"
ravel analyses list --framework simpleanalysis --family long-lived
ravel analyses show rivet:ATLAS_2019_I1734263
ravel analyses show simpleanalysis:EwkCompressed2018
ravel analyses check-source EwkCompressed2018 --source /path/to/simple-analysis
```

A paper identifier resolving to multiple routines produces an ambiguity error
listing the choices. It cannot silently select the compressed VBF branch, the
wrong lepton channel, or an inclusive discovery region. `show` returns source
pins, external-dependency signals, metadata issues, candidate model matches,
existing native registration restrictions, and the required adaptation and
validation work. `check-source` verifies selected actual local bytes and HEAD;
it rejects modified sources, wrong revisions, unresolved assets and symlinks.
It does not build, run, change the toolchain, or authorize a physics calculation.

This is a durable discovery and planning capability, adapted from the useful
routine-lookup pattern seen in adjacent tools through original Ravel code.
It is **not yet an executable general routine-admission lifecycle**. In
particular, it cannot make a new analysis runnable merely by listing it, and its
source-check PASS is not a physical or runtime-compatibility PASS. Those limits
are included in every packet, not hidden in this document.

## Development sequence justified by the survey

1. **Frozen-event Rivet admission.** Add an explicit `analyze-existing-events`
   lifecycle with a named input event level, pinned routine/runtime/options,
   event/weight census and bin-quantity contract. Start with the paired ATLAS/CMS
   Drell–Yan controls, then diboson and jet observables. Every contribution should
   be comparable with the unchanged upstream routine on the same events. Do not
   write another selection when the preserved implementation can be used.
2. **Simple reconstructed-object admission.** Use ordinary dilepton and jets/MET
   selections to test object flags, thresholds, overlap removal and region
   membership. Native SimpleAnalysis compilation, external assets and Mac/ARM ABI
   support need explicit per-adapter evidence. Compare selections before fitting
   limits. Transfer recurring response or normalization failures back to RRR.
3. **Quantity and weight transport.** Implement explicit integrated/differential,
   absolute/normalized and one-/multi-dimensional bin semantics. Validate signed
   and multiple weights, correlated subevents, finite-MC moments, under/overflow
   and merge invariance. This extends the current positive-uniform LO generation
   scope; documentation alone cannot supply it.
4. **Measurement inference through mature backends.** Add supplied covariance,
   SM/theory predictions and overlap policy, preferably first through an external
   Contur/Spey interface. The existing supplied-pyhf route is useful but cannot
   replace a missing covariance or reinterpret every YODA histogram as counts.
5. **Model, classifier and lifetime branches.** Admit UFO/FeynRules, EFT orders
   and interference, ONNX/tagger inputs, topology/efficiency maps and LLP response
   through distinct benchmark contracts. Heavy-ion, forward and neutrino routes
   need additional scientific machinery and should not inherit pp-search claims.

Every branch needs a small positive end-to-end control, failures that deliberately
break the scientific contract, and a complete requested-output denominator.
For the agreed comparative experiment, recorded affirmative check-ins may be
scripted. That supplies consent to the experiment, not expert review or evidence
that a proposed physics approximation is correct.

The efficient next experiment is **fixed-event analysis equivalence**, followed
by reference closure, not another large RRR grid. It can isolate semantic and
adapter errors without introducing Monte Carlo fluctuations. It still cannot
calibrate a detector or establish a paper's full reproduction by itself.

## Competitor adaptation and scientific distinctiveness

The refreshed [twelve-system assessment](2026-09-26-competitor-capability-map.md)
changes the old availability picture: SFitterAgents now has substantial source;
FERMIACC remains a paper with no runnable public repository located in this
bounded search. Current Contur and SModelS provide important inference and
surrogate capabilities. AgentRivet documents normalization and observable
failures directly relevant to admission testing.

Implementing a competitor's useful capability with original code avoids code
copying; it does not create scientific novelty. The plausible Ravel research
contribution is a measured reduction in scientifically wrong results through
physicist decisions and artifact-bound checks, across different analysis types.
That needs a controlled evaluation with fidelity, missed failures, false
refusals and cost measured separately. Neither this catalogue nor the earlier
engineering test counts establish it.

RRR low-splitting shape, acceptance, generator-cut dependence and full-plane
closure remain publication requirements. The broader landscape makes Ravel's
expansion plan more rational; it does not remove those failures from the paper.

## Implementation follow-through

The sequence above now has [executable components and a control report](../../evidence/audits/2026-09-26-scientific-studies/README.md).
The census remains a discovery denominator, not a claim that all 633 entries
execute successfully or reproduce their papers. Use the [scientific-study guide](../workflow/reference/scientific-studies.md)
for current admission rules and the report for actual executed coverage.
