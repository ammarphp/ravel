"""The governed runtime: the seal, the identity gate's sealed kind, the entries' early admission, the
installer's seal and the doctor's controller admission.

Every runtime is sealed into this test's lock domain (the controller home resolves there). The
controls are inert: no network, model call, worker step or native science. The acceptance case
emulates a fresh user-writable installation in a new environment and drives the real entries in
child processes up to the run's first store records.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tomllib
import venv

import pytest

from ravel import cli
from ravel.controller.authority import operator
from ravel.controller.confine import identity
from ravel.setup import governed_runtime as gr

ROOT = Path(__file__).resolve().parents[2]
REQUEST = ("Estimate the yield of a fictional widget process in a toy model and report the value with its "
           "uncertainty.")
SEAL = identity.SEAL_COMMAND


class Reexec(BaseException):
    """Raised by the stand-in for ``os.execv``: the entry handed itself to a launcher.

    ``os.execv`` never returns, so no outcome wrapper may convert this into an exit code: like
    ``SystemExit`` it is outside ``Exception``."""


def _writable(path):
    """Restore the owner's write bits below ``path`` so the test's temporary tree can be removed."""
    path = Path(path)
    if not path.exists() or path.is_symlink():
        return
    for parent, directories, files in os.walk(path):
        os.chmod(parent, 0o700)
        for name in files:
            if not os.path.islink(os.path.join(parent, name)):
                os.chmod(os.path.join(parent, name), 0o600)


def _read_only(path):
    for parent, directories, files in os.walk(path, topdown=False):
        for name in files:
            os.chmod(os.path.join(parent, name), 0o444)
        for name in directories:
            os.chmod(os.path.join(parent, name), 0o555)
    os.chmod(path, 0o555)


@pytest.fixture(autouse=True)
def governed(tmp_path, monkeypatch):
    """No selector redirects code; host observations stay under this test's directory."""
    for name in identity.SELECTORS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    from ravel.workflow import agent_tripwire
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])
    root = identity.runtime_root()
    yield root
    _writable(root)
    _writable(tmp_path)


def tiny_package(base, body="VALUE = 1\n"):
    """A copied package tree: modules, a data file and a nested directory."""
    package = base / "ravel"
    (package / "data").mkdir(parents=True)
    (package / "__init__.py").write_text(body)
    (package / "cli.py").write_text("def main(argv=None):\n    return 0\n")
    (package / "data" / "note.json").write_text('{"fictional": true}\n')
    return package


def _rewrite(path, text):
    """Change a sealed file's bytes the way an unconfined process with the owner's uid could."""
    os.chmod(path.parent, 0o755)
    os.chmod(path, 0o644)
    path.write_text(text)
    os.chmod(path, 0o444)
    os.chmod(path.parent, 0o555)


# ---- the seal ---------------------------------------------------------------------------------

def test_seal_writes_a_read_only_runtime_with_its_record_launcher_and_current_pointer(tmp_path, governed):
    package = tiny_package(tmp_path / "copy")
    result = gr.seal(package=package)
    tree = "tree:" + identity._tree_digest(package)
    runtime = Path(result["runtime_dir"])
    assert governed == Path(os.path.realpath(operator.controller_home() / "runtime"))
    assert runtime == governed / tree[5:21] and result["runtime_id"] == tree[5:21] and result["reused"] is False
    assert sorted(os.listdir(runtime)) == ["SEAL.json", "bin", "site"]
    launcher = runtime / "bin" / "ravel"
    for path in (runtime, *runtime.rglob("*")):
        expected = 0o555 if path.is_dir() or path == launcher else 0o444
        assert stat.S_IMODE(os.lstat(path).st_mode) == expected, path
    sealed = runtime / "site" / "ravel"
    assert "tree:" + identity._tree_digest(sealed) == tree
    assert (sealed / "__pycache__" / f"cli.{sys.implementation.cache_tag}.pyc").is_file()
    record = json.loads((runtime / "SEAL.json").read_text())
    assert record == result["seal"] and record["schema"] == "ravel-governed-runtime.v1"
    assert record["digest"] == tree and record["runtime_id"] == runtime.name
    assert record["bytecode"]["digest"] == identity._bytecode_digest(sealed)
    assert record["bytecode"]["invalidation"] == "checked-hash" and record["bytecode"]["not_compiled"] == []
    assert record["source"] == {"package_dir": str(Path(os.path.realpath(package))),
                                "kind": identity.package_identity(package)["kind"]}
    assert record["python"] == {"executable": sys.executable, "version": platform.python_version(),
                                "implementation": sys.implementation.name}
    assert "ravel_version" in record and "distribution" in record
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record["created_utc"])
    text = launcher.read_text()
    assert text.startswith("#!/bin/sh\n") and f"exec {shlex.quote(sys.executable)} -I -c " in text
    assert json.dumps(str(runtime / "site")) in text and text.rstrip().endswith('"$@"')
    pointer = governed / "CURRENT"
    assert stat.S_ISREG(os.lstat(pointer).st_mode) and pointer.read_text() == str(runtime) + "\n"
    assert gr.verify(runtime) == []
    current = gr.current()
    assert current["runtime_id"] == runtime.name and current["launcher"] == str(launcher) and current["problems"] == []


