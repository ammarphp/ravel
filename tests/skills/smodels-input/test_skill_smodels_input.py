"""smodels-input block on own SLHA text."""
SKILL = "smodels-input"
SLHA = """BLOCK MASS
  1000011 300.0
  1000022 100.0
DECAY 1000011 1.0
  1.0 2 1000022 11
XSECTION 13000 2212 2212 2 -1000011 1000011
  0 0 0 0 0 0 1.0E-02 SModelS-fixture
"""


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["slha-input-census"]


def test_slha_census(handbook):
    census = handbook.load(SKILL, "slha-input-census")["slha_census"]
    assert census(SLHA, [1000011]) == {"mass_block": True, "missing_decays": [], "xsection_blocks": 1}
    stripped = SLHA.split("XSECTION")[0]
    assert census(stripped, [1000011, 1000013]) == {"mass_block": True, "missing_decays": [1000013],
                                                    "xsection_blocks": 0}
