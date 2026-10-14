"""Explicit, byte-preserving source-to-public distribution layout.

Only the committed registry (`distribution.json`) determines the selection. Filesystem validation
is deliberately independent of optional scientific dependencies.

In a tree that carries `export-provenance.json` and a registry with only the distribution
selection (a distributed tree), the checks run in their public mode.
"""
from fnmatch import fnmatchcase
import json
from pathlib import Path, PurePosixPath
import re


REGISTRY = "distribution.json"
# The provenance record of a distributed tree, excluded from every selection; public-mode checks key on it.
PUBLIC_MARKER = "export-provenance.json"
DISTRIBUTION_FIELDS = {"files", "extra_files", "trees", "exclude"}
# Optional registry fields beyond the selection (see declarations); a distributed registry has none.
SOURCE_PATTERN_FIELDS = ("internal", "internal_exclude")
# Optional settings of the checks (see source_settings).
SOURCE_SETTINGS_FIELD = "source_checks"


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
    if (not isinstance(registry, dict) or set(registry) != {"schema_version", "distribution"}
            or type(registry.get("schema_version")) is not int or registry["schema_version"] != 2):
        raise ValueError("invalid distribution registry schema; expected integer version 2")
    distribution = registry["distribution"]
    if not isinstance(distribution, dict) or not DISTRIBUTION_FIELDS <= set(distribution):
        raise ValueError("invalid distribution selection")
    for field, values in distribution.items():
        if field in DISTRIBUTION_FIELDS or field in SOURCE_PATTERN_FIELDS:
            _patterns(values, "distribution " + field)
            if (field not in ("exclude",) + SOURCE_PATTERN_FIELDS
                    and any(any(ch in v for ch in "*?[") for v in values)):
                raise ValueError("distribution roots must be literal paths")
            continue
        # An optional settings file: one literal path among the files that `internal` names.
        if not isinstance(values, str) or any(ch in values for ch in "*?["):
            raise ValueError(f"distribution {field} must be one literal path")
        normalized(values)
        if not _matches(values, distribution.get("internal", [])):
            raise ValueError(f"distribution {field} must name an undistributed file (distribution.internal)")
    return registry


def source_fields(distribution):
    """The undistributed declarations (fields beyond the selection) in a registry's distribution block."""
    return [field for field in distribution if field not in DISTRIBUTION_FIELDS]


def settings_files(distribution):
    """{field: path} of the optional settings files a registry declares."""
    return {field: value for field, value in distribution.items()
            if field not in DISTRIBUTION_FIELDS and field not in SOURCE_PATTERN_FIELDS}


def public_registry(registry):
    """The registry as distributed: every undistributed declaration is dropped. The shipped
    selection is unchanged."""
    projected = json.loads(json.dumps(registry))
    for field in source_fields(registry["distribution"]):
        projected["distribution"].pop(field, None)
    return projected


def public_registry_bytes(root):
    """The distributed registry file, formatted like the committed one."""
    return (json.dumps(public_registry(load_registry(root)), indent=2, ensure_ascii=False) + "\n").encode()


def is_source_checkout(root):
    """True when the tree's registry declares undistributed material (never in a distributed tree)."""
    if not safe_path(root, REGISTRY).is_file():
        return False
    return bool(source_fields(load_registry(root)["distribution"]))


def source_settings(root):
    """The optional settings of the checks, or {} for a tree whose registry declares none (a
    distributed tree, such as this repository). A declared file that is missing or
    invalid is an error, never an empty setting."""
    if not safe_path(root, REGISTRY).is_file():
        return {}
    relative = load_registry(root)["distribution"].get(SOURCE_SETTINGS_FIELD)
    if relative is None:
        return {}
    document = json.loads(safe_path(root, relative).read_text(), object_pairs_hook=_unique)
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
            or document["schema_version"] != 1):
        raise ValueError(f"{relative}: invalid source settings; expected schema_version 1")
    return document


