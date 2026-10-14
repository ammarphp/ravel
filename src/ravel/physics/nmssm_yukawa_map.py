"""Finite released NMSSM tree SLHA convention to neutral-Higgs predictions.

This is a selected tree map, not a new spectrum solver. It consumes complete
real diagonal SLHA Yukawa matrices and tree Higgs mixing at one explicit DRbar
scale. The ordinary study supplies execution/review authority. No UV matching,
RGE, loop correction, total width, BR or production prediction is inferred.
"""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

from . import model_specific_spectrum as named, model_tool_bridge as custody, ufo_decay

SCOPE = 'nmssm_tree_yukawa_prediction_delivery'
API = Path(__file__).parents[1] / 'data/spectrum/nmssm-tree-yukawa.json'
FAMILIES = (('d', 'YD', (1, 3, 5), 0, 3),
            ('u', 'YU', (2, 4, 6), 1, 3),
            ('e', 'YE', (11, 13, 15), 0, 1))
HIGGS = (25, 35, 45)
VALIDITY = {'basis': 'FlexibleSUSY-2.9.0-NMSSM-SLHA2-SVD',
            'cp': 'real_CP_even', 'flavour': 'three_generation_diagonal',
            'order': 'tree_DRbar_at_explicit_Q', 'kinematics': 'on_shell_two_body'}


def _keys(obj, keys, label):
    custody._keys(obj, keys, label)


def _q(token):
    return named.number(token)


def _s(q):
    return str(q.numerator) + '/' + str(q.denominator)


def _finite(q, label):
    try:
        x = float(q)
    except (ValueError, OverflowError):
        raise ValueError('nonfinite ' + label) from None
    named.require(math.isfinite(x) and (q == 0 or x != 0), 'nonfinite/underflowing ' + label)
    return x


def _json(raw):
    from ravel.workflow.state_io import _unique
    def reject(x):
        raise ValueError('nonfinite JSON ' + x)
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject)


def _read(path, expected=None):
    return _json(named.raw_file(path, expected))


def validate(task):
    _keys(task, ('request',), 'NMSSM tree-map task')
    named.require(type(task['request']) is str and task['request'].strip(), 'explicit request path required')
    return task


def request_document(doc):
    _keys(doc, ('schema_version', 'operation', 'profile', 'spectrum', 'input_card',
                'scale_token', 'validity', 'checks', 'origin'), 'NMSSM tree-map request')
    named.require(type(doc['schema_version']) is int and doc['schema_version'] == 1 and
                  doc['operation'] == 'nmssm_tree_yukawa' and doc['profile'] == named.NAME,
                  'exact released NMSSM tree-map schema/profile required')
    named.require(doc['validity'] == VALIDITY, 'CPV, flavour-changing or other basis/order map is unsupported')
    named.require(_q(doc['scale_token']) > 0, 'explicit positive GeV DRbar scale token required')
    _keys(doc['checks'], ('mixing_absolute', 'mass_squared_absolute_GeV2', 'mass_squared_relative'),
          'prospectively supplied numerical agreement bands')
    for value in doc['checks'].values():
        named.require(_q(value) >= 0, 'nonnegative explicit numerical agreement band required')
    origin = doc['origin']
    named.require(type(origin) is dict and origin.get('kind') in ('supplied_unqualified', 'accepted_named_spectrum'),
                  'explicit supplied or accepted named-spectrum origin required')
    _keys(origin, ('kind', 'run') if origin['kind'] == 'accepted_named_spectrum' else ('kind',), 'spectrum origin')
    return doc


def load(task, base):
    validate(task)
    path = custody._regular(task['request'], base)
    return path, request_document(_read(path))


