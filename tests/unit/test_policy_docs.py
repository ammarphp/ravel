"""Operational policy documents agree with each other and with the code they describe.

These are document checks: statistic policy, the route precedence table, the
scientific-study mode tables, the CLI reference and the task-contract enums.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ravel.cli import FOCUSED_COMMANDS
from ravel.validation import validate_task_contract as vtc
from ravel.workflow import science

ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def section(text: str, heading: str) -> str:
    """Body of the Markdown section whose heading line contains ``heading``."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s", line)
        if match and heading in line:
            depth = len(match.group(1))
            body = []
            for later in lines[i + 1:]:
                other = re.match(r"^(#{1,6})\s", later)
                if other and len(other.group(1)) <= depth:
                    break
                body.append(later)
            return "\n".join(body)
    raise AssertionError(f"section {heading!r} not found")


def table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows[1:]  # drop the header


def hard_rule(text: str) -> str:
    rules = section(text, "Hard rules")
    first = re.search(r"^- (.*?)(?=^- |\Z)", rules, re.M | re.S)
    assert first, "hard rules section has no bullets"
    return flat(first.group(1))


# ---------------------------------------------------------------- statistic policy

def test_hard_rule_is_identical_in_both_agent_entry_files():
    # 2e59a61 renders CLAUDE.md as the claude host entry: it imports AGENTS.md instead of repeating
    # it, so the one rule is reachable from both files and there is no second copy to diverge.
    claude = read("CLAUDE.md")
    assert claude.splitlines()[0] == "@AGENTS.md"
    assert not re.search(r"^#{1,6}\s.*Hard rules", claude, re.M)
    assert hard_rule(read("AGENTS.md"))


def test_hard_rule_makes_cls_the_default_and_keeps_a_prescribed_statistic():
    rule = hard_rule(read("AGENTS.md"))
    assert "95% CLs" in rule and "default" in rule
    assert "prescribe" in rule and "primary" in rule
    for prescribed in ("formula", "σ", "Δχ²", "credible interval"):
        assert prescribed in rule, prescribed
    for kind in ("fit", "measurement", "calculation", "summar"):
        assert kind in rule, kind


@pytest.mark.parametrize("relative", [
    ".claude/rules/statistics.md",
    ".claude/skills/physicist-intake/SKILL.md",
    "docs/reference/scope.md",
    "docs/workflow/start.md",
])
def test_statistic_policy_is_stated_wherever_statistics_are_chosen(relative):
    text = flat(read(relative))
    assert "95% CLs" in text and "default" in text, relative
    assert re.search(r"prescribe[sd]? (a |the )?statistic", text), relative
    assert "primary" in text, relative


def test_statistics_rule_lists_prescribed_forms_and_other_result_kinds():
    text = flat(read(".claude/rules/statistics.md"))
    for prescribed in ("formula", "σ", "Δχ²", "credible interval"):
        assert prescribed in text, prescribed
    assert "alongside" in text
    for kind in ("fit", "measurement", "calculation", "summar"):
        assert kind in text, kind


def test_intake_skill_does_not_replace_a_prescribed_statistic():
    text = flat(read(".claude/skills/physicist-intake/SKILL.md"))
    assert "Do not rewrite a significance request as exclusion" in text
    assert "requested quantity" in text


# ---------------------------------------------------------------- route precedence

KIND_ROUTES = {
    "research": "research-orchestration.md",
    "method_study": "research-orchestration.md",
    "anomaly_search": "research-orchestration.md",
    "reproduce": "steps/02-inputs.md",
    "reinterpret": "steps/02-inputs.md",
    "scan": "steps/02-inputs.md",
    "projection": "steps/02-inputs.md",
    "survey": "steps/02-inputs.md",
    "summary_plot": "steps/02-inputs.md",
    "no_routine": "steps/02-inputs.md",
    "calculation": "intake-and-challenges.md",
    "generate": "scoped-workflows.md",
    "likelihood": "scoped-workflows.md",
    "unsupported": "capability_recovery.json",
    "open": "reading.json",
}


def held_operations(names=()):
    """Operations of tools the release withholds; the documents must not offer them.

    A released tree carries no withheld list: it declares only the operations it ships, so any of
    ``names`` it does not declare is held there as well."""
    from ravel.setup import manifest as mf
    from shipped_catalogue import shipped_operations
    return mf.unreleased_operations(mf.load(ROOT)[0]) | (set(names) - set(shipped_operations(names)))


def precedence_rows():
    return table_rows(section(read("docs/workflow/start.md"), "Which route a request takes"))


def test_precedence_table_covers_every_task_mode_and_method_study():
    named = set()
    for row in precedence_rows():
        named |= set(re.findall(r"`([a-z_]+)`", row[0]))
    assert set(vtc.TASK_MODES) | {"method_study"} <= named


@pytest.mark.parametrize("kind,target", sorted(KIND_ROUTES.items()))
def test_each_task_mode_has_one_route_and_next_step(kind, target):
    rows = [row for row in precedence_rows() if f"`{kind}`" in row[0]]
    assert len(rows) == 1, kind
    assert target in " ".join(rows[0][1:]), (kind, rows[0])


