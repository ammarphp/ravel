# Required site ROOT analysis and reproducibility workflows

Ordinary mode `root-stream` reads a supplied complete ROOT member population
using a source-reviewed kernel. `ravel site-workflow` exports already prepared
studies to Snakemake. Transport and reproducibility are separate from a designed
search analysis, background validity, sensitivity, inference and site availability.
Every original background/signal sample and missing scientific input stays in the
question. No filename supplies DSID, data/MC identity, units or normalization.

## Required Linux installation

Linux CPython3.12 and native source-build prerequisites are required. Read the
[required native toolchain setup](../installation.md)
before installing the full Python host. In the actual Linux checkout:

```sh
python3.12 scripts/setup/site_installation.py --plan
python3.12 scripts/setup/site_installation.py --install
```

The helper creates checkout-local `.ravel-site/site-analysis`, installing RAVEL
itself and `requirements-full.txt` plus `requirements-site.txt`: fsspec2026.9.0,
fsspec-xrootd0.5.5 and XRootD6.2.0. A separate required `.ravel-site/site-wms`
uses `requirements-site-wms.txt`: Snakemake9.27.0 and packaging25.0. Snakemake's
packaging<26 must not replace proven host packaging26.3. The connector states
Linux-only tested support. Neither installed paths nor pip checks prove native
ABI, credentials, RSE/data access or scientific validity.

On a Mac, generate concrete commands for a supplied remote Linux checkout:

```sh
python3.12 scripts/setup/site_installation.py --plan --linux-root /absolute/linux/ravel --out required-site.json
```

Transfer the exact source separately; no local complete site runtime is claimed.
The helper neither copies tokens nor changes global configuration, downloads
data or submits jobs. Interrupted exact profiles can resume installation;
unrelated or changed declarations are retained/refused, not silently deleted.

## Closed scientific source contracts

Task is exactly `{config: {path, sha256, size}}`. Config schema1 has `dataset,
analysis, bundle, runtime, site, limits` plus `schema_version`; these documents
have exact closed keys enforced in `root_stream_core.py`.

Dataset declares complete membership authority, fixed sample/member/source-entry
ordering and all samples. Each sample has `id, kind, dsid, process, normalization,
members`. Kinds are background_mc, signal_mc or data. Data DSID/normalization are
null. Each member binds `id, did, guid, uri, tree, entries, size_bytes, checksum`.
Checksum has explicit algorithm/value and source authority; URIs are literal,
unsigned file/root paths without queries/globs/credentials. The full dataset
must equal its pinned source authority including identities and order.

MC normalization binds the full original population/source and exact signed
nonzero sum_weights, luminosity_fb_inverse, cross_section_pb, filter_efficiency
and k_factor. Analyzed members must belong to that original population. The
single factor `luminosity * 1000 * cross_section * efficiency * k / sum_weights`
is applied after all chunks, never using chunk/selected-row denominators. Raw
analyzed MC sumw/sumw2 remains distinct from the retained full denominator.

Analysis has original_goal, explicit branch name/shape/dtype/unit census,
weight_contract, quantities and blinding. Shape is scalar or one-level jagged.
Weight contract separates raw_mc_weight, scale_factors and multiplicative event
variations. Each quantity uses existing closed quantities semantics with complete
bins/axes/weights/units and absolute scale1 before sample normalization. One
physical source entry is one independent Poissonized event group; its multiple
fills, all bins and variations retain cross moments. This is an explicit
conditional sampling law, not generator integration error/fixed-N covariance or
proven independence.

Bundle keys are exactly entry, blind_entry, files, review_source. blind_entry is
explicitly null for MC-only tasks, or the reviewed data mask entry, never omitted.
The kernel implements `analyze(table, source_entries, sample)` and returns each
admitted source row including empty selections, with exact source_entry and the
complete quantity-ID fill mapping. Weights are captured from original arrays
before supplied code can change them. MC rows cannot be omitted.

