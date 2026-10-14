"""README Appendix B is rendered from src/ravel/data/citations/upstream.json.

The data file holds one row per toolchain tool with the tool's own citation request,
where it was found, and a note when only a release paper or the home page is given.
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
            assert REF.match(ref) if isinstance(ref, str) else ref.get("text"), (row["tool"], ref)


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
    assert all(re.fullmatch(r"<!-- ravel:(toolchain|capabilities|disk):(start|end) -->", c) for c in comments), comments


def test_renderer_formats_identifiers_and_home_pages():
    renderer = _renderer()
    old_style = "hep-ph" + "/" + "0012345"  # synthetic old-style identifier
    new_style = syn.arxiv(1)  # synthetic new-style identifier
    row = {"tool": "Tool", "link": "https://t.example/", "home_page": "https://t.example/home", "used_for": "Work",
           "basis": "request", "cite": ["arXiv:" + new_style, "doi:10.1/a(b)c"],
           "also": [{"when": "for a stated case", "cite": [old_style]}]}
    assert renderer.render_row(row) == (
        f"| [Tool](https://t.example/) | Work | [arXiv:{new_style}](https://arxiv.org/abs/{new_style}) and "
        "[doi:10.1/a(b)c](https://doi.org/10.1/a%28b%29c); for a stated case, also "
        f"[{old_style}](https://arxiv.org/abs/{old_style}) |")
    home = dict(row, basis="home-page", cite=[], also=[])
    assert renderer.render_row(home).endswith("| [Home page](https://t.example/home) |")
    text = dict(row, cite=[{"text": "A. Author, J. 1 (2000) 2"}, {"text": "B", "url": "https://b.example/"}], also=[])
    assert renderer.render_row(text).endswith("| A. Author, J. 1 (2000) 2 and [B](https://b.example/) |")


def test_no_citation_row_names_a_withheld_tool():
    """A tool whose installer group is withheld from a release is not cited in the shipped data or the
    README."""
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from ravel.setup import manifest as mf
    manifest = mf.load(ROOT)[0]
    assert [row["tool"] for row in _rows() if mf.release_mentions(manifest, [row["tool"], row["link"]])] == []
