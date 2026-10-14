"""The figure-critique record and the delivery-gate provider that reads it.

A figure critic records one ``figure-critique`` per figure: the figure's run path and
sha256, the structural mismatches it found and the red flags among them. A red flag
is a defect that makes the figure state something false (``RED_FLAGS``); it blocks the
``delivery``, ``final_task`` and ``export`` gates until a new critique of the current
bytes records none. A critique of bytes that have since changed still blocks when it
carried a red flag: the changed figure needs its own critique. Mismatches that are not
red flags stay caption deviations (``figure_target critique``) and never block here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .state_io import atomic_json, read_json

DIRECTORY = 'review/figure-critique'
SCHEMA = 'figure-critique.v1'
GATES = ('delivery', 'final_task', 'export')
RED_FLAGS = ('wrong_quantity', 'wrong_reference', 'axis_mislabelled', 'units_missing_or_wrong', 'series_missing',
             'series_unidentified', 'scale_misleading', 'uncertainty_missing', 'normalization_inconsistent')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(rundir, *, figure, figure_id, red_flags=(), mismatches=(), reviewer=None):
    """Write the critique of the figure at run path ``figure``; returns the run-relative record path."""
    root = Path(rundir).resolve()
    path = (root / figure).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('a figure critique names a run figure file')
    flags = []
    for flag in red_flags:
        if type(flag) is not dict or flag.get('code') not in RED_FLAGS or type(flag.get('summary')) is not str:
            raise ValueError('a red flag has a code from RED_FLAGS and a summary')
        flags.append({'code': flag['code'], 'summary': flag['summary']})
    sha = _sha(path)
    value = {'schema': SCHEMA, 'figure': {'path': path.relative_to(root).as_posix(), 'sha256': sha},
             'figure_id': figure_id, 'red_flags': flags, 'mismatches': [str(m) for m in mismatches],
             'reviewer': reviewer}
    rel = f"{DIRECTORY}/{hashlib.sha256(value['figure']['path'].encode()).hexdigest()[:24]}-{sha[:12]}.json"
    atomic_json(root / rel, value)
    return rel


def critiques(rundir):
    folder = Path(rundir) / DIRECTORY
    rows = []
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else ():
        try:
            value = read_json(path)
        except (OSError, ValueError):
            value = None
        rows.append((path.relative_to(Path(rundir)).as_posix(), value))
    return rows


def blocking(rundir):
    """``[(record path, figure path, reason, flags)]`` for every critique that blocks delivery."""
    root = Path(rundir).resolve()
    by_figure = {}
    found = []
    for rel, value in critiques(root):
        if type(value) is not dict or value.get('schema') != SCHEMA:
            found.append((rel, None, 'figure_critique_invalid', []))
            continue
        by_figure.setdefault(value['figure']['path'], []).append((rel, value))
    for figure, rows in sorted(by_figure.items()):
        path = root / figure
        current = _sha(path) if path.is_file() else None
        now = [(rel, v) for rel, v in rows if v['figure']['sha256'] == current]
        if now:
            for rel, v in now:
                if v['red_flags']:
                    found.append((rel, figure, 'figure_red_flag', v['red_flags']))
            continue
        for rel, v in rows:
            if v['red_flags']:
                found.append((rel, figure, 'figure_critique_stale', v['red_flags']))
    return found


def gate_errors(rundir, gate, action):
    """Decision-gate provider (``data/gates/providers.json`` id ``figure_critique``)."""
    from .decision_gate import GateError
    if gate not in GATES:
        return []
    errors = []
    for rel, figure, code, flags in blocking(rundir):
        message = {'figure_red_flag': f'figure {figure} carries red flags: ' + '; '.join(f['summary'] for f in flags),
                   'figure_critique_stale': f'figure {figure} changed after a red-flag critique and has no new critique',
                   'figure_critique_invalid': f'{rel} is not a {SCHEMA} record'}[code]
        errors.append(GateError(code, gate, 'figure_critique', message,
                                'correct the figure and record a new critique of its current bytes with no red flag',
                                (rel,)))
    return errors
