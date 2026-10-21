"""Data-driven model defaults, private overlays and complete token accounting."""
from copy import deepcopy
import json
import math
import stat

import pytest

from ravel.workflow import model_catalogue as mc
from ravel.workflow import transport_registry as tr


@pytest.fixture
def catalogue():
    return mc.load(builtin_only=True)


@pytest.fixture(autouse=True)
def isolated_overlay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('RAVEL_MODEL_CATALOGUE', raising=False)


def overlay_document(catalogue, rows):
    document = deepcopy(catalogue)
    document.pop('origins', None)
    document['models'] = deepcopy(rows)
    return document


def write_overlay(path, catalogue, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlay_document(catalogue, rows)), encoding='utf-8')
    return path


def test_builtin_is_valid_and_consistent_with_transport_families(catalogue):
    raw = json.loads(mc.BUILTIN.read_text(encoding='utf-8'))
    assert mc.validate(raw) is raw
    assert mc.validate(catalogue) is catalogue
    assert tuple(raw['classes']) == mc.CLASSES
    assert tuple(raw['tiers']) == tr.TIERS
    ids = [row['id'] for row in raw['models']]
    assert len(ids) == len(set(ids)) > 0
    for row in raw['models']:
        assert row['family'] in dict(tr.FAMILY_PATTERNS)
        assert tr.model_family(row['id']) == row['family']
        assert row['class'] in mc.CLASSES
        assert row['status'] in mc.STATUSES
        assert set(row['tiers']) <= set(tr.TIERS)
        assert set(row['prices_per_million']) == set(mc.PRICE_KEYS)
        assert all(math.isfinite(value) and value >= 0
                   for value in row['prices_per_million'].values())
        assert catalogue['origins'][row['id']] == 'builtin'


@pytest.mark.parametrize(('field', 'value'), [
    ('id', 'bad id'), ('family', 'unlisted'), ('class', 'huge'),
    ('status', 'retired'), ('tiers', ['unlisted']), ('tiers', ['agent', 'agent']),
    ('context_tokens', True), ('context_tokens', -1), ('max_output_tokens', 0),
    ('efforts', ['high', 'high']), ('efforts', 'high'), ('released', 9),
    ('notes', []), ('extra', True),
    ('prices_per_million', {'input': 1}),
    ('prices_per_million', {'input': -1, 'cache_write': 1, 'cache_read': 1, 'output': 1}),
    ('prices_per_million', {'input': float('nan'), 'cache_write': 1, 'cache_read': 1, 'output': 1}),
    ('prices_per_million', {'input': 1, 'cache_write': True, 'cache_read': 1, 'output': 1}),
])
def test_validate_names_row_and_bad_field(catalogue, field, value):
    document = deepcopy(catalogue)
    row = document['models'][0]
    original_id = row['id']
    row[field] = value
    with pytest.raises(ValueError) as caught:
        mc.validate(document)
    assert str(caught.value).startswith('model catalogue: ')
    assert (row['id'] if field == 'id' else original_id) in str(caught.value)
    assert field in str(caught.value)


@pytest.mark.parametrize('mutation', ['extra', 'missing', 'duplicate', 'preset', 'classes', 'tiers', 'origins'])
def test_validate_closed_document(catalogue, mutation):
    document = deepcopy(catalogue)
    if mutation == 'extra':
        document['unlisted'] = 1
    elif mutation == 'missing':
        del document['models'][0]['prices_per_million']
    elif mutation == 'duplicate':
        document['models'].append(deepcopy(document['models'][0]))
    elif mutation == 'preset':
        document['presets']['premium']['agent'] = ['unlisted']
    elif mutation == 'classes':
        document['classes'].append('unlisted')
    elif mutation == 'tiers':
        document['tiers'].append('unlisted')
    else:
        document['origins'][document['models'][0]['id']] = 'unlisted'
    with pytest.raises(ValueError, match='model catalogue: '):
        mc.validate(document)


