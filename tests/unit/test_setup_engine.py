"""Installer engine: ordering, idempotence, resume, quarantine, conflicts and the home sandbox."""
from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import tarfile
import zipfile

import pytest

from ravel.setup import fetch, installer, state, steps
from ravel.setup import manifest as mf
from setup_fakes import (COMMIT_A, COMMIT_B, FakeOpener, FakeRunner, pdf_set_tarball, sha256, snapshot,
                         synthetic_manifest, tarball)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "native/setup/wrappers", repo / "native/setup/wrappers")
    archive = tarball({"tool-1.0/README": b"tool\n", "tool-1.0/bin/run": b"#!/bin/sh\n"})
    manifest, catalog, payloads = synthetic_manifest(archive_bytes=archive, pdf_bytes=pdf_set_tarball("TestSet", 12345))
    mf.validate(manifest, catalog)
    return {"tmp": tmp_path, "home": home, "repo": repo, "prefix": tmp_path / "prefix", "manifest": manifest,
            "catalog": catalog, "payloads": payloads}


def make(world, runner=None, opener=None, **options):
    opener = opener or FakeOpener(world["payloads"])
    tool = installer.Installer(world["repo"], world["prefix"], platform_key="linux-x86_64", manifest=world["manifest"],
                               catalog=world["catalog"], runner=runner or FakeRunner(),
                               fetcher=fetch.Fetcher(world["prefix"] / "downloads", opener=opener,
                                                     offline=options.pop("offline", False)),
                               environ={"PATH": "/usr/bin:/bin", "HOME": str(world["home"]),
                                        "RAVEL_CONTAINER_ENGINE": "podman", "PYTHONPATH": "/leak",
                                        "CONDA_PREFIX": "/leak"},
                               stream=io.StringIO(), accept_licenses=True, interactive=False, jobs=2, **options)
    return tool, opener


def test_steps_run_in_dependency_order_for_a_profile(world):
    runner = FakeRunner()
    tool, _ = make(world, runner)
    result = tool.run()
    assert result["status"] == "complete", result
    assert list(result["groups"]) == ["base", "data", "build"]
    kinds = [Path(c[0]).name + ":" + c[1] for c in runner.calls]
    assert kinds.index("conda:create") < kinds.index("git:clone") < kinds.index("make-outputs:" + str(world["prefix"] / "bin/tool"))
    assert (world["prefix"] / "tools/tool/README").read_text() == "tool\n"
    assert (world["prefix"] / "share/LHAPDF/TestSet/TestSet.info").is_file()
    # PDF sets are hard-linked into the environment, so tools that check ownership accept them.
    linked = world["prefix"] / "tools/miniforge3/envs/tools/share/LHAPDF/TestSet/TestSet.info"
    assert linked.is_file() and not linked.is_symlink()
    assert os.stat(linked).st_ino == os.stat(world["prefix"] / "share/LHAPDF/TestSet/TestSet.info").st_ino
    assert "nb_core = 2" in (world["prefix"] / "tools/repo/options.txt").read_text()
    receipt = (world["prefix"] / "receipts/base.json").read_text()
    assert COMMIT_A in receipt and "GPL-3.0-or-later" in receipt


def test_profile_selection_includes_dependencies_only(world):
    tool, _ = make(world)
    assert tool.groups(only=["data"]) == ["base", "data"]
    assert tool.groups("site") == ["base"]
    assert tool.groups(skip=["build"]) == ["base", "data"]
    with pytest.raises(mf.ManifestError, match="unknown profile"):
        tool.groups("nonexistent")


def test_second_run_skips_everything_without_network_or_commands(world):
    tool, opener = make(world)
    assert tool.run()["status"] == "complete"
    runner = FakeRunner(images=tool.runner.images)
    again, opener2 = make(world, runner, offline=True)
    output = again.stream
    result = again.run()
    assert result["status"] == "complete"
    assert runner.calls == [] and opener2.requests == []
    assert output.getvalue().count("(verified)") == sum(len(g["steps"]) for g in world["manifest"]["groups"])


def test_resume_after_injected_failure_restarts_at_the_failed_step(world):
    failing = FakeRunner(fail=lambda argv: Path(argv[0]).name == "make-outputs")
    tool, _ = make(world, failing)
    result = tool.run()
    assert result["status"] == "incomplete" and result["failed"][0]["group"] == "build"
    recorded = state.InstallState(world["prefix"]).get("build/compile")
    assert recorded["status"] == "failed" and Path(recorded["log"]).is_file()
    assert "build/wrapper" not in state.InstallState(world["prefix"]).data["steps"]
    fixed = FakeRunner()
    resumed, opener = make(world, fixed)
    result = resumed.run()
    assert result["status"] == "complete"
    names = [Path(c[0]).name for c in fixed.calls]
    assert "conda" not in names and "git" not in names and opener.requests == []
    assert names[0] == "make-outputs"


