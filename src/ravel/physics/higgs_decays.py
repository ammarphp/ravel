"""Explicit, source-bound decay cards, output transport and reference comparison.

This module never launches an engine. Supplied format descriptions remain
unqualified until checked against the selected program's pinned manual/runtime.
A four-fermion sector is never presented as a complete scalar branching set.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re

from ravel.physics.resonance_width import _keys, _num

REQUIRED_PHYSICS_INPUTS = (
    'alpha_s_mz', 'mb_mb_GeV', 'mc_GeV', 'mt_pole_GeV', 'gamma_w_GeV', 'gamma_z_GeV',
)
WIDTH_SUM_RELATIVE_TOLERANCE = 1e-6
COMPARISON_TOLERANCES = {'bb': .015, 'tautau': .015, 'mumu': .015, 'cc': .015,
                         'gammagamma': .015, 'Zgamma': .015, 'gg': .015,
                         'WW': .03, 'ZZ': .03, 'Gamma_H': .03}
CHANNEL_ALIASES = {'ττ': 'tautau', 'μμ': 'mumu', 'γγ': 'gammagamma',
                   'Zγ': 'Zgamma', 'Γ_H': 'Gamma_H'}


def _text(value, label):
    if type(value) is not str or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError('explicit single-line ' + label + ' required')
    return value


def _pdg(value):
    if type(value) is not int or value == 0:
        raise ValueError('nonzero integer PDG identity required')
    return value


def _basename(value):
    _text(value, 'filename')
    if value in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
        raise ValueError('ordinary basename required')
    return value


def adapter(program):
    from ravel.physics.higgs_decay_programs import ADAPTERS
    try:
        return ADAPTERS[program]
    except (KeyError, TypeError) as exc:
        raise ValueError('unknown decay program: ' + str(program)) from exc


def validate_point(point):
    _keys(point, ('schema_version', 'program', 'version', 'order', 'ew_scheme',
                  'physics_inputs', 'parameters', 'scalars'), label='model point')
    if type(point['schema_version']) is not int or point['schema_version'] != 1:
        raise ValueError('model point schema_version 1 required')
    adapter(point['program'])
    for key in ('version', 'order', 'ew_scheme'):
        _text(point[key], key)
    physics = point['physics_inputs']
    if type(physics) is not dict:
        raise ValueError('explicit physics_inputs mapping required')
    missing = set(REQUIRED_PHYSICS_INPUTS) - set(physics)
    if missing:
        raise ValueError('missing physics input: ' + ', '.join(sorted(missing)))
    for key, value in physics.items():
        _text(key, 'physics input name')
        _num(value, key, positive=True)
    params = point['parameters']
    if type(params) is not dict:
        raise ValueError('explicit parameters mapping required, including all model inputs and flags')
    for key, value in params.items():
        _text(key, 'parameter name')
        if type(value) is str:
            _text(value, key)
        else:
            _num(value, key)
    scalars = point['scalars']
    if type(scalars) is not list or not scalars:
        raise ValueError('explicit nonempty scalar population required')
    identities = []
    for scalar in scalars:
        _keys(scalar, ('pdg', 'mass_GeV', 'coverage'), label='scalar')
        identities.append(_pdg(scalar['pdg']))
        _num(scalar['mass_GeV'], 'scalar mass_GeV', positive=True)
        if scalar['coverage'] not in ('complete', 'four_fermion'):
            raise ValueError('explicit complete or four_fermion coverage required')
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate scalar identity')
    return deepcopy(point)


def validate_table(table):
    _keys(table, ('schema_version', 'program', 'version', 'order', 'ew_scheme', 'units', 'scalars'),
          ('format_provenance', 'layout_qualified'), label='decay table')
    if type(table['schema_version']) is not int or table['schema_version'] != 1 or table['units'] != 'GeV':
        raise ValueError('schema 1 decay widths in GeV required')
    adapter(table['program'])
    for key in ('version', 'order', 'ew_scheme'):
        _text(table[key], key)
    if type(table['scalars']) is not list or not table['scalars']:
        raise ValueError('nonempty scalar population required')
    identities = []
    for scalar in table['scalars']:
        _keys(scalar, ('pdg', 'mass_GeV', 'coverage', 'total_width_GeV', 'channels'), label='decay scalar')
        identities.append(_pdg(scalar['pdg']))
        _num(scalar['mass_GeV'], 'scalar mass_GeV', positive=True)
        if scalar['coverage'] not in ('complete', 'four_fermion'):
            raise ValueError('explicit complete or four_fermion coverage required')
        total = _num(scalar['total_width_GeV'], 'total_width_GeV', positive=True)
        if type(scalar['channels']) is not list or not scalar['channels']:
            raise ValueError('nonempty exclusive channel population required')
        ids, daughters, widths = [], [], []
        for channel in scalar['channels']:
            _keys(channel, ('id', 'daughters', 'partial_width_GeV', 'branching_ratio', 'program'),
                  label='decay channel')
            if channel['program'] != table['program']:
                raise ValueError('one program per scalar branching set required')
            ids.append(_text(channel['id'], 'channel id'))
            ds = channel['daughters']
            if type(ds) is not list or len(ds) < 2:
                raise ValueError('explicit multi-particle daughter population required')
            if scalar['coverage'] == 'four_fermion' and len(ds) != 4:
                raise ValueError('four_fermion sector requires four daughter identities per channel')
            daughters.append(tuple(sorted(_pdg(x) for x in ds)))
            width = _num(channel['partial_width_GeV'], 'partial_width_GeV', nonnegative=True)
            br = _num(channel['branching_ratio'], 'branching_ratio', nonnegative=True)
            if br > 1 or not math.isclose(br, width / total, rel_tol=1e-12, abs_tol=0):
                raise ValueError('branching_ratio differs from partial / total width')
            widths.append(width)
        if len(set(ids)) != len(ids) or len(set(daughters)) != len(daughters):
            raise ValueError('duplicate channel or permuted daughter population')
        try:
            summed = math.fsum(widths)
        except OverflowError as exc:
            raise ValueError('partial-width sum overflows finite transport precision') from exc
        if abs(summed - total) > WIDTH_SUM_RELATIVE_TOLERANCE * total:
            raise ValueError('partial-width sum differs from stated total by more than 1e-6 relative')
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate scalar identity')
    return deepcopy(table)


def to_slha(table):
    """Serialize complete scalar sets only; no sector total may masquerade as Γ_H."""
    document = validate_table(table)
    if any(s['coverage'] != 'complete' for s in document['scalars']):
        raise ValueError('complete scalar widths required for SLHA DECAY blocks')
    lines = ['# ' + ' '.join(document[k] for k in ('program', 'version', 'order', 'ew_scheme'))]
    lines.append('BLOCK MASS')
    lines += [f" {s['pdg']} {s['mass_GeV']:.17g}" for s in document['scalars']]
    for scalar in document['scalars']:
        lines.append(f"DECAY {scalar['pdg']} {scalar['total_width_GeV']:.17g}")
        for channel in scalar['channels']:
            ds = ' '.join(str(x) for x in channel['daughters'])
            lines.append(f" {channel['branching_ratio']:.17g} {len(channel['daughters'])} {ds} # {channel['id']}")
    return '\n'.join(lines) + '\n'


def compare_reference(table, rows, *, pdg, required_channels=None):
    """Compare supplied cited rows at one exact mass; no built-in reference values.