def test_lookup_exact_before_longest_version_suffix(catalogue):
    row = mc.lookup('claude-opus-5-5', catalogue)
    assert row['id'] == 'claude-opus-5-5'
    assert mc.lookup('claude-opus-5-5-20260401', catalogue) is row
    assert mc.lookup('claude-opus-5-5-2026-04-01', catalogue) is row
    assert mc.lookup('claude-opus-5-5@revision', catalogue) is row
    assert mc.lookup('claude-opus-5', catalogue)['id'] == 'claude-opus-5'
    one_row = overlay_document(catalogue, [row])
    for unknown in ('claude-opus-5', 'claude-opus-55', 'claude-opus-5-5-extra', 'claude-opus-5-5@',
                    'claude-opus-5-5-9', 'claude-opus-5-5-9-preview'):
        assert mc.lookup(unknown, one_row) is None


def test_problem_and_exact_remedy(catalogue):
    assert mc.problem('claude-opus-5-5-20260401', catalogue) is None
    assert mc.problem('gpt-unlisted', catalogue) == 'model:uncatalogued'
    for invalid in ('', 'bad id', 'x\n', None, 7, True):
        assert mc.problem(invalid, catalogue) == 'model:invalid'
    message = mc.remedy('gpt-unlisted', catalogue)
    assert "model 'gpt-unlisted'" in message
    assert '.ravel/models/catalogue.json' in message
    assert 'RAVEL_MODEL_CATALOGUE' in message
    assert 'ravel models detect --adopt' in message
    assert '\n' not in message
    assert 'identifier' in mc.remedy('bad id', catalogue)


def test_price_accounts_for_each_reported_part(catalogue):
    usage = {'input_tokens': 1_000_000, 'cache_creation_input_tokens': 2_000_000,
             'cache_read_input_tokens': 3_000_000, 'output_tokens': 4_000_000}
    result = mc.price(usage, 'claude-opus-5-5-20260401', catalogue)
    assert result['status'] == 'priced'
    assert result['cost_usd'] == pytest.approx(4 + 10 + 0.6 + 80)
    assert result['model'] == 'claude-opus-5-5'
    assert result['prices_per_million'] == mc.lookup(result['model'], catalogue)['prices_per_million']
    assert result['price_basis'] == catalogue['price_basis']
    zero = {key: 0 for key in usage}
    assert mc.price(zero, result['model'], catalogue)['cost_usd'] == 0.0
    assert mc.price(usage, 'gpt-unlisted', catalogue)['status'] == 'model_unknown'
    assert mc.price(usage, 'gpt-unlisted', catalogue)['cost_usd'] is None


@pytest.mark.parametrize('part', ['input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'])
@pytest.mark.parametrize('invalid', [None, -1, True, 1.5, '0'])
def test_price_never_estimates_missing_or_invalid_usage(catalogue, part, invalid):
    usage = {'input_tokens': 1, 'cache_creation_input_tokens': 2,
             'cache_read_input_tokens': 3, 'output_tokens': 4}
    del usage[part]
    assert mc.price(usage, catalogue['models'][0]['id'], catalogue)['status'] == 'usage_incomplete'
    usage[part] = invalid
    result = mc.price(usage, catalogue['models'][0]['id'], catalogue)
    assert result['status'] == 'usage_incomplete'
    assert result['cost_usd'] is None


