"""README Appendix B is rendered from src/ravel/data/citations/upstream.json.

The data file holds one row per toolchain tool with the tool's own citation request as full
references (authors, title, venue, year and identifiers), where it was found, and a note when a
release paper or the home page stands in for a request.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import synthetic_identifiers as syn

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
DATA = ROOT / "src" / "ravel" / "data" / "citations" / "upstream.json"
BASES = {"request", "listed-reference", "release-paper", "home-page"}
REF = re.compile(r"^(?:arXiv:\d{4}\.\d{4,5}|(?:hep-ph|hep-ex|astro-ph)/\d{7}|doi:10\.\d{4,9}/\S+|ascl:\d{4}\.\d{3})$")


def _renderer():
    spec = importlib.util.spec_from_file_location("render_citations", ROOT / "scripts/maintenance/render_citations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows():
    return json.loads(DATA.read_text(encoding="utf-8"))["tools"]


def _toolchain_tools(text: str) -> list[str]:
    section = text.split("\n## Toolchain\n", 1)[1].split("\n## ", 1)[0]
    tools = []
    for row in section.splitlines():
        if row.startswith("| ") and not row.startswith(("| Area", "| Toolchain | Tools |", "|---")):
            tools += [t.strip() for t in re.split(r",\s*| and ", re.sub(r"\([^)]*\)", "", row.split("|")[2])) if t.strip()]
    return tools


def test_every_row_is_complete_and_sourced():
    rows = _rows()
    assert len({row["tool"] for row in rows}) == len(rows)
    for row in rows:
        assert row["basis"] in BASES, row["tool"]
        for key in ("link", "home_page", "source_url"):
            assert row[key].startswith(("http://", "https://")), (row["tool"], key)
        assert 1 <= len(row["used_for"].split()) <= 7, row["tool"]
        assert not re.search(r"\b(?:ATLAS|CMS)-[A-Z]{2,5}-\d{4}-\d+|\d+ ?(?:GeV|TeV)|four-lepton", row["used_for"])
        refs = row["cite"] + [ref for also in row.get("also", []) for ref in also["cite"]]
        assert (row["basis"] == "home-page") == (not row["cite"]), row["tool"]
        if row["basis"] in {"home-page", "release-paper"}:
            assert row.get("note"), f"{row['tool']}: say why no request is cited"
        for ref in refs:
            _assert_reference(row["tool"], ref)


def _assert_reference(tool, ref):
    """A shipped reference is complete: authors, a venue or publisher or year, and a resolvable identifier."""
    assert isinstance(ref, dict) and ref.get("authors"), (tool, ref)
    assert ref.get("journal") or ref.get("publisher") or ref.get("year") or ref.get("url"), (tool, ref)
    assert ref.get("arxiv") or ref.get("doi") or ref.get("ascl") or ref.get("url"), (tool, ref)
    assert set(ref) <= {"id", "authors", "title", "journal", "volume", "year", "pages", "publisher",
                        "arxiv", "doi", "ascl", "url"}, (tool, sorted(ref))
    if "id" in ref:
        # The identifier the tool's request names is one of the reference's own links.
        assert REF.match(ref["id"]), (tool, ref["id"])
        kind, _, value = ref["id"].partition(":") if not ref["id"].startswith(("hep-", "astro-")) else ("arXiv", "", ref["id"])
        assert {"arXiv": ref.get("arxiv"), "doi": ref.get("doi"), "ascl": ref.get("ascl")}[kind] == value, (tool, ref["id"])
    if "title" not in ref:
        # Only a requested reference whose title names another agent system is cited without it.
        assert ref.get("arxiv") and ref.get("year"), (tool, ref)


def test_every_toolchain_tool_has_a_data_row():
    """The generated toolchain table lists released components; each one has a citation row."""
    text = README.read_text(encoding="utf-8")
    cited = " | ".join(row["tool"].casefold() for row in _rows())  # a versioned row name covers its tool
    missing = [tool for tool in _toolchain_tools(text) if tool.casefold() not in cited]
    assert not missing, missing


def test_readme_appendix_b_is_the_rendered_data():
    renderer = _renderer()
    text = README.read_text(encoding="utf-8")
    assert renderer.render_readme(text, _rows()) == text, "run scripts/maintenance/render_citations.py"
    comments = re.findall(r"<!--.*?-->", text, re.S)
    assert all(re.fullmatch(r"<!-- ravel:(?:(toolchain|capabilities|disk):(start|end)|example-mode:[\w-]+) -->", c)
               for c in comments), comments


def test_renderer_formats_references_and_home_pages():
    renderer = _renderer()
    old_style = "hep-ph" + "/" + "0012345"  # synthetic old-style identifier
    new_style = syn.arxiv(1)  # synthetic new-style identifier
    paper = {"id": "arXiv:" + new_style, "authors": "A. Author et al.", "title": "A tool", "journal": "J. Synth.",
             "volume": "1", "year": 2000, "pages": "2", "arxiv": new_style, "doi": "10.1/a(b)c"}
    note = {"authors": "B. Author", "title": "Notes", "publisher": "Archive", "year": 2001, "arxiv": old_style}
    row = {"tool": "Tool", "link": "https://t.example/", "home_page": "https://t.example/home", "used_for": "Work",
           "basis": "request", "cite": [paper], "also": [{"when": "for a stated case", "cite": [note]}]}
    lines, after = renderer.render_row(row, 4)
    assert after == 6
    assert lines == [
        "**[Tool](https://t.example/)**: work.", "",
        f"4. [arXiv:{new_style}](https://arxiv.org/abs/{new_style}), "
        "[doi:10.1/a(b)c](https://doi.org/10.1/a%28b%29c).",
        f"5. For a stated case, also: [arXiv:{old_style}](https://arxiv.org/abs/{old_style})."]
    home = dict(row, basis="home-page", cite=[], also=[])
    assert renderer.render_row(home, 6) == (["**[Tool](https://t.example/)**: work. Home page: <https://t.example/home>."], 6)
    software = {"authors": "C. Author", "title": "Package", "url": "https://p.example/"}
    assert renderer.render_reference(software) == "<https://p.example/>."
    untitled = {"authors": "D. Author", "year": 2002, "arxiv": new_style}
    assert renderer.render_reference(untitled) == f"[arXiv:{new_style}](https://arxiv.org/abs/{new_style})."
    preprint = dict(untitled, title="Draft")
    assert renderer.render_reference(preprint).startswith("[arXiv:")
    block = renderer.render_block([row, home])
    assert block.startswith("**[Tool]") and "\n\n1. [arXiv:" in block and block.endswith("<https://t.example/home>.")


def test_readme_appendix_b_is_collapsed_and_numbered_continuously():
    text = README.read_text(encoding="utf-8")
    renderer = _renderer()
    section = text.split(renderer.HEADING, 1)[1].split("\n## ", 1)[0]
    assert renderer.SUMMARY in section and section.rstrip().endswith(renderer.END)
    numbers = [int(n) for n in re.findall(r"^(\d+)\. ", section, re.M)]
    assert numbers == list(range(1, len(numbers) + 1))
    assert len(numbers) == sum(len(row["cite"]) + sum(len(a["cite"]) for a in row.get("also", [])) for row in _rows())


def test_no_citation_row_names_a_withheld_tool():
    """A tool whose installer group is withheld from a release is not cited in the shipped data or the
    README."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from ravel.setup import manifest as mf
    manifest = mf.load(ROOT)[0]
    assert [row["tool"] for row in _rows() if mf.release_mentions(manifest, [row["tool"], row["link"]])] == []


def test_citation_appendix_covers_every_tool_without_personal_names():
    renderer = _renderer()
    rows = _rows()
    path = ROOT / "docs/architecture/upstream-tools.md"
    assert path.read_text() == renderer.render_appendix(rows)
    for row in rows:
        assert f"]({row['link']})" in path.read_text()
        assert f"[{row['basis']}]({renderer.appendix_source(row)})" in path.read_text()
    assert "arxiv.org/" not in path.read_text()
    # Display uses exact identifiers while full metadata remains validated above.
    for row in rows:
        for ref in row['cite']:
            rendered = renderer.render_reference(ref)
            assert all(link in rendered for link in renderer.links(ref))
            assert ref['authors'] not in rendered
