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
