"""Synthetic sibling sources exercise lean bundles without scientific execution."""
import hashlib
import json
from pathlib import Path

import pytest


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / 'source'
    rows = []
    for name in ('alpha', 'beta', 'gamma', 'delta', 'epsilon'):
        path = root / f'src/ravel/data/skills/tools/{name}/SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(f'---\nname: {name}\n---\n# {name}\n\n'
                        '## Prepare\nPreparation text.\n\n### Detail\nNested text.\n'
                        '```text\n## Inside a fence\n```\n\n'
                        '## Inspect\nInspection text.\n')
        rows.append({'id': 'hb:' + name, 'kind': 'hb', 'title': name,
                     'summary': 'Sibling procedure', 'links': {},
                     'source': {'path': str(path.relative_to(root)),
                                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}})
    rows += [{'id': 'check:sibling', 'kind': 'check', 'summary': 'Check the supplied inputs', 'links': {}},
             {'id': 'trap:sibling', 'kind': 'trap', 'summary': 'Inspect the declared basis', 'links': {}},
             {'id': 'op:sibling-generation', 'kind': 'op', 'title': 'Sibling generation', 'summary': '',
              'op': {'examples': []},
              'links': {'handbooks': ['hb:' + n for n in ('alpha', 'beta', 'gamma', 'delta', 'epsilon')],
                        'checks': ['check:sibling'], 'traps': ['trap:sibling']}}]
    atlas = write_json(root / 'atlas.json', {'schema_version': 1, 'kind': 'knowledge-atlas', 'entries': rows})
    premise = {'id': 'trap:sibling', 'statement': 'Retain the declared basis.',
               'predicate': {'any': [{'operations_any': ['sibling-generation']}]}}
    premises = write_json(root / 'premises.json', {'schema_version': 1, 'kind': 'physics-premises',
                                                 'premises': [premise], 'conventions': []})
    roles = write_json(root / 'bindings.json', {'schema_version': 1, 'roles': {}})
    card = {'id': 'generator-sibling', 'family': 'production', 'reviewed_by': [],
            'must_check': ['check:sibling'], 'independence': {'kind': 'none'},
            'knowledge': {'must_read': ['hb:alpha'],
                          'derive': ['handbooks_for_node', 'checks_judging_node', 'premises_firing'],
                          'forbidden': [], 'budget_tokens': 24000}}
    binding = {'workspace': tmp_path / 'workspace', 'atlas_path': atlas, 'source_root': root,
               'premises_path': premises, 'role_bindings_path': roles}
    facts = {'node_id': 'node-sibling', 'operation': 'sibling-generation'}
    return card, facts, binding


def test_generator_work_order_caps_procedures(sources):
    from ravel.workflow.knowledge_bundles import materialize, bind_work_order
    card, facts, binding = sources
    order = {'node_id': facts['node_id'], 'operation': facts['operation'], 'knowledge': card['knowledge']}
    result = bind_work_order(order, card, binding)
    index = result['knowledge_bundle']
    assert len([i for i in index['items'] if i['kind'] == 'hb']) == 3
    assert result['handbooks'] == ['hb:alpha', 'hb:beta', 'hb:delta']
    assert {'check:sibling', 'trap:sibling'} <= set(index['served_ids'])
    assert materialize(card, facts, {**binding, 'workspace': Path(binding['workspace']).with_name('other')})['bundle_sha256'] == index['bundle_sha256']


def test_cited_id_must_be_in_atlas_and_served(sources):
    from ravel.workflow.knowledge_bundles import materialize, validate_cited_ids
    card, facts, binding = sources
    index = materialize(card, facts, binding)
    with pytest.raises(ValueError, match='unknown atlas ID'):
        validate_cited_ids({'knowledge_used': ['hb:invented']}, index, atlas_path=binding['atlas_path'])
    with pytest.raises(ValueError, match='unserved'):
        validate_cited_ids({'knowledge_used': ['hb:epsilon']}, index, atlas_path=binding['atlas_path'])
    assert validate_cited_ids({'knowledge_used': ['hb:alpha']}, index, atlas_path=binding['atlas_path']) == ['hb:alpha']