def test_digest_mismatch_quarantines_and_blocks_dependents(world):
    payloads = dict(world["payloads"])
    payloads["https://example.org/tool.tar.gz"] = b"tampered" * 10
    tool, _ = make(world, opener=FakeOpener(payloads))
    result = tool.run()
    assert result["status"] == "incomplete" and result["failed"][0]["status"] == "digest_mismatch"
    quarantined = list((world["prefix"] / "downloads/quarantine").iterdir())
    assert len(quarantined) == 1 and quarantined[0].read_bytes() == b"tampered" * 10
    assert not (world["prefix"] / "tools/tool").exists()
    assert result["groups"]["data"]["reason"] == "waits for base"


def test_existing_checkout_at_another_commit_is_a_conflict_and_untouched(world):
    repo = world["prefix"] / "tools/repo"
    repo.mkdir(parents=True)
    (repo / ".fakehead").write_text(COMMIT_B)
    (repo / "keep.txt").write_text("mine")
    tool, _ = make(world)
    result = tool.run()
    assert result["status"] == "incomplete" and "left untouched" in result["groups"]["base"]["error"]
    assert (repo / "keep.txt").read_text() == "mine" and (repo / ".fakehead").read_text() == COMMIT_B
    adopt, _ = make(world, adopt=True)
    assert adopt.run()["status"] == "complete"


def test_foreign_environment_is_not_replaced_but_our_failed_one_is_set_aside(world):
    env = world["prefix"] / "tools/miniforge3/envs/tools"
    (env / "conda-meta").mkdir(parents=True)
    tool, _ = make(world)
    assert tool.run()["failed"][0]["status"] == "conflict"
    marker = world["prefix"] / "state/owned/conda-tools.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}")
    again, _ = make(world)
    assert again.run()["status"] == "complete"
    assert any((world["prefix"] / "trash").iterdir())


def test_home_sandbox_only_prefix_changes(world, tmp_path):
    (world["home"] / ".zshrc").write_text("# user shell\n")
    before = snapshot(tmp_path)
    runner = FakeRunner()
    tool, _ = make(world, runner)
    assert tool.run()["status"] == "complete"
    after = snapshot(tmp_path)
    changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    outside = sorted(p for p in changed if not p.startswith("prefix"))
    assert outside == []
    for env in runner.envs:
        assert env["CONDA_PKGS_DIRS"].startswith(str(world["prefix"]))
        assert env["PIP_CACHE_DIR"].startswith(str(world["prefix"]))
        assert env["XDG_CACHE_HOME"].startswith(str(world["prefix"]))
        assert env["CONDA_REGISTER_ENVS"] == "false"
        assert "PYTHONPATH" not in env and "CONDA_PREFIX" not in env


def test_lock_prevents_two_installers(world):
    tool, _ = make(world)
    with state.install_lock(world["prefix"]):
        with pytest.raises(state.LockedError):
            tool.run()


def test_licences_must_be_accepted_before_anything_runs(world):
    runner = FakeRunner()
    tool, _ = make(world, runner)
    tool.accept_licenses = False
    result = tool.run()
    assert result["status"] == "licences_not_accepted" and runner.calls == []
    assert "GPL-3.0-or-later" in tool.stream.getvalue()


def test_manual_prerequisite_defers_group_and_its_dependants(world):
    world["manifest"]["groups"][1]["steps"].insert(0, {
        "id": "kernel", "kind": "manual", "probe": {"argv": ["probe-missing"]},
        "instruction": "Install the licensed kernel yourself."})
    tool, _ = make(world)
    result = tool.run()
    assert result["status"] == "complete_with_deferred"
    assert result["groups"]["base"]["status"] == "done"
    assert result["groups"]["data"]["status"] == "deferred"
    assert result["groups"]["build"]["status"] == "deferred"
    assert "licensed kernel" in tool.stream.getvalue()


def test_plan_lists_steps_and_changes_nothing(world):
    tool, opener = make(world)
    plan = tool.plan()
    assert [g["group"] for g in plan["groups"]] == ["base", "data", "build"]
    step = plan["groups"][0]["steps"][1]
    assert step["commit"] == COMMIT_A and step["state"] == "pending"
    assert not world["prefix"].exists() and opener.requests == []
    assert "TestSet" in installer.format_plan(plan)


def test_pdf_set_with_wrong_index_is_refused(world):
    bad = pdf_set_tarball("TestSet", 999)
    world["catalog"]["sets"][0].update(size=len(bad), sha256=sha256(bad))
    world["payloads"]["https://pdf.example.org/TestSet.tar.gz"] = bad
    tool, _ = make(world)
    result = tool.run()
    assert result["status"] == "incomplete" and "LHAID 12345" in result["groups"]["data"]["error"]
    assert not (world["prefix"] / "share/LHAPDF/TestSet").exists()


