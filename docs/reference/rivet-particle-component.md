# Native particle construction continuation

`ravel.physics.rivet_particle_component.compile_component(recipe)` compiles an
explicit ordered native projection graph. It returns init/analyze source, headers,
source-semantic notes and remaining obligations. `instantiate(source,
expected_sha256=..., recipe=...)` fills three unique whole-line
`RAVEL_PARTICLE_HEADERS/INIT/ANALYZE` template slots and returns a fresh source
identity. This is construction, not arbitrary C++ translation or execution.

The closed recipe contains schema_version1, kind
`native-rivet-particle-components`, and1–32 nodes. Each node has a C++ id, kind,
optional native projection_name and optional output{id,access}. References must
be to prior nodes, with distinct local and native identities.

| kind | Required explicit semantics |
|---|---|
| stable | conjunctive pt/abs_eta/abs_rapidity cuts with literal units; pids:null or signed/absolute exact IDs |
| identified | prior input plus signed/absolute ID roster |
| prompt | prior input plus tau_decays and muon_decays each prompt/nonprompt |
| dressed | prior leptons then photons; radius0–10; cone only; post-dressing cuts |
| vetoed | prior input; explicit projection veto roster; optional signed/absolute ID veto roster |
| charged / visible | prior input; native generator charge or visibility predicate |
| unstable | literal cuts/PIDs; native record-status, parton and last-signed-copy filtering |
| invisible | prompt_only bool and both decay flags; native whole-event FinalState, without an input acceptance filter |
| charged_leptons | prior input; native ChargedFinalState then charged-lepton PID predicate |
| leading | prior input; exact signed/absolute PIDs; explicit leading_only and empty_policy |
| invariant_mass | prior input; ordered signed unequal PID pairs; GeV window; invariant/transverse window; null or positive GeV target |
| merged | two prior inputs; native raw-generator identity merge |
| partonic_tops | literal cuts, decay_mode, emu_from_prompt_tau bool, include_hadronic_taus bool, which_top first/last and record_scope=native_generator_record |
| heavy_hadrons | literal cuts on the native UnstableParticles input before heavy-flavor/terminal-copy selection |

Outputs can use native particles, particles_by_pt, raw_particles or, for a dressed
node, dressed_leptons; an invariant_mass node also supports particle_pairs.
Projection registration is required for access. Native pT
sorting leaves equal-pT order unspecified. Native base types are enforced: PartonicTops is a ParticleFinder rather than a
FinalState. It can be a VetoedFinalState particle-finder veto, but must not be an
input to FinalState-based selection, FastJets, DileptonFinder or MissingMomentum.
HeavyHadrons is FinalState-derived and can use those native interfaces. This is
a C++ type boundary; passing it does not establish physical applicability.

The source-bound meanings matter. Promptness is Rivet ancestry, not reconstructed
vertex displacement. Both prompt decay flags are explicit rather than borrowing
LeptonFinder convenience defaults. The two-input dressing constructor takes the
lepton projection first. CONE photon capture is strictly within radius and assigns
to the closest charged bare lepton; equal distances follow native collection
order. Dressed momentum cuts apply after capture. VetoedFinalState uses the native
raw constituent/genParticle identity, including its null-pointer behavior, not a
geometric overlap surrogate. Python computes none of these event quantities.

The module imports the separately source-cleared rivet_jet_component's closed cut,
identity, number and digest utilities. The connected rivet_components and
rivet_event_components compilers consume this same DAG before native jets and
visible-complement recoil. No clustering or particle arithmetic is performed in Python.

The two whole-source cases are SYN_9015_I1254 and SYN_9022_I1436. They retain
all original source outside explicitly recorded projection/header slots, exact
assets, collection retrieval, event selection, histogram booking and finalization.
Their new capsules are incomplete and unresolved. Source-body restoration and
regeneration controls do not establish native API/particle-event equality or paper
physics. External diboson input populations are not presently qualified here.

The selection/composition extension is bound to inspected Rivet4.1.4 native
headers and implementations. InvisibleFinalState uses an uncut whole FinalState;
it can select invisible BSM species as well as neutrinos. Promptness uses
isDirect and the explicit tau/muon policies. It is not a detector-MET projection.
ChargedLeptons can contain charged stable taus if the parent does; it does not
reconstruct tau decays.

