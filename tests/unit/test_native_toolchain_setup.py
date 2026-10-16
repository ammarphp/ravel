"""The compatibility alias scripts/setup/native_toolchain.py and per-mode tool selection."""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

from ravel.setup import doctor
from ravel.setup import manifest as mf

ROOT = Path(__file__).absolute().parents[2]
HELPER = ROOT / "scripts/setup/native_toolchain.py"
SPEC = importlib.util.spec_from_file_location("ravel_native_setup_alias", HELPER)
alias = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alias)
MANIFEST, CATALOG = mf.load(ROOT)


def run_alias(argv, environ=None):
    with patch.dict(os.environ, environ or {}, clear=False), contextlib.redirect_stdout(io.StringIO()) as out:
        code = alias.main(argv)
    return code, json.loads(out.getvalue())


def test_complete_current_operation_population():
    module = ast.parse((ROOT / "src/ravel/workflow/science.py").read_text())
    modes = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "MODES" for t in n.targets))
    actual = [row["mode"] for row in MANIFEST["operations"]]
    assert len(actual) == len(set(actual))
    # Every science mode has its row, in the registry's order; a further row belongs to a mode that
    # the mode descriptors or an operation signature offer outside that registry.
    assert actual[:len(modes)] == list(modes)
    descriptors = json.loads((ROOT / "src/ravel/data/mode_descriptors.json").read_text())["modes"]
    signatures = json.loads((ROOT / "src/ravel/data/operation_signatures.json").read_text())["operations"]
    scoped = set(descriptors) | {s["implementation"]["mode"] for s in signatures.values()
                                 if s.get("implementation", {}).get("mode")}
    assert set(actual[len(modes):]) <= scoped - set(modes)
    groups = {g["id"] for g in MANIFEST["groups"]}
    assert all(set(row["groups"]) <= groups for row in MANIFEST["operations"])


def test_plan_lists_every_group_without_running_anything(tmp_path):
    code, plan = run_alias(["--plan", "--prefix", str(tmp_path / "p")])
    assert code == 0
    assert [g["group"] for g in plan["groups"]] == mf.profile_groups(MANIFEST)
    assert not (tmp_path / "p").exists()


def test_mode_selection_reaches_its_tools():
    assert doctor.select_groups(MANIFEST, mode="native-likelihood") == ["compiler-bootstrap", "python-host",
                                                                          "container-runtime", "root-combine"]
    analyze = set(doctor.select_groups(MANIFEST, mode="analyze"))
    assert {"rivet-shower", "ma5", "simpleanalysis", "restframes"} <= analyze
    assert doctor.select_groups(MANIFEST, mode="numerical-reference-check") == ["compiler-bootstrap", "python-host"]
    root_stream = doctor.select_groups(MANIFEST, mode="root-stream")
    assert root_stream == ["compiler-bootstrap", "python-host", "site-root-wms"]
    assert doctor.select_groups(MANIFEST, mode="a-mode-added-later") == ["compiler-bootstrap", "python-host"]


def _no_real_process(*args, **kwargs):
    raise FileNotFoundError("tests never start a real tool")


def test_check_is_the_doctor_and_strict_fails_when_tools_are_missing(tmp_path):
    with patch.dict(os.environ, {"OPENAI_API_KEY": "unread-secret"}), \
            patch.object(doctor.subprocess, "run", _no_real_process):
        code, report = run_alias(["--check", "--strict", "--prefix", str(tmp_path / "empty"),
                                  "--mode", "numerical-reference-check"])
    assert code == 1 and report["kind"] == "ravel-doctor-report"
    assert "unread-secret" not in json.dumps(report)
    assert {g["group"] for g in report["groups"]} == {"compiler-bootstrap", "python-host"}


def test_research_host_and_python_profiles_are_required():
    byid = mf.by_id(MANIFEST)
    assert MANIFEST["host_python"] == {"supported": ">=3.11,<3.13", "default": "3.12"}
    assert byid["research-host"]["checks"][0]["kind"] == "provider"
    host = byid["python-host"]["steps"][0]
    assert host["argv"][-1] == "{REPO}/scripts/setup/python_installation.py"
    assert "{REPO}/.venv-smodels/bin/python" in host["outputs"]
    assert "{REPO}/.venv-sfitter/bin/python" in host["outputs"]
    selected = mf.profile_groups(MANIFEST, platform_key="linux-x86_64")
    assert all(group["id"] in selected for group in MANIFEST["groups"] if group["id"] not in mf.unreleased_groups(MANIFEST))
