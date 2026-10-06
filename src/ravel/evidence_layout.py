"""Explicit, byte-preserving archive-to-public layout shared by the evidence checks and replay.

Collection names describe public evidence. Original run IDs and paths remain in
the registry and the records themselves; this module never rewrites their bytes.
Only the committed registry determines the selection. Filesystem validation is
deliberately independent of optional scientific dependencies.

A tree that carries `evidence/export-provenance.json` and a registry with only the distribution
selection is a distributed tree, as this repository is, and the checks run in their public mode.
The curation record (`evidence/curation.json`) maps each record whose wording was curated from its
original identity to its curated one (`curation_errors`, `pin_matches`).
"""
import hashlib
from fnmatch import fnmatchcase
import json
from pathlib import Path, PurePosixPath
import re


REGISTRY = "evidence/collections.json"
# The provenance record of a distributed tree, excluded from every selection; public-mode checks key on it.
PUBLIC_MARKER = "evidence/export-provenance.json"
DISTRIBUTION_FIELDS = {"files", "extra_files", "trees", "exclude"}
# Optional registry fields beyond the selection (see declarations); a distributed registry has none.
SOURCE_PATTERN_FIELDS = ("internal", "internal_exclude")
# Optional settings of the checks (see source_settings).
SOURCE_SETTINGS_FIELD = "source_checks"
# The shipped record of curated wording in hash-pinned and historical records (see curation_errors).
CURATION_RECORD = "evidence/curation.json"
CURATION_FIELDS = {"original_sha256", "original_bytes", "curated_sha256", "curated_bytes", "pinned_by",
                   "change", "reason"}
