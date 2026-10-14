"""Assertion messages for supervised-stage controls: what the stage recorded and what it logged.

A stage that fails on another host otherwise reports only its exit status. This
text is evidence for the reader of a failed run; no test reads it back.
"""
import json
from pathlib import Path


def stage_evidence(rundir, limit=3000):
    """The recorded stage outcomes, failure receipts and the end of every log under ``rundir/logs``."""
    root = Path(rundir)
    rows = []
    try:
        from ravel.workflow import execution
        stages = execution.load_execution(root)['stages']
        rows.append(json.dumps({name: {key: record.get(key) for key in ('status', 'returncode', 'reason', 'attempt_id')}
                                for name, record in stages.items()}, default=str))
    except Exception as exc:  # the message must not hide the assertion it explains
        rows.append(f'no execution record: {exc!r}')
    logs = root / 'logs'
    for path in sorted(logs.glob('*.failure.json')) + sorted(logs.rglob('*.log')):
        try:
            rows.append(f'--- {path.relative_to(root)}\n{path.read_text(errors="replace")[-limit:]}')
        except OSError as exc:
            rows.append(f'--- {path}: {exc!r}')
    return '\n'.join(rows)
