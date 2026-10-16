# Required site ROOT analysis and reproducibility workflows

Ordinary mode `root-stream` reads a supplied complete ROOT member population
using a source-reviewed kernel. `ravel site-workflow` exports already prepared
studies to Snakemake. Transport and reproducibility are separate from a designed
search analysis, background validity, sensitivity, inference and site availability.
Every original background/signal sample and missing scientific input stays in the
question. No filename supplies DSID, data/MC identity, units or normalization.

## Required Linux installation

Keep the checkout, prefix, runs and transcripts in a work area with enough quota.
Read the [native prerequisites](../installation.md), then install without root:

```sh
bash scripts/setup/install.sh --profile site --prefix /work/ravel-tools --lcg-view none
source /work/ravel-tools/config/ravel-env.sh
ravel site doctor --profile generic --prefix /work/ravel-tools \
  --runs-dir /work/runs --transcripts-dir /work/transcripts
```

For an HTCondor analysis facility, save this supplied site record as `site.json`:

```json
{"scheduler":"htcondor","requires_proxy":true,"requires_kerberos":false,"requires_afs":false}
```

```sh
ravel site doctor --profile analysis-facility --site-record site.json \
  --prefix /work/ravel-tools --runs-dir /work/runs --transcripts-dir /work/transcripts
```

`--site-record` overrides the analysis-facility profile's Slurm default and its
credential requirements. Declare only the requirements that the site actually has.

Choose an absolute LCG view path containing `setup.sh` when the facility uses
CVMFS. `auto` lists this CPU's candidates and refuses installation. The installer
carries the explicit choice through `RAVEL_LCG_VIEW` and writes
`<prefix>/.ravel-site/lcg-view.json`: schema version1, `choice`, `release`,
`platform` and `path`. For `none`, the last three fields are null. The doctor fails
if the recorded view disappears. Source `<prefix>/.ravel-site/lcg-view.sh` in the
analysis shell that needs the view.

Linux CPython3.12 runs `<prefix>/.ravel-site/site-analysis`, installed from
`requirements-full.txt` and `requirements-site.txt`, and the separate
`<prefix>/.ravel-site/site-wms`, installed from `requirements-site-wms.lock` with
`pip --require-hashes`. The WMS lock includes Snakemake9.27.0, packaging25.0,
cluster-generic and its compatible executor interface (`>=9.3.2,<10`). A release
ships the lock. Maintainers regenerate it from `requirements-site-wms.in` with
`bash scripts/setup/lock-site-wms.sh`, which needs network access to the package
index. A missing lock stops installation. The analysis and native environments
retain their existing dependency contracts.

`<prefix>/.ravel-site/wms.json` records schema version1, the Snakemake executable
and version, each executor plugin and version, all locked packages, copied lock
path and sha256, analysis interpreter, shim and installed release tag or commit.
Run `<prefix>/bin/ravel-snakemake`: it clears `PYTHONPATH`, `PYTHONHOME` and
`PYTHONSTARTUP`, sets `PYTHONNOUSERSITE=1`, and executes the WMS Snakemake.
RAVEL resolves the shim using `RAVEL_SITE_PREFIX`, `RAVEL_NATIVE_BUILD`, the
site-analysis interpreter's prefix or the native-prefix pointer. The facility view
stays out of the workflow manager.

One prefix holds one release for one campaign. `campaign.json` reserves the release
before creating either site environment. A different release is refused with both
release names: install the new release into a new prefix once the current campaign
ends. Exact interrupted declarations can resume; changed declarations require a
new prefix. The project profile and launch receipts also belong to that campaign;
retain their original pins when changing releases.

Installer children, `config/ravel-env.sh` and container wrappers set
`APPTAINER_CACHEDIR=<prefix>/cache/apptainer` and
`APPTAINER_TMPDIR=<prefix>/tmp/apptainer`. Installer temporary files use
`TMPDIR=<prefix>/tmp` on Linux; pip, conda and XDG caches also use the prefix. The doctor
reports both Apptainer locations and fails when an override escapes the prefix.

The site disk gate is 10 GiB: the selected groups and dependencies total 9.1 GiB
in the manifest estimates, with 0.9 GiB headroom; it is an estimate, not a measured peak. The doctor
reads `fs listquota` on AFS paths or `quota -s`, then free space with `df`.
The prefix needs at least the install size. Runs and transcripts need 4 GiB free
by default; `--min-free-gb` sets their threshold and can increase the prefix
threshold. A home location with insufficient or unknown free quota is refused.
Choose a work area with enough space and quota. The installer applies the same
prefix rule before creating the site environments.

The site target keeps publication PDF, graph and SVG tools and uses pyhf for
statistics. It omits the Combine container and the separate TeX group. Software
installation and synthetic tests leave facility execution, native ABI, data access
and scientific validity to their own qualification.

On a Mac, generate concrete commands for a supplied remote Linux checkout:

```sh
python3.12 scripts/setup/site_installation.py --plan --linux-root /absolute/linux/ravel \
  --prefix /work/ravel-tools --out required-site.json
```

Transfer the exact source separately; no local complete site runtime is claimed.
The helper does not change global configuration or submit jobs.

### Synthetic site qualification

`site-root-wms` and `site-access` declare `tester-qualification`. The facility user
qualifies them after the site doctor passes. Installation and fake tests leave
them unqualified. Provide bubblewrap (`bwrap`) on the Linux worker and run
`ravel transport qualify <transport-id>` for the selected installed worker.
The doctor reads stored probe and qualification records; it never runs either.

Create a fresh work directory containing this `Snakefile`:

```python
rule all:
    input: "second.txt"
rule first:
    output: "first.txt"
    shell: "printf 'synthetic input\\n' > {output}"
rule second:
    input: "first.txt"
    output: "second.txt"
    shell: "cat {input} > {output}"
```

