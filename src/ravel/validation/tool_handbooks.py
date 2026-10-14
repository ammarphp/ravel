"""Runtime HEP tool handbooks: discovery and contract checks.

A handbook is a directory ``src/ravel/data/skills/tools/<tool>/`` holding
``SKILL.md``, a ``references/`` directory and ``references/review.md``. It
ships as package data, so an installed RAVEL finds it with ``handbook_root()``
and an installer copies whole handbook directories into an agent's skills
directory.

The checks, used by ``check_agent_surface``:

- frontmatter: exactly the six Agent Skills keys (name, description, license,
  compatibility, allowed-tools, metadata), RAVEL fields under ``metadata``
  only, ``metadata.ravel-requires-modes`` naming declared science modes;
- budget: the estimated token count of ``SKILL.md`` and of each reference file
  stays within a budget (5000 by default). The estimate is a line proxy: each
  line costs ceil(characters / 4) + 1 tokens;
- pitfalls: every bullet under ``## Pitfalls`` names the RAVEL check that
  catches it (``Caught by `module.function```) or is labelled ``Advisory:``;
- parameters: every ``metadata.ravel-parameters`` entry, and every
  ``operation.field`` path the body mentions, is listed in
  ``data/skills/operation-fields.json``;
- versions: ``metadata.upstream-version`` items (``group:component=version``
  for a toolchain-manifest group, ``pypi:distribution=version`` for a pinned
  Python dependency) match the pins, unless listed in
  ``metadata.ravel-version-unpinned``;
- review record: ``references/review.md`` carries one JSON record naming the
  executable and illustrative code blocks; every ``ravel-block=<id>`` block is
  listed and every listed block exists. ``tests/skills/<name>/`` runs the
  executable ones;
- installed copies: a handbook installed into a skills directory is
  byte-identical to the packaged source;
- collisions (report-only): skill descriptions that overlap strongly.

``availability`` turns a ``ravel doctor`` report (or the older
``native_doctor`` report) into the per-handbook unavailable ledger.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re

FRONTMATTER_KEYS = ("name", "description", "license", "compatibility", "allowed-tools", "metadata")
REQUIRED_KEYS = ("name", "description", "license", "metadata")
METADATA_KEYS = ("ravel-requires-modes", "upstream-version", "ravel-parameters", "ravel-version-unpinned",
                 "last-reviewed")
REQUIRED_METADATA = ("ravel-requires-modes", "upstream-version", "last-reviewed")
TOKEN_BUDGET = 5000
DESCRIPTION_LIMIT = 1024          # the Agent Skills specification's limit
COLLISION_THRESHOLD = 0.35          # report-only; highest pair on 2026-10-11 was 0.20
REVIEW_KEYS = ("skill", "reviewed", "reviewer", "sources", "tested_versions", "executable_blocks",
               "illustrative_blocks", "limits")
OK_DOCTOR = ("ready", "remote_route")

_FENCE = re.compile(r"^```([A-Za-z0-9_+-]*)[ \t]+ravel-block=([a-z0-9][a-z0-9-]*)[ \t]*\n(.*?)^```[ \t]*$",
                    re.M | re.S)
_REVIEW = re.compile(r"^```json[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
_VERSION = re.compile(r"\d+(?:\.\d+)+|[0-9a-f]{40}")
_WORD = re.compile(r"[a-z][a-z0-9+-]{2,}")
_STOP = frozenset("use when the and for with from into this that what which before after only not are its "
                  "any each one two run runs your you must also how via per".split())


# ------------------------------------------------------------------ discovery

def handbook_root():
    """The packaged handbook directory (works from a checkout or an installed wheel)."""
    from ravel.paths import package_data_path
    return package_data_path("skills", "tools")


def operation_fields_path():
    from ravel.paths import package_data_path
    return package_data_path("skills", "operation-fields.json")


def handbooks(root=None):
    root = Path(root) if root is not None else handbook_root()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def handbook_files(skill_dir):
    """Every regular file of a handbook, relative path -> path."""
    skill_dir = Path(skill_dir)
    return {p.relative_to(skill_dir).as_posix(): p for p in sorted(skill_dir.rglob("*"))
            if p.is_file() and p.name != ".DS_Store" and "__pycache__" not in p.parts}


# ------------------------------------------------------------------ parsing

class FrontmatterError(ValueError):
    pass


def _strict_yaml(text):
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
        duplicate = sorted({k for k in keys if keys.count(k) > 1}, key=str)
        if duplicate:
            raise FrontmatterError(f"duplicate frontmatter key {duplicate[0]!r}")
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        return yaml.load(text, Loader=Loader)
    except yaml.YAMLError as error:
        raise FrontmatterError(f"frontmatter is not valid YAML: {error}") from None


def split_frontmatter(text):
    """(frontmatter mapping, body) of a SKILL.md text."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise FrontmatterError("no YAML frontmatter")
    data = _strict_yaml(match.group(1))
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter is not a mapping")
    return data, text[match.end():]


