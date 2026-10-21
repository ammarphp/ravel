"""Detached presentation provenance. Source bytes are never modified in place."""
from __future__ import annotations

from io import BytesIO
import json
import re
import xml.etree.ElementTree as ET

from .common import SinkRefused

IMAGES = {'.png', '.jpg', '.jpeg', '.tif', '.tiff'}
# These are presentation formats for which silent byte copying would lose the notice.
UNSUPPORTED = {'.gif', '.webp', '.bmp', '.eps', '.ps', '.ppt', '.pptx', '.doc', '.docx', '.avif', '.heic'}


def lines(label, reference, qualification=None):
    result = []
    if label.lower() != 'accepted':
        limitation = ' '.join(str(qualification or 'Limitations apply; consult the receipt.').split())
        # Bound the detached notice while keeping the complete qualification in the receipt.
        result.append(f'{label.upper()}: {limitation[:180]}')
    result.append(f'RAVEL provenance: {reference} -> delivery/RECEIPT.json')
    return result


def _pdf(raw, label, reference, notice):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, RectangleObject
    reader = PdfReader(BytesIO(raw), strict=True)
    if reader.is_encrypted or not reader.pages:
        raise ValueError('encrypted or empty PDF')
    writer = PdfWriter()
    for original in reader.pages:
        original.transfer_rotation_to_content()
        page = writer.add_page(original)
        left, bottom, right, top = map(float, page.cropbox)
        width = right - left
        if width < 36 or top <= bottom:
            raise ValueError('invalid PDF page bounds')
        # Use fixed ASCII notices and wrap by Helvetica's conservative maximum glyph width.
        font_size = min(9.0, max(4.0, width / 100))
        count = max(1, int((width - 12) / font_size))
        wrapped = [part for line in notice for part in _wrap(line, count)]
        band = 12 + (font_size + 3) * len(wrapped)
        page.mediabox = RectangleObject([left, bottom - band, right, top])
        page.cropbox = RectangleObject(page.mediabox)
        footer = writer.add_blank_page(width=width, height=top - bottom + band)
        footer.mediabox = RectangleObject(page.mediabox)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        footer[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/RavelNotice'): writer._add_object(font)})})
        commands = [f'q 1 1 1 rg {left} {bottom-band} {width} {band} re f Q',
                    f'BT /RavelNotice {font_size} Tf 0 0 0 rg']
        for index, line in enumerate(wrapped):
            encoded = line.encode('ascii', 'replace').decode('ascii').replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(f'1 0 0 1 {left+6} {bottom-9-index*(font_size+3)} Tm ({encoded}) Tj')
        commands.append('ET')
        stream = DecodedStreamObject()
        stream.set_data('\n'.join(commands).encode('ascii'))
        footer[NameObject('/Contents')] = writer._add_object(stream)
        page.merge_page(footer)
        del writer.pages[-1]
    metadata = dict(reader.metadata or {})
    metadata.update({'/Label': label.upper(), '/ReceiptReference': reference})
    writer.add_metadata({str(k): str(v) for k, v in metadata.items()})
    result = BytesIO()
    writer.write(result)
    data = result.getvalue()
    check = PdfReader(BytesIO(data), strict=True)
    # Verification is on the actual serialized output, for every page.
    for page in check.pages:
        text = ' '.join((page.extract_text() or '').split())
        expected = ' '.join(' '.join(notice).encode('ascii', 'replace').decode('ascii').split())
        # Wrapping may split identifiers; compare with whitespace removed.
        if expected.replace(' ', '') not in text.replace(' ', ''):
            raise ValueError('PDF visible notice failed extract-text verification')
    if check.metadata.get('/ReceiptReference') != reference or check.metadata.get('/Label') != label.upper():
        raise ValueError('PDF notice metadata verification failed')
    return data


def _wrap(line, count):
    return [line[start:start + count] for start in range(0, len(line), count)] or ['']


def _image(raw, suffix, label, reference, notice):
    from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin
    source = Image.open(BytesIO(raw))
    if source.format not in {'PNG', 'JPEG', 'TIFF'}:
        raise ValueError('image encoding does not match a supported PNG/JPEG/TIFF format')
    if getattr(source, 'n_frames', 1) != 1:
        raise ValueError('multiple image frames; export each frame as a separate PNG or PDF')
    source.load()
    if source.mode not in {'RGB', 'RGBA', 'L', 'LA', 'P', '1'}:
        raise ValueError('unsupported high-depth or color image mode; export a presentation PNG while retaining the scientific source')
    source = ImageOps.exif_transpose(source)
    font = ImageFont.load_default(size=14)
    width = max(source.width, 640)
    count = max(16, int((width - 16) / 14))
    wrapped = [part for line in notice for part in _wrap(line, count)]
    band = 16 + 20 * len(wrapped)
    canvas = Image.new('RGBA', (width, source.height + band), 'white')
    canvas.paste(source.convert('RGBA'), (0, 0))
    draw = ImageDraw.Draw(canvas)
    bounds = []
    for index, line in enumerate(wrapped):
        point = (8, source.height + 8 + index * 20)
        box = draw.textbbox(point, line, font=font)
        if box[0] < 0 or box[1] < source.height or box[2] > width or box[3] > canvas.height:
            raise ValueError('visible image notice exceeds the added footer bounds')
        draw.text(point, line, fill='black', font=font)
        bounds.append(box)
    result = BytesIO()
    metadata = {'Label': label.upper(), 'ReceiptReference': reference, 'Notice': '\n'.join(notice)}
    if suffix == '.png':
        info = PngImagePlugin.PngInfo()
        for key, value in metadata.items():
            info.add_text(key, value)
        canvas.save(result, format='PNG', pnginfo=info)
    elif suffix in {'.jpg', '.jpeg'}:
        exif = Image.Exif()
        exif[270] = json.dumps(metadata)
        canvas.convert('RGB').save(result, format='JPEG', quality=95, exif=exif)
    else:
        canvas.save(result, format='TIFF', tiffinfo={270: json.dumps(metadata)})
    data = result.getvalue()
    check = Image.open(BytesIO(data))
    saved = check.info if suffix == '.png' else json.loads(check.getexif()[270])
    if saved.get('Label') != label.upper() or saved.get('ReceiptReference') != reference or check.size != canvas.size:
        raise ValueError('image notice metadata or geometry verification failed')
    # Confirm serialized pixels contain ink within the declared footer, including lossy JPEG.
    footer = check.convert('RGB').crop((0, source.height, width, canvas.height))
    if footer.getextrema() == ((255, 255), (255, 255), (255, 255)):
        raise ValueError('image visible notice verification failed')
    return data


def _svg(raw, label, reference, notice):
    if re.search(br'<!|<\?', re.sub(br'^\s*<\?xml\s+[^?]*\?>', b'', raw), re.I):
        raise ValueError('SVG declarations, entities and processing instructions are unsupported')
    root = ET.fromstring(raw)
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('not an SVG document')
    forbidden = {'script', 'foreignobject', 'animate', 'animatemotion', 'animatetransform', 'set', 'style', 'handler', 'iframe', 'object', 'embed', 'link'}
    for element in root.iter():
        if (element.tag.startswith('{') and not element.tag.startswith('{http://www.w3.org/2000/svg}')) or element.tag.split('}')[-1].lower() in forbidden:
            raise ValueError('active SVG content; export an inert SVG or PNG')
        for key, value in element.attrib.items():
            name = key.split('}')[-1].lower()
            if name == 'base' or (name == 'style' and '\\' in value) or name.startswith('on') or ('href' in name and not value.startswith('#')) or re.search(r'url\s*\((?!\s*[\"\']?#)|@import|javascript:', value, re.I):
                raise ValueError('active or externally referenced SVG content; export an inert SVG or PNG')
    view = root.get('viewBox')
    if view:
        x, y, width, height = map(float, view.replace(',', ' ').split())
    else:
        def dimension(key):
            value = root.get(key, '')
            if not re.fullmatch(r'\d+(?:\.\d+)?(?:px)?', value):
                raise ValueError('SVG needs numeric width/height or a viewBox')
            return float(value.removesuffix('px'))
        x, y, width, height = 0, 0, dimension('width'), dimension('height')
    import math
    if not all(math.isfinite(v) for v in (x, y, width, height)) or min(width, height) <= 0:
        raise ValueError('invalid SVG dimensions')
    size = width / 110
    wrapped = [part for line in notice for part in _wrap(line, 100)]
    band = size * (len(wrapped) * 1.5 + 2)
    # A nested original viewport preserves percentage geometry and isolates inherited styles
    # (for example root opacity) from the controller's visible notice.
    original_width = root.get('width', str(width))
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([a-z]*)', original_width)
    if not match:
        raise ValueError('SVG needs a fixed viewport width; export PNG instead')
    ns = '{http://www.w3.org/2000/svg}' if root.tag.startswith('{') else ''
    wrapper = ET.Element(ns + 'svg', {'width': original_width,
                         'height': f'{float(match[1]) * (height+band)/width}{match[2]}',
                         'viewBox': f'{x} {y} {width} {height+band}'})
    root.set('x', str(x))
    root.set('y', str(y))
    root.set('width', str(width))
    root.set('height', str(height))
    root.set('viewBox', f'{x} {y} {width} {height}')
    root.set('overflow', 'hidden')
    wrapper.append(root)
    root = wrapper
    metadata = ET.SubElement(root, ns + 'metadata')
    metadata.text = json.dumps({'Label': label.upper(), 'ReceiptReference': reference})
    group = ET.SubElement(root, ns + 'g', {'id': 'ravel-provenance'})
    ET.SubElement(group, ns + 'rect', {'x': str(x), 'y': str(y+height), 'width': str(width), 'height': str(band), 'fill': 'white'})
    for index, line in enumerate(wrapped):
        text = ET.SubElement(group, ns + 'text', {'x': str(x+size), 'y': str(y+height+size*(index*1.5+1.5)),
                                               'font-size': str(size), 'font-family': 'monospace', 'fill': 'black'})
        text.text = line
    data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    checked = ET.fromstring(data)
    if reference not in ''.join(checked.itertext()).replace('\n', ''):
        # A long reference can wrap; check the complete visible string without whitespace.
        if reference not in ''.join(checked.itertext()).replace(' ', '').replace('\n', ''):
            raise ValueError('SVG visible reference verification failed')
    return data


def tex(raw, notice):
    text = raw.decode('utf-8')
    # Keep offsets while suppressing comments, so commented begin markers cannot be selected.
    uncommented = re.sub(r'(?<!\\)%[^\n]*', lambda m: ' ' * len(m[0]), text)
    matches = list(re.finditer(r'\\begin\s*\{document\}', uncommented))
    if len(matches) != 1:
        raise ValueError('TeX needs exactly one uncommented \\begin{document}; deliver a compiled PDF or complete TeX document')
    escaped = {'\\': r'\textbackslash{}', '{': r'\{', '}': r'\}', '%': r'\%', '$': r'\$',
               '&': r'\&', '#': r'\#', '_': r'\_', '^': r'\textasciicircum{}', '~': r'\textasciitilde{}'}
    visible = '\n\\par\\begingroup\\small\\noindent\n' + r'\par '.join(
        ''.join(escaped.get(c, c) for c in line) for line in notice) + '\n\\par\\endgroup\n'
    position = matches[0].end()
    return (text[:position] + visible + text[position:]).encode('utf-8')


def presented(suffix):
    """Whether ``derivative`` renders (or refuses) this suffix: the delivery reads such a file whole."""
    return suffix in ('.pdf', '.svg', '.tex') or suffix in IMAGES or suffix in UNSUPPORTED


def derivative(raw, suffix, label, reference, qualification=None):
    """Return a visibly marked derivative, or None for non-presentation data."""
    notice = lines(label, reference, qualification)
    try:
        if suffix == '.pdf':
            return _pdf(raw, label, reference, notice)
        if suffix in IMAGES:
            return _image(raw, suffix, label, reference, notice)
        if suffix == '.svg':
            return _svg(raw, label, reference, notice)
        if suffix == '.tex':
            return tex(raw, notice)
        if suffix in UNSUPPORTED:
            raise ValueError('unsupported presentation format; export PDF, PNG, JPEG, TIFF or inert SVG')
    except ImportError as exc:
        raise SinkRefused(f'{suffix} provenance rendering requires the installed figures dependencies; install the project figures profile: {exc}') from exc
    except Exception as exc:
        raise SinkRefused(f'Cannot visibly label {suffix} delivery: {exc}. Repair/export the source as a supported presentation format and deliver again.') from exc
    return None
