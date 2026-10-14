"""ravel doctor on synthetic prefixes: statuses, fixes, secrets, Wolfram and site checks."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from ravel.setup import doctor
from ravel.setup import manifest as mf

ROOT = Path(__file__).resolve().parents[2]
MANIFEST, CATALOG = mf.load(ROOT)


def tool(path: Path, output: str, code: int = 0) -> Path:
    """A fake executable that prints a fixed version banner."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\nexit {code}\n")
    path.chmod(0o755)
    return path


def small_manifest():
    groups = [
        {"id": "engine", "title": "Engine", "depends_on": [], "size_gb": 1, "minutes": 1, "steps": [],
         "checks": [
             {"id": "engine", "kind": "executable", "path": "{BIN}/engine",
              "probe": {"argv": ["{path}", "--version"], "regex": r"engine (\S+)", "expect": "2.9.27"}},
             {"id": "engine-data", "kind": "directory", "path": "{SHARE}/engine"},
             {"id": "make", "kind": "executable", "path": "{BIN}/make",
              "probe": {"argv": ["{path}", "--version"], "regex": r"GNU Make (\S+)", "expect": ">=4"}},
         ]},
        {"id": "kernel", "title": "Kernel", "depends_on": [], "size_gb": 0, "minutes": 0, "steps": [],
         "checks": [{"id": "licence-tool", "kind": "manual", "probe": {"argv": ["{BIN}/licence-tool"]},
                     "instruction": "Install the licensed tool yourself."}]},
        {"id": "site", "title": "Site", "depends_on": [], "size_gb": 0, "minutes": 0, "steps": [],
         "routes": {"default": "native", "macos-arm64": "remote"}, "manual": "Runs on the Linux site.",
         "checks": [{"id": "site-python", "kind": "executable", "path": "{BIN}/site-python"}]},
        {"id": "provider", "title": "Provider", "depends_on": [], "size_gb": 0, "minutes": 0, "steps": [],
         "checks": [{"id": "provider", "kind": "provider"}]},
    ]
    document = {"schema_version": 2, "kind": "ravel-toolchain-manifest", "groups": groups,
                "default": {"groups": [g["id"] for g in groups], "disk_gb": 1}, "profiles": {},
                "incompatible_path_bindings": [["engine", "make"]], "operations": []}
    return document


def make_doctor(tmp_path, platform="macos-arm64", environ=None, which=None, glob_paths=None, manifest=None):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    environ = {"PATH": "/usr/bin:/bin", **(environ or {})}
    return doctor.Doctor(repo, tmp_path / "prefix", platform, manifest or small_manifest(), CATALOG,
                         environ=environ, which=which or (lambda name: None),
                         glob_paths=glob_paths or (lambda pattern: []))


def statuses(report):
    return {c["id"]: c["status"] for g in report["groups"] for c in g["checks"]}


def test_ready_missing_mismatch_manual_remote_and_unconfigured(tmp_path):
    bin_dir = tmp_path / "prefix/bin"
    tool(bin_dir / "engine", "engine 2.9.26")
    tool(bin_dir / "make", "GNU Make 4.4.1")
    (tmp_path / "prefix/share/engine").mkdir(parents=True)
    d = make_doctor(tmp_path)
    report = d.report(["engine", "kernel", "site", "provider"])
    assert statuses(report) == {"engine": "version_mismatch", "engine-data": "ready", "make": "ready",
                                "licence-tool": "manual_required", "site-python": "remote_route",
                                "provider": "unconfigured"}
    engine = report["groups"][0]["checks"][0]
    assert engine["found"] == "2.9.26" and engine["expected"] == "2.9.27"
    assert engine["fix"] == f"bash scripts/setup/install.sh --only engine --prefix {tmp_path / 'prefix'}"
    assert report["groups"][1]["checks"][0]["fix"] == "Install the licensed tool yourself."
    assert report["groups"][2]["status"] == "remote_route"
    assert report["status"] == "version_mismatch" and report["ready"] is False
    tool(bin_dir / "engine", "engine 2.9.27")
    tool(bin_dir / "licence-tool", "ok")
    assert statuses(make_doctor(tmp_path).report(["engine", "kernel"]))["engine"] == "ready"
    (bin_dir / "engine").unlink()
    assert statuses(make_doctor(tmp_path).report(["engine"]))["engine"] == "missing"


def test_linux_runs_the_site_checks_that_are_remote_on_macos(tmp_path):
    d = make_doctor(tmp_path, platform="linux-x86_64")
    assert statuses(d.report(["site"]))["site-python"] == "missing"


