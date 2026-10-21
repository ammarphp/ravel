"""Editable model knowledge, defaults and split token prices from the catalogue.

The builtin catalogue is merged with a user overlay selected by
``RAVEL_MODEL_CATALOGUE`` or ``.ravel/models/catalogue.json`` in the current
directory or a parent project directory. Overlay rows replace matching ids;
new rows precede existing rows of their family and class. A new model is a
catalogue row, not code. Unknown prices and unreported usage remain unknown.
"""
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import tempfile

from . import transport_registry


BUILTIN = Path(__file__).resolve().parents[1] / 'data' / 'models' / 'catalogue.json'
OVERLAY_ENV = 'RAVEL_MODEL_CATALOGUE'
CLASSES = ('top', 'strong', 'mid', 'small')
STATUSES = ('current', 'legacy', 'preview')
PRICE_KEYS = ('input', 'cache_write', 'cache_read', 'output')

_DOCUMENT_KEYS = {'schema_version', 'kind', 'purpose', 'recorded_utc', 'price_basis',
                  'classes', 'tiers', 'presets', 'models'}
_ROW_KEYS = {'id', 'family', 'class', 'tiers', 'context_tokens', 'max_output_tokens',
             'prices_per_million', 'efforts', 'released', 'status'}
_USAGE_KEYS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')
_LOCAL_OVERLAY = Path('.ravel') / 'models' / 'catalogue.json'
# Dated snapshots and explicit revision aliases belong to one row. A new numeric
# model version does not inherit the capabilities or tariff of an older prefix.
VERSION_SUFFIX = r'(?:-(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})|@.+)'


def _fail(field, message, identity=None):
    row = f'row {identity!r} ' if identity is not None else ''
    raise ValueError(f'model catalogue: {row}{field}: {message}')


def _shape(value, required, optional, field, identity=None):
    if type(value) is not dict:
        _fail(field, 'must be an object', identity)
    if any(type(key) is not str for key in value):
        _fail(field, 'field names must be strings', identity)
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        _fail(field, f'missing {sorted(missing)} or unknown {sorted(extra)} fields', identity)


def _strings(value, field, identity=None, choices=None, nonempty=False):
    if (type(value) is not list or (nonempty and not value)
            or any(type(item) is not str or not item.strip() for item in value)):
        _fail(field, 'must be a list of nonempty strings', identity)
    if len(value) != len(set(value)) or (choices is not None and not set(value) <= set(choices)):
        _fail(field, f'must contain unique values from {choices}' if choices else 'must contain unique values', identity)


def _valid_id(model_id):
    return type(model_id) is str and transport_registry.MODEL_ID.fullmatch(model_id) is not None


def validate(document):
    """Check the closed catalogue shape and return the supplied object unchanged.

    Explicit null token limits, release and prices denote unknown adopted metadata.
    Prices, when supplied, must include all four finite, nonnegative components.
    ``origins`` is optional metadata attached by :func:`load`.
    """
    _shape(document, _DOCUMENT_KEYS, {'origins'}, 'document')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        _fail('schema_version', 'must be 1')
    if document['kind'] != 'model-catalogue':
        _fail('kind', 'must be model-catalogue')
    for field in ('purpose', 'recorded_utc', 'price_basis'):
        if type(document[field]) is not str or not document[field].strip():
            _fail(field, 'must be a nonempty string')
    for field, values in (('classes', CLASSES), ('tiers', transport_registry.TIERS)):
        _strings(document[field], field, choices=values, nonempty=True)
        if set(document[field]) != set(values):
            _fail(field, f'must list {values}')
    if type(document['presets']) is not dict or not document['presets']:
        _fail('presets', 'must be a nonempty object')
    for name, preset in document['presets'].items():
        field = f'presets.{name}'
        if type(name) is not str or not name.strip():
            _fail('presets', 'names must be nonempty strings')
        _shape(preset, set(transport_registry.TIERS), {'summary'}, field)
        for tier in transport_registry.TIERS:
            _strings(preset[tier], f'{field}.{tier}', choices=CLASSES, nonempty=True)
        if 'summary' in preset and (type(preset['summary']) is not str or not preset['summary'].strip()):
            _fail(f'{field}.summary', 'must be a nonempty string')
    if type(document['models']) is not list:
        _fail('models', 'must be a list')
    families = dict(transport_registry.FAMILY_PATTERNS)
    ids = set()
    for row in document['models']:
        identity = row.get('id', '?') if type(row) is dict else '?'
        _shape(row, _ROW_KEYS, {'notes'}, 'fields', identity)
        if not _valid_id(row['id']):
            _fail('id', 'must be a valid model identifier', identity)
        if identity in ids:
            _fail('id', 'is duplicated', identity)
        ids.add(identity)
        for field, choices in (('family', families), ('class', CLASSES), ('status', STATUSES)):
            if type(row[field]) is not str or row[field] not in choices:
                _fail(field, f'must be one of {tuple(choices)}', identity)
        _strings(row['tiers'], 'tiers', identity, transport_registry.TIERS, nonempty=True)
        _strings(row['efforts'], 'efforts', identity)
        for field in ('context_tokens', 'max_output_tokens'):
            if row[field] is not None and (type(row[field]) is not int or row[field] <= 0):
                _fail(field, 'must be a positive integer or null when unknown', identity)
        if row['released'] is not None and (type(row['released']) is not str or not row['released'].strip()):
            _fail('released', 'must be a nonempty string or null when unknown', identity)
        if 'notes' in row and type(row['notes']) is not str:
            _fail('notes', 'must be a string', identity)
        prices = row['prices_per_million']
        if prices is not None:
            _shape(prices, set(PRICE_KEYS), set(), 'prices_per_million', identity)
            for key, value in prices.items():
                # JSON numbers may be arbitrarily large integers; reject nonfinite floats
                # without first coercing an integer to an overflowing float.
                if type(value) not in (int, float) or value < 0 or (type(value) is float and not math.isfinite(value)):
                    _fail(f'prices_per_million.{key}', 'must be finite and nonnegative', identity)
    if 'origins' in document:
        origins = document['origins']
        if type(origins) is not dict or set(origins) != ids:
            _fail('origins', 'must map each model id exactly once')
        for identity, origin in origins.items():
            if type(origin) is not str or not (origin == 'builtin' or (origin.startswith('overlay:') and origin[8:])):
                _fail('origins', 'must be builtin or overlay:<path>', identity)
    return document


