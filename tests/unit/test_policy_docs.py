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


# ---------------------------------------------------------------- complete source inventory

@pytest.fixture
def documentation_inventory_tools(monkeypatch):
    """The documentation reader is maintenance tooling, not a product import."""
    import importlib
    monkeypatch.syspath_prepend(str(ROOT / 'scripts/maintenance'))
    generator = importlib.import_module('render_documentation_inventory')
    parsers = importlib.import_module('documentation_parsers')
    return generator, parsers


def test_documentation_inventory_is_current_and_has_no_unresolved_parsers(documentation_inventory_tools):
    generator, _ = documentation_inventory_tools
    # Membership comes from the fresh selected-source view, never the checked
    # snapshot's own list. This is part of the ordinary default test suite.
    errors = generator.snapshot_errors(ROOT)
    assert errors == [], '\n'.join(errors[:30])


def _documentation_fixture(generator):
    """Small fictional source surfaces for meaningful completeness mutations."""
    entries = []
    for kind in ('capability', 'command', 'option', 'science-mode', 'config-key', 'module'):
        identity = kind + ':synthetic-record'
        target = generator.COMMANDS if kind in ('command', 'option') else generator.MARKDOWN
        row = {'id': identity, 'kind': kind, 'summary': 'Synthetic declaration',
               'source': 'src/ravel/synthetic.py', 'scope': 'registration',
               'docs': [target + '#' + generator.anchor(identity), 'docs/reference/synthetic-guide.md']}
        if kind in ('command', 'option'):
            row['details'] = {'command': 'ravel synthetic inspect', 'line': 1, 'scope': 'main'}
            if kind == 'option':
                row['details'].update(names=['--sample'], constraints={'required': 'True'})
        entries.append(row)
    return {'schema_version': 1, 'kind': 'documentation-inventory', 'entries': entries,
            'counts': {kind: 1 for kind in (entry['kind'] for entry in entries)},
            'source_pins': [], 'parser_gaps': []}


def _write_documentation_fixture(root, generator, value):
    outputs = {**generator.snapshot_outputs(value), 'docs/reference/synthetic-guide.md': '# Synthetic guide\n'}
    for relative, content in outputs.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')


@pytest.mark.parametrize('kind', ['capability', 'command', 'option', 'science-mode', 'config-key', 'module'])
@pytest.mark.parametrize('change', ['new-source-entry', 'removed-source-entry'])
def test_documentation_gate_rejects_missing_and_stale_entries(tmp_path, documentation_inventory_tools, kind, change):
    from copy import deepcopy
    generator, _ = documentation_inventory_tools
    value = _documentation_fixture(generator)
    _write_documentation_fixture(tmp_path, generator, value)
    assert generator.snapshot_errors(tmp_path, value) == []
    fresh = deepcopy(value)
    if change == 'new-source-entry':
        entry = deepcopy(next(row for row in fresh['entries'] if row['kind'] == kind))
        entry['id'] += '-new'
        entry['docs'][0] = entry['docs'][0].split('#')[0] + '#' + generator.anchor(entry['id'])
        fresh['entries'].append(entry)
        fresh['counts'][kind] += 1
    else:
        fresh['entries'] = [row for row in fresh['entries'] if row['kind'] != kind]
        fresh['counts'].pop(kind)
    errors = generator.snapshot_errors(tmp_path, fresh)
    assert any('stale documentation snapshot:' in error for error in errors), errors
    if change == 'new-source-entry':
        assert any('missing documentation entry:' in error for error in errors), errors


def test_documentation_gate_rejects_deleted_page_anchor_and_duplicate_id(tmp_path, documentation_inventory_tools):
    from copy import deepcopy
    generator, _ = documentation_inventory_tools
    value = _documentation_fixture(generator)
    _write_documentation_fixture(tmp_path, generator, value)
    (tmp_path / 'docs/reference/synthetic-guide.md').unlink()
    errors = generator.documentation_errors(tmp_path, value)
    assert 'missing documentation page: docs/reference/synthetic-guide.md' in errors
    _write_documentation_fixture(tmp_path, generator, value)
    entry = value['entries'][0]
    target = tmp_path / generator.MARKDOWN
    target.write_text(target.read_text().replace('id="' + generator.anchor(entry['id']) + '"', 'id="removed"'))
    assert 'missing documentation entry: ' + entry['docs'][0] in generator.documentation_errors(tmp_path, value)
    duplicate = deepcopy(value)
    duplicate['entries'].append(deepcopy(entry))
    assert 'duplicate documentation ids' in generator.documentation_errors(tmp_path, duplicate)


def _parser_fixture_inventory(root, generator, parsers):
    source = root / 'src/ravel/synthetic.py'
    rows, gaps = parsers.extract(root, [source])
    entries = []
    for row in rows:
        entries.append({'id': row['id'], 'kind': row['kind'], 'summary': row['summary'],
                        'source': row['source'], 'scope': 'parser-declaration',
                        'details': {key: value for key, value in row.items() if key not in ('id', 'kind', 'summary', 'source')},
                        'docs': [generator.COMMANDS + '#' + generator.anchor(row['id'])]})
    from collections import Counter
    return {'schema_version': 1, 'kind': 'documentation-inventory', 'entries': entries,
            'counts': dict(Counter(row['kind'] for row in entries)), 'source_pins': [], 'parser_gaps': gaps}


def test_parser_inventory_reads_source_loops_helpers_conditions_and_boolean_aliases_without_execution(
        tmp_path, documentation_inventory_tools):
    generator, parsers = documentation_inventory_tools
    source = tmp_path / 'src/ravel/synthetic.py'
    source.parent.mkdir(parents=True)
    source.write_text('''
raise RuntimeError("command modules must never execute during documentation generation")
import argparse
VERBS = ('inspect', 'emit')
def common(parser):
    parser.add_argument('--enabled', action=argparse.BooleanOptionalAction)
def parser():
    root = argparse.ArgumentParser(prog='ravel synthetic')
    commands = root.add_subparsers(dest='verb')
    for verb in VERBS:
        child = commands.add_parser(verb, help='synthetic ' + verb)
        common(child)
        if verb == 'emit':
            child.add_argument('--out', required=True)
    return root
''')
    value = _parser_fixture_inventory(tmp_path, generator, parsers)
    assert value['parser_gaps'] == []
    options = [row['details'] for row in value['entries'] if row['kind'] == 'option']
    assert {row['command'] for row in options if '--out' in row['names']} == {'ravel synthetic emit'}
    assert {row['command'] for row in options if '--no-enabled' in row['names']} == {
        'ravel synthetic inspect', 'ravel synthetic emit'}
    _write_documentation_fixture(tmp_path, generator, value)
    assert generator.snapshot_errors(tmp_path, value) == []
    source.write_text(source.read_text().replace("common(child)", "common(child)\n        child.add_argument('--new-source-option')"))
    fresh = _parser_fixture_inventory(tmp_path, generator, parsers)
    errors = generator.snapshot_errors(tmp_path, fresh)
    assert any('missing documentation entry:' in error for error in errors), errors
    assert any('stale documentation snapshot:' in error for error in errors), errors


