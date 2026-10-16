"""Load, validate and expand the toolchain manifest (schema 2).

The manifest is data: groups of typed install steps and readiness checks,
named profiles, per-platform routes and pinned sources. This module turns it
into ordered, fully expanded step lists for one platform and prefix.
"""
from __future__ import annotations

import json
import hashlib
import copy
import os
from pathlib import Path
import platform as _platform
import re
from copy import deepcopy

SCHEMA_VERSION = 2
MAX_JSON_BYTES = 4 * 1024 * 1024
PLATFORMS = ("macos-arm64", "macos-x86_64", "linux-x86_64", "linux-aarch64")
ROUTES = ("native", "container", "remote", "manual", "unsupported")
STEP_KINDS = {
    "manual", "miniforge", "conda_env", "pip", "git", "archive", "download", "pdf_sets", "command",
    "container_pull", "container_build", "wrapper", "options_file", "link_children", "write_file",
    "verify_file", "container_run", "native_compile",
}
# Group qualification labels (tools-and-validation census 2.2): E qualified, S/I built but unqualified,
# E- failed, P not built.
QUALIFICATIONS = ("qualified", "built-unqualified", "failed", "not-built", "excluded", "tester-qualification")
CHECK_KINDS = {"file", "directory", "executable", "probe", "provider", "wolfram", "container_image",
               "site", "manual", "analysis_catalogue", "agent_cli"}
# Variables the engine defines for every step. Anything else in braces is an error.
ENGINE_VARIABLES = ("P", "REPO", "SUBDIR", "PLATFORM", "JOBS", "CONDA", "ENVS", "TOOLS", "BIN", "SHARE",
                    "LHAPDF_DATA", "DOWNLOADS", "CONFIG", "CONTAINERS", "HOST_PYTHON", "INSTALLER_PYTHON",
                    "CONTAINER_ENGINE", "OCI_PLATFORM", "LCG_VIEW")
CONDA_SUBDIRS = {"macos-arm64": "osx-arm64", "macos-x86_64": "osx-64",
                 "linux-x86_64": "linux-64", "linux-aarch64": "linux-aarch64"}
OCI_PLATFORMS = {"macos-arm64": "linux/arm64", "macos-x86_64": "linux/amd64",
                 "linux-x86_64": "linux/amd64", "linux-aarch64": "linux/arm64"}
_VARIABLE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SHELL_VARIABLE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
SM_PDF_SET_NAMES = (
    "PDF4LHC21_40_pdfas", "NNPDF40_nnlo_as_01180", "NNPDF40_nnlo_pdfas",
    "NNPDF40_nnlo_as_01160", "NNPDF40_nnlo_as_01200", "MSHT20nnlo_as118",
    "CT18ZNNLO", "NNPDF31_nnlo_as_0118", "ATLASpdf21_T3", "ABMP16_5_nnlo",
)


class ManifestError(ValueError):
    """The manifest or catalogue does not satisfy the schema."""


def _pairs(rows):
    out = {}
    for key, value in rows:
        if key in out:
            raise ManifestError("duplicate JSON key: " + key)
        out[key] = value
    return out


def read_json(path):
    """Strict bounded JSON: duplicate keys and NaN/Infinity are refused."""
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ManifestError("setup JSON exceeds 4 MiB: " + str(path))

    def constant(value):
        raise ManifestError("non-finite JSON value: " + value)

    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=constant)


def repo_root():
    """The source checkout: this file's own checkout, else RAVEL_ROOT or the cwd's."""
    here = Path(__file__).resolve().parents[3]
    if (here / "native/setup/toolchain-manifest.json").is_file():
        return here
    from ravel.paths import repository_root
    return repository_root() or here


def manifest_path(repo=None):
    return Path(repo or repo_root()) / "native/setup/toolchain-manifest.json"


def _fragment_files(repo):
    directory = Path(repo) / "native/setup/groups"
    _require(not directory.is_symlink(), str(directory) + ": symlink directory refused")
    if not directory.exists():
        return []
    _require(directory.is_dir(), str(directory) + ": directory required")
    files = []
    for path in sorted(directory.iterdir()):
        _require(not path.is_symlink(), str(path) + ": symlink refused")
        _require(path.is_file(), str(path) + ": regular file required")
        if path.name in ("README.md", "group.schema.json"):
            continue
        _require(path.suffix == ".json", str(path) + ": regular .json fragment required")
        files.append(path)
    return files


def _read_fragment(path):
    try:
        return read_json(path)
    except (ValueError, UnicodeError) as exc:
        raise ManifestError(str(path) + ": " + str(exc)) from exc


