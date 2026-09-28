"""Campaign manifest build/verify tests (slice design §3, §4.1). Every spec, campaign, host,
approval reference and judge report here is a SYNTHETIC software-test fixture, not agent evidence
and not an approval."""
import copy
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from governance import campaign_manifest as cm
from governance import canonical, contracts, runner
from governance.canonical import ContractError

experiment = contracts.experiment
V1_CLI = Path(contracts.__file__).with_name("experiment.py")


def sha(label):
    return hashlib.sha256(f"synthetic-fixture:{label}".encode()).hexdigest()


def spec(real_host=None, kind="synthetic"):
    """The v1 spec for the fake host (synthetic labels) or, given a real host config, bound to that host
    and to the campaign kind: an empirical spec declares the host exactly, a synthetic one prefixes both
    the runtime and the model with the synthetic label (the rule is restated here, not imported)."""
    model, runtime = "synthetic-fake-subject", "synthetic-fake-adapter"
    if real_host is not None:
        model, runtime = real_host["model"], f"{real_host['adapter']} {real_host['version']}"
        if kind == "synthetic":
            model, runtime = f"synthetic {model}", f"synthetic {runtime}"
    return {"experiment_id": "synthetic-fixture-campaign", "protocol_sha256": sha("protocol"),
            "code_commit": "b" * 40, "environment_sha256": sha("environment"),
            "model": model, "runtime": runtime, "schedule_seed": 42,
            "seeds": [11], "budget": {"usd_per_run": 1, "seconds_per_run": 60},
            "tasks": [{"id": "lf-a", "expected": "complete", "prompt_sha256": sha("prompt"),
                       "oracle_sha256": sha("oracle-lf-a"), "fidelity_tolerance": 0.005},
                      {"id": "lf-d", "expected": "refuse", "prompt_sha256": sha("prompt"),
                       "oracle_sha256": sha("oracle-lf-d"), "fidelity_tolerance": None}]}


def definition(task_id, expected, provisional=True):
    refusing = expected == "refuse"
    inputs = [{"name": "workspace.json", "kind": "workspace", "sha256": sha("workspace")},
              {"name": "title.txt", "kind": "title", "sha256": sha("title")}]
    if not refusing:
        inputs.append({"name": "luminosity.json", "kind": "luminosity", "sha256": sha("luminosity")})
    return {"schema_version": 1, "task_id": task_id, "family": "likelihood_freshness",
            "pair_id": "synthetic-pair-1", "variant": "V3 missing authority" if refusing else "V2 conversion-only",
            "expected": expected, "stratum": "S1", "prompt_sha256": sha("prompt"), "inputs": inputs,
            "prior_inputs": [{"name": "workspace.json", "kind": "workspace", "sha256": sha("workspace")},
                             {"name": "luminosity.json", "kind": "luminosity", "sha256": sha("prior-lumi")}],
            "required_claims": [] if refusing else [{"field": "sigma_vis_obs_fb", "role": "observed", "unit": "fb"}],
            "required_title": None, "refusal_conditions": ["no authorized luminosity record"] if refusing else [],
            "fidelity": {"metric": "relative_error", "quantity": "sigma_vis_obs_fb",
                         "tolerance": None if refusing else 0.005},
            "reuse_expectation": "refuse_convert" if refusing else "recompute_convert",
            "oracle_sha256": sha(f"oracle-{task_id}"),
            "source": {"kind": "synthetic_development", "license": "Apache-2.0"}, "provisional": provisional}


def host(adapter="fake"):
    record = {"schema_version": 1, "adapter": "fake", "executable": None, "executable_sha256": None,
              "version": None, "model": None, "reasoning": None, "sampling": None,
              "context_policy": "fresh_session", "memory_policy": "none", "subagent_policy": "none",
              "tool_allowlist": [], "network": "localhost", "sandbox": "seatbelt",
              "environment_manifest_sha256": sha("environment"), "cost_source": "none_synthetic",
              "unknown_fields": []}
    if adapter != "fake":
        record.update(adapter=adapter, executable=f"/opt/synthetic-fixture/{adapter}",
                      executable_sha256=sha(adapter), version="0.0.0-synthetic", model="synthetic-fixture-model",
                      cost_source="host_reported", unknown_fields=["reasoning", "sampling"])
    return record


def arms():
    result = {}
    for arm, factors in contracts.ARMS.items():
        result[arm] = {"schema_version": 1, "arm": arm,
                       "instructions": {"included": factors["instructions"],
                                        "text_sha256": sha("instructions") if factors["instructions"] else None},
                       "guard": {"mode": "block" if factors["enforcement"] else "audit",
                                 "feedback": "diagnostic" if factors["enforcement"] else "silent",
                                 "implementation_sha256": sha("guard")},
                       "common": {name: sha(name) for name in contracts.COMMON_FIELDS},
                       "prompt_template_sha256": sha("template+instructions" if factors["instructions"]
                                                     else "template")}
    return result


SYNTHETIC_AUTH = {"kind": "synthetic_engineering", "reference": "SYNTHETIC engineering test fixture; not an approval",
                  "reference_sha256": None}
# The bytes FIXTURE_APPROVAL's reference_sha256 names (sha("approval")): a SYNTHETIC stand-in, approves nothing.
APPROVAL_RECORD = b"synthetic-fixture:approval"
FIXTURE_APPROVAL = {"kind": "approved_campaign",
                    "reference": "SYNTHETIC test fixture standing in for an approval record; approves nothing",
                    "reference_sha256": hashlib.sha256(APPROVAL_RECORD).hexdigest()}
assert FIXTURE_APPROVAL["reference_sha256"] == sha("approval")


def campaign_args(tmp_path, kind="synthetic", **changes):
    args = {"kind": kind, "campaign_id": "synthetic-fixture-campaign", "spec": spec(), "host": host(),
            "arms": arms(), "tasks": [definition("lf-a", "complete"), definition("lf-d", "refuse")],
            "budget": {"usd_per_run": 1, "seconds_per_run": 60, "max_broker_ops": 40, "max_fits": 4,
                       "max_stage_executions": 6, "global_usd_cap": 8, "global_seconds_cap": 480},
            "authorization": dict(SYNTHETIC_AUTH), "created_utc": "2026-09-25T12:00:00Z",
            "source": {"git_commit": "b" * 40, "dirty": True},
            "interpreter": {"executable": "/usr/bin/python3", "version": "CPython 3.12.0", "sha256": sha("python")},
            "subjects_root": str(tmp_path / "subjects")}
    if kind == "empirical":
        args.update(campaign_id="synthetic-fixture-empirical-namespace-test", host=host("claude_cli"),
                    spec=spec(host("claude_cli"), "empirical"), approval_record=APPROVAL_RECORD,
                    authorization=dict(FIXTURE_APPROVAL), source={"git_commit": "b" * 40, "dirty": False},
                    tasks=[definition("lf-a", "complete", False), definition("lf-d", "refuse", False)])
    args.update(changes)
    return args


def write(tmp_path, kind="synthetic", **changes):
    return cm.write_campaign(tmp_path / "store", **campaign_args(tmp_path, kind, **changes))


def rewrite(path, data):
    path.chmod(0o644)
    path.write_bytes(data)


def edit_manifest(campaign_dir, change):
    manifest = canonical.strict_load(campaign_dir / cm.MANIFEST)
    change(manifest)
    rewrite(campaign_dir / cm.MANIFEST, cm.manifest_bytes(manifest))


def materialize_definitions(campaign_dir, definitions):
    """Write evaluator/<run_id>/task_definition.json for every planned run, as the runner will."""
    registry = json.loads((campaign_dir / "registry.json").read_bytes())
    by_id = {d["task_id"]: d for d in definitions}
    for run in registry["runs"]:
        target = campaign_dir / "evaluator" / run["run_id"] / "task_definition.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(0o644)
        target.write_bytes(canonical.canonical_bytes(by_id[run["task_id"]]))
    return registry


def error_text(result):
    assert result["ok"] is False and result["errors"]
    return "\n".join(result["errors"])


SEALED_AT = ("2026-09-25T12:00:00.000000Z", "2026-09-25T12:00:05.000000Z")
SEALED_EXECUTOR = "synthetic-fixture-executor"   # the executor_id seal_runs seals
STUB_SCORER = "synthetic-stub-judge (test fixture)"


