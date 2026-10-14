"""Explicit calibration-only Rivet preload admission; no calibration generation.

One file is intentional: pinned AnalysisHandler::readData replaces _preloads.
No RAW/event-count/object resumption, percentile reimplementation or weights from
marginal errors. Dispatch evidence never means the native projection consumed it.
"""
import hashlib
import math
import re
from pathlib import Path
from ravel.physics import native_categorical, native_estimate


class PreloadError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PreloadError(message)


def _source(source):
    require(type(source) is dict and set(source) == {'path', 'sha256', 'first_line', 'last_line', 'text'}, 'exact source excerpt pin required')
    require(type(source['path']) is str and Path(source['path']).is_absolute(), 'absolute source path required')
    require(type(source['sha256']) is str and re.fullmatch('[0-9a-f]{64}', source['sha256']), 'source SHA256 required')
    require(type(source['first_line']) is int and type(source['last_line']) is int and 1 <= source['first_line'] <= source['last_line'], 'source line interval required')
    require(type(source['text']) is str and source['text'].strip(), 'nonempty source excerpt required')


def validate(task):
    if 'centrality_preload' not in task:
        return
    c = task['centrality_preload']
    require(type(c) is dict and set(c) == {'schema_version', 'path', 'sha256', 'mode', 'calibration_analysis', 'histogram', 'routine_source', 'source_dependencies', 'provenance', 'weight_policy', 'origin'}, 'closed single centrality preload contract required')
    require(type(c['schema_version']) is int and c['schema_version'] == 1, 'preload schema1 required')
    require(task.get('backend') in ('rivet', 'rivet-built'), 'preload only supported through Rivet')
    require(task.get('runtime', {}).get('version') in ('4.1.3', '4.1.4'), 'source-qualified preload semantics limited to Rivet4.1.3/4.1.4')
    require(type(c['path']) is str and bool(c['path']) and ',' not in c['path'], 'single preload path; native CLI splits commas')
    require(type(c['sha256']) is str and re.fullmatch('[0-9a-f]{64}', c['sha256']), 'calibration SHA256 required')
    require(c['mode'] in ('GEN', 'IMP', 'USR') and task.get('options', {}).get('cent') == c['mode'], 'explicit matching cent=GEN/IMP/USR required')
    for key in ('calibration_analysis', 'histogram'):
        require(type(c[key]) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_]*', c[key]), 'literal calibration identity required')
    require(c['calibration_analysis'] != task['routine'], 'calibration cannot resume the executing analysis')
    require(type(c['provenance']) is str and c['provenance'].strip(), 'calibration producer/model/beam applicability description required')
    origin = c['origin']
    require(type(origin) is dict and set(origin) == {'path', 'sha256'} and type(origin['path']) is str and origin['path'] and type(origin['sha256']) is str and re.fullmatch('[0-9a-f]{64}', origin['sha256']), 'original calibration-output pin required')
    require(c['weight_policy'] == 'source_calibration_unverified', 'calibration weight applicability remains unverified')
    _source(c['routine_source'])
    require(Path(c['routine_source']['path']).suffix == '.cc', 'bound Rivet translation unit required')
    deps = c['source_dependencies']
    require(type(deps) is list and 1 <= len(deps) <= 32, 'bound native CLI/framework/percentile source dependencies required')
    for s in deps:
        _source(s)
    sources = [c['routine_source'], *deps]
    require(len({(s['path'], s['first_line'], s['last_line']) for s in sources}) == len(sources), 'duplicate source excerpt')
    # A lexical binding, not C++ branch/projection or native-consumption proof.
    text = c['routine_source']['text']
    require('declareCentrality' in text and '"' + c['calibration_analysis'] + '"' in text and '"' + c['histogram'] + '"' in text, 'declared source calibration call identity differs')


def _path(base, value):
    p = Path(value)
    return p if p.is_absolute() else Path(base).absolute() / p


def _source_read(source):
    raw, text = native_categorical.read_bytes(source['path'])
    require(hashlib.sha256(raw).hexdigest() == source['sha256'], 'source bytes changed')
    lines = text.splitlines()
    require(source['last_line'] <= len(lines) and '\n'.join(lines[source['first_line']-1:source['last_line']]) == source['text'], 'source excerpt changed')



