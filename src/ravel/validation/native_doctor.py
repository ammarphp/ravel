"""Read-only macOS native-toolchain preflight; it never installs or generates events.

The report describes prerequisite availability, not a clean-install certification
or physics validation. Use ``python -m ravel.validation.native_doctor --json``.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess

from ravel.paths import native_binary, native_build_root


class ProbeError(ValueError):
    pass


def probe(command, *, env=None):
    """Only bounded version/configuration probes belong here; no shell expansion."""
    query_env = (os.environ if env is None else env).copy()
    query_env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run([str(x) for x in command], capture_output=True,
                                text=True, timeout=15, env=query_env, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"{command[0]}: {exc}") from exc
    if result.returncode:
        raise ProbeError(f"{command[0]} returned {result.returncode}: "
                         f"{result.stderr.strip()[:400]}")
    return result.stdout.strip()


def host_info(*, system=None, machine=None, run=probe):
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    result = {"system": system, "process_arch": machine, "native_arch": machine,
              "rosetta": False, "supported": False, "errors": []}
    if system != "Darwin":
        result["errors"].append("These native provisioning/build recipes require macOS")
        return result
    def optional(key):
        try:
            return run(["sysctl", "-in", key])
        except ProbeError:
            return None
    translated = optional("sysctl.proc_translated")
    silicon = optional("hw.optional.arm64")
    result["rosetta"] = translated == "1" or (machine == "x86_64" and silicon == "1")
    if result["rosetta"]:
        result["native_arch"] = "arm64"
        result["errors"].append("Rosetta process: use a native Apple Silicon terminal and Python")
    if machine not in {"arm64", "x86_64"}:
        result["errors"].append(f"Unsupported macOS process architecture: {machine}")
    try:
        version = run(["sw_vers", "-productVersion"])
        result["macos_version"] = version
        if int(version.split(".")[0]) < 11:
            result["errors"].append("The pinned Miniforge release requires macOS 11 or newer")
    except (ProbeError, ValueError):
        result["errors"].append("Cannot determine the macOS version")
    result["supported"] = not result["errors"]
    return result


def binary_architectures(path, *, run=probe):
    """Inspect bytes via file(1), never execute the binary being inspected."""
    description = run(["file", "-b", "-L", str(path)])
    if "Mach-O" not in description:
        raise ProbeError(f"Not a Mach-O executable/library: {path}: {description}")
    arches = set(re.findall(r"\b(?:arm64|x86_64)\b", description))
    if not arches:
        raise ProbeError(f"Cannot identify architecture: {path}: {description}")
    return arches


def require_architecture(path, arch, *, run=probe):
    path = Path(path)
    if not path.is_file():
        raise ProbeError(f"Missing native binary/library: {path}")
    arches = binary_architectures(path, run=run)
    if arch not in arches:
        raise ProbeError(f"Architecture mismatch: {path} contains {sorted(arches)}, needs {arch}")
    return ", ".join(sorted(arches))


def prefix_environment(prefix):
    env = os.environ.copy()
    env["PATH"] = str(Path(prefix)/"bin") + os.pathsep + env.get("PATH", "")
    env["CONDA_PREFIX"] = str(prefix)
    return env


def compiler_command(prefix, configured=None, *, env=None):
    """Resolve the compiler from configuration or this prefix, without triplets.

    Compiler/config flag strings are tokenized, never evaluated as shell code.
    An explicit compiler that is missing is an error, never a silent fallback.
    """
    prefix = Path(prefix)
    env = prefix_environment(prefix) if env is None else env
    configured = configured or env.get("CXX")
    if configured:
        command = ([configured] if Path(configured).is_file() else shlex.split(configured))
        if not command:
            raise ProbeError("Empty C++ compiler command")
        found = shutil.which(command[0], path=env.get("PATH"))
        if not found:
            raise ProbeError(f"Configured C++ compiler not found: {command[0]}")
        return [found, *command[1:]]
    candidates = sorted(p for p in (prefix/"bin").glob("*-clang++") if os.access(p, os.X_OK))
    resolved = {p.resolve(): p for p in candidates}
    if len(resolved) == 1:
        return [str(next(iter(resolved.values())))]
    if len(resolved) > 1:
        raise ProbeError("Multiple C++ compilers in the prefix; select CXX explicitly")
    found = shutil.which("clang++", path=env.get("PATH"))
    if not found:
        raise ProbeError("No C++ compiler found; provide CXX or the matching conda compiler")
    return [found]


def compiler_target(command, arch, *, run=probe):
    target = run([*command, "-dumpmachine"])
    expected = {"arm64": ("arm64", "aarch64"), "x86_64": ("x86_64",)}.get(arch, ())
    if not target.startswith(expected) or "darwin" not in target.lower():
        raise ProbeError(f"Compiler target {target!r} does not match native macOS {arch}")
    return target


def diagnose(build_root=None, binary_dir=None, *, profile="native", require_rjr=False,
             run=probe, host=None):
    build = Path(build_root).expanduser().resolve() if build_root else native_build_root()
    binaries = Path(binary_dir).expanduser().resolve() if binary_dir else native_binary("pythia_shower").parent
    host = host_info(run=run) if host is None else host
    report = {"schema_version": 1, "read_only": True, "profile": profile,
              "host": host, "build_root": str(build), "binary_dir": str(binaries),
              "checks": [], "scope": "Prerequisite probes only; no compilation, installation, simulation or physics certification"}
    checks = report["checks"]
    def check(name, function, *, warning=False):
        try:
            detail = function()
            checks.append({"name": name, "status": "pass", "detail": str(detail)})
            return True
        except (OSError, ValueError) as exc:
            checks.append({"name": name, "status": "warning" if warning else "fail", "detail": str(exc)})
            return False
    def required(path, executable=False):
        if not path.is_file() or (executable and not os.access(path, os.X_OK)):
            raise ProbeError(f"Missing {'executable' if executable else 'file'}: {path}")
        return path
    def required_directory(path):
        if not path.is_dir():
            raise ProbeError(f"Missing directory: {path}")
        return path
    checks.append({"name": "host", "status": "pass" if host["supported"] else "fail",
                   "detail": "; ".join(host["errors"]) or f"Native {host['native_arch']} macOS"})
    arch = host["native_arch"]
    expected_subdir = {"arm64": "osx-arm64", "x86_64": "osx-64"}.get(arch)
    def subdir_check():
        actual = os.environ.get("CONDA_SUBDIR")
        if actual and actual != expected_subdir:
            raise ProbeError(f"CONDA_SUBDIR={actual} conflicts with {expected_subdir}")
        return actual or f"not overridden; expected {expected_subdir}"
    check("conda_subdir", subdir_check)
    prefix = build/"tools/miniforge3"
    check("conda", lambda: required(prefix/"bin/conda", executable=True))
    check("conda_metadata", lambda: required_directory(prefix/"conda-meta"))
    base_ok = check("base_python_arch", lambda: require_architecture(prefix/"bin/python", arch, run=run))
    if base_ok and host["supported"]:
        def conda_version():
            version = run([str(prefix/"bin/conda"), "--version"])
            if not re.fullmatch(r"conda \d+\.\d+[^\s]*", version):
                raise ProbeError(f"Unrecognized conda version response: {version!r}")
            return version
        check("conda_version", conda_version)
    if profile != "bootstrap":
        def sdk():
            path = Path(run(["xcrun", "--show-sdk-path"]))
            required_directory(path)
            return path
        check("macos_sdk", sdk)
    envs = {"bootstrap": [], "mg5": ["mg5"], "shower": ["rivet"],
            "recast": ["recast"], "native": ["mg5", "rivet", "recast"]}[profile]
    modules = {"mg5": ["six", "numpy"], "rivet": ["numpy", "uproot", "awkward", "pyhf", "jsonpatch"],
               "recast": ["ROOT", "numpy", "awkward"]}
    for name in envs:
        env_prefix = prefix/"envs"/name
        python = env_prefix/"bin/python"
        compatible = check(f"{name}_python_arch", lambda p=python: require_architecture(p, arch, run=run))
        check(f"{name}_metadata", lambda p=env_prefix: required_directory(p/"conda-meta"))
        if compatible and base_ok and host["supported"]:
            def imports(p=python, packages=modules[name], name=name):
                script = ("import importlib.util,json,sys; "
                          "print(json.dumps({'version':list(sys.version_info[:3]), 'missing':"
                          f"[x for x in {packages!r} if importlib.util.find_spec(x) is None]" + "}))")
                data = json.loads(run([str(p), "-I", "-B", "-c", script]))
                if data["missing"]:
                    raise ProbeError(f"Missing modules: {', '.join(data['missing'])}")
                if name == "mg5" and data["version"][:2] != [3, 10]:
                    raise ProbeError("The recorded MG5 recipe requires Python 3.10")
                return f"Python {'.'.join(map(str, data['version']))}; {', '.join(packages)} discoverable (imports not exercised)"
            check(f"{name}_python_packages", imports)
        if name == "mg5":
            check("madgraph_source", lambda: required(build/"tools/mg5amcnlo/bin/mg5_aMC"))
            for tool in ["gfortran", "make"]:
                check(f"mg5_{tool}", lambda t=tool: required(env_prefix/"bin"/t, executable=True))
            if compatible and host["supported"]:
                check("fortran_target", lambda p=env_prefix: compiler_target([str(p/"bin/gfortran")], arch, run=run))
        if name == "rivet":
            for tool in ["pythia8-config", "HepMC3-config"]:
                check(tool, lambda t=tool: required(env_prefix/"bin"/t, executable=True))
            check("pythia_shower", lambda: require_architecture(binaries/"pythia_shower", arch, run=run))
            if compatible and host["supported"]:
                check("shower_compiler", lambda p=env_prefix: compiler_target(compiler_command(p), arch, run=run))
        if name == "recast":
            config = env_prefix/"bin/root-config"
            if check("root_config", lambda: required(config, executable=True)) and host["supported"] and compatible:
                def root_configuration(p=env_prefix, config=config):
                    found = Path(run([str(config), "--prefix"])).resolve()
                    if found != p.resolve():
                        raise ProbeError(f"root-config resolves to {found}, expected {p}")
                    command = compiler_command(p, os.environ.get("CXX") or run([str(config), "--cxx"]))
                    target = compiler_target(command, arch, run=run)
                    return f"ROOT {run([str(config), '--version'])}; compiler {shlex.join(command)}; target {target}"
                check("root_configuration", root_configuration)
            check("delphes", lambda: require_architecture(env_prefix/"bin/DelphesHepMC3", arch, run=run))
            check("libDelphes", lambda: require_architecture(env_prefix/"lib/libDelphes.dylib", arch, run=run))
            check("delphes_headers", lambda: required(env_prefix/"include/classes/DelphesClasses.h"))
            check("delphes_reader_headers", lambda: required(env_prefix/"include/ExRootAnalysis/ExRootTreeReader.h"))
    if profile == "native":
        check("mapyde_converter", lambda: required(prefix/"envs/pipeline/share/mapyde/scripts/Delphes2SA.py"))
    if require_rjr:
        check("rjr_resolve", lambda: require_architecture(binaries/"rjr_resolve", arch, run=run))
        check("RestFrames", lambda: require_architecture(build/"tools/restframes-native/lib/libRestFrames.dylib", arch, run=run))
    report["ready"] = all(item["status"] != "fail" for item in checks)
    report["counts"] = {status: sum(c["status"] == status for c in checks) for status in ("pass", "warning", "fail")}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--binary-dir", type=Path)
    parser.add_argument("--profile", choices=["bootstrap", "mg5", "shower", "recast", "native"], default="native")
    parser.add_argument("--require-rjr", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = diagnose(args.build_root, args.binary_dir, profile=args.profile, require_rjr=args.require_rjr)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Native preflight: {'ready for prerequisite review' if report['ready'] else 'blocked'}")
        for item in report["checks"]:
            print(f"[{item['status']}] {item['name']}: {item['detail']}")
        print(report["scope"])
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
