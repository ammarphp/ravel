"""Apache-2.0 JSON worker for LHAPDF under its own Python interpreter.

This file uses only the standard library until main imports the external tool.
It launches nothing; the calling science workflow supplies method admission and
supervision. PDF uncertainty math is delegated to PDFSet.uncertainty, including
the installed set's confidence rescaling and replica central-value convention.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def request_sha256(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite worker number required')
    return float(value)


def validate_request(request):
    required = {'schema_version', 'kind', 'set', 'info', 'member_ids', 'member_values', 'confidence_level_percent'}
    if (not isinstance(request, dict) or set(request) != required
            or request['schema_version'] != 1 or request['kind'] != 'pdf-uncertainty-request'):
        raise ValueError('closed PDF uncertainty worker request required')
    if not isinstance(request['set'], str) or not request['set'] or any(c in request['set'] for c in '/\\\x00'):
        raise ValueError('PDF set basename required')
    info = request['info']
    if (not isinstance(info, dict) or info.get('error_type') not in ('hessian', 'symmhessian', 'replicas', 'hessian+as', 'symmhessian+as', 'replicas+as')
            or not isinstance(info.get('text'), str)
            or hashlib.sha256(info['text'].encode()).hexdigest() != info.get('sha256')):
        raise ValueError('source-bound .info ErrorType required')
    count = info.get('num_members')
    if type(count) is not int or count < 2 or request['member_ids'] != list(range(count)):
        raise ValueError('complete ordered worker member ids required')
    if any(type(i) is not int for i in request['member_ids']):
        raise ValueError('integer member ids required')
    base_kind = info['error_type'].split('+')[0]
    variations = count - 1 - (2 if info['error_type'].endswith('+as') else 0)
    if (variations < 1 or base_kind == 'hessian' and (variations < 2 or variations % 2)
            or base_kind == 'replicas' and variations < 2):
        raise ValueError('member count incompatible with .info ErrorType')
    rows = request['member_values']
    if not isinstance(rows, list) or len(rows) != count or not rows or not isinstance(rows[0], list) or not rows[0]:
        raise ValueError('complete worker member vectors required')
    for row in rows:
        if not isinstance(row, list) or len(row) != len(rows[0]):
            raise ValueError('aligned worker bins required')
        for value in row:
            _finite(value)
    if not 0 < _finite(request['confidence_level_percent']) < 100:
        raise ValueError('worker confidence level must be between zero and 100')


def _property(obj, name):
    value = getattr(obj, name)
    return value() if callable(value) else value


def verify_installed_info(request, library):
    """Bind the complete installed .info bytes, not a same-name substitute."""
    candidates = [Path(root) / request['set'] / (request['set'] + '.info') for root in library.paths()]
    selected = next((path for path in candidates if path.is_file()), None)
    if selected is None or selected.is_symlink():
        raise ValueError('installed regular PDF .info required')
    raw = selected.read_bytes()
    if hashlib.sha256(raw).hexdigest() != request['info']['sha256'] or raw.decode() != request['info']['text']:
        raise ValueError('installed PDF .info differs from supplied source')
    return selected


def evaluate(request, library):
    """Evaluate an injected library interface (synthetic fakes in host tests).

    Production main first verifies installed source bytes. No PDF formula is
    guessed in the host or here: the set itself dispatches its ErrorType.
    """
    validate_request(request)
    pdfset = library.getPDFSet(request['set'])
    kind = str(_property(pdfset, 'errorType'))
    if kind != request['info']['error_type']:
        raise ValueError('loaded PDF ErrorType differs from supplied .info')
    if _property(pdfset, 'size') != request['info']['num_members']:
        raise ValueError('loaded PDF member count differs from supplied .info')
    source_cl = _finite(_property(pdfset, 'errorConfLevel'))
    supplied_cl = request['info']['confidence_level_percent']
    if supplied_cl is not None and not math.isclose(source_cl, supplied_cl, rel_tol=0, abs_tol=1e-9):
        raise ValueError('loaded PDF confidence level differs from supplied .info')
    bins = []
    for values in zip(*request['member_values']):
        uncertainty = pdfset.uncertainty(list(values), request['confidence_level_percent'])
        row = {'central': _finite(uncertainty.central), 'minus': _finite(uncertainty.errminus),
               'plus': _finite(uncertainty.errplus), 'symmetric': _finite(uncertainty.errsymm),
               'confidence_rescale': _finite(uncertainty.scale)}
        if any(row[key] < 0 for key in ('minus', 'plus', 'symmetric', 'confidence_rescale')):
            raise ValueError('nonnegative library uncertainties required')
        bins.append(row)
    version = library.version() if callable(library.version) else library.version
    return {'schema_version': 1, 'kind': 'pdf-uncertainty-result', 'set': request['set'],
            'error_type': kind, 'member_ids': request['member_ids'],
            'confidence_level_percent': request['confidence_level_percent'],
            'source_confidence_level_percent': source_cl, 'info_sha256': request['info']['sha256'],
            'request_sha256': request_sha256(request), 'library_version': str(version), 'bins': bins}


def _read(path):
    def refuse(token):
        raise ValueError('nonfinite JSON token: ' + token)
    return json.loads(Path(path).read_text(), parse_constant=refuse)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    request = _read(args.request)
    validate_request(request)
    # External GPL library is imported only by this separate executable worker.
    import lhapdf
    info = verify_installed_info(request, lhapdf)
    before = info.read_bytes()
    result = evaluate(request, lhapdf)
    if before != info.read_bytes():
        raise ValueError('PDF metadata changed during worker execution')
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