def test_omission_census_lists_every_capped_item_per_order(sources):
    from ravel.workflow.knowledge_bundles import bind_work_order, omission_census
    card, facts, binding = sources
    first = bind_work_order(facts, card, binding)
    second = bind_work_order({**facts, 'node_id': 'other-node'}, card,
                             {**binding, 'workspace': Path(binding['workspace']).with_name('other')})
    census = omission_census([first, second])
    for node in ('node-sibling', 'other-node'):
        assert {r['id'] for r in census if r['node_id'] == node and r['reason'] == 'procedural_cap'} == {
            'hb:gamma', 'hb:epsilon', *{'hb:' + n + '#inspect' for n in ('alpha', 'beta', 'gamma', 'delta', 'epsilon')}}


def test_section_serving_excludes_siblings_frontmatter_and_keeps_nested(sources):
    from ravel.workflow.knowledge_bundles import serve_section
    _, _, binding = sources
    text = serve_section('hb:alpha', 'prepare', binding)
    assert text.startswith('## Prepare\n')
    assert '### Detail' in text and '## Inside a fence' in text
    assert 'Inspection text' not in text and 'name: alpha' not in text
    with pytest.raises(ValueError, match='unknown handbook section'):
        serve_section('hb:alpha', 'absent', binding)


def test_only_pinned_handbooks_are_read_as_procedures(sources):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    path = Path(binding['source_root']) / 'src/ravel/data/skills/tools/alpha/SKILL.md'
    path.write_text(path.read_text() + 'Changed source.\n')
    with pytest.raises(ValueError, match='handbook source changed'):
        materialize(card, facts, binding)


def test_unresolved_must_read_refuses_before_writes(sources):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    card['knowledge']['must_read'] = ['hb:invented']
    with pytest.raises(ValueError, match='unknown atlas ID'):
        materialize(card, facts, binding)
    assert not Path(binding['workspace']).exists()


def test_consult_keeps_full_handbooks_without_cap(sources):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    card['family'] = 'consult'
    index = materialize(card, facts, binding)
    handbooks = [i for i in index['items'] if i['kind'] == 'hb']
    assert len(handbooks) == 5 and index['procedural_cap_exempt']
    for item in handbooks:
        text = (Path(binding['workspace']) / item['path']).read_text()
        assert 'Preparation text' in text and 'Inspection text' in text
    assert not [i for i in index['omitted'] if i['reason'] == 'procedural_cap']


def test_selected_sections_count_individually_toward_cap(sources):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    facts['handbook_sections'] = {'hb:alpha': ['inspect', 'prepare']}
    index = materialize(card, facts, binding)
    assert [(i['id'], i['section']) for i in index['items'] if i['kind'] == 'hb'] == [
        ('hb:alpha', 'inspect'), ('hb:alpha', 'prepare'), ('hb:beta', 'prepare')]


@pytest.mark.parametrize('cap', [0, True, '3'])
def test_invalid_procedural_cap_refused(sources, cap):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    card['knowledge']['max_procedural_items'] = cap
    with pytest.raises(ValueError, match='max_procedural_items'):
        materialize(card, facts, binding)


def test_must_read_above_cap_and_required_budget_refused(sources):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    card['knowledge']['must_read'] = ['hb:alpha', 'hb:beta', 'hb:delta', 'hb:gamma']
    with pytest.raises(ValueError, match='must_read procedural items exceed cap'):
        materialize(card, facts, binding)
    card['knowledge']['must_read'] = ['hb:alpha']
    card['knowledge']['budget_tokens'] = 1
    with pytest.raises(ValueError, match='required knowledge exceeds budget'):
        materialize(card, facts, binding)
    assert not Path(binding['workspace']).exists()


def test_reviewer_cold_bundle_never_contains_lesson_or_headline(sources):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    card['independence']['kind'] = 'specialist'
    data = json.loads(Path(binding['role_bindings_path']).read_text())
    data['roles'][card['id']] = {'include': ['lesson:sibling', 'producer_headline:sibling']}
    write_json(Path(binding['role_bindings_path']), data)
    index = materialize(card, facts, binding)
    assert not set(index['served_ids']) & {'lesson:sibling', 'producer_headline:sibling'}
    assert {(r['id'], r['reason']) for r in index['omitted']} >= {
        ('lesson:sibling', 'forbidden'), ('producer_headline:sibling', 'forbidden')}


