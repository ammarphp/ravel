"""madgraph-model-import blocks on a synthetic UFO directory."""
SKILL = "madgraph-model-import"


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["ufo-census"]


def test_ufo_census(handbook, tmp_path):
    census = handbook.load(SKILL, "ufo-census")
    for name in census["CORE"][:-1]:
        (tmp_path / name).write_text("# synthetic\n")
    (tmp_path / "restrict_default.dat").write_text("")
    (tmp_path / "restrict_massless.dat").write_text("")
    assert census["ufo_census"](tmp_path) == {"missing": ["lorentz.py"],
                                               "restrictions": ["restrict_default.dat", "restrict_massless.dat"]}
