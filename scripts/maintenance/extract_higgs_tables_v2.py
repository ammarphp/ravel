"""Assemble supplied reviewed extraction records; no PDF parsing or acquisition.

Inputs supply all processes, masses, energies, stages, citations and printed lines.
This script preserves inherited rows and stamps its own digest on additions.
A human or independent extraction job must check the records against primary bytes.

PYTHONPATH=src python scripts/maintenance/extract_higgs_tables_v2.py \
    --base /cache/base.json --additions /cache/reviewed.json --output /cache/tables.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from ravel.validation.constants_manifest import ConstantsError, check_higgs_tables


def digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def assemble(base, additions):
    """Preserve a supplied v1 document and append supplied reviewed v2 records."""
    if base.get('schema_version') != 1 or check_higgs_tables(base):
        raise ConstantsError('valid version 1 base required')
    if not isinstance(additions, dict) or set(additions) != {'citations', 'rows', 'ratios'}:
        raise ConstantsError('additions require citations, rows and ratios only')
    if (not isinstance(additions['citations'], dict) or not isinstance(additions['rows'], list)
            or not isinstance(additions['ratios'], list)):
        raise ConstantsError('additions require citation mapping and row lists')
    document = copy.deepcopy(base)
    document['schema_version'] = 2
    for section in ('rows', 'ratios'):
        document['legacy_' + section + '_sha256'] = {row['id']: digest(row) for row in base[section]}
    for key, citation in additions['citations'].items():
        if key in document['citations'] and citation != document['citations'][key]:
            raise ConstantsError('cannot replace inherited citation: ' + key)
        document['citations'][key] = copy.deepcopy(citation)
    script_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for row in copy.deepcopy(additions['rows']):
        if not isinstance(row, dict) or not isinstance(row.get('locator'), dict):
            raise ConstantsError('new row requires reviewed locator')
        row['locator']['extraction_script_sha256'] = script_digest
        document['rows'].append(row)
    document['ratios'].extend(copy.deepcopy(additions['ratios']))
    findings = check_higgs_tables(document)
    if findings:
        raise ConstantsError('invalid assembled tables: ' + json.dumps(findings, allow_nan=False))
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--additions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    document = assemble(json.loads(args.base.read_bytes()), json.loads(args.additions.read_bytes()))
    # Exclusive creation protects both inherited inputs and existing extraction records.
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(document, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'rows': len(document['rows']), 'ratios': len(document['ratios'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