def seal_runs(campaign_dir, **overrides):
    """SYNTHETIC runner-shaped seals (runner._seal, slice design §10a), no process involved: per registry
    run a sealed/run.json and prompt.txt, evidence_manifest.json (canonical.tree_manifest of sealed/) and a
    journal closing the run and recording its one ``sealed`` record with canonical.digest of that
    manifest. ``overrides`` replace run.json fields. Returns {run_id: journaled evidence digest}."""
    manifest = canonical.strict_load(campaign_dir / "campaign.json")
    registry = json.loads((campaign_dir / "registry.json").read_bytes())
    digests = {}
    for run in registry["runs"]:
        rdir = campaign_dir / "runs" / run["run_id"]
        record = {"schema_version": 1, "run_id": run["run_id"], "campaign_id": manifest["campaign_id"],
                  "campaign_kind": manifest["kind"], "task_id": run["task_id"], "seed": run["seed"],
                  "arm": run["arm"], "opaque_handle": sha(f"opaque-{run['run_id']}")[:16],
                  "adapter": manifest["host"]["adapter"], "synthetic": manifest["kind"] == "synthetic",
                  "executor_id": SEALED_EXECUTOR, "behavior": None, "behavior_plan_sha256": None,
                  "started_utc": SEALED_AT[0], "ended_utc": SEALED_AT[1], "status_hint": "exited",
                  "not_started_reason": None,
                  "treatment_manifest_sha256": canonical.digest(manifest["arms"][run["arm"]]),
                  "prompt_sha256": sha("prompt"), "profile_sha256": None, "validity_flags": [], **overrides}
        canonical.write_once(rdir / "sealed" / "run.json",
                             (json.dumps(record, indent=1, sort_keys=True) + "\n").encode())
        canonical.write_once(rdir / "sealed" / "prompt.txt", b"SYNTHETIC fixture prompt\n")
        entries = canonical.tree_manifest(rdir / "sealed")
        canonical.write_once(rdir / "evidence_manifest.json", (json.dumps(entries, indent=1) + "\n").encode())
        digests[run["run_id"]] = canonical.digest(entries)
        journal = rdir / "journal.jsonl"
        canonical.append_jsonl(journal, {"state": "exited", "time_utc": SEALED_AT[1],
                                         "details": {"status_hint": "exited", "exit_code": 0}})
        canonical.append_jsonl(journal, {"state": "sealed", "time_utc": SEALED_AT[1],
                                         "details": {"evidence_sha256": digests[run["run_id"]],
                                                     "files": len(entries), "output_violations": []}})
    return digests


def relabel_in_place(campaign_dir, real_host):
    """SYNTHETIC store writer: copy a synthetic campaign (runs and journals included) into the empirical
    namespace and meet every manifest-level empirical requirement there: kind and store_kind, an
    approved_campaign authorization whose reference resolves to a frozen approval record, a clean source
    tree and a real host. spec.json and registry.json are left as they were."""
    moved = campaign_dir.parent.parent / "empirical" / campaign_dir.name
    moved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(campaign_dir, moved)
    edit_manifest(moved, lambda m: (m.update(kind="empirical", authorization=dict(FIXTURE_APPROVAL), host=real_host,
                                             source={"git_commit": "b" * 40, "dirty": False}),
                                    m["storage"].update(store_kind="empirical")))
    (moved / cm.APPROVAL).write_bytes(APPROVAL_RECORD)
    contracts.validate_campaign_manifest(canonical.strict_load(moved / "campaign.json"))   # every manifest rule met
    return moved


def refreeze(campaign_dir, new_spec):
    """SYNTHETIC store writer going further: replace spec.json and registry.json by the exact v1 bytes of
    ``new_spec`` (new run ids), rehash the manifest and move every run directory to the new run id of the
    same (task, seed, arm). Returns {old run_id: new run_id}."""
    old = json.loads((campaign_dir / "registry.json").read_bytes())
    registry = experiment.freeze(new_spec)
    rewrite(campaign_dir / "spec.json", cm.v1_bytes(new_spec))
    rewrite(campaign_dir / "registry.json", cm.v1_bytes(registry))
    edit_manifest(campaign_dir, lambda m: m.update(
        spec_sha256=hashlib.sha256(cm.v1_bytes(new_spec)).hexdigest(), registry_sha256=registry["registry_sha256"],
        registry_file_sha256=hashlib.sha256(cm.v1_bytes(registry)).hexdigest()))
    new_ids = {(r["task_id"], r["seed"], r["arm"]): r["run_id"] for r in registry["runs"]}
    moved = {r["run_id"]: new_ids[(r["task_id"], r["seed"], r["arm"])] for r in old["runs"]}
    for old_id, new_id in moved.items():
        (campaign_dir / "runs" / old_id).rename(campaign_dir / "runs" / new_id)
    return moved


# ---- write + verify ---------------------------------------------------------------------------

def test_write_then_verify_round_trip_with_exact_v1_bytes(tmp_path):
    record = cm.interpreter_record(sys.executable)
    campaign_dir = write(tmp_path, interpreter=record)
    assert campaign_dir == tmp_path / "store" / "synthetic" / "synthetic-fixture-campaign"
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    spec_bytes = (campaign_dir / "spec.json").read_bytes()
    assert spec_bytes == (json.dumps(spec(), indent=2, allow_nan=False) + "\n").encode()
    cli = subprocess.run([sys.executable, str(V1_CLI), "freeze", str(campaign_dir / "spec.json")],
                         capture_output=True, check=True)
    registry_bytes = (campaign_dir / "registry.json").read_bytes()
    assert registry_bytes == cli.stdout  # exactly what the unchanged v1 CLI prints
    manifest = canonical.strict_load(campaign_dir / "campaign.json")
    contracts.validate_campaign_manifest(manifest)
    assert manifest["spec_sha256"] == hashlib.sha256(spec_bytes).hexdigest()
    assert manifest["registry_file_sha256"] == hashlib.sha256(registry_bytes).hexdigest()
    assert manifest["registry_sha256"] == json.loads(registry_bytes)["registry_sha256"]
    assert manifest["interpreter"] == record
    assert manifest["storage"] == {"store_kind": "synthetic", "subjects_root": str(tmp_path / "subjects")}
    assert [t["definition_sha256"] for t in manifest["tasks"]] == [
        canonical.digest(definition("lf-a", "complete")), canonical.digest(definition("lf-d", "refuse"))]
    assert manifest["retry_policy"] == "none" and manifest["kind"] == "synthetic"
    for name in ("spec.json", "registry.json", "campaign.json"):
        assert (campaign_dir / name).stat().st_mode & 0o222 == 0, name


def test_refuses_to_overwrite_an_existing_campaign_directory(tmp_path):
    campaign_dir = write(tmp_path)
    before = {p.name: p.read_bytes() for p in campaign_dir.iterdir()}
    with pytest.raises(ContractError, match="refusing to overwrite"):
        write(tmp_path, created_utc="2026-09-26T12:00:00Z")
    assert {p.name: p.read_bytes() for p in campaign_dir.iterdir()} == before
    (tmp_path / "store" / "synthetic" / "synthetic-fixture-other").mkdir()
    with pytest.raises(ContractError, match="refusing to overwrite"):
        write(tmp_path, campaign_id="synthetic-fixture-other")


def test_invalid_inputs_fail_before_any_directory_is_created(tmp_path):
    bad = spec()
    bad["seeds"] = [11.0]
    for changes, match in (({"spec": bad}, "v1 freeze"),
                           ({"source": {"git_commit": "c" * 40, "dirty": True}}, "code_commit"),
                           ({"campaign_id": "../escape"}, "campaign_id"),
                           ({"created_utc": "yesterday"}, "created_utc"),
                           ({"subjects_root": str(tmp_path / "store" / "subjects")},
                            "separate from the campaign store"),
                           ({"arms": {k: v for k, v in arms().items() if k != "full"}}, "missing fields")):
        with pytest.raises(ContractError, match=match):
            write(tmp_path, **changes)
    assert not (tmp_path / "store" / "synthetic" / "synthetic-fixture-campaign").exists()


def test_task_definitions_must_match_the_v1_spec(tmp_path):
    other_oracle = definition("lf-a", "complete")
    other_oracle["oracle_sha256"] = sha("another-oracle")
    other_tolerance = definition("lf-a", "complete")
    other_tolerance["fidelity"]["tolerance"] = 0.01
    for tasks, match in (([definition("lf-a", "complete")], "differ from v1 spec tasks"),
                         ([other_oracle, definition("lf-d", "refuse")], "oracle_sha256 differs"),
                         ([other_tolerance, definition("lf-d", "refuse")], "fidelity.tolerance differs"),
                         ([definition("lf-a", "complete")] * 2, "duplicate definition"),
                         ([definition("lf-a", "refuse"), definition("lf-d", "refuse")], "expected differs"),
                         ([], "nonempty list")):
        with pytest.raises(ContractError, match=match):
            write(tmp_path, tasks=tasks)


# ---- the v1 value-equality loophole is closed by byte verification -------------------------

def _seed_float(registry):
    registry["runs"][0]["seed"] = 11.0
    return json.dumps(registry, indent=2) + "\n"


def _arm_flag_int(registry):
    registry["arms"]["full"]["instructions"] = 1
    registry["arms"]["baseline"]["enforcement"] = 0
    return json.dumps(registry, indent=2) + "\n"


def _sorted_keys(registry):
    return json.dumps(registry, indent=2, sort_keys=True) + "\n"


def _arms_reordered(registry):
    registry["arms"] = dict(reversed(list(registry["arms"].items())))
    return json.dumps(registry, indent=2) + "\n"


def _indent_one(registry):
    return json.dumps(registry, indent=1) + "\n"


def _no_newline(registry):
    return json.dumps(registry, indent=2)


@pytest.mark.parametrize("mutate", [_seed_float, _arm_flag_int, _sorted_keys, _arms_reordered, _indent_one,
                                    _no_newline])
def test_value_equal_registry_rewrites_fail_verify(tmp_path, mutate):
    campaign_dir = write(tmp_path)
    registry_path = campaign_dir / "registry.json"
    altered = mutate(json.loads(registry_path.read_bytes())).encode()
    assert altered != registry_path.read_bytes()
    experiment.validate_registry(json.loads(altered))  # the v1 check alone accepts this rewrite
    rewrite(registry_path, altered)
    edit_manifest(campaign_dir, lambda m: m.update(registry_file_sha256=hashlib.sha256(altered).hexdigest()))
    result = cm.verify(campaign_dir)
    assert result["ok"] is False
    assert result["errors"] == ["registry.json: bytes differ from the v1 freeze of spec.json (altered types, key "
                                "order or formatting; value equality is not accepted)"]


