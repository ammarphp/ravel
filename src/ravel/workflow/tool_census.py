"""Packaged tool/analysis census, conservative planning ranks and status projection.

Metadata mapping, historical qualification and doctor readiness are separate facts.
This module imports no scientific runtimes and authorizes no execution.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
import re

STATUS_TABLE = 'docs/reference/tool-status.md'
STATUSES = ('qualified', 'built_but_unqualified', 'not_installed', 'excluded')


def census_bytes(path=None):
    return (Path(path).read_bytes() if path is not None else
            files('ravel').joinpath('data/backends/census.json').read_bytes())


def load_census(path=None, catalog='local'):
    """Load the shipped data on each call, including caller-selected mutation fixtures."""
    return _decode(census_bytes(path), catalog)


def catalog_provenance(catalog):
    """Where routine coverage came from: the local catalogue's path and digest, or its absence."""
    if catalog is None:
        return {'status': 'not_built', 'detail': 'no catalogue available; build one with `ravel catalogue` to map routine coverage'}
    return {'status': 'local', 'entries': len(catalog['entries']), 'retrieved_at_utc': catalog['retrieved_at_utc'],
            'sources': sorted(catalog['sources'])}


def _local_catalog():
    from ravel.analysis_catalog import load_catalog
    try:
        return load_catalog()
    except (OSError, ValueError):
        return None


def _decode(raw, catalog='local'):
    """The census with each catalogue-backed engine's routine entries taken from ``catalog``
    (the catalogue `load_catalog()` selects by default, None for none). This census lists no routine itself."""
    data = json.loads(raw)
    if data.get('schema_version') != 1 or data.get('kind') != 'ravel-backend-census':
        raise ValueError('backend census schema1 required')
    tools = data['tools']
    if len({r['id'] for r in tools}) != len(tools):
        raise ValueError('duplicate census tool')
    by_id = {r['id']: r for r in tools}
    for row in tools:
        if 'request_names' in row:
            names = row['request_names']
            if not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names):
                raise ValueError('census request_names must be a list of nonblank strings')
            for name in names:
                if name.startswith('re:'):
                    try:
                        re.compile(name[3:])
                    except re.error as exc:
                        raise ValueError('invalid census request_names expression') from exc
        if row['status'] not in STATUSES or not row['doctor_checks']:
            raise ValueError('census tool needs one status and doctor checks: ' + row['id'])
        if row['requirement'] not in ('required_for_profile', 'excluded'):
            raise ValueError('unknown tool requirement')
    if len({r['id'] for r in data['backends']}) != len(data['backends']):
        raise ValueError('duplicate census backend')
    for row in data['backends']:
        if row['tool_id'] not in by_id or not row['signal_bases'] or not row['families']:
            raise ValueError('backend needs census tool and source applicability')
    if catalog == 'local':
        catalog = _local_catalog() if any(r.get('catalog_framework') for r in data['backends']) else None
    data['analysis_catalog'] = catalog_provenance(catalog)
    for row in data['backends']:
        framework = row.get('catalog_framework')
        if framework is None:
            row.setdefault('analysis_entries', [])
        elif 'analysis_entries' not in row:
            row['analysis_entries'] = [] if catalog is None else [
                {'family': e['family'], 'id': e['id'], 'name': e['name'], 'source_relation': e['source_relation']}
                for e in catalog['entries'] if e['framework'] == framework]
            row['mapping_count'] = None if catalog is None else len(row['analysis_entries'])
    return data


