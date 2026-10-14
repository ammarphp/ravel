"""Fresh metadata identity laws; no external runtime/provider/native work."""
import importlib.metadata as md
import os
from pathlib import Path
import warnings

import pytest
from ravel.workflow import execution
from ravel.workflow.validation_io import ValidationSession


def _distribution(tmp_path, leaf, text, filename="METADATA", cls=md.PathDistribution):
    root = tmp_path / leaf
    root.mkdir()
    (root / filename).write_text(text, encoding="utf-8")
    return cls(root)


def _population(monkeypatch, rows):
    monkeypatch.setattr(md, "distributions", lambda: iter(rows))


def _expected(pairs):
    return {"platform": execution.platform.platform(), "python": execution.sys.version,
            "environment_sha256": execution.digest(execution.runtime_environment()),
            "packages_sha256": execution.digest(sorted(pairs))}


@pytest.mark.parametrize("filename, text", [
    ("METADATA", "Name: Folded\nVersion: 1\nLicense: one\n        two\n\nbody\n"),
    ("PKG-INFO", "Name: Folded\nVersion: 1\n\nlegacy body\n"),
])
def test_exact_stdlib_parser_and_runtime_fields(tmp_path, monkeypatch, filename, text):
    row = _distribution(tmp_path, "metadata", text, filename)
    _population(monkeypatch, [row])
    assert execution.runtime_context() == _expected([("Folded", "1")])


def test_duplicates_missing_fields_and_complete_discovery(tmp_path, monkeypatch):
    rows = [_distribution(tmp_path, "a", "Name: Same\nVersion: 4\n"),
            _distribution(tmp_path, "b", "Name: Same\nVersion: 4\n"),
            _distribution(tmp_path, "unnamed", "Version: 9\n"),
            _distribution(tmp_path, "missing", "Name: NoVersion\n")]
    _population(monkeypatch, rows)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert execution.runtime_context() == _expected([("Same", "4"), ("Same", "4"), ("NoVersion", None)])
    rows.append(_distribution(tmp_path, "new", "Name: NewCurrent\nVersion: 2\n"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert execution.runtime_context() == _expected([("Same", "4"), ("Same", "4"), ("NoVersion", None), ("NewCurrent", "2")])


def test_same_size_and_mtime_metadata_change_is_fresh(tmp_path, monkeypatch):
    row = _distribution(tmp_path, "a", "Name: Fresh\nVersion: 1\n")
    _population(monkeypatch, [row])
    before = execution.runtime_context()
    path = tmp_path / "a" / "METADATA"
    old = path.stat()
    path.write_text("Name: Fresh\nVersion: 2\n", encoding="utf-8")
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert path.stat().st_size == old.st_size
    assert path.stat().st_mtime_ns == old.st_mtime_ns
    after = execution.runtime_context()
    assert after == _expected([("Fresh", "2")])
    assert before["packages_sha256"] != after["packages_sha256"]


def test_custom_distribution_version_getter_keeps_own_semantics(tmp_path, monkeypatch):
    class VersionProvider(md.PathDistribution):
        @property
        def version(self):
            return "provider-current-" + self.read_text("VERSION-SOURCE").strip()
    row = _distribution(tmp_path, "custom", "Name: Custom\nVersion: metadata-value\n", cls=VersionProvider)
    path = tmp_path / "custom" / "VERSION-SOURCE"
    path.write_text("one")
    _population(monkeypatch, [row])
    assert execution.runtime_context() == _expected([("Custom", "provider-current-one")])
    path.write_text("two")
    assert execution.runtime_context() == _expected([("Custom", "provider-current-two")])


def test_custom_finder_is_not_replaced_by_metadata_version(monkeypatch):
    class FinderDistribution:
        metadata = {"Name": "Finder", "Version": "ignored"}
        version = "finder-version"
    _population(monkeypatch, [FinderDistribution()])
    assert execution.runtime_context() == _expected([("Finder", "finder-version")])


def test_standard_distribution_reads_current_metadata_once(tmp_path, monkeypatch):
    rows = [_distribution(tmp_path, "a", "Name: Once\nVersion: 1\n"),
            _distribution(tmp_path, "b", "Name: Once\nVersion: 1\n")]
    _population(monkeypatch, rows)
    original = md.PathDistribution.read_text
    reads = []
    def read(self, filename):
        reads.append((str(self._path), filename))
        return original(self, filename)
    monkeypatch.setattr(md.PathDistribution, "read_text", read)
    assert execution.runtime_context() == _expected([("Once", "1"), ("Once", "1")])
    assert reads == [(str(tmp_path / "a"), "METADATA"), (str(tmp_path / "b"), "METADATA")]
    assert execution.runtime_context() == _expected([("Once", "1"), ("Once", "1")])
    assert len(reads) == 4


@pytest.mark.parametrize("change", ["metadata", "population", "environment"])
def test_validation_session_ending_rechecks_current_runtime(tmp_path, monkeypatch, change):
    row = _distribution(tmp_path, "metadata", "Name: Bound\nVersion: 1\n")
    rows = [row]
    _population(monkeypatch, rows)
    run = tmp_path / "run"
    run.mkdir()
    session = ValidationSession(run, resolve_path=lambda value: Path(value),
        read_json=lambda path: None, runtime_context=execution.runtime_context,
        digest=execution.digest, state_name="state.json")
    if change == "metadata":
        (tmp_path / "metadata" / "METADATA").write_text("Name: Bound\nVersion: 2\n")
    elif change == "population":
        rows.append(_distribution(tmp_path, "new", "Name: Added\nVersion: 1\n"))
    else:
        monkeypatch.setenv("OMP_NUM_THREADS", "runtime-identity-changed")
    errors = session.finish()
    assert errors == ["validation final census unavailable: runtime changed during validation"]
    assert session.closed


def test_validation_session_unchanged_runtime_finishes_with_fresh_read(tmp_path, monkeypatch):
    row = _distribution(tmp_path, "metadata", "Name: Stable\nVersion: 1\n")
    _population(monkeypatch, [row])
    original = md.PathDistribution.read_text
    reads = []
    def read(self, filename):
        reads.append(filename)
        return original(self, filename)
    monkeypatch.setattr(md.PathDistribution, "read_text", read)
    run = tmp_path / "run"
    run.mkdir()
    session = ValidationSession(run, resolve_path=lambda value: Path(value),
        read_json=lambda path: None, runtime_context=execution.runtime_context,
        digest=execution.digest, state_name="state.json")
    assert reads == ["METADATA"]
    assert session.finish() == []
    assert reads == ["METADATA", "METADATA"]
    assert session.closed
