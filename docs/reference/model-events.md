# Source-bound model event generation

The ordinary `model-events` scientific adapter prepares and runs full supplied UFO models through the pinned MG5_aMC 2.9.27 driver. It uses existing ordinary source custody, CHECK-IN 1, approved-attempt selection, supervised worker and native process-group execution. It does not introduce a generator, shower, matrix-element evaluator or statistical optimizer.

A preparation is source-only. Use `ravel model-events prepare --request request.json --out fresh-preparation`, then `ravel plan --rundir fresh-run --spec fresh-preparation/science.json`. The deterministic Graph/Host action `model-event-plan` consumes the same request. It never approves or executes the study. The native worker is reachable only from the exact approved ordinary task/output. A supplied-event operation remains separate; preparing supplied events cannot silently satisfy a request for generation.

## Complete source and mode declaration

The closed schema requires full MG and unrestricted UFO source-tree manifests, an exact native Python and support-file census, compiler/runtime dependency trees, explicit source process/parameter/run cards, and explicit decay/reweight/shower choices. Every expanded source member becomes an ordinary stage input. Graph inputs expose compact manifest identities, all cards/variation definitions and original parent dependencies; preparation expands and hashes all members before and after. It never treats an unverified manifest as proof of its live members. Output may not overlap the original source trees.

`generation.scheme` and perturbative `order` are mandatory. The implemented upstream paths are unmerged LO, LO MLM, LO CKKW-L, NLO MC@NLO and NLO FxFx. Their explicit `ickkw`, matrix-element cuts, integrated-shower parameters, hard-process label and complete process jet multiplicities must agree. A matched/NLO request cannot become unshowered or unmerged LO. MLM/CKKW-L/FxFx require multiple declared jet populations. The historical MSSM native pipeline remains the historical unmerged LO path; explicit MadSpin, reweight, NLO, matching/merging or systematics requests there receive a constructive `model-events` routing error.

Process cards contain only literal particle definitions and `generate`/`add process` commands. The adapter imports the supplied private UFO with `-full`, so MG's default restriction card is not silently applied. NLO processes must contain `[QCD]`. The literal native export process/model history is retained and compared to the requested commands. Decay chains are declared in the separate MadSpin card. Explicit SLHA scalar parameters, block scales, widths and branching rows are preserved; Auto widths are refused rather than computed without a separate admitted operation.

All original cards are copied, never edited in place. The reserved nominal weight channel cannot be declared as a variation. Copied admitted MG/UFO members and their complete non-cache membership are authenticated before and after build and generation, with each returned census retained before mismatch refusal. Native generated process trees are separate; only the existing explicit Python-derived cache policy is excluded. Runtime set commands use the upstream --no_save option, so copied configuration files have no general mutation exemption. Intent, exact rendered-card pins, actual returned card text, command argv/status/timing and generated file census are retained before success checks. The only implemented Pythia output-card normalization is MG's source-backed `HEPMCoutput:file = auto` to the declared literal native filename. Arbitrary filenames, cut changes, backend changes and nominal parameter changes refuse. The private source and native scripts never install software or download a model.

## Decay and variation semantics

MadSpin must declare its literal mode, seed and decay commands. Modes `madspin`, `full`, `onshell` and `none` have different upstream approximations; the route does not promote them to an identical spin/width treatment. Applicability assumptions remain mandatory. Full decayed event exposure must still satisfy the exact approved denominator; a native return that adds or loses records fails with partial evidence retained.

LO scale/PDF variations use explicit `use_syst`, `systematics_program=systematics` and arguments. NLO uses explicit on-the-fly scale/PDF controls or stored-info systematics. Header identities, groups, MUR/MUF factors and LHAPDF IDs are matched to actual upstream header attributes or NLO text. A PDF set/member label remains a source declaration requiring the pinned LHAPDF/grid source; ID correspondence alone is not an independent library qualification.

