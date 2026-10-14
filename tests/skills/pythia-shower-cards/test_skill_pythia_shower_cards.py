"""pythia-shower-cards block on own card texts."""
import pytest

from ravel.physics import pythia_cards

SKILL = "pythia-shower-cards"
PLANNED = "Main:numberOfEvents = 100\nHEPMCoutput:file = auto\nJetMatching:merge = on\nJetMatching:qCut = 30\n"


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["pythia-card-compare"]


def test_card_differences(handbook):
    differences = handbook.load(SKILL, "pythia-card-compare")["card_differences"]
    assert differences(PLANNED, PLANNED) == []
    assert differences(PLANNED, PLANNED.replace("qCut = 30", "qCut = 10"))


def test_duplicate_setting_is_refused():
    with pytest.raises(ValueError):
        pythia_cards.parse(PLANNED + "JetMatching:qCut = 40\n")
