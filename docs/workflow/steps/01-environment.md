# Step 1 — Environment · [agent]

## On the controller

When RAVEL's controller runs an analysis request (`ravel drive`), this step is plan step `env` of the
analysis route (`src/ravel/data/controller/routes/analysis.json`). It runs in the prepare phase, before CHECK-IN 1,
at no compute rung, as a worker step (role `coordinator`) through the governed step graph:

- **Delivers** this document and the environment reference to the worker, with a receipt the worker acknowledges.
- **Writes** `outputs/environment.json`: `tools` (each `{name, status: available | missing | unknown, required,
  required_by}`, from the controller's inventory probe, never from memory) and `operations` (every operation the
  plan names).
- **Checks** (route adapter `environment`): every declared operation is accounted for; a required tool reported
  missing fails the step with the repair it needs. The run must not reach CHECK-IN 1 until the step holds.

A readiness record authorizes nothing: compute still needs the CHECK-IN 1 authority.

Before any plan exists, the controller observes the host once and keeps one `environment-profile` record in
the run's store: CPUs, memory, GPUs and free disk at the run and store roots, network egress, the batch system,
the sandbox and container backends, and every census tool's readiness, version, licence and platform
qualification from the doctor's own checks. A saved site profile (`ravel site init`) supplies what a probe
needs you to specify (the site's network policy, a local source mirror, credential requirements, the scheduler) and is
pinned by its digest. A resumed run keeps the profile it was admitted with.

Planning reads that profile. The tool census declares the capability needs a plan can have and, for each, its
candidate tools in preference order with the operations or roles through which a step uses them (for example,
routine construction: the agentic Rivet construction roles first, a hand-written analysis second; global and
effective-field-theory fits: SFitter first; symbolic model building: the FeynRules packages first, then a supplied
UFO model, then a pregenerated spectrum generator, then a SymPy derivation run as authored code). A need arises
from the request's task label or wording, a requested tool, a step that declares it, or a step that uses a
candidate implying it. The judgment planner sees
every need with its candidates' state on this host; every need that arises must be served by its best available
candidate, or the plan records a typed reason (`not_applicable` with a statement and evidence: a reading item or a
decide or ask step). The controller records the check as a `tool-selection` record and obligation CT09 at every plan
revision. A fixed route that leaves a need unserved hands it to the judgment graph as an open obligation.
At each step's preflight a tool the plan bound and found available is checked again; one lost since approval
holds the step (`tool_unavailable`) with the need's other candidates, before any effect.

When the profile records no network egress (a probe found none, or the site profile declares the network
offline), the route's publication acquisitions read local sources only: the resource census consults its local
rungs and the site mirror, and the data step reads the mirror's copy of the record; the step's
`parameters.source_mode` records the switch.

On a run the controller does not own, the host follows the procedure below as before; such a run's
results read NOT GOVERNED, and the controller refuses its legacy commands for a controller-owned run.

## Choosing provider models

Before creating a run, the operator can use `ravel setup-models` to discover providers
and choose a spending preset. `--yes` selects balanced defaults; `--preset premium`
or `--preset economy` selects another level without questions. `--cost-cap-usd` sets
an optional per-run ceiling. Discovery reads model listings and login status only;
`--verify` explicitly opts into governed transport conformance after a displayed cost scenario
and confirmation. It permits up to eight turns per selected model; the scenario is not a
spending bound. `--verification-cost-cap-usd` supplies the finite per-qualification API ceiling.
Subscription routes use the operator's login and have no monetary ceiling.
An agent session receives the operator command instead of changing operator authority.
Use `ravel models detect --adopt` to propose newly listed identifiers,
`ravel models preset balanced --write` to save a selection, `ravel models check`
to check current selections (`--run RUN_ID` reads frozen selections), and
`ravel models estimate --preset balanced` to inspect typical full-tier route costs.
Unknown prices remain unknown, and cache-unsplit inputs make these list-price
estimates upper bounds for the projected workload. See the
[transport reference](../../reference/transports.md#choosing-models) for overlays.

Setup and `ravel doctor` derive their worker claims from the controller's wired transports.
A listed model remains an unverified candidate until the operator qualifies that model and
installed transport version through `ravel transport qualify`; a controller run needs that
evidence in its protected store. HTTP and local loop workers use the same worker spec, broker,
instruction custody and receipt path as CLI workers. An explicit zero broker-call card keeps
only its final-record channel. Model or effort requirements exceeding a provider's declared contract hold
the role with a remedy; choosing a cheaper preset never removes a required capability.

## Procedure

Run commands from the repository root in Bash. A passing readiness check does not
authorize generation or any other compute; that still needs the CHECK-IN 1 approval.

The installer provides one released toolchain. Omit `--profile` for this platform;
use `--profile site` only for a Linux analysis facility. Every reported requirement
must pass. A missing or misconfigured tool makes `ravel doctor` exit with status 1
and prints its exact repair command; licence activation remains a user action.

Groups marked `qualification.required_per_platform` in `native/setup` enter the
implicit installer and doctor selection only when a successful qualification record
matches this host platform. The `mcfm-amplitudes` group  has evidence for
`linux-x86_64`. Operation availability
and planning refuse `amplitude-integration` on platforms without matching evidence,
naming the missing group and platform. Explicit `--only mcfm-amplitudes` remains the
route for approved installation and qualification work; installation alone does not
remove this admission hold.

For a site installation, use `bash scripts/setup/install.sh --profile site --prefix
<work-prefix> --lcg-view <absolute-view-path-or-none>`. Put the checkout, runs and
transcripts in work space. Run `ravel site doctor --profile generic --prefix
<work-prefix> --runs-dir <work-runs> --transcripts-dir <work-transcripts>` before a
campaign. Use `<work-prefix>/bin/ravel-snakemake` to isolate the hash-locked workflow
manager from facility Python settings. One prefix holds one release per campaign;
start a new prefix for the next release after that campaign ends. The
`tester-qualification` site groups require the facility user's
[synthetic site qualification](../../reference/site-workflows.md#synthetic-site-qualification).

The complete Python installer retains test tools, build tooling and all solver
dependencies. For a package-only installation, solver imports require the
`cosmology` extra (`python -m pip install 'ravel-hep[cosmology]'`); the error names
this extra if a selected runtime is missing an import. Installing an extra does
not replace source/runtime admission, approval or numerical qualification.

## Check the tools this study needs

```bash
.venv/bin/ravel doctor --mode <science mode>      # or --profile site on a facility, or --group madgraph
```

The doctor lists every tool the mode needs, with its status and the exact command that
fixes each problem. It changes nothing. Report its findings in CHECK-IN 1:

- `ready` and `remote_route` (Linux-site tools seen from a Mac) need no action.
- `missing` or `version_mismatch`: the fix is `bash scripts/setup/install.sh --only <group>`.
  Installing downloads and builds software, so ask the user before running it, and give
  the size and time from `bash scripts/setup/install.sh --plan --only <group>`.
- `manual_required` and `unconfigured` (Wolfram licence, TeX, Rosetta, API key, grid
  credentials) are actions for the user. Never activate licences or handle credentials.

Do not substitute a different tool, version or analysis to work around a missing one. On the
controller, an alternative is only one of the need's declared candidates, chosen because the preferred one is
missing on this host or with a recorded typed reason; anything else is a plan change.
Record the doctor report (`--json`) with the study's runtime record. Installation
readiness grants no numerical qualification. Compare a supplied operation/version/
condition receipt using `ravel.setup.qualification.compare_receipt`; the input and
evidence schema is in `docs/installation.md`.

## Native details

`source native/scripts/paths.sh` sets `RAVEL_NATIVE_BUILD` and `RAVEL_NATIVE_BIN` for a
shell, using the same prefix as the installer (an explicit `RAVEL_NATIVE_BUILD`, then
`.ravel/native-prefix`, then `native/build`). The compressed-slepton route also needs the
RJR resolver; on macOS check it with

```bash
python -B scripts/run.py ravel.validation.native_doctor --json --require-rjr
```

which also distinguishes Intel, Apple-silicon and Rosetta processes. The installer
records versions, commits and digests in `<prefix>/receipts/`; the
[installation guide](../../installation.md) lists what each profile contains.

For execution, follow the [native pipeline reference](../reference/native-pipeline.md)
and the approved task's cards, detector adapter, routine and statistical mapping.

## Paper-PDF tooling

The figure extractor's PDF-page route needs Poppler's `pdftoppm` (installed by the
`publication` group); the arXiv-source route can avoid that renderer.

**Next:** [Step 2 — Inputs](02-inputs.md).

## Census status and prospective engine ranking

The [tool-status table](../../reference/tool-status.md) is generated from the
packaged tool and analysis census. Use `ravel doctor --census --json` to report
every tool's readiness and its separate historical qualification scope. A tool
without a provider contract reports that gap; an excluded tool is never probed.
Required means required for the selected operation/profile. Source presence,
installation readiness and scientific qualification are separate facts.

`ravel.workflow.backend_portfolio.assess(request_path)` ranks the six prospective
recasting engines from that census and lists configured studies, reasons and
shared routine/output overlaps. Record this assessment in CHECK-IN 1. Choose
explicit source-applicable studies; retain each engine's assumptions and outputs.
Cross-engine combination stays `null`; ranks grant no execution approval.

Source-only discovery is available through `ravel analyses list`, `ravel modes list`
and `ravel research-tools --help`; source acquisition remains a separate operation.
Use `ravel status --rundir <run> --write` for the science run's next
blocker. Lifecycle invariant checking is documented in
`ravel.validation.validate_run_state`; it is separate from a science packet.

For source-only planning,
`ravel.workflow.recast_route.rank_routes(signal_basis=..., routine_ids=..., family=...)`
returns the released ranks and a census hash; `load_census()["tools"]` gives each tool's
historical label and evidence scope.
The portfolio prepares its configured adapter routes. Literature services are
`research_tools.discover_literature` and `research_tools.acquire_literature`;
they require the ordinary source and execution contracts.

Regenerate the table with `python -m ravel.workflow.tool_census`; check for drift
with `python -m ravel.workflow.tool_census --check`. The source unit suite runs
the same drift check.

The route ranking retains every census backend. Missing tools carry `label: not_ready`
and `fix`; a qualified historical row has `readiness_unknown` until a doctor observation
is supplied through `observations`. From `doctor.census_report()`, pass only rows whose
tool IDs belong to the backend census; the reference-data row is separate. Readiness does not
change the declared source applicability or grant execution approval. A `census_path`
can bind an alternate pinned census for a planning record. The portfolio uses this
ranking through its existing API; overlapping results still require explicit review.

`ravel doctor --census --json` reports Higgs reference-data acquisition locators,
expected files, required owner action and download-size uncertainty. Obtain owner
approval before downloading the source tables. Do not download from this registration automatically or substitute the test
fixtures. Measure the actual download size during approved acquisition.

After approved acquisition and source review, register ordinary local primary files and
one normalized table file with SHA-256 pins in the reference `SOURCE.json`.
`ravel.validation.constants_manifest.load_higgs_tables(directory)` verifies both sets
of bytes, citation resolution and the table schema. Each row records its process,
mass, unit, reference value, citation key and absolute asymmetric uncertainty envelope;
cross-section rows also record energy, perturbative order and PDF. No interpolation or
unit conversion is implemented. Preserve the source uncertainty definition rather than
inventing an envelope. `python -m ravel.validation.constants_manifest tables.json`
checks citations, declared envelopes and table-row ratios; any finding exits nonzero.
`recompute_higgs_ratios(document)` returns the verified quotients. CHECK-IN 1 must retain
the primary/table pins and any unresolved applicability or uncertainty interpretation.
See the [reference loader contract](../../reference/knowledge.md) for the acquisition hold.

### Additional source and licence records

When package requirements or native manifest groups change, regenerate the
[component inventory](../../reference/component-inventory.md) in the full-profile
host environment with `python scripts/maintenance/render_component_inventory.py`.
Use `--check` to refuse stale metadata, then run
`python scripts/maintenance/sync_instruction_bundle.py` to refresh packaged documents.

Before installing an additional tool, resolve its filled entry in
`native/setup/tools-pins.json` and apply the offline licence/Containerfile lint.
Pending entries require source acquisition and licence evidence before installation.
The [scope-tools ledger](../../reference/tool-licences.md#scope-tools-add-ons) gives
the pin resolver, fragment interface and comparator source-extraction checks.

## Project workflow-manager guidance

For a project declaring workflow-manager-first policy, install portable agent
guidance with `ravel agent-surface install --project PROJECT`. Load
`.ravel/agent-guidance.md` into the host session. Existing project instruction
documents stay byte-identical. The shell discipline guard is enabled by default
for policy-required projects; `--wms-guard` installs it explicitly elsewhere.
For an HTCondor analysis facility, initialize with `ravel wms init --profile htcondor
--jobs N --remote-ceiling C --shared-state-root /shared` and launch through
`ravel wms launch --jobs N`. The installed site shim, exported profile digest,
shared state declaration and zero-retry bound remain pinned to the launch.
See [governed site launch](../../reference/site-workflows.md#workflow-manager-first-projects).
Machine runtime settings stay local and untracked. Plan and approve retain their
check-ins; approved stages use `ravel wms launch` when required by policy.
See [the approved-stage guide](../../guides/approved-workflow-stages.md) for the
recorded guard opt-out, separate environment skill, retries and qualification
boundaries. Do not treat generated guidance or a dry-run as native qualification.

Toolchain declarations are read through `ravel.setup.manifest.load(root)`, which merges
inline groups with `native/setup/groups/*.json` before validation. When inspecting a
staged tree without its PDF catalogue, use `ravel.setup.manifest.view(root)`; compare
its content with `python -m ravel.setup.manifest view --canonical-sha256 --root <tree>`.
The [group fragment contract](../../../native/setup/groups/README.md) describes the
contributor schema and digest-preserving split helper.

Each non-qualified census entry has an install group, a qualification-job specification,
a site deferral, or a data-format record in `src/ravel/data/knowledge/qualification/rows.json`.
The declaration is planning evidence only: use the existing admission and launch guard before
any source acquisition, installation, or qualification execution.