def test_overlay_replaces_rows_and_prioritizes_new_family_class_rows(catalogue, tmp_path, monkeypatch):
    replaced = deepcopy(mc.defaults('anthropic', 'judgment', 'premium', catalogue))
    replaced['prices_per_million']['input'] = 13
    newer = deepcopy(replaced)
    newer['id'] = 'claude-synthetic-99'
    path = write_overlay(tmp_path / 'private.json', catalogue, [replaced, newer])
    monkeypatch.setenv(mc.OVERLAY_ENV, str(path))
    merged = mc.load()
    assert mc.lookup(replaced['id'], merged)['prices_per_million']['input'] == 13
    assert mc.defaults('anthropic', 'judgment', 'premium', merged)['id'] == newer['id']
    assert merged['origins'][newer['id']] == f'overlay:{path}'
    assert merged['origins'][replaced['id']] == f'overlay:{path}'
    assert mc.lookup(replaced['id'], mc.load(builtin_only=True))['prices_per_million']['input'] != 13
    assert mc.lookup(newer['id'], mc.load(builtin_only=True)) is None
    assert catalogue == mc.load(builtin_only=True)


def test_overlay_preserves_new_row_order_and_can_add_presets(catalogue, tmp_path):
    row = deepcopy(catalogue['models'][0])
    row['id'] = 'claude-synthetic-99'
    next_row = deepcopy(row)
    next_row['id'] = 'claude-synthetic-98'
    document = overlay_document(catalogue, [row, next_row])
    document['presets']['custom'] = deepcopy(document['presets']['premium'])
    path = tmp_path / 'overlay.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    merged = mc.load(overlay=path)
    assert mc.defaults('anthropic', 'judgment', 'custom', merged)['id'] == row['id']
    assert [r['id'] for r in merged['models'] if r['id'] in (row['id'], next_row['id'])] == [row['id'], next_row['id']]


def test_default_project_overlay_and_environment_precedence(catalogue, tmp_path, monkeypatch):
    row = deepcopy(catalogue['models'][0])
    row['prices_per_million']['input'] = 17
    local = write_overlay(tmp_path / '.ravel' / 'models' / 'catalogue.json', catalogue, [row])
    nested = tmp_path / 'nested'
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert mc.load()['origins'][row['id']] == f'overlay:{local}'
    row['prices_per_million']['input'] = 19
    environment = write_overlay(tmp_path / 'environment.json', catalogue, [row])
    monkeypatch.setenv(mc.OVERLAY_ENV, str(environment))
    assert mc.lookup(row['id'], mc.load())['prices_per_million']['input'] == 19
    assert mc.lookup(row['id'], mc.load(overlay=local))['prices_per_million']['input'] == 17


@pytest.mark.parametrize('content', ['{', '{"models": []}', '{"unlisted": true}'])
def test_malformed_overlay_names_its_path(catalogue, tmp_path, monkeypatch, content):
    path = tmp_path / 'broken.json'
    path.write_text(content, encoding='utf-8')
    monkeypatch.setenv(mc.OVERLAY_ENV, str(path))
    with pytest.raises(ValueError) as caught:
        mc.load()
    assert str(path) in str(caught.value)
    assert str(caught.value).startswith('model catalogue: ')
    assert mc.load(builtin_only=True)['models'] == catalogue['models']


def test_explicit_missing_overlay_is_refused(tmp_path):
    path = tmp_path / 'missing.json'
    with pytest.raises(ValueError, match='missing.json'):
        mc.load(overlay=path)


def test_invalid_row_overlay_reports_both_path_and_row(catalogue, tmp_path):
    row = deepcopy(catalogue['models'][0])
    row['prices_per_million']['output'] = -1
    path = write_overlay(tmp_path / 'invalid-row.json', catalogue, [row])
    with pytest.raises(ValueError) as caught:
        mc.load(overlay=path)
    assert all(text in str(caught.value) for text in (str(path), row['id'], 'prices_per_million.output'))
    assert mc.load(builtin_only=True, overlay=path)['models'] == catalogue['models']


