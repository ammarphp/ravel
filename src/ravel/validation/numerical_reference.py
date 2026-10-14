"""Complete supplied held-out numerical comparisons, without evaluating a model.

Exact decimal/rational values and absolute-radius enclosures are distinct from
binary64 numbers or statistical errors. Content identity is an integrity fact;
neither distinct files nor agreement proves independent oracle provenance.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

from ravel.physics.source_tables import bounded_read
from ravel.workflow.state_io import atomic_json, _unique

FILE_LIMIT = 4 * 1024 * 1024
TOTAL_LIMIT = 32 * 1024 * 1024
MAX_FILES = 128
MAX_CELLS = 64000
SCOPE = 'supplied_heldout_numerical_comparison'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def exact(value):
    """Parse a bounded exact token; never round via float or accept a bool."""
    if type(value) is int:
        result = Fraction(value)
    elif type(value) is str and len(value) <= 512 and re.fullmatch(
            r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[+-]?[0-9]+/[1-9][0-9]*', value):
        exponent = re.search(r'[eE]([+-]?[0-9]+)$', value)
        if exponent and abs(int(exponent[1])) > 128:
            raise ValueError('bounded exact exponent required')
        result = Fraction(value)
    else:
        raise ValueError('exact finite decimal/rational text or integer required')
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 4096:
        raise ValueError('bounded exact numerator/denominator required')
    return result


def ratio(value):
    return str(value.numerator) + '/' + str(value.denominator)


def _closed(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('closed ' + label + ' required')


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError('bounded nonempty literal text required')
    return value


def _id(value):
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) is None:
        raise ValueError('bounded literal identifier required')
    return value


def _tree(value, count, depth=0):
    count[0] += 1
    if count[0] > 200000 or depth > 32:
        raise ValueError('bounded JSON tree required')
    if type(value) is dict:
        for child in value.values():
            _tree(child, count, depth + 1)
    elif type(value) is list:
        for child in value:
            _tree(child, count, depth + 1)


def _json(raw):
    def refuse(value):
        raise ValueError('finite strict JSON required: ' + value)
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=refuse)
        _tree(value, [0])
        return value
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError('bounded strict UTF-8 JSON required') from exc


class _Reader:
    """Per-call immutable file census; all declared dependencies are ordinary inputs."""
    def __init__(self):
        self.files = {}
        self.total = 0

    def read(self, path, expected=None):
        path = Path(path).absolute()
        raw = bounded_read(path, FILE_LIMIT)
        pin = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        if expected is not None and (expected['sha256'] != pin['sha256'] or expected['size'] != pin['size']):
            raise ValueError('bound supplied file bytes changed')
        if str(path) in self.files:
            if self.files[str(path)] != pin:
                raise ValueError('same input changed during admission')
        else:
            self.total += len(raw)
            if len(self.files) >= MAX_FILES or self.total > TOTAL_LIMIT:
                raise ValueError('complete input census exceeds resource bounds')
            self.files[str(path)] = pin
        return raw, pin

    def pin(self, value, base):
        _closed(value, ('path', 'sha256', 'size'), 'file pin')
        if (type(value['path']) is not str or not value['path'] or
                type(value['sha256']) is not str or re.fullmatch(r'[0-9a-f]{64}', value['sha256']) is None or
                type(value['size']) is not int or not 0 < value['size'] <= FILE_LIMIT):
            raise ValueError('bounded nonempty exact file pin required')
        path = Path(value['path']).expanduser()
        path = path if path.is_absolute() else Path(base) / path
        raw, pin = self.read(path, value)
        return raw, pin

    def recheck(self):
        for pin in list(self.files.values()):
            self.read(pin['path'], pin)


def _basis(deck):
    _closed(deck['context'], ('quantity', 'model', 'process', 'normalization', 'domain', 'basis'), 'quantity context')
    for value in deck['context'].values():
        _text(value)
    axes, components = deck['axes'], deck['components']
    if type(axes) is not list or not 1 <= len(axes) <= 4 or type(components) is not list or not 1 <= len(components) <= 32:
        raise ValueError('bounded nonempty ordered axes/components required')
    for row in axes:
        _closed(row, ('id', 'unit'), 'axis'); _id(row['id']); _text(row['unit'])
    for row in components:
        _closed(row, ('id', 'unit', 'convention', 'atol', 'rtol'), 'component')
        _id(row['id']); _text(row['unit']); _text(row['convention'])
        if exact(row['atol']) < 0 or exact(row['rtol']) < 0:
            raise ValueError('nonnegative fixed engineering bands required')
    if len({r['id'] for r in axes}) != len(axes) or len({r['id'] for r in components}) != len(components):
        raise ValueError('unique basis identifiers required')
    population, coordinates = {}, set()
    for part, lower in (('training_points', 0), ('heldout_points', 1)):
        rows = deck[part]
        if type(rows) is not list or not lower <= len(rows) <= 1000:
            raise ValueError('explicit bounded training and nonempty held-out decks required')
        for row in rows:
            _closed(row, ('id', 'coordinates'), 'declared point')
            identity = _id(row['id'])
            if type(row['coordinates']) is not list or len(row['coordinates']) != len(axes):
                raise ValueError('complete ordered point coordinates required')
            coordinate = tuple(exact(x) for x in row['coordinates'])
            if identity in population or coordinate in coordinates:
                raise ValueError('unique physical points; training/held-out overlap is forbidden')
            coordinates.add(coordinate)
            population[identity] = (coordinate, part)
    return population


def _ball(value):
    _closed(value, ('mid', 'radius'), 'absolute-radius numerical enclosure')
    mid, radius = exact(value['mid']), exact(value['radius'])
    if radius < 0:
        raise ValueError('nonnegative absolute radius required')
    return mid, radius


def _points(doc, deck, population, required):
    _closed(doc, ('schema_version', 'kind', 'context', 'axes', 'components', 'rows'), 'point values/v1')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1 or doc['kind'] != 'numerical-point-values':
        raise ValueError('point values/v1 kind required')
    metadata = [{k: c[k] for k in ('id', 'unit', 'convention')} for c in deck['components']]
    if doc['context'] != deck['context'] or doc['axes'] != deck['axes'] or doc['components'] != metadata:
        raise ValueError('exact quantity/domain/unit/basis/convention match required')
    if type(doc['rows']) is not list or len(doc['rows']) != len(required):
        raise ValueError('complete declared point population required')
    result = {}
    ids = [c['id'] for c in deck['components']]
    for row in doc['rows']:
        _closed(row, ('id', 'coordinates', 'values'), 'numerical row')
        identity = _id(row['id'])
        if identity in result or identity not in required:
            raise ValueError('duplicate or foreign numerical point')
        if type(row['coordinates']) is not list or tuple(exact(x) for x in row['coordinates']) != population[identity][0]:
            raise ValueError('literal point identity differs from physical coordinates')
        _closed(row['values'], ids, 'complete component census')
        result[identity] = {c: _ball(row['values'][c]) for c in ids}
    if set(result) != set(required):
        raise ValueError('missing numerical points')
    return result


def _eft(doc, projection, deck, population, reader, base):
    """Read existing eft-functions delivery only; no source evaluator is imported."""
    _closed(projection, ('configuration', 'component_map'), 'EFT projection')
    raw, configuration_pin = reader.pin(projection['configuration'], base)
    config = _json(raw)
    _closed(config, ('schema_version', 'model', 'cards', 'coefficient_unit', 'one_coefficient_basis', 'evaluation_points'), 'EFT configuration')
    if type(config['schema_version']) is not int or config['schema_version'] != 1:
        raise ValueError('EFT configuration/v1 required')
    source_base = Path(configuration_pin['path']).parent
    # EFT config uses its existing path/SHA pins; measured sizes are retained here.
    def legacy_pin(pin):
        _closed(pin, ('path', 'sha256'), 'existing EFT source pin')
        if type(pin['path']) is not str or type(pin['sha256']) is not str or re.fullmatch(r'[a-f0-9]{64}', pin['sha256']) is None:
            raise ValueError('exact existing EFT source identity required')
        path = Path(pin['path']); path = path if path.is_absolute() else source_base / path
        raw, observed = reader.read(path)
        if observed['sha256'] != pin['sha256']:
            raise ValueError('EFT source bytes changed')
        return observed
    model_pin = legacy_pin(config['model'])
    if type(config['cards']) is not list or not 1 <= len(config['cards']) <= 32:
        raise ValueError('complete bounded EFT card population required')
    card_pins = [legacy_pin(p) for p in config['cards']]
    if len({p['path'] for p in card_pins}) != len(card_pins):
        raise ValueError('unique EFT card inputs required')
    _closed(doc, ('status', 'physics_validated', 'scope', 'coefficient_unit', 'one_coefficient_basis',
                  'model', 'cards', 'algebra_witness', 'evaluations', 'limitations'), 'retained EFT delivery')
    if doc['status'] != 'passed' or doc['physics_validated'] is not False or doc['model']['source_sha256'] != model_pin['sha256']:
        raise ValueError('retained EFT source identity/delivery boundary differs')
    if ([c['sha256'] for c in doc['cards']] != [p['sha256'] for p in card_pins] or
            doc['coefficient_unit'] != config['coefficient_unit'] or doc['one_coefficient_basis'] != config['one_coefficient_basis'] or
            deck['axes'] != [{'id': doc['model']['domain']['name'], 'unit': config['coefficient_unit']}] or
            deck['context']['basis'] != config['one_coefficient_basis']):
        raise ValueError('EFT source/card/unit/basis association differs')
    mapping = projection['component_map']
    _closed(mapping, [c['id'] for c in deck['components']], 'EFT component map')
    functions = doc['model']['functions']
    if (type(functions) is not dict or len(set(mapping.values())) != len(mapping) or
            set(mapping.values()) != set(functions) or any(c['unit'] != '1' for c in deck['components'])):
        raise ValueError('complete one-to-one dimensionless EFT function basis required')
    coordinates = {p[0]: identity for identity, p in population.items()}
    configured = [tuple([exact(x)]) for x in config['evaluation_points']]
    if len(configured) != len(population) or len(set(configured)) != len(configured) or set(configured) != set(coordinates):
        raise ValueError('EFT configured point deck differs')
    if type(doc['evaluations']) is not list or len(doc['evaluations']) != len(population):
        raise ValueError('complete retained EFT point population required')
    values = {}
    for row in doc['evaluations']:
        _closed(row, ('point', 'scales'), 'retained EFT evaluation')
        point = (exact(row['point']),)
        if point not in coordinates or coordinates[point] in values:
            raise ValueError('foreign/duplicate EFT evaluation point')
        _closed(row['scales'], functions, 'complete EFT scale basis')
        values[coordinates[point]] = {c: (exact(row['scales'][f]), Fraction(0)) for c, f in mapping.items()}
    return values


def _integral(doc, projection, deck, population, reader, base):
    """Compare literal reported centers; QMC errors never become enclosures."""
    from ravel.physics import finite_integrals_core as core
    _closed(projection, ('configuration', 'component_map'), 'finite-integral projection')
    raw, config_pin = reader.pin(projection['configuration'], base)
    config = core.config(_json(raw))
    _closed(doc, ('schema_version','kind','backend','version','configuration','generator_spec','rows',
                  'error_meaning','qualified_enclosure','physics_validated'), 'integral reported values')
    if (doc['schema_version'] != 1 or doc['kind'] != 'finite-integral-reported-values' or doc['backend'] != 'pySecDec'
            or doc['version'] != core.VERSION or doc['configuration'] != config
            or doc['generator_spec'] != core.generator_spec(config) or doc['error_meaning'] != core.ERROR_MEANING
            or doc['qualified_enclosure'] is not False or doc['physics_validated'] is not False):
        raise ValueError('finite integral source/delivery conventions differ')
    mapping = projection['component_map']
    _closed(mapping, [c['id'] for c in deck['components']], 'complex integral component map')
    if sorted(mapping.values()) != ['imag','real'] or len(mapping)!=2:
        raise ValueError('complete one-to-one real and imaginary mapping required')
    axes=[{'id':a,'unit':'GeV' if a=='mu' else 'GeV^2'} for a in config['axes']]
    unit='GeV^'+str(4-2*config['propagators'])
    if (deck['context'] != core.numerical_context(config) or deck['axes'] != axes
            or any(c['unit']!=unit or c['convention']!=core.NORMALIZATION+'; '+mapping[c['id']] for c in deck['components'])):
        raise ValueError('integral invariant/scale/branch/unit/normalization basis differs')
    if len(doc['rows']) != len(config['points']) or len(population)!=len(config['points']):
        raise ValueError('complete integral population required')
    values={};estimates=[]
    for point,row in zip(config['points'],doc['rows']):
        expected=core.derived(config,point,row.get('raw'))
        if (row.get('id')!=point['id'] or row.get('point')!=point or row.get('status')!='returned'
                or row.get('derived')!=expected or point['id'] not in population
                or population[point['id']][0]!=tuple(exact(x) for x in expected['coordinates'])):
            raise ValueError('complete literal integral return and declared point differ')
        # Radius zero here is the exact representation of the REPORTED center,
        # not a claim that it equals the mathematical integral without error.
        values[point['id']]={k:(exact(expected['values'][v]),Fraction(0)) for k,v in mapping.items()}
        estimates.append({'point':point['id'],'reported_errors':{k:expected['values']['error_'+v] for k,v in mapping.items()},
                          'estimated_precision_met':expected['estimated_precision_met']})
    return values,{'kind':'reported_centers_only','qualified_enclosure':False,'error_meaning':core.ERROR_MEANING,
                   'configuration_source':config_pin,'rows':estimates,'statistical_error_used_as_radius':False}


def _numeric_payload(values, population, component_ids):
    # Ignore point labels and JSON spellings, retain coordinate and basis order.
    return [{'coordinates': [ratio(x) for x in population[p][0]],
             'values': [[ratio(x) for x in values[p][c]] for c in component_ids]}
            for p in sorted(values, key=lambda k: population[k][0])]


def validate(task):
    _closed(task, ('input',), 'numerical-reference-check task')
    _text(task['input'])


def _load(task, base):
    validate(task)
    reader = _Reader()
    path = Path(task['input']).expanduser(); path = path if path.is_absolute() else Path(base) / path
    raw, config_pin = reader.read(path)
    config = _json(raw); parent = Path(config_pin['path']).parent
    _closed(config, ('schema_version', 'kind', 'deck', 'candidate', 'references', 'duplicate_reference_policy'), 'reference comparison configuration')
    if type(config['schema_version']) is not int or config['schema_version'] != 1 or config['kind'] != 'heldout-numerical-reference-check':
        raise ValueError('held-out reference comparison/v1 required')
    if config['duplicate_reference_policy'] not in ('report', 'refuse'):
        raise ValueError('explicit duplicate reference content policy required')
    raw, deck_pin = reader.pin(config['deck'], parent); deck = _json(raw)
    _closed(deck, ('schema_version', 'kind', 'context', 'axes', 'components', 'training_points', 'heldout_points'), 'numerical deck')
    if type(deck['schema_version']) is not int or deck['schema_version'] != 1 or deck['kind'] != 'numerical-reference-deck':
        raise ValueError('numerical reference deck/v1 required')
    population = _basis(deck)
    heldout = [p for p in population if population[p][1] == 'heldout_points']
    refs = config['references']
    if type(refs) is not list or not 1 <= len(refs) <= 8 or len(population) * len(deck['components']) * (len(refs) + 1) > MAX_CELLS:
        raise ValueError('complete numerical cell budget exceeded')
    source_origins = []
    def origin(record, candidate=False):
        keys = ('id', 'format', 'file', 'evidence', 'projection') if candidate else ('id', 'file', 'evidence')
        _closed(record, keys, 'candidate/reference source')
        _id(record['id'])
        if type(record['evidence']) is not list or not 1 <= len(record['evidence']) <= 32:
            raise ValueError('explicit bounded origin evidence required')
        evidence = [reader.pin(p, parent)[1] for p in record['evidence']]
        if len({p['path'] for p in evidence}) != len(evidence):
            raise ValueError('unique origin evidence pins required')
        raw, pin = reader.pin(record['file'], parent)
        source_origins.append({'id': record['id'], 'file': pin, 'evidence': evidence})
        return _json(raw)
    candidate = config['candidate']; doc = origin(candidate, True); reported_metadata = None
    if candidate['format'] == 'point-values/v1' and candidate['projection'] is None:
        values = _points(doc, deck, population, population)
    elif candidate['format'] == 'finite-integral-reported/v1':
        values, reported_metadata = _integral(doc, candidate['projection'], deck, population, reader, parent)
    elif candidate['format'] == 'eft-functions/v1':
        values = _eft(doc, candidate['projection'], deck, population, reader, parent)
    else:
        raise ValueError('explicit supported retained candidate format required')
    if len({r['id'] for r in refs}) != len(refs) or candidate['id'] in {r['id'] for r in refs}:
        raise ValueError('unique candidate/reference identities required')
    references = [(r['id'], _points(origin(r), deck, population, heldout)) for r in refs]
    reader.recheck()
    return config, deck, deck_pin, population, values, references, source_origins, reader, reported_metadata


def compare(task, base):
    """Return all exact residuals and complete coverage, including failed cells."""
    config, deck, deck_pin, population, values, refs, origins, reader, reported_metadata = _load(task, base)
    cells, reference_summaries, digests = [], [], {}
    ids = [c['id'] for c in deck['components']]
    heldout = [p for p in population if population[p][1] == 'heldout_points']
    for reference, expected in refs:
        payload_sha = digest(_numeric_payload(expected, population, ids))
        digests.setdefault(payload_sha, []).append(reference)
        component_hashes = {}
        for c in ids:
            component_hashes.setdefault(digest(_numeric_payload(expected, population, [c])), []).append(c)
        classifications = {'exact_zero': 0, 'zero_compatible_enclosure': 0, 'nonzero': 0}
        for p in heldout:
            for c in deck['components']:
                identity = c['id']; cm, cr = values[p][identity]; em, er = expected[p][identity]
                classification = ('exact_zero' if em == 0 and er == 0 else
                                  'zero_compatible_enclosure' if er > 0 and abs(em) <= er else 'nonzero')
                classifications[classification] += 1
                band = exact(c['atol']) + exact(c['rtol']) * abs(em)
                # Candidate enclosure must be contained in oracle interval + fixed band.
                excursion, allowance = abs(cm - em) + cr, er + band
                cells.append({'reference': reference, 'point': p, 'component': identity,
                              'candidate': {'mid': ratio(cm), 'radius': ratio(cr)},
                              'reference_value': {'mid': ratio(em), 'radius': ratio(er)},
                              'residual': ratio(cm - em), 'engineering_band': ratio(band),
                              'excursion': ratio(excursion), 'allowance': ratio(allowance),
                              'reference_class': classification, 'passed': excursion <= allowance})
        reference_summaries.append({'id': reference, 'numeric_payload_sha256': payload_sha,
            'zero_census': classifications,
            'duplicate_component_payloads': [v for v in component_hashes.values() if len(v) > 1]})
    duplicates = [v for v in digests.values() if len(v) > 1]
    numerical_passed = all(c['passed'] for c in cells)
    distinctness_passed = not duplicates or config['duplicate_reference_policy'] == 'report'
    reader.recheck()
    result = {'schema_version': 1, 'kind': 'heldout-numerical-comparison',
        'status': 'passed' if numerical_passed and distinctness_passed else 'failed',
        'status_scope': SCOPE, 'physics_validated': False,
        'numerical_passed': numerical_passed, 'content_policy_passed': distinctness_passed,
        'context': deck['context'], 'axes': deck['axes'], 'components': deck['components'],
        'configuration_source': next(iter(reader.files.values())),
        'candidate_format': config['candidate']['format'],
        'reported_center_metadata': reported_metadata,
        'candidate_comparison_semantics': ('reported centers versus supplied reference enclosures and fixed engineering bands; candidate uncertainty unqualified' if reported_metadata else 'supplied candidate numerical enclosure'),
        'candidate_projection': config['candidate']['projection'],
        'deck_source': deck_pin, 'deck_sha256': digest(deck),
        'coverage': {'training_ids': [p for p in population if population[p][1] == 'training_points'],
                     'heldout_ids': heldout, 'component_ids': ids, 'reference_ids': [r for r, _ in refs],
                     'expected_comparisons': len(heldout) * len(ids) * len(refs),
                     'checked_comparisons': len(cells), 'missing': [], 'foreign': [],
                     'failed_cells': [{k: c[k] for k in ('reference', 'point', 'component')} for c in cells if not c['passed']]},
        'cells': cells, 'references': reference_summaries,
        'duplicate_reference_payloads': duplicates, 'duplicate_reference_policy': config['duplicate_reference_policy'],
        'shared_candidate_reference_evidence': [
            {'reference': source['id'], 'sha256': p['sha256'], 'reference_path': p['path'],
             'candidate_paths': [q['path'] for q in origins[0]['evidence'] if q['sha256'] == p['sha256']]}
            for source in origins[1:] for p in source['evidence']
            if any(q['sha256'] == p['sha256'] for q in origins[0]['evidence'])],
        'source_origins': origins, 'input_pins': list(reader.files.values()),
        'resources': {'input_files': len(reader.files), 'input_bytes': reader.total,
                      'admitted_cells': len(population) * len(ids) * (len(refs) + 1),
                      'cell_limit': MAX_CELLS, 'file_limit_bytes': FILE_LIMIT, 'total_limit_bytes': TOTAL_LIMIT},
        'training_heldout_coordinates_disjoint': True,
        'withholding_chronology_verified': False, 'oracle_independence_proven': False,
        'limitations': ['No model, fit, native, provider or kernel was evaluated.',
            'Training/held-out disjointness is mathematical; withholding chronology remains unverified.',
            'Numeric payload identity ignores labels/spelling; different content does not prove independent provenance.',
            'Absolute radii are supplied numerical enclosures, not statistical uncertainties or coverage calibration.',
            'Agreement at this complete supplied deck is not a continuum, physical-domain or model-validity proof.']}
    if reported_metadata:
        result['limitations'].append('The finite integral candidate is a reported center only; QMC estimates are retained separately and neither used as enclosure radii nor proven accurate.')
    return result, reader


def inputs(task, base):
    # Admission validates shape/coverage only; numerical comparisons belong in run.
    *_, reader, reported_metadata = _load(task, base)
    return [Path(p) for p in reader.files]


def run(task, base, out):
    result, reader = compare(task, base)
    out = Path(out)
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('ordinary fresh output directory required')
    out.mkdir(parents=True, exist_ok=False)
    reader.recheck()
    atomic_json(out / 'numerical-reference.json', result)
    try:
        reader.recheck()
    except ValueError:
        # Retain the attempted computation, but no standalone success receipt.
        (out / 'numerical-reference.json').rename(out / 'uncommitted-numerical-reference.json')
        raise
    return result


def write_report(result, out):
    out = Path(out)
    report = out / 'numerical-reference-report.md'
    c = result['coverage']
    report.write_text('Supplied held-out numerical comparison: ' + result['status'] + '.\n\n'
        + str(c['checked_comparisons']) + ' of ' + str(c['expected_comparisons']) + ' declared cells checked; '
        + str(len(c['failed_cells'])) + ' failed cells.\n\n'
        + 'References with identical numerical payloads: ' + json.dumps(result['duplicate_reference_payloads']) + '.\n\n'
        + '\n'.join('- ' + text for text in result['limitations']) + '\n')
    return [{'stem': 'numerical-reference-report', 'files': [report.name],
             'normalization': 'Exact supplied basis and fixed engineering bands; no independent physics qualification'}]
