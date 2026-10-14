"""Prepare literal source scale-factor bindings; never construct detector events.

The complete supplied decoded/ROOT census is retained, including modes that the
existing scalar provider cannot represent. Native alternatives are separate
recipes, not independent efficiencies or factors to multiply together.
"""
from pathlib import Path
import hashlib
import json
import re

from ravel.physics.ma5_saf import Capture, _json, _keys
from ravel.workflow.state_io import atomic_json
from . import provider, _scalar, formulas, kernels

SOURCE_HASHES = {
    'common_efficiency': '97b0e3c22b97f617acb2d5b739aec149f50aa7c7365c278dae975cd0ab94f1b2',
    'helper_functions': '4db7f16915805621f10ddcd296a503c4466c2af4f7d7f793ad11f49fca1555dc',
    'tool_configuration': provider.EMPTY_WP_CONFIGURATION_SHA256,
    'trigger_tool': 'e6738649e3a97438933f8cea08bae6f8907d870f6fdf2752f7b197395738b462',
    'shared_files_version': '2a18e104999636ed0c2092ec5172e341910bed0d0b4457adeca400e42384738b',
}
MAX_INPUT_BYTES = 32 * 1024**2
MAX_RECIPES = 256
LEGAL_WP = {
    'JetID': {'jetbdtsigloose', 'jetbdtsigmedium', 'jetbdtsigtight'},
    'Reco': {''},
    'EleOLR': {'', 'TauEleOLR', 'eleBDTLoose', 'eleBDTLoosePlusVeto',
               'eleBDTMedium', 'eleBDTMediumPlusVeto', 'eleBDTTight', 'eleBDTTightPlusVeto',
               'EleLooseLLHOLR', 'EleMediumLLHOLR', 'EleTightLLHOLR'},
    'Trigger': {'all_loose', 'all_medium', 'all_tight'},
}
SCOPE = 'literal marginal data/MC scale-factor recipes; not absolute efficiency, joint response or analysis applicability'


def _pin(path, raw):
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def _read_pin(capture, pin, base):
    result = capture.pin(pin, base)
    if sum(len(raw) for _, raw in capture.files.values()) > MAX_INPUT_BYTES:
        raise ValueError('aggregate response source preparation byte bound exceeded')
    return result


def _emit(capture, path, value):
    expected = hashlib.sha256((json.dumps(value, indent=2, allow_nan=False) + '\n').encode()).hexdigest()
    atomic_json(path, value)
    _, raw = capture.read(path, path.parent, expected)
    return _pin(path, raw)


def _load(request, expected_sha256=None):
    capture = Capture()
    path, raw = capture.read(request, Path.cwd(), expected_sha256)
    spec = _json(raw)
    _keys(spec, {'schema_version', 'kind', 'native_sources', 'decoded', 'root_key_census', 'payloads', 'scope'}, 'response recipe request')
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1 or spec['kind'] != 'athena-marginal-calibration-recipes':
        raise ValueError('explicit Athena marginal recipe request/v1 required')
    _keys(spec['native_sources'], set(SOURCE_HASHES), 'complete native source profile')
    for role, pin in spec['native_sources'].items():
        if pin.get('sha256') != SOURCE_HASHES[role]:
            raise ValueError('released native source profile differs: ' + role)
        _read_pin(capture, pin, path.parent)
    decoded_path, decoded_raw = _read_pin(capture, spec['decoded'], path.parent)
    decoded = _json(decoded_raw)
    if type(decoded.get('payloads')) is not list or not 1 <= len(decoded['payloads']) <= 64:
        raise ValueError('complete bounded decoded payload census required')
    _, key_raw = _read_pin(capture, spec['root_key_census'], path.parent)
    key_census = _json(key_raw)
    if type(key_census.get('payloads')) is not list:
        raise ValueError('complete original physical-key census required')
    physical = {}
    for row in key_census['payloads']:
        key = (row.get('path'), row.get('sha256'))
        if key in physical or type(row.get('records')) is not list or not row['records']:
            raise ValueError('unique complete physical ROOT record census required')
        physical[key] = row
    scope_path, scope_raw = _read_pin(capture, spec['scope'], path.parent)
    scope = _json(scope_raw)
    if type(scope) is not dict:
        raise ValueError('explicit applicable population/channel/era prerequisites required')
    if type(spec['payloads']) is not list or len(spec['payloads']) != len(decoded['payloads']):
        raise ValueError('every decoded primary payload must remain in the source census')
    index = {}
    for row in decoded['payloads']:
        key = (row.get('path'), row.get('sha256'))
        if key in index:
            raise ValueError('duplicate decoded primary identity')
        index[key] = row
    records = []
    seen = set()
    for record in spec['payloads']:
        _keys(record, {'root', 'domain', 'population'}, 'primary payload configuration')
        _keys(record['domain'], {'configuration_namespace', 'simulation_namespace', 'era_namespace'}, 'native domain')
        for value in record['domain'].values():
            provider._text(value)
        root, root_raw = _read_pin(capture, record['root'], path.parent)
        key = (str(root), hashlib.sha256(root_raw).hexdigest())
        if key not in index or key in seen:
            raise ValueError('original ROOT and complete decoded identity census differ')
        seen.add(key)
        population_path, population_raw = _read_pin(capture, record['population'], path.parent)
        if type(_json(population_raw)) is not dict:
            raise ValueError('explicit source population/configuration declaration required')
        payload = index[key]
        if key not in physical or physical[key].get('bytes') != len(root_raw):
            raise ValueError('physical record census and original ROOT identity differ')
        available = {(obj['name'], obj['cycle'], obj['class']) for obj in physical[key]['records']}
        for obj in payload['objects']:
            name, cycle = obj['key'].rsplit(';', 1)
            if name != obj['name'] or (name, int(cycle), obj['class']) not in available:
                raise ValueError('decoded key/cycle/class absent from retained physical record census')
        payload = {**payload, '_physical_record_count': len(physical[key]['records'])}
        # The added count is receipt metadata, not part of the original decoded
        # content commitment consumed by CalibrationProvider.
        records.append((root, payload, record['domain'], _pin(population_path, population_raw)))
    if len(seen) != len(index) or set(physical) != set(index):
        raise ValueError('missing original primary payload')
    if sum(len(raw) for _, raw in capture.files.values()) > MAX_INPUT_BYTES:
        raise ValueError('aggregate response source preparation byte bound exceeded')
    capture.finish()
    return capture, path, spec, decoded_path, records, _pin(scope_path, scope_raw)


