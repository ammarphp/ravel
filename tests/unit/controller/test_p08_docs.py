"""The judgment-protocols checklist keeps its eight protocols and states the controller's site semantics."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
CHECKLIST = ROOT / "docs/workflow/checklists/judgment-protocols.md"
REFERENCE = ROOT / "docs/workflow/reference/scientific-judgment.md"


def section(text, heading):
    start = text.index(heading)
    following = re.search(r"\n## ", text[start + len(heading):])
    return text[start:start + len(heading) + following.start()] if following else text[start:]


def test_the_eight_protocols_are_kept():
    text = CHECKLIST.read_text()
    names = ["look-first", "basis-manifest", "trap-sweep", "anchor-chain", "discrepancy-decomposition",
             "source-ladder", "conservative-default", "kill-the-result"]
    for number, name in enumerate(names, 1):
        assert f"## P{number} — {name}" in text


def test_site_modes_follow_the_controller_semantics():
    text = " ".join(section(CHECKLIST.read_text(), "## Judgment sites under the controller").split())
    assert "manual is R3 authority" in text
    assert "delegated is R2 independent review" in text
    assert "script-assisted is an `operate` step that runs the named tool" in text
    assert "proceed-with-flag is R1 with a P7 conservative-default record and a deviation entry" in text
    assert "A decision without a valid record is refused" in text
    assert "never lower it; an unknown action is R3" in text
    assert "An unmatched request retains its original obligations and receives judgment planning" in text
    assert "A missing task materializer, child-route binding, physical input or native executor can still hold execution" in text
    assert "successful execution requires the actual operation binding and evidence" in text
    assert "labelled NOT GOVERNED" in text


def test_the_reference_points_at_the_controller_section():
    assert "judgment-protocols.md#judgment-sites-under-the-controller" in REFERENCE.read_text()
    assert "## Judgment sites under the controller" in CHECKLIST.read_text()
