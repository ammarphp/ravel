"""Acknowledgement checks, reviewer items and the closed output schemas of a packet.

Every worker output schema (``producer.v2``, ``findings.v3``) carries
``instruction_ack.manifest_sha256`` and ``checklist[]``, one row per duty unit:
``{unit, status: done | not_applicable | blocked, evidence, note}``, or a compact
``checklist: {schema_version: 1, groups: [{indices, status, evidence, note}]}``.
Indices are zero-based positions in the pinned manifest's complete ``units`` array.
Groups expand to the same per-unit rows; no duty has an implicit status. ``check_ack``
returns one error per fault, each prefixed by its class so a caller can route it:

- ``manifest:`` the acknowledged manifest is not the delivered one;
- ``missing:`` / ``duplicate:`` / ``unknown:`` a duty unit without exactly one row, or a row
  for a unit the manifest does not carry;
- ``status:`` / ``digest:`` a malformed row;
- ``evidence:`` a ``done`` row whose pointer does not resolve to an output written in this
  attempt (or to a field of the final record outside ``checklist`` and ``instruction_ack``);
- ``note:`` a ``not_applicable`` row without a note;
- ``blocked:`` a blocked duty: the step holds with that note.

An empty list means the acknowledgement is complete. Whether the worker obeyed the
instructions stays advisory; the reviewer judges that against ``reviewer_items``.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from urllib.parse import unquote

from ravel.paths import package_data_path
from . import catalogue as _catalogue, compiler
from .custody import current_scope, observed_completion, json_document

STATUSES = ('done', 'not_applicable', 'blocked')
VERDICTS = ('pass', 'fail', 'unresolved')
FINAL_RECORD = 'final_record'
ACKNOWLEDGEMENT = ('checklist', 'instruction_ack')  # never evidence for a row of themselves
OUTPUT_SCHEMAS = {'producer': 'producer.v2', 'findings': 'findings.v3'}


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _path(value: str) -> str:
    value = value.strip().replace('\\', '/')
    while value.startswith('./'):
        value = value[2:]
    return value


def _pointer(document, pointer: str) -> bool:
    """RFC 6901: True when ``pointer`` names a value inside ``document``."""
    if re.search(r'%(?![0-9a-fA-F]{2})', pointer):
        return False
    try:
        pointer = unquote(pointer, errors='strict')
    except UnicodeError:
        return False
    if re.search(r'~(?![01])', pointer):
        return False
    if pointer == '':
        return True
    if not pointer.startswith('/'):
        return False
    node = document
    for token in pointer[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(node):
            node = node[int(token)]
        else:
            return False
    return True


def _evidence_problem(evidence, written: set[str], record: dict) -> str | None:
    if not _text(evidence):
        return 'done without an evidence pointer'
    path, _, pointer = evidence.partition('#')
    path = _path(path)
    scope = current_scope()
    if scope is None:
        return 'no controller-observed completion scope for evidence'
    if path == FINAL_RECORD:
        if not pointer or not _pointer(record, pointer):
            return f'{evidence!r} names no field of the final record'
        if unquote(pointer)[1:].split('/')[0].replace('~1', '/').replace('~0', '~') in ACKNOWLEDGEMENT:
            return f'{evidence!r} points into the acknowledgement, not to evidence'
        return None
    if path not in written:
        return f'{evidence!r} names no output written in this attempt'
    try:
        raw = scope.read(path)
        if pointer and not _pointer(json_document(raw), pointer):
            return f'{evidence!r} names no fragment in the observed artifact'
    except (OSError, ValueError, UnicodeError) as exc:
        return f'{evidence!r}: {exc}'
    return None


def normalise_checklist(manifest: dict, checklist) -> tuple[list, list[str]]:
    """Expand indexed groups without changing the worker's custody-bound final record.

    The manifest pin is still checked by ``check_ack``. Malformed group structure is a
    manifest-level fault so it cannot leave unrelated delivery obligations credited.
    Duplicate indices become duplicate unit rows and face the ordinary duplicate check.
    """
    if isinstance(checklist, list):
        return checklist, []
    if not isinstance(checklist, dict):
        return [], ['manifest: checklist[] is missing']
    if (set(checklist) != {'schema_version', 'groups'}
            or type(checklist.get('schema_version')) is not int or checklist['schema_version'] != 1
            or not isinstance(checklist.get('groups'), list)):
        return [], ['manifest: compact checklist requires schema_version 1 and groups[] only']
    units = manifest.get('units', [])
    indexed, errors = [], []
    for number, group in enumerate(checklist['groups']):
        label = f'manifest: compact checklist group {number}'
        if (not isinstance(group, dict) or set(group) != {'indices', 'status', 'evidence', 'note'}
                or not isinstance(group.get('indices'), list) or not group['indices']):
            errors.append(label + ' requires nonempty indices[], status, evidence and note only')
            continue
        for index in group['indices']:
            if type(index) is not int or not 0 <= index < len(units):
                errors.append(label + f': invalid manifest unit index {index!r}')
                continue
            indexed.append((index, {'unit': units[index]['id'],
                                   **{key: group[key] for key in ('status', 'evidence', 'note')}}))
    return [row for _, row in sorted(indexed, key=lambda pair: pair[0])], errors


def check_ack(manifest: dict, final_record: dict, outputs: list[str]) -> list[str]:
    """Errors in a worker's acknowledgement of the delivered manifest; empty when complete."""
    if not isinstance(final_record, dict):
        return ['manifest: the final record is not an object']
    if not _text(manifest.get('sha256')):
        return ['manifest: instruction_ack.manifest_sha256 is not the delivered manifest digest']
    rows, errors = normalise_checklist(manifest, final_record.get('checklist'))
    scope = current_scope()
    if scope is not None:
        try:
            scope.validate(manifest, final_record)
        except (AttributeError, KeyError, TypeError, OSError, ValueError) as exc:
            return ['manifest: controller completion custody failed: ' + str(exc)]
    ack = final_record.get('instruction_ack')
    delivered = manifest.get('sha256')
    if not _text(delivered) or not isinstance(ack, dict) or ack.get('manifest_sha256') != delivered:
        errors.append('manifest: instruction_ack.manifest_sha256 is not the delivered manifest digest')
    units = {entry['id']: entry for entry in manifest.get('units', [])}
    written = {_path(p) for p in outputs if isinstance(p, str)}
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('unit'), str):
            errors.append(f'status: checklist[{index}]: a row is an object naming its unit')
            continue
        uid = row['unit']
        if uid not in units:
            errors.append(f'unknown: {uid}: not a unit of the delivered manifest')
            continue
        if uid in seen:
            errors.append(f'duplicate: {uid}: more than one checklist row')
            continue
        seen.add(uid)
        if 'sha256' in row and row['sha256'] != units[uid]['sha256']:
            errors.append(f'digest: {uid}: the row names a different unit digest')
        status = row.get('status')
        if status not in STATUSES:
            errors.append(f'status: {uid}: {status!r} is not done, not_applicable or blocked')
        elif status == 'done':
            problem = _evidence_problem(row.get('evidence'), written, final_record)
            if problem:
                errors.append(f'evidence: {uid}: {problem}')
        elif status == 'not_applicable':
            if not _text(row.get('note')):
                errors.append(f'note: {uid}: not_applicable without a note')
        else:
            note = row.get('note')
            errors.append(f'blocked: {uid}: {note.strip() if _text(note) else "blocked without a stated reason"}')
    errors += [f'missing: {uid}: no checklist row for a duty unit'
               for uid, entry in units.items() if entry['kind'] == 'duty' and uid not in seen]
    return errors


