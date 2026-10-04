"""Build and verify campaign directories around exact v1 spec and registry bytes (slice design §3, §4.1).

A campaign lives at ``<store>/<kind>/<campaign_id>/`` and holds ``spec.json`` and ``registry.json``
(the exact bytes the v1 CLI reads and prints) plus ``campaign.json`` (the §4.1 manifest).
``verify`` re-derives the registry from ``spec.json`` and compares bytes, which closes the v1
value-equality loophole: ``experiment.validate_registry`` accepts a registry whose seed is
written ``11.0``, whose arm flags are written ``1`` or whose keys are reordered; ``verify`` does
not. Task definitions enter the manifest as ``canonical.digest`` of each §4.4 record.

The v1 spec is bound to the host it evaluates (one spec per model/runtime configuration) and to the
campaign kind (``spec_identity``): an empirical campaign's spec declares ``runtime_label(host)`` and
the host's pinned model exactly; a synthetic campaign's spec carries the synthetic label in both (a
real host's as ``synthetic <runtime_label>`` and ``synthetic <model>``, a fake host's as a prefix).
The kind is therefore part of the spec digest and of every run id: a synthetic cohort's run ids never
belong to an empirical campaign, on any host, and relabeling ``kind`` in place fails ``verify``.
For a real host the kind also fixes the authorization class (``contracts.validate_campaign_manifest``:
synthetic needs ``synthetic_engineering``, empirical ``approved_campaign``), and an authorization's
``reference_sha256``, when given, must resolve to the approval record frozen with the campaign
(``approval_record``, write-once). ``verify`` also checks each run's seal (slice design §10a): every
sealed run.json the runner would trust (``runner.seal_problem`` reconciles its seal) is checked against
the registry and the manifest, so a cohort whose spec and registry are re-frozen under another kind still
disagrees with its sealed runs; a seal verify cannot check (a symlink or irregular entry on a seal path,
a torn journal, a value-equal but non-canonical evidence manifest) is an error, never skipped (the
runner's seal_problem refuses the same symlinked, irregular and non-canonical seals). A seal the runner refuses (changed after sealing) is left to its custody incident.
Scope: a same-uid writer who rewrites the journal's sealed digest together with the sealed tree is
outside this check (slice design §12.6 residual).
Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath

from . import canonical, contracts
from .canonical import ContractError, require

experiment = contracts.experiment
SPEC, REGISTRY, MANIFEST = "spec.json", "registry.json", "campaign.json"
APPROVAL = "approval_record"   # the bytes an authorization's reference_sha256 names, frozen with the campaign
TASK_DEFINITION = "task_definition.json"
FAMILY_INDEX = ("coordinator", "family", "index.json")   # a runner-built campaign's frozen family (runner.py)
# Sealed evidence of one assignment, as runner._seal writes it (slice design §10a).
RUNS, JOURNAL, SEALED, EVIDENCE_MANIFEST, RUN_RECORD = (
    "runs", "journal.jsonl", "sealed", "evidence_manifest.json", "run.json")
SYNTHETIC_LABEL = "synthetic"  # prefix of a synthetic campaign's spec model and runtime (never an empirical one's)
READ_ERRORS = (OSError, ValueError, TypeError, KeyError, RecursionError)
PYTHON_VERSION = re.compile(r"(CPython|PyPy) [0-9]+\.[0-9]+\.[0-9]+\S*")


def v1_bytes(value) -> bytes:
    """Exact bytes of the v1 CLI output for this object: json.dumps(indent=2) plus a newline."""
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def manifest_bytes(manifest) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _v1(function, *args):
    try:
        return function(*args)
    except (ValueError, TypeError, KeyError) as exc:
        raise ContractError(f"v1 {function.__name__}: {exc}") from exc


def runtime_label(host) -> str:
    """The v1 ``spec.runtime`` of an empirical real-host campaign: ``'<adapter> <pinned version>'``."""
    return f"{host['adapter']} {host['version']}"


def spec_identity(kind, host) -> tuple:
    """(model, runtime) the v1 spec of a ``kind`` campaign on this real host must declare.

    Empirical: the host exactly, ``(host.model, runtime_label(host))``. Synthetic: both prefixed by
    the synthetic label and a space; model None when the host's model is unknown (then any model
    carrying that prefix). ``runtime_label`` starts with the adapter name, never the label, so the two
    kinds never share a spec or a run id. A fake host has no identity (its spec carries the label)."""
    require(host["adapter"] != "fake", "spec_identity: the fake host has no identity; its v1 spec carries the "
                                       f"{SYNTHETIC_LABEL!r} label instead")
    require(kind in contracts.KINDS, f"spec_identity: kind must be one of {list(contracts.KINDS)}")
    model, runtime = host["model"], runtime_label(host)
    if kind == "synthetic":
        model = None if model is None else f"{SYNTHETIC_LABEL} {model}"
        runtime = f"{SYNTHETIC_LABEL} {runtime}"
    return model, runtime


def _regular(path, root) -> Path:
    """Return path if it is a regular file reached from root through no symlink (lstat only)."""
    path, current = Path(path), Path(root)
    for part in path.relative_to(root).parts:
        current = current / part
        require(not current.is_symlink(), f"symlink {current.relative_to(root)} is not accepted")
    require(stat.S_ISREG(path.lstat().st_mode), "not a regular file")
    return path


def _overlap(a, b) -> bool:
    a, b = Path(a).resolve(), Path(b).resolve()
    return a == b or a in b.parents or b in a.parents


def _check_definition(definition, task, kind, label):
    """Check one §4.4 definition against its v1 spec task; return its manifest task entry.
    Shared by write_campaign and verify."""
    contracts.validate_task_definition(definition, label)
    require(definition["task_id"] == task["id"], f"{label}: is for task {definition['task_id']!r}, not {task['id']!r}")
    for name in ("expected", "prompt_sha256", "oracle_sha256"):
        require(definition[name] == task[name], f"{label}: {name} differs from the v1 spec")
    require(canonical.canonical_bytes(definition["fidelity"]["tolerance"])
            == canonical.canonical_bytes(task["fidelity_tolerance"]),
            f"{label}: fidelity.tolerance differs from v1 fidelity_tolerance")
    require(kind != "empirical" or definition["provisional"] is False,
            f"{label}: a provisional (unreviewed) definition cannot enter an empirical campaign")
    require(kind != "empirical" or not definition.get("waivers"),
            f"{label}: a definition with a pending waiver {definition.get('waivers')} cannot enter an empirical campaign "
            "(D-V: the bank scores only synthetic engineering campaigns until the reviewer records it)")
    return {"task_id": task["id"], "family": definition["family"], "pair_id": definition["pair_id"],
            "definition_sha256": canonical.digest(definition)}


def _task_entries(spec, definitions, kind):
    """Cross-check §4.4 definitions against the v1 spec; return manifest task entries in spec order."""
    require(isinstance(definitions, list) and definitions, "tasks: nonempty list of task definitions required")
    by_id = {}
    for i, definition in enumerate(definitions):
        contracts.validate_task_definition(definition, f"tasks[{i}]")
        require(definition["task_id"] not in by_id, f"tasks: duplicate definition for {definition['task_id']}")
        by_id[definition["task_id"]] = definition
    spec_ids = [t["id"] for t in spec["tasks"]]
    require(set(by_id) == set(spec_ids),
            f"tasks: definitions {sorted(by_id)} differ from v1 spec tasks {sorted(spec_ids)}")
    return [_check_definition(by_id[t["id"]], t, kind, f"task {t['id']}") for t in spec["tasks"]]


def _spec_errors(manifest, spec):
    """Manifest-versus-v1-spec rules shared by write_campaign (before writing) and verify."""
    errors = []
    for name in ("usd_per_run", "seconds_per_run"):
        if canonical.canonical_bytes(manifest["budget"][name]) != canonical.canonical_bytes(spec["budget"][name]):
            errors.append(f"budget.{name}: {manifest['budget'][name]!r} differs from v1 spec.budget "
                          f"{spec['budget'][name]!r}")
    if [t["task_id"] for t in manifest["tasks"]] != [t["id"] for t in spec["tasks"]]:
        errors.append("tasks: task ids must equal the v1 spec task ids in spec order")
    if manifest["source"]["git_commit"] != spec["code_commit"]:
        errors.append("source.git_commit: differs from v1 spec.code_commit")
    host, kind = manifest["host"], manifest["kind"]
    if host["adapter"] == "fake":
        for name in ("model", "runtime"):
            if not spec[name].startswith(SYNTHETIC_LABEL):
                errors.append(f"spec.{name}: a fake-host campaign's v1 spec carries the synthetic label "
                              f"(prefix {SYNTHETIC_LABEL!r}), got {spec[name]!r}")
        return errors
    model, runtime = spec_identity(kind, host)
    synthetic = kind == "synthetic"
    if spec["runtime"] != runtime:
        rule = ("a synthetic campaign's v1 spec carries" if synthetic
                else "an empirical campaign's v1 spec never carries")
        errors.append(f"spec.runtime: {spec['runtime']!r} does not identify the host and the campaign kind; "
                      f"{runtime!r} required ({rule} the synthetic label)")
    if model is not None and spec["model"] != model:
        errors.append(f"spec.model: {spec['model']!r} differs from host.model {host['model']!r}"
                      + (f" with the synthetic label ({model!r} required)" if synthetic else ""))
    elif model is None and not spec["model"].startswith(f"{SYNTHETIC_LABEL} "):
        errors.append(f"spec.model: {spec['model']!r} lacks the synthetic label ({SYNTHETIC_LABEL + ' '!r} prefix) "
                      "of a synthetic campaign whose host model is unknown")
    return errors


def write_campaign(store, *, kind, campaign_id, spec, host, arms, tasks, budget, authorization,
                   created_utc, source, interpreter, subjects_root, approval_record=None) -> Path:
    """Validate everything, then create <store>/<kind>/<campaign_id>/ exactly once.

    ``tasks`` are full §4.4 task definitions (one per v1 task); the manifest stores their digests.
    ``approval_record`` is the bytes that ``authorization.reference_sha256`` names: required when that
    hash is given (and written once as ``approval_record``), refused when it is null.
    Refuses to overwrite an existing campaign directory. campaign.json is written last.
    """
    registry = _v1(experiment.freeze, spec)
    spec_bytes, registry_bytes = v1_bytes(spec), v1_bytes(registry)
    manifest = {
        "schema_version": 1, "campaign_id": campaign_id, "kind": kind, "created_utc": created_utc,
        "spec_sha256": canonical.sha256_bytes(spec_bytes), "registry_sha256": registry["registry_sha256"],
        "registry_file_sha256": canonical.sha256_bytes(registry_bytes), "source": source,
        "interpreter": interpreter, "host": host, "arms": arms, "tasks": _task_entries(spec, tasks, kind),
        "budget": budget, "retry_policy": "none", "authorization": authorization,
        "storage": {"store_kind": kind, "subjects_root": str(subjects_root)},
    }
    contracts.validate_campaign_manifest(manifest)
    errors = _spec_errors(manifest, spec)
    require(not errors, "; ".join(errors))
    reference = authorization["reference_sha256"]
    if reference is None:
        require(approval_record is None, f"{APPROVAL}: given, but authorization.reference_sha256 is null")
    else:
        require(isinstance(approval_record, bytes) and canonical.sha256_bytes(approval_record) == reference,
                f"{APPROVAL}: the bytes whose sha256 is authorization.reference_sha256 are required (the approval "
                "record the authorization names, frozen with the campaign)")
    store = Path(store)
    require(store.is_absolute(), f"store: absolute path required, got {store}")
    require(not _overlap(store, subjects_root), "subjects_root: must be separate from the campaign store")
    namespace = store / kind
    namespace.mkdir(parents=True, exist_ok=True)
    require(not namespace.is_symlink(), f"refusing symlinked campaign namespace {namespace}")
    campaign_dir = namespace / campaign_id
    try:
        campaign_dir.mkdir()
    except FileExistsError:
        raise ContractError(f"refusing to overwrite existing campaign directory {campaign_dir}") from None
    canonical.write_once(campaign_dir / SPEC, spec_bytes)
    canonical.write_once(campaign_dir / REGISTRY, registry_bytes)
    if approval_record is not None:
        canonical.write_once(campaign_dir / APPROVAL, approval_record)
    canonical.write_once(campaign_dir / MANIFEST, manifest_bytes(manifest))
    result = verify(campaign_dir)
    require(result["ok"], f"written campaign failed verification: {result['errors']}")
    return campaign_dir


def _definition_copies(campaign_dir, registry, errors) -> list:
    """(label, path, task_id) of every on-disk task definition: evaluator/<run_id>/task_definition.json
    wherever it exists and, in a runner-built campaign, each definition its frozen family index lists
    (coordinator/family/index.json). An index task outside the v1 spec is a family-only definition (a campaign
    over a task subset keeps the whole family): listed, and checked by ``verify`` for structure only. A v1 spec
    task missing from the index, and an unreadable or unsafe index, are errors (appended)."""
    copies = []
    for run in registry["runs"]:
        path = campaign_dir / "evaluator" / run["run_id"] / TASK_DEFINITION
        if path.exists() or path.is_symlink():
            copies.append((f"evaluator/{run['run_id']}/{TASK_DEFINITION}", path, run["task_id"]))
    index_path = campaign_dir.joinpath(*FAMILY_INDEX)
    if not os.path.lexists(index_path):
        return copies
    label = "/".join(FAMILY_INDEX)
    try:
        index = canonical.strict_load(_regular(index_path, campaign_dir))
        require(isinstance(index, dict) and isinstance(index.get("tasks"), list), "tasks: list required")
        spec_tasks = {r["task_id"] for r in registry["runs"]}
        listed = []
        for i, task in enumerate(index["tasks"]):
            require(isinstance(task, dict) and isinstance(task.get("task_id"), str)
                    and isinstance(task.get("definition_path"), str), f"tasks[{i}]: task_id and definition_path")
            relative = PurePosixPath(task["definition_path"])
            require(relative.parts and not relative.is_absolute() and ".." not in relative.parts,
                    f"tasks[{i}].definition_path: a relative path inside the family required")
            require(task["task_id"] not in listed, f"tasks[{i}]: task {task['task_id']!r} is listed twice")
            listed.append(task["task_id"])
            copies.append((f"{index_path.parent.relative_to(campaign_dir).as_posix()}/{relative.as_posix()}",
                           index_path.parent.joinpath(*relative.parts), task["task_id"]))
        missing = sorted(spec_tasks - set(listed))
        require(not missing, f"the v1 spec tasks {missing} are missing from the family index")
    except READ_ERRORS as exc:
        errors.append(f"{label}: {exc}")
    return copies


def _entry_error(path, directory, label):
    """None when ``path`` does not exist or is a real directory (``directory``) or regular file (lstat, no
    symlink followed); else the error naming ``label``."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{label}: {exc}"
    if stat.S_ISLNK(mode):
        return (f"{label}: a symlink on a seal path; the coordinator never writes one, and neither verify nor "
                "the runner reads a seal through it, so the seal cannot be checked")
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        return f"{label}: not a {'directory' if directory else 'regular file'} (a seal path)"
    return None