def _origin(doc, base):
    """Accepted origin is current actual spectrum custody, never a user label."""
    if doc['origin']['kind'] == 'supplied_unqualified':
        return []
    from ravel.workflow import task_completion, execution, science
    observed = task_completion._Inputs(base)
    try:
        rd, _ = task_completion._accepted_review(doc['origin']['run'], named.SCOPE, observed)
        spec = science.execution_spec(rd)
        named.require(spec['mode'] == 'generated-spectrum', 'accepted origin must be actual generated-spectrum')
        from . import generated_spectrum
        configpath, config = generated_spectrum._load(spec['task'], rd)
        named.require(config['schema_version'] == 2 and config['profile'] == named.NAME,
                      'legacy/different named spectrum cannot supply this physical map')
        outputs = execution.load_execution(rd)['stages']['science']['outputs']
        named.require(len(outputs) == 1, 'one closed accepted spectrum output required')
        out = custody._regular(outputs[0], rd, directory=True)
        resultpath = out / 'generated-spectrum.json'
        observed.capture(resultpath)
        result = _read(resultpath)
        named.require(result['status'] == 'passed' and result['model_profile'] == named.NAME and
                      result['configuration'] == {'path': str(configpath), 'sha256': custody._hash(configpath)},
                      'actual named result/configuration binding differs')
        supplied = custody._pin(doc['spectrum'], base)
        original = custody._pin(doc['input_card'], base)
        named.require(supplied == out / 'NMSSM.slha' and
                      result['generated_slha']['path'] == str(supplied) and
                      result['generated_slha']['sha256'] == doc['spectrum']['sha256'] and
                      original == custody._pin(config['input_card'], configpath.parent) and
                      config['input_card']['sha256'] == doc['input_card']['sha256'],
                      'map must consume exact accepted native return and original input')
        named.require(result['full_slha'] == named.inventory(named.raw_file(supplied, doc['spectrum']['sha256'])) and
                      result['input_witness']['all_input'] == named.inventory(named.raw_file(original, doc['input_card']['sha256'])),
                      'accepted result must retain exact full return and original input census')
        observed.finish()
        return [Path(p['path']) for p in observed.pins.values()]
    finally:
        observed.close()


def _sources():
    api = _read(API)
    profile = named.profile()
    named.require(api['profile'] == named.NAME and api['framework_commit'] == profile['framework_commit'] and
                  all(profile['files'].get(p['path']) == p['sha256'] for p in api['source_files']),
                  'released equation source identities differ from the existing named profile')
    return api


def _input_paths(path, doc):
    _sources()
    return sorted(set([path, API, named.PROFILE, custody._pin(doc['spectrum'], path.parent),
                       custody._pin(doc['input_card'], path.parent), *_origin(doc, path.parent)]))


def inputs(task, base):
    path, doc = load(task, base)
    return _input_paths(path, doc)


def _captured(task, base):
    """Commit the request bytes parsed, never a later reloaded request epoch."""
    validate(task)
    path = custody._regular(task['request'], base)
    raw = named.raw_file(path)
    doc = request_document(_json(raw))
    files = _input_paths(path, doc)
    before = {p: hashlib.sha256(named.raw_file(p)).hexdigest() for p in files}
    named.require(before[path] == hashlib.sha256(raw).hexdigest(), 'initial request changed before source capture')
    return path, doc, files, before


def _finish(task, base, files, before):
    current = inputs(task, base)
    named.require(files == current and before == {p: hashlib.sha256(named.raw_file(p)).hexdigest() for p in current},
                  'original map inputs/current accepted source changed during mapping')


def validate_scope(spec):
    policy = spec.get('review_policy', {}).get('policy', {})
    scopes = policy.get('claim_scopes', {})
    named.require(spec.get('schema_version') == 2 and spec.get('max_attempts') == 1 and
                  policy.get('max_redos') == 0 and set(scopes) == {SCOPE} and
                  scopes[SCOPE].get('actions') == ['delivery'],
                  'tree-map requires one-attempt delivery-only ordinary review')


def _block(doc, name, scale, addresses):
    blocks = [s for s in doc['sections'] if s['kind'] == 'block' and s['name'] == name and s['scale'] == scale]
    named.require(len(blocks) == 1, 'missing/duplicate exact block occurrence: ' + name)
    rows = blocks[0]['rows']
    named.require(all(r['kind'] == 'scalar' for r in rows), 'opaque selected block rows refused: ' + name)
    keys = [tuple(r['codes']) for r in rows]
    named.require(len(keys) == len(set(keys)) and set(keys) == set(addresses),
                  'complete exact address population required: ' + name)
    return {tuple(r['codes']): _q(r['value']) for r in rows}


def _scalar(doc, block, codes, scale=None):
    return _q(named.scalar(doc, {'block': block, 'codes': list(codes), 'scale': scale}))


