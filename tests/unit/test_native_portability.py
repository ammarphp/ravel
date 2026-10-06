"""Portable, fake-tool tests: no native HEP installation, compilation or simulation."""
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

import pytest

from ravel.physics import native_build
from ravel.validation import native_doctor as doctor

REPO = Path(__file__).resolve().parents[2]
HOST = {"system": "Darwin", "process_arch": "arm64", "native_arch": "arm64",
        "rosetta": False, "supported": True, "errors": []}


def executable(path, text="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


@pytest.mark.parametrize("system,machine,translated,silicon,version,supported,rosetta", [
    ("Darwin", "arm64", "0", "1", "15.5", True, False),
    ("Darwin", "x86_64", None, "0", "15.6", True, False),
    ("Darwin", "x86_64", "1", "1", "15.6", False, True),
    ("Darwin", "x86_64", None, "1", "15.6", False, True),
    ("Darwin", "ppc64", None, None, "15.6", False, False),
    ("Darwin", "x86_64", None, "0", "10.15", False, False),
    ("Darwin", "arm64", "0", "1", "unknown", False, False),
    ("Linux", "aarch64", None, None, "", False, False),
])
def test_host_architecture_is_not_guessed(system, machine, translated, silicon, version, supported, rosetta):
    def run(cmd):
        value = {"sysctl.proc_translated": translated, "hw.optional.arm64": silicon,
                 "-productVersion": version}[cmd[-1]]
        if value is None:
            raise doctor.ProbeError("unknown sysctl")
        return value
    result = doctor.host_info(system=system, machine=machine, run=run)
    assert result["supported"] is supported
    assert result["rosetta"] is rosetta


@pytest.mark.parametrize("description,arch,passes", [
    ("Mach-O 64-bit executable arm64", "arm64", True),
    ("Mach-O 64-bit executable x86_64", "arm64", False),
    ("Mach-O universal binary with 2 architectures: x86_64 arm64", "arm64", True),
    ("Mach-O universal binary with 2 architectures: x86_64 arm64", "x86_64", True),
    ("POSIX shell script, ASCII text executable arm64", "arm64", False),
    ("ELF 64-bit LSB executable, ARM aarch64", "arm64", False),
])
def test_binary_bytes_not_filename_determine_architecture(tmp_path, description, arch, passes):
    path = executable(tmp_path/"arm64-compiler")
    run = lambda _: description
    if passes:
        assert arch in doctor.require_architecture(path, arch, run=run)
    else:
        with pytest.raises(doctor.ProbeError):
            doctor.require_architecture(path, arch, run=run)


def test_probe_timeout_and_missing_executable_are_reported(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 15
        assert "shell" not in kwargs
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        raise subprocess.TimeoutExpired(args[0], 15)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(doctor.ProbeError, match="timed out"):
        doctor.probe(["fake-tool"])


def test_empty_installation_doctor_is_read_only(tmp_path):
    root = tmp_path/"not installed"
    report = doctor.diagnose(root, tmp_path/"no bins", profile="bootstrap", host=HOST)
    assert report["read_only"] and not report["ready"]
    assert report["counts"]["fail"] == 3
    assert not root.exists()


def test_doctor_does_not_execute_wrong_architecture_python(tmp_path):
    build = tmp_path/"build"
    prefix = build/"tools/miniforge3"
    executable(prefix/"bin/python")
    executable(prefix/"bin/conda")
    (prefix/"conda-meta").mkdir()
    executable(prefix/"envs/mg5/bin/python")
    calls = []
    def run(cmd):
        calls.append(cmd)
        if cmd[0] == "file":
            return "Mach-O 64-bit executable x86_64"
        if cmd[0] == "xcrun":
            return str(tmp_path)
        pytest.fail(f"Unexpected execution: {cmd}")
    report = doctor.diagnose(build, profile="mg5", host=HOST, run=run)
    assert not report["ready"]
    assert all(Path(cmd[0]).name != "python" for cmd in calls)


def test_compiler_path_and_quoted_flags_preserve_spaces_without_shell(tmp_path):
    prefix = tmp_path/"prefix with spaces"
    compiler = executable(prefix/"bin/custom-clang++")
    env = {"PATH": str(prefix/"bin")}
    assert doctor.compiler_command(prefix, str(compiler), env=env) == [str(compiler)]
    assert doctor.compiler_command(prefix, 'custom-clang++ -std=c++17', env=env) == [str(compiler), "-std=c++17"]
    assert native_build.flags("config", run=lambda _: '-I"/include with spaces" -L"/lib with spaces" -lROOT') == [
        "-I/include with spaces", "-L/lib with spaces", "-lROOT"]
    with pytest.raises(doctor.ProbeError, match="not found"):
        doctor.compiler_command(prefix, "missing-compiler", env=env)


def test_ambiguous_compiler_requires_explicit_choice(tmp_path):
    executable(tmp_path/"bin/one-clang++")
    executable(tmp_path/"bin/two-clang++")
    with pytest.raises(doctor.ProbeError, match="Multiple"):
        doctor.compiler_command(tmp_path, env={"PATH": str(tmp_path/"bin")})


def fake_shell_host(tmp_path, *, arch="arm64", translated="0", system="Darwin", subdir=None):
    directory = tmp_path/"fakebin"
    executable(directory/"uname", '#!/bin/sh\ncase "$1" in -s) echo "$FAKE_SYSTEM" ;; -m) echo "$FAKE_ARCH" ;; esac\n')
    executable(directory/"sysctl", '#!/bin/sh\ncase "$2" in sysctl.proc_translated) echo "$FAKE_TRANSLATED" ;; hw.optional.arm64) echo "$FAKE_SILICON" ;; esac\n')
    executable(directory/"sw_vers", '#!/bin/sh\necho 15.5\n')
    executable(directory/"file", '#!/bin/sh\necho "Mach-O 64-bit executable $FAKE_BINARY_ARCH"\n')
    env = os.environ.copy()
    for key in ["BUILD_DIR", "CONDA_SUBDIR", "OUT", "RF_PREFIX", "CXX"]:
        env.pop(key, None)
    env.update(PATH=str(directory)+os.pathsep+os.environ["PATH"], FAKE_SYSTEM=system,
               FAKE_ARCH=arch, FAKE_TRANSLATED=translated,
               FAKE_SILICON="1" if arch == "arm64" or translated == "1" else "0",
               FAKE_BINARY_ARCH=arch, RAVEL_NATIVE_BUILD=str(tmp_path/"native"),
               RAVEL_NATIVE_BIN=str(tmp_path/"nativebin"))
    if subdir:
        env["CONDA_SUBDIR"] = subdir
    return env


def shell(script, env, *args):
    return subprocess.run(["/bin/bash", str(REPO/script), *args], env=env, text=True,
                          capture_output=True, timeout=20, cwd="/tmp")


@pytest.mark.parametrize("arch,asset", [("arm64", "MacOSX-arm64.sh"), ("x86_64", "MacOSX-x86_64.sh")])
def test_bootstrap_selects_pinned_arch_without_writing_or_network(tmp_path, arch, asset):
    env = fake_shell_host(tmp_path, arch=arch)
    result = shell("environment/scripts/00-install-miniforge.sh", env, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert asset in result.stdout and "/download/26.5.3-0/" in result.stdout
    assert "SHA256:" in result.stdout and "latest" not in result.stdout
    assert not Path(env["RAVEL_NATIVE_BUILD"]).exists()


@pytest.mark.parametrize("overrides,fragment", [
    ({"arch": "x86_64", "translated": "1"}, "Rosetta"),
    ({"system": "Linux"}, "requires macOS"),
    ({"arch": "powerpc"}, "unsupported macOS architecture"),
    ({"arch": "arm64", "subdir": "osx-64"}, "CONDA_SUBDIR"),
])
def test_bootstrap_rejects_unsupported_host_before_writing(tmp_path, overrides, fragment):
    env = fake_shell_host(tmp_path, **overrides)
    result = shell("environment/scripts/00-install-miniforge.sh", env, "--dry-run")
    assert result.returncode != 0
    assert fragment in result.stderr
    assert not Path(env["RAVEL_NATIVE_BUILD"]).exists()


def test_partial_install_is_preserved_and_not_reported_ready(tmp_path):
    env = fake_shell_host(tmp_path)
    prefix = Path(env["RAVEL_NATIVE_BUILD"])/"tools/miniforge3"
    prefix.mkdir(parents=True)
    sentinel = prefix/"interrupted-install.txt"
    sentinel.write_text("preserve")
    result = shell("environment/scripts/00-install-miniforge.sh", env)
    assert result.returncode != 0 and "incomplete" in result.stderr
    assert sentinel.read_text() == "preserve"
    assert list(prefix.iterdir()) == [sentinel]


def test_corrupt_installer_is_not_executed(tmp_path):
    env = fake_shell_host(tmp_path)
    fakebin = Path(env["PATH"].split(os.pathsep)[0])
    executable(fakebin/"curl", '#!/bin/sh\nwhile [ "$#" -gt 0 ]; do if [ "$1" = -o ]; then shift; out="$1"; fi; shift; done\nprintf "#!/bin/sh\\ntouch %s\\n" "$MARKER" > "$out"\n')
    marker = tmp_path/"installer-ran"
    env["MARKER"] = str(marker)
    result = shell("environment/scripts/00-install-miniforge.sh", env)
    assert result.returncode != 0 and "checksum mismatch" in result.stderr
    assert not marker.exists()
    assert not (Path(env["RAVEL_NATIVE_BUILD"])/"tools/miniforge3").exists()


def fake_conda(env):
    prefix = Path(env["RAVEL_NATIVE_BUILD"])/"tools/miniforge3"
    executable(prefix/"bin/python", f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    executable(prefix/"bin/conda", '#!/bin/sh\nif [ "$1" = --version ]; then echo "conda 26.5.3"; else printf "%s\\n" "$@"; fi\n')
    (prefix/"conda-meta").mkdir()
    return prefix


def test_environment_recipe_uses_exact_prefix_and_has_no_login_shell(tmp_path):
    env = fake_shell_host(tmp_path)
    prefix = fake_conda(env)
    result = shell("environment/scripts/01-create-env.sh", env, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert f"--prefix {prefix}/envs/mg5" in result.stdout
    assert "--override-channels" in result.stdout and "six numpy" in result.stdout
    assert not (prefix/"envs/mg5").exists()


def test_mixed_prefix_and_partial_environment_fail_closed(tmp_path):
    env = fake_shell_host(tmp_path)
    prefix = fake_conda(env)
    env["FAKE_BINARY_ARCH"] = "x86_64"
    result = shell("environment/scripts/01-create-env.sh", env, "--dry-run")
    assert result.returncode != 0 and "does not contain native arm64" in result.stderr
    env["FAKE_BINARY_ARCH"] = "arm64"
    (prefix/"envs/mg5").mkdir(parents=True)
    result = shell("environment/scripts/01-create-env.sh", env, "--dry-run")
    assert result.returncode != 0 and "already exists" in result.stderr


@pytest.mark.parametrize("script,kind,environment", [
    ("pythia-shower-build.sh", "shower", "rivet"),
    ("rjr-resolve-build.sh", "rjr", "recast"),
    ("restframes-native-build.sh", "restframes", "recast"),
])
def test_build_wrappers_work_with_bash3_empty_args_and_exact_prefix(tmp_path, script, kind, environment):
    env = fake_shell_host(tmp_path)
    prefix = fake_conda(env)
    executable(prefix/f"envs/{environment}/bin/python")
    result = shell("native/scripts/"+script, env, "--dry-run")
    assert result.returncode == 0, result.stderr
    args = result.stdout.splitlines()
    assert args[:3] == ["run", "--no-capture-output", "--prefix"]
    assert args[3] == str(prefix/f"envs/{environment}")
    assert "ravel.physics.native_build" in args and kind in args and "--dry-run" in args
    assert args[args.index("python")+1] == "-B"


def test_build_failure_preserves_existing_binary_and_scratch_is_removed(tmp_path):
    output = executable(tmp_path/"binary", "original bytes")
    plan = {"kind": "shower", "output": str(output), "architecture": "arm64",
            "commands": [["fake-cxx", "-o", "<staged-output>"]]}
    def fail(cmd, **kwargs):
        Path(cmd[-1]).write_text("partial output")
        raise subprocess.CalledProcessError(1, cmd)
    with pytest.raises(subprocess.CalledProcessError):
        native_build.execute_build(plan, replace=True, run=fail)
    assert output.read_text() == "original bytes"
    assert list(tmp_path.iterdir()) == [output]


def test_existing_output_refused_before_compiler(tmp_path):
    output = executable(tmp_path/"binary")
    with pytest.raises(doctor.ProbeError, match="Output exists"):
        native_build.execute_build({"kind": "shower", "output": str(output)}, run=lambda *a, **k: pytest.fail("compiled"))


@pytest.mark.parametrize("member", ["../escape", "/escape"])
def test_source_archive_traversal_rejected_before_extraction(tmp_path, member):
    archive = tmp_path/"bad.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo(member)
        info.size = 4
        handle.addfile(info, io.BytesIO(b"oops"))
    with pytest.raises(doctor.ProbeError, match="Unsafe"):
        native_build.extract_restframes(archive, tmp_path/"unpacked")
    assert not (tmp_path/"unpacked").exists()


def test_cli_empty_prefix_outputs_json_and_creates_nothing(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO/"src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    path = tmp_path/"absent"
    result = subprocess.run([sys.executable, "-m", "ravel.validation.native_doctor", "--json",
                             "--profile", "bootstrap", "--build-root", str(path)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    report = json.loads(result.stdout)
    assert result.returncode == 1 and report["read_only"] and not report["ready"]
    assert not path.exists()


def plan_fixture(tmp_path, monkeypatch):
    prefix = tmp_path/"environment with spaces"
    executable(prefix/"bin/python")
    executable(prefix/"bin/platform-clang++")
    for name in ["libpythia8.dylib", "libHepMC3.dylib", "libCore.so"]:
        executable(prefix/"lib"/name)
    sdk = tmp_path/"SDK"
    sdk.mkdir()
    monkeypatch.setenv("CONDA_PREFIX", str(prefix))
    monkeypatch.delenv("CXX", raising=False)
    monkeypatch.delenv("CONDA_SUBDIR", raising=False)
    def run(cmd):
        if cmd[0] == "file":
            return "Mach-O 64-bit dynamically linked shared library arm64"
        if cmd[0] == "xcrun":
            return str(sdk)
        if cmd[-1] == "-dumpmachine":
            return "arm64-apple-darwin24.0"
        if cmd[-1] == "--prefix":
            return str(prefix)
        if cmd[-1] == "--libdir":
            return str(prefix/"lib")
        if cmd[-1] == "--cxx":
            return str(prefix/"bin/platform-clang++")
        return f'-I"{prefix}/include" -L"{prefix}/lib" -lExample'
    return prefix, run


def test_shower_build_plan_is_read_only_and_preserves_argument_boundaries(tmp_path, monkeypatch):
    prefix, run = plan_fixture(tmp_path, monkeypatch)
    output = tmp_path/"new output/shower"
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    plan = native_build.build_plan("shower", prefix, output, host=HOST, run=run)
    command = plan["commands"][0]
    assert command[0] == str(prefix/"bin/platform-clang++")
    assert f"-I{prefix}/include" in command and "<staged-output>" in command
    assert plan["compiler_target"] == "arm64-apple-darwin24.0"
    assert before == sorted(str(p) for p in tmp_path.rglob("*"))


def test_rjr_accepts_macho_root_so_and_rejects_foreign_root_prefix(tmp_path, monkeypatch):
    prefix, run = plan_fixture(tmp_path, monkeypatch)
    rf = tmp_path/"Rest Frames"
    executable(rf/"lib/libRestFrames.dylib")
    executable(rf/"include/RestFrames/RestFrames.hh")
    plan = native_build.build_plan("rjr", prefix, tmp_path/"resolver", restframes=rf, host=HOST, run=run)
    assert f"-I{rf}/include" in plan["commands"][0]
    def foreign(cmd):
        return "/other/ROOT" if cmd[-1] == "--prefix" else run(cmd)
    with pytest.raises(doctor.ProbeError, match="different environment"):
        native_build.build_plan("rjr", prefix, tmp_path/"resolver", restframes=rf, host=HOST, run=foreign)


def test_restframes_plan_discovers_automake_without_fixed_version(tmp_path, monkeypatch):
    prefix, run = plan_fixture(tmp_path, monkeypatch)
    for version in ["1.9", "1.17"]:
        for name in ["config.guess", "config.sub"]:
            executable(prefix/f"share/automake-{version}"/name)
    build = tmp_path/"build"
    executable(build/"tools/simple-analysis-src/Ext_RestFrames/data/tarball")
    monkeypatch.setattr(native_build, "native_build_root", lambda: build)
    plan = native_build.build_plan("restframes", prefix, tmp_path/"restframes", host=HOST, run=run)
    assert plan["auxiliary"].endswith("automake-1.17")
    assert not (tmp_path/"restframes").exists()


@pytest.mark.parametrize("target", ["x86_64-apple-darwin24", "aarch64-linux-gnu", "unknown"])
def test_compiler_target_must_match_architecture_and_os(target):
    with pytest.raises(doctor.ProbeError, match="does not match"):
        doctor.compiler_target(["compiler"], "arm64", run=lambda _: target)


@pytest.mark.parametrize("flags", [["-arch", "x86_64"], ["--target=x86_64-apple-darwin"],
                                   ["-target", "aarch64-linux-gnu"], ["-arch"]])
def test_config_flags_cannot_silently_cross_compile(flags):
    with pytest.raises(doctor.ProbeError):
        native_build.validate_target_flags([["compiler", *flags]], "arm64")


def test_successful_explicit_replacement_is_staged(tmp_path, monkeypatch):
    output = executable(tmp_path/"binary", "original")
    plan = {"kind": "shower", "output": str(output), "architecture": "arm64",
            "commands": [["fake-cxx", "-o", "<staged-output>"]]}
    def compile_stub(cmd, **kwargs):
        assert output.read_text() == "original"
        executable(Path(cmd[-1]), "new binary")
    checked = []
    monkeypatch.setattr(native_build, "require_architecture", lambda path, arch: checked.append((path, arch)))
    native_build.execute_build(plan, replace=True, run=compile_stub)
    assert output.read_text() == "new binary"
    assert len(checked) == 1 and checked[0][1] == "arm64"
    assert list(tmp_path.iterdir()) == [output]


def test_path_alias_conflicts_fail_before_tools_are_run(tmp_path):
    env = fake_shell_host(tmp_path)
    env["BUILD_DIR"] = str(tmp_path/"different")
    result = shell("environment/scripts/00-install-miniforge.sh", env, "--dry-run")
    assert result.returncode != 0 and "disagree" in result.stderr
    assert not Path(env["BUILD_DIR"]).exists()


def test_installer_whitespace_prefix_fails_before_download(tmp_path):
    env = fake_shell_host(tmp_path)
    env["RAVEL_NATIVE_BUILD"] = str(tmp_path/"native with spaces")
    result = shell("environment/scripts/00-install-miniforge.sh", env, "--dry-run")
    assert result.returncode != 0 and "without whitespace" in result.stderr
    assert not Path(env["RAVEL_NATIVE_BUILD"]).exists()


def test_broken_conda_entry_point_is_not_reused(tmp_path):
    env = fake_shell_host(tmp_path)
    prefix = fake_conda(env)
    executable(prefix/"bin/conda", "#!/bin/sh\nexit 7\n")
    before = (prefix/"bin/conda").read_bytes()
    result = shell("environment/scripts/00-install-miniforge.sh", env, "--dry-run")
    assert result.returncode != 0 and "conda version probe failed" in result.stderr
    assert (prefix/"bin/conda").read_bytes() == before


def test_doctor_rejects_broken_conda_despite_native_python(tmp_path):
    env = fake_shell_host(tmp_path)
    prefix = fake_conda(env)
    def run(cmd):
        if cmd[0] == "file":
            return "Mach-O executable arm64"
        raise doctor.ProbeError("conda broken")
    report = doctor.diagnose(Path(env["RAVEL_NATIVE_BUILD"]), profile="bootstrap", host=HOST, run=run)
    assert not report["ready"]
    assert next(x for x in report["checks"] if x["name"] == "conda_version")["status"] == "fail"


@pytest.mark.parametrize("valid", [True, False])
def test_doctor_root_compiler_honors_explicit_cxx(tmp_path, monkeypatch, valid):
    build = tmp_path/"build"
    prefix = build/"tools/miniforge3"
    recast = prefix/"envs/recast"
    for directory in [prefix, recast]:
        executable(directory/"bin/python")
        (directory/"conda-meta").mkdir()
    for path in [prefix/"bin/conda", recast/"bin/root-config", recast/"bin/DelphesHepMC3",
                 recast/"lib/libDelphes.dylib", recast/"include/classes/DelphesClasses.h",
                 recast/"include/ExRootAnalysis/ExRootTreeReader.h"]:
        executable(path)
    compiler = executable(recast/"bin/explicit-compiler")
    monkeypatch.setenv("CXX", str(compiler) if valid else str(recast/"bin/missing-compiler"))
    monkeypatch.delenv("CONDA_SUBDIR", raising=False)
    def run(cmd):
        if cmd[0] == "file":
            return "Mach-O executable arm64"
        if cmd[0] == "xcrun":
            return str(tmp_path)
        if cmd[-1] == "--version":
            return "conda 26.5.3" if Path(cmd[0]).name == "conda" else "6.40.00"
        if cmd[-1] == "--prefix":
            return str(recast)
        if cmd[-1] == "--cxx":
            pytest.fail("CXX override was ignored")
        if cmd[-1] == "-dumpmachine":
            assert cmd[0] == str(compiler)
            return "arm64-apple-darwin24"
        if "-c" in cmd:
            assert "-B" in cmd and "-I" in cmd
            return '{"version":[3,12,0],"missing":[]}'
        pytest.fail(f"Unexpected probe: {cmd}")
    report = doctor.diagnose(build, profile="recast", host=HOST, run=run)
    root = next(x for x in report["checks"] if x["name"] == "root_configuration")
    assert (root["status"] == "pass") is valid
    assert report["ready"] is valid