def test_sealing_identical_bytes_again_reuses_the_runtime_and_new_bytes_make_a_new_current_one(tmp_path):
    package = tiny_package(tmp_path / "copy")
    first = gr.seal(package=package)
    runtime = Path(first["runtime_dir"])
    stamp = {p: os.lstat(p).st_mtime_ns for p in runtime.rglob("*")}
    again = gr.seal(package=package)
    assert again["reused"] is True and again["runtime_dir"] == first["runtime_dir"] and again["seal"] == first["seal"]
    assert {p: os.lstat(p).st_mtime_ns for p in runtime.rglob("*")} == stamp
    (package / "cli.py").write_text("def main(argv=None):\n    return 1\n")
    other = gr.seal(package=package)
    assert other["reused"] is False and other["runtime_dir"] != first["runtime_dir"]
    assert gr.current()["runtime_dir"] == other["runtime_dir"] and gr.verify(runtime) == []
    (package / "cli.py").write_text("def main(argv=None):\n    return 0\n")
    assert gr.seal(package=package)["reused"] is True and gr.current()["runtime_dir"] == first["runtime_dir"]


def test_a_package_with_a_symbolic_link_is_not_sealed(tmp_path, governed):
    package = tiny_package(tmp_path / "copy")
    (package / "linked.py").symlink_to(package / "cli.py")
    with pytest.raises(gr.SealRefused, match="symbolic link"):
        gr.seal(package=package)
    # Nothing is left behind: no runtime, staging tree or pointer.
    assert not governed.exists() or [p.name for p in governed.iterdir()] in ([], [gr.LOCK])


def test_returned_write_bits_are_removed_again_when_the_bytes_still_verify(tmp_path):
    package = tiny_package(tmp_path / "copy")
    runtime = Path(gr.seal(package=package)["runtime_dir"])
    os.chmod(runtime / "site", 0o755)
    problems = gr.verify(runtime)
    assert problems and all(p.startswith(gr.MODE_PROBLEM) for p in problems)
    reopened = identity.package_identity(runtime / "site" / "ravel")
    assert reopened["kind"] == "sealed" and reopened["writable_by_controller_user"] is True
    with pytest.raises(identity.UngovernedInstall, match="writable"):
        identity.require_governed_install(identity=reopened)
    assert gr.seal(package=package)["reused"] is True and gr.verify(runtime) == []


# ---- the identity gate --------------------------------------------------------------------------

