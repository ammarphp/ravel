"""Prospective figure-target overlays from pinned coordinates or calibrated images.

No digitization, rebinning, unit conversion or statistical qualification is inferred.
Every rendering input is copied from the one admitted bounded byte snapshot.
"""
from pathlib import Path
import hashlib
import io
import json
import math
import tempfile

from .display_labels import axis_label, display_label

_BASIS = ('quantity', 'model', 'production', 'width', 'branching_fraction',
          'energy', 'normalization', 'interference', 'response')
_MAX_FILE = 32 * 1024 * 1024
_MAX_TOTAL = 64 * 1024 * 1024


def _strict(raw):
    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ValueError('duplicate comparison JSON key: ' + key)
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + x)))


def _encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _identity(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _read_bytes(path, maximum):
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('comparison file exceeds its admitted byte bound')
    return raw


def file_pin(path):
    path = Path(path).absolute()
    before = path.stat()
    if not path.is_file() or before.st_size > _MAX_FILE:
        raise ValueError('comparison input is not a bounded regular file')
    raw = _read_bytes(path, _MAX_FILE)
    if _identity(before) != _identity(path.stat()) or len(raw) != before.st_size:
        raise ValueError('comparison file changed while read')
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


class _Inputs:
    def __init__(self, max_total=_MAX_TOTAL, max_files=128):
        self.rows = {}
        self.total = 0
        self.staged = []
        self.max_total = max_total
        self.max_files = max_files

    def read(self, pin):
        if not isinstance(pin, dict) or set(pin) != {'path', 'sha256', 'size'}:
            raise ValueError('exact path/sha256/size input pin required')
        path = Path(pin['path']).absolute()
        key = str(path)
        if key in self.rows:
            if self.rows[key][0] != pin:
                raise ValueError('conflicting comparison input pin')
            return self.rows[key][1]
        before = path.stat()
        if (not path.is_file() or type(pin['size']) is not int or not 0 <= pin['size'] <= _MAX_FILE
                or len(self.rows) >= self.max_files or self.total + pin['size'] > self.max_total):
            raise ValueError('comparison input exceeds bounded file population')
        raw = _read_bytes(path, pin['size'])
        if (_identity(before) != _identity(path.stat()) or len(raw) != pin['size']
                or hashlib.sha256(raw).hexdigest() != pin['sha256']):
            raise ValueError('comparison input pin changed: ' + key)
        self.rows[key] = (dict(pin), raw, _identity(before))
        self.total += len(raw)
        return raw

    def finish(self):
        for pin, raw, identity in self.rows.values():
            path = Path(pin['path'])
            if _identity(path.stat()) != identity or _read_bytes(path, len(raw)) != raw:
                raise ValueError('comparison input changed at delivery: ' + str(path))
        for path, raw in self.staged:
            if _read_bytes(path, len(raw)) != raw:
                raise ValueError('comparison staged input changed at delivery: ' + str(path))

    def stage(self, pin, directory):
        raw = self.read(pin)
        path = directory / (str(len(list(directory.iterdir()))) + '-' + Path(pin['path']).name)
        path.write_bytes(raw)
        if _read_bytes(path, len(raw)) != raw:
            raise ValueError('comparison staged input differs from admitted bytes')
        self.staged.append((path, raw))
        return str(path)


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite literal comparison coordinate required')
    return value


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _fields(value, required, optional=(), subject='comparison document'):
    if (not isinstance(value, dict) or not set(required) <= set(value)
            or not set(value) <= set(required) | set(optional)):
        raise ValueError(subject + ' has missing or unsupported fields; supplied content cannot be silently dropped')


def _axis(axis):
    _fields(axis, ('quantity', 'name', 'unit', 'scale'), ('display_label',), 'comparison axis')
    if not isinstance(axis, dict) or axis.get('scale') not in ('linear', 'log'):
        raise ValueError('explicit comparison axis scale required')
    if not isinstance(axis.get('quantity'), str) or not axis['quantity'].strip():
        raise ValueError('comparison axis quantity identity required')
    axis_label(axis)


def _basis(basis):
    if not isinstance(basis, dict) or set(basis) != set(_BASIS):
        raise ValueError('complete explicit comparison physics basis required')
    for key, value in basis.items():
        if not isinstance(value, str) or not value.strip() or value.strip().lower() in ('unknown', 'unspecified'):
            raise ValueError('unresolved comparison basis: ' + key)


def _coordinates(doc):
    _fields(doc, ('schema_version', 'kind', 'basis', 'axes', 'series'), subject='coordinate population')
    if doc.get('schema_version') != 1 or doc.get('kind') != 'plot-coordinate-series':
        raise ValueError('plot-coordinate-series schema 1 required')
    if set(doc.get('axes', {})) != {'x', 'y'}:
        raise ValueError('both coordinate axes required')
    for axis in doc['axes'].values():
        _axis(axis)
    _basis(doc.get('basis'))
    series = doc.get('series')
    if not isinstance(series, list) or not 1 <= len(series) <= 32:
        raise ValueError('finite complete comparison series population required')
    seen = set()
    delivered = 0
    for row in series:
        _fields(row, ('id', 'geometry', 'records'), ('label', 'uncertainty'), 'comparison series')
        if not isinstance(row.get('id'), str) or not row['id'].strip() or row['id'] in seen:
            raise ValueError('unique comparison series identities required')
        seen.add(row['id'])
        display_label(row['id'], row.get('label'))
        if row.get('geometry') not in ('markers', 'polyline', 'bins'):
            raise ValueError('explicit markers/polyline/bins geometry required')
        records = row.get('records')
        if not isinstance(records, list) or not 1 <= len(records) <= 10000:
            raise ValueError('complete ordered comparison records required')
        uncertainty = row.get('uncertainty')
        if 'uncertainty' in row:
            _fields(uncertainty, ('convention', 'meaning'), subject='supplied uncertainty')
            if uncertainty['convention'] not in ('absolute-y-offsets', 'unavailable') or not _text(uncertainty['meaning']):
                raise ValueError('explicit absolute-y-offsets/unavailable convention and supplied meaning required')
        absolute_errors = uncertainty is not None and uncertainty['convention'] == 'absolute-y-offsets'
        ids = set()
        previous_high = None
        for record in records:
            required = ('id', 'x', 'y', 'status')
            optional = ('reason',)
            if row['geometry'] == 'bins':
                required += ('low', 'high')
            if absolute_errors:
                optional += ('error_low', 'error_high')
            _fields(record, required, optional, 'comparison record')
            if not isinstance(record.get('id'), str) or not record['id'].strip() or record['id'] in ids:
                raise ValueError('unique comparison record identities required')
            ids.add(record['id'])
            x = _number(record.get('x'))
            if doc['axes']['x']['scale'] == 'log' and x <= 0:
                raise ValueError('nonpositive log-axis coordinate')
            if record.get('status') == 'unknown':
                if record.get('y') is not None or not _text(record.get('reason')):
                    raise ValueError('unknown comparison record needs null y and reason')
                if 'error_low' in record or 'error_high' in record:
                    raise ValueError('unknown records cannot claim numerical uncertainty')
            elif record.get('status') == 'delivered':
                if 'reason' in record:
                    raise ValueError('delivered coordinates cannot carry an unknown-record reason')
                delivered += 1
                y = _number(record.get('y'))
                if doc['axes']['y']['scale'] == 'log' and y <= 0:
                    raise ValueError('nonpositive log-axis coordinate')
                if absolute_errors:
                    lower, upper = _number(record.get('error_low')), _number(record.get('error_high'))
                    if lower < 0 or upper < 0:
                        raise ValueError('absolute uncertainty offsets must be nonnegative')
                    _number(y - lower); _number(y + upper)
                    if doc['axes']['y']['scale'] == 'log' and y - lower <= 0:
                        raise ValueError('supplied uncertainty crosses nonpositive log-axis support; no clipping is allowed')
            else:
                raise ValueError('comparison record requires literal delivered/unknown status')
            if row['geometry'] == 'bins':
                lo, hi = _number(record.get('low')), _number(record.get('high'))
                if not lo <= x <= hi or not lo < hi:
                    raise ValueError('comparison bin geometry differs from its coordinate')
                if doc['axes']['x']['scale'] == 'log' and lo <= 0:
                    raise ValueError('nonpositive log-axis bin edge')
                if previous_high is not None and lo < previous_high:
                    raise ValueError('bin population must retain an ordered non-overlapping interval support')
                previous_high = hi
    if not delivered:
        raise ValueError('no delivered coordinates to overlay; unknown population remains unresolved')
    if (doc['axes']['y']['unit'] == 'events/bin' or doc['basis']['normalization'] == 'events_per_bin'):
        if any(row['geometry'] != 'bins' for row in series):
            raise ValueError('integrated events-per-bin coordinates require explicit complete bin intervals')
    return doc


def _bin_support(doc):
    binned = [row for row in doc['series'] if row['geometry'] == 'bins']
    if not binned:
        return None
    if len(binned) != len(doc['series']):
        raise ValueError('mixed binned/unbinned comparison requires an explicit reviewed transformation')
    support = [[record['low'], record['high']] for record in binned[0]['records']]
    if any([[r['low'], r['high']] for r in row['records']] != support for row in binned[1:]):
        raise ValueError('all binned comparison series require the same complete interval support, including unknown bins')
    return support


def _comparable(agent, reference):
    # Display spelling is not a scientific difference. Identity, units and scale are.
    for key in ('x', 'y'):
        for field in ('quantity', 'unit', 'scale'):
            if agent['axes'][key][field] != reference['axes'][key][field]:
                raise ValueError('incomparable reference axis ' + key + ': ' + field)
    if agent['basis'] != reference['basis']:
        raise ValueError('incomparable reference physics/normalization basis')
    # Equal events/bin values have different meanings on different intervals.
    # Refuse rather than invent a rebinning/normalization-domain transformation.
    reference_support = (_bin_support(reference) if 'series' in reference
                         else reference.get('bin_support'))
    if _bin_support(agent) != reference_support:
        raise ValueError('incomparable complete bin support; a reviewed transformation is required')


def _declared_axes(target, axes):
    declared = target.get('axes') or {}
    if any(declared.get(key) != axes[key]['scale'] for key in ('x', 'y')):
        raise ValueError('comparison scales differ from declared figure-target axes; record the published scales first')


def _transform(value, scale):
    value = _number(value)
    if scale == 'log':
        if value <= 0:
            raise ValueError('nonpositive calibrated log coordinate')
        return math.log10(value)
    return value


def pixel_coordinate(value, axis, anchors):
    """Affine calibration in the declared linear or log10 coordinate space."""
    if not isinstance(anchors, list) or len(anchors) != 2:
        raise ValueError('exact two axis calibration anchors required')
    p0, p1 = (_number(a['pixel']) for a in anchors)
    v0, v1 = (_transform(a['value'], axis['scale']) for a in anchors)
    if p0 == p1 or v0 == v1:
        raise ValueError('degenerate image calibration')
    return p0 + (_transform(value, axis['scale']) - v0) * (p1 - p0) / (v1 - v0)


def _calibration(reference):
    calibration = reference['calibration']
    _fields(calibration, ('format', 'source_note', 'image_size', 'crop', 'x', 'y'),
            subject='image calibration')
    if calibration.get('format') not in ('png', 'jpeg') or not calibration.get('source_note'):
        raise ValueError('explicit image format and calibration-source note required')
    size = calibration.get('image_size')
    if (not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size)
            or size[0] * size[1] > 16_000_000):
        raise ValueError('bounded explicit original image dimensions required')
    crop = calibration.get('crop')
    if not isinstance(crop, list) or len(crop) != 4:
        raise ValueError('explicit plot-area crop corners required')
    left, top, right, bottom = [_number(v) for v in crop]
    if not (0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]):
        raise ValueError('reference crop outside original image')
    for key, endpoints in (('x', [left, right]), ('y', [top, bottom])):
        anchors = calibration.get(key)
        if not isinstance(anchors, list) or len(anchors) != 2 or [a.get('pixel') for a in anchors] != endpoints:
            raise ValueError('calibration anchors must be the declared plot-area crop corners')
        for anchor in anchors:
            _fields(anchor, ('pixel', 'value'), subject='image calibration anchor')
        pixel_coordinate(anchors[0]['value'], reference['axes'][key], anchors)
    return calibration