def _float_or_bool(value) -> bool:
    """True if a float or a bool occurs anywhere in a parsed JSON value. Without one, JSON values that compare
    equal in Python have equal canonical bytes. runner.evidence_digest now compares the evidence manifest with
    the sealed tree by canonical bytes too; verify still reports such a manifest as an error of its own."""
    if isinstance(value, (bool, float)):
        return True
    if isinstance(value, list):
        return any(_float_or_bool(v) for v in value)
    if isinstance(value, dict):
        return any(_float_or_bool(v) for v in value.values())
    return False


def _sealed_run_record(campaign_dir, run_id) -> tuple:
    """(record, error) for the seal of ``run_id``: (run.json, None) when verify must check that record;
    (None, error) when verify cannot tell whether the runner would trust the seal; (None, None) when no
    seal can be trusted (nothing sealed yet, or runner.seal_problem necessarily refuses it).

    The rule (fail closed, slice design §10a): every seal ``runner.seal_problem`` reconciles is checked
    here. Neither follows a symlink on a seal path (seal_problem rejects one with lstat, as verify does), and
    seal_problem compares evidence_manifest.json with the sealed tree by canonical bytes, verify with the
    journaled digest. Verify stays the stricter of the two, so:
      * a symlink or irregular entry at runs/<run_id>, its journal.jsonl, sealed/, evidence_manifest.json
        or sealed/run.json is an error, whatever the journal says;
      * a malformed (torn) journal is an error: nothing tells whether or how the run was sealed;
      * no journal, or a journal without a ``sealed`` record: nothing sealed, nothing to check;
      * a journal whose ``sealed`` records are not exactly one with a sha256 evidence digest, or an
        evidence manifest that is missing or does not parse: seal_problem refuses it (custody incident);
      * the journaled digest is canonical.digest of the evidence manifest: bound. It must list run.json
        exactly once; when run.json holds the listed bytes, it is parsed and returned (else the tree
        changed after sealing, which seal_problem refuses);
      * the digest differs: seal_problem refuses it, unless the manifest holds a float or bool (a
        value-equal rewrite of the coordinator's integers, which an older seal_problem accepted), an error."""
    run_dir, label = campaign_dir / RUNS / run_id, f"{RUNS}/{run_id}"
    for parts, directory in (((), True), ((JOURNAL,), False), ((SEALED,), True), ((EVIDENCE_MANIFEST,), False),
                             ((SEALED, RUN_RECORD), False)):
        error = _entry_error(run_dir.joinpath(*parts), directory, "/".join((label,) + parts))
        if error is not None:
            return None, error
    journal = run_dir / JOURNAL
    if not os.path.lexists(journal):
        return None, None
    try:
        records, torn = canonical.read_jsonl(journal)
    except READ_ERRORS as exc:
        return None, f"{label}/{JOURNAL}: {exc}"
    if torn is not None:
        return None, (f"{label}/{JOURNAL}: malformed journal ({torn}); verify cannot tell whether or how the run "
                      "was sealed (repair by hand, never guess)")
    seals = [r["details"].get("evidence_sha256") for r in records
             if isinstance(r, dict) and r.get("state") == "sealed" and isinstance(r.get("details"), dict)]
    if len(seals) != 1 or not canonical.is_sha256(seals[0]):
        return None, None
    try:
        entries = canonical.strict_load(run_dir / EVIDENCE_MANIFEST)
        journaled = canonical.digest(entries) == seals[0]
    except READ_ERRORS:
        return None, None
    if not journaled:
        if _float_or_bool(entries):
            return None, (f"{label}/{EVIDENCE_MANIFEST}: holds a float or boolean where the coordinator writes "
                          "integers, and its digest is not the journaled seal: not the manifest the coordinator "
                          "sealed, so verify cannot tell whether the seal reconciles")
        return None, None
    listed = [e for e in entries if isinstance(e, dict) and e.get("path") == RUN_RECORD] \
        if isinstance(entries, list) else []
    if len(listed) != 1:
        return None, (f"{label}: the journaled seal lists {RUN_RECORD} {len(listed)} times; every coordinator seal "
                      "lists it once")
    try:
        data = (run_dir / SEALED / RUN_RECORD).read_bytes()
    except OSError:
        return None, None
    if listed[0] != {"path": RUN_RECORD, "sha256": canonical.sha256_bytes(data), "bytes": len(data)}:
        return None, None
    try:
        return canonical.strict_loads(data.decode()), None
    except READ_ERRORS as exc:
        return None, f"{label}/{SEALED}/{RUN_RECORD}: {exc}"