def _read(path):
    try:
        return validate(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f'model catalogue: {path}: {exc}') from exc


def _overlay_path(overlay=None):
    if overlay is not None:
        return Path(overlay).expanduser().resolve()
    if os.environ.get(OVERLAY_ENV):
        return Path(os.environ[OVERLAY_ENV]).expanduser().resolve()
    for directory in (Path.cwd(), *Path.cwd().parents):
        path = directory / _LOCAL_OVERLAY
        if path.exists():
            return path
    return None


def load(*, builtin_only=False, overlay=None):
    """Load builtin rows and merge the selected overlay, recording every row's origin.

    An explicit overlay path takes precedence over the environment and project
    search. A selected unreadable or malformed overlay is refused. ``builtin_only``
    skips overlay discovery entirely. Replacement rows retain their builtin slot;
    new rows retain overlay order before the first row of their family and class.
    """
    result = _read(BUILTIN)
    result['origins'] = {row['id']: 'builtin' for row in result['models']}
    path = None if builtin_only else _overlay_path(overlay)
    if path is None:
        return result
    user = _read(path)
    replacements = {row['id']: row for row in user['models']}
    builtin_ids = set(result['origins'])
    rows = [replacements.get(row['id'], row) for row in result['models']]
    # Insert in reverse so multiple new rows of a class preserve authored order.
    for row in reversed(user['models']):
        if row['id'] in builtin_ids:
            continue
        position = next((i for i, old in enumerate(rows)
                         if (old['family'], old['class']) == (row['family'], row['class'])), len(rows))
        rows.insert(position, row)
    result['models'] = rows
    result['origins'].update({row['id']: f'overlay:{path}' for row in user['models']})
    result['presets'].update(user['presets'])
    if user['models'] and user['price_basis'] != result['price_basis']:
        result['price_basis'] += f'; overlay {path}: {user["price_basis"]}'
    return validate(result)


def _catalogue(catalogue):
    return load() if catalogue is None else catalogue


def lookup(model_id, catalogue=None):
    """Find an exact id, then the longest id with a dated or @ revision suffix."""
    if not _valid_id(model_id):
        return None
    rows = _catalogue(catalogue)['models']
    for row in rows:
        if row['id'] == model_id:
            return row
    matches = [row for row in rows if model_id.startswith(row['id'])
               and re.fullmatch(VERSION_SUFFIX, model_id[len(row['id']):])]
    return max(matches, key=lambda row: len(row['id']), default=None)


def problem(model_id, catalogue=None):
    """Return a stable refusal reason for invalid or uncatalogued identifiers."""
    if not _valid_id(model_id):
        return 'model:invalid'
    return None if lookup(model_id, catalogue) is not None else 'model:uncatalogued'


