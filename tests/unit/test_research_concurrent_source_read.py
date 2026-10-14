"""Real-file source-read controls; no Graph/scientific/native dispatch."""
import hashlib
import os
from pathlib import Path

import pytest
from ravel.physics import research_comparison as comparison
from ravel.workflow import research_cycle as cycle


def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def source(tmp_path):
    directory = tmp_path / 'parent'
    directory.mkdir()
    path = directory / 'request.json'
    path.write_bytes(b'{"value":3}\n')
    return path


def consume(path, kind):
    if kind == 'command':
        return cycle._cli_document(path)
    return comparison.document(pin(path), path.parent)


def during_read(monkeypatch, action, *, returned=None):
    """Intercept the real newly opened leaf descriptor, not old Path.open."""
    original = os.fdopen
    observed = {'reads': [], 'activated': False}

    class Stream:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): self.stream.__enter__(); return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def fileno(self): return self.stream.fileno()
        def read(self, bound):
            raw = self.stream.read(bound)
            observed['reads'].append(bound)
            action()
            observed['activated'] = True
            return raw if returned is None else returned(raw, bound)

    monkeypatch.setattr(os, 'fdopen', lambda fd, *args, **kwargs: Stream(original(fd, *args, **kwargs)))
    return observed


@pytest.mark.parametrize('kind', ['command', 'comparison'])
@pytest.mark.parametrize('change', ['add', 'remove', 'rename'])
def test_unrelated_sibling_change_does_not_refuse_input(tmp_path, monkeypatch, kind, change):
    path = source(tmp_path); expected = pin(path)
    sibling = path.parent / 'note.txt'
    if change != 'add': sibling.write_text('unrelated')
    action = (lambda: sibling.write_text('concurrent note')) if change == 'add' else sibling.unlink if change == 'remove' else lambda: sibling.rename(path.parent / 'renamed-note.txt')
    observed = during_read(monkeypatch, action)
    assert consume(path, kind) == {'value': 3}
    assert observed['activated'] and pin(path) == expected


@pytest.mark.parametrize('kind', ['command', 'comparison'])
@pytest.mark.parametrize('change', ['bytes', 'leaf', 'delete', 'mode', 'leaf_symlink', 'parent_symlink', 'parent', 'intermediate'])
def test_actual_leaf_or_path_change_refuses(tmp_path, monkeypatch, kind, change):
    path = source(tmp_path)
    if change in ('parent', 'intermediate'):
        other = tmp_path / 'replacement'
        other.mkdir()
        if change == 'intermediate':
            nested = path.parent / 'nested'; nested.mkdir()
            path.rename(nested / path.name); path = nested / path.name
            (other / 'nested').mkdir()
            replacement = other / 'nested' / path.name
        else: replacement = other / path.name
        os.link(path, replacement)

    def change_path():
        if change == 'bytes': path.write_bytes(b'{"value":9}\n')
        elif change == 'leaf':
            replacement = path.with_name('replacement.json'); replacement.write_bytes(path.read_bytes()); os.replace(replacement, path)
        elif change == 'delete': path.unlink()
        elif change == 'mode': path.chmod(0o600 if path.stat().st_mode & 0o777 != 0o600 else 0o644)
        elif change == 'leaf_symlink':
            moved = path.with_name('moved.json'); path.rename(moved); path.symlink_to(moved)
        elif change == 'parent_symlink':
            parent = path.parent; moved = tmp_path / 'moved'; parent.rename(moved); parent.symlink_to(moved, target_is_directory=True)
        else:
            parent = tmp_path / 'parent'; parent.rename(tmp_path / 'moved'); other.rename(parent)

    observed = during_read(monkeypatch, change_path)
    with pytest.raises(ValueError): consume(path, kind)
    assert observed['activated']


@pytest.mark.parametrize('kind', ['command', 'comparison'])
def test_content_mutation_and_restore_is_still_refused(tmp_path, monkeypatch, kind):
    path = source(tmp_path); original = path.read_bytes()
    def mutation():
        path.write_bytes(b'{"value":9}\n'); path.write_bytes(original)
    observed = during_read(monkeypatch, mutation)
    with pytest.raises(ValueError): consume(path, kind)
    assert observed['activated'] and path.read_bytes() == original


def test_pinned_comparison_authenticates_consumed_buffer(tmp_path, monkeypatch):
    path = source(tmp_path); expected = pin(path)
    observed = during_read(monkeypatch, lambda: None, returned=lambda raw, n: raw.replace(b'3', b'9'))
    with pytest.raises(ValueError, match='authenticated'):
        comparison.document(expected, path.parent)
    assert observed['activated'] and pin(path) == expected


@pytest.mark.parametrize('kind', ['command', 'comparison'])
@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'not JSON'])
def test_strict_consumed_json_refuses(tmp_path, kind, raw):
    path = source(tmp_path); path.write_bytes(raw)
    with pytest.raises((ValueError, RuntimeError)): consume(path, kind)


def test_growth_after_initial_leaf_observation_refuses_before_read(tmp_path, monkeypatch):
    path = source(tmp_path); original = os.open; observed = {'opened': False}
    def opening(name, flags, *args, **kwargs):
        if name == path.name and kwargs.get('dir_fd') is not None:
            observed['opened'] = True
            path.write_bytes(b' ' * 64)
        return original(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', opening)
    observed_read = during_read(monkeypatch, lambda: pytest.fail('changed leaf reached bounded read'))
    with pytest.raises(ValueError): cycle._bounded_source_snapshot(path, 32)
    assert observed['opened'] and not observed_read['activated']


def test_bounded_read_never_requests_more_than_limit_plus_one(tmp_path, monkeypatch):
    path = source(tmp_path)
    observed = during_read(monkeypatch, lambda: None, returned=lambda raw, n: b'x' * n)
    with pytest.raises(ValueError): cycle._bounded_source_snapshot(path, 32)
    assert observed['reads'] == [33]


@pytest.mark.parametrize('phase', ['before_fdopen', 'after_read'])
def test_descriptors_closed_on_refusal(tmp_path, monkeypatch, phase):
    path = source(tmp_path); opened = []; original_open = os.open
    def opening(*args, **kwargs):
        descriptor = original_open(*args, **kwargs); opened.append(descriptor); return descriptor
    monkeypatch.setattr(os, 'open', opening)
    if phase == 'before_fdopen':
        monkeypatch.setattr(os, 'fdopen', lambda *a, **kw: (_ for _ in ()).throw(OSError('injected fdopen refusal')))
    else: during_read(monkeypatch, path.unlink)
    with pytest.raises(ValueError): cycle._bounded_source_snapshot(path, 32)
    for descriptor in set(opened):
        with pytest.raises(OSError): os.fstat(descriptor)


def test_restored_ancestor_rename_is_not_claimed_as_detectable(tmp_path, monkeypatch):
    path = source(tmp_path); original = pin(path)
    def temporary_rename():
        parent = path.parent; moved = tmp_path / 'temporary'; parent.rename(moved); moved.rename(parent)
    observed = during_read(monkeypatch, temporary_rename)
    assert consume(path, 'comparison') == {'value': 3}
    assert observed['activated'] and pin(path) == original


