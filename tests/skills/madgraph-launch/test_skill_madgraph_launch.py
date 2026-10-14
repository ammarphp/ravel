"""madgraph-launch blocks against RAVEL's card checker and rendered scripts."""
import sys
from pathlib import Path

import pytest

from ravel.physics import model_events

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "unit"))
from test_model_events import config, texts  # noqa: E402

SKILL = "madgraph-launch"


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert set(handbook.listed(SKILL)) == {"run-card-keyed-edit", "launch-edit-window"}


def test_keyed_run_card_edit_round_trips_through_check_cards(handbook, tmp_path):
    set_run_card = handbook.load(SKILL, "run-card-keyed-edit")["set_run_card"]
    c = config(tmp_path)
    cards = texts(c)
    edited = set_run_card("# 10 = nevents is only a comment\n" + cards["run"], {"nevents": 50, "iseed": 7})
    c["generation"]["events"], c["generation"]["seed"] = 50, 7
    observed = model_events.check_cards(c, {**cards, "run": edited})
    assert observed["run"]["nevents"].strip() == "50" and observed["run"]["iseed"].strip() == "7"
    c["generation"]["events"] = 3                        # declaration not updated: refused
    with pytest.raises(ValueError, match="nevents"):
        model_events.check_cards(c, {**cards, "run": edited})
    with pytest.raises(ValueError, match="0 rows for xqcut_typo"):
        set_run_card(cards["run"], {"xqcut_typo": 1})


def test_launch_edit_window(handbook, tmp_path):
    check = handbook.load(SKILL, "launch-edit-window")["check_launch_edits"]
    c = config(tmp_path)
    _, launch = model_events.render_scripts(c, texts(c), model_path=tmp_path / "model", process_path=tmp_path / "PROC")
    assert check(launch) is True
    assert check("launch PROC\nshower=OFF\n0\nset nevents 500\n0\n") is True
    with pytest.raises(ValueError, match="outside the card-edit window"):
        check("launch PROC\nshower=OFF\n0\n0\nset nevents 500\n")
    with pytest.raises(ValueError, match="two answers"):
        check("launch PROC\n0\n")