def words(value):
    return [w for w in str(value).split() if w]


def estimate_tokens(text):
    """Line proxy for a tokenizer: each line costs ceil(characters / 4) + 1."""
    return sum(math.ceil(len(line) / 4) + 1 for line in text.splitlines())


def blocks(skill_dir):
    """{block id: {'language', 'code', 'file'}} for every ``ravel-block=<id>`` fence."""
    found = {}
    for rel, path in handbook_files(skill_dir).items():
        if not rel.endswith(".md"):
            continue
        for match in _FENCE.finditer(path.read_text(encoding="utf-8")):
            language, ident, code = match.groups()
            if ident in found:
                raise ValueError(f"duplicate block id {ident!r}")
            found[ident] = {"language": language, "code": code, "file": rel}
    return found


def review_record(skill_dir):
    path = Path(skill_dir) / "references" / "review.md"
    if not path.is_file():
        raise ValueError("references/review.md missing")
    records = _REVIEW.findall(path.read_text(encoding="utf-8"))
    if len(records) != 1:
        raise ValueError("references/review.md needs exactly one ```json review record")
    record = json.loads(records[0])
    if not isinstance(record, dict) or set(record) != set(REVIEW_KEYS):
        raise ValueError("review record keys must be exactly " + ", ".join(REVIEW_KEYS))
    return record


