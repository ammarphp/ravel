"""Portability and error-boundary checks for the small public command surface.

Set RAVEL_TEST_WHEEL to a freshly built wheel for the isolated payload regression.
The ordinary suite does not need a build backend or download packages.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ravel import cli, validate_task_contract
from ravel.resources import FAST_RUN, payload_files, resource_root
DATA_ROOT = resource_root()
from ravel.evidence_layout import public_path, resolve


def contract():
    return {"schema_version": 1, "prompt": "Survey published analyses", "task_mode": "survey",
            "detector_mode": "particle-level", "stat_mode": "none-survey",
            "required_user_inputs": [], "assumptions": [], "compute_plan": "none",
            "approval_required": True}


def test_validation_api_and_relative_file_work_from_unrelated_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    Path("contract.json").write_text(json.dumps(contract()))
    assert validate_task_contract(contract()) == []
    assert cli.main(["validate", "contract.json", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "valid": True, "errors": [], "compute_authorized": False}


def test_validation_distinguishes_bad_contract_from_unreadable_input(tmp_path, capsys):
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({**contract(), "approval_required": False}))
    assert cli.main(["validate", str(invalid), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["valid"] is False
    invalid.write_bytes(b"\xff")
    assert cli.main(["validate", str(invalid), "--json"]) == 2
    assert "cannot read" in json.loads(capsys.readouterr().out)["errors"][0]


@pytest.mark.parametrize('suffix,code', [
    (', "approval_required": false, "approval_required": true}', 2),
    (', "targets": {"lumi_fb": NaN}}', 2),
    (', "targets": {"lumi_fb": Infinity}}', 2),
    (', "targets": {"lumi_fb": 1e999}}', 1),
])
def test_cli_preserves_strict_loader_and_numeric_contract_rules(tmp_path, capsys, suffix, code):
    path = tmp_path / 'ambiguous.json'
    path.write_text(json.dumps(contract())[:-1] + suffix)
    assert cli.main(['validate', str(path), '--json']) == code
    result = json.loads(capsys.readouterr().out)
    assert result['valid'] is False and result['compute_authorized'] is False
    assert result['errors']


def test_replay_refuses_existing_output_and_preserves_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.importlib.metadata, "version", lambda name: "test")
    protected = tmp_path / "prior-run"
    protected.mkdir()
    (protected / "evidence.json").write_text("do not overwrite")
    assert cli.main(["replay", "--out", str(protected)]) == 2
    assert (protected / "evidence.json").read_text() == "do not overwrite"
    assert "exists" in capsys.readouterr().err.lower()


def test_replay_missing_dependency_leaves_no_partial_output(tmp_path, monkeypatch, capsys):
    def missing(name):
        raise cli.importlib.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(cli.importlib.metadata, "version", missing)
    output = tmp_path / "replay"
    assert cli.main(["replay", "--out", str(output)]) == 2
    assert not output.exists()
    assert "Replay dependencies are missing" in capsys.readouterr().err


def test_audit_outside_checkout_explains_required_source(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["audit", "--root", str(tmp_path)]) == 2
    assert "ravel audit --root PATH" in capsys.readouterr().err


def test_source_payload_selection_excludes_other_runs_and_runtime_droppings():
    files = payload_files(DATA_ROOT)
    assert len(files) > 6
    assert all("__pycache__" not in path and "/logs/" not in path and "/.work/" not in path
               for path in files)
    run_prefix = public_path(FAST_RUN, DATA_ROOT) + "/"
    run_paths = [path for path in files if path.startswith(run_prefix)]
    assert run_paths
    assert all(not path.endswith(".py") for path in files)
    assert not any(path.startswith("trial-runs/") for path in files)


def test_explicit_replay_interpreter_ignores_an_existing_conda_binary(tmp_path):
    spec = importlib.util.spec_from_file_location("ravel.validation.benchmark", REPO / "src/ravel/validation/benchmark.py")
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    fake_conda = tmp_path / "conda"
    fake_conda.touch()
    benchmark.CONDA = fake_conda
    assert benchmark._py_invoke()[0] == str(fake_conda)
    benchmark.USE_CURRENT_PYTHON = True
    assert benchmark._py_invoke() == [sys.executable]
    args = benchmark.build_parser().parse_args(["--fast", "--work-dir", str(tmp_path / "scratch")])
    assert benchmark.resolve_out(args) == str(tmp_path / "scratch/results.latest.json")


def test_built_wheel_works_without_source_tree_and_has_same_engine_bytes(tmp_path):
    wheel = os.environ.get("RAVEL_TEST_WHEEL")
    if not wheel:
        pytest.skip("release check: set RAVEL_TEST_WHEEL to a freshly built wheel")
    isolated = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert not any("__pycache__" in name or "/.work/" in name or "_payload/" in name
                       or "trial-runs/" in name or name.endswith(".cc") for name in names)
        archive.extractall(isolated)
    for relative in payload_files(DATA_ROOT):
        assert (isolated / "ravel/data/replay" / relative).read_bytes() == resolve(DATA_ROOT, relative).read_bytes()
    for source in (REPO / 'src/ravel').rglob('*.py'):
        assert (isolated / 'ravel' / source.relative_to(REPO / 'src/ravel')).read_bytes() == source.read_bytes(), str(source.relative_to(REPO))
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "from ravel import validate_task_contract; "
            "from ravel.resources import resource_root; "
            "assert str(resource_root()).endswith('ravel/data/replay'); "
            "assert validate_task_contract({'approval_required': False}); "
            "from ravel.cli import main; raise SystemExit(main(['validate', '--schema']))")
    completed = subprocess.run([sys.executable, "-I", "-c", code, str(isolated)],
                               cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert "required" in json.loads(completed.stdout)
    ambiguous = tmp_path / 'duplicate-contract.json'
    ambiguous.write_text(json.dumps(contract())[:-1] + ', "approval_required": true}')
    validate_code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                     "from ravel.cli import main; "
                     "raise SystemExit(main(['validate', sys.argv[2], '--json']))")
    rejected = subprocess.run([sys.executable, '-I', '-c', validate_code, str(isolated), str(ambiguous)],
                              cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert rejected.returncode == 2, rejected.stdout + rejected.stderr
    assert 'duplicate' in json.loads(rejected.stdout)['errors'][0]
    # A wheel that imports successfully can still lose files needed by subprocess engines.
    # Exercise the real cached statistics with scratch outside the extracted installation.
    output = tmp_path / 'wheel-replay'
    replay_code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                   "from ravel.cli import main; "
                   "raise SystemExit(main(['replay', '--out', sys.argv[2]]))")
    replay = subprocess.run([sys.executable, '-I', '-c', replay_code, str(isolated), str(output)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert replay.returncode == 0, replay.stdout + replay.stderr
    result = json.loads((output / 'results.json').read_text())
    assert result['summary'] == {'n_cases': 1, 'n_breach': 0, 'gate_ok': True}
    assert not any(path.name == '.work' for path in isolated.rglob('*'))
    assert (output / 'work/ins1458270_squark_800_100/pyhf/exclusion.json').is_file()


def test_source_launcher_and_module_command_work_from_unrelated_directory(tmp_path):
    from ravel.paths import module_command
    commands = ([sys.executable, str(REPO / 'scripts/run.py'), 'ravel.validation.validate_task_contract', '--schema'],
                module_command('ravel.validation.validate_task_contract', '--schema'))
    for command in commands:
        completed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stderr
        assert 'required' in json.loads(completed.stdout)
    no_module = subprocess.run([sys.executable, str(REPO / 'scripts/run.py')], cwd=tmp_path,
                               capture_output=True, text=True, timeout=30)
    assert no_module.returncode != 0
    assert 'usage:' in no_module.stderr


def test_importing_native_converters_does_not_parse_arguments_or_load_root(tmp_path):
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "sys.argv = ['foreign-program', '--unrelated']; import ravel.__main__; "
            "import ravel.physics.delphes2sa_native as d; "
            "import ravel.physics.sa2json_native as s; "
            "import ravel.plotting.plot_simpleanalysis as p; "
            "import ravel.physics.rivet_ref_yields; import ravel.physics.write_yoda; "
            "assert all(callable(m.main) for m in (d,s,p)); "
            "assert all(name not in sys.modules for name in ('ROOT', 'uproot', 'yoda'))")
    result = subprocess.run([sys.executable, '-I', '-c', code, str(REPO / 'src')],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_native_converter_restores_process_state_if_upstream_fails(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ravel.physics import delphes2sa_native
    script = tmp_path / 'Delphes2SA.py'
    script.write_text("raise RuntimeError('converter failed')")
    load = lambda *args: 0
    declare = lambda *args: True
    fake_root = SimpleNamespace(gSystem=SimpleNamespace(Load=load),
                                gInterpreter=SimpleNamespace(Declare=declare, AddIncludePath=lambda p: None))
    monkeypatch.setitem(sys.modules, 'ROOT', fake_root)
    monkeypatch.setenv('D2SA', str(script))
    monkeypatch.setenv('DELPHES_PATH', 'original')
    monkeypatch.setattr(delphes2sa_native, 'read_weights', lambda *_a, **_k: [1.0])
    old_argv = sys.argv
    with pytest.raises(RuntimeError, match='converter failed'):
        delphes2sa_native.main(['--input', 'arbitrary.root', '--output', str(tmp_path / 'out.root'),
                               '--lumi', '139000', '--XS', '1'])
    assert fake_root.gSystem.Load is load and fake_root.gInterpreter.Declare is declare
    assert os.environ['DELPHES_PATH'] == 'original' and sys.argv is old_argv


def test_native_toolchain_override_and_packaged_assets_work_without_checkout(tmp_path, monkeypatch):
    from ravel import paths
    monkeypatch.setenv('RAVEL_NATIVE_BUILD', str(tmp_path / 'toolchain'))
    monkeypatch.setenv('RAVEL_NATIVE_BIN', str(tmp_path / 'executables'))
    assert paths.native_build_root() == tmp_path / 'toolchain'
    assert paths.native_binary('rjr_resolve') == tmp_path / 'executables/rjr_resolve'
    assert paths.repository_root(tmp_path) is None
    from ravel.physics.nlo_xsec import load_lo_ref
    assert load_lo_ref('slepton')
    assert paths.package_data_path('fixtures', 'susy-2018-06', 'BkgOnly.json').is_file()
