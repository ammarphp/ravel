"""Lint of native/setup/toolchain-manifest.json (schema 2) and native/setup/pdf-sets.json."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re

import pytest

from ravel.setup import manifest as mf

ROOT = Path(__file__).resolve().parents[2]
MANIFEST, CATALOG = mf.load(ROOT)
BYID = mf.by_id(MANIFEST)


def all_steps():
    for group in MANIFEST["groups"]:
        for step in group["steps"]:
            yield group, step


def test_manifest_and_catalogue_validate():
    assert MANIFEST["schema_version"] == 2
    mf.validate(MANIFEST, CATALOG)


def test_every_git_source_is_pinned_by_full_commit():
    rows = [(g["id"], s) for g, s in all_steps() if s["kind"] == "git"]
    # The floor counts the groups a release ships; a source tree also pins its withheld groups' sources.
    assert len([gid for gid, _ in rows if gid not in mf.unreleased_groups(MANIFEST)]) >= 18
    for gid, step in rows:
        assert re.fullmatch(r"[0-9a-f]{40}", step["commit"]), (gid, step["id"])
        assert step["url"].startswith("https://")


def test_every_download_has_a_digest_and_no_pin_is_left_blocked():
    for group, step in all_steps():
        if step["kind"] in ("archive", "download", "verify_file"):
            assert step.get("sha256") or step.get("md5"), (group["id"], step["id"])
            assert not step.get("blocked_reason"), (group["id"], step["id"])
    for asset in MANIFEST["miniforge"]["assets"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])


def test_every_container_image_is_pinned_by_digest():
    pulls = [s for _, s in all_steps() if s["kind"] == "container_pull"]
    assert {s["name"] for s in pulls} == {"simpleanalysis", "combine"}
    for step in pulls:
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", step["digest"])


def test_no_undefined_or_shell_variables_anywhere():
    used = mf.lint_unknown_variables(MANIFEST)
    assert used <= set(mf.ENGINE_VARIABLES)
    text = json.dumps(MANIFEST["groups"])
    assert not re.search(r"\$\{?[A-Z_]+", text)
    for name in ("FEYNRULES_EXPECTED_SHA256", "SARAH_EXPECTED_SHA256", "CHECKMATE_REVISION", "NYX_REVISION",
                 "PHASETRACER_REVISION", "FS_MODEL", "GENERATED_SOURCE_DIRECTORY"):
        assert name not in text


@pytest.mark.parametrize("mutation, message", [
    (lambda g: g["steps"].append({"id": "x", "kind": "git", "url": "https://a", "commit": "abc", "dest": "{P}/x"}),
     "40-hex"),
    (lambda g: g["steps"].append({"id": "x", "kind": "archive", "url": "https://a", "dest": "{P}/x"}), "sha256"),
    (lambda g: g["steps"].append({"id": "x", "kind": "command", "argv": ["make", "{UNDEFINED}"],
                                  "outputs": ["{P}/x"]}), "undefined variable"),
    (lambda g: g["steps"].append({"id": "x", "kind": "command", "argv": ["make", "$HOME"], "outputs": ["{P}/x"]}),
     "shell variable"),
    (lambda g: g["steps"].append({"id": "x", "kind": "command", "argv": ["bash", "-c", "make"],
                                  "outputs": ["{P}/x"]}), "inline shell"),
    (lambda g: g["steps"].append({"id": "x", "kind": "command", "argv": ["make"]}), "outputs"),
    (lambda g: g["steps"].append({"id": "x", "kind": "pip", "python": "{P}/p", "requirements": ["numpy"]}), "pinned"),
    (lambda g: g["steps"].append({"id": "x", "kind": "container_pull", "image": "a/b:latest",
                                  "digest": "sha256:" + "0" * 64}), "without tag"),
    (lambda g: g["depends_on"].append("nyx"), "dependencies"),
])
def test_validator_rejects_unpinned_or_undefined_steps(mutation, message):
    document = copy.deepcopy(MANIFEST)
    mutation(document["groups"][2])
    with pytest.raises(mf.ManifestError, match=message):
        mf.validate(document, CATALOG)


def test_validator_rejects_bad_profiles_and_pairs():
    document = copy.deepcopy(MANIFEST)
    document["profiles"]["site"]["groups"].append("nonexistent")
    with pytest.raises(mf.ManifestError, match="unknown group"):
        mf.validate(document)
    document = copy.deepcopy(MANIFEST)
    document["incompatible_path_bindings"].append(["rivet", "no-such-check"])
    with pytest.raises(mf.ManifestError, match="incompatible"):
        mf.validate(document)


def test_validator_requires_the_site_procedure_of_a_tester_qualification():
    for change in (lambda q: q.pop("procedure"), lambda q: q.update(procedure="  "),
                   lambda q: q.update(procedure="first line\nsecond line")):
        broken = copy.deepcopy(MANIFEST)
        change(next(g for g in broken["groups"] if g["id"] == "site-access")["qualification"])
        with pytest.raises(mf.ManifestError, match="site procedure"):
            mf.validate(broken, CATALOG)


def test_required_profiles_exist_and_close_over_dependencies():
    assert set(MANIFEST['profiles']) == {'site'}
    for name in (None, 'site'):
        ordered = mf.profile_groups(MANIFEST, name)
        for index, gid in enumerate(ordered):
            assert set(BYID[gid]['depends_on']) <= set(ordered[:index]), (name, gid)
    assert {'python-host', 'site-root-wms', 'site-access', 'root-combine'} <= set(mf.profile_groups(MANIFEST, 'site'))


def test_every_group_has_a_check_on_every_platform_it_installs_on():
    for group in MANIFEST["groups"]:
        for platform in mf.PLATFORMS:
            if mf.route_for(group, platform) in ("native", "container"):
                assert [c for c in group["checks"] if mf.applies(c, platform)], (group["id"], platform)


def test_remote_routes_on_macos_are_the_site_only_groups():
    remote = {g["id"] for g in MANIFEST["groups"] if mf.route_for(g, "macos-arm64") == "remote"}
    assert remote == {"nyx", "site-root-wms", "site-access"}
    assert all(mf.route_for(BYID[g], "linux-x86_64") == "native" for g in remote)


def test_madgraph_two_and_three_side_by_side_with_lhapdf():
    steps = {s["id"]: s for s in BYID["madgraph"]["steps"]}
    assert steps["mg5-source"]["commit"] == "eb76cab72b8d44aac7162ac7221ac08a4384a169"
    assert steps["mg5-3-source"]["tag"].startswith("v3.")
    assert steps["mg5-3-source"]["dest"] != steps["mg5-source"]["dest"]
    for env in ("mg5-env", "mg5-3-env"):
        assert "lhapdf=6.5.6" in steps[env]["specs"]
    assert steps["mg5-options"]["values"]["lhapdf_py3"] == "{ENVS}/mg5/bin/lhapdf-config"
    interface = {s["id"]: s for s in BYID["mg5-py8-interface"]["steps"]}
    assert interface["py8-interface-source"]["url"].endswith("MG5aMC_PY8_interface")
    assert interface["mg5-options"]["values"]["mg5amc_py8_interface_path"] == "{TOOLS}/MG5aMC_PY8_interface"


def test_previous_false_readiness_checks_are_fixed():
    checks = {c["id"]: c for g in MANIFEST["groups"] for c in g["checks"]}
    assert checks["rivet-build"]["path"].endswith("/rivet/bin/rivet-build")
    assert "rivet-buildplugin" not in json.dumps(MANIFEST)
    assert checks["pythia83-config"]["path"] == "{ENVS}/rivet/bin/pythia8-config"
    assert checks["restframes"]["path"] == "{TOOLS}/restframes-native"
    assert checks["contur"]["probe"]["expect"] == "3.1.5"
    required = (ROOT / "environment/python/requirements-smodels.txt").read_text()
    assert f"smodels=={checks['smodels-python']['probe']['expect']}" in required
    assert "3d3ccb52188acc86940f3881c98251ea904bb9e0" not in json.dumps(MANIFEST)


def test_symbolic_sources_are_pinned_and_licensed_kernel_is_never_activated():
    steps = {s["id"]: s for s in BYID["wolfram"]["steps"]}
    assert steps["feynrules"]["sha256"] == "85eddac7b5b61eac772c93df93a0c44bc34f531069985a719fe454f0a54afc81"
    assert steps["feynrules"]["size"] == 603115
    assert steps["kernel"]["kind"] == "manual"
    text = json.dumps(MANIFEST) + "".join(p.read_text() for p in (ROOT / "native/setup/recipes").glob("*.sh"))
    assert "-activate" not in text.replace("`wolframscript -activate`", "")
    assert "init.m" not in text.replace("no init.m", "")


def test_gpl_tools_are_fetched_externally_with_licences_recorded():
    licences = {l["component"]: l["spdx"] for g in MANIFEST["groups"] for l in g.get("licenses", [])}
    for component in ("HEPTAPOD", "FeynCalc", "AgentRivet"):
        assert any(component in key for key in licences), component
    agents = {s["id"]: s for s in BYID["agent-sources"]["steps"]}
    assert agents["agentrivet"]["commit"] == "e4d12eccb6aee546d993481c75576c0df4e2b037"
    vendored = list((ROOT / "src/ravel").rglob("*")) + list((ROOT / "native").rglob("*"))
    assert not any(p.name in ("FeynCalc.m", "nda_tool.py", "mcfm.f90") for p in vendored)


def test_container_runtime_stays_inside_the_prefix():
    steps = {s["id"]: s for s in BYID["container-runtime"]["steps"]}
    assert steps["podman-arm64"]["sha256"] == "2379bcb0bf320df5deccf84115337109d3f9051f7d017948ee68a92ce932e798"
    template = (ROOT / "native/setup/wrappers/ravel-podman.sh.in").read_text()
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "CONTAINERS_CONF"):
        assert variable + '="@CONTAINERS@' in template
    assert "rosetta" in steps and steps["rosetta"]["platforms"] == ["macos-arm64"]
    assert MANIFEST["container_build"]["module"] == "ravel.execution_backend"


def test_podman_wrapper_keeps_the_machine_socket_path_short():
    template = (ROOT / "native/setup/wrappers/ravel-podman.sh.in").read_text()
    # podman binds a unix socket under $HOME/.podman; macOS limits that path to 103 bytes
    assert 'if [ "${#HOME}" -gt' in template
    assert 'export HOME="$short_home"' in template


def test_install_shim_pins_the_same_miniforge():
    shim = (ROOT / "scripts/setup/install.sh").read_text()
    assert "MINIFORGE_VERSION=" + MANIFEST["miniforge"]["version"] in shim
    for asset in MANIFEST["miniforge"]["assets"].values():
        assert asset["sha256"] in shim and asset["name"].split(MANIFEST["miniforge"]["version"])[1] in shim


def test_pdf_catalogue_contains_the_required_sets():
    sets = {s["name"]: s for s in CATALOG["sets"]}
    expected = {"NNPDF30_nlo_as_0118": 260000, "LUXlep-NNPDF31_nlo_as_0118_luxqed": 82400, "cteq6l1": 10042,
                "NNPDF23_lo_as_0130_qed": 247000, "NNPDF23_nlo_as_0119": 230000, "CT14lo": 13200, "CT18NNLO": 14000}
    assert {k: v["lhaid"] for k, v in sets.items()} == expected
    lux = sets["LUXlep-NNPDF31_nlo_as_0118_luxqed"]
    assert lux["sha256"] == "fcb690fdd260720960f755e1143af0113f2b924c65391946d3321beb64359025"
    assert lux["digest_status"] == "verified"
    assert all(s["size"] > 100000 for s in sets.values())


def test_every_lhapdf_id_named_by_code_cards_or_tasks_is_installed():
    ids = {s["lhaid"] for s in CATALOG["sets"]}
    pattern = re.compile(r"(?:lhaid['\"]?\s*[:=]\s*['\"]?|PDF_ID\s*=\s*)(\d{4,6})", re.I)
    found = {}
    roots = [ROOT / "src/ravel", ROOT / "benchmarks/scoped", ROOT / "native"]
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in (".py", ".json", ".dat", ".txt", ".toml") or "data/workflow" in str(path):
                continue
            if path.name == "pdf-sets.json":
                continue
            for match in pattern.finditer(path.read_text(errors="replace")):
                found.setdefault(int(match.group(1)), str(path.relative_to(ROOT)))
    assert found, "the scanner should see at least the native generation default"
    missing = {k: v for k, v in found.items() if k not in ids}
    assert not missing, missing


def test_operations_name_only_known_modes_and_groups():
    import ast
    module = ast.parse((ROOT / "src/ravel/workflow/science.py").read_text())
    modes = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "MODES" for t in n.targets))
    # The scoped adapters are offered through their operation signatures rather than the science registry.
    signatures = json.loads((ROOT / "src/ravel/data/operation_signatures.json").read_text())["operations"]
    scoped = {s["implementation"]["mode"] for s in signatures.values()
              if s.get("implementation", {}).get("kind") == "scoped-adapter"}
    listed = [row["mode"] for row in MANIFEST["operations"]]
    assert len(listed) == len(set(listed))
    assert set(listed) <= set(modes) | scoped and scoped <= set(listed)
    for row in MANIFEST["operations"]:
        assert set(row["groups"]) <= set(BYID)


def test_recipes_and_wrappers_referenced_by_steps_exist():
    for group, step in all_steps():
        if step["kind"] == "command" and step["argv"][0] == "bash":
            script = step["argv"][1].replace("{REPO}/", "")
            assert (ROOT / script).is_file(), script
        if step["kind"] == "wrapper":
            assert (ROOT / "native/setup/wrappers" / step["template"]).is_file()
        for relative in step.get("inputs", []):
            assert (ROOT / relative).is_file(), relative


def test_simpleanalysis_source_fetches_its_restframes_submodule():
    step = next(s for s in BYID["restframes"]["steps"] if s["id"] == "simpleanalysis-source")
    assert "Ext_RestFrames" in step.get("submodules", [])


def test_herwig_environment_carries_its_own_readline():
    step = next(s for s in BYID["contur"]["steps"] if s["id"] == "herwig-env")
    assert any(spec.split("=")[0] == "readline" for spec in step["specs"])


def test_spheno_recipe_names_the_compiler_the_makefile_recognises():
    recipe = (ROOT / "native/setup/recipes/build-spheno.sh").read_text()
    assert re.search(r"^make .* F90=gfortran\s*$", recipe, re.M)


def test_flexiblesusy_recipe_finds_a_kernel_when_wolframscript_is_a_launcher():
    recipe = (ROOT / "native/setup/recipes/build-flexiblesusy.sh").read_text()
    assert "realpath" in recipe and "/Applications/Wolfram*.app/Contents/MacOS" in recipe
    assert re.search(r"createmodel .*--with-math-cmd=", recipe)
    assert "--sarah-model" not in recipe  # each model file names its own SARAH model
    assert "--with-sarah-dir" not in recipe  # this FlexibleSUSY release has no such option
    assert "-initfile" in recipe and "PrependTo[$Path" in recipe


def test_easyscan_environment_pins_the_eigen_series_its_engines_accept():
    step = next(s for s in BYID["easyscan"]["steps"] if s["id"] == "easyscan-env")
    assert "eigen=3.4.0" in step["specs"]


def test_pip_step_puts_the_interpreter_folder_first_on_the_build_path(tmp_path):
    from ravel.setup import steps

    seen = {}

    class Runner:
        def run(self, argv, *, cwd=None, env=None, log=None):
            seen["env"], seen["argv"] = env, argv
            return 0

    ctx = steps.Context(prefix=tmp_path, repo=tmp_path, platform_key="x", values={}, runner=Runner(), fetcher=None,
                        manifest=None, catalog=None, base_env={"PATH": "/usr/bin"})
    steps._pip({"python": "/env/bin/python", "requirements": ["/src/pkg"], "options": ["--no-build-isolation"]}, ctx)
    assert seen["env"]["PATH"] == "/env/bin:/usr/bin"


def test_recast_base_builds_a_pinned_fastjet_that_ships_fastjet_config():
    steps = {s["id"]: s for s in BYID["recast-base"]["steps"]}
    src = steps["fastjet-source"]
    assert src["kind"] == "archive" and re.fullmatch(r"[0-9a-f]{64}", src["sha256"])
    build = steps["fastjet-build"]
    assert build["kind"] == "command"
    assert (ROOT / "native/setup/recipes/build-fastjet.sh").is_file()
    check = next(c for c in BYID["recast-base"]["checks"] if c["id"] == "fastjet-config")
    assert check["path"] == "{TOOLS}/fastjet-3.5.2/bin/fastjet-config"
    assert check["probe"]["expect"] == "3.5.2"
    assert check["path"] in build["outputs"]


def test_spectrum_env_pins_a_boost_whose_odeint_compiles_with_eigen_arrays_under_clang_22():
    step = next(s for s in BYID["spectrum"]["steps"] if s["kind"] == "conda_env")
    assert "libboost-devel=1.88.*" in step["specs"]
    assert not any(spec.startswith("boost-cpp=1.85") for spec in step["specs"])


def test_feyncalc_pin_is_past_the_release_that_aborts_in_wolfram_15():
    wolfram = BYID["wolfram"]
    step = next(s for s in wolfram["steps"] if s["id"] == "feyncalc")
    check = next(c for c in wolfram["checks"] if c["id"] == "feyncalc")
    assert step["commit"] == check["probe"]["expect"] == "1ee480093293a01a82b3e365d026808f1d4e1c17"
    assert "fe6645114a794c2aed96d4f6c3512ef1b1affac6" not in json.dumps(wolfram)


def test_feynarts_patch_sets_the_feyncalc_context_directory_not_a_global_symbol():
    text = (ROOT / "native/setup/recipes/patch-feynarts.sh").read_text()
    assert 'FeynCalc\\`\\$FeynArtsDirectory = ' in text
    assert '\n\\$FeynArtsDirectory' not in text


def test_easyscan_builds_a_pinned_alglib_for_phasetracer():
    group = BYID["easyscan"]
    steps = {s["id"]: s for s in group["steps"]}
    src = steps["alglib-source"]
    assert src["kind"] == "archive" and re.fullmatch(r"[0-9a-f]{64}", src["sha256"])
    build = steps["alglib-build"]
    assert (ROOT / "native/setup/recipes/build-alglib.sh").is_file()
    engines = steps["engines"]
    assert "--alglib" in engines["argv"] and "{TOOLS}/alglib-3.20.0" in engines["argv"]
    assert "{TOOLS}/alglib-3.20.0/lib/libalglib.a" in build["outputs"]
    assert any(l["component"] == "ALGLIB" and l["spdx"].startswith("GPL") for l in group["licenses"])
    ids = [s["id"] for s in group["steps"]]
    assert ids.index("alglib-build") < ids.index("engines")


@pytest.mark.parametrize("recipe, product", [("build-fastjet.sh", "bin/fastjet-config"), ("build-alglib.sh", "lib/libalglib.a")])
def test_source_build_recipes_are_no_ops_when_the_product_exists(tmp_path, recipe, product):
    import subprocess
    out = tmp_path / "out"
    (out / product).parent.mkdir(parents=True)
    (out / product).write_text("built")
    done = subprocess.run(["bash", str(ROOT / "native/setup/recipes" / recipe), "--src", str(tmp_path / "none"),
                           "--env", str(tmp_path / "none"), "--out", str(out)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_checkmate_recipe_disables_libcxx_availability_markup_on_macos():
    text = (ROOT / "native/setup/recipes/build-checkmate.sh").read_text()
    assert "-D_LIBCPP_DISABLE_AVAILABILITY" in text
    assert text.index("-D_LIBCPP_DISABLE_AVAILABILITY") < text.index("./configure")


def test_checkmate_recipe_passes_cxx_to_the_delphes_make_because_root_arch_file_overrides_the_environment():
    text = (ROOT / "native/setup/recipes/build-checkmate.sh").read_text()
    assert 'make -j"$JOBS" CXX="$CXX' in text


def test_checkmate_recipe_puts_the_pythia_82_headers_ahead_of_the_environment_pythia_83_headers():
    text = (ROOT / "native/setup/recipes/build-checkmate.sh").read_text()
    assert 'CXX="$CXX -I$PY8/include"' in text and "-lpythia8" in text


def test_checkmate_recipe_uses_the_environment_clang_and_the_root_cxx_standard_on_macos():
    text = (ROOT / "native/setup/recipes/build-checkmate.sh").read_text()
    assert '"$ENV/bin/clang++"' in text and "-std=c++20" in text and "-std=gnu++11" in text


def test_checkmate_recipe_adds_the_onnx_runtime_header_directory():
    text = (ROOT / "native/setup/recipes/build-checkmate.sh").read_text()
    assert "include/onnxruntime/core/session" in text


def test_checkmate_recipe_downgrades_the_narrowing_error_clang_raises_for_two_analyses():
    assert "-Wno-c++11-narrowing" in (ROOT / "native/setup/recipes/build-checkmate.sh").read_text()


def test_checkmate_recipe_links_the_pythia_82_library_ahead_of_the_environment_pythia_83_library():
    assert '-L"$PY8/lib"' in (ROOT / "native/setup/recipes/build-checkmate.sh").read_text()


def _nyx_recipe_world(tmp_path, *, mpi=True):
    """Stub build tools that record their command lines; the make stub leaves the Lyman-alpha executable."""
    import os
    import shutil
    stubs, env = tmp_path / "stubs", tmp_path / "host-build"
    log = tmp_path / "calls.log"
    for folder, names in ((stubs, ("mpicxx", "mpicc") if mpi else ()), (env / "bin", ("cmake", "make"))):
        folder.mkdir(parents=True)
        for name in names:
            tool = folder / name
            tool.write_text('#!/bin/sh\necho "$0 $*" >> "$NYX_STUB_LOG"\n'
                            'case "$*" in *Exec/LyA*) for a in "$@"; do last="$a"; [ "$a" = -C ] && take=1 && continue; '
                            '[ "${take:-}" = 1 ] && dir="$a" && take=; done; : > "$dir/Nyx3d.gnu.TPROF.MPI.OMP.ex";; esac\n')
            tool.chmod(0o755)
    for name in ("dirname", "mkdir", "cp", "mv", "uname", "rm"):
        os.symlink(shutil.which(name), stubs / name)
    (tmp_path / "Nyx/Exec/LyA").mkdir(parents=True)
    out = tmp_path / "tools/nyx-build"
    out.parent.mkdir()
    argv = [shutil.which("bash"), str(ROOT / "native/setup/recipes/build-nyx.sh"), "--env", str(env),
            "--amrex", str(tmp_path / "amrex"), "--nyx", str(tmp_path / "Nyx"), "--sundials", str(tmp_path / "sundials"),
            "--out", str(out), "--jobs", "3"]
    return argv, {"PATH": str(stubs), "NYX_STUB_LOG": str(log)}, log, out, env


def test_nyx_recipe_builds_shared_sundials_and_gives_the_executable_a_run_path_to_their_final_place(tmp_path):
    """The Nyx makefile names libsundials_core ahead of the solvers that need it. That order resolves
    only against shared libraries, and the build directory is renamed after the link."""
    import subprocess
    argv, environ, log, out, env = _nyx_recipe_world(tmp_path)
    done = subprocess.run(argv, env=environ, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    configure, build, nyx = log.read_text().splitlines()
    assert configure.startswith(str(env / "bin/cmake") + " -S ") and build.startswith(str(env / "bin/cmake") + " --build ")
    assert " -DBUILD_SHARED_LIBS=ON " in configure + " " and " -DBUILD_STATIC_LIBS=OFF " in configure + " "
    assert "-DBUILD_SHARED_LIBS=OFF" not in configure
    assert f"-DCMAKE_C_COMPILER={tmp_path / 'stubs/mpicc'}" in configure and "-DCMAKE_INSTALL_RPATH=$ORIGIN" in configure
    assert f"-DCMAKE_MAKE_PROGRAM={env / 'bin/make'}" in configure
    assert nyx.startswith(str(env / "bin/make") + " -C ") and " -j3 " in nyx
    assert f"XTRALIBS=-Wl,-rpath,{out}/sundials/lib" in nyx.split()
    assert not [word for word in nyx.split() if word.startswith(("LDFLAGS=", "LIBRARIES="))], "these replace the makefile's own"
    assert (out / "bin/Nyx3d.gnu.MPI.OMP.ex").is_file()
    assert not list(out.parent.glob("nyx-build.partial-*"))


def test_nyx_recipe_stops_before_building_when_no_mpi_compiler_is_on_the_path(tmp_path):
    import subprocess
    argv, environ, log, out, _ = _nyx_recipe_world(tmp_path, mpi=False)
    done = subprocess.run(argv, env=environ, capture_output=True, text=True)
    assert done.returncode == 1 and "mpicxx" in done.stderr and "MPI module" in done.stderr
    assert not log.exists() and not out.exists() and not list(out.parent.glob("nyx-build.partial-*"))


def test_nyx_group_waits_for_the_site_mpi_and_builds_with_the_installed_cmake():
    steps = BYID["nyx"]["steps"]
    ids = [step["id"] for step in steps]
    mpi, build = steps[ids.index("mpi")], steps[ids.index("build")]
    assert ids.index("mpi") < ids.index("build")
    assert mpi["kind"] == "manual" and mpi["probe"]["argv"] == ["mpicxx", "--version"]
    assert "MPI" in mpi["instruction"] and "rerun the installer" in mpi["instruction"]
    assert build["argv"][build["argv"].index("--env") + 1] == "{ENVS}/host-build"
    assert "compiler-bootstrap" in BYID["nyx"]["depends_on"]
