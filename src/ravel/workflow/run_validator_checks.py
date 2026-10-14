"""Explicit in-process adapters for allowlisted run checks; no module-name execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .broker import confined
from .state_io import read_json

TRAP_CHECK = 'check:validation.validate_run_state.check_trap_sweep'
ROUTE_CHECK = 'check:validation.validate_run_state.check_route'


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
    check = validator.check_trap_sweep if check_id == TRAP_CHECK else validator.check_route
    status, path, checks = value.call(check, str(value.rundir), contract, facts, 'R', False)
    return status in {'PASS', 'WARN'}, {'status': status, 'path': path, 'checks': checks}


def _contract(value, check_id):
    from ravel.validation.validate_task_contract import validate
    errors = value.call(validate, read_json(value.path('inputs/task_contract.json')))
    return not errors, {'errors': errors}


def _normalization(value, check_id):
    from ravel.physics.normalization_ledger import check
    options = value.parameters(check_id)
    ledger = read_json(value.path(options.get('ledger', 'inputs/normalization_ledger.json')))
    delivered = read_json(value.path(options['delivered'])) if 'delivered' in options else None
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


ADAPTERS = {
    TRAP_CHECK: _state, ROUTE_CHECK: _state,
    'check:validation.validate_task_contract.validate': _contract,
    'check:physics.normalization_ledger.check': _normalization,
    'check:validation.validate_cutflow': _cutflow,
    'check:validation.input_closure.check': _closure,
    'check:validation.verify_pack.check_deviations_ledger': _deviations,
    'check:validation.certificates.validate_certificate': _certificate,
    'ravel.validation.calibration_checks': _calibration,
}


def run(check_id, value: RunCheckInput):
    """Execute one explicit adapter and preserve invalid/missing evidence as failure."""
    from .review_projection_checks import result
    try:
        passed, diagnostics = ADAPTERS[check_id](value, check_id)
    except (Exception, SystemExit) as exc:
        passed, diagnostics = False, {'error': type(exc).__name__, 'detail': str(exc)}
    return {**result(check_id, [], status='passed' if passed else 'failed', diagnostics=diagnostics),
            'validator_executed': value.validator_executed}