def test_parser_inventory_keeps_unresolved_declarations_as_gaps(tmp_path, documentation_inventory_tools):
    generator, parsers = documentation_inventory_tools
    source = tmp_path / 'src/ravel/synthetic.py'
    source.parent.mkdir(parents=True)
    source.write_text('''
import argparse
def parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(discover_argument_at_runtime())
    return parser
''')
    value = _parser_fixture_inventory(tmp_path, generator, parsers)
    assert len(value['parser_gaps']) == 1
    assert any('unresolved parser declarations:' in error for error in generator.documentation_errors(tmp_path, value))


def test_documentation_schema_inventory_retains_nested_conditional_and_added_keys(documentation_inventory_tools):
    from copy import deepcopy
    generator, _ = documentation_inventory_tools
    schema = {'type': 'object', 'required': ['limit'], 'properties': {
        'limit': {'type': 'integer', 'minimum': 0},
        'records': {'type': 'array', 'items': {'type': 'object', 'properties': {'path': {'type': 'string'}}}},
        'policy': {'oneOf': [{'properties': {'mode': {'const': 'bounded'}}},
                            {'properties': {'mode': {'const': 'manual'}, 'reason': {'type': 'string'}}}]}}}
    fields = {row['key']: row for row in generator.schema_fields(schema)}
    assert set(fields) == {'limit', 'records', 'records[].path', 'policy', 'policy.mode', 'policy.reason'}
    assert fields['limit']['variants'][0]['required'] is True
    assert len(fields['policy.mode']['variants']) == 2
    mutated = deepcopy(schema)
    mutated['properties']['new_key'] = {'type': 'boolean'}
    assert set(row['key'] for row in generator.schema_fields(mutated)) - set(fields) == {'new_key'}


def test_documentation_schema_refs_follow_use_sites_and_source_mutations(documentation_inventory_tools):
    from copy import deepcopy
    generator, _ = documentation_inventory_tools
    schema = {'properties': {'identity': {'$ref': '#/$defs/identity'},
                             'destination': {'allOf': [{'$ref': '#/$defs/path'}, {'pattern': '^/'}]}},
              '$defs': {'identity': {'type': 'object', 'properties': {'scope': {'type': 'string'}}},
                        'path': {'type': 'string'}, 'unused': {'properties': {'ghost': {'type': 'boolean'}}}}}
    fields = {row['key']: row for row in generator.schema_fields(schema)}
    assert set(fields) == {'identity', 'identity.scope', 'destination'}
    assert fields['identity']['variants'][0]['constraints']['type'] == 'object'
    assert 'allOf' in fields['destination']['variants'][0]['constraints']
    changed = deepcopy(schema)
    changed['$defs']['identity']['properties']['new_field'] = {'type': 'integer'}
    assert set(row['key'] for row in generator.schema_fields(changed)) - set(fields) == {'identity.new_field'}
    changed['$defs']['identity']['properties']['recursive'] = {'$ref': '#/$defs/identity'}
    changed['properties']['missing'] = {'$ref': '#/$defs/not-present'}
    changed['properties']['external'] = {'$ref': 'synthetic-schema.json'}
    gaps = []
    references = []
    generator.schema_fields(changed, gaps=gaps, references=references)
    assert {gap['reason'] for gap in gaps} == {
        'missing local reference', 'missing confined schema document'}
    assert any(edge['recursive'] and edge['target_use_site'] == 'identity' for edge in references)
    assert all('ghost' not in row['key'] for row in generator.schema_fields(changed))


def test_documentation_schema_refs_follow_cross_file_ids_anchors_and_mutations(documentation_inventory_tools):
    from copy import deepcopy
    generator, _ = documentation_inventory_tools
    source = 'schemas/root.schema.json'
    record = {'$id': 'urn:synthetic:record', 'type': 'object', 'properties': {
        'label': {'type': 'string'}, 'next': {'$ref': 'root.schema.json'}}}
    anchored = {'$defs': {'payload': {'$anchor': 'payload', 'properties': {'value': {'type': 'integer'}}}}}
    root = {'properties': {'by_path': {'$ref': 'record.schema.json'},
                           'by_id': {'$ref': 'urn:synthetic:record'},
                           'by_anchor': {'$ref': 'anchored.schema.json#payload'}}}
    documents = {source: root, 'schemas/record.schema.json': record, 'schemas/anchored.schema.json': anchored}
    gaps, references = [], []
    before = {row['key']: row for row in generator.schema_fields(
        root, source=source, documents=documents, gaps=gaps, references=references)}
    assert gaps == []
    assert {'by_path.label', 'by_id.label', 'by_anchor.value'} <= set(before)
    assert before['by_path.label']['variants'][0]['source'] == 'schemas/record.schema.json'
    assert any(edge['recursive'] and edge['target_source'] == source for edge in references)
    changed = deepcopy(documents)
    changed['schemas/record.schema.json']['properties']['added_field'] = {'type': 'boolean'}
    after = {row['key'] for row in generator.schema_fields(root, source=source, documents=changed)}
    assert after - set(before) == {'by_path.added_field', 'by_id.added_field'}
    changed['schemas/duplicate.schema.json'] = deepcopy(record)
    gaps = []
    generator.schema_fields(root, source=source, documents=changed, gaps=gaps)
    assert {gap['reason'] for gap in gaps} == {'ambiguous declared schema identifier'}
    invalid = {'properties': {'remote': {'$ref': 'https://invalid.example/schema'},
                              'missing_anchor': {'$ref': 'anchored.schema.json#absent'}}}
    gaps = []
    generator.schema_fields(invalid, source=source, documents=documents, gaps=gaps)
    assert {gap['reason'] for gap in gaps} == {
        'unresolved schema identifier; no remote fetching', 'missing schema anchor'}


@pytest.mark.parametrize('category', [
    'parser_gaps', 'parser_context_gaps', 'graph_gaps', 'configuration_gaps',
    'schema_reference_gaps', 'environment_gaps',
])
def test_documentation_gate_refuses_every_unresolved_extraction_category(
        tmp_path, documentation_inventory_tools, category):
    generator, _ = documentation_inventory_tools
    value = _documentation_fixture(generator)
    _write_documentation_fixture(tmp_path, generator, value)
    assert generator.documentation_errors(tmp_path, value) == []
    value[category] = [{'source': 'src/ravel/synthetic.py', 'reason': 'Synthetic unresolved declaration'}]
    # Even a freshly rewritten snapshot must not hide a dropped declaration.
    _write_documentation_fixture(tmp_path, generator, value)
    assert any(error.startswith('unresolved ') for error in generator.snapshot_errors(tmp_path, value))