_SHA256 = re.compile(r"[0-9a-f]{64}")


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
    """The registry as distributed: every undistributed declaration is dropped. Collections and the
    shipped selection are unchanged."""
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
    repository and evidence checks; None for a tree whose registry declares no settings files, such
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
    """Find an explicit registry path in either its original run layout or its public evidence layout.

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


def _is_internal(relative, registry):
    """Undistributed material (`distribution.internal`), named by its public (destination) path."""
    destination = _translate(relative, registry, "source", "destination")
    return _matches(destination, registry["distribution"].get("internal", []))


def _is_shipped(relative, registry, include_internal=False):
    relative = _translate(relative, registry, "destination", "source")
    if not include_internal and _is_internal(relative, registry):
        return False
    for c in registry["collections"]:
        if relative.startswith(c["source"] + "/"):
            suffix = relative[len(c["source"]) + 1:]
            return _matches(suffix, c["include"]) and not _matches(suffix, c["exclude"])
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
        paths = {binding["public_path"] for binding in record["file_bindings_before_evidence_index_render"]}
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


def selected_files(root, include_internal=False):
    """Return the entire explicit export selection, rejecting destination collisions.

    With include_internal, return the checked surface of a tree that declares undistributed
    material instead: the same selection plus that (internal) material.
    """
    registry = load_registry(root)
    candidates = set()
    d = registry["distribution"]
    for relative in d["files"] + d["extra_files"]:
        if safe_path(root, relative).is_file() and (include_internal or not _is_internal(relative, registry)):
            candidates.add(relative)
    roots = d["trees"] + [c["source"] for c in registry["collections"]]
    for relative in roots:
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
        destination = _translate(source, registry, "source", "destination")
        key = destination.casefold()
        if key in seen:
            raise ValueError(f"export destination collision: {source} and {seen[key]}")
        safe_path(root, source)
        seen[key] = source
        mapped.append((source, destination))
    return mapped


# --------------------------------------------------------------------------------------------
# Curated wording in hash-pinned and historical records
# --------------------------------------------------------------------------------------------

def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_curation_record(root):
    """The shipped curation record, {public path: entry}, or {} for a tree without one.

    A curated record is a hash-pinned or historical file whose wording was changed for the
    public distribution. Its entry maps the original identity (`original_sha256`,
    `original_bytes`) to the curated one, names the records that pinned the original digest
    (`pinned_by`), and says what wording changed (`change`) and why (`reason`). A pin that
    recorded the original digest accepts the curated file through its entry (`pin_matches`)."""
    path = safe_path(root, CURATION_RECORD)
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(), object_pairs_hook=_unique)
    if (not isinstance(document, dict) or set(document) != {"schema_version", "purpose", "records"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or not isinstance(document["purpose"], str) or not isinstance(document["records"], dict)):
        raise ValueError(f"{CURATION_RECORD}: invalid curation record schema; expected version 1")
    for relative, entry in document["records"].items():
        normalized(relative)
        label = f"{CURATION_RECORD}: {relative}"
        if not isinstance(entry, dict) or set(entry) != CURATION_FIELDS:
            raise ValueError(f"{label}: an entry needs exactly {sorted(CURATION_FIELDS)}")
        for field in ("original_sha256", "curated_sha256"):
            if not isinstance(entry[field], str) or not _SHA256.fullmatch(entry[field]):
                raise ValueError(f"{label}: {field} must be a lower-case sha256")
        for field in ("original_bytes", "curated_bytes"):
            if type(entry[field]) is not int or entry[field] < 0:
                raise ValueError(f"{label}: {field} must be a byte count")
        if entry["original_sha256"] == entry["curated_sha256"]:
            raise ValueError(f"{label}: a curation must change the record")
        for field in ("change", "reason"):
            if not isinstance(entry[field], str) or not entry[field].strip():
                raise ValueError(f"{label}: {field} must say what changed and why")
        pins = entry["pinned_by"]
        if not isinstance(pins, list) or len(set(pins)) != len(pins):
            raise ValueError(f"{label}: pinned_by must be a list of unique paths")
        for pin in pins:
            normalized(pin)
    return document["records"]


def pin_matches(root, relative, recorded, actual, record=None):
    """True when a file whose digest a record pinned as `recorded` now has digest `actual`: the
    file is unchanged, or it is the curated copy that the curation record maps from exactly
    that original. A pin may name the file by its source path; the record names public paths."""
    if actual == recorded:
        return True
    try:
        record = load_curation_record(root) if record is None else record
        entry = record.get(relative) or record.get(public_path(relative, root))
    except (ValueError, OSError):
        return False
    return bool(entry) and entry["original_sha256"] == recorded and entry["curated_sha256"] == actual


def curation_errors(root):
    """Every disagreement between the shipped curation record and the files it names.

    In every tree, each entry's `pinned_by` records must still carry its original digest, so the
    original identity stays traceable. In a tree whose registry declares no undistributed
    material (a distributed tree), each curated file must have exactly its curated identity. A tree
    that declares it may keep some records in their original form; its own tooling verifies the
    edits behind the record there."""
    root = Path(root)
    try:
        if not safe_path(root, CURATION_RECORD).is_file():
            return []
        record = load_curation_record(root)
        source_checkout = is_source_checkout(root)
    except (ValueError, OSError) as exc:
        return [str(exc)]
    errors = []
    for destination, entry in sorted(record.items()):
        for pin in entry["pinned_by"]:
            try:
                text = resolve(root, pin).read_text(encoding="utf-8")
            except (OSError, ValueError):
                errors.append(f"{destination}: {pin}, which pins its original digest, is unreadable")
                continue
            if entry["original_sha256"] not in text:
                errors.append(f"{destination}: {pin} does not carry its original digest")
        if source_checkout:
            continue
        try:
            data = resolve(root, destination).read_bytes()
        except (OSError, ValueError):
            errors.append(f"{destination}: curated record missing")
            continue
        if (_sha256(data), len(data)) != (entry["curated_sha256"], entry["curated_bytes"]):
            errors.append(f"{destination}: differs from its curated identity in {CURATION_RECORD}")
    return errors


def internal_mentions(text, patterns):
    """Literal path prefixes of the given registry patterns that occur in text."""
    found = []
    for pattern in patterns:
        literal = re.split(r"[*?\[]", pattern, maxsplit=1)[0]
        if literal and literal in text:
            found.append(literal)
    return found