def test_registry_file_hash_is_checked(tmp_path):
    campaign_dir = write(tmp_path)
    edit_manifest(campaign_dir, lambda m: m.update(registry_file_sha256=sha("other")))
    assert "registry.json: sha256 differs" in error_text(cm.verify(campaign_dir))
    edit_manifest(campaign_dir, lambda m: m.update(registry_sha256=sha("other")))
    assert "registry_sha256: differs from the v1 freeze" in error_text(cm.verify(campaign_dir))


def test_spec_bytes_are_hashed_and_canonical(tmp_path):
    campaign_dir = write(tmp_path)
    spec_path = campaign_dir / "spec.json"
    rewrite(spec_path, (json.dumps(spec(), indent=1) + "\n").encode())
    text = error_text(cm.verify(campaign_dir))
    assert "spec.json: sha256 differs" in text and "not the exact v1 serialization" in text
    changed = spec()
    changed["model"] = "synthetic-other-model"
    rewrite(spec_path, cm.v1_bytes(changed))
    text = error_text(cm.verify(campaign_dir))
    assert "spec.json: sha256 differs" in text and "registry.json: bytes differ" in text
    assert "registry_sha256: differs" in text
    rewrite(spec_path, b'{"experiment_id": "a", "experiment_id": "b"}\n')
    assert "duplicate JSON field" in error_text(cm.verify(campaign_dir))


def test_manifest_budget_must_equal_v1_spec_budget_exactly(tmp_path):
    base = campaign_args(tmp_path)["budget"]
    with pytest.raises(ContractError, match="usd_per_run.*differs from v1 spec.budget"):
        write(tmp_path, budget={**base, "usd_per_run": 2})
    with pytest.raises(ContractError, match="usd_per_run.*differs from v1 spec.budget"):
        write(tmp_path, budget={**base, "usd_per_run": 1.0})  # value-equal but not the same JSON number
    campaign_dir = write(tmp_path)
    edit_manifest(campaign_dir, lambda m: m["budget"].update(seconds_per_run=60.0))
    assert "budget.seconds_per_run" in error_text(cm.verify(campaign_dir))


def test_missing_or_malformed_manifest_fails(tmp_path):
    campaign_dir = write(tmp_path)
    rewrite(campaign_dir / "campaign.json", b'{"schema_version": 1, "schema_version": 1}')
    assert "duplicate JSON field" in error_text(cm.verify(campaign_dir))
    (campaign_dir / "campaign.json").unlink()
    assert "campaign.json" in error_text(cm.verify(campaign_dir))
    edit = tmp_path / "store" / "synthetic" / "x"
    edit.mkdir()
    assert cm.verify(edit)["ok"] is False


def test_evaluator_task_definitions_must_match_manifest_digests(tmp_path):
    campaign_dir = write(tmp_path)
    registry = json.loads((campaign_dir / "registry.json").read_bytes())
    run = next(r for r in registry["runs"] if r["task_id"] == "lf-a")
    target = campaign_dir / "evaluator" / run["run_id"] / "task_definition.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(canonical.canonical_bytes(definition("lf-a", "complete")))
    assert cm.verify(campaign_dir)["ok"] is True
    tampered = definition("lf-a", "complete")
    tampered["refusal_conditions"] = []
    tampered["required_title"] = "synthetic altered title"
    rewrite(target, canonical.canonical_bytes(tampered))
    assert "definition_sha256" in error_text(cm.verify(campaign_dir))
    assert "differs from the manifest task entry" in error_text(cm.verify(campaign_dir))
    rewrite(target, canonical.canonical_bytes(definition("lf-d", "refuse")))
    assert "is for task 'lf-d'" in error_text(cm.verify(campaign_dir))


def test_verify_repeats_the_write_time_definition_checks(tmp_path):
    campaign_dir = write(tmp_path)
    definitions = [definition("lf-a", "complete"), definition("lf-d", "refuse")]
    materialize_definitions(campaign_dir, definitions)
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    for name, value in (("pair_id", "synthetic-pair-2"), ("family", "synthetic-other-family")):
        edit_manifest(campaign_dir, lambda m: m["tasks"][0].update({name: value}))
        assert f"{name} " in error_text(cm.verify(campaign_dir)), name
        edit_manifest(campaign_dir, lambda m: m["tasks"][0].update({name: definitions[0][name]}))
    assert cm.verify(campaign_dir)["ok"] is True
    for field, value, match in (("oracle_sha256", sha("another-oracle"), "oracle_sha256 differs from the v1 spec"),
                                ("prompt_sha256", sha("another-prompt"), "prompt_sha256 differs from the v1 spec"),
                                ("fidelity", {"metric": "relative_error", "quantity": "sigma_vis_obs_fb",
                                              "tolerance": 0.01}, "fidelity.tolerance differs")):
        altered = {**definition("lf-a", "complete"), field: value}
        materialize_definitions(campaign_dir, [altered, definitions[1]])
        edit_manifest(campaign_dir, lambda m: m["tasks"][0].update(definition_sha256=canonical.digest(altered)))
        assert match in error_text(cm.verify(campaign_dir)), field


def test_verify_rejects_provisional_definitions_in_an_empirical_campaign(tmp_path):
    campaign_dir = write(tmp_path, "empirical")
    reviewed = [definition("lf-a", "complete", False), definition("lf-d", "refuse", False)]
    materialize_definitions(campaign_dir, reviewed)
    assert cm.verify(campaign_dir)["ok"] is True
    provisional = [definition("lf-a", "complete"), definition("lf-d", "refuse")]
    materialize_definitions(campaign_dir, provisional)
    edit_manifest(campaign_dir, lambda m: [t.update(definition_sha256=canonical.digest(d))
                                           for t, d in zip(m["tasks"], provisional)])
    assert "provisional (unreviewed) definition cannot enter an empirical campaign" in error_text(cm.verify(campaign_dir))


def test_verify_rejects_symlinked_or_irregular_files(tmp_path):
    campaign_dir = write(tmp_path)
    registry = materialize_definitions(campaign_dir, [definition("lf-a", "complete"), definition("lf-d", "refuse")])
    outside = tmp_path / "outside"
    outside.mkdir()
    target = campaign_dir / "evaluator" / registry["runs"][0]["run_id"] / "task_definition.json"
    (outside / "task_definition.json").write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(outside / "task_definition.json")
    assert "symlink evaluator/" in error_text(cm.verify(campaign_dir))
    target.unlink()
    shutil.rmtree(campaign_dir / "evaluator")
    assert cm.verify(campaign_dir)["ok"] is True
    for name in ("spec.json", "registry.json", "campaign.json"):
        path = campaign_dir / name
        (outside / name).write_bytes(path.read_bytes())
        path.chmod(0o644)
        path.unlink()
        path.symlink_to(outside / name)  # identical bytes, but not a regular file in the campaign
        assert f"symlink {name} is not accepted" in error_text(cm.verify(campaign_dir)), name
        path.unlink()
        path.mkdir()
        assert name in error_text(cm.verify(campaign_dir)), name
        path.rmdir()
        path.write_bytes((outside / name).read_bytes())
    assert cm.verify(campaign_dir)["ok"] is True


@pytest.mark.parametrize("name", ["spec.json", "campaign.json"])
@pytest.mark.parametrize("depth", [300, 900, 100000])
def test_deeply_nested_json_fails_verify_without_raising(tmp_path, name, depth):
    campaign_dir = write(tmp_path)
    rewrite(campaign_dir / name, ('{"experiment_id": ' + "[" * depth + "]" * depth + "}\n").encode())
    assert name in error_text(cm.verify(campaign_dir))
    assert cm.verify_run_provenance(campaign_dir, [])["ok"] is False


def test_verify_checks_subjects_root_separation(tmp_path):
    campaign_dir = write(tmp_path)
    for inside in (tmp_path / "store", tmp_path / "store" / "subjects", tmp_path):
        edit_manifest(campaign_dir, lambda m: m["storage"].update(subjects_root=str(inside)))
        assert "storage.subjects_root: overlaps the campaign store" in error_text(cm.verify(campaign_dir))


# ---- the v1 spec is bound to the host it evaluates and to the campaign kind ---------------------

def test_fake_host_spec_carries_the_synthetic_label(tmp_path):
    for name in ("model", "runtime"):
        unlabeled = {**spec(), name: "fixture-value-missing-the-label"}  # SYNTHETIC fixture, deliberately unlabeled
        with pytest.raises(ContractError, match=f"spec.{name}: a fake-host campaign's v1 spec carries the synthetic"):
            write(tmp_path, spec=unlabeled)


def test_real_host_spec_declares_the_host_runtime_and_model(tmp_path):
    real = host("claude_cli")
    assert cm.runtime_label(real) == "claude_cli 0.0.0-synthetic"
    with pytest.raises(ContractError, match="spec.runtime: 'synthetic-fake-adapter' does not identify the host"):
        write(tmp_path, host=real)
    with pytest.raises(ContractError, match="spec.model: 'synthetic-other-model' differs from host.model"):
        write(tmp_path, host=real, spec={**spec(real), "model": "synthetic-other-model"})
    with pytest.raises(ContractError, match="does not identify the host"):
        write(tmp_path, host=real, spec={**spec(real), "runtime": "synthetic codex_cli 0.0.0-synthetic"})
    unpinned = {**real, "model": None}
    with pytest.raises(ContractError, match="lists a null model in unknown_fields"):
        write(tmp_path, host=unpinned, spec=spec(real))
    unknown = {**unpinned, "unknown_fields": ["model", "reasoning", "sampling"]}
    with pytest.raises(ContractError, match="host.model: an empirical campaign must pin the model"):
        write(tmp_path, "empirical", host=unknown, spec=spec(real, "empirical"))
    with pytest.raises(ContractError, match="spec.model: 'synthetic-fixture-model' .*synthetic label"):
        write(tmp_path, host=unknown, spec={**spec(real), "model": "synthetic-fixture-model"})   # prefix, no space
    campaign_dir = write(tmp_path, host=unknown, spec=spec(real))  # synthetic engineering: model may be unknown
    assert cm.verify(campaign_dir)["ok"] is True