def _calibration_grammar(block, name):
    """Admit a closed native-writer subset, never sanitize original bytes.

    ReaderYODA V3 reads annotations as YAML until literal ---, then trims and
    parses data directives. Quoted/aliased/multiline YAML is outside this subset.
    MaskedBins is a data directive, not an annotation-based masking operation.
    """
    require(block['type'] == 'ESTIMATE1D', 'calibration native Estimate1D required')
    lines = block['body'].splitlines()
    require(lines.count('---') == 1, 'one literal native annotation/data separator required')
    separator = lines.index('---')
    annotations = {}
    for line in lines[:separator]:
        require(not any(token in line for token in ('BEGIN ', 'END ')), 'native context marker inside annotations')
        if not line.strip() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z][A-Za-z0-9_]*): ?([A-Za-z0-9_./ +,()%\-]*)', line)
        require(match is not None, 'plain scalar native annotation grammar required; quoted/alias/multiline keys unsupported')
        key, value = match.groups()
        require(key not in annotations, 'duplicate normalized native annotation key')
        require(key != 'MaskedBins', 'masked calibration annotation unsupported')
        # Disallow schema-resolved YAML scalar keys rather than reinterpret them.
        require(key.lower() not in ('null', 'true', 'false', 'yes', 'no', 'on', 'off'), 'ambiguous YAML annotation key unsupported')
        annotations[key] = value
    require(annotations.get('Path') == name, 'native annotation Path identity differs')
    require('Type' not in annotations or annotations['Type'] == 'Estimate1D', 'native annotation Type identity differs')
    data = lines[separator+1:]
    header_seen = False
    for line in data:
        stripped = line.strip()
        require(not any(token in stripped for token in ('BEGIN ', 'END ')), 'native context marker inside data')
        require(not stripped.startswith('MaskedBins'), 'masked calibration native data directive unsupported')
        if not stripped:
            continue
        if stripped.startswith(('Edges(', 'ErrorLabels:', '#')):
            require(not line[0].isspace(), 'indented native directive outside closed writer grammar')
        if line.startswith('#'):
            if line.startswith('# value'):
                require(not header_seen, 'duplicate native numerical header')
                header_seen = True
            continue
        if line.startswith(('Edges(A1): ', 'ErrorLabels: ')):
            require(not header_seen, 'native geometry/error declaration after numerical header')
            continue
        require(header_seen, 'native data directive outside closed calibration grammar')
    require(header_seen, 'native numerical header required')
    # Geometry/error declarations belong to data, never YAML annotations.
    # The existing strict parser checks unique edges/labels and full row census.
    return native_estimate._estimate(block)