def holds(errors: list[str]) -> list[str]:
    """The blocked rows among ``check_ack`` errors: they hold the step rather than fail it."""
    return [e for e in errors if e.startswith('blocked:')]


def reviewer_items(manifest: dict, card: dict | None) -> list[dict]:
    """Items a reviewer must give a verdict on: the reviewer card's must_check entries, then the
    producer manifest's review-required units (census decisions and protocol sentences that name
    an output), each with its exact text."""
    items = []
    if card is not None:
        path = compiler.CARD_PATH.format(role=card['id'])
        items += [{'id': f'must_check:{check}', 'kind': 'must_check', 'check': check,
                   'unit': f'{path}#must_check/{n}', 'source': 'reviewer card'}
                  for n, check in enumerate(card['must_check'])]
    cat = _catalogue.installed()
    for entry in manifest.get('units', []):
        if entry.get('review_required'):
            unit = cat.units[entry['id']]
            items.append({'id': f'unit:{entry["id"]}', 'kind': 'review_required', 'unit': entry['id'],
                          'sha256': entry['sha256'], 'text': unit['text'], 'census': list(unit.get('census', [])),
                          'source': 'producer checklist'})
    return items


def check_item_verdicts(items: list[dict], record: dict) -> list[str]:
    """One verdict with evidence per reviewer item in a ``findings.v3`` record's ``item_verdicts``."""
    rows = record.get('item_verdicts') if isinstance(record, dict) else None
    if not isinstance(rows, list):
        return ['item_verdicts[] is missing']
    wanted, errors, seen = {i['id'] for i in items}, [], set()
    for row in rows:
        item = row.get('item') if isinstance(row, dict) else None
        if item not in wanted:
            errors.append(f'unknown: {item}: not a reviewer item of this review')
        elif item in seen:
            errors.append(f'duplicate: {item}: more than one verdict')
        else:
            seen.add(item)
            if row.get('verdict') not in VERDICTS:
                errors.append(f'status: {item}: verdict is not pass, fail or unresolved')
            elif row['verdict'] != 'unresolved' and not (isinstance(row.get('evidence'), list) and row['evidence']):
                errors.append(f'evidence: {item}: a {row["verdict"]} verdict needs evidence')
            elif row['verdict'] == 'unresolved' and not _text(row.get('note')):
                errors.append(f'note: {item}: an unresolved verdict needs a note')
    errors += [f'missing: {item}: no verdict' for item in sorted(wanted - seen)]
    return errors