def test_documentation_schema_refs_preserve_source_defined_loader_dialects(documentation_inventory_tools):
    generator, _ = documentation_inventory_tools
    controller = 'src/ravel/data/controller/schemas/root.v1.json'
    judgment = 'src/ravel/data/judgment/schemas/protocols/root.v1.json'
    documents = {
        controller: {'properties': {'step': {'$ref': 'step.v1'}}},
        'src/ravel/data/controller/schemas/step.v1.json': {'properties': {'action': {'type': 'string'}}},
        judgment: {'properties': {'evidence': {'$ref': 'protocols/target.v1.json#attacks'}}},
        'src/ravel/data/judgment/schemas/protocols/target.v1.json': {
            'properties': {'attacks': {'type': 'array', 'items': {'properties': {'answer': {'type': 'string'}}}}}},
    }
    for source, expected in ((controller, 'step.action'), (judgment, 'evidence[].answer')):
        gaps = []
        fields = generator.schema_fields(documents[source], source=source, documents=documents, gaps=gaps)
        assert expected in {row['key'] for row in fields}
        assert gaps == []


def test_documentation_dispatch_roots_follow_required_wrapper_word_source(tmp_path, documentation_inventory_tools):
    generator, _ = documentation_inventory_tools
    source = tmp_path / 'src/ravel/cli.py'
    source.parent.mkdir(parents=True)
    source.write_text('''
FOCUSED_COMMANDS = {'synthetic-inspect': ('workflow.synthetic', 'inspect a synthetic document')}
LIFECYCLE_COMMANDS = {'synthetic-life': ('validation.synthetic', 'check', None, 'check a synthetic document')}
CONTROLLER_COMMANDS = {'synthetic-ask': ('controller.synthetic', 'main', 'ask a synthetic question')}
raise RuntimeError('dispatch source must not execute')
''')
    before = {row['name']: row for row in generator.command_registrations(tmp_path)}
    assert before['synthetic-life']['command'] == 'ravel synthetic-life check'
    assert before['synthetic-ask']['command'] == 'ravel synthetic-ask'
    source.write_text(source.read_text().replace("'check', None", "'inspect', None"))
    after = {row['name']: row for row in generator.command_registrations(tmp_path)}
    assert after['synthetic-life']['command'] == 'ravel synthetic-life inspect'
    assert after['synthetic-life']['command'] != before['synthetic-life']['command']


def test_documentation_effective_role_inventory_observes_fragment_and_override_sources(tmp_path, documentation_inventory_tools):
    import json
    generator, _ = documentation_inventory_tools
    roles = tmp_path / 'src/ravel/data/roles'
    roles.mkdir(parents=True)
    base = {'id': 'synthetic-base', 'family': 'research', 'purpose': 'Base synthetic purpose'}
    document = {'schema_version': 1, 'kind': 'role-registry', 'aliases': {},
                'roles': {base['id']: {'card': base, 'override': 'cards/synthetic-base.json'}}}
    (roles / 'registry.json').write_text(json.dumps(document))
    original = {row['card']['id']: row for row in generator.effective_roles(tmp_path)}
    assert set(original) == {'synthetic-base'}
    (roles / 'registration').mkdir()
    fragment = {'schema_version': 1, 'roles': {'synthetic-added': {'card': {
        'id': 'synthetic-added', 'family': 'research', 'purpose': 'Fragment synthetic purpose'}, 'override': None}}, 'aliases': {}}
    (roles / 'registration/synthetic.json').write_text(json.dumps(fragment))
    (roles / 'cards').mkdir()
    override = {**base, 'purpose': 'Override synthetic purpose'}
    (roles / 'cards/synthetic-base.json').write_text(json.dumps(override))
    changed = {row['card']['id']: row for row in generator.effective_roles(tmp_path)}
    assert set(changed) - set(original) == {'synthetic-added'}
    assert changed['synthetic-added']['source'] == 'src/ravel/data/roles/registration/synthetic.json'
    assert changed['synthetic-base']['source'] == 'src/ravel/data/roles/cards/synthetic-base.json'
    assert changed['synthetic-base']['card']['purpose'] == 'Override synthetic purpose'


def test_authored_reference_gate_rejects_sibling_option_unknown_command_and_module(
        tmp_path, documentation_inventory_tools):
    import importlib
    generator, parsers = documentation_inventory_tools
    references = importlib.import_module('documentation_references')
    source = tmp_path / 'src/ravel/synthetic.py'
    source.parent.mkdir(parents=True)
    source.write_text('''
import argparse
def parser():
    root = argparse.ArgumentParser(prog='ravel synthetic')
    commands = root.add_subparsers(dest='verb')
    first = commands.add_parser('first')
    first.add_argument('--first-only', action='store_true')
    second = commands.add_parser('second')
    second.add_argument('--second-only', action='store_true')
    return root
''')
    value = _parser_fixture_inventory(tmp_path, generator, parsers)
    (tmp_path / 'README.md').write_text('''# Synthetic guide
`ravel synthetic first --first-only`
`ravel synthetic second --second-only`
`ravel synthetic first -- --external-option`
`ravel.root` is a data file.
''')
    assert references.errors(tmp_path, value) == []
    with (tmp_path / 'README.md').open('a') as stream:
        stream.write('''
`ravel synthetic first --second-only`
`ravel synthetic stale-subcommand`
`ravel nonexistent-command`
`ravel.nonexistent_module`
''')
    errors = references.errors(tmp_path, value)
    assert {(row['kind'], row['reference']) for row in errors} == {
        ('option', 'ravel synthetic --second-only'),
        ('subcommand', 'ravel synthetic stale-subcommand'),
        ('command', 'ravel nonexistent-command'),
        ('module', 'ravel.nonexistent_module')}
    # Root prose files are part of the ordinary snapshot completeness gate.
    _write_documentation_fixture(tmp_path, generator, value)
    assert any('stale authored option reference:' in error for error in generator.snapshot_errors(tmp_path, value))