def remedy(model_id, catalogue=None):
    """Give one concrete sentence explaining how to fix a model selection."""
    issue = problem(model_id, catalogue)
    if issue == 'model:invalid':
        return (f'model {model_id!r} has an invalid identifier: use 1 to 200 letters, digits, dots, '
                'underscores, colons, slashes, @ signs or hyphens, starting with a letter or digit')
    if issue is None:
        return f'model {model_id!r} is in the model catalogue and needs no correction'
    return (f'model {model_id!r} is not in the model catalogue: add a row to .ravel/models/catalogue.json '
            '(or the file named by RAVEL_MODEL_CATALOGUE) with its family, class, tiers and prices, '
            'or run `ravel models detect --adopt` after the provider lists it')


def price(usage, model_id, catalogue=None):
    """Price only complete uncached-input, cache-write, cache-read and output usage."""
    catalogue = _catalogue(catalogue)
    row = lookup(model_id, catalogue)
    result = {'status': 'model_unknown', 'cost_usd': None, 'model': row['id'] if row else None,
              'prices_per_million': deepcopy(row['prices_per_million']) if row else None,
              'price_basis': catalogue['price_basis']}
    if (type(usage) is not dict
            or any(type(usage.get(key)) is not int or usage[key] < 0 for key in _USAGE_KEYS)):
        result['status'] = 'usage_incomplete'
        return result
    if row is None:
        return result
    prices = row['prices_per_million']
    if prices is None:
        result['status'] = 'usage_incomplete'
        result['price_basis'] += '; row prices are not supplied'
        return result
    try:
        cost = math.fsum(usage[key] * prices[part] / 1_000_000 for key, part in zip(_USAGE_KEYS, PRICE_KEYS))
    except OverflowError:
        cost = math.inf
    if not math.isfinite(cost):
        result['status'] = 'usage_incomplete'
        result['price_basis'] += '; cost exceeds the finite numeric range'
        return result
    result.update(status='priced', cost_usd=cost)
    return result


def call_bound(model_id, catalogue=None):
    """Conservative list-price bound for one context-full request; never changes the model.

    Context and output limits come from the same editable catalogue as the tariff. This bound is
    reserved before dispatch. Actual cost uses provider-reported usage and the served model.
    """
    row = lookup(model_id, catalogue)
    if row is None or row.get('prices_per_million') is None:
        raise ValueError(remedy(model_id, catalogue) if row is None else 'model prices missing: ' + model_id)
    prices = row['prices_per_million']
    context, output = row.get('context_tokens'), row.get('max_output_tokens')
    if type(context) is not int or context <= 0 or type(output) is not int or output <= 0:
        raise ValueError('model context and output limits required: ' + model_id)
    bound = (context * max(prices['input'], prices['cache_write'], prices['cache_read'])
             + output * prices['output']) / 1_000_000
    if not math.isfinite(bound) or bound < 0:
        raise ValueError('model call bound must be finite')
    return {'model': row['id'], 'context_tokens': context, 'max_output_tokens': output,
            'prices_per_million': deepcopy(prices), 'cost_usd': bound,
            'basis': 'catalogue_context_and_output_limits_at_maximum_input_tariff'}


def _preset(preset, catalogue):
    if preset not in catalogue['presets']:
        raise KeyError('unknown preset')
    return catalogue['presets'][preset]


def defaults(family, tier, preset, catalogue=None):
    """Choose by class order and row order, using previews only after all current rows."""
    catalogue = _catalogue(catalogue)
    classes = _preset(preset, catalogue)[tier]
    for status in ('current', 'preview'):
        for class_ in classes:
            for row in catalogue['models']:
                if (row['family'] == family and row['class'] == class_ and row['status'] == status
                        and tier in row['tiers']):
                    return row
    return None


def preset_models(preset, families, catalogue=None):
    """Return available tier defaults per requested family, leaving missing tiers out."""
    catalogue = _catalogue(catalogue)
    _preset(preset, catalogue)
    result = {}
    for family in families:
        result[family] = {}
        for tier in transport_registry.TIERS:
            row = defaults(family, tier, preset, catalogue)
            if row is not None:
                result[family][tier] = row['id']
    return result


