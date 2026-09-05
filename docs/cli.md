# Ravel package and replay environment

The distribution name is `ravel-hep`; the import and command are `ravel`. Install from a
checkout or a built wheel. These commands do not imply that a package has been published on
PyPI. Python 3.10–3.12 is declared; the frozen replay environment was verified on
CPython 3.12.13, macOS ARM64. Other declared platforms are not established by that check.

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
RAVEL_TEST_WHEEL=/tmp/ravel-dist/ravel_hep-0.2.0-py3-none-any.whl \
  .venv-replay/bin/python -m pytest tests/unit/test_ravel_cli.py -q
```

The 2026-09-05 clean-environment check built a wheel from its source distribution and
installed it outside the checkout. The fast replay passed with observed/expected
mu95 of 0.219143/0.275714 and S95 recovery ratios 0.997857/1.02296. Acceptance was explicitly
cached. The existing five numerical selftests also passed, including the NaN-pocket
optimizer and published 2018-06 free-fit regressions. These are scoped checks, not a fresh
generation trial. The package and benchmark invocation tests passed 16 checks, including
wheel payload parity and protection of existing output evidence.