Export the configured HTCondor profile for this release. Its submit and status
console scripts must resolve to the site-analysis interpreter. The doctor reports
`ravel-wms-condor-submit` and `ravel-wms-condor-status` and skips them in a release
that does not declare them; qualify the profile once both rows pass. The following direct shim command is the synthetic qualification and manual fallback.
For approved campaign stages, use the governed `ravel wms init/launch` path below.
Run this check against a real single-node HTCondor or the permitted test queue:

```sh
/work/ravel-tools/bin/ravel-snakemake --snakefile /work/site-qualification/Snakefile \
  --directory /work/site-qualification --profile /work/site-qualification/profiles/htcondor \
  --jobs 1 --cores 1 --retries 0
```

Retain the release and lock digest, doctor JSON, profile, submission/status logs,
worker qualification records and both output files. Require a successful scheduler
exit and equal file contents. These receipts qualify the tested facility and
synthetic workflow. The doctor reports the built-in batch-slot lease policy. Governed HTCondor workers
use `_CONDOR_SCRATCH_DIR/.ravel-lease` with `RAVEL_LEASE_SCOPE=batch-slot`; a missing,
relative, linked or unowned scratch directory, or one without the starter's job ad
named by `_CONDOR_JOB_AD`, refuses the lease. Persistent state
stays in the shared work area. Machine actions are never labelled human approval.

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
site-analysis interpreter pin. wms is either the original
engine=snakemake/version=9.27.0/cores=1/retries=0 block or a bounded profile that adds
`profile` (local|htcondor|slurm), `cores` (1..1024), `jobs` and `remote_ceiling`.
Snakemake `retries` stays 0 in both: a Snakemake retry would re-run a spent run-step,
so a failed partition is retried by RAVEL instead (below). Locally, `cores` may not
exceed the slots the machine lease admits on this host (one on macOS: one native
scientific job at a time) and `jobs` may not exceed `cores`. A remote profile bounds
`jobs` by its `remote_ceiling`, which must fit the owner-set remote job ceiling
(`RAVEL_REMOTE_JOB_CEILING`); each remote worker relies on its host-scoped lease.
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

A plain site export requires the exporting shell's runtime settings to match the plan's runtime digest.

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

## Workflow-manager-first projects

A project can require that its approved stages run only through Snakemake:

```sh
ravel wms init --project PROJECT --audit audit.json [--python PY] [--site-id ID]
ravel wms add --project PROJECT --rundir PROJECT/runs/RUN [--task ID] [--after ID ...]
ravel wms launch --project PROJECT --task ID
ravel wms status --project PROJECT
ravel wms revalidate --project PROJECT --task ID
```

`init` writes `workflow/policy.json` (`wms_required: true`), `workflow/project.json`,
an empty `workflow/index.json` and a stable `workflow/Snakefile`. The Snakefile reads
only `index.json` at parse time, includes `rules/<task>.smk` in sorted order and has the
single `rule all`. The audit block lists record paths; the local profile has one core
and no retries.

For an HTCondor analysis facility, initialize the project on its worker-reachable
shared POSIX work area. Set the owner ceiling in the launch environment; the
project's declared ceiling must fit it (the owner default is one job):

```sh
export RAVEL_SITE_PREFIX=/work/ravel-tools
export RAVEL_REMOTE_JOB_CEILING=32
ravel wms init --project /work/campaign --audit /work/campaign/audit.json \
  --profile htcondor --jobs 8 --remote-ceiling 32 --shared-state-root /work \
  --python /work/ravel-tools/.ravel-site/site-analysis/bin/python
ravel wms add --project /work/campaign --rundir /work/campaign/runs/RUN --task TASK
ravel wms launch --project /work/campaign --task TASK --jobs 8
ravel wms retry --project /work/campaign --task TASK
```

Optional `init --site-options options.json` supplies the existing validated HTCondor
submit options, including memory, runtime, analysis-bin path and opt-in proxy path
handoff. The governed profile fixes `workflow_dir` to the project workflow and
`lease_scope` to `batch-slot`. It is exported by `site_profiles/htcondor.py` to
`PROJECT/.ravel-site/profiles/htcondor/`, outside `workflow/profiles`. Both profile
files and their complete member roster have a combined SHA-256 digest recorded
in `project.json`, bound at `add`, and checked before every launch. Each launch
copies those bytes to `PROJECT/.ravel-site/launches/TASK/N/htcondor/`, pins the copy
in its receipt, and invokes the pinned installed `ravel-snakemake` shim with
`--profile <copy> --jobs N --cores 1 --retries 0`. It ignores the ordinary
`RAVEL_SNAKEMAKE` override for this route. The HTCondor default keeps the active
Python launcher, including its virtual environment symlink; `--python` selects the
site-analysis interpreter explicitly. A changed profile, shim, project ceiling
or extra profile member is refused. Local projects keep the one-core command.

`launch --jobs N` defaults to the initialized count and must fit the declared
remote ceiling and the current owner ceiling. Partition tasks additionally retain
the exact fan-out pinned in their approved master; a project ceiling cannot widen
that approval, including for unfinished `--after` tasks. Snakemake retries remain zero;
`ravel wms retry` plans/registers a fresh approved partition attempt within its
master's attempt bound. No launch flag enables scheduler retries.

The declared shared root must contain the project, run state, exports, launch
records and live authorization locks. Node-local temporary and worker scratch
paths are refused. A path declaration cannot establish remote reachability:
qualify identical paths, read/write access and cross-node POSIX locks on the
workers before a campaign. The run directories' canonical paths must stay inside
the project. Per-slot leases use worker scratch while persistent state stays
shared. A site run and retained worker receipts are still required for facility
qualification.

The strict guard admits a site command only when its exact argv matches a live
`ravel wms launch` record, using the pinned shim, profile digest and bounded job
count. It rechecks the profile and frozen parse inputs. Arbitrary `--profile`,
`--executor`, retry options and alternate paths are refused. A completed launch
record grants no authority. The normal agent entry point is `ravel wms launch`;
the direct shim example above remains a manual qualification/fallback outside
this governed launch contract.