def pitfalls(body):
    """The bullets of the ``## Pitfalls`` section, each joined to one line."""
    match = re.search(r"^## Pitfalls[ \t]*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    if not match:
        return None
    items = []
    for line in match.group(1).splitlines():
        if re.match(r"^- ", line):
            items.append(line[2:].strip())
        elif items and line.startswith("  ") and line.strip():
            items[-1] += " " + line.strip()
    return items


# ------------------------------------------------------------------ references to RAVEL checks

def _source_root():
    return Path(__file__).resolve().parents[2]       # .../src


def resolve_check(ref, src_root=None):
    """True when ``ref`` names an existing RAVEL module, function or file.

    ``ravel.physics.model_events.check_cards`` resolves to a module file plus a
    top-level ``def``/``class``/assignment; ``src/ravel/validation/lhe_check.py``
    resolves to the file. Nothing is imported.
    """
    src = Path(src_root) if src_root is not None else _source_root()
    if ref.endswith(".py"):
        rel = ref[4:] if ref.startswith("src/") else ref
        return (src / rel).is_file()
    parts = ref.split(".")
    if parts[0] != "ravel":
        return False
    for cut in range(len(parts), 1, -1):
        module = src.joinpath(*parts[:cut]).with_suffix(".py")
        if module.is_file():
            names = parts[cut:]
            if not names:
                return True
            if len(names) > 1:
                return False
            text = module.read_text(encoding="utf-8")
            return bool(re.search(rf"^(?:def|class)\s+{re.escape(names[0])}\b|^{re.escape(names[0])}\s*=",
                                  text, re.M))
    return False


# ------------------------------------------------------------------ versions

def manifest_pins(manifest):
    """{group id: (lower-cased group text, version tokens)} for either manifest shape.

    Version-1 manifests carry ``version_contract`` maps; version-2 manifests carry
    titles, step tags and conda specs, and check ``expect`` values. Every string
    in the group counts, so both shapes resolve the same pins.
    """
    pins = {}
    for group in (manifest or {}).get("groups", []):
        text = json.dumps(group, sort_keys=True)
        pins[group["id"]] = (text.lower(), set(_VERSION.findall(text)))
    return pins


def python_pins(pyproject_text):
    """{distribution: version} for ``name==version`` dependency pins."""
    pins = {}
    for name, version in re.findall(r'"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^",;\s]+)', pyproject_text):
        pins.setdefault(name.lower(), version)
    return pins


def parse_versions(value):
    items = []
    for item in words(value):
        match = re.fullmatch(r"([a-z0-9-]+):([A-Za-z0-9_.+-]+)=([A-Za-z0-9_.+-]+)", item)
        if not match:
            raise ValueError(f"upstream-version item {item!r} is not source:component=version")
        items.append(match.groups())
    return items


def check_versions(metadata, *, manifest_pins_=None, python_pins_=None):
    """Errors and notes for ``upstream-version`` against the toolchain pins."""
    errors, notes = [], []
    try:
        items = parse_versions(metadata.get("upstream-version", ""))
        unpinned = {tuple(i) for i in parse_versions(metadata.get("ravel-version-unpinned", ""))}
    except ValueError as error:
        return [str(error)], notes
    if not items:
        errors.append("upstream-version names no version")
    if not unpinned <= set(items):
        errors.append("ravel-version-unpinned lists an item missing from upstream-version")
    groups, distributions = manifest_pins_ or {}, python_pins_ or {}
    for source, component, version in items:
        label = f"{source}:{component}={version}"
        if source == "pypi":
            pinned = distributions.get(component.lower())
            ok = pinned == version
            found = f"pyproject pins {pinned}" if pinned else "pyproject has no pin"
        else:
            text, tokens = groups.get(source, ("", set()))
            ok = source in groups and component.lower() in text and version in tokens
            found = (f"group {source} does not pin {component} {version}" if source in groups
                     else f"toolchain manifest has no group {source}")
        if ok and (source, component, version) in unpinned:
            notes.append(f"{label} is pinned now; drop it from ravel-version-unpinned")
        elif not ok and (source, component, version) not in unpinned:
            errors.append(f"upstream-version {label} does not match the toolchain ({found}); "
                          "fix it or list it in ravel-version-unpinned")
    return errors, notes


# ------------------------------------------------------------------ one handbook

def load_operation_fields(path=None):
    data = json.loads(Path(path or operation_fields_path()).read_text(encoding="utf-8"))
    fields = set()
    for operation, row in data["operations"].items():
        fields.update(f"{operation}.{field}" for field in row["fields"])
    return fields, set(data["operations"])


def check_handbook(skill_dir, *, modes, fields=None, operations=None, budget=TOKEN_BUDGET,
                   manifest_pins_=None, python_pins_=None, src_root=None, tests_root=None):
    """(errors, notes) for one handbook directory."""
    skill_dir = Path(skill_dir)
    name = skill_dir.name
    errors, notes = [], []

    def fail(message):
        errors.append(f"{name}: {message}")

    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    try:
        front, body = split_frontmatter(text)
    except FrontmatterError as error:
        return [f"{name}: {error}"], notes
    extra = sorted(set(front) - set(FRONTMATTER_KEYS))
    if extra:
        fail(f"frontmatter keys {extra} are outside the closed set {list(FRONTMATTER_KEYS)}; "
             "put RAVEL fields under metadata")
    for key in REQUIRED_KEYS:
        if key not in front:
            fail(f"frontmatter key {key!r} missing")
    if front.get("name") != name:
        fail(f"frontmatter name {front.get('name')!r} differs from the directory name")
    description = " ".join(str(front.get("description", "")).split())
    if not 40 <= len(description) <= DESCRIPTION_LIMIT:
        fail(f"description must be 40-{DESCRIPTION_LIMIT} characters")
    for key in ("license", "compatibility", "allowed-tools"):
        if key in front and not isinstance(front[key], str):
            fail(f"{key} must be a string")
    metadata = front.get("metadata")
    if not isinstance(metadata, dict):
        fail("metadata must be a mapping")
        metadata = {}
    extra = sorted(set(metadata) - set(METADATA_KEYS))
    if extra:
        fail(f"metadata keys {extra} are outside {list(METADATA_KEYS)}")
    for key in REQUIRED_METADATA:
        if key not in metadata:
            fail(f"metadata.{key} missing")
    for key, value in metadata.items():
        if not isinstance(value, str):
            fail(f"metadata.{key} must be a quoted string")
    unknown = [m for m in words(metadata.get("ravel-requires-modes", "")) if m not in modes]
    if unknown:
        fail(f"ravel-requires-modes names undeclared modes {unknown}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(metadata.get("last-reviewed", ""))):
        fail("metadata.last-reviewed must be a YYYY-MM-DD date")

    # Context budget.
    for rel, path in handbook_files(skill_dir).items():
        if rel == "SKILL.md" or (rel.startswith("references/") and rel.endswith(".md")):
            cost = estimate_tokens(path.read_text(encoding="utf-8"))
            if cost > budget:
                fail(f"{rel} costs about {cost} tokens (line proxy), over the {budget} budget")
    if not (skill_dir / "references").is_dir():
        fail("references/ missing")

    # Pitfalls.
    items = pitfalls(body)
    if items is None:
        fail("no '## Pitfalls' section")
    for item in items or []:
        refs = re.findall(r"Caught by ((?:`[^`]+`(?:,? (?:and )?)?)+)", item)
        names = [r for group in refs for r in re.findall(r"`([^`]+)`", group)]
        advisory = item.startswith("Advisory:") or " Advisory:" in item
        if not names and not advisory:
            fail(f"pitfall names no RAVEL check and is not labelled Advisory: {item[:70]!r}")
        for ref in names:
            if not resolve_check(ref, src_root):
                fail(f"pitfall names {ref!r}, which is not a RAVEL module, function or file")

    # Parameters against the operation field list.
    if fields is not None:
        declared = words(metadata.get("ravel-parameters", ""))
        for parameter in declared:
            if parameter not in fields:
                fail(f"ravel-parameters {parameter!r} is not an operation.field in operation-fields.json")
        prefixes = tuple(f"{op}." for op in (operations or ()))
        mentioned = {t for t in re.findall(r"`([a-z0-9-]+\.[a-z0-9_.]+)`", body) if t.startswith(prefixes)}
        for parameter in sorted(mentioned - set(declared)):
            fail(f"body mentions {parameter!r} without listing it in metadata.ravel-parameters")

    # Versions.
    version_errors, version_notes = check_versions(metadata, manifest_pins_=manifest_pins_,
                                                   python_pins_=python_pins_)
    errors += [f"{name}: {e}" for e in version_errors]
    notes += [f"{name}: {n}" for n in version_notes]

    # Review record and code blocks.
    try:
        record = review_record(skill_dir)
        found = blocks(skill_dir)
    except (ValueError, json.JSONDecodeError) as error:
        fail(str(error))
    else:
        if record["skill"] != name:
            fail("review record names another skill")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(record["reviewed"])):
            fail("review record date must be YYYY-MM-DD")
        if not record["sources"] or not all(isinstance(s, str) and s for s in record["sources"]):
            fail("review record cites no upstream source")
        listed = list(record["executable_blocks"]) + list(record["illustrative_blocks"])
        if len(listed) != len(set(listed)):
            fail("review record lists a block twice")
        for ident in sorted(set(listed) - set(found)):
            fail(f"review record lists block {ident!r}, which no file carries")
        for ident in sorted(set(found) - set(listed)):
            fail(f"block {ident!r} is not listed in the review record")
        for ident in record["executable_blocks"]:
            if ident in found and found[ident]["language"] != "python":
                fail(f"executable block {ident!r} must be python")
        if tests_root is not None and record["executable_blocks"]:
            if not any((Path(tests_root) / name).glob("test_*.py")):
                fail(f"tests/skills/{name}/ has no test running the executable blocks")
    return errors, notes


def check_all(root=None, *, modes, budget=TOKEN_BUDGET, manifest=None, pyproject_text="", fields_path=None,
              src_root=None, tests_root=None):
    """(errors, notes) over every packaged handbook."""
    found = handbooks(root)
    if not found:
        return ["no tool handbooks found"], []
    fields, operations = load_operation_fields(fields_path)
    groups, distributions = manifest_pins(manifest), python_pins(pyproject_text)
    errors, notes = [], []
    for skill_dir in found:
        e, n = check_handbook(skill_dir, modes=modes, fields=fields, operations=operations, budget=budget,
                              manifest_pins_=groups, python_pins_=distributions, src_root=src_root,
                              tests_root=tests_root)
        errors += e
        notes += n
    return errors, notes


# ------------------------------------------------------------------ installed copies

def check_installed(skills_dirs, root=None):
    """Errors for installed handbook copies that differ from the packaged source.

    ``skills_dirs`` are agent skills directories (a project's ``.claude/skills``
    or ``.agents/skills``, or a user-level one). A directory there whose name is
    a packaged handbook must be byte-identical to it, with no missing or extra
    file.
    """
    errors = []
    packaged = {p.name: p for p in handbooks(root)}
    for skills_dir in map(Path, skills_dirs):
        if not skills_dir.is_dir():
            continue
        for installed in sorted(p for p in skills_dir.iterdir() if p.is_dir() and p.name in packaged):
            source, copy = handbook_files(packaged[installed.name]), handbook_files(installed)
            label = f"{skills_dir}/{installed.name}"
            for rel in sorted(set(source) - set(copy)):
                errors.append(f"installed copy {label} lacks {rel}; reinstall the handbook")
            for rel in sorted(set(copy) - set(source)):
                errors.append(f"installed copy {label} carries {rel}, which the packaged handbook does not")
            for rel in sorted(set(source) & set(copy)):
                if source[rel].read_bytes() != copy[rel].read_bytes():
                    errors.append(f"installed copy {label}/{rel} is stale; reinstall the handbook")
    return errors


# ------------------------------------------------------------------ collisions (report-only)

def _description(path):
    try:
        front, _ = split_frontmatter(Path(path).read_text(encoding="utf-8"))
    except (FrontmatterError, OSError):
        return ""
    return " ".join(str(front.get("description", "")).split())


def collisions(skill_files, threshold=COLLISION_THRESHOLD):
    """Pairs of skills whose description word sets overlap at or above ``threshold`` (Jaccard)."""
    bags = {}
    for path in skill_files:
        name = Path(path).parent.name
        bags[name] = {w for w in _WORD.findall(_description(path).lower()) if w not in _STOP}
    names = sorted(bags)
    found = []
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            union = bags[left] | bags[right]
            score = len(bags[left] & bags[right]) / len(union) if union else 0.0
            if score >= threshold:
                found.append((left, right, round(score, 2)))
    return found


# ------------------------------------------------------------------ doctor adapter and unavailable ledger

# native_doctor check names -> toolchain groups, for the fallback report.
NATIVE_DOCTOR_GROUPS = {
    "madgraph_source": "madgraph", "mg5_gfortran": "madgraph", "mg5_make": "madgraph",
    "mg5_python_arch": "madgraph", "mg5_python_packages": "madgraph",
    "rivet_python_arch": "rivet-shower", "rivet_python_packages": "rivet-shower",
    "pythia8-config": "rivet-shower", "HepMC3-config": "rivet-shower", "pythia_shower": "rivet-shower",
    "recast_python_arch": "recast-base", "root_config": "recast-base", "root_configuration": "recast-base",
    "delphes": "recast-base", "libDelphes": "recast-base", "delphes_headers": "recast-base",
}


def group_status(report):
    """{toolchain group: status} from a ``ravel doctor`` or ``native_doctor`` report."""
    if not isinstance(report, dict):
        raise ValueError("doctor report must be a JSON object")
    if report.get("kind") == "ravel-doctor-report":
        return {g["group"]: g["status"] for g in report.get("groups", [])}
    if "checks" in report and "groups" not in report:
        status = {}
        for check in report["checks"]:
            group = NATIVE_DOCTOR_GROUPS.get(check.get("name"))
            if group is None:
                continue
            state = "ready" if check.get("status") in ("pass", "warning") else "missing"
            if status.get(group) != "missing":
                status[group] = state
        return status
    raise ValueError("unrecognised doctor report")


def doctor_report(repo=None):
    """A live report: ``ravel doctor`` when installed, else ``native_doctor``.

    Both are read-only probes. The ravel doctor report is preferred because it
    covers every toolchain group and their versions.
    """
    try:
        from ravel.setup import doctor, manifest as mf          # installer stream
        root = Path(repo or mf.repo_root())
        loaded, catalog = mf.load(root)
        prefix = doctor.resolve_prefix(root, None, None)
        engine = doctor.Doctor(root, prefix, mf.detect_platform(), loaded, catalog)
        return engine.report(doctor.select_groups(loaded))
    except ImportError:
        from ravel.validation import native_doctor
        return native_doctor.diagnose()


def handbook_groups(skill_dir):
    front, _ = split_frontmatter((Path(skill_dir) / "SKILL.md").read_text(encoding="utf-8"))
    items = parse_versions(front.get("metadata", {}).get("upstream-version", ""))
    return sorted({source for source, _, _ in items if source != "pypi"})


def availability(report, root=None):
    """The unavailable ledger: {handbook: {'status', 'groups'}}.

    ``available`` when every toolchain group the handbook pins is ready (or runs
    on a remote site); ``unavailable`` when one is not; ``unknown`` when the
    report does not cover a group. A handbook for an unavailable tool is
    illustrative on this host: its executable blocks are not run here.
    """
    status = group_status(report)
    ledger = {}
    for skill_dir in handbooks(root):
        groups = handbook_groups(skill_dir)
        rows = {g: status.get(g, "not probed") for g in groups}
        if any(s not in OK_DOCTOR and s != "not probed" for s in rows.values()):
            state = "unavailable"
        elif any(s == "not probed" for s in rows.values()):
            state = "unknown"
        else:
            state = "available"
        ledger[skill_dir.name] = {"status": state, "groups": rows}
    return ledger


def format_ledger(ledger):
    lines = []
    for name, row in sorted(ledger.items()):
        detail = ", ".join(f"{g} {s}" for g, s in row["groups"].items()) or "no toolchain group"
        lines.append(f"{name}: {row['status']} ({detail})")
    return lines


def default_install_dirs(project):
    project = Path(project)
    return [project / ".claude" / "skills", project / ".agents" / "skills"]


def environment_install_dirs():
    """User-level skills directories that may hold installed handbooks."""
    home = Path(os.path.expanduser("~"))
    return [home / ".claude" / "skills", home / ".agents" / "skills"]
