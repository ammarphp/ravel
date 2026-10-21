"""Inert launch program of canary C1: the confined operate steps of the analysis route run this file.

The route analysis the scripted worker writes binds it into the plan before CHECK-IN 1
(``route_analysis.launches``); the step graph starts it as a materialised confined launch, inside
the step's attempt ``outputs`` directory, with every input resolved from verified custody
(``@input:`` tokens). It never calls a model or the network. Standard library only.

Usage: ``python -I -c <this source> <mode> <config json> <input path>...``

- ``recast``: run the supplied analysis script at the smoke point; the smoke qualifies the script
  when its value lies within its own uncertainty of the request's stated expectation.
- ``waypoint``: the early-verification waypoint from the smoke record.
- ``point``: run the supplied script over the approved grid (the script tabulates the points it is
  given) and keep this point's own row. A script that leaves the point out fails this launch, so
  the point stays an explicit hole of the approved grid.
- ``assemble``: the scan table from the completed point results, with the point population.
- ``final``: the final figure index over the assembled table.

The reviewer-owed checks of the analysis route (cutflow, normalization ledger, acceptance
certificate, plot lint, figure index) read validation documents this program writes beside its
outputs: a declared unit-weight toy enumeration (``toy_inputs`` below, the same enumeration the
controller's own composition gate uses), never a claim about the toy observable itself.
"""
# Note: no brace-enclosed lowercase name may appear in this source: the route's unbound-placeholder check
# reads every bound launch argv, and this source is one argv element.

import json
import math
import struct
import zlib


def _toy_png(acceptance):
    width, height = 160, 120
    pixels = bytearray([255] * (width * height * 3))

    def rectangle(x0, y0, x1, y1, color):
        for y in range(y0, y1):
            for x in range(x0, x1):
                start = (y * width + x) * 3
                pixels[start:start + 3] = bytes(color)

    rectangle(24, 16, 25, 97, (0, 0, 0))
    rectangle(24, 96, 145, 97, (0, 0, 0))
    rectangle(55, 96 - round(80 * acceptance), 115, 96, (45, 105, 180))
    for y in (16, 56, 96):
        rectangle(21, y, 25, y + 1, (0, 0, 0))
    for x in (24, 84, 144):
        rectangle(x, 96, x + 1, 100, (0, 0, 0))

    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))

    rows = b''.join(b'\0' + pixels[y * width * 3:(y + 1) * width * 3]
                    for y in range(height))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'tEXt', b'Description\0Toy acceptance: 50 of 100 rows; axes 0 to 1')
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def _toy_pdf(acceptance):
    drawing = (
        '0 0 0 RG 1 w 40 35 m 40 115 l S 40 35 m 160 35 l S\n'
        '0.176 0.412 0.706 rg 70 35 60 %s re f\n'
        '0 0 0 rg BT /F1 8 Tf 25 32 Td (0) Tj ET\n'
        'BT /F1 8 Tf 20 72 Td (0.5) Tj ET\n'
        'BT /F1 8 Tf 25 112 Td (1) Tj ET\n'
        'BT /F1 8 Tf 38 23 Td (0) Tj 59 0 Td (0.5) Tj 60 0 Td (1) Tj ET\n'
        'BT /F1 8 Tf 75 10 Td (row fraction) Tj ET\n'
        'BT /F1 8 Tf 1 0 0 1 4 125 Tm (acceptance) Tj ET\n'
        'BT /F1 9 Tf 45 140 Td (50 / 100 rows: acceptance 0.5) Tj ET\n'
    ) % (80 * acceptance)
    stream = drawing.encode('ascii')
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 210 160] '
        b'/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length ' + str(len(stream)).encode('ascii') + b' >>\nstream\n'
        + stream + b'endstream',
    ]
    result = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(('%d 0 obj\n' % number).encode('ascii') + body + b'\nendobj\n')
    xref = len(result)
    result.extend(('xref\n0 %d\n0000000000 65535 f \n' % len(offsets)).encode('ascii'))
    for offset in offsets[1:]:
        result.extend(('%010d 00000 n \n' % offset).encode('ascii'))
    result.extend(('trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n'
                   % (len(offsets), xref)).encode('ascii'))
    return bytes(result)


