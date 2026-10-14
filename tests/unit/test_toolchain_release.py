"""Release selection uses one explicit list; probes and installs use inert fakes."""
import copy
import json
from pathlib import Path
import re

import pytest

from ravel.setup import doctor, installer, manifest as mf
from ravel import addons
from shipped_catalogue import shipped_operations

ROOT = Path(__file__).resolve().parents[2]


def test_only_site_is_a_named_profile():
    manifest, _ = mf.load(ROOT)
    assert set(manifest['profiles']) == {'site'}
    assert manifest['default']['groups']
    for profile in ('full', 'collider', 'theory', 'statistics', 'publication', 'ml'):
        with pytest.raises(mf.ManifestError, match='unknown profile'):
            mf.profile_groups(manifest, profile)


def test_qualified_labels_require_successful_platform_records():
    manifest, catalog = mf.load(ROOT)
    for group in manifest['groups']:
        if group['qualification']['status'] == 'qualified':
            record = group['qualification']['record']
            assert record['tool'] == group['id'] and record['doctor_result'] == 'ready'
            assert record['version'] and record['platform'] in mf.PLATFORMS
    broken = copy.deepcopy(manifest)
    group = next(g for g in broken['groups'] if g['qualification']['status'] == 'qualified')
    del group['qualification']['record']
    with pytest.raises(mf.ManifestError, match='qualification record'):
        mf.validate(broken, catalog)


def test_unreleased_groups_are_skipped_by_default_and_explicitly_selectable(tmp_path):
    manifest, catalog = mf.load(ROOT)
    # The source tree lists them as withheld; a released tree does not declare them at all.
    excluded = mf.held_groups(manifest, {'checkmate', 'madloop', 'magnus', 'jhugen-mela', 'tex', 'mcfm-amplitudes',
                                         'iris', 'nyx'})
    assert {'checkmate', 'madloop', 'magnus', 'jhugen-mela', 'tex', 'mcfm-amplitudes', 'iris'} <= excluded
    assert 'nyx' not in excluded, 'qualified on a Linux MPI site'
    tool = installer.Installer(ROOT, tmp_path / 'prefix', manifest=manifest, catalog=catalog,
                               platform_key='macos-arm64', environ={}, interactive=False)
    assert not excluded.intersection(tool.groups())
    assert not excluded.intersection(doctor.select_groups(manifest))
    # Evidence labels do not decide membership.
    stale = copy.deepcopy(manifest)
    for group in stale['groups']:
        group['qualification'] = {'status': 'not-built', 'basis': 'synthetic stale label'}
    assert mf.profile_groups(stale) == mf.profile_groups(manifest)
    d = doctor.Doctor(ROOT, tmp_path / 'prefix', 'macos-arm64', manifest, catalog,
                      environ={}, which=lambda _: None, glob_paths=lambda _: [],
                      run_probe=lambda *a, **k: (127, 'synthetic missing tool'))
    report = d.report(doctor.select_groups(manifest))
    assert not excluded.intersection(g['group'] for g in report['groups'])
    listed = manifest.get('unreleased', {'groups': [], 'operations': []})
    assert all(row['check'] for row in listed['groups'])
    assert ({'mode': 'amplitude-crosscheck', 'groups': ['jhugen-mela']} in listed['operations']
            or not shipped_operations(['amplitude-crosscheck']))
    # A withheld group the tree declares stays explicitly selectable.
    for gid in mf.unreleased_groups(manifest):
        assert gid in tool.groups(only=[gid])
        assert doctor.select_groups(manifest, groups=[gid]) == [gid]
        assert d.report([gid])['groups'][0]['group'] == gid


def test_standard_groups_and_doctor_never_offer_optional_tools(tmp_path):
    manifest, catalog = mf.load(ROOT)
    selected = mf.profile_groups(manifest)
    assert {'agent-sources', 'sfitter', 'nyx', 'publication', 'ml', 'diagram-consumers'} <= set(selected)
    assert not {'mcfm-amplitudes', 'iris'} & set(selected)
    forbidden = re.compile(r'optional|add-on|addon|if installed|when available', re.I)
    for group in manifest['groups']:
        assert 'optional' not in group
        assert not forbidden.search(json.dumps({k: group.get(k, '') for k in ('title', 'description', 'notes')}))
    d = doctor.Doctor(ROOT, tmp_path / 'prefix', 'macos-arm64', manifest, catalog,
                      environ={}, which=lambda _: None, glob_paths=lambda _: [],
                      run_probe=lambda *a, **k: (127, 'synthetic missing tool'))
    report = d.report(selected)
    assert report['ready'] is False
    assert not forbidden.search(doctor.format_report(report))
    assert all(c.get('fix') for g in report['groups'] for c in g['checks']
               if c['status'] not in doctor.OK_STATUSES)


