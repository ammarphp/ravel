"""Recompute delivery findings, using declared evidence only.

``check_delivery(rundir, pack)`` writes outputs/delivery-checks.json and returns one
finding per check (check, status, severity, detail, receipt). A pack may declare ``deliverables`` with ``path``,
``absolute_yield``, and pinned ``normalization_ledger``, ``figure_comparison``
or ``counting_inputs``. The figure pin names the ordinary
figure-comparison task document. Legacy yield pointers still require a ledger;
absence never earns an absolute-yield pass. No reference or covariance is guessed.
"""
import hashlib
import json
from pathlib import Path


def _read(root, pin):
    if type(pin) is not dict or not {'path', 'sha256'} <= set(pin):
        raise ValueError('delivery input requires a path and sha256 pin')
    path = Path(pin['path'])
    path = path if path.is_absolute() else root / path
    path = path.absolute()
    if root not in path.parents or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('delivery input must be a regular file inside the run')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('delivery input pin digest differs')
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('duplicate delivery input key')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('nonfinite delivery input')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


def _write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('delivery receipt must be a regular run endpoint')
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    path.write_bytes(raw)
    return {'path': relative, 'sha256': hashlib.sha256(raw).hexdigest()}


def counting_calibration(sr, *, signal_strength=1., level=.05, poi_cap=128.):
    import math
    from ravel.validation import statistical_calibration as calibration
    count = sr.get('n')
    if type(count) is float and math.isfinite(count) and count.is_integer():
        count = int(count)
    if sr.get('db') != 0 or type(count) is not int or not sr.get('s', 0) > 0:
        return {'status': 'not_applicable', 'detail': 'requires one integer Poisson count, known background and positive signal',
                'coverage': {'status': 'not_evaluated', 'general_likelihood_coverage_validated': False}}
    try:
        # Bound the independent reference scan without altering the requested
        # pyhf scan. A bound that cannot resolve the root remains above_scan.
        cap = min(poi_cap, math.nextafter((calibration.MAX_MEAN - sr['b']) / sr['s'], 0.))
        reference = calibration.known_background_poisson_upper_limit(count, sr['s'], sr['b'], level=level, poi_cap=cap)
        coverage = calibration.known_background_poisson_coverage(signal_strength, sr['s'], sr['b'], level=level)
    except (ValueError, OverflowError, ArithmeticError) as exc:
        return {'status': 'not_applicable', 'detail': 'bounded exact counting reference unavailable: ' + str(exc),
                'coverage': {'status': 'not_evaluated', 'general_likelihood_coverage_validated': False}}
    return {'status': 'pass' if reference['status'] == coverage['status'] == 'resolved' else 'missing_input',
            'reference': reference, 'coverage': coverage,
            'detail': 'independent count-ordered exact Poisson law; no equivalence to asymptotic qtilde inferred'}


def check_delivery(rundir: Path, pack: dict) -> list[dict]:
    from ravel.physics import normalization_ledger, figure_comparison
    from ravel.validation.normalization_ledger import parity_rows
    root = Path(rundir).resolve()
    findings = []
    pack['coverage'] = {'status': 'not_evaluated', 'general_likelihood_coverage_validated': False}
    deliveries = list(pack.get('deliverables') or [])
    pointers = pack.get('pointers') or {}
    if not deliveries:
        # Old packs advertise absolute SR yields by their summary and pointer.
        deliveries = [{'path': pointers.get('sr_yields') or pointers.get('yields') or 'result-pack',
                       'absolute_yield': bool(pack.get('sr_yields_summary')),
                       **{k: pack[k] for k in ('normalization_ledger', 'figure_comparison', 'counting_inputs') if k in pack}}]
    for i, delivery in enumerate(deliveries):
        target = str(delivery.get('path', 'result-pack'))
        for name in ('normalization_ledger', 'figure_comparison', 'statistical_calibration'):
            key = 'counting_inputs' if name == 'statistical_calibration' else name
            required = name == 'normalization_ledger' and delivery.get('absolute_yield') is True
            row = {'check': name, 'deliverable': target,
                   'status': 'missing_input' if required else 'not_applicable',
                   'severity': 'A' if required else 'C',
                   'detail': 'absolute yield requires a pinned normalization ledger with delivered bins' if required else 'no applicable declared input',
                   'receipt': None}
            if key in delivery:
                row['severity'] = 'A'
                try:
                    document = _read(root, delivery[key])
                    if name == 'normalization_ledger':
                        delivered = document.get('delivered')
                        if delivered is None and required:
                            row.update(status='missing_input', detail='ledger has no independently delivered per-bin yields')
                            findings.append(row); continue
                        result = normalization_ledger.check(document, delivered=delivered, certifier_sigma_fb=pack.get('sigma_ref_fb'))
                        result['parity_rows'] = parity_rows(document, delivered=delivered, certifier_sigma_fb=pack.get('sigma_ref_fb')) if delivered is not None else []
                        row.update(status='pass' if result['passed'] else 'fail', detail=', '.join(r['code'] for r in result['failures']) or 'all delivered yields recomputed')
                    elif name == 'figure_comparison':
                        directory = root / 'outputs' / f'delivery-comparison-{i}'
                        # Each invocation retains a fresh ordinary comparator receipt.
                        suffix = 0
                        while directory.exists():
                            suffix += 1; directory = root / 'outputs' / f'delivery-comparison-{i}-{suffix}'
                        result = figure_comparison.run(document, root, directory)
                        verdicts = list(result.get('verdicts', {}).values())
                        row.update(status='fail' if any(v.upper() in ('FAIL', 'FAILED') for v in verdicts) else 'pass' if verdicts else 'missing_input',
                                   detail='ordinary fidelity comparator under declared transformations')
                    else:
                        result = counting_calibration(document)
                        row.update(status=result['status'], detail=result['detail'])
                        pack['coverage'] = result['coverage']
                    row['receipt'] = _write(root, f'outputs/delivery-check-{i}-{name}.json', result)
                except (ValueError, OSError, KeyError, TypeError, ArithmeticError) as exc:
                    row.update(status='fail', detail=str(exc))
            findings.append(row)
    pack['coverage'] = pack.get('coverage') or {'status': 'not_evaluated', 'general_likelihood_coverage_validated': False}
    _write(root, 'outputs/delivery-checks.json', {'schema_version': 1, 'check_results': findings, 'coverage': pack['coverage']})
    return findings