def toy_inputs(routine, step_id, attempt, report_path=None, output_prefix=None):
    weights = [1.0] * 100
    selected = weights[:50]
    generated_sumw = sum(weights)
    generated_sumw2 = sum(w * w for w in weights)
    selected_sumw = sum(selected)
    selected_sumw2 = sum(w * w for w in selected)
    sigma_pb, luminosity_pb = 2.0, 1.0
    scale = sigma_pb * luminosity_pb / generated_sumw
    acceptance = selected_sumw / generated_sumw
    ledger = {
        'schema_version': 1, 'sample': 'declared unit-weight toy',
        'luminosity': {'value': luminosity_pb, 'unit': 'pb^-1', 'source': 'stated toy model'},
        'sigma': {'value': sigma_pb, 'unit': 'pb', 'order': 'LO', 'tool': 'toy enumeration',
                  'pdf': 'none (toy model)', 'scales': 'none (toy model)',
                  'process_basis': 'declared toy process', 'source': 'stated toy model'},
        'generated': {'sumw': generated_sumw, 'sumw2': generated_sumw2},
        'selected': {'X': {'sumw': [selected_sumw], 'sumw2': [selected_sumw2]}},
        'bin_convention': 'per-bin',
    }
    cuts = []
    for name, expression, rows in [('all events', None, weights),
                                    ('selected', 'row_index < 50', selected)]:
        sumw, sumw2 = sum(rows), sum(w * w for w in rows)
        cuts.append({'name': name, 'expression': expression, 'raw': len(rows),
                     'sumw': sumw, 'sumw2': sumw2, 'yield': scale * sumw,
                     'yield_uncertainty': scale * math.sqrt(sumw2)})
    cutflow = {'schema_version': 1, 'kind': 'cutflow',
               'quantity': {'weight_convention': 'signed'}, 'recipe': routine,
               'unit': 'events', 'normalization_scale': scale,
               'regions': [{'name': 'X', 'cuts': cuts}]}
    # The reference is fixed independently of the enumerated selection above.
    published_acceptance = .5
    ratio = acceptance / published_acceptance
    residual = abs(1 - ratio)
    tolerances = {'driving_tol': .15, 'contributing_tol': .25, 'mu95_bound': .10,
                  'tail_events': 5, 'driving_factor': 1.5, 'interp_max_span': 200.0}
    driving_ok = residual <= tolerances['driving_tol']
    verdict = ('FAIL' if not driving_ok else 'PASS' if residual <= tolerances['mu95_bound']
               else 'WARN' if residual <= 1.5 * tolerances['mu95_bound'] else 'FAIL')
    acceptance_report = {
        'rows': [{'sr': 'X', 'role': 'driving', 'mine': acceptance, 'pub': published_acceptance,
                  'events': len(selected), 'node': 'grid node (100, 1)', 'off_grid': False, 'ratio': ratio}],
        'certification_tolerances': {'approved': dict(tolerances), 'effective': dict(tolerances)},
        'driving_tol': tolerances['driving_tol'], 'mu95_bound': tolerances['mu95_bound'],
        'worst_driving_residual': residual, 'verdict': verdict,
    }
    scientific_descriptors = {
        'P05': {'basis': ['selected_sumw:X'], 'units': 'weighted_rows',
                'sign_convention': 'signed_weight_sum', 'covariance': [[selected_sumw2]], 'population': ['X']},
        'E07': {'pdf_member': 'none finite toy enumeration',
                'generation_settings': {'kind': 'finite_enumeration', 'rows': len(weights), 'selected_rows': len(selected)}},
        'E08': {'spectrum': {}, 'invisible_states': []},
        'E10': {'beam_energy': 'none finite toy enumeration', 'seed': 'none deterministic enumeration'},
        'E13': {'weight_names': ['nominal'], 'reentrant': False, 'merged': False, 'single_weight': True},
        'E17': {'bin_ids': ['X']},
        'E18': {'perturbative_order': 'LO', 'process_basis': [ledger['sigma']['process_basis']]},
    }
    documents = {
        'validation/acceptance-report.json': acceptance_report,
        'validation/normalization-ledger.json': ledger,
        'validation/yields.json': {'X': [scale * selected_sumw]},
        'validation/cutflow.json': cutflow,
        'validation/tables/submission.yaml': {
            'description': 'acceptance times efficiency SRX toy', 'data_file': 'grid.yaml'},
        'validation/tables/grid.yaml': {
            'independent_variables': [
                {'header': {'name': 'parent'}, 'values': [{'value': 100}]},
                {'header': {'name': 'lsp'}, 'values': [{'value': 1}]}],
            'dependent_variables': [{'header': {'name': 'acceptance'},
                                     'values': [{'value': .5}]}]},
    }
    files = {path: json.dumps(doc) for path, doc in documents.items()}
    files['validation/toy.png'] = _toy_png(acceptance)
    files['validation/toy.pdf'] = _toy_pdf(acceptance)
    prefix = output_prefix or ('steps/' + step_id + '/attempts/' + str(attempt) + '/outputs/')
    metadata = {
        'scientific_descriptors': scientific_descriptors,
        'validator_inputs': {
            'check:validation.certify_acceptance': {'document': prefix + 'validation/acceptance-report.json'},
            'check:physics.normalization_ledger.check': {
                'ledger': prefix + 'validation/normalization-ledger.json',
                'delivered': prefix + 'validation/yields.json'},
            'check:validation.validate_cutflow': {
                'signal': prefix + 'validation/cutflow.json', 'routine': routine,
                'sigma_pb': sigma_pb, 'lumi_fb': .001,
                'tables_dir': prefix + 'validation/tables', 'grid': 'toy',
                'm_parent': 100, 'm_lsp': 1, 'srs': 'X', 'driving_sr_override': 'X'},
        },
        'figure_spec': {'x_scale': 'linear', 'y_scale': 'linear',
                        'x_range': [0, 1], 'y_range': [0, 1],
                        'x_label': 'row fraction', 'y_label': 'acceptance'},
        'n_figures': 1,
        'figures': [{'id': 'F1', 'filename': prefix + 'validation/toy.png',
                     'pdf': prefix + 'validation/toy.pdf',
                     'what_it_shows': '50 of 100 unit-weight toy rows pass; acceptance 0.5'}],
    }
    if report_path is not None:
        report = prefix + report_path.removeprefix('outputs/')
        metadata['validator_inputs']['check:validation.plot_lint'] = {'document': report}
        metadata['validator_inputs']['check:validation.verify_pack.check_figures'] = {'figures': report}
    return metadata, files


