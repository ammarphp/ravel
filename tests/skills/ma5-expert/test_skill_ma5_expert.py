"""ma5-expert block on an own SAF cut-flow text."""
SKILL = "ma5-expert"
SAF = """<SAFheader>
</SAFheader>
<InitialCounter>
"Initial number of events"
8 3
12.5 4.25
20.125 7.75
</InitialCounter>
<Counter>
"weighted cut"
6 2
9.25 3.5
18.0 7.0
</Counter>
<SAFfooter>
</SAFfooter>
"""


def test_record_lists_exactly_the_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ["saf-counters"]


def test_cutflow_keeps_both_sign_channels(handbook):
    rows = handbook.load(SKILL, "saf-counters")["cutflow"](SAF)
    assert rows == [("Initial number of events", 12.5, 4.25), ("weighted cut", 9.25, 3.5)]