def test_identity_of_installed_sealed_checkout_and_writable_copies(tmp_path, monkeypatch):
    site = tmp_path / "site-packages"
    installed = tiny_package(site)
    monkeypatch.setattr(identity, "_site_directories", lambda: [Path(os.path.realpath(site))])
    writable = identity.package_identity(installed)
    assert writable["kind"] == "installed" and writable["writable_by_controller_user"] is True
    with pytest.raises(identity.UngovernedInstall, match="writable") as refused:
        identity.require_governed_install(identity=writable)
    assert refused.value.fix == SEAL and refused.value.problems
    _read_only(site)
    read_only = identity.package_identity(installed)
    assert read_only["kind"] == "installed" and read_only["writable_by_controller_user"] is False
    assert identity.require_governed_install(identity=read_only)["governed"] is True
    _writable(site)
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    source = tiny_package(checkout / "src")
    found = identity.package_identity(source)
    assert found["kind"] == "checkout" and found["checkout"] == str(Path(os.path.realpath(checkout)))
    with pytest.raises(identity.UngovernedInstall, match="checkout code"):
        identity.require_governed_install(identity=found)
    runtime = Path(gr.seal(package=installed)["runtime_dir"])
    sealed = identity.package_identity(runtime / "site" / "ravel")
    assert sealed["kind"] == "sealed" and sealed["runtime_id"] == runtime.name and sealed["digest"] == writable["digest"]
    assert sealed["sealed_from"] == {"package_dir": str(Path(os.path.realpath(installed))), "kind": "installed"}
    assert sealed["writable_by_controller_user"] is False and sealed["symlinks"] == [] and sealed["checkout"] is None
    admitted = identity.require_governed_install(identity=sealed)
    assert admitted["governed"] is True and admitted["label"] is None and admitted["problems"] == []
    # code_identity reports the imported package through the same classification.
    monkeypatch.setattr(identity, "_imported_package", lambda: runtime / "site" / "ravel")
    assert identity.code_identity()["kind"] == "sealed"
    quiet = identity.package_identity(runtime / "site" / "ravel", digest=False)
    assert quiet["kind"] == "sealed" and "digest" not in quiet
    # A sealed runtime that redirects nothing is still refused while a selector is set.
    monkeypatch.setenv("RAVEL_ROOT", str(checkout))
    with pytest.raises(identity.UngovernedInstall, match="RAVEL_ROOT") as redirected:
        identity.require_governed_install(identity=identity.package_identity(runtime / "site" / "ravel"))
    assert redirected.value.fix == "unset RAVEL_ROOT"


class _Distribution:
    """Installed-distribution metadata with one ``direct_url.json`` body."""
    version = "0"

    def __init__(self, direct_url):
        self.direct_url = direct_url

    def read_text(self, name):
        return self.direct_url if name == "direct_url.json" else None


def test_an_editable_install_identifies_only_the_project_it_points_at(tmp_path, monkeypatch):
    """The kind comes from the package at hand: an editable install elsewhere in the environment, as the
    CI runner makes, does not turn another checkout into 'editable'."""
    monkeypatch.setattr(identity, "_site_directories", lambda: [Path(os.path.realpath(tmp_path / "site-packages"))])
    project = tmp_path / "project with space"
    other = tmp_path / "other"
    for root in (project, other):
        (root / ".git").mkdir(parents=True)
    source = tiny_package(project / "src")
    elsewhere = tiny_package(other / "src")

    def installed_as(directory, editable=True):
        body = json.dumps({"url": directory.as_uri(), "dir_info": {"editable": editable}})
        monkeypatch.setattr(identity, "_distribution", lambda: _Distribution(body))

    installed_as(other)
    assert identity.package_identity(source)["kind"] == "checkout"
    assert identity.package_identity(elsewhere)["kind"] == "editable"
    installed_as(project)
    found = identity.package_identity(source)
    assert found["kind"] == "editable" and found["checkout"] == str(Path(os.path.realpath(project)))
    with pytest.raises(identity.UngovernedInstall, match="editable code"):
        identity.require_governed_install(identity=found)
    assert identity.package_identity(elsewhere)["kind"] == "checkout"
    installed_as(project, editable=False)
    assert identity.package_identity(source)["kind"] == "checkout"
    # Metadata that cannot be read to the end keeps the cautious answer; no metadata is no editable install.
    for body, kind in (("{not json", "editable"), (json.dumps({"dir_info": {"editable": True}}), "editable"),
                       (json.dumps({"url": "https://example.invalid/p", "dir_info": {"editable": True}}), "editable"),
                       ("", "checkout"), (None, "checkout")):
        monkeypatch.setattr(identity, "_distribution", lambda body=body: _Distribution(body))
        assert identity.package_identity(source)["kind"] == kind, body
    monkeypatch.setattr(identity, "_distribution", lambda: None)
    assert identity.package_identity(source)["kind"] == "checkout"


