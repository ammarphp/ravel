"""Explicit, byte-preserving archive-to-public layout shared by export and replay.

Collection names describe public evidence. Original run IDs and paths remain in
the registry and the records themselves; this module never rewrites their bytes.
Only the committed registry determines shipping policy. Filesystem validation is
deliberately independent of optional scientific dependencies.
"""
from fnmatch import fnmatchcase
import json
from pathlib import Path, PurePosixPath
import re


REGISTRY = "evidence/collections.json"


def normalized(relative):
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or "\0" in relative or PurePosixPath(relative).is_absolute()
            or any(p in ("", ".", "..") for p in relative.split("/"))):
        raise ValueError(f"path must be normalized and repository-relative: {relative!r}")
    return relative


def safe_path(root, relative):
    """Resolve no symlinks, including a symlink pointing back inside the tree."""
    normalized(relative)
    root = Path(root).resolve()
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p != root):
        raise ValueError(f"path must not contain symlinks: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"path escapes repository: {relative}")
    return path


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate registry key: {key}")
        result[key] = value
    return result


def _patterns(values, label, nonempty=False):
    if (not isinstance(values, list) or (nonempty and not values)
            or any(not isinstance(v, str) for v in values)
            or len(set(values)) != len(values)):
        raise ValueError(f"{label} must be a list of unique path patterns")
    for value in values:
        normalized(value)


def load_registry(root):
    registry = json.loads(safe_path(root, REGISTRY).read_text(), object_pairs_hook=_unique)
    if (not isinstance(registry, dict) or set(registry) != {"schema_version", "collections", "distribution"}
            or type(registry.get("schema_version")) is not int or registry["schema_version"] != 1):
        raise ValueError("invalid evidence layout schema; expected integer version 1")
    collections = registry["collections"]
    if not isinstance(collections, list) or not collections:
        raise ValueError("collections must be a nonempty list")
    sources, destinations = [], []
    fields = {"source", "destination", "source_run_id", "title", "kind", "include", "exclude"}
    for c in collections:
        if not isinstance(c, dict) or set(c) != fields:
            raise ValueError("invalid evidence collection fields")
        for field in ("source", "destination"):
            normalized(c[field])
        if (not c["source"].startswith("trial-runs/") or c["source"].count("/") != 1
                or c["source_run_id"] != c["source"].split("/")[1]):
            raise ValueError("collection source must identify one original trial run")
        if not re.fullmatch(r"evidence/(benchmarks|scans|native-validation|case-studies)/[a-z0-9]+(?:-[a-z0-9]+)*", c["destination"]):
            raise ValueError("collection destination must use the public evidence layout")
        if not isinstance(c["title"], str) or not c["title"].strip():
            raise ValueError("collection title must be nonempty")
        if c["kind"] not in ("benchmark", "scan", "native-validation", "case-study"):
            raise ValueError("unknown collection kind")
        _patterns(c["include"], "include", nonempty=True)
        _patterns(c["exclude"], "exclude")
        sources.append(c["source"].casefold())
        destinations.append(c["destination"].casefold())
    for paths in (sources, destinations):
        if len(set(paths)) != len(paths) or any(a.startswith(b + "/") for a in paths for b in paths if a != b):
            raise ValueError("collection paths collide or overlap")
    distribution = registry["distribution"]
    if not isinstance(distribution, dict) or set(distribution) != {"files", "extra_files", "trees", "exclude"}:
        raise ValueError("invalid distribution selection")
    for field, values in distribution.items():
        _patterns(values, "distribution " + field)
        if field != "exclude" and any(any(ch in v for ch in "*?[") for v in values):
            raise ValueError("distribution roots must be literal paths")
    return registry


def _translate(relative, registry, origin, target):
    normalized(relative)
    for c in registry["collections"]:
        prefix = c[origin]
        if relative == prefix or relative.startswith(prefix + "/"):
            return c[target] + relative[len(prefix):]
    return relative


def public_path(relative, root):
    return _translate(relative, load_registry(root), "source", "destination")


def source_path(relative, root):
    return _translate(relative, load_registry(root), "destination", "source")


def resolve(root, relative):
    """Find an explicit registry path in either a source checkout or public bundle.

    An existing direct path always wins. Missing unregistered files remain missing;
    the resolver never invents inputs or searches another checkout.
    """
    direct = safe_path(root, relative)
    if direct.exists() or not safe_path(root, REGISTRY).is_file():
        return direct
    registry = load_registry(root)
    for origin, target in (("source", "destination"), ("destination", "source")):
        alternate = _translate(relative, registry, origin, target)
        if alternate != relative:
            return safe_path(root, alternate)
    return direct


def _matches(relative, patterns):
    # Shell-style '*' stays within one path segment. Only an explicit '**' may
    # recurse: output/*.txt must never select event dumps in output/PROC_*/....
    def match(parts, pattern):
        if not pattern:
            return not parts
        if pattern[0] == '**':
            return match(parts, pattern[1:]) or bool(parts) and match(parts[1:], pattern)
        return bool(parts) and fnmatchcase(parts[0], pattern[0]) and match(parts[1:], pattern[1:])
    return any(match(relative.split('/'), pattern.split('/')) for pattern in patterns)


def _is_shipped(relative, registry):
    relative = _translate(relative, registry, "destination", "source")
    for c in registry["collections"]:
        if relative.startswith(c["source"] + "/"):
            suffix = relative[len(c["source"]) + 1:]
            return _matches(suffix, c["include"]) and not _matches(suffix, c["exclude"])
    d = registry["distribution"]
    if _matches(relative, d["exclude"]):
        return False
    return (relative in d["files"] or relative in d["extra_files"]
            or any(relative == tree or relative.startswith(tree + "/") for tree in d["trees"]))


def is_shipped(relative, root):
    return _is_shipped(relative, load_registry(root))


def selected_files(root):
    """Return the entire explicit export selection, rejecting destination collisions."""
    registry = load_registry(root)
    candidates = set()
    d = registry["distribution"]
    for relative in d["files"] + d["extra_files"]:
        if safe_path(root, relative).is_file():
            candidates.add(relative)
    roots = d["trees"] + [c["source"] for c in registry["collections"]]
    for relative in roots:
        base = safe_path(root, relative)
        if not base.exists():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(Path(root)).as_posix()
            if not _is_shipped(rel, registry):
                continue
            if path.is_symlink():
                raise ValueError(f"export must not contain symlinks: {rel}")
            if path.is_file():
                candidates.add(rel)
    mapped, seen = [], {}
    for source in sorted(candidates):
        destination = _translate(source, registry, "source", "destination")
        key = destination.casefold()
        if key in seen:
            raise ValueError(f"export destination collision: {source} and {seen[key]}")
        safe_path(root, source)
        seen[key] = source
        mapped.append((source, destination))
    return mapped