def test_spec_identity_is_disjoint_between_the_two_campaign_kinds():
    real = host("claude_cli")
    assert cm.spec_identity("empirical", real) == ("synthetic-fixture-model", "claude_cli 0.0.0-synthetic")
    assert cm.spec_identity("synthetic", real) == ("synthetic synthetic-fixture-model",
                                                   "synthetic claude_cli 0.0.0-synthetic")
    assert cm.spec_identity("synthetic", {**real, "model": None}) == (None, "synthetic claude_cli 0.0.0-synthetic")
    for kind in ("empirical", "synthetic"):
        model, runtime = cm.spec_identity(kind, real)
        assert (spec(real, kind)["model"], spec(real, kind)["runtime"]) == (model, runtime)
    for adapter in ("claude_cli", "codex_cli"):   # an empirical runtime never starts with the label
        assert not cm.spec_identity("empirical", host(adapter))[1].startswith(cm.SYNTHETIC_LABEL)
    with pytest.raises(ContractError, match="fake host"):
        cm.spec_identity("synthetic", host())


def test_real_host_synthetic_spec_must_carry_the_synthetic_label(tmp_path):
    """R1.1 root cause: a synthetic campaign on a real host used to declare the host exactly as an
    empirical campaign does, so both kinds froze the same v1 spec and the same run ids. Now the
    campaign kind is part of the v1 spec for every host, and the run ids of the two kinds are disjoint."""
    real = host("claude_cli")
    with pytest.raises(ContractError, match="spec.runtime: 'claude_cli 0.0.0-synthetic' does not identify the host "
                                            "and the campaign kind; 'synthetic claude_cli 0.0.0-synthetic' required"):
        write(tmp_path, host=real, spec=spec(real, "empirical"))
    with pytest.raises(ContractError, match="spec.runtime: 'synthetic claude_cli 0.0.0-synthetic' does not identify"):
        write(tmp_path, "empirical", spec=spec(real, "synthetic"))
    with pytest.raises(ContractError, match="spec.model: 'synthetic-fixture-model' differs from host.model"):
        write(tmp_path, host=real, spec={**spec(real), "model": real["model"]})
    synthetic = write(tmp_path, host=real, spec=spec(real))
    empirical = write(tmp_path, "empirical", campaign_id="synthetic-fixture-campaign")   # same host, same tasks
    ids = {name: {r["run_id"] for r in json.loads((d / "registry.json").read_bytes())["runs"]}
           for name, d in (("synthetic", synthetic), ("empirical", empirical))}
    assert len(ids["synthetic"]) == len(ids["empirical"]) == 8 and not ids["synthetic"] & ids["empirical"]


def test_host_binding_is_rechecked_by_verify(tmp_path):
    campaign_dir = write(tmp_path, "empirical")
    edit_manifest(campaign_dir, lambda m: m["host"].update(model="synthetic-substituted-model"))
    assert "spec.model: 'synthetic-fixture-model' differs from host.model" in error_text(cm.verify(campaign_dir))
    edit_manifest(campaign_dir, lambda m: m["host"].update(model="synthetic-fixture-model", version="9.9.9-synthetic"))
    assert "spec.runtime: 'claude_cli 0.0.0-synthetic' does not identify the host" in error_text(cm.verify(campaign_dir))


# ---- namespace and authorization --------------------------------------------------------------

def test_directory_must_match_kind_namespace_and_campaign_id(tmp_path):
    campaign_dir = write(tmp_path)
    moved = tmp_path / "store" / "empirical" / "synthetic-fixture-campaign"
    moved.parent.mkdir(parents=True)
    shutil.copytree(campaign_dir, moved)
    text = error_text(cm.verify(moved))
    assert "namespace: a synthetic campaign must live under <store>/synthetic/" in text
    renamed = tmp_path / "store" / "synthetic" / "synthetic-fixture-renamed"
    shutil.copytree(campaign_dir, renamed)
    assert "is not campaign_id" in error_text(cm.verify(renamed))


def test_synthetic_campaign_relabeled_as_empirical_in_place_fails(tmp_path):
    campaign_dir = write(tmp_path)
    moved = tmp_path / "store" / "empirical" / "synthetic-fixture-campaign"
    moved.parent.mkdir(parents=True)
    shutil.copytree(campaign_dir, moved)
    edit_manifest(moved, lambda m: (m.update(kind="empirical"), m["storage"].update(store_kind="empirical")))
    assert "empirical requires an approved_campaign authorization" in error_text(cm.verify(moved))
    edit_manifest(moved, lambda m: m.update(authorization=dict(FIXTURE_APPROVAL)))
    assert "cannot use the fake adapter" in error_text(cm.verify(moved))
    # Every manifest-level empirical requirement met, the spec is still the synthetic one: fails.
    for model in ("synthetic-fixture-model", "synthetic-fake-subject"):
        edit_manifest(moved, lambda m: m.update(host={**host("claude_cli"), "model": model},
                                                source={"git_commit": "b" * 40, "dirty": False}))
        assert contracts.validate_campaign_manifest(canonical.strict_load(moved / "campaign.json")) is None
        assert "spec.runtime: 'synthetic-fake-adapter' does not identify the host" in error_text(cm.verify(moved))


@pytest.mark.parametrize("adapter", ["fake", "claude_cli"])
def test_a_sealed_synthetic_cohort_cannot_be_relabeled_empirical(tmp_path, adapter):
    """R1.1 regression, CONTRACT_16 / slice §12.6, for the fake host and for a real host (a SYNTHETIC mock
    labeled claude_cli; nothing is launched). A synthetic cohort with sealed, journaled runs and honest
    judge reports is relabeled empirical (1) in place, meeting every manifest-level rule, and (2) with its
    spec and registry re-frozen under the empirical label and every run directory moved to the new run
    ids. Before the fix the real-host in-place relabel verified (same spec, same run ids) and the
    relabeled judge reports passed verify_run_provenance; now the kind is bound into the v1 spec and
    every run record sealed under the journal is checked against the manifest, so both fail."""
    real = host("claude_cli")
    synthetic = write(tmp_path, host=host(adapter), spec=spec(real if adapter != "fake" else None))
    seal_runs(synthetic)
    reports = judge_reports(synthetic)
    assert cm.verify(synthetic) == {"ok": True, "errors": []}                              # the honest control
    assert cm.verify_run_provenance(synthetic, reports) == {"ok": True, "errors": []}
    labels = {"campaign_kind": "empirical", "synthetic": False, "adapter": "claude_cli"}

    # (1) in place: every manifest-level empirical requirement met, the spec and the sealed runs unchanged
    moved = relabel_in_place(synthetic, real)
    text = error_text(cm.verify(moved))
    assert "spec.runtime: " in text and "does not identify the host" in text
    for rid in json.loads((moved / "registry.json").read_bytes())["runs"]:
        label = f"runs/{rid['run_id']}/sealed/run.json"
        assert f"{label}.campaign_kind: 'synthetic' differs from this campaign's 'empirical'" in text
        assert f"{label}.synthetic: True differs from this campaign's False" in text
        assert (f"{label}.adapter: 'fake' differs" in text) is (adapter == "fake")
    result = cm.verify_run_provenance(moved, judge_reports(synthetic, **labels))
    assert result["ok"] is False and all(e.startswith("campaign: ") for e in result["errors"])

    # (2) re-frozen under the empirical label: the manifest agrees with its spec, the sealed records do not
    moved_ids = refreeze(moved, spec(real, "empirical"))
    assert all(old != new for old, new in moved_ids.items())
    text = error_text(cm.verify(moved))
    assert "spec." not in text and "registry" not in text                    # spec, registry, manifest agree
    for old, new in moved_ids.items():
        label = f"runs/{new}/sealed/run.json"
        assert f"{label}.run_id: '{old}' differs from this campaign's '{new}'" in text
        assert f"{label}.campaign_kind: 'synthetic' differs" in text and f"{label}.synthetic: True differs" in text
    rekeyed = [{**r, **labels, "run_id": moved_ids[r["run_id"]],
                "v1_outcome": {**r["v1_outcome"], "run_id": moved_ids[r["run_id"]]}} for r in reports]
    result = cm.verify_run_provenance(moved, rekeyed)
    assert result["ok"] is False and all(e.startswith("campaign: ") for e in result["errors"])
    assert cm.verify(synthetic)["ok"] is True                               # the original cohort is untouched