def test_documentation_graph_inventory_follows_source_wrappers_loops_aliases_and_mutations(
        tmp_path, documentation_inventory_tools):
    import importlib
    graphs = importlib.import_module('documentation_graphs')
    source = tmp_path / 'src/ravel/synthetic_graph.py'
    source.parent.mkdir(parents=True)
    source.write_text('''
raise RuntimeError('graph modules must never execute during documentation generation')
from langgraph.graph import StateGraph
from ravel.workflow import graph_nodes as nodes
def _common(builder):
    return lambda name, node: nodes.add(builder, name, node, graph_id='synthetic.graph')
def _standard(builder, add):
    add('standard', object())
def build(ctx):
    builder = StateGraph(dict)
    add = _common(builder)
    alias = add
    for index in range(3):
        alias(f'S{index}', object())
    _standard(builder, add)
    return builder
''')
    registrations = [{'id': 'synthetic.graph', 'module': 'ravel.synthetic_graph', 'builder': 'build'}]
    rows, gaps = graphs.collect_graph_nodes(tmp_path, registrations)
    assert gaps == []
    assert {row['name'] for row in rows} == {'S0', 'S1', 'S2', 'standard'}
    assert all(row['source'] == 'src/ravel/synthetic_graph.py' for row in rows)
    source.write_text(source.read_text().replace('    return builder', "    add('new-source-node', object())\n    return builder"))
    changed, gaps = graphs.collect_graph_nodes(tmp_path, registrations)
    assert gaps == []
    assert {row['name'] for row in changed} - {row['name'] for row in rows} == {'new-source-node'}
    source.write_text(source.read_text().replace('    return builder', '    for label in ctx.names:\n        alias(label, object())\n    return builder'))
    _, gaps = graphs.collect_graph_nodes(tmp_path, registrations)
    assert any('ctx.names' in gap['expression'] for gap in gaps)


def test_documentation_graph_inventory_resolves_imported_comprehension_source_population(
        tmp_path, documentation_inventory_tools):
    import importlib
    graphs = importlib.import_module('documentation_graphs')
    directory = tmp_path / 'src/ravel'
    directory.mkdir(parents=True)
    edges = directory / 'synthetic_edges.py'
    edges.write_text("EDGES = (('first', 'second'), ('second', 'first'))\n")
    (directory / 'synthetic_graph.py').write_text('''
from langgraph.graph import StateGraph
from ravel.workflow import graph_nodes as nodes
from .synthetic_edges import EDGES
def build(ctx):
    builder = StateGraph(dict)
    add = lambda name, node: nodes.add(builder, name, node, graph_id='synthetic.graph')
    names = {name for edge in EDGES for name in edge if name != 'second'}
    for name in sorted(names):
        add(name, object())
    return builder
''')
    registrations = [{'id': 'synthetic.graph', 'module': 'ravel.synthetic_graph', 'builder': 'build'}]
    rows, gaps = graphs.collect_graph_nodes(tmp_path, registrations)
    assert gaps == []
    assert {row['name'] for row in rows} == {'first'}
    edges.write_text("EDGES = (('first', 'third'), ('second', 'first'))\n")
    rows, gaps = graphs.collect_graph_nodes(tmp_path, registrations)
    assert gaps == []
    assert {row['name'] for row in rows} == {'first', 'third'}


def test_documentation_named_keysets_follow_confined_json_source_changes(tmp_path, documentation_inventory_tools):
    import json
    _, parsers = documentation_inventory_tools
    source = tmp_path / 'src/ravel/workflow/synthetic_settings.py'
    source.parent.mkdir(parents=True)
    data = tmp_path / 'src/ravel/data/synthetic-settings.json'
    data.parent.mkdir()
    data.write_text(json.dumps({'keys': ['first_field']}))
    source.write_text('''
raise RuntimeError('settings source must never execute')
import json
from pathlib import Path
SCHEMAS = json.loads((Path(__file__).parents[1] / 'data/synthetic-settings.json').read_text())
SETTINGS_KEYS = frozenset(SCHEMAS['keys'])
DEFAULT_KEYS = set(SETTINGS_KEYS) | {'second_field'}
''')
    before = parsers.Declarations(tmp_path, source)
    assert set(before.globals['DEFAULT_KEYS']) == {'first_field', 'second_field'}
    assert before.data_sources == {'src/ravel/data/synthetic-settings.json'}
    data.write_text(json.dumps({'keys': ['first_field', 'new_field']}))
    after = parsers.Declarations(tmp_path, source)
    assert set(after.globals['DEFAULT_KEYS']) - set(before.globals['DEFAULT_KEYS']) == {'new_field'}


def test_documentation_environment_inventory_follows_source_names_and_excludes_writes(
        tmp_path, documentation_inventory_tools):
    import importlib
    environment = importlib.import_module('documentation_environment')
    source = tmp_path / 'src/ravel/synthetic_environment.py'
    source.parent.mkdir(parents=True)
    source.write_text('''
raise RuntimeError('environment source must never execute')
import os as process
from os import getenv as read_variable
PREFIX = 'SYNTHETIC_'
NAMED_VARIABLE = PREFIX + 'ROOT'
def read(credential_variable):
    process.environ['SYNTHETIC_WRITE_ONLY'] = 'value'
    process.environ.pop('SYNTHETIC_POP_ONLY', None)
    root = process.environ[NAMED_VARIABLE]
    saved = process.environ.copy()
    copied = saved.get('SYNTHETIC_COPY')
    for name in ('SYNTHETIC_FIRST', 'SYNTHETIC_SECOND'):
        value = read_variable(name)
    selected = {name: process.environ.get(name) for name in ('SYNTHETIC_THIRD',)}
    token = process.environ.get(credential_variable)
    return root
''')
    rows, dynamic, gaps = environment.collect_environment_reads(tmp_path, [source])
    assert gaps == []
    assert {row['name'] for row in rows} == {
        'SYNTHETIC_ROOT', 'SYNTHETIC_COPY', 'SYNTHETIC_FIRST', 'SYNTHETIC_SECOND', 'SYNTHETIC_THIRD'}
    assert len(dynamic) == 1 and dynamic[0]['expression'] == 'credential_variable'
    assert all(row['source'] == 'src/ravel/synthetic_environment.py' and row['line'] > 1 for row in rows)
    source.write_text(source.read_text().replace("PREFIX + 'ROOT'", "PREFIX + 'NEW_ROOT'"))
    changed, _, _ = environment.collect_environment_reads(tmp_path, [source])
    assert {row['name'] for row in changed} - {row['name'] for row in rows} == {'SYNTHETIC_NEW_ROOT'}
    source.write_text(source.read_text().replace("PREFIX + 'NEW_ROOT'", 'discover_name()'))
    _, _, gaps = environment.collect_environment_reads(tmp_path, [source])
    assert len(gaps) == 1 and gaps[0]['expression'] == 'NAMED_VARIABLE'


def test_documentation_parser_rendering_preserves_fixed_typed_constraints(documentation_inventory_tools):
    generator, _ = documentation_inventory_tools
    location = 'src/ravel/synthetic.py:12'
    fixed = generator.structural_details({'default': 'False', 'choices': '[0, 1, 2]',
                                          'nargs': '+', 'required': 'True'}, location, parser=True)
    assert fixed == {'default': False, 'choices': [0, 1, 2], 'nargs': '+', 'required': 'True'}
    assert generator.structural_details({'default': 'None'}, location, parser=True)['default'] is None
    textual = generator.structural_details({'default': 'source: computed_path()', 'choices': "['first', 'second']"},
                                            location, parser=True)
    assert set(textual.values()) == {'source declaration at ' + location}


