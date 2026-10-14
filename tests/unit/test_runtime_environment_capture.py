"""Runtime environment capsules preserve only the values already hashed by execution."""
import sys
from pathlib import Path

import pytest

from ravel.workflow import execution
from ravel.workflow.state_io import atomic_json


def specification(root):
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "inputs/source.txt").write_text("source\n")
    inputs = ["inputs/source.txt"]
    value = {"command": [sys.executable, "-c", "pass"], "cwd": str(root.resolve()),
        "inputs": inputs, "outputs": ["outputs/result.txt"],
        "input_snapshot": execution.snapshot(root, inputs), "parents": {},
        "runtime": execution.runtime_context()}
    value["fingerprint"] = execution.digest(value)
    return value


def succeeded_attempt(root):
    spec = specification(root)
    record = execution.begin_attempt(root, "capture", spec, "logs/capture.log")
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    (root / "outputs/result.txt").write_text("done\n")
    (root / "logs/capture.log").write_text("done\n")
    assert execution.finish_attempt(root, record, 0) == 0
    return record


def package_files(monkeypatch, entries):
    package_root = Path(execution.__file__).resolve().parents[1]
    original = Path.rglob
    def rglob(path, pattern):
        if path == package_root and pattern == "*.py":
            return iter(entries)
        return original(path, pattern)
    monkeypatch.setattr(Path, "rglob", rglob)


def test_runtime_context_hashes_the_captured_exact_whitelist(monkeypatch):
    expected = dict.fromkeys(execution.RUNTIME_ENVIRONMENT_KEYS)
    for index, name in enumerate(execution.RUNTIME_ENVIRONMENT_KEYS):
        value = f"value-{index}"
        monkeypatch.setenv(name, value)
        expected[name] = value
    assert execution.runtime_environment() == expected
    assert execution.runtime_context()["environment_sha256"] == execution.digest(expected)


def test_secret_environment_values_are_not_captured(monkeypatch):
    before = execution.runtime_environment()
    monkeypatch.setenv("RAVEL_TEST_SECRET", "should-not-be-recorded")
    assert execution.runtime_environment() == before
    assert "RAVEL_TEST_SECRET" not in before


@pytest.mark.parametrize("mutation", ["missing", "tampered", "extra", "invalid-type"])
def test_capsule_validation_rejects_readable_but_invalid_records(tmp_path, mutation):
    record = succeeded_attempt(tmp_path)
    state_path = tmp_path / execution.STATE_NAME
    state = execution.load_execution(tmp_path)
    capsule = state["stages"]["capture"]["runtime_environment"]
    if mutation == "missing":
        capsule.pop(execution.RUNTIME_ENVIRONMENT_KEYS[0])
    elif mutation == "tampered":
        capsule[execution.RUNTIME_ENVIRONMENT_KEYS[0]] = "different value"
    elif mutation == "invalid-type":
        capsule[execution.RUNTIME_ENVIRONMENT_KEYS[0]] = 7
    else:
        capsule["RAVEL_TEST_SECRET"] = "should-not-be-recorded"
    atomic_json(state_path, state)
    assert execution.read_json(state_path) == state
    errors = execution.stage_errors(tmp_path, "capture")
    assert any("runtime environment capsule" in error for error in errors)


def test_environment_mismatch_is_refused_before_attempt_mutates_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "planned")
    spec = specification(tmp_path)
    output = tmp_path / "outputs/result.txt"
    output.parent.mkdir()
    output.write_text("preserve\n")
    monkeypatch.setenv("OMP_NUM_THREADS", "changed")
    with pytest.raises(ValueError, match="changed since stage planning"):
        execution.begin_attempt(tmp_path, "capture", spec, "logs/capture.log")
    assert output.read_text() == "preserve\n"
    assert execution.load_execution(tmp_path)["stages"] == {}


def test_legacy_record_without_capsule_keeps_existing_validation(tmp_path):
    record = succeeded_attempt(tmp_path)
    state = execution.load_execution(tmp_path)
    del state["stages"]["capture"]["runtime_environment"]
    atomic_json(tmp_path / execution.STATE_NAME, state)
    attempt_path = tmp_path / record["attempt_record"]
    attempt = execution.read_json(attempt_path)
    attempt.pop("runtime_environment")
    atomic_json(attempt_path, attempt)
    assert not execution.stage_errors(tmp_path, "capture")


def test_plan_stage_preserves_alias_and_duplicate_input_identity(tmp_path, monkeypatch):
    source = tmp_path / "inputs/script.py"
    source.parent.mkdir()
    source.write_text("pass\n")
    alias = "inputs/../inputs/script.py"
    package_files(monkeypatch, [source.resolve(), source.resolve()])
    spec = execution.plan_stage(tmp_path, "alias_case",
        [sys.executable, "inputs/script.py", str(source.resolve())], [alias], [], [], str(tmp_path))
    assert spec["inputs"] == [alias, str(Path(sys.executable).resolve())]
    assert list(spec["input_snapshot"]) == [str(source.resolve()), str(Path(sys.executable).resolve())]
    assert spec["fingerprint"] == execution.digest({k: v for k, v in spec.items() if k != "fingerprint"})


def test_plan_stage_retains_old_symlink_duplicate_refusal(tmp_path, monkeypatch):
    target = tmp_path / "inputs/real.py"
    target.parent.mkdir()
    target.write_text("pass\n")
    alias = target.with_name("alias.py")
    alias.symlink_to(target)
    package_files(monkeypatch, [alias])
    with pytest.raises(ValueError, match="duplicate artifact path"):
        execution.plan_stage(tmp_path, "symlink_case", [sys.executable, "-c", "pass"],
            [str(target)], [], [], str(tmp_path))


def test_plan_stage_resolves_inputs_linearly_with_package_files(tmp_path, monkeypatch):
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    paths = []
    for index in range(400):
        path = input_dir / f"source-{index}.dat"
        path.write_text("x\n")
        paths.append(path)
    package_files(monkeypatch, paths[:30])
    resolve = execution.resolve_path
    calls = 0
    def counted_resolve(*args, **kwargs):
        nonlocal calls
        calls += 1
        return resolve(*args, **kwargs)
    monkeypatch.setattr(execution, "resolve_path", counted_resolve)
    spec = execution.plan_stage(tmp_path, "large_plan", [sys.executable, "-c", "pass"],
        [str(path.relative_to(tmp_path)) for path in paths], [], [], str(tmp_path))
    assert len(spec["inputs"]) == 401
    assert calls <= 2 * len(paths) + 30 + 10