def test_disallowed_handbook_path_refused(sources):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    atlas = json.loads(Path(binding['atlas_path']).read_text())
    atlas['entries'][0]['source']['path'] = 'docs/sibling.md'
    write_json(Path(binding['atlas_path']), atlas)
    with pytest.raises(ValueError, match='critical-path tool handbooks'):
        materialize(card, facts, binding)


def test_tampered_bundle_and_missing_citation_list_refused(sources):
    from ravel.workflow.knowledge_bundles import materialize, validate_cited_ids
    card, facts, binding = sources
    index = materialize(card, facts, binding)
    with pytest.raises(ValueError, match='knowledge_used must be an ID list'):
        validate_cited_ids({}, index, atlas_path=binding['atlas_path'])
    index['items'].append({'id': 'hb:epsilon'})
    with pytest.raises(ValueError, match='bundle digest differs'):
        validate_cited_ids({'knowledge_used': ['hb:epsilon']}, index, atlas_path=binding['atlas_path'])


def test_atlas_registers_premise_conventions():
    from ravel.paths import package_data_path
    from ravel.workflow.knowledge import load_atlas
    document = json.loads(package_data_path('knowledge', 'premises.json').read_text())
    ids = {row['id'] for row in load_atlas()['entries']}
    assert {row['id'] for row in document['conventions']} <= ids


def test_updated_handbook_changes_bundle_and_order_digest(sources):
    from ravel.workflow.knowledge_bundles import bind_work_order
    card, facts, binding = sources
    first = bind_work_order(facts, card, binding)
    atlas = json.loads(Path(binding['atlas_path']).read_text())
    path = Path(binding['source_root']) / atlas['entries'][0]['source']['path']
    path.write_text(path.read_text().replace('Preparation text.', 'Revised preparation text.'))
    atlas['entries'][0]['source']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(Path(binding['atlas_path']), atlas)
    second = bind_work_order(facts, card, {**binding, 'workspace': Path(binding['workspace']).with_name('updated')})
    assert first['order_sha256'] != second['order_sha256']
    assert first['knowledge_bundle']['bundle_sha256'] != second['knowledge_bundle']['bundle_sha256']


@pytest.mark.parametrize('role', ['analyst', 'coder', 'code_reviewer', 'physics_reviewer'])
def test_construction_brief_preserves_original_projection(role):
    from ravel.workflow.agentrivet_brief import Briefs
    from ravel.workflow.knowledge_bundles import agentrivet_brief
    briefs = Briefs(routine='SiblingRoutine', contract=['Declared sibling basis'])
    card = {'id': 'upstream-agentrivet-' + role.replace('_', '-')}
    assert agentrivet_brief(card, briefs, 'sibling-stage') == briefs(role, 'sibling-stage', None)


def test_registered_generator_binding_and_schema(tmp_path):
    from jsonschema import Draft202012Validator
    from ravel.paths import package_data_path
    from ravel.workflow.role_registry import load, self_checks, card_sha256
    from ravel.workflow.knowledge_bundles import materialize
    workspace = tmp_path / 'empty-worker'
    index = materialize(load('generator'), {'node_id': 'node-sibling', 'operation': 'model-events'},
                        {'workspace': workspace})
    assert [i['id'] for i in index['items'] if i['kind'] == 'hb'] == [
        'hb:madgraph-launch', 'hb:lhapdf-pdf-sets', 'hb:pythia-shower-cards']
    assert {'trap:T6', 'trap:T11', 'trap:T12', 'conv:yield-basis'} <= set(index['served_ids'])
    assert index['self_check'] == self_checks('generator')
    assert index['card_sha256'] == card_sha256('generator')
    assert json.loads((workspace / 'inputs/knowledge/index.json').read_text()) == index
    for item in index['items']:
        assert hashlib.sha256((workspace / item['path']).read_bytes()).hexdigest() == item['sha256']
    schema = json.loads(package_data_path('knowledge', 'schema', 'bundle.json').read_text())
    assert not list(Draft202012Validator(schema).iter_errors(index))