def derive(spectrum_raw, input_raw, doc):
    """Algebra and supplied-band checks; does not execute a spectrum generator."""
    request_document(doc)
    spectrum, original = named.inventory(spectrum_raw), named.inventory(input_raw)
    named.require(not spectrum['native_error_rows'] and not original['native_error_rows'], 'native error diagnostics forbid prediction mapping')
    for code, value in ((3, 1), (4, 0), (12, 0), (23, 1)):
        named.require(_scalar(original, 'FLEXIBLESUSY', (code,)) == value,
                      'explicit tree output settings required: FlexibleSUSY[' + str(code) + ']')
    named.require(_scalar(original, 'MODSEL', (6,)) == 0, 'flavour-violating model selection unsupported')
    for s in original['sections']:
        if s['kind'] == 'block' and s['name'] == 'MODSEL':
            if any(r.get('codes') == [5] for r in s['rows']):
                named.require(_scalar(original, 'MODSEL', (5,)) == 0, 'CP-violating model selection unsupported')
    q = doc['scale_token']
    addresses = [(i, j) for i in range(1, 4) for j in range(1, 4)]
    mixing = _block(spectrum, 'NMHMIX', None, addresses)
    matrices = {block: _block(spectrum, block, q, addresses) for _, block, _, _, _ in FAMILIES}
    for name in ('IMNMHMIX', 'IMYU', 'IMYD', 'IMYE'):
        occurrences = [s for s in spectrum['sections'] if s['kind'] == 'block' and s['name'] == name]
        if occurrences:
            im = _block(spectrum, name, None if name == 'IMNMHMIX' else q, addresses)
            named.require(all(x == 0 for x in im.values()), 'complex Yukawa/CP-even mixing not supported')
    for values in matrices.values():
        named.require(all(v == 0 for (i, j), v in values.items() if i != j), 'non-diagonal SLHA Yukawa matrix refused')
        diagonal = [values[(i, i)] for i in range(1, 4)]
        named.require(all(v >= 0 for v in diagonal) and diagonal == sorted(diagonal), 'SLHA SVD positive ascending singular values required')
    residuals = [sum(mixing[(i, k)] * mixing[(j, k)] for k in range(1, 4)) - int(i == j)
                 for i in range(1, 4) for j in range(1, 4)]
    bound = _q(doc['checks']['mixing_absolute'])
    named.require(all(abs(r) <= bound for r in residuals), 'mixing orthogonality differs beyond supplied band; no reorthogonalization')
    vd, vu = [_scalar(spectrum, 'HMIX', (n,), q) for n in (102, 103)]
    named.require(vd > 0 and vu > 0, 'positive supplied vd/vu convention required')
    masses = {pdg: _scalar(spectrum, 'MASS', (pdg,)) for pdg in (*HIGGS, *(p for f in FAMILIES for p in f[2]))}
    named.require(all(m >= 0 for m in masses.values()) and all(masses[p] > 0 for p in HIGGS),
                  'signed tachyon/negative kinematic mass refused, never absolute-valued')
    absband, relband = [_q(doc['checks'][k]) for k in ('mass_squared_absolute_GeV2', 'mass_squared_relative')]
    mass_checks = []
    for family, block, pdgs, column, color in FAMILIES:
        v = (vd, vu)[column]
        for j, pdg in enumerate(pdgs, 1):
            y = matrices[block][(j, j)]
            expected = y*y*v*v/2
            residual = masses[pdg]**2 - expected
            band = absband + relband*abs(expected)
            named.require(abs(residual) <= band, 'returned mass/Yukawa tree relation differs beyond supplied band')
            mass_checks.append({'pdg': pdg, 'expected_squared_GeV2': _s(expected),
                                'residual_squared_GeV2': _s(residual), 'declared_band_GeV2': _s(band)})
    rows = []
    for i, parent in enumerate(HIGGS, 1):
        for family, block, pdgs, column, color in FAMILIES:
            for j, anti in enumerate(pdgs, 1):
                for k, fermion in enumerate(pdgs, 1):
                    factor = -matrices[block][(j, k)] * mixing[(i, column+1)]
                    g = _finite(factor, 'exact Yukawa-mixing prefactor') / math.sqrt(2)
                    named.require(math.isfinite(g) and (factor == 0 or g != 0), 'nonfinite/underflowing chiral coefficient')
                    m, a, b = [_finite(masses[p], 'kinematic mass') for p in (parent, anti, fermion)]
                    opened = masses[parent] > masses[anti] + masses[fermion]
                    reference = None
                    if opened:
                        named.require(m > a+b, 'open exact channel collapsed at binary64 threshold')
                        reference = ufo_decay.tree_reference('SFF', [m, a, b], {'gL': g, 'gR': g}, color)
                        named.require(factor == 0 or reference['partial_width_GeV'] > 0,
                                      'positive open partial width collapsed; no fabricated zero')
                    rows.append({'id': f'h{parent}_{family}{j}{k}', 'parent_pdg': parent,
                                 'outgoing_pdgs': [-anti, fermion], 'flavour_indices': [j, k],
                                 'family': family, 'higgs_row': i, 'higgs_gauge_column': column+1,
                                 'yukawa_block': block, 'scale_token_GeV': q,
                                 'exact_prefactor_over_sqrt2': _s(factor),
                                 'HEPTAPOD_coordinates': {'gL': {'real': g, 'imag': 0.0}, 'gR': {'real': g, 'imag': 0.0}},
                                 'vertex_convention': 'i*(gL*PL+gR*PR); upstream Cp has global i stripped',
                                 'channel_status': 'open_tree_channel' if opened else 'closed_or_threshold_no_offshell_prediction',
                                 'tree_reference': reference, 'flavour_zero_derived': j != k})
    named.require(len(rows) == 81 and len({r['id'] for r in rows}) == 81, 'complete 81-channel population required')
    return {'schema_version': 1, 'status': 'passed', 'status_scope': SCOPE,
            'profile': named.NAME, 'operation': doc['operation'], 'validity': doc['validity'],
            'scale_token_GeV': q, 'full_spectrum': spectrum, 'full_original_input': original,
            'source_origin': doc['origin'], 'requested_checks': doc['checks'],
            'mixing_orthogonality_residuals': [_s(r) for r in residuals], 'mass_yukawa_checks': mass_checks,
            'couplings_and_channels': rows, 'population': {'higgs': 3, 'fermion_families': 3, 'generation_pairs': 9, 'channels': 81},
            'physics_validated': False, 'execution_authorized': False, 'native_calls': 0,
            'perturbative_validity': 'unknown', 'native_amplitude_equivalence': 'unknown',
            'rge_applied': False, 'eft_matching_applied': False, 'supplied_card_changed': False,
            'supplied_total_width_replaced': False, 'branching_ratios_predicted': False,
            'limitations': ['Supplied spectrum origin is not authenticated native consumption unless the accepted origin join is used.',
                'Tree DRbar-at-Q map only; positive-loop pole mixing is not silently treated as tree mixing.',
                'Caller-declared bands are engineering agreement predicates, not spectrum/perturbative accuracy certification.',
                'Widths use existing binary64 on-shell tree reference; no loop/native amplitude, total DECAY/BR, production or UV/EFT matching certificate.',
                'All original blocks/diagnostics remain retained; supersymmetric decays, CP-odd/charged Higgs and flavour-changing couplings are outside this finite map.']}