def _fragment_group(path, wrapper):
    where = str(path)
    _require(isinstance(wrapper, dict), where + ": fragment wrapper must be an object")
    _require(set(wrapper) <= {"group", "unreleased"},
             where + ": unknown wrapper key(s): " + ", ".join(sorted(set(wrapper) - {"group", "unreleased"})))
    group = wrapper.get("group")
    _require(isinstance(group, dict) and isinstance(group.get("id"), str) and group["id"],
             where + ": exactly one group object with an id required")
    gid = group["id"]
    if "unreleased" in wrapper:
        rows = wrapper["unreleased"]
        _require(isinstance(rows, dict) and set(rows) == {"groups", "operations"},
                 where + ": unreleased needs only groups and operations")
        _require(isinstance(rows["groups"], list) and len(rows["groups"]) == 1,
                 where + ": unreleased needs one own-group row for " + gid)
        row = rows["groups"][0]
        _require(isinstance(row, dict) and row.get("id") == gid,
                 where + ": unreleased row must name " + gid + ", got " + repr(row))
        _require(all(isinstance(row.get(k), str) and row[k] for k in ("check", "reason")),
                 where + ": unreleased check and reason required for " + gid)
        _require("display_terms" not in row or (isinstance(row["display_terms"], list)
                 and all(isinstance(t, str) for t in row["display_terms"])),
                 where + ": display_terms must be strings for " + gid)
        _require(set(row) <= {"id", "check", "reason", "display_terms"},
                 where + ": unknown unreleased group field for " + gid)
        _require(isinstance(rows["operations"], list), where + ": unreleased operations list required")
        for row in rows["operations"]:
            _require(isinstance(row, dict) and set(row) == {"mode", "groups"}
                     and isinstance(row.get("mode"), str) and row["mode"] and row.get("groups") == [gid],
                     where + ": unreleased operation must name only " + gid + ", got " + repr(row))
    return group


def _assemble(main, main_path, fragments):
    """Pure assembler, also used to verify a proposed structural split before writes."""
    document = copy.deepcopy(main)
    order = document.pop("group_order", None)
    # Old staged trees can be partial documents; with no fragments no expansion is needed.
    if not fragments and order is None:
        return document, {}
    inline = document.get("groups")
    _require(isinstance(inline, list), str(main_path) + ": groups list required")
    groups, sources = {}, {}

    def add(group, path):
        _require(isinstance(group, dict) and isinstance(group.get("id"), str), str(path) + ": group id required")
        gid = group["id"]
        _require(gid not in groups, f"duplicate group {gid}: {sources.get(gid)} and {path}")
        groups[gid], sources[gid] = group, Path(path)

    for group in inline:
        add(group, main_path)
    pending = []
    for path, wrapper in fragments:
        group = _fragment_group(path, wrapper)
        add(copy.deepcopy(group), path)
        pending.append((path, wrapper, group["id"]))
    for path, wrapper, gid in pending:
        _require(path.stem == gid, f"{path}: filename stem differs from group id {gid}")
        if "unreleased" in wrapper:
            held = document.setdefault("unreleased", {"groups": [], "operations": []})
            for key in ("groups", "operations"):
                for row in wrapper["unreleased"][key]:
                    identity = "id" if key == "groups" else "mode"
                    _require(not any(r.get(identity) == row.get(identity) for r in held.setdefault(key, [])),
                             f"{main_path} and {path}: duplicate unreleased {row.get(identity)} for {gid}")
                    held[key].append(copy.deepcopy(row))
    positioned = order if order is not None else [g["id"] for g in inline]
    _require(isinstance(positioned, list) and all(isinstance(g, str) for g in positioned)
             and len(set(positioned)) == len(positioned), str(main_path) + ": group_order must contain unique ids")
    _require(set(positioned) <= groups.keys(), str(main_path) + ": group_order names missing id(s): "
             + ", ".join(sorted(set(positioned) - groups.keys())))
    priority = positioned + [gid for _, _, gid in pending if gid not in positioned]
    priority += [gid for gid in groups if gid not in priority]
    for gid, group in groups.items():
        deps = group.get("depends_on", [])
        _require(isinstance(deps, list) and all(isinstance(d, str) for d in deps),
                 f"{sources[gid]}: {gid}: dependencies list required")
        missing = set(deps) - groups.keys()
        _require(not missing, f"{sources[gid]}: {gid}: unknown dependencies: " + ", ".join(sorted(missing)))
    ordered, remaining = [], list(priority)
    while remaining:
        ready = next((gid for gid in remaining if set(groups[gid].get("depends_on", [])) <= set(ordered)), None)
        _require(ready is not None, "dependency cycle: " + ", ".join(f"{gid} ({sources[gid]})" for gid in remaining))
        ordered.append(ready)
        remaining.remove(ready)
    document["groups"] = [groups[gid] for gid in ordered]
    checks = {}
    for gid in ordered:
        for check in groups[gid].get("checks", []):
            _require(isinstance(check, dict) and isinstance(check.get("id"), str) and check["id"],
                     f"{sources[gid]}: {gid}: check id required")
            cid = check["id"]
            _require(cid not in checks, f"duplicate check id {cid}: {checks.get(cid)} and {sources[gid]} ({gid})")
            checks[cid] = sources[gid]
    held = unreleased_groups(document)
    default = document.get("default")
    if pending:
        _require(isinstance(default, dict) and isinstance(default.get("groups"), list),
                 str(main_path) + ": default groups required for fragment expansion")
        additions = [gid for gid in ordered if gid in {g for _, _, g in pending}
                     and gid not in default["groups"] and gid not in held]
        default["groups"].extend(additions)
        if additions:
            from decimal import Decimal
            for gid in additions:
                _require(isinstance(groups[gid].get("size_gb"), (int, float)),
                         f"{sources[gid]}: {gid}: size_gb required")
            default["disk_gb"] = float(Decimal(str(default["disk_gb"]))
                                      + sum(Decimal(str(groups[g]["size_gb"])) for g in additions))
    return document, sources