def input_pins(request, *, expected_sha256=None):
    """Complete ordinary Graph input closure, authenticated afresh per call."""
    capture, _, _, _, _, _ = _load(request, expected_sha256)
    return [_pin(path, raw) for path, (_, raw) in capture.files.items()]


def _coordinates(payload):
    coordinates = payload.get('literal_coordinates')
    if type(coordinates) is not dict:
        raise ValueError('source axis metadata and coordinate routes required')
    def title(axis):
        metadata = coordinates.get(axis + '_metadata')
        if metadata is None:
            return None
        if type(metadata) is not dict or metadata.get('name') != axis.upper() + 'axis' or metadata.get('class') != 'TNamed':
            raise ValueError('literal native TNamed axis metadata required')
        return metadata.get('title')
    x = {'P': 'final_p', 'PFinalCalib': 'final_p', 'TruthDecayMode': 'truth_decay_mode',
         'truth pt': 'truth_pt'}.get(title('x'), 'final_pt')
    y = {'track-eta': 'track_eta', '|eta|': 'final_abs_eta', 'mu': 'mu',
         'truth |eta|': 'truth_abs_eta_literal'}.get(title('y'), 'final_eta')
    if coordinates.get('x') != x or coordinates.get('y') != y:
        raise ValueError('decoded coordinate routing differs from pinned native metadata law')
    return x, y


def _aliases(payload):
    """Literal ReadInputs aliases for the whole native readable object census."""
    expected = {}
    for obj in payload['objects']:
        if obj['class'] not in ('TH2F', 'TH2D', 'TH3F', 'TH3D', 'TF1'):
            continue
        name = obj['name']
        if name.startswith('sf_') or '_up_' in name or '_down_' in name:
            names = [name]
        else:
            stem, separator, suffix = name.partition('_')
            if not separator:
                raise ValueError('native nuisance object lacks a represented suffix')
            names = [stem + '_' + direction + '_' + suffix for direction in ('up', 'down')]
        for alias in names:
            if alias in expected:
                raise ValueError('ambiguous native alias/object cycles')
            expected[alias] = {'key': obj['key'], 'class': obj['class']}
    supplied = payload.get('source_efficiency_aliases')
    if type(supplied) is not dict or set(supplied) != set(expected):
        raise ValueError('complete native ReadInputs alias census differs')
    for alias, row in expected.items():
        if supplied[alias].get('key') != row['key'] or supplied[alias].get('class') != row['class']:
            raise ValueError('native asymmetric alias/key/class routing differs')
    return expected


