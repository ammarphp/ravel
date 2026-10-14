"""Census-driven prospective reinterpretation routes, with readiness and repair reasons.

No runtime is imported or probed. Historical qualification, caller-supplied doctor
observations and source applicability are separate; ranks authorize no execution.
"""
from __future__ import annotations

from hashlib import sha256

from .tool_census import STATUSES, _decode, census_bytes, released_backends


def _fix(tool):
    actions = []
    for check in tool['doctor_checks']:
        kind = check['kind']
        if kind == 'manifest':
            action = 'bash scripts/setup/install.sh --only ' + check['group']
        elif kind == 'executable':
            action = 'Owner action: install/provide ' + ', '.join(check['names']) + '; ' + check['scope']
        elif kind == 'resource':
            action = 'Owner action: supply pinned resource ' + check['path']
        elif kind == 'unprovided':
            action = 'Owner action: provide a source-backed provider contract; ' + check['reason']
        elif kind == 'excluded':
            action = 'No execution route; ' + check['reason']
        else:
            raise ValueError('unknown census doctor check: ' + kind)
        if action not in actions:
            actions.append(action)
    return '; '.join(actions)


def rank_routes(*, signal_basis, routine_ids=(), family=None, census_path=None, observations=()):
    """Read census bytes on every call and return all routes with deterministic reasons.

    Compatibility precedes exact routine matches, historical qualification and
    mapped inventory size. Missing tools remain prospective offers with a repair.
    Without a supplied doctor observation, readiness is unknown for installed
    historical rows; no claim about this machine is inferred from qualification.
    """
    raw = census_bytes(census_path)
    data = _decode(raw)
    tools = {row['id']: row for row in data['tools']}
    observed = {}
    allowed = {'ready', 'missing', 'version_mismatch', 'manual_required', 'unconfigured',
               'unsupported', 'remote_route', 'excluded', 'conflict'}
    for row in observations:
        if row['id'] in observed or row['id'] not in tools or row['readiness'] not in allowed:
            raise ValueError('unique census tool and known doctor readiness required')
        observed[row['id']] = row['readiness']
    requested = set(routine_ids)
    ranking = []
    for backend in released_backends(data):
        tool = tools[backend['tool_id']]
        known = {name for item in backend['analysis_entries'] for name in (item['id'], item['name'])}
        matches = sorted(requested & known)
        basis_ok = signal_basis in backend['signal_bases']
        family_ok = family is None or family in backend['families']
        compatible = basis_ok and family_ok
        readiness = observed.get(tool['id'], 'unknown')
        excluded = tool['status'] == 'excluded' or readiness == 'excluded'
        label = ('excluded' if excluded else 'ready' if readiness == 'ready' else
                 'not_ready' if readiness != 'unknown' or tool['status'] == 'not_installed' else 'readiness_unknown')
        fix = _fix(tool) if label in ('not_ready', 'excluded') else None
        reasons = [backend['assumptions'], backend['coverage_scope'],
                   'Prediction basis admitted by census.' if basis_ok else 'Prediction basis outside census contract.',
                   'Exact metadata matches: ' + str(len(matches)),
                   'Reported historical qualification: ' + tool['status'] + '; ' + tool['evidence_scope'],
                   'Readiness: ' + label + ('; ' + fix if fix else '; installation is not inferred from historical qualification.')]
        if requested - known:
            reasons.append('Unmatched routines require source investigation; absence from metadata is not a physics refusal.')
        if family is not None:
            reasons.append('Requested family admitted.' if family_ok else 'Requested family outside census contract.')
        score = (int(compatible and not excluded), len(matches),
                 -STATUSES.index(tool['status']), backend['mapping_count'] or 0)
        ranking.append({'backend': backend['id'], 'tool_id': tool['id'], 'compatible': compatible,
                        'status': tool['status'], 'reported_status': tool['status'],
                        'qualification_scope': tool['evidence_scope'], 'label': label, 'fix': fix,
                        'readiness': readiness, 'readiness_scope': 'supplied doctor observation' if tool['id'] in observed else 'pinned census only',
                        'matched_routines': matches, 'mapping_count': backend['mapping_count'],
                        'execution_count': backend['execution_count'], 'reasons': reasons, '_score': score})
    ranking.sort(key=lambda row: (tuple(-v for v in row['_score']), row['backend']))
    for rank, row in enumerate(ranking, 1):
        row.pop('_score')
        row['rank'] = rank
    return {'kind': 'backend-census-ranking', 'schema_version': 1, 'ranking': ranking,
            'census_sha256': sha256(raw).hexdigest(), 'analysis_catalog': data['analysis_catalog'],
            'cross_backend_combination': None, 'execution_authorized': False, 'physics_validated': False}


# Existing portfolio callers keep their signature and result envelope.
rank_backends = rank_routes
recast_route = rank_routes


def higgs_reference_readiness():
    """Source-only doctor row; no download, executable probe or synthetic fallback."""
    from ravel.validation.constants_manifest import ConstantsError, load_higgs_source, load_higgs_tables
    source = load_higgs_source()
    try:
        load_higgs_tables()
        readiness, label, detail = 'ready', 'ready', 'Pinned reference bytes and table contracts verified; physics validity is not inferred.'
    except (ConstantsError, OSError, ValueError) as exc:
        readiness, label, detail = 'manual_required', 'not_ready', str(exc)
    return {'id': 'higgs-reference-tables', 'title': 'Higgs reference tables',
            'status': 'built_but_unqualified' if label == 'ready' else 'not_installed',
            'reported_status': source['status'], 'hold_status': source['status'],
            'readiness': readiness, 'label': label, 'fix': source.get('owner_action'),
            'evidence_scope': 'Reference data schema and pin verification only; no fetched physics tables.',
            'checks': [{'binding': {'kind': 'resource'}, 'status': readiness, 'detail': detail}],
            'sources': source.get('sources', []), 'expected_files': source.get('expected_files', []),
            'download_size': source.get('download_size'), 'would_make_possible': source.get('would_make_possible')}


def register_higgs_reference(add, package):
    """Emit the source-held tool row through the atlas producer's typed row seam."""
    from ravel.validation.constants_manifest import load_higgs_source
    source = load_higgs_source(package / 'data/knowledge/higgs')
    add('check', 'higgs-reference-schema', 'Higgs reference table schema',
        'Cited row, uncertainty envelope and ratio document contract',
        package / 'data/knowledge/higgs/schema.json',
        check={'catches': 'Malformed Higgs table rows, missing reference metadata and uncertainty definitions'})
    return add('tool', 'higgs-reference-tables', 'Higgs reference tables',
               source['would_make_possible'], package / 'data/knowledge/higgs/SOURCE.json',
               qualification_status='not_installed' if source['status'] != 'installed' else 'built_but_unqualified',
               qualification_scope='Reference registration only; no physics qualification inferred.',
               hold_status=source['status'], source_locator=source['sources'],
               owner_action=source['owner_action'], expected_files=source['expected_files'],
               download_size=source['download_size'], would_make_possible=source['would_make_possible'],
               links={'checks': ['check:higgs-reference-schema', 'check:validation.constants_manifest.check_higgs_tables']})