def _tree_view(repo):
    path = manifest_path(repo)
    from ravel.setup.pin_sources import resolve
    from ravel.workflow.operation_registration import manifest_document, read_signatures
    document, sources = _assemble(read_json(path), path, [(p, _read_fragment(p)) for p in _fragment_files(repo)])
    try:
        document = manifest_document(document, read_signatures(Path(repo) / 'src/ravel/data/operation_signatures.json'))
    except (ValueError, UnicodeError) as exc:
        raise ManifestError(str(path) + ': ' + str(exc)) from exc
    return resolve(document, repo), sources


def view(root=None):
    """Merge one tree's main manifest and fragments without catalogue/full validation.

    Wrapper, source collision and dependency checks apply here; ``load`` additionally
    applies the complete schema, licence policy and PDF-set catalogue validator.
    Structural ``group_order`` metadata is consumed, never included in the result.
    """
    return _tree_view(Path(root or repo_root()))[0]


def canonical_sha256(document):
    """Digest the merged document with sorted keys and compact JSON separators."""
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def load(repo=None):
    """Read and validate the merged manifest plus its PDF-set catalogue."""
    repo = Path(repo or repo_root())
    document, sources = _tree_view(repo)
    catalog = read_json(repo / document.get("pdf_sets", "native/setup/pdf-sets.json"))
    try:
        validate(document, catalog)
    except ManifestError as exc:
        paths = {str(path) for gid, path in sources.items()
                 if re.search(r"(?<![a-zA-Z0-9_-])" + re.escape(gid) + r"(?![a-zA-Z0-9_-])", str(exc))}
        if not paths:
            # Some existing cross-group validators emit no group id in their message.
            paths = {f"{gid} ({path})" for gid, path in sources.items() if path != manifest_path(repo)}
            paths.add(str(manifest_path(repo)))
        raise ManifestError(str(exc) + " [source: " + ", ".join(sorted(paths)) + "]") from exc
    return document, catalog


def detect_platform(system=None, machine=None):
    """Return one of PLATFORMS, or raise for an unsupported host."""
    system = system or _platform.system()
    machine = (machine or _platform.machine()).lower()
    arch = {"arm64": "arm64", "aarch64": "aarch64", "x86_64": "x86_64", "amd64": "x86_64"}.get(machine)
    if system == "Darwin" and arch in ("arm64", "x86_64"):
        return "macos-" + arch
    if system == "Linux" and arch in ("x86_64", "aarch64"):
        return "linux-" + arch
    raise ManifestError(f"unsupported platform {system}/{machine}; RAVEL installs on macOS or Linux")


def route_for(group, platform_key):
    routes = group.get("routes", {})
    return routes.get(platform_key, routes.get("default", "native"))


def applies(item, platform_key):
    platforms = item.get("platforms")
    return platforms is None or platform_key in platforms


def default_disk_gb(manifest):
    return manifest["default"]["disk_gb"]


def by_id(manifest):
    return {group["id"]: group for group in manifest["groups"]}


def unreleased_groups(manifest):
    """Development recipes withheld from implicit release selection."""
    return {row['id'] for row in manifest.get('unreleased', {}).get('groups', [])}


def unreleased_operations(manifest):
    return {row['mode'] for row in manifest.get('unreleased', {}).get('operations', [])}


