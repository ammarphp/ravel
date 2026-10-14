"""Digitise curves, markers and bands from published figures.

Vector PDF route
    The page content stream is walked with full graphics-state tracking: the
    current transformation matrix (``cm``, ``q``/``Q``), nested Form XObjects
    (figures embedded in a paper are usually forms), stroke and fill colours,
    line width and dash pattern. Every stroked path, filled path, marker (small
    form or repeated small closed path) and text string is collected in page
    coordinates (points). Axis calibration comes from declared anchors,
    declared tick values matched to the detected major tick marks, or from the
    numeric tick labels found on the page (mathtext powers of ten included),
    each label snapped to its tick mark. Linear and logarithmic axes are
    supported. A series is selected by colour, line width, dash pattern, or by
    its legend entry; the legend handle itself is never part of the series.

Raster route
    A PNG/JPEG figure is calibrated from declared pixel anchors. A series is
    the set of pixels within a colour tolerance of the declared colour: a
    curve is traced column by column, markers are connected components, and a
    band is the per-column lower and upper edge.

Output
    ``digitized.json`` holds the series in data coordinates with per-point
    digitisation uncertainty, the calibration (anchors, fit coefficients,
    residuals) and the source file's sha256 and page. ``review.png`` draws the
    extracted points on top of the rendered source so a person or agent can
    check the extraction by eye. No physics value is inferred; a digitised
    series is approximate reference evidence and is labelled as such.

Specification (JSON, paths relative to the specification file)::

    {"schema_version": 1,
     "source": {"path": "figure.pdf", "page": 1},
     "region": [x0, y0, x1, y1],          # optional page box (points) holding the figure
     "frame":  [x0, y0, x1, y1],          # optional plot frame; detected when absent
     "axes": {"x": {"label": "Mediator mass", "unit": "GeV", "scale": "linear",
                    "calibration": {"method": "tick_labels"}},
              "y": {"label": "Cross section", "unit": "pb", "scale": "log",
                    "calibration": {"method": "tick_values", "values": [0.01, 0.1, 1, 10]}}},
     "series": [{"name": "observed", "label": "Observed limit", "kind": "line",
                 "select": {"legend": "Observed"}},
                {"name": "band", "label": "Expected limit, 68% band", "kind": "band",
                 "select": {"color": "#00ff00", "tolerance": 0.05}}]}

Calibration methods: ``tick_labels`` (vector only), ``tick_values`` (vector
only, values listed from left to right or bottom to top) and ``anchors``
(``[{"position": p, "value": v}, ...]`` in page points for a PDF, or pixel
coordinates measured from the top-left image corner for a raster image, where
the centre of the first pixel is 0.5).
"""
from pathlib import Path
import io
import math
import re

import numpy as np

from .figure_io import (axis_title, code_identity, finite_list, hex_rgb, load_spec, natural_label,
                        new_output_dir, read_bytes, resolve, rgb_hex, scale_of, sha256_bytes,
                        write_new_bytes, write_new_json)

RASTER_SUFFIXES = ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff')
MARKER_MAX_SIZE = 16.0          # points; a closed path smaller than this can be a marker
FORM_MARKER_MAX_SIZE = 24.0     # points; a Form XObject smaller than this is a marker
BEZIER_SAMPLES = 8
VECTOR_POSITION_FLOOR = 0.01    # points: positional precision floor for vector extraction
RASTER_POSITION_FLOOR = 0.5     # pixels
_NUMBER = re.compile(r'^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$')
_MANTISSA_TIMES_TEN = re.compile(r'^([+-]?(?:\d+\.?\d*|\.\d+))\s*[×x·]\s*10$')


def sha256_file(path):
    return sha256_bytes(read_bytes(path))


# ===================================================================== geometry
def _matrix(values):
    a, b, c, d, e, f = (float(v) for v in values)
    return np.array([[a, b, 0.0], [c, d, 0.0], [e, f, 1.0]])


def _apply(matrix, x, y):
    p = np.array([x, y, 1.0]) @ matrix
    return float(p[0]), float(p[1])


def _scale(matrix):
    return math.sqrt(abs(np.linalg.det(matrix[:2, :2]))) or 1.0


def _bbox(points):
    pts = np.asarray(points, float)
    return (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max()))


def _union(boxes):
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _inside(box, outer, tol=0.0):
    return (box[0] >= outer[0] - tol and box[1] >= outer[1] - tol
            and box[2] <= outer[2] + tol and box[3] <= outer[3] + tol)


def _overlaps(box, outer, tol=0.0):
    return not (box[2] < outer[0] - tol or box[0] > outer[2] + tol or box[3] < outer[1] - tol or box[1] > outer[3] + tol)


def _bezier(p0, p1, p2, p3):
    out = []
    for i in range(1, BEZIER_SAMPLES + 1):
        t = i / BEZIER_SAMPLES
        u = 1 - t
        out.append(tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t ** 3 * d
                         for a, b, c, d in zip(p0, p1, p2, p3)))
    return out


# ===================================================================== PDF walker
class _GState:
    __slots__ = ('ctm', 'stroke', 'fill', 'width', 'dash', 'font', 'size', 'tc', 'tw', 'th', 'tl', 'rise')

    def __init__(self):
        self.ctm = np.eye(3)
        self.stroke = (0.0, 0.0, 0.0)
        self.fill = (0.0, 0.0, 0.0)
        self.width = 1.0
        self.dash = ()
        self.font = None
        self.size = 0.0
        self.tc = self.tw = self.tl = self.rise = 0.0
        self.th = 1.0

    def copy(self):
        other = _GState.__new__(_GState)
        for name in self.__slots__:
            setattr(other, name, getattr(self, name))
        other.ctm = self.ctm.copy()
        return other


def _colour(operands):
    values = []
    for v in operands:
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            return None                  # pattern or named colour: not a plain colour
    if len(values) == 1:
        return (values[0],) * 3
    if len(values) == 3:
        return tuple(values)
    if len(values) == 4:
        c, m, y, k = values
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _font_decoder(font_dict):
    try:
        from pypdf.generic._font import Font
        return Font.from_font_resource(font_dict)
    except Exception:
        return None


def _decode(font, raw):
    """Decode one string operand into (text, per-character widths in 1/1000 em)."""
    data = getattr(raw, 'original_bytes', None)
    data = bytes(data) if data is not None else (raw.encode('latin-1', 'replace') if isinstance(raw, str) else bytes(raw))
    if font is None:
        text = data.decode('latin-1')
        return text, [500.0] * len(text)
    if isinstance(font.encoding, str):
        try:
            text = data.decode(font.encoding, 'surrogatepass')
        except (UnicodeDecodeError, LookupError):
            text = data.decode('latin-1')
        source = text
    else:
        text = ''.join(font.encoding.get(b, chr(b)) for b in data)
        source = ''.join(chr(b) for b in data)
    widths = [float(font.get_text_width(ch)) for ch in (source if len(source) == len(text) else text)]
    shown = []
    for ch in text:
        mapped = font.character_map.get(ch, ch)
        shown.append(mapped if isinstance(mapped, str) and len(mapped) == 1 else ch)
    return ''.join(shown), widths


