"""Installer dry run and per-profile doctor coverage: every action listed, nothing touched, no group missing."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from ravel.setup import doctor, installer
from ravel.setup import manifest as mf
from test_setup_engine import make, world  # noqa: F401  (fixture and helper)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST, CATALOG = mf.load(ROOT)
PROFILES = (None, "site")
LABELS = {"ready", "not-ready", "owner-action", "remote", "unsupported"}


def tree(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob("*")) if path.exists() else None


def test_dry_run_lists_every_action_and_touches_nothing(world):  # noqa: F811
    tool, opener = make(world)
    before = tree(world["tmp"])
    plan = tool.dry_run()
    assert plan["mode"] == "dry-run" and plan["prefix"] == str(world["prefix"])
    steps = [(g["group"], s["id"]) for g in tool.plan()["groups"] for s in g["steps"]]
    assert [(a["group"], a["step"]) for a in plan["actions"]] == steps
    assert all({"kind", "what", "network", "writes"} <= set(a) for a in plan["actions"])
    fetching = [a for a in plan["actions"] if a["network"] == "yes"]
    assert fetching and all(a["fetch"] for a in fetching)
    assert plan["network_fetches"] == sorted({u for a in fetching for u in a["fetch"]})
    assert plan["disk_gb"] == tool.plan()["disk_gb"] and "queue job" in plan["size_basis"]
    assert any(w.endswith("config/ravel-env.sh") for w in plan["fixed_writes"])
    assert tree(world["tmp"]) == before and not world["prefix"].exists()
    assert opener.requests == [] and tool.runner.calls == []


@pytest.mark.parametrize("profile", PROFILES)
def test_dry_run_covers_each_profile_of_the_real_manifest(tmp_path, profile):
    prefix = tmp_path / "prefix"
    tool = installer.Installer(ROOT, prefix, platform_key="macos-arm64", manifest=MANIFEST, catalog=CATALOG,
                               environ={"PATH": "/nonexistent", "HOME": str(tmp_path / "h")}, stream=io.StringIO(),
                               interactive=False)
    plan = tool.dry_run(profile)
    json.dumps(plan)
    assert [g["group"] for g in plan["groups"]] == mf.profile_groups(MANIFEST, profile, platform_key="macos-arm64")
    assert plan["profile"] == (profile or "default") and plan["actions"]
    for group in plan["groups"]:
        assert group["size_gb"] >= 0 and group["minutes"] >= 0
    assert not prefix.exists() and not (tmp_path / "h").exists()
    assert "Miniforge" in installer.format_dry_run(plan) or "miniforge" in installer.format_dry_run(plan)


def test_dry_run_cli_flag_prints_and_creates_nothing(tmp_path, capsys):
    prefix = tmp_path / "pfx"
    assert installer.main(["--dry-run", "--prefix", str(prefix), "--json"], repo=ROOT) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "dry-run" and plan["profile"] == "default"
    assert installer.main(["--dry-run", "--profile", "site", "--prefix", str(prefix)], repo=ROOT) == 0
    assert "network" in capsys.readouterr().out
    assert not prefix.exists()


def fake_doctor(tmp_path, platform="macos-arm64"):
    return doctor.Doctor(ROOT, tmp_path / "prefix", platform, MANIFEST, CATALOG,
                         environ={"PATH": str(tmp_path / "fakebin")}, which=lambda n: None,
                         glob_paths=lambda p: [], run_probe=lambda argv, env=None, timeout=15: (127, "not found"))


@pytest.mark.parametrize("profile", PROFILES)
def test_doctor_json_reports_every_group_of_a_profile_with_label_and_fix(tmp_path, profile):
    expected = mf.profile_groups(MANIFEST, profile, platform_key="macos-arm64")
    report = fake_doctor(tmp_path).report(expected, profile=profile)
    json.dumps(report)
    assert report["profile"] == profile and report["expected_groups"] == expected
    assert [g["group"] for g in report["groups"]] == expected
    for group in report["groups"]:
        assert group["label"] in LABELS, group
        assert group["qualification"]
        if group["label"] in ("not-ready", "owner-action"):
            assert group.get("fix"), group["group"]
    assert sum(report["summary"].values()) == len(expected)
    assert set(report["summary"]) <= LABELS


def test_doctor_cli_json_names_the_profile(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RAVEL_NATIVE_BUILD", str(tmp_path / "prefix"))
    doctor.main(["--json"], repo=ROOT,
                run_probe=lambda argv, env=None, timeout=15: (127, "not found"))
    report = json.loads(capsys.readouterr().out)
    assert report["profile"] == "default" and report["expected_groups"]
    assert len(report["groups"]) == len(report["expected_groups"])


@pytest.mark.parametrize("profile", PROFILES)
def test_docs_name_each_profile_with_the_command_that_prints_its_size(profile):
    # Disk and time come from the manifest through --dry-run (and the README's generated disk
    # region); the guide states no separate figure that could drift from them.
    text = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith(f"| `{profile or 'default'}`"))
    assert "--dry-run" in row and (profile is None or f"--profile {profile}" in row)
    assert "GB" not in row
