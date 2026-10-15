"""Bind the shipped analysis assets to the engines that consume supplied descriptors.

``data/analysis_assets``, ``data/native_cumulants`` and ``data/sfitter/published-records``
hold source-pinned descriptors and source bundles. The engines take descriptors as input and
read source bytes by pin, so each function here only resolves package-relative names to
absolute pins and checks every pinned byte stream; it interprets nothing and runs nothing.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'
ASSETS = DATA / 'analysis_assets'
CUMULANTS = DATA / 'native_cumulants'


class AssetError(ValueError):
    def __init__(self, message, reason='invalid_input'):
        super().__init__(message)
        self.reason = reason


def _require(ok, why, reason='invalid_input'):
    if not ok:
        raise AssetError(why, reason)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pin(path):
    return {'path': str(Path(path).absolute()), 'sha256': _sha(path)}


def _checked(path, expected, label):
    path = Path(path)
    _require(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)),
             f'ordinary {label} file required: {path}')
    _require(_sha(path) == expected, f'{label} bytes differ from the shipped pin: {path.name}')
    return path.absolute()


def _json(path):
    return json.loads(Path(path).read_bytes())


def _study(study, default):
    from .truth_reco_response import study_contract
    return study_contract(copy.deepcopy(study if study is not None else default))


# --------------------------------------------------------------------------------------------
# Native cumulant bundle
# --------------------------------------------------------------------------------------------

def cumulant_mapping(*, native_weight='', study=None):
    """The complete ``native-cumulant/v1`` mapping with pins to the shipped source bundle.

    ``native_weight`` names the weight stream whose suffixed outputs are mapped ('' is the
    nominal stream); every output and RAW operand is retained for it."""
    mapping = _json(CUMULANTS / 'mapping.json')
    for pin in mapping['sources']:
        pin['path'] = str(_checked(CUMULANTS / pin['path'], pin['sha256'], 'cumulant source'))
    _require(isinstance(native_weight, str) and native_weight.isascii()
             and not any(c.isspace() or c in '[]' for c in native_weight), 'explicit ASCII native weight required')
    suffix = f'[{native_weight}]' if native_weight else ''
    mapping['native_weight'] = {'native': native_weight, 'suffix': suffix}
    if study is not None:
        mapping['study'] = _study(study, mapping['study'])
    return mapping


# --------------------------------------------------------------------------------------------
# Six-b trace/classifier package
# --------------------------------------------------------------------------------------------

SIXB = ASSETS / 'six-b'
SIXB_DEPENDENCIES = (
    'include/Rivet/Event.hh', 'include/Rivet/Analysis.hh', 'include/Rivet/Tools/RivetHepMC.hh',
    'include/Rivet/Tools/ExptSmearingFunctions.hh', 'include/Rivet/Tools/RivetONNXrt.hh',
    'src/Core/Event.cc', 'src/Core/Analysis.cc', 'src/Core/AnalysisInfo.cc', 'src/Core/AnalysisHandler.cc',
    'src/Projections/Sphericity.cc', 'include/Rivet/Projections/Sphericity.hh',
    'include/Rivet/Projections/SmearedJets.hh', 'include/Rivet/Projections/SmearedParticles.hh')


def six_b_descriptor():
    """The instrumentation package/v1 JSON (trace manifest, edits, model roster, build, study)."""
    return _json(SIXB / 'descriptor.json')


def six_b_contracts():
    """The six source-classifier feature contracts keyed by contract id, absolute resource paths."""
    contracts = _json(SIXB / 'contracts.json')
    for contract in contracts.values():
        for key in ('source', 'model'):
            contract[key]['path'] = str(SIXB / contract[key]['path'])
        for excerpt in contract['source_excerpts']:
            excerpt['file'] = copy.deepcopy(contract['source'])
    return contracts


def six_b_prepare_input(output):
    """Write ``prepare-input.json``, ``contracts.json`` and the reference into a fresh directory.

    Returns the ``prepare-source`` task for ``analysis-response-features``. The pins name the
    shipped package bytes directly, except that the reference is copied under the basename the
    instrumented routine loads it by (the original routine's own name), and ``contracts.json``
    carries absolute resource paths."""
    out = Path(output).absolute()
    _require(not out.exists() and not out.is_symlink() and '..' not in out.parts,
             'fresh ordinary six-b input directory required')
    descriptor_path = SIXB / 'descriptor.json'
    descriptor = _json(descriptor_path)
    original = descriptor['routine']
    source = _checked(SIXB / 'source/routine.cc', descriptor['instrumentation']['source_sha256'], 'six-b source')
    contracts = six_b_contracts()
    models = {}
    for key, row in descriptor['models'].items():
        contract = contracts[row['contract']]
        models[key] = _checked(SIXB / contract['model']['path'], contract['model']['sha256'], 'six-b model')
    out.mkdir(parents=True)
    reference = out / (original + '.yoda.gz')
    reference.write_bytes((SIXB / 'source/reference.yoda.gz').read_bytes())
    contract_path = out / 'contracts.json'
    contract_path.write_text(json.dumps(contracts, sort_keys=True, allow_nan=False) + '\n')
    document = {
        'schema_version': 1,
        'instrumentation': _pin(descriptor_path),
        'source': _pin(source),
        'info': _pin(SIXB / 'source/routine.info'),
        'reference': _pin(reference),
        'models': {key: _pin(path) for key, path in models.items()},
        'contracts': _pin(contract_path),
        'dependencies': [_pin(SIXB / name) for name in SIXB_DEPENDENCIES],
    }
    input_path = out / 'prepare-input.json'
    input_path.write_text(json.dumps(document, sort_keys=True, allow_nan=False) + '\n')
    return {'schema_version': 1, 'operation': 'prepare-source', 'input': str(input_path),
            'input_sha256': _sha(input_path)}


# --------------------------------------------------------------------------------------------
# Native fill-site schemas
# --------------------------------------------------------------------------------------------

def group_fill_routines():
    return sorted(_json(ASSETS / 'group-fills/descriptors.json')['routines'])


def _reference_geometry(path):
    with gzip.open(path, 'rt') as stream:
        text = stream.read()
    return {name.replace('/REF', '', 1): json.loads(re.search(r'^Edges\(A1\): (.+)$', body, re.M)[1])
            for name, body in re.findall(r'^BEGIN YODA_ESTIMATE1D_V3 (/REF/[^\n]+)\n(.*?)^END YODA_ESTIMATE1D_V3',
                                         text, re.M | re.S)}


def group_fill_contract(routine, *, rivet_prefix, mode=None, weight_suffixes=('',), study=None,
                        extra_native_objects=()):
    """Static ``native-group-acquisition`` contract members for one released routine.

    ``rivet_prefix`` is the installed Rivet 4.1.4 prefix holding ``share/Rivet/<routine>.cc`` and
    its reference file; edges come from that reference. ``weight_suffixes`` are the RAW suffixes
    of the selected weight streams, which fix the native object census. A routine that books
    objects beyond the RAW, final, counter and cross-section objects lists them in
    ``extra_native_objects``. Returns the members to merge into the run's contract:
    ``fill_schema``, ``outputs``, ``reference``, ``routine``, ``native_analysis_alias`` and
    ``original_source_sha256`` (and ``analysis_options`` when the routine has modes)."""
    descriptors = _json(ASSETS / 'group-fills/descriptors.json')
    _require(routine in descriptors['routines'], f'no shipped fill schema for {routine!r}', 'missing_input')
    row = descriptors['routines'][routine]
    prefix = Path(rivet_prefix).absolute()
    source = _checked(prefix / row['source'], row['source_sha256'], 'routine source')
    reference = _checked(prefix / row['reference'], row['reference_sha256'], 'reference')
    modes = row['modes']
    if modes:
        _require(mode in modes, f'explicit routine mode required: {sorted(modes)}')
    else:
        _require(mode is None, 'routine has no mode')
    settings = modes.get(mode, {})
    alias = row['alias'].format(routine=routine, mode=mode)
    format_args = {'alias': alias, 'routine': routine, **settings}
    geometry = _reference_geometry(reference)
    outputs = []
    for item in row['outputs']:
        ref = item['reference'].format(**format_args)
        _require(ref in geometry, f'reference geometry absent: {ref}')
        out = {'id': item['id'], 'site': item['site'], 'path': item['path'].format(**format_args),
               'edges': geometry[ref], 'axis_unit': item['axis_unit'], 'unit': '1',
               'source_fill_weight': 1, 'source_fill_fraction': 1, 'reference_path': ref}
        if 'group_low' in item:
            out['group_low'], out['group_high'] = item['group_low'], item['group_high']
        outputs.append(out)
    _require(isinstance(weight_suffixes, (list, tuple)) and weight_suffixes
             and len(set(weight_suffixes)) == len(weight_suffixes)
             and all(isinstance(s, str) for s in weight_suffixes), 'unique RAW weight suffixes required')
    objects = ['/_XSEC']
    for suffix in weight_suffixes:
        for out in outputs:
            objects += ['/RAW' + out['path'] + suffix, out['path'] + suffix]
        objects.append('/RAW/_EVTCOUNT' + suffix)
        if settings.get('ancillary'):
            for index in range(1, 5):
                name = f'/{alias}/d{index:02d}-x01-y01' + suffix
                objects += [name, '/RAW' + name]
    objects += list(extra_native_objects)
    sources = []
    if modes:
        # The option namespace of the released handler and the unit definitions behind the
        # booked axes: both are read by the native census, so both are pinned.
        for item in descriptors['naming_sources']:
            sources.append(_pin(_checked(ASSETS / item['package_path'], item['sha256'], 'naming source')))
        units = prefix / descriptors['units_header']['prefix_path']
        _require(units.is_file() and _sha(units) in descriptors['units_header']['accepted_sha256'],
                 'a supported Rivet Units.hh is required under the prefix')
        sources.append(_pin(units))
    schema = {'schema_version': 1, 'routine': routine, 'native_analysis_alias': alias,
              'source': _pin(source), 'sources': sources, 'sites': copy.deepcopy(row['sites']),
              'outputs': outputs, 'rules': copy.deepcopy(row['rules']),
              'native_object_paths': list(dict.fromkeys(objects)),
              'study': _study(study, {'study_id': routine, 'parameter_grid': [], 'datasets': ['supplied-events'],
                                      'output': {'stem': 'native-group-acquisition', 'formats': ['json']}})}
    result = {'fill_schema': schema, 'outputs': copy.deepcopy(outputs), 'reference': _pin(reference),
              'routine': routine, 'native_analysis_alias': alias, 'original_source_sha256': row['source_sha256']}
    if modes:
        result['analysis_options'] = {row['options_key']: mode}
    return result


# --------------------------------------------------------------------------------------------
# Response contract and cutflow definition
# --------------------------------------------------------------------------------------------

def response_contract(*, four_state=True, study=None):
    """The direct slepton-lepton ``response_contract/v1``.

    ``four_state`` keeps the topology rules of the four-state production sample (two
    same-species opposite-sign root sleptons, two stable lightest neutralinos, two direct
    leptons); without it the contract carries no topology requirement."""
    contract = _json(ASSETS / 'response/slepton-direct-lepton.json')
    if not four_state:
        contract['topology'] = []
    if study is not None:
        value = _study(study, {})
        for key in ('study_id', 'parameter_grid', 'datasets'):
            contract[key] = value[key]
    from .truth_reco_response import response_contract as validate
    return validate(contract)


def cutflow_definition(selection_source, output, *, luminosity_pb_inverse=None):
    """Write the compressed-selection ``cutflow-definition`` bound to the producer bytes.

    ``selection_source`` is the source file of the selected routine that writes the trace; the
    definition binds exactly its bytes (``compressed_validation.native_plan_inputs`` checks
    that). Returns the byte pin for ``compressed_validation.bind``."""
    out = Path(output).absolute()
    _require(not out.exists() and not out.is_symlink() and '..' not in out.parts,
             'fresh ordinary cutflow-definition directory required')
    template = ASSETS / 'cutflow/compressed-slepton.cutflow.json'
    value = _json(template)
    producer = Path(selection_source).absolute()
    _require(producer.is_file() and not any(p.is_symlink() for p in (producer, *producer.parents)),
             'ordinary selection source file required', 'missing_input')
    out.mkdir(parents=True)
    note = out / 'review-note.md'
    note.write_bytes((ASSETS / 'review-note.md').read_bytes())
    _require(_sha(note) == value['review']['evidence'][0]['sha256'], 'shipped evidence note differs from its pin')
    value['sources'] = {'selection': _pin(producer)}
    if luminosity_pb_inverse is not None:
        _require(type(luminosity_pb_inverse) in (int, float) and luminosity_pb_inverse > 0, 'positive luminosity required')
        value['normalization']['luminosity_pb_inverse'] = float(luminosity_pb_inverse)
    path = out / 'cutflow.json'
    path.write_text(json.dumps(value, allow_nan=False) + '\n')
    return _pin(path)
