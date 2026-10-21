"""Request plan sidecar (S1-03): signatures, templates, the deterministic draft and the plan check."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

import request_plan_corpus as corpus
from shipped_catalogue import shipped_operations
from ravel.workflow import request_plan as rp
from ravel.workflow import task_completion
from ravel.validation import validate_request_plan as vp

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'src/ravel'
ENVELOPE = {'error_class', 'reason', 'action_required', 'suggested_next_operation', 'evidence_ids'}
# Experiment, collaboration, paper, benchmark and challenge identities never name a vocabulary item or template.
IDENTITY = re.compile(r'(?i)\b(?:atlas|cms|lhcb|alice|belle|babar|arxiv|inspire|ins\d{4,}|\d{4}\.\d{4,5}|'
                      r'(?:sus|exo|hig|top|smp|b2g)-\d{2}-\d{3}|benchmark|challenge|'
                      r'olympics|hl-lhc)\b')
# Named suites, compared systems and studies are refused by the generality gate's denylist.
from ravel.validation import check_generality  # noqa: E402
DENYLIST = check_generality.load_denylist(None, env={})
CRITICAL_PATH = ('generate', 'likelihood', 'lhe-transform', 'generation-reconciliation', 'event-production',
                 'columnar-analysis', 'authored-analysis', 'formula-grid', 'coupling-morphing', 'prescribed-statistic',
                 'search-statistics', 'differential-likelihood', 'figure-comparison', 'model-authoring',
                 'cross-section', 'group-normalization', 'normalized-measurement', 'amplitude-integration',
                 'amplitude-predictions', 'weighted-events', 'amplitude-crosscheck', 'measurement', 'eft-toolchain',
                 'cosmology-solver', 'resonance-width', 'fill-template', 'manuscript-build', 'analyze',
                 'model-events', 'analysis-lifecycle', 'lifecycle-routine-recast', 'lifecycle-workspace-limit',
                 'lifecycle-shape-fit', 'lifecycle-scan-aggregation', 'lifecycle-summary-overlay')


def drafted(name):
    case = corpus.CASES[name]()
    return case, rp.draft(case.doc, case.contract(), catalogue=corpus.catalogue)


def errors(case, plan, **kwargs):
    kwargs.setdefault('obligations', case.obligations)
    kwargs.setdefault('catalogue', corpus.catalogue)
    return vp.check(case.doc, plan, **kwargs)


def classes(rows):
    return {e['error_class'] for e in rows}


def node(plan, operation):
    return next(n for n in plan['nodes'] if n['operation'] == operation)


# --------------------------------------------------------------------------- signatures
def test_signatures_follow_the_schema_and_name_registered_operations():
    signed = vp.signatures()
    registry = vp.registry()
    from ravel.workflow import science, scoped_spec
    for name, entry in signed.items():
        assert name in registry
        implementation = entry['implementation']
        if implementation['kind'] == 'science-mode':
            assert name in science.MODES and implementation['mode'] == name
        if implementation['kind'] == 'scoped-adapter':
            assert name in scoped_spec.MODES
        module = implementation.get('module')
        assert module and (SRC.parent / (module.replace('.', '/') + '.py')).is_file(), name
        for slot in entry['consumes'] + entry['produces']:
            assert slot['kind'] in vp.ARTIFACT_KINDS or re.match(vp.NAMESPACED_KIND, slot['kind'])
        assert set(entry['effects']) <= set(vp.EFFECTS)
        assert {a['element'] for a in entry['basis']['adds']} <= set(vp.BASES[:-1])
        slots = {s['slot'] for s in entry['consumes']}
        assert set(entry['basis']['passes']) <= slots, name
        for add in entry['basis']['adds']:
            for key in ('origin_from', 'level_from'):
                if key in add:
                    assert add[key].split('.')[0] in slots, (name, add)


def test_the_critical_path_operations_are_signed_and_general():
    assert set(shipped_operations(CRITICAL_PATH)) <= set(vp.signatures())
    from ravel.workflow.capability_routing import declared_descriptors
    descriptors = declared_descriptors()
    assert all(descriptors[mode]['descriptor']['applicability']['scope'] == 'general'
               for mode in CRITICAL_PATH if mode in descriptors)


def test_an_unlisted_mode_contributes_unclassified_and_a_flag():
    # Every registered mode is signed (Stage 2 row 2-02); a registry with one entry withdrawn stands in.
    assert all(entry is not None for entry in vp.registry().values())
    registry = dict(vp.registry(), quantities=None)
    case, plan = drafted('supplied-events-search')
    analysis = node(plan, 'columnar-analysis')
    analysis['operation'] = 'quantities'
    plan['claims'][0]['basis_declared'] = sorted(set(plan['claims'][0]['basis_declared']) | {'unclassified'},
                                                 key=vp.BASES.index)
    rows = errors(case, plan, reg=registry)
    assert 'unknown_operation' not in classes(rows)
    assert 'unclassified' in {r['element'] for r in vp.computed_bases(plan, registry)['C1']}
    assert any(f['flag'] == 'unclassified' and analysis['id'] in f['ids'] for f in vp.flags(case.doc, plan, registry))


# --------------------------------------------------------------------------- templates and neutrality
def test_templates_are_generic_and_use_registered_operations():
    rows = rp.templates()
    assert rows and rows[-1]['id'] == 'open-research'
    registry = vp.registry()
    for template in rows:
        text = json.dumps(template)
        assert not IDENTITY.search(text), template['id']
        assert not DENYLIST.hits(text), template['id']
        assert re.fullmatch(r'[a-z][a-z0-9-]*', template['id'])
        for spec in template['nodes']:
            # A template may name an operation this tree does not ship; the planner then does not propose it.
            assert spec['operation'] is None or spec['operation'] in registry or not shipped_operations([spec['operation']])
    vocabulary = ' '.join([*vp.ARTIFACT_KINDS, *vp.EFFECTS, *vp.BASES, *vp.CLAIM_KINDS, *vp.BOUNDARY_CLASSES,
                           *vp.signatures()])
    assert not IDENTITY.search(vocabulary)
    assert not DENYLIST.hits(vocabulary)


def test_no_code_path_reads_the_identity_context():
    for path in (SRC / 'workflow/request_plan.py', SRC / 'validation/validate_request_plan.py'):
        tree = ast.parse(path.read_text())
        hits = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == 'identity_context']
        allowed = [n for a in ast.walk(tree) if isinstance(a, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'CONSTRAINT_TYPES' for t in a.targets)
                   for n in ast.walk(a.value) if isinstance(n, ast.Constant) and n.value == 'identity_context']
        assert hits == allowed, path


def test_a_context_label_does_not_change_the_plan():
    base = corpus.binned_yield_template()
    labelled = corpus.Reading(base.prompt + '\nTask label: Example Suite case 7')
    labelled.doc = deepcopy(base.doc)
    labelled.doc['prompt_sha256'] = hashlib.sha256(labelled.prompt.encode()).hexdigest()
    labelled.doc['constraints'].append({'id': f'K{len(base.doc["constraints"]) + 1}', 'type': 'identity_context',
                                        'value': {'label': 'Example Suite case 7'},
                                        'evidence': [labelled.span('Example Suite case 7')]})
    labelled.obligations = [labelled.obligations[0], *deepcopy(base.obligations[1:])]
    one = rp.draft(base.doc, base.contract())
    two = rp.draft(labelled.doc, labelled.contract())
    for plan in (one, two):
        plan.pop('reading'), plan.pop('prompt_sha256')
    assert one == two


def test_a_template_needing_an_operation_the_tree_does_not_register_is_not_proposed(monkeypatch):
    """A tree that withholds an operation drafts around every template that needs it."""
    case = corpus.CASES['written-note']()
    needed = {n['operation'] for t in rp.templates() if t['id'] == 'document-assembly' for n in t['nodes']} - {None}
    assert needed
    registry = {name: row for name, row in vp.registry().items() if name not in needed}
    monkeypatch.setattr(vp, 'registry', lambda: dict(registry))
    plan = rp.draft(case.doc, case.contract(), catalogue=corpus.catalogue)
    assert not needed & {n['operation'] for n in plan['nodes']}
    assert errors(case, plan, reg=registry) == []
    assert {row['obligation_id'] for row in plan['coverage']} == {o['id'] for o in case.obligations}


# --------------------------------------------------------------------------- the corpus
@pytest.mark.parametrize('name', sorted(corpus.CASES))
def test_every_corpus_draft_checks_and_covers_every_obligation(name):
    case, plan = drafted(name)
    task_completion.validate_requirements(case.contract())
    assert vp.reading_schema_errors(case.doc) == []
    assert vp.plan_schema_errors(plan) == []
    assert errors(case, plan) == []
    covered = {row['obligation_id'] for row in plan['coverage']}
    assert covered == {o['id'] for o in case.obligations}
    assert plan['status'] == 'draft' and plan['authors'][0]['actor'] == 'local-proposer'
    assert plan['reading'] == rp.pin('inputs/reading.json', case.doc)
    for operation, sha in plan['signatures']['entries'].items():
        assert sha == vp.entry_sha256(vp.signatures()[operation])


@pytest.mark.parametrize('name', sorted(corpus.CASES))
def test_the_draft_is_deterministic_across_processes(name):
    case, plan = drafted(name)
    assert rp.document_bytes(rp.draft(case.doc, case.contract(), catalogue=corpus.catalogue)) == rp.document_bytes(plan)
    script = ('import sys, hashlib; sys.path[:0] = [sys.argv[1], sys.argv[2]];'
              'import request_plan_corpus as c; from ravel.workflow import request_plan as p;'
              'x = c.CASES[sys.argv[3]](); print(hashlib.sha256(p.document_bytes('
              'p.draft(x.doc, x.contract(), catalogue=c.catalogue))).hexdigest())')
    out = subprocess.run([sys.executable, '-c', script, str(SRC.parent), str(Path(__file__).parent), name],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == hashlib.sha256(rp.document_bytes(plan)).hexdigest()


def test_the_w_mass_question_plans_no_event_generation():
    case, plan = drafted('w-mass-triplet')
    registry = vp.registry()
    assert not any('generates_events' in vp._effects(n, registry) for n in plan['nodes'])
    assert [n['operation'] for n in plan['nodes']] == ['acquire-published', 'source-tables', 'formula-grid', 'measurement']
    claim = plan['claims'][0]
    assert claim['kind'] == 'estimate' and claim['level'] == 'observed'
    assert 'analytic' in claim['basis_declared'] and plan['label']['rule'] == 'D5'


def test_probes_become_open_parents_with_their_shape():
    assert drafted('muon-collider-self-coupling')[1]['claims'][0]['level'] == 'expected'
    case, plan = drafted('displaced-dimuon-background')
    assert plan['boundaries'] == ['B1'] and any('B1' in row['by'] for row in plan['coverage'])
    case, plan = drafted('tagger-method-study')
    train = node(plan, 'authored-analysis')
    assert train['kind'] == 'authored' and 'trained_model' in plan['claims'][0]['basis_declared']
    assert any(w['kind'] == 'known_answer' and w['after'] == train['id'] for w in plan['waypoints'])
    case, plan = drafted('spin-correlation-agreement')
    assert plan['claims'][0]['statistic']['source'] == 'declared'
    for name in ('muon-collider-self-coupling', 'displaced-dimuon-background', 'spin-correlation-agreement',
                 'tagger-method-study', 'w-mass-triplet'):
        assert drafted(name)[1]['label'] == {'task_mode': 'research', 'rule': 'D5',
                                             'floor_row': drafted(name)[1]['label']['floor_row']}


def test_requested_stages_keep_their_nodes_and_restricted_sources_are_not_acquired():
    case, plan = drafted('binned-yield-template')
    operations = [n['operation'] for n in plan['nodes']]
    assert operations == ['model-events', 'event-production', 'columnar-analysis', 'fill-template']
    assert plan['claims'][0]['deliverable']['artifact'] == 'table'
    assert 'acquire-published' not in operations
    shower = next(o['id'] for o in case.obligations if o['statement'] == 'Pythia shower')
    assert node(plan, 'event-production')['id'] in next(r['by'] for r in plan['coverage'] if r['obligation_id'] == shower)


def test_a_prescribed_statistic_stays_primary_verbatim():
    case, plan = drafted('prescribed-significance-contour')
    statistic = plan['claims'][0]['statistic']
    assert statistic == {'source': 'prescribed', 'definition': 'Sig = 2(sqrt(S+B) - sqrt(B)) = 2',
                         'evidence': [case.span('Sig = 2(sqrt(S+B) - sqrt(B)) = 2')], 'secondary': []}
    assert node(plan, 'model-events')['fan_out']['axes'][0]['values'] == [2, 2.5, 3]


def test_derived_label_rules():
    assert drafted('content-free')[1]['label']['rule'] == 'D1'
    assert drafted('private-data')[1]['label'] == {'task_mode': 'unsupported', 'rule': 'D1', 'floor_row': 'unsupported'}
    assert drafted('scoped-generation')[1]['label'] == {'task_mode': 'generate', 'rule': 'D2', 'floor_row': 'generate'}
    assert drafted('stated-counts')[1]['label']['task_mode'] == 'likelihood'
    assert drafted('preserved-recast')[1]['label'] == {'task_mode': 'reinterpret', 'rule': 'D3',
                                                       'floor_row': 'reinterpret'}
    assert drafted('preserved-recast-scan')[1]['label']['task_mode'] == 'scan'
    assert drafted('stated-arithmetic')[1]['label']['rule'] == 'D4'
    assert drafted('written-note')[1]['label']['floor_row'] == 'manuscript'
    assert drafted('tagger-method-study')[1]['label']['floor_row'] == 'method_study'


def test_without_a_preserved_routine_a_recast_is_served_by_children():
    case = corpus.preserved_recast()
    plan = rp.draft(case.doc, case.contract(), catalogue=lambda locator: False)
    assert 'analysis-lifecycle' not in {n['operation'] for n in plan['nodes']}
    assert errors(case, plan, catalogue=lambda locator: False) == []
    assert plan['label']['rule'] == 'D5'
    assert any(f['flag'] == 'not_certified_on_this_route' for f in vp.flags(case.doc, plan, catalogue=lambda x: False))


def test_a_requested_generator_is_held_not_substituted():
    case, plan = drafted('requested-generator')
    generator = node(plan, 'model-events')
    assert generator['status'] == 'held' and {'pointer': '/tool', 'value': 'Powheg', 'authority': 'user_quoted',
                                              'evidence': 'K1'} in generator['fields']
    assert node(plan, 'figure-comparison')['id'] in vp.ancestors(plan, 'C1')
    generator.update(status='available', held_by=None)
    generator['fields'] = [f for f in generator['fields'] if f['pointer'] != '/tool']
    assert 'requested_tool_unserved' in classes(errors(case, plan))


# --------------------------------------------------------------------------- typed errors
def test_every_error_uses_the_refusal_envelope():
    case, plan = drafted('supplied-events-search')
    plan['nodes'][0]['operation'] = 'no-such-mode'
    rows = errors(case, plan)
    assert rows and all(set(r) == ENVELOPE for r in rows)


def test_unregistered_mode():
    case, plan = drafted('supplied-events-search')
    plan['nodes'][0]['operation'] = 'no-such-mode'
    assert 'unknown_operation' in classes(errors(case, plan))


def test_unproduced_consumed_kind():
    case, plan = drafted('supplied-events-search')
    analysis = node(plan, 'columnar-analysis')['id']
    plan['edges'] = [e for e in plan['edges'] if not (e['to']['ref'] == analysis and e['to']['slot'] == 'events')]
    assert 'slot_unfilled' in classes(errors(case, plan))


def test_incompatible_edge_kind():
    case, plan = drafted('supplied-events-search')
    edge = next(e for e in plan['edges'] if e['to']['slot'] == 'signal')
    edge['kind'] = 'table'
    assert 'edge_incompatible' in classes(errors(case, plan))


def test_negated_stage_node():
    case, plan = drafted('binned-yield-template')
    case.doc['constraints'].append({'id': 'K9', 'type': 'negated_stage', 'value': {'stage': 'detector'},
                                    'evidence': [case.span('Delphes detector simulation')]})
    assert 'negated_stage_present' in classes(errors(case, plan))


def test_negated_stage_is_not_planned():
    case = corpus.binned_yield_template()
    case.doc['constraints'] = [c for c in case.doc['constraints'] if c['value'].get('stage') != 'detector']
    case.doc['constraints'].append({'id': 'K9', 'type': 'negated_stage', 'value': {'stage': 'detector'},
                                    'evidence': [case.span('Delphes detector simulation')]})
    case.doc['deliverables'][0]['artifact']['require'] = {}
    plan = rp.draft(case.doc, case.contract())
    assert 'event-production' not in {n['operation'] for n in plan['nodes']}
    assert 'negated_stage_present' not in classes(errors(case, plan))


def test_forbidden_source_consumer():
    case, plan = drafted('w-mass-triplet')
    case.doc['constraints'].append({'id': 'K9', 'type': 'source_restriction',
                                    'value': {'kind': 'forbidden-source', 'classes': ['hepdata']},
                                    'evidence': [case.span('W mass')]})
    assert 'forbidden_source' in classes(errors(case, plan))
    clean = rp.draft(case.doc, case.contract())
    assert 'hepdata' not in node(clean, 'acquire-published')['fields'][0]['value']
    assert 'forbidden_source' not in classes(errors(case, clean))


def test_orphan_compute():
    case, plan = drafted('supplied-events-search')
    extra = deepcopy(node(plan, 'columnar-analysis'))
    extra.update(id='N9', covers=['not-an-obligation'])
    plan['nodes'].append(extra)
    plan['edges'].append({'id': 'E9', 'from': {'ref': 'I1', 'slot': 'provided'}, 'to': {'ref': 'N9', 'slot': 'events'},
                          'kind': 'event_sample', 'require': {}, 'resolution': 'compatible', 'converter': None,
                          'acceptance': 'accepted_review'})
    plan['edges'].append({'id': 'E10', 'from': {'ref': 'I3', 'slot': 'provided'}, 'to': {'ref': 'N9', 'slot': 'recipe'},
                          'kind': 'selection', 'require': {}, 'resolution': 'compatible', 'converter': None,
                          'acceptance': 'accepted_review'})
    assert classes(errors(case, plan)) == {'orphan_compute'}


def test_changed_prescribed_statistic():
    case, plan = drafted('prescribed-significance-contour')
    plan['claims'][0]['statistic'].update(source='policy_default', definition='95% CLs', evidence=[])
    assert 'statistic_policy_violation' in classes(errors(case, plan))
    case, plan = drafted('prescribed-significance-contour')
    plan['claims'][0]['statistic']['secondary'] = [{'definition': '95% CLs', 'label': 'alongside'}]
    assert errors(case, plan) == []


def test_statistic_policy_defaults_and_declarations():
    case, plan = drafted('supplied-events-search')
    plan['claims'][0]['statistic']['definition'] = '90% CLs'
    assert 'statistic_policy_violation' in classes(errors(case, plan))
    case, plan = drafted('spin-correlation-agreement')
    plan['status'] = 'proposed'
    assert 'statistic_policy_violation' in classes(errors(case, plan))
    plan['claims'][0]['statistic']['definition'] = 'chi2 of the difference with the declared correlation'
    plan['claims'][0]['comparison'].update(metric='chi2 p-value', tolerance={'p_min': 0.05})
    assert errors(case, plan) == []


def test_p0_s1_prime_violations():
    case, plan = drafted('preserved-recast')
    case.doc['constraints'].append({'id': 'K9', 'type': 'blinding', 'value': {},
                                    'evidence': [case.span('Recast analysis-routine-X')]})
    assert 'in_place_retention' in classes(errors(case, plan))
    case, plan = drafted('preserved-recast')
    assert errors(case, plan, anchors=[{'locator': 'analysis-routine-X', 'withheld': False}]) == []
    assert 'in_place_retention' in classes(errors(case, plan, anchors=[]))
    child = rp.draft(case.doc, case.contract(), catalogue=lambda locator: False)
    assert 'in_place_retention' in classes(
        errors(case, child, anchors=[{'locator': 'analysis-routine-X', 'withheld': False}]) +
        _with_lifecycle_locator(case, child))


def _with_lifecycle_locator(case, plan):
    """A child-served claim with a preserved route and a recorded anchor must stay on route A."""
    plan = deepcopy(plan)
    plan['inputs'].append({'id': 'I9', 'provides': {'kind': 'statistical_model', 'require': {'origin': 'published'}},
                           'source': 'published', 'locator': 'published workspace', 'evidence': [], 'pin': None,
                           'status': 'located'})
    statistics = node(plan, 'search-statistics')
    plan['edges'].append({'id': 'E9', 'from': {'ref': 'I9', 'slot': 'provided'},
                          'to': {'ref': statistics['id'], 'slot': 'workspace'}, 'kind': 'statistical_model',
                          'require': {}, 'resolution': 'compatible', 'converter': None, 'acceptance': 'accepted_review'})
    plan['claims'][0]['basis_declared'] = sorted({r['element'] for r in vp.computed_bases(plan)['C1']}, key=vp.BASES.index)
    return [e for e in errors(case, plan, anchors=[{'claim': 'C1', 'withheld': False}])
            if e['error_class'] == 'in_place_retention']


def test_published_figure_claim_without_comparison():
    case, plan = drafted('requested-generator')
    figure = node(plan, 'figure-comparison')['id']
    plan['nodes'] = [n for n in plan['nodes'] if n['id'] != figure]
    plan['edges'] = [e for e in plan['edges'] if figure not in (e['from']['ref'], e['to']['ref'])]
    for row in plan['coverage']:
        row['by'] = [x for x in row['by'] if x != figure]
    assert 'published_figure_unserved' in classes(errors(case, plan))


def test_understated_basis():
    case, plan = drafted('supplied-events-search')
    plan['claims'][0]['basis_declared'] = ['supplied_inputs']
    assert 'claim_basis_understated' in classes(errors(case, plan))


def test_kind_weaker_than_artifact():
    case, plan = drafted('supplied-events-search')
    claim = plan['claims'][0]
    claim.update(kind='prediction', level='not_applicable')
    claim['statistic'] = {'source': 'not_applicable', 'definition': None, 'evidence': [], 'secondary': []}
    assert 'claim_kind_inconsistent' in classes(errors(case, plan))
    claim.update(kind='agreement')
    claim['statistic']['source'] = 'declared'
    assert 'claim_kind_inconsistent' in classes(errors(case, plan))


def test_cycle_and_size_limit():
    case, plan = drafted('supplied-events-search')
    first, second = plan['nodes'][0]['id'], plan['nodes'][1]['id']
    plan['edges'].append({'id': 'E99', 'from': {'ref': second, 'slot': 'model'}, 'to': {'ref': first, 'slot': 'cross_section'},
                          'kind': 'statistical_model', 'require': {}, 'resolution': 'compatible', 'converter': None,
                          'acceptance': 'accepted_review'})
    assert 'cycle' in classes(errors(case, plan))
    case, plan = drafted('supplied-events-search')
    plan['nodes'] = [dict(plan['nodes'][0], id=f'N{i}') for i in range(1, 130)]
    assert classes(errors(case, plan)) == {'size_limit'}


def test_rung_and_conservation_and_tools():
    case, plan = drafted('supplied-events-search')
    node(plan, 'columnar-analysis')['rung'] = 'none'
    plan['nodes'][0]['operation'] = 'model-events'
    assert 'rung_below_effects' in classes(errors(case, plan))
    case, plan = drafted('binned-yield-template')
    case.doc['dismissed'] = []
    assert 'fact_unconserved' in classes(errors(case, plan))
    case, plan = drafted('scoped-generation')
    plan['nodes'][0]['fields'] = [f for f in plan['nodes'][0]['fields'] if f['pointer'] != '/tool']
    assert 'requested_tool_unserved' in classes(errors(case, plan))


def test_critical_fields_need_a_source_or_an_anchored_default():
    case, plan = drafted('supplied-events-search')
    analysis = node(plan, 'columnar-analysis')
    analysis['fields'].append({'pointer': '/task/normalization/luminosity_ifb', 'value': 139,
                               'authority': 'agent_inference', 'evidence': None})
    assert 'critical_field_unsourced' in classes(errors(case, plan))
    analysis['fields'][-1].update(authority='adapter_default', evidence=None)
    assert 'critical_field_unsourced' in classes(errors(case, plan))
    analysis['fields'][-1].update(evidence='practice:the run luminosity of the supplied sample record')
    assert errors(case, plan) == []
    assert vp.adapter_defaults(plan) == [{'node': analysis['id'], 'operation': 'columnar-analysis',
                                          'pointer': '/task/normalization/luminosity_ifb', 'value': 139,
                                          'anchor': 'practice:the run luminosity of the supplied sample record'}]


def test_coverage_waypoints_budgets_lease_and_boundaries():
    case, plan = drafted('supplied-events-search')
    plan['coverage'] = [r for r in plan['coverage'] if r['obligation_id'] != 'O1']
    assert 'obligation_uncovered' in classes(errors(case, plan))
    case, plan = drafted('scoped-generation')
    plan['waypoints'] = [{'id': 'WP1', 'kind': 'none', 'after': None, 'before': ['N1'],
                          'criterion': 'single bounded stage', 'check': None, 'on_false': 'stop'}]
    assert errors(case, plan) == []
    assert 'waypoint_none_invalid' in classes(errors(case, plan, delegation={}))
    case, plan = drafted('supplied-events-search')
    plan['waypoints'].append({'id': 'WP9', 'kind': 'none', 'after': None, 'before': [],
                              'criterion': 'skip review', 'check': None, 'on_false': 'stop'})
    assert 'waypoint_none_invalid' in classes(errors(case, plan))
    case, plan = drafted('supplied-events-search')
    plan['aggregate_budget']['wall_seconds'] = 10
    node(plan, 'columnar-analysis')['budget']['max_seconds'] = 100
    assert 'budget_exceeds' in classes(errors(case, plan))
    assert 'delegation_exceeds' in classes(errors(case, plan, delegation={'wall_seconds': 5}))
    case, plan = drafted('tagger-method-study')
    assert 'delegation_exceeds' in classes(errors(case, plan, delegation={'authored_nodes': False}))
    case, plan = drafted('scoped-generation')
    plan['nodes'][0]['fields'].append({'pointer': '/parallel', 'value': 2, 'authority': 'user_quoted', 'evidence': None})
    assert 'lease_conflict' in classes(errors(case, plan))
    case, plan = drafted('displaced-dimuon-background')
    plan['boundaries'].append('B7')
    assert 'boundary_unjustified' in classes(errors(case, plan))


def test_unresolved_edges_need_a_witness_waypoint():
    case, plan = drafted('supplied-events-search')
    edge = next(e for e in plan['edges'] if e['to']['slot'] == 'events')
    edge['resolution'] = 'unresolved'
    assert 'edge_unresolved' in classes(errors(case, plan))
    plan['waypoints'].append({'id': 'WP9', 'kind': 'condition', 'after': None, 'before': [edge['to']['ref']],
                              'criterion': 'the witness reads the supplied event level', 'check': 'event_census',
                              'on_false': 'stop'})
    assert 'edge_unresolved' not in classes(errors(case, plan))


# --------------------------------------------------------------------------- schemas, pins, CLI
def test_schemas_use_only_evaluated_keywords():
    evaluated = {'type', 'properties', 'required', 'additionalProperties', 'enum', 'const', 'pattern', 'items',
                 'minItems', 'maxItems', 'anyOf', 'minLength', 'minimum', 'maximum'}

    def walk(schema):
        assert set(schema) <= evaluated, set(schema) - evaluated
        for value in schema.get('properties', {}).values():
            walk(value)
        for key in ('items', 'additionalProperties'):
            if isinstance(schema.get(key), dict):
                walk(schema[key])
        for option in schema.get('anyOf', ()):
            walk(option)
    for schema in (vp.READING_SCHEMA, vp.PLAN_SCHEMA, vp.SIGNATURES_SCHEMA):
        walk(schema)


def test_reading_schema_is_enforced_by_the_draft():
    case = corpus.w_mass_triplet()
    case.doc['facts'][0]['authority'] = 'agent_inference'
    with pytest.raises(ValueError, match='request-reading schema'):
        rp.draft(case.doc, case.contract())
    case = corpus.w_mass_triplet()
    with pytest.raises(ValueError, match='different prompts'):
        rp.draft(case.doc, dict(case.contract(), prompt='another request'))


def test_write_pins_the_exact_bytes(tmp_path):
    case, plan = drafted('w-mass-triplet')
    pinned = rp.write(tmp_path, plan)
    data = (tmp_path / 'inputs/plan.json').read_bytes()
    assert pinned == {'path': 'inputs/plan.json', 'sha256': hashlib.sha256(data).hexdigest()}
    assert json.loads(data) == plan


def test_cli_reports_errors_and_flags(tmp_path, capsys):
    case, plan = drafted('requested-generator')
    (tmp_path / 'reading.json').write_text(json.dumps(case.doc))
    (tmp_path / 'plan.json').write_text(json.dumps(plan))
    (tmp_path / 'contract.json').write_text(json.dumps(case.contract()))
    args = ['--reading', str(tmp_path / 'reading.json'), '--plan', str(tmp_path / 'plan.json'),
            '--contract', str(tmp_path / 'contract.json')]
    assert vp.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['errors'] == [] and any(f['flag'] == 'held' for f in report['flags'])
    plan['nodes'][0]['operation'] = 'no-such-mode'
    (tmp_path / 'plan.json').write_text(json.dumps(plan))
    assert vp.main(args) == 1


def test_claims_without_a_certifiable_route_are_flagged_with_a_proposed_route():
    case, plan = drafted('supplied-events-search')
    flag = next(f for f in vp.flags(case.doc, plan) if f['flag'] == 'no_certifiable_route')
    assert flag['ids'][0] == 'C1' and 'uncertified-proxy' in flag['text'] and 'To certify it' in flag['text']
    case = corpus.preserved_recast()
    plan = rp.draft(case.doc, case.contract(), catalogue=lambda locator: False)
    flag = next(f for f in vp.flags(case.doc, plan, catalogue=lambda x: False)
                if f['flag'] == 'not_certified_on_this_route')
    assert 'A certifiable route needs' in flag['text']
    case.doc['constraints'].append({'id': 'K9', 'type': 'blinding', 'value': {},
                                    'evidence': [case.span('Recast analysis-routine-X')]})
    assert any(f['flag'] == 'reference_withheld' for f in vp.flags(case.doc, plan, catalogue=lambda x: False))


def test_the_default_catalogue_lookup_resolves_preserved_routines(tmp_path, monkeypatch):
    from ravel import analysis_catalog
    from synthetic_catalog import build
    monkeypatch.setenv(analysis_catalog.CATALOG_ENV, str(tmp_path / 'absent.json'))
    vp._catalog.cache_clear()
    assert vp.preserved_routine('rivet:ATLAS_9001_I0001') is False
    path, catalog = build(tmp_path / 'upstream')
    monkeypatch.setenv(analysis_catalog.CATALOG_ENV, str(path))
    vp._catalog.cache_clear()
    entry = catalog['entries'][0]
    assert vp.preserved_routine(entry['id']) is True
    assert vp.preserved_routine('no routine has this name') is False
    vp._catalog.cache_clear()


def test_required_validation_ports_remain_awaited_owner_evidence(monkeypatch):
    case, original = drafted('written-note')
    operation = next(n['operation'] for n in original['nodes'] if n.get('operation'))
    registry = deepcopy(vp.registry())
    registry[operation]['consumes'].append({
        'slot': 'independent_check', 'kind': 'validation:independent-check', 'require': {'scope': 'current'}})
    monkeypatch.setattr(vp, 'registry', lambda: deepcopy(registry))
    plan = rp.draft(case.doc, case.contract(), catalogue=corpus.catalogue)
    target = node(plan, operation)
    edge = next(e for e in plan['edges'] if e['to'] == {'ref': target['id'], 'slot': 'independent_check'})
    supplied = next(i for i in plan['inputs'] if i['id'] == edge['from']['ref'])
    assert supplied['source'] == 'owner_action' and supplied['status'] == 'awaited'
    assert supplied['pin'] is None and supplied['evidence'] == []
    assert supplied['provides'] == {'kind': 'validation:independent-check', 'require': {'scope': 'current'}}
    assert not [e for e in errors(case, plan, reg=registry) if e['error_class'] == 'slot_unfilled']
    plan['edges'].remove(edge)
    assert 'slot_unfilled' in classes(errors(case, plan, reg=registry))