@pytest.mark.parametrize("change", ["source", "bytecode", "seal-record", "link"])
def test_a_changed_runtime_is_not_sealed_and_admission_refuses(tmp_path, monkeypatch, change):
    package = tiny_package(tmp_path / "copy")
    monkeypatch.setattr(identity, "_imported_package", lambda: package)
    runtime = Path(gr.seal(package=package)["runtime_dir"])
    sealed = runtime / "site" / "ravel"
    assert identity.package_identity(sealed)["kind"] == "sealed" and gr.admission()["status"] == "ready"
    if change == "source":
        _rewrite(sealed / "data" / "note.json", '{"fictional": false}\n')
    elif change == "bytecode":
        compiled = sealed / "__pycache__" / f"cli.{sys.implementation.cache_tag}.pyc"
        os.chmod(compiled.parent, 0o755)
        os.chmod(compiled, 0o644)
        compiled.write_bytes(compiled.read_bytes() + b"\0")
        os.chmod(compiled, 0o444)
        os.chmod(compiled.parent, 0o555)
    elif change == "seal-record":
        record = json.loads((runtime / "SEAL.json").read_text())
        record["digest"] = "tree:" + "f" * 64
        os.chmod(runtime, 0o755)
        os.chmod(runtime / "SEAL.json", 0o644)
        (runtime / "SEAL.json").write_text(json.dumps(record))
        os.chmod(runtime / "SEAL.json", 0o444)
        os.chmod(runtime, 0o555)
    else:
        os.chmod(sealed, 0o755)
        (sealed / "planted.py").symlink_to(tmp_path / "elsewhere.py")
        os.chmod(sealed, 0o555)
    changed = identity.package_identity(sealed)
    if change == "link":
        assert changed["symlinks"] == ["planted.py"]
    else:
        assert changed["kind"] != "sealed" and "runtime_id" not in changed
    with pytest.raises(identity.UngovernedInstall):
        identity.require_governed_install(identity=changed)
    assert gr.verify(runtime)
    decision = gr.admission()
    assert decision["status"] == "not-ready" and decision["launcher"] is None and decision["fix"] == SEAL
    assert "does not verify" in decision["reason"]
    with pytest.raises(gr.SealRefused, match="no longer verifies"):
        gr.seal(package=package)


