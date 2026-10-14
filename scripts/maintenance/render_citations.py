#!/usr/bin/env python3
"""Render README Appendix B from src/ravel/data/citations/upstream.json.

The data file is the single source for the upstream citation table; edit it, then re-run this.

Usage: render_citations.py [--check]     # --check: report drift, change nothing, exit 1 on drift
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, "src", "ravel", "data", "citations", "upstream.json")
README = os.path.join(REPO, "README.md")
HEADING = "## Appendix B: Citing upstream dependencies"
HEADER = ["| Tool | Used for | Cite |", "|---|---|---|"]


def ref_link(ref):
    if isinstance(ref, dict):
        return f"[{ref['text']}]({ref['url']})" if ref.get("url") else ref["text"]
    if ref.startswith("arXiv:"):
        url = "https://arxiv.org/abs/" + ref[len("arXiv:"):]
    elif ref.startswith("doi:"):
        url = "https://doi.org/" + ref[len("doi:"):]
    elif ref.startswith("ascl:"):
        url = "https://ascl.net/" + ref[len("ascl:"):]
    else:
        url = "https://arxiv.org/abs/" + ref
    return f"[{ref}]({url.replace('(', '%28').replace(')', '%29')})"


def join(refs):
    links = [ref_link(ref) for ref in refs]
    return links[0] if len(links) == 1 else ", ".join(links[:-1]) + " and " + links[-1]


def render_row(row):
    cite = join(row["cite"]) if row["cite"] else f"[Home page]({row['home_page']})"
    for also in row.get("also", []):
        cite += f"; {also['when']}, also {join(also['cite'])}"
    return f"| [{row['tool']}]({row['link']}) | {row['used_for']} | {cite} |"


def render_readme(text, rows):
    """Return the README with the Appendix B table replaced by the rendered rows."""
    start = text.index(HEADING)
    lines = text[start:].split("\n")
    first = lines.index(HEADER[0])
    last = first
    while last + 1 < len(lines) and lines[last + 1].startswith("|"):
        last += 1
    lines[first:last + 1] = HEADER + [render_row(row) for row in rows]
    return text[:start] + "\n".join(lines)


def main(argv):
    with open(DATA, encoding="utf-8") as fh:
        rows = json.load(fh)["tools"]
    with open(README, encoding="utf-8") as fh:
        text = fh.read()
    new = render_readme(text, rows)
    if "--check" in argv:
        if new != text:
            print("README Appendix B differs from upstream.json; run render_citations.py")
            return 1
        return 0
    if new != text:
        with open(README, "w", encoding="utf-8") as fh:
            fh.write(new)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