def test_documentation_parser_inventory_marks_unknown_availability_predicates(tmp_path, documentation_inventory_tools):
    _, parsers = documentation_inventory_tools
    source = tmp_path / 'src/ravel/synthetic_conditional.py'
    source.parent.mkdir(parents=True)
    source.write_text('''
raise RuntimeError('availability predicates must not execute')
import argparse
def parser():
    root = argparse.ArgumentParser(prog='ravel synthetic')
    commands = root.add_subparsers()
    if 'synthetic-backend' in available_backends():
        child = commands.add_parser('conditional')
        child.add_argument('--output', required=True)
    return root
''')
    rows, gaps = parsers.extract(tmp_path, [source])
    assert gaps == []
    conditional = [row for row in rows if row['kind'] in ('command', 'option')]
    assert len(conditional) == 2
    assert all(row['availability']['kind'] == 'conditional-source-declaration' for row in conditional)
    assert all(row['availability']['predicates'][0]['expression'] == "'synthetic-backend' in available_backends()"
               for row in conditional)
    assert not next(row for row in rows if row['kind'] == 'parser').get('availability')


def test_documentation_schema_inventory_follows_conditional_refs_and_dynamic_value_fields(documentation_inventory_tools):
    from copy import deepcopy
    generator, _ = documentation_inventory_tools
    schema = {'type': 'object', 'allOf': [{
        'if': {'properties': {'version': {'const': 2}}},
        'then': {'properties': {'record': {'$ref': '#/$defs/record'}}},
        'else': {'properties': {'legacy': {'type': 'boolean'}}}}],
        'dependentSchemas': {'feature': {'properties': {'dependent': {'type': 'integer'}}}},
        'properties': {'patterns': {'patternProperties': {'^item-': {'properties': {'path': {'type': 'string'}}}}},
                       'open_map': {'additionalProperties': {'properties': {'enabled': {'type': 'boolean'}}}}},
        '$defs': {'record': {'properties': {'identity': {'type': 'string'}}}}}
    boundaries, gaps = [], []
    before = {row['key']: row for row in generator.schema_fields(schema, boundaries=boundaries, gaps=gaps)}
    assert gaps == []
    assert set(before) == {'version', 'record', 'record.identity', 'legacy', 'feature', 'dependent',
                           'patterns', 'patterns.{key}.path', 'open_map', 'open_map.{key}.enabled'}
    assert any(condition.get('conditional') == 'then'
               for condition in before['record.identity']['variants'][0]['predicates'])
    assert {boundary['kind'] for boundary in boundaries} == {'patternProperties', 'additionalProperties'}
    changed = deepcopy(schema)
    changed['$defs']['record']['properties']['added_under_branch'] = {'type': 'number'}
    assert {row['key'] for row in generator.schema_fields(changed)} - set(before) == {'record.added_under_branch'}
    changed['allOf'][0]['else']['properties']['removed_reference'] = {'$ref': '#/$defs/absent'}
    generator.schema_fields(changed, gaps=gaps)
    assert any(gap['path'] == 'removed_reference' and gap['reason'] == 'missing local reference' for gap in gaps)


def test_documentation_environment_inventory_follows_parameter_defaults_and_constructor_aliases(
        tmp_path, documentation_inventory_tools):
    import importlib
    environment = importlib.import_module('documentation_environment')
    source = tmp_path / 'src/ravel/synthetic_environment_defaults.py'
    source.parent.mkdir(parents=True)
    source.write_text('''
raise RuntimeError('source environment fixtures must never execute')
import os
def read(env=os.environ):
    return env.get('SYNTHETIC_DEFAULT')
class Reader:
    def home(self):
        return self.environ.get('SYNTHETIC_CLASS_HOME')
    def __init__(self, supplied=None):
        self.environ = dict(os.environ if supplied is None else supplied)
    def write(self):
        self.environ['SYNTHETIC_WRITE_ONLY'] = 'value'
class OrdinaryRecord:
    def __init__(self):
        self.environ = {}
    def read(self):
        return self.environ.get('ORDINARY_RECORD_FIELD')
''')
    rows, dynamic, gaps = environment.collect_environment_reads(tmp_path, [source])
    assert gaps == [] and dynamic == []
    assert {row['name'] for row in rows} == {'SYNTHETIC_DEFAULT', 'SYNTHETIC_CLASS_HOME'}
    source.write_text(source.read_text().replace("return self.environ.get('SYNTHETIC_CLASS_HOME')",
                                               "return self.environ.get('SYNTHETIC_NEW_HOME')"))
    changed, _, _ = environment.collect_environment_reads(tmp_path, [source])
    assert {row['name'] for row in changed} - {row['name'] for row in rows} == {'SYNTHETIC_NEW_HOME'}


def test_documentation_parser_discovery_covers_root_nested_and_native_build_scripts(
        tmp_path, documentation_inventory_tools):
    generator, parsers = documentation_inventory_tools
    locations = ['scripts/synthetic_build.py', 'scripts/validation/synthetic_qualification.py',
                 'native/setup/recipes/synthetic_overlay.py', 'native/containers/synthetic/write_receipt.py']
    body = "import argparse\nparser = argparse.ArgumentParser()\nparser.add_argument('--original')\n"
    for relative in [*locations, 'tests/synthetic_not_product.py']:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    discovered = generator.parser_source_paths(tmp_path)
    assert {path.relative_to(tmp_path).as_posix() for path in discovered} == set(locations)
    rows, gaps = parsers.extract(tmp_path, discovered)
    assert gaps == []
    assert {row['source'] for row in rows} == set(locations)
    source = tmp_path / locations[0]
    source.write_text(body + "parser.add_argument('--new-build-option')\n")
    changed, gaps = parsers.extract(tmp_path, generator.parser_source_paths(tmp_path))
    assert gaps == []
    assert sum('--new-build-option' in row.get('names', []) for row in changed) == 1


# ---------------------------------------------------------------- reviewed citation maintenance