def test_probes_never_use_a_shell_or_the_network(tmp_path):
    tool(tmp_path / "prefix/bin/engine", "engine 2.9.27")
    calls = []

    def fake_probe(argv, *, env=None, timeout=15):
        calls.append((argv, timeout, env))
        return 0, "engine 2.9.27"

    d = doctor.Doctor(tmp_path, tmp_path / "prefix", "macos-arm64", small_manifest(), CATALOG,
                      environ={"PATH": "/usr/bin"}, run_probe=fake_probe, which=lambda n: None)
    d.report(["engine"])
    for argv, timeout, env in calls:
        assert isinstance(argv, list) and timeout <= 60
        assert argv[0] not in ("sh", "bash", "zsh", "curl", "wget")
        assert env["PATH"].startswith(str(tmp_path / "prefix/bin"))


def test_provider_presence_is_checked_without_reading_the_secret(tmp_path):
    config = tmp_path / "host.json"
    config.write_text(json.dumps({"type": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"}))
    env = {"RAVEL_HOST_CONFIG": str(config)}
    missing = make_doctor(tmp_path, environ=env).report(["provider"])
    check = missing["groups"][0]["checks"][0]
    assert check["status"] == "unconfigured" and "ANTHROPIC_API_KEY" in check["detail"]
    assert "prepare-external" in check["detail"]
    present = make_doctor(tmp_path, environ={**env, "ANTHROPIC_API_KEY": "sk-very-secret-value"}).report(["provider"])
    assert statuses(present)["provider"] == "ready"
    assert "sk-very-secret-value" not in json.dumps(present)
    config.write_text(json.dumps({"type": "command", "command": ["claude", "-p"]}))
    assert statuses(make_doctor(tmp_path, environ=env).report(["provider"]))["provider"] == "ready"


def wolfram_manifest():
    return {"schema_version": 2, "kind": "ravel-toolchain-manifest", "operations": [],
            "default": {"groups": ["wolfram"], "disk_gb": 0}, "profiles": {}, "incompatible_path_bindings": [],
            "groups": [{"id": "wolfram", "title": "W", "depends_on": [], "size_gb": 0, "minutes": 0, "steps": [],
                        "checks": [{"id": "wolfram-kernel", "kind": "wolfram", "expect": "14.3|15.0"}]}]}


@pytest.mark.parametrize("output, code, expected", [
    ("15.", 0, "ready"), ("14.3", 0, "ready"), ("13.2", 0, "version_mismatch"),
    ("The product has not been activated", 1, "unconfigured"),
])
def test_wolfram_status_is_read_without_activation(tmp_path, output, code, expected):
    ws = tool(tmp_path / "wolfram/wolframscript", output, code)
    d = make_doctor(tmp_path, which={"wolframscript": str(ws)}.get, manifest=wolfram_manifest())
    report = d.report(["wolfram"])
    assert statuses(report)["wolfram-kernel"] == expected
    assert d.probes and all("-activate" not in argv for argv in d.probes)
    assert d.probes[0][1:] == ["-code", "$VersionNumber"]


def test_absent_wolfram_kernel_is_a_manual_prerequisite(tmp_path):
    report = make_doctor(tmp_path, manifest=wolfram_manifest()).report(["wolfram"])
    check = report["groups"][0]["checks"][0]
    assert check["status"] == "manual_required" and "wolframscript -activate" in check["detail"]


def test_wolfram_found_in_the_applications_folder(tmp_path):
    ws = tool(tmp_path / "Wolfram.app/Contents/MacOS/wolframscript", "15.")
    d = make_doctor(tmp_path, manifest=wolfram_manifest(),
                    glob_paths=lambda p: [str(ws)] if p.startswith("/Applications/Wolfram") else [])
    assert statuses(d.report(["wolfram"]))["wolfram-kernel"] == "ready"


def test_incompatible_bindings_are_a_conflict(tmp_path):
    shared = tool(tmp_path / "prefix/bin/engine", "engine 2.9.27 GNU Make 4.4")
    (tmp_path / "prefix/bin/make").symlink_to(shared)
    manifest = small_manifest()
    manifest["groups"][0]["checks"][2]["probe"]["regex"] = r"GNU Make (\S+)"
    report = make_doctor(tmp_path, manifest=manifest).report(["engine"])
    assert report["status"] == "conflict" and "same file" in report["conflicts"][0]


def test_container_image_check_uses_the_engine_without_starting_machines(tmp_path):
    engine = tool(tmp_path / "engine", "", 1)
    manifest = {"schema_version": 2, "kind": "ravel-toolchain-manifest", "operations": [],
                "incompatible_path_bindings": [], "default": {"groups": ["img"], "disk_gb": 0}, "profiles": {},
                "groups": [{"id": "img", "title": "I", "depends_on": [], "size_gb": 0, "minutes": 0, "steps": [],
                            "checks": [{"id": "image", "kind": "container_image", "name": "x", "image": "reg/x",
                                        "digest": "sha256:" + "a" * 64}]}]}
    d = make_doctor(tmp_path, manifest=manifest, environ={"RAVEL_CONTAINER_ENGINE": str(engine)})
    assert statuses(d.report(["img"]))["image"] == "missing"
    assert d.probes == [[str(engine), "image", "exists", "reg/x@sha256:" + "a" * 64]]
    assert not any("start" in argv for argv in d.probes)
    tool(tmp_path / "engine", "", 0)
    assert statuses(make_doctor(tmp_path, manifest=manifest,
                                environ={"RAVEL_CONTAINER_ENGINE": str(engine)}).report(["img"]))["image"] == "ready"


def test_site_checks(tmp_path, monkeypatch):
    manifest = {"schema_version": 2, "kind": "ravel-toolchain-manifest", "operations": [],
                "incompatible_path_bindings": [], "default": {"groups": ["site"], "disk_gb": 0}, "profiles": {},
                "groups": [{"id": "site", "title": "S", "depends_on": [], "size_gb": 0, "minutes": 0, "steps": [],
                            "checks": [{"id": n, "kind": "site", "site": n, "instruction": "do " + n}
                                       for n in ("kerberos", "condor", "apptainer", "agent-cli", "servicex-config")]}]}
    monkeypatch.chdir(tmp_path)
    klist = tool(tmp_path / "bin/klist", "", 1)
    found = {"klist": str(klist), "apptainer": "/usr/bin/apptainer", "claude": "/home/runner/.local/bin/claude"}
    report = make_doctor(tmp_path, platform="linux-x86_64", manifest=manifest, which=found.get).report(["site"])
    result = statuses(report)
    assert result == {"kerberos": "unconfigured", "condor": "missing", "apptainer": "ready", "agent-cli": "ready",
                      "servicex-config": result["servicex-config"]}
    condor = report["groups"][0]["checks"][1]
    assert condor["fix"] == "do condor"


def test_version_matching_rules():
    assert doctor.version_matches("3.03.01", "3.3.1")
    assert doctor.version_matches("6.40/00", "6.40*") or doctor.version_matches("6.40.00", "6.40*")
    assert doctor.version_matches("4.4.1", ">=4") and not doctor.version_matches("3.81", ">=4")
    assert doctor.version_matches("26.5.3", "26.5.*") and not doctor.version_matches("26.3.2", "26.5.*")
    assert doctor.version_matches("15.0", "14.3|15.0") and not doctor.version_matches("2.9.26", "2.9.27")


def test_real_manifest_report_on_an_empty_prefix_names_a_fix_for_everything(tmp_path):
    d = doctor.Doctor(ROOT, tmp_path / "empty", "linux-x86_64", MANIFEST, CATALOG,
                      environ={"PATH": "/usr/bin:/bin"}, which=lambda n: None, glob_paths=lambda p: [],
                      run_probe=lambda argv, env=None, timeout=15: (127, "not found"))
    report = d.report(mf.profile_groups(MANIFEST))
    assert report["ready"] is False
    for group in report["groups"]:
        for check in group["checks"]:
            if check["status"] not in ("ready", "remote_route"):
                assert check.get("fix"), (group["group"], check["id"])
    json.dumps(report)


def test_cli_json_and_strict_exit_codes(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_NATIVE_BUILD", str(tmp_path / "prefix"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = doctor.main(["--group", "cosmology", "--json", "--strict"], repo=ROOT,
                           run_probe=lambda argv, env=None, timeout=15: (0, "1.6.5 3.4.1.0 3.6.2"))
    report = json.loads(out.getvalue())
    assert report["kind"] == "ravel-doctor-report" and report["groups"][0]["group"] == "cosmology"
    assert code == (0 if report["ready"] else 1)
    with contextlib.redirect_stdout(io.StringIO()):
        assert doctor.main(["--group", "lhapdf-sets", "--strict"], repo=ROOT) == 1
        assert doctor.main(["--group", "lhapdf-sets"], repo=ROOT) == 1
    with contextlib.redirect_stderr(io.StringIO()):
        assert doctor.main(["--group", "no-such-group"], repo=ROOT) == 2


def test_ravel_cli_dispatches_doctor(monkeypatch, tmp_path):
    from ravel import cli
    assert cli.FOCUSED_COMMANDS["doctor"][0] == "setup.doctor"
    monkeypatch.setenv("RAVEL_NATIVE_BUILD", str(tmp_path / "prefix"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["doctor", "--group", "lhapdf-sets"]) == 1
    assert "lhapdf-sets" in out.getvalue() and "fix: bash scripts/setup/install.sh --only lhapdf-sets" in out.getvalue()


def test_profile_help_lists_every_manifest_profile():
    names = set(MANIFEST["profiles"])
    help_text = doctor.parser().format_help()
    for name in names:
        assert name in help_text, name


def test_wolfram_load_check_sets_the_directory_symbol_a_package_declares(tmp_path):
    manifest = wolfram_manifest()
    manifest["groups"][0]["checks"][0]["load"] = [
        {"name": "Pkg", "root": "{TOOLS}/pkg", "context": "Pkg`", "directory_symbol": "PkgPath"}]
    ws = tool(tmp_path / "wolfram/wolframscript", "15.\nRAVEL-LOAD-OK", 0)
    d = make_doctor(tmp_path, which={"wolframscript": str(ws)}.get, manifest=manifest)
    assert statuses(d.report(["wolfram"]))["wolfram-kernel"] == "ready"
    code = d.probes[-1][2]
    assert code.startswith('$PkgPath = "') and code.index("$PkgPath") < code.index('Needs["Pkg`"]')


def test_agent_command_line_host_is_ready_only_with_an_installed_agent(tmp_path):
    """The shipped agent command-line host configuration is a provider configuration: ready when the
    agent it names is installed, with no session started and no login read."""
    shipped = ROOT / "src/ravel/data/transports/hosts/agent-cli.json"
    assert json.loads(shipped.read_text())["type"] == "agent-cli"
    env = {"RAVEL_HOST_CONFIG": str(shipped)}
    absent = make_doctor(tmp_path, environ=env).report(["provider"])["groups"][0]["checks"][0]
    assert absent["status"] == "unconfigured" and "none is on PATH" in absent["detail"]
    assert (ROOT / doctor.AGENT_CLI_HOST) == shipped
    unset = make_doctor(tmp_path).report(["provider"])["groups"][0]["checks"][0]
    assert unset["status"] == "unconfigured" and doctor.AGENT_CLI_HOST in unset["detail"]
    d = make_doctor(tmp_path, environ=env, which={"codex": "/opt/bin/codex"}.get)
    present = d.report(["provider"])["groups"][0]["checks"][0]
    assert present["status"] == "ready" and "codex" in present["detail"]
    assert d.probes == [], "presence only: nothing is run"
    config = tmp_path / "host.json"
    config.write_text(json.dumps({"type": "agent-cli", "agent": "claude"}))
    env = {"RAVEL_HOST_CONFIG": str(config)}
    other = make_doctor(tmp_path, environ=env, which={"codex": "/opt/bin/codex"}.get)
    assert statuses(other.report(["provider"]))["provider"] == "unconfigured"
    named = make_doctor(tmp_path, environ=env, which={"claude": "/opt/bin/claude"}.get)
    assert statuses(named.report(["provider"]))["provider"] == "ready"
    config.write_text(json.dumps({"type": "agent-cli", "agent": "no-such-agent"}))
    assert statuses(make_doctor(tmp_path, environ=env, which={"claude": "/opt/bin/claude"}.get)
                    .report(["provider"]))["provider"] == "unconfigured"


def test_site_groups_carry_the_procedure_a_tester_runs_and_the_doctor_prints_it(tmp_path):
    """Only the two Linux-facility groups are qualified by testers; the doctor prints the same one-line
    procedure the manifest records, on the Mac (remote) and on the site."""
    byid = mf.by_id(MANIFEST)
    testers = {g["id"] for g in MANIFEST["groups"] if g["qualification"]["status"] == "tester-qualification"}
    assert testers == {"site-root-wms", "site-access"} == set(doctor.TESTER_PROCEDURES)
    source = Path(doctor.__file__).read_text()
    for gid in sorted(testers):
        procedure = byid[gid]["qualification"]["procedure"]
        assert procedure == doctor.TESTER_PROCEDURES[gid] and procedure in source
        assert f"ravel doctor --group {gid}" in procedure and "exits with status 0" in procedure
        assert all(check["id"] in procedure for check in byid[gid]["checks"])
        for platform in ("macos-arm64", "linux-x86_64"):
            d = doctor.Doctor(ROOT, tmp_path / "prefix", platform, MANIFEST, CATALOG, environ={"PATH": "/usr/bin:/bin"},
                              which=lambda n: None, glob_paths=lambda p: [],
                              run_probe=lambda argv, env=None, timeout=15: (127, "not found"))
            report = d.report([gid])
            assert report["groups"][0]["tester_procedure"] == procedure
            assert procedure in doctor.format_report(report)
    ordinary = doctor.Doctor(ROOT, tmp_path / "prefix", "macos-arm64", MANIFEST, CATALOG, environ={"PATH": "/usr/bin:/bin"},
                             which=lambda n: None, glob_paths=lambda p: [],
                             run_probe=lambda argv, env=None, timeout=15: (127, "not found")).report(["cosmology"])
    assert "tester_procedure" not in ordinary["groups"][0]