Data blinding requires exclude_signal_regions, reviewed source, blind_entry and
explicit allowed control/validation regions and a closed model_fields map from
quantity IDs to permitted CR/VR bin IDs. The pinned root-stream-blind-domain
source binds domain_id, original_goal_sha256, those exact allowed fields, protected
regions and review_source. It is the immutable prospective domain, not a later
pass assertion. `allow(table, allowed_regions)`
returns an exact boolean row mask; it runs before data reaches analyze. Raw rows,
explicit excluded-row counters, previews and plugin stdout/stderr do not enter model context
or published logs. This requires trusted source-reviewed analysis/mask code; it
is not a hostile-code OS sandbox. Complete DATA entries/intervals/identities and
moment state remain restricted machine records. Public analytical packets expose
only allowed CR/VR bins and covariance, plus a digest/completion verdict of the
private census; no total DATA entries, range endpoints, SR values, empty/flow or
excluded counts. Ordinary Host model presentation rejects typed internal DATA
source/census/native records; models consume the safe source-context/aggregate
projection. External CERN metadata and arbitrary trusted Python remain outside
this enforcement, and source/mask safety needs independent review.

Complete runtime capture has a prospective 64,000-file/8 GiB ceiling and 32 MiB
manifest/request bounds. Root measured an existing 31,654-file full host; the
actual Linux site profile remains unmeasured. Large local scientific members
use descriptor-streamed size/checksum checks independent of document limits.
Runtime binds exact interpreter, complete trees, site roots and versions
NumPy1.26.4/Awkward2.6.7/Uproot5.3.12 plus the transport above. Site names RSE/id,
initial allowed hosts, finite read timeout, persistent output and null or named
credential reference. Values are resolved only in the private worker. XRootD
redirect trust remains site policy, not proof of every actual server hostname.
Server replies retain their checksum algorithm (Adler32 never becomes SHA256).
GUID is source-authority metadata; before/after checksum/size and actual tree
entry count are metadata evidence, not an atomic server lock/full-byte SHA claim.

Complete contiguous original intervals retain empty trees, uneven final chunks,
empty selections and signed cancellation. Partial completed intervals are retained
on failure without automatic retry. Time/RSS/output/member/chunk/quantity bounds
are explicit. The ordinary supervisor and final source/descriptor/member checks
retain the actual evidence boundary.

## Prepare and export

```sh
ravel root-stream --request task.json
```

This is source-only context. Host root-stream-context requires every metadata and
kernel source as a Graph input and exposes no raw data. Ordinary schema2 plans
require one attempt, zero redos and root-stream-delivery's delivery-only scope.
All existing approval, launch, review and result rules remain authoritative.

Site export schema1 declares site_id, python, tasks, audit, wms. python is the exact
site-analysis interpreter pin; wms is engine=snakemake/version=9.27.0/cores=1/retries=0.
Ordered tasks have unique id, rundir, actual canonical plan pin, owner and earlier
actual depends_on IDs. Owner is ordinary or the actual research_cycle/cycle/
experiment association read from records. A staged actual campaign parent cannot
be omitted. Arbitrary shell commands, retries and automatic resume are refused.

Audit binds complete prompt pins, exact model_build, timezone-aware timestamps,
token_accounting, environment, tracked_skill_sources and blinding_policy. The
latter binds exclude_signal_region_data_from_model_and_analysis, review_source
and original_domain (the original root-stream-blind-domain pin, or null for no
data tasks). Every data root-stream task in one frozen export must preserve that
exact domain; verify rechecks it before adaptive task execution. Unknown historical records block complete submission provenance; they
are never invented. Supplied prompt completeness/safety needs independent review.

```sh
ravel site-workflow export --request site-export.json --out /absolute/persistent/export
```

The generated Snakefile runs no Python when parsed: integrity is the explicit rule
ravel_verify_export (marker completed/.export-verified-<sha12>.json), which every
task rule (task_<id>) takes as input. Task ids `all` and Snakemake keywords are refused.
Tests parse every generated Snakefile with real Snakemake `-n` when RAVEL_TEST_SNAKEMAKE
names a tests-only Snakemake; site execution through Snakemake is not yet qualified.

Fresh workflow.json/Snakefile/export-closure and WMS argv bind original manifest
digest, full source and retained completion receipts. Rules call existing
science.run or research_cycle.run_experiment via the exact analysis interpreter.
Campaign locks, charges, deadlines, prerequisites and acceptance remain unchanged.
Delivery markers commit actual result/verification bytes and infer no acceptance.
Export does not relocate approved plans, create approvals, renew deadlines,
adjudicate, invoke a model or submit to a batch scheduler. Prepare at the actual
site; failed/ambiguous operations require existing explicit recovery/intake.

