"""Installed MadGraph versions and selection of one by need.

Versions come from the toolchain manifest (native/setup/toolchain-manifest.json):
each MadGraph source checkout (a ``git`` step with a release tag) is paired with
the conda environment its options file names for LHAPDF. Selection never
downloads or builds anything; a version that is not installed is refused.
"""
from __future__ import annotations

import os
from pathlib import Path

from ravel.physics.beam_content import version_tuple


def installed_madgraph(prefix=None, *, document=None, repo=None):
    """Return MadGraph runtimes the manifest declares under ``prefix``.

    Each entry: version, tree, python, compiler, lhapdf_config, installed (bool).
    """
    from ravel.setup import manifest
    prefix = Path(prefix or os.environ.get("RAVEL_NATIVE_BUILD") or "")
    if not str(prefix):
        raise ValueError("RAVEL_NATIVE_BUILD is not set; the generator toolchain location is unknown")
    if document is None:
        document = manifest.read_json(manifest.manifest_path(repo))
    platform_key = manifest.detect_platform()
    values = manifest.variables(prefix, repo or manifest.repo_root(), platform_key)
    group = next((g for g in document["groups"] if g["id"] == "madgraph"), None)
    if group is None:
        raise ValueError("toolchain manifest has no madgraph group")
    steps = manifest.expand(group["steps"], values)
    sources = [s for s in steps if s["kind"] == "git" and "tag" in s]
    options = [s for s in steps if s["kind"] == "options_file"]
    result = []
    for source in sources:
        tree = Path(source["dest"])
        option = next((o for o in options if Path(o["path"]).is_relative_to(tree)), None)
        if option is None or "lhapdf_py3" not in option.get("values", {}):
            raise ValueError(f"manifest pairs no environment with {tree}")
        config = Path(option["values"]["lhapdf_py3"])
        env = config.parent.parent
        entry = {"version": source["tag"].lstrip("v"), "tree": str(tree), "python": str(env / "bin/python"),
                 "compiler": str(env / "bin/gfortran"), "lhapdf_config": str(config),
                 "source_commit": source.get("commit")}
        version_file = tree / "VERSION"
        entry["installed"] = all(Path(entry[k]).is_file() for k in ("python", "compiler", "lhapdf_config")) and (
            tree / "bin/mg5_aMC").is_file() and version_file.is_file()
        if entry["installed"]:
            observed = _version_file(version_file)
            if observed != entry["version"]:
                raise ValueError(f"{tree} reports MadGraph {observed}, the manifest pins {entry['version']}")
        result.append(entry)
    return sorted(result, key=lambda e: version_tuple(e["version"]))


def _version_file(path):
    for line in Path(path).read_text().splitlines():
        if line.strip().lower().startswith("version"):
            return line.split("=", 1)[1].strip()
    raise ValueError(f"MadGraph VERSION file has no version line: {path}")


def runtime_version(tree):
    """The version string of a MadGraph tree (its VERSION file)."""
    return _version_file(Path(tree) / "VERSION")


def select(requested, minimum, candidates):
    """Choose an installed runtime.

    ``requested`` is an exact version or ``"auto"``. ``auto`` picks the oldest
    installed version that meets ``minimum`` (None means any), so an ordinary
    process keeps the long-standing default and a process that needs the newer
    generator gets it. Returns (entry, record).
    """
    installed = [c for c in candidates if c["installed"]]
    floor = version_tuple(minimum) if minimum else (0, 0, 0)
    if requested != "auto":
        match = [c for c in candidates if c["version"] == requested]
        if not match:
            raise ValueError(f"MadGraph {requested} is not declared in the toolchain manifest "
                             f"(declared: {', '.join(c['version'] for c in candidates)})")
        if not match[0]["installed"]:
            raise ValueError(f"MadGraph {requested} is declared but not installed; run `ravel doctor`")
        if version_tuple(requested) < floor:
            raise ValueError(f"this process needs MadGraph {minimum} or later; {requested} was requested")
        chosen = match[0]
        reason = "requested version"
    else:
        eligible = [c for c in installed if version_tuple(c["version"]) >= floor]
        if not eligible:
            raise ValueError(f"no installed MadGraph meets the requirement {minimum or 'any'} "
                             f"(installed: {', '.join(c['version'] for c in installed) or 'none'}); run `ravel doctor`")
        chosen = eligible[0]
        reason = (f"oldest installed version meeting the minimum {minimum}" if minimum
                  else "oldest installed version; the process has no version requirement")
    record = {"name": "MadGraph5_aMC@NLO", "requested": requested, "minimum": minimum,
              "selected": chosen["version"], "reason": reason, "source_commit": chosen.get("source_commit"),
              "candidates": [{"version": c["version"], "installed": c["installed"]} for c in candidates]}
    return chosen, record