class PageContent:
    """Everything drawn on one PDF page, in page coordinates (points)."""

    def __init__(self, box):
        self.box = box                  # (x0, y0, x1, y1) of the page media box
        self.strokes = []               # dict(points=[N x 2 arrays], color, width, dash, closed, bbox)
        self.fills = []                 # dict(points=[...], color, bbox)
        self.markers = []               # dict(center, color, size, shape, bbox)
        self.texts = []                 # dict(text, x, y, size, width)


def parse_pdf_page(path, page=1):
    from pypdf import PdfReader
    from pypdf.generic import ContentStream
    reader = PdfReader(io.BytesIO(read_bytes(path)))
    if not 1 <= page <= len(reader.pages):
        raise ValueError(f'page {page} does not exist; the document has {len(reader.pages)} pages')
    pg = reader.pages[page - 1]
    if int(pg.get('/Rotate', 0) or 0) % 360:
        raise ValueError('rotated pages are not supported; rotate the page to upright first')
    mb = pg.mediabox
    content = PageContent((float(mb.left), float(mb.bottom), float(mb.right), float(mb.top)))
    stream = pg.get_contents()
    if stream is None:
        return content
    _walk(reader, stream.operations, pg.get('/Resources') or {}, _GState(), content, depth=0)
    return content


def _resources_entry(resources, kind, name):
    try:
        table = resources.get(kind)
        table = table.get_object() if table is not None else None
        return table[name].get_object() if table is not None and name in table else None
    except Exception:
        return None