def source_module(root):
    """The layout module that an optional settings file names (`layout_module`), for further
    repository checks; None for a tree whose registry declares no settings files, such
    as this repository. A tree that declares settings
    but does not name the module, or names a missing file, is an error rather than a silently
    weaker check."""
    if not safe_path(root, REGISTRY).is_file() or not settings_files(load_registry(root)["distribution"]):
        return None
    relative = source_settings(root).get("layout_module")
    if not isinstance(relative, str):
        raise ValueError(f"{REGISTRY}: a registry that declares settings files must name a layout module in them")
    path = safe_path(root, normalized(relative))
    if not path.is_file():
        raise ValueError(f"{relative}: the declared layout module is missing")
    import importlib.util
    spec = importlib.util.spec_from_file_location("ravel_source_layout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_path(relative, root=None):
    """A file's public path. The distribution keeps every selected file at its source path."""
    return normalized(relative)


def source_path(relative, root=None):
    return normalized(relative)


def resolve(root, relative):
    """The repository path of a registry-relative file; the resolver never searches elsewhere."""
    return safe_path(root, relative)


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


def _is_internal(relative, registry):
    """Undistributed material (`distribution.internal`)."""
    return _matches(relative, registry["distribution"].get("internal", []))


def _is_shipped(relative, registry, include_internal=False):
    if not include_internal and _is_internal(relative, registry):
        return False
    d = registry["distribution"]
    if _matches(relative, d["exclude"]) or _matches(relative, d.get("internal_exclude", [])):
        return False
    return (relative in d["files"] or relative in d["extra_files"]
            or any(relative == tree or relative.startswith(tree + "/") for tree in d["trees"]))


def is_shipped(relative, root):
    return _is_shipped(relative, load_registry(root))


def is_internal(relative, root):
    """True for undistributed material that the registry would otherwise select."""
    registry = load_registry(root)
    return _is_internal(relative, registry) and _is_shipped(relative, registry, include_internal=True)


def declared_internal(relative, root):
    """True for any path that the registry's internal patterns name (selected or not)."""
    return _is_internal(relative, load_registry(root))


def internal_patterns(root):
    return list(load_registry(root)["distribution"].get("internal", []))


def is_public_tree(root):
    """A distributed tree: it carries the generated provenance record and a registry without
    undistributed declarations. A registry that declares them never counts as public, so a stray
    provenance file in such a tree never switches the checks to their public mode."""
    marker = Path(root) / PUBLIC_MARKER
    if not marker.is_file() or marker.is_symlink():
        return False
    try:
        distribution = load_registry(root)["distribution"]
    except (ValueError, OSError):
        return False
    return not source_fields(distribution)


def exported_paths(root):
    """In a public tree, every path its provenance record binds; otherwise, or when the record
    lists no file bindings, None."""
    if not is_public_tree(root):
        return None
    try:
        record = json.loads((Path(root) / PUBLIC_MARKER).read_text())
        paths = {binding["public_path"] for binding in record["file_bindings"]}
    except (ValueError, OSError, KeyError, TypeError):
        return None
    return paths | {PUBLIC_MARKER} if paths else None


def is_withheld(relative, root):
    """A file this tree's checks must not expect to find. In a public tree: any path its provenance
    record does not bind. In a tree whose registry declares undistributed material: that material."""
    exported = exported_paths(root)
    if exported is not None:
        return relative not in exported
    if is_public_tree(root):
        return False
    return is_internal(relative, root)


def selected_files(root, include_internal=False, *, registry=None):
    """Return the entire explicit export selection as (source, public) pairs, rejecting collisions.

    With include_internal, return the checked surface of a tree that declares undistributed
    material instead: the same selection plus that (internal) material.
    """
    registry = load_registry(root) if registry is None else registry
    candidates = set()
    d = registry["distribution"]
    for relative in d["files"] + d["extra_files"]:
        if safe_path(root, relative).is_file() and (include_internal or not _is_internal(relative, registry)):
            candidates.add(relative)
    for relative in d["trees"]:
        base = safe_path(root, relative)
        if not base.exists():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(Path(root)).as_posix()
            if not _is_shipped(rel, registry, include_internal):
                continue
            if path.is_symlink():
                raise ValueError(f"export must not contain symlinks: {rel}")
            if path.is_file():
                candidates.add(rel)
    mapped, seen = [], {}
    for source in sorted(candidates):
        destination = source
        key = destination.casefold()
        if key in seen:
            raise ValueError(f"export destination collision: {source} and {seen[key]}")
        safe_path(root, source)
        seen[key] = source
        mapped.append((source, destination))
    return mapped


def internal_mentions(text, patterns):
    """Literal path prefixes of the given registry patterns that occur in text."""
    found = []
    for pattern in patterns:
        literal = re.split(r"[*?\[]", pattern, maxsplit=1)[0]
        if literal and literal in text:
            found.append(literal)
    return found