def _sealed_run_errors(campaign_dir, manifest, runs) -> list:
    """Check the sealed run.json of each run in ``runs`` (``_sealed_run_record``): it must validate and name
    this assignment, campaign, kind, synthetic label and adapter, so the kind a run was sealed under cannot
    be relabeled around it, and a seal verify cannot check is an error."""
    error = _entry_error(campaign_dir / RUNS, True, RUNS)
    if error is not None:
        return [error]
    errors = []
    for run in runs:
        record, error = _sealed_run_record(campaign_dir, run["run_id"])
        if error is not None:
            errors.append(error)
        if record is None:
            continue
        label = f"{RUNS}/{run['run_id']}/{SEALED}/{RUN_RECORD}"
        try:
            contracts.validate_run_record(record, label)
        except READ_ERRORS as exc:
            errors.append(str(exc))
            continue
        expected = {"run_id": run["run_id"], "campaign_id": manifest["campaign_id"],
                    "campaign_kind": manifest["kind"], "synthetic": manifest["kind"] == "synthetic",
                    "adapter": manifest["host"]["adapter"], "task_id": run["task_id"], "seed": run["seed"],
                    "arm": run["arm"]}
        errors += [f"{label}.{name}: {record[name]!r} differs from this campaign's {value!r} (the run record sealed "
                   "and journaled when the run closed)"
                   for name, value in expected.items()
                   if type(record[name]) is not type(value) or record[name] != value]
    return errors