def _walk(reader, operations, resources, state, content, depth):
    from pypdf.generic import ContentStream
    if depth > 12:
        raise ValueError('Form XObject nesting exceeds 12 levels')
    resources = resources.get_object() if hasattr(resources, 'get_object') else resources
    stack = []
    subpaths, current, closed = [], [], []
    fonts = {}
    tm = tlm = np.eye(3)

    def flush_current():
        nonlocal current
        if current:
            subpaths.append(current)
            closed.append(False)
        current = []

    def paint(stroke, fill, close=False):
        nonlocal subpaths, current, closed
        if close and current:
            current.append(current[0])
            flush_current()
            closed[-1] = True
        flush_current()
        paths = [np.array(p, float) for p in subpaths if len(p) >= 1]
        if paths:
            box = _union(_bbox(p) for p in paths)
            if stroke:
                content.strokes.append({'points': paths, 'color': state.stroke, 'width': state.width * _scale(state.ctm),
                                        'dash': tuple(round(d * _scale(state.ctm), 2) for d in state.dash),
                                        'closed': list(closed), 'bbox': box})
            if fill and state.fill is not None:
                areas = [p for p in paths if len(p) >= 3]
                if areas:
                    content.fills.append({'points': areas, 'color': state.fill, 'bbox': _union(_bbox(p) for p in areas)})
        subpaths, current, closed = [], [], []

    for operands, operator in operations:
        op = operator.decode('latin-1') if isinstance(operator, bytes) else str(operator)
        try:
            if op == 'q':
                stack.append(state.copy())
            elif op == 'Q':
                if stack:
                    state = stack.pop()
            elif op == 'cm':
                state.ctm = _matrix(operands) @ state.ctm
            elif op == 'w':
                state.width = float(operands[0])
            elif op == 'd':
                state.dash = tuple(float(v) for v in operands[0])
            elif op in ('RG', 'G', 'K', 'SC', 'SCN'):
                state.stroke = _colour(operands)
            elif op in ('rg', 'g', 'k', 'sc', 'scn'):
                state.fill = _colour(operands)
            elif op == 'CS':
                state.stroke = (0.0, 0.0, 0.0)
            elif op == 'cs':
                state.fill = (0.0, 0.0, 0.0)
            elif op == 'm':
                flush_current()
                current = [_apply(state.ctm, operands[0], operands[1])]
            elif op == 'l':
                current.append(_apply(state.ctm, operands[0], operands[1]))
            elif op in ('c', 'v', 'y') and current:
                vals = [float(v) for v in operands]
                p0 = current[-1]
                if op == 'c':
                    p1, p2, p3 = (_apply(state.ctm, vals[0], vals[1]), _apply(state.ctm, vals[2], vals[3]),
                                  _apply(state.ctm, vals[4], vals[5]))
                elif op == 'v':
                    p1, p2, p3 = p0, _apply(state.ctm, vals[0], vals[1]), _apply(state.ctm, vals[2], vals[3])
                else:
                    p1 = _apply(state.ctm, vals[0], vals[1])
                    p3 = _apply(state.ctm, vals[2], vals[3])
                    p2 = p3
                current.extend(_bezier(p0, p1, p2, p3))
            elif op == 'h':
                if current:
                    current.append(current[0])
                    subpaths.append(current)
                    closed.append(True)
                    current = []
            elif op == 're':
                flush_current()
                x, y, w, h = (float(v) for v in operands)
                corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
                subpaths.append([_apply(state.ctm, *c) for c in corners])
                closed.append(True)
            elif op == 'S':
                paint(True, False)
            elif op == 's':
                paint(True, False, close=True)
            elif op in ('f', 'F', 'f*'):
                paint(False, True, close=True)
            elif op in ('B', 'B*'):
                paint(True, True)
            elif op in ('b', 'b*'):
                paint(True, True, close=True)
            elif op == 'n':
                subpaths, current, closed = [], [], []
            elif op == 'Do':
                _do(reader, operands[0], resources, state, content, depth)
            elif op == 'BT':
                tm = tlm = np.eye(3)
            elif op == 'Tf':
                name = operands[0]
                if name not in fonts:
                    font_dict = _resources_entry(resources, '/Font', name)
                    fonts[name] = _font_decoder(font_dict) if font_dict is not None else None
                state.font = fonts[name]
                state.size = float(operands[1])
            elif op == 'Tc':
                state.tc = float(operands[0])
            elif op == 'Tw':
                state.tw = float(operands[0])
            elif op == 'Tz':
                state.th = float(operands[0]) / 100.0
            elif op == 'TL':
                state.tl = float(operands[0])
            elif op == 'Ts':
                state.rise = float(operands[0])
            elif op in ('Td', 'TD'):
                tx, ty = float(operands[0]), float(operands[1])
                if op == 'TD':
                    state.tl = -ty
                tlm = _matrix([1, 0, 0, 1, tx, ty]) @ tlm
                tm = tlm.copy()
            elif op == 'Tm':
                tlm = _matrix(operands)
                tm = tlm.copy()
            elif op == 'T*':
                tlm = _matrix([1, 0, 0, 1, 0, -state.tl]) @ tlm
                tm = tlm.copy()
            elif op in ('Tj', "'", '"', 'TJ'):
                if op in ("'", '"'):
                    if op == '"':
                        state.tw, state.tc = float(operands[0]), float(operands[1])
                    tlm = _matrix([1, 0, 0, 1, 0, -state.tl]) @ tlm
                    tm = tlm.copy()
                items = operands[0] if op == 'TJ' else [operands[-1]]
                tm = _show_text(items, state, tm, content)
        except (IndexError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and 'nesting' in str(exc):
                raise
            continue          # a malformed operator is skipped, never guessed


def _show_text(items, state, tm, content):
    pieces = []
    for item in items:
        if isinstance(item, (int, float)) or type(item).__name__ in ('FloatObject', 'NumberObject'):
            tm = _matrix([1, 0, 0, 1, -float(item) / 1000.0 * state.size * state.th, 0]) @ tm
            pieces.append(None)
            continue
        text, widths = _decode(state.font, item)
        for ch, w in zip(text, widths):
            advance = (w / 1000.0 * state.size + state.tc + (state.tw if ch == ' ' else 0.0)) * state.th
            device = tm @ state.ctm
            render = _matrix([state.size * state.th, 0, 0, state.size, 0, state.rise]) @ device
            end = _matrix([1, 0, 0, 1, advance, 0]) @ device
            width = math.hypot(end[2, 0] - device[2, 0], end[2, 1] - device[2, 1])
            pieces.append((ch, render[2, 0], render[2, 1], width, state.size * _scale(device)))
            tm = _matrix([1, 0, 0, 1, advance, 0]) @ tm
    # Group consecutive characters into words (a TJ kerning gap keeps the word).
    word = []
    for piece in pieces + [None]:
        if piece is not None and piece[0] != ' ':
            word.append(piece)
            continue
        if word:
            text = ''.join(p[0] for p in word)
            x0, y0 = word[0][1], word[0][2]
            x1 = word[-1][1] + word[-1][3]
            content.texts.append({'text': text, 'x': x0, 'y': y0, 'width': max(x1 - x0, 0.0),
                                  'size': word[0][4]})
        word = []
    return tm


def _do(reader, name, resources, state, content, depth):
    from pypdf.generic import ContentStream
    xobj = _resources_entry(resources, '/XObject', name)
    if xobj is None or xobj.get('/Subtype') != '/Form':
        return
    matrix = _matrix(xobj.get('/Matrix', [1, 0, 0, 1, 0, 0])) @ state.ctm
    bbox = [float(v) for v in xobj.get('/BBox', [0, 0, 0, 0])]
    corners = [_apply(matrix, bbox[0], bbox[1]), _apply(matrix, bbox[2], bbox[3]),
               _apply(matrix, bbox[0], bbox[3]), _apply(matrix, bbox[2], bbox[1])]
    device = _bbox(corners)
    inner = state.copy()
    inner.ctm = matrix
    form_resources = xobj.get('/Resources') or resources
    operations = ContentStream(xobj, reader).operations
    if max(device[2] - device[0], device[3] - device[1]) <= FORM_MARKER_MAX_SIZE:
        probe = PageContent(content.box)
        _walk(reader, operations, form_resources, inner, probe, depth + 1)
        drawn = [*probe.fills, *probe.strokes]
        if not drawn:
            return
        box = _union(d['bbox'] for d in drawn)
        cx, cy = _apply(matrix, 0, 0)
        if not (box[0] - 0.5 <= cx <= box[2] + 0.5 and box[1] - 0.5 <= cy <= box[3] + 0.5):
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        color = probe.fills[0]['color'] if probe.fills else probe.strokes[0]['color']
        content.markers.append({'center': (cx, cy), 'color': color, 'size': max(box[2] - box[0], box[3] - box[1]),
                                'shape': str(name), 'bbox': box})
        return
    _walk(reader, operations, form_resources, inner, content, depth + 1)


# ===================================================================== page analysis
def _restrict(content, region):
    if region is None:
        return content
    out = PageContent(content.box)
    out.strokes = [s for s in content.strokes if _overlaps(s['bbox'], region)]
    out.fills = [f for f in content.fills if _overlaps(f['bbox'], region)]
    out.markers = [m for m in content.markers if _inside(m['bbox'], region, 1.0)]
    out.texts = [t for t in content.texts if region[0] <= t['x'] <= region[2] and region[1] <= t['y'] <= region[3]]
    return out


def _is_rect(points):
    pts = np.asarray(points)
    if len(pts) not in (4, 5):
        return False
    xs, ys = np.unique(np.round(pts[:, 0], 2)), np.unique(np.round(pts[:, 1], 2))
    return len(xs) == 2 and len(ys) == 2


def detect_frame(content):
    """The plot frame: the axis-aligned rectangle (not the page) carrying the most tick marks."""
    page = content.box
    page_area = (page[2] - page[0]) * (page[3] - page[1])
    candidates = set()
    for prim in [*content.fills, *content.strokes]:
        for pts in prim['points']:
            if not _is_rect(pts):
                continue
            box = tuple(round(v, 3) for v in _bbox(pts))
            area = (box[2] - box[0]) * (box[3] - box[1])
            if 0.02 * page_area <= area <= 0.97 * page_area:
                candidates.add(box)
    best, best_key = None, None
    for box in candidates:
        ticks = detect_ticks(content, box)
        count = sum(len(ticks[k][0]) + len(ticks[k][1]) for k in ('x', 'y'))
        key = (count, (box[2] - box[0]) * (box[3] - box[1]))
        if best_key is None or key > best_key:
            best, best_key = box, key
    if best is None:
        # Fall back to long axis-aligned strokes (separately drawn spines).
        long = []
        for prim in content.strokes:
            for pts in prim['points']:
                if len(pts) != 2:
                    continue
                (x0, y0), (x1, y1) = pts
                if abs(x0 - x1) < 0.1 and abs(y1 - y0) > 0.2 * (page[3] - page[1]):
                    long.append(_bbox(pts))
                elif abs(y0 - y1) < 0.1 and abs(x1 - x0) > 0.2 * (page[2] - page[0]):
                    long.append(_bbox(pts))
        if long:
            box = _union(long)
            if box[2] - box[0] > 1 and box[3] - box[1] > 1:
                best = box
    if best is None:
        raise ValueError('no plot frame found; declare "frame" as [x0, y0, x1, y1] in page points')
    return best


def _segments(content):
    for prim in content.strokes:
        for pts in prim['points']:
            if len(pts) == 2 or (len(pts) == 3 and np.allclose(pts[0], pts[2])):
                yield prim, pts[0], pts[1]


def detect_ticks(content, frame):
    """Tick marks on the frame edges, in page coordinates, split into major and minor."""
    span_x, span_y = frame[2] - frame[0], frame[3] - frame[1]
    found = {'x': [], 'y': []}
    for which, edge_first, edge_second in (('x', frame[1], frame[3]), ('y', frame[0], frame[2])):
        for edge in (edge_first, edge_second):
            ticks = []
            for prim, a, b in _segments(content):
                if which == 'x':
                    if abs(a[0] - b[0]) > 0.05:
                        continue
                    length = abs(a[1] - b[1])
                    near = min(abs(a[1] - edge), abs(b[1] - edge))
                    pos, limit, lo, hi = a[0], 0.06 * span_y + 2, frame[0] - 0.5, frame[2] + 0.5
                else:
                    if abs(a[1] - b[1]) > 0.05:
                        continue
                    length = abs(a[0] - b[0])
                    near = min(abs(a[0] - edge), abs(b[0] - edge))
                    pos, limit, lo, hi = a[1], 0.06 * span_x + 2, frame[1] - 0.5, frame[3] + 0.5
                if 0.5 <= length <= limit and near <= 1.0 and lo <= pos <= hi:
                    ticks.append((round(float(pos), 3), float(length)))
            if ticks:
                merged = {}
                for pos, length in ticks:
                    merged[pos] = max(length, merged.get(pos, 0.0))
                longest = max(merged.values())
                major = sorted(p for p, l in merged.items() if l >= 0.75 * longest)
                minor = sorted(p for p, l in merged.items() if l < 0.75 * longest)
                found[which] = (major, minor)
                break
        if not found[which]:
            found[which] = ([], [])
    return found


def _parse_number(text):
    text = text.strip().replace('−', '-').replace('–', '-').replace('$', '')
    if _NUMBER.match(text):
        return float(text)
    return None


def merge_runs(texts):
    """Join glyphs drawn one by one (mathtext, kerned strings) into words on the same baseline."""
    rows = sorted(texts, key=lambda t: (round(t['y'], 1), round(t['size'], 1), t['x']))
    out = []
    for t in rows:
        last = out[-1] if out else None
        if (last is not None and abs(last['size'] - t['size']) <= 0.05 * t['size']
                and abs(last['y'] - t['y']) <= 0.05 * t['size']
                and -0.05 * t['size'] <= t['x'] - (last['x'] + last['width']) <= 0.12 * t['size']):
            last['text'] += t['text']
            last['width'] = t['x'] + t['width'] - last['x']
        else:
            out.append(dict(t))
    return out


def numeric_labels(content):
    """Numeric text items, merging mathtext powers of ten (10 with a raised exponent)."""
    texts = sorted(merge_runs(content.texts), key=lambda t: (t['y'], t['x']))
    used = set()
    out = []
    for i, base in enumerate(texts):
        if i in used:
            continue
        raw = base['text'].strip().replace('−', '-')
        mantissa = None
        if raw == '10':
            mantissa = 1.0
        else:
            match = _MANTISSA_TIMES_TEN.match(raw)
            if match:
                mantissa = float(match.group(1))
        exponent = None
        if mantissa is not None:
            end = base['x'] + base['width']
            for j, sup in enumerate(texts):
                if j == i or j in used:
                    continue
                value = _parse_number(sup['text'])
                if value is None or value != int(value) or sup['size'] > 0.92 * base['size']:
                    continue
                if (-0.3 * base['size'] <= sup['x'] - end <= 0.6 * base['size']
                        and 0.15 * base['size'] <= sup['y'] - base['y'] <= 0.95 * base['size']):
                    exponent = (j, int(value), sup)
                    break
        if exponent is not None:
            j, power, sup = exponent
            used.update((i, j))
            out.append({'text': f'{raw}^{power}', 'value': mantissa * 10.0 ** power, 'x': base['x'], 'y': base['y'],
                        'width': sup['x'] + sup['width'] - base['x'], 'size': base['size']})
            continue
        value = _parse_number(raw)
        if value is not None:
            used.add(i)
            out.append({'text': raw, 'value': value, 'x': base['x'], 'y': base['y'],
                        'width': base['width'], 'size': base['size']})
    return out


def _axis_labels(labels, frame, which):
    if which == 'x':
        rows = [l for l in labels if l['y'] < frame[1] and frame[1] - l['y'] <= 4 * l['size'] + 4
                and frame[0] - l['size'] <= l['x'] + l['width'] / 2 <= frame[2] + l['size']]
        if not rows:
            return []
        top = max(l['y'] for l in rows)
        return [l for l in rows if abs(l['y'] - top) <= 0.3 * l['size']]
    cols = [l for l in labels if l['x'] + l['width'] <= frame[0] + 0.5 and frame[0] - (l['x'] + l['width']) <= 3 * l['size'] + 4
            and frame[1] - l['size'] <= l['y'] + 0.35 * l['size'] <= frame[3] + l['size']]
    if not cols:
        return []
    right = max(l['x'] + l['width'] for l in cols)
    return [l for l in cols if abs(l['x'] + l['width'] - right) <= 1.5 * l['size']]


# ===================================================================== calibration
class Calibration:
    """value = f^-1(a + b * position), f = identity (linear) or log10 (log)."""

    def __init__(self, anchors, scale, method, floor):
        if len(anchors) < 2:
            raise ValueError('axis calibration needs at least two anchors')
        positions = np.array([a['position'] for a in anchors], float)
        values = np.array([a['value'] for a in anchors], float)
        if scale == 'log' and np.any(values <= 0):
            raise ValueError('a logarithmic axis needs positive anchor values')
        f = np.log10(values) if scale == 'log' else values
        if np.ptp(f) == 0 or np.ptp(positions) == 0:
            raise ValueError('axis anchors must have distinct positions and values')
        b, a = np.polyfit(positions, f, 1)
        self.a, self.b, self.scale, self.method = float(a), float(b), scale, method
        self.anchors = anchors
        fitted_position = (f - a) / b
        self.position_residuals = (fitted_position - positions).tolist()
        self.rms_position = float(np.sqrt(np.mean(np.square(self.position_residuals)))) if len(anchors) > 2 else 0.0
        self.floor = floor
        self.residuals = (self.value(positions) - values).tolist() if scale == 'linear' else \
            (np.log10(self.value(positions)) - f).tolist()

    def value(self, position):
        f = self.a + self.b * np.asarray(position, float)
        return np.power(10.0, f) if self.scale == 'log' else f

    def position(self, value):
        value = np.asarray(value, float)
        f = np.log10(value) if self.scale == 'log' else value
        return (f - self.a) / self.b

    def uncertainty(self, position, extra=0.0):
        sigma_pos = math.sqrt(self.rms_position ** 2 + self.floor ** 2 + extra ** 2)
        sigma_f = abs(self.b) * sigma_pos
        if self.scale == 'log':
            return np.abs(self.value(position)) * math.log(10) * sigma_f
        return np.full(np.shape(position), sigma_f, dtype=float)

    def record(self):
        return {'method': self.method, 'scale': self.scale, 'anchors': self.anchors,
                'coefficients': {'intercept': self.a, 'slope': self.b,
                                 'meaning': ('log10(value)' if self.scale == 'log' else 'value') + ' = intercept + slope * position'},
                'residuals': self.residuals,
                'residual_unit': 'decades' if self.scale == 'log' else 'axis units',
                'max_abs_residual': float(max(abs(r) for r in self.residuals)),
                'position_residuals': self.position_residuals,
                'rms_position_residual': self.rms_position,
                'position_floor': self.floor}


def _calibrate_vector(axis, which, content, frame, ticks):
    cal = axis.get('calibration') or {'method': 'tick_labels'}
    method = cal.get('method')
    scale = scale_of(axis, f'{which} axis')
    major, _minor = ticks[which]
    if method == 'anchors':
        anchors = [{'position': float(finite_list([a['position']], 'anchor position')[0]),
                    'value': float(finite_list([a['value']], 'anchor value')[0])} for a in cal.get('anchors', [])]
        return Calibration(anchors, scale, 'anchors', VECTOR_POSITION_FLOOR)
    if method == 'tick_values':
        values = finite_list(cal.get('values'), f'{which} tick values', minimum=2)
        if len(major) != len(values):
            raise ValueError(f'{which} axis: {len(values)} tick values declared but {len(major)} major tick marks '
                             f'were found at {major}; declare anchors instead')
        anchors = [{'position': p, 'value': v, 'source': 'major tick mark'} for p, v in zip(major, values)]
        return Calibration(anchors, scale, 'tick_values', VECTOR_POSITION_FLOOR)
    if method != 'tick_labels':
        raise ValueError(f'{which} axis calibration method must be tick_labels, tick_values or anchors')
    labels = _axis_labels(numeric_labels(content), frame, which)
    if len(labels) < 2:
        raise ValueError(f'{which} axis: fewer than two numeric tick labels found; declare tick values or anchors')
    available = list(major)
    anchors = []
    for label in sorted(labels, key=lambda l: l['x'] if which == 'x' else l['y']):
        centre = label['x'] + label['width'] / 2 if which == 'x' else label['y'] + 0.35 * label['size']
        snapped, distance = None, None
        for pos in available:
            d = abs(pos - centre)
            if distance is None or d < distance:
                snapped, distance = pos, d
        tolerance = (0.5 * label['width'] + 0.6 * label['size']) if which == 'x' else 0.8 * label['size']
        if snapped is not None and distance <= tolerance:
            available.remove(snapped)
            anchors.append({'position': snapped, 'value': label['value'], 'label': label['text'],
                            'source': 'tick label snapped to its tick mark'})
        else:
            anchors.append({'position': centre, 'value': label['value'], 'label': label['text'],
                            'source': 'tick label centre (no tick mark found)'})
    if scale == 'log':
        anchors = [a for a in anchors if a['value'] > 0]
    calibration = Calibration(anchors, scale, 'tick_labels', VECTOR_POSITION_FLOOR)
    span = (frame[2] - frame[0]) if which == 'x' else (frame[3] - frame[1])
    if max(abs(r) for r in calibration.position_residuals) > 0.02 * span:
        raise ValueError(f'{which} axis tick labels do not fit a {scale} scale (worst residual '
                         f'{max(abs(r) for r in calibration.position_residuals):.2f} pt); check the declared '
                         'scale or declare anchors')
    return calibration


# ===================================================================== selection
def _distance(c1, c2):
    if c1 is None or c2 is None:
        return float('inf')
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))