def test_a_runtime_reached_through_a_link_or_a_linked_pointer_is_refused(tmp_path, monkeypatch, governed):
    package = tiny_package(tmp_path / "copy")
    monkeypatch.setattr(identity, "_imported_package", lambda: package)
    runtime = Path(gr.seal(package=package)["runtime_dir"])
    outside = tmp_path / "outside" / runtime.name
    shutil.copytree(runtime, outside)  # a faithful copy of the runtime, its seal record included
    _writable(runtime)
    shutil.rmtree(runtime)
    runtime.symlink_to(outside, target_is_directory=True)
    linked = identity.package_identity(runtime / "site" / "ravel")
    assert linked["kind"] != "sealed" and linked["package_dir"] == str(Path(os.path.realpath(outside)) / "site" / "ravel")
    with pytest.raises(identity.UngovernedInstall):
        identity.require_governed_install(identity=linked)
    assert gr.verify(runtime) == [f"{runtime} is not a directory"]
    assert gr.admission()["status"] == "not-ready"
    pointer = governed / "CURRENT"
    pointer.unlink()
    pointer.symlink_to(tmp_path / "pointer-elsewhere")
    found = gr.current()
    assert found["runtime_id"] is None and found["problems"] and gr.admission()["status"] == "not-ready"
    # A runtime directory that is itself a link would move every seal elsewhere: refused, fail closed.
    _writable(governed)
    shutil.rmtree(governed)
    governed.symlink_to(outside.parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        identity.runtime_root()
    assert identity.package_identity(outside / "site" / "ravel")["kind"] != "sealed"
    with pytest.raises(ValueError, match="symbolic link"):
        gr.seal(package=package)
    decision = gr.admission()
    assert decision["status"] == "not-ready" and "cannot be read" in decision["reason"]
    governed.unlink()


def test_the_distribution_lookup_tries_the_declared_name_then_the_import_name(monkeypatch):
    metadata = identity.importlib.metadata
    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["name"] == identity.DISTRIBUTIONS[0]
    seen = []

    class Found:
        version = "0.0.1"

    def only_import_name(name):
        seen.append(name)
        if name == "ravel":
            return Found()
        raise metadata.PackageNotFoundError(name)
    monkeypatch.setattr(metadata, "distribution", only_import_name)
    assert identity._distribution().version == "0.0.1" and seen == ["ravel-hep", "ravel"]
    seen.clear()
    monkeypatch.setattr(metadata, "distribution", lambda name: seen.append(name) or Found())
    assert identity._distribution() is not None and seen == ["ravel-hep"]

    def absent(name):
        raise metadata.PackageNotFoundError(name)
    monkeypatch.setattr(metadata, "distribution", absent)
    assert identity._distribution() is None


def test_the_refusal_names_only_commands_that_exist(tmp_path, capsys):
    with pytest.raises(identity.UngovernedInstall) as checkout:
        identity.require_governed_install()  # this suite runs from a writable source tree
    assert SEAL in str(checkout.value) and checkout.value.fix == SEAL
    package = tiny_package(tmp_path / "copy")
    found = identity.package_identity(package)
    with pytest.raises(identity.UngovernedInstall) as refused:
        identity.require_governed_install(identity={**found, "selectors": {"RAVEL_ROOT": str(tmp_path)},
                                                    "symlinks": ["linked.py"]})
    message = str(refused.value)
    assert "--development" not in message
    commands = re.findall(r"`([^`]+)`", message)
    launcher = str(identity.runtime_root() / identity.runtime_id(found["digest"]) / "bin" / "ravel")
    assert set(commands) == {"unset RAVEL_ROOT", "bash scripts/setup/install.sh", SEAL, launcher}
    for command in commands:
        words = shlex.split(command)
        if words[0] == "ravel":
            with pytest.raises(SystemExit) as parsed:  # the real command line accepts the words
                cli.main([*words[1:], "--help"])
            assert parsed.value.code == 0, command
        elif words[0] == "bash":
            assert (ROOT / words[1]).is_file()
        elif words[0] == "unset":
            assert set(words[1:]) <= set(identity.SELECTORS)
    capsys.readouterr()
    assert gr.parser().parse_args(["seal"]).command == "seal"
    assert cli.FOCUSED_COMMANDS["governed-runtime"][0] == "setup.governed_runtime"
    sealed = gr.seal(package=package)
    assert sealed["launcher"] == launcher and os.access(launcher, os.X_OK)


def test_ledger_evidence_admits_sealed_code_exactly_as_installed_code():
    from ravel.controller.confine import ledger_evidence, policy

    class Store:
        def __init__(self, rows):
            self.rows = rows

        def scan(self, kind):
            return self.rows.get(kind, [])
    pin = [{"id": "pin-1", "record": {"schema_version": 1, "path": "/fictional/policy.json", "sha256": "a" * 64}}]
    for kind, proved in (("installed", True), ("sealed", True), ("checkout", False), ("editable", False)):
        record = {"kind": kind, "governed": True, "label": None, "problems": [], "writable_by_controller_user": False,
                  "symlinks": [], "selectors": {}}
        rows = ledger_evidence.ledger_evidence(Store({"code-identity": [{"id": "ci-1", "record": record}],
                                                      policy.SOURCE_KIND: pin}))
        assert ({"SW23", "SW29"} <= set(rows)) is proved and (proved or rows == {}), kind
        writable = dict(record, writable_by_controller_user=True)
        assert ledger_evidence.ledger_evidence(Store({"code-identity": [{"id": "ci-1", "record": writable}],
                                                      policy.SOURCE_KIND: pin})) == {}


# ---- the entries, status and the doctor ---------------------------------------------------------

@pytest.mark.parametrize("form", ["ask", "drive", "resume"])
def test_a_refused_entry_creates_no_run_directory_or_store(tmp_path, capsys, form):
    from ravel.controller import store
    request = tmp_path / "request.txt"
    request.write_text(REQUEST)
    run = tmp_path / "runs" / "r1"
    argv = {"ask": ["ask", "--rundir", str(run), REQUEST],
            "drive": ["drive", "--request-file", str(request), "--rundir", str(run)],
            "resume": ["drive", "--resume", "run-20000101-000000-00000000"]}[form]
    root = store.store_root()
    assert cli.main(argv) == 2
    err = capsys.readouterr().err
    assert "nothing was started" in err and SEAL in err and "--development" not in err
    assert "no controller run" not in err  # the identity check comes before the resume lookup
    assert not (tmp_path / "runs").exists() and (not root.exists() or not any(root.iterdir()))


def test_an_unsealed_install_reexecutes_through_the_current_runtime_holding_its_bytes(tmp_path, monkeypatch,
                                                                                      capsys):
    package = tiny_package(tmp_path / "site-packages")
    monkeypatch.setattr(identity, "_imported_package", lambda: package)
    calls = []

    def execv(path, args):
        calls.append((path, list(args)))
        raise Reexec()
    monkeypatch.setattr(os, "execv", execv)
    run = tmp_path / "runs" / "r1"
    ask = ["ask", "--rundir", str(run), REQUEST]
    assert cli.main(ask) == 2 and calls == []  # nothing sealed yet: refused
    capsys.readouterr()
    sealed = gr.seal(package=package)
    with pytest.raises(Reexec):
        cli.main(ask)
    assert calls == [(sealed["launcher"], [sealed["launcher"], *ask])] and not run.exists()
    calls.clear()
    resume = ["drive", "--resume", "run-20000101-000000-00000000"]
    with pytest.raises(Reexec):
        cli.main(resume)
    assert calls == [(sealed["launcher"], [sealed["launcher"], *resume])]
    calls.clear()
    (package / "cli.py").write_text("def main(argv=None):\n    return 3\n")  # an upgrade without a new seal
    assert cli.main(ask) == 2 and calls == []
    assert "not the bytes imported here" in capsys.readouterr().err
    (package / "cli.py").write_text("def main(argv=None):\n    return 0\n")
    # Inside the sealed runtime a failed check never hands over again: it refuses.
    sealed_package = Path(sealed["runtime_dir"]) / "site" / "ravel"
    monkeypatch.setattr(identity, "_imported_package", lambda: sealed_package)
    os.chmod(sealed_package, 0o755)
    assert cli.main(ask) == 2 and calls == []
    assert "writable" in capsys.readouterr().err
    os.chmod(sealed_package, 0o555)


def test_status_reports_the_current_runtime_the_match_and_the_admission(tmp_path, monkeypatch, capsys):
    package = tiny_package(tmp_path / "copy")
    monkeypatch.setattr(identity, "_imported_package", lambda: package)
    assert cli.main(["governed-runtime", "status"]) == 1
    before = json.loads(capsys.readouterr().out)
    assert before["schema"] == gr.STATUS_SCHEMA and before["current"] is None and before["matches_imported"] is False
    assert before["admission"]["status"] == "not-ready" and before["admission"]["fix"] == SEAL
    assert before["imported"]["package_dir"] == str(Path(os.path.realpath(package)))
    assert cli.main(["governed-runtime", "seal"]) == 0
    sealed = json.loads(capsys.readouterr().out)
    assert cli.main(["governed-runtime", "status"]) == 0
    after = json.loads(capsys.readouterr().out)
    assert after["current"]["runtime_id"] == sealed["runtime_id"] and after["current"]["problems"] == []
    assert after["matches_imported"] is True and after["imported"]["digest"] == sealed["seal"]["digest"]
    assert after["admission"] == {"status": "ready", "runs": "sealed", "kind": "sealed",
                                  "package_dir": str(Path(sealed["runtime_dir"]) / "site" / "ravel"),
                                  "runtime_id": sealed["runtime_id"], "launcher": sealed["launcher"],
                                  "reason": None, "fix": None}


def test_the_doctor_reports_the_controller_admission_and_a_refusal_makes_it_not_ready(tmp_path, monkeypatch,
                                                                                      capsys):
    from ravel.setup import doctor
    package = tiny_package(tmp_path / "copy")
    monkeypatch.setattr(identity, "_imported_package", lambda: package)
    argv = ["--group", "cosmology", "--json", "--prefix", str(tmp_path / "prefix")]
    probe = lambda argv, env=None, timeout=15: (0, "1.6.5 3.4.1.0 3.6.2")  # noqa: E731
    code = doctor.main(argv, repo=ROOT, run_probe=probe)
    refused = json.loads(capsys.readouterr().out)
    entry = refused["controller_admission"]
    assert entry["status"] == "not-ready" and entry["fix"] == SEAL and "nothing was started" in entry["reason"]
    assert refused["ready"] is False and code == 1
    assert f"fix: {SEAL}" in doctor.format_report(refused)
    gr.seal(package=package)
    code = doctor.main(argv, repo=ROOT, run_probe=probe)
    admitted = json.loads(capsys.readouterr().out)
    entry = admitted["controller_admission"]
    assert entry["status"] == "ready" and entry["runs"] == "sealed" and entry["fix"] is None
    toolchain_ready = admitted["status"] in doctor.OK_STATUSES
    assert admitted["ready"] is toolchain_ready and code == (0 if toolchain_ready else 1)
    assert f"controller-admission  ready: ravel ask runs the sealed runtime {entry['runtime_id']}" in \
        doctor.format_report(admitted)


def test_the_installer_seals_with_the_host_interpreter_and_reports_a_failure(tmp_path, monkeypatch, capsys):
    from ravel import python_installation as p
    runtime = {"runtime_id": "a" * 16, "runtime_dir": "/fictional/runtime/" + "a" * 16,
               "launcher": "/fictional/runtime/" + "a" * 16 + "/bin/ravel", "reused": False}
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(runtime), stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(sys, "version_info", (3, 12, 0))
    monkeypatch.setattr(p, "declarations", lambda root: {"host_requirements": "requirements-full.txt",
                                                         "isolated_required": [{"directory": ".venv-x",
                                                                                "requirements": "x.txt"}]})
    monkeypatch.setattr(p, "_environment", lambda root, logical: root / logical / "bin/python")
    value = p.install(tmp_path, host_only=True)
    host = str(tmp_path / ".venv/bin/python")
    assert [argv for argv, _ in calls] == [[host, "-m", "pip", "install", "-r", str(tmp_path / "requirements-full.txt")],
                                           [host, "-I", "-m", "ravel", "governed-runtime", "seal"]]
    assert calls[-1][1]["cwd"] == tmp_path and value["governed_runtime"] == {**runtime, "sealed": True}
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(
        argv, 2, stdout="", stderr="ravel governed-runtime seal: refused for a fictional reason"))
    failed = p.seal_host(Path(host), tmp_path)
    assert failed["sealed"] is False and "fictional reason" in failed["error"]
    assert failed["fix"] == shlex.join([host, "-I", "-m", "ravel", "governed-runtime", "seal"])
    monkeypatch.setattr(p, "install", lambda root, host_only=False: {"governed_runtime": failed})
    assert p.main([], source_root=tmp_path) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["governed_runtime"]["sealed"] is False
    assert "not sealed" in captured.err and failed["fix"] in captured.err
    monkeypatch.setattr(p, "install", lambda root, host_only=False: {"governed_runtime": {**runtime, "sealed": True}})
    assert p.main(["--host-only"], source_root=tmp_path) == 0


