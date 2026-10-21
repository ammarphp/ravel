"""Reviewed additive citation migration uses fictional instruction sources only."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[3] / 'scripts/maintenance/build_instruction_catalogue.py'
SPEC = importlib.util.spec_from_file_location('instruction_refresh_builder', MODULE_PATH)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
SOURCE = 'docs/fictional-instructions.md'


def unit(index, text, *, section='duties', form='paragraph', census=()):
    return {'id': f'{SOURCE}#{section}/{index}', 'source': SOURCE, 'section': section,
            'form': form, 'text': text, 'sha256': builder.compiler.digest_text(text),
            'census': list(census)}


@pytest.fixture
def case(tmp_path, monkeypatch):
    data = tmp_path / 'src/ravel/data/instructions'
    data.mkdir(parents=True)
    old = [unit(0, 'Keep the first fictional duty.', census=['FICTIONAL-ONE', 'FICTIONAL-WHOLE']),
           unit(1, 'Keep the second fictional duty.', census=['FICTIONAL-WHOLE'])]
    previous = {'units': [{key: value for key, value in row.items() if key not in ('source', 'section')}
                          for row in old]}
    for row in previous['units']:
        row['text'] = row['text'].split('\n')
    (data / 'catalogue.json').write_text(json.dumps(previous))
    prior = {'source_sha256': 'old-source-digest', 'reviewed_by': 'previous reviewer',
             'reason': 'previous review', 'units': {old[0]['id']: old[0]['sha256']},
             'prior_migration': {'reviewed_by': 'earlier reviewer', 'reason': 'earlier review'}}
    citations = {'schema_version': 1, 'census_sha256': 'original-census-digest', 'rows': [
        {'id': 'FICTIONAL-ONE', 'source': SOURCE, 'line': 8, 'source_sha256': 'original-source-digest',
         'evidence': 'first fictional duty', 'decision': True, 'migration': prior},
        {'id': 'FICTIONAL-WHOLE', 'source': SOURCE, 'line': 1, 'source_sha256': 'original-source-digest',
         'evidence': '', 'decision': False},
        {'id': 'OTHER', 'source': 'docs/other-fiction.md', 'line': 2, 'evidence': 'unchanged'},
    ]}
    new = [unit(0, 'An added fictional duty.'), unit(1, old[0]['text']), unit(2, old[1]['text'])]
    compiled = {'units': new, 'files': [{'path': SOURCE, 'sha256': 'current-source-digest'}],
                'texts': {SOURCE: 'current fictional source'}}
    calls = []
    view = object()
    cards = [{'id': 'fictional-role'}]
    monkeypatch.setattr(builder, 'published_view', lambda root: view)
    monkeypatch.setattr(builder.role_registry, 'all_cards', lambda **kwargs: cards)
    def compile_current(root, sources, **kwargs):
        calls.append((root, sources, kwargs))
        return deepcopy(compiled)
    monkeypatch.setattr(builder.compiler, 'build', compile_current)
    return SimpleNamespace(root=tmp_path, data=data, previous=previous, old=old, new=new,
                           citations=citations, compiled=compiled, calls=calls, view=view, cards=cards)


def refresh(case, **kwargs):
    return builder.refresh_preserved_sources(case.root, {}, case.citations, [SOURCE],
                                             reviewed_by='current reviewer', reason='additive review', **kwargs)


def test_additions_map_preserved_units_and_preserve_original_metadata_and_history(case):
    before = deepcopy(case.citations)
    result = refresh(case)
    assert case.citations == before
    assert result['census_sha256'] == before['census_sha256']
    assert result['rows'][2] == before['rows'][2]
    for original, updated in zip(before['rows'][:2], result['rows'][:2]):
        assert {key: value for key, value in updated.items() if key != 'migration'} == {
            key: value for key, value in original.items() if key != 'migration'}
        assert updated['migration']['source_sha256'] == 'current-source-digest'
        assert updated['migration']['reviewed_by'] == 'current reviewer'
        assert updated['migration']['reason'] == 'additive review'
    first, whole = result['rows'][:2]
    assert first['migration']['units'] == {case.new[1]['id']: case.new[1]['sha256']}
    assert first['migration']['prior_migration'] == before['rows'][0]['migration']
    assert whole['migration']['units'] == {row['id']: row['sha256'] for row in case.new}
    assert case.calls == [(case.root, {}, {'cards': case.cards, 'view': case.view})]


@pytest.mark.parametrize('damage', ['remove', 'text', 'reorder', 'section', 'form'])
def test_changed_or_removed_or_reordered_previous_units_refuse(case, damage):
    new = case.compiled['units']
    if damage == 'remove':
        new.pop(1)
    if damage == 'text':
        new[1] = unit(1, 'Changed first duty.')
    if damage == 'reorder':
        new[1], new[2] = new[2], new[1]
    if damage == 'section':
        new[1] = unit(1, new[1]['text'], section='different-section')
    if damage == 'form':
        new[1] = unit(1, new[1]['text'], form='item')
    with pytest.raises(ValueError, match='removed, changed or reordered'):
        refresh(case)


def test_prior_migration_pins_recover_binding_when_census_id_is_absent(case):
    case.previous['units'][0]['census'].remove('FICTIONAL-ONE')
    (case.data / 'catalogue.json').write_text(json.dumps(case.previous))
    assert refresh(case)['rows'][0]['migration']['units'] == {
        case.new[1]['id']: case.new[1]['sha256']}


def test_repeating_current_reviewed_refresh_preserves_exact_migration_history(case):
    first = refresh(case)
    # A completed maintenance invocation stores the new catalogue with its actual
    # current bindings alongside the refreshed citations.
    current = deepcopy(case.new)
    for row in first['rows'][:2]:
        for entry in current:
            if entry['id'] in row['migration']['units']:
                entry['census'].append(row['id'])
    (case.data / 'catalogue.json').write_text(json.dumps({'units': current}))
    case.citations = first
    before = deepcopy(first)
    assert refresh(case) == before
    assert case.citations == before


@pytest.mark.parametrize('damage', ['no-binding', 'unknown-pin', 'changed-pin', 'empty-pin', 'old-digest'])
def test_missing_binding_and_invalid_previous_pins_refuse(case, damage):
    if damage == 'no-binding':
        case.previous['units'][0]['census'].remove('FICTIONAL-ONE')
        case.citations['rows'][0].pop('migration')
    if damage == 'unknown-pin':
        case.citations['rows'][0]['migration']['units'] = {'unknown-unit': 'a' * 64}
    if damage == 'changed-pin':
        case.citations['rows'][0]['migration']['units'][case.old[0]['id']] = 'b' * 64
    if damage == 'empty-pin':
        case.citations['rows'][0]['migration']['units'] = {}
    if damage == 'old-digest':
        case.previous['units'][0]['sha256'] = 'c' * 64
    (case.data / 'catalogue.json').write_text(json.dumps(case.previous))
    with pytest.raises(ValueError, match='binding|pin|digest'):
        refresh(case)


@pytest.mark.parametrize('args', [[], ['--reviewed-by', 'reviewer'], ['--reason', 'reason'],
                                  ['--reviewed-by', ' ', '--reason', 'reason']])
def test_refresh_cli_requires_review_metadata_before_reading_sources(args):
    with pytest.raises(SystemExit) as stopped:
        builder.main(['--refresh-preserved-source', SOURCE, *args])
    assert stopped.value.code == 2


@pytest.mark.parametrize('option', ['--census', '--coverage'])
def test_refresh_cli_refuses_census_and_coverage_options(option):
    with pytest.raises(SystemExit) as stopped:
        builder.main(['--refresh-preserved-source', SOURCE, '--reviewed-by', 'reviewer', '--reason', 'reason',
                      option, 'fictional-input'])
    assert stopped.value.code == 2


def test_refresh_cli_checks_citations_drift_and_runs_ordinary_build(case, monkeypatch, capsys):
    (case.data / 'citations.json').write_text(json.dumps(case.citations))
    monkeypatch.setattr(builder.compiler, 'load_sources', lambda path: {})
    built = {'units': deepcopy(case.new), 'files': [], 'mirrors': [], 'sha256': 'fictional-catalogue-digest'}
    manifests = {'fictional': 'manifest'}
    (case.data / 'catalogue.json').write_text(json.dumps(case.previous))
    (case.data / 'manifests.json').write_text(json.dumps(manifests, indent=1, ensure_ascii=False) + '\n')
    calls = []
    def ordinary_build(root, **kwargs):
        calls.append((root, kwargs))
        for row in kwargs['citations']['rows']:
            if row.get('source') == SOURCE:
                for entry in built['units']:
                    if entry['id'] in row['migration']['units']:
                        entry['census'].append(row['id'])
        return built, manifests
    monkeypatch.setattr(builder.catalogue, 'build', ordinary_build)
    before = {path.name: path.read_bytes() for path in case.data.iterdir()}
    assert builder.main(['--root', str(case.root), '--check', '--refresh-preserved-source', SOURCE,
                         '--reviewed-by', 'reviewer', '--reason', 'reason']) == 1
    assert 'stale: src/ravel/data/instructions/citations.json' in capsys.readouterr().out
    assert len(calls) == 1 and calls[0][0] == case.root
    assert calls[0][1]['citations']['rows'][0]['migration']['reviewed_by'] == 'reviewer'
    assert set(calls[0][1]) == {'sources', 'citations', 'drift', 'withheld', 'view'}
    assert {path.name: path.read_bytes() for path in case.data.iterdir()} == before


@pytest.mark.parametrize('damage', ['census', 'unit', 'digest'])
def test_postbuild_scope_preservation_refuses_ordinary_attachment_loss(case, damage):
    citations = refresh(case)
    units = deepcopy(case.new)
    for row in citations['rows'][:2]:
        for entry in units:
            if entry['id'] in row['migration']['units']:
                entry['census'].append(row['id'])
    built = {'units': units}
    builder.verify_refreshed_bindings(built, citations, [SOURCE])
    if damage == 'census':
        units[1]['census'].remove('FICTIONAL-ONE')
    if damage == 'unit':
        units.pop(1)
    if damage == 'digest':
        units[1]['sha256'] = 'invalid-digest'
    before = deepcopy(built)
    with pytest.raises(ValueError, match='ordinary census attachment lost refreshed binding'):
        builder.verify_refreshed_bindings(built, citations, [SOURCE])
    assert built == before
