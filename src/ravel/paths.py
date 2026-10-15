"""Locations for source checkouts, packaged data and native tools."""
from __future__ import annotations

import os
import hashlib
import stat
from pathlib import Path
import sys


def repository_root(start: str | Path | None = None) -> Path | None:
    """Find a Ravel source checkout without assuming the caller's directory depth.

    An explicit start confines the search to that path and its ancestors. Otherwise
    RAVEL_ROOT, this package's location, and the current directory are considered.
    Installed package data is deliberately not treated as a source checkout.
    """
    starts = ([Path(start)] if start is not None else
              ([Path(os.environ["RAVEL_ROOT"])] if os.environ.get("RAVEL_ROOT") else [])
              + [Path(__file__), Path.cwd()])
    for candidate in starts:
        candidate = candidate.expanduser().resolve()
        if candidate.is_file():
            candidate = candidate.parent
        for parent in (candidate, *candidate.parents):
            if ((parent / "pyproject.toml").is_file()
                    and (parent / "src/ravel/__init__.py").is_file()):
                return parent
    return None


def require_repository_root(start: str | Path | None = None) -> Path:
    root = repository_root(start)
    if root is None:
        raise FileNotFoundError("This operation requires a Ravel source checkout. "
                                "Set RAVEL_ROOT to its directory or run from that checkout.")
    return root


def package_data_path(*parts: str) -> Path:
    """Locate read-only package assets (Python wheels are installed unpacked)."""
    return Path(__file__).resolve().parent.joinpath("data", *parts)



WORKFLOW_INSTRUCTIONS = ('docs/reference/host-enforcement.md', 'docs/workflow/hooks.md', '.claude/skills/physicist-intake/SKILL.md', 'docs/cli.md', 'docs/installation.md', 'docs/reference/agentrivet-source.md', 'docs/reference/analysis-admission.md', 'docs/reference/deliver-workspace.md', 'docs/reference/background-model-construction.md', 'docs/reference/detector-response-moments.md', 'docs/reference/domain-adapters.md', 'docs/reference/environment.md', 'docs/reference/parameter-space-sampling.md', 'docs/reference/failure-modes.md', 'docs/reference/hs3-likelihood.md', 'docs/reference/initialized-settings-qualification.md', 'docs/reference/dataset-query-quantities.md', 'docs/reference/columnar-analysis.md', 'docs/reference/authored-analysis.md', 'docs/reference/site-workflows.md', 'docs/reference/intake-and-challenges.md', 'docs/reference/symbolic-evaluation.md', 'docs/reference/tree-array-export.md', 'docs/reference/source-graph-diagnostics-calibration.md', 'docs/reference/research-progress-and-indexed-meta-review.md', 'docs/physics/cosmic-evolution.md', 'docs/reference/contur-companion.md', 'docs/reference/joint-statistical-models.md', 'docs/reference/limitations.md', 'docs/reference/model-sources.md', 'docs/reference/native-categorical.md', 'docs/reference/native-portability.md', 'docs/reference/native-saved-fit.md', 'docs/reference/parametric-exponential-construction.md', 'docs/reference/parametric-power-construction.md', 'docs/reference/prepared-runtime.md', 'docs/reference/quantities-and-measurements.md', 'docs/reference/rivet-particle-component.md', 'docs/reference/rivet-shape-components.md', 'docs/reference/routine-build.md', 'docs/reference/scientific-results.md', 'docs/reference/scope.md', 'docs/reference/statistical-construction.md', 'docs/reference/svj-study-recipes.md', 'docs/workflow/README.md', 'docs/workflow/checklists/check-ins.md', 'docs/workflow/checklists/choosing-routine.md', 'docs/workflow/checklists/complex-analysis.md', 'docs/workflow/checklists/data-acquisition.md', 'docs/workflow/checklists/detector-fidelity.md', 'docs/workflow/checklists/exclusion-model.md', 'docs/workflow/checklists/figure-contract.md', 'docs/workflow/checklists/generation-settings.md', 'docs/workflow/checklists/judgment-protocols.md', 'docs/workflow/checklists/merging.md', 'docs/workflow/checklists/model-cards.md', 'docs/workflow/checklists/physics-traps.md', 'docs/workflow/checklists/plot-criteria.md', 'docs/workflow/checklists/plot-guidelines.md', 'docs/workflow/checklists/plot-naming.md', 'docs/workflow/checklists/reproduction-closure.md', 'docs/workflow/checklists/troubleshooting.md', 'docs/workflow/checklists/validation.md', 'docs/workflow/checklists/verification-ladder.md', 'docs/workflow/checklists/verification-panel.md', 'docs/workflow/reference/effmap-folding.md', 'docs/workflow/reference/example-rivet-ewk-path.md', 'docs/workflow/reference/failed-stage-review.md', 'docs/workflow/reference/initialized-settings-retained.md', 'docs/workflow/reference/native-pipeline.md', 'docs/workflow/reference/named-scans.md', 'docs/workflow/reference/pdf-variations.md', 'docs/workflow/reference/physics-review.md', 'docs/workflow/reference/science-review.md', 'docs/workflow/reference/scientific-studies.md', 'docs/workflow/reference/scoped-workflows.md', 'docs/workflow/reference/workspace-combination-study.md', 'docs/workflow/start.md', 'docs/workflow/steps/01-environment.md', 'docs/workflow/steps/02-inputs.md', 'docs/workflow/steps/03-generate.md', 'docs/workflow/steps/04-analyze.md', 'docs/workflow/steps/05-visualize.md', 'docs/workflow/steps/06-acquire-data.md', 'docs/workflow/steps/07-exclude.md', 'docs/workflow/steps/08-scan.md', 'docs/workflow/steps/09-verify.md', 'environment/README.md', 'docs/workflow/reference/scientific-context-continuation.md', 'docs/workflow/reference/sfitter-source-context.md', 'docs/reference/agentrivet-construction.md', 'docs/reference/amplitude-reweighting.md', 'docs/reference/manuscript-method-transfer.md', 'docs/reference/manuscript-production.md', 'docs/reference/staged-manuscript-authoring.md', 'docs/reference/model-bound-diagrams.md', 'docs/workflow/reference/research-orchestration.md', 'docs/workflow/reference/data-read-outcomes.md', 'docs/workflow/reference/literature-context.md', 'docs/workflow/reference/literature-discovery.md', 'docs/workflow/reference/sn-jnl-publication.md', 'docs/workflow/reference/task-completion.md', 'docs/workflow/reference/result-templates.md', 'docs/reference/figures-and-comparison.md', 'docs/reference/inference-engines.md', 'docs/reference/execution-backends.md', 'docs/reference/batch-allocations.md', 'docs/reference/roles.md', 'docs/reference/challenge-operations.md', 'docs/reference/models-and-normalization.md', 'docs/reference/event-production.md', 'docs/reference/tool-status.md', 'docs/reference/statistics-core.md', 'docs/workflow/checklists/independent-numerics.md', 'docs/workflow/reference/width-input-materialization.md', 'docs/reference/mass-width-grid-recipes.md', 'docs/reference/cross-section-conventions.md', 'docs/workflow/reference/provider-policy.md', 'docs/workflow/checklists/conformance.md', 'docs/workflow/reference/supplied-document-builds.md')