def _legend_zones(content):
    zones = []
    for t in content.texts:
        if _parse_number(t['text']) is not None:
            continue
        s = t['size'] or 10.0
        zones.append((t['x'] - 3.6 * s, t['y'] - 0.5 * s, t['x'] - 0.05 * s, t['y'] + 1.1 * s))
    return zones


def _in_zone(box, zones):
    return any(_inside(box, z, 0.5) for z in zones)


def _legend_handle(content, text, kind):
    wanted = ' '.join(text.lower().split())
    hits = []
    for t in content.texts:
        got = ' '.join(t['text'].lower().split())
        if wanted in got or got in wanted and len(got) >= 3:
            hits.append((0 if got == wanted else 1, -len(got), t))
    # Multi-word legend entries are stored word by word; match the first word's row.
    if not hits:
        first = wanted.split()[0] if wanted.split() else wanted
        hits = [(2, 0, t) for t in content.texts if ' '.join(t['text'].lower().split()) == first]
    if not hits:
        raise ValueError(f'legend entry {text!r} not found on the page')
    hits.sort(key=lambda h: (h[0], h[1]))
    t = hits[0][2]
    # The handle sits left of the first word of the entry on the same row.
    row = [o for o in content.texts if abs(o['y'] - t['y']) < 0.2 * (t['size'] or 10) and o['x'] <= t['x']]
    t = min(row, key=lambda o: o['x']) if row else t
    s = t['size'] or 10.0
    zone = (t['x'] - 3.6 * s, t['y'] - 0.5 * s, t['x'] - 0.05 * s, t['y'] + 1.1 * s)
    markers = [m for m in content.markers if _inside(m['bbox'], zone, 0.5)]
    strokes = [p for p in content.strokes if _inside(p['bbox'], zone, 0.5)]
    fills = [f for f in content.fills if _inside(f['bbox'], zone, 0.5)]
    for f in fills:                       # a single legend marker is often drawn inline
        w, h = f['bbox'][2] - f['bbox'][0], f['bbox'][3] - f['bbox'][1]
        if max(w, h) <= MARKER_MAX_SIZE and 0.5 <= (w / h if h else 99) <= 2.0:
            markers.append({'color': f['color'], 'bbox': f['bbox']})
    fills = [f for f in fills if not any(m['bbox'] == f['bbox'] for m in markers)]
    open_strokes = [p for p in strokes if not all(p['closed'])]
    if kind in ('markers', 'auto') and markers:
        return 'markers', {'color': markers[0]['color']}
    if kind in ('line', 'auto') and open_strokes:
        p = max(open_strokes, key=lambda q: q['bbox'][2] - q['bbox'][0])
        return 'line', {'color': p['color'], 'width': p['width'], 'dash': p['dash']}
    if kind in ('band', 'auto') and fills:
        return 'band', {'color': fills[0]['color']}
    raise ValueError(f'no legend handle of kind {kind!r} found next to {text!r}')