def _compile(root, payload, namespaces, population, sources):
    physical_count = payload['_physical_record_count']
    payload = {key: value for key, value in payload.items() if key != '_physical_record_count'}
    name = root.name
    parts = name.split('_')
    component = parts[0]
    result = {'root': {'path': str(root), 'sha256': payload['sha256']},
              'domain': namespaces, 'population': population, 'recipes': [],
              'physical_record_count': physical_count,
              'retained_objects': [{'key': x['key'], 'class': x['class'],
                 'disposition': ('native axis metadata' if x['class'] == 'TNamed' else
                     'not read by native CommonEfficiencyTool; no scalar fallback' if x['class'].startswith('TH1') else
                     'retained exact source object; consumer depends on selected native configuration')}
                  for x in payload['objects']],
              'unsupported': []}
    if component not in LEGAL_WP:
        result['unsupported'].append({'mode': component, 'reason': 'TES is native smearing; selection cuts and split campaign/substructure tools are not marginal recipe alternatives'})
        return result, []
    if len(parts) < 3 or parts[1] not in ('TrueHadTau', 'TrueElectron'):
        raise ValueError('supported native file/truth namespace required')
    x, y = _coordinates(payload)
    compiled = _scalar.CompiledPayload.compile(payload, payload['sha256'], _scalar.decoded_payload_digest(payload))
    aliases = _aliases(payload)
    nominal = {}
    for obj in payload['objects']:
        match = re.fullmatch(r'sf(?:_(.*))?_(1|3)p', obj['name'])
        if match:
            wp, prong = match.group(1) or '', match.group(2)
            if (wp, prong) in nominal:
                raise ValueError('ambiguous nominal ROOT object cycles')
            nominal[wp, prong] = obj['key']
    alternatives = sorted({wp for wp, _ in nominal})
    if not alternatives:
        result['unsupported'].append({'mode': component, 'reason': 'no represented unsplit source prong/working-point configuration'})
    bindings = []
    for wp in alternatives:
        if wp not in LEGAL_WP[component] or (wp == '' and parts[1] != 'TrueHadTau'):
            result['unsupported'].append({'working_point': wp, 'reason': 'not a represented released native tool configuration'})
            continue
        unity = component == 'EleOLR'
        prongs = ('1',) if unity else ('1', '3')
        if any((wp, prong) not in nominal for prong in prongs):
            result['unsupported'].append({'working_point': wp, 'reason': 'incomplete required native prong census'})
            continue
        endings = {prong: (('_' + wp) if wp else '') + '_' + prong + 'p' for prong in prongs}
        stems = set()
        for alias in aliases:
            for ending in endings.values():
                match = re.fullmatch(r'([A-Za-z0-9]+)_(up|down)' + re.escape(ending), alias)
                if match:
                    stems.add(match.group(1))
        if len({stem.upper() for stem in stems}) != len(stems):
            raise ValueError('ambiguous native CP nuisance basename capitalization')
        nuisances = {}
        nuisance_census = []
        for stem in sorted(stems):
            nuisance = 'TAUS_' + parts[1].upper() + '_EFF_' + component.upper() + '_' + stem.upper()
            entries = {}
            for prong in prongs:
                pair = {}
                for direction in ('up', 'down'):
                    alias = stem + '_' + direction + endings[prong]
                    if alias not in aliases:
                        raise ValueError('incomplete asymmetric native nuisance/prong census')
                    key = aliases[alias]['key']
                    _scalar._object(compiled, key)
                    pair[direction + '_key'] = key
                    pair[direction + '_alias'] = alias
                entries[prong] = [{**pair, 'parameter': 1.0}]
            nuisances[nuisance] = entries
            nuisance_census.append({'id': nuisance, 'native_object_stem': stem,
                'recommended': stem[:1].isupper() or stem[1:2].isupper(),
                'correlation_identity': nuisance,
                'evaluation': 'separate coherent up/down alternative; recommended sets cannot be combined with other variations'})
        for prong in prongs:
            _scalar._object(compiled, nominal[wp, prong])
        domain = {'athena_commit': provider.ATHENA_COMMIT,
                  'shared_files_version': provider.SHARED_FILES_VERSION, **namespaces, 'working_point': wp}
        binding = {'domain': domain, 'correction': {
            'binding_id': name + ':' + (wp or 'native-empty-WP'),
            'quantity': 'marginal_data_over_mc_sf', 'payload_sha256': payload['sha256'],
            'decoded_payload_sha256': compiled.decoded_digest, 'expected_truth': 'had_tau' if parts[1] == 'TrueHadTau' else 'electron',
            'three_prong_unity': unity, 'x_coordinate': x, 'y_coordinate': y,
            'keys_by_prong': {prong: {'nominal': nominal[wp, prong]} for prong in prongs}, 'nuisances': nuisances}}
        if wp == '':
            tool = 'RecoHadTauTool' if component == 'Reco' else 'EleOLRHadTauTool'
            domain['empty_wp_tool'] = tool
            binding['native_configuration'] = {'tool': tool, 'working_point': '', 'source': sources['tool_configuration']}
        native = {'tool': 'TauEfficiencyTriggerTool' if component == 'Trigger' else 'CommonEfficiencyTool',
                  'working_point': wp.removeprefix('all_') if component == 'Trigger' else wp,
                  'period_binning': 'all' if component == 'Trigger' else None,
                  'split_mu': False, 'split_campaign': False, 'use_substructure': False, 'skip_truth_match': False}
        item = {'working_point': wp, 'native_configuration': native, 'nuisances': nuisance_census,
                'quantity': 'marginal_data_over_mc_sf', 'population': population,
                'coordinate_law': {'x': x, 'y': y, 'momentum_unit': 'GeV',
                    'histogram': 'native xmin/xmax*0.999 clamp; FindFixBin; no interpolation',
                    'TF1': 'checked zero-parameter 1D expression; no histogram clamp'},
                'analysis_applicability': 'requires independent source/configuration/population review'}
        result['recipes'].append(item)
        bindings.append(binding)
    return result, bindings


