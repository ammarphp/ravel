# Ravel package, intake, and replay environment

The distribution name is `ravel-hep`; the import and command are `ravel`. Install from a
checkout or a built wheel. These commands do not imply that a package has been published on
PyPI. Python 3.10–3.12 is declared; the frozen replay environment was verified on
CPython 3.12.13, macOS ARM64. Other declared platforms are not established by that check.

For draft intake and contract validation, the base package has no runtime dependencies:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/ravel --help
```

Run installation from the checkout, or replace `.` with the path to a built wheel. Use
`pip install -e .` for editable development. The installed `ravel` command and
`python -m ravel` can be run from any working directory with that environment active.
The additional frozen environment below is needed for the cached numerical replay:

```sh
uv python install 3.12.13
uv venv --python 3.12.13 .venv-replay
uv pip sync --python .venv-replay/bin/python --require-hashes requirements-replay.lock
uv pip install --python .venv-replay/bin/python --no-deps .
.venv-replay/bin/ravel --help
.venv-replay/bin/ravel replay --out /tmp/ravel-replay-example
```

Use a new output path for every replay. The directory contains `environment.json`,
`results.json`, and `work/` with the fresh statistical output and subprocess logs. Existing
output directories are refused, including on failed runs, so failure evidence is retained.
The environment record captures all installed Python distribution versions and a SHA-256
fingerprint of the selected engine/input bundle; these identify the replay rather than
claiming that its environment was necessarily installed from the committed lock.
The command uses its own Python interpreter even when a local conda toolchain exists.
The package installation is read-only during replay; no checkout or installation-directory
write permissions are needed. Once installed, the cached replay requires no network access.

Replay refits one published squark benchmark through the existing pyhf engine, then checks
the existing numerical floors and provenance requirements. It does not generate events,
rerun detector simulation, or reproduce the full analysis. Without Rivet's YODA bindings,
acceptance certification is explicitly taken from the tracked benchmark baseline and marked
`cached_replay` in the result. A successful replay proves only this scoped regression check.
It does not establish broad generality, fresh agent self-drive, or publication readiness.

The wheel includes the engines and the small explicit input allowlist in
`src/ravel/resources.py`. Build-time missing-input checks prevent an incomplete export from
producing an apparently usable wheel. Engine code is packaged from its existing source files;
there is no separately maintained copy of the physics or contract logic.

## Start a draft intake

```sh
ravel initiate \
  --prompt "Reproduce Figure 3 of ATLAS SUSY-2018-16 for a slepton-bino model." \
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

Exit 0 means intake files were written, not approved. Exit 1 means an invalid/unsupported route;
exit 2 means an input, command or write error. Blank, unsupported or invalid requests create no
output directory. Existing destinations, including symlinks, are refused. Partial outputs from
write failures are retained; use a new destination for a new intake, never to resume an existing run.

Without installation, use the same entry point from the source tree:

```sh
python3.12 /path/to/ravel/scripts/run.py ravel.__main__ initiate \
  --prompt-file /path/to/request.txt --out /tmp/ravel-source-intake
```

## Resume and inspect current state

```sh
ravel status --rundir /path/to/existing-run
ravel status --rundir /path/to/existing-run --write
```

Both commands rebuild the packet from the live contract, ledger, lifecycle gates, execution
receipts and approval. `--write` also refreshes `current_state.json`; it does not change the source
contract, ledger or scientific artifacts. Inspect `next_required`, `blockers`, approval errors and
stage receipts, then open only the relevant workflow step. Refresh after a restart or compaction.

The packet is a view, not permission or a scientific certificate. Executors and serving gates
revalidate the original artifacts. Do not edit the packet to unblock work or rerun intake to resume.
Exit 0 means the packet was derived; lifecycle blockers or absent approval may still be present.
Exit 1 indicates invalid execution evidence; input/command errors exit 2.

## Validate, replay, and audit

```sh
ravel validate path/to/task_contract.json --json
ravel validate --schema
python -m ravel validate path/to/task_contract.json
```

Validation uses the existing validator's strict JSON reader and schema checks, including
duplicate-key and nonfinite-number rejection. Exit 0 means schema-valid, 1 means
invalid, and 2 means a command/input error. It never grants compute approval. The Python API is
`from ravel import validate_task_contract`; it accepts a decoded JSON value and returns the
same list of validation errors. Replay exits 0 for a passing gate, 1 for a benchmark breach,
and 2 for a command/setup error. Retained logs explain subprocess failures.

```sh
ravel audit --root /path/to/ravel
ravel audit --root /path/to/ravel --out /tmp/ravel-audit.md
```

The R1–R9 audit requires a source checkout because it examines workflow documents, available
run records, and the native tool inventory. If run within a checkout, `--root` can be omitted.
The audit is read-only unless an explicit, new `--out` is supplied. Its existing engine exits
0 when a report completes, even if dimensions warn or fail. It is a diagnostic report, not a
pass/fail gate. The public export contains fewer records than the research checkout, so its
scores must not be compared as measurements of physics capability. The standalone wheel
reports an actionable source-checkout requirement rather than inventing an audit score.

The replay extra declares bounded compatible direct dependencies; `requirements-replay.lock`
freezes all transitive versions with distribution hashes for Python 3.12. NumPy is held below
2 because the existing project records a pyhf toy-based incompatibility. Full native HEP
reproducibility needs the separately documented compiler, generator, shower, detector, analysis,
and external-data setup. This Python lock does not change the native-default execution policy.

To update the lock deliberately, resolve and review the dependency diff, then run a clean
replay and the relevant numerical and package tests before accepting new versions:

```sh
uv pip compile pyproject.toml --extra replay --extra test --python-version 3.12 \
  --universal --generate-hashes --output-file requirements-replay.lock
uv build --out-dir /tmp/ravel-dist
```

Build outputs are wheels and source distributions. Build the wheel from the source
distribution as an additional release check. The build backend itself is pinned in
`pyproject.toml`; its isolated build dependencies are separate from the replay runtime lock.
For public release, build from the sanitized public export so historical machine paths in
research metadata are not copied into the wheel. Run the package portability check with:

```sh
RAVEL_TEST_WHEEL=/tmp/ravel-dist/ravel_hep-0.4.0-py3-none-any.whl \
  .venv-replay/bin/python -m pytest tests/unit/test_ravel_cli.py \
  tests/unit/test_cli_initiate.py -q
```

The 2026-09-05 clean-environment check built a wheel from its source distribution and
installed it outside the checkout. The fast replay passed with observed/expected
mu95 of 0.219143/0.275714 and S95 recovery ratios 0.997857/1.02296. Acceptance was explicitly
cached. The existing five numerical selftests also passed, including the NaN-pocket
optimizer and published 2018-06 free-fit regressions. These are scoped checks, not a fresh
generation trial. Package portability checks also covered wheel payload parity and protection of existing output
evidence; consult the release evidence for the tested revision and complete test counts.
