"""Synthetic manifest fragments, source custody and release projections; no native jobs."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.setup import manifest as mf, steps

ROOT = Path(__file__).resolve().parents[2]


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def group(gid='fictional-tool', depends=()):
    return {'id': gid, 'title': gid, 'depends_on': list(depends), 'size_gb': 0.25,
            'minutes': 1, 'steps': [{'id': 'write', 'kind': 'write_file',
                                    'path': '{P}/fictional', 'content': 'fictional'}],
            'checks': [{'id': gid + '-ready', 'kind': 'file', 'path': '{P}/fictional'}]}


@pytest.fixture
def tree(tmp_path):
    base = group('fictional-base')
    m = {'schema_version': 2, 'kind': 'ravel-toolchain-manifest', 'groups': [base],
         'default': {'groups': [base['id']], 'disk_gb': 1.0},
         'profiles': {'site': {'groups': [base['id']], 'disk_gb': 1.0}}, 'operations': [],
         'unreleased': {'groups': [], 'operations': []},
         'miniforge': {'assets': {p: {'sha256': '0' * 64} for p in mf.PLATFORMS}},
         'container_build': {'module': 'fictional', 'argv': []}}
    put(mf.manifest_path(tmp_path), m)
    put(tmp_path / 'native/setup/pdf-sets.json', {'schema_version': 1, 'kind': 'ravel-lhapdf-sets',
        'base_url': 'https://example.invalid/', 'sets': [
        {'name': 'FictionalSet', 'lhaid': 1, 'size': 1, 'sha256': '0' * 64}]})
    return tmp_path


def fragment(root, gid='fictional-tool', value=None):
    path = root / 'native/setup/groups' / (gid + '.json')
    put(path, value if value is not None else {'group': group(gid)})
    return path


def hold(gid):
    return {'groups': [{'id': gid, 'check': gid + '-ready', 'reason': 'fictional hold'}],
            'operations': [{'mode': 'fictional-operation', 'groups': [gid]}]}


def assert_refused(root, *terms):
    with pytest.raises(mf.ManifestError) as error:
        mf.load(root)
    for term in terms:
        assert term in str(error.value)


def test_duplicate_group_in_main_and_fragment(tree):
    fragment(tree, 'fictional-base')
    assert_refused(tree, 'fictional-base', 'toolchain-manifest.json', 'fictional-base.json')


def test_duplicate_group_in_two_fragments(tree):
    fragment(tree)
    fragment(tree, 'fictional-copy', {'group': group()})
    assert_refused(tree, 'fictional-tool', 'fictional-tool.json', 'fictional-copy.json')


def test_duplicate_check_names_both_files(tree):
    fragment(tree)
    other = group('fictional-other'); other['checks'][0]['id'] = 'fictional-tool-ready'
    fragment(tree, other['id'], {'group': other})
    assert_refused(tree, 'fictional-tool-ready', 'fictional-tool.json', 'fictional-other.json')


@pytest.mark.parametrize('field', ['profiles', 'profile', 'default', 'operations', 'refusal_classes', 'engine'])
def test_wrapper_keys_refused(tree, field):
    fragment(tree, value={'group': group(), field: {}})
    assert_refused(tree, 'fictional-tool.json', field)


def test_stem_mismatch(tree):
    fragment(tree, 'fictional-wrong', {'group': group()})
    assert_refused(tree, 'fictional-tool', 'fictional-wrong.json')


def test_two_groups_refused(tree):
    fragment(tree, value={'group': [group(), group('fictional-other')]})
    assert_refused(tree, 'fictional-tool.json', 'group')


def test_duplicate_json_key(tree):
    p = fragment(tree); p.write_text('{"group":{},"group":{}}')
    assert_refused(tree, 'fictional-tool.json', 'duplicate JSON key')


@pytest.mark.parametrize('raw', ['{"group":NaN}', '{"group":Infinity}', '{broken', '\udcff'])
def test_invalid_json(tree, raw):
    p = fragment(tree); p.write_bytes(raw.encode('utf-8', errors='surrogateescape'))
    assert_refused(tree, 'fictional-tool.json')


def test_oversized_fragment(tree):
    p = fragment(tree); p.write_bytes(b' ' * (mf.MAX_JSON_BYTES + 1))
    assert_refused(tree, 'fictional-tool.json', '4 MiB')


def test_other_group_hold_refused(tree):
    fragment(tree, value={'group': group(), 'unreleased': hold('fictional-other')})
    assert_refused(tree, 'fictional-tool.json', 'fictional-other')


def test_other_group_operation_hold_refused(tree):
    rows = hold('fictional-tool'); rows['operations'][0]['groups'] = ['fictional-other']
    fragment(tree, value={'group': group(), 'unreleased': rows})
    assert_refused(tree, 'fictional-tool.json', 'fictional-other')


@pytest.mark.parametrize('name', ['fictional-link.json', 'README.md', 'group.schema.json'])
def test_symlink_refused(tree, name):
    p = tree / 'native/setup/groups' / name; p.parent.mkdir(parents=True, exist_ok=True)
    p.symlink_to(mf.manifest_path(tree))
    assert_refused(tree, name, 'symlink')


@pytest.mark.parametrize('kind', ['directory', 'text', 'hidden'])
def test_unexpected_entry_refused(tree, kind):
    p = tree / 'native/setup/groups' / {'directory': 'fictional.json', 'text': 'fictional.txt', 'hidden': '.fictional'}[kind]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir() if kind == 'directory' else p.write_text('fictional')
    assert_refused(tree, p.name)


def test_symlink_directory_refused(tree, tmp_path):
    target = tmp_path / 'fictional-directory'; target.mkdir()
    (tree / 'native/setup/groups').symlink_to(target, target_is_directory=True)
    assert_refused(tree, 'groups', 'symlink')


def test_unknown_dependency_names_fragment(tree):
    fragment(tree, value={'group': group(depends=['fictional-absent'])})
    assert_refused(tree, 'fictional-tool.json', 'fictional-tool', 'fictional-absent')


def test_dependency_cycle_names_sources(tree):
    fragment(tree, value={'group': group(depends=['fictional-other'])})
    fragment(tree, 'fictional-other', {'group': group('fictional-other', ['fictional-tool'])})
    assert_refused(tree, 'fictional-tool.json', 'fictional-other.json', 'cycle')


@pytest.mark.parametrize('label', ['optional', 'add-on', 'extra'])
def test_tool_labels_refused(tree, label):
    g = group(); g['description'] = 'A ' + label + ' tool'
    fragment(tree, value={'group': g})
    assert_refused(tree, 'fictional-tool', label)


def test_tool_label_key_refused(tree):
    g = group(); g['optional'] = False
    fragment(tree, value={'group': g})
    assert_refused(tree, 'fictional-tool', 'optional')


def test_fragment_validation_names_source(tree):
    g = group(); g['steps'][0] = {'id': 'fictional-bad', 'kind': 'git', 'commit': 'fictional'}
    fragment(tree, value={'group': g})
    assert_refused(tree, 'fictional-tool.json', '40-hex')


def test_new_group_default_and_reserved_fields(tree):
    g = group(depends=['fictional-base']); g['steps'][0]['cleanup'] = ['{P}/fictional-temp']
    g['components'] = {'fictional-part': {'steps': [], 'size_gb': 0.1, 'checks': []}}
    fragment(tree, value={'group': g})
    m, _ = mf.load(tree)
    assert m['groups'] == [group('fictional-base'), g]
    assert m['default'] == {'groups': ['fictional-base', 'fictional-tool'], 'disk_gb': 1.25}
    assert m['profiles'] == {'site': {'groups': ['fictional-base'], 'disk_gb': 1.0}}
    from jsonschema import Draft202012Validator
    schema = mf.read_json(ROOT / 'native/setup/groups/group.schema.json')
    assert list(Draft202012Validator(schema).iter_errors({'group': g})) == []


def test_withheld_fragment_not_selected(tree):
    fragment(tree, value={'group': group(depends=['fictional-base']), 'unreleased': hold('fictional-tool')})
    m, _ = mf.load(tree)
    assert m['default'] == {'groups': ['fictional-base'], 'disk_gb': 1.0}
    assert mf.profile_groups(m) == ['fictional-base']
    assert mf.profile_groups(m, only=['fictional-tool']) == ['fictional-base', 'fictional-tool']


def test_new_groups_stable_dependency_order(tree):
    fragment(tree, 'fictional-alpha', {'group': group('fictional-alpha', ['fictional-zeta'])})
    fragment(tree, 'fictional-beta', {'group': group('fictional-beta')})
    fragment(tree, 'fictional-zeta', {'group': group('fictional-zeta')})
    assert [g['id'] for g in mf.load(tree)[0]['groups']] == [
        'fictional-base', 'fictional-beta', 'fictional-zeta', 'fictional-alpha']


def split_module():
    spec = importlib.util.spec_from_file_location('split_group_helper', ROOT / 'scripts/setup/split_group.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize('gid', ['fictional-base', 'fictional-tool'])
def test_split_preserves_view_fingerprints_and_holds(tree, gid):
    path = mf.manifest_path(tree); m = mf.read_json(path)
    m['groups'].append(group()); m['unreleased'] = hold('fictional-tool'); put(path, m)
    original, cat = mf.load(tree)
    values = mf.variables(tree / 'prefix', tree, 'linux-x86_64')
    before = [steps.fingerprint(g['id'], s, values, tree, cat) for g in original['groups'] for s in g['steps']]
    helper = split_module()
    helper.split_group(tree, gid, check=True)
    assert mf.read_json(path) == m and not (tree / 'native/setup/groups' / (gid + '.json')).exists()
    helper.split_group(tree, gid)
    assert mf.view(tree) == original
    assert mf.read_json(path)['unreleased'] == m['unreleased']
    assert [steps.fingerprint(g['id'], s, values, tree, cat) for g in mf.view(tree)['groups'] for s in g['steps']] == before
    snapshot = {p: p.read_bytes() for p in tree.rglob('*') if p.is_file()}
    helper.split_group(tree, gid, check=True)
    assert snapshot == {p: p.read_bytes() for p in tree.rglob('*') if p.is_file()}


def test_split_refuses_digest_change_without_writes(tree, monkeypatch):
    helper = split_module()
    snapshot = {p: p.read_bytes() for p in tree.rglob('*') if p.is_file()}
    calls = iter(['fictional-before', 'fictional-after'])
    monkeypatch.setattr(mf, 'canonical_sha256', lambda m: next(calls))
    with pytest.raises(mf.ManifestError, match='digest'):
        helper.split_group(tree, 'fictional-base')
    assert snapshot == {p: p.read_bytes() for p in tree.rglob('*') if p.is_file()}


def test_real_repository_join_identity_profiles_and_digest():
    source = mf.read_json(mf.manifest_path(ROOT)); merged, _ = mf.load(ROOT)
    main = __import__('group_fragment_fixture').extend_group_expectation(source, ROOT)
    joined = copy.deepcopy(main); order = joined.pop('group_order'); rows = mf.by_id(main)
    fragment_ids = []
    for p in (ROOT / 'native/setup/groups').glob('*.json'):
        if p.name != 'group.schema.json':
            g = mf.read_json(p)['group']; rows[g['id']] = g; fragment_ids.append(g['id'])
    assert set(fragment_ids) <= set(order)
    joined['groups'] = [rows[gid] for gid in order]
    assert [g['id'] for g in merged['groups']] == order
    # The pin resolver rewrites a group that names a source ledger; every other group is its file's text.
    bound = {gid for gid in order if 'pin_file' in rows[gid]}
    assert bound.isdisjoint(source['group_order'])
    assert {k: v for k, v in joined.items() if k != 'groups'} == {k: v for k, v in merged.items() if k != 'groups'}
    assert ([g for g in joined['groups'] if g['id'] not in bound]
            == [g for g in merged['groups'] if g['id'] not in bound])
    # Groups declared only as fragments follow the positioned groups; their release rows follow the main rows.
    positioned = source['group_order']; held = source.get('unreleased', {})
    assert [g['id'] for g in merged['groups']][:len(positioned)] == positioned
    assert not any(g['id'] in positioned for g in merged['groups'][len(positioned):])
    for key in ('groups', 'operations'):
        assert merged.get('unreleased', {}).get(key, [])[:len(held.get(key, []))] == held.get(key, [])
    # A fragment-only group joins the default toolchain unless a release row withholds it.
    pending = [gid for gid in order if gid not in positioned]
    additions = [gid for gid in pending if gid not in mf.unreleased_groups(merged)]
    from decimal import Decimal
    assert merged['default']['groups'] == [*source['default']['groups'], *additions]
    assert merged['default']['disk_gb'] == float(Decimal(str(source['default']['disk_gb']))
                                                 + sum(Decimal(str(rows[gid]['size_gb'])) for gid in additions))
    # Without the fragment-only groups and their release rows, the document is the original split's join.
    from test_higgs_installers import positioned_group_view
    base = copy.deepcopy(source); base.pop('group_order'); base['groups'] = [rows[gid] for gid in positioned]
    view = positioned_group_view(merged, positioned)
    assert {k: v for k, v in base.items() if k != 'default'} == {k: v for k, v in view.items() if k != 'default'}
    assert merged['default'] == main['default']
    assert merged['profiles'] == main['profiles'] and set(merged['profiles']) == {'site'}
    assert len(merged['profiles']['site']['groups']) == 7
    result = subprocess.run([sys.executable, '-B', '-m', 'ravel.setup.manifest', 'view',
                             '--canonical-sha256', '--root', str(ROOT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == mf.canonical_sha256(merged)


def test_missing_or_empty_directory_unchanged(tree):
    before = mf.load(tree)[0]
    (tree / 'native/setup/groups').mkdir()
    assert mf.load(tree)[0] == before


def test_generator_versions_identical_to_inline_document():
    from ravel.physics.generator_versions import installed_madgraph
    document, _ = mf.load(ROOT)
    assert installed_madgraph('/fictional/prefix', repo=ROOT) == installed_madgraph(
        '/fictional/prefix', repo=ROOT, document=document)


def test_licence_policy_cli_checks_fragment(tree, monkeypatch, capsys):
    from ravel.setup import licence_policy as policy
    g = group(); g['licenses'] = [{'component': 'fictional-module', 'spdx': 'GPL-3.0-only'}]
    g['steps'] = [{'id': 'fictional-pip', 'kind': 'pip', 'python': '{REPO}/.venv/bin/python',
                   'requirements': ['fictional-module==1.0']}]
    fragment(tree, value={'group': g})
    assert policy.check(mf.view(tree))
    monkeypatch.setattr(policy, 'repo_root', lambda: tree)
    put(tree / 'native/setup/tools-pins.json', {'tools': {}})
    put(tree / 'native/setup/tools-pins.schema.json', {'type': 'object'})
    assert policy.main([]) == 1
    assert 'fictional-tool' in capsys.readouterr().out


def test_atlas_pins_defining_file_and_tracks_mutation():
    from ravel.workflow import knowledge_atlas as ka
    atlas = ka.generate(ROOT)
    rows = {r['installer_group']: r for r in atlas['entries'] if r.get('installer_group')}
    merged = mf.view(ROOT)
    # The source atlas exposes release members and pins every defining source.
    assert set(rows) == set(mf.by_id(merged)) - mf.unreleased_groups(merged)
    sources = {p['path'] for p in atlas['generator']['sources']}
    assert all('native/setup/groups/' + g['id'] + '.json' in sources
               for g in merged['groups'] if (ROOT / 'native/setup/groups' / (g['id'] + '.json')).exists())
    for gid, row in rows.items():
        path = ROOT / 'native/setup/groups' / (gid + '.json')
        if not path.exists():
            path = mf.manifest_path(ROOT)
        assert row['source']['path'] == path.relative_to(ROOT).as_posix()
        assert row['source']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_software_skills_read_fragment(tree, monkeypatch):
    from ravel.workflow import agent_surface
    path = mf.manifest_path(tree); main = mf.read_json(path)
    main['groups'][0]['version_contract'] = {}; put(path, main)
    g = group(); g['version_contract'] = {'fictional-tool': '1.0'}
    fragment(tree, value={'group': g})
    monkeypatch.setattr(agent_surface, 'observe', lambda *a, **k: {})
    skills = agent_surface.software_skills(mf.manifest_path(tree), packages=[], executables=[], all_groups=True)
    assert 'software-fictional-tool' in skills


def _direct_main_reads(text, ignored_functions=()):
    import ast
    tree = ast.parse(text)
    markers = ('toolchain-manifest.json', 'manifest_path', 'Path(manifest)')
    raw_readers = {'loads', 'read', 'read_json', '_tree_json', 'data', 'read_text', 'read_bytes'}
    safe_fallbacks = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp) and isinstance(node.body, ast.Call):
            name = node.body.func.attr if isinstance(node.body.func, ast.Attribute) else getattr(node.body.func, 'id', '')
            if name == 'view' and 'toolchain-manifest.json' in ast.unparse(node.test):
                safe_fallbacks.update(id(n) for n in ast.walk(node.orelse))
    findings = []
    scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        if getattr(scope, 'name', None) in ignored_functions:
            continue
        def walk_scope(node):
            yield node
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                yield from walk_scope(child)
        nodes = list(walk_scope(scope))
        tainted = set()
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = ast.unparse(node.value) if node.value else ''
                if any(marker in value for marker in markers):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    tainted.update(n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name))
        for node in nodes:
            if not isinstance(node, ast.Call) or id(node) in safe_fallbacks:
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
            if name not in raw_readers:
                continue
            code = ast.unparse(node)
            used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if any(marker in code for marker in markers) or used & tainted:
                findings.append(code)
    return sorted(set(findings))


def test_reader_guard_detects_literal_path_and_loader_bypass():
    assert _direct_main_reads('path = root / "native/setup/toolchain-manifest.json"\nm = json.loads(path.read_text())')
    assert _direct_main_reads('m = mf.read_json(mf.manifest_path(root))')
    assert _direct_main_reads('m = read(root, "native/setup/toolchain-manifest.json", {})')
    assert not _direct_main_reads('m = mf.view(root)')


def test_wrapper_schema_matches_acceptance_and_reserved_fields(tree):
    from jsonschema import Draft202012Validator
    schema = mf.read_json(ROOT / 'native/setup/groups/group.schema.json')
    validator = Draft202012Validator(schema)
    g = group(); g['fictional_future_field'] = {'value': 3}
    g['steps'][0]['fictional_future_field'] = 4
    g['steps'][0]['cleanup'] = ['{P}/fictional-temp']; g['components'] = {'fictional-part': {}}
    wrapper = {'group': g, 'unreleased': hold(g['id'])}
    assert list(validator.iter_errors(wrapper)) == []
    fragment(tree, value=wrapper)
    assert mf.load(tree)[0]['groups'][-1] == g
    for key in ('profiles', 'operations', 'engine'):
        assert list(validator.iter_errors(dict(wrapper, **{key: {}})))


def test_fragment_missing_size_names_source(tree):
    g = group(); del g['size_gb']
    fragment(tree, value={'group': g})
    assert_refused(tree, 'fictional-tool.json', 'fictional-tool', 'size_gb')


def test_fragment_hold_wrong_check_names_source(tree):
    rows = hold('fictional-tool'); rows['groups'][0]['check'] = 'fictional-absent'
    fragment(tree, value={'group': group(), 'unreleased': rows})
    assert_refused(tree, 'fictional-tool.json', 'fictional-tool', 'check')


def test_duplicate_check_in_main_and_fragment(tree):
    g = group(); g['checks'][0]['id'] = 'fictional-base-ready'
    fragment(tree, value={'group': g})
    assert_refused(tree, 'fictional-base-ready', 'toolchain-manifest.json', 'fictional-tool.json')


def test_named_manifest_outside_a_tree_is_read_as_given(tree, monkeypatch, capsys):
    from ravel.setup import licence_policy as policy
    from ravel.workflow import agent_surface
    document = mf.read_json(mf.manifest_path(tree))
    planted = group(); planted['licenses'] = [{'component': 'fictional-module', 'spdx': 'GPL-3.0-only'}]
    planted['steps'] = [{'id': 'fictional-pip', 'kind': 'pip', 'python': '{REPO}/.venv/bin/python',
                         'requirements': ['fictional-module==1.0']}]
    planted['version_contract'] = {'fictional-tool': '1.0'}
    document['groups'][0]['version_contract'] = {}
    document['groups'].append(planted)
    named = tree / 'fictional-elsewhere/toolchain-manifest.json'
    put(named, document)
    monkeypatch.setattr(policy, 'repo_root', lambda: tree)
    put(tree / 'native/setup/tools-pins.json', {'tools': {}})
    put(tree / 'native/setup/tools-pins.schema.json', {'type': 'object'})
    assert policy.main(['--manifest', str(named)]) == 1
    assert 'fictional-tool' in capsys.readouterr().out
    monkeypatch.setattr(agent_surface, 'observe', lambda *a, **k: {})
    skills = agent_surface.software_skills(named, packages=[], executables=[], all_groups=True)
    assert 'software-fictional-tool' in skills


def test_handbook_gate_reports_on_a_tree_without_a_toolchain_manifest(tmp_path):
    from ravel.validation import check_agent_surface as surface
    (tmp_path / surface.HANDBOOK_ROOT).mkdir(parents=True)
    errors, _ = surface.check_handbooks(str(tmp_path))
    assert errors == ['no tool handbooks found']


def test_fragment_hold_joins_a_main_hold_block_without_operation_rows(tree):
    path = mf.manifest_path(tree); main = mf.read_json(path)
    main['unreleased'] = {'groups': []}; put(path, main)
    fragment(tree, value={'group': group(depends=['fictional-base']), 'unreleased': hold('fictional-tool')})
    merged, _ = mf.load(tree)
    assert mf.unreleased_groups(merged) == {'fictional-tool'}
    assert mf.unreleased_operations(merged) == {'fictional-operation'}
    assert merged['default']['groups'] == ['fictional-base']


