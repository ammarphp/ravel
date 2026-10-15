"""Installer completion controls with synthetic inputs and inert runners only."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from ravel import analysis_catalog as ac
from ravel.setup import doctor, manifest as mf, steps
from ravel.setup.fetch import DigestMismatch
from setup_fakes import FakeRunner
from test_setup_engine import world, make
from test_setup_doctor import make_doctor
from test_setup_install_shim import system, fake

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("failure", [steps.StepError, steps.Conflict, DigestMismatch])
def test_independent_groups_survive_failure(world, monkeypatch, failure):
    from ravel.setup import installer
    groups = world["manifest"]["groups"]
    groups[2]["depends_on"] = []
    groups.append(dict(groups[1], id="descendant", depends_on=["data"], steps=[]))
    world["manifest"]["default"]["groups"].append("descendant")
    original = installer.run_step
    def run_step(step, ctx):
        if step["id"] == "env":
            if failure is DigestMismatch:
                raise failure("https://example.org/synthetic", "a"*64, "b"*64, ctx.prefix / "quarantine/synthetic")
            raise failure("synthetic fault")
        return original(step, ctx)
    monkeypatch.setattr(installer, "run_step", run_step)
    tool, _ = make(world)
    result = tool.run()
    assert result["status"] == "incomplete"
    assert result["groups"]["build"]["status"] == "done"
    assert result["groups"]["data"]["reason"] == "waits for base"
    assert result["groups"]["descendant"]["reason"] == "waits for data"
    row = result["failed"][0]
    assert row["group"] == "base" and row["step"] == "base/env"
    assert row["error"] and Path(row["log"]).is_file()
    assert row["fix"] and "--resume" in result["rerun"]
    assert "waits for base" in tool.stream.getvalue()
    monkeypatch.setattr(installer, "Installer", lambda *a, **k: tool)
    monkeypatch.setattr(installer, "write_pointer", lambda *a: None)
    assert installer.main([], repo=world["repo"]) == 1


def test_all_failures_are_retained(world):
    world["manifest"]["groups"][2]["depends_on"] = []
    tool, _ = make(world, FakeRunner(fail=lambda argv: True))
    result = tool.run()
    assert {f["group"] for f in result["failed"]} == {"base", "build"}
    assert set(result["groups"]) == {"base", "data", "build"}


def test_summary_retains_outcomes_and_rerun(world):
    tool, _ = make(world, FakeRunner(fail=lambda argv: True))
    result = tool.run()
    summary = json.loads(Path(result["summary"]).read_text())
    assert summary["failed"] == result["failed"]
    assert summary["groups"] == result["groups"]
    assert summary["rerun"] == result["rerun"]


def test_failure_fix_keeps_run_options(world):
    tool, _ = make(world, FakeRunner(fail=lambda argv: True), adopt=True, offline=True)
    result = tool.run()
    fix = result["failed"][0]["fix"]
    assert "--only base" in fix and "--resume" in fix
    assert "--jobs 2" in fix and "--offline" in fix and "--adopt" in fix


def test_resume_skips_completed_independent_group(world):
    world["manifest"]["groups"][2]["depends_on"] = []
    tool, _ = make(world, FakeRunner(fail=lambda argv: Path(argv[0]).name == "conda"))
    assert tool.run()["groups"]["build"]["status"] == "done"
    resumed, _ = make(world)
    assert resumed.run()["status"] == "complete"
    assert not any(Path(c[0]).name == "make-outputs" for c in resumed.runner.calls)


def test_serial_build_environment_is_step_local(world):
    tool, _ = make(world)
    tool.values["JOBS"] = "8"
    groups = mf.by_id(mf.load(ROOT)[0])
    host = next(s for s in groups["python-host"]["steps"] if s["id"] == "python-environments")
    integral = groups["finite-integrals"]["steps"][0]
    env_step = copy.deepcopy(integral)
    env_step["name"] = "synthetic-integrals"
    # Reuse only the environment contract; package installation is inert.
    env_step["specs"], env_step["pip"] = ["python=3.12"], ["synthetic==1.0"]
    command = {"id": "host", "kind": "command", "env": host.get("env", {}),
               "argv": ["make-outputs", "{BIN}/host"], "outputs": ["{BIN}/host"]}
    other = dict(command, id="other", env={}, argv=["make-outputs", "{BIN}/other"], outputs=["{BIN}/other"])
    world["manifest"]["groups"][0]["steps"] = [env_step, command, other]
    assert tool.run("site")["status"] == "complete"
    for env in tool.runner.envs[:-1]:
        assert env["MAKEFLAGS"] == "-j1" and env["SCONSFLAGS"] == "-j1"
    assert tool.runner.envs[-1]["MAKEFLAGS"] == "-j8"


def test_clone_failure_names_git_version(world):
    class GitRunner(FakeRunner):
        def capture(self, argv, **kwargs):
            if argv == ["git", "--version"]:
                return 0, "git version 2.15.0"
            return super().capture(argv, **kwargs)
    tool, _ = make(world, GitRunner(fail=lambda argv: argv[:2] == ["git", "clone"]))
    assert "git version 2.15.0" in tool.run("site")["groups"]["base"]["error"]


@pytest.mark.parametrize("version,exit_code", [("2.15.0", 3), ("2.39.0", 0)])
def test_git_preflight_minimum(system, version, exit_code):
    _, run, tmp = system
    fake(tmp / "fakebin", "git", f"echo 'git version {version}'")
    result = run("--preflight-only", "--no-disk-check", prefix=tmp / "p")
    assert result.returncode == exit_code
    if exit_code:
        assert "PATH=/usr/bin:$PATH" in result.stderr and "newer git" in result.stderr


def test_manifest_catalogue_contract():
    manifest, catalog = mf.load(ROOT)
    mf.validate(manifest, catalog)
    group = mf.by_id(manifest)["analysis-catalogue"]
    assert group["depends_on"] == ["python-host", "rivet-shower", "restframes"]
    source, build = group["steps"]
    assert source["commit"] == "0f6596fac03b40566ccdfae5b3e062b7f56a055a"
    assert source["dest"] == "{TOOLS}/rivet-src"
    assert build["argv"][:3] == ["{HOST_PYTHON}", "-m", "ravel.workflow.analysis_catalog_build"]
    assert build["argv"][build["argv"].index("--rivet-ref")+1] == source["commit"]
    sa = next(s for s in mf.by_id(manifest)["restframes"]["steps"] if s["id"] == "simpleanalysis-source")
    assert build["argv"][build["argv"].index("--simpleanalysis-ref")+1] == sa["commit"]
    assert build["argv"][build["argv"].index("--out")+1] == build["outputs"][0]
    assert build["outputs"][0].startswith("{P}/")
    assert group["id"] in manifest["default"]["groups"]
    assert not any(group["id"] in g["depends_on"] for g in manifest["groups"])
    assert any(c["kind"] == "agent_cli" for c in mf.by_id(manifest)["research-host"]["checks"])


def synthetic_catalogue(revision="a"*40):
    row = dict(id="rivet:SYNTHETIC_ROUTINE", name="SYNTHETIC_ROUTINE", framework="rivet", source_id="rivet",
               physics_validated_by_ravel=False, source_files=[], reference_files=[], plot_files=[], analysis_ids=[],
               publication_urls=[], model_index_matches=[], metadata_issues=[], features={}, metadata={},
               experiment="SYNTHETIC", title="Synthetic observable", upstream_status="UNVALIDATED",
               source_relation="unresolved", inspire_id=None)
    row["family"] = ac.classify(row)["family"]
    value = dict(schema_version=1, sources={
        "rivet": dict(revision=revision, repository="https://example.org/rivet", selected_info_files=1),
        "simpleanalysis": dict(revision="b"*40, repository="https://example.org/simple", registered_routines=0)}, entries=[row])
    value["summary"] = ac.summarize(value)
    return ac.validate_catalog(value)


@pytest.mark.parametrize("case,status", [("missing", "missing"), ("invalid", "unconfigured"),
                                          ("wrong", "version_mismatch"), ("valid", "ready")])
def test_catalogue_doctor(tmp_path, case, status):
    d = make_doctor(tmp_path)
    path = ac.installed_catalog_path(d.prefix)
    if case != "missing":
        path.parent.mkdir(parents=True)
        path.write_text("{}" if case == "invalid" else json.dumps(synthetic_catalogue("c"*40 if case == "wrong" else "a"*40)))
    check = dict(id="catalogue", kind="analysis_catalogue", rivet_ref="a"*40,
                 rebuild=["{HOST_PYTHON}", "-m", "ravel.workflow.analysis_catalog_build", "--rivet", "{TOOLS}/rivet-src",
                          "--rivet-ref", "a"*40, "--simpleanalysis", "{TOOLS}/simple-analysis-src",
                          "--simpleanalysis-ref", "b"*40, "--out", str(path), "--force"])
    result = d.evaluate_check(dict(id="catalogue"), check)
    assert result["status"] == status
    if status != "ready":
        assert "--out" in result["fix"] and "--force" in result["fix"] and "a"*40 in result["fix"]


def test_catalogue_invalid_sources_are_reported(tmp_path):
    d = make_doctor(tmp_path)
    path = ac.installed_catalog_path(d.prefix)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema_version": 1, "sources": []}))
    result = d.evaluate_check(dict(id="catalogue"), dict(id="catalogue", kind="analysis_catalogue",
        rivet_ref="a"*40, rebuild=["{HOST_PYTHON}", "-m", "ravel.workflow.analysis_catalog_build", "--force"]))
    assert result["status"] == "unconfigured" and "--force" in result["fix"]


def test_installed_catalogue_prefix_resolution(tmp_path, monkeypatch):
    from ravel import paths
    monkeypatch.setattr(paths, "native_build_root", lambda: tmp_path)
    assert ac.installed_catalog_path() == tmp_path / "share/ravel/analysis-catalog.json"


def test_catalogue_resolution_order(tmp_path, monkeypatch):
    from ravel import paths
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(paths, "native_build_root", lambda: tmp_path / "prefix")
    monkeypatch.delenv("RAVEL_ANALYSIS_CATALOG", raising=False)
    installed = ac.installed_catalog_path()
    installed.parent.mkdir(parents=True)
    installed.write_text("{}")
    assert ac.catalog_path() == installed
    cached = tmp_path / "cache/ravel/analysis-catalog.json"
    cached.parent.mkdir(parents=True)
    cached.write_text("{}")
    assert ac.catalog_path() == cached
    monkeypatch.setenv("RAVEL_ANALYSIS_CATALOG", str(tmp_path / "chosen.json"))
    assert ac.catalog_path() == tmp_path / "chosen.json"


@pytest.mark.parametrize("case,status", [("missing", "missing"), ("invalid", "unconfigured"),
                                          ("wrong", "version_mismatch"), ("valid", "ready")])
def test_catalogue_doctor_from_synthetic_git(tmp_path, case, status):
    # This helper arrives with the catalogue builder. It creates fictional local Git
    # checkouts with init/add/commit only; it clones or fetches nothing.
    from synthetic_catalog import build
    _, catalog = build(tmp_path / "sources")
    d = make_doctor(tmp_path)
    path = ac.installed_catalog_path(d.prefix)
    expected = catalog["sources"]["rivet"]["revision"]
    if case != "missing":
        path.parent.mkdir(parents=True)
        if case == "invalid":
            catalog["entries"][0]["physics_validated_by_ravel"] = True
        if case == "wrong":
            expected = "a"*40
        path.write_text(json.dumps(catalog))
    check = dict(id="catalogue", kind="analysis_catalogue", rivet_ref=expected,
                 rebuild=["{HOST_PYTHON}", "-m", "ravel.workflow.analysis_catalog_build", "--rivet", str(tmp_path / "sources/rivet"),
                          "--rivet-ref", expected, "--simpleanalysis", str(tmp_path / "sources/simpleanalysis"),
                          "--simpleanalysis-ref", catalog["sources"]["simpleanalysis"]["revision"],
                          "--out", str(path), "--force"])
    assert d.evaluate_check(dict(id="catalogue"), check)["status"] == status


@pytest.mark.parametrize("messages,unchanged,loaded", [([], True, True), (["load::fault"], True, True), ([], False, True), ([], True, False)])
def test_feynrules_probe_uses_namespace_shim(tmp_path, messages, unchanged, loaded):
    d = make_doctor(tmp_path)
    record = dict(mode="package_context_symbols_v1", message_free_load=True, load_messages=messages,
                  system_definitions_unchanged=unchanged, package_commutator_downvalues=2, package_matrix_symbol_downvalues=8)
    def fake_probe(argv, **kwargs):
        assert "providerNamespace" in argv[-1] and "systemBefore" in argv[-1]
        return 0, 'banner\nRAVEL-NAMESPACE:' + json.dumps(dict(provider_loaded=loaded, namespace_compatibility=record))
    d.run_probe = fake_probe
    result = d._wolfram_loads("fake-kernel", {"load": [{"name": "FeynRules", "root": "{TOOLS}/provider", "context": "FeynRules`"}]})
    assert result["status"] == ("ready" if not messages and unchanged and loaded else "unconfigured")


@pytest.mark.parametrize("name,version,status", [("claude", "2.1.100", "version_mismatch"),
    ("claude", "2.1.296", "ready"), ("claude", "2.2.0", "ready"), ("codex", "1.0", "ready"), (None, "", "missing")])
def test_agent_cli_check(tmp_path, name, version, status):
    if name:
        fake(tmp_path, name, f"echo '{version}'")
    d = make_doctor(tmp_path, which=lambda n: str(tmp_path / n) if n == name else None)
    result = d.evaluate_check(dict(id="research-host"), dict(id="agent", kind="agent_cli"))
    assert result["status"] == status
    if status == "version_mismatch":
        assert result["fix"] == "claude update"
    if status == "ready":
        assert result["transport_qualified"] is False
        assert f"ravel transport qualify {name}-cli-worker" in result["detail"]


@pytest.mark.parametrize("name", ["claude", "codex"])
@pytest.mark.parametrize("change,qualified", [(None, True), ("binary", False), ("declaration", False), ("probe", False), ("qualification", False)])
def test_agent_cli_stored_qualification(tmp_path, monkeypatch, name, change, qualified):
    from ravel.workflow import transport_registry as registry
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    path = tmp_path / name
    path.write_text("#!/bin/sh\necho 2.1.296\n")
    path.chmod(0o755)
    document = registry.load(name + "-cli-worker")
    probe = dict(schema_version=1, kind="transport-probe", transport_id=document["id"],
                 declaration_sha256=registry.declaration_sha256(document), cli_version="2.1.296",
                 help_sha256="a"*64, flags={f: "confirmed" for f in registry.template_flags(document)},
                 capabilities_confirmed={k: True for k in registry.BOOLEAN_CAPABILITIES}, unusable=[],
                 probed_utc="2026-01-01T00:00:00Z", executable_path=str(path),
                 executable_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), exit_status=0)
    receipt = {key: None for key in registry.QUALIFICATION_RECORD_KEYS}
    receipt.update(schema_version=1, kind="transport-qualification", transport_id=document["id"], status="live_qualified",
                   declaration_sha256=registry.declaration_sha256(document), probe_sha256=registry.digest(probe),
                   executable_sha256=probe["executable_sha256"], executable_path=str(path))
    if change == "binary":
        path.write_text("#!/bin/sh\necho changed\n")
    if change == "declaration":
        probe["declaration_sha256"] = "b"*64
    if change == "probe":
        probe["cli_version"] = "changed"
    if change == "qualification":
        receipt["status"] = "failed"
    registry.probe_path(document["id"]).parent.mkdir(parents=True)
    registry.probe_path(document["id"]).write_text(json.dumps(probe))
    registry.qualification_path(document["id"]).write_text(json.dumps(receipt))
    d = make_doctor(tmp_path, which=lambda n: str(path) if n == name else None)
    d.run_probe = lambda *a, **k: (0, "2.1.296")
    result = d.evaluate_check(dict(id="research-host"), dict(id="agent", kind="agent_cli"))
    assert result["status"] == "ready" and result["transport_qualified"] is qualified
    if not qualified:
        assert f"ravel transport qualify {document['id']}" in result["detail"]


def test_disk_numbers_agree(system):
    """The installer's preflight and the README read the manifest's figures; no doc hard-codes another."""
    _, run, tmp = system
    document, _ = mf.load(ROOT)
    targets = {"default": document["default"]["disk_gb"],
               **{name: row["disk_gb"] for name, row in document["profiles"].items()}}
    readme = (ROOT / "README.md").read_text()
    assert f"needs {targets['default']} GB of disk space" in readme
    text = (ROOT / "docs/installation.md").read_text()
    assert "66 GB" not in text and "110 GB" not in text
    for name, disk in targets.items():
        # A named facility profile needs its explicit software-view choice even for a preflight.
        args = ("--preflight-only", "--no-disk-check") + (() if name == "default" else ("--profile", name, "--lcg-view", "none"))
        result = run(*args, prefix=tmp / "p")
        assert result.returncode == 0, result.stderr
        assert f"about {disk} GB needed" in result.stdout


def test_unknown_profile_is_refused_before_any_install(system):
    _, run, tmp = system
    result = run("--preflight-only", "--profile", "no-such-target", prefix=tmp / "p")
    assert result.returncode == 2 and "unknown profile no-such-target" in result.stderr
    assert not (tmp / "p").exists()


def test_fractional_disk_figure_rounds_up_for_the_free_space_check(system):
    settings, run, tmp = system
    document, _ = mf.load(ROOT)
    disk = document["default"]["disk_gb"]
    need = int(disk) + (0 if float(disk).is_integer() else 1)
    settings["free_kb"] = str((need - 1) * 1024 * 1024)
    result = run("--preflight-only", prefix=tmp / "p")
    assert result.returncode == 4 and "not enough free disk space" in result.stderr
    settings["free_kb"] = str(need * 1024 * 1024)
    assert run("--preflight-only", prefix=tmp / "p").returncode == 0