def release_mentions(manifest, value):
    """Does a display declaration name a withheld tool or operation?"""
    text = json.dumps(value, ensure_ascii=False).casefold()
    rows = manifest.get('unreleased', {}).get('groups', [])
    terms = [term for row in rows for term in row.get('display_terms', [row['id']])]
    return any(re.search(r'(?<![a-z0-9])' + re.escape(term.casefold()) + r'(?![a-z0-9])', text)
               for term in terms) or any(mode in text for mode in unreleased_operations(manifest))


def held_groups(manifest, names=()):
    """Withheld groups, and any of ``names`` the manifest does not declare.

    A released tree carries no withheld list: it declares only the groups it ships, so a group
    it does not declare is held there as well."""
    known = {group['id'] for group in manifest.get('groups', [])}
    return unreleased_groups(manifest) | (set(names) - known if known else set())


def withheld_tool(manifest, row):
    """Is a census tool row withheld? Its own name or its bindings decide, never its notes."""
    bound = set(row.get('installer_groups', [])) | {
        c['group'] for c in row.get('doctor_checks', []) if c.get('kind') == 'manifest'}
    held = held_groups(manifest, bound)
    checks = row.get('doctor_checks', [])
    # Every readiness check it has belongs to a held group: nothing released can report on it.
    unchecked = bool(checks) and all(c.get('kind') == 'manifest' and c['group'] in held for c in checks)
    return ((bool(bound) and bound <= held) or unchecked
            or release_mentions(manifest, [row.get('id', ''), row.get('title', '')]))


def qualification_records(group):
    """The original platform record and any later records in the same format."""
    qualification = group.get('qualification') or {}
    record = qualification.get('record')
    return ([record] if record is not None else []) + qualification.get('additional_records', [])


def platform_qualification_reason(group, platform_key):
    """A release hold only for groups that require qualification on each host platform."""
    qualification = group.get('qualification') or {}
    if not qualification.get('required_per_platform'):
        return ''
    if qualification.get('status') == 'qualified' and any(
            _successful_qualification_record(group['id'], record)
            and record['platform'] == platform_key for record in qualification_records(group)):
        return ''
    return (f"{group['id']}: missing successful qualification for {platform_key} "
            "in native/setup qualification records")


def _successful_qualification_record(gid, record):
    return (isinstance(record, dict) and record.get('tool') == gid and bool(record.get('version'))
            and record.get('platform') in PLATFORMS
            and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(record.get('date', ''))) is not None
            and record.get('doctor_result') == 'ready'
            and _HEX64.fullmatch(str(record.get('evidence_sha256', ''))) is not None)


def profile_groups(manifest, profile=None, *, only=None, skip=None, platform_key=None):
    """Ordered group ids for a profile (or explicit --only list) plus dependencies."""
    groups = by_id(manifest)
    if only:
        wanted = list(only)
    else:
        if profile is None:
            wanted = list(manifest['default']['groups'])
        else:
            if profile not in manifest['profiles']:
                raise ManifestError('unknown profile: ' + profile + '; choose site, or omit --profile')
            wanted = list(manifest['profiles'][profile]['groups'])
    unknown = [g for g in list(wanted) + list(skip or ()) if g not in groups]
    if unknown:
        raise ManifestError("unknown group: " + ", ".join(unknown))
    needed = set()

    def visit(group_id):
        if group_id in needed:
            return
        needed.add(group_id)
        for dependency in groups[group_id]["depends_on"]:
            visit(dependency)

    for group_id in wanted:
        visit(group_id)
    skipped = set(skip or ())
    if not only:
        skipped.update(unreleased_groups(manifest))
        platform_key = platform_key or detect_platform()
        skipped.update(gid for gid, group in groups.items()
                       if platform_qualification_reason(group, platform_key))
    return [g["id"] for g in manifest["groups"] if g["id"] in needed and g["id"] not in skipped]


def variables(prefix, repo, platform_key, *, jobs=None, container_engine=None, installer_python=None):
    prefix, repo = Path(prefix), Path(repo)
    jobs = jobs or max(1, (os.cpu_count() or 2) // 2)
    tools = prefix / "tools"
    values = {
        "P": str(prefix), "REPO": str(repo), "SUBDIR": CONDA_SUBDIRS[platform_key], "PLATFORM": platform_key,
        "JOBS": str(jobs), "CONDA": str(tools / "miniforge3/bin/conda"), "ENVS": str(tools / "miniforge3/envs"),
        "TOOLS": str(tools), "BIN": str(prefix / "bin"), "SHARE": str(prefix / "share"),
        "LHAPDF_DATA": str(prefix / "share/LHAPDF"), "DOWNLOADS": str(prefix / "downloads"),
        "CONFIG": str(prefix / "config"), "CONTAINERS": str(prefix / "containers"),
        "HOST_PYTHON": str(repo / ".venv/bin/python"),
        "INSTALLER_PYTHON": installer_python or str(tools / "miniforge3/bin/python"),
        "LCG_VIEW": "",
        "CONTAINER_ENGINE": container_engine or str(prefix / "bin/ravel-podman"),
        "OCI_PLATFORM": OCI_PLATFORMS[platform_key],
    }
    return values


def expand(value, values):
    """Expand {NAME} placeholders recursively in strings, lists and dicts."""
    if isinstance(value, str):
        def replace(match):
            name = match.group(1)
            if name not in values:
                raise ManifestError("undefined variable {" + name + "} in " + value)
            return values[name]
        return _VARIABLE.sub(replace, value)
    if isinstance(value, list):
        return [expand(item, values) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, values) for key, item in value.items()}
    return value


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _require(condition, message):
    if not condition:
        raise ManifestError(message)