def test_work_order_adds_requirements_without_weakening_card(sources):
    from ravel.workflow.knowledge_bundles import bind_work_order
    card, facts, binding = sources
    card['knowledge']['forbidden'] = ['lessons']
    order = {**facts, 'knowledge': {'must_read': ['hb:epsilon'], 'derive': [],
                                  'forbidden': [], 'max_procedural_items': 99}}
    result = bind_work_order(order, card, binding)
    assert result['knowledge']['must_read'] == ['hb:alpha', 'hb:epsilon']
    assert result['knowledge']['forbidden'] == ['lessons']
    assert result['knowledge_bundle']['max_procedural_items'] == 3
    assert {'hb:alpha', 'hb:epsilon'} <= set(result['knowledge_bundle']['served_ids'])
    assert card['knowledge']['must_read'] == ['hb:alpha']


def test_withheld_source_refused_by_section_and_materializer(sources):
    from ravel.workflow.knowledge_bundles import materialize, serve_section
    card, facts, binding = sources
    binding['withheld_ids'] = ['hb:alpha']
    with pytest.raises(ValueError, match='withheld handbook ID'):
        serve_section('hb:alpha', 'prepare', binding)
    with pytest.raises(ValueError, match='withheld required ID'):
        materialize(card, facts, binding)
    assert not Path(binding['workspace']).exists()


@pytest.mark.parametrize('command', ['adopt', 'pin-obligations'])
def test_worker_cli_preserves_work_order_commands(command, monkeypatch):
    from ravel.workflow import agent_worker, work_dispatch
    received = []
    monkeypatch.setattr(work_dispatch, 'main', lambda args: received.append(args) or 0)
    assert agent_worker.main([command, '--rundir', 'sibling-run']) == 0
    assert received == [[command, '--rundir', 'sibling-run']]


def test_registered_pitfall_serves_its_source_bullet(sources):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    atlas = json.loads(Path(binding['atlas_path']).read_text())
    row = atlas['entries'][0]
    path = Path(binding['source_root']) / row['source']['path']
    path.write_text(path.read_text() + '\n## Pitfalls\n- Sibling pitfall.\n- Other pitfall.\n')
    row['source']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    atlas['entries'].append({**row, 'id': 'hb:alpha#pitfall-1'})
    write_json(Path(binding['atlas_path']), atlas)
    card['knowledge']['must_read'] = ['hb:alpha#pitfall-1']
    index = materialize(card, facts, binding)
    item = next(i for i in index['items'] if i['id'] == 'hb:alpha#pitfall-1')
    assert (Path(binding['workspace']) / item['path']).read_text() == '- Sibling pitfall.\n'


def test_reviewer_obligations_cannot_be_dropped_by_selectors(sources, monkeypatch):
    from ravel.workflow import role_registry
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    card['reviewed_by'] = ['reviewer-sibling']
    card['knowledge']['derive'] = []
    monkeypatch.setattr(role_registry, 'load', lambda *args, **kwargs: {'must_check': ['check:sibling']})
    index = materialize(card, facts, binding)
    assert index['self_check'] == ['check:sibling']


@pytest.mark.parametrize('independence,sees', [({'kind': 'voting'}, {}),
                                               ({'kind': 'none'}, {'profile': 'blind'})])
def test_voting_and_blind_cards_refuse_order_supplied_lessons(sources, independence, sees):
    from ravel.workflow.knowledge_bundles import materialize
    card, facts, binding = sources
    card['independence'], card['sees'] = independence, sees
    for identity in ('lesson:sibling', 'producer_headline:sibling'):
        with pytest.raises(ValueError, match='forbidden required ID'):
            materialize(card, dict(facts, knowledge={'must_read': [identity]}), binding)
    assert not Path(binding['workspace']).exists()
    index = materialize(card, facts, binding)
    restriction = {'withheld_ids': [], 'forbidden': ['lessons', 'producer_headline']}
    from ravel.workflow.knowledge_atlas import digest, encode
    assert index['source_restriction_sha256'] == digest(encode(restriction))