LeadingParticlesFinalState selects the highest-pT particle per signed PID, with
strict-greater ties retaining the first input. Global leading_only uses the
signed-PID map order for ties and natively returns a default Particle when no
strictly positive-pT leader exists, including empty input. That mode requires
empty_policy="native_default_particle"; ordinary per-PID mode requires
"empty_collection". No unchecked single-particle accessor is emitted.

InvMassFinalState uses literal ordered signed PID pairs. Each pair requires two distinct signed species so the pinned native selector populates both species buckets. Negative full mass-squared is rejected before the native
mass window. A transverse window still chooses a positive target by closest
full invariant mass. The pinned native1e30 distance sentinel and strict comparison
are retained: if no distance falls below that sentinel, the passing set remains.
A null target retains all passing pairs; particlePairs is
an explicit native pair collection. Endpoints follow native inRange, rather
than a new Python convention. Ordered species-bucket iteration and native pair
multiplicity are retained. MergedFinalState preserves first-input order and
adds second-input particles absent from the first by genParticle identity,
including equal-null behavior; it does not deduplicate within either input or
compare momentum or PID.

The pinned native cache comparison omits InvisibleFinalState prompt/decay flags
and InvMassFinalState target mass. One recipe therefore permits only identical
invisible policy, and only identical target for an equal PID-pair/window/measure
policy, conservatively even across different parent local names. Distinct
declaration names do not establish native cache separation. Review independently authored enclosing C++ projections in the complete routine for additional conflicting declarations before compilation.

Three complete source construction cases preserve SYN_9023_I1422,
SYN_9024_I1071 and SYN_9025_I1358 outside explicit init/header slots.
Their analyze/finalize tails and metadata/reference bytes are exact. Their
ordinary capsules remain incomplete; native_construction source packets retain
whole-source/output/weight/reference obligations, and routine_build refuses
until fresh runtime/dependency admission. Existing rivet-built quantity contracts
remain responsible for every requested histogram, profile, counter, RAW/final
object and named weight. No units, response model or covariance are inferred
from this source compiler.

The current catalogue's551 compile-unit occurrences correspond to550 unique
source paths.58 routines include one of the five new headers, and49 contain
non-include references (overlap retained). The individual non-include counts
are25InvisibleFinalState,13ChargedLeptons,11LeadingParticlesFinalState,
2InvMassFinalState and0MergedFinalState. These are lexical source/operator
opportunities, not49 served routines. Five constructor families are implemented;
zero new routines have native-event or whole-task qualification.

The complete547-row census retains626 eligible survey rows (547 Rivet and79
SimpleAnalysis by recorded user decision), with no new scientific coverage credit. Source
references142PromptFinalState/147LeptonFinder/103IdentifiedFinalState/161VetoedFinalState
have241 distinct routines in their union. Constructor overloads and actual
per-routine applicability must be inspected before assigning a component recipe.

Native qualification should use existing routine_build and rivet-built routes.
The FastJets qualification prospectus binds the exact original17/25 structural
cohorts, all original constituent source/API/oracle files and previous baseline
observations. Changed-source compilation and event authority remain fresh; all
9/29 objects and135/681 rows include final/RAW, errors/undefined state, global
objects and flows. Only the observed nominal weight domain is covered by those
existing contracts. Named-weight generalization requires new source/actual
weight evidence. A whole-output compatibility check does not infer MC covariance.

The particle component needs a subsequent independent ancestry/shared-photon/cone-edge/
post-cut/raw-veto cohort with explicitly declared all-weight/signed/zero cases,
fresh baseline and derivative builds, whole RAW/final outputs and event-level
projection witnesses. It must not use a pure-jet or empty event fixture to claim
that endpoint. A source proposal is useful before that cohort exists, but native
approval and scientific support remain absent until the actual experiment.

## Native generator-record heavy flavor

