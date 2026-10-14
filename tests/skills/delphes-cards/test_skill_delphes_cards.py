"""delphes-cards block on an own minimal card in Delphes TCL syntax."""
import pytest

from ravel.physics import delphes_cards

SKILL = "delphes-cards"
CARD = """
set ExecutionPath { ECal HCal NeutrinoFilter GenMissingET MissingET }
module SimpleCalorimeter ECal {
  add EnergyFraction {0} {0.0}
  add EnergyFraction {11} {1.0}
  add EnergyFraction {12} {0.0}
  add EnergyFraction {1000022} {0.0}
}
module SimpleCalorimeter HCal {
  # default deposit
  add EnergyFraction {0} {1.0}
  add EnergyFraction {11} {0.0}
  add EnergyFraction {12} {0.0}
  add EnergyFraction {1000022} {0.0}
}
module PdgCodeFilter NeutrinoFilter {
  set InputArray Delphes/stableParticles
  add PdgCode {12}
  add PdgCode {-12}
}
module Merger GenMissingET {
  add InputArray NeutrinoFilter/filteredParticles
  set MomentumOutputArray momentum
}
module Merger MissingET {
  add InputArray EFlowMerger/eflow
  set MomentumOutputArray momentum
}
"""


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["invisible-census"]


def test_census_finds_the_visible_gravitino(handbook):
    report = handbook.load(SKILL, "invisible-census")["escaping_states_report"](CARD, [12, 1000022, 1000039])
    assert report[1000039] == {"visible": True, "calorimeter_fractions": {"ECal": [0.0], "HCal": [1.0]},
                               "in_generator_met": False}
    assert report[1000022]["visible"] is False and report[1000022]["in_generator_met"] is False
    assert report[12]["visible"] is False and report[12]["in_generator_met"] is True
    assert delphes_cards.visible_invisibles(CARD, [12, 1000039]) == [1000039]
    fixed = CARD.replace("add EnergyFraction {1000022} {0.0}", "add EnergyFraction {1000022} {0.0}\n  add EnergyFraction {1000039} {0.0}")
    assert delphes_cards.visible_invisibles(fixed, [1000039]) == []


def test_card_without_calorimeters_is_refused():
    with pytest.raises(ValueError):
        delphes_cards.invisible_census("module Merger MissingET {\n}\n", [12])
