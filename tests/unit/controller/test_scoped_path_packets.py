"""Fictional seat packets at the dispatch boundary, with real instruction consumers.

These are packet delivery and refusal controls, not executed controller routes,
process starts, worker receipts, scientific results or model calls. Named slices
select an existing seat's duties; their operations grant no execution authority.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from ravel.controller import instructions as ins
from ravel.paths import package_data_path
from ravel.workflow import role_registry, toolbelt


ROOT = Path(__file__).resolve().parents[3]
INPUTS = [{'artifact': 'fixture:outputs/source.json', 'sha256': 'a' * 64}]


class OwnedSeatScopeGap(AssertionError):
    """Only the recorded ROLES boundary receives expected-failure treatment."""


READING_ORACLES = {
    'proto:P1': ('docs/workflow/checklists/judgment-protocols.md', '## P1 — look-first'),
    'proto:P2': ('docs/workflow/checklists/judgment-protocols.md', '## P2 — basis-manifest'),
    'proto:P3': ('docs/workflow/checklists/judgment-protocols.md', '## P3 — trap-sweep'),
    'proto:P5': ('docs/workflow/checklists/judgment-protocols.md', '## P5 — discrepancy-decomposition'),
    'proto:P6': ('docs/workflow/checklists/judgment-protocols.md', '## P6 — source-ladder'),
    'checklist:data-acquisition': ('docs/workflow/checklists/data-acquisition.md',
                                 "# Checklist — acquiring the analysis's data + likelihood"),
    'hb:columnar-analysis': ('src/ravel/data/skills/tools/columnar-analysis/SKILL.md', 'name: columnar-analysis'),
    'hb:feynrules': ('src/ravel/data/skills/tools/feynrules/SKILL.md', 'name: feynrules'),
    'hb:inference-engines': ('src/ravel/data/skills/tools/inference-engines/SKILL.md', 'name: inference-engines'),
    'hb:lhapdf-pdf-sets': ('src/ravel/data/skills/tools/lhapdf-pdf-sets/SKILL.md', 'name: lhapdf-pdf-sets'),
    'hb:madgraph-launch': ('src/ravel/data/skills/tools/madgraph-launch/SKILL.md', 'name: madgraph-launch'),
    'hb:model-authoring': ('src/ravel/data/skills/tools/model-authoring/SKILL.md', 'name: model-authoring'),
    'hb:pyhf-workspace-patching': ('src/ravel/data/skills/tools/pyhf-workspace-patching/SKILL.md', 'name: pyhf-workspace-patching'),
    'hb:rivet-routine': ('src/ravel/data/skills/tools/rivet-routine/SKILL.md', 'name: rivet-routine'),
    'hb:roofit-histfactory': ('src/ravel/data/skills/tools/roofit-histfactory/SKILL.md', 'name: roofit-histfactory'),
    'hb:snakemake-workflows': ('src/ravel/data/skills/tools/snakemake-workflows/SKILL.md', 'name: snakemake-workflows'),
    'checklist:reproduction-closure': ('docs/workflow/checklists/reproduction-closure.md', '# Diagnose a failed physics reproduction'),
    'checklist:physics-traps': ('docs/workflow/checklists/physics-traps.md', '# Checklist — physics traps'),
}

# Authored source oracles, rather than the packet's selected roles or sources.
# The output family is the acknowledging packet schema; the card retains its
# separately declared producer.v1/findings.v2 final-record tool schema.
CASES = [
    ('intake', 'coordinator', 'ordinary-study-prepare', 'planning',
     'docs/workflow/steps/02-inputs.md', '# Step 2 — Inputs',
     ('proto:P1',), 'producer.v1', 'producer.v2', 'submit_final'),
    ('method-choice', 'consult-inference', 'inference', 'planning',
     'docs/workflow/steps/07-exclude.md', '# Step 7 — Exclusion (pyhf)',
     ('hb:inference-engines', 'hb:pyhf-workspace-patching', 'hb:roofit-histfactory'),
     'producer.v1', 'producer.v2', 'knowledge_find'),
    ('inference', 'inference', 'inference', 'exclude',
     'docs/workflow/steps/07-exclude.md', '# Step 7 — Exclusion (pyhf)',
     ('hb:inference-engines', 'hb:pyhf-workspace-patching'),
     'producer.v1', 'producer.v2', 'submit_final'),
    ('model', 'model-builder', 'model-inputs', 'planning',
     'docs/workflow/checklists/model-cards.md', '# Checklist — defining the model cards',
     ('hb:model-authoring', 'hb:feynrules'), 'producer.v1', 'producer.v2', 'submit_final'),
    ('generation', 'generator', 'generate', 'generate',
     'docs/workflow/steps/03-generate.md', '# Step 3 — Generate events',
     ('hb:madgraph-launch', 'hb:lhapdf-pdf-sets'), 'producer.v1', 'producer.v2', 'submit_final'),
    ('analysis', 'analysis-author', 'analyze', 'analyze',
     'docs/workflow/steps/04-analyze.md', '# Step 4 — Analyze',
     ('hb:columnar-analysis', 'hb:rivet-routine'), 'producer.v1', 'producer.v2', 'submit_final'),
    ('review', 'physics-critic', 'inference', 'verify',
     'docs/workflow/checklists/verification-panel.md', '# Checklist — the ADVERSARIAL VERIFICATION PANEL',
     ('proto:P1',), 'findings.v2', 'findings.v3', 'submit_final'),
    ('research', 'research-explorer', 'research-comparison', 'planning',
     'docs/workflow/reference/research-protocols.md', '# Staged scientific research protocols',
     ('proto:P1',), 'producer.v1', 'producer.v2', 'submit_final'),
    ('literature', 'literature-scout', 'literature-discovery-crawl', 'planning',
     'docs/workflow/checklists/data-acquisition.md', "# Checklist — acquiring the analysis's data + likelihood",
     ('proto:P6', 'checklist:data-acquisition'), 'producer.v1', 'producer.v2', 'literature_list_papers'),
    ('manuscript', 'manuscript-writer', 'manuscript-build', 'planning',
     'docs/reference/manuscript-production.md', '# Manuscript production API and contracts',
     ('proto:P1',), 'producer.v1', 'producer.v2', 'submit_final'),
    ('batch', 'consult-workflow-manager', 'external-workflow', 'planning',
     'src/ravel/data/skills/tools/snakemake-workflows/SKILL.md', 'name: snakemake-workflows',
     ('hb:snakemake-workflows',), 'producer.v1', 'producer.v2', 'knowledge_find'),
    ('judgment', 'coordinator', 'literal-calculation', 'planning',
     'docs/workflow/checklists/judgment-protocols.md', '# Checklist — judgment protocols',
     ('proto:P1',), 'producer.v1', 'producer.v2', 'submit_final'),
    ('plan-review', 'plan-critic', 'ordinary-study-prepare', 'planning',
     'docs/workflow/checklists/check-ins.md', '# Checklist — CHECK-INS',
     ('proto:P1', 'proto:P6', 'checklist:reproduction-closure'),
     'findings.v2', 'findings.v3', 'submit_final'),
]

REVIEW_CASES = [
    ('normalization-seat', 'normalization-auditor', 'inference', 'verify',
     'docs/workflow/checklists/verification-panel.md', '# Checklist — the ADVERSARIAL VERIFICATION PANEL',
     ('proto:P2',), 'findings.v2', 'findings.v3', 'submit_final'),
    ('discrepancy-seat', 'discrepancy-attributor', 'inference', 'verify',
     'docs/workflow/checklists/verification-panel.md', '# Checklist — the ADVERSARIAL VERIFICATION PANEL',
     ('proto:P5', 'checklist:reproduction-closure'), 'findings.v2', 'findings.v3', 'submit_final'),
    ('trap-seat', 'trap-auditor', 'inference', 'verify',
     'docs/workflow/checklists/verification-panel.md', '# Checklist — the ADVERSARIAL VERIFICATION PANEL',
     ('proto:P3', 'proto:P2', 'checklist:physics-traps'), 'findings.v2', 'findings.v3', 'submit_final'),
    ('verifier-seat', 'skeptical-verifier', 'inference', 'verify',
     'docs/workflow/checklists/verification-panel.md', '# Checklist — the ADVERSARIAL VERIFICATION PANEL',
     ('proto:P1',), 'findings.v2', 'findings.v3', 'submit_final'),
    ('decider-seat', 'physics-decider', 'inference', 'verify',
     'docs/workflow/checklists/verification-panel.md', '# Checklist — the ADVERSARIAL VERIFICATION PANEL',
     ('proto:P1',), 'findings.v2', 'findings.v3', 'submit_final'),
]


def source_card(role):
    """Read authored JSON independently of role_registry.load's projection."""
    rows = json.loads(package_data_path('roles', 'registry.json').read_text())['roles']
    row = rows.get(role)
    if row is None:
        return json.loads(package_data_path('roles', 'cards', role + '.json').read_text())
    override = row.get('override')
    return (json.loads(package_data_path('roles', override).read_text())
            if override else row['card'])


