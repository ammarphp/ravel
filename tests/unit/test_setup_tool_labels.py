"""Tool install and labels: licences, dropped backends, pins, doctor labels, holds, refusal classes."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

import pytest

from ravel.setup import doctor, holds, host_config
from ravel.setup import manifest as mf
from ravel.workflow.backends import oci_local
from shipped_catalogue import shipped_groups

ROOT = Path(__file__).resolve().parents[2]
MANIFEST, CATALOG = mf.load(ROOT)
BYID = mf.by_id(MANIFEST)


def licences(group):
    return {row["component"]: row["spdx"] for row in BYID[group].get("licenses", [])}


@pytest.mark.parametrize("group", shipped_groups(["root-combine", "cosmology", "iris", "publication", "lhapdf-sets"]))
def test_licence_entries_exist_for_groups_that_had_none(group):
    assert licences(group)


def test_agentrivet_is_gpl_3_or_later_and_the_only_agent_source():
    assert licences("agent-sources") == {"AgentRivet": "GPL-3.0-or-later"}
    assert [s["id"] for s in BYID["agent-sources"]["steps"]] == ["agentrivet", "config"]
    assert [c["id"] for c in BYID["agent-sources"]["checks"]] == ["agentrivet"]
    # The retired backends' names are covered by the repository hygiene denylist
    # (tests/unit/test_repo_hygiene.py).


def test_dropped_backend_routes_refuse_with_a_plain_reason():
    from ravel.workflow import cosmology_backend as cb, cosmology_runtime as rt, research_tools as rtools
    for call in (lambda: cb.prepare({}, source_base="."), lambda: cb.read_results({}), lambda: rt.RuntimeBinding(),
                 lambda: rtools.backend_spec(".", {}, {}, {}, base_dir=".", graph_id="g", max_wall_seconds=1)):
        with pytest.raises(cb.BackendRetired, match="dropped from RAVEL"):
            call()


def test_one_heptapod_pin():
    commits = {s["commit"] for g in MANIFEST["groups"] for s in g["steps"] if "heptapod" in s.get("url", "")}
    assert len(commits) == 1
    assert not [s for g in MANIFEST["groups"] for s in g["steps"] if s["id"] == "heptapod-eda"]
    probe = next(c for c in BYID["wolfram"]["checks"] if c["id"] == "heptapod")["probe"]["expect"]
    assert probe in commits


def test_smodels_is_3_2_1_with_3_1_1_runnable_and_coverage_cites_the_database():
    steps = {s["id"]: s for s in BYID["smodels"]["steps"]}
    assert steps["database"]["url"].endswith("official321.pcl") and steps["database"]["size"] == 1165122724
    assert steps["install-311"]["requirements"][0] == "smodels==3.1.1"
    expects = {c["id"]: c["probe"]["expect"] for c in BYID["smodels"]["checks"] if "probe" in c}
    assert expects == {"smodels-version": "3.2.1", "smodels-311-version": "3.1.1"}
    config = json.loads(steps["config"]["content"])
    assert config["default"] == "3.2.1"
    assert all(v["database_version"] == k and v["database_doi"].startswith("10.5281/zenodo.")
               for k, v in config["versions"].items())
    assert "smodels==3.2.1" in (ROOT / "environment/python/requirements-smodels.txt").read_text()


def test_pdf_digests_are_verified_or_labelled_single_download():
    assert {s["digest_status"] for s in CATALOG["sets"]} == {"verified", "single-download"}
    assert "observed" not in json.dumps(CATALOG)


def test_new_groups_and_their_pins():
    ml = [s for s in BYID["ml"]["steps"] if s["kind"] == "pip"][0]
    assert [r.split("==")[0] for r in ml["requirements"]] == ["scikit-learn", "torch", "torch_geometric"]
    assert all("==" in r for r in ml["requirements"]) and "ml" in mf.profile_groups(MANIFEST)
    assert BYID["pdg"]["steps"][0]["sha256"] == json.loads(
        (ROOT / "src/ravel/data/reference/pdg/SOURCE.json").read_text())["origin"]["wheel_sha256"]


def test_jhugen_mela_recipe_refuses_until_pins_are_recorded():
    recipe = ROOT / "native/containers/jhugen-mela"
    text = (recipe / "Containerfile").read_text()
    base = json.loads((recipe / "base-image.json").read_text())
    digest = base["base"]["digest"]
    assert digest and digest.startswith("sha256:") and len(digest) == 71
    assert oci_local.containerfile_bases(text) == [f"registry.fedoraproject.org/fedora@{digest}"]
    with pytest.raises(ValueError, match="not pinned by digest"):
        oci_local.containerfile_bases(text.replace(digest, "sha256:RECORD-DIGEST-AT-FIRST-APPROVED-PULL"))
    for key in ("jhugen", "mela"):
        assert re.fullmatch(r"[0-9a-f]{40}", base[key]["commit"])
    for name in ("build-jhugen-mela.sh", "check-jhugen-mela.sh"):
        subprocess.run(["bash", "-n", str(recipe / name)], check=True)
    assert "refusing" in (recipe / "build-jhugen-mela.sh").read_text()


def test_font_cache_is_warmed_and_checked():
    assert "font-cache" in {s["id"] for s in BYID["publication"]["steps"]}
    assert "font-cache" in {c["id"] for c in BYID["publication"]["checks"]}


def test_site_libraries_are_pinned_or_labelled():
    surface = json.loads((ROOT / "src/ravel/data/agent_surface/surface.json").read_text())
    text = (ROOT / "requirements-site.txt").read_text()
    for name in ("coffea", "cabinetry", "vector", "boost-histogram", "pyarrow"):
        assert name in surface["python_packages"]
        assert re.search(rf"^{re.escape(name)}==", text, re.M) or \
            re.search(rf"^# {re.escape(name)}: provided by the site's LCG view, unpinned", text, re.M), name


def test_installer_never_calls_the_wolfram_agent_tools_deploy():
    text = "".join(p.read_text(encoding="utf-8") for base in ("src/ravel/setup", "scripts/setup", "native/setup")
                   for p in (ROOT / base).rglob("*") if p.is_file() and p.suffix in (".py", ".sh", ".json", ".in")
                   and p.name != "test_setup_tool_labels.py")
    assert "DeployAgentTools" not in text


# ------------------------------------------------------------------ doctor labels and holds
def no_native_tool(argv, env=None, timeout=15):
    """Test probe: never starts a process, so no real tool (Wolfram, podman, TeX, ...) runs in a test."""
    return 127, "not found (test fake)"


def make_doctor(tmp_path, manifest=None, environ=None, which=None, run_probe=None):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return doctor.Doctor(repo, tmp_path / "prefix", "macos-arm64", manifest or MANIFEST, CATALOG,
                         environ={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), **(environ or {})},
                         which=which or (lambda name: None), glob_paths=lambda pattern: [],
                         run_probe=run_probe or no_native_tool)


def test_doctor_tests_never_start_a_real_tool(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a doctor test started a real process: " + repr(args[:1]))
    monkeypatch.setattr(doctor.subprocess, "run", refuse)
    d = make_doctor(tmp_path)
    for platform in ("macos-arm64", "linux-x86_64"):
        d.platform = platform
        d.report([g["id"] for g in MANIFEST["groups"]])
    assert d.probes, "the full manifest has probe checks; they must reach the fake"


def test_doctor_json_labels_every_group(tmp_path):
    report = make_doctor(tmp_path).report([g["id"] for g in MANIFEST["groups"]])
    labels = {"ready", "not-ready", "owner-action", "remote", "unsupported"}
    quals = set(mf.QUALIFICATIONS)
    assert len(report["groups"]) == len(MANIFEST["groups"])
    for group in report["groups"]:
        assert group["label"] in labels and group["qualification"] in quals and group["qualification_basis"]
        if group["label"] == "not-ready":
            assert group["fix"], group["group"]
    assert {r["id"] for r in report["refusal_classes"]} >= {"SP-03", "SP-06-T8", "SP-06-T9", "SP-06-T10", "SP-06-T11"}
    json.dumps(report)


def test_every_manifest_group_records_a_qualification():
    assert all(g["qualification"]["status"] in mf.QUALIFICATIONS for g in MANIFEST["groups"])


def test_loop_requests_are_held_where_the_tree_does_not_declare_madloop():
    released = {**MANIFEST, "groups": [g for g in MANIFEST["groups"] if g["id"] != "madloop"]}
    hold = holds.loop_request_hold("generate p p > t t~ [QCD]", released)
    assert hold["status"] == "held" and hold["group"] == "madloop" and hold["request_classes"] == ["nlo-loop"]
    assert hold["qualification"] is None and "does not declare" in hold["reason"]
    assert holds.loop_request_hold("generate p p > e+ e- j", released) is None


def wolfram_manifest():
    check = next(c for c in BYID["wolfram"]["checks"] if c["kind"] == "wolfram")
    return {"schema_version": 2, "kind": "ravel-toolchain-manifest", "operations": [],
            "default": {"groups": ["wolfram"], "disk_gb": 0}, "profiles": {}, "incompatible_path_bindings": [],
            "groups": [{"id": "wolfram", "title": "W", "depends_on": [], "size_gb": 0, "minutes": 0, "steps": [],
                        "checks": [check], "qualification": {"status": "built-unqualified", "basis": "test"}}]}


class Kernel:
    def __init__(self, failing=()):
        self.failing, self.calls = set(failing), []

    def __call__(self, argv, env=None, timeout=15):
        self.calls.append(list(argv))
        code = argv[2]
        if code == "$VersionNumber":
            return 0, "15.0\n"
        if "RAVEL-NAMESPACE:" in code:
            # FeynRules loads through the provider namespace shim and reports a typed record.
            ok = "FeynRules" not in self.failing
            record = dict(mode="package_context_symbols_v1", message_free_load=True, load_messages=[],
                          system_definitions_unchanged=True, package_commutator_downvalues=2,
                          package_matrix_symbol_downvalues=8)
            return 0, "banner\nRAVEL-NAMESPACE:" + json.dumps(dict(provider_loaded=ok, namespace_compatibility=record))
        package = re.search(r'Needs\["(\w+)`"\]', code).group(1)
        return 0, "RAVEL-LOAD-FAIL\n" if package in self.failing else "banner\nRAVEL-LOAD-OK\n"


def test_wolfram_proves_each_package_loads_in_its_own_fresh_kernel(tmp_path):
    kernel = Kernel()
    d = make_doctor(tmp_path, wolfram_manifest(), which=lambda n: "/k/wolframscript", run_probe=kernel)
    row = d.report(["wolfram"])["groups"][0]["checks"][0]
    assert row["status"] == "ready" and row["loaded"] == ["FeynRules", "SARAH", "FeynCalc", "FeynArts"]
    loads = [c for c in kernel.calls if c[2] != "$VersionNumber"]
    assert len(loads) == 4 and all(c[1] == "-code" and "-activate" not in c for c in kernel.calls)
    assert all("DeployAgentTools" not in " ".join(c) for c in kernel.calls)


def test_wolfram_load_failure_is_not_ready_and_names_the_package(tmp_path):
    d = make_doctor(tmp_path, wolfram_manifest(), which=lambda n: "/k/wolframscript", run_probe=Kernel({"SARAH"}))
    group = d.report(["wolfram"])["groups"][0]
    row = group["checks"][0]
    assert row["status"] == "unconfigured" and row["load_failed"] == ["SARAH"] and group["label"] == "owner-action"
    assert "SARAH" in group["holds"][0]["reason"] and "fallbacks" in group["holds"][0]["reason"]


def test_missing_wolfram_kernel_is_a_hold_that_names_it(tmp_path):
    group = make_doctor(tmp_path, wolfram_manifest()).report(["wolfram"])["groups"][0]
    reason = group["holds"][0]["reason"]
    assert "wolframscript" in reason and "SymPy/mpmath" in reason and group["label"] == "owner-action"


def test_host_config_change_is_a_doctor_warning(tmp_path):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    config = home / ".codex/config.toml"
    config.write_text("model = 'a'\n")
    d = make_doctor(tmp_path)
    assert d.report(["python-host"])["warnings"] == []
    host_config.record(d.values["CONFIG"], home)
    assert d.report(["python-host"])["warnings"] == []
    config.write_text("model = 'b'\n")
    warning = d.report(["python-host"])["warnings"][0]
    assert ".codex/config.toml changed" in warning and "never edits it" in warning
    assert "model" not in json.dumps(json.loads((Path(d.values["CONFIG"]) / "host-config-digests.json").read_text()))
    host_config.record(d.values["CONFIG"], home, replace=True)
    assert d.report(["python-host"])["warnings"] == []


def test_diagram_consumers_do_not_install_the_orchestral_framework():
    requirements = [r for s in BYID["diagram-consumers"]["steps"] for r in s.get("requirements", [])]
    assert requirements and not [r for r in requirements if r.lower().startswith("orchestral")]
    assert "orchestral-ai" not in (ROOT / "native/setup/toolchain-manifest.json").read_text(encoding="utf-8")


def test_notice_credits_the_shipped_pdg_subset():
    source = json.loads((ROOT / "src/ravel/data/reference/pdg/SOURCE.json").read_text())
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Particle Data Group" in notice and "CC BY 4.0" in notice and source["edition"] in notice
    assert "src/ravel/data/reference/pdg" in notice


def test_refusal_classes_state_what_would_make_them_possible():
    rows = {r["id"]: r for r in MANIFEST["refusal_classes"]}
    assert rows["SP-03"]["refused_by"].startswith("src/ravel/physics/model_specific_spectrum.py")
    assert all(r["would_make_it_possible"] and r["why"] for r in rows.values())


def test_wolfram_namespace_load_failure_names_feynrules(tmp_path):
    d = make_doctor(tmp_path, wolfram_manifest(), which=lambda n: "/k/wolframscript", run_probe=Kernel({"FeynRules"}))
    row = d.report(["wolfram"])["groups"][0]["checks"][0]
    assert row["status"] == "unconfigured" and row["load_failed"] == ["FeynRules"]
