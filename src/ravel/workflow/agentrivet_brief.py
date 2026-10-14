"""RAVEL construction context for each AgentRivet role, and text feedback for repairs.

A brief is a small JSON document presented beside an original role's messages.
It carries what RAVEL knows and the upstream roles lack: the routine name the
build will require, the HEPData tables with their binning, the typed analysis
specification with its ambiguity record, the normalization contract, RAVEL's
Rivet authoring guidance and review checklist, and the latest construction
check of the draft under work. Upstream messages are never edited.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from ravel.physics import agentrivet_candidate as candidate
from . import agentrivet_checks

DATA = Path(__file__).resolve().parents[1] / 'data'
GUIDANCE = DATA / 'rivet' / 'construction.json'
HANDBOOK = DATA / 'skills' / 'tools' / 'rivet-routine' / 'SKILL.md'
MAX_SPEC = 256 * 1024

PARTS = {
    'analyst': ('hepdata_tables', 'analysis_spec', 'ambiguities', 'normalization_contract'),
    'coder': ('authoring', 'rivet_handbook', 'checklist', 'hepdata_tables', 'analysis_spec', 'ambiguities',
              'normalization_contract', 'observations'),
    'code_reviewer': ('checklist', 'hepdata_tables', 'observations'),
    'physics_reviewer': ('checklist', 'analysis_spec', 'ambiguities', 'normalization_contract', 'observations'),
}


def guidance():
    value = json.loads(GUIDANCE.read_text())
    if value.get('kind') != 'rivet-construction-guidance' or not value.get('checklist'):
        raise ValueError('packaged Rivet construction guidance is malformed')
    return value


def handbook():
    text = HANDBOOK.read_text()
    if text.startswith('---'):
        text = text.split('---', 2)[2]
    return text.strip()


def load_spec(pin, base, *, sources=None):
    """A typed analysis specification, checked by ``analysis_spec`` with every span against its source.

    The bytes checked are the snapshotted bytes the construction captures. Sources are
    resolved beside the specification, as the columnar analysis engine resolves them.
    ``sources`` (a list) receives the pinned source files whose spans were checked.
    """
    from . import analysis_spec
    path, raw = candidate._snapshot(pin, base)
    if len(raw) > MAX_SPEC:
        raise ValueError('analysis specification exceeds the construction brief bound')
    document = candidate._json(raw)
    checked = analysis_spec.load(document, Path(path).parent)
    if sources is not None:
        sources.extend(checked['sources'])
    return document


def ambiguities(spec):
    """Fields the specification marks ambiguous or not specified."""
    rows = []
    for item in (spec or {}).get('items', []):
        if not isinstance(item, dict):
            continue
        for name, field in (item.get('fields') or {}).items():
            if isinstance(field, dict) and field.get('status') in ('ambiguous', 'not_specified'):
                row = {'item': item.get('id'), 'role': item.get('role'), 'field': name, 'status': field['status']}
                for key in ('readings', 'note'):
                    if key in field:
                        row[key] = deepcopy(field[key])
                rows.append(row)
    return rows


def tables(table_map):
    if table_map is None:
        return None
    rows = []
    for identity, entry in sorted(table_map['entries'].items()):
        rows.append({'id': identity, 'description': entry['description'][:400], 'xlabels': entry['xlabels'],
                     'ylabel': entry['ylabel'], 'dimension': entry['dimension'], 'n_bins': entry['n_points'],
                     'edges': entry['edges'][:501] if entry['edges'] is not None else None})
    return rows


class Briefs:
    """Callable ``(role, stage, last_draft) -> brief`` bound to one construction."""

    def __init__(self, *, routine, table_map=None, spec=None, contract=(), checks=None):
        self.routine, self.table_map, self.spec = routine, table_map, spec
        self.contract, self.checks = list(contract), checks
        self.guide = guidance()

    def part(self, name, last_draft):
        if name == 'authoring':
            return self.guide['authoring']
        if name == 'rivet_handbook':
            return handbook()
        if name == 'checklist':
            return self.guide['checklist']
        if name == 'hepdata_tables':
            return tables(self.table_map)
        if name == 'analysis_spec':
            return self.spec
        if name == 'ambiguities':
            return ambiguities(self.spec) if self.spec is not None else None
        if name == 'normalization_contract':
            return self.contract or None
        if name == 'observations':
            if self.checks is None or last_draft is None:
                return None
            return agentrivet_checks.summary(self.checks.record_for(last_draft))
        raise KeyError(name)

    def __call__(self, role, stage, last_draft):
        if role not in PARTS:
            return None
        brief = {'schema_version': 1, 'kind': 'ravel-construction-brief', 'role': role, 'stage': stage,
                 'routine_name': self.routine,
                 'purpose': ('RAVEL construction context for this role. The routine must register exactly '
                             'routine_name. Observations describe the latest draft as RAVEL compiled and ran it.')}
        for name in PARTS[role]:
            value = self.part(name, last_draft)
            if value is not None:
                brief[name] = value
        return brief


# ---------------------------------------------------------------- repairs

def _read_bytes(pin):
    try:
        _, raw = candidate._snapshot({'path': pin['path'], 'sha256': pin['sha256']}, Path('/'))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return raw


def _log_text(raw):
    """Text of a retained log: decoded stdout/stderr of a JSON process log, or the file itself."""
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        document = None
    if isinstance(document, dict) and ('stdout_base64' in document or 'stderr_base64' in document):
        import base64
        parts = []
        for key in ('stdout_base64', 'stderr_base64'):
            try:
                parts.append(base64.b64decode(document.get(key) or '', validate=True).decode('utf-8', errors='replace'))
            except (ValueError, TypeError):
                pass
        return '\n'.join(p for p in parts if p.strip())
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return None


def failure_feedback(document):
    """Compiler and log text from a verified failed-stage intake: ``(kind, text)``."""
    pins = []
    for row in document.get('evidence', []):
        pins.append((row, row.get('location')))
    for row in document.get('returned_outputs') or []:
        if isinstance(row, dict) and 'path' in row and 'sha256' in row:
            pins.append((row, None))
    for row in (document.get('launch_observation') or {}).get('pins', []):
        pins.append((row, None))
    sections, seen = [], set()
    for pin, location in pins:
        if pin['path'] in seen:
            continue
        seen.add(pin['path'])
        raw = _read_bytes(pin)
        text = _log_text(raw) if raw is not None else None
        if not text or not text.strip():
            continue
        title = Path(pin['path']).name + (f' ({location})' if location else '')
        sections.append(f'--- {title}\n' + agentrivet_checks.bounded(text.strip(), 12000))
    error = document.get('execution_error')
    head = f"The build/event stage failed (exit {document.get('exit_code')})" + (f': {error}' if error else '.')
    body = '\n\n'.join(sections) if sections else 'No log text was retained with the failure.'
    text = agentrivet_checks.bounded(head + '\n\n' + body, 24000)
    kind = 'compile' if any(d['severity'] in ('error', 'fatal error') for d in agentrivet_checks.diagnostics(text)) else 'failure'
    return kind, text


def send_back_feedback(summary, view):
    """Review text from a current independent send-back: summary plus unresolved findings."""
    lines = ['Independent review sent the routine back.', 'Summary: ' + summary.strip()]
    for finding in view.get('unresolved_findings') or []:
        if isinstance(finding, dict):
            parts = [f'{k}: {v}' for k, v in finding.items() if isinstance(v, (str, int, float)) and k != 'sha256']
            lines.append('- ' + '; '.join(parts))
        else:
            lines.append('- ' + str(finding))
    return 'review', '\n'.join(lines)


def repair_prompt(memory, routine, draft, kind, feedback):
    """RAVEL's revision request for the original coder: the selected draft plus feedback text."""
    if kind == 'compile':
        head = ('Revise the following C++ analysis code to fix the compiler errors below. Only change lines '
                'needed to fix these errors; leave every other line as it is.')
        label = 'Compiler and build output'
    elif kind == 'review':
        head = 'Revise the following C++ analysis code using the independent review findings below.'
        label = 'Review findings'
    else:
        head = 'Revise the following C++ analysis code to address the failure below.'
        label = 'Failure output'
    return (f"{head}\n\nAnalysis ID: {routine}\n\nAnalysis summary:\n{memory.get('analysis_model')}\n\n"
            f"Current code:\n{draft}\n\n{label}:\n{feedback}")