# A smoke approval (E-204) binds neither the broker limits nor the order of the roster: it authorizes only the smoke's
# size and the runner's default limits (runner.DEFAULT_BUDGET's, restated here: the evaluator's import graph never
# reaches the coordinator; a test keeps them equal). A larger roster or other limits need a pilot approval (E-211).
SMOKE_MAX_ASSIGNMENTS = 8
SMOKE_BROKER_LIMITS = {"max_broker_ops": 40, "max_fits": 4, "max_stage_executions": 6}


def approval_scope_problems(approval: dict, *, spec, host, budget, arms) -> list:
    """Why ``approval`` (a real-host synthetic campaign's approval record) does not cover this campaign ([] when it
    does), from the campaign's own files: ``spec`` the v1 spec (task ids, seeds, schedule seed), ``host`` the pinned
    host fields (adapter, version, executable_sha256, model, effort), ``budget`` the manifest budget and ``arms`` the
    arm names in the campaign's order. The caps must equal the budget exactly (canonical bytes: 2.0 is not 2), runs and
    assignments the roster (every task x seed in every arm), the scope the spec's, the host fields the pin's, and shared
    quota accepted. A pilot's approval (E-204) also binds the schedule: its schedule_seed must equal the spec's, its task
    list, seeds and arms the campaign's in their order, and its broker_limits the budget's (canonical bytes). A smoke's
    covers at most SMOKE_MAX_ASSIGNMENTS assignments and only SMOKE_BROKER_LIMITS (E-211). The build
    (live.approval_problems) adds the credential variable, the pilot's host settings and the ledger; ``verify`` and
    preflight re-run this against the frozen record (E-211), so a campaign rewritten after its build is refused."""
    try:
        contracts.validate_smoke_approval(approval)
    except ContractError as exc:
        return [str(exc)]
    problems = []
    pilot = approval["kind"] == contracts.PILOT_APPROVAL_KIND
    for name in ("usd_per_run", "seconds_per_run", "global_usd_cap", "global_seconds_cap"):
        if name not in budget or canonical.canonical_bytes(approval["caps"][name]) != canonical.canonical_bytes(
                budget[name]):
            problems.append(f"caps.{name} {approval['caps'][name]!r} differs from the campaign budget's "
                            f"{budget.get(name)!r}")
    tasks = [t["id"] for t in spec["tasks"]]
    roster = len(tasks) * len(spec["seeds"]) * len(list(arms))
    scope = approval["scope"]
    for name, mine, theirs in (("tasks", scope["tasks"], tasks), ("seeds", scope["seeds"], spec["seeds"]),
                               ("arms", scope["arms"], list(arms))):
        if sorted(mine) != sorted(theirs):
            problems.append(f"scope.{name} {sorted(mine)} differs from the campaign's {sorted(theirs)}")
        elif pilot and list(mine) != list(theirs):
            problems.append(f"scope.{name} {list(mine)} is not in the campaign's order {list(theirs)} (a pilot's "
                            "approval binds the schedule)")
    if pilot:
        if "schedule_seed" not in spec or canonical.canonical_bytes(approval["schedule_seed"]) != \
                canonical.canonical_bytes(spec["schedule_seed"]):
            problems.append(f"schedule_seed {approval['schedule_seed']!r} differs from the campaign's "
                            f"{spec.get('schedule_seed')!r}")
        for name in contracts.BROKER_LIMIT_FIELDS:
            mine = approval["broker_limits"][name]
            if name not in budget or canonical.canonical_bytes(mine) != canonical.canonical_bytes(budget[name]):
                problems.append(f"broker_limits.{name} {mine!r} differs from the campaign budget's "
                                f"{budget.get(name)!r}")
    else:
        if roster > SMOKE_MAX_ASSIGNMENTS:
            problems.append(f"a smoke approval covers at most {SMOKE_MAX_ASSIGNMENTS} assignments, not {roster}: a "
                            f"larger campaign needs a {contracts.PILOT_APPROVAL_KIND} approval (E-211)")
        for name, default in SMOKE_BROKER_LIMITS.items():
            if budget.get(name, default) != default:
                problems.append(f"budget.{name} {budget.get(name)!r}: a smoke approval binds no broker limits, so it "
                                f"covers only the default {default!r}; other limits need a "
                                f"{contracts.PILOT_APPROVAL_KIND} approval (E-211)")
    if scope["assignments"] != roster or approval["caps"]["runs"] != roster:
        problems.append(f"scope.assignments/caps.runs {scope['assignments']}/{approval['caps']['runs']} differ from "
                        f"the {roster} assignments of the roster")
    for name in contracts.SMOKE_HOST_FIELDS:
        if scope["host"][name] != host.get(name):
            problems.append(f"scope.host.{name} {scope['host'][name]!r} differs from the pinned host's "
                            f"{host.get(name)!r}")
    if approval["account_preconditions"]["shared_quota_accepted"] is not True:
        problems.append("account_preconditions.shared_quota_accepted: the budget owner has not accepted runs "
                        "drawing on the shared subscription quota")
    return problems