ME reweighting uses the upstream card's actual order: each named `launch` is followed by its literal parameter edits. The edits must equal the declared coefficient point through an explicit real/imaginary component, factor/unit and external UFO address map. NLO `_nlo` and NLO-tree `_tree` suffixes are retained. The exact coefficient basis, flavour, scale and complex components are carried with source pins. WCxf/Wilson artifacts cannot supply an inferred UFO/SFitter map. These weights represent full native matrix elements; isolated linear interference or quadratic coefficients require a separately source-backed projection and are refused by this route. Reweighting phase-space overlap, NLO approximation choice and EFT validity remain scientific obligations.

## Complete signed populations and downstream boundary

Every generated LHE event, including negative and zero nominal weights, is consumed through EOF. Its full particle/header population, process normalization, PDF/beam identity, complete named or compact weight vector and ordinal are retained in a progressive JSONL journal. Missing/extra/duplicate/nonfinite weights, truncated exposure or altered raw streams refuse. Decimal W/Q summaries describe literal serialized weights. No luminosity normalization, envelope, cross-variation independence, sampling-law qualification or finite-MC covariance is inferred. The event hash is explicitly canonical XML, while original raw-file bytes have a separate hash.

Integrated showers must declare a complete unique nominal-plus-all-variation name map. The actual HepMC2 E/N weight vectors, explicit units, finite particle/beam records and bounded returned population are retained progressively. A declared LHE-to-shower name map is not an independently qualified correspondence. The original LHE ordinal is deliberately null until an observer qualification supplies that join. Shower vetoes may reduce returned events within the explicit lower/upper bound; they do not change the original generated LHE denominator.

Generator handoffs retain source/model/cards/runtime, intended/rendered/observed settings, complete selected weight labels, signed W/Q and original exposure. They do not invent per-region yields, efficiencies, correlation law, detector selection or likelihood. Existing supplied-event detector/routine consumers need their own admitted lineage/normalization operation; source identity or marginal multiweights cannot replace missing shared-group covariance. Parent goal dependencies remain external and immutable, and generation delivery leaves reinterpretation/fit/coverage obligations open.

## Qualification status

This is an implemented source candidate with pure card, transport and inert native-driver protocol controls. No MG process, UFO import, compiler, shower, event generation or physics validation has been run for it. Build/run lifecycle, actual integrated Pythia support, MadSpin return, real native header conventions, complete source and owned-process quiescence must be qualified in future ordinary studies. The current installed MG configuration does not establish a usable MG5aMC_PY8 interface; an arbitrary installed Pythia prefix is insufficient.

Primary implementation sources: pinned MG 2.9.27 `madgraph/interface/{madgraph_interface,madevent_interface,amcatnlo_run_interface,reweight_interface}.py`, `<supplied-MG-source>/MadSpin/interface_madspin.py`, `<supplied-MG-source>/models/import_ufo.py`, `madgraph/various/{banner,systematics}.py`, LO Pythia/NLO shower cards and `<supplied-MG-source>/Template/NLO/SubProcesses/handling_lhe_events.f`. Upstream descriptions: https://cp3.irmp.ucl.ac.be/projects/madgraph/wiki/MadSpin and https://cp3.irmp.ucl.ac.be/projects/madgraph/wiki/Reweight . Exact source pins and line traces are retained in the private handoff rather than claimed as executed scientific evidence.

## Authenticated export and static-build reuse

A new `generator_reuse` declaration uses the existing `model-events` preparation,
plan, approval and worker. It does not create an execution controller or a global
cache. Omit it to retain the existing fresh-export behavior. To produce a reusable
capsule on an ordinary successful run, declare:

```json
"generator_reuse": {
  "candidate": null,
  "max_files": 50000,
  "max_bytes": 1073741824,
  "max_member_bytes": 134217728
}
```

For a later run, replace `candidate` with
`{"rundir": "/absolute/original-run", "capsule_sha256": "<exact generator-reuse.json SHA256>"}`.
Preparation reports fresh, miss, export-reuse or export-and-static-reuse. A
missing, failed, stale, incompatible or oversized candidate is an explicit miss
and the existing worker exports afresh. A candidate admitted into the ordinary
plan is revalidated before consumption and at ending custody; a later drift
requires a new ordinary plan, rather than silently executing under changed
inputs. Prior approval or scientific votes do not authorize the new run.