PartonicTops emission uses the exact five-argument native constructor: TopDecay,
PromptEMuFromTau, InclHadronicTau, Cut, WhichTop. decay_mode is one of all,
electron, muon, tau, e_mu, e_mu_tau or hadronic. All fields are explicit; the
compiler neither guesses a decay mode nor reconstructs a W. Parent cuts precede
copy selection. The native first/last predicate tests direct parents/children
for top content, without an all-ancestor search or status/signed-copy rule. The
decay classifier scans native allDescendants, with prompt-lepton and photon-
ancestor rules. Hadronic tau selection examines direct charged-lepton children.
Negative energy or mass is rejected after native copy/decay selection.

record_scope must be native_generator_record. Event-record tops can be absent,
unphysical or outside the lab frame; this selector is not a fiducial pseudo-top
or detector reconstruction. tops, particles, particles_by_pt and raw_particles
are complete collection accessors; no unchecked singleton is emitted.

HeavyHadrons uses the original native UnstableParticles input, with its record
status/parton/same-signed-child filters and the declared cuts. It retains native
heavy hadrons whose direct generator children have no matching heavy flavor,
not merely no equal PID and not an all-descendant veto. Bottom takes priority
over charm: a Bc hadron is in the bottom collection only. Charm descendants of
bottom hadrons are not removed by an ancestry veto. The native unbound/no-decay
branch is preserved. This is not detector tagging or a supplied efficiency.

A heavy_hadrons output requires {id,access,cuts}; cuts:null calls the uncut
accessor. b_hadrons, c_hadrons, particles and particles_by_pt support explicit
post-selection cuts. raw_particles requires cuts:null because native
rawParticles has no Cut overload. Constructor cuts and output cuts remain
distinct; Python performs no particle, ancestry, momentum or weight arithmetic.

The complete SYN_9026_I1371_PARTON, SYN_9027_I1211 and
SYN_9028_I1278 construction cases retain every byte outside declared
header/init/access spans, with all original assets. Their18 normalized spectra,
6 cross-section spectra and full asymmetry/RAW operands retain the original
finalization. The four tau policies of the asymmetry source remain separate.
Ordinary native_construction packets bind the original full source and the
deterministic proposal as support, requiring a distinct subsequent target name.
They do not label it a fresh model output. Fresh source_capsule identities keep
dependency review incomplete, and ordinary routine_build refuses them until
complete runtime admission. No prior source or baseline acceptance carries.

The pinned4.1.4 catalogue has551 compile occurrences and550 unique paths. After
removing comments and quoted literals,15 sources use PartonicTops and12 use
HeavyHadrons (27 in the union). These are source-construction opportunities,
not27 served or validated routines. The compiler supports explicit subsets of
native constructors/accessors; arbitrary callbacks, dynamic policy, additional
ancestor filters and unlowered reconstruction remain available through complete
native C++ construction and ordinary native execution, subject to source review.
Fresh version/ABI/compile/registration, record-applicable cohorts, all named
weights, full RAW/final/flow/error states and paper applicability remain pending.

## Native primary-particle definitions and signed cuts

`primary_particles` lowers `Rivet::PrimaryParticles({pids}, Cut)` with an explicit
ordered roster of 0–128 distinct positive native `int` PID literals. The native
selector compares `abs(record.pid)` to each literal; an empty roster accepts no
species, and each roster element must use the declared absolute-species convention. Order is preserved because
native projection comparison includes the ordered roster. `alice_primary_particles`
lowers `ALICE::PrimaryParticles(Cut)` from `Rivet/Projections/AliceCommon.hh`.
It uses the unchanged native ALICE species switch, including nuclei and neutrinos;
it must not accept a user PID override. Both kinds require
`record_scope="native_generator_record"`, literal `cuts`, and the usual optional
registration/output fields. They are ParticleFinder-derived, **not FinalState**:
raw-identity projection vetoes can consume them, but FinalState selectors,
FastJets, DileptonFinder and MissingMomentum inputs must not. The native source
can still use them as ParticleFinder inputs to Correlators or EventMixingFinalState.

