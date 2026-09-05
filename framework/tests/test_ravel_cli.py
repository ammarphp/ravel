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
from ravel.resources import payload_files


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
    files = payload_files(REPO)
    assert len(files) > 6
    assert all("__pycache__" not in path and "/logs/" not in path and "/.work/" not in path
               for path in files)
    run_paths = [path for path in files if path.startswith("trial-runs/") and "_infrastructure" not in path]
    assert len({path.split("/")[1] for path in run_paths}) == 1


def test_explicit_replay_interpreter_ignores_an_existing_conda_binary(tmp_path):
    spec = importlib.util.spec_from_file_location("ravel_benchmark", REPO / "framework/benchmark/run_benchmark.py")
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
        assert not any("__pycache__" in name or "/.work/" in name for name in names)
        archive.extractall(isolated)
    for relative in payload_files(REPO):
        assert (isolated / "ravel/_payload" / relative).read_bytes() == (REPO / relative).read_bytes()
    for source in (REPO / 'src/ravel').glob('*.py'):
        assert (isolated / 'ravel' / source.name).read_bytes() == source.read_bytes()
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "from ravel import validate_task_contract; "
            "from ravel.resources import resource_root; "
            "assert '_payload' in str(resource_root()); "
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
    assert not (isolated / 'ravel/_payload/framework/benchmark/.work').exists()
    assert (output / 'work/ins1458270_squark_800_100/pyhf/exclusion.json').is_file()
