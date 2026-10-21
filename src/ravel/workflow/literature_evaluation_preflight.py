"""Read-only preflight of a declared literature evaluation membership against a pinned index.

An evaluation declares which documents (with exact versions) it covers, the coordinate system
its located answers use, the corpus and index manifest digests it was prepared against, and
whether its gold answers are frozen. Before any evaluated run, this preflight compares that
declaration with one admitted index snapshot and names every reason it cannot proceed. It reads
only the membership document and the snapshot it is given: no evaluation content, gold answers,
corpus sources, model or network. It never tunes, edits or selects anything; passing establishes
neither retrieval quality nor provider qualification, both of which stay external prerequisites.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

KIND = 'literature-evaluation-membership'
REPORT_KIND = 'literature-evaluation-preflight'
# Declared coordinate systems and the located-evidence spaces each admits.
COORDINATES = {'member-lines': ('original-text', 'extracted-text'), 'pdf-pages': ('pdf-page-text',)}
MAX_DOCUMENTS = 10000
MAX_BYTES = 8 * 1024 * 1024
_HEX = re.compile(r'[0-9a-f]{64}')
KEYS = {'schema_version', 'kind', 'coordinates', 'corpus_sha256', 'index_manifest_sha256', 'gold', 'documents'}


def _text(value, limit=512):
    return type(value) is str and 0 < len(value) <= limit


def _shape(membership):
    """Problems with the declaration's closed shape (empty when it is well formed)."""
    if type(membership) is not dict or set(membership) != KEYS:
        return ['the membership document must hold exactly ' + ', '.join(sorted(KEYS))]
    problems = []
    if type(membership['schema_version']) is not int or membership['schema_version'] != 1 or membership['kind'] != KIND:
        problems.append(f'schema_version 1 and kind {KIND} required')
    if membership['coordinates'] not in COORDINATES:
        problems.append('coordinates must be one of ' + ', '.join(COORDINATES))
    for key in ('corpus_sha256', 'index_manifest_sha256'):
        if type(membership[key]) is not str or not _HEX.fullmatch(membership[key]):
            problems.append(key + ' must be a sha256 hex digest')
    gold = membership['gold']
    if (type(gold) is not dict or set(gold) != {'frozen', 'sha256'} or type(gold['frozen']) is not bool
            or not (gold['sha256'] is None or type(gold['sha256']) is str and _HEX.fullmatch(gold['sha256']))):
        problems.append('gold must be {frozen: boolean, sha256: digest or null}')
    documents = membership['documents']
    if (type(documents) is not list or not 0 < len(documents) <= MAX_DOCUMENTS
            or any(type(d) is not dict or set(d) != {'document_id', 'version'}
                   or not _text(d['document_id']) or not _text(d['version'], 128) for d in documents)):
        problems.append('documents must be a nonempty list of {document_id, version}')
    elif len({(d['document_id'], d['version']) for d in documents}) != len(documents):
        problems.append('documents repeat a member')
    return problems


def preflight(membership, snapshot):
    """The preflight report of ``membership`` against an admitted ``snapshot`` (``literature_build``).

    Reasons: ``invalid_membership``, ``index_digest_changed``, ``corpus_digest_changed``,
    ``gold_not_frozen``, ``document_missing``, ``version_missing`` and
    ``coordinate_system_mismatch``. The status is ``passed`` only when there is none.
    """
    from .literature_build import validate_snapshot
    checked = validate_snapshot(snapshot)
    manifest, corpus = checked['manifest'], checked['corpus']
    reasons = [{'code': 'invalid_membership', 'detail': p} for p in _shape(membership)]
    if not reasons:
        if membership['index_manifest_sha256'] != manifest['manifest_sha256']:
            reasons.append({'code': 'index_digest_changed',
                            'detail': 'the declared index manifest differs from the pinned snapshot'})
        if membership['corpus_sha256'] != manifest['corpus_sha256']:
            reasons.append({'code': 'corpus_digest_changed',
                            'detail': 'the declared corpus digest differs from the pinned snapshot'})
        if membership['gold']['frozen'] is not True or membership['gold']['sha256'] is None:
            reasons.append({'code': 'gold_not_frozen', 'detail': 'the gold answers are not declared frozen'})
        versions = {}
        for paper in corpus['papers']:
            versions.setdefault(paper['document_id'], set()).add(paper['version'])
        spaces = {}
        for unit in corpus['units']:
            evidence = unit['evidence']
            spaces.setdefault((evidence['document_id'], evidence['version']), set()).add(evidence['location']['space'])
        admitted = set(COORDINATES[membership['coordinates']])
        for member in membership['documents']:
            document, version = member['document_id'], member['version']
            if document not in versions:
                reasons.append({'code': 'document_missing', 'document_id': document, 'version': version,
                                'detail': 'the pinned snapshot holds no such document'})
            elif version not in versions[document]:
                reasons.append({'code': 'version_missing', 'document_id': document, 'version': version,
                                'detail': 'the pinned snapshot holds the document only at ' + ', '.join(
                                    sorted(versions[document]))})
            else:
                other = sorted(spaces.get((document, version), set()) - admitted)
                if other:
                    reasons.append({'code': 'coordinate_system_mismatch', 'document_id': document, 'version': version,
                                    'detail': 'located units use ' + ', '.join(other) + ', not the declared '
                                              + membership['coordinates'] + ' coordinates'})
    encoded = json.dumps(membership, sort_keys=True, separators=(',', ':'), default=str).encode()
    return {'schema_version': 1, 'kind': REPORT_KIND, 'status': 'refused' if reasons else 'passed',
            'reasons': reasons, 'membership_sha256': hashlib.sha256(encoded).hexdigest(),
            'index': {'id': manifest['id'], 'manifest_sha256': manifest['manifest_sha256'],
                      'corpus_sha256': manifest['corpus_sha256']},
            'documents': len(membership['documents']) if type(membership) is dict
            and type(membership.get('documents')) is list else 0,
            'quality_measured': False, 'provider_qualified': False}


def _membership(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('the membership document must be an ordinary bounded file')
    return json.loads(path.read_bytes())


def main(argv=None):
    """``python -m ravel.workflow.literature_evaluation_preflight --membership M --index-root R``."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--membership', type=Path, required=True, help='the declared membership document')
    parser.add_argument('--index-root', type=Path, required=True, help='the admitted literature index store')
    parser.add_argument('--snapshot', help='a pinned snapshot id (default: the store current pointer)')
    args = parser.parse_args(argv)
    from .literature_build import load_index
    try:
        report = preflight(_membership(args.membership), load_index(args.index_root, args.snapshot))
    except (OSError, ValueError) as exc:
        print(f'literature_evaluation_preflight: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(deepcopy(report), indent=2, sort_keys=True))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
