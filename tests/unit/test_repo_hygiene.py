"""Repository hygiene: superseded record trees stay empty and no denied phrase is tracked.

The denylist (adapted-system names and AI-attribution phrases) is stored only as sha256 digests of
lower-cased word n-grams (n = 1..4) in src/ravel/data/hygiene/denylist-digests.json, so the list
never contains the words it denies. scripts/maintenance/hygiene_denylist.py regenerates it from
phrases given on its command line.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
DENYLIST = ROOT / "src/ravel/data/hygiene/denylist-digests.json"
PURGED_TREES = ("trial-runs", "evidence", "benchmarks", "framework", "stages", "pedagogical",
                "SESSIONS", "docs/research", "docs/validation")
WORD = re.compile(r"[a-z0-9]+")


def tracked(*paths):
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *paths],
                            capture_output=True, check=True)
    return [p for p in result.stdout.decode().split("\0") if p]


def digests():
    document = json.loads(DENYLIST.read_text())
    assert document["schema_version"] == 1 and document["max_ngram"] == 4
    values = set(document["digests"])
    assert values and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in values)
    return values


def ngram_digests(text, max_n=4):
    words = WORD.findall(text.lower())
    found = set()
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            found.add(hashlib.sha256(" ".join(words[i:i + n]).encode()).hexdigest())
    return found


def hits(text, denied):
    return ngram_digests(text) & denied


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_superseded_record_trees_have_no_tracked_files():
    for tree in PURGED_TREES:
        assert tracked(tree) == [], tree


def test_matcher_finds_a_phrase_only_as_whole_words():
    denied = {hashlib.sha256(b"example retired tool").hexdigest(), hashlib.sha256(b"zzexample").hexdigest()}
    assert hits("Built with the Example Retired-Tool runtime.", denied)
    assert hits("uses ZZEXAMPLE.", denied)
    assert not hits("example retiredtool", denied) and not hits("zzexamples", denied)


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs a git checkout")
def test_no_tracked_text_file_contains_a_denied_phrase():
    denied = digests()
    offenders = []
    for relative in tracked("."):
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        if b"\0" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if hits(text, denied):
            offenders.append(relative)
    assert offenders == []