def _check_digest(where, item):
    if item.get("blocked_reason"):
        return
    has_sha = isinstance(item.get("sha256"), str) and _HEX64.match(item["sha256"])
    has_md5 = isinstance(item.get("md5"), str) and _HEX32.match(item["md5"])
    _require(has_sha or has_md5, where + ": sha256 (or upstream md5) pin required")
    if "size" in item:
        _require(isinstance(item["size"], int) and item["size"] > 0, where + ": size must be a positive integer")


def _check_step(group_id, step, step_ids):
    where = group_id + "/" + str(step.get("id"))
    _require(isinstance(step.get("id"), str) and step["id"], group_id + ": step id required")
    _require(step["id"] not in step_ids, where + ": duplicate step id")
    step_ids.add(step["id"])
    kind = step.get("kind")
    _require(kind in STEP_KINDS, where + ": unknown step kind " + str(kind))
    if "platforms" in step:
        _require(set(step["platforms"]) <= set(PLATFORMS) and step["platforms"], where + ": bad platforms")
    for text in _strings({k: v for k, v in step.items() if k not in ("description", "instruction")}):
        _require(not _SHELL_VARIABLE.search(text), where + ": shell variable in " + repr(text))
        for name in _VARIABLE.findall(text):
            _require(name in ENGINE_VARIABLES, where + ": undefined variable {" + name + "}")
    if kind == "git":
        _require(isinstance(step.get("commit"), str) and _HEX40.match(step["commit"]), where + ": 40-hex commit required")
        _require(str(step.get("url", "")).startswith("https://"), where + ": https git URL required")
        _require(isinstance(step.get("dest"), str), where + ": dest required")
    elif kind in ("archive", "download"):
        _require(str(step.get("url", "")).startswith("https://"), where + ": https URL required")
        _check_digest(where, step)
        _require(isinstance(step.get("dest"), str), where + ": dest required")
    elif kind == "verify_file":
        _check_digest(where, step)
    elif kind == "conda_env":
        _require(isinstance(step.get("name"), str) and step["name"], where + ": env name required")
        _require(isinstance(step.get("specs"), list) and step["specs"], where + ": conda specs required")
    elif kind == "pip":
        _require(isinstance(step.get("python"), str), where + ": python required")
        for spec in step.get("requirements", []):
            pinned = "==" in spec or spec.startswith(("-r", "-e", "{", "/"))
            _require(pinned, where + ": pip requirement must be pinned with ==: " + spec)
    elif kind == "container_pull":
        _require(re.match(r"^sha256:[0-9a-f]{64}$", str(step.get("digest", ""))) is not None,
                 where + ": image digest sha256:<64 hex> required")
        _require("@" not in str(step.get("image", "")) and ":" not in str(step.get("image", "")).split("/")[-1],
                 where + ": image must be named without tag or digest; the digest field pins it")
    elif kind == "container_build":
        for field in ("containerfile", "context", "platform", "tag", "receipt"):
            _require(isinstance(step.get(field), str) and step[field], where + ": " + field + " required")
    elif kind == "container_run":
        for field in ("source", "overlay", "build", "image_receipt", "launcher", "installation", "program"):
            _require(isinstance(step.get(field), str) and step[field], where + ": " + field + " required")
        _require(step.get("argv") == ["/opt/ravel/bin/build-mcfm.sh", step["source"], step["overlay"], step["build"]],
                 where + ": argv must be the declared MCFM build command")
        _require(re.fullmatch(r"[A-Za-z0-9_.-]+", step["program"]) is not None, where + ": plain program name required")
        _require(bool(step.get("outputs")), where + ": declared outputs required")
    elif kind == "native_compile":
        for field in ("source", "overlay", "build", "toolchain", "installation", "program"):
            _require(isinstance(step.get(field), str) and step[field], where + ": " + field + " required")
        _require(step.get("argv") == ["{REPO}/native/containers/mcfm/build-mcfm.sh", step["source"], step["overlay"],
                                      step["build"]], where + ": argv must be the declared MCFM build command")
        _require(re.fullmatch(r"[A-Za-z0-9_.-]+", step["program"]) is not None, where + ": plain program name required")
        _require(bool(step.get("outputs")), where + ": declared outputs required")
        _require(set(step.get("platforms", ())) <= {"linux-x86_64"} and step.get("platforms"),
                 where + ": a native compile is declared for linux-x86_64 only")
    elif kind == "command":
        _require(isinstance(step.get("argv"), list) and step["argv"], where + ": argv required")
        _require(step["argv"][0] not in ("sh", "bash", "zsh") or step["argv"][1:2] != ["-c"],
                 where + ": inline shell is not allowed; use a recipe script")
        _require(step.get("outputs") or step.get("unless"),
                 where + ": a command needs declared outputs or an 'unless' probe so reruns can verify it")
    elif kind == "manual":
        _require(isinstance(step.get("probe"), dict) or isinstance(step.get("path"), str),
                 where + ": a manual step needs a probe or a path")
    if kind == "manual":
        _require(isinstance(step.get("instruction"), str) and step["instruction"], where + ": instruction required")
    elif kind == "wrapper":
        _require(isinstance(step.get("name"), str) and isinstance(step.get("template"), str), where + ": name/template")