@pytest.mark.parametrize('preset', ['premium', 'balanced', 'economy'])
def test_defaults_and_preset_models_resolve_each_family_and_tier(catalogue, preset):
    families = ['anthropic', 'openai', 'google']
    result = mc.preset_models(preset, families, catalogue)
    for family in families:
        for tier in tr.TIERS:
            row = mc.defaults(family, tier, preset, catalogue)
            assert row['status'] == 'current'
            assert row['family'] == family and tier in row['tiers']
            assert result[family][tier] == row['id']
            candidates = [candidate for class_ in catalogue['presets'][preset][tier]
                          for candidate in catalogue['models']
                          if candidate['family'] == family and candidate['class'] == class_
                          and tier in candidate['tiers'] and candidate['status'] == 'current']
            assert row == candidates[0]


def test_defaults_only_use_preview_when_all_preferred_classes_lack_current(catalogue):
    document = deepcopy(catalogue)
    top = mc.defaults('anthropic', 'judgment', 'premium', document)
    strong = mc.defaults('anthropic', 'judgment', 'balanced', document)
    top['status'] = 'preview'
    assert mc.defaults('anthropic', 'judgment', 'premium', document) is strong
    strong['status'] = 'legacy'
    assert mc.defaults('anthropic', 'judgment', 'premium', document) is top
    top['status'] = 'legacy'
    assert mc.defaults('anthropic', 'judgment', 'premium', document) is None
    assert set(mc.preset_models('premium', ['anthropic'], document)['anthropic']) == {'agent', 'cheap'}
    assert mc.preset_models('premium', ['unlisted'], document) == {'unlisted': {}}
    with pytest.raises(KeyError, match='unknown preset'):
        mc.preset_models('unlisted', [], document)
    with pytest.raises(KeyError, match='unknown preset'):
        mc.tier_models('unlisted', [], document)


@pytest.mark.parametrize('preset', ['premium', 'balanced', 'economy'])
def test_tier_models_cover_real_transport_family_declarations(catalogue, preset):
    documents = tr.all_declarations(installed_only=True)
    result, omitted = mc.tier_models(preset, documents, catalogue)
    assert set(result) == set(tr.TIERS)
    for document in documents:
        for tier in tr.TIERS:
            expected = next((mc.defaults(model['family'], tier, preset, catalogue)
                             for model in document['models'] if tier in model['tiers']
                             and model['family'] != 'any'), None)
            gaps = [gap for gap in omitted if gap['transport'] == document['id'] and gap['tier'] == tier]
            if expected:
                assert result[tier][document['id']] == expected['id']
                assert tr.model_problem(document, expected['id']) is None
                assert gaps == []
            else:
                assert document['id'] not in result[tier]
                assert len(gaps) == 1
                assert gaps[0]['reason'] in ('family:unknown', 'no_catalogue_row')


def test_tier_models_preserve_first_known_exact_id_and_declared_tiers(catalogue):
    known = mc.defaults('anthropic', 'agent', 'premium', catalogue)
    observed = known['id'] + '-20260401'
    documents = [
        {'id': 'fixed', 'models': [
            {'id': 'claude-unlisted', 'family': 'anthropic', 'tiers': list(tr.TIERS)},
            {'id': observed, 'family': 'anthropic', 'tiers': ['agent']},
            {'id': known['id'], 'family': 'anthropic', 'tiers': ['agent']}]},
        {'id': 'restricted', 'models': [{'id': '{configured}', 'family': 'anthropic', 'tiers': ['agent']}]},
        {'id': 'generic', 'models': [{'id': '{configured}', 'family': 'any', 'tiers': list(tr.TIERS)}]},
        {'id': 'empty', 'models': []},
    ]
    result, omitted = mc.tier_models('balanced', documents, catalogue)
    assert result['agent']['fixed'] == observed
    assert result['agent']['restricted'] == mc.defaults('anthropic', 'agent', 'balanced', catalogue)['id']
    assert 'fixed' not in result['judgment'] and 'restricted' not in result['cheap']
    assert len(omitted) == len(documents) * len(tr.TIERS) - 2
    assert all(gap['reason'] for gap in omitted)
    assert next(gap for gap in omitted if gap['transport'] == 'generic')['reason'] == 'family:unknown'


