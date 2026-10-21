"""Source-independent must-read completeness and fail-closed knowledge controls."""
import hashlib
import json
from pathlib import Path

import pytest

from ravel.controller.instructions import catalogue, compiler, delivery
from ravel.workflow import role_registry

ROOT = Path(__file__).resolve().parents[3]


def records(value, identity):
    """Test oracle: locate exact IDs directly in source JSON, without catalogue selectors."""
    found = []
    if isinstance(value, dict):
        if value.get('id') == identity:
            found.append(value)
        for child in value.values():
            found.extend(records(child, identity))
    elif isinstance(value, list):
        for child in value:
            found.extend(records(child, identity))
    return found


def fixture_tree(tmp_path, monkeypatch, *, identity='conv:fictional-ledger', document=None,
                 source='knowledge/ledger.json', text=None, digest=None):
    if document is None:
        document = {'bundles': [{'nested': {'id': identity, 'title': 'Short title',
                     'obligation': 'Inspect the complete fictional ledger before delivery.',
                     'extra': {'threshold': 17, 'instructions': ['Keep all fields.']}}}]}
    text = text if text is not None else json.dumps(document, indent=2) + '\n'
    source_path = tmp_path / source
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(text)
    atlas = {'entries': [{'id': identity, 'kind': identity.split(':')[0], 'summary': 'Short summary',
              'source': {'path': source, 'sha256': digest or hashlib.sha256(text.encode()).hexdigest()}}]}
    atlas_path = tmp_path / catalogue.ATLAS_PATH
    atlas_path.parent.mkdir(parents=True, exist_ok=True)
    atlas_path.write_text(json.dumps(atlas))
    sources = {'canonical': [], 'mirrors': [], 'discover': [], 'preamble': [], 'protocols': {},
               'step_kinds': {}, 'checkins': {}, 'governing_skills': []}
    card = {'id': 'fictional-reader', 'knowledge': {'must_read': [identity]}}
    monkeypatch.setattr(role_registry, 'registry_sha256', lambda **kw: 'fictional-registry')

    def build(view=None):
        built, manifests = catalogue.build(tmp_path, sources=sources, cards=[card], citations={'rows': []},
                                           view=view or compiler.View(tmp_path))
        return catalogue.Catalogue(built, manifests)
    return build, source_path, identity, document, sources


def delivered(cat, identity):
    return [cat.units[uid] for uid in cat.resolve('knowledge:' + identity)]


