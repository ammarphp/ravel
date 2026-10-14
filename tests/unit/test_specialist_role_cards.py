"""Authored specialist and integrity cards: contract text and tier checks, no model calls."""
import json
from pathlib import Path

import pytest

from ravel.paths import package_data_path
from ravel.workflow import role_registry as rr

ROOT = Path(__file__).resolve().parents[2]
CARDS = ('plan-critic', 'integrity-auditor', 'object-selection-mapper', 'discrepancy-attributor',
         'trap-auditor', 'figure-critic', 'literature-scout')


def _file(role):
    return package_data_path('roles', 'cards', role + '.json')


def _protocol(role):
    return ' '.join(rr.load(role)['protocol']).lower()


@pytest.mark.parametrize('role', CARDS)
def test_authored_card_is_the_effective_validated_card(role):
    path = _file(role)
    assert path.is_file() and not path.is_symlink(), role
    authored = json.loads(path.read_text())
    assert rr.load(role) == authored
    assert rr.validate_card(authored) == []
    assert authored['model']['tier'] == 'judgment'
    assert authored['version'] != '2.0.0'  # replaces the registry default


def test_registry_and_rendered_surfaces_have_no_drift():
    from ravel import evidence_layout
    assert rr.validate_registry(root=ROOT) == []
    if evidence_layout.is_public_tree(ROOT):
        pytest.skip('public trees ship a curated subset of host surfaces')
    assert rr.check_rendered(ROOT) == []


def test_scout_card_file_is_never_cheap():
    """CI guard on the committed bytes, independent of the in-memory validator."""
    authored = json.loads(_file('literature-scout').read_text())
    assert authored['model']['tier'] == 'judgment'
    assert authored['model']['tier'] != 'cheap'


@pytest.mark.parametrize('tier', ['cheap', 'agent'])
def test_scout_below_judgment_tier_is_refused(tier):
    card = rr.load('literature-scout')
    card['model']['tier'] = tier
    assert 'literature-scout requires judgment tier' in rr.validate_card(card)


def test_scout_outputs_evidence_cards_and_recipe_ledger_rows():
    card = rr.load('literature-scout')
    kinds = {o['kind'] for o in card['output']['declared_outputs']}
    assert {'evidence_cards', 'recipe_ledger_rows'} <= kinds
    text = _protocol('literature-scout')
    for field in ('claim', 'assertion_kind', 'quantity', 'value', 'uncertainty', 'conditions',
                  'scope_not_covered', 'locator', 'excerpt_sha256', 'superseded_by', 'extractor'):
        assert field in text, field
    for phrase in ('verbatim', 'commit', 'data', 'release', 'run'):
        assert phrase in text, phrase


def test_plan_critic_requires_route_search_and_waypoints():
    text = _protocol('plan-critic')
    assert 'certifiable route' in text and 'before' in text and 'uncertified' in text
    assert 'waypoint for each published intermediate artifact' in text
    assert 'evidence class' in text
    assert 'cheapest discriminating test' in text
    assert 'signal-model completeness before any calibration' in text
    card = rr.load('plan-critic')
    assert 'board_prose' in card['sees']['forbidden_inputs']
    assert 'never post' in text and 'critic projection' in text


def test_integrity_auditor_sees_the_record():
    card = rr.load('integrity-auditor')
    assert card['sees']['profile'] == 'full'
    reads = set(card['tools']['read_paths'])
    assert {'research/protocol.json', 'research/history/', 'research/exposure_ledger.jsonl',
            'agent-work/', 'claims/'} <= reads
    text = _protocol('integrity-auditor')
    assert 'receipt index' in text and 'stage record' in text and 'query' in text
    assert 'computed disclosure block' in text


def test_attributor_forbids_attribution_below_noise():
    text = _protocol('discrepancy-attributor')
    assert 'never attribute a feature below the noise threshold' in text
    assert 'two rival hypotheses' in text and 'kill condition' in text
    assert 'per-bin signal yields' in text


@pytest.mark.parametrize('role', CARDS)
def test_cards_carry_no_identity_or_package_labels(role):
    import re
    text = _file(role).read_text()
    assert not re.search(r'\b(M|CJ|AL|LG|OR|KM|WT)-[0-9]', text)
    assert not re.search(r'\b(ATLAS|CMS|SUSY-20|arXiv|RS1)\b', text)