def approval_host_fields(host) -> dict:
    """The fields an approval's scope.host names, from a campaign's frozen host configuration (its reasoning is
    "--effort <level>")."""
    reasoning = host.get("reasoning") or ""
    return {"adapter": host.get("adapter"), "version": host.get("version"),
            "executable_sha256": host.get("executable_sha256"), "model": host.get("model"),
            "effort": reasoning[len("--effort "):] if reasoning.startswith("--effort ") else None}


def campaign_arms(manifest) -> list:
    """The campaign's arm names in the order its roster was built from (contracts.ARMS when it holds exactly them)."""
    names = list(manifest["arms"])
    return list(contracts.ARMS) if sorted(names) == sorted(contracts.ARMS) else sorted(names)


def frozen_approval(campaign_dir, manifest):
    """(the approval record, the problems of its scope against this campaign's files) of a real-host synthetic
    campaign; (None, []) for any other campaign (its approval, if any, is a record this module does not read)."""
    authorization = manifest["authorization"]
    if authorization["kind"] != "synthetic_engineering" or authorization["reference_sha256"] is None \
            or manifest["host"]["adapter"] == "fake":
        return None, []
    try:
        approval = canonical.strict_loads(_regular(campaign_dir / APPROVAL, campaign_dir).read_bytes().decode("utf-8"))
        spec = canonical.strict_loads(_regular(campaign_dir / SPEC, campaign_dir).read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, *READ_ERRORS) as exc:
        return None, [f"the frozen approval record or spec cannot be read ({exc})"]
    if not isinstance(approval, dict):
        return None, ["the frozen approval record is no JSON object"]
    return approval, approval_scope_problems(approval, spec=spec, host=approval_host_fields(manifest["host"]),
                                             budget=manifest["budget"], arms=campaign_arms(manifest))


