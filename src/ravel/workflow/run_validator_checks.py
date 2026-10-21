"""Explicit in-process adapters for allowlisted run checks; no module-name execution.

An adapter answers passed (True), failed (False) or inconclusive (None, the evidence decides
neither way). An inconclusive result never counts as a pass, and an exception is a failure.
Inputs come from the sealed work order's ``check_inputs``; a pinned result of an earlier stage
is read only through its registered custody (``_custody_json``). An adapter that needs no
``check_inputs`` (the run-state stage checks, the figure and deviation checks) finds its inputs in
the run tree, so a role without a sealed order can run it; one that names a parameter cannot.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

from .broker import confined
from .state_io import read_json

TRAP_CHECK = 'check:validation.validate_run_state.check_trap_sweep'
ROUTE_CHECK = 'check:validation.validate_run_state.check_route'
FIGURE_CONTRACT_CHECK = 'check:validation.validate_run_state.check_figure_contract'
CENSUS_CHECK = 'check:validation.validate_run_state.check_resource_census'
FIGURES_CHECK = 'check:validation.verify_pack.check_figures'
# The run-state stage checks, one validator function each.
STATE_CHECKS = {TRAP_CHECK: 'check_trap_sweep', ROUTE_CHECK: 'check_route',
                FIGURE_CONTRACT_CHECK: 'check_figure_contract', CENSUS_CHECK: 'check_resource_census'}


@dataclass
class RunCheckInput:
    rundir: Path
    work_order: dict
    workspace: Path
    validator_executed: bool = field(default=False, init=False)

    def call(self, function, *args, **kwargs):
        self.validator_executed = True
        return function(*args, **kwargs)

    def parameters(self, check_id):
        value = self.work_order.get('check_inputs', {}).get(check_id, {})
        if type(value) is not dict:
            raise ValueError('check_inputs must contain parameter objects')
        return value

    def path(self, relative):
        path = confined(self.rundir, relative)
        if not path.exists():
            raise ValueError('validator input is missing')
        return path


def _state(value, check_id):
    from ravel.validation import validate_run_state as validator
    contract = read_json(value.path('inputs/task_contract.json'))
    facts = ({'trap_sweep_path': 'inputs/trap_sweep.json' if
              (value.rundir / 'inputs/trap_sweep.json').is_file() else None}
             if check_id == TRAP_CHECK else validator.discover_facts(str(value.rundir), contract))
    check = getattr(validator, STATE_CHECKS[check_id])
    status, path, checks = value.call(check, str(value.rundir), contract, facts, 'R', False)
    # PASS and WARN are the validator's declared successes; N/A and a legacy waiver decide nothing.
    return (True if status in {'PASS', 'WARN'} else False if status == 'FAIL' else None), {
        'status': status, 'path': path, 'checks': checks}


def _contract(value, check_id):
    from ravel.validation.validate_task_contract import validate
    errors = value.call(validate, read_json(value.path('inputs/task_contract.json')))
    return not errors, {'errors': errors}


def _json_input(value, named):
    """A JSON input named by a run-relative path, or by a ``{path, sha256}`` pin whose bytes must still match it (a
    controller binds a reviewed step's adopted output that way)."""
    if type(named) is dict:
        from .world_digest import read_bound
        if set(named) != {'path', 'sha256'} or type(named['path']) is not str:
            raise ValueError('a pinned validator input is a {path, sha256} pin')
        value.path(named['path'])
        raw, sha = read_bound(value.rundir, named['path'])
        if sha != named['sha256']:
            raise ValueError('validator input pin changed: ' + named['path'])
        return json.loads(raw)
    return read_json(value.path(named))


def _normalization(value, check_id):
    from ravel.physics.normalization_ledger import check
    options = value.parameters(check_id)
    ledger = _json_input(value, options.get('ledger', 'inputs/normalization_ledger.json'))
    delivered = _json_input(value, options['delivered']) if 'delivered' in options else None
    report = value.call(check, ledger, delivered=delivered)
    return report['passed'], report


def _closure(value, check_id):
    from ravel.validation.input_closure import check
    options = value.parameters(check_id)
    report = value.call(check, value.rundir, options['fit'], options['reference'])
    return report['independent'], report


def _cutflow(value, check_id):
    from ravel.validation import validate_cutflow
    options = value.parameters(check_id)
    required = {'signal', 'routine', 'sigma_pb', 'lumi_fb', 'tables_dir', 'grid', 'm_parent', 'm_lsp', 'srs'}
    optional = {'sr_reader', 'label', 'exclusion', 'driving_sr_override', 'driving_tol',
                'contributing_tol', 'mu95_bound', 'interp_max_span', 'certification_context'}
    if not required <= options.keys() or options.keys() - required - optional:
        raise ValueError('cutflow needs the declared typed input parameters')
    path_keys = {'signal', 'tables_dir', 'exclusion', 'certification_context'}
    argv = []
    for key, raw in options.items():
        if type(raw) not in (str, int, float):
            raise ValueError('cutflow parameters must be scalar values')
        item = str(value.path(raw)) if key in path_keys else str(raw)
        argv += ['--' + key.replace('_', '-'), item]
    # The validator's own report lives in the check's scratch directory, never among the worker's
    # outputs: a declared output of the same name is not removed or replaced by its self-check.
    out = confined(value.workspace, 'scratch/self-checks/cutflow-self-check.md')
    out.parent.mkdir(parents=True, exist_ok=True)
    # A new result is mandatory, even if a prior failed attempt left output bytes.
    out.unlink(missing_ok=True)
    out.with_suffix('.json').unlink(missing_ok=True)
    value.call(validate_cutflow.main, argv + ['--out', str(out)])
    report = read_json(out.with_suffix('.json'))
    return report['verdict'] == 'PASS', report


def _deviations(value, check_id):
    from ravel.validation import verify_pack
    report = verify_pack.Report()
    documents = {rel: read_json(value.path(rel)) for rel in verify_pack.find_artifact_jsons(str(value.rundir))}
    value.call(verify_pack.check_deviations_ledger, report, str(value.rundir), documents)
    return not any(row[0] == 'FAIL' for row in report.lines), {'checks': report.lines}


def _figures(value, check_id):
    """Every figures.json of the run (or the one named in check_inputs): files on disk, captions, figure contract."""
    from ravel.validation import verify_pack
    root, named = str(value.rundir), value.parameters(check_id).get('figures')
    names = [named] if named else [rel for rel in verify_pack.find_artifact_jsons(root) if Path(rel).name == 'figures.json']
    index, report, declared = verify_pack.file_index(root), verify_pack.Report(), 0
    for rel in names:
        document = read_json(value.path(rel))
        if type(document) is not dict:
            raise ValueError(f'{rel} must be a JSON object')
        declared += len(document.get('figures') or [])
        value.call(verify_pack.check_figures, report, root, index, rel, document)
    levels = {row[0] for row in report.lines}
    diagnostics = {'checks': report.lines, 'figures_json': names, 'figures_declared': declared}
    # No figures.json, no declared figure, or a caption or contract target left open decides nothing.
    return (False if 'FAIL' in levels else None if not declared or 'WARN' in levels else True), diagnostics


def _certificate(value, check_id):
    from ravel.validation.certificates import validate_certificate
    options = value.parameters(check_id)
    value.path(options['path'])
    contract = read_json(value.path('inputs/task_contract.json'))
    report = value.call(validate_certificate, value.rundir, options['path'], kind=options['kind'],
                        contract=contract, required_subjects=options.get('required_subjects', []), live=True)
    return report['status'] == 'PASS', report


def _calibration(value, check_id):
    from ravel.validation.calibration_checks import validate_spec
    options = value.parameters(check_id)
    report = value.call(validate_spec, read_json(value.path(options['spec'])), value.rundir)
    return True, report


def _custody_json(value, check_id, key):
    """A JSON input the sealed order names as a pin, read once and checked against its registered custody."""
    from ravel.validation import calibration_checks
    pin = value.parameters(check_id).get(key)
    if type(pin) is not dict:
        raise ValueError(f'{check_id} needs the pinned {key} input in check_inputs')
    value.path(pin.get('path', ''))
    return json.loads(calibration_checks.read_custody(pin, value.rundir, f'{check_id} {key}'))


# ---- detector calibration (detector-calibrator) ------------------------------------------------

CALIBRATION_SPEC_CHECKS = ('check:calibration_target_disjoint', 'check:confirmation_separation',
                           'check:anchored_bounds', 'check:imported_calibration', 'check:calibration_no_global_scalar',
                           'check:signal_model_complete_before_calibration')
CALIBRATION_RECEIPT_CHECKS = ('check:calibration_before_and_after', 'check:calibration_frozen')


def _calibration_spec(value, check_id):
    """One calibration-spec invariant; the whole-spec validator covers anchoring, imports and scalars."""
    from ravel.validation import calibration_checks as cal
    spec = read_json(value.path(value.parameters(check_id)['spec']))
    if check_id == 'check:calibration_target_disjoint':
        return True, value.call(cal.calibration_target_disjoint, spec, value.rundir)
    if check_id == 'check:confirmation_separation':
        return True, value.call(cal.confirmation_separation, spec, value.rundir)
    if check_id == 'check:signal_model_complete_before_calibration':
        pending = value.call(cal.signal_model_complete_before_calibration, spec, value.rundir)
        # A scoped approximation is admissible only after its own R2 authority: not yet a pass.
        return (None if pending else True), {'approximation_pending_authority': pending}
    report = value.call(cal.validate_spec, spec, value.rundir)
    if check_id == 'check:anchored_bounds' and report['outside_band']:
        return None, {**report, 'reason': 'candidates outside the anchored band await R3 authority'}
    return True, report


def _calibration_receipt(value, check_id):
    """Before-and-after scores and the frozen response, from the calibration's registered receipt."""
    from ravel.validation.calibration_checks import delivery_check
    receipt = _custody_json(value, check_id, 'receipt')
    return True, {'errors': value.call(delivery_check, receipt)}


ADAPTERS = {
    **{check: _state for check in STATE_CHECKS},
    'check:validation.validate_task_contract.validate': _contract,
    'check:physics.normalization_ledger.check': _normalization,
    'check:validation.validate_cutflow': _cutflow,
    'check:validation.input_closure.check': _closure,
    'check:validation.verify_pack.check_deviations_ledger': _deviations,
    FIGURES_CHECK: _figures,
    'check:validation.certificates.validate_certificate': _certificate,
    'ravel.validation.calibration_checks': _calibration,
    **{check: _calibration_spec for check in CALIBRATION_SPEC_CHECKS},
    **{check: _calibration_receipt for check in CALIBRATION_RECEIPT_CHECKS},
}


def run(check_id, value: RunCheckInput):
    """Execute one explicit adapter and preserve invalid/missing evidence as failure."""
    from .review_projection_checks import result
    try:
        passed, diagnostics = ADAPTERS[check_id](value, check_id)
    except (Exception, SystemExit) as exc:
        passed, diagnostics = False, {'error': type(exc).__name__, 'detail': str(exc)}
    status = 'inconclusive' if passed is None else 'passed' if passed is True else 'failed'
    return {**result(check_id, [], status=status, diagnostics=diagnostics),
            'validator_executed': value.validator_executed}
