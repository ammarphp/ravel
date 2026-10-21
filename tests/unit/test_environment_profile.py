"""Inert environment observations and private site-profile persistence."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
import threading
import time
from types import SimpleNamespace

import pytest

from ravel.setup import environment_profile as ep
from ravel.setup import manifest as mf
from ravel.controller.authority import operator
from ravel.workflow.backends import site_batch


def _settings(**changes):
    result = {"scheduler": None, "requires_proxy": False, "requires_kerberos": False,
              "requires_afs": False, "cvmfs": []}
    result.update(changes)
    return result


def _site(**changes):
    values = dict(name="temporary-site", seed="generic", settings=_settings(),
                  now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    values.update(changes)
    return ep.site_profile_document(**values)


def _probes(calls=None):
    calls = calls if calls is not None else {}
    values = {
        "host": {"system": "Test", "release": "1", "machine": "test", "python": "3"},
        "platform": "unknown",
        "resources": {"cpus": 4, "cpus_usable": 2, "memory_bytes": 4096, "disk": []},
        "gpus": {"count": 0, "source": "none-detected", "names": []},
        "network": {"egress": "available", "source": "probe", "checks": []},
        "batch": {"system": "none", "available": [], "inside_job": None, "source": "detected"},
        "sandbox": {"backend": None, "backends": {}},
        "containers": {name: None for name in ("podman", "apptainer", "singularity", "docker")},
        "tools": {"observed": True, "source": "doctor-census", "prefix": None,
                  "reason": None, "rows": {}},
    }
    def make(name):
        def probe(*args, **kwargs):
            calls[name] = (args, kwargs)
            return deepcopy(values[name])
        return probe
    return {name: make(name) for name in values}


def test_observe_schema_roots_and_injected_probe_call_contract(tmp_path):
    calls = {}
    result = ep.observe(run_dir=tmp_path / "run", store_root=tmp_path / "store",
                        prefix=tmp_path / "prefix", probes=_probes(calls))
    assert result["schema"] == ep.SCHEMA == "ravel-environment-profile.v1"
    assert set(result) == {"schema", "observed_utc", "ravel_version", "platform", "host",
                           "resources", "filesystem", "network", "batch", "sandbox",
                           "containers", "tools", "sources", "site_profile", "probe_errors"}
    assert result["sources"] == {"mirror": None}
    assert isinstance(result["observed_utc"], str) and result["observed_utc"]
    assert isinstance(result["ravel_version"], str) and result["ravel_version"]
    assert set(result["host"]) == {"system", "release", "machine", "python"}
    assert set(result["resources"]) == {"cpus", "cpus_usable", "memory_bytes", "disk", "gpus"}
    assert result["resources"]["gpus"] == {"count": 0, "source": "none-detected", "names": []}
    roots = result["filesystem"]["roots"]
    assert roots and all(Path(path).is_absolute() for path in roots.values())
    assert str((tmp_path / "run").resolve()) in roots.values()
    assert str((tmp_path / "store").resolve()) in roots.values()
    assert calls["resources"] == ((roots,), {})
    assert calls["tools"] == ((), {"prefix": tmp_path / "prefix"})
    assert calls["batch"] == ((), {"scheduler": None})
    for name in ("host", "platform", "gpus", "network", "sandbox", "containers"):
        assert calls[name] == ((), {})
    assert result["site_profile"] is None
    assert result["probe_errors"] == []


@pytest.mark.parametrize("name", ["host", "platform", "resources", "gpus", "network", "batch",
                                  "sandbox", "containers", "tools"])
def test_observe_contains_each_probe_exception(name):
    probes = _probes()
    def failed(*args, **kwargs):
        raise RuntimeError("failure " + "x" * 500)
    probes[name] = failed
    result = ep.observe(probes=probes)
    error = next(row for row in result["probe_errors"] if row["probe"] == name)
    assert "RuntimeError" in error["error"] and "failure" in error["error"]
    assert len(error["error"]) <= 300
    assert result["schema"] == ep.SCHEMA


def test_tools_can_be_explicitly_unobserved():
    calls = {}
    result = ep.observe(probes=_probes(calls), tools=False)
    assert result["tools"] == {"observed": False, "reason": "not requested"}
    assert "tools" not in calls


@pytest.mark.parametrize("policy,egress", [("offline", "none"), ("online", "available")])
def test_site_network_policy_skips_probe_and_declares_scheduler(policy, egress):
    calls = {}
    site = _site(network_policy=policy, settings=_settings(scheduler="slurm"))
    result = ep.observe(site=site, probes=_probes(calls))
    assert result["network"] == {"egress": egress, "source": "site-profile", "checks": []}
    assert "network" not in calls
    assert calls["batch"] == ((), {"scheduler": "slurm"})
    assert result["batch"]["system"] == "slurm"
    assert result["batch"]["source"] == "site-profile"


def test_loaded_site_pin_is_retained():
    pin = {"path": "/temporary/profile.json", "sha256": "a" * 64, "name": "temporary-site"}
    result = ep.observe(site=(_site(), pin), probes=_probes())
    assert result["site_profile"] == pin


def test_site_mirror_reaches_the_profile():
    result = ep.observe(site=_site(mirror="/fictional/mirror"), probes=_probes())
    assert result["sources"] == {"mirror": "/fictional/mirror"}


@pytest.mark.parametrize("systems,expected", [([], "none"), (["slurm"], "slurm"),
                                             (["htcondor"], "htcondor"),
                                             (["slurm", "htcondor"], "multiple")])
def test_batch_requires_complete_command_sets_without_execution(systems, expected):
    searched = []
    installed = {command for system in systems for command in site_batch.COMMANDS[system]}
    def which(command):
        searched.append(command)
        return "/fake/bin/" + command if command in installed else None
    result = ep.probe_batch(environ={}, which=which)
    assert result["system"] == expected
    assert set(result["available"]) == set(systems)
    assert result["inside_job"] is None
    assert result["source"] == "detected"
    assert installed <= set(searched)
    assert set(searched) <= {command for commands in site_batch.COMMANDS.values() for command in commands}
    assert all(commands[0] in searched for commands in site_batch.COMMANDS.values())


@pytest.mark.parametrize("system", list(site_batch.COMMANDS))
def test_batch_partial_command_set_is_unavailable(system):
    installed = set(site_batch.COMMANDS[system][:-1])
    result = ep.probe_batch(environ={}, which=lambda name: "/fake/" + name if name in installed else None)
    assert result["system"] == "none" and result["available"] == []


@pytest.mark.parametrize("key,system", [("SLURM_JOB_ID", "slurm"),
                                        ("_CONDOR_JOB_AD", "htcondor"),
                                        ("_CONDOR_SCRATCH_DIR", "htcondor")])
def test_batch_inside_job_markers(key, system):
    result = ep.probe_batch(environ={key: "present"}, which=lambda name: None)
    assert result["inside_job"] == system
    assert result["system"] == system


@pytest.mark.parametrize("scheduler", ["slurm", "htcondor"])
def test_batch_declared_scheduler_is_recorded_without_fabricating_commands(scheduler):
    result = ep.probe_batch(environ={}, which=lambda name: None, scheduler=scheduler)
    assert result["system"] == scheduler
    assert result["source"] == "site-profile"
    assert result["available"] == []


class _Connection:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True


def test_network_connector_contract_closes_successful_connections():
    calls, connections = [], []
    def connect(address, *, timeout):
        calls.append((address, timeout))
        connection = _Connection()
        connections.append(connection)
        return connection
    result = ep.probe_network(endpoints=[("first.invalid", 443), ("second.invalid", 8443)],
                              timeout=0.2, connect=connect)
    assert calls == [(("first.invalid", 443), 0.2), (("second.invalid", 8443), 0.2)]
    assert all(connection.closed for connection in connections)
    assert result["egress"] == "available" and result["source"] == "probe"
    assert result["checks"] == [{"host": host, "port": port, "ok": True, "error": None}
                                 for host, port in [call[0] for call in calls]]


def test_network_failed_and_empty_endpoint_results():
    def fail(address, *, timeout):
        raise OSError("transport unavailable")
    result = ep.probe_network(endpoints=[("unavailable.invalid", 443)], connect=fail)
    assert result["egress"] == "none"
    assert result["checks"][0]["ok"] is False
    assert "transport unavailable" in result["checks"][0]["error"]
    empty = ep.probe_network(endpoints=[], connect=fail)
    assert empty["egress"] == "unknown" and empty["checks"] == []


def test_network_hanging_connector_has_an_outer_deadline():
    release = threading.Event()
    def hang(address, *, timeout):
        release.wait()
        return _Connection()
    started = time.monotonic()
    try:
        result = ep.probe_network(endpoints=[("blocked.invalid", 443)], timeout=0.05, connect=hang)
        assert time.monotonic() - started <= 2.05
        assert result["egress"] == "none"
        assert result["checks"][0]["ok"] is False
    finally:
        release.set()


def _tool_row(**changes):
    row = {"readiness": "ready", "status": "built_but_unqualified", "version": "1.2",
           "licence": "not_applicable", "platform_qualification": ""}
    row.update(changes)
    return row


def _availability(profile, census_id):
    result = ep.tool_status(profile, census_id)
    if result["reason"] == "unobserved":
        assert result == {"available": False, "reason": "unobserved", "readiness": None, "version": None}
    else:
        row = profile["tools"]["rows"][census_id]
        assert result == {"available": result["reason"] is None, "reason": result["reason"],
                          "readiness": row["readiness"], "version": row["version"]}
    return {key: result[key] for key in ("available", "reason")}


def _tool_profile(row):
    return {"tools": {"observed": True, "rows": {"tool-a": row}}}


@pytest.mark.parametrize("readiness,reason", [("ready", None), ("remote_route", "remote_only"),
    ("missing", "not_installed"), ("manual_required", "not_installed"),
    ("version_mismatch", "version_mismatch"), ("unconfigured", "unconfigured"),
    ("unsupported", "unsupported_platform"), ("excluded", "excluded")])
def test_tool_status_closed_reason_mapping(readiness, reason):
    assert _availability(_tool_profile(_tool_row(readiness=readiness)), "tool-a") == {
        "available": reason is None, "reason": reason}


@pytest.mark.parametrize("licence,reason", [("unlicensed", "unlicensed"),
                                           ("licensed", "unconfigured"),
                                           ("unknown", "unconfigured"),
                                           ("not_applicable", "unconfigured")])
def test_unconfigured_tool_uses_licence_discriminator(licence, reason):
    assert _availability(_tool_profile(_tool_row(readiness="unconfigured", licence=licence)),
                          "tool-a") == {"available": False, "reason": reason}


@pytest.mark.parametrize("readiness,reason", [("ready", "unqualified_platform"),
                                              ("missing", "not_installed"),
                                              ("unsupported", "unsupported_platform")])
def test_platform_requirement_overrides_only_ready(readiness, reason):
    row = _tool_row(readiness=readiness, platform_qualification="required record absent")
    assert _availability(_tool_profile(row), "tool-a") == {"available": False, "reason": reason}


@pytest.mark.parametrize("profile", [None, [], {}, {"tools": None}, {"tools": []},
    {"tools": {"observed": False}}, {"tools": {"observed": True}},
    {"tools": {"observed": True, "rows": []}}, {"tools": {"observed": True, "rows": {}}},
    _tool_profile(None), _tool_profile([]), _tool_profile({}),
    _tool_profile(_tool_row(readiness=2)), _tool_profile(_tool_row(status=[])),
    _tool_profile(_tool_row(version=2)), _tool_profile(_tool_row(licence=True)),
    _tool_profile(_tool_row(platform_qualification=[]))])
def test_missing_or_malformed_tool_facts_are_unobserved(profile):
    assert _availability(profile, "tool-a") == {"available": False, "reason": "unobserved"}


def test_site_document_contract_and_default_observed_state():
    document = _site()
    assert document["schema"] == ep.SITE_SCHEMA == "ravel-site-profile.v1"
    assert set(document) == {"schema", "name", "created_utc", "seed", "settings", "network",
                             "sources", "observed"}
    assert document["settings"] == _settings()
    assert document["network"] == {"policy": "auto"}
    assert document["sources"] == {"mirror": None}
    assert datetime.fromisoformat(document["created_utc"].replace("Z", "+00:00")) == datetime(
        2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert ep.validate_site_profile(document) == []


@pytest.mark.parametrize("key", ["schema", "name", "created_utc", "seed", "settings", "network",
                                 "sources", "observed"])
def test_site_validator_rejects_missing_top_level_keys(key):
    document = _site()
    del document[key]
    assert ep.validate_site_profile(document)


@pytest.mark.parametrize("section,key,value", [
    (None, "extra", True), (None, "schema", "other"), (None, "name", ""),
    (None, "name", 2), (None, "seed", "other"), (None, "created_utc", "invalid"),
    ("settings", "extra", True), ("settings", "scheduler", "other"),
    ("settings", "requires_proxy", 1), ("settings", "requires_kerberos", "yes"),
    ("settings", "requires_afs", None), ("settings", "cvmfs", "not-a-list"),
    ("settings", "cvmfs", ["relative"]), ("settings", "cvmfs", [2]),
    ("network", "extra", True), ("network", "policy", "other"),
    ("sources", "extra", True), ("sources", "mirror", "relative"),
    ("sources", "mirror", 2), (None, "observed", {"schema": "other"}),
])
def test_site_validator_rejects_unknown_and_invalid_values(section, key, value):
    document = _site()
    target = document if section is None else document[section]
    target[key] = value
    assert ep.validate_site_profile(document)


@pytest.mark.parametrize("key", list(_settings()))
def test_site_validator_requires_all_setting_keys(key):
    document = _site()
    del document["settings"][key]
    assert ep.validate_site_profile(document)


def test_site_requires_credentials_for_shared_path_access():
    with pytest.raises(ValueError):
        _site(settings=_settings(requires_afs=True))
    document = _site(settings=_settings(requires_afs=True, requires_kerberos=True,
                                        requires_proxy=True, cvmfs=["/temporary/mount"]),
                     mirror="/temporary/mirror", observed={"schema": ep.SCHEMA})
    assert ep.validate_site_profile(document) == []


def test_site_roundtrip_is_private_canonical_and_pinned(tmp_path):
    path = tmp_path / "private" / "profile.json"
    document = _site()
    saved_pin = ep.save_site_profile(document, path=path)
    raw = path.read_bytes()
    assert raw == (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    loaded, pin = ep.load_site_profile(path=path)
    assert saved_pin == pin
    assert loaded == document
    assert pin == {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                   "name": document["name"]}
    replacement = _site(name="replacement")
    ep.save_site_profile(replacement, path=path)
    assert ep.load_site_profile(path=path)[0] == replacement
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_site_save_keeps_the_mode_of_an_existing_directory(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)
    ep.save_site_profile(_site(), path=shared / "profile.json")
    assert stat.S_IMODE(shared.stat().st_mode) == 0o755
    assert stat.S_IMODE((shared / "profile.json").stat().st_mode) == 0o600


def test_site_absent_profile_and_default_controller_home(tmp_path, monkeypatch):
    monkeypatch.setattr(operator, "controller_home", lambda: tmp_path)
    assert ep.site_profile_path() == tmp_path / "site" / "profile.json"
    assert ep.load_site_profile() == (None, None)
    ep.save_site_profile(_site())
    assert ep.load_site_profile()[0]["name"] == "temporary-site"


def test_site_invalid_document_is_never_written(tmp_path):
    path = tmp_path / "profile.json"
    with pytest.raises(ValueError):
        ep.save_site_profile({"schema": "other"}, path=path)
    assert not path.exists()


@pytest.mark.parametrize("text", ["not json", "[]", '{"schema": "other"}'])
def test_site_load_rejects_invalid_json_or_document(tmp_path, text):
    path = tmp_path / "profile.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        ep.load_site_profile(path=path)


@pytest.mark.parametrize("kind", ["directory", "file-link", "broken-link", "ancestor-link"])
def test_site_persistence_rejects_nonregular_and_symlink_paths(tmp_path, kind):
    target = tmp_path / "target"
    target.mkdir()
    regular = target / "profile.json"
    regular.write_text(json.dumps(_site()))
    path = tmp_path / "profile.json"
    if kind == "directory":
        path.mkdir()
    elif kind == "file-link":
        path.symlink_to(regular)
    elif kind == "broken-link":
        path.symlink_to(tmp_path / "absent")
    else:
        link = tmp_path / "link"
        link.symlink_to(target, target_is_directory=True)
        path = link / "profile.json"
    for operation in (lambda: ep.load_site_profile(path=path),
                      lambda: ep.save_site_profile(_site(), path=path)):
        with pytest.raises(ValueError):
            operation()


def test_network_default_endpoints_use_configured_constants(monkeypatch):
    from ravel.workflow import discovery_http
    monkeypatch.setattr(discovery_http, "HEPDATA", "https://first.invalid/path")
    monkeypatch.setattr(discovery_http, "INSPIRE", "https://second.invalid/path")
    calls = []
    def connect(address, *, timeout):
        calls.append(address)
        return _Connection()
    result = ep.probe_network(connect=connect)
    assert calls == [("first.invalid", 443), ("second.invalid", 443)]
    assert result["egress"] == "available"


def test_probe_tools_uses_existing_observations_and_qualification_reasons(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")
    monkeypatch.setattr(mf, "manifest_path", lambda repo: manifest_path)
    groups = [
        {"id": "group-a", "checks": [{"id": "kernel", "kind": "wolfram"}],
         "qualification": {"required_per_platform": True, "status": "built-unqualified"}},
        {"id": "group-b", "checks": [{"id": "present", "kind": "file"}],
         "qualification": {"required_per_platform": True, "status": "built-unqualified"}},
    ]
    def check(group, name, status="ready", **changes):
        return {"binding": {"kind": "manifest", "group": group, "check": name},
                "status": status, **changes}
    census_rows = [
        {"id": "tool-a", "readiness": "ready", "status": "built_but_unqualified", "checks": [
            check("group-a", "kernel", found="1.2"),
            check("group-b", "present", found="2.3")]},
        {"id": "tool-b", "readiness": "unconfigured", "status": "built_but_unqualified", "checks": [
            check("group-a", "kernel", "unconfigured", detail="Kernel not activated")]},
        {"id": "tool-c", "readiness": "unconfigured", "status": "built_but_unqualified", "checks": [
            check("group-b", "present", "unconfigured", detail="Kernel not activated")]},
        {"id": "tool-d", "readiness": "missing", "status": "not_installed", "checks": [
            check("group-a", "kernel", "missing")]},
    ]
    doctor = SimpleNamespace(prefix=tmp_path / "prefix", platform="unknown",
                             manifest={"groups": groups}, census_report=lambda: deepcopy(census_rows))
    result = ep.probe_tools(prefix=tmp_path / "unused", repo=tmp_path, doctor=doctor)
    assert result["observed"] is True
    assert result["source"] == "doctor-census" and result["reason"] is None
    assert result["prefix"] == str(doctor.prefix)
    row = result["rows"]["tool-a"]
    assert row == {"readiness": "ready", "status": "built_but_unqualified", "version": "1.2",
                   "licence": "licensed", "platform_qualification": "; ".join(
                       mf.platform_qualification_reason(group, doctor.platform) for group in groups)}
    assert result["rows"]["tool-b"]["licence"] == "unlicensed"
    assert result["rows"]["tool-c"]["licence"] == "not_applicable"
    assert result["rows"]["tool-d"]["licence"] == "unknown"
    assert result["rows"]["tool-d"]["version"] is None


def test_probe_tools_absent_manifest_never_constructs_doctor(tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "manifest_path", lambda repo: tmp_path / "absent.json")
    result = ep.probe_tools(repo=tmp_path)
    assert result == {"observed": False, "source": "doctor-census", "prefix": None,
                      "reason": "toolchain manifest unavailable", "rows": {}}


def test_resource_probe_uses_injected_capacity_and_existing_disk_ancestor(tmp_path, monkeypatch):
    monkeypatch.setattr(ep.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(ep.os, "sched_getaffinity", lambda pid: {1, 2}, raising=False)
    monkeypatch.setattr(ep.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 16}[key])
    paths = []
    def usage(path):
        paths.append(path)
        return SimpleNamespace(free=100, total=200)
    monkeypatch.setattr(ep.shutil, "disk_usage", usage)
    result = ep.probe_resources({"run": str(tmp_path / "missing" / "run")})
    assert result == {"cpus": 8, "cpus_usable": 2, "memory_bytes": 65536,
                      "disk": [{"root": "run", "path": str(tmp_path), "free_bytes": 100,
                                "total_bytes": 200}]}
    assert paths == [tmp_path]


def test_gpu_probe_uses_injected_runner_and_handles_failure():
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="GPU 0: Device A (UUID: hidden)\nGPU 1: Device B\n")
    result = ep.probe_gpus(which=lambda name: "/fake/device-query", run=run)
    assert result == {"count": 2, "source": "nvidia-smi", "names": ["Device A", "Device B"]}
    assert calls == [(["/fake/device-query", "-L"],
                      {"capture_output": True, "text": True, "timeout": 10, "check": False})]
    assert ep.probe_gpus(which=lambda name: None) == {
        "count": 0, "source": "none-detected", "names": []}
    def failed(*args, **kwargs):
        raise OSError("unavailable")
    assert ep.probe_gpus(which=lambda name: "/fake/device-query", run=failed) == {
        "count": None, "source": "not-probed", "names": []}


def test_container_probe_is_only_command_lookup():
    searched = []
    def which(name):
        searched.append(name)
        return "/fake/" + name if name == "podman" else None
    assert ep.probe_containers(which=which) == {
        "podman": "/fake/podman", "apptainer": None, "singularity": None, "docker": None}
    assert searched == ["podman", "apptainer", "singularity", "docker"]


def test_sandbox_probe_reuses_existing_availability(monkeypatch):
    from ravel.workflow import sandbox
    from ravel.controller.confine import launcher
    monkeypatch.setattr(sandbox, "available", lambda: "linux")
    monkeypatch.setattr(launcher, "backends", lambda: {"linux": "available"})
    assert ep.probe_sandbox() == {"backend": "linux", "backends": {"linux": "available"}}


@pytest.mark.parametrize("kind", ["duplicate", "nan", "infinity"])
def test_site_load_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path, kind):
    path = tmp_path / "profile.json"
    document = _site()
    if kind == "duplicate":
        raw = json.dumps(document)[:-1] + ', "name": "replacement"}'
    else:
        document["observed"] = {"schema": ep.SCHEMA,
                                "value": float("nan") if kind == "nan" else float("inf")}
        raw = json.dumps(document)
    path.write_text(raw)
    with pytest.raises(ValueError):
        ep.load_site_profile(path=path)


def test_site_pin_hashes_exact_input_bytes(tmp_path):
    path = tmp_path / "profile.json"
    document = _site()
    raw = (" \n" + json.dumps(document, separators=(",", ":")) + "\n\n").encode()
    path.write_bytes(raw)
    loaded, pin = ep.load_site_profile(path=path)
    assert loaded == document
    assert pin["sha256"] == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw


def test_per_call_probe_overrides_do_not_mutate_default_probe_table(monkeypatch):
    defaults = _probes()
    monkeypatch.setattr(ep, "PROBES", defaults)
    snapshot = dict(defaults)
    result = ep.observe(probes={"platform": lambda: "linux-x86_64"})
    assert result["platform"] == "linux-x86_64"
    assert ep.PROBES == snapshot
    assert ep.observe()["platform"] == "unknown"


def test_all_probe_failures_preserve_complete_profile():
    def failed(*args, **kwargs):
        raise ValueError("unavailable")
    result = ep.observe(probes={name: failed for name in _probes()})
    assert {row["probe"] for row in result["probe_errors"]} == set(_probes())
    assert set(result) == {"schema", "observed_utc", "ravel_version", "platform", "host",
                           "resources", "filesystem", "network", "batch", "sandbox",
                           "containers", "tools", "sources", "site_profile", "probe_errors"}
    assert result["sources"] == {"mirror": None}
    assert result["platform"] == "unknown"
    assert result["resources"]["cpus"] is None
    assert result["resources"]["gpus"]["count"] is None
    assert result["network"]["egress"] == "unknown"
    assert result["tools"]["observed"] is False


def test_network_one_success_is_sufficient():
    connection = _Connection()
    def connect(address, *, timeout):
        if address[0] == "unavailable.invalid":
            raise OSError("transport unavailable")
        return connection
    result = ep.probe_network(endpoints=[("unavailable.invalid", 443), ("available.invalid", 443)],
                              connect=connect)
    assert result["egress"] == "available"
    assert [row["ok"] for row in result["checks"]] == [False, True]
    assert connection.closed


def test_failed_atomic_replace_preserves_previous_document(tmp_path, monkeypatch):
    path = tmp_path / "private" / "profile.json"
    ep.save_site_profile(_site(), path)
    original = path.read_bytes()
    def failed_replace(source, destination):
        assert Path(source).parent == path.parent
        assert destination == path
        assert stat.S_IMODE(Path(source).stat().st_mode) == 0o600
        raise OSError("replace refused")
    monkeypatch.setattr(ep.os, "replace", failed_replace)
    with pytest.raises(OSError, match="replace refused"):
        ep.save_site_profile(_site(name="replacement"), path)
    assert path.read_bytes() == original
    assert list(path.parent.iterdir()) == [path]


def test_site_validator_reports_independent_problems_together():
    document = _site()
    document["name"] = "Invalid name"
    document["created_utc"] = "2026-01-02Z"
    document["settings"]["requires_afs"] = True
    document["network"]["extra"] = 1
    document["sources"]["mirror"] = "relative"
    errors = ep.validate_site_profile(document)
    assert len(errors) == 5
    for field in ("name", "created_utc", "requires_afs", "extra", "mirror"):
        assert any(field in error for error in errors)