def test_sealed_run_records_are_read_only_when_bound_to_the_journal(tmp_path):
    """verify reads a sealed run.json when its bytes are the ones the coordinator journaled: the journal
    holds one ``sealed`` record whose evidence_sha256 is the digest of evidence_manifest.json, and that
    manifest lists run.json with these bytes. Such a record must validate and agree with the registry
    and the manifest. A seal left unread is only one runner.seal_problem refuses (a custody incident),
    asserted here for each; a seal verify cannot read as the runner does (a torn or symlinked journal)
    is an error, never skipped (review of R1.1: a symlinked journal used to unbind a relabeled run)."""
    campaign_dir = write(tmp_path)
    registry = json.loads((campaign_dir / "registry.json").read_bytes())
    first, second, third = (r["run_id"] for r in registry["runs"][:3])
    seal_runs(campaign_dir, campaign_id="synthetic-other-campaign")   # bound to the journal, wrong campaign
    text = error_text(cm.verify(campaign_dir))
    assert f"runs/{first}/sealed/run.json.campaign_id: 'synthetic-other-campaign' differs from this campaign's" in text
    assert len(cm.verify(campaign_dir)["errors"]) == len(registry["runs"])
    shutil.rmtree(campaign_dir / "runs")
    seal_runs(campaign_dir, seed=12)
    text = error_text(cm.verify(campaign_dir))
    assert f"runs/{first}/sealed/run.json.seed: 12 differs from this campaign's 11" in text
    shutil.rmtree(campaign_dir / "runs")
    seal_runs(campaign_dir, synthetic=False)                          # bound, but not a valid run record
    assert f"runs/{first}/sealed/run.json.synthetic: must be true iff" in error_text(cm.verify(campaign_dir))
    shutil.rmtree(campaign_dir / "runs")
    seal_runs(campaign_dir)
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    # Not bound, not read: a run.json changed after sealing (manifest stale), a consistent tree+manifest
    # rewrite the journal does not match, and a journal holding two seals.
    for rid in (first, second):
        path = campaign_dir / "runs" / rid / "sealed" / "run.json"
        rewrite(path, path.read_bytes().replace(b'"campaign_kind": "synthetic"', b'"campaign_kind": "empirical"'))
    entries = canonical.tree_manifest(campaign_dir / "runs" / second / "sealed")
    rewrite(campaign_dir / "runs" / second / "evidence_manifest.json", (json.dumps(entries, indent=1) + "\n").encode())
    journal = campaign_dir / "runs" / third / "journal.jsonl"
    canonical.append_jsonl(journal, canonical.read_jsonl(journal)[0][-1])
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    for rid in (first, second, third):                               # each is the runner's custody incident
        assert runner.seal_problem(campaign_dir / "runs" / rid)[1] is not None, rid
    # Every record bound and relabeled (3 disagreements each). A missing evidence manifest leaves one run
    # unread (seal_problem refuses it); a torn journal and a symlinked journal are errors naming the run.
    shutil.rmtree(campaign_dir / "runs")
    seal_runs(campaign_dir, campaign_kind="empirical", synthetic=False, adapter="claude_cli")
    assert len(cm.verify(campaign_dir)["errors"]) == 3 * len(registry["runs"])
    with open(campaign_dir / "runs" / first / "journal.jsonl", "ab") as handle:
        handle.write(b'{"state": "sea')                              # SYNTHETIC torn write
    journal = campaign_dir / "runs" / second / "journal.jsonl"
    (tmp_path / "outside-journal.jsonl").write_bytes(journal.read_bytes())
    journal.unlink()
    journal.symlink_to(tmp_path / "outside-journal.jsonl")
    (campaign_dir / "runs" / third / "evidence_manifest.json").unlink()
    assert runner.seal_problem(campaign_dir / "runs" / second) == (None, (   # the runner no longer follows it
        f"runs/{second}/journal.jsonl is a symlink or not a regular file (the coordinator never writes one "
        "there; a seal is never read through it)"))
    assert runner.seal_problem(campaign_dir / "runs" / third)[1] is not None
    errors = cm.verify(campaign_dir)["errors"]
    assert len(errors) == 3 * (len(registry["runs"]) - 3) + 2
    [torn] = [e for e in errors if first in e]
    assert torn.startswith(f"runs/{first}/journal.jsonl: malformed journal (line 3: ")
    assert [e for e in errors if second in e] == [f"runs/{second}/journal.jsonl: a symlink on a seal path; the "
                                                  "coordinator never writes one, and neither verify nor the "
                                                  "runner reads a seal through it, so the seal cannot be checked"]
    assert not [e for e in errors if third in e]


def unbind(run_dir, variant):
    """SYNTHETIC store writer: make one sealed run's seal unreadable to verify's lstat-only reading while
    keeping its bytes (every variant but the torn journal leaves the sealed content as it was)."""
    run_dir.chmod(0o755)
    renamed = {"journal-symlink": ("journal.jsonl",), "sealed-symlink": ("sealed",),
               "manifest-symlink": ("evidence_manifest.json",)}
    if variant in renamed:
        path = run_dir.joinpath(*renamed[variant])
        path.rename(path.with_name(path.name + ".real"))
        path.symlink_to(path.name + ".real")
    elif variant == "rundir-symlink":
        hidden = run_dir.with_name(".hidden-" + run_dir.name)
        run_dir.rename(hidden)
        run_dir.symlink_to(hidden.name)
    elif variant == "record-symlink":
        sealed = run_dir / "sealed"
        sealed.chmod(0o755)
        (sealed / "run.json").rename(sealed / "run.real")
        (sealed / "run.json").symlink_to("run.real")
    elif variant == "manifest-float":   # value-equal to the sealed tree (an older runner.evidence_digest accepted it)
        path = run_dir / "evidence_manifest.json"
        entries = [{**e, "bytes": float(e["bytes"])} for e in canonical.strict_load(path)]
        rewrite(path, (json.dumps(entries, indent=1) + "\n").encode())
    elif variant == "journal-directory":
        journal = run_dir / "journal.jsonl"
        journal.rename(run_dir / "journal.real")
        journal.mkdir()
    elif variant == "torn-journal":
        with open(run_dir / "journal.jsonl", "ab") as handle:
            handle.write(b'{"state": "exi')                              # SYNTHETIC torn write
    else:
        raise AssertionError(variant)


# variant -> (verify's error for runs/<id>, does runner.seal_problem trust the seal: True, False or "raises").
# Since the runner rejects symlinked and irregular seal paths with lstat and compares evidence_manifest.json by
# canonical bytes (hand-off of this review to runner.py), it trusts none of them either; before, it followed
# the four symlinks and accepted the float rewrite by value (True), and raised on a directory journal.
UNBOUND = {"journal-symlink": ("/journal.jsonl: a symlink on a seal path", False),
           "rundir-symlink": (": a symlink on a seal path", False),
           "sealed-symlink": ("/sealed: a symlink on a seal path", False),
           "manifest-symlink": ("/evidence_manifest.json: a symlink on a seal path", False),
           "manifest-float": ("/evidence_manifest.json: holds a float or boolean", False),
           "record-symlink": ("/sealed/run.json: a symlink on a seal path", False),
           "journal-directory": ("/journal.jsonl: not a regular file", False),
           "torn-journal": ("/journal.jsonl: malformed journal", "raises")}


@pytest.mark.parametrize("variant", [*UNBOUND, "runs-symlink"])
def test_a_seal_verify_cannot_read_as_the_runner_does_is_an_error(tmp_path, variant):
    """Review of R1.1 (probe_symlink_verify): a real-host synthetic cohort (SYNTHETIC mock labeled claude_cli,
    nothing launched), sealed, relabeled empirical and re-frozen with its run directories moved, then every
    seal made unreadable to verify's lstat-only reading. Before the fix verify skipped such a seal and
    returned ok, although runner.seal_problem then followed symlinks (and compared evidence_manifest.json by
    value) and trusted it: the relabel passed verify and verify_run_provenance. Now each is an error naming
    the run, and seal_problem refuses every one of them as well (UNBOUND)."""
    real = host("claude_cli")
    synthetic = write(tmp_path, host=real, spec=spec(real))
    seal_runs(synthetic)
    reports = judge_reports(synthetic)
    moved = relabel_in_place(synthetic, real)
    ids = refreeze(moved, spec(real, "empirical"))
    if variant == "runs-symlink":
        (moved / "runs").rename(moved / ".runs-real")
        (moved / "runs").symlink_to(".runs-real")
        expected, trusted = ["runs: a symlink on a seal path; the coordinator never writes one, and neither "
                             "verify nor the runner reads a seal through it, so the seal cannot be checked"], False
    else:
        for new in ids.values():
            unbind(moved / "runs" / new, variant)
        suffix, trusted = UNBOUND[variant]
        expected = [f"runs/{new}{suffix}" for new in ids.values()]
    for new in ids.values():
        run_dir = moved / "runs" / new
        if trusted == "raises":
            with pytest.raises((ContractError, OSError)):
                runner.seal_problem(run_dir)
        else:
            assert (runner.seal_problem(run_dir)[1] is None) is trusted, new
    errors = cm.verify(moved)["errors"]
    assert len(errors) == len(expected)
    assert all(error.startswith(prefix) for error, prefix in zip(errors, expected)), errors
    labels = {"campaign_kind": "empirical", "synthetic": False, "adapter": "claude_cli"}
    rekeyed = [{**r, **labels, "run_id": ids[r["run_id"]],
                "v1_outcome": {**r["v1_outcome"], "run_id": ids[r["run_id"]]}} for r in reports]
    result = cm.verify_run_provenance(moved, rekeyed)
    assert result["ok"] is False and result["errors"] == [f"campaign: {e}" for e in errors]