def _approval_errors(campaign_dir, manifest) -> list:
    """An authorization's reference_sha256, when given, must be the sha256 of the approval record frozen
    with the campaign; with none given there is no approval record. A real-host synthetic campaign's frozen approval
    must still cover the campaign's files (approval_scope_problems, E-211)."""
    reference, path = manifest["authorization"]["reference_sha256"], campaign_dir / APPROVAL
    if reference is None:
        present = os.path.lexists(path)
        return [f"{APPROVAL}: present, but authorization.reference_sha256 is null"] if present else []
    try:
        data = _regular(path, campaign_dir).read_bytes()
    except READ_ERRORS as exc:
        return [f"{APPROVAL}: authorization.reference_sha256 must resolve to the approval record frozen with the "
                f"campaign ({exc})"]
    if canonical.sha256_bytes(data) != reference:
        return [f"{APPROVAL}: sha256 differs from authorization.reference_sha256"]
    _, problems = frozen_approval(campaign_dir, manifest)
    return [f"{APPROVAL}: does not cover the campaign: {p}" for p in problems]


BANK_INDEX_KEYS = ("contrasts", "visible_oracle_values")   # a task-bank index (bank_version) must carry both


def _environment_errors(campaign_dir, manifest) -> list:
    """A runner-built campaign's ``coordinator/environment.json``, when present, binds its family index: its
    ``family_index_sha256`` must be the index's sha256 and its canonical digest the host's
    ``environment_manifest_sha256`` (the runner's own load rule, so a verified campaign's index is the frozen one)."""
    path, label = campaign_dir / "coordinator" / "environment.json", "coordinator/environment.json"
    if not os.path.lexists(path):
        return []
    try:
        environment = canonical.strict_load(_regular(path, campaign_dir))
        index = campaign_dir.joinpath(*FAMILY_INDEX)
        errors = []
        if canonical.digest(environment) != manifest["host"]["environment_manifest_sha256"]:
            errors.append(f"{label}: its digest is not host.environment_manifest_sha256")
        if os.path.lexists(index) and (not isinstance(environment, dict) or environment.get("family_index_sha256")
                                       != canonical.sha256_file(_regular(index, campaign_dir))):
            errors.append(f"{label}: family_index_sha256 is not the sha256 of {'/'.join(FAMILY_INDEX)} (the frozen "
                          "family index was changed)")
        return errors
    except READ_ERRORS as exc:
        return [f"{label}: {exc}"]


