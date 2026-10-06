"""Explicit macOS native helper builds; --dry-run only probes prerequisites.

Invoke through native/scripts/*-build.sh to activate the exact conda prefix.
Compiler output is staged, so a failed build never replaces a working binary.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import tempfile

from ravel.paths import native_binary, native_build_root, require_repository_root
from ravel.validation.native_doctor import (ProbeError, compiler_command, compiler_target, host_info,
                                             probe, require_architecture)


def flags(config, *options, run=probe):
    result = shlex.split(run([str(config), *options]))
    if not result:
        raise ProbeError(f"Empty compiler/linker flags from {config}")
    return result


def build_plan(kind, prefix, output, *, restframes=None, run=probe, host=None):
    host = host_info(run=run) if host is None else host
    if not host["supported"]:
        raise ProbeError("; ".join(host["errors"]))
    prefix, output = Path(prefix).resolve(), Path(output).absolute()
    if Path(os.environ.get("CONDA_PREFIX", "")).resolve() != prefix:
        raise ProbeError(f"Activate the exact environment with conda run --prefix {prefix}")
    expected_subdir = "osx-arm64" if host["native_arch"] == "arm64" else "osx-64"
    if os.environ.get("CONDA_SUBDIR", expected_subdir) != expected_subdir:
        raise ProbeError("CONDA_SUBDIR conflicts with the native architecture")
    require_architecture(prefix/"bin/python", host["native_arch"], run=run)
    sdk = Path(run(["xcrun", "--show-sdk-path"]))
    if not sdk.is_dir():
        raise ProbeError(f"Missing macOS SDK: {sdk}; install/select Command Line Tools outside this helper")
    repo = require_repository_root()
    plan = {"kind": kind, "prefix": str(prefix), "output": str(output),
            "architecture": host["native_arch"], "sdk": str(sdk), "commands": [],
            "existing_output": output.exists() or output.is_symlink(), "dry_run": True}
    if kind == "shower":
        compiler = compiler_command(prefix)
        for library in ["libpythia8.dylib", "libHepMC3.dylib"]:
            require_architecture(prefix/"lib"/library, host["native_arch"], run=run)
        compile_flags = flags(prefix/"bin/pythia8-config", "--cxxflags", "--libs", run=run)
        compile_flags += flags(prefix/"bin/HepMC3-config", "--cflags", "--libs", run=run)
        plan["commands"] = [[*compiler, str(repo/"native/src/pythia_shower.cc"),
                              *compile_flags, f"-Wl,-rpath,{prefix/'lib'}", "-o", "<staged-output>"]]
    else:
        config = prefix/"bin/root-config"
        if Path(run([str(config), "--prefix"])).resolve() != prefix:
            raise ProbeError("root-config belongs to a different environment")
        compiler = compiler_command(prefix, os.environ.get("CXX") or run([str(config), "--cxx"]))
        cflags = flags(config, "--cflags", run=run)
        libs = flags(config, "--libs", run=run)
        root_libdir = Path(run([str(config), "--libdir"])).resolve()
        if not root_libdir.is_relative_to(prefix):
            raise ProbeError("ROOT libraries resolve outside the selected environment")
        # ROOT may use .so on macOS even though the file contains Mach-O code.
        core = next((root_libdir/name for name in ["libCore.dylib", "libCore.so"]
                     if (root_libdir/name).is_file()), root_libdir/"libCore.dylib")
        require_architecture(core, host["native_arch"], run=run)
        if kind == "rjr":
            restframes = Path(restframes).resolve()
            require_architecture(restframes/"lib/libRestFrames.dylib", host["native_arch"], run=run)
            if not (restframes/"include/RestFrames/RestFrames.hh").is_file():
                raise ProbeError(f"Missing RestFrames headers: {restframes}")
            plan["commands"] = [[*compiler, *cflags, f"-I{restframes/'include'}",
                                  str(repo/"native/src/rjr_resolve.cc"), f"-L{restframes/'lib'}", "-lRestFrames",
                                  *libs, f"-Wl,-rpath,{restframes/'lib'}", f"-Wl,-rpath,{prefix/'lib'}",
                                  "-o", "<staged-output>"]]
        else:
            tarball = native_build_root()/"tools/simple-analysis-src/Ext_RestFrames/data/tarball"
            if not tarball.is_file():
                raise ProbeError(f"Missing recorded RestFrames source tarball: {tarball}")
            candidates = sorted((prefix/"share").glob("automake-*/config.guess"))
            candidates = [p.parent for p in candidates if p.with_name("config.sub").is_file()]
            if not candidates:
                raise ProbeError(f"No automake config.guess/config.sub pair found under {prefix/'share'}")
            # The tools supply platform detection, not generated physics code.
            auxiliary = max(candidates, key=lambda p: tuple(int(n) for n in re_digits(p.name)))
            plan.update(tarball=str(tarball), auxiliary=str(auxiliary), compiler=compiler,
                        cflags=cflags, libs=libs)
            plan["commands"] = [["<extracted-source>/configure", f"--prefix={output}",
                                  "--enable-shared", "--disable-static", f"--with-rootsys={prefix}"],
                                 [*compiler, *cflags, "-fPIC", "-I./inc", "-c", "<each-source.cc>", "-o", "<object>"],
                                 [*compiler, "-dynamiclib", "-install_name", str(output/"lib/libRestFrames.dylib"),
                                  "-o", "<staged-library>", "<objects>", *libs]]
    # Probe the selected compiler and its default target without compiling anything.
    plan["compiler_target"] = compiler_target(compiler, host["native_arch"], run=run)
    validate_target_flags(plan["commands"], host["native_arch"])
    return plan


def validate_target_flags(commands, arch):
    for command in commands:
        for i, value in enumerate(command):
            if value == "-arch" and (i+1 == len(command) or command[i+1] != arch):
                raise ProbeError(f"Compiler flags request a different architecture from {arch}")
            if value.startswith(("--target=", "-target=")):
                target = value.split("=", 1)[1]
                compiler_target([], arch, run=lambda _: target)
            if value in {"--target", "-target"}:
                if i+1 == len(command):
                    raise ProbeError("Missing compiler target")
                compiler_target([], arch, run=lambda _: command[i+1])


def re_digits(value):
    import re
    return re.findall(r"\d+", value)


def extract_restframes(tarball, directory):
    """Reject traversal and links before extracting upstream source into scratch."""
    directory = Path(directory).resolve()
    with tarfile.open(tarball, "r:gz") as archive:
        for member in archive.getmembers():
            target = (directory/member.name).resolve()
            if not target.is_relative_to(directory) or not (member.isdir() or member.isfile()):
                raise ProbeError(f"Unsafe source archive member: {member.name}")
        archive.extractall(directory)
    source = directory/"RestFrames-1.0.1"
    if not (source/"configure").is_file():
        raise ProbeError("Expected RestFrames-1.0.1/configure in the source archive")
    return source


def execute_build(plan, *, replace=False, run=subprocess.run):
    output = Path(plan["output"])
    # Recheck filesystem state after planning. Never replace an entire installed library tree.
    if output.exists() or output.is_symlink():
        if not replace or plan["kind"] == "restframes" or not output.is_file() or output.is_symlink():
            raise ProbeError(f"Output exists: {output}; use a new destination (binaries allow explicit --replace)")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ravel-build-", dir=output.parent) as work:
        work = Path(work)
        staged = work/"result"
        if plan["kind"] != "restframes":
            command = [str(staged) if part == "<staged-output>" else part for part in plan["commands"][0]]
            run(command, check=True)
            if not staged.is_file() or not os.access(staged, os.X_OK):
                raise ProbeError("Compiler did not produce an executable; existing output preserved")
            require_architecture(staged, plan["architecture"])
        else:
            source = extract_restframes(plan["tarball"], work)
            for destination in [source, source/"config"]:
                if destination.is_dir():
                    for name in ["config.guess", "config.sub"]:
                        shutil.copy2(Path(plan["auxiliary"])/name, destination/name)
            run([str(source/"configure"), f"--prefix={output}", "--enable-shared", "--disable-static",
                 f"--with-rootsys={plan['prefix']}"], check=True, cwd=source)
            (staged/"lib").mkdir(parents=True)
            objects = []
            for filename in sorted((source/"src").glob("*.cc")):
                if filename.stem == "libRestFrames_rdict":
                    continue
                obj = work/(filename.stem+".o")
                run([*plan["compiler"], *plan["cflags"], "-fPIC", "-I./inc", "-c", str(filename), "-o", str(obj)],
                    check=True, cwd=source)
                objects.append(str(obj))
            if not objects:
                raise ProbeError("No RestFrames sources found")
            library = staged/"lib/libRestFrames.dylib"
            run([*plan["compiler"], "-dynamiclib", "-install_name", str(output/"lib/libRestFrames.dylib"),
                 "-o", str(library), *objects, *plan["libs"]], check=True)
            require_architecture(library, plan["architecture"])
            shutil.copytree(source/"inc/RestFrames", staged/"include/RestFrames")
        # For a new destination use an exclusive link/rename boundary: no concurrent
        # builder may silently overwrite it. Directory builds require an absent target.
        if plan["kind"] == "restframes":
            if output.exists() or output.is_symlink():
                raise ProbeError(f"Output appeared during build: {output}")
            staged.rename(output)
        elif replace:
            if output.is_symlink() or (output.exists() and not output.is_file()):
                raise ProbeError(f"Output changed during build: {output}")
            os.replace(staged, output)
        else:
            os.link(staged, output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["shower", "rjr", "restframes"])
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--restframes", type=Path, default=native_build_root()/"tools/restframes-native")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true", help="replace one existing binary only after a successful build")
    args = parser.parse_args(argv)
    output = args.out or {"shower": native_binary("pythia_shower"), "rjr": native_binary("rjr_resolve"),
                          "restframes": native_build_root()/"tools/restframes-native"}[args.kind]
    try:
        plan = build_plan(args.kind, args.prefix, output, restframes=args.restframes)
        if args.dry_run:
            print(json.dumps(plan, indent=2))
        else:
            print(f"Built: {execute_build(plan, replace=args.replace)}")
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        parser.exit(2, f"native_build: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
