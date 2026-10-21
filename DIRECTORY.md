# Repository directory

Maintained by hand with the `directory-keeper` skill when files are added, moved or removed.
Each run uses a per-run `run_state.json` ledger.
README demonstrations write to ignored `local-runs/`; these local outputs are not tracked.

## Root files

| File | Purpose |
|---|---|
| `.gitignore` | Paths Git does not track (local runs, build products, caches) |
| `AGENTS.md` | Agent instructions (the same text as `CLAUDE.md`) |
| `CHANGELOG.md` | Release notes |
| `CITATION.cff` | Citation metadata |
| `CLAUDE.md` | Agent instructions for Claude Code (the same text as `AGENTS.md`) |
| `CONTRIBUTING.md` | Development setup, checks and contribution rules |
| `DIRECTORY.md` | This map of the repository |
| `GEMINI.md` | Project file |
| `LICENSE` | Apache License 2.0 |
| `Makefile` | Green-bar and adversarial-check targets |
| `NOTICE` | Copyright and attribution notice |
| `README.md` | Project overview and quick start |
| `THIRD-PARTY-NOTICES.md` | Licences of third-party files copied into the repository |
| `distribution.json` | The explicit selection of files the distribution carries |
| `hatch_build.py` | Wheel build hook that packages the curated replay data |
| `pyproject.toml` | Package metadata, dependencies and tool settings |
| `requirements-full.txt` | Full Python host requirements (declarations in `pyproject.toml`) |
| `requirements-replay.lock` | Hashed, pinned replay and test dependencies |
| `requirements-replay.txt` | Replay and test requirements (installs the lock file) |
| `requirements-site-wms.in` | Inputs of the workflow-management profile, resolved into its hash lock |
| `requirements-site-wms.lock` | Hashed lock of the workflow-management profile |
| `requirements-site-wms.txt` | Separate Linux workflow-management profile |
| `requirements-site.txt` | Linux ROOT and site analysis profile |

## Main directories

| Directory | Contents |
|---|---|
| `src/ravel/physics/` | Event processing and statistical engines |
| `src/ravel/workflow/` | Run lifecycle, approvals, provenance, and scan orchestration |
| `src/ravel/validation/` | Task validation and scientific checks |
| `src/ravel/plotting/` | Figures and comparisons |
| `src/ravel/data/` | Templates, fixtures, and reference inputs |
| `tests/unit/` | Focused regression tests |
| `tests/adversarial/` | Adversarial workflow scenarios |
| `tests/fixtures/` | Immutable test inputs |
| `native/` | Native toolchain: build, setup and execution; start at `native/README.md` |
| `native/src/` | Native C++ source |
| `native/scripts/` | Native build and execution scripts |
| `environment/` | Simulation environment setup; start at `environment/README.md` |
| `scripts/` | Maintenance, documentation and audit commands |
| `docs/` | User documentation; start at `docs/README.md` |
| `docs/workflow/` | Physics workflow instructions |
| `docs/reference/` | Capabilities, contracts, and tool reference |
| `docs/architecture/` | How a calculation is set up, run and checked, one figure per page |
| `docs/figures/` | Documentation figures, their sources and the shared style |
| `.claude/` | Agent skills, rules, and enforcement hooks |
| `.agents/` | Mirrored skills |
| `.github/` | Continuous integration |

## Workflow enforcement files

| File | Purpose |
|---|---|
| `.claude/hooks/posttooluse-observer.sh` | PostToolUse hook: records skills, edits and subagents in the run ledger |
| `.claude/hooks/pretooluse-skill.sh` | PreToolUse hook: blocks contract-dependent skills before intake |
| `.claude/hooks/stop-dispatcher.sh` | Stop hook: passes the turn to `stop_dispatch.py` |
| `.claude/hooks/userpromptsubmit-router.sh` | UserPromptSubmit hook: routes physics prompts to intake |
| `scripts/maintenance/install-git-hooks.sh` | Installs the pre-commit check of the agent surface |
| `src/ravel/validation/sr_plausibility.py` | Analysis-to-statistics plausibility gate |
| `src/ravel/validation/validate_checkin.py` | Check-in artifact validator |
| `src/ravel/validation/validate_parameters.py` | Parameter-validation obligations before long compute |
| `src/ravel/workflow/preflight_watcher.py` | Checks a completion watcher's command before it is armed |
| `src/ravel/workflow/progress_reporter.py` | One-line progress report for a long scan or point |
| `src/ravel/workflow/provenance.py` | Run-state and lifecycle-artifact provenance |
| `src/ravel/workflow/stage_supervisor.py` | Watchdog around one pipeline stage command |
| `src/ravel/workflow/stop_dispatch.py` | Stop-hook checks, one branch per workflow rule |
| `src/ravel/workflow/workflow_state.py` | Per-run state machine and ledger (`run_state.json`) |
| `tests/fixtures/hook-probes/hook-primacy.json` | Recorded hook-behaviour probes (regression fixture) |
