# Repository directory

Generated from `evidence/collections.json` during distribution export.
Historical evidence is read-only. New runs use a per-run `run_state.json` ledger.

## Root files

| File | Purpose |
|---|---|
| `.gitignore` | Project metadata, entry points, or policy |
| `AGENTS.md` | Project metadata, entry points, or policy |
| `CHANGELOG.md` | Project metadata, entry points, or policy |
| `CITATION.cff` | Project metadata, entry points, or policy |
| `CLAUDE.md` | Project metadata, entry points, or policy |
| `CONTRIBUTING.md` | Project metadata, entry points, or policy |
| `DIRECTORY.md` | Project metadata, entry points, or policy |
| `LICENSE` | Project metadata, entry points, or policy |
| `Makefile` | Project metadata, entry points, or policy |
| `NOTICE` | Project metadata, entry points, or policy |
| `README.md` | Project metadata, entry points, or policy |
| `benchmarks/README.md` | Project metadata, entry points, or policy |
| `docs/README.md` | Project metadata, entry points, or policy |
| `environment/README.md` | Project metadata, entry points, or policy |
| `hatch_build.py` | Project metadata, entry points, or policy |
| `native/README.md` | Project metadata, entry points, or policy |
| `pyproject.toml` | Project metadata, entry points, or policy |
| `requirements-replay.lock` | Project metadata, entry points, or policy |
| `requirements-replay.txt` | Project metadata, entry points, or policy |

## Main directories

| Directory | Contents | Files |
|---|---|---|
| `src/ravel/physics/` | Event processing and statistical engines | 20 |
| `src/ravel/workflow/` | Run lifecycle, approvals, provenance, and scan orchestration | 16 |
| `src/ravel/validation/` | Task validation, scientific checks, and benchmark replay | 17 |
| `src/ravel/plotting/` | Figures and comparisons | 12 |
| `src/ravel/data/` | Templates, fixtures, and reference inputs | 9 |
| `tests/unit/` | Focused regression tests | 71 |
| `tests/adversarial/` | Adversarial workflow scenarios | 37 |
| `tests/fixtures/` | Immutable test inputs | 6 |
| `benchmarks/` | Benchmark and capability registries | 11 |
| `native/src/` | Native C++ source | 3 |
| `native/scripts/` | Native build and execution scripts | 7 |
| `environment/` | Simulation environment setup | 6 |
| `scripts/` | Maintenance, documentation, and export commands | 17 |
| `docs/workflow/` | Physics workflow instructions | 50 |
| `docs/reference/` | Capabilities, contracts, and tool reference | 8 |
| `docs/validation/` | Scoped results, cases, and evidence descriptions | 20 |
| `docs/development/` | Contributor guidance and explicitly labeled history | 20 |
| `docs/research/` | Research and evaluation protocols | 12 |
| `docs/guides/` | Longer guides and sources | 5 |
| `evidence/` | Curated historical inputs, measurements, and provenance | 185 |
| `.claude/` | Agent skills, rules, and enforcement hooks | 32 |
| `.agents/` | Mirrored skills | 16 |
| `.github/` | Continuous integration | 1 |

## Workflow enforcement files

| File | Purpose |
|---|---|
| `.claude/hooks/posttooluse-observer.sh` | Workflow enforcement or its regression fixture |
| `.claude/hooks/pretooluse-skill.sh` | Workflow enforcement or its regression fixture |
| `.claude/hooks/stop-dispatcher.sh` | Workflow enforcement or its regression fixture |
| `.claude/hooks/userpromptsubmit-router.sh` | Workflow enforcement or its regression fixture |
| `scripts/maintenance/install-git-hooks.sh` | Workflow enforcement or its regression fixture |
| `src/ravel/validation/sr_plausibility.py` | Workflow enforcement or its regression fixture |
| `src/ravel/validation/validate_checkin.py` | Workflow enforcement or its regression fixture |
| `src/ravel/validation/validate_parameters.py` | Workflow enforcement or its regression fixture |
| `src/ravel/workflow/preflight_watcher.py` | Workflow enforcement or its regression fixture |
| `src/ravel/workflow/progress_reporter.py` | Workflow enforcement or its regression fixture |
| `src/ravel/workflow/provenance.py` | Workflow enforcement or its regression fixture |
| `src/ravel/workflow/stage_supervisor.py` | Workflow enforcement or its regression fixture |
| `src/ravel/workflow/stop_dispatch.py` | Workflow enforcement or its regression fixture |
| `src/ravel/workflow/workflow_state.py` | Workflow enforcement or its regression fixture |
| `tests/fixtures/hook-probes/hook-primacy.json` | Workflow enforcement or its regression fixture |

## Curated evidence

| Collection | Files |
|---|---|
| `evidence/benchmarks/atlas-2016-squark-pair/` | 114 |
| `evidence/case-studies/arm64-container-slepton-200-150/` | 2 |
| `evidence/case-studies/hvt-zprime-ww-low-mass-summary/` | 7 |
| `evidence/native-validation/compressed-electroweak/` | 5 |
| `evidence/native-validation/slepton-200-150/` | 5 |
| `evidence/native-validation/three-lepton-electroweak/` | 5 |
| `evidence/native-validation/zero-lepton-squark/` | 5 |
| `evidence/scans/slepton-bino-figure-3/` | 18 |
| `evidence/scans/slepton-bino-pdf-rescan/` | 11 |