def _match(color, target, tolerance):
    return _distance(color, target) <= tolerance


def _vector_series(spec, content, frame, cx, cy, zones):
    name = spec.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}', name):
        raise ValueError('each series needs a short name')
    label = natural_label(spec.get('label', ''), f'series {name} label')
    kind = spec.get('kind', 'auto')
    if kind not in ('auto', 'line', 'markers', 'band'):
        raise ValueError('series kind must be auto, line, markers or band')
    select = spec.get('select') or {}
    tolerance = float(select.get('tolerance', 0.06))
    width = dash = None
    if 'legend' in select:
        kind, style = _legend_handle(content, select['legend'], kind)
        target = style['color']
        width = style.get('width')
        dash = style.get('dash')
        tolerance = min(tolerance, 0.02)
    elif 'color' in select:
        target = hex_rgb(select['color'])
        if 'width' in select:
            lo, hi = finite_list(select['width'], 'width range', minimum=2)
            width = (lo, hi)
        if 'dash' in select:
            dash = select['dash']
    else:
        raise ValueError(f'series {name}: select by "color" or "legend"')
    region = tuple(finite_list(select['region'], 'selection region', minimum=4)) if 'region' in select else frame

    def width_ok(w):
        if width is None:
            return True
        if isinstance(width, tuple):
            return width[0] <= w <= width[1]
        return abs(w - width) <= 0.15 * width + 0.05

    def dash_ok(d):
        if dash is None:
            return True
        if dash == 'solid':
            return not d
        if dash == 'dashed':
            return bool(d)
        return tuple(d) == tuple(dash)

    usable = lambda box: _overlaps(box, region, 0.5) and not _in_zone(box, zones)
    lines = [p for p in content.strokes if p['color'] is not None and _match(p['color'], target, tolerance)
             and width_ok(p['width']) and dash_ok(p['dash']) and usable(p['bbox'])]
    fills = [f for f in content.fills if f['color'] is not None and _match(f['color'], target, tolerance) and usable(f['bbox'])]
    markers = [m for m in content.markers if m['color'] is not None and _match(m['color'], target, tolerance)
               and _inside(m['bbox'], region, 1.0) and not _in_zone(m['bbox'], zones)]
    if not markers:
        small = [f for f in fills if max(f['bbox'][2] - f['bbox'][0], f['bbox'][3] - f['bbox'][1]) <= MARKER_MAX_SIZE]
        if len(small) >= 2 and kind in ('markers', 'auto'):
            markers = [{'center': ((f['bbox'][0] + f['bbox'][2]) / 2, (f['bbox'][1] + f['bbox'][3]) / 2),
                        'color': f['color'], 'bbox': f['bbox'], 'size': 0} for f in small]
    if kind == 'auto':
        kind = 'markers' if markers else ('line' if [p for p in lines if not all(p['closed'])] else 'band')
    record = {'name': name, 'label': label, 'kind': kind,
              'style': {'color': rgb_hex(target), 'width': width if not isinstance(width, tuple) else list(width),
                        'dash': list(dash) if isinstance(dash, tuple) else dash},
              'selection': {k: v for k, v in select.items()}}
    clip = frame if spec.get('clip_to_frame', True) else None
    page_points = []
    if kind == 'line':
        segments = []
        for p in lines:
            for pts in p['points']:
                for piece in _clip(pts, clip):
                    if len(piece) >= 2:
                        segments.append(piece)
                        page_points.append(piece)
        if not segments:
            raise ValueError(f'series {name}: no drawn line matches the selection')
        record['segments'] = [_to_data(seg, cx, cy) for seg in segments]
    elif kind == 'markers':
        if not markers:
            raise ValueError(f'series {name}: no drawn marker matches the selection')
        centres = sorted({(round(m['center'][0], 3), round(m['center'][1], 3)) for m in markers})
        pts = np.array(centres, float)
        if clip is not None:
            pts = pts[(pts[:, 0] >= clip[0] - 0.5) & (pts[:, 0] <= clip[2] + 0.5)
                      & (pts[:, 1] >= clip[1] - 0.5) & (pts[:, 1] <= clip[3] + 0.5)]
        seg = _to_data(pts, cx, cy)
        bars = [(a, b) for p in content.strokes if p['color'] is not None and _match(p['color'], target, tolerance)
                and not _in_zone(p['bbox'], zones) for a, b in [(q[0], q[-1]) for q in p['points'] if len(q) >= 2]]
        lows, highs, xlows, xhighs = [], [], [], []
        for (px, py), x, y in zip(pts, seg['x'], seg['y']):
            ylo = yhi = xlo = xhi = None
            for a, b in bars:
                if abs(a[0] - b[0]) < 0.3 and abs(a[0] - px) < 0.6 and min(a[1], b[1]) - 0.5 <= py <= max(a[1], b[1]) + 0.5:
                    ylo = min(a[1], b[1]) if ylo is None else min(ylo, a[1], b[1])
                    yhi = max(a[1], b[1]) if yhi is None else max(yhi, a[1], b[1])
                if abs(a[1] - b[1]) < 0.3 and abs(a[1] - py) < 0.6 and min(a[0], b[0]) - 0.5 <= px <= max(a[0], b[0]) + 0.5:
                    xlo = min(a[0], b[0]) if xlo is None else min(xlo, a[0], b[0])
                    xhi = max(a[0], b[0]) if xhi is None else max(xhi, a[0], b[0])
            lows.append(None if ylo is None else float(y - cy.value(ylo)))
            highs.append(None if yhi is None else float(cy.value(yhi) - y))
            xlows.append(None if xlo is None else float(x - cx.value(xlo)))
            xhighs.append(None if xhi is None else float(cx.value(xhi) - x))
        if any(v is not None for v in lows):
            seg['y_error_low'], seg['y_error_high'] = lows, highs
        if any(v is not None for v in xlows):
            seg['x_error_low'], seg['x_error_high'] = xlows, xhighs
        record['segments'] = [seg]
        page_points.append(pts)
    else:
        if not fills:
            raise ValueError(f'series {name}: no drawn filled area matches the selection')
        polygon = max((pts for f in fills for pts in f['points']), key=lambda q: len(q))
        lower, upper = _envelope(polygon)
        record['polygon'] = _to_data(polygon, cx, cy)
        record['lower'] = _to_data(lower, cx, cy)
        record['upper'] = _to_data(upper, cx, cy)
        record['segments'] = [record['lower'], record['upper']]
        page_points.extend([lower, upper])
    record['points'] = int(sum(len(s['x']) for s in record['segments']))
    return record, page_points


