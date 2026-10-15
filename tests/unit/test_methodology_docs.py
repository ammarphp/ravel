"""Methodology pages: present, linked, illustrated, glossed, plain and anonymous."""
from __future__ import annotations

import codecs
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
METHOD = ROOT / "docs" / "methodology"
PAGES = {"agent-architecture": "methodology-agent-roles", "research-loop": "methodology-research-loop",
         "decision-justification": "methodology-decision-justification"}
# The shared glossary belongs to the README package; its link resolves once both packages merge.
CROSS_PACKAGE = {ROOT / "docs" / "reference" / "glossary.md"}
HEDGES = re.compile(r"\b(?:may|might|should be able|attempts? to|experimental|limited|only|not yet)\b", re.I)


def _links(text: str):
    yield from re.findall(r'!?\[[^\]]*\]\((<?[^)\s]+>?)\)', text)
    yield from re.findall(r'\b(?:src|srcset|href)=["\']([^"\']+)', text)


def _pages() -> list[Path]:
    return [METHOD / "README.md", *[METHOD / f"{page}.md" for page in PAGES]]


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.stem)
def test_local_links_resolve(path: Path):
    for href in _links(path.read_text(encoding="utf-8")):
        url = urlsplit(href.strip("<>"))
        if url.scheme or url.netloc or not url.path:
            continue
        target = (path.parent / unquote(url.path)).resolve()
        assert target.exists() or target in CROSS_PACKAGE, f"{path.name}: missing {href}"


@pytest.mark.parametrize("page,figure", PAGES.items())
def test_page_shows_its_figure_in_both_palettes(page: str, figure: str):
    text = (METHOD / f"{page}.md").read_text(encoding="utf-8")
    assert f'srcset="../figures/svg/dark/{figure}.svg"' in text
    assert f'src="../figures/svg/light/{figure}.svg"' in text
    assert re.search(r'alt="[^"]{80,}"', text), "the figure needs a full text alternative"
    assert (ROOT / "docs" / "figures" / "src" / f"{figure}.tex").is_file()


@pytest.mark.parametrize("page", PAGES)
def test_page_defines_terms_and_ends_with_a_glossary(page: str):
    text = (METHOD / f"{page}.md").read_text(encoding="utf-8")
    assert "\n## Terms\n" in text or "\n## Glossary\n" in text
    glossary = text.split("\n## Glossary\n", 1)[1]
    assert len(re.findall(r"^\| [^|-][^|]* \| ", glossary, re.M)) >= 6
    assert "](../reference/glossary.md)" in glossary


@pytest.mark.parametrize("path", _pages(), ids=lambda p: p.stem)
def test_plain_and_anonymous(path: Path):
    text = path.read_text(encoding="utf-8")
    prose = re.sub(r"```.*?```|`[^`]*`", "", text, flags=re.S)
    prose = re.sub(r"\b(?:read|append)-only\b", "", prose, flags=re.I)
    assert not HEDGES.findall(prose), HEDGES.findall(prose)
    banned = [codecs.decode(word, "rot13") for word in ("FpvragvfgGjb", "PZONtrag", "Qranevb", "orapuznex")]
    banned += ["Co-" + "Authored-By", "Generated" + " with"]
    for word in banned:
        assert word.lower() not in text.lower(), word
    assert not re.search(r"\b(?:ATLAS|CMS)-[A-Z]{2,5}-\d{4}-\d+", text)


def test_index_links_every_page_and_docs_index_links_the_index():
    index = (METHOD / "README.md").read_text(encoding="utf-8")
    for page in PAGES:
        assert f"]({page}.md)" in index
    assert "](methodology/README.md)" in (ROOT / "docs" / "README.md").read_text(encoding="utf-8")


def test_research_loop_names_every_protocol_value():
    from ravel.workflow import research_protocol
    text = (METHOD / "research-loop.md").read_text(encoding="utf-8")
    for value in research_protocol.PURPOSES | research_protocol.EXPOSURES:
        assert f"`{value}`" in text, value
    for value in research_protocol.DECISIONS:
        assert f"| {value} |" in text, value


def test_agent_architecture_lists_every_registered_role():
    from ravel.workflow import role_registry
    # The effective registry: registry.json plus the appended role fragments.
    registry = role_registry.registry_document()
    text = (METHOD / "agent-architecture.md").read_text(encoding="utf-8")
    assert f"ships {len(registry['roles'])} role cards" in text
    listed = set(re.findall(r"`([a-z][a-z0-9-]+)`", text))
    prefixed = {"sf-": "`sf-*`", "upstream-agentrivet-": "`upstream-agentrivet-analyst`"}
    for role in registry["roles"]:
        assert role in listed or any(role.startswith(p) and mark in text for p, mark in prefixed.items()), role
