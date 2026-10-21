"""In-process test seams of the controller (switch SW30).

The graph substrate keeps in-process seams that substitute decisions: the
``gate_check``/``gate_providers`` arguments, the ``GATE_CHECK``/``GATE_PROVIDERS`` context
variables, in-process graph, route-spec and service registrations, and the machine lease's
``_LOCATION``. In a controller process, and for any scope a controller run owns, they are
refused unless the test harness enabled them in this process. No environment variable, file or
argument enables them: ``enable_seams`` is called by ``tests/conftest.py`` only. The legacy
commands keep their seams on runs the controller does not own.
"""
from __future__ import annotations

from contextlib import contextmanager
import sys

_ENABLED = False
_CONTROLLER = False


class SeamRefused(ValueError):
    """An in-process seam was used where the controller refuses it."""


def enable_seams():
    """Enable the seams for this test process. Only a pytest ``conftest.py`` may call this."""
    global _ENABLED
    caller = sys._getframe(1).f_code.co_filename.replace("\\", "/")
    if "pytest" not in sys.modules or not caller.endswith("/conftest.py"):
        raise SeamRefused("the controller test seams are enabled by the test harness's conftest.py only")
    _ENABLED = True


def seams_enabled():
    return _ENABLED


def mark_controller_process():
    """Called by the controller entry: from now on this process refuses seams it did not enable."""
    global _CONTROLLER
    _CONTROLLER = True


def controller_process():
    return _CONTROLLER


@contextmanager
def seams(enabled, *, controller=None):
    """Within a test: run a block as a production process would (``seams(False, controller=True)``)."""
    global _ENABLED, _CONTROLLER
    if "pytest" not in sys.modules:
        raise SeamRefused("the controller test seams are changed inside the test harness only")
    before = (_ENABLED, _CONTROLLER)
    _ENABLED = bool(enabled)
    if controller is not None:
        _CONTROLLER = bool(controller)
    try:
        yield
    finally:
        _ENABLED, _CONTROLLER = before


def refuse(what):
    """Raise unless the test harness enabled the seams in this process."""
    if not _ENABLED:
        raise SeamRefused(f"{what} is an in-process test seam; the controller refuses it outside the test harness")


def refuse_for_controller(what, *, owned=False):
    """Raise when ``what`` would act in a controller process or on a controller-owned scope without the harness."""
    if (owned or _CONTROLLER) and not _ENABLED:
        raise SeamRefused(f"{what} is an in-process test seam; a controller run refuses it outside the test "
                          "harness")