def test_analysis_kinds_go_to_checkin1_and_research_kinds_to_the_orchestrator():
    for row in precedence_rows():
        text = " ".join(row)
        if "`reproduce`" in row[0]:
            assert "CHECK-IN 1" in text
        if "`research`" in row[0]:
            assert "research-orchestrate" in text


def test_precedence_table_routes_supplied_inputs_manuscripts_and_diagrams():
    rows = [" ".join(row) for row in precedence_rows()]
    first = [row for row in rows if "supplied" in row.lower()]
    assert first and "scientific-studies.md" in first[0] and "ravel plan" in first[0]
    # c023742 removed the manuscript route with the withheld TeX tool: a held operation is not offered.
    assert any("manuscript-build" in row for row in rows) == ("manuscript-build" not in held_operations(["manuscript-build"]))
    assert not [m for m in held_operations(["manuscript-build"]) if any(m in row for row in rows)]
    assert any("feyn-graph" in row for row in rows)
    # Rows that do not depend on task_mode come first, so they take precedence.
    labels = [row[0].lower() for row in precedence_rows()]
    assert labels.index(next(l for l in labels if "supplied" in l)) < labels.index(
        next(l for l in labels if "`reproduce`" in l))


def test_the_open_route_precedes_the_research_route():
    labels = [row[0] for row in precedence_rows()]
    open_row = next(i for i, label in enumerate(labels) if "`open`" in label)
    research_row = next(i for i, label in enumerate(labels) if "`research`" in label)
    assert open_row < research_row
    assert "exits 1 only" in " ".join(precedence_rows()[[i for i, l in enumerate(labels)
                                                          if "`unsupported`" in l][0]])


def test_precedence_table_overrides_conflicting_derived_next_steps():
    body = flat(section(read("docs/workflow/start.md"), "Which route a request takes"))
    assert "intake_handoff.json" in body and "current_state.json" in body
    assert "follow this table" in body


# ---------------------------------------------------------------- scientific-study modes

STUDY_MODES = ("eft-toolchain", "cosmology-solver", "feyn-graph", "diagram-analysis",
               "feynarts-amplitude", "manuscript-build", "measurement")


def study_table_modes(text):
    modes = []
    for line in text.splitlines():
        match = re.match(r"^\| `([a-z0-9-]+)` \|", line)
        if match:
            modes.append(match.group(1))
    return modes


def test_scientific_study_tables_name_existing_modes_only():
    modes = study_table_modes(read("docs/workflow/reference/scientific-studies.md"))
    assert modes
    assert [m for m in modes if m not in science.MODES] == []


@pytest.mark.parametrize("mode", STUDY_MODES)
def test_scientific_study_tables_list_mode(mode):
    # A released mode is listed; a mode of a withheld tool (c023742) is absent from the tables.
    listed = mode in study_table_modes(read("docs/workflow/reference/scientific-studies.md"))
    assert listed == (mode not in held_operations([mode]))


def test_scientific_studies_names_result_templates():
    text = read("docs/workflow/reference/scientific-studies.md")
    assert "ravel fill-template" in text and "result-templates.md" in text


def test_scientific_studies_documents_rivet_to_hepdata_comparison():
    body = flat(section(read("docs/workflow/reference/scientific-studies.md"),
                        "Compare Rivet output with HEPData"))
    for needed in ("`analyze`", "`source-tables`", "`measurement`", "observables.json",
                   "experimental_covariance", "goodness_of_fit", "signal_strength"):
        assert needed in body, needed


# ---------------------------------------------------------------- CLI reference

def test_cli_reference_names_every_focused_command():
    from ravel.cli import released_commands
    text = read("docs/cli.md")
    named = lambda c: f"`{c}`" in text or f"ravel {c}" in text  # noqa: E731
    released = set(released_commands())
    assert [c for c in FOCUSED_COMMANDS if c in released and not named(c)] == []
    # A command of a withheld tool is not offered.
    assert [c for c in FOCUSED_COMMANDS if c not in released and named(c)] == []


@pytest.mark.parametrize("command", [
    "ravel intake-plan prepare", "ravel intake-plan graph-spec", "ravel intake-plan checkin1-response",
    "ravel agent-graph prepare-external", "ravel agent-graph deliver-external",
    "ravel model-events prepare", "ravel fill-template",
])
def test_cli_reference_shows_command(command):
    assert command in read("docs/cli.md")


def test_cli_reference_describes_held_intake_directory():
    text = flat(read("docs/cli.md"))
    assert "unsupported or invalid requests create no output directory" not in text
    assert "capability_recovery.json" in text


# ---------------------------------------------------------------- task contract enums

@pytest.mark.parametrize("field,values", [
    ("task_mode", vtc.TASK_MODES), ("detector_mode", vtc.DETECTOR_MODES),
    ("stat_mode", vtc.STAT_MODES), ("compute_plan", vtc.COMPUTE_PLANS),
])
def test_task_contract_reference_lists_validator_enums(field, values):
    line = next(l for l in read("docs/reference/task-contract.md").splitlines()
                if l.startswith(f"| `{field}` |"))
    assert set(re.findall(r"`([^`]+)`", line.split("|")[2])) == set(values)