def _check_check(group, check, check_ids):
    where = group["id"] + "/check " + str(check.get("id"))
    _require(isinstance(check.get("id"), str) and check["id"], where + ": id required")
    _require(check["id"] not in check_ids, where + ": duplicate check id")
    check_ids.add(check["id"])
    _require(check.get("kind") in CHECK_KINDS, where + ": unknown kind " + str(check.get("kind")))
    if check["kind"] in ("file", "directory", "executable"):
        _require(isinstance(check.get("path"), str) and check["path"], where + ": path required")
    if check["kind"] == "analysis_catalogue":
        _require(isinstance(check.get("rivet_ref"), str) and _HEX40.fullmatch(check["rivet_ref"]),
                 where + ": exact Rivet commit required")
        _require(isinstance(check.get("rebuild"), list) and check["rebuild"]
                 and all(isinstance(a, str) for a in check["rebuild"]), where + ": rebuild argv required")
    probe = check.get("probe")
    if probe is not None:
        _require(isinstance(probe.get("argv"), list) and probe["argv"], where + ": probe argv required")
        if "regex" in probe:
            re.compile(probe["regex"])
        _require(isinstance(probe.get("json_status", ""), str), where + ": probe json_status must be a string")
    for text in _strings(check):
        _require(not _SHELL_VARIABLE.search(text), where + ": shell variable in " + repr(text))
        for name in _VARIABLE.findall(text):
            _require(name in ENGINE_VARIABLES or name == "path", where + ": undefined variable {" + name + "}")


def _ancestors(groups, gid):
    byid = {g.get("id"): g for g in groups if isinstance(g, dict)}
    seen, pending = set(), list(byid[gid].get("depends_on") or [])
    while pending:
        item = pending.pop()
        if item not in seen and item in byid:
            seen.add(item)
            pending += list(byid[item].get("depends_on") or [])
    return seen