def test_general_mcfm_name_resolves_and_member_hashes_verify():
    found = addons.resolve('mcfm-amplitudes', env={})
    assert found.root == ROOT / 'addons/gpl/mcfm-amplitudes'
    assert found.manifest['program'] == 'ravel_mcfm_amplitudes'
    assert found.members()


def test_missing_required_tools_fail_the_default_doctor(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor.Doctor, 'wolfram_kernel', lambda self: None)
    code = doctor.main(['--json', '--prefix', str(tmp_path / 'prefix')], repo=ROOT,
                       environ={'PATH': '/nonexistent', 'HOME': str(tmp_path / 'home')},
                       run_probe=lambda *a, **k: (127, 'synthetic missing tool'))
    report = json.loads(capsys.readouterr().out)
    assert report['ready'] is False
    assert code == 1


def test_generated_tool_lists_withhold_development_groups(tmp_path):
    from ravel.workflow import tool_census
    manifest, catalog = mf.load(ROOT)
    d = doctor.Doctor(ROOT, tmp_path / 'prefix', 'macos-arm64', manifest, catalog,
                      environ={}, which=lambda _: None, glob_paths=lambda _: [],
                      run_probe=lambda *a, **k: (127, 'synthetic missing tool'))
    assert not mf.release_mentions(manifest, tool_census.doctor_report(d))
    assert not mf.release_mentions(manifest, tool_census.render_status(tool_census.load_census(), manifest))


def test_named_development_groups_install_with_inert_steps(tmp_path):
    from setup_fakes import FakeRunner
    manifest, catalog = mf.load(ROOT)
    manifest = copy.deepcopy(manifest)
    for group in manifest['groups']:
        group['routes'] = {'default': 'native'}
        group['steps'] = [{'id': 'synthetic-build', 'kind': 'command',
                           'argv': ['make-outputs', '{BIN}/' + group['id']],
                           'outputs': ['{BIN}/' + group['id']]}]
    repo = tmp_path / 'repo'
    repo.mkdir()
    runner = FakeRunner()
    tool = installer.Installer(repo, tmp_path / 'prefix', manifest=manifest, catalog=catalog,
                               platform_key='macos-arm64', environ={'HOME': str(tmp_path / 'home')},
                               runner=runner, interactive=False, accept_licenses=True)
    for gid in mf.unreleased_groups(manifest):
        result = tool.run(only=[gid])
        assert result['status'] == 'complete'
        assert result['groups'][gid]['status'] == 'done'
        assert (tmp_path / 'prefix/bin' / gid).is_file()


def test_diagrammatica_uses_the_existing_pinned_eda_install():
    manifest, _ = mf.load(ROOT)
    groups = mf.by_id(manifest)
    assert 'diagram-consumers' in mf.profile_groups(manifest)
    assert groups['diagram-consumers']['qualification']['status'] == 'qualified'
    assert any(c['id'] == 'heptapod-eda' for c in groups['diagram-consumers']['checks'])
    source = next(s for s in groups['wolfram']['steps'] if s['id'] == 'heptapod')
    assert source['url'].startswith('https://') and re.fullmatch('[0-9a-f]{40}', source['commit'])


def test_backend_tool_lists_use_the_same_release_list(monkeypatch, capsys):
    from ravel.workflow import execution_backend as eb
    manifest, _ = mf.load(ROOT)
    assert eb.main(['list']) == 0
    assert not mf.release_mentions(manifest, capsys.readouterr().out)
    seen = []
    class FakeBackend:
        def doctor(self):
            return {'ready': True}
    def get(kind):
        seen.append(kind)
        return FakeBackend()
    monkeypatch.setattr(eb, 'get', get)
    assert eb.doctor_all()
    assert not mf.unreleased_groups(manifest).intersection(seen)


def test_default_ranking_withholds_unreleased_backends():
    from ravel.workflow import tool_census
    manifest, _ = mf.load(ROOT)
    result = tool_census.rank_backends(signal_basis='bsm')
    assert result['ranking']
    assert not mf.release_mentions(manifest, result['ranking'])


def test_root_cli_help_withholds_unreleased_tools():
    from ravel import cli
    manifest, _ = mf.load(ROOT)
    assert not mf.release_mentions(manifest, cli.parser().format_help())


