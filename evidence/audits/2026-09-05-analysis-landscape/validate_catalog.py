#!/usr/bin/env python3
"""Validate this dated survey's evidence consistency; does not certify physics."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import sys


def validate(base: Path) -> dict:
    errors = []
    def read(name):
        try:
            return json.loads((base / name).read_text())
        except (OSError, ValueError) as exc:
            errors.append(f'{name}: {exc}')
            return None
    census = read('candidate-census.json')
    source_doc = read('sources.json')
    pin_doc = read('repository-pins.json')
    fetches = read('metadata-fetches.json')
    index = read('public-models-metadata.json')
    if any(x is None for x in (census, source_doc, pin_doc, fetches, index)):
        return {'status': 'FAIL', 'errors': errors}
    sources = source_doc.get('sources', [])
    source_ids = [s.get('id') for s in sources]
    if len(set(source_ids)) != len(source_ids):
        errors.append('duplicate source IDs')
    for source in sources:
        if not str(source.get('url', '')).startswith('https://'):
            errors.append(f'invalid source URL: {source.get("id")}')
    rows = census.get('curated_candidates', [])
    row_ids = [r.get('id') for r in rows]
    if len(set(row_ids)) != len(row_ids):
        errors.append('duplicate candidate IDs')
    if len(rows) != 26:
        errors.append('dated curated census must retain 26 rows')
    if len(index) != 45 or census.get('index_metadata', {}).get('count') != len(index):
        errors.append('index count mismatch')
    if census.get('index_metadata', {}).get('execution_tier') != 'E0':
        errors.append('discovery snapshot cannot imply executable admission')
    for row in rows:
        rid = row.get('id')
        if row.get('execution_tier') not in census.get('execution_tiers', {}):
            errors.append(f'{rid}: undeclared execution tier')
        for field in ('model_limitations', 'detector_limitations', 'statistical_limitations', 'admission_evidence_required', 'missing_or_unverified_artifacts'):
            value = row.get(field)
            if not isinstance(value, list) or not value or not all(isinstance(x, str) and x.strip() for x in value):
                errors.append(f'{rid}: missing {field}')
        validation = row.get('validation', {})
        if validation.get('status') != 'candidate' or validation.get('validated_by_this_survey') is not False:
            errors.append(f'{rid}: unsupported validation promotion in dated survey')
        for field in ('numerical', 'central_value', 'detector_and_model', 'coverage'):
            if validation.get(field) != 'not_assessed':
                errors.append(f'{rid}: unsupported {field} validation')
        if row.get('ravel_ready_to_execute') is not False:
            errors.append(f'{rid}: contradictory execution admission')
        refs = list(row.get('source_ids', []))
        if not refs:
            errors.append(f'{rid}: missing sources')
        for artifact in row.get('available_artifacts', []):
            if artifact.get('availability') not in census.get('artifact_availability_levels', {}):
                errors.append(f'{rid}: undeclared artifact availability')
            if not artifact.get('source_ids'):
                errors.append(f'{rid}: unsourced artifact')
            refs.extend(artifact.get('source_ids', []))
        for ref in refs:
            if ref not in source_ids:
                errors.append(f'{rid}: unknown source {ref}')
        aid = row.get('index_analysis_id')
        if aid:
            matching = [x for x in index if x.get('link', '').rstrip('/').endswith('/' + aid)]
            if len(matching) != 1:
                errors.append(f'{rid}: ambiguous or absent index analysis {aid}')
            elif (row.get('publication_url') != matching[0]['link'] or row.get('data_record_url') != matching[0]['hepdata'].rstrip('?')):
                errors.append(f'{rid}: publication/data identity mismatch')
    repositories = pin_doc.get('repositories', [])
    pinned = 0
    for item in repositories:
        if item.get('status') == 'pinned':
            pinned += 1
            if not re.fullmatch(r'[0-9a-f]{40}', str(item.get('commit', ''))):
                errors.append(f'invalid repository pin: {item.get("name")}')
        elif item.get('commit') or not item.get('error'):
            errors.append(f'failed pin is not explicit: {item.get("name")}')
    if pinned != 16:
        errors.append('dated successful repository pin count mismatch')
    for fetched in fetches:
        if fetched.get('status') == 200:
            path = base / fetched.get('saved', '')
            if path.parent.resolve() != base.resolve():
                errors.append('saved metadata path outside evidence directory')
                continue
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != fetched.get('saved_sha256'):
                errors.append(f'saved metadata hash mismatch: {fetched.get("id")}')
            if not re.fullmatch(r'[0-9a-f]{64}', str(fetched.get('response_sha256', ''))):
                errors.append(f'missing response identity: {fetched.get("id")}')
        elif fetched.get('status') != 'fetch_failed' or not fetched.get('error'):
            errors.append(f'unknown retrieval state: {fetched.get("id")}')
    return {'status': 'FAIL' if errors else 'PASS', 'errors': errors,
            'curated_candidates': len(rows), 'discovery_index_entries': len(index),
            'sources': len(sources), 'successful_repository_pins': pinned,
            'new_scientific_validations': 0,
            'scope': 'Dated survey integrity only; external executions and scientific validity not tested.'}


if __name__ == '__main__':
    result = validate(Path(__file__).resolve().parent)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['status'] == 'PASS' else 1)
