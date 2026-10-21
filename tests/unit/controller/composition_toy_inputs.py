"""Source injected into composition workers for explicitly declared toy inputs."""

SCRIPT = r'''
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
'''