def packet_step(case, lean):
    name, role, operation, stage, source, *_ = case
    return {'id': 'fictional-' + name, 'kind': 'review' if name in ('review', 'plan-review') or name.endswith('-seat') else 'derive',
            'role': role, 'route': name, 'stage': stage, 'operation': operation,
            'description': 'Inspect the supplied fictional fixture and preserve its recorded scope.',
            'inputs': deepcopy(INPUTS), 'outputs': [], 'depends_on': [],
            'instruction_sources': [source], 'protocols': [], 'parameters': {},
            'engagement': {'inline_context_tokens': 0} if lean else {}}


@pytest.mark.parametrize('lean', [False, True], ids=['ordinary-context', 'zero-inline-context'])
@pytest.mark.parametrize('case', CASES + REVIEW_CASES, ids=[case[0] for case in CASES + REVIEW_CASES])
def test_scoped_packet_delivers_source_duties_and_refuses_changed_dispatch(case, lean):
    name, role, operation, _, source, snippet, readings, declared_schema, packet_schema, tool = case
    card = role_registry.load(role)
    authored = source_card(role)
    # Effective operations may gain explicit registered assignments. Every other
    # field must equal the independently read authored card, without omission.
    assert {k: v for k, v in card.items() if k != 'operations'} == {
        k: v for k, v in authored.items() if k != 'operations'}
    assert set(authored['operations']) <= set(card['operations'])
    assert card['output']['schema'] == declared_schema
    assert tuple(card['knowledge']['must_read']) == readings
    step = packet_step(case, lean)
    manifest = ins.manifest(step, card)
    built = ins.packet(manifest, card, step, INPUTS)
    text = built['text']
    assert json.dumps(card, indent=1, sort_keys=True, ensure_ascii=False) in text
    assert snippet in (ROOT / source).read_text() and snippet in text
    assert built['schema_id'] == packet_schema
    Draft202012Validator.check_schema(built['schema'])
    assert built['schema']['additionalProperties'] is False
    assert built['schema']['properties']['instruction_ack']['properties']['manifest_sha256']['const'] == manifest['sha256']

    catalogue = ins.installed()
    source_units = [row for row in manifest['units'] if row['id'].startswith(source + '#')]
    assert source_units, (name, source)
    assert any(row['kind'] == 'duty' for row in source_units)
    # Every mandatory text is inline even when the context allowance is zero.
    mandatory = [row for row in manifest['units']
                 if row['kind'] == 'duty' or row['via'] in ('card', 'must_read')]
    assert mandatory and not {row['id'] for row in mandatory} & set(built['deferred'])
    for row in mandatory:
        assert catalogue.units[row['id']]['text'] in text, row['id']
    for reading in readings:
        reading_source, reading_snippet = READING_ORACLES[reading]
        assert reading_snippet in (ROOT / reading_source).read_text()
        assert reading_snippet in text
        owed = set(catalogue.resolve('knowledge:' + reading))
        assert owed and owed <= {row['id'] for row in manifest['units']}
        assert owed <= set(built['units'])
        assert all(uid.startswith(reading_source + '#') for uid in owed)

    tools = toolbelt.build(card)['tools']
    by_name = {row['name']: row for row in tools}
    assert tool in by_name and 'submit_final' in by_name
    declared = json.loads(package_data_path('roles', 'schema', 'outputs', declared_schema + '.json').read_text())
    declared.pop('$schema', None)
    assert by_name['submit_final']['args_schema'] == declared
    Draft202012Validator.check_schema(by_name['submit_final']['args_schema'])
    capabilities = {row['id']: row for row in built['capability_context']['catalogue']['entries']}
    assert capabilities['op:' + operation]['kind'] == 'operation'
    assert capabilities['tool:affordance/' + tool]['kind'] == 'tool'
    assert 'op:' + operation + ' | cost=' in text
    assert 'tool:affordance/' + tool + ' | cost=' in text

    # Parent-held sentinel: only the real packet check can release this local
    # downstream boundary. It neither dispatches a worker nor credits evidence.
    downstream = []

    def release(candidate, pinned_inputs):
        errors = ins.check_packet(candidate, manifest, card, step, pinned_inputs)
        if not errors:
            downstream.append(name)
        return errors

    changed = deepcopy(built)
    changed['text'] = changed['text'].replace(card['purpose'], 'Changed fictional duty')
    changed['sha256'] = hashlib.sha256(changed['text'].encode()).hexdigest()
    errors = release(changed, INPUTS)
    assert 'effective card missing or altered in the packet' in errors and downstream == []
    foreign_inputs = deepcopy(INPUTS)
    foreign_inputs[0]['sha256'] = 'b' * 64
    errors = release(built, foreign_inputs)
    assert 'packet differs from the installed instruction catalogue' in errors and downstream == []
    assert release(built, INPUTS) == [] and downstream == [name]