def validate(document, catalog=None):
    """Raise ManifestError on the first schema or pinning defect."""
    _require(isinstance(document, dict) and document.get("schema_version") == SCHEMA_VERSION
             and document.get("kind") == "ravel-toolchain-manifest", "toolchain manifest schema 2 expected")
    groups = document.get("groups")
    _require(isinstance(groups, list) and groups, "groups required")
    seen, all_checks = set(), set()
    for group in groups:
        _require(isinstance(group, dict) and isinstance(group.get("id"), str), "group id required")
        gid = group["id"]
        _require("optional" not in group, gid + ": optional field refused")
        for key in ("title", "description", "notes"):
            _require(not re.search(r"\b(?:optional|add-on|addon|extra|if installed|when available)\b",
                                   json.dumps(group.get(key, "")), re.I),
                     gid + ": tool label refused: " + str(group.get(key, "")))
        _require(gid not in seen, "duplicate group " + gid)
        _require(isinstance(group.get("title"), str) and group["title"], gid + ": title required")
        depends = group.get("depends_on")
        _require(isinstance(depends, list) and set(depends) <= seen, gid + ": dependencies must precede the group")
        seen.add(gid)
        for key, route in group.get("routes", {}).items():
            _require(key in PLATFORMS + ("default",) and route in ROUTES, gid + ": bad route " + key)
        if any(route_for(group, p) == "manual" for p in PLATFORMS):
            _require(isinstance(group.get("manual"), str) and group["manual"], gid + ": manual instruction required")
        _require(isinstance(group.get("size_gb"), (int, float)) and isinstance(group.get("minutes"), int),
                 gid + ": size_gb and minutes required")
        for licence in group.get("licenses", []):
            _require(isinstance(licence.get("component"), str) and isinstance(licence.get("spdx"), str),
                     gid + ": licence component/spdx required")
        if "qualification" in group:
            _require(group["qualification"].get("status") in QUALIFICATIONS
                     and isinstance(group["qualification"].get("basis"), str) and group["qualification"]["basis"],
                     gid + ": qualification needs a status from " + ", ".join(QUALIFICATIONS) + " and a basis")
            qualification = group['qualification']
            _require(type(qualification.get('required_per_platform', False)) is bool,
                     gid + ': required_per_platform must be boolean')
            _require(isinstance(qualification.get('additional_records', []), list),
                     gid + ': additional qualification records must be a list')
            records = qualification_records(group)
            if (qualification['status'] == 'qualified' or qualification.get('required_per_platform')
                    or qualification.get('additional_records')):
                _require(bool(records) and all(_successful_qualification_record(gid, r) for r in records),
                         gid + ': successful platform qualification record required')
                _require(len({r['platform'] for r in records}) == len(records),
                         gid + ': duplicate platform qualification record')
            if group['qualification']['status'] == 'tester-qualification':
                procedure = group['qualification'].get('procedure')
                _require(isinstance(procedure, str) and procedure.strip() and '\n' not in procedure,
                         gid + ': tester qualification needs its one-line site procedure')
        if "hold" in group:
            _require(all(isinstance(group["hold"].get(k), str) and group["hold"][k] for k in ("reason", "status"))
                     and isinstance(group["hold"].get("request_classes"), list) and group["hold"]["request_classes"],
                     gid + ": hold needs reason, status and request_classes")
        if gid != "python-host" and "{HOST_PYTHON}" in json.dumps(group.get("steps", [])):
            _require("python-host" in _ancestors(groups, gid),
                     gid + ": a step that runs {HOST_PYTHON} needs the python-host group among its dependencies")
        step_ids = set()
        _require(isinstance(group.get("steps"), list), gid + ": steps list required")
        for step in group["steps"]:
            _check_step(gid, step, step_ids)
        _require(isinstance(group.get("checks"), list) and group["checks"], gid + ": checks required")
        for check in group["checks"]:
            _check_check(group, check, all_checks)
        for platform_key in PLATFORMS:
            if route_for(group, platform_key) in ("native", "container"):
                active = [c for c in group["checks"] if applies(c, platform_key)]
                _require(active, gid + ": no readiness check applies on " + platform_key)
    profiles = document.get("profiles")
    _require(isinstance(profiles, dict) and set(profiles) == {'site'}, 'site is the only named profile')
    _require(isinstance(document.get('default'), dict), 'default toolchain required')
    for name, profile in [('default', document['default']), *profiles.items()]:
        _require(isinstance(profile.get("groups"), list) and profile["groups"], "profile " + name + " needs groups")
        _require(set(profile["groups"]) <= seen, "profile " + name + " names an unknown group")
        _require(isinstance(profile.get("disk_gb"), (int, float)), "profile " + name + " needs disk_gb")
    unreleased = document.get('unreleased', {})
    withheld = unreleased_groups(document)
    _require(withheld <= seen, 'unreleased list names an unknown group')
    for row in unreleased.get('groups', []):
        _require(isinstance(row.get('reason'), str) and row['reason'] and
                 row.get('check') in {c['id'] for c in by_id(document)[row['id']]['checks']},
                 'unreleased group needs a failing check and reason')
    for row in unreleased.get('operations', []):
        _require(set(row.get('groups', [])) <= withheld and row.get('groups'),
                 'unreleased operation must name its withheld requirements')
    miniforge = document.get("miniforge", {})
    for key in PLATFORMS:
        asset = miniforge.get("assets", {}).get(key)
        _require(isinstance(asset, dict) and _HEX64.match(str(asset.get("sha256", ""))), "miniforge pin for " + key)
    entry = document.get("container_build")
    _require(isinstance(entry, dict) and isinstance(entry.get("module"), str) and isinstance(entry.get("argv"), list),
             "container_build entry (module, argv) required")
    for text in entry["argv"]:
        for name in _VARIABLE.findall(text):
            _require(name in ENGINE_VARIABLES or name in ("RECIPE", "CONTAINERFILE", "BUILD_CONTEXT", "IMAGE_TAG", "IMAGE_PLATFORM", "BUILD_RECEIPT"), "container_build: undefined variable {" + name + "}")
    for row in document.get("refusal_classes", []):
        _require(all(isinstance(row.get(k), str) and row[k] for k in
                     ("id", "title", "refused", "why", "refused_by", "would_make_it_possible"))
                 and set(row.get("groups", [])) <= seen, "refusal class needs its fields and known groups: " + str(row.get("id")))
    for row in document.get("operations", []):
        _require(set(row.get("groups", [])) <= seen, "operation " + str(row.get("mode")) + " names an unknown group")
    for pair in document.get("incompatible_path_bindings", []):
        _require(isinstance(pair, list) and len(pair) == 2 and set(pair) <= all_checks,
                 "incompatible pair must name two checks: " + repr(pair))
    if catalog is not None:
        validate_pdf_sets(catalog)
    from ravel.setup.licence_policy import validate as validate_licence_policy
    validate_licence_policy(document)
    from ravel.setup.gpl_isolation import validate as validate_gpl_isolation
    validate_gpl_isolation(document)
    return document


