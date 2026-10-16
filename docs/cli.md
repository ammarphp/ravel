# Ravel package, intake, and locked environment

The distribution name is `ravel-hep`; the import and command are `ravel`. Use Python 3.12 for the complete host and required isolated SModelS/SFitter setup. The host supports Python 3.11–3.12.

`bash scripts/setup/install.sh` installs everything, including this Python setup and the native tools, and `ravel doctor` checks it ([installation guide](installation.md)). For the Python package alone, prepare Python 3.12 and the [compiler prerequisites](installation.md#before-you-start), then run from the checkout:

```sh
python3.12 scripts/setup/python_installation.py
source .venv/bin/activate
ravel --help
```

The installer prepares `.venv`, `.venv-smodels` and `.venv-sfitter` using the complete requirements. An existing activated host can install the host environment with `python -m pip install -r requirements-full.txt` from the repository root; that file also installs RAVEL itself. Follow the [ordered installation guide](installation.md) for required native engines, source packages, model access and the research Host. The installed `ravel` command and `python -m ravel` use the active environment from any working directory.

The hash-locked Python environment in `requirements-replay.lock` pins the statistics layer
(pyhf, NumPy, SciPy) for Python 3.12 and is the environment CI uses for its test suite.
It does not establish broad generality or publication readiness.

The wheel includes engine code, declared workflow instructions and required setup assets.
`hatch_build.py` verifies the source instructions and their packaged copies before export.
Validation corpora and scientific reference inputs are selected externally by each request;
the package supplies no replay corpus or historical result population.

The complete setup installs the required Python methodology libraries in the host and isolated engine environments:

```bash
python3.12 scripts/setup/python_installation.py
source .venv/bin/activate
```

The [ordered installation guide](installation.md) supplies native engine, source and model-access procedures. Required Python libraries provide numerical calculations, measurements, published-classifier execution, source parsing, figures and software checks. MadGraph/Pythia, Rivet/YODA, ROOT/Combine, SimpleAnalysis, MadAnalysis/PAD, Contur, generated spectrum/decay tools, SFitter, pySecDec, cosmology solvers and the Wilson/flavio/smelli chain retain their separately bound runtimes. Ordinary adapters verify the selected executable/interpreter, complete source assets, versions, build and result contracts. The wheel contains selected upstream API/reference assets; external compiled engines remain separate. Installation prepares dependencies; each computation still follows its approved study.

Installed source catalogues inspect the imported `ravel` package. An explicit
`--source-root` still names a checkout containing `src/ravel`; it never falls back to
another installation if that selected checkout is missing or changed.

## Discover public analysis routines

These commands read a routine catalogue: the file `RAVEL_ANALYSIS_CATALOG` names, the one
`ravel catalogue --rivet <checkout> --simpleanalysis <checkout>` builds in your cache from your
own checkouts, the one the installer built, or else the snapshot the package ships (pinned Rivet and
SimpleAnalysis revisions, with the public probability-model index associations). A catalogue named
by `RAVEL_ANALYSIS_CATALOG` that is absent is refused. They inspect metadata and adaptation
requirements:

```sh
ravel analyses summary
ravel analyses list --experiment CMS --query "Drell"
ravel analyses list --framework simpleanalysis --family long-lived --json
ravel analyses show rivet:SYN_9015_I1254
ravel analyses check-source <routine-name> --source /path/to/simple-analysis
ravel analyses assess --specification analysis.json --out admission.json
```

`show` also accepts an unambiguous exact paper/INSPIRE identifier. Multiple matching
routines require an explicit choice. `check-source` requires Git and an existing
pinned upstream checkout; it checks selected source/asset bytes without executing
upstream code. PASS means source agreement only.
`assess` reads a source-bound evidence specification and reports missing or failed
build, event, response, reference and inference prerequisites without executing
them. Exit 0 means its scoped census is complete; exit 2 means it remains blocked.
Neither result grants execution or physics authority. See the
[analysis-admission contract](reference/analysis-admission.md).

An external, source-pinned coverage landscape can supply more detailed routine
obligations and primary-resource joins on top of the local catalogue:

```sh
ravel analyses adapt rivet:SYN_9016_I1227 \
  --landscape /path/to/landscape-manifest.json \
  --manifest-sha256 EXTERNALLY_RETAINED_SHA256 \
  --objective measurement --out adaptation.json
```

The manifest and its constituent files must match their recorded identities.
Resolution uses exact identifiers; resource discovery does not establish a usable
likelihood or validated analysis. Add both `--source-root /path/to/upstream` and
`--capsule source-capsule.json` to write a normal source-capsule review seed after
checking source bytes. Unresolved dependencies stay unresolved and prevent a
build until reviewed. Output files must be new. This command performs no build,
simulation or inference and grants no execution authority.

## Start a draft intake

```sh
ravel initiate \
  --prompt "Reproduce the exclusion figure of a published slepton search for a slepton-bino model." \
  --out /tmp/ravel-slepton-intake
ravel validate /tmp/ravel-slepton-intake/inputs/task_contract.json --json
```

Use exactly one of `--prompt` or `--prompt-file`. File input must be UTF-8. `--out` is
required and must name a new directory. For a longer request:

```sh
ravel initiate --prompt-file request.txt --out /tmp/ravel-intake-from-file
```

Intake writes the original `request.txt`, a validated draft `inputs/task_contract.json`, an
initial `run_state.json` ledger, and a derived `current_state.json` view. A method-study request
also writes `method_proposal.md` and uses a survey contract with compute=`none`:

```sh
ravel initiate --prompt "Develop a collider-search method and compare candidate baselines." \
  --out /tmp/ravel-method-study
```

This preserves the research objective without pretending that a training executor, dataset,
protected evaluation, or calibration study exists. Those decisions remain explicit in the proposal.

The default local parser handles actions, quoted context and negated requests; it is bounded,
not a general scientific reasoner. A host agent can supply a grounded interpretation for unfamiliar
wording:

```sh
ravel initiate --prompt-file request.txt --interpretation intent.json --out /tmp/ravel-host-intake
```

The interpretation object requires `schema_version: 1`, `prompt_sha256`, `kind`, `objective`,
`requested_outputs`, `evidence`, and `unresolved`. The hash is SHA-256 of the exact UTF-8 request;
each evidence item is `{start, end, text}` with zero-based, end-exclusive Python character offsets
and exact matching text. `kind` is a supported task mode or `method_study`; output and unresolved
items are strings. Invalid hashes/spans, duplicate spans, unknown fields and introduced analysis
identifiers fail validation. Grounding records the interpretation's source, not its scientific
correctness or execution approval. Review the resulting draft before advancing.

Intake makes no model call, network request or simulation. Missing inputs, `TBD-judgment`, default
cost assumptions and proposed compute remain visible. `compute_authorized=false` is explicit;
no skills, approvals or compute are recorded as complete. The `routed` ledger field remains false
until the workflow completes routing. Continue through the [analysis workflow](workflow/start.md)
to resolve inputs, review figures and budget, and present CHECK-IN 1. An installed wheel can draft
intake elsewhere; the full workflow additionally needs its documents, tools and native environment.

Exit 0 means intake files were written, not approved. Exit 1 means the request is held as
`unsupported` or invalid; exit 2 means an input, command or write error. A held request still
writes its directory: `request.txt`, the draft contract, `inputs/capability_recovery.json` and
`current_state.json`. Read the recovery packet, then follow the route table in
[start.md](workflow/start.md#which-route-a-request-takes); resolve the held run in place with
`ravel initiate --resolve <held-run> --interpretation intent.json`. A blank request writes nothing.
Existing destinations, including symlinks, are refused. Partial outputs from write failures are
retained; use a new destination for a new intake, never to resume an existing run.

Without installation, use the same entry point from the source tree:

```sh
python3.12 /path/to/ravel/scripts/run.py ravel.__main__ initiate \
  --prompt-file /path/to/request.txt --out /tmp/ravel-source-intake
```

## Resume and inspect current state

For generation-only or supplied-likelihood calculations, the supported sequence is
`initiate` → `plan --spec` → `approve` → `run` → `status`. Use
`compare-recipes --left --right` before treating two controls as the same physics calculation.
See the [scoped workflow guide](workflow/reference/scoped-workflows.md) for exact specifications,
scripted experimental approval, output artifacts, one-attempt budgets and capability gaps.
The commands work from an installed wheel; generation needs a supplied native MadGraph runtime.

```sh
ravel status --rundir /path/to/existing-run
ravel status --rundir /path/to/existing-run --write
```

Both commands rebuild the packet from the live contract, ledger, lifecycle gates, execution
receipts and approval. `--write` also refreshes `current_state.json`; it does not change the source
contract, ledger or scientific artifacts. Inspect `next_required`, `blockers`, approval errors and
stage receipts, then open only the relevant workflow step. Refresh after a restart or compaction.

For an initial immutable schema2 study executed under a retained source epoch, explicitly
select the current review reader with `ravel status --rundir /path/to/retained-run
--retained-study` (optionally `--write`). This validates the original full source/input
population, approval, runtime capsule, successful receipt, outputs/log, current journal
and supporting role-context bytes without importing the historical package or regenerating
its input inventory. Accepted, held, rejected, stopped and invalid evidence remain distinct;
`physics_validated` stays false. The packet records the original execution identity separately
from the current reader. It supports neither correction/checkpoint histories nor missing
original runtime capsules. `--write` requires a valid original-evidence observation and
refuses to overwrite a status file that is itself committed evidence.

The review-only projection is also available through `physics_review.status(root,
retained_study=True)` and its `status --retained-study` subcommand.

Exact accepted products can be checked with `python -m ravel.workflow.physics_review
--rundir /path/to/retained-run gate --action reuse --retained-study` (or `delivery`).
The explicit API `physics_review.snapshot(root, action='reuse', retained_study=True)`
returns the existing schema1 snapshot only after the same fresh immutable validation and
original policy's accepted scope/action check. Holds and changed evidence refuse. This
opt-in path cannot admit bulk work, corrections, hold lifts or new computation; consumers
still need their own new plans. Omitting the option preserves normal current-study gates
and admission. Pending-role submission remains limited to awaiting_review/send_back.

The packet is a view, not permission or a scientific certificate. Executors and serving gates
revalidate the original artifacts. Do not edit the packet to unblock work or rerun intake to resume.
Exit 0 means the packet was derived; lifecycle blockers or absent approval may still be present.
Exit 1 indicates invalid execution evidence; input/command errors exit 2.

`python -m ravel.validation.check_status_packet /path/to/existing-run` regenerates the packet from
the run's records alone and checks that its next work item matches `current_state.json` byte for
byte; refresh a stale packet with `--write` before resuming.

## Lifecycle governance on any host

`ravel approve`, `ravel go` and `ravel advance` dispatch by run kind. A scientific or scoped study
is approved over its concrete CHECK-IN 1 and executes through `ravel run`; a native run is approved
over `inputs/checkin1.json` and its cost preflight (`--plan`, default the contract's compute plan),
records its CHECK-IN 2 GO with `ravel go --quote`, and advances its lifecycle stage with
`ravel advance --to <stage>`. None of them launches compute.

```sh
ravel gate --rundir /path/to/run --action tool_call --command "<exact command>" --json
ravel gate --rundir /path/to/run --action delivery --json
ravel lifecycle check --rundir /path/to/run
ravel checkin validate /path/to/run/inputs/checkin1.json
ravel result-pack --rundir /path/to/run --stat-mode <mode> --detector-mode <mode>
```

`ravel gate` returns the gate verdict for a run and an action or an exact tool call: exit 0 allow,
2 deny, 1 usage error or no run. Hosts without hooks call it before acting; see
[host governance](workflow/hooks.md) for the hooks, the run registry, and what each host enforces.
Hook governance covers Claude Code only. `ravel result-pack` refuses generation output that has no
approved launch record and records the host's enforcement in `result.json`. A pack that delivers absolute SR yields needs
`--normalization-ledger <file in the run>`; the pack pins the ledger and the delivery checks recompute
the delivered yields from it. Without a ledger the pack is refused. `ravel stage`,
`ravel scan`, `ravel cost`, `ravel trap-sweep` and `ravel certify` run the corresponding stage
supervisor, scan orchestrator, cost preflight, trap sweep and acceptance certification.

## Validate and audit

```sh
ravel validate path/to/task_contract.json --json
ravel validate --schema
python -m ravel validate path/to/task_contract.json
```

Validation uses the existing validator's strict JSON reader and schema checks, including
duplicate-key and nonfinite-number rejection. Exit 0 means schema-valid, 1 means
invalid, and 2 means a command/input error. It never grants compute approval. The Python API is
`from ravel import validate_task_contract`; it accepts a decoded JSON value and returns the
same list of validation errors.

```sh
ravel audit --root /path/to/ravel
ravel audit --root /path/to/ravel --out /tmp/ravel-audit.md
```

The R1–R8 audit requires a source checkout because it examines workflow documents, available
run records, and the native tool inventory. If run within a checkout, `--root` can be omitted.
The audit is read-only unless an explicit, new `--out` is supplied. Its existing engine exits
0 when a report completes, even if dimensions warn or fail. It is a diagnostic report, not a
pass/fail gate. The public repository holds a curated subset of the original run records, so
its scores must not be compared as measurements of physics capability. The standalone wheel
reports an actionable source-checkout requirement rather than inventing an audit score.

The `replay` dependency profile declares bounded direct dependencies; `requirements-replay.lock`
freezes all transitive versions with distribution hashes for Python 3.12. NumPy is held below
2 because the existing project records a pyhf toy-based incompatibility. Full native HEP
reproducibility needs the separately documented compiler, generator, shower, detector, analysis,
and external-data setup. This Python lock does not change the native-default execution policy.

To update the lock deliberately, resolve and review the dependency diff, then run the
relevant numerical and package tests before accepting new versions:

```sh
uv pip compile pyproject.toml --extra replay --extra test --python-version 3.12 \
  --universal --generate-hashes --output-file requirements-replay.lock
uv build --out-dir /tmp/ravel-dist
```

Build outputs are wheels and source distributions. Build the wheel from the source
distribution as an additional release check. The build backend itself is pinned in
`pyproject.toml`; its isolated build dependencies are separate from the locked runtime.
For public release, build from the sanitized public export so machine paths are not copied
into the wheel. Run the package portability check with:

```sh
RAVEL_TEST_WHEEL=$(ls /tmp/ravel-dist/ravel_hep-*-py3-none-any.whl) \
  .venv-replay/bin/python -m pytest tests/unit/test_ravel_cli.py \
  tests/unit/test_cli_initiate.py -q
```

The G8 release gate checks that agent calls go through the graph substrate. A static census
lists every agent call site in `src/ravel` at function granularity, and each site that bypasses
the substrate must appear in a baseline. The baseline names the package that removes the
bypass, and entries can only be removed:

```sh
ravel release check --gate G8          # report mode: prints the gate record, exits 0
python -m ravel.validation.check_agent_paths census --write   # after editing a call site
```

`--mode block_new` fails on a bypass missing from the baseline. `--mode empty` fails until the
baseline is empty. A static census is not proof that no dynamic path escapes. With
`RAVEL_AGENT_TRIPWIRE=1`, the lowest layers refuse calls made outside a substrate node.
`report` records those calls without refusing them. Gates G1-G7 are not yet available
through this command.

## Supplied-data scientific studies

`plan --spec` also accepts every scientific-study mode listed in
[scientific studies](workflow/reference/scientific-studies.md), such as `analyze`,
`quantities`, `measurement`, `domain`, `eft-toolchain`, `cosmology-solver`, `feyn-graph`
and `manuscript-build`. The `analyze` task can
select the typed `analysis-ir` backend, source-bound `routine-build`, or evaluate
an exactly verified plugin with `rivet-built`;
the `domain` task can select the bounded fixed-phase-space `model-probe`.
These use the explicit [scientific-study specification](workflow/reference/scientific-studies.md),
not a reinterpreted generation or reproduction contract. `approve`, `run` and
`status --write` share the bounded lifecycle; `run --resume` verifies completed
outputs without relaunching computation. Requested inputs and code must still
match their approved hashes. A successful study requires CHECK-IN 2 review before
any follow-up and does not mark an analysis as physics-validated.

New scientific execution capabilities require the prospective version 2 review
envelope. The first successful worker remains `awaiting_review`; its computation
can finish before delivery or reuse is admitted. `science-correct --rundir RUN
--request correction.json` materializes and admits only a previously allowed
numeric repair under the recorded decider, without launching it. The request has
`actor_id`, `changed_paths`, `recheck_checks` and optional `max_seconds`.
Run the exact admitted correction with `run`, then review its fresh evidence.
See the [review and correction contract](workflow/reference/science-review.md)
for policy fields, preserved input copies, spent attempts and scoped acceptance.

When a request supplies a numeric output template, fill it from an accepted result:

```sh
ravel fill-template --template template.yaml --result RUN/outputs/quantities.json \
  --rundir RUN --claim-scope reproduction --out filled.yaml
```

The command copies values only, keeps every bin edge and writes
`filled.yaml.provenance.json`. Optional flags select a table (`--table`), a dependent column
(`--column`), a weight stream (`--weight`), a declared rebinning (`--rebinning`) and an
uncertainty label (`--uncertainty-label`). See [result templates](workflow/reference/result-templates.md).

## Plan a calculation intake

A `calculation` draft carries `inputs/intake_handoff.json`. The intake planner turns it into a
two-node Graph: a designer chooses an ordinary study or a source-development continuation, and
a deterministic node checks that choice and prepares the plan.

```sh
ravel intake-plan prepare --parent RUN/inputs/task_contract.json --out planning \
  --modes literal-calculation measurement --evidence evidence.json --resources resources.json
ravel intake-plan graph-spec --request planning/request.json --graph-root graph \
  --out graph-spec --graph-id intake-plan --model MODEL --effort EFFORT
ravel intake-plan checkin1-response --delivery delivery.json --request response.json
```

`--modes` lists one to sixteen candidate scientific-study modes. `--resources` holds
`max_child_seconds`, `max_calls` (2), `max_output_tokens` and `max_wall_seconds`. `--adapter`
selects the configured model transport (default `responses`). Run the Graph with
`ravel agent-graph run`, or deliver the designer through `prepare-external` and
`deliver-external` below. `checkin1-response` records an actual CHECK-IN 1 reply that asks for
autonomous operation; its request holds `user_text`, `quote`, `delegate_actor`, `actions`,
`bounds`, `task_class` and `blinding_policy`. See
[calculations and research intake](reference/intake-and-challenges.md).

## Prepare event generation

```sh
ravel model-events prepare --request request.json --out fresh-preparation
ravel plan --rundir fresh-run --spec fresh-preparation/science.json
```

The request pins the generation `config`, the `review_policy`, a `supervisor_seconds` ceiling and
an optional `goal_binding` to a parent task. Preparation writes `science.json` for an ordinary
`model-events` study and generates no events. See [model events](reference/model-events.md).

Statistical inference on supplied numbers uses five study modes. `ravel inference` prepares them
without computing anything:

```sh
ravel inference modes
ravel inference example --mode prescribed-statistic > stat.json
ravel inference check --mode prescribed-statistic --input stat.json
ravel inference spec --mode prescribed-statistic --input stat.json --policy review.json \
  --source "..." --assumption "..." --out spec.json
```

See [inference engines](reference/inference-engines.md).

## Advisory research tools and independent checks

These commands preserve or inspect explicitly supplied evidence. They do not
authorize scientific execution, alter an approved study, or provide a reviewer
vote. Use `--help` on each command for its full native parser.

```bash
# Freeze a board charter and its declared source bytes, then commit before reveal.
ravel hypothesis-board create --board board --charter charter.json --artifacts sources.json
ravel hypothesis-board digest --board board --submission producer.json
ravel hypothesis-board commit --board board --actor ACTOR --digest SUBMISSION_SHA256
ravel hypothesis-board reveal --board board --submission producer.json
ravel hypothesis-board snapshot --board board --expected-charter-sha256 RETAINED_CHARTER_SHA256

# Finite categorical policy recommendation, with an exclusive optional report.
ravel experiment-allocator --case case.json --out allocation.json

# Inspect shared evidence lineage; lack of shared rows does not prove independence.
ravel evidence-independence --artifact baseline=baseline.json --artifact candidate=candidate.json

# Derive an explicitly unverified numerical claim, or verify an existing producer claim.
ravel numerical-witness derive --input rows.json --out claim.json
ravel numerical-witness verify --input rows.json --claim producer-claim.json \
  --original-source original-census.json \
  --checker-sha256 RETAINED_CHECKER_SHA256 --input-sha256 RETAINED_INPUT_SHA256 \
  --claim-sha256 RETAINED_CLAIM_SHA256 --original-source-sha256 RETAINED_SOURCE_SHA256

# Detached stdlib replay of a typed-analysis bundle.
ravel analysis-witness --bundle retained/analysis-witness \
  --manifest-sha256 RETAINED_MANIFEST_SHA256

# Retain a research graph and run it through an explicitly configured agent host.
ravel agent-graph create --graph graph --spec graph.json
ravel agent-graph run --graph graph --host-config host.json --workers 1
ravel agent-graph status --graph graph

# Hand one model node to an external host, then return its response.
ravel agent-graph prepare-external --graph graph --node NODE
ravel agent-graph deliver-external --graph graph --node NODE --response response.json

# Control a graph.
ravel agent-graph cancel --graph graph --reason "..."
ravel agent-graph resume --graph graph
ravel agent-graph rework --graph graph --reason "..." --nodes NODE [NODE ...]
ravel agent-graph revise --graph graph --spec graph-v2.json --reason "..."
ravel agent-graph reconcile --graph graph --call CALL --outcome completed --evidence evidence.json \
  --result result.json --reason "..."
```

`prepare-external` reserves one attempt of a pending `external` model node and writes a sealed
request under `graph/requests/`; no model runs. The external host answers that request and
`deliver-external` imports the response, checks it against the prepared request and the node's
role contract, and records the call. Reviewer, critic and verifier roles attest fresh context.
`reconcile` settles a started call whose outcome is unknown as `completed`, `not_dispatched` or
`failed`.

Board commit/reveal ordering binds declared submissions locally; actor/session
metadata is not authenticated independence or an OS sandbox. The allocator's
categorical predictions and costs are supplied hypotheses. An unknown prediction
remains compatible with every declared observation; the recommendation is
`ADVISORY`, with `execution_authorized: false`. Actual tests still require their
own concrete scientific plan and approval.
The agent graph schedules declared dependencies and bounded node attempts through
its configured host. Graph completion and advisory proposals do not grant human
compute assent, CHECK-IN 2 GO or scientific acceptance; those remain actions in
the supervised workflow with their own evidence and actor contracts.

Numerical verification requires externally retained checker, input, claim and
original-source digests. Computing a claim and its reference through the same
producer is not independent checking. Verified arithmetic remains conditional
on the supplied population, weighting, coupling and uncertainty convention;
it is not physics calibration or source authentication. Explicit `--out` paths
are newly created artifacts and existing evidence is never overwritten.

The ordinary analyze routes also admit source-bound
[native categorical observables](reference/native-categorical.md). Declare their
literal axes and source/RAW object contracts in the task passed to `ravel plan --spec SPEC --rundir RUN`; use the existing approval/run/status lifecycle. Their portable table
retains masks and undefined values. This interface does not assert observed
native weight selection or scientific qualification.

`ravel plan --spec SPEC --rundir RUN` also accepts prospective version 2
[`pdf-variations`](workflow/reference/pdf-variations.md) studies. This first
operation reweights supplied LO parton records across all members of one pinned
NNPDF replica set with fixed supplied response. PDF ensemble and nominal finite-MC
covariances remain distinct. It does not provide NLO counterterms, scale or
alpha_s variations, authenticated generator extraction or physics acceptance.

## Analysis challenges and submissions

Running RAVEL inside another project, logging agent sessions, answering review requests with a
fresh agent session and packaging an accepted analysis for submission are described in
[challenge operations](reference/challenge-operations.md).

```bash
ravel agent-surface install --project ../my-analysis
ravel agent-audit build --log .ravel/agent-audit/prompts.jsonl --out audit
ravel agent-cli answer-graph --graph graph --prepare
ravel export-submission --request submission-request.json --into ../submission-repo
ravel export-submission verify --package ../submission-repo/submission --fresh-clone
ravel conformance check --repo ../my-analysis --rules rules.json --out ../conformance-report.json
```

The conformance rule pack is supplied by the requester; see the
[conformance checklist](workflow/checklists/conformance.md).

## Diagnose a retained failed stage

`ravel failed-review` provides read-only intake, diagnostic role contexts, feedback verification and source binding for a separately approved successor. It never accepts a failed result or grants reuse, correction, retry or launch permission. See the [failed-stage review reference](workflow/reference/failed-stage-review.md) for the exact request and commands.

`ravel model-derivation-bridge plan --help` and `ravel model-derivation-bridge handoff --help` delegate to the existing derivation parser. The direct `python -m ravel.physics.model_derivation_bridge` entry has the same plan/handoff authority and accepted-readiness requirements.

Retained status writes hold the existing review write lock across the original evidence observation and the intended status write. A late scientific hold is serialized with that write; a status file already committed as review or hold evidence is refused before overwriting it. The writer retains one validation session and checks its original journal/evidence epoch immediately before writing. This is cooperative journal serialization, not a filesystem-wide atomic snapshot or new scientific authority.


Retained initial scientific review opening
-----------------------------------------

`ravel judgment open --rundir RUN --checks CHECKS --retained-study` opens only
the first real review cycle for a successful immutable initial schema-2 study.
It checks the original source, interpreter/runtime environment, approval,
launch authorization, complete inputs, stage outputs and logs, without
importing the historical package or rebuilding the current adapter inventory.
The current reader is separate from the original executor. Existing reviews
are preserved; this option does not initialize or rerun science, waive failed
stages, accept a claim, or allow empty scientific check evidence.

Approved generated marker families expand only to their exact committed zero
members and retain the source-defined family proof. Fresh SFitter specs may
call `sfitter_native.source_output_policy(task, base)` before planning to bind
the exact eight empty copies from released upstream commit 6072a79e. The source
must be captured as a singleton approved stage input; the copied output path
and source hash are explicit. Failed historical SFitter attempts remain failed.


Installed workflow instructions
------------------------------

A refreshed ordinary intake/status packet keeps its original `instructions`
IDs and adds `instruction_resources` with readable absolute paths and byte
commitments. The wheel includes a finite operational set: entry/check-in
guides, numbered blocker steps, scientific/scoped/review guides and prepared
runtime replay. Resolve a step through
`ravel.paths.workflow_instruction_path("docs/workflow/steps/02-inputs.md")`.
A source checkout's existing documents are preferred; an explicit `source_root`
requires that root's document and does not fall back to installed bytes.
Research, skill and historical-evidence links outside this set require their
original checkout. Instructions grant no approval or scientific acceptance.
`ravel audit` continues to require a source checkout.

`ravel dataset-query-quantities population --analysis analysis.json` displays the supplied
analysis population. `ravel dataset-query-quantities context --task task.json --output fresh.json`
inspects pinned dataset, query, observable and presentation requirements without
service or scientific-runtime access. Execution uses an ordinary unapproved
`dataset-query-quantities` specification, approval and the science worker. See
[the supplied contract](reference/dataset-query-quantities.md).

## Reconstructed-event analysis

`ravel columnar-analysis` checks event files against a format descriptor (`inspect`), compiles a
recipe and checks it against the files (`validate`), checks a typed analysis specification
against a recipe (`spec-check`), runs one partition (`analyse`), adds partitions (`merge`),
writes the normalised histograms, cutflow and provenance (`finalize`) and draws a stacked control
plot from finalised results (`plot`). Studies run through the ordinary `columnar-analysis`
science mode. See [the recipe reference](reference/columnar-analysis.md).

## Shower and detector production

`ravel event-production check task.json` reads the LHE header, checks the Pythia command lines,
the merging settings, the model's invisible states, every Delphes card and the installed programs,
and prints what the production would do. `ravel event-production header FILE` prints what an LHE
header states, and `ravel event-production receipt FILE` checks a production receipt's Delphes files.
Productions run through the ordinary `event-production` science mode.
`ravel detector-card check CARD --invisible PDG` refuses a card that would reconstruct an invisible
state, `ravel detector-card derive` writes a managed derived or skimmed card with every change
recorded, and `ravel output-gate check` evaluates a finished stage's outputs against their contracts.
See [the production reference](reference/event-production.md).

`ravel root-schema --input FILE --draft` lists the trees and branches of a ROOT file without
writing anything and drafts a format descriptor and weight contract for review.

`ravel authored-analysis` lints agent-written analysis code, pins attempts, runs them in a
sandbox and prints the designer packet for a repair, within an approved `authored-analysis`
study. See [the authored step](reference/authored-analysis.md).

## Supplied EasyScan scan contracts

`ravel parameter-space-sampling context --task task.json --output fresh.json` inspects a supplied schema-2 scan contract. Supply the study identity, pinned request and INI, programme mappings, workspace population, finite resources and table export format. Incomplete mappings produce `missing_scan_input` before external tree inspection. Execute the original framework/programme/sampler workflow through the ordinary unapproved schema2 `parameter-space-sampling` plan, actual approval and common worker. See [the exact contract](reference/parameter-space-sampling.md); no replacement sampler, native execution or scientific qualification is inferred from context.


### Supplied tree arrays

`ravel tree-array-export inspect --task task.json` inspects a supplied tree-to-array
contract without decoding ROOT. Execution uses ordinary science mode
`tree-array-export` and plan/approve/run. The task has `input` and `input_sha256`.
Its pinned schema-2 request supplies `study_id`, `parameter_grid`, source pins,
an ordered dataset population, tree names, destinations, NPY/NPZ formats, consumer
associations, a column layout, source premises and resource bounds. Scalar,
positional jagged and constant columns have explicit source units, corresponding
field groups, padding and overflow policies. All actual tree rows survive.
Missing inputs refuse with `MissingArrayInput`; no installed file or layout
population is inferred. See [the export contract](reference/tree-array-export.md).


<a id="optional-symbolic-evaluation"></a>

### Symbolic evaluation

Use ordinary schema2 mode `symbolic-evaluation` for reviewed, source-bound Wolfram/FeynCalc scripts and the original external HEPTAPOD symbolic-to-Python converter. `ravel symbolic-evaluation inspect --input request.json --input-sha256 SHA256` checks complete declared prerequisites without importing the required engines or launching a kernel. The task is `{input,input_sha256}`. Bind the original question, executable/application metadata, complete provider/script/dependency trees, exact backend files, result/marker populations, variables, units, conventions and aggregate resources. Existing approval and Check-In2 review remain required. Complete formulas, complex pairs and failed/unissued entries reach ordinary result/report files; no physics correctness, numerical equivalence or original-catalogue completion is inferred. Missing installed Wolfram/SymPy is a prerequisite; the adapter installs nothing and edits no configuration. The source API and `docs/reference/symbolic-evaluation.md` describe the complete contract.


### Native source-graph diagnostics and calibration

Ordinary `native-statistical-construction` cells may explicitly declare fixed-NLL
derivatives or full-auxiliary fixed-truth calibration. Read the [source graph
diagnostics and calibration contract](reference/source-graph-diagnostics-calibration.md)
before preparing these studies. Observed data, explicitly generated Asimov data,
conditioning fits and calibration experiments retain separate source populations
and ordinary approval/review requirements. Software source checks do not establish
native integration, sampling, optimizer or coverage qualification.


### CosmicIC and Nyx source-bound operations

The ordinary `cosmic-evolution` mode prepares supplied source, native cards,
transfer tables and complete IC/Nyx product commitments. Read the
[CosmicIC/Nyx operation contract](physics/cosmic-evolution.md) before planning
retained-product reuse or an explicitly admitted site-local operation in an
already allocated job. Missing generator/writer sources, runtime/build closure,
IC normalization and remote accounting remain explicit prerequisites. Source
preparation does not establish native evolution or scientific qualification.


### Contur native companion operations

The ordinary `contur-companion` mode connects declared native SM tests, Herwig
cross-section and branching extraction, parameter-map plots, and Rivet plots to
source capture, unapproved planning and supervised operation reports. Read the
[Contur companion contract](reference/contur-companion.md) for complete input and product
populations, serial profiles and runtime requirements. Joint model-point/all-beam
grids use `contur-yoda`; cached results and software controls do not qualify native
execution, statistical inference or scientific applicability.

## Execution backends, partitions and sites

A supervised stage can run natively, in a podman container, on an HTCondor/SLURM cluster. Read [execution backends](reference/execution-backends.md).

```sh
ravel backend list                        # native, oci-local, site
ravel backend doctor                      # runtimes present; no credentials read
ravel backend prepare --spec stage.json --out stage-plan.json
ravel backend handles --rundir RUN        # jobs of a run, with their state
ravel backend recover --handle DIR        # adopt an interrupted job; never resubmits
ravel partitions run --rundir RUN --stage parts --spec partitions.json --workdir W --merge  # supervised, approved stage only
ravel site doctor --profile lxplus --eos-dir /eos/user/a/me/work
ravel site study-job submit --rundir RUN --account A --partition P --cpus 16 --time 720 -- AGENT ...  # one study per Slurm job
ravel ntuples resolve --declaration samples.json --out resolved.json
ravel ntuples normalize --resolved resolved.json --out dataset.json \
  --xsec-db xsec.txt --xsec-descriptor xsec-columns.json --lumi lumi.json --bookkeeper bookkeeper.json
```

Run a backend plan through `stage_supervisor --backend-plan`; machine, image and
launch commands are dry runs until `--execute`. `ravel site study-job` runs a whole
study, agent included, inside one Slurm allocation; heavy rungs need the run's
approval ([batch allocations](reference/batch-allocations.md)). `backend launch --execute` and
`partitions run` run only as supervised stages of an approved run. Science and
scoped specifications place their stage with `execution.backend_plan`.

## Figures and comparison with published results

```sh
ravel figure digitize --spec digitise.json --out published/      # digitized.json and review.png
ravel compare --spec compare.json --out comparison.json          # metrics, verdict and summary
ravel figure plane --spec plane.json --out plane/                # parameter-plane figure
ravel figure measurement --spec overlay.json --out overlay/      # data, predictions, ratio, official figure
ravel figure plan --task task.json                               # files a figure-comparison study reads
```

Inside a run, the `figure-comparison` scientific study runs these as planned operations.
See [figures and comparison](reference/figures-and-comparison.md).

## Command index

| Command | Purpose |
|---|---|
| `ravel initiate` | Draft an intake contract and run ledger from a request |
| `ravel status` | Rebuild a run's current-state packet |
| `ravel plan`, `ravel approve`, `ravel run` | Plan, approve and execute a scientific or scoped study |
| `ravel science-correct` | Admit a bounded correction to a scientific study |
| `ravel runtime-capsule` | Inspect or create a prepared runtime capsule |
| `ravel compare-recipes` | Compare two executed physics recipes |
| `ravel validate` | Validate a task contract |
| `ravel audit` | Audit a source checkout |
| `ravel release` | Record a release gate (`check --gate G8`: the agent call-site census) |
| `ravel analyses` | Search and inspect the public routine census |
| `ravel research-orchestrate` | Prepare and run the research coordinator for an open question |
| `ravel research-cycle` | Connect hypotheses, ordinary studies, reviews and synthesis |
| `ravel research-tools` | Prepare source API context and experiment plans |
| `ravel research-protocol` | Bind staged research protocols and prepare comparison studies |
| `ravel intake-plan` | Prepare and record the designer choice for a calculation intake |
| `ravel task-completion` | Inspect coverage of the original task or require whole-task acceptance |
| `ravel fill-template` | Fill a supplied result template from an accepted result |
| `ravel figure` | Digitise published figures and draw parameter-plane and measurement figures |
| `ravel compare` | Compare a result with a reference under declared transformations and tolerances |
| `ravel agent-graph` | Create, run and control bounded agent graphs |
| `ravel agentrivet-construction` | Build a Rivet routine from a paper with event feedback |
| `ravel rivet-hepdata-map` | Build a HEPData table map and reference YODA, or check a routine's bookings |
| `ravel resonance-study` | Compile resonance hypotheses into ordinary search studies |
| `ravel model-events` | Prepare an event-generation study |
| `ravel model-spectrum` | Prepare a named-model spectrum or a UFO and card handoff |
| `ravel generation-efficiency` | Prepare same-process pilots and empirical cost forecasts |
| `ravel pilot-cost` | Measure completed pilots and forecast a larger run |
| `ravel lhe-transform` | Check LHE particle-rewrite rules and count their matches |
| `ravel spec-reconcile` | Compare a physics intent with MadGraph cards |
| `ravel model-portfolio` | Prepare a simplified-model portfolio study |
| `ravel model-tool-bridge` | Prepare a supplied-UFO matrix-element study |
| `ravel model-provider-bridge` | Prepare a native scientific-provider qualification |
| `ravel model-derivation-bridge` | Prepare a model derivation or qualify reuse of accepted output |
| `ravel model` | Author a FeynRules model from a ModelSpec or template, lint it, run two-gauge checks, check the UFO, and admit a UFO (`ravel model admit`) |
| `ravel simplified-spectrum` | Write an SLHA2 card for a simplified-model spectrum and check decay closure |
| `ravel xsec` | Look up a published cross section under a named order, PDF and scale |
| `ravel lineshape` | Leading-order partial widths, propagator schemes and width consistency |
| `ravel normalization` | Reconcile generator cross sections, or derive branching and filter factors |
| `ravel normalization-ledger` | Check every normalization factor and recompute delivered yields |
| `ravel amplitudes` | Check amplitude-basis documents (integration, predictions, weighted events, cross-checks) and write their study specification |
| `ravel model-conventions` | Show NMSSM spectrum conventions |
| `ravel mssm-physical-map` | Inspect MSSM spectrum and lifetime grids or prepare an LLP recipe |
| `ravel chargino-decay-table` | Prepare a pure-limit chargino decay table |
| `ravel backend-provider` | Discover backend source catalogues and prepare native inputs |
| `ravel contur-yoda` | Prepare a Contur study on one YODA file |
| `ravel contur-companion` | Prepare Contur SM tests, Herwig extraction and plots |
| `ravel symbolic-evaluation` | Inspect symbolic evaluation inputs |
| `ravel feyn-graph` | Inspect Feynman diagram enumeration inputs |
| `ravel diagram-analysis` | Inspect NDA and Diagrammatica diagram inputs |
| `ravel feynarts-amplitude` | Prepare FeynArts and FeynCalc amplitude source |
| `ravel root-stream` | Inspect a site ROOT sample, DSID and weight contract |
| `ravel site-workflow` | Export prepared studies for a site analysis and WMS profile |
| `ravel wms adopt`, `adopt-run`, `adopt-status` | Pin an external Snakefile, plan its approved inspection and its supervised run, and show the state of an adoption |
| `ravel site` | Check Linux analysis-site readiness, print a no-root install plan and run one study per Slurm allocation |
| `ravel study-grid` | Submit, observe, resume and harvest a finite grid of prepared studies, each cell in its own batch allocation ([batch allocations](reference/batch-allocations.md)) |
| `ravel ntuples` | Resolve grid datasets into ROOT members and build MC normalization |
| `ravel backend` | Inspect execution backends, prepare plans, and follow, recover or cancel backend jobs |
| `ravel partitions` | Run a stage over a split input population and merge additive outputs |
| `ravel dataset-query-quantities` | Inspect supplied columnar query requirements |
| `ravel checkmate-events` | Prepare a CheckMATE study on supplied HepMC2 events |
| `ravel tree-array-export` | Inspect supplied tree, column and array destination contracts |
| `ravel parameter-space-sampling` | Inspect supplied EasyScan scan contracts |
| `ravel sfitter-observed-events` | Acquire event and bin observations and sampling covariance for SFitter |
| `ravel sfitter-workflow` | Prepare SFitter phases and handoffs |
| `ravel sfitter-review` | Recompute SFitter review evidence and prepare review roles |
| `ravel review` | Open, critique, correct and recheck a physics decision |
| `ravel judgment` | Dispatch scoped physics review roles and return repairs |
| `ravel review-context` | Prepare and read role-specific evidence packets |
| `ravel review-rubric` | Show a review rubric, select it for a run with a pinned overlay, and apply it to a review packet |
| `ravel failed-review` | Record a failed stage's diagnostic premises |
| `ravel diagnose` | Evaluate a frozen controlled-experiment contract |
| `ravel decision-case` | Check an evidence-linked decision graph |
| `ravel hypothesis-board` | Preserve blind advisory hypotheses and falsifiers |
| `ravel experiment-allocator` | Recommend an advisory experiment allocation |
| `ravel evidence-independence` | Inspect shared lineage between evidence artifacts |
| `ravel numerical-witness` | Derive or independently check numerical claims |
| `ravel analysis-witness` | Check a retained typed-analysis bundle |
| `ravel reco-ntuple` | Check a reconstructed-ntuple format descriptor for native routine runs |
| `ravel note-profile` | Check a page-limited note rule pack and write its formatting contract |
| `ravel agent-audit` | Build per-prompt audit logs from agent transcripts and session hooks |
| `ravel agent-surface` | Install RAVEL's skills, hooks and rules into another project |
| `ravel agent-cli` | Answer RAVEL model requests with a fresh Claude Code, Codex, Antigravity or Gemini CLI session |
| `ravel transport` | List, show and probe the declared model transports (`list`, `show <id>`, `probe <id>` or `probe --all`) |
| `ravel project-instructions` | Pin one project instruction document for a run (`pin`, `repin` by an explicit approval, `show`); every worker and reviewer session of the run receives it |
| `ravel export-submission` | Write and verify a relocatable submission package of an accepted analysis |
| `ravel deliver-workspace` | Copy an accepted study's artifacts into a requester-supplied layout with a provenance index, and verify it later (`verify --into WORKSPACE`) |
| `ravel conformance` | Check a git working tree and declared run records against a requester-supplied rule pack, read-only |
| `ravel manuscript` | Pin a supplied class bundle without redistribution rights (`bundle`) and prepare source-bound slides from an authenticated note build (`slides`); compilation runs through the supervised manuscript build |
| `ravel gate` | Host-neutral gate verdict for a run and an action or tool call (hosts without hooks) |
| `ravel go`, `ravel advance` | Record a native run's CHECK-IN 2 GO or advance its lifecycle stage |
| `ravel lifecycle check` | Check a run against the lifecycle state machine and invariants |
| `ravel checkin validate` | Validate a CHECK-IN deck |
| `ravel result-pack` | Assemble `result.json` and `figures.json`; refuses raw launches and failed delivery checks |
| `ravel stage` | Run one approved pipeline stage under supervision |
| `ravel scan` | Plan, launch, monitor and assemble a parameter scan |
| `ravel cost` | Size compute before spending it and write the cost preflight record |
| `ravel trap-sweep` | Write or check the physics trap sweep of a run |
| `ravel certify` | Certify acceptance times efficiency against published values |
| `ravel procedure` | Export or verify a recorded procedure note, worker audit and Snakemake evidence workflow |
| `ravel env` | Capture a content-addressed environment snapshot or report package/runtime differences |
| `ravel wms` | Workflow-manager-first projects: `init`, `add` an approved run as a Snakemake rule before it runs, `launch` it through run-step, `status`, `revalidate` a task after a policy change |
| `ravel knowledge` | Query and check the generated knowledge atlas |
| `ravel modes` | List, show and retrieve examples for registered science modes |
| `ravel work` | Seal production work orders (`seal`), show the next ready node (`next`), dispatch its role worker (`dispatch --node`), record a host waiver (`waive`, `host-authored`), pin CHECK-IN 1 work obligations (`pin-obligations`) and adopt exact nonempty role outputs (`adopt`) |
| `ravel drive` | Run an epoch-two run through the `lifecycle.drive` graph; it stops at each human CHECK-IN and resumes on `ravel drive respond --decision approve --record <approval record>` |
| `ravel rdj` | Read the next challenges, answers, status and cases of the decision justification for a gated action; authorization is by code |
| `ravel graph` | Run, observe, answer and drain registered agent graphs (`run`, `status`, `stop`, `respond`, `events`, `list`) |
| `ravel check:event_accounting` | Reconcile event counts and signed moments under declared transformations |
| `ravel lease` | Show the machine lease holder, run the read-only preflight of earlier jobs' live processes and clear an operator fence |
| `ravel gate-wiring` | Record CHECK-IN responses (approve, reopen, withdraw) and steering in custody, and report RDJ cost |
| `ravel steer` | Record steering through gate-wiring |
| `ravel respond` | Record responses through gate-wiring |
| `ravel research-preregister` | Derive and record the research preregistration from an approved CHECK-IN 1 plan |
| `ravel method-decision` | Validate and render the cheapest sufficient method in CHECK-IN 1 |
| `ravel literature` | Check evidence cards, follow located citations and code commits, and resolve publication titles |
| `ravel catalogue` | Build the local analysis catalogue from your Rivet and SimpleAnalysis checkouts |

Run `ravel <command> --help` for each command's arguments.
