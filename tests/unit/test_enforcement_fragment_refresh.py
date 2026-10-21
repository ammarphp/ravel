"""Maintenance preserves guard bytes and refuses missing or ambiguous postimages."""
import difflib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('fragment_refresh', ROOT / 'scripts/maintenance/refresh_enforcement_fragment.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def fragment(before, after):
    return ''.join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                      fromfile='a/src/example.py', tofile='b/src/example.py'))


def test_refresh_preserves_unrelated_changes_and_removes_only_the_guard():
    before = 'def action():\n    execute()\n'
    after = 'def action():\n    require_authority()\n    execute()\n'
    installed = '# newly integrated preamble\n\n' + after + '\n# another change\n'
    expected = '# newly integrated preamble\n\n' + before + '\n# another change\n'
    assert refresh.reverse_exact(installed, fragment(before, after)) == expected


@pytest.mark.parametrize('installed', ['absent\n', 'guard\nguard\n'])
def test_changed_or_ambiguous_guard_requires_review(installed):
    with pytest.raises(ValueError, match='absent or ambiguous'):
        refresh.reverse_exact(installed, fragment('old\n', 'guard\n'))


def test_an_unrelated_target_cannot_be_selected(tmp_path):
    with pytest.raises(ValueError, match='local fragment'):
        refresh.refreshed(tmp_path, '../unrelated.patch')