`add` runs after approval and before execution. It refuses a run dir without a current
approved plan and names `ravel approve`; Snakemake never approves. The run dir must sit
inside the project, so that the project's policy governs it. `add` writes a one-task
site-workflow export under `workflow/exports/<task>/` and its rule as
`workflow/rules/<task>.smk`. Then it records the task, export, rule and policy pins in
`index.json`. An aborted or failed run leaves the rule and export intact. A spent
attempt cannot resume; add a fresh approved attempt under a new task id. Duplicate task
ids, a run dir that is already a task and `--after` names missing from the index are
refused before any rule is written. `--after` makes the rule depend on those tasks'
completion markers, and run-step checks their deliveries, such as a note built after
its analyses.

The prompt and token logs grow during a session. `add` freezes a copy of the prompt,
token-accounting, environment and tracked-skill records under `workflow/audit/<task>/`,
and the export pins the copies. The final submission binds the final logs. The blinding
policy keeps its original pin and is validated as for any export.

`launch` runs Snakemake with the target `exports/<task>/completed/<task>.json`. Any
unfinished `--after` tasks run first. Each rule runs `site_workflow run-step`, which
re-verifies the export and approval and calls `science.run` or
`research_cycle.run_experiment`. It writes the completion marker. Each launch writes
`workflow/launches/<task>/<n>.json` with the Snakemake argv, version, start and end
UTC, exit code, marker pin and log. The receipt records delivery only. The Snakemake
version is read before the stage runs. A delivery record that cannot be read after the
run marks the receipt `incomplete` and names the record, so a stage that ran always has
a receipt. Dispatch records of the `--after` tasks that ran inside a launch are attached
to that launch's receipt.

`launch` refuses a task whose policy file changed since `add`. The run stays governed
through its index entry whatever the policy now says, so the refusal names the pinned
digest and two ways out: restore the policy file, or acknowledge the change with
`ravel wms revalidate`. `revalidate` re-pins the current policy for one task. It first
checks that every governance file on the path is well formed, that the run is still
governed, that the plan is still approved and that the export and the rule are
unchanged. It records the previous and current pins in the index entry. It approves
nothing and runs nothing.

Under `workflow/.wms.lock`, `launch` reads the Snakefile, the index and every indexed
task's rule once, including rules for other tasks. It verifies the stable Snakefile
bytes and every rule pin, reserves a new log and writes the verified bytes as read-only
copies to `workflow/launches/<task>/<n>.parse/`. A changed or missing rule refuses the
launch. Snakemake parses the copies with the project workflow as its working directory.
An edit or a concurrent `add` after the check therefore cannot change what the launch
parses. The receipt pins the copies under `parse_inputs` and records in
`unchanged_after_run` whether they still matched after Snakemake returned. Logs and
receipts never overwrite an earlier launch's evidence.

Snakemake loads `profiles/default/` beside a workflow and the profile named in
`SNAKEMAKE_PROFILE`, and turns every key into a command-line option that the receipt's
argv does not show. `launch` refuses when `workflow/profiles` exists and runs Snakemake
without `SNAKEMAKE_PROFILE` or `SNAKEMAKE_WORKFLOW_PROFILE`. The receipt records under `snakemake_profile` whether the
variable was removed or absent.

When the policy requires the workflow manager, a direct `ravel run`, `science.run` or
`research_cycle.run_experiment` on a governed run dir is refused with the `ravel wms`
route. The stage supervisor (`ravel stage`) refuses a direct launch on a governed run
dir for every approval route: a scientific study, a scoped plan, a native plan and a
compute rung. Only a stage with no approval route, such as a build step, is outside
that check. A run stays governed
while any ancestor `workflow/index.json` lists it or any ancestor
`workflow/policy.json` requires the workflow manager. A nearer policy cannot lift
that requirement. An index lists a run by the identity of its directory: an entry
written with `..` segments or through a symbolic link governs the same run, and a
relative entry is refused. A malformed policy or index anywhere on the path refuses
dispatch, and the refusal names the file. A policy with a duplicate key and a dangling
policy or index link are malformed. A `workflow/index.json` that belongs to another
tool governs nothing: it has no `workflow/project.json` or `workflow/policy.json`
beside it and is valid JSON without a `tasks` list.
Scoped runs inside a governed project are refused by the CLI, the library and the
stage supervisor:
scoped runs are not workflow-manager tasks. Run them outside the governed project,
or set the governing project's policy to not require the workflow manager; any
remaining governing ancestor or index entry still requires it.
Only run-step lifts the refusal, through an
in-process context entered after its own verify; no environment variable lifts it.
For a governed run, run-step and that context require two things. The project index
must list exactly this export for the run: a plain export written elsewhere and a
second export inside `workflow/exports/` are refused and name `ravel wms add`. And
`ravel wms launch` must hold a live launch authorization for the task. `launch` writes
that record under `workflow/.live/` and holds its lock while Snakemake runs. The
record names the task, the tasks it depends on and their indexed export digests. A
`run-step` called by hand, a `.snakemake/locks` entry, an earlier launch and a record
left by a launcher that died authorize nothing, and the refusal comes before any
dispatch record is written.

`launch` first checks the task's run dir for its method decision
(`inputs/method-decision.json`). A full or scan run dir without a valid record is
refused with the method-decision refusal before its plan is read. Snakemake does not
start and no launch record is written.

While the stage runs, run-step holds a dispatch grant for its run dir in the same
folder. The authorized-launch boundary (`authorized_popen`), native `generate` and
`generate-activated`, and the scoped generation and likelihood payloads require
custody of a governed run: the step's own process has it, and a worker the step
started has it while the grant is held. A direct call to any of them on a governed run
dir is refused with the `ravel wms` route.

This is discipline, not a security boundary against code that rewrites these
functions. Every run-step writes `exports/<task>/dispatch/<n>.json`. The
record holds the working directory, whether `.snakemake/locks` held a lock during the
step and the runtime environment snapshot. `ravel wms status` counts dispatches
without a Snakemake lock and dispatches outside a launch. The plan does not yet pin
the policy file; governance checks at dispatch remain independent of that plan binding.

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
all partition ceilings, times the attempt bound, plus the merge ceiling must fit
both the original ROOT limit and original scientific specification.