def prepare(request, output_dir, *, expected_sha256=None):
    """Public source-to-binding preparation; outputs are unqualified inputs."""
    capture, path, spec, decoded_path, records, scope = _load(request, expected_sha256)
    destination = Path(output_dir).absolute()
    if '..' in destination.parts or destination.exists() or destination.is_symlink():
        raise ValueError('fresh canonical response preparation directory required')
    capture.ordinary(destination.parent, directory=True)
    if any(input_path.is_relative_to(destination) or destination.is_relative_to(input_path.parent)
           for input_path in capture.files if input_path != path):
        raise ValueError('response preparation must not change a committed input root')
    sources = {role: _pin(p, raw) for role, pin in spec['native_sources'].items()
               for p, raw in [capture.pin(pin, path.parent)]}
    census, compiled = [], []
    for root, payload, domain, population in records:
        row, bindings = _compile(root, payload, domain, population, sources)
        census.append(row)
        compiled.extend((row, item, binding) for item, binding in zip(row['recipes'], bindings))
    if len(compiled) > MAX_RECIPES:
        raise ValueError('response recipe count bound exceeded')
    capture.finish()
    destination.mkdir()
    outputs = []
    for ordinal, (row, item, binding) in enumerate(compiled):
        output = destination / ('binding-%04d.json' % ordinal)
        binding_pin = _emit(capture, output, binding)
        # Exercise the ordinary existing consumer's admission, without evaluating
        # any event or treating a decoded payload as experimental calibration.
        provider.CalibrationProvider.load(decoded=provider.ArtifactPin(str(decoded_path), spec['decoded']['sha256']),
            original_root=provider.ArtifactPin(**row['root']), binding=provider.ArtifactPin(**binding_pin))
        item['binding'] = binding_pin
        outputs.append(binding_pin)
    receipt = {'schema_version': 1, 'kind': 'prepared-athena-marginal-recipes',
        'request': _pin(path, capture.files[path][1]), 'decoded': _pin(decoded_path, capture.files[decoded_path][1]),
        'native_sources': sources, 'scope_input': scope, 'primary_census': census,
        'physical_key_census': spec['root_key_census'],
        'binding_count': len(compiled), 'quantity': 'marginal_data_over_mc_sf',
        'outputs': outputs, 'scope': SCOPE,
        'population_transform': 'none; no event filtering, resampling, weight composition or reconstructed-state production',
        'native_evaluation_performed': False, 'analysis_approval': False, 'scientific_acceptance': False,
        'remaining_requirements': ['analysis-matched producer/release/campaign configuration',
            'complete reconstructed/truth event and all named-weight/group populations',
            'joint ID/trigger/isolation/top-veto response where required; no marginal-factor inference',
            'native parity and full p4/MET/OR/mT2 variations with source modifier correlations']}
    receipt_path = destination / 'preparation.json'
    receipt_pin = _emit(capture, receipt_path, receipt)
    capture.finish()
    if set(destination.iterdir()) != {receipt_path, *(Path(pin['path']) for pin in outputs)}:
        raise ValueError('ending generated response recipe membership differs')
    capture.finish()
    return {'receipt': receipt_pin, 'binding_count': len(compiled), 'scope': SCOPE,
            'analysis_approval': False, 'scientific_acceptance': False}