@pytest.fixture
def reviewed_passage_migration():
    import hashlib
    import importlib.util
    from ravel.controller.instructions import compiler

    spec = importlib.util.spec_from_file_location(
        'reviewed_passage_builder', ROOT / 'scripts/maintenance/build_instruction_catalogue.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    source, other = 'docs/contract.md', 'docs/other-contract.md'
    text = ('# Request contract\n\nKeep the requested quantity and input population.\n\n'
            'Retain source-bound review evidence.\n')
    compiled = {'texts': {source: text, other: text},
                'units': [*compiler.compile_markdown(source, text),
                          *compiler.compile_markdown(other, text)]}
    target = next(unit for unit in compiled['units']
                  if unit['source'] == source and unit['form'] == 'paragraph')
    citations = {'schema_version': 1, 'rows': [{
        'id': 'SYN-PASSAGE', 'source': source, 'line': 3,
        'evidence': 'The exact retired instruction.', 'source_sha256': 'original-source',
        'decision': True, 'blocking': True, 'kind': 'instruction',
        'migration_history': [{'reviewed_by': 'original-review', 'reason': 'Original history.'}],
        'migration': {'reviewed_by': 'prior-review', 'reason': 'Prior binding.'},
    }, {
        'id': 'SYN-UNCHANGED', 'source': other, 'line': 3,
        'source_sha256': hashlib.sha256(text.encode()).hexdigest(), 'decision': False,
    }]}
    review = {'schema_version': 2, 'citations_sha256': compiler.digest_value(citations),
              'migrations': [{
                  'id': 'SYN-PASSAGE', 'row_sha256': compiler.digest_value(citations['rows'][0]),
                  'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                  'units': {target['id']: compiler.digest_text(target['text'])},
                  'replaces_evidence': citations['rows'][0]['evidence'],
                  'reviewed_by': 'independent-document-review',
                  'reason': 'Reviewed exact original evidence and the complete replacement unit.',
              }]}
    return builder, compiler, compiled, citations, review


def test_reviewed_passage_migration_preserves_original_record_and_runtime_binding(reviewed_passage_migration):
    from copy import deepcopy
    builder, compiler, compiled, citations, review = reviewed_passage_migration
    original = deepcopy(citations)
    migrated = builder.apply_reviewed_migrations(citations, review, compiled)
    assert citations == original
    assert migrated['rows'][1] == original['rows'][1]
    assert {key: value for key, value in migrated['rows'][0].items() if key != 'migration'} == {
        key: value for key, value in original['rows'][0].items() if key != 'migration'}
    assert migrated['rows'][0]['migration']['replaces_evidence'] == original['rows'][0]['evidence']
    compiler.attach_census(compiled['units'], migrated['rows'], compiled['texts'])
    bound = [unit for unit in compiled['units'] if 'SYN-PASSAGE' in unit.get('census', [])]
    assert len(bound) == 1
    assert {unit['id'] for unit in bound} == set(review['migrations'][0]['units'])
    assert bound[0]['review_required'] is True and bound[0]['kind'] == 'duty'


@pytest.mark.parametrize('change', [
    'citation-digest', 'row-digest', 'source-digest', 'source-bytes', 'unit-bytes',
    'substring', 'unknown-unit', 'foreign-unit', 'two-units', 'empty-units',
    'missing-evidence', 'different-evidence', 'normalized-evidence', 'empty-original-evidence',
    'missing-reviewer', 'missing-reason', 'duplicate', 'boolean-version', 'unknown-version',
])
def test_reviewed_passage_migration_requires_exact_review_and_one_same_source_unit(
        reviewed_passage_migration, change):
    builder, compiler, compiled, citations, review = reviewed_passage_migration
    entry = review['migrations'][0]
    uid = next(iter(entry['units']))
    target = next(unit for unit in compiled['units'] if unit['id'] == uid)
    if change == 'citation-digest':
        review['citations_sha256'] = 'stale'
    elif change == 'row-digest':
        entry['row_sha256'] = 'stale'
    elif change == 'source-digest':
        entry['source_sha256'] = 'stale'
    elif change == 'source-bytes':
        compiled['texts'][target['source']] += '\nChanged source bytes.\n'
    elif change == 'unit-bytes':
        target['text'] += ' Changed unit bytes.'
    elif change == 'substring':
        entry['units'][uid] = compiler.digest_text('requested quantity')
    elif change == 'unknown-unit':
        entry['units'] = {'docs/contract.md#invented-substring/0': compiler.digest_text('requested quantity')}
    elif change == 'foreign-unit':
        foreign = next(unit for unit in compiled['units']
                       if unit['source'] != target['source'] and unit['text'] == target['text'])
        entry['units'] = {foreign['id']: compiler.digest_text(foreign['text'])}
    elif change == 'two-units':
        second = next(unit for unit in compiled['units']
                      if unit['source'] == target['source'] and unit['id'] != uid)
        entry['units'][second['id']] = compiler.digest_text(second['text'])
    elif change == 'empty-units':
        entry['units'] = {}
    elif change == 'missing-evidence':
        entry.pop('replaces_evidence')
    elif change == 'different-evidence':
        entry['replaces_evidence'] = 'An unrelated retired instruction.'
    elif change == 'normalized-evidence':
        entry['replaces_evidence'] += ' '
    elif change == 'empty-original-evidence':
        citations['rows'][0]['evidence'] = entry['replaces_evidence'] = ' '
        entry['row_sha256'] = compiler.digest_value(citations['rows'][0])
        review['citations_sha256'] = compiler.digest_value(citations)
    elif change in ('missing-reviewer', 'missing-reason'):
        entry['reviewed_by' if change == 'missing-reviewer' else 'reason'] = ' '
    elif change == 'duplicate':
        review['migrations'].append(dict(entry))
    else:
        review['schema_version'] = True if change == 'boolean-version' else 3
    with pytest.raises(ValueError):
        builder.apply_reviewed_migrations(citations, review, compiled)


@pytest.mark.parametrize('keep_evidence_field', [False, True])
def test_reviewed_migration_v1_still_refuses_passage_citations(
        reviewed_passage_migration, keep_evidence_field):
    builder, _, compiled, citations, review = reviewed_passage_migration
    review['schema_version'] = 1
    if not keep_evidence_field:
        review['migrations'][0].pop('replaces_evidence')
    with pytest.raises(ValueError):
        builder.apply_reviewed_migrations(citations, review, compiled)


@pytest.mark.parametrize('version', [1, 2])
def test_reviewed_whole_file_migrations_keep_complete_population_requirement(
        reviewed_passage_migration, version):
    builder, compiler, compiled, citations, review = reviewed_passage_migration
    row, entry = citations['rows'][0], review['migrations'][0]
    row['line'], row['evidence'] = 1, None
    review['schema_version'] = version
    entry.pop('replaces_evidence')
    entry['row_sha256'] = compiler.digest_value(row)
    review['citations_sha256'] = compiler.digest_value(citations)
    entry['units'] = {unit['id']: compiler.digest_text(unit['text'])
                      for unit in compiled['units'] if unit['source'] == row['source']}
    migrated = builder.apply_reviewed_migrations(citations, review, compiled)
    assert migrated['rows'][0]['migration'] == {
        key: entry[key] for key in ('reviewed_by', 'reason', 'source_sha256', 'units')}
    compiler.attach_census(compiled['units'], migrated['rows'], compiled['texts'])
    assert {unit['id'] for unit in compiled['units'] if 'SYN-PASSAGE' in unit.get('census', [])} == set(entry['units'])
    entry['units'].pop(next(iter(entry['units'])))
    with pytest.raises(ValueError, match='complete current unit population'):
        builder.apply_reviewed_migrations(citations, review, compiled)


# ---------------------------------------------------------------- documentation language

@pytest.fixture(scope='module')
def documentation_language_tools():
    import importlib.util
    import sys
    name = 'documentation_language'
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/maintenance/documentation_language.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_documentation_language_is_plain_and_positive(documentation_language_tools):
    assert documentation_language_tools.errors(ROOT) == []


@pytest.mark.parametrize('statement', [
    'RAVEL does not support this operation.', 'This operation is not supported.',
    'RAVEL cannot execute it.', "RAVEL can't execute it.", 'It is not yet ready.',
    'It is not available.', 'Unsupported operation.', 'Known gaps and limitations.',
    'This is out of scope.', 'It is not part of 1.3.0.', 'The interface is withheld.',
    'This is planned for a future release.', 'See the road' 'map.', 'Coming soon.',
    'Work in progress.', 'Future work.', 'Pending integration.', 'RAVEL is not wired.',
    'RAVEL is not integrated.', 'Unprovided execution.', 'Unwired execution.', 'RAVEL may run it.', 'It might work.', 'It should work.',
    'RAVEL currently runs it.', 'Experimental execution.', 'Best effort execution.',
    'Use it where possible.', 'Works in most cases.',
    'RAVEL does not\nsupport it.', 'RAVEL is not\nyet ready.',
])
def test_documentation_language_rejects_new_claims(tmp_path, documentation_language_tools, statement):
    path = tmp_path / 'docs/new-page.md'
    path.parent.mkdir()
    path.write_text(statement)
    assert documentation_language_tools.errors(tmp_path, [])


def test_documentation_language_exceptions_bind_exact_passages(tmp_path, documentation_language_tools):
    language = documentation_language_tools
    path = tmp_path / 'README.md'
    text = 'Do not publish inputs that cannot be shared under their licence.'
    path.write_text(text)
    exception = {'path': 'README.md', 'pattern': 'incapacity', 'text': text, 'count': 1,
                 'reason': 'User instruction preserving input licensing requirements.'}
    assert language.errors(tmp_path, [exception]) == []
    path.write_text(text + '\nRAVEL cannot execute the operation.')
    assert any('RAVEL cannot' in error for error in language.errors(tmp_path, [exception]))
    path.write_text(text + '\n' + text)
    assert language.errors(tmp_path, [exception])
    path.write_text('Keep input licences with published artifacts.')
    assert any('stale language exception' in error for error in language.errors(tmp_path, [exception]))


def test_documentation_language_scans_generated_json_prose(tmp_path, documentation_language_tools):
    import json
    path = tmp_path / 'docs/inventory.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'id': 'unsupported', 'summary': 'RAVEL may execute it.'}))
    assert documentation_language_tools.errors(tmp_path, [])
    path.write_text(json.dumps({'id': 'unsupported', 'summary': 'Registered source declaration.'}))
    assert documentation_language_tools.errors(tmp_path, []) == []


@pytest.mark.parametrize('suffix,payload', [
    ('.tex', r'\node {RAVEL may execute it.};'),
    ('.svg', '<svg xmlns="http://www.w3.org/2000/svg"><text>RAVEL cannot execute it.</text></svg>'),
])
def test_documentation_language_scans_diagram_sources(tmp_path, documentation_language_tools, suffix, payload):
    path = tmp_path / ('docs/diagram' + suffix)
    path.parent.mkdir()
    path.write_text(payload)
    assert documentation_language_tools.errors(tmp_path, [])


def test_documentation_language_checks_divergent_instruction_copies(tmp_path, documentation_language_tools):
    canonical = tmp_path / 'docs/workflow/start.md'
    canonical.parent.mkdir(parents=True)
    canonical.write_text('Run the approved operation.')
    copy = tmp_path / 'src/ravel/data/workflow/docs/workflow/start.md'
    copy.parent.mkdir(parents=True)
    copy.write_text(canonical.read_text())
    assert documentation_language_tools.errors(tmp_path, []) == []
    copy.write_text('RAVEL cannot execute the operation.')
    assert any('src/ravel/data/workflow/' in error for error in documentation_language_tools.errors(tmp_path, []))


@pytest.mark.parametrize('statement', [
    'For x < y, RAVEL cannot execute a fit; require z > w.',
    '<!-- RAVEL may execute it. -->',
])
def test_documentation_language_retains_comparisons_and_comment_prose(tmp_path, documentation_language_tools, statement):
    (tmp_path / 'README.md').write_text(statement)
    assert documentation_language_tools.errors(tmp_path, [])


def test_documentation_language_checks_replaced_agent_header(tmp_path, documentation_language_tools):
    canonical = tmp_path / 'src/ravel/data/agent_surface/instructions.md'
    canonical.parent.mkdir(parents=True)
    canonical.write_text('Run the approved operation.\n')
    (tmp_path / 'AGENTS.md').write_text('RAVEL cannot execute it.\n' + canonical.read_text())
    assert documentation_language_tools.errors(tmp_path, [])


def test_documentation_language_scans_svg_nested_visible_text(tmp_path, documentation_language_tools):
    path = tmp_path / 'docs/diagram.svg'
    path.parent.mkdir()
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text><tspan>RAVEL</tspan> cannot execute it.</text></svg>')
    assert documentation_language_tools.errors(tmp_path, [])


@pytest.mark.parametrize('statement', [
    '<img src="diagram.svg" alt="RAVEL cannot execute it.">',
    '<img src="diagram.svg" alt="`RAVEL cannot execute it.`">',
    '<span title="RAVEL may execute it.">Diagram</span>',
    '<div aria-label="RAVEL might execute it."></div>',
])
def test_documentation_language_scans_html_descriptions(tmp_path, documentation_language_tools, statement):
    (tmp_path / 'README.md').write_text(statement)
    assert documentation_language_tools.errors(tmp_path, [])



def test_documentation_language_scans_divergent_catalogue_document_units(tmp_path, documentation_language_tools):
    import json
    canonical = tmp_path / 'docs/workflow/start.md'
    canonical.parent.mkdir(parents=True)
    canonical.write_text('Run the approved operation.')
    catalogue = tmp_path / 'src/ravel/data/instructions/catalogue.json'
    catalogue.parent.mkdir(parents=True)
    from ravel.controller.instructions import compiler
    unit = compiler.compile_markdown('docs/workflow/start.md', canonical.read_text())[0]
    unit = {key: value for key, value in unit.items() if key not in ('source', 'section', 'n')}
    unit['text'] = unit['text'].splitlines()
    assert 'source' not in unit and isinstance(unit['text'], list)
    catalogue.write_text(json.dumps({'units': [unit]}))
    assert documentation_language_tools.errors(tmp_path, []) == []
    unit['text'] = ['RAVEL cannot execute it.']
    unit['source'] = 'src/unscanned.py'  # Source metadata cannot override the emitted identity.
    catalogue.write_text(json.dumps({'units': [unit]}))
    assert documentation_language_tools.errors(tmp_path, [])



def test_documentation_language_keeps_catalogue_code_and_prose_distinct(tmp_path, documentation_language_tools):
    import json
    from ravel.controller.instructions import compiler
    canonical = tmp_path / 'docs/workflow/start.md'
    canonical.parent.mkdir(parents=True)
    canonical.write_text('```text\nRAVEL cannot execute it.\n```\n')
    unit = compiler.compile_markdown('docs/workflow/start.md', canonical.read_text())[0]
    unit = {key: value for key, value in unit.items() if key not in ('source', 'section', 'n')}
    unit['text'] = unit['text'].splitlines()
    catalogue = tmp_path / 'src/ravel/data/instructions/catalogue.json'
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text(json.dumps({'units': [unit]}))
    assert documentation_language_tools.errors(tmp_path, []) == []
    unit.update(text=['RAVEL cannot execute it.'], form='paragraph')
    catalogue.write_text(json.dumps({'units': [unit]}))
    assert documentation_language_tools.errors(tmp_path, [])



def test_documentation_language_scans_new_json_prose_fields(tmp_path, documentation_language_tools):
    import json
    path = tmp_path / 'docs/new-inventory.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'new_capability_claim': 'RAVEL may execute it.'}))
    assert documentation_language_tools.errors(tmp_path, [])


def test_documentation_language_distinguishes_policy_operands_from_display_prose(tmp_path, documentation_language_tools):
    import json
    (tmp_path / 'distribution.json').write_text(json.dumps({'distribution': {'public_transforms': 'docs/policy.json'}}))
    target = tmp_path / 'docs/policy.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'old': ['cannot run'],
                                  'new': 'not available', 'purpose': 'Source export policy.'}))
    assert documentation_language_tools.errors(tmp_path, []) == []
    data = json.loads(target.read_text())
    data['purpose'] = 'RAVEL cannot run the operation.'
    target.write_text(json.dumps(data))
    assert documentation_language_tools.errors(tmp_path, [])