def test_old_mcfm_names_are_gone():
    old = re.compile(r'four-lepton-mcfm|mcfm-four-lepton|ravel_mcfm_four_lepton')
    offenders = []
    for directory in ('addons', 'src', 'docs', 'scripts', 'native', 'tests'):
        for path in (ROOT / directory).rglob('*'):
            if path.is_file() and path != Path(__file__) and path.suffix in ('.py', '.sh', '.md', '.json', '.f90', '.cmake'):
                if old.search(path.read_text(errors='replace')):
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_released_tools_stay_listed_when_their_notes_mention_a_withheld_tool(tmp_path):
    from ravel.workflow import tool_census
    from ravel.workflow.knowledge import load_atlas
    manifest, catalog = mf.load(ROOT)
    census = tool_census.load_census()
    kept = {'census-delphes-3-5-1', 'census-root-6-40', 'census-spey-0-2-6',
            'census-podman-5-8-2-macos-client-vfkit-0-6-3-gvproxy-0-8-9-podman-vm-ravel-rosetta-2'}
    withheld = {'census-hepmc2-2-06-11', 'census-pythia-8-244', 'census-tex-live-or-mactex-with-pdflatex-bibtex-revtex'}
    titles = {row['id']: row['title'] for row in census['tools']}
    table = tool_census.render_status(census, manifest)
    assert all('| ' + titles[i] + ' |' in table for i in kept)
    assert not any('| ' + titles[i] + ' |' in table for i in withheld)
    d = doctor.Doctor(ROOT, tmp_path / 'prefix', 'macos-arm64', manifest, catalog,
                      environ={}, which=lambda _: None, glob_paths=lambda _: [],
                      run_probe=lambda *a, **k: (127, 'synthetic missing tool'))
    reported = {row['id'] for row in tool_census.doctor_report(d)}
    assert kept <= reported and not withheld & reported
    atlas = {row['id'] for row in load_atlas()['entries']}
    assert {'tool:' + i for i in kept} <= atlas and not {'tool:' + i for i in withheld} & atlas


def test_every_offered_operation_declares_the_groups_it_needs():
    """Each mode a registry or an operation signature offers has a toolchain row, so the per-mode
    doctor and the release surface know what it needs; no row names a mode nothing offers."""
    import json
    from ravel.setup import manifest as mf
    from ravel.workflow import science
    manifest = mf.load(ROOT)[0]
    rows = {row['mode'] for row in manifest['operations']}
    signatures = json.loads((ROOT / 'src/ravel/data/operation_signatures.json').read_text())['operations']
    descriptors = json.loads((ROOT / 'src/ravel/data/mode_descriptors.json').read_text())['modes']
    offered = set(science.MODES) | set(descriptors) | {
        s['implementation']['mode'] for s in signatures.values() if s.get('implementation', {}).get('mode')}
    assert sorted(offered - rows) == [] and sorted(rows - offered) == []


def test_census_report_and_table_work_on_a_tree_that_declares_only_released_groups(tmp_path):
    """A released tree's manifest carries no withheld list and none of the withheld groups. A census row
    bound only to such groups is not reported there, and a released tool keeps its row without the
    check of a group the tree does not declare."""
    from ravel.workflow import tool_census
    manifest, catalog = mf.load(ROOT)
    census = tool_census.load_census()
    bound = {row['id']: set(row.get('installer_groups', [])) |
             {c['group'] for c in row['doctor_checks'] if c['kind'] == 'manifest'} for row in census['tools']}
    # Withheld in the source tree's list, or not declared by a released tree.
    held = mf.held_groups(manifest, set().union(*bound.values()))
    public = copy.deepcopy(manifest)
    public['groups'] = [g for g in public['groups'] if g['id'] not in held]
    public.pop('unreleased', None)
    assert mf.held_groups(public, held | {'python-host'}) == held and mf.held_groups(public) == set()
    assert mf.held_groups({}, held) == set(), 'without a manifest nothing is known to be held'
    checked = {row['id']: {c['group'] for c in row['doctor_checks'] if c['kind'] == 'manifest'}
               if all(c['kind'] == 'manifest' for c in row['doctor_checks']) else None for row in census['tools']}
    only_held = {i for i, groups in bound.items() if groups and (groups <= held or (checked[i] and checked[i] <= held))}
    mixed = {i for i, groups in bound.items() if groups & held} - only_held
    assert only_held and mixed
    assert only_held == {row['id'] for row in census['tools'] if mf.withheld_tool(public, row)}
    d = doctor.Doctor(ROOT, tmp_path / 'prefix', 'macos-arm64', public, catalog,
                      environ={}, which=lambda _: None, glob_paths=lambda _: [],
                      run_probe=lambda *a, **k: (127, 'synthetic missing tool'))
    report = {row['id']: row for row in tool_census.doctor_report(d, census)}
    assert not only_held & set(report) and mixed <= set(report)
    for row in report.values():
        assert row['checks'] and not [c for c in row['checks'] if c['binding'].get('group') in held], row['id']
    table = tool_census.render_status(census, public)
    titles = {row['id']: row['title'] for row in census['tools']}
    assert not any('| ' + titles[i] + ' |' in table for i in only_held)
    assert all('| ' + titles[i] + ' |' in table for i in mixed)
    assert not any(re.search(r'(?<![\w-])' + re.escape(gid) + r'/', table) for gid in held)
    # The coverage table does not list an analysis engine whose tool is withheld.
    coverage = table.split('## Analysis coverage', 1)[1]
    engines = {row['id']: row['tool_id'] for row in census['backends']}
    assert {e for e, tool in engines.items() if tool in only_held}
    for engine, tool in engines.items():
        assert (('| ' + engine + ' |') in coverage) == (tool not in only_held), engine