def inspect(task, base='.', *, admitted_source_files):
    """Rebind source and complete calibration file before command construction.

    The closed V1 calibration domain is finite nonnegative Estimate1D values.
    It excludes signed/nonmonotonic and masked calibrations, not all Rivet data.
    Native initialization and applicability require independently reviewed runs.
    """
    validate(task)
    if 'centrality_preload' not in task:
        return None
    c = task['centrality_preload']
    require(Path(c['routine_source']['path']).absolute() in {Path(p).absolute() for p in admitted_source_files}, 'calibration call source not admitted by the routine build/source graph')
    for source in [c['routine_source'], *c['source_dependencies']]:
        _source_read(source)
    path = _path(base, c['path'])
    require(',' not in str(path), 'native preload CLI cannot represent comma paths')
    raw, text = native_categorical.read_bytes(path)
    require(hashlib.sha256(raw).hexdigest() == c['sha256'], 'calibration bytes changed')
    objects = native_categorical.blocks(text)
    name = '/' + c['calibration_analysis'] + '/' + c['histogram'] + {'GEN': '', 'IMP': '_IMP', 'USR': '_USR'}[c['mode']]
    require(set(objects) == {name}, 'exact single calibration object required; no RAW/global counts or resumed analysis state')
    block = objects[name]
    original_raw, original_text = native_categorical.read_bytes(_path(base, c['origin']['path']))
    require(hashlib.sha256(original_raw).hexdigest() == c['origin']['sha256'], 'original calibration output bytes changed')
    original_objects = native_categorical.blocks(original_text)
    require(name in original_objects and original_objects[name]['block_sha256'] == block['block_sha256'], 'selected calibration block differs from its original full output')
    obj = _calibration_grammar(block, name)
    finite = [b for b in obj['bins'] if not b['flow']]
    require(all(b['value'] is not None and b['value'] >= 0 for b in finite), 'finite nonnegative central calibration values required')
    try:
        area = math.fsum(b['value'] * (b['high'][0] - b['low'][0]) for b in finite)
        total = math.fsum(b['value'] for b in finite)
    except OverflowError as exc:
        raise PreloadError('calibration arithmetic overflow') from exc
    require(math.isfinite(area) and area > 0 and math.isfinite(total) and total > 0, 'positive finite native area and percentile value sum required')
    return {'path': str(path.absolute()), 'sha256': c['sha256'], 'origin': c['origin'], 'origin_block_sha256': original_objects[name]['block_sha256'], 'mode': c['mode'], 'object_path': name, 'native_object': obj,
            'finite_area_check': area, 'percentile_finite_value_sum_check': total,
            'interpretation': 'Calibration-only native preload; values/errors/flows retained without transforms.',
            'source_contract': c, 'native_consumption_observed': False,
            'calibration_weight_applicability_verified': False, 'physics_validated': False}


def inputs(task, base='.', *, admitted_source_files):
    receipt = inspect(task, base, admitted_source_files=admitted_source_files)
    if receipt is None:
        return []
    c = task['centrality_preload']
    return list(dict.fromkeys([Path(receipt['path']), _path(base, c['origin']['path']), *[Path(s['path']) for s in [c['routine_source'], *c['source_dependencies']]], Path(__file__).resolve(), Path(native_categorical.__file__).resolve(), Path(native_estimate.__file__).resolve()]))


def arguments(task, base='.', *, admitted_source_files, exposure=None):
    receipt = inspect(task, base, admitted_source_files=admitted_source_files)
    if receipt is None:
        return [], None
    if receipt['mode'] == 'USR':
        require(exposure is not None and exposure['format'] == 'HepMC3', 'USR centrality requires supplied HepMC3')
    return ['--preload-file', receipt['path']], receipt


def prepare(source_path, *, expected_sha256, object_path, output_path):
    """Extract one literal calibration block, retaining full original output.

    No transforms, generator/beam qualification or conversion of REF into GEN.
    The output and full original must both be pinned in the supplied task.
    """
    require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256), 'original calibration SHA256 required')
    raw, text = native_categorical.read_bytes(Path(source_path).absolute())
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'original calibration output bytes changed')
    objects = native_categorical.blocks(text)
    require(object_path in objects and objects[object_path]['type'] == 'ESTIMATE1D', 'original selected native Estimate1D required')
    _calibration_grammar(objects[object_path], object_path)
    lines = text.splitlines(keepends=True)
    start = next(i for i,l in enumerate(lines) if l.rstrip('\r\n') == 'BEGIN YODA_ESTIMATE1D_V3 ' + object_path)
    end = next(i for i in range(start+1,len(lines)) if lines[i].rstrip('\r\n') == 'END YODA_ESTIMATE1D_V3')
    selected = ''.join(lines[start:end+1]).encode('utf-8')
    require(hashlib.sha256(selected).hexdigest() == objects[object_path]['block_sha256'], 'literal extraction identity differs')
    output = Path(output_path).absolute()
    require(not output.exists() and not output.is_symlink() and not any(p.is_symlink() for p in output.parents), 'fresh ordinary calibration destination required')
    with output.open('xb') as stream:
        stream.write(selected)
    return {'path': str(output), 'sha256': hashlib.sha256(selected).hexdigest(), 'origin': {'path': str(Path(source_path).absolute()), 'sha256': expected_sha256}, 'object_path': object_path, 'block_sha256': objects[object_path]['block_sha256'], 'native_consumption_observed': False, 'physics_validated': False}