@pytest.mark.parametrize('statement', [
    '<img alt="RAVEL can&#110;ot execute it.">',
    '<img alt=RAVEL&#32;cannot&#32;execute>',
    '<img alt="x > `RAVEL cannot execute it.`">',
    '<span aria-description="RAVEL cannot execute it."></span>',
])
def test_documentation_language_scans_encoded_accessible_text(tmp_path, documentation_language_tools, statement):
    (tmp_path / 'README.md').write_text(statement)
    assert documentation_language_tools.errors(tmp_path, [])


@pytest.mark.parametrize('payload', [
    '<text><tspan x="0">RAVEL</tspan><tspan x="40">cannot</tspan><tspan x="80">execute.</tspan></text>',
    '<text aria-description="RAVEL cannot execute it.">Ready</text>',
])
def test_documentation_language_scans_positioned_svg_and_accessible_text(tmp_path, documentation_language_tools, payload):
    path = tmp_path / 'docs/figure.svg'
    path.parent.mkdir()
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg">' + payload + '</svg>')
    assert documentation_language_tools.errors(tmp_path, [])


def test_documentation_language_checks_policy_named_fields_in_regular_documents(tmp_path, documentation_language_tools):
    import json
    target = tmp_path / 'docs/ordinary.json'
    target.parent.mkdir()
    target.write_text(json.dumps({'terms': ['RAVEL cannot execute it.'], 'old': 'RAVEL may execute it.'}))
    assert len(documentation_language_tools.errors(tmp_path, [])) == 2