@pytest.mark.parametrize("variant", [None, "journal-symlink", "rundir-symlink"])
def test_write_outcomes_refuses_a_refrozen_relabel_with_unbound_seals(tmp_path, variant):
    """Review of R1.1 (probe_symlink_outcomes), end to end through runner.write_outcomes: a SYNTHETIC real-host
    cohort, sealed and judged with reports bound to its seals (the control writes outcomes), is relabeled
    empirical, re-frozen, its run directories moved and its reports relabeled. Before the fix, one symlink per
    run (journal or run directory) made write_outcomes write 8 empirical rows while every sealed run.json still
    said synthetic under the old run id. Now verify refuses first, with or without the symlink, and the copied
    outcomes.json is left as it was; runner.seal_problem refuses the symlinked seals as well."""
    real = host("claude_cli")
    synthetic = write(tmp_path, host=real, spec=spec(real))
    digests = seal_runs(synthetic)
    # the control's reports are a labeled stub scorer's, bound to the seals (evidence and sealed executor): an
    # audit.py report would be re-derived from the sealed evidence (R1.0), which these synthetic seals lack
    for report in judge_reports(synthetic):
        digest = digests[report["run_id"]]
        report = {**report, "evidence_sha256": digest, "scorer_id": STUB_SCORER,
                  "v1_outcome": {**report["v1_outcome"], "evidence_sha256": digest, "scorer_id": STUB_SCORER,
                                 "executor_id": SEALED_EXECUTOR}}
        canonical.write_once(synthetic / "runs" / report["run_id"] / "judge_report.json",
                             canonical.canonical_bytes(report))
    (synthetic / runner.COORDINATOR).mkdir(mode=0o700)
    control = runner.write_outcomes(synthetic, scorer_ids=[STUB_SCORER])
    assert len(canonical.strict_load(control)["outcomes"]) == len(digests)
    moved = relabel_in_place(synthetic, real)
    ids = refreeze(moved, spec(real, "empirical"))
    old_of = {new: old for old, new in ids.items()}
    labels = {"campaign_kind": "empirical", "synthetic": False, "adapter": "claude_cli"}
    for new in ids.values():
        path = moved / "runs" / new / "judge_report.json"
        report = canonical.strict_load(path)
        rewrite(path, canonical.canonical_bytes({**report, **labels, "run_id": new,
                                                 "v1_outcome": {**report["v1_outcome"], "run_id": new}}))
        if variant is not None:
            unbind(moved / "runs" / new, variant)
            assert "is a symlink" in runner.seal_problem(moved / "runs" / new)[1]   # the runner refuses it too
    before = (moved / "outcomes.json").read_bytes()
    with pytest.raises(ContractError, match="campaign verification failed") as refused:
        runner.write_outcomes(moved)
    message = str(refused.value)
    for new in ids.values():
        assert (f"runs/{new}/sealed/run.json.campaign_kind: 'synthetic' differs" in message) is (variant is None)
        assert ("a symlink on a seal path" in message) is (variant is not None)
    assert (moved / "outcomes.json").read_bytes() == before


def test_write_outcomes_checks_the_sealed_record_it_trusts(tmp_path, monkeypatch):
    """Hand-off of the R1.1 review to runner._bind_to_seals: the sealed run.json it reads once the seal
    reconciles is itself checked against the registry and the manifest (run_id, campaign, kind, synthetic,
    adapter, task, seed, arm), so the record trusted is the record checked, not only by verify. SYNTHETIC: a
    reconciled seal naming another seed, and verify stubbed to pass (a verify that missed it)."""
    campaign_dir = write(tmp_path)
    digests = seal_runs(campaign_dir, seed=12)
    for report in judge_reports(campaign_dir):
        digest = digests[report["run_id"]]
        report = {**report, "evidence_sha256": digest, "scorer_id": STUB_SCORER,
                  "v1_outcome": {**report["v1_outcome"], "evidence_sha256": digest, "scorer_id": STUB_SCORER,
                                 "executor_id": SEALED_EXECUTOR}}
        canonical.write_once(campaign_dir / "runs" / report["run_id"] / "judge_report.json",
                             canonical.canonical_bytes(report))
    (campaign_dir / runner.COORDINATOR).mkdir(mode=0o700)
    with pytest.raises(ContractError, match="campaign verification failed"):
        runner.write_outcomes(campaign_dir, scorer_ids=[STUB_SCORER])
    monkeypatch.setattr(cm, "verify", lambda *args, **kwargs: {"ok": True, "errors": []})
    first = json.loads((campaign_dir / "registry.json").read_bytes())["runs"][0]["run_id"]
    with pytest.raises(ContractError, match=f"{first}: sealed run.json.seed 12 differs from this campaign's 11"):
        runner.write_outcomes(campaign_dir, scorer_ids=[STUB_SCORER])
    assert not (campaign_dir / "outcomes.json").exists()


def test_verify_can_limit_the_seal_check_to_named_runs(tmp_path):
    """verify(sealed_runs=[...]) checks the seals of those registry runs only (a caller judging one run,
    such as audit.build_report, need not re-read every seal: minor review finding on quadratic audit cost);
    every other check is unchanged, and anything but a nonempty list of registry run ids is an error with
    every seal checked."""
    campaign_dir = write(tmp_path)
    runs = [r["run_id"] for r in json.loads((campaign_dir / "registry.json").read_bytes())["runs"]]
    seal_runs(campaign_dir, campaign_kind="empirical", synthetic=False, adapter="claude_cli")   # 3 errors per run
    assert len(cm.verify(campaign_dir)["errors"]) == 3 * len(runs)
    for named in ([runs[1]], (runs[1], runs[1])):
        errors = cm.verify(campaign_dir, sealed_runs=named)["errors"]
        assert len(errors) == 3 and all(e.startswith(f"runs/{runs[1]}/sealed/run.json.") for e in errors)
    assert len(cm.verify(campaign_dir, sealed_runs=runs[:2])["errors"]) == 6
    for bad in ([], runs[0], [sha("unplanned-run")], [runs[0], 1], None):
        errors = cm.verify(campaign_dir, sealed_runs=bad)["errors"]
        assert len(errors) == 3 * len(runs) + (bad is not None)
        assert ("sealed_runs: a nonempty list" in "\n".join(errors)) is (bad is not None)
    shutil.rmtree(campaign_dir / "runs")
    seal_runs(campaign_dir)
    edit_manifest(campaign_dir, lambda m: m["budget"].update(usd_per_run=2))
    assert "budget.usd_per_run" in error_text(cm.verify(campaign_dir, sealed_runs=[runs[0]]))


def test_approval_reference_resolves_to_the_frozen_approval_record(tmp_path):
    """An authorization's reference_sha256, when given, must name the approval record frozen with the
    campaign (<campaign>/approval_record, write-once): an arbitrary 64-hex string no longer passes. What
    an approval record contains and who issues it is an open human decision (PKT-D07); only the hash
    binding is enforced."""
    campaign_dir = write(tmp_path, "empirical")
    record = campaign_dir / cm.APPROVAL
    assert record.read_bytes() == APPROVAL_RECORD and record.stat().st_mode & 0o222 == 0
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    for approval_record, match in ((None, "approval_record: .*required"),
                                   (b"SYNTHETIC other bytes", "approval_record: .*required")):
        with pytest.raises(ContractError, match=match):
            write(tmp_path, "empirical", campaign_id="synthetic-fixture-other", approval_record=approval_record)
    with pytest.raises(ContractError, match="approval_record: given, but authorization.reference_sha256 is null"):
        write(tmp_path, approval_record=APPROVAL_RECORD)
    assert not (tmp_path / "store" / "empirical" / "synthetic-fixture-other").exists()
    rewrite(record, b"SYNTHETIC substituted approval\n")
    assert "approval_record: sha256 differs from authorization.reference_sha256" in error_text(cm.verify(campaign_dir))
    record.unlink()
    assert "approval_record: authorization.reference_sha256 must resolve" in error_text(cm.verify(campaign_dir))
    outside = tmp_path / "outside-approval"
    outside.write_bytes(APPROVAL_RECORD)
    record.symlink_to(outside)
    assert "approval_record: authorization.reference_sha256 must resolve" in error_text(cm.verify(campaign_dir))
    record.unlink()
    record.write_bytes(APPROVAL_RECORD)
    assert cm.verify(campaign_dir)["ok"] is True
    engineering = {**SYNTHETIC_AUTH, "reference_sha256": FIXTURE_APPROVAL["reference_sha256"]}
    synthetic = write(tmp_path, authorization=engineering, approval_record=APPROVAL_RECORD)
    assert cm.verify(synthetic)["ok"] is True
    plain = write(tmp_path, campaign_id="synthetic-fixture-plain")
    (plain / cm.APPROVAL).write_bytes(APPROVAL_RECORD)
    assert "approval_record: present, but authorization.reference_sha256 is null" in error_text(cm.verify(plain))


def family_tree(campaign_dir, definitions):
    """A runner-shaped coordinator/family (index.json and tasks/<id>/task_definition.json), SYNTHETIC."""
    family = campaign_dir / "coordinator" / "family"
    tasks = []
    for d in definitions:
        path = f"tasks/{d['task_id']}/task_definition.json"
        target = family / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(0o644)
        target.write_bytes(canonical.canonical_bytes(d))
        tasks.append({"task_id": d["task_id"], "definition_path": path, "definition_sha256": canonical.digest(d)})
    index = family / "index.json"
    if index.exists():
        index.chmod(0o644)
    index.write_text(json.dumps({"schema_version": 1, "tasks": tasks}, indent=1) + "\n")
    return index