# ---- acceptance: a fresh user-writable installation -----------------------------------------------

def _fresh_install(base):
    """The package copied into a new environment's site-packages, writable by its user, with its metadata."""
    venv.EnvBuilder(system_site_packages=True, with_pip=False).create(base)
    python = base / "bin" / "python"
    site = Path(subprocess.check_output([str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                                        text=True).strip())
    # Dependencies come from the test interpreter's environment; this checkout stays off the path.
    dependencies = [p for p in sys.path if p and Path(p).name in ("site-packages", "dist-packages")]
    (site / "fresh-install-dependencies.pth").write_text("\n".join(dependencies) + "\n")
    shutil.copytree(ROOT / "src" / "ravel", site / "ravel", ignore=shutil.ignore_patterns("__pycache__"))
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    info = site / f"ravel_hep-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: ravel-hep\nVersion: {version}\n")
    (info / "INSTALLER").write_text("fresh-install fixture\n")
    (info / "RECORD").write_text("ravel/__init__.py,,\n")
    return python, site, version


def _only_run(root, before):
    from ravel.controller.store import RunStore
    [run_id] = sorted(p.name for p in root.iterdir() if (p / "run.json").is_file() and p.name not in before)
    store = RunStore(run_id, root=root)
    kinds = [json.loads(line)["kind"] for line in (store.root / "journal.jsonl").read_text().splitlines()]
    return store, kinds