The total-width row interface uses quantity=total_width, unit=GeV. Existing
version-one branching rows use process, mass_gev and citation_key, supported
alongside channel, mass_GeV and citation. Reference selection is caller-owned.
"""
    d = validate_table(table)
    selected = [s for s in d['scalars'] if s['pdg'] == _pdg(pdg)]
    if len(selected) != 1 or selected[0]['coverage'] != 'complete':
        raise ValueError('one complete scalar set required for reference comparison')
    scalar = selected[0]
    if type(rows) is not list or not rows:
        raise ValueError('nonempty supplied cited reference rows required')
    predictions = {CHANNEL_ALIASES.get(c['id'], c['id']): c['branching_ratio'] for c in scalar['channels']}
    predictions['Gamma_H'] = scalar['total_width_GeV']
    result, seen, row_ids = [], set(), set()
    for row in rows:
        if type(row) is not dict:
            raise ValueError('reference row object required')
        row_id = _text(row.get('id'), 'reference row id')
        channel = _text(row.get('channel', row.get('process')), 'reference channel')
        channel = CHANNEL_ALIASES.get(channel, channel)
        if channel not in COMPARISON_TOLERANCES or channel not in predictions or channel in seen or row_id in row_ids:
            raise ValueError('distinct available supported reference channel required')
        seen.add(channel); row_ids.add(row_id)
        mass = _num(row.get('mass_GeV', row.get('mass_gev')), 'reference mass', positive=True)
        if mass != scalar['mass_GeV']:
            raise ValueError('exact reference mass required; no interpolation')
        if 'program' in row and row['program'] != d['program']:
            raise ValueError('reference program differs from selected prediction program')
        total = channel == 'Gamma_H'
        if row.get('quantity') != ('total_width' if total else 'branching_ratio') or row.get('unit') != ('GeV' if total else '1'):
            raise ValueError('reference quantity and unit must match the compared quantity')
        citation = _text(row.get('citation', row.get('citation_key')), 'reference citation')
        reference = _num(row.get('value'), 'reference value', positive=True)
        if not total and reference > 1:
            raise ValueError('reference branching ratio exceeds one')
        delta = abs(predictions[channel] - reference) / reference
        tolerance = COMPARISON_TOLERANCES[channel]
        result.append({'reference_id': row_id, 'channel': channel, 'prediction': predictions[channel],
                       'reference': reference, 'unit': row['unit'], 'relative_difference': delta,
                       'relative_tolerance': tolerance, 'passed': delta <= tolerance,
                       'citation': citation})
    if required_channels is not None:
        if type(required_channels) is not list or not required_channels:
            raise ValueError('nonempty required_channels list required')
        required = {CHANNEL_ALIASES.get(k, k) for k in required_channels}
        if required - seen:
            raise ValueError('missing required reference channels: ' + ', '.join(sorted(required - seen)))
    return {'program': d['program'], 'version': d['version'], 'order': d['order'], 'ew_scheme': d['ew_scheme'],
            'pdg': pdg, 'mass_GeV': scalar['mass_GeV'], 'channels': result,
            'passed': all(r['passed'] for r in result), 'physics_validated': False}


def validate(task):
    _keys(task, ('request',), label='higgs-decays task')
    _text(task['request'], 'request path')
    return dict(task)


def _load(task, base):
    from ravel.physics import model_tool_bridge as custody
    validate(task)
    request_path = custody._regular(task['request'], base)
    request = custody._read(request_path)
    _keys(request, ('schema_version', 'action', 'point', 'format', 'format_source', 'publication'),
          ('outputs', 'execution'), label='decay request')
    if type(request['schema_version']) is not int or request['schema_version'] != 1 or request['action'] not in ('prepare', 'parse'):
        raise ValueError('schema 1 with explicit prepare or parse action required')
    point_path, format_path, source_path = [custody._pin(request[k], request_path.parent)
                                           for k in ('point', 'format', 'format_source')]
    point, contract = custody._read(point_path), custody._read(format_path)
    if type(point) is not dict:
        raise ValueError('model point object required')
    engine = adapter(point.get('program'))
    engine.render_card(point, contract)
    publication = request['publication']
    _keys(publication, ('json', 'slha'), label='publication filenames')
    _basename(publication['json'])
    if publication['slha'] is not None:
        _basename(publication['slha'])
    names = [publication['json'], contract['card']['filename']]
    if publication['slha'] is not None:
        names.append(publication['slha'])
    if len(set(names)) != len(names):
        raise ValueError('distinct publication and input card filenames required')
    if set(engine.output_names(contract)) & set(names):
        raise ValueError('native outputs may not overwrite generated cards or publications')
    files = [request_path, point_path, format_path, source_path]
    outputs = {}
    if request['action'] == 'parse':
        if 'execution' in request or type(request.get('outputs')) is not list:
            raise ValueError('parse requires supplied output pins and no launch specification')
        for row in request['outputs']:
            _keys(row, ('name', 'path', 'sha256'), label='program output pin')
            name = _basename(row['name'])
            if name in outputs:
                raise ValueError('duplicate output filename')
            path = custody._pin({'path': row['path'], 'sha256': row['sha256']}, request_path.parent)
            outputs[name] = path.read_text()
            files.append(path)
        engine.parse_outputs(point, contract, outputs)
    else:
        if 'outputs' in request or 'execution' not in request:
            raise ValueError('prepare requires an explicit native job specification, never supplied outputs')
        files.append(_binary(request['execution'], request_path.parent))
    from ravel.physics import higgs_decay_programs
    from ravel.physics.higgs_decay_programs import adapters, formats
    registry = Path(__file__).resolve().parents[1] / 'data/higgs/decay-programs.json'
    files += [Path(__file__), Path(higgs_decay_programs.__file__), Path(adapters.__file__),
              Path(formats.__file__), registry, Path(__import__('ravel.physics.resonance_width', fromlist=['']).__file__)]
    return request, point, contract, engine, outputs, list(dict.fromkeys(files))


def _binary(execution, base):
    from ravel.physics import model_tool_bridge as custody
    _keys(execution, ('binary', 'arguments', 'max_seconds', 'disk_bytes'), label='native execution specification')
    if type(execution['arguments']) is not list:
        raise ValueError('explicit argument vector required')
    for item in execution['arguments']:
        _text(item, 'native argument')
    _num(execution['max_seconds'], 'max_seconds', positive=True)
    if type(execution['disk_bytes']) is not int or execution['disk_bytes'] <= 0:
        raise ValueError('positive integer disk_bytes required')
    return custody._pin(execution['binary'], base)


def inputs(task, base):
    return _load(task, base)[-1]


def native_job(point, contract, execution, base):
    """A job description for existing supervised admission, never a direct launcher."""
    engine = adapter(point['program'])
    if point['program'] == 'FeynHiggs':
        return engine.scope_tools_job(point, contract, execution, base)
    binary = _binary(execution, base)
    card = engine.render_card(point, contract)
    return {'command': [str(binary), *execution['arguments']], 'cwd': 'generated_card_directory',
            'program': point['program'], 'version': point['version'], 'order': point['order'],
            'ew_scheme': point['ew_scheme'], 'input_card': contract['card']['filename'],
            'input_card_sha256': hashlib.sha256(card.encode()).hexdigest(),
            'binary': dict(execution['binary']), 'max_seconds': execution['max_seconds'],
            'disk_bytes': execution['disk_bytes'], 'expected_outputs': engine.output_names(contract),
            'launch_interface': 'ravel.workflow.launch_authorization.authorized_popen',
            'requires': ['method-decision record', 'scientific admission', 'bound supervised stage'],
            'launch_performed': False, 'physics_validated': False}


def run(task, base, output):
    """Render cards and consume supplied outputs, within the scientific worker contract."""
    from ravel.physics import model_tool_bridge as custody
    request, point, contract, engine, outputs, files = _load(task, base)
    before = {p: custody._hash(p) for p in files}
    unresolved = Path(output).absolute()
    out = unresolved.resolve()
    if any(p.is_symlink() for p in (unresolved, *unresolved.parents)) or any(p.is_relative_to(out) for p in files):
        raise ValueError('fresh output may not alias or contain input files')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError('fresh empty output directory required')
    result = {'status': 'passed', 'physics_validated': False, 'action': request['action'],
              'program': point['program'], 'version': point['version'], 'order': point['order'],
              'ew_scheme': point['ew_scheme'], 'format_pin': request['format'],
              'model_point_pin': request['point'],
              'format_source_pin': request['format_source'], 'layout_qualified': False,
              'limitations': ['Supplied format schemas are not native layout or physics qualification.',
                              'Sector widths cannot populate a complete scalar SLHA branching set.']}
    slha = None
    if request['action'] == 'parse':
        result['output_pins'] = request['outputs']
        result['decay_table'] = engine.parse_outputs(point, contract, outputs)
        result['decay_table']['format_provenance'] = {k: request[k] for k in ('format', 'format_source')}
        if request['publication']['slha'] is not None:
            slha = to_slha(result['decay_table'])
    else:
        request_base = custody._regular(task['request'], base).parent
        result['native_job'] = native_job(point, contract, request['execution'], request_base)
    card = engine.render_card(point, contract)
    if any(custody._hash(p) != digest for p, digest in before.items()):
        raise ValueError('bound input bytes changed during decay transport')
    out.mkdir(parents=True, exist_ok=True)
    (out / contract['card']['filename']).write_text(card)
    if slha is not None:
        (out / request['publication']['slha']).write_text(slha)
    custody._write(out / request['publication']['json'], result)
    return result


def main(argv=None):
    """Read-only comparison or local card/output transport; never native launch."""
    import argparse
    import sys
    from ravel.physics import model_tool_bridge as custody
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    transport = commands.add_parser('transport', help='Render a card or parse pinned supplied output files')
    transport.add_argument('--request', required=True)
    transport.add_argument('--base', required=True)
    transport.add_argument('--output', required=True)
    comparison = commands.add_parser('compare', help='Compare supplied cited reference rows at an exact mass')
    comparison.add_argument('--table', required=True)
    comparison.add_argument('--reference-rows', required=True)
    comparison.add_argument('--pdg', type=int, required=True)
    comparison.add_argument('--channels', nargs='+', required=True)
    comparison.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'transport':
            run({'request': args.request}, args.base, args.output)
            return 0
        table = custody._read(custody._regular(args.table, Path.cwd()))
        rows = custody._read(custody._regular(args.reference_rows, Path.cwd()))
        if type(table) is not dict:
            raise ValueError('decay table object required')
        result = compare_reference(table.get('decay_table', table), rows, pdg=args.pdg,
                                   required_channels=args.channels)
        unresolved = Path(args.output).absolute()
        target = unresolved.resolve()
        if target.exists() or any(p.is_symlink() for p in (unresolved, *unresolved.parents)):
            raise ValueError('fresh ordinary comparison output path required')
        target.parent.mkdir(parents=True, exist_ok=True)
        custody._write(target, result)
        return 0 if result['passed'] else 1
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