def validate_sm_pdf_pins(pins):
    """Validate the acquired source facts before they enter the PDF catalogue."""
    _require(isinstance(pins, dict) and pins.get("schema_version") == 1
             and pins.get("kind") == "ravel-sm-pdf-pins", "SM PDF pins schema 1 expected")
    rows = pins.get("sets")
    _require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows),
             "SM PDF pins require a list of set rows")
    names = [row.get("name") for row in rows]
    _require(tuple(names) == SM_PDF_SET_NAMES, "SM PDF pins must preserve the declared set order")
    for row in rows:
        name = row["name"]
        _require(isinstance(row.get("lhaid"), int) and row["lhaid"] > 0, name + ": LHAID required")
        _require(isinstance(row.get("size"), int) and row["size"] > 0, name + ": size required")
        _require(isinstance(row.get("sha256"), str) and _HEX64.fullmatch(row["sha256"]) is not None,
                 name + ": sha256 required")
        _require(isinstance(row.get("used_for"), str) and row["used_for"].strip(), name + ": used_for required")
    return pins


def append_sm_pdf_sets(catalog, pins):
    """Append acquired SM set facts without rewriting established catalogue rows."""
    validate_sm_pdf_pins(pins)
    result = deepcopy(catalog)
    names = {row.get("name") for row in result.get("sets", [])}
    collisions = names & set(SM_PDF_SET_NAMES)
    _require(not collisions, "SM PDF set already present: " + ", ".join(sorted(collisions)))
    result.setdefault("sets", []).extend({**row, "digest_status": "single-download"} for row in pins["sets"])
    validate_pdf_sets(result, sm_pins=pins)
    return result


def validate_pdf_sets(catalog, *, sm_pins=None):
    _require(isinstance(catalog, dict) and catalog.get("schema_version") == 1
             and catalog.get("kind") == "ravel-lhapdf-sets", "PDF-set catalogue schema 1 expected")
    _require(str(catalog.get("base_url", "")).startswith("https://"), "PDF-set base_url must be https")
    names, ids = set(), set()
    for row in catalog.get("sets", []):
        name = row.get("name")
        _require(isinstance(name, str) and re.match(r"^[A-Za-z0-9_.+-]+$", name), "bad PDF set name")
        _require(name not in names, "duplicate PDF set " + name)
        names.add(name)
        _require(isinstance(row.get("lhaid"), int) and row["lhaid"] not in ids, name + ": unique LHAID required")
        ids.add(row["lhaid"])
        _require(isinstance(row.get("size"), int) and row["size"] > 0, name + ": size required")
        _check_digest("PDF set " + name, row)
    _require(names, "at least one PDF set required")
    if sm_pins is not None:
        validate_sm_pdf_pins(sm_pins)
        expected = {row["name"]: row for row in sm_pins["sets"]}
        actual = {row["name"]: row for row in catalog["sets"]}
        for name, pin in expected.items():
            _require(name in actual, name + ": missing pinned PDF set")
            for field in ("lhaid", "size", "sha256", "used_for"):
                _require(actual[name].get(field) == pin[field], name + ": " + field + " must match sm-pins")
            _require(actual[name].get("digest_status") == "single-download",
                     name + ": digest status must remain single-download until independently verified")
    return catalog


def lint_unknown_variables(document):
    """Return every placeholder name used anywhere in steps/checks (for tests)."""
    found = set()
    for group in document["groups"]:
        for text in _strings(group.get("steps", [])):
            found.update(_VARIABLE.findall(text))
    return found


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("view", help="Read the merged toolchain document")
    command.add_argument("--root", type=Path)
    command.add_argument("--canonical-sha256", action="store_true")
    args = parser.parse_args(argv)
    try:
        document = view(args.root)
        print(canonical_sha256(document) if args.canonical_sha256 else json.dumps(document, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
