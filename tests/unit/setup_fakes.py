"""Fakes for installer and doctor tests: no network, no real conda, git or builds."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeOpener:
    """urlopen stand-in serving bytes from a dict and counting requests."""

    def __init__(self, payloads):
        self.payloads = dict(payloads)
        self.requests = []

    def __call__(self, url, timeout):
        self.requests.append(url)
        if url not in self.payloads:
            raise OSError("no such URL in the fake: " + url)
        return contextlib.closing(io.BytesIO(self.payloads[url]))


class FakeRunner:
    """Simulates conda, git, container engines and simple build commands.

    ``fail`` is a predicate on argv that forces a nonzero exit. Commands named
    ``make-outputs`` create every later argument as a file.
    """

    def __init__(self, fail=None, images=()):
        self.calls = []
        self.captures = []
        self.envs = []
        self.fail = fail or (lambda argv: False)
        self.images = set(images)

    def run(self, argv, *, cwd=None, env=None, log=None):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        self.envs.append(env)
        if log:
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a") as handle:
                handle.write("$ " + " ".join(argv) + "\n")
        if self.fail(argv):
            return 1
        name = Path(argv[0]).name
        if name == "conda" and argv[1] == "create":
            env_dir = Path(argv[argv.index("--prefix") + 1])
            (env_dir / "conda-meta").mkdir(parents=True, exist_ok=True)
            (env_dir / "bin").mkdir(exist_ok=True)
            (env_dir / "bin/python").write_text("#!/bin/sh\n")
        elif name == "git" and argv[1] == "clone":
            target = Path(argv[-1])
            target.mkdir(parents=True)
            (target / ".git").mkdir()
        elif name == "git" and "checkout" in argv:
            repo = Path(argv[argv.index("-C") + 1])
            (repo / ".fakehead").write_text(argv[-1])
        elif name == "make-outputs":
            for path in argv[1:]:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text("built\n")
        elif "pull" in argv and len(argv) > 2:
            self.images.add(argv[-1])
        return 0

    def capture(self, argv, *, env=None, timeout=30, cwd=None):
        argv = [str(a) for a in argv]
        self.captures.append(argv)
        name = Path(argv[0]).name
        if name == "git" and "rev-parse" in argv:
            head = Path(argv[argv.index("-C") + 1]) / ".fakehead"
            return (0, head.read_text()) if head.is_file() else (128, "not a git repository")
        if name == "git" and "cat-file" in argv:
            return 0, ""
        if name == "git" and "diff" in argv:
            return 0, ""
        if name == "conda" and "list" in argv:
            return 0, "@EXPLICIT\n"
        if "inspect" in argv and "image" in argv:
            return (0, "[]") if argv[-1] in self.images else (1, "no such image")
        if name == "probe-ok":
            return 0, "ok"
        if name == "probe-missing":
            return 1, "missing"
        return 0, ""


def tarball(members: dict[str, bytes], *, extra=None) -> bytes:
    """A gzip tarball from {name: bytes}; ``extra`` adds raw TarInfo entries."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
        for info in extra or ():
            tar.addfile(info)
    return buffer.getvalue()


def pdf_set_tarball(name: str, lhaid: int, members: int = 2) -> bytes:
    files = {f"{name}/{name}.info": f"SetDesc: test\nSetIndex: {lhaid}\nNumMembers: {members}\n".encode()}
    for index in range(members):
        files[f"{name}/{name}_{index:04d}.dat"] = b"PdfType: central\n"
    return tarball(files)