The compatibility identity commits the complete unrestricted UFO, MG source,
process definitions and coupling/perturbative-order commands, source transforms,
producer/observer implementations, native Python/support files, compiler and
library dependency populations, runtime options, effective build-tool binaries,
OS/architecture and a digest of the relevant compiler/native environment. `make`,
`ar` and `ranlib` are resolved without running them and become ordinary pinned
inputs. Runtime support and library completeness retain the existing declared
source/runtime premises; this is not an OS sandbox or a compiler certificate.

The worker captures its export immediately after the authenticated native export,
before supplied production cards or any launch. It stores a closed, regular-file
capsule, preserving original member modes and link semantics as metadata.
Internal include links and authenticated source-library links relocate into the
fresh process/source roots. The sole textual relocation is the released
configuration writer's explicit `mg5_path` setting; unknown active path values
refuse. Original process-observer bytes and their original build/config/model
commitments are retained. A reuse receipt labels artifact materialization and
states that no new native export ran; it does not pretend the old observation
was made during the new run.

For the supported released LO `MadEventCmd.configure_directory` API, a
source-bound wrapper returns the original result unchanged and captures only
static `.o`/`.a` source objects/libraries at completion. It never stores Events,
adaptive grids, random state, survey directories or previous run cards in that
static overlay. On every ordinary launch this source function cleans PDF/generic
libraries and subprocess executables before returning; it still treats fresh cards,
compiles and surveys/refines normally. No compile call is skipped or replaced.
This can reuse compatible libraries but does not promise every object survives
native dependency checks or that every subprocess binary is reused. NLO and an
unsupported build API use export reuse with normal native rebuilding.

Static compatibility additionally binds the complete nominal parameter card,
all other cards, run settings, shower/decay/reweight/weight semantics and source
API. Only the declared main event count/seed and run `nevents`/`iseed` differ.
A mass, width, coupling, cut or other physical change can reuse the unchanged
export identity while dropping the static overlay and rebuilding normally.
Every run still writes its complete new cards, uses its new seed, performs fresh
integration, retains signed/zero/all-weight event exposure, and must satisfy its
original ordinary resource/approval and downstream scientific contracts.

Reused generation-time process observers retain their original model-import
path. Current admission still compares every original UFO/source member and
checks the fresh copied model before generation; the original and relocated
paths describe those distinct roles. Both operative-seed reads use the same
origin import identity. Foreign model imports and changed complete source
populations remain refused.

The exact released MG2.9.27 `Template/LO/Events/.keep` is the sole admitted
incidental Events file before launch. Its empty bytes and released exporter,
copy helper and cleaner are authenticated. Other Events files, aliases and
changed marker sources remain unavailable. Captured zero-byte members such as
`SubProcesses/done` use a lossless typed nonempty storage envelope; materializing
into fresh work restores their exact empty bytes. No native source, log or
scientific result is padded. Stored envelope bytes count toward reuse ceilings.

`model-event-plan prepare` prospectively declares exactly the build and combined
generation stdout/stderr `.log` files as incidental members. Their actual empty
bytes remain hashed in the ordinary output snapshot, including the materialized
build's empty stderr. A manually supplied specification uses the same
`model_events.output_policy(config)` declaration when those raw logs can be empty.
The existing split pre-shower branch instead names its exact build,
hard-generation and shower-reentry streams, preserving that separate route.
Scientific files and unexpected empty outputs retain the common strict guard.

Capture has explicit file/member/total byte ceilings, including the cumulative
population and bytes hashed through external source links. Unsupported export links
or a capture ceiling retain an unavailable diagnostic and any partial files;
they do not qualify a capsule or turn a completed/failed run directory into a
cache. Successful ordinary origin and the closed capsule are checked again at
the final common worker boundary. Source controls do not establish actual
native reuse, speedup, amplitude correctness, independent samples, matching
validity or physical qualification; those require separately admitted runs.