def generic_schema(schema_id: str) -> dict:
    return json.loads(package_data_path('roles', 'schema', 'outputs', schema_id + '.json').read_text())


def ack_properties() -> dict:
    """The ``instruction_ack``, ``checklist`` and ``escalation`` property schemas every acknowledging
    output schema carries (``producer.v2``, ``findings.v3`` and the judgment schemas)."""
    props = generic_schema('producer.v2')['properties']
    return {key: deepcopy(props[key]) for key in ('instruction_ack', 'checklist', 'escalation')}


def pin_schema(schema: dict, manifest: dict, card: dict | None) -> dict:
    """A copy of an acknowledging schema pinned to one packet: the manifest digest as a constant, the
    duty units as the only checklist units and their count, and the card's escalation kinds."""
    schema = deepcopy(schema)
    props = schema['properties']
    props['instruction_ack']['properties']['manifest_sha256'] = {'const': manifest['sha256']}
    duty = [e['id'] for e in manifest['units'] if e['kind'] == 'duty']
    checklist = props['checklist']
    checklist['minItems'] = checklist['maxItems'] = len(duty)
    if duty:
        checklist['items']['properties']['unit'] = {'enum': duty}
    compact = checklist.get('properties', {}).get('groups')
    if compact is not None:
        compact['minItems'] = 1 if duty else 0
        compact['maxItems'] = len(duty)
        indices = compact['items']['properties']['indices']
        indices['maxItems'] = len(duty)
        if duty:
            indices['items'] = {'enum': [index for index, entry in enumerate(manifest['units'])
                                       if entry['kind'] == 'duty'], 'type': 'integer'}
    if card is not None:
        props['escalation']['items']['properties']['kind'] = {'enum': list(card['escalation'])}
    return schema


def output_schema(card: dict | None, manifest: dict) -> tuple[str, dict]:
    """The closed output schema of a packet: the card's output family at its acknowledging version
    (``producer.v2`` or ``findings.v3``), pinned to the packet, with the card's finding version."""
    declared = card['output']['schema'] if card is not None else 'producer.v1'
    family, _, version = declared.rpartition('.v')
    schema_id = OUTPUT_SCHEMAS.get(family)
    if schema_id is None:
        raise ValueError(f'no acknowledging output schema for {declared}')
    schema = pin_schema(generic_schema(schema_id), manifest, card)
    if schema_id == 'findings.v3':
        variants = schema['properties']['items']['items']['anyOf']
        schema['properties']['items']['items'] = variants[0] if version == '1' else variants[1]
    return schema_id, schema


def validate_record(schema_id: str, record: dict) -> list[str]:
    """JSON-schema errors of a final record against a generic acknowledging schema; finding items
    of a ``findings.v3`` record also pass the finding-classification rules of version 2."""
    from jsonschema import Draft202012Validator
    errors = [('/'.join(str(p) for p in e.absolute_path) or '$') + ': ' + e.message
              for e in Draft202012Validator(generic_schema(schema_id)).iter_errors(record)]
    if not errors and schema_id == 'findings.v3':
        from ravel.workflow import finding_routing
        for item in record['items']:
            try:
                finding_routing.validate(item)
            except ValueError as exc:
                errors.append(str(exc))
    return errors