def workflow_instruction_path(logical: str, *, source_root=None) -> Path:
    """Resolve a curated logical ID; an explicit source root remains strict.

    Existing checkout docs take precedence, then installed bundled resources.
    Auxiliary research and historical-evidence links require their checkout.
    """
    if logical not in WORKFLOW_INSTRUCTIONS:
        raise ValueError("unknown packaged workflow instruction")
    package = Path(__file__).resolve().parent
    root = (Path(source_root).absolute() if source_root is not None else
            package.parent.parent if package.parent.name == "src" else None)
    if root is not None and (source_root is not None or (root / logical).is_file()):
        path = root / logical
    else:
        path = package_data_path("workflow", logical)
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise FileNotFoundError("Workflow instruction is missing: " + str(path))
    return path


def workflow_instruction(logical: str, *, source_root=None) -> dict:
    """One bounded observed instruction with its original logical name."""
    path = workflow_instruction_path(logical, source_root=source_root)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > 256 * 1024:
        raise ValueError("bounded regular workflow instruction required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("workflow instruction changed before read")
        raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024 or identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("workflow instruction changed during read")
    if identity(path.lstat()) != identity(before) or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("workflow instruction changed after read")
    return {"logical_path": logical, "path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw), "role": "operational instructions; no execution or scientific acceptance authority"}


def main_checkout(root: str | Path | None = None) -> Path | None:
    """The main checkout of a linked git worktree, read from the worktree's `.git` file.

    Returns None for a main checkout, an installed package, or anything that is not a
    linked worktree. git itself is not invoked.
    """
    root = Path(root) if root is not None else repository_root()
    if root is None:
        return None
    marker = root / ".git"
    try:
        if not marker.is_file():
            return None
        line = marker.read_text().splitlines()[0]
    except (OSError, IndexError):
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = Path(line.split(":", 1)[1].strip())
    gitdir = gitdir if gitdir.is_absolute() else (root / gitdir)
    try:
        common = Path((gitdir / "commondir").read_text().splitlines()[0].strip())
    except (OSError, IndexError):
        return None
    common = (common if common.is_absolute() else gitdir / common).resolve()
    main = common.parent if common.name == ".git" else None
    return main if main is not None and main.resolve() != root.resolve() else None


def shared_native_build() -> Path:
    """The per-user shared toolchain location: $XDG_DATA_HOME/ravel-native, by default
    ~/.local/share/ravel-native."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base).expanduser() / "ravel-native"


def _native_roots(start=None) -> list[Path]:
    root = repository_root(start) if start is not None else repository_root()
    root = root or (Path(start) if start is not None else Path.cwd())
    roots = [root]
    main = main_checkout(root)
    if main is not None:
        roots.append(main)
    return roots


def native_build_candidates(start=None) -> list[Path]:
    """Search order for the native toolchain prefix (first existing directory wins):
    this checkout's stages/01-event-generation/build, then its native/build; the same two
    in the main checkout when this is a linked git worktree; then shared_native_build()."""
    out = []
    for root in _native_roots(start):
        out += [root / "stages/01-event-generation/build", root / "native/build"]
    return out + [shared_native_build()]


def _native_prefix_choice(start=None) -> tuple[Path, bool]:
    """(prefix, explicitly chosen). Same order as native/scripts/paths.sh.

    RAVEL_NATIVE_BUILD, then the installer's pointer file .ravel/native-prefix (this
    checkout's, then the main checkout's for a linked worktree), then the first existing
    directory in native_build_candidates(), then the conventional <checkout>/native/build.
    """
    override = os.environ.get("RAVEL_NATIVE_BUILD")
    if override:
        return Path(override).expanduser().resolve(), True
    for root in _native_roots(start):
        pointer = root / ".ravel/native-prefix"
        if pointer.is_file():
            lines = pointer.read_text(encoding="utf-8").splitlines()
            if lines and lines[0].strip():
                return Path(lines[0].strip()).expanduser().resolve(), True
    candidates = native_build_candidates(start)
    found = next((c for c in candidates if c.is_dir()), None)
    return (found if found is not None else candidates[1]), False


def native_build_root(start=None) -> Path:
    """Locate native tools without relocating an existing installation.

    RAVEL_NATIVE_BUILD or the installer's pointer file choose the prefix. Otherwise the
    first existing directory in native_build_candidates() is used, so a linked worktree
    shares its main checkout's toolchain. With nothing installed, the conventional
    <checkout>/native/build is returned.
    """
    return _native_prefix_choice(start)[0]


def native_binary(name: str, start=None) -> Path:
    """Find a generated native executable; these binaries are never wheel contents.

    RAVEL_NATIVE_BIN wins; an explicitly chosen prefix keeps its programs in <prefix>/bin.
    Otherwise native/build/bin of this checkout, then of the main checkout, then
    <native build>/bin and the shared location's bin are searched.
    """
    if Path(name).name != name:
        raise ValueError("native binary name must be a filename")
    override = os.environ.get("RAVEL_NATIVE_BIN")
    if override:
        return Path(override).expanduser().resolve() / name
    prefix, chosen = _native_prefix_choice(start)
    if chosen:
        return prefix / "bin" / name
    roots = _native_roots(start)
    dirs = [r / "native/build/bin" for r in roots]
    dirs += [prefix / "bin", shared_native_build() / "bin"]
    chosen_dir = (next((d for d in dirs if (d / name).exists()), None)
                  or next((d for d in dirs if d.is_dir()), None) or dirs[0])
    return chosen_dir / name


def module_command(module: str, *args: object, python=None) -> list[str]:
    """Invoke the same package with an optional external Python interpreter.

    The one package bootstrap works for editable and ordinary installations, and
    for native conda interpreters without installing replay dependencies there.
    A sequence may be supplied for a prefix such as conda run -n rivet python.
    """
    prefix = ([sys.executable] if python is None else
              [str(python)] if isinstance(python, (str, Path)) else list(python))
    return [*prefix, str(Path(__file__).with_name("_bootstrap.py")), module,
            *(str(arg) for arg in args)]
