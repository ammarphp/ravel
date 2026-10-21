"""The obligation catalogue (CONTROLLER-SPEC 7.1): read-only package data.

``scripts/maintenance/build_obligation_catalogue.py`` compiles it from the census and the coverage table. Only the
installed copy is read: never a file in a run tree, the working directory or an environment-selected path. A run
pins the catalogue digest at intake; every later ledger operation refuses a catalogue with a different digest.
Rows are returned as immutable mappings.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
import re
from types import MappingProxyType
from typing import Mapping

RESOURCE = 'data/obligations/catalogue.json'
SCHEMA = 'obligation-catalogue.v1'
STAGES = ('intake', 'plan', 'seat', 'review', 'deliver', 'event')
SCOPES = ('run', 'deliverable', 'step', 'waypoint', 'point', 'seat', 'artifact', 'event')
STAGE_SCOPES = {
    'intake': ('run', 'deliverable'),
    'plan': ('run', 'step', 'waypoint', 'point'),
    'seat': ('seat',),
    'review': ('seat',),
    'deliver': ('run', 'artifact'),
    'event': ('event',),
}
CLASSES = ('E', 'L', 'R', 'I')
LEDGER_CLASSES = ('route', 'role/instruction', 'delegation/independence', 'authority/approval', 'execution/tool',
                  'review/credit', 'delivery/claims', 'budget/stop')
WAIVABILITY = ('authority', 'diagnostic', 'never')
WAIVERS = ('authority', 'scope', 'statistic', 'budget')
SELECT_KEYS = frozenset({'route', 'task_mode', 'operation', 'mode', 'workflow_step', 'research_stage', 'checkin',
                         'gate', 'role', 'document', 'seat_kind', 'review_kind', 'step_kind', 'has_step_kind',
                         'points', 'launches', 'rung', 'wms'})
ROW_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
MECHANISM = re.compile(r'^M(0[1-9]|1[0-9]|2[0-9])$')


class CatalogueError(ValueError):
    """The installed catalogue is absent, malformed or not the one the run pinned."""


@dataclass(frozen=True)
class Catalogue:
    sha256: str
    rows: Mapping[str, Mapping]
    order: tuple[str, ...]
    by_stage: Mapping[str, tuple[str, ...]]
    gate_registry: Mapping
    counts: Mapping

    def row(self, row_id: str) -> Mapping:
        try:
            return self.rows[row_id]
        except KeyError:
            raise CatalogueError(f'obligation {row_id} is not in the installed catalogue') from None


def _resource():
    return files('ravel').joinpath(RESOURCE)


def _bytes() -> bytes:
    return _resource().read_bytes()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _validate_row(row) -> None:
    if not isinstance(row, dict):
        raise CatalogueError('a catalogue row is not an object')
    rid = row.get('id')
    if not isinstance(rid, str) or not ROW_ID.match(rid):
        raise CatalogueError(f'catalogue row id {rid!r} is invalid')
    if row.get('class') not in CLASSES:
        raise CatalogueError(f'{rid}: class {row.get("class")!r} is not one of {CLASSES}')
    if row.get('ledger_class') not in LEDGER_CLASSES:
        raise CatalogueError(f'{rid}: ledger class {row.get("ledger_class")!r} is unknown')
    mechanisms = row.get('mechanisms')
    if not isinstance(mechanisms, list) or not mechanisms or not all(
            isinstance(m, str) and MECHANISM.match(m) for m in mechanisms):
        raise CatalogueError(f'{rid}: mechanisms {mechanisms!r} are invalid')
    if not isinstance(row.get('node'), str) or not row['node']:
        raise CatalogueError(f'{rid}: no discharging node')
    if row.get('waivability') not in WAIVABILITY:
        raise CatalogueError(f'{rid}: waivability {row.get("waivability")!r} is unknown')
    if row['waivability'] == 'authority' and row.get('waiver') not in WAIVERS:
        raise CatalogueError(f'{rid}: a waivable row names no waiver kind')
    applicability = row.get('applicability')
    if not isinstance(applicability, dict):
        raise CatalogueError(f'{rid}: no applicability')
    stage, scope = applicability.get('stage'), applicability.get('scope')
    if stage not in STAGES or scope not in STAGE_SCOPES[stage]:
        raise CatalogueError(f'{rid}: stage {stage!r} with scope {scope!r} is not allowed')
    select = applicability.get('select', {})
    if not isinstance(select, dict) or set(select) - SELECT_KEYS:
        raise CatalogueError(f'{rid}: unknown selector keys {sorted(set(select) - SELECT_KEYS)}')


def parse(data: bytes) -> Catalogue:
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogueError(f'the obligation catalogue is not JSON: {exc}') from None
    if not isinstance(document, dict) or document.get('schema') != SCHEMA:
        raise CatalogueError(f'the obligation catalogue is not an {SCHEMA} document')
    rows = document.get('rows')
    if not isinstance(rows, list) or not rows:
        raise CatalogueError('the obligation catalogue has no rows')
    index, by_stage = {}, {stage: [] for stage in STAGES}
    for row in rows:
        _validate_row(row)
        if row['id'] in index:
            raise CatalogueError(f'the obligation catalogue repeats {row["id"]}')
        index[row['id']] = _freeze(row)
        by_stage[row['applicability']['stage']].append(row['id'])
    registry = document.get('gate_registry')
    if not isinstance(registry, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(registry.get('sha256', ''))):
        raise CatalogueError('the obligation catalogue pins no decision-gate provider registry')
    return Catalogue(sha256=hashlib.sha256(data).hexdigest(), rows=MappingProxyType(index),
                     order=tuple(r['id'] for r in rows),
                     by_stage=MappingProxyType({k: tuple(v) for k, v in by_stage.items()}),
                     gate_registry=_freeze(registry), counts=_freeze(document.get('counts') or {}))


_CACHE: dict[str, Catalogue] = {}
_STAT: dict[tuple, str] = {}


def _stat_key():
    """The installed file's identity, or None where the resource is not a plain file (a zipped install)."""
    resource = _resource()
    stat = getattr(resource, 'stat', None)
    if stat is None:
        return None
    try:
        st = stat()
    except OSError:
        return None
    return (str(resource), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def load() -> Catalogue:
    """The installed catalogue, parsed once per distinct content.

    A file whose identity (device, inode, size, modification time) is unchanged is not re-read; any change makes
    the next call read and digest it again, so a run's pin check sees the changed content.
    """
    key = _stat_key() if _bytes is _INSTALLED_BYTES else None
    if key is not None and _STAT.get(key) in _CACHE:
        return _CACHE[_STAT[key]]
    try:
        data = _bytes()
    except OSError as exc:
        raise CatalogueError(f'the installed obligation catalogue cannot be read: {exc}') from None
    digest = hashlib.sha256(data).hexdigest()
    cached = _CACHE.get(digest)
    if cached is None:
        cached = _CACHE[digest] = parse(data)
    if key is not None:
        _STAT[key] = digest
    return cached


_INSTALLED_BYTES = _bytes
