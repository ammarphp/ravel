"""Page-limited note rule packs: supplied limits and sections, never code constants."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import manuscript_format as mf, manuscript_production as mp, note_profile
from ravel.paths import package_data_path
from test_manuscript_production import setup, completed, put, pin

PACK = {'schema_version': 1, 'kind': 'note-rule-pack', 'id': 'toy-pack', 'title': 'Toy page-limited note',
        'origin': 'user', 'source_basis': None, 'max_main_pages': 6, 'excluded_sections': [],
        'max_figures': 4, 'max_tables': 3, 'required_semantics': ['strategy', 'validation'],
        'main_text_semantics': ['strategy'], 'allow_user_count_exclusions': False,
        'requires_supplied_requirements': True}


def packed(root, monkeypatch, pack=PACK, *, tighten=None, extra_rules=()):
    request, state, value = setup(root, monkeypatch)
    pack_pin = put(root, 'pack.json', pack)
    contract = mf.build_note_contract(pack, pack_pin, stage='draft', article_type='internal note',
                                      render={'class': 'article', **note_profile.RENDER_DEFAULTS},
                                      extra_rules=extra_rules)
    if tighten:
        for rule in contract['rules']:
            if rule['kind'] in tighten:
                rule['value'] = tighten[rule['kind']]
    request['profile'] = 'page-limited-note'
    request['formatting'] = put(root, 'format.json', contract)
    request['challenge_requirements'] = put(root, 'requirements.json', {'requirements': ['supplied text']})
    for section in ('strategy', 'validation'):
        value['paragraphs'].append({'id': section, 'section': section, 'kind': 'claim',
                                    'text': 'Synthetic ' + section + ' paragraph.', 'method_ids': [],
                                    'citation_ids': [], 'evidence_ids': [], 'uncertainties': ['Synthetic.']})
    return request, state, value, contract


def test_no_rule_pack_ships_with_the_package():
    root = package_data_path('manuscript')
    assert not (root / 'rule-packs').exists()
    assert not [p for p in root.rglob('*.json') if '"note-rule-pack"' in p.read_text()]


def test_note_profile_refuses_without_a_supplied_rule_pack(tmp_path, capsys):
    for argv in (['check'], ['contract', '--out', str(tmp_path / 'contract.json')]):
        with pytest.raises(SystemExit) as stop:
            note_profile.main(argv)
        assert stop.value.code != 0 and '--rule-pack' in capsys.readouterr().err
    assert not (tmp_path / 'contract.json').exists()


def test_no_challenge_profile_or_constant_remains_in_code():
    sources = [Path(mf.__file__), Path(mp.__file__)]
    from ravel.physics import manuscript_build
    sources.append(Path(manuscript_build.__file__))
    text = '\n'.join(p.read_text() for p in sources).lower()
    from ravel.validation import check_generality
    assert not check_generality.load_denylist(None, env={}).hits(text) and 'page-limited-note' in mf.PROFILES


def test_pack_contract_loads_and_writer_accepts_complete_note(tmp_path, monkeypatch):
    request, state, value, contract = packed(tmp_path, monkeypatch)
    loaded = mf.load(request['formatting'], tmp_path, {})
    assert loaded['rule_pack']['sha256'] == pin(tmp_path / 'pack.json')['sha256']
    kinds = {r['kind']: r['value'] for r in loaded['rules']}
    assert kinds['max_main_pages'] == 6 and kinds['max_figures'] == 4 and kinds['max_tables'] == 3
    b = mp.prepare_writer(request, tmp_path / 'writer', base_dir=tmp_path, campaign=tmp_path / 'campaign')
    completed(b, state, value, monkeypatch)
    package = mp.collect(b, tmp_path / 'note')['package']
    assert package['profile'] == 'page-limited-note'


@pytest.mark.parametrize('kind', ['max_main_pages', 'max_figures', 'max_tables'])
def test_contract_cannot_weaken_pack_ceiling(tmp_path, monkeypatch, kind):
    request, _, _, _ = packed(tmp_path, monkeypatch, tighten={kind: 50})
    with pytest.raises(ValueError, match='ceiling'):
        mf.load(request['formatting'], tmp_path, {})


def test_contract_may_tighten_pack_ceiling(tmp_path, monkeypatch):
    request, _, _, _ = packed(tmp_path, monkeypatch, tighten={'max_main_pages': 4})
    assert mf.load(request['formatting'], tmp_path, {})


def test_user_count_exclusion_refused_when_pack_forbids_it(tmp_path, monkeypatch):
    exclusion = {'id': 'mine', 'kind': 'excluded_sections', 'scope': 'main-pages', 'value': ['appendix'],
                 'origin': 'user', 'source_basis': None}
    request, _, _, _ = packed(tmp_path, monkeypatch, extra_rules=[exclusion])
    with pytest.raises(ValueError, match='user counting exclusions'):
        mf.load(request['formatting'], tmp_path, {})
    allowed = dict(PACK, allow_user_count_exclusions=True)
    request, _, _, _ = packed(tmp_path / 'b', monkeypatch, pack=allowed, extra_rules=[exclusion])
    assert mf.load(request['formatting'], tmp_path / 'b', {})


def test_page_limited_note_requires_a_pack(tmp_path, monkeypatch):
    request, _, _, contract = packed(tmp_path, monkeypatch)
    del contract['rule_pack']
    with pytest.raises(ValueError, match='rule pack'):
        mf.load(put(tmp_path, 'bare.json', contract), tmp_path, {})


def test_missing_required_section_and_appendix_placement_refused(tmp_path, monkeypatch):
    request, state, value, _ = packed(tmp_path, monkeypatch)
    value['paragraphs'] = [p for p in value['paragraphs'] if p['section'] != 'validation']
    b = mp.prepare_writer(request, tmp_path / 'writer', base_dir=tmp_path, campaign=tmp_path / 'campaign')
    completed(b, state, value, monkeypatch)
    with pytest.raises(ValueError, match='semantic content missing'):
        mp.collect(b, tmp_path / 'note')


def test_main_text_role_cannot_move_to_appendix(tmp_path, monkeypatch):
    request, state, value, contract = packed(tmp_path, monkeypatch)
    rows = mf.section_layout(contract)
    for row in rows:
        if row['id'] == 'strategy':
            row['placement'] = 'appendix'
    rows = [r for r in rows if r['placement'] == 'main'] + [r for r in rows if r['placement'] != 'main']
    contract['sections'] = rows
    request['formatting'] = put(tmp_path, 'format-appendix.json', contract)
    b = mp.prepare_writer(request, tmp_path / 'writer', base_dir=tmp_path, campaign=tmp_path / 'campaign')
    completed(b, state, value, monkeypatch)
    with pytest.raises(ValueError, match='appendix'):
        mp.collect(b, tmp_path / 'note')


def test_supplied_requirements_document_required_when_pack_says_so(tmp_path, monkeypatch):
    request, _, _, _ = packed(tmp_path, monkeypatch)
    request['challenge_requirements'] = None
    with pytest.raises(ValueError, match='supplied requirements'):
        mp.prepare_writer(request, tmp_path / 'writer', base_dir=tmp_path, campaign=tmp_path / 'campaign')


@pytest.mark.parametrize('change', ['unknown-role', 'challenge-without-source', 'zero-pages', 'main-not-required'])
def test_malformed_rule_packs_refused(change):
    pack = deepcopy(PACK)
    if change == 'unknown-role':
        pack['required_semantics'] = ['made-up-role']
    if change == 'challenge-without-source':
        pack['origin'] = 'challenge'
    if change == 'zero-pages':
        pack['max_main_pages'] = 0
    if change == 'main-not-required':
        pack['main_text_semantics'] = ['background']
    with pytest.raises(ValueError):
        mf.validate_rule_pack(pack)


def test_note_profile_cli_writes_new_contract_once(tmp_path, capsys):
    (tmp_path / 'pack.json').write_text(json.dumps(PACK))
    assert note_profile.main(['check', '--rule-pack', str(tmp_path / 'pack.json')]) == 0
    assert json.loads(capsys.readouterr().out)['max_main_pages'] == 6
    out = tmp_path / 'format.json'
    assert note_profile.main(['contract', '--rule-pack', str(tmp_path / 'pack.json'), '--out', str(out)]) == 0
    written = json.loads(out.read_text())
    assert written['profile'] == 'page-limited-note' and written['rule_pack']['path'] == str(tmp_path / 'pack.json')
    with pytest.raises(SystemExit):
        note_profile.main(['contract', '--rule-pack', str(tmp_path / 'pack.json'), '--out', str(out)])
