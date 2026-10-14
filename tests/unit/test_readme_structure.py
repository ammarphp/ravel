"""Readable README, current architecture, preserved links, and scoped examples.

The ordinary checks inspect documents only. The archived statistical quickstart
is a separate explicitly enabled calculation, with its historical fixed scope.
"""
from __future__ import annotations

import codecs
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
ARCH = ROOT / "docs" / "architecture"
STAGES = ["stage-1-environment", "stage-2-inputs", "stage-3-generate", "stage-4-analyze", "stage-5-visualize",
          "stage-6-acquire-data", "stage-7-exclude", "stage-8-scan", "stage-9-verify"]
CROSS = ["checkins", "guardrails", "records", "backends"]
CURRENT = ["stage-5-visualize", "stage-9-verify", *CROSS]
PICTURE = re.compile(r"<picture>(.*?)</picture>", re.S)
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)


def _check_picture(block: str, base: Path) -> str:
    """Detailed tutorial SVGs retain matching light/dark assets and descriptive text."""
    dark = re.search(r'<source media="\(prefers-color-scheme: dark\)" srcset="([^"]+)"', block)
    img = re.search(r'<img [^>]*src="([^"]+)"[^>]*>', block)
    alt = re.search(r'alt="([^"]{20,})"', block)
    assert dark and img and alt, f"incomplete picture: {block[:120]}"
    assert (base / img.group(1)).is_file() and (base / dark.group(1)).is_file()
    assert "/svg/light/" in img.group(1) and "/svg/dark/" in dark.group(1)
    assert Path(img.group(1)).name == Path(dark.group(1)).name
    return Path(img.group(1)).stem


def _check_mermaid(block: str):
    """Source-level checks; rendering is a separate documentation-build concern."""
    assert re.match(r"\s*flowchart (?:TD|LR)\b", block)
    assert len(re.findall(r"\w+\[[^\]\n]+\]", block)) >= 3
    assert block.count("-->") >= 2


def _ids(text: str) -> set[str]:
    ids = set(re.findall(r'<a\b[^>]*\b(?:id|name)=["\']([^"\']+)', text, re.I))
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        name = re.sub(r"[^\w\- ]", "", re.sub(r"<[^>]+>", "", heading).lower().strip()).replace(" ", "-")
        n = counts.get(name, 0)
        ids.add(name if n == 0 else f"{name}-{n}")
        counts[name] = n + 1
    return ids


def _local_links(text: str):
    yield from re.findall(r'!?\[[^\]]*\]\((<?[^)\s]+>?)(?:\s+["\'][^)]*)?\)', text)
    yield from re.findall(r'\b(?:src|srcset|href)=["\']([^"\']+)', text)


def _assert_local_links(path: Path):
    for href in _local_links(path.read_text(encoding="utf-8")):
        u = urlsplit(href.strip("<>"))
        if u.scheme or u.netloc:
            continue
        target = path.parent / unquote(u.path) if u.path else path
        assert target.exists(), f"{path.name}: missing {href}"
        if u.fragment and target.suffix == ".md":
            assert unquote(u.fragment) in _ids(target.read_text(encoding="utf-8")), f"{path.name}: missing {href}"


@pytest.mark.parametrize("page", STAGES + CROSS)
def test_architecture_page_has_one_current_or_tutorial_diagram(page: str):
    path = ARCH / f"{page}.md"
    text = path.read_text(encoding="utf-8")
    pictures, mermaid = PICTURE.findall(text), MERMAID.findall(text)
    assert len(pictures) + len(mermaid) == 1
    if page in CURRENT:
        assert mermaid, f"{page}: current diagram must be editable Mermaid"
    if pictures:
        assert _check_picture(pictures[0], path.parent) == page
    else:
        _check_mermaid(mermaid[0])


@pytest.mark.parametrize("n,page", list(enumerate(STAGES, start=1)))
def test_architecture_pages_link_back(n: int, page: str):
    text = (ARCH / f"{page}.md").read_text(encoding="utf-8")
    assert re.search(rf"\]\(\.\./workflow/steps/0{n}-[\w-]+\.md\)", text)
    assert "](README.md)" in text


