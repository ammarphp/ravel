"""Run-bound admission for direct retrieval and extraction entry points.

All discovered contracts bind independently. No process setting supplies an
exemption. Only contract and provenance metadata are read before source admission.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse

from . import source_policy
from .rdj_custody import TASK_CONTRACT
from .state_io import read_json

VALUE_QUANTITIES = ('value', 'values', 'published-value', 'limit', 'limits', 'yield',
                    'sr-yields', 'cutflow', 'efficiency', 'acceptance', 'acc-eff',
                    'covariance', 'likelihood', 'exclusion-contour', 'edge', 'series')
VALUE_CLASSES = ('published-values', 'tables', 'figures', 'data', 'observed-data',
                 'hepdata', 'likelihood')
FIGURE_CLASSES = ('published-values', 'figures')
TOOL_CLASSES = {'fetch_figures': FIGURE_CLASSES}
METADATA_QUANTITIES = ('text', 'definitions', 'cards', 'object-definitions', 'qualitative')
RECEIPTS = 'logs/source-receipts'


class SourceRestricted(ValueError):
    """A governing contract refused this source; callers must not absorb it as an ordinary error."""


def _physical(path):
    """Resolve symlinks before applying '..', unlike a lexical absolute path."""
    return Path(path).absolute().resolve()


def _ancestors(path):
    for start in (Path(os.path.abspath(path)), _physical(path)):
        yield start
        yield from start.parents


def _contracts(rundir, output):
    found = {}
    for anchor in (rundir, output, Path.cwd()):
        if anchor is None:
            continue
        for root in _ancestors(anchor):
            path = root / TASK_CONTRACT
            try:
                path.lstat()
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError:
                pass  # unreadable candidates still govern and are refused below
            key = (str(root.resolve()), str(path.resolve()))
            found.setdefault(key, (root.resolve(), path))
    return list(found.values())


def _record_ids(record):
    nested = record.get('record') or {}
    ids = {}
    inspire = record.get('inspire') or record.get('inspire_id') or nested.get('inspire_id')
    if inspire is not None:
        ids['inspire'] = [str(inspire) if str(inspire).startswith('ins') else 'ins' + str(inspire)]
    recid = record.get('recid') or nested.get('recid') or record.get('record_ref')
    if recid is not None:
        ids['hepdata'] = [str(recid)]
    return ids


def _url_ids(url):
    parsed = urlparse(url)
    path = parsed.path
    ids = {}
    if parsed.hostname and parsed.hostname.endswith('hepdata.net'):
        match = re.search(r'/record/(?:data/)?(ins\d+|\d+)', path)
        if match:
            value = match[1]
            ids['inspire' if value.startswith('ins') else 'hepdata'] = [value]
    elif parsed.hostname == 'arxiv.org':
        match = re.search(r'/(?:pdf|e-print|abs)/([^/]+)', path)
        if match:
            ids['arxiv'] = [match[1].removesuffix('.pdf')]
    return ids


def _union(*maps):
    """Keep every independently supplied identity; a later map never erases an earlier one."""
    result = {}
    for ids in maps:
        for key, values in ids.items():
            values = values if isinstance(values, list) else [values]
            result[key] = list(dict.fromkeys([*result.get(key, []), *values]))
    return result


def _spellings(key, value):
    """Equivalent spellings of one identity: arXiv versions and zero-padded record numbers."""
    value = str(value)
    forms = {value}
    if key == 'arxiv':
        forms.add(re.sub(r'v\d+$', '', value))
    elif key in ('inspire', 'hepdata'):
        match = re.fullmatch(r'(ins)?0*(\d+)', value)
        if match:
            forms.add((match[1] or '') + match[2])
    return {form for form in forms if form}


def equivalent_identities(identifiers):
    """Expand every identity list with its equivalent spellings, both for rules and sources."""
    if type(identifiers) is not dict:
        return identifiers
    return {key: sorted(set().union(*(_spellings(key, v) for v in values))) if type(values) is list else values
            for key, values in identifiers.items()}


def numeric_quantities(rows):
    """Value quantities, plus every non-metadata quantity a scoped rule names.

    An extraction whose quantities are not resolved in advance is treated as
    extracting any quantity a rule scopes, so an unlisted name never escapes.
    """
    scoped = {q for row in rows for q in (row.get('scope') or {}).get('quantities', [])}
    return list(dict.fromkeys([*VALUE_QUANTITIES, *sorted(scoped - set(METADATA_QUANTITIES))]))


def _descriptor(tool, source, rows):
    result = deepcopy(source) if isinstance(source, dict) else {'path': str(source)}
    unresolved = tool == 'digitize' or 'quantities' not in result
    result.setdefault('classes', list(TOOL_CLASSES.get(tool, VALUE_CLASSES)))
    if tool == 'digitize':
        result['classes'] = list(VALUE_CLASSES)
    if unresolved:
        result['quantities'] = numeric_quantities(rows)
    if 'record' in result:
        result['identifiers'] = _union(_record_ids(result.pop('record')), result.get('identifiers', {}))
    if 'url' in result:
        ids = _union(_url_ids(result['url']), result.get('identifiers', {}))
        result['identifiers'] = ids
        result['identity_unresolved'] = not bool(ids)
    if 'identifiers' in result:
        result['identifiers'] = equivalent_identities(result['identifiers'])
    if 'specification' in result:
        specpath = Path(result.pop('specification')).absolute()
        spec = read_json(specpath)
        specsource = spec.get('source') or {}
        path = Path(specsource['path'])
        result.update({k: v for k, v in specsource.items() if k in ('path', 'page', 'format')})
        result['path'] = str(path if path.is_absolute() else specpath.parent / path)
        result['quantities'] = list(dict.fromkeys([*result['quantities'], *(
            s['kind'] for s in spec.get('series', []) if isinstance(s, dict) and isinstance(s.get('kind'), str))]))
    return result


def _aliases(source, root, seen=()):
    """Resolve filesystem aliases and qualitative-gallery provenance without source IO."""
    descriptor = deepcopy(source)
    path = descriptor.get('path')
    if path is None:
        return [descriptor]
    lexical = Path(os.path.abspath(path))
    resolved = _physical(path)
    if str(resolved) in seen:
        raise ValueError('cyclic qualitative gallery provenance')
    seen = (*seen, str(resolved))
    descriptors = []
    for candidate in (lexical, resolved):
        for base in (root / 'inputs', root):
            if candidate.is_relative_to(base):
                relative = candidate.relative_to(base).as_posix()
                if relative != '.':
                    descriptors.append({**descriptor, 'path': relative})
    # A file outside the run is named only through recorded provenance, never its basename.
    for parent in resolved.parents:
        manifest = parent / 'figure_manifest.json'
        if manifest.is_file():
            doc = read_json(manifest)
            if doc.get('usage') == 'qualitative' and any(
                    (parent / item['path']).resolve() == resolved for item in doc.get('figures', [])):
                original = {**descriptor, **doc['source'], 'quantities': descriptor['quantities']}
                descriptors.extend(_aliases(original, root, seen))
            # A manifest that does not describe this file hides no outer provenance.
        if parent == root:
            break
    return descriptors


def _receipt(root, record):
    folder = root / RECEIPTS
    if not folder.resolve().is_relative_to(root.resolve()):
        raise ValueError('source restriction receipt directory escapes the run')
    folder.mkdir(parents=True, exist_ok=True)
    data = json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + '\n'
    number = 1
    while True:
        path = folder / f'{number}.json'
        try:
            with path.open('x', encoding='utf-8') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return path.resolve()
        except FileExistsError:
            number += 1


def require(tool, source, *, rundir=None, output=None):
    """Refuse and receipt violations of every governing contract before source IO.

    Descriptors carry identities, paths and quantity kinds. An opaque offline
    fixture cannot prove an identity restriction is satisfied without reading its
    source bytes, so it is refused before that read. Metadata and qualitative
    viewing are distinct from extracting values under no-value-extraction rules.
    """
    from ravel.validation import validate_task_contract as contracts
    governing = _contracts(rundir, output)
    if not governing:
        return
    refusals = []
    for root, contractpath in governing:
        candidate = {'tool': tool, 'source': {'descriptor': str(source)}, 'allowed': False,
                     'schema_version': 1, 'contract': str(contractpath)}
        try:
            contract = read_json(contractpath)
            errors = contracts.validate(contract)
            if not errors:
                errors = contracts.validate_pins(root, contract)
            if errors:
                raise ValueError('; '.join(errors))
            rows = source_policy.canonical(contract.get('forbidden_sources', []))
            if not rows:
                continue
            descriptor = _descriptor(tool, source, rows)
            metadata = set(descriptor['quantities']) <= set(METADATA_QUANTITIES)
            declared = [r for r in rows if not (metadata and r['kind'] == 'no-value-extraction')]
            effective = [{**r, 'identifiers': equivalent_identities(r['identifiers'])} if 'identifiers' in r else r
                         for r in declared]
            matches = []
            identity_unresolved = False
            matched_source = descriptor
            for alias in _aliases(descriptor, root):
                try:
                    source_policy.require_read(effective, alias)
                except ValueError:
                    for row in source_policy.matches(effective, alias):
                        row = declared[effective.index(row)]
                        if row not in matches:
                            matches.append(row)
                    matched_source = alias
            for row, spelled in zip(declared, effective):
                identities = spelled.get('identifiers', {})
                unresolved = descriptor.get('identity_unresolved') or (not metadata and any(
                    values and not descriptor.get('identifiers', {}).get(key) for key, values in identities.items()))
                if (unresolved and any(identities.values()) and
                        (not row.get('scope') or set(row['scope']['quantities']) & set(descriptor['quantities']))):
                    identity_unresolved = True
                    if row not in matches:
                        matches.append(row)
            if not matches:
                continue
            candidate.update(source=matched_source, rules=matches,
                             refusal_code='unresolved_source_identity' if identity_unresolved else 'forbidden_source',
                             source_restriction_sha256=source_policy.digest(rows))
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            candidate.update(refusal_code='invalid_governing_contract_or_source', error=str(exc))
        receipt = _receipt(root, candidate)
        names = ', '.join(str(r.get('id', r['kind'])) + ': ' + r['statement'] for r in candidate.get('rules', []))
        refusals.append(f'source restriction {names or candidate.get("error")}; receipt {receipt}')
    if refusals:
        raise SourceRestricted('; '.join(refusals))