def rank_backends(*, signal_basis, routine_ids=(), family=None, census_path=None):
    """Rank prospective engines from data; an offer still needs exact source review.

    Basis/family compatibility comes first, followed by exact metadata matches,
    historical tool status and mapped inventory size. Unknown coverage stays unknown.
    Ranks never select, combine, approve or execute a study.
    """
    raw = census_bytes(census_path)
    data = _decode(raw)
    tools = {r['id']: r for r in data['tools']}
    requested = set(routine_ids)
    ranking = []
    for row in released_backends(data):
        tool = tools[row['tool_id']]
        known = {v for a in row['analysis_entries'] for v in (a['id'], a['name'])}
        matches = sorted(requested & known)
        compatible = signal_basis in row['signal_bases'] and (family is None or family in row['families'])
        reasons = [row['assumptions'], row['coverage_scope'],
                   'Prediction basis admitted by census.' if signal_basis in row['signal_bases'] else 'Prediction basis outside census contract.',
                   'Exact metadata matches: ' + str(len(matches)),
                   'Reported historical qualification: ' + tool['status'] + '; ' + tool['evidence_scope']]
        if requested - known:
            reasons.append('Unmatched routines require source investigation; absence from metadata is not a physics refusal.')
        if family is not None:
            reasons.append('Requested family admitted.' if family in row['families'] else 'Requested family outside census contract.')
        score = (int(compatible and tool['status'] != 'excluded'), len(matches),
                 -STATUSES.index(tool['status']), row['mapping_count'] or 0)
        ranking.append({'backend': row['id'], 'compatible': compatible, 'status': tool['status'],
                        'matched_routines': matches, 'mapping_count': row['mapping_count'],
                        'execution_count': row['execution_count'], 'reasons': reasons, '_score': score})
    ranking.sort(key=lambda r: (tuple(-v for v in r['_score']), r['backend']))
    for rank, row in enumerate(ranking, 1):
        row.pop('_score'); row['rank'] = rank
    return {'kind': 'backend-census-ranking', 'schema_version': 1, 'ranking': ranking,
            'census_sha256': sha256(raw).hexdigest(), 'analysis_catalog': data['analysis_catalog'],
            'cross_backend_combination': None, 'execution_authorized': False, 'physics_validated': False}


def released_backends(data):
    """One release projection for both ranking APIs and their portfolio callers."""
    from ravel.setup import manifest as mf
    manifest = mf_manifest(mf.repo_root())
    tools = {row['id']: row for row in data['tools']}
    if manifest:
        return [row for row in data['backends']
                if not mf.release_mentions(manifest, [row, tools[row['tool_id']]])]
    from .knowledge import load_atlas
    offered = {row['id'][5:] for row in load_atlas()['entries'] if row['kind'] == 'tool'}
    return [row for row in data['backends'] if row['tool_id'] in offered]


def doctor_report(doctor, census=None):
    """Check every census row without equating tool readiness with physics validity.

    Existing manifest checks retain their versions/paths. Explicit presence and
    source checks cover proposed tools and built-in readers without invoking them.
    Excluded tools are recorded and never probed. Calls are cached only within
    this report, so a later doctor invocation observes current state again.
    """
    from ravel.setup import manifest as mf
    from ravel.setup.doctor import STATUS_ORDER
    census = census if census is not None else load_census()
    groups = mf.by_id(doctor.manifest)
    checked, result = {}, []
    for tool in census['tools']:
        if mf.withheld_tool(doctor.manifest, tool):
            continue
        checks = []
        for binding in tool['doctor_checks']:
            kind = binding['kind']
            if kind == 'manifest' and binding['group'] in mf.held_groups(doctor.manifest, [binding['group']]):
                continue  # a released tool keeps its row; the check of a withheld group is not offered
            if kind == 'manifest':
                key = (binding['group'], binding['check'])
                if key not in checked:
                    group = groups[binding['group']]
                    check = next(c for c in group['checks'] if c['id'] == binding['check'])
                    route = mf.route_for(group, doctor.platform)
                    if not mf.applies(check, doctor.platform):
                        row = {'status': 'remote_route', 'detail': 'Check belongs to another platform.'}
                    elif route in ('remote', 'unsupported'):
                        row = {'status': 'remote_route' if route == 'remote' else 'unsupported',
                               'detail': group.get('manual')}
                    else:
                        row = doctor.evaluate_check(group, check)
                    checked[key] = row
                observation = dict(checked[key])
            elif kind == 'executable':
                paths = {name: doctor.which(name) for name in binding['names']}
                observation = {'status': 'ready' if all(paths.values()) else 'missing',
                               'paths': paths, 'detail': binding['scope']}
            elif kind == 'resource':
                path = doctor.repo / binding['path']
                observation = {'status': 'ready' if path.is_file() else 'missing',
                               'path': str(path), 'detail': binding['scope']}
            elif kind == 'excluded':
                observation = {'status': 'excluded', 'detail': binding['reason']}
            elif kind == 'unprovided':
                observation = {'status': 'unsupported', 'detail': binding['reason']}
            else:
                raise ValueError('unknown census doctor check: ' + kind)
            checks.append({'binding': binding, **observation})
        statuses = {c['status'] for c in checks}
        readiness = ('excluded' if statuses == {'excluded'} else
                     max(statuses, key=STATUS_ORDER.index))
        from ravel.setup.qualification import census_status
        status = census_status(readiness)
        result.append({'id': tool['id'], 'title': tool['title'], 'status': status,
                       'readiness': readiness, 'reported_status': tool['status'],
                       'evidence_scope': tool['evidence_scope'], 'checks': checks})
    return result


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _withheld_backend(manifest, row, tools):
    """An analysis engine is withheld when its declaration names a withheld tool or its census tool is withheld."""
    from ravel.setup import manifest as mf
    tool = tools.get(row.get('tool_id'))
    return mf.release_mentions(manifest, [row, tool]) or (tool is not None and mf.withheld_tool(manifest, tool))