An optional `fanout` is `{max_attempts: 1..5, wms: {profile, cores, jobs,
remote_ceiling}}`; without it a master keeps one attempt and the one-core local
profile. The fan-out is stored in the master, which every partition and merge
configuration pins, so CHECK-IN 1 of each branch shows it (section
`partition_fanout`: partitions, profile, cores, jobs, remote ceiling, attempt bound)
and changing any value is a new plan digest. An export whose wms profile differs
from the approved fan-out is refused at export and again at run-step. Original RAM, source, site,
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
the original successful ordinary receipt. A partition may claim again only up to
the master's `max_attempts`, in a new run directory. Earlier attempts must be
failed or reported as "ran but did not deliver"; unresolved attempts block retry. A
missing, unreadable or still-running execution record is unresolved and blocks
the retry. An interrupted record, or a failed record without terminal exit and
finish evidence, also stays unresolved until the recording host proves that its
child has ended. A PID on another host proves nothing. A running record stays
unresolved even when its child is absent. Run
`ravel run --rundir <attempt> --resume` on the recording host for existing
supervised recovery; this command grants no fresh attempt or approval. A record
that does not name its recording host stays unresolved: a process id observed on
this host proves nothing about a record of unknown origin.

Limitation: a workflow-manager project refuses that command for a run directory
it governs before supervised recovery starts, and no `ravel wms` command runs that
recovery. An unresolved attempt of a governed partition is therefore held: it
stays charged, and its partition is neither retried nor merged under this master.
The retry and merge refusals name this hold instead of the command. Continuing
that partition needs a new master reservation through the research design and
admission route.

Limitation: a lost supervisor is not resolved by that command. When the ledger
still says `running` and both the child and its recorded process group are
absent, `ravel run --rundir <attempt> --resume` records the attempt as failed
with `descendant_containment: not_established` and keeps a recovery hold. The
absence of the group leader does not establish that its descendants ended, so
the command does not make the attempt retryable. Repeating it changes
nothing. The attempt stays unresolved and charged, and its partition is neither
retried nor merged under this master. The retry and merge refusals name this
hold. Continuing that partition needs a new master reservation through the
research design and admission route.
Failed attempts stay charged. Resume lists `retry_admissible_partition_ids`. A
scientifically revised study still requires the existing separate research
design/admission route, rather than replacing the original master.

### Parallel partitions through the workflow manager and bounded retries

Partitions run in parallel through Snakemake over ordinary site-workflow tasks:
each prepared partition run dir is one task, and an export may add a merge rule
`fanin: [{id, master, output}]`. The merge rule waits for a delivery record
for every partition of that master, at its original task output path
`completed/<task>.json`. All original partition tasks must be in the export.
An original run-step or a later approved attempt publishes that
partition's selected delivery to this same output. Relaunching the original
export then runs the merge rule without dispatching spent partition rules.
The manifest and Snakefile retain their original bytes; manager retries remain 0.

In an HTCondor project, use `ravel wms init --profile htcondor` with its declared
shared state root and ceiling, followed by `ravel wms launch --jobs N`; scheduler
submission and each run-step remain attached to RAVEL launch receipts.
In a project governed from the start (`ravel wms init`), add each original
partition run directory with `ravel wms add` and run it with `ravel wms launch`
through its own one-task export. Create the export with the merge rule under
`PROJECT/workflow/exports/`, binding the same task ids and run directories. Its
partition rules never dispatch a governed run, and that refusal names
`ravel wms add`. When an original delivers through its indexed export, that
run-step publishes the delivery to every export under `PROJECT/workflow/exports/`
that merges the run directory as a partition. If that publication stopped before
the merge export's marker was written, or the original delivered but its own
marker was never written, relaunching the merge export runs the partition's rule.
The rule publishes the delivered original and dispatches nothing. A rule that
only publishes needs no launch authorization, because it runs no stage.

A later attempt reaches the merge rule by any approved route within the
master's attempt bound: a retry registered with `ravel wms retry`, a fresh run
directory planned from the same partition specification and run with
`ravel run`, or a new campaign experiment for a campaign-owned partition. Each
claims its attempt in the master journal at the same worker boundary, and a
campaign experiment passes its campaign admission there. When the original
export is relaunched, the rule of a partition whose original run directory is
spent publishes the delivery of the attempt that the journal selects and
dispatches nothing. A registered retry publishes through its retry ledger. An
attempt run outside the retry command has no ledger: its publication binds the
journal claim, the canonical completion and the ordinary result and
verification pins, and a registered retry cannot be published that way.

An ordinary task that depends on a partition task waits for the same delivery
record. Its run-step accepts the selected delivered attempt, original or
retry, after the same publication, claim and pin checks as the merge rule. This
holds for a dependency inside the export and for an `after` row that names a
partition task of an earlier export.

`ravel site-workflow fanin` selects exactly one delivered attempt per partition
from the authenticated master journal. It checks the issued publication pin,
canonical completion, selected run directory, and the ordinary result and
verification pins before writing the merge draft with `partition-merge`
preparation. A file alone grants no merge authority. A missing delivery names
the partition and `ravel wms retry`; multiple deliveries refuse. An unresolved
attempt also names the supervised recovery command. The draft still needs its own plan and approval.
Site and container placement of a scientific worker stays refused (see
`placement`); this route keeps the ordinary supervisor on the executing host.

When a partition task's run-step ends without delivery:

```sh
ravel wms retry --project PROJECT --task TASK      # plans PROJECT/.../RUN-attemptN
ravel approve --rundir PROJECT/.../RUN-attemptN    # ordinary approval; a retry never approves
ravel wms retry --project PROJECT --task TASK      # registers TASK_aN through ravel wms add
ravel wms launch --project PROJECT --task TASK_aN
```