def test_architecture_index_links_every_page_and_explains_tutorial_scope():
    text = (ARCH / "README.md").read_text(encoding="utf-8")
    for page in STAGES + CROSS:
        assert f"]({page}.md)" in text
    assert "step 1–8 SVG" in text and "event-generation/recasting tutorial" in text
    assert "current Step 9" in text and "editable Mermaid" in text


SECTIONS = ["Install", "Start a study", "What RAVEL does", "Toolchain", "How it works", "Documentation",
            "Licence and citation", "Appendix A: Architecture", "Appendix B: Citing upstream dependencies"]
ARCH_PARTS = {"The research loop and agent team": "arch-agent-team", "A study's life": "arch-study-life",
              "Physicist steering and compute": "arch-steering", "The physics toolchain": "arch-toolchain",
              "Statistics and inference": "arch-statistics", "Models and hosts": "arch-models-hosts",
              "Provenance and receipts": "arch-provenance", "Workflow engines": "arch-engines"}
HEDGES = re.compile(r"\b(?:may|might|should be able|attempts? to|experimental|limited|only|not yet)\b", re.I)


LANE_REGION = re.compile(r"<!-- ravel:(toolchain|capabilities|disk):start -->.*?<!-- ravel:\1:end -->", re.S)


def _prose(text: str) -> str:
    """The README as the release lane approves it: generated lane regions removed."""
    return LANE_REGION.sub("", text)


def _without_citation_table(text: str) -> str:
    """The README without its verified Appendix B table, the generality gate's one citation exemption."""
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location("render_citations", ROOT / "scripts/maintenance/render_citations.py")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    rows = json.loads((ROOT / "src/ravel/data/citations/upstream.json").read_text())["tools"]
    assert renderer.render_readme(text, rows) == text, "Appendix B differs from its renderer"
    table = "\n".join(renderer.HEADER + [renderer.render_row(row) for row in rows])
    start = text.index(renderer.HEADING)
    assert text[start:].count(table) == 1
    return text[:start] + text[start:].replace(table, "", 1)


def _section(text: str, name: str) -> str:
    body = text.split(f"\n## {name}\n", 1)[1]
    return re.split(r"^## ", body, maxsplit=1, flags=re.M)[0]


def _table_first_cells(section: str) -> list[str]:
    rows = [line for line in section.splitlines() if line.startswith("| ") and not line.startswith("|--")]
    return [row.split("|")[1].strip() for row in rows[1:] if not set(row.split("|")[1].strip()) <= set("-: ")]


def test_readme_sections_in_order():
    headings = re.findall(r"^## (.+)$", README.read_text(encoding="utf-8"), re.M)
    assert headings == SECTIONS


def test_readme_is_short_plain_and_anonymous():
    text = README.read_text(encoding="utf-8")
    assert text.startswith("# RAVEL\n")
    assert len(_prose(text).splitlines()) <= 360
    prose = re.sub(r"```.*?```", "", _prose(text), flags=re.S)
    assert len(re.findall(r"\S+", prose)) <= 4000
    banned = ["R" + "RR", "e" + "RJR", "C" + "R-", "Claude" + " Code", "Co" + "dex", "case" + " study",
              "flag" + "ship", "[" + "Opus]", codecs.decode("FpvragvfgGjb", "rot13"), codecs.decode("PZONtrag", "rot13"), codecs.decode("Qranevb", "rot13"),
              codecs.decode("orapuznex", "rot13"), codecs.decode("PbyyvqreOrapu", "rot13"),
              "Generated" + " with", "Co-" + "Authored-By"]
    for word in banned:
        assert word not in text, word
    assert not re.search(r"\b(?:ATLAS|CMS)-[A-Z]{2,5}-\d{4}-\d+", text), "no analysis is named"
    assert "```mermaid" not in text
    from ravel.validation import check_generality
    # The verified rendered Appendix B table is the gate's one citation exemption.
    assert check_generality.scan_text(_without_citation_table(text), check_generality.load_denylist(None, env={})) == []
    hedges = HEDGES.findall(prose)
    assert not hedges, hedges