def _clip(points, frame):
    pts = np.asarray(points, float)
    if frame is None:
        return [pts]
    keep = ((pts[:, 0] >= frame[0] - 0.5) & (pts[:, 0] <= frame[2] + 0.5)
            & (pts[:, 1] >= frame[1] - 0.5) & (pts[:, 1] <= frame[3] + 0.5))
    pieces, start = [], None
    for i, k in enumerate(keep):
        if k and start is None:
            start = i
        if not k and start is not None:
            pieces.append(pts[start:i])
            start = None
    if start is not None:
        pieces.append(pts[start:])
    return pieces


def _envelope(polygon, max_columns=2000):
    pts = np.asarray(polygon, float)
    xs = np.unique(pts[:, 0])
    if len(xs) > max_columns:
        xs = np.linspace(xs.min(), xs.max(), max_columns)
    edges = list(zip(pts[:-1], pts[1:])) + [(pts[-1], pts[0])]
    lower, upper = [], []
    for x in xs:
        hits = []
        for p, q in edges:
            if min(p[0], q[0]) - 1e-9 <= x <= max(p[0], q[0]) + 1e-9:
                if abs(q[0] - p[0]) < 1e-9:
                    hits.extend((p[1], q[1]))
                else:
                    hits.append(p[1] + (x - p[0]) * (q[1] - p[1]) / (q[0] - p[0]))
        if hits:
            lower.append((x, min(hits)))
            upper.append((x, max(hits)))
    return np.array(lower), np.array(upper)


