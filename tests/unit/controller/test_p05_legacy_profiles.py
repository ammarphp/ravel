"""Run only the two legacy scheduler fixture repairs from the exact delivered patch.

The peer source stays untouched. Its inert scheduler fixture and test function globals
come from the patched in-memory module; this wrapper keeps its own pytest file identity.
"""
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
import types

import pytest

from test_p05_peer_adapters import _apply_peer

_REPOSITORY = Path(__file__).resolve().parents[3]
_PEER_PATH = 'tests/unit/test_site_profiles.py'
_PEER = _REPOSITORY / _PEER_PATH
_ORIGINAL_BYTES = _PEER.read_bytes()
_PATCH = (_REPOSITORY / 'tests/fixtures/peer_contracts/profile-tests.patch').read_text()


def _hunk_texts(patch):
    """The exact old and new text of each hunk of the single-file legacy patch."""
    old, new = [], []
    for body in re.split(r'(?m)^@@ .*\n', patch)[1:]:
        lines = body.splitlines(keepends=True)
        old.append(''.join(line[1:] for line in lines if line[0] in ' -'))
        new.append(''.join(line[1:] for line in lines if line[0] in ' +'))
    return old, new


def _legacy_source(original, patch):
    """Return the peer source in its applied state, and how it got there.

    Before the peer's owner integrates the repair the exact hunks apply in memory; once the
    peer file itself carries them they are already applied. Either way the result must show
    every hunk's new text exactly once and none of the replaced text.
    """
    old, new = _hunk_texts(patch)
    assert len(old) == 2 and len(new) == 2
    if all(original.count(text) == 1 for text in new) and not any(text in original for text in old):
        source, how = original, 'integrated'
    else:
        source, hunks = _apply_peer(original, patch, _PEER_PATH)
        assert hunks == len(old)
        how = 'patched-in-memory'
    assert all(source.count(text) == 1 for text in new)
    assert not any(text in source for text in old)
    return source, how


_SOURCE, _HOW = _legacy_source(_ORIGINAL_BYTES.decode(), _PATCH)
_SPEC = importlib.util.spec_from_file_location('test_site_profiles', _PEER)
_MODULE = types.ModuleType('_ravel_p05_legacy_site_profiles')
_MODULE.__file__ = str(_PEER)
_MODULE.__package__ = _SPEC.parent
sys.modules[_MODULE.__name__] = _MODULE
exec(compile(_SOURCE, _MODULE.__file__, 'exec'), _MODULE.__dict__)

# Only this explicit fixture and the two repaired test functions are exported.
# Their plain helper functions remain in the in-memory module's own globals.
scheduler = _MODULE.scheduler
test_rendered_commands_accept_workflow_formatting_and_relocation = (
    _MODULE.test_rendered_commands_accept_workflow_formatting_and_relocation)
test_submit_cli_surfaces_refusal_and_record_path = _MODULE.test_submit_cli_surfaces_refusal_and_record_path


@pytest.fixture(autouse=True)
def _peer_bytes_unchanged():
    expected = hashlib.sha256(_ORIGINAL_BYTES).hexdigest()
    assert hashlib.sha256(_PEER.read_bytes()).hexdigest() == expected
    yield
    assert hashlib.sha256(_PEER.read_bytes()).hexdigest() == expected