### Completed-survey same-run continuation (MG 2.9.27 LO)

`integration_checkpoint` is a separate opt-in configuration field. It captures the
returned first survey in the released regular MadEvent `run_generate_events` body;
it does not replace the generator, scheduler, approval or event-delivery route.
Existing configurations and `generator_reuse` keep their existing behavior. Static
export/build reuse is for fresh production state. A survey checkpoint retains
adaptive state and belongs to one logical sample.

```json
"integration_checkpoint": {
  "candidate": null,
  "max_files": 20000,
  "max_bytes": 1073741824,
  "max_member_bytes": 67108864
}
```

These are explicit operational ceilings, not permission to spend them. Select them
against the ordinary approved study's time, memory, disk and complete exposure.
The supported policy has finite upper bounds of 100,000 members, 4 GiB total
storage/reference bytes and 128 MiB per member. All actual resources and native
calls still require the existing plan/check-in approval. Capture itself consumes
that original study's wall allowance. The field requires exact released MG 2.9.27
LO source, `operative_seed_observation`, an original goal binding and local native
ownership. It cannot be combined with static `generator_reuse` or the separate
pre-shower split transport.

The immutable `integration-checkpoint/checkpoint.json` records the actual live
`AllResults`, exact current run/tag alias, `RunResults`/`OneTagResults`, final
`RunStatistics`, complete card/banner, original/current seed, Python random state
and native `mg_seedset` presence/value. A finite typed codec replaces pickle;
unsupported native state refuses. The stale `HTML/results.pkl` is retained only
as original provenance. The full process census includes source-selected channel
results, grids, event pools, maxima, loop resources, cards, binaries, empty files,
link targets and modes. Source-selected zero subprocesses/channels remain explicit.
No file count, parser success or nonempty grid establishes statistical precision or
physical validity. Native grid-reader behavior and final sampling/precision require
later matched qualification; no uniform-grid fallback is accepted as evidence that
the old adaptive proposal was faithfully restored.

Capture happens after the real survey returns and before the first refinement.
It verifies that local integration descendants are quiescent while the native
owner remains alive. The capture retains that owner's `RunWeb` bytes as provenance.
A failed recorder stops dependent native control flow; incomplete storage is not
a checkpoint. A later failure preserves a previously sealed checkpoint without
making its incomplete output successful.

To request continuation, prepare a new immutable config through the ordinary
model-event preparer. Replace only the candidate and choose a smaller declared
wall ceiling within the original unspent allocation:

```json
"candidate": {
  "rundir": "/absolute/original-ordinary-study",
  "attempt": 1,
  "checkpoint_sha256": "<exact returned-survey checkpoint digest>"
}
```

The original process/model/UFO, coupling and perturbative orders, cards, requested
full event count, seed, compiler/library/PDF/runtime input population and environment
must remain identical. Path spellings are resolved against the authenticated original
config base. A changed seed or exposure is an independent fresh-production request,
not this same-run route. A mismatch does not prohibit a new ordinary fresh plan;
it prevents calling incompatible state a continuation.

The consumer authenticates the original approved plan, registered attempt,
failed-stage ledger, phase invocation/capture receipt, complete closed original
stdout, original native owner/cleanup and bound helper/source bytes. It requires
the old owner group to be absent before admitting a new worker. Remaining wall time
is the smaller original selected-stage/native ceiling minus the larger recorded
original stage/native elapsed time. The source config, generated request and actual
native receipt must agree on that original native ceiling. Fully exhausted allocations, ambiguous ownership, missing native
receipts or an unrecorded interruption remain held; the adapter never manufactures
remaining budget or grants a two-hour-cap extension. All failed/unknown attempts
remain charged by the ordinary campaign. The current continuation also needs its
own genuine approval; a checkpoint is an input, not authority.