def test_verify_checks_the_coordinator_family_definitions(tmp_path):
    """The write-time definition checks (and the empirical no-provisional rule) are repeated on the
    coordinator's frozen family definitions, not only on evaluator copies that happen to exist, so an
    empirical campaign is refused before any run copies a provisional definition."""
    campaign_dir = write(tmp_path)
    index = family_tree(campaign_dir, [definition("lf-a", "complete"), definition("lf-d", "refuse")])
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    altered = {**definition("lf-a", "complete"), "pair_id": "synthetic-pair-2"}
    family_tree(campaign_dir, [altered, definition("lf-d", "refuse")])
    assert ("coordinator/family/tasks/lf-a/task_definition.json: pair_id 'synthetic-pair-2' differs from the "
            "manifest task entry") in error_text(cm.verify(campaign_dir))
    for tasks, match in (([{"task_id": "lf-a", "definition_path": "../../campaign.json"}], "definition_path"),
                         ([{"task_id": "lf-z", "definition_path": "tasks/lf-a/task_definition.json"}], "lf-z"),
                         ("not a list", "coordinator/family/index.json")):
        rewrite(index, json.dumps({"schema_version": 1, "tasks": tasks}).encode())
        assert match in error_text(cm.verify(campaign_dir)), tasks
    rewrite(index, b'{"tasks": [], "tasks": []}')
    assert "coordinator/family/index.json: duplicate JSON field" in error_text(cm.verify(campaign_dir))
    empirical = write(tmp_path, "empirical")
    family_tree(empirical, [definition("lf-a", "complete", False), definition("lf-d", "refuse", False)])
    assert cm.verify(empirical)["ok"] is True
    provisional = [definition("lf-a", "complete"), definition("lf-d", "refuse")]
    family_tree(empirical, provisional)
    edit_manifest(empirical, lambda m: [t.update(definition_sha256=canonical.digest(d))
                                        for t, d in zip(m["tasks"], provisional)])
    text = error_text(cm.verify(empirical))
    assert ("coordinator/family/tasks/lf-a/task_definition.json: a provisional (unreviewed) definition cannot "
            "enter an empirical campaign") in text


def test_verify_rederives_the_bank_rules_of_a_frozen_task_bank(tmp_path):
    """WP12 plan step 1: a runner-built campaign freezes the whole task bank (tasks.registry.build_bank); verify
    re-derives contracts.validate_task_bank over every definition its index lists, so a contrast whose declared
    fault inputs are not the twins' actual subject-visible differences fails verification. SYNTHETIC."""
    from governance.tasks import registry
    built = registry.build_bank(tmp_path / "bank")
    definitions = [canonical.strict_load(tmp_path / "bank" / t["definition_path"]) for t in built["tasks"]]
    campaign = spec()
    campaign["tasks"] = built["v1_tasks"]
    campaign_dir = write(tmp_path, spec=campaign, tasks=definitions)
    shutil.copytree(tmp_path / "bank", campaign_dir / "coordinator" / "family")
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    index = campaign_dir / "coordinator" / "family" / "index.json"
    tampered = json.loads(index.read_bytes())
    tampered["contrasts"][0]["fault_inputs"] = ["luminosity.json"]
    rewrite(index, json.dumps(tampered, indent=1).encode())
    assert error_text(cm.verify(campaign_dir)) == (
        "coordinator/family/index.json.contrasts[0]: the subject-visible differences ['workspace.json'] are not "
        "the declared fault_inputs ['luminosity.json']")
    tampered["contrasts"] = [c for c in built["contrasts"] if c["id"] != "lf-p2"]
    rewrite(index, json.dumps(tampered, indent=1).encode())
    assert "pair lf-p2 needs its primary contrast" in error_text(cm.verify(campaign_dir))
    # an index whose definitions cannot all be read is reported once, never judged as a partial bank
    tampered = copy.deepcopy(built)
    tampered["tasks"][2]["definition_path"] = "../../campaign.json"
    rewrite(index, json.dumps(tampered, indent=1).encode())
    text = error_text(cm.verify(campaign_dir))
    assert "definition_path" in text and "pair" not in text and "contrasts" not in text


def test_a_task_bank_index_without_its_rules_or_changed_after_freezing_fails_verification(tmp_path):
    """Review of 2026-09-27: a task-bank index (it names a bank_version) whose contrasts or visible_oracle_values were
    removed is an error, never a bank without rules; and a runner-built campaign's coordinator/environment.json binds
    the frozen index (family_index_sha256) and the host (environment_manifest_sha256), so any change to the index
    fails verify, as it fails the runner's load. SYNTHETIC."""
    from governance.tasks import registry
    built = registry.build_bank(tmp_path / "bank")
    definitions = [canonical.strict_load(tmp_path / "bank" / t["definition_path"]) for t in built["tasks"]]
    campaign = spec()
    campaign["tasks"] = built["v1_tasks"]
    environment = {"schema_version": 1, "family_index_sha256": canonical.sha256_file(tmp_path / "bank" / "index.json"),
                   "synthetic": "SYNTHETIC environment manifest"}
    campaign_dir = write(tmp_path, spec=campaign, tasks=definitions,
                         host={**host(), "environment_manifest_sha256": canonical.digest(environment)})
    shutil.copytree(tmp_path / "bank", campaign_dir / "coordinator" / "family")
    index = campaign_dir / "coordinator" / "family" / "index.json"
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}           # no environment.json: not bound
    (campaign_dir / "coordinator" / "environment.json").write_text(json.dumps(environment))
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    for key in ("contrasts", "visible_oracle_values"):
        tampered = {k: v for k, v in built.items() if k != key}
        rewrite(index, json.dumps(tampered, indent=1).encode())
        text = error_text(cm.verify(campaign_dir))
        assert f"a task-bank index (bank_version 'wp12-dev-1') without ['{key}']" in text, text
        assert "family_index_sha256 is not the sha256" in text
    rewrite(index, json.dumps(built, indent=1).encode())        # the same content, other bytes: still a change
    assert "family_index_sha256 is not the sha256" in error_text(cm.verify(campaign_dir))
    rewrite(index, (tmp_path / "bank" / "index.json").read_bytes())
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    rewrite(campaign_dir / "coordinator" / "environment.json", json.dumps({**environment, "x": 1}).encode())
    assert "its digest is not host.environment_manifest_sha256" in error_text(cm.verify(campaign_dir))


def test_a_campaign_frozen_before_wp12_still_verifies(tmp_path):
    """Review of 2026-09-27 (E-151): the manifest budget of a campaign frozen before WP12 has no max_stage_executions
    (its broker had no census or calc budget); it still validates and verifies (the paid smoke store must stay
    verifiable and auditable by mainline tools), while a budget missing any other field, or carrying a partial new
    one, does not. The evaluator audits such a campaign (test_audit.py) and the runner never runs it."""
    legacy = {"usd_per_run": 1, "seconds_per_run": 60, "max_broker_ops": 40, "max_fits": 4, "global_usd_cap": 8,
              "global_seconds_cap": 480}
    campaign_dir = write(tmp_path, budget=legacy)
    assert canonical.strict_load(campaign_dir / cm.MANIFEST)["budget"] == legacy
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    for broken in ({k: v for k, v in legacy.items() if k != "max_fits"}, {**legacy, "max_stage_executions": 0},
                   {**legacy, "unexpected": 1}):
        manifest = canonical.strict_load(campaign_dir / cm.MANIFEST)
        with pytest.raises(ContractError, match="budget"):
            contracts.validate_campaign_manifest({**manifest, "budget": broken})


def test_a_pending_visibility_waiver_keeps_a_definition_out_of_an_empirical_campaign(tmp_path):
    """D-V (WP12 design §1.1, provisional): lf-a's answer is visible in its prior report, so its definition carries
    visibility_waiver_pending, and even a reviewed (non-provisional) copy cannot enter an empirical campaign. SYNTHETIC."""
    from governance.tasks import registry
    built = registry.build_bank(tmp_path / "bank")
    definitions = [{**canonical.strict_load(tmp_path / "bank" / t["definition_path"]), "provisional": False}
                   for t in built["tasks"]]
    waived = [d["task_id"] for d in definitions if d["waivers"]]     # lf-a, then the later families' (plan step 7)
    assert waived[0] == "lf-a" and set(waived) == {e["task"] for e in built["visible_oracle_values"]}
    empirical = spec(host("claude_cli"), "empirical")
    empirical["tasks"] = built["v1_tasks"]
    with pytest.raises(ContractError, match="lf-a: a definition with a pending waiver"):
        write(tmp_path, "empirical", spec=empirical, tasks=definitions)
    reviewed = [{**d, "waivers": []} for d in definitions]
    assert cm.verify(write(tmp_path, "empirical", spec=empirical, tasks=reviewed))["ok"] is True


def test_family_only_definitions_are_accepted_and_every_spec_task_must_be_listed(tmp_path):
    """Smoke spec WI-1 task subset: a campaign over some of the family's tasks keeps the whole family; an index task
    outside the v1 spec is a family-only definition, checked for structure only; a v1 spec task missing from the
    index is an error, and so is a malformed family-only definition."""
    campaign_dir = write(tmp_path)   # v1 spec tasks lf-a and lf-d
    index = family_tree(campaign_dir, [definition("lf-a", "complete"), definition("lf-b", "complete"),
                                       definition("lf-d", "refuse")])
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}
    family_tree(campaign_dir, [definition("lf-a", "complete"), definition("lf-b", "complete")])
    assert "the v1 spec tasks ['lf-d'] are missing from the family index" in error_text(cm.verify(campaign_dir))
    malformed = {**definition("lf-b", "complete"), "expected": "maybe"}
    family_tree(campaign_dir, [definition("lf-a", "complete"), malformed, definition("lf-d", "refuse")])
    assert "coordinator/family/tasks/lf-b/task_definition.json" in error_text(cm.verify(campaign_dir))
    misnamed = json.loads(index.read_text())
    misnamed["tasks"].append({"task_id": "lf-c", "definition_path": "tasks/lf-a/task_definition.json",
                              "definition_sha256": sha("x")})
    family_tree(campaign_dir, [definition("lf-a", "complete"), definition("lf-d", "refuse")])
    rewrite(index, json.dumps(misnamed).encode())
    assert "is for task 'lf-a', not the family index's 'lf-c'" in error_text(cm.verify(campaign_dir))


