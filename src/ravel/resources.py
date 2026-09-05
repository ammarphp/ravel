"""Explicit distribution resource selection shared by the build and editable install."""
from pathlib import Path

FAST_RUN = "trial-runs/2026-06-08_ATLAS_2016_I1458270_squark-pair"
ENGINE_FILES = (
    "trial-runs/_infrastructure/validate_task_contract.py",
    "trial-runs/_infrastructure/pyhf_exclude.py",
    "trial-runs/_infrastructure/validate_cutflow.py",
    "framework/benchmark/run_benchmark.py",
    "framework/benchmark/cases.json",
    "framework/benchmark/results.json",
)
FAST_FILES = (
    "RESULT.md", "provenance.json", "outputs/sr_yields_fitted.json",
    "outputs/sr_yields.json", "outputs/squark.yoda",
    "outputs/pyhf_exclusion/exclusion.json",
    "plots/ATLAS_2016_I1458270/named/ATLAS_2016_I1458270__d04-x01-y01__meff-incl_SR-2jl.png",
)


def payload_files(root: Path) -> list[str]:
    """Return the small allowlist; exclude logs, generated outputs, and other trials."""
    selected = [*ENGINE_FILES, *(f"{FAST_RUN}/{name}" for name in FAST_FILES)]
    tables = root / FAST_RUN / "outputs/hepdata/tables/HEPData-ins1458270-v1-yaml"
    if not (tables / "submission.yaml").is_file():
        raise FileNotFoundError(f"replay bundle requires {tables / 'submission.yaml'}")
    selected.extend(str(path.relative_to(root)) for path in sorted(tables.glob("*.yaml")))
    for relative in selected:
        if not (root / relative).is_file():
            raise FileNotFoundError(f"replay bundle requires {relative}")
    return selected


def resource_root() -> Path:
    """Wheels use their payload; source/editable runs use the checkout."""
    bundled = Path(__file__).resolve().parent / "_payload"
    if bundled.is_dir():
        return bundled
    source = Path(__file__).resolve().parents[2]
    if (source / "pyproject.toml").is_file() and all((source / f).is_file() for f in ENGINE_FILES):
        return source
    raise FileNotFoundError("Ravel's bundled engines are missing. Reinstall the ravel-hep wheel.")