A new process copy omits the old owner marker and stale pickle. The released enclosing
`MELauncher.launch_program` creates fresh `RunWeb` through `RunWebHandling`; its
child deliberately uses `force_run=True`. The checkpoint validates the actual
source-bound enclosing frame, exact child identity and fresh current-PID marker.
A direct native constructor with its own fresh marker remains distinct; arbitrary
forced calls outside that released owner context refuse. The original native survey API is
substituted once: real current `check_survey`/`configure_directory` runs, sealed
integration products must survive that setup, then the codec restores the complete
live graph and uses released `AllResults.def_current` for the exact existing tag.
It never calls the destructive `set_run_name` branch to add a tag. The current
setup timestamp is retained. Python state and `mg_seedset` are restored **after**
setup, so a later source seed branch cannot silently reset them. The original full
`run_generate_events` body then performs the requested refinement, zero-cross
branch, second-refinement threshold, combine/store and configured final services.
No shortened tail or synthetic survey seed log is used.

Both operative-seed readbacks consume two separate authenticated records: the
original survey stdout with its one genuine seed-offset observation, and the actual
continuation stdout with no repeated survey. Current banner/process/card/LHE and
complete output ending checks remain binding. Results retain `same_sample_lineage`
and `independent_sample=false`; the original failure remains a failure. Restored
survey/materialized export timing is labeled separately and cannot qualify the
existing fresh-generation phase calibration.

Here “regular LO” includes loop-induced LO **only** where MG 2.9.27 uses this same
regular MadEvent branch (including its source-directed local multicore/one-core
selection). Complete MadLoop resources/statistics are retained. A separate matched
loop-induced native control is required before advertising that family as working.
This source implementation supplies no process-specific interruption evidence, speedup,
external-program result or physics acceptance. NLO, gridpack channel retry, live mid-worker RNG
recovery, interrupted split merges, completed-refine capture, shower resume and
independent warm-start sample pooling are outside this first codec. The distinct
MG versions in original comparative tasks retain their own prerequisites; the known
2.9.27 gridpack precision-parser issue is not patched by this implementation.

#### Completed-survey continuation control and V2 source prerequisites

Capture serializes the actual released `RunCardLO.includepath` as an exact
`collections.defaultdict(list)`, retaining its mapping order, shared values and
factory semantics. Other factories refuse. Actual released-class constructor
and round-trip controls are a separate root-owned qualification step; synthetic
class fixtures do not establish that result.

The immutable checkpoint binds a genesis descriptor in an explicitly owned
sibling control directory of its original ordinary run. Mutable journal and
lock state are outside the checkpoint/process member census and old scientific
outputs. Planning only reads that state. Each continuation claim repeats current
ordinary approval, goal/config/source and registered-attempt admission, then
serializes one owner against the exact original checkpoint and goal. The whole
selected ordinary stage ceiling is debited from the original remainder. Every
failed or unknown reservation remains charged; there are no inferred refunds.
Two successor directories cannot borrow the same remainder concurrently. Exact
previous failure and native/ordinary cleanup evidence can release ownership for
a smaller serial retry, without restoring its consumed allowance. A successful
same-run continuation forbids another replay of the captured RNG stream.
Missing or inconsistent control state refuses; the API never resets it or
creates a replacement grant. Interrupted emission may leave conservative held
state requiring explicit recovery. This uses the existing mutable ordinary
execution-control trust boundary, not an OS sandbox or a cryptographic guarantee
against an operator rolling back all authoritative filesystem history.

Control documents have a finite 1 MiB operational bound and at most 512 claims;
these support ceilings confer no execution authority. Immutable genesis bytes
count in checkpoint capacity. The effective file/member/total ceilings are the
intersection of original and current policies. Complete declared payload,
manifest, survey prefix, genesis and linked references must fit before payload
reads or materialization; no truncation is allowed. Configuration relocation
must also fit. Both seed consumers and their endings use the admitted current
source base and policy, authenticating original survey stdout separately from
the actual resumed tail. All original event/exposure/weight, source and full
released-driver checks remain, with separate current child/claim/ending checks.
