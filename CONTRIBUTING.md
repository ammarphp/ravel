# Contributing

Contributions can improve a physics engine, catch a failure, clarify a workflow,
or make an existing result easier to reproduce. Describe the concrete problem,
the resulting behavior, and the evidence supporting the change.

## Set up

Use Python 3.12 and the committed lock from the repository root:

```bash
python3.12 -m venv .venv-dev
.venv-dev/bin/python -m pip install --require-hashes -r requirements-replay.lock
.venv-dev/bin/python -m pip install --no-deps -e .
```

The lock includes the Python test dependencies. Native simulation tools are
separate; see [installation](docs/installation.md). Most development checks do
not require event generation or an LLM call.

## Check a change

Run the relevant unit tests while editing, then the full suite before proposing a
code change:

```bash
.venv-dev/bin/python -m pytest tests/unit -q
.venv-dev/bin/python scripts/check_publication.py
.venv-dev/bin/python scripts/check_evidence.py --check
```

The adversarial suite exercises intentionally invalid workflow states. Install the
repository's Git hooks before running its complete board; one case checks that
the pre-commit hook is actually installed. This changes this checkout's hook setup.

```bash
source .venv-dev/bin/activate
bash scripts/maintenance/install-git-hooks.sh
.venv-dev/bin/python tests/adversarial/run_suite.py --require-all
```

Activation also makes subprocesses and the installed hook use the development
environment's `python3` when they resolve it from `PATH`.

For changes to statistics, dependencies, packaging, or benchmark inputs, also run
the cached replay into a fresh directory:

```bash
.venv-dev/bin/ravel replay --out ravel-replay-change
```

Report failures, skips, unavailable native dependencies, and cached acceptance
explicitly. A passing synthetic gate case demonstrates the guard's behavior;
it does not establish scientific accuracy or autonomous task completion.

## Preserve scientific evidence

Keep upstream physics inputs attributable and preserve original run records.
Explain changes to statistical assumptions, tolerances, or comparison bases.
Do not update a reference result or relax a gate merely to obtain a passing test.
Add a focused regression when fixing a substantive failure, ideally showing that
the previous behavior fails it.

Numerical publication claims live in [the results page](docs/validation/results.md)
and [claim registry](evidence/claims.json). Capability state comes from
[the capability matrix](benchmarks/capabilities.json); update the source and run
`scripts/gen_status.py` rather than editing generated paragraphs. Changes to the
workflow also need corresponding contract, hook, and test updates where applicable.

## Keep the repository navigable

Use the [repository layout](docs/development/repository-layout.md) to choose a
home for new files. Keep user instructions in `docs/`, implementation in
`src/ravel/`, tests in `tests/`, and research arguments in `docs/research/`.
Preserve historical run identifiers and reconcile `DIRECTORY.md` when the tree
changes. Agent-specific instructions are in [AGENTS.md](AGENTS.md).

In a pull request, state what changed, why, how it was checked, and any remaining
limitations. Release and public-export work follows the
[distribution guide](docs/development/distribution.md).