def context(task, base):
    path, doc, files, before = _captured(task, base)
    result = {'schema_version': 1, 'kind': 'nmssm-tree-map-context', 'request': doc,
            'equations': _sources()['equations'], 'input_pins': [{'path': str(p), 'sha256': sha} for p, sha in before.items()],
            'ordinary_task': {'request': str(path)}, 'mode': 'nmssm-yukawa-map',
            'physics_validated': False, 'execution_authorized': False}
    _finish(task, base, files, before)
    return result


def _derive_captured(path, doc, before):
    raw = named.raw_file(custody._pin(doc['spectrum'], path.parent), doc['spectrum']['sha256'])
    original = named.raw_file(custody._pin(doc['input_card'], path.parent), doc['input_card']['sha256'])
    result = derive(raw, original, doc)
    result['released_equation_sources'] = _sources()
    result['input_pins'] = [{'path': str(p), 'sha256': sha} for p, sha in before.items()]
    return result


def compile_map(task, base):
    """Reusable supplied-data result with a complete current source recheck."""
    path, doc, files, before = _captured(task, base)
    result = _derive_captured(path, doc, before)
    _finish(task, base, files, before)
    return result


def verify_result(task, base, result):
    """Recompute this finite derivation; a self-rehashed numerical edit fails."""
    named.require(result == compile_map(task, base), 'map result differs from complete current released derivation')
    return True


def run(task, base, output):
    path, doc, files, before = _captured(task, base)
    result = _derive_captured(path, doc, before)
    _finish(task, base, files, before)
    out = Path(output).expanduser().absolute()
    named.require(not out.exists() and not any(p.is_symlink() for p in (out, *out.parents)) and
                  not any(p == out or p.is_relative_to(out) for p in files), 'fresh independent map output required')
    out.mkdir(parents=True)
    target = out / 'nmssm-yukawa-map.json'
    # Freeze the intended value before invoking a writer callback. Its argument
    # must not alias the scientific result returned to ordinary consumers.
    expected = (json.dumps(result, indent=2, allow_nan=False) + '\n').encode()
    detached = _json(expected)
    expected_pin = {'path': str(target.resolve()),
                    'sha256': hashlib.sha256(expected).hexdigest()}
    try:
        pin = named.write_exact(target, detached)
        _finish(task, base, files, before)
        named.require(pin == expected_pin and named.raw_file(target) == expected,
                      'generated map output differs from its initial commitment')
        named.require((json.dumps(detached, indent=2, allow_nan=False) + '\n').encode() == expected and
                      (json.dumps(result, indent=2, allow_nan=False) + '\n').encode() == expected,
                      'writer argument or returned map changed after initial commitment')
    except Exception:
        if target.exists():
            target.rename(out / 'failed-nmssm-yukawa-map.json')
        raise
    return result


def main(argv=None):
    """No implicit execution: this CLI emits the preparation context only."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    args = parser.parse_args(argv)
    path = custody._regular(args.request, Path.cwd())
    print(json.dumps(context({'request': str(path)}, path.parent), indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