def _bank_errors(campaign_dir, bank) -> list:
    """A runner-built campaign freezes the whole task bank (``coordinator/family/index.json`` with its
    ``contrasts``, schema_version 2 definitions): the bank rules (``contracts.validate_task_bank``: twins,
    identical request bytes, budget and operations, each contrast's declared differences) are re-derived over
    every definition the index lists. A family index without contrasts (a hand-built v1 family, or a family frozen
    before WP12) has none; a task-bank index (it names a ``bank_version``) without ``contrasts`` or
    ``visible_oracle_values`` is an error, never a bank without rules. An index whose tasks or definitions could
    not all be read is already an error, so the rules are not applied to part of the bank."""
    label = "/".join(FAMILY_INDEX)
    if not bank or any(d is None for d in bank.values()):
        return []
    try:
        index = canonical.strict_load(_regular(campaign_dir.joinpath(*FAMILY_INDEX), campaign_dir))
    except READ_ERRORS as exc:
        return [f"{label}: {exc}"]
    if isinstance(index, dict) and "bank_version" in index:
        missing = [key for key in BANK_INDEX_KEYS if not isinstance(index.get(key), list)]
        if missing:
            return [f"{label}: a task-bank index (bank_version {index['bank_version']!r}) without {missing}: its bank "
                    "rules cannot be re-derived"]
    if not isinstance(index, dict) or "contrasts" not in index:
        return []
    if [t.get("task_id") if isinstance(t, dict) else None for t in index.get("tasks") or []] != list(bank):
        return []
    try:
        contracts.validate_task_bank(list(bank.values()), index["contrasts"], label,
                                     visible_oracle_values=index.get("visible_oracle_values", []))
    except READ_ERRORS as exc:   # the message names the index and the offending entry
        return [str(exc)]
    return []


def verify(campaign_dir, *, sealed_runs=None) -> dict:
    """Re-derive every §4.1 invariant from the files on disk (spec, registry, manifest and any approval
    record must be regular files). Task definitions are checked wherever they already exist (evaluator
    copies and a runner-built campaign's frozen family), and each run's seal (``_sealed_run_record``):
    every seal the runner would trust has its run.json checked against the registry and the manifest,
    and a seal verify cannot check (symlinked, irregular, torn journal) is an error.

    ``sealed_runs`` (default: every registry run) limits the seal check to these registry run ids, for a
    caller that trusts one run's seal (audit.build_report); every other check is unchanged.
    Returns {"ok": bool, "errors": [...]}; never raises on bad files."""
    campaign_dir = Path(campaign_dir).resolve()
    try:
        manifest = canonical.strict_load(_regular(campaign_dir / MANIFEST, campaign_dir))
        contracts.validate_campaign_manifest(manifest)
    except READ_ERRORS as exc:
        return {"ok": False, "errors": [f"{MANIFEST}: {exc}"]}
    errors = []
    if campaign_dir.name != manifest["campaign_id"]:
        errors.append(f"namespace: directory {campaign_dir.name!r} is not campaign_id {manifest['campaign_id']!r}")
    if campaign_dir.parent.name != manifest["kind"]:
        errors.append(f"namespace: a {manifest['kind']} campaign must live under <store>/{manifest['kind']}/, "
                      f"found {campaign_dir.parent.name!r}")
    if _overlap(campaign_dir.parent.parent, manifest["storage"]["subjects_root"]):
        errors.append("storage.subjects_root: overlaps the campaign store")
    try:
        spec_bytes = _regular(campaign_dir / SPEC, campaign_dir).read_bytes()
        if canonical.sha256_bytes(spec_bytes) != manifest["spec_sha256"]:
            errors.append(f"{SPEC}: sha256 differs from campaign spec_sha256")
        spec = canonical.strict_loads(spec_bytes.decode())
        if v1_bytes(spec) != spec_bytes:
            errors.append(f"{SPEC}: bytes are not the exact v1 serialization of their content")
        registry = _v1(experiment.freeze, spec)
    except READ_ERRORS as exc:
        return {"ok": False, "errors": errors + [f"{SPEC}: {exc}"]}
    try:
        registry_bytes = _regular(campaign_dir / REGISTRY, campaign_dir).read_bytes()
    except READ_ERRORS as exc:
        errors.append(f"{REGISTRY}: {exc}")
    else:
        if registry_bytes != v1_bytes(registry):
            errors.append(f"{REGISTRY}: bytes differ from the v1 freeze of {SPEC} (altered types, key order "
                          "or formatting; value equality is not accepted)")
        if canonical.sha256_bytes(registry_bytes) != manifest["registry_file_sha256"]:
            errors.append(f"{REGISTRY}: sha256 differs from campaign registry_file_sha256")
    if registry["registry_sha256"] != manifest["registry_sha256"]:
        errors.append(f"registry_sha256: differs from the v1 freeze of {SPEC}")
    errors += _spec_errors(manifest, spec)
    errors += _approval_errors(campaign_dir, manifest)
    tasks = {t["id"]: t for t in spec["tasks"]}
    entries = {t["task_id"]: t for t in manifest["tasks"]}
    family_prefix = "/".join(FAMILY_INDEX[:-1]) + "/"
    bank = {}   # task id -> the definition the frozen family index lists (None when it cannot be read)
    for label, path, task_id in _definition_copies(campaign_dir, registry, errors):
        from_index = label.startswith(family_prefix)
        try:
            definition = canonical.strict_load(_regular(path, campaign_dir))
        except READ_ERRORS as exc:
            errors.append(f"{label}: {exc}")
            if from_index:
                bank[task_id] = None
            continue
        if from_index:
            bank[task_id] = definition
        if task_id not in tasks:   # a family-only definition (the campaign runs a task subset): structure only
            try:
                contracts.validate_task_definition(definition, label)
                require(definition["task_id"] == task_id,
                        f"{label}: is for task {definition['task_id']!r}, not the family index's {task_id!r}")
            except ContractError as exc:
                errors.append(str(exc))
            continue
        try:
            entry = _check_definition(definition, tasks[task_id], manifest["kind"], label)
        except ContractError as exc:  # the message already names the file
            errors.append(str(exc))
            continue
        recorded = entries.get(task_id, {})
        for name in ("family", "pair_id", "definition_sha256"):
            if entry[name] != recorded.get(name):
                errors.append(f"{label}: {name} {entry[name]!r} differs from the manifest task entry "
                              f"({recorded.get(name)!r})")
    errors += _bank_errors(campaign_dir, bank)
    errors += _environment_errors(campaign_dir, manifest)
    runs = registry["runs"]
    if sealed_runs is not None:
        planned = {r["run_id"] for r in runs}
        if (isinstance(sealed_runs, (list, tuple)) and sealed_runs
                and all(isinstance(r, str) and r in planned for r in sealed_runs)):
            wanted = set(sealed_runs)
            runs = [r for r in runs if r["run_id"] in wanted]
        else:
            errors.append("sealed_runs: a nonempty list of this campaign's registry run ids (or None for all)")
    errors += _sealed_run_errors(campaign_dir, manifest, runs)
    return {"ok": not errors, "errors": errors}


