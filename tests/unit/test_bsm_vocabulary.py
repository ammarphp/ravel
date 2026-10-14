"""Schema of the packaged BSM model-hint vocabulary read by the request parser."""
import json
import re
from pathlib import Path

import ravel

VOCABULARY = Path(ravel.__file__).parent / 'data' / 'routing' / 'bsm-vocabulary.json'


def load():
    return json.loads(VOCABULARY.read_text(encoding='utf-8'))


def test_closed_top_level_schema():
    doc = load()
    assert set(doc) == {'schema_version', 'kind', 'description', 'categories', 'families', 'entries'}
    assert doc['schema_version'] == 1 and doc['kind'] == 'bsm-vocabulary'
    assert doc['categories'] == sorted(set(doc['categories']), key=doc['categories'].index)
    assert len(set(doc['families'])) == len(doc['families'])


def test_entries_are_typed_unique_and_literal():
    doc = load()
    ids, aliases = set(), {}
    for entry in doc['entries']:
        assert set(entry) == {'id', 'label', 'category', 'family', 'aliases'}
        assert re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', entry['id']) and entry['id'] not in ids
        ids.add(entry['id'])
        assert entry['category'] in doc['categories'] and entry['family'] in doc['families']
        assert type(entry['label']) is str and entry['label'].strip()
        assert type(entry['aliases']) is list and entry['aliases']
        for alias in entry['aliases']:
            assert type(alias) is str and alias == alias.strip() and len(alias) >= 2
            key = alias.casefold()
            # One alias names one entry, so a hint never resolves ambiguously.
            assert aliases.setdefault(key, entry['id']) == entry['id'], alias
            re.compile(re.escape(alias))


def test_every_category_and_family_is_used():
    doc = load()
    assert {e['category'] for e in doc['entries']} == set(doc['categories'])
    assert {e['family'] for e in doc['entries']} == set(doc['families'])


def test_aliases_match_varied_wording_on_token_boundaries():
    doc = load()
    def hits(text):
        found = set()
        for entry in doc['entries']:
            for alias in entry['aliases']:
                pattern = r'(?<![\w])' + re.escape(alias) + r'(?![\w])'
                if re.search(pattern, text, re.I):
                    found.add(entry['id'])
        return found
    assert {'wprime', 'ssm'} <= hits("Limits on a W' in the sequential standard model decaying to a lepton and neutrino")
    assert 'leptoquark' in hits('pair-produced scalar leptoquarks coupling to third-generation fermions')
    assert 'heavy-neutral-lepton' in hits('displaced decays of HNLs from W boson decays')
    assert 'two-higgs-doublet' in hits('a 2HDM+a benchmark with a light pseudoscalar')
    assert hits('the stop quark is produced') == {'squark'}
    assert not hits('stopped running at noon')


def test_covers_the_parser_free_text_hint_terms():
    # Every term the request parser recognised before the data file existed has an entry.
    doc = load()
    known = {alias.casefold() for entry in doc['entries'] for alias in entry['aliases']}
    for term in ("HVT", "Z'", "W'", 'slepton', 'higgsino', 'wino', 'bino', 'toponium', 'heavy Higgs',
                 'dark pion', 'dark rho', 'semi-visible jet', 'semi-visible jets', 'SVJ', 'pMSSM', 'axial',
                 'pseudoscalar', 'pseudo-scalar', 'supersymmetry', 'SUSY'):
        assert term.casefold() in known, term
