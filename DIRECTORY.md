# Repository directory

Maintained by hand with the `directory-keeper` skill when files are added, moved or removed.
Historical evidence is read-only. New runs use a per-run `run_state.json` ledger.
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
| `LICENSE` | Apache License 2.0 |
| `Makefile` | Replay, claims, green-bar and adversarial-check targets |
| `NOTICE` | Copyright and attribution notice |
| `README.md` | Project overview and quick start |
| `hatch_build.py` | Wheel build hook that packages the curated replay data |
| `pyproject.toml` | Package metadata, dependencies and tool settings |
| `requirements-replay.lock` | Hashed, pinned replay and test dependencies |
| `requirements-replay.txt` | Replay and test requirements (installs the lock file) |

## Main directories

| Directory | Contents |
|---|---|
| `src/ravel/physics/` | Event processing and statistical engines |
| `src/ravel/workflow/` | Run lifecycle, approvals, provenance, and scan orchestration |
| `src/ravel/validation/` | Task validation, scientific checks, and benchmark replay |
| `src/ravel/plotting/` | Figures and comparisons |
| `src/ravel/data/` | Templates, fixtures, and reference inputs |
| `tests/unit/` | Focused regression tests |
| `tests/adversarial/` | Adversarial workflow scenarios |
| `tests/fixtures/` | Immutable test inputs |
| `benchmarks/` | Benchmark and capability registries; start at `benchmarks/README.md` |
| `native/` | Native toolchain: build, setup and execution; start at `native/README.md` |
| `native/src/` | Native C++ source |
| `native/scripts/` | Native build and execution scripts |
| `environment/` | Simulation environment setup; start at `environment/README.md` |
| `scripts/` | Maintenance, documentation, evidence and audit commands |
| `docs/` | User documentation; start at `docs/README.md` |
| `docs/workflow/` | Physics workflow instructions |
| `docs/reference/` | Capabilities, contracts, and tool reference |
| `docs/validation/` | Scoped results, cases, and evidence descriptions |
| `docs/architecture/` | How a calculation is planned, run and checked, one figure per page |
| `docs/figures/` | Documentation figures, their sources and the shared style |
| `evidence/` | Curated historical inputs, measurements, and provenance; start at `evidence/README.md` |
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
| `src/ravel/workflow/waypoint_evidence.py` | Software: hashed CHECK-IN 2 comparison and artifact manifest |
| `src/ravel/workflow/launch_authorization.py` | Software: shared checked launch interface and retained approval event chain |
| `src/ravel/workflow/stage_supervisor.py` | Watchdog around one pipeline stage command |
| `src/ravel/workflow/stop_dispatch.py` | Stop-hook checks, one branch per workflow rule |
| `src/ravel/workflow/workflow_state.py` | Per-run state machine and ledger (`run_state.json`) |
| `tests/fixtures/hook-probes/hook-primacy.json` | Recorded hook-behaviour probes (regression fixture) |
| `tests/unit/test_waypoint_authorization.py` | Software: adverse waypoint custody, launch ordering and validator regression probes |

## Curated evidence

| Collection | Contents |
|---|---|
| `evidence/benchmarks/atlas-2016-squark-pair/` | ATLAS 2016 squark-pair cached benchmark |
| `evidence/case-studies/arm64-container-slepton-200-150/` | ARM64 emulated-container slepton timing |
| `evidence/case-studies/hvt-zprime-ww-low-mass-summary/` | HVT Z-prime to WW low-mass published-limit summary |
| `evidence/native-validation/compressed-electroweak/` | Compressed electroweak native and container oracle comparison |
| `evidence/native-validation/slepton-200-150/` | Native slepton 200/150 benchmark and ARM64 timing |
| `evidence/native-validation/three-lepton-electroweak/` | Three-lepton electroweak native and container oracle comparison |
| `evidence/native-validation/zero-lepton-squark/` | Zero-lepton squark native and container oracle comparison |
| `evidence/scans/slepton-bino-figure-3/` | Slepton-bino figure 3 scan |
| `evidence/scans/slepton-bino-pdf-rescan/` | Slepton-bino paired PDF rescan |