def _draw_series(ax, doc, prefix, mapping=None):
    for row in doc['series']:
        label = prefix + ': ' + display_label(row['id'], row.get('label'))
        color = None
        xs, ys = [], []
        for record in row['records']:
            x = record['x']
            y = record['y'] if record['status'] == 'delivered' else float('nan')
            if mapping:
                x = mapping('x', x)
                if record['status'] == 'delivered':
                    y = mapping('y', y)
            xs.append(x); ys.append(y)
        if row['geometry'] == 'bins':
            first = True
            for record, y in zip(row['records'], ys):
                if record['status'] != 'delivered':
                    continue
                lo, hi = record['low'], record['high']
                if mapping:
                    lo, hi = mapping('x', lo), mapping('x', hi)
                options = {} if first else {'color': color}
                artist = ax.plot([lo, hi], [y, y], label=label if first else None,
                                 **options)[0]
                if first:
                    color = artist.get_color()
                first = False
        else:
            # Actual vertices remain visible even for a singleton or disconnected
            # polyline; this does not create an extra coordinate or bridge unknowns.
            artist = ax.plot(xs, ys, marker='o',
                             linestyle='none' if row['geometry'] == 'markers' else '-', label=label)[0]
            color = artist.get_color()
        if (row.get('uncertainty') or {}).get('convention') == 'absolute-y-offsets':
            for record, x, y in zip(row['records'], xs, ys):
                if record['status'] != 'delivered':
                    continue
                endpoints = (record['y'] - record['error_low'], record['y'] + record['error_high'])
                if mapping:
                    endpoints = tuple(mapping('y', value) for value in endpoints)
                lower, upper = min(endpoints), max(endpoints)
                ax.errorbar([x], [y], yerr=[[y - lower], [upper - y]],
                            fmt='none', capsize=3, color=color, ecolor=color)


