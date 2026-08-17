from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

REQUIRED_ANCHORS = [
    "Skill-trigger behavior evals",
    "stage-recovery",
    "skill-precedence",
    "should-trigger",
    "shouldn't-trigger",
    "TRAIN",
    "HELD-OUT",
]


def _text():
    return (REPO / "framework" / "ROUTING-EVALS.md").read_text(encoding="utf-8")


def test_section_present_with_anchors():
    t = _text()
    missing = [a for a in REQUIRED_ANCHORS if a not in t]
    assert not missing, f"ROUTING-EVALS skill-trigger section missing anchors: {missing}"


def test_min_prompt_counts_and_split():
    sec = _text().split("Skill-trigger behavior evals", 1)[1]
    # "should-trigger" is NOT a substring of "shouldn't-trigger" (n't breaks it) -> counts independent
    assert sec.count("should-trigger") >= 4, "need >= 4 should-trigger prompts"
    assert sec.count("shouldn't-trigger") >= 3, "need >= 3 shouldn't-trigger prompts"
    # each trigger split into a train and a held-out subset
    assert sec.count("TRAIN") >= 2 and sec.count("HELD-OUT") >= 2, \
        "each trigger needs a TRAIN and a HELD-OUT subset"