Retry planning requires `inputs/method-decision.json` in the first claimed run
directory and copies its bytes into the fresh attempt. The receipt and each
planning or registration ledger step retain `method_decision_sha256`. CHECK-IN 1
discloses that carried decision before the fresh plan is approved. Registration
uses the same `ravel wms add` route as an ordinary project task and refuses if
the carried bytes differ from the origin. Missing origin records refuse before
planning; copying a decision grants no approval or execution authority.

Each attempt runs in a new directory; earlier attempts are kept, and every step is
recorded in `workflow/retries/<master>-<partition>.json`. Planning the first
retry of a partition records the merge exports under `PROJECT/workflow/exports/`
that wait for it; create the export with the merge rule there before that first
retry. When the registered attempt's run-step delivers, it publishes the delivery
to those exports; relaunch the original export afterwards. The ledger's
`delivery-published` step retains the attempt number, UTC time, export binding
and publication pin after the task output exists.
`delivery-publication-issued` records issuance before that write; issuance alone
does not authorize the merge. An interrupted publication is finished with
`ravel.workflow.wms_retry.publish_registered_attempt(project, rundir)`, which
never runs the attempt again; the merge rule names that call when a delivered
attempt has no published record.

Delivered means that the attempt's ordinary delivery exists and passes the same
receipt, result and verification checks used by partition recording. Execution
status `succeeded` and a completion marker alone are insufficient. A succeeded execution with a refused
result is reported as "ran but did not deliver", stays charged, is excluded
from the merge, and may retry only within the approved attempt bound.
A campaign-owned
partition is retried as a new campaign experiment instead; relaunching the
original export publishes its delivery as described above.
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

The doctor checks the installed WMS lock, Snakemake, executor plugin/interface,
explicit view, caches, locations/quota, profile interpreters, lease policy,
calling-shell PYTHONPATH, bubblewrap and stored worker qualification. It also
checks Python 3.12, grid proxy lifetime, Kerberos, EOS, CVMFS, batch clients,
Node, an agent CLI, rucio, apptainer, XRootD and tmux. `install-plan`
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
To run a whole study, agent included, inside one Slurm allocation, see
[running studies in batch allocations](batch-allocations.md).

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

Profiles under `profiles/local` and `profiles/htcondor` render bounded core/job counts
and zero retries. The SLURM profile is not available in this release. The HTCondor
profile has `qualified: false`, `release_status: "tester-qualification"` and the label
"awaits site qualification". Install `snakemake-executor-plugin-cluster-generic` at
the exact version in the site install lock, with
`snakemake-interface-executor-plugins>=9.3.2,<10` for Snakemake 9.27.0. The profile's
`qualification_command` is the qualifying command:
`snakemake --snakefile scheduler-check.smk --profile profiles/htcondor --jobs 1`.
Run it on the shared work area in a directory that holds the written profile, a
`scheduler-check.smk` with one small synthetic rule named `task_<id>`, and a
`run-keys.json` entry for that id. Rendering and local tests establish
configuration behavior; a successful site run establishes scheduler qualification.

`site_profiles.write_profile(directory, name, cores=1, jobs=None, options=None,
project_id=None)` writes `directory/name/config.yaml` and `profile.json` and returns
the directory, both files' SHA-256 pins and the profile. `write_profiles` calls that
writer for local and HTCondor. The governed project launcher exports its pinned profile under `.ravel-site` at
initialization. Standalone exports may call `write_profile` with a project id
and must write `run-keys.json` before starting Snakemake. That plain
JSON object maps task ids to study run keys, taken from `rdj_custody.root(rundir).name`.
The submit client reads the index without importing custody. It derives the task id
from `task_<id>` or `ravel_verify_<id>`. With a project id it refuses missing or invalid
tags. `RavelProject`, `RavelRun` and `RavelTask` each match `[A-Za-z0-9_.-]{1,64}`;
use opaque ids without paths, user names or host names. `batch_name` is the run key.
Pause and cancel select one study with `-constraint 'RavelRun == "<run key>"'`.
A pause sets the `RavelPause` attribute on the jobs it holds and must clear it when
it releases them: a job that carries the attribute keeps its hold exemption.

HTCondor calls `ravel-wms-condor-submit` and `ravel-wms-condor-status` through PATH.
Rendered commands carry `--project-id` and encoded profile options that survive
Snakemake command formatting; the clients also accept `--profile profile.json`.
The job's `threads` supplies `request_cpus`. Rule resources `mem_mb` and `runtime`
override profile defaults of 1024 MB and 60 minutes; the runtime is multiplied by
60 and written as seconds under `runtime_attribute` (default `+MaxRuntime`, matching
the batch backend). `flavour` supplies `+JobFlavour`. Declared `disk_mb` supplies
`request_disk`. `getenv = False` and an explicit minimal environment provide PATH
from `analysis_bin` plus `/usr/bin:/bin`, HOME from the submitter and only the named
variables in `ravel_env`. `lease_scope="batch-slot"`, the default, adds
`RAVEL_LEASE_SCOPE=batch-slot`; the built-in lease policy uses the worker
`_CONDOR_SCRATCH_DIR` as its scratch root, with locks under `.ravel-lease`. `lease_scope="machine"` omits that batch-slot marker. The job runs on the
shared filesystem with `should_transfer_files = NO`.

Credential hand-off is opt-in: `use_x509userproxy=true` uses the scheduler's proxy
selection, or `x509userproxy_env` names the submitter variable containing a proxy
path. The client passes the path and never reads or copies the credential.
`site_options` is a validated scheduler key/value map. Keys cannot contain spaces
or `=`; values cannot contain newlines. The map cannot override fixed resource,
environment, tagging, hold, credential or executable fields under any spelling:
the submit command, its `+Name` or `MY.Name` job attribute and the scheduler's
alternate names are refused alike, and `runtime_attribute` cannot name one of
them. A site `periodic_release` expression must exclude the three hold exemptions
below, or it releases paused jobs. `workflow_dir` selects
the workflow directory explicitly. `log_dir`, `output_dir` and `error_dir` select
separate scheduler log, stdout and stderr directories. Their default is
`.ravel-condor/` next to the job script. Put these directories and the workflow's
`.ravel-condor/` status state on the shared POSIX work area, not on object storage.

