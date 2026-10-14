"""A source pin's directories are identified, not timed: unrelated entries are tolerated.

Pure synthetic bytes; no native operation.
"""
import hashlib
import os
from pathlib import Path

import pytest

from ravel.workflow import validation_io


def source_fixture(root):
    path = root / 'parent' / 'data' / 'source'
    path.parent.mkdir(parents=True)
    raw = b'bounded synthetic source'
    path.write_bytes(raw)
    return path, raw, {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def during_the_read(monkeypatch, path, action):
    """Run ``action`` once, after the opening observation and before the source is opened."""
    original = Path.open
    done = []

    def opened(self, *args, **kwargs):
        if self == path and not done:
            done.append(True)
            action()
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opened)
    return done


def test_unrelated_entries_beside_the_source_and_above_it_are_tolerated(tmp_path, monkeypatch):
    path, raw, pin = source_fixture(tmp_path)

    def other_processes():
        # Another process may create and remove files in any directory on the path.
        for directory in (path.parent, path.parent.parent, tmp_path):
            (directory / 'unrelated').write_bytes(b'x')
            (directory / 'gone').write_bytes(b'y')
            (directory / 'gone').unlink()
    done = during_the_read(monkeypatch, path, other_processes)
    assert validation_io._source_pin_bytes(pin) == raw and done


def test_replaced_directory_on_the_path_is_refused(tmp_path, monkeypatch):
    path, _raw, pin = source_fixture(tmp_path)
    # The same file under another directory: only the directory identity differs afterwards.
    replacement = tmp_path / 'replacement' / 'data'
    replacement.mkdir(parents=True)
    os.link(path, replacement / path.name)

    def replace_directory():
        (tmp_path / 'parent').rename(tmp_path / 'moved')
        (tmp_path / 'replacement').rename(tmp_path / 'parent')
    done = during_the_read(monkeypatch, path, replace_directory)
    with pytest.raises(ValueError, match='source pin bytes or ancestry changed'):
        validation_io._source_pin_bytes(pin)
    assert done


def test_replaced_source_is_refused(tmp_path, monkeypatch):
    path, raw, pin = source_fixture(tmp_path)

    def replace_source():
        path.rename(path.with_name('old'))
        path.write_bytes(raw)
    done = during_the_read(monkeypatch, path, replace_source)
    with pytest.raises(ValueError, match='source pin descriptor changed'):
        validation_io._source_pin_bytes(pin)
    assert done


def test_source_changed_and_restored_in_place_is_refused(tmp_path, monkeypatch):
    path, raw, pin = source_fixture(tmp_path)

    def rewrite():
        path.write_bytes(b'x' * len(raw))
        path.write_bytes(raw)
    done = during_the_read(monkeypatch, path, rewrite)
    with pytest.raises(ValueError, match='source pin descriptor changed'):
        validation_io._source_pin_bytes(pin)
    assert done
