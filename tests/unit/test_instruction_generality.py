"""Agent instructions judge work by general correctness, never by a score or a past outcome.

No role card, skill, rule or host instruction file may ask an agent to optimise a score or a
benchmark tier, or cite a selected historical outcome as the reason for a rule. The denied
phrases are stored only as sha256 digests of lower-cased word n-grams (n = 1..4) in
src/ravel/data/hygiene/instruction-digests.json, so this test names nothing it denies.
scripts/maintenance/hygiene_denylist.py regenerates the file from phrases on its command line.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = ROOT / "src/ravel/data/hygiene/instruction-digests.json"
SURFACES = (".claude/skills", ".agents/skills", ".claude/rules", ".claude/agents", ".ravel/roles",
            "src/ravel/data/roles", "src/ravel/data/skills", ".codex", ".gemini", ".opencode",
            ".antigravity", "AGENTS.md", "CLAUDE.md", "GEMINI.md")
WORD = re.compile(r"[a-z0-9]+")


def digests():
    document = json.loads(DIGESTS.read_text())
    assert document["schema_version"] == 1 and document["max_ngram"] == 4
    values = set(document["digests"])
    assert values and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in values)
    return values


def hits(text, denied, max_n=4):
    words = WORD.findall(text.replace("\\n", " ").lower())
    found = set()
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            found.add(hashlib.sha256(" ".join(words[i:i + n]).encode()).hexdigest())
    return found & denied


def instruction_files():
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *SURFACES],
                            capture_output=True, check=True)
    return [p for p in result.stdout.decode().split("\0") if p]


def test_matcher_reads_json_escaped_text_as_words():
    denied = {hashlib.sha256(b"keep the score").hexdigest()}
    assert hits('"protocol": "a fix must keep the\\nscore"', denied)
    assert not hits("keep the scores", denied)


def test_digest_list_denies_score_directed_and_outcome_cues():
    denied = digests()
    # A generic score-directed sentence and a generic tier target are caught.
    assert hits("A fix must improve or hold the result.", denied)
    assert hits("Rank fixes by benchmark tier impact.", denied)
    # The general replacement wording is allowed.
    assert not hits("The fix removes the mechanism of the failure; safeguards do not regress.", denied)


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_no_instruction_surface_is_score_directed_or_cites_past_outcomes():
    denied = digests()
    offenders = []
    for relative in instruction_files():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if hits(text, denied):
            offenders.append(relative)
    assert offenders == []