def test_non_analysis_seat_receives_its_route_neutral_task_scope():
    """ROLES/REPORT.md #112/I1; scoped advisory work must retain its own route."""
    case = CASES[9]  # manuscript/manuscript-writer, independent of analysis routing
    step = packet_step(case, False)
    card = role_registry.load('manuscript-writer')
    manifest = ins.manifest(step, card)
    built = ins.packet(manifest, card, step, INPUTS)
    # Establish unrelated custody/schema preconditions before the known defect.
    assert ins.check_packet(built, manifest, card, step, INPUTS) == []
    assert built['schema_id'] == 'producer.v2'
    if '== Seat scope ==' not in built['text']:
        raise OwnedSeatScopeGap('ROLES #112/I1: route-neutral seat scope is absent')
    scope_text = built['text'].split('== Seat scope ==', 1)[1]
    scope = json.JSONDecoder().raw_decode(scope_text.lstrip())[0]
    assert scope['role'] == 'manuscript-writer'
    assert scope['route'] == 'manuscript' and scope['stage'] == 'planning'
    assert scope['operation'] == 'manuscript-build'
    assert scope['purpose'] == 'Write only evidence-supported claims and preserve provenance, unsuccessful attempts and disclosure.'
    assert scope['response_schema'] == 'producer.v2'