def test_documentation_language_scans_generated_native_agent_profiles(tmp_path, documentation_language_tools):
    path = tmp_path / '.claude/agents/ravel-synthetic.md'
    path.parent.mkdir(parents=True)
    path.write_text('Dispatch this role. RAVEL might execute it.')
    assert documentation_language_tools.errors(tmp_path, [])


def test_documentation_language_requires_exact_registered_policy_path(tmp_path, documentation_language_tools):
    import json
    (tmp_path / 'distribution.json').write_text(json.dumps({'distribution': {'public_scope': 'docs/policy.json'}}))
    target = tmp_path / 'docs/policy.json'
    target.parent.mkdir()
    target.write_text(json.dumps({'terms': ['future work'], 'purpose': 'Public content policy.'}))
    assert documentation_language_tools.errors(tmp_path, []) == []
    (tmp_path / 'docs/ordinary.json').write_text(target.read_text())
    assert documentation_language_tools.errors(tmp_path, [])


def _held_tree(root, *, declared, unreleased):
    """A toolchain tree whose census binds three groups; the released form lists no withheld groups."""
    import json
    (root / 'src/ravel/data/backends').mkdir(parents=True)
    (root / 'native/setup').mkdir(parents=True)
    (root / 'src/ravel/data/backends/census.json').write_text(json.dumps({'tools': [
        {'id': 'census-' + name, 'installer_groups': [name], 'doctor_checks': []} for name in ('engine', 'extra', 'later')]}))
    groups = [{'id': name, 'title': name, 'platforms': ['linux'], 'depends_on': [], 'checks': [], 'steps': [],
               'qualification': {'status': 'qualified'}} for name in declared]
    manifest = {'groups': groups, 'operations': [], 'default': {'disk_gb': 1, 'groups': declared}, 'profiles': {}}
    if unreleased:
        manifest['unreleased'] = {'groups': [{'id': name, 'check': name, 'reason': 'held'} for name in unreleased],
                                  'operations': []}
    (root / 'native/setup/toolchain-manifest.json').write_text(json.dumps(manifest))


def test_documentation_inventory_withholds_the_same_groups_from_a_source_tree_and_its_release(tmp_path, documentation_inventory_tools):
    generator, _ = documentation_inventory_tools
    from ravel.setup import manifest as toolchain
    source, released = tmp_path / 'source', tmp_path / 'released'
    _held_tree(source, declared=['engine', 'extra', 'later'], unreleased=['later'])
    _held_tree(released, declared=['engine', 'extra'], unreleased=[])
    assert generator.held_names(source, toolchain) == generator.held_names(released, toolchain) == ['later']


def test_documentation_inventory_names_a_held_group_only_as_a_word_of_its_own(documentation_inventory_tools):
    generator, _ = documentation_inventory_tools
    held = ['later']
    assert generator.names_any(held, 'native/containers/later/build.sh')
    assert generator.names_any(held, {'predicates': [{'expression': "'later' in released_kinds()"}]})
    assert not generator.names_any(held, 'native/containers/later-gate/build.sh')
    assert not generator.names_any(held, 'census-later')
    assert not generator.names_any([], 'native/containers/later/build.sh')