def test_nested_record_keeps_every_field_and_source(tmp_path, monkeypatch):
    build, path, identity, document, _ = fixture_tree(tmp_path, monkeypatch)
    cat = build()
    units = delivered(cat, identity)
    assert [json.loads(u['text']) for u in units] == records(document, identity)
    assert all(u['source'] == path.relative_to(tmp_path).as_posix() for u in units)
    assert all(u['kind'] == 'duty' and u['sha256'] == compiler.digest_text(u['text']) for u in units)
    metadata = next(r for r in cat.document['files'] if r['path'] == units[0]['source'])
    assert metadata['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert metadata['units'] == len(cat.by_source[metadata['path']])
    assert catalogue.coverage_problems(cat) == []


@pytest.mark.parametrize('failure', ['missing', 'unresolved', 'ambiguous', 'digest', 'withheld'])
def test_bad_source_refuses_summary_substitution(tmp_path, monkeypatch, failure):
    identity = 'conv:fictional-ledger'
    document = {'id': identity, 'obligation': 'Preserve the full fictional record.'}
    if failure == 'unresolved':
        document['id'] += '-different'
    if failure == 'ambiguous':
        document = {'left': document, 'right': dict(document)}
    build, path, _, _, _ = fixture_tree(tmp_path, monkeypatch, document=document,
                                       digest='0' * 64 if failure == 'digest' else None)
    if failure == 'missing':
        path.unlink()
    view = compiler.View(tmp_path, shipped={catalogue.ATLAS_PATH}) if failure == 'withheld' else None
    with pytest.raises(ValueError):
        build(view)


def test_family_mandate_inside_a_complete_knowledge_record_is_detected(tmp_path, monkeypatch):
    """Complete must-read records are delivered duties, so the family acceptance scans them too."""
    build, _, identity, _, _ = fixture_tree(tmp_path, monkeypatch)
    assert catalogue.family_mandates(build()) == []  # positive control
    document = {'nested': {'id': identity, 'obligation': 'Assign the reviewer from a different model family.'}}
    build, _, identity, _, _ = fixture_tree(tmp_path, monkeypatch, document=document)
    cat = build()
    assert catalogue.family_mandates(cat) == [u['id'] for u in delivered(cat, identity)]


def test_computed_check_delivers_complete_source(tmp_path, monkeypatch):
    text = '# Full fictional check\ndef inspect_record(value):\n    return value.get("hidden_obligation") == 17\n'
    build, path, identity, _, _ = fixture_tree(tmp_path, monkeypatch, identity='check:fictional-inspection',
                                               source='checks/inspect.py', text=text)
    units = delivered(build(), identity)
    assert compiler.normalise(text) in '\n'.join(u['text'] for u in units)
    assert all(u['source'] == path.relative_to(tmp_path).as_posix() for u in units)


def test_published_view_is_the_content_and_digest_boundary(tmp_path, monkeypatch):
    public = {'nested': {'id': 'conv:fictional-ledger', 'obligation': 'Public retained instruction.'}}
    build, path, identity, _, _ = fixture_tree(tmp_path, monkeypatch, document=public)
    published = path.read_text()
    path.write_text('PRIVATE SOURCE TEXT')
    view = compiler.View(tmp_path, transforms={path.relative_to(tmp_path).as_posix(): {}},
                         publish=lambda *args: published.encode())
    assert [json.loads(u['text']) for u in delivered(build(view), identity)] == records(public, identity)


def test_markdown_protocol_keeps_full_section(tmp_path, monkeypatch):
    text = '# Protocols\n\n## P7: Fictional inspection\n\nInspect every retained field.\n\nKeep the hidden note.\n\n## P8: Other\n\nOther section.\n'
    build, _, identity, _, sources = fixture_tree(tmp_path, monkeypatch, identity='proto:P7',
                                                  source='knowledge/protocols.md', text=text)
    sources['canonical'] = [{'path': 'knowledge/protocols.md', 'kind': 'workflow', 'nodes': ['step.fixture']}]
    actual = '\n'.join(u['text'] for u in delivered(build(), identity))
    assert 'Inspect every retained field.' in actual and 'Keep the hidden note.' in actual
    assert 'Other section.' not in actual


ATLAS = json.loads((ROOT / catalogue.ATLAS_PATH).read_text())['entries']
ACTUAL_CARDS = role_registry.all_cards(roles_root=ROOT / 'src/ravel/data/roles')
MUST_READ = {identity for card in ACTUAL_CARDS
             for identity in card['knowledge']['must_read']}
SOURCE_ROWS = [r for r in ATLAS if r['id'] in MUST_READ and
               (r['source']['path'].endswith('.json') or r['kind'] == 'check')]


@pytest.fixture(scope='module')
def actual_catalogue():
    # The release owner rebuilds installed data before running the package suite.
    return catalogue.installed()


@pytest.mark.parametrize('row', SOURCE_ROWS, ids=lambda row: row['id'])
def test_actual_must_read_matches_independently_located_source(actual_catalogue, row):
    text = (ROOT / row['source']['path']).read_text()
    units = delivered(actual_catalogue, row['id'])
    if row['source']['path'].endswith('.json'):
        expected = records(json.loads(text), row['id'])
        assert len(expected) == 1
        # Independently identified source record must occur whole in a delivered JSON unit.
        assert any(expected[0] in records(json.loads(u['text']), row['id']) for u in units)
    else:
        assert compiler.normalise(text) in '\n'.join(u['text'] for u in units)
    assert all(u['source'] == row['source']['path'] for u in units)

    # Exercise actual packets against the independent source oracle, rather than using
    # catalogue resolution as the expected-content oracle (the original CF03 tautology).
    expected_text = (compiler.normalise(json.dumps(expected[0], indent=2, ensure_ascii=False))
                     if row['source']['path'].endswith('.json') else compiler.normalise(text))
    for card in ACTUAL_CARDS:
        if row['id'] not in card['knowledge']['must_read']:
            continue
        step = {'id': 'fictional-read', 'role': card['id']}
        manifest = delivery.manifest(step, card)
        packet = delivery.packet(manifest, card, step, [])
        assert expected_text in packet['text'], (card['id'], row['id'])