PrimaryParticles walks only the native first production-vertex parent, skipping
ignored records. A beam ancestor with status 3 or 4 accepts before checking the
ancestor's primary species; otherwise a primary-species ancestor rejects and a
non-status-2 ancestor rejects. A missing ancestor accepts after target PID/status
checks. Target status is not restricted to stable status 1. Kinematic cuts apply
after primary classification. This is neither promptness nor detector primary-track
selection, and Python evaluates none of the event ancestry.

Particle cuts now additionally accept `signed_eta`, `signed_rapidity`, `charge`
and `abs_charge`, all with `unit="1"`. Charge means the native `charge()` or
`abscharge()` property, **not charge3**; no factor of three is applied. Relations
are gt/ge/lt/le/eq/ne. `native_range` takes `value:{low,high}` with finite, ordered
literal endpoints and calls `Cuts::range` directly; Rivet's interval is lower
inclusive and upper exclusive. Equal endpoints intentionally denote an empty
interval. pT ranges use GeV; the old nonnegative absolute-quantity and pT limits
remain. Signed eta/rapidity/charge can be negative. Predicate count and duplicate
identity guards remain, and jet/pair cut contracts are separate. Existing recipes
retain exact emitted source and metadata.

The ALICE specialization's inspected 4.1.4 compare path first compares cuts and
then calls `mkPCmp(*o,"PrimaryParticles")`, which requests a named subprojection.
The specialization constructor shown in that source does not declare that named
subprojection. This is a source-derived registration/cache qualification question,
not an observed native failure. The compiler preserves the original class and
records the obligation; it does not rename caches, replace ALICE with a guessed
PID roster, or certify equal-cut multi-declaration behavior. Inspect every enclosing
native declaration and qualify that path on the actual runtime before adoption.

Four complete source proposals retain SYN_9008_I1392 (gapped strange-particle
cumulants), SYN_9029_I1532 (charge-separated eta-group spectra),
SYN_9030_I1038 (categorical same/mixed-event ratios) and
SYN_9031_I1023 (central PbPb identified yields). Full booking, normalization,
transient/RAW/final objects, errors and undefined states, trigger/calibration,
Correlators, mixing buffers and defaultWeightIndex remain in their original
native code. Incomplete capsules and normal construction source packets retain
all those obligations; ordinary routine_build refuses unresolved native dependencies.
The complete 551-compile-occurrence/550-source census has two generic and sixteen
ALICE-specialized source users. Those eighteen opportunities give zero executed
coverage credit. The missing source-applicable 7 TeV pp cohort and PbPb calibration
are not replaced with structural or wrong-energy fixtures.

Arbitrary upstream C++ remains executable through the existing full-source native
fallback after exact dependency/asset/runtime admission. This typed subset does
not become a gate requiring every published Rivet projection to be reimplemented.
Native ABI/version checks, whole-output all-weight event equivalence and paper
applicability require fresh execution and independent scientific review.

## Native decay-product tables

`decayed_particles` constructs Rivet `DecayedParticles` from an earlier native ParticleFinder node. Required fields are `input`, `stable_pids` (distinct signed native integer PID roster, empty permitted) and `record_scope: native_generator_record`. It emits native `addStable` calls; stopping on a PID does not automatically stop on its antiparticle. Native decay recursion, source generator history, aligned table order and `modeMatches` remain in Rivet and the enclosing full routine.

The class derives from Projection, not ParticleFinder or FinalState. It must not be a FastJets, MET, FinalState or raw-identity veto input, or another decay-table parent. Optional output `access` is `projection`, `decaying`, `n_stable` or `decay_products`; each emits a complete const native reference. Null output retains lazy native projection construction. No singleton/index/mode kernel is lowered.

Native4.1.4 sorts parent particles by pT, skips mothers with zero/one direct child, recurses to leaf or exact signed stop PID, and counts every terminal product. Mother, total count and signed PID-map tables share the same filtered mother index. `modeMatches` checks the supplied total and each requested species multiplicity; preserve the original complete maps, conjugation and safe indices. This is generator record semantics, not a detector decay efficiency, branching fraction or lifetime model. Complete upstream native-source execution remains available beyond this bounded construction subset; fresh version/API/compile/load/whole output and physical cohort qualification is required.
