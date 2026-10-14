#!/usr/bin/env python3
"""Fail when product src/, tests/ or docs/ contain an evaluation-identity term.

The forbidden-term list is never committed. Supply it from outside the repository:
  RAVEL_EVAL_TERMS_FILE=<path>   one term per line ('#' comments and blank lines ignored)
  RAVEL_EVAL_TERMS=<a>,<b>,...   comma- or newline-separated terms
Matching is the generality gate's (src/ravel/validation/check_generality.py): a term matches a run of
words with the same letters and digits, in any case and with any separators. The gate reads the same
variables on every run; this script checks the outside list alone. Exit 0 = clean, 1 = hits,
2 = no list supplied. Hits print path:line and the matching term's index, not the line text.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ravel.validation import check_generality  # noqa: E402

DEFAULT_ROOTS = ("src", "tests", "docs")


def load_terms(env=os.environ) -> list[str]:
    raw: list[str] = []
    path = env.get("RAVEL_EVAL_TERMS_FILE")
    if path:
        raw += Path(path).read_text(encoding="utf-8").splitlines()
    if env.get("RAVEL_EVAL_TERMS"):
        raw += env["RAVEL_EVAL_TERMS"].replace(",", "\n").splitlines()
    return [t.strip() for t in raw if t.strip() and not t.strip().startswith("#")]


def scan(repo: Path, terms: list[str], roots=DEFAULT_ROOTS) -> list[tuple[str, int, int]]:
    numbered = [(number, check_generality.entry_for(term, "external")) for number, term in enumerate(terms)
                if len(check_generality._compact(term)) >= 3]
    index = {entry["digest"]: number for number, entry in reversed(numbered)}
    entries = [entry for _, entry in numbered]
    denylist = check_generality.Denylist(entries)
    hits = []
    for root in roots:
        base = repo / root
        if not base.exists():
            continue
        for path in ([base] if base.is_file() else check_generality._walk(base)):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            relative = str(path.relative_to(repo))
            for offset, _ in denylist.hits(text):
                number = text.count("\n", 0, offset) + 1
                hits.append((relative, number, _term_at(text, offset, index)))
    return sorted(set(hits))


def _term_at(text, offset, index):
    """The index of the term whose digest matches the word run starting at ``offset``."""
    words = []
    for match in check_generality.WORD.finditer(text, offset):
        words.append(match.group().lower())
        digest = check_generality._digest("".join(words))
        if digest in index:
            return index[digest]
        if len(words) == check_generality.MAX_WORDS:
            break
    return -1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_ROOTS))
    args = parser.parse_args(argv)
    terms = load_terms()
    if not terms:
        print("no term list: set RAVEL_EVAL_TERMS_FILE or RAVEL_EVAL_TERMS", file=sys.stderr)
        return 2
    hits = scan(Path(args.repo), terms, args.paths)
    for path, number, index in hits:
        print(f"{path}:{number}: term #{index}")
    print(f"{len(hits)} hit(s) for {len(terms)} term(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
