"""Offline census routing, doctor bindings and honest tool labels."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ravel.workflow import backend_portfolio as portfolio
from ravel.setup import doctor, manifest as mf
from shipped_catalogue import shipped_operations

ROOT = Path(__file__).resolve().parents[2]


def test_every_census_tool_has_atlas_doctor_and_status(tmp_path):
    census = portfolio.load_census()
    atlas = json.loads((ROOT / 'src/ravel/data/knowledge/atlas.json').read_text())
    ids = {r['id'] for r in atlas['entries']}
    qualification = json.loads((ROOT / 'src/ravel/data/knowledge/qualification.json').read_text())
    assert {r['id'] for r in census['tools']} == {r['id'] for r in qualification['tools']}
    assert all('tool:' + r['id'] in ids for r in census['tools'] if not mf.withheld_tool(mf.load(ROOT)[0], r))
    manifest = mf.view(ROOT)
    # Every manifest target is replaced with an inert versioned executable. No native runtime is used.
    for group in manifest['groups']:
        for check in group['checks']:
            fake = tmp_path / 'bin' / (group['id'] + '-' + check['id'])
            fake.parent.mkdir(exist_ok=True)
            fake.write_text("#!/bin/sh\nprintf 'synthetic-tool 1.0\\n'\n")
            fake.chmod(0o755)
            check.clear()
            check.update(id=fake.name.removeprefix(group['id'] + '-'), kind='executable', path=str(fake),
                         probe={'argv': ['{path}', '--version'], 'regex': r'synthetic-tool (\S+)', 'expect': '1.0'})
    for row in census['tools']:
        for check in row['doctor_checks']:
            if check['kind'] == 'executable':
                for name in check['names']:
                    fake = tmp_path / 'bin' / name
                    fake.write_text('#!/bin/sh\nexit 0\n'); fake.chmod(0o755)
    d = doctor.Doctor(ROOT, tmp_path / 'prefix', 'linux-x86_64', manifest, {'sets': []},
                      environ={'PATH': str(tmp_path / 'bin')},
                      which=lambda name: str(tmp_path / 'bin' / name) if (tmp_path / 'bin' / name).exists() else None)
    report = d.census_report(census)
    assert len(report) == sum(not mf.withheld_tool(manifest, r) for r in census["tools"])
    assert all(r['status'] in {'qualified', 'built_but_unqualified', 'not_installed', 'excluded'} for r in report)
    assert all(r['checks'] for r in report)
    assert all(r['readiness'] in {'ready', 'excluded', 'unsupported'} for r in report)
    assert all(r['status'] == 'not_installed' for r in report if r['readiness'] == 'unsupported')
    assert d.probes and all(str(tmp_path / 'bin') in argv[0] for argv in d.probes)


def test_ranking_reads_census_and_row_mutation_changes_order(tmp_path):
    path = tmp_path / 'census.json'
    census = portfolio.load_census()
    path.write_text(json.dumps(census))
    first = portfolio.rank_backends(signal_basis='bsm', census_path=path)
    winner = first['ranking'][0]['backend']
    row = next(r for r in census['backends'] if r['id'] == winner)
    row['signal_bases'] = ['sm']
    path.write_text(json.dumps(census))
    second = portfolio.rank_backends(signal_basis='bsm', census_path=path)
    assert second['ranking'][0]['backend'] != winner
    assert second['census_sha256'] != first['census_sha256']
    assert first['cross_backend_combination'] is None
    assert not first['execution_authorized']


def test_required_tool_wording_has_no_optional_label():
    paths = ['diagrammatica_code', 'eft_toolchain', 'parameter_space_sampling', 'parameter_space_sampling_worker',
             'sfitter_native', 'model_sources', 'dataset_query_quantities', 'dataset_query_quantities_worker',
             'finite_integrals_worker', 'scoped_shower']
    for name in paths:
        text = (ROOT / f'src/ravel/physics/{name}.py').read_text()
        doc = ast.get_docstring(ast.parse(text))
        assert 'optional' not in doc.splitlines()[0].casefold(), name
    # The page of an operation this tree does not ship is withheld with it.
    pages = ['agentrivet-source', *shipped_operations(['diagrammatica-code', 'dataset-query-quantities',
                                                        'parameter-space-sampling'])]
    assert len(pages) >= 3
    for name in pages:
        text = (ROOT / f'docs/reference/{name}.md').read_text()
        assert 'optional external' not in text.casefold()
        assert 'optional native python' not in text.casefold()
        assert not text.startswith('# Optional'), name


def test_generated_status_table_is_current_and_detects_mutation():
    from ravel.workflow import tool_census
    census = portfolio.load_census(catalog=tool_census.shipped_catalog(ROOT))
    text = (ROOT / tool_census.STATUS_TABLE).read_text()
    assert text == tool_census.render_status(census)
    mutated = deepcopy(census)
    mutated['tools'][0]['status'] = 'excluded'
    assert tool_census.render_status(mutated) != text


def test_assess_exposes_ranked_choices_and_overlaps(monkeypatch):
    from ravel.workflow import backend_portfolio as bp
    monkeypatch.setattr(bp, '_pin', lambda p: {'path': str(p), 'sha256': 'a' * 64})
    class Capture:
        def finish(self): pass
    entries = [dict(row={'id': backend, 'backend': backend, 'outputs': {'q': {'quantity_ids': ['q']}},
                         'applicability': {'routine_ids': ['synthetic-routine']}},
                    specification={'mode': mode}, applicable=True, blockers=[], adapter_inputs=[])
               for backend, mode in [('smodels', 'model-portfolio'), ('ma5', 'ma5-pad')]]
    monkeypatch.setattr(bp, '_load', lambda p: (Path(p), {'signal_basis': 'bsm', 'energy_tev': 13},
                       {'request': {'task_id': 'synthetic'}, 'request_sha256': 'b' * 64}, entries, Capture()))
    result = bp.assess('synthetic.json')
    assert len(result['backend_ranking']['ranking']) == sum(not mf.release_mentions(mf.load(ROOT)[0], row) for row in portfolio.load_census()['backends'])
    assert result['overlaps'] == [{'study_ids': ['smodels', 'ma5'], 'artifact_ids': ['q'],
                                 'routine_ids': ['synthetic-routine'], 'combination': None}]
    assert all(r['ranking_reasons'] for r in result['studies'])


def test_census_ships_no_routine_list_and_maps_the_local_catalogue(tmp_path, monkeypatch):
    from ravel import analysis_catalog
    from synthetic_catalog import build
    raw = json.loads((ROOT / 'src/ravel/data/backends/census.json').read_text())
    assert 'analysis_catalog' not in raw
    assert not any(b.get('analysis_entries') for b in raw['backends'])
    monkeypatch.setenv(analysis_catalog.CATALOG_ENV, str(tmp_path / 'absent.json'))
    census = portfolio.load_census()
    assert census['analysis_catalog']['status'] == 'not_built'
    assert all(b['analysis_entries'] == [] for b in census['backends'])
    assert next(b for b in census['backends'] if b['id'] == 'rivet')['mapping_count'] is None
    path, catalog = build(tmp_path / 'upstream')
    monkeypatch.setenv(analysis_catalog.CATALOG_ENV, str(path))
    census = portfolio.load_census()
    assert census['analysis_catalog']['entries'] == len(catalog['entries'])
    mapped = {a['id'] for b in census['backends'] for a in b['analysis_entries']}
    assert mapped == {a['id'] for a in catalog['entries']}
    qualification = json.loads((ROOT / 'src/ravel/data/knowledge/qualification.json').read_text())
    by_id = {r['id']: r for r in census['tools']}
    for row in qualification['tools']:
        assert all(by_id[row['id']][k] == v for k, v in row.items())
    assert all(r['execution_count'] is None for r in census['backends'])


def test_generated_status_cli_rejects_stale_table(tmp_path):
    from ravel.workflow import tool_census
    data = tmp_path / 'src/ravel/data/backends/census.json'
    data.parent.mkdir(parents=True)
    data.write_text((ROOT / 'src/ravel/data/backends/census.json').read_text())
    assert tool_census.main(['--root', str(tmp_path)]) == 0
    assert tool_census.main(['--root', str(tmp_path), '--check']) == 0
    (tmp_path / tool_census.STATUS_TABLE).write_text('stale')
    assert tool_census.main(['--root', str(tmp_path), '--check']) == 1


def test_metadata_match_and_family_rank_are_data_driven(tmp_path):
    census = portfolio.load_census()
    row = next(r for r in census['backends'] if r['id'] == 'simpleanalysis')
    row['analysis_entries'] = [{'id': 'synthetic:routine', 'name': 'synthetic-routine'}]
    row['mapping_count'] = 1
    path = tmp_path / 'census.json'; path.write_text(json.dumps(census))
    result = portfolio.rank_backends(signal_basis='bsm', routine_ids=['synthetic-routine'],
                                     family='search', census_path=path)
    assert result['ranking'][0]['backend'] == 'simpleanalysis'
    assert result['ranking'][0]['matched_routines'] == ['synthetic-routine']
    assert not next(r for r in result['ranking'] if r['backend'] == 'contur')['compatible']


def test_unprovided_and_excluded_tools_cannot_become_ready(tmp_path):
    census = portfolio.load_census()
    census['tools'] = [r for r in census['tools'] if r['doctor_checks'][0]['kind'] in {'unprovided', 'excluded'}]
    d = doctor.Doctor(ROOT, tmp_path / 'prefix', 'linux-x86_64', {'groups': []}, {'sets': []},
                      environ={'PATH': str(tmp_path)}, which=lambda name: '/fake/present',
                      run_probe=lambda *a, **k: pytest.fail('unsupported/excluded tools must never execute'))
    rows = d.census_report(census)
    assert rows
    assert all(r['status'] in {'not_installed', 'excluded'} for r in rows)
    assert d.probes == []


def test_documented_top_level_commands_exist():
    from ravel.cli import parser
    from argparse import _SubParsersAction
    names = set()
    for action in parser()._actions:
        if isinstance(action, _SubParsersAction): names.update(action.choices)
    # The focused commands dispatch before parser(), so they are registered separately.
    from ravel.cli import FOCUSED_COMMANDS
    names.update(FOCUSED_COMMANDS)
    import re
    docs = ['docs/reference/environment.md', 'docs/reference/tool-licences.md',
            'docs/reference/symbolic-evaluation.md', 'docs/workflow/reference/failed-stage-review.md',
            'docs/workflow/steps/cosmology-solvers.md', 'docs/workflow/checklists/ml-training.md',
            'docs/reference/classifier-inputs.md', 'docs/workflow/reference/research-orchestration.md',
            'docs/workflow/steps/01-environment.md']
    for name in docs:
        commands = set(re.findall(r'\bravel ([a-z][a-z0-9-]+)', (ROOT / name).read_text()))
        assert commands <= names, (name, commands - names)


def test_user_facing_census_text_has_no_internal_stream_labels():
    import re
    from ravel.workflow import tool_census
    texts = {'environment': (ROOT / 'docs/workflow/steps/01-environment.md').read_text(),
             'diagrammatica': (ROOT / 'docs/reference/diagrammatica-code.md').read_text(),
             'table': tool_census.render_status(portfolio.load_census())}
    for name, text in texts.items():
        assert not re.search(r'\b(?:KM-\d|KM-F|WD-L|M-\d\d)\b', text), name
    assert 'external GPL backend is external' not in texts['diagrammatica']


def test_every_unqualified_census_row_has_a_package_or_recorded_home():
    """Every unfinished census entry is installable or has an explicit next action."""
    census = portfolio.load_census()
    qualification = json.loads((ROOT / 'src/ravel/data/knowledge/qualification/rows.json').read_text())
    manifest, _ = mf.load(ROOT)

    group_ids = {group['id'] for group in manifest['groups']}
    named = {record['group'] for record in qualification['census_homes'] if record['kind'] == 'package'}
    for row in census['tools']:
        named |= set(row['installer_groups']) | {check['group'] for check in row['doctor_checks']
                                                 if check['kind'] == 'manifest'}
    if 'unreleased' in manifest:
        # A tree carrying its withheld list declares every group, withheld or not: an undeclared
        # name there is an error, never a held group.
        assert named <= group_ids, sorted(named - group_ids)
    # A group the release withholds (explicitly, or by not declaring it in a released tree) is the
    # recorded home of the tools bound to it.
    homes_of = group_ids | mf.held_groups(manifest, named)

    def uncovered(document, homes):
        by_census = {}
        for home in homes:
            by_census.setdefault(home['census_id'], []).append(home)
        missing = []
        for row in document['tools']:
            if row['status'] == 'qualified':
                continue
            manifest_groups = {check['group'] for check in row['doctor_checks']
                               if check['kind'] == 'manifest'}
            package = (bool(row['installer_groups']) and set(row['installer_groups']) <= homes_of) \
                or bool(manifest_groups) and manifest_groups <= homes_of
            records = by_census.get(row['id'], [])
            recorded = any(
                record['kind'] in {'qualification-job', 'data-format'}
                or record['kind'] == 'deferral' and record['reason'] == 'site-only; qualified at a site'
                or record['kind'] == 'package' and record['group'] in homes_of
                for record in records
            )
            if not package and not recorded:
                missing.append(row['id'])
        return missing

    assert uncovered(census, qualification['census_homes']) == []

    recorded_ids = [row['census_id'] for row in qualification['census_homes']]
    assert len(recorded_ids) == len(set(recorded_ids))
    assert set(recorded_ids) <= {row['id'] for row in census['tools']}

    homes = {row['census_id']: row for row in qualification['census_homes']}
    # A package home installs by default, or the release withholds it explicitly (a pending home without
    # source records or qualification).
    withheld = mf.held_groups(manifest, named)
    assert all((row['group'] in manifest['default']['groups']) != (row['group'] in withheld)
               for row in homes.values() if row['kind'] == 'package')
    agent_rows = {
        'census-agentrivet-e4d12ecc',
        'census-magnus-cli-agpl',
        'census-langgraph-1-2-14-checkpoint-4-2-0-sqlite-saver-3-1-1-langchain-core-1-6-7-pydantic-2-14-0',
        'census-model-providers-anthropic-messages-openai-responses-gemini-openai-compatible-chat-completions',
    }
    assert all(homes[identity]['kind'] == 'qualification-job' for identity in agent_rows)
    assert all(homes[identity]['job']['name'].endswith('import-and-version') for identity in agent_rows)
    assert all(homes[identity]['job']['command'][:2] == ['ravel', 'plan'] for identity in agent_rows)

    planted = deepcopy(census)
    planted['tools'].append({
        'id': 'census-planted-uncovered', 'status': 'not_installed', 'installer_groups': [],
        'doctor_checks': [{'kind': 'unprovided'}],
    })
    with pytest.raises(AssertionError, match='census-planted-uncovered'):
        assert uncovered(planted, qualification['census_homes']) == []
