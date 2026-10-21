"""The current source checkout satisfies the complete instruction surface gate."""
import sys

import pytest

from ravel.validation import check_agent_surface


def test_current_source_instruction_surface(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_agent_surface'])
    with pytest.raises(SystemExit) as result:
        check_agent_surface.main()
    assert result.value.code == 0