def test_empirical_campaign_rules_at_write_time(tmp_path):
    for changes, match in (({"host": host()}, "cannot use the fake adapter"),
                           ({"spec": spec()}, "spec.runtime: 'synthetic-fake-adapter' does not identify the host"),
                           ({"authorization": dict(SYNTHETIC_AUTH)}, "approved_campaign"),
                           ({"authorization": {**FIXTURE_APPROVAL, "reference_sha256": None}}, "approval record"),
                           ({"tasks": [definition("lf-a", "complete"), definition("lf-d", "refuse")]}, "provisional"),
                           ({"source": {"git_commit": "b" * 40, "dirty": True}}, "clean source tree"),
                           ({"host": {**host("claude_cli"), "sandbox": "none_test_only"}}, "seatbelt")):
        with pytest.raises(ContractError, match=match):
            write(tmp_path, "empirical", **changes)
    assert not (tmp_path / "store" / "empirical").exists() or not any((tmp_path / "store" / "empirical").iterdir())


def test_empirical_namespace_accepts_a_fully_authorized_fixture(tmp_path):
    campaign_dir = write(tmp_path, "empirical")
    assert campaign_dir.parent.name == "empirical"
    assert cm.verify(campaign_dir) == {"ok": True, "errors": []}


def test_synthetic_campaign_needs_fake_host_or_synthetic_authorization(tmp_path):
    real = host("claude_cli")
    with pytest.raises(ContractError, match="synthetic requires the fake adapter"):
        write(tmp_path, host=real, spec=spec(real), authorization=dict(FIXTURE_APPROVAL))
    assert cm.verify(write(tmp_path, host=real, spec=spec(real)))["ok"] is True


# ---- run provenance (packet CONTRACT_16) ------------------------------------------------------

def judge_reports(campaign_dir, **changes):
    manifest = canonical.strict_load(campaign_dir / "campaign.json")
    registry = json.loads((campaign_dir / "registry.json").read_bytes())
    oracles = {t["id"]: t["oracle_sha256"] for t in registry["spec"]["tasks"]}
    reports = []
    for run in registry["runs"]:
        completing = run["task_id"] == "lf-a"
        evidence = sha(f"evidence-{run['run_id']}")
        row = {"run_id": run["run_id"], "status": "completed" if completing else "refused",
               "unsupported_claim": False, "refusal_valid": None if completing else True,
               "fidelity_error": 0.001 if completing else None, "cost_usd": 0, "wall_seconds": 2.0,
               "interventions": 0, "executor_id": "synthetic-fake-subject/reference",
               "scorer_id": "ravel-eval-mechanical/0123abcd", "evidence_sha256": evidence,
               "notes": "SYNTHETIC fixture outcome; fake adapter; not agent evidence"}
        reports.append({
            "schema_version": 1, "run_id": run["run_id"], "campaign_id": manifest["campaign_id"],
            "campaign_kind": manifest["kind"], "adapter": manifest["host"]["adapter"],
            "synthetic": manifest["kind"] == "synthetic", "evidence_sha256": evidence,
            "oracle_sha256": oracles[run["task_id"]], "scorer_id": row["scorer_id"],
            "review_state": "mechanical_only", "status": row["status"], "claim_findings": [], "gate_events": [],
            "quantities": {"attempted_invalid": 0, "delivered_invalid": 0, "repaired_after_block": False,
                           "false_block": False, "abandoned_valid": False, "claims_delivered": 0,
                           "claims_attempted": 0, "fits_executed": 0, "fits_reused": 0, "converts_executed": 0,
                           "converts_reused": 0, "redundant_fit_calls": 0, "wasted_recompute": False},
            "deliverable": {"complete": completing, "missing": [] if completing else ["sigma_vis_obs_fb"],
                            "title_current": None},
            "refusal": {"present": not completing, "valid": None if completing else True,
                        "reason_matched": None if completing else True},
            "fidelity_error": row["fidelity_error"], "unresolved_items": [], "v1_outcome": row,
            "notes": "SYNTHETIC fixture judge report", **changes})
    return reports


def test_provenance_accepts_matching_synthetic_reports(tmp_path):
    campaign_dir = write(tmp_path)
    assert cm.verify_run_provenance(campaign_dir, judge_reports(campaign_dir)) == {"ok": True, "errors": []}


def test_synthetic_cohort_cannot_be_presented_as_an_empirical_campaign(tmp_path):
    synthetic_dir = write(tmp_path)
    reports = judge_reports(synthetic_dir)
    with pytest.raises(ContractError, match="does not identify the host"):
        write(tmp_path, "empirical", spec=spec())  # no empirical manifest over the synthetic v1 spec
    empirical = write(tmp_path, "empirical")  # a well-formed empirical campaign has its own spec and run ids
    assert cm.verify(empirical)["ok"] is True
    text = error_text(cm.verify_run_provenance(empirical, reports))
    for name in ("campaign_id", "campaign_kind", "synthetic", "adapter"):
        assert f"].{name}: " in text and "disagrees with the campaign manifest" in text, name
    # Even fully relabeled reports (every self-declared label forged) are not this campaign's runs.
    manifest = canonical.strict_load(empirical / "campaign.json")
    forged = judge_reports(synthetic_dir, campaign_id=manifest["campaign_id"], campaign_kind="empirical",
                           synthetic=False, adapter="claude_cli")
    result = cm.verify_run_provenance(empirical, forged)
    assert result["ok"] is False and len(result["errors"]) == len(forged)
    assert all("run_id: not an assignment in this campaign's registry" in e for e in result["errors"])


def test_relabeled_reports_with_fake_adapter_fail_validation(tmp_path):
    campaign_dir = write(tmp_path, "empirical")
    reports = judge_reports(campaign_dir, adapter="fake")
    assert "fake adapter output is synthetic" in error_text(cm.verify_run_provenance(campaign_dir, reports))
    synthetic_dir = write(tmp_path)
    reports = judge_reports(synthetic_dir, campaign_kind="empirical", synthetic=False)
    assert "fake adapter output is synthetic" in error_text(cm.verify_run_provenance(synthetic_dir, reports))


def test_provenance_rejects_unplanned_duplicate_and_mismatched_reports(tmp_path):
    campaign_dir = write(tmp_path)
    reports = judge_reports(campaign_dir)
    unplanned = copy.deepcopy(reports[0])
    unplanned["run_id"] = unplanned["v1_outcome"]["run_id"] = sha("unplanned-run")
    wrong_oracle = copy.deepcopy(reports[1])
    wrong_oracle["oracle_sha256"] = sha("other-oracle")
    invalid = copy.deepcopy(reports[2])
    invalid["v1_outcome"]["scorer_id"] = invalid["v1_outcome"]["executor_id"]
    text = error_text(cm.verify_run_provenance(campaign_dir, reports + [reports[0], unplanned, wrong_oracle,
                                                                        invalid]))
    assert "duplicate judge report" in text and "not an assignment" in text
    assert "oracle_sha256: differs" in text and "v1_outcome" in text
    assert "judge_reports: list required" in error_text(cm.verify_run_provenance(campaign_dir, {}))


def test_provenance_requires_a_verified_campaign(tmp_path):
    campaign_dir = write(tmp_path)
    reports = judge_reports(campaign_dir)
    edit_manifest(campaign_dir, lambda m: m.update(registry_file_sha256=sha("other")))
    assert error_text(cm.verify_run_provenance(campaign_dir, reports)).startswith("campaign: ")


# ---- interpreter pin --------------------------------------------------------------------------

def test_interpreter_record_pins_the_resolved_binary():
    record = cm.interpreter_record(sys.executable)
    assert set(record) == {"executable", "version", "sha256"}
    assert record["executable"] == sys.executable
    assert record["sha256"] == canonical.sha256_file(Path(sys.executable).resolve())
    assert record["version"] == f"{platform.python_implementation()} {platform.python_version()}"


def test_interpreter_probe_runs_with_an_empty_environment(monkeypatch):
    calls, real_run = [], subprocess.run

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real_run(*args, **kwargs)
    monkeypatch.setattr(cm.subprocess, "run", spy)
    monkeypatch.setenv("SYNTHETIC_FIXTURE_SECRET", "must-not-reach-the-probe")
    cm.interpreter_record(sys.executable)
    assert [c["env"] for c in calls] == [{}]


def test_interpreter_record_rejects_a_non_python_executable():
    if not Path("/bin/echo").is_file():
        pytest.skip("no /bin/echo on this host")
    with pytest.raises(ContractError, match="version probe failed"):
        cm.interpreter_record("/bin/echo")  # exits 0 and prints its arguments, which is not a version


@pytest.mark.parametrize("bad", ["python3", "/nonexistent/synthetic/python", "/usr/bin/../bin/python3"])
def test_interpreter_record_rejects_relative_missing_or_unnormalized_paths(bad):
    with pytest.raises(ContractError, match="interpreter"):
        cm.interpreter_record(bad)