def render_status(data, manifest=None):
    """Stable, complete projection; CI checks bytes against the packaged source."""
    lines = ['# Tool checks', '',
             'Generated from `src/ravel/data/backends/census.json`; do not edit this table.', '',
             'Tools are required by their selected operation/profile. Run `ravel doctor --census`',
             'for readiness checks on the selected machine.', '',
             '| Tool | Requirement | Doctor check |', '|---|---|---|']
    from ravel.setup import manifest as mf
    manifest = manifest if manifest is not None else mf.load()[0]
    for row in sorted(data['tools'], key=lambda r: r['id']):
        if mf.withheld_tool(manifest, row) or row['status'] == 'excluded':
            continue
        checks = []
        for check in row['doctor_checks']:
            if check['kind'] == 'manifest' and check['group'] in mf.held_groups(manifest, [check['group']]): continue
            if check['kind'] == 'manifest': checks.append(check['group'] + '/' + check['check'])
            elif check['kind'] == 'executable': checks.append('presence: ' + ', '.join(check['names']))
            elif check['kind'] == 'resource': checks.append('source: ' + check['path'])
            else: continue
        if not checks:
            checks.append('no doctor check declared')
        title = re.sub(r'\b[A-Z]+ (?=(?:SimpleAnalysis|Combine|GitLab)\b)', '', row['title'])
        lines.append('| ' + ' | '.join(map(_cell, [title,
                     row['requirement'].replace('_', ' '), '; '.join(checks)])) + ' |')
    lines.append('')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate/check the tool-status table without executing tools.')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    expected = render_tree(args.root)
    target = args.root / STATUS_TABLE
    if args.check:
        return 0 if target.is_file() and target.read_text() == expected else 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected)
    return 0


def render_tree(root):
    """The table the tree at ``root`` ships, from its own census, catalogue snapshot and manifest."""
    root = Path(root)
    return render_status(load_census(root / 'src/ravel/data/backends/census.json', catalog=shipped_catalog(root)),
                         mf_manifest(root))


def shipped_catalog(root):
    """The snapshot the tree at ``root`` ships, so the generated table never depends on this machine."""
    from ravel.analysis_catalog import load_catalog
    path = Path(root) / 'src/ravel/data/analysis-catalog.json'
    return load_catalog(path) if path.is_file() else None


def mf_manifest(root):
    from ravel.setup import manifest
    return manifest.load(root)[0] if manifest.manifest_path(root).is_file() else {}


if __name__ == '__main__':
    raise SystemExit(main())
