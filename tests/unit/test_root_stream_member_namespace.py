"""A local member's directories are identified, not timed: unrelated entries are tolerated.

Pure synthetic bytes; no ROOT, site or native operation.
"""
import hashlib
import os

import pytest

from ravel.physics import root_stream_worker as worker


def member_fixture(root):
    path = root / 'parent' / 'data' / 'member'
    path.parent.mkdir(parents=True)
    raw = b'bounded synthetic member'
    path.write_bytes(raw)
    return path, {'uri': path.as_uri(), 'guid': 'synthetic', 'entries': 1, 'size_bytes': len(raw),
                  'checksum': {'algorithm': 'sha256', 'value': hashlib.sha256(raw).hexdigest()}}


def test_unrelated_entries_beside_the_member_and_above_it_are_tolerated(tmp_path):
    path, member = member_fixture(tmp_path)
    handle, _ = worker.open_member(member, {})
    try:
        # Another process may create and remove files in any directory on the path.
        for directory in (path.parent, path.parent.parent, tmp_path):
            other = directory / 'unrelated'
            other.write_bytes(b'x'); (directory / 'gone').write_bytes(b'y'); (directory / 'gone').unlink()
        assert worker.identity(handle, member)['entries'] == 1
    finally:
        handle.close()


def test_replaced_directory_on_the_path_is_refused(tmp_path):
    path, member = member_fixture(tmp_path)
    # The same file under another directory: only the directory identity differs afterwards.
    replacement = tmp_path / 'replacement' / 'data'
    replacement.mkdir(parents=True)
    os.link(path, replacement / path.name)
    handle, _ = worker.open_member(member, {})
    try:
        (tmp_path / 'parent').rename(tmp_path / 'moved')
        (tmp_path / 'replacement').rename(tmp_path / 'parent')
        with pytest.raises(ValueError, match='original local descriptor/ancestor differs'):
            worker.identity(handle, member)
    finally:
        handle.close()


def test_replaced_member_is_refused(tmp_path):
    path, member = member_fixture(tmp_path)
    handle, _ = worker.open_member(member, {})
    try:
        raw = path.read_bytes(); path.rename(path.with_name('old')); path.write_bytes(raw)
        with pytest.raises(ValueError, match='original local source namespace differs'):
            worker.identity(handle, member)
    finally:
        handle.close()