def test_adopt_writes_valid_private_overlay_and_replaces_idempotently(catalogue, tmp_path):
    kwargs = {'family': 'openai', 'class_': 'mid', 'tiers': list(tr.TIERS),
              'prices_per_million': dict.fromkeys(mc.PRICE_KEYS, 2.0),
              'context_tokens': 10000, 'max_output_tokens': 1000, 'released': '2026-10'}
    path = mc.adopt('gpt-synthetic-99', **kwargs)
    assert path == tmp_path / '.ravel' / 'models' / 'catalogue.json'
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert mc.validate(json.loads(path.read_text()))
    kwargs['prices_per_million']['input'] = 3.0
    assert mc.adopt('gpt-synthetic-99', **kwargs) == path
    document = json.loads(path.read_text())
    assert [row['id'] for row in document['models']].count('gpt-synthetic-99') == 1
    assert document['models'][0]['prices_per_million']['input'] == 3.0
    assert mc.defaults('openai', 'agent', 'balanced', mc.load())['id'] == 'gpt-synthetic-99'
    assert mc.lookup('gpt-synthetic-99', mc.load(builtin_only=True)) is None


def test_adopt_honours_environment_and_unknown_metadata(tmp_path, monkeypatch):
    path = tmp_path / 'private' / 'catalogue.json'
    monkeypatch.setenv(mc.OVERLAY_ENV, str(path))
    assert mc.adopt('custom-model', family='openai', class_='small', tiers=['cheap']) == path
    document = json.loads(path.read_text())
    assert mc.validate(document) is document
    row = document['models'][0]
    assert row['context_tokens'] is None and row['released'] is None
    assert row['prices_per_million'] is None
    usage = dict.fromkeys(('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens'), 1)
    assert mc.price(usage, 'custom-model')['cost_usd'] is None
    assert mc.price(usage, 'custom-model')['status'] == 'usage_incomplete'


def test_adopt_prepend_explicit_path_and_invalid_updates_preserve_bytes(tmp_path, monkeypatch):
    path = tmp_path / 'chosen' / 'catalogue.json'
    monkeypatch.setenv(mc.OVERLAY_ENV, str(tmp_path / 'unused.json'))
    kwargs = {'family': 'google', 'class_': 'small', 'tiers': ('cheap',), 'path': path}
    assert mc.adopt('gemini-synthetic-98', **kwargs) == path
    mc.adopt('gemini-synthetic-99', **kwargs)
    assert [row['id'] for row in json.loads(path.read_text())['models']] == ['gemini-synthetic-99', 'gemini-synthetic-98']
    before = path.read_bytes()
    with pytest.raises(ValueError, match='prices_per_million'):
        mc.adopt('gemini-synthetic-99', prices_per_million={'input': 1}, **kwargs)
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not (tmp_path / 'unused.json').exists()


@pytest.mark.parametrize(('model_id', 'family'), [('bad id', 'openai'), ('x\n', 'openai'), ('gpt-synthetic', 'unlisted')])
def test_adopt_refuses_invalid_identity_and_family(tmp_path, model_id, family):
    path = tmp_path / 'refused' / 'catalogue.json'
    with pytest.raises(ValueError, match='model catalogue: '):
        mc.adopt(model_id, family=family, class_='small', tiers=['cheap'], path=path)
    assert not path.exists()


def test_summary_is_a_listing_with_origin_and_split_prices(catalogue):
    rows = mc.summary(catalogue)
    assert len(rows) == len(catalogue['models'])
    assert set(rows[0]) == {'id', 'family', 'class', 'tiers', 'status', 'input', 'output', 'cache_read', 'origin'}
    assert rows[0]['origin'] == 'builtin'
    assert rows[0]['input'] == catalogue['models'][0]['prices_per_million']['input']
    assert [row['id'] for row in rows] == [row['id'] for row in catalogue['models']]