def test_a_fresh_writable_install_is_refused_then_sealed_and_its_launcher_starts_a_run(tmp_path):
    python, site, version = _fresh_install(tmp_path / "fresh")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", RAVEL_STATE_DIR=str(tmp_path / "state"))
    for name in ("PYTHONPATH", "PYTHONHOME", *identity.SELECTORS):
        env.pop(name, None)
    request = tmp_path / "request.txt"
    request.write_text(REQUEST)
    runs = tmp_path / "runs"
    store_root = Path(os.path.realpath(operator.controller_home() / "runs"))

    def ravel(*argv, command=None):
        return subprocess.run([*(command or [str(python), "-m", "ravel"]), *argv], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=600)

    refused = ravel("drive", "--request-file", str(request), "--rundir", str(runs / "refused"))
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "writable" in refused.stderr and SEAL in refused.stderr and "--development" not in refused.stderr
    assert not runs.exists() and (not store_root.exists() or not any(store_root.iterdir()))

    sealed = ravel("governed-runtime", "seal")
    assert sealed.returncode == 0, sealed.stderr
    result = json.loads(sealed.stdout)
    seal, launcher = result["seal"], result["launcher"]
    assert Path(result["runtime_dir"]).parent == identity.runtime_root()
    assert seal["source"] == {"package_dir": str(Path(os.path.realpath(site / "ravel"))), "kind": "installed"}
    assert seal["digest"] == "tree:" + identity._tree_digest(site / "ravel") and seal["python"]["executable"] == str(python)
    record = (site / f"ravel_hep-{version}.dist-info" / "RECORD").read_bytes()
    assert seal["distribution"] == {"name": "ravel-hep", "version": version,
                                    "record_sha256": hashlib.sha256(record).hexdigest()}
    assert seal["ravel_version"] == version

    for name, command in (("sealed", [launcher]), ("ordinary", None)):
        before = {p.name for p in store_root.iterdir()} if store_root.exists() else set()
        started = ravel("drive", "--request-file", str(request), "--rundir", str(runs / name), command=command)
        # Admitted code starts the run; it stops at the operator's restricted-source pin, before any model call.
        assert started.returncode == 2 and "not admitted: operator restricted_sources" in started.stderr, \
            started.stdout + started.stderr
        store, kinds = _only_run(store_root, before)
        assert store.verify() == [] and Path(os.path.realpath(store.run_dir)) == Path(os.path.realpath(runs / name))
        assert kinds[0] == "run" and "request" in kinds and kinds[-1] == "code-identity", kinds
        assert not {"intake", "route", "plan", "wave", "authority", "judgment", "step-launch"} & set(kinds)
        pinned = store.latest("request")["record"]
        assert pinned["sha256"] == hashlib.sha256(REQUEST.encode()).hexdigest()
        admitted = store.latest("code-identity")["record"]
        assert admitted["kind"] == "sealed" and admitted["governed"] is True and admitted["label"] is None
        assert admitted["runtime_id"] == result["runtime_id"] and admitted["digest"] == seal["digest"]
        assert admitted["package_dir"] == str(Path(result["runtime_dir"]) / "site" / "ravel")
