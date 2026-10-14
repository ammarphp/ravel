"""Exact source/resource discovery from a caller-supplied pinned landscape.

The release does not bundle research archives. A manifest binds external JSON
artifacts by byte count and SHA256. Discovery and source-capsule seeds neither
admit execution nor establish scientific coverage or a complete LHC denominator.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re

from ravel import analysis_sources

KINDS = {'atlas', 'capsules', 'resources', 'native_records', 'native_contracts', 'measurements'}
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON object key: ' + key)
        result[key] = value
    return result


def _json(raw):
    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            raise ValueError('nonfinite JSON number')
        return value
    try:
        return json.loads(raw, object_pairs_hook=_object,
                          parse_float=finite_float,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON number')))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('landscape artifact must be finite UTF-8 JSON') from exc


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('landscape requires exact lowercase SHA256')


def _count(value):
    return type(value) is int and value >= 0


def _tokens(row, native=False):
    if native:
        return ({row['record_id']} | set(row.get('cms_analysis_ids', []))
                | set(row.get('analysis_inspire_ids', [])) | set(row.get('analysis_arxiv_ids', []))
                | {'ins' + str(x) for x in row.get('analysis_inspire_ids', [])}
                | {'arXiv:' + x for x in row.get('analysis_arxiv_ids', [])})
    identity = row['identity']
    return ({row['routine_id'], row['name']} | set(identity.get('analysis_ids', []))
            | set(identity.get('primary_inspire_ids', [])) | set(identity.get('official_arxiv_ids', []))
            | {'ins' + str(x) for x in identity.get('primary_inspire_ids', [])}
            | {'arXiv:' + x for x in identity.get('official_arxiv_ids', [])})


class Landscape:
    """Loaded, byte-pinned external evidence; optional artifacts load on demand."""

    def __init__(self, manifest_path, manifest, manifest_sha256):
        self.path = manifest_path
        self._manifest = manifest
        self.manifest_sha256 = manifest_sha256
        self._documents = {}
        atlas = self._read('atlas')
        if not isinstance(atlas, dict) or (type(atlas.get('schema_version')) is not int or atlas.get('schema_version') != 1) or not isinstance(atlas.get('routines'), list):
            raise ValueError('landscape atlas requires schema 1 and explicit routines')
        if atlas.get('source_scope') != manifest['source_scope']:
            raise ValueError('landscape source scope differs from manifest')
        self._rows = {}
        self._index = {}
        for row in atlas['routines']:
            if not isinstance(row, dict) or not isinstance(row.get('routine_id'), str) or row['routine_id'] in self._rows:
                raise ValueError('landscape duplicate or invalid routine identity')
            if (row.get('framework') not in ('rivet', 'simpleanalysis', 'cpp')
                    or not isinstance(row.get('name'), str)
                    or row['routine_id'] != row['framework'] + ':' + row['name']
                    or type(row.get('eligible_implementation')) is not bool
                    or not isinstance(row.get('identity'), dict)
                    or not isinstance(row.get('source_files'), list)):
                raise ValueError('landscape routine framework/name/eligibility/source fields invalid')
            for key in ('analysis_ids', 'primary_inspire_ids', 'official_arxiv_ids'):
                if not isinstance(row['identity'].get(key, []), list) or any(not isinstance(x, str) or not x for x in row['identity'].get(key, [])):
                    raise ValueError('landscape exact identifiers must be nonempty strings')
            if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*', row['name']):
                raise ValueError('landscape routine name invalid')
            source_paths = set()
            for fact in row['source_files']:
                if not isinstance(fact, dict) or 'path' not in fact or 'sha256' not in fact:
                    raise ValueError('landscape routine source needs path and SHA256')
                analysis_sources.relative_path(fact['path']); _sha(fact['sha256'])
                if fact['path'] in source_paths:
                    raise ValueError('landscape routine source path repeated')
                source_paths.add(fact['path'])
            if row['framework'] not in manifest['source_scope']:
                raise ValueError('routine framework is absent from source scope')
            self._rows[row['routine_id']] = row
            for token in _tokens(row):
                self._index.setdefault(token, []).append(row['routine_id'])
        population = manifest['population']
        if (len(self._rows) != population['raw_rows']
                or sum(row['eligible_implementation'] for row in self._rows.values()) != population['eligible_rows']):
            raise ValueError('landscape row population differs from manifest')
        self._rows = dict(sorted(self._rows.items()))

    def _read(self, kind):
        if kind not in self._manifest['artifacts']:
            return None
        if kind not in self._documents:
            fact = self._manifest['artifacts'][kind]
            path = self.path.parent / fact['path']
            if (not path.is_file() or not path.resolve().is_relative_to(self.path.parent)
                    or any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(self.path.parent))):
                raise ValueError('landscape artifact missing, linked or outside manifest root: ' + kind)
            if path.stat().st_size != fact['bytes']:
                raise ValueError('landscape artifact byte count differs: ' + kind)
            raw = path.read_bytes()
            if len(raw) != fact['bytes'] or hashlib.sha256(raw).hexdigest() != fact['sha256']:
                raise ValueError('landscape artifact SHA256 differs: ' + kind)
            self._documents[kind] = _json(raw)
        return self._documents[kind]

    def _records(self, kind, field):
        doc = self._read(kind)
        if doc is None:
            return []
        if not isinstance(doc, dict) or (type(doc.get('schema_version')) is not int or doc.get('schema_version') != 1) or not isinstance(doc.get(field), list):
            raise ValueError('landscape artifact requires schema 1 and ' + field + ': ' + kind)
        records = doc[field]
        key = 'record_id' if kind in ('native_records', 'native_contracts') else 'routine_id'
        if any(not isinstance(r, dict) or not isinstance(r.get(key), str) or not r[key] for r in records) or len({r[key] for r in records}) != len(records):
            raise ValueError('landscape artifact has duplicate or invalid record identities: ' + kind)
        if kind == 'native_records':
            for record in records:
                for field in ('cms_analysis_ids', 'analysis_inspire_ids', 'analysis_arxiv_ids'):
                    values = record.get(field, [])
                    if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values):
                        raise ValueError('landscape native exact identifiers must be nonempty strings in lists')
        if kind == 'resources':
            if type(doc.get('recovery_population_complete', False)) is not bool:
                raise ValueError('landscape resource recovery completeness must be boolean')
            if any(not isinstance(r.get('exact_hepdata_metadata_matches', []), list) for r in records):
                raise ValueError('landscape exact resource matches must be explicit lists')
        return records

    def summary(self):
        resources = self._read('resources')
        result = {'schema_version': 1, 'kind': 'analysis-coverage-landscape-summary',
                  'manifest_sha256': self.manifest_sha256, 'source_scope': copy.deepcopy(self._manifest['source_scope']),
                  'population': copy.deepcopy(self._manifest['population']),
                  'source_framework_rows': {framework: sum(r['framework'] == framework and r['eligible_implementation'] for r in self._rows.values())
                                            for framework in sorted({r['framework'] for r in self._rows.values()})},
                  'all_lhc_paper_census_complete': False, 'complete_scientific_tasks_from_discovery': 0,
                  'execution_admitted': False, 'physics_coverage_claim': False}
        if resources is not None:
            self._records('resources', 'routines')
            result['resource_population_complete'] = resources.get('recovery_population_complete', False)
            result['eligible_exact_metadata_join_rows'] = sum(bool(r.get('exact_hepdata_metadata_matches'))
                for r in resources['routines'] if r.get('routine_id') in self._rows and self._rows[r['routine_id']]['eligible_implementation'])
        return result

    def intake(self, identifier, objective='prediction'):
        if not isinstance(identifier, str) or not identifier:
            raise ValueError('exact landscape identifier required')
        if objective not in ('prediction', 'measurement', 'exclusion'):
            raise ValueError('landscape objective must be prediction, measurement or exclusion')
        rows = [self._rows[key] for key in self._index.get(identifier, [])]
        native = [r for r in self._records('native_records', 'records') if identifier in _tokens(r, native=True)]
        selected = {r['routine_id'] for r in rows}
        resource_ids = {r['record_id'] for r in native}
        if objective == 'measurement':
            obligations = ['Exact experimental covariance and bin/unit/normalization basis',
                           'SM plus new-model prediction and declared theory uncertainty policy',
                           'Source applicability, overlap and inferential calibration']
        elif objective == 'exclusion':
            obligations = ['Complete original likelihood and observed/expected convention',
                           'Signal and every required variation in all affected SR/CR',
                           'Native nuisance/finite-MC semantics and independent fit/coverage validation']
        else:
            obligations = ['Supplied event/detector and generator normalization contract',
                           'Complete instantiated outputs and independent source/runtime comparison']
        result = {'schema_version': 1, 'kind': 'analysis-coverage-landscape-intake',
                  'identifier': identifier, 'objective': objective,
                  'resolution': 'exact_multiple_routines_select_scope' if len(rows) > 1 else 'exact_routine' if rows else 'exact_resource_only' if native else 'unknown_identifier',
                  'manifest_sha256': self.manifest_sha256, 'source_scope': copy.deepcopy(self._manifest['source_scope']),
                  'population': copy.deepcopy(self._manifest['population']),
                  'routines': rows, 'native_resource_candidates': native,
                  'objective_requirements': obligations,
                  'resource_semantic_evidence': [r for r in self._records('resources', 'routines') if r.get('routine_id') in selected],
                  'native_source_contracts': [r for r in self._records('native_contracts', 'records') if r.get('record_id') in resource_ids],
                  'actual_measurement_source_contracts': [r for r in self._records('measurements', 'records') if r.get('routine_id') in selected],
                  'artifact_bindings': self._manifest['artifacts'],
                  'verified_loaded_artifacts': sorted(self._documents),
                  'all_lhc_paper_census_complete': False, 'execution_admitted': False, 'physics_coverage_claim': False,
                  'next_action': 'Bind exact sources/output/model and discharge source, runtime, detector and statistical obligations.'}
        return copy.deepcopy(result)

    def capsule(self, identifier, source_root):
        """Verify retained source bytes and return a normal incomplete review seed."""
        matches = self._index.get(identifier, [])
        if len(matches) != 1:
            raise ValueError('source capsule requires exactly one resolved routine')
        row = self._rows[matches[0]]
        if not row['eligible_implementation']:
            raise ValueError('source capsule cannot seed an explicitly excluded implementation')
        seeds = [r for r in self._records('capsules', 'records') if r.get('routine_id') == row['routine_id']]
        if len(seeds) != 1 or set(seeds[0]) not in ({'routine_id', 'capsule'}, {'routine_id', 'capsule', 'file_ids'}):
            raise ValueError('source capsule inventory unavailable or ambiguous for routine')
        seed = copy.deepcopy(seeds[0]['capsule'])
        if not isinstance(seed, dict):
            raise ValueError('landscape capsule must be an object')
        if 'file_ids' in seeds[0]:
            ids = seeds[0]['file_ids']; pool = self._read('capsules').get('file_facts')
            if (not isinstance(ids, list) or not isinstance(pool, dict) or not ids
                    or any(not isinstance(key, str) or key not in pool for key in ids)
                    or len(set(ids)) != len(ids) or seed.get('files') != []):
                raise ValueError('landscape capsule file references incomplete or duplicated')
            seed['files'] = [copy.deepcopy(pool[key]) for key in ids]
            if any(not isinstance(f, dict) or set(f) != {'path', 'sha256', 'role'} for f in seed['files']):
                raise ValueError('landscape capsule pooled file fact requires path, SHA256 and role')
            if not isinstance(seed.get('dependencies'), list):
                raise ValueError('landscape capsule dependencies must be a list')
            headers = [f['path'] for f in seed['files'] if f.get('role') == 'header']
            assets = [f['path'] for f in seed['files'] if f.get('role') in ('model', 'preprocessing', 'data', 'reference')]
            for name, kind, files in [('lexically resolved internal headers', 'source', headers), ('declared source assets and references', 'asset', assets)]:
                if files:
                    seed['dependencies'].append({'name': name, 'kind': kind, 'status': 'resolved', 'files': files,
                        'reason': 'Pinned retained file bytes; native/dynamic/scientific closure remains unresolved.'})
        analysis_sources.validate_capsule(seed)
        if (seed['framework'] != row['framework'] or seed['routine'] != row['name']
                or seed['dependency_review']['complete']
                or not any(d['status'] == 'unresolved' for d in seed['dependencies'])):
            raise ValueError('landscape capsule must be the matching incomplete dependency review seed')
        pin = self._manifest['source_scope'][row['framework']]
        if any(seed['source'][k] != pin[k] for k in ('repository', 'revision')):
            raise ValueError('landscape capsule source identity differs from manifest')
        if any(sub not in pin['submodules'] for sub in seed['submodules']):
            raise ValueError('landscape capsule submodule identity differs from manifest')
        facts = {f['path']: f for f in seed['files']}
        if not row['source_files'] or any(f['path'] not in facts or facts[f['path']]['sha256'] != f['sha256'] or facts[f['path']]['role'] != 'compile' for f in row['source_files']):
            raise ValueError('landscape capsule compile source differs from pinned routine')
        root = Path(source_root).absolute()
        seed['root'] = str(root)
        analysis_sources.source_files(seed, root.parent)
        return seed


def load_landscape(manifest_path, *, expected_sha256=None):
    """Load a local manifest; no fetch, imports of supplied code, compiler or fit."""
    candidate = Path(manifest_path).absolute()
    if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 1_000_000:
        raise ValueError('ordinary landscape manifest required, at most 1 MB')
    raw = candidate.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        _sha(expected_sha256)
        if digest != expected_sha256:
            raise ValueError('landscape manifest SHA256 differs')
    manifest = _json(raw)
    required = {'schema_version', 'kind', 'source_scope', 'population', 'artifacts'}
    if (not isinstance(manifest, dict) or set(manifest) != required
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
            or manifest['kind'] != 'analysis-coverage-landscape'
            or not isinstance(manifest['source_scope'], dict) or not manifest['source_scope']
            or not isinstance(manifest['artifacts'], dict)
            or not manifest['artifacts'] or 'atlas' not in manifest['artifacts']
            or set(manifest['artifacts']) - KINDS):
        raise ValueError('invalid analysis-coverage-landscape/v1 manifest fields')
    for framework, pin in manifest['source_scope'].items():
        if (framework not in ('rivet', 'simpleanalysis', 'cpp') or not isinstance(pin, dict)
                or set(pin) != {'repository', 'revision', 'submodules'} or not isinstance(pin['submodules'], list)):
            raise ValueError('landscape source scope requires exact framework repository/revision/submodules')
        source = {'repository': pin['repository'], 'revision': pin['revision'], 'description': 'External landscape source identity assertion'}
        if source['repository'] == 'supplied':
            if source['revision'] is not None:
                raise ValueError('supplied landscape source cannot assert Git revision')
        elif (not isinstance(source['repository'], str) or not source['repository'].startswith('https://')
                or not isinstance(source['revision'], str) or not re.fullmatch('[0-9a-f]{40}', source['revision'])):
            raise ValueError('landscape source requires HTTPS repository and exact commit')
        seen = set()
        for sub in pin['submodules']:
            if not isinstance(sub, dict) or set(sub) != {'path', 'repository', 'revision'}:
                raise ValueError('landscape submodule identity invalid')
            analysis_sources.relative_path(sub['path'])
            if (sub['path'] in seen or not isinstance(sub['repository'], str) or not sub['repository'].startswith('https://')
                    or not isinstance(sub['revision'], str) or not re.fullmatch('[0-9a-f]{40}', sub['revision'])):
                raise ValueError('landscape submodule requires unique path and exact source pin')
            seen.add(sub['path'])
    population = manifest['population']
    if (not isinstance(population, dict) or set(population) != {'raw_rows', 'eligible_rows', 'all_lhc_paper_census_complete'}
            or not _count(population['raw_rows']) or not _count(population['eligible_rows'])
            or population['eligible_rows'] > population['raw_rows']
            or population['all_lhc_paper_census_complete'] is not False):
        raise ValueError('explicit source population required; all-LHC coverage remains unknown')
    paths, total = set(), 0
    for fact in manifest['artifacts'].values():
        if not isinstance(fact, dict) or set(fact) != {'path', 'sha256', 'bytes'}:
            raise ValueError('landscape artifact needs path, SHA256 and bytes')
        analysis_sources.relative_path(fact['path']); _sha(fact['sha256'])
        if fact['path'] in paths or type(fact['bytes']) is not int or not 0 < fact['bytes'] <= MAX_ARTIFACT_BYTES:
            raise ValueError('duplicate artifact path or invalid landscape byte budget')
        paths.add(fact['path']); total += fact['bytes']
    if total > MAX_TOTAL_BYTES:
        raise ValueError('landscape total declared byte budget exceeded')
    return Landscape(candidate.resolve(), manifest, digest)
