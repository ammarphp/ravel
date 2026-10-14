"""CHECK-IN section and live approval binding for acceptance tolerances.

Legacy CHECK-IN documents remain readable. A new governed acceptance report must
have the complete section in the approved bytes. Defaults are proposed by an
empty inputs/certification_tolerances.json or by the section composer's context.
This checks integrity and recorded deviations, not human identity or physics.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from ravel.workflow.state_io import read_json


SECTION = 'certification_tolerances'
PROPOSAL = 'inputs/certification_tolerances.json'
DEFAULTS = {'driving_tol': .15, 'contributing_tol': .25, 'mu95_bound': .10,
            'tail_events': 5, 'driving_factor': 1.5, 'interp_max_span': 200.0}
# +1: a larger value admits more (wider tolerances, more report-only tail SRs, wider
# interpolation brackets); -1: a smaller driving factor puts fewer SRs in the strict tier.
LOOSER = {'driving_tol': 1, 'contributing_tol': 1, 'mu95_bound': 1,
          'tail_events': 1, 'driving_factor': -1, 'interp_max_span': 1}


def tolerances(value, *, complete=False):
    """Validate the six controls; omitted proposal values keep the legacy defaults."""
    if type(value) is not dict or set(value) - DEFAULTS.keys():
        raise ValueError('certification_tolerances must contain only the six named controls')
    if complete and set(value) != DEFAULTS.keys():
        raise ValueError('certification_tolerances requires all six controls')
    result = {**DEFAULTS, **value}
    for name, number in result.items():
        try:
            valid = type(number) in (int, float) and math.isfinite(number)
        except OverflowError:
            valid = False
        if not valid or number < 0 or (name != 'tail_events' and number == 0):
            raise ValueError(f'certification_tolerances.{name} must be finite and '
                             + ('nonnegative' if name == 'tail_events' else 'positive'))
        if name == 'tail_events' and type(number) is not int:
            raise ValueError('certification_tolerances.tail_events must be an integer')
    if result['driving_factor'] < 1:
        raise ValueError('certification_tolerances.driving_factor must be >= 1')
    return result


def checkin_section(context):
    """Section render(context) seam: proposed controls or a complete stored section."""
    base = context.get('base_dir')
    if base is not None and (Path(base) / PROPOSAL).exists():
        try:
            return tolerances(read_json(Path(base) / PROPOSAL))
        except ValueError as exc:
            raise ValueError('certification_tolerances proposal: ' + str(exc)) from exc
    if SECTION in context:
        return tolerances(context[SECTION])
    sections = context['document'].get('sections', {})
    if SECTION in sections:
        return tolerances(sections[SECTION], complete=True)
    if _requires_section(context.get('contract')):
        return dict(DEFAULTS)
    return None


def _requires_section(contract):
    """A planned run whose statistics ship an acceptance-certified limit shows its controls.

    Contracts without a pinned request plan predate this section; governed certification
    still refuses them until a renewed approval carries it.
    """
    if not isinstance(contract, dict) or not contract.get('request_plan'):
        return False
    from ravel.validation.validate_run_state import CERT_REQUIRED_STAT_MODES
    return contract.get('stat_mode') in CERT_REQUIRED_STAT_MODES


def section_errors(content, context):
    """Section validate(content, context) seam; no waiver for invalid numbers."""
    try:
        tolerances(content, complete=True)
    except ValueError as exc:
        return [str(exc)]
    return []


def discover_rundir(*paths):
    """Find governance beside producer inputs/outputs, so omitting a flag is no bypass."""
    roots = set()
    for path in paths:
        parent = Path(path).resolve().parent
        for candidate in (parent, *parent.parents):
            if any((candidate / marker).is_file() for marker in
                   ('inputs/checkin1.json', 'inputs/checkin1_approval.json',
                    'inputs/task_contract.json', 'run_state.json')):
                roots.add(candidate)
                break
    if len(roots) > 1:
        raise ValueError('rundir disagrees between certification inputs and output')
    return next(iter(roots), None)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _approved(root):
    # Consume the approval owner's verifier, never a local copy of its fingerprint.
    from ravel.workflow.workflow_state import verify_approval
    checkin = root / 'inputs/checkin1.json'
    approval = root / 'inputs/checkin1_approval.json'
    pins = (_digest(checkin), _digest(approval))
    errors = verify_approval(str(root))
    if errors:
        raise ValueError('certification approval binding: ' + '; '.join(errors))
    doc = read_json(checkin)
    record = read_json(approval)
    if pins != (_digest(checkin), _digest(approval)):
        raise ValueError('certification approval changed while reading tolerances')
    approved = tolerances(doc.get('sections', {}).get(SECTION), complete=True)
    return approved, {'checkin1_sha256': pins[0], 'approval_sha256': pins[1],
                      'input_fingerprint': record['input_fingerprint']}


def _deviation_rows(raw):
    """Only table rows under the declared ledger header can name an exact change."""
    header = None
    required = {'parameter', 'from', 'to', 'why', 'touches'}
    for line in raw.splitlines():
        line = line.strip()
        if not (line.startswith('|') and line.endswith('|')):
            header = None
            continue
        cells = [c.strip().strip('`') for c in line[1:-1].split('|')]
        if set(cells) == required and len(cells) == len(required):
            header = cells
            continue
        if header is None or len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        name = row['parameter'].removeprefix('--').replace('-', '_')
        if name not in DEFAULTS or not row['why'] or not row['touches']:
            continue
        try:
            before, after = json.loads(row['from']), json.loads(row['to'])
            tolerances({name: before})
            tolerances({name: after})
        except (ValueError, TypeError):
            continue
        yield {**row, 'parameter': name, 'from': before, 'to': after}


def bind_tolerances(rundir, supplied):
    """Return effective controls and provenance; changed controls require exact ledger rows.

    ``supplied`` contains only explicit CLI overrides. The first approval and its
    CHECK-IN remain unchanged. A deviation row discloses a tighter control only; a
    looser one is refused until a renewed approval carries it in the section.
    Decision-gate callers can use the returned pins with gate='deviation' and the
    interface's action {kind, digest, summary, pins, node_id, rung, scope}.
    """
    root = Path(rundir).resolve()
    approved, pins = _approved(root)
    effective = tolerances({**approved, **supplied}, complete=True)
    changes = [name for name in DEFAULTS if effective[name] != approved[name]]
    looser = [name for name in changes if (effective[name] - approved[name]) * LOOSER[name] > 0]
    if looser:
        raise ValueError('; '.join(f'{name} {effective[name]} is looser than the approved {approved[name]}'
                                   for name in looser)
                         + '; a looser control needs a renewed CHECK-IN 1 approval of the changed section. '
                           'A DEVIATIONS.md row discloses a tighter control; it never loosens an approved one')
    rows, ledger_pin = [], None
    if changes:
        path = root / 'DEVIATIONS.md'
        raw = path.read_bytes() if path.is_file() else b''
        ledger_pin = hashlib.sha256(raw).hexdigest()
        candidates = list(_deviation_rows(raw.decode('utf-8')))
        for name in changes:
            matches = [r for r in candidates if r['parameter'] == name
                       and r['from'] == approved[name] and r['to'] == effective[name]]
            if len(matches) != 1:
                raise ValueError(f'{name} changed from approved {approved[name]} to {effective[name]}; '
                                 'requires one exact DEVIATIONS.md row naming parameter/from/to/why/touches')
            rows.append(matches[0])
    binding = {'schema_version': 1, 'approved': approved, 'effective': effective,
               **pins, 'deviations': rows}
    if rows:
        binding['deviations_sha256'] = ledger_pin
    return effective, binding


def verify_binding(rundir, binding):
    """Read-only consumer seam; recheck approval and any recorded ledger bytes."""
    try:
        if type(binding) is not dict or type(binding.get('schema_version')) is not int or binding['schema_version'] != 1:
            raise ValueError('certification_tolerances requires binding schema_version 1')
        effective = tolerances(binding.get('effective'), complete=True)
        tolerances(binding.get('approved'), complete=True)
        _, expected = bind_tolerances(rundir, effective)
        if binding != expected:
            raise ValueError('certification_tolerances binding changed or disagrees with approval/deviation')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [str(exc)]
    return []


def verify_report(rundir, report):
    """Executor certificate handoff: verify controls and the two legacy headline fields."""
    if type(report) is not dict:
        return ['certification_tolerances report must be an object']
    binding = report.get(SECTION)
    if binding is None:
        return [f'report has no {SECTION} binding: it was not produced under an approved CHECK-IN 1']
    if type(binding) is dict and binding.get('governance') == 'diagnostic':
        return [f'{SECTION}: a diagnostic report is not bound to an approved CHECK-IN 1']
    errors = verify_binding(rundir, binding)
    if errors:
        return errors
    for name in ('driving_tol', 'mu95_bound'):
        value = report.get(name)
        if type(value) not in (int, float) or value != binding['effective'][name]:
            errors.append(f'{name} disagrees with certification_tolerances.effective')
    return errors