def verify_run_provenance(campaign_dir, judge_reports) -> dict:
    """Verify the campaign, then reject judge reports that disagree with it on campaign_id,
    campaign_kind, synthetic label, adapter, assignment or oracle (packet CONTRACT_16: a
    synthetic cohort relabeled as empirical fails). The campaign check includes the sealed run record
    of every seal the runner would trust (and fails on any seal it cannot check), so the labels a report
    is held to are also the ones its run was sealed under; and since the kind is part of the v1 spec for
    every host, a synthetic cohort's run ids are never an empirical registry's, even with every
    self-declared label forged. A seal the runner refuses (changed after sealing) is not read here;
    runner.write_outcomes and report refuse it as a custody incident.
    Returns {"ok": bool, "errors": [...]}."""
    result = verify(campaign_dir)
    if not result["ok"]:
        return {"ok": False, "errors": [f"campaign: {e}" for e in result["errors"]]}
    campaign_dir = Path(campaign_dir).resolve()
    manifest = canonical.strict_load(campaign_dir / MANIFEST)
    registry = canonical.strict_load(campaign_dir / REGISTRY)
    runs = {r["run_id"]: r for r in registry["runs"]}
    oracles = {t["id"]: t["oracle_sha256"] for t in registry["spec"]["tasks"]}
    expected = {"campaign_id": manifest["campaign_id"], "campaign_kind": manifest["kind"],
                "synthetic": manifest["kind"] == "synthetic", "adapter": manifest["host"]["adapter"]}
    if not isinstance(judge_reports, list):
        return {"ok": False, "errors": ["judge_reports: list required"]}
    errors, seen = [], set()
    for i, report in enumerate(judge_reports):
        label = f"judge_reports[{i}]"
        try:
            contracts.validate_judge_report(report, label)
        except (ContractError, RecursionError) as exc:
            errors.append(str(exc))
            continue
        for name, value in expected.items():
            if report[name] != value:
                errors.append(f"{label}.{name}: {report[name]!r} disagrees with the campaign manifest ({value!r})")
        run = runs.get(report["run_id"])
        if run is None:
            errors.append(f"{label}.run_id: not an assignment in this campaign's registry")
        elif report["oracle_sha256"] != oracles[run["task_id"]]:
            errors.append(f"{label}.oracle_sha256: differs from the v1 oracle_sha256 of task {run['task_id']}")
        if report["run_id"] in seen:
            errors.append(f"{label}.run_id: duplicate judge report")
        seen.add(report["run_id"])
    return {"ok": not errors, "errors": errors}


def interpreter_record(executable) -> dict:
    """Pin an interpreter: {executable (path as given), version, sha256 of the resolved binary}."""
    path = str(executable)
    require(os.path.isabs(path) and os.path.normpath(path) == path,
            f"interpreter: normalized absolute path required, got {path!r}")
    try:
        resolved = Path(path).resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"interpreter: cannot resolve {path!r}: {exc}") from exc
    require(resolved.is_file() and os.access(resolved, os.X_OK), f"interpreter: not an executable file: {resolved}")
    probe = "import platform; print(platform.python_implementation(), platform.python_version())"
    try:
        done = subprocess.run([path, "-I", "-c", probe], capture_output=True, text=True, timeout=60,
                              env={}, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"interpreter: version probe failed: {exc}") from exc
    version = done.stdout.strip()
    require(done.returncode == 0 and PYTHON_VERSION.fullmatch(version) is not None,
            f"interpreter: version probe failed (exit {done.returncode}, output {version[:80]!r})")
    return {"executable": path, "version": version, "sha256": canonical.sha256_file(resolved)}
