"""Write an admitted synthetic method decision into a run before a full or scan approval."""
import json
from pathlib import Path

from ravel.workflow import method_selection
from ravel.workflow.state_io import atomic_json

FIXTURES = Path(__file__).parents[1] / 'fixtures/method_decisions'


def admit_method(rundir, name='rough_estimate', *, refresh=True):
    """Record the named fictional decision; refresh CHECK-IN 1 when one exists."""
    root = Path(rundir)
    record = json.loads((FIXTURES / f'{name}.json').read_text())
    allowed, reason = method_selection.escalation_allowed(record)
    if not allowed:
        raise ValueError(reason)
    atomic_json(root / method_selection.DECISION_PATH, record)
    if refresh and (root / 'inputs/checkin1.json').is_file():
        method_selection.refresh_checkin(root)
    return root / method_selection.DECISION_PATH