# ---- the launch modes --------------------------------------------------------------------------

import subprocess
import sys
import uuid
from pathlib import Path


def _attempt():
    """The attempt number: the launch runs in ``steps/<step>/attempts/<n>/outputs``."""
    try:
        return int(Path.cwd().parent.name)
    except ValueError:
        return 1


def _write(path, value):
    target = Path(path[len('outputs/'):] if path.startswith('outputs/') else path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        target.write_bytes(value)
    else:
        target.write_text(value if isinstance(value, str) else json.dumps(value, indent=1, sort_keys=True))


def _validation(config, report):
    """Validation documents for the route's reviewer-owed checks, written beside the step's outputs."""
    metadata, files = toy_inputs(config['routine'], config['step'], _attempt(), report_path=report)
    for path, value in files.items():
        _write(path, value)
    return metadata


def _table(script, output, points):
    """Run the supplied analysis script once; a failed run fails this launch with its own status."""
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([sys.executable, '-I', script, output, *[repr(float(g)) for g in points]])
    if done.returncode != 0:
        sys.stderr.write(f'the supplied analysis script exited with status {done.returncode}\n')
        raise SystemExit(done.returncode or 1)
    with open(output) as stream:
        return json.load(stream)


def _row(table, value):
    return next((r for r in table.get('rows') or () if isinstance(r, dict) and r.get('coupling') == value), None)


def _pdf(path, fraction):
    _write(path, _toy_pdf(max(0.0, min(1.0, fraction))))


def recast(config, script):
    symbol, smoke = config['symbol'], float(config['smoke'])
    table = _table(script, 'smoke/toy-table.json', [smoke])
    row = _row(table, smoke)
    if row is None:
        sys.stderr.write('the supplied script wrote no row for the smoke point %s = %r\n' % (symbol, smoke))
        raise SystemExit(3)
    expected = float(config['expected'])
    within = abs(row['observable'] - expected) <= row['uncertainty']
    metadata = _validation(config, config['outputs'][0])
    document = {'schema_version': 1, 'kind': 'toy-recast', 'routine': config['routine'],
                'samples': ['the toy observable at %s = %r' % (symbol, smoke)], 'events': row['observable'],
                'detector_mode': config['detector_mode'], 'rows': [row],
                'toy_observable_execution': table.get('toy_observable_execution'),
                'qualification': {'routine': config['routine'], 'status': 'qualified' if within else 'failed',
                                  'basis': 'smoke value %r ± %r against the stated expectation %r'
                                           % (row['observable'], row['uncertainty'], expected)},
                **metadata, 'attempt': _attempt(), 'execution': uuid.uuid4().hex}
    _write(config['outputs'][0], document)
    _write(config['outputs'][1], {'schema_version': 1, 'kind': 'toy-histograms',
                                  'bins': [[row['coupling'], row['observable'], row['uncertainty']]]})
    return 0  # a smoke outside its expectation is recorded as a failed qualification, for the controller to judge


def waypoint(config, recast_path):
    with open(recast_path) as stream:
        smoke = json.load(stream)
    row = (smoke.get('rows') or [None])[0]
    metadata = _validation(config, config['outputs'][0])
    document = {'schema_version': 1, 'kind': 'toy-waypoint',
                'summary': 'the smoke value of the toy observable against the stated expectation',
                'element': f'N at {config["symbol"]} = {config["smoke"]}',
                'expectation': f'N = {config["expected"]} within the smoke uncertainty',
                'observed': row, 'evidence': 'the smoke record of recast.smoke',
                **metadata, 'attempt': _attempt(), 'execution': uuid.uuid4().hex}
    _write(config['outputs'][0], document)
    _pdf(config['outputs'][1], (row or {}).get('observable', 0) / 100.0)
    return 0


def point(config, script):
    symbol, value = config['symbol'], config['coordinates'][config['axis']]
    table = _table(script, 'toy-table.json', config['grid'])
    row = _row(table, value)
    if row is None:
        sys.stderr.write('the supplied script wrote no row for %s = %r; point %s has no result\n'
                         % (symbol, value, config['tag']))
        return 5
    metadata = _validation(config, config['outputs'][0])
    _write(config['outputs'][0], {'schema_version': 1, 'kind': 'toy-point-result', 'tag': config['tag'],
                                  'parameters': config['coordinates'], 'row': row,
                                  'detector_mode': config['detector_mode'],
                                  'toy_observable_execution': table.get('toy_observable_execution'),
                                  **metadata, 'attempt': _attempt(), 'execution': uuid.uuid4().hex})
    return 0


def assemble(config, *paths):
    results = []
    for path in paths:
        with open(path) as stream:
            results.append(json.load(stream))
    by_tag = {r.get('tag'): r for r in results}
    population = [{'tag': p['id'], 'parameters': p['parameters'],
                   'status': 'completed' if p['id'] in by_tag else 'missing'} for p in config['points']]
    rows = [by_tag[p['id']]['row'] for p in config['points'] if p['id'] in by_tag]
    missing = [p['tag'] for p in population if p['status'] != 'completed']
    metadata = _validation(config, config['outputs'][0])
    keep = {key: metadata[key] for key in ('validator_inputs',)}
    keep['validator_inputs'] = {k: v for k, v in keep['validator_inputs'].items()
                                if k == 'check:physics.normalization_ledger.check'}
    _write(config['outputs'][0], {'schema_version': 1, 'kind': 'toy-observable-table', 'model': config['model'],
                                  'rows': rows, 'point_population': population,
                                  'points': [{'tag': r.get('tag'), 'row': r.get('row')} for r in results],
                                  'n_planned': len(population), 'n_done': len(rows), 'n_missing': len(missing),
                                  'missing_tags': missing, **keep,
                                  'attempt': _attempt(), 'execution': uuid.uuid4().hex})
    _pdf(config['outputs'][1], len(rows) / max(1, len(population)))
    return 0


def final(config, scan_path):
    with open(scan_path) as stream:
        scan = json.load(stream)
    metadata = _validation(config, config['outputs'][0])
    _write(config['outputs'][0], {'schema_version': 1, 'kind': 'toy-figures',
                                  'caption': f'N against {config["symbol"]} with its uncertainty',
                                  'rows': scan.get('rows'), **metadata,
                                  'attempt': _attempt(), 'execution': uuid.uuid4().hex})
    _pdf(config['outputs'][1], len(scan.get('rows') or ()) / max(1, scan.get('n_planned') or 1))
    return 0


MODES = {'recast': recast, 'waypoint': waypoint, 'point': point, 'assemble': assemble, 'final': final}


def main(argv):
    mode, config, paths = argv[0], json.loads(argv[1]), argv[2:]
    return MODES[mode](config, *paths)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