def test_install_is_one_block_near_the_top():
    text = README.read_text(encoding="utf-8")
    assert text.index("## Install") < 1500
    section = _section(text, "Install")
    blocks = re.findall(r"```bash\n(.*?)```", section, re.S)
    assert len(blocks) == 1
    lines = blocks[0].strip().splitlines()
    assert lines[0].startswith("git clone ") and "bash scripts/setup/install.sh" in blocks[0]
    assert lines[-1].endswith("ravel doctor")
    assert "docs/installation.md" in section and "Wolfram" in section
    assert re.search(r"\d+ GB", section) and re.search(r"\d+(?:–\d+)? hours", section)
    assert len([p for p in re.sub(r"```.*?```", "", section, flags=re.S).split("\n\n") if p.strip()]) <= 3


def test_complete_installation_matches_canonical_package_contract():
    import json
    import tomllib
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    contract = json.loads((ROOT / "environment/python/installation.json").read_text(encoding="utf-8"))
    assert project["name"] == "ravel-hep"
    assert project["requires-python"] == contract["requires_python"] == ">=3.11,<3.13"
    assert contract["default_python"] == "3.12"
    assert contract["helper"] == "scripts/setup/python_installation.py"
    assert (ROOT / contract["helper"]).is_file()
    rows = [line.strip() for line in (ROOT / contract["host_requirements"]).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    assert rows[-1] == "."  # The complete requirements also install this distribution.
    assert rows[:-1] == project["dependencies"] == contract["dependencies"]
    assert {item["directory"] for item in contract["isolated_required"]} == {".venv-smodels", ".venv-sfitter"}
    guide = (ROOT / "docs/installation.md").read_text(encoding="utf-8")
    assert "bash scripts/setup/install.sh" in guide and "ravel doctor" in guide and "--profile site" in guide
    assert ".venv-smodels" in guide and ".venv-sfitter" in guide and "Wolfram" in guide
    section = _section(README.read_text(encoding="utf-8"), "Install")
    assert "python -m pip install ." not in section and "ravel-hep[" not in section
    assert "requirements-replay.lock" not in section and "optional" not in section.lower()


def test_toolchain_section_offers_no_optional_tool():
    assert "optional" not in _section(README.read_text(encoding="utf-8"), "Toolchain").lower()


def test_every_toolchain_tool_has_a_citation_row():
    text = README.read_text(encoding="utf-8")
    cited = " ".join(_table_first_cells(_section(text, "Appendix B: Citing upstream dependencies")))
    for row in _section(text, "Toolchain").splitlines():
        if not row.startswith("| ") or row.startswith(("| Area", "| Toolchain | Tools |")):  # table headers
            continue
        for tool in re.split(r",\s*| and ", re.sub(r"\([^)]*\)", "", row.split("|")[2])):
            tool = tool.strip()
            if tool:
                assert tool in cited, f"{tool} has no citation row"


def test_overview_and_appendix_figures():
    text = README.read_text(encoding="utf-8")
    how = _section(text, "How it works")
    pictures = PICTURE.findall(how)
    assert len(pictures) == 1 and _check_picture(pictures[0], ROOT) == "readme-overview"
    assert "#appendix-a-architecture" in how
    appendix = _section(text, "Appendix A: Architecture")
    parts = re.findall(r"^### (.+)$", appendix, re.M)
    assert parts == list(ARCH_PARTS)
    for part, figure in ARCH_PARTS.items():
        body = appendix.split(f"### {part}\n", 1)[1].split("\n### ", 1)[0]
        pictures = PICTURE.findall(body)
        assert len(pictures) == 1 and _check_picture(pictures[0], ROOT) == figure, part
        assert "**In:**" in body and "**Out:**" in body, part


def test_contributor_default_and_locked_environment_are_distinct():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    setup = text.split("## Set up", 1)[1].split("## Check a change", 1)[0]
    assert "python3.12 scripts/setup/python_installation.py" in setup
    assert "source .venv/bin/activate" in setup and "python -m pip check" in setup
    assert "requirements-replay.lock" not in setup and ".venv-dev" not in text
    locked = text.split("### Locked statistics environment", 1)[1]
    assert "--require-hashes -r requirements-replay.lock" in locked
    assert "--no-deps -e ." in locked
    assert "install-git-hooks.sh" in text and "run_suite.py --require-all" in text
    assert "This changes this checkout" in text


@pytest.mark.parametrize("relative", ["docs/cli.md", "docs/workflow/reference/scientific-studies.md",
                                     "docs/workflow/reference/scoped-workflows.md", "docs/reference/quantities-and-measurements.md"])
def test_current_setup_guides_use_complete_installation(relative: str):
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "python3.12 scripts/setup/python_installation.py" in text
    assert "source .venv/bin/activate" in text
    assert "installation.md" in text
    for old in ("ravel-hep[science", "ravel-hep[figures", "ravel-hep[measurement",
                "the base package has no third-party runtime", "optional dependencies and `test` extra"):
        assert old not in text


def test_required_symbolic_setup_preserves_declared_alternative():
    symbolic = (ROOT / "docs/reference/symbolic-evaluation.md").read_text()
    models = (ROOT / "docs/reference/model-sources.md").read_text()
    assert "required" in symbolic.lower() and "SymPy" in symbolic and "Wolfram" in symbolic
    assert "licensed" in symbolic and "Python" in symbolic
    for old in ("license is optional", "symbolic extra", "PennKey", "license restoration"):
        assert old not in symbolic + models
    assert "activation" in models and "installation.md" in models


def test_study_commands_are_prospective_and_approval_is_explicit():
    section = _section(README.read_text(encoding="utf-8"), "Start a study")
    commands = [section.index(c) for c in ("ravel initiate", "ravel status", "ravel approve", "ravel run")]
    assert commands == sorted(commands)
    assert "CHECK-IN 1" in section and "--quote" in section
    assert "43.651372" not in section and "GATE: OK" not in section


@pytest.mark.parametrize("path", [ARCH / "README.md", ARCH / "checkins.md", ARCH / "stage-9-verify.md"])
def test_current_review_diagrams_retain_order_and_material_repair(path: Path):
    text = path.read_text(encoding="utf-8")
    blocks = MERMAID.findall(text)
    assert blocks
    block = blocks[0]
    _check_mermaid(block)
    assert re.search(r"K\s*-->\|Result review\|\s*V", block)
    assert re.search(r"V\s*-->\s*S", block)
    for label in ("Physics critic", "Skeptical verifier", "Synthesizer", "Material objection"):
        assert label in block
    assert "improver" in block.lower() and "repair-design" in block.lower() and "admi" in block.lower()
    assert re.search(r"(?:A|A2|CA)\s*-->\s*(?:E|X)", block)



@pytest.mark.parametrize("path", [ARCH / "README.md", ARCH / "checkins.md", ARCH / "stage-9-verify.md"])
def test_retained_evidence_request_is_separate_from_vote_and_repair(path: Path):
    text = path.read_text(encoding="utf-8")
    block = MERMAID.findall(text)[0]
    assert "Nonvoting retained-evidence request" in block
    for role in ("K", "V", "S"):
        assert re.search(rf"{role}\s*-\.->\|Retained-page request\|\s*ER", block)
    assert "authenticated requested pages" in block
    assert "Same Graph and original budget" in block
    assert "explicit" in text.lower() and "deadline" in text.lower()
    assert "scientific-context-continuation.md" in text
    # The page branch preserves the distinct material-objection repair path.
    assert "Root-cause" in block or "Root-cause diagnosis" in block
    assert "improver" in block.lower() and "admi" in block.lower()
    assert "caller" in text.lower()


def test_evidence_records_and_domain_context_keep_presentation_scope():
    records = (ARCH / "records.md").read_text(encoding="utf-8")
    assert "nonvoting request" in records and "review pending" in records
    assert "prior call’s reading credit" in records and "original cumulative calls" in records


def test_checkins_retain_approval_waypoint_and_deviation_distinctions():
    text = (ARCH / "checkins.md").read_text(encoding="utf-8")
    for label in ("CHECK-IN 1", "CHECK-IN 2", "Deviation check-in", "Final check-in",
                  "declared manual or delegated authority"):
        assert label in text
    assert "binds that exact scope" in text
    assert "Work continues within that scope" in text
    assert "proposed scope change follows its required approval" in text
    assert "inherited objections" in text and "Fresh role contexts" in text
    for path in (README, ARCH / "README.md", ARCH / "checkins.md", ROOT / "docs/figures/src/checkins.tex"):
        assert "until you decide" not in path.read_text(encoding="utf-8")


def test_claims_and_hooks_have_explicit_scope():
    text = README.read_text(encoding="utf-8")
    for overstated in ("Each part, and each step, has its own page", "Each panel is explained",
                       "Automatically, on every run", "the lifecycle validator checks every run before delivery"):
        assert overstated not in text
    assert "next step" in text and "original question" in text
    guard = (ARCH / "guardrails.md").read_text(encoding="utf-8")
    assert "configured entry points" in guard and "On other hosts" in guard
    assert "Current source, runtime and launch checks" in guard
    assert "whole-task" in guard and "Numerical and physics concerns" in guard


def test_diagrams_have_readable_responsibility_and_scope_text():
    section = _section(README.read_text(encoding="utf-8"), "What RAVEL does")
    for area in ("Collider studies and reinterpretation", "Higgs and Standard Model measurements",
                 "Models and theory calculations", "Statistics", "Cosmology", "Open-ended research"):
        assert f"**{area}.**" in section, area
    index = (ARCH / "README.md").read_text(encoding="utf-8")
    assert "Boxes name implemented operations" in index
    assert re.search(r"^\| Layer \| Implemented interface \| Purpose \|$", index, re.M)
    for layer in ("Intake", "Source context", "Design", "Controller", "Agent/tool graph", "Study lifecycle", "Scientific judgment", "Delivery"):
        assert re.search(rf"^\| {re.escape(layer)} \|", index, re.M)
    records = (ARCH / "records.md").read_text(encoding="utf-8")
    assert "complete inventory and an actual presented page are separate records" in records
    assert "large/binary omissions" in records and "open obligations" in records


def test_legacy_public_readme_anchors_remain_resolvable():
    expected = ["what-ravel-does", "install", "quick-start", "1-check-the-installation", "2-compute-a-first-limit",
                "3-ask-a-coding-agent", "how-ravel-works", "how-a-calculation-runs", "working-with-a-coding-agent",
                "commands", "supported-analyses-and-statistics", "toolchain-and-platforms", "outputs", "what-ravel-checks",
                "limitations", "documentation", "getting-help-and-contributing", "citing-ravel", "license"]
    assert set(expected) <= _ids(README.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", [README, ARCH / "README.md", *[ARCH / f"{p}.md" for p in STAGES + CROSS],
                                    ROOT / "THIRD-PARTY-NOTICES.md",
                                    ROOT / "docs/figures/README.md", ROOT / "CONTRIBUTING.md"])
def test_local_document_and_asset_links_resolve(path: Path):
    _assert_local_links(path)


def test_third_party_notices_list_licence_copyright_and_files_for_each_copied_set():
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    assert "THIRD-PARTY-NOTICES.md" in readme and "## Appendix B: Citing upstream dependencies" in readme
    rows = [line for line in notices.splitlines() if line.startswith("| ") and not line.startswith("| Copied")
            and not line.startswith("|---")]
    assert rows
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) == 5 and all(cells), row
        for path in re.findall(r"`([^`*]+)`", cells[4]):
            if "/" in path:
                assert (ROOT / path).is_file(), path
