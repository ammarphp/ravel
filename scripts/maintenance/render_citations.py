#!/usr/bin/env python3
"""Render upstream citation links from src/ravel/data/citations/upstream.json.

The data file is the single source for the upstream reference list; edit it, then re-run this.
The list sits between the appendix's <summary> line and its closing </details> tag. References are
numbered continuously; each tool's entry names the tool, what RAVEL uses it for and its references.

Usage: render_citations.py [--check]     # --check: report drift, change nothing, exit 1 on drift
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, "src", "ravel", "data", "citations", "upstream.json")
README = os.path.join(REPO, "README.md")
APPENDIX = os.path.join(REPO, "docs", "architecture", "upstream-tools.md")
HEADING = "## Appendix B: Citing upstream tools"
SUMMARY = "<summary>References for each upstream tool</summary>"
END = "</details>"


def _url(prefix, value):
    return prefix + value.replace("(", "%28").replace(")", "%29")


def links(ref):
    """The reference's identifiers as links: arXiv, then DOI, then ASCL, then a plain address."""
    out = []
    if ref.get("arxiv"):
        out.append(f"[arXiv:{ref['arxiv']}]({_url('https://arxiv.org/abs/', ref['arxiv'])})")
    if ref.get("doi"):
        out.append(f"[doi:{ref['doi']}]({_url('https://doi.org/', ref['doi'])})")
    if ref.get("ascl"):
        out.append(f"[ascl:{ref['ascl']}](https://ascl.net/{ref['ascl']})")
    if ref.get("url") and not out:
        out.append(f"<{ref['url']}>")
    return out


def venue(ref):
    """Journal, volume, year and first page in the usual HEP form, or the publisher, or the year."""
    if ref.get("journal"):
        text = f"*{ref['journal']}*"
        if ref.get("volume"):
            text += f" **{ref['volume']}**"
        if ref.get("year"):
            text += f" ({ref['year']})"
        if ref.get("pages"):
            text += f" {ref['pages']}"
        return text
    if ref.get("publisher"):
        return ref["publisher"] + (f" ({ref['year']})" if ref.get("year") else "")
    return f"({ref['year']})" if ref.get("year") else ""


def render_reference(ref):
    """Keep exact source identifiers; the data record retains full bibliographic metadata."""
    return ", ".join(links(ref)) + "."


def tool_label(row):
    """Use the software name without an organizational prefix."""
    for name in ("SimpleAnalysis", "Combine"):
        if row["tool"].endswith(" " + name):
            return name
    return row["tool"]


def tool_purpose(row):
    return "Public event selections" if tool_label(row) == "SimpleAnalysis" else row["used_for"]


def render_row(row, start=1):
    """The tool's entry and the next reference number. A tool without a reference cites its home page."""
    purpose = tool_purpose(row)
    lines = [f"**[{tool_label(row)}]({row['link']})**: {purpose[0].lower() + purpose[1:]}."]
    if not row["cite"]:
        lines[0] += f" Home page: <{row['home_page']}>."
        return lines, start
    items = [render_reference(ref) for ref in row["cite"]]
    for also in row.get("also", []):
        items += [f"{also['when'][0].upper() + also['when'][1:]}, also: {render_reference(ref)}" for ref in also["cite"]]
    lines += [""] + [f"{start + n}. {item}" for n, item in enumerate(items)]
    return lines, start + len(items)


def render_block(rows):
    """The whole rendered list, tool entries separated by blank lines."""
    out, number = [], 1
    for row in rows:
        lines, number = render_row(row, number)
        out += lines + [""]
    return "\n".join(out[:-1])


def render_readme(text, rows):
    """Return the README with the Appendix B list replaced by the rendering of ``rows``."""
    start = text.index(HEADING)
    first = text.index(SUMMARY, start) + len(SUMMARY)
    last = text.index(END, first)
    return text[:first] + "\n\n" + render_block(rows) + "\n\n" + text[last:]


def render_appendix(rows):
    """A concise tool-to-citation-request index, without names of people or studies."""
    lines = [
        "# Upstream tools and citations", "",
        "Cite the tools used by your study. Each row links the tool and its",
        "citation source. The [reference list](../../README.md#appendix-b-citing-upstream-tools)",
        "retains exact identifiers; [citation data](../../src/ravel/data/citations/upstream.json)",
        "retains the bibliographic metadata and source of each request.", "",
        "| Tool | Used for | Citation source |", "|---|---|---|",
    ]
    for row in rows:
        tool = tool_label(row)
        purpose = tool_purpose(row)
        source = appendix_source(row)
        lines.append(f"| [{tool}]({row['link']}) | {purpose} | "
                     f"[{row['basis']}]({source}) |")
    lines += ["", "Return to the [architecture index](README.md).", ""]
    return "\n".join(lines)


def appendix_source(row):
    """Keep exact publication identifiers in the existing bibliographic appendix."""
    if "arxiv.org/" in row["source_url"]:
        return "../../README.md#appendix-b-citing-upstream-tools"
    return row["source_url"]


def main(argv):
    with open(DATA, encoding="utf-8") as fh:
        rows = json.load(fh)["tools"]
    with open(README, encoding="utf-8") as fh:
        text = fh.read()
    new = render_readme(text, rows)
    appendix = render_appendix(rows)
    old_appendix = open(APPENDIX, encoding="utf-8").read() if os.path.isfile(APPENDIX) else None
    if "--check" in argv:
        if new != text or appendix != old_appendix:
            print("Upstream citation documentation differs; run scripts/maintenance/render_citations.py")
            return 1
        return 0
    if new != text:
        with open(README, "w", encoding="utf-8") as fh:
            fh.write(new)
    if appendix != old_appendix:
        with open(APPENDIX, "w", encoding="utf-8") as fh:
            fh.write(appendix)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
