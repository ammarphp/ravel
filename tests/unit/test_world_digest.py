"""The world projection is read-only and depends solely on explicitly bound bytes."""
import importlib

import pytest


def module():
    return importlib.import_module('ravel.workflow.world_digest')


@pytest.mark.parametrize('changed', ['journal.json', 'receipt.json', 'input.dat', 'resources.json'])
def test_any_bound_input_change_changes_digest(tmp_path, changed):
    names = ['journal.json', 'receipt.json', 'input.dat', 'resources.json']
    for name in names:
        (tmp_path / name).write_text('{}')
    before = module().digest(tmp_path, names)
    (tmp_path / changed).write_text('{"value": 2}')
    assert module().digest(tmp_path, names)['sha256'] != before['sha256']


def test_unbound_changes_order_and_mtime_do_not_change_digest(tmp_path):
    names = ['a', 'b']
    for name in names:
        (tmp_path / name).write_text('same')
    before = module().digest(tmp_path, names)
    (tmp_path / 'a').touch()
    (tmp_path / 'unbound').write_text('changed')
    assert module().digest(tmp_path, names[::-1]) == before
    assert (tmp_path / 'a').read_text() == 'same'


@pytest.mark.parametrize('path', ['../escape', '/tmp/escape', 'missing'])
def test_world_digest_refuses_unavailable_or_unconfined_inputs(tmp_path, path):
    with pytest.raises((ValueError, OSError)):
        module().digest(tmp_path, [path])