18TB data availability, source normalization/branch units, credential policy,
validated background strategy and sensitivity remain separate original obligations.
The complete130/16/18/52 programme and earlier failures remain preserved.

## Code provenance

This is original RAVEL implementation using public APIs reviewed against
[US ATLAS AF AI](https://usatlas.github.io/af-docs/ai/),
[marketplace](https://github.com/usatlas/marketplace),
[fsspec-xrootd0.5.5](https://github.com/scikit-hep/fsspec-xrootd/tree/0b5121497e9dfb7c17f84fbc00579f90d01268b0)
(BSD-3-Clause), [XRootD6.2.0](https://github.com/xrootd/xrootd/tree/v6.2.0)
(LGPL-3.0-or-later) and [Snakemake9.27.0](https://github.com/snakemake/snakemake/tree/v9.27.0)
(MIT). No upstream source is copied into this product and no upstream agent skill
replaces RAVEL's authority rules. Exact source/API intake is retained privately.

## Background design, independent validation and sensitivity handoff

`ravel site-workflow statistical-handoff --request handoff-request.json --out <fresh>`
consumes the exact original ordinary stream result/closure and current stream task,
plus a complete pinned source-defined design. It materializes distinct observed
control-region background and null-observation expected SR/CR constructions for
existing `statistical_construction`/`native-likelihood` consumers. VR counts remain
held out. Background transfer/ABCD laws, domains, nuisance responses, original
normalization and sensitivity generating assumptions are supplied scientific
inputs; none is inferred from histograms. Every mean term explicitly maps a full
MC sample/quantity/all-region bin roster, including control signal contamination.
Global MC denominators and signed moments/variation covariance remain attached;
DATA evidence is the same permitted CR/VR projection, never the private state.

The design binds original region roles; count observations require unit-weight
integrated data with integer means, variance equal to the count and zero sameevent
cross-bin covariance. Multifill/overlap/weighted ambiguity refuses a Poisson join.
CR/VR share one actual joint data quantity; VR never becomes fitted CR. No SR
observation can be inserted, and zero-masked SR is never substituted for null.
Existing expected-data semantics retain a separate supplied-nominal generating
law. No Gaussian MC nuisance or independent Poisson auxiliary is invented.

Supply actual native runtime and both fit contracts in the design's native_bundle
pin to emit concrete existing native-likelihood tasks; null is an explicit
missing-runtime blocker while the source-bound construction tables stay usable.
Ordinary planning/review remains unapproved. No fit, validation or sensitivity
is executed by this handoff. The independent validation/calibration studies and
actual background/sensitivity result remain part of the original goal.

`root_stream.blinding_check(result, destination, public_paths, accepted_policy)`
is the fixed genuine final-packet checker. It authenticates original result,
private request/native census and recomputed safe projection, then exact bytes of
ordinary result.json and root-stream-report.json/.md. The ordered three-path
roster is mandatory; selecting private native/closure/recipe records or widening
the original accepted policy refuses. It returns schema1
blinding_preservation_check with policy_sha256, status=pass, sr_data_exposed=false
and checked_paths. This witnesses these actual public packets only; arbitrary
additional figures/files require their own source-defined blinding check.


### Current ordinary origin and machine-private artifact presentation

An existing WMS completion marker and every predecessor output must resolve the
actual canonical approved plan, original spent attempt, launch/admission receipt,
succeeded execution and complete current output census through RAVEL's existing
science lifecycle. A caller-created passed JSON file cannot establish delivery.
The statistical handoff uses the same successful original ROOT producer boundary;
its pure table projection remains conditional on the supplied complete scientific
laws, and neither boundary grants scientific acceptance or new execution rights.

Before presenting an artifact as model context, inline review text, a binary
witness or an on-demand catalogue/page, the Host uses its authenticated original
source identity (also retained by role-packet copies). Within an actual ROOT-stream
producer namespace only the three source-recomputed public analytical exports are
eligible. The complete native request, progress JSONL ledger, census, closure and
other original records remain machine-private regardless of their JSON keys or
packet-copy filename. Public CR/VR aggregate exports remain usable under the exact
original blind domain. This is provenance enforcement on actual produced artifacts,
not an OS sandbox or a classifier for arbitrary text copied outside provenance.


Schema-2 exports resolve the authenticated original stage before an attempt, or
its actual selected stage after the retained attempt/correction token exists.
The prepared plan has no top-level output-directory field. A changed selected
destination requires a fresh exact export; it cannot reuse an old WMS marker.
Model presentation refuses a producer namespace with retained original science
records and a missing, renamed or nonordinary plan. Loss of authority cannot make
its private DATA intervals into an external text input. The genuine lifecycle
regression is a proposed two-record signed-weight software control, not ROOT/site
or scientific qualification.


## Complete partitioned ROOT studies

Config schema2 adds one closed `partitioning` object to the unchanged schema1
ROOT contract. It is `{master: {path, sha256, size}, operation: "partition" |
"merge", partition_id: string | null, completions: [original completion pins]}`.
A partition is an unnormalized machine record; it is never a completed study.
The existing `root-stream` ordinary mode and supervised science worker execute
both phases. Snakemake wraps the existing approved tasks; it supplies no new
actor, scientific approval, retry permission or resource renewal.

Prepare a pinned full schema2 scientific specification whose ROOT config is the
original schema1 complete study. The planner request has `schema_version: 1`,
`specification` pin, `partition_entries`, `max_partitions`, `grouping` and
`budget`, plus the bound existing `owner` described below. Grouping is `{kind: independent_entries | declared_groups, source:
{path, sha256, size}, statement}`. An independent-entry premise must be explicit
and source-reviewed; file or partition boundaries do not prove independence.
A declared group source is `{schema_version: 1, kind: physical-event-groups,
groups: [{id, sample, spans: [{member, start, stop}]}]}`. This complete original
preselection census includes every entry, including no-fill entries. Each whole
group remains in one partition, including groups crossing source files within
one explicit sample. A group larger than the prospective partition allocation
refuses instead of splitting. Cross-sample groups with different normalization
or missing cross-sample covariance construction refuse; no independence is
inferred. Raise the declared allocation explicitly if a complete group needs it.

`budget` is `{partition_seconds, merge_seconds, max_total_seconds}`; the sum of
all partition ceilings plus the merge ceiling must fit both the original ROOT
limit and original scientific specification. Original RAM, source, site,
selection, branch, weight, blinding and complete normalization contracts stay
fixed. Ordinary/campaign admission and actual charges remain authoritative.
The planner uses at most 10,000 complete partitions and a 64 MiB authenticated
master allocation, with no truncated roster. Schema2 native request/closure
transport is bounded at 64 MiB; schema1's original request/closure bounds remain.
Runtime membership remains a complete bounded census, never a model-context dump.

```sh
ravel site-workflow partition-plan --request partition-request.json --out /owned/master
```

The returned master pin and per-partition specification pins are machine-private.
Plan each generated specification through the existing scientific-study intake,
review and ordinary execution APIs. Export those already prepared studies using
ordinary `ravel site-workflow export`; execute only through its admitted ordinary
or research-cycle owner. After each successful selected ordinary attempt:

```sh
ravel site-workflow partition-record --request completion-request.json --out /owned/master/completed/PARTITION_ID.json
ravel site-workflow partition-resume --request resume-request.json
ravel site-workflow partition-merge --request merge-request.json --out /owned/merge-draft
```

The record request is `{master, partition_id, rundir}`. Resume and merge requests
are `{master, completions}`. Each completion is bound to the canonical original
master, successful approval/admission/attempt receipt, original output census,
complete raw native census, closure, current source and exact selected task.
Caller-created passed JSON, repeated IDs/run directories, changed sources,
stale receipts and incomplete coverage refuse. Resume lists pending partitions;
it cannot renew a spent failed ordinary attempt. A fresh merge specification is
created only after the complete original completion roster authenticates. Plan,
approve and optionally export that merge through the same ordinary route.

Partitions retain bounded floating-point expansion partials for every raw first,
second and cross moment, not rounded per-partition means. Complete groups sum
record contributions before their outer product. All quantities, weights,
variations, empty records and source entry intervals survive the merge. One
original full signed generator denominator per DSID then supplies the single
normalization factor. Group-level raw generator sumw2 and original record squares
are separately labeled. The unchanged statistical handoff accepts only the
successful complete ordinary merge, keeps observed CR and held-out VR distinct,
and uses null-observation expected SR sensitivity. Ambiguous correlated or
multifill DATA-to-Poisson mappings still refuse. The joint moment matrix carries
cross-bin/variation (and explicitly declared fold-quantity) blocks; no unrecorded
cross-fold covariance or independent replica assumption is fabricated.

The master, grouping source, partition configs, full DATA intervals and completion
records remain restricted machine provenance. Original source paths identify
these namespaces before ordinary Host decoding, including authenticated role
copies and retained namespaces. Only the complete merge's existing fixed public
CR/VR projection is analytical/model evidence. An incomplete DATA partition has
no public counts, interval endpoints or complement yield. This enforcement is
not a sandbox for arbitrary Python, manual out-of-band copies or external CERN
metadata. ROOT access, Linux runtime/ABI, production independence, normalization,
selection, background modeling and numerical/physics qualification still require
actual scoped evidence; source preparation and synthetic software controls do not
establish those claims.


Partition masters require `owner: {kind: research_cycle, cycle: <existing-cycle>}`
in the partition-plan request. The existing cycle must have enough original
wall/native-attempt allowance for the complete master. Preparation debits the
whole declared master ceiling once in its durable resource ledger, keyed by the
original specification digest; it grants no approval. Re-preparing the same
original specification under this owner cannot reset that reservation.
At the actual approved ordinary worker boundary, a canonical partition or merge
identity claims its exact registered run/attempt in the same immutable journal.
Claims retain their full declared seconds after failure, interruption or missing
terminal evidence. A new run directory cannot renew one. Resume distinguishes
unclaimed pending partitions from blocked claimed partitions, and reuses only
the original successful ordinary receipt. Automatic failed retries remain
unsupported; a new scientifically revised study requires the existing separate
research design/admission route, rather than replacing the original master.
The master deadline starts on its first actual claim and is never renewed; each
branch must also fit the original campaign deadline. WMS duplicate task IDs or
run directories cannot evade the canonical master/partition identity guard.

The complete roster uses a bounded source-typed attempt journal under the original
campaign, with one constant-size predecessor record per canonical task (up to
10,000 partitions plus merge). Its genesis pin is anchored in the original
campaign's master reservation. This keeps the existing 128-revision generic
role/campaign limit unchanged: the campaign only needs its reservation and
initial clock commits, not one generic revision per data partition. No partition
is dropped, and no full historical snapshot is copied on each claim. Missing or
changed records, broken ancestry, incomplete publication and head rollback with
retained later records refuse. Failure/unknown status cannot release a claim.


For an actual campaign experiment using this schema2 master, the experiment
retains its original declared branch cost and ordinary plan. The whole master
already reserves the exact branch wall/native attempt, so its campaign ledger
adds only separately declared calls/tokens and any wall overhead above the exact
branch ceiling. The source-bound master pin is retained in the original planning
and dispatch events. Phase allocation keeps every original check, polish cost,
current evidence requirement and actual usage; its derived construction debit
attributes the already reserved branch rather than charging it twice.

The ordinary campaign dispatcher checks current hypotheses, premises, reviewed
parents, phase evidence, complete inputs and approved plan while holding its
existing operation lock. For this authenticated partition/merge only, it then
releases that lock before waiting for science.run. The actual registered worker
reacquires the same lock and repeats the campaign admission against the current
state and exact dispatch event before publishing its original immutable claim.
The ordinary run/attempt locks and master claim journal remain the concurrency
and failed/unknown-spend authority. Merely holding a lock, planning a study or
passing a Boolean cannot replace this admission. Direct standalone ordinary
partition runs remain supported under the same original master reservation;
direct dispatch of a campaign-owned experiment without its current campaign
boundary refuses. Other science experiment lock lifetimes remain unchanged.

## Site readiness, datasets and batch execution

Check the site before a long session:

```sh
ravel site doctor --profile lxplus --eos-dir /eos/user/a/me/work
ravel site install-plan --env-prefix /afs/cern.ch/work/a/me/env --checkout /afs/cern.ch/work/a/me/ravel
```

The doctor checks Python 3.12, the grid proxy lifetime, a Kerberos ticket, EOS
write access, CVMFS, the HTCondor or SLURM client, TeX, Node, an agent CLI, rucio,
apptainer, XRootD and tmux. It prints no credential contents. `install-plan`
prints the no-root route: Miniforge with Python 3.12 in your work space, then
`site_installation.py`. For long sessions run the agent in tmux, renew Kerberos
with `krenew` or `k5reauth`, and create a long proxy with `voms-proxy-init --valid 96:00`.

Build the dataset document from grid datasets with `ravel ntuples`:

- `resolve` reads a declaration (`samples` with `id`, `kind`, `dsid`, `process`,
  `tree`, `dids`; optional `rse`, campaign `rules` and `split_by_campaign`) and
  asks rucio at the site, or reads `--listing` with the same content, for every
  file's GUID, Adler32, size, entries and `root://` replica. The raw responses
  are kept as the checksum and membership authority.
- `normalize` reads the full sum of weights per file from a declared bookkeeping
  object (`{"kind": "histogram", "object": "<name pattern with {dsid}>", "bin": N}`,
  `{"kind": "tree-sum", "tree": ..., "branch": ...}` or a supplied `table`), joins
  cross section, filter efficiency and k-factor from a supplied database whose
  column names and `cross_section_unit` you declare, takes the luminosity per
  campaign from a supplied table with its `unit`, and writes the dataset with
  its population and normalization records. A DSID missing from the database, a
  bookkeeping object for another DSID, or a sample spanning campaigns is refused.

Process many files in parallel with `ravel partitions` on the `site` backend
(HTCondor or SLURM); each partition is a batch job with its own receipt and the
merge checks every partition. See [execution backends](execution-backends.md).

## Recorded procedure and environment export

`ravel procedure export --rundir RUN --into FRESH_DIRECTORY [--cores N]
[--baseline-environment SNAPSHOT.json]` works on recorded runs from any operation.
It writes `procedure.md`, `procedure.json`, a relative `Snakefile`, `closure.json`,
`worker-audit.json`, `environment.json`, `environment-diff.json`, scheduler profiles
and `templates/theory.smk`. `ravel procedure verify --package DIRECTORY` rechecks
file digests, source pins and the run record roster. Do not overwrite an export.

Each rule verifies the retained evidence of a recorded stage attempt or worker call.
Failure statuses remain visible. These rules do not rerun the recorded shell commands
or establish successful scientific results. Final quantitative reports emit an export
only after their existing whole-parent delivery gate; submission export includes the
procedure too. `ravel status --rundir RUN --write` emits the same export for any
completed parent whose fresh lifecycle verdict is PASS. A refused export is recorded
in the packet with its reason and does not block the status refresh. Open parents remain
unexported by status; standalone procedure export remains available for inspection.
Other delivery owners call `procedure_export.export_for_delivery(rundir)`
after their own gate. This seam never changes completion authority.

Worker auditing reads every `agent-work/<node>/<attempt>/receipt.json` and its
checksum-bound transport-neutral `transcript.jsonl`, including production, reviewer,
consult, decision-review and research-coordinator roles. There is no role filter.
Legacy graph model calls remain visible with missing-transcript gaps. Missing builds,
timestamps or token accounting stay unknown. The procedure retains graph ids, versions
and thread ids when the producer recorded them; a framework checkpoint grants no
scientific authority. The audit ingests original worker prompts through `agent_audit`.
Research runs require the current computed disclosure from `completion_disclosure.build`;
a binding without the protocol refuses export. Non-research runs explicitly state that
no research disclosure applies, without inventing a zero funnel or human review.

Profiles under `profiles/local`, `profiles/htcondor` and `profiles/slurm` render bounded
core/job counts and zero retries. HTCondor and SLURM are labelled **configurable,
unqualified**. Their plugins, site account/partition, filesystem, interpreter and
submission policies must be configured and qualified at the site. Rendering or a
local dry-run does not establish native scheduler qualification. The theory template
maps symbolic → numeric → fit to named tasks in a supplied approved site-workflow
manifest. It executes only through that existing executor and its normal gates.

`ravel env snapshot --out SNAPSHOT.json` captures package metadata and runtime versions,
without reading environment variables or running native tools. `ravel env diff --before
OLD.json --after NEW.json` reports added, removed and changed packages and runtime values,
and refuses snapshots whose content id changed. Package names use standard normalized
spelling; capture time is excluded from the content id. `snapshot_id` is available to
backend-plan owners through the capture and export interfaces. Without a supplied
baseline, an export's diff explicitly compares its export-time snapshot with itself;
it does not claim knowledge of a historical execution environment.
