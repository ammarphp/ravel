"""Shared input, label and output helpers for the figure and comparison tools.

Specifications are strict JSON. Paths inside a specification resolve relative to
the specification's own directory. Outputs are written as new files only; an
existing output is never overwritten. Every figure passes the house plot lint
before it is saved.
"""
from pathlib import Path
import hashlib
import json
import math
import re

from .display_labels import label_errors

MAX_INPUT_BYTES = 64 * 1024 * 1024

# Raw identifiers that must not reach a figure: dotted tree branches
# (Electron.PT), indexed branches (jet[0]) and snake_case column names.
_BRANCH = re.compile(r'\b[A-Za-z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9]*\b|\b\w+\[\d+\]')


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def read_bytes(path, limit=MAX_INPUT_BYTES):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'regular input file required: {path}')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'input exceeds {limit} bytes: {path}')
    return raw


def pin(path):
    path = Path(path).absolute()
    raw = read_bytes(path)
    return {'path': str(path), 'sha256': sha256_bytes(raw), 'size': len(raw)}


def strict_json(raw, label='JSON document'):
    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ValueError(f'{label} repeats key {key!r}')
            out[key] = value
        return out

    def constant(name):
        raise ValueError(f'{label} contains non-finite {name}')
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def load_json(path):
    return strict_json(read_bytes(path), str(path))


def load_spec(path):
    """Read a specification and return (document, directory it resolves paths against)."""
    path = Path(path).absolute()
    document = load_json(path)
    if not isinstance(document, dict) or document.get('schema_version') != 1:
        raise ValueError(f'{path}: schema_version 1 specification object required')
    return document, path.parent


def resolve(base, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('a nonempty file path is required')
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(base) / path).absolute()


def json_pointer(document, pointer):
    if pointer in (None, ''):
        return document
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('JSON pointer must start with /')
    node = document
    for part in pointer[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                raise ValueError(f'JSON pointer {pointer} does not resolve')
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise ValueError(f'JSON pointer {pointer} does not resolve')
    return node


def finite_list(values, label, *, minimum=1):
    if not isinstance(values, (list, tuple)) or len(values) < minimum:
        raise ValueError(f'{label} needs at least {minimum} numbers')
    out = []
    for v in values:
        if type(v) not in (int, float) or not math.isfinite(v):
            raise ValueError(f'{label} must contain finite numbers')
        out.append(float(v))
    return out


def natural_label(text, what='label'):
    """Return a display label or refuse a machine identifier.

    Scientific math between $ signs is allowed. Underscores, ROOT markup,
    dotted branch names and indexed columns outside math are refused.
    """
    errors = label_errors(text)
    if not errors:
        plain = re.sub(r'\$[^$]*\$', '', text)
        if _BRANCH.search(plain):
            errors.append('raw branch or column name')
    if errors:
        raise ValueError(f'{what} {text!r} is not a natural-language label: ' + '; '.join(errors))
    return text


def axis_title(axis, what):
    """'Label [unit]' from a declared axis; the unit may be '' for dimensionless."""
    if not isinstance(axis, dict) or 'label' not in axis:
        raise ValueError(f'{what} needs a natural-language label')
    label = natural_label(axis['label'], what)
    unit = axis.get('unit', '')
    if not isinstance(unit, str):
        raise ValueError(f'{what} unit must be text')
    if unit.strip():
        natural_label(unit, what + ' unit')
        return f'{label} [{unit}]'
    return label


def scale_of(axis, what):
    scale = (axis or {}).get('scale', 'linear')
    if scale not in ('linear', 'log'):
        raise ValueError(f'{what} scale must be linear or log')
    return scale


def write_new_bytes(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': path.name, 'sha256': sha256_bytes(raw), 'size': len(raw)}


def write_new_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    return write_new_bytes(path, raw)


def new_output_dir(path):
    path = Path(path).absolute()
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f'output directory must be new or empty: {path}')
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_figure(fig, directory, stem, *, dpi=200):
    """Lint the live figure, then write STEM.pdf and STEM.png as new files."""
    from . import mplhep_style as house
    import io
    violations = house.lint_figure(fig)
    if violations:
        raise ValueError('figure layout failed the plot lint: ' + '; '.join(violations))
    files = []
    for ext in ('pdf', 'png'):
        buffer = io.BytesIO()
        fig.savefig(buffer, format=ext, dpi=dpi, bbox_inches='tight')
        files.append(write_new_bytes(Path(directory) / f'{stem}.{ext}', buffer.getvalue()))
    return {'stem': stem, 'files': files, 'plot_lint': 'PASS'}


def code_identity(module_file):
    raw = Path(module_file).read_bytes()
    return {'module': Path(module_file).name, 'sha256': sha256_bytes(raw)}


def hex_rgb(value):
    """'#RRGGBB' or [r, g, b] in 0..1 -> (r, g, b) floats in 0..1."""
    if isinstance(value, str) and re.fullmatch(r'#?[0-9a-fA-F]{6}', value):
        value = value.lstrip('#')
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        rgb = finite_list(value, 'colour', minimum=3)
        if all(0 <= c <= 1 for c in rgb):
            return tuple(rgb)
    raise ValueError(f'colour must be #RRGGBB or three numbers in 0..1: {value!r}')


def rgb_hex(rgb):
    return '#' + ''.join(f'{max(0, min(255, round(c * 255))):02x}' for c in rgb)