def test_env_file_is_written_but_never_sourced_automatically(world):
    tool, _ = make(world)
    tool.run("site")
    text = (world["prefix"] / "config/ravel-env.sh").read_text()
    assert f"RAVEL_NATIVE_BUILD={world['prefix']}" in text and "LHAPDF_DATA_PATH" not in text
    assert not (world["home"] / ".zshrc").exists() and not (world["home"] / ".bashrc").exists()


# ------------------------------------------------------------------ prefix resolution

def test_prefix_resolution_order(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert installer.resolve_prefix(repo, None, {}) == repo / "native/build"
    (repo / "stages/01-event-generation/build").mkdir(parents=True)
    assert installer.resolve_prefix(repo, None, {}) == repo / "stages/01-event-generation/build"
    (repo / ".ravel").mkdir()
    (repo / ".ravel/native-prefix").write_text(str(tmp_path / "pointed") + "\n")
    assert installer.resolve_prefix(repo, None, {}) == tmp_path / "pointed"
    assert installer.resolve_prefix(repo, None, {"RAVEL_NATIVE_BUILD": str(tmp_path / "env")}) == tmp_path / "env"
    assert installer.resolve_prefix(repo, str(tmp_path / "flag"), {"RAVEL_NATIVE_BUILD": "x"}) == tmp_path / "flag"
    with pytest.raises(mf.ManifestError, match="whitespace"):
        installer.resolve_prefix(repo, str(tmp_path / "has space"), {})


def test_pointer_written_only_for_a_non_default_prefix(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert installer.write_pointer(repo, repo / "native/build") is None
    pointer = installer.write_pointer(repo, tmp_path / "elsewhere")
    assert pointer.read_text().strip() == str(tmp_path / "elsewhere")


def test_container_engine_choice(tmp_path):
    assert installer.container_engine(tmp_path, "macos-arm64", {}) == str(tmp_path / "bin/ravel-podman")
    assert installer.container_engine(tmp_path, "linux-x86_64", {"RAVEL_CONTAINER_ENGINE": "/x/docker"}) == "/x/docker"
    found = {"apptainer": "/usr/bin/apptainer"}
    assert installer.container_engine(tmp_path, "linux-x86_64", {}, which=found.get) == "/usr/bin/apptainer"


# ------------------------------------------------------------------ downloads and archives

def test_fetch_uses_cache_and_offline_mode(tmp_path):
    data = b"payload"
    opener = FakeOpener({"https://x.org/f": data})
    fetcher = fetch.Fetcher(tmp_path / "cache", opener=opener)
    pin = {"sha256": sha256(data), "size": len(data)}
    first = fetcher.fetch("https://x.org/f", pin)
    assert first == tmp_path / "cache/sha256" / pin["sha256"] and first.read_bytes() == data
    offline = fetch.Fetcher(tmp_path / "cache", opener=FakeOpener({}), offline=True)
    assert offline.fetch("https://x.org/f", pin) == first
    with pytest.raises(fetch.FetchError, match="offline"):
        offline.fetch("https://x.org/g", {"sha256": "0" * 64})
    with pytest.raises(fetch.FetchError, match="https"):
        fetch.Fetcher(tmp_path / "c2", opener=opener).fetch("http://x.org/f", pin)


def test_fetch_accepts_upstream_md5_and_refuses_blocked_pins(tmp_path):
    import hashlib
    data = b"database"
    fetcher = fetch.Fetcher(tmp_path, opener=FakeOpener({"https://z.org/db": data}))
    path = fetcher.fetch("https://z.org/db", {"md5": hashlib.md5(data).hexdigest(), "size": len(data)})
    assert path.read_bytes() == data
    with pytest.raises(fetch.FetchError, match="no verified pin"):
        fetcher.fetch("https://z.org/db", {"blocked_reason": "upstream publishes no checksum"})


def test_size_mismatch_is_quarantined(tmp_path):
    data = b"x" * 100
    fetcher = fetch.Fetcher(tmp_path, opener=FakeOpener({"https://x.org/f": data}))
    with pytest.raises(fetch.DigestMismatch):
        fetcher.fetch("https://x.org/f", {"sha256": sha256(data), "size": 50})
    assert len(list((tmp_path / "quarantine").iterdir())) == 1


@pytest.mark.parametrize("name", ["../escape.txt", "/abs/path.txt", "ok/../../escape.txt"])
def test_tar_members_escaping_the_destination_are_refused(tmp_path, name):
    archive = tmp_path / "bad.tar.gz"
    archive.write_bytes(tarball({name: b"x"}))
    with pytest.raises(fetch.UnsafeArchive):
        fetch.safe_extract(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists() and not (tmp_path / "escape.txt").exists()


def test_tar_symlink_escape_and_devices_are_refused(tmp_path):
    link = tarfile.TarInfo("pkg/link")
    link.type, link.linkname = tarfile.SYMTYPE, "../../etc/passwd"
    archive = tmp_path / "link.tar.gz"
    archive.write_bytes(tarball({"pkg/a": b"a"}, extra=[link]))
    with pytest.raises(fetch.UnsafeArchive):
        fetch.safe_extract(archive, tmp_path / "out")
    device = tarfile.TarInfo("pkg/dev")
    device.type = tarfile.CHRTYPE
    archive.write_bytes(tarball({"pkg/a": b"a"}, extra=[device]))
    with pytest.raises(fetch.UnsafeArchive):
        fetch.safe_extract(archive, tmp_path / "out2")


def test_internal_symlink_and_zip_extraction(tmp_path):
    link = tarfile.TarInfo("pkg/lib/alias")
    link.type, link.linkname = tarfile.SYMTYPE, "real"
    archive = tmp_path / "ok.tar.gz"
    archive.write_bytes(tarball({"pkg/lib/real": b"r"}, extra=[link]))
    out = fetch.safe_extract(archive, tmp_path / "out", strip=1)
    assert (out / "lib/alias").read_text() == "r"
    bundle = tmp_path / "b.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        info = zipfile.ZipInfo("podman-5/usr/bin/podman")
        info.external_attr = 0o755 << 16
        z.writestr(info, "#!/bin/sh\n")
    out = fetch.safe_extract(bundle, tmp_path / "zip", strip=1)
    assert os.access(out / "usr/bin/podman", os.X_OK)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../evil", "x")
    with pytest.raises(fetch.UnsafeArchive):
        fetch.safe_extract(evil, tmp_path / "zip2")


# ------------------------------------------------------------------ wrappers

def test_container_wrapper_passes_arguments_unchanged(tmp_path):
    engine = tmp_path / "fake-engine"
    engine.write_text("#!/usr/bin/env bash\nfor a in \"$@\"; do printf '<%s>\\n' \"$a\"; done\n")
    engine.chmod(0o755)
    text = steps.render_template((ROOT / "native/setup/wrappers/container-run.sh.in").read_text(), {
        "ENGINE": str(engine), "IMAGE": "reg/img@sha256:" + "e" * 64, "PLATFORM": "linux/amd64",
        "COMMAND": "combine", "NAME": "combine", "LHAPDF": str(tmp_path / "pdf"), "PREFIX": str(tmp_path)})
    wrapper = tmp_path / "combine"
    wrapper.write_text(text)
    wrapper.chmod(0o755)
    import subprocess
    tricky = ["-M", "AsymptoticLimits", "card with space.txt", "--setParameters", "r=1,x='$HOME'", ""]
    out = subprocess.run([str(wrapper), *tricky], capture_output=True, text=True, cwd=tmp_path,
                         env={"PATH": "/usr/bin:/bin"}, check=True).stdout.splitlines()
    assert out[:3] == ["<run>", "<--rm>", "<--platform>"]
    assert "<--network>" in out and "<none>" in out
    tail = out[out.index("<combine>") + 1:]
    assert tail == [f"<{a}>" for a in tricky]


def test_wrapper_never_replaces_a_file_it_did_not_write(world):
    target = world["prefix"] / "bin/tool-wrapper"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho user script\n")
    tool, _ = make(world)
    result = tool.run()
    assert result["status"] == "incomplete" and result["failed"][0]["status"] == "conflict"
    assert "user script" in target.read_text()


def test_ownership_marker_states_ownership_and_every_template_carries_it():
    # The marker says who owns the file. It does not read as a statement of who or what authored it.
    assert steps.OWNED_MARK == "owned by the RAVEL installer"
    for template in sorted((ROOT / "native/setup/wrappers").glob("*.in")):
        lines = template.read_text().splitlines()
        assert "# " + steps.OWNED_MARK in lines, template.name
        assert not any("generated by" in line.lower() for line in lines), template.name


@pytest.mark.parametrize("mark", [steps.OWNED_MARK, *steps.LEGACY_OWNED_MARKS])
def test_wrapper_replaces_a_file_carrying_a_current_or_earlier_ownership_marker(world, mark):
    target = world["prefix"] / "bin/tool-wrapper"
    target.parent.mkdir(parents=True)
    target.write_text(f"#!/bin/sh\n# {mark}\necho stale wrapper\n")
    tool, _ = make(world)
    result = tool.run()
    assert result["status"] == "complete", result
    text = target.read_text()
    assert "stale wrapper" not in text and "# " + steps.OWNED_MARK in text.splitlines()
