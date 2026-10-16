# Contributing

Contributions can improve a physics engine, catch a failure, clarify a workflow,
or make an existing result easier to reproduce. Describe the concrete problem,
the resulting behavior, and the evidence supporting the change.

## Set up

Prepare Python 3.12 and the [compiler prerequisites](docs/installation.md#before-you-start), then run the complete Python setup from the repository root:

```bash
python3.12 scripts/setup/python_installation.py
source .venv/bin/activate
python -m pip check
ravel --help
```

The installer provides the full Python host and development tools in `.venv`, with separate required SModelS and SFitter environments. Follow the [installation guide](docs/installation.md) for native engines and their setup checks. Most development checks use software fixtures and source contracts.

## Check a change

Run the relevant unit tests while editing, then the full suite before proposing a
code change:

```bash
.venv/bin/python -m pytest tests/unit -q
```

The adversarial suite exercises intentionally invalid workflow states. Install the
repository's Git hooks before running its complete board; one case checks that
the pre-commit hook is actually installed. This changes this checkout's hook setup.

```bash
source .venv/bin/activate
bash scripts/maintenance/install-git-hooks.sh
.venv/bin/python tests/adversarial/run_suite.py --require-all
```

Activation also makes subprocesses and the installed hook use the development
environment's `python3` when they resolve it from `PATH`.

For changes to statistics, also run the engine selftests:

```bash
.venv/bin/python -m ravel.physics.pyhf_exclude selftest
.venv/bin/python -m ravel.physics.project_limits --selftest
```

Report failures, skips and unavailable native dependencies explicitly. A passing synthetic gate case demonstrates the guard's behavior;
it does not establish scientific accuracy or autonomous task completion.

### Locked statistics environment

CI installs the hash-locked statistics layer from `requirements-replay.lock`. To reproduce it, use a
fresh environment:

```bash
python3.12 -m venv .venv-replay
.venv-replay/bin/python -m pip install --require-hashes -r requirements-replay.lock
.venv-replay/bin/python -m pip install --no-deps -e .
```

The complete installer above is the default development setup.

The public test matrix installs this hash lock first and constrains the editable
package installation to those resolved versions. It partitions the sorted test
files into eight shards and runs a fresh pytest process for every file. The long
files listed in `ci_shards.LONG` each run in a job of their own:

```bash
python scripts/maintenance/ci_shards.py --index 0 --count 8 --run --file-timeout 2400
python scripts/maintenance/ci_shards.py --long tests/unit/test_wms_retry.py --run --file-timeout 16200
```

The runner retains every file's exit status, continues after failures, prints file
and shard timings, and supplies a short private temporary root for Unix sockets.
This runner sets umask `0002` for every pytest child; helper executables used by
permission checks must explicitly set mode `0700`. Cluster rehearsals using other
launchers must set `0002` inside the remote test process too: a batch script can
reset the invoking shell's umask. Include a run with the sandbox unavailable.
Shared runners can take substantially longer than cluster nodes. Tests of custody
or presentation should inject a scoped clock rather than depend on elapsed wall
time; deadline tests must retain explicit clock advancement and exhaustion checks.
A file that reaches its time limit is stopped with its process group, reported as
`exit=timeout` and counted as failed; a test still running two minutes before the
file's limit dumps its thread tracebacks to the log once, so a hang names its test and
waiting line.
The Linux CI job installs bubblewrap, logs and disables the AppArmor restriction
on unprivileged user namespaces when that sysctl exists, and requires the actual
worker denial probe to succeed before testing. Tests that need real confinement
skip with `sandbox-blocked` when its launcher is unavailable; a failed denial
remains a test failure. Inert transport controls still run without a launcher.

Do not infer numerical drift from a shared pytest process alone: module imports,
optimizer state and loaded-runtime custody can survive between files. Preserve
and restore global numerical backends in tests that change them. The reference-fit
API scopes its guarded NumPy optimizer and restores its caller's backend. Source exports
bind package source/data bytes and membership, excluding generated `__pycache__`
trees; they do not depend on checkout timestamps.

## Preserve scientific inputs

Keep upstream physics inputs attributable.
Explain changes to statistical assumptions, tolerances, or comparison bases.
Do not update a reference result or relax a gate merely to obtain a passing test.
Add a focused regression when fixing a substantive failure, ideally showing that
the previous behavior fails it.

Scientific full and scan test fixtures use
`tests/unit/method_decision_fixture.py:admit_method` after planning and before approval.
Choose a fictional decision that fits the operation. The helper validates the record
and refreshes its CHECK-IN disclosure. Install the decision before deliberately changing
inputs in a refusal test. An inert process lifecycle test with no scientific contract
uses the existing `_engineering_only=True` API, zero generated events and the explicit
`engineering_session` fixture. Production agent sessions remain refused on that path.

Changes to the workflow also need corresponding contract, hook, and test updates
where applicable.

## Keep the repository navigable

Use the [directory index](DIRECTORY.md) to choose a
home for new files. Keep user instructions in `docs/`, implementation in
`src/ravel/`, and tests in `tests/`.
Reconcile `DIRECTORY.md` when the tree
changes. Agent-specific instructions are in [AGENTS.md](AGENTS.md).

In a pull request, state what changed, why, how it was checked, and any remaining
limitations.
