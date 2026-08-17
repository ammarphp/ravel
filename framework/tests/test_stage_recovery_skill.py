# framework/tests/test_stage_recovery_skill.py
import re
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / ".claude/skills/stage-recovery/SKILL.md"

def test_stage_recovery_skill_wellformed_and_co_primary():
    assert SKILL.is_file(), "stage-recovery SKILL.md missing"
    text = SKILL.read_text()
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert fm, "missing YAML frontmatter"
    head = fm.group(1)
    assert re.search(r"^name:\s*stage-recovery\s*$", head, re.M)
    assert re.search(r"^description:\s*\S", head, re.M)
    assert re.search(r"^when_to_use:\s*\S", head, re.M)
    assert "resource_census.py --debug recipe-search" in text
    assert re.search(r"co-?primary", text, re.I)
    assert "--assert-recipe-search" in text