def _physical_ticks(axis, anchors):
    """Readable physical ticks, then placed through the unchanged calibration."""
    from matplotlib.ticker import LogLocator, MaxNLocator
    low, high = sorted(_number(anchor['value']) for anchor in anchors)
    def bounded(candidates):
        # Locator arithmetic may encode 0.1 as 0.09999999999999999. Round
        # presentation ticks to the displayed value before mapping; scientific
        # records and calibration anchors are never rounded or transformed here.
        values = {float(format(value, '.12g')) for value in candidates if math.isfinite(value)}
        return sorted(value for value in values if low <= value <= high)
    if axis['scale'] == 'log':
        values = bounded(LogLocator(base=10, subs=(1., 2., 5.), numticks=8).tick_values(low, high))
        if len(values) > 8 or len(values) < 2:
            values = bounded(LogLocator(base=10, subs=(1.,), numticks=8).tick_values(low, high))
    else:
        values = []
    if len(values) < 2:
        values = bounded(MaxNLocator(nbins=4, steps=[1, 2, 2.5, 5, 10]).tick_values(low, high))
    return values


def _render_coordinates(agent, reference, directory, image=None, calibration=None, source_note=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from . import mplhep_style as house
    house.apply_style('ATLAS', required=True)
    fig, ax = plt.subplots(figsize=(9, 6))
    try:
        if image is None:
            _draw_series(ax, reference, 'Official reference')
            _draw_series(ax, agent, 'Agent')
            ax.set_xscale(agent['axes']['x']['scale']); ax.set_yscale(agent['axes']['y']['scale'])
            # Matplotlib applies these local margins in the selected axis scale.
            # Margins affect only automatic numerical limits, never fixed source
            # limits, calibrated raster pixels or any scientific record.
            ax.margins(x=.06, y=.06)
            title = 'Agent and official numerical reference'
        else:
            from PIL import Image
            with Image.open(io.BytesIO(image)) as original:
                width, height = original.size
                if [width, height] != calibration['image_size'] or width * height > 16_000_000:
                    raise ValueError('reference image exceeds declared dimensions/pixel budget')
            pixels = plt.imread(io.BytesIO(image), format=calibration['format'])
            height, width = pixels.shape[:2]
            if [width, height] != calibration['image_size']:
                raise ValueError('reference image dimensions differ from calibration')
            left, top, right, bottom = calibration['crop']
            if not (0 <= left < right <= width and 0 <= top < bottom <= height):
                raise ValueError('reference crop outside original image')
            for key, endpoints in (('x', [left, right]), ('y', [top, bottom])):
                if [a['pixel'] for a in calibration[key]] != endpoints:
                    raise ValueError('calibration anchors must be the declared plot-area crop corners')
            ax.imshow(pixels, extent=(0, width, height, 0), interpolation='none')
            def mapping(key, value):
                pixel = pixel_coordinate(value, agent['axes'][key], calibration[key])
                bounds = (left, right) if key == 'x' else (top, bottom)
                if not bounds[0] <= pixel <= bounds[1]:
                    raise ValueError('agent coordinate outside calibrated reference crop')
                return pixel
            _draw_series(ax, agent, 'Agent', mapping)
            ax.set_xlim(left, right); ax.set_ylim(bottom, top)
            for key in ('x', 'y'):
                values = _physical_ticks(agent['axes'][key], calibration[key])
                ticks = [pixel_coordinate(value, agent['axes'][key], calibration[key]) for value in values]
                getattr(ax, 'set_' + key + 'ticks')(ticks, [format(value, '.12g') for value in values])
            title = 'Calibrated image overlay — visual comparison only'
        ax.set_xlabel(axis_label(agent['axes']['x'])); ax.set_ylabel(axis_label(agent['axes']['y']))
        fig.suptitle(title, fontsize=13)
        if source_note:
            fig.text(.02, .015, source_note, fontsize=8)
        meanings = []
        for doc in (agent, reference) if image is None else (agent,):
            for row in doc['series']:
                uncertainty = row.get('uncertainty')
                text = ('Absolute y offsets: ' + display_label(uncertainty['meaning'])
                        if uncertainty and uncertainty['convention'] == 'absolute-y-offsets'
                        else 'Uncertainty unavailable: ' + (display_label(uncertainty['meaning'])
                             if uncertainty else display_label(row['id'], row.get('label')) + ' (not supplied)'))
                if text not in meanings:
                    meanings.append(text)
        if meanings:
            import textwrap
            fig.text(.02, .055, textwrap.fill('; '.join(meanings), width=110), fontsize=8)
        ax.legend(loc='upper center', bbox_to_anchor=(.5, -.22), fontsize=9)
        fig.subplots_adjust(bottom=.32, top=.88)
        failures = house.lint_figure(fig, readable_labels=True)
        if failures:
            raise ValueError('comparison plot contract: ' + '; '.join(failures))
        for ext in ('png', 'pdf'):
            fig.savefig(directory / ('overlay.' + ext), dpi=220, bbox_inches='tight')
    finally:
        plt.close(fig)


def _existing_renderer(config, request, inputs, directory):
    """Keep renderer style changes within the admitted comparison call."""
    import matplotlib as mpl
    with mpl.rc_context():
        return _draw_existing_renderer(config, request, inputs, directory)


def _draw_existing_renderer(config, request, inputs, directory):
    """Fixed adapters to the original numerical renderers; no free command string."""
    from . import mplhep_style as house
    house.apply_style(config['experiment'], required=True)
    if config['experiment'] not in ('ATLAS', 'CMS'):
        raise ValueError('explicit ATLAS/CMS renderer experiment required')
    com, lumi = _number(config['com']), _number(config['lumi'])
    if com <= 0 or lumi <= 0:
        raise ValueError('positive declared energy and luminosity required')
    stage = directory / 'inputs'; stage.mkdir()
    def source(key):
        return inputs.stage(config[key], stage)
    out = str(directory / 'overlay')
    argv = ['--out', out, '--experiment', config['experiment'], '--com', str(com), '--lumi', str(lumi)]
    renderer = config['renderer']
    if renderer in ('scan_contour', 'mass_plane_overlay'):
        expected_x = 'm_parent'
        expected_y = 'dm' if config.get('plane') == 'dm' else 'm_lsp'
        if renderer == 'mass_plane_overlay' and (request['axes']['x']['quantity'] != expected_x or request['axes']['y']['quantity'] != expected_y
                or any(request['axes'][k]['unit'] != 'GeV' for k in ('x', 'y'))):
            raise ValueError('declared axes differ from existing mass-plane renderer semantics')
        if renderer == 'scan_contour':
            from . import scan_contour
            scan = _strict(inputs.read(config['scan']))
            spec = _strict(inputs.read(config['plot_spec']))
            scan_contour.validate_spec(scan, spec, request['axes'])
            # Output destinations are selected by the comparison operation; all
            # axis/layer choices still come from the pinned supplied contract.
            spec['outputs'] = [{**output, 'path': str(directory / Path(output['path']).name)}
                               for output in spec['outputs']]
            spec_path = stage / 'selected-plot.json'
            spec_path.write_text(json.dumps(spec, allow_nan=False))
            argv += ['--scan', source('scan'), '--plot-spec', str(spec_path)]
            scan_contour.main(argv)
        else:
            from . import mass_plane_overlay
            for contour in config['contours']:
                argv += ['--contour', contour['role'] + '=' + inputs.stage(contour['source'], stage)]
            for key in ('x', 'y'):
                argv += ['--log' + key if request['axes'][key]['scale'] == 'log' else '--lin' + key]
            if config['plane'] not in ('mass', 'dm'):
                raise ValueError('explicit mass/dm point plane required')
            if not isinstance(config['point'], list) or len(config['point']) != 2:
                raise ValueError('exact two-coordinate tested mass point required')
            argv += ['--point', ','.join(str(_number(x)) for x in config['point']),
                     '--analysis', config['analysis'], '--plane', config['plane'],
                     '--limit-artifact', source('limit_artifact'),
                     '--parent-label', display_label(request['axes']['x']['name'], request['axes']['x'].get('display_label')),
                     '--lsp-label', display_label(request['axes']['y']['name'], request['axes']['y'].get('display_label')),
                     '--model-label', display_label(config['model_label'])]
            mass_plane_overlay.main(argv)
    elif renderer == 'overlay_on_data':
        from . import overlay_on_data
        if (request['axes']['x']['scale'] != 'linear' or request['axes']['y']['scale'] != 'log'
                or request['axes']['y']['quantity'] != 'events_per_bin'
                or request['axes']['y']['unit'] != 'events/bin'
                or request['basis']['normalization'] != 'events_per_bin'):
            raise ValueError('existing distribution renderer requires linear x, log event-count y and events-per-bin normalization')
        argv[1] = out + '.png'
        argv += ['--signal', source('signal'), '--ref', source('ref'), '--routine', config['routine'],
                 '--table', config['table'], '--data-y', config['data_y'], '--bkg-y', config['bkg_y'],
                 '--xlabel', axis_label(request['axes']['x']), '--label', display_label(config['label']),
                 '--sig-scale', '1.0']
        if config.get('stack'):
            argv += ['--stack', source('stack')]
        overlay_on_data.main(argv)
    else:
        raise ValueError('unsupported existing numerical renderer')


def _existing_sources(request, inputs):
    """Validate and capture the fixed adapter's complete sources without drawing."""
    if isinstance(request.get('renderer'), dict) and request['renderer'].get('renderer') == 'scan_contour':
        from .scan_contour import PlotInputError
        if not request['renderer'].get('plot_spec'):
            raise PlotInputError('plot_spec')
    _basis(request.get('basis'))
    if set(request.get('axes', {})) != {'x', 'y'}:
        raise ValueError('both existing renderer axes required')
    for axis in request['axes'].values():
        _axis(axis)
    config = request['renderer']
    common = ('renderer', 'experiment', 'com', 'lumi')
    renderer = config.get('renderer') if isinstance(config, dict) else None
    if renderer == 'scan_contour':
        _fields(config, common + ('scan', 'plot_spec'), subject='declarative scan renderer')
        from .scan_contour import validate_spec, PlotInputError
        scan = _strict(inputs.read(config['scan']))
        spec = _strict(inputs.read(config['plot_spec']))
        validate_spec(scan, spec, request['axes'])
        if scan.get('model_basis') != request['basis']:
            raise PlotInputError('scan and comparison basis differ', 'comparison_mismatch')
        if spec['presentation'] != {key: config[key] for key in ('experiment', 'com', 'lumi')}:
            raise PlotInputError('renderer and plot presentation differ', 'comparison_mismatch')
    elif renderer == 'mass_plane_overlay':
        _fields(config, common + ('plane', 'point', 'analysis', 'limit_artifact',
                                 'model_label', 'contours'), subject='existing mass renderer')
        if config['plane'] not in ('mass', 'dm') or not _text(config['analysis']):
            raise ValueError('explicit mass/dm plane and analysis required')
        if not isinstance(config['point'], list) or len(config['point']) != 2:
            raise ValueError('exact two-coordinate tested mass point required')
        for value in config['point']:
            _number(value)
        display_label(config['model_label'])
        expected_x = 'm_parent'
        expected_y = 'dm' if config['plane'] == 'dm' else 'm_lsp'
    elif renderer == 'overlay_on_data':
        _fields(config, common + ('signal', 'ref', 'routine', 'table', 'data_y', 'bkg_y', 'label'),
                ('stack',), 'existing distribution renderer')
        if (request['axes']['x']['scale'] != 'linear' or request['axes']['y']['scale'] != 'log'
                or request['axes']['y']['quantity'] != 'events_per_bin'
                or request['axes']['y']['unit'] != 'events/bin'
                or request['basis']['normalization'] != 'events_per_bin'):
            raise ValueError('existing distribution renderer requires linear x, log event-count y and events-per-bin normalization')
        if not all(_text(config[key]) for key in ('routine', 'table', 'data_y', 'bkg_y')):
            raise ValueError('explicit distribution object identities required')
        display_label(config['label'])
        inputs.read(config['signal']); inputs.read(config['ref'])
        if config.get('stack'):
            inputs.read(config['stack'])
    else:
        raise ValueError('unsupported existing numerical renderer')
    if config['experiment'] not in ('ATLAS', 'CMS') or _number(config['com']) <= 0 or _number(config['lumi']) <= 0:
        raise ValueError('positive declared ATLAS/CMS energy and luminosity required')
    if renderer == 'mass_plane_overlay':
        if (request['axes']['x']['quantity'] != expected_x or request['axes']['y']['quantity'] != expected_y
                or any(request['axes'][key]['unit'] != 'GeV' for key in ('x', 'y'))):
            raise ValueError('declared axes differ from existing mass-plane renderer semantics')
        if not isinstance(config['contours'], list) or not config['contours']:
            raise ValueError('genuine reference contours required')
        for contour in config['contours']:
            _fields(contour, ('role', 'source'), subject='existing reference contour')
            if contour['role'] not in ('observed', 'expected', 'observed_aux', 'expected_aux'):
                raise ValueError('unsupported reference contour role')
            inputs.read(contour['source'])
        inputs.read(config['limit_artifact'])
    result = {'renderer': config, 'axes': request['axes'], 'basis': request['basis']}
    if renderer == 'scan_contour':
        result.update(scan=scan, plot_spec=spec)
        _overlay_names(result)
    return result


def _source_request(request_pin, target, inputs):
    """The same source-derived admission is used by production and final readout."""
    request = _strict(inputs.read(request_pin))
    common = ('schema_version', 'kind', 'target', 'counterpart', 'applicability')
    kind = request.get('kind') if isinstance(request, dict) else None
    if kind == 'numerical':
        _fields(request, common + ('agent', 'reference'), subject='numerical comparison request')
    elif kind == 'raster':
        _fields(request, common + ('agent', 'reference', 'numerical_reference_availability'),
                subject='raster comparison request')
    elif kind == 'existing-numerical':
        _fields(request, common + ('basis', 'axes', 'renderer'), subject='existing comparison request')
    else:
        raise ValueError('explicit numerical/raster comparison kind required')
    if request['schema_version'] != 1 or request['target'] != {
            'figure_id': target.get('figure_id'), 'paper': target.get('paper')}:
        raise ValueError('comparison request is not bound to this figure target')
    _fields(request['applicability'], ('state', 'reason', 'sources'), subject='comparison applicability')
    if request['applicability']['state'] != 'comparable' or not _text(request['applicability']['reason']):
        raise ValueError('comparable reference applicability and source explanation required')
    evidence = request['applicability']['sources']
    if not isinstance(evidence, list) or not evidence:
        raise ValueError('pinned comparability source evidence required')
    for pin in evidence:
        inputs.read(pin)
    inputs.read(request['counterpart'])
    if Path(request['counterpart']['path']).absolute() != Path(target['generated_counterpart']['path']).absolute():
        raise ValueError('comparison agent artifact differs from attached counterpart')
    if kind == 'existing-numerical':
        population = _existing_sources(request, inputs)
        _declared_axes(target, request['axes'])
        return request, population
    agent = _coordinates(_strict(inputs.read(request['agent'])))
    _declared_axes(target, agent['axes'])
    if kind == 'numerical':
        reference = _coordinates(_strict(inputs.read(request['reference'])))
        _comparable(agent, reference)
        return request, {'agent': agent, 'reference': reference}
    reference = request['reference']
    _fields(reference, ('image', 'axes', 'basis', 'calibration'), ('origin', 'bin_support'),
            'raster reference')
    _basis(reference['basis'])
    if set(reference['axes']) != {'x', 'y'}:
        raise ValueError('both raster reference axes required')
    for axis in reference['axes'].values():
        _axis(axis)
    _comparable(agent, reference)
    calibration = _calibration(reference)
    for row in agent['series']:
        for record in row['records']:
            coordinates = {'x': [record['x']], 'y': []}
            if row['geometry'] == 'bins':
                coordinates['x'] += [record['low'], record['high']]
            if record['status'] == 'delivered':
                coordinates['y'].append(record['y'])
                if (row.get('uncertainty') or {}).get('convention') == 'absolute-y-offsets':
                    coordinates['y'] += [record['y']-record['error_low'], record['y']+record['error_high']]
            for key, values in coordinates.items():
                bounds = (calibration['crop'][0], calibration['crop'][2]) if key == 'x' \
                    else (calibration['crop'][1], calibration['crop'][3])
                for value in values:
                    pixel = pixel_coordinate(value, agent['axes'][key], calibration[key])
                    if not bounds[0] <= pixel <= bounds[1]:
                        raise ValueError('agent coordinate/uncertainty outside calibrated reference crop')
    availability = request['numerical_reference_availability']
    _fields(availability, ('state', 'reason', 'sources'), subject='numerical reference availability')
    if availability['state'] != 'unavailable' or not _text(availability['reason']) or not availability['sources']:
        raise ValueError('raster comparison requires source-pinned unavailable numerical-reference disposition')
    if not isinstance(availability['sources'], list):
        raise ValueError('complete numerical-reference disposition sources required')
    for pin in availability['sources']:
        inputs.read(pin)
    origin = reference.get('origin', {'source': reference['image'], 'method': 'original-image'})
    _fields(origin, ('source', 'method'), subject='raster image origin')
    inputs.read(origin['source'])
    extracted = (target.get('extracted_image') or {}).get('path')
    if (not extracted or Path(extracted).absolute() != Path(origin['source']['path']).absolute()
            or not _text(origin['method'])):
        raise ValueError('calibrated image origin differs from the attached official figure')
    inputs.read(reference['image'])
    return request, {'agent': agent, 'reference_image': reference}


def _overlay_names(population):
    """Derive selected artifact names from the pinned renderer contract."""
    if (population.get('renderer') or {}).get('renderer') == 'scan_contour':
        names = [Path(output['path']).name for output in population['plot_spec']['outputs']]
        if len(set(names)) != len(names) or any(name in ('inputs', 'comparison-receipt.json') for name in names):
            raise ValueError('ambiguous or reserved comparison output name')
        return names
    return ['overlay.png', 'overlay.pdf']


def deliver(request_pin, target, output_parent):
    """Called by ordinary figure_target compose in addition to side-by-side."""
    inputs = _Inputs()
    request, population = _source_request(request_pin, target, inputs)
    intended_request, intended_population = _encoded(request), _encoded(population)
    counterpart = request['counterpart']
    directory = Path(tempfile.mkdtemp(prefix='reference-comparison-', dir=output_parent))
    inputs.stage(request_pin, directory)
    kind = request['kind']
    if kind == 'existing-numerical':
        _existing_renderer(request['renderer'], request, inputs, directory)
    else:
        inputs.stage(request['agent'], directory)
        agent = population['agent']
        paper = target.get('paper') or {}
        citation = '; '.join(('arXiv' if key == 'arxiv' else key) + ': ' + str(value)
                             for key, value in paper.items() if value)
        source_note = display_label((target.get('figure_id') or 'Declared synthesis') + '; ' + citation
                                    + '; energy: ' + agent['basis']['energy']
                                    + '; normalization: ' + agent['basis']['normalization'])
        if kind == 'numerical':
            inputs.stage(request['reference'], directory)
            reference = population['reference']
            _render_coordinates(agent, reference, directory, source_note=source_note)
        else:
            reference = population['reference_image']
            calibration = _calibration(reference)
            image = inputs.read(reference['image'])
            inputs.stage(reference['image'], directory)
            _render_coordinates(agent, reference, directory, image, calibration, source_note=source_note)
    if _encoded(request) != intended_request or _encoded(population) != intended_population:
        raise ValueError('renderer changed the originally admitted request/scientific population')
    files = sorted(p for p in directory.rglob('*') if p.is_file())
    overlay_names = _overlay_names(population)
    if not all((directory / name).is_file() for name in overlay_names):
        raise ValueError('comparison renderer did not deliver the selected overlay population')
    outputs = [file_pin(p) for p in files]
    receipt = {'schema_version': 1, 'kind': 'figure-reference-comparison', 'status': 'delivered',
               'comparison_kind': kind, 'request': request_pin, 'counterpart': counterpart,
               'target': request['target'], 'input_pins': [r[0] for r in inputs.rows.values()],
               'outputs': outputs, 'population': population,
               'visual_only': kind == 'raster', 'numerical_reference': kind != 'raster',
               'numerical_fidelity': None, 'physics_validated': False,
               'scope': 'Source-bound display comparison; scientific equivalence remains a review obligation'}
    raw = _encoded(receipt)
    receipt_path = directory / 'comparison-receipt.json'
    receipt_path.write_bytes(raw)
    inputs.finish()
    for pin in outputs:
        if file_pin(pin['path']) != pin:
            raise ValueError('comparison artifact changed at delivery')
    if _read_bytes(receipt_path, len(raw)) != raw:
        raise ValueError('comparison receipt changed at delivery')
    if sorted(str(p) for p in directory.rglob('*') if p.is_file()) != sorted(
            [pin['path'] for pin in outputs] + [str(receipt_path)]):
        raise ValueError('comparison output population changed at delivery')
    return {'schema_version': 1, 'deliverable': 'reference-comparison', 'state': 'delivered',
            'receipt': file_pin(receipt_path),
            'overlays': [pin for pin in outputs if Path(pin['path']).name in overlay_names]}


def verify_target_comparison(target):
    """Pure file-bound gate; absence preserves historical target semantics."""
    contract = target.get('reference_comparison')
    if contract is None:
        return []
    try:
        if contract.get('schema_version') != 1:
            raise ValueError('unsupported prospective comparison contract')
        if contract.get('deliverable') == 'non-comparison':
            if contract.get('state') not in ('no-reference', 'incomparable-reference') or not _text(contract.get('reason')):
                raise ValueError('non-comparison delivery requires an explicit reference disposition and reason')
            if contract.get('receipt'):
                raise ValueError('non-comparison disposition cannot claim an overlay')
            return []
        if contract.get('deliverable') != 'reference-comparison' or contract.get('state') != 'delivered':
            raise ValueError('prospective reference-comparison overlay remains undelivered')
        # Readout includes original inputs and retained copies, not a new render admission.
        inputs = _Inputs(max_total=192 * 1024 * 1024, max_files=384)
        receipt = _strict(inputs.read(contract['receipt']))
        if receipt.get('kind') != 'figure-reference-comparison' or receipt.get('status') != 'delivered':
            raise ValueError('invalid comparison receipt')
        if receipt.get('target') != {'figure_id': target.get('figure_id'), 'paper': target.get('paper')}:
            raise ValueError('overlay receipt belongs to a different figure target')
        if Path(receipt['counterpart']['path']).absolute() != Path(target['generated_counterpart']['path']).absolute():
            raise ValueError('overlay counterpart differs from attached generated figure')
        if target.get('comparison_request') and target['comparison_request'] != receipt['request']:
            raise ValueError('overlay request differs from the attached comparison request')
        kind = receipt.get('comparison_kind')
        if (kind not in ('numerical', 'raster', 'existing-numerical') or receipt.get('physics_validated') is not False
                or receipt.get('numerical_fidelity') is not None
                or receipt.get('visual_only') is not (kind == 'raster')
                or receipt.get('numerical_reference') is not (kind != 'raster')):
            raise ValueError('comparison scope/visual-only semantics changed')
        request, population = _source_request(receipt['request'], target, inputs)
        if request['kind'] != kind or request['counterpart'] != receipt['counterpart'] or request['target'] != receipt['target']:
            raise ValueError('comparison kind/counterpart/target differs from the pinned source request')
        if _encoded(receipt.get('population')) != _encoded(population):
            raise ValueError('displayed comparison population differs from the pinned scientific source documents')
        receipt_key = str(Path(contract['receipt']['path']).absolute())
        source_pins = [row[0] for key, row in inputs.rows.items() if key != receipt_key]
        if receipt.get('input_pins') != source_pins:
            raise ValueError('comparison source inventory differs from the complete admitted request')
        for pin in receipt['outputs']:
            inputs.read(pin)
        names = {Path(pin['path']).name for pin in receipt['outputs']}
        overlay_names = _overlay_names(population)
        if not set(overlay_names) <= names:
            raise ValueError('selected overlay population incomplete')
        if contract.get('overlays') != [pin for pin in receipt['outputs']
                                      if Path(pin['path']).name in overlay_names]:
            raise ValueError('target overlay paths differ from the committed receipt')
        inputs.finish()
        return []
    except (ValueError, OSError, KeyError, TypeError) as error:
        return ['reference comparison: ' + str(error)]