def tier_models(preset, transport_documents, catalogue=None):
    """Return transport tier preferences and a reason for every omitted transport/tier.

    Declared tiers and exact ids are preserved. Configured slots use their explicit
    family; an ``any`` slot requires an operator's family choice and is omitted.
    This prepares preferences only; transport qualification remains a separate check.
    """
    catalogue = _catalogue(catalogue)
    _preset(preset, catalogue)
    result = {tier: {} for tier in transport_registry.TIERS}
    omitted = []
    known_families = dict(transport_registry.FAMILY_PATTERNS)
    for document in transport_documents:
        for tier in transport_registry.TIERS:
            entries = [entry for entry in document['models'] if tier in entry['tiers']]
            reason = 'tier:undeclared' if not entries else 'family:unknown'
            for entry in entries:
                if '{configured}' in entry['id']:
                    family = entry['family']
                    if family == 'any' or family not in known_families:
                        continue
                    row = defaults(family, tier, preset, catalogue)
                    model_id = row['id'] if row else None
                else:
                    row = lookup(entry['id'], catalogue)
                    model_id = entry['id'] if row is not None and tier in row['tiers'] else None
                if model_id is not None:
                    result[tier][document['id']] = model_id
                    break
                reason = 'no_catalogue_row' if row is None else 'tier:unsupported'
            else:
                omitted.append({'transport': document['id'], 'tier': tier, 'reason': reason})
    return result, omitted


def adopt(model_id, *, family, class_, tiers, prices_per_million=None, context_tokens=None,
          max_output_tokens=None, released=None, status='current', path=None):
    """Prepend or replace a row in a validated private overlay, writing atomically.

    Unspecified metadata remains null; no provider data is inferred. The explicit
    path or environment selects the destination, otherwise it is under cwd.
    """
    destination = Path(path or os.environ.get(OVERLAY_ENV) or Path.cwd() / _LOCAL_OVERLAY).expanduser().resolve()
    if not _valid_id(model_id):
        _fail('id', 'must be a valid model identifier', model_id)
    if type(family) is not str or family not in dict(transport_registry.FAMILY_PATTERNS):
        _fail('family', 'must name a registered provider family', model_id)
    if destination.exists():
        document = _read(destination)
    else:
        document = load(builtin_only=True)
        document['models'] = []
        document['price_basis'] = 'user-supplied prices per million tokens; unknown prices are not estimated'
    document.pop('origins', None)
    existing = next((row for row in document['models'] if row['id'] == model_id), {})
    row = {**existing, 'id': model_id, 'family': family, 'class': class_,
           'tiers': list(tiers) if type(tiers) in (list, tuple) else tiers,
           'context_tokens': context_tokens, 'max_output_tokens': max_output_tokens,
           'prices_per_million': deepcopy(prices_per_million), 'efforts': existing.get('efforts', []),
           'released': released, 'status': status}
    document['models'] = [row] + [old for old in document['models'] if old['id'] != model_id]
    validate(document)
    # mkdir(parents=True) uses ambient permissions for intermediate parents; create
    # each missing directory explicitly to keep the entire new overlay path private.
    missing = []
    parent = destination.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir(mode=0o700, exist_ok=True)
        parent.chmod(0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                         prefix='.catalogue-', suffix='.json', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def summary(catalogue=None):
    """Return ordered listing rows with source provenance and principal prices."""
    catalogue = _catalogue(catalogue)
    result = []
    for row in catalogue['models']:
        prices = row['prices_per_million'] or {}
        result.append({**{key: deepcopy(row[key]) for key in ('id', 'family', 'class', 'tiers', 'status')},
                       **{key: prices.get(key) for key in ('input', 'output', 'cache_read')},
                       'origin': catalogue.get('origins', {}).get(row['id'], 'builtin')})
    return result


def parser():
    ap = argparse.ArgumentParser(prog='ravel models', description=__doc__)
    subs = ap.add_subparsers(dest='command', required=True)
    listing = subs.add_parser('list', help='list catalogue rows')
    listing.add_argument('--json', action='store_true')
    listing.add_argument('--family')
    subs.add_parser('show', help='show one model and a token price example').add_argument('model')
    detect = subs.add_parser('detect', help='discover models without model calls')
    for flag in ('json', 'adopt', 'yes'):
        detect.add_argument('--' + flag, action='store_true')
    detect.add_argument('--preset', choices=('premium', 'balanced', 'economy'))
    preset = subs.add_parser('preset', help='resolve operator agent preferences')
    preset.add_argument('name', choices=('premium', 'balanced', 'economy'))
    for flag in ('json', 'write'):
        preset.add_argument('--' + flag, action='store_true')
    subs.add_parser('check', help='check operator or frozen run selections').add_argument('--run')
    est = subs.add_parser('estimate', help='estimate typical full-tier run costs')
    est.add_argument('--preset', required=True, choices=('premium', 'balanced', 'economy'))
    est.add_argument('--route')
    est.add_argument('--json', action='store_true')
    subs.add_parser('calibrate', help='delegate to the installed calibration command')
    return ap


def main(argv=None):
    """Run the operator-facing catalogue commands."""
    from .models_cli import main as command
    return command(argv)


if __name__ == '__main__':
    raise SystemExit(main())