With a project id, status uses a per-project snapshot under a POSIX file lock.
At most once per `status_cache_seconds` (default 20), it queries the project's
queue once and queries history once only for missing registered job ids. The
history constraint includes those ids and its result limit is their count.
A history answer is recorded and that job is not queried again; the same holds
for a job that failed after its missing grace. Calls between refreshes read the
snapshot. The profile sets `seconds-between-status-checks` to that interval, so
Snakemake starts one sweep per refresh, and `max-status-checks-per-second` to 10,
because each job's call inside a sweep reads the snapshot. Without a project id, status queries each job
directly. Completed jobs succeed only with exit code zero. Removed jobs and system
holds fail. User holds (reason 1), jobs submitted on hold (reason 15), and jobs
carrying `RavelPause` report running at any hold age and are never removed.
`periodic_remove` removes other holds after `hold_grace_seconds` (default 1800),
preserving all three hold exemptions.
An absent or unknown job writes its first-missing time to `<id>.missing` in its
log directory, runs within `missing_grace_seconds` (default 600), then fails;
an unknown job never succeeds. A known status clears the marker. Scheduler client
calls have a 20-second timeout.

The theory template
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

## Facility agent plugins

A facility may expose its site tools through an agent plugin and MCP server.
For example, the [UChicago public AI guide](https://usatlas.github.io/af-docs/ai/)
describes `af-uchicago` from the `usatlas/marketplace` marketplace. The supplied
facility context includes Rucio lookup/download, AMI metadata, HTCondor status
and submission, notebook execution and filesystem capabilities; Codex and Cursor
can use the same server. Follow the site's current installation instructions.

The human installs the plugin in their host, signs in through the browser and
links their grid identity. Agents never receive, read, copy or manage passwords,
tokens or grid credentials. Authentication gives the server access; RAVEL still
requires a scope-covering CHECK-IN 1 approval before an effectful call. Review
actual MCP names and semantics against the declared policy. See
[site-tool admission](host-enforcement.md#site-tool-servers) for the generated
host declarations, explicit checks on hookless hosts and observation records.

## Agent guidance for approved workflow stages

See [Run approved stages through Snakemake](../guides/approved-workflow-stages.md).
`ravel agent-surface install --project PROJECT` preserves existing project
instruction documents byte for byte and writes portable guidance into
`.ravel/agent-guidance.md`. Its Snakemake skill reads the site-wms declaration or
toolchain manifest even when the separate environment is absent from PATH.
Machine paths stay in ignored local runtime files; load the guidance into the
host session alongside the project's instructions.

Before creating runs with restricted material, put the project's classification
and exact transport/account allowlist in `<project>/.ravel/data_classification.json`
and run `ravel agent-surface install --project <project>`. New runs inherit it and
record its digest in their inputs; run declarations may only narrow the project
restriction. `ravel agent-surface check --project <project>` reports the effective
policy. Once declared, a missing or unreadable default refuses dispatch rather
than restoring public behavior. Keep the declaration marker with the project and
the policy snapshot with each run. See [provider policy](../workflow/reference/provider-policy.md)
for declaration syntax, amendments and the saved/current restriction checks.

A policy-required project enables the shell discipline guard by default.
`--wms-guard` installs it explicitly; `--no-wms-guard --guard-approval FILE`
requires a recorded, project-scoped approval when the policy requires it.
The hook names `ravel wms add` and `ravel wms launch` on refusal. It grants no
approval and is not a security boundary. Plan and approve keep their check-ins;
never approve through the workflow manager. Launch/retry and site-record
integration require their installed owning interfaces; these agent-surface
fixtures establish no native or remote qualification.

## Portable submission packages

Export an accepted run into a fresh repository directory:

```bash
ravel export-submission --request request.json --into repository --framework-source vendor --framework-checkout tagged-framework
```

Use `--framework-source release:v1.0.0` to install framework code from its public
repository tag. Use `vendor` to ship the framework files inside `vendor/ravel/`.
Both routes require a local Git checkout at a release tag named `vMAJOR.MINOR` or
`vMAJOR.MINOR.PATCH`. HEAD must be the tag's commit, tracked shipped paths must be
clean, and the running RAVEL version must equal the tag's `pyproject.toml` version.
Without `--framework-checkout`, export uses the running module's source checkout.

The tag's own Git tree authenticates the framework files. The vendored set comes
from its sdist includes, readme, license files and the input census declared by the
custom build hook. That census includes canonical instructions, their packaged
copies and installation assets. It reads source contracts without running a build.
Git archive supplies the bytes; every extracted file is checked against its Git blob
id. `vendor/ravel/VENDOR-MANIFEST.json` records tag, resolved commit and each file's
path, SHA256 and blob id. Verification rechecks this manifest and the complete vendor
roster. The submission manifest carries the selected release-tree entries only for
vendor verification. `release:<tag>` records the tag and pins its resolved commit in
`environment/ravel-requirements.txt`; vendor mode names `./vendor/ravel`. The build
hook suppresses source bytecode writes while inspecting its inputs; `make env`
also sets `PYTHONDONTWRITEBYTECODE=1` before the package loader starts.

Before the vendor manifest is written, the release's own
`scripts/maintenance/restricted_source_scan.py` (read from the tag) scans the vendored
files. Set `RAVEL_RESTRICTED_SOURCES` to the owner's deny list, kept outside every
repository, and any listed document hash or fingerprint refuses the export; without it
only the uncited document-hash rule runs. An invalid deny list, a finding or a release
without the scan refuses the export and leaves no package. The manifest's
`restricted_source_scan` field records whether a deny list was supplied, never its
path or content.

The default export obtains its distribution name and version from its own source
project metadata or installed distribution metadata. Verification checks the pin
against the recorded framework identity. Select an explicit framework source for
a package checked against a release tag.

Supply `--layout layout.json` for repository conventions. Its schema is
`src/ravel/data/submission/layout.schema.json`:

```json
{
  "schema_version": 1,
  "subdir": "submission",
  "snakefile": "Snakefile",
  "rerun_target": "rerun",
  "required_files": ["Makefile", "REPRODUCE.md"]
}
```

`subdir` and `snakefile` are relative to the destination repository. Required files
are relative to the package. The example puts a launcher at the repository root and
the package under `submission/`. Paths outside the repository are refused. The default
is `submission/Snakefile` and a `reproduce` target. Export writes files and executes
none of the generated commands.

Run these targets from the package directory:

- `make env` runs `sh environment/setup.sh` and creates `.bin/` commands.
- `make check` runs `snakemake -n` with one local core.
- `make verify` runs `ravel export-submission verify --package .`.
- `make reproduce` selects the layout's rerun target using the governed replay
  template. Replay prepares a fresh run and stops at its approval gate. Approve
  that fresh plan through the ordinary RAVEL interface, then repeat the target.
  The package never grants approval or labels machine approval as human.

The embedded procedure calls `ravel procedure verify-node` through PATH and binds
source pins to the package's `run/` copy. Verification survives relocation and does
not execute scientific commands. Standalone procedure exports keep absolute source
pins for the original machine and disclose that limitation. Copied records that need
path changes become labelled package projections; gzip originals retain the exact
historical bytes, sizes and SHA256. Historical approvals grant no fresh authority.

At export, the portability scan checks literal matches of the original run directory,
exporting interpreter, framework checkout and home directory in text up to 8 MiB.
Slash syntax such as source comments, JSON pointers and relative rule expressions
is preserved. Metadata projections replace only known roots. Run inputs retain their
original bytes; retained review snapshots remain opaque evidence with content-addressed
names checked against their bytes. Compressed originals retain historical evidence.
A known machine root in other packaged text causes refusal. Subsequent verification
relies on the complete SHA256 listing rather than guessing filesystem paths.

`procedure/completed/`, environment installation directories, `.reproduce/` and every
nested `.snakemake/` are workflow working state. Fresh copies skip nested workflow
state. `.bin/` has no blanket exemption: only untracked setup-created command links
to the corresponding local environment are allowed; tracked unlisted commands refuse.
Other unlisted files fail verification. `verify --fresh-clone` checks another parent
directory and runs a dry run when Snakemake is available. Commit a Git package before
cloning it; uncommitted files fail the clone check. No native computation or site job
runs during export or verification.

The public replay module supplies the rule set through `replay.template_text()`, the
same interface as `ravel replay template`. If that integration is absent, the generated
rerun target asks the public CLI for its template at execution time and refuses when
the interface is missing. Environment installation and actual replay remain separate
host checks; fixture tests do not establish either.

## Adopting an external Snakefile

`ravel wms adopt` runs a Snakemake workflow that RAVEL did not write, for example one
that a venue or collaborator supplies. Parsing a Snakefile executes its Python, so
RAVEL first parses it inside the approved supervised inspection. The route has two
ordinary studies of the `external-workflow` science mode, each with its own CHECK-IN 1,
method decision, approval, supervised stage and receipts.

```bash
ravel wms adopt --snakefile external/Snakefile --workdir external/work \
    --rundir adoptions/first --study study.json --target results/summary.txt --cores 2
ravel approve --rundir adoptions/first/inspect        # approves the parse
ravel run --rundir adoptions/first/inspect
ravel wms adopt-run --adoption adoptions/first        # plans the run from the inspection
ravel approve --rundir adoptions/first/run            # approves the roster and commands
ravel run --rundir adoptions/first/run
ravel wms adopt-status --adoption adoptions/first
```

`study.json` supplies `source`, `assumptions`, `max_seconds`, `approval_mode` and
`review_policy` for both studies, in the form every science specification uses.

**Adopt.** RAVEL reads the Snakefile as text and pins it with every file it includes:
`include:` files, `workflow.include()` calls, the `snakefile:` of a `module`, and literal
`configfile:`, `script:`, `notebook:` and `conda:` files. A file that is both named by a
directive and included is pinned once and scanned for its own includes. `--member` names
a workflow file that the Snakefile's Python loads through an include it computes, for
example through an alias of `workflow.include`. A member is pinned and scanned like an
included file: its rules, the files it includes and the files it names join the record.
`--pin` adds any other file, such as a Python module the Snakefile imports or a program
its commands call. A file that is only pinned is never loaded as an include.
The result is `adoption.json` in the new adoption folder, with each file's role, path,
digest and the line that names it; every include as written, with the file it resolved
to; the members; every rule with its source text, file and line; the interpreter of the
Snakemake console entry; and the planned inspection study in `inspect/`. Snakemake is
not started.

Included files, members and named files lie in the Snakefile's folder or the working
directory. `--root` names another allowed folder; repeat it for several. A declared
`--output` resolves inside the working directory with every link on its path followed.

The record binds the Python interpreter that runs the Snakemake console entry. It is the
interpreter that the entry's first line names, by absolute path or through `env`, which
adoption resolves on the search path once. For the shim of an installed site prefix it is
the interpreter of the manager entry that the prefix's own validated record names.
`--interpreter` names the interpreter directly. An entry whose interpreter cannot be
resolved is refused at adoption.

Adoption refuses a workflow whose code it cannot pin: an `include:`, `workflow.include()`
or module `snakefile:` that is not a plain string, a remote include, a `meta_wrapper:`, a
file that cannot be read as Snakefile text, and an included file, a member or a named
file outside the allowed folders. `script:` paths with wildcards, `wrapper:`
directives and other references that name no fixed local file are listed in
`unpinned_references`. Targets and outputs are plain names; a name that starts with a
dash is refused, so no Snakemake option enters through them.

**Inspect.** The inspection study's CHECK-IN 1 shows the pinned files, every rule with its
source text, file and line, and the four exact Snakemake calls. Each call carries the
pinned Snakefile, the working directory, the executable, the cores and the targets of the
adoption record, so all four are fixed when the adoption is approved. After approval, the
science worker runs them under the stage supervisor and the machine lease: `--dry-run
--list-rules`; `--dry-run --dag dot`; `--dry-run --summary`; and `--dry-run
--printshellcmds`. No job runs. The adapter refuses to start Snakemake in any process
other than the approved supervised science worker of the study, before it writes a file. The Snakefile's own top-level
Python runs in the working directory, where Snakemake also writes its `.snakemake/`
bookkeeping folder. The worker writes
`inspection.json` with every rule, every job for the targets with its inputs, outputs
and shell command, the summary rows, the DAG and each call's output. A job with no
shell command runs a Python `run:` block, a script or nothing; its rule's declared
actions say which. Shell commands are kept exactly as Snakemake prints them, indentation
and blank lines included. The Snakefile writes to the same stream as `--list-rules`, so a
listed name counts as a rule only when an adopted file declares it; any other listed name
is shown under `listed_without_declaration`. The inspection fails when a call fails, when
a pinned file changed during it, or when the job count Snakemake states differs from the
jobs read.

**Run.** `ravel wms adopt-run` plans the run study from the inspection that the
successful supervised attempt of the inspection study wrote; any other inspection file
is refused. Its CHECK-IN 1 carries the roster: every rule with its source text, the jobs
and every shell command, with the exact launch command. After approval the worker first
repeats the `--dry-run --printshellcmds` call. A job whose rule and command the approved
roster does not show, for example one that a removed intermediate file brings back,
refuses the launch; adopt the workflow again to inspect and approve it. Then the worker
starts `snakemake --snakefile <pinned> --directory <workdir> --cores N <targets>` once,
as one supervised stage. It copies the workflow's outputs into
`outputs/attempt-1/external-workflow/delivered/` and pins source and copy in
`receipt.json`, which also lists the Snakefile pins, the command, the Snakemake
version, the exit code and the start and end times. Outputs named with `--output` are
required; without `--output` the outputs are the files the workflow's own summary
lists, and one that is absent after the run is recorded. An empty output file is bound
by its digest and has no copy.

**Changed files.** Every pinned file is an input of both studies. A pinned file that
changed after adoption refuses planning, approval checks and launch, and the message
names the file. The same check scans the closure again: an include that now resolves to
another file, for example through a retargeted link, a newly named file, a moved working
directory and a declared output that a link now leads outside the working directory are
refused by name. The worker reads the Snakemake version first and runs this check as the
last step before each Snakemake call starts, and checks the pins again when the
inspection or execution ends.
Every output the run will write is checked against the working directory before launch:
the outputs named with `--output`, the files of the workflow's summary and the outputs of
the jobs that the dry run before launch shows. `--output` selects what is delivered; it
does not narrow this check. An output outside the working directory refuses the launch
before Snakemake starts.
To run a changed workflow, adopt it again so that the new files are inspected and
approved.

**Profiles.** Every call passes `--profile none --workflow-profile none` and removes
`SNAKEMAKE_PROFILE` from the environment. A profile is a source of command-line options
that no pin covers.

**Limits.** The workflow is third-party code: RAVEL pins, inspects and supervises it and
records delivery. Its rules, scripts and results carry no RAVEL validation, and the
receipt infers no scientific acceptance. Snakemake reads the pinned files in place.
Programs that the shell commands call are pinned only when named with `--pin`. The
static include checks read the files as text; the before-load check below covers
includes that the Snakefile's Python computes while it runs. A
member of an output folder that is a link leading out of that folder is listed as outside
the working directory and is neither read nor copied.

**Include loading.** Inspection and execution start through
`wms_launch.launch_adopted`, inside the approved supervised science worker, with
method admission and workflow-policy custody checked again at each call. The
selected manager's Python interpreter runs `wms_include.py`, which wraps
`Snakemake Workflow.include` before the console entry parses any member. The
manager's own source resolver resolves each include against its including file.
Before the original include method runs, the canonical path must lie inside the
allowed folders, its sha256 must match the adoption record, and the file must be
workflow source that the adoption scanned: the Snakefile, an include or a member.
This also checks includes that Python computes at runtime: such an include loads
only when its file was named with `--member` at adoption, so its rules are in the
first CHECK-IN. A file named with `--pin` alone is refused as an include. Every
call retains a read-only adoption snapshot whose digest the interpreter checks.

Snakemake starts further interpreters of its own, for example one for each
Python `run:` job, and each of them parses the workflow again. Every call writes
a copy of the include check into a folder of its own, `<call>.include-hook/`,
and that folder is the import path of the processes below the call. Each Python
interpreter started there runs the copy first, so an interpreter that loads
Snakemake checks its includes against the same snapshot and digest. A member
that a job wrote during the run is refused there before it is parsed, and an
interpreter whose snapshot is absent or changed parses nothing. A site
customization of the manager's own environment still runs.

The calls start the interpreter bound at adoption, and the Snakemake version is
read through it. Python startup, user-site and path overrides are cleared for
that interpreter, and the folder of RAVEL's own modules is taken off its import
path. This loading check is workflow discipline; third-party Python still runs
under the enclosing approved stage.

**Combining with RAVEL rules.** Within a workflow-manager project, add each approved
adoption study using `ravel wms add --project PROJECT --rundir STUDY`, then launch
its indexed task using `ravel wms launch --project PROJECT --task TASK`. This
applies separately to the inspection and execution studies. The emitted rule
dispatches the ordinary supervised worker through the existing run-step route.
The index binds the emitted `workflow.json` manifest and `adoption.json` by
sha256. For the task and every task it depends on, the shared launcher verifies
both before parsing and again immediately before dispatch; a change to either
refuses the launch. An adoption that the launch cannot run is not read, so a
workflow edited after its own study does not refuse the other tasks of the
project. The single launch receipt retains both pins under `workflow_bindings`,
including adopted dependency tasks. The adapter's own before-load wrapper remains
active inside that launch.
Adding a task or starting the manager grants no study approval.

The real include-boundary control is gated by `RAVEL_TEST_SNAKEMAKE`. Qualification
requires running it in the installed Linux workflow-manager environment; synthetic
module controls alone do not establish compatibility with that installation.
