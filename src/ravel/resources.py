"""The data-only, curated replay bundle shared by source and installed commands."""
from pathlib import Path

from .evidence_layout import public_path, resolve
from .paths import package_data_path, repository_root

FAST_RUN = "trial-runs/2026-06-08_ATLAS_2016_I1458270_squark-pair"
FAST_FILES = (
    "RESULT.md", "provenance.json", "outputs/sr_yields_fitted.json",
    "outputs/sr_yields.json", "outputs/squark.yoda",
    "outputs/pyhf_exclusion/exclusion.json",
    "plots/ATLAS_2016_I1458270/named/ATLAS_2016_I1458270__d04-x01-y01__meff-incl_SR-2jl.png",
)


def payload_files(root: Path) -> list[str]:
    """Select replay data only; implementation code is the ordinary ravel package."""
    selected = ["benchmarks/cases.json", "benchmarks/results.json", "evidence/collections.json",
                *(f"{FAST_RUN}/{name}" for name in FAST_FILES)]
    tables_relative = f"{FAST_RUN}/outputs/hepdata/tables/HEPData-ins1458270-v1-yaml"
    tables = resolve(root, tables_relative)
    if not (tables / "submission.yaml").is_file():
        raise FileNotFoundError(f"replay bundle requires {tables / 'submission.yaml'}")
    selected.extend(f"{tables_relative}/{path.name}" for path in sorted(tables.glob("*.yaml")))
    for relative in selected:
        if not resolve(root, relative).is_file():
            raise FileNotFoundError(f"replay bundle requires {relative}")
    return sorted(public_path(relative, root) for relative in selected)


def resource_root() -> Path:
    """Locate installed replay data or source evidence without copying engine code."""
    bundled = package_data_path("replay")
    if (bundled / "benchmarks/cases.json").is_file():
        return bundled
    source = repository_root()
    if source is not None and (source / "benchmarks/cases.json").is_file():
        return source
    raise FileNotFoundError("Ravel's replay data is missing. Reinstall the ravel-hep wheel.")