def _to_data(points, cx, cy, extra_x=0.0, extra_y=0.0):
    pts = np.asarray(points, float)
    x, y = cx.value(pts[:, 0]), cy.value(pts[:, 1])
    return {'x': [float(v) for v in x], 'y': [float(v) for v in y],
            'x_uncertainty': [float(v) for v in cx.uncertainty(pts[:, 0], extra_x)],
            'y_uncertainty': [float(v) for v in cy.uncertainty(pts[:, 1], extra_y)]}


# ===================================================================== inventory
def inventory(path, page=1, region=None):
    """Summarise what a PDF page draws, for choosing selections and calibration."""
    content = _restrict(parse_pdf_page(path, page), tuple(region) if region else None)
    try:
        frame = detect_frame(content)
    except ValueError:
        frame = None
    styles = {}
    for kind, prims in (('stroke', content.strokes), ('fill', content.fills)):
        for p in prims:
            if p['color'] is None:
                continue
            key = (kind, rgb_hex(p['color']), round(p.get('width', 0.0), 2), tuple(p.get('dash', ())))
            row = styles.setdefault(key, {'kind': kind, 'color': key[1], 'width': key[2], 'dash': list(key[3]),
                                          'paths': 0, 'points': 0, 'bbox': p['bbox']})
            row['paths'] += 1
            row['points'] += sum(len(q) for q in p['points'])
            row['bbox'] = _union([row['bbox'], p['bbox']])
    markers = {}
    for m in content.markers:
        key = (rgb_hex(m['color']) if m['color'] else None, m['shape'])
        row = markers.setdefault(key, {'color': key[0], 'shape': key[1], 'count': 0, 'size': round(m['size'], 2)})
        row['count'] += 1
    ticks = detect_ticks(content, frame) if frame else {'x': ([], []), 'y': ([], [])}
    return {'page': page, 'page_box': list(content.box), 'frame': list(frame) if frame else None,
            'styles': sorted(styles.values(), key=lambda r: -r['points']),
            'markers': list(markers.values()),
            'texts': [{'text': t['text'], 'x': round(t['x'], 2), 'y': round(t['y'], 2), 'size': round(t['size'], 2)}
                      for t in content.texts],
            'numeric_labels': [{'text': l['text'], 'value': l['value'], 'x': round(l['x'], 2), 'y': round(l['y'], 2)}
                               for l in numeric_labels(content)],
            'tick_marks': {'x': ticks['x'][0], 'y': ticks['y'][0]},
            'minor_tick_marks': {'x': ticks['x'][1], 'y': ticks['y'][1]}}


# ===================================================================== raster
def _raster_series(spec, image, frame, cx, cy):
    name = spec.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}', name):
        raise ValueError('each series needs a short name')
    label = natural_label(spec.get('label', ''), f'series {name} label')
    kind = spec.get('kind', 'line')
    if kind not in ('line', 'markers', 'band'):
        raise ValueError('raster series kind must be line, markers or band')
    select = spec.get('select') or {}
    if 'color' not in select:
        raise ValueError(f'raster series {name}: select by "color"')
    target = np.array(hex_rgb(select['color']))
    tolerance = float(select.get('tolerance', 0.15))
    c0, r0, c1, r1 = (int(round(v)) for v in frame)
    sub = image[r0:r1, c0:c1, :3].astype(float) / 255.0
    mask = np.sqrt(np.sum((sub - target) ** 2, axis=2)) <= tolerance
    record = {'name': name, 'label': label, 'kind': kind,
              'style': {'color': rgb_hex(target), 'tolerance': tolerance}, 'selection': dict(select)}
    pixels = []
    if kind == 'line':
        cols, rows, thick = [], [], []
        previous = None
        for c in range(mask.shape[1]):
            hit = np.flatnonzero(mask[:, c])
            if not len(hit):
                continue
            runs = np.split(hit, np.flatnonzero(np.diff(hit) > 1) + 1)
            if previous is None:
                run = max(runs, key=len)
            else:
                run = min(runs, key=lambda r: abs(r.mean() - previous))
            previous = float(run.mean())
            cols.append(c + c0 + 0.5)
            rows.append(previous + r0 + 0.5)
            thick.append(len(run))
        if not cols:
            raise ValueError(f'series {name}: no pixel matches the selected colour')
        pts = np.column_stack([cols, rows])
        seg = {'x': [float(v) for v in cx.value(pts[:, 0])], 'y': [float(v) for v in cy.value(pts[:, 1])],
               'x_uncertainty': [float(v) for v in cx.uncertainty(pts[:, 0])],
               'y_uncertainty': [float(u) for u in (cy.uncertainty(np.array([r]), t / 2.0)[0]
                                                    for r, t in zip(pts[:, 1], thick))]}
        record['segments'] = [seg]
        pixels.append(pts)
    elif kind == 'markers':
        from scipy import ndimage
        labels, count = ndimage.label(mask)
        min_area = int(select.get('min_area', 4))
        centres = []
        for index in range(1, count + 1):
            rr, cc = np.nonzero(labels == index)
            if len(rr) >= min_area:
                centres.append((cc.mean() + c0 + 0.5, rr.mean() + r0 + 0.5))
        if not centres:
            raise ValueError(f'series {name}: no marker of the selected colour found')
        pts = np.array(sorted(centres))
        seg = _to_data(pts, cx, cy)
        record['segments'] = [seg]
        pixels.append(pts)
    else:
        lower, upper = [], []
        for c in range(mask.shape[1]):
            hit = np.flatnonzero(mask[:, c])
            if len(hit):
                lower.append((c + c0 + 0.5, hit.max() + r0 + 0.5))
                upper.append((c + c0 + 0.5, hit.min() + r0 + 0.5))
        if not lower:
            raise ValueError(f'series {name}: no pixel matches the selected colour')
        lo, up = np.array(lower), np.array(upper)
        record['lower'], record['upper'] = _to_data(lo, cx, cy), _to_data(up, cx, cy)
        # A row index grows downward: the upper envelope has the smaller row.
        if cy.b > 0:
            record['lower'], record['upper'] = record['upper'], record['lower']
        record['segments'] = [record['lower'], record['upper']]
        pixels.extend([lo, up])
    record['points'] = int(sum(len(s['x']) for s in record['segments']))
    return record, pixels


def _raster_calibration(axis, which):
    cal = axis.get('calibration') or {}
    if cal.get('method') != 'anchors':
        raise ValueError(f'raster {which} axis needs declared pixel anchors (method "anchors")')
    anchors = [{'position': float(finite_list([a['position']], 'anchor position')[0]),
                'value': float(finite_list([a['value']], 'anchor value')[0])} for a in cal.get('anchors', [])]
    return Calibration(anchors, scale_of(axis, f'{which} axis'), 'anchors', RASTER_POSITION_FLOOR)