def synthetic_manifest(*, archive_bytes: bytes, pdf_bytes: bytes):
    """A small schema-2 manifest exercising every step kind the engine runs offline."""
    archive_url = "https://example.org/tool.tar.gz"
    groups = [
        {"id": "base", "title": "Base", "depends_on": [], "size_gb": 0.1, "minutes": 1,
         "licenses": [{"component": "Tool", "spdx": "GPL-3.0-or-later"}],
         "steps": [
             {"id": "env", "kind": "conda_env", "name": "tools", "specs": ["python=3.12"]},
             {"id": "source", "kind": "git", "url": "https://example.org/repo.git", "commit": COMMIT_A,
              "dest": "{TOOLS}/repo"},
             {"id": "archive", "kind": "archive", "url": archive_url, "sha256": sha256(archive_bytes),
              "size": len(archive_bytes), "dest": "{TOOLS}/tool", "strip": 1},
         ],
         "checks": [{"id": "tools-python", "kind": "executable", "path": "{ENVS}/tools/bin/python"}]},
        {"id": "data", "title": "Data", "depends_on": ["base"], "size_gb": 0.1, "minutes": 1,
         "licenses": [{"component": "Synthetic data", "spdx": "CC0-1.0"}],
         "steps": [
             {"id": "sets", "kind": "pdf_sets"},
             {"id": "link", "kind": "link_children", "source": "{LHAPDF_DATA}", "dest": "{ENVS}/tools/share/LHAPDF"},
             {"id": "config", "kind": "write_file", "path": "{CONFIG}/data.json", "content": "{\"ok\": true}\n"},
             {"id": "options", "kind": "options_file", "path": "{TOOLS}/repo/options.txt", "values": {"nb_core": "{JOBS}"}},
         ],
         "checks": [{"id": "set-dir", "kind": "directory", "path": "{LHAPDF_DATA}/TestSet"}]},
        {"id": "build", "title": "Build", "depends_on": ["data"], "size_gb": 0.1, "minutes": 1,
         "licenses": [{"component": "Synthetic image", "spdx": "MIT"}],
         "steps": [
             {"id": "compile", "kind": "command", "argv": ["make-outputs", "{BIN}/tool"], "outputs": ["{BIN}/tool"]},
             {"id": "wrapper", "kind": "wrapper", "name": "tool-wrapper", "template": "container-run.sh.in",
              "values": {"IMAGE": "registry.example/tool@sha256:" + "c" * 64, "PLATFORM": "linux/amd64",
                         "COMMAND": "tool", "NAME": "tool", "LHAPDF": "{LHAPDF_DATA}"}},
             {"id": "image", "kind": "container_pull", "name": "tool", "image": "registry.example/tool",
              "digest": "sha256:" + "c" * 64, "platform": "linux/amd64"},
         ],
         "checks": [{"id": "tool", "kind": "executable", "path": "{BIN}/tool"}]},
    ]
    manifest = {
        "schema_version": 2, "kind": "ravel-toolchain-manifest",
        "miniforge": {"version": "0", "url": "https://example.org/{asset}",
                      "assets": {p: {"name": "mf.sh", "sha256": "d" * 64}
                                 for p in ("macos-arm64", "macos-x86_64", "linux-x86_64", "linux-aarch64")}},
        "container_build": {"module": "ravel.execution_backend", "argv": ["{HOST_PYTHON}", "-m", "x", "{RECIPE}"]},
        "default": {"groups": ["base", "data", "build"], "disk_gb": 1}, "profiles": {
                     "site": {"groups": ["base"], "disk_gb": 1}},
        "groups": groups, "operations": [], "incompatible_path_bindings": [],
    }
    catalog = {"schema_version": 1, "kind": "ravel-lhapdf-sets", "base_url": "https://pdf.example.org",
               "sets": [{"name": "TestSet", "lhaid": 12345, "size": len(pdf_bytes), "sha256": sha256(pdf_bytes)}]}
    payloads = {archive_url: archive_bytes, "https://pdf.example.org/TestSet.tar.gz": pdf_bytes}
    return manifest, catalog, payloads


def snapshot(root: Path) -> dict[str, str]:
    """Relative path -> content digest (or 'dir'/'link') for every entry under root."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            rel = str(path.relative_to(root))
            if path.is_symlink():
                out[rel] = "link:" + os.readlink(path)
            elif path.is_dir():
                out[rel] = "dir"
            else:
                out[rel] = sha256(path.read_bytes())
    return out


def write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path