# ===================================================================== review overlay
def _review_png(background, to_pixel, series_points, anchors, labels, size):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    height, width = background.shape[:2]
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(background, origin='upper')
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.axis('off')
    palette = ['#ff00ff', '#00c8ff', '#ff8c00', '#00b000', '#8000ff']
    for i, (pts_list, label) in enumerate(zip(series_points, labels)):
        colour = palette[i % len(palette)]
        for j, pts in enumerate(pts_list):
            px = np.array([to_pixel(x, y) for x, y in np.asarray(pts)])
            if len(px):
                ax.plot(px[:, 0], px[:, 1], '+', color=colour, ms=size, mew=1.0,
                        label=('Extracted: ' + label) if j == 0 else None)
    for which, anchor_list in anchors.items():
        for a in anchor_list:
            px, py = a
            ax.plot([px], [py], 'x', color='#00a0a0', ms=size + 3, mew=1.5)
    ax.legend(loc='upper right', fontsize=7, framealpha=0.8)
    buffer = io.BytesIO()
    fig.savefig(buffer, format='png', dpi=dpi)
    plt.close(fig)
    return buffer.getvalue()


# ===================================================================== entry point
def run_spec(spec_path, out_dir):
    """Digitise according to a specification; write digitized.json and review.png into out_dir."""
    spec, base = load_spec(spec_path)
    allowed = {'schema_version', 'source', 'region', 'frame', 'axes', 'series', 'description'}
    if set(spec) - allowed:
        raise ValueError(f'unknown digitisation fields: {sorted(set(spec) - allowed)}')
    source = spec.get('source') or {}
    path = resolve(base, source.get('path'))
    page = int(source.get('page', 1))
    raw = read_bytes(path)
    fmt = source.get('format') or ('raster' if path.suffix.lower() in RASTER_SUFFIXES else 'vector-pdf')
    if fmt not in ('raster', 'vector-pdf'):
        raise ValueError('source format must be vector-pdf or raster')
    axes = spec.get('axes') or {}
    if set(axes) != {'x', 'y'}:
        raise ValueError('declare both x and y axes')
    axis_titles = {k: axis_title(axes[k], f'{k} axis') for k in ('x', 'y')}
    series_specs = spec.get('series')
    if not isinstance(series_specs, list) or not series_specs:
        raise ValueError('declare at least one series')
    names = [s.get('name') for s in series_specs]
    if len(set(names)) != len(names):
        raise ValueError('series names must be unique')
    for s in series_specs:
        natural_label(s.get('label', ''), f"series {s.get('name')} label")
    out = new_output_dir(out_dir)
    warnings = []
    if fmt == 'vector-pdf':
        content = parse_pdf_page(path, page)
        region = tuple(finite_list(spec['region'], 'region', minimum=4)) if 'region' in spec else None
        content = _restrict(content, region)
        frame = tuple(finite_list(spec['frame'], 'frame', minimum=4)) if 'frame' in spec else detect_frame(content)
        ticks = detect_ticks(content, frame)
        cx = _calibrate_vector(axes['x'], 'x', content, frame, ticks)
        cy = _calibrate_vector(axes['y'], 'y', content, frame, ticks)
        zones = _legend_zones(content)
        series, overlay_points = [], []
        for s in series_specs:
            record, pts = _vector_series(s, content, frame, cx, cy, zones)
            series.append(record)
            overlay_points.append(pts)
        try:
            import pypdfium2 as pdfium
            document = pdfium.PdfDocument(raw)
            scale = 2.0
            image = np.asarray(document[page - 1].render(scale=scale).to_pil().convert('RGB'))
            x0, top = content.box[0], content.box[3]
            to_pixel = lambda x, y: ((x - x0) * scale, (top - y) * scale)
            anchors = {k: [to_pixel(a['position'], frame[1]) if k == 'x' else to_pixel(frame[0], a['position'])
                           for a in c.anchors] for k, c in (('x', cx), ('y', cy))}
            png = _review_png(image, to_pixel, overlay_points, anchors, [s['label'] for s in series], 4)
        except Exception as exc:          # the review image is evidence, never a silent gap
            raise ValueError(f'could not render the review overlay: {exc}') from exc
        frame_record = {'box': list(frame), 'unit': 'pdf points', 'source': 'declared' if 'frame' in spec else 'detected'}
    else:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            rgba = im.convert('RGBA')
            white = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
            image = np.asarray(Image.alpha_composite(white, rgba).convert('RGB'))
        h, w = image.shape[:2]
        frame = tuple(finite_list(spec['frame'], 'frame', minimum=4)) if 'frame' in spec else (0, 0, w, h)
        cx = _raster_calibration(axes['x'], 'x')
        cy = _raster_calibration(axes['y'], 'y')
        series, overlay_points = [], []
        for s in series_specs:
            record, pts = _raster_series(s, image, frame, cx, cy)
            series.append(record)
            overlay_points.append(pts)
        to_pixel = lambda x, y: (x, y)
        anchors = {'x': [(a['position'], frame[3] - 2) for a in cx.anchors],
                   'y': [(frame[0] + 2, a['position']) for a in cy.anchors]}
        png = _review_png(image, to_pixel, overlay_points, anchors, [s['label'] for s in series], 3)
        frame_record = {'box': list(frame), 'unit': 'pixels from the top-left corner',
                        'source': 'declared' if 'frame' in spec else 'whole image'}
        warnings.append('Raster digitisation resolves positions to about one pixel; the per-point uncertainty '
                        'includes half the traced line thickness.')
    overlay = write_new_bytes(out / 'review.png', png)
    document = {
        'schema_version': 1, 'kind': 'digitized-series',
        'source': {'path': str(path), 'sha256': sha256_bytes(raw), 'size': len(raw),
                   'page': page if fmt == 'vector-pdf' else None, 'format': fmt},
        'frame': frame_record,
        'axes': {k: {'label': axes[k]['label'], 'unit': axes[k].get('unit', ''), 'title': axis_titles[k],
                     'scale': scale_of(axes[k], k), 'calibration': c.record()}
                 for k, c in (('x', cx), ('y', cy))},
        'series': series,
        'review_overlay': {'path': overlay['path'], 'sha256': overlay['sha256'],
                           'instructions': 'Check that every extracted point (+) sits on the intended curve and '
                                           'that the calibration anchors (x) sit on the labelled ticks.'},
        'provenance': {'tool': 'ravel.plotting.digitize', 'code': code_identity(__file__),
                       'specification_sha256': sha256_bytes(read_bytes(spec_path))},
        'evidence_class': 'digitized figure (approximate); prefer tabulated values when they exist',
        'warnings': warnings,
        'machine_review_only': True,
    }
    write_new_json(out / 'digitized.json', document)
    return document


def load_series(document, name):
    """Return one series of a digitized-series document by name."""
    if not isinstance(document, dict) or document.get('kind') != 'digitized-series':
        raise ValueError('a digitized-series document is required')
    for series in document.get('series', []):
        if series.get('name') == name:
            return series
    raise ValueError(f'series {name!r} is not in the digitized document')
